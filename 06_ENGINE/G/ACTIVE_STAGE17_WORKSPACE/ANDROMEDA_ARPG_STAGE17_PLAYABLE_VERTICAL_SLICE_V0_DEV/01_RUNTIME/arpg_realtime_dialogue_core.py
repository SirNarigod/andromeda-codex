from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable

AUTHORITY = "STAGE16A_AUTHORIAL_UI_DIALOGUE_PRE_GODOT_NOT_CANON_COPY"

NORMAL_TEXT_HEX = "#6B6B6B"
IMPORTANT_TEXT_HEX = "#D9A15F"  # soft/light orange candidate; Stage16B visual validation required
BUBBLE_BG_HEX = "#FFFFFF"
BUBBLE_CORNER_RADIUS_PX_CANDIDATE = 14
MAX_VISIBLE_BUBBLES_CANDIDATE = 3
FULL_VISIBILITY_DISTANCE_M_CANDIDATE = 8.0
FADE_END_DISTANCE_M_CANDIDATE = 14.0
CHOICE_RANGE_M_CANDIDATE = 2.0
READING_CHARS_PER_SECOND_CANDIDATE = 15.0
MIN_BUBBLE_SECONDS_CANDIDATE = 1.8
MAX_BUBBLE_SECONDS_CANDIDATE = 8.0
INTER_TURN_PAUSE_SECONDS_CANDIDATE = 0.35

# Presentation priority only. It does not alter Living/Narrative authority or dialogue content.
PRIORITY = {
    "DIRECT_PLAYER": 500,
    "IMPORTANT_NARRATIVE": 450,
    "QUEST_CONTEXT": 400,
    "NEARBY_CONVERSATION": 250,
    "AMBIENT": 150,
    "DISTANT": 50,
}


def _finite(v: Any) -> float:
    x = float(v)
    if not math.isfinite(x):
        raise ValueError("NON_FINITE_VALUE")
    return x


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class DialogueLine:
    line_ref: str
    speaker_ref: str
    text: str
    presentation_class: str = "AMBIENT"
    important: bool = False
    distance_m: float = 0.0
    conversation_ref: str | None = None
    turn_index: int = 0
    directed_to_player: bool = False


class RealtimeDialogueCore:
    """Pre-Godot dialogue presentation contract.

    It never authors canonical dialogue. It receives already-authorized runtime text/brief output and
    decides only presentation: bubble visibility, priority, duration, accessibility line and choices.
    Gameplay continues in real time; there is no NEXT button contract.
    """

    VERSION = "V0.3.0-PRE-GODOT"
    STAGE = "16A/23"
    AUTHORITY = AUTHORITY

    def style_contract(self) -> dict[str, Any]:
        return {
            "bubble_shape": "ROUNDED_RECTANGLE_WITH_SUBTLE_POINTER",
            "bubble_background_hex": BUBBLE_BG_HEX,
            "normal_text_hex": NORMAL_TEXT_HEX,
            "important_text_hex": IMPORTANT_TEXT_HEX,
            "font_style": "ROUNDED_READABLE_FONT_FAMILY_STAGE16B_ASSET_SELECTION_PENDING",
            "corner_radius_px_candidate": BUBBLE_CORNER_RADIUS_PX_CANDIDATE,
            "shadow": "VERY_SUBTLE",
            "important_orange": "SOFT_LIGHT_NOT_VIVID",
            "requires_stage16b_visual_validation": True,
        }

    def timing_for_text(self, text: str, *, important: bool = False) -> dict[str, Any]:
        clean = " ".join(str(text).split())
        if not clean:
            raise ValueError("DIALOGUE_TEXT_EMPTY")
        base = len(clean) / READING_CHARS_PER_SECOND_CANDIDATE
        # Important lines remain slightly longer, but narrative still advances automatically.
        if important:
            base *= 1.15
        seconds = _clamp(base, MIN_BUBBLE_SECONDS_CANDIDATE, MAX_BUBBLE_SECONDS_CANDIDATE)
        return {
            "seconds": round(seconds, 3),
            "auto_advance": True,
            "requires_next_button": False,
            "player_movement_locked": False,
            "inter_turn_pause_seconds": INTER_TURN_PAUSE_SECONDS_CANDIDATE,
            "authority": "GAMEPLAY_DERIVED_READING_CADENCE_REBALANCEABLE",
        }

    def distance_visibility(self, distance_m: float) -> dict[str, Any]:
        d = max(0.0, _finite(distance_m))
        if d <= FULL_VISIBILITY_DISTANCE_M_CANDIDATE:
            alpha = 1.0
            state = "FULL"
        elif d >= FADE_END_DISTANCE_M_CANDIDATE:
            alpha = 0.0
            state = "HIDDEN"
        else:
            span = FADE_END_DISTANCE_M_CANDIDATE - FULL_VISIBILITY_DISTANCE_M_CANDIDATE
            alpha = 1.0 - ((d - FULL_VISIBILITY_DISTANCE_M_CANDIDATE) / span)
            state = "FADING"
        return {
            "distance_m": round(d, 4),
            "state": state,
            "alpha": round(_clamp(alpha, 0.0, 1.0), 4),
            "full_distance_m_candidate": FULL_VISIBILITY_DISTANCE_M_CANDIDATE,
            "fade_end_distance_m_candidate": FADE_END_DISTANCE_M_CANDIDATE,
            "requires_stage16b_validation": True,
        }

    def hover_name(self, *, npc_ref: str, display_name: str, hovered: bool, role_label: str | None = None) -> dict[str, Any]:
        if not str(npc_ref):
            raise ValueError("NPC_REF_REQUIRED")
        visible = bool(hovered)
        return {
            "npc_ref": str(npc_ref),
            "visible": visible,
            "name": str(display_name) if visible else None,
            "role_label": (str(role_label) if role_label else None) if visible else None,
            "policy": "HOVER_ONLY",
        }

    def normalize_line(self, raw: DialogueLine | dict[str, Any]) -> dict[str, Any]:
        if isinstance(raw, DialogueLine):
            d = raw.__dict__.copy()
        else:
            d = dict(raw)
        line_ref = str(d.get("line_ref") or "").strip()
        speaker_ref = str(d.get("speaker_ref") or "").strip()
        text = " ".join(str(d.get("text") or "").split())
        if not line_ref or not speaker_ref or not text:
            raise ValueError("LINE_REF_SPEAKER_AND_TEXT_REQUIRED")
        pclass = str(d.get("presentation_class") or "AMBIENT").upper()
        directed = bool(d.get("directed_to_player", False))
        important = bool(d.get("important", False))
        if directed:
            pclass = "DIRECT_PLAYER"
        elif important and pclass in {"AMBIENT", "DISTANT", "NEARBY_CONVERSATION"}:
            pclass = "IMPORTANT_NARRATIVE"
        if pclass not in PRIORITY:
            raise ValueError("UNKNOWN_PRESENTATION_CLASS")
        dist = max(0.0, _finite(d.get("distance_m", 0.0)))
        turn = int(d.get("turn_index", 0))
        conv = d.get("conversation_ref")
        return {
            "line_ref": line_ref,
            "speaker_ref": speaker_ref,
            "text": text,
            "presentation_class": pclass,
            "important": important,
            "distance_m": dist,
            "conversation_ref": str(conv) if conv is not None else None,
            "turn_index": turn,
            "directed_to_player": directed,
            "priority": PRIORITY[pclass],
        }

    def select_visible_lines(self, lines: Iterable[DialogueLine | dict[str, Any]], *, max_visible: int = MAX_VISIBLE_BUBBLES_CANDIDATE) -> dict[str, Any]:
        limit = int(max_visible)
        if limit <= 0:
            raise ValueError("MAX_VISIBLE_MUST_BE_POSITIVE")
        normalized = []
        for raw in lines:
            line = self.normalize_line(raw)
            vis = self.distance_visibility(line["distance_m"])
            if vis["state"] == "HIDDEN":
                continue
            line["distance_alpha"] = vis["alpha"]
            normalized.append(line)

        # In one conversation, only the earliest pending turn is shown at once. This prevents stacked
        # bubbles from the same exchange and produces natural A->B alternation in real time.
        earliest_by_conversation: dict[str, dict[str, Any]] = {}
        standalone: list[dict[str, Any]] = []
        for line in normalized:
            conv = line.get("conversation_ref")
            if not conv:
                standalone.append(line)
                continue
            old = earliest_by_conversation.get(conv)
            key = (line["turn_index"], line["line_ref"])
            if old is None or key < (old["turn_index"], old["line_ref"]):
                earliest_by_conversation[conv] = line
        candidates = standalone + list(earliest_by_conversation.values())
        candidates.sort(key=lambda x: (-x["priority"], x["distance_m"], x["speaker_ref"], x["line_ref"]))
        visible = candidates[:limit]
        suppressed = len(candidates) - len(visible) + (len(normalized) - len(candidates))

        rendered = []
        for line in visible:
            timing = self.timing_for_text(line["text"], important=line["important"])
            rendered.append({
                **line,
                "bubble_visible": True,
                "bubble_background_hex": BUBBLE_BG_HEX,
                "text_hex": IMPORTANT_TEXT_HEX if line["important"] else NORMAL_TEXT_HEX,
                "duration_seconds": timing["seconds"],
                "accessibility_bottom_line": bool(line["important"]),
                "next_button": False,
                "movement_lock": False,
            })
        return {
            "status": "PASS",
            "visible": rendered,
            "visible_count": len(rendered),
            "suppressed_or_queued_count": max(0, suppressed),
            "max_visible_candidate": limit,
            "policy": "PRIORITY_PLUS_DISTANCE_WITH_CONVERSATION_TURN_GATING",
        }

    def important_accessibility_line(self, line: DialogueLine | dict[str, Any]) -> dict[str, Any]:
        d = self.normalize_line(line)
        if not d["important"]:
            return {"visible": False, "reason": "NOT_IMPORTANT"}
        return {
            "visible": True,
            "speaker_ref": d["speaker_ref"],
            "text": d["text"],
            "text_hex": IMPORTANT_TEXT_HEX,
            "position": "BOTTOM_SCREEN_SUBTLE",
            "duplicates_world_bubble": True,
            "blocks_gameplay": False,
        }

    def choice_overlay(self, *, npc_ref: str, choices: Iterable[dict[str, Any] | str], distance_m: float, active: bool = True) -> dict[str, Any]:
        d = max(0.0, _finite(distance_m))
        normalized = []
        for idx, c in enumerate(choices):
            if isinstance(c, str):
                ref, label = f"CHOICE-{idx+1}", c
            else:
                ref = str(c.get("choice_ref") or f"CHOICE-{idx+1}")
                label = str(c.get("label") or "").strip()
            if not label:
                raise ValueError("CHOICE_LABEL_REQUIRED")
            normalized.append({"choice_ref": ref, "label": label})
        if not active or not normalized:
            return {"visible": False, "choices": [], "reason": "NO_ACTIVE_DECISION"}
        if d > CHOICE_RANGE_M_CANDIDATE:
            return {"visible": False, "choices": [], "reason": "OUT_OF_CHOICE_RANGE", "distance_m": round(d, 4)}
        return {
            "visible": True,
            "npc_ref": str(npc_ref),
            "choices": normalized,
            "presentation": "SMALL_TEMPORARY_OPTIONS_NEAR_NPC",
            "large_modal": False,
            "next_button": False,
            "player_movement_locked": False,
            "range_m_candidate": CHOICE_RANGE_M_CANDIDATE,
            "requires_stage16b_validation": True,
        }

    def presentation_contract(self) -> dict[str, Any]:
        return {
            "mode": "REAL_TIME_NO_NEXT_BUTTON",
            "player_movement_locked": False,
            "npc_movement_locked": False,
            "world_pause_required": False,
            "multi_npc_conversation": True,
            "conversation_turns": "ALTERNATE_BY_TURN_INDEX_WITH_SHORT_AUTOMATIC_PAUSE",
            "max_visible_bubbles_candidate": MAX_VISIBLE_BUBBLES_CANDIDATE,
            "name_visibility": "HOVER_ONLY",
            "important_accessibility_line": "BOTTOM_SCREEN_PLUS_WORLD_BUBBLE",
            "choice_ui": "SMALL_TEMPORARY_OPTIONS_NEAR_NPC",
            "style": self.style_contract(),
            "canon_guard": "PRESENTATION_ONLY_NEVER_PROMOTES_RUNTIME_COPY_TO_CANON_DIALOGUE",
        }

    def deterministic_signature(self) -> str:
        payload = {
            "style": self.style_contract(),
            "contract": self.presentation_contract(),
            "priority": PRIORITY,
        }
        return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()
