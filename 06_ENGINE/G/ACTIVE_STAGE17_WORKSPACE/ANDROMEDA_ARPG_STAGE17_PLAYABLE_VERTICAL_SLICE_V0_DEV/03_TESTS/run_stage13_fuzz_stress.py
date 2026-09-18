import json,os,tempfile,threading,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from living_runtime import LivingRuntime
from world_systems import WorldSystems
from atlas_living_bridge import AtlasLivingBridge,AtlasSnapshotPublisher
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip');OUT=ROOT/'04_REPORTS/STAGE13_FUZZ_STRESS_V1_0.json'
t=tempfile.TemporaryDirectory();db=os.path.join(t.name,'stress.db');snapdir=os.path.join(t.name,'snapshots');rt=LivingRuntime(db,master_release_path=MASTER);w=rt.create_world('stress-owner',13130,ticks_per_day=24);wid=w['world_instance_id'];ws=WorldSystems(rt);ws.load_master_snapshots(MASTER);ws.bootstrap_world(wid,population_seed=1000);pub=AtlasSnapshotPublisher(rt,snapdir);first=pub.publish(wid);snapshot=os.path.join(snapdir,first['snapshot_file'])
errs=[];counts={'player':0,'admin':0,'writes':0,'publishes':0};lock=threading.Lock();latest={'path':snapshot}
def writer_and_publisher():
 try:
  for i in range(60):
   ws.set_route_operational(wid,'RTE-001',i%2==0,reason='ATLAS_STRESS');ws.economy_tick(wid,f'e-{i}','FULL')
   if i%4==0:
    m=pub.publish(wid)
    with lock:latest['path']=os.path.join(snapdir,m['snapshot_file']);counts['publishes']+=1
  m=pub.publish(wid)
  with lock:latest['path']=os.path.join(snapdir,m['snapshot_file']);counts['publishes']+=1;counts['writes']=60
 except Exception as e:
  with lock:errs.append('writer:'+repr(e))
def reader(role,idx):
 try:
  for i in range(30):
   with lock:path=latest['path']
   b=AtlasLivingBridge(path,MASTER)
   try:
    p=b.export_projection(wid,role=role,request_scope='stress-owner' if role=='PLAYER' else None,spoiler_max=i%4,recent_events=30)
    if b.verify_projection(p)['status']!='PASS':raise RuntimeError('projection hash fail')
    if b.write_attempt_probe()!='PASS_READ_ONLY':raise RuntimeError('snapshot became writable')
   finally:b.close()
   with lock:counts[role.lower()]+=1
 except Exception as e:
  with lock:errs.append(f'{role}-{idx}:'+repr(e))
ts=[threading.Thread(target=writer_and_publisher)] + [threading.Thread(target=reader,args=('PLAYER',i)) for i in range(4)] + [threading.Thread(target=reader,args=('ADMIN',i)) for i in range(4)]
[x.start() for x in ts];[x.join(180) for x in ts];alive=sum(x.is_alive() for x in ts)
# final atomic snapshot and verification
m=pub.publish(wid);final_path=os.path.join(snapdir,m['snapshot_file']);b=AtlasLivingBridge(final_path,MASTER);final=b.export_projection(wid,role='ADMIN',recent_events=500);sql=b.conn.execute('pragma integrity_check').fetchone()[0];fk=len(b.conn.execute('pragma foreign_key_check').fetchall());readonly=b.write_attempt_probe();b.close();core=rt.full_integrity_check(wid)['status'];rt.close()
status='PASS' if not errs and alive==0 and counts['player']==120 and counts['admin']==120 and counts['writes']==60 and counts['publishes']==16 and sql=='ok' and fk==0 and readonly=='PASS_READ_ONLY' and core=='PASS' else 'FAIL'
rep={'record_id':'STAGE13-FUZZ-STRESS-V1.0','status':status,'reader_threads':8,'player_projections':counts['player'],'admin_projections':counts['admin'],'writer_route_economy_cycles':counts['writes'],'atomic_snapshot_publishes':counts['publishes']+1,'threads_alive':alive,'errors':errs[:20],'sqlite_snapshot_integrity':sql,'foreign_key_failures':fk,'readonly_probe':readonly,'runtime_integrity':core,'final_event_count':len(final['layers']['LIVE_EVENTS'])};OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2));print(json.dumps(rep));t.cleanup();raise SystemExit(0 if status=='PASS' else 1)
