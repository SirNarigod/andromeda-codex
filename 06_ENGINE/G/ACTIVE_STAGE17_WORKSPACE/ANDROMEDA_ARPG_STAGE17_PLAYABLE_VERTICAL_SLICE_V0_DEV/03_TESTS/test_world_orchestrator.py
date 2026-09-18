import copy, json, os, sqlite3, tempfile, threading, unittest, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '01_RUNTIME'))

from living_runtime import LivingRuntime, ValidationError, IntegrityError, ConflictError, NotFoundError, OfflinePolicyError, new_runtime_id, clock_point
from consequence_engine import ConsequenceEngine
from agent_brain import AgentBrain, IntentValidator
from social_memory import SocialMemorySystem
from ecology_brain import EcologySystem
from object_environment import ObjectEnvironmentSystem
from world_orchestrator import WorldSimulationOrchestrator, PHASE_ORDER

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
HERB='CRI-001'; HOME='TER-011'; BIOME='BIO-008'

def agent_data(hunger=80):
    return {'needs':{'hunger':hunger,'safety':20},'goals':{'survive':90},'risk_tolerance':50,'location_ref':'LOC-A','money':10,'energy':80}

def make_agent(rt,w,hunger=80):
    c=rt.get_clock(w['world_instance_id']); state={'state_id':new_runtime_id('state'),'world_instance_id':w['world_instance_id'],'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':agent_data(hunger),'protection':{}}
    return rt.register_entity(w['world_instance_id'],state)

def eat_policy():
    return {'policy_key':'policy.eat','action_type':'EAT','allowed_sources':['AGENT_BRAIN'],'actor_kinds':['AGENT'],'target_required':False,'target_kinds':[],'offline_policy':'ACTIVE_ONLY','spatial_policy':'NONE','protection_impacts':[],'cooldown_ticks':0,'parameter_schema':{},'resource_requirements':[],'actor_state_equals':{},'target_state_equals':{},'consequence_templates':[{'target':'ACTOR','operation':'DECREMENT','field_path':'data.needs.hunger','amount':10}]}

def eat_behavior():
    return {'behavior_key':'eat','intent_type':'EAT','need_key':'hunger','threshold':50,'target_strategy':'NONE','need_weight':100,'base_priority':0,'risk_cost':0,'risk_penalty_weight':1,'opportunity_bonus':0,'goal_key':'survive','goal_weight':10,'target_kinds':[],'target_fact_equals':{},'parameters':{}}

def eco_profile():
    return {'species_ref':HERB,'diet':'HERBIVORE','social_structure':'HERD','cognition_mode':'ADAPTIVE','activity_mode':'DIURNAL','range_excursion_allowed':False}

class OrchCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=os.path.join(self.tmp.name,'w.db')
        self.rt=LivingRuntime(self.db,master_release_path=MASTER);self.w=self.rt.create_world('orch-test',909,ticks_per_day=24);self.wid=self.w['world_instance_id']
        self.val=IntentValidator(self.rt);self.brain=AgentBrain(self.rt,self.val);self.social=SocialMemorySystem(self.rt);self.eco=EcologySystem(self.rt,self.val);self.obj=ObjectEnvironmentSystem(self.rt);self.cons=ConsequenceEngine(self.rt)
        self.orch=WorldSimulationOrchestrator(self.rt,self.cons,self.brain,self.val,self.social,self.eco,self.obj)
        self.orch.configure_world(self.wid,{'environment_cadence_ticks':1,'ecology_aggregate_cadence_ticks':1,'integrity_cadence_ticks':1,'full_npc_budget':8,'active_npc_budget':2,'full_ecology_budget':8,'active_ecology_budget':2})
        self.scope=self.orch.register_scope(self.wid,HOME,'FULL')
        self.agent=make_agent(self.rt,self.w);self.val.register_policy(self.wid,eat_policy());self.brain.register_behavior(self.wid,eat_behavior());self.orch.register_participant(self.wid,self.agent['entity_runtime_id'],'NPC',scope_ref=HOME)
        self.eco.load_master_fauna_snapshots(MASTER);self.eco.register_species_profile(self.wid,eco_profile());self.eco.install_default_action_policies(self.wid)
        self.animal=self.eco.spawn_animal(self.wid,species_ref=HERB,territory_ref=HOME,biome_ref=BIOME,age_days=60,hunger=10,thirst=10,energy=80,reproduction_drive=0)
        self.orch.register_participant(self.wid,self.animal['entity_runtime_id'],'ECOLOGY',scope_ref=HOME)
        self.eco.register_population(self.wid,species_ref=HERB,territory_ref=HOME,count=100,carrying_capacity=200,resource_index=80,water_index=80,climate_comfort=80)
    def tearDown(self):
        try:self.rt.close()
        except:pass
        self.tmp.cleanup()
    def tick(self,**kw):return self.orch.run_tick(self.wid,**kw)

class PolicyScopeTests(OrchCase):
    def test_policy_authority(self):self.assertEqual(self.orch.get_policy(self.wid)['authority'],'RUNTIME_ORCHESTRATION_NOT_CANON')
    def test_unknown_policy_field_rejected(self):
        with self.assertRaises(ValidationError):self.orch.configure_world(self.wid,{'magic_budget':1})
    def test_zero_budget_rejected(self):
        with self.assertRaises(ValidationError):self.orch.configure_world(self.wid,{'full_npc_budget':0})
    def test_causal_budget_above_engine_rejected(self):
        with self.assertRaises(ValidationError):self.orch.configure_world(self.wid,{'consequence_root_budget':999})
    def test_scope_canonical_ref_valid(self):self.assertEqual(self.scope['scope_ref'],HOME)
    def test_scope_unknown_ref_rejected(self):
        with self.assertRaises(ValidationError):self.orch.register_scope(self.wid,'TER-999','FULL')
    def test_scope_invalid_lod(self):
        with self.assertRaises(ValidationError):self.orch.register_scope(self.wid,'TER-002','ULTRA')
    def test_scope_duplicate_rejected(self):
        with self.assertRaises(ConflictError):self.orch.register_scope(self.wid,HOME,'ACTIVE')
    def test_scope_change(self):self.assertEqual(self.orch.set_scope_lod(self.wid,HOME,'ACTIVE')['lod'],'ACTIVE')

class ParticipantTests(OrchCase):
    def test_npc_participant_persisted(self):self.assertEqual(self.rt.conn.execute("SELECT COUNT(*) c FROM orchestration_participants WHERE subsystem='NPC'").fetchone()['c'],1)
    def test_ecology_participant_persisted(self):self.assertEqual(self.rt.conn.execute("SELECT COUNT(*) c FROM orchestration_participants WHERE subsystem='ECOLOGY'").fetchone()['c'],1)
    def test_wrong_npc_kind_rejected(self):
        with self.assertRaises(ValidationError):self.orch.register_participant(self.wid,self.animal['entity_runtime_id'],'NPC',scope_ref=HOME)
    def test_wrong_ecology_kind_rejected(self):
        a=make_agent(self.rt,self.w)
        with self.assertRaises(ValidationError):self.orch.register_participant(self.wid,a['entity_runtime_id'],'ECOLOGY',scope_ref=HOME)
    def test_unregistered_scope_rejected(self):
        a=make_agent(self.rt,self.w)
        with self.assertRaises(ValidationError):self.orch.register_participant(self.wid,a['entity_runtime_id'],'NPC',scope_ref='TER-002')
    def test_duplicate_participant_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):self.orch.register_participant(self.wid,self.agent['entity_runtime_id'],'NPC',scope_ref=HOME)
    def test_invalid_social_targets_rejected(self):
        a=make_agent(self.rt,self.w)
        with self.assertRaises(ValidationError):self.orch.register_participant(self.wid,a['entity_runtime_id'],'NPC',scope_ref=HOME,metadata={'social_targets':'bad'})

class TickOrderTests(OrchCase):
    def test_full_tick_completes(self):self.assertEqual(self.tick()['status'],'COMPLETED')
    def test_phase_order_exact(self):self.assertEqual([x['phase'] for x in self.tick()['phases']],PHASE_ORDER)
    def test_clock_advances_once(self):
        b=self.rt.get_clock(self.wid)['tick'];self.tick();a=self.rt.get_clock(self.wid)['tick'];self.assertEqual(a,b+1)
    def test_npc_action_changes_state(self):
        self.tick();self.assertEqual(self.rt.get_entity(self.wid,self.agent['entity_runtime_id'])['data']['needs']['hunger'],70)
    def test_ecology_individual_decides(self):
        self.tick();self.assertGreater(self.rt.conn.execute('SELECT COUNT(*) c FROM ecology_decisions').fetchone()['c'],0)
    def test_ecology_aggregate_tick(self):
        self.tick();self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM ecology_routine_ticks').fetchone()['c'],1)
    def test_environment_tick(self):
        self.tick();self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM environment_ticks').fetchone()['c'],1)
    def test_post_guard_full(self):
        r=self.tick();p=[x for x in r['phases'] if x['phase']=='POST_GUARD'][0];self.assertEqual(p['detail']['scope'],'FULL')
    def test_run_idempotent_same_key(self):
        a=self.tick(tick_key='fixed');b=self.tick(tick_key='fixed');self.assertTrue(b['idempotent_replay']);self.assertEqual(a['run_id'],b['run_id']);self.assertEqual(self.rt.get_clock(self.wid)['tick'],1)
    def test_phase_log_immutable(self):
        r=self.tick();pid=r['phases'][0]['phase_log_id']
        with self.assertRaises(sqlite3.DatabaseError):self.rt.conn.execute("UPDATE orchestration_phase_log SET status='FAILED' WHERE phase_log_id=?",(pid,))

class LODTests(OrchCase):
    def test_aggregate_blocks_individual(self):
        self.rt.set_simulation_mode(self.wid,'AGGREGATE');self.tick();self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM agent_decisions').fetchone()['c'],0);self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM ecology_decisions').fetchone()['c'],0);self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM ecology_routine_ticks').fetchone()['c'],1)
    def test_offline_blocks_individual(self):
        self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE');self.tick();self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM agent_decisions').fetchone()['c'],0);self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM ecology_decisions').fetchone()['c'],0)
    def test_scope_aggregate_blocks_participants(self):
        self.orch.set_scope_lod(self.wid,HOME,'AGGREGATE');self.tick();self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM agent_decisions').fetchone()['c'],0);self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM ecology_decisions').fetchone()['c'],0)
    def test_active_budget_limits_npcs(self):
        self.rt.set_simulation_mode(self.wid,'ACTIVE')
        for _ in range(4):
            a=make_agent(self.rt,self.w);self.orch.register_participant(self.wid,a['entity_runtime_id'],'NPC',scope_ref=HOME)
        self.tick();self.assertLessEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM agent_decisions').fetchone()['c'],2)
    def test_full_budget_higher(self):
        for _ in range(4):
            a=make_agent(self.rt,self.w);self.orch.register_participant(self.wid,a['entity_runtime_id'],'NPC',scope_ref=HOME)
        self.tick();self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM agent_decisions').fetchone()['c'],5)

class RecoveryConsequenceTests(OrchCase):
    def test_recovery_phase_recovers_due_object(self):
        prof=self.obj.register_profile(self.wid,{'object_class':'BRIDGE','material_class':'STONE','base_integrity':100});o=self.obj.spawn_object(self.wid,profile_id=prof['profile_id']);actor=self.agent['entity_runtime_id'];self.obj.interact(self.wid,actor_ref=actor,target_ref=o['entity_runtime_id'],interaction_type='DAMAGE',amount=100)
        self.rt.advance_ticks(self.wid,7*24);self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE');self.tick();self.assertEqual(self.rt.get_entity(self.wid,o['entity_runtime_id'])['lifecycle'],'ACTIVE')
    def test_consequence_drain_records_root_run(self):
        self.tick();roots=self.rt.conn.execute('SELECT COUNT(*) c FROM propagation_runs').fetchone()['c'];self.assertGreater(roots,0)
    def test_unpropagated_roots_zero_after_tick_except_clock(self):
        self.tick(); roots=self.orch._unpropagated_roots(self.wid,100);self.assertLessEqual(len(roots),1)

class ExtensionTests(OrchCase):
    def test_extension_runs(self):
        seen=[];self.orch.attach_extension(self.wid,'economy',lambda c:(seen.append(c['tick_key']) or {'status':'PASS'}));r=self.tick();self.assertEqual(seen,['0:0']);self.assertEqual([x for x in r['phases'] if x['phase']=='EXTENSIONS'][0]['detail']['executed'],1)
    def test_extension_order_deterministic(self):
        seen=[];self.orch.attach_extension(self.wid,'z',lambda c:(seen.append('z') or {}));self.orch.attach_extension(self.wid,'a',lambda c:(seen.append('a') or {}));self.tick();self.assertEqual(seen,['a','z'])
    def test_offline_extension_requires_safe(self):
        with self.assertRaises(ValidationError):self.orch.attach_extension(self.wid,'bad',lambda c:{},modes={'ROUTINE_OFFLINE'})
    def test_safe_offline_extension_runs(self):
        seen=[];self.orch.attach_extension(self.wid,'routine',lambda c:(seen.append(1) or {'status':'PASS'}),modes={'ROUTINE_OFFLINE'},routine_safe=True);self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE');self.tick();self.assertEqual(seen,[1])
    def test_bind_extension_handler_requires_descriptor(self):
        with self.assertRaises(NotFoundError):self.orch.bind_extension_handler(self.wid,'missing',lambda c:{})
    def test_bind_extension_handler_identity_mismatch_blocked(self):
        def a(c):return {}
        def b(c):return {}
        self.orch.attach_extension(self.wid,'economy',a);self.orch._adapters.clear()
        with self.assertRaises(IntegrityError):self.orch.bind_extension_handler(self.wid,'economy',b)
    def test_nonobject_extension_fails_closed(self):
        self.orch.attach_extension(self.wid,'bad',lambda c:1)
        with self.assertRaises(IntegrityError):self.tick();self.assertEqual(self.rt.get_world(self.wid)['status'],'CORRUPT_BLOCKED')

class IntegrityConcurrencyTests(OrchCase):
    def test_run_chain_two_ticks(self):
        self.orch.run_steps(self.wid,2);self.assertEqual(self.orch.verify_run_chain(self.wid)['status'],'PASS')
    def test_run_corruption_detected(self):
        r=self.tick();self.rt.conn.execute("UPDATE orchestration_runs SET run_json='{}' WHERE run_id=?",(r['run_id'],));self.assertEqual(self.orch.full_integrity_check(self.wid)['status'],'FAIL')
    def test_participant_corruption_detected(self):
        self.rt.conn.execute("UPDATE orchestration_participants SET participant_json='{}' WHERE entity_ref=?",(self.agent['entity_runtime_id'],));self.assertEqual(self.orch.full_integrity_check(self.wid)['status'],'FAIL')
    def test_integrity_guard_blocks_corrupt(self):
        self.rt.conn.execute("UPDATE orchestration_participants SET participant_json='{}' WHERE entity_ref=?",(self.agent['entity_runtime_id'],));self.assertEqual(self.orch.integrity_guard(self.wid)['status'],'FAIL');self.assertEqual(self.rt.get_world(self.wid)['status'],'CORRUPT_BLOCKED')
    def test_same_tick_concurrent_idempotent(self):
        out=[];errs=[]
        def worker():
            try:out.append(self.tick(tick_key='same'))
            except Exception as e:errs.append(e)
        ts=[threading.Thread(target=worker) for _ in range(8)]
        [t.start() for t in ts];[t.join() for t in ts]
        self.assertFalse(errs);self.assertEqual(len({x['run_id'] for x in out}),1);self.assertEqual(self.rt.get_clock(self.wid)['tick'],1)
    def test_paused_clock_blocks_tick(self):
        self.rt.set_clock_state(self.wid,'PAUSED')
        with self.assertRaises(ConflictError):self.tick()
    def test_run_steps_validation(self):
        with self.assertRaises(ValidationError):self.orch.run_steps(self.wid,0)


class AuditSnapshotTests(OrchCase):
    def test_config_snapshot_created(self):
        r=self.tick();row=self.rt.conn.execute("SELECT snapshot_hash FROM orchestration_config_snapshots WHERE run_id=?",(r['run_id'],)).fetchone();self.assertEqual(row['snapshot_hash'],r['config_snapshot_hash'])
    def test_config_snapshot_immutable(self):
        r=self.tick()
        with self.assertRaises(sqlite3.DatabaseError):self.rt.conn.execute("UPDATE orchestration_config_snapshots SET snapshot_json='{}' WHERE run_id=?",(r['run_id'],))
    def test_policy_records_snapshot_before_change(self):
        r=self.tick();old=r['config_snapshot_hash'];self.orch.configure_world(self.wid,{'environment_cadence_ticks':2,'ecology_aggregate_cadence_ticks':1,'integrity_cadence_ticks':1,'full_npc_budget':8,'active_npc_budget':2,'full_ecology_budget':8,'active_ecology_budget':2});self.assertEqual(self.rt.conn.execute("SELECT snapshot_hash FROM orchestration_config_snapshots WHERE run_id=?",(r['run_id'],)).fetchone()['snapshot_hash'],old)
    def test_backpressure_policy_rejects_low_root_capacity(self):
        with self.assertRaises(ValidationError):self.orch.configure_world(self.wid,{'max_roots_per_run':10})
    def test_missing_extension_handler_preflight_blocks_without_run(self):
        self.orch.attach_extension(self.wid,'economy',lambda c:{'status':'PASS'});self.orch._adapters.clear();before=self.rt.conn.execute('SELECT COUNT(*) c FROM orchestration_runs').fetchone()['c']
        with self.assertRaises(ConflictError):self.tick()
        self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM orchestration_runs').fetchone()['c'],before);self.assertEqual(self.rt.get_world(self.wid)['status'],'ACTIVE')

class TimelineIsolationTests(unittest.TestCase):
    def test_two_worlds_isolated(self):
        tmp=tempfile.TemporaryDirectory();db=os.path.join(tmp.name,'x.db');rt=LivingRuntime(db,master_release_path=MASTER)
        try:
            v=IntentValidator(rt);b=AgentBrain(rt,v);s=SocialMemorySystem(rt);e=EcologySystem(rt,v);o=ObjectEnvironmentSystem(rt);c=ConsequenceEngine(rt);orch=WorldSimulationOrchestrator(rt,c,b,v,s,e,o)
            w1=rt.create_world('a',1,ticks_per_day=24);w2=rt.create_world('b',2,ticks_per_day=24);orch.configure_world(w1['world_instance_id'],{'integrity_cadence_ticks':1});orch.configure_world(w2['world_instance_id'],{'integrity_cadence_ticks':1})
            orch.run_tick(w1['world_instance_id']);self.assertEqual(rt.get_clock(w1['world_instance_id'])['tick'],1);self.assertEqual(rt.get_clock(w2['world_instance_id'])['tick'],0);self.assertEqual(orch.full_integrity_check(w2['world_instance_id'])['status'],'PASS')
        finally:rt.close();tmp.cleanup()

if __name__=='__main__':unittest.main()
