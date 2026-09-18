from __future__ import annotations

import copy
import hashlib
import heapq
import json
import math
import threading
from typing import Any

from living_runtime import (
    LivingRuntime, EventEnvelope, ValidationError, IntegrityError, ConflictError,
    NotFoundError, canonical_json, sha256_text, new_runtime_id, clock_point,
)


RUNTIME_POLICY = "MOBILITY_BIOLOGY_V1_1_RUNTIME_NOT_CANON"
METABOLISM_POLICY = {
    "hunger_per_day": 18.0,
    "thirst_per_day": 24.0,
    "energy_loss_per_day": 8.0,
    "stress_recovery_per_day": 8.0,
    "deprivation_stress_per_day": 28.0,
    "contamination_stress_per_day_at_100": 20.0,
    "smoke_stress_per_day_at_100": 14.0,
    "biological_death_threshold": 100.0,
}


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(v)))


def _abs_tick(clock: dict[str, Any]) -> int:
    return int(clock["day"]) * int(clock["ticks_per_day"]) + int(clock["tick"])


class MobilityBiologySystem:
    """Route-backed travel, ecological movement and bounded biological time.

    Canon remains read-only. Numeric travel fallbacks and metabolism rates are explicit
    runtime balancing policy, not canonical facts.
    """

    SCHEMA_VERSION = 1
    EXTENSION_KEY = "mobility_biology"
    EXTENSION_VERSION = "V1.1-DEV"
    MOVEMENT_EVENTS = {"ECO_FLEE", "ECO_PATROL"}

    def __init__(self, runtime: LivingRuntime, world_systems: Any, ecology: Any, *, domain_hub: Any | None = None) -> None:
        if world_systems.runtime is not runtime or ecology.runtime is not runtime:
            raise ValidationError("mobility/biology dependencies must share LivingRuntime")
        self.runtime = runtime
        self.world_systems = world_systems
        self.ecology = ecology
        self.domain_hub = domain_hub
        self.conn = runtime.conn
        self._lock = threading.RLock()
        self._unsubscribe = None
        self._initialize_schema()
        self.attach()

    def _initialize_schema(self) -> None:
        with self.runtime._write_lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mobility_event_queue(
                    event_id TEXT PRIMARY KEY REFERENCES events(event_id) ON DELETE RESTRICT,
                    world_instance_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','COMPLETED','SKIPPED','FAILED')),
                    result_json TEXT,
                    result_hash TEXT,
                    last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS mobility_effects(
                    effect_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE RESTRICT,
                    world_instance_id TEXT NOT NULL,
                    effect_key TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('APPLIED','SKIPPED')),
                    effect_json TEXT NOT NULL,
                    effect_hash TEXT NOT NULL,
                    UNIQUE(event_id,effect_key)
                );
                CREATE TRIGGER IF NOT EXISTS mobility_effect_no_update BEFORE UPDATE ON mobility_effects
                    BEGIN SELECT RAISE(ABORT,'mobility effects immutable'); END;
                CREATE TRIGGER IF NOT EXISTS mobility_effect_no_delete BEFORE DELETE ON mobility_effects
                    BEGIN SELECT RAISE(ABORT,'mobility effects immutable'); END;

                CREATE TABLE IF NOT EXISTS travel_plans(
                    travel_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    traveler_ref TEXT NOT NULL,
                    origin_ref TEXT NOT NULL,
                    destination_ref TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PLANNED','IN_TRANSIT','ARRIVED','BLOCKED','CANCELLED')),
                    due_abs_tick INTEGER NOT NULL,
                    plan_json TEXT NOT NULL,
                    plan_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_travel_due ON travel_plans(world_instance_id,status,due_abs_tick);

                CREATE TABLE IF NOT EXISTS biology_tick_log(
                    record_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    entity_ref TEXT NOT NULL,
                    tick_key TEXT NOT NULL,
                    event_id TEXT,
                    result_json TEXT NOT NULL,
                    result_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id,entity_ref,tick_key)
                );
                CREATE TRIGGER IF NOT EXISTS biology_tick_no_update BEFORE UPDATE ON biology_tick_log
                    BEGIN SELECT RAISE(ABORT,'biology tick log immutable'); END;
                CREATE TRIGGER IF NOT EXISTS biology_tick_no_delete BEFORE DELETE ON biology_tick_log
                    BEGIN SELECT RAISE(ABORT,'biology tick log immutable'); END;
                """
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('mobility_biology_schema_version',?)",
                (str(self.SCHEMA_VERSION),),
            )

    def attach(self) -> None:
        if self._unsubscribe is not None:
            return
        def handler(event: EventEnvelope) -> None:
            if event.event_type not in self.MOVEMENT_EVENTS:
                return
            try:
                with self._lock, self.runtime._write_lock:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO mobility_event_queue(event_id,world_instance_id,event_type,status) VALUES(?,?,?,'PENDING')",
                        (event.event_id, event.world_instance_id, event.event_type),
                    )
            except Exception:
                return
        self._unsubscribe = self.runtime.event_bus.subscribe(handler)

    def detach(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe(); self._unsubscribe = None

    # ---------- Canon-backed route graph ----------
    def _route_runtime_state(self, world_instance_id: str, route_ref: str) -> dict[str, Any] | None:
        try:
            return self.world_systems._entity_for(world_instance_id, "ROUTE_RUNTIME", route_ref)
        except NotFoundError:
            return None

    def _route_speed(self, route: dict[str, Any], requested_mode: str | None = None) -> tuple[str, float, str]:
        bands = route.get("speed_bands_kmh") or {}
        if requested_mode and requested_mode in bands:
            vals = bands[requested_mode]
            return requested_mode, float(sum(vals) / len(vals)), "MASTER_SPEED_BAND_MIDPOINT"
        candidates: list[tuple[float, str]] = []
        for mode, vals in bands.items():
            if isinstance(vals, list) and vals:
                candidates.append((float(sum(vals) / len(vals)), str(mode)))
        if candidates:
            speed, mode = sorted(candidates, reverse=True)[0]
            return mode, speed, "MASTER_SPEED_BAND_FASTEST_AVAILABLE_RUNTIME_SELECTION"
        modes = list(route.get("transport_modes") or [])
        mode = requested_mode if requested_mode in modes else (str(modes[0]) if modes else "runtime_walk")
        # Secondary local routes lack speed bands. This is an explicit runtime policy,
        # not a canonical travel speed.
        speed = 5.0 if mode in {"a pé", "runtime_walk"} else 20.0
        return mode, speed, "RUNTIME_SECONDARY_ROUTE_SPEED_POLICY_NOT_CANON"

    def _anchor(self, ref: str) -> str:
        seen: set[str] = set(); cur = ref
        for _ in range(4):
            if cur in seen: break
            seen.add(cur)
            loc = self.world_systems.resolve_location(cur)
            parent = loc.get("parent_ref")
            if not isinstance(parent, str) or not parent:
                return cur
            cur = parent
        return cur

    def _graph(self, world_instance_id: str, clearance_level: int, requested_mode: str | None = None) -> dict[str, list[dict[str, Any]]]:
        graph: dict[str, list[dict[str, Any]]] = {}
        for category in ("ROUTE", "SECONDARY_ROUTE"):
            for route in self.world_systems._snapshots(category):
                rr = route.get("id")
                if not isinstance(rr, str): continue
                rte = self._route_runtime_state(world_instance_id, rr)
                if rte is None or not bool(rte.get("data", {}).get("operational", True)) or float(rte.get("data", {}).get("capacity_factor", 1.0)) <= 0:
                    continue
                access = int(route.get("access_level", 0) or 0)
                if access > int(clearance_level):
                    continue
                o, d = route.get("origin_id"), route.get("destination_id")
                if not isinstance(o, str) or not isinstance(d, str): continue
                mode, speed, speed_basis = self._route_speed(route, requested_mode)
                dist = float(route.get("distance_km") or route.get("geometry_distance_km") or 0.0)
                if dist <= 0 or speed <= 0: continue
                edge = {"route_ref":rr,"from":o,"to":d,"distance_km":dist,"mode":mode,"speed_kmh":speed,"hours":dist/speed,"speed_basis":speed_basis,"risk":route.get("risk"),"access_level":access,"category":category}
                graph.setdefault(o, []).append(edge)
                if bool(route.get("bidirectional", category == "SECONDARY_ROUTE")):
                    rev = dict(edge); rev["from"], rev["to"] = d, o
                    graph.setdefault(d, []).append(rev)
        return graph

    def plan_travel(self, world_instance_id: str, traveler_ref: str, destination_ref: str, *, requested_mode: str | None = None) -> dict[str, Any]:
        traveler = self.runtime.get_entity(world_instance_id, traveler_ref)
        if traveler.get("lifecycle") != "ACTIVE": raise ConflictError("traveler is not active")
        data = traveler.get("data") or {}
        existing = data.get("travel") if isinstance(data.get("travel"), dict) else None
        if existing and existing.get("status") == "IN_TRANSIT": raise ConflictError("traveler already in transit")
        origin_ref = data.get("location_ref") or data.get("poi_ref") or data.get("site_ref")
        if not isinstance(origin_ref, str): raise ConflictError("traveler has no route-resolvable location")
        if not self.runtime.canonical_ref_resolves(destination_ref): raise ValidationError("destination_ref must be canonical")
        origin_anchor, destination_anchor = self._anchor(origin_ref), self._anchor(destination_ref)
        clearance = int(data.get("clearance_level", 0) or 0)
        graph = self._graph(world_instance_id, clearance, requested_mode)
        if origin_anchor == destination_anchor:
            loc = self.world_systems.resolve_location(destination_ref)
            route_refs = list(loc.get("route_ids") or [])
            direct = None
            for rr in route_refs:
                for edges in graph.values():
                    for e in edges:
                        if e["route_ref"] == rr and {e["from"],e["to"]} == {origin_anchor,destination_ref}:
                            direct=e;break
                    if direct:break
                if direct:break
            if direct:
                path=[direct]
            elif origin_ref != destination_ref:
                # Same parent location but no Master route means no invented micro-route.
                raise ConflictError("no canonical/runtime route resolves local destination")
            else:
                path=[]
        else:
            pq=[(0.0,origin_anchor,[])]; best={origin_anchor:0.0}; path=None
            while pq:
                cost,node,p=heapq.heappop(pq)
                if cost != best.get(node): continue
                if node == destination_anchor: path=p;break
                for e in graph.get(node,[]):
                    nc=cost+float(e["hours"])
                    if nc < best.get(e["to"],math.inf):
                        best[e["to"]]=nc; heapq.heappush(pq,(nc,e["to"],p+[e]))
            if path is None: raise ConflictError("no operational authorized canonical route to destination")
        total_hours=sum(float(e["hours"]) for e in path)
        distance=sum(float(e["distance_km"]) for e in path)
        clock=self.runtime.get_clock(world_instance_id); ticks_per_day=int(clock["ticks_per_day"])
        duration_ticks=max(1,int(math.ceil(total_hours/24.0*ticks_per_day))) if path else 0
        now_abs=_abs_tick(clock); due=now_abs+duration_ticks
        return {
            "status":"PLANNED","origin_ref":origin_ref,"origin_anchor":origin_anchor,"destination_ref":destination_ref,"destination_anchor":destination_anchor,
            "route_ids":[e["route_ref"] for e in path],"legs":copy.deepcopy(path),"distance_km":round(distance,3),"estimated_hours":round(total_hours,4),
            "duration_ticks":duration_ticks,"start_abs_tick":now_abs,"due_abs_tick":due,"clearance_level":clearance,"authority":RUNTIME_POLICY,
        }

    def start_travel(self, world_instance_id: str, traveler_ref: str, destination_ref: str, *, requested_mode: str | None = None) -> dict[str, Any]:
        traveler=self.runtime.get_entity(world_instance_id,traveler_ref); plan=self.plan_travel(world_instance_id,traveler_ref,destination_ref,requested_mode=requested_mode)
        travel_id=new_runtime_id("travel"); record={"travel_id":travel_id,"traveler_ref":traveler_ref,**plan,"status":"IN_TRANSIT"}
        if plan["duration_ticks"] == 0:
            record["status"]="ARRIVED"
        w=self.runtime.get_world(world_instance_id); c=w["clock_state"]
        action={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":world_instance_id,"timeline_id":w["timeline_id"],"actor_ref":traveler_ref,"action_type":"TRAVEL_STARTED","parameters":{"travel_id":travel_id,"destination_ref":destination_ref,"route_ids":plan["route_ids"],"duration_ticks":plan["duration_ticks"],"authority":RUNTIME_POLICY},"precondition_snapshot":{"entity_versions":{traveler_ref:traveler["version"]}},"idempotency_key":f"travel-start:{traveler_ref}:{traveler['version']}:{destination_ref}","created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"ACTION","execution_class":"ACTIVE_ONLY"}
        cons=[]
        if plan["duration_ticks"] > 0:
            cons.append({"target_ref":traveler_ref,"operation":"SET","field_path":"data.travel","value":record,"priority":0,"kind":"DIRECT"})
        else:
            cons.append({"target_ref":traveler_ref,"operation":"SET","field_path":"data.location_ref","value":destination_ref,"priority":0,"kind":"DIRECT"})
        result=self.runtime.apply_action(world_instance_id,action,cons)
        text=canonical_json(record); h=sha256_text(text)
        with self._lock,self.runtime._write_lock:
            self.conn.execute("INSERT INTO travel_plans VALUES(?,?,?,?,?,?,?,?,?)",(travel_id,world_instance_id,traveler_ref,plan["origin_ref"],destination_ref,record["status"],int(plan["due_abs_tick"]),text,h))
        return {**record,"event_id":result["event_id"],"plan_hash":h}

    def _routes_still_operational(self, world_instance_id: str, route_ids: list[str]) -> bool:
        for rr in route_ids:
            state=self._route_runtime_state(world_instance_id,rr)
            if state is None or not bool(state.get("data",{}).get("operational",True)) or float(state.get("data",{}).get("capacity_factor",1.0))<=0:
                return False
        return True

    def process_arrivals(self, world_instance_id: str) -> dict[str, Any]:
        now=_abs_tick(self.runtime.get_clock(world_instance_id)); rows=self.conn.execute("SELECT * FROM travel_plans WHERE world_instance_id=? AND status='IN_TRANSIT' AND due_abs_tick<=? ORDER BY due_abs_tick,travel_id",(world_instance_id,now)).fetchall(); results=[]
        for row in rows:
            if sha256_text(row["plan_json"])!=row["plan_hash"]: raise IntegrityError("travel plan hash mismatch")
            plan=json.loads(row["plan_json"]); traveler=self.runtime.get_entity(world_instance_id,row["traveler_ref"])
            active=(traveler.get("data") or {}).get("travel") or {}
            if active.get("travel_id")!=row["travel_id"]: status="CANCELLED"; event_id=None
            elif not self._routes_still_operational(world_instance_id,list(plan.get("route_ids") or [])):
                w=self.runtime.get_world(world_instance_id);c=w["clock_state"]
                action={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":world_instance_id,"timeline_id":w["timeline_id"],"actor_ref":"SYSTEM_RECONCILIATION","action_type":"TRAVEL_BLOCKED","parameters":{"travel_id":row["travel_id"],"reason":"ROUTE_BECAME_UNAVAILABLE"},"precondition_snapshot":{"entity_versions":{traveler["entity_runtime_id"]:traveler["version"]}},"idempotency_key":f"travel-block:{row['travel_id']}","created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"SYSTEM_RECONCILIATION","execution_class":"ROUTINE_SAFE"}
                blocked=copy.deepcopy(active);blocked["status"]="BLOCKED";blocked["blocked_reason"]="ROUTE_BECAME_UNAVAILABLE"
                r=self.runtime.apply_action(world_instance_id,action,[{"target_ref":traveler["entity_runtime_id"],"operation":"SET","field_path":"data.travel","value":blocked,"priority":0,"kind":"DIRECT"}]);status="BLOCKED";event_id=r["event_id"]
            else:
                w=self.runtime.get_world(world_instance_id);c=w["clock_state"]
                action={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":world_instance_id,"timeline_id":w["timeline_id"],"actor_ref":"SYSTEM_RECONCILIATION","action_type":"TRAVEL_ARRIVED","parameters":{"travel_id":row["travel_id"],"destination_ref":row["destination_ref"],"authority":RUNTIME_POLICY},"precondition_snapshot":{"entity_versions":{traveler["entity_runtime_id"]:traveler["version"]}},"idempotency_key":f"travel-arrive:{row['travel_id']}","created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"SYSTEM_RECONCILIATION","execution_class":"ROUTINE_SAFE"}
                r=self.runtime.apply_action(world_instance_id,action,[{"target_ref":traveler["entity_runtime_id"],"operation":"SET","field_path":"data.location_ref","value":row["destination_ref"],"priority":0,"kind":"DIRECT"},{"target_ref":traveler["entity_runtime_id"],"operation":"SET","field_path":"data.travel","value":{"travel_id":row["travel_id"],"status":"ARRIVED","destination_ref":row["destination_ref"],"arrival_abs_tick":now,"authority":RUNTIME_POLICY},"priority":1,"kind":"DIRECT"}]);status="ARRIVED";event_id=r["event_id"]
            with self._lock,self.runtime._write_lock:self.conn.execute("UPDATE travel_plans SET status=? WHERE travel_id=?",(status,row["travel_id"]))
            results.append({"travel_id":row["travel_id"],"status":status,"event_id":event_id})
        return {"status":"PASS","processed":len(results),"results":results}

    # ---------- Ecological movement ----------
    def _event(self,event_id:str)->dict[str,Any]:
        row=self.conn.execute("SELECT * FROM events WHERE event_id=?",(event_id,)).fetchone()
        if not row: raise NotFoundError("event not found")
        return {"event_id":row["event_id"],"world_instance_id":row["world_instance_id"],"event_type":row["event_type"],"subjects":json.loads(row["subjects_json"]),"payload":json.loads(row["payload_json"])}

    def _species_biomes(self,species_ref:str)->list[str]:
        row=self.conn.execute("SELECT distribution_json,distribution_hash FROM fauna_snapshots WHERE species_ref=?",(species_ref,)).fetchone()
        if not row:return []
        if sha256_text(row["distribution_json"])!=row["distribution_hash"]:raise IntegrityError("fauna snapshot hash mismatch")
        d=json.loads(row["distribution_json"]); primary=d.get("distribution_primary") or {}; values=list(primary.get("biome_ids") or [])+list(d.get("biome_ids") or [])
        return list(dict.fromkeys(x for x in values if isinstance(x,str)))

    def _insert_mobility_effect(self,event_id:str,wid:str,key:str,status:str,detail:dict[str,Any])->dict[str,Any]:
        prior=self.conn.execute("SELECT effect_json,effect_hash FROM mobility_effects WHERE event_id=? AND effect_key=?",(event_id,key)).fetchone()
        if prior:
            if sha256_text(prior["effect_json"])!=prior["effect_hash"]:raise IntegrityError("mobility effect hash mismatch")
            b=json.loads(prior["effect_json"]);b["idempotent_replay"]=True;return b
        b={"effect_id":new_runtime_id("mobilityeffect"),"event_id":event_id,"world_instance_id":wid,"effect_key":key,"status":status,"detail":copy.deepcopy(detail),"authority":RUNTIME_POLICY};text=canonical_json(b);h=sha256_text(text)
        self.conn.execute("INSERT INTO mobility_effects VALUES(?,?,?,?,?,?,?)",(b["effect_id"],event_id,wid,key,status,text,h));b["effect_hash"]=h;return b

    def _process_movement_event(self,event_id:str)->dict[str,Any]:
        e=self._event(event_id);wid=e["world_instance_id"]; animal_ref=next((x for x in e["subjects"] if isinstance(x,str) and x.startswith("rt:")),None)
        if not animal_ref:return self._insert_mobility_effect(event_id,wid,"movement:no-actor","SKIPPED",{"reason":"NO_RUNTIME_ACTOR"})
        try: animal=self.runtime.get_entity(wid,animal_ref)
        except NotFoundError:return self._insert_mobility_effect(event_id,wid,f"movement:{animal_ref}","SKIPPED",{"reason":"ACTOR_MISSING"})
        if animal.get("entity_kind") not in {"ANIMAL","CREATURE"}:return self._insert_mobility_effect(event_id,wid,f"movement:{animal_ref}","SKIPPED",{"reason":"NOT_ECOLOGICAL_ACTOR"})
        d=animal.get("data") or {};eco=d.get("ecology") or {};current=eco.get("biome_ref")
        key=f"movement:{e['event_type']}:{animal_ref}"
        if e["event_type"]=="ECO_FLEE":
            alternatives=[b for b in self._species_biomes(d.get("species_ref")) if b!=current]
            if alternatives:
                destination=sorted(alternatives)[0]; w=self.runtime.get_world(wid);c=w["clock_state"]
                action={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":wid,"timeline_id":w["timeline_id"],"actor_ref":"SYSTEM_RECONCILIATION","action_type":"ECO_MOVEMENT_RECONCILED","parameters":{"source_event_id":event_id,"movement_type":"FLEE","from_biome":current,"to_biome":destination,"authority":RUNTIME_POLICY},"precondition_snapshot":{"entity_versions":{animal_ref:animal["version"]}},"idempotency_key":f"eco-move:{event_id}","created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"SYSTEM_RECONCILIATION","execution_class":"ROUTINE_SAFE"}
                r=self.runtime.apply_action(wid,action,[{"target_ref":animal_ref,"operation":"SET","field_path":"data.ecology.biome_ref","value":destination,"priority":0,"kind":"DERIVED"}])
                return self._insert_mobility_effect(event_id,wid,key,"APPLIED",{"from_biome":current,"to_biome":destination,"reconciliation_event_id":r["event_id"],"basis":"CANONICAL_SPECIES_BIOME_DISTRIBUTION"})
        # Patrol or single-biome flee gets a real runtime microspace displacement inside the known biome.
        seed=int(hashlib.sha256(event_id.encode()).hexdigest()[:12],16);x=round(((seed%2001)-1000)/1000.0,3);y=round((((seed//2001)%2001)-1000)/1000.0,3)
        w=self.runtime.get_world(wid);c=w["clock_state"]
        action={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":wid,"timeline_id":w["timeline_id"],"actor_ref":"SYSTEM_RECONCILIATION","action_type":"ECO_MOVEMENT_RECONCILED","parameters":{"source_event_id":event_id,"movement_type":e["event_type"].removeprefix("ECO_"),"microspace":[x,y],"authority":RUNTIME_POLICY},"precondition_snapshot":{"entity_versions":{animal_ref:animal["version"]}},"idempotency_key":f"eco-move:{event_id}","created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"SYSTEM_RECONCILIATION","execution_class":"ROUTINE_SAFE"}
        r=self.runtime.apply_action(wid,action,[{"target_ref":animal_ref,"operation":"SET","field_path":"data.ecology.micro_position","value":{"x":x,"y":y,"space_ref":current or eco.get("territory_ref"),"authority":"RUNTIME_MICROSPACE_ZERO_CANON_IMPACT"},"priority":0,"kind":"DERIVED"}])
        return self._insert_mobility_effect(event_id,wid,key,"APPLIED",{"micro_position":{"x":x,"y":y},"space_ref":current or eco.get("territory_ref"),"reconciliation_event_id":r["event_id"],"basis":"RUNTIME_MICROSPACE_ZERO_CANON_IMPACT"})

    def drain_movement(self,world_instance_id:str)->dict[str,Any]:
        # Backfill events in case post-commit callback was missed.
        with self._lock,self.runtime._write_lock:
            self.conn.execute("""INSERT OR IGNORE INTO mobility_event_queue(event_id,world_instance_id,event_type,status)
                               SELECT event_id,world_instance_id,event_type,'PENDING' FROM events
                               WHERE world_instance_id=? AND event_type IN ('ECO_FLEE','ECO_PATROL')""",(world_instance_id,))
        rows=self.conn.execute("SELECT event_id FROM mobility_event_queue WHERE world_instance_id=? AND status='PENDING' ORDER BY rowid",(world_instance_id,)).fetchall();out=[]
        for row in rows:
            try:
                effect=self._process_movement_event(row["event_id"]);status="COMPLETED" if effect["status"]=="APPLIED" else "SKIPPED";err=None
            except Exception as exc:
                status="FAILED";effect={"event_id":row["event_id"],"status":"FAILED","error":str(exc)};err=str(exc)
            text=canonical_json(effect);h=sha256_text(text)
            with self._lock,self.runtime._write_lock:self.conn.execute("UPDATE mobility_event_queue SET status=?,result_json=?,result_hash=?,last_error=? WHERE event_id=?",(status,text,h,err,row["event_id"]))
            out.append(effect)
        return {"status":"PASS" if not any(x.get("status")=="FAILED" for x in out) else "FAIL","processed":len(out),"effects":out}

    # ---------- Biological clock / environment ----------
    def _environment_for(self,world_instance_id:str,biome_ref:str|None)->dict[str,float]:
        neutral={"temperature":20.0,"humidity":50.0,"smoke":0.0,"contamination":0.0,"source":"NEUTRAL_RUNTIME_FALLBACK"}
        if not biome_ref:return neutral
        matches=[e for e in self.runtime.list_entities(world_instance_id) if e.get("entity_kind")=="ENVIRONMENT_ZONE" and e.get("lifecycle")=="ACTIVE" and e.get("canonical_ref")==biome_ref]
        if not matches:return neutral
        d=matches[0].get("data") or {};return {"temperature":float(d.get("temperature",20.0)),"humidity":float(d.get("humidity",50.0)),"smoke":float(d.get("smoke",0.0)),"contamination":float(d.get("contamination",0.0)),"source":matches[0]["entity_runtime_id"]}

    def biology_tick(self,world_instance_id:str,*,tick_key:str|None=None)->dict[str,Any]:
        clock=self.runtime.get_clock(world_instance_id);key=tick_key or f"biology:{clock['day']}:{clock['tick']}";tpd=float(clock["ticks_per_day"]);results=[]
        animals=[e for e in self.runtime.list_entities(world_instance_id) if e.get("entity_kind") in {"ANIMAL","CREATURE"} and e.get("lifecycle")=="ACTIVE"]
        for animal in animals:
            ref=animal["entity_runtime_id"]
            prior=self.conn.execute("SELECT result_json,result_hash FROM biology_tick_log WHERE world_instance_id=? AND entity_ref=? AND tick_key=?",(world_instance_id,ref,key)).fetchone()
            if prior:
                if sha256_text(prior["result_json"])!=prior["result_hash"]:raise IntegrityError("biology tick hash mismatch")
                b=json.loads(prior["result_json"]);b["idempotent_replay"]=True;results.append(b);continue
            d=animal.get("data") or {};eco=d.get("ecology") or {};bio=d.get("biology") if isinstance(d.get("biology"),dict) else {}
            env=self._environment_for(world_instance_id,eco.get("biome_ref"));temp=env["temperature"]; humidity=env["humidity"]
            hot=max(0.0,temp-30.0);cold=max(0.0,5.0-temp);dry=max(0.0,35.0-humidity)
            thirst_rate=METABOLISM_POLICY["thirst_per_day"]*(1.0+hot/40.0+dry/100.0)
            hunger_rate=METABOLISM_POLICY["hunger_per_day"]
            energy_rate=METABOLISM_POLICY["energy_loss_per_day"]*(1.0+cold/30.0)
            hunger=_clamp(float(eco.get("hunger",20.0))+hunger_rate/tpd);thirst=_clamp(float(eco.get("thirst",20.0))+thirst_rate/tpd);energy=_clamp(float(eco.get("energy",80.0))-energy_rate/tpd)
            stress=float(bio.get("stress",0.0)); deprivation=max(0.0,max(hunger,thirst)-85.0)/15.0
            stress_delta=(deprivation*METABOLISM_POLICY["deprivation_stress_per_day"]+env["contamination"]/100.0*METABOLISM_POLICY["contamination_stress_per_day_at_100"]+env["smoke"]/100.0*METABOLISM_POLICY["smoke_stress_per_day_at_100"])/tpd
            if deprivation<=0 and env["contamination"]<10 and env["smoke"]<10: stress_delta-=METABOLISM_POLICY["stress_recovery_per_day"]/tpd
            stress=_clamp(stress+stress_delta)
            frac=float(bio.get("age_fraction_days",0.0))+1.0/tpd;whole=int(math.floor(frac+1e-12));frac-=whole;age=int(d.get("age_days",0))+whole
            profile=self.ecology.get_species_profile(world_instance_id,d.get("species_ref"));mature=age>=int(profile.get("maturity_days",0))
            lethal=stress>=METABOLISM_POLICY["biological_death_threshold"]
            protection=animal.get("protection") if isinstance(animal.get("protection"),dict) else {};death_blocked=lethal and protection.get("death") in {"BLOCKED","STORY_AUTHORITY_ONLY"}
            if death_blocked: lethal=False;stress=99.0
            w=self.runtime.get_world(world_instance_id);c=w["clock_state"]
            params={"tick_key":key,"environment":env,"rates":{"hunger_per_day":hunger_rate,"thirst_per_day":round(thirst_rate,4),"energy_loss_per_day":round(energy_rate,4)},"biological_death":lethal,"death_blocked_by_protection":death_blocked,"authority":RUNTIME_POLICY}
            action={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":world_instance_id,"timeline_id":w["timeline_id"],"actor_ref":ref,"action_type":"BIOLOGY_TICK","parameters":params,"precondition_snapshot":{"entity_versions":{ref:animal["version"]}},"idempotency_key":f"biology:{key}:{ref}","created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"SYSTEM_ROUTINE","execution_class":"ROUTINE_SAFE"}
            cons=[
                {"target_ref":ref,"operation":"SET","field_path":"data.ecology.hunger","value":round(hunger,6),"priority":0,"kind":"DIRECT"},
                {"target_ref":ref,"operation":"SET","field_path":"data.ecology.thirst","value":round(thirst,6),"priority":1,"kind":"DIRECT"},
                {"target_ref":ref,"operation":"SET","field_path":"data.ecology.energy","value":round(energy,6),"priority":2,"kind":"DIRECT"},
                {"target_ref":ref,"operation":"SET","field_path":"data.age_days","value":age,"priority":3,"kind":"DIRECT"},
                {"target_ref":ref,"operation":"SET","field_path":"data.mature","value":mature,"priority":4,"kind":"DIRECT"},
                {"target_ref":ref,"operation":"SET","field_path":"data.biology","value":{"age_fraction_days":round(frac,9),"stress":round(stress,6),"last_environment":env,"policy":RUNTIME_POLICY},"priority":5,"kind":"DIRECT"},
            ]
            if lethal:cons.append({"target_ref":ref,"operation":"TRANSITION","field_path":"lifecycle","from":"ACTIVE","value":"DEAD","priority":6,"kind":"DIRECT"})
            r=self.runtime.apply_action(world_instance_id,action,cons)
            if self.domain_hub is not None:self.domain_hub.drain_pending(world_instance_id)
            result={"record_id":new_runtime_id("biotick"),"world_instance_id":world_instance_id,"entity_ref":ref,"tick_key":key,"event_id":r["event_id"],"age_days":age,"hunger":round(hunger,6),"thirst":round(thirst,6),"energy":round(energy,6),"stress":round(stress,6),"mature":mature,"biological_death":lethal,"environment":env,"authority":RUNTIME_POLICY}
            text=canonical_json(result);h=sha256_text(text)
            with self._lock,self.runtime._write_lock:self.conn.execute("INSERT INTO biology_tick_log VALUES(?,?,?,?,?,?,?)",(result["record_id"],world_instance_id,ref,key,r["event_id"],text,h))
            results.append(result)
        return {"status":"PASS","tick_key":key,"processed":len(results),"results":results,"authority":RUNTIME_POLICY}

    def extension_handler(self, context: dict[str,Any]) -> dict[str,Any]:
        wid=context["world_instance_id"];tick_key=context["tick_key"]
        movement=self.drain_movement(wid); arrivals=self.process_arrivals(wid); biology=self.biology_tick(wid,tick_key=f"orchestrator:{tick_key}")
        return {"status":"PASS" if movement["status"]=="PASS" and biology["status"]=="PASS" else "FAIL","authority":RUNTIME_POLICY,"movement":movement,"arrivals":arrivals,"biology":biology}

    def attach_to_orchestrator(self, orchestrator: Any, world_instance_id: str) -> dict[str,Any]:
        return orchestrator.attach_extension(world_instance_id,self.EXTENSION_KEY,self.extension_handler,version=self.EXTENSION_VERSION,modes={"FULL","ACTIVE","AGGREGATE","ROUTINE_OFFLINE"},cadence_ticks=1,routine_safe=True)

    def full_integrity_check(self, world_instance_id: str) -> dict[str,Any]:
        failures=[]
        with self.runtime._write_lock:
            for r in self.conn.execute("SELECT event_id,result_json,result_hash,status FROM mobility_event_queue WHERE world_instance_id=?",(world_instance_id,)).fetchall():
                if r["result_json"] is not None and sha256_text(r["result_json"])!=r["result_hash"]:failures.append(f"MOBILITY_QUEUE_HASH:{r['event_id']}")
                if r["status"]=="FAILED":failures.append(f"MOBILITY_QUEUE_FAILED:{r['event_id']}")
            for r in self.conn.execute("SELECT effect_id,effect_json,effect_hash FROM mobility_effects WHERE world_instance_id=?",(world_instance_id,)).fetchall():
                if sha256_text(r["effect_json"])!=r["effect_hash"]:failures.append(f"MOBILITY_EFFECT_HASH:{r['effect_id']}")
            for r in self.conn.execute("SELECT travel_id,plan_json,plan_hash,status FROM travel_plans WHERE world_instance_id=?",(world_instance_id,)).fetchall():
                if sha256_text(r["plan_json"])!=r["plan_hash"]:failures.append(f"TRAVEL_PLAN_HASH:{r['travel_id']}")
            for r in self.conn.execute("SELECT record_id,result_json,result_hash FROM biology_tick_log WHERE world_instance_id=?",(world_instance_id,)).fetchall():
                if sha256_text(r["result_json"])!=r["result_hash"]:failures.append(f"BIOLOGY_TICK_HASH:{r['record_id']}")
        replay=self.runtime.compare_replay_to_materialized(world_instance_id)
        if replay["status"]!="PASS":failures.append("REPLAY_MISMATCH")
        return {"status":"PASS" if not failures else "FAIL","failures":failures,"replay":replay,"authority":RUNTIME_POLICY}
