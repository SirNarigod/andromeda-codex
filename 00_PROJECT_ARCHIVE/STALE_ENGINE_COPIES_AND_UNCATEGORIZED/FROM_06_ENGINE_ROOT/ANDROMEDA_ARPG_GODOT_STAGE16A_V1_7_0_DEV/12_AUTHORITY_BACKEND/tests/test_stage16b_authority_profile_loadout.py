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
        owner_scope="stage16b:profile-loadout-test",
        world_seed=160823,
        player_class="WARRIOR",
        development_profile_bootstrap=True,
    )


class Stage16BAuthorityProfileLoadoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_profile_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.config = build_config(cls.root)
        cls.adapter = Stage16BAuthorityAdapter(cls.config)
        cls.session = "S16B-PROFILE-LOADOUT"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, command: str, params: dict, ref: str) -> dict:
        return self.adapter.command(
            {"session_ref": self.session, "command": command, "command_ref": ref, "params": params}
        )

    def test_01_dev_profile_uses_two_catalog_weapons_and_one_main_hand(self) -> None:
        snapshot = self.adapter.snapshot(self.session)
        loadout = snapshot["weapon_loadout"]
        self.assertEqual({"1", "2"}, set(loadout["slots"]))
        self.assertTrue(loadout["slots"]["1"])
        self.assertTrue(loadout["slots"]["2"])
        self.assertNotEqual(loadout["slots"]["1"], loadout["slots"]["2"])
        self.assertIn(loadout["active_slot"], (1, 2))
        inventory = snapshot["inventory"]
        self.assertEqual(loadout["slots"][str(loadout["active_slot"])], inventory["equipped"]["MAIN_HAND"])
        applied = [
            row for row in snapshot["equipment_modifiers"]["equipped"]
            if row.get("slot") == "MAIN_HAND" and row.get("applied")
        ]
        self.assertEqual(1, len(applied))

    def test_02_auto_pickup_roundtrip_and_snapshot_projection(self) -> None:
        enabled = self.command("SET_AUTO_PICKUP", {"enabled": True}, "PROFILE-AUTO-ON")
        self.assertEqual("PASS", enabled["status"])
        self.assertTrue(enabled["enabled"])
        self.assertTrue(self.adapter.snapshot(self.session)["profile_preferences"]["auto_pickup"])
        disabled = self.command("SET_AUTO_PICKUP", {"enabled": False}, "PROFILE-AUTO-OFF")
        self.assertEqual("PASS", disabled["status"])
        self.assertFalse(self.adapter.snapshot(self.session)["profile_preferences"]["auto_pickup"])

    def test_03_auto_pickup_duplicate_is_suppressed(self) -> None:
        envelope = {
            "session_ref": self.session,
            "command": "SET_AUTO_PICKUP",
            "command_ref": "PROFILE-AUTO-REPLAY",
            "params": {"enabled": True},
        }
        first = self.adapter.command(envelope)
        second = self.adapter.command(envelope)
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        self.assertTrue(second["replay_suppressed"])

    def test_04_activate_slots_changes_authoritative_main_hand_without_stacking(self) -> None:
        first = self.command("ACTIVATE_WEAPON_SLOT", {"slot": 1}, "PROFILE-SLOT-1")
        second = self.command("ACTIVATE_WEAPON_SLOT", {"slot": 2}, "PROFILE-SLOT-2")
        self.assertEqual("PASS", first["status"])
        self.assertEqual("PASS", second["status"])
        snapshot = self.adapter.snapshot(self.session)
        loadout = snapshot["weapon_loadout"]
        self.assertEqual(2, loadout["active_slot"])
        self.assertEqual(loadout["slots"]["2"], snapshot["inventory"]["equipped"]["MAIN_HAND"])
        applied = [
            row for row in snapshot["equipment_modifiers"]["equipped"]
            if row.get("slot") == "MAIN_HAND" and row.get("applied")
        ]
        self.assertEqual(1, len(applied))
        self.assertEqual(loadout["slots"]["2"], applied[0]["instance_ref"])

    def test_05_cycle_and_duplicate_do_not_switch_twice(self) -> None:
        envelope = {
            "session_ref": self.session,
            "command": "CYCLE_WEAPON_SLOT",
            "command_ref": "PROFILE-CYCLE-REPLAY",
            "params": {"direction": 1},
        }
        first = self.adapter.command(envelope)
        active = self.adapter.snapshot(self.session)["weapon_loadout"]["active_slot"]
        second = self.adapter.command(envelope)
        after = self.adapter.snapshot(self.session)["weapon_loadout"]["active_slot"]
        self.assertEqual("PASS", first["status"])
        self.assertTrue(second["idempotent_replay"])
        self.assertTrue(second["replay_suppressed"])
        self.assertEqual(active, after)

    def test_06_profile_state_survives_adapter_restart(self) -> None:
        self.command("SET_AUTO_PICKUP", {"enabled": True}, "PROFILE-PERSIST-AUTO")
        self.command("ACTIVATE_WEAPON_SLOT", {"slot": 2}, "PROFILE-PERSIST-SLOT")
        before = self.adapter.snapshot(self.session)
        world_id = before["identity"]["world_instance_id"]
        self.adapter.close()
        self.__class__.adapter = Stage16BAuthorityAdapter(self.config)
        rebound = self.adapter.bind_session(self.session)
        self.assertEqual("PASS", rebound["status"])
        after = self.adapter.snapshot(self.session)
        self.assertEqual(world_id, after["identity"]["world_instance_id"])
        self.assertTrue(after["profile_preferences"]["auto_pickup"])
        self.assertEqual(before["weapon_loadout"], after["weapon_loadout"])
        self.assertEqual(
            before["inventory"]["equipped"]["MAIN_HAND"],
            after["inventory"]["equipped"]["MAIN_HAND"],
        )


    def test_20_inventory_may_hold_more_weapons_than_the_two_quick_slots(self) -> None:
        """G16B-21: two slots is a loadout limit, not an inventory limit."""
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        carried = self.adapter._weapon_instances(items)
        snapshot = self.adapter.snapshot(self.session)
        loadout = snapshot["weapon_loadout"]
        slotted = {str(ref) for ref in loadout["slots"].values() if ref}

        self.assertEqual(2, len(loadout["slots"]), "quick loadout must expose exactly 2 slots")
        self.assertEqual(2, len(slotted), "both quick slots must hold a distinct weapon")
        self.assertGreater(
            len(carried), len(slotted), "inventory must be able to carry a spare weapon"
        )
        self.assertTrue(set(slotted).issubset(set(carried)))

    def test_21_spare_weapon_is_never_equipped_and_never_stacks_modifiers(self) -> None:
        """The spare must stay inert: not in MAIN_HAND, no modifier contribution."""
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        snapshot = self.adapter.snapshot(self.session)
        loadout = snapshot["weapon_loadout"]
        slotted = {str(ref) for ref in loadout["slots"].values() if ref}
        spare = [ref for ref in self.adapter._weapon_instances(items) if ref not in slotted]
        self.assertTrue(spare, "no spare weapon carried")

        main_hand = str(snapshot["inventory"]["equipped"]["MAIN_HAND"])
        self.assertNotIn(main_hand, spare)
        active_slot = int(loadout["active_slot"])
        self.assertEqual(str(loadout["slots"][str(active_slot)]), main_hand)

        applied = [
            row
            for row in snapshot["equipment_modifiers"]["equipped"]
            if row.get("applied")
        ]
        self.assertEqual(1, len(applied), "only the active MAIN_HAND weapon may apply modifiers")
        self.assertEqual(main_hand, str(applied[0]["instance_ref"]))

    def test_22_activating_the_other_slot_still_leaves_the_spare_inert(self) -> None:
        snapshot = self.adapter.snapshot(self.session)
        current = int(snapshot["weapon_loadout"]["active_slot"])
        target = 2 if current == 1 else 1
        out = self.command("ACTIVATE_WEAPON_SLOT", {"slot": target}, "PROFILE-SPARE-SWAP")
        self.assertEqual("PASS", out["status"])

        after = self.adapter.snapshot(self.session)
        loadout = after["weapon_loadout"]
        self.assertEqual(target, int(loadout["active_slot"]))
        main_hand = str(after["inventory"]["equipped"]["MAIN_HAND"])
        self.assertEqual(str(loadout["slots"][str(target)]), main_hand)

        applied = [row for row in after["equipment_modifiers"]["equipped"] if row.get("applied")]
        self.assertEqual(1, len(applied))
        self.assertEqual(main_hand, str(applied[0]["instance_ref"]))


    def motion(self) -> dict:
        return dict(
            self.adapter._engine.movement(self.adapter.world_instance_id).state(
                self.adapter._player_ref
            )
        )

    def test_30_toggling_auto_pickup_never_disturbs_movement(self) -> None:
        """G16B-06 'never interrupts movement'."""
        moved = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "MOVE_TO_POINT",
                "command_ref": "PROFILE-NOINT-MOVE",
                "params": {
                    "iso_x_m": self.motion()["iso_x_m"] + 5.0,
                    "iso_y_m": self.motion()["iso_y_m"],
                    "duration_s": 0.25,
                    "mode": "WALK",
                },
            }
        )
        self.assertEqual("PASS", moved["status"])
        before = self.motion()

        self.command("SET_AUTO_PICKUP", {"enabled": True}, "PROFILE-NOINT-ON")
        self.command("SET_AUTO_PICKUP", {"enabled": False}, "PROFILE-NOINT-OFF")
        after = self.motion()

        for key in ("iso_x_m", "iso_y_m", "altitude_m", "stamina", "mode", "heading_deg", "elapsed_s"):
            self.assertEqual(before[key], after[key], f"auto pickup toggle moved {key}")

    def test_31_toggling_auto_pickup_never_clears_an_attack_cooldown(self) -> None:
        """G16B-06 'never interrupts attack': the toggle must not refresh cooldown."""
        snapshot = self.adapter.snapshot(self.session)
        target_ref = str(snapshot["combat_targets"][0]["target_ref"])

        def attack(ref: str) -> dict:
            return self.adapter.command(
                {
                    "session_ref": self.session,
                    "command": "REQUEST_ATTACK",
                    "command_ref": ref,
                    "params": {"target_ref": target_ref},
                }
            )

        first = attack("PROFILE-NOINT-ATTACK-1")
        self.assertEqual("PASS", first["status"], first.get("reason"))

        blocked = attack("PROFILE-NOINT-ATTACK-2")
        self.assertEqual("REJECTED", blocked["status"])
        self.assertEqual("ATTACK_COOLDOWN", blocked["reason"])

        self.command("SET_AUTO_PICKUP", {"enabled": True}, "PROFILE-NOINT-ATK-ON")
        self.command("SET_AUTO_PICKUP", {"enabled": False}, "PROFILE-NOINT-ATK-OFF")

        still_blocked = attack("PROFILE-NOINT-ATTACK-3")
        self.assertEqual("REJECTED", still_blocked["status"])
        self.assertEqual(
            "ATTACK_COOLDOWN",
            still_blocked["reason"],
            "the toggle must not clear or restart the authoritative cooldown",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
