from __future__ import annotations
import sys,json,hashlib,shutil,tempfile,os
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v15 import IntegratedLivingEngineV15
MASTER=Path('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_1_0_RELEASE.zip');EXPECTED='9677b10890c24dfc04916178a2b9fd40a9ea131f2a13c1ec8255186ab203a98b'
checks=[]
def ck(n,ok,d=''):checks.append({'name':n,'status':'PASS' if ok else 'FAIL','detail':d})
def load(rel):return json.loads((ROOT/rel).read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
ck('MASTER_HASH',sha(MASTER)==EXPECTED,sha(MASTER))
for rel,key,expected in [
 ('04_REPORTS/V1_5_0/V15_HISTORICAL_REGRESSION.json','HISTORICAL_807',lambda d:d.get('tests')==807 and d.get('status')=='PASS'),
 ('04_REPORTS/V1_5_0/V15_INTEGRATED_STRESS.json','STRESS_30',lambda d:d.get('worlds_completed')==30 and d.get('status')=='PASS'),
 ('04_REPORTS/V1_5_0/V15_DETERMINISM.json','DETERMINISM_10',lambda d:d.get('pairs')==10 and d.get('status')=='PASS'),
 ('04_REPORTS/V1_5_0/V15_STATIC_AUDIT.json','STATIC_28',lambda d:d.get('checks')==28 and d.get('status')=='PASS'),
 ('04_REPORTS/STAGE13_EXTENDED_VALIDATION_V1_0.json','STAGE13_1403',lambda d:d.get('passed')==1403 and d.get('status')=='PASS'),
 ('04_REPORTS/STAGE13_FUZZ_STRESS_V1_0.json','STAGE13_FUZZ',lambda d:d.get('status')=='PASS' and not d.get('errors')),
 ('04_REPORTS/STAGE14/STAGE14_GLOBAL_INTEGRATION_V1_0.json','STAGE14_43',lambda d:d.get('passed')==43 and d.get('status')=='PASS'),
 ('04_REPORTS/STAGE14/STAGE14_MULTIWORLD_SOAK_V1_0.json','MULTIWORLD_37',lambda d:d.get('passed')==37 and d.get('status')=='PASS'),
 ('04_REPORTS/STAGE14/STAGE14_CORRUPTION_MATRIX_V1_0.json','CORRUPTION_10',lambda d:d.get('detected')==10 and d.get('status')=='PASS')]:
 d=load(rel);ck(key,expected(d),str({k:d.get(k) for k in ('status','passed','tests','pairs','worlds_completed','checks','detected')}))
bl=load('04_REPORTS/V1_5_0/BUG_CORRECTION_LEDGER_V1_5_0.json');ck('BUGS_15_CLOSED',bl.get('closed')==15 and bl.get('open')==0)
hl=load('04_REPORTS/V1_5_0/HARNESS_CORRECTION_LEDGER_V1_5_0.json');ck('HARNESS_OPEN_0',hl.get('open')==0)
ag=load('09_CODEX_EXPANSION/V1_5_0_DEV/AGENT_REGISTRY_V1_5_0.json');ck('AGENTS_11',len(ag.get('agents',[]))==11)
fg=load('09_CODEX_EXPANSION/V1_5_0_DEV/FUTURE_COUNTRY_GATE_V1_5_0.json');ck('SECOND_COUNTRY_LOCKED',fg.get('status')=='LOCKED' and fg.get('active_country_count')==1 and all(not x['implemented'] for x in fg['reserved_archetypes']))
co=load('02_CONTRACTS/GODOT_ISOMETRIC_TRAVERSAL_CONTRACT_V1_5.json');ck('GODOT_CONTRACT_V15',co.get('version')=='V1.5.0' and co.get('authority')=='SERVER_AUTHORITATIVE');ck('GODOT_SESSION_RULE','session_ref' in co.get('session_rule','') and 'player_ref' in co.get('session_rule',''))
# live world + resume
fd,path=tempfile.mkstemp(suffix='.sqlite');os.close(fd)
try:
 e=IntegratedLivingEngineV15(path,master_release_path=str(MASTER));r=e.create_world('v15-readiness',1201,load_relationships=False);wid=r['world']['world_instance_id'];c=e.country(wid);n=next(x for x in c._all_npc_records() if x['class']=='WARRIOR');g=e.godot(wid);ck('LIVE_HEALTH',e.health_v15(wid)['status']=='PASS');ck('SESSION_BIND_LIVE',g.bind_session('READY-S',n['id'])['status']=='PASS');ck('SNAPSHOT_LIVE',g.client_snapshot('READY-S')['status']=='PASS');before=e.movement(wid).state(n['id']);e.close()
 e2=IntegratedLivingEngineV15(path,master_release_path=str(MASTER));res=e2.resume_world(wid);ck('RESUME_WORLD',res.get('status')=='PASS' and res.get('world_instance_id')==wid);ck('RESUME_HEALTH',e2.health_v15(wid)['status']=='PASS');ck('SESSION_AFTER_RESUME',e2.godot(wid).client_snapshot('READY-S')['status']=='PASS');after=e2.movement(wid).state(n['id']);ck('MOTION_AFTER_RESUME',before['iso_x_m']==after['iso_x_m'] and before['iso_y_m']==after['iso_y_m']);e2.close()
finally:
 try:os.unlink(path)
 except FileNotFoundError:pass
# local hygiene
bad=[str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and ('__pycache__' in p.parts or p.suffix in {'.pyc','.pyo','.tmp','.db','.sqlite','.sqlite3'})];ck('NO_TRANSIENT_FILES',not bad,'|'.join(bad[:20]))
failed=[x for x in checks if x['status']=='FAIL']
godot=shutil.which('godot4') or shutil.which('godot'); external={'godot_executable':godot,'runtime_execution':'PASS' if godot else 'PENDING','reason':None if godot else 'Godot 4 executable is not installed in this environment; GDScript/runtime scene execution cannot be truthfully claimed.'}
status='PASS_SERVER_CONVERGED_EXTERNAL_GODOT_PENDING' if not failed and not godot else ('PASS' if not failed else 'FAIL')
rep={'record_id':'V15-DEV-READINESS','version':'V1.5.0-DEV','local_checks':len(checks),'local_passed':len(checks)-len(failed),'local_failed':len(failed),'local_status':'PASS' if not failed else 'FAIL','external_godot_gate':external,'release_authorized':bool(not failed and godot),'backup_authorized':bool(not failed and godot),'status':status,'failures':failed,'checks_detail':checks}
out=ROOT/'07_RELEASE_READINESS/V1_5_0_DEV/V15_DEV_READINESS.json';out.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:rep[k] for k in ('local_checks','local_passed','local_failed','local_status','external_godot_gate','release_authorized','backup_authorized','status')},ensure_ascii=False));raise SystemExit(1 if failed else 0)
