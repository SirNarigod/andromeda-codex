from __future__ import annotations

import os
import pathlib
import shutil
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / "01_RUNTIME"))

from integrated_arpg_engine_v16a import IntegratedARPGEngineV16A
from living_runtime import ConflictError

MASTER = os.environ.get("ANDROMEDA_MASTER_RELEASE", "/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip")


class Stage16AVerticalSliceAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        td = pathlib.Path(cls.tmp.name)
        cls.e = IntegratedARPGEngineV16A(str(td / "world.sqlite"), master_release_path=MASTER, save_root=td / "saves")
        out = cls.e.create_world("stage16a:vertical", 161650)
        cls.wid = out["world"]["world_instance_id"]
        cls.profile = cls.e.arpg(cls.wid).create_profile("stage16a:vertical", display_name="Vertical Slice Tester")["profile"]
        cls.pr = cls.profile["profile_ref"]
        cls.avatar = cls.profile["avatar_ref"]
        cls.s = cls.e.stage16a(cls.wid)
        cls.items = cls.e.items_arpg(cls.wid)
        cls.items.ensure_inventory(cls.pr)
        cls.narrative = cls.e.narrative_arpg(cls.wid)
        cls.ec = cls.e.economy_arpg(cls.wid)
        cls.g = cls.e.gathering_arpg(cls.wid)
        cls.combat = cls.e.combat_arpg(cls.wid)

    @classmethod
    def tearDownClass(cls):
        cls.e.runtime.close()
        cls.tmp.cleanup()

    def test_01_health(self):
        self.assertEqual(self.e.health_arpg_v16a(self.wid)["status"], "PASS")

    def test_02_contract_is_pre_godot_and_physical_world_first(self):
        c = self.s.contract()
        self.assertEqual(c["godot_gate"], "PENDING_PC_AND_EDITOR_BRIDGE")
        self.assertEqual(c["physical_resource_rule"], "PHYSICAL_WORLD_SOURCE_MUST_GROUND_LOOT_BEFORE_INVENTORY")
        self.assertEqual(c["pickup_radius_m"], 0.5)

    def test_03_auto_pickup_default_off(self):
        self.assertFalse(self.s.ensure_profile_preferences(self.pr)["auto_pickup_enabled"])

    def test_04_auto_pickup_toggle_and_replay(self):
        a = self.s.set_auto_pickup(self.pr, True, event_ref="u16:auto:on")
        b = self.s.set_auto_pickup(self.pr, True, event_ref="u16:auto:on")
        self.assertTrue(a["enabled"])
        self.assertTrue(b["idempotent_replay"])
        self.assertTrue(self.s.ensure_profile_preferences(self.pr)["auto_pickup_enabled"])

    def test_05_auto_pickup_conflict_detected(self):
        with self.assertRaises(ConflictError):
            self.s.set_auto_pickup(self.pr, False, event_ref="u16:auto:on")

    def test_06_traversal_uses_inventory_weight_and_consumes_stamina(self):
        before = self.e.movement(self.wid).state(self.avatar)["stamina"]
        out = self.s.traversal_effect(
            self.pr, distance_m=18, slope_deg=10, surface_ref="GRASS_FIELD", ascending=True, event_ref="u16:travel:1"
        )
        after = self.e.movement(self.wid).state(self.avatar)["stamina"]
        self.assertEqual(out["status"], "PASS")
        self.assertLess(after, before)
        self.assertEqual(out["traversal"]["load"]["inventory_authority"], "STAGE05_UNIVERSAL_ITEM_CORE")

    def test_07_traversal_replay_does_not_double_charge_stamina(self):
        before = self.e.movement(self.wid).state(self.avatar)["stamina"]
        out = self.s.traversal_effect(
            self.pr, distance_m=18, slope_deg=10, surface_ref="GRASS_FIELD", ascending=True, event_ref="u16:travel:1"
        )
        after = self.e.movement(self.wid).state(self.avatar)["stamina"]
        self.assertTrue(out["idempotent_replay"])
        self.assertEqual(before, after)

    def test_08_dialogue_is_realtime_nonblocking(self):
        frame = self.s.dialogue_frame([
            {
                "line_ref": "L1", "speaker_ref": "NPC-A", "text": "A ponte está com problemas.",
                "important": True, "distance_m": 2.0, "directed_to_player": True,
            }
        ])
        self.assertFalse(frame["world_paused"])
        self.assertFalse(frame["next_button"])
        self.assertIn("IMPORTANT_DIALOGUE_ACCESSIBILITY", frame["hud"]["visible_channels"])

    def test_09_quest_cycle_uses_real_narrative_core(self):
        q = "QST-S12-VARGA-ORIENTATION"
        self.narrative.accept_quest(self.pr, q, event_ref="u16:q:accept")
        x = self.narrative.submit_objective(
            self.pr, q, "VISIT-VARGA", evidence={"canonical_ref": "CIT-001"}, event_ref="u16:q:visit"
        )
        self.assertEqual(x["quest"]["state"], "READY_TO_TURN_IN")
        y = self.narrative.turn_in_quest(self.pr, q, event_ref="u16:q:turn")
        self.assertEqual(y["quest"]["state"], "COMPLETED")

    def _prepare_enemy(self):
        if hasattr(self.__class__, "enemy_ref"):
            return self.__class__.enemy_ref
        target = None
        for n in self.e.country(self.wid)._all_npc_records():
            if n["id"] == self.avatar:
                continue
            if not (n.get("protection") or {}).get("protected"):
                target = n["id"]
                break
        self.assertIsNotNone(target)
        pstate = self.e.movement(self.wid).state(self.avatar)
        geo = self.e.spatial(self.wid).isometric_to_geodetic(pstate["iso_x_m"], pstate["iso_y_m"], pstate["altitude_m"])
        self.e.movement(self.wid).sync_to_geodetic(target, geo, reason="S16A_TEST_COLOCATE")
        self.combat.ensure_enemy(target)
        self.__class__.enemy_ref = target
        return target

    def test_10_live_enemy_cannot_drop_combat_loot(self):
        target = self._prepare_enemy()
        out = self.s.spawn_defeated_enemy_drop(
            target, item_ref="ITEM-FOOD", item_kind="FOOD", quantity=1, event_ref="u16:enemy:premature"
        )
        self.assertEqual(out["status"], "REJECTED")
        self.assertEqual(out["reason"], "ENEMY_NOT_DEFEATED")

    def test_11_combat_defeat_real_target(self):
        target = self._prepare_enemy()
        enemy = self.combat.ensure_enemy(target)
        enemy["health"] = 0.05
        enemy["life_state"] = "ALIVE"
        self.combat._save_row("arpg_enemy_combat_state", target, enemy)
        got = None
        for i in range(24):
            self.combat.tick_player(self.pr, 1.0)
            out = self.combat.player_attack(self.pr, target, event_ref=f"u16:enemy:hit:{i}")
            if out.get("status") == "PASS" and out.get("lethal"):
                got = out
                break
        self.assertIsNotNone(got)
        self.assertEqual(self.combat.ensure_enemy(target)["life_state"], "DEFEATED")

    def test_12_defeated_enemy_spawns_physical_drop(self):
        target = self._prepare_enemy()
        out = self.s.spawn_defeated_enemy_drop(
            target, item_ref="ITEM-FOOD", item_kind="FOOD", quantity=1, event_ref="u16:enemy:drop"
        )
        self.assertEqual(out["status"], "PASS")
        self.__class__.enemy_drop = out["drop_ref"]
        d = self.s.ground_loot.drop(out["drop_ref"])
        self.assertFalse(d["direct_to_inventory"])
        self.assertFalse(d["settled"])

    def test_13_unsettled_enemy_drop_cannot_be_picked(self):
        out = self.s.pickup_drop(
            self.pr, self.enemy_drop, physical_distance_m=0.1, reachable_now=True, event_ref="u16:enemy:pickup:unsettled"
        )
        self.assertEqual(out["reason"], "DROP_NOT_SETTLED")

    def test_14_enemy_drop_distance_rule_then_pickup(self):
        d = self.s.ground_loot.drop(self.enemy_drop)
        self.s.confirm_drop_settled(
            self.enemy_drop, settled_position=d["candidate_position"], reachable=True, event_ref="u16:enemy:settle"
        )
        far = self.s.pickup_drop(
            self.pr, self.enemy_drop, physical_distance_m=0.5001, reachable_now=True, event_ref="u16:enemy:pickup:far"
        )
        self.assertEqual(far["reason"], "PICKUP_DISTANCE_EXCEEDED")
        near = self.s.pickup_drop(
            self.pr, self.enemy_drop, physical_distance_m=0.5, reachable_now=True, event_ref="u16:enemy:pickup:near"
        )
        self.assertEqual(near["status"], "PASS")

    def _prepare_mining(self):
        if hasattr(self.__class__, "mining_node"):
            return self.__class__.mining_node
        self.g.assign_role(self.pr, "MINING")
        self.items.grant_item(self.pr, "ITEM-TOOL", 1, event_ref="u16:mining:tool")
        n = self.g.list_nodes(activity_type="MINING")[0]
        w = self.e.world_arpg(self.wid)
        st = w.ensure_profile(self.pr)
        st["zone_ref"] = n["zone_ref"]
        st["instance_context"] = {"kind": "OVERWORLD", "ref": n["zone_ref"]}
        w._save_profile(st)
        self.__class__.mining_node = n
        return n

    def test_15_gathering_produces_ground_loot_not_inventory(self):
        n = self._prepare_mining()
        before = self.items.inventory_snapshot(self.pr)["stacks"].get(n["output_item_ref"], 0)
        out = self.s.gather_to_ground_loot(self.pr, n["node_ref"], 2, event_ref="u16:gather:mining")
        after = self.items.inventory_snapshot(self.pr)["stacks"].get(n["output_item_ref"], 0)
        self.assertEqual(out["status"], "PASS")
        self.assertEqual(after, before)
        self.assertFalse(out["direct_to_inventory"])
        self.__class__.gather_drop = out["drop_ref"]
        self.__class__.gather_output = n["output_item_ref"]
        self.__class__.gather_before = before
        self.__class__.gather_quantity = out["work_result"]["produced_units"]

    def test_16_gathering_replay_does_not_duplicate_drop_or_source_consumption(self):
        n = self._prepare_mining()
        before_remaining = self.g.node(n["node_ref"])["remaining_units"]
        out = self.s.gather_to_ground_loot(self.pr, n["node_ref"], 2, event_ref="u16:gather:mining")
        after_remaining = self.g.node(n["node_ref"])["remaining_units"]
        self.assertEqual(out["drop_ref"], self.gather_drop)
        self.assertEqual(before_remaining, after_remaining)
        self.assertTrue(out["work_result"]["idempotent_replay"])

    def test_17_gather_drop_pickup_is_only_inventory_entry_point(self):
        d = self.s.ground_loot.drop(self.gather_drop)
        self.s.confirm_drop_settled(
            self.gather_drop, settled_position=d["candidate_position"], reachable=True, event_ref="u16:gather:settle"
        )
        out = self.s.pickup_drop(
            self.pr, self.gather_drop, physical_distance_m=0.2, reachable_now=True, event_ref="u16:gather:pickup"
        )
        after = self.items.inventory_snapshot(self.pr)["stacks"].get(self.gather_output, 0)
        self.assertEqual(out["status"], "PASS")
        self.assertEqual(after, self.gather_before + self.gather_quantity)

    def test_18_all_gathering_activities_have_physical_drop_mapping(self):
        for activity in self.g.ACTIVITIES:
            node = self.g.list_nodes(activity_type=activity)[0]
            source_kind, item_kind = self.s._drop_source_for_node(node)
            self.assertTrue(source_kind)
            self.assertTrue(item_kind)

    def test_19_auto_pickup_collects_only_nearby_eligible_drop(self):
        pos = self.e.movement(self.wid).state(self.avatar)
        a = self.s.ground_loot.spawn_drop(
            source_ref=self.avatar, source_kind="PLAYER_DROP", item_ref="ITEM-GRAIN", item_kind="MATERIAL", quantity=1,
            candidate_position=pos, event_ref="u16:auto:drop:a",
        )["drop_ref"]
        b = self.s.ground_loot.spawn_drop(
            source_ref=self.avatar, source_kind="PLAYER_DROP", item_ref="ITEM-FRUIT", item_kind="FOOD", quantity=1,
            candidate_position=pos, event_ref="u16:auto:drop:b",
        )["drop_ref"]
        self.s.confirm_drop_settled(a, settled_position=pos, reachable=True, event_ref="u16:auto:settle:a")
        self.s.confirm_drop_settled(b, settled_position=pos, reachable=True, event_ref="u16:auto:settle:b")
        out = self.s.auto_pickup_nearby(self.pr, {a:0.2, b:0.7}, event_prefix="u16:auto:pickup")
        self.assertEqual(len(out["picked"]), 1)
        self.assertEqual(out["picked"][0]["drop_ref"], a)
        self.assertFalse(out["interrupts_action"])
        self.__class__.persistent_active_drop = b

    def test_20_vendor_quote_does_not_auto_purchase(self):
        self.ec.ensure_wallet(self.pr, 1000)
        market = next(v for v in self.ec.list_vendors() if v["location_ref"] == "POI-002")
        before = self.ec.wallet(self.pr)["balance"]
        q = self.ec.price_quote(self.pr, market["vendor_ref"], "ITEM-GRAIN", 1, event_ref="u16:shop:quote")
        self.assertEqual(self.ec.wallet(self.pr)["balance"], before)
        self.__class__.shop_quote = q["quote"]["quote_ref"]

    def test_21_vendor_purchase_requires_explicit_execution(self):
        before = self.items.inventory_snapshot(self.pr)["stacks"].get("ITEM-GRAIN", 0)
        out = self.ec.execute_trade(self.shop_quote, event_ref="u16:shop:buy")
        after = self.items.inventory_snapshot(self.pr)["stacks"].get("ITEM-GRAIN", 0)
        self.assertEqual(out["status"], "PASS")
        self.assertEqual(after, before + 1)

    def test_22_interaction_feedback_preserves_pointer_intent(self):
        x = self.s.interaction_feedback(
            "LEFT", [], ground_point={"iso_x_m": 1.0, "iso_y_m": 2.0}
        )
        self.assertEqual(x["intent"]["intent"], "MOVE_TO_POINT")
        self.assertEqual(x["feedback"]["world_marker"], "SMALL_GROUND_RING")

    def test_23_direct_pointer_hit_wins_overlap(self):
        x = self.s.interaction_feedback("RIGHT", [
            {"ref":"DROP-X","kind":"GROUND_LOOT","screen_distance_px":4,"depth_m":2,"physical_distance_m":0.2},
            {"ref":"NPC-X","kind":"NPC","screen_distance_px":0,"depth_m":1,"hostile":False},
        ])
        self.assertEqual(x["intent"]["target_ref"], "NPC-X")
        self.assertEqual(x["intent"]["intent"], "APPROACH_INTERACT")

    def test_24_feedback_priority_keeps_damage_above_pickup(self):
        x = self.s.feedback.select_feedback(
            [{"feedback_class":"PICKUP"},{"feedback_class":"PLAYER_DAMAGE"}], combat_active=True, max_visible=1
        )
        self.assertEqual(x["visible"][0]["feedback_class"], "PLAYER_DAMAGE")

    def test_25_death_and_respawn_preserve_inventory(self):
        before = self.items.inventory_snapshot(self.pr)["stacks"].copy()
        self.e.character(self.wid).apply_health_change(self.pr, -10**9, event_ref="u16:death", source_type="TEST")
        self.assertEqual(self.e.character(self.wid).state(self.pr)["vitals"]["life_state"], "DEAD")
        out = self.e.save_recovery(self.wid).recover_death(self.pr, event_ref="u16:respawn")
        after = self.items.inventory_snapshot(self.pr)["stacks"].copy()
        self.assertEqual(out["status"], "PASS")
        self.assertEqual(before, after)
        self.assertEqual(out["waypoint_ref"], "WP-CANON-CIT-001")

    def test_26_active_uncollected_drop_survives_player_death(self):
        refs = {d["drop_ref"] for d in self.s.ground_loot.active_drops()}
        self.assertIn(self.persistent_active_drop, refs)

    def test_27_stage16a_verify_after_full_cycle(self):
        self.assertEqual(self.s.verify()["status"], "PASS")
        self.assertEqual(self.e.health_arpg_v16a(self.wid)["status"], "PASS")

    def test_28_no_stage16_presentation_pauses_world(self):
        self.assertFalse(self.s.dialogue.presentation_contract()["world_pause_required"])
        self.assertFalse(self.s.camera.contract()["world_pause"])
        self.assertFalse(self.s.feedback.contract()["global_hitstop"])


class Stage16AVerticalSlicePersistenceTests(unittest.TestCase):
    def test_29_save_restore_preserves_stage16a_preferences_and_ground_loot(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="s16a_persist_"))
        try:
            db = root / "world.sqlite"
            e = IntegratedARPGEngineV16A(str(db), master_release_path=MASTER, save_root=root / "saves")
            wid = e.create_world("stage16a:persist", 161651)["world"]["world_instance_id"]
            p = e.arpg(wid).create_profile("stage16a:persist", display_name="Persist Slice")["profile"]
            pr, avatar = p["profile_ref"], p["avatar_ref"]
            s = e.stage16a(wid)
            s.set_auto_pickup(pr, True, event_ref="persist:auto")
            pos = e.movement(wid).state(avatar)
            dr = s.ground_loot.spawn_drop(
                source_ref=avatar, source_kind="PLAYER_DROP", item_ref="ITEM-FRUIT", item_kind="FOOD", quantity=2,
                candidate_position=pos, event_ref="persist:drop",
            )["drop_ref"]
            s.confirm_drop_settled(dr, settled_position=pos, reachable=True, event_ref="persist:settle")
            snap = e.save_recovery(wid).create_snapshot("slot16", kind="MANUAL")
            self.assertEqual(snap["status"], "PASS")
            restored = root / "restored.sqlite"
            e.save_recovery(wid).restore_slot_to("slot16", restored)
            e.runtime.close()

            e2 = IntegratedARPGEngineV16A(str(restored), master_release_path=MASTER, save_root=root / "restored_saves")
            rr = e2.resume_world(wid)
            s2 = e2.stage16a(wid)
            self.assertEqual(rr["arpg_health"]["status"], "PASS")
            self.assertTrue(s2.ensure_profile_preferences(pr)["auto_pickup_enabled"])
            self.assertIn(dr, {x["drop_ref"] for x in s2.ground_loot.active_drops()})
            self.assertEqual(s2.verify()["status"], "PASS")
            e2.runtime.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
