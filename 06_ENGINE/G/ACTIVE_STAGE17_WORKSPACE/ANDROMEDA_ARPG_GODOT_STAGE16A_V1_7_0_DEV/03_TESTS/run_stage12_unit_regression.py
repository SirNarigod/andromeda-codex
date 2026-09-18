import json,subprocess,sys,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'04_REPORTS/STAGE12_UNIT_REGRESSION_V1_0.json'
mods=[('runtime_core','test_runtime_core.py',59),('consequence_engine','test_consequence_engine.py',56),('agent_brain','test_agent_brain.py',90),('social_memory','test_social_memory.py',72),('ecology_brain','test_ecology_brain.py',77),('object_environment','test_object_environment.py',73),('world_orchestrator','test_world_orchestrator.py',54),('world_systems','test_world_systems.py',51),('long_horizon','test_long_horizon.py',44),('llm_gateway','test_llm_gateway.py',35)]
rows=[]; total=0; failed=0
for name,pat,expected in mods:
 p=subprocess.run([sys.executable,'-m','unittest','discover','-s','03_TESTS','-p',pat,'-q'],cwd=ROOT,text=True,capture_output=True,timeout=90)
 text=(p.stdout or '')+(p.stderr or '')
 m=re.search(r'Ran (\d+) tests?',text); count=int(m.group(1)) if m else 0
 ok=p.returncode==0 and count==expected
 rows.append({'module':name,'pattern':pat,'expected':expected,'tests':count,'status':'PASS' if ok else 'FAIL','tail':text[-500:] if not ok else None}); total+=count; failed+=0 if ok else 1
rep={'record_id':'STAGE12-UNIT-REGRESSION-V1.0','modules':rows,'tests':total,'passed':total if failed==0 else None,'failed_modules':failed,'status':'PASS' if failed==0 and total==611 else 'FAIL'}
OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2)); print(json.dumps(rep,ensure_ascii=False)); raise SystemExit(0 if rep['status']=='PASS' else 1)
