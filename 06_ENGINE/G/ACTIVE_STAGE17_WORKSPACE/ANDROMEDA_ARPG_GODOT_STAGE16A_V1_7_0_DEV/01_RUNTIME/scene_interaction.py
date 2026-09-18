from __future__ import annotations

import copy
import hashlib
import random
from typing import Any

from content_catalog import (
    DUNGEON_WEAPONS,
    DUNGEON_WEAPON_BY_REF,
    ITEM_NAMES,
    dungeon_name,
    object_name,
    name_status,
)

SCENE_TYPES = (
    "DOOR", "TRAPDOOR", "CHAIR", "BOOK", "TORCH", "GROUND_WEAPON",
    "CHEST", "LEVER", "RUNE_PEDESTAL", "CONSOLE",
)


def _seed(*parts: Any) -> int:
    raw = "|".join(map(str, parts)).encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest()[:16], 16)


class SceneInteractionSystem:
    VERSION = "V1.2.1-DEV"
    AUTHORITY = "AUTHOR_AUTHORIZED_SCENE_INTERACTION_EXPANSION_PENDING_MASTER_CONSOLIDATION"

    def __init__(self, country_system: Any) -> None:
        self.country = country_system
        self.seed = int(country_system.seed)
        self.bootstrap()

    def _rng(self, *parts: Any) -> random.Random:
        return random.Random(_seed(self.seed, *parts))

    def bootstrap(self) -> dict[str, Any]:
        created_dungeons = 0
        created_objects = 0
        for state in self.country.world["country"]["states"]:
            for block in state["blocks"]:
                block.setdefault("scene_objects", [])
                block.setdefault("dungeons", [])
                if not block["scene_objects"]:
                    block["scene_objects"] = self._make_block_objects(state, block)
                if not block["dungeons"]:
                    block["dungeons"] = self._make_dungeons(state, block)
                for city in block.get("cities", []):
                    city.setdefault("scene_objects", [])
                    if not city["scene_objects"]:
                        city["scene_objects"] = self._make_city_objects(state, block, city)
                created_dungeons += len(block["dungeons"])
                created_objects += len(block["scene_objects"])
                created_objects += sum(len(c.get("scene_objects", [])) for c in block.get("cities", []))
                created_objects += sum(len(d.get("objects", [])) for d in block.get("dungeons", []))
        self.country.reconcile_country_inventory()
        if self.country.runtime and self.country.world_instance_id:
            self.country._record_event("SCENE_SYSTEM_BOOTSTRAPPED", {"dungeons": created_dungeons, "objects": created_objects})
        return {"status": "PASS", "dungeons": created_dungeons, "objects": created_objects}

    def _base_obj(self, obj_id: str, typ: str, *, block_id: str, city_id: str | None = None, dungeon_id: str | None = None) -> dict[str, Any]:
        return {
            "id": obj_id,
            "name": object_name(typ, obj_id),
            "name_status": name_status(),
            "object_type": typ,
            "status": "ACTIVE",
            "block_id": block_id,
            "city_id": city_id,
            "dungeon_id": dungeon_id,
            "interaction_enabled": True,
        }

    def _make_block_objects(self, state: dict[str, Any], block: dict[str, Any]) -> list[dict[str, Any]]:
        rng = self._rng("block-scenes", block["id"])
        out: list[dict[str, Any]] = []
        # Contextual outdoor interactables. Root Deep avoids normal furniture.
        if block["root_deep"]:
            types = ["RUNE_PEDESTAL", "TORCH", "LEVER"]
        else:
            types = ["DOOR", "TORCH"]
            if state["archetype"] in ("TECHNOLOGY", "ROBOTICS"):
                types += ["CONSOLE"]
            if state["archetype"] == "MAGIC":
                types += ["RUNE_PEDESTAL"]
            if rng.random() < 0.35:
                types += ["GROUND_WEAPON"]
        for i, typ in enumerate(types, 1):
            obj_id = f"SCN-{block['id']}-OUT-{i:02d}"
            obj = self._base_obj(obj_id, typ, block_id=block["id"])
            self._initialize_state(obj, rng, state, block)
            out.append(obj)
        return out

    def _make_city_objects(self, state: dict[str, Any], block: dict[str, Any], city: dict[str, Any]) -> list[dict[str, Any]]:
        rng = self._rng("city-scenes", city["id"])
        types = ["DOOR", "CHAIR", "BOOK", "TORCH", "CHEST"]
        if state["archetype"] in ("TECHNOLOGY", "ROBOTICS"):
            types.append("CONSOLE")
        if state["archetype"] == "MAGIC":
            types.append("RUNE_PEDESTAL")
        if state["archetype"] == "MILITARY" or rng.random() < 0.20:
            types.append("GROUND_WEAPON")
        out = []
        for i, typ in enumerate(types, 1):
            obj_id = f"SCN-{city['id']}-{i:02d}"
            obj = self._base_obj(obj_id, typ, block_id=block["id"], city_id=city["id"])
            self._initialize_state(obj, rng, state, block)
            out.append(obj)
        return out

    def _make_dungeons(self, state: dict[str, Any], block: dict[str, Any]) -> list[dict[str, Any]]:
        rng = self._rng("dungeons", block["id"])
        if block["root_deep"]:
            count = 1 + (1 if rng.random() < 0.45 else 0)
        else:
            chance = 0.22 + float(block["climate"]["magic_intensity"]) * 0.20 + float(block["climate"]["resource_richness"]) * 0.18
            count = 1 if rng.random() < chance else 0
            if rng.random() < chance * 0.18:
                count += 1
        out: list[dict[str, Any]] = []
        for dindex in range(1, count + 1):
            did = f"DNG-{block['state_id']}-{block['id'].split('-')[-1]}-{dindex:02d}"
            darkness = rng.randint(72, 100) if block["root_deep"] else rng.randint(45, 94)
            dungeon = {
                "id": did,
                "name": dungeon_name(did, block["root_deep"], state["archetype"]),
                "name_status": name_status(),
                "status": "ACTIVE",
                "state_id": block["state_id"],
                "block_id": block["id"],
                "root_deep": bool(block["root_deep"]),
                "hazardous": True,
                "darkness_level": darkness,
                "recommended_light": darkness >= 60,
                "objects": [],
            }
            # Every dungeon intentionally supports the requested interaction vocabulary.
            base_types = ["DOOR", "TRAPDOOR", "CHAIR", "BOOK", "TORCH", "CHEST", "LEVER"]
            if state["archetype"] in ("TECHNOLOGY", "ROBOTICS"):
                base_types.append("CONSOLE")
            if state["archetype"] == "MAGIC" or block["root_deep"]:
                base_types.append("RUNE_PEDESTAL")
            for i, typ in enumerate(base_types, 1):
                oid = f"{did}-OBJ-{i:02d}"
                obj = self._base_obj(oid, typ, block_id=block["id"], dungeon_id=did)
                self._initialize_state(obj, rng, state, block)
                dungeon["objects"].append(obj)
            # Required dungeon weapon families: sword, crossbow, bow and whip.
            offset = len(dungeon["objects"])
            for wi, spec in enumerate(DUNGEON_WEAPONS, 1):
                oid = f"{did}-WPN-{wi:02d}"
                obj = self._base_obj(oid, "GROUND_WEAPON", block_id=block["id"], dungeon_id=did)
                condition_pct = rng.randint(18, 72)
                obj.update({
                    "name": f"{spec['name']} — desgastada",
                    "item_ref": spec["item_ref"],
                    "item_name": spec["name"],
                    "weapon_family": spec["family"],
                    "tier": spec["tier"],
                    "quantity": 1,
                    "condition": "OLD",
                    "durability_max": int(spec["base_durability"]),
                    "durability": max(1, int(spec["base_durability"] * condition_pct / 100)),
                })
                dungeon["objects"].append(obj)
            out.append(dungeon)
        return out

    def _initialize_state(self, obj: dict[str, Any], rng: random.Random, state: dict[str, Any], block: dict[str, Any]) -> None:
        typ = obj["object_type"]
        if typ in ("DOOR", "TRAPDOOR"):
            obj.update({"is_open": False, "locked": bool(rng.random() < (0.18 if typ == "DOOR" else 0.30)), "key_ref": "ITEM-OLD-KEY"})
        elif typ == "CHAIR":
            obj.update({"occupied_by": None, "capacity": 1})
        elif typ == "BOOK":
            tag = {"TECHNOLOGY": "KNOW-TECH", "ROBOTICS": "KNOW-ROBOTICS", "MILITARY": "KNOW-MILITARY", "MAGIC": "KNOW-MAGIC", "NATURE": "KNOW-NATURE"}.get(state["archetype"], "KNOW-LOCAL")
            obj.update({"read_count": 0, "knowledge_tag": f"{tag}-{block['id']}"})
        elif typ == "TORCH":
            obj.update({"item_ref": "ITEM-TORCH", "item_name": ITEM_NAMES["ITEM-TORCH"], "quantity": 1, "lit": False, "light_radius_m": 9})
        elif typ == "GROUND_WEAPON":
            spec = DUNGEON_WEAPONS[rng.randrange(len(DUNGEON_WEAPONS))]
            pct = rng.randint(12, 58)
            obj.update({"item_ref": spec["item_ref"], "item_name": spec["name"], "weapon_family": spec["family"], "tier": spec["tier"], "quantity": 1, "condition": "OLD", "durability_max": spec["base_durability"], "durability": max(1, int(spec["base_durability"] * pct / 100))})
        elif typ == "CHEST":
            obj.update({"is_open": False, "inventory": {"ITEM-OLD-KEY": 1, "ITEM-TORCH": 1 + rng.randint(0, 1)}, "looted": False})
        elif typ == "LEVER":
            obj.update({"position": "UP", "linked_effect": "LOCAL_MECHANISM_TOGGLE"})
        elif typ == "RUNE_PEDESTAL":
            obj.update({"activated": False, "magic_intensity": round(float(block["climate"]["magic_intensity"]), 4)})
        elif typ == "CONSOLE":
            obj.update({"powered": True, "access_level": "LOCAL_OPERATIONAL"})

    def _all_objects(self):
        for st in self.country.world["country"]["states"]:
            for b in st["blocks"]:
                for obj in b.get("scene_objects", []):
                    yield b, None, None, obj
                for c in b.get("cities", []):
                    for obj in c.get("scene_objects", []):
                        yield b, c, None, obj
                for d in b.get("dungeons", []):
                    for obj in d.get("objects", []):
                        yield b, None, d, obj

    def dungeon(self, dungeon_id: str) -> dict[str, Any]:
        for st in self.country.world["country"]["states"]:
            for b in st["blocks"]:
                for d in b.get("dungeons", []):
                    if d["id"] == dungeon_id:
                        return d
        raise KeyError(dungeon_id)

    def scene_object(self, object_id: str):
        for b, c, d, obj in self._all_objects():
            if obj["id"] == object_id:
                return b, c, d, obj
        raise KeyError(object_id)

    def enter_dungeon(self, npc_id: str, dungeon_id: str) -> dict[str, Any]:
        npc = self.country.npc(npc_id)
        d = self.dungeon(dungeon_id)
        if npc["block_id"] != d["block_id"]:
            return {"status": "REJECTED", "reason": "ACTOR_NOT_IN_DUNGEON_BLOCK"}
        if npc["class"] == "CHILD":
            return {"status": "REJECTED", "reason": "PROTECTED_MINOR_DUNGEON"}
        if npc["class"] == "WORKER" and d.get("hazardous"):
            return {"status": "REJECTED", "reason": "PROTECTED_WORKER_HAZARDOUS_DUNGEON"}
        npc["scene_id"] = dungeon_id
        npc["city_id"] = None
        self._commit("DUNGEON_ENTERED", {"npc_id": npc_id, "dungeon_id": dungeon_id})
        return {"status": "PASS", "npc_id": npc_id, "dungeon_id": dungeon_id, "darkness_level": d["darkness_level"], "recommended_light": d["recommended_light"]}

    def leave_dungeon(self, npc_id: str) -> dict[str, Any]:
        npc = self.country.npc(npc_id)
        old = npc.get("scene_id")
        npc["scene_id"] = None
        self._commit("DUNGEON_LEFT", {"npc_id": npc_id, "dungeon_id": old})
        return {"status": "PASS", "npc_id": npc_id, "dungeon_id": old}

    def _locality(self, npc: dict[str, Any], b: dict[str, Any], c: dict[str, Any] | None, d: dict[str, Any] | None) -> tuple[bool, str]:
        if npc.get("block_id") != b["id"]:
            return False, "ACTOR_NOT_IN_BLOCK"
        if d is not None and npc.get("scene_id") != d["id"]:
            return False, "ACTOR_NOT_IN_DUNGEON"
        if c is not None and npc.get("city_id") != c["id"]:
            return False, "ACTOR_NOT_IN_CITY"
        return True, "OK"

    def _has_light(self, npc: dict[str, Any]) -> bool:
        return bool(npc.get("active_light"))

    def interact(self, npc_id: str, object_id: str, action: str) -> dict[str, Any]:
        action = action.upper().strip()
        npc = self.country.npc(npc_id)
        b, c, d, obj = self.scene_object(object_id)
        ok, reason = self._locality(npc, b, c, d)
        if not ok:
            return {"status": "REJECTED", "reason": reason}
        typ = obj["object_type"]
        if d is not None and d["darkness_level"] >= 70 and action in ("READ", "INSPECT") and not self._has_light(npc):
            return {"status": "REJECTED", "reason": "INSUFFICIENT_LIGHT"}

        result: dict[str, Any]
        if typ in ("DOOR", "TRAPDOOR") and action in ("OPEN", "CLOSE"):
            if action == "OPEN" and obj.get("locked"):
                if npc["inventory"].get(obj.get("key_ref"), 0) <= 0:
                    return {"status": "REJECTED", "reason": "LOCKED_REQUIRES_KEY"}
                obj["locked"] = False
            obj["is_open"] = action == "OPEN"
            result = {"status": "PASS", "is_open": obj["is_open"], "locked": obj.get("locked", False)}
        elif typ == "CHAIR" and action in ("SIT", "STAND"):
            if action == "SIT":
                if obj.get("occupied_by") not in (None, npc_id):
                    return {"status": "REJECTED", "reason": "CHAIR_OCCUPIED"}
                obj["occupied_by"] = npc_id
            else:
                if obj.get("occupied_by") == npc_id:
                    obj["occupied_by"] = None
            result = {"status": "PASS", "occupied_by": obj.get("occupied_by")}
        elif typ == "BOOK" and action == "READ":
            obj["read_count"] += 1
            tag = obj["knowledge_tag"]
            if tag not in npc["knowledge_tags"]:
                npc["knowledge_tags"].append(tag)
            result = {"status": "PASS", "knowledge_tag": tag, "read_count": obj["read_count"]}
        elif typ == "TORCH" and action == "TAKE":
            result = self._take_item_object(npc, obj)
        elif typ == "TORCH" and action == "LIGHT":
            if npc["inventory"].get("ITEM-TORCH", 0) <= 0:
                return {"status": "REJECTED", "reason": "NO_TORCH_IN_INVENTORY"}
            npc["active_light"] = "ITEM-TORCH"
            result = {"status": "PASS", "active_light": npc["active_light"], "light_radius_m": obj.get("light_radius_m", 9)}
        elif typ == "GROUND_WEAPON" and action == "TAKE":
            result = self._take_item_object(npc, obj, instance=True)
        elif typ == "CHEST" and action == "OPEN":
            obj["is_open"] = True
            result = {"status": "PASS", "is_open": True, "contents": copy.deepcopy(obj["inventory"])}
        elif typ == "CHEST" and action == "LOOT":
            if not obj.get("is_open"):
                return {"status": "REJECTED", "reason": "CHEST_CLOSED"}
            moved = {}
            for item, qty in list(obj["inventory"].items()):
                if qty > 0:
                    npc["inventory"][item] = npc["inventory"].get(item, 0) + qty
                    moved[item] = qty
                    obj["inventory"][item] = 0
            obj["looted"] = True
            result = {"status": "PASS", "moved": moved}
        elif typ == "LEVER" and action == "PULL":
            obj["position"] = "DOWN" if obj["position"] == "UP" else "UP"
            result = {"status": "PASS", "position": obj["position"], "effect": obj["linked_effect"]}
        elif typ == "RUNE_PEDESTAL" and action == "ACTIVATE":
            obj["activated"] = True
            result = {"status": "PASS", "activated": True, "magic_intensity": obj["magic_intensity"]}
        elif typ == "CONSOLE" and action == "USE":
            result = {"status": "PASS", "powered": obj["powered"], "access_level": obj["access_level"]}
        else:
            return {"status": "REJECTED", "reason": "ACTION_NOT_SUPPORTED_FOR_OBJECT", "object_type": typ, "action": action}

        result.update({"npc_id": npc_id, "object_id": object_id, "object_type": typ, "action": action})
        self._commit("SCENE_INTERACTION", result)
        return result

    def inventory_light(self, npc_id: str, action: str = "LIGHT") -> dict[str, Any]:
        """Use a carried torch independently of the scene where it was picked up."""
        npc = self.country.npc(npc_id); action = action.upper().strip()
        if action == "LIGHT":
            if int(npc.get("inventory", {}).get("ITEM-TORCH", 0)) <= 0:
                return {"status": "REJECTED", "reason": "NO_TORCH_IN_INVENTORY", "npc_id": npc_id}
            npc["active_light"] = "ITEM-TORCH"
        elif action == "EXTINGUISH":
            npc["active_light"] = None
        else:
            return {"status": "REJECTED", "reason": "UNSUPPORTED_LIGHT_ACTION", "npc_id": npc_id}
        out = {"status": "PASS", "npc_id": npc_id, "action": action, "active_light": npc.get("active_light")}
        self._commit("INVENTORY_LIGHT_CHANGED", out)
        return out

    def equip_carried_weapon(self, npc_id: str, item_ref: str) -> dict[str, Any]:
        npc = self.country.npc(npc_id)
        spec = DUNGEON_WEAPON_BY_REF.get(item_ref)
        if spec is None:
            return {"status": "REJECTED", "reason": "NOT_SCENE_WEAPON", "npc_id": npc_id, "item_ref": item_ref}
        if int(npc.get("inventory", {}).get(item_ref, 0)) <= 0:
            return {"status": "REJECTED", "reason": "WEAPON_NOT_OWNED", "npc_id": npc_id, "item_ref": item_ref}
        instances = [x for x in npc.get("item_instances", []) if x.get("item_ref") == item_ref and int(x.get("durability") or 0) > 0]
        if not instances:
            return {"status": "REJECTED", "reason": "NO_FUNCTIONAL_WEAPON_INSTANCE", "npc_id": npc_id, "item_ref": item_ref}
        inst = max(instances, key=lambda x: int(x.get("durability") or 0))
        npc["equipped_weapon"] = {
            "item_ref": item_ref,
            "name": spec["name"],
            "family": spec["family"],
            "tier": spec["tier"],
            "stats": copy.deepcopy(spec["stats"]),
            "source_object_id": inst["source_object_id"],
            "durability": inst["durability"],
            "durability_max": inst["durability_max"],
            "authority": "AUTHOR_AUTHORIZED_DUNGEON_WEAPON_DEV",
        }
        out = {"status": "PASS", "npc_id": npc_id, "equipped_weapon": copy.deepcopy(npc["equipped_weapon"])}
        self._commit("SCENE_WEAPON_EQUIPPED", out)
        return out

    def unequip_carried_weapon(self, npc_id: str) -> dict[str, Any]:
        npc = self.country.npc(npc_id); previous = copy.deepcopy(npc.get("equipped_weapon"))
        npc["equipped_weapon"] = None
        out = {"status": "PASS", "npc_id": npc_id, "previous": previous}
        self._commit("SCENE_WEAPON_UNEQUIPPED", out)
        return out

    def _take_item_object(self, npc: dict[str, Any], obj: dict[str, Any], *, instance: bool = False) -> dict[str, Any]:
        qty = int(obj.get("quantity", 0))
        if obj.get("status") == "TAKEN" or qty <= 0:
            return {"status": "REJECTED", "reason": "OBJECT_ALREADY_TAKEN"}
        item = obj["item_ref"]
        npc["inventory"][item] = npc["inventory"].get(item, 0) + qty
        if instance:
            npc.setdefault("item_instances", []).append({
                "source_object_id": obj["id"],
                "item_ref": item,
                "name": obj.get("item_name", ITEM_NAMES.get(item, item)),
                "condition": obj.get("condition", "USED"),
                "durability": obj.get("durability"),
                "durability_max": obj.get("durability_max"),
            })
        obj["quantity"] = 0
        obj["status"] = "TAKEN"
        return {"status": "PASS", "item_ref": item, "quantity": qty, "npc_total": npc["inventory"][item]}

    def _commit(self, event_type: str, payload: dict[str, Any]) -> None:
        self.country.reconcile_country_inventory()
        if self.country.runtime and self.country.world_instance_id:
            self.country._record_event(event_type, payload)

    def validate(self) -> dict[str, Any]:
        failures: list[str] = []
        seen: set[str] = set()
        dungeons = 0
        objects = 0
        weapon_family_hits = {"SWORD": 0, "CROSSBOW": 0, "BOW": 0, "WHIP": 0}
        for st in self.country.world["country"]["states"]:
            for b in st["blocks"]:
                for d in b.get("dungeons", []):
                    dungeons += 1
                    families = {o.get("weapon_family") for o in d.get("objects", []) if o["object_type"] == "GROUND_WEAPON"}
                    if not {"SWORD", "CROSSBOW", "BOW", "WHIP"}.issubset(families):
                        failures.append("DUNGEON_WEAPON_FAMILIES:" + d["id"])
                    if d["darkness_level"] >= 60 and not any(o["object_type"] == "TORCH" for o in d["objects"]):
                        failures.append("DARK_DUNGEON_NO_TORCH:" + d["id"])
                    for fam in families:
                        if fam in weapon_family_hits:
                            weapon_family_hits[fam] += 1
                for _, _, _, obj in self._objects_in_block(b):
                    objects += 1
                    oid = obj["id"]
                    if oid in seen:
                        failures.append("DUP_OBJECT_ID:" + oid)
                    seen.add(oid)
                    if obj.get("object_type") not in SCENE_TYPES:
                        failures.append("UNKNOWN_OBJECT_TYPE:" + oid)
                    if not obj.get("name"):
                        failures.append("UNNAMED_OBJECT:" + oid)
                    if obj.get("object_type") == "GROUND_WEAPON":
                        if obj.get("item_ref") not in DUNGEON_WEAPON_BY_REF:
                            failures.append("UNKNOWN_GROUND_WEAPON:" + oid)
                        if not 0 < int(obj.get("durability", 0)) <= int(obj.get("durability_max", 0)):
                            failures.append("WEAPON_DURABILITY_RANGE:" + oid)
                    if int(obj.get("quantity", 1) or 0) < 0:
                        failures.append("NEG_SCENE_QUANTITY:" + oid)
        # At least one dungeon is guaranteed at country level for this feature-complete pilot.
        if dungeons == 0:
            failures.append("NO_DUNGEONS")
        if any(v == 0 for v in weapon_family_hits.values()):
            failures.append("COUNTRY_DUNGEON_WEAPON_FAMILY_MISSING")
        return {
            "status": "PASS" if not failures else "FAIL",
            "failures": failures,
            "dungeons": dungeons,
            "objects": objects,
            "weapon_family_hits": weapon_family_hits,
        }

    def _objects_in_block(self, b: dict[str, Any]):
        for obj in b.get("scene_objects", []):
            yield b, None, None, obj
        for c in b.get("cities", []):
            for obj in c.get("scene_objects", []):
                yield b, c, None, obj
        for d in b.get("dungeons", []):
            for obj in d.get("objects", []):
                yield b, None, d, obj
