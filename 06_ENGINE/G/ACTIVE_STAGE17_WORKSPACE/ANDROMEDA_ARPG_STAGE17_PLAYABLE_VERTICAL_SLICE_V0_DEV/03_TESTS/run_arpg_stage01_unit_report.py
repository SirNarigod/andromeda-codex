from __future__ import annotations
import io, json, sys, unittest, importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('test_arpg_game_core_stage01', ROOT/'03_TESTS/test_arpg_game_core_stage01.py')
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
suite=unittest.defaultTestLoader.loadTestsFromModule(module)
stream=io.StringIO(); result=unittest.TextTestRunner(stream=stream,verbosity=1).run(suite)
report={
 'record_id':'ARPG-STAGE01-UNIT-REPORT-V0.2.0','stage':'01/18','tests':result.testsRun,
 'passed':result.testsRun-len(result.failures)-len(result.errors),'failed':len(result.failures),'errors':len(result.errors),
 'status':'PASS' if result.wasSuccessful() else 'FAIL',
 'failures':[{'test':str(t),'detail':d} for t,d in result.failures],
 'errors_detail':[{'test':str(t),'detail':d} for t,d in result.errors],
}
out=ROOT/'04_REPORTS/ARPG_STAGE01/ARPG_STAGE01_UNIT_REPORT_V0_2_0.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
raise SystemExit(0 if result.wasSuccessful() else 1)
