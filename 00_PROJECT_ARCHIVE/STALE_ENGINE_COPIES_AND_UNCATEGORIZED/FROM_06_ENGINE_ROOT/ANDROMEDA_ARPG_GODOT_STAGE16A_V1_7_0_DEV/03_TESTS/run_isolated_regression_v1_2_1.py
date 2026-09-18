import subprocess,re,json,time,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1]
OUT=R/'04_REPORTS/V1_2_1/ISOLATED_REGRESSION_V1_2_1.json'; OUT.parent.mkdir(parents=True,exist_ok=True)
rows=[]; total=0; failed=[]; start=time.time()
for p in sorted((R/'03_TESTS').glob('test_*.py')):
    t=time.time()
    try:
        cp=subprocess.run([sys.executable,str(p),'-q'],cwd=R,text=True,capture_output=True,timeout=70)
        text=(cp.stdout or '')+'\n'+(cp.stderr or '')
        m=re.search(r'Ran\s+(\d+)\s+tests?',text)
        count=int(m.group(1)) if m else None
        if count is not None: total+=count
        status='PASS' if cp.returncode==0 else 'FAIL'
        row={'file':p.name,'status':status,'tests':count,'seconds':round(time.time()-t,3),'returncode':cp.returncode}
        if status!='PASS':
            row['output_tail']=text[-4000:]; failed.append(row)
        rows.append(row)
    except subprocess.TimeoutExpired as e:
        row={'file':p.name,'status':'TIMEOUT','tests':None,'seconds':round(time.time()-t,3)}; rows.append(row); failed.append(row)
rep={'record_id':'ISOLATED-REGRESSION-V1.2.1','status':'PASS' if not failed else 'FAIL','files':len(rows),'tests_total':total,'failed_files':len(failed),'rows':rows,'failures':failed,'seconds':round(time.time()-start,3),'policy':'Each test module executes in a fresh process with individual timeout; avoids monolithic harness hangs.'}
OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({'status':rep['status'],'files':rep['files'],'tests_total':rep['tests_total'],'failed_files':rep['failed_files'],'seconds':rep['seconds']})); raise SystemExit(0 if not failed else 1)
