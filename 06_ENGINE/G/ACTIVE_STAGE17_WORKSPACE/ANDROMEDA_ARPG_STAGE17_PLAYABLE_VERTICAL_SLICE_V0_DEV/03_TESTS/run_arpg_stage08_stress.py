import json, os, tempfile
from integrated_arpg_engine_v08 import IntegratedARPGEngineV08
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
checks=[]
def ck(n,c,d=None): checks.append({'name':n,'status':'PASS' if c else 'FAIL','detail':d})
with tempfile.TemporaryDirectory() as td:
    db=os.path.join(td,'s.sqlite'); e=IntegratedARPGEngineV08(db,master_release_path=MASTER); r=e.create_world('stress:stage08',90808); wid=r['world']['world_instance_id']; w=e.world_arpg(wid); zones=w.list_zones()
    profiles=[]
    for i in range(4):
        p=e.arpg(wid).create_profile(f'stress:c{i}',origin_mode='CREATED',display_name=f'Stress {i}',activate=True)['profile']; profiles.append(p)
    ck('profiles',len(profiles)==4,len(profiles)); ck('zones',len(zones)>0,len(zones))
    # 17-ish zones x 24 deterministic environmental steps
    sample_count=0
    for z in zones:
        for step in range(24):
            a=w.environment_sample(z['zone_ref'],step=step); b=w.environment_sample(z['zone_ref'],step=step); sample_count+=1
            if a!=b: ck('weather_drift_'+z['zone_ref']+'_'+str(step),False)
    ck('weather_samples',sample_count==len(zones)*24,sample_count)
    runtime_wps=[x for z in zones for x in z['waypoints'] if x['waypoint_ref'].startswith('WP-RUNTIME-')]
    event_count=0
    for pi,p in enumerate(profiles):
        pref=p['profile_ref']
        for wi,wp in enumerate(runtime_wps):
            er=f's:{pi}:d:{wi}'; a=w.discover_waypoint(pref,wp['waypoint_ref'],event_ref=er); b=w.discover_waypoint(pref,wp['waypoint_ref'],event_ref=er); event_count+=2
            if a['world_server_sequence']!=b['world_server_sequence'] or not b.get('idempotent_replay'): ck('replay_discovery_'+er,False)
        target=runtime_wps[-1]; tr=w.fast_travel(pref,target['waypoint_ref'],event_ref=f's:{pi}:travel'); event_count+=1; ck('travel_'+str(pi),tr['status']=='PASS')
    ck('event_count',event_count==len(profiles)*(len(runtime_wps)*2+1),event_count)
    ck('boundary_routes',all(w.boundary_route(r)['boundary_locked'] for r in ('RTE-001','RTE-003','RTE-013')))
    states_before={p['profile_ref']:w.profile_state(p['profile_ref']) for p in profiles}; verify_before=w.verify(); ck('verify_before',verify_before['status']=='PASS',verify_before)
    e.runtime.close(); e2=IntegratedARPGEngineV08(db,master_release_path=MASTER); e2.resume_world(wid); w2=e2.world_arpg(wid); ck('verify_after',w2.verify()['status']=='PASS',w2.verify())
    for pref,before in states_before.items(): ck('restore_'+pref,w2.profile_state(pref)==before)
    e2.runtime.close()
failed=[x for x in checks if x['status']!='PASS']; out={'record_id':'ARPG-STAGE08-STRESS-V0.9.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','metrics':{'profiles':4,'zones':len(zones),'weather_samples':sample_count,'events':event_count,'runtime_waypoints':len(runtime_wps)},'results':checks}
print(json.dumps(out,ensure_ascii=False,indent=2)); raise SystemExit(0 if not failed else 1)
