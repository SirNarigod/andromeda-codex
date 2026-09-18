from __future__ import annotations
import argparse, importlib.util, json, os, subprocess, sys, time
from pathlib import Path

def cases_for(path: Path):
    spec=importlib.util.spec_from_file_location(path.stem,path); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    import unittest
    suite=unittest.TestLoader().loadTestsFromModule(mod)
    return [x.id() for group in suite for x in group]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("tests",nargs="*",default=["test_*.py"]); ap.add_argument("--timeout",type=float,default=60); ap.add_argument("--output",default="python_suite_report.json"); a=ap.parse_args()
    root=Path(__file__).resolve().parent; files=[]
    for pat in a.tests: files.extend(sorted(root.glob(pat)))
    results=[]; env=os.environ.copy(); env.setdefault("PYTHONUNBUFFERED","1")
    for f in files:
        if f.name==Path(__file__).name: continue
        for case in cases_for(f):
            started=time.time()
            try:
                p=subprocess.run([sys.executable,"-W","ignore","-m","unittest","-q",case],cwd=root,env=env,capture_output=True,text=True,timeout=a.timeout)
                status="PASS" if p.returncode==0 else "FAIL"; detail=(p.stdout+p.stderr)[-4000:]
            except subprocess.TimeoutExpired as exc:
                status="TIMEOUT"; detail=str(exc)
            results.append({"case":case,"status":status,"duration_s":round(time.time()-started,3),"detail":detail})
    report={"status":"PASS" if all(x["status"]=="PASS" for x in results) else "FAIL","timeout_s":a.timeout,"case_count":len(results),"results":results}
    Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps({"status":report["status"],"case_count":len(results),"failed":[x for x in results if x["status"]!="PASS"]},ensure_ascii=False)); return 0 if report["status"]=="PASS" else 1
if __name__=="__main__": raise SystemExit(main())