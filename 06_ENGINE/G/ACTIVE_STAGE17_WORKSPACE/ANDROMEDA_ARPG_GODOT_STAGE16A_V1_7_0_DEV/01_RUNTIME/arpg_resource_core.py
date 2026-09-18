from __future__ import annotations

import copy
import json
import math
from typing import Any

from living_runtime import ValidationError, ConflictError, IntegrityError, canonical_json, sha256_text


PLACEHOLDER_CONSUMABLES: dict[str, dict[str, Any]] = {
    "PLACEHOLDER_HEALTH_RESTORE": {
        "kind": "HEALTH_RESTORE", "health_restore": 120.0, "resource_restore": 0.0,
        "cooldown_group": "CONSUMABLE_RECOVERY", "cooldown_s": 0.75, "starting_quantity": 3,
    },
    "PLACEHOLDER_RESOURCE_RESTORE": {
        "kind": "RESOURCE_RESTORE", "health_restore": 0.0, "resource_restore": 90.0,
        "cooldown_group": "CONSUMABLE_RECOVERY", "cooldown_s": 0.75, "starting_quantity": 3,
    },
    "PLACEHOLDER_HYBRID_RESTORE": {
        "kind": "HYBRID_RESTORE", "health_restore": 70.0, "resource_restore": 55.0,
        "cooldown_group": "CONSUMABLE_RECOVERY", "cooldown_s": 1.0, "starting_quantity": 1,
    },
}


class ARPGResourceCore:
    """Stage 04 adaptive resource, cooldown and placeholder-consumable authority.

    CharacterCore remains authoritative for health and the numeric PRIMARY resource pool.
    This layer owns action costs, cooldown ledgers, action locks and temporary placeholder
    consumables. Names and numbers in PLACEHOLDER_CONSUMABLES are GAMEPLAY_DERIVED and must
    not be interpreted as canonical Andrômeda items; Stage 05 will bind real itemization.
    """

    VERSION = "V0.5.0"
    STAGE = "04/20"
    AUTHORITY = "ARPG_RESOURCES_COOLDOWNS_CONSUMABLES_GAMEPLAY_DERIVATION"
    RESOURCE_MODEL = "ADAPTIVE_BUILD_DERIVED"
    PRIMARY_CHANNEL = "PRIMARY"
    MAX_ACTION_COST = 1_000_000.0
    MAX_COOLDOWN_S = 3600.0
    MAX_INTERRUPTION_S = 30.0
    MAX_CONSUMABLE_STACK = 999

    def __init__(self, engine: Any, world_instance_id: str) -> None:
        self.engine = engine
        self.runtime = engine.runtime
        self.world_instance_id = world_instance_id
        self._init_schema()
        self.bootstrap_existing_profiles()

    def _init_schema(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS arpg_resource_state(
                    world_instance_id TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, profile_ref),
                    FOREIGN KEY(world_instance_id, profile_ref)
                      REFERENCES arpg_player_profiles(world_instance_id, profile_ref) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS arpg_resource_events(
                    server_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    world_instance_id TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    event_ref TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id, event_ref)
                );
                CREATE INDEX IF NOT EXISTS idx_arpg_resource_events_profile
                  ON arpg_resource_events(world_instance_id, profile_ref, server_sequence);
                """
            )
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('arpg_resource_core_version',?)",
                (self.VERSION,),
            )

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> tuple[str, str]:
        text = canonical_json(payload)
        return text, sha256_text(text)

    def _row(self, profile_ref: str):
        return self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_resource_state WHERE world_instance_id=? AND profile_ref=?",
            (self.world_instance_id, profile_ref),
        ).fetchone()

    def _initial_state(self, profile_ref: str) -> dict[str, Any]:
        profile = self.engine.arpg(self.world_instance_id).profile(profile_ref)
        return {
            "profile_ref": profile_ref,
            "avatar_ref": profile["avatar_ref"],
            "resource_model": self.RESOURCE_MODEL,
            "resource_channels": {
                self.PRIMARY_CHANNEL: {
                    "active": True,
                    "mode": "UNSPECIALIZED",
                    "numeric_source": "CHARACTER_CORE_VITALS_RESOURCE",
                    "specialization_authority": "DEFERRED_BUILD_EVIDENCE_STAGE06",
                }
            },
            "cooldowns": {},
            "global_cooldown_remaining_s": 0.0,
            "global_cooldown_policy": "OPT_IN_PER_ACTION_NOT_UNIVERSAL",
            "action_lock_remaining_s": 0.0,
            "last_interrupt_source_ref": None,
            "consumables": {k: int(v["starting_quantity"]) for k, v in PLACEHOLDER_CONSUMABLES.items()},
            "consumable_authority": "PLACEHOLDER_ONLY_STAGE05_ITEMIZATION_PENDING",
            "regeneration_authority": "CHARACTER_CORE_DERIVED_STATS",
            "skill_cost_binding": "DEFERRED_STAGE06",
            "equipment_cost_modifiers": "DEFERRED_STAGE05",
            "art_dependency": "NONE_PLACEHOLDER_READY",
            "authority": self.AUTHORITY,
        }

    def _save(self, state: dict[str, Any]) -> None:
        text, h = self._hash_payload(state)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO arpg_resource_state VALUES(?,?,?,?)",
                (self.world_instance_id, state["profile_ref"], text, h),
            )

    def ensure_profile(self, profile_ref: str) -> dict[str, Any]:
        # Also validates the profile and guarantees CharacterCore exists.
        self.engine.character(self.world_instance_id).ensure_profile(profile_ref)
        row = self._row(profile_ref)
        if not row:
            self._save(self._initial_state(profile_ref))
        return self.state(profile_ref)

    def bootstrap_existing_profiles(self) -> None:
        try:
            profiles = self.engine.arpg(self.world_instance_id).list_profiles()
        except Exception:
            return
        for p in profiles:
            if not self._row(p["profile_ref"]):
                self._save(self._initial_state(p["profile_ref"]))

    def state(self, profile_ref: str) -> dict[str, Any]:
        row = self._row(profile_ref)
        if not row:
            raise KeyError(profile_ref)
        if sha256_text(row["payload_json"]) != row["payload_hash"]:
            raise IntegrityError("ARPG resource state hash mismatch")
        return json.loads(row["payload_json"])

    def _event_existing(self, event_ref: str):
        return self.runtime.conn.execute(
            "SELECT * FROM arpg_resource_events WHERE world_instance_id=? AND event_ref=?",
            (self.world_instance_id, event_ref),
        ).fetchone()

    def _event_hash(self, profile_ref: str, event_ref: str, event_type: str, payload: dict[str, Any]) -> str:
        return sha256_text(canonical_json({
            "profile_ref": profile_ref, "event_ref": event_ref, "event_type": event_type, "payload": payload,
        }))

    def _existing_or_none(self, profile_ref: str, event_ref: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        event_ref = str(event_ref).strip()
        if not event_ref or len(event_ref) > 180:
            raise ValidationError("event_ref must contain 1-180 characters")
        row = self._event_existing(event_ref)
        if not row:
            return None
        expected = self._event_hash(profile_ref, event_ref, event_type, payload)
        if row["event_hash"] != expected or row["profile_ref"] != profile_ref or row["event_type"] != event_type:
            raise ConflictError("RESOURCE_EVENT_REF_CONFLICT")
        out = json.loads(row["result_json"])
        out["idempotent_replay"] = True
        out["resource_server_sequence"] = row["server_sequence"]
        return out

    def _record_event(self, profile_ref: str, event_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        h = self._event_hash(profile_ref, event_ref, event_type, payload)
        with self.runtime._write_lock:
            cur = self.runtime.conn.execute(
                "INSERT INTO arpg_resource_events(world_instance_id,profile_ref,event_ref,event_type,payload_json,result_json,event_hash) VALUES(?,?,?,?,?,?,?)",
                (self.world_instance_id, profile_ref, event_ref, event_type, canonical_json(payload), canonical_json(result), h),
            )
            seq = cur.lastrowid
        out = copy.deepcopy(result)
        out["resource_server_sequence"] = seq
        return out

    def _reject(self, profile_ref: str, event_ref: str, event_type: str, payload: dict[str, Any], reason: str, **extra: Any) -> dict[str, Any]:
        return self._record_event(profile_ref, event_ref, event_type, payload, {
            "status": "REJECTED", "reason": reason, "idempotent_replay": False, **extra,
        })

    def _life_gate(self, profile_ref: str) -> dict[str, Any]:
        gate = self.engine.character(self.world_instance_id).can_act(profile_ref)
        if gate.get("status") != "PASS":
            return gate
        state = self.ensure_profile(profile_ref)
        if float(state.get("action_lock_remaining_s", 0.0)) > 1e-9:
            return {"status": "REJECTED", "reason": "ACTION_INTERRUPTED", "remaining_s": state["action_lock_remaining_s"]}
        return {"status": "PASS"}

    def snapshot(self, profile_ref: str) -> dict[str, Any]:
        state = self.ensure_profile(profile_ref)
        char = self.engine.character(self.world_instance_id).state(profile_ref)
        out = copy.deepcopy(state)
        out["resource_channels"][self.PRIMARY_CHANNEL]["current"] = float(char["vitals"]["resource"])
        out["resource_channels"][self.PRIMARY_CHANNEL]["maximum"] = float(char["derived"]["max_resource"])
        out["resource_channels"][self.PRIMARY_CHANNEL]["regen_per_s"] = float(char["derived"]["resource_regen_per_s"])
        return out

    def reserve_action(
        self,
        profile_ref: str,
        *,
        action_ref: str,
        resource_cost: float,
        cooldown_s: float,
        event_ref: str,
        cooldown_group: str | None = None,
        global_cooldown_s: float = 0.0,
    ) -> dict[str, Any]:
        action_ref = str(action_ref).strip().upper()
        cooldown_group = str(cooldown_group or action_ref).strip().upper()
        resource_cost = float(resource_cost)
        cooldown_s = float(cooldown_s)
        global_cooldown_s = float(global_cooldown_s)
        if not action_ref or len(action_ref) > 120 or not cooldown_group or len(cooldown_group) > 120:
            raise ValidationError("invalid action/cooldown reference")
        for value, name, upper in ((resource_cost, "resource_cost", self.MAX_ACTION_COST), (cooldown_s, "cooldown_s", self.MAX_COOLDOWN_S), (global_cooldown_s, "global_cooldown_s", self.MAX_COOLDOWN_S)):
            if not math.isfinite(value) or value < 0 or value > upper:
                raise ValidationError(f"{name} out of range")
        payload = {
            "action_ref": action_ref, "resource_cost": round(resource_cost, 6), "cooldown_s": round(cooldown_s, 6),
            "cooldown_group": cooldown_group, "global_cooldown_s": round(global_cooldown_s, 6),
        }
        existing = self._existing_or_none(profile_ref, event_ref, "ACTION_RESERVATION", payload)
        if existing is not None:
            return existing
        gate = self._life_gate(profile_ref)
        if gate.get("status") != "PASS":
            return self._reject(profile_ref, event_ref, "ACTION_RESERVATION", payload, gate.get("reason", "CHARACTER_CANNOT_ACT"), remaining_s=gate.get("remaining_s"))
        state = self.ensure_profile(profile_ref)
        remaining = float(state["cooldowns"].get(cooldown_group, 0.0))
        if remaining > 1e-9:
            return self._reject(profile_ref, event_ref, "ACTION_RESERVATION", payload, "ACTION_COOLDOWN", cooldown_group=cooldown_group, remaining_s=remaining)
        gcd = float(state.get("global_cooldown_remaining_s", 0.0))
        if gcd > 1e-9:
            return self._reject(profile_ref, event_ref, "ACTION_RESERVATION", payload, "GLOBAL_COOLDOWN", remaining_s=gcd)
        char = self.engine.character(self.world_instance_id).state(profile_ref)
        current = float(char["vitals"]["resource"])
        if resource_cost > current + 1e-9:
            return self._reject(profile_ref, event_ref, "ACTION_RESERVATION", payload, "INSUFFICIENT_RESOURCE", current=current, required=resource_cost)
        if resource_cost > 0:
            self.engine.character(self.world_instance_id).apply_resource_change(
                profile_ref, -resource_cost, event_ref=f"{event_ref}:PRIMARY_SPEND", source_type="ARPG_ACTION_COST",
            )
        state = self.ensure_profile(profile_ref)
        if cooldown_s > 0:
            state["cooldowns"][cooldown_group] = round(cooldown_s, 6)
        if global_cooldown_s > 0:
            state["global_cooldown_remaining_s"] = round(max(float(state.get("global_cooldown_remaining_s", 0.0)), global_cooldown_s), 6)
        self._save(state)
        after = float(self.engine.character(self.world_instance_id).state(profile_ref)["vitals"]["resource"])
        return self._record_event(profile_ref, event_ref, "ACTION_RESERVATION", payload, {
            "status": "PASS", "action_ref": action_ref, "cooldown_group": cooldown_group,
            "resource_before": current, "resource_after": after, "resource_spent": round(current-after, 6),
            "cooldown_remaining_s": round(cooldown_s, 6), "global_cooldown_remaining_s": round(global_cooldown_s, 6),
            "idempotent_replay": False,
        })

    def use_consumable(self, profile_ref: str, consumable_ref: str, *, event_ref: str) -> dict[str, Any]:
        consumable_ref = str(consumable_ref).strip().upper()
        definition = PLACEHOLDER_CONSUMABLES.get(consumable_ref)
        if not definition:
            raise ValidationError("unknown Stage04 placeholder consumable")
        payload = {"consumable_ref": consumable_ref}
        existing = self._existing_or_none(profile_ref, event_ref, "CONSUMABLE_USE", payload)
        if existing is not None:
            return existing
        gate = self._life_gate(profile_ref)
        if gate.get("status") != "PASS":
            return self._reject(profile_ref, event_ref, "CONSUMABLE_USE", payload, gate.get("reason", "CHARACTER_CANNOT_ACT"), remaining_s=gate.get("remaining_s"))
        state = self.ensure_profile(profile_ref)
        qty = int(state["consumables"].get(consumable_ref, 0))
        if qty <= 0:
            return self._reject(profile_ref, event_ref, "CONSUMABLE_USE", payload, "CONSUMABLE_EMPTY")
        group = str(definition["cooldown_group"])
        remaining = float(state["cooldowns"].get(group, 0.0))
        if remaining > 1e-9:
            return self._reject(profile_ref, event_ref, "CONSUMABLE_USE", payload, "CONSUMABLE_COOLDOWN", cooldown_group=group, remaining_s=remaining)
        char = self.engine.character(self.world_instance_id).state(profile_ref)
        health = float(char["vitals"]["health"]); max_health = float(char["derived"]["max_health"])
        resource = float(char["vitals"]["resource"]); max_resource = float(char["derived"]["max_resource"])
        wants_health = float(definition["health_restore"]) > 0 and health < max_health - 1e-9
        wants_resource = float(definition["resource_restore"]) > 0 and resource < max_resource - 1e-9
        if not wants_health and not wants_resource:
            return self._reject(profile_ref, event_ref, "CONSUMABLE_USE", payload, "CONSUMABLE_NO_EFFECT")
        applied_health = 0.0; applied_resource = 0.0
        if wants_health:
            out_h = self.engine.character(self.world_instance_id).apply_health_change(
                profile_ref, float(definition["health_restore"]), event_ref=f"{event_ref}:HEALTH", source_type="PLACEHOLDER_CONSUMABLE",
            )
            applied_health = float(out_h["applied_delta"])
        if wants_resource:
            out_r = self.engine.character(self.world_instance_id).apply_resource_change(
                profile_ref, float(definition["resource_restore"]), event_ref=f"{event_ref}:RESOURCE", source_type="PLACEHOLDER_CONSUMABLE",
            )
            applied_resource = float(out_r["applied_delta"])
        state = self.ensure_profile(profile_ref)
        state["consumables"][consumable_ref] = qty - 1
        state["cooldowns"][group] = round(float(definition["cooldown_s"]), 6)
        self._save(state)
        return self._record_event(profile_ref, event_ref, "CONSUMABLE_USE", payload, {
            "status": "PASS", "consumable_ref": consumable_ref, "remaining_quantity": qty-1,
            "applied_health": round(applied_health, 6), "applied_resource": round(applied_resource, 6),
            "cooldown_group": group, "cooldown_remaining_s": round(float(definition["cooldown_s"]), 6),
            "placeholder_only": True, "idempotent_replay": False,
        })

    def grant_consumable(self, profile_ref: str, consumable_ref: str, quantity: int, *, event_ref: str) -> dict[str, Any]:
        consumable_ref = str(consumable_ref).strip().upper()
        if consumable_ref not in PLACEHOLDER_CONSUMABLES:
            raise ValidationError("unknown Stage04 placeholder consumable")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0 or quantity > self.MAX_CONSUMABLE_STACK:
            raise ValidationError("quantity out of range")
        payload = {"consumable_ref": consumable_ref, "quantity": quantity}
        existing = self._existing_or_none(profile_ref, event_ref, "CONSUMABLE_GRANT", payload)
        if existing is not None:
            return existing
        state = self.ensure_profile(profile_ref)
        before = int(state["consumables"].get(consumable_ref, 0))
        after = min(self.MAX_CONSUMABLE_STACK, before + quantity)
        state["consumables"][consumable_ref] = after
        self._save(state)
        return self._record_event(profile_ref, event_ref, "CONSUMABLE_GRANT", payload, {
            "status": "PASS", "consumable_ref": consumable_ref, "before": before, "after": after,
            "granted": after-before, "idempotent_replay": False,
        })

    def apply_interruption(self, profile_ref: str, *, duration_s: float, source_ref: str, event_ref: str) -> dict[str, Any]:
        duration_s = float(duration_s)
        source_ref = str(source_ref).strip()
        if not math.isfinite(duration_s) or duration_s <= 0 or duration_s > self.MAX_INTERRUPTION_S:
            raise ValidationError("interruption duration out of range")
        if not source_ref or len(source_ref) > 160:
            raise ValidationError("invalid interruption source")
        payload = {"duration_s": round(duration_s, 6), "source_ref": source_ref}
        existing = self._existing_or_none(profile_ref, event_ref, "INTERRUPTION", payload)
        if existing is not None:
            return existing
        self.engine.character(self.world_instance_id).ensure_profile(profile_ref)
        state = self.ensure_profile(profile_ref)
        state["action_lock_remaining_s"] = round(max(float(state.get("action_lock_remaining_s", 0.0)), duration_s), 6)
        state["last_interrupt_source_ref"] = source_ref
        self._save(state)
        return self._record_event(profile_ref, event_ref, "INTERRUPTION", payload, {
            "status": "PASS", "action_lock_remaining_s": state["action_lock_remaining_s"], "source_ref": source_ref,
            "idempotent_replay": False,
        })

    def tick_profile(self, profile_ref: str, delta_s: float) -> dict[str, Any]:
        delta_s = float(delta_s)
        if not math.isfinite(delta_s) or delta_s <= 0 or delta_s > 1.0:
            raise ValidationError("delta_s must be in (0,1]")
        state = self.ensure_profile(profile_ref)
        changed = False
        cooldowns: dict[str, float] = {}
        for key, value in state.get("cooldowns", {}).items():
            nv = max(0.0, float(value) - delta_s)
            if nv > 1e-9:
                cooldowns[key] = round(nv, 6)
            if abs(nv - float(value)) > 1e-9:
                changed = True
        state["cooldowns"] = cooldowns
        for field in ("global_cooldown_remaining_s", "action_lock_remaining_s"):
            old = float(state.get(field, 0.0))
            new = max(0.0, old - delta_s)
            if abs(new-old) > 1e-9:
                state[field] = round(new, 6); changed = True
        if changed:
            self._save(state)
        return {
            "status": "PASS", "changed": changed, "cooldowns": copy.deepcopy(state["cooldowns"]),
            "global_cooldown_remaining_s": float(state.get("global_cooldown_remaining_s", 0.0)),
            "action_lock_remaining_s": float(state.get("action_lock_remaining_s", 0.0)),
        }

    def event_history(self, profile_ref: str) -> list[dict[str, Any]]:
        rows = self.runtime.conn.execute(
            "SELECT server_sequence,event_ref,event_type,payload_json,result_json,event_hash FROM arpg_resource_events WHERE world_instance_id=? AND profile_ref=? ORDER BY server_sequence",
            (self.world_instance_id, profile_ref),
        ).fetchall()
        return [{
            "server_sequence": r["server_sequence"], "event_ref": r["event_ref"], "event_type": r["event_type"],
            "payload": json.loads(r["payload_json"]), "result": json.loads(r["result_json"]), "event_hash": r["event_hash"],
        } for r in rows]

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        profiles = self.engine.arpg(self.world_instance_id).list_profiles()
        for p in profiles:
            try:
                state = self.ensure_profile(p["profile_ref"])
                char = self.engine.character(self.world_instance_id).state(p["profile_ref"])
            except Exception:
                failures.append("RESOURCE_STATE_MISSING_OR_CORRUPT:" + p["profile_ref"]); continue
            if state.get("avatar_ref") != p.get("avatar_ref"):
                failures.append("RESOURCE_AVATAR_BINDING:" + p["profile_ref"])
            if state.get("resource_model") != self.RESOURCE_MODEL:
                failures.append("RESOURCE_MODEL:" + p["profile_ref"])
            if state.get("resource_channels", {}).get(self.PRIMARY_CHANNEL, {}).get("numeric_source") != "CHARACTER_CORE_VITALS_RESOURCE":
                failures.append("PRIMARY_RESOURCE_AUTHORITY:" + p["profile_ref"])
            if not (0.0 <= float(char["vitals"]["resource"]) <= float(char["derived"]["max_resource"])):
                failures.append("PRIMARY_RESOURCE_RANGE:" + p["profile_ref"])
            for key, value in state.get("cooldowns", {}).items():
                if not isinstance(key, str) or not key or float(value) <= 0 or float(value) > self.MAX_COOLDOWN_S:
                    failures.append("COOLDOWN_RANGE:" + p["profile_ref"] + ":" + str(key))
            if not (0.0 <= float(state.get("global_cooldown_remaining_s", -1)) <= self.MAX_COOLDOWN_S):
                failures.append("GCD_RANGE:" + p["profile_ref"])
            if not (0.0 <= float(state.get("action_lock_remaining_s", -1)) <= self.MAX_INTERRUPTION_S):
                failures.append("ACTION_LOCK_RANGE:" + p["profile_ref"])
            for cref, qty in state.get("consumables", {}).items():
                if cref not in PLACEHOLDER_CONSUMABLES or not isinstance(qty, int) or isinstance(qty, bool) or not (0 <= qty <= self.MAX_CONSUMABLE_STACK):
                    failures.append("CONSUMABLE_LEDGER:" + p["profile_ref"] + ":" + str(cref))
        rows = self.runtime.conn.execute(
            "SELECT profile_ref,event_ref,event_type,payload_json,event_hash FROM arpg_resource_events WHERE world_instance_id=?",
            (self.world_instance_id,),
        ).fetchall()
        for r in rows:
            payload = json.loads(r["payload_json"])
            if self._event_hash(r["profile_ref"], r["event_ref"], r["event_type"], payload) != r["event_hash"]:
                failures.append("RESOURCE_EVENT_HASH:" + r["event_ref"])
        return {
            "status": "PASS" if not failures else "FAIL", "failures": failures, "profiles": len(profiles),
            "events": len(rows), "version": self.VERSION, "resource_model": self.RESOURCE_MODEL,
            "placeholder_consumables": len(PLACEHOLDER_CONSUMABLES), "authority": self.AUTHORITY,
        }
