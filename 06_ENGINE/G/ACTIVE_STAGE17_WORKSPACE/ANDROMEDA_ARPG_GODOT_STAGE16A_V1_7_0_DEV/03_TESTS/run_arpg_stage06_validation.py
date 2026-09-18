from __future__ import annotations
import json, os, sys, tempfile
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,os.path.join(ROOT,'01_RUNTIME'))
from integrated_arpg_engine_v06 import IntegratedARPGEngineV06
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

def main():
    checks=[]
    def ck(n,c,d=None): checks.append({'name':n,'status':'PASS' if c else 'FAIL','detail':d})
    with tempfile.TemporaryDirectory() as td:
        db=os.path.join(td,'v.sqlite'); e=IntegratedARPGEngineV06(db,master_release_path=MASTER); wid=e.create_world('stage06:validation',61616)['world']['world_instance_id']; sk=e.skills_arpg(wid)
        ck('health',e.health_arpg_v06(wid)['status']=='PASS'); defs=sk.list_definitions(); ck('defs_36',len(defs)==36,len(defs)); ck('canon_30',sum(d['source_authority']=='MASTER_READ_ONLY' for d in defs)==30); ck('derived_6',sum(d['source_authority']=='GAMEPLAY_DERIVED_REPLACEABLE' for d in defs)==6)
        for ref,name in [('SKL-CANON-MAG-007','Estase de Intervalo'),('SKL-CANON-MAG-009','Pele de Guarda'),('SKL-CANON-MAG-011','Passo de Encosta')]:
            d=sk.definition(ref); ck(ref+':identity',d['name']==name); ck(ref+':guard',not d['player_castable_default'] and d['runtime_mapping']=='AUTHORIAL_OR_LATER_SYSTEM_MAPPING_REQUIRED')
        p=e.arpg(wid).create_profile('local:v',origin_mode='CREATED',display_name='V')['profile']; pref=p['profile_ref']; avatar=p['avatar_ref']; s=sk.snapshot(pref); ck('no_fixed_class',s['build_signature']['fixed_class'] is None); ck('empty_learning',not s['learned'])
        for i,ref in enumerate(['SKL-GP-POWER-STRIKE','SKL-GP-PRECISION-STRIKE','SKL-GP-GUARD-DISCIPLINE']): ck('learn:'+ref,sk.learn_skill(pref,ref,event_ref=f'v:learn:{i}',source_ref='TRAINER')['status']=='PASS')
        ck('assign_active',sk.assign_active(pref,'SKL-GP-POWER-STRIKE',1,event_ref='v:assign')['status']=='PASS'); base=e.combat_arpg(wid).player_stats(pref)['armor']; ck('passive_assign',sk.activate_passive(pref,'SKL-GP-GUARD-DISCIPLINE',1,event_ref='v:passive')['status']=='PASS'); ck('passive_applied',e.combat_arpg(wid).player_stats(pref)['armor']>base)
        target=next(n['id'] for n in e.country(wid)._all_npc_records() if n['id']!=avatar and not (n.get('protection') or {}).get('protected')); pos=e.movement(wid).state(avatar); geo=e.spatial(wid).isometric_to_geodetic(pos['iso_x_m'],pos['iso_y_m'],pos['altitude_m']); e.movement(wid).sync_to_geodetic(target,geo,reason='VALIDATION')
        before=e.character(wid).state(pref)['vitals']['resource']; use=sk.use_slot(pref,1,event_ref='v:use',target_ref=target); ck('use_pass',use['status']=='PASS',use.get('reason')); ck('resource_spent',e.character(wid).state(pref)['vitals']['resource']<before); ck('skill_combat_event',use.get('effect',{}).get('skill_ref')=='SKL-GP-POWER-STRIKE')
        h=e.combat_arpg(wid).ensure_enemy(target)['health']; r=e.character(wid).state(pref)['vitals']['resource']; replay=sk.use_slot(pref,1,event_ref='v:use',target_ref=target); ck('idempotent',replay.get('idempotent_replay') is True); ck('no_double_damage',e.combat_arpg(wid).ensure_enemy(target)['health']==h); ck('no_double_spend',e.character(wid).state(pref)['vitals']['resource']==r)
        sig=sk.build_signature(pref); ck('evidence_positive',sig['evidence_total']>0); ck('dominant_martial',sig['dominant_axes'][0]['axis']=='MARTIAL'); ck('still_no_fixed_class',sig['fixed_class'] is None)
        snap=e.arpg(wid).client_snapshot(pref); ck('client_skills',snap['skills']['definition_count']==36); ck('verify',sk.verify()['status']=='PASS',sk.verify().get('failures')); ck('final_health',e.health_arpg_v06(wid)['status']=='PASS',e.health_arpg_v06(wid).get('failures')); e.close()
        e2=IntegratedARPGEngineV06(db,master_release_path=MASTER); e2.resume_world(wid); rs=e2.skills_arpg(wid).snapshot(pref); ck('restore_learned','SKL-GP-POWER-STRIKE' in rs['learned']); ck('restore_passive',rs['passive_loadout']['1']=='SKL-GP-GUARD-DISCIPLINE'); ck('restore_health',e2.health_arpg_v06(wid)['status']=='PASS'); e2.close()
    failed=[x for x in checks if x['status']=='FAIL']; out={'record_id':'ARPG-STAGE06-VALIDATION-V0.7.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','failures':failed}; print(json.dumps(out,ensure_ascii=False,indent=2)); return 0 if not failed else 1
if __name__=='__main__': raise SystemExit(main())
