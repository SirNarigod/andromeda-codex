"""Stage17 / Etapa 31 -- S17-C3R4B formal gathering mutable-capacity migration.

MIGRATION_ID   : S17_GATHERING_NODE_MUTABLE_CAPACITY_MIGRATION_V1
SOURCE_SCHEMA  : V1_LEGACY_UNVERSIONED
TARGET_SCHEMA  : S17_GATHERING_NODE_DEFINITION_SCHEMA_V2

Formal, generic, idempotent, transactional migration for the gathering-node
definition drift documented in STAGE17_RECORDS/S17_C3R2_* and designed in
STAGE17_RECORDS/S17_C3R3_*. Contains NO hardcoded node_ref, capacity
value, or source_ref -- it scans every row of ``arpg_gathering_nodes`` for
the target world, recomputes each row's current expected definition
directly from ``country_scale_state`` (the same country-scale JSON the
protected ``ARPGGatheringWorkCore._node_definition`` reads), and uses
``stage17_gathering_capacity_contract.classify_definition_diff`` -- the
SAME pure allow-list function the Stage17 runtime patch uses -- to decide,
per row, whether any observed difference is exactly the allowed
"mutable capacity observation" case or a genuine structural drift.

Never constructs an ``ARPGGatheringWorkCore``/engine instance. Never calls
``resume_world()``. Never imports ``andromeda_authority_adapter`` or
``resource_metric_placement``. Touches at most two tables:
``arpg_gathering_nodes`` (UPDATE, only already-allow-listed rows) and
``stage17_gathering_migrations`` (its own new, additive, Stage17-only
table). Uses raw transactional SQL because no public engine API exists to
update an already-inserted gathering node definition (see
STAGE17_RECORDS/S17_C3R3_GATHERING_MUTABLE_CAPACITY_CONTRACT_DESIGN,
Section 11 "SQL policy") -- this is a formal, versioned, transactional,
audited, idempotent, precondition-checked migration, not ad-hoc SQL.

Usage:
    python migrate_stage17_gathering_mutable_capacity_v1.py [--db-path PATH] [--apply]

Default is a dry run (scan + report only, zero writes). ``--apply`` is
required to actually mutate the database, mirroring the
``repair_stage17_player_position.py`` convention already established in
this engagement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = BASE_DIR / "01_RUNTIME"
BACKEND_DIR = BASE_DIR / "12_AUTHORITY_BACKEND_STAGE17"
DEFAULT_DB_PATH = BASE_DIR / "STAGE17_RUNTIME_STATE" / "authority" / "stage17_world.sqlite"

for _p in (str(RUNTIME_DIR), str(BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from living_runtime import canonical_json, sha256_text  # noqa: E402  (pure functions only; see module docstring)
import stage17_gathering_capacity_contract as contract  # noqa: E402

MIGRATION_ID = "S17_GATHERING_NODE_MUTABLE_CAPACITY_MIGRATION_V1"
SOURCE_SCHEMA = contract.CONTRACT_SCHEMA_V1_LEGACY
TARGET_SCHEMA = contract.CONTRACT_SCHEMA_V2
TOOL_VERSION = "1.0.0"

MIGRATION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS stage17_gathering_migrations(
  world_instance_id TEXT NOT NULL,
  migration_id TEXT NOT NULL,
  source_schema TEXT NOT NULL,
  target_schema TEXT NOT NULL,
  started_at_utc TEXT NOT NULL,
  completed_at_utc TEXT NOT NULL,
  status TEXT NOT NULL,
  affected_node_count INTEGER NOT NULL,
  affected_node_refs_json TEXT NOT NULL,
  before_hashes_json TEXT NOT NULL,
  after_hashes_json TEXT NOT NULL,
  migration_payload_hash TEXT NOT NULL,
  tool_version TEXT NOT NULL,
  PRIMARY KEY(world_instance_id, migration_id)
);
"""


# --------------------------------------------------------------------------- utils

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> tuple[str | None, int | None]:
    if not path.exists():
        return None, None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest(), path.stat().st_size


def _stable_float(seed: Any, *parts: Any) -> float:
    raw = "|".join(str(x) for x in (seed,) + parts)
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(h[:16], 16) / float(0xFFFFFFFFFFFFFFFF)


def _find_block(country: dict, block_ref: str) -> dict | None:
    for s in country.get("states", []):
        for b in s.get("blocks", []):
            if b.get("id") == block_ref:
                return b
    return None


def _find_by_id(records: list, rid: str) -> dict | None:
    for r in records:
        if r.get("id") == rid:
            return r
    return None


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.executescript(MIGRATION_TABLE_DDL)


def resolve_world_instance_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM s16b_bootstrap WHERE key='world_instance_id'").fetchone()
    if row is None:
        raise RuntimeError("MIGRATION_PRECONDITION_FAILED: s16b_bootstrap.world_instance_id not found")
    return row["value"]


# ------------------------------------------------------------- definition recompute

def recompute_expected_definition(row: sqlite3.Row, country: dict, seed: Any) -> dict | None:
    """Re-derive what ARPGGatheringWorkCore._node_definition would produce
    for this persisted row RIGHT NOW, reading only country_scale_state.
    Verified byte-identical (via S17-C3R3's full 312-node scan) against the
    protected core's own hashes for every currently-matching row. Returns
    None if the underlying country-scale source can no longer be resolved.
    """
    block = _find_block(country, row["block_ref"])
    if block is None:
        return None

    source_kind = row["source_kind"]
    activity = row["activity_type"]
    source_ref = row["source_ref"]

    if source_kind == "MINERAL":
        src = _find_by_id(block.get("resources", []), source_ref)
        if src is None:
            return None
        capacity = int(src.get("capacity_units", 0))
        source_meta = {"kind": src.get("kind"), "tier": src.get("tier"), "name": src.get("name"), "authority": "COUNTRY_RUNTIME_DERIVED"}
    elif source_kind == "FLORA":
        src = _find_by_id(block.get("flora", []), source_ref)
        if src is None:
            return None
        capacity = int(src.get("capacity_units", 0))
        source_meta = {
            "species_ref": src.get("species_ref"), "tier": src.get("tier"), "name": src.get("name"),
            "flora_canon_guard": "MASTER_FLORA_SPATIALIZATION_BLOCKED; COUNTRY_RUNTIME_DERIVED_ONLY",
        }
    elif source_kind == "FAUNA":
        src = _find_by_id(block.get("fauna", []), source_ref)
        if src is None:
            return None
        capacity = int(src.get("count", 0))
        source_meta = {
            "species_ref": src.get("species_ref"), "role": src.get("role"), "tier": src.get("tier"),
            "name": src.get("name"), "authority": "COUNTRY_RUNTIME_DERIVED_FAUNA_PROXY",
        }
    elif source_kind == "FISHING":
        capacity = 80 + int(_stable_float(seed, row["zone_ref"], "FISH_CAP") * 121)
        source_meta = {
            "river_ref": "RIV-VARDEN", "basin_ref": "BAS-001",
            "species_identity": "UNSPECIFIED_GAMEPLAY_DERIVED",
            "spatial_basis": "RIVER_SEGMENT_INTERSECTS_ZONE_BBOX",
        }
    else:
        return None

    support: list[str] = []
    if activity == "AGRICULTURE":
        support = ["AGZ-001", "RSZ-003"]
    if activity == "HUNTING":
        support = ["JOB-EXPL-CAC-001"]

    return {
        "node_ref": row["node_ref"],
        "world_instance_id": row["world_instance_id"],
        "country_ref": "TER-011",
        "zone_ref": row["zone_ref"],
        "block_ref": row["block_ref"],
        "activity_type": activity,
        "source_kind": source_kind,
        "source_ref": source_ref,
        "output_item_ref": row["output_item_ref"],
        "capacity_units": int(max(0, capacity)),
        "renewability": "LIVING_ECOLOGY_STAGE14" if source_kind in {"FLORA", "FAUNA", "FISHING"} else "NON_RENEWABLE_WITHIN_STAGE09",
        "canonical_context_support_refs": support,
        "canonical_context_scope": "SUPPORT_NOT_EXACT_LOCATION" if support else "NONE",
        "source_meta": source_meta,
        "art_dependency": "NONE_PLACEHOLDER_READY",
        "authority": "ANDROMEDA_ARPG_STAGE09_GATHERING_WORK",
    }


# --------------------------------------------------------------------- scan + check

def scan_all_nodes(conn: sqlite3.Connection, world_instance_id: str) -> dict:
    css_row = conn.execute(
        "SELECT payload_json, payload_hash FROM country_scale_state WHERE world_instance_id=?",
        (world_instance_id,),
    ).fetchone()
    if css_row is None:
        raise RuntimeError("MIGRATION_PRECONDITION_FAILED: country_scale_state missing for world")
    css_self_consistent = sha256_text(css_row["payload_json"]) == css_row["payload_hash"]
    payload = json.loads(css_row["payload_json"])
    country = payload["country"]
    seed = payload.get("seed")

    rows = conn.execute(
        "SELECT * FROM arpg_gathering_nodes WHERE world_instance_id=? ORDER BY node_ref",
        (world_instance_id,),
    ).fetchall()

    match: list[str] = []
    allowed: list[dict[str, Any]] = []
    structural: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []

    for row in rows:
        persisted = json.loads(row["definition_json"])
        expected = recompute_expected_definition(row, country, seed)
        if expected is None:
            unsupported.append({"node_ref": row["node_ref"], "reason": "SOURCE_NOT_RESOLVABLE"})
            continue
        expected_text = canonical_json(expected)
        expected_hash = sha256_text(expected_text)
        if expected_hash == row["definition_hash"]:
            match.append(row["node_ref"])
            continue
        verdict, diff_fields = contract.classify_definition_diff(persisted, expected)
        if verdict == "ALLOWED_MUTABLE_CAPACITY_DRIFT":
            allowed.append(
                {
                    "node_ref": row["node_ref"],
                    "activity_type": row["activity_type"],
                    "source_kind": row["source_kind"],
                    "source_ref": row["source_ref"],
                    "diff_fields": diff_fields,
                    "persisted_hash": row["definition_hash"],
                    "expected_hash": expected_hash,
                    "expected_text": expected_text,
                    "persisted_capacity_units": persisted.get("capacity_units"),
                    "expected_capacity_units": expected.get("capacity_units"),
                }
            )
        else:
            structural.append(
                {
                    "node_ref": row["node_ref"],
                    "diff_fields": diff_fields,
                    "persisted_hash": row["definition_hash"],
                    "expected_hash": expected_hash,
                }
            )

    summary = {
        "total_nodes": len(rows),
        "matching": len(match),
        "allowed_mutable_capacity_drift_count": len(allowed),
        "structural_drift_count": len(structural),
        "unsupported_drift_count": len(unsupported),
        "country_scale_state_self_consistent": css_self_consistent,
    }
    return {
        "summary": summary,
        "match": match,
        "allowed_mutable_capacity_drift": allowed,
        "structural_drift": structural,
        "unsupported_drift": unsupported,
    }


def check_prior_migration(conn: sqlite3.Connection, world_instance_id: str, migration_id: str) -> dict:
    if not table_exists(conn, "stage17_gathering_migrations"):
        return {"state": "NONE"}
    row = conn.execute(
        "SELECT affected_node_refs_json, after_hashes_json FROM stage17_gathering_migrations "
        "WHERE world_instance_id=? AND migration_id=? AND status='COMPLETE'",
        (world_instance_id, migration_id),
    ).fetchone()
    if row is None:
        return {"state": "NONE"}
    affected = json.loads(row["affected_node_refs_json"])
    after_hashes = json.loads(row["after_hashes_json"])
    current: dict[str, str | None] = {}
    for node_ref in affected:
        r = conn.execute(
            "SELECT definition_hash FROM arpg_gathering_nodes WHERE world_instance_id=? AND node_ref=?",
            (world_instance_id, node_ref),
        ).fetchone()
        current[node_ref] = r["definition_hash"] if r else None
    if current == after_hashes:
        return {"state": "COMPLETE_AND_VERIFIED", "affected_node_refs": affected}
    return {"state": "COMPLETE_BUT_DIVERGED", "affected_node_refs": affected, "expected": after_hashes, "actual": current}


# --------------------------------------------------------------------------- run

def run(db_path: Path, apply: bool) -> dict:
    before_hash, before_size = sha256_file(db_path)
    wal = db_path.with_name(db_path.name + "-wal")
    shm = db_path.with_name(db_path.name + "-shm")
    before_wal, before_shm = wal.exists(), shm.exists()

    result: dict[str, Any] = {
        "migration_id": MIGRATION_ID,
        "source_schema": SOURCE_SCHEMA,
        "target_schema": TARGET_SCHEMA,
        "tool_version": TOOL_VERSION,
        "db_path": str(db_path),
        "apply": apply,
        "hash_before": {"sha256": before_hash, "size": before_size, "wal_present": before_wal, "shm_present": before_shm},
    }

    if before_hash is None:
        result["status"] = "ABORTED_DB_NOT_FOUND"
        return result

    ro_conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro&immutable=1", uri=True)
    ro_conn.row_factory = sqlite3.Row
    try:
        world_instance_id = resolve_world_instance_id(ro_conn)
        result["world_instance_id"] = world_instance_id
        prior = check_prior_migration(ro_conn, world_instance_id, MIGRATION_ID)
        scan = scan_all_nodes(ro_conn, world_instance_id)
    finally:
        ro_conn.close()

    result["prior_migration_state"] = prior["state"]
    result["scan"] = scan["summary"]

    def _finish(status: str, **extra: Any) -> dict:
        result["status"] = status
        result.update(extra)
        after_hash, after_size = sha256_file(db_path)
        result["hash_after"] = {
            "sha256": after_hash, "size": after_size,
            "wal_present": wal.exists(), "shm_present": shm.exists(),
        }
        result["main_db_unchanged"] = (after_hash == before_hash and after_size == before_size)
        return result

    if apply and (before_wal or before_shm):
        return _finish(
            "ABORTED_PRECONDITION_WAL_OR_SHM_PRESENT",
            note="Refuses to --apply while -wal/-shm exist; checkpoint/close every other connection first.",
        )

    if prior["state"] == "COMPLETE_AND_VERIFIED":
        return _finish("ALREADY_APPLIED", affected_node_refs=prior["affected_node_refs"])

    if prior["state"] == "COMPLETE_BUT_DIVERGED":
        return _finish(
            "ABORTED_STATE_DIVERGED_SINCE_PRIOR_MIGRATION",
            divergence={"expected": prior["expected"], "actual": prior["actual"]},
        )

    if scan["structural_drift"] or scan["unsupported_drift"]:
        return _finish(
            "ABORTED_STRUCTURAL_DRIFT_FOUND",
            structural_drift=scan["structural_drift"],
            unsupported_drift=scan["unsupported_drift"],
        )

    if not scan["allowed_mutable_capacity_drift"]:
        return _finish("NO_MIGRATION_NEEDED")

    if not apply:
        return _finish(
            "DRY_RUN_WOULD_APPLY",
            would_affect_node_refs=[n["node_ref"] for n in scan["allowed_mutable_capacity_drift"]],
        )

    # ---- writable, transactional path -------------------------------------------------
    started_at = _now_iso()
    wconn = sqlite3.connect(str(db_path))
    wconn.row_factory = sqlite3.Row
    try:
        wconn.execute("BEGIN IMMEDIATE")
        ensure_migration_table(wconn)

        prior2 = check_prior_migration(wconn, world_instance_id, MIGRATION_ID)
        if prior2["state"] == "COMPLETE_AND_VERIFIED":
            wconn.execute("ROLLBACK")
            return _finish("ALREADY_APPLIED", affected_node_refs=prior2["affected_node_refs"])
        if prior2["state"] == "COMPLETE_BUT_DIVERGED":
            wconn.execute("ROLLBACK")
            return _finish(
                "ABORTED_STATE_DIVERGED_SINCE_PRIOR_MIGRATION",
                divergence={"expected": prior2["expected"], "actual": prior2["actual"]},
            )

        scan2 = scan_all_nodes(wconn, world_instance_id)
        if scan2["structural_drift"] or scan2["unsupported_drift"]:
            wconn.execute("ROLLBACK")
            return _finish(
                "ABORTED_STRUCTURAL_DRIFT_FOUND",
                structural_drift=scan2["structural_drift"],
                unsupported_drift=scan2["unsupported_drift"],
            )
        eligible = scan2["allowed_mutable_capacity_drift"]
        if not eligible:
            wconn.execute("ROLLBACK")
            return _finish("NO_MIGRATION_NEEDED")

        before_hashes: dict[str, str] = {}
        after_hashes: dict[str, str] = {}
        affected_refs: list[str] = []
        for item in eligible:
            node_ref = item["node_ref"]
            before_hashes[node_ref] = item["persisted_hash"]
            wconn.execute(
                "UPDATE arpg_gathering_nodes SET definition_json=?, definition_hash=? "
                "WHERE world_instance_id=? AND node_ref=?",
                (item["expected_text"], item["expected_hash"], world_instance_id, node_ref),
            )
            after_hashes[node_ref] = item["expected_hash"]
            affected_refs.append(node_ref)

        affected_refs_sorted = sorted(affected_refs)
        completed_at = _now_iso()
        payload_for_hash = {
            "migration_id": MIGRATION_ID,
            "source_schema": SOURCE_SCHEMA,
            "target_schema": TARGET_SCHEMA,
            "world_instance_id": world_instance_id,
            "affected_node_refs": affected_refs_sorted,
            "before_hashes": before_hashes,
            "after_hashes": after_hashes,
        }
        migration_payload_hash = sha256_text(canonical_json(payload_for_hash))

        wconn.execute(
            "INSERT INTO stage17_gathering_migrations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                world_instance_id, MIGRATION_ID, SOURCE_SCHEMA, TARGET_SCHEMA,
                started_at, completed_at, "COMPLETE", len(affected_refs_sorted),
                canonical_json(affected_refs_sorted), canonical_json(before_hashes),
                canonical_json(after_hashes), migration_payload_hash, TOOL_VERSION,
            ),
        )
        wconn.execute("COMMIT")
        # Force the just-committed WAL frames into the main file NOW, while
        # wconn (the connection that owns them) is still open. Without this,
        # the on-disk main-file bytes can lag behind the logical commit for
        # as long as this connection (or any other) stays open, and a
        # mode=ro&immutable=1 reader -- which by design never looks at a
        # -wal file, trusting the main file alone -- would observe stale
        # pre-migration data even though the transaction fully committed.
        # (Discovered empirically during the first real S17-C3R4B apply:
        # the immediate post-commit immutable=1 rescan and the raw
        # sha256_file() hash both reported the OLD state; an independent
        # rescan after full process exit -- once Python's own connection
        # teardown had auto-checkpointed -- correctly reported the new
        # state. See STAGE17_RECORDS/S17_C3R4B_* for the full trace.)
        wconn.execute("PRAGMA wal_checkpoint(FULL)")

        post_conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro&immutable=1", uri=True)
        post_conn.row_factory = sqlite3.Row
        try:
            post_scan = scan_all_nodes(post_conn, world_instance_id)
        finally:
            post_conn.close()

        return _finish(
            "APPLIED",
            affected_node_count=len(affected_refs_sorted),
            affected_node_refs=affected_refs_sorted,
            before_hashes=before_hashes,
            after_hashes=after_hashes,
            migration_payload_hash=migration_payload_hash,
            started_at_utc=started_at,
            completed_at_utc=completed_at,
            post_migration_scan=post_scan["summary"],
        )
    except Exception as exc:
        try:
            wconn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        return _finish("FAILED_ROLLED_BACK", error=f"{type(exc).__name__}: {exc}")
    finally:
        wconn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--apply", action="store_true", default=False)
    args = parser.parse_args()

    result = run(Path(args.db_path), apply=bool(args.apply))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") not in {"FAILED_ROLLED_BACK", "ABORTED_STRUCTURAL_DRIFT_FOUND", "ABORTED_STATE_DIVERGED_SINCE_PRIOR_MIGRATION", "ABORTED_DB_NOT_FOUND", "ABORTED_PRECONDITION_WAL_OR_SHM_PRESENT"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
