from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


EXCLUDED_TOP_LEVEL = {"STAGE17_RUNTIME_STATE", "STAGE17_TOOLS", "STAGE17_RECORDS"}
EXCLUDED_ROOT_FILES = {
    "STAGE16B_BASELINE_PROVENANCE.json",
    "STAGE17_INITIAL_SOURCE_MANIFEST_V0_1_0_DEV.json",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_entries(root: Path) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts[0] in EXCLUDED_TOP_LEVEL:
            continue
        if len(relative.parts) == 1 and relative.name in EXCLUDED_ROOT_FILES:
            continue
        key = relative.as_posix()
        result[key] = {"relative_path": key, "size": path.stat().st_size, "sha256": sha256(path)}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    root = args.workspace.resolve()
    manifest = json.loads((root / "STAGE17_INITIAL_SOURCE_MANIFEST_V0_1_0_DEV.json").read_text(encoding="utf-8"))
    initial = {item["relative_path"]: item for item in manifest["entries"]}
    current = current_entries(root)
    added = [current[key] for key in sorted(current.keys() - initial.keys())]
    deleted = [initial[key] for key in sorted(initial.keys() - current.keys())]
    modified = [
        {"relative_path": key, "before": initial[key], "after": current[key]}
        for key in sorted(current.keys() & initial.keys())
        if current[key]["sha256"] != initial[key]["sha256"]
    ]
    payload = {
        "status": "PASS",
        "baseline_manifest_hash": manifest["manifest_hash"],
        "added_count": len(added),
        "modified_count": len(modified),
        "deleted_count": len(deleted),
        "added": added,
        "modified": modified,
        "deleted": deleted,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
