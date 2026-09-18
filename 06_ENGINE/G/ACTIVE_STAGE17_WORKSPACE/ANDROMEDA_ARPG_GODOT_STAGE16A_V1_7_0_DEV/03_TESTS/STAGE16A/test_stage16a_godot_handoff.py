from __future__ import annotations
import json, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
MANIFEST=ROOT/'02_CONTRACTS/ARPG_STAGE16A/ARPG_GODOT_HANDOFF_MANIFEST_V0_8_0.json'
ACCEPT=ROOT/'02_CONTRACTS/ARPG_STAGE16A/ARPG_STAGE16B_GODOT_ACCEPTANCE_MATRIX_V0_8_0.json'
CONTRACT=ROOT/'10_ARPG/STAGE16A/ARPG_STAGE16A_PRE_GODOT_CONTRACT_V0_8_0.json'
START=ROOT/'10_ARPG/STAGE16A/CODEX_GODOT_HANDOFF_START_HERE_V0_8_0.md'

class HandoffManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m=json.loads(MANIFEST.read_text(encoding='utf-8')); cls.a=json.loads(ACCEPT.read_text(encoding='utf-8')); cls.c=json.loads(CONTRACT.read_text(encoding='utf-8')); cls.md=START.read_text(encoding='utf-8')
    def test_01_files(self): self.assertTrue(MANIFEST.is_file() and ACCEPT.is_file() and CONTRACT.is_file() and START.is_file())
    def test_02_authority(self): self.assertIn('READ_ONLY',self.m['authority']['master']); self.assertFalse(self.m['authority']['canon_mutation']); self.assertIn('DO_NOT_REIMPLEMENT',self.m['authority']['server_rule'])
    def test_03_target_folder(self): self.assertEqual(self.m['target_folder'],'07_GODOT_ARPG_STAGE16B'); self.assertIn('READ_ONLY',self.m['legacy_godot_folder'])
    def test_04_scenes(self):
        required={'Main.tscn','Player.tscn','NPC.tscn','Enemy.tscn','GroundLoot.tscn','ResourceNode.tscn','RegionCell.tscn','IsometricCameraRig.tscn','HUD.tscn','DialogueBubble.tscn','StaminaWorldRing.tscn','Inventory.tscn','WaterVolume.tscn','DroppedBag.tscn'}
        self.assertEqual(required,set(self.m['scene_tree']))
    def test_05_autoloads(self): self.assertEqual({'AndromedaBridge','InputRouter','SceneStream','PresentationBus','ClientSession'},{x['name'] for x in self.m['autoloads']})
    def test_06_inputs(self):
        acts={x['action'] for x in self.m['input_map']}; self.assertTrue({'pointer_left','pointer_right','attack_selected','interact_selected','inventory_toggle','camera_zoom_in','camera_zoom_out','weapon_slot_1','weapon_slot_2','weapon_cycle_wheel','camera_zoom_modifier'}.issubset(acts))
    def test_07_mouse_contracts(self):
        d={x['action']:x['behavior'] for x in self.m['input_map']}; self.assertIn('GroundLoot',d['pointer_left']); self.assertIn('Click only',d['pointer_right'])
    def test_08_collision_layers_unique(self):
        layers=[x['layer'] for x in self.m['collision_layers_candidate']]; self.assertEqual(len(layers),len(set(layers))); self.assertTrue(all(1<=x<=32 for x in layers))
    def test_09_navigation_candidates(self):
        t=self.m['navigation']['terrain_candidates']; self.assertEqual(32.0,t['max_walkable_slope_deg']); self.assertEqual(0.35,t['max_step_height_m']); self.assertEqual(0.12,t['micro_relief_collision_filter_m'])
    def test_10_streaming(self):
        s=self.m['terrain_and_streaming']; self.assertFalse(s['body_balance_mechanic']); self.assertEqual(4096.0,s['living_macro_chunk_m']); self.assertEqual({'ACTIVE','PRELOAD','SYSTEMIC'},set(s['phases']))
    def test_11_camera(self):
        c=self.m['camera_candidates']; self.assertEqual(45.0,c['yaw_deg']); self.assertEqual(55.0,c['pitch_deg']); self.assertFalse(c['free_orbit']); self.assertLess(c['min_distance_m'],c['distance_m']); self.assertLess(c['distance_m'],c['max_distance_m'])
    def test_12_dialogue(self):
        d=self.m['dialogue_ui']; self.assertFalse(d['world_pause']); self.assertFalse(d['next_button']); self.assertEqual('#FFFFFF',d['bubble_bg']); self.assertEqual('#6B6B6B',d['normal_text']); self.assertEqual('#D9A15F',d['important_text']); self.assertEqual('hover only',d['npc_name'])
    def test_13_hud(self):
        h=self.m['hud']; self.assertIn('MINIMAL',h['philosophy']); self.assertIn('white rounded',h['inventory'].lower()); self.assertIn('ON/OFF',h['auto_pickup_control'])
    def test_14_loot(self):
        g=self.m['ground_loot']; self.assertEqual(0.5,g['pickup_radius_m']); self.assertIn('TREE',g['physical_sources']); self.assertIn('ORE',g['physical_sources']); self.assertIn('FISHING',g['physical_sources']); self.assertIn('category/type',g['icon_policy'])
    def test_15_bridge_security(self):
        b=self.m['bridge_contract']; self.assertIn('DO_NOT_INVENT_ENDPOINTS',b['transport']); self.assertIn('damage',b['security']); self.assertGreaterEqual(len(b['required_capabilities']),15)
    def test_16_implementation_order(self): self.assertEqual(11,len(self.m['implementation_order'])); self.assertTrue(self.m['implementation_order'][0].startswith('B01')); self.assertTrue(self.m['implementation_order'][-1].startswith('B11'))
    def test_17_acceptance_matrix(self):
        self.assertEqual(28,len(self.m['acceptance_gates'])); self.assertEqual(28,len(self.a['gates'])); self.assertEqual([f'G16B-{i:02d}' for i in range(1,29)],[x['id'] for x in self.a['gates']])
    def test_18_no_backup(self): self.assertIn('NO_STAGE16_FINAL_BACKUP',self.a['backup_rule']); self.assertFalse(self.c['backup_authorized']); self.assertFalse(self.c['stage16_complete'])
    def test_19_accumulated_counts(self): self.assertEqual(180,self.c['accumulated_pre_godot_tests']); self.assertEqual(29,self.c['handoff_validator_checks']); self.assertEqual(209,self.c['accumulated_tests_total']); self.assertEqual(20,self.c['stress_checks']); self.assertEqual(0,self.c['canon_mutations'])
    def test_20_start_here(self):
        for token in ['Stage 16 só pode ser fechada','0,5 m','Ground Loot','sem botão Próximo','07_GODOT_ARPG_STAGE16B','G16B-01..28']:
            self.assertIn(token,self.md)
    def test_21_stamina_world_ring(self):
        s=self.m['stamina_world_ring']; self.assertEqual('CIRCLE_RADIAL',s['shape']); self.assertEqual('SOFT_YELLOW',s['color']); self.assertTrue(s['hide_when_full_and_inactive']); self.assertIn('PLAYER_ADJACENT',s['placement'])
    def test_22_two_weapon_authority(self):
        w=self.m['weapon_loadout']; self.assertEqual(2,w['max_quick_slots']); self.assertEqual(1,w['simultaneously_active_weapons']); self.assertEqual([1,2],w['slots']); self.assertIn('MAIN_HAND',w['backend_authority'])
    def test_23_contextual_wheel(self):
        w=self.m['weapon_loadout']; self.assertIn('MOUSE_WHEEL_WITHOUT_ZOOM_MODIFIER',w['switch_inputs']); self.assertIn('ZOOM_MODIFIER',w['zoom_input']); self.assertIn('UI_SCROLL_ONLY',w['menu_wheel'])
    def test_24_unified_ui_language(self):
        u=self.m['ui_theme']; self.assertEqual('#FFFFFF',u['panel_background']); self.assertEqual('#6B6B6B',u['primary_text']); self.assertEqual('#D9A15F',u['important_text']); self.assertIn('ROUNDED_SANS',u['font_direction']); self.assertIn('inventory',u['applies_to'])
    def test_25_water_traversal_contract(self):
        w=self.m['water_traversal']; self.assertEqual(0.65,w['shallow_depth_m_candidate']); self.assertFalse(w['body_balance_mechanic']); self.assertIn('PLAYER',w['living_actors']); self.assertIn('STAMINA',w['strong_current']); self.assertIn('BLOCKED',w['vehicle_deep'])
    def test_26_bag_inventory_death_contract(self):
        b=self.m['bag_inventory_death']; self.assertTrue(b['bag_is_real_container']); self.assertEqual(8,b['base_slots_without_bag_candidate']); self.assertEqual(30,b['bag_slots_candidate']); self.assertTrue(b['equipped_armor_clothes_retained']); self.assertIn('PROTECTED',b['quest_critical_unique_protection'])
    def test_27_water_ttl_contract(self):
        b=self.m['bag_inventory_death']; self.assertIn('30',b['bag_death_water']); self.assertIn('15',b['individual_water_loot']); self.assertIn('NO_EXPIRY',b['bag_death_land'])
    def test_28_npc_bag_ownership(self):
        b=self.m['bag_inventory_death']; self.assertTrue(b['npc_same_bag_rules']); self.assertTrue(b['player_can_recover_npc_bag']); self.assertFalse(b['npc_auto_theft'])
    def test_29_bridge_and_acceptance_cover_water_bag(self):
        caps=' | '.join(self.m['bridge_contract']['required_capabilities']); self.assertIn('water traversal',caps); self.assertIn('bag death-drop',caps); self.assertIn('water Ground Loot exposure',caps); self.assertEqual('G16B-28',self.a['gates'][-1]['id'])

if __name__=='__main__': unittest.main(verbosity=2)
