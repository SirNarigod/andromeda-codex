from __future__ import annotations

import copy
import json
import math
from typing import Any

from living_runtime import ValidationError, ConflictError, canonical_json, sha256_text

ACTOR_ROLES = {
    "PLAYER", "CIVILIAN", "WORKER", "MERCHANT", "GUARD", "ALLY", "NEUTRAL",
    "HOSTILE", "ANIMAL", "CREATURE", "ROBOT", "BOSS",
}
DISPOSITIONS = {"ALLIED", "FRIENDLY", "NEUTRAL", "WARY", "HOSTILE"}
COMBAT_RANKS = {"NONCOMBATANT", "COMMON", "CHAMPION", "ELITE", "MINIBOSS", "BOSS"}
AI_STATES = {"DISABLED", "IDLE", "PATROL", "ALERT", "CHASE", "ATTACK", "RETURN", "FLEE", "DEFEATED"}

RANK_MULTIPLIERS: dict[str, dict[str, float]] = {
    "NONCOMBATANT": {"health": 1.0, "damage": 1.0, "armor": 1.0, "xp": 0.0, "aggro": 0.0},
    "COMMON": {"health": 1.0, "damage": 1.0, "armor": 1.0, "xp": 1.0, "aggro": 1.0},
    "CHAMPION": {"health": 1.35, "damage": 1.15, "armor": 1.10, "xp": 1.35, "aggro": 1.08},
    "ELITE": {"health": 1.80, "damage": 1.30, "armor": 1.25, "xp": 1.80, "aggro": 1.15},
    "MINIBOSS": {"health": 3.50, "damage": 1.60, "armor": 1.45, "xp": 3.00, "aggro": 1.25},
    "BOSS": {"health": 7.00, "damage": 2.00, "armor": 1.75, "xp": 5.00, "aggro": 1.35},
}


class ARPGActorCore:
    """Stage07 actor, hostility and PvE AI authority.

    This is a gameplay overlay. It never rewrites an NPC's canonical identity, profession,
    species, faction or narrative state. Country/Living records remain the source records;
    the ARPG actor profile only describes how an active instance behaves in gameplay.
    """

    VERSION = "V0.8.0"
    STAGE = "07/20"
    AUTHORITY = "ARPG_ACTORS_HOSTILITY_AI_GAMEPLAY_DERIVATION"
    DEFAULT_AGGRO_M = 9.0
    DEFAULT_LEASH_M = 18.0
    DEFAULT_ATTACK_RANGE_M = 1.65
    DEFAULT_AI_ATTACK_INTERVAL_S = 1.25
    MAX_AI_ACTORS_PER_TICK = 32

    def __init__(self, engine: Any, world_instance_id: str) -> None:
        self.engine = engine
        self.runtime = engine.runtime
        self.world_instance_id = world_instance_id
        self.country = engine.country(world_instance_id)
        self._init_schema()
        self.bootstrap_country_actors()
        self.bootstrap_players()

    def _init_schema(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS arpg_actor_profiles(
                    world_instance_id TEXT NOT NULL,
                    actor_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id,actor_ref)
                );
                CREATE TABLE IF NOT EXISTS arpg_actor_ai_state(
                    world_instance_id TEXT NOT NULL,
                    actor_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id,actor_ref)
                );
                CREATE TABLE IF NOT EXISTS arpg_actor_events(
                    server_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    world_instance_id TEXT NOT NULL,
                    event_ref TEXT NOT NULL,
                    actor_ref TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id,event_ref)
                );
                CREATE INDEX IF NOT EXISTS idx_arpg_actor_events_actor
                  ON arpg_actor_events(world_instance_id,actor_ref,server_sequence);
                """
            )
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('arpg_actor_core_version',?)",
                (self.VERSION,),
            )

    @staticmethod
    def _payload_hash(payload: dict[str, Any]) -> tuple[str, str]:
        text = canonical_json(payload)
        return text, sha256_text(text)

    def _save(self, table: str, actor_ref: str, payload: dict[str, Any]) -> None:
        text, h = self._payload_hash(payload)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                f"INSERT OR REPLACE INTO {table}(world_instance_id,actor_ref,payload_json,payload_hash) VALUES(?,?,?,?)",
                (self.world_instance_id, actor_ref, text, h),
            )

    def _load(self, table: str, actor_ref: str) -> dict[str, Any] | None:
        row = self.runtime.conn.execute(
            f"SELECT payload_json,payload_hash FROM {table} WHERE world_instance_id=? AND actor_ref=?",
            (self.world_instance_id, actor_ref),
        ).fetchone()
        if not row:
            return None
        if sha256_text(row["payload_json"]) != row["payload_hash"]:
            raise ConflictError("ACTOR_STATE_HASH_MISMATCH")
        return json.loads(row["payload_json"])

    def _event_existing(self, event_ref: str):
        return self.runtime.conn.execute(
            "SELECT * FROM arpg_actor_events WHERE world_instance_id=? AND event_ref=?",
            (self.world_instance_id, event_ref),
        ).fetchone()

    def _event_hash(self, actor_ref: str, event_type: str, payload: dict[str, Any]) -> str:
        return sha256_text(canonical_json({"actor_ref": actor_ref, "event_type": event_type, "payload": payload}))

    def _record_event(self, event_ref: str, actor_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        event_ref = str(event_ref).strip()
        if not event_ref or len(event_ref) > 180:
            raise ValidationError("event_ref must contain 1-180 characters")
        h = self._event_hash(actor_ref, event_type, payload)
        existing = self._event_existing(event_ref)
        if existing:
            if existing["event_hash"] != h:
                raise ConflictError("ACTOR_EVENT_REF_CONFLICT")
            out = json.loads(existing["result_json"])
            out["idempotent_replay"] = True
            out["actor_server_sequence"] = existing["server_sequence"]
            return out
        textp = canonical_json(payload)
        textr = canonical_json(result)
        with self.runtime._write_lock:
            cur = self.runtime.conn.execute(
                "INSERT INTO arpg_actor_events(world_instance_id,event_ref,actor_ref,event_type,payload_json,result_json,event_hash) VALUES(?,?,?,?,?,?,?)",
                (self.world_instance_id, event_ref, actor_ref, event_type, textp, textr, h),
            )
        out = copy.deepcopy(result)
        out["actor_server_sequence"] = int(cur.lastrowid)
        return out

    def _player_profile_for_avatar(self, actor_ref: str) -> dict[str, Any] | None:
        try:
            for p in self.engine.arpg(self.world_instance_id).list_profiles():
                if p.get("avatar_ref") == actor_ref:
                    return p
        except Exception:
            return None
        return None

    @staticmethod
    def _npc_default(npc: dict[str, Any]) -> tuple[str, str, str]:
        cls = str(npc.get("class") or "").upper()
        protected = bool((npc.get("protection") or {}).get("protected", False))
        if cls == "PLAYER_AVATAR":
            return "PLAYER", "ALLIED", "COMMON"
        if cls == "CHILD":
            return "CIVILIAN", "NEUTRAL", "NONCOMBATANT"
        if cls == "WORKER":
            return "WORKER", "NEUTRAL", "NONCOMBATANT" if protected else "COMMON"
        if cls == "ROBOT":
            return "ROBOT", "NEUTRAL", "COMMON"
        if cls in {"WARRIOR", "MERCENARY"}:
            return "GUARD", "NEUTRAL", "COMMON"
        if cls in {"MAGE", "NATIVE"}:
            return "NEUTRAL", "NEUTRAL", "COMMON"
        return "NEUTRAL", "NEUTRAL", "COMMON"

    def _home_position(self, actor_ref: str) -> dict[str, float] | None:
        try:
            m = self.engine.movement(self.world_instance_id).state(actor_ref)
            return {"iso_x_m": float(m["iso_x_m"]), "iso_y_m": float(m["iso_y_m"]), "altitude_m": float(m.get("altitude_m", 0.0))}
        except Exception:
            return None

    def ensure_actor(self, actor_ref: str) -> dict[str, Any]:
        actor_ref = str(actor_ref).strip()
        if not actor_ref:
            raise ValidationError("actor_ref required")
        existing = self._load("arpg_actor_profiles", actor_ref)
        if existing is not None:
            return copy.deepcopy(existing)
        p = self._player_profile_for_avatar(actor_ref)
        npc = None
        try:
            npc = self.country.npc(actor_ref)
        except KeyError:
            pass
        robot_asset = None
        if p is None and npc is None and actor_ref.startswith("RBT-"):
            try:
                row = self.runtime.conn.execute(
                    "SELECT payload_json,payload_hash FROM arpg_robot_instances WHERE world_instance_id=? AND robot_ref=?",
                    (self.world_instance_id, actor_ref),
                ).fetchone()
                if row and sha256_text(row["payload_json"]) == row["payload_hash"]:
                    robot_asset = json.loads(row["payload_json"])
            except Exception:
                robot_asset = None
        if p is None and npc is None and robot_asset is None:
            raise ValidationError("ACTOR_NOT_SUPPORTED_STAGE07")
        if p is not None:
            role, disposition, rank = "PLAYER", "ALLIED", "COMMON"
            protected = False
            targetable = True
            source_class = "PLAYER_AVATAR"
            source_kind = "PLAYER"
            source_ref = p.get("canonical_ref") or p.get("profile_ref")
        elif robot_asset is not None:
            role, disposition, rank = "ROBOT", str(robot_asset.get("disposition") or "NEUTRAL").upper(), "COMMON"
            protected = False
            targetable = True
            source_class = "ROBOT"
            source_kind = "TECH_ASSET"
            source_ref = robot_asset.get("robot_ref")
        else:
            role, disposition, rank = self._npc_default(npc)
            protection = npc.get("protection") or {}
            protected = bool(protection.get("protected", False))
            targetable = bool(protection.get("combat_targetable", True))
            source_class = npc.get("class")
            source_kind = "COUNTRY_NPC"
            source_ref = npc.get("id")
        home = self._home_position(actor_ref)
        profile = {
            "actor_ref": actor_ref,
            "source_kind": source_kind,
            "source_ref": source_ref,
            "source_class": source_class,
            "actor_role": role,
            "disposition": disposition,
            "combat_rank": rank,
            "protected_identity": protected,
            "combat_targetable": targetable,
            "ai_enabled": bool(role != "PLAYER" and disposition == "HOSTILE" and not protected),
            "aggro_radius_m": self.DEFAULT_AGGRO_M,
            "leash_radius_m": self.DEFAULT_LEASH_M,
            "attack_range_m": self.DEFAULT_ATTACK_RANGE_M,
            "ai_attack_interval_s": self.DEFAULT_AI_ATTACK_INTERVAL_S,
            "home_position": home,
            "faction_ref": None,
            "canonical_identity_mutation": False,
            "authority": self.AUTHORITY,
        }
        ai = {
            "actor_ref": actor_ref,
            "state": "DISABLED" if role == "PLAYER" else "IDLE",
            "target_profile_ref": None,
            "target_actor_ref": None,
            "decision_sequence": 0,
            "attack_cooldown_s": 0.0,
            "last_distance_m": None,
            "last_reason": None,
            "authority": self.AUTHORITY,
        }
        self._save("arpg_actor_profiles", actor_ref, profile)
        self._save("arpg_actor_ai_state", actor_ref, ai)
        return copy.deepcopy(profile)

    def ensure_profile(self, profile_ref: str) -> dict[str, Any]:
        p = self.engine.arpg(self.world_instance_id).profile(profile_ref)
        return self.ensure_actor(p["avatar_ref"])

    def bootstrap_country_actors(self) -> dict[str, Any]:
        # Stage07 uses LOD/lazy materialization: the Country may contain hundreds of NPCs,
        # but only actors that become player-controlled, targeted, configured or streamed into
        # an active AI set receive ARPG overlay rows. This prevents O(country population) writes
        # at every world bootstrap while preserving deterministic classification on first access.
        total = sum(1 for _ in self.country._all_npc_records())
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('arpg_actor_country_source_count',?)",
                (str(total),),
            )
        return {"status": "PASS", "total": total, "created": 0, "materialization": "LAZY_ACTIVE_SET"}

    def country_source_actor_count(self) -> int:
        row = self.runtime.conn.execute("SELECT value FROM runtime_meta WHERE key='arpg_actor_country_source_count'").fetchone()
        return int(row['value']) if row else sum(1 for _ in self.country._all_npc_records())

    def bootstrap_players(self) -> dict[str, Any]:
        created = 0
        try:
            profiles = self.engine.arpg(self.world_instance_id).list_profiles()
        except Exception:
            profiles = []
        for p in profiles:
            if self._load("arpg_actor_profiles", p["avatar_ref"]) is None:
                self.ensure_actor(p["avatar_ref"])
                created += 1
        return {"status": "PASS", "profiles": len(profiles), "created": created}

    def actor(self, actor_ref: str) -> dict[str, Any]:
        return self.ensure_actor(actor_ref)

    def ai_state(self, actor_ref: str) -> dict[str, Any]:
        self.ensure_actor(actor_ref)
        state = self._load("arpg_actor_ai_state", actor_ref)
        if state is None:
            raise ConflictError("ACTOR_AI_STATE_MISSING")
        return copy.deepcopy(state)

    def _save_actor(self, p: dict[str, Any]) -> None:
        self._save("arpg_actor_profiles", p["actor_ref"], p)

    def _save_ai(self, s: dict[str, Any]) -> None:
        self._save("arpg_actor_ai_state", s["actor_ref"], s)

    def set_disposition(self, actor_ref: str, disposition: str, *, event_ref: str, reason: str = "RUNTIME_GAMEPLAY") -> dict[str, Any]:
        disposition = str(disposition).upper().strip()
        if disposition not in DISPOSITIONS:
            raise ValidationError("invalid disposition")
        payload = {"disposition": disposition, "reason": str(reason)}
        existing = self._event_existing(str(event_ref))
        if existing:
            return self._record_event(event_ref, actor_ref, "DISPOSITION_SET", payload, {})
        p = self.ensure_actor(actor_ref)
        before = p["disposition"]
        if p["actor_role"] == "PLAYER" and disposition == "HOSTILE":
            raise ValidationError("player avatar disposition is controller-owned")
        if p.get("protected_identity") and disposition == "HOSTILE":
            result = {"status": "REJECTED", "reason": "PROTECTED_ACTOR_CANNOT_AUTO_AGGRESS", "actor_ref": actor_ref, "disposition": before, "idempotent_replay": False, "authority": self.AUTHORITY}
            return self._record_event(event_ref, actor_ref, "DISPOSITION_SET", payload, result)
        p["disposition"] = disposition
        p["actor_role"] = "HOSTILE" if disposition == "HOSTILE" and p["actor_role"] not in {"ANIMAL", "CREATURE", "ROBOT", "BOSS"} else p["actor_role"]
        p["ai_enabled"] = bool(disposition == "HOSTILE" and not p.get("protected_identity") and p["actor_role"] != "PLAYER")
        self._save_actor(p)
        ai = self.ai_state(actor_ref)
        if not p["ai_enabled"]:
            ai.update({"state": "IDLE", "target_profile_ref": None, "target_actor_ref": None, "last_reason": "NON_HOSTILE"})
        self._save_ai(ai)
        result = {"status": "PASS", "actor_ref": actor_ref, "before": before, "after": disposition, "ai_enabled": p["ai_enabled"], "idempotent_replay": False, "authority": self.AUTHORITY}
        return self._record_event(event_ref, actor_ref, "DISPOSITION_SET", payload, result)

    def set_combat_rank(self, actor_ref: str, rank: str, *, event_ref: str, reason: str = "RUNTIME_GAMEPLAY") -> dict[str, Any]:
        rank = str(rank).upper().strip()
        if rank not in COMBAT_RANKS:
            raise ValidationError("invalid combat rank")
        payload = {"rank": rank, "reason": str(reason)}
        existing = self._event_existing(str(event_ref))
        if existing:
            return self._record_event(event_ref, actor_ref, "COMBAT_RANK_SET", payload, {})
        p = self.ensure_actor(actor_ref)
        before = p["combat_rank"]
        if p.get("protected_identity") and rank != "NONCOMBATANT":
            result = {"status": "REJECTED", "reason": "PROTECTED_ACTOR_RANK_BLOCKED", "actor_ref": actor_ref, "rank": before, "idempotent_replay": False, "authority": self.AUTHORITY}
            return self._record_event(event_ref, actor_ref, "COMBAT_RANK_SET", payload, result)
        p["combat_rank"] = rank
        if rank == "BOSS":
            p["actor_role"] = "BOSS"
        p["aggro_radius_m"] = round(self.DEFAULT_AGGRO_M * RANK_MULTIPLIERS[rank]["aggro"], 6) if rank != "NONCOMBATANT" else 0.0
        self._save_actor(p)
        scaling = self._apply_rank_scaling(actor_ref, rank)
        result = {"status": "PASS", "actor_ref": actor_ref, "before": before, "after": rank, "scaling": scaling, "idempotent_replay": False, "authority": self.AUTHORITY}
        return self._record_event(event_ref, actor_ref, "COMBAT_RANK_SET", payload, result)

    def _apply_rank_scaling(self, actor_ref: str, rank: str) -> dict[str, Any]:
        if rank == "NONCOMBATANT":
            return {"status": "SKIPPED", "reason": "NONCOMBATANT"}
        combat = self.engine.combat_arpg(self.world_instance_id)
        state = combat.ensure_enemy(actor_ref)
        # Scaling is always reapplied from the Stage03 base seed, not compounded from current values.
        npc = self.country.npc(actor_ref)
        level = combat._tier_level(npc)
        cls = str(npc.get("class") or "NPC").upper()
        import hashlib
        seed = int(hashlib.sha256(cls.encode("utf-8")).hexdigest()[:8], 16)
        base_max = float(70 + level * 18 + seed % 21)
        base_armor = float(8 + level * 2 + seed % 7)
        base_damage = float(7 + level * 3 + seed % 6)
        base_xp = int(20 + level * 15)
        mult = RANK_MULTIPLIERS[rank]
        ratio = 1.0 if float(state.get("max_health", 0.0)) <= 0 else max(0.0, min(1.0, float(state.get("health", 0.0)) / float(state["max_health"])))
        state["max_health"] = round(base_max * mult["health"], 6)
        state["health"] = round(max(1.0, state["max_health"] * ratio), 6) if state.get("life_state") == "ALIVE" else float(state.get("health", 0.0))
        state["armor"] = round(base_armor * mult["armor"], 6)
        state["base_damage"] = round(base_damage * mult["damage"], 6)
        state["xp_reward"] = int(round(base_xp * mult["xp"]))
        state["combat_rank"] = rank
        state["rank_authority"] = self.AUTHORITY
        state["stagger_threshold"] = round(float(state["max_health"]) * (0.18 if rank in {"COMMON", "CHAMPION"} else 0.24), 6)
        combat._save_row("arpg_enemy_combat_state", actor_ref, state)
        return {"status": "PASS", "max_health": state["max_health"], "base_damage": state["base_damage"], "armor": state["armor"], "xp_reward": state["xp_reward"]}

    def hostility_to_profile(self, actor_ref: str, profile_ref: str) -> dict[str, Any]:
        p = self.ensure_actor(actor_ref)
        profile = self.engine.arpg(self.world_instance_id).profile(profile_ref)
        hostile = bool(p["disposition"] == "HOSTILE" and p.get("ai_enabled") and not p.get("protected_identity"))
        return {
            "status": "PASS",
            "actor_ref": actor_ref,
            "profile_ref": profile_ref,
            "target_actor_ref": profile["avatar_ref"],
            "hostile": hostile,
            "disposition": p["disposition"],
            "protected_identity": p.get("protected_identity", False),
            "combat_rank": p["combat_rank"],
            "authority": self.AUTHORITY,
        }

    def _distance(self, a: str, b: str) -> float:
        ma = self.engine.movement(self.world_instance_id).state(a)
        mb = self.engine.movement(self.world_instance_id).state(b)
        return math.hypot(float(ma["iso_x_m"]) - float(mb["iso_x_m"]), float(ma["iso_y_m"]) - float(mb["iso_y_m"]))

    def _distance_home(self, actor_ref: str, profile: dict[str, Any]) -> float:
        home = profile.get("home_position")
        if not home:
            return 0.0
        m = self.engine.movement(self.world_instance_id).state(actor_ref)
        return math.hypot(float(m["iso_x_m"]) - float(home["iso_x_m"]), float(m["iso_y_m"]) - float(home["iso_y_m"]))

    def _alive_profiles(self) -> list[dict[str, Any]]:
        out = []
        for p in self.engine.arpg(self.world_instance_id).list_profiles():
            if not p.get("active"):
                continue
            try:
                ch = self.engine.character(self.world_instance_id).state(p["profile_ref"])
                if ch["vitals"]["life_state"] == "ALIVE":
                    out.append(p)
            except Exception:
                continue
        return out

    def _nearest_target(self, actor_ref: str, aggro_radius_m: float) -> tuple[dict[str, Any] | None, float | None]:
        best = None
        best_d = None
        for p in self._alive_profiles():
            try:
                d = self._distance(actor_ref, p["avatar_ref"])
            except Exception:
                continue
            if d <= aggro_radius_m + 1e-9 and (best_d is None or d < best_d):
                best, best_d = p, d
        return best, best_d

    def tick_actor(self, actor_ref: str, delta_s: float) -> dict[str, Any]:
        delta_s = float(delta_s)
        if not math.isfinite(delta_s) or delta_s <= 0 or delta_s > 1.0:
            raise ValidationError("delta_s must be in (0,1]")
        p = self.ensure_actor(actor_ref)
        ai = self.ai_state(actor_ref)
        ai["decision_sequence"] = int(ai.get("decision_sequence", 0)) + 1
        ai["attack_cooldown_s"] = round(max(0.0, float(ai.get("attack_cooldown_s", 0.0)) - delta_s), 6)
        if p["actor_role"] == "PLAYER":
            ai.update({"state": "DISABLED", "last_reason": "PLAYER_CONTROLLED"})
            self._save_ai(ai)
            return {"status": "PASS", "actor_ref": actor_ref, "ai_state": "DISABLED", "action": "NONE", "reason": "PLAYER_CONTROLLED"}
        try:
            enemy_state = self.engine.combat_arpg(self.world_instance_id).ensure_enemy(actor_ref)
            self.engine.combat_arpg(self.world_instance_id).tick_actor(actor_ref, delta_s)
        except Exception as exc:
            ai.update({"state": "DISABLED", "last_reason": "COMBAT_STATE_UNAVAILABLE"})
            self._save_ai(ai)
            return {"status": "PASS", "actor_ref": actor_ref, "ai_state": "DISABLED", "action": "NONE", "reason": "COMBAT_STATE_UNAVAILABLE", "detail": str(exc)}
        if enemy_state.get("life_state") != "ALIVE":
            ai.update({"state": "DEFEATED", "target_profile_ref": None, "target_actor_ref": None, "last_reason": "DEFEATED"})
            self._save_ai(ai)
            return {"status": "PASS", "actor_ref": actor_ref, "ai_state": "DEFEATED", "action": "NONE"}
        if not p.get("ai_enabled") or p.get("protected_identity") or p.get("disposition") != "HOSTILE":
            ai.update({"state": "IDLE", "target_profile_ref": None, "target_actor_ref": None, "last_reason": "NON_HOSTILE_OR_PROTECTED"})
            self._save_ai(ai)
            return {"status": "PASS", "actor_ref": actor_ref, "ai_state": "IDLE", "action": "NONE", "reason": ai["last_reason"]}

        target = None
        distance = None
        if ai.get("target_profile_ref"):
            try:
                candidate = self.engine.arpg(self.world_instance_id).profile(ai["target_profile_ref"])
                ch = self.engine.character(self.world_instance_id).state(candidate["profile_ref"])
                if candidate.get("active") and ch["vitals"]["life_state"] == "ALIVE":
                    target = candidate
                    distance = self._distance(actor_ref, candidate["avatar_ref"])
            except Exception:
                target = None
        if target is None:
            target, distance = self._nearest_target(actor_ref, float(p["aggro_radius_m"]))
            if target is None:
                ai.update({"state": "IDLE", "target_profile_ref": None, "target_actor_ref": None, "last_distance_m": None, "last_reason": "NO_TARGET_IN_AGGRO"})
                self._save_ai(ai)
                return {"status": "PASS", "actor_ref": actor_ref, "ai_state": "IDLE", "action": "NONE", "reason": "NO_TARGET_IN_AGGRO"}
            ai["target_profile_ref"] = target["profile_ref"]
            ai["target_actor_ref"] = target["avatar_ref"]

        home_distance = self._distance_home(actor_ref, p)
        ai["last_distance_m"] = round(float(distance), 6)
        if home_distance > float(p["leash_radius_m"]) or float(distance) > float(p["leash_radius_m"]) * 1.25:
            home = p.get("home_position")
            ai.update({"state": "RETURN", "target_profile_ref": None, "target_actor_ref": None, "last_reason": "LEASH_EXCEEDED"})
            moved = None
            if home is not None:
                cur = self.engine.movement(self.world_instance_id).state(actor_ref)
                dx = float(home["iso_x_m"]) - float(cur["iso_x_m"])
                dy = float(home["iso_y_m"]) - float(cur["iso_y_m"])
                if math.hypot(dx, dy) > 0.10:
                    moved = self.engine.movement(self.world_instance_id).step_vector(actor_ref, dx, dy, duration_s=min(delta_s, 0.25), mode="RUN")
            self._save_ai(ai)
            return {"status": "PASS", "actor_ref": actor_ref, "ai_state": "RETURN", "action": "RETURN_HOME", "movement": moved, "home_distance_m": round(home_distance, 6)}

        if float(distance) <= float(p["attack_range_m"]) + 1e-9:
            ai["state"] = "ATTACK"
            if ai["attack_cooldown_s"] > 1e-9:
                ai["last_reason"] = "AI_ATTACK_COOLDOWN"
                self._save_ai(ai)
                return {"status": "PASS", "actor_ref": actor_ref, "ai_state": "ATTACK", "action": "WAIT_COOLDOWN", "remaining_s": ai["attack_cooldown_s"]}
            event_ref = f"ai07:{actor_ref}:{ai['decision_sequence']}"
            out = self.engine.combat_arpg(self.world_instance_id).enemy_attack_player(actor_ref, target["profile_ref"], event_ref=event_ref)
            ai["attack_cooldown_s"] = round(float(p["ai_attack_interval_s"]), 6)
            ai["last_reason"] = out.get("reason") or "ATTACK_RESOLVED"
            self._save_ai(ai)
            return {"status": "PASS", "actor_ref": actor_ref, "ai_state": "ATTACK", "action": "ATTACK", "combat": out, "target_profile_ref": target["profile_ref"]}

        ai["state"] = "CHASE"
        cur = self.engine.movement(self.world_instance_id).state(actor_ref)
        tpos = self.engine.movement(self.world_instance_id).state(target["avatar_ref"])
        dx = float(tpos["iso_x_m"]) - float(cur["iso_x_m"])
        dy = float(tpos["iso_y_m"]) - float(cur["iso_y_m"])
        move = self.engine.movement(self.world_instance_id).step_vector(actor_ref, dx, dy, duration_s=min(delta_s, 0.25), mode="RUN")
        ai["last_reason"] = "PURSUING_HOSTILE_TARGET"
        self._save_ai(ai)
        return {"status": "PASS", "actor_ref": actor_ref, "ai_state": "CHASE", "action": "MOVE_TOWARD_TARGET", "movement": move, "target_profile_ref": target["profile_ref"], "distance_m": round(float(distance), 6)}

    def tick_nearby(self, profile_ref: str, delta_s: float, *, max_actors: int | None = None) -> dict[str, Any]:
        max_actors = self.MAX_AI_ACTORS_PER_TICK if max_actors is None else int(max_actors)
        if max_actors < 1 or max_actors > 256:
            raise ValidationError("max_actors out of range")
        player = self.engine.arpg(self.world_instance_id).profile(profile_ref)
        rows = self.runtime.conn.execute(
            "SELECT actor_ref,payload_json,payload_hash FROM arpg_actor_profiles WHERE world_instance_id=? ORDER BY actor_ref",
            (self.world_instance_id,),
        ).fetchall()
        candidates = []
        for row in rows:
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                raise ConflictError("ACTOR_STATE_HASH_MISMATCH")
            p = json.loads(row["payload_json"])
            if not p.get("ai_enabled") or p["actor_ref"] == player["avatar_ref"]:
                continue
            try:
                d = self._distance(p["actor_ref"], player["avatar_ref"])
            except Exception:
                continue
            if d <= max(float(p.get("leash_radius_m", self.DEFAULT_LEASH_M)) * 1.5, float(p.get("aggro_radius_m", self.DEFAULT_AGGRO_M))):
                candidates.append((d, p["actor_ref"]))
        candidates.sort(key=lambda x: (x[0], x[1]))
        results = [self.tick_actor(ref, delta_s) for _d, ref in candidates[:max_actors]]
        return {"status": "PASS", "profile_ref": profile_ref, "considered": len(candidates), "ticked": len(results), "results": results, "authority": self.AUTHORITY}

    def selected_target_snapshot(self, profile_ref: str, target_ref: str | None) -> dict[str, Any] | None:
        if not target_ref:
            return None
        try:
            p = self.ensure_actor(target_ref)
        except Exception:
            return None
        return {"actor": p, "ai": self.ai_state(target_ref), "hostility": self.hostility_to_profile(target_ref, profile_ref), "authority": self.AUTHORITY}

    def snapshot(self, profile_ref: str, selected_target_ref: str | None = None) -> dict[str, Any]:
        p = self.engine.arpg(self.world_instance_id).profile(profile_ref)
        me = self.ensure_actor(p["avatar_ref"])
        counts: dict[str, int] = {}
        rows = self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_actor_profiles WHERE world_instance_id=?",
            (self.world_instance_id,),
        ).fetchall()
        for row in rows:
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                raise ConflictError("ACTOR_STATE_HASH_MISMATCH")
            ap = json.loads(row["payload_json"])
            counts[ap["actor_role"]] = counts.get(ap["actor_role"], 0) + 1
        return {"status": "PASS", "player_actor": me, "selected_target": self.selected_target_snapshot(profile_ref, selected_target_ref), "role_counts": counts, "authority": self.AUTHORITY}

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        profiles = 0
        ai_states = 0
        events = 0
        rows = self.runtime.conn.execute(
            "SELECT actor_ref,payload_json,payload_hash FROM arpg_actor_profiles WHERE world_instance_id=? ORDER BY actor_ref",
            (self.world_instance_id,),
        ).fetchall()
        for row in rows:
            profiles += 1
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                failures.append("ACTOR_HASH:" + row["actor_ref"])
                continue
            p = json.loads(row["payload_json"])
            if p.get("actor_ref") != row["actor_ref"]:
                failures.append("ACTOR_REF:" + row["actor_ref"])
            if p.get("actor_role") not in ACTOR_ROLES:
                failures.append("ACTOR_ROLE:" + row["actor_ref"])
            if p.get("disposition") not in DISPOSITIONS:
                failures.append("DISPOSITION:" + row["actor_ref"])
            if p.get("combat_rank") not in COMBAT_RANKS:
                failures.append("COMBAT_RANK:" + row["actor_ref"])
            if p.get("protected_identity") and p.get("ai_enabled"):
                failures.append("PROTECTED_AI_ENABLED:" + row["actor_ref"])
        rows2 = self.runtime.conn.execute(
            "SELECT actor_ref,payload_json,payload_hash FROM arpg_actor_ai_state WHERE world_instance_id=? ORDER BY actor_ref",
            (self.world_instance_id,),
        ).fetchall()
        for row in rows2:
            ai_states += 1
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                failures.append("AI_HASH:" + row["actor_ref"])
                continue
            s = json.loads(row["payload_json"])
            if s.get("state") not in AI_STATES:
                failures.append("AI_STATE:" + row["actor_ref"])
            if float(s.get("attack_cooldown_s", -1.0)) < 0:
                failures.append("AI_COOLDOWN:" + row["actor_ref"])
        erows = self.runtime.conn.execute(
            "SELECT event_hash,actor_ref,event_ref,event_type,payload_json FROM arpg_actor_events WHERE world_instance_id=?",
            (self.world_instance_id,),
        ).fetchall()
        for row in erows:
            events += 1
            payload = json.loads(row["payload_json"])
            if self._event_hash(row["actor_ref"], row["event_type"], payload) != row["event_hash"]:
                failures.append("EVENT_HASH:" + row["event_ref"])
        return {"status": "PASS" if not failures else "FAIL", "failures": failures, "actors": profiles, "ai_states": ai_states, "events": events, "country_source_actors": self.country_source_actor_count(), "materialization": "LAZY_ACTIVE_SET", "authority": self.AUTHORITY}
