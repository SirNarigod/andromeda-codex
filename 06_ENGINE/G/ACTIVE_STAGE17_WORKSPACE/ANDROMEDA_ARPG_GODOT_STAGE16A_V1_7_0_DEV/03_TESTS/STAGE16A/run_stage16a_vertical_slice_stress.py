from __future__ import annotations
import json, os, pathlib, shutil, tempfile
import sys
ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_arpg_engine_v16a import IntegratedARPGEngineV16A
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
OUT=os.environ.get('ARPG_STAGE16A_STRESS_OUT')
checks=[]
def ck(name, cond, detail=None):
    checks.append({'name':name,'status':'PASS' if cond else 'FAIL','detail':detail})
    if not cond: raise AssertionError(f'{name}:{detail}')
root=pathlib.Path(tempfile.mkdtemp(prefix='s16a_stress_'))
try:
    db=root/'world.sqlite'; e=IntegratedARPGEngineV16A(str(db),master_release_path=MASTER,save_root=root/'saves')
    wid=e.create_world('s16a:stress',161699)['world']['world_instance_id']; s=e.stage16a(wid)
    ck('01_bootstrap',e.health_arpg_v16a(wid)['status']=='PASS')
    profiles=[]
    for i in range(4):
        p=e.arpg(wid).create_profile(f's16a:stress:{i}',display_name=f'Stress {i}')['profile']; profiles.append(p)
        e.items_arpg(wid).ensure_inventory(p['profile_ref']); s.set_auto_pickup(p['profile_ref'],True,event_ref=f'stress:auto:{i}')
    ck('02_profiles_created',len(profiles)==4)
    ck('03_preferences_enabled',all(s.ensure_profile_preferences(p['profile_ref'])['auto_pickup_enabled'] for p in profiles))
    travel=[]
    for i,p in enumerate(profiles):
        pr=p['profile_ref']; before=e.movement(wid).state(p['avatar_ref'])['stamina']
        x=s.traversal_effect(pr,distance_m=10+i,slope_deg=4+i,surface_ref='GRASS_FIELD',event_ref=f'stress:travel:{i}')
        after=e.movement(wid).state(p['avatar_ref'])['stamina']; travel.append((before,after,x))
    ck('04_traversal_pass',all(x[2]['status']=='PASS' for x in travel))
    before_replay=[e.movement(wid).state(p['avatar_ref'])['stamina'] for p in profiles]
    for i,p in enumerate(profiles): s.traversal_effect(p['profile_ref'],distance_m=10+i,slope_deg=4+i,surface_ref='GRASS_FIELD',event_ref=f'stress:travel:{i}')
    after_replay=[e.movement(wid).state(p['avatar_ref'])['stamina'] for p in profiles]
    ck('05_traversal_replay_idempotent',before_replay==after_replay)
    ck('06_stamina_range',all(0<=x<=100 for x in after_replay))
    drops=[]
    for i,p in enumerate(profiles):
        pos=e.movement(wid).state(p['avatar_ref'])
        for j in range(6):
            d=s.ground_loot.spawn_drop(source_ref=p['avatar_ref'],source_kind='PLAYER_DROP',item_ref='ITEM-GRAIN',item_kind='MATERIAL',quantity=1,candidate_position=pos,event_ref=f'stress:drop:{i}:{j}')['drop_ref']
            s.confirm_drop_settled(d,settled_position=pos,reachable=True,event_ref=f'stress:settle:{i}:{j}'); drops.append((p['profile_ref'],d,j))
    ck('07_spawn_count',len(drops)==24)
    ck('08_settled_count',all(s.ground_loot.drop(d)['settled'] for _,d,_ in drops))
    picked=0
    for i,p in enumerate(profiles):
        own=[(d,j) for pr,d,j in drops if pr==p['profile_ref']]
        distances={d:(0.2 if j%2==0 else 0.8) for d,j in own}
        out=s.auto_pickup_nearby(p['profile_ref'],distances,event_prefix=f'stress:pickup:{i}'); picked+=len(out['picked'])
    ck('09_auto_pickup_runs',picked>0)
    ck('10_picked_total',picked==12,picked)
    active=s.ground_loot.active_drops(); ck('11_active_remaining',len(active)==12,len(active))
    ck('12_active_all_settled',all(d['settled'] and d['reachable'] for d in active))
    received=sum(e.items_arpg(wid).inventory_snapshot(p['profile_ref'])['stacks'].get('ITEM-GRAIN',0) for p in profiles)
    ck('13_inventory_received_exact',received==12,received)
    snap=e.save_recovery(wid).create_snapshot('stress-slot',kind='MANUAL'); ck('14_snapshot',snap['status']=='PASS')
    ck('15_slot_verify',e.save_recovery(wid).verify_slot('stress-slot')['status']=='PASS')
    restored=root/'restored.sqlite'; rr=e.save_recovery(wid).restore_slot_to('stress-slot',restored); ck('16_restore_copy',rr['status']=='PASS')
    e.runtime.close(); e2=IntegratedARPGEngineV16A(str(restored),master_release_path=MASTER,save_root=root/'restored_saves'); r=e2.resume_world(wid); s2=e2.stage16a(wid)
    ck('17_resume_health',r['arpg_health']['status']=='PASS')
    ck('18_preferences_survive',all(s2.ensure_profile_preferences(p['profile_ref'])['auto_pickup_enabled'] for p in profiles))
    ck('19_active_drops_survive',len(s2.ground_loot.active_drops())==12)
    ck('20_final_verify',s2.verify()['status']=='PASS' and e2.health_arpg_v16a(wid)['status']=='PASS')
    e2.runtime.close()
    result={'status':'PASS','checks':len(checks),'passed':sum(x['status']=='PASS' for x in checks),'failed':sum(x['status']=='FAIL' for x in checks),'results':checks}
    if OUT: pathlib.Path(OUT).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('status','checks','passed','failed')}))
finally:
    shutil.rmtree(root,ignore_errors=True)
