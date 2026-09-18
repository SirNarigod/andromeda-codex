import sys,json,time,math,tempfile,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v14 import IntegratedLivingEngineV14
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_1_0_RELEASE.zip';fail=[];stats={'worlds':0,'states':0,'blocks':0,'subregions':0,'dungeons':0,'rooms':0,'travels':0,'chunk_transitions':0,'godot_payload_entities':0,'max_roundtrip_error_m':0.0,'max_loaded_chunks':0};t=time.time()
for seed in range(5100,5130):
 e=IntegratedLivingEngineV14(':memory:',master_release_path=MASTER)
 try:
  r=e.create_world('v14-stress',seed,load_relationships=False);w=r['world']['world_instance_id'];c=e.country(w);sp=e.spatial(w);lod=e.atlas_lod(w);stream=e.streaming(w);dg=e.dungeon_graph(w);stats['worlds']+=1
  if e.health_v14(w)['status']!='PASS':fail.append([seed,'HEALTH',e.health_v14(w)['failures']]);continue
  country=c.world['country'];stats['states']+=len(country['states']);blocks=[b for st in country['states'] for b in st['blocks']];stats['blocks']+=len(blocks);stats['subregions']+=sum(len(b['subregions']) for b in blocks)
  for i in range(7):
   if lod.project(i,layers=[])['feature_count']<=0:fail.append([seed,'LOD',i])
  if set(lod.layer_projection())!=set(lod.LAYERS):fail.append([seed,'LAYERS'])
  for b in blocks:
   for cc in [b['coordinate_center']]+[sr['coordinate_center'] for sr in b['subregions']]:stats['max_roundtrip_error_m']=max(stats['max_roundtrip_error_m'],sp.roundtrip_error_m(cc['longitude'],cc['latitude']))
   for city in b['cities']:
    expected=sp._subregion_for_point(b,city['coordinate_center'])
    if city.get('subregion_id')!=expected:fail.append([seed,'CITY_SUBREGION',city['id']])
  # Travel across state with stress speed so test targets streaming, not wall-clock duration.
  actor=next((x for x in c._all_npc_records() if x['class'] in ('WARRIOR','MERCENARY','MAGE')),None)
  dst=next((b for b in blocks if actor and b['state_id']!=actor['state_id']),None)
  if actor and dst:
   before=e.runtime.get_clock(w);mv=stream.travel_npc(actor['id'],dst['id'],speed_kmh=1200);after=e.runtime.get_clock(w)
   if mv.get('status')!='PASS' or (before['day'],before['tick'])==(after['day'],after['tick']):fail.append([seed,'TRAVEL',mv])
   else:stats['travels']+=1;stats['chunk_transitions']+=mv['chunk_transitions']
  stats['max_loaded_chunks']=max(stats['max_loaded_chunks'],len(stream.loaded))
  ds=[d for b in blocks for d in b.get('dungeons',[])];stats['dungeons']+=len(ds);stats['rooms']+=sum(len(d['graph_v2']['rooms']) for d in ds)
  if ds and actor:
   d=ds[0];stream.travel_npc(actor['id'],d['block_id'],speed_kmh=1200);x=dg.enter(actor['id'],d['id'])
   if x.get('status')!='PASS':fail.append([seed,'DUNGEON_ENTER',x])
   else:
    ch=stream.owners[actor['id']];p=lod.godot_chunk_payload(ch);refs=[z['entity_ref'] for z in p['entities']];stats['godot_payload_entities']+=len(refs)
    if actor['id'] not in refs or len(refs)!=len(set(refs)):fail.append([seed,'GODOT_PAYLOAD'])
    if dg.leave(actor['id']).get('status')!='PASS':fail.append([seed,'DUNGEON_LEAVE'])
  integ=stream.full_integrity_check()
  if integ['status']!='PASS':fail.append([seed,'STREAM_INTEGRITY',integ['failures'][:5]])
 finally:e.close()
rep={'record_id':'V14-SPATIAL-STREAM-STRESS','status':'PASS' if not fail else 'FAIL','stats':stats,'failure_count':len(fail),'failures':fail[:30],'seconds':round(time.time()-t,3)}
out=ROOT/'04_REPORTS/V1_4_0/V14_SPATIAL_STREAM_STRESS.json';out.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n');print(json.dumps(rep,ensure_ascii=False));raise SystemExit(1 if fail else 0)
