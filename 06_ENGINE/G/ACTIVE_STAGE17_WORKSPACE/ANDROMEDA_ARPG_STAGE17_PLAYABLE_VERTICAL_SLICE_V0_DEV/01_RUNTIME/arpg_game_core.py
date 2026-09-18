from __future__ import annotations

import copy
import hashlib
import json
import math
import uuid
import zipfile
from pathlib import Path
from typing import Any

from living_runtime import ValidationError, IntegrityError, ConflictError, canonical_json, sha256_text, new_runtime_id, validate_runtime_id


CANONICAL_INDEX_PATH = "ANDROMEDA_CODEX_MASTER/02_ATLAS/STAGE_08_REFERENCE/01_DATA/ATLAS_ENTITY_INDEX_V1_0.json"
PROFILE_MODES = {"CREATED", "CANONICAL"}
COMMAND_TYPES = {
    "MOVE_POINTER", "POINTER_PRIMARY", "SELECT_TARGET", "PRIMARY_ACTION",
    "CANCEL_ACTION", "PAUSE", "RESUME", "USE_CONSUMABLE",
    "USE_ITEM", "EQUIP_ITEM", "UNEQUIP_ITEM",
    "LEARN_SKILL", "ASSIGN_SKILL", "ACTIVATE_PASSIVE", "USE_SKILL",
}
ACTION_STATES = {"IDLE", "MOVING", "TARGETING", "ACTING", "BLOCKED", "PAUSED"}
DEFAULT_OBJECT_ACTIONS = {
    "DOOR": "OPEN",
    "TRAPDOOR": "OPEN",
    "CHEST": "OPEN",
    "GROUND_WEAPON": "TAKE",
    "BOOK": "READ",
    "TORCH": "LIGHT",
    "CHAIR": "USE",
    "LEVER": "USE",
    "RUNE_PEDESTAL": "USE",
    "CONSOLE": "USE",
}


class ARPGGameCore:
    """Stage 01 server-authoritative ARPG command/state core.

    The Godot/client layer submits intents. This core owns player profiles, active avatar,
    pointer movement intent, target selection, deterministic command sequencing and persistence.
    Numeric player progression/combat values are deliberately deferred to later ARPG stages.
    """

    VERSION = "V0.2.0"
    STAGE = "01/18"
    AUTHORITY = "ARPG_GAME_CORE_SERVER_AUTHORITATIVE_RUNTIME_DERIVATION"
    CONTROL_SCHEME = "MOUSE_POINTER_DIABLO_LIKE"
    NETWORK_MODEL = "SINGLE_PLAYER_FIRST_MULTIPLAYER_READY"
    CLASS_MODEL = "EMERGENT_FROM_PLAYER_CHOICES"
    MAX_PROFILES_PER_WORLD = 12
    MAX_POINTER_DISTANCE_M = 160.0
    DEFAULT_ARRIVAL_TOLERANCE_M = 0.18

    def __init__(self, engine: Any, world_instance_id: str) -> None:
        self.engine = engine
        self.runtime = engine.runtime
        self.world_instance_id = world_instance_id
        self.country = engine.country(world_instance_id)
        self._canonical_character_cache: dict[str, dict[str, Any]] | None = None
        self._init_schema()
        self._recover_active_sessions()

    def _init_schema(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS arpg_player_profiles(
                    world_instance_id TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    slot_index INTEGER NOT NULL,
                    avatar_ref TEXT NOT NULL,
                    origin_mode TEXT NOT NULL,
                    controller_scope TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, profile_ref),
                    UNIQUE(world_instance_id, slot_index),
                    UNIQUE(world_instance_id, avatar_ref)
                );
                CREATE TABLE IF NOT EXISTS arpg_input_state(
                    world_instance_id TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, profile_ref),
                    FOREIGN KEY(world_instance_id, profile_ref)
                      REFERENCES arpg_player_profiles(world_instance_id, profile_ref) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS arpg_command_stream(
                    server_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    world_instance_id TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    client_sequence INTEGER NOT NULL,
                    command_ref TEXT NOT NULL UNIQUE,
                    command_type TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    command_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id, profile_ref, client_sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_arpg_command_world_profile
                    ON arpg_command_stream(world_instance_id, profile_ref, client_sequence);
                """
            )
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('arpg_game_core_version',?)",
                (self.VERSION,),
            )

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> tuple[str, str]:
        text = canonical_json(payload)
        return text, sha256_text(text)

    def _load_canonical_characters(self) -> dict[str, dict[str, Any]]:
        if self._canonical_character_cache is not None:
            return self._canonical_character_cache
        path = self.runtime.master_release_path
        if not path:
            raise IntegrityError("Master release is required for canonical character profiles")
        with zipfile.ZipFile(path, "r") as zf:
            data = json.loads(zf.read(CANONICAL_INDEX_PATH))
        out = {}
        for entry in data.get("entries", []):
            if not isinstance(entry, dict):
                continue
            if entry.get("domain") == "narrativa/personagens" and isinstance(entry.get("id"), str):
                out[entry["id"]] = copy.deepcopy(entry)
        if not out:
            raise IntegrityError("canonical character index is empty")
        self._canonical_character_cache = out
        return out

    def _canonical_character(self, canonical_ref: str) -> dict[str, Any]:
        if not self.runtime.canonical_ref_resolves(canonical_ref):
            raise ValidationError(f"unknown canonical_ref: {canonical_ref}")
        entry = self._load_canonical_characters().get(canonical_ref)
        if not entry:
            raise ValidationError(f"canonical_ref is not a character: {canonical_ref}")
        return copy.deepcopy(entry)

    def _start_city(self, city_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        if city_id:
            city = self.country.city(city_id)
            block = self.country.block(next(b["id"] for s in self.country.world["country"]["states"] for b in s["blocks"] if any(c["id"] == city_id for c in b.get("cities", []))))
            state = self.country.state(block["state_id"])
            return state, block, city
        for state in self.country.world["country"]["states"]:
            for block in state["blocks"]:
                if block.get("root_deep"):
                    continue
                cities = block.get("cities", [])
                if cities:
                    return state, block, cities[0]
        raise IntegrityError("no valid ARPG start city exists")

    def _profile_row(self, profile_ref: str):
        return self.runtime.conn.execute(
            "SELECT * FROM arpg_player_profiles WHERE world_instance_id=? AND profile_ref=?",
            (self.world_instance_id, profile_ref),
        ).fetchone()

    def profile(self, profile_ref: str) -> dict[str, Any]:
        row = self._profile_row(profile_ref)
        if not row:
            raise KeyError(profile_ref)
        if sha256_text(row["payload_json"]) != row["payload_hash"]:
            raise IntegrityError("ARPG profile hash mismatch")
        body = json.loads(row["payload_json"])
        body["active"] = bool(row["active"])
        return body

    def list_profiles(self) -> list[dict[str, Any]]:
        rows = self.runtime.conn.execute(
            "SELECT profile_ref FROM arpg_player_profiles WHERE world_instance_id=? ORDER BY slot_index",
            (self.world_instance_id,),
        ).fetchall()
        return [self.profile(r["profile_ref"]) for r in rows]

    def _input(self, profile_ref: str) -> dict[str, Any]:
        row = self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_input_state WHERE world_instance_id=? AND profile_ref=?",
            (self.world_instance_id, profile_ref),
        ).fetchone()
        if not row:
            raise IntegrityError("ARPG input state missing")
        if sha256_text(row["payload_json"]) != row["payload_hash"]:
            raise IntegrityError("ARPG input state hash mismatch")
        return json.loads(row["payload_json"])

    def _save_input(self, profile_ref: str, state: dict[str, Any]) -> None:
        text, h = self._hash_payload(state)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO arpg_input_state VALUES(?,?,?,?)",
                (self.world_instance_id, profile_ref, text, h),
            )

    def _save_profile(self, profile: dict[str, Any], active: bool) -> None:
        body = copy.deepcopy(profile)
        body.pop("active", None)
        text, h = self._hash_payload(body)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT INTO arpg_player_profiles VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    self.world_instance_id, body["profile_ref"], body["slot_index"], body["avatar_ref"],
                    body["origin_mode"], body["controller_scope"], 1 if active else 0, text, h,
                ),
            )

    def _session_ref(self, profile_ref: str) -> str:
        return "ARPG-" + hashlib.sha256(profile_ref.encode()).hexdigest()[:24]

    def _recover_active_sessions(self) -> None:
        for p in self.list_profiles():
            if p.get("active"):
                self.engine.godot(self.world_instance_id).bind_session(self._session_ref(p["profile_ref"]), p["avatar_ref"], role="PLAYER")

    def _spawn_avatar(self, *, display_name: str, origin_mode: str, canonical_ref: str | None, start_city_id: str | None, profile_ref: str) -> str:
        state, block, city = self._start_city(start_city_id)
        avatar_ref = "PLY-" + uuid.uuid4().hex.upper()
        avatar = {
            "id": avatar_ref,
            "name": display_name,
            "name_status": "CANONICAL_REFERENCE_READ_ONLY" if origin_mode == "CANONICAL" else "PLAYER_DEFINED_RUNTIME",
            "class": "PLAYER_AVATAR",
            "emergent_class": None,
            "class_model": self.CLASS_MODEL,
            "tier": "BAIXO",
            "age": None,
            "status": "ACTIVE",
            "state_id": state["id"],
            "block_id": block["id"],
            "city_id": city["id"],
            "scene_id": None,
            "protection": {"protected": False, "combat_targetable": True, "hazardous_labor_allowed": True, "exploitation_allowed": False},
            "inventory": {},
            "item_instances": [],
            "knowledge_tags": [],
            "active_light": None,
            "wallet": {"currency": "CREDIT_RUNTIME", "balance": 0.0},
            "health": 100,
            "reputation": 0,
            "arpg_profile_ref": profile_ref,
            "avatar_origin_mode": origin_mode,
            "canonical_ref": canonical_ref,
            "runtime_balance_authority": "ARPG_STAGE01_PLACEHOLDER_NOT_CANON",
        }
        city["npcs"].append(avatar)
        self.country.reconcile_country_inventory()
        self.country._record_event(
            "ARPG_PLAYER_AVATAR_CREATED",
            {"avatar_ref": avatar_ref, "profile_ref": profile_ref, "origin_mode": origin_mode, "canonical_ref": canonical_ref, "authority": self.AUTHORITY},
        )
        # Existing V1.5 systems were bootstrapped before profile creation; register the new avatar into them.
        self.engine.movement(self.world_instance_id).bootstrap()
        self.engine.streaming(self.world_instance_id).bootstrap_country_npcs()
        self.engine.bridge(self.world_instance_id).ensure_npc(avatar_ref)
        return avatar_ref

    def create_profile(
        self,
        controller_scope: str,
        *,
        origin_mode: str = "CREATED",
        display_name: str | None = None,
        canonical_ref: str | None = None,
        start_city_id: str | None = None,
        slot_index: int | None = None,
        activate: bool = True,
        profile_ref: str | None = None,
    ) -> dict[str, Any]:
        origin_mode = str(origin_mode).upper().strip()
        if origin_mode not in PROFILE_MODES:
            raise ValidationError("origin_mode must be CREATED or CANONICAL")
        controller_scope = str(controller_scope).strip()
        if not controller_scope:
            raise ValidationError("controller_scope is required")
        profiles = self.list_profiles()
        if len(profiles) >= self.MAX_PROFILES_PER_WORLD:
            raise ConflictError("maximum ARPG profiles reached")
        used = {p["slot_index"] for p in profiles}
        if slot_index is None:
            slot_index = next(i for i in range(self.MAX_PROFILES_PER_WORLD) if i not in used)
        if not isinstance(slot_index, int) or isinstance(slot_index, bool) or not (0 <= slot_index < self.MAX_PROFILES_PER_WORLD) or slot_index in used:
            raise ValidationError("invalid or occupied slot_index")

        canon_entry = None
        if origin_mode == "CANONICAL":
            if not canonical_ref:
                raise ValidationError("canonical profile requires canonical_ref")
            if any(p.get("origin_mode") == "CANONICAL" and p.get("canonical_ref") == canonical_ref for p in profiles):
                raise ConflictError("canonical character already has a profile in this world")
            canon_entry = self._canonical_character(canonical_ref)
            if display_name is not None and str(display_name).strip() != canon_entry.get("name"):
                raise ValidationError("canonical character display name cannot override Master")
            display_name = canon_entry.get("name")
        else:
            if canonical_ref is not None:
                raise ValidationError("created profile cannot declare canonical_ref")
            display_name = str(display_name or "").strip()
            if not display_name or len(display_name) > 48:
                raise ValidationError("created profile display_name must contain 1-48 characters")

        # Fase 8.3 (Stage17, 14/09): profile_ref agora pode ser fornecido
        # explicitamente (validado no mesmo formato que new_runtime_id ja
        # produz) - permite que PlanetSystem.transfer_profile() preserve a
        # MESMA identidade de profile_ref num motor de outro territorio (dbs
        # separados, sem risco de colisao, ja que o id e um UUID). Default
        # None preserva 100% o comportamento existente (gera um novo).
        if profile_ref is not None:
            validate_runtime_id(profile_ref, "player_profile")
            if self.runtime.conn.execute(
                "SELECT 1 FROM arpg_player_profiles WHERE world_instance_id=? AND profile_ref=?",
                (self.world_instance_id, profile_ref),
            ).fetchone():
                raise ConflictError("profile_ref already exists in this world")
        else:
            profile_ref = new_runtime_id("player_profile")
        avatar_ref = self._spawn_avatar(
            display_name=display_name,
            origin_mode=origin_mode,
            canonical_ref=canonical_ref,
            start_city_id=start_city_id,
            profile_ref=profile_ref,
        )
        profile = {
            "profile_ref": profile_ref,
            "world_instance_id": self.world_instance_id,
            "slot_index": slot_index,
            "controller_scope": controller_scope,
            "origin_mode": origin_mode,
            "canonical_ref": canonical_ref,
            "display_name": display_name,
            "avatar_ref": avatar_ref,
            "control_scheme": self.CONTROL_SCHEME,
            "network_model": self.NETWORK_MODEL,
            "server_authoritative": True,
            "progression": {
                "class_model": self.CLASS_MODEL,
                "emergent_class": None,
                "evidence": {},
                "authority": "CANON_BOUNDED_RUNTIME_BUILD" if origin_mode == "CANONICAL" else "RUNTIME_GAMEPLAY_BUILD",
            },
            "canonical_character_metadata": canon_entry,
            "art_dependency": "NONE_PLACEHOLDER_READY",
            "authority": self.AUTHORITY,
        }
        self._save_profile(profile, active=False)
        inp = {
            "last_client_sequence": 0,
            "selected_target_ref": None,
            "selected_target_kind": None,
            "action_state": "IDLE",
            "move_target": None,
            "move_mode": "RUN",
            "arrival_tolerance_m": self.DEFAULT_ARRIVAL_TOLERANCE_M,
            "last_block_reason": None,
        }
        self._save_input(profile_ref, inp)
        if activate:
            self.activate_profile(profile_ref, controller_scope=controller_scope)
        # Stage 02+ character progression is attached lazily so Stage 01 remains backward-compatible.
        try:
            self.engine.character(self.world_instance_id).ensure_profile(profile_ref)
        except (AttributeError, KeyError):
            pass
        # Stage 07+ actor/AI overlay is likewise optional for older engines.
        try:
            self.engine.actors_arpg(self.world_instance_id).ensure_profile(profile_ref)
        except (AttributeError, KeyError):
            pass
        # Stage 08+ world context is lazy and optional so earlier engines remain byte-contract compatible.
        try:
            self.engine.world_arpg(self.world_instance_id).ensure_profile(profile_ref)
        except (AttributeError, KeyError):
            pass
        return {"status": "PASS", "profile": self.profile(profile_ref), "input_state": self._input(profile_ref), "authority": self.AUTHORITY}

    def activate_profile(self, profile_ref: str, *, controller_scope: str) -> dict[str, Any]:
        profile = self.profile(profile_ref)
        if profile["controller_scope"] != controller_scope:
            return {"status": "REJECTED", "reason": "PROFILE_OWNERSHIP_MISMATCH"}
        with self.runtime._write_lock:
            # Single-player uses one local controller. Future multiplayer may have one active
            # profile per controller simultaneously; activation therefore never globally disables
            # another controller's avatar.
            self.runtime.conn.execute(
                "UPDATE arpg_player_profiles SET active=0 WHERE world_instance_id=? AND controller_scope=?",
                (self.world_instance_id, controller_scope),
            )
            self.runtime.conn.execute(
                "UPDATE arpg_player_profiles SET active=1 WHERE world_instance_id=? AND profile_ref=?",
                (self.world_instance_id, profile_ref),
            )
        session = self._session_ref(profile_ref)
        bound = self.engine.godot(self.world_instance_id).bind_session(session, profile["avatar_ref"], role="PLAYER")
        return {"status": bound.get("status"), "profile_ref": profile_ref, "avatar_ref": profile["avatar_ref"], "session_ref": session, "authority": self.AUTHORITY}

    def active_profile(self, controller_scope: str | None = None) -> dict[str, Any] | None:
        if controller_scope is None:
            rows = self.runtime.conn.execute(
                "SELECT profile_ref FROM arpg_player_profiles WHERE world_instance_id=? AND active=1 ORDER BY slot_index",
                (self.world_instance_id,),
            ).fetchall()
            if len(rows) > 1:
                raise ConflictError("multiple active controllers; controller_scope is required")
            return self.profile(rows[0]["profile_ref"]) if rows else None
        row = self.runtime.conn.execute(
            "SELECT profile_ref FROM arpg_player_profiles WHERE world_instance_id=? AND controller_scope=? AND active=1",
            (self.world_instance_id, controller_scope),
        ).fetchone()
        return self.profile(row["profile_ref"]) if row else None

    def _assert_owner(self, profile: dict[str, Any], controller_scope: str) -> None:
        if profile["controller_scope"] != controller_scope:
            raise ConflictError("PROFILE_OWNERSHIP_MISMATCH")
        if not profile.get("active"):
            raise ConflictError("PROFILE_NOT_ACTIVE")

    def _resolve_target(self, avatar_ref: str, target_ref: str) -> dict[str, Any]:
        if target_ref == avatar_ref:
            return {"status": "REJECTED", "reason": "SELF_TARGET_NOT_ALLOWED"}
        try:
            npc = self.country.npc(target_ref)
            return {"status": "PASS", "kind": "NPC", "target_ref": target_ref, "data": {"class": npc.get("class"), "block_id": npc.get("block_id"), "city_id": npc.get("city_id")}}
        except KeyError:
            pass
        try:
            _b, _c, _d, obj = self.engine.scenes(self.world_instance_id).scene_object(target_ref)
            return {"status": "PASS", "kind": "SCENE_OBJECT", "target_ref": target_ref, "data": {"object_type": obj.get("object_type")}}
        except KeyError:
            pass
        try:
            ent = self.runtime.get_entity(self.world_instance_id, target_ref)
            if ent.get("lifecycle") != "ACTIVE":
                return {"status": "REJECTED", "reason": "TARGET_NOT_ACTIVE"}
            return {"status": "PASS", "kind": "RUNTIME_ENTITY", "target_ref": target_ref, "data": {"entity_kind": ent.get("entity_kind")}}
        except Exception:
            return {"status": "REJECTED", "reason": "TARGET_NOT_FOUND"}

    def _set_target(self, profile: dict[str, Any], target_ref: str | None) -> dict[str, Any]:
        state = self._input(profile["profile_ref"])
        if not target_ref:
            state.update({"selected_target_ref": None, "selected_target_kind": None, "action_state": "IDLE" if not state.get("move_target") else "MOVING"})
            self._save_input(profile["profile_ref"], state)
            return {"status": "PASS", "cleared": True}
        target = self._resolve_target(profile["avatar_ref"], str(target_ref))
        if target["status"] != "PASS":
            return target
        state.update({"selected_target_ref": target["target_ref"], "selected_target_kind": target["kind"], "action_state": "TARGETING"})
        self._save_input(profile["profile_ref"], state)
        return {"status": "PASS", "target": target}

    def _move_pointer(self, profile: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        try:
            tx = float(params["iso_x_m"])
            ty = float(params["iso_y_m"])
        except Exception as exc:
            raise ValidationError("MOVE_POINTER requires finite iso_x_m and iso_y_m") from exc
        if not math.isfinite(tx) or not math.isfinite(ty):
            raise ValidationError("MOVE_POINTER requires finite coordinates")
        mode = str(params.get("mode", "RUN")).upper()
        if mode not in self.engine.movement(self.world_instance_id).SPEEDS_MPS:
            return {"status": "REJECTED", "reason": "UNSUPPORTED_MOVE_MODE"}
        tolerance = float(params.get("arrival_tolerance_m", self.DEFAULT_ARRIVAL_TOLERANCE_M))
        if not math.isfinite(tolerance) or not (0.05 <= tolerance <= 2.0):
            raise ValidationError("arrival_tolerance_m out of range")
        cur = self.engine.movement(self.world_instance_id).state(profile["avatar_ref"])
        distance = math.hypot(tx - cur["iso_x_m"], ty - cur["iso_y_m"])
        if distance > self.MAX_POINTER_DISTANCE_M:
            return {"status": "REJECTED", "reason": "POINTER_DESTINATION_OUT_OF_LOCAL_RANGE", "distance_m": round(distance, 4), "max_distance_m": self.MAX_POINTER_DISTANCE_M}
        geo = self.engine.spatial(self.world_instance_id).isometric_to_geodetic(tx, ty, cur["altitude_m"])
        box = list(map(float, self.country.world["country"]["bounding_region"]))
        if not (box[0] <= geo["longitude"] <= box[2] and box[1] <= geo["latitude"] <= box[3]):
            return {"status": "REJECTED", "reason": "POINTER_DESTINATION_OUTSIDE_COUNTRY"}
        state = self._input(profile["profile_ref"])
        state.update({
            "move_target": {"iso_x_m": tx, "iso_y_m": ty},
            "move_mode": mode,
            "arrival_tolerance_m": tolerance,
            "action_state": "MOVING" if distance > tolerance else "IDLE",
            "last_block_reason": None,
        })
        if distance <= tolerance:
            state["move_target"] = None
        self._save_input(profile["profile_ref"], state)
        return {"status": "PASS", "movement_intent": "ARRIVED" if distance <= tolerance else "STARTED", "distance_m": round(distance, 6), "target": state.get("move_target"), "mode": mode}

    def _primary_action(self, profile: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        state = self._input(profile["profile_ref"])
        ref = state.get("selected_target_ref")
        kind = state.get("selected_target_kind")
        if not ref:
            return {"status": "REJECTED", "reason": "NO_SELECTED_TARGET"}
        resolved = self._resolve_target(profile["avatar_ref"], ref)
        if resolved["status"] != "PASS":
            state.update({"selected_target_ref": None, "selected_target_kind": None, "action_state": "IDLE"})
            self._save_input(profile["profile_ref"], state)
            return resolved
        state["action_state"] = "ACTING"
        self._save_input(profile["profile_ref"], state)
        if kind == "SCENE_OBJECT":
            object_type = (resolved.get("data") or {}).get("object_type")
            action = str(params.get("interaction_action") or DEFAULT_OBJECT_ACTIONS.get(object_type, "USE")).upper()
            out = self.engine.collision(self.world_instance_id).interact(profile["avatar_ref"], ref, action, float(params.get("max_distance_m", 2.5)))
            state = self._input(profile["profile_ref"])
            state["action_state"] = "TARGETING" if out.get("status") == "PASS" else "IDLE"
            self._save_input(profile["profile_ref"], state)
            return {"status": out.get("status", "REJECTED"), "route": "INTERACTION", "resolved_action": action, "result": out}
        if kind == "NPC":
            # Stage07 makes hostility authoritative: hostile actors can be attacked by the normal
            # primary pointer action; neutral/protected NPCs keep the legacy explicit-combat gate.
            auto_hostile = False
            hostility = None
            try:
                hostility = self.engine.actors_arpg(self.world_instance_id).hostility_to_profile(ref, profile["profile_ref"])
                auto_hostile = bool(hostility.get("hostile"))
            except (AttributeError, KeyError, ValidationError):
                pass
            if bool(params.get("combat_intent", False)) or auto_hostile:
                try:
                    out = self.engine.combat_arpg(self.world_instance_id).player_attack(
                        profile["profile_ref"], ref,
                        event_ref=str(params.get("_combat_event_ref") or ("manual:" + profile["profile_ref"] + ":" + ref)),
                        damage_type=str(params.get("damage_type", "PHYSICAL")),
                    )
                except (AttributeError, KeyError):
                    out = {"status": "REJECTED", "reason": "COMBAT_CORE_NOT_ATTACHED"}
                state = self._input(profile["profile_ref"]); state["action_state"] = "TARGETING" if out.get("status") == "PASS" else "IDLE"; self._save_input(profile["profile_ref"], state)
                return {"status": out.get("status", "REJECTED"), "route": "COMBAT", "resolved_action": "BASIC_ATTACK", "result": out, "target_ref": ref, "hostility": hostility, "auto_hostile": auto_hostile}
            state = self._input(profile["profile_ref"]); state["action_state"] = "TARGETING"; self._save_input(profile["profile_ref"], state)
            return {"status": "PASS", "route": "NPC_CONTEXT", "resolved_action": "COMBAT_OR_DIALOGUE_GATE", "implementation_stage": "COMBAT_STAGE03_DIALOGUE_STAGE11", "combat_activation_policy": "EXPLICIT_COMBAT_INTENT_UNTIL_STAGE08_HOSTILITY", "active_hostility_policy": "STAGE07_RUNTIME_HOSTILITY_WHEN_ATTACHED", "hostility": hostility, "target_ref": ref}
        state = self._input(profile["profile_ref"]); state["action_state"] = "TARGETING"; self._save_input(profile["profile_ref"], state)
        return {"status": "PASS", "route": "RUNTIME_ENTITY_CONTEXT", "resolved_action": "COMBAT_OR_LOOT_GATE", "implementation_stage": "COMBAT_STAGE03_LOOT_STAGE06", "target_ref": ref}

    def _execute_command(self, profile: dict[str, Any], command_type: str, params: dict[str, Any]) -> dict[str, Any]:
        # CharacterCore owns vital-state authority. Dead avatars may still pause, resume,
        # cancel UI intent or inspect a target, but cannot move or execute primary actions.
        if command_type in {"MOVE_POINTER", "PRIMARY_ACTION", "POINTER_PRIMARY", "USE_CONSUMABLE", "USE_ITEM", "EQUIP_ITEM", "UNEQUIP_ITEM", "USE_SKILL"}:
            try:
                gate = self.engine.character(self.world_instance_id).can_act(profile["profile_ref"])
            except (AttributeError, KeyError):
                gate = {"status": "PASS"}
            if gate.get("status") == "PASS":
                try:
                    gate = self.engine.combat_arpg(self.world_instance_id).can_player_act(profile["profile_ref"])
                except (AttributeError, KeyError):
                    pass
            if gate.get("status") != "PASS":
                return {"status": "REJECTED", "reason": gate.get("reason", "CHARACTER_CANNOT_ACT"), "life_state": gate.get("life_state")}
        if command_type == "MOVE_POINTER":
            return self._move_pointer(profile, params)
        if command_type == "SELECT_TARGET":
            return self._set_target(profile, params.get("target_ref"))
        if command_type == "PRIMARY_ACTION":
            return self._primary_action(profile, params)
        if command_type == "POINTER_PRIMARY":
            target_ref = params.get("target_ref")
            if target_ref:
                sel = self._set_target(profile, str(target_ref))
                if sel.get("status") != "PASS":
                    return sel
                return self._primary_action(profile, params)
            if "iso_x_m" in params and "iso_y_m" in params:
                return self._move_pointer(profile, params)
            return {"status": "REJECTED", "reason": "POINTER_PRIMARY_REQUIRES_TARGET_OR_WORLD_POINT"}
        if command_type == "USE_CONSUMABLE":
            try:
                out = self.engine.resources_arpg(self.world_instance_id).use_consumable(
                    profile["profile_ref"], str(params.get("consumable_ref", "")),
                    event_ref=str(params.get("_resource_event_ref") or ("manual:resource:" + profile["profile_ref"])),
                )
            except ValidationError as exc:
                out = {"status": "REJECTED", "reason": str(exc)}
            except (AttributeError, KeyError):
                out = {"status": "REJECTED", "reason": "RESOURCE_CORE_NOT_ATTACHED"}
            return {"status": out.get("status", "REJECTED"), "route": "CONSUMABLE", "resolved_action": "USE_CONSUMABLE", "result": out}
        if command_type == "USE_ITEM":
            try:
                out = self.engine.items_arpg(self.world_instance_id).use_consumable(
                    profile["profile_ref"], str(params.get("item_ref", "")),
                    event_ref=str(params.get("_item_event_ref") or ("manual:item:use:" + profile["profile_ref"])),
                )
            except ValidationError as exc:
                out = {"status": "REJECTED", "reason": str(exc)}
            except (AttributeError, KeyError):
                out = {"status": "REJECTED", "reason": "ITEM_CORE_NOT_ATTACHED"}
            return {"status": out.get("status", "REJECTED"), "route": "ITEM", "resolved_action": "USE_ITEM", "result": out}
        if command_type == "EQUIP_ITEM":
            try:
                out = self.engine.items_arpg(self.world_instance_id).equip(
                    profile["profile_ref"], str(params.get("instance_ref", "")), str(params.get("slot", "")),
                    event_ref=str(params.get("_item_event_ref") or ("manual:item:equip:" + profile["profile_ref"])),
                )
            except ValidationError as exc:
                out = {"status": "REJECTED", "reason": str(exc)}
            except (AttributeError, KeyError):
                out = {"status": "REJECTED", "reason": "ITEM_CORE_NOT_ATTACHED"}
            return {"status": out.get("status", "REJECTED"), "route": "ITEM", "resolved_action": "EQUIP_ITEM", "result": out}
        if command_type == "LEARN_SKILL":
            try:
                out = self.engine.skills_arpg(self.world_instance_id).learn_skill(
                    profile["profile_ref"], str(params.get("skill_ref", "")),
                    event_ref=str(params.get("_skill_event_ref") or ("manual:skill:learn:" + profile["profile_ref"])),
                    source_type=str(params.get("source_type", "TRAINING")), source_ref=str(params.get("source_ref", "GAME_CORE")),
                )
            except ValidationError as exc:
                out = {"status":"REJECTED","reason":str(exc)}
            except (AttributeError, KeyError):
                out = {"status":"REJECTED","reason":"SKILL_CORE_NOT_ATTACHED"}
            return {"status":out.get("status","REJECTED"),"route":"SKILL","resolved_action":"LEARN_SKILL","result":out}
        if command_type == "ASSIGN_SKILL":
            try:
                out = self.engine.skills_arpg(self.world_instance_id).assign_active(profile["profile_ref"], str(params.get("skill_ref", "")), int(params.get("slot", 0)), event_ref=str(params.get("_skill_event_ref") or ("manual:skill:assign:" + profile["profile_ref"])))
            except (ValidationError, ValueError, TypeError) as exc:
                out = {"status":"REJECTED","reason":str(exc)}
            except (AttributeError, KeyError):
                out = {"status":"REJECTED","reason":"SKILL_CORE_NOT_ATTACHED"}
            return {"status":out.get("status","REJECTED"),"route":"SKILL","resolved_action":"ASSIGN_SKILL","result":out}
        if command_type == "ACTIVATE_PASSIVE":
            try:
                out = self.engine.skills_arpg(self.world_instance_id).activate_passive(profile["profile_ref"], str(params.get("skill_ref", "")), int(params.get("slot", 0)), event_ref=str(params.get("_skill_event_ref") or ("manual:skill:passive:" + profile["profile_ref"])))
            except (ValidationError, ValueError, TypeError) as exc:
                out = {"status":"REJECTED","reason":str(exc)}
            except (AttributeError, KeyError):
                out = {"status":"REJECTED","reason":"SKILL_CORE_NOT_ATTACHED"}
            return {"status":out.get("status","REJECTED"),"route":"SKILL","resolved_action":"ACTIVATE_PASSIVE","result":out}
        if command_type == "USE_SKILL":
            try:
                skills = self.engine.skills_arpg(self.world_instance_id)
                target_ref = params.get("target_ref") or self._input(profile["profile_ref"]).get("selected_target_ref")
                if params.get("slot") is not None:
                    out = skills.use_slot(profile["profile_ref"], int(params.get("slot")), event_ref=str(params.get("_skill_event_ref") or ("manual:skill:use:" + profile["profile_ref"])), target_ref=target_ref)
                else:
                    out = skills.use_skill(profile["profile_ref"], str(params.get("skill_ref", "")), event_ref=str(params.get("_skill_event_ref") or ("manual:skill:use:" + profile["profile_ref"])), target_ref=target_ref)
            except (ValidationError, ValueError, TypeError) as exc:
                out = {"status":"REJECTED","reason":str(exc)}
            except (AttributeError, KeyError):
                out = {"status":"REJECTED","reason":"SKILL_CORE_NOT_ATTACHED"}
            return {"status":out.get("status","REJECTED"),"route":"SKILL","resolved_action":"USE_SKILL","result":out}
        if command_type == "UNEQUIP_ITEM":
            try:
                out = self.engine.items_arpg(self.world_instance_id).unequip(
                    profile["profile_ref"], str(params.get("slot", "")),
                    event_ref=str(params.get("_item_event_ref") or ("manual:item:unequip:" + profile["profile_ref"])),
                )
            except ValidationError as exc:
                out = {"status": "REJECTED", "reason": str(exc)}
            except (AttributeError, KeyError):
                out = {"status": "REJECTED", "reason": "ITEM_CORE_NOT_ATTACHED"}
            return {"status": out.get("status", "REJECTED"), "route": "ITEM", "resolved_action": "UNEQUIP_ITEM", "result": out}
        if command_type == "CANCEL_ACTION":
            state = self._input(profile["profile_ref"])
            state.update({"move_target": None, "action_state": "IDLE", "last_block_reason": None})
            if params.get("clear_target", False):
                state.update({"selected_target_ref": None, "selected_target_kind": None})
            self._save_input(profile["profile_ref"], state)
            return {"status": "PASS", "cancelled": True}
        if command_type == "PAUSE":
            self.runtime.set_clock_state(self.world_instance_id, "PAUSED")
            state = self._input(profile["profile_ref"]); state["action_state"] = "PAUSED"; self._save_input(profile["profile_ref"], state)
            return {"status": "PASS", "clock_state": "PAUSED"}
        if command_type == "RESUME":
            self.runtime.set_clock_state(self.world_instance_id, "RUNNING")
            state = self._input(profile["profile_ref"]); state["action_state"] = "MOVING" if state.get("move_target") else ("TARGETING" if state.get("selected_target_ref") else "IDLE"); self._save_input(profile["profile_ref"], state)
            return {"status": "PASS", "clock_state": "RUNNING"}
        return {"status": "REJECTED", "reason": "UNSUPPORTED_ARPG_COMMAND"}

    def submit_command(
        self,
        controller_scope: str,
        profile_ref: str,
        client_sequence: int,
        command_type: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        profile = self.profile(profile_ref)
        try:
            self._assert_owner(profile, controller_scope)
        except ConflictError as exc:
            return {"status": "REJECTED", "reason": str(exc)}
        if not isinstance(client_sequence, int) or isinstance(client_sequence, bool) or client_sequence <= 0:
            raise ValidationError("client_sequence must be a positive integer")
        command_type = str(command_type).upper().strip()
        if command_type not in COMMAND_TYPES:
            return {"status": "REJECTED", "reason": "UNSUPPORTED_ARPG_COMMAND", "command_type": command_type}
        params = copy.deepcopy(parameters or {})
        params_text = canonical_json(params)
        command_hash = sha256_text(canonical_json({"profile_ref": profile_ref, "client_sequence": client_sequence, "command_type": command_type, "parameters": params}))
        existing = self.runtime.conn.execute(
            "SELECT * FROM arpg_command_stream WHERE world_instance_id=? AND profile_ref=? AND client_sequence=?",
            (self.world_instance_id, profile_ref, client_sequence),
        ).fetchone()
        if existing:
            if existing["command_hash"] != command_hash:
                return {"status": "REJECTED", "reason": "CLIENT_SEQUENCE_CONFLICT", "client_sequence": client_sequence}
            out = json.loads(existing["result_json"])
            out["idempotent_replay"] = True
            out["server_sequence"] = existing["server_sequence"]
            return out
        state = self._input(profile_ref)
        expected = int(state["last_client_sequence"]) + 1
        if client_sequence != expected:
            return {"status": "REJECTED", "reason": "OUT_OF_ORDER_CLIENT_SEQUENCE", "expected": expected, "received": client_sequence}
        internal_params = copy.deepcopy(params)
        internal_params["_combat_event_ref"] = f"cmd:{profile_ref}:{client_sequence}"
        internal_params["_resource_event_ref"] = f"cmd:{profile_ref}:{client_sequence}:resource"
        internal_params["_item_event_ref"] = f"cmd:{profile_ref}:{client_sequence}:item"
        internal_params["_skill_event_ref"] = f"cmd:{profile_ref}:{client_sequence}:skill"
        result = self._execute_command(profile, command_type, internal_params)
        command_ref = new_runtime_id("command")
        stored = {
            **copy.deepcopy(result),
            "command_ref": command_ref,
            "client_sequence": client_sequence,
            "command_type": command_type,
            "server_authoritative": True,
            "idempotent_replay": False,
            "authority": self.AUTHORITY,
        }
        result_text = canonical_json(stored)
        with self.runtime._write_lock:
            cur = self.runtime.conn.execute(
                "INSERT INTO arpg_command_stream(world_instance_id,profile_ref,client_sequence,command_ref,command_type,parameters_json,result_json,command_hash) VALUES(?,?,?,?,?,?,?,?)",
                (self.world_instance_id, profile_ref, client_sequence, command_ref, command_type, params_text, result_text, command_hash),
            )
            server_sequence = cur.lastrowid
        state = self._input(profile_ref)
        state["last_client_sequence"] = client_sequence
        self._save_input(profile_ref, state)
        stored["server_sequence"] = server_sequence
        return stored

    def tick(self, profile_ref: str, *, delta_s: float = 1.0 / 60.0) -> dict[str, Any]:
        profile = self.profile(profile_ref)
        if not profile.get("active"):
            return {"status": "REJECTED", "reason": "PROFILE_NOT_ACTIVE"}
        if not math.isfinite(float(delta_s)) or float(delta_s) <= 0 or float(delta_s) > 0.5:
            raise ValidationError("delta_s must be >0 and <=0.5")
        if self.runtime.get_clock(self.world_instance_id)["state"] == "PAUSED":
            return {"status": "PASS", "frame_state": "PAUSED", "moved_m": 0.0}
        character_tick = None
        combat_tick = None
        try:
            gate = self.engine.character(self.world_instance_id).can_act(profile_ref)
            character_tick = self.engine.character(self.world_instance_id).tick_profile(profile_ref, float(delta_s))
        except (AttributeError, KeyError):
            gate = {"status": "PASS"}
        try:
            combat_tick = self.engine.combat_arpg(self.world_instance_id).tick_player(profile_ref, float(delta_s))
            if gate.get("status") == "PASS":
                gate = self.engine.combat_arpg(self.world_instance_id).can_player_act(profile_ref)
        except (AttributeError, KeyError):
            combat_tick = None
        resource_tick = None
        try:
            resource_tick = self.engine.resources_arpg(self.world_instance_id).tick_profile(profile_ref, float(delta_s))
        except (AttributeError, KeyError):
            resource_tick = None
        if gate.get("status") != "PASS":
            state = self._input(profile_ref)
            if state.get("move_target") is not None or state.get("action_state") not in {"IDLE", "PAUSED"}:
                state.update({"move_target": None, "action_state": "IDLE", "last_block_reason": gate.get("reason")})
                self._save_input(profile_ref, state)
            frame = "DEAD" if gate.get("life_state") == "DEAD" else "CONTROL_LOCKED"
            return {"status": "PASS", "frame_state": frame, "moved_m": 0.0, "character": character_tick, "combat": combat_tick, "resources": resource_tick, "reason": gate.get("reason")}
        state = self._input(profile_ref)
        target = state.get("move_target")
        if not target:
            return {"status": "PASS", "frame_state": state.get("action_state", "IDLE"), "moved_m": 0.0}
        mover = self.engine.movement(self.world_instance_id)
        cur = mover.state(profile["avatar_ref"])
        dx = float(target["iso_x_m"]) - cur["iso_x_m"]
        dy = float(target["iso_y_m"]) - cur["iso_y_m"]
        distance = math.hypot(dx, dy)
        tolerance = float(state.get("arrival_tolerance_m", self.DEFAULT_ARRIVAL_TOLERANCE_M))
        if distance <= tolerance:
            state.update({"move_target": None, "action_state": "TARGETING" if state.get("selected_target_ref") else "IDLE", "last_block_reason": None})
            self._save_input(profile_ref, state)
            return {"status": "PASS", "frame_state": "ARRIVED", "moved_m": 0.0, "remaining_m": round(distance, 6)}
        env = self.engine.environment(self.world_instance_id).state_for_block(self.country.npc(profile["avatar_ref"])["block_id"])
        mode = str(state.get("move_mode", "RUN")).upper()
        speed = mover.SPEEDS_MPS[mode] * float(env["movement_factor"])
        duration = min(float(delta_s), max(0.001, distance / max(speed, 1e-9)))
        out = self.engine.godot(self.world_instance_id).command(profile["avatar_ref"], "MOVE_VECTOR", {"dx": dx, "dy": dy, "duration_s": duration, "mode": mode})
        if out.get("status") != "PASS":
            state.update({"move_target": None, "action_state": "BLOCKED", "last_block_reason": out.get("reason") or "MOVEMENT_REJECTED"})
            self._save_input(profile_ref, state)
            return {"status": "PASS", "frame_state": "BLOCKED", "moved_m": 0.0, "movement_result": out}
        cur2 = mover.state(profile["avatar_ref"])
        remaining = math.hypot(float(target["iso_x_m"]) - cur2["iso_x_m"], float(target["iso_y_m"]) - cur2["iso_y_m"])
        arrived = remaining <= tolerance
        if arrived:
            state.update({"move_target": None, "action_state": "TARGETING" if state.get("selected_target_ref") else "IDLE", "last_block_reason": None})
            self._save_input(profile_ref, state)
        return {"status": "PASS", "frame_state": "ARRIVED" if arrived else "MOVING", "moved_m": out.get("moved_m", 0.0), "remaining_m": round(remaining, 6), "movement_result": out}

    def client_snapshot(self, profile_ref: str) -> dict[str, Any]:
        profile = self.profile(profile_ref)
        input_state = self._input(profile_ref)
        base = self.engine.godot(self.world_instance_id).snapshot(profile["avatar_ref"])
        try:
            character_state = self.engine.character(self.world_instance_id).ensure_profile(profile_ref)
        except (AttributeError, KeyError):
            character_state = None
        try:
            combat_state = self.engine.combat_arpg(self.world_instance_id).player_snapshot(profile_ref, input_state.get("selected_target_ref"))
        except (AttributeError, KeyError):
            combat_state = None
        try:
            resource_state = self.engine.resources_arpg(self.world_instance_id).snapshot(profile_ref)
        except (AttributeError, KeyError):
            resource_state = None
        try:
            item_state = self.engine.items_arpg(self.world_instance_id).ensure_inventory(profile_ref)
        except (AttributeError, KeyError):
            item_state = None
        try:
            skill_state = self.engine.skills_arpg(self.world_instance_id).snapshot(profile_ref)
        except (AttributeError, KeyError):
            skill_state = None
        try:
            actor_state = self.engine.actors_arpg(self.world_instance_id).snapshot(profile_ref, input_state.get("selected_target_ref"))
        except (AttributeError, KeyError):
            actor_state = None
        return {
            "status": "PASS",
            "profile": profile,
            "input_state": input_state,
            "character": character_state,
            "combat": combat_state,
            "resources": resource_state,
            "items": item_state,
            "skills": skill_state,
            "actors": actor_state,
            "player": base,
            "clock_state": self.runtime.get_clock(self.world_instance_id)["state"],
            "server_authoritative": True,
            "control_scheme": self.CONTROL_SCHEME,
            "network_model": self.NETWORK_MODEL,
            "art_dependency": "NONE_PLACEHOLDER_READY",
            "authority": self.AUTHORITY,
        }

    def command_history(self, profile_ref: str) -> list[dict[str, Any]]:
        rows = self.runtime.conn.execute(
            "SELECT server_sequence,client_sequence,command_ref,command_type,parameters_json,result_json,command_hash FROM arpg_command_stream WHERE world_instance_id=? AND profile_ref=? ORDER BY client_sequence",
            (self.world_instance_id, profile_ref),
        ).fetchall()
        out = []
        for row in rows:
            out.append({
                "server_sequence": row["server_sequence"], "client_sequence": row["client_sequence"], "command_ref": row["command_ref"],
                "command_type": row["command_type"], "parameters": json.loads(row["parameters_json"]), "result": json.loads(row["result_json"]), "command_hash": row["command_hash"],
            })
        return out

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        profiles = self.list_profiles()
        active = [p for p in profiles if p.get("active")]
        active_by_controller: dict[str, int] = {}
        for p in active:
            active_by_controller[p["controller_scope"]] = active_by_controller.get(p["controller_scope"], 0) + 1
        for scope, count in active_by_controller.items():
            if count > 1:
                failures.append("MULTIPLE_ACTIVE_PROFILES_FOR_CONTROLLER:" + scope)
        if len(profiles) > self.MAX_PROFILES_PER_WORLD:
            failures.append("PROFILE_LIMIT_EXCEEDED")
        for p in profiles:
            try:
                npc = self.country.npc(p["avatar_ref"])
            except KeyError:
                failures.append("PROFILE_AVATAR_MISSING:" + p["profile_ref"])
                continue
            if npc.get("arpg_profile_ref") != p["profile_ref"]:
                failures.append("PROFILE_AVATAR_BINDING:" + p["profile_ref"])
            if p["origin_mode"] == "CREATED" and p.get("canonical_ref") is not None:
                failures.append("CREATED_PROFILE_CANON_REF:" + p["profile_ref"])
            if p["origin_mode"] == "CANONICAL":
                try:
                    self._canonical_character(p.get("canonical_ref"))
                except Exception:
                    failures.append("CANONICAL_PROFILE_REF:" + p["profile_ref"])
            try:
                self.engine.movement(self.world_instance_id).state(p["avatar_ref"])
            except Exception:
                failures.append("PROFILE_MOTION_MISSING:" + p["profile_ref"])
            if p["avatar_ref"] not in self.engine.streaming(self.world_instance_id).owners:
                failures.append("PROFILE_STREAM_OWNER_MISSING:" + p["profile_ref"])
            try:
                inp = self._input(p["profile_ref"])
            except Exception:
                failures.append("PROFILE_INPUT_STATE:" + p["profile_ref"])
                continue
            if inp.get("action_state") not in ACTION_STATES:
                failures.append("ACTION_STATE_INVALID:" + p["profile_ref"])
            rows = self.runtime.conn.execute(
                "SELECT client_sequence,parameters_json,result_json,command_hash,profile_ref,command_type FROM arpg_command_stream WHERE world_instance_id=? AND profile_ref=? ORDER BY client_sequence",
                (self.world_instance_id, p["profile_ref"]),
            ).fetchall()
            seqs = [int(r["client_sequence"]) for r in rows]
            if seqs and seqs != list(range(1, max(seqs) + 1)):
                failures.append("COMMAND_SEQUENCE_GAP:" + p["profile_ref"])
            if int(inp.get("last_client_sequence", -1)) != (max(seqs) if seqs else 0):
                failures.append("INPUT_COMMAND_SEQUENCE_DIVERGENCE:" + p["profile_ref"])
            for r in rows:
                params = json.loads(r["parameters_json"])
                expected = sha256_text(canonical_json({"profile_ref": r["profile_ref"], "client_sequence": int(r["client_sequence"]), "command_type": r["command_type"], "parameters": params}))
                if expected != r["command_hash"]:
                    failures.append("COMMAND_HASH:" + p["profile_ref"] + ":" + str(r["client_sequence"]))
                try:
                    json.loads(r["result_json"])
                except Exception:
                    failures.append("COMMAND_RESULT_JSON:" + p["profile_ref"] + ":" + str(r["client_sequence"]))
        return {
            "status": "PASS" if not failures else "FAIL",
            "failures": failures,
            "profiles": len(profiles),
            "active_profiles": len(active),
            "active_controllers": len(active_by_controller),
            "commands": self.runtime.conn.execute("SELECT COUNT(*) c FROM arpg_command_stream WHERE world_instance_id=?", (self.world_instance_id,)).fetchone()["c"],
            "control_scheme": self.CONTROL_SCHEME,
            "network_model": self.NETWORK_MODEL,
            "class_model": self.CLASS_MODEL,
            "art_dependency": "NONE_PLACEHOLDER_READY",
            "authority": self.AUTHORITY,
        }
