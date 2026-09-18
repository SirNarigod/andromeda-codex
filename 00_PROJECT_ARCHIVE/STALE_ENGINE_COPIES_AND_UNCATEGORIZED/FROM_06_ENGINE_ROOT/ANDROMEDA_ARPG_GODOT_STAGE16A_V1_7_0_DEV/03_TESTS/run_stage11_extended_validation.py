import json, os, tempfile, time, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'01_RUNTIME'))
from living_runtime import LivingRuntime
from consequence_engine import ConsequenceEngine
from agent_brain import AgentBrain, IntentValidator
from social_memory import SocialMemorySystem
from ecology_brain import EcologySystem
from object_environment import ObjectEnvironmentSystem
from world_orchestrator import WorldSimulationOrchestrator
from world_systems import WorldSystems
from long_horizon import LongHorizonSimulation

MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'; HERB='CRI-001'; HOME='TER-011'
checks=[]
def ck(name,cond,detail=None):checks.append({'name':name,'status':'PASS' if cond else 'FAIL','detail':detail});return cond

def stack(db, timeline, seed=1, ecology=True):
 rt=LivingRuntime(db,master_release_path=MASTER);w=rt.create_world(timeline,seed,ticks_per_day=24);wid=w['world_instance_id'];val=IntentValidator(rt);brain=AgentBrain(rt,val);social=SocialMemorySystem(rt);eco=EcologySystem(rt,val);obj=ObjectEnvironmentSystem(rt);cons=ConsequenceEngine(rt);orch=WorldSimulationOrchestrator(rt,cons,brain,val,social,eco,obj);orch.configure_world(wid,{'max_roots_per_run':256,'integrity_cadence_ticks':24,'extension_budget':4});ws=WorldSystems(rt);ws.load_master_snapshots(MASTER);ws.bootstrap_world(wid,population_seed=1000)
 if ecology:
  eco.load_master_fauna_snapshots();eco.register_species_profile(wid,{'species_ref':HERB,'diet':'HERBIVORE','social_structure':'HERD','cognition_mode':'ADAPTIVE','activity_mode':'DIURNAL','range_excursion_allowed':False});eco.install_default_action_policies(wid);eco.register_population(wid,species_ref=HERB,territory_ref=HOME,count=100,carrying_capacity=200)
 lh=LongHorizonSimulation(rt,orch,ws,eco,obj);lh.configure_world(wid);return rt,wid,val,brain,social,eco,obj,cons,orch,ws,lh

def norm_ws(ws,wid):
 out={}
 for kind in ['ECONOMIC_FLOW','POPULATION_AGGREGATE','FACTION_RUNTIME','ROUTE_RUNTIME']:
  vals=[]
  for e in ws._entities(wid,kind):vals.append((e.get('canonical_ref') or e['data'].get('source_ref'),e['data']))
  out[kind]=vals
 return out

t0=time.time();tmp=tempfile.TemporaryDirectory()
try:
 # Horizon matrix.
 for i,days in enumerate([1,7,30,180,365,3650]):
  db=os.path.join(tmp.name,f'h{i}.db');rt,wid,_,_,_,eco,obj,_,orch,ws,lh=stack(db,f'h-{days}',100+i,ecology=(days!=3650));s=lh.begin_offline_session(wid);before=lh._decision_counts(wid);r=lh.simulate_offline_days(wid,days,request_key=f'd{days}');after=lh._decision_counts(wid);rec=lh.reconcile_and_resume(wid)
  ck(f'horizon_{days}_clock',rt.get_clock(wid)['day']==days,rt.get_clock(wid));ck(f'horizon_{days}_no_individual',before==after,{'before':before,'after':after});ck(f'horizon_{days}_segments_chain',lh.verify_segment_chain(s['session_id'])['status']=='PASS');ck(f'horizon_{days}_integrity',all(x['status']=='PASS' for x in [rt.full_integrity_check(wid),orch.full_integrity_check(wid),ws.full_integrity_check(wid),lh.full_integrity_check(wid)]));ck(f'horizon_{days}_reconciled',rec['integrity']=='PASS' and rt.get_world(wid)['simulation_mode']=='FULL');ck(f'horizon_{days}_backlog',rec['consequence_backlog_after']==0)
  for p in ws._entities(wid,'POPULATION_AGGREGATE'):ck(f'horizon_{days}_pop_nonnegative_{p["entity_runtime_id"]}',p['data']['count']>=0)
  for f in ws._entities(wid,'ECONOMIC_FLOW'):ck(f'horizon_{days}_price_bounds_{f["entity_runtime_id"]}',.5*f['data']['base_price']<=f['data']['price']<=3*f['data']['base_price'])
  rt.close()
 # Determinism: two independent worlds with same inputs/duration.
 a=stack(os.path.join(tmp.name,'detA.db'),'detA',777,ecology=True);b=stack(os.path.join(tmp.name,'detB.db'),'detB',777,ecology=True)
 for st in [a,b]:st[-1].begin_offline_session(st[1]);st[-1].simulate_offline_days(st[1],365,request_key='year')
 ck('deterministic_world_system_state',norm_ws(a[-2],a[1])==norm_ws(b[-2],b[1]))
 ck('deterministic_ecology_count',a[5].get_population(a[1],HERB,HOME)['count']==b[5].get_population(b[1],HERB,HOME)['count'])
 ck('deterministic_clock',a[0].get_clock(a[1])['day']==b[0].get_clock(b[1])['day']==365)
 for st in [a,b]:st[0].close()
 # Recovery exact boundary and periodic snapshots.
 rt,wid,_,_,_,eco,obj,_,orch,ws,lh=stack(os.path.join(tmp.name,'recovery.db'),'rec',88,ecology=False);prof=obj.register_profile(wid,{'object_class':'BRIDGE','material_class':'STONE','base_integrity':100});o=obj.spawn_object(wid,profile_id=prof['profile_id']);obj.interact(wid,actor_ref='SYSTEM_RECONCILIATION',target_ref=o['entity_runtime_id'],interaction_type='DAMAGE',amount=100,routine_safe=True);s=lh.begin_offline_session(wid);lh.simulate_offline_days(wid,90,request_key='90');to_days=[r['to_day'] for r in rt.conn.execute('SELECT to_day FROM long_horizon_segments WHERE session_id=? ORDER BY sequence',(s['session_id'],)).fetchall()];ck('recovery_boundary_day7',7 in to_days,to_days);ck('snapshot_boundary_day30',rt.conn.execute("SELECT COUNT(*) c FROM temporal_snapshots WHERE session_id=? AND day=30",(s['session_id'],)).fetchone()['c']==1);ck('snapshot_boundary_day60',rt.conn.execute("SELECT COUNT(*) c FROM temporal_snapshots WHERE session_id=? AND day=60",(s['session_id'],)).fetchone()['c']==1);ck('snapshot_boundary_day90',rt.conn.execute("SELECT COUNT(*) c FROM temporal_snapshots WHERE session_id=? AND day=90",(s['session_id'],)).fetchone()['c']==1);ck('structure_recovered',rt.get_entity(wid,o['entity_runtime_id'])['lifecycle']=='ACTIVE');rt.close()
finally:tmp.cleanup()
failed=[x for x in checks if x['status']!='PASS'];out={'record_id':'STAGE11-EXTENDED-VALIDATION-V1.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','seconds':round(time.time()-t0,3),'failures':failed}
Path(__file__).resolve().parents[1].joinpath('04_REPORTS/STAGE11_EXTENDED_VALIDATION_V1_0.json').write_text(json.dumps(out,indent=2,ensure_ascii=False));print(json.dumps(out,indent=2));raise SystemExit(0 if not failed else 1)
