import json,os,sys
from integrated_arpg_engine_v10 import IntegratedARPGEngineV10
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip');OUT=os.environ.get('ARPG_STAGE10_STRESS_OUT','04_REPORTS/ARPG_STAGE10/ARPG_STAGE10_STRESS_V1_1_0.json');checks=[]
def ck(n,ok,d=None):checks.append({'name':n,'status':'PASS' if ok else 'FAIL','detail':d})
e=IntegratedARPGEngineV10(':memory:',master_release_path=MASTER);r=e.create_world('stress:s10',101020);wid=r['world']['world_instance_id'];m=e.mobility_arpg(wid);w=e.world_arpg(wid);it=e.items_arpg(wid);segs=[x for x in m.list_segments() if x['segment_kind']=='DERIVED_LOCAL_CONNECTOR'];profiles=[];vehicles=[];travels=0;replays=0
for i in range(4):
 p=e.arpg(wid).create_profile(f'stress:s10:{i}',origin_mode='CREATED',display_name=f'Driver{i}')['profile'];pref=p['profile_ref'];profiles.append(pref);v=m.create_vehicle(pref,list(m.VEHICLE_PROFILES)[i%3],event_ref=f's:create:{i}')['vehicle'];vr=v['vehicle_ref'];vehicles.append(vr);m.board(pref,vr,event_ref=f's:board:{i}',as_driver=True);s=segs[i%len(segs)];st=w.ensure_profile(pref);st['zone_ref']=s['origin_ref'];st['instance_context']={'kind':'OVERWORLD','ref':s['origin_ref']};w._save_profile(st);vv=m.vehicle(vr);vv['zone_ref']=s['origin_ref'];m._save_vehicle(vv);o=m.travel(pref,vr,s['segment_ref'],event_ref=f's:travel:{i}');ck(f'travel_{i}',o['status']=='PASS',o);travels+=o['status']=='PASS';rp=m.travel(pref,vr,s['segment_ref'],event_ref=f's:travel:{i}');ck(f'replay_{i}',rp.get('idempotent_replay') is True);replays+=rp.get('idempotent_replay') is True;it.grant_item(pref,'MIN-IRON',5,event_ref=f's:iron:{i}');ck(f'cargo_{i}',m.load_cargo(pref,vr,'MIN-IRON',2,event_ref=f's:load:{i}')['status']=='PASS')
# bridge condition churn stays bounded
for x in (100,70,30,5,100): b=m.set_bridge_condition('POI-046',x);ck(f'bridge_{x}',0<=b['capacity_factor']<=1)
# NPC fleet
npcs=[]
for stt in e.country(wid).world['country']['states']:
 for b in stt['blocks']:
  for c in b['cities']:
   for n in c['npcs']:
    if n['class']!='CHILD':npcs.append(n)
for i,n in enumerate(npcs[:4]):
 v=m.create_vehicle(n['id'],'VEH-PROFILE-UTILITY-CARGO',event_ref=f's:npc:create:{i}')['vehicle'];ck(f'npc_zone_{i}',v['zone_ref'] is not None);ck(f'npc_board_{i}',m.board(n['id'],v['vehicle_ref'],event_ref=f's:npc:board:{i}',as_driver=True)['status']=='PASS')
ck('health',e.health_arpg_v10(wid)['status']=='PASS');ck('verify',m.verify()['status']=='PASS',m.verify());ck('vehicle_count',len(m.list_vehicles())>=8);ck('boundary_locked',all(m.segment(x)['boundary_locked'] for x in m.BOUNDARY_ROUTES));ck('cargo_integrity',all(it.inventory_snapshot(v)['owner_kind']=='VEHICLE_CARGO' for v in vehicles))
# deterministic infrastructure on same seed
r2=e.create_world('stress:s10:2',101020);m2=e.mobility_arpg(r2['world']['world_instance_id']);ck('deterministic_segments',[(s['segment_ref'],s['distance_km']) for s in m.list_segments()]==[(s['segment_ref'],s['distance_km']) for s in m2.list_segments()]);e.close()
res={'record_id':'ARPG-STAGE10-STRESS-V1.1.0','checks':len(checks),'passed':sum(x['status']=='PASS' for x in checks),'failed':sum(x['status']=='FAIL' for x in checks),'status':'PASS' if all(x['status']=='PASS' for x in checks) else 'FAIL','metrics':{'profiles':len(profiles),'vehicles':len(vehicles)+4,'travels':travels,'replays':replays},'results':checks};os.makedirs(os.path.dirname(OUT),exist_ok=True);open(OUT,'w',encoding='utf-8').write(json.dumps(res,ensure_ascii=False,indent=2,sort_keys=True));print(json.dumps({k:res[k] for k in ('checks','passed','failed','status','metrics')}));sys.exit(0 if res['status']=='PASS' else 1)
