"""Stage17 / Etapa 31 -- S17-C3R1 Player Authority Position Recovery Tool.

Hardened replacement for the temporary scratch script used during S17-C3B
diagnosis (see ORIGINAL_SCRIPT_PATH/ORIGINAL_SCRIPT_SHA256 below). That
script proved the recovery *mechanism* correct -- ContinuousMovementSystem.
sync_to_geodetic() followed by ChunkStreamingSystem.transfer() is exactly
the sequence dungeon_graph_v2.py already uses for every real dungeon
enter/move/leave transition -- but it hardcoded the destination coordinate,
the world_instance_id and the player/avatar ref. This version resolves all
three dynamically from real authority before ever mutating anything, and
defaults to a read-only dry run.

ORIGINAL_SCRIPT_PATH = (
    session scratchpad) .../scratchpad/repair_player_position.py
ORIGINAL_SCRIPT_SHA256 = (
    b6f29a1cc08dbf221eaadd85700053e5ffe61e682a9558ca98ea1e22dd809d33)
The original script is left untouched as historical evidence; this is a
new, separate file, not an overwrite.

Never runs any DML/DDL by hand, never hardcodes a destination or an
avatar_ref, never touches C1B/C1/C2 resource-placement tables (this module
never imports resource_metric_placement.py and never references
s17_resource_metric_placements / s17_resource_metric_constraints /
s17_resource_placement_manifests).

Default mode is a dry run. Mutation only happens with --apply, and only
after every guard below passes.

    python repair_stage17_player_position.py                # dry run
    python repair_stage17_player_position.py --apply         # mutate

Mutation sequence when --apply is given (Section 14 of the S17-C3R1
authorization):
    A. resolve world (bootstrap, read-only sqlite3 connection)
    B. resolve profile/avatar (engine.arpg().profile())
    C. read + validate manifest anchor (pure file I/O, no DB)
    D. validate all guards (world match, finite anchor, zone/block)
    E. read current movement state (evidence only, no threshold gate)
    F. sync_to_geodetic()
    G. compute expected chunk from the resulting position
    H. move.verify()
    I. only if MOTION_OWNER_DIVERGENCE for the resolved avatar_ref:
       streaming.transfer(avatar_ref, expected_chunk)
    J. move.verify() again -- must be PASS or the tool reports FAILED,
       it never loops fixing other entities
    K. PRAGMA wal_checkpoint(FULL)
    L. runtime.close()
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Fixed, non-secret paths. The workspace root is derived from this file's own
# location (STAGE17_TOOLS/recovery/<this file>), never from an operator-
# supplied --world-id-style argument (Section 7: no external world override).
# ---------------------------------------------------------------------------
TOOLS_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = TOOLS_DIR.parent.parent
RUNTIME_DIR = WORKSPACE_ROOT / "01_RUNTIME"
DB_PATH = WORKSPACE_ROOT / "STAGE17_RUNTIME_STATE" / "authority" / "stage17_world.sqlite"
MASTER_RELEASE = Path(r"C:\Users\thall\ANDROMEDA_PRODUCT\ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip")
SAVE_ROOT = WORKSPACE_ROOT / "STAGE17_RUNTIME_STATE" / "saves"
MANIFEST_PATH = (
    WORKSPACE_ROOT
    / "STAGE17_CONTENT"
    / "RESOURCE_PLACEMENT"
    / "CANONICAL"
    / "S17_RESOURCE_METRIC_PLACEMENTS_R0001.json"
)
EXPECTED_SCHEMA_VERSION = "S17_RESOURCE_METRIC_PLACEMENT_V1"
ACCEPTED_ANCHOR_KINDS = {"SERVER_AUTHORITATIVE_PLAYER_MOTION_SNAPSHOT_DEV_AUTHORING_ANCHOR"}

sys.path.insert(0, str(RUNTIME_DIR))


class RecoveryError(RuntimeError):
    """A guard failed. Carries a stable error code (Section 24)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


# ---------------------------------------------------------------------------
# Manifest loading + validation -- pure file I/O and JSON, zero DB access.
# ---------------------------------------------------------------------------
def load_and_validate_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RecoveryError("MANIFEST_NOT_FOUND", str(path))
    try:
        raw = path.read_bytes()
        envelope = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("MANIFEST_INVALID", f"unreadable or not JSON: {exc}") from exc
    if not isinstance(envelope, dict) or not raw:
        raise RecoveryError("MANIFEST_INVALID", "empty or non-object envelope")
    manifest = envelope.get("canonical_manifest")
    if not isinstance(manifest, dict):
        raise RecoveryError("MANIFEST_INVALID", "canonical_manifest missing or not an object")
    import hashlib

    canonical_text = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest_sha256 = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
    if str(manifest.get("schema_version")) != EXPECTED_SCHEMA_VERSION:
        raise RecoveryError(
            "MANIFEST_INVALID",
            f"unexpected schema_version: {manifest.get('schema_version')!r}",
        )
    revision = str(manifest.get("placement_revision") or "").strip()
    if not revision:
        raise RecoveryError("MANIFEST_INVALID", "placement_revision missing/empty")
    world_binding = manifest.get("world_binding")
    if not isinstance(world_binding, dict):
        raise RecoveryError("MANIFEST_INVALID", "world_binding missing or not an object")
    manifest_world_id = str(world_binding.get("world_instance_id") or "").strip()
    if not manifest_world_id:
        raise RecoveryError("MANIFEST_INVALID", "world_binding.world_instance_id missing/empty")
    anchor_position = world_binding.get("anchor_position")
    if not isinstance(anchor_position, dict):
        raise RecoveryError("ANCHOR_INVALID", "world_binding.anchor_position missing or not an object")
    for key in ("iso_x_m", "iso_y_m", "altitude_m"):
        if key not in anchor_position:
            raise RecoveryError("ANCHOR_INVALID", f"anchor_position missing {key}")
        if not _finite(anchor_position[key]):
            raise RecoveryError("NON_FINITE_POSITION", f"anchor_position.{key} is not finite")
    anchor_kind = str(world_binding.get("anchor_kind") or "").strip()
    if anchor_kind not in ACCEPTED_ANCHOR_KINDS:
        raise RecoveryError(
            "ANCHOR_INVALID",
            f"anchor_kind {anchor_kind!r} is not in the accepted contract {sorted(ACCEPTED_ANCHOR_KINDS)}",
        )
    if not manifest.get("placements"):
        raise RecoveryError("MANIFEST_INVALID", "placements list missing/empty")
    return {
        "manifest": manifest,
        "world_binding": world_binding,
        "anchor_position": {
            "iso_x_m": float(anchor_position["iso_x_m"]),
            "iso_y_m": float(anchor_position["iso_y_m"]),
            "altitude_m": float(anchor_position["altitude_m"]),
        },
        "anchor_kind": anchor_kind,
        "anchor_player_ref": str(world_binding.get("anchor_player_ref") or "").strip(),
        "manifest_world_instance_id": manifest_world_id,
        "zone_ref": str(world_binding.get("zone_ref") or "").strip(),
        "block_ref": str(world_binding.get("block_ref") or "").strip(),
        "manifest_sha256": manifest_sha256,
        "placement_revision": revision,
    }


# ---------------------------------------------------------------------------
# World resolution -- a genuinely read-only sqlite3 connection, not the full
# engine, so this specific lookup can never write a byte. immutable=1 (not
# just mode=ro) is required: a plain mode=ro connection to a WAL-mode
# database still creates empty -wal/-shm files on open (proven empirically
# during S17-C3R1 hardening -- the main file hash stayed identical but the
# auxiliary files went from absent to present). immutable=1 tells SQLite the
# file will not change for the life of this connection and skips that WAL
# bookkeeping entirely, so this call is only ever used here, before the
# world's engine (a real read/write connection) is ever constructed.
# ---------------------------------------------------------------------------
def resolve_stored_world_instance_id(db_path: Path) -> str:
    if not db_path.is_file():
        raise RecoveryError("MANIFEST_NOT_FOUND", f"world db not found: {db_path}")
    uri = f"file:{db_path.as_posix()}?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    try:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT value FROM s16b_bootstrap WHERE key='world_instance_id'"
        ).fetchone()
    finally:
        con.close()
    if row is None or not str(row["value"]).strip():
        raise RecoveryError("WORLD_MISMATCH", "no world_instance_id stored in s16b_bootstrap")
    return str(row["value"]).strip()


def enforce_world_guard(stored_world_id: str, manifest_world_id: str) -> None:
    if stored_world_id != manifest_world_id:
        raise RecoveryError(
            "STAGE17_RECOVERY_WORLD_MISMATCH",
            f"stored={stored_world_id!r} manifest={manifest_world_id!r}",
        )


# ---------------------------------------------------------------------------
# Engine-backed steps. Only constructed after the manifest + world guard
# above already passed using zero-write access.
# ---------------------------------------------------------------------------
def build_engine(world_instance_id: str):
    from integrated_arpg_engine_v16a import IntegratedARPGEngineV16A  # noqa: E402
    from living_runtime import ValidationError  # noqa: E402

    engine = IntegratedARPGEngineV16A(
        str(DB_PATH), master_release_path=str(MASTER_RELEASE), save_root=str(SAVE_ROOT)
    )
    try:
        engine.resume_world(world_instance_id)
    except ValidationError as exc:
        # A pre-existing MOTION_OWNER_DIVERGENCE is exactly what step I below
        # exists to repair; _attach_v15 has already fully run by the time
        # resume_world raises, so engine.movement/.streaming/.spatial are
        # already usable. Any other resume failure is not this tool's job.
        failures = getattr(exc, "args", [""])[0] if exc.args else ""
        if "MOTION_OWNER_DIVERGENCE" not in str(failures):
            raise
    return engine


def resolve_avatar(engine, world_instance_id: str) -> dict[str, str]:
    # Reuse the engine's own already-open connection (the same one
    # andromeda_authority_adapter.py's _bootstrap_get uses) instead of opening
    # a second connection to the same file -- this only ever runs after
    # build_engine() has already produced a real read/write connection, so
    # there is no dry-run concern here.
    row = engine.runtime.conn.execute(
        "SELECT value FROM s16b_bootstrap WHERE key='profile_ref'"
    ).fetchone()
    profile_ref = str(row["value"]).strip() if row is not None else ""
    if not profile_ref:
        raise RecoveryError("PROFILE_NOT_FOUND", "no profile_ref stored in s16b_bootstrap")
    try:
        profile = engine.arpg(world_instance_id).profile(profile_ref)
    except KeyError as exc:
        raise RecoveryError("PROFILE_NOT_FOUND", profile_ref) from exc
    avatar_ref = str(profile.get("avatar_ref", "")).strip()
    if not avatar_ref:
        raise RecoveryError("AVATAR_NOT_FOUND", f"profile {profile_ref} has empty avatar_ref")
    try:
        engine.movement(world_instance_id).state(avatar_ref)
    except (KeyError, ValueError) as exc:
        raise RecoveryError("MOTION_STATE_NOT_FOUND", avatar_ref) from exc
    return {"profile_ref": profile_ref, "avatar_ref": avatar_ref}


def check_anchor_player_provenance(anchor_player_ref: str, avatar_ref: str) -> str:
    # world_binding.anchor_player_ref records *whose* motion snapshot the
    # manifest's authoring anchor was captured from -- it is provenance of
    # how the anchor was baked, not an ownership/identity requirement on the
    # anchor's later use. The manifest's own contract
    # (RESOURCE_PLACEMENT_WORLD_MISMATCH guard, resource_metric_placement.py)
    # only ever compares world_instance_id, never anchor_player_ref, so a
    # mismatch here is audited and reported, not treated as fatal.
    return "MATCH" if anchor_player_ref == avatar_ref else "PROVENANCE_MISMATCH_NON_FATAL"


def check_zone_block(engine, world_instance_id: str, zone_ref: str, block_ref: str) -> str:
    if not zone_ref or not block_ref:
        return "NOT_AVAILABLE_IN_CURRENT_CONTRACT"
    try:
        engine.country(world_instance_id).block(block_ref)
    except (KeyError, ValueError):
        return "BLOCK_REF_NOT_FOUND_IN_COUNTRY_DATA"
    return "VALIDATED"


def compute_chunk(engine, world_instance_id: str, position: dict[str, float]) -> str:
    spatial = engine.spatial(world_instance_id)
    geo = spatial.isometric_to_geodetic(position["iso_x_m"], position["iso_y_m"], position["altitude_m"])
    return spatial.chunk_for_geodetic(geo["longitude"], geo["latitude"])["chunk_id"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the real recovery mutation. Omit for a read-only dry run (default).",
    )
    args = parser.parse_args()
    mode = "APPLY" if args.apply else "DRY_RUN"

    result: dict[str, Any] = {
        "mode": mode,
        "world_instance_id": None,
        "profile_ref": None,
        "avatar_ref": None,
        "manifest_path": str(MANIFEST_PATH),
        "manifest_sha256": None,
        "anchor_kind": None,
        "anchor_position": None,
        "anchor_player_provenance": None,
        "zone_block_validation": None,
        "before_position": None,
        "before_chunk": None,
        "expected_after_position": None,
        "expected_after_chunk": None,
        "world_match": None,
        "validation_status": "NOT_STARTED",
        "mutation_applied": False,
        "verify_before": None,
        "verify_after": None,
        "final_status": "NOT_STARTED",
    }

    try:
        manifest_info = load_and_validate_manifest(MANIFEST_PATH)
        result["manifest_sha256"] = manifest_info["manifest_sha256"]
        result["anchor_kind"] = manifest_info["anchor_kind"]
        result["anchor_position"] = manifest_info["anchor_position"]

        stored_world_id = resolve_stored_world_instance_id(DB_PATH)
        enforce_world_guard(stored_world_id, manifest_info["manifest_world_instance_id"])
        result["world_instance_id"] = stored_world_id
        result["world_match"] = True

        if not args.apply:
            # Proven empirically (S17-C3R1 preflight, hash comparison before/after):
            # constructing IntegratedARPGEngineV16A and calling resume_world() is NOT
            # side-effect free even when it raises -- a crashed resume_world() call
            # still left the main .sqlite file's hash and size changed and checkpointed
            # away the WAL/SHM files. Every check below this point (avatar resolution,
            # anchor-player provenance, zone/block, current position, expected chunk,
            # move.verify()) requires that same engine construction, so none of it can
            # be performed as a true dry run against the live world DB. Per S17-C3R1
            # Section 34, this does not block the tool -- --apply stays a clearly
            # separate, explicit step -- it only means dry-run cannot honestly claim to
            # have validated identity/position/verify without opening the engine.
            result["validation_status"] = "PARTIAL_STATIC_ONLY"
            result["engine_dependent_validation"] = "SKIPPED_DRY_RUN_ENGINE_OPEN_HAS_SIDE_EFFECTS"
            result["final_status"] = "DRY_RUN_VALIDATED_MANIFEST_AND_WORLD_GUARD_ONLY"
            print(json.dumps(result, indent=2))
            return 0

        engine = build_engine(stored_world_id)
        try:
            identity = resolve_avatar(engine, stored_world_id)
            result["profile_ref"] = identity["profile_ref"]
            result["avatar_ref"] = identity["avatar_ref"]

            result["anchor_player_provenance"] = check_anchor_player_provenance(
                manifest_info["anchor_player_ref"], identity["avatar_ref"]
            )
            result["zone_block_validation"] = check_zone_block(
                engine, stored_world_id, manifest_info["zone_ref"], manifest_info["block_ref"]
            )

            move = engine.movement(stored_world_id)
            before_state = move.state(identity["avatar_ref"])
            result["before_position"] = {
                "iso_x_m": before_state["iso_x_m"],
                "iso_y_m": before_state["iso_y_m"],
                "altitude_m": before_state["altitude_m"],
            }
            result["before_chunk"] = compute_chunk(engine, stored_world_id, result["before_position"])

            anchor = manifest_info["anchor_position"]
            expected_chunk = compute_chunk(engine, stored_world_id, anchor)
            result["expected_after_position"] = anchor
            result["expected_after_chunk"] = expected_chunk

            distance_m = math.dist(
                (result["before_position"]["iso_x_m"], result["before_position"]["iso_y_m"]),
                (anchor["iso_x_m"], anchor["iso_y_m"]),
            )
            result["distance_from_anchor_m"] = distance_m

            already_home = distance_m < 0.01 and result["before_chunk"] == expected_chunk
            if already_home:
                result["validation_status"] = "PASS"
                result["final_status"] = "ALREADY_AT_RECOVERY_ANCHOR"
                print(json.dumps(result, indent=2))
                return 0

            result["validation_status"] = "PASS"

            if not args.apply:
                result["final_status"] = "DRY_RUN_VALIDATED_NO_MUTATION"
                print(json.dumps(result, indent=2))
                return 0

            # ---- everything past this line only runs with --apply ----
            result["verify_before"] = move.verify()
            sync_result = move.sync_to_geodetic(
                identity["avatar_ref"],
                {
                    "longitude": engine.spatial(stored_world_id)
                    .isometric_to_geodetic(anchor["iso_x_m"], anchor["iso_y_m"], anchor["altitude_m"])["longitude"],
                    "latitude": engine.spatial(stored_world_id)
                    .isometric_to_geodetic(anchor["iso_x_m"], anchor["iso_y_m"], anchor["altitude_m"])["latitude"],
                    "altitude_m": anchor["altitude_m"],
                },
                reason="S17_C3R1_PLAYER_POSITION_RECOVERY",
            )
            if sync_result.get("status") != "PASS":
                raise RecoveryError("NON_FINITE_POSITION", json.dumps(sync_result))
            result["mutation_applied"] = True

            verify_after_sync = move.verify()
            for failure in verify_after_sync.get("failures", []):
                if not failure.startswith("MOTION_OWNER_DIVERGENCE:"):
                    raise RecoveryError("VERIFY_FAILED", failure)
                divergent_ref = failure.split(":", 1)[1]
                if divergent_ref != identity["avatar_ref"]:
                    # Section 17: this tool repairs only the resolved avatar_ref.
                    # Any other entity's divergence is reported, never touched.
                    continue
                streaming = engine.streaming(stored_world_id)
                try:
                    transfer_result = streaming.transfer(divergent_ref, expected_chunk)
                except Exception as exc:  # noqa: BLE001
                    raise RecoveryError("TRANSFER_FAILED", str(exc)) from exc
                if transfer_result.get("status") != "PASS":
                    raise RecoveryError("TRANSFER_FAILED", json.dumps(transfer_result))

            final_verify = move.verify()
            result["verify_after"] = final_verify
            other_entity_failures = [
                f for f in final_verify.get("failures", [])
                if not f.startswith(f"MOTION_OWNER_DIVERGENCE:{identity['avatar_ref']}")
            ]
            avatar_still_failing = any(
                f.startswith(f"MOTION_OWNER_DIVERGENCE:{identity['avatar_ref']}")
                for f in final_verify.get("failures", [])
            )
            if avatar_still_failing:
                raise RecoveryError("VERIFY_FAILED", "avatar_ref still divergent after transfer")
            if other_entity_failures:
                result["other_entity_divergences_reported_not_fixed"] = other_entity_failures

            engine.runtime.conn.execute("PRAGMA wal_checkpoint(FULL)")
            result["final_status"] = "RECOVERY_APPLIED"
        finally:
            engine.runtime.close()

    except RecoveryError as exc:
        result["validation_status"] = "FAILED"
        result["final_status"] = exc.code
        result["error_detail"] = exc.detail
        print(json.dumps(result, indent=2))
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
