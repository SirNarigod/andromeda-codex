"""G16B-28: ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY transport.

ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY (andromeda_authority_adapter.py::
_attempt_development_npc_bag_recovery()) is a thin, development-only,
narrowly-scoped transport wrapper around the exact same stage16a.recover_bag()
the real REQUEST_BAG_RECOVERY handler already calls for the player. It exists
solely so a stranger-NPC bag-recovery ATTEMPT -- which real gameplay never
lets a client provoke, since every command in this system is single-actor
(the session only ever represents the Player) -- can be observed live from
Godot. claimant_kind is fixed to "NPC" server-side and is never client-
controlled; the client supplies only bag_ref and npc_ref. The core is the
only thing that decides pass/reject.

These tests exercise the command itself: transport validation, the
development-profile guard, npc_ref validation against the real NPC registry,
replay/idempotency, and the real stranger-NPC-rejected / owner-NPC-recovers
behaviors -- reconfirming, through a Godot-reachable command instead of
direct core access, the exact same enforcement
test_stage16b_authority_save_death_water.py::test_10 already proved.
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

COMMAND = "ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY"


def build_config(root: pathlib.Path) -> AuthorityConfig:
    master = _resolve_master_path()
    return AuthorityConfig(
        master_release_path=master,
        master_release_sha256=verify_master(master),
        runtime_dir=PROJECT_ROOT / "01_RUNTIME",
        db_path=root / "world.sqlite",
        save_root=root / "saves",
        owner_scope="stage16b:dev-npc-bag-recovery-test",
        world_seed=160832,
        player_class="WARRIOR",
        development_profile_bootstrap=True,
    )


class Stage16BDevNpcBagRecoveryGuardTests(unittest.TestCase):
    """A: development profile OFF -> REJECTED, zero mutation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_devnpcbag_guard_")
        cls.root = pathlib.Path(cls._tmp.name)
        cfg = dataclasses.replace(build_config(cls.root), development_profile_bootstrap=False)
        cls.adapter = Stage16BAuthorityAdapter(cfg)
        cls.session = "S16B-DEVNPCBAG-GUARD"
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
        # Real NPCs exist even with the loadout off (world population is not
        # gated by development_profile_bootstrap) -- confirm the guard fires
        # before even bag_ref/npc_ref are read.
        result = self.command("B28-GUARD", {"bag_ref": "ANY", "npc_target_ref": "ANY"})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual(
            "DEV_NPC_BAG_RECOVERY_DISABLED_OUTSIDE_DEVELOPMENT_PROFILE", result["reason"]
        )


class Stage16BDevNpcBagRecoveryTransportTests(unittest.TestCase):
    """B, transport validation, npc_ref validation, H, I."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_devnpcbag_transport_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session = "S16B-DEVNPCBAG-TRANSPORT"
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
        bind = self.adapter.bind_session("S16B-DEVNPCBAG-TRANSPORT-BIND-PROBE")
        self.assertIn(COMMAND, bind["enabled_commands"])

    def test_02_bag_ref_missing_is_rejected(self) -> None:
        result = self.command("B28-MISSING-BAG", {"npc_target_ref": "whatever"})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("DEV_NPC_BAG_RECOVERY_BAG_REF_REQUIRED", result["reason"])

    def test_03_npc_ref_missing_is_rejected(self) -> None:
        result = self.command("B28-MISSING-NPC", {"bag_ref": "BAG-X"})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("DEV_NPC_BAG_RECOVERY_NPC_REF_REQUIRED", result["reason"])

    def test_04_player_ref_as_npc_ref_is_rejected(self) -> None:
        # The client cannot pretend the Player is "an NPC" through this route.
        # self.adapter._player_ref is the avatar_ref the guard actually
        # compares against (distinct from profile_ref).
        result = self.command(
            "B28-PLAYER-AS-NPC", {"bag_ref": "BAG-X", "npc_target_ref": self.adapter._player_ref}
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("DEV_NPC_BAG_RECOVERY_REF_IS_PLAYER_NOT_NPC", result["reason"])

    def test_05_unknown_npc_ref_is_rejected(self) -> None:
        result = self.command(
            "B28-UNKNOWN-NPC", {"bag_ref": "BAG-X", "npc_target_ref": "NOT-A-REAL-NPC-REF"}
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("DEV_NPC_BAG_RECOVERY_UNKNOWN_NPC_REF", result["reason"])

    def test_06_unknown_bag_ref_returns_natural_bag_not_found(self) -> None:
        real_npc = next(
            row["id"]
            for row in self.adapter._engine.country(self.adapter.world_instance_id)._all_npc_records()
            if row["id"] != self.adapter._player_ref
        )
        result = self.command("B28-UNKNOWN-BAG", {"bag_ref": "BAG-DOES-NOT-EXIST", "npc_target_ref": real_npc})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("BAG_NOT_FOUND", result["reason"])

    def test_07_unexpected_param_is_rejected(self) -> None:
        result = self.command("B28-UNEXPECTED-PARAM", {"bag_ref": "X", "npc_target_ref": "Y", "bogus": True})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("UNEXPECTED_COMMAND_PARAM", result["reason"])


class Stage16BDevNpcBagRecoveryBehaviorTests(unittest.TestCase):
    """C, D, E, F, G: real core behavior for stranger and owner NPC claimants."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_devnpcbag_behavior_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session = "S16B-DEVNPCBAG-BEHAVIOR"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {"session_ref": self.session, "command": COMMAND, "command_ref": ref, "params": params}
        )

    def _drop_a_real_npc_bag(self, label: str) -> tuple[str, str, str]:
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        npcs = [
            row["id"]
            for row in self.adapter._engine.country(self.adapter.world_instance_id)._all_npc_records()
            if row["id"] != self.adapter._player_ref
            and not stage16a.water_bag.ensure_carry_profile(row["id"]).get("equipped_bag_ref")
        ]
        owner, stranger = npcs[0], npcs[1]
        stage16a.water_bag.equip_new_bag(owner, event_ref=f"{label}-EQUIP")
        position = self.adapter._engine.movement(self.adapter.world_instance_id).state(
            self.adapter._player_ref
        )
        dropped = stage16a.drop_bag_for_death(
            owner, in_water=False,
            position={k: float(position.get(k, 0.0)) for k in ("iso_x_m", "iso_y_m", "altitude_m")},
            event_ref=f"{label}-DROP",
        )
        return dropped["bag_ref"], owner, stranger

    def test_01_stranger_npc_rejected_zero_mutation(self) -> None:
        bag_ref, owner, stranger = self._drop_a_real_npc_bag("B28-D")
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        before = dict(stage16a.water_bag.bag(bag_ref))

        # D: DEV_NPC_RECOVERY_COMMAND_AUTHORITATIVE / DEV_STRANGER_NPC_RECOVERY_REJECTED
        result = self.command("B28-STRANGER", {"bag_ref": bag_ref, "npc_target_ref": stranger})
        self.assertEqual("REJECTED", result["status"])
        # DEV_STRANGER_NPC_RECOVERY_REASON
        self.assertEqual("FOREIGN_NPC_BAG_RECOVERY_NOT_ENABLED", result["reason"])
        self.assertTrue(result["server_authoritative"])
        self.assertTrue(result["development_only"])
        self.assertEqual(COMMAND, result["command"])

        # E: DEV_STRANGER_NPC_ZERO_MUTATION / OWNER_UNCHANGED / CONTENTS_UNCHANGED
        after = dict(stage16a.water_bag.bag(bag_ref))
        self.assertEqual(before["property_owner_ref"], after["property_owner_ref"])
        self.assertEqual(owner, after["property_owner_ref"])
        self.assertEqual(before["carrier_ref"], after["carrier_ref"])
        self.assertEqual(before["state"], after["state"])
        self.assertEqual(before.get("foreign_recovery_ref"), after.get("foreign_recovery_ref"))
        self.assertEqual(before, after, "DEV_STRANGER_NPC_ZERO_MUTATION")

    def test_02_owner_npc_recovers_own_bag_real_core_behavior(self) -> None:
        # C: npc_ref that IS the bag's own owner -- observe the REAL core
        # behavior (recover_bag() checks ownership BEFORE claimant_kind, so
        # the owner branch fires regardless of claimant_kind="NPC" here).
        bag_ref, owner, _stranger = self._drop_a_real_npc_bag("B28-C")
        result = self.command("B28-OWNER-RECOVERS", {"bag_ref": bag_ref, "npc_target_ref": owner})
        self.assertEqual("PASS", result["status"])
        self.assertEqual("OWNER", result["ownership"])
        self.assertEqual("EQUIPPED", result["bag"]["state"])
        self.assertEqual(owner, result["bag"]["carrier_ref"])

    def test_03_replay_same_command_ref_zero_additional_mutation(self) -> None:
        bag_ref, owner, stranger = self._drop_a_real_npc_bag("B28-G")
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)

        first = self.command("B28-REPLAY-REF", {"bag_ref": bag_ref, "npc_target_ref": stranger})
        self.assertEqual("REJECTED", first["status"])
        self.assertFalse(first["idempotent_replay"])
        state_after_first = dict(stage16a.water_bag.bag(bag_ref))

        second = self.command("B28-REPLAY-REF", {"bag_ref": bag_ref, "npc_target_ref": stranger})
        # DEV_NPC_RECOVERY_REPLAY_SUPPRESSED
        self.assertTrue(second["idempotent_replay"])
        state_after_second = dict(stage16a.water_bag.bag(bag_ref))
        self.assertEqual(state_after_first, state_after_second)
        self.assertEqual(owner, state_after_second["property_owner_ref"])

    def test_04_command_does_not_grant_item_or_xp(self) -> None:
        # H: no side effects on the Player beyond the transport itself.
        bag_ref, owner, stranger = self._drop_a_real_npc_bag("B28-H")
        before_xp = self.adapter._engine.character(self.adapter.world_instance_id).ensure_profile(
            self.adapter.profile_ref
        )["experience"]
        before_inv = self.adapter.snapshot(self.session)["inventory_projection"]["base_inventory"]["stacks"]

        result = self.command("B28-NO-SIDE-EFFECTS", {"bag_ref": bag_ref, "npc_target_ref": stranger})
        self.assertEqual("REJECTED", result["status"])

        after_xp = self.adapter._engine.character(self.adapter.world_instance_id).ensure_profile(
            self.adapter.profile_ref
        )["experience"]
        after_inv = self.adapter.snapshot(self.session)["inventory_projection"]["base_inventory"]["stacks"]
        self.assertEqual(before_xp, after_xp)
        self.assertEqual(before_inv, after_inv)
