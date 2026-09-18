from __future__ import annotations

import json
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
    GATHER_RANGE_M,
    PLACEMENT_AUTHORITY,
    POSITION_AUTHORITY,
)


MANIFEST_PATH = (
    WORKSPACE_ROOT
    / "STAGE17_CONTENT"
    / "RESOURCE_PLACEMENT"
    / "CANONICAL"
    / "S17_RESOURCE_METRIC_PLACEMENTS_R0001.json"
)
SOURCE_DB = WORKSPACE_ROOT / "STAGE17_RUNTIME_STATE" / "authority" / "stage17_world.sqlite"


class Stage17ResourceMetricGatherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s17_resource_metric_gather_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.db_path = cls.root / "world.sqlite"
        shutil.copy2(SOURCE_DB, cls.db_path)
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
        cls.session = "S17-C2-RESOURCE-METRIC"
        cls.assert_status(cls.adapter.bind_session(cls.session), "PASS")
        registry = cls.adapter.resource_placement_registry
        assert registry is not None
        cls.registry = registry
        cls.placements = {
            row["resource_kind"]: row for row in registry.active_placements()
        }

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    @staticmethod
    def assert_status(result: dict, expected: str) -> None:
        if result.get("status") != expected:
            raise AssertionError(result)

    def move_to_offset(
        self, kind: str, dx: float, dy: float, ref: str
    ) -> dict:
        position = self.placements[kind]["position"]
        result = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "MOVE_TO_POINT",
                "command_ref": ref,
                "params": {
                    "iso_x_m": float(position["iso_x_m"]) + dx,
                    "iso_y_m": float(position["iso_y_m"]) + dy,
                    "duration_s": 10.0,
                    "mode": "WALK",
                },
            }
        )
        self.assertEqual("PASS", result.get("status"), result)
        return result

    def gather(
        self,
        kind: str,
        ref: str,
        *,
        logical_ref: str | None = None,
        extra: dict | None = None,
    ) -> dict:
        placement = self.placements[kind]
        params = {
            "placement_ref": placement["placement_ref"],
            "target_ref": logical_ref or placement["logical_node_ref"],
            "requested_units": 1,
        }
        params.update(extra or {})
        return self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REQUEST_GATHER",
                "command_ref": ref,
                "params": params,
            }
        )

    def remaining(self, kind: str) -> int:
        logical_ref = self.placements[kind]["logical_node_ref"]
        gathering = self.adapter._engine.gathering_arpg(self.adapter.world_instance_id)
        return int(gathering.node(logical_ref)["remaining_units"])

    def drop_count(self) -> int:
        return len(
            self.adapter._engine.stage16a(self.adapter.world_instance_id)
            .ground_loot.active_drops()
        )

    def test_01_snapshot_projects_only_active_metric_tree_and_ore(self) -> None:
        snapshot = self.adapter.snapshot(self.session)
        resources = snapshot["resources"]
        self.assertEqual({"TREE", "ORE"}, {row["resource_kind"] for row in resources})
        self.assertEqual(2, len(resources))
        self.assertTrue(all(row["server_authoritative"] for row in resources))

    def test_02_projection_preserves_physical_and_logical_identity(self) -> None:
        resources = self.adapter.snapshot(self.session)["resources"]
        for row in resources:
            self.assertEqual(row["target_ref"], row["placement_ref"])
            self.assertTrue(row["placement_ref"].startswith("RESOURCE-PLACEMENT-S17-"))
            self.assertTrue(row["logical_node_ref"].startswith("GTH-"))
            self.assertNotEqual(row["placement_ref"], row["logical_node_ref"])

    def test_03_projection_contract_is_metric_and_world_bound(self) -> None:
        snapshot = self.adapter.snapshot(self.session)
        world = snapshot["identity"]["world_instance_id"]
        for row in snapshot["resources"]:
            self.assertEqual("RESOURCE", row["target_kind"])
            self.assertEqual(world, row["world_instance_id"])
            self.assertEqual(POSITION_AUTHORITY, row["position_authority"])
            self.assertEqual(PLACEMENT_AUTHORITY, row["authority"])
            self.assertEqual(GATHER_RANGE_M, row["gather_range_m"])
            self.assertNotIn("GODOT_LOCAL_PLACEHOLDER_ONLY", json.dumps(row))

    def test_04_exact_1_5_m_boundary_passes_server_side(self) -> None:
        self.move_to_offset("ORE", GATHER_RANGE_M, 0.0, "S17-C2-MOVE-BOUNDARY")
        result = self.gather("ORE", "S17-C2-GATHER-BOUNDARY")
        self.assertEqual("PASS", result["status"], result)
        guard = result["metric_spatial_guard"]
        self.assertAlmostEqual(GATHER_RANGE_M, guard["distance_m"], places=9)
        self.assertTrue(guard["los"]["clear"])

    def test_05_above_1_5_m_rejects_without_mutation(self) -> None:
        self.move_to_offset("ORE", 1.5001, 0.0, "S17-C2-MOVE-OUTSIDE")
        before_remaining = self.remaining("ORE")
        before_drops = self.drop_count()
        result = self.gather("ORE", "S17-C2-GATHER-OUTSIDE")
        self.assertEqual("RESOURCE_GATHER_OUT_OF_RANGE", result["reason"])
        self.assertFalse(result["mutation_applied"])
        self.assertEqual(before_remaining, self.remaining("ORE"))
        self.assertEqual(before_drops, self.drop_count())

    def test_06_authoritative_aabb_blocks_tree_los_without_mutation(self) -> None:
        # The baked blocker lies immediately west of TREE.  This position is
        # 1.4m from the resource, but its segment crosses that authoritative AABB.
        self.move_to_offset("TREE", -1.4, 0.0, "S17-C2-MOVE-BLOCKED")
        before_remaining = self.remaining("TREE")
        before_drops = self.drop_count()
        result = self.gather("TREE", "S17-C2-GATHER-BLOCKED")
        self.assertEqual("RESOURCE_GATHER_BLOCKED_LOS", result["reason"])
        self.assertFalse(result["mutation_applied"])
        self.assertEqual(PLACEMENT_AUTHORITY, result["blocker_authority"])
        self.assertEqual(["RESOURCE-LOS-BLOCKER-S17-001"], result["blocked_by"])
        self.assertEqual(before_remaining, self.remaining("TREE"))
        self.assertEqual(before_drops, self.drop_count())

    def test_07_tree_clear_side_gather_delegates_to_protected_core(self) -> None:
        self.move_to_offset("TREE", 1.0, 0.0, "S17-C2-MOVE-TREE-CLEAR")
        before = self.remaining("TREE")
        result = self.gather("TREE", "S17-C2-GATHER-TREE-CLEAR")
        self.assertEqual("PASS", result["status"], result)
        self.assertTrue(result["metric_spatial_guard"]["los"]["clear"])
        self.assertEqual(POSITION_AUTHORITY, result["metric_spatial_guard"]["resource_position_authority"])
        self.assertEqual(before - 1, self.remaining("TREE"))
        self.assertEqual("TREE", result["physical_output"]["source_kind"])

    def test_08_ore_clear_side_gather_delegates_to_protected_core(self) -> None:
        self.move_to_offset("ORE", 1.0, 0.0, "S17-C2-MOVE-ORE-CLEAR")
        before = self.remaining("ORE")
        result = self.gather("ORE", "S17-C2-GATHER-ORE-CLEAR")
        self.assertEqual("PASS", result["status"], result)
        self.assertTrue(result["metric_spatial_guard"]["los"]["clear"])
        self.assertEqual(before - 1, self.remaining("ORE"))
        self.assertEqual("ORE", result["physical_output"]["source_kind"])

    def test_09_wrong_placement_gth_pair_rejected_without_mutation(self) -> None:
        self.move_to_offset("TREE", 1.0, 0.0, "S17-C2-MOVE-WRONG-PAIR")
        before = self.remaining("TREE")
        before_drops = self.drop_count()
        result = self.gather(
            "TREE",
            "S17-C2-GATHER-WRONG-PAIR",
            logical_ref=self.placements["ORE"]["logical_node_ref"],
        )
        self.assertEqual("RESOURCE_PLACEMENT_LOGICAL_REF_MISMATCH", result["reason"])
        self.assertEqual(before, self.remaining("TREE"))
        self.assertEqual(before_drops, self.drop_count())

    def test_10_client_position_distance_and_los_injection_rejected(self) -> None:
        for index, field in enumerate(
            ("iso_x_m", "iso_y_m", "distance", "range", "position", "blocked", "los_clear")
        ):
            result = self.gather(
                "ORE",
                f"S17-C2-GATHER-INJECTION-{index}",
                extra={field: 0},
            )
            self.assertEqual("UNEXPECTED_COMMAND_PARAM", result["reason"], (field, result))

    def test_11_missing_placement_has_no_production_legacy_bypass(self) -> None:
        placement = self.placements["TREE"]
        result = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REQUEST_GATHER",
                "command_ref": "S17-C2-GATHER-MISSING-PLACEMENT",
                "params": {
                    "target_ref": placement["logical_node_ref"],
                    "requested_units": 1,
                },
            }
        )
        self.assertEqual("RESOURCE_PLACEMENT_REF_REQUIRED", result["reason"])

    def test_12_unknown_or_other_world_placement_is_rejected(self) -> None:
        result = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REQUEST_GATHER",
                "command_ref": "S17-C2-GATHER-OTHER-WORLD",
                "params": {
                    "placement_ref": "RESOURCE-PLACEMENT-S17-OTHERWORLD00000",
                    "target_ref": self.placements["TREE"]["logical_node_ref"],
                    "requested_units": 1,
                },
            }
        )
        self.assertEqual("RESOURCE_PLACEMENT_NOT_FOUND", result["reason"])

    def test_13_duplicate_command_replays_without_second_depletion(self) -> None:
        self.move_to_offset("ORE", 1.0, 0.0, "S17-C2-MOVE-REPLAY")
        ref = "S17-C2-GATHER-REPLAY"
        before = self.remaining("ORE")
        first = self.gather("ORE", ref)
        middle = self.remaining("ORE")
        second = self.gather("ORE", ref)
        after = self.remaining("ORE")
        self.assertEqual("PASS", first["status"], first)
        self.assertTrue(second["idempotent_replay"])
        self.assertTrue(second["replay_suppressed"])
        self.assertEqual(before - 1, middle)
        self.assertEqual(middle, after)

    def test_14_depletion_is_only_on_logical_gth(self) -> None:
        placement_columns = {
            row[1]
            for row in self.adapter._engine.runtime.conn.execute(
                "PRAGMA table_info(s17_resource_metric_placements)"
            ).fetchall()
        }
        self.assertFalse({"remaining_units", "depleted", "capacity_units"} & placement_columns)
        for placement in self.placements.values():
            self.assertGreaterEqual(self.remaining(placement["resource_kind"]), 0)

    def test_15_blocker_and_los_are_resolved_without_client_geometry(self) -> None:
        constraints = self.adapter._engine.runtime.conn.execute(
            "SELECT * FROM s17_resource_metric_constraints "
            "WHERE world_instance_id=? AND active=1 AND blocks_los=1",
            (self.adapter.world_instance_id,),
        ).fetchall()
        self.assertEqual(1, len(constraints))
        self.assertEqual("AXIS_ALIGNED_SOLID_BLOCKER", constraints[0]["constraint_kind"])
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["canonical_manifest"]
        self.assertFalse(manifest["constraints"][0]["authoring_source"]["runtime_authority"])

    def test_16_restart_preserves_placements_and_projection_without_duplicates(self) -> None:
        before = {
            row["placement_ref"]: (row["position"], row["logical_node_ref"], row["placement_revision"])
            for row in self.registry.active_placements()
        }
        resumed = Stage16BAuthorityAdapter(self.config)
        try:
            self.assertEqual("RESUMED", resumed.bootstrap_mode)
            registry = resumed.resource_placement_registry
            assert registry is not None
            after = {
                row["placement_ref"]: (row["position"], row["logical_node_ref"], row["placement_revision"])
                for row in registry.active_placements()
            }
            self.assertEqual(before, after)
            self.assertEqual(2, len(after))
            self.assertTrue(resumed.resource_placement_materialization["idempotent"])
        finally:
            resumed.close()

    def test_17_snapshot_payload_is_finite_json_and_small_active_subset(self) -> None:
        snapshot = self.adapter.snapshot(self.session)
        payload = json.dumps(snapshot["resources"], allow_nan=False, sort_keys=True)
        self.assertEqual(2, len(snapshot["resources"]))
        self.assertLess(len(payload.encode("utf-8")), 8_192)

    def test_18_metric_guard_never_accepts_client_position(self) -> None:
        self.move_to_offset("TREE", 1.0, 0.0, "S17-C2-MOVE-GUARD")
        result = self.gather("TREE", "S17-C2-GATHER-GUARD")
        self.assertEqual("PASS", result["status"], result)
        guard = result["metric_spatial_guard"]
        self.assertFalse(guard["client_position_accepted"])
        self.assertEqual("PASS_WHEN_DISTANCE_LESS_THAN_OR_EQUAL_TO_1_5_M", guard["range_boundary_policy"])
        self.assertTrue(guard["server_authoritative"])

    def test_19_hunting_and_fishing_are_not_misclassified_as_static_placements(self) -> None:
        gathering = self.adapter._engine.gathering_arpg(self.adapter.world_instance_id)
        zone_ref = self.adapter._engine.world_arpg(self.adapter.world_instance_id).profile_state(
            self.adapter.profile_ref
        )["zone_ref"]
        for activity in ("HUNTING", "FISHING"):
            node = next(
                row
                for row in gathering.list_nodes(activity_type=activity, zone_ref=zone_ref)
                if activity != "HUNTING" or (row.get("source_meta") or {}).get("role") != "PREDATOR"
            )
            result = self.adapter.command(
                {
                    "session_ref": self.session,
                    "command": "REQUEST_GATHER",
                    "command_ref": f"S17-C2-{activity}-LOGICAL-ACTIVITY",
                    "params": {"target_ref": node["node_ref"], "requested_units": 1},
                }
            )
            self.assertEqual("PASS", result["status"], result)
            self.assertIsNone(result["placement_ref"])
            self.assertIsNone(result["metric_spatial_guard"])
            self.assertEqual(activity, result["activity_type"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
