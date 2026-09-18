"""G16B-27: ADVANCE_DEVELOPMENT_WATER_TIME transport.

ADVANCE_DEVELOPMENT_WATER_TIME (andromeda_authority_adapter.py::
_advance_development_water_time()) is a thin, development-only transport
wrapper around the exact same stage16a.advance_water_time() the production
real-time path (_advance_authoritative_water_clock(), called from every
snapshot()) already calls. It exists solely so the 900s ground-loot / 1800s
dropped-bag water TTL thresholds can be proven deterministically without
waiting real wall-clock minutes -- it does not create a second clock, does
not duplicate the SUNK rule, and cannot mutate anything unless this world was
booted with development_profile_bootstrap=True.

These tests exercise the COMMAND itself (transport validation, the
development-profile guard, replay/idempotency, and the 899/900, 1799/1800,
land-bag-no-TTL clauses driven through the command instead of direct core
access) -- proving there is now a real, Godot-reachable route to the exact
same authoritative SUNK transitions
tests/test_stage16b_authority_save_death_water.py already proved via direct
core calls (test_09/test_10/test_11), which remain untouched and still pass.
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys
import tempfile
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "01_RUNTIME"))

from andromeda_authority_adapter import Stage16BAuthorityAdapter  # noqa: E402
from authority_config import AuthorityConfig, _resolve_master_path, verify_master  # noqa: E402

COMMAND = "ADVANCE_DEVELOPMENT_WATER_TIME"


def build_config(root: pathlib.Path) -> AuthorityConfig:
    master = _resolve_master_path()
    return AuthorityConfig(
        master_release_path=master,
        master_release_sha256=verify_master(master),
        runtime_dir=PROJECT_ROOT / "01_RUNTIME",
        db_path=root / "world.sqlite",
        save_root=root / "saves",
        owner_scope="stage16b:dev-water-time-test",
        world_seed=160831,
        player_class="WARRIOR",
        development_profile_bootstrap=True,
    )


class Stage16BDevWaterTimeGuardTests(unittest.TestCase):
    """D: development profile OFF -> REJECTED, zero mutation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_devwater_guard_")
        cls.root = pathlib.Path(cls._tmp.name)
        cfg = dataclasses.replace(build_config(cls.root), development_profile_bootstrap=False)
        cls.adapter = Stage16BAuthorityAdapter(cfg)
        cls.session = "S16B-DEVWATER-GUARD"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {"session_ref": self.session, "command": COMMAND, "command_ref": ref, "params": params}
        )

    def test_01_disabled_outside_development_profile_zero_mutation(self) -> None:
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        position = self.adapter._engine.movement(self.adapter.world_instance_id).state(
            self.adapter._player_ref
        )
        spawned = stage16a.ground_loot.spawn_drop(
            source_ref="B27-GUARD-SOURCE",
            source_kind="PLAYER_DROP",
            item_ref="ITEM-FOOD",
            item_kind="CONSUMABLE",
            quantity=1,
            candidate_position=position,
            event_ref="B27-GUARD-SPAWN",
        )
        drop_ref = spawned["drop_ref"]
        stage16a.confirm_drop_settled(
            drop_ref, settled_position=position, reachable=True, event_ref="B27-GUARD-SETTLE"
        )
        marked = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REPORT_GROUND_LOOT_WATER_STATE",
                "command_ref": "B27-GUARD-MARK",
                "params": {
                    "request_ref": "B27-GUARD-MARK:UI", "target_ref": drop_ref, "drop_ref": drop_ref,
                    "in_water": True, "flow_speed_mps": 0.2, "client_presentation_only": True,
                },
            }
        )
        self.assertEqual("PASS", marked["status"])
        before = stage16a.ground_loot.drop(drop_ref)["water_exposure_s"]

        result = self.command("B27-GUARD-ADVANCE", {"delta_s": 900.0})
        # DEV_WATER_TIME_COMMAND_DISABLED_OUTSIDE_DEVELOPMENT_PROFILE
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual(
            "DEV_WATER_TIME_COMMAND_DISABLED_OUTSIDE_DEVELOPMENT_PROFILE", result["reason"]
        )
        after = stage16a.ground_loot.drop(drop_ref)["water_exposure_s"]
        self.assertEqual(before, after, "zero mutation on rejection")
        self.assertEqual("ACTIVE", stage16a.ground_loot.drop(drop_ref)["state"])


class Stage16BDevWaterTimeTransportTests(unittest.TestCase):
    """A/B/C: transport-shape validation. L: server_authoritative. K: no side effects."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_devwater_transport_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session = "S16B-DEVWATER-TRANSPORT"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {"session_ref": self.session, "command": COMMAND, "command_ref": ref, "params": params}
        )

    def test_01_advertised_in_enabled_commands(self) -> None:
        bind = self.adapter.bind_session("S16B-DEVWATER-TRANSPORT-BIND-PROBE")
        self.assertIn(COMMAND, bind["enabled_commands"])

    def test_02_delta_s_missing_is_rejected(self) -> None:
        # A
        result = self.command("B27-A-MISSING", {})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("DEV_WATER_TIME_DELTA_S_REQUIRED", result["reason"])

    def test_03_delta_s_negative_is_rejected(self) -> None:
        # B
        result = self.command("B27-B-NEGATIVE", {"delta_s": -1.0})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("DEV_WATER_TIME_DELTA_S_MUST_BE_NON_NEGATIVE", result["reason"])

    def test_04_delta_s_non_numeric_is_rejected(self) -> None:
        # C: string
        result = self.command("B27-C-STRING", {"delta_s": "900"})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("DEV_WATER_TIME_DELTA_S_MUST_BE_FINITE_NUMBER", result["reason"])

    def test_05_delta_s_bool_is_rejected(self) -> None:
        # C: bool is not accepted as a number (matches _finite()'s own contract)
        result = self.command("B27-C-BOOL", {"delta_s": True})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("DEV_WATER_TIME_DELTA_S_MUST_BE_FINITE_NUMBER", result["reason"])

    def test_06_delta_s_non_finite_is_rejected(self) -> None:
        # C: NaN / inf
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad=bad):
                result = self.command(f"B27-C-NONFINITE-{bad}", {"delta_s": bad})
                self.assertEqual("REJECTED", result["status"])
                self.assertEqual("DEV_WATER_TIME_DELTA_S_MUST_BE_FINITE_NUMBER", result["reason"])

    def test_07_unexpected_param_is_rejected(self) -> None:
        result = self.command("B27-UNEXPECTED-PARAM", {"delta_s": 1.0, "bogus": True})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("UNEXPECTED_COMMAND_PARAM", result["reason"])

    def test_08_zero_delta_is_accepted_server_authoritative_no_side_effects(self) -> None:
        # L: server_authoritative=true. K: no XP/equip/inventory side effects
        # beyond the TTL consequence itself -- on a world with nothing in
        # water, delta_s=0 is a real, accepted no-op.
        before_xp = self.adapter._engine.character(self.adapter.world_instance_id).ensure_profile(
            self.adapter.profile_ref
        )["experience"]
        before_inv = self.adapter.snapshot(self.session)["inventory_projection"]["base_inventory"]["stacks"]

        result = self.command("B27-ZERO-DELTA", {"delta_s": 0.0})
        self.assertEqual("PASS", result["status"])
        self.assertTrue(result["server_authoritative"])
        self.assertTrue(result["development_only"])
        self.assertTrue(result["grants_nothing"])
        self.assertEqual("ADVANCE_DEVELOPMENT_WATER_TIME", result["command"])

        after_xp = self.adapter._engine.character(self.adapter.world_instance_id).ensure_profile(
            self.adapter.profile_ref
        )["experience"]
        after_inv = self.adapter.snapshot(self.session)["inventory_projection"]["base_inventory"]["stacks"]
        self.assertEqual(before_xp, after_xp)
        self.assertEqual(before_inv, after_inv)

    def test_09_replay_same_command_ref_no_second_advance(self) -> None:
        # J: replay does not advance the clock a second time.
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        position = self.adapter._engine.movement(self.adapter.world_instance_id).state(
            self.adapter._player_ref
        )
        spawned = stage16a.ground_loot.spawn_drop(
            source_ref="B27-REPLAY-SOURCE", source_kind="PLAYER_DROP", item_ref="ITEM-FOOD",
            item_kind="CONSUMABLE", quantity=1, candidate_position=position, event_ref="B27-REPLAY-SPAWN",
        )
        drop_ref = spawned["drop_ref"]
        stage16a.confirm_drop_settled(drop_ref, settled_position=position, reachable=True, event_ref="B27-REPLAY-SETTLE")
        self.adapter.command(
            {
                "session_ref": self.session, "command": "REPORT_GROUND_LOOT_WATER_STATE",
                "command_ref": "B27-REPLAY-MARK",
                "params": {
                    "request_ref": "B27-REPLAY-MARK:UI", "target_ref": drop_ref, "drop_ref": drop_ref,
                    "in_water": True, "flow_speed_mps": 0.0, "client_presentation_only": True,
                },
            }
        )
        first = self.command("B27-REPLAY-REF", {"delta_s": 100.0})
        self.assertEqual("PASS", first["status"])
        self.assertFalse(first["idempotent_replay"])
        exposure_after_first = stage16a.ground_loot.drop(drop_ref)["water_exposure_s"]

        second = self.command("B27-REPLAY-REF", {"delta_s": 100.0})
        self.assertTrue(second["idempotent_replay"], "DEV_WATER_TIME_REPLAY_SUPPRESSED")
        exposure_after_second = stage16a.ground_loot.drop(drop_ref)["water_exposure_s"]
        self.assertEqual(
            exposure_after_first, exposure_after_second, "DEV_WATER_TIME_REPLAY_NO_SECOND_ADVANCE"
        )
        # DEV_WATER_TIME_ADVANCE_AUTHORITATIVE
        self.assertEqual("PASS", first["status"])
        self.assertGreaterEqual(exposure_after_first, 100.0)


class Stage16BDevWaterTimeGroundLootBoundaryTests(unittest.TestCase):
    """E/F + section 8 save/reload, driven entirely through the new command."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_devwater_groundloot_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session = "S16B-DEVWATER-GROUNDLOOT"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, name: str, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {"session_ref": self.session, "command": name, "command_ref": ref, "params": params}
        )

    def test_01_899_alive_save_reload_900_sunk_via_command(self) -> None:
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        position = self.adapter._engine.movement(self.adapter.world_instance_id).state(
            self.adapter._player_ref
        )
        spawned = stage16a.ground_loot.spawn_drop(
            source_ref="B27-GL-SOURCE", source_kind="PLAYER_DROP", item_ref="ITEM-FOOD",
            item_kind="CONSUMABLE", quantity=1, candidate_position=position, event_ref="B27-GL-SPAWN",
        )
        drop_ref = spawned["drop_ref"]
        stage16a.confirm_drop_settled(drop_ref, settled_position=position, reachable=True, event_ref="B27-GL-SETTLE")
        marked = self.command(
            "REPORT_GROUND_LOOT_WATER_STATE", "B27-GL-MARK",
            {
                "request_ref": "B27-GL-MARK:UI", "target_ref": drop_ref, "drop_ref": drop_ref,
                "in_water": True, "flow_speed_mps": 0.3, "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", marked["status"])

        # E: delta_s=899 -> Ground Loot not SUNK
        advance_899 = self.command(COMMAND, "B27-GL-ADVANCE-899", {"delta_s": 899.0})
        self.assertEqual("PASS", advance_899["status"])
        self.assertEqual("ACTIVE", stage16a.ground_loot.drop(drop_ref)["state"])
        self.assertAlmostEqual(899.0, stage16a.ground_loot.drop(drop_ref)["water_exposure_s"], places=3)

        # Section 8: real save through the command-driven state
        saved = self.command(
            "REQUEST_SAVE", "B27-GL-SAVE-899",
            {
                "request_ref": "B27-GL-SAVE-899:UI", "slot_ref": "b27glwater", "save_kind": "MANUAL",
                "reason": "G16B27_DEV_WATER_TIME_CONTINUITY", "client_presentation_only": True,
            },
        )
        self.assertEqual("CONFIRMED", saved["result"])
        restored = self.command(
            "REQUEST_RELOAD_RESYNC", "B27-GL-RELOAD-899",
            {
                "request_ref": "B27-GL-RELOAD-899:UI", "slot_ref": "b27glwater",
                "require_resync_before_ready": True, "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", restored["status"])
        # REQUEST_RELOAD_RESYNC reopens the world's own SQLite connection, so
        # the pre-reload stage16a reference is stale (closed) afterward --
        # re-fetch it fresh, same convention as test_09 in
        # test_stage16b_authority_save_death_water.py.
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        # GROUND_LOOT_EXPOSURE_NOT_RESET_BY_RELOAD
        restored_drop = stage16a.ground_loot.drop(drop_ref)
        self.assertEqual("ACTIVE", restored_drop["state"])
        self.assertAlmostEqual(899.0, restored_drop["water_exposure_s"], places=3)

        # F: +1 -> exactly the threshold -> SUNK
        advance_1 = self.command(COMMAND, "B27-GL-ADVANCE-900", {"delta_s": 1.0})
        self.assertEqual("PASS", advance_1["status"])
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        self.assertEqual("SUNK", stage16a.ground_loot.drop(drop_ref)["state"])


class Stage16BDevWaterTimeBagBoundaryTests(unittest.TestCase):
    """G/H + section 8 save/reload for the dropped Bag, via the new command."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_devwater_bag_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session = "S16B-DEVWATER-BAG"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, name: str, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {"session_ref": self.session, "command": name, "command_ref": ref, "params": params}
        )

    def test_01_1799_floating_save_reload_1800_sunk_via_command(self) -> None:
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        owner = next(
            row["id"]
            for row in self.adapter._engine.country(self.adapter.world_instance_id)._all_npc_records()
            if row["id"] != self.adapter._player_ref
            and not stage16a.water_bag.ensure_carry_profile(row["id"]).get("equipped_bag_ref")
        )
        stage16a.water_bag.equip_new_bag(owner, event_ref="B27-BAG-EQUIP")
        position = self.adapter._engine.movement(self.adapter.world_instance_id).state(
            self.adapter._player_ref
        )
        dropped = stage16a.drop_bag_for_death(
            owner, in_water=True, position=position, event_ref="B27-BAG-DROP"
        )
        bag_ref = dropped["bag_ref"]

        # G: 1799 -> still floating
        advance_1799 = self.command(COMMAND, "B27-BAG-ADVANCE-1799", {"delta_s": 1799.0})
        self.assertEqual("PASS", advance_1799["status"])
        self.assertEqual("DROPPED_WATER_FLOATING", stage16a.water_bag.bag(bag_ref)["state"])

        # Section 8: real save through the command-driven state
        saved = self.command(
            "REQUEST_SAVE", "B27-BAG-SAVE-1799",
            {
                "request_ref": "B27-BAG-SAVE-1799:UI", "slot_ref": "b27bagwater", "save_kind": "MANUAL",
                "reason": "G16B27_DEV_WATER_TIME_BAG_CONTINUITY", "client_presentation_only": True,
            },
        )
        self.assertEqual("CONFIRMED", saved["result"])
        restored = self.command(
            "REQUEST_RELOAD_RESYNC", "B27-BAG-RELOAD-1799",
            {
                "request_ref": "B27-BAG-RELOAD-1799:UI", "slot_ref": "b27bagwater",
                "require_resync_before_ready": True, "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", restored["status"])
        # REQUEST_RELOAD_RESYNC reopens the world's own SQLite connection --
        # re-fetch stage16a fresh, same convention as test_11 in
        # test_stage16b_authority_save_death_water.py.
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        # BAG_EXPOSURE_NOT_RESET_BY_RELOAD
        restored_bag = stage16a.water_bag.bag(bag_ref)
        self.assertEqual("DROPPED_WATER_FLOATING", restored_bag["state"])
        self.assertAlmostEqual(1799.0, restored_bag["water_exposure_s"], places=3)

        # H: +1 -> SUNK; ownership preserved through the sink
        advance_1 = self.command(COMMAND, "B27-BAG-ADVANCE-1800", {"delta_s": 1.0})
        self.assertEqual("PASS", advance_1["status"])
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        sunk_bag = stage16a.water_bag.bag(bag_ref)
        self.assertEqual("SUNK", sunk_bag["state"])
        self.assertEqual(owner, sunk_bag["property_owner_ref"])

    def test_02_land_bag_survives_extreme_advance_via_command(self) -> None:
        # I: land Bag + large time advance -> continues to exist.
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        owner = next(
            row["id"]
            for row in self.adapter._engine.country(self.adapter.world_instance_id)._all_npc_records()
            if row["id"] != self.adapter._player_ref
            and not stage16a.water_bag.ensure_carry_profile(row["id"]).get("equipped_bag_ref")
        )
        stage16a.water_bag.equip_new_bag(owner, event_ref="B27-LANDBAG-EQUIP")
        position = self.adapter._engine.movement(self.adapter.world_instance_id).state(
            self.adapter._player_ref
        )
        dropped = stage16a.drop_bag_for_death(
            owner, in_water=False, position=position, event_ref="B27-LANDBAG-DROP"
        )
        bag_ref = dropped["bag_ref"]
        self.assertEqual("DROPPED_LAND", stage16a.water_bag.bag(bag_ref)["state"])

        result = self.command(COMMAND, "B27-LANDBAG-ADVANCE-EXTREME", {"delta_s": 100000.0})
        self.assertEqual("PASS", result["status"])
        bag_after = stage16a.water_bag.bag(bag_ref)
        self.assertEqual("DROPPED_LAND", bag_after["state"])
        self.assertEqual(owner, bag_after["property_owner_ref"])

        saved = self.command(
            "REQUEST_SAVE", "B27-LANDBAG-SAVE",
            {
                "request_ref": "B27-LANDBAG-SAVE:UI", "slot_ref": "b27landbag", "save_kind": "MANUAL",
                "reason": "G16B27_DEV_WATER_TIME_LANDBAG_CONTINUITY", "client_presentation_only": True,
            },
        )
        self.assertEqual("CONFIRMED", saved["result"])
        restored = self.command(
            "REQUEST_RELOAD_RESYNC", "B27-LANDBAG-RELOAD",
            {
                "request_ref": "B27-LANDBAG-RELOAD:UI", "slot_ref": "b27landbag",
                "require_resync_before_ready": True, "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", restored["status"])
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        self.assertEqual("DROPPED_LAND", stage16a.water_bag.bag(bag_ref)["state"])
