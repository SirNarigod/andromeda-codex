from __future__ import annotations
import json, os, sys, tempfile
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,os.path.join(ROOT,'01_RUNTIME'))
from integrated_arpg_engine_v04 import IntegratedARPGEngineV04
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

checks=[]
def ck(name, cond, detail=None):
    checks.append({'name':name,'status':'PASS' if cond else 'FAIL','detail':detail})

def main():
    with tempfile.TemporaryDirectory() as td:
        db=os.path.join(td,'v.sqlite'); e=IntegratedARPGEngineV04(db,master_release_path=MASTER)
        out=e.create_world('stage04:validation',45454); wid=out['world']['world_instance_id']
        p=e.arpg(wid).create_profile('local:validation',origin_mode='CREATED',display_name='Validation')['profile']; pref=p['profile_ref']
        r=e.resources_arpg(wid); c=e.character(wid)
        ck('health_v04',e.health_arpg_v04(wid)['status']=='PASS')
        snap=r.snapshot(pref); ch=c.state(pref)
        ck('resource_model',snap['resource_model']=='ADAPTIVE_BUILD_DERIVED')
        ck('primary_active',snap['resource_channels']['PRIMARY']['active'] is True)
        ck('primary_unspecialized',snap['resource_channels']['PRIMARY']['mode']=='UNSPECIALIZED')
        ck('primary_source',snap['resource_channels']['PRIMARY']['numeric_source']=='CHARACTER_CORE_VITALS_RESOURCE')
        ck('primary_current_sync',snap['resource_channels']['PRIMARY']['current']==ch['vitals']['resource'])
        ck('primary_max_sync',snap['resource_channels']['PRIMARY']['maximum']==ch['derived']['max_resource'])
        ck('regen_sync',snap['resource_channels']['PRIMARY']['regen_per_s']==ch['derived']['resource_regen_per_s'])
        ck('gcd_opt_in',snap['global_cooldown_policy']=='OPT_IN_PER_ACTION_NOT_UNIVERSAL')
        ck('placeholder_authority',snap['consumable_authority']=='PLACEHOLDER_ONLY_STAGE05_ITEMIZATION_PENDING')
        for cref in ('PLACEHOLDER_HEALTH_RESTORE','PLACEHOLDER_RESOURCE_RESTORE','PLACEHOLDER_HYBRID_RESTORE'):
            ck('consumable_exists:'+cref,cref in snap['consumables'])
            ck('consumable_positive:'+cref,snap['consumables'][cref]>0)
        before=c.state(pref)['vitals']['resource']
        a=r.reserve_action(pref,action_ref='VALIDATE_A',resource_cost=10,cooldown_s=.5,event_ref='v:a')
        ck('action_pass',a['status']=='PASS'); ck('resource_spent',abs(a['resource_spent']-10)<1e-9)
        ck('resource_decreased',c.state(pref)['vitals']['resource']<before)
        replay=r.reserve_action(pref,action_ref='VALIDATE_A',resource_cost=10,cooldown_s=.5,event_ref='v:a')
        ck('action_replay',replay.get('idempotent_replay') is True)
        b=r.reserve_action(pref,action_ref='VALIDATE_A',resource_cost=0,cooldown_s=0,event_ref='v:a2')
        ck('action_cooldown_reject',b['status']=='REJECTED' and b['reason']=='ACTION_COOLDOWN')
        t=r.tick_profile(pref,.5); ck('tick_pass',t['status']=='PASS'); ck('cooldown_cleared','VALIDATE_A' not in t['cooldowns'])
        huge=r.reserve_action(pref,action_ref='HUGE',resource_cost=999999,cooldown_s=0,event_ref='v:huge')
        ck('insufficient_resource',huge['status']=='REJECTED' and huge['reason']=='INSUFFICIENT_RESOURCE')
        # health consumable
        c.apply_health_change(pref,-80,event_ref='v:damage',source_type='TEST')
        q0=r.snapshot(pref)['consumables']['PLACEHOLDER_HEALTH_RESTORE']; h0=c.state(pref)['vitals']['health']
        pot=r.use_consumable(pref,'PLACEHOLDER_HEALTH_RESTORE',event_ref='v:pot')
        ck('pot_pass',pot['status']=='PASS'); ck('pot_heals',c.state(pref)['vitals']['health']>h0)
        ck('pot_quantity',pot['remaining_quantity']==q0-1); ck('pot_placeholder',pot['placeholder_only'] is True)
        shared=r.use_consumable(pref,'PLACEHOLDER_RESOURCE_RESTORE',event_ref='v:shared')
        ck('shared_cooldown',shared['status']=='REJECTED' and shared['reason']=='CONSUMABLE_COOLDOWN')
        r.tick_profile(pref,1.0)
        # no effect
        char=c.state(pref); missing=char['derived']['max_health']-char['vitals']['health']
        if missing>0: c.apply_health_change(pref,missing,event_ref='v:topoff',source_type='TEST')
        q1=r.snapshot(pref)['consumables']['PLACEHOLDER_HEALTH_RESTORE']
        ne=r.use_consumable(pref,'PLACEHOLDER_HEALTH_RESTORE',event_ref='v:noeffect')
        ck('no_effect_reject',ne['status']=='REJECTED' and ne['reason']=='CONSUMABLE_NO_EFFECT')
        ck('no_effect_no_consume',r.snapshot(pref)['consumables']['PLACEHOLDER_HEALTH_RESTORE']==q1)
        # resource pot via command
        c.apply_resource_change(pref,-30,event_ref='v:drain',source_type='TEST'); r.tick_profile(pref,1.0)
        seq=e.arpg(wid)._input(pref)['last_client_sequence']+1
        cmd=e.arpg(wid).submit_command('local:validation',pref,seq,'USE_CONSUMABLE',{'consumable_ref':'PLACEHOLDER_RESOURCE_RESTORE'})
        ck('command_consumable_pass',cmd['status']=='PASS'); ck('command_route',cmd['route']=='CONSUMABLE')
        cmd2=e.arpg(wid).submit_command('local:validation',pref,seq,'USE_CONSUMABLE',{'consumable_ref':'PLACEHOLDER_RESOURCE_RESTORE'})
        ck('command_replay',cmd2.get('idempotent_replay') is True)
        # interruption
        r.tick_profile(pref,1.0); intr=r.apply_interruption(pref,duration_s=.3,source_ref='NPC-TEST',event_ref='v:int')
        ck('interrupt_pass',intr['status']=='PASS'); ck('interrupt_lock',intr['action_lock_remaining_s']==.3)
        lock=r.reserve_action(pref,action_ref='LOCKED',resource_cost=0,cooldown_s=0,event_ref='v:locked')
        ck('interrupt_blocks',lock['status']=='REJECTED' and lock['reason']=='ACTION_INTERRUPTED')
        r.tick_profile(pref,.3); unlock=r.reserve_action(pref,action_ref='LOCKED',resource_cost=0,cooldown_s=0,event_ref='v:unlocked')
        ck('interrupt_clears',unlock['status']=='PASS')
        # gcd
        g1=r.reserve_action(pref,action_ref='GCD1',resource_cost=0,cooldown_s=0,event_ref='v:g1',global_cooldown_s=.4)
        ck('gcd_set',g1['status']=='PASS' and g1['global_cooldown_remaining_s']==.4)
        g2=r.reserve_action(pref,action_ref='GCD2',resource_cost=0,cooldown_s=0,event_ref='v:g2')
        ck('gcd_blocks',g2['status']=='REJECTED' and g2['reason']=='GLOBAL_COOLDOWN')
        r.tick_profile(pref,.4); g3=r.reserve_action(pref,action_ref='GCD2',resource_cost=0,cooldown_s=0,event_ref='v:g3')
        ck('gcd_clears',g3['status']=='PASS')
        # grant and replay
        gb=r.snapshot(pref)['consumables']['PLACEHOLDER_HYBRID_RESTORE']; gr=r.grant_consumable(pref,'PLACEHOLDER_HYBRID_RESTORE',2,event_ref='v:grant')
        ck('grant_pass',gr['status']=='PASS'); ck('grant_quantity',gr['after']==gb+2)
        gr2=r.grant_consumable(pref,'PLACEHOLDER_HYBRID_RESTORE',2,event_ref='v:grant'); ck('grant_replay',gr2.get('idempotent_replay') is True)
        # dead profile
        dp=e.arpg(wid).create_profile('local:deadval',origin_mode='CREATED',display_name='DeadVal')['profile']; dpref=dp['profile_ref']; r.ensure_profile(dpref)
        hp=c.state(dpref)['vitals']['health']; c.apply_health_change(dpref,-hp,event_ref='v:deadkill',source_type='TEST')
        dead=r.use_consumable(dpref,'PLACEHOLDER_HEALTH_RESTORE',event_ref='v:deadpot')
        ck('dead_consumable_block',dead['status']=='REJECTED' and dead['reason']=='CHARACTER_DEAD')
        da=r.reserve_action(dpref,action_ref='DEAD_ACTION',resource_cost=0,cooldown_s=0,event_ref='v:deadact')
        ck('dead_action_block',da['status']=='REJECTED' and da['reason']=='CHARACTER_DEAD')
        # snapshot/verify/event integrity
        cs=e.arpg(wid).client_snapshot(pref); ck('snapshot_resources',cs['resources'] is not None)
        ck('snapshot_server_authority',cs['server_authoritative'] is True)
        vr=r.verify(); ck('resource_verify',vr['status']=='PASS',vr.get('failures'))
        hv=e.health_arpg_v04(wid); ck('health_final',hv['status']=='PASS',hv.get('failures'))
        ck('resource_events_positive',vr['events']>0)
        ck('profiles_bound',vr['profiles']==2)
        ck('art_none',r.snapshot(pref)['art_dependency']=='NONE_PLACEHOLDER_READY')
        e.close()
    failed=[x for x in checks if x['status']!='PASS']
    out={'record_id':'ARPG-STAGE04-VALIDATION-V0.5.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','failures':failed}
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0 if not failed else 1
if __name__=='__main__': raise SystemExit(main())
