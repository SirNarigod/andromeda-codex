"""Backend-owned validation runner for the Stage16B authority adapter.

Runs, in one pass and with the Master V2.0.1 authority pinned:

  1. Master V2.0.1 SHA-256 + no active V2.1.0 path
  2. Stage16A protected checkpoint byte audit (724 entries)
  3. Backend suite coverage (no suite on disk may go unregistered)
  4. Every Stage16B authority suite in BACKEND_SUITES
  5. Stage16A regression (unittest discover)
  6. Stage16A vertical slice stress
  7. Stage15 validation + stress

A step only counts as PASS on an explicit success signal. Warnings, skips and
empty output are never promoted to PASS.

    python run_stage16b_authority_validation.py [--out reports/EVIDENCE.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
REPO_ROOT = PROJECT_ROOT.parent
RUNTIME_DIR = PROJECT_ROOT / "01_RUNTIME"

sys.path.insert(0, str(BACKEND_DIR))
from authority_config import (  # noqa: E402
    FORBIDDEN_MASTER_TOKENS,
    MASTER_V2_0_1_SHA256,
    _resolve_master_path,
)

# Active Stage16A protected checkpoint. V0.8.1 succeeded V0.8.0 (verify()'s
# catalog-membership fix -- see STAGE16A_CHECKPOINT_V0_8_1_SEALED.json in the
# same ARPG CODEX folder for the inheritance record); V0.8.0 remains sealed
# and restorable as the historical predecessor, it is simply no longer the
# checkpoint this validator compares the live tree against.
CHECKPOINT_ZIP = Path(
    r"C:\Users\thall\Documents\ARPG CODEX"
    r"\ANDROMEDA_ARPG_STAGE16A_PRE_GODOT_V1_8_0_DEV_CHECKPOINT_V0_8_1.zip"
)

UNITTEST_COUNT_RE = re.compile(r"^Ran (\d+) tests? in", re.MULTILINE)

# Every backend suite that must run. step_suite_coverage() fails the whole validation if a
# tests/test_*.py file exists on disk without being listed here, so a suite can never be
# silently dropped from the regression.
BACKEND_SUITES = (
    "tests.test_stage16b_authority_adapter",
    "tests.test_stage16b_authority_http",
    "tests.test_stage16b_authority_profile_loadout",
    "tests.test_stage16b_authority_traversal",
    "tests.test_stage16b_authority_ground_loot",
    "tests.test_stage16b_authority_gathering",
    "tests.test_stage16b_authority_combat",
    "tests.test_stage16b_authority_economy_inventory_quest",
    "tests.test_stage16b_authority_save_death_water",
    "tests.test_stage16a_item_definitions_verify_contract",
    "tests.test_stage16a_checkpoint_governance",
    "tests.test_stage16b_authority_clothes",
    "tests.test_stage16b_authority_dev_water_time",
    "tests.test_stage16b_authority_dev_npc_bag_recovery",
    "tests.test_stage16b_authority_bag_recovery_spatial_retry",
    "tests.test_stage16b_authority_living_systemic",
    "tests.test_stage16b_authority_npc_dialogue",
)


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    master = str(_resolve_master_path())
    env["ANDROMEDA_MASTER_RELEASE"] = master
    env["ANDROMEDA_MASTER"] = master
    env["ANDROMEDA_MASTER_V201"] = master
    env["PYTHONPATH"] = os.pathsep.join(
        [str(RUNTIME_DIR), str(BACKEND_DIR), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run(argv: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        argv, cwd=str(cwd), env=child_env(), capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def step_master() -> dict:
    master = _resolve_master_path()
    digest = hashlib.sha256(master.read_bytes()).hexdigest().upper()
    forbidden = [t for t in FORBIDDEN_MASTER_TOKENS if t in str(master)]
    ok = digest == MASTER_V2_0_1_SHA256 and not forbidden
    return {
        "step": "master_v2_0_1_integrity",
        "status": "PASS" if ok else "FAIL",
        "master_path": str(master),
        "sha256": digest,
        "expected_sha256": MASTER_V2_0_1_SHA256,
        "forbidden_tokens_in_path": forbidden,
        "read_only": True,
    }


def step_checkpoint() -> dict:
    if not CHECKPOINT_ZIP.is_file():
        return {"step": "stage16a_protected_checkpoint", "status": "FAIL", "reason": "CHECKPOINT_MISSING"}
    missing: list[str] = []
    mismatch: list[str] = []
    verified = 0
    with zipfile.ZipFile(CHECKPOINT_ZIP) as archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
        for name in names:
            target = REPO_ROOT / name
            if not target.is_file():
                missing.append(name)
                continue
            if hashlib.sha256(archive.read(name)).digest() == hashlib.sha256(
                target.read_bytes()
            ).digest():
                verified += 1
            else:
                mismatch.append(name)
    ok = not missing and not mismatch and verified == len(names)
    return {
        "step": "stage16a_protected_checkpoint",
        "status": "PASS" if ok else "FAIL",
        "entries": len(names),
        "verified": verified,
        "missing": missing[:20],
        "mismatch": mismatch[:20],
        "protected_bytes_changed": len(missing) + len(mismatch),
    }


def step_suite_coverage() -> dict:
    """Refuse to report PASS while a backend suite exists but is not registered."""
    on_disk = {f"tests.{p.stem}" for p in sorted((BACKEND_DIR / "tests").glob("test_*.py"))}
    registered = set(BACKEND_SUITES)
    unregistered = sorted(on_disk - registered)
    missing_file = sorted(registered - on_disk)
    ok = not unregistered and not missing_file and on_disk
    return {
        "step": "backend_suite_coverage",
        "status": "PASS" if ok else "FAIL",
        "suites_on_disk": len(on_disk),
        "suites_registered": len(registered),
        "unregistered_suites": unregistered,
        "registered_but_missing": missing_file,
    }


def step_unittest(name: str, argv: list[str], cwd: Path) -> dict:
    started = time.time()
    code, output = run(argv, cwd)
    match = UNITTEST_COUNT_RE.search(output)
    tests = int(match.group(1)) if match else 0
    # An explicit trailing "OK" plus a non-zero test count is the only PASS signal.
    passed = code == 0 and output.strip().endswith("OK") and tests > 0
    return {
        "step": name,
        "status": "PASS" if passed else "FAIL",
        "exit_code": code,
        "tests": tests,
        "seconds": round(time.time() - started, 3),
        "tail": output.strip().splitlines()[-6:],
    }


def step_json_runner(name: str, script: Path, cwd: Path) -> dict:
    started = time.time()
    code, output = run([sys.executable, str(script)], cwd)
    payload = None
    for line in reversed(output.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                payload = None
            if payload is not None:
                break
    ok = (
        code == 0
        and isinstance(payload, dict)
        and payload.get("status") == "PASS"
        and int(payload.get("failed", 1)) == 0
        and int(payload.get("passed", 0)) > 0
    )
    return {
        "step": name,
        "status": "PASS" if ok else "FAIL",
        "exit_code": code,
        "report": payload,
        "seconds": round(time.time() - started, 3),
        "tail": output.strip().splitlines()[-6:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(BACKEND_DIR / "reports" / "STAGE16B_AUTHORITY_BACKEND_VALIDATION_V0_8_0.json"))
    args = parser.parse_args()

    started = time.time()
    steps = [step_master(), step_checkpoint()]

    steps.append(step_suite_coverage())
    for module in BACKEND_SUITES:
        steps.append(
            step_unittest(
                f"{module.rsplit('.', 1)[-1]}_suite",
                [sys.executable, "-m", "unittest", module, "-v"],
                BACKEND_DIR,
            )
        )
    steps.append(
        step_unittest(
            "stage16a_regression",
            [sys.executable, "-m", "unittest", "discover", "-s", "03_TESTS/STAGE16A", "-p", "test_*.py"],
            PROJECT_ROOT,
        )
    )
    steps.append(
        step_json_runner(
            "stage16a_vertical_slice_stress",
            PROJECT_ROOT / "03_TESTS/STAGE16A/run_stage16a_vertical_slice_stress.py",
            PROJECT_ROOT,
        )
    )
    steps.append(
        step_json_runner(
            "stage15_validation",
            PROJECT_ROOT / "03_TESTS/run_arpg_stage15_validation.py",
            PROJECT_ROOT,
        )
    )
    steps.append(
        step_json_runner(
            "stage15_stress",
            PROJECT_ROOT / "03_TESTS/run_arpg_stage15_stress.py",
            PROJECT_ROOT,
        )
    )

    failures = [s["step"] for s in steps if s["status"] != "PASS"]
    record = {
        "record_id": "ANDROMEDA-STAGE16B-AUTHORITY-BACKEND-VALIDATION-V0.8.0",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status": "PASS" if not failures else "FAIL",
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "master_version": "V2.0.1",
        "master_promotion_to_v2_1_0": False,
        "protected_checkpoint_bytes_changed": next(
            (s.get("protected_bytes_changed") for s in steps if s["step"] == "stage16a_protected_checkpoint"),
            None,
        ),
        "backend_suites_registered": len(BACKEND_SUITES),
        "python_tests_total": sum(int(s.get("tests") or 0) for s in steps),
        "failures": failures,
        "steps": steps,
        "seconds": round(time.time() - started, 3),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({k: record[k] for k in ("record_id", "status", "failures", "seconds")}, ensure_ascii=False))
    for step in steps:
        print(f"  {step['status']:<4} {step['step']} tests={step.get('tests', step.get('report'))}")
    print(f"evidence -> {out}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
