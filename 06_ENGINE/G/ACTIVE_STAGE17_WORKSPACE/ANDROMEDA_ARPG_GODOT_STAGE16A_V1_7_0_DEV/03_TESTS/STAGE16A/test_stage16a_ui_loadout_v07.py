from __future__ import annotations
import os, pathlib, tempfile, unittest
ROOT = pathlib.Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT/'01_RUNTIME'))
from integrated_arpg_engine_v16a import IntegratedARPGEngineV16A
from arpg_minimal_hud_core import MinimalHUDCore
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

class Stage16AUIWeaponLoadoutV07Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); td=pathlib.Path(cls.tmp.name)
        cls.db=td/'world.sqlite'; cls.save=td/'saves'
        cls.e=IntegratedARPGEngineV16A(str(cls.db),master_release_path=MASTER,save_root=cls.save)
        out=cls.e.create_world('stage16a:v07',160700)
        cls.wid=out['world']['world_instance_id']
        p=cls.e.arpg(cls.wid).create_profile('stage16a:v07',display_name='UI Loadout Tester')['profile']
        cls.pr=p['profile_ref']; cls.s=cls.e.stage16a(cls.wid); cls.items=cls.e.items_arpg(cls.wid)
        weapons=[d for d in cls.items.list_definitions() if d.get('item_kind')=='WEAPON']
        assert len(weapons)>=3
        cls.refs=[]
        for i,d in enumerate(weapons[:3],1):
            g=cls.items.grant_item(cls.pr,d['item_ref'],1,event_ref=f'v07:grant:{i}')
            cls.refs.append(g['instance_refs'][0])
    @classmethod
    def tearDownClass(cls):
        cls.e.runtime.close(); cls.tmp.cleanup()

    def test_01_hud_unified_white_rounded_language(self):
        c=MinimalHUDCore().ui_language_contract()
        self.assertEqual('#FFFFFF',c['panel_background']); self.assertEqual('ROUNDED',c['panel_shape'])
        self.assertIn('ROUNDED_SANS',c['font_direction']); self.assertIn('WHITE_ROUNDED',c['inventory'])

    def test_02_stamina_full_inactive_hidden(self):
        x=MinimalHUDCore().compose({'stamina_fraction':1.0,'stamina_active':False})
        self.assertNotIn('STAMINA',x['visible'])

    def test_03_stamina_partial_is_yellow_radial_player_adjacent(self):
        x=MinimalHUDCore().compose({'stamina_fraction':0.65,'stamina_active':False})['visible']['STAMINA']
        self.assertEqual('CIRCLE',x['shape']); self.assertEqual('SOFT_YELLOW',x['color'])
        self.assertEqual('PLAYER_ADJACENT_SCREEN_SPACE',x['screen_alignment']); self.assertAlmostEqual(.65,x['fraction'])

    def test_04_loadout_has_exactly_two_quickslots_and_one_active_weapon(self):
        l=self.s.ensure_weapon_loadout(self.pr)
        self.assertEqual({'1','2'},set(l['slots'])); self.assertEqual(2,l['max_quick_slots']); self.assertEqual(1,l['simultaneously_active_weapons'])

    def test_05_assign_two_weapons(self):
        a=self.s.assign_weapon_slot(self.pr,1,self.refs[0],event_ref='v07:slot:1')
        b=self.s.assign_weapon_slot(self.pr,2,self.refs[1],event_ref='v07:slot:2')
        self.assertEqual('PASS',a['status']); self.assertEqual('PASS',b['status'])
        self.assertEqual(self.refs[0],b['loadout']['slots']['1']); self.assertEqual(self.refs[1],b['loadout']['slots']['2'])

    def test_06_same_weapon_cannot_fill_both_slots(self):
        x=self.s.assign_weapon_slot(self.pr,2,self.refs[0],event_ref='v07:slot:duplicate')
        self.assertEqual('REJECTED',x['status']); self.assertEqual('WEAPON_ALREADY_ASSIGNED_TO_OTHER_QUICKSLOT',x['reason'])

    def test_07_activate_slot1_equips_only_slot1_main_hand(self):
        x=self.s.activate_weapon_slot(self.pr,1,event_ref='v07:activate:1')
        self.assertEqual('PASS',x['status']); self.assertEqual(1,x['loadout']['active_slot'])
        inv=self.items.inventory_snapshot(self.pr)
        self.assertEqual(self.refs[0],inv['equipped']['MAIN_HAND'])
        applied=[r for r in self.items.equipment_modifiers(self.pr)['equipped'] if r.get('slot')=='MAIN_HAND' and r.get('applied')]
        self.assertEqual(1,len(applied)); self.assertEqual(self.refs[0],applied[0]['instance_ref'])

    def test_08_activate_slot2_replaces_main_hand_not_stacks_weapons(self):
        x=self.s.activate_weapon_slot(self.pr,2,event_ref='v07:activate:2')
        self.assertEqual('PASS',x['status']); self.assertEqual(2,x['loadout']['active_slot'])
        self.assertEqual(self.refs[1],self.items.inventory_snapshot(self.pr)['equipped']['MAIN_HAND'])
        applied=[r for r in self.items.equipment_modifiers(self.pr)['equipped'] if r.get('slot')=='MAIN_HAND' and r.get('applied')]
        self.assertEqual(1,len(applied)); self.assertEqual(self.refs[1],applied[0]['instance_ref'])

    def test_09_wheel_cycle_toggles_between_two_slots(self):
        x=self.s.cycle_weapon_slot(self.pr,1,event_ref='v07:wheel:1')
        self.assertEqual('PASS',x['status']); self.assertEqual(1,x['target_slot'])
        y=self.s.cycle_weapon_slot(self.pr,-1,event_ref='v07:wheel:2')
        self.assertEqual('PASS',y['status']); self.assertEqual(2,y['target_slot'])

    def test_10_replay_does_not_switch_twice(self):
        a=self.s.cycle_weapon_slot(self.pr,1,event_ref='v07:wheel:replay')
        active=self.s.ensure_weapon_loadout(self.pr)['active_slot']
        b=self.s.cycle_weapon_slot(self.pr,1,event_ref='v07:wheel:replay')
        self.assertTrue(b['idempotent_replay']); self.assertEqual(active,self.s.ensure_weapon_loadout(self.pr)['active_slot']); self.assertEqual(a['target_slot'],b['target_slot'])

    def test_11_third_weapon_can_replace_a_quickslot_but_never_creates_slot3(self):
        x=self.s.assign_weapon_slot(self.pr,2,self.refs[2],event_ref='v07:slot:replace2')
        self.assertEqual('PASS',x['status']); self.assertEqual({'1','2'},set(x['loadout']['slots'])); self.assertEqual(self.refs[2],x['loadout']['slots']['2'])
        with self.assertRaises(ValueError): self.s.assign_weapon_slot(self.pr,3,self.refs[1],event_ref='v07:slot:3')

    def test_12_health_and_contract(self):
        h=self.e.health_arpg_v16a(self.wid); self.assertEqual('PASS',h['status'])
        c=self.s.contract(); self.assertEqual(2,c['weapon_loadout']['max_quick_slots']); self.assertEqual(1,c['weapon_loadout']['simultaneously_active_weapons'])
        self.assertEqual('ZOOM_MODIFIER_HELD_PLUS_MOUSE_WHEEL',c['weapon_loadout']['zoom_input'])
        self.assertTrue(c['stamina_hud']['hide_when_full_and_inactive'])

class Stage16AWeaponLoadoutPersistenceV07Tests(unittest.TestCase):
    def test_13_loadout_persists_across_resume(self):
        with tempfile.TemporaryDirectory() as td_raw:
            td=pathlib.Path(td_raw); db=td/'persist.sqlite'; save=td/'saves'
            e=IntegratedARPGEngineV16A(str(db),master_release_path=MASTER,save_root=save)
            out=e.create_world('stage16a:v07:persist',160713); wid=out['world']['world_instance_id']
            pr=e.arpg(wid).create_profile('stage16a:v07:persist',display_name='Persist Loadout')['profile']['profile_ref']
            items=e.items_arpg(wid); s16=e.stage16a(wid)
            weapons=[d for d in items.list_definitions() if d.get('item_kind')=='WEAPON'][:2]
            refs=[]
            for i,d in enumerate(weapons,1): refs.append(items.grant_item(pr,d['item_ref'],1,event_ref=f'v07:persist:grant:{i}')['instance_refs'][0])
            s16.assign_weapon_slot(pr,1,refs[0],event_ref='v07:persist:slot1'); s16.assign_weapon_slot(pr,2,refs[1],event_ref='v07:persist:slot2'); s16.activate_weapon_slot(pr,2,event_ref='v07:persist:activate2')
            before=s16.ensure_weapon_loadout(pr); e.runtime.close()
            e2=IntegratedARPGEngineV16A(str(db),master_release_path=MASTER,save_root=save); e2.resume_world(wid)
            after=e2.stage16a(wid).ensure_weapon_loadout(pr)
            self.assertEqual(before,after); self.assertEqual(2,after['active_slot']); self.assertEqual(refs[1],e2.items_arpg(wid).inventory_snapshot(pr)['equipped']['MAIN_HAND']); self.assertEqual('PASS',e2.health_arpg_v16a(wid)['status'])
            e2.runtime.close()

if __name__=='__main__': unittest.main(verbosity=2)
