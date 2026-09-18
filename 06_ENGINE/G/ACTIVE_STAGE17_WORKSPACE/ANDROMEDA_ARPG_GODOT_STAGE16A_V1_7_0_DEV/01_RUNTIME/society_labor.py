from __future__ import annotations

import copy
import json
import threading
import zipfile
from pathlib import Path
from typing import Any

from living_runtime import (
    LivingRuntime, EventEnvelope, ValidationError, IntegrityError, ConflictError,
    NotFoundError, canonical_json, sha256_text, new_runtime_id, clock_point,
)

PROFESSION_MASTER_PATH = "ANDROMEDA_CODEX_MASTER/03_DOMAINS/PROFESSIONS/02_PROFISSOES/PROFESSIONS_FUNCTIONAL_MASTER_V1_0.json"
RUNTIME_AUTHORITY = "SOCIETY_LABOR_V1_1_RUNTIME_NOT_CANON"
RELEVANT_LEGAL_EVENTS = {"COMBAT_RESOLVED", "THEFT", "ROBBERY", "ASSAULT", "KILL", "TRESPASS"}
WAGE_BASE = {"LOW":8.0,"MEDIUM":12.0,"HIGH":18.0}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo,min(hi,float(v)))


class SocietyLaborSystem:
    """Runtime law/reputation/faction/labor integration over canonical read-only data.

    This module intentionally separates canonical professions/faction presence from
    runtime law, wage, fine and productivity policies. No law is treated as canonical
    merely because the simulation needs one.
    """
    SCHEMA_VERSION=1
    EXTENSION_KEY="society_labor"
    EXTENSION_VERSION="V1.1-DEV"

    def __init__(self, runtime: LivingRuntime, world_systems: Any, social: Any, commerce: Any, *, domain_hub: Any|None=None) -> None:
        if any(getattr(x,"runtime",None) is not runtime for x in (world_systems,social,commerce)):
            raise ValidationError("society/labor dependencies must share LivingRuntime")
        self.runtime=runtime;self.world_systems=world_systems;self.social=social;self.commerce=commerce;self.domain_hub=domain_hub;self.conn=runtime.conn;self._lock=threading.RLock();self._unsubscribe=None
        self._initialize_schema();self.attach()

    def _initialize_schema(self)->None:
        with self.runtime._write_lock:
            self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS profession_snapshots(
              profession_ref TEXT PRIMARY KEY, name TEXT NOT NULL, sector TEXT NOT NULL,
              relative_remuneration TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
              source_release_sha256 TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS profession_snapshot_no_update BEFORE UPDATE ON profession_snapshots BEGIN SELECT RAISE(ABORT,'profession snapshot immutable'); END;
            CREATE TRIGGER IF NOT EXISTS profession_snapshot_no_delete BEFORE DELETE ON profession_snapshots BEGIN SELECT RAISE(ABORT,'profession snapshot immutable'); END;

            CREATE TABLE IF NOT EXISTS law_profiles(
              law_profile_id TEXT PRIMARY KEY, world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
              territory_ref TEXT NOT NULL, authority_faction_ref TEXT, profile_json TEXT NOT NULL, profile_hash TEXT NOT NULL,
              UNIQUE(world_instance_id,territory_ref)
            );
            CREATE TRIGGER IF NOT EXISTS law_profile_no_update BEFORE UPDATE ON law_profiles BEGIN SELECT RAISE(ABORT,'law profile immutable; create a new world/version to replace policy'); END;
            CREATE TRIGGER IF NOT EXISTS law_profile_no_delete BEFORE DELETE ON law_profiles BEGIN SELECT RAISE(ABORT,'law profile immutable'); END;

            CREATE TABLE IF NOT EXISTS society_event_queue(
              event_id TEXT PRIMARY KEY REFERENCES events(event_id) ON DELETE RESTRICT,
              world_instance_id TEXT NOT NULL, event_type TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('PENDING','COMPLETED','SKIPPED','FAILED')),
              result_json TEXT, result_hash TEXT, last_error TEXT
            );

            CREATE TABLE IF NOT EXISTS legal_incidents(
              incident_id TEXT PRIMARY KEY, world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
              source_event_id TEXT NOT NULL, offender_ref TEXT NOT NULL, target_ref TEXT,
              territory_ref TEXT NOT NULL, authority_faction_ref TEXT, offense TEXT NOT NULL,
              fine REAL NOT NULL, reputation_delta REAL NOT NULL, evidence_json TEXT NOT NULL,
              incident_json TEXT NOT NULL, incident_hash TEXT NOT NULL,
              UNIQUE(world_instance_id,source_event_id,offense)
            );
            CREATE TABLE IF NOT EXISTS legal_incident_status(
              incident_id TEXT PRIMARY KEY REFERENCES legal_incidents(incident_id) ON DELETE RESTRICT,
              world_instance_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('OPEN','PAID','DISMISSED')),
              paid_event_id TEXT, updated_json TEXT NOT NULL, updated_hash TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS legal_incident_no_update BEFORE UPDATE ON legal_incidents BEGIN SELECT RAISE(ABORT,'legal incident evidence immutable'); END;
            CREATE TRIGGER IF NOT EXISTS legal_incident_no_delete BEFORE DELETE ON legal_incidents BEGIN SELECT RAISE(ABORT,'legal incident evidence immutable'); END;

            CREATE TABLE IF NOT EXISTS labor_employers(
              employer_ref TEXT PRIMARY KEY, world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
              location_ref TEXT NOT NULL, territory_ref TEXT, employer_json TEXT NOT NULL, employer_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS job_offers(
              offer_id TEXT PRIMARY KEY, world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
              employer_ref TEXT NOT NULL, profession_ref TEXT NOT NULL, location_ref TEXT NOT NULL, territory_ref TEXT,
              status TEXT NOT NULL CHECK(status IN ('OPEN','FILLED','CLOSED')),
              slots_total INTEGER NOT NULL, slots_filled INTEGER NOT NULL, wage_per_shift REAL NOT NULL,
              offer_json TEXT NOT NULL, offer_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS employment_contracts(
              contract_id TEXT PRIMARY KEY, world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
              worker_ref TEXT NOT NULL, employer_ref TEXT NOT NULL, offer_id TEXT NOT NULL,
              profession_ref TEXT NOT NULL, location_ref TEXT NOT NULL, territory_ref TEXT,
              economic_category TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('ACTIVE','ENDED','ARREARS')),
              wage_per_shift REAL NOT NULL, shifts_worked INTEGER NOT NULL,
              contract_json TEXT NOT NULL, contract_hash TEXT NOT NULL
            );
            DROP INDEX IF EXISTS idx_active_contract_per_worker;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_active_contract_per_worker ON employment_contracts(world_instance_id,worker_ref) WHERE status IN ('ACTIVE','ARREARS');
            CREATE TABLE IF NOT EXISTS wage_events(
              wage_event_id TEXT PRIMARY KEY, world_instance_id TEXT NOT NULL, contract_id TEXT NOT NULL,
              source_event_id TEXT NOT NULL, amount REAL NOT NULL, wage_json TEXT NOT NULL, wage_hash TEXT NOT NULL,
              UNIQUE(world_instance_id,contract_id,source_event_id)
            );
            CREATE TRIGGER IF NOT EXISTS wage_event_no_update BEFORE UPDATE ON wage_events BEGIN SELECT RAISE(ABORT,'wage event immutable'); END;
            CREATE TRIGGER IF NOT EXISTS wage_event_no_delete BEFORE DELETE ON wage_events BEGIN SELECT RAISE(ABORT,'wage event immutable'); END;
            """)
            self.conn.execute("INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('society_labor_schema_version',?)",(str(self.SCHEMA_VERSION),))

    def attach(self)->None:
        if self._unsubscribe is not None:return
        def handler(event:EventEnvelope)->None:
            if event.event_type not in RELEVANT_LEGAL_EVENTS:return
            try:
                with self._lock,self.runtime._write_lock:self.conn.execute("INSERT OR IGNORE INTO society_event_queue(event_id,world_instance_id,event_type,status) VALUES(?,?,?,'PENDING')",(event.event_id,event.world_instance_id,event.event_type))
            except Exception:return
        self._unsubscribe=self.runtime.event_bus.subscribe(handler)
    def detach(self)->None:
        if self._unsubscribe is not None:self._unsubscribe();self._unsubscribe=None

    # ---------- profession catalog ----------
    def load_professions(self,master_release_path:str|Path)->dict[str,Any]:
        path=str(master_release_path);source_hash=self.runtime._file_sha256(path);inserted=0
        with zipfile.ZipFile(path) as z:doc=json.loads(z.read(PROFESSION_MASTER_PATH))
        profs=doc.get("professions") or []
        with self._lock,self.runtime._write_lock:
            for p in profs:
                ref=p.get("id");name=p.get("name");sector=p.get("sector") or p.get("category") or "unknown";rem=p.get("relative_remuneration") or "UNSPECIFIED"
                if not all(isinstance(x,str) and x for x in (ref,name,sector,rem)):raise IntegrityError("profession snapshot missing required data")
                text=canonical_json(p);h=sha256_text(text);row=self.conn.execute("SELECT payload_hash FROM profession_snapshots WHERE profession_ref=?",(ref,)).fetchone()
                if row:
                    if row["payload_hash"]!=h:raise IntegrityError("profession snapshot drift")
                    continue
                self.conn.execute("INSERT INTO profession_snapshots VALUES(?,?,?,?,?,?,?)",(ref,name,sector,rem,text,h,source_hash));inserted+=1
        return {"status":"PASS","count":len(profs),"inserted":inserted,"authority":"MASTER_READ_ONLY_PROFESSION_SNAPSHOT"}

    def profession(self,profession_ref:str)->dict[str,Any]:
        row=self.conn.execute("SELECT payload_json,payload_hash FROM profession_snapshots WHERE profession_ref=?",(profession_ref,)).fetchone()
        if not row:raise NotFoundError("profession not loaded")
        if sha256_text(row["payload_json"])!=row["payload_hash"]:raise IntegrityError("profession snapshot hash mismatch")
        return json.loads(row["payload_json"])

    @staticmethod
    def _economic_category(prof:dict[str,Any])->str:
        text=(str(prof.get("sector",""))+" "+str(prof.get("category",""))).lower()
        if any(x in text for x in ["agr", "rural", "pecu", "alimenta", "colheita"]):return "FOOD"
        if any(x in text for x in ["saúde","medic","farm"]):return "MEDICAL"
        if any(x in text for x in ["tecn", "comunica", "rede", "dados", "análise", "inteligência"]):return "TECHNOLOGY"
        if any(x in text for x in ["indústria","manufatura","oficina","manutenção","reparo","fabricação"]):return "MATERIAL"
        return "GENERAL"

    @staticmethod
    def _wage_for(prof:dict[str,Any])->float:
        r=str(prof.get("relative_remuneration","")).upper().replace("É","E")
        if "ALTA" in r:return WAGE_BASE["HIGH"]
        if "BAIX" in r:return WAGE_BASE["LOW"]
        return WAGE_BASE["MEDIUM"]

    def _territory_for_location(self,location_ref:str|None)->str|None:
        if not isinstance(location_ref,str):return None
        loc=self.world_systems.resolve_location(location_ref)
        return loc.get("territory_ref")

    # ---------- law / faction ----------
    def configure_law_profile(self,world_instance_id:str,territory_ref:str,*,authority_faction_ref:str|None=None,protected_species:list[str]|None=None,rules:dict[str,dict[str,Any]]|None=None)->dict[str,Any]:
        self.runtime.get_world(world_instance_id)
        if not self.runtime.canonical_ref_resolves(territory_ref):raise ValidationError("territory_ref must be canonical")
        if authority_faction_ref is not None and not self.runtime.canonical_ref_resolves(authority_faction_ref):raise ValidationError("authority_faction_ref must be canonical")
        protected=sorted(set(protected_species or []))
        for s in protected:
            if not self.runtime.canonical_ref_resolves(s):raise ValidationError(f"unknown protected species: {s}")
        default_rules={
            "ASSAULT":{"prohibited":True,"fine":40.0,"reputation_delta":-8.0,"witness_required":True},
            "HOMICIDE":{"prohibited":True,"fine":200.0,"reputation_delta":-35.0,"witness_required":True},
            "THEFT":{"prohibited":True,"fine":60.0,"reputation_delta":-12.0,"witness_required":True},
            "ROBBERY":{"prohibited":True,"fine":100.0,"reputation_delta":-20.0,"witness_required":True},
            "WILDLIFE_KILL":{"prohibited":True,"fine":50.0,"reputation_delta":-10.0,"witness_required":True,"protected_only":True},
        }
        merged=copy.deepcopy(default_rules)
        if rules:
            for k,v in rules.items():
                if k not in merged or not isinstance(v,dict):raise ValidationError("unsupported/invalid runtime law rule")
                merged[k].update(copy.deepcopy(v))
        for name,r in merged.items():
            r["prohibited"]=bool(r.get("prohibited",False));r["witness_required"]=bool(r.get("witness_required",True));r["fine"]=_clamp(float(r.get("fine",0)),0,1_000_000);r["reputation_delta"]=_clamp(float(r.get("reputation_delta",0)),-100,100)
        pid=new_runtime_id("lawprofile");body={"law_profile_id":pid,"world_instance_id":world_instance_id,"territory_ref":territory_ref,"authority_faction_ref":authority_faction_ref,"protected_species":protected,"rules":merged,"authority":RUNTIME_AUTHORITY,"canon_status":"NOT_CANON_RUNTIME_POLICY"};text=canonical_json(body);h=sha256_text(text)
        with self._lock,self.runtime._write_lock:
            if self.conn.execute("SELECT 1 FROM law_profiles WHERE world_instance_id=? AND territory_ref=?",(world_instance_id,territory_ref)).fetchone():raise ConflictError("runtime law profile already configured for territory")
            self.conn.execute("INSERT INTO law_profiles VALUES(?,?,?,?,?,?)",(pid,world_instance_id,territory_ref,authority_faction_ref,text,h))
        body["profile_hash"]=h;return body

    def _law(self,wid:str,territory:str)->dict[str,Any]|None:
        row=self.conn.execute("SELECT profile_json,profile_hash FROM law_profiles WHERE world_instance_id=? AND territory_ref=?",(wid,territory)).fetchone()
        if not row:return None
        if sha256_text(row["profile_json"])!=row["profile_hash"]:raise IntegrityError("law profile hash mismatch")
        return json.loads(row["profile_json"])

    def _entity_territory(self,wid:str,ref:str|None)->str|None:
        if not isinstance(ref,str):return None
        if ref.startswith("rt:"):
            try:e=self.runtime.get_entity(wid,ref)
            except NotFoundError:return None
            d=e.get("data") or {};eco=d.get("ecology") if isinstance(d.get("ecology"),dict) else {}
            t=eco.get("territory_ref") or d.get("territory_ref")
            if isinstance(t,str):return t
            return self._territory_for_location(d.get("location_ref") or d.get("poi_ref") or d.get("site_ref"))
        return self._territory_for_location(ref)

    def _event_record(self,event_id:str)->dict[str,Any]:
        row=self.conn.execute("SELECT * FROM events WHERE event_id=?",(event_id,)).fetchone()
        if not row:raise NotFoundError("event not found")
        return {"event_id":row["event_id"],"world_instance_id":row["world_instance_id"],"event_type":row["event_type"],"subjects":json.loads(row["subjects_json"]),"payload":json.loads(row["payload_json"])}

    def _classify_offense(self,e:dict[str,Any])->tuple[str|None,str|None]:
        params=(e.get("payload") or {}).get("parameters") or {};target=params.get("target_ref")
        if e["event_type"]=="COMBAT_RESOLVED":
            if not isinstance(target,str):return None,None
            try:t=self.runtime.get_entity(e["world_instance_id"],target)
            except NotFoundError:return None,target
            if t.get("entity_kind")=="AGENT":return ("HOMICIDE" if bool(params.get("lethal")) else "ASSAULT"),target
            if t.get("entity_kind") in {"ANIMAL","CREATURE"} and bool(params.get("lethal")):return "WILDLIFE_KILL",target
            return None,target
        if e["event_type"] in {"THEFT","ROBBERY","ASSAULT"}:return e["event_type"],target
        if e["event_type"]=="KILL":return "HOMICIDE",target
        return None,target

    def _witnesses(self,wid:str,event_id:str,offender:str)->list[str]:
        rows=self.conn.execute("SELECT agent_ref,memory_json,memory_hash FROM social_memories WHERE world_instance_id=? AND linked_event_id=? ORDER BY agent_ref",(wid,event_id)).fetchall();out=[]
        for r in rows:
            if sha256_text(r["memory_json"])!=r["memory_hash"]:raise IntegrityError("witness memory hash mismatch")
            if r["agent_ref"]!=offender:out.append(r["agent_ref"])
        return sorted(set(out))

    def _faction_runtime(self,wid:str,faction_ref:str|None)->dict[str,Any]|None:
        if not faction_ref:return None
        try:return self.world_systems._entity_for(wid,"FACTION_RUNTIME",faction_ref)
        except NotFoundError:return None

    def _record_queue_result(self,event_id:str,status:str,result:dict[str,Any],err:str|None=None)->None:
        text=canonical_json(result);h=sha256_text(text)
        with self._lock,self.runtime._write_lock:self.conn.execute("UPDATE society_event_queue SET status=?,result_json=?,result_hash=?,last_error=? WHERE event_id=?",(status,text,h,err,event_id))

    def drain_legal_events(self,world_instance_id:str)->dict[str,Any]:
        if self.domain_hub is not None:self.domain_hub.drain_pending(world_instance_id)
        with self._lock,self.runtime._write_lock:
            self.conn.execute("""INSERT OR IGNORE INTO society_event_queue(event_id,world_instance_id,event_type,status)
                               SELECT event_id,world_instance_id,event_type,'PENDING' FROM events WHERE world_instance_id=? AND event_type IN ('COMBAT_RESOLVED','THEFT','ROBBERY','ASSAULT','KILL','TRESPASS')""",(world_instance_id,))
        rows=self.conn.execute("SELECT event_id FROM society_event_queue WHERE world_instance_id=? AND status='PENDING' ORDER BY rowid",(world_instance_id,)).fetchall();results=[]
        for row in rows:
            try:
                e=self._event_record(row["event_id"]);offender=next((s for s in e["subjects"] if isinstance(s,str) and s.startswith("rt:")),None);offense,target=self._classify_offense(e)
                if not offender or not offense:
                    result={"event_id":e["event_id"],"status":"SKIPPED","reason":"NO_APPLICABLE_OFFENSE"};self._record_queue_result(e["event_id"],"SKIPPED",result);results.append(result);continue
                territory=self._entity_territory(world_instance_id,target) or self._entity_territory(world_instance_id,offender)
                if not territory:
                    result={"event_id":e["event_id"],"status":"SKIPPED","reason":"JURISDICTION_UNRESOLVED"};self._record_queue_result(e["event_id"],"SKIPPED",result);results.append(result);continue
                law=self._law(world_instance_id,territory)
                if not law:
                    result={"event_id":e["event_id"],"status":"SKIPPED","reason":"NO_RUNTIME_LAW_PROFILE","territory_ref":territory};self._record_queue_result(e["event_id"],"SKIPPED",result);results.append(result);continue
                rule=law["rules"].get(offense) or {}
                if not bool(rule.get("prohibited")):
                    result={"event_id":e["event_id"],"status":"SKIPPED","reason":"OFFENSE_NOT_PROHIBITED","offense":offense};self._record_queue_result(e["event_id"],"SKIPPED",result);results.append(result);continue
                if offense=="WILDLIFE_KILL" and bool(rule.get("protected_only",True)):
                    try:species=(self.runtime.get_entity(world_instance_id,target).get("data") or {}).get("species_ref")
                    except Exception:species=None
                    if species not in law.get("protected_species",[]):
                        result={"event_id":e["event_id"],"status":"SKIPPED","reason":"WILDLIFE_NOT_PROTECTED","species_ref":species};self._record_queue_result(e["event_id"],"SKIPPED",result);results.append(result);continue
                witnesses=self._witnesses(world_instance_id,e["event_id"],offender)
                if bool(rule.get("witness_required",True)) and not witnesses:
                    result={"event_id":e["event_id"],"status":"SKIPPED","reason":"NO_DIRECT_EVIDENCE","offense":offense,"territory_ref":territory};self._record_queue_result(e["event_id"],"SKIPPED",result);results.append(result);continue
                existing=self.conn.execute("SELECT incident_json,incident_hash FROM legal_incidents WHERE world_instance_id=? AND source_event_id=? AND offense=?",(world_instance_id,e["event_id"],offense)).fetchone()
                if existing:
                    if sha256_text(existing["incident_json"])!=existing["incident_hash"]:raise IntegrityError("legal incident hash mismatch")
                    incident=json.loads(existing["incident_json"])
                else:
                    iid=new_runtime_id("incident");evidence={"witness_refs":witnesses,"witness_count":len(witnesses),"source_event_id":e["event_id"],"evidence_model":"DIRECT_MEMORY_ONLY_V1_1"};fine=float(rule.get("fine",0));repdelta=float(rule.get("reputation_delta",0));incident={"incident_id":iid,"world_instance_id":world_instance_id,"source_event_id":e["event_id"],"offender_ref":offender,"target_ref":target,"territory_ref":territory,"authority_faction_ref":law.get("authority_faction_ref"),"offense":offense,"fine":fine,"reputation_delta":repdelta,"evidence":evidence,"authority":RUNTIME_AUTHORITY};text=canonical_json(incident);h=sha256_text(text)
                    with self._lock,self.runtime._write_lock:
                        self.conn.execute("INSERT INTO legal_incidents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(iid,world_instance_id,e["event_id"],offender,target,territory,law.get("authority_faction_ref"),offense,fine,repdelta,canonical_json(evidence),text,h))
                        st={"incident_id":iid,"status":"OPEN","paid_event_id":None,"authority":RUNTIME_AUTHORITY};stt=canonical_json(st);sth=sha256_text(stt);self.conn.execute("INSERT INTO legal_incident_status VALUES(?,?,?,?,?,?)",(iid,world_instance_id,"OPEN",None,stt,sth))
                    incident["incident_hash"]=h
                    fac=law.get("authority_faction_ref")
                    if fac and repdelta!=0:
                        self.social.apply_reputation_delta(world_instance_id,offender,repdelta,scope_type="FACTION",scope_ref=fac,reason=f"legal:{offense}",source_event_id=e["event_id"],idempotency_key=f"legal-rep:{iid}")
                    fr=self._faction_runtime(world_instance_id,fac)
                    if fr:
                        pressure=min(100.0,float(fr["data"].get("legal_pressure",0.0))+min(20.0,abs(repdelta)*0.5+5.0));w=self.runtime.get_world(world_instance_id);c=w["clock_state"];a={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":world_instance_id,"timeline_id":w["timeline_id"],"actor_ref":"SYSTEM_RECONCILIATION","action_type":"LEGAL_PRESSURE_CHANGED","parameters":{"incident_id":iid,"offense":offense,"authority":RUNTIME_AUTHORITY},"precondition_snapshot":{"entity_versions":{fr["entity_runtime_id"]:fr["version"]}},"idempotency_key":f"legal-pressure:{iid}","created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"SYSTEM_RECONCILIATION","execution_class":"ROUTINE_SAFE"};self.runtime.apply_action(world_instance_id,a,[{"target_ref":fr["entity_runtime_id"],"operation":"SET","field_path":"data.legal_pressure","value":round(pressure,4),"priority":0,"kind":"DERIVED"}])
                result={"event_id":e["event_id"],"status":"COMPLETED","incident":incident};self._record_queue_result(e["event_id"],"COMPLETED",result);results.append(result)
            except Exception as exc:
                result={"event_id":row["event_id"],"status":"FAILED","error":str(exc)};self._record_queue_result(row["event_id"],"FAILED",result,str(exc));results.append(result)
        return {"status":"PASS" if not any(x["status"]=="FAILED" for x in results) else "FAIL","processed":len(results),"results":results}

    def incident_status(self,incident_id:str)->dict[str,Any]:
        row=self.conn.execute("SELECT updated_json,updated_hash FROM legal_incident_status WHERE incident_id=?",(incident_id,)).fetchone()
        if not row:raise NotFoundError("incident status not found")
        if sha256_text(row["updated_json"])!=row["updated_hash"]:raise IntegrityError("incident status hash mismatch")
        return json.loads(row["updated_json"])

    def pay_fine(self,world_instance_id:str,incident_id:str)->dict[str,Any]:
        row=self.conn.execute("SELECT * FROM legal_incidents WHERE incident_id=? AND world_instance_id=?",(incident_id,world_instance_id)).fetchone()
        if not row:raise NotFoundError("incident not found")
        status=self.incident_status(incident_id)
        if status["status"]!="OPEN":raise ConflictError("incident is not open")
        if not row["authority_faction_ref"]:raise ConflictError("incident has no runtime faction treasury")
        account=self.commerce.create_account(world_instance_id,row["offender_ref"]);wallet=self.runtime.get_entity(world_instance_id,account["wallet_runtime_id"]);fac=self._faction_runtime(world_instance_id,row["authority_faction_ref"])
        if not fac:raise ConflictError("authority faction runtime projection missing")
        fine=float(row["fine"])
        if float(wallet["data"]["balance"])<fine:raise ConflictError("insufficient funds for fine")
        w=self.runtime.get_world(world_instance_id);c=w["clock_state"];action={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":world_instance_id,"timeline_id":w["timeline_id"],"actor_ref":row["offender_ref"],"action_type":"LEGAL_FINE_PAID","parameters":{"incident_id":incident_id,"amount":fine,"authority_faction_ref":row["authority_faction_ref"],"authority":RUNTIME_AUTHORITY},"precondition_snapshot":{"entity_versions":{wallet["entity_runtime_id"]:wallet["version"],fac["entity_runtime_id"]:fac["version"]}},"idempotency_key":f"fine:{incident_id}","created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"ACTION","execution_class":"ACTIVE_ONLY"}
        r=self.runtime.apply_action(world_instance_id,action,[{"target_ref":wallet["entity_runtime_id"],"operation":"DECREMENT","field_path":"data.balance","amount":fine,"priority":0,"kind":"DIRECT"},{"target_ref":fac["entity_runtime_id"],"operation":"INCREMENT","field_path":"data.treasury","amount":fine,"priority":1,"kind":"DIRECT"}])
        new={"incident_id":incident_id,"status":"PAID","paid_event_id":r["event_id"],"authority":RUNTIME_AUTHORITY};text=canonical_json(new);h=sha256_text(text)
        with self._lock,self.runtime._write_lock:self.conn.execute("UPDATE legal_incident_status SET status='PAID',paid_event_id=?,updated_json=?,updated_hash=? WHERE incident_id=?",(r["event_id"],text,h,incident_id))
        return {"status":"PASS","event_id":r["event_id"],"incident":new}

    # ---------- labor ----------
    def create_employer(self,world_instance_id:str,location_ref:str,*,starting_cash:float=1000.0,name:str="Runtime Employer")->dict[str,Any]:
        if not self.runtime.canonical_ref_resolves(location_ref):raise ValidationError("employer location must be canonical")
        territory=self._territory_for_location(location_ref);w=self.runtime.get_world(world_instance_id);c=w["clock_state"];eid=new_runtime_id("employer")
        state={"state_id":new_runtime_id("state"),"world_instance_id":world_instance_id,"timeline_id":w["timeline_id"],"entity_runtime_id":eid,"origin":"RUNTIME_BORN","entity_kind":"EMPLOYER","lifecycle":"ACTIVE","version":0,"updated_at":clock_point(c["day"],c["tick"]),"data":{"name":name,"location_ref":location_ref,"territory_ref":territory,"cash_balance":float(starting_cash),"authority":RUNTIME_AUTHORITY},"protection":{}}
        self.runtime.register_entity(world_instance_id,state);body={"employer_ref":eid,"world_instance_id":world_instance_id,"location_ref":location_ref,"territory_ref":territory,"name":name,"authority":RUNTIME_AUTHORITY};text=canonical_json(body);h=sha256_text(text)
        with self._lock,self.runtime._write_lock:self.conn.execute("INSERT INTO labor_employers VALUES(?,?,?,?,?,?)",(eid,world_instance_id,location_ref,territory,text,h))
        return self.runtime.get_entity(world_instance_id,eid)

    def create_job_offer(self,world_instance_id:str,employer_ref:str,profession_ref:str,*,slots:int=1,wage_per_shift:float|None=None)->dict[str,Any]:
        if not isinstance(slots,int) or slots<=0:raise ValidationError("slots must be positive integer")
        employer=self.runtime.get_entity(world_instance_id,employer_ref)
        if employer.get("entity_kind") not in {"EMPLOYER","VENDOR"} or employer.get("lifecycle")!="ACTIVE":raise ValidationError("invalid active employer")
        prof=self.profession(profession_ref);location=(employer.get("data") or {}).get("location_ref");territory=self._territory_for_location(location)
        dist=prof.get("territory_distribution") or {};pois=set(dist.get("poi_ids") or []);ters=set(dist.get("territory_ids") or [])
        if location not in pois and territory not in ters:raise ConflictError("profession is not canonically distributed at employer location/territory")
        wage=float(self._wage_for(prof) if wage_per_shift is None else wage_per_shift)
        if wage<=0:raise ValidationError("wage must be positive")
        oid=new_runtime_id("joboffer");body={"offer_id":oid,"world_instance_id":world_instance_id,"employer_ref":employer_ref,"profession_ref":profession_ref,"profession_name":prof.get("name"),"location_ref":location,"territory_ref":territory,"economic_category":self._economic_category(prof),"slots_total":slots,"slots_filled":0,"wage_per_shift":wage,"status":"OPEN","wage_authority":"RUNTIME_BALANCE_NOT_CANON","profession_authority":"MASTER_READ_ONLY"};text=canonical_json(body);h=sha256_text(text)
        with self._lock,self.runtime._write_lock:self.conn.execute("INSERT INTO job_offers VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(oid,world_instance_id,employer_ref,profession_ref,location,territory,"OPEN",slots,0,wage,text,h))
        body["offer_hash"]=h;return body

    def _offer(self,offer_id:str)->dict[str,Any]:
        row=self.conn.execute("SELECT offer_json,offer_hash,status,slots_filled FROM job_offers WHERE offer_id=?",(offer_id,)).fetchone()
        if not row:raise NotFoundError("job offer not found")
        if sha256_text(row["offer_json"])!=row["offer_hash"]:raise IntegrityError("job offer base hash mismatch")
        b=json.loads(row["offer_json"]);b["status"]=row["status"];b["slots_filled"]=row["slots_filled"];return b

    def accept_job(self,world_instance_id:str,worker_ref:str,offer_id:str)->dict[str,Any]:
        worker=self.runtime.get_entity(world_instance_id,worker_ref)
        if worker.get("entity_kind")!="AGENT" or worker.get("lifecycle")!="ACTIVE":raise ValidationError("worker must be active AGENT")
        travel=(worker.get("data") or {}).get("travel") if isinstance((worker.get("data") or {}).get("travel"),dict) else {}
        if travel.get("status")=="IN_TRANSIT":raise ConflictError("worker cannot accept job while in transit")
        offer=self._offer(offer_id)
        if offer["world_instance_id"]!=world_instance_id or offer["status"]!="OPEN" or int(offer["slots_filled"])>=int(offer["slots_total"]):raise ConflictError("job offer unavailable")
        if (worker.get("data") or {}).get("location_ref")!=offer["location_ref"]:raise ConflictError("worker is not at employer location")
        if self.conn.execute("SELECT 1 FROM employment_contracts WHERE world_instance_id=? AND worker_ref=? AND status IN ('ACTIVE','ARREARS')",(world_instance_id,worker_ref)).fetchone():raise ConflictError("worker already has active contract")
        # Paid employment must always have an explicit runtime monetary destination.
        # This is an operational account only; it does not create or alter canonical currency facts.
        account=self.commerce.create_account(world_instance_id,worker_ref)
        cid=new_runtime_id("contract");body={"contract_id":cid,"world_instance_id":world_instance_id,"worker_ref":worker_ref,"employer_ref":offer["employer_ref"],"offer_id":offer_id,"profession_ref":offer["profession_ref"],"location_ref":offer["location_ref"],"territory_ref":offer["territory_ref"],"economic_category":offer["economic_category"],"status":"ACTIVE","wage_per_shift":offer["wage_per_shift"],"shifts_worked":0,"wallet_runtime_id":account["wallet_runtime_id"],"authority":RUNTIME_AUTHORITY};text=canonical_json(body);h=sha256_text(text)
        w=self.runtime.get_world(world_instance_id);c=w["clock_state"];action={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":world_instance_id,"timeline_id":w["timeline_id"],"actor_ref":worker_ref,"action_type":"EMPLOYMENT_ACCEPTED","parameters":{"contract_id":cid,"profession_ref":offer["profession_ref"],"employer_ref":offer["employer_ref"],"wallet_runtime_id":account["wallet_runtime_id"],"authority":RUNTIME_AUTHORITY},"precondition_snapshot":{"entity_versions":{worker_ref:worker["version"]}},"idempotency_key":f"employment:{worker_ref}:{offer_id}","created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"ACTION","execution_class":"ACTIVE_ONLY"}
        self.runtime.apply_action(world_instance_id,action,[{"target_ref":worker_ref,"operation":"SET","field_path":"data.employment","value":{"contract_id":cid,"profession_ref":offer["profession_ref"],"employer_ref":offer["employer_ref"],"location_ref":offer["location_ref"],"wallet_runtime_id":account["wallet_runtime_id"],"status":"ACTIVE","authority":RUNTIME_AUTHORITY},"priority":0,"kind":"DIRECT"}])
        with self._lock,self.runtime._write_lock:
            self.conn.execute("INSERT INTO employment_contracts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(cid,world_instance_id,worker_ref,offer["employer_ref"],offer_id,offer["profession_ref"],offer["location_ref"],offer["territory_ref"],offer["economic_category"],"ACTIVE",offer["wage_per_shift"],0,text,h))
            filled=int(offer["slots_filled"])+1;status="FILLED" if filled>=int(offer["slots_total"]) else "OPEN";self.conn.execute("UPDATE job_offers SET slots_filled=?,status=? WHERE offer_id=?",(filled,status,offer_id))
        body["contract_hash"]=h;return body

    def _contract(self,contract_id:str)->dict[str,Any]:
        row=self.conn.execute("SELECT * FROM employment_contracts WHERE contract_id=?",(contract_id,)).fetchone()
        if not row:raise NotFoundError("employment contract not found")
        if sha256_text(row["contract_json"])!=row["contract_hash"]:raise IntegrityError("employment contract base hash mismatch")
        b=json.loads(row["contract_json"]);b["status"]=row["status"];b["shifts_worked"]=row["shifts_worked"];return b

    def reconcile_employment_lifecycle(self,world_instance_id:str)->dict[str,Any]:
        """End employment when the worker is no longer an active living agent.

        This closes a cross-domain lifecycle gap: death/archival cannot leave a paid
        contract occupying a job slot forever. Contract history remains preserved.
        """
        rows=self.conn.execute("SELECT contract_id,worker_ref,offer_id,status FROM employment_contracts WHERE world_instance_id=? AND status IN ('ACTIVE','ARREARS') ORDER BY contract_id",(world_instance_id,)).fetchall()
        ended=[]
        for row in rows:
            try:worker=self.runtime.get_entity(world_instance_id,row["worker_ref"])
            except Exception:worker=None
            if worker is not None and worker.get("lifecycle")=="ACTIVE":continue
            event_id=None
            if worker is not None:
                w=self.runtime.get_world(world_instance_id);c=w["clock_state"];employment=(worker.get("data") or {}).get("employment") if isinstance((worker.get("data") or {}).get("employment"),dict) else {}
                if employment.get("status")!="ENDED":
                    action={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":world_instance_id,"timeline_id":w["timeline_id"],"actor_ref":"SYSTEM_RECONCILIATION","action_type":"EMPLOYMENT_ENDED_BY_LIFECYCLE","parameters":{"contract_id":row["contract_id"],"worker_lifecycle":worker.get("lifecycle"),"authority":RUNTIME_AUTHORITY},"precondition_snapshot":{"entity_versions":{worker["entity_runtime_id"]:worker["version"]}},"idempotency_key":f"employment-end-lifecycle:{row['contract_id']}","created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"SYSTEM_RECONCILIATION","execution_class":"ROUTINE_SAFE"}
                    result=self.runtime.apply_action(world_instance_id,action,[{"target_ref":worker["entity_runtime_id"],"operation":"SET","field_path":"data.employment.status","value":"ENDED","priority":0,"kind":"DERIVED"}]);event_id=result["event_id"]
            with self._lock,self.runtime._write_lock:
                self.conn.execute("UPDATE employment_contracts SET status='ENDED' WHERE contract_id=? AND status IN ('ACTIVE','ARREARS')",(row["contract_id"],))
                offer=self.conn.execute("SELECT slots_total,slots_filled,status FROM job_offers WHERE offer_id=?",(row["offer_id"],)).fetchone()
                if offer:
                    filled=max(0,int(offer["slots_filled"])-1);status="OPEN" if filled<int(offer["slots_total"]) else "FILLED";self.conn.execute("UPDATE job_offers SET slots_filled=?,status=? WHERE offer_id=?",(filled,status,row["offer_id"]))
            ended.append({"contract_id":row["contract_id"],"worker_ref":row["worker_ref"],"previous_status":row["status"],"event_id":event_id,"status":"ENDED"})
        return {"status":"PASS","ended":len(ended),"contracts":ended,"authority":RUNTIME_AUTHORITY}

    def work_shift(self,world_instance_id:str,contract_id:str)->dict[str,Any]:
        contract=self._contract(contract_id)
        if contract["world_instance_id"]!=world_instance_id or contract["status"]!="ACTIVE":raise ConflictError("contract is not active")
        worker=self.runtime.get_entity(world_instance_id,contract["worker_ref"]);employer=self.runtime.get_entity(world_instance_id,contract["employer_ref"]);wd=worker.get("data") or {}
        travel=wd.get("travel") if isinstance(wd.get("travel"),dict) else {}
        if travel.get("status")=="IN_TRANSIT":raise ConflictError("worker cannot work while in transit")
        if wd.get("location_ref")!=contract["location_ref"]:raise ConflictError("worker is not at work location")
        if float((employer.get("data") or {}).get("cash_balance",0))<float(contract["wage_per_shift"]):
            with self._lock,self.runtime._write_lock:self.conn.execute("UPDATE employment_contracts SET status='ARREARS' WHERE contract_id=?",(contract_id,))
            raise ConflictError("employer cannot fund wage; contract entered ARREARS")
        account=self.commerce.create_account(world_instance_id,contract["worker_ref"]);wallet=self.runtime.get_entity(world_instance_id,account["wallet_runtime_id"]);wage=float(contract["wage_per_shift"]);w=self.runtime.get_world(world_instance_id);c=w["clock_state"]
        action={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":world_instance_id,"timeline_id":w["timeline_id"],"actor_ref":contract["worker_ref"],"action_type":"WORK_SHIFT_COMPLETED","parameters":{"contract_id":contract_id,"profession_ref":contract["profession_ref"],"wage":wage,"authority":RUNTIME_AUTHORITY},"precondition_snapshot":{"entity_versions":{wallet["entity_runtime_id"]:wallet["version"],employer["entity_runtime_id"]:employer["version"],worker["entity_runtime_id"]:worker["version"]}},"idempotency_key":f"shift:{contract_id}:{contract['shifts_worked']}","created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"ACTION","execution_class":"ACTIVE_ONLY"}
        r=self.runtime.apply_action(world_instance_id,action,[{"target_ref":employer["entity_runtime_id"],"operation":"DECREMENT","field_path":"data.cash_balance","amount":wage,"priority":0,"kind":"DIRECT"},{"target_ref":wallet["entity_runtime_id"],"operation":"INCREMENT","field_path":"data.balance","amount":wage,"priority":1,"kind":"DIRECT"},{"target_ref":worker["entity_runtime_id"],"operation":"SET","field_path":"data.employment.shifts_worked","value":int(contract["shifts_worked"])+1,"priority":2,"kind":"DIRECT"}])
        wid=new_runtime_id("wage");body={"wage_event_id":wid,"world_instance_id":world_instance_id,"contract_id":contract_id,"source_event_id":r["event_id"],"amount":wage,"profession_ref":contract["profession_ref"],"authority":RUNTIME_AUTHORITY};text=canonical_json(body);h=sha256_text(text)
        with self._lock,self.runtime._write_lock:
            self.conn.execute("INSERT INTO wage_events VALUES(?,?,?,?,?,?,?)",(wid,world_instance_id,contract_id,r["event_id"],wage,text,h));self.conn.execute("UPDATE employment_contracts SET shifts_worked=shifts_worked+1 WHERE contract_id=?",(contract_id,))
        return {"status":"PASS","event_id":r["event_id"],"wage_event":body,"balance":self.commerce.account_state(world_instance_id,contract["worker_ref"])["balance"]}

    def labor_tick(self,world_instance_id:str,*,tick_key:str)->dict[str,Any]:
        contracts=[self._contract(r["contract_id"]) for r in self.conn.execute("SELECT contract_id FROM employment_contracts WHERE world_instance_id=? AND status='ACTIVE' ORDER BY contract_id",(world_instance_id,)).fetchall()]
        counts:dict[tuple[str|None,str],int]={}
        for c in contracts:counts[(c.get("territory_ref"),c.get("economic_category","GENERAL"))]=counts.get((c.get("territory_ref"),c.get("economic_category","GENERAL")),0)+1
        flows=self.world_systems._entities(world_instance_id,"ECONOMIC_FLOW");cons=[];targets=[];metrics=[]
        for flow in flows:
            d=flow["data"];territory=d.get("destination_territory_ref");cat=d.get("product_category","GENERAL");workers=counts.get((territory,cat),0);general=counts.get((territory,"GENERAL"),0);factor=round(min(1.5,1.0+workers*0.03+general*0.01),4);targets.append(flow);cons.append({"target_ref":flow["entity_runtime_id"],"operation":"SET","field_path":"data.labor_factor","value":factor,"priority":len(cons),"kind":"DERIVED"});metrics.append({"flow_ref":d["flow_ref"],"territory_ref":territory,"product_category":cat,"matched_workers":workers,"general_workers":general,"labor_factor":factor})
        if not targets:return {"status":"PASS","event_id":None,"metrics":[]}
        r=self.world_systems._action(world_instance_id,"LABOR_PRODUCTIVITY_RECONCILED",tick_key,targets,cons,suffix="labor")
        return {"status":"PASS","event_id":r["event_id"],"metrics":metrics,"authority":RUNTIME_AUTHORITY}

    def extension_handler(self,context:dict[str,Any])->dict[str,Any]:
        wid=context["world_instance_id"];lifecycle=self.reconcile_employment_lifecycle(wid);legal=self.drain_legal_events(wid);labor=self.labor_tick(wid,tick_key=f"labor:{context['tick_key']}")
        return {"status":"PASS" if legal["status"]=="PASS" and lifecycle["status"]=="PASS" else "FAIL","authority":RUNTIME_AUTHORITY,"employment_lifecycle":lifecycle,"legal":legal,"labor":labor}
    def attach_to_orchestrator(self,orchestrator:Any,world_instance_id:str)->dict[str,Any]:
        return orchestrator.attach_extension(world_instance_id,self.EXTENSION_KEY,self.extension_handler,version=self.EXTENSION_VERSION,modes={"FULL","ACTIVE","AGGREGATE","ROUTINE_OFFLINE"},cadence_ticks=1,routine_safe=True)

    def full_integrity_check(self,world_instance_id:str)->dict[str,Any]:
        failures=[]
        with self.runtime._write_lock:
            for table,j,h,where,args in [
                ("profession_snapshots","payload_json","payload_hash","1=1",()),
                ("law_profiles","profile_json","profile_hash","world_instance_id=?",(world_instance_id,)),
                ("legal_incidents","incident_json","incident_hash","world_instance_id=?",(world_instance_id,)),
                ("legal_incident_status","updated_json","updated_hash","world_instance_id=?",(world_instance_id,)),
                ("labor_employers","employer_json","employer_hash","world_instance_id=?",(world_instance_id,)),
                ("job_offers","offer_json","offer_hash","world_instance_id=?",(world_instance_id,)),
                ("employment_contracts","contract_json","contract_hash","world_instance_id=?",(world_instance_id,)),
                ("wage_events","wage_json","wage_hash","world_instance_id=?",(world_instance_id,)),
            ]:
                for r in self.conn.execute(f"SELECT rowid,{j},{h} FROM {table} WHERE {where}",args).fetchall():
                    if sha256_text(r[j])!=r[h]:failures.append(f"{table}:HASH:{r['rowid']}")
            for r in self.conn.execute("SELECT event_id,status,result_json,result_hash FROM society_event_queue WHERE world_instance_id=?",(world_instance_id,)).fetchall():
                if r["result_json"] is not None and sha256_text(r["result_json"])!=r["result_hash"]:failures.append(f"society_event_queue:HASH:{r['event_id']}")
                if r["status"]=="FAILED":failures.append(f"society_event_queue:FAILED:{r['event_id']}")
        replay=self.runtime.compare_replay_to_materialized(world_instance_id)
        if replay["status"]!="PASS":failures.append("REPLAY_MISMATCH")
        return {"status":"PASS" if not failures else "FAIL","failures":failures,"replay":replay,"authority":RUNTIME_AUTHORITY}
