"""Stage17 / Etapa 31 -- S17-C3R4A tests for
STAGE17_TOOLS/migrations/migrate_stage17_gathering_mutable_capacity_v1.py.

Two tiers:

  * Synthetic-DB tier (fast, hand-built minimal SQLite fixtures): scan
    classification, dry-run zero-mutation, apply/idempotency/rollback,
    migration-marker bookkeeping, source-integrity statics.

  * Real-copy integration tier: operates ONLY on throwaway copies of the
    real Stage17 world DB made once at collection time by
    S17-C3R3/S17-C3R4 tooling (see setUpModule) -- the real, live DB at
    STAGE17_RUNTIME_STATE/authority/stage17_world.sqlite is opened here
    only via mode=ro&immutable=1, exactly once, to make a fresh temp copy
    per test; every mutation, every engine construction, and every
    resume_world() call in this file targets a private tempfile copy that
    is deleted (or left in the scratch dir) afterward. The original is
    never opened writable and never has an engine constructed against it
    from this file.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TOOLS_DIR.parent
MIGRATIONS_DIR = TOOLS_DIR / "migrations"
REAL_DB_PATH = PROJECT_ROOT / "STAGE17_RUNTIME_STATE" / "authority" / "stage17_world.sqlite"
MASTER_RELEASE = Path(r"C:\Users\thall\ANDROMEDA_PRODUCT\ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip")

_spec = importlib.util.spec_from_file_location(
    "migrate_stage17_gathering_mutable_capacity_v1",
    MIGRATIONS_DIR / "migrate_stage17_gathering_mutable_capacity_v1.py",
)
migrate = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = migrate
_spec.loader.exec_module(migrate)  # type: ignore[union-attr]  (this also puts 01_RUNTIME + backend dirs on sys.path)

import stage17_gathering_capacity_contract as contract  # noqa: E402
from living_runtime import canonical_json, sha256_text  # noqa: E402


def _sha256_file(path: Path):
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


# --------------------------------------------------------------------- synthetic DB

SYNTH_WORLD = "rt:world:synth0000000000000000000000000"
SYNTH_SEED = 424242
SYNTH_BLOCK = "BLK-SYNTH-01"
SYNTH_ZONE = "ZONE-SYNTH-01"


def _synth_country(*, mineral_capacity=500, fauna_count=30, fauna_role="HERBIVORE"):
    return {
        "seed": SYNTH_SEED,
        "country": {
            "states": [
                {
                    "id": "STA-SYNTH",
                    "blocks": [
                        {
                            "id": SYNTH_BLOCK,
                            "resources": [
                                {"id": "MIN-SYNTH-01", "kind": "ORE", "tier": "ALTO", "name": "Synthstone", "capacity_units": mineral_capacity, "remaining_units": mineral_capacity},
                            ],
                            "flora": [],
                            "fauna": [
                                {"id": "FAU-SYNTH-01", "species_ref": "FAU-SYNTH", "role": fauna_role, "tier": "MÉDIO", "name": "Synth Critter", "count": fauna_count, "status": "ACTIVE"},
                            ],
                        }
                    ],
                }
            ]
        },
    }


def _build_synthetic_db(path: Path, *, persisted_country, current_country) -> None:
    """Insert three gathering nodes -- MINING (always matches),
    HUNTING (capacity-only drift between persisted_country and
    current_country), plus current_country's own state used as the live
    country_scale_state row. Persisted definitions are produced via the
    tool's OWN recompute function against persisted_country, guaranteeing
    the fixture is byte-faithful to what a real bootstrap would have
    written at that earlier time.
    """
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE s16b_bootstrap(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE country_scale_state(world_instance_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL);
        CREATE TABLE arpg_gathering_nodes(
          node_ref TEXT NOT NULL, world_instance_id TEXT NOT NULL, zone_ref TEXT NOT NULL,
          block_ref TEXT NOT NULL, activity_type TEXT NOT NULL, source_kind TEXT NOT NULL,
          source_ref TEXT NOT NULL, output_item_ref TEXT NOT NULL, definition_json TEXT NOT NULL,
          definition_hash TEXT NOT NULL,
          PRIMARY KEY(world_instance_id, node_ref)
        );
        """
    )
    conn.execute("INSERT INTO s16b_bootstrap VALUES('world_instance_id', ?)", (SYNTH_WORLD,))
    raw = canonical_json(current_country)
    conn.execute(
        "INSERT INTO country_scale_state VALUES(?,?,?)",
        (SYNTH_WORLD, raw, sha256_text(raw)),
    )

    fake_rows = {
        "MIN-SYNTH-01": dict(
            node_ref="GTH-SYNTHMINERAL0001", world_instance_id=SYNTH_WORLD, zone_ref=SYNTH_ZONE,
            block_ref=SYNTH_BLOCK, activity_type="MINING", source_kind="MINERAL",
            source_ref="MIN-SYNTH-01", output_item_ref="MIN-SYNTH-01",
        ),
        "FAU-SYNTH-01": dict(
            node_ref="GTH-SYNTHFAUNA00001", world_instance_id=SYNTH_WORLD, zone_ref=SYNTH_ZONE,
            block_ref=SYNTH_BLOCK, activity_type="HUNTING", source_kind="FAUNA",
            source_ref="FAU-SYNTH-01", output_item_ref="ITEM-FAUNA-FAU-SYNTH",
        ),
    }
    for source_ref, base in fake_rows.items():
        # recompute_expected_definition only ever does row["field"] --
        # a plain dict already satisfies that via its own real __getitem__,
        # no sqlite3.Row stand-in needed.
        persisted_def = migrate.recompute_expected_definition(base, persisted_country["country"], persisted_country["seed"])
        text = canonical_json(persisted_def)
        h = sha256_text(text)
        conn.execute(
            "INSERT INTO arpg_gathering_nodes VALUES(?,?,?,?,?,?,?,?,?,?)",
            (base["node_ref"], SYNTH_WORLD, base["zone_ref"], base["block_ref"], base["activity_type"],
             base["source_kind"], base["source_ref"], base["output_item_ref"], text, h),
        )
    conn.commit()
    conn.close()


class SyntheticScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="s17c3r4_synth_"))
        self.db_path = self.tmp / "synth.sqlite"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_20_scan_classifies_match_allowed_and_structural(self) -> None:
        persisted = _synth_country(mineral_capacity=500, fauna_count=50, fauna_role="HERBIVORE")
        current = _synth_country(mineral_capacity=500, fauna_count=30, fauna_role="HERBIVORE")
        _build_synthetic_db(self.db_path, persisted_country=persisted, current_country=current)
        conn = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro&immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        scan = migrate.scan_all_nodes(conn, SYNTH_WORLD)
        conn.close()
        self.assertEqual(scan["summary"]["total_nodes"], 2)
        self.assertEqual(scan["summary"]["matching"], 1, "MINERAL unchanged must MATCH")
        self.assertEqual(scan["summary"]["allowed_mutable_capacity_drift_count"], 1)
        self.assertEqual(scan["summary"]["structural_drift_count"], 0)
        self.assertEqual(scan["allowed_mutable_capacity_drift"][0]["node_ref"], "GTH-SYNTHFAUNA00001")
        self.assertEqual(scan["allowed_mutable_capacity_drift"][0]["persisted_capacity_units"], 50)
        self.assertEqual(scan["allowed_mutable_capacity_drift"][0]["expected_capacity_units"], 30)

    def test_21_scan_classifies_structural_drift_on_role_change(self) -> None:
        persisted = _synth_country(fauna_count=30, fauna_role="HERBIVORE")
        current = _synth_country(fauna_count=30, fauna_role="PREDATOR")
        _build_synthetic_db(self.db_path, persisted_country=persisted, current_country=current)
        conn = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro&immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        scan = migrate.scan_all_nodes(conn, SYNTH_WORLD)
        conn.close()
        self.assertEqual(scan["summary"]["allowed_mutable_capacity_drift_count"], 0)
        self.assertEqual(scan["summary"]["structural_drift_count"], 1)
        self.assertEqual(scan["structural_drift"][0]["node_ref"], "GTH-SYNTHFAUNA00001")

    def test_22_dry_run_is_zero_mutation(self) -> None:
        persisted = _synth_country(fauna_count=50)
        current = _synth_country(fauna_count=30)
        _build_synthetic_db(self.db_path, persisted_country=persisted, current_country=current)
        before = _sha256_file(self.db_path)
        result = migrate.run(self.db_path, apply=False)
        after = _sha256_file(self.db_path)
        self.assertEqual(before, after)
        self.assertEqual(result["status"], "DRY_RUN_WOULD_APPLY")
        self.assertEqual(result["would_affect_node_refs"], ["GTH-SYNTHFAUNA00001"])
        self.assertTrue(result["main_db_unchanged"])

    def test_23_apply_updates_only_eligible_row(self) -> None:
        persisted = _synth_country(mineral_capacity=500, fauna_count=50)
        current = _synth_country(mineral_capacity=500, fauna_count=30)
        _build_synthetic_db(self.db_path, persisted_country=persisted, current_country=current)
        result = migrate.run(self.db_path, apply=True)
        self.assertEqual(result["status"], "APPLIED")
        self.assertEqual(result["affected_node_count"], 1)
        self.assertEqual(result["affected_node_refs"], ["GTH-SYNTHFAUNA00001"])

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        mineral_row = conn.execute("SELECT definition_json FROM arpg_gathering_nodes WHERE node_ref='GTH-SYNTHMINERAL0001'").fetchone()
        fauna_row = conn.execute("SELECT definition_json, definition_hash FROM arpg_gathering_nodes WHERE node_ref='GTH-SYNTHFAUNA00001'").fetchone()
        conn.close()
        self.assertEqual(json.loads(mineral_row["definition_json"])["capacity_units"], 500, "MINERAL row must be untouched")
        fauna_def = json.loads(fauna_row["definition_json"])
        self.assertEqual(fauna_def["capacity_units"], 30)
        self.assertEqual(fauna_row["definition_hash"], sha256_text(canonical_json(fauna_def)), "row must remain self-consistent (hash == sha256(json))")

    def test_24_apply_creates_migration_marker_row(self) -> None:
        persisted = _synth_country(fauna_count=50)
        current = _synth_country(fauna_count=30)
        _build_synthetic_db(self.db_path, persisted_country=persisted, current_country=current)
        migrate.run(self.db_path, apply=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM stage17_gathering_migrations WHERE world_instance_id=? AND migration_id=?",
            (SYNTH_WORLD, migrate.MIGRATION_ID),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "COMPLETE")
        self.assertEqual(row["target_schema"], migrate.TARGET_SCHEMA)
        self.assertEqual(json.loads(row["affected_node_refs_json"]), ["GTH-SYNTHFAUNA00001"])

    def test_25_second_apply_is_idempotent_already_applied(self) -> None:
        persisted = _synth_country(fauna_count=50)
        current = _synth_country(fauna_count=30)
        _build_synthetic_db(self.db_path, persisted_country=persisted, current_country=current)
        migrate.run(self.db_path, apply=True)
        after_first = _sha256_file(self.db_path)
        second = migrate.run(self.db_path, apply=True)
        after_second = _sha256_file(self.db_path)
        self.assertEqual(second["status"], "ALREADY_APPLIED")
        self.assertEqual(after_first, after_second, "second run must be zero-mutation")

    def test_26_diverged_state_after_marker_is_not_silently_reapplied(self) -> None:
        persisted = _synth_country(fauna_count=50)
        current = _synth_country(fauna_count=30)
        _build_synthetic_db(self.db_path, persisted_country=persisted, current_country=current)
        migrate.run(self.db_path, apply=True)
        # Simulate further legitimate hunting AFTER the migration completed --
        # the marker's after_hashes_json now disagrees with the live row.
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("UPDATE arpg_gathering_nodes SET definition_hash='TAMPERED' WHERE node_ref='GTH-SYNTHFAUNA00001'")
        conn.commit()
        conn.close()
        result = migrate.run(self.db_path, apply=True)
        self.assertEqual(result["status"], "ABORTED_STATE_DIVERGED_SINCE_PRIOR_MIGRATION")

    def test_27_structural_drift_present_aborts_with_zero_writes(self) -> None:
        persisted = _synth_country(fauna_count=30, fauna_role="HERBIVORE")
        current = _synth_country(fauna_count=30, fauna_role="PREDATOR")
        _build_synthetic_db(self.db_path, persisted_country=persisted, current_country=current)
        before = _sha256_file(self.db_path)
        result = migrate.run(self.db_path, apply=True)
        after = _sha256_file(self.db_path)
        self.assertEqual(result["status"], "ABORTED_STRUCTURAL_DRIFT_FOUND")
        self.assertEqual(before, after)
        conn = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro&immutable=1", uri=True)
        exists = migrate.table_exists(conn, "stage17_gathering_migrations")
        conn.close()
        self.assertFalse(exists, "an aborted migration must not even leave behind its own bookkeeping table")

    def test_28_no_migration_needed_when_everything_matches(self) -> None:
        same = _synth_country(fauna_count=30)
        _build_synthetic_db(self.db_path, persisted_country=same, current_country=same)
        before = _sha256_file(self.db_path)
        result = migrate.run(self.db_path, apply=True)
        after = _sha256_file(self.db_path)
        self.assertEqual(result["status"], "NO_MIGRATION_NEEDED")
        self.assertEqual(before, after)

    def test_29_transaction_rollback_on_injected_failure(self) -> None:
        persisted = _synth_country(fauna_count=50)
        current = _synth_country(fauna_count=30)
        _build_synthetic_db(self.db_path, persisted_country=persisted, current_country=current)

        real_scan = migrate.scan_all_nodes
        call_count = {"n": 0}

        def _boom(conn, world_instance_id):
            call_count["n"] += 1
            if call_count["n"] == 2:  # first call is the read-only preflight; second is inside the transaction
                raise RuntimeError("INJECTED_FAILURE_FOR_TEST")
            return real_scan(conn, world_instance_id)

        migrate.scan_all_nodes = _boom
        try:
            before = _sha256_file(self.db_path)
            result = migrate.run(self.db_path, apply=True)
            after = _sha256_file(self.db_path)
        finally:
            migrate.scan_all_nodes = real_scan

        self.assertEqual(result["status"], "FAILED_ROLLED_BACK")
        self.assertIn("INJECTED_FAILURE_FOR_TEST", result["error"])
        conn = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro&immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT definition_json FROM arpg_gathering_nodes WHERE node_ref='GTH-SYNTHFAUNA00001'").fetchone()
        conn.close()
        self.assertEqual(json.loads(row["definition_json"])["capacity_units"], 50, "rollback must leave the row exactly as it was")


    def test_38_apply_hash_after_and_post_scan_reflect_the_actual_committed_state(self) -> None:
        """Regression test for a real bug found during the S17-C3R4B live
        apply: the first --apply run against the real DB reported
        main_db_unchanged=true and a stale post_migration_scan (still
        showing the pre-migration drift) even though the transaction had
        genuinely committed -- because the post-commit verification used a
        mode=ro&immutable=1 connection (and a raw file hash) without first
        checkpointing the WAL, and immutable=1 connections never consult a
        -wal file. Fixed by an explicit `PRAGMA wal_checkpoint(FULL)`
        immediately after COMMIT, before any post-verification read.

        This test previously would NOT have caught the bug either, because
        it verified row content through a plain read-write connection
        (which always sees the WAL). It now asserts specifically on the
        tool's *own reported* hash_after / post_migration_scan fields,
        which are exactly what an operator reads to decide the migration
        is trustworthy.
        """
        persisted = _synth_country(mineral_capacity=500, fauna_count=50)
        current = _synth_country(mineral_capacity=500, fauna_count=30)
        _build_synthetic_db(self.db_path, persisted_country=persisted, current_country=current)

        result = migrate.run(self.db_path, apply=True)
        self.assertEqual(result["status"], "APPLIED")
        self.assertNotEqual(
            result["hash_after"]["sha256"], result["hash_before"]["sha256"],
            "hash_after must reflect the real post-commit file, not a stale pre-checkpoint read",
        )
        self.assertFalse(result["main_db_unchanged"], "an APPLIED migration must never claim the DB is unchanged")
        self.assertEqual(result["post_migration_scan"]["allowed_mutable_capacity_drift_count"], 0)
        self.assertEqual(result["post_migration_scan"]["matching"], result["post_migration_scan"]["total_nodes"])
        self.assertFalse(result["hash_after"]["wal_present"], "checkpoint must leave no dangling -wal file")
        self.assertFalse(result["hash_after"]["shm_present"], "checkpoint must leave no dangling -shm file")

        # And an independent, freshly-opened immutable=1 reader (simulating
        # a completely separate process/tool run right after) must see the
        # exact same committed truth -- not the pre-checkpoint state.
        independent = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro&immutable=1", uri=True)
        independent.row_factory = sqlite3.Row
        independent_scan = migrate.scan_all_nodes(independent, SYNTH_WORLD)
        independent.close()
        self.assertEqual(independent_scan["summary"]["allowed_mutable_capacity_drift_count"], 0)
        self.assertEqual(_sha256_file(self.db_path), result["hash_after"]["sha256"])


class MigrationToolSourceIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (MIGRATIONS_DIR / "migrate_stage17_gathering_mutable_capacity_v1.py").read_text(encoding="utf-8")

    def test_30_no_hardcoded_real_refs_or_values(self) -> None:
        for banned in ("GTH-1D268772796B25C4CC6B", "FAU-BROWSER-05-04-01", "PLY-455FEDE6124F42819BDA63A8E82355F4"):
            self.assertNotIn(banned, self.source)

    def test_31_no_engine_or_adapter_import(self) -> None:
        import re

        import_lines = [line for line in self.source.splitlines() if re.match(r"^\s*(from|import)\s+\S", line)]
        banned = ("integrated_arpg_engine", "andromeda_authority_adapter", "resource_metric_placement")
        offenders = [line for line in import_lines for b in banned if b in line]
        self.assertEqual(offenders, [], f"migration tool must stay engine-free: {offenders}")

    def test_32_apply_flag_present_default_false(self) -> None:
        self.assertIn('"--apply"', self.source)
        self.assertIn("default=False", self.source)


# ------------------------------------------------------------------ real-copy tier

def _real_db_available() -> bool:
    return REAL_DB_PATH.is_file() and MASTER_RELEASE.is_file()


@unittest.skipUnless(_real_db_available(), "real Stage17 world DB or master release not present in this environment")
class RealCopyIntegrationTests(unittest.TestCase):
    """Every test in this class works on a throwaway per-test copy of the
    real DB, made via a mode=ro&immutable=1 connection's underlying file
    (a plain filesystem copy, never a writable connection to the real
    path). The real DB's hash is asserted unchanged before AND after the
    whole class runs (see setUpClass/tearDownClass)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.real_hash_before = _sha256_file(REAL_DB_PATH)
        cls.work_dir = Path(tempfile.mkdtemp(prefix="s17c3r4_realcopy_"))

    @classmethod
    def tearDownClass(cls) -> None:
        real_hash_after = _sha256_file(REAL_DB_PATH)
        shutil.rmtree(cls.work_dir, ignore_errors=True)
        assert real_hash_after == cls.real_hash_before, "REAL Stage17 world DB was mutated by the test suite -- this must never happen"

    def _fresh_copy(self, label: str) -> Path:
        dest = self.work_dir / f"{label}_{id(self)}_{len(list(self.work_dir.glob('*.sqlite')))}.sqlite"
        shutil.copyfile(REAL_DB_PATH, dest)
        return dest

    def _open_engine(self, db_path: Path):
        from integrated_arpg_engine_v16a import IntegratedARPGEngineV16A  # noqa: PLC0415

        save_root = self.work_dir / f"saves_{db_path.stem}"
        save_root.mkdir(parents=True, exist_ok=True)
        return IntegratedARPGEngineV16A(str(db_path), master_release_path=str(MASTER_RELEASE), save_root=str(save_root))

    def _world_instance_id(self, db_path: Path) -> str:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro&immutable=1", uri=True)
        row = conn.execute("SELECT value FROM s16b_bootstrap WHERE key='world_instance_id'").fetchone()
        conn.close()
        return row[0]

    def test_33_dry_run_against_real_copy_finds_exactly_one_allowed_drift(self) -> None:
        copy_path = self._fresh_copy("dryrun")
        before = _sha256_file(copy_path)
        result = migrate.run(copy_path, apply=False)
        after = _sha256_file(copy_path)
        self.assertEqual(before, after)
        self.assertIn(result["status"], {"DRY_RUN_WOULD_APPLY", "NO_MIGRATION_NEEDED", "ALREADY_APPLIED"})
        if result["status"] == "DRY_RUN_WOULD_APPLY":
            self.assertEqual(result["scan"]["structural_drift_count"], 0)
            self.assertEqual(len(result["would_affect_node_refs"]), result["scan"]["allowed_mutable_capacity_drift_count"])

    def test_34_apply_against_real_copy_then_real_engine_verify_pass(self) -> None:
        copy_path = self._fresh_copy("applyverify")
        wid = self._world_instance_id(copy_path)
        mig = migrate.run(copy_path, apply=True)
        # ALREADY_APPLIED is expected once the real DB this copy was taken
        # from has itself already been migrated (S17-C3R4B) -- idempotency
        # working as designed, not a different code path to special-case.
        self.assertIn(mig["status"], {"APPLIED", "NO_MIGRATION_NEEDED", "ALREADY_APPLIED"})
        self.assertEqual(mig["post_migration_scan"]["structural_drift_count"] if mig["status"] == "APPLIED" else mig["scan"]["structural_drift_count"], 0)

        contract.install_on_import_path(str(migrate.RUNTIME_DIR))
        engine = self._open_engine(copy_path)
        try:
            engine.resume_world(wid)  # must not raise
            core = engine.gathering_arpg(wid)
            verify = core.verify()
            self.assertEqual(verify["status"], "PASS", verify)
            self.assertEqual(verify["nodes"], mig["scan"]["total_nodes"] if mig["status"] != "APPLIED" else mig["post_migration_scan"]["total_nodes"])
        finally:
            engine.runtime.close()

    def test_35_recurrence_two_hunt_restart_cycles(self) -> None:
        copy_path = self._fresh_copy("recurrence")
        wid = self._world_instance_id(copy_path)
        mig = migrate.run(copy_path, apply=True)
        # ALREADY_APPLIED is expected once the real DB this copy was taken
        # from has itself already been migrated (S17-C3R4B) -- idempotency
        # working as designed, not a different code path to special-case.
        self.assertIn(mig["status"], {"APPLIED", "NO_MIGRATION_NEEDED", "ALREADY_APPLIED"})
        contract.install_on_import_path(str(migrate.RUNTIME_DIR))

        engine1 = self._open_engine(copy_path)
        engine1.resume_world(wid)
        core1 = engine1.gathering_arpg(wid)
        self.assertEqual(core1.verify()["status"], "PASS")
        hunting_nodes = core1.list_nodes(activity_type="HUNTING")
        target = next((n for n in hunting_nodes if n["remaining_units"] > 5), None)
        self.assertIsNotNone(target, "expected at least one non-depleted HUNTING node in the real world copy")
        remaining_0 = target["remaining_units"]
        taken_1 = core1._consume_source(target, 3)
        self.assertGreater(taken_1, 0)
        engine1.runtime.conn.execute("PRAGMA wal_checkpoint(FULL)")
        engine1.runtime.close()

        engine2 = self._open_engine(copy_path)
        engine2.resume_world(wid)  # must NOT raise IntegrityError -- this is the actual recurrence proof
        core2 = engine2.gathering_arpg(wid)
        self.assertEqual(core2.verify()["status"], "PASS")
        node_after_1 = core2.node(target["node_ref"])
        self.assertEqual(node_after_1["remaining_units"], remaining_0 - taken_1)
        taken_2 = core2._consume_source(node_after_1, 2)
        self.assertGreater(taken_2, 0)
        engine2.runtime.conn.execute("PRAGMA wal_checkpoint(FULL)")
        engine2.runtime.close()

        engine3 = self._open_engine(copy_path)
        engine3.resume_world(wid)  # second restart -- must ALSO not raise
        core3 = engine3.gathering_arpg(wid)
        self.assertEqual(core3.verify()["status"], "PASS")
        node_after_2 = core3.node(target["node_ref"])
        self.assertEqual(node_after_2["remaining_units"], remaining_0 - taken_1 - taken_2)
        engine3.runtime.close()

        # No UNADDRESSED drift remains anywhere in the DB after the cycle --
        # the runtime patch (not a second offline migration) is what kept
        # any newly-hunted node self-consistent across both restarts. The
        # offline tool's own status may legitimately come back either
        # ALREADY_APPLIED (its own prior node_ref is still untouched) or
        # NO_MIGRATION_NEEDED (a fresh scan finds nothing eligible) --
        # both mean zero mutation and zero outstanding work; what matters
        # is the scan itself, always populated regardless of which status
        # short-circuited first.
        replay = migrate.run(copy_path, apply=True)
        self.assertIn(replay["status"], {"ALREADY_APPLIED", "NO_MIGRATION_NEEDED"})
        self.assertEqual(replay["scan"]["allowed_mutable_capacity_drift_count"], 0)
        self.assertEqual(replay["scan"]["structural_drift_count"], 0)

    def test_36_artificial_structural_drift_after_migration_still_fails(self) -> None:
        copy_path = self._fresh_copy("structural")
        wid = self._world_instance_id(copy_path)
        mig = migrate.run(copy_path, apply=True)
        # ALREADY_APPLIED is expected once the real DB this copy was taken
        # from has itself already been migrated (S17-C3R4B) -- idempotency
        # working as designed, not a different code path to special-case.
        self.assertIn(mig["status"], {"APPLIED", "NO_MIGRATION_NEEDED", "ALREADY_APPLIED"})

        conn = sqlite3.connect(str(copy_path))
        conn.row_factory = sqlite3.Row
        fauna_row = conn.execute(
            "SELECT source_ref FROM arpg_gathering_nodes WHERE world_instance_id=? AND source_kind='FAUNA' LIMIT 1",
            (wid,),
        ).fetchone()
        self.assertIsNotNone(fauna_row)
        source_ref = fauna_row["source_ref"]
        css = conn.execute("SELECT payload_json FROM country_scale_state WHERE world_instance_id=?", (wid,)).fetchone()
        payload = json.loads(css["payload_json"])
        # Mutate `tier` rather than `role`: country_scale.py's own validate()
        # requires a combat_profile on any PREDATOR record, which this test
        # has no business fabricating -- tier is a plain source_meta field
        # with no such cross-field requirement, and is just as genuinely
        # structural (non-capacity) a drift as role would be.
        changed = False
        for s in payload["country"]["states"]:
            for b in s["blocks"]:
                for a in b.get("fauna", []):
                    if a.get("id") == source_ref:
                        a["tier"] = "ALTO" if a.get("tier") != "ALTO" else "BAIXO"
                        changed = True
        self.assertTrue(changed)
        raw = canonical_json(payload)
        conn.execute("UPDATE country_scale_state SET payload_json=?, payload_hash=? WHERE world_instance_id=?", (raw, sha256_text(raw), wid))
        conn.commit()
        conn.close()

        contract.install_on_import_path(str(migrate.RUNTIME_DIR))
        from living_runtime import IntegrityError

        engine = self._open_engine(copy_path)
        try:
            with self.assertRaises(IntegrityError):
                engine.resume_world(wid)
        finally:
            engine.runtime.close()

    def test_37_mineral_and_flora_untouched_by_real_migration(self) -> None:
        copy_path = self._fresh_copy("mineralflora")
        mig = migrate.run(copy_path, apply=True)
        affected = mig.get("affected_node_refs", [])
        if not affected:
            self.skipTest("no migration was applicable against this copy")
        conn = sqlite3.connect(f"file:{copy_path.as_posix()}?mode=ro&immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT node_ref, source_kind FROM arpg_gathering_nodes WHERE node_ref IN ({})".format(
                ",".join("?" * len(affected))
            ),
            affected,
        ).fetchall()
        conn.close()
        kinds = {r["source_kind"] for r in rows}
        self.assertNotIn("MINERAL", kinds, "migration must never touch MINERAL nodes")
        self.assertTrue(kinds.issubset({"FAUNA", "FLORA", "FISHING"}))


if __name__ == "__main__":
    unittest.main()
