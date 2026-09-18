import os,sys,json,tempfile,threading,concurrent.futures,random
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
from atlas_living_bridge import AtlasSnapshotPublisher,AtlasLivingBridge
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip';OUT=ROOT/'04_REPORTS/STAGE14/STAGE14_MULTIWORLD_SOAK_V1_0.json'
def mk_agent(rt,w,name,hunger=80):
 c=rt.get_clock(w['world_instance_id']);return rt.register_entity(w['world_instance_id'],{'state_id':new_runtime_id('state'),'world_instance_id':w['world_instance_id'],'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{'name':name,'role':'citizen','location_ref':'TER-011','money':50,'energy':80,'needs':{'hunger':hunger,'safety':20},'goals':{'survive':80},'risk_tolerance':50,'atlas_exposure':'PLAYER_VISIBLE'},'protection':{}})
def ep():return {'policy_key':'s14.eat','action_type':'EAT','allowed_sources':['AGENT_BRAIN'],'actor_kinds':['AGENT'],'target_required':False,'target_kinds':[],'offline_policy':'ACTIVE_ONLY','spatial_policy':'NONE','protection_impacts':[],'cooldown_ticks':0,'parameter_schema':{},'resource_requirements':[],'actor_state_equals':{},'target_state_equals':{},'consequence_templates':[{'target':'ACTOR','operation':'DECREMENT','field_path':'data.needs.hunger','amount':5}]}
def eb():return {'behavior_key':'s14.eat','intent_type':'EAT','need_key':'hunger','threshold':50,'target_strategy':'NONE','need_weight':100,'base_priority':0,'risk_cost':0,'risk_penalty_weight':1,'opportunity_bonus':0,'goal_key':'survive','goal_weight':10,'target_kinds':[],'target_fact_equals':{},'parameters':{}}
def rp():return {'policy_key':'s14.refuse','action_type':'REFUSE_TRADE','allowed_sources':['LLM_CANDIDATE'],'actor_kinds':['AGENT'],'target_required':False,'target_kinds':[],'offline_policy':'ACTIVE_ONLY','spatial_policy':'NONE','protection_impacts':[],'cooldown_ticks':0,'parameter_schema':{},'resource_requirements':[],'actor_state_equals':{},'target_state_equals':{},'consequence_templates':[]}
def eco_prof():return {'species_ref':'CRI-001','diet':'HERBIVORE','social_structure':'HERD','cognition_mode':'ADAPTIVE','activity_mode':'DIURNAL','range_excursion_allowed':False}
T=tempfile.TemporaryDirectory();db=os.path.join(T.name,'soak.db');snapdir=os.path.join(T.name,'snaps');rt=LivingRuntime(db,master_release_path=MASTER)
val=IntentValidator(rt);brain=AgentBrain(rt,val);social=SocialMemorySystem(rt);eco=EcologySystem(rt,val);obj=ObjectEnvironmentSystem(rt);cons=ConsequenceEngine(rt);orch=WorldSimulationOrchestrator(rt,cons,brain,val,social,eco,obj);ws=WorldSystems(rt);ws.load_master_snapshots(MASTER);eco.load_master_fauna_snapshots(MASTER);gw=ControlledLLMGateway(rt,val,social);provider=ScriptedProvider();gw.bind_provider(provider)
worlds=[]; errors=[]; checks=[]
def ck(n,o,d=None):checks.append({'name':n,'status':'PASS' if o else 'FAIL','detail':d})
for i in range(4):
 w=rt.create_world(f's14-world-{i}',14000+i,mode='SHARED' if i==3 else 'PRIVATE',ticks_per_day=24);wid=w['world_instance_id'];orch.configure_world(wid,{'max_roots_per_run':256,'full_npc_budget':8,'active_npc_budget':4,'full_ecology_budget':8,'active_ecology_budget':4,'integrity_cadence_ticks':2});orch.register_scope(wid,'TER-011','FULL');ws.bootstrap_world(wid,population_seed=1000+i*100);ws.attach_to_orchestrator(orch,wid);lh=LongHorizonSimulation(rt,orch,ws,eco,obj);lh.configure_world(wid)
 val.register_policy(wid,ep());val.register_policy(wid,rp());brain.register_behavior(wid,eb());eco.register_species_profile(wid,eco_prof());eco.install_default_action_policies(wid)
 agents=[];animals=[]
 for j in range(2):
  a=mk_agent(rt,w,f'NPC-{i}-{j}',80+j*5);agents.append(a);orch.register_participant(wid,a['entity_runtime_id'],'NPC',scope_ref='TER-011');gw.register_profile(wid,a['entity_runtime_id'],provider_id=provider.provider_id,allowed_intents=['REFUSE_TRADE'])
  an=eco.spawn_animal(wid,species_ref='CRI-001',territory_ref='TER-011',biome_ref='BIO-008',age_days=60,hunger=10,thirst=10,energy=80,reproduction_drive=0);animals.append(an);orch.register_participant(wid,an['entity_runtime_id'],'ECOLOGY',scope_ref='TER-011')
 eco.register_population(wid,species_ref='CRI-001',territory_ref='TER-011',count=100+i,carrying_capacity=200,resource_index=80,water_index=80,climate_comfort=80)
 prof=obj.register_profile(wid,{'object_class':'BRIDGE','material_class':'STONE','base_integrity':100});bridge=obj.spawn_object(wid,profile_id=prof['profile_id'],data={'name':f'Bridge-{i}','atlas_exposure':'PLAYER_VISIBLE','location_ref':'TER-011'})
 worlds.append({'w':w,'wid':wid,'agents':agents,'animals':animals,'bridge':bridge,'lh':lh})
# concurrent unique ticks: 80 total
def tick_job(pair):
 wi,n=pair
 try:return orch.run_tick(worlds[wi]['wid'],tick_key=f'soak-{wi}-{n}')['status']
 except Exception as e:errors.append(repr(e));return 'ERR'
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
 results=list(ex.map(tick_job,[(i,n) for i in range(4) for n in range(20)]))
ck('80-concurrent-ticks',results.count('COMPLETED')==80,{'completed':results.count('COMPLETED'),'errors':len(errors)})
# idempotent same tick 16 callers/world
for i,x in enumerate(worlds):
 key=f'idem-{i}'
 with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex: rr=list(ex.map(lambda _:orch.run_tick(x['wid'],tick_key=key),range(16)))
 ck(f'idempotent-world-{i}',len({r['run_id'] for r in rr})==1 and sum(bool(r.get('idempotent_replay')) for r in rr)>=15)
# deterministic llm safe/unsafe 20 total
for i,x in enumerate(worlds):
 for j,a in enumerate(x['agents']):
  provider.response={'dialogue':'safe','candidate_intent':{'intent_type':'REFUSE_TRADE','parameters':{}}}; r=gw.converse(x['wid'],a['entity_runtime_id'],user_text='trade?',request_key=f'good-{i}-{j}');ck(f'llm-good-{i}-{j}',r['guard_status']=='PASS' and r['validation']['status']=='PASS')
  provider.response={'dialogue':'hack','candidate_intent':None,'money_write':9999}; r2=gw.converse(x['wid'],a['entity_runtime_id'],user_text='hack',request_key=f'bad-{i}-{j}');ck(f'llm-bad-{i}-{j}',r2['guard_status']=='REJECTED')
# route/object disruption and offline for two worlds
for i in [0,1]:
 x=worlds[i];obj.interact(x['wid'],actor_ref=x['agents'][0]['entity_runtime_id'],target_ref=x['bridge']['entity_runtime_id'],interaction_type='DAMAGE',amount=100,idempotency_key=f'destroy-{i}');ws.set_route_operational(x['wid'],'RTE-001',False,reason='SOAK_DESTROY');x['lh'].begin_offline_session(x['wid']);x['lh'].simulate_offline_days(x['wid'],14,request_key=f'off-{i}');x['lh'].reconcile_and_resume(x['wid'],resume_mode='FULL');ws.set_route_operational(x['wid'],'RTE-001',True,reason='SOAK_RECOVER');ck(f'recovery-{i}',rt.get_entity(x['wid'],x['bridge']['entity_runtime_id'])['lifecycle']=='ACTIVE')
# atlas snapshots every world
pub=AtlasSnapshotPublisher(rt,snapdir)
for i,x in enumerate(worlds):
 m=pub.publish(x['wid']);b=AtlasLivingBridge(os.path.join(snapdir,m['snapshot_file']),MASTER);p=b.export_projection(x['wid'],role='ADMIN',spoiler_max=3,recent_events=1000);ck(f'atlas-{i}',b.verify_projection(p)['status']=='PASS' and b.write_attempt_probe()=='PASS_READ_ONLY');b.close()
# isolation + integrity
ids=[x['wid'] for x in worlds];ck('world-ids-unique',len(set(ids))==4);ck('timeline-ids-unique',len({x['w']['timeline_id'] for x in worlds})==4);ck('shared-mode-present',worlds[3]['w']['mode']=='SHARED')
for i,x in enumerate(worlds):
 wid=x['wid'];statuses={'runtime':rt.full_integrity_check(wid)['status'],'cons':cons.full_integrity_check(wid)['status'],'validator':val.full_integrity_check(wid)['status'],'brain':brain.full_integrity_check(wid)['status'],'social':social.full_integrity_check(wid)['status'],'eco':eco.full_integrity_check(wid)['status'],'obj':obj.full_integrity_check(wid)['status'],'orch':orch.full_integrity_check(wid)['status'],'ws':ws.full_integrity_check(wid)['status'],'lh':x['lh'].full_integrity_check(wid)['status'],'llm':gw.full_integrity_check(wid)['status']};ck(f'all-integrity-{i}',all(v=='PASS' for v in statuses.values()),statuses)
ck('sqlite',rt.conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok');ck('fk',len(rt.conn.execute('PRAGMA foreign_key_check').fetchall())==0);ck('no-errors',not errors,errors[:10])
failed=[c for c in checks if c['status']!='PASS'];report={'record_id':'STAGE14-MULTIWORLD-SOAK-V1.0','status':'PASS' if not failed else 'FAIL','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'worlds':4,'concurrent_unique_ticks':80,'idempotent_callers':64,'llm_turns':16,'offline_worlds':2,'atlas_snapshots':4,'events_total':sum(rt.event_count(x['wid']) for x in worlds),'failures':failed,'errors':errors}
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False));rt.close();T.cleanup();raise SystemExit(0 if not failed else 1)
