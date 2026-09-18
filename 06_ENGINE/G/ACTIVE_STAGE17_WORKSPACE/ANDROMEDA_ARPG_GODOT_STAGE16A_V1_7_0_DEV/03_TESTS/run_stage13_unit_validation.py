import subprocess,sys,re,json
from pathlib import Path
R=Path(__file__).resolve().parents[1];OUT=R/'04_REPORTS/STAGE13_UNIT_VALIDATION_V1_0.json'
p=subprocess.run([sys.executable,'-m','unittest','discover','-s','03_TESTS','-p','test_atlas_living_bridge.py','-q'],cwd=R,text=True,capture_output=True,timeout=90);txt=(p.stdout or '')+(p.stderr or '');m=re.search(r'Ran (\d+) tests?',txt);py=int(m.group(1)) if m else 0
j=subprocess.run(['node','03_TESTS/test_atlas_live_core.mjs'],cwd=R,text=True,capture_output=True,timeout=30);jd={}
try:jd=json.loads((j.stdout or '').strip().splitlines()[-1])
except:pass
status='PASS' if p.returncode==0 and py==61 and j.returncode==0 and jd.get('status')=='PASS' and jd.get('checks')==7 else 'FAIL';rep={'record_id':'STAGE13-UNIT-VALIDATION-V1.0','python_tests':py,'python_status':'PASS' if p.returncode==0 else 'FAIL','js_checks':jd.get('checks',0),'js_status':jd.get('status','FAIL'),'status':status,'python_tail':None if p.returncode==0 else txt[-1000:],'js_tail':None if j.returncode==0 else (j.stderr or '')[-1000:]};OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(rep));raise SystemExit(0 if status=='PASS' else 1)
