from __future__ import annotations

import pathlib
import tempfile
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
import sys

sys.path.insert(0, str(BACKEND_DIR))

from andromeda_authority_adapter import Stage16BAuthorityAdapter  # noqa: E402
from authority_config import AuthorityConfig, _resolve_master_path, verify_master  # noqa: E402


def build_config(root: pathlib.Path) -> AuthorityConfig:
    master = _resolve_master_path()
    return AuthorityConfig(
        master_release_path=master,
        master_release_sha256=verify_master(master),
        runtime_dir=PROJECT_ROOT / "01_RUNTIME",
        db_path=root / "world.sqlite",
        save_root=root / "saves",
        owner_scope="stage16b:gathering-authority-test",
        world_seed=160800,
        player_class="WARRIOR",
        development_profile_bootstrap=True,
    )


class Stage16BAuthorityGatheringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_gathering_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session = "S16B-GATHERING"
        cls.adapter.bind_session(cls.session)
        cls.snapshot = cls.adapter.snapshot(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, target_ref: str, ref: str, **extra: object) -> dict:
        return self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REQUEST_GATHER",
                "command_ref": ref,
                "params": {"target_ref": target_ref, "requested_units": 1, **extra},
            }
        )

    def resource(self, kind: str) -> dict:
        return next(row for row in self.snapshot["resources"] if row["resource_kind"] == kind)

    def gather_until_output(self, node_ref: str, prefix: str) -> dict:
        for attempt in range(12):
            out = self.command(node_ref, f"{prefix}-{attempt:02d}")
            if out.get("drop_ref"):
                return out
        self.fail(f"authoritative {prefix} produced no physical output in 12 attempts")

    def test_01_snapshot_projects_real_current_zone_resource_nodes(self) -> None:
        self.assertTrue(self.snapshot["server_authoritative"])
        self.assertEqual(
            {"TREE", "ROCK", "ORE", "FLORA", "AGRICULTURE"},
            {row["resource_kind"] for row in self.snapshot["resources"]},
        )
        self.assertTrue(all(row["target_ref"].startswith("GTH-") for row in self.snapshot["resources"]))
        self.assertTrue(all(row["position_authority"] == "GODOT_LOCAL_PLACEHOLDER_ONLY" for row in self.snapshot["resources"]))

    def test_02_development_profile_uses_existing_role_and_item_authorities(self) -> None:
        bootstrap = self.adapter.development_profile_bootstrap
        self.assertEqual(
            {"MINING", "LOGGING", "FORAGING", "AGRICULTURE", "HUNTING", "FISHING"},
            set(bootstrap["assigned_gathering_roles"]),
        )
        worker = self.adapter._engine.gathering_arpg(self.adapter.world_instance_id).worker(
            self.adapter.profile_ref
        )
        self.assertEqual(set(bootstrap["assigned_gathering_roles"]), set(worker["roles"]))

    def test_03_client_cannot_supply_yield_tool_location_or_inventory_result(self) -> None:
        target = self.resource("TREE")["target_ref"]
        for index, field in enumerate(
            ("yield", "quantity", "tool_instance_ref", "physical_distance_m", "inventory_grant")
        ):
            out = self.command(target, f"S16B-GATHER-FORGED-{index}", **{field: 999})
            expected = (
                "CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN"
                if field == "inventory_grant"
                else "UNEXPECTED_COMMAND_PARAM"
            )
            self.assertEqual(expected, out["reason"])

    def test_04_tree_gather_is_real_ground_loot_and_not_inventory(self) -> None:
        target = self.resource("TREE")["target_ref"]
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        before = items.inventory_snapshot(self.adapter.profile_ref)
        out = self.command(target, "S16B-GATHER-TREE")
        after = items.inventory_snapshot(self.adapter.profile_ref)
        self.assertEqual("PASS", out["status"])
        self.assertEqual("TREE", out["physical_output"]["source_kind"])
        self.assertFalse(out["direct_to_inventory"])
        self.assertTrue(out["physical_output"]["physical_world_first"])
        self.assertFalse(out["physical_output"]["settled"])
        self.assertEqual(before["stacks"], after["stacks"])

    def test_05_duplicate_gather_replays_without_second_source_consumption(self) -> None:
        target = self.resource("FLORA")["target_ref"]
        node_before = self.adapter._engine.gathering_arpg(self.adapter.world_instance_id).node(target)
        first = self.command(target, "S16B-GATHER-REPLAY")
        node_middle = self.adapter._engine.gathering_arpg(self.adapter.world_instance_id).node(target)
        second = self.command(target, "S16B-GATHER-REPLAY")
        node_after = self.adapter._engine.gathering_arpg(self.adapter.world_instance_id).node(target)
        self.assertEqual("PASS", first["status"])
        self.assertTrue(second["idempotent_replay"])
        self.assertTrue(second["replay_suppressed"])
        self.assertEqual(node_before["remaining_units"] - 1, node_middle["remaining_units"])
        self.assertEqual(node_middle["remaining_units"], node_after["remaining_units"])

    def test_06_all_static_resource_kinds_delegate_to_stage16a(self) -> None:
        expected_output_sources = {
            "TREE": "TREE",
            "ROCK": "ORE",  # protected Stage16A maps all MINING output to ORE
            "ORE": "ORE",
            "FLORA": "FLORA",
            "AGRICULTURE": "AGRICULTURE",
        }
        for index, (kind, output_source) in enumerate(expected_output_sources.items()):
            out = self.command(self.resource(kind)["target_ref"], f"S16B-GATHER-STATIC-{index}")
            self.assertEqual("PASS", out["status"], (kind, out))
            self.assertEqual(kind, out["resource_kind"])
            self.assertEqual(output_source, out["physical_output"]["source_kind"])
            self.assertTrue(out["yield_evaluated_server_side"])
            self.assertTrue(out["tool_evaluated_server_side"])

    def test_07_hunting_and_fishing_use_the_same_physical_delivery_channel(self) -> None:
        gathering = self.adapter._engine.gathering_arpg(self.adapter.world_instance_id)
        zone = self.adapter._engine.world_arpg(self.adapter.world_instance_id).profile_state(
            self.adapter.profile_ref
        )["zone_ref"]
        hunting = next(
            row
            for row in gathering.list_nodes(activity_type="HUNTING", zone_ref=zone)
            if (row.get("source_meta") or {}).get("role") != "PREDATOR"
        )
        fishing = gathering.list_nodes(activity_type="FISHING", zone_ref=zone)[0]
        hunt_out = self.gather_until_output(hunting["node_ref"], "S16B-GATHER-HUNT")
        fish_out = self.gather_until_output(fishing["node_ref"], "S16B-GATHER-FISH")
        self.assertEqual("HUNTING", hunt_out["physical_output"]["source_kind"])
        self.assertEqual("FISHING", fish_out["physical_output"]["source_kind"])
        self.assertFalse(hunt_out["direct_to_inventory"])
        self.assertFalse(fish_out["direct_to_inventory"])

    def test_08_settle_observation_becomes_authoritative_only_through_stage16a(self) -> None:
        out = self.command(self.resource("AGRICULTURE")["target_ref"], "S16B-GATHER-SETTLE")
        drop = out["physical_output"]
        position = dict(drop["candidate_position"])
        settled = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "CONFIRM_DROP_SETTLED",
                "command_ref": "S16B-GATHER-SETTLE-CONFIRM",
                "params": {
                    "target_ref": drop["drop_ref"],
                    "settled_position": position,
                    "reachable": True,
                },
            }
        )
        persisted = self.adapter._engine.stage16a(self.adapter.world_instance_id).ground_loot.drop(
            drop["drop_ref"]
        )
        self.assertEqual("PASS", settled["status"])
        self.assertTrue(persisted["settled"])
        self.assertTrue(persisted["reachable"])
        self.assertEqual(position, persisted["settled_position"])

    def test_09_settle_rejects_forged_authoritative_fields(self) -> None:
        out = self.command(self.resource("TREE")["target_ref"], "S16B-GATHER-SETTLE-FORGED-DROP")
        drop = out["physical_output"]
        rejected = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "CONFIRM_DROP_SETTLED",
                "command_ref": "S16B-GATHER-SETTLE-FORGED",
                "params": {
                    "target_ref": drop["drop_ref"],
                    "settled_position": drop["candidate_position"],
                    "reachable": True,
                    "inventory_grant": True,
                },
            }
        )
        self.assertEqual("CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN", rejected["reason"])

    def test_10_snapshot_contains_new_unsettled_outputs_without_local_grant(self) -> None:
        snapshot = self.adapter.snapshot(self.session)
        drops = snapshot["ground_loot"]
        self.assertGreaterEqual(len(drops), 8)
        self.assertTrue(all(row["direct_to_inventory"] is False for row in drops))
        self.assertTrue(all(row["target_ref"] == row["drop_ref"] for row in drops))


class Stage16BGatheringRestartContinuityTests(unittest.TestCase):
    def test_11_hunting_depletion_survives_real_engine_restart(self) -> None:
        with tempfile.TemporaryDirectory(prefix="s16b_gathering_restart_") as raw_root:
            root = pathlib.Path(raw_root)
            config = build_config(root)
            first = Stage16BAuthorityAdapter(config)
            try:
                session = "S16B-GATHERING-RESTART"
                first.bind_session(session)
                gathering = first._engine.gathering_arpg(first.world_instance_id)
                zone_ref = first._engine.world_arpg(first.world_instance_id).profile_state(
                    first.profile_ref
                )["zone_ref"]
                hunting = next(
                    row
                    for row in gathering.list_nodes(activity_type="HUNTING", zone_ref=zone_ref)
                    if (row.get("source_meta") or {}).get("role") != "PREDATOR"
                )
                before = gathering.node(hunting["node_ref"])["remaining_units"]
                result = None
                for attempt in range(16):
                    result = first.command(
                        {
                            "session_ref": session,
                            "command": "REQUEST_GATHER",
                            "command_ref": f"S16B-GATHER-RESTART-HUNT-{attempt:02d}",
                            "params": {"target_ref": hunting["node_ref"], "requested_units": 1},
                        }
                    )
                    if int((result.get("work_result") or {}).get("resource_consumed", 0)) > 0:
                        break
                after_gather = gathering.node(hunting["node_ref"])["remaining_units"]
                world_instance_id = first.world_instance_id
            finally:
                first.close()

            self.assertIsNotNone(result)
            self.assertEqual("PASS", result["status"])
            self.assertGreater(
                int((result.get("work_result") or {}).get("resource_consumed", 0)), 0
            )
            self.assertEqual(before - 1, after_gather)

            resumed = Stage16BAuthorityAdapter(config)
            try:
                self.assertEqual("RESUMED", resumed.bootstrap_mode)
                self.assertEqual(world_instance_id, resumed.world_instance_id)
                after_restart = resumed._engine.gathering_arpg(
                    resumed.world_instance_id
                ).node(hunting["node_ref"])["remaining_units"]
                self.assertEqual(after_gather, after_restart)
                compatibility = resumed.gathering_resume_compatibility
                self.assertEqual("APPLIED", compatibility["status"])
                self.assertFalse(compatibility["protected_core_modified_on_disk"])
                self.assertFalse(compatibility["country_progress_reset"])
                adjusted = next(
                    row
                    for row in compatibility["adjustments"]
                    if row["node_ref"] == hunting["node_ref"]
                )
                self.assertGreater(
                    adjusted["persisted_capacity_units"],
                    adjusted["authoritative_remaining_count"],
                )
            finally:
                resumed.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
