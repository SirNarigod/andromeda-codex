"""Validate an external production manifest and copy its declared files to staging.

This utility has no canon-write path.  It is intentionally local and can be
called by a future watcher after UE5, Blender or Canva connections exist.
"""
import argparse
import json
import shutil
from pathlib import Path

REQUIRED = {"manifest_id", "source_hash", "target_niche", "authority", "files"}
ALLOWED_NICHES = {"01_LORE", "03_EPISODIOS", "04_MECANICAS", "05_CRIACAO_PROCEDURAL", "06_ENGINE", "07_AUTOMATION"}


def validate(manifest_path: Path) -> dict:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = REQUIRED - payload.keys()
    if missing:
        raise ValueError(f"missing required fields: {sorted(missing)}")
    if payload["authority"] in {"CANON_WRITE", "CANON_R2_CONFIRMADO"}:
        raise ValueError("external imports cannot declare canon authority")
    if Path(payload["target_niche"]).parts[0] not in ALLOWED_NICHES:
        raise ValueError("unknown target niche")
    if not isinstance(payload["files"], list) or not payload["files"]:
        raise ValueError("manifest requires at least one declared file")
    return payload


def stage(manifest_path: Path, staging_root: Path) -> Path:
    payload = validate(manifest_path)
    source_root = manifest_path.parent.resolve()
    staging_root = staging_root.resolve()
    target = (staging_root / payload["manifest_id"]).resolve()
    if staging_root not in target.parents:
        raise ValueError("manifest_id escapes staging")
    target.mkdir(parents=True, exist_ok=True)
    copied = []
    for declared in payload["files"]:
        source = (source_root / declared).resolve()
        if source_root not in source.parents or not source.is_file():
            raise ValueError(f"declared file is unavailable or escapes inbox: {declared}")
        destination = target / source.name
        shutil.copy2(source, destination)
        copied.append(destination.name)
    (target / "validated_manifest.json").write_text(json.dumps({**payload, "staging_only": True, "copied_files": copied}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--staging", type=Path, required=True)
    args = parser.parse_args()
    print(stage(args.manifest, args.staging))
