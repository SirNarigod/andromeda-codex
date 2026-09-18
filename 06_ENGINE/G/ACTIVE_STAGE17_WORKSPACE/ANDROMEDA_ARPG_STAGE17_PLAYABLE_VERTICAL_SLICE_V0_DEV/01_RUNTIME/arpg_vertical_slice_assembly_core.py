from __future__ import annotations

import inspect
import json
import math
from typing import Any, Iterable

from living_runtime import ConflictError, canonical_json, sha256_text
from arpg_interaction_intent_core import InteractionIntentResolver
from arpg_ground_loot_core import GroundLootCore
from arpg_terrain_traversal_streaming_core import TerrainTraversalStreamingCore
from arpg_realtime_dialogue_core import RealtimeDialogueCore
from arpg_minimal_hud_core import MinimalHUDCore
from arpg_camera_presentation_core import CameraPresentationCore
from arpg_gamefeel_feedback_core import GameFeelFeedbackCore
from arpg_water_bag_survival_core import WaterBagSurvivalCore


ACTIVITY_TO_DROP_SOURCE = {
    "MINING": "ORE",
    "LOGGING": "TREE",
    "FORAGING": "FLORA",
    "AGRICULTURE": "AGRICULTURE",
    "HUNTING": "HUNTING",
    "FISHING": "FISHING",
}

ACTIVITY_TO_ICON_ITEM_KIND = {
    "MINING": "MINERAL",
    "LOGGING": "WOOD",
    "FORAGING": "FLORA",
    "AGRICULTURE": "FLORA",
    "HUNTING": "MATERIAL",
    "FISHING": "FOOD",
}


class VerticalSliceAssemblyCore:
    """Stage16A pre-Godot integration facade.

    This layer does not replace Stage01-15 authorities. It reconciles their outputs into
    the authored Stage16A interaction/presentation contracts so the first vertical slice
    can be proven before scene/node implementation in Godot.
    """

    VERSION = "V0.8.0-PRE-GODOT"
    STAGE = "16A/23"
    AUTHORITY = "ANDROMEDA_ARPG_STAGE16A_VERTICAL_SLICE_ASSEMBLY_PRE_GODOT"

    def __init__(self, engine: Any, world_instance_id: str) -> None:
        self.engine = engine
        self.runtime = engine.runtime
        self.world_instance_id = str(world_instance_id)
        self.interaction = InteractionIntentResolver()
        self.ground_loot = GroundLootCore(self.runtime.conn, self.world_instance_id)
        self.terrain = TerrainTraversalStreamingCore()
        self.dialogue = RealtimeDialogueCore()
        self.hud = MinimalHUDCore()
        self.camera = CameraPresentationCore()
        self.feedback = GameFeelFeedbackCore()
        self.water_bag = WaterBagSurvivalCore(self.engine, self.world_instance_id, self.ground_loot)
        self._schema()

    def _schema(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS arpg_stage16a_profile_prefs(
                    world_instance_id TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, profile_ref)
                );
                CREATE TABLE IF NOT EXISTS arpg_stage16a_events(
                    world_instance_id TEXT NOT NULL,
                    event_ref TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    result_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, event_ref)
                );
                CREATE TABLE IF NOT EXISTS arpg_stage16a_weapon_loadouts(
                    world_instance_id TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, profile_ref)
                );
                """
            )
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('arpg_stage16a_vertical_slice_version',?)",
                (self.VERSION,),
            )

    def contract(self) -> dict[str, Any]:
        return {
            "version": self.VERSION,
            "stage": self.STAGE,
            "authority": self.AUTHORITY,
            "status": "PRE_GODOT_INTEGRATION_ONLY",
            "flow": [
                "SPAWN",
                "EXPLORE_TERRAIN_STAMINA_LOAD",
                "NPC_REALTIME_DIALOGUE",
                "QUEST_OBJECTIVE",
                "COMBAT",
                "ENEMY_GROUND_LOOT",
                "PICKUP_TO_INVENTORY",
                "GATHERING_TO_GROUND_LOOT",
                "VENDOR_INTERACTION",
                "SAVE",
                "PLAYER_DEATH",
                "RESPAWN",
            ],
            "physical_resource_rule": "PHYSICAL_WORLD_SOURCE_MUST_GROUND_LOOT_BEFORE_INVENTORY",
            "pickup_radius_m": 0.5,
            "gathering_delivery_mode_vertical_slice": "GROUND_LOOT",
            "legacy_gathering_delivery_mode": "INVENTORY_BACKWARD_COMPATIBILITY_ONLY",
            "auto_pickup_preference_persistent": True,
            "weapon_loadout": {
                "max_quick_slots": 2,
                "simultaneously_active_weapons": 1,
                "slots": [1, 2],
                "switch_inputs": ["KEY_1", "KEY_2", "MOUSE_WHEEL"],
                "zoom_input": "ZOOM_MODIFIER_HELD_PLUS_MOUSE_WHEEL",
                "menu_wheel_behavior": "UI_SCROLL_ONLY_NO_WEAPON_SWAP_NO_CAMERA_ZOOM",
                "authority": "STAGE16A_RUNTIME_NOT_GODOT_PRESENTATION",
            },
            "stamina_hud": {
                "shape": "YELLOW_RADIAL_CIRCLE",
                "placement": "ADJACENT_TO_PLAYER",
                "hide_when_full_and_inactive": True,
            },
            "ui_language": "UNIFIED_WHITE_ROUNDED_LIGHT_LEGIBLE_CONSOLE_UI",
            "water_bag_survival": self.water_bag.contract(),
            "godot_gate": "PENDING_PC_AND_EDITOR_BRIDGE",
            "art_dependency": "NONE_PLACEHOLDER_READY",
            "canon_mutation": False,
        }

    def _event_row(self, event_ref: str):
        return self.runtime.conn.execute(
            "SELECT * FROM arpg_stage16a_events WHERE world_instance_id=? AND event_ref=?",
            (self.world_instance_id, str(event_ref)),
        ).fetchone()

    def _event_existing(self, event_ref: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = self._event_row(event_ref)
        if not row:
            return None
        ptext = canonical_json(payload)
        if row["event_type"] != event_type or row["payload_hash"] != sha256_text(ptext):
            raise ConflictError("STAGE16A_EVENT_REF_CONFLICT")
        if sha256_text(row["payload_json"]) != row["payload_hash"]:
            raise RuntimeError("STAGE16A_EVENT_PAYLOAD_HASH_MISMATCH")
        if sha256_text(row["result_json"]) != row["result_hash"]:
            raise RuntimeError("STAGE16A_EVENT_RESULT_HASH_MISMATCH")
        out = json.loads(row["result_json"])
        out["idempotent_replay"] = True
        return out

    def _record_event(self, event_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        ptext = canonical_json(payload)
        rtext = canonical_json(result)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT INTO arpg_stage16a_events VALUES(?,?,?,?,?,?,?)",
                (
                    self.world_instance_id,
                    str(event_ref),
                    event_type,
                    ptext,
                    sha256_text(ptext),
                    rtext,
                    sha256_text(rtext),
                ),
            )
        return result

    def ensure_profile_preferences(self, profile_ref: str) -> dict[str, Any]:
        self.engine.arpg(self.world_instance_id).profile(profile_ref)
        row = self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_stage16a_profile_prefs WHERE world_instance_id=? AND profile_ref=?",
            (self.world_instance_id, profile_ref),
        ).fetchone()
        if row:
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                raise RuntimeError("STAGE16A_PROFILE_PREF_HASH_MISMATCH")
            return json.loads(row["payload_json"])
        payload = {
            "profile_ref": profile_ref,
            "auto_pickup_enabled": False,
            "reduced_motion": False,
            "dialogue_duration_scale": 1.0,
            "font_scale": 1.0,
            "authority": "PLAYER_PRESENTATION_PREFERENCES_RUNTIME",
        }
        text = canonical_json(payload)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT INTO arpg_stage16a_profile_prefs VALUES(?,?,?,?)",
                (self.world_instance_id, profile_ref, text, sha256_text(text)),
            )
        return payload

    def _save_preferences(self, payload: dict[str, Any]) -> None:
        text = canonical_json(payload)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO arpg_stage16a_profile_prefs VALUES(?,?,?,?)",
                (self.world_instance_id, payload["profile_ref"], text, sha256_text(text)),
            )

    def set_auto_pickup(self, profile_ref: str, enabled: bool, *, event_ref: str) -> dict[str, Any]:
        payload = {"profile_ref": profile_ref, "enabled": bool(enabled)}
        replay = self._event_existing(event_ref, "SET_AUTO_PICKUP", payload)
        if replay is not None:
            return replay
        prefs = self.ensure_profile_preferences(profile_ref)
        prefs["auto_pickup_enabled"] = bool(enabled)
        self._save_preferences(prefs)
        result = {
            "status": "PASS",
            "profile_ref": profile_ref,
            "enabled": bool(enabled),
            "hud": self.hud.auto_pickup_status(bool(enabled)),
            "idempotent_replay": False,
        }
        return self._record_event(event_ref, "SET_AUTO_PICKUP", payload, result)

    def ensure_weapon_loadout(self, profile_ref: str) -> dict[str, Any]:
        self.engine.arpg(self.world_instance_id).profile(profile_ref)
        row = self.runtime.conn.execute(
            "SELECT payload_json,payload_hash FROM arpg_stage16a_weapon_loadouts WHERE world_instance_id=? AND profile_ref=?",
            (self.world_instance_id, profile_ref),
        ).fetchone()
        if row:
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                raise RuntimeError("STAGE16A_WEAPON_LOADOUT_HASH_MISMATCH")
            return json.loads(row["payload_json"])
        payload = {
            "profile_ref": profile_ref,
            "slots": {"1": None, "2": None},
            "active_slot": None,
            "max_quick_slots": 2,
            "simultaneously_active_weapons": 1,
            "authority": "STAGE16A_TWO_WEAPON_QUICK_LOADOUT",
        }
        self._save_weapon_loadout(payload)
        return payload

    def _save_weapon_loadout(self, payload: dict[str, Any]) -> None:
        text = canonical_json(payload)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO arpg_stage16a_weapon_loadouts VALUES(?,?,?,?)",
                (self.world_instance_id, payload["profile_ref"], text, sha256_text(text)),
            )

    def _validate_quickslot_weapon(self, profile_ref: str, instance_ref: str) -> tuple[bool, str | None]:
        items = self.engine.items_arpg(self.world_instance_id)
        try:
            inv = items.inventory_snapshot(profile_ref)
        except KeyError:
            items.ensure_inventory(profile_ref)
            inv = items.inventory_snapshot(profile_ref)
        if instance_ref not in inv.get("instance_refs", []):
            return False, "WEAPON_INSTANCE_NOT_OWNED"
        inst = items.instance(instance_ref)
        definition = items.definition(inst["item_ref"])
        if definition.get("item_kind") != "WEAPON":
            return False, "QUICKSLOT_ACCEPTS_WEAPON_ONLY"
        return True, None

    def assign_weapon_slot(self, profile_ref: str, slot: int, instance_ref: str, *, event_ref: str) -> dict[str, Any]:
        slot = int(slot)
        if slot not in (1, 2):
            raise ValueError("WEAPON_QUICKSLOT_MUST_BE_1_OR_2")
        payload = {"profile_ref": profile_ref, "slot": slot, "instance_ref": str(instance_ref)}
        replay = self._event_existing(event_ref, "WEAPON_SLOT_ASSIGN", payload)
        if replay is not None:
            return replay
        loadout = self.ensure_weapon_loadout(profile_ref)
        ok, reason = self._validate_quickslot_weapon(profile_ref, str(instance_ref))
        if not ok:
            return self._record_event(event_ref, "WEAPON_SLOT_ASSIGN", payload, {
                "status": "REJECTED", "reason": reason, "idempotent_replay": False
            })
        other = "2" if slot == 1 else "1"
        if loadout["slots"].get(other) == str(instance_ref):
            return self._record_event(event_ref, "WEAPON_SLOT_ASSIGN", payload, {
                "status": "REJECTED", "reason": "WEAPON_ALREADY_ASSIGNED_TO_OTHER_QUICKSLOT", "idempotent_replay": False
            })
        replaced = loadout["slots"].get(str(slot))
        loadout["slots"][str(slot)] = str(instance_ref)
        self._save_weapon_loadout(loadout)
        return self._record_event(event_ref, "WEAPON_SLOT_ASSIGN", payload, {
            "status": "PASS", "slot": slot, "instance_ref": str(instance_ref),
            "replaced_instance_ref": replaced, "loadout": loadout, "idempotent_replay": False
        })

    def activate_weapon_slot(self, profile_ref: str, slot: int, *, event_ref: str) -> dict[str, Any]:
        slot = int(slot)
        if slot not in (1, 2):
            raise ValueError("WEAPON_QUICKSLOT_MUST_BE_1_OR_2")
        payload = {"profile_ref": profile_ref, "slot": slot}
        replay = self._event_existing(event_ref, "WEAPON_SLOT_ACTIVATE", payload)
        if replay is not None:
            return replay
        loadout = self.ensure_weapon_loadout(profile_ref)
        instance_ref = loadout["slots"].get(str(slot))
        if not instance_ref:
            return self._record_event(event_ref, "WEAPON_SLOT_ACTIVATE", payload, {
                "status": "REJECTED", "reason": "WEAPON_QUICKSLOT_EMPTY", "slot": slot, "idempotent_replay": False
            })
        ok, reason = self._validate_quickslot_weapon(profile_ref, instance_ref)
        if not ok:
            return self._record_event(event_ref, "WEAPON_SLOT_ACTIVATE", payload, {
                "status": "REJECTED", "reason": reason, "slot": slot, "idempotent_replay": False
            })
        equip = self.engine.items_arpg(self.world_instance_id).equip(
            profile_ref, instance_ref, "MAIN_HAND", event_ref=f"{event_ref}:MAIN_HAND"
        )
        if equip.get("status") != "PASS":
            return self._record_event(event_ref, "WEAPON_SLOT_ACTIVATE", payload, {
                "status": "REJECTED", "reason": equip.get("reason", "MAIN_HAND_EQUIP_FAILED"),
                "slot": slot, "equip": equip, "idempotent_replay": False
            })
        previous = loadout.get("active_slot")
        loadout["active_slot"] = slot
        self._save_weapon_loadout(loadout)
        return self._record_event(event_ref, "WEAPON_SLOT_ACTIVATE", payload, {
            "status": "PASS", "slot": slot, "previous_slot": previous,
            "instance_ref": instance_ref, "equip": equip, "loadout": loadout, "idempotent_replay": False
        })

    def cycle_weapon_slot(self, profile_ref: str, direction: int, *, event_ref: str) -> dict[str, Any]:
        direction = 1 if int(direction) >= 0 else -1
        payload = {"profile_ref": profile_ref, "direction": direction}
        replay = self._event_existing(event_ref, "WEAPON_SLOT_CYCLE", payload)
        if replay is not None:
            return replay
        loadout = self.ensure_weapon_loadout(profile_ref)
        populated = [i for i in (1, 2) if loadout["slots"].get(str(i))]
        if not populated:
            return self._record_event(event_ref, "WEAPON_SLOT_CYCLE", payload, {
                "status": "REJECTED", "reason": "NO_WEAPON_IN_QUICKSLOTS", "idempotent_replay": False
            })
        current = loadout.get("active_slot")
        if len(populated) == 1:
            target = populated[0]
        elif current not in populated:
            target = populated[0] if direction > 0 else populated[-1]
        else:
            target = 2 if current == 1 else 1
        activated = self.activate_weapon_slot(profile_ref, target, event_ref=f"{event_ref}:ACTIVATE")
        result = {
            "status": activated.get("status"), "direction": direction, "target_slot": target,
            "activation": activated, "idempotent_replay": False
        }
        if activated.get("status") != "PASS":
            result["reason"] = activated.get("reason", "WEAPON_CYCLE_ACTIVATION_FAILED")
        return self._record_event(event_ref, "WEAPON_SLOT_CYCLE", payload, result)

    def _profile_avatar(self, profile_ref: str) -> str:
        return self.engine.arpg(self.world_instance_id).profile(profile_ref)["avatar_ref"]

    def _inventory_metrics(self, profile_ref: str) -> dict[str, Any]:
        return self.water_bag.carry_metrics(profile_ref)

    def traversal_effect(
        self,
        profile_ref: str,
        *,
        distance_m: float,
        slope_deg: float,
        surface_ref: str,
        ascending: bool = True,
        event_ref: str,
    ) -> dict[str, Any]:
        payload = {
            "profile_ref": profile_ref,
            "distance_m": float(distance_m),
            "slope_deg": float(slope_deg),
            "surface_ref": str(surface_ref).upper(),
            "ascending": bool(ascending),
        }
        replay = self._event_existing(event_ref, "TRAVERSAL_EFFECT", payload)
        if replay is not None:
            return replay
        metrics = self._inventory_metrics(profile_ref)
        sample = self.terrain.traversal_sample(
            distance_m=distance_m,
            slope_deg=slope_deg,
            surface_ref=surface_ref,
            current_weight=metrics["current_weight"],
            weight_capacity=metrics["weight_capacity"],
            ascending=ascending,
        )
        if sample["status"] != "PASS":
            return self._record_event(event_ref, "TRAVERSAL_EFFECT", payload, {
                "status": "REJECTED",
                "reason": sample.get("reason", "TRAVERSAL_BLOCKED"),
                "traversal": sample,
                "idempotent_replay": False,
            })
        avatar_ref = self._profile_avatar(profile_ref)
        stamina = self.engine.movement(self.world_instance_id).apply_external_stamina_cost(
            avatar_ref,
            sample["stamina_cost"],
            reason="STAGE16A_TERRAIN_LOAD_TRAVERSAL",
        )
        result = {
            "status": "PASS",
            "profile_ref": profile_ref,
            "avatar_ref": avatar_ref,
            "traversal": sample,
            "stamina": stamina,
            "hud": self.hud.compose({"stamina_active": sample["stamina_cost"] > 0}),
            "idempotent_replay": False,
        }
        return self._record_event(event_ref, "TRAVERSAL_EFFECT", payload, result)

    def dialogue_frame(self, lines: Iterable[dict[str, Any]], *, combat_active: bool = False) -> dict[str, Any]:
        presentation = self.dialogue.select_visible_lines(lines)
        important = any(bool(x.get("important")) for x in presentation["visible"])
        return {
            "status": "PASS",
            "dialogue": presentation,
            "hud": self.hud.compose({"combat_active": combat_active, "important_dialogue": important}),
            "world_paused": False,
            "next_button": False,
        }

    def _drop_source_for_node(self, node: dict[str, Any]) -> tuple[str, str]:
        activity = str(node["activity_type"]).upper()
        if activity not in ACTIVITY_TO_DROP_SOURCE:
            raise ValueError("UNSUPPORTED_GATHERING_ACTIVITY_FOR_GROUND_LOOT")
        return ACTIVITY_TO_DROP_SOURCE[activity], ACTIVITY_TO_ICON_ITEM_KIND[activity]

    def _ground_delivery_sink(self, *, worker_ref: str, node: dict[str, Any], quantity: int, event_ref: str, preview_only: bool = False) -> dict[str, Any]:
        source_kind, item_kind = self._drop_source_for_node(node)
        self.engine.items_arpg(self.world_instance_id).definition(node["output_item_ref"])
        profile = self.engine.arpg(self.world_instance_id).profile(worker_ref)
        pos = self.engine.movement(self.world_instance_id).state(profile["avatar_ref"])
        candidate = {"iso_x_m": pos["iso_x_m"], "iso_y_m": pos["iso_y_m"], "altitude_m": pos["altitude_m"]}
        if preview_only:
            if int(quantity) <= 0 or not all(math.isfinite(float(v)) for v in candidate.values()):
                return {"status": "REJECTED", "reason": "INVALID_PHYSICAL_DELIVERY_PREVIEW"}
            return {
                "status": "PASS",
                "preview_only": True,
                "source_kind": source_kind,
                "item_kind": item_kind,
                "item_ref": node["output_item_ref"],
                "quantity": int(quantity),
                "physical_world_first": True,
            }
        return self.ground_loot.spawn_drop(
            source_ref=node["node_ref"],
            source_kind=source_kind,
            item_ref=node["output_item_ref"],
            item_kind=item_kind,
            quantity=int(quantity),
            candidate_position=candidate,
            event_ref=event_ref,
        )

    def gather_to_ground_loot(self, profile_ref: str, node_ref: str, requested_units: int, *, event_ref: str, danger_clearance_ref: str | None = None) -> dict[str, Any]:
        gathering = self.engine.gathering_arpg(self.world_instance_id)
        node = gathering.node(node_ref)
        create = gathering.create_work_order(profile_ref, node_ref, requested_units, event_ref=f"{event_ref}:CREATE")
        if create.get("status") != "PASS":
            return {"status": "REJECTED", "reason": create.get("reason", "WORK_ORDER_CREATE_FAILED"), "create": create}
        order_ref = create["order"]["order_ref"]
        execute = gathering.execute_work_order(
            order_ref,
            event_ref=f"{event_ref}:EXECUTE",
            danger_clearance_ref=danger_clearance_ref,
            delivery_mode="GROUND_LOOT",
            delivery_sink=self._ground_delivery_sink,
        )
        if execute.get("status") != "PASS":
            return execute
        return {
            "status": "PASS",
            "node_ref": node_ref,
            "activity_type": node["activity_type"],
            "work_result": execute,
            "drop_ref": ((execute.get("physical_delivery") or {}).get("drop_ref")),
            "direct_to_inventory": False,
            "physical_world_first": True,
        }

    def confirm_drop_settled(self, drop_ref: str, *, settled_position: dict[str, float], reachable: bool, event_ref: str) -> dict[str, Any]:
        return self.ground_loot.confirm_settled(
            drop_ref,
            settled_position=settled_position,
            reachable=reachable,
            event_ref=event_ref,
        )

    def pickup_drop(self, profile_ref: str, drop_ref: str, *, physical_distance_m: float, reachable_now: bool, event_ref: str) -> dict[str, Any]:
        result = self.ground_loot.pickup(
            drop_ref,
            profile_ref=profile_ref,
            physical_distance_m=physical_distance_m,
            reachable_now=reachable_now,
            event_ref=event_ref,
            grant_item=self.water_bag.grant_carried_item,
        )
        if result.get("status") == "PASS":
            drop = self.ground_loot.drop(drop_ref)
            result["hud"] = self.hud.pickup_feedback(
                item_type=drop["item_kind"], quantity=int(drop["quantity"]), rarity=str(drop.get("rarity") or "COMMON")
            )
            result["feedback"] = self.feedback.pickup_feedback(
                item_type=drop["item_kind"], quantity=int(drop["quantity"]), rarity=str(drop.get("rarity") or "COMMON")
            )
        return result

    def auto_pickup_nearby(self, profile_ref: str, distances_by_drop_ref: dict[str, float], *, event_prefix: str) -> dict[str, Any]:
        prefs = self.ensure_profile_preferences(profile_ref)
        candidates = []
        active = {d["drop_ref"]: d for d in self.ground_loot.active_drops()}
        for ref, distance in distances_by_drop_ref.items():
            drop = active.get(ref)
            if not drop:
                continue
            candidates.append({
                "ref": ref,
                "kind": "GROUND_LOOT",
                "physical_distance_m": float(distance),
                "reachable": bool(drop.get("reachable")),
                "direct_hit": True,
            })
        plan = self.interaction.resolve_auto_pickup(candidates, enabled=bool(prefs["auto_pickup_enabled"]))
        picked, rejected = [], []
        for idx, ref in enumerate(plan["pickup_refs"]):
            out = self.pickup_drop(
                profile_ref,
                ref,
                physical_distance_m=float(distances_by_drop_ref[ref]),
                reachable_now=True,
                event_ref=f"{event_prefix}:{idx}:{ref}",
            )
            (picked if out.get("status") == "PASS" else rejected).append(out)
        return {"status": "PASS", "plan": plan, "picked": picked, "rejected": rejected, "interrupts_action": False}

    def spawn_defeated_enemy_drop(self, enemy_ref: str, *, item_ref: str, item_kind: str, quantity: int, event_ref: str) -> dict[str, Any]:
        state = self.engine.combat_arpg(self.world_instance_id).ensure_enemy(enemy_ref)
        if state.get("life_state") != "DEFEATED":
            return {"status": "REJECTED", "reason": "ENEMY_NOT_DEFEATED", "enemy_ref": enemy_ref}
        self.engine.items_arpg(self.world_instance_id).definition(item_ref)
        pos = self.engine.movement(self.world_instance_id).state(enemy_ref)
        return self.ground_loot.spawn_drop(
            source_ref=enemy_ref,
            source_kind="ENEMY",
            item_ref=item_ref,
            item_kind=item_kind,
            quantity=int(quantity),
            candidate_position={"iso_x_m":pos["iso_x_m"],"iso_y_m":pos["iso_y_m"],"altitude_m":pos["altitude_m"]},
            event_ref=event_ref,
        )

    def execute_trade_carried(self, profile_ref: str, quote_ref: str, *, event_ref: str) -> dict[str, Any]:
        economy = self.engine.economy_arpg(self.world_instance_id)
        quote = economy._quote(quote_ref)
        if quote.get("owner_ref") != profile_ref:
            return {"status":"REJECTED","reason":"QUOTE_OWNER_MISMATCH"}
        inv_owner = self.water_bag.effective_inventory_owner(profile_ref)
        if quote.get("direction") == "BUY":
            fit = self.water_bag.can_accept_carried(profile_ref, quote["item_ref"], int(quote["quantity"]))
            if fit.get("status") != "PASS":
                return fit
        return economy.execute_trade(quote_ref, event_ref=event_ref, inventory_owner_ref=inv_owner)

    def _retained_weapon_refs(self, owner_ref: str) -> list[str]:
        try:
            loadout = self.ensure_weapon_loadout(owner_ref)
        except Exception:
            return []
        return [str(x) for x in loadout.get("slots", {}).values() if x]

    def equip_bag(self, owner_ref: str, *, event_ref: str) -> dict[str, Any]:
        return self.water_bag.equip_new_bag(
            owner_ref, event_ref=event_ref, retained_instance_refs=self._retained_weapon_refs(owner_ref)
        )

    def water_traversal_effect(
        self, profile_ref: str, *, depth_m: float, flow_speed_mps: float, distance_m: float,
        under_bridge: bool = False, event_ref: str
    ) -> dict[str, Any]:
        metrics = self._inventory_metrics(profile_ref)
        capacity = max(0.001, float(metrics["weight_capacity"]))
        load_fraction = max(0.0, float(metrics["current_weight"]) / capacity)
        sample = self.water_bag.water_traversal_sample(
            actor_kind="PLAYER", depth_m=depth_m, flow_speed_mps=flow_speed_mps,
            distance_m=distance_m, load_fraction=load_fraction, under_bridge=under_bridge,
        )
        if sample.get("status") != "PASS":
            return sample
        avatar = self._profile_avatar(profile_ref)
        spend = self.engine.movement(self.world_instance_id).apply_external_stamina_cost(
            avatar, float(sample["stamina_cost"]), reason="WATER_TRAVERSAL_STAGE16A"
        )
        return {"status":"PASS","profile_ref":profile_ref,"traversal":sample,"stamina":spend}

    def vehicle_water_traversal(
        self, *, depth_m: float, flow_speed_mps: float, distance_m: float, under_bridge: bool = False
    ) -> dict[str, Any]:
        return self.water_bag.water_traversal_sample(
            actor_kind="VEHICLE", depth_m=depth_m, flow_speed_mps=flow_speed_mps,
            distance_m=distance_m, load_fraction=0.0, under_bridge=under_bridge,
        )

    def water_exhaustion_tick(
        self, actor_ref: str, *, actor_kind: str, stamina: float, in_water: bool, delta_s: float,
        event_ref: str, position: dict[str, float] | None = None
    ) -> dict[str, Any]:
        out = self.water_bag.exhaustion_tick(
            actor_ref, actor_kind=actor_kind, stamina=stamina, in_water=in_water, delta_s=delta_s, event_ref=event_ref
        )
        if out.get("defeat_required") and str(actor_kind).upper() == "PLAYER":
            profile_ref = str(actor_ref)
            try:
                ch = self.engine.character(self.world_instance_id).ensure_profile(profile_ref)
                ch["vitals"]["life_state"] = "DEAD"
                ch["vitals"]["health"] = 0.0
                self.engine.character(self.world_instance_id)._save(ch)
            except Exception:
                pass
            pos = position or {"iso_x_m":0.0,"iso_y_m":0.0,"altitude_m":0.0}
            out["bag_drop"] = self.water_bag.drop_bag_on_death(
                profile_ref, in_water=bool(in_water), position=pos, event_ref=f"{event_ref}:BAGDROP"
            )
        elif out.get("defeat_required") and str(actor_kind).upper() == "NPC":
            pos = position or {"iso_x_m":0.0,"iso_y_m":0.0,"altitude_m":0.0}
            out["bag_drop"] = self.water_bag.drop_bag_on_death(
                str(actor_ref), in_water=bool(in_water), position=pos, event_ref=f"{event_ref}:BAGDROP"
            )
        return out

    def drop_bag_for_death(self, owner_ref: str, *, in_water: bool, position: dict[str, float], event_ref: str) -> dict[str, Any]:
        return self.water_bag.drop_bag_on_death(owner_ref, in_water=in_water, position=position, event_ref=event_ref)

    def recover_bag(self, bag_ref: str, claimant_ref: str, *, claimant_kind: str, event_ref: str) -> dict[str, Any]:
        return self.water_bag.recover_bag(bag_ref, claimant_ref, claimant_kind=claimant_kind, event_ref=event_ref)

    def mark_drop_in_water(self, drop_ref: str, *, in_water: bool, flow_speed_mps: float, event_ref: str) -> dict[str, Any]:
        return self.water_bag.mark_ground_drop_water(drop_ref, in_water=in_water, flow_speed_mps=flow_speed_mps, event_ref=event_ref)

    def advance_water_time(self, delta_s: float, *, event_ref: str) -> dict[str, Any]:
        return self.water_bag.advance_water_time(delta_s, event_ref=event_ref)

    def interaction_feedback(self, button: str, candidates: Iterable[dict[str, Any]], *, ground_point: dict[str, float] | None = None) -> dict[str, Any]:
        intent = self.interaction.resolve_click(button, candidates, ground_point=ground_point)
        accepted = intent.get("status") == "PASS"
        feedback_intent = intent.get("intent", "APPROACH_INTERACT")
        fb = self.feedback.click_feedback(feedback_intent, accepted=accepted, reason=intent.get("reason"))
        return {"status": "PASS", "intent": intent, "feedback": fb}

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        contract = self.contract()
        if contract["pickup_radius_m"] != 0.5:
            failures.append("PICKUP_RADIUS_CONTRACT")
        if self.dialogue.presentation_contract().get("world_pause_required"):
            failures.append("DIALOGUE_WORLD_PAUSE_FORBIDDEN")
        if self.camera.contract().get("world_pause"):
            failures.append("CAMERA_WORLD_PAUSE_FORBIDDEN")
        if self.feedback.contract().get("may_change_gameplay_result"):
            failures.append("GAMEFEEL_MAY_NOT_CHANGE_GAMEPLAY")
        params = inspect.signature(self.engine.gathering_arpg(self.world_instance_id).execute_work_order).parameters
        if "delivery_mode" not in params or "delivery_sink" not in params:
            failures.append("GATHERING_GROUND_LOOT_DELIVERY_EXTENSION_MISSING")
        if not hasattr(self.engine.movement(self.world_instance_id), "apply_external_stamina_cost"):
            failures.append("MOVEMENT_EXTERNAL_STAMINA_BRIDGE_MISSING")
        water_verify = self.water_bag.verify()
        if water_verify.get("status") != "PASS":
            failures.extend("WATER_BAG:" + x for x in water_verify.get("failures", []))

        for row in self.runtime.conn.execute(
            "SELECT profile_ref,payload_json,payload_hash FROM arpg_stage16a_profile_prefs WHERE world_instance_id=?",
            (self.world_instance_id,),
        ).fetchall():
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                failures.append("PROFILE_PREF_HASH:" + row["profile_ref"])
        for row in self.runtime.conn.execute(
            "SELECT profile_ref,payload_json,payload_hash FROM arpg_stage16a_weapon_loadouts WHERE world_instance_id=?",
            (self.world_instance_id,),
        ).fetchall():
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                failures.append("WEAPON_LOADOUT_HASH:" + row["profile_ref"])
                continue
            loadout = json.loads(row["payload_json"])
            if set(loadout.get("slots", {})) != {"1", "2"} or loadout.get("max_quick_slots") != 2:
                failures.append("WEAPON_LOADOUT_SLOT_CONTRACT:" + row["profile_ref"])
                continue
            active = loadout.get("active_slot")
            if active not in (None, 1, 2):
                failures.append("WEAPON_LOADOUT_ACTIVE_SLOT:" + row["profile_ref"])
            refs = [x for x in loadout["slots"].values() if x]
            if len(refs) != len(set(refs)):
                failures.append("WEAPON_LOADOUT_DUPLICATE_INSTANCE:" + row["profile_ref"])
            for ref in refs:
                ok, reason = self._validate_quickslot_weapon(row["profile_ref"], ref)
                if not ok:
                    failures.append("WEAPON_LOADOUT_INVALID_INSTANCE:" + row["profile_ref"] + ":" + str(reason))
            if active in (1, 2):
                expected = loadout["slots"].get(str(active))
                try:
                    actual = self.engine.items_arpg(self.world_instance_id).inventory_snapshot(row["profile_ref"])["equipped"].get("MAIN_HAND")
                except KeyError:
                    actual = None
                if expected != actual:
                    failures.append("WEAPON_LOADOUT_ACTIVE_MAIN_HAND_MISMATCH:" + row["profile_ref"])
        for row in self.runtime.conn.execute(
            "SELECT event_ref,payload_json,payload_hash,result_json,result_hash FROM arpg_stage16a_events WHERE world_instance_id=?",
            (self.world_instance_id,),
        ).fetchall():
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                failures.append("EVENT_PAYLOAD_HASH:" + row["event_ref"])
            if sha256_text(row["result_json"]) != row["result_hash"]:
                failures.append("EVENT_RESULT_HASH:" + row["event_ref"])
        for row in self.runtime.conn.execute(
            "SELECT drop_ref,payload_json,payload_hash FROM arpg_ground_loot WHERE world_instance_id=?",
            (self.world_instance_id,),
        ).fetchall():
            if sha256_text(row["payload_json"]) != row["payload_hash"]:
                failures.append("GROUND_LOOT_HASH:" + row["drop_ref"])
        return {
            "status": "PASS" if not failures else "FAIL",
            "failures": failures,
            "active_ground_drops": len(self.ground_loot.active_drops()),
            "preferences": self.runtime.conn.execute(
                "SELECT COUNT(*) c FROM arpg_stage16a_profile_prefs WHERE world_instance_id=?",
                (self.world_instance_id,),
            ).fetchone()["c"],
            "weapon_loadouts": self.runtime.conn.execute(
                "SELECT COUNT(*) c FROM arpg_stage16a_weapon_loadouts WHERE world_instance_id=?",
                (self.world_instance_id,),
            ).fetchone()["c"],
            "water_bag": water_verify,
            "events": self.runtime.conn.execute(
                "SELECT COUNT(*) c FROM arpg_stage16a_events WHERE world_instance_id=?",
                (self.world_instance_id,),
            ).fetchone()["c"],
            "godot_gate": contract["godot_gate"],
            "authority": self.AUTHORITY,
        }
