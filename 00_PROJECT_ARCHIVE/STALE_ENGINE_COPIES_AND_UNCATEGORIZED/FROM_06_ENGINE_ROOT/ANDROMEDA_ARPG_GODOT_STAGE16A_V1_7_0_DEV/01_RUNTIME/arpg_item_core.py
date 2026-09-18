from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any

from living_runtime import (
    ValidationError, ConflictError, IntegrityError, NotFoundError,
    canonical_json, sha256_text,
)


RARITY_TIERS: dict[str, dict[str, Any]] = {
    "COMMON": {"display": "Comum", "affix_count": 0, "socket_cap": 0},
    "ATTUNED": {"display": "Sintonizado", "affix_count": 1, "socket_cap": 1},
    "EXCEPTIONAL": {"display": "Excepcional", "affix_count": 2, "socket_cap": 1},
    "RELIC": {"display": "Relíquia", "affix_count": 3, "socket_cap": 2},
    "SINGULAR": {"display": "Singular", "affix_count": 0, "socket_cap": 3},
}

# These labels and numeric ranges are gameplay derivations, not canonical lore.
AFFIX_POOL: tuple[dict[str, Any], ...] = (
    {"id": "AFF-DAMAGE", "label": "Impacto", "stat": "damage_flat", "min": 2.0, "max": 7.0, "kinds": ("WEAPON",)},
    {"id": "AFF-ACCURACY", "label": "Precisão", "stat": "accuracy_flat", "min": 4.0, "max": 14.0, "kinds": ("WEAPON",)},
    {"id": "AFF-CRIT", "label": "Abertura", "stat": "crit_chance_pct", "min": 1.0, "max": 4.0, "kinds": ("WEAPON",)},
    {"id": "AFF-SPEED", "label": "Celeridade", "stat": "attack_speed_pct", "min": 2.0, "max": 8.0, "kinds": ("WEAPON",)},
    {"id": "AFF-ARMOR", "label": "Guarda", "stat": "armor_flat", "min": 4.0, "max": 14.0, "kinds": ("ARMOR",)},
    {"id": "AFF-EVASION", "label": "Desvio", "stat": "evasion_flat", "min": 4.0, "max": 12.0, "kinds": ("ARMOR",)},
    {"id": "AFF-FIRE-RES", "label": "Resguardo Ígneo", "stat": "resistance:FIRE", "min": 4.0, "max": 14.0, "kinds": ("WEAPON", "ARMOR")},
    {"id": "AFF-COLD-RES", "label": "Resguardo Frio", "stat": "resistance:COLD", "min": 4.0, "max": 14.0, "kinds": ("WEAPON", "ARMOR")},
    {"id": "AFF-LIGHTNING-RES", "label": "Resguardo Elétrico", "stat": "resistance:LIGHTNING", "min": 4.0, "max": 14.0, "kinds": ("WEAPON", "ARMOR")},
    {"id": "AFF-TOXIC-RES", "label": "Resguardo Tóxico", "stat": "resistance:TOXIC", "min": 4.0, "max": 14.0, "kinds": ("WEAPON", "ARMOR")},
    {"id": "AFF-ARCANE-RES", "label": "Resguardo Arcano", "stat": "resistance:ARCANE", "min": 4.0, "max": 14.0, "kinds": ("WEAPON", "ARMOR")},
)

CONSUMABLE_EFFECTS: dict[str, dict[str, Any]] = {
    # The source identities already exist in the author-authorized DEV catalog.
    # The numeric effects below are Stage05 gameplay balance only.
    "ITEM-FOOD": {"health_restore": 35.0, "resource_restore": 0.0, "cooldown_group": "CONSUMABLE_RECOVERY", "cooldown_s": 1.0},
    "ITEM-WATER": {"health_restore": 0.0, "resource_restore": 20.0, "cooldown_group": "CONSUMABLE_RECOVERY", "cooldown_s": 0.75},
    "ITEM-HERB": {"health_restore": 50.0, "resource_restore": 0.0, "cooldown_group": "CONSUMABLE_RECOVERY", "cooldown_s": 1.0},
    "ITEM-MANA-CRYSTAL": {"health_restore": 0.0, "resource_restore": 60.0, "cooldown_group": "CONSUMABLE_RECOVERY", "cooldown_s": 1.0},
    "ITEM-FRUIT": {"health_restore": 20.0, "resource_restore": 0.0, "cooldown_group": "CONSUMABLE_RECOVERY", "cooldown_s": 0.75},
}


class ARPGItemCore:
    """Stage05 universal itemization and inventory authority.

    Canon supplies item identity where it exists. Rarity, quality, affixes, item instances,
    weight, stack behavior, equipment slots and numeric bonuses are gameplay-derived runtime
    data. This core is owner-generic so player and future NPC work/gathering can use the same
    inventory contract rather than parallel systems.
    """

    VERSION = "V0.6.0"
    STAGE = "05/20"
    AUTHORITY = "ARPG_ITEMIZATION_GAMEPLAY_DERIVATION"
    MAX_QUANTITY = 1_000_000_000
    DEFAULT_SLOT_CAPACITY = 60
    DEFAULT_WEIGHT_CAPACITY = 100.0
    MAX_SLOT_CAPACITY = 1000
    MAX_WEIGHT_CAPACITY = 100000.0
    EQUIPMENT_SLOTS = ("MAIN_HAND", "OFF_HAND", "HEAD", "CHEST", "HANDS", "LEGS", "FEET", "NECK", "RING_LEFT", "RING_RIGHT", "UTILITY")

    def __init__(self, engine: Any, world_instance_id: str) -> None:
        self.engine = engine
        self.runtime = engine.runtime
        self.world_instance_id = world_instance_id
        self._init_schema()
        self.bootstrap_definitions()
        self.bootstrap_existing_profiles()

    def _init_schema(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS arpg_item_definitions(
                    item_ref TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    source_authority TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS arpg_item_inventories(
                    world_instance_id TEXT NOT NULL,
                    owner_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, owner_ref)
                );
                CREATE TABLE IF NOT EXISTS arpg_item_instances(
                    instance_ref TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL,
                    owner_ref TEXT NOT NULL,
                    item_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_arpg_item_instances_owner
                    ON arpg_item_instances(world_instance_id, owner_ref, item_ref);
                CREATE TABLE IF NOT EXISTS arpg_item_events(
                    server_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    world_instance_id TEXT NOT NULL,
                    owner_ref TEXT NOT NULL,
                    event_ref TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id, event_ref)
                );
                CREATE INDEX IF NOT EXISTS idx_arpg_item_events_owner
                    ON arpg_item_events(world_instance_id, owner_ref, server_sequence);
                CREATE TRIGGER IF NOT EXISTS arpg_item_definition_no_update
                    BEFORE UPDATE ON arpg_item_definitions BEGIN SELECT RAISE(ABORT,'ARPG item definition immutable'); END;
                CREATE TRIGGER IF NOT EXISTS arpg_item_definition_no_delete
                    BEFORE DELETE ON arpg_item_definitions BEGIN SELECT RAISE(ABORT,'ARPG item definition immutable'); END;
                """
            )
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('arpg_item_core_version',?)",
                (self.VERSION,),
            )

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> tuple[str, str]:
        text = canonical_json(payload)
        return text, sha256_text(text)

    @staticmethod
    def _stable_float(seed: str, channel: str) -> float:
        digest = hashlib.sha256(f"{seed}|{channel}".encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") / float(2**64 - 1)

    @staticmethod
    def _stable_instance_ref(world_instance_id: str, event_ref: str, index: int) -> str:
        h = hashlib.sha256(f"{world_instance_id}|{event_ref}|{index}".encode("utf-8")).hexdigest()[:28]
        return "itm:" + h

    @staticmethod
    def _classify(ref: str, source: dict[str, Any]) -> str:
        if ref.startswith("WPN-"):
            return "WEAPON"
        if ref == "ITEM-ARMOR":
            return "ARMOR"
        if ref == "ITEM-TOOL":
            return "TOOL"
        if ref in CONSUMABLE_EFFECTS:
            return "CONSUMABLE"
        if ref.startswith("MIN-") or ref.startswith("ITEM-HARVEST-") or ref.startswith("ITEM-FAUNA-"):
            return "MATERIAL"
        if ref in {"ITEM-CIRCUIT", "ITEM-SENSOR", "ITEM-SERVO", "ITEM-ACTUATOR", "ITEM-ENERGY-CELL", "ITEM-RUNE-DUST"}:
            return "COMPONENT"
        if ref in {"ITEM-GRAIN"}:
            return "MATERIAL"
        if ref == "ITEM-OLD-KEY":
            return "QUEST_UTILITY"
        if ref == "ITEM-TORCH":
            return "UTILITY"
        return "GENERIC"

    @staticmethod
    def _weight_for(kind: str) -> float:
        return {
            "WEAPON": 4.0, "ARMOR": 7.0, "TOOL": 3.0, "CONSUMABLE": 0.3,
            "MATERIAL": 0.5, "COMPONENT": 0.6, "QUEST_UTILITY": 0.2,
            "UTILITY": 1.0, "GENERIC": 1.0,
        }.get(kind, 1.0)

    @staticmethod
    def _stack_max_for(kind: str) -> int:
        if kind == "CONSUMABLE": return 50
        if kind in {"MATERIAL", "COMPONENT"}: return 999
        if kind in {"QUEST_UTILITY", "UTILITY", "GENERIC"}: return 20
        return 1

    @staticmethod
    def _equip_slots_for(kind: str) -> list[str]:
        if kind == "WEAPON": return ["MAIN_HAND"]
        if kind == "ARMOR": return ["CHEST"]
        if kind == "TOOL": return ["UTILITY"]
        return []

    @staticmethod
    def _reach_bonus(reach: Any) -> float:
        key = str(reach or "").upper().replace("É", "E")
        if key in {"LONGO", "ALTO"}: return 2.25
        if key in {"MEDIO", "MÉDIO"}: return 0.90
        if key in {"CURTO", "BAIXO"}: return 0.20
        return 0.0

    def _base_modifiers(self, kind: str, source: dict[str, Any]) -> dict[str, Any]:
        mods: dict[str, Any] = {
            "damage_flat": 0.0, "damage_pct": 0.0, "armor_flat": 0.0,
            "accuracy_flat": 0.0, "evasion_flat": 0.0, "crit_chance_pct": 0.0,
            "attack_speed_pct": 0.0, "range_bonus_m": 0.0,
            "resistances": {"FIRE": 0.0, "COLD": 0.0, "LIGHTNING": 0.0, "TOXIC": 0.0, "ARCANE": 0.0},
        }
        perf = source.get("performance") or {}
        if kind == "WEAPON":
            control = float(perf.get("control", 5) or 0)
            stability = float(perf.get("stability", 5) or 0)
            mobility = float(perf.get("mobility", 5) or 0)
            mods["damage_flat"] = round(1.0 + stability * 0.70 + control * 0.25, 6)
            mods["accuracy_flat"] = round(control * 1.20, 6)
            mods["attack_speed_pct"] = round((mobility - 5.0) * 2.0, 6)
            mods["range_bonus_m"] = self._reach_bonus(perf.get("reach"))
        elif kind == "ARMOR":
            mods["armor_flat"] = 12.0
        return mods

    def _definition_from_source(self, item_ref: str, source_kind: str, source: dict[str, Any]) -> dict[str, Any]:
        kind = self._classify(item_ref, source)
        status = str(source.get("canonical_status") or "").upper()
        canonical = "CÂNONE" in status or "CANON" in status and "NOT_CANON" not in status
        perf = source.get("performance") or {}
        durability_score = float(perf.get("durability", 5) or 5)
        base_durability = 0.0
        if kind in {"WEAPON", "ARMOR", "TOOL"}:
            base_durability = round(40.0 + max(0.0, min(10.0, durability_score)) * 12.0, 6)
        stack_max = self._stack_max_for(kind)
        return {
            "item_ref": item_ref,
            "name": source.get("name") or item_ref,
            "item_kind": kind,
            "source_kind": source_kind,
            "canonical_identity": bool(canonical),
            "canonical_status": source.get("canonical_status"),
            "source_authority": "MASTER_READ_ONLY" if canonical else "GAMEPLAY_DERIVED_DEV_SOURCE",
            "source_category": source.get("category"),
            "stackable": stack_max > 1,
            "stack_max": stack_max,
            "unit_weight": self._weight_for(kind),
            "equip_slots": self._equip_slots_for(kind),
            "instance_policy": "UNIQUE_INSTANCE" if kind in {"WEAPON", "ARMOR", "TOOL"} else "STACK",
            "base_durability": base_durability,
            "quality_policy": "INSTANCE_1_100_GAMEPLAY_DERIVED" if kind in {"WEAPON", "ARMOR", "TOOL"} else "NOT_APPLICABLE",
            "rarity_policy": "INSTANCE_ROLL_GAMEPLAY_DERIVED" if kind in {"WEAPON", "ARMOR", "TOOL"} else "COMMON_STACK",
            "rarity_display_names_authority": "GAMEPLAY_DERIVED_RENAMEABLE",
            "base_modifiers": self._base_modifiers(kind, source),
            "consumable_effect": copy.deepcopy(CONSUMABLE_EFFECTS.get(item_ref)),
            "socket_support": {
                "supported": kind in {"WEAPON", "ARMOR", "TOOL"},
                "capacity_by_rarity": {k: int(v["socket_cap"]) for k, v in RARITY_TIERS.items()},
                "augmentation_binding": "DEFERRED_TO_RUNE_SKILL_WORK_INTEGRATION",
            },
            "source_snapshot_hash": sha256_text(canonical_json(source)),
            "art_dependency": "NONE_PLACEHOLDER_READY",
            "authority": self.AUTHORITY,
        }

    def bootstrap_definitions(self) -> dict[str, Any]:
        rows = self.runtime.conn.execute(
            "SELECT item_ref,item_kind,payload_json,payload_hash FROM commerce_catalog_snapshots ORDER BY item_ref"
        ).fetchall()
        inserted = 0
        with self.runtime._write_lock:
            for row in rows:
                if sha256_text(row["payload_json"]) != row["payload_hash"]:
                    raise IntegrityError("commerce catalog hash mismatch during item bootstrap")
                source = json.loads(row["payload_json"])
                definition = self._definition_from_source(row["item_ref"], row["item_kind"], source)
                text, h = self._hash_payload(definition)
                existing = self.runtime.conn.execute(
                    "SELECT payload_hash FROM arpg_item_definitions WHERE item_ref=?", (row["item_ref"],)
                ).fetchone()
                if existing:
                    if existing["payload_hash"] != h:
                        raise IntegrityError("ARPG item definition drift:" + row["item_ref"])
                    continue
                self.runtime.conn.execute(
                    "INSERT INTO arpg_item_definitions VALUES(?,?,?,?,?)",
                    (row["item_ref"], row["item_kind"], definition["source_authority"], text, h),
                )
                inserted += 1
        return {"status": "PASS", "inserted": inserted, "definitions": len(rows)}

    def definition(self, item_ref: str) -> dict[str, Any]:
        row = self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_item_definitions WHERE item_ref=?", (str(item_ref),)
        ).fetchone()
        if not row:
            raise NotFoundError("ARPG item definition not found:" + str(item_ref))
        if sha256_text(row["payload_json"]) != row["payload_hash"]:
            raise IntegrityError("ARPG item definition hash mismatch")
        return json.loads(row["payload_json"])

    def list_definitions(self) -> list[dict[str, Any]]:
        rows = self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_item_definitions ORDER BY item_ref"
        ).fetchall()
        out = []
        for row in rows:
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                raise IntegrityError("ARPG item definition hash mismatch")
            out.append(json.loads(row["payload_json"]))
        return out

    def _owner_kind(self, owner_ref: str) -> str:
        prow = self.runtime.conn.execute(
            "SELECT 1 FROM arpg_player_profiles WHERE world_instance_id=? AND profile_ref=?",
            (self.world_instance_id, owner_ref),
        ).fetchone()
        if prow:
            return "PLAYER_PROFILE"
        if owner_ref.startswith("rt:"):
            self.runtime.get_entity(self.world_instance_id, owner_ref)
            return "RUNTIME_ENTITY"
        if owner_ref.startswith("BAG-S16A-"):
            return "STAGE16A_BAG_CONTAINER"
        if owner_ref.startswith("DROP-S16A-HOLD-"):
            return "STAGE16A_GROUND_LOOT_HOLD"
        if owner_ref.startswith("VEH-"):
            row = self.runtime.conn.execute(
                "SELECT 1 FROM arpg_vehicle_instances WHERE world_instance_id=? AND vehicle_ref=?",
                (self.world_instance_id, owner_ref),
            ).fetchone()
            if row:
                return "VEHICLE_CARGO"
        if owner_ref.startswith("MACH-"):
            try:
                row = self.runtime.conn.execute(
                    "SELECT 1 FROM arpg_machine_instances WHERE world_instance_id=? AND machine_ref=?",
                    (self.world_instance_id, owner_ref),
                ).fetchone()
                if row:
                    return "MACHINE_STORAGE"
            except Exception:
                pass
        if owner_ref.startswith("RBT-"):
            try:
                row = self.runtime.conn.execute(
                    "SELECT 1 FROM arpg_robot_instances WHERE world_instance_id=? AND robot_ref=?",
                    (self.world_instance_id, owner_ref),
                ).fetchone()
                if row:
                    return "ROBOT_CARGO"
            except Exception:
                pass
        if owner_ref.startswith("SHOP-S13-"):
            try:
                row = self.runtime.conn.execute(
                    "SELECT 1 FROM arpg_economy_vendors WHERE world_instance_id=? AND vendor_ref=?",
                    (self.world_instance_id, owner_ref),
                ).fetchone()
                if row:
                    return "ECONOMY_VENDOR_STOCK"
            except Exception:
                pass
        if owner_ref.startswith("STASH-S13-"):
            try:
                row = self.runtime.conn.execute(
                    "SELECT 1 FROM arpg_economy_stashes WHERE world_instance_id=? AND stash_ref=?",
                    (self.world_instance_id, owner_ref),
                ).fetchone()
                if row:
                    return "PLAYER_STASH"
            except Exception:
                pass
        # Country NPC ids are valid shared-work owners later, but no job semantics are activated here.
        try:
            self.engine.country(self.world_instance_id).npc(owner_ref)
            return "COUNTRY_NPC"
        except Exception:
            raise ValidationError("unknown item inventory owner")

    def _initial_inventory(self, owner_ref: str, owner_kind: str, slot_capacity: int, weight_capacity: float) -> dict[str, Any]:
        return {
            "owner_ref": owner_ref,
            "owner_kind": owner_kind,
            "slot_capacity": int(slot_capacity),
            "weight_capacity": round(float(weight_capacity), 6),
            "capacity_policy": "SLOT_AND_WEIGHT_GAMEPLAY_DERIVED_V0_6",
            "stacks": {},
            "instance_refs": [],
            "equipped": {slot: None for slot in self.EQUIPMENT_SLOTS},
            "shared_owner_contract": "PLAYER_AND_NPC_COMPATIBLE_STAGE09",
            "legacy_commerce_inventory": "COMPATIBILITY_PROJECTION_NOT_REPLACED_STAGE05",
            "authority": self.AUTHORITY,
        }

    def _inventory_row(self, owner_ref: str):
        return self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_item_inventories WHERE world_instance_id=? AND owner_ref=?",
            (self.world_instance_id, owner_ref),
        ).fetchone()

    def _save_inventory(self, inv: dict[str, Any]) -> None:
        text, h = self._hash_payload(inv)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO arpg_item_inventories VALUES(?,?,?,?)",
                (self.world_instance_id, inv["owner_ref"], text, h),
            )

    def ensure_inventory(self, owner_ref: str, *, slot_capacity: int | None = None, weight_capacity: float | None = None) -> dict[str, Any]:
        owner_ref = str(owner_ref).strip()
        if not owner_ref or len(owner_ref) > 180:
            raise ValidationError("invalid inventory owner_ref")
        row = self._inventory_row(owner_ref)
        if row:
            return self.inventory_snapshot(owner_ref)
        owner_kind = self._owner_kind(owner_ref)
        sc = self.DEFAULT_SLOT_CAPACITY if slot_capacity is None else int(slot_capacity)
        wc = self.DEFAULT_WEIGHT_CAPACITY if weight_capacity is None else float(weight_capacity)
        if isinstance(sc, bool) or not (1 <= sc <= self.MAX_SLOT_CAPACITY):
            raise ValidationError("slot_capacity out of range")
        if not math.isfinite(wc) or not (0.1 <= wc <= self.MAX_WEIGHT_CAPACITY):
            raise ValidationError("weight_capacity out of range")
        inv = self._initial_inventory(owner_ref, owner_kind, sc, wc)
        self._save_inventory(inv)
        return self.inventory_snapshot(owner_ref)

    def bootstrap_existing_profiles(self) -> None:
        try:
            profiles = self.engine.arpg(self.world_instance_id).list_profiles()
        except Exception:
            return
        for profile in profiles:
            if not self._inventory_row(profile["profile_ref"]):
                inv = self._initial_inventory(profile["profile_ref"], "PLAYER_PROFILE", self.DEFAULT_SLOT_CAPACITY, self.DEFAULT_WEIGHT_CAPACITY)
                self._save_inventory(inv)

    def _load_inventory(self, owner_ref: str) -> dict[str, Any]:
        row = self._inventory_row(owner_ref)
        if not row:
            raise KeyError(owner_ref)
        if sha256_text(row["payload_json"]) != row["payload_hash"]:
            raise IntegrityError("ARPG inventory hash mismatch")
        return json.loads(row["payload_json"])

    def instance(self, instance_ref: str) -> dict[str, Any]:
        row = self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_item_instances WHERE world_instance_id=? AND instance_ref=?",
            (self.world_instance_id, str(instance_ref)),
        ).fetchone()
        if not row:
            raise NotFoundError("ARPG item instance not found:" + str(instance_ref))
        if sha256_text(row["payload_json"]) != row["payload_hash"]:
            raise IntegrityError("ARPG item instance hash mismatch")
        return json.loads(row["payload_json"])

    def _save_instance(self, inst: dict[str, Any]) -> None:
        text, h = self._hash_payload(inst)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO arpg_item_instances VALUES(?,?,?,?,?,?)",
                (inst["instance_ref"], self.world_instance_id, inst["owner_ref"], inst["item_ref"], text, h),
            )

    def _delete_instance(self, instance_ref: str) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "DELETE FROM arpg_item_instances WHERE world_instance_id=? AND instance_ref=?",
                (self.world_instance_id, instance_ref),
            )

    def _inventory_metrics(self, inv: dict[str, Any]) -> dict[str, Any]:
        slots = 0
        weight = 0.0
        for item_ref, qty in inv.get("stacks", {}).items():
            d = self.definition(item_ref)
            qty = int(qty)
            if qty <= 0:
                continue
            slots += int(math.ceil(qty / max(1, int(d["stack_max"]))))
            weight += float(d["unit_weight"]) * qty
        for iref in inv.get("instance_refs", []):
            inst = self.instance(iref)
            d = self.definition(inst["item_ref"])
            slots += 1
            weight += float(d["unit_weight"])
        return {
            "used_slots": slots,
            "free_slots": int(inv["slot_capacity"]) - slots,
            "current_weight": round(weight, 6),
            "free_weight": round(float(inv["weight_capacity"]) - weight, 6),
        }

    def inventory_snapshot(self, owner_ref: str) -> dict[str, Any]:
        inv = self._load_inventory(owner_ref)
        out = copy.deepcopy(inv)
        out["metrics"] = self._inventory_metrics(inv)
        out["instances"] = [self.instance(x) for x in inv.get("instance_refs", [])]
        out["definition_count"] = self.runtime.conn.execute("SELECT COUNT(*) c FROM arpg_item_definitions").fetchone()["c"]
        return out

    def _event_existing(self, event_ref: str):
        return self.runtime.conn.execute(
            "SELECT * FROM arpg_item_events WHERE world_instance_id=? AND event_ref=?",
            (self.world_instance_id, event_ref),
        ).fetchone()

    def _event_hash(self, owner_ref: str, event_ref: str, event_type: str, payload: dict[str, Any]) -> str:
        return sha256_text(canonical_json({"owner_ref": owner_ref, "event_ref": event_ref, "event_type": event_type, "payload": payload}))

    def _existing_or_none(self, owner_ref: str, event_ref: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        event_ref = str(event_ref).strip()
        if not event_ref or len(event_ref) > 180:
            raise ValidationError("event_ref must contain 1-180 characters")
        row = self._event_existing(event_ref)
        if not row:
            return None
        h = self._event_hash(owner_ref, event_ref, event_type, payload)
        if row["event_hash"] != h or row["owner_ref"] != owner_ref or row["event_type"] != event_type:
            raise ConflictError("ITEM_EVENT_REF_CONFLICT")
        out = json.loads(row["result_json"])
        out["idempotent_replay"] = True
        out["item_server_sequence"] = row["server_sequence"]
        return out

    def _record_event(self, owner_ref: str, event_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        h = self._event_hash(owner_ref, event_ref, event_type, payload)
        with self.runtime._write_lock:
            cur = self.runtime.conn.execute(
                "INSERT INTO arpg_item_events(world_instance_id,owner_ref,event_ref,event_type,payload_json,result_json,event_hash) VALUES(?,?,?,?,?,?,?)",
                (self.world_instance_id, owner_ref, event_ref, event_type, canonical_json(payload), canonical_json(result), h),
            )
            seq = cur.lastrowid
        out = copy.deepcopy(result)
        out["item_server_sequence"] = seq
        return out

    def _reject(self, owner_ref: str, event_ref: str, event_type: str, payload: dict[str, Any], reason: str, **extra: Any) -> dict[str, Any]:
        return self._record_event(owner_ref, event_ref, event_type, payload, {"status": "REJECTED", "reason": reason, "idempotent_replay": False, **extra})

    def _roll_rarity(self, seed: str) -> str:
        roll = self._stable_float(seed, "RARITY") * 100.0
        if roll < 70.0: return "COMMON"
        if roll < 90.0: return "ATTUNED"
        if roll < 98.0: return "EXCEPTIONAL"
        return "RELIC"

    def _roll_affixes(self, item_kind: str, rarity: str, seed: str) -> list[dict[str, Any]]:
        count = int(RARITY_TIERS[rarity]["affix_count"])
        pool = [x for x in AFFIX_POOL if item_kind in x["kinds"]]
        if count <= 0 or not pool:
            return []
        ranked = sorted(pool, key=lambda a: self._stable_float(seed, "AFFIX_ORDER:" + a["id"]))
        out = []
        for aff in ranked[:min(count, len(ranked))]:
            r = self._stable_float(seed, "AFFIX_VALUE:" + aff["id"])
            value = float(aff["min"]) + (float(aff["max"]) - float(aff["min"])) * r
            out.append({"affix_ref": aff["id"], "label": aff["label"], "stat": aff["stat"], "value": round(value, 6), "authority": "GAMEPLAY_DERIVED"})
        return out

    def _new_instance(self, owner_ref: str, item_ref: str, event_ref: str, index: int, *, rarity: str | None = None, quality: int | None = None) -> dict[str, Any]:
        definition = self.definition(item_ref)
        if definition["instance_policy"] != "UNIQUE_INSTANCE":
            raise ValidationError("stack item cannot create unique instance")
        seed = f"{self.world_instance_id}|{event_ref}|{item_ref}|{index}"
        rarity = str(rarity or self._roll_rarity(seed)).upper()
        if rarity not in RARITY_TIERS:
            raise ValidationError("unknown rarity tier")
        if rarity == "SINGULAR":
            raise ValidationError("SINGULAR rarity requires authored unique definition; automatic generation blocked")
        if quality is None:
            quality = 50 + int(self._stable_float(seed, "QUALITY") * 51.0)
        if isinstance(quality, bool) or not isinstance(quality, int) or not (1 <= quality <= 100):
            raise ValidationError("quality must be integer 1-100")
        base_dur = float(definition["base_durability"])
        quality_factor = 0.75 + float(quality) / 200.0
        max_dur = round(base_dur * quality_factor, 6)
        socket_capacity = int(RARITY_TIERS[rarity]["socket_cap"]) if definition["socket_support"]["supported"] else 0
        return {
            "instance_ref": self._stable_instance_ref(self.world_instance_id, event_ref, index),
            "item_ref": item_ref,
            "owner_ref": owner_ref,
            "rarity": rarity,
            "rarity_display": RARITY_TIERS[rarity]["display"],
            "quality": quality,
            "durability": max_dur,
            "max_durability": max_dur,
            "condition": "INTACT",
            "affixes": self._roll_affixes(definition["item_kind"], rarity, seed),
            "socket_capacity": socket_capacity,
            "sockets": [None for _ in range(socket_capacity)],
            "socket_binding": "EMPTY_SOCKET_FRAMEWORK_STAGE05",
            "authority": self.AUTHORITY,
        }

    def _fits(self, inv: dict[str, Any], *, item_ref: str, quantity: int, instances_to_add: int = 0) -> tuple[bool, dict[str, Any]]:
        before = self._inventory_metrics(inv)
        d = self.definition(item_ref)
        stacks = copy.deepcopy(inv.get("stacks", {}))
        if d["stackable"]:
            stacks[item_ref] = int(stacks.get(item_ref, 0)) + int(quantity)
        simulated = copy.deepcopy(inv)
        simulated["stacks"] = stacks
        # For unique items weight/slots are added directly because instances are not saved yet.
        after = self._inventory_metrics(simulated)
        if instances_to_add:
            after["used_slots"] += instances_to_add
            after["free_slots"] -= instances_to_add
            after["current_weight"] = round(after["current_weight"] + float(d["unit_weight"]) * instances_to_add, 6)
            after["free_weight"] = round(after["free_weight"] - float(d["unit_weight"]) * instances_to_add, 6)
        ok = after["used_slots"] <= int(inv["slot_capacity"]) and after["current_weight"] <= float(inv["weight_capacity"]) + 1e-9
        return ok, {"before": before, "after": after}

    def grant_item(self, owner_ref: str, item_ref: str, quantity: int, *, event_ref: str, rarity: str | None = None, quality: int | None = None) -> dict[str, Any]:
        owner_ref = str(owner_ref).strip(); item_ref = str(item_ref).strip()
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not (1 <= quantity <= self.MAX_QUANTITY):
            raise ValidationError("quantity out of range")
        definition = self.definition(item_ref)
        payload = {"item_ref": item_ref, "quantity": quantity, "rarity": rarity, "quality": quality}
        existing = self._existing_or_none(owner_ref, event_ref, "ITEM_GRANT", payload)
        if existing is not None:
            return existing
        self.ensure_inventory(owner_ref)
        inv = self._load_inventory(owner_ref)
        if definition["stackable"]:
            ok, metrics = self._fits(inv, item_ref=item_ref, quantity=quantity)
            if not ok:
                return self._reject(owner_ref, event_ref, "ITEM_GRANT", payload, "INVENTORY_CAPACITY_EXCEEDED", metrics=metrics)
            before = int(inv["stacks"].get(item_ref, 0))
            inv["stacks"][item_ref] = before + quantity
            self._save_inventory(inv)
            return self._record_event(owner_ref, event_ref, "ITEM_GRANT", payload, {
                "status": "PASS", "item_ref": item_ref, "stackable": True, "before": before,
                "after": before + quantity, "granted": quantity, "instance_refs": [], "idempotent_replay": False,
            })
        if quantity > 50:
            raise ValidationError("unique instance grant limited to 50 per event")
        ok, metrics = self._fits(inv, item_ref=item_ref, quantity=0, instances_to_add=quantity)
        if not ok:
            return self._reject(owner_ref, event_ref, "ITEM_GRANT", payload, "INVENTORY_CAPACITY_EXCEEDED", metrics=metrics)
        created = [self._new_instance(owner_ref, item_ref, event_ref, i, rarity=rarity, quality=quality) for i in range(quantity)]
        for inst in created:
            if self.runtime.conn.execute("SELECT 1 FROM arpg_item_instances WHERE instance_ref=?", (inst["instance_ref"],)).fetchone():
                raise ConflictError("ITEM_INSTANCE_REF_COLLISION")
            self._save_instance(inst)
            inv["instance_refs"].append(inst["instance_ref"])
        self._save_inventory(inv)
        return self._record_event(owner_ref, event_ref, "ITEM_GRANT", payload, {
            "status": "PASS", "item_ref": item_ref, "stackable": False, "granted": quantity,
            "instance_refs": [x["instance_ref"] for x in created], "instances": created, "idempotent_replay": False,
        })

    def remove_item(self, owner_ref: str, item_ref: str, quantity: int, *, event_ref: str, instance_ref: str | None = None) -> dict[str, Any]:
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise ValidationError("quantity must be positive integer")
        d = self.definition(item_ref)
        payload = {"item_ref": item_ref, "quantity": quantity, "instance_ref": instance_ref}
        existing = self._existing_or_none(owner_ref, event_ref, "ITEM_REMOVE", payload)
        if existing is not None: return existing
        inv = self._load_inventory(owner_ref)
        if d["stackable"]:
            before = int(inv["stacks"].get(item_ref, 0))
            if before < quantity:
                return self._reject(owner_ref, event_ref, "ITEM_REMOVE", payload, "INSUFFICIENT_ITEM_QUANTITY", available=before)
            after = before - quantity
            if after: inv["stacks"][item_ref] = after
            else: inv["stacks"].pop(item_ref, None)
            self._save_inventory(inv)
            return self._record_event(owner_ref, event_ref, "ITEM_REMOVE", payload, {"status": "PASS", "item_ref": item_ref, "removed": quantity, "remaining": after, "idempotent_replay": False})
        if quantity != 1 or not instance_ref:
            raise ValidationError("unique item removal requires quantity=1 and instance_ref")
        if instance_ref not in inv.get("instance_refs", []):
            return self._reject(owner_ref, event_ref, "ITEM_REMOVE", payload, "ITEM_INSTANCE_NOT_OWNED")
        inst = self.instance(instance_ref)
        if inst["item_ref"] != item_ref:
            raise ConflictError("ITEM_INSTANCE_DEFINITION_MISMATCH")
        if instance_ref in inv.get("equipped", {}).values():
            return self._reject(owner_ref, event_ref, "ITEM_REMOVE", payload, "ITEM_INSTANCE_EQUIPPED")
        inv["instance_refs"].remove(instance_ref); self._save_inventory(inv); self._delete_instance(instance_ref)
        return self._record_event(owner_ref, event_ref, "ITEM_REMOVE", payload, {"status": "PASS", "item_ref": item_ref, "removed": 1, "instance_ref": instance_ref, "idempotent_replay": False})

    def transfer_item(self, source_owner_ref: str, dest_owner_ref: str, item_ref: str, quantity: int, *, event_ref: str, instance_ref: str | None = None) -> dict[str, Any]:
        source_owner_ref = str(source_owner_ref); dest_owner_ref = str(dest_owner_ref)
        if source_owner_ref == dest_owner_ref:
            raise ValidationError("source and destination owner must differ")
        d = self.definition(item_ref)
        payload = {"dest_owner_ref": dest_owner_ref, "item_ref": item_ref, "quantity": quantity, "instance_ref": instance_ref}
        existing = self._existing_or_none(source_owner_ref, event_ref, "ITEM_TRANSFER", payload)
        if existing is not None: return existing
        self.ensure_inventory(source_owner_ref); self.ensure_inventory(dest_owner_ref)
        src = self._load_inventory(source_owner_ref); dst = self._load_inventory(dest_owner_ref)
        if d["stackable"]:
            if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
                raise ValidationError("quantity invalid")
            available = int(src["stacks"].get(item_ref, 0))
            if available < quantity:
                return self._reject(source_owner_ref, event_ref, "ITEM_TRANSFER", payload, "INSUFFICIENT_ITEM_QUANTITY", available=available)
            ok, metrics = self._fits(dst, item_ref=item_ref, quantity=quantity)
            if not ok:
                return self._reject(source_owner_ref, event_ref, "ITEM_TRANSFER", payload, "DESTINATION_CAPACITY_EXCEEDED", metrics=metrics)
            remain = available - quantity
            if remain: src["stacks"][item_ref] = remain
            else: src["stacks"].pop(item_ref, None)
            dst["stacks"][item_ref] = int(dst["stacks"].get(item_ref, 0)) + quantity
        else:
            if quantity != 1 or not instance_ref:
                raise ValidationError("unique transfer requires quantity=1 and instance_ref")
            if instance_ref not in src.get("instance_refs", []):
                return self._reject(source_owner_ref, event_ref, "ITEM_TRANSFER", payload, "ITEM_INSTANCE_NOT_OWNED")
            if instance_ref in src.get("equipped", {}).values():
                return self._reject(source_owner_ref, event_ref, "ITEM_TRANSFER", payload, "ITEM_INSTANCE_EQUIPPED")
            ok, metrics = self._fits(dst, item_ref=item_ref, quantity=0, instances_to_add=1)
            if not ok:
                return self._reject(source_owner_ref, event_ref, "ITEM_TRANSFER", payload, "DESTINATION_CAPACITY_EXCEEDED", metrics=metrics)
            src["instance_refs"].remove(instance_ref); dst["instance_refs"].append(instance_ref)
            inst = self.instance(instance_ref); inst["owner_ref"] = dest_owner_ref; self._save_instance(inst)
        self._save_inventory(src); self._save_inventory(dst)
        return self._record_event(source_owner_ref, event_ref, "ITEM_TRANSFER", payload, {
            "status": "PASS", "source_owner_ref": source_owner_ref, "dest_owner_ref": dest_owner_ref,
            "item_ref": item_ref, "quantity": quantity, "instance_ref": instance_ref, "idempotent_replay": False,
        })

    def equip(self, profile_ref: str, instance_ref: str, slot: str, *, event_ref: str) -> dict[str, Any]:
        slot = str(slot).upper().strip()
        if slot not in self.EQUIPMENT_SLOTS:
            raise ValidationError("unsupported equipment slot")
        self.engine.arpg(self.world_instance_id).profile(profile_ref)
        payload = {"instance_ref": instance_ref, "slot": slot}
        existing = self._existing_or_none(profile_ref, event_ref, "ITEM_EQUIP", payload)
        if existing is not None: return existing
        inv = self._load_inventory(profile_ref)
        if instance_ref not in inv.get("instance_refs", []):
            return self._reject(profile_ref, event_ref, "ITEM_EQUIP", payload, "ITEM_INSTANCE_NOT_OWNED")
        inst = self.instance(instance_ref); d = self.definition(inst["item_ref"])
        if slot not in d.get("equip_slots", []):
            return self._reject(profile_ref, event_ref, "ITEM_EQUIP", payload, "ITEM_SLOT_INCOMPATIBLE", allowed_slots=d.get("equip_slots", []))
        previous_slot = next((s for s, v in inv["equipped"].items() if v == instance_ref), None)
        if previous_slot and previous_slot != slot:
            inv["equipped"][previous_slot] = None
        replaced = inv["equipped"].get(slot)
        inv["equipped"][slot] = instance_ref
        self._save_inventory(inv)
        return self._record_event(profile_ref, event_ref, "ITEM_EQUIP", payload, {
            "status": "PASS", "slot": slot, "instance_ref": instance_ref, "replaced_instance_ref": replaced,
            "condition": inst["condition"], "idempotent_replay": False,
        })

    def unequip(self, profile_ref: str, slot: str, *, event_ref: str) -> dict[str, Any]:
        slot = str(slot).upper().strip()
        if slot not in self.EQUIPMENT_SLOTS: raise ValidationError("unsupported equipment slot")
        payload = {"slot": slot}
        existing = self._existing_or_none(profile_ref, event_ref, "ITEM_UNEQUIP", payload)
        if existing is not None: return existing
        inv = self._load_inventory(profile_ref); ref = inv["equipped"].get(slot)
        if not ref: return self._reject(profile_ref, event_ref, "ITEM_UNEQUIP", payload, "EQUIPMENT_SLOT_EMPTY")
        inv["equipped"][slot] = None; self._save_inventory(inv)
        return self._record_event(profile_ref, event_ref, "ITEM_UNEQUIP", payload, {"status": "PASS", "slot": slot, "instance_ref": ref, "idempotent_replay": False})

    def apply_durability_loss(self, owner_ref: str, instance_ref: str, amount: float, *, event_ref: str) -> dict[str, Any]:
        amount = float(amount)
        if not math.isfinite(amount) or amount <= 0 or amount > 1_000_000:
            raise ValidationError("durability loss out of range")
        payload = {"instance_ref": instance_ref, "amount": round(amount, 6)}
        existing = self._existing_or_none(owner_ref, event_ref, "DURABILITY_LOSS", payload)
        if existing is not None: return existing
        inv = self._load_inventory(owner_ref)
        if instance_ref not in inv.get("instance_refs", []): return self._reject(owner_ref, event_ref, "DURABILITY_LOSS", payload, "ITEM_INSTANCE_NOT_OWNED")
        inst = self.instance(instance_ref); before = float(inst["durability"]); after = max(0.0, before - amount)
        inst["durability"] = round(after, 6); inst["condition"] = "BROKEN" if after <= 1e-9 else ("DAMAGED" if after < float(inst["max_durability"]) * 0.35 else "INTACT")
        self._save_instance(inst)
        return self._record_event(owner_ref, event_ref, "DURABILITY_LOSS", payload, {"status": "PASS", "instance_ref": instance_ref, "before": before, "after": inst["durability"], "condition": inst["condition"], "idempotent_replay": False})

    def repair_instance(self, owner_ref: str, instance_ref: str, *, event_ref: str, repair_authority: str = "SYSTEM_TEST_STAGE05") -> dict[str, Any]:
        payload = {"instance_ref": instance_ref, "repair_authority": repair_authority}
        existing = self._existing_or_none(owner_ref, event_ref, "ITEM_REPAIR", payload)
        if existing is not None: return existing
        inv = self._load_inventory(owner_ref)
        if instance_ref not in inv.get("instance_refs", []): return self._reject(owner_ref, event_ref, "ITEM_REPAIR", payload, "ITEM_INSTANCE_NOT_OWNED")
        inst = self.instance(instance_ref); before = float(inst["durability"])
        inst["durability"] = float(inst["max_durability"]); inst["condition"] = "INTACT"; self._save_instance(inst)
        return self._record_event(owner_ref, event_ref, "ITEM_REPAIR", payload, {"status": "PASS", "instance_ref": instance_ref, "before": before, "after": inst["durability"], "economic_cost": "DEFERRED_STAGE11", "idempotent_replay": False})

    def use_consumable(self, profile_ref: str, item_ref: str, *, event_ref: str) -> dict[str, Any]:
        d = self.definition(item_ref); effect = d.get("consumable_effect")
        if d["item_kind"] != "CONSUMABLE" or not effect:
            raise ValidationError("item is not a Stage05 consumable")
        payload = {"item_ref": item_ref}
        existing = self._existing_or_none(profile_ref, event_ref, "ITEM_USE", payload)
        if existing is not None: return existing
        gate = self.engine.character(self.world_instance_id).can_act(profile_ref)
        if gate.get("status") != "PASS": return self._reject(profile_ref, event_ref, "ITEM_USE", payload, gate.get("reason", "CHARACTER_CANNOT_ACT"))
        inv = self._load_inventory(profile_ref); qty = int(inv["stacks"].get(item_ref, 0))
        if qty <= 0: return self._reject(profile_ref, event_ref, "ITEM_USE", payload, "ITEM_NOT_AVAILABLE")
        char = self.engine.character(self.world_instance_id).state(profile_ref)
        health = float(char["vitals"]["health"]); max_health = float(char["derived"]["max_health"])
        resource = float(char["vitals"]["resource"]); max_resource = float(char["derived"]["max_resource"])
        wants_h = float(effect["health_restore"]) > 0 and health < max_health - 1e-9
        wants_r = float(effect["resource_restore"]) > 0 and resource < max_resource - 1e-9
        if not wants_h and not wants_r: return self._reject(profile_ref, event_ref, "ITEM_USE", payload, "ITEM_USE_NO_EFFECT")
        reservation = self.engine.resources_arpg(self.world_instance_id).reserve_action(
            profile_ref, action_ref="USE_ITEM", resource_cost=0.0, cooldown_s=float(effect["cooldown_s"]),
            cooldown_group=str(effect["cooldown_group"]), event_ref=event_ref + ":COOLDOWN", global_cooldown_s=0.0,
        )
        if reservation.get("status") != "PASS":
            return self._reject(profile_ref, event_ref, "ITEM_USE", payload, reservation.get("reason", "ITEM_COOLDOWN"), cooldown_result=reservation)
        applied_h = 0.0; applied_r = 0.0
        if wants_h:
            x = self.engine.character(self.world_instance_id).apply_health_change(profile_ref, float(effect["health_restore"]), event_ref=event_ref+":HEALTH", source_type="ARPG_ITEM_STAGE05")
            applied_h = float(x["applied_delta"])
        if wants_r:
            x = self.engine.character(self.world_instance_id).apply_resource_change(profile_ref, float(effect["resource_restore"]), event_ref=event_ref+":RESOURCE", source_type="ARPG_ITEM_STAGE05")
            applied_r = float(x["applied_delta"])
        inv = self._load_inventory(profile_ref); current = int(inv["stacks"].get(item_ref, 0))
        if current <= 0: raise IntegrityError("consumable disappeared during authoritative use")
        if current == 1: inv["stacks"].pop(item_ref, None)
        else: inv["stacks"][item_ref] = current - 1
        self._save_inventory(inv)
        return self._record_event(profile_ref, event_ref, "ITEM_USE", payload, {
            "status": "PASS", "item_ref": item_ref, "remaining_quantity": current-1,
            "applied_health": round(applied_h, 6), "applied_resource": round(applied_r, 6),
            "cooldown_group": effect["cooldown_group"], "cooldown_s": effect["cooldown_s"],
            "placeholder_only": False, "effect_authority": "GAMEPLAY_DERIVED_STAGE05", "idempotent_replay": False,
        })

    def equipment_modifiers(self, profile_ref: str) -> dict[str, Any]:
        self.engine.arpg(self.world_instance_id).profile(profile_ref)
        inv = self._load_inventory(profile_ref)
        total = {
            "damage_flat": 0.0, "damage_pct": 0.0, "armor_flat": 0.0, "accuracy_flat": 0.0,
            "evasion_flat": 0.0, "crit_chance_pct": 0.0, "attack_speed_pct": 0.0,
            "range_bonus_m": 0.0, "resistances": {"FIRE": 0.0, "COLD": 0.0, "LIGHTNING": 0.0, "TOXIC": 0.0, "ARCANE": 0.0},
        }
        applied = []
        for slot, iref in inv.get("equipped", {}).items():
            if not iref: continue
            inst = self.instance(iref); d = self.definition(inst["item_ref"])
            if inst.get("condition") == "BROKEN":
                applied.append({"slot": slot, "instance_ref": iref, "item_ref": inst["item_ref"], "applied": False, "reason": "BROKEN"})
                continue
            quality_factor = 0.75 + float(inst["quality"]) / 200.0
            base = d.get("base_modifiers") or {}
            for k in ("damage_flat", "damage_pct", "armor_flat", "accuracy_flat", "evasion_flat", "crit_chance_pct", "attack_speed_pct", "range_bonus_m"):
                total[k] += float(base.get(k, 0.0)) * quality_factor
            for dt, val in (base.get("resistances") or {}).items(): total["resistances"][dt] += float(val) * quality_factor
            for aff in inst.get("affixes", []):
                stat = aff.get("stat"); value = float(aff.get("value", 0.0))
                if isinstance(stat, str) and stat.startswith("resistance:"):
                    dt = stat.split(":",1)[1]; total["resistances"][dt] = total["resistances"].get(dt,0.0)+value
                elif stat in total and stat != "resistances": total[stat] += value
            applied.append({"slot": slot, "instance_ref": iref, "item_ref": inst["item_ref"], "applied": True, "rarity": inst["rarity"], "quality": inst["quality"]})
        for k in list(total):
            if k != "resistances": total[k] = round(float(total[k]), 6)
        total["resistances"] = {k: round(float(v), 6) for k,v in total["resistances"].items()}
        return {"status": "PASS", "modifiers": total, "equipped": applied, "authority": self.AUTHORITY}

    def event_history(self, owner_ref: str) -> list[dict[str, Any]]:
        rows = self.runtime.conn.execute(
            "SELECT server_sequence,event_ref,event_type,payload_json,result_json,event_hash FROM arpg_item_events WHERE world_instance_id=? AND owner_ref=? ORDER BY server_sequence",
            (self.world_instance_id, owner_ref),
        ).fetchall()
        return [{"server_sequence":r["server_sequence"],"event_ref":r["event_ref"],"event_type":r["event_type"],"payload":json.loads(r["payload_json"]),"result":json.loads(r["result_json"]),"event_hash":r["event_hash"]} for r in rows]

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        defs = self.runtime.conn.execute("SELECT item_ref,source_kind,payload_json,payload_hash FROM arpg_item_definitions ORDER BY item_ref").fetchall()
        # Catalog membership is checked by real filiation, not by counting rows filtered
        # through a hardcoded source_kind prefix allowlist. commerce_catalog_snapshots is
        # itself the definitive set of refs the commerce/bootstrap provider is responsible
        # for; any commerce ref missing its corresponding arpg_item_definitions row is a
        # real integrity failure. A definition existing that is NOT in commerce_catalog_
        # snapshots is never a failure here: legitimate independent providers (Stage09
        # fishing, Stage13 economy projections, and any future provider) own their own
        # refs outside the commerce catalog by design, and this check must never need
        # editing again just because another such provider is added.
        catalog_refs = {r["item_ref"] for r in self.runtime.conn.execute("SELECT item_ref FROM commerce_catalog_snapshots").fetchall()}
        definition_refs = {r["item_ref"] for r in defs}
        missing_catalog_refs = sorted(catalog_refs - definition_refs)
        if missing_catalog_refs: failures.append("ITEM_DEFINITION_CATALOG_REF_MISSING:" + ",".join(missing_catalog_refs))
        for row in defs:
            if sha256_text(row["payload_json"]) != row["payload_hash"]: failures.append("ITEM_DEFINITION_HASH:"+row["item_ref"])
            d = json.loads(row["payload_json"])
            if d.get("item_ref") != row["item_ref"]: failures.append("ITEM_DEFINITION_REF:"+row["item_ref"])
            if int(d.get("stack_max",0)) < 1: failures.append("ITEM_STACK_MAX:"+row["item_ref"])
        inv_rows = self.runtime.conn.execute("SELECT owner_ref,payload_json,payload_hash FROM arpg_item_inventories WHERE world_instance_id=?",(self.world_instance_id,)).fetchall()
        for row in inv_rows:
            if sha256_text(row["payload_json"]) != row["payload_hash"]: failures.append("INVENTORY_HASH:"+row["owner_ref"]); continue
            inv = json.loads(row["payload_json"])
            try: metrics = self._inventory_metrics(inv)
            except Exception: failures.append("INVENTORY_METRICS:"+row["owner_ref"]); continue
            if metrics["used_slots"] > int(inv["slot_capacity"]): failures.append("INVENTORY_SLOT_OVERFLOW:"+row["owner_ref"])
            if metrics["current_weight"] > float(inv["weight_capacity"])+1e-9: failures.append("INVENTORY_WEIGHT_OVERFLOW:"+row["owner_ref"])
            for ref,qty in inv.get("stacks",{}).items():
                try: d=self.definition(ref)
                except Exception: failures.append("INVENTORY_UNKNOWN_STACK:"+row["owner_ref"]+":"+ref); continue
                if not d["stackable"] or not isinstance(qty,int) or isinstance(qty,bool) or qty<=0: failures.append("INVENTORY_STACK_INVALID:"+row["owner_ref"]+":"+ref)
            owned=set(inv.get("instance_refs",[]))
            for slot,iref in inv.get("equipped",{}).items():
                if slot not in self.EQUIPMENT_SLOTS: failures.append("INVENTORY_SLOT_UNKNOWN:"+row["owner_ref"]+":"+slot)
                if iref and iref not in owned: failures.append("EQUIPPED_NOT_OWNED:"+row["owner_ref"]+":"+str(iref))
            for iref in owned:
                try: inst=self.instance(iref); d=self.definition(inst["item_ref"])
                except Exception: failures.append("INSTANCE_MISSING:"+iref); continue
                if inst.get("owner_ref")!=row["owner_ref"]: failures.append("INSTANCE_OWNER:"+iref)
                if inst.get("rarity") not in RARITY_TIERS: failures.append("INSTANCE_RARITY:"+iref)
                if not (1<=int(inst.get("quality",0))<=100): failures.append("INSTANCE_QUALITY:"+iref)
                if not (0.0<=float(inst.get("durability",-1))<=float(inst.get("max_durability",-2))+1e-9): failures.append("INSTANCE_DURABILITY:"+iref)
                if len(inst.get("sockets",[])) != int(inst.get("socket_capacity",-1)): failures.append("INSTANCE_SOCKET_COUNT:"+iref)
                if d["instance_policy"]!="UNIQUE_INSTANCE": failures.append("INSTANCE_POLICY:"+iref)
        event_rows=self.runtime.conn.execute("SELECT owner_ref,event_ref,event_type,payload_json,event_hash FROM arpg_item_events WHERE world_instance_id=?",(self.world_instance_id,)).fetchall()
        for r in event_rows:
            payload=json.loads(r["payload_json"])
            if self._event_hash(r["owner_ref"],r["event_ref"],r["event_type"],payload)!=r["event_hash"]: failures.append("ITEM_EVENT_HASH:"+r["event_ref"])
        return {
            "status":"PASS" if not failures else "FAIL", "failures":failures, "definitions":len(defs),
            "inventories":len(inv_rows), "instances":self.runtime.conn.execute("SELECT COUNT(*) c FROM arpg_item_instances WHERE world_instance_id=?",(self.world_instance_id,)).fetchone()["c"],
            "events":len(event_rows), "rarity_tiers":len(RARITY_TIERS), "affix_pool":len(AFFIX_POOL),
            "consumable_definitions":len(CONSUMABLE_EFFECTS), "version":self.VERSION, "authority":self.AUTHORITY,
        }
