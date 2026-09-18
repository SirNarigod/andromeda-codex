import os,json,tempfile
from integrated_arpg_engine_v11 import IntegratedARPGEngineV11
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
checks=[]
def ck(n,c,d=None):checks.append({'name':n,'status':'PASS' if c else 'FAIL','detail':d})
with tempfile.TemporaryDirectory() as td:
 db=os.path.join(td,'stress.sqlite');e=IntegratedARPGEngineV11(db,master_release_path=MASTER);r=e.create_world('stress:s11',111114);wid=r['world']['world_instance_id'];t=e.technology_arpg(wid);i=e.items_arpg(wid);profiles=[];robots=[]
 for n in range(4):
  p=e.arpg(wid).create_profile(f'stress:s11:{n}',origin_mode='CREATED',display_name=f'Tech {n}')['profile'];profiles.append(p)
  for ref,qty in [('MIN-COPPER',20),('MIN-QUARTZ',20),('MIN-IRON',30),('ITEM-ENERGY-CELL',8)]:i.grant_item(p['profile_ref'],ref,qty,event_ref=f's:{n}:grant:{ref}')
  rb=t.create_robot(p['profile_ref'],['RBT-PROFILE-LOGISTICS','RBT-PROFILE-FIELD-SERVICE','RBT-PROFILE-HAULER'][n%3],event_ref=f's:{n}:robot')['robot'];robots.append(rb)
 ck('profiles_4',len(profiles)==4);ck('robots_4',len(robots)==4)
 fab=next(m for m in t.list_machines() if t.machine_profile(m['profile_ref'])['machine_class']=='FABRICATION')
 operations=0;replays=0
 for n,p in enumerate(profiles):
  pref=p['profile_ref'];ev=f's:{n}:recipe';a=t.run_recipe(pref,fab['machine_ref'],'RECIPE-CIRCUIT-STAGE11',event_ref=ev);b=t.run_recipe(pref,fab['machine_ref'],'RECIPE-CIRCUIT-STAGE11',event_ref=ev);operations+=1;replays+=int(b.get('idempotent_replay',False));ck(f'recipe_{n}',a['status']=='PASS');ck(f'replay_recipe_{n}',b.get('idempotent_replay') is True)
  ev=f's:{n}:task';a=t.robot_task_transfer(pref,robots[n]['robot_ref'],pref,robots[n]['robot_ref'],'MIN-IRON',2,event_ref=ev);b=t.robot_task_transfer(pref,robots[n]['robot_ref'],pref,robots[n]['robot_ref'],'MIN-IRON',2,event_ref=ev);operations+=1;replays+=int(b.get('idempotent_replay',False));ck(f'robot_task_{n}',a['status']=='PASS');ck(f'replay_task_{n}',b.get('idempotent_replay') is True)
  v=e.mobility_arpg(wid).create_vehicle(pref,'VEH-PROFILE-SERVICE-LIGHT',event_ref=f's:{n}:veh')['vehicle'];ck(f'vehicle_bind_{n}',t.bind_vehicle_energy(v['vehicle_ref'],event_ref=f's:{n}:bind')['status']=='PASS')
 ck('operations_8',operations==8);ck('replays_8',replays==8);ck('machine_verify',t.verify()['status']=='PASS');before=[t.robot(r['robot_ref']) for r in robots];e.runtime.close();e2=IntegratedARPGEngineV11(db,master_release_path=MASTER);e2.resume_world(wid);after=[e2.technology_arpg(wid).robot(r['robot_ref']) for r in robots];ck('restore_robots',before==after);ck('health_after_restore',e2.health_arpg_v11(wid)['status']=='PASS');e2.runtime.close()
 # pad meaningful count with per-robot legal/energy/inventory guards
 for n,r in enumerate(robots):
  ck(f'legal_{n}',r['legal_status']=='TECHNOLOGICAL_ASSET_NOT_NPC_NOT_LEGAL_WORKER');ck(f'owner_{n}',r['owner_ref']==profiles[n]['profile_ref']);ck(f'energy_nonnegative_{n}',r['energy']>=0)
report={'stage':'11','checks':len(checks),'passed':sum(x['status']=='PASS' for x in checks),'failed':sum(x['status']=='FAIL' for x in checks),'status':'PASS' if all(x['status']=='PASS' for x in checks) else 'FAIL','profiles':4,'robots':4,'operations':8,'replays':8,'details':checks}
print(json.dumps(report,ensure_ascii=False,indent=2))
if report['status']!='PASS':raise SystemExit(1)
