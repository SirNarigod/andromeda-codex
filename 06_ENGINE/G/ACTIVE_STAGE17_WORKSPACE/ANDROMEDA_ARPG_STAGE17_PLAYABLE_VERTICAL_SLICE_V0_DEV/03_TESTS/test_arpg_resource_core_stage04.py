from __future__ import annotations
import os, sys, tempfile, unittest

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT,'01_RUNTIME'))
from integrated_arpg_engine_v04 import IntegratedARPGEngineV04
from living_runtime import ValidationError, ConflictError

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

class ResourceStage04Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.db=os.path.join(cls.tmp.name,'world.sqlite')
        cls.engine=IntegratedARPGEngineV04(cls.db, master_release_path=MASTER)
        out=cls.engine.create_world('stage04:test',40404)
        cls.wid=out['world']['world_instance_id']
        created=cls.engine.arpg(cls.wid).create_profile('local:test',origin_mode='CREATED',display_name='ResourceTester')
        cls.profile=created['profile']; cls.pref=cls.profile['profile_ref']; cls.avatar=cls.profile['avatar_ref']

    @classmethod
    def tearDownClass(cls):
        cls.engine.close(); cls.tmp.cleanup()

    def test_01_health(self):
        self.assertEqual(self.engine.health_arpg_v04(self.wid)['status'],'PASS')

    def test_02_adaptive_resource_snapshot(self):
        snap=self.engine.resources_arpg(self.wid).snapshot(self.pref)
        self.assertEqual(snap['resource_model'],'ADAPTIVE_BUILD_DERIVED')
        self.assertEqual(snap['resource_channels']['PRIMARY']['mode'],'UNSPECIALIZED')
        ch=self.engine.character(self.wid).state(self.pref)
        self.assertEqual(snap['resource_channels']['PRIMARY']['current'],ch['vitals']['resource'])
        self.assertEqual(snap['resource_channels']['PRIMARY']['maximum'],ch['derived']['max_resource'])

    def test_03_action_spend_cooldown_and_replay(self):
        r=self.engine.resources_arpg(self.wid)
        before=self.engine.character(self.wid).state(self.pref)['vitals']['resource']
        out=r.reserve_action(self.pref,action_ref='TEST_ACTION',resource_cost=20,cooldown_s=1.0,event_ref='u04:action1')
        self.assertEqual(out['status'],'PASS'); self.assertAlmostEqual(out['resource_spent'],20.0,places=6)
        after=self.engine.character(self.wid).state(self.pref)['vitals']['resource']
        self.assertAlmostEqual(before-after,20.0,places=6)
        replay=r.reserve_action(self.pref,action_ref='TEST_ACTION',resource_cost=20,cooldown_s=1.0,event_ref='u04:action1')
        self.assertTrue(replay['idempotent_replay'])
        self.assertEqual(self.engine.character(self.wid).state(self.pref)['vitals']['resource'],after)

    def test_04_cooldown_gate_and_tick(self):
        r=self.engine.resources_arpg(self.wid)
        blocked=r.reserve_action(self.pref,action_ref='TEST_ACTION',resource_cost=1,cooldown_s=1,event_ref='u04:action2')
        self.assertEqual(blocked['status'],'REJECTED'); self.assertEqual(blocked['reason'],'ACTION_COOLDOWN')
        r.tick_profile(self.pref,1.0)
        ok=r.reserve_action(self.pref,action_ref='TEST_ACTION',resource_cost=1,cooldown_s=0,event_ref='u04:action3')
        self.assertEqual(ok['status'],'PASS')

    def test_05_insufficient_resource(self):
        r=self.engine.resources_arpg(self.wid)
        cur=self.engine.character(self.wid).state(self.pref)['vitals']['resource']
        out=r.reserve_action(self.pref,action_ref='EXPENSIVE',resource_cost=cur+1,cooldown_s=0,event_ref='u04:expensive')
        self.assertEqual(out['status'],'REJECTED'); self.assertEqual(out['reason'],'INSUFFICIENT_RESOURCE')

    def test_06_health_consumable_and_shared_cooldown(self):
        r=self.engine.resources_arpg(self.wid)
        self.engine.character(self.wid).apply_health_change(self.pref,-100,event_ref='u04:damage',source_type='TEST')
        before=r.snapshot(self.pref)['consumables']['PLACEHOLDER_HEALTH_RESTORE']
        out=r.use_consumable(self.pref,'PLACEHOLDER_HEALTH_RESTORE',event_ref='u04:heal')
        self.assertEqual(out['status'],'PASS'); self.assertGreater(out['applied_health'],0)
        self.assertEqual(out['remaining_quantity'],before-1)
        blocked=r.use_consumable(self.pref,'PLACEHOLDER_RESOURCE_RESTORE',event_ref='u04:sharedcd')
        self.assertEqual(blocked['status'],'REJECTED'); self.assertEqual(blocked['reason'],'CONSUMABLE_COOLDOWN')

    def test_07_no_effect_does_not_consume(self):
        r=self.engine.resources_arpg(self.wid); r.tick_profile(self.pref,1.0)
        ch=self.engine.character(self.wid).state(self.pref)
        missing=float(ch['derived']['max_health'])-float(ch['vitals']['health'])
        if missing>1e-9:
            self.engine.character(self.wid).apply_health_change(self.pref,missing,event_ref='u04:topoff',source_type='TEST')
        before=r.snapshot(self.pref)['consumables']['PLACEHOLDER_HEALTH_RESTORE']
        out=r.use_consumable(self.pref,'PLACEHOLDER_HEALTH_RESTORE',event_ref='u04:noeffect')
        self.assertEqual(out['status'],'REJECTED'); self.assertEqual(out['reason'],'CONSUMABLE_NO_EFFECT')
        self.assertEqual(r.snapshot(self.pref)['consumables']['PLACEHOLDER_HEALTH_RESTORE'],before)

    def test_08_game_core_consumable_command_and_replay(self):
        r=self.engine.resources_arpg(self.wid); r.tick_profile(self.pref,1.0)
        self.engine.character(self.wid).apply_resource_change(self.pref,-40,event_ref='u04:draincmd',source_type='TEST')
        seq=self.engine.arpg(self.wid)._input(self.pref)['last_client_sequence']+1
        out=self.engine.arpg(self.wid).submit_command('local:test',self.pref,seq,'USE_CONSUMABLE',{'consumable_ref':'PLACEHOLDER_RESOURCE_RESTORE'})
        self.assertEqual(out['status'],'PASS'); self.assertEqual(out['route'],'CONSUMABLE')
        replay=self.engine.arpg(self.wid).submit_command('local:test',self.pref,seq,'USE_CONSUMABLE',{'consumable_ref':'PLACEHOLDER_RESOURCE_RESTORE'})
        self.assertTrue(replay['idempotent_replay'])

    def test_09_interruption_lock(self):
        r=self.engine.resources_arpg(self.wid); r.tick_profile(self.pref,1.0)
        out=r.apply_interruption(self.pref,duration_s=0.4,source_ref='TEST_ENEMY',event_ref='u04:interrupt')
        self.assertEqual(out['status'],'PASS')
        blocked=r.reserve_action(self.pref,action_ref='LOCK_TEST',resource_cost=0,cooldown_s=0,event_ref='u04:lockblocked')
        self.assertEqual(blocked['status'],'REJECTED'); self.assertEqual(blocked['reason'],'ACTION_INTERRUPTED')
        r.tick_profile(self.pref,0.5)
        ok=r.reserve_action(self.pref,action_ref='LOCK_TEST',resource_cost=0,cooldown_s=0,event_ref='u04:lockok')
        self.assertEqual(ok['status'],'PASS')

    def test_10_opt_in_global_cooldown(self):
        r=self.engine.resources_arpg(self.wid)
        first=r.reserve_action(self.pref,action_ref='GCD_A',resource_cost=0,cooldown_s=0,event_ref='u04:gcd1',global_cooldown_s=0.4)
        self.assertEqual(first['status'],'PASS')
        blocked=r.reserve_action(self.pref,action_ref='GCD_B',resource_cost=0,cooldown_s=0,event_ref='u04:gcd2')
        self.assertEqual(blocked['status'],'REJECTED'); self.assertEqual(blocked['reason'],'GLOBAL_COOLDOWN')
        r.tick_profile(self.pref,0.5)
        ok=r.reserve_action(self.pref,action_ref='GCD_B',resource_cost=0,cooldown_s=0,event_ref='u04:gcd3')
        self.assertEqual(ok['status'],'PASS')

    def test_11_dead_character_gate(self):
        created=self.engine.arpg(self.wid).create_profile('local:dead',origin_mode='CREATED',display_name='DeadTester')
        pref=created['profile']['profile_ref']
        self.engine.character(self.wid).ensure_profile(pref); self.engine.resources_arpg(self.wid).ensure_profile(pref)
        hp=self.engine.character(self.wid).state(pref)['vitals']['health']
        self.engine.character(self.wid).apply_health_change(pref,-hp,event_ref='u04:dead:kill',source_type='TEST')
        out=self.engine.resources_arpg(self.wid).use_consumable(pref,'PLACEHOLDER_HEALTH_RESTORE',event_ref='u04:dead:consume')
        self.assertEqual(out['status'],'REJECTED'); self.assertEqual(out['reason'],'CHARACTER_DEAD')

    def test_12_event_conflict(self):
        r=self.engine.resources_arpg(self.wid)
        r.grant_consumable(self.pref,'PLACEHOLDER_HEALTH_RESTORE',1,event_ref='u04:conflict')
        with self.assertRaises(ConflictError):
            r.grant_consumable(self.pref,'PLACEHOLDER_HEALTH_RESTORE',2,event_ref='u04:conflict')

    def test_13_snapshot_game_core(self):
        snap=self.engine.arpg(self.wid).client_snapshot(self.pref)
        self.assertIsNotNone(snap['resources'])
        self.assertEqual(snap['resources']['resource_model'],'ADAPTIVE_BUILD_DERIVED')
        self.assertEqual(snap['resources']['consumable_authority'],'PLACEHOLDER_ONLY_STAGE05_ITEMIZATION_PENDING')

    def test_14_invalid_consumable_command_rejected(self):
        seq=self.engine.arpg(self.wid)._input(self.pref)['last_client_sequence']+1
        out=self.engine.arpg(self.wid).submit_command('local:test',self.pref,seq,'USE_CONSUMABLE',{'consumable_ref':'NOT_A_REAL_CONSUMABLE'})
        self.assertEqual(out['status'],'REJECTED')
        self.assertIn('unknown Stage04 placeholder consumable',out['result']['reason'])

    def test_15_verify(self):
        self.assertEqual(self.engine.resources_arpg(self.wid).verify()['status'],'PASS')
        self.assertEqual(self.engine.health_arpg_v04(self.wid)['status'],'PASS')

class ResourceStage04PersistenceTests(unittest.TestCase):
    def test_16_persistence_resume(self):
        with tempfile.TemporaryDirectory() as td:
            db=os.path.join(td,'persist.sqlite')
            e=IntegratedARPGEngineV04(db, master_release_path=MASTER)
            out=e.create_world('stage04:persist',44044); wid=out['world']['world_instance_id']
            p=e.arpg(wid).create_profile('local:persist',origin_mode='CREATED',display_name='Persist')['profile']; pref=p['profile_ref']
            e.resources_arpg(wid).reserve_action(pref,action_ref='PERSIST_COOLDOWN',resource_cost=5,cooldown_s=9,event_ref='persist:action')
            before=e.resources_arpg(wid).snapshot(pref); e.close()
            e2=IntegratedARPGEngineV04(db, master_release_path=MASTER); e2.resume_world(wid)
            after=e2.resources_arpg(wid).snapshot(pref)
            self.assertEqual(after['cooldowns']['PERSIST_COOLDOWN'],before['cooldowns']['PERSIST_COOLDOWN'])
            self.assertEqual(after['resource_channels']['PRIMARY']['current'],before['resource_channels']['PRIMARY']['current'])
            self.assertEqual(e2.health_arpg_v04(wid)['status'],'PASS'); e2.close()

if __name__=='__main__': unittest.main(verbosity=2)
