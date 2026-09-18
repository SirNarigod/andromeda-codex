import os,sys,json,tempfile,shutil,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from living_runtime import LivingRuntime,new_runtime_id,clock_point
from consequence_engine import ConsequenceEngine
from agent_brain import AgentBrain,IntentValidator
from social_memory import SocialMemorySystem
from ecology_brain import EcologySystem
from object_environment import ObjectEnvironmentSystem
from world_orchestrator import WorldSimulationOrchestrator
from world_systems import WorldSystems
from long_horizon import LongHorizonSimulation
from llm_gateway import ControlledLLMGateway,ScriptedProvider
from atlas_living_bridge import AtlasLivingBridge,AtlasBridgeIntegrityError
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip';OUT=ROOT/'04_REPORTS/STAGE14/STAGE14_CORRUPTION_MATRIX_V1_0.json'
T=tempfile.TemporaryDirectory();base=os.path.join(T.name,'base.db');rt=LivingRuntime(base,master_release_path=MASTER);w=rt.create_world('corrupt',1415,ticks_per_day=24);wid=w['world_instance_id'];val=IntentValidator(rt);brain=AgentBrain(rt,val);social=SocialMemorySystem(rt);eco=EcologySystem(rt,val);obj=ObjectEnvironmentSystem(rt);cons=ConsequenceEngine(rt);orch=WorldSimulationOrchestrator(rt,cons,brain,val,social,eco,obj);ws=WorldSystems(rt);ws.load_master_snapshots(MASTER);ws.bootstrap_world(wid,population_seed=1000);orch.configure_world(wid,{'max_roots_per_run':256});ws.attach_to_orchestrator(orch,wid);lh=LongHorizonSimulation(rt,orch,ws,eco,obj);lh.configure_world(wid)
c=rt.get_clock(wid);a=rt.register_entity(wid,{'state_id':new_runtime_id('state'),'world_instance_id':wid,'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{'name':'A','money':10},'protection':{}});b=rt.register_entity(wid,{'state_id':new_runtime_id('state'),'world_instance_id':wid,'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{'name':'B','money':10},'protection':{}})
social.apply_relationship_delta(wid,a['entity_runtime_id'],b['entity_runtime_id'],{'trust':5},reason='seed');eco.load_master_fauna_snapshots(MASTER);eco.register_species_profile(wid,{'species_ref':'CRI-001','diet':'HERBIVORE','social_structure':'HERD','cognition_mode':'ADAPTIVE','activity_mode':'DIURNAL','range_excursion_allowed':False});eco.register_population(wid,species_ref='CRI-001',territory_ref='TER-011',count=100,carrying_capacity=200,resource_index=80,water_index=80,climate_comfort=80);gw=ControlledLLMGateway(rt,val,social);p=ScriptedProvider();gw.bind_provider(p);gw.register_profile(wid,a['entity_runtime_id'],provider_id=p.provider_id)
# create event+ledger
orch.run_tick(wid,tick_key='seed-orch');lh.begin_offline_session(wid);lh.simulate_offline_days(wid,1,request_key='seed-off');lh.reconcile_and_resume(wid,resume_mode='FULL');rt.close()
results=[]
def case(name,sql,checker,drop=None):
 dst=os.path.join(T.name,name+'.db');shutil.copy2(base,dst);c=sqlite3.connect(dst)
 if drop:
  for tr in drop:c.execute(f'DROP TRIGGER IF EXISTS {tr}')
 c.execute(sql);c.commit();c.close()
 detected=False;detail=None
 try: detected=bool(checker(dst));detail='DETECTED' if detected else 'NOT_DETECTED'
 except Exception as e: detected=True;detail=type(e).__name__+': '+str(e)
 results.append({'case':name,'status':'PASS' if detected else 'FAIL','detail':detail})
def runtime_fail(path):
 r=LivingRuntime(path,master_release_path=MASTER);x=r.full_integrity_check(wid);r.close();return x['status']=='FAIL'
def social_fail(path):
 r=LivingRuntime(path,master_release_path=MASTER);s=SocialMemorySystem(r);x=s.full_integrity_check(wid);r.close();return x['status']=='FAIL'
def eco_fail(path):
 r=LivingRuntime(path,master_release_path=MASTER);v=IntentValidator(r);e=EcologySystem(r,v);x=e.full_integrity_check(wid);r.close();return x['status']=='FAIL'
def ws_fail(path):
 r=LivingRuntime(path,master_release_path=MASTER);s=WorldSystems(r);x=s.full_integrity_check(wid);r.close();return x['status']=='FAIL'
def orch_fail(path):
 r=LivingRuntime(path,master_release_path=MASTER);v=IntentValidator(r);o=WorldSimulationOrchestrator(r,ConsequenceEngine(r),AgentBrain(r,v),v,SocialMemorySystem(r),EcologySystem(r,v),ObjectEnvironmentSystem(r));x=o.full_integrity_check(wid);r.close();return x['status']=='FAIL'
def lh_fail(path):
 r=LivingRuntime(path,master_release_path=MASTER);v=IntentValidator(r);e=EcologySystem(r,v);ob=ObjectEnvironmentSystem(r);o=WorldSimulationOrchestrator(r,ConsequenceEngine(r),AgentBrain(r,v),v,SocialMemorySystem(r),e,ob);s=WorldSystems(r);l=LongHorizonSimulation(r,o,s,e,ob);x=l.full_integrity_check(wid);r.close();return x['status']=='FAIL'
def llm_fail(path):
 r=LivingRuntime(path,master_release_path=MASTER);v=IntentValidator(r);g=ControlledLLMGateway(r,v,SocialMemorySystem(r));x=g.full_integrity_check(wid);r.close();return x['status']=='FAIL'
def atlas_fail(path):
 try:
  b=AtlasLivingBridge(path,MASTER);b.export_projection(wid,role='ADMIN');b.close();return False
 except AtlasBridgeIntegrityError:return True
case('entity_state_hash',"UPDATE entity_states SET state_hash='bad' WHERE world_instance_id=(SELECT world_instance_id FROM worlds LIMIT 1) LIMIT 1",runtime_fail)
case('event_hash',"UPDATE events SET event_hash='bad' WHERE world_instance_id=(SELECT world_instance_id FROM worlds LIMIT 1) LIMIT 1",runtime_fail,drop=['events_no_update'])
case('causal_ledger_hash',"UPDATE causal_ledger SET ledger_hash='bad' WHERE world_instance_id=(SELECT world_instance_id FROM worlds LIMIT 1) LIMIT 1",runtime_fail,drop=['ledger_no_update'])
case('social_relationship_hash',"UPDATE relationships_current SET relationship_hash='bad' LIMIT 1",social_fail)
case('ecology_population_hash',"UPDATE ecology_populations_current SET population_hash='bad' LIMIT 1",eco_fail)
case('world_system_binding_hash',"UPDATE world_system_bindings SET binding_hash='bad' LIMIT 1",ws_fail)
case('orchestrator_run_hash',"UPDATE orchestration_runs SET run_hash='bad' LIMIT 1",orch_fail,drop=['orchestration_run_no_update'])
case('long_horizon_segment_hash',"UPDATE long_horizon_segments SET segment_hash='bad' LIMIT 1",lh_fail,drop=['long_segment_no_update'])
case('llm_profile_hash',"UPDATE llm_agent_profiles SET profile_hash='bad' LIMIT 1",llm_fail,drop=['llm_profile_no_update'])
case('atlas_state_hash',"UPDATE entity_states SET state_hash='bad' LIMIT 1",atlas_fail)
failed=[x for x in results if x['status']!='PASS'];report={'record_id':'STAGE14-CORRUPTION-MATRIX-V1.0','status':'PASS' if not failed else 'FAIL','cases':len(results),'detected':len(results)-len(failed),'missed':len(failed),'results':results};OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False));T.cleanup();raise SystemExit(0 if not failed else 1)
