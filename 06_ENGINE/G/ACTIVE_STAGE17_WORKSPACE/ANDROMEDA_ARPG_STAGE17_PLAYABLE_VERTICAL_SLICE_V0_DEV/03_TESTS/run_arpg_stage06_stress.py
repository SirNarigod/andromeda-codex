from __future__ import annotations
import json, os, sys, tempfile
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,os.path.join(ROOT,'01_RUNTIME'))
from integrated_arpg_engine_v06 import IntegratedARPGEngineV06
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

def main():
    checks=[]
    def ck(n,c,d=None): checks.append({'name':n,'status':'PASS' if c else 'FAIL','detail':d})
    with tempfile.TemporaryDirectory() as td:
        db=os.path.join(td,'s.sqlite'); e=IntegratedARPGEngineV06(db,master_release_path=MASTER); wid=e.create_world('stage06:stress',62626)['world']['world_instance_id']; sk=e.skills_arpg(wid); profiles=[]
        npcs=[n for n in e.country(wid)._all_npc_records() if not (n.get('protection') or {}).get('protected')]
        total_uses=0; total_replays=0
        for pi in range(2):
            p=e.arpg(wid).create_profile(f'local:s{pi}',origin_mode='CREATED',display_name=f'S{pi}')['profile']; pref=p['profile_ref']; profiles.append(pref)
            for j,ref in enumerate(['SKL-GP-POWER-STRIKE','SKL-GP-PRECISION-STRIKE','SKL-GP-FOCUS-PULSE','SKL-GP-GUARD-DISCIPLINE']): sk.learn_skill(pref,ref,event_ref=f's:{pi}:learn:{j}',source_ref='STRESS')
            sk.assign_active(pref,'SKL-GP-POWER-STRIKE',1,event_ref=f's:{pi}:a1'); sk.assign_active(pref,'SKL-GP-PRECISION-STRIKE',2,event_ref=f's:{pi}:a2'); sk.activate_passive(pref,'SKL-GP-GUARD-DISCIPLINE',1,event_ref=f's:{pi}:p1')
            target=next(n['id'] for n in npcs if n['id']!=p['avatar_ref']); pos=e.movement(wid).state(p['avatar_ref']); geo=e.spatial(wid).isometric_to_geodetic(pos['iso_x_m'],pos['iso_y_m'],pos['altitude_m']); e.movement(wid).sync_to_geodetic(target,geo,reason='STRESS')
            for i in range(6):
                e.combat_arpg(wid).tick_player(pref,1.0); e.resources_arpg(wid).tick_profile(pref,1.0); e.resources_arpg(wid).tick_profile(pref,0.5)
                ch=e.character(wid); st=ch.state(pref); miss=st['derived']['max_resource']-st['vitals']['resource']
                if miss>0: ch.apply_resource_change(pref,miss,event_ref=f's:{pi}:r:{i}',source_type='STRESS')
                en=e.combat_arpg(wid).ensure_enemy(target)
                if en['life_state']!='ALIVE' or en['health']<5: en['life_state']='ALIVE'; en['health']=en['max_health']; e.combat_arpg(wid)._save_row('arpg_enemy_combat_state',target,en)
                ref=f's:{pi}:use:{i}'; out=sk.use_slot(pref,1 if i%2==0 else 2,event_ref=ref,target_ref=target); ck(f'use:{pi}:{i}',out['status']=='PASS',out.get('reason')); total_uses+=out['status']=='PASS'; replay=sk.use_slot(pref,1 if i%2==0 else 2,event_ref=ref,target_ref=target); ck(f'replay:{pi}:{i}',replay.get('idempotent_replay') is True); total_replays+=bool(replay.get('idempotent_replay'))
            ck(f'evidence:{pi}',sk.build_signature(pref)['evidence_total']>0); ck(f'passive:{pi}',e.combat_arpg(wid).player_stats(pref)['skill_modifiers']['active_passives'][0]['skill_ref']=='SKL-GP-GUARD-DISCIPLINE')
        ck('health',e.health_arpg_v06(wid)['status']=='PASS'); ck('verify',sk.verify()['status']=='PASS'); before={p:sk.snapshot(p) for p in profiles}; e.close(); e2=IntegratedARPGEngineV06(db,master_release_path=MASTER); e2.resume_world(wid); ck('restore_health',e2.health_arpg_v06(wid)['status']=='PASS');
        for p in profiles:
            ck('restore:'+p,e2.skills_arpg(wid).snapshot(p)['learned']==before[p]['learned'])
        e2.close()
    failed=[x for x in checks if x['status']=='FAIL']; out={'record_id':'ARPG-STAGE06-STRESS-V0.7.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'successful_uses':int(total_uses),'idempotent_replays':int(total_replays),'profiles':2,'status':'PASS' if not failed else 'FAIL','failures':failed}; print(json.dumps(out,ensure_ascii=False,indent=2)); return 0 if not failed else 1
if __name__=='__main__': raise SystemExit(main())
