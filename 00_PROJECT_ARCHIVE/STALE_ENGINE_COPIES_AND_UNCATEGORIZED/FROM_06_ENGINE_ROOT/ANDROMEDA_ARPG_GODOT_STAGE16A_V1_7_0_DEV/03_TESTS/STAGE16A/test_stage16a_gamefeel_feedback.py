from __future__ import annotations
import pathlib, sys, unittest
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "01_RUNTIME"))
from arpg_gamefeel_feedback_core import GameFeelFeedbackCore

class Stage16AGameFeelFeedbackTests(unittest.TestCase):
    def setUp(self): self.f=GameFeelFeedbackCore()
    def test_01_feedback_never_changes_gameplay_result(self): self.assertFalse(self.f.contract()['may_change_gameplay_result'])
    def test_02_no_global_hitstop(self): self.assertFalse(self.f.contract()['global_hitstop'])
    def test_03_move_click_is_small_temporary_marker(self):
        x=self.f.click_feedback('MOVE_TO_POINT'); self.assertEqual(x['world_marker'],'SMALL_GROUND_RING'); self.assertFalse(x['blocks_gameplay'])
    def test_04_blocked_action_has_reason(self):
        x=self.f.click_feedback('APPROACH_INTERACT',accepted=False,reason='BLOCKED_PATH'); self.assertEqual(x['feedback_class'],'BLOCKED_INTERACTION'); self.assertEqual(x['reason'],'BLOCKED_PATH')
    def test_05_pickup_feedback_uses_type_icon(self): self.assertEqual(self.f.pickup_feedback(item_type='MINERAL',quantity=3)['icon_policy'],'BY_ITEM_TYPE_NOT_ITEM_ID')
    def test_06_invalid_pickup_quantity_rejected(self):
        with self.assertRaises(ValueError): self.f.pickup_feedback(item_type='MINERAL',quantity=0)
    def test_07_normal_hit_has_local_only_freeze(self):
        x=self.f.hit_feedback(dealt_damage=True); self.assertGreater(x['local_freeze_ms'],0); self.assertTrue(x['local_animation_only']); self.assertFalse(x['global_world_pause'])
    def test_08_critical_hit_stronger_than_normal(self):
        a=self.f.hit_feedback(dealt_damage=True); b=self.f.hit_feedback(dealt_damage=True,critical=True); self.assertGreater(b['local_freeze_ms'],a['local_freeze_ms']); self.assertGreaterEqual(b['camera_impulse'],a['camera_impulse'])
    def test_09_reduced_motion_removes_camera_impulse_and_freeze(self):
        x=self.f.hit_feedback(dealt_damage=True,critical=True,reduced_motion=True); self.assertEqual(x['camera_impulse'],0); self.assertEqual(x['local_freeze_ms'],0)
    def test_10_no_damage_no_fake_hit_confirm(self): self.assertEqual(self.f.hit_feedback(dealt_damage=False)['feedback_class'],'NO_DAMAGE_CONFIRM')
    def test_11_damage_numbers_not_mandatory(self): self.assertFalse(self.f.hit_feedback(dealt_damage=True)['mandatory_damage_number'])
    def test_12_incoming_damage_reveals_vitals(self): self.assertTrue(self.f.incoming_damage_feedback()['hud_vitals_reveal'])
    def test_13_shield_absorb_has_distinct_semantic_audio(self): self.assertEqual(self.f.incoming_damage_feedback(shield_absorbed=True)['audio_cue'],'PLAYER_SHIELD_HIT')
    def test_14_priority_keeps_player_damage_over_pickup(self):
        x=self.f.select_feedback([{'feedback_class':'PICKUP'},{'feedback_class':'PLAYER_DAMAGE'}],combat_active=True,max_visible=1); self.assertEqual(x['visible'][0]['feedback_class'],'PLAYER_DAMAGE')
    def test_15_combat_deprioritizes_move_marker(self):
        x=self.f.select_feedback([{'feedback_class':'MOVE_CLICK'},{'feedback_class':'HIT_CONFIRM'}],combat_active=True,max_visible=1); self.assertEqual(x['visible'][0]['feedback_class'],'HIT_CONFIRM')
    def test_16_audio_is_semantic_not_final_asset(self):
        x=self.f.audio_policy(cue='ITEM_PICKUP'); self.assertTrue(x['semantic_only']); self.assertFalse(x['final_asset_required'])
    def test_17_duplicate_audio_debounced(self): self.assertTrue(self.f.audio_policy(cue='ITEM_PICKUP',duplicate_within_ms=10)['suppressed_duplicate'])
    def test_18_deterministic_signature(self): self.assertEqual(self.f.deterministic_signature(),GameFeelFeedbackCore().deterministic_signature())

if __name__=='__main__': unittest.main(verbosity=2)
