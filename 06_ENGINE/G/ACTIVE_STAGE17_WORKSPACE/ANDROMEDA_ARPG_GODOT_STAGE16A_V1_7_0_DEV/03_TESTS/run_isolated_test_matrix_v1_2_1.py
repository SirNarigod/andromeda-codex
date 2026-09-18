from __future__ import annotations
import json, os, re, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TESTS=sorted(p for p in (ROOT/'03_TESTS').glob('test_*.py'))
results=[]; failures=[]; total=0; start=time.time()
env=dict(os.environ); env.setdefault('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
for p in TESTS:
    t=time.time()
    try:
        cp=subprocess.run([sys.executable,str(p),'-q'],cwd=ROOT,env=env,text=True,capture_output=True,timeout=90)
        text=(cp.stdout or '')+'\n'+(cp.stderr or '')
        m=re.search(r'Ran\s+(\d+)\s+tests?',text); count=int(m.group(1)) if m else 0
        total+=count
        row={'file':p.name,'status':'PASS' if cp.returncode==0 else 'FAIL','tests':count,'seconds':round(time.time()-t,3),'returncode':cp.returncode}
        if cp.returncode!=0:
            row['tail']='\n'.join(text.strip().splitlines()[-40:]); failures.append(row)
        results.append(row)
    except subprocess.TimeoutExpired as e:
        row={'file':p.name,'status':'TIMEOUT','tests':0,'seconds':round(time.time()-t,3),'returncode':124}; results.append(row); failures.append(row)
out={'status':'PASS' if not failures else 'FAIL','files':len(TESTS),'tests':total,'seconds':round(time.time()-start,3),'failures':failures,'results':results,'policy':'ISOLATED_PER_FILE_TIMEOUT_90S'}
path=ROOT/'04_REPORTS/V1_2_1/ISOLATED_TEST_MATRIX_V1_2_1.json'; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print(json.dumps(out,ensure_ascii=False,indent=2)); raise SystemExit(0 if out['status']=='PASS' else 1)
