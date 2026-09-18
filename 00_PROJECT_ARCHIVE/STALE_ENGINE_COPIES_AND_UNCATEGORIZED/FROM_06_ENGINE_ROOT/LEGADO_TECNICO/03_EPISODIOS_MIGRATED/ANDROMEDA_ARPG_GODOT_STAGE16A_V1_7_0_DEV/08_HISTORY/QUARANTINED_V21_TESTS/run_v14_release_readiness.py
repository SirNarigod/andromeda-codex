from __future__ import annotations
import sys,json,hashlib,tempfile,os
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
MASTER=Path('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_1_0_RELEASE.zip');EXPECTED='9677b10890c24dfc04916178a2b9fd40a9ea131f2a13c1ec8255186ab203a98b'
from integrated_engine_v14 import IntegratedLivingEngineV14
from country_scale import CountryScaleSystem
checks=[]
def ck(n,ok,d=''):checks.append({'name':n,'status':'PASS' if ok else 'FAIL','detail':d})
def load(rel):return json.loads((ROOT/rel).read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
ck('MASTER_HASH',sha(MASTER)==EXPECTED,sha(MASTER))
contract=load('02_CONTRACTS/GODOT_ISOMETRIC_STREAMING_CONTRACT_V1_4.json');ck('CONTRACT_VERSION',contract.get('version')=='1.4.0');ck('CONTRACT_STATUS',contract.get('status') in {'DEV_CONTRACT','RELEASE_CONTRACT'},str(contract.get('status')));ck('CHUNK_SIZE',contract.get('world_units',{}).get('chunk_size_m')==4096);ck('PROCESS_RESUME_CONTRACT',contract.get('process_resume',{}).get('supported') is True);ck('ACCESS_CONTRACT',set(contract.get('access_projection',{}))=={'PUBLIC','PLAYER_RUNTIME','ADMIN'})
ag=load('09_CODEX_EXPANSION/V1_4_0/AGENT_REGISTRY_V1_4_0.json');ck('AGENTS_10',len(ag.get('agents',[]))==10,str(len(ag.get('agents',[]))));ck('SINGLE_SOURCE_AGENT_POLICY',ag.get('single_source_of_truth') is True)
bl=load('04_REPORTS/V1_4_0/BUG_CORRECTION_LEDGER_V1_4_0.json');ck('BUG_LEDGER_16_CLOSED',bl.get('closed')==16 and bl.get('open')==0,str((bl.get('closed'),bl.get('open'))));hl=load('04_REPORTS/V1_4_0/HARNESS_CORRECTION_LEDGER_V1_4_0.json');ck('HARNESS_OPEN_0',hl.get('open')==0)
for rel,key in [('04_REPORTS/V1_4_0/V14_SPATIAL_STREAM_STRESS.json','SPATIAL_STRESS'),('04_REPORTS/V1_4_0/V14_SPATIAL_DETERMINISM.json','DETERMINISM'),('04_REPORTS/V1_4_0/V14_LOD_CATALOG_STRESS.json','LOD_300'),('04_REPORTS/V1_4_0/V14_STATIC_AUDIT.json','STATIC')]:
 d=load(rel);ck(key,d.get('status')=='PASS',str(d.get('failure_count',d.get('failed'))))
s13=load('04_REPORTS/STAGE13_EXTENDED_VALIDATION_V1_0.json');ck('STAGE13_1403',s13.get('status')=='PASS' and s13.get('passed')==1403,str(s13.get('passed')));fuzz=load('04_REPORTS/STAGE13_FUZZ_STRESS_V1_0.json');ck('STAGE13_FUZZ',fuzz.get('status')=='PASS' and not fuzz.get('errors'))
g=load('04_REPORTS/STAGE14/STAGE14_GLOBAL_INTEGRATION_V1_0.json');ck('STAGE14_GLOBAL_43',g.get('status')=='PASS' and g.get('passed')==43);m=load('04_REPORTS/STAGE14/STAGE14_MULTIWORLD_SOAK_V1_0.json');ck('STAGE14_MULTI_37',m.get('status')=='PASS' and m.get('passed')==37);co=load('04_REPORTS/STAGE14/STAGE14_CORRUPTION_MATRIX_V1_0.json');ck('CORRUPTION_10',co.get('status')=='PASS' and co.get('detected')==10)
ck('COUNTRY_VERSION',CountryScaleSystem.VERSION=='V1.4.0',CountryScaleSystem.VERSION)
bad=[str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and ('__pycache__' in p.parts or p.suffix in {'.pyc','.pyo','.tmp','.db','.sqlite','.sqlite3'})];ck('NO_TRANSIENT_FILES',not bad,'|'.join(bad[:20]))
# Live gate
E=IntegratedLivingEngineV14(':memory:',master_release_path=str(MASTER))
try:
 r=E.create_world('readiness-v14',1201,load_relationships=False);w=r['world']['world_instance_id'];c=E.country(w);sp=E.spatial(w);lod=E.atlas_lod(w);st=E.streaming(w);dg=E.dungeon_graph(w)
 ck('LIVE_HEALTH',E.health_v14(w)['status']=='PASS');ck('COUNTRY_SCHEMA',c.world.get('schema_version')=='1.4.0',str(c.world.get('schema_version')));ck('LOD_VERIFY',lod.verify()['status']=='PASS');ck('LOD_LEVELS_7',len(lod.LOD_LEVELS)==7);ck('LAYERS_11',len(lod.LAYERS)==11);ck('STREAM_INTEGRITY',st.full_integrity_check()['status']=='PASS');ck('DUNGEON_GRAPH',dg.validate()['status']=='PASS')
 pub=lod.project(2,layers=list(lod.LAYERS),audience='PUBLIC');ck('PUBLIC_REDACTIONS_5',len(pub['redacted_layers'])==5,str(pub['redacted_layers']));ck('PUBLIC_LOD5_BLOCK',lod.project(5,audience='PUBLIC')['status']=='REJECTED');ck('ADMIN_LOD6',lod.project(6,audience='ADMIN')['status']=='PASS')
 routes=lod.layer_projection(['routes'])['routes']['rows'];ck('CANON_ROUTES_ONLY',bool(routes) and all(x['route_id'].startswith('RTE-') and x['authority']=='CÂNONE_ESPACIAL' for x in routes));ck('NO_RTR_DERIVED',not any(x['route_id'].startswith('RTR-DERIVED') for x in routes))
 b=next(b for s in c.world['country']['states'] for b in s['blocks']);ch=sp.chunk_for_geodetic(b['coordinate_center']['longitude'],b['coordinate_center']['latitude'])['chunk_id'];ck('SIGNED_CHUNK_VALID',sp.chunk_neighbors(ch,0)==[ch],ch);ck('ROUNDTRIP_LT_1MM',sp.roundtrip_error_m(b['coordinate_center']['longitude'],b['coordinate_center']['latitude'])<.001)
 payload=lod.godot_chunk_payload(ch);refs=[x['entity_ref'] for x in payload['entities']];ck('GODOT_UNIQUE_REFS',len(refs)==len(set(refs)));ck('GODOT_READ_ONLY_AUTH',payload.get('authority')=='READ_ONLY_GODOT_CHUNK_PAYLOAD')
finally:E.close()
# Process restart gate
fd,path=tempfile.mkstemp(suffix='.sqlite');os.close(fd)
try:
 e=IntegratedLivingEngineV14(path,master_release_path=str(MASTER));rr=e.create_world('readiness-resume',4401,load_relationships=False);wid=rr['world']['world_instance_id'];clock=e.runtime.get_clock(wid);e.close();e2=IntegratedLivingEngineV14(path,master_release_path=str(MASTER));res=e2.resume_world(wid);ck('PROCESS_RESUME',res.get('status')=='PASS' and res.get('world_instance_id')==wid and res.get('new_world_created') is False);ck('PROCESS_RESUME_CLOCK',e2.runtime.get_clock(wid)==clock);ck('PROCESS_RESUME_HEALTH',e2.health_v14(wid)['status']=='PASS');e2.close()
finally:
 try:os.unlink(path)
 except FileNotFoundError:pass
failed=[x for x in checks if x['status']=='FAIL'];rep={'record_id':'V14-RELEASE-READINESS','version':'V1.4.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','failures':failed,'checks_detail':checks}
out=ROOT/'07_RELEASE_READINESS/V1_4_0_DEV/V14_RELEASE_READINESS.json';out.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:rep[k] for k in ('record_id','checks','passed','failed','status','failures')},ensure_ascii=False));raise SystemExit(1 if failed else 0)
