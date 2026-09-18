from __future__ import annotations
import os, sys, tempfile, unittest, itertools

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT,'01_RUNTIME'))
from integrated_arpg_engine_v03 import IntegratedARPGEngineV03
from living_runtime import ValidationError, ConflictError

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

class CombatStage03Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.db=os.path.join(cls.tmp.name,'world.sqlite')
        cls.engine=IntegratedARPGEngineV03(cls.db, master_release_path=MASTER)
        out=cls.engine.create_world('stage03:test',30303)
        cls.wid=out['world']['world_instance_id']
        created=cls.engine.arpg(cls.wid).create_profile('local:test',origin_mode='CREATED',display_name='CombatTester')
        cls.profile=created['profile']; cls.pref=cls.profile['profile_ref']; cls.avatar=cls.profile['avatar_ref']
        cls.target=None; cls.protected=None
        for n in cls.engine.country(cls.wid)._all_npc_records():
            if n['id']==cls.avatar: continue
            if not (n.get('protection') or {}).get('protected') and cls.target is None: cls.target=n['id']
            if (n.get('protection') or {}).get('protected') and (n.get('protection') or {}).get('combat_targetable', True) and cls.protected is None: cls.protected=n['id']
            if cls.target and cls.protected: break
        assert cls.target and cls.protected
        pstate=cls.engine.movement(cls.wid).state(cls.avatar)
        geo=cls.engine.spatial(cls.wid).isometric_to_geodetic(pstate['iso_x_m'],pstate['iso_y_m'],pstate['altitude_m'])
        cls.engine.movement(cls.wid).sync_to_geodetic(cls.target,geo,reason='TEST_COLOCATE')
        cls.engine.movement(cls.wid).sync_to_geodetic(cls.protected,geo,reason='TEST_COLOCATE')

    @classmethod
    def tearDownClass(cls):
        cls.engine.close(); cls.tmp.cleanup()

    def test_01_health(self):
        self.assertEqual(self.engine.health_arpg_v03(self.wid)['status'],'PASS')

    def test_02_player_stats(self):
        s=self.engine.combat_arpg(self.wid).player_stats(self.pref)
        self.assertGreater(s['base_damage'],0); self.assertGreater(s['accuracy'],0); self.assertEqual(s['equipment_modifiers'],'DEFERRED_STAGE05')

    def test_03_enemy_overlay(self):
        e=self.engine.combat_arpg(self.wid).ensure_enemy(self.target)
        self.assertEqual(e['life_state'],'ALIVE'); self.assertGreater(e['max_health'],0); self.assertEqual(e['permanent_death'],'BLOCKED_STAGE03')

    def test_04_attack_and_replay(self):
        c=self.engine.combat_arpg(self.wid)
        before=c.ensure_enemy(self.target)['health']
        out=c.player_attack(self.pref,self.target,event_ref='u03:attack1')
        self.assertEqual(out['status'],'PASS')
        after=c.ensure_enemy(self.target)['health']
        self.assertLessEqual(after,before)
        replay=c.player_attack(self.pref,self.target,event_ref='u03:attack1')
        self.assertTrue(replay['idempotent_replay']); self.assertEqual(c.ensure_enemy(self.target)['health'],after)

    def test_05_cooldown(self):
        out=self.engine.combat_arpg(self.wid).player_attack(self.pref,self.target,event_ref='u03:cooldown')
        self.assertEqual(out['status'],'REJECTED'); self.assertEqual(out['reason'],'ATTACK_COOLDOWN')
        self.engine.combat_arpg(self.wid).tick_player(self.pref,1.0)
        self.assertEqual(self.engine.combat_arpg(self.wid).overlay(self.avatar)['attack_cooldown_remaining_s'],0.0)

    def test_06_out_of_range(self):
        c=self.engine.combat_arpg(self.wid)
        p=self.engine.movement(self.wid).state(self.avatar)
        far=self.engine.spatial(self.wid).isometric_to_geodetic(p['iso_x_m']+100,p['iso_y_m'],p['altitude_m'])
        self.engine.movement(self.wid).sync_to_geodetic(self.target,far,reason='TEST_FAR')
        out=c.player_attack(self.pref,self.target,event_ref='u03:far')
        self.assertEqual(out['status'],'REJECTED'); self.assertEqual(out['reason'],'TARGET_OUT_OF_RANGE')
        geo=self.engine.spatial(self.wid).isometric_to_geodetic(p['iso_x_m'],p['iso_y_m'],p['altitude_m'])
        self.engine.movement(self.wid).sync_to_geodetic(self.target,geo,reason='TEST_NEAR')

    def test_07_protected_identity_nonlethal(self):
        c=self.engine.combat_arpg(self.wid)
        st=c.ensure_enemy(self.protected); st['health']=0.05; c._save_row('arpg_enemy_combat_state',self.protected,st)
        c.tick_player(self.pref,1.0)
        # Search deterministic event refs until one hits; protected target must remain alive at >=1 hp.
        got=None
        for i in range(20):
            out=c.player_attack(self.pref,self.protected,event_ref=f'u03:protected:{i}')
            if out['status']=='PASS' and out['hit']:
                got=out; break
            c.tick_player(self.pref,1.0)
        self.assertIsNotNone(got)
        self.assertTrue(got['protected_defeat_blocked']); self.assertFalse(got['lethal'])
        self.assertEqual(c.ensure_enemy(self.protected)['life_state'],'ALIVE'); self.assertEqual(c.ensure_enemy(self.protected)['health'],1.0)

    def test_08_enemy_attack_character_authority(self):
        c=self.engine.combat_arpg(self.wid); c.tick_actor(self.target,1.0)
        before=self.engine.character(self.wid).state(self.pref)['vitals']['health']
        got=None
        for i in range(20):
            out=c.enemy_attack_player(self.target,self.pref,event_ref=f'u03:enemy:{i}')
            if out['status']=='PASS' and out['hit']:
                got=out; break
        self.assertIsNotNone(got)
        after=self.engine.character(self.wid).state(self.pref)['vitals']['health']
        self.assertLess(after,before)

    def test_09_status_dot(self):
        c=self.engine.combat_arpg(self.wid)
        st=c.ensure_enemy(self.target)
        if st['life_state']!='ALIVE':
            st['life_state']='ALIVE'; st['health']=st['max_health']; c._save_row('arpg_enemy_combat_state',self.target,st)
        ap=c.apply_status(self.target,status_ref='TEST_DOT',duration_s=1.0,magnitude_per_s=3.0,damage_type='TOXIC',source_ref=self.avatar,event_ref='u03:status')
        self.assertEqual(ap['status'],'PASS')
        before=c.ensure_enemy(self.target)['health']; tick=c.tick_actor(self.target,0.5); after=c.ensure_enemy(self.target)['health']
        self.assertAlmostEqual(before-after,1.5,places=5); self.assertEqual(len(tick['statuses']),1)
        tick2=c.tick_actor(self.target,0.5); self.assertEqual(len(tick2['statuses']),0)

    def test_10_game_core_route(self):
        c=self.engine.combat_arpg(self.wid); c.tick_player(self.pref,1.0)
        seq=self.engine.arpg(self.wid)._input(self.pref)['last_client_sequence']+1
        out=self.engine.arpg(self.wid).submit_command('local:test',self.pref,seq,'POINTER_PRIMARY',{'target_ref':self.target,'combat_intent':True})
        self.assertEqual(out['route'],'COMBAT'); self.assertEqual(out['resolved_action'],'BASIC_ATTACK')
        replay=self.engine.arpg(self.wid).submit_command('local:test',self.pref,seq,'POINTER_PRIMARY',{'target_ref':self.target,'combat_intent':True})
        self.assertTrue(replay['idempotent_replay'])

    def test_11_snapshot(self):
        snap=self.engine.arpg(self.wid).client_snapshot(self.pref)
        self.assertIsNotNone(snap['combat']); self.assertEqual(snap['combat']['formula_version'],'ARPG_COMBAT_FORMULAS_V0_4_0')

    def test_12_invalid_damage_type(self):
        with self.assertRaises(ValidationError):
            self.engine.combat_arpg(self.wid).player_attack(self.pref,self.target,event_ref='u03:badtype',damage_type='VOID_UNKNOWN')

    def test_13_event_conflict(self):
        c=self.engine.combat_arpg(self.wid); c.tick_player(self.pref,1.0)
        c.player_attack(self.pref,self.target,event_ref='u03:conflict',damage_type='PHYSICAL')
        with self.assertRaises(ConflictError):
            c.player_attack(self.pref,self.target,event_ref='u03:conflict',damage_type='FIRE')

    def test_14_verify(self):
        self.assertEqual(self.engine.combat_arpg(self.wid).verify()['status'],'PASS')

if __name__=='__main__': unittest.main(verbosity=2)
