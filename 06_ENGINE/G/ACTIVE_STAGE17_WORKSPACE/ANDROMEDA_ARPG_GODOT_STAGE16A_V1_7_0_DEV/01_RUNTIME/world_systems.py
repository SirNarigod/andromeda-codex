from __future__ import annotations

import copy, json, math, threading, zipfile
from pathlib import Path
from typing import Any

from living_runtime import (
    LivingRuntime, ValidationError, IntegrityError, ConflictError, NotFoundError,
    canonical_json, sha256_text, new_runtime_id, clock_point,
)

MASTER_PATHS = {
    "ECONOMIC_FLOW": "ANDROMEDA_CODEX_MASTER/03_DOMAINS/SPATIALIZATION/03_REDES/STELLAR_ECONOMIC_FLOWS_V1_0.json",
    "FACTION_INFLUENCE": "ANDROMEDA_CODEX_MASTER/03_DOMAINS/SPATIALIZATION/03_REDES/STELLAR_FACTION_INFLUENCE_V1_0.json",
    "POPULATION_DISTRIBUTION": "ANDROMEDA_CODEX_MASTER/03_DOMAINS/SPATIALIZATION/02_DISTRIBUICOES/STELLAR_POPULATION_DISTRIBUTION_V1_0.json",
    "ROUTE": "ANDROMEDA_CODEX_MASTER/03_DOMAINS/GEOSPATIAL/02_GEOGRAFIA/STELLAR_ROUTE_SKELETON_V1_0.json",
    "SECONDARY_ROUTE": "ANDROMEDA_CODEX_MASTER/03_DOMAINS/SPATIALIZATION/03_REDES/STELLAR_SECONDARY_ROUTE_REGISTRY_V1_0.json",
}
AUXILIARY_MASTER_PATHS = {
    "POI": "ANDROMEDA_CODEX_MASTER/03_DOMAINS/SPATIALIZATION/05_ATLAS/STELLAR_POI_REGISTRY_V1_0.json",
    "INDUSTRIAL_NODE": "ANDROMEDA_CODEX_MASTER/03_DOMAINS/SPATIALIZATION/03_REDES/STELLAR_INDUSTRIAL_NODES_V1_0.json",
}
PRODUCT_CATEGORY_HINTS = {
    "produção rural": "FOOD",
    "produtos de encosta": "FOOD",
    "recursos marítimos": "FOOD",
    "insumos medicinais": "MEDICAL",
    "material ferral": "MATERIAL",
    "componentes de rede": "TECHNOLOGY",
    "componentes cristalinos": "TECHNOLOGY",
}
ALLOWED_MODES={"FULL","ACTIVE","AGGREGATE","ROUTINE_OFFLINE"}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _abs_tick(clock: dict[str,Any]) -> int:
    return int(clock["day"])*int(clock["ticks_per_day"])+int(clock["tick"])


class WorldSystems:
    """Runtime systemic economy/faction/population layer. Canon data is read-only input."""
    SCHEMA_VERSION=1
    EXTENSION_KEY="world_systems"
    EXTENSION_VERSION="V1.0"

    def __init__(self, runtime: LivingRuntime) -> None:
        self.runtime=runtime; self.conn=runtime.conn; self._lock=threading.RLock(); self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self.runtime._write_lock:
            self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS world_system_master_snapshots(
              snapshot_key TEXT PRIMARY KEY, category TEXT NOT NULL, canonical_ref TEXT NOT NULL,
              source_path TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS world_system_location_snapshots(
              location_ref TEXT PRIMARY KEY, location_kind TEXT NOT NULL, territory_ref TEXT, parent_ref TEXT,
              route_ids_json TEXT NOT NULL, source_path TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS world_system_bindings(
              binding_id TEXT PRIMARY KEY, world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
              timeline_id TEXT NOT NULL, system_kind TEXT NOT NULL, canonical_ref TEXT NOT NULL,
              entity_runtime_id TEXT NOT NULL, binding_json TEXT NOT NULL, binding_hash TEXT NOT NULL,
              UNIQUE(world_instance_id,system_kind,canonical_ref), UNIQUE(world_instance_id,entity_runtime_id)
            );
            CREATE TABLE IF NOT EXISTS world_system_tick_log(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, tick_record_id TEXT NOT NULL UNIQUE,
              world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
              timeline_id TEXT NOT NULL, tick_key TEXT NOT NULL, system_name TEXT NOT NULL,
              mode TEXT NOT NULL, event_id TEXT, result_json TEXT NOT NULL, result_hash TEXT NOT NULL,
              UNIQUE(world_instance_id,tick_key,system_name)
            );
            CREATE TABLE IF NOT EXISTS faction_relations_runtime(
              relation_id TEXT PRIMARY KEY, world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
              source_faction_ref TEXT NOT NULL, target_faction_ref TEXT NOT NULL,
              stance REAL NOT NULL CHECK(stance BETWEEN -100 AND 100), relation_json TEXT NOT NULL, relation_hash TEXT NOT NULL,
              UNIQUE(world_instance_id,source_faction_ref,target_faction_ref)
            );
            CREATE TRIGGER IF NOT EXISTS ws_snapshot_no_update BEFORE UPDATE ON world_system_master_snapshots BEGIN SELECT RAISE(ABORT,'master snapshot immutable'); END;
            CREATE TRIGGER IF NOT EXISTS ws_snapshot_no_delete BEFORE DELETE ON world_system_master_snapshots BEGIN SELECT RAISE(ABORT,'master snapshot immutable'); END;
            CREATE TRIGGER IF NOT EXISTS ws_location_snapshot_no_update BEFORE UPDATE ON world_system_location_snapshots BEGIN SELECT RAISE(ABORT,'location snapshot immutable'); END;
            CREATE TRIGGER IF NOT EXISTS ws_location_snapshot_no_delete BEFORE DELETE ON world_system_location_snapshots BEGIN SELECT RAISE(ABORT,'location snapshot immutable'); END;
            CREATE TRIGGER IF NOT EXISTS ws_tick_no_update BEFORE UPDATE ON world_system_tick_log BEGIN SELECT RAISE(ABORT,'world system tick immutable'); END;
            CREATE TRIGGER IF NOT EXISTS ws_tick_no_delete BEFORE DELETE ON world_system_tick_log BEGIN SELECT RAISE(ABORT,'world system tick immutable'); END;
            """)
            self.conn.execute("INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('world_systems_schema_version',?)",(str(self.SCHEMA_VERSION),))

    def load_master_snapshots(self, master_release_path: str|Path) -> dict[str,Any]:
        p=str(master_release_path); inserted=0; counts={}; auxiliary_inserted=0
        with zipfile.ZipFile(p) as z:
            docs={k:json.loads(z.read(path)) for k,path in MASTER_PATHS.items()}
            aux_docs={k:json.loads(z.read(path)) for k,path in AUXILIARY_MASTER_PATHS.items()}
        records={
          "ECONOMIC_FLOW": docs["ECONOMIC_FLOW"]["flows"],
          "FACTION_INFLUENCE": docs["FACTION_INFLUENCE"]["records"],
          "POPULATION_DISTRIBUTION": docs["POPULATION_DISTRIBUTION"]["settlements"],
          "ROUTE": docs["ROUTE"]["routes"],
          "SECONDARY_ROUTE": docs["SECONDARY_ROUTE"]["routes"],
        }
        pois={item["id"]:item for item in aux_docs["POI"]["pois"]}
        location_rows=[]
        for item in pois.values():
            location_rows.append((item["id"],"POI",item.get("territory_id"),item.get("parent_id"),list(item.get("route_ids",[])),AUXILIARY_MASTER_PATHS["POI"],item))
        for item in aux_docs["INDUSTRIAL_NODE"]["nodes"]:
            poi=pois.get(item.get("poi_id")) or {}
            route_ids=list(dict.fromkeys(list(item.get("transport",[]))+list(poi.get("route_ids",[]))))
            location_rows.append((item["id"],"INDUSTRIAL_NODE",poi.get("territory_id"),item.get("poi_id"),route_ids,AUXILIARY_MASTER_PATHS["INDUSTRIAL_NODE"],item))
        with self._lock,self.runtime._write_lock:
            for category,items in records.items():
                counts[category]=len(items)
                for item in items:
                    cref=(item.get("id") if category!="POPULATION_DISTRIBUTION" else item.get("settlement_id"))
                    if not isinstance(cref,str) or not cref: raise IntegrityError("master snapshot missing canonical reference")
                    key=f"{category}:{cref}"; text=canonical_json(item); h=sha256_text(text)
                    row=self.conn.execute("SELECT payload_hash FROM world_system_master_snapshots WHERE snapshot_key=?",(key,)).fetchone()
                    if row:
                        if row["payload_hash"]!=h: raise IntegrityError("master snapshot drift")
                        continue
                    self.conn.execute("INSERT INTO world_system_master_snapshots VALUES(?,?,?,?,?,?)",(key,category,cref,MASTER_PATHS[category],text,h));inserted+=1
            for ref,kind,territory,parent,routes,source,item in location_rows:
                text=canonical_json(item); h=sha256_text(text); routes_text=canonical_json(routes)
                row=self.conn.execute("SELECT payload_hash,territory_ref,parent_ref,route_ids_json FROM world_system_location_snapshots WHERE location_ref=?",(ref,)).fetchone()
                if row:
                    if row["payload_hash"]!=h or row["territory_ref"]!=territory or row["parent_ref"]!=parent or row["route_ids_json"]!=routes_text:
                        raise IntegrityError("location snapshot drift")
                    continue
                self.conn.execute("INSERT INTO world_system_location_snapshots VALUES(?,?,?,?,?,?,?,?)",(ref,kind,territory,parent,routes_text,source,text,h)); auxiliary_inserted+=1
        return {"status":"PASS","inserted":inserted,"counts":counts,"total":sum(counts.values()),"auxiliary_inserted":auxiliary_inserted,"auxiliary_total":len(location_rows),"authority":"MASTER_READ_ONLY_SNAPSHOT"}

    def _snapshots(self, category: str) -> list[dict[str,Any]]:
        rows=self.conn.execute("SELECT canonical_ref,payload_json,payload_hash FROM world_system_master_snapshots WHERE category=? ORDER BY canonical_ref",(category,)).fetchall();out=[]
        for r in rows:
            if sha256_text(r["payload_json"])!=r["payload_hash"]: raise IntegrityError("world system master snapshot hash mismatch")
            out.append(json.loads(r["payload_json"]))
        return out

    def _make_state(self, world: dict[str,Any], kind: str, canonical_ref: str, data: dict[str,Any]) -> dict[str,Any]:
        clock=world["clock_state"]; backed=self.runtime.canonical_ref_resolves(canonical_ref)
        body={"state_id":new_runtime_id("state"),"world_instance_id":world["world_instance_id"],"timeline_id":world["timeline_id"],"entity_runtime_id":new_runtime_id(kind.lower()),"origin":"CANONICAL_BACKED" if backed else "RUNTIME_BORN","entity_kind":kind,"lifecycle":"ACTIVE","version":0,"updated_at":clock_point(clock["day"],clock["tick"]),"data":copy.deepcopy(data),"protection":{},"runtime_authority":"RUNTIME_SYSTEM_STATE_NOT_CANON"}
        if backed: body["canonical_ref"]=canonical_ref
        else: body["data"]["source_ref"]=canonical_ref; body["data"]["source_ref_authority"]="MASTER_RECORD_REFERENCE_UNRESOLVED_AS_CANON_RUNTIME_ONLY"
        return body

    def _bind(self, world: dict[str,Any], kind: str, canonical_ref: str, entity_runtime_id: str, metadata: dict[str,Any]|None=None) -> None:
        bid=new_runtime_id("wsbind"); body={"binding_id":bid,"world_instance_id":world["world_instance_id"],"timeline_id":world["timeline_id"],"system_kind":kind,"canonical_ref":canonical_ref,"entity_runtime_id":entity_runtime_id,"metadata":copy.deepcopy(metadata or {}),"authority":"RUNTIME_BINDING_NOT_CANON"};text=canonical_json(body);h=sha256_text(text)
        self.conn.execute("INSERT INTO world_system_bindings VALUES(?,?,?,?,?,?,?,?)",(bid,world["world_instance_id"],world["timeline_id"],kind,canonical_ref,entity_runtime_id,text,h))

    def bootstrap_world(self, world_instance_id: str, *, population_seed: int=1000) -> dict[str,Any]:
        if not isinstance(population_seed,int) or isinstance(population_seed,bool) or population_seed<=0: raise ValidationError("population_seed must be positive integer")
        world=self.runtime.get_world(world_instance_id)
        if not self._snapshots("ROUTE"): raise ConflictError("load master snapshots before bootstrap")
        if self.conn.execute("SELECT 1 FROM world_system_bindings WHERE world_instance_id=? LIMIT 1",(world_instance_id,)).fetchone(): raise ConflictError("world systems already bootstrapped")
        created={"ROUTE_RUNTIME":0,"ECONOMIC_FLOW":0,"POPULATION_AGGREGATE":0,"FACTION_RUNTIME":0}
        # Materialize route operational projections.
        for r in self._snapshots("ROUTE") + self._snapshots("SECONDARY_ROUTE"):
            s=self._make_state(world,"ROUTE_RUNTIME",r["id"],{"route_ref":r["id"],"operational":True,"capacity_factor":1.0,"risk":r.get("risk"),"runtime_authority":"RUNTIME_ROUTE_OPERATION_NOT_CANON"}); self.runtime.register_entity(world_instance_id,s); self._bind(world,"ROUTE_RUNTIME",r["id"],s["entity_runtime_id"]);created["ROUTE_RUNTIME"]+=1
        # Materialize flows with deterministic runtime defaults, explicitly not canon.
        for f in self._snapshots("ECONOMIC_FLOW"):
            s=self._make_state(world,"ECONOMIC_FLOW",f["id"],{"flow_ref":f["id"],"product":f["product"],"product_category":self.classify_product(f["product"]),"origin_id":f["origin_id"],"processing_id":f["processing_id"],"destination_id":f["destination_id"],"destination_territory_ref":self.resolve_location(f["destination_id"]).get("territory_ref"),"route_ids":list(f.get("route_ids",[])),"stock":100.0,"production_rate":20.0,"consumption_rate":15.0,"base_price":10.0,"price":10.0,"shortage_pressure":0.0,"last_throughput":0.0,"runtime_seed_policy":"DETERMINISTIC_RUNTIME_DEFAULT_NOT_CANON"}); self.runtime.register_entity(world_instance_id,s);self._bind(world,"ECONOMIC_FLOW",f["id"],s["entity_runtime_id"]);created["ECONOMIC_FLOW"]+=1
        for p in self._snapshots("POPULATION_DISTRIBUTION"):
            s=self._make_state(world,"POPULATION_AGGREGATE",p["settlement_id"],{"settlement_ref":p["settlement_id"],"territory_ref":p["territory_id"],"count":population_seed,"labor_force":int(population_seed*0.55),"employed":int(population_seed*0.50),"unemployed":int(population_seed*0.05),"birth_accumulator":0.0,"death_accumulator":0.0,"migration_accumulator":0.0,"food_security":75.0,"welfare_index":70.0,"runtime_seed_policy":"NUMERIC_POPULATION_RUNTIME_ONLY_NOT_CANON"});self.runtime.register_entity(world_instance_id,s);self._bind(world,"POPULATION_AGGREGATE",p["settlement_id"],s["entity_runtime_id"],{"territory_ref":p["territory_id"]});created["POPULATION_AGGREGATE"]+=1
        for f in self._snapshots("FACTION_INFLUENCE"):
            scope=f.get("scope") or {}; fac=f["faction_ref"]
            s=self._make_state(world,"FACTION_RUNTIME",fac,{"faction_ref":fac,"territory_ref":scope.get("territory_id"),"influence":50.0,"treasury":1000.0,"security":50.0,"stability":50.0,"influence_not_sovereignty":True,"runtime_seed_policy":"RUNTIME_FACTION_STATE_NOT_CANON"});self.runtime.register_entity(world_instance_id,s);self._bind(world,"FACTION_RUNTIME",fac,s["entity_runtime_id"],{"presence_type":f.get("presence_type"),"scope":scope});created["FACTION_RUNTIME"]+=1
        return {"status":"PASS","created":created,"total":sum(created.values()),"population_seed":population_seed,"authority":"RUNTIME_SYSTEM_STATE_NOT_CANON"}

    def bootstrap_world_contextual(self, world_instance_id: str, *, population_seed: int=1000) -> dict[str,Any]:
        """V1.1 runtime-only contextual bootstrap.

        Canon supplies topology, product semantics and faction presence. Numeric values remain
        runtime balancing policy and are explicitly tagged as non-canonical. Legacy bootstrap
        remains unchanged for backward compatibility.
        """
        if not isinstance(population_seed,int) or isinstance(population_seed,bool) or population_seed<=0:
            raise ValidationError("population_seed must be positive integer")
        world=self.runtime.get_world(world_instance_id)
        routes=self._snapshots("ROUTE") + self._snapshots("SECONDARY_ROUTE")
        if not routes: raise ConflictError("load master snapshots before bootstrap")
        if self.conn.execute("SELECT 1 FROM world_system_bindings WHERE world_instance_id=? LIMIT 1",(world_instance_id,)).fetchone():
            raise ConflictError("world systems already bootstrapped")
        created={"ROUTE_RUNTIME":0,"ECONOMIC_FLOW":0,"POPULATION_AGGREGATE":0,"FACTION_RUNTIME":0}
        route_by_id={r["id"]:r for r in routes}
        # Runtime route projections preserve canonical topology while operational state stays mutable.
        for r in routes:
            s=self._make_state(world,"ROUTE_RUNTIME",r["id"],{"route_ref":r["id"],"operational":True,"capacity_factor":1.0,"risk":r.get("risk"),"runtime_authority":"RUNTIME_ROUTE_OPERATION_NOT_CANON"})
            self.runtime.register_entity(world_instance_id,s);self._bind(world,"ROUTE_RUNTIME",r["id"],s["entity_runtime_id"]);created["ROUTE_RUNTIME"]+=1
        # Population stays numeric-runtime-only. Canonical connectivity/support alter the seed instead of every settlement being identical.
        for p in self._snapshots("POPULATION_DISTRIBUTION"):
            settlement=p["settlement_id"]
            degree=sum(1 for r in routes if settlement in {r.get("origin_id"),r.get("destination_id")})
            support=len(p.get("support_basis") or [])
            multiplier=0.75 + min(degree,8)*0.05 + min(support,5)*0.02
            count=max(1,int(round(population_seed*multiplier)))
            labor=int(count*0.55); employed_ratio=min(0.53,0.45+min(degree,8)*0.01); employed=min(labor,int(count*employed_ratio)); unemployed=max(0,labor-employed)
            food=_clamp(68.0+min(support,5)*1.4,0,100); welfare=_clamp(62.0+min(degree,8)*1.5+min(support,5),0,100)
            data={"settlement_ref":settlement,"territory_ref":p["territory_id"],"count":count,"labor_force":labor,"employed":employed,"unemployed":unemployed,"birth_accumulator":0.0,"death_accumulator":0.0,"migration_accumulator":0.0,"food_security":round(food,4),"welfare_index":round(welfare,4),"contextual_seed":{"population_reference_seed":population_seed,"route_degree":degree,"support_basis_count":support,"multiplier":round(multiplier,4)},"runtime_seed_policy":"CONTEXTUAL_V1_1_NUMERIC_RUNTIME_ONLY_NOT_CANON"}
            s=self._make_state(world,"POPULATION_AGGREGATE",settlement,data);self.runtime.register_entity(world_instance_id,s);self._bind(world,"POPULATION_AGGREGATE",settlement,s["entity_runtime_id"],{"territory_ref":p["territory_id"]});created["POPULATION_AGGREGATE"]+=1
        # Faction operational state varies by canonical network reach, never by invented sovereignty.
        for f in self._snapshots("FACTION_INFLUENCE"):
            scope=f.get("scope") or {};fac=f["faction_ref"]; route_reach=len(scope.get("route_ids") or []); biome_reach=len(scope.get("biome_ids") or [])
            influence=_clamp(44.0+min(route_reach,10)*1.4,0,100); treasury=700.0+route_reach*80.0; security=_clamp(44.0+min(route_reach,10)*1.2+min(biome_reach,5)*0.8,0,100); stability=_clamp(48.0+min(route_reach,10)*0.7,0,100)
            data={"faction_ref":fac,"territory_ref":scope.get("territory_id"),"influence":round(influence,4),"treasury":round(treasury,4),"security":round(security,4),"stability":round(stability,4),"influence_not_sovereignty":True,"contextual_seed":{"route_reach":route_reach,"biome_reach":biome_reach,"presence_type":f.get("presence_type")},"runtime_seed_policy":"CONTEXTUAL_V1_1_FACTION_RUNTIME_NOT_CANON"}
            s=self._make_state(world,"FACTION_RUNTIME",fac,data);self.runtime.register_entity(world_instance_id,s);self._bind(world,"FACTION_RUNTIME",fac,s["entity_runtime_id"],{"presence_type":f.get("presence_type"),"scope":scope});created["FACTION_RUNTIME"]+=1
        category_policy={
            "FOOD":(8.0,24.0,18.0),"MEDICAL":(22.0,12.0,9.0),"MATERIAL":(16.0,18.0,12.0),"TECHNOLOGY":(28.0,10.0,7.0),"GENERAL":(12.0,15.0,10.0),
        }
        risk_weight={"BAIXO":0.00,"LOW":0.00,"MODERADO":0.08,"MODERATE":0.08,"CONTROLADO":0.04,"ALTO":0.18,"HIGH":0.18,"EXTREMO":0.28,"EXTREME":0.28}
        for f in self._snapshots("ECONOMIC_FLOW"):
            category=self.classify_product(f["product"]); price_base,prod_base,cons_base=category_policy.get(category,category_policy["GENERAL"]); route_ids=list(f.get("route_ids",[])); total_distance=0.0;risk=0.0
            for rr in route_ids:
                r=route_by_id.get(rr) or {}; total_distance+=float(r.get("distance_km") or 0.0); risk=max(risk,risk_weight.get(str(r.get("risk") or "").upper(),0.05))
            logistics=1.0+min(total_distance/2500.0,0.45)+risk
            destination=self.resolve_location(f["destination_id"]); pop_factor=self._population_factor(world_instance_id,f["destination_id"])
            production=round(prod_base/max(1.0,1.0+risk*0.5),4); consumption=round(cons_base*_clamp(pop_factor,0.5,2.0),4); base_price=round(price_base*logistics,4); stock=round(max(production,consumption)*5.0,4)
            data={"flow_ref":f["id"],"product":f["product"],"product_category":category,"origin_id":f["origin_id"],"processing_id":f["processing_id"],"destination_id":f["destination_id"],"destination_territory_ref":destination.get("territory_ref"),"route_ids":route_ids,"stock":stock,"production_rate":production,"consumption_rate":consumption,"base_price":base_price,"price":base_price,"shortage_pressure":0.0,"last_throughput":0.0,"labor_factor":1.0,"contextual_seed":{"route_distance_km":round(total_distance,4),"risk_factor":risk,"logistics_factor":round(logistics,4),"population_factor":round(pop_factor,4)},"runtime_seed_policy":"CONTEXTUAL_V1_1_ECONOMY_RUNTIME_ONLY_NOT_CANON"}
            s=self._make_state(world,"ECONOMIC_FLOW",f["id"],data);self.runtime.register_entity(world_instance_id,s);self._bind(world,"ECONOMIC_FLOW",f["id"],s["entity_runtime_id"]);created["ECONOMIC_FLOW"]+=1
        return {"status":"PASS","created":created,"total":sum(created.values()),"population_reference_seed":population_seed,"seed_policy":"CONTEXTUAL_V1_1_RUNTIME_ONLY_NOT_CANON","authority":"RUNTIME_SYSTEM_STATE_NOT_CANON"}

    def _entity_for(self, world_instance_id: str, kind: str, canonical_ref: str) -> dict[str,Any]:
        row=self.conn.execute("SELECT entity_runtime_id,binding_json,binding_hash FROM world_system_bindings WHERE world_instance_id=? AND system_kind=? AND canonical_ref=?",(world_instance_id,kind,canonical_ref)).fetchone()
        if not row: raise NotFoundError(f"world system binding not found: {kind}:{canonical_ref}")
        if sha256_text(row["binding_json"])!=row["binding_hash"]: raise IntegrityError("world system binding hash mismatch")
        return self.runtime.get_entity(world_instance_id,row["entity_runtime_id"])

    def _entities(self, world_instance_id: str, kind: str) -> list[dict[str,Any]]:
        rows=self.conn.execute("SELECT entity_runtime_id,binding_json,binding_hash FROM world_system_bindings WHERE world_instance_id=? AND system_kind=? ORDER BY canonical_ref",(world_instance_id,kind)).fetchall();out=[]
        for r in rows:
            if sha256_text(r["binding_json"])!=r["binding_hash"]: raise IntegrityError("world system binding hash mismatch")
            out.append(self.runtime.get_entity(world_instance_id,r["entity_runtime_id"]))
        return out

    def _action(self, world_instance_id: str, action_type: str, tick_key: str, targets: list[dict[str,Any]], consequences: list[dict[str,Any]], *, suffix: str) -> dict[str,Any]:
        world=self.runtime.get_world(world_instance_id); clock=world["clock_state"]
        action={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"actor_ref":"SYSTEM_ROUTINE","action_type":action_type,"parameters":{"tick_key":tick_key,"system":suffix},"precondition_snapshot":{"entity_versions":{e["entity_runtime_id"]:e["version"] for e in targets}},"idempotency_key":f"worldsys:{suffix}:{tick_key}","created_at":clock_point(clock["day"],clock["tick"]),"status":"SCHEDULED","source":"SYSTEM_ROUTINE","execution_class":"ROUTINE_SAFE"}
        return self.runtime.apply_action(world_instance_id,action,consequences)

    def _record_tick(self, world_instance_id: str, tick_key: str, name: str, mode: str, result: dict[str,Any]) -> dict[str,Any]:
        row=self.conn.execute("SELECT result_json,result_hash FROM world_system_tick_log WHERE world_instance_id=? AND tick_key=? AND system_name=?",(world_instance_id,tick_key,name)).fetchone()
        if row:
            if sha256_text(row["result_json"])!=row["result_hash"]: raise IntegrityError("world system tick hash mismatch")
            out=json.loads(row["result_json"]);out["idempotent_replay"]=True;return out
        world=self.runtime.get_world(world_instance_id);rid=new_runtime_id("wstick");body={"tick_record_id":rid,"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"tick_key":tick_key,"system_name":name,"mode":mode,**copy.deepcopy(result),"idempotent_replay":False};text=canonical_json(body);h=sha256_text(text)
        self.conn.execute("INSERT INTO world_system_tick_log(tick_record_id,world_instance_id,timeline_id,tick_key,system_name,mode,event_id,result_json,result_hash) VALUES(?,?,?,?,?,?,?,?,?)",(rid,world_instance_id,world["timeline_id"],tick_key,name,mode,result.get("event_id"),text,h));return body

    def set_route_operational(self, world_instance_id: str, route_ref: str, operational: bool, *, capacity_factor: float|None=None, reason: str="SYSTEMIC") -> dict[str,Any]:
        with self._lock, self.runtime._write_lock:
            if not isinstance(operational,bool): raise ValidationError("operational must be boolean")
            ent=self._entity_for(world_instance_id,"ROUTE_RUNTIME",route_ref); factor=(1.0 if operational else 0.0) if capacity_factor is None else float(capacity_factor)
            if factor<0 or factor>1: raise ValidationError("capacity_factor must be 0..1")
            world=self.runtime.get_world(world_instance_id);c=world["clock_state"]
            action={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"actor_ref":"SYSTEM_RECONCILIATION","action_type":"ROUTE_OPERATION_CHANGED","parameters":{"route_ref":route_ref,"operational":operational,"reason":reason},"precondition_snapshot":{"entity_versions":{ent["entity_runtime_id"]:ent["version"]}},"idempotency_key":f"route:{route_ref}:{operational}:{factor}:{ent['version']}","created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"SYSTEM_RECONCILIATION","execution_class":"ROUTINE_SAFE"}
            cons=[{"target_ref":ent["entity_runtime_id"],"operation":"SET","field_path":"data.operational","value":operational,"priority":0,"kind":"DIRECT"},{"target_ref":ent["entity_runtime_id"],"operation":"SET","field_path":"data.capacity_factor","value":factor,"priority":1,"kind":"DIRECT"}]
            return self.runtime.apply_action(world_instance_id,action,cons)

    @staticmethod
    def classify_product(product: str) -> str:
        key=str(product or "").strip().lower()
        return PRODUCT_CATEGORY_HINTS.get(key,"GENERAL")

    def resolve_location(self, canonical_ref: str) -> dict[str,Any]:
        row=self.conn.execute("SELECT location_kind,territory_ref,parent_ref,route_ids_json,payload_json,payload_hash FROM world_system_location_snapshots WHERE location_ref=?",(canonical_ref,)).fetchone()
        if row:
            if sha256_text(row["payload_json"])!=row["payload_hash"]: raise IntegrityError("location snapshot hash mismatch")
            return {"location_ref":canonical_ref,"kind":row["location_kind"],"territory_ref":row["territory_ref"],"parent_ref":row["parent_ref"],"route_ids":json.loads(row["route_ids_json"]),"method":"MASTER_SPATIAL_SNAPSHOT"}
        # Settlements already carry their canonical territory binding.
        prow=self.conn.execute("SELECT payload_json,payload_hash FROM world_system_master_snapshots WHERE category='POPULATION_DISTRIBUTION' AND canonical_ref=?",(canonical_ref,)).fetchone()
        if prow:
            if sha256_text(prow["payload_json"])!=prow["payload_hash"]: raise IntegrityError("population snapshot hash mismatch")
            payload=json.loads(prow["payload_json"]); return {"location_ref":canonical_ref,"kind":"SETTLEMENT","territory_ref":payload.get("territory_id"),"parent_ref":None,"route_ids":[],"method":"MASTER_POPULATION_SNAPSHOT"}
        return {"location_ref":canonical_ref,"kind":"UNKNOWN","territory_ref":None,"parent_ref":None,"route_ids":[],"method":"UNRESOLVED"}

    def resolve_destination_population(self, world_instance_id: str, destination_ref: str) -> dict[str,Any]:
        try:
            p=self._entity_for(world_instance_id,"POPULATION_AGGREGATE",destination_ref)
            count=int(p["data"]["count"]); territory=p["data"].get("territory_ref")
            return {"status":"RESOLVED","destination_ref":destination_ref,"territory_ref":territory,"settlement_refs":[p["data"]["settlement_ref"]],"population":count,"factor":max(0.25,count/1000.0),"method":"DIRECT_SETTLEMENT"}
        except NotFoundError:
            pass
        loc=self.resolve_location(destination_ref); territory=loc.get("territory_ref")
        if not territory:
            return {"status":"UNRESOLVED","destination_ref":destination_ref,"territory_ref":None,"settlement_refs":[],"population":0,"factor":1.0,"method":"SAFE_RUNTIME_FALLBACK"}
        matches=[p for p in self._entities(world_instance_id,"POPULATION_AGGREGATE") if p["data"].get("territory_ref")==territory]
        if not matches:
            return {"status":"UNRESOLVED","destination_ref":destination_ref,"territory_ref":territory,"settlement_refs":[],"population":0,"factor":1.0,"method":"NO_POPULATION_IN_TERRITORY"}
        count=sum(max(0,int(p["data"]["count"])) for p in matches)
        return {"status":"RESOLVED","destination_ref":destination_ref,"territory_ref":territory,"settlement_refs":[p["data"]["settlement_ref"] for p in matches],"population":count,"factor":max(0.25,count/1000.0),"method":"DESTINATION_TERRITORY"}

    def _population_factor(self, world_instance_id: str, destination_ref: str) -> float:
        return float(self.resolve_destination_population(world_instance_id,destination_ref)["factor"])

    def route_capacity_for_location(self, world_instance_id: str, location_ref: str) -> dict[str,Any]:
        loc=self.resolve_location(location_ref); refs=list(loc.get("route_ids",[])); samples=[]
        for rr in refs:
            try:
                rte=self._entity_for(world_instance_id,"ROUTE_RUNTIME",rr); d=rte["data"]
                cap=float(d.get("capacity_factor",1.0)) if d.get("operational",True) else 0.0
                samples.append((rr,_clamp(cap,0,1)))
            except NotFoundError:
                continue
        if not samples:
            return {"location_ref":location_ref,"capacity":1.0,"routes":[],"method":"NO_RUNTIME_ROUTE_FALLBACK"}
        # Multiple access routes create resilience: average available capacity is a better market signal than weakest-link.
        cap=sum(v for _,v in samples)/len(samples)
        return {"location_ref":location_ref,"capacity":round(_clamp(cap,0,1),4),"routes":[{"route_ref":r,"capacity":v} for r,v in samples],"method":"MASTER_LOCATION_RUNTIME_ROUTE_AVERAGE"}

    def local_product_pressure(self, world_instance_id: str, territory_ref: str|None, category: str) -> dict[str,Any]:
        category=str(category or "GENERAL").upper(); flows=self._entities(world_instance_id,"ECONOMIC_FLOW")
        matching=[f for f in flows if f["data"].get("product_category")==category and territory_ref and f["data"].get("destination_territory_ref")==territory_ref]
        scope="LOCAL"
        if not matching:
            matching=[f for f in flows if f["data"].get("product_category")==category]; scope="GLOBAL_CATEGORY_FALLBACK"
        if not matching:
            return {"category":category,"territory_ref":territory_ref,"pressure":0.0,"flow_refs":[],"scope":"NO_MATCH"}
        pressure=sum(float(f["data"].get("shortage_pressure",0.0)) for f in matching)/len(matching)
        return {"category":category,"territory_ref":territory_ref,"pressure":round(_clamp(pressure,0,100),4),"flow_refs":[f["data"]["flow_ref"] for f in matching],"scope":scope}

    def _economy_tick_locked(self, world_instance_id: str, tick_key: str, mode: str) -> dict[str,Any]:
        if mode not in ALLOWED_MODES: raise ValidationError("invalid mode")
        prior=self.conn.execute("SELECT result_json,result_hash FROM world_system_tick_log WHERE world_instance_id=? AND tick_key=? AND system_name='ECONOMY'",(world_instance_id,tick_key)).fetchone()
        if prior:
            if sha256_text(prior["result_json"])!=prior["result_hash"]: raise IntegrityError("economy tick hash mismatch")
            r=json.loads(prior["result_json"]);r["idempotent_replay"]=True;return r
        flows=self._entities(world_instance_id,"ECONOMIC_FLOW"); consequences=[];metrics={"flows":len(flows),"produced":0.0,"consumed":0.0,"shortage":0.0,"activity":0.0}
        for e in flows:
            d=e["data"]; route_factor=1.0
            for rr in d.get("route_ids",[]):
                rte=self._entity_for(world_instance_id,"ROUTE_RUNTIME",rr); rd=rte["data"]; route_factor=min(route_factor,float(rd["capacity_factor"]) if rd["operational"] else 0.0)
            labor_factor=_clamp(float(d.get("labor_factor",1.0)),0.25,1.5)
            produced=float(d["production_rate"])*route_factor*labor_factor; demand=float(d["consumption_rate"])*self._population_factor(world_instance_id,d["destination_id"]); available=float(d["stock"])+produced; consumed=min(available,demand); stock=max(0.0,available-consumed); shortage=max(0.0,demand-consumed); pressure=0.0 if demand<=0 else _clamp(shortage/demand*100.0,0,100); scarcity=(pressure/100.0); price=round(_clamp(float(d["base_price"])*(1.0+1.5*scarcity),float(d["base_price"])*0.5,float(d["base_price"])*3.0),4)
            vals={"stock":round(stock,4),"price":price,"shortage_pressure":round(pressure,4),"last_throughput":round(consumed,4)}
            for i,(k,v) in enumerate(vals.items()): consequences.append({"target_ref":e["entity_runtime_id"],"operation":"SET","field_path":f"data.{k}","value":v,"priority":i,"kind":"DIRECT"})
            metrics["produced"]+=produced;metrics["consumed"]+=consumed;metrics["shortage"]+=shortage;metrics["activity"]+=consumed*price
        res=self._action(world_instance_id,"WORLD_SYSTEM_ECONOMY_TICK",tick_key,flows,consequences,suffix="economy");metrics={k:round(v,4) if isinstance(v,float) else v for k,v in metrics.items()};metrics.update({"status":"PASS","event_id":res["event_id"],"metrics":metrics.copy()})
        return self._record_tick(world_instance_id,tick_key,"ECONOMY",mode,metrics)

    def _population_tick_locked(self, world_instance_id: str, tick_key: str, mode: str) -> dict[str,Any]:
        if mode not in ALLOWED_MODES: raise ValidationError("invalid mode")
        prior=self.conn.execute("SELECT result_json,result_hash FROM world_system_tick_log WHERE world_instance_id=? AND tick_key=? AND system_name='POPULATION'",(world_instance_id,tick_key)).fetchone()
        if prior:
            if sha256_text(prior["result_json"])!=prior["result_hash"]: raise IntegrityError("population tick hash mismatch")
            r=json.loads(prior["result_json"]);r["idempotent_replay"]=True;return r
        pops=self._entities(world_instance_id,"POPULATION_AGGREGATE");flows=self._entities(world_instance_id,"ECONOMIC_FLOW"); consequences=[];tot={"settlements":len(pops),"births":0,"deaths":0,"migration":0,"population_before":0,"population_after":0,"food_pressure_by_territory":{}}
        facs=self._entities(world_instance_id,"FACTION_RUNTIME"); security_by_territory={f["data"].get("territory_ref"):float(f["data"]["security"]) for f in facs}
        for e in pops:
            d=e["data"];count=int(d["count"]);tot["population_before"]+=count; food_pressure=self.local_product_pressure(world_instance_id,d.get("territory_ref"),"FOOD"); tot["food_pressure_by_territory"][str(d.get("territory_ref"))]=food_pressure; food=_clamp(100.0-float(food_pressure["pressure"]),0,100); birth_acc=float(d["birth_accumulator"])+count*0.00020*(0.5+food/200); death_acc=float(d["death_accumulator"])+count*(0.00010+(100-food)*0.000002); births=int(birth_acc); deaths=int(death_acc);birth_acc-=births;death_acc-=deaths
            mig_acc=float(d["migration_accumulator"]);migration=0
            if mode!="ROUTINE_OFFLINE":
                sec=security_by_territory.get(d.get("territory_ref"),50.0); opportunity=(float(d["employed"])/max(1,float(d["labor_force"])))*100; mig_acc += (sec-50.0+opportunity-75.0)*count/1_000_000.0; migration=math.trunc(mig_acc);mig_acc-=migration
            new_count=max(0,count+births-deaths+migration); labor=int(new_count*0.55); jobs=max(0,int(new_count*(0.46+food/1000.0))); employed=min(labor,jobs);unemployed=max(0,labor-employed);welfare=_clamp(0.55*food+0.45*(100*(employed/max(1,labor))),0,100)
            vals={"count":new_count,"labor_force":labor,"employed":employed,"unemployed":unemployed,"birth_accumulator":round(birth_acc,8),"death_accumulator":round(death_acc,8),"migration_accumulator":round(mig_acc,8),"food_security":round(food,4),"welfare_index":round(welfare,4)}
            for i,(k,v) in enumerate(vals.items()): consequences.append({"target_ref":e["entity_runtime_id"],"operation":"SET","field_path":f"data.{k}","value":v,"priority":i,"kind":"DIRECT"})
            tot["births"]+=births;tot["deaths"]+=deaths;tot["migration"]+=migration;tot["population_after"]+=new_count
        res=self._action(world_instance_id,"WORLD_SYSTEM_POPULATION_TICK",tick_key,pops,consequences,suffix="population");out={"status":"PASS","event_id":res["event_id"],"metrics":tot};return self._record_tick(world_instance_id,tick_key,"POPULATION",mode,out)

    def faction_runtime_context(self, world_instance_id: str, faction_ref: str) -> dict[str,Any]:
        """Resolve the runtime context a faction may legitimately react to.

        Canonical faction scope is read-only. Numeric relation stance and systemic outcomes are
        Living runtime state and never imply sovereignty changes.
        """
        ent=self._entity_for(world_instance_id,"FACTION_RUNTIME",faction_ref)
        brow=self.conn.execute("SELECT binding_json,binding_hash FROM world_system_bindings WHERE world_instance_id=? AND system_kind='FACTION_RUNTIME' AND canonical_ref=?",(world_instance_id,faction_ref)).fetchone()
        if not brow: raise NotFoundError(f"faction binding not found: {faction_ref}")
        if sha256_text(brow["binding_json"])!=brow["binding_hash"]: raise IntegrityError("faction binding hash mismatch")
        binding=json.loads(brow["binding_json"]); scope=((binding.get("metadata") or {}).get("scope") or {})
        territory=scope.get("territory_id") or ent["data"].get("territory_ref"); scope_routes=set(scope.get("route_ids") or [])

        relation_rows=self.conn.execute("SELECT relation_id,source_faction_ref,target_faction_ref,stance,relation_json,relation_hash FROM faction_relations_runtime WHERE world_instance_id=? AND (source_faction_ref=? OR target_faction_ref=?) ORDER BY source_faction_ref,target_faction_ref",(world_instance_id,faction_ref,faction_ref)).fetchall()
        stances=[]; relations=[]
        for row in relation_rows:
            if sha256_text(row["relation_json"])!=row["relation_hash"]: raise IntegrityError(f"faction relation hash mismatch: {row['relation_id']}")
            stance=float(row["stance"]); stances.append(stance); relations.append({"relation_id":row["relation_id"],"source_faction_ref":row["source_faction_ref"],"target_faction_ref":row["target_faction_ref"],"stance":stance})
        diplomacy=sum(stances)/len(stances) if stances else 0.0

        flows=self._entities(world_instance_id,"ECONOMIC_FLOW"); local_flows=[]
        for flow in flows:
            fd=flow["data"]; flow_routes=set(fd.get("route_ids") or [])
            if (territory and fd.get("destination_territory_ref")==territory) or (scope_routes and flow_routes.intersection(scope_routes)):
                local_flows.append(flow)
        pops=[p for p in self._entities(world_instance_id,"POPULATION_AGGREGATE") if territory and p["data"].get("territory_ref")==territory]
        labor=sum(max(0,int(p["data"].get("labor_force",0))) for p in pops); unemployed=sum(max(0,int(p["data"].get("unemployed",0))) for p in pops)
        unemployment=(unemployed/max(1,labor)) if pops else 0.0
        activity=sum(max(0.0,float(f["data"].get("last_throughput",0.0)))*max(0.0,float(f["data"].get("price",0.0))) for f in local_flows)
        return {"status":"RESOLVED","faction_ref":faction_ref,"territory_ref":territory,"scope_route_ids":sorted(scope_routes),"economic_flow_refs":[f["data"]["flow_ref"] for f in local_flows],"economic_activity":round(activity,6),"population_refs":[p["data"]["settlement_ref"] for p in pops],"labor_force":labor,"unemployed":unemployed,"unemployment_ratio":round(unemployment,8),"diplomatic_stance":round(diplomacy,6),"relations":relations,"authority":"RUNTIME_CONTEXT_FROM_CANON_SCOPE_NOT_SOVEREIGNTY"}

    def _faction_tick_locked(self, world_instance_id: str, tick_key: str, mode: str) -> dict[str,Any]:
        if mode not in ALLOWED_MODES: raise ValidationError("invalid mode")
        prior=self.conn.execute("SELECT result_json,result_hash FROM world_system_tick_log WHERE world_instance_id=? AND tick_key=? AND system_name='FACTION'",(world_instance_id,tick_key)).fetchone()
        if prior:
            if sha256_text(prior["result_json"])!=prior["result_hash"]: raise IntegrityError("faction tick hash mismatch")
            r=json.loads(prior["result_json"]);r["idempotent_replay"]=True;return r
        facs=self._entities(world_instance_id,"FACTION_RUNTIME"); consequences=[];tot={"factions":len(facs),"treasury_delta":0.0,"influence_delta":0.0,"contexts":{}}
        for e in facs:
            d=e["data"]; fac=d["faction_ref"];ctx=self.faction_runtime_context(world_instance_id,fac);local_activity=float(ctx["economic_activity"]);unemployment=float(ctx["unemployment_ratio"]);diplomacy=float(ctx["diplomatic_stance"]);legal_pressure=_clamp(float(d.get("legal_pressure",0.0)),0,100)
            trade_factor=_clamp(1.0+diplomacy/500.0,0.80,1.20); revenue=local_activity*0.001*trade_factor; treasury=float(d["treasury"])+revenue
            target_security=_clamp(70.0-unemployment*80.0-legal_pressure*0.30+diplomacy*0.04,20,90);security=float(d["security"])+(target_security-float(d["security"]))*0.05
            stability=_clamp(0.6*security+0.4*(100-unemployment*100)-legal_pressure*0.10+diplomacy*0.03,0,100); influence=float(d["influence"])
            if mode!="ROUTINE_OFFLINE": influence=_clamp(influence+(stability-50.0)*0.002,0,100)
            vals={"treasury":round(treasury,4),"security":round(security,4),"stability":round(stability,4),"influence":round(influence,4),"influence_not_sovereignty":True,"last_faction_context":{"economic_activity":round(local_activity,4),"unemployment_ratio":round(unemployment,6),"diplomatic_stance":round(diplomacy,4),"trade_factor":round(trade_factor,4),"legal_pressure":round(legal_pressure,4),"runtime_only":True}}
            for i,(k,v) in enumerate(vals.items()): consequences.append({"target_ref":e["entity_runtime_id"],"operation":"SET","field_path":f"data.{k}","value":v,"priority":i,"kind":"DIRECT"})
            tot["treasury_delta"]+=treasury-float(d["treasury"]);tot["influence_delta"]+=influence-float(d["influence"]);tot["contexts"][fac]={"economic_activity":round(local_activity,4),"unemployment_ratio":round(unemployment,6),"diplomatic_stance":round(diplomacy,4),"revenue_delta":round(revenue,4)}
        res=self._action(world_instance_id,"WORLD_SYSTEM_FACTION_TICK",tick_key,facs,consequences,suffix="faction");tot={k:round(v,6) if isinstance(v,float) else v for k,v in tot.items()};out={"status":"PASS","event_id":res["event_id"],"metrics":tot,"authority":"RUNTIME_FACTION_DYNAMICS_NOT_CANON"};return self._record_tick(world_instance_id,tick_key,"FACTION",mode,out)

    def economy_tick(self, world_instance_id: str, tick_key: str, mode: str) -> dict[str,Any]:
        with self._lock, self.runtime._write_lock:
            return self._economy_tick_locked(world_instance_id,tick_key,mode)

    def population_tick(self, world_instance_id: str, tick_key: str, mode: str) -> dict[str,Any]:
        with self._lock, self.runtime._write_lock:
            return self._population_tick_locked(world_instance_id,tick_key,mode)

    def faction_tick(self, world_instance_id: str, tick_key: str, mode: str) -> dict[str,Any]:
        with self._lock, self.runtime._write_lock:
            return self._faction_tick_locked(world_instance_id,tick_key,mode)

    def extension_handler(self, context: dict[str,Any]) -> dict[str,Any]:
        wid=context["world_instance_id"];mode=context["simulation_mode"];tick_key=context["tick_key"]
        economy=self.economy_tick(wid,tick_key,mode);population=self.population_tick(wid,tick_key,mode);faction=self.faction_tick(wid,tick_key,mode)
        return {"status":"PASS","authority":"RUNTIME_WORLD_SYSTEMS_NOT_CANON","mode":mode,"economy":economy,"population":population,"faction":faction}

    def attach_to_orchestrator(self, orchestrator: Any, world_instance_id: str) -> dict[str,Any]:
        return orchestrator.attach_extension(world_instance_id,self.EXTENSION_KEY,self.extension_handler,version=self.EXTENSION_VERSION,modes=set(ALLOWED_MODES),cadence_ticks=1,routine_safe=True)

    def bind_to_orchestrator(self, orchestrator: Any, world_instance_id: str) -> dict[str,Any]:
        return orchestrator.bind_extension_handler(world_instance_id,self.EXTENSION_KEY,self.extension_handler)

    def set_faction_relation(self, world_instance_id: str, source_faction_ref: str, target_faction_ref: str, stance: float) -> dict[str,Any]:
        stance=float(stance)
        if not -100<=stance<=100: raise ValidationError("stance must be -100..100")
        self._entity_for(world_instance_id,"FACTION_RUNTIME",source_faction_ref);self._entity_for(world_instance_id,"FACTION_RUNTIME",target_faction_ref)
        rid=new_runtime_id("facrel")
        with self._lock,self.runtime._write_lock:
            old=self.conn.execute("SELECT relation_id FROM faction_relations_runtime WHERE world_instance_id=? AND source_faction_ref=? AND target_faction_ref=?",(world_instance_id,source_faction_ref,target_faction_ref)).fetchone()
            if old: rid=old["relation_id"]
            body={"relation_id":rid,"world_instance_id":world_instance_id,"source_faction_ref":source_faction_ref,"target_faction_ref":target_faction_ref,"stance":stance,"authority":"RUNTIME_FACTION_RELATION_NOT_CANON"};text=canonical_json(body);h=sha256_text(text)
            if old:self.conn.execute("UPDATE faction_relations_runtime SET stance=?,relation_json=?,relation_hash=? WHERE relation_id=?",(stance,text,h,rid))
            else:self.conn.execute("INSERT INTO faction_relations_runtime VALUES(?,?,?,?,?,?,?)",(rid,world_instance_id,source_faction_ref,target_faction_ref,stance,text,h))
        return body

    def summary(self, world_instance_id: str) -> dict[str,Any]:
        return {"routes":len(self._entities(world_instance_id,"ROUTE_RUNTIME")),"flows":len(self._entities(world_instance_id,"ECONOMIC_FLOW")),"populations":len(self._entities(world_instance_id,"POPULATION_AGGREGATE")),"factions":len(self._entities(world_instance_id,"FACTION_RUNTIME")),"ticks":self.conn.execute("SELECT COUNT(*) c FROM world_system_tick_log WHERE world_instance_id=?",(world_instance_id,)).fetchone()["c"]}

    def full_integrity_check(self, world_instance_id: str) -> dict[str,Any]:
        failures=[]
        with self._lock,self.runtime._write_lock:
            for r in self.conn.execute("SELECT snapshot_key,payload_json,payload_hash FROM world_system_master_snapshots").fetchall():
                if sha256_text(r["payload_json"])!=r["payload_hash"]:failures.append(f"SNAPSHOT_HASH:{r['snapshot_key']}")
            for r in self.conn.execute("SELECT location_ref,payload_json,payload_hash,route_ids_json FROM world_system_location_snapshots").fetchall():
                if sha256_text(r["payload_json"])!=r["payload_hash"]:failures.append(f"LOCATION_SNAPSHOT_HASH:{r['location_ref']}")
                try: json.loads(r["route_ids_json"])
                except Exception: failures.append(f"LOCATION_ROUTE_JSON:{r['location_ref']}")
            for r in self.conn.execute("SELECT binding_id,binding_json,binding_hash,entity_runtime_id FROM world_system_bindings WHERE world_instance_id=?",(world_instance_id,)).fetchall():
                if sha256_text(r["binding_json"])!=r["binding_hash"]:failures.append(f"BINDING_HASH:{r['binding_id']}")
                try:self.runtime.get_entity(world_instance_id,r["entity_runtime_id"])
                except Exception:failures.append(f"BINDING_ENTITY:{r['binding_id']}")
            for r in self.conn.execute("SELECT tick_record_id,result_json,result_hash FROM world_system_tick_log WHERE world_instance_id=?",(world_instance_id,)).fetchall():
                if sha256_text(r["result_json"])!=r["result_hash"]:failures.append(f"TICK_HASH:{r['tick_record_id']}")
            for r in self.conn.execute("SELECT relation_id,relation_json,relation_hash,stance FROM faction_relations_runtime WHERE world_instance_id=?",(world_instance_id,)).fetchall():
                if sha256_text(r["relation_json"])!=r["relation_hash"]:failures.append(f"FACTION_REL_HASH:{r['relation_id']}")
                if not -100<=r["stance"]<=100:failures.append(f"FACTION_REL_RANGE:{r['relation_id']}")
        raw_summary={k:self.conn.execute("SELECT COUNT(*) c FROM world_system_bindings WHERE world_instance_id=? AND system_kind=?",(world_instance_id,kind)).fetchone()["c"] for k,kind in [("routes","ROUTE_RUNTIME"),("flows","ECONOMIC_FLOW"),("populations","POPULATION_AGGREGATE"),("factions","FACTION_RUNTIME")]}
        raw_summary["ticks"]=self.conn.execute("SELECT COUNT(*) c FROM world_system_tick_log WHERE world_instance_id=?",(world_instance_id,)).fetchone()["c"]
        return {"status":"PASS" if not failures else "FAIL","failures":failures,"summary":raw_summary}
