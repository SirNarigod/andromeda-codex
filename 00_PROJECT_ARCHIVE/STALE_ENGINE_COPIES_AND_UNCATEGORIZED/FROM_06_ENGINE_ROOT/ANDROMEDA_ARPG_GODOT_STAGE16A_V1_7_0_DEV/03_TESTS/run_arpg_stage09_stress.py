import json,os,sys
from integrated_arpg_engine_v09 import IntegratedARPGEngineV09
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip');OUT=os.environ.get('ARPG_STAGE09_STRESS_OUT','04_REPORTS/ARPG_STAGE09/ARPG_STAGE09_STRESS_V1_0_0.json')
checks=[]
def ck(n,o,d=None):checks.append({'name':n,'status':'PASS' if o else 'FAIL','detail':d})
e=IntegratedARPGEngineV09(':memory:',master_release_path=MASTER);r=e.create_world('stress:s09',99009);wid=r['world']['world_instance_id'];g=e.gathering_arpg(wid);it=e.items_arpg(wid);w=e.world_arpg(wid)
profiles=[];operations=0;replays=0
for pi in range(3):
 p=e.arpg(wid).create_profile(f'stress:s09:{pi}',origin_mode='CREATED',display_name=f'Worker {pi}')['profile'];ref=p['profile_ref'];profiles.append(ref);g.ensure_worker(ref)
 for a in g.ACTIVITIES:g.assign_role(ref,a)
 it.grant_item(ref,'ITEM-TOOL',1,event_ref=f's:{pi}:tool');it.grant_item(ref,'WPN-001',1,event_ref=f's:{pi}:wpn')
 for ai,a in enumerate(g.ACTIVITIES):
  nodes=g.list_nodes(activity_type=a)
  if a=='HUNTING':nodes=[n for n in nodes if n['source_meta'].get('role')!='PREDATOR'] or nodes
  n=nodes[(pi+ai)%len(nodes)];st=w.ensure_profile(ref);st['zone_ref']=n['zone_ref'];st['instance_context']={'kind':'OVERWORLD','ref':n['zone_ref']};w._save_profile(st)
  ev=f's:{pi}:{a}';o=g.create_work_order(ref,n['node_ref'],2,event_ref=ev+':c');ck(ev+':create',o['status']=='PASS',o)
  if o['status']=='PASS':
   x=g.execute_work_order(o['order']['order_ref'],event_ref=ev+':x',danger_clearance_ref='STRESS_CLEARANCE' if a=='HUNTING' else None);ck(ev+':execute',x['status']=='PASS',x);operations+=1
   rp=g.execute_work_order(o['order']['order_ref'],event_ref=ev+':x',danger_clearance_ref='STRESS_CLEARANCE' if a=='HUNTING' else None);ck(ev+':replay',rp.get('idempotent_replay') is True);replays+=1
ck('verify',g.verify()['status']=='PASS',g.verify());ck('all_nodes_nonnegative',all(n['remaining_units']>=0 for n in g.list_nodes()));ck('workers_progress',all(g.worker(p)['completed_orders']>0 for p in profiles));ck('profession_bridge',g.employment_bridge()['status']=='PASS')
# deterministic node topology repeat within same process
r2=e.create_world('stress:s09:repeat',99009);g2=e.gathering_arpg(r2['world']['world_instance_id']);ck('deterministic_topology',[n['node_ref'] for n in g.list_nodes()]==[n['node_ref'] for n in g2.list_nodes()])
e.close();res={'record_id':'ARPG-STAGE09-STRESS-V1.0.0','checks':len(checks),'passed':sum(x['status']=='PASS' for x in checks),'failed':sum(x['status']=='FAIL' for x in checks),'profiles':len(profiles),'operations':operations,'replays':replays,'status':'PASS' if all(x['status']=='PASS' for x in checks) else 'FAIL','results':checks};os.makedirs(os.path.dirname(OUT),exist_ok=True);open(OUT,'w',encoding='utf-8').write(json.dumps(res,ensure_ascii=False,indent=2,sort_keys=True));print(json.dumps({k:res[k] for k in ('checks','passed','failed','profiles','operations','replays','status')}));sys.exit(0 if res['status']=='PASS' else 1)
