import json, os, tempfile, sys
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
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'; REPORT=Path(__file__).resolve().parents[1]/'04_REPORTS'/'STAGE10_EXTENDED_VALIDATION_V1_0.json'
def systems(rt):
 v=IntentValidator(rt);b=AgentBrain(rt,v);s=SocialMemorySystem(rt);e=EcologySystem(rt,v);o=ObjectEnvironmentSystem(rt);c=ConsequenceEngine(rt);orch=WorldSimulationOrchestrator(rt,c,b,v,s,e,o);ws=WorldSystems(rt);return v,b,s,e,o,c,orch,ws
def main():
 checks=0;fails=[]
 def ck(x,n):
  nonlocal checks;checks+=1
  if not x:fails.append(n)
 tmp=tempfile.TemporaryDirectory();db=os.path.join(tmp.name,'x.db');rt=LivingRuntime(db,master_release_path=MASTER);v,b,s,e,o,c,orch,ws=systems(rt);snap=ws.load_master_snapshots(MASTER);ck(snap['total']==58,'snapshot_total')
 worlds=[]
 for i in range(4):
  w=rt.create_world(f's10-{i}',100+i,ticks_per_day=24,mode='PRIVATE' if i<3 else 'SHARED');wid=w['world_instance_id'];orch.configure_world(wid,{'integrity_cadence_ticks':4,'extension_budget':4,'max_roots_per_run':256,'full_npc_budget':8,'active_npc_budget':4,'full_ecology_budget':8,'active_ecology_budget':4});ws.bootstrap_world(wid,population_seed=1000+i*100);ws.attach_to_orchestrator(orch,wid);worlds.append(wid)
  ck(ws.summary(wid)=={'routes':34,'flows':7,'populations':14,'factions':3,'ticks':0},f'bootstrap_{i}')
 # baseline 12 ticks each
 for wid in worlds:
  for _ in range(12):ck(orch.run_tick(wid)['status']=='COMPLETED',f'baseline_tick:{wid}')
  ck(ws.full_integrity_check(wid)['status']=='PASS',f'baseline_integrity:{wid}')
 # route shock world0: FLOW-001 uses SRTE-001/RTE-001, deplete and measure response
 wid=worlds[0];flow0=ws._entity_for(wid,'ECONOMIC_FLOW','FLOW-001');base_price=flow0['data']['price'];base_security=ws._entity_for(wid,'FACTION_RUNTIME','FAC-001')['data']['security']
 for rr in flow0['data']['route_ids']:ws.set_route_operational(wid,rr,False,reason='EXTENDED_SHOCK')
 for _ in range(16):orch.run_tick(wid)
 shocked=ws._entity_for(wid,'ECONOMIC_FLOW','FLOW-001');ck(shocked['data']['shortage_pressure']>0,'shortage_after_route_shock');ck(shocked['data']['price']>=base_price,'price_not_down_under_shortage')
 pops=ws._entities(wid,'POPULATION_AGGREGATE');ck(all(0<=p['data']['food_security']<=100 for p in pops),'food_security_bounds');ck(all(p['data']['employed']+p['data']['unemployed']==p['data']['labor_force'] for p in pops),'labor_invariant')
 fac=ws._entity_for(wid,'FACTION_RUNTIME','FAC-001');ck(0<=fac['data']['influence']<=100,'influence_bounds');ck(fac['data']['influence_not_sovereignty'] is True,'non_sovereignty_guard')
 # restore and recovery of flow
 for rr in flow0['data']['route_ids']:ws.set_route_operational(wid,rr,True,reason='EXTENDED_RESTORE')
 for _ in range(8):orch.run_tick(wid)
 restored=ws._entity_for(wid,'ECONOMIC_FLOW','FLOW-001');ck(restored['data']['shortage_pressure']<=shocked['data']['shortage_pressure'],'shortage_recovery')
 # offline: no migration and faction influence frozen
 before_inf=[x['data']['influence'] for x in ws._entities(wid,'FACTION_RUNTIME')];before_mig=[x['data']['migration_accumulator'] for x in ws._entities(wid,'POPULATION_AGGREGATE')];rt.set_simulation_mode(wid,'ROUTINE_OFFLINE')
 for _ in range(24):orch.run_tick(wid)
 after_inf=[x['data']['influence'] for x in ws._entities(wid,'FACTION_RUNTIME')];after_mig=[x['data']['migration_accumulator'] for x in ws._entities(wid,'POPULATION_AGGREGATE')];ck(before_inf==after_inf,'offline_influence_frozen');ck(before_mig==after_mig,'offline_migration_frozen')
 # isolation: world1 route stays operational and tick counts differ
 ck(ws._entity_for(worlds[1],'ROUTE_RUNTIME',flow0['data']['route_ids'][0])['data']['operational'] is True,'timeline_route_isolation');ck(ws.summary(worlds[1])['ticks']==36,'world1_tick_count')
 # restart/rebind
 rt.close();rt=LivingRuntime(db,master_release_path=MASTER);v,b,s,e,o,c,orch,ws=systems(rt);wid=worlds[2]
 try:orch.run_tick(wid);ck(False,'restart_should_require_rebind')
 except Exception:ck(True,'restart_requires_rebind')
 ws.bind_to_orchestrator(orch,wid);ck(orch.run_tick(wid)['status']=='COMPLETED','restart_rebind_tick');ck(ws.full_integrity_check(wid)['status']=='PASS','restart_ws_integrity');ck(orch.full_integrity_check(wid)['status']=='PASS','restart_orch_integrity')
 sqlite=rt.conn.execute('PRAGMA integrity_check').fetchone()[0];fk=len(rt.conn.execute('PRAGMA foreign_key_check').fetchall());ck(sqlite=='ok','sqlite');ck(fk==0,'fk')
 report={'record_id':'STAGE10-EXTENDED-VALIDATION-V1.0','status':'PASS' if not fails else 'FAIL','checks':checks,'passed':checks-len(fails),'failed':len(fails),'failures':fails,'worlds':4,'master_snapshots':58,'main_routes':25,'secondary_routes':9,'flows':7,'population_distributions':14,'faction_influences':3,'shock':{'base_price':base_price,'shortage_pressure':shocked['data']['shortage_pressure'],'restored_shortage':restored['data']['shortage_pressure'],'base_security':base_security},'sqlite_integrity':sqlite,'foreign_key_failures':fk}
 REPORT.write_text(json.dumps(report,indent=2,ensure_ascii=False));print(json.dumps(report,indent=2,ensure_ascii=False));rt.close();tmp.cleanup();return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
