import os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'01_RUNTIME'))

from living_runtime import LivingRuntime,new_runtime_id,clock_point,ConflictError
from world_systems import WorldSystems
from agent_brain import IntentValidator
from ecology_brain import EcologySystem
from social_memory import SocialMemorySystem
from domain_integration import DomainIntegrationHub
from object_environment import ObjectEnvironmentSystem
from mobility_biology import MobilityBiologySystem

MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
PRED='CRI-002'; HOME='TER-011'; BIO_A='BIO-008'; BIO_B='BIO-002'

def profile(species=PRED):
    return {'species_ref':species,'diet':'CARNIVORE','social_structure':'PACK','cognition_mode':'ADAPTIVE','activity_mode':'DIURNAL','range_excursion_allowed':False}

def agent(rt,wid,loc='CIT-001',clearance=0):
    w=rt.get_world(wid);c=w['clock_state'];s={'state_id':new_runtime_id('state'),'world_instance_id':wid,'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{'name':'Traveler','location_ref':loc,'clearance_level':clearance},'protection':{}}
    return rt.register_entity(wid,s)

class MobilityBiologyV11(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=os.path.join(self.tmp.name,'m.db')
        self.rt=LivingRuntime(self.db,master_release_path=MASTER);self.w=self.rt.create_world('mobility-biology',1501,ticks_per_day=24);self.wid=self.w['world_instance_id']
        self.ws=WorldSystems(self.rt);self.ws.load_master_snapshots(MASTER);self.ws.bootstrap_world(self.wid,population_seed=1000)
        self.val=IntentValidator(self.rt);self.eco=EcologySystem(self.rt,self.val);self.eco.load_master_fauna_snapshots(MASTER);self.eco.register_species_profile(self.wid,profile());self.eco.install_default_action_policies(self.wid)
        self.social=SocialMemorySystem(self.rt);self.hub=DomainIntegrationHub(self.rt,self.eco,self.social);self.obj=ObjectEnvironmentSystem(self.rt)
        self.mb=MobilityBiologySystem(self.rt,self.ws,self.eco,domain_hub=self.hub)
    def tearDown(self):
        try:self.mb.detach();self.hub.detach();self.rt.close()
        except:pass
        self.tmp.cleanup()
    def animal(self,biome=BIO_A,**kw):
        args={'species_ref':PRED,'territory_ref':HOME,'biome_ref':biome,'age_days':30,'hunger':20,'thirst':20,'energy':80,'reproduction_drive':0};args.update(kw);return self.eco.spawn_animal(self.wid,**args)
    def test_route_plan_uses_master_distance_and_no_fabricated_route(self):
        a=agent(self.rt,self.wid);p=self.mb.plan_travel(self.wid,a['entity_runtime_id'],'LOC-001')
        self.assertEqual(p['route_ids'],['RTE-001']);self.assertEqual(p['distance_km'],384.0);self.assertGreater(p['duration_ticks'],0);self.assertIn('MASTER',p['legs'][0]['speed_basis'])
    def test_start_travel_does_not_teleport_and_arrival_moves(self):
        a=agent(self.rt,self.wid);t=self.mb.start_travel(self.wid,a['entity_runtime_id'],'LOC-001');state=self.rt.get_entity(self.wid,a['entity_runtime_id'])
        self.assertEqual(state['data']['location_ref'],'CIT-001');self.assertEqual(state['data']['travel']['status'],'IN_TRANSIT')
        self.rt.advance_ticks(self.wid,t['duration_ticks']);r=self.mb.process_arrivals(self.wid);state=self.rt.get_entity(self.wid,a['entity_runtime_id'])
        self.assertEqual(r['results'][0]['status'],'ARRIVED');self.assertEqual(state['data']['location_ref'],'LOC-001');self.assertEqual(state['data']['travel']['status'],'ARRIVED')
    def test_route_closure_blocks_due_arrival(self):
        a=agent(self.rt,self.wid);t=self.mb.start_travel(self.wid,a['entity_runtime_id'],'LOC-001');self.ws.set_route_operational(self.wid,'RTE-001',False)
        self.rt.advance_ticks(self.wid,t['duration_ticks']);r=self.mb.process_arrivals(self.wid);state=self.rt.get_entity(self.wid,a['entity_runtime_id'])
        self.assertEqual(r['results'][0]['status'],'BLOCKED');self.assertEqual(state['data']['location_ref'],'CIT-001');self.assertEqual(state['data']['travel']['status'],'BLOCKED')
    def test_unresolved_path_is_blocked_not_fabricated(self):
        a=agent(self.rt,self.wid)
        with self.assertRaises(ConflictError):self.mb.plan_travel(self.wid,a['entity_runtime_id'],BIO_A)
    def test_access_level_blocks_restricted_route_without_clearance(self):
        a=agent(self.rt,self.wid,'LOC-001',0)
        with self.assertRaises(ConflictError):self.mb.plan_travel(self.wid,a['entity_runtime_id'],'LOC-013')
        b=agent(self.rt,self.wid,'LOC-001',3);p=self.mb.plan_travel(self.wid,b['entity_runtime_id'],'LOC-013');self.assertEqual(p['route_ids'],['RTE-002'])
    def test_flee_changes_to_alternate_canonical_biome_once(self):
        a=self.animal(BIO_A);intent=self.val.submit_intent(self.wid,actor_ref=a['entity_runtime_id'],intent_type='ECO_FLEE',parameters={},source='AGENT_BRAIN');self.assertEqual(self.val.validate_intent(intent['intent_id'])['status'],'PASS');self.val.execute_validated_intent(intent['intent_id'])
        r=self.mb.drain_movement(self.wid);state=self.rt.get_entity(self.wid,a['entity_runtime_id']);self.assertEqual(state['data']['ecology']['biome_ref'],BIO_B);self.assertEqual(r['status'],'PASS')
        ver=state['version'];self.mb.drain_movement(self.wid);self.assertEqual(self.rt.get_entity(self.wid,a['entity_runtime_id'])['version'],ver)
    def test_patrol_changes_runtime_micro_position(self):
        a=self.animal();intent=self.val.submit_intent(self.wid,actor_ref=a['entity_runtime_id'],intent_type='ECO_PATROL',parameters={},source='AGENT_BRAIN');self.val.validate_intent(intent['intent_id']);self.val.execute_validated_intent(intent['intent_id']);self.mb.drain_movement(self.wid)
        pos=self.rt.get_entity(self.wid,a['entity_runtime_id'])['data']['ecology']['micro_position'];self.assertEqual(pos['space_ref'],BIO_A);self.assertEqual(pos['authority'],'RUNTIME_MICROSPACE_ZERO_CANON_IMPACT')
    def test_24_biology_ticks_age_and_metabolism_progress(self):
        a=self.animal();before=self.rt.get_entity(self.wid,a['entity_runtime_id'])
        for i in range(24):
            self.rt.advance_ticks(self.wid,1);self.mb.biology_tick(self.wid,tick_key=f'day0:{i}')
        after=self.rt.get_entity(self.wid,a['entity_runtime_id']);self.assertEqual(after['data']['age_days'],before['data']['age_days']+1);self.assertGreater(after['data']['ecology']['hunger'],before['data']['ecology']['hunger']);self.assertGreater(after['data']['ecology']['thirst'],before['data']['ecology']['thirst'])
    def test_hot_environment_increases_thirst_rate(self):
        hot=self.animal(BIO_A);neutral=self.animal(BIO_B);self.obj.create_environment_zone(self.wid,canonical_ref=BIO_A,temperature=42,humidity=20)
        self.mb.biology_tick(self.wid,tick_key='hot-compare');h=self.rt.get_entity(self.wid,hot['entity_runtime_id']);n=self.rt.get_entity(self.wid,neutral['entity_runtime_id']);self.assertGreater(h['data']['ecology']['thirst'],n['data']['ecology']['thirst'])
    def test_biological_death_reconciles_population(self):
        self.eco.register_population(self.wid,species_ref=PRED,territory_ref=HOME,count=2,carrying_capacity=20);a=self.animal(hunger=100,thirst=100)
        w=self.rt.get_world(self.wid);c=w['clock_state'];act={'action_id':new_runtime_id('action'),'intent_id':new_runtime_id('intent'),'world_instance_id':self.wid,'timeline_id':w['timeline_id'],'actor_ref':'SYSTEM_RECONCILIATION','action_type':'TEST_STRESS','parameters':{},'precondition_snapshot':{'entity_versions':{a['entity_runtime_id']:a['version']}},'idempotency_key':'stress-seed','created_at':clock_point(c['day'],c['tick']),'status':'SCHEDULED','source':'SYSTEM_RECONCILIATION','execution_class':'ROUTINE_SAFE'}
        self.rt.apply_action(self.wid,act,[{'target_ref':a['entity_runtime_id'],'operation':'SET','field_path':'data.biology','value':{'age_fraction_days':0.0,'stress':99.5,'policy':'TEST'},'priority':0,'kind':'DIRECT'}])
        self.mb.biology_tick(self.wid,tick_key='lethal');state=self.rt.get_entity(self.wid,a['entity_runtime_id']);self.assertEqual(state['lifecycle'],'DEAD');self.assertEqual(self.eco.get_population(self.wid,PRED,HOME)['count'],1)
    def test_biology_tick_is_idempotent(self):
        a=self.animal();r1=self.mb.biology_tick(self.wid,tick_key='same');v1=self.rt.get_entity(self.wid,a['entity_runtime_id'])['version'];r2=self.mb.biology_tick(self.wid,tick_key='same');v2=self.rt.get_entity(self.wid,a['entity_runtime_id'])['version'];self.assertEqual(v1,v2);self.assertTrue(r2['results'][0].get('idempotent_replay'))
    def test_integrity_after_mobility_and_biology(self):
        a=self.animal();intent=self.val.submit_intent(self.wid,actor_ref=a['entity_runtime_id'],intent_type='ECO_PATROL',parameters={},source='AGENT_BRAIN');self.val.validate_intent(intent['intent_id']);self.val.execute_validated_intent(intent['intent_id']);self.mb.drain_movement(self.wid);self.mb.biology_tick(self.wid,tick_key='integrity');rep=self.mb.full_integrity_check(self.wid);self.assertEqual(rep['status'],'PASS',rep)

if __name__=='__main__':unittest.main()
