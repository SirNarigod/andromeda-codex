from __future__ import annotations
import hashlib,json,sys
from pathlib import Path

EXPECTED_MASTER_SHA='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2'
REQUIRED_RUNTIME=['living_runtime.py','domain_integration.py','commerce_system.py','combat_system.py','mobility_biology.py','society_labor.py','system_health.py','integrated_engine.py','world_systems.py','world_orchestrator.py']
FORBIDDEN_SUFFIXES={'.db','.sqlite','.sqlite3','.pyc','.pyo'}
FORBIDDEN_NAMES={'.env','credentials.json','secrets.json'}

def sha256(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def main(root:Path, master:Path)->dict:
 checks=[]
 def ck(name,ok,detail=None):checks.append({'check':name,'status':'PASS' if ok else 'FAIL','detail':detail})
 ck('master_exists',master.exists(),str(master)); ck('master_sha256',master.exists() and sha256(master)==EXPECTED_MASTER_SHA,sha256(master) if master.exists() else None)
 for name in REQUIRED_RUNTIME: ck(f'required_runtime:{name}',(root/'01_RUNTIME'/name).is_file())
 pyfiles=sorted((root/'01_RUNTIME').glob('*.py')); compile_fail=[]
 for p in pyfiles:
  try:compile(p.read_text(encoding='utf-8'),str(p),'exec')
  except Exception as e:compile_fail.append({'file':str(p),'error':str(e)})
 ck('runtime_compile',not compile_fail,compile_fail)
 forbidden=[]
 for p in root.rglob('*'):
  if not p.is_file():continue
  low=p.name.lower()
  if p.suffix.lower() in FORBIDDEN_SUFFIXES or low in FORBIDDEN_NAMES or '__pycache__' in p.parts:forbidden.append(str(p.relative_to(root)))
 ck('no_forbidden_artifacts',not forbidden,forbidden)
 bundled=[str(p.relative_to(root)) for p in root.rglob('ANDROMEDA_CODEX_MASTER*.zip')]
 ck('master_not_bundled',not bundled,bundled)
 valp=root/'07_RELEASE_READINESS'/'V1_1_0'/'VALIDATION_SUMMARY_V1_1_0.json'; ck('validation_summary_present',valp.is_file())
 if valp.is_file():
  val=json.loads(valp.read_text()); ck('validation_summary_pass',val.get('status')=='PASS',val.get('status')); ck('python_745_pass',val.get('python',{}).get('total',{}).get('passed')==745 and val.get('python',{}).get('total',{}).get('failed')==0,val.get('python',{}).get('total'))
 matrixp=root/'07_RELEASE_READINESS'/'V1_1_0'/'IMPROVEMENT_RESOLUTION_MATRIX_V1_1_0.json';ck('resolution_matrix_present',matrixp.is_file())
 if matrixp.is_file():
  matrix=json.loads(matrixp.read_text()); ck('no_open_p0_p1',matrix.get('summary',{}).get('open_p0_p1')==0,matrix.get('summary'));ck('resolution_gate_pass',matrix.get('release_gate')=='PASS',matrix.get('release_gate'))
 ck('readme_v1_1_present',(root/'README_RELEASE_V1_1_0.md').is_file())
 # Static guardrails: runtime modules must continue declaring non-canon/read-only boundaries.
 text='\n'.join(p.read_text(errors='ignore') for p in pyfiles)
 ck('runtime_noncanon_markers','NOT_CANON' in text or 'RUNTIME_ONLY' in text)
 ck('read_only_markers','READ_ONLY' in text or 'MASTER_READ_ONLY' in text)
 failed=[c for c in checks if c['status']!='PASS']
 return {'record_id':'LIVING-SIM-V1.1.0-RELEASE-AUDIT','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','failures':failed,'results':checks}

if __name__=='__main__':
 root=Path(sys.argv[1] if len(sys.argv)>1 else '.').resolve(); master=Path(sys.argv[2] if len(sys.argv)>2 else '/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
 print(json.dumps(main(root,master),ensure_ascii=False,indent=2))
