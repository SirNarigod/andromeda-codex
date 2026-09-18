from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


PICKUP_RADIUS_M = 0.5

TARGET_KINDS = {
    "GROUND_LOOT",
    "ACTOR",
    "NPC",
    "ANIMAL",
    "GATHER_NODE",
    "SCENE_OBJECT",
    "VEHICLE",
}

# Semantic order is only a deterministic tie-breaker after pointer proximity and depth.
# It must never override a clearly closer/frontmost pointer hit.
SEMANTIC_TIE_PRIORITY = {
    "GROUND_LOOT": 0,
    "ACTOR": 1,
    "NPC": 1,
    "ANIMAL": 1,
    "GATHER_NODE": 2,
    "SCENE_OBJECT": 3,
    "VEHICLE": 4,
}


@dataclass(frozen=True)
class HitCandidate:
    ref: str
    kind: str
    screen_distance_px: float = 0.0
    depth_m: float = 0.0
    physical_distance_m: float | None = None
    direct_hit: bool = True
    reachable: bool = True
    hostile: bool = False
    selectable: bool = True
    interactable: bool = True

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "HitCandidate":
        return cls(
            ref=str(value.get("ref", "")),
            kind=str(value.get("kind", "")).upper(),
            screen_distance_px=float(value.get("screen_distance_px", 0.0)),
            depth_m=float(value.get("depth_m", 0.0)),
            physical_distance_m=(None if value.get("physical_distance_m") is None else float(value["physical_distance_m"])),
            direct_hit=bool(value.get("direct_hit", True)),
            reachable=bool(value.get("reachable", True)),
            hostile=bool(value.get("hostile", False)),
            selectable=bool(value.get("selectable", True)),
            interactable=bool(value.get("interactable", True)),
        )


class InteractionIntentResolver:
    """Pure pre-Godot input resolver for Stage 16A.

    It resolves *intent* only. Pathfinding, hostility authority, inventory capacity,
    combat cooldown and actual interaction execution remain owned by their existing
    runtime systems.
    """

    pickup_radius_m = PICKUP_RADIUS_M

    def _normalize(self, candidates: Iterable[HitCandidate | dict[str, Any]]) -> list[HitCandidate]:
        out: list[HitCandidate] = []
        for candidate in candidates:
            hit = candidate if isinstance(candidate, HitCandidate) else HitCandidate.from_mapping(candidate)
            if not hit.ref or hit.kind not in TARGET_KINDS:
                continue
            out.append(hit)
        return out

    def choose_pointer_target(self, candidates: Iterable[HitCandidate | dict[str, Any]]) -> HitCandidate | None:
        hits = [h for h in self._normalize(candidates) if h.direct_hit and h.selectable]
        if not hits:
            return None
        hits.sort(
            key=lambda h: (
                max(0.0, h.screen_distance_px),
                max(0.0, h.depth_m),
                SEMANTIC_TIE_PRIORITY.get(h.kind, 99),
                h.ref,
            )
        )
        return hits[0]

    def _pickup_intent(self, hit: HitCandidate, button: str) -> dict[str, Any]:
        if not hit.reachable:
            return {
                "status": "REJECTED",
                "reason": "GROUND_LOOT_UNREACHABLE",
                "target_ref": hit.ref,
                "cursor": "BLOCKED",
                "button": button,
            }
        distance = hit.physical_distance_m
        if distance is not None and distance <= self.pickup_radius_m:
            return {
                "status": "PASS",
                "intent": "PICKUP",
                "target_ref": hit.ref,
                "max_pickup_distance_m": self.pickup_radius_m,
                "cursor": "PICKUP",
                "interrupts_action": False,
                "button": button,
            }
        return {
            "status": "PASS",
            "intent": "APPROACH_PICKUP",
            "target_ref": hit.ref,
            "arrival_distance_m": self.pickup_radius_m,
            "requires_path": True,
            "cursor": "PICKUP",
            "button": button,
        }

    def resolve_click(
        self,
        button: str,
        candidates: Iterable[HitCandidate | dict[str, Any]],
        *,
        ground_point: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        button = str(button).upper().strip()
        if button not in {"LEFT", "RIGHT"}:
            return {"status": "REJECTED", "reason": "UNSUPPORTED_POINTER_BUTTON"}

        hit = self.choose_pointer_target(candidates)
        if hit is None:
            if ground_point is None:
                return {"status": "REJECTED", "reason": "NO_TARGET_OR_GROUND_POINT", "button": button}
            return {
                "status": "PASS",
                "intent": "MOVE_TO_POINT",
                "ground_point": {"iso_x_m": float(ground_point["iso_x_m"]), "iso_y_m": float(ground_point["iso_y_m"])},
                "cursor": "MOVE",
                "button": button,
            }

        if hit.kind == "GROUND_LOOT":
            return self._pickup_intent(hit, button)

        if button == "LEFT":
            return {
                "status": "PASS",
                "intent": "SELECT_TARGET",
                "target_ref": hit.ref,
                "target_kind": hit.kind,
                "cursor": "SELECT",
                "movement_change": "NONE",
                "button": button,
            }

        # RIGHT is contextual and may create an approach action.
        if hit.kind in {"ACTOR", "NPC", "ANIMAL"}:
            if hit.hostile:
                return {
                    "status": "PASS",
                    "intent": "CHASE_ATTACK",
                    "target_ref": hit.ref,
                    "target_kind": hit.kind,
                    "requires_path": True,
                    "cursor": "ATTACK",
                    "button": button,
                }
            return {
                "status": "PASS",
                "intent": "APPROACH_INTERACT",
                "target_ref": hit.ref,
                "target_kind": hit.kind,
                "requires_path": True,
                "cursor": "TALK" if hit.kind in {"ACTOR", "NPC"} else "INTERACT",
                "button": button,
            }

        if hit.kind == "GATHER_NODE":
            return {
                "status": "PASS",
                "intent": "APPROACH_HARVEST",
                "target_ref": hit.ref,
                "requires_path": True,
                "cursor": "HARVEST",
                "button": button,
            }

        if hit.kind in {"SCENE_OBJECT", "VEHICLE"}:
            return {
                "status": "PASS",
                "intent": "APPROACH_INTERACT",
                "target_ref": hit.ref,
                "target_kind": hit.kind,
                "requires_path": True,
                "cursor": "INTERACT",
                "button": button,
            }

        return {"status": "REJECTED", "reason": "UNRESOLVED_CONTEXT", "target_ref": hit.ref, "button": button}

    def resolve_auto_pickup(
        self,
        candidates: Iterable[HitCandidate | dict[str, Any]],
        *,
        enabled: bool,
    ) -> dict[str, Any]:
        if not enabled:
            return {"status": "PASS", "enabled": False, "pickup_refs": [], "interrupts_action": False}
        eligible: list[HitCandidate] = []
        for hit in self._normalize(candidates):
            if hit.kind != "GROUND_LOOT" or not hit.reachable or hit.physical_distance_m is None:
                continue
            if hit.physical_distance_m <= self.pickup_radius_m:
                eligible.append(hit)
        eligible.sort(key=lambda h: (float(h.physical_distance_m or 0.0), h.ref))
        return {
            "status": "PASS",
            "enabled": True,
            "pickup_refs": [h.ref for h in eligible],
            "max_pickup_distance_m": self.pickup_radius_m,
            "interrupts_action": False,
        }

    def hover_preview(self, candidates: Iterable[HitCandidate | dict[str, Any]]) -> dict[str, Any]:
        hit = self.choose_pointer_target(candidates)
        if hit is None:
            return {"status": "PASS", "target_ref": None, "cursor": "MOVE"}
        if hit.kind == "GROUND_LOOT":
            cursor = "BLOCKED" if not hit.reachable else "PICKUP"
        elif hit.kind in {"ACTOR", "NPC", "ANIMAL"}:
            cursor = "ATTACK" if hit.hostile else ("TALK" if hit.kind in {"ACTOR", "NPC"} else "INTERACT")
        elif hit.kind == "GATHER_NODE":
            cursor = "HARVEST"
        else:
            cursor = "INTERACT"
        return {"status": "PASS", "target_ref": hit.ref, "target_kind": hit.kind, "cursor": cursor}
