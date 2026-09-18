from pathlib import Path
import sys,tempfile,os,json,hashlib
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v15 import IntegratedLivingEngineV15
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_1_0_RELEASE.zip'
def signature(seed):
 with tempfile.TemporaryDirectory() as td:
  e=IntegratedLivingEngineV15(os.path.join(td,'w.db'),master_release_path=MASTER);r=e.create_world('det',seed,load_relationships=False);wid=r['world']['world_instance_id'];c=e.country(wid);n=next(x for x in c._all_npc_records() if x['class']=='WARRIOR')
  env=e.environment(wid).state_for_block(n['block_id']);blocks=[b['id'] for st in c.world['country']['states'] for b in st['blocks']];dst=next(b for b in blocks if b!=n['block_id']);path=e.navigation(wid).plan_blocks(n['block_id'],dst)
  st=e.movement(wid).state(n['id']);lod=e.atlas_lod(wid).project(3,audience='ADMIN')
  logical={'seed':seed,'npc_id':n['id'],'environment':{k:env[k] for k in ('block_id','temperature_c','precipitating','wind_mps','daylight','movement_factor')},'path':{k:path.get(k) for k in ('status','block_path','canonical_route_refs','distance_km')},'motion':{k:round(st[k],6) if isinstance(st[k],float) else st[k] for k in ('iso_x_m','iso_y_m','altitude_m','mode','stamina')},'lod_ids':[f['id'] for f in lod['features']]}
  e.close();raw=json.dumps(logical,sort_keys=True,separators=(',',':'));return hashlib.sha256(raw.encode()).hexdigest(),logical
import argparse
ap=argparse.ArgumentParser();ap.add_argument('--start',type=int,default=0);ap.add_argument('--count',type=int,default=2);args=ap.parse_args()
pairs=[];fail=[]
for seed in range(16000+args.start,16000+args.start+args.count):
 h1,logical_a=signature(seed);h2,logical_b=signature(seed);ok=h1==h2;pairs.append({'seed':seed,'hash_a':h1,'hash_b':h2,'match':ok});
 if not ok:fail.append(seed)
report={'record_id':'V15-DETERMINISM-BATCH','start':args.start,'pairs':len(pairs),'matched':len(pairs)-len(fail),'failed_seeds':fail,'rows':pairs,'status':'PASS' if not fail else 'FAIL'}
out=ROOT/f'04_REPORTS/V1_5_0/V15_DETERMINISM_BATCH_{args.start:02d}_{args.count:02d}.json';out.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps({k:report[k] for k in ('pairs','matched','failed_seeds','status')},indent=2));raise SystemExit(0 if not fail else 1)
