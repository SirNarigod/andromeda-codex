from pathlib import Path
import sys,tempfile,os,json,hashlib,traceback
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v15 import IntegratedLivingEngineV15
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_1_0_RELEASE.zip'
import argparse
ap=argparse.ArgumentParser();ap.add_argument('--start',type=int,default=0);ap.add_argument('--count',type=int,default=5);a=ap.parse_args()
rows=[]; failures=[]
for i in range(a.start,a.start+a.count):
 seed=15000+i
 try:
  with tempfile.TemporaryDirectory() as td:
   e=IntegratedLivingEngineV15(os.path.join(td,'w.db'),master_release_path=MASTER); r=e.create_world('v15-stress',seed,load_relationships=False);wid=r['world']['world_instance_id'];c=e.country(wid)
   n=next(x for x in c._all_npc_records() if x['class']=='WARRIOR'); g=e.godot(wid); sess=f'S-{seed}'; assert g.bind_session(sess,n['id'])['status']=='PASS'
   s0=g.client_snapshot(sess); assert s0['status']=='PASS'
   moves={'PASS':0,'COLLISION_BLOCKED':0}
   for _ in range(3):
    mv=g.client_command(sess,'MOVE_VECTOR',{'dx':1,'dy':0.25,'duration_s':1,'mode':'WALK'})
    if mv['status']=='PASS':moves['PASS']+=1
    elif mv.get('reason')=='COLLISION_BLOCKED':moves['COLLISION_BLOCKED']+=1
    else: raise AssertionError(('move',mv))
   disc=g.client_command(sess,'DISCOVER',{'radius_m':160});assert disc['status']=='PASS'
   blocks=[b['id'] for st in c.world['country']['states'] for b in st['blocks']]; dest=next(b for b in blocks if b!=c.npc(n['id'])['block_id']); pp=g.client_command(sess,'PATH_PLAN',{'destination_block_id':dest}); assert pp['status'] in ('PASS','REJECTED')
   # Dungeon chain using actual spatial locality and authoritative graph.
   d=next(d for st in c.world['country']['states'] for b in st['blocks'] for d in b.get('dungeons',[])); c.relocate_npc(n['id'],d['block_id']); en=e.dungeon_graph(wid).enter(n['id'],d['id']);assert en['status']=='PASS'; cur=en['room_id']
   known={x['feature_ref'] for x in e.discovery(wid).known(n['id'])}; assert cur in known
   edge=next((x for x in d['graph_v2']['edges'] if (x['from']==cur or x['to']==cur) and not x.get('secret')),None)
   dm='NO_EDGE'
   if edge:
    dst=edge['to'] if edge['from']==cur else edge['from']; rr=g.client_command(sess,'DUNGEON_MOVE',{'to_room_id':dst}); dm=rr['status']; assert rr['status'] in ('PASS','REJECTED')
   snap=g.client_snapshot(sess);assert snap['status']=='PASS'; ents=[x for x in snap['chunk']['entities'] if x.get('entity_ref')==n['id']]; assert len(ents)==1
   dx=abs(ents[0]['isometric']['x_m']-snap['transform']['iso_x_m']);dy=abs(ents[0]['isometric']['y_m']-snap['transform']['iso_y_m']);assert dx<.001 and dy<.001
   # No undiscovered room may leak into player payload.
   known={x['feature_ref'] for x in e.discovery(wid).known(n['id'])}; leaked=[x['entity_ref'] for x in snap['chunk']['entities'] if x.get('kind')=='DUNGEON_ROOM' and x.get('entity_ref') not in known];assert not leaked,leaked
   h=e.health_v15(wid); assert h['status']=='PASS',h['failures']
   env=e.environment(wid).state_for_block(c.npc(n['id'])['block_id']);assert env['status']=='PASS'
   rows.append({'seed':seed,'npc':n['id'],'moves':moves,'path_status':pp['status'],'dungeon_move':dm,'known':len(known),'health':'PASS','transform_delta_max_m':max(dx,dy),'environment':{'temp':env['temperature_c'],'rain':env['precipitating'],'daylight':env['daylight']}})
   e.close()
 except Exception as ex:
  failures.append({'seed':seed,'error':repr(ex),'traceback':traceback.format_exc()})
report={'record_id':'V15-INTEGRATED-STRESS-BATCH','start':a.start,'worlds':a.count,'passed':len(rows),'failed':len(failures),'rows':rows,'failures':failures,'status':'PASS' if not failures else 'FAIL'}
out=ROOT/f'04_REPORTS/V1_5_0/V15_INTEGRATED_STRESS_BATCH_{a.start:02d}_{a.count:02d}.json';out.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps({k:report[k] for k in ('worlds','passed','failed','status')},indent=2));raise SystemExit(0 if not failures else 1)
