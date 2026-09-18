import json, os, random, tempfile, threading, time, sys
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

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip');HERB='CRI-001';HOME='TER-011'

def make_systems(rt,wid,bootstrap=False,ecology=False):
 val=IntentValidator(rt);brain=AgentBrain(rt,val);social=SocialMemorySystem(rt);eco=EcologySystem(rt,val);obj=ObjectEnvironmentSystem(rt);cons=ConsequenceEngine(rt);orch=WorldSimulationOrchestrator(rt,cons,brain,val,social,eco,obj);ws=WorldSystems(rt);lh=LongHorizonSimulation(rt,orch,ws,eco,obj)
 if bootstrap:
  orch.configure_world(wid,{'max_roots_per_run':256,'integrity_cadence_ticks':24});ws.load_master_snapshots(MASTER);ws.bootstrap_world(wid,population_seed=1000);lh.configure_world(wid)
  if ecology:
   eco.load_master_fauna_snapshots();eco.register_species_profile(wid,{'species_ref':HERB,'diet':'HERBIVORE','social_structure':'HERD','cognition_mode':'ADAPTIVE','activity_mode':'DIURNAL','range_excursion_allowed':False});eco.install_default_action_policies(wid);eco.register_population(wid,species_ref=HERB,territory_ref=HOME,count=100,carrying_capacity=200)
 return val,brain,social,eco,obj,cons,orch,ws,lh

t0=time.time();tmp=tempfile.TemporaryDirectory();fail=[];metrics={}
try:
 # Same-world concurrent retry: all callers must converge to one catch-up.
 db=os.path.join(tmp.name,'same.db');rt=LivingRuntime(db,master_release_path=MASTER);w=rt.create_world('same',123,ticks_per_day=24);wid=w['world_instance_id'];*_,orch,ws,lh=make_systems(rt,wid,bootstrap=True,ecology=False);lh.begin_offline_session(wid)
 outs=[];errs=[]
 def same_worker():
  try:outs.append(lh.simulate_offline_days(wid,30,request_key='same-30'))
  except Exception as e:errs.append(f'{type(e).__name__}:{e}')
 ts=[threading.Thread(target=same_worker) for _ in range(32)]
 for t in ts:t.start()
 for t in ts:t.join()
 metrics['same_request_callers']=32;metrics['same_request_successes']=len(outs);metrics['same_request_replays']=sum(1 for o in outs if o.get('idempotent_replay'));metrics['same_request_errors']=errs;metrics['same_request_day']=rt.get_clock(wid)['day']
 if errs or len(outs)!=32 or rt.get_clock(wid)['day']!=30 or metrics['same_request_replays']!=31:fail.append('SAME_REQUEST_IDEMPOTENCY')
 lh.reconcile_and_resume(wid);rt.close()

 # Restart mid-session and replay after restart.
 db=os.path.join(tmp.name,'restart.db');rt=LivingRuntime(db,master_release_path=MASTER);w=rt.create_world('restart',321,ticks_per_day=24);wid=w['world_instance_id'];*_,orch,ws,lh=make_systems(rt,wid,bootstrap=True,ecology=True);sess=lh.begin_offline_session(wid);first=lh.simulate_offline_days(wid,180,request_key='part1');rt.close()
 rt=LivingRuntime(db,master_release_path=MASTER);*_,orch,ws,lh=make_systems(rt,wid,bootstrap=False,ecology=False);replay=lh.simulate_offline_days(wid,180,request_key='part1');second=lh.simulate_offline_days(wid,185,request_key='part2');rec=lh.reconcile_and_resume(wid)
 metrics['restart_final_day']=rt.get_clock(wid)['day'];metrics['restart_replay']=replay.get('idempotent_replay');metrics['restart_integrity']=lh.full_integrity_check(wid)['status'];metrics['restart_reconciled']=rec['integrity']
 if rt.get_clock(wid)['day']!=365 or not replay.get('idempotent_replay') or metrics['restart_integrity']!='PASS' or rec['integrity']!='PASS':fail.append('RESTART_RECONCILIATION')
 rt.close()

 # Multiworld concurrent long-horizon sessions in one Runtime/SQLite database.
 db=os.path.join(tmp.name,'multi.db');rt=LivingRuntime(db,master_release_path=MASTER);worlds=[];systems={}
 for i in range(6):
  w=rt.create_world(f'mw-{i}',900+i,ticks_per_day=24);wid=w['world_instance_id'];systems[wid]=make_systems(rt,wid,bootstrap=True,ecology=(i%2==0));systems[wid][-1].begin_offline_session(wid);worlds.append(wid)
 durations=[30,180,365,730,1095,3650];errs=[]
 def mw_worker(wid,days):
  try:systems[wid][-1].simulate_offline_days(wid,days,request_key=f'd{days}');systems[wid][-1].reconcile_and_resume(wid)
  except Exception as e:errs.append((wid,type(e).__name__,str(e)))
 ts=[threading.Thread(target=mw_worker,args=(wid,d)) for wid,d in zip(worlds,durations)]
 for t in ts:t.start()
 for t in ts:t.join()
 metrics['multiworld_worlds']=len(worlds);metrics['multiworld_errors']=errs;metrics['multiworld_days']={wid:rt.get_clock(wid)['day'] for wid in worlds};metrics['multiworld_integrity']={wid:systems[wid][-1].full_integrity_check(wid)['status'] for wid in worlds}
 if errs or any(rt.get_clock(wid)['day']!=d for wid,d in zip(worlds,durations)) or any(v!='PASS' for v in metrics['multiworld_integrity'].values()):fail.append('MULTIWORLD')
 # Fuzz sequential sessions/durations on first world, preserving exact cumulative clock.
 wid=worlds[0];lh=systems[wid][-1];rnd=random.Random(111);expected=rt.get_clock(wid)['day'];session_runs=25
 for i in range(session_runs):
  days=rnd.randint(1,45);lh.begin_offline_session(wid);lh.simulate_offline_days(wid,days,request_key=f'f{i}');lh.reconcile_and_resume(wid,resume_mode='AGGREGATE' if i%3==0 else 'FULL');expected+=days
 metrics['fuzz_sessions']=session_runs;metrics['fuzz_expected_day']=expected;metrics['fuzz_actual_day']=rt.get_clock(wid)['day'];metrics['fuzz_integrity']=lh.full_integrity_check(wid)['status']
 if metrics['fuzz_actual_day']!=expected or metrics['fuzz_integrity']!='PASS':fail.append('FUZZ_SESSIONS')
 # Native DB checks.
 metrics['sqlite_integrity']=rt.conn.execute('PRAGMA integrity_check').fetchone()[0];metrics['foreign_key_failures']=len(rt.conn.execute('PRAGMA foreign_key_check').fetchall())
 if metrics['sqlite_integrity']!='ok' or metrics['foreign_key_failures']!=0:fail.append('SQLITE')
 rt.close()
finally:tmp.cleanup()
out={'record_id':'STAGE11-FUZZ-STRESS-V1.0','status':'PASS' if not fail else 'FAIL','failures':fail,'metrics':metrics,'seconds':round(time.time()-t0,3)}
Path(__file__).resolve().parents[1].joinpath('04_REPORTS/STAGE11_FUZZ_STRESS_V1_0.json').write_text(json.dumps(out,indent=2,ensure_ascii=False));print(json.dumps(out,indent=2));raise SystemExit(0 if not fail else 1)
