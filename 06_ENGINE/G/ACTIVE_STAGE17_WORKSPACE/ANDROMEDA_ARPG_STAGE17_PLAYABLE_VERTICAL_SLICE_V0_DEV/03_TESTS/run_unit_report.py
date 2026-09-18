import json,sys,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'01_RUNTIME'))
start=time.time()
suite=unittest.defaultTestLoader.discover(str(ROOT/'03_TESTS'),pattern='test_*.py')
result=unittest.TestResult();suite.run(result)
report={
 'record_id':'LIVING-SIM-ETAPA-08-UNIT-TEST-REPORT-V1.0',
 'tests_run':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors),
 'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
 'elapsed_seconds':round(time.time()-start,3),
 'failure_details':[{'test':str(t),'traceback':tb} for t,tb in result.failures],
 'error_details':[{'test':str(t),'traceback':tb} for t,tb in result.errors],
}
report['status']='PASS' if report['failures']==0 and report['errors']==0 else 'FAIL'
(ROOT/'04_REPORTS'/'UNIT_TEST_REPORT_V1_0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
if report['status']!='PASS': raise SystemExit(1)
