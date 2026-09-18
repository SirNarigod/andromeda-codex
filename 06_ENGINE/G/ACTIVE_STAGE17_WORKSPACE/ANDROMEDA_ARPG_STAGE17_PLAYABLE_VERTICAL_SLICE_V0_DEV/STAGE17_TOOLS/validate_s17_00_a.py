from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


EXPECTED_STAGE16B_SHA256 = "77276aa0bcff0475193d2b85a89fdee7d27564b8b5c83af09f8725b414cd67cc"
EXPECTED_STAGE16B_SIZE = 852793
EXPECTED_STAGE16B_ENTRIES = 304
EXPECTED_WORKSPACE = "ANDROMEDA_ARPG_STAGE17_PLAYABLE_VERTICAL_SLICE_V0_DEV"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_zip(path: Path) -> dict:
    with zipfile.ZipFile(path, "r") as archive:
        bad_entry = archive.testzip()
        entry_count = len(archive.infolist())
    return {
        "path": str(path),
        "sha256": sha256(path),
        "size": path.stat().st_size,
        "entry_count": entry_count,
        "testzip": "CLEAN" if bad_entry is None else bad_entry,
    }


def add_check(checks: list[dict], check_id: str, condition: bool, detail: object) -> None:
    checks.append({"id": check_id, "pass": bool(condition), "detail": detail})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    checkpoint = check_zip(args.checkpoint.resolve())
    backup = check_zip(args.backup.resolve())
    provenance_path = workspace / "STAGE16B_BASELINE_PROVENANCE.json"
    manifest_path = workspace / "STAGE17_INITIAL_SOURCE_MANIFEST_V0_1_0_DEV.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    canonical_entries = json.dumps(
        manifest["entries"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    manifest_hash = hashlib.sha256(canonical_entries).hexdigest()

    stage17_godot = (workspace / "13_GODOT_ARPG_STAGE17").resolve()
    stage17_backend = (workspace / "12_AUTHORITY_BACKEND_STAGE17").resolve()
    runtime_state = (workspace / "STAGE17_RUNTIME_STATE").resolve()
    copied_runtime_candidates = [
        path.relative_to(workspace).as_posix()
        for path in workspace.rglob("*")
        if path.is_file()
        and runtime_state not in path.resolve().parents
        and (
            path.name.lower().endswith((".sqlite", ".sqlite3", ".db"))
            or "save" in {part.lower() for part in path.relative_to(workspace).parts[:-1]}
        )
    ]

    checks: list[dict] = []
    add_check(checks, "WORKSPACE_EXISTS", workspace.is_dir(), str(workspace))
    add_check(checks, "WORKSPACE_IDENTITY", workspace.name == EXPECTED_WORKSPACE, workspace.name)
    add_check(checks, "PROVENANCE_EXISTS", provenance_path.is_file(), str(provenance_path))
    add_check(checks, "SOURCE_MANIFEST_EXISTS", manifest_path.is_file(), str(manifest_path))
    for prefix, item in (("CHECKPOINT", checkpoint), ("BACKUP", backup)):
        add_check(checks, f"{prefix}_SHA256", item["sha256"] == EXPECTED_STAGE16B_SHA256, item)
        add_check(checks, f"{prefix}_SIZE", item["size"] == EXPECTED_STAGE16B_SIZE, item["size"])
        add_check(checks, f"{prefix}_ENTRY_COUNT", item["entry_count"] == EXPECTED_STAGE16B_ENTRIES, item["entry_count"])
        add_check(checks, f"{prefix}_TESTZIP", item["testzip"] == "CLEAN", item["testzip"])
    add_check(checks, "BACKUP_CHECKPOINT_BYTE_IDENTITY", args.backup.read_bytes() == args.checkpoint.read_bytes(), True)
    add_check(checks, "PROVENANCE_STAGE16B_CLOSED", provenance.get("source_stage_status") == "CLOSED", provenance.get("source_stage_status"))
    add_check(checks, "PROVENANCE_STAGE16B_READ_ONLY", provenance.get("stage16b_read_only") is True, provenance.get("stage16b_read_only"))
    add_check(checks, "PROVENANCE_28_PASS", provenance.get("functional_matrix") == {"pass": 28, "partial": 0}, provenance.get("functional_matrix"))
    add_check(checks, "PROVENANCE_SOURCE_HASHES", provenance.get("source_checkpoint", {}).get("sha256") == EXPECTED_STAGE16B_SHA256 and provenance.get("source_backup", {}).get("sha256") == EXPECTED_STAGE16B_SHA256, {"checkpoint": provenance.get("source_checkpoint"), "backup": provenance.get("source_backup")})
    add_check(checks, "INITIAL_MANIFEST_SELF_CONSISTENT", manifest_hash == manifest.get("manifest_hash") and len(manifest.get("entries", [])) == manifest.get("file_count") and sum(item["size"] for item in manifest.get("entries", [])) == manifest.get("total_bytes"), {"calculated_hash": manifest_hash, "recorded_hash": manifest.get("manifest_hash"), "file_count": manifest.get("file_count"), "total_bytes": manifest.get("total_bytes")})
    add_check(checks, "GODOT_STAGE17_PATH_SEPARATE", stage17_godot.is_dir() and "07_GODOT_ARPG_STAGE16B" not in str(stage17_godot), str(stage17_godot))
    add_check(checks, "BACKEND_STAGE17_PATH_SEPARATE", stage17_backend.is_dir() and stage17_backend.name == "12_AUTHORITY_BACKEND_STAGE17", str(stage17_backend))
    add_check(checks, "RUNTIME_STATE_SEPARATE", runtime_state.is_dir() and runtime_state.parent == workspace, str(runtime_state))
    add_check(checks, "NO_HISTORICAL_RUNTIME_COPIED", not copied_runtime_candidates, copied_runtime_candidates)

    failed = [item for item in checks if not item["pass"]]
    payload = {
        "gate": "S17_00_BASELINE_FORK_VALIDATION",
        "status": "PASS" if not failed else "FAIL",
        "checks": len(checks),
        "passed": len(checks) - len(failed),
        "failed": len(failed),
        "failures": failed,
        "checkpoint": checkpoint,
        "backup": backup,
        "workspace": str(workspace),
        "initial_manifest": {
            "file_count": manifest.get("file_count"),
            "total_bytes": manifest.get("total_bytes"),
            "manifest_hash": manifest.get("manifest_hash"),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
