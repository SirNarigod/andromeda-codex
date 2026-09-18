from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable


AUTHORITY = "STAGE16A_GAMEPLAY_DERIVED_PRE_GODOT_NOT_CANON"
PICKUP_RADIUS_M = 0.5
LIVING_MACRO_CHUNK_SIZE_M = 4096.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def _finite(v: Any) -> float:
    x = float(v)
    if not math.isfinite(x):
        raise ValueError("NON_FINITE_VALUE")
    return x


@dataclass(frozen=True)
class SurfaceProfile:
    surface_ref: str
    traversal_factor: float
    speed_factor: float
    road_class: bool = False
    vehicle_hint: str = "NEUTRAL"


# Gameplay-derived starting coefficients. Stage17 owns final balance.
SURFACES: dict[str, SurfaceProfile] = {
    "ROAD_GOOD": SurfaceProfile("ROAD_GOOD", 0.88, 1.05, True, "PREFERRED"),
    "ROAD_WORN": SurfaceProfile("ROAD_WORN", 0.96, 1.00, True, "PREFERRED"),
    "TRAIL": SurfaceProfile("TRAIL", 1.03, 0.98, True, "SUPPORTED"),
    "FIRM_GROUND": SurfaceProfile("FIRM_GROUND", 1.00, 1.00),
    "GRASS_FIELD": SurfaceProfile("GRASS_FIELD", 1.06, 0.98),
    "LOOSE_SOIL": SurfaceProfile("LOOSE_SOIL", 1.14, 0.94),
    "ROCKY_GROUND": SurfaceProfile("ROCKY_GROUND", 1.18, 0.92),
    "MUD": SurfaceProfile("MUD", 1.32, 0.84),
    "ROOT_DEEP_OVERLAY": SurfaceProfile("ROOT_DEEP_OVERLAY", 1.25, 0.88),
}

# Pre-Godot candidate thresholds. Must be validated against CharacterBody/NavMesh in Stage16B.
SLOPE_BANDS = (
    (6.0, "SUBTLE", 1.00, 1.00),
    (14.0, "LIGHT", 1.08, 0.98),
    (24.0, "MODERATE", 1.22, 0.92),
    (32.0, "STEEP_WALKABLE_CANDIDATE", 1.48, 0.82),
)
MAX_WALKABLE_SLOPE_DEG_CANDIDATE = 32.0
MAX_STEP_HEIGHT_M_CANDIDATE = 0.35
MICRO_RELIEF_COLLISION_FILTER_M_CANDIDATE = 0.12

# Large logical maps are partitioned into smaller stream cells. Large area != large simultaneous load.
MAP_SCALE_POLICIES: dict[str, dict[str, Any]] = {
    "INTERIOR": {"logical_extent_m": 96.0, "cell_size_m": 96.0, "preload_ring": 0},
    "POI": {"logical_extent_m": 192.0, "cell_size_m": 192.0, "preload_ring": 0},
    "SMALL_AREA": {"logical_extent_m": 512.0, "cell_size_m": 256.0, "preload_ring": 1},
    "SUBREGION": {"logical_extent_m": 2048.0, "cell_size_m": 256.0, "preload_ring": 1},
    "REGION": {"logical_extent_m": 8192.0, "cell_size_m": 512.0, "preload_ring": 1},
    "STATE_PHASE": {"logical_extent_m": 32768.0, "cell_size_m": 512.0, "preload_ring": 1},
}

STREAM_PHASES = {
    "ACTIVE": "FULL_GAMEPLAY_AND_VISUAL",
    "PRELOAD": "COLLISION_NAV_AND_LOW_VISUAL",
    "SYSTEMIC": "LIVING_ONLY_NO_GODOT_SCENE",
}


class TerrainTraversalStreamingCore:
    """Stage16A pre-Godot contract for traversal cost and runtime scene streaming.

    It does not author terrain canon. It converts runtime samples (slope/surface/load) into
    gameplay-derived movement/stamina hints and maps logical areas to stream cells. Existing
    Living 4096m chunks remain the macro simulation authority.
    """

    VERSION = "V0.2.0-PRE-GODOT"
    STAGE = "16A/23"
    AUTHORITY = AUTHORITY
    BODY_BALANCE_MECHANIC = False

    def slope_profile(self, slope_deg: float, *, ascending: bool = True) -> dict[str, Any]:
        slope = abs(_finite(slope_deg))
        if slope > MAX_WALKABLE_SLOPE_DEG_CANDIDATE:
            return {
                "status": "BLOCKED",
                "slope_deg": round(slope, 4),
                "reason": "SLOPE_EXCEEDS_PRE_GODOT_WALKABLE_CANDIDATE",
                "max_walkable_candidate_deg": MAX_WALKABLE_SLOPE_DEG_CANDIDATE,
                "requires_stage16b_validation": True,
            }
        label, stamina, speed = SLOPE_BANDS[-1][1:]
        for upper, name, stamina_factor, speed_factor in SLOPE_BANDS:
            if slope <= upper:
                label, stamina, speed = name, stamina_factor, speed_factor
                break
        if not ascending:
            # Descents matter, but are intentionally less punishing than climbs and do not add a balance mechanic.
            stamina = 1.0 + (stamina - 1.0) * 0.35
            speed = min(1.03, 1.0 + (1.0 - speed) * 0.15)
        return {
            "status": "PASS",
            "band": label,
            "slope_deg": round(slope, 4),
            "ascending": bool(ascending),
            "stamina_factor": round(stamina, 6),
            "speed_factor": round(speed, 6),
            "body_balance_mechanic": False,
            "requires_stage16b_validation": True,
        }

    def load_profile(self, *, current_weight: float, weight_capacity: float) -> dict[str, Any]:
        current = max(0.0, _finite(current_weight))
        capacity = _finite(weight_capacity)
        if capacity <= 0:
            raise ValueError("WEIGHT_CAPACITY_MUST_BE_POSITIVE")
        ratio = current / capacity
        # Inventory Core already rejects >capacity; this guard keeps traversal deterministic for malformed callers.
        effective = _clamp(ratio, 0.0, 1.0)
        if effective <= 0.35:
            band, stamina, speed = "LIGHT", 1.00, 1.00
        elif effective <= 0.65:
            band, stamina, speed = "MEDIUM", 1.10, 0.98
        elif effective <= 0.85:
            band, stamina, speed = "HEAVY", 1.24, 0.94
        else:
            band, stamina, speed = "VERY_HEAVY", 1.42, 0.88
        return {
            "status": "PASS",
            "band": band,
            "weight_ratio": round(ratio, 6),
            "effective_ratio": round(effective, 6),
            "stamina_factor": stamina,
            "speed_factor": speed,
            "over_capacity_input": ratio > 1.0 + 1e-9,
            "inventory_authority": "STAGE05_UNIVERSAL_ITEM_CORE",
        }

    def traversal_sample(
        self,
        *,
        distance_m: float,
        slope_deg: float,
        surface_ref: str,
        current_weight: float,
        weight_capacity: float,
        ascending: bool = True,
        base_stamina_per_meter: float = 0.08,
        base_speed_mps: float = 4.8,
    ) -> dict[str, Any]:
        distance = _finite(distance_m)
        if distance < 0:
            raise ValueError("DISTANCE_MUST_BE_NON_NEGATIVE")
        surface = SURFACES.get(str(surface_ref).upper().strip())
        if surface is None:
            raise ValueError("UNKNOWN_SURFACE:" + str(surface_ref))
        slope = self.slope_profile(slope_deg, ascending=ascending)
        if slope["status"] != "PASS":
            return {
                "status": "BLOCKED",
                "reason": slope["reason"],
                "distance_m": distance,
                "surface_ref": surface.surface_ref,
                "slope": slope,
                "body_balance_mechanic": False,
            }
        load = self.load_profile(current_weight=current_weight, weight_capacity=weight_capacity)
        stamina_per_m = (
            _finite(base_stamina_per_meter)
            * surface.traversal_factor
            * slope["stamina_factor"]
            * load["stamina_factor"]
        )
        speed = (
            _finite(base_speed_mps)
            * surface.speed_factor
            * slope["speed_factor"]
            * load["speed_factor"]
        )
        return {
            "status": "PASS",
            "distance_m": round(distance, 4),
            "surface_ref": surface.surface_ref,
            "surface_factor": surface.traversal_factor,
            "road_class": surface.road_class,
            "slope": slope,
            "load": load,
            "stamina_cost": round(distance * stamina_per_m, 6),
            "stamina_per_meter": round(stamina_per_m, 6),
            "effective_speed_mps": round(max(0.1, speed), 6),
            "body_balance_mechanic": False,
            "authority": AUTHORITY,
        }

    def route_compare(self, candidates: Iterable[dict[str, Any]]) -> dict[str, Any]:
        rows = []
        for i, c in enumerate(candidates):
            sample = self.traversal_sample(**c)
            rows.append({"candidate_index": i, **sample})
        passable = [r for r in rows if r.get("status") == "PASS"]
        if not passable:
            return {"status": "BLOCKED", "reason": "NO_PASSABLE_ROUTE", "candidates": rows}
        best = min(passable, key=lambda r: (r["stamina_cost"], r["distance_m"], r["candidate_index"]))
        return {
            "status": "PASS",
            "recommended_candidate_index": best["candidate_index"],
            "selection_basis": "LOWEST_STAMINA_COST_THEN_DISTANCE",
            "candidates": rows,
            "authority": AUTHORITY,
        }

    def area_policy(self, area_scale: str) -> dict[str, Any]:
        key = str(area_scale).upper().strip()
        if key not in MAP_SCALE_POLICIES:
            raise ValueError("UNKNOWN_AREA_SCALE:" + str(area_scale))
        p = dict(MAP_SCALE_POLICIES[key])
        p.update({
            "status": "PASS",
            "area_scale": key,
            "living_macro_chunk_size_m": LIVING_MACRO_CHUNK_SIZE_M,
            "large_area_partitioned": p["logical_extent_m"] > p["cell_size_m"],
            "authority": AUTHORITY,
        })
        return p

    @staticmethod
    def cell_id(area_ref: str, cell_x: int, cell_y: int) -> str:
        return f"CELL-S16A-{str(area_ref)}-{int(cell_x):+05d}-{int(cell_y):+05d}"

    def cell_for_local_position(self, *, area_ref: str, area_scale: str, x_m: float, y_m: float) -> dict[str, Any]:
        p = self.area_policy(area_scale)
        x = _finite(x_m)
        y = _finite(y_m)
        half = p["logical_extent_m"] / 2.0
        if not (-half <= x <= half and -half <= y <= half):
            return {
                "status": "OUTSIDE_AREA",
                "area_ref": str(area_ref),
                "area_scale": p["area_scale"],
                "logical_extent_m": p["logical_extent_m"],
                "position": {"x_m": x, "y_m": y},
            }
        size = p["cell_size_m"]
        cx = math.floor((x + half) / size)
        cy = math.floor((y + half) / size)
        max_index = max(0, int(math.ceil(p["logical_extent_m"] / size)) - 1)
        cx = min(cx, max_index)
        cy = min(cy, max_index)
        return {
            "status": "PASS",
            "area_ref": str(area_ref),
            "area_scale": p["area_scale"],
            "cell_id": self.cell_id(area_ref, cx, cy),
            "cell_x": cx,
            "cell_y": cy,
            "cell_size_m": size,
            "logical_extent_m": p["logical_extent_m"],
        }

    def stream_plan(self, *, area_ref: str, area_scale: str, active_cell_x: int, active_cell_y: int) -> dict[str, Any]:
        p = self.area_policy(area_scale)
        count_axis = max(1, int(math.ceil(p["logical_extent_m"] / p["cell_size_m"])))
        ax, ay = int(active_cell_x), int(active_cell_y)
        if not (0 <= ax < count_axis and 0 <= ay < count_axis):
            raise ValueError("ACTIVE_CELL_OUTSIDE_AREA")
        active = [self.cell_id(area_ref, ax, ay)]
        preload: list[str] = []
        ring = int(p["preload_ring"])
        if ring > 0:
            for x in range(max(0, ax-ring), min(count_axis-1, ax+ring)+1):
                for y in range(max(0, ay-ring), min(count_axis-1, ay+ring)+1):
                    cid = self.cell_id(area_ref, x, y)
                    if cid not in active:
                        preload.append(cid)
        loaded = active + sorted(preload)
        total = count_axis * count_axis
        return {
            "status": "PASS",
            "area_ref": str(area_ref),
            "area_scale": p["area_scale"],
            "logical_extent_m": p["logical_extent_m"],
            "cell_size_m": p["cell_size_m"],
            "cells_per_axis": count_axis,
            "total_logical_cells": total,
            "active_cells": active,
            "preload_cells": sorted(preload),
            "loaded_scene_cells": loaded,
            "loaded_scene_cell_count": len(loaded),
            "systemic_unloaded_cell_count": total - len(loaded),
            "phases": dict(STREAM_PHASES),
            "living_macro_chunk_size_m": LIVING_MACRO_CHUNK_SIZE_M,
            "living_lod_policy": "UNLOADED_GODOT_CELLS_CONTINUE_SYSTEMIC_SIMULATION",
            "authority": AUTHORITY,
        }

    def terrain_contract(self) -> dict[str, Any]:
        return {
            "status": "PASS",
            "version": self.VERSION,
            "authority": AUTHORITY,
            "body_balance_mechanic": False,
            "physics_policy": {
                "visual_surface": "DETAILED_RELIEF_ALLOWED",
                "collision_surface": "SIMPLIFIED_STABLE",
                "traversal_surface": "SLOPE_SURFACE_LOAD_COST",
                "max_walkable_slope_deg_candidate": MAX_WALKABLE_SLOPE_DEG_CANDIDATE,
                "max_step_height_m_candidate": MAX_STEP_HEIGHT_M_CANDIDATE,
                "micro_relief_collision_filter_m_candidate": MICRO_RELIEF_COLLISION_FILTER_M_CANDIDATE,
                "godot_validation_required": True,
            },
            "surfaces": {k: vars(v) for k, v in SURFACES.items()},
            "map_scales": json.loads(json.dumps(MAP_SCALE_POLICIES)),
            "living_macro_chunk_size_m": LIVING_MACRO_CHUNK_SIZE_M,
        }

    def deterministic_signature(self) -> str:
        payload = json.dumps(self.terrain_contract(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
