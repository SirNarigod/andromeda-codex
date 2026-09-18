import os,sys,json,hashlib,re,subprocess,py_compile,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; OUT=ROOT/'04_REPORTS/STAGE14/STAGE14_RELEASE_READINESS_AUDIT_V1_0.json'; MASTER=Path('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'); EXPECT='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2'
checks=[]
def ck(n,o,d=None):checks.append({'name':n,'status':'PASS' if o else 'FAIL','detail':d})
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
ck('master-present',MASTER.exists()); ck('master-sha',sha(MASTER)==EXPECT,sha(MASTER))
# Baseline hashes from stage13 embedded evidence
base=json.loads((ROOT/'06_ATLAS_LIVING/UPSTREAM_BASELINE_HASHES_V1_0.json').read_text())
for name,exp in base.get('runtime_modules',{}).items():
 p=ROOT/'01_RUNTIME'/name; ck('baseline-runtime:'+name,p.exists() and sha(p)==exp,sha(p) if p.exists() else 'missing')
with zipfile.ZipFile(MASTER) as z:
 for name,exp in base.get('canonical_atlas_runtime',{}).items():
  try: got=hashlib.sha256(z.read('ANDROMEDA_CODEX_MASTER/'+name)).hexdigest(); ok=got==exp
  except KeyError: got='missing';ok=False
  ck('baseline-atlas:'+name,ok,got)
# Python compilation
for p in sorted((ROOT/'01_RUNTIME').glob('*.py')):
 try:py_compile.compile(str(p),doraise=True);ck('compile:'+p.name,True)
 except Exception as e:ck('compile:'+p.name,False,str(e))
# JS syntax
for p in sorted((ROOT/'06_ATLAS_LIVING').glob('*.mjs')):
 q=subprocess.run(['node','--check',str(p)],capture_output=True,text=True);ck('js-syntax:'+p.name,q.returncode==0,q.stderr[-500:])
# source safety
runtime='\n'.join(p.read_text(errors='ignore') for p in (ROOT/'01_RUNTIME').glob('*.py'))
for token in ['import requests','import httpx','import socket','from socket','import openai','from openai','eval(','exec(']:ck('forbid:'+token,token not in runtime)
ck('no-todo-fixme',not re.search(r'\b(TODO|FIXME)\b',runtime))
ck('no-db-artifacts',not any(p.suffix.lower() in {'.db','.sqlite','.sqlite3'} for p in ROOT.rglob('*') if p.is_file()))
secret_patterns=[r'sk-[A-Za-z0-9_-]{20,}',r'AKIA[0-9A-Z]{16}',r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----']
for pat in secret_patterns:ck('no-secret:'+pat,re.search(pat,runtime) is None)
# required runtime modules
mods=['living_runtime.py','consequence_engine.py','agent_brain.py','social_memory.py','ecology_brain.py','object_environment.py','world_orchestrator.py','world_systems.py','long_horizon.py','llm_gateway.py','atlas_living_bridge.py']
for m in mods:ck('module:'+m,(ROOT/'01_RUNTIME'/m).exists())
# stage14 reports required so far
for f in ['STAGE14_GLOBAL_INTEGRATION_V1_0.json','STAGE14_MULTIWORLD_SOAK_V1_0.json','STAGE14_CORRUPTION_MATRIX_V1_0.json']:
 p=ROOT/'04_REPORTS/STAGE14'/f;ok=p.exists() and json.loads(p.read_text()).get('status')=='PASS';ck('stage14-report:'+f,ok)
failed=[c for c in checks if c['status']!='PASS'];report={'record_id':'STAGE14-RELEASE-READINESS-AUDIT-V1.0','status':'PASS' if not failed else 'FAIL','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'failures':failed};OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False));raise SystemExit(0 if not failed else 1)
