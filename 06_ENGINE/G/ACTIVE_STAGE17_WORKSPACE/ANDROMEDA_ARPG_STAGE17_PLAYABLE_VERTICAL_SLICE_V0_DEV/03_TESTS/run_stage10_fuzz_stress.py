import json, os, random, tempfile, threading, sys
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
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip');REPORT=Path(__file__).resolve().parents[1]/'04_REPORTS'/'STAGE10_FUZZ_STRESS_V1_0.json'
def stack(rt):
 v=IntentValidator(rt);b=AgentBrain(rt,v);s=SocialMemorySystem(rt);e=EcologySystem(rt,v);o=ObjectEnvironmentSystem(rt);c=ConsequenceEngine(rt);orch=WorldSimulationOrchestrator(rt,c,b,v,s,e,o);ws=WorldSystems(rt);return orch,ws
def main():
 tmp=tempfile.TemporaryDirectory();db=os.path.join(tmp.name,'stress.db');rt=LivingRuntime(db,master_release_path=MASTER);orch,ws=stack(rt);ws.load_master_snapshots(MASTER);worlds=[]
 for i in range(6):
  w=rt.create_world(f'stress-{i}',9000+i,ticks_per_day=24,mode='SHARED' if i==5 else 'PRIVATE');wid=w['world_instance_id'];orch.configure_world(wid,{'integrity_cadence_ticks':8,'extension_budget':4,'max_roots_per_run':256,'full_npc_budget':4,'active_npc_budget':2,'full_ecology_budget':4,'active_ecology_budget':2});ws.bootstrap_world(wid,population_seed=800+i*100);ws.attach_to_orchestrator(orch,wid);worlds.append(wid)
 errors=[];same=[]
 def same_call():
  try:same.append(orch.run_tick(worlds[0],tick_key='same-concurrent'))
  except Exception as e:errors.append('same:'+repr(e))
 ts=[threading.Thread(target=same_call) for _ in range(32)];[t.start() for t in ts];[t.join() for t in ts]
 same_runs=len({x['run_id'] for x in same});same_replays=sum(1 for x in same if x.get('idempotent_replay'))
 # 120 unique orchestration ticks across 6 worlds
 def worker(wid,n):
  for _ in range(n):
   try:orch.run_tick(wid)
   except Exception as e:errors.append('tick:'+repr(e))
 ts=[threading.Thread(target=worker,args=(wid,20)) for wid in worlds];[t.start() for t in ts];[t.join() for t in ts]
 # concurrent route toggles, serialized by authority lock
 toggles=[]
 def toggle(i):
  try:
   r=ws.set_route_operational(worlds[1],'RTE-001',i%2==0,reason='STRESS');toggles.append(r)
  except Exception as e:errors.append('route:'+repr(e))
 ts=[threading.Thread(target=toggle,args=(i,)) for i in range(160)];[t.start() for t in ts];[t.join() for t in ts]
 # faction relation fuzz in valid range
 rng=random.Random(1010)
 for _ in range(600):
  a,b=rng.sample(['FAC-001','FAC-002','FAC-003'],2);ws.set_faction_relation(worlds[2],a,b,rng.uniform(-100,100))
 # offline sequence
 rt.set_simulation_mode(worlds[3],'ROUTINE_OFFLINE');inf0=[f['data']['influence'] for f in ws._entities(worlds[3],'FACTION_RUNTIME')];mig0=[p['data']['migration_accumulator'] for p in ws._entities(worlds[3],'POPULATION_AGGREGATE')]
 for _ in range(24):orch.run_tick(worlds[3])
 inf1=[f['data']['influence'] for f in ws._entities(worlds[3],'FACTION_RUNTIME')];mig1=[p['data']['migration_accumulator'] for p in ws._entities(worlds[3],'POPULATION_AGGREGATE')]
 invariants=[]
 for wid in worlds:
  flows=ws._entities(wid,'ECONOMIC_FLOW');pops=ws._entities(wid,'POPULATION_AGGREGATE');facs=ws._entities(wid,'FACTION_RUNTIME');routes=ws._entities(wid,'ROUTE_RUNTIME')
  invariants += [all(x['data']['stock']>=0 and x['data']['price']>=0 and 0<=x['data']['shortage_pressure']<=100 for x in flows), all(p['data']['count']>=0 and p['data']['employed']+p['data']['unemployed']==p['data']['labor_force'] for p in pops), all(0<=f['data']['influence']<=100 and f['data']['influence_not_sovereignty'] for f in facs), all(0<=r['data']['capacity_factor']<=1 for r in routes), ws.full_integrity_check(wid)['status']=='PASS', orch.full_integrity_check(wid)['status']=='PASS']
 sqlite_before=rt.conn.execute('PRAGMA integrity_check').fetchone()[0];fk_before=len(rt.conn.execute('PRAGMA foreign_key_check').fetchall());event_count=rt.conn.execute('SELECT COUNT(*) c FROM events').fetchone()['c'];run_count=rt.conn.execute("SELECT COUNT(*) c FROM orchestration_runs WHERE status='COMPLETED'").fetchone()['c'];tick_logs=rt.conn.execute('SELECT COUNT(*) c FROM world_system_tick_log').fetchone()['c']
 rt.close();rt=LivingRuntime(db,master_release_path=MASTER);orch,ws=stack(rt)
 for wid in worlds:ws.bind_to_orchestrator(orch,wid)
 reopen_ok=all(ws.full_integrity_check(w)['status']=='PASS' and orch.full_integrity_check(w)['status']=='PASS' for w in worlds);sqlite_after=rt.conn.execute('PRAGMA integrity_check').fetchone()[0];fk_after=len(rt.conn.execute('PRAGMA foreign_key_check').fetchall())
 status='PASS' if not errors and same_runs==1 and same_replays==31 and len(toggles)==160 and all(invariants) and inf0==inf1 and mig0==mig1 and reopen_ok and sqlite_before=='ok' and sqlite_after=='ok' and fk_before==0 and fk_after==0 else 'FAIL'
 report={'record_id':'STAGE10-FUZZ-STRESS-V1.0','status':status,'errors':errors,'worlds':6,'same_tick_callers':32,'same_tick_unique_runs':same_runs,'same_tick_idempotent_replays':same_replays,'unique_tick_requests':120,'route_toggle_calls':160,'route_toggle_success':len(toggles),'faction_relation_fuzz':600,'offline_ticks':24,'offline_influence_frozen':inf0==inf1,'offline_migration_frozen':mig0==mig1,'invariant_checks':len(invariants),'invariants_passed':sum(bool(x) for x in invariants),'completed_runs':run_count,'world_system_tick_logs':tick_logs,'events':event_count,'sqlite_before':sqlite_before,'sqlite_after':sqlite_after,'foreign_keys_before':fk_before,'foreign_keys_after':fk_after,'reopen_integrity':reopen_ok}
 REPORT.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));rt.close();tmp.cleanup();return 0 if status=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
