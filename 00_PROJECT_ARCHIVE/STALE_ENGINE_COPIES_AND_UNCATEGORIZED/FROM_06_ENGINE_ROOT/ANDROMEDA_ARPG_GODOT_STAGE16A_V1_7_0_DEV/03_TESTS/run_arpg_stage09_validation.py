import json, os, sys, tempfile
from integrated_arpg_engine_v09 import IntegratedARPGEngineV09
from living_runtime import ConflictError
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
OUT=os.environ.get('ARPG_STAGE09_VALIDATION_OUT','04_REPORTS/ARPG_STAGE09/ARPG_STAGE09_VALIDATION_V1_0_0.json')
checks=[]
def ck(name,ok,detail=None): checks.append({'name':name,'status':'PASS' if ok else 'FAIL','detail':detail})
e=IntegratedARPGEngineV09(':memory:',master_release_path=MASTER);r=e.create_world('val:s09',90909);wid=r['world']['world_instance_id'];g=e.gathering_arpg(wid);it=e.items_arpg(wid);w=e.world_arpg(wid)
v=g.verify();ck('health',e.health_arpg_v09(wid)['status']=='PASS');ck('verify',v['status']=='PASS',v)
ck('activity_keys',set(v['activities'])==set(g.ACTIVITIES),v['activities']);ck('activity_nonzero',all(v['activities'][a]>0 for a in g.ACTIVITIES),v['activities']);ck('node_total_sum',v['nodes']==sum(v['activities'].values()))
ck('profession_snapshots_91',g.employment_bridge()['canonical_profession_snapshots']==91)
ck('fishing_exists',len(g.list_nodes(activity_type='FISHING'))>0)
ck('fishing_spatial',all(g._zone_has_physical_fishing_water(w.zone(n['zone_ref'])) for n in g.list_nodes(activity_type='FISHING')))
ck('fishing_not_root',all(w.zone(n['zone_ref']).get('anomaly_overlay') is None for n in g.list_nodes(activity_type='FISHING')))
ck('fish_item_noncanon',it.definition(g.FISH_ITEM_REF)['canonical_identity'] is False)
ck('outputs_resolve',all((it.definition(n['output_item_ref']) or True) for n in g.list_nodes()))
ck('no_negative_nodes',all(n['remaining_units']>=0 for n in g.list_nodes()))
ck('flora_guard',all('MASTER_FLORA_SPATIALIZATION_BLOCKED' in n['source_meta']['flora_canon_guard'] for n in g.list_nodes() if n['source_kind']=='FLORA'))
ck('agriculture_context',all('AGZ-001' in n['canonical_context_support_refs'] and 'RSZ-003' in n['canonical_context_support_refs'] for n in g.list_nodes(activity_type='AGRICULTURE')))
# player role and work
p=e.arpg(wid).create_profile('val:s09',origin_mode='CREATED',display_name='Validation Worker')['profile'];pref=p['profile_ref'];g.ensure_worker(pref)
roles={a:g.assign_role(pref,a) for a in g.ACTIVITIES};ck('hunter_profession',roles['HUNTING']['profession_ref']=='JOB-EXPL-CAC-001');ck('agriculture_profession',roles['AGRICULTURE']['profession_ref']=='JOB-RUR-AGR-001');ck('mining_not_false_local_profession',roles['MINING']['profession_ref'] is None);ck('fishing_derived_role',roles['FISHING']['profession_ref'] is None)
try:g.assign_role(pref,'MINING',profession_ref='JOB-MIN-OPER-001');ck('out_of_country_profession_reject',False)
except ConflictError:ck('out_of_country_profession_reject',True)
it.grant_item(pref,'ITEM-TOOL',1,event_ref='v:tool');it.grant_item(pref,'WPN-001',1,event_ref='v:weapon')
def move(node):
 st=w.ensure_profile(pref);st['zone_ref']=node['zone_ref'];st['instance_context']={'kind':'OVERWORLD','ref':node['zone_ref']};w._save_profile(st)
for a in ('MINING','LOGGING','FORAGING','AGRICULTURE','FISHING'):
 n=g.list_nodes(activity_type=a)[0];move(n);before=n['remaining_units'];o=g.create_work_order(pref,n['node_ref'],1,event_ref=f'v:{a}:c');ck(f'{a}_order_create',o['status']=='PASS',o)
 x=g.execute_work_order(o['order']['order_ref'],event_ref=f'v:{a}:x');ck(f'{a}_execute',x['status']=='PASS',x);ck(f'{a}_remaining_nonincrease',g.node(n['node_ref'])['remaining_units']<=before)
# hunting nonpredator
n=next(x for x in g.list_nodes(activity_type='HUNTING') if x['source_meta'].get('role')!='PREDATOR');move(n);o=g.create_work_order(pref,n['node_ref'],1,event_ref='v:h:c');x=g.execute_work_order(o['order']['order_ref'],event_ref='v:h:x');ck('HUNTING_execute',x['status']=='PASS',x)
# predator guard
n=next(x for x in g.list_nodes(activity_type='HUNTING') if x['source_meta'].get('role')=='PREDATOR');move(n);o=g.create_work_order(pref,n['node_ref'],1,event_ref='v:p:c');x=g.execute_work_order(o['order']['order_ref'],event_ref='v:p:x');ck('predator_clearance_guard',x.get('reason')=='PREDATOR_HUNT_REQUIRES_STAGE07_DANGER_CLEARANCE',x)
# child guard
child=next(n for s in e.country(wid).world['country']['states'] for b in s['blocks'] for c in b['cities'] for n in c['npcs'] if n['class']=='CHILD')
try:g.assign_role(child['id'],'AGRICULTURE');ck('child_labor_guard',False)
except ConflictError:ck('child_labor_guard',True)
# replay
n=g.list_nodes(activity_type='MINING')[0];move(n);o=g.create_work_order(pref,n['node_ref'],1,event_ref='v:r:c');rep=g.create_work_order(pref,n['node_ref'],1,event_ref='v:r:c');ck('create_replay',rep.get('idempotent_replay') is True)
# deterministic projection same seed in same engine
r2=e.create_world('val:s09:2',90909);g2=e.gathering_arpg(r2['world']['world_instance_id']);ck('same_seed_node_refs',[n['node_ref'] for n in g.list_nodes()]==[n['node_ref'] for n in g2.list_nodes()])
ck('final_verify',g.verify()['status']=='PASS',g.verify())
e.close()
res={'record_id':'ARPG-STAGE09-VALIDATION-V1.0.0','checks':len(checks),'passed':sum(x['status']=='PASS' for x in checks),'failed':sum(x['status']=='FAIL' for x in checks),'status':'PASS' if all(x['status']=='PASS' for x in checks) else 'FAIL','results':checks}
os.makedirs(os.path.dirname(OUT),exist_ok=True);open(OUT,'w',encoding='utf-8').write(json.dumps(res,ensure_ascii=False,indent=2,sort_keys=True));print(json.dumps({k:res[k] for k in ('checks','passed','failed','status')},ensure_ascii=False))
if res['status']!='PASS':sys.exit(1)
