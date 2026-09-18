from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
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
        owner_scope="stage16b:ground-loot-authority-test",
        world_seed=160824,
        player_class="WARRIOR",
        development_profile_bootstrap=True,
    )


class Stage16BAuthorityGroundLootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_loot_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.config = build_config(cls.root)
        cls.adapter = Stage16BAuthorityAdapter(cls.config)
        cls.session = "S16B-GROUND-LOOT"
        cls.bind = cls.adapter.bind_session(cls.session)
        cls.stage16a = cls.adapter._engine.stage16a(cls.adapter.world_instance_id)
        cls.items = cls.adapter._engine.items_arpg(cls.adapter.world_instance_id)
        cls.movement = cls.adapter._engine.movement(cls.adapter.world_instance_id)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, target_ref: str, ref: str, params: dict | None = None) -> dict:
        return self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REQUEST_PICKUP",
                "command_ref": ref,
                "params": {"target_ref": target_ref} if params is None else params,
            }
        )

    def spawn(self, name: str, distance_m: float, *, settled: bool, reachable: bool = True) -> str:
        state = self.movement.state(self.adapter._player_ref)
        pos = {
            "iso_x_m": float(state["iso_x_m"]) + float(distance_m),
            "iso_y_m": float(state["iso_y_m"]),
            "altitude_m": float(state.get("altitude_m", 0.0)),
        }
        out = self.stage16a.ground_loot.spawn_drop(
            source_ref="S16B-AUTHORITY-PROBE",
            source_kind="PLAYER_DROP",
            item_ref="ITEM-GRAIN",
            item_kind="MATERIAL",
            quantity=1,
            candidate_position=pos,
            event_ref=f"S16B:AUTHORITY:LOOT:{name}:SPAWN",
        )
        self.assertEqual("PASS", out["status"])
        drop_ref = out["drop_ref"]
        if settled:
            settled_out = self.stage16a.confirm_drop_settled(
                drop_ref,
                settled_position=pos,
                reachable=reachable,
                event_ref=f"S16B:AUTHORITY:LOOT:{name}:SETTLE",
            )
            self.assertEqual("PASS", settled_out["status"])
        return drop_ref

    def test_01_session_controls_the_profile_avatar(self) -> None:
        self.assertEqual(self.adapter.avatar_ref, self.adapter._player_ref)
        self.assertEqual(self.adapter.avatar_ref, self.bind["player_ref"])

    def test_02_snapshot_projects_real_active_ground_loot(self) -> None:
        ref = self.spawn("SNAPSHOT", 0.25, settled=True)
        entries = self.adapter.snapshot(self.session)["ground_loot"]
        projected = next(row for row in entries if row["target_ref"] == ref)
        self.assertEqual(ref, projected["drop_ref"])
        self.assertTrue(projected["settled"])
        self.assertTrue(projected["physical_world_first"])
        self.assertFalse(projected["direct_to_inventory"])

    def test_03_client_cannot_supply_pickup_distance_or_reachability(self) -> None:
        ref = self.spawn("FORGED-DISTANCE", 0.75, settled=True)
        out = self.command(
            ref,
            "S16B-LOOT-FORGED-DISTANCE",
            {"target_ref": ref, "physical_distance_m": 0.0, "reachable_now": True},
        )
        self.assertEqual("REJECTED", out["status"])
        self.assertEqual("UNEXPECTED_COMMAND_PARAM", out["reason"])
        self.assertEqual("ACTIVE", self.stage16a.ground_loot.drop(ref)["state"])

    def test_04_unsettled_drop_is_rejected_by_core(self) -> None:
        ref = self.spawn("UNSETTLED", 0.1, settled=False)
        out = self.command(ref, "S16B-LOOT-UNSETTLED")
        self.assertEqual("REJECTED", out["status"])
        self.assertEqual("DROP_NOT_SETTLED", out["reason"])
        self.assertTrue(out["distance_evaluated_server_side"])

    def test_05_distance_0_5001_is_rejected_from_server_positions(self) -> None:
        ref = self.spawn("FAR", 0.5001, settled=True)
        out = self.command(ref, "S16B-LOOT-FAR")
        self.assertEqual("REJECTED", out["status"])
        self.assertEqual("PICKUP_DISTANCE_EXCEEDED", out["reason"])
        self.assertGreater(out["physical_distance_m"], 0.5)
        self.assertEqual("ACTIVE", self.stage16a.ground_loot.drop(ref)["state"])

    def test_06_exactly_0_5_is_collected_by_stage16a(self) -> None:
        ref = self.spawn("EXACT", 0.5, settled=True)
        before = self.items.inventory_snapshot(self.adapter.profile_ref)["stacks"].get("ITEM-GRAIN", 0)
        out = self.command(ref, "S16B-LOOT-EXACT")
        after = self.items.inventory_snapshot(self.adapter.profile_ref)["stacks"].get("ITEM-GRAIN", 0)
        self.assertEqual("PASS", out["status"])
        self.assertAlmostEqual(0.5, out["physical_distance_m"], places=6)
        self.assertEqual(before + 1, after)
        self.assertEqual("COLLECTED", self.stage16a.ground_loot.drop(ref)["state"])
        self.assertTrue(out["server_authoritative"])

    def test_07_unreachable_drop_is_rejected(self) -> None:
        ref = self.spawn("UNREACHABLE", 0.1, settled=True, reachable=False)
        out = self.command(ref, "S16B-LOOT-UNREACHABLE")
        self.assertEqual("REJECTED", out["status"])
        self.assertEqual("GROUND_LOOT_UNREACHABLE", out["reason"])
        self.assertEqual("ACTIVE", self.stage16a.ground_loot.drop(ref)["state"])

    def test_08_duplicate_command_does_not_grant_twice(self) -> None:
        ref = self.spawn("REPLAY", 0.2, settled=True)
        envelope = {
            "session_ref": self.session,
            "command": "REQUEST_PICKUP",
            "command_ref": "S16B-LOOT-REPLAY",
            "params": {"target_ref": ref},
        }
        before = self.items.inventory_snapshot(self.adapter.profile_ref)["stacks"].get("ITEM-GRAIN", 0)
        first = self.adapter.command(envelope)
        middle = self.items.inventory_snapshot(self.adapter.profile_ref)["stacks"].get("ITEM-GRAIN", 0)
        second = self.adapter.command(envelope)
        after = self.items.inventory_snapshot(self.adapter.profile_ref)["stacks"].get("ITEM-GRAIN", 0)
        self.assertEqual("PASS", first["status"])
        self.assertEqual(before + 1, middle)
        self.assertEqual(middle, after)
        self.assertTrue(second["idempotent_replay"])
        self.assertTrue(second["replay_suppressed"])
        self.assertEqual(first["result_sequence"], second["result_sequence"])

    def test_09_missing_target_is_rejected_without_grant(self) -> None:
        before = self.items.inventory_snapshot(self.adapter.profile_ref)["stacks"].get("ITEM-GRAIN", 0)
        out = self.command("DROP-DOES-NOT-EXIST", "S16B-LOOT-MISSING")
        after = self.items.inventory_snapshot(self.adapter.profile_ref)["stacks"].get("ITEM-GRAIN", 0)
        self.assertEqual("REJECTED", out["status"])
        self.assertEqual("GROUND_LOOT_NOT_FOUND", out["reason"])
        self.assertEqual(before, after)

    def test_10_collected_drop_leaves_active_snapshot_and_active_drop_remains(self) -> None:
        ref = self.spawn("ACTIVE-REMAINS", 0.3, settled=True)
        collected = self.spawn("SNAPSHOT-COLLECTED", 0.2, settled=True)
        self.assertEqual("PASS", self.command(collected, "S16B-LOOT-SNAPSHOT-COLLECTED")["status"])
        refs = {row["target_ref"] for row in self.adapter.snapshot(self.session)["ground_loot"]}
        self.assertIn(ref, refs)
        self.assertNotIn(collected, refs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
