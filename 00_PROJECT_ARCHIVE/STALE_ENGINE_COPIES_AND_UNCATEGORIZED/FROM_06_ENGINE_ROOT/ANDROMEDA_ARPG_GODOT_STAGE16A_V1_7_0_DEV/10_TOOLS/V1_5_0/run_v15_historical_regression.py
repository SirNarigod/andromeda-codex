from pathlib import Path
import subprocess,sys,re,json,argparse,time
ROOT=Path(__file__).resolve().parents[2]
ap=argparse.ArgumentParser();ap.add_argument('--start',type=int,default=0);ap.add_argument('--count',type=int,default=8);args=ap.parse_args()
files=sorted(p for p in (ROOT/'03_TESTS').glob('test_*.py') if not p.name.startswith('test_v15_'))
sel=files[args.start:args.start+args.count];rows=[];fail=[];total=0
for p in sel:
 t=time.time()
 try:
  cp=subprocess.run([sys.executable,str(p)],cwd=str(ROOT),text=True,capture_output=True,timeout=120)
  text=(cp.stdout or '')+'\n'+(cp.stderr or '')
  m=re.search(r'Ran\s+(\d+)\s+tests?',text); n=int(m.group(1)) if m else 0; total+=n
  ok=cp.returncode==0 and m is not None
  row={'file':p.name,'tests':n,'returncode':cp.returncode,'seconds':round(time.time()-t,3),'status':'PASS' if ok else 'FAIL'}
  if not ok: row['tail']='\n'.join(text.splitlines()[-30:]);fail.append(row)
  rows.append(row)
 except subprocess.TimeoutExpired as ex:
  row={'file':p.name,'tests':0,'returncode':None,'seconds':round(time.time()-t,3),'status':'TIMEOUT','tail':str(ex)};rows.append(row);fail.append(row)
report={'record_id':'V15-HISTORICAL-REGRESSION-BATCH','start':args.start,'file_count':len(sel),'tests':total,'passed_files':sum(r['status']=='PASS' for r in rows),'failed_files':len(fail),'rows':rows,'failures':fail,'status':'PASS' if not fail else 'FAIL'}
out=ROOT/f'04_REPORTS/V1_5_0/V15_HISTORICAL_REGRESSION_BATCH_{args.start:02d}_{len(sel):02d}.json';out.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({k:report[k] for k in ('start','file_count','tests','passed_files','failed_files','status')},indent=2));raise SystemExit(0 if not fail else 1)
