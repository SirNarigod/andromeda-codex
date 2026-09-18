from __future__ import annotations
import json, os, sys, tempfile
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_arpg_engine_v02 import IntegratedARPGEngineV02
from character_core import CharacterCore
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
checks=[]
def ck(n,o,d=None): checks.append({'name':n,'status':'PASS' if o else 'FAIL','detail':d})
with tempfile.TemporaryDirectory() as td:
    db=os.path.join(td,'stress02.sqlite'); e=IntegratedARPGEngineV02(db,master_release_path=MASTER)
    rep=e.create_world('stage02-stress',992202,load_relationships=False); wid=rep['world']['world_instance_id']; a=e.arpg(wid); c=e.character(wid)
    profiles=[]
    for i in range(4): profiles.append(a.create_profile(f'controller:{i}',origin_mode='CREATED',display_name=f'Stress02 {i}')['profile'])
    ck('PROFILES_4',len(profiles)==4,len(profiles))
    total_events=0
    for i,p in enumerate(profiles):
        need=c.xp_to_next(1)
        x=c.award_experience(p['profile_ref'],need,event_ref=f'stress:xp:{i}'); total_events+=1
        alloc={('VITALITY' if i%2==0 else 'POWER'):5}
        c.allocate_attributes(p['profile_ref'],alloc,event_ref=f'stress:attr:{i}'); total_events+=1
        c.apply_health_change(p['profile_ref'],-25,event_ref=f'stress:hp:{i}'); total_events+=1
        c.apply_resource_change(p['profile_ref'],-20,event_ref=f'stress:res:{i}'); total_events+=1
        for _ in range(5): c.tick_profile(p['profile_ref'],0.1)
        ck(f'PROFILE_VERIFY_{i}',c.state(p['profile_ref'])['level']==2 and c.state(p['profile_ref'])['unspent_attribute_points']==0)
        replay=c.award_experience(p['profile_ref'],need,event_ref=f'stress:xp:{i}')
        ck(f'XP_REPLAY_{i}',replay.get('idempotent_replay') is True)
    ck('EVENTS_16',sum(len(c.event_history(p['profile_ref'])) for p in profiles)==16)
    ck('CHAR_VERIFY',c.verify()['status']=='PASS',c.verify().get('failures'))
    ck('ENGINE_VERIFY',e.health_arpg_v02(wid)['status']=='PASS',e.health_arpg_v02(wid).get('failures'))
    before={p['profile_ref']:c.state(p['profile_ref']) for p in profiles}; e.close()
    e2=IntegratedARPGEngineV02(db,master_release_path=MASTER); r=e2.resume_world(wid); c2=e2.character(wid)
    ck('RESUME',r['status']=='PASS'); ck('RESUME_STATES',all(c2.state(k)==v for k,v in before.items()))
    ck('RESUME_VERIFY',e2.health_arpg_v02(wid)['status']=='PASS',e2.health_arpg_v02(wid).get('failures')); e2.close()
failed=[x for x in checks if x['status']=='FAIL']
report={'record_id':'ARPG-STAGE02-STRESS-V0.3.0','stage':'02/18','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','metrics':{'profiles':4,'character_events':16,'regen_ticks':20},'failures':failed}
(ROOT/'04_REPORTS/ARPG_STAGE02/ARPG_STAGE02_STRESS_V0_3_0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
raise SystemExit(1 if failed else 0)
