import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "01_RUNTIME"))

from arpg_interaction_intent_core import InteractionIntentResolver


class Stage16AInteractionIntentTests(unittest.TestCase):
    def setUp(self):
        self.r = InteractionIntentResolver()

    def test_left_ground_moves(self):
        out = self.r.resolve_click("LEFT", [], ground_point={"iso_x_m": 4, "iso_y_m": 7})
        self.assertEqual(out["intent"], "MOVE_TO_POINT")

    def test_left_enemy_selects_without_moving(self):
        out = self.r.resolve_click("LEFT", [{"ref":"EN-1","kind":"ACTOR","hostile":True}])
        self.assertEqual(out["intent"], "SELECT_TARGET")
        self.assertEqual(out["movement_change"], "NONE")

    def test_right_enemy_chase_attacks(self):
        out = self.r.resolve_click("RIGHT", [{"ref":"EN-1","kind":"ACTOR","hostile":True}])
        self.assertEqual(out["intent"], "CHASE_ATTACK")

    def test_right_npc_context(self):
        out = self.r.resolve_click("RIGHT", [{"ref":"NPC-1","kind":"NPC"}])
        self.assertEqual(out["intent"], "APPROACH_INTERACT")
        self.assertEqual(out["cursor"], "TALK")

    def test_left_loot_far_approaches(self):
        out = self.r.resolve_click("LEFT", [{"ref":"DROP-1","kind":"GROUND_LOOT","physical_distance_m":2.0}])
        self.assertEqual(out["intent"], "APPROACH_PICKUP")
        self.assertEqual(out["arrival_distance_m"], 0.5)

    def test_left_loot_near_picks_up(self):
        out = self.r.resolve_click("LEFT", [{"ref":"DROP-1","kind":"GROUND_LOOT","physical_distance_m":0.5}])
        self.assertEqual(out["intent"], "PICKUP")

    def test_loot_beyond_half_meter_never_direct_pickup(self):
        out = self.r.resolve_click("RIGHT", [{"ref":"DROP-1","kind":"GROUND_LOOT","physical_distance_m":0.5001}])
        self.assertEqual(out["intent"], "APPROACH_PICKUP")

    def test_unreachable_loot_rejected(self):
        out = self.r.resolve_click("LEFT", [{"ref":"DROP-1","kind":"GROUND_LOOT","physical_distance_m":0.2,"reachable":False}])
        self.assertEqual(out["status"], "REJECTED")
        self.assertEqual(out["reason"], "GROUND_LOOT_UNREACHABLE")

    def test_right_gather_harvests(self):
        out = self.r.resolve_click("RIGHT", [{"ref":"TREE-1","kind":"GATHER_NODE"}])
        self.assertEqual(out["intent"], "APPROACH_HARVEST")

    def test_overlap_prefers_closest_pointer_hit_not_blind_semantics(self):
        candidates = [
            {"ref":"DROP-1","kind":"GROUND_LOOT","screen_distance_px":3.0,"depth_m":4.0,"physical_distance_m":0.4},
            {"ref":"EN-1","kind":"ACTOR","hostile":True,"screen_distance_px":0.0,"depth_m":3.0},
        ]
        out = self.r.resolve_click("RIGHT", candidates)
        self.assertEqual(out["target_ref"], "EN-1")
        self.assertEqual(out["intent"], "CHASE_ATTACK")

    def test_equal_pointer_hits_use_frontmost_depth(self):
        candidates = [
            {"ref":"DROP-1","kind":"GROUND_LOOT","screen_distance_px":0.0,"depth_m":5.0,"physical_distance_m":0.4},
            {"ref":"NPC-1","kind":"NPC","screen_distance_px":0.0,"depth_m":2.0},
        ]
        out = self.r.resolve_click("LEFT", candidates)
        self.assertEqual(out["target_ref"], "NPC-1")

    def test_auto_pickup_only_half_meter_reachable_and_non_interrupting(self):
        candidates = [
            {"ref":"A","kind":"GROUND_LOOT","physical_distance_m":0.2,"reachable":True},
            {"ref":"B","kind":"GROUND_LOOT","physical_distance_m":0.5,"reachable":True},
            {"ref":"C","kind":"GROUND_LOOT","physical_distance_m":0.51,"reachable":True},
            {"ref":"D","kind":"GROUND_LOOT","physical_distance_m":0.1,"reachable":False},
        ]
        out = self.r.resolve_auto_pickup(candidates, enabled=True)
        self.assertEqual(out["pickup_refs"], ["A", "B"])
        self.assertFalse(out["interrupts_action"])

    def test_auto_pickup_off(self):
        out = self.r.resolve_auto_pickup([{"ref":"A","kind":"GROUND_LOOT","physical_distance_m":0.1}], enabled=False)
        self.assertEqual(out["pickup_refs"], [])

    def test_hover_communicates_action_before_click(self):
        out = self.r.hover_preview([{"ref":"ORE-1","kind":"GATHER_NODE"}])
        self.assertEqual(out["cursor"], "HARVEST")


if __name__ == "__main__":
    unittest.main(verbosity=2)
