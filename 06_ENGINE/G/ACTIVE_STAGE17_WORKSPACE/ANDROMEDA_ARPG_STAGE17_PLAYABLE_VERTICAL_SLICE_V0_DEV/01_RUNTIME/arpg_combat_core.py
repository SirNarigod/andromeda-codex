from __future__ import annotations

import copy
import hashlib
import json
import math
import unicodedata
from typing import Any

from living_runtime import ValidationError, ConflictError, IntegrityError, canonical_json, sha256_text


DAMAGE_TYPES = ("PHYSICAL", "FIRE", "COLD", "LIGHTNING", "TOXIC", "ARCANE")
PLAYER_ATTACK_STYLE = "BASIC_ATTACK_PLACEHOLDER"
TIER_LEVELS = {"BAIXO": 1, "MEDIO": 5, "ALTO": 10}


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return text.upper().strip()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


class ARPGCombatCore:
    """Stage 03 server-authoritative deterministic ARPG combat core.

    Player HP remains owned exclusively by CharacterCore. NPC/enemy HP is a gameplay-derived
    overlay and never mutates Master canon. Item bonuses and skills are intentionally absent;
    Stage 05 and Stage 07 layer them on top of these formulas.
    """

    VERSION = "V0.4.0"
    STAGE = "03/18"
    AUTHORITY = "ARPG_COMBAT_CORE_GAMEPLAY_DERIVATION"
    FORMULA_VERSION = "ARPG_COMBAT_FORMULAS_V0_4_0"
    BASIC_RANGE_M = 2.75
    PVP_ENABLED = False
    MAX_RESIST = 75.0
    MIN_RESIST = -50.0
    MAX_ARMOR_MITIGATION = 0.75
    MIN_HIT_CHANCE = 20.0
    MAX_HIT_CHANCE = 98.0
    MAX_CRIT_CHANCE = 50.0
    MAX_STATUS_DURATION_S = 60.0
    MAX_STATUS_DPS = 10000.0

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
                CREATE TABLE IF NOT EXISTS arpg_combat_overlay(
                    world_instance_id TEXT NOT NULL,
                    actor_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, actor_ref)
                );
                CREATE TABLE IF NOT EXISTS arpg_enemy_combat_state(
                    world_instance_id TEXT NOT NULL,
                    actor_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, actor_ref)
                );
                CREATE TABLE IF NOT EXISTS arpg_combat_events(
                    server_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    world_instance_id TEXT NOT NULL,
                    event_ref TEXT NOT NULL,
                    attacker_ref TEXT NOT NULL,
                    target_ref TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id, event_ref)
                );
                CREATE INDEX IF NOT EXISTS idx_arpg_combat_events_actor
                    ON arpg_combat_events(world_instance_id, attacker_ref, server_sequence);
                """
            )
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('arpg_combat_core_version',?)",
                (self.VERSION,),
            )

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> tuple[str, str]:
        text = canonical_json(payload)
        return text, sha256_text(text)

    def _save_row(self, table: str, actor_ref: str, payload: dict[str, Any]) -> None:
        if table not in {"arpg_combat_overlay", "arpg_enemy_combat_state"}:
            raise IntegrityError("invalid combat table")
        text, h = self._hash_payload(payload)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                f"INSERT OR REPLACE INTO {table}(world_instance_id,actor_ref,payload_json,payload_hash) VALUES(?,?,?,?)",
                (self.world_instance_id, actor_ref, text, h),
            )

    def _load_row(self, table: str, actor_ref: str) -> dict[str, Any] | None:
        row = self.runtime.conn.execute(
            f"SELECT payload_json,payload_hash FROM {table} WHERE world_instance_id=? AND actor_ref=?",
            (self.world_instance_id, actor_ref),
        ).fetchone()
        if not row:
            return None
        if sha256_text(row["payload_json"]) != row["payload_hash"]:
            raise IntegrityError("ARPG combat state hash mismatch")
        return json.loads(row["payload_json"])

    def _profile_for_avatar(self, avatar_ref: str) -> dict[str, Any] | None:
        row = self.runtime.conn.execute(
            "SELECT profile_ref FROM arpg_player_profiles WHERE world_instance_id=? AND avatar_ref=?",
            (self.world_instance_id, avatar_ref),
        ).fetchone()
        return self.engine.arpg(self.world_instance_id).profile(row["profile_ref"]) if row else None

    def _base_overlay(self, actor_ref: str, actor_kind: str, profile_ref: str | None = None) -> dict[str, Any]:
        return {
            "actor_ref": actor_ref,
            "actor_kind": actor_kind,
            "profile_ref": profile_ref,
            "attack_cooldown_remaining_s": 0.0,
            "stagger_remaining_s": 0.0,
            "statuses": [],
            "last_target_ref": None,
            "combat_state": "READY",
            "formula_version": self.FORMULA_VERSION,
            "authority": self.AUTHORITY,
        }

    def ensure_player(self, profile_ref: str) -> dict[str, Any]:
        profile = self.engine.arpg(self.world_instance_id).profile(profile_ref)
        self.engine.character(self.world_instance_id).ensure_profile(profile_ref)
        actor_ref = profile["avatar_ref"]
        overlay = self._load_row("arpg_combat_overlay", actor_ref)
        if overlay is None:
            overlay = self._base_overlay(actor_ref, "PLAYER", profile_ref)
            self._save_row("arpg_combat_overlay", actor_ref, overlay)
        return copy.deepcopy(overlay)

    def bootstrap_existing_profiles(self) -> None:
        try:
            profiles = self.engine.arpg(self.world_instance_id).list_profiles()
        except Exception:
            return
        for profile in profiles:
            self.ensure_player(profile["profile_ref"])

    def _npc(self, actor_ref: str) -> dict[str, Any]:
        try:
            npc = self.engine.country(self.world_instance_id).npc(actor_ref)
        except KeyError as exc:
            raise ValidationError("unknown combat actor") from exc
        return npc

    @classmethod
    def _tier_level(cls, npc: dict[str, Any]) -> int:
        return TIER_LEVELS.get(_norm(npc.get("tier")), 1)

    def ensure_enemy(self, actor_ref: str) -> dict[str, Any]:
        if self._profile_for_avatar(actor_ref) is not None:
            raise ValidationError("player avatars do not use enemy combat state")
        npc = self._npc(actor_ref)
        if str(npc.get("status", "ACTIVE")).upper() != "ACTIVE":
            raise ConflictError("TARGET_NOT_ACTIVE")
        state = self._load_row("arpg_enemy_combat_state", actor_ref)
        if state is not None:
            return copy.deepcopy(state)
        level = self._tier_level(npc)
        cls = _norm(npc.get("class")) or "NPC"
        class_seed = int(hashlib.sha256(cls.encode("utf-8")).hexdigest()[:8], 16)
        max_health = float(70 + level * 18 + class_seed % 21)
        armor = float(8 + level * 2 + class_seed % 7)
        evasion = float(8 + level * 1.2 + class_seed % 5)
        state = {
            "actor_ref": actor_ref,
            "actor_kind": "NPC_COMBAT_TARGET",
            "source_class": npc.get("class"),
            "source_tier": npc.get("tier"),
            "level": level,
            "life_state": "ALIVE",
            "health": max_health,
            "max_health": max_health,
            "armor": armor,
            "evasion": evasion,
            "accuracy": float(70 + level * 4 + class_seed % 11),
            "base_damage": float(7 + level * 3 + class_seed % 6),
            "crit_chance_pct": float(4 + class_seed % 5),
            "crit_multiplier": 1.5,
            "resistances": {d: 0.0 for d in DAMAGE_TYPES if d != "PHYSICAL"},
            "stagger_threshold": float(max_health * 0.18),
            "xp_reward": int(20 + level * 15),
            "protected_identity": bool((npc.get("protection") or {}).get("protected", False)),
            "combat_targetable": bool((npc.get("protection") or {}).get("combat_targetable", True)),
            "hostility_authority": "DEFERRED_STAGE08_EXPLICIT_COMBAT_INTENT_REQUIRED",
            "permanent_death": "BLOCKED_STAGE03",
            "formula_version": self.FORMULA_VERSION,
            "authority": "GAMEPLAY_DERIVED_NOT_CANON",
        }
        self._save_row("arpg_enemy_combat_state", actor_ref, state)
        if self._load_row("arpg_combat_overlay", actor_ref) is None:
            self._save_row("arpg_combat_overlay", actor_ref, self._base_overlay(actor_ref, "NPC"))
        return copy.deepcopy(state)

    def overlay(self, actor_ref: str) -> dict[str, Any]:
        ov = self._load_row("arpg_combat_overlay", actor_ref)
        if ov is None:
            profile = self._profile_for_avatar(actor_ref)
            if profile:
                return self.ensure_player(profile["profile_ref"])
            self.ensure_enemy(actor_ref)
            ov = self._load_row("arpg_combat_overlay", actor_ref)
        return copy.deepcopy(ov)

    def _save_overlay(self, overlay: dict[str, Any]) -> None:
        self._save_row("arpg_combat_overlay", overlay["actor_ref"], overlay)

    def player_stats(self, profile_ref: str) -> dict[str, Any]:
        state = self.engine.character(self.world_instance_id).ensure_profile(profile_ref)
        attrs = state["attributes"]
        derived = state["derived"]
        level = int(state["level"])
        armor = float(derived["resilience_potential"]) * 0.55 + level * 0.5
        evasion = float(attrs["AGILITY"]) * 1.2 + float(attrs["PERCEPTION"]) * 0.6 + level * 0.25
        accuracy = float(derived["precision_potential"]) * 3.5 + level * 2.0
        base_damage = 8.0 + float(derived["power_potential"]) * 0.55 + level * 0.8
        crit_chance = _clamp(5.0 + float(attrs["PERCEPTION"]) * 0.22 + float(attrs["AGILITY"]) * 0.10, 0.0, self.MAX_CRIT_CHANCE)
        crit_multiplier = 1.50 + min(0.50, float(attrs["AGILITY"]) * 0.005)
        attacks_per_second = 1.15 + min(1.35, float(attrs["AGILITY"]) * 0.015)
        resistances = {d: 0.0 for d in DAMAGE_TYPES if d != "PHYSICAL"}
        range_m = self.BASIC_RANGE_M
        equipment_modifiers: Any = "DEFERRED_STAGE05"
        try:
            eq = self.engine.items_arpg(self.world_instance_id).equipment_modifiers(profile_ref)
            mods = eq.get("modifiers") or {}
            base_damage = (base_damage + float(mods.get("damage_flat", 0.0))) * (1.0 + float(mods.get("damage_pct", 0.0)) / 100.0)
            armor += float(mods.get("armor_flat", 0.0))
            evasion += float(mods.get("evasion_flat", 0.0))
            accuracy += float(mods.get("accuracy_flat", 0.0))
            crit_chance = _clamp(crit_chance + float(mods.get("crit_chance_pct", 0.0)), 0.0, self.MAX_CRIT_CHANCE)
            attacks_per_second = max(0.1, attacks_per_second * (1.0 + float(mods.get("attack_speed_pct", 0.0)) / 100.0))
            range_m = max(0.5, range_m + float(mods.get("range_bonus_m", 0.0)))
            for dt, value in (mods.get("resistances") or {}).items():
                if dt in resistances:
                    resistances[dt] = float(resistances[dt]) + float(value)
            equipment_modifiers = eq
        except (AttributeError, KeyError):
            pass
        skill_modifiers: Any = "DEFERRED_STAGE07"
        try:
            sk = self.engine.skills_arpg(self.world_instance_id).combat_modifiers(profile_ref)
            smods = sk.get("modifiers") or {}
            base_damage = (base_damage + float(smods.get("damage_flat", 0.0))) * (1.0 + float(smods.get("damage_pct", 0.0)) / 100.0)
            armor += float(smods.get("armor_flat", 0.0))
            evasion += float(smods.get("evasion_flat", 0.0))
            accuracy += float(smods.get("accuracy_flat", 0.0))
            crit_chance = _clamp(crit_chance + float(smods.get("crit_chance_pct", 0.0)), 0.0, self.MAX_CRIT_CHANCE)
            attacks_per_second = max(0.1, attacks_per_second * (1.0 + float(smods.get("attack_speed_pct", 0.0)) / 100.0))
            range_m = max(0.5, range_m + float(smods.get("range_bonus_m", 0.0)))
            for dt, value in (smods.get("resistances") or {}).items():
                if dt in resistances:
                    resistances[dt] = float(resistances[dt]) + float(value)
            skill_modifiers = sk
        except (AttributeError, KeyError):
            pass
        return {
            "level": level,
            "armor": round(armor, 6),
            "evasion": round(evasion, 6),
            "accuracy": round(accuracy, 6),
            "base_damage": round(base_damage, 6),
            "crit_chance_pct": round(crit_chance, 6),
            "crit_multiplier": round(crit_multiplier, 6),
            "attacks_per_second": round(attacks_per_second, 6),
            "attack_interval_s": round(1.0 / attacks_per_second, 6),
            "resistances": {d: round(float(v), 6) for d, v in resistances.items()},
            "range_m": round(range_m, 6),
            "equipment_modifiers": equipment_modifiers,
            "skill_modifiers": skill_modifiers,
            "formula_version": self.FORMULA_VERSION,
            "authority": "GAMEPLAY_DERIVED_NOT_CANON",
        }

    @staticmethod
    def _armor_mitigation(armor: float, attacker_level: int) -> float:
        armor = max(0.0, float(armor))
        return min(ARPGCombatCore.MAX_ARMOR_MITIGATION, armor / (armor + 100.0 + max(1, int(attacker_level)) * 10.0))

    @classmethod
    def _resistance_mitigation(cls, resistance: float) -> float:
        return _clamp(float(resistance), cls.MIN_RESIST, cls.MAX_RESIST) / 100.0

    def _stable_roll(self, event_ref: str, channel: str) -> float:
        # Runtime world IDs are intentionally unique UUIDs. They must not perturb gameplay RNG.
        # The simulation seed + immutable event reference + roll channel define deterministic outcomes.
        world = self.runtime.get_world(self.world_instance_id)
        world_seed = int(world["seed"])
        digest = hashlib.sha256(f"{world_seed}|{event_ref}|{channel}".encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") / float(2**64 - 1)

    def _distance(self, actor_ref: str, target_ref: str) -> float:
        mover = self.engine.movement(self.world_instance_id)
        a = mover.state(actor_ref)
        b = mover.state(target_ref)
        return math.hypot(float(a["iso_x_m"]) - float(b["iso_x_m"]), float(a["iso_y_m"]) - float(b["iso_y_m"]))

    def _event_existing(self, event_ref: str):
        return self.runtime.conn.execute(
            "SELECT * FROM arpg_combat_events WHERE world_instance_id=? AND event_ref=?",
            (self.world_instance_id, event_ref),
        ).fetchone()

    def _event_hash(self, attacker_ref: str, target_ref: str, event_type: str, payload: dict[str, Any]) -> str:
        return sha256_text(canonical_json({
            "attacker_ref": attacker_ref, "target_ref": target_ref,
            "event_type": event_type, "payload": payload,
        }))

    def _existing_or_none(self, event_ref: str, attacker_ref: str, target_ref: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        event_ref = str(event_ref).strip()
        if not event_ref or len(event_ref) > 180:
            raise ValidationError("event_ref must contain 1-180 characters")
        row = self._event_existing(event_ref)
        if not row:
            return None
        h = self._event_hash(attacker_ref, target_ref, event_type, payload)
        if row["event_hash"] != h:
            raise ConflictError("COMBAT_EVENT_REF_CONFLICT")
        out = json.loads(row["result_json"])
        out["idempotent_replay"] = True
        return out

    def _record_event(self, event_ref: str, attacker_ref: str, target_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        h = self._event_hash(attacker_ref, target_ref, event_type, payload)
        with self.runtime._write_lock:
            cur = self.runtime.conn.execute(
                "INSERT INTO arpg_combat_events(world_instance_id,event_ref,attacker_ref,target_ref,event_type,payload_json,result_json,event_hash) VALUES(?,?,?,?,?,?,?,?)",
                (self.world_instance_id, event_ref, attacker_ref, target_ref, event_type, canonical_json(payload), canonical_json(result), h),
            )
            seq = cur.lastrowid
        out = copy.deepcopy(result)
        out["combat_server_sequence"] = seq
        return out

    def _rejected(self, event_ref: str, attacker_ref: str, target_ref: str, event_type: str, payload: dict[str, Any], reason: str, **extra: Any) -> dict[str, Any]:
        result = {"status": "REJECTED", "reason": reason, "idempotent_replay": False, **extra}
        return self._record_event(event_ref, attacker_ref, target_ref, event_type, payload, result)

    def can_player_act(self, profile_ref: str) -> dict[str, Any]:
        profile = self.engine.arpg(self.world_instance_id).profile(profile_ref)
        char_gate = self.engine.character(self.world_instance_id).can_act(profile_ref)
        if char_gate.get("status") != "PASS":
            return char_gate
        ov = self.ensure_player(profile_ref)
        if float(ov.get("stagger_remaining_s", 0.0)) > 1e-9:
            return {"status": "REJECTED", "reason": "COMBAT_STAGGERED", "remaining_s": ov["stagger_remaining_s"], "life_state": "ALIVE"}
        return {"status": "PASS", "life_state": "ALIVE", "actor_ref": profile["avatar_ref"]}

    def _resolve_damage(self, *, raw_damage: float, damage_type: str, attacker_level: int, target_armor: float, target_resistance: float, critical: bool, crit_multiplier: float) -> dict[str, float]:
        damage_type = str(damage_type).upper()
        if damage_type not in DAMAGE_TYPES:
            raise ValidationError("unsupported damage type")
        premit = float(raw_damage) * (float(crit_multiplier) if critical else 1.0)
        if damage_type == "PHYSICAL":
            mitigation = self._armor_mitigation(target_armor, attacker_level)
        else:
            mitigation = self._resistance_mitigation(target_resistance)
        final = max(0.1, premit * (1.0 - mitigation))
        return {"raw": round(float(raw_damage), 6), "pre_mitigation": round(premit, 6), "mitigation_pct": round(mitigation * 100.0, 6), "final": round(final, 6)}

    def player_attack(self, profile_ref: str, target_ref: str, *, event_ref: str, damage_type: str = "PHYSICAL") -> dict[str, Any]:
        profile = self.engine.arpg(self.world_instance_id).profile(profile_ref)
        actor_ref = profile["avatar_ref"]
        damage_type = str(damage_type).upper().strip()
        if damage_type not in DAMAGE_TYPES:
            raise ValidationError("unsupported damage type")
        payload = {"profile_ref": profile_ref, "damage_type": damage_type, "attack_style": PLAYER_ATTACK_STYLE}
        existing = self._existing_or_none(event_ref, actor_ref, target_ref, "PLAYER_ATTACK", payload)
        if existing is not None:
            return existing
        gate = self.can_player_act(profile_ref)
        if gate.get("status") != "PASS":
            return self._rejected(event_ref, actor_ref, target_ref, "PLAYER_ATTACK", payload, gate.get("reason", "CHARACTER_CANNOT_ACT"))
        if self._profile_for_avatar(target_ref) is not None:
            if not self.PVP_ENABLED:
                return self._rejected(event_ref, actor_ref, target_ref, "PLAYER_ATTACK", payload, "PVP_DISABLED")
        enemy = self.ensure_enemy(target_ref)
        if not enemy.get("combat_targetable", True):
            return self._rejected(event_ref, actor_ref, target_ref, "PLAYER_ATTACK", payload, "TARGET_NOT_COMBAT_TARGETABLE")
        if enemy["life_state"] != "ALIVE":
            return self._rejected(event_ref, actor_ref, target_ref, "PLAYER_ATTACK", payload, "TARGET_ALREADY_DEFEATED")
        overlay = self.ensure_player(profile_ref)
        if float(overlay.get("attack_cooldown_remaining_s", 0.0)) > 1e-9:
            return self._rejected(event_ref, actor_ref, target_ref, "PLAYER_ATTACK", payload, "ATTACK_COOLDOWN", remaining_s=round(float(overlay["attack_cooldown_remaining_s"]), 6))
        distance = self._distance(actor_ref, target_ref)
        stats = self.player_stats(profile_ref)
        if distance > float(stats["range_m"]) + 1e-9:
            return self._rejected(event_ref, actor_ref, target_ref, "PLAYER_ATTACK", payload, "TARGET_OUT_OF_RANGE", distance_m=round(distance, 6), range_m=stats["range_m"])

        hit_chance = _clamp(75.0 + (float(stats["accuracy"]) - float(enemy["evasion"])) * 0.18, self.MIN_HIT_CHANCE, self.MAX_HIT_CHANCE)
        hit_roll = self._stable_roll(event_ref, "HIT") * 100.0
        hit = hit_roll < hit_chance
        crit_chance = min(self.MAX_CRIT_CHANCE, float(stats["crit_chance_pct"]))
        crit_roll = self._stable_roll(event_ref, "CRIT") * 100.0
        critical = bool(hit and crit_roll < crit_chance)
        damage = {"raw": 0.0, "pre_mitigation": 0.0, "mitigation_pct": 0.0, "final": 0.0}
        before = float(enemy["health"])
        after = before
        staggered = False
        protected_defeat = False
        lethal = False
        xp = None
        if hit:
            damage = self._resolve_damage(
                raw_damage=float(stats["base_damage"]), damage_type=damage_type, attacker_level=int(stats["level"]),
                target_armor=float(enemy["armor"]), target_resistance=float(enemy["resistances"].get(damage_type, 0.0)),
                critical=critical, crit_multiplier=float(stats["crit_multiplier"]),
            )
            after = max(0.0, before - float(damage["final"]))
            if after <= 0.0:
                if enemy.get("protected_identity"):
                    after = 1.0
                    protected_defeat = True
                else:
                    after = 0.0
                    lethal = True
                    enemy["life_state"] = "DEFEATED"
            enemy["health"] = round(after, 6)
            self._save_row("arpg_enemy_combat_state", target_ref, enemy)
            if float(damage["final"]) >= float(enemy["stagger_threshold"]):
                tov = self.overlay(target_ref)
                tov["stagger_remaining_s"] = max(float(tov.get("stagger_remaining_s", 0.0)), 0.35)
                tov["combat_state"] = "STAGGERED"
                self._save_overlay(tov)
                staggered = True
            if lethal:
                xp = self.engine.character(self.world_instance_id).award_experience(
                    profile_ref, int(enemy["xp_reward"]), event_ref=f"{event_ref}:XP", source_type="COMBAT_STAGE03"
                )
        overlay["attack_cooldown_remaining_s"] = float(stats["attack_interval_s"])
        overlay["last_target_ref"] = target_ref
        overlay["combat_state"] = "RECOVERY"
        self._save_overlay(overlay)
        result = {
            "status": "PASS", "event_ref": event_ref, "attacker_ref": actor_ref, "target_ref": target_ref,
            "attack_style": PLAYER_ATTACK_STYLE, "damage_type": damage_type,
            "distance_m": round(distance, 6), "range_m": stats["range_m"],
            "hit_chance_pct": round(hit_chance, 6), "hit_roll_pct": round(hit_roll, 6), "hit": hit,
            "crit_chance_pct": round(crit_chance, 6), "crit_roll_pct": round(crit_roll, 6), "critical": critical,
            "damage": damage, "health_before": round(before, 6), "health_after": round(after, 6),
            "staggered": staggered, "lethal": lethal, "protected_defeat_blocked": protected_defeat,
            "xp": xp, "cooldown_s": stats["attack_interval_s"], "formula_version": self.FORMULA_VERSION,
            "idempotent_replay": False, "authority": self.AUTHORITY,
        }
        return self._record_event(event_ref, actor_ref, target_ref, "PLAYER_ATTACK", payload, result)

    def preview_player_skill_attack(self, profile_ref: str, target_ref: str, *, range_bonus_m: float = 0.0) -> dict[str, Any]:
        profile = self.engine.arpg(self.world_instance_id).profile(profile_ref)
        actor_ref = profile["avatar_ref"]
        gate = self.can_player_act(profile_ref)
        if gate.get("status") != "PASS":
            return gate
        if self._profile_for_avatar(target_ref) is not None and not self.PVP_ENABLED:
            return {"status": "REJECTED", "reason": "PVP_DISABLED"}
        try:
            enemy = self.ensure_enemy(target_ref)
        except Exception:
            return {"status": "REJECTED", "reason": "INVALID_COMBAT_TARGET"}
        if not enemy.get("combat_targetable", True):
            return {"status": "REJECTED", "reason": "TARGET_NOT_COMBAT_TARGETABLE"}
        if enemy["life_state"] != "ALIVE":
            return {"status": "REJECTED", "reason": "TARGET_ALREADY_DEFEATED"}
        overlay = self.ensure_player(profile_ref)
        if float(overlay.get("attack_cooldown_remaining_s", 0.0)) > 1e-9:
            return {"status": "REJECTED", "reason": "ATTACK_RECOVERY", "remaining_s": round(float(overlay["attack_cooldown_remaining_s"]), 6)}
        stats = self.player_stats(profile_ref)
        distance = self._distance(actor_ref, target_ref)
        range_m = max(0.5, float(stats["range_m"]) + float(range_bonus_m))
        if distance > range_m + 1e-9:
            return {"status": "REJECTED", "reason": "TARGET_OUT_OF_RANGE", "distance_m": round(distance, 6), "range_m": round(range_m, 6)}
        return {"status": "PASS", "actor_ref": actor_ref, "target_ref": target_ref, "distance_m": round(distance, 6), "range_m": round(range_m, 6)}

    def player_skill_attack(
        self, profile_ref: str, target_ref: str, *, event_ref: str, skill_ref: str,
        damage_type: str, power_multiplier: float = 1.0, range_bonus_m: float = 0.0,
        accuracy_bonus: float = 0.0, crit_bonus_pct: float = 0.0, recovery_s: float = 0.0,
    ) -> dict[str, Any]:
        profile = self.engine.arpg(self.world_instance_id).profile(profile_ref)
        actor_ref = profile["avatar_ref"]
        damage_type = str(damage_type).upper().strip()
        if damage_type not in DAMAGE_TYPES:
            raise ValidationError("unsupported damage type")
        power_multiplier = float(power_multiplier); range_bonus_m = float(range_bonus_m)
        accuracy_bonus = float(accuracy_bonus); crit_bonus_pct = float(crit_bonus_pct); recovery_s = float(recovery_s)
        if not all(math.isfinite(v) for v in (power_multiplier, range_bonus_m, accuracy_bonus, crit_bonus_pct, recovery_s)):
            raise ValidationError("non-finite skill attack parameter")
        if power_multiplier <= 0 or power_multiplier > 20 or range_bonus_m < -10 or range_bonus_m > 100 or recovery_s < 0 or recovery_s > 10:
            raise ValidationError("skill attack parameter out of range")
        payload = {"profile_ref": profile_ref, "skill_ref": str(skill_ref), "damage_type": damage_type, "power_multiplier": round(power_multiplier,6), "range_bonus_m": round(range_bonus_m,6), "accuracy_bonus": round(accuracy_bonus,6), "crit_bonus_pct": round(crit_bonus_pct,6), "recovery_s": round(recovery_s,6)}
        existing = self._existing_or_none(event_ref, actor_ref, target_ref, "PLAYER_SKILL_ATTACK", payload)
        if existing is not None:
            return existing
        pre = self.preview_player_skill_attack(profile_ref, target_ref, range_bonus_m=range_bonus_m)
        if pre.get("status") != "PASS":
            return self._rejected(event_ref, actor_ref, target_ref, "PLAYER_SKILL_ATTACK", payload, pre.get("reason", "SKILL_ATTACK_PRECHECK"), precheck=pre)
        enemy = self.ensure_enemy(target_ref)
        stats = self.player_stats(profile_ref)
        distance = float(pre["distance_m"]); range_m = float(pre["range_m"])
        hit_chance = _clamp(75.0 + (float(stats["accuracy"]) + accuracy_bonus - float(enemy["evasion"])) * 0.18, self.MIN_HIT_CHANCE, self.MAX_HIT_CHANCE)
        hit_roll = self._stable_roll(event_ref, "SKILL_HIT") * 100.0
        hit = hit_roll < hit_chance
        crit_chance = min(self.MAX_CRIT_CHANCE, max(0.0, float(stats["crit_chance_pct"]) + crit_bonus_pct))
        crit_roll = self._stable_roll(event_ref, "SKILL_CRIT") * 100.0
        critical = bool(hit and crit_roll < crit_chance)
        damage = {"raw":0.0,"pre_mitigation":0.0,"mitigation_pct":0.0,"final":0.0}
        before = float(enemy["health"]); after = before; lethal=False; protected_defeat=False; staggered=False; xp=None
        if hit:
            damage = self._resolve_damage(raw_damage=float(stats["base_damage"])*power_multiplier, damage_type=damage_type, attacker_level=int(stats["level"]), target_armor=float(enemy["armor"]), target_resistance=float(enemy["resistances"].get(damage_type,0.0)), critical=critical, crit_multiplier=float(stats["crit_multiplier"]))
            after=max(0.0,before-float(damage["final"]))
            if after<=0.0:
                if enemy.get("protected_identity"):
                    after=1.0; protected_defeat=True
                else:
                    after=0.0; lethal=True; enemy["life_state"]="DEFEATED"
            enemy["health"]=round(after,6); self._save_row("arpg_enemy_combat_state",target_ref,enemy)
            if float(damage["final"]) >= float(enemy["stagger_threshold"]):
                tov=self.overlay(target_ref); tov["stagger_remaining_s"]=max(float(tov.get("stagger_remaining_s",0.0)),0.35); tov["combat_state"]="STAGGERED"; self._save_overlay(tov); staggered=True
            if lethal:
                xp=self.engine.character(self.world_instance_id).award_experience(profile_ref,int(enemy["xp_reward"]),event_ref=f"{event_ref}:XP",source_type="COMBAT_SKILL_STAGE06")
        overlay=self.ensure_player(profile_ref); overlay["attack_cooldown_remaining_s"]=max(float(overlay.get("attack_cooldown_remaining_s",0.0)),recovery_s); overlay["last_target_ref"]=target_ref; overlay["combat_state"]="RECOVERY"; self._save_overlay(overlay)
        result={"status":"PASS","event_ref":event_ref,"attacker_ref":actor_ref,"target_ref":target_ref,"skill_ref":str(skill_ref),"damage_type":damage_type,"distance_m":round(distance,6),"range_m":round(range_m,6),"hit_chance_pct":round(hit_chance,6),"hit_roll_pct":round(hit_roll,6),"hit":hit,"crit_chance_pct":round(crit_chance,6),"crit_roll_pct":round(crit_roll,6),"critical":critical,"damage":damage,"health_before":round(before,6),"health_after":round(after,6),"staggered":staggered,"lethal":lethal,"protected_defeat_blocked":protected_defeat,"xp":xp,"recovery_s":round(recovery_s,6),"formula_version":self.FORMULA_VERSION,"idempotent_replay":False,"authority":self.AUTHORITY}
        return self._record_event(event_ref, actor_ref, target_ref, "PLAYER_SKILL_ATTACK", payload, result)

    def enemy_attack_player(self, attacker_ref: str, target_profile_ref: str, *, event_ref: str, damage_type: str = "PHYSICAL") -> dict[str, Any]:
        target_profile = self.engine.arpg(self.world_instance_id).profile(target_profile_ref)
        target_ref = target_profile["avatar_ref"]
        damage_type = str(damage_type).upper().strip()
        if damage_type not in DAMAGE_TYPES:
            raise ValidationError("unsupported damage type")
        payload = {"target_profile_ref": target_profile_ref, "damage_type": damage_type, "attack_style": "ENEMY_BASIC_ATTACK"}
        existing = self._existing_or_none(event_ref, attacker_ref, target_ref, "ENEMY_ATTACK", payload)
        if existing is not None:
            return existing
        enemy = self.ensure_enemy(attacker_ref)
        if enemy["life_state"] != "ALIVE":
            return self._rejected(event_ref, attacker_ref, target_ref, "ENEMY_ATTACK", payload, "ATTACKER_DEFEATED")
        target_state = self.engine.character(self.world_instance_id).ensure_profile(target_profile_ref)
        if target_state["vitals"]["life_state"] != "ALIVE":
            return self._rejected(event_ref, attacker_ref, target_ref, "ENEMY_ATTACK", payload, "TARGET_DEAD")
        aov = self.overlay(attacker_ref)
        if float(aov.get("stagger_remaining_s", 0.0)) > 1e-9:
            return self._rejected(event_ref, attacker_ref, target_ref, "ENEMY_ATTACK", payload, "ATTACKER_STAGGERED")
        distance = self._distance(attacker_ref, target_ref)
        if distance > self.BASIC_RANGE_M + 1e-9:
            return self._rejected(event_ref, attacker_ref, target_ref, "ENEMY_ATTACK", payload, "TARGET_OUT_OF_RANGE", distance_m=round(distance, 6), range_m=self.BASIC_RANGE_M)
        pstats = self.player_stats(target_profile_ref)
        hit_chance = _clamp(75.0 + (float(enemy["accuracy"]) - float(pstats["evasion"])) * 0.18, self.MIN_HIT_CHANCE, self.MAX_HIT_CHANCE)
        hit_roll = self._stable_roll(event_ref, "HIT") * 100.0
        hit = hit_roll < hit_chance
        crit_chance = min(self.MAX_CRIT_CHANCE, float(enemy["crit_chance_pct"]))
        crit_roll = self._stable_roll(event_ref, "CRIT") * 100.0
        critical = bool(hit and crit_roll < crit_chance)
        damage = {"raw": 0.0, "pre_mitigation": 0.0, "mitigation_pct": 0.0, "final": 0.0}
        before = float(target_state["vitals"]["health"])
        after = before
        life_state = target_state["vitals"]["life_state"]
        staggered = False
        if hit:
            damage = self._resolve_damage(
                raw_damage=float(enemy["base_damage"]), damage_type=damage_type, attacker_level=int(enemy["level"]),
                target_armor=float(pstats["armor"]), target_resistance=float(pstats["resistances"].get(damage_type, 0.0)),
                critical=critical, crit_multiplier=float(enemy["crit_multiplier"]),
            )
            health_event = self.engine.character(self.world_instance_id).apply_health_change(
                target_profile_ref, -float(damage["final"]), event_ref=f"{event_ref}:HEALTH", source_type="COMBAT_STAGE03"
            )
            after = float(health_event["health_after"])
            life_state = health_event["life_state"]
            if float(damage["final"]) >= max(8.0, float(target_state["derived"]["max_health"]) * 0.12) and life_state == "ALIVE":
                tov = self.ensure_player(target_profile_ref)
                tov["stagger_remaining_s"] = max(float(tov.get("stagger_remaining_s", 0.0)), 0.25)
                tov["combat_state"] = "STAGGERED"
                self._save_overlay(tov)
                staggered = True
        result = {
            "status": "PASS", "event_ref": event_ref, "attacker_ref": attacker_ref, "target_ref": target_ref,
            "attack_style": "ENEMY_BASIC_ATTACK", "damage_type": damage_type,
            "distance_m": round(distance, 6), "range_m": self.BASIC_RANGE_M,
            "hit_chance_pct": round(hit_chance, 6), "hit_roll_pct": round(hit_roll, 6), "hit": hit,
            "crit_chance_pct": round(crit_chance, 6), "crit_roll_pct": round(crit_roll, 6), "critical": critical,
            "damage": damage, "health_before": round(before, 6), "health_after": round(after, 6),
            "target_life_state": life_state, "staggered": staggered,
            "enemy_cadence": "DEFERRED_STAGE08_AI_SCHEDULER", "formula_version": self.FORMULA_VERSION,
            "idempotent_replay": False, "authority": self.AUTHORITY,
        }
        return self._record_event(event_ref, attacker_ref, target_ref, "ENEMY_ATTACK", payload, result)

    def apply_status(self, actor_ref: str, *, status_ref: str, duration_s: float, magnitude_per_s: float = 0.0, damage_type: str = "PHYSICAL", source_ref: str = "SYSTEM", event_ref: str) -> dict[str, Any]:
        status_ref = str(status_ref).upper().strip()
        damage_type = str(damage_type).upper().strip()
        if damage_type not in DAMAGE_TYPES:
            raise ValidationError("unsupported damage type")
        duration_s = float(duration_s); magnitude_per_s = float(magnitude_per_s)
        if not math.isfinite(duration_s) or duration_s <= 0 or duration_s > self.MAX_STATUS_DURATION_S:
            raise ValidationError("status duration out of range")
        if not math.isfinite(magnitude_per_s) or magnitude_per_s < 0 or magnitude_per_s > self.MAX_STATUS_DPS:
            raise ValidationError("status magnitude out of range")
        payload = {"status_ref": status_ref, "duration_s": duration_s, "magnitude_per_s": magnitude_per_s, "damage_type": damage_type, "source_ref": source_ref}
        existing = self._existing_or_none(event_ref, source_ref, actor_ref, "STATUS_APPLY", payload)
        if existing is not None:
            return existing
        ov = self.overlay(actor_ref)
        statuses = [s for s in ov.get("statuses", []) if s.get("status_ref") != status_ref]
        statuses.append({"status_ref": status_ref, "remaining_s": round(duration_s, 6), "magnitude_per_s": round(magnitude_per_s, 6), "damage_type": damage_type, "source_ref": source_ref})
        ov["statuses"] = statuses
        self._save_overlay(ov)
        result = {"status": "PASS", "actor_ref": actor_ref, "status_effect": copy.deepcopy(statuses[-1]), "idempotent_replay": False, "authority": self.AUTHORITY}
        return self._record_event(event_ref, source_ref, actor_ref, "STATUS_APPLY", payload, result)

    def tick_actor(self, actor_ref: str, delta_s: float) -> dict[str, Any]:
        delta_s = float(delta_s)
        if not math.isfinite(delta_s) or delta_s <= 0 or delta_s > 1.0:
            raise ValidationError("delta_s must be in (0,1]")
        ov = self.overlay(actor_ref)
        old_cd = float(ov.get("attack_cooldown_remaining_s", 0.0))
        old_stagger = float(ov.get("stagger_remaining_s", 0.0))
        ov["attack_cooldown_remaining_s"] = round(max(0.0, old_cd - delta_s), 6)
        ov["stagger_remaining_s"] = round(max(0.0, old_stagger - delta_s), 6)
        damage_total = 0.0
        statuses_out = []
        profile = self._profile_for_avatar(actor_ref)
        enemy = None if profile else self.ensure_enemy(actor_ref)
        for status in ov.get("statuses", []):
            remaining_before = float(status["remaining_s"])
            active_s = min(delta_s, remaining_before)
            dot = max(0.0, float(status.get("magnitude_per_s", 0.0))) * active_s
            if dot > 0.0:
                if profile:
                    char = self.engine.character(self.world_instance_id).state(profile["profile_ref"])
                    if char["vitals"]["life_state"] == "ALIVE":
                        # DOT tick uses a deterministic frame-local reference derived from current state.
                        ref = "dot:" + sha256_text(canonical_json({"actor": actor_ref, "status": status, "health": char["vitals"]["health"], "dt": delta_s}))[:24]
                        try:
                            out = self.engine.character(self.world_instance_id).apply_health_change(profile["profile_ref"], -dot, event_ref=ref, source_type="COMBAT_STATUS")
                            damage_total += max(0.0, float(out["health_before"]) - float(out["health_after"]))
                        except ConflictError:
                            pass
                else:
                    if enemy["life_state"] == "ALIVE":
                        applied = min(float(enemy["health"]), dot)
                        enemy["health"] = round(max(0.0, float(enemy["health"]) - applied), 6)
                        damage_total += applied
                        if enemy["health"] <= 0.0:
                            if enemy.get("protected_identity"):
                                enemy["health"] = 1.0
                            else:
                                enemy["life_state"] = "DEFEATED"
            status = copy.deepcopy(status)
            status["remaining_s"] = round(max(0.0, remaining_before - delta_s), 6)
            if status["remaining_s"] > 1e-9:
                statuses_out.append(status)
        ov["statuses"] = statuses_out
        ov["combat_state"] = "STAGGERED" if ov["stagger_remaining_s"] > 0 else ("RECOVERY" if ov["attack_cooldown_remaining_s"] > 0 else "READY")
        self._save_overlay(ov)
        if enemy is not None:
            self._save_row("arpg_enemy_combat_state", actor_ref, enemy)
        return {"status": "PASS", "actor_ref": actor_ref, "damage_applied": round(damage_total, 6), "cooldown_remaining_s": ov["attack_cooldown_remaining_s"], "stagger_remaining_s": ov["stagger_remaining_s"], "statuses": copy.deepcopy(statuses_out), "combat_state": ov["combat_state"]}

    def tick_player(self, profile_ref: str, delta_s: float) -> dict[str, Any]:
        profile = self.engine.arpg(self.world_instance_id).profile(profile_ref)
        self.ensure_player(profile_ref)
        return self.tick_actor(profile["avatar_ref"], delta_s)

    def target_state(self, target_ref: str) -> dict[str, Any] | None:
        profile = self._profile_for_avatar(target_ref)
        if profile:
            char = self.engine.character(self.world_instance_id).state(profile["profile_ref"])
            return {"actor_ref": target_ref, "actor_kind": "PLAYER", "life_state": char["vitals"]["life_state"], "health": char["vitals"]["health"], "max_health": char["derived"]["max_health"], "overlay": self.overlay(target_ref)}
        try:
            enemy = self.ensure_enemy(target_ref)
        except (ValidationError, ConflictError):
            return None
        return {**enemy, "overlay": self.overlay(target_ref)}

    def player_snapshot(self, profile_ref: str, selected_target_ref: str | None = None) -> dict[str, Any]:
        profile = self.engine.arpg(self.world_instance_id).profile(profile_ref)
        return {
            "profile_ref": profile_ref,
            "actor_ref": profile["avatar_ref"],
            "stats": self.player_stats(profile_ref),
            "overlay": self.ensure_player(profile_ref),
            "selected_target": self.target_state(selected_target_ref) if selected_target_ref else None,
            "pvp_enabled": self.PVP_ENABLED,
            "formula_version": self.FORMULA_VERSION,
            "authority": self.AUTHORITY,
        }

    def event_history(self) -> list[dict[str, Any]]:
        rows = self.runtime.conn.execute(
            "SELECT server_sequence,event_ref,attacker_ref,target_ref,event_type,payload_json,result_json,event_hash FROM arpg_combat_events WHERE world_instance_id=? ORDER BY server_sequence",
            (self.world_instance_id,),
        ).fetchall()
        return [{**{k: row[k] for k in ("server_sequence", "event_ref", "attacker_ref", "target_ref", "event_type", "event_hash")}, "payload": json.loads(row["payload_json"]), "result": json.loads(row["result_json"])} for row in rows]

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        overlays = 0; enemies = 0; events = 0
        for table in ("arpg_combat_overlay", "arpg_enemy_combat_state"):
            rows = self.runtime.conn.execute(f"SELECT actor_ref,payload_json,payload_hash FROM {table} WHERE world_instance_id=?", (self.world_instance_id,)).fetchall()
            for row in rows:
                if sha256_text(row["payload_json"]) != row["payload_hash"]:
                    failures.append("STATE_HASH:" + row["actor_ref"])
                    continue
                payload = json.loads(row["payload_json"])
                if payload.get("actor_ref") != row["actor_ref"]:
                    failures.append("STATE_ACTOR_REF:" + row["actor_ref"])
                if table == "arpg_combat_overlay":
                    overlays += 1
                    if float(payload.get("attack_cooldown_remaining_s", -1)) < 0 or float(payload.get("stagger_remaining_s", -1)) < 0:
                        failures.append("OVERLAY_TIMER_RANGE:" + row["actor_ref"])
                else:
                    enemies += 1
                    h = float(payload.get("health", -1)); mh = float(payload.get("max_health", -1))
                    if h < 0 or mh <= 0 or h > mh:
                        failures.append("ENEMY_HEALTH_RANGE:" + row["actor_ref"])
                    if payload.get("life_state") not in {"ALIVE", "DEFEATED"}:
                        failures.append("ENEMY_LIFE_STATE:" + row["actor_ref"])
        for row in self.runtime.conn.execute("SELECT * FROM arpg_combat_events WHERE world_instance_id=? ORDER BY server_sequence", (self.world_instance_id,)).fetchall():
            events += 1
            payload = json.loads(row["payload_json"])
            if self._event_hash(row["attacker_ref"], row["target_ref"], row["event_type"], payload) != row["event_hash"]:
                failures.append("EVENT_HASH:" + row["event_ref"])
        for profile in self.engine.arpg(self.world_instance_id).list_profiles():
            try:
                self.ensure_player(profile["profile_ref"])
            except Exception as exc:
                failures.append("PLAYER_COMBAT_STATE:" + profile["profile_ref"] + ":" + str(exc))
        return {"status": "PASS" if not failures else "FAIL", "failures": failures, "overlays": overlays, "enemy_states": enemies, "events": events, "formula_version": self.FORMULA_VERSION, "authority": self.AUTHORITY}
