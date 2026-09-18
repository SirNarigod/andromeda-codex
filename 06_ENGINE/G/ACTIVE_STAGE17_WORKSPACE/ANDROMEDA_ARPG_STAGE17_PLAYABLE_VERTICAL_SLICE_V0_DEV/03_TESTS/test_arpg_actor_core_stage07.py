from __future__ import annotations
import os, sys, tempfile, unittest

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT,'01_RUNTIME'))
from integrated_arpg_engine_v07 import IntegratedARPGEngineV07
from living_runtime import ConflictError

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')


class ActorStage07Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); cls.db=os.path.join(cls.tmp.name,'world.sqlite')
        cls.engine=IntegratedARPGEngineV07(cls.db,master_release_path=MASTER)
        cls.wid=cls.engine.create_world('stage07:test',70707)['world']['world_instance_id']
        cls.p=cls.engine.arpg(cls.wid).create_profile('local:test',origin_mode='CREATED',display_name='ActorTester')['profile']
        cls.pref=cls.p['profile_ref']; cls.avatar=cls.p['avatar_ref']; cls.ac=cls.engine.actors_arpg(cls.wid)
        npcs=[n for n in cls.engine.country(cls.wid)._all_npc_records() if n['id']!=cls.avatar]
        cls.hostile_npc=next(n for n in npcs if not (n.get('protection') or {}).get('protected'))
        cls.neutral_npc=next(n for n in npcs if n['id']!=cls.hostile_npc['id'] and not (n.get('protection') or {}).get('protected'))
        cls.child=next(n for n in npcs if n.get('class')=='CHILD')
        cls.worker=next(n for n in npcs if n.get('class')=='WORKER')

    @classmethod
    def tearDownClass(cls):
        cls.engine.close(); cls.tmp.cleanup()

    @classmethod
    def sync_to_player(cls, actor_ref, offset=0.9):
        pos=cls.engine.movement(cls.wid).state(cls.avatar)
        geo=cls.engine.spatial(cls.wid).isometric_to_geodetic(pos['iso_x_m']+offset,pos['iso_y_m'],pos['altitude_m'])
        cls.engine.movement(cls.wid).sync_to_geodetic(actor_ref,geo,reason='STAGE07_TEST')

    def test_01_health_and_bootstrap(self):
        self.assertEqual(self.engine.health_arpg_v07(self.wid)['status'],'PASS')
        v=self.ac.verify(); self.assertEqual(v['status'],'PASS'); self.assertGreaterEqual(v['country_source_actors'],490)

    def test_02_player_actor_overlay(self):
        p=self.ac.ensure_profile(self.pref); self.assertEqual(p['actor_role'],'PLAYER'); self.assertEqual(p['disposition'],'ALLIED')
        self.assertFalse(p['ai_enabled'])

    def test_03_children_are_noncombatant_and_protected(self):
        p=self.ac.actor(self.child['id']); self.assertTrue(p['protected_identity']); self.assertEqual(p['combat_rank'],'NONCOMBATANT')
        out=self.ac.set_disposition(self.child['id'],'HOSTILE',event_ref='u07:child-hostile'); self.assertEqual(out['status'],'REJECTED')
        self.assertEqual(out['reason'],'PROTECTED_ACTOR_CANNOT_AUTO_AGGRESS')

    def test_04_worker_not_auto_hostile(self):
        p=self.ac.actor(self.worker['id']); self.assertTrue(p['protected_identity']); self.assertFalse(p['ai_enabled'])
        out=self.ac.set_combat_rank(self.worker['id'],'ELITE',event_ref='u07:worker-elite'); self.assertEqual(out['status'],'REJECTED')

    def test_05_combatants_default_neutral(self):
        p=self.ac.actor(self.hostile_npc['id']); self.assertEqual(p['disposition'],'NEUTRAL'); self.assertFalse(p['ai_enabled'])

    def test_06_set_hostile_and_replay(self):
        out=self.ac.set_disposition(self.hostile_npc['id'],'HOSTILE',event_ref='u07:hostile'); self.assertEqual(out['status'],'PASS'); self.assertTrue(out['ai_enabled'])
        rep=self.ac.set_disposition(self.hostile_npc['id'],'HOSTILE',event_ref='u07:hostile'); self.assertTrue(rep['idempotent_replay'])
        self.assertTrue(self.ac.hostility_to_profile(self.hostile_npc['id'],self.pref)['hostile'])

    def test_07_neutral_pointer_stays_context(self):
        arpg=self.engine.arpg(self.wid); seq=arpg._input(self.pref)['last_client_sequence']+1
        s=arpg.submit_command('local:test',self.pref,seq,'SELECT_TARGET',{'target_ref':self.neutral_npc['id']}); self.assertEqual(s['status'],'PASS')
        seq+=1; out=arpg.submit_command('local:test',self.pref,seq,'PRIMARY_ACTION',{}); self.assertEqual(out['status'],'PASS'); self.assertEqual(out['route'],'NPC_CONTEXT')
        self.assertEqual(out['active_hostility_policy'],'STAGE07_RUNTIME_HOSTILITY_WHEN_ATTACHED')

    def test_08_hostile_pointer_auto_combat(self):
        self.sync_to_player(self.hostile_npc['id'])
        arpg=self.engine.arpg(self.wid); seq=arpg._input(self.pref)['last_client_sequence']+1
        arpg.submit_command('local:test',self.pref,seq,'SELECT_TARGET',{'target_ref':self.hostile_npc['id']})
        seq+=1; out=arpg.submit_command('local:test',self.pref,seq,'PRIMARY_ACTION',{})
        self.assertEqual(out['route'],'COMBAT'); self.assertTrue(out['auto_hostile']); self.assertIn(out['status'],{'PASS','REJECTED'})
        if out['status']=='REJECTED': self.assertIn(out['result']['reason'],{'ATTACK_COOLDOWN'})

    def test_09_ai_chase(self):
        self.sync_to_player(self.hostile_npc['id'],offset=4.0)
        out=self.ac.tick_actor(self.hostile_npc['id'],0.25); self.assertEqual(out['status'],'PASS'); self.assertEqual(out['ai_state'],'CHASE'); self.assertEqual(out['action'],'MOVE_TOWARD_TARGET')

    def test_10_ai_attack_character_core(self):
        self.sync_to_player(self.hostile_npc['id'],offset=0.8)
        before=self.engine.character(self.wid).state(self.pref)['vitals']['health']; hit=False
        for i in range(30):
            out=self.ac.tick_actor(self.hostile_npc['id'],1.0)
            combat=out.get('combat') or {}
            if out.get('action')=='ATTACK' and combat.get('status')=='PASS' and combat.get('hit'):
                hit=True; break
        self.assertTrue(hit)
        after=self.engine.character(self.wid).state(self.pref)['vitals']['health']; self.assertLess(after,before)

    def test_11_elite_rank_scales_without_canon_mutation(self):
        c=self.engine.combat_arpg(self.wid); base=c.ensure_enemy(self.hostile_npc['id']).copy()
        out=self.ac.set_combat_rank(self.hostile_npc['id'],'ELITE',event_ref='u07:elite'); self.assertEqual(out['status'],'PASS')
        now=c.ensure_enemy(self.hostile_npc['id']); self.assertGreater(now['max_health'],base['max_health']); self.assertGreater(now['base_damage'],base['base_damage'])
        self.assertEqual(now['combat_rank'],'ELITE'); self.assertFalse(self.ac.actor(self.hostile_npc['id'])['canonical_identity_mutation'])

    def test_12_boss_rank_scales_further(self):
        elite=self.engine.combat_arpg(self.wid).ensure_enemy(self.hostile_npc['id'])['max_health']
        out=self.ac.set_combat_rank(self.hostile_npc['id'],'BOSS',event_ref='u07:boss'); self.assertEqual(out['status'],'PASS')
        boss=self.engine.combat_arpg(self.wid).ensure_enemy(self.hostile_npc['id'])['max_health']; self.assertGreater(boss,elite)
        self.assertEqual(self.ac.actor(self.hostile_npc['id'])['actor_role'],'BOSS')

    def test_13_event_conflict(self):
        self.ac.set_disposition(self.neutral_npc['id'],'WARY',event_ref='u07:conflict',reason='A')
        with self.assertRaises(ConflictError): self.ac.set_disposition(self.neutral_npc['id'],'FRIENDLY',event_ref='u07:conflict',reason='B')

    def test_14_client_snapshot_actor_state(self):
        arpg=self.engine.arpg(self.wid); seq=arpg._input(self.pref)['last_client_sequence']+1
        arpg.submit_command('local:test',self.pref,seq,'SELECT_TARGET',{'target_ref':self.hostile_npc['id']})
        snap=arpg.client_snapshot(self.pref); self.assertIsNotNone(snap['actors']); self.assertEqual(snap['actors']['player_actor']['actor_role'],'PLAYER')
        self.assertEqual(snap['actors']['selected_target']['actor']['actor_ref'],self.hostile_npc['id'])

    def test_15_tick_arpg_wrapper(self):
        out=self.engine.tick_arpg(self.pref,delta_s=0.1,max_ai_actors=8); self.assertEqual(out['status'],'PASS'); self.assertEqual(out['actors']['status'],'PASS')

    def test_16_verify(self):
        self.assertEqual(self.ac.verify()['status'],'PASS'); self.assertEqual(self.engine.health_arpg_v07(self.wid)['status'],'PASS')


class ActorStage07PersistenceTests(unittest.TestCase):
    def test_17_persistence_resume(self):
        with tempfile.TemporaryDirectory() as td:
            db=os.path.join(td,'persist.sqlite'); e=IntegratedARPGEngineV07(db,master_release_path=MASTER)
            wid=e.create_world('stage07:persist',70708)['world']['world_instance_id']; p=e.arpg(wid).create_profile('local:p',origin_mode='CREATED',display_name='Persist')['profile']
            n=next(n for n in e.country(wid)._all_npc_records() if n['id']!=p['avatar_ref'] and not (n.get('protection') or {}).get('protected'))
            ac=e.actors_arpg(wid); ac.set_disposition(n['id'],'HOSTILE',event_ref='p:hostile'); ac.set_combat_rank(n['id'],'CHAMPION',event_ref='p:rank'); before=ac.actor(n['id']); e.close()
            e2=IntegratedARPGEngineV07(db,master_release_path=MASTER); e2.resume_world(wid); after=e2.actors_arpg(wid).actor(n['id'])
            self.assertEqual(after['disposition'],'HOSTILE'); self.assertEqual(after['combat_rank'],'CHAMPION'); self.assertEqual(after['home_position'],before['home_position']); self.assertEqual(e2.health_arpg_v07(wid)['status'],'PASS'); e2.close()

if __name__=='__main__': unittest.main(verbosity=2)
