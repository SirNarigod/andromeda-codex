from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

AUTHORITY = "STAGE16A_GAMEFEEL_CONTEXTUAL_FEEDBACK_PRE_GODOT"

# Presentation-only tuning candidates; never authoritative combat values.
FEEDBACK_CANDIDATES = {
    "move_click_marker_seconds": 0.35,
    "interaction_marker_seconds": 0.55,
    "pickup_pulse_seconds": 0.45,
    "blocked_feedback_seconds": 0.70,
    "normal_hit_local_freeze_ms": 28,
    "strong_hit_local_freeze_ms": 42,
    "critical_hit_local_freeze_ms": 58,
    "max_camera_impulse": 0.18,
    "max_visible_feedback_events": 3,
    "duplicate_audio_debounce_ms": 70,
}

PRIORITY = {
    "PLAYER_CRITICAL_DAMAGE": 100,
    "PLAYER_DAMAGE": 95,
    "BOSS_DANGER": 90,
    "CRITICAL_HIT_CONFIRM": 85,
    "HIT_CONFIRM": 80,
    "BLOCKED_INTERACTION": 72,
    "QUEST_UPDATE": 68,
    "INTERACTION_CONFIRM": 60,
    "PICKUP": 50,
    "MOVE_CLICK": 20,
    "AMBIENT": 10,
}


class GameFeelFeedbackCore:
    """Maps gameplay outcomes to minimal, non-authoritative presentation feedback."""

    VERSION = "V0.4.0-PRE-GODOT"
    STAGE = "16A/23"
    AUTHORITY = AUTHORITY

    def contract(self) -> dict[str, Any]:
        return {
            "presentation_only": True,
            "may_change_gameplay_result": False,
            "global_hitstop": False,
            "local_animation_freeze_only": True,
            "camera_impulse": "SUBTLE_OPTIONAL_REDUCED_MOTION_AWARE",
            "damage_numbers": "NOT_REQUIRED_BY_CORE_OPTIONAL_LATER_PRESENTATION_SETTING",
            "audio": "SEMANTIC_CUE_TOKENS_ONLY_NO_FINAL_ASSET",
            "click_feedback": "SMALL_TEMPORARY_WORLD_MARKER",
            "blocked_interaction": "VISIBLE_AND_AUDIBLE_NON_BLOCKING_REASON_FEEDBACK",
            "priority": dict(PRIORITY),
            "candidates": dict(FEEDBACK_CANDIDATES),
            "requires_stage16b_feel_validation": True,
            "authority": AUTHORITY,
        }

    def click_feedback(self, intent: str, *, accepted: bool = True, reason: str | None = None) -> dict[str, Any]:
        i = str(intent).upper().strip()
        if not accepted:
            return {
                "status": "PASS",
                "feedback_class": "BLOCKED_INTERACTION",
                "world_marker": "SMALL_BLOCKED_PULSE",
                "duration_seconds": FEEDBACK_CANDIDATES["blocked_feedback_seconds"],
                "audio_cue": "UI_INTERACTION_BLOCKED",
                "reason": str(reason or "ACTION_REJECTED"),
                "blocks_gameplay": False,
            }
        if i == "MOVE_TO_POINT":
            return {
                "status": "PASS",
                "feedback_class": "MOVE_CLICK",
                "world_marker": "SMALL_GROUND_RING",
                "duration_seconds": FEEDBACK_CANDIDATES["move_click_marker_seconds"],
                "audio_cue": None,
                "blocks_gameplay": False,
            }
        if i in {"PICKUP", "APPROACH_PICKUP"}:
            return {
                "status": "PASS",
                "feedback_class": "PICKUP" if i == "PICKUP" else "INTERACTION_CONFIRM",
                "world_marker": "SMALL_PICKUP_PULSE",
                "duration_seconds": FEEDBACK_CANDIDATES["interaction_marker_seconds"],
                "audio_cue": "ITEM_PICKUP" if i == "PICKUP" else None,
                "blocks_gameplay": False,
            }
        if i in {"CHASE_ATTACK", "APPROACH_INTERACT", "APPROACH_HARVEST", "SELECT_TARGET"}:
            return {
                "status": "PASS",
                "feedback_class": "INTERACTION_CONFIRM",
                "world_marker": "SMALL_CONTEXT_PULSE",
                "duration_seconds": FEEDBACK_CANDIDATES["interaction_marker_seconds"],
                "audio_cue": None,
                "blocks_gameplay": False,
            }
        return {"status": "REJECTED", "reason": "UNSUPPORTED_FEEDBACK_INTENT", "intent": i}

    def hit_feedback(
        self,
        *,
        dealt_damage: bool,
        critical: bool = False,
        strong_hit: bool = False,
        target_is_boss: bool = False,
        reduced_motion: bool = False,
    ) -> dict[str, Any]:
        if not dealt_damage:
            return {
                "status": "PASS",
                "feedback_class": "NO_DAMAGE_CONFIRM",
                "local_freeze_ms": 0,
                "camera_impulse": 0.0,
                "audio_cue": "ATTACK_NO_DAMAGE",
                "global_world_pause": False,
            }
        if critical:
            freeze = int(FEEDBACK_CANDIDATES["critical_hit_local_freeze_ms"])
            cls = "CRITICAL_HIT_CONFIRM"
        elif strong_hit or target_is_boss:
            freeze = int(FEEDBACK_CANDIDATES["strong_hit_local_freeze_ms"])
            cls = "HIT_CONFIRM"
        else:
            freeze = int(FEEDBACK_CANDIDATES["normal_hit_local_freeze_ms"])
            cls = "HIT_CONFIRM"
        impulse = 0.0 if reduced_motion else min(float(FEEDBACK_CANDIDATES["max_camera_impulse"]), 0.08 + (0.05 if strong_hit else 0.0) + (0.05 if critical else 0.0))
        return {
            "status": "PASS",
            "feedback_class": cls,
            "local_freeze_ms": 0 if reduced_motion else freeze,
            "local_animation_only": True,
            "global_world_pause": False,
            "camera_impulse": round(impulse, 4),
            "audio_cue": "COMBAT_CRITICAL_HIT" if critical else "COMBAT_HIT",
            "target_bar_pulse": True,
            "mandatory_damage_number": False,
        }

    def incoming_damage_feedback(self, *, critical: bool = False, shield_absorbed: bool = False, reduced_motion: bool = False) -> dict[str, Any]:
        return {
            "status": "PASS",
            "feedback_class": "PLAYER_CRITICAL_DAMAGE" if critical else "PLAYER_DAMAGE",
            "hud_vitals_reveal": True,
            "shield_pulse": bool(shield_absorbed),
            "camera_impulse": 0.0 if reduced_motion else (0.14 if critical else 0.08),
            "audio_cue": "PLAYER_SHIELD_HIT" if shield_absorbed else "PLAYER_HURT",
            "screen_flash": "SUBTLE_EDGE_ONLY",
            "global_world_pause": False,
        }

    def pickup_feedback(self, *, item_type: str, quantity: int, rarity: str = "COMMON") -> dict[str, Any]:
        q = int(quantity)
        if q <= 0:
            raise ValueError("PICKUP_QUANTITY_MUST_BE_POSITIVE")
        return {
            "status": "PASS",
            "feedback_class": "PICKUP",
            "item_type": str(item_type),
            "quantity": q,
            "rarity": str(rarity),
            "icon_policy": "BY_ITEM_TYPE_NOT_ITEM_ID",
            "world_pulse_seconds": FEEDBACK_CANDIDATES["pickup_pulse_seconds"],
            "hud_feedback": "SMALL_TEMPORARY",
            "audio_cue": "ITEM_PICKUP",
            "blocks_gameplay": False,
        }

    def select_feedback(self, events: Iterable[dict[str, Any]], *, combat_active: bool, max_visible: int | None = None) -> dict[str, Any]:
        limit = int(max_visible or FEEDBACK_CANDIDATES["max_visible_feedback_events"])
        if limit <= 0:
            return {"status": "PASS", "visible": [], "suppressed": list(events)}
        normalized: list[dict[str, Any]] = []
        for idx, event in enumerate(events):
            e = dict(event)
            cls = str(e.get("feedback_class", "AMBIENT")).upper()
            e["feedback_class"] = cls
            e["priority"] = int(PRIORITY.get(cls, 0))
            e["_stable_index"] = idx
            # During combat, low-value ambient/move markers become less competitive, never more authoritative.
            e["effective_priority"] = e["priority"] - (10 if combat_active and cls in {"AMBIENT", "MOVE_CLICK"} else 0)
            normalized.append(e)
        normalized.sort(key=lambda e: (-e["effective_priority"], e["_stable_index"]))
        visible = normalized[:limit]
        suppressed = normalized[limit:]
        for e in visible + suppressed:
            e.pop("_stable_index", None)
        return {"status": "PASS", "visible": visible, "suppressed": suppressed, "combat_active": bool(combat_active)}

    def audio_policy(self, *, cue: str, duplicate_within_ms: int = 999) -> dict[str, Any]:
        c = str(cue).upper().strip()
        if not c:
            return {"status": "REJECTED", "reason": "EMPTY_AUDIO_CUE"}
        debounce = int(FEEDBACK_CANDIDATES["duplicate_audio_debounce_ms"])
        suppressed = int(duplicate_within_ms) < debounce
        return {
            "status": "PASS",
            "cue": c,
            "semantic_only": True,
            "play": not suppressed,
            "suppressed_duplicate": suppressed,
            "final_asset_required": False,
        }

    def deterministic_signature(self) -> str:
        raw = json.dumps(self.contract(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
