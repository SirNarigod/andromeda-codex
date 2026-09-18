from __future__ import annotations

import copy
import json
import math
import pathlib
import shutil
import sqlite3
import sys
import tempfile
import unittest
from dataclasses import replace


BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from andromeda_authority_adapter import Stage16BAuthorityAdapter  # noqa: E402
from authority_config import load_config  # noqa: E402
from resource_metric_placement import (  # noqa: E402
    PLACEMENT_AUTHORITY,
    POSITION_AUTHORITY,
    SCHEMA_VERSION,
    ResourceMetricPlacementRegistry,
    ResourcePlacementError,
    canonical_manifest_hash,
    stable_placement_ref,
)


MANIFEST_PATH = (
    WORKSPACE_ROOT
    / "STAGE17_CONTENT"
    / "RESOURCE_PLACEMENT"
    / "CANONICAL"
    / "S17_RESOURCE_METRIC_PLACEMENTS_R0001.json"
)
SOURCE_DB = WORKSPACE_ROOT / "STAGE17_RUNTIME_STATE" / "authority" / "stage17_world.sqlite"


class Stage17ResourceMetricPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s17_resource_placement_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.db_path = cls.root / "world.sqlite"
        shutil.copy2(SOURCE_DB, cls.db_path)
        # The copied DEV world may already contain the production materialization.
        # Clearing only additive Stage17 tables in this disposable test copy lets
        # this suite prove first materialization without touching gameplay state.
        conn = sqlite3.connect(cls.db_path)
        try:
            for table in (
                "s17_resource_metric_constraints",
                "s17_resource_metric_placements",
                "s17_resource_placement_manifests",
            ):
                conn.execute(f"DELETE FROM {table}")
            conn.commit()
        finally:
            conn.close()
        base = load_config()
        cls.config = replace(
            base,
            db_path=cls.db_path,
            save_root=cls.root / "saves",
            owner_scope="stage17:playable-v0-dev",
            world_seed=160800,
            resource_placement_manifest_path=MANIFEST_PATH,
        )
        cls.adapter = Stage16BAuthorityAdapter(cls.config)
        cls.registry = cls.adapter.resource_placement_registry
        assert cls.registry is not None
        cls.manifest, cls.manifest_hash = cls.registry.load_manifest(MANIFEST_PATH)
        cls.placements = cls.registry.active_placements()
        cls.session = "S17-C1B-PLACEMENT"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def test_01_manifest_schema_valid(self) -> None:
        self.assertEqual(SCHEMA_VERSION, self.manifest["schema_version"])
        self.registry.validate_manifest(self.manifest, self.manifest_hash)

    def test_02_canonical_ordering(self) -> None:
        refs = [row["placement_ref"] for row in self.manifest["placements"]]
        constraint_refs = [row["constraint_ref"] for row in self.manifest["constraints"]]
        self.assertEqual(sorted(refs), refs)
        self.assertEqual(sorted(constraint_refs), constraint_refs)

    def test_03_deterministic_hash(self) -> None:
        self.assertEqual(self.manifest_hash, canonical_manifest_hash(self.manifest))

    def test_04_deterministic_physical_refs(self) -> None:
        for row in self.manifest["placements"]:
            self.assertEqual(
                row["placement_ref"],
                stable_placement_ref(
                    row["world_instance_id"],
                    row["logical_node_ref"],
                    row["authoring_source"]["object_ref"],
                    row["placement_revision"],
                    row["ordinal"],
                ),
            )

    def test_05_tree_placement_materialized(self) -> None:
        tree = next(row for row in self.placements if row["resource_kind"] == "TREE")
        self.assertTrue(tree["placement_ref"].startswith("RESOURCE-PLACEMENT-S17-"))
        self.assertEqual(POSITION_AUTHORITY, tree["position_authority"])

    def test_06_ore_placement_materialized(self) -> None:
        ore = next(row for row in self.placements if row["resource_kind"] == "ORE")
        self.assertTrue(ore["placement_ref"].startswith("RESOURCE-PLACEMENT-S17-"))
        self.assertEqual(POSITION_AUTHORITY, ore["position_authority"])

    def test_07_logical_gth_refs_are_real(self) -> None:
        gathering = self.adapter._engine.gathering_arpg(self.adapter.world_instance_id)
        for row in self.placements:
            self.assertEqual(row["logical_node_ref"], gathering.node(row["logical_node_ref"])["node_ref"])

    def test_08_gth_identity_not_regenerated(self) -> None:
        manifest_refs = {row["logical_node_ref"] for row in self.manifest["placements"]}
        stored_refs = {row["logical_node_ref"] for row in self.placements}
        self.assertEqual(manifest_refs, stored_refs)

    def test_09_first_materialization_inserted_exactly_two(self) -> None:
        report = self.adapter.resource_placement_materialization
        self.assertEqual("PASS", report["status"])
        self.assertEqual(2, report["inserted"])
        self.assertEqual(1, report["constraint_inserted"])

    def test_10_restart_persists_identity_position_and_revision(self) -> None:
        before = {
            row["placement_ref"]: (row["position"], row["placement_revision"])
            for row in self.placements
        }
        second = Stage16BAuthorityAdapter(self.config)
        try:
            registry = second.resource_placement_registry
            self.assertIsNotNone(registry)
            assert registry is not None
            after = {
                row["placement_ref"]: (row["position"], row["placement_revision"])
                for row in registry.active_placements()
            }
            self.assertEqual(before, after)
            self.assertTrue(second.resource_placement_materialization["idempotent"])
        finally:
            second.close()

    def test_11_same_manifest_replay_creates_no_duplicates(self) -> None:
        report = self.registry.materialize(self.manifest, self.manifest_hash)
        self.assertTrue(report["idempotent"])
        self.assertEqual(2, len(self.registry.active_placements()))

    def test_12_conflicting_same_revision_rejected(self) -> None:
        changed = copy.deepcopy(self.manifest)
        changed["placements"][0]["position"]["iso_x_m"] += 0.25
        with self.assertRaisesRegex(ResourcePlacementError, "REVISION_CONFLICT"):
            self.registry.materialize(changed, canonical_manifest_hash(changed))

    def test_13_world_mismatch_rejected(self) -> None:
        changed = copy.deepcopy(self.manifest)
        changed["world_binding"]["world_instance_id"] = "rt:world:other"
        with self.assertRaisesRegex(ResourcePlacementError, "WORLD_MISMATCH"):
            self.registry.validate_manifest(changed, canonical_manifest_hash(changed))

    def test_14_invalid_altitude_rejected(self) -> None:
        changed = copy.deepcopy(self.manifest)
        changed["placements"][0]["position"]["altitude_m"] = None
        with self.assertRaisesRegex(ResourcePlacementError, "INVALID_RESOURCE_PLACEMENT_POSITION"):
            self.registry.validate_manifest(changed, canonical_manifest_hash(changed))

    def test_15_nan_and_infinity_rejected(self) -> None:
        for invalid in (math.nan, math.inf, -math.inf):
            changed = copy.deepcopy(self.manifest)
            changed["placements"][0]["position"]["iso_y_m"] = invalid
            with self.assertRaisesRegex(ResourcePlacementError, "INVALID_RESOURCE_PLACEMENT_POSITION"):
                self.registry.validate_manifest(changed, canonical_manifest_hash(changed))

    def test_16_gameplay_client_cannot_set_or_move_placement(self) -> None:
        tree = next(row for row in self.placements if row["resource_kind"] == "TREE")
        out = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REQUEST_GATHER",
                "command_ref": "S17-C1B-FORGED-PLACEMENT-POSITION",
                "params": {
                    "placement_ref": tree["placement_ref"],
                    "target_ref": tree["logical_node_ref"],
                    "requested_units": 1,
                    "iso_x_m": tree["position"]["iso_x_m"],
                },
            }
        )
        self.assertEqual("UNEXPECTED_COMMAND_PARAM", out["reason"])

    def test_17_logical_gth_remains_depletion_authority(self) -> None:
        columns = {
            row[1]
            for row in self.adapter._engine.runtime.conn.execute(
                "PRAGMA table_info(s17_resource_metric_placements)"
            ).fetchall()
        }
        self.assertFalse({"remaining_units", "capacity_units", "depleted"} & columns)

    def test_18_many_physical_placements_per_gth_are_permitted(self) -> None:
        changed = copy.deepcopy(self.manifest)
        original = changed["placements"][0]
        extra = copy.deepcopy(original)
        extra["authoring_source"]["object_ref"] = "N_TO_ONE_CONTRACT_PROBE"
        extra["authoring_source"]["node_path"] += ":N_TO_ONE_PROBE"
        extra["ordinal"] = 7
        extra["placement_ref"] = stable_placement_ref(
            extra["world_instance_id"],
            extra["logical_node_ref"],
            extra["authoring_source"]["object_ref"],
            extra["placement_revision"],
            extra["ordinal"],
        )
        changed["placements"].append(extra)
        changed["placements"].sort(key=lambda row: row["placement_ref"])
        self.registry.validate_manifest(changed, canonical_manifest_hash(changed))
        self.assertEqual(2, sum(
            row["logical_node_ref"] == original["logical_node_ref"]
            for row in changed["placements"]
        ))

    def test_19_query_by_zone_and_block(self) -> None:
        binding = self.manifest["world_binding"]
        rows = self.registry.active_placements(
            zone_ref=binding["zone_ref"], block_ref=binding["block_ref"]
        )
        self.assertEqual(2, len(rows))

    def test_20_query_by_logical_gth(self) -> None:
        for row in self.placements:
            resolved = self.registry.placements_for_logical(row["logical_node_ref"])
            self.assertEqual([row["placement_ref"]], [entry["placement_ref"] for entry in resolved])

    def test_21_same_manifest_load_is_reproducible(self) -> None:
        again, again_hash = self.registry.load_manifest(MANIFEST_PATH)
        self.assertEqual(self.manifest, again)
        self.assertEqual(self.manifest_hash, again_hash)

    def test_22_source_provenance_retained(self) -> None:
        for row in self.placements:
            self.assertEqual(self.manifest_hash, row["source_manifest_hash"])
            self.assertIn(row["authoring_object_ref"], {"TREE_PRIMARY", "ORE_PRIMARY"})
            self.assertTrue(row["authoring_node_path"].startswith("WorldStreamRoot/"))

    def test_23_registry_metrics_report_no_duplicate_depletion(self) -> None:
        metrics = self.registry.metrics()
        self.assertEqual("PASS", metrics["status"])
        self.assertFalse(metrics["logical_gth_depletion_duplicated"])
        self.assertEqual(2, metrics["placement_count"])

    def test_24_position_authority_is_materialized_backend_not_godot(self) -> None:
        self.assertTrue(all(row["authority"] == PLACEMENT_AUTHORITY for row in self.placements))
        self.assertTrue(all(row["position_authority"] == POSITION_AUTHORITY for row in self.placements))
        self.assertNotIn("GODOT_LOCAL", json.dumps(self.placements, sort_keys=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
