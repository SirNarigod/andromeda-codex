from __future__ import annotations
import sys,json,hashlib,re
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
BASE=Path('/mnt/data/ANDROMEDA_V1_4_CYCLE/living_v1_3/ANDROMEDA_LIVING_COUNTRY_SCALE_V1_3_0')
MASTER=Path('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_1_0_RELEASE.zip')
EXPECTED_MASTER='9677b10890c24dfc04916178a2b9fd40a9ea131f2a13c1ec8255186ab203a98b'
sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v14 import IntegratedLivingEngineV14
checks=[]
def ck(name,ok,detail=''):
 checks.append({'name':name,'status':'PASS' if ok else 'FAIL','detail':detail})
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
ck('MASTER_V2_1_HASH',MASTER.exists() and sha(MASTER)==EXPECTED_MASTER,sha(MASTER) if MASTER.exists() else 'missing')
# Existing runtime inherited from V1.3: only country_scale may change.
mods=[];missing=[]
for p in (BASE/'01_RUNTIME').glob('*.py'):
 q=ROOT/'01_RUNTIME'/p.name
 if not q.exists():missing.append(p.name);continue
 if sha(p)!=sha(q):mods.append(p.name)
ck('NO_INHERITED_RUNTIME_MISSING',not missing,','.join(missing))
ck('RUNTIME_MODIFICATION_ALLOWLIST',set(mods)<= {'country_scale.py'},','.join(mods))
for n in ['spatial_coordinates.py','streaming_system.py','dungeon_graph_v2.py','atlas_country_lod.py','integrated_engine_v14.py']:
 ck('NEW_MODULE_'+n,(ROOT/'01_RUNTIME'/n).exists())
# syntax without writing pycache
syntax_bad=[]
for p in (ROOT/'01_RUNTIME').glob('*.py'):
 try:compile(p.read_text(encoding='utf-8'),str(p),'exec')
 except Exception as e:syntax_bad.append(f'{p.name}:{e}')
ck('RUNTIME_SYNTAX_IN_MEMORY',not syntax_bad,';'.join(syntax_bad))
# Hygiene
bad=[]
for p in ROOT.rglob('*'):
 if not p.is_file():continue
 if '__pycache__' in p.parts or p.suffix in {'.pyc','.pyo','.tmp','.db','.sqlite','.sqlite3'}:bad.append(str(p.relative_to(ROOT)))
ck('NO_TRANSIENT_ARTIFACTS',not bad,'|'.join(bad[:50]))
# Contract
cp=ROOT/'02_CONTRACTS/GODOT_ISOMETRIC_STREAMING_CONTRACT_V1_4.json'
try:contract=json.loads(cp.read_text())
except Exception as e:contract={};ck('CONTRACT_JSON',False,str(e))
else:ck('CONTRACT_JSON',True)
ck('CONTRACT_VERSION',contract.get('version')=='1.4.0',str(contract.get('version')))
ck('CONTRACT_CHUNK_4096',(contract.get('world_units') or {}).get('chunk_size_m')==4096,str((contract.get('world_units') or {}).get('chunk_size_m')))
# Runtime world audit
engine=IntegratedLivingEngineV14(':memory:',master_release_path=str(MASTER))
try:
 r=engine.create_world('v14-static-audit',1201,load_relationships=False);wid=r['world']['world_instance_id']
 c=engine.country(wid);sp=engine.spatial(wid);lod=engine.atlas_lod(wid);stream=engine.streaming(wid);dg=engine.dungeon_graph(wid)
 ck('HEALTH_V14',engine.health_v14(wid)['status']=='PASS',str(engine.health_v14(wid).get('failures')))
 ck('STREAM_INTEGRITY',stream.full_integrity_check()['status']=='PASS',str(stream.full_integrity_check().get('failures')))
 ck('DUNGEON_GRAPH_INTEGRITY',dg.validate()['status']=='PASS',str(dg.validate().get('failures')))
 routes=lod.layer_projection(['routes'])['routes']['rows']
 ck('ROUTES_PRESENT',len(routes)>0,str(len(routes)))
 ck('ROUTES_CANONICAL_IDS',all(str(x.get('route_id','')).startswith('RTE-') for x in routes),str([x.get('route_id') for x in routes[:5]]))
 ck('NO_DERIVED_ROUTE_IDS',not any(str(x.get('route_id','')).startswith('RTR-DERIVED') for x in routes))
 ck('ROUTE_AUTHORITY_CANON',all(x.get('authority')=='CÂNONE_ESPACIAL' for x in routes))
 # spatial vs subregion
 mism=[]; invm=[]
 for st in c.world['country']['states']:
  for b in st['blocks']:
   for obj in list(b.get('cities',[]))+list(b.get('dungeons',[])):
    exp=sp._subregion_for_point(b,obj['coordinate_center'])
    if obj.get('subregion_id')!=exp:mism.append((obj['id'],obj.get('subregion_id'),exp))
 ck('SPATIAL_SUBREGION_ALIGNMENT',not mism,str(mism[:10]))
 # scene coords / chunk parse roundtrip
 no_coords=[];chunk_bad=[]
 for st in c.world['country']['states']:
  for b in st['blocks']:
   objs=list(b.get('scene_objects',[]))
   for city in b.get('cities',[]):objs+=city.get('scene_objects',[])
   for d in b.get('dungeons',[]):
    objs+=d.get('objects',[])
    for room in (d.get('graph_v2') or {}).get('rooms',[]):objs += [room]+[o for o in room.get('objects',[]) if not o.get('object_ref')]
   for obj in objs:
    cc=obj.get('coordinate_center')
    if not cc:no_coords.append(obj.get('id'))
    else:
     ch=sp.chunk_for_geodetic(cc['longitude'],cc['latitude'])
     try:sp.chunk_neighbors(ch['chunk_id'],radius=0)
     except Exception as e:chunk_bad.append((ch['chunk_id'],str(e)))
 ck('ALL_SPATIAL_OBJECTS_HAVE_COORDS',not no_coords,str(no_coords[:10]))
 ck('ALL_CHUNK_IDS_PARSE',not chunk_bad,str(chunk_bad[:10]))
 # payload uniqueness across currently loaded chunks
 dup=[]
 for ch in list(stream.loaded)[:100]:
  p=lod.godot_chunk_payload(ch);refs=[x['entity_ref'] for x in p['entities']]
  if len(refs)!=len(set(refs)):dup.append(ch)
 ck('GODOT_PAYLOAD_UNIQUE_REFS',not dup,str(dup[:10]))
 # Read-only projection
 p=lod.project(1,layers=['climate']);before=hashlib.sha256(json.dumps(c.world,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 if p['features']:p['features'][0]['name']='MUTATED_CLIENT_SIDE'
 after=hashlib.sha256(json.dumps(c.world,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 ck('ATLAS_PROJECTION_READ_ONLY',before==after)
 # roundtrip
 err=max(sp.roundtrip_error_m(b['coordinate_center']['longitude'],b['coordinate_center']['latitude']) for st in c.world['country']['states'] for b in st['blocks'])
 ck('COORDINATE_ROUNDTRIP_LT_1MM',err<0.001,str(err))
 pub=lod.project(2,layers=['climate','resources','commerce','population','root','threat','routes'],audience='PUBLIC')
 ck('PUBLIC_SENSITIVE_LAYERS_REDACTED',set(pub.get('redacted_layers',[]))=={'resources','commerce','population','root','threat'},str(pub.get('redacted_layers')))
 ck('PUBLIC_DUNGEON_LOD_BLOCKED',lod.project(5,audience='PUBLIC').get('status')=='REJECTED')
 ck('ADMIN_FULL_LOD_ALLOWED',lod.project(6,audience='ADMIN').get('status')=='PASS')
 ck('COUNTRY_SCHEMA_V14',c.world.get('schema_version')=='1.4.0',str(c.world.get('schema_version')))
finally:engine.close()
failed=[x for x in checks if x['status']=='FAIL']
rep={'record_id':'V14-STATIC-AUDIT','version':'V1.4.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','failures':failed,'checks_detail':checks}
out=ROOT/'04_REPORTS/V1_4_0/V14_STATIC_AUDIT.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:rep[k] for k in ('record_id','checks','passed','failed','status','failures')},ensure_ascii=False));raise SystemExit(1 if failed else 0)
