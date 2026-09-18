from __future__ import annotations

import copy
import json
import math
from typing import Any

from living_runtime import ValidationError, ConflictError, IntegrityError, canonical_json, sha256_text


CORE_ATTRIBUTES = ("POWER", "AGILITY", "VITALITY", "INTELLECT", "WILL", "PERCEPTION")
LIFE_STATES = {"ALIVE", "DEAD"}


class CharacterCore:
    """Stage 02 deterministic player-character progression core.

    All numeric values are GAMEPLAY_DERIVED runtime data. Canonical characters keep their
    canonical identity but do not receive invented canonical stats. Combat damage, skills,
    equipment modifiers and respawn rules remain deferred to their dedicated ARPG stages.
    """

    VERSION = "V0.3.0"
    STAGE = "02/18"
    AUTHORITY = "ARPG_CHARACTER_CORE_GAMEPLAY_DERIVATION"
    LEVEL_CAP = 100
    BASE_ATTRIBUTE = 10
    ATTRIBUTE_POINTS_PER_LEVEL = 5
    MAX_ATTRIBUTE_VALUE = 250
    MAX_EVENT_XP = 10_000_000

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
                CREATE TABLE IF NOT EXISTS arpg_character_state(
                    world_instance_id TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, profile_ref),
                    FOREIGN KEY(world_instance_id, profile_ref)
                      REFERENCES arpg_player_profiles(world_instance_id, profile_ref) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS arpg_character_events(
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
                CREATE INDEX IF NOT EXISTS idx_arpg_character_events_profile
                    ON arpg_character_events(world_instance_id, profile_ref, server_sequence);
                """
            )
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('arpg_character_core_version',?)",
                (self.VERSION,),
            )

    @staticmethod
    def xp_to_next(level: int) -> int:
        level = int(level)
        if level < 1:
            raise ValidationError("level must be >= 1")
        if level >= CharacterCore.LEVEL_CAP:
            return 0
        # Smooth ARPG curve: inexpensive early experimentation, progressively slower mastery.
        return int(round(100.0 * (level ** 1.52) + 35.0 * level))

    @classmethod
    def cumulative_xp_for_level(cls, level: int) -> int:
        level = max(1, min(cls.LEVEL_CAP, int(level)))
        return sum(cls.xp_to_next(lvl) for lvl in range(1, level))

    @classmethod
    def derived_stats(cls, attributes: dict[str, int], level: int) -> dict[str, float | int]:
        a = {k: int(attributes[k]) for k in CORE_ATTRIBUTES}
        level = int(level)
        return {
            "max_health": int(100 + a["VITALITY"] * 12 + level * 4),
            "max_resource": int(50 + a["WILL"] * 6 + a["INTELLECT"] * 4 + level * 2),
            "health_regen_per_s": round(0.25 + a["VITALITY"] * 0.04 + a["WILL"] * 0.02, 6),
            "resource_regen_per_s": round(0.50 + a["WILL"] * 0.06 + a["INTELLECT"] * 0.04, 6),
            "power_potential": round(a["POWER"] * 2.0 + a["AGILITY"] * 0.5, 6),
            "precision_potential": round(a["AGILITY"] * 1.5 + a["PERCEPTION"] * 1.2, 6),
            "technique_potential": round(a["INTELLECT"] * 1.5 + a["WILL"] * 0.8, 6),
            "resilience_potential": round(a["VITALITY"] * 1.5 + a["WILL"] * 1.0, 6),
        }

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> tuple[str, str]:
        text = canonical_json(payload)
        return text, sha256_text(text)

    def _row(self, profile_ref: str):
        return self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_character_state WHERE world_instance_id=? AND profile_ref=?",
            (self.world_instance_id, profile_ref),
        ).fetchone()

    def _initial_state(self, profile_ref: str) -> dict[str, Any]:
        profile = self.engine.arpg(self.world_instance_id).profile(profile_ref)
        attrs = {name: self.BASE_ATTRIBUTE for name in CORE_ATTRIBUTES}
        derived = self.derived_stats(attrs, 1)
        return {
            "profile_ref": profile_ref,
            "avatar_ref": profile["avatar_ref"],
            "origin_mode": profile["origin_mode"],
            "canonical_ref": profile.get("canonical_ref"),
            "level": 1,
            "level_cap": self.LEVEL_CAP,
            "experience": 0,
            "experience_into_level": 0,
            "experience_to_next": self.xp_to_next(1),
            "unspent_attribute_points": 0,
            "attributes": attrs,
            "derived": derived,
            "vitals": {
                "life_state": "ALIVE",
                "health": float(derived["max_health"]),
                "resource": float(derived["max_resource"]),
            },
            "build_evidence": {
                "attribute_investment": {name: 0 for name in CORE_ATTRIBUTES},
                "skills": {},
                "equipment": {},
                "playstyle": {},
                "emergent_class": None,
                "classification_stage": "DEFERRED_UNTIL_BUILD_SIGNALS_EXIST",
            },
            "numeric_authority": "GAMEPLAY_DERIVED_NOT_CANON",
            "combat_formulas": "DEFERRED_STAGE03",
            "skill_formulas": "DEFERRED_STAGE07",
            "equipment_modifiers": "DEFERRED_STAGE05",
            "death_resolution": "DEFERRED_STAGE13",
            "art_dependency": "NONE_PLACEHOLDER_READY",
            "authority": self.AUTHORITY,
        }

    def ensure_profile(self, profile_ref: str) -> dict[str, Any]:
        if self._row(profile_ref):
            return self.state(profile_ref)
        state = self._initial_state(profile_ref)
        self._save(state)
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
            raise IntegrityError("ARPG character state hash mismatch")
        return json.loads(row["payload_json"])

    def _save(self, state: dict[str, Any]) -> None:
        text, h = self._hash_payload(state)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO arpg_character_state VALUES(?,?,?,?)",
                (self.world_instance_id, state["profile_ref"], text, h),
            )

    def _event_existing(self, event_ref: str):
        return self.runtime.conn.execute(
            "SELECT * FROM arpg_character_events WHERE world_instance_id=? AND event_ref=?",
            (self.world_instance_id, event_ref),
        ).fetchone()

    def _event_hash(self, profile_ref: str, event_ref: str, event_type: str, payload: dict[str, Any]) -> str:
        return sha256_text(canonical_json({
            "profile_ref": profile_ref,
            "event_ref": event_ref,
            "event_type": event_type,
            "payload": payload,
        }))

    def _record_event(self, profile_ref: str, event_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        event_ref = str(event_ref).strip()
        if not event_ref or len(event_ref) > 160:
            raise ValidationError("event_ref must contain 1-160 characters")
        h = self._event_hash(profile_ref, event_ref, event_type, payload)
        existing = self._event_existing(event_ref)
        if existing:
            if existing["event_hash"] != h or existing["profile_ref"] != profile_ref or existing["event_type"] != event_type:
                raise ConflictError("CHARACTER_EVENT_REF_CONFLICT")
            out = json.loads(existing["result_json"])
            out["idempotent_replay"] = True
            return out
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT INTO arpg_character_events(world_instance_id,profile_ref,event_ref,event_type,payload_json,result_json,event_hash) VALUES(?,?,?,?,?,?,?)",
                (self.world_instance_id, profile_ref, event_ref, event_type, canonical_json(payload), canonical_json(result), h),
            )
        return result

    def _validate_profile(self, profile_ref: str) -> dict[str, Any]:
        profile = self.engine.arpg(self.world_instance_id).profile(profile_ref)
        self.ensure_profile(profile_ref)
        return profile

    def award_experience(self, profile_ref: str, amount: int, *, event_ref: str, source_type: str = "GAMEPLAY") -> dict[str, Any]:
        self._validate_profile(profile_ref)
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0 or amount > self.MAX_EVENT_XP:
            raise ValidationError("experience amount out of range")
        source_type = str(source_type).strip().upper() or "GAMEPLAY"
        payload = {"amount": amount, "source_type": source_type}
        existing = self._event_existing(str(event_ref).strip())
        if existing:
            h = self._event_hash(profile_ref, str(event_ref).strip(), "XP_AWARD", payload)
            if existing["event_hash"] != h:
                raise ConflictError("CHARACTER_EVENT_REF_CONFLICT")
            out = json.loads(existing["result_json"])
            out["idempotent_replay"] = True
            return out

        state = self.state(profile_ref)
        before_level = int(state["level"])
        if before_level >= self.LEVEL_CAP:
            result = {"status": "PASS", "profile_ref": profile_ref, "xp_applied": 0, "level_before": before_level, "level_after": before_level, "levels_gained": 0, "level_cap_reached": True, "idempotent_replay": False}
            return self._record_event(profile_ref, event_ref, "XP_AWARD", payload, result)

        before_xp = int(state["experience"])
        new_xp = min(self.cumulative_xp_for_level(self.LEVEL_CAP), before_xp + amount)
        new_level = before_level
        while new_level < self.LEVEL_CAP and new_xp >= self.cumulative_xp_for_level(new_level + 1):
            new_level += 1
        gained = new_level - before_level
        state["experience"] = new_xp
        state["level"] = new_level
        floor = self.cumulative_xp_for_level(new_level)
        state["experience_into_level"] = 0 if new_level >= self.LEVEL_CAP else new_xp - floor
        state["experience_to_next"] = self.xp_to_next(new_level)
        if gained:
            state["unspent_attribute_points"] = int(state["unspent_attribute_points"]) + gained * self.ATTRIBUTE_POINTS_PER_LEVEL
            old_derived = copy.deepcopy(state["derived"])
            state["derived"] = self.derived_stats(state["attributes"], new_level)
            self._preserve_vital_deficit(state, old_derived)
        self._save(state)
        result = {
            "status": "PASS", "profile_ref": profile_ref, "xp_applied": new_xp - before_xp,
            "experience": new_xp, "level_before": before_level, "level_after": new_level, "levels_gained": gained,
            "attribute_points_gained": gained * self.ATTRIBUTE_POINTS_PER_LEVEL, "level_cap_reached": new_level >= self.LEVEL_CAP,
            "idempotent_replay": False,
        }
        return self._record_event(profile_ref, event_ref, "XP_AWARD", payload, result)

    def _preserve_vital_deficit(self, state: dict[str, Any], old_derived: dict[str, Any]) -> None:
        vitals = state["vitals"]
        old_max_h = float(old_derived["max_health"])
        old_max_r = float(old_derived["max_resource"])
        missing_h = max(0.0, old_max_h - float(vitals["health"]))
        missing_r = max(0.0, old_max_r - float(vitals["resource"]))
        vitals["health"] = max(0.0, float(state["derived"]["max_health"]) - missing_h)
        vitals["resource"] = max(0.0, float(state["derived"]["max_resource"]) - missing_r)
        if vitals["health"] <= 0.0:
            vitals["health"] = 0.0
            vitals["life_state"] = "DEAD"

    def allocate_attributes(self, profile_ref: str, allocations: dict[str, int], *, event_ref: str) -> dict[str, Any]:
        self._validate_profile(profile_ref)
        if not isinstance(allocations, dict) or not allocations:
            raise ValidationError("allocations must be a non-empty object")
        normalized: dict[str, int] = {}
        for raw_key, raw_value in allocations.items():
            key = str(raw_key).upper().strip()
            if key not in CORE_ATTRIBUTES:
                raise ValidationError("unknown core attribute: " + key)
            if not isinstance(raw_value, int) or isinstance(raw_value, bool) or raw_value <= 0:
                raise ValidationError("attribute allocations must be positive integers")
            normalized[key] = normalized.get(key, 0) + raw_value
        payload = {"allocations": dict(sorted(normalized.items()))}
        existing = self._event_existing(str(event_ref).strip())
        if existing:
            h = self._event_hash(profile_ref, str(event_ref).strip(), "ATTRIBUTE_ALLOCATION", payload)
            if existing["event_hash"] != h:
                raise ConflictError("CHARACTER_EVENT_REF_CONFLICT")
            out = json.loads(existing["result_json"])
            out["idempotent_replay"] = True
            return out

        state = self.state(profile_ref)
        total = sum(normalized.values())
        if total > int(state["unspent_attribute_points"]):
            raise ConflictError("INSUFFICIENT_ATTRIBUTE_POINTS")
        for key, amount in normalized.items():
            if int(state["attributes"][key]) + amount > self.MAX_ATTRIBUTE_VALUE:
                raise ConflictError("ATTRIBUTE_CAP_EXCEEDED:" + key)
        old_derived = copy.deepcopy(state["derived"])
        for key, amount in normalized.items():
            state["attributes"][key] = int(state["attributes"][key]) + amount
            state["build_evidence"]["attribute_investment"][key] = int(state["build_evidence"]["attribute_investment"][key]) + amount
        state["unspent_attribute_points"] = int(state["unspent_attribute_points"]) - total
        state["derived"] = self.derived_stats(state["attributes"], int(state["level"]))
        self._preserve_vital_deficit(state, old_derived)
        self._save(state)
        result = {
            "status": "PASS", "profile_ref": profile_ref, "allocated": payload["allocations"],
            "unspent_attribute_points": state["unspent_attribute_points"], "attributes": copy.deepcopy(state["attributes"]),
            "derived": copy.deepcopy(state["derived"]), "idempotent_replay": False,
        }
        return self._record_event(profile_ref, event_ref, "ATTRIBUTE_ALLOCATION", payload, result)

    def apply_health_change(self, profile_ref: str, delta: float, *, event_ref: str, source_type: str = "SYSTEM") -> dict[str, Any]:
        self._validate_profile(profile_ref)
        if not isinstance(delta, (int, float)) or isinstance(delta, bool) or not math.isfinite(float(delta)) or float(delta) == 0.0:
            raise ValidationError("health delta must be finite and non-zero")
        delta = round(float(delta), 6)
        source_type = str(source_type).strip().upper() or "SYSTEM"
        payload = {"delta": delta, "source_type": source_type}
        existing = self._event_existing(str(event_ref).strip())
        if existing:
            h = self._event_hash(profile_ref, str(event_ref).strip(), "HEALTH_CHANGE", payload)
            if existing["event_hash"] != h:
                raise ConflictError("CHARACTER_EVENT_REF_CONFLICT")
            out = json.loads(existing["result_json"])
            out["idempotent_replay"] = True
            return out
        state = self.state(profile_ref)
        before = float(state["vitals"]["health"])
        if state["vitals"]["life_state"] == "DEAD" and delta > 0:
            raise ConflictError("DEAD_CHARACTER_REQUIRES_RESPAWN_STAGE13")
        after = min(float(state["derived"]["max_health"]), max(0.0, before + delta))
        state["vitals"]["health"] = round(after, 6)
        if after <= 0.0:
            state["vitals"]["life_state"] = "DEAD"
        self._save(state)
        result = {"status": "PASS", "profile_ref": profile_ref, "health_before": before, "health_after": after, "applied_delta": round(after - before, 6), "life_state": state["vitals"]["life_state"], "idempotent_replay": False}
        return self._record_event(profile_ref, event_ref, "HEALTH_CHANGE", payload, result)

    def apply_resource_change(self, profile_ref: str, delta: float, *, event_ref: str, source_type: str = "SYSTEM") -> dict[str, Any]:
        self._validate_profile(profile_ref)
        if not isinstance(delta, (int, float)) or isinstance(delta, bool) or not math.isfinite(float(delta)) or float(delta) == 0.0:
            raise ValidationError("resource delta must be finite and non-zero")
        delta = round(float(delta), 6)
        source_type = str(source_type).strip().upper() or "SYSTEM"
        payload = {"delta": delta, "source_type": source_type}
        existing = self._event_existing(str(event_ref).strip())
        if existing:
            h = self._event_hash(profile_ref, str(event_ref).strip(), "RESOURCE_CHANGE", payload)
            if existing["event_hash"] != h:
                raise ConflictError("CHARACTER_EVENT_REF_CONFLICT")
            out = json.loads(existing["result_json"])
            out["idempotent_replay"] = True
            return out
        state = self.state(profile_ref)
        before = float(state["vitals"]["resource"])
        after = min(float(state["derived"]["max_resource"]), max(0.0, before + delta))
        state["vitals"]["resource"] = round(after, 6)
        self._save(state)
        result = {"status": "PASS", "profile_ref": profile_ref, "resource_before": before, "resource_after": after, "applied_delta": round(after - before, 6), "idempotent_replay": False}
        return self._record_event(profile_ref, event_ref, "RESOURCE_CHANGE", payload, result)

    def tick_profile(self, profile_ref: str, delta_s: float) -> dict[str, Any]:
        if not isinstance(delta_s, (int, float)) or isinstance(delta_s, bool) or not math.isfinite(float(delta_s)) or delta_s <= 0 or delta_s > 1.0:
            raise ValidationError("delta_s must be in (0,1]")
        state = self.ensure_profile(profile_ref)
        if state["vitals"]["life_state"] != "ALIVE":
            return {"status": "PASS", "life_state": "DEAD", "changed": False}
        health = float(state["vitals"]["health"])
        resource = float(state["vitals"]["resource"])
        max_health = float(state["derived"]["max_health"])
        max_resource = float(state["derived"]["max_resource"])
        nh = min(max_health, health + float(state["derived"]["health_regen_per_s"]) * float(delta_s))
        nr = min(max_resource, resource + float(state["derived"]["resource_regen_per_s"]) * float(delta_s))
        changed = abs(nh - health) > 1e-9 or abs(nr - resource) > 1e-9
        if changed:
            state["vitals"]["health"] = round(nh, 6)
            state["vitals"]["resource"] = round(nr, 6)
            self._save(state)
        return {"status": "PASS", "life_state": "ALIVE", "changed": changed, "health": round(nh, 6), "resource": round(nr, 6)}

    def can_act(self, profile_ref: str) -> dict[str, Any]:
        state = self.ensure_profile(profile_ref)
        if state["vitals"]["life_state"] != "ALIVE":
            return {"status": "REJECTED", "reason": "CHARACTER_DEAD", "life_state": state["vitals"]["life_state"]}
        return {"status": "PASS", "life_state": "ALIVE"}

    def event_history(self, profile_ref: str) -> list[dict[str, Any]]:
        rows = self.runtime.conn.execute(
            "SELECT server_sequence,event_ref,event_type,payload_json,result_json,event_hash FROM arpg_character_events WHERE world_instance_id=? AND profile_ref=? ORDER BY server_sequence",
            (self.world_instance_id, profile_ref),
        ).fetchall()
        return [{"server_sequence": r["server_sequence"], "event_ref": r["event_ref"], "event_type": r["event_type"], "payload": json.loads(r["payload_json"]), "result": json.loads(r["result_json"]), "event_hash": r["event_hash"]} for r in rows]

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        profiles = self.engine.arpg(self.world_instance_id).list_profiles()
        for p in profiles:
            try:
                state = self.state(p["profile_ref"])
            except Exception:
                failures.append("CHARACTER_STATE_MISSING_OR_CORRUPT:" + p["profile_ref"])
                continue
            if state.get("avatar_ref") != p.get("avatar_ref"):
                failures.append("CHARACTER_AVATAR_BINDING:" + p["profile_ref"])
            level = state.get("level")
            if not isinstance(level, int) or not (1 <= level <= self.LEVEL_CAP):
                failures.append("LEVEL_RANGE:" + p["profile_ref"])
            attrs = state.get("attributes", {})
            for key in CORE_ATTRIBUTES:
                val = attrs.get(key)
                if not isinstance(val, int) or isinstance(val, bool) or not (self.BASE_ATTRIBUTE <= val <= self.MAX_ATTRIBUTE_VALUE):
                    failures.append("ATTRIBUTE_RANGE:" + p["profile_ref"] + ":" + key)
            if state.get("derived") != self.derived_stats(attrs, level):
                failures.append("DERIVED_STATS_DIVERGENCE:" + p["profile_ref"])
            vitals = state.get("vitals", {})
            if vitals.get("life_state") not in LIFE_STATES:
                failures.append("LIFE_STATE:" + p["profile_ref"])
            if not (0.0 <= float(vitals.get("health", -1)) <= float(state["derived"]["max_health"])):
                failures.append("HEALTH_RANGE:" + p["profile_ref"])
            if not (0.0 <= float(vitals.get("resource", -1)) <= float(state["derived"]["max_resource"])):
                failures.append("RESOURCE_RANGE:" + p["profile_ref"])
            expected_into = 0 if level >= self.LEVEL_CAP else int(state["experience"]) - self.cumulative_xp_for_level(level)
            if int(state.get("experience_into_level", -1)) != expected_into:
                failures.append("XP_LEVEL_DIVERGENCE:" + p["profile_ref"])
            invested = sum(int(v) for v in state["build_evidence"]["attribute_investment"].values())
            levels_points = (int(level) - 1) * self.ATTRIBUTE_POINTS_PER_LEVEL
            if invested + int(state["unspent_attribute_points"]) != levels_points:
                failures.append("ATTRIBUTE_POINT_LEDGER:" + p["profile_ref"])
        rows = self.runtime.conn.execute(
            "SELECT profile_ref,event_ref,event_type,payload_json,event_hash FROM arpg_character_events WHERE world_instance_id=?",
            (self.world_instance_id,),
        ).fetchall()
        for r in rows:
            payload = json.loads(r["payload_json"])
            expected = self._event_hash(r["profile_ref"], r["event_ref"], r["event_type"], payload)
            if expected != r["event_hash"]:
                failures.append("CHARACTER_EVENT_HASH:" + r["event_ref"])
        return {
            "status": "PASS" if not failures else "FAIL",
            "failures": failures,
            "profiles": len(profiles),
            "events": len(rows),
            "level_cap": self.LEVEL_CAP,
            "attributes": list(CORE_ATTRIBUTES),
            "numeric_authority": "GAMEPLAY_DERIVED_NOT_CANON",
            "art_dependency": "NONE_PLACEHOLDER_READY",
            "authority": self.AUTHORITY,
        }
