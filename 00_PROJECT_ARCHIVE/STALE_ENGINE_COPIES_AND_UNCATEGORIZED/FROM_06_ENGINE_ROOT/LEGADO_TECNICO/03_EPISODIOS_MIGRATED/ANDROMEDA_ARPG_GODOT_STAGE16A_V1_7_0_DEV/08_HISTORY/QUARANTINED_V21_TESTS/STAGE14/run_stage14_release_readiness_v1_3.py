import ast,hashlib,json,re,subprocess,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'04_REPORTS/V1_3_0/STAGE14_RELEASE_READINESS_V1_3_0.json'
M21=Path('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_1_0_RELEASE.zip'); M20=Path('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
H21='9677b10890c24dfc04916178a2b9fd40a9ea131f2a13c1ec8255186ab203a98b'; H20='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2'
checks=[]
def ck(n,o,d=None): checks.append({'name':n,'status':'PASS' if o else 'FAIL','detail':d})
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
ck('master-v21-present',M21.exists()); ck('master-v21-sha',M21.exists() and sha(M21)==H21,sha(M21) if M21.exists() else 'missing')
ck('master-v20-baseline-present',M20.exists()); ck('master-v20-baseline-sha',M20.exists() and sha(M20)==H20,sha(M20) if M20.exists() else 'missing')
# Syntax in memory: never create pycache.
for p in sorted((ROOT/'01_RUNTIME').glob('*.py')):
    try: ast.parse(p.read_text(encoding='utf-8')); ok=True; detail=None
    except Exception as e: ok=False; detail=str(e)
    ck('syntax:'+p.name,ok,detail)
# Source safety.
runtime='\n'.join(p.read_text(errors='ignore') for p in (ROOT/'01_RUNTIME').glob('*.py'))
for token in ['import requests','import httpx','import socket','from socket','import openai','from openai','eval(','exec(']: ck('forbid:'+token,token not in runtime)
ck('no-todo-fixme',not re.search(r'\b(TODO|FIXME)\b',runtime))
ck('no-db-artifacts',not any(p.suffix.lower() in {'.db','.sqlite','.sqlite3'} for p in ROOT.rglob('*') if p.is_file()))
ck('no-pycache',not any(p.name=='__pycache__' for p in ROOT.rglob('__pycache__')))
for pat in [r'sk-[A-Za-z0-9_-]{20,}',r'AKIA[0-9A-Z]{16}',r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----']:
    ck('no-secret:'+pat,re.search(pat,runtime) is None)
# Required V1.3 modules.
for m in ['living_runtime.py','commerce_system.py','combat_system.py','country_scale.py','country_living_bridge.py','integrated_engine_v13.py','ecology_brain.py','consequence_engine.py','atlas_living_bridge.py']:
    ck('module:'+m,(ROOT/'01_RUNTIME'/m).exists())
# Evidence gates.
reports={
 'static':ROOT/'04_REPORTS/V1_3_0/V1_3_STATIC_AUDIT.json',
 'regression':ROOT/'04_REPORTS/V1_3_0/ISOLATED_REGRESSION_V1_3_0.json',
 'determinism':ROOT/'04_REPORTS/V1_3_0/COMBAT_DETERMINISM_REPEAT_V1_3_0.json',
 'bridge_stress':ROOT/'04_REPORTS/V1_3_0/COUNTRY_LIVING_BRIDGE_STRESS_V1_3.json',
 'catalog_stress':ROOT/'04_REPORTS/V1_3_0/V1_3_CATALOG_DISTRIBUTION_STRESS.json',
 'stage13_ext':ROOT/'04_REPORTS/STAGE13_EXTENDED_VALIDATION_V1_0.json',
 'stage13_fuzz':ROOT/'04_REPORTS/STAGE13_FUZZ_STRESS_V1_0.json',
 'stage14_global':ROOT/'04_REPORTS/STAGE14/STAGE14_GLOBAL_INTEGRATION_V1_0.json',
 'stage14_multi':ROOT/'04_REPORTS/STAGE14/STAGE14_MULTIWORLD_SOAK_V1_0.json',
 'stage14_corruption':ROOT/'04_REPORTS/STAGE14/STAGE14_CORRUPTION_MATRIX_V1_0.json',
}
for name,p in reports.items():
    ok=False; detail='missing'
    if p.exists():
        d=json.loads(p.read_text()); ok=d.get('status')=='PASS'; detail={'status':d.get('status'),'record_id':d.get('record_id')}
    ck('report:'+name,ok,detail)
reg=json.loads(reports['regression'].read_text()); ck('regression-24-files-776-tests',reg.get('files')==24 and reg.get('tests_total')==776 and reg.get('failed_files')==0,{'files':reg.get('files'),'tests':reg.get('tests_total')})
det=json.loads(reports['determinism'].read_text()); ck('deterministic-repeat-identical',det.get('stats_identical') is True,det)
st=json.loads(reports['static'].read_text()); ck('static-audit-57-57',st.get('checks')==57 and st.get('failed')==0,{'checks':st.get('checks'),'failed':st.get('failed')})
# Historical Stage14 readiness is not an authority for V1.3; prove exactly why it is superseded.
hist=ROOT/'04_REPORTS/STAGE14/STAGE14_RELEASE_READINESS_AUDIT_V1_0.json'
if hist.exists():
    h=json.loads(hist.read_text()); names=sorted(x.get('name') for x in h.get('failures',[])); expected=sorted(['baseline-runtime:living_runtime.py','baseline-runtime:consequence_engine.py','baseline-runtime:ecology_brain.py','baseline-runtime:world_orchestrator.py','baseline-runtime:world_systems.py'])
    ck('historical-readiness-only-obsolete-baseline-failures',names==expected,names)
else: ck('historical-readiness-only-obsolete-baseline-failures',False,'missing')
failed=[c for c in checks if c['status']=='FAIL']
rep={'record_id':'STAGE14-RELEASE-READINESS-V1.3.0','status':'PASS' if not failed else 'FAIL','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'failures':failed,'historical_v1_0_readiness':'SUPERSEDED_FOR_V1_3_BASELINE_AUTHORITY'}
OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n'); print(json.dumps({'status':rep['status'],'checks':rep['checks'],'passed':rep['passed'],'failed':rep['failed'],'failures':failed[:5]},ensure_ascii=False)); raise SystemExit(1 if failed else 0)
