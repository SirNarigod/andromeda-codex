from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any

from living_runtime import ValidationError, IntegrityError, ConflictError, NotFoundError, canonical_json, sha256_text


class ARPGGatheringWorkCore:
    """Stage09 shared gathering/work authority for player and Country NPCs.

    Canonical Master data remains read-only. Country resource/flora/fauna quantities are
    runtime-derived projections. All produced resources enter the Stage05 universal item
    inventory. Numeric productivity/mastery and fishing catch are gameplay-derived.
    """

    VERSION = "V1.0.0"
    AUTHORITY = "ANDROMEDA_ARPG_STAGE09_GATHERING_WORK"
    GAMEPLAY_AUTHORITY = "GAMEPLAY_DERIVED_STAGE09_REBALANCEABLE"
    COUNTRY_REF = "TER-011"
    FISH_ITEM_REF = "ITEM-FISH-CATCH"
    ACTIVITIES = ("MINING", "LOGGING", "FORAGING", "AGRICULTURE", "HUNTING", "FISHING")
    HAZARDOUS = {"MINING", "LOGGING", "HUNTING"}
    BASE_DURATION_S = {"MINING": 2.4, "LOGGING": 2.1, "FORAGING": 1.3, "AGRICULTURE": 1.7, "HUNTING": 3.2, "FISHING": 2.8}
    TOOL_KIND = {"MINING": "TOOL", "LOGGING": "TOOL", "FORAGING": "TOOL", "AGRICULTURE": "TOOL", "HUNTING": "WEAPON", "FISHING": "TOOL"}
    ROLE_DEFAULTS = {
        "MINING": {"role_ref": "ROLE-GTH-MINER", "canonical_candidate": "JOB-MIN-OPER-001"},
        "LOGGING": {"role_ref": "ROLE-GTH-FORESTRY", "canonical_candidate": None},
        "FORAGING": {"role_ref": "ROLE-GTH-FORAGER", "canonical_candidate": None},
        "AGRICULTURE": {"role_ref": "ROLE-GTH-AGRICULTURE", "canonical_candidate": "JOB-RUR-AGR-001"},
        "HUNTING": {"role_ref": "ROLE-GTH-HUNTER", "canonical_candidate": "JOB-EXPL-CAC-001"},
        "FISHING": {"role_ref": "ROLE-GTH-FISHER", "canonical_candidate": None},
    }

    def __init__(self, engine: Any, world_instance_id: str) -> None:
        self.engine = engine
        self.runtime = engine.runtime
        self.world_instance_id = str(world_instance_id)
        self.country = engine.country(world_instance_id)
        self.world = engine.world_arpg(world_instance_id)
        self.items = engine.items_arpg(world_instance_id)
        self.society = engine.society
        self._init_schema()
        self._ensure_stage09_item_definitions()
        self._bootstrap_nodes()
        self._bootstrap_existing_players()

    def _init_schema(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.executescript("""
            CREATE TABLE IF NOT EXISTS arpg_gathering_nodes(
              node_ref TEXT NOT NULL,
              world_instance_id TEXT NOT NULL,
              zone_ref TEXT NOT NULL,
              block_ref TEXT NOT NULL,
              activity_type TEXT NOT NULL,
              source_kind TEXT NOT NULL,
              source_ref TEXT NOT NULL,
              output_item_ref TEXT NOT NULL,
              definition_json TEXT NOT NULL,
              definition_hash TEXT NOT NULL,
              PRIMARY KEY(world_instance_id,node_ref),
              UNIQUE(world_instance_id,block_ref,activity_type,source_kind,source_ref)
            );
            CREATE TABLE IF NOT EXISTS arpg_gathering_runtime_state(
              node_ref TEXT NOT NULL,
              world_instance_id TEXT NOT NULL,
              remaining_units INTEGER NOT NULL,
              cycle INTEGER NOT NULL,
              state_json TEXT NOT NULL,
              state_hash TEXT NOT NULL,
              PRIMARY KEY(world_instance_id,node_ref)
            );
            CREATE TABLE IF NOT EXISTS arpg_worker_profiles(
              world_instance_id TEXT NOT NULL,
              worker_ref TEXT NOT NULL,
              worker_kind TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              payload_hash TEXT NOT NULL,
              PRIMARY KEY(world_instance_id,worker_ref)
            );
            CREATE TABLE IF NOT EXISTS arpg_work_orders(
              order_ref TEXT PRIMARY KEY,
              world_instance_id TEXT NOT NULL,
              worker_ref TEXT NOT NULL,
              node_ref TEXT NOT NULL,
              activity_type TEXT NOT NULL,
              status TEXT NOT NULL,
              create_event_ref TEXT NOT NULL,
              requested_units INTEGER NOT NULL,
              payload_json TEXT NOT NULL,
              payload_hash TEXT NOT NULL,
              result_json TEXT,
              result_hash TEXT,
              UNIQUE(world_instance_id,create_event_ref)
            );
            CREATE TABLE IF NOT EXISTS arpg_work_events(
              world_instance_id TEXT NOT NULL,
              event_ref TEXT NOT NULL,
              event_type TEXT NOT NULL,
              payload_hash TEXT NOT NULL,
              result_json TEXT NOT NULL,
              result_hash TEXT NOT NULL,
              PRIMARY KEY(world_instance_id,event_ref)
            );
            """)

    @staticmethod
    def _payload(obj: dict[str, Any]) -> tuple[str, str]:
        text = canonical_json(obj)
        return text, sha256_text(text)

    def _stable_float(self, *parts: Any) -> float:
        raw = "|".join(str(x) for x in (self._world_seed(),) + parts)
        h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return int(h[:16], 16) / float(0xFFFFFFFFFFFFFFFF)

    def _world_seed(self) -> int:
        try:
            return int(self.country.seed)
        except Exception:
            return 0

    def _ensure_stage09_item_definitions(self) -> None:
        try:
            self.items.definition(self.FISH_ITEM_REF)
            return
        except Exception:
            pass
        definition = {
            "item_ref": self.FISH_ITEM_REF,
            "name": "Captura Aquática Não Identificada",
            "item_kind": "MATERIAL",
            "source_kind": "STAGE09_FISHING_GAMEPLAY_DERIVED",
            "canonical_identity": False,
            "canonical_status": "GAMEPLAY_DERIVED_NOT_CANON",
            "source_authority": self.GAMEPLAY_AUTHORITY,
            "source_category": "FISHING_CATCH_GENERIC",
            "stackable": True,
            "stack_max": 999,
            "unit_weight": 0.6,
            "equip_slots": [],
            "instance_policy": "STACK",
            "base_durability": 0.0,
            "quality_policy": "NOT_APPLICABLE",
            "rarity_policy": "COMMON_STACK",
            "rarity_display_names_authority": "GAMEPLAY_DERIVED_RENAMEABLE",
            "base_modifiers": {"damage_flat":0.0,"damage_pct":0.0,"armor_flat":0.0,"accuracy_flat":0.0,"evasion_flat":0.0,"crit_chance_pct":0.0,"attack_speed_pct":0.0,"range_bonus_m":0.0,"resistances":{"FIRE":0.0,"COLD":0.0,"LIGHTNING":0.0,"TOXIC":0.0,"ARCANE":0.0}},
            "consumable_effect": None,
            "socket_support": {"supported": False, "capacity_by_rarity": {}, "augmentation_binding": "NOT_APPLICABLE"},
            "source_snapshot_hash": sha256_text("STAGE09:FISHING:TER-011:RIV-VARDEN"),
            "art_dependency": "NONE_PLACEHOLDER_READY",
            "authority": self.AUTHORITY,
            "canon_guard": "No fish species name or biology is asserted; this is a generic gameplay catch until authorial/canonical fauna binding exists.",
        }
        text, h = self._payload(definition)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT INTO arpg_item_definitions(item_ref,source_kind,source_authority,payload_json,payload_hash) VALUES(?,?,?,?,?)",
                (self.FISH_ITEM_REF, "STAGE09_FISHING_GAMEPLAY_DERIVED", self.GAMEPLAY_AUTHORITY, text, h),
            )

    @staticmethod
    def _segment_bbox_intersects(a: list[float], b: list[float], bbox: list[float]) -> bool:
        minx, miny, maxx, maxy = map(float, bbox)
        sx0, sx1 = sorted((float(a[0]), float(b[0]))); sy0, sy1 = sorted((float(a[1]), float(b[1])))
        return not (sx1 < minx or sx0 > maxx or sy1 < miny or sy0 > maxy)

    def _zone_has_physical_fishing_water(self, zone: dict[str, Any]) -> bool:
        h = zone.get("hydrology_context") or {}
        river = h.get("river") or {}
        coords = ((river.get("geometry") or {}).get("coordinates") or [])
        bbox = zone.get("bounding_region") or []
        if len(bbox) != 4 or len(coords) < 2:
            return False
        for i in range(len(coords)-1):
            if self._segment_bbox_intersects(coords[i], coords[i+1], bbox):
                return True
        return False

    def _node_definition(self, zone: dict[str, Any], *, activity: str, source_kind: str, source_ref: str,
                         output_item_ref: str, capacity: int, source_meta: dict[str, Any]) -> dict[str, Any]:
        block_ref = zone["block_ref"]
        node_ref = "GTH-" + hashlib.sha256(f"{self._world_seed()}|{activity}|{block_ref}|{source_kind}|{source_ref}".encode()).hexdigest()[:20].upper()
        support = []
        if activity == "AGRICULTURE": support = ["AGZ-001", "RSZ-003"]
        if activity == "HUNTING": support = ["JOB-EXPL-CAC-001"]
        return {
            "node_ref": node_ref,
            "world_instance_id": self.world_instance_id,
            "country_ref": self.COUNTRY_REF,
            "zone_ref": zone["zone_ref"],
            "block_ref": block_ref,
            "activity_type": activity,
            "source_kind": source_kind,
            "source_ref": source_ref,
            "output_item_ref": output_item_ref,
            "capacity_units": int(max(0, capacity)),
            "renewability": "LIVING_ECOLOGY_STAGE14" if source_kind in {"FLORA", "FAUNA", "FISHING"} else "NON_RENEWABLE_WITHIN_STAGE09",
            "canonical_context_support_refs": support,
            "canonical_context_scope": "SUPPORT_NOT_EXACT_LOCATION" if support else "NONE",
            "source_meta": copy.deepcopy(source_meta),
            "art_dependency": "NONE_PLACEHOLDER_READY",
            "authority": self.AUTHORITY,
        }

    def _insert_node(self, d: dict[str, Any], *, state_remaining: int | None = None) -> None:
        text, h = self._payload(d)
        with self.runtime._write_lock:
            row = self.runtime.conn.execute("SELECT definition_hash FROM arpg_gathering_nodes WHERE world_instance_id=? AND node_ref=?", (self.world_instance_id,d["node_ref"],)).fetchone()
            if row:
                if row["definition_hash"] != h: raise IntegrityError("gathering node drift:" + d["node_ref"])
                return
            self.runtime.conn.execute(
                "INSERT INTO arpg_gathering_nodes VALUES(?,?,?,?,?,?,?,?,?,?)",
                (d["node_ref"], self.world_instance_id, d["zone_ref"], d["block_ref"], d["activity_type"], d["source_kind"], d["source_ref"], d["output_item_ref"], text, h),
            )
            if state_remaining is not None:
                state = {"node_ref": d["node_ref"], "remaining_units": int(state_remaining), "cycle": 0, "authority": self.GAMEPLAY_AUTHORITY}
                st, sh = self._payload(state)
                self.runtime.conn.execute("INSERT INTO arpg_gathering_runtime_state VALUES(?,?,?,?,?,?)", (d["node_ref"], self.world_instance_id, int(state_remaining), 0, st, sh))

    def _bootstrap_nodes(self) -> dict[str, Any]:
        inserted_before = self.runtime.conn.execute("SELECT COUNT(*) c FROM arpg_gathering_nodes WHERE world_instance_id=?", (self.world_instance_id,)).fetchone()["c"]
        for zone in self.world.list_zones():
            block = self.country.block(zone["block_ref"])
            for r in block.get("resources", []):
                d = self._node_definition(zone, activity="MINING", source_kind="MINERAL", source_ref=r["id"], output_item_ref=r["id"], capacity=int(r.get("capacity_units",0)), source_meta={"kind":r.get("kind"),"tier":r.get("tier"),"name":r.get("name"),"authority":"COUNTRY_RUNTIME_DERIVED"})
                self._insert_node(d)
            for f in block.get("flora", []):
                species = f["species_ref"]
                if species == "FLR-HARDWOOD": activity = "LOGGING"
                elif species in {"FLR-GRAIN", "FLR-PASTURE"}: activity = "AGRICULTURE"
                else: activity = "FORAGING"
                out = "ITEM-HARVEST-" + species
                d = self._node_definition(zone, activity=activity, source_kind="FLORA", source_ref=f["id"], output_item_ref=out, capacity=int(f.get("capacity_units",0)), source_meta={"species_ref":species,"tier":f.get("tier"),"name":f.get("name"),"flora_canon_guard":"MASTER_FLORA_SPATIALIZATION_BLOCKED; COUNTRY_RUNTIME_DERIVED_ONLY"})
                self._insert_node(d)
            for a in block.get("fauna", []):
                species = a["species_ref"]
                d = self._node_definition(zone, activity="HUNTING", source_kind="FAUNA", source_ref=a["id"], output_item_ref="ITEM-FAUNA-"+species, capacity=int(a.get("count",0)), source_meta={"species_ref":species,"role":a.get("role"),"tier":a.get("tier"),"name":a.get("name"),"authority":"COUNTRY_RUNTIME_DERIVED_FAUNA_PROXY"})
                self._insert_node(d)
            if zone.get("anomaly_overlay") is None and self._zone_has_physical_fishing_water(zone):
                cap = 80 + int(self._stable_float(zone["zone_ref"], "FISH_CAP") * 121)
                d = self._node_definition(zone, activity="FISHING", source_kind="FISHING", source_ref="RIV-VARDEN:"+zone["zone_ref"], output_item_ref=self.FISH_ITEM_REF, capacity=cap, source_meta={"river_ref":"RIV-VARDEN","basin_ref":"BAS-001","species_identity":"UNSPECIFIED_GAMEPLAY_DERIVED","spatial_basis":"RIVER_SEGMENT_INTERSECTS_ZONE_BBOX"})
                self._insert_node(d, state_remaining=cap)
        count = self.runtime.conn.execute("SELECT COUNT(*) c FROM arpg_gathering_nodes WHERE world_instance_id=?", (self.world_instance_id,)).fetchone()["c"]
        return {"status":"PASS","inserted":count-inserted_before,"nodes":count}

    def _definition_row(self, node_ref: str):
        row = self.runtime.conn.execute("SELECT * FROM arpg_gathering_nodes WHERE world_instance_id=? AND node_ref=?", (self.world_instance_id, str(node_ref))).fetchone()
        if not row: raise NotFoundError("gathering node not found:"+str(node_ref))
        if sha256_text(row["definition_json"]) != row["definition_hash"]: raise IntegrityError("gathering node hash mismatch")
        return row

    def _source_record(self, d: dict[str, Any]) -> dict[str, Any] | None:
        block = self.country.block(d["block_ref"])
        if d["source_kind"] == "MINERAL": return next((x for x in block.get("resources",[]) if x["id"]==d["source_ref"]), None)
        if d["source_kind"] == "FLORA": return next((x for x in block.get("flora",[]) if x["id"]==d["source_ref"]), None)
        if d["source_kind"] == "FAUNA": return next((x for x in block.get("fauna",[]) if x["id"]==d["source_ref"]), None)
        return None

    def node(self, node_ref: str) -> dict[str, Any]:
        row = self._definition_row(node_ref); d = json.loads(row["definition_json"])
        src = self._source_record(d)
        if d["source_kind"] == "MINERAL": remaining = int((src or {}).get("remaining_units",0))
        elif d["source_kind"] == "FLORA": remaining = int((src or {}).get("remaining_units",0))
        elif d["source_kind"] == "FAUNA": remaining = int((src or {}).get("count",0))
        else:
            st = self.runtime.conn.execute("SELECT * FROM arpg_gathering_runtime_state WHERE world_instance_id=? AND node_ref=?", (self.world_instance_id,d["node_ref"],)).fetchone()
            if not st: raise IntegrityError("runtime node state missing")
            if sha256_text(st["state_json"]) != st["state_hash"]: raise IntegrityError("runtime node state hash mismatch")
            remaining = int(st["remaining_units"])
        d["remaining_units"] = remaining
        d["depleted"] = remaining <= 0
        return d

    def list_nodes(self, *, activity_type: str | None = None, zone_ref: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT node_ref FROM arpg_gathering_nodes WHERE world_instance_id=?"; args: list[Any] = [self.world_instance_id]
        if activity_type is not None:
            activity_type = str(activity_type).upper()
            if activity_type not in self.ACTIVITIES: raise ValidationError("invalid gathering activity")
            q += " AND activity_type=?"; args.append(activity_type)
        if zone_ref is not None: q += " AND zone_ref=?"; args.append(str(zone_ref))
        q += " ORDER BY node_ref"
        return [self.node(r["node_ref"]) for r in self.runtime.conn.execute(q, tuple(args)).fetchall()]

    def _worker_kind(self, worker_ref: str) -> str:
        try:
            self.engine.arpg(self.world_instance_id).profile(worker_ref)
            return "PLAYER_PROFILE"
        except Exception:
            pass
        try:
            self.country.npc(worker_ref)
            return "COUNTRY_NPC"
        except Exception:
            raise ValidationError("worker must be player profile or Country NPC")

    def _initial_worker(self, worker_ref: str, kind: str) -> dict[str, Any]:
        return {"worker_ref":worker_ref,"worker_kind":kind,"roles":{},"mastery":{a:{"xp":0,"rank":1} for a in self.ACTIVITIES},"completed_orders":0,"authority":self.AUTHORITY}

    def _save_worker(self, d: dict[str, Any]) -> None:
        text,h=self._payload(d)
        with self.runtime._write_lock:
            self.runtime.conn.execute("INSERT OR REPLACE INTO arpg_worker_profiles VALUES(?,?,?,?,?)",(self.world_instance_id,d["worker_ref"],d["worker_kind"],text,h))

    def ensure_worker(self, worker_ref: str) -> dict[str, Any]:
        row=self.runtime.conn.execute("SELECT payload_json,payload_hash FROM arpg_worker_profiles WHERE world_instance_id=? AND worker_ref=?",(self.world_instance_id,str(worker_ref))).fetchone()
        if row:
            if sha256_text(row["payload_json"])!=row["payload_hash"]: raise IntegrityError("worker profile hash mismatch")
            return json.loads(row["payload_json"])
        kind=self._worker_kind(str(worker_ref)); d=self._initial_worker(str(worker_ref),kind); self._save_worker(d); self.items.ensure_inventory(str(worker_ref)); return d

    def _bootstrap_existing_players(self) -> None:
        try: profiles=self.engine.arpg(self.world_instance_id).list_profiles()
        except Exception: profiles=[]
        for p in profiles: self.ensure_worker(p["profile_ref"])

    def worker(self, worker_ref: str) -> dict[str, Any]: return self.ensure_worker(worker_ref)

    def _profession_allowed_here(self, profession_ref: str) -> tuple[bool, dict[str, Any]]:
        prof=self.society.profession(profession_ref)
        dist=prof.get("territory_distribution") or {}; allowed=self.COUNTRY_REF in set(dist.get("territory_ids") or [])
        return allowed, prof

    def assign_role(self, worker_ref: str, activity_type: str, *, profession_ref: str | None = None) -> dict[str, Any]:
        activity_type=str(activity_type).upper()
        if activity_type not in self.ACTIVITIES: raise ValidationError("invalid work activity")
        w=self.ensure_worker(worker_ref)
        if w["worker_kind"]=="COUNTRY_NPC":
            npc=self.country.npc(worker_ref); p=npc.get("protection") or {}
            if npc.get("class")=="CHILD" or int(npc.get("age",18))<18: raise ConflictError("PROTECTED_CHILD_LABOR_FORBIDDEN")
            if activity_type in self.HAZARDOUS and not bool(p.get("hazardous_labor_allowed",False)):
                raise ConflictError("HAZARDOUS_LABOR_NOT_ALLOWED_FOR_WORKER")
        role=self.ROLE_DEFAULTS[activity_type]; candidate=profession_ref or role.get("canonical_candidate")
        binding={"activity_type":activity_type,"role_ref":role["role_ref"],"profession_ref":None,"profession_name":None,"authority":self.GAMEPLAY_AUTHORITY,"territory_ref":self.COUNTRY_REF}
        if candidate:
            allowed,prof=self._profession_allowed_here(candidate)
            if profession_ref and not allowed: raise ConflictError("PROFESSION_NOT_CANONICALLY_DISTRIBUTED_IN_TER_011")
            if allowed:
                binding.update({"profession_ref":candidate,"profession_name":prof.get("name"),"authority":"MASTER_PROFESSION_READ_ONLY_BINDING"})
            elif profession_ref is None:
                binding["canonical_candidate_not_bound_reason"]="PROFESSION_DISTRIBUTION_OUTSIDE_TER_011"
        if activity_type in {"FISHING","LOGGING","FORAGING"} and not binding["profession_ref"]:
            binding["canon_guard"]="Activity role is gameplay-derived; no canonical profession is asserted."
        w["roles"][activity_type]=binding; self._save_worker(w); return copy.deepcopy(binding)

    def _worker_location(self, worker_ref: str, kind: str) -> tuple[str | None, str | None]:
        if kind=="PLAYER_PROFILE":
            st=self.world.profile_state(worker_ref); z=self.world.zone(st["zone_ref"]); return st["zone_ref"],z["block_ref"]
        npc=self.country.npc(worker_ref); block=npc.get("block_id"); zone=next((z for z in self.world.list_zones() if z["block_ref"]==block),None); return (zone or {}).get("zone_ref"),block

    def _find_work_instance(self, worker_ref: str, required_kind: str) -> dict[str, Any] | None:
        inv=self.items.inventory_snapshot(worker_ref)
        for inst in inv.get("instances",[]):
            try: d=self.items.definition(inst["item_ref"])
            except Exception: continue
            if d.get("item_kind")==required_kind and inst.get("condition")!="BROKEN": return inst
        return None

    def _event_existing(self, event_ref: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        row=self.runtime.conn.execute("SELECT * FROM arpg_work_events WHERE world_instance_id=? AND event_ref=?",(self.world_instance_id,str(event_ref))).fetchone()
        if not row: return None
        ph=sha256_text(canonical_json({"event_type":event_type,"payload":payload}))
        if row["payload_hash"]!=ph: raise ConflictError("WORK_EVENT_REF_CONFLICT")
        if sha256_text(row["result_json"])!=row["result_hash"]: raise IntegrityError("work event result hash mismatch")
        out=json.loads(row["result_json"]); out["idempotent_replay"]=True; return out

    def _record_event(self, event_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        ph=sha256_text(canonical_json({"event_type":event_type,"payload":payload})); text,rh=self._payload(result)
        with self.runtime._write_lock:
            self.runtime.conn.execute("INSERT INTO arpg_work_events VALUES(?,?,?,?,?,?)",(self.world_instance_id,str(event_ref),event_type,ph,text,rh))
        return copy.deepcopy(result)

    def create_work_order(self, worker_ref: str, node_ref: str, requested_units: int, *, event_ref: str) -> dict[str, Any]:
        if not isinstance(requested_units,int) or isinstance(requested_units,bool) or not (1<=requested_units<=100): raise ValidationError("requested_units out of range 1..100")
        node=self.node(node_ref); w=self.ensure_worker(worker_ref); activity=node["activity_type"]
        payload={"worker_ref":worker_ref,"node_ref":node_ref,"requested_units":requested_units}
        existing=self._event_existing(event_ref,"WORK_ORDER_CREATE",payload)
        if existing is not None:return existing
        role=w.get("roles",{}).get(activity)
        if not role: return self._record_event(event_ref,"WORK_ORDER_CREATE",payload,{"status":"REJECTED","reason":"WORK_ROLE_NOT_ASSIGNED","idempotent_replay":False})
        zone,block=self._worker_location(worker_ref,w["worker_kind"])
        if block!=node["block_ref"]: return self._record_event(event_ref,"WORK_ORDER_CREATE",payload,{"status":"REJECTED","reason":"WORKER_NOT_AT_RESOURCE_NODE","worker_block_ref":block,"node_block_ref":node["block_ref"],"idempotent_replay":False})
        req_kind=self.TOOL_KIND[activity]; tool=self._find_work_instance(worker_ref,req_kind)
        if tool is None: return self._record_event(event_ref,"WORK_ORDER_CREATE",payload,{"status":"REJECTED","reason":"REQUIRED_WORK_EQUIPMENT_MISSING","required_item_kind":req_kind,"idempotent_replay":False})
        if node["remaining_units"]<=0: return self._record_event(event_ref,"WORK_ORDER_CREATE",payload,{"status":"REJECTED","reason":"RESOURCE_NODE_DEPLETED","idempotent_replay":False})
        order_ref="WKO-"+hashlib.sha256(f"{self.world_instance_id}|{event_ref}".encode()).hexdigest()[:24].upper()
        rank=int(w["mastery"][activity]["rank"]); duration=round(self.BASE_DURATION_S[activity]*requested_units/max(1.0,1.0+(rank-1)*0.03),6)
        order={"order_ref":order_ref,"world_instance_id":self.world_instance_id,"worker_ref":worker_ref,"worker_kind":w["worker_kind"],"node_ref":node_ref,"activity_type":activity,"requested_units":requested_units,"tool_instance_ref":tool["instance_ref"],"tool_item_ref":tool["item_ref"],"duration_s":duration,"status":"READY","role":copy.deepcopy(role),"authority":self.AUTHORITY}
        text,h=self._payload(order)
        with self.runtime._write_lock:
            self.runtime.conn.execute("INSERT INTO arpg_work_orders VALUES(?,?,?,?,?,?,?,?,?,?,NULL,NULL)",(order_ref,self.world_instance_id,worker_ref,node_ref,activity,"READY",str(event_ref),requested_units,text,h))
        return self._record_event(event_ref,"WORK_ORDER_CREATE",payload,{"status":"PASS","order":order,"idempotent_replay":False})

    def _read_order(self, order_ref: str) -> dict[str, Any]:
        row=self.runtime.conn.execute("SELECT * FROM arpg_work_orders WHERE world_instance_id=? AND order_ref=?",(self.world_instance_id,str(order_ref))).fetchone()
        if not row: raise NotFoundError("work order not found")
        if sha256_text(row["payload_json"])!=row["payload_hash"]: raise IntegrityError("work order payload hash mismatch")
        d=json.loads(row["payload_json"]); d["status"]=row["status"]
        if row["result_json"]:
            if sha256_text(row["result_json"])!=row["result_hash"]: raise IntegrityError("work order result hash mismatch")
            d["result"]=json.loads(row["result_json"])
        return d

    def _set_fishing_remaining(self, node_ref: str, remaining: int) -> None:
        row=self.runtime.conn.execute("SELECT cycle FROM arpg_gathering_runtime_state WHERE world_instance_id=? AND node_ref=?",(self.world_instance_id,node_ref)).fetchone(); cycle=int(row["cycle"] if row else 0)
        state={"node_ref":node_ref,"remaining_units":int(remaining),"cycle":cycle,"authority":self.GAMEPLAY_AUTHORITY}; text,h=self._payload(state)
        with self.runtime._write_lock:self.runtime.conn.execute("UPDATE arpg_gathering_runtime_state SET remaining_units=?,state_json=?,state_hash=? WHERE world_instance_id=? AND node_ref=?",(int(remaining),text,h,self.world_instance_id,node_ref))

    def _consume_source(self, node: dict[str, Any], qty: int) -> int:
        qty=max(0,int(qty)); current=int(node["remaining_units"]); taken=min(qty,current)
        if taken<=0:return 0
        if node["source_kind"]=="FISHING": self._set_fishing_remaining(node["node_ref"],current-taken); return taken
        src=self._source_record(node)
        if src is None: raise IntegrityError("country source missing for gathering node")
        if node["source_kind"] in {"MINERAL","FLORA"}: src["remaining_units"]=current-taken
        elif node["source_kind"]=="FAUNA": src["count"]=current-taken
        self.country._persist_state(); self.country._record_event("ARPG_GATHERING_SOURCE_CONSUMED",{"node_ref":node["node_ref"],"source_ref":node["source_ref"],"activity_type":node["activity_type"],"consumed":taken,"remaining":current-taken,"authority":self.AUTHORITY},persist_first=False)
        return taken

    def _restore_source(self, node: dict[str, Any], previous: int) -> None:
        if node["source_kind"]=="FISHING": self._set_fishing_remaining(node["node_ref"],previous); return
        src=self._source_record(node)
        if src is None:return
        if node["source_kind"] in {"MINERAL","FLORA"}: src["remaining_units"]=int(previous)
        elif node["source_kind"]=="FAUNA": src["count"]=int(previous)
        self.country._persist_state()

    def execute_work_order(self, order_ref: str, *, event_ref: str, danger_clearance_ref: str | None = None, delivery_mode: str = "INVENTORY", delivery_sink=None) -> dict[str, Any]:
        delivery_mode=str(delivery_mode).upper().strip()
        if delivery_mode not in {"INVENTORY","GROUND_LOOT"}:
            return {"status":"REJECTED","reason":"UNSUPPORTED_DELIVERY_MODE","delivery_mode":delivery_mode,"idempotent_replay":False}
        if delivery_mode=="GROUND_LOOT" and delivery_sink is None:
            return {"status":"REJECTED","reason":"GROUND_LOOT_DELIVERY_SINK_REQUIRED","delivery_mode":delivery_mode,"idempotent_replay":False}
        order=self._read_order(order_ref); payload={"order_ref":order_ref,"danger_clearance_ref":danger_clearance_ref}
        # Preserve the exact legacy event payload for the historical default mode.
        if delivery_mode!="INVENTORY": payload["delivery_mode"]=delivery_mode
        existing=self._event_existing(event_ref,"WORK_ORDER_EXECUTE",payload)
        if existing is not None:return existing
        if order["status"]=="COMPLETED": return self._record_event(event_ref,"WORK_ORDER_EXECUTE",payload,{"status":"PASS","order_ref":order_ref,"result":order.get("result"),"idempotent_completed_order":True,"idempotent_replay":False})
        if order["status"]!="READY": return self._record_event(event_ref,"WORK_ORDER_EXECUTE",payload,{"status":"REJECTED","reason":"WORK_ORDER_NOT_READY","idempotent_replay":False})
        node=self.node(order["node_ref"]); worker=self.ensure_worker(order["worker_ref"]); activity=order["activity_type"]
        zone,block=self._worker_location(order["worker_ref"],worker["worker_kind"])
        if block!=node["block_ref"]: return self._record_event(event_ref,"WORK_ORDER_EXECUTE",payload,{"status":"REJECTED","reason":"WORKER_MOVED_AWAY_FROM_RESOURCE_NODE","idempotent_replay":False})
        tool=self._find_work_instance(order["worker_ref"],self.TOOL_KIND[activity])
        if not tool or tool["instance_ref"]!=order["tool_instance_ref"]: return self._record_event(event_ref,"WORK_ORDER_EXECUTE",payload,{"status":"REJECTED","reason":"WORK_EQUIPMENT_CHANGED_OR_UNAVAILABLE","idempotent_replay":False})
        if activity=="HUNTING" and str((node.get("source_meta") or {}).get("role"))=="PREDATOR" and not danger_clearance_ref:
            return self._record_event(event_ref,"WORK_ORDER_EXECUTE",payload,{"status":"REJECTED","reason":"PREDATOR_HUNT_REQUIRES_STAGE07_DANGER_CLEARANCE","idempotent_replay":False})
        requested=int(order["requested_units"]); available=int(node["remaining_units"]); base=min(requested,available)
        if base<=0:return self._record_event(event_ref,"WORK_ORDER_EXECUTE",payload,{"status":"REJECTED","reason":"RESOURCE_NODE_DEPLETED","idempotent_replay":False})
        rank=int(worker["mastery"][activity]["rank"]); efficiency=min(1.35,1.0+(rank-1)*0.018)
        if activity in {"HUNTING","FISHING"}:
            success=0.72+min(0.20,(rank-1)*0.012)
            if self._stable_float(event_ref,node["node_ref"],activity,"SUCCESS")>success:
                result={"status":"PASS","order_ref":order_ref,"activity_type":activity,"produced_units":0,"output_item_ref":node["output_item_ref"],"success":False,"resource_consumed":0,"mastery_xp_gained":2,"authority":self.AUTHORITY}
                worker["mastery"][activity]["xp"]+=2; self._recalc_rank(worker,activity); worker["completed_orders"]+=1; self._save_worker(worker); self._complete_order(order_ref,result)
                return self._record_event(event_ref,"WORK_ORDER_EXECUTE",payload,{**result,"idempotent_replay":False})
        produced=min(available,max(1,int(math.floor(base*efficiency))))
        # Legacy inventory delivery keeps the original capacity preflight. Physical
        # Stage16A delivery intentionally does not consult inventory capacity because
        # the resource exists in the world before pickup.
        if delivery_mode=="INVENTORY":
            inv=self.items._load_inventory(order["worker_ref"]); ok,metrics=self.items._fits(inv,item_ref=node["output_item_ref"],quantity=produced)
            if not ok:return self._record_event(event_ref,"WORK_ORDER_EXECUTE",payload,{"status":"REJECTED","reason":"INVENTORY_CAPACITY_EXCEEDED","metrics":metrics,"idempotent_replay":False})
        else:
            preview=delivery_sink(worker_ref=order["worker_ref"],node=node,quantity=produced,event_ref=f"{event_ref}:GROUND_LOOT",preview_only=True)
            if not isinstance(preview,dict) or preview.get("status")!="PASS":
                return self._record_event(event_ref,"WORK_ORDER_EXECUTE",payload,{"status":"REJECTED","reason":"GROUND_LOOT_DELIVERY_PREFLIGHT_FAILED","delivery_preview":preview,"idempotent_replay":False})
        previous=available
        physical_delivery=None
        try:
            consumed=self._consume_source(node,produced)
            if delivery_mode=="INVENTORY":
                grant=self.items.grant_item(order["worker_ref"],node["output_item_ref"],consumed,event_ref=f"{event_ref}:ITEM")
                if grant.get("status")!="PASS": raise ConflictError("item grant failed after capacity preflight")
            else:
                physical_delivery=delivery_sink(
                    worker_ref=order["worker_ref"], node=node, quantity=consumed, event_ref=f"{event_ref}:GROUND_LOOT", preview_only=False
                )
                if not isinstance(physical_delivery,dict) or physical_delivery.get("status")!="PASS":
                    raise ConflictError("ground loot delivery failed after source consumption")
            durability_loss=round(max(0.25,consumed*0.22),6)
            durability=self.items.apply_durability_loss(order["worker_ref"],tool["instance_ref"],durability_loss,event_ref=f"{event_ref}:DUR")
        except Exception:
            self._restore_source(node,previous)
            raise
        xp=max(3,consumed*6); worker["mastery"][activity]["xp"]+=xp; self._recalc_rank(worker,activity); worker["completed_orders"]+=1; self._save_worker(worker)
        result={"status":"PASS","order_ref":order_ref,"activity_type":activity,"produced_units":consumed,"output_item_ref":node["output_item_ref"],"success":True,"resource_consumed":consumed,"remaining_units":previous-consumed,"duration_s":order["duration_s"],"tool_instance_ref":tool["instance_ref"],"tool_durability":durability.get("after"),"mastery_xp_gained":xp,"mastery_rank":worker["mastery"][activity]["rank"],"role_authority":order["role"].get("authority"),"authority":self.AUTHORITY,"delivery_mode":delivery_mode}
        if physical_delivery is not None: result["physical_delivery"]=physical_delivery
        self._complete_order(order_ref,result)
        return self._record_event(event_ref,"WORK_ORDER_EXECUTE",payload,{**result,"idempotent_replay":False})

    def _complete_order(self, order_ref: str, result: dict[str, Any]) -> None:
        text,h=self._payload(result)
        with self.runtime._write_lock:self.runtime.conn.execute("UPDATE arpg_work_orders SET status='COMPLETED',result_json=?,result_hash=? WHERE order_ref=?",(text,h,order_ref))

    def _recalc_rank(self, worker: dict[str, Any], activity: str) -> None:
        xp=int(worker["mastery"][activity]["xp"]); worker["mastery"][activity]["rank"]=min(20,1+int(math.sqrt(max(0,xp)/120.0)))

    def employment_bridge(self) -> dict[str, Any]:
        c=self.runtime.conn.execute("SELECT COUNT(*) c FROM profession_snapshots").fetchone()["c"]
        return {"status":"PASS" if c==91 else "FAIL","canonical_profession_snapshots":c,"society_labor_authority":"SOCIETY_LABOR_V1_1_RUNTIME_NOT_CANON","shared_work_order_authority":self.AUTHORITY,"note":"Paid employment/wages remain in SocietyLabor; resource production is Stage09 shared work authority."}

    def snapshot(self, worker_ref: str | None = None) -> dict[str, Any]:
        nodes=self.list_nodes(); counts={a:0 for a in self.ACTIVITIES}
        for n in nodes: counts[n["activity_type"]]+=1
        out={"version":self.VERSION,"authority":self.AUTHORITY,"country_ref":self.COUNTRY_REF,"nodes_total":len(nodes),"nodes_by_activity":counts,"fishing_nodes_physical":counts["FISHING"],"profession_bridge":self.employment_bridge(),"art_dependency":"NONE_PLACEHOLDER_READY"}
        if worker_ref is not None: out["worker"]=self.worker(worker_ref); out["inventory"]=self.items.inventory_snapshot(worker_ref)
        return out

    def verify(self) -> dict[str, Any]:
        failures=[]; nodes=self.list_nodes()
        if not nodes: failures.append("NO_GATHERING_NODES")
        if self.employment_bridge()["status"]!="PASS": failures.append("PROFESSION_SNAPSHOT_COUNT")
        for n in nodes:
            if n["activity_type"] not in self.ACTIVITIES: failures.append("BAD_ACTIVITY:"+n["node_ref"])
            try:self.items.definition(n["output_item_ref"])
            except Exception:failures.append("OUTPUT_ITEM_MISSING:"+n["node_ref"])
            if n["remaining_units"]<0:failures.append("NEGATIVE_REMAINING:"+n["node_ref"])
            if n["source_kind"]=="FISHING":
                z=self.world.zone(n["zone_ref"])
                if not self._zone_has_physical_fishing_water(z):failures.append("FISHING_WITHOUT_PHYSICAL_RIVER:"+n["node_ref"])
                if n["output_item_ref"]!=self.FISH_ITEM_REF:failures.append("FISHING_ITEM_CONTRACT:"+n["node_ref"])
            if n["source_kind"]=="FLORA" and "MASTER_FLORA_SPATIALIZATION_BLOCKED" not in str((n.get("source_meta") or {}).get("flora_canon_guard")): failures.append("FLORA_CANON_GUARD_MISSING:"+n["node_ref"])
        for table,j,h in [("arpg_gathering_nodes","definition_json","definition_hash"),("arpg_gathering_runtime_state","state_json","state_hash"),("arpg_worker_profiles","payload_json","payload_hash")]:
            for r in self.runtime.conn.execute(f"SELECT rowid,{j},{h} FROM {table} WHERE world_instance_id=?",(self.world_instance_id,)).fetchall():
                if sha256_text(r[j])!=r[h]:failures.append(f"{table}:HASH:{r['rowid']}")
        for r in self.runtime.conn.execute("SELECT event_ref,result_json,result_hash FROM arpg_work_events WHERE world_instance_id=?",(self.world_instance_id,)).fetchall():
            if sha256_text(r["result_json"])!=r["result_hash"]:failures.append("WORK_EVENT_HASH:"+r["event_ref"])
        return {"status":"PASS" if not failures else "FAIL","failures":failures,"nodes":len(nodes),"activities":{a:sum(1 for n in nodes if n["activity_type"]==a) for a in self.ACTIVITIES},"profession_snapshots":self.employment_bridge()["canonical_profession_snapshots"],"authority":self.AUTHORITY}
