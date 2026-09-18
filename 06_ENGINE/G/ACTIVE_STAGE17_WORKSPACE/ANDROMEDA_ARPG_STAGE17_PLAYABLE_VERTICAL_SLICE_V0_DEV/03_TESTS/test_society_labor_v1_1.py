import os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'01_RUNTIME'))

from living_runtime import LivingRuntime,new_runtime_id,clock_point,ConflictError
from world_systems import WorldSystems
from commerce_system import CommerceSystem
from social_memory import SocialMemorySystem
from agent_brain import IntentValidator
from ecology_brain import EcologySystem
from domain_integration import DomainIntegrationHub
from society_labor import SocietyLaborSystem

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

def mk_agent(rt,wid,loc,name='Agent'):
    w=rt.get_world(wid);c=w['clock_state'];s={'state_id':new_runtime_id('state'),'world_instance_id':wid,'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{'name':name,'location_ref':loc},'protection':{}}
    return rt.register_entity(wid,s)

class SocietyLaborV11(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=os.path.join(self.tmp.name,'s.db');self.rt=LivingRuntime(self.db,master_release_path=MASTER);self.w=self.rt.create_world('society-labor',1601,ticks_per_day=24);self.wid=self.w['world_instance_id']
        self.ws=WorldSystems(self.rt);self.ws.load_master_snapshots(MASTER);self.ws.bootstrap_world(self.wid,population_seed=1000)
        self.cs=CommerceSystem(self.rt,self.ws);self.cs.load_catalog(MASTER);self.social=SocialMemorySystem(self.rt);self.val=IntentValidator(self.rt);self.eco=EcologySystem(self.rt,self.val);self.eco.load_master_fauna_snapshots(MASTER);self.hub=DomainIntegrationHub(self.rt,self.eco,self.social)
        self.sl=SocietyLaborSystem(self.rt,self.ws,self.social,self.cs,domain_hub=self.hub);self.profs=self.sl.load_professions(MASTER)
    def tearDown(self):
        try:self.sl.detach();self.hub.detach();self.rt.close()
        except:pass
        self.tmp.cleanup()
    def emit_combat(self,attacker,target,witness=None,lethal=True,key='combat-test'):
        w=self.rt.get_world(self.wid);c=w['clock_state'];a={'action_id':new_runtime_id('action'),'intent_id':new_runtime_id('intent'),'world_instance_id':self.wid,'timeline_id':w['timeline_id'],'actor_ref':attacker['entity_runtime_id'],'action_type':'COMBAT_RESOLVED','parameters':{'target_ref':target['entity_runtime_id'],'lethal':lethal},'precondition_snapshot':{'entity_versions':{attacker['entity_runtime_id']:attacker['version'],target['entity_runtime_id']:target['version']}},'idempotency_key':key,'created_at':clock_point(c['day'],c['tick']),'status':'SCHEDULED','source':'ACTION','execution_class':'ACTIVE_ONLY'}
        return self.rt.apply_action(self.wid,a,[{'target_ref':target['entity_runtime_id'],'operation':'SET','field_path':'data.last_combat_test','value':key,'priority':0,'kind':'DIRECT'}])
    def test_profession_catalog_loads_all_91(self):
        self.assertEqual(self.profs['count'],91);p=self.sl.profession('JOB-RUR-AGR-001');self.assertEqual(p['name'],'Trabalhador agrícola')
    def test_no_law_profile_means_no_fabricated_crime(self):
        a=mk_agent(self.rt,self.wid,'LOC-001','A');t=mk_agent(self.rt,self.wid,'LOC-001','T');w=mk_agent(self.rt,self.wid,'LOC-001','W');r=self.emit_combat(a,t,w,True,'no-law');self.hub.drain_pending(self.wid);out=self.sl.drain_legal_events(self.wid);self.assertEqual(out['results'][0]['reason'],'NO_RUNTIME_LAW_PROFILE');self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM legal_incidents').fetchone()['c'],0)
    def test_witnessed_homicide_creates_incident_reputation_and_faction_pressure(self):
        self.sl.configure_law_profile(self.wid,'TER-001',authority_faction_ref='FAC-001');a=mk_agent(self.rt,self.wid,'LOC-001','A');t=mk_agent(self.rt,self.wid,'LOC-001','T');w=mk_agent(self.rt,self.wid,'LOC-001','W');self.cs.create_account(self.wid,a['entity_runtime_id'],starting_balance=500)
        self.emit_combat(a,t,w,True,'homicide');self.hub.drain_pending(self.wid);out=self.sl.drain_legal_events(self.wid);inc=out['results'][0]['incident'];self.assertEqual(inc['offense'],'HOMICIDE');self.assertGreaterEqual(inc['evidence']['witness_count'],1);rep=self.social.get_reputation(self.wid,a['entity_runtime_id'],scope_type='FACTION',scope_ref='FAC-001');self.assertLess(rep['score'],0);fac=self.ws._entity_for(self.wid,'FACTION_RUNTIME','FAC-001');self.assertGreater(fac['data']['legal_pressure'],0)
    def test_no_witness_means_no_automatic_conviction(self):
        self.sl.configure_law_profile(self.wid,'TER-001',authority_faction_ref='FAC-001');a=mk_agent(self.rt,self.wid,'LOC-001','A');t=mk_agent(self.rt,self.wid,'LOC-001','T');self.emit_combat(a,t,None,False,'unseen-assault');self.hub.drain_pending(self.wid);out=self.sl.drain_legal_events(self.wid);self.assertEqual(out['results'][0]['reason'],'NO_DIRECT_EVIDENCE');self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM legal_incidents').fetchone()['c'],0)
    def test_fine_payment_transfers_full_amount_to_faction_treasury(self):
        self.sl.configure_law_profile(self.wid,'TER-001',authority_faction_ref='FAC-001');a=mk_agent(self.rt,self.wid,'LOC-001','A');t=mk_agent(self.rt,self.wid,'LOC-001','T');w=mk_agent(self.rt,self.wid,'LOC-001','W');acct=self.cs.create_account(self.wid,a['entity_runtime_id'],starting_balance=500);self.emit_combat(a,t,w,False,'fine');self.hub.drain_pending(self.wid);inc=self.sl.drain_legal_events(self.wid)['results'][0]['incident'];before=self.cs.account_state(self.wid,a['entity_runtime_id'])['balance'];fb=self.ws._entity_for(self.wid,'FACTION_RUNTIME','FAC-001')['data']['treasury'];self.sl.pay_fine(self.wid,inc['incident_id']);after=self.cs.account_state(self.wid,a['entity_runtime_id'])['balance'];fa=self.ws._entity_for(self.wid,'FACTION_RUNTIME','FAC-001')['data']['treasury'];self.assertAlmostEqual(before-after,inc['fine']);self.assertAlmostEqual(fa-fb,inc['fine']);self.assertEqual(self.sl.incident_status(inc['incident_id'])['status'],'PAID')
    def test_wildlife_kill_only_illegal_if_species_is_protected(self):
        self.eco.register_species_profile(self.wid,{'species_ref':'CRI-002','diet':'CARNIVORE','social_structure':'PACK','cognition_mode':'ADAPTIVE','activity_mode':'DIURNAL','range_excursion_allowed':False});self.sl.configure_law_profile(self.wid,'TER-011',protected_species=[]);a=mk_agent(self.rt,self.wid,'BIO-008','A');w=mk_agent(self.rt,self.wid,'BIO-008','W');animal=self.eco.spawn_animal(self.wid,species_ref='CRI-002',territory_ref='TER-011',biome_ref='BIO-008');self.emit_combat(a,animal,w,True,'wildlife');self.hub.drain_pending(self.wid);out=self.sl.drain_legal_events(self.wid);self.assertEqual(out['results'][0]['reason'],'WILDLIFE_NOT_PROTECTED')
    def test_job_offer_respects_canonical_profession_distribution(self):
        emp=self.sl.create_employer(self.wid,'POI-005')
        offer=self.sl.create_job_offer(self.wid,emp['entity_runtime_id'],'JOB-RUR-AGR-001');self.assertEqual(offer['territory_ref'],'TER-011')
        other=self.sl.create_employer(self.wid,'POI-010')
        with self.assertRaises(ConflictError):self.sl.create_job_offer(self.wid,other['entity_runtime_id'],'JOB-RUR-AGR-001')
    def test_accept_job_and_wage_are_transactional(self):
        emp=self.sl.create_employer(self.wid,'POI-005',starting_cash=1000);worker=mk_agent(self.rt,self.wid,'POI-005','Worker');offer=self.sl.create_job_offer(self.wid,emp['entity_runtime_id'],'JOB-RUR-AGR-001');contract=self.sl.accept_job(self.wid,worker['entity_runtime_id'],offer['offer_id']);before=self.cs.account_state(self.wid,worker['entity_runtime_id'])['balance'];eb=self.rt.get_entity(self.wid,emp['entity_runtime_id'])['data']['cash_balance'];out=self.sl.work_shift(self.wid,contract['contract_id']);after=self.cs.account_state(self.wid,worker['entity_runtime_id'])['balance'];ea=self.rt.get_entity(self.wid,emp['entity_runtime_id'])['data']['cash_balance'];self.assertAlmostEqual(after-before,contract['wage_per_shift']);self.assertAlmostEqual(eb-ea,contract['wage_per_shift']);self.assertEqual(out['status'],'PASS')
    def test_labor_tick_connects_worker_to_local_food_flow(self):
        emp=self.sl.create_employer(self.wid,'POI-005');worker=mk_agent(self.rt,self.wid,'POI-005');offer=self.sl.create_job_offer(self.wid,emp['entity_runtime_id'],'JOB-RUR-AGR-001');self.sl.accept_job(self.wid,worker['entity_runtime_id'],offer['offer_id']);r=self.sl.labor_tick(self.wid,tick_key='labor-1');flow=self.ws._entity_for(self.wid,'ECONOMIC_FLOW','FLOW-001');self.assertGreater(flow['data']['labor_factor'],1.0);m=[x for x in r['metrics'] if x['flow_ref']=='FLOW-001'][0];self.assertEqual(m['matched_workers'],1)
    def test_world_economy_consumes_labor_factor(self):
        emp=self.sl.create_employer(self.wid,'POI-005');worker=mk_agent(self.rt,self.wid,'POI-005');offer=self.sl.create_job_offer(self.wid,emp['entity_runtime_id'],'JOB-RUR-AGR-001');self.sl.accept_job(self.wid,worker['entity_runtime_id'],offer['offer_id']);self.sl.labor_tick(self.wid,tick_key='labor-factor');f=self.ws._entity_for(self.wid,'ECONOMIC_FLOW','FLOW-001');self.assertEqual(f['data']['labor_factor'],1.03);before=f['data']['stock'];self.ws.economy_tick(self.wid,'econ-labor','FULL');after=self.ws._entity_for(self.wid,'ECONOMIC_FLOW','FLOW-001')['data']['stock'];self.assertGreater(after,before)
    def test_worker_death_ends_contract_and_reopens_slot(self):
        emp=self.sl.create_employer(self.wid,'POI-005');worker=mk_agent(self.rt,self.wid,'POI-005');offer=self.sl.create_job_offer(self.wid,emp['entity_runtime_id'],'JOB-RUR-AGR-001');contract=self.sl.accept_job(self.wid,worker['entity_runtime_id'],offer['offer_id']);worker=self.rt.get_entity(self.wid,worker['entity_runtime_id']);w=self.rt.get_world(self.wid);c=w['clock_state']
        action={'action_id':new_runtime_id('action'),'intent_id':new_runtime_id('intent'),'world_instance_id':self.wid,'timeline_id':w['timeline_id'],'actor_ref':'SYSTEM_RECONCILIATION','action_type':'TEST_WORKER_DEATH','parameters':{},'precondition_snapshot':{'entity_versions':{worker['entity_runtime_id']:worker['version']}},'idempotency_key':'worker-death','created_at':clock_point(c['day'],c['tick']),'status':'SCHEDULED','source':'SYSTEM_RECONCILIATION','execution_class':'ROUTINE_SAFE'}
        self.rt.apply_action(self.wid,action,[{'target_ref':worker['entity_runtime_id'],'operation':'TRANSITION','field_path':'lifecycle','from':'ACTIVE','value':'DEAD','priority':0,'kind':'DIRECT'}]);r=self.sl.reconcile_employment_lifecycle(self.wid);self.assertEqual(r['ended'],1);self.assertEqual(self.sl._contract(contract['contract_id'])['status'],'ENDED');off=self.sl._offer(offer['offer_id']);self.assertEqual(off['status'],'OPEN');self.assertEqual(off['slots_filled'],0);self.assertEqual(self.rt.get_entity(self.wid,worker['entity_runtime_id'])['data']['employment']['status'],'ENDED')
    def test_arrears_contract_blocks_second_active_employment(self):
        emp=self.sl.create_employer(self.wid,'POI-005',starting_cash=0);worker=mk_agent(self.rt,self.wid,'POI-005');offer=self.sl.create_job_offer(self.wid,emp['entity_runtime_id'],'JOB-RUR-AGR-001');contract=self.sl.accept_job(self.wid,worker['entity_runtime_id'],offer['offer_id'])
        with self.assertRaises(ConflictError):self.sl.work_shift(self.wid,contract['contract_id'])
        self.assertEqual(self.sl._contract(contract['contract_id'])['status'],'ARREARS');emp2=self.sl.create_employer(self.wid,'POI-005');offer2=self.sl.create_job_offer(self.wid,emp2['entity_runtime_id'],'JOB-RUR-AGR-001')
        with self.assertRaises(ConflictError):self.sl.accept_job(self.wid,worker['entity_runtime_id'],offer2['offer_id'])
    def test_full_integrity_after_law_and_labor(self):
        self.sl.configure_law_profile(self.wid,'TER-001',authority_faction_ref='FAC-001');a=mk_agent(self.rt,self.wid,'LOC-001');t=mk_agent(self.rt,self.wid,'LOC-001');w=mk_agent(self.rt,self.wid,'LOC-001');self.emit_combat(a,t,w,False,'integrity-law');self.hub.drain_pending(self.wid);self.sl.drain_legal_events(self.wid);emp=self.sl.create_employer(self.wid,'POI-005');worker=mk_agent(self.rt,self.wid,'POI-005');offer=self.sl.create_job_offer(self.wid,emp['entity_runtime_id'],'JOB-RUR-AGR-001');self.sl.accept_job(self.wid,worker['entity_runtime_id'],offer['offer_id']);self.sl.work_shift(self.wid,self.rt.conn.execute("SELECT contract_id FROM employment_contracts WHERE worker_ref=?",(worker['entity_runtime_id'],)).fetchone()['contract_id']);rep=self.sl.full_integrity_check(self.wid);self.assertEqual(rep['status'],'PASS',rep)

if __name__=='__main__':unittest.main()
