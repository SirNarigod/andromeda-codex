import json, os, tempfile
from integrated_arpg_engine_v08 import IntegratedARPGEngineV08

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
checks=[]
def ck(name,cond,detail=None): checks.append({'name':name,'status':'PASS' if cond else 'FAIL','detail':detail})
with tempfile.TemporaryDirectory() as td:
    db=os.path.join(td,'v.sqlite'); e=IntegratedARPGEngineV08(db,master_release_path=MASTER); r=e.create_world('validation:stage08',88008); wid=r['world']['world_instance_id']; w=e.world_arpg(wid)
    p=e.arpg(wid).create_profile('validation:stage08',origin_mode='CREATED',display_name='Validator')['profile']; pref=p['profile_ref']
    v=w.verify(); ck('world_verify',v['status']=='PASS',v)
    counts=w.canonical_catalog()['counts']
    expected={'biomes':10,'climate_zones':8,'basins':6,'rivers':7,'water_bodies':8,'aquifers':4,'regions':8,'locations':18,'routes':25,'territories':13}
    for k,val in expected.items(): ck('canon_count_'+k,counts.get(k)==val,counts.get(k))
    zones=w.list_zones(); ck('zones_exist',len(zones)>0,len(zones)); ck('one_country',len({z['country_ref'] for z in zones})==1,sorted({z['country_ref'] for z in zones}))
    ck('country_is_ter011',all(z['country_ref']=='TER-011' for z in zones))
    ck('primary_biome_all',all(z['biome']['primary_id']=='BIO-008' for z in zones)); ck('major_biome_all',all(z['biome']['major_system_id']=='BIO-002' for z in zones)); ck('climate_all',all(z['environment']['canonical_climate_id']=='CLM-002' for z in zones))
    ck('hydrology_all',all(z['hydrology_context']['ids']==['BAS-001','RIV-VARDEN'] for z in zones))
    roots=[z for z in zones if (z['biome'].get('legacy_procedural_classification') or {}).get('class')=='ROOT_DEEP']
    ck('root_deep_present',len(roots)>0,len(roots)); ck('root_deep_overlay',all((z.get('anomaly_overlay') or {}).get('overlay_id')=='BIO-ROOT-DEEP' and (z.get('anomaly_overlay') or {}).get('predator_only') for z in roots))
    ck('root_deep_no_normal_city_flora',all(not z['anomaly_overlay']['normal_city_allowed'] and not z['anomaly_overlay']['normal_flora_allowed'] for z in roots))
    ck('climate_alias_clamp',all((('rainfall_mm_y' not in z['environment']['legacy_procedural_climate']) or z['environment']['runtime_baseline']['annual_precipitation_mm']==round(max(420.0,min(950.0,float(z['environment']['legacy_procedural_climate']['rainfall_mm_y']))),2)) for z in zones))
    for rid in ('RTE-001','RTE-003','RTE-013'):
        rs=w.boundary_route(rid); ck('boundary_'+rid,rs['boundary_locked'] and rs['playability']=='BOUNDARY_GATE_ONLY',rs)
    st=w.profile_state(pref); ck('start_country',st['country_ref']=='TER-011'); ck('start_waypoint','WP-CANON-CIT-001' in st['discovered_waypoints']); ck('overworld_start',st['instance_context']['kind']=='OVERWORLD')
    samples=[w.environment_sample(z['zone_ref'],step=i+100) for i,z in enumerate(zones)]
    ck('temperature_bounds',all(2<=x['temperature_c']<=33 for x in samples)); ck('precip_bounds',all(420<=x['annual_precipitation_reference_mm']<=950 for x in samples)); ck('weather_deterministic',all(w.environment_sample(z['zone_ref'],step=i+100)==samples[i] for i,z in enumerate(zones)))
    ck('encounter_anchors',all(len(z['encounter_anchors'])==2 for z in zones)); ck('actor_authority',all(a['actor_authority']=='STAGE07_ACTOR_CORE' for z in zones for a in z['encounter_anchors']))
    ck('resource_stage09_gate',all(z['resource_system_gate']=='STAGE09_GATHERING_HUNTING_FISHING_WORK' for z in zones)); ck('mobility_stage10_gate',all(z['mobility_system_gate']=='STAGE10_MOBILITY_INFRASTRUCTURE' for z in zones))
    ck('dungeons_present',sum(len(z['dungeons']) for z in zones)>0,sum(len(z['dungeons']) for z in zones)); ck('waypoints_present',sum(len(z['waypoints']) for z in zones)>=6,sum(len(z['waypoints']) for z in zones))
    wp=next(x for z in zones for x in z['waypoints'] if x['waypoint_ref'].startswith('WP-RUNTIME-')); rej=w.fast_travel(pref,wp['waypoint_ref'],event_ref='v:reject'); ck('undiscovered_reject',rej['status']=='REJECTED' and rej['reason']=='WAYPOINT_NOT_DISCOVERED',rej)
    d=w.discover_waypoint(pref,wp['waypoint_ref'],event_ref='v:discover'); ck('discover_wp',d['status']=='PASS'); t=w.fast_travel(pref,wp['waypoint_ref'],event_ref='v:travel'); ck('fast_travel',t['status']=='PASS' and t['zone_ref']==wp['zone_ref'],t)
    replay=w.fast_travel(pref,wp['waypoint_ref'],event_ref='v:travel'); ck('travel_replay',replay.get('idempotent_replay') is True,replay)
    # find a dungeon and put profile in its zone through a discovered waypoint if possible, otherwise controlled test-state relocation
    dz=next(z for z in zones if z['dungeons']); ps=w.profile_state(pref); ps['zone_ref']=dz['zone_ref']; ps['instance_context']={'kind':'OVERWORLD','ref':dz['zone_ref']}; w._save_profile(ps)
    dungeon=dz['dungeons'][0]['dungeon_ref']; ent=w.enter_dungeon(pref,dungeon,event_ref='v:dngin'); ck('dungeon_enter',ent['status']=='PASS',ent); ext=w.exit_dungeon(pref,event_ref='v:dngout'); ck('dungeon_exit',ext['status']=='PASS',ext)
    snap=w.snapshot(pref); ck('snapshot_world',snap['status']=='PASS' and snap['profile_world_state']['profile_ref']==pref); ck('no_art_required',all(z['art_dependency']=='NONE_PLACEHOLDER_READY' for z in zones))
    # save/restore exact DB state
    before=w.profile_state(pref); e.runtime.close(); e2=IntegratedARPGEngineV08(db,master_release_path=MASTER); e2.resume_world(wid); after=e2.world_arpg(wid).profile_state(pref); ck('resume_state',before==after); ck('resume_health',e2.health_arpg_v08(wid)['status']=='PASS'); e2.runtime.close()
failed=[x for x in checks if x['status']!='PASS']; out={'record_id':'ARPG-STAGE08-VALIDATION-V0.9.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','results':checks}
print(json.dumps(out,ensure_ascii=False,indent=2))
raise SystemExit(0 if not failed else 1)
