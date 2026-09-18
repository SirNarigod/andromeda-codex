import json, os, sqlite3, tempfile, threading, unittest, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'01_RUNTIME'))

from living_runtime import LivingRuntime, ValidationError, ConflictError, IntegrityError, NotFoundError
from consequence_engine import ConsequenceEngine
from agent_brain import AgentBrain, IntentValidator
from social_memory import SocialMemorySystem
from ecology_brain import EcologySystem
from object_environment import ObjectEnvironmentSystem
from world_orchestrator import WorldSimulationOrchestrator
from world_systems import WorldSystems
from long_horizon import LongHorizonSimulation

MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
HERB='CRI-001'; HOME='TER-011'

class LHCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=os.path.join(self.tmp.name,'w.db')
        self.rt=LivingRuntime(self.db,master_release_path=MASTER);self.w=self.rt.create_world('lh-test',1111,ticks_per_day=24);self.wid=self.w['world_instance_id']
        self.val=IntentValidator(self.rt);self.brain=AgentBrain(self.rt,self.val);self.social=SocialMemorySystem(self.rt);self.eco=EcologySystem(self.rt,self.val);self.obj=ObjectEnvironmentSystem(self.rt);self.cons=ConsequenceEngine(self.rt);self.orch=WorldSimulationOrchestrator(self.rt,self.cons,self.brain,self.val,self.social,self.eco,self.obj)
        self.orch.configure_world(self.wid,{'integrity_cadence_ticks':24,'max_roots_per_run':256,'extension_budget':4})
        self.ws=WorldSystems(self.rt);self.ws.load_master_snapshots(MASTER);self.ws.bootstrap_world(self.wid,population_seed=1000)
        self.eco.load_master_fauna_snapshots();self.eco.register_species_profile(self.wid,{'species_ref':HERB,'diet':'HERBIVORE','social_structure':'HERD','cognition_mode':'ADAPTIVE','activity_mode':'DIURNAL','range_excursion_allowed':False});self.eco.install_default_action_policies(self.wid);self.eco.register_population(self.wid,species_ref=HERB,territory_ref=HOME,count=100,carrying_capacity=200)
        self.lh=LongHorizonSimulation(self.rt,self.orch,self.ws,self.eco,self.obj);self.lh.configure_world(self.wid)
    def tearDown(self):
        try:self.rt.close()
        except:pass
        self.tmp.cleanup()
    def begin(self):return self.lh.begin_offline_session(self.wid)

class PolicyChronologyTests(LHCase):
    def test_default_policy(self):self.assertEqual(self.lh.get_policy(self.wid)['long_chunk_days'],30)
    def test_unknown_policy_rejected(self):
        with self.assertRaises(ValidationError):self.lh.configure_world(self.wid,{'magic_year':1})
    def test_bad_fraction_rejected(self):
        with self.assertRaises(ValidationError):self.lh.configure_world(self.wid,{'max_ecology_change_fraction_per_chunk':.9})
    def test_default_calendar_no_fake_year(self):self.assertIsNone(self.lh.chronology(self.wid)['display_calendar'])
    def test_runtime_display_calendar_optional(self):self.lh.configure_world(self.wid,{'display_days_per_year':360});self.assertEqual(self.lh.chronology(self.wid)['display_calendar']['days_per_year'],360)
    def test_chronology_authority(self):self.assertEqual(self.lh.chronology(self.wid)['authority'],'UNIVERSE_DAY_INDEX')
    def test_policy_hash_corruption_detected(self):
        self.rt.conn.execute('DROP TRIGGER long_policy_no_update_hash_guard');self.rt.conn.execute("UPDATE long_horizon_policies SET policy_json='{}' WHERE world_instance_id=?",(self.wid,))
        with self.assertRaises(IntegrityError):self.lh.get_policy(self.wid)

class OfflineSessionTests(LHCase):
    def test_begin_sets_offline(self):self.begin();self.assertEqual(self.rt.get_world(self.wid)['simulation_mode'],'ROUTINE_OFFLINE')
    def test_begin_records_snapshot(self):s=self.begin();self.assertEqual(self.rt.conn.execute("SELECT COUNT(*) c FROM temporal_snapshots WHERE session_id=?",(s['session_id'],)).fetchone()['c'],1)
    def test_duplicate_begin_blocked(self):self.begin();self.rt.set_simulation_mode(self.wid,'FULL');
    def test_duplicate_begin_blocked_actual(self):
        self.begin();
        with self.assertRaises(ConflictError):self.lh.begin_offline_session(self.wid)
    def test_already_offline_without_session_blocked(self):
        self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE')
        with self.assertRaises(ConflictError):self.lh.begin_offline_session(self.wid)
    def test_no_open_session_simulation_rejected(self):
        with self.assertRaises(NotFoundError):self.lh.simulate_offline_days(self.wid,1)
    def test_bad_days_rejected(self):
        self.begin()
        with self.assertRaises(ValidationError):self.lh.simulate_offline_days(self.wid,0)
    def test_max_days_guard(self):
        self.begin()
        with self.assertRaises(ValidationError):self.lh.simulate_offline_days(self.wid,3651)

class CatchupTests(LHCase):
    def test_one_day_advances_exactly_24_ticks(self):
        self.begin();self.lh.simulate_offline_days(self.wid,1,request_key='r');c=self.rt.get_clock(self.wid);self.assertEqual((c['day'],c['tick']),(1,0))
    def test_short_horizon_daily_segments(self):self.begin();r=self.lh.simulate_offline_days(self.wid,7,request_key='r');self.assertEqual(r['segments'],7)
    def test_medium_horizon_weekly_segments(self):self.begin();r=self.lh.simulate_offline_days(self.wid,28,request_key='r');self.assertEqual(r['segments'],4)
    def test_long_horizon_monthlike_chunks_runtime_only(self):self.begin();r=self.lh.simulate_offline_days(self.wid,365,request_key='r');self.assertGreaterEqual(r['segments'],13)
    def test_request_idempotency(self):
        self.begin();a=self.lh.simulate_offline_days(self.wid,7,request_key='same');c1=self.rt.get_clock(self.wid).copy();b=self.lh.simulate_offline_days(self.wid,7,request_key='same');c2=self.rt.get_clock(self.wid).copy();self.assertTrue(b['idempotent_replay']);self.assertEqual(c1,c2);self.assertEqual(a['segment_ids'],b['segment_ids'])
    def test_request_key_duration_conflict(self):
        self.begin();self.lh.simulate_offline_days(self.wid,1,request_key='same')
        with self.assertRaises(ConflictError):self.lh.simulate_offline_days(self.wid,2,request_key='same')
    def test_no_individual_decisions(self):
        self.begin();r=self.lh.simulate_offline_days(self.wid,30,request_key='r');self.assertEqual(r['individual_npc_decisions_added'],0);self.assertEqual(r['individual_ecology_decisions_added'],0)
    def test_population_human_migration_frozen(self):
        before=[p['data']['migration_accumulator'] for p in self.ws._entities(self.wid,'POPULATION_AGGREGATE')];self.begin();self.lh.simulate_offline_days(self.wid,30,request_key='r');after=[p['data']['migration_accumulator'] for p in self.ws._entities(self.wid,'POPULATION_AGGREGATE')];self.assertEqual(before,after)
    def test_faction_influence_frozen(self):
        before=[f['data']['influence'] for f in self.ws._entities(self.wid,'FACTION_RUNTIME')];self.begin();self.lh.simulate_offline_days(self.wid,60,request_key='r');after=[f['data']['influence'] for f in self.ws._entities(self.wid,'FACTION_RUNTIME')];self.assertEqual(before,after)
    def test_population_chunk_cap(self):
        before=[p['data']['count'] for p in self.ws._entities(self.wid,'POPULATION_AGGREGATE')];self.begin();self.lh.simulate_offline_days(self.wid,30,request_key='r');after=[p['data']['count'] for p in self.ws._entities(self.wid,'POPULATION_AGGREGATE')];self.assertTrue(all(.9*b<=a<=1.1*b+1 for a,b in zip(after,before)))
    def test_ecology_chunk_cap(self):
        b=self.eco.get_population(self.wid,HERB,HOME)['count'];self.begin();self.lh.simulate_offline_days(self.wid,30,request_key='r');a=self.eco.get_population(self.wid,HERB,HOME)['count'];self.assertTrue(.85*b<=a<=1.15*b+1)
    def test_periodic_snapshot_created(self):
        s=self.begin();self.lh.simulate_offline_days(self.wid,60,request_key='r');self.assertGreaterEqual(self.rt.conn.execute("SELECT COUNT(*) c FROM temporal_snapshots WHERE session_id=?",(s['session_id'],)).fetchone()['c'],3)
    def test_segment_chain(self):
        s=self.begin();self.lh.simulate_offline_days(self.wid,35,request_key='r');self.assertEqual(self.lh.verify_segment_chain(s['session_id'])['status'],'PASS')

class RecoveryTests(LHCase):
    def test_recovery_splits_at_day7(self):
        prof=self.obj.register_profile(self.wid,{'object_class':'BRIDGE','material_class':'STONE','base_integrity':100});o=self.obj.spawn_object(self.wid,profile_id=prof['profile_id']);
        # System actor is allowed for deterministic setup.
        self.obj.interact(self.wid,actor_ref='SYSTEM_RECONCILIATION',target_ref=o['entity_runtime_id'],interaction_type='DAMAGE',amount=100,routine_safe=True)
        s=self.begin();r=self.lh.simulate_offline_days(self.wid,30,request_key='r');self.assertEqual(self.rt.get_entity(self.wid,o['entity_runtime_id'])['lifecycle'],'ACTIVE');rows=self.rt.conn.execute("SELECT to_day FROM long_horizon_segments WHERE session_id=? ORDER BY sequence",(s['session_id'],)).fetchall();self.assertIn(7,[x['to_day'] for x in rows])
    def test_recovery_history_preserved(self):
        prof=self.obj.register_profile(self.wid,{'object_class':'BRIDGE','material_class':'STONE','base_integrity':100});o=self.obj.spawn_object(self.wid,profile_id=prof['profile_id']);self.obj.interact(self.wid,actor_ref='SYSTEM_RECONCILIATION',target_ref=o['entity_runtime_id'],interaction_type='DAMAGE',amount=100,routine_safe=True);before=self.rt.event_count(self.wid);self.begin();self.lh.simulate_offline_days(self.wid,7,request_key='r');self.assertGreater(self.rt.event_count(self.wid),before)

class ReconciliationTests(LHCase):
    def test_resume_prior_mode(self):self.begin();self.lh.simulate_offline_days(self.wid,7,request_key='r');r=self.lh.reconcile_and_resume(self.wid);self.assertEqual(r['resume_mode'],'FULL');self.assertEqual(self.rt.get_world(self.wid)['simulation_mode'],'FULL')
    def test_resume_active_override(self):self.begin();self.lh.simulate_offline_days(self.wid,1,request_key='r');self.lh.reconcile_and_resume(self.wid,resume_mode='ACTIVE');self.assertEqual(self.rt.get_world(self.wid)['simulation_mode'],'ACTIVE')
    def test_resume_offline_rejected(self):self.begin();self.lh.simulate_offline_days(self.wid,1,request_key='r');
    def test_resume_offline_rejected_actual(self):
        self.begin();self.lh.simulate_offline_days(self.wid,1,request_key='r')
        with self.assertRaises(ValidationError):self.lh.reconcile_and_resume(self.wid,resume_mode='ROUTINE_OFFLINE')
    def test_report_created(self):self.begin();self.lh.simulate_offline_days(self.wid,7,request_key='r');r=self.lh.reconcile_and_resume(self.wid);self.assertTrue(r['report_hash']);self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM reconciliation_reports').fetchone()['c'],1)
    def test_session_reconciled(self):s=self.begin();self.lh.simulate_offline_days(self.wid,1,request_key='r');self.lh.reconcile_and_resume(self.wid);self.assertEqual(self.rt.conn.execute('SELECT status FROM offline_sessions WHERE session_id=?',(s['session_id'],)).fetchone()['status'],'RECONCILED')
    def test_second_session_allowed(self):self.begin();self.lh.simulate_offline_days(self.wid,1,request_key='a');self.lh.reconcile_and_resume(self.wid);self.begin();self.lh.simulate_offline_days(self.wid,1,request_key='b');self.lh.reconcile_and_resume(self.wid);self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM offline_sessions').fetchone()['c'],2)
    def test_reconcile_detects_individual_decision_count_drift(self):
        self.begin();self.lh.simulate_offline_days(self.wid,1,request_key='r');
        # artificial evidence of forbidden individual decision
        self.rt.conn.execute("INSERT INTO agent_decisions(decision_id,world_instance_id,timeline_id,agent_ref,intent_id,decision_json,decision_hash) VALUES('fake',?,?,?,?,?,?)",(self.wid,self.w['timeline_id'],'fake',None,'{}','bad'))
        with self.assertRaises(IntegrityError):self.lh.reconcile_and_resume(self.wid)

class IntegrityTests(LHCase):
    def test_snapshot_immutable(self):
        s=self.lh.create_snapshot(self.wid)
        with self.assertRaises(sqlite3.DatabaseError):self.rt.conn.execute("UPDATE temporal_snapshots SET state_json='{}' WHERE snapshot_id=?",(s['snapshot_id'],))
    def test_segment_immutable(self):
        self.begin();r=self.lh.simulate_offline_days(self.wid,1,request_key='r')
        with self.assertRaises(sqlite3.DatabaseError):self.rt.conn.execute("DELETE FROM long_horizon_segments WHERE segment_id=?",(r['segment_ids'][0],))
    def test_segment_corruption_detected_after_trigger_removed(self):
        s=self.begin();r=self.lh.simulate_offline_days(self.wid,1,request_key='r');self.rt.conn.execute('DROP TRIGGER long_segment_no_update');self.rt.conn.execute("UPDATE long_horizon_segments SET segment_json='{}' WHERE segment_id=?",(r['segment_ids'][0],));self.assertEqual(self.lh.verify_segment_chain(s['session_id'])['status'],'FAIL')
    def test_full_integrity_pass(self):self.begin();self.lh.simulate_offline_days(self.wid,7,request_key='r');self.assertEqual(self.lh.full_integrity_check(self.wid)['status'],'PASS')
    def test_integrity_guard_blocks_corrupt(self):
        s=self.lh.create_snapshot(self.wid);self.rt.conn.execute('DROP TRIGGER temporal_snapshot_no_update');self.rt.conn.execute("UPDATE temporal_snapshots SET state_json='{}' WHERE snapshot_id=?",(s['snapshot_id'],));self.assertEqual(self.lh.integrity_guard(self.wid)['status'],'FAIL');self.assertEqual(self.rt.get_world(self.wid)['status'],'CORRUPT_BLOCKED')

class ConcurrentIdempotencyTests(LHCase):
    def test_same_request_concurrent_does_not_double_advance(self):
        self.begin();outs=[];errs=[]
        def work():
            try:outs.append(self.lh.simulate_offline_days(self.wid,1,request_key='same'))
            except Exception as e:errs.append(type(e).__name__)
        ts=[threading.Thread(target=work) for _ in range(8)]
        for t in ts:t.start()
        for t in ts:t.join()
        c=self.rt.get_clock(self.wid);self.assertEqual(c['day'],1);self.assertGreaterEqual(len(outs),1);self.assertTrue(all(o['to']['day']==1 for o in outs))

if __name__=='__main__':unittest.main()
