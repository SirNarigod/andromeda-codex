from __future__ import annotations

import hashlib
import json
from typing import Any

AUTHORITY = "STAGE16A_AUTHORIAL_MINIMAL_HUD_PRE_GODOT"

# Candidate durations/alphas are gameplay presentation tuning, not canon.
HUD_CANDIDATES = {
    "idle_vitals_alpha": 0.22,
    "active_vitals_alpha": 0.92,
    "interaction_hint_seconds": 1.8,
    "loot_feedback_seconds": 1.8,
    "quest_update_seconds": 4.0,
    "auto_pickup_status_seconds": 2.0,
}


class MinimalHUDCore:
    """Contextual HUD composition. The world remains the dominant visual layer."""

    VERSION = "V0.7.0-PRE-GODOT"
    STAGE = "16A/23"
    AUTHORITY = AUTHORITY

    def channels(self) -> tuple[str, ...]:
        return (
            "PLAYER_VITALS",
            "STAMINA",
            "PROTECTION",
            "TARGET_INFO",
            "BOSS_STATUS",
            "INTERACTION_HINT",
            "LOOT_FEEDBACK",
            "QUEST_UPDATE",
            "IMPORTANT_DIALOGUE_ACCESSIBILITY",
            "AUTO_PICKUP_STATUS",
            "CHOICE_OVERLAY",
            "NPC_HOVER_NAME",
        )

    def compose(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        c = dict(context or {})
        combat = bool(c.get("combat_active", False))
        stamina_active = bool(c.get("stamina_active", False))
        health_recent = bool(c.get("health_changed_recently", False))
        protection_recent = bool(c.get("protection_changed_recently", False))
        target = bool(c.get("target_relevant", False))
        boss = bool(c.get("boss_active", False))
        interaction = bool(c.get("interaction_hint", False))
        loot = bool(c.get("loot_feedback", False))
        quest = bool(c.get("quest_update", False))
        important_dialogue = bool(c.get("important_dialogue", False))
        auto_pickup_changed = bool(c.get("auto_pickup_changed", False))
        choice = bool(c.get("choice_overlay", False))
        npc_hover = bool(c.get("npc_hover", False))

        visible: dict[str, dict[str, Any]] = {}

        # Vitals remain extremely subtle when idle, but do not disappear during danger or recent damage.
        if combat or health_recent:
            visible["PLAYER_VITALS"] = {"alpha": HUD_CANDIDATES["active_vitals_alpha"], "mode": "ACTIVE"}
        else:
            visible["PLAYER_VITALS"] = {"alpha": HUD_CANDIDATES["idle_vitals_alpha"], "mode": "IDLE_SUBTLE"}

        stamina_fraction = float(c.get("stamina_fraction", 1.0))
        stamina_visible = stamina_active or stamina_fraction < 0.999999
        if stamina_visible:
            visible["STAMINA"] = {
                "alpha": HUD_CANDIDATES["active_vitals_alpha"],
                "mode": "WORLD_ADJACENT_PLAYER_RADIAL",
                "shape": "CIRCLE",
                "fill_direction": "RADIAL_DEPLETION_AND_RECOVERY",
                "color": "SOFT_YELLOW",
                "fraction": max(0.0, min(1.0, stamina_fraction)),
                "hide_when_full_and_inactive": True,
                "screen_alignment": "PLAYER_ADJACENT_SCREEN_SPACE",
            }
        if combat or protection_recent:
            visible["PROTECTION"] = {"alpha": HUD_CANDIDATES["active_vitals_alpha"], "mode": "CONTEXTUAL"}
        if target:
            visible["TARGET_INFO"] = {"alpha": 1.0, "mode": "TARGET_RELEVANT"}
        if boss:
            visible["BOSS_STATUS"] = {"alpha": 1.0, "mode": "BOSS_ONLY"}
        if interaction:
            visible["INTERACTION_HINT"] = {"duration_seconds": HUD_CANDIDATES["interaction_hint_seconds"], "mode": "TEMPORARY"}
        if loot:
            visible["LOOT_FEEDBACK"] = {"duration_seconds": HUD_CANDIDATES["loot_feedback_seconds"], "mode": "TEMPORARY"}
        if quest:
            visible["QUEST_UPDATE"] = {"duration_seconds": HUD_CANDIDATES["quest_update_seconds"], "mode": "TEMPORARY"}
        if important_dialogue:
            visible["IMPORTANT_DIALOGUE_ACCESSIBILITY"] = {"mode": "SUBTLE_BOTTOM_LINE", "blocks_gameplay": False}
        if auto_pickup_changed:
            visible["AUTO_PICKUP_STATUS"] = {"duration_seconds": HUD_CANDIDATES["auto_pickup_status_seconds"], "mode": "TEMPORARY"}
        if choice:
            visible["CHOICE_OVERLAY"] = {"mode": "NEAR_NPC", "large_modal": False, "blocks_world": False}
        if npc_hover:
            visible["NPC_HOVER_NAME"] = {"mode": "HOVER_ONLY"}

        return {
            "status": "PASS",
            "philosophy": "MINIMAL_CONTEXTUAL_WORLD_FIRST",
            "visible": visible,
            "visible_channels": list(visible.keys()),
            "permanent_large_panels": False,
            "dialogue_next_button": False,
            "world_is_primary_visual_layer": True,
            "requires_stage16b_visual_validation": True,
        }

    def enemy_bar_policy(self, *, hostile: bool, recently_engaged: bool, boss: bool = False, alpha_rank: bool = False) -> dict[str, Any]:
        # Stage03/07 own combat semantics; this only decides presentation presence.
        if boss:
            return {"visible": True, "placement": "BOSS_HUD_CONTEXTUAL", "shield_channel": True, "style": "MINIMAL"}
        visible = bool(hostile and recently_engaged)
        return {
            "visible": visible,
            "placement": "FIXED_STRAIGHT_ABOVE_HEAD",
            "hp_channel": visible,
            "shield_channel": bool(visible and alpha_rank),
            "billboard_rotation": "SCREEN_ALIGNED_STABLE_NOT_CHARACTER_ROTATION",
            "style": "MINIMAL",
        }

    def pickup_feedback(self, *, item_type: str, quantity: int, rarity: str = "COMMON") -> dict[str, Any]:
        q = int(quantity)
        if q <= 0:
            raise ValueError("PICKUP_QUANTITY_MUST_BE_POSITIVE")
        return {
            "visible": True,
            "item_type": str(item_type),
            "quantity": q,
            "rarity": str(rarity),
            "icon_policy": "BY_ITEM_TYPE_NOT_ITEM_ID",
            "duration_seconds": HUD_CANDIDATES["loot_feedback_seconds"],
            "presentation": "SMALL_NON_BLOCKING_FEEDBACK",
        }

    def auto_pickup_status(self, enabled: bool) -> dict[str, Any]:
        return {
            "visible": True,
            "enabled": bool(enabled),
            "label": "AUTO_PICKUP_ON" if enabled else "AUTO_PICKUP_OFF",
            "duration_seconds": HUD_CANDIDATES["auto_pickup_status_seconds"],
            "persistent_large_indicator": False,
        }

    def weapon_quickslot_presentation(self, *, active_slot: int | None = None) -> dict[str, Any]:
        if active_slot not in (None, 1, 2):
            raise ValueError("ACTIVE_WEAPON_SLOT_MUST_BE_1_OR_2_OR_NONE")
        return {
            "max_active_weapon_slots": 2,
            "slots": [1, 2],
            "active_slot": active_slot,
            "presentation": "SMALL_WHITE_ROUNDED_QUICK_SLOTS",
            "active_highlight": "SUBTLE_SOFT_YELLOW_ACCENT",
            "idle_behavior": "FADE_TO_DISCREET_AFTER_SWAP",
            "wheel_swap": True,
            "numeric_keys": ["1", "2"],
        }

    def ui_language_contract(self) -> dict[str, Any]:
        return {
            "reference_philosophy": "NINTENDO_SWITCH_LIKE_CLEAN_CONSOLE_UI_WITHOUT_COPYING_ASSETS",
            "panel_background": "#FFFFFF",
            "panel_shape": "ROUNDED",
            "corner_radius_px_candidate": 14,
            "primary_text": "#6B6B6B",
            "secondary_text": "#8A8A8A",
            "important_text": "#D9A15F",
            "font_direction": "ROUNDED_SANS_LEGIBLE",
            "shadow": "SUBTLE_ONLY",
            "spacing": "AIRY_CONSOLE_UI",
            "inventory": "WHITE_ROUNDED_PANEL_SAME_LANGUAGE_AS_DIALOGUE_BUBBLE",
            "vendors": "WHITE_ROUNDED_PANEL_SAME_LANGUAGE_AS_DIALOGUE_BUBBLE",
            "crafting": "WHITE_ROUNDED_PANEL_SAME_LANGUAGE_AS_DIALOGUE_BUBBLE",
            "tooltips": "WHITE_ROUNDED_COMPACT_CARD",
            "final_font_asset": "DEFERRED_STAGE16B_VISUAL_VALIDATION",
        }

    def accessibility_contract(self) -> dict[str, Any]:
        return {
            "important_dialogue_bottom_line_default": True,
            "world_bubble_remains_visible": True,
            "font_scale_configurable": True,
            "dialogue_duration_scale_configurable": True,
            "contrast_validation_required_stage16b": True,
            "color_not_only_signal": True,
            "important_dialogue_signal": ["SOFT_LIGHT_ORANGE_TEXT", "BOTTOM_ACCESSIBILITY_LINE"],
        }

    def contract(self) -> dict[str, Any]:
        return {
            "philosophy": "MINIMAL_CONTEXTUAL_WORLD_FIRST",
            "hud_idle": "SUBTLE",
            "hud_combat": "REVEAL_RELEVANT_CHANNELS",
            "hud_after_context": "FADE_BACK_TO_SUBTLE",
            "npc_name": "HOVER_ONLY",
            "no_permanent_inventory_panel": True,
            "no_large_dialogue_modal": True,
            "important_dialogue": "WORLD_BUBBLE_PLUS_BOTTOM_ACCESSIBILITY_LINE",
            "stamina": {
                "presentation": "YELLOW_RADIAL_CIRCLE_ADJACENT_TO_PLAYER",
                "hide_when_full_and_inactive": True,
                "never_permanent_full_ring": True,
            },
            "weapon_quickslots": self.weapon_quickslot_presentation(),
            "ui_language": self.ui_language_contract(),
            "channels": list(self.channels()),
            "accessibility": self.accessibility_contract(),
            "authority": AUTHORITY,
        }

    def deterministic_signature(self) -> str:
        raw = json.dumps({"contract": self.contract(), "candidates": HUD_CANDIDATES}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
