from __future__ import annotations
import json, os, sys, tempfile
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,os.path.join(ROOT,'01_RUNTIME'))
from integrated_arpg_engine_v04 import IntegratedARPGEngineV04
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

def main():
    checks=[]
    def ck(name,cond,detail=None): checks.append({'name':name,'status':'PASS' if cond else 'FAIL','detail':detail})
    with tempfile.TemporaryDirectory() as td:
        db=os.path.join(td,'stress.sqlite'); e=IntegratedARPGEngineV04(db,master_release_path=MASTER)
        out=e.create_world('stage04:stress',46464); wid=out['world']['world_instance_id']; refs=[]
        for i in range(3):
            p=e.arpg(wid).create_profile(f'local:stress:{i}',origin_mode='CREATED',display_name=f'Stress{i}')['profile']; refs.append(p['profile_ref'])
        ck('three_profiles',len(refs)==3)
        total_actions=0; total_replays=0
        for pi,pref in enumerate(refs):
            r=e.resources_arpg(wid); c=e.character(wid)
            start=c.state(pref)['vitals']['resource']
            for i in range(20):
                ev=f's:{pi}:a:{i}'; o=r.reserve_action(pref,action_ref='STRESS_ACTION',resource_cost=1,cooldown_s=.05,event_ref=ev)
                if o['status']=='PASS': total_actions+=1
                rp=r.reserve_action(pref,action_ref='STRESS_ACTION',resource_cost=1,cooldown_s=.05,event_ref=ev)
                if rp.get('idempotent_replay'): total_replays+=1
                r.tick_profile(pref,.05)
            ck(f'actions_profile_{pi}',total_actions==(pi+1)*20)
            ck(f'replays_profile_{pi}',total_replays==(pi+1)*20)
            ck(f'resource_decreased_{pi}',c.state(pref)['vitals']['resource']<start)
            c.apply_resource_change(pref,-10,event_ref=f's:{pi}:drain',source_type='STRESS')
            pot=r.use_consumable(pref,'PLACEHOLDER_RESOURCE_RESTORE',event_ref=f's:{pi}:pot')
            ck(f'pot_profile_{pi}',pot['status']=='PASS' and pot['applied_resource']>0)
            intr=r.apply_interruption(pref,duration_s=.2,source_ref='STRESS',event_ref=f's:{pi}:int')
            blk=r.reserve_action(pref,action_ref='INTERRUPTED',resource_cost=0,cooldown_s=0,event_ref=f's:{pi}:blk')
            ck(f'interrupt_profile_{pi}',intr['status']=='PASS' and blk['reason']=='ACTION_INTERRUPTED')
            r.tick_profile(pref,.2)
        ck('total_actions_60',total_actions==60)
        ck('total_replays_60',total_replays==60)
        ck('verify_before_restore',e.resources_arpg(wid).verify()['status']=='PASS')
        e.close()
        e2=IntegratedARPGEngineV04(db,master_release_path=MASTER); e2.resume_world(wid)
        ck('restore_health',e2.health_arpg_v04(wid)['status']=='PASS')
        ck('restore_profiles',e2.resources_arpg(wid).verify()['profiles']==3)
        for i,pref in enumerate(refs): ck(f'restore_snapshot_{i}',e2.resources_arpg(wid).snapshot(pref)['resource_model']=='ADAPTIVE_BUILD_DERIVED')
        e2.close()
    failed=[x for x in checks if x['status']!='PASS']
    out={'record_id':'ARPG-STAGE04-STRESS-V0.5.0','profiles':3,'actions':total_actions,'replays':total_replays,'checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','failures':failed}
    print(json.dumps(out,ensure_ascii=False,indent=2)); return 0 if not failed else 1
if __name__=='__main__': raise SystemExit(main())
