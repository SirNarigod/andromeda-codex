from __future__ import annotations
import json, os, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_arpg_engine_v01 import IntegratedARPGEngineV01

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
checks=[]
def ck(name,ok,detail=None): checks.append({'name':name,'status':'PASS' if ok else 'FAIL','detail':detail})

with tempfile.TemporaryDirectory() as td:
    db=os.path.join(td,'stress.sqlite')
    e=IntegratedARPGEngineV01(db,master_release_path=MASTER)
    report=e.create_world('arpg-stage01-stress',987654,load_relationships=False)
    wid=report['world']['world_instance_id']; core=e.arpg(wid)
    profiles=[]
    for i,ref in enumerate(['PER-001','PER-002','PER-003','PER-004']):
        profiles.append(core.create_profile(f'net:canon:{i}',origin_mode='CANONICAL',canonical_ref=ref)['profile'])
    for i in range(8):
        profiles.append(core.create_profile(f'net:created:{i}',origin_mode='CREATED',display_name=f'Stress Hero {i}')['profile'])
    ck('PROFILE_CAPACITY_12',len(profiles)==12,len(profiles))
    ck('PROFILE_CORE_AFTER_CREATE',core.verify()['status']=='PASS',core.verify().get('failures'))
    total_commands=0; total_frames=0; blocked_frames=0
    for idx,p in enumerate(profiles):
        scope=p['controller_scope']; seq=0
        for cycle in range(5):
            st=e.movement(wid).state(p['avatar_ref'])
            sign=1 if (cycle+idx)%2==0 else -1
            seq+=1
            out=core.submit_command(scope,p['profile_ref'],seq,'MOVE_POINTER',{'iso_x_m':st['iso_x_m']+sign*0.75,'iso_y_m':st['iso_y_m']+(0.25 if cycle%2 else 0.0),'mode':'WALK'})
            total_commands+=1
            if out.get('status')!='PASS':
                ck(f'MOVE_COMMAND_{idx}_{cycle}',False,out); continue
            for _ in range(2):
                f=core.tick(p['profile_ref'],delta_s=0.08); total_frames+=1
                if f.get('frame_state')=='BLOCKED': blocked_frames+=1; break
                if f.get('frame_state')=='ARRIVED': break
            seq+=1
            out2=core.submit_command(scope,p['profile_ref'],seq,'CANCEL_ACTION',{'clear_target':cycle%3==0}); total_commands+=1
            if out2.get('status')!='PASS': ck(f'CANCEL_COMMAND_{idx}_{cycle}',False,out2)
        hist=core.command_history(p['profile_ref'])
        ck(f'SEQUENCE_CONTIGUOUS_{idx}',[x['client_sequence'] for x in hist]==list(range(1,seq+1)),len(hist))
        replay=core.submit_command(scope,p['profile_ref'],seq,'CANCEL_ACTION',{'clear_target':4%3==0})
        # Exact replay of the final cancel command must be idempotent.
        ck(f'REPLAY_{idx}',replay.get('idempotent_replay') is True,replay.get('reason'))
    ck('TOTAL_COMMANDS_120',total_commands==120,total_commands)
    ck('CORE_POST_STRESS',core.verify()['status']=='PASS',core.verify().get('failures'))
    ck('ENGINE_POST_STRESS',e.health_arpg_v01(wid)['status']=='PASS',e.health_arpg_v01(wid).get('failures'))
    ck('COUNTRY_POST_STRESS',e.country(wid).validate()['status']=='PASS',e.country(wid).validate().get('failures'))
    ck('STREAM_POST_STRESS',e.streaming(wid).full_integrity_check()['status']=='PASS',e.streaming(wid).full_integrity_check().get('failures'))
    e.close()
    e2=IntegratedARPGEngineV01(db,master_release_path=MASTER)
    try:
        r=e2.resume_world(wid); c2=e2.arpg(wid)
        ck('STRESS_RESUME',r.get('status')=='PASS',r)
        ck('STRESS_RESUME_PROFILES',len(c2.list_profiles())==12,len(c2.list_profiles()))
        ck('STRESS_RESUME_COMMANDS',sum(len(c2.command_history(p['profile_ref'])) for p in profiles)==120)
        ck('STRESS_RESUME_HEALTH',e2.health_arpg_v01(wid)['status']=='PASS',e2.health_arpg_v01(wid).get('failures'))
    finally: e2.close()

failed=[c for c in checks if c['status']=='FAIL']
report={'record_id':'ARPG-STAGE01-STRESS-V0.2.0','stage':'01/18','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','metrics':{'profiles':12,'commands':total_commands,'frames':total_frames,'blocked_frames':blocked_frames},'failures':failed}
out=ROOT/'04_REPORTS/ARPG_STAGE01/ARPG_STAGE01_STRESS_V0_2_0.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
raise SystemExit(1 if failed else 0)
