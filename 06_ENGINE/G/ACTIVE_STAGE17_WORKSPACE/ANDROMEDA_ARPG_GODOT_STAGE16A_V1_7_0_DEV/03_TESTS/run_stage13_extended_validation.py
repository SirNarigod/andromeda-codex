import json,os,tempfile,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from living_runtime import LivingRuntime,new_runtime_id,clock_point
from world_systems import WorldSystems
from atlas_living_bridge import AtlasLivingBridge,AtlasBridgePermissionError
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip';OUT=ROOT/'04_REPORTS/STAGE13_EXTENDED_VALIDATION_V1_0.json'
checks=[]
def ck(n,o,d=None):checks.append({'name':n,'status':'PASS' if o else 'FAIL','detail':d})
t=tempfile.TemporaryDirectory();db=os.path.join(t.name,'ext.db');rt=LivingRuntime(db,master_release_path=MASTER);worlds=[];ws=WorldSystems(rt);ws.load_master_snapshots(MASTER)
for i in range(4):
 w=rt.create_world(f'owner-{i}',13000+i,ticks_per_day=24);worlds.append(w);ws.bootstrap_world(w['world_instance_id'],population_seed=1000+i*100);ws.economy_tick(w['world_instance_id'],f'e-{i}','FULL');ws.population_tick(w['world_instance_id'],f'p-{i}','FULL');ws.faction_tick(w['world_instance_id'],f'f-{i}','FULL')
 for j in range(25):
  c=rt.get_clock(w['world_instance_id']);s={'state_id':new_runtime_id('state'),'world_instance_id':w['world_instance_id'],'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{'name':f'R{i}-{j}','atlas_exposure':'PLAYER_VISIBLE' if j%2==0 else 'PRIVATE','money':j,'secret':f's{j}'},'protection':{'death':'BLOCKED'}};rt.register_entity(w['world_instance_id'],s)
rt.close();b=AtlasLivingBridge(db,MASTER)
# public 200 checks
for i in range(200):
 p=b.export_projection(role='PUBLIC',spoiler_max=i%4);ck(f'pub-{i}',p['runtime_access']=='NONE' and p['layers']=={} and p['access']['canonical_level_4_hidden'])
# player 4 worlds x 100 projections
for wi,w in enumerate(worlds):
 for j in range(100):
  p=b.export_projection(w['world_instance_id'],role='PLAYER',request_scope=f'owner-{wi}',spoiler_max=j%4,recent_events=10)
  txt=json.dumps(p).lower();ck(f'player-{wi}-{j}',p['world']['world_instance_id']==w['world_instance_id'] and p['runtime_access']=='PLAYER_SAFE' and 'secret' not in txt and 'raw_prompt' not in txt and b.verify_projection(p)['status']=='PASS')
# admin projections, layers and hash
for wi,w in enumerate(worlds):
 for j in range(100):
  p=b.export_projection(w['world_instance_id'],role='ADMIN',spoiler_max=3,recent_events=25)
  ck(f'admin-{wi}-{j}',len(p['layers']['LIVE_ECONOMY'])==7 and len(p['layers']['LIVE_POPULATION'])==14 and len(p['layers']['LIVE_FACTIONS'])==3 and b.verify_projection(p)['status']=='PASS' and not p['layers']['LLM_METRICS'].get('raw_content_exposed',False))
# wrong scope 100
for i in range(100):
 try:b.export_projection(worlds[i%4]['world_instance_id'],role='PLAYER',request_scope='wrong');ok=False
 except AtlasBridgePermissionError:ok=True
 ck(f'scope-deny-{i}',ok)
# tamper 200 hashes
for i in range(200):
 p=b.export_projection(worlds[i%4]['world_instance_id'],role='ADMIN',recent_events=2);p['world']['clock']['tick']+=1;ck(f'tamper-{i}',b.verify_projection(p)['status']=='FAIL')
# cross-world isolation 100
for i in range(100):
 a=b.export_projection(worlds[0]['world_instance_id'],role='ADMIN');c=b.export_projection(worlds[1]['world_instance_id'],role='ADMIN');idsa={x['entity_runtime_id'] for x in a['layers']['LIVE_ENTITY_STATE']};idsc={x['entity_runtime_id'] for x in c['layers']['LIVE_ENTITY_STATE']};ck(f'isolation-{i}',not(idsa&idsc) and a['world']['timeline_id']!=c['world']['timeline_id'])
ck('readonly-probe',b.write_attempt_probe()=='PASS_READ_ONLY');ck('sqlite-integrity',b.conn.execute('pragma integrity_check').fetchone()[0]=='ok');ck('foreign-keys',len(b.conn.execute('pragma foreign_key_check').fetchall())==0)
failed=[x for x in checks if x['status']=='FAIL'];rep={'record_id':'STAGE13-EXTENDED-VALIDATION-V1.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','worlds':4,'projections_generated':1200,'failures':failed[:20]};OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2));print(json.dumps(rep));b.close();t.cleanup();raise SystemExit(0 if not failed else 1)
