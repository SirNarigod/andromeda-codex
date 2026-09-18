from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from typing import Any, Callable


PICKUP_RADIUS_M = 0.5
ALLOWED_SOURCE_KINDS = {
    "ENEMY", "TREE", "ROCK", "ORE", "FLORA", "AGRICULTURE",
    "HUNTING", "FISHING", "CONTAINER", "PRODUCTION", "PLAYER_DROP",
}

ICON_CATEGORY_BY_ITEM_KIND = {
    "WEAPON": "ICON_WEAPON",
    "ARMOR": "ICON_ARMOR",
    "TOOL": "ICON_TOOL",
    "CONSUMABLE": "ICON_CONSUMABLE",
    "FOOD": "ICON_FOOD",
    "MATERIAL": "ICON_MATERIAL",
    "RESOURCE": "ICON_MATERIAL",
    "ORE": "ICON_MINERAL",
    "MINERAL": "ICON_MINERAL",
    "WOOD": "ICON_NATURAL_RESOURCE",
    "FLORA": "ICON_FLORA",
    "TECH_COMPONENT": "ICON_TECH_COMPONENT",
    "RUNE": "ICON_RUNE",
    "QUEST": "ICON_QUEST",
    "CURRENCY": "ICON_CURRENCY",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class GroundLootCore:
    """Persistent pre-Godot ground-loot authority for Stage 16A.

    Physics and safe-ground settlement are intentionally external. A drop cannot be
    picked up until the runtime/editor confirms it has settled in a reachable point.
    """

    def __init__(self, conn: sqlite3.Connection, world_instance_id: str):
        self.conn = conn
        self.world_instance_id = str(world_instance_id)
        self.conn.row_factory = sqlite3.Row
        self._schema()

    def _schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS arpg_ground_loot(
                world_instance_id TEXT NOT NULL,
                drop_ref TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                state TEXT NOT NULL,
                PRIMARY KEY(world_instance_id, drop_ref)
            );
            CREATE TABLE IF NOT EXISTS arpg_ground_loot_events(
                world_instance_id TEXT NOT NULL,
                event_ref TEXT NOT NULL,
                action TEXT NOT NULL,
                result_json TEXT NOT NULL,
                result_hash TEXT NOT NULL,
                PRIMARY KEY(world_instance_id, event_ref)
            );
            """
        )
        self.conn.commit()

    def _event(self, event_ref: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT result_json,result_hash FROM arpg_ground_loot_events WHERE world_instance_id=? AND event_ref=?",
            (self.world_instance_id, event_ref),
        ).fetchone()
        if not row:
            return None
        if _sha(row["result_json"]) != row["result_hash"]:
            raise RuntimeError("GROUND_LOOT_EVENT_HASH_MISMATCH")
        result = json.loads(row["result_json"])
        result["idempotent_replay"] = True
        return result

    def _record(self, event_ref: str, action: str, result: dict[str, Any]) -> dict[str, Any]:
        text = _canonical_json(result)
        self.conn.execute(
            "INSERT INTO arpg_ground_loot_events(world_instance_id,event_ref,action,result_json,result_hash) VALUES(?,?,?,?,?)",
            (self.world_instance_id, event_ref, action, text, _sha(text)),
        )
        self.conn.commit()
        return result

    def _save(self, payload: dict[str, Any]) -> None:
        text = _canonical_json(payload)
        self.conn.execute(
            "INSERT OR REPLACE INTO arpg_ground_loot(world_instance_id,drop_ref,payload_json,payload_hash,state) VALUES(?,?,?,?,?)",
            (self.world_instance_id, payload["drop_ref"], text, _sha(text), payload["state"]),
        )
        self.conn.commit()

    def drop(self, drop_ref: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_ground_loot WHERE world_instance_id=? AND drop_ref=?",
            (self.world_instance_id, str(drop_ref)),
        ).fetchone()
        if not row:
            raise KeyError("GROUND_LOOT_NOT_FOUND:" + str(drop_ref))
        if _sha(row["payload_json"]) != row["payload_hash"]:
            raise RuntimeError("GROUND_LOOT_HASH_MISMATCH")
        return json.loads(row["payload_json"])

    def icon_category(self, item_kind: str) -> str:
        return ICON_CATEGORY_BY_ITEM_KIND.get(str(item_kind).upper().strip(), "ICON_GENERIC_ITEM_TYPE")

    def spawn_drop(
        self,
        *,
        source_ref: str,
        source_kind: str,
        item_ref: str,
        item_kind: str,
        quantity: int,
        candidate_position: dict[str, float],
        event_ref: str,
        drop_index: int = 0,
        rarity: str | None = None,
        quality: int | None = None,
    ) -> dict[str, Any]:
        replay = self._event(event_ref)
        if replay is not None:
            return replay
        source_kind = str(source_kind).upper().strip()
        if source_kind not in ALLOWED_SOURCE_KINDS:
            return self._record(event_ref, "SPAWN", {"status": "REJECTED", "reason": "UNSUPPORTED_PHYSICAL_DROP_SOURCE", "source_kind": source_kind, "idempotent_replay": False})
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            return self._record(event_ref, "SPAWN", {"status": "REJECTED", "reason": "INVALID_DROP_QUANTITY", "idempotent_replay": False})
        if not isinstance(drop_index, int) or drop_index < 0:
            return self._record(event_ref, "SPAWN", {"status": "REJECTED", "reason": "INVALID_DROP_INDEX", "idempotent_replay": False})
        try:
            pos = {
                "iso_x_m": float(candidate_position["iso_x_m"]),
                "iso_y_m": float(candidate_position["iso_y_m"]),
                "altitude_m": float(candidate_position.get("altitude_m", 0.0)),
            }
        except Exception:
            return self._record(event_ref, "SPAWN", {"status": "REJECTED", "reason": "INVALID_DROP_POSITION", "idempotent_replay": False})
        if not all(math.isfinite(v) for v in pos.values()):
            return self._record(event_ref, "SPAWN", {"status": "REJECTED", "reason": "INVALID_DROP_POSITION", "idempotent_replay": False})

        drop_ref = "DROP-S16A-" + _sha(f"{self.world_instance_id}|{event_ref}|{drop_index}|{item_ref}")[:20].upper()
        payload = {
            "drop_ref": drop_ref,
            "source_ref": str(source_ref),
            "source_kind": source_kind,
            "item_ref": str(item_ref),
            "item_kind": str(item_kind).upper().strip(),
            "icon_category": self.icon_category(item_kind),
            "quantity": quantity,
            "rarity": rarity,
            "quality": quality,
            "candidate_position": pos,
            "settled_position": None,
            "settled": False,
            "reachable": False,
            "state": "ACTIVE",
            "pickup_radius_m": PICKUP_RADIUS_M,
            "physical_world_first": True,
            "direct_to_inventory": False,
            "environment": "LAND",
            "water_exposure_s": 0.0,
            "water_ttl_s": None,
            "water_flow_speed_mps": 0.0,
            "float_state": None,
            "authority": "STAGE16A_GAMEPLAY_RUNTIME_NOT_CANON",
        }
        self._save(payload)
        return self._record(event_ref, "SPAWN", {"status": "PASS", "drop_ref": drop_ref, "drop": payload, "idempotent_replay": False})

    def confirm_settled(
        self,
        drop_ref: str,
        *,
        settled_position: dict[str, float],
        reachable: bool,
        event_ref: str,
    ) -> dict[str, Any]:
        replay = self._event(event_ref)
        if replay is not None:
            return replay
        payload = self.drop(drop_ref)
        if payload["state"] != "ACTIVE":
            return self._record(event_ref, "SETTLE", {"status": "REJECTED", "reason": "DROP_NOT_ACTIVE", "drop_ref": drop_ref, "idempotent_replay": False})
        pos = {
            "iso_x_m": float(settled_position["iso_x_m"]),
            "iso_y_m": float(settled_position["iso_y_m"]),
            "altitude_m": float(settled_position.get("altitude_m", 0.0)),
        }
        if not all(math.isfinite(v) for v in pos.values()):
            return self._record(event_ref, "SETTLE", {"status": "REJECTED", "reason": "INVALID_SETTLED_POSITION", "drop_ref": drop_ref, "idempotent_replay": False})
        payload["settled_position"] = pos
        payload["settled"] = True
        payload["reachable"] = bool(reachable)
        self._save(payload)
        return self._record(event_ref, "SETTLE", {"status": "PASS", "drop_ref": drop_ref, "reachable": payload["reachable"], "idempotent_replay": False})

    def pickup(
        self,
        drop_ref: str,
        *,
        profile_ref: str,
        physical_distance_m: float,
        reachable_now: bool,
        event_ref: str,
        grant_item: Callable[..., dict[str, Any]],
    ) -> dict[str, Any]:
        replay = self._event(event_ref)
        if replay is not None:
            return replay
        payload = self.drop(drop_ref)
        if payload["state"] != "ACTIVE":
            return self._record(event_ref, "PICKUP", {"status": "REJECTED", "reason": "DROP_NOT_ACTIVE", "drop_ref": drop_ref, "idempotent_replay": False})
        if not payload.get("settled"):
            return self._record(event_ref, "PICKUP", {"status": "REJECTED", "reason": "DROP_NOT_SETTLED", "drop_ref": drop_ref, "idempotent_replay": False})
        if not payload.get("reachable") or not reachable_now:
            return self._record(event_ref, "PICKUP", {"status": "REJECTED", "reason": "GROUND_LOOT_UNREACHABLE", "drop_ref": drop_ref, "idempotent_replay": False})
        try:
            distance = float(physical_distance_m)
        except Exception:
            distance = float("inf")
        if not math.isfinite(distance) or distance > PICKUP_RADIUS_M:
            return self._record(event_ref, "PICKUP", {"status": "REJECTED", "reason": "PICKUP_DISTANCE_EXCEEDED", "drop_ref": drop_ref, "distance_m": distance, "max_distance_m": PICKUP_RADIUS_M, "idempotent_replay": False})

        grant = grant_item(
            str(profile_ref), payload["item_ref"], int(payload["quantity"]),
            event_ref="ground-loot:" + str(event_ref), rarity=payload.get("rarity"), quality=payload.get("quality"),
        )
        if grant.get("status") != "PASS":
            return self._record(event_ref, "PICKUP", {"status": "REJECTED", "reason": grant.get("reason", "INVENTORY_REJECTED"), "drop_ref": drop_ref, "inventory_result": grant, "drop_remains_active": True, "idempotent_replay": False})
        payload["state"] = "COLLECTED"
        payload["collected_by_profile_ref"] = str(profile_ref)
        self._save(payload)
        return self._record(event_ref, "PICKUP", {"status": "PASS", "drop_ref": drop_ref, "profile_ref": str(profile_ref), "item_ref": payload["item_ref"], "quantity": payload["quantity"], "inventory_result": grant, "idempotent_replay": False})

    def set_water_state(self, drop_ref: str, *, in_water: bool, flow_speed_mps: float, ttl_s: float, event_ref: str) -> dict[str, Any]:
        replay = self._event(event_ref)
        if replay is not None:
            return replay
        payload = self.drop(drop_ref)
        if payload["state"] != "ACTIVE":
            return self._record(event_ref, "WATER_STATE", {"status":"REJECTED","reason":"DROP_NOT_ACTIVE","drop_ref":drop_ref,"idempotent_replay":False})
        if bool(in_water):
            payload["environment"] = "WATER"
            payload["water_ttl_s"] = float(ttl_s)
            payload["water_flow_speed_mps"] = max(0.0, float(flow_speed_mps))
            payload["float_state"] = "FLOATING_OR_SUSPENDED"
            payload.setdefault("water_exposure_s", 0.0)
        else:
            payload["environment"] = "LAND"
            payload["water_ttl_s"] = None
            payload["water_flow_speed_mps"] = 0.0
            payload["float_state"] = None
            payload["water_exposure_s"] = 0.0
        self._save(payload)
        return self._record(event_ref, "WATER_STATE", {"status":"PASS","drop_ref":drop_ref,"environment":payload["environment"],"water_ttl_s":payload["water_ttl_s"],"idempotent_replay":False})

    def advance_water_exposure(self, delta_s: float, *, event_ref: str) -> dict[str, Any]:
        replay = self._event(event_ref)
        if replay is not None:
            return replay
        delta = max(0.0, float(delta_s))
        sunk = []
        rows = self.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_ground_loot WHERE world_instance_id=? AND state='ACTIVE'",
            (self.world_instance_id,),
        ).fetchall()
        for row in rows:
            if _sha(row["payload_json"]) != row["payload_hash"]:
                raise RuntimeError("GROUND_LOOT_HASH_MISMATCH")
            payload = json.loads(row["payload_json"])
            if payload.get("environment") != "WATER":
                continue
            payload["water_exposure_s"] = round(float(payload.get("water_exposure_s",0.0)) + delta, 6)
            ttl = payload.get("water_ttl_s")
            if ttl is not None and payload["water_exposure_s"] >= float(ttl):
                payload["state"] = "SUNK"
                payload["float_state"] = "SUNK"
                payload["reachable"] = False
                sunk.append(payload["drop_ref"])
            self._save(payload)
        return self._record(event_ref, "ADVANCE_WATER_EXPOSURE", {"status":"PASS","delta_s":delta,"sunk_drop_refs":sunk,"idempotent_replay":False})

    def active_drops(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_ground_loot WHERE world_instance_id=? AND state='ACTIVE' ORDER BY drop_ref",
            (self.world_instance_id,),
        ).fetchall()
        out = []
        for row in rows:
            if _sha(row["payload_json"]) != row["payload_hash"]:
                raise RuntimeError("GROUND_LOOT_HASH_MISMATCH")
            out.append(json.loads(row["payload_json"]))
        return out
