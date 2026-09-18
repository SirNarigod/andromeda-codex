from __future__ import annotations
import os, sys, tempfile, unittest

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT,'01_RUNTIME'))
from integrated_arpg_engine_v06 import IntegratedARPGEngineV06
from living_runtime import ConflictError

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

class SkillStage06Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); cls.db=os.path.join(cls.tmp.name,'world.sqlite')
        cls.engine=IntegratedARPGEngineV06(cls.db,master_release_path=MASTER)
        cls.wid=cls.engine.create_world('stage06:test',60606)['world']['world_instance_id']
        p=cls.engine.arpg(cls.wid).create_profile('local:test',origin_mode='CREATED',display_name='SkillTester')['profile']
        cls.pref=p['profile_ref']; cls.avatar=p['avatar_ref']; cls.skills=cls.engine.skills_arpg(cls.wid)
        cls.target=next(n['id'] for n in cls.engine.country(cls.wid)._all_npc_records() if n['id']!=cls.avatar and not (n.get('protection') or {}).get('protected'))
        pos=cls.engine.movement(cls.wid).state(cls.avatar); geo=cls.engine.spatial(cls.wid).isometric_to_geodetic(pos['iso_x_m'],pos['iso_y_m'],pos['altitude_m'])
        cls.engine.movement(cls.wid).sync_to_geodetic(cls.target,geo,reason='STAGE06_TEST')

    @classmethod
    def tearDownClass(cls):
        cls.engine.close(); cls.tmp.cleanup()

    @classmethod
    def ready_target(cls):
        c=cls.engine.combat_arpg(cls.wid); st=c.ensure_enemy(cls.target)
        if st['life_state']!='ALIVE' or st['health']<5:
            st['life_state']='ALIVE'; st['health']=st['max_health']; c._save_row('arpg_enemy_combat_state',cls.target,st)
        c.tick_player(cls.pref,1.0); cls.engine.resources_arpg(cls.wid).tick_profile(cls.pref,1.0); cls.engine.resources_arpg(cls.wid).tick_profile(cls.pref,0.5)

    def test_01_health_catalog(self):
        self.assertEqual(self.engine.health_arpg_v06(self.wid)['status'],'PASS')
        defs=self.skills.list_definitions(); self.assertEqual(len(defs),36)
        self.assertEqual(sum(1 for d in defs if d['source_authority']=='MASTER_READ_ONLY'),30)
        self.assertEqual(sum(1 for d in defs if d['source_authority']=='GAMEPLAY_DERIVED_REPLACEABLE'),6)

    def test_02_canonical_magic_preserved_not_auto_castable(self):
        d=self.skills.definition('SKL-CANON-MAG-007')
        self.assertEqual(d['canonical_ref'],'MAG-007'); self.assertEqual(d['name'],'Estase de Intervalo')
        self.assertFalse(d['player_castable_default']); self.assertEqual(d['effect_model'],'LORE_BOUND_NO_RUNTIME_EFFECT')
        self.assertIn('MASTER_READ_ONLY',d['source_authority'])

    def test_03_initial_no_fixed_class(self):
        s=self.skills.snapshot(self.pref)
        self.assertEqual(s['learned'],{}); self.assertIsNone(s['build_signature']['fixed_class'])
        self.assertEqual(s['build_signature']['evidence_total'],0.0)

    def test_04_learn_and_replay(self):
        out=self.skills.learn_skill(self.pref,'SKL-GP-POWER-STRIKE',event_ref='u06:learn',source_type='TRAINING',source_ref='TRAINER:TEST')
        self.assertEqual(out['status'],'PASS')
        replay=self.skills.learn_skill(self.pref,'SKL-GP-POWER-STRIKE',event_ref='u06:learn',source_type='TRAINING',source_ref='TRAINER:TEST')
        self.assertTrue(replay['idempotent_replay'])

    def test_05_assign_active(self):
        out=self.skills.assign_active(self.pref,'SKL-GP-POWER-STRIKE',1,event_ref='u06:assign')
        self.assertEqual(out['status'],'PASS'); self.assertEqual(self.skills.state(self.pref)['active_loadout']['1'],'SKL-GP-POWER-STRIKE')

    def test_06_use_skill_spends_resource_and_damages(self):
        self.ready_target(); c=self.engine.character(self.wid); before_r=c.state(self.pref)['vitals']['resource']; before_h=self.engine.combat_arpg(self.wid).ensure_enemy(self.target)['health']
        out=self.skills.use_slot(self.pref,1,event_ref='u06:use1',target_ref=self.target)
        self.assertEqual(out['status'],'PASS'); self.assertLess(c.state(self.pref)['vitals']['resource'],before_r)
        self.assertLessEqual(self.engine.combat_arpg(self.wid).ensure_enemy(self.target)['health'],before_h)
        self.assertEqual(out['effect']['skill_ref'],'SKL-GP-POWER-STRIKE')

    def test_07_use_replay_no_double_spend(self):
        r=self.engine.character(self.wid).state(self.pref)['vitals']['resource']; h=self.engine.combat_arpg(self.wid).ensure_enemy(self.target)['health']
        out=self.skills.use_slot(self.pref,1,event_ref='u06:use1',target_ref=self.target)
        self.assertTrue(out['idempotent_replay']); self.assertEqual(self.engine.character(self.wid).state(self.pref)['vitals']['resource'],r)
        self.assertEqual(self.engine.combat_arpg(self.wid).ensure_enemy(self.target)['health'],h)

    def test_08_cooldown_blocks_new_use(self):
        out=self.skills.use_slot(self.pref,1,event_ref='u06:cooldown',target_ref=self.target)
        self.assertEqual(out['status'],'REJECTED'); self.assertIn(out['reason'],{'ACTION_COOLDOWN','ATTACK_RECOVERY'})

    def test_09_passive_modifies_combat(self):
        self.skills.learn_skill(self.pref,'SKL-GP-GUARD-DISCIPLINE',event_ref='u06:learnpass',source_ref='TRAINER:TEST')
        base=self.engine.combat_arpg(self.wid).player_stats(self.pref)['armor']
        out=self.skills.activate_passive(self.pref,'SKL-GP-GUARD-DISCIPLINE',1,event_ref='u06:passive')
        self.assertEqual(out['status'],'PASS')
        after=self.engine.combat_arpg(self.wid).player_stats(self.pref); self.assertGreater(after['armor'],base)
        self.assertIsInstance(after['skill_modifiers'],dict)

    def test_10_build_evidence_changes_from_use(self):
        sig=self.skills.build_signature(self.pref); self.assertGreater(sig['evidence_total'],0)
        self.assertEqual(sig['dominant_axes'][0]['axis'],'MARTIAL'); self.assertIsNone(sig['fixed_class'])

    def test_11_mastery_rank_progression(self):
        # 9 additional successful uses + the first use = rank 2 at 100 mastery XP.
        start=self.skills.state(self.pref)['learned']['SKL-GP-POWER-STRIKE']['use_count']
        needed=max(0,10-start)
        for i in range(needed):
            self.ready_target()
            # refill resource if required without bypassing CharacterCore authority
            ch=self.engine.character(self.wid); st=ch.state(self.pref); missing=st['derived']['max_resource']-st['vitals']['resource']
            if missing>0: ch.apply_resource_change(self.pref,missing,event_ref=f'u06:refill:{i}',source_type='TEST')
            out=self.skills.use_skill(self.pref,'SKL-GP-POWER-STRIKE',event_ref=f'u06:mastery:{i}',target_ref=self.target)
            self.assertEqual(out['status'],'PASS')
        rec=self.skills.state(self.pref)['learned']['SKL-GP-POWER-STRIKE']; self.assertGreaterEqual(rec['use_count'],10); self.assertGreaterEqual(rec['rank'],2)

    def test_12_canonical_source_can_be_learned_but_not_mapped_to_active(self):
        out=self.skills.learn_skill(self.pref,'SKL-CANON-MAG-007',event_ref='u06:learncanon',source_type='CANONICAL_TRAINING',source_ref='EDU-MAR-001')
        self.assertEqual(out['status'],'PASS')
        assign=self.skills.assign_active(self.pref,'SKL-CANON-MAG-007',2,event_ref='u06:assigncanon')
        self.assertEqual(assign['status'],'REJECTED'); self.assertEqual(assign['reason'],'SKILL_NOT_ACTIVE')

    def test_13_game_core_skill_commands(self):
        self.skills.learn_skill(self.pref,'SKL-GP-PRECISION-STRIKE',event_ref='u06:learnprec',source_ref='TRAINER:TEST')
        seq=self.engine.arpg(self.wid)._input(self.pref)['last_client_sequence']+1
        a=self.engine.arpg(self.wid).submit_command('local:test',self.pref,seq,'ASSIGN_SKILL',{'skill_ref':'SKL-GP-PRECISION-STRIKE','slot':2})
        self.assertEqual(a['status'],'PASS'); self.assertEqual(a['route'],'SKILL')
        self.ready_target(); seq+=1
        ch=self.engine.character(self.wid); st=ch.state(self.pref); missing=st['derived']['max_resource']-st['vitals']['resource']
        if missing>0: ch.apply_resource_change(self.pref,missing,event_ref='u06:cmdrefill',source_type='TEST')
        u=self.engine.arpg(self.wid).submit_command('local:test',self.pref,seq,'USE_SKILL',{'slot':2,'target_ref':self.target})
        self.assertEqual(u['status'],'PASS'); self.assertEqual(u['route'],'SKILL')
        replay=self.engine.arpg(self.wid).submit_command('local:test',self.pref,seq,'USE_SKILL',{'slot':2,'target_ref':self.target}); self.assertTrue(replay['idempotent_replay'])

    def test_14_snapshot_contains_skills(self):
        snap=self.engine.arpg(self.wid).client_snapshot(self.pref)
        self.assertIsNotNone(snap['skills']); self.assertEqual(snap['skills']['definition_count'],36)
        self.assertIsNone(snap['skills']['build_signature']['fixed_class'])

    def test_15_event_conflict(self):
        self.skills.learn_skill(self.pref,'SKL-GP-SWIFT-DISCIPLINE',event_ref='u06:conflict',source_ref='A')
        with self.assertRaises(ConflictError):
            self.skills.learn_skill(self.pref,'SKL-GP-FOCUS-DISCIPLINE',event_ref='u06:conflict',source_ref='B')

    def test_16_verify(self):
        self.assertEqual(self.skills.verify()['status'],'PASS')
        self.assertEqual(self.engine.health_arpg_v06(self.wid)['status'],'PASS')


class SkillStage06PersistenceTests(unittest.TestCase):
    def test_17_persistence_resume(self):
        with tempfile.TemporaryDirectory() as td:
            db=os.path.join(td,'persist.sqlite'); e=IntegratedARPGEngineV06(db,master_release_path=MASTER)
            wid=e.create_world('stage06:persist',60607)['world']['world_instance_id']; p=e.arpg(wid).create_profile('local:p',origin_mode='CREATED',display_name='Persist')['profile']; pref=p['profile_ref']
            sk=e.skills_arpg(wid); sk.learn_skill(pref,'SKL-GP-GUARD-DISCIPLINE',event_ref='p:learn',source_ref='TRAINER'); sk.activate_passive(pref,'SKL-GP-GUARD-DISCIPLINE',1,event_ref='p:passive'); before=sk.snapshot(pref); e.close()
            e2=IntegratedARPGEngineV06(db,master_release_path=MASTER); e2.resume_world(wid); after=e2.skills_arpg(wid).snapshot(pref)
            self.assertEqual(after['passive_loadout']['1'],'SKL-GP-GUARD-DISCIPLINE'); self.assertEqual(after['learned'],before['learned']); self.assertEqual(e2.health_arpg_v06(wid)['status'],'PASS'); e2.close()

if __name__=='__main__': unittest.main(verbosity=2)
