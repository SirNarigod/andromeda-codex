from __future__ import annotations
import json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST = ROOT / '03_TESTS' / 'test_arpg_item_core_stage05.py'
REPORT = ROOT / '04_REPORTS' / 'ARPG_STAGE05' / 'ARPG_STAGE05_UNIT_REPORT_V0_6_0.json'

def main() -> int:
    env = dict(os.environ)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    proc = subprocess.run(
        [sys.executable, str(TEST)],
        cwd=str(TEST.parent), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=90,
    )
    text = proc.stdout or ''
    match = re.search(r'Ran\s+(\d+)\s+tests?', text)
    total = int(match.group(1)) if match else 0
    success = proc.returncode == 0 and total == 22 and re.search(r'\nOK\s*$', text) is not None
    out = {
        'record_id': 'ARPG-STAGE05-UNIT-REPORT-V0.6.0',
        'stage': '05/20', 'version': 'V0.6.0',
        'tests': total, 'passed': total if success else 0,
        'failed': 0 if success else max(1, total),
        'status': 'PASS' if success else 'FAIL',
        'execution': 'ISOLATED_SUBPROCESS',
        'expected_tests': 22,
        'returncode': proc.returncode,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False))
    if not success:
        print(text[-8000:], file=sys.stderr)
    return 0 if success else 1

if __name__ == '__main__':
    raise SystemExit(main())
