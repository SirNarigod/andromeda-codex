from __future__ import annotations
import json, os, sys, tempfile, math
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,os.path.join(ROOT,'01_RUNTIME'))
from integrated_arpg_engine_v07 import IntegratedARPGEngineV07
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

def main():
    checks=[]
    def ck(n,c,d=None): checks.append({'name':n,'status':'PASS' if c else 'FAIL','detail':d})
    with tempfile.TemporaryDirectory() as td:
        db=os.path.join(td,'v.sqlite'); e=IntegratedARPGEngineV07(db,master_release_path=MASTER); wid=e.create_world('stage07:validation',71717)['world']['world_instance_id']; ac=e.actors_arpg(wid)
        ck('health',e.health_arpg_v07(wid)['status']=='PASS'); v=ac.verify(); ck('actor_verify',v['status']=='PASS',v.get('failures')); ck('country_actor_bootstrap',v['country_source_actors']>=490,v['country_source_actors'])
        p=e.arpg(wid).create_profile('local:v',origin_mode='CREATED',display_name='V')['profile']; pref=p['profile_ref']; avatar=p['avatar_ref']; ck('player_actor',ac.actor(avatar)['actor_role']=='PLAYER')
        npcs=[n for n in e.country(wid)._all_npc_records() if n['id']!=avatar]; child=next(n for n in npcs if n['class']=='CHILD'); worker=next(n for n in npcs if n['class']=='WORKER'); target=next(n for n in npcs if not (n.get('protection') or {}).get('protected') and n['id'] not in {child['id'],worker['id']}); neutral=next(n for n in npcs if n['id']!=target['id'] and not (n.get('protection') or {}).get('protected'))
        ck('child_guard',ac.actor(child['id'])['combat_rank']=='NONCOMBATANT' and ac.actor(child['id'])['protected_identity']); ck('child_hostile_reject',ac.set_disposition(child['id'],'HOSTILE',event_ref='v:child')['status']=='REJECTED')
        ck('worker_guard',ac.actor(worker['id'])['protected_identity'] and not ac.actor(worker['id'])['ai_enabled']); ck('worker_elite_reject',ac.set_combat_rank(worker['id'],'ELITE',event_ref='v:worker')['status']=='REJECTED')
        ck('default_neutral',ac.actor(target['id'])['disposition']=='NEUTRAL'); h=ac.set_disposition(target['id'],'HOSTILE',event_ref='v:hostile'); ck('hostile_set',h['status']=='PASS' and h['ai_enabled']); ck('hostile_replay',ac.set_disposition(target['id'],'HOSTILE',event_ref='v:hostile')['idempotent_replay']); ck('hostility_query',ac.hostility_to_profile(target['id'],pref)['hostile'])
        # Neutral remains context route.
        arpg=e.arpg(wid); seq=arpg._input(pref)['last_client_sequence']+1; arpg.submit_command('local:v',pref,seq,'SELECT_TARGET',{'target_ref':neutral['id']}); seq+=1; ctx=arpg.submit_command('local:v',pref,seq,'PRIMARY_ACTION',{}); ck('neutral_context',ctx['route']=='NPC_CONTEXT'); ck('legacy_gate_preserved',ctx['combat_activation_policy']=='EXPLICIT_COMBAT_INTENT_UNTIL_STAGE08_HOSTILITY')
        # Hostile auto-attack via normal primary action.
        pos=e.movement(wid).state(avatar); close=e.spatial(wid).isometric_to_geodetic(pos['iso_x_m']+0.8,pos['iso_y_m'],pos['altitude_m']); e.movement(wid).sync_to_geodetic(target['id'],close,reason='VALIDATION_CLOSE')
        seq+=1; arpg.submit_command('local:v',pref,seq,'SELECT_TARGET',{'target_ref':target['id']}); seq+=1; auto=arpg.submit_command('local:v',pref,seq,'PRIMARY_ACTION',{}); ck('hostile_auto_route',auto['route']=='COMBAT'); ck('hostile_auto_flag',auto.get('auto_hostile') is True)
        # AI attacks character authority; allow multiple deterministic attack decisions until a hit.
        before=e.character(wid).state(pref)['vitals']['health']; hit=None
        for i in range(30):
            o=ac.tick_actor(target['id'],1.0); c=o.get('combat') or {}
            if o.get('action')=='ATTACK' and c.get('status')=='PASS' and c.get('hit'): hit=c; break
        ck('ai_hit',hit is not None); after=e.character(wid).state(pref)['vitals']['health']; ck('ai_character_hp_authority',hit is not None and after<before,(before,after))
        # Chase from 4m.
        far=e.spatial(wid).isometric_to_geodetic(pos['iso_x_m']+4.0,pos['iso_y_m'],pos['altitude_m']); e.movement(wid).sync_to_geodetic(target['id'],far,reason='VALIDATION_FAR'); chase=ac.tick_actor(target['id'],0.25); ck('ai_chase',chase['ai_state']=='CHASE' and chase['action']=='MOVE_TOWARD_TARGET',chase)
        # Rank hierarchy uses gameplay overlay only.
        base=e.combat_arpg(wid).ensure_enemy(target['id'])['max_health']; elite=ac.set_combat_rank(target['id'],'ELITE',event_ref='v:elite'); elite_hp=e.combat_arpg(wid).ensure_enemy(target['id'])['max_health']; boss=ac.set_combat_rank(target['id'],'BOSS',event_ref='v:boss'); boss_hp=e.combat_arpg(wid).ensure_enemy(target['id'])['max_health']; ck('elite_scaling',elite['status']=='PASS' and elite_hp>base,(base,elite_hp)); ck('boss_scaling',boss['status']=='PASS' and boss_hp>elite_hp,(elite_hp,boss_hp)); ck('no_canon_identity_mutation',not ac.actor(target['id'])['canonical_identity_mutation'])
        snap=arpg.client_snapshot(pref); ck('snapshot_actor_core',snap['actors'] is not None); ck('snapshot_selected_target',snap['actors']['selected_target']['actor']['actor_ref']==target['id'])
        tick=e.tick_arpg(pref,delta_s=.1,max_ai_actors=8); ck('integrated_tick',tick['status']=='PASS' and tick['actors']['status']=='PASS'); ck('final_verify',ac.verify()['status']=='PASS',ac.verify().get('failures')); ck('final_health',e.health_arpg_v07(wid)['status']=='PASS',e.health_arpg_v07(wid).get('failures')); e.close()
        e2=IntegratedARPGEngineV07(db,master_release_path=MASTER); e2.resume_world(wid); rs=e2.actors_arpg(wid).actor(target['id']); ck('restore_disposition',rs['disposition']=='HOSTILE'); ck('restore_rank',rs['combat_rank']=='BOSS'); ck('restore_health',e2.health_arpg_v07(wid)['status']=='PASS'); e2.close()
    failed=[x for x in checks if x['status']=='FAIL']; out={'record_id':'ARPG-STAGE07-VALIDATION-V0.8.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','failures':failed}; print(json.dumps(out,ensure_ascii=False,indent=2)); return 0 if not failed else 1
if __name__=='__main__': raise SystemExit(main())
