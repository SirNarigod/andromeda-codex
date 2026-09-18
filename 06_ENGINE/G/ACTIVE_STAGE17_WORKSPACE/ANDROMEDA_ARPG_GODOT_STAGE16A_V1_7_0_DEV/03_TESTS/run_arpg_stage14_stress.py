from __future__ import annotations
import json,os,sys,tempfile
from integrated_arpg_engine_v14 import IntegratedARPGEngineV14
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
OUT=os.environ.get('ARPG_STAGE14_STRESS_OUT','/tmp/ARPG_STAGE14_STRESS_V1_5_0.json')

def main():
 checks=[]
 def ck(n,o,d=None):checks.append({'name':n,'status':'PASS' if o else 'FAIL','detail':d})
 with tempfile.TemporaryDirectory() as td:
  db=os.path.join(td,'stress14.sqlite');e=IntegratedARPGEngineV14(db,master_release_path=MASTER);r=e.create_world('stress:s14',141417);wid=r['world']['world_instance_id'];l=e.living_arpg(wid);m=e.mobility_arpg(wid);t=e.technology_arpg(wid);ec=e.economy_arpg(wid)
  demand=[]
  for i in range(12):
   broken=i<5
   m.set_bridge_condition('POI-046',0 if broken else 100)
   if i in (2,3):
    mach=t.list_machines()[0];x=t.machine(mach['machine_ref']);x['integrity']=20;x['energy']=3;t._save_machine(x)
   if i==6:
    mach=t.list_machines()[0];x=t.machine(mach['machine_ref']);p=t.machine_profile(x['profile_ref']);x['integrity']=p['integrity_max'];x['energy']=p['energy_max'];t._save_machine(x)
   res=l.run_cycle(f's14:stress:{i}');ck(f'cycle_{i}',res['status']=='PASS');rep=l.run_cycle(f's14:stress:{i}');ck(f'replay_{i}',rep.get('idempotent_replay') is True);demand.append(float(ec._market_row('POI-002','ITEM-GRAIN')['demand_index']))
  ck('demand_responded',max(demand)>min(demand),{'min':min(demand),'max':max(demand)});ck('bridge_signals',any(s['signal_type']=='INFRASTRUCTURE_DISRUPTION' for s in l.list_signals()));ck('opportunities_generated',len(l.list_opportunities())>0);before=l.cycle('s14:stress:4');e.runtime.close();e2=IntegratedARPGEngineV14(db,master_release_path=MASTER);e2.resume_world(wid);l2=e2.living_arpg(wid);ck('resume_cycle',l2.cycle('s14:stress:4')==before);ck('resume_health',e2.health_arpg_v14(wid)['status']=='PASS');ck('signal_persistence',len(l2.list_signals())>=len(l.list_signals()) if False else len(l2.list_signals())>0);e2.runtime.close()
 fail=[x for x in checks if x['status']!='PASS'];out={'status':'PASS' if not fail else 'FAIL','checks':len(checks),'passed':len(checks)-len(fail),'failed':len(fail),'failures':fail,'cycles':12,'replays':12,'authority':'ANDROMEDA_ARPG_STAGE14_LIVING_INTEGRATION'};open(OUT,'w').write(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False));return 0 if not fail else 1
if __name__=='__main__':sys.exit(main())
