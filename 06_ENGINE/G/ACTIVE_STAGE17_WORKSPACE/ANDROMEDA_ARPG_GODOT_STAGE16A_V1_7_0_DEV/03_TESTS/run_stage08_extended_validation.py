import json, os, sys, tempfile, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from living_runtime import LivingRuntime, ValidationError, ConflictError, OfflinePolicyError, new_runtime_id, clock_point
from object_environment import ObjectEnvironmentSystem
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
start=time.time();checks=passed=0;failures=[]
def ck(cond,label):
 global checks,passed
 checks+=1
 if cond:passed+=1
 else:failures.append(label)

def actor(rt,wid):
 w=rt.get_world(wid);c=w['clock_state'];s={'state_id':new_runtime_id('state'),'world_instance_id':wid,'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{},'protection':{}};return rt.register_entity(wid,s)

with tempfile.TemporaryDirectory() as td:
 db=os.path.join(td,'stage08_extended.db');rt=LivingRuntime(db,master_release_path=MASTER);w=rt.create_world('stage08-extended',80808,ticks_per_day=24);wid=w['world_instance_id'];sys8=ObjectEnvironmentSystem(rt);a=actor(rt,wid)
 profiles={}
 specs=[
  ('door',{'object_class':'DOOR','material_class':'WOOD','flammable':True,'supports_open':True,'supports_lock':True,'ignition_temperature':100,'water_absorption':1}),
  ('machine',{'object_class':'MACHINE','material_class':'METAL','flammable':False,'supports_activation':True,'heat_resistance':.8}),
  ('flora',{'object_class':'FLORA','material_class':'ORGANIC','flammable':True,'harvestable':True,'base_integrity':50,'ignition_temperature':80,'water_absorption':1}),
  ('bridge',{'object_class':'BRIDGE','material_class':'STONE','flammable':False}),
  ('weapon',{'object_class':'WEAPON','material_class':'METAL','flammable':False}),
  ('container',{'object_class':'CONTAINER','material_class':'WOOD','flammable':True,'supports_open':True,'supports_lock':True,'ignition_temperature':120}),
  ('vehicle',{'object_class':'VEHICLE','material_class':'COMPOSITE','flammable':True,'supports_activation':True,'ignition_temperature':180}),
  ('resource',{'object_class':'RESOURCE_NODE','material_class':'ORGANIC','flammable':True,'harvestable':True,'base_integrity':80,'ignition_temperature':90}),
 ]
 for name,p in specs:
  profiles[name]=sys8.register_profile(wid,p);ck(profiles[name]['authority']=='RUNTIME_REACTIVE_PROFILE_NOT_CANON',f'profile:{name}')
 # 250 doors, open-close-lock-unlock cycles = 1000 object transitions.
 doors=[]
 for i in range(250):
  o=sys8.spawn_object(wid,profile_id=profiles['door']['profile_id']);doors.append(o)
  for typ in ['OPEN','CLOSE','LOCK','UNLOCK']:
   r=sys8.interact(wid,actor_ref=a['entity_runtime_id'],target_ref=o['entity_runtime_id'],interaction_type=typ);ck(r['status']=='SUCCEEDED',f'door:{i}:{typ}')
  s=rt.get_entity(wid,o['entity_runtime_id']);ck(s['data']['open'] is False and s['data']['locked'] is False,f'door_final:{i}')
 # Damage/repair 200 objects.
 for i in range(200):
  o=sys8.spawn_object(wid,profile_id=profiles['machine']['profile_id'])
  sys8.interact(wid,actor_ref=a['entity_runtime_id'],target_ref=o['entity_runtime_id'],interaction_type='DAMAGE',amount=25)
  ck(rt.get_entity(wid,o['entity_runtime_id'])['data']['integrity']==75,f'dmg:{i}')
  sys8.interact(wid,actor_ref=a['entity_runtime_id'],target_ref=o['entity_runtime_id'],interaction_type='REPAIR',amount=10)
  ck(rt.get_entity(wid,o['entity_runtime_id'])['data']['integrity']==85,f'repair:{i}')
 # 120 simultaneous destruction records then one 7-day recovery window.
 destroyed=[]
 for i in range(120):
  o=sys8.spawn_object(wid,profile_id=profiles['bridge']['profile_id']);destroyed.append(o)
  sys8.interact(wid,actor_ref=a['entity_runtime_id'],target_ref=o['entity_runtime_id'],interaction_type='DAMAGE',amount=100)
  s=rt.get_entity(wid,o['entity_runtime_id']);ck(s['lifecycle']=='DESTROYED' and s['data']['integrity']==0,f'destroy:{i}')
 ck(rt.conn.execute("SELECT COUNT(*) c FROM recoveries WHERE world_instance_id=? AND status='SCHEDULED'",(wid,)).fetchone()['c']==120,'recoveries_120')
 rt.advance_ticks(wid,7*24);rec=rt.process_due_recoveries(wid);ck(len(rec)==120,'recoveries_processed_120')
 for i,o in enumerate(destroyed):
  s=rt.get_entity(wid,o['entity_runtime_id']);ck(s['lifecycle']=='ACTIVE' and s['data']['integrity']==100 and s['data']['functional'],f'recovered:{i}')
 # 50 zones x 8 members. Fire/water environment reactions.
 zones=[];members=[]
 for i in range(50):
  z=sys8.create_environment_zone(wid,temperature=20,humidity=30,fire_intensity=80 if i%2==0 else 0,water_level=80 if i%2 else 0);zones.append(z)
  for j in range(8):
   o=sys8.spawn_object(wid,profile_id=profiles['door']['profile_id'],zone_ref=z['entity_runtime_id']);members.append(o);sys8.link(wid,z['entity_runtime_id'],o['entity_runtime_id'],link_type='ENVIRONMENT_MEMBER',conductance=.8)
  r=sys8.simulate_environment_tick(wid,tick_key=f'zone-{i}');ck(r['status']=='PASS',f'envtick:{i}')
 for i,o in enumerate(members):
  s=rt.get_entity(wid,o['entity_runtime_id'])
  ck((s['data']['temperature']>20) if (i//8)%2==0 else (s['data']['wetness']>0),f'env_effect:{i}')
 # 100 resource nodes, deterministic harvest and no underflow.
 for i in range(100):
  o=sys8.spawn_object(wid,profile_id=profiles['resource']['profile_id'],data={'resource_quantity':100})
  for _ in range(5):sys8.interact(wid,actor_ref=a['entity_runtime_id'],target_ref=o['entity_runtime_id'],interaction_type='HARVEST',amount=10)
  ck(rt.get_entity(wid,o['entity_runtime_id'])['data']['resource_quantity']==50,f'harvest:{i}')
 # Fanout fire propagation enforces budget exactly.
 root=sys8.spawn_object(wid,profile_id=profiles['door']['profile_id']);sys8.interact(wid,actor_ref=a['entity_runtime_id'],target_ref=root['entity_runtime_id'],interaction_type='IGNITE')
 leaves=[]
 for i in range(40):
  o=sys8.spawn_object(wid,profile_id=profiles['door']['profile_id']);leaves.append(o);sys8.link(wid,root['entity_runtime_id'],o['entity_runtime_id'],link_type='ADJACENT',conductance=1)
 pr=sys8.propagate_fire(wid,root['entity_runtime_id'],propagation_key='fanout',budget=32);ck(pr['heated']==32,'fire_budget_32');ck(pr['budget_exhausted'],'fire_budget_exhausted');ck(sum(bool(rt.get_entity(wid,o['entity_runtime_id'])['data']['burning']) for o in leaves)==32,'fire_ignited_32')
 replay=sys8.propagate_fire(wid,root['entity_runtime_id'],propagation_key='fanout',budget=32);ck(replay['idempotent_replay'],'fire_replay')
 # Offline: 100 extraordinary fire attempts blocked, water routine continues.
 rt.set_simulation_mode(wid,'ROUTINE_OFFLINE')
 for i in range(100):
  try:sys8.propagate_fire(wid,root['entity_runtime_id'],propagation_key=f'off-{i}');ck(False,f'off_fire:{i}')
  except OfflinePolicyError:ck(True,f'off_fire:{i}')
 z=sys8.create_environment_zone(wid,humidity=95,fire_intensity=100);o=sys8.spawn_object(wid,profile_id=profiles['door']['profile_id']);sys8.link(wid,z['entity_runtime_id'],o['entity_runtime_id'],link_type='ENVIRONMENT_MEMBER');rr=sys8.simulate_environment_tick(wid,tick_key='offline-safe');s=rt.get_entity(wid,o['entity_runtime_id']);ck(s['data']['wetness']>0,'offline_water_applied');ck(s['data']['temperature']==20,'offline_fire_frozen');ck(rr['blocked']>=1,'offline_fire_counted_blocked');rt.set_simulation_mode(wid,'FULL')
 # Six independent timelines in same DB; no cross-world linking.
 worlds=[]
 for i in range(6):
  wi=rt.create_world(f'obj-timeline-{i}',9000+i,ticks_per_day=24);sw=ObjectEnvironmentSystem(rt);p=sw.register_profile(wi['world_instance_id'],{'object_class':'DOOR','supports_open':True});ob=sw.spawn_object(wi['world_instance_id'],profile_id=p['profile_id']);worlds.append((wi,sw,ob));ck(sw.full_integrity_check(wi['world_instance_id'])['status']=='PASS',f'timeline_integrity:{i}')
 try:worlds[0][1].link(worlds[0][0]['world_instance_id'],worlds[0][2]['entity_runtime_id'],worlds[1][2]['entity_runtime_id']);ck(False,'cross_world_link')
 except Exception:ck(True,'cross_world_link')
 # Core/object integrity and native SQLite checks.
 integ=sys8.full_integrity_check(wid);ck(integ['status']=='PASS','object_integrity');ck(rt.full_integrity_check(wid)['status']=='PASS','core_integrity');ck(rt.conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok','sqlite_integrity');ck(len(rt.conn.execute('PRAGMA foreign_key_check').fetchall())==0,'foreign_keys')
 counts={t:rt.conn.execute(f'SELECT COUNT(*) c FROM {t}').fetchone()['c'] for t in ['reactive_profiles','environment_links','reaction_logs','environment_ticks','propagation_runs_env','entity_states','events','recoveries']}
 rt.close()
 rt=LivingRuntime(db,master_release_path=MASTER);sys8=ObjectEnvironmentSystem(rt);ck(sys8.full_integrity_check(wid)['status']=='PASS','reopen_object_integrity');ck(rt.full_integrity_check(wid)['status']=='PASS','reopen_core_integrity');rt.close()
report={'record_id':'LIVING-SIM-ETAPA-08-EXTENDED-VALIDATION-V1.0','checks':checks,'passed':passed,'failed':checks-passed,'elapsed_seconds':round(time.time()-start,3),'scale':{'door_cycles':250,'damage_repair_objects':200,'destroy_recover_objects':120,'environment_zones':50,'environment_members':400,'resource_nodes':100,'fire_fanout':40,'offline_fire_block_cases':100,'timelines':7,'record_counts':counts},'failures':failures,'status':'PASS' if not failures else 'FAIL'}
(ROOT/'04_REPORTS'/'EXTENDED_VALIDATION_V1_0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
if report['status']!='PASS':raise SystemExit(1)
