from __future__ import annotations

import hashlib
import json
import math
from typing import Any

AUTHORITY = "STAGE16A_CAMERA_PRESENTATION_PRE_GODOT"

# Presentation candidates only. Stage16B must validate them visually/physically in Godot.
CAMERA_CANDIDATES = {
    "projection": "PERSPECTIVE_ISOMETRIC_OBLIQUE",
    "default_yaw_deg": 45.0,
    "default_pitch_deg": 55.0,
    "default_distance_m": 14.0,
    "min_distance_m": 11.0,
    "max_distance_m": 18.0,
    "height_follow_half_life_s": 0.18,
    "micro_vertical_deadband_m": 0.12,
    "occluder_fade_alpha": 0.20,
    "occluder_restore_seconds": 0.18,
    "zoom_step_m": 1.0,
}


class CameraPresentationCore:
    """Pure camera policy for Stage16A.

    This module never moves a Godot Camera3D directly. It produces deterministic
    presentation targets/guards that Stage16B can map onto SpringArm3D/Camera3D,
    occlusion fading and input projection.
    """

    VERSION = "V0.4.0-PRE-GODOT"
    STAGE = "16A/23"
    AUTHORITY = AUTHORITY

    def contract(self) -> dict[str, Any]:
        return {
            "camera_mode": "STABLE_ISOMETRIC_OBLIQUE",
            "world_pause": False,
            "free_orbit_default": False,
            "manual_rotation_authority": "UNRESOLVED_NOT_ENABLED_IN_FIRST_SLICE",
            "terrain_follow": "SMOOTH_ANCHOR_NOT_RAW_MICRO_RELIEF",
            "occlusion": "FADE_BLOCKING_WORLD_GEOMETRY_BEFORE_ABRUPT_CAMERA_JUMP",
            "zoom": "PLAYER_CONTROLLED_CLAMPED_NO_FORCED_COMBAT_ZOOM",
            "pointer_projection_stability": "CAMERA_IMPULSES_MUST_NOT_CHANGE_RESOLVED_CLICK_INTENT",
            "requires_stage16b_visual_validation": True,
            "candidates": dict(CAMERA_CANDIDATES),
            "authority": AUTHORITY,
        }

    def base_rig(self) -> dict[str, Any]:
        return {
            "projection": CAMERA_CANDIDATES["projection"],
            "yaw_deg": CAMERA_CANDIDATES["default_yaw_deg"],
            "pitch_deg": CAMERA_CANDIDATES["default_pitch_deg"],
            "distance_m": CAMERA_CANDIDATES["default_distance_m"],
            "free_orbit": False,
            "candidate_only": True,
        }

    def clamp_zoom_distance(self, requested_distance_m: float) -> dict[str, Any]:
        req = float(requested_distance_m)
        lo = float(CAMERA_CANDIDATES["min_distance_m"])
        hi = float(CAMERA_CANDIDATES["max_distance_m"])
        applied = min(hi, max(lo, req))
        return {
            "status": "PASS",
            "requested_distance_m": req,
            "distance_m": round(applied, 4),
            "clamped": not math.isclose(req, applied),
            "forced_by_combat": False,
        }

    def zoom_step(self, current_distance_m: float, direction: str) -> dict[str, Any]:
        d = str(direction).upper().strip()
        if d not in {"IN", "OUT"}:
            return {"status": "REJECTED", "reason": "UNSUPPORTED_ZOOM_DIRECTION"}
        step = float(CAMERA_CANDIDATES["zoom_step_m"])
        requested = float(current_distance_m) + (-step if d == "IN" else step)
        out = self.clamp_zoom_distance(requested)
        out["direction"] = d
        return out

    def height_follow(
        self,
        *,
        previous_smoothed_altitude_m: float,
        anchor_altitude_m: float,
        delta_seconds: float,
    ) -> dict[str, Any]:
        prev = float(previous_smoothed_altitude_m)
        anchor = float(anchor_altitude_m)
        dt = max(0.0, float(delta_seconds))
        deadband = float(CAMERA_CANDIDATES["micro_vertical_deadband_m"])
        delta = anchor - prev
        if abs(delta) <= deadband:
            return {
                "status": "PASS",
                "smoothed_altitude_m": round(prev, 6),
                "micro_relief_filtered": True,
                "teleport": False,
            }
        half_life = max(0.001, float(CAMERA_CANDIDATES["height_follow_half_life_s"]))
        if dt <= 0:
            alpha = 0.0
        else:
            alpha = 1.0 - math.pow(0.5, dt / half_life)
        new_value = prev + delta * alpha
        return {
            "status": "PASS",
            "smoothed_altitude_m": round(new_value, 6),
            "micro_relief_filtered": False,
            "teleport": False,
            "alpha": round(alpha, 6),
        }

    def occlusion_policy(
        self,
        *,
        obstacle_ref: str,
        blocks_player_view: bool,
        obstacle_kind: str = "WORLD_GEOMETRY",
        transparent_safe: bool = True,
    ) -> dict[str, Any]:
        if not blocks_player_view:
            return {
                "status": "PASS",
                "obstacle_ref": str(obstacle_ref),
                "action": "RESTORE_OPACITY",
                "camera_reposition": False,
            }
        if not transparent_safe:
            return {
                "status": "PASS",
                "obstacle_ref": str(obstacle_ref),
                "action": "CAMERA_COLLISION_SHORTEN_DISTANCE",
                "camera_reposition": True,
                "abrupt_jump_allowed": False,
            }
        return {
            "status": "PASS",
            "obstacle_ref": str(obstacle_ref),
            "obstacle_kind": str(obstacle_kind),
            "action": "FADE_OCCLUDER",
            "target_alpha": CAMERA_CANDIDATES["occluder_fade_alpha"],
            "restore_seconds": CAMERA_CANDIDATES["occluder_restore_seconds"],
            "camera_reposition": False,
            "abrupt_jump_allowed": False,
        }

    def context_policy(self, context: str) -> dict[str, Any]:
        c = str(context).upper().strip()
        allowed = {"OVERWORLD", "COMBAT", "INTERIOR", "DUNGEON", "VEHICLE", "BOSS"}
        if c not in allowed:
            return {"status": "REJECTED", "reason": "UNSUPPORTED_CAMERA_CONTEXT", "context": c}
        return {
            "status": "PASS",
            "context": c,
            "forced_zoom": False,
            "forced_rotation": False,
            "keep_player_anchor_visible": True,
            "occlusion_fade_enabled": True,
            "terrain_height_smoothing": True,
        }

    def pointer_stability_guard(self, *, feedback_impulse_active: bool, pointer_action_pending: bool) -> dict[str, Any]:
        return {
            "status": "PASS",
            "feedback_impulse_active": bool(feedback_impulse_active),
            "pointer_action_pending": bool(pointer_action_pending),
            "re_resolve_world_target_due_to_visual_impulse": False,
            "rule": "VISUAL_CAMERA_IMPULSE_NEVER_REWRITES_ALREADY_RESOLVED_GAMEPLAY_INTENT",
        }

    def deterministic_signature(self) -> str:
        raw = json.dumps(self.contract(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
