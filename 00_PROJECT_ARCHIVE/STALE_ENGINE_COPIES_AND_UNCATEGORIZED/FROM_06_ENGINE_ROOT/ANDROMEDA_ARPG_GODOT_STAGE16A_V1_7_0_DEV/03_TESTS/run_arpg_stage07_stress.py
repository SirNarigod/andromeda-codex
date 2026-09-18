from __future__ import annotations
import json, os, sys, tempfile
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,os.path.join(ROOT,'01_RUNTIME'))
from integrated_arpg_engine_v07 import IntegratedARPGEngineV07
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

def main():
    checks=[]
    def ck(n,c,d=None): checks.append({'name':n,'status':'PASS' if c else 'FAIL','detail':d})
    with tempfile.TemporaryDirectory() as td:
        db=os.path.join(td,'s.sqlite'); e=IntegratedARPGEngineV07(db,master_release_path=MASTER); wid=e.create_world('stage07:stress',72727)['world']['world_instance_id']; arpg=e.arpg(wid); ac=e.actors_arpg(wid)
        ps=[arpg.create_profile(f'local:{i}',origin_mode='CREATED',display_name=f'P{i}')['profile'] for i in range(2)]
        npcs=[n for n in e.country(wid)._all_npc_records() if all(n['id']!=p['avatar_ref'] for p in ps) and not (n.get('protection') or {}).get('protected')][:8]
        ck('actors_8',len(npcs)==8,len(npcs))
        for i,n in enumerate(npcs):
            out=ac.set_disposition(n['id'],'HOSTILE',event_ref=f's:hostile:{i}'); ck(f'hostile:{i}',out['status']=='PASS')
            rank=['COMMON','CHAMPION','ELITE','COMMON','CHAMPION','ELITE','MINIBOSS','BOSS'][i]
            r=ac.set_combat_rank(n['id'],rank,event_ref=f's:rank:{i}'); ck(f'rank:{i}',r['status']=='PASS')
            # deterministic replay must not rescale twice
            rr=ac.set_combat_rank(n['id'],rank,event_ref=f's:rank:{i}'); ck(f'rank_replay:{i}',rr.get('idempotent_replay') is True)
        # Put all hostile actors around profile 0 and run 20 frames; tick limit exercises nearby budget.
        p0=ps[0]; pos=e.movement(wid).state(p0['avatar_ref'])
        for i,n in enumerate(npcs):
            geo=e.spatial(wid).isometric_to_geodetic(pos['iso_x_m']+2.0+(i%4)*0.4,pos['iso_y_m']+(i//4)*0.4,pos['altitude_m']); e.movement(wid).sync_to_geodetic(n['id'],geo,reason='STRESS07')
        frames=0; ai_ticks=0
        for _ in range(20):
            out=e.tick_arpg(p0['profile_ref'],delta_s=.2,max_ai_actors=8); frames+=1; ai_ticks+=out['actors']['ticked'];
            if e.character(wid).state(p0['profile_ref'])['vitals']['life_state']!='ALIVE': break
        ck('frames_positive',frames>0,frames); ck('ai_ticks_positive',ai_ticks>0,ai_ticks); ck('actor_verify',ac.verify()['status']=='PASS',ac.verify().get('failures')); ck('health',e.health_arpg_v07(wid)['status']=='PASS',e.health_arpg_v07(wid).get('failures'))
        before={n['id']:(ac.actor(n['id'])['disposition'],ac.actor(n['id'])['combat_rank']) for n in npcs}; e.close()
        e2=IntegratedARPGEngineV07(db,master_release_path=MASTER); e2.resume_world(wid); ac2=e2.actors_arpg(wid); after={n['id']:(ac2.actor(n['id'])['disposition'],ac2.actor(n['id'])['combat_rank']) for n in npcs}; ck('restore_all_actor_profiles',before==after); ck('restore_verify',ac2.verify()['status']=='PASS',ac2.verify().get('failures')); e2.close()
    failed=[x for x in checks if x['status']=='FAIL']; out={'record_id':'ARPG-STAGE07-STRESS-V0.8.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','frames':frames,'ai_ticks':ai_ticks,'hostile_actors':len(npcs),'failures':failed}; print(json.dumps(out,ensure_ascii=False,indent=2)); return 0 if not failed else 1
if __name__=='__main__': raise SystemExit(main())
