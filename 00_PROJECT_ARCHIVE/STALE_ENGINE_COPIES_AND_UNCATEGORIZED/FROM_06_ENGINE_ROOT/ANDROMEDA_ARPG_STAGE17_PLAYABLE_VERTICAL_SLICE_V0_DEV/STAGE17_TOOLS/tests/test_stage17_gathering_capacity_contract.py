"""Stage17 / Etapa 31 -- S17-C3R4A unit tests for the versioned mutable-
capacity gathering contract (12_AUTHORITY_BACKEND_STAGE17/
stage17_gathering_capacity_contract.py).

Pure/fast tier: no real Stage17 world DB, no engine, no --apply. Exercises
the diff classifier and the install/uninstall monkeypatch mechanics against
tiny synthetic fixtures only. Heavier real-copy/real-engine coverage lives
in test_migrate_stage17_gathering_mutable_capacity_v1.py.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
import threading
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2] / "12_AUTHORITY_BACKEND_STAGE17"
RUNTIME_DIR = Path(__file__).resolve().parents[2] / "01_RUNTIME"
# Needed only so the patched _insert_node's lazy `from living_runtime import
# IntegrityError` resolves to the real, protected exception type -- this
# test file never constructs an engine and never opens the real world DB.
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

_spec = importlib.util.spec_from_file_location(
    "stage17_gathering_capacity_contract", BACKEND_DIR / "stage17_gathering_capacity_contract.py"
)
contract = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = contract
_spec.loader.exec_module(contract)  # type: ignore[union-attr]

from living_runtime import IntegrityError as RealIntegrityError  # noqa: E402


def _canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _base_def(**overrides) -> dict:
    d = {
        "node_ref": "GTH-TESTNODE0000000001",
        "world_instance_id": "rt:world:testworld00000000000000000000",
        "country_ref": "TER-011",
        "zone_ref": "ZONE-TEST",
        "block_ref": "BLK-TEST",
        "activity_type": "HUNTING",
        "source_kind": "FAUNA",
        "source_ref": "FAU-TEST-01",
        "output_item_ref": "ITEM-FAUNA-FAU-TEST",
        "capacity_units": 40,
        "renewability": "LIVING_ECOLOGY_STAGE14",
        "canonical_context_support_refs": ["JOB-EXPL-CAC-001"],
        "canonical_context_scope": "SUPPORT_NOT_EXACT_LOCATION",
        "source_meta": {"species_ref": "FAU-TEST", "role": "HERBIVORE", "tier": "MÉDIO", "name": "Test Fauna", "authority": "COUNTRY_RUNTIME_DERIVED_FAUNA_PROXY"},
        "art_dependency": "NONE_PLACEHOLDER_READY",
        "authority": "ANDROMEDA_ARPG_STAGE09_GATHERING_WORK",
    }
    d.update(overrides)
    return d


class ClassifyDefinitionDiffTests(unittest.TestCase):
    def test_01_match_no_diff(self) -> None:
        persisted = _base_def()
        expected = _base_def()
        verdict, diff = contract.classify_definition_diff(persisted, expected)
        self.assertEqual(verdict, "MATCH")
        self.assertEqual(diff, [])

    def test_02_allowed_capacity_only_diff_fauna(self) -> None:
        persisted = _base_def(capacity_units=86)
        expected = _base_def(capacity_units=58)
        verdict, diff = contract.classify_definition_diff(persisted, expected)
        self.assertEqual(verdict, "ALLOWED_MUTABLE_CAPACITY_DRIFT")
        self.assertEqual(diff, ["capacity_units"])

    def test_03_structural_diff_source_ref_rejected(self) -> None:
        persisted = _base_def()
        expected = _base_def(source_ref="FAU-TEST-02")
        verdict, diff = contract.classify_definition_diff(persisted, expected)
        self.assertEqual(verdict, "STRUCTURAL_DRIFT")
        self.assertEqual(diff, ["source_ref"])

    def test_04_structural_diff_output_item_ref_rejected(self) -> None:
        persisted = _base_def()
        expected = _base_def(output_item_ref="ITEM-FAUNA-OTHER")
        verdict, diff = contract.classify_definition_diff(persisted, expected)
        self.assertEqual(verdict, "STRUCTURAL_DRIFT")
        self.assertIn("output_item_ref", diff)

    def test_05_structural_diff_block_ref_rejected(self) -> None:
        persisted = _base_def()
        expected = _base_def(block_ref="BLK-OTHER")
        verdict, diff = contract.classify_definition_diff(persisted, expected)
        self.assertEqual(verdict, "STRUCTURAL_DRIFT")
        self.assertIn("block_ref", diff)

    def test_06_structural_diff_activity_type_rejected(self) -> None:
        persisted = _base_def()
        expected = _base_def(activity_type="FORAGING")
        verdict, diff = contract.classify_definition_diff(persisted, expected)
        self.assertEqual(verdict, "STRUCTURAL_DRIFT")
        self.assertIn("activity_type", diff)

    def test_07_capacity_diff_mineral_not_eligible(self) -> None:
        persisted = _base_def(source_kind="MINERAL", renewability="NON_RENEWABLE_WITHIN_STAGE09", capacity_units=900)
        expected = _base_def(source_kind="MINERAL", renewability="NON_RENEWABLE_WITHIN_STAGE09", capacity_units=100)
        verdict, diff = contract.classify_definition_diff(persisted, expected)
        self.assertEqual(verdict, "STRUCTURAL_DRIFT", "MINERAL must never be granted the mutable-capacity bypass")
        self.assertEqual(diff, ["capacity_units"])

    def test_08_capacity_diff_flora_eligible_in_principle(self) -> None:
        persisted = _base_def(source_kind="FLORA", activity_type="LOGGING", capacity_units=4800)
        expected = _base_def(source_kind="FLORA", activity_type="LOGGING", capacity_units=4200)
        verdict, diff = contract.classify_definition_diff(persisted, expected)
        self.assertEqual(verdict, "ALLOWED_MUTABLE_CAPACITY_DRIFT", "FLORA shares the LIVING_ECOLOGY_STAGE14 label -- eligible by contract, even if never observed in practice")

    def test_09_capacity_diff_fishing_eligible_in_principle(self) -> None:
        persisted = _base_def(source_kind="FISHING", activity_type="FISHING", capacity_units=150)
        expected = _base_def(source_kind="FISHING", activity_type="FISHING", capacity_units=140)
        verdict, diff = contract.classify_definition_diff(persisted, expected)
        self.assertEqual(verdict, "ALLOWED_MUTABLE_CAPACITY_DRIFT")

    def test_10_flora_non_capacity_diff_still_rejected(self) -> None:
        persisted = _base_def(source_kind="FLORA", activity_type="LOGGING", source_meta={"species_ref": "FLR-HARDWOOD", "tier": "ALTO", "name": "X", "flora_canon_guard": "g"})
        expected = _base_def(source_kind="FLORA", activity_type="LOGGING", source_meta={"species_ref": "FLR-HARDWOOD", "tier": "BAIXO", "name": "X", "flora_canon_guard": "g"})
        verdict, diff = contract.classify_definition_diff(persisted, expected)
        self.assertEqual(verdict, "STRUCTURAL_DRIFT", "FLORA/FISHING are not blanket-bypassed -- only an exact capacity_units-only diff qualifies")
        self.assertEqual(diff, ["source_meta"])

    def test_11_multi_field_diff_including_capacity_rejected(self) -> None:
        persisted = _base_def(capacity_units=86, source_ref="FAU-TEST-01")
        expected = _base_def(capacity_units=58, source_ref="FAU-TEST-99")
        verdict, diff = contract.classify_definition_diff(persisted, expected)
        self.assertEqual(verdict, "STRUCTURAL_DRIFT", "capacity_units drift stacked with any other diff must not be allow-listed")
        self.assertEqual(sorted(diff), ["capacity_units", "source_ref"])

    def test_12_missing_field_counts_as_structural(self) -> None:
        persisted = _base_def()
        expected = _base_def()
        del expected["art_dependency"]
        verdict, diff = contract.classify_definition_diff(persisted, expected)
        self.assertEqual(verdict, "STRUCTURAL_DRIFT")
        self.assertIn("art_dependency", diff)


class FakeGatheringCore:
    """Minimal stand-in exercising only what _insert_node_v2 touches:
    self._payload, self.runtime.conn, self.runtime._write_lock,
    self.world_instance_id. Backed by a real (in-memory) sqlite connection
    against a table shaped exactly like arpg_gathering_nodes so the patched
    SELECT/UPDATE/INSERT SQL runs for real.
    """

    def __init__(self, conn: sqlite3.Connection, world_instance_id: str) -> None:
        self.runtime = _FakeRuntime(conn)
        self.world_instance_id = world_instance_id

    @staticmethod
    def _payload(obj: dict) -> tuple[str, str]:
        text = _canonical_json(obj)
        return text, _sha256_text(text)

    def _insert_node(self, d: dict, *, state_remaining=None) -> None:
        text, h = self._payload(d)
        with self.runtime._write_lock:
            row = self.runtime.conn.execute(
                "SELECT definition_hash FROM arpg_gathering_nodes WHERE world_instance_id=? AND node_ref=?",
                (self.world_instance_id, d["node_ref"]),
            ).fetchone()
            if row:
                if row["definition_hash"] != h:
                    raise RealIntegrityError("gathering node drift:" + d["node_ref"])
                return
            self.runtime.conn.execute(
                "INSERT INTO arpg_gathering_nodes VALUES(?,?,?)",
                (d["node_ref"], self.world_instance_id, text),
            )
            self.runtime.conn.execute(
                "UPDATE arpg_gathering_nodes SET definition_hash=? WHERE node_ref=? AND world_instance_id=?",
                (h, d["node_ref"], self.world_instance_id),
            )


class _FakeRuntime:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._write_lock = threading.RLock()


def _make_fixture_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE arpg_gathering_nodes(
          node_ref TEXT NOT NULL, world_instance_id TEXT NOT NULL,
          definition_json TEXT NOT NULL, definition_hash TEXT NOT NULL DEFAULT '',
          PRIMARY KEY(world_instance_id, node_ref)
        );
        """
    )
    return conn


class InstallUninstallTests(unittest.TestCase):
    def setUp(self) -> None:
        contract.uninstall()
        contract.RECONCILIATION_LOG.clear()

    def tearDown(self) -> None:
        contract.uninstall()

    def test_13_install_is_idempotent(self) -> None:
        contract.install(FakeGatheringCore)
        patched_once = FakeGatheringCore._insert_node
        contract.install(FakeGatheringCore)
        self.assertIs(FakeGatheringCore._insert_node, patched_once, "second install() must not double-wrap")

    def test_14_uninstall_restores_original(self) -> None:
        original = FakeGatheringCore._insert_node
        contract.install(FakeGatheringCore)
        self.assertIsNot(FakeGatheringCore._insert_node, original)
        contract.uninstall()
        self.assertIs(FakeGatheringCore._insert_node, original)

    def test_15_patched_insert_allows_capacity_only_drift_and_updates_row(self) -> None:
        conn = _make_fixture_conn()
        core = FakeGatheringCore(conn, "rt:world:fixture0000000000000000000000")
        original_def = _base_def(capacity_units=86)
        text, h = core._payload(original_def)
        conn.execute(
            "INSERT INTO arpg_gathering_nodes VALUES(?,?,?,?)",
            (original_def["node_ref"], core.world_instance_id, text, h),
        )
        contract.install(FakeGatheringCore)

        new_def = _base_def(capacity_units=58)
        core._insert_node(new_def)

        row = conn.execute(
            "SELECT definition_json, definition_hash FROM arpg_gathering_nodes WHERE node_ref=?",
            (new_def["node_ref"],),
        ).fetchone()
        stored = json.loads(row["definition_json"])
        self.assertEqual(stored["capacity_units"], 58)
        expected_text, expected_hash = core._payload(new_def)
        self.assertEqual(row["definition_hash"], expected_hash)
        self.assertEqual(len(contract.RECONCILIATION_LOG), 1)
        self.assertEqual(contract.RECONCILIATION_LOG[0]["persisted_capacity_units"], 86)
        self.assertEqual(contract.RECONCILIATION_LOG[0]["reconciled_capacity_units"], 58)

    def test_16_patched_insert_still_rejects_structural_drift(self) -> None:
        conn = _make_fixture_conn()
        core = FakeGatheringCore(conn, "rt:world:fixture0000000000000000000000")
        original_def = _base_def(source_ref="FAU-TEST-01")
        text, h = core._payload(original_def)
        conn.execute(
            "INSERT INTO arpg_gathering_nodes VALUES(?,?,?,?)",
            (original_def["node_ref"], core.world_instance_id, text, h),
        )
        contract.install(FakeGatheringCore)

        mutated_def = _base_def(source_ref="FAU-TEST-99")
        with self.assertRaises(RealIntegrityError) as ctx:
            core._insert_node(mutated_def)
        self.assertIn("gathering node drift", str(ctx.exception))
        row = conn.execute(
            "SELECT definition_json FROM arpg_gathering_nodes WHERE node_ref=?",
            (mutated_def["node_ref"],),
        ).fetchone()
        self.assertEqual(json.loads(row["definition_json"])["source_ref"], "FAU-TEST-01", "row must be unchanged after a rejected structural drift")


class SourceIntegrityTests(unittest.TestCase):
    """Static checks mirroring the recovery tool's own established style
    (STAGE17_TOOLS/tests/test_repair_stage17_player_position.py)."""

    def setUp(self) -> None:
        self.source = (BACKEND_DIR / "stage17_gathering_capacity_contract.py").read_text(encoding="utf-8")

    def test_17_never_edits_protected_file_on_disk(self) -> None:
        self.assertNotIn(".write(", self.source)
        self.assertNotIn("write_text", self.source)
        self.assertNotIn("open(", self.source, "module must never open any file -- monkeypatch only, no disk I/O")

    def test_18_no_sql_dml_outside_documented_update(self) -> None:
        import re

        execute_args = re.findall(r"\.execute\(\s*(\"\"\".*?\"\"\"|\"[^\"]*\"|'[^']*')", self.source, re.DOTALL)
        dml = re.compile(r"\b(INSERT|DELETE|DROP|ALTER)\b", re.IGNORECASE)
        offenders = [s for s in execute_args if dml.search(s)]
        self.assertEqual(offenders, [], f"contract module must only ever UPDATE arpg_gathering_nodes, never INSERT/DELETE/DROP/ALTER: {offenders}")

    def test_19_no_hardcoded_real_node_or_capacity_values(self) -> None:
        for banned in ("GTH-1D268772796B25C4CC6B", "FAU-BROWSER-05-04-01", "86", "58"):
            self.assertNotIn(banned, self.source, f"contract module must be fully generic, found: {banned}")


if __name__ == "__main__":
    unittest.main()
