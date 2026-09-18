import json, os, sys, tempfile, threading, time, random
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from living_runtime import LivingRuntime, ConflictError, ValidationError, OfflinePolicyError, new_runtime_id, clock_point
from object_environment import ObjectEnvironmentSystem
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
start=time.time();failures=[];guard=threading.Lock()
def fail(x):
 with guard:failures.append(x)
def mkactor(rt,wid):
 w=rt.get_world(wid);c=w['clock_state'];s={'state_id':new_runtime_id('state'),'world_instance_id':wid,'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{},'protection':{}};return rt.register_entity(wid,s)
with tempfile.TemporaryDirectory() as td:
 db=os.path.join(td,'objstress.db');rt=LivingRuntime(db,master_release_path=MASTER);w=rt.create_world('obj-stress',888,ticks_per_day=24);wid=w['world_instance_id'];s=ObjectEnvironmentSystem(rt);a=mkactor(rt,wid)
 door=s.register_profile(wid,{'object_class':'DOOR','material_class':'WOOD','flammable':True,'supports_open':True,'supports_lock':True,'ignition_temperature':100,'water_absorption':1});res=s.register_profile(wid,{'object_class':'RESOURCE_NODE','material_class':'ORGANIC','flammable':True,'harvestable':True});bridge=s.register_profile(wid,{'object_class':'BRIDGE','material_class':'STONE'})
 # Shared resource: 1,200 contenders, exactly 600 units available.
 node=s.spawn_object(wid,profile_id=res['profile_id'],data={'resource_quantity':600});threads=24;loops=50;succ=reject=errors=0;cl=threading.Lock()
 def harvest_worker(seed):
  global succ,reject,errors
  for _ in range(loops):
   try:s.interact(wid,actor_ref=a['entity_runtime_id'],target_ref=node['entity_runtime_id'],interaction_type='HARVEST',amount=1);x='PASS'
   except (ConflictError,ValidationError):x='REJECT'
   except Exception as e:x='ERROR';fail(f'harvest:{type(e).__name__}:{e}')
   with cl:
    if x=='PASS':succ+=1
    elif x=='REJECT':reject+=1
    else:errors+=1
 ts=[threading.Thread(target=harvest_worker,args=(i,)) for i in range(threads)];[t.start() for t in ts];[t.join(45) for t in ts]
 if any(t.is_alive() for t in ts):fail('harvest_threads_alive')
 qty=rt.get_entity(wid,node['entity_runtime_id'])['data']['resource_quantity']
 if succ!=600 or qty!=0:fail(f'harvest_conservation:{succ}:{qty}')
 # Shared bridge damage: can be destroyed only once; integrity never negative; single recovery schedule.
 b=s.spawn_object(wid,profile_id=bridge['profile_id']);dpass=dreject=0
 def dmg_worker():
  global dpass,dreject
  for _ in range(20):
   try:s.interact(wid,actor_ref=a['entity_runtime_id'],target_ref=b['entity_runtime_id'],interaction_type='DAMAGE',amount=1);x=1
   except (ConflictError,ValidationError):x=0
   except Exception as e:x=-1;fail(f'damage:{type(e).__name__}:{e}')
   with cl:
    if x==1:dpass+=1
    elif x==0:dreject+=1
 dts=[threading.Thread(target=dmg_worker) for _ in range(10)];[t.start() for t in dts];[t.join(45) for t in dts]
 if any(t.is_alive() for t in dts):fail('damage_threads_alive')
 bs=rt.get_entity(wid,b['entity_runtime_id'])
 if bs['data']['integrity']!=0 or bs['lifecycle']!='DESTROYED':fail(f'bridge_state:{bs["data"]["integrity"]}:{bs["lifecycle"]}')
 if rt.conn.execute('SELECT COUNT(*) c FROM recoveries WHERE target_ref=?',(b['entity_runtime_id'],)).fetchone()['c']!=1:fail('bridge_recovery_not_one')
 # 2,400 operations across distinct objects in parallel.
 objs=[s.spawn_object(wid,profile_id=door['profile_id']) for _ in range(240)];op_errors=[]
 def object_worker(idx):
  subset=objs[idx*10:(idx+1)*10]
  try:
   for _ in range(10):
    for o in subset:s.interact(wid,actor_ref=a['entity_runtime_id'],target_ref=o['entity_runtime_id'],interaction_type='DAMAGE',amount=.5)
  except Exception as e:
   with guard:op_errors.append(f'{type(e).__name__}:{e}')
 ots=[threading.Thread(target=object_worker,args=(i,)) for i in range(24)];[t.start() for t in ots];[t.join(45) for t in ots]
 if any(t.is_alive() for t in ots):fail('object_threads_alive')
 failures.extend(op_errors)
 for o in objs:
  if rt.get_entity(wid,o['entity_runtime_id'])['data']['integrity']!=95:fail('distinct_object_lost_update');break
 # Environment tick with 200 members; then repeat idempotently.
 z=s.create_environment_zone(wid,fire_intensity=50,water_level=10);members=[]
 for i in range(200):
  o=s.spawn_object(wid,profile_id=door['profile_id']);members.append(o);s.link(wid,z['entity_runtime_id'],o['entity_runtime_id'],link_type='ENVIRONMENT_MEMBER',conductance=.5)
 tick=s.simulate_environment_tick(wid,tick_key='stress-env');versions=[rt.get_entity(wid,o['entity_runtime_id'])['version'] for o in members];tick2=s.simulate_environment_tick(wid,tick_key='stress-env')
 if not tick2['idempotent_replay'] or versions!=[rt.get_entity(wid,o['entity_runtime_id'])['version'] for o in members]:fail('env_tick_not_idempotent')
 # Fire fanout: 64 neighbors but max 32 heat applications. 32 concurrent callers with same key all converge.
 root=s.spawn_object(wid,profile_id=door['profile_id']);s.interact(wid,actor_ref=a['entity_runtime_id'],target_ref=root['entity_runtime_id'],interaction_type='IGNITE');leaves=[]
 for i in range(64):
  o=s.spawn_object(wid,profile_id=door['profile_id']);leaves.append(o);s.link(wid,root['entity_runtime_id'],o['entity_runtime_id'],link_type='ADJACENT',conductance=1)
 pres=[]
 def prop_worker():
  try:r=s.propagate_fire(wid,root['entity_runtime_id'],propagation_key='same-prop',budget=32);pres.append(r)
  except Exception as e:fail(f'prop:{type(e).__name__}:{e}')
 pts=[threading.Thread(target=prop_worker) for _ in range(32)];[t.start() for t in pts];[t.join(45) for t in pts]
 if any(t.is_alive() for t in pts):fail('prop_threads_alive')
 burning=sum(bool(rt.get_entity(wid,o['entity_runtime_id'])['data']['burning']) for o in leaves)
 if burning!=32:fail(f'fire_budget_burning:{burning}')
 if len(pres)!=32 or sum(bool(r.get('idempotent_replay')) for r in pres)!=31:fail(f'prop_idempotency:{len(pres)}:{sum(bool(r.get("idempotent_replay")) for r in pres)}')
 # Fuzz 3,000 malformed/valid interactions; errors are expected but integrity must hold.
 rnd=random.Random(808);accepted=rejected=0;target=objs[0];types=['OPEN','CLOSE','LOCK','UNLOCK','DAMAGE','REPAIR','IGNITE','EXTINGUISH','HEAT','COOL','SOAK','DRY','HARVEST','INVALID','TELEPORT']
 for i in range(3000):
  typ=rnd.choice(types);amt=rnd.uniform(-100,10000)
  try:s.interact(wid,actor_ref=a['entity_runtime_id'],target_ref=target['entity_runtime_id'],interaction_type=typ,amount=amt);accepted+=1
  except Exception:rejected+=1
 if not accepted or not rejected:fail(f'fuzz_paths:{accepted}:{rejected}')
 # Offline fuzz: fire propagation must be blocked, safe humidity tick remains possible.
 rt.set_simulation_mode(wid,'ROUTINE_OFFLINE')
 for i in range(100):
  try:s.propagate_fire(wid,root['entity_runtime_id'],propagation_key=f'off-{i}');fail('offline_fire_allowed');break
  except OfflinePolicyError:pass
 oz=s.create_environment_zone(wid,humidity=95);oo=s.spawn_object(wid,profile_id=door['profile_id']);s.link(wid,oz['entity_runtime_id'],oo['entity_runtime_id'],link_type='ENVIRONMENT_MEMBER');s.simulate_environment_tick(wid,tick_key='off-safe')
 if rt.get_entity(wid,oo['entity_runtime_id'])['data']['wetness']<=0:fail('offline_safe_water_missing')
 rt.set_simulation_mode(wid,'FULL')
 before=s.full_integrity_check(wid);core=rt.full_integrity_check(wid);quick=rt.conn.execute('PRAGMA quick_check').fetchone()[0];fk=len(rt.conn.execute('PRAGMA foreign_key_check').fetchall());counts={t:rt.conn.execute(f'SELECT COUNT(*) c FROM {t}').fetchone()['c'] for t in ['reaction_logs','environment_links','environment_ticks','propagation_runs_env','entity_states','events','recoveries']};rt.close()
 rt=LivingRuntime(db,master_release_path=MASTER);s=ObjectEnvironmentSystem(rt);after=s.full_integrity_check(wid);core2=rt.full_integrity_check(wid);integrity=rt.conn.execute('PRAGMA integrity_check').fetchone()[0];fk2=len(rt.conn.execute('PRAGMA foreign_key_check').fetchall());rt.close()
 if before['status']!='PASS' or after['status']!='PASS' or core['status']!='PASS' or core2['status']!='PASS' or quick!='ok' or integrity!='ok' or fk or fk2:fail('integrity_failure')
report={'record_id':'LIVING-SIM-ETAPA-08-FUZZ-STRESS-V1.0','status':'PASS' if not failures else 'FAIL','elapsed_seconds':round(time.time()-start,3),'threads':threads,'shared_harvest_attempts':threads*loops,'shared_harvest_successes':succ,'shared_harvest_rejections':reject,'remaining_resource':qty,'bridge_damage_attempts':200,'bridge_damage_successes':dpass,'bridge_damage_rejections':dreject,'distinct_object_operations':2400,'environment_members':200,'fire_propagation_callers':32,'fire_neighbors':64,'fire_ignited':burning,'interaction_fuzz_cases':3000,'fuzz_accepted':accepted,'fuzz_rejected':rejected,'offline_fire_block_cases':100,'integrity_before_reopen':before['status'],'integrity_after_reopen':after['status'],'core_before':core['status'],'core_after':core2['status'],'sqlite_quick_check':quick,'sqlite_integrity_check_after':integrity,'foreign_key_failures':fk,'foreign_key_failures_after':fk2,'record_counts':counts,'failures':failures[:100]}
(ROOT/'04_REPORTS'/'FUZZ_STRESS_V1_0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
if report['status']!='PASS':raise SystemExit(1)
