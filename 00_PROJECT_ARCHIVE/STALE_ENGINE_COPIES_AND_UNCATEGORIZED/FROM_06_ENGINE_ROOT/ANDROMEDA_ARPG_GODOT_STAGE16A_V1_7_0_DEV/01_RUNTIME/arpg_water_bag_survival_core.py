from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Iterable

from living_runtime import ConflictError, ValidationError, canonical_json, sha256_text


class WaterBagSurvivalCore:
    """Stage16A water traversal, bag-container, drowning/exhaustion and water TTL authority.

    This is a gameplay-derived extension. It does not mutate canon or the sealed Stage15
    death policy; Stage16A projects the newer authored rules on top of the historical core.
    """

    VERSION = "V0.8.0-PRE-GODOT"
    AUTHORITY = "ARPG_STAGE16A_WATER_BAG_SURVIVAL_RUNTIME_NOT_CANON"

    BASE_SLOT_LIMIT = 8
    BAG_SLOT_CAPACITY = 30
    BAG_WEIGHT_CAPACITY = 80.0
    ITEM_WATER_TTL_S = 15.0 * 60.0
    BAG_WATER_TTL_S = 30.0 * 60.0
    EXHAUSTION_GRACE_S = 4.0
    SHALLOW_DEPTH_M = 0.65
    VEHICLE_MAX_WADE_DEPTH_M = 0.55

    def __init__(self, engine: Any, world_instance_id: str, ground_loot: Any) -> None:
        self.engine = engine
        self.runtime = engine.runtime
        self.world_instance_id = str(world_instance_id)
        self.ground_loot = ground_loot
        self._schema()

    def _schema(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS arpg_stage16a_carry_profiles(
                    world_instance_id TEXT NOT NULL,
                    owner_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, owner_ref)
                );
                CREATE TABLE IF NOT EXISTS arpg_stage16a_bags(
                    world_instance_id TEXT NOT NULL,
                    bag_ref TEXT NOT NULL,
                    property_owner_ref TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, bag_ref)
                );
                CREATE TABLE IF NOT EXISTS arpg_stage16a_water_exhaustion(
                    world_instance_id TEXT NOT NULL,
                    actor_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, actor_ref)
                );
                CREATE TABLE IF NOT EXISTS arpg_stage16a_water_bag_events(
                    world_instance_id TEXT NOT NULL,
                    event_ref TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    result_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, event_ref)
                );
                """
            )
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('arpg_stage16a_water_bag_version',?)",
                (self.VERSION,),
            )

    @staticmethod
    def _stable_ref(prefix: str, seed: str) -> str:
        return prefix + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20].upper()

    def contract(self) -> dict[str, Any]:
        return {
            "version": self.VERSION,
            "authority": self.AUTHORITY,
            "water": {
                "shallow_crossing": ["PLAYER", "NPC", "ANIMAL", "VEHICLE"],
                "shallow_depth_m_candidate": self.SHALLOW_DEPTH_M,
                "strong_current_costs_more_stamina": True,
                "under_bridge_shallow_water_traversable": True,
                "deep_water_mode": "SWIM_FOR_PLAYER_NPC_ANIMAL",
                "vehicles_deep_water": "BLOCKED_UNLESS_FUTURE_WATER_CAPABLE_VEHICLE",
                "balance_body_system": False,
            },
            "stamina": {
                "water_cost_depends_on": ["DEPTH", "FLOW", "LOAD", "DISTANCE"],
                "zero_stamina_in_water_can_defeat": True,
                "exhaustion_grace_s_candidate": self.EXHAUSTION_GRACE_S,
            },
            "inventory": {
                "base_slots_without_bag_candidate": self.BASE_SLOT_LIMIT,
                "bag_is_real_container": True,
                "bag_slots_candidate": self.BAG_SLOT_CAPACITY,
                "equipped_weapons_retained_on_death": True,
                "equipped_armor_clothes_retained_on_death": True,
                "quest_and_critical_unique_protected_from_permanent_loss": True,
            },
            "water_loot": {
                "individual_item_ttl_s": self.ITEM_WATER_TTL_S,
                "bag_ttl_s": self.BAG_WATER_TTL_S,
                "bag_floats": True,
                "land_bag_ttl": None,
            },
            "ownership": {
                "player_can_recover_npc_bag": True,
                "foreign_property_reaction_hook": True,
                "npc_auto_theft": False,
            },
            "canon_mutation": False,
        }

    def _event_existing(self, event_ref: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = self.runtime.conn.execute(
            "SELECT event_type,payload_hash,result_json,result_hash FROM arpg_stage16a_water_bag_events WHERE world_instance_id=? AND event_ref=?",
            (self.world_instance_id, str(event_ref)),
        ).fetchone()
        if not row:
            return None
        expected = sha256_text(canonical_json(payload))
        if row["event_type"] != event_type or row["payload_hash"] != expected:
            raise ConflictError("STAGE16A_WATER_BAG_EVENT_REF_CONFLICT")
        if sha256_text(row["result_json"]) != row["result_hash"]:
            raise RuntimeError("STAGE16A_WATER_BAG_EVENT_RESULT_HASH_MISMATCH")
        out = json.loads(row["result_json"])
        out["idempotent_replay"] = True
        return out

    def _record(self, event_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        ptext = canonical_json(payload)
        rtext = canonical_json(result)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT INTO arpg_stage16a_water_bag_events VALUES(?,?,?,?,?,?)",
                (self.world_instance_id, str(event_ref), event_type, sha256_text(ptext), rtext, sha256_text(rtext)),
            )
        return result

    def _save_carry(self, state: dict[str, Any]) -> None:
        text = canonical_json(state)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO arpg_stage16a_carry_profiles VALUES(?,?,?,?)",
                (self.world_instance_id, state["owner_ref"], text, sha256_text(text)),
            )

    def ensure_carry_profile(self, owner_ref: str) -> dict[str, Any]:
        row = self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_stage16a_carry_profiles WHERE world_instance_id=? AND owner_ref=?",
            (self.world_instance_id, str(owner_ref)),
        ).fetchone()
        if row:
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                raise RuntimeError("STAGE16A_CARRY_PROFILE_HASH_MISMATCH")
            return json.loads(row["payload_json"])
        items = self.engine.items_arpg(self.world_instance_id)
        items.ensure_inventory(str(owner_ref))
        state = {
            "owner_ref": str(owner_ref),
            "equipped_bag_ref": None,
            "base_slot_limit": self.BASE_SLOT_LIMIT,
            "policy": "SMALL_BASE_INVENTORY_BAG_EXTENDS_CARRY",
            "authority": self.AUTHORITY,
        }
        self._save_carry(state)
        return state

    def _save_bag(self, bag: dict[str, Any]) -> None:
        text = canonical_json(bag)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO arpg_stage16a_bags VALUES(?,?,?,?,?,?)",
                (self.world_instance_id, bag["bag_ref"], bag["property_owner_ref"], bag["state"], text, sha256_text(text)),
            )

    def bag(self, bag_ref: str) -> dict[str, Any]:
        row = self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_stage16a_bags WHERE world_instance_id=? AND bag_ref=?",
            (self.world_instance_id, str(bag_ref)),
        ).fetchone()
        if not row:
            raise KeyError("STAGE16A_BAG_NOT_FOUND:" + str(bag_ref))
        if sha256_text(row["payload_json"]) != row["payload_hash"]:
            raise RuntimeError("STAGE16A_BAG_HASH_MISMATCH")
        return json.loads(row["payload_json"])

    def _is_protected_definition(self, definition: dict[str, Any], instance: dict[str, Any] | None = None) -> bool:
        if str(definition.get("item_kind", "")).upper() in {"QUEST", "QUEST_ITEM", "QUEST_UTILITY"}:
            return True
        if instance and str(instance.get("rarity", "")).upper() == "SINGULAR":
            return True
        return False

    def equip_new_bag(self, owner_ref: str, *, event_ref: str, retained_instance_refs: Iterable[str] = ()) -> dict[str, Any]:
        retained = sorted({str(x) for x in retained_instance_refs if x})
        payload = {"owner_ref": str(owner_ref), "retained_instance_refs": retained}
        replay = self._event_existing(event_ref, "BAG_EQUIP", payload)
        if replay is not None:
            return replay
        carry = self.ensure_carry_profile(owner_ref)
        if carry.get("equipped_bag_ref"):
            return self._record(event_ref, "BAG_EQUIP", payload, {"status":"REJECTED","reason":"BAG_ALREADY_EQUIPPED","idempotent_replay":False})
        bag_ref = self._stable_ref("BAG-S16A-", f"{self.world_instance_id}|{owner_ref}|{event_ref}")
        items = self.engine.items_arpg(self.world_instance_id)
        items.ensure_inventory(bag_ref, slot_capacity=self.BAG_SLOT_CAPACITY, weight_capacity=self.BAG_WEIGHT_CAPACITY)
        inv = items.inventory_snapshot(owner_ref)
        equipped = {x for x in inv.get("equipped", {}).values() if x}
        protected_instances = equipped | set(retained)
        moved_stacks: list[dict[str, Any]] = []
        moved_instances: list[str] = []
        for item_ref, qty in list(inv.get("stacks", {}).items()):
            if int(qty) <= 0:
                continue
            out = items.transfer_item(owner_ref, bag_ref, item_ref, int(qty), event_ref=f"{event_ref}:STACK:{item_ref}")
            if out.get("status") == "PASS":
                moved_stacks.append({"item_ref":item_ref,"quantity":int(qty)})
        inv = items.inventory_snapshot(owner_ref)
        for instance_ref in list(inv.get("instance_refs", [])):
            if instance_ref in protected_instances:
                continue
            inst = items.instance(instance_ref)
            out = items.transfer_item(owner_ref, bag_ref, inst["item_ref"], 1, event_ref=f"{event_ref}:INST:{instance_ref}", instance_ref=instance_ref)
            if out.get("status") == "PASS":
                moved_instances.append(instance_ref)
        bag = {
            "bag_ref": bag_ref,
            "property_owner_ref": str(owner_ref),
            "carrier_ref": str(owner_ref),
            "state": "EQUIPPED",
            "location_kind": "CARRIED",
            "position": None,
            "float_state": None,
            "water_exposure_s": 0.0,
            "water_ttl_s": None,
            "slot_capacity": self.BAG_SLOT_CAPACITY,
            "weight_capacity": self.BAG_WEIGHT_CAPACITY,
            "foreign_recovery_ref": None,
            "authority": self.AUTHORITY,
        }
        self._save_bag(bag)
        carry["equipped_bag_ref"] = bag_ref
        self._save_carry(carry)
        return self._record(event_ref, "BAG_EQUIP", payload, {
            "status":"PASS","bag_ref":bag_ref,"bag":bag,"moved_stacks":moved_stacks,"moved_instances":moved_instances,"idempotent_replay":False
        })

    def effective_inventory_owner(self, owner_ref: str) -> str:
        carry = self.ensure_carry_profile(owner_ref)
        bag_ref = carry.get("equipped_bag_ref")
        if bag_ref:
            bag = self.bag(bag_ref)
            if bag.get("state") == "EQUIPPED" and bag.get("carrier_ref") == str(owner_ref):
                return bag_ref
        return str(owner_ref)

    def carry_metrics(self, owner_ref: str) -> dict[str, Any]:
        items = self.engine.items_arpg(self.world_instance_id)
        items.ensure_inventory(str(owner_ref))
        base = items.inventory_snapshot(str(owner_ref))
        total_weight = float(base["metrics"]["current_weight"])
        total_slots = int(base["metrics"]["used_slots"])
        capacity = float(base["weight_capacity"])
        bag_ref = self.effective_inventory_owner(owner_ref)
        bag_metrics = None
        if bag_ref != str(owner_ref):
            bag = items.inventory_snapshot(bag_ref)
            total_weight += float(bag["metrics"]["current_weight"])
            total_slots += int(bag["metrics"]["used_slots"])
            capacity = max(capacity, float(bag["weight_capacity"]))
            bag_metrics = bag["metrics"]
        return {
            "current_weight": round(total_weight, 6),
            "weight_capacity": round(capacity, 6),
            "used_slots_total": total_slots,
            "base_slot_limit": self.BASE_SLOT_LIMIT,
            "bag_ref": bag_ref if bag_ref != str(owner_ref) else None,
            "bag_metrics": bag_metrics,
            "inventory_authority": "STAGE05_UNIVERSAL_ITEM_CORE_PLUS_STAGE16A_BAG_ROUTING",
        }

    def can_accept_carried(self, owner_ref: str, item_ref: str, quantity: int) -> dict[str, Any]:
        dest = self.effective_inventory_owner(owner_ref)
        items = self.engine.items_arpg(self.world_instance_id)
        inv = items.inventory_snapshot(dest)
        definition = items.definition(item_ref)
        used = int(inv["metrics"]["used_slots"])
        existing = int(inv.get("stacks", {}).get(item_ref, 0))
        if definition.get("stackable"):
            stack_max = max(1, int(definition.get("stack_max", 1)))
            before_slots = math.ceil(existing / stack_max) if existing else 0
            after_slots = math.ceil((existing + int(quantity)) / stack_max)
            projected = used + (after_slots - before_slots)
        else:
            projected = used + int(quantity)
        logical_limit = int(inv["slot_capacity"]) if dest != str(owner_ref) else self.BASE_SLOT_LIMIT
        return {
            "status": "PASS" if projected <= logical_limit else "REJECTED",
            "reason": None if projected <= logical_limit else "BASE_INVENTORY_SLOT_LIMIT_WITHOUT_BAG",
            "effective_inventory_owner_ref": dest,
            "projected_used_slots": projected,
            "logical_slot_limit": logical_limit,
        }

    def grant_carried_item(self, owner_ref: str, item_ref: str, quantity: int, *, event_ref: str, rarity: str | None = None, quality: int | None = None) -> dict[str, Any]:
        dest = self.effective_inventory_owner(owner_ref)
        items = self.engine.items_arpg(self.world_instance_id)
        fit = self.can_accept_carried(owner_ref, item_ref, int(quantity))
        if fit["status"] != "PASS":
            return fit
        out = items.grant_item(dest, item_ref, int(quantity), event_ref=event_ref, rarity=rarity, quality=quality)
        if out.get("status") == "PASS":
            out = dict(out)
            out["effective_inventory_owner_ref"] = dest
            out["bag_equipped"] = dest != str(owner_ref)
        return out

    def _return_protected_from_bag(self, owner_ref: str, bag_ref: str, *, event_ref: str) -> dict[str, Any]:
        items = self.engine.items_arpg(self.world_instance_id)
        returned_stacks: list[dict[str, Any]] = []
        returned_instances: list[str] = []
        inv = items.inventory_snapshot(bag_ref)
        for item_ref, qty in list(inv.get("stacks", {}).items()):
            definition = items.definition(item_ref)
            if self._is_protected_definition(definition):
                out = items.transfer_item(bag_ref, owner_ref, item_ref, int(qty), event_ref=f"{event_ref}:PSTACK:{item_ref}")
                if out.get("status") == "PASS":
                    returned_stacks.append({"item_ref":item_ref,"quantity":int(qty)})
        inv = items.inventory_snapshot(bag_ref)
        for instance_ref in list(inv.get("instance_refs", [])):
            inst = items.instance(instance_ref)
            definition = items.definition(inst["item_ref"])
            if self._is_protected_definition(definition, inst):
                out = items.transfer_item(bag_ref, owner_ref, inst["item_ref"], 1, event_ref=f"{event_ref}:PINST:{instance_ref}", instance_ref=instance_ref)
                if out.get("status") == "PASS":
                    returned_instances.append(instance_ref)
        return {"stacks":returned_stacks,"instances":returned_instances}

    def drop_bag_on_death(self, owner_ref: str, *, in_water: bool, position: dict[str, float], event_ref: str) -> dict[str, Any]:
        payload = {"owner_ref":str(owner_ref),"in_water":bool(in_water),"position":{k:float(position.get(k,0.0)) for k in ("iso_x_m","iso_y_m","altitude_m")}}
        replay = self._event_existing(event_ref, "BAG_DEATH_DROP", payload)
        if replay is not None:
            return replay
        carry = self.ensure_carry_profile(owner_ref)
        bag_ref = carry.get("equipped_bag_ref")
        if not bag_ref:
            return self._record(event_ref, "BAG_DEATH_DROP", payload, {"status":"PASS","bag_dropped":False,"reason":"NO_BAG_EQUIPPED","idempotent_replay":False})
        protected = self._return_protected_from_bag(owner_ref, bag_ref, event_ref=event_ref)
        bag = self.bag(bag_ref)
        bag.update({
            "carrier_ref": None,
            "state": "DROPPED_WATER_FLOATING" if in_water else "DROPPED_LAND",
            "location_kind": "WATER" if in_water else "LAND",
            "position": payload["position"],
            "float_state": "FLOATING" if in_water else "GROUND_STABLE",
            "water_exposure_s": 0.0,
            "water_ttl_s": self.BAG_WATER_TTL_S if in_water else None,
            "foreign_recovery_ref": None,
        })
        self._save_bag(bag)
        carry["equipped_bag_ref"] = None
        self._save_carry(carry)
        return self._record(event_ref, "BAG_DEATH_DROP", payload, {
            "status":"PASS","bag_dropped":True,"bag_ref":bag_ref,"bag":bag,"protected_returned":protected,"idempotent_replay":False
        })

    def recover_bag(self, bag_ref: str, claimant_ref: str, *, claimant_kind: str, event_ref: str) -> dict[str, Any]:
        payload = {"bag_ref":str(bag_ref),"claimant_ref":str(claimant_ref),"claimant_kind":str(claimant_kind).upper()}
        replay = self._event_existing(event_ref, "BAG_RECOVER", payload)
        if replay is not None:
            return replay
        bag = self.bag(bag_ref)
        if bag.get("state") not in {"DROPPED_LAND","DROPPED_WATER_FLOATING"}:
            return self._record(event_ref, "BAG_RECOVER", payload, {"status":"REJECTED","reason":"BAG_NOT_RECOVERABLE","idempotent_replay":False})
        owner = bag["property_owner_ref"]
        if str(claimant_ref) == owner:
            carry = self.ensure_carry_profile(owner)
            if carry.get("equipped_bag_ref"):
                return self._record(event_ref, "BAG_RECOVER", payload, {"status":"REJECTED","reason":"CLAIMANT_ALREADY_HAS_BAG_EQUIPPED","idempotent_replay":False})
            bag.update({"carrier_ref":owner,"state":"EQUIPPED","location_kind":"CARRIED","position":None,"float_state":None,"water_ttl_s":None})
            carry["equipped_bag_ref"] = bag_ref
            self._save_carry(carry); self._save_bag(bag)
            return self._record(event_ref, "BAG_RECOVER", payload, {"status":"PASS","ownership":"OWNER","bag":bag,"idempotent_replay":False})
        if payload["claimant_kind"] != "PLAYER":
            return self._record(event_ref, "BAG_RECOVER", payload, {"status":"REJECTED","reason":"FOREIGN_NPC_BAG_RECOVERY_NOT_ENABLED","idempotent_replay":False})
        bag.update({"carrier_ref":str(claimant_ref),"state":"RECOVERED_FOREIGN","location_kind":"CARRIED_FOREIGN","position":None,"float_state":None,"water_ttl_s":None,"foreign_recovery_ref":str(claimant_ref)})
        self._save_bag(bag)
        return self._record(event_ref, "BAG_RECOVER", payload, {
            "status":"PASS","ownership":"FOREIGN_PROPERTY","property_owner_ref":owner,
            "reaction_hook":"PROPERTY_RECOVERY_CONTEXT_ELIGIBLE","auto_theft":False,"bag":bag,"idempotent_replay":False
        })

    @staticmethod
    def _flow_class(flow_speed_mps: float) -> tuple[str, float]:
        f = max(0.0, float(flow_speed_mps))
        if f < 0.45:
            return "CALM", 1.0
        if f < 1.15:
            return "CURRENT", 1.35
        return "STRONG_CURRENT", 1.85

    def water_traversal_sample(self, *, actor_kind: str, depth_m: float, flow_speed_mps: float, distance_m: float, load_fraction: float, under_bridge: bool = False) -> dict[str, Any]:
        kind = str(actor_kind).upper().strip()
        if kind not in {"PLAYER","NPC","ANIMAL","VEHICLE"}:
            raise ValidationError("unsupported water traversal actor_kind")
        depth = max(0.0, float(depth_m)); distance = max(0.0, float(distance_m)); load = min(2.0, max(0.0, float(load_fraction)))
        flow_class, flow_factor = self._flow_class(flow_speed_mps)
        shallow = depth <= self.SHALLOW_DEPTH_M
        if kind == "VEHICLE":
            if depth > self.VEHICLE_MAX_WADE_DEPTH_M:
                return {"status":"BLOCKED","reason":"VEHICLE_WATER_TOO_DEEP","mode":"BLOCKED","stamina_cost":0.0,"flow_class":flow_class,"under_bridge":bool(under_bridge)}
            speed_factor = max(0.35, 1.0 - depth * 0.55 - max(0.0,float(flow_speed_mps))*0.12)
            return {"status":"PASS","mode":"WADE_VEHICLE","stamina_cost":0.0,"speed_factor":round(speed_factor,6),"traction_penalty":round(1.0-speed_factor,6),"flow_class":flow_class,"under_bridge":bool(under_bridge),"shallow":True}
        mode = "WADE" if shallow else "SWIM"
        base_per_m = 0.34 if shallow else 0.95
        depth_factor = 1.0 + (depth / max(0.1,self.SHALLOW_DEPTH_M))*0.18 if shallow else 1.35 + min(2.0, depth-self.SHALLOW_DEPTH_M)*0.18
        load_factor = 1.0 + 0.75 * load
        stamina_cost = distance * base_per_m * depth_factor * flow_factor * load_factor
        speed_factor = max(0.25, 1.0 / (1.0 + 0.30*(depth_factor-1.0) + 0.20*(flow_factor-1.0) + 0.15*load))
        return {
            "status":"PASS","mode":mode,"stamina_cost":round(stamina_cost,6),"speed_factor":round(speed_factor,6),
            "flow_class":flow_class,"flow_factor":flow_factor,"under_bridge":bool(under_bridge),"shallow":shallow,
            "balance_body_system":False,"death_risk_if_stamina_exhausted":True,
        }

    def _save_exhaustion(self, state: dict[str, Any]) -> None:
        text = canonical_json(state)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO arpg_stage16a_water_exhaustion VALUES(?,?,?,?)",
                (self.world_instance_id,state["actor_ref"],text,sha256_text(text)),
            )

    def exhaustion_state(self, actor_ref: str) -> dict[str, Any]:
        row = self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_stage16a_water_exhaustion WHERE world_instance_id=? AND actor_ref=?",
            (self.world_instance_id,str(actor_ref)),
        ).fetchone()
        if row:
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                raise RuntimeError("STAGE16A_WATER_EXHAUSTION_HASH_MISMATCH")
            return json.loads(row["payload_json"])
        state={"actor_ref":str(actor_ref),"actor_kind":None,"zero_stamina_water_s":0.0,"life_state":"ALIVE","authority":self.AUTHORITY}
        self._save_exhaustion(state); return state

    def exhaustion_tick(self, actor_ref: str, *, actor_kind: str, stamina: float, in_water: bool, delta_s: float, event_ref: str) -> dict[str, Any]:
        payload={"actor_ref":str(actor_ref),"actor_kind":str(actor_kind).upper(),"stamina":round(float(stamina),6),"in_water":bool(in_water),"delta_s":round(float(delta_s),6)}
        replay=self._event_existing(event_ref,"WATER_EXHAUSTION_TICK",payload)
        if replay is not None: return replay
        st=self.exhaustion_state(actor_ref); st["actor_kind"]=payload["actor_kind"]
        if not in_water or float(stamina)>1e-9:
            st["zero_stamina_water_s"]=0.0
        elif st.get("life_state") == "ALIVE":
            st["zero_stamina_water_s"]=round(float(st.get("zero_stamina_water_s",0.0))+max(0.0,float(delta_s)),6)
            if st["zero_stamina_water_s"]>=self.EXHAUSTION_GRACE_S:
                st["life_state"]="DEFEATED"
        self._save_exhaustion(st)
        return self._record(event_ref,"WATER_EXHAUSTION_TICK",payload,{
            "status":"PASS","actor_ref":str(actor_ref),"life_state":st["life_state"],"zero_stamina_water_s":st["zero_stamina_water_s"],
            "grace_s":self.EXHAUSTION_GRACE_S,"defeat_required":st["life_state"]=="DEFEATED","idempotent_replay":False
        })

    def mark_ground_drop_water(self, drop_ref: str, *, in_water: bool, flow_speed_mps: float = 0.0, event_ref: str) -> dict[str, Any]:
        return self.ground_loot.set_water_state(drop_ref, in_water=bool(in_water), flow_speed_mps=float(flow_speed_mps), ttl_s=self.ITEM_WATER_TTL_S, event_ref=event_ref)

    def advance_water_time(self, delta_s: float, *, event_ref: str) -> dict[str, Any]:
        payload={"delta_s":round(float(delta_s),6)}
        replay=self._event_existing(event_ref,"ADVANCE_WATER_TIME",payload)
        if replay is not None: return replay
        delta=max(0.0,float(delta_s))
        loot=self.ground_loot.advance_water_exposure(delta, event_ref=f"{event_ref}:LOOT")
        expired_bags=[]
        rows=self.runtime.conn.execute(
            "SELECT bag_ref,payload_json,payload_hash FROM arpg_stage16a_bags WHERE world_instance_id=? AND state='DROPPED_WATER_FLOATING'",
            (self.world_instance_id,),
        ).fetchall()
        for row in rows:
            if sha256_text(row["payload_json"])!=row["payload_hash"]:
                raise RuntimeError("STAGE16A_BAG_HASH_MISMATCH")
            bag=json.loads(row["payload_json"]); bag["water_exposure_s"]=round(float(bag.get("water_exposure_s",0.0))+delta,6)
            if bag["water_exposure_s"]>=self.BAG_WATER_TTL_S:
                bag["state"]="SUNK"; bag["float_state"]="SUNK"; expired_bags.append(bag["bag_ref"])
            self._save_bag(bag)
        return self._record(event_ref,"ADVANCE_WATER_TIME",payload,{
            "status":"PASS","delta_s":delta,"ground_loot":loot,"bags_sunk":expired_bags,"idempotent_replay":False
        })

    def verify(self) -> dict[str, Any]:
        failures=[]
        for table,keycol in (("arpg_stage16a_carry_profiles","owner_ref"),("arpg_stage16a_bags","bag_ref"),("arpg_stage16a_water_exhaustion","actor_ref")):
            rows=self.runtime.conn.execute(f"SELECT {keycol},payload_json,payload_hash FROM {table} WHERE world_instance_id=?",(self.world_instance_id,)).fetchall()
            for r in rows:
                if sha256_text(r["payload_json"])!=r["payload_hash"]:
                    failures.append(f"{table}:{r[keycol]}:HASH")
        if self.ITEM_WATER_TTL_S != 900.0: failures.append("ITEM_WATER_TTL")
        if self.BAG_WATER_TTL_S != 1800.0: failures.append("BAG_WATER_TTL")
        return {
            "status":"PASS" if not failures else "FAIL","failures":failures,
            "bags":self.runtime.conn.execute("SELECT COUNT(*) c FROM arpg_stage16a_bags WHERE world_instance_id=?",(self.world_instance_id,)).fetchone()["c"],
            "carry_profiles":self.runtime.conn.execute("SELECT COUNT(*) c FROM arpg_stage16a_carry_profiles WHERE world_instance_id=?",(self.world_instance_id,)).fetchone()["c"],
            "authority":self.AUTHORITY,
        }
