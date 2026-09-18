import sys,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from country_scale import CountryScaleSystem
from scene_interaction import SceneInteractionSystem
from spatial_coordinates import SpatialCoordinateSystem
from dungeon_graph_v2 import DungeonGraphV2
from atlas_country_lod import AtlasCountryLOD
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_1_0_RELEASE.zip'
fail=[];stats={'worlds':0,'states':0,'blocks':0,'subregions':0,'cities':0,'dungeons':0,'rooms':0,'scene_objects':0,'npcs':0,'canonical_routes_seen':0,'public_redactions':0};t=time.time()
for seed in range(7000,7300):
 try:
  c=CountryScaleSystem(master_release_path=MASTER,seed=seed);scene=SceneInteractionSystem(c);sp=SpatialCoordinateSystem(c);dg=DungeonGraphV2(c,scene,spatial=sp);lod=AtlasCountryLOD(c,sp);country=c.world['country'];stats['worlds']+=1
  if c.validate()['status']!='PASS':fail.append([seed,'COUNTRY',c.validate()['failures']]);continue
  if dg.validate()['status']!='PASS':fail.append([seed,'DUNGEON_GRAPH',dg.validate()['failures']]);continue
  blocks=[b for s in country['states'] for b in s['blocks']];stats['states']+=len(country['states']);stats['blocks']+=len(blocks);stats['subregions']+=sum(len(b['subregions']) for b in blocks);stats['cities']+=sum(len(b['cities']) for b in blocks);stats['npcs']+=sum(1 for _ in c._all_npc_records())
  ds=[d for b in blocks for d in b.get('dungeons',[])];stats['dungeons']+=len(ds);stats['rooms']+=sum(len(d['graph_v2']['rooms']) for d in ds)
  for b in blocks:
   objs=list(b.get('scene_objects',[]))
   for city in b.get('cities',[]):objs+=city.get('scene_objects',[])
   for d in b.get('dungeons',[]):
    objs+=d.get('objects',[])
    for r in d['graph_v2']['rooms']:objs += [o for o in r.get('objects',[]) if not o.get('object_ref')]
   stats['scene_objects']+=len(objs)
   for obj in list(b.get('cities',[]))+list(b.get('dungeons',[])):
    exp=sp._subregion_for_point(b,obj['coordinate_center'])
    if obj.get('subregion_id')!=exp:fail.append([seed,'SUBREGION',obj['id'],obj.get('subregion_id'),exp])
  routes=lod.layer_projection(['routes'])['routes']['rows'];stats['canonical_routes_seen']+=len(routes)
  if any(not r['route_id'].startswith('RTE-') for r in routes):fail.append([seed,'ROUTE_AUTHORITY'])
  pub=lod.project(2,layers=list(lod.LAYERS),audience='PUBLIC');stats['public_redactions']+=len(pub['redacted_layers'])
  if lod.project(5,audience='PUBLIC')['status']!='REJECTED':fail.append([seed,'PUBLIC_DUNGEON_LEAK'])
  if lod.verify()['status']!='PASS':fail.append([seed,'LOD_VERIFY'])
 except Exception as e:fail.append([seed,'EXCEPTION',type(e).__name__,str(e)])
rep={'record_id':'V14-LOD-CATALOG-STRESS','status':'PASS' if not fail else 'FAIL','stats':stats,'failure_count':len(fail),'failures':fail[:50],'seconds':round(time.time()-t,3)}
out=ROOT/'04_REPORTS/V1_4_0/V14_LOD_CATALOG_STRESS.json';out.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n');print(json.dumps(rep,ensure_ascii=False));raise SystemExit(1 if fail else 0)
