from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


WORKSPACE_ID = "ANDROMEDA_ARPG_STAGE17_PLAYABLE_VERTICAL_SLICE_V0_DEV"
SOURCE_BACKUP_SHA256 = "77276aa0bcff0475193d2b85a89fdee7d27564b8b5c83af09f8725b414cd67cc"
SOURCE_STAGE16A_V0_8_1_SHA256 = "03bc6b621a5ae8e0bf6542803412611855b32503154221ec7ea1b7aaf28befc4"
SOURCE_STAGE16A_V0_8_0_SHA256 = "21626a3152cb37e167eee24bff9d3142c5d389a8ca2827594b34211591525a6a"
MASTER_V2_0_1_SHA256 = "6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2"
LIVING_V1_0_0_SHA256 = "6f12c9db0976e234ef55cdfe23b998c07240fa8d80eb0d0c247d12bbd16ebabc"

EXCLUDED_TOP_LEVEL = {
    "STAGE17_RUNTIME_STATE",
    "STAGE17_TOOLS",
    "STAGE17_RECORDS",
}
EXCLUDED_ROOT_FILES = {
    "STAGE16B_BASELINE_PROVENANCE.json",
    "STAGE17_INITIAL_SOURCE_MANIFEST_V0_1_0_DEV.json",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def source_entries(root: Path) -> list[dict]:
    entries: list[dict] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts[0] in EXCLUDED_TOP_LEVEL:
            continue
        if len(relative.parts) == 1 and relative.name in EXCLUDED_ROOT_FILES:
            continue
        entries.append(
            {
                "relative_path": relative.as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return entries


def write_initial_manifest(root: Path) -> dict:
    entries = source_entries(root)
    canonical_entries = json.dumps(
        entries, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    manifest_hash = hashlib.sha256(canonical_entries).hexdigest()
    payload = {
        "manifest_id": "ANDROMEDA-STAGE17-INITIAL-SOURCE-MANIFEST-V0.1.0-DEV",
        "workspace_identity": WORKSPACE_ID,
        "scope": "DERIVED_SOURCE_ONLY",
        "excluded": sorted(EXCLUDED_TOP_LEVEL),
        "file_count": len(entries),
        "total_bytes": sum(item["size"] for item in entries),
        "manifest_hash": manifest_hash,
        "hash_definition": "SHA256 of canonical compact JSON for the sorted entries array",
        "entries": entries,
    }
    output = root / "STAGE17_INITIAL_SOURCE_MANIFEST_V0_1_0_DEV.json"
    _write_json(output, payload)
    return payload


def write_provenance(root: Path, manifest: dict) -> dict:
    payload = {
        "record_id": "ANDROMEDA-STAGE17-BASELINE-PROVENANCE-V0.1.0-DEV",
        "stage17_workspace_identity": WORKSPACE_ID,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_stage": "STAGE16B",
        "source_stage_status": "CLOSED",
        "source_checkpoint": {
            "identity": "ANDROMEDA_ARPG_STAGE16B_AUTHORITY_GODOT_CHECKPOINT_V0_1_0",
            "sha256": SOURCE_BACKUP_SHA256,
        },
        "source_backup": {
            "identity": "ANDROMEDA_ARPG_STAGE16B_AUTHORITY_GODOT_BACKUP_V0_1_0",
            "sha256": SOURCE_BACKUP_SHA256,
        },
        "derivation_method": "Stage16A V0.8.1 protected checkpoint extraction plus byte-validated Stage16B backup overlay; Godot and backend copied into distinct Stage17 identities",
        "destination_root": str(root.resolve()),
        "functional_matrix": {"pass": 28, "partial": 0},
        "final_audit": "PASS",
        "restore_validated": True,
        "backup_validated": True,
        "protected_baselines": {
            "stage16a_v0_8_1_sha256": SOURCE_STAGE16A_V0_8_1_SHA256,
            "stage16a_v0_8_0_sha256": SOURCE_STAGE16A_V0_8_0_SHA256,
            "master_v2_0_1_sha256": MASTER_V2_0_1_SHA256,
            "living_simulation_engine_v1_0_0_sha256": LIVING_V1_0_0_SHA256,
        },
        "stage16b_read_only": True,
        "stage17_status": "DEVELOPMENT_WORKSPACE_CREATED",
        "initial_source_manifest": {
            "file": "STAGE17_INITIAL_SOURCE_MANIFEST_V0_1_0_DEV.json",
            "file_count": manifest["file_count"],
            "total_bytes": manifest["total_bytes"],
            "manifest_hash": manifest["manifest_hash"],
        },
    }
    _write_json(root / "STAGE16B_BASELINE_PROVENANCE.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    root = args.workspace.resolve()
    if root.name != WORKSPACE_ID:
        raise SystemExit(f"Unexpected workspace identity: {root}")
    manifest = write_initial_manifest(root)
    provenance = write_provenance(root, manifest)
    print(
        json.dumps(
            {
                "status": "PASS",
                "file_count": manifest["file_count"],
                "total_bytes": manifest["total_bytes"],
                "manifest_hash": manifest["manifest_hash"],
                "created_at": provenance["created_at"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
