from __future__ import annotations
import json, os, shutil, tempfile, time
from pathlib import Path
from integrated_arpg_engine_v15 import IntegratedARPGEngineV15
MASTER=os.environ.get('ANDROMEDA_MASTER','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
OUT=os.environ.get('ARPG_STAGE15_STRESS_OUT')
checks=[]
def ck(name,cond,detail=None):
    checks.append({'name':name,'status':'PASS' if cond else 'FAIL','detail':detail})
    if not cond: raise AssertionError(f'{name}:{detail}')
root=Path(tempfile.mkdtemp(prefix='andromeda_s15_stress_'))
try:
    db=root/'world.sqlite'; saves=root/'saves'
    e=IntegratedARPGEngineV15(str(db),master_release_path=MASTER,save_root=saves)
    r=e.create_world('stage15:stress',1515999); wid=r['world']['world_instance_id']; rec=e.save_recovery(wid)
    profiles=[]
    for i in range(3):
        p=e.arpg(wid).create_profile(f'local:s15:{i}',display_name=f'S15-{i}',slot_index=i)['profile']; profiles.append(p['profile_ref'])
        e.items_arpg(wid).grant_item(p['profile_ref'],'ITEM-FOOD',i+1,event_ref=f's15:stress:item:{i}')
    ck('three_profiles',len(profiles)==3)
    a=rec.create_snapshot('stress',kind='MANUAL'); ck('save_a',a['status']=='PASS')
    # Mutate all profiles, autosave, verify rotation.
    for i,pr in enumerate(profiles): e.character(wid).award_experience(pr,100+i*25,event_ref=f's15:stress:xp:{i}')
    b=rec.create_snapshot('stress',kind='AUTO'); ck('save_b',b['status']=='PASS')
    ck('rotation_current',rec.verify_slot('stress')['status']=='PASS')
    ck('rotation_previous',rec.verify_slot('stress',generation='previous')['status']=='PASS')
    # 6 death/recovery cycles + idempotent replays.
    for i,pr in enumerate(profiles):
        for j in range(2):
            e.character(wid).apply_health_change(pr,-10**9,event_ref=f's15:stress:kill:{i}:{j}',source_type='STRESS')
            out=rec.recover_death(pr,event_ref=f's15:stress:recover:{i}:{j}')
            ck(f'recover_{i}_{j}',out['status']=='PASS' and out['inventory_preserved'] and out['experience_preserved'])
            rep=rec.recover_death(pr,event_ref=f's15:stress:recover:{i}:{j}')
            ck(f'replay_{i}_{j}',rep.get('idempotent_replay') is True)
    # snapshot post-recovery; corrupt and rollback.
    rec.create_snapshot('stress',kind='POST_STRESS')
    cur,_=rec._paths('stress','current')
    data=bytearray(cur.read_bytes()); data[min(len(data)-1,4096)]^=0x01; cur.write_bytes(data)
    ck('stress_corruption_detected',rec.verify_slot('stress')['status']=='FAIL')
    rec.rollback_slot('stress'); ck('stress_rollback_valid',rec.verify_slot('stress')['status']=='PASS')
    restored=root/'restored.sqlite'; rec.restore_slot_to('stress',restored)
    e.runtime.close()
    e2=IntegratedARPGEngineV15(str(restored),master_release_path=MASTER,save_root=root/'resume_saves')
    t=time.perf_counter(); rr=e2.resume_world(wid); elapsed=time.perf_counter()-t
    ck('multi_profile_resume',rr['arpg_health']['status']=='PASS')
    ck('multi_profile_resume_under_60s',elapsed<60,round(elapsed,3))
    ck('all_profiles_restored',len(e2.arpg(wid).list_profiles())==3)
    ck('health_final',e2.health_arpg_v15(wid)['status']=='PASS')
    e2.runtime.close()
    passed=sum(x['status']=='PASS' for x in checks)
    result={'status':'PASS' if passed==len(checks) else 'FAIL','checks':len(checks),'passed':passed,'failed':len(checks)-passed,'resume_seconds':round(elapsed,3),'results':checks}
    if OUT: Path(OUT).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('status','checks','passed','failed','resume_seconds')},ensure_ascii=False))
finally:
    # Explicit cleanup, after all output has been flushed; no TemporaryDirectory finalizer involved.
    shutil.rmtree(root,ignore_errors=True)
