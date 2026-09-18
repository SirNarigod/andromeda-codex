from __future__ import annotations
import json, math, os, sys, tempfile
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_arpg_engine_v03 import IntegratedARPGEngineV03
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
checks=[]
def ck(n,o,d=None): checks.append({'name':n,'status':'PASS' if o else 'FAIL','detail':d})
def colocate(e,wid,a,b):
    ps=e.movement(wid).state(a); geo=e.spatial(wid).isometric_to_geodetic(ps['iso_x_m'],ps['iso_y_m'],ps['altitude_m']); e.movement(wid).sync_to_geodetic(b,geo,reason='STAGE03_STRESS_COLOCATE')
with tempfile.TemporaryDirectory() as td:
    db=os.path.join(td,'stress03.sqlite'); e=IntegratedARPGEngineV03(db,master_release_path=MASTER); rep=e.create_world('stage03-stress',93303,load_relationships=False); wid=rep['world']['world_instance_id']; a=e.arpg(wid); c=e.combat_arpg(wid)
    profiles=[a.create_profile(f'controller:{i}',origin_mode='CREATED',display_name=f'Combat Stress {i}')['profile'] for i in range(4)]
    ck('PROFILES_4',len(profiles)==4,len(profiles))
    candidates=[n['id'] for n in e.country(wid)._all_npc_records() if not (n.get('protection') or {}).get('protected') and (n.get('protection') or {}).get('combat_targetable',True) and n['id'] not in {p['avatar_ref'] for p in profiles}][:8]
    ck('TARGETS_8',len(candidates)==8,len(candidates))
    attacks=0; passes=0; replays=0; status_ticks=0
    for i,p in enumerate(profiles):
        target=candidates[i]
        colocate(e,wid,p['avatar_ref'],target); c.ensure_player(p['profile_ref']); est=c.ensure_enemy(target)
        for j in range(12):
            c.tick_player(p['profile_ref'],1.0)
            out=c.player_attack(p['profile_ref'],target,event_ref=f'stress:{i}:attack:{j}'); attacks+=1
            if out['status']=='PASS': passes+=1
            if j in (2,7):
                rr=c.player_attack(p['profile_ref'],target,event_ref=f'stress:{i}:attack:{j}')
                if rr.get('idempotent_replay'): replays+=1
            if c.ensure_enemy(target)['life_state']!='ALIVE':
                # keep stress actor alive without changing Country/Master; Stage03 overlay only.
                st=c.ensure_enemy(target); st['life_state']='ALIVE'; st['health']=st['max_health']; c._save_row('arpg_enemy_combat_state',target,st)
        c.apply_status(target,status_ref=f'STRESS_DOT_{i}',duration_s=1.0,magnitude_per_s=2.0,damage_type='TOXIC',source_ref=p['avatar_ref'],event_ref=f'stress:{i}:status')
        c.tick_actor(target,.5); c.tick_actor(target,.5); status_ticks+=2
        ck(f'PROFILE_{i}_OVERLAY',c.overlay(p['avatar_ref'])['attack_cooldown_remaining_s']>=0)
    ck('ATTACKS_48',attacks==48,attacks); ck('ATTACK_PASSES',passes>=32,passes); ck('REPLAYS_8',replays==8,replays); ck('STATUS_TICKS_8',status_ticks==8,status_ticks)
    ck('COMBAT_VERIFY',c.verify()['status']=='PASS',c.verify().get('failures')); ck('ENGINE_VERIFY',e.health_arpg_v03(wid)['status']=='PASS',e.health_arpg_v03(wid).get('failures'))
    before={t:c.ensure_enemy(t) for t in candidates[:4]}; pbefore={p['profile_ref']:c.overlay(p['avatar_ref']) for p in profiles}; events=len(c.event_history()); e.close()
    e2=IntegratedARPGEngineV03(db,master_release_path=MASTER); r=e2.resume_world(wid); c2=e2.combat_arpg(wid); ck('RESUME',r['status']=='PASS'); ck('RESUME_ENEMIES',all(c2.ensure_enemy(k)==v for k,v in before.items())); ck('RESUME_OVERLAYS',all(c2.overlay(e2.arpg(wid).profile(k)['avatar_ref'])==v for k,v in pbefore.items())); ck('RESUME_EVENTS',len(c2.event_history())==events,(len(c2.event_history()),events)); ck('RESUME_VERIFY',e2.health_arpg_v03(wid)['status']=='PASS',e2.health_arpg_v03(wid).get('failures')); e2.close()
failed=[x for x in checks if x['status']=='FAIL']
report={'record_id':'ARPG-STAGE03-STRESS-V0.4.0','stage':'03/18','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','metrics':{'profiles':4,'targets':8,'attack_attempts':attacks,'attack_passes':passes,'idempotent_replays':replays,'status_ticks':status_ticks,'combat_events':events},'failures':failed}
(ROOT/'04_REPORTS/ARPG_STAGE03/ARPG_STAGE03_STRESS_V0_4_0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
raise SystemExit(1 if failed else 0)
