import sys,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v14 import IntegratedLivingEngineV14
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_1_0_RELEASE.zip'

def canonical_summary(seed):
    e=IntegratedLivingEngineV14(':memory:',master_release_path=MASTER)
    try:
        r=e.create_world('determinism',seed,load_relationships=False);wid=r['world']['world_instance_id']
        c=e.country(wid); sp=e.spatial(wid); lod=e.atlas_lod(wid); dg=e.dungeon_graph(wid)
        country=c.world['country']
        blocks=[b for st in country['states'] for b in st['blocks']]
        routes=lod.layer_projection(['routes'])['routes']['rows']
        data={
          'seed':seed,
          'states':[(s['id'],s['name'],s.get('archetype')) for s in country['states']],
          'blocks':[(b['id'],b['state_id'],round(b['coordinate_center']['longitude'],9),round(b['coordinate_center']['latitude'],9),b.get('biome_id')) for b in blocks],
          'subregions':[(sr['id'],b['id'],round(sr['coordinate_center']['longitude'],9),round(sr['coordinate_center']['latitude'],9)) for b in blocks for sr in b['subregions']],
          'dungeons':[(d['id'],d['block_id'],round(d['coordinate_center']['longitude'],9),round(d['coordinate_center']['latitude'],9),[(rm['id'],round(rm['coordinate_center']['longitude'],9),round(rm['coordinate_center']['latitude'],9)) for rm in d['graph_v2']['rooms']]) for b in blocks for d in b.get('dungeons',[])],
          'routes':[(x['route_id'],x.get('authority'),x.get('geometry')) for x in routes],
          'lod_counts':[lod.project(i,layers=[])['feature_count'] for i in range(7)],
          'graph_status':dg.validate()['status'],
        }
        blob=json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
        return hashlib.sha256(blob).hexdigest(),data
    finally:e.close()

fail=[];results=[]
for seed in range(6200,6210):
    h1,d1=canonical_summary(seed);h2,d2=canonical_summary(seed)
    ok=h1==h2
    results.append({'seed':seed,'hash_a':h1,'hash_b':h2,'same':ok})
    if not ok:fail.append({'seed':seed,'a':h1,'b':h2})
rep={'record_id':'V14-SPATIAL-DETERMINISM','status':'PASS' if not fail else 'FAIL','world_pairs':10,'checks':10,'failures':fail,'results':results}
out=ROOT/'04_REPORTS/V1_4_0/V14_SPATIAL_DETERMINISM.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n');print(json.dumps(rep,ensure_ascii=False));raise SystemExit(1 if fail else 0)
