from __future__ import annotations

import copy, json, math, threading
from typing import Any

from living_runtime import (
    LivingRuntime, ValidationError, IntegrityError, ConflictError, NotFoundError,
    canonical_json, sha256_text, new_runtime_id, clock_point,
)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _abs_tick(clock: dict[str, Any]) -> int:
    return int(clock["day"]) * int(clock["ticks_per_day"]) + int(clock["tick"])


class LongHorizonSimulation:
    """Conservative long-horizon/offline simulator.

    Authority boundary:
      * no individual NPC/animal decisions offline;
      * only ROUTINE_SAFE aggregate processes are advanced;
      * Canon remains read-only;
      * absolute universe day/tick is authoritative chronology;
      * optional display calendar is runtime-only, never Canon.
    """

    SCHEMA_VERSION = 1
    POLICY_DEFAULTS = {
        "max_days_per_call": 3650,
        "short_horizon_days": 14,
        "medium_horizon_days": 180,
        "short_chunk_days": 1,
        "medium_chunk_days": 7,
        "long_chunk_days": 30,
        "snapshot_cadence_days": 30,
        "max_population_change_fraction_per_chunk": 0.10,
        "max_ecology_change_fraction_per_chunk": 0.15,
        "max_total_population_change_fraction_per_call": 0.50,
        "max_total_ecology_change_fraction_per_call": 0.50,
        "environment_tick_once_per_segment": True,
        "fail_closed_on_integrity": True,
        "display_days_per_year": None,
    }

    def __init__(self, runtime: LivingRuntime, orchestrator: Any, world_systems: Any, ecology: Any, objects: Any) -> None:
        if any(getattr(x, "runtime", None) is not runtime for x in (orchestrator, world_systems, ecology, objects)):
            raise ValidationError("all long-horizon systems must share the same LivingRuntime")
        self.runtime = runtime
        self.orchestrator = orchestrator
        self.world_systems = world_systems
        self.ecology = ecology
        self.objects = objects
        self.conn = runtime.conn
        self._lock = threading.RLock()
        if not hasattr(runtime,"_long_horizon_world_locks"):
            runtime._long_horizon_world_locks = {}
            runtime._long_horizon_world_locks_guard = threading.RLock()
        if not hasattr(runtime,"_long_horizon_operation_lock"):
            runtime._long_horizon_operation_lock = threading.RLock()
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self.runtime._write_lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS long_horizon_policies(
                  world_instance_id TEXT PRIMARY KEY REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                  timeline_id TEXT NOT NULL,
                  policy_json TEXT NOT NULL,
                  policy_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS offline_sessions(
                  session_id TEXT PRIMARY KEY,
                  world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                  timeline_id TEXT NOT NULL,
                  start_day INTEGER NOT NULL,
                  start_tick INTEGER NOT NULL,
                  end_day INTEGER,
                  end_tick INTEGER,
                  prior_mode TEXT NOT NULL,
                  status TEXT NOT NULL CHECK(status IN ('OPEN','RECONCILED','ABORTED')),
                  start_counts_json TEXT NOT NULL,
                  session_json TEXT NOT NULL,
                  session_hash TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_one_open_offline_session
                  ON offline_sessions(world_instance_id) WHERE status='OPEN';
                CREATE TABLE IF NOT EXISTS offline_catchup_requests(
                  request_id TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL REFERENCES offline_sessions(session_id) ON DELETE RESTRICT,
                  world_instance_id TEXT NOT NULL,
                  request_key TEXT NOT NULL,
                  requested_days INTEGER NOT NULL CHECK(requested_days>0),
                  result_json TEXT,
                  result_hash TEXT,
                  UNIQUE(session_id,request_key)
                );
                CREATE TABLE IF NOT EXISTS long_horizon_segments(
                  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                  segment_id TEXT NOT NULL UNIQUE,
                  session_id TEXT NOT NULL REFERENCES offline_sessions(session_id) ON DELETE RESTRICT,
                  world_instance_id TEXT NOT NULL,
                  from_day INTEGER NOT NULL,
                  from_tick INTEGER NOT NULL,
                  to_day INTEGER NOT NULL,
                  to_tick INTEGER NOT NULL,
                  delta_ticks INTEGER NOT NULL CHECK(delta_ticks>0),
                  delta_days INTEGER NOT NULL CHECK(delta_days>0),
                  segment_json TEXT NOT NULL,
                  segment_hash TEXT NOT NULL,
                  UNIQUE(session_id,from_day,from_tick,to_day,to_tick)
                );
                CREATE TABLE IF NOT EXISTS temporal_snapshots(
                  snapshot_id TEXT PRIMARY KEY,
                  world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                  session_id TEXT REFERENCES offline_sessions(session_id) ON DELETE SET NULL,
                  day INTEGER NOT NULL,
                  tick INTEGER NOT NULL,
                  reason TEXT NOT NULL,
                  state_json TEXT NOT NULL,
                  state_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_temporal_snapshot_world_time
                  ON temporal_snapshots(world_instance_id,day,tick);
                CREATE TABLE IF NOT EXISTS reconciliation_reports(
                  report_id TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL UNIQUE REFERENCES offline_sessions(session_id) ON DELETE RESTRICT,
                  world_instance_id TEXT NOT NULL,
                  report_json TEXT NOT NULL,
                  report_hash TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS long_policy_no_update_hash_guard
                  BEFORE UPDATE ON long_horizon_policies
                  WHEN NEW.policy_hash != OLD.policy_hash OR NEW.policy_json != OLD.policy_json
                  BEGIN SELECT RAISE(ABORT,'long-horizon policy replacement requires configure API'); END;
                CREATE TRIGGER IF NOT EXISTS long_segment_no_update BEFORE UPDATE ON long_horizon_segments
                  BEGIN SELECT RAISE(ABORT,'long-horizon segment immutable'); END;
                CREATE TRIGGER IF NOT EXISTS long_segment_no_delete BEFORE DELETE ON long_horizon_segments
                  BEGIN SELECT RAISE(ABORT,'long-horizon segment immutable'); END;
                CREATE TRIGGER IF NOT EXISTS temporal_snapshot_no_update BEFORE UPDATE ON temporal_snapshots
                  BEGIN SELECT RAISE(ABORT,'temporal snapshot immutable'); END;
                CREATE TRIGGER IF NOT EXISTS temporal_snapshot_no_delete BEFORE DELETE ON temporal_snapshots
                  BEGIN SELECT RAISE(ABORT,'temporal snapshot immutable'); END;
                CREATE TRIGGER IF NOT EXISTS reconciliation_no_update BEFORE UPDATE ON reconciliation_reports
                  BEGIN SELECT RAISE(ABORT,'reconciliation report immutable'); END;
                CREATE TRIGGER IF NOT EXISTS reconciliation_no_delete BEFORE DELETE ON reconciliation_reports
                  BEGIN SELECT RAISE(ABORT,'reconciliation report immutable'); END;
                """
            )
            self.conn.execute("INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('long_horizon_schema_version',?)", (str(self.SCHEMA_VERSION),))

    def configure_world(self, world_instance_id: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        world = self.runtime.get_world(world_instance_id)
        p = copy.deepcopy(self.POLICY_DEFAULTS)
        overrides = overrides or {}
        unknown = set(overrides) - set(p)
        if unknown:
            raise ValidationError(f"unknown long-horizon policy fields: {sorted(unknown)}")
        p.update(copy.deepcopy(overrides))
        ints = ["max_days_per_call","short_horizon_days","medium_horizon_days","short_chunk_days","medium_chunk_days","long_chunk_days","snapshot_cadence_days"]
        for k in ints:
            if not isinstance(p[k], int) or isinstance(p[k], bool) or p[k] <= 0:
                raise ValidationError(f"{k} must be positive integer")
        if p["short_horizon_days"] > p["medium_horizon_days"]:
            raise ValidationError("short_horizon_days cannot exceed medium_horizon_days")
        for frac_key in ("max_population_change_fraction_per_chunk","max_ecology_change_fraction_per_chunk","max_total_population_change_fraction_per_call","max_total_ecology_change_fraction_per_call"):
            frac = p[frac_key]
            if not isinstance(frac, (int,float)) or isinstance(frac,bool) or not (0 < float(frac) <= 0.5):
                raise ValidationError(f"{frac_key} must be >0 and <=0.5")
        if p["display_days_per_year"] is not None:
            if not isinstance(p["display_days_per_year"], int) or isinstance(p["display_days_per_year"], bool) or p["display_days_per_year"] <= 0:
                raise ValidationError("display_days_per_year must be positive integer or null")
        body = {"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"policy":p,"authority":"RUNTIME_LONG_HORIZON_POLICY_NOT_CANON"}
        text = canonical_json(body); h = sha256_text(text)
        with self._lock, self.runtime._write_lock:
            row = self.conn.execute("SELECT policy_hash FROM long_horizon_policies WHERE world_instance_id=?",(world_instance_id,)).fetchone()
            if row:
                self.conn.execute("DROP TRIGGER IF EXISTS long_policy_no_update_hash_guard")
                try:
                    self.conn.execute("UPDATE long_horizon_policies SET policy_json=?,policy_hash=? WHERE world_instance_id=?",(text,h,world_instance_id))
                finally:
                    self.conn.execute("""CREATE TRIGGER IF NOT EXISTS long_policy_no_update_hash_guard BEFORE UPDATE ON long_horizon_policies WHEN NEW.policy_hash != OLD.policy_hash OR NEW.policy_json != OLD.policy_json BEGIN SELECT RAISE(ABORT,'long-horizon policy replacement requires configure API'); END""")
            else:
                self.conn.execute("INSERT INTO long_horizon_policies VALUES(?,?,?,?)",(world_instance_id,world["timeline_id"],text,h))
        body["policy_hash"] = h
        return body

    def get_policy(self, world_instance_id: str) -> dict[str, Any]:
        with self.runtime._write_lock:
            row = self.conn.execute("SELECT policy_json,policy_hash FROM long_horizon_policies WHERE world_instance_id=?",(world_instance_id,)).fetchone()
        if not row:
            return self.configure_world(world_instance_id)["policy"]
        if sha256_text(row["policy_json"]) != row["policy_hash"]:
            raise IntegrityError("long-horizon policy hash mismatch")
        return json.loads(row["policy_json"])["policy"]

    def chronology(self, world_instance_id: str) -> dict[str, Any]:
        c = self.runtime.get_clock(world_instance_id); p = self.get_policy(world_instance_id)
        out = {"authority":"UNIVERSE_DAY_INDEX","epoch_id":c["epoch_id"],"day":c["day"],"tick":c["tick"],"ticks_per_day":c["ticks_per_day"],"absolute_tick":_abs_tick(c),"display_calendar_authority":"RUNTIME_ONLY_NOT_CANON"}
        dpy = p.get("display_days_per_year")
        if dpy:
            out["display_calendar"] = {"days_per_year":dpy,"year_index":c["day"]//dpy,"day_of_year":c["day"]%dpy}
        else:
            out["display_calendar"] = None
        return out

    def _decision_counts(self, world_instance_id: str) -> dict[str, int]:
        out = {}
        with self.runtime._write_lock:
            for name, table in [("npc","agent_decisions"),("ecology_individual","ecology_decisions")]:
                try:
                    out[name] = int(self.conn.execute(f"SELECT COUNT(*) c FROM {table} WHERE world_instance_id=?",(world_instance_id,)).fetchone()["c"])
                except Exception:
                    out[name] = 0
        return out

    def _state_projection(self, world_instance_id: str) -> dict[str, Any]:
        c = self.runtime.get_clock(world_instance_id)
        entities = []
        with self.runtime._write_lock:
            rows = self.conn.execute("SELECT entity_kind,canonical_ref,entity_runtime_id,lifecycle,version,state_json,state_hash FROM entity_states WHERE world_instance_id=? ORDER BY entity_kind,COALESCE(canonical_ref,''),entity_runtime_id",(world_instance_id,)).fetchall()
            for r in rows:
                if sha256_text(r["state_json"]) != r["state_hash"]:
                    raise IntegrityError("entity state hash mismatch during temporal snapshot")
                body = json.loads(r["state_json"])
                entities.append({"entity_kind":r["entity_kind"],"canonical_ref":r["canonical_ref"],"entity_runtime_id":r["entity_runtime_id"],"lifecycle":r["lifecycle"],"version":r["version"],"data":body.get("data",{})})
            eco=[]
            try:
                erows=self.conn.execute("SELECT species_ref,territory_ref,population_json,population_hash FROM ecology_populations_current WHERE world_instance_id=? ORDER BY species_ref,territory_ref",(world_instance_id,)).fetchall()
                for r in erows:
                    if sha256_text(r["population_json"])!=r["population_hash"]: raise IntegrityError("ecology population hash mismatch during snapshot")
                    eco.append(json.loads(r["population_json"]))
            except Exception as exc:
                if isinstance(exc, IntegrityError): raise
            recoveries = [dict(r) for r in self.conn.execute("SELECT recovery_id,target_ref,due_at_day,status FROM recoveries WHERE world_instance_id=? ORDER BY due_at_day,recovery_id",(world_instance_id,)).fetchall()]
        return {"clock":clock_point(c["day"],c["tick"]),"ticks_per_day":c["ticks_per_day"],"entities":entities,"ecology_populations":eco,"recoveries":recoveries,"decision_counts":self._decision_counts(world_instance_id)}

    def create_snapshot(self, world_instance_id: str, *, session_id: str | None=None, reason: str="MANUAL") -> dict[str, Any]:
        with self.runtime._long_horizon_operation_lock:
            return self._create_snapshot_unlocked(world_instance_id,session_id=session_id,reason=reason)

    def _create_snapshot_unlocked(self, world_instance_id: str, *, session_id: str | None=None, reason: str="MANUAL") -> dict[str, Any]:
        if not isinstance(reason,str) or not reason: raise ValidationError("snapshot reason required")
        c=self.runtime.get_clock(world_instance_id); state=self._state_projection(world_instance_id); state_text=canonical_json(state); state_hash=sha256_text(state_text); sid=new_runtime_id("tsnap")
        body={"snapshot_id":sid,"world_instance_id":world_instance_id,"session_id":session_id,"day":c["day"],"tick":c["tick"],"reason":reason,"state_hash":state_hash,"authority":"RUNTIME_TEMPORAL_SNAPSHOT_NOT_CANON"}
        with self._lock,self.runtime._write_lock:
            self.conn.execute("INSERT INTO temporal_snapshots VALUES(?,?,?,?,?,?,?,?)",(sid,world_instance_id,session_id,c["day"],c["tick"],reason,state_text,state_hash))
        return body

    def begin_offline_session(self, world_instance_id: str) -> dict[str, Any]:
        with self.runtime._long_horizon_operation_lock:
            return self._begin_offline_session_unlocked(world_instance_id)

    def _begin_offline_session_unlocked(self, world_instance_id: str) -> dict[str, Any]:
        world=self.runtime.get_world(world_instance_id)
        if world["simulation_mode"]=="ROUTINE_OFFLINE": raise ConflictError("world already in ROUTINE_OFFLINE")
        if world["status"]!="ACTIVE": raise ConflictError("world must be ACTIVE")
        with self._lock,self.runtime._write_lock:
            if self.conn.execute("SELECT 1 FROM offline_sessions WHERE world_instance_id=? AND status='OPEN'",(world_instance_id,)).fetchone(): raise ConflictError("offline session already open")
            c=world["clock_state"]; session_id=new_runtime_id("offline"); counts=self._decision_counts(world_instance_id)
            body={"session_id":session_id,"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"start":clock_point(c["day"],c["tick"]),"prior_mode":world["simulation_mode"],"status":"OPEN","start_counts":counts,"authority":"RUNTIME_OFFLINE_SESSION_NOT_CANON"}
            text=canonical_json(body);h=sha256_text(text)
            self.conn.execute("INSERT INTO offline_sessions(session_id,world_instance_id,timeline_id,start_day,start_tick,prior_mode,status,start_counts_json,session_json,session_hash) VALUES(?,?,?,?,?,?,'OPEN',?,?,?)",(session_id,world_instance_id,world["timeline_id"],c["day"],c["tick"],world["simulation_mode"],canonical_json(counts),text,h))
        self.runtime.set_simulation_mode(world_instance_id,"ROUTINE_OFFLINE")
        snap=self.create_snapshot(world_instance_id,session_id=session_id,reason="OFFLINE_START")
        body["start_snapshot_id"]=snap["snapshot_id"]
        return body

    def _get_open_session(self, world_instance_id: str) -> dict[str, Any]:
        with self.runtime._write_lock:
            r=self.conn.execute("SELECT * FROM offline_sessions WHERE world_instance_id=? AND status='OPEN'",(world_instance_id,)).fetchone()
        if not r: raise NotFoundError("open offline session not found")
        if sha256_text(r["session_json"])!=r["session_hash"]: raise IntegrityError("offline session hash mismatch")
        return dict(r)

    def _choose_chunk_days(self, remaining: int, total_requested: int, p: dict[str,Any]) -> int:
        if total_requested <= p["short_horizon_days"]: base=p["short_chunk_days"]
        elif total_requested <= p["medium_horizon_days"]: base=p["medium_chunk_days"]
        else: base=p["long_chunk_days"]
        return min(remaining,base)

    def _next_recovery_day(self, world_instance_id: str, current_day: int, end_day: int) -> int | None:
        with self.runtime._write_lock:
            r=self.conn.execute("SELECT MIN(due_at_day) d FROM recoveries WHERE world_instance_id=? AND status='SCHEDULED' AND due_at_day>? AND due_at_day<=?",(world_instance_id,current_day,end_day)).fetchone()
        return int(r["d"]) if r and r["d"] is not None else None

    def _plan_world_systems(self, world_instance_id: str, delta_ticks: int, cap_fraction: float, baseline_counts: dict[str,int] | None=None) -> dict[str,Any]:
        ws=self.world_systems
        with ws._lock, self.runtime._write_lock:
            flows=copy.deepcopy(ws._entities(world_instance_id,"ECONOMIC_FLOW")); pops=copy.deepcopy(ws._entities(world_instance_id,"POPULATION_AGGREGATE")); facs=copy.deepcopy(ws._entities(world_instance_id,"FACTION_RUNTIME")); routes=copy.deepcopy(ws._entities(world_instance_id,"ROUTE_RUNTIME"))
        if not (flows or pops or facs): return {"skip":True,"reason":"WORLD_SYSTEMS_NOT_BOOTSTRAPPED"}
        route_map={r["data"].get("route_ref") or r.get("canonical_ref"):r["data"] for r in routes}
        flowd={e["entity_runtime_id"]:copy.deepcopy(e["data"]) for e in flows}; popd={e["entity_runtime_id"]:copy.deepcopy(e["data"]) for e in pops}; facd={e["entity_runtime_id"]:copy.deepcopy(e["data"]) for e in facs}
        pop_by_ref={d.get("settlement_ref") or d.get("source_ref"):d for d in popd.values()}
        initial_counts={k:int(v["count"]) for k,v in popd.items()}; bound_counts=baseline_counts or initial_counts
        totals={"produced":0.0,"consumed":0.0,"shortage":0.0,"births":0,"deaths":0,"migration":0,"treasury_delta":0.0,"influence_delta":0.0}
        for _ in range(delta_ticks):
            # economy
            for d in flowd.values():
                rf=1.0
                for rr in d.get("route_ids",[]):
                    rd=route_map.get(rr)
                    if rd is None: rf=0.0; break
                    rf=min(rf,float(rd.get("capacity_factor",1.0)) if rd.get("operational",True) else 0.0)
                pd=pop_by_ref.get(d.get("destination_id")); pf=max(0.25,float(pd["count"])/1000.0) if pd else 1.0
                produced=float(d["production_rate"])*rf; demand=float(d["consumption_rate"])*pf; available=float(d["stock"])+produced; consumed=min(available,demand); stock=max(0.0,available-consumed); shortage=max(0.0,demand-consumed); pressure=0.0 if demand<=0 else _clamp(shortage/demand*100.0,0,100); price=_clamp(float(d["base_price"])*(1.0+1.5*(pressure/100.0)),float(d["base_price"])*0.5,float(d["base_price"])*3.0)
                d.update({"stock":stock,"price":price,"shortage_pressure":pressure,"last_throughput":consumed});totals["produced"]+=produced;totals["consumed"]+=consumed;totals["shortage"]+=shortage
            avg_short=sum(float(d["shortage_pressure"]) for d in flowd.values())/max(1,len(flowd)); security_by_territory={d.get("territory_ref"):float(d["security"]) for d in facd.values()}
            # population -- offline: migration frozen
            for eid,d in popd.items():
                count=int(d["count"]); food=_clamp(100.0-avg_short,0,100); ba=float(d["birth_accumulator"])+count*0.00020*(0.5+food/200); da=float(d["death_accumulator"])+count*(0.00010+(100-food)*0.000002); births=int(ba);deaths=int(da);ba-=births;da-=deaths
                new_count=max(0,count+births-deaths)
                # conservative long-horizon cap per chunk, runtime-only guardrail
                initial=max(1,int(bound_counts.get(eid,initial_counts[eid])));lo=max(0,math.floor(initial*(1-cap_fraction)));hi=math.ceil(initial*(1+cap_fraction));new_count=max(lo,min(hi,new_count))
                labor=int(new_count*0.55);jobs=max(0,int(new_count*(0.46+food/1000.0)));employed=min(labor,jobs);unemployed=max(0,labor-employed);welfare=_clamp(0.55*food+0.45*(100*(employed/max(1,labor))),0,100)
                d.update({"count":new_count,"labor_force":labor,"employed":employed,"unemployed":unemployed,"birth_accumulator":ba,"death_accumulator":da,"food_security":food,"welfare_index":welfare})
                totals["births"]+=births;totals["deaths"]+=deaths
            # faction -- offline influence frozen
            econ_activity=sum(float(d["last_throughput"])*float(d["price"]) for d in flowd.values());unemp=sum(int(d["unemployed"]) for d in popd.values())/max(1,sum(int(d["labor_force"]) for d in popd.values()))
            for d in facd.values():
                old_t=float(d["treasury"]); treasury=old_t+econ_activity*0.001/max(1,len(facd));target_security=_clamp(70.0-unemp*80.0,20,90);security=float(d["security"])+(target_security-float(d["security"]))*0.05;stability=_clamp(0.6*security+0.4*(100-unemp*100),0,100)
                d.update({"treasury":treasury,"security":security,"stability":stability})
                totals["treasury_delta"]+=treasury-old_t
        consequences=[];targets=flows+pops+facs
        fields_flow=["stock","price","shortage_pressure","last_throughput"]
        fields_pop=["count","labor_force","employed","unemployed","birth_accumulator","death_accumulator","migration_accumulator","food_security","welfare_index"]
        fields_fac=["treasury","security","stability","influence","influence_not_sovereignty"]
        for e in flows:
            d=flowd[e["entity_runtime_id"]]
            for i,k in enumerate(fields_flow): consequences.append({"target_ref":e["entity_runtime_id"],"operation":"SET","field_path":f"data.{k}","value":round(d[k],8) if isinstance(d[k],float) else d[k],"priority":i,"kind":"DIRECT"})
        for e in pops:
            d=popd[e["entity_runtime_id"]]
            for i,k in enumerate(fields_pop): consequences.append({"target_ref":e["entity_runtime_id"],"operation":"SET","field_path":f"data.{k}","value":round(d[k],8) if isinstance(d[k],float) else d[k],"priority":i,"kind":"DIRECT"})
        for e in facs:
            d=facd[e["entity_runtime_id"]]
            for i,k in enumerate(fields_fac): consequences.append({"target_ref":e["entity_runtime_id"],"operation":"SET","field_path":f"data.{k}","value":round(d[k],8) if isinstance(d[k],float) else d[k],"priority":i,"kind":"DIRECT"})
        return {"skip":False,"targets":targets,"consequences":consequences,"metrics":{k:round(v,6) if isinstance(v,float) else v for k,v in totals.items()}}

    def _apply_world_system_plan(self, world_instance_id: str, session_id: str, segment_id: str, plan: dict[str,Any]) -> dict[str,Any]:
        if plan.get("skip"): return {"status":"SKIPPED","reason":plan["reason"]}
        world=self.runtime.get_world(world_instance_id);c=world["clock_state"]
        action={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"actor_ref":"SYSTEM_RECONCILIATION","action_type":"LONG_HORIZON_WORLD_SYSTEMS_INTERVAL","parameters":{"session_id":session_id,"segment_id":segment_id},"precondition_snapshot":{"entity_versions":{e["entity_runtime_id"]:e["version"] for e in plan["targets"]}},"idempotency_key":f"longhorizon:worldsystems:{segment_id}","created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"SYSTEM_RECONCILIATION","execution_class":"ROUTINE_SAFE"}
        r=self.runtime.apply_action(world_instance_id,action,plan["consequences"]);return {"status":"PASS","event_id":r["event_id"],"metrics":plan["metrics"]}

    def _plan_ecology(self, world_instance_id: str, delta_ticks: int, cap_fraction: float, baseline_counts: dict[tuple[str,str],int] | None=None) -> dict[str,Any]:
        eco=self.ecology
        with eco._lock,self.runtime._write_lock:
            rows=self.conn.execute("SELECT population_json,population_hash FROM ecology_populations_current WHERE world_instance_id=? ORDER BY species_ref,territory_ref",(world_instance_id,)).fetchall(); links=self.conn.execute("SELECT link_json,link_hash FROM food_web_links WHERE world_instance_id=? AND status='ACTIVE'",(world_instance_id,)).fetchall()
            if not rows:return {"skip":True,"reason":"ECOLOGY_POPULATIONS_NOT_BOOTSTRAPPED"}
            pops={};initial={}
            for r in rows:
                if sha256_text(r["population_json"])!=r["population_hash"]:raise IntegrityError("ecology population hash mismatch")
                p=json.loads(r["population_json"]);key=(p["species_ref"],p["territory_ref"]);pops[key]=copy.deepcopy(p);initial[key]=int(p["count"])
            parsed_links=[]
            for r in links:
                if sha256_text(r["link_json"])!=r["link_hash"]:raise IntegrityError("food web hash mismatch")
                parsed_links.append(json.loads(r["link_json"]))
            profiles={s:eco.get_species_profile(world_instance_id,s) for s,_ in pops}
        for _ in range(delta_ticks):
            planned={}
            for key,p in pops.items():
                prof=profiles[p["species_ref"]];pressure=min(p["resource_index"],p["water_index"],p["climate_comfort"])/100.0;density=(p["count"]/p["carrying_capacity"]) if p["carrying_capacity"] else 1.0;raw=p["count"]*prof["population_growth_rate"]*pressure*(1-density);cap=max(1,int(math.ceil(p["count"]*prof["routine_population_change_cap_fraction"]))) if p["count"] else 0;planned[key]=max(-cap,min(cap,int(round(raw)))) if cap else 0
            for link in parsed_links:
                ts={t for s,t in pops if s==link["predator_species_ref"]}&{t for s,t in pops if s==link["prey_species_ref"]}
                for t in ts:
                    pred=pops[(link["predator_species_ref"],t)];prey=pops[(link["prey_species_ref"],t)];prof=profiles[link["predator_species_ref"]];kills=int(min(prey["count"],math.floor(pred["count"]*prof["predation_rate"]*link["preference"])));prey_cap=max(1,int(math.ceil(prey["count"]*0.05))) if prey["count"] else 0;kills=min(kills,prey_cap);planned[(prey["species_ref"],t)]=planned.get((prey["species_ref"],t),0)-kills;planned[(pred["species_ref"],t)]=planned.get((pred["species_ref"],t),0)+int(math.floor(kills*link["efficiency"]*0.1))
            for key,d in planned.items(): pops[key]["count"]=max(0,pops[key]["count"]+d)
        for k in pops:
            init=int((baseline_counts or initial).get(k,initial[k])); lo=max(0,math.floor(init*(1-cap_fraction))); hi=math.ceil(init*(1+cap_fraction)); pops[k]["count"]=max(lo,min(hi,int(pops[k]["count"])))
        net={k:int(pops[k]["count"])-initial[k] for k in pops}
        return {"skip":False,"net":net,"initial_total":sum(initial.values()),"final_total":sum(int(p["count"]) for p in pops.values())}

    def _apply_ecology_plan(self, world_instance_id: str, plan: dict[str,Any]) -> dict[str,Any]:
        if plan.get("skip"):return {"status":"SKIPPED","reason":plan["reason"]}
        eco=self.ecology; applied=[]
        with eco._lock,self.runtime._write_lock:
            self.runtime._begin()
            try:
                for (s,t),d in sorted(plan["net"].items()):
                    if d: applied.append(eco._apply_population_delta_tx(world_instance_id,s,t,d,"LONG_HORIZON_ROUTINE"))
                self.runtime._commit()
            except Exception:
                self.runtime._rollback();raise
        return {"status":"PASS","population_changes":len(applied),"initial_total":plan["initial_total"],"final_total":plan["final_total"],"cross_territory_migration":False}

    def _drain_consequences(self, world_instance_id: str) -> dict[str,Any]:
        return self.orchestrator.drain_pending_consequences(world_instance_id)

    def _record_segment(self, session_id: str, world_instance_id: str, start: dict[str,Any], end: dict[str,Any], delta_ticks: int, delta_days: int, details: dict[str,Any], segment_id: str) -> dict[str,Any]:
        body={"segment_id":segment_id,"session_id":session_id,"world_instance_id":world_instance_id,"from":clock_point(start["day"],start["tick"]),"to":clock_point(end["day"],end["tick"]),"delta_ticks":delta_ticks,"delta_days":delta_days,"details":copy.deepcopy(details),"status":"PASS","authority":"RUNTIME_LONG_HORIZON_SEGMENT_NOT_CANON"};text=canonical_json(body);h=sha256_text(text)
        with self._lock,self.runtime._write_lock:
            self.conn.execute("INSERT INTO long_horizon_segments(segment_id,session_id,world_instance_id,from_day,from_tick,to_day,to_tick,delta_ticks,delta_days,segment_json,segment_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(segment_id,session_id,world_instance_id,start["day"],start["tick"],end["day"],end["tick"],delta_ticks,delta_days,text,h))
        body["segment_hash"]=h;return body

    def simulate_offline_days(self, world_instance_id: str, days: int, *, request_key: str | None=None) -> dict[str,Any]:
        # SQLite uses one shared connection per Runtime. Serialize long-horizon operations on that connection;
        # callers/worlds may still submit concurrently and are deterministically queued.
        with self.runtime._long_horizon_operation_lock:
            with self.runtime._long_horizon_world_locks_guard:
                lock=self.runtime._long_horizon_world_locks.setdefault(world_instance_id,threading.RLock())
            with lock:
                return self._simulate_offline_days_locked(world_instance_id,days,request_key=request_key)

    def _simulate_offline_days_locked(self, world_instance_id: str, days: int, *, request_key: str | None=None) -> dict[str,Any]:
        if not isinstance(days,int) or isinstance(days,bool) or days<=0: raise ValidationError("days must be positive integer")
        if request_key is not None and (not isinstance(request_key,str) or not request_key): raise ValidationError("request_key must be non-empty string")
        session=self._get_open_session(world_instance_id); p=self.get_policy(world_instance_id)
        request_key=request_key or new_runtime_id("catchup")
        with self._lock,self.runtime._write_lock:
            prior=self.conn.execute("SELECT requested_days,result_json,result_hash FROM offline_catchup_requests WHERE session_id=? AND request_key=?",(session["session_id"],request_key)).fetchone()
            if prior:
                if prior["requested_days"]!=days: raise ConflictError("catch-up request_key reused with different duration")
                if not prior["result_json"] or sha256_text(prior["result_json"])!=prior["result_hash"]: raise IntegrityError("catch-up request hash mismatch")
                out=json.loads(prior["result_json"]);out["idempotent_replay"]=True;return out
            self.conn.execute("INSERT INTO offline_catchup_requests(request_id,session_id,world_instance_id,request_key,requested_days) VALUES(?,?,?,?,?)",(new_runtime_id("catchreq"),session["session_id"],world_instance_id,request_key,days))
        if days>p["max_days_per_call"]: raise ValidationError("requested offline duration exceeds max_days_per_call")
        world=self.runtime.get_world(world_instance_id)
        if world["simulation_mode"]!="ROUTINE_OFFLINE": raise ConflictError("world must remain in ROUTINE_OFFLINE during catch-up")
        segments=[];remaining=days;start_call=self.runtime.get_clock(world_instance_id);last_snapshot_day=start_call["day"]
        # Call-level baselines prevent many small chunks from compounding past the offline safety envelope.
        human_baseline={e["entity_runtime_id"]:int(e["data"]["count"]) for e in self.world_systems._entities(world_instance_id,"POPULATION_AGGREGATE")}
        eco_baseline={}
        with self.runtime._write_lock:
            for r in self.conn.execute("SELECT population_json,population_hash FROM ecology_populations_current WHERE world_instance_id=?",(world_instance_id,)).fetchall():
                if sha256_text(r["population_json"])!=r["population_hash"]: raise IntegrityError("ecology population hash mismatch")
                q=json.loads(r["population_json"]); eco_baseline[(q["species_ref"],q["territory_ref"])]=int(q["count"])
        while remaining>0:
            c=self.runtime.get_clock(world_instance_id);chunk=self._choose_chunk_days(remaining,days,p);candidate_end=c["day"]+chunk
            # Split exactly on due recovery and periodic snapshot boundaries so the audit timeline is stable.
            rd=self._next_recovery_day(world_instance_id,c["day"],candidate_end)
            next_snapshot_day=last_snapshot_day+p["snapshot_cadence_days"]
            boundaries=[x for x in (rd,next_snapshot_day) if x is not None and c["day"] < x <= candidate_end]
            if boundaries: chunk=max(1,min(boundaries)-c["day"])
            delta_ticks=chunk*c["ticks_per_day"];segment_id=new_runtime_id("lhseg")
            # Apply recoveries already due at the segment boundary before planning the next interval.
            self.runtime.process_due_recoveries(world_instance_id); self._drain_consequences(world_instance_id)
            elapsed_after=days-remaining+chunk
            human_cap=min(float(p["max_total_population_change_fraction_per_call"]),float(p["max_population_change_fraction_per_chunk"])*float(elapsed_after)/float(p["long_chunk_days"]))
            eco_cap=min(float(p["max_total_ecology_change_fraction_per_call"]),float(p["max_ecology_change_fraction_per_chunk"])*float(elapsed_after)/float(p["long_chunk_days"]))
            ws_plan=self._plan_world_systems(world_instance_id,delta_ticks,human_cap,human_baseline);eco_plan=self._plan_ecology(world_instance_id,delta_ticks,eco_cap,eco_baseline)
            self.runtime.advance_ticks(world_instance_id,delta_ticks,source="SYSTEM_RECONCILIATION")
            ws_result=self._apply_world_system_plan(world_instance_id,session["session_id"],segment_id,ws_plan)
            eco_result=self._apply_ecology_plan(world_instance_id,eco_plan)
            env_result=self.objects.simulate_environment_tick(world_instance_id,tick_key=f"long:{session['session_id']}:{segment_id}") if p["environment_tick_once_per_segment"] else {"status":"SKIPPED"}
            recovery=self.runtime.process_due_recoveries(world_instance_id);drain=self._drain_consequences(world_instance_id);end=self.runtime.get_clock(world_instance_id)
            seg=self._record_segment(session["session_id"],world_instance_id,c,end,delta_ticks,chunk,{"world_systems":ws_result,"ecology":eco_result,"environment":env_result,"recoveries":len(recovery),"consequence_drain":{"roots_processed":drain.get("roots_processed",0),"pending_after":drain.get("pending_after",0)}},segment_id);segments.append(seg)
            if end["day"]-last_snapshot_day>=p["snapshot_cadence_days"]:
                self.create_snapshot(world_instance_id,session_id=session["session_id"],reason="OFFLINE_PERIODIC");last_snapshot_day=end["day"]
            remaining-=chunk
        end_call=self.runtime.get_clock(world_instance_id)
        out={"status":"PASS","session_id":session["session_id"],"request_key":request_key,"requested_days":days,"segments":len(segments),"from":clock_point(start_call["day"],start_call["tick"]),"to":clock_point(end_call["day"],end_call["tick"]),"individual_npc_decisions_added":self._decision_counts(world_instance_id)["npc"]-json.loads(session["start_counts_json"])["npc"],"individual_ecology_decisions_added":self._decision_counts(world_instance_id)["ecology_individual"]-json.loads(session["start_counts_json"])["ecology_individual"],"segment_ids":[s["segment_id"] for s in segments],"idempotent_replay":False}
        text=canonical_json(out);h=sha256_text(text)
        with self._lock,self.runtime._write_lock:self.conn.execute("UPDATE offline_catchup_requests SET result_json=?,result_hash=? WHERE session_id=? AND request_key=?",(text,h,session["session_id"],request_key))
        return out

    def reconcile_and_resume(self, world_instance_id: str, *, resume_mode: str | None=None) -> dict[str,Any]:
        with self.runtime._long_horizon_operation_lock:
            return self._reconcile_and_resume_unlocked(world_instance_id,resume_mode=resume_mode)

    def _reconcile_and_resume_unlocked(self, world_instance_id: str, *, resume_mode: str | None=None) -> dict[str,Any]:
        session=self._get_open_session(world_instance_id);before_counts=json.loads(session["start_counts_json"]);after_counts=self._decision_counts(world_instance_id)
        if after_counts!=before_counts: raise IntegrityError("individual decisions changed during offline session")
        self.runtime.process_due_recoveries(world_instance_id);drain=self._drain_consequences(world_instance_id)
        reports={"runtime":self.runtime.full_integrity_check(world_instance_id),"orchestrator":self.orchestrator.full_integrity_check(world_instance_id),"world_systems":self.world_systems.full_integrity_check(world_instance_id),"ecology":self.ecology.full_integrity_check(world_instance_id),"objects":self.objects.full_integrity_check(world_instance_id)}
        bad=[k for k,v in reports.items() if v.get("status")!="PASS"]
        if bad:
            if self.get_policy(world_instance_id)["fail_closed_on_integrity"]:
                with self.runtime._write_lock:self.conn.execute("UPDATE worlds SET status='CORRUPT_BLOCKED' WHERE world_instance_id=?",(world_instance_id,))
            raise IntegrityError(f"reconciliation integrity failed: {bad}")
        end_snap=self.create_snapshot(world_instance_id,session_id=session["session_id"],reason="OFFLINE_END")
        mode=resume_mode or session["prior_mode"]
        if mode not in {"FULL","ACTIVE","AGGREGATE"}: raise ValidationError("resume_mode must be FULL, ACTIVE, or AGGREGATE")
        c=self.runtime.get_clock(world_instance_id);start_state=self.conn.execute("SELECT state_json,state_hash FROM temporal_snapshots WHERE session_id=? AND reason='OFFLINE_START' ORDER BY rowid LIMIT 1",(session["session_id"],)).fetchone();end_state=self.conn.execute("SELECT state_json,state_hash FROM temporal_snapshots WHERE snapshot_id=?",(end_snap["snapshot_id"],)).fetchone()
        if not start_state or sha256_text(start_state["state_json"])!=start_state["state_hash"] or sha256_text(end_state["state_json"])!=end_state["state_hash"]: raise IntegrityError("reconciliation snapshot hash mismatch")
        start_obj=json.loads(start_state["state_json"]);end_obj=json.loads(end_state["state_json"])
        report_id=new_runtime_id("recon");report={"report_id":report_id,"session_id":session["session_id"],"world_instance_id":world_instance_id,"from":clock_point(session["start_day"],session["start_tick"]),"to":clock_point(c["day"],c["tick"]),"elapsed_days":c["day"]-session["start_day"],"segments":self.conn.execute("SELECT COUNT(*) c FROM long_horizon_segments WHERE session_id=?",(session["session_id"],)).fetchone()["c"],"decision_counts":{"before":before_counts,"after":after_counts},"state_hash_before":start_state["state_hash"],"state_hash_after":end_state["state_hash"],"entity_count_before":len(start_obj["entities"]),"entity_count_after":len(end_obj["entities"]),"ecology_population_rows_before":len(start_obj["ecology_populations"]),"ecology_population_rows_after":len(end_obj["ecology_populations"]),"consequence_backlog_after":drain.get("pending_after",0),"resume_mode":mode,"integrity":"PASS","authority":"RUNTIME_RECONCILIATION_NOT_CANON"}
        text=canonical_json(report);h=sha256_text(text)
        with self._lock,self.runtime._write_lock:
            self.conn.execute("INSERT INTO reconciliation_reports VALUES(?,?,?,?,?)",(report_id,session["session_id"],world_instance_id,text,h))
            final_session={"session_id":session["session_id"],"world_instance_id":world_instance_id,"timeline_id":session["timeline_id"],"start":clock_point(session["start_day"],session["start_tick"]),"end":clock_point(c["day"],c["tick"]),"prior_mode":session["prior_mode"],"resume_mode":mode,"status":"RECONCILED","authority":"RUNTIME_OFFLINE_SESSION_NOT_CANON"};st=canonical_json(final_session);sh=sha256_text(st)
            self.conn.execute("UPDATE offline_sessions SET end_day=?,end_tick=?,status='RECONCILED',session_json=?,session_hash=? WHERE session_id=?",(c["day"],c["tick"],st,sh,session["session_id"]))
        self.runtime.set_simulation_mode(world_instance_id,mode);report["report_hash"]=h;return report

    def verify_segment_chain(self, session_id: str) -> dict[str,Any]:
        failures=[]
        with self.runtime._write_lock:
            rows=self.conn.execute("SELECT * FROM long_horizon_segments WHERE session_id=? ORDER BY sequence",(session_id,)).fetchall()
        prev_to=None
        for r in rows:
            if sha256_text(r["segment_json"])!=r["segment_hash"]:failures.append(f"SEGMENT_HASH:{r['segment_id']}")
            frm=(r["from_day"],r["from_tick"]);to=(r["to_day"],r["to_tick"])
            if prev_to is not None and frm!=prev_to:failures.append(f"SEGMENT_GAP:{r['segment_id']}")
            prev_to=to
        return {"status":"PASS" if not failures else "FAIL","failures":failures,"segments":len(rows)}

    def full_integrity_check(self, world_instance_id: str) -> dict[str,Any]:
        failures=[]
        with self._lock,self.runtime._write_lock:
            for r in self.conn.execute("SELECT policy_json,policy_hash FROM long_horizon_policies WHERE world_instance_id=?",(world_instance_id,)).fetchall():
                if sha256_text(r["policy_json"])!=r["policy_hash"]:failures.append("POLICY_HASH")
            for r in self.conn.execute("SELECT session_id,session_json,session_hash,status FROM offline_sessions WHERE world_instance_id=?",(world_instance_id,)).fetchall():
                if sha256_text(r["session_json"])!=r["session_hash"]:failures.append(f"SESSION_HASH:{r['session_id']}")
            for r in self.conn.execute("SELECT request_id,result_json,result_hash FROM offline_catchup_requests WHERE world_instance_id=? AND result_json IS NOT NULL",(world_instance_id,)).fetchall():
                if sha256_text(r["result_json"])!=r["result_hash"]:failures.append(f"CATCHUP_HASH:{r['request_id']}")
            for r in self.conn.execute("SELECT segment_id,segment_json,segment_hash FROM long_horizon_segments WHERE world_instance_id=?",(world_instance_id,)).fetchall():
                if sha256_text(r["segment_json"])!=r["segment_hash"]:failures.append(f"SEGMENT_HASH:{r['segment_id']}")
            for r in self.conn.execute("SELECT snapshot_id,state_json,state_hash FROM temporal_snapshots WHERE world_instance_id=?",(world_instance_id,)).fetchall():
                if sha256_text(r["state_json"])!=r["state_hash"]:failures.append(f"SNAPSHOT_HASH:{r['snapshot_id']}")
            for r in self.conn.execute("SELECT report_id,report_json,report_hash FROM reconciliation_reports WHERE world_instance_id=?",(world_instance_id,)).fetchall():
                if sha256_text(r["report_json"])!=r["report_hash"]:failures.append(f"REPORT_HASH:{r['report_id']}")
        open_count=self.conn.execute("SELECT COUNT(*) c FROM offline_sessions WHERE world_instance_id=? AND status='OPEN'",(world_instance_id,)).fetchone()["c"]
        if open_count>1:failures.append("MULTIPLE_OPEN_SESSIONS")
        return {"status":"PASS" if not failures else "FAIL","failures":failures,"summary":{"sessions":self.conn.execute("SELECT COUNT(*) c FROM offline_sessions WHERE world_instance_id=?",(world_instance_id,)).fetchone()["c"],"segments":self.conn.execute("SELECT COUNT(*) c FROM long_horizon_segments WHERE world_instance_id=?",(world_instance_id,)).fetchone()["c"],"snapshots":self.conn.execute("SELECT COUNT(*) c FROM temporal_snapshots WHERE world_instance_id=?",(world_instance_id,)).fetchone()["c"],"reports":self.conn.execute("SELECT COUNT(*) c FROM reconciliation_reports WHERE world_instance_id=?",(world_instance_id,)).fetchone()["c"]}}

    def integrity_guard(self, world_instance_id: str) -> dict[str,Any]:
        r=self.full_integrity_check(world_instance_id)
        if r["status"]!="PASS":
            with self.runtime._write_lock:self.conn.execute("UPDATE worlds SET status='CORRUPT_BLOCKED' WHERE world_instance_id=?",(world_instance_id,))
        return r
