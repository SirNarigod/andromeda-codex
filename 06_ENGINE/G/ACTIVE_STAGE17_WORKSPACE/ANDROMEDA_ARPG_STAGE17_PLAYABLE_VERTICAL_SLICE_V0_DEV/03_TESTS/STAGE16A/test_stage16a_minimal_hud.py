from __future__ import annotations
import pathlib, sys, unittest
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "01_RUNTIME"))
from arpg_minimal_hud_core import MinimalHUDCore

class Stage16AMinimalHUDTests(unittest.TestCase):
    def setUp(self): self.h=MinimalHUDCore()
    def test_01_idle_hud_is_subtle(self):
        x=self.h.compose({}); self.assertEqual(x['visible']['PLAYER_VITALS']['mode'],'IDLE_SUBTLE'); self.assertLess(x['visible']['PLAYER_VITALS']['alpha'],0.5)
    def test_02_combat_reveals_vitals_and_protection_but_not_full_inactive_stamina(self):
        x=self.h.compose({'combat_active':True,'stamina_fraction':1.0,'stamina_active':False}); self.assertIn('PLAYER_VITALS',x['visible']); self.assertNotIn('STAMINA',x['visible']); self.assertIn('PROTECTION',x['visible'])
    def test_03_stamina_appears_when_traversal_uses_it(self): self.assertIn('STAMINA',self.h.compose({'stamina_active':True})['visible'])
    def test_04_no_permanent_large_panels(self): self.assertFalse(self.h.compose({})['permanent_large_panels'])
    def test_05_target_only_when_relevant(self):
        self.assertNotIn('TARGET_INFO',self.h.compose({})['visible']); self.assertIn('TARGET_INFO',self.h.compose({'target_relevant':True})['visible'])
    def test_06_boss_status_contextual(self): self.assertIn('BOSS_STATUS',self.h.compose({'boss_active':True})['visible'])
    def test_07_interaction_hint_temporary(self): self.assertEqual(self.h.compose({'interaction_hint':True})['visible']['INTERACTION_HINT']['mode'],'TEMPORARY')
    def test_08_loot_feedback_uses_item_type_icon(self):
        x=self.h.pickup_feedback(item_type='MINERAL',quantity=3,rarity='COMMON'); self.assertEqual(x['icon_policy'],'BY_ITEM_TYPE_NOT_ITEM_ID'); self.assertEqual(x['quantity'],3)
    def test_09_auto_pickup_status_is_not_permanent(self): self.assertFalse(self.h.auto_pickup_status(True)['persistent_large_indicator'])
    def test_10_important_dialogue_bottom_line_nonblocking(self):
        x=self.h.compose({'important_dialogue':True})['visible']['IMPORTANT_DIALOGUE_ACCESSIBILITY']; self.assertFalse(x['blocks_gameplay'])
    def test_11_npc_name_only_hover_channel(self):
        self.assertNotIn('NPC_HOVER_NAME',self.h.compose({})['visible']); self.assertIn('NPC_HOVER_NAME',self.h.compose({'npc_hover':True})['visible'])
    def test_12_choice_overlay_not_large_modal(self):
        x=self.h.compose({'choice_overlay':True})['visible']['CHOICE_OVERLAY']; self.assertFalse(x['large_modal']); self.assertFalse(x['blocks_world'])
    def test_13_enemy_bar_hidden_until_engaged(self): self.assertFalse(self.h.enemy_bar_policy(hostile=True,recently_engaged=False)['visible'])
    def test_14_enemy_bar_stable_above_head(self):
        x=self.h.enemy_bar_policy(hostile=True,recently_engaged=True); self.assertTrue(x['visible']); self.assertEqual(x['placement'],'FIXED_STRAIGHT_ABOVE_HEAD')
    def test_15_alpha_enemy_gets_shield_channel(self): self.assertTrue(self.h.enemy_bar_policy(hostile=True,recently_engaged=True,alpha_rank=True)['shield_channel'])
    def test_16_accessibility_not_color_only(self): self.assertTrue(self.h.accessibility_contract()['color_not_only_signal'])
    def test_17_contract_has_no_large_dialogue_modal(self): self.assertTrue(self.h.contract()['no_large_dialogue_modal'])
    def test_18_deterministic_signature(self): self.assertEqual(self.h.deterministic_signature(),MinimalHUDCore().deterministic_signature())

if __name__=='__main__': unittest.main(verbosity=2)
