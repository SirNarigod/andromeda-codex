from __future__ import annotations
import pathlib, sys, unittest
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "01_RUNTIME"))
from arpg_realtime_dialogue_core import RealtimeDialogueCore, IMPORTANT_TEXT_HEX, NORMAL_TEXT_HEX

class Stage16ARealtimeDialogueTests(unittest.TestCase):
    def setUp(self): self.c = RealtimeDialogueCore()

    def test_01_realtime_no_next_button(self):
        x=self.c.presentation_contract(); self.assertEqual(x['mode'],'REAL_TIME_NO_NEXT_BUTTON'); self.assertFalse(x['player_movement_locked'])
    def test_02_style_white_rounded_grey(self):
        x=self.c.style_contract(); self.assertEqual(x['bubble_background_hex'],'#FFFFFF'); self.assertEqual(x['normal_text_hex'],NORMAL_TEXT_HEX); self.assertIn('ROUNDED',x['bubble_shape'])
    def test_03_important_is_soft_orange(self):
        x=self.c.style_contract(); self.assertEqual(x['important_text_hex'],IMPORTANT_TEXT_HEX); self.assertEqual(x['important_orange'],'SOFT_LIGHT_NOT_VIVID')
    def test_04_hover_name_only(self):
        self.assertFalse(self.c.hover_name(npc_ref='N1',display_name='NPC',hovered=False)['visible']); self.assertTrue(self.c.hover_name(npc_ref='N1',display_name='NPC',hovered=True)['visible'])
    def test_05_short_text_gets_minimum_reading_time(self):
        x=self.c.timing_for_text('Oi.'); self.assertGreaterEqual(x['seconds'],1.8); self.assertTrue(x['auto_advance']); self.assertFalse(x['requires_next_button'])
    def test_06_long_text_capped(self):
        x=self.c.timing_for_text('a'*1000); self.assertLessEqual(x['seconds'],8.0)
    def test_07_important_line_lasts_not_less(self):
        a=self.c.timing_for_text('Mensagem importante com tamanho moderado.',important=False); b=self.c.timing_for_text('Mensagem importante com tamanho moderado.',important=True); self.assertGreaterEqual(b['seconds'],a['seconds'])
    def test_08_distance_full_then_fade_then_hidden(self):
        self.assertEqual(self.c.distance_visibility(4)['state'],'FULL'); self.assertEqual(self.c.distance_visibility(10)['state'],'FADING'); self.assertEqual(self.c.distance_visibility(15)['state'],'HIDDEN')
    def test_09_direct_player_priority(self):
        lines=[{'line_ref':'A','speaker_ref':'N1','text':'ambient','presentation_class':'AMBIENT','distance_m':1},{'line_ref':'B','speaker_ref':'N2','text':'direct','directed_to_player':True,'distance_m':3}]
        x=self.c.select_visible_lines(lines,max_visible=1); self.assertEqual(x['visible'][0]['line_ref'],'B')
    def test_10_important_priority_over_ambient(self):
        lines=[{'line_ref':'A','speaker_ref':'N1','text':'ambient','presentation_class':'AMBIENT','distance_m':1},{'line_ref':'B','speaker_ref':'N2','text':'important','important':True,'distance_m':4}]
        x=self.c.select_visible_lines(lines,max_visible=1); self.assertEqual(x['visible'][0]['line_ref'],'B')
    def test_11_max_visible_bubbles_limits_clutter(self):
        lines=[{'line_ref':str(i),'speaker_ref':'N'+str(i),'text':'fala','distance_m':1} for i in range(8)]
        x=self.c.select_visible_lines(lines); self.assertEqual(x['visible_count'],3); self.assertGreater(x['suppressed_or_queued_count'],0)
    def test_12_same_conversation_alternates_one_turn_at_a_time(self):
        lines=[{'line_ref':'T2','speaker_ref':'B','text':'segunda','conversation_ref':'C','turn_index':2,'distance_m':1},{'line_ref':'T1','speaker_ref':'A','text':'primeira','conversation_ref':'C','turn_index':1,'distance_m':1}]
        x=self.c.select_visible_lines(lines); self.assertEqual(x['visible_count'],1); self.assertEqual(x['visible'][0]['line_ref'],'T1')
    def test_13_different_conversations_can_coexist(self):
        lines=[{'line_ref':'A','speaker_ref':'N1','text':'a','conversation_ref':'C1','turn_index':1,'distance_m':1},{'line_ref':'B','speaker_ref':'N2','text':'b','conversation_ref':'C2','turn_index':1,'distance_m':1}]
        x=self.c.select_visible_lines(lines); self.assertEqual(x['visible_count'],2)
    def test_14_important_world_bubble_also_bottom_line(self):
        line={'line_ref':'I','speaker_ref':'N1','text':'Cuidado.','important':True,'distance_m':1}; x=self.c.select_visible_lines([line])['visible'][0]; self.assertTrue(x['accessibility_bottom_line']); self.assertEqual(x['text_hex'],IMPORTANT_TEXT_HEX); self.assertTrue(self.c.important_accessibility_line(line)['visible'])
    def test_15_normal_line_has_no_bottom_duplicate(self):
        line={'line_ref':'N','speaker_ref':'N1','text':'Bom dia.','distance_m':1}; self.assertFalse(self.c.important_accessibility_line(line)['visible'])
    def test_16_choice_near_npc_is_small_not_modal(self):
        x=self.c.choice_overlay(npc_ref='N1',choices=['Aceitar','Recusar'],distance_m=1.5); self.assertTrue(x['visible']); self.assertFalse(x['large_modal']); self.assertFalse(x['next_button'])
    def test_17_choice_too_far_hides(self):
        x=self.c.choice_overlay(npc_ref='N1',choices=['Aceitar'],distance_m=3); self.assertFalse(x['visible']); self.assertEqual(x['reason'],'OUT_OF_CHOICE_RANGE')
    def test_18_deterministic_signature(self): self.assertEqual(self.c.deterministic_signature(),RealtimeDialogueCore().deterministic_signature())

if __name__=='__main__': unittest.main(verbosity=2)
