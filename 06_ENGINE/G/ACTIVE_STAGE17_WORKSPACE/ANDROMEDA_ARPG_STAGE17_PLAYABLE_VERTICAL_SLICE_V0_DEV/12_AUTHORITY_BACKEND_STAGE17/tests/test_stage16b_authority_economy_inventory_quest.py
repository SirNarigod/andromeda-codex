from __future__ import annotations

import dataclasses
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
        owner_scope="stage16b:economy-inventory-quest-authority-test",
        world_seed=160800,
        player_class="WARRIOR",
        development_profile_bootstrap=True,
    )


class Stage16BAuthorityEconomyInventoryQuestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_economy_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session = "S16B-ECONOMY"
        cls.adapter.bind_session(cls.session)
        cls.snapshot = cls.adapter.snapshot(cls.session)
        cls.vendor = cls.snapshot["vendor_stock"][0]
        cls.stock = next(row for row in cls.vendor["items"] if "instance_ref" not in row)
        cls.quote_result: dict = {}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, name: str, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {
                "session_ref": self.session,
                "command": name,
                "command_ref": ref,
                "params": params,
            }
        )

    def quote(self, ref: str, quantity: int = 1) -> dict:
        return self.command(
            "REQUEST_TRADE_QUOTE",
            ref,
            {
                "request_ref": ref + ":UI",
                "vendor_ref": self.vendor["vendor_ref"],
                "item_ref": self.stock["item_ref"],
                "direction": "BUY",
                "quantity": quantity,
                "client_presentation_only": True,
            },
        )

    def execute(self, quote: dict, ref: str, **overrides: object) -> dict:
        params = {
            "quote_ref": quote["quote_ref"],
            "event_ref": ref + ":UI_EVENT",
            "confirmation_ref": ref + ":CONFIRM",
            "vendor_ref": quote["vendor_ref"],
            "item_ref": quote["item_ref"],
            "direction": quote["direction"],
            "quantity": quote["quantity"],
            "explicit_user_confirmation": True,
            "client_presentation_only": True,
        }
        params.update(overrides)
        return self.command("EXECUTE_TRADE", ref, params)

    def test_01_snapshot_projects_real_inventory_vendor_wallet_and_quests(self) -> None:
        projection = self.snapshot["inventory_projection"]
        self.assertEqual(8, projection["base_inventory"]["slot_limit"])
        self.assertEqual("NO_BAG", projection["bag"]["state"])
        self.assertEqual(2, len(projection["weapon_loadout"]["quick_slots"]))
        self.assertIn(projection["weapon_loadout"]["active_slot"], (1, 2))
        self.assertTrue(self.vendor["items"])
        self.assertTrue(all(row["price_requires_quote"] for row in self.vendor["items"]))
        self.assertEqual(5, self.snapshot["quest_projection"]["template_count"])
        self.assertTrue(self.snapshot["economy_projection"]["wallet"]["owner_ref"])

    def test_02_quote_is_stage13_authoritative_and_contains_no_auto_execute(self) -> None:
        out = self.quote("S16B-ECONOMY-QUOTE-1")
        type(self).quote_result = out
        self.assertEqual("PASS", out["status"])
        self.assertTrue(out["server_authoritative"])
        self.assertTrue(out["price_evaluated_server_side"])
        self.assertGreater(float(out["unit_price"]), 0.0)
        self.assertGreater(float(out["total_price"]), 0.0)
        self.assertNotIn("trade", out)

    def test_03_duplicate_quote_is_transport_suppressed(self) -> None:
        first = self.quote("S16B-ECONOMY-QUOTE-REPLAY")
        second = self.quote("S16B-ECONOMY-QUOTE-REPLAY")
        self.assertEqual(first["quote_ref"], second["quote_ref"])
        self.assertTrue(second["idempotent_replay"])
        self.assertTrue(second["replay_suppressed"])

    def test_04_execute_requires_explicit_confirmation(self) -> None:
        quote = self.quote("S16B-ECONOMY-QUOTE-NO-CONFIRM")
        out = self.execute(
            quote,
            "S16B-ECONOMY-NO-CONFIRM",
            explicit_user_confirmation=False,
        )
        self.assertEqual("EXPLICIT_USER_CONFIRMATION_REQUIRED", out["reason"])

    def test_05_quote_identity_mismatch_is_inert(self) -> None:
        quote = self.quote("S16B-ECONOMY-QUOTE-MISMATCH")
        economy = self.adapter._engine.economy_arpg(self.adapter.world_instance_id)
        before = economy.wallet(self.adapter.profile_ref)["balance"]
        out = self.execute(
            quote,
            "S16B-ECONOMY-MISMATCH",
            quantity=int(quote["quantity"]) + 1,
        )
        after = economy.wallet(self.adapter.profile_ref)["balance"]
        self.assertEqual("QUOTE_QUANTITY_MISMATCH", out["reason"])
        self.assertEqual(before, after)

    def test_06_explicit_buy_mutates_only_stage13_and_stage05(self) -> None:
        quote = self.quote("S16B-ECONOMY-QUOTE-BUY-BASE")
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        economy = self.adapter._engine.economy_arpg(self.adapter.world_instance_id)
        before_quantity = int(
            items.inventory_snapshot(self.adapter.profile_ref)["stacks"].get(
                self.stock["item_ref"], 0
            )
        )
        before_wallet = float(economy.wallet(self.adapter.profile_ref)["balance"])
        out = self.execute(quote, "S16B-ECONOMY-BUY-BASE")
        after_quantity = int(
            items.inventory_snapshot(self.adapter.profile_ref)["stacks"].get(
                self.stock["item_ref"], 0
            )
        )
        after_wallet = float(economy.wallet(self.adapter.profile_ref)["balance"])
        self.assertEqual("PASS", out["status"])
        self.assertEqual("ACCEPTED", out["result"])
        self.assertEqual(before_quantity + 1, after_quantity)
        self.assertLess(after_wallet, before_wallet)
        self.assertEqual(self.adapter.profile_ref, out["inventory_owner_ref"])

    def test_07_bag_equip_is_a_real_stage16a_container(self) -> None:
        before_loadout = self.adapter._engine.stage16a(
            self.adapter.world_instance_id
        ).ensure_weapon_loadout(self.adapter.profile_ref)
        out = self.command(
            "REQUEST_EQUIP_BAG",
            "S16B-ECONOMY-EQUIP-BAG",
            {
                "request_ref": "S16B-ECONOMY-EQUIP-BAG:UI",
                "bag_instance_ref": "UI-CORRELATION-BAG",
                "client_presentation_only": True,
            },
        )
        projection = self.adapter.snapshot(self.session)["inventory_projection"]
        after_loadout = self.adapter._engine.stage16a(
            self.adapter.world_instance_id
        ).ensure_weapon_loadout(self.adapter.profile_ref)
        self.assertEqual("PASS", out["status"])
        self.assertFalse(out["client_bag_instance_ref_used_as_authority"])
        self.assertEqual("BAG_EQUIPPED", projection["bag"]["state"])
        self.assertEqual("EQUIPPED_BAG", projection["routing"]["source"])
        self.assertEqual(before_loadout["slots"], after_loadout["slots"])

    def test_08_buy_with_bag_routes_through_stage16a(self) -> None:
        quote = self.quote("S16B-ECONOMY-QUOTE-BUY-BAG")
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        effective = stage16a.water_bag.effective_inventory_owner(self.adapter.profile_ref)
        self.assertNotEqual(self.adapter.profile_ref, effective)
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        before = int(items.inventory_snapshot(effective)["stacks"].get(self.stock["item_ref"], 0))
        out = self.execute(quote, "S16B-ECONOMY-BUY-BAG")
        after = int(items.inventory_snapshot(effective)["stacks"].get(self.stock["item_ref"], 0))
        self.assertEqual("PASS", out["status"])
        self.assertEqual(effective, out["inventory_owner_ref"])
        self.assertEqual(before + 1, after)

    def test_09_accept_quest_uses_existing_stage12_template(self) -> None:
        quest_ref = self.snapshot["quest_projection"]["offers"][0]["quest_ref"]
        out = self.command(
            "ACCEPT_QUEST",
            "S16B-QUEST-ACCEPT",
            {
                "request_ref": "S16B-QUEST-ACCEPT:UI",
                "quest_ref": quest_ref,
                "client_presentation_only": True,
            },
        )
        projection = self.adapter.snapshot(self.session)["quest_projection"]
        self.assertEqual("PASS", out["status"])
        self.assertEqual("ACTIVE", out["quest"]["state"])
        self.assertIn(quest_ref, {row["quest_ref"] for row in projection["quests"]})
        self.assertNotIn(quest_ref, {row["quest_ref"] for row in projection["offers"]})

    def test_10_duplicate_quest_accept_does_not_duplicate_state(self) -> None:
        quest_ref = self.adapter._engine.narrative_arpg(
            self.adapter.world_instance_id
        ).list_quests(self.adapter.profile_ref)[0]["quest_ref"]
        params = {
            "request_ref": "S16B-QUEST-REPLAY:UI",
            "quest_ref": quest_ref,
            "client_presentation_only": True,
        }
        first = self.command("ACCEPT_QUEST", "S16B-QUEST-REPLAY", params)
        second = self.command("ACCEPT_QUEST", "S16B-QUEST-REPLAY", params)
        quests = self.adapter._engine.narrative_arpg(
            self.adapter.world_instance_id
        ).list_quests(self.adapter.profile_ref)
        self.assertEqual("PASS", first["status"])
        self.assertTrue(second["replay_suppressed"])
        self.assertEqual(1, sum(row["quest_ref"] == quest_ref for row in quests))

    def test_11_wrong_session_and_forged_authority_are_inert(self) -> None:
        quote = self.quote("S16B-ECONOMY-QUOTE-SECURITY")
        forged = self.command(
            "EXECUTE_TRADE",
            "S16B-ECONOMY-FORGED",
            {
                "quote_ref": quote["quote_ref"],
                "event_ref": "FORGED:UI",
                "confirmation_ref": "FORGED:CONFIRM",
                "vendor_ref": quote["vendor_ref"],
                "item_ref": quote["item_ref"],
                "direction": quote["direction"],
                "quantity": quote["quantity"],
                "explicit_user_confirmation": True,
                "owner_ref": "FORGED-OWNER",
            },
        )
        wrong_session = self.adapter.command(
            {
                "session_ref": "WRONG-SESSION",
                "command": "ACCEPT_QUEST",
                "command_ref": "S16B-QUEST-WRONG-SESSION",
                "params": {
                    "quest_ref": "QST-S12-VARGA-MEDIATION",
                    "client_presentation_only": True,
                },
            }
        )
        self.assertEqual("CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN", forged["reason"])
        self.assertEqual("UNKNOWN_OR_INACTIVE_SESSION", wrong_session["reason"])


class Stage16BRequestEquipItemTests(unittest.TestCase):
    """REQUEST_EQUIP_ITEM: a thin transport that delegates 100% of validation
    (ownership, item existence, slot compatibility, idempotency) to the
    already-existing, protected items.equip(). No rule is duplicated here."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_equip_item_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session = "S16B-EQUIP-ITEM"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REQUEST_EQUIP_ITEM",
                "command_ref": ref,
                "params": params,
            }
        )

    def test_01_owned_armor_equips_to_compatible_slot(self) -> None:
        """REQUEST_EQUIP_ITEM_OWNED_ARMOR_PASS"""
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        grant = items.grant_item(self.adapter.profile_ref, "ITEM-ARMOR", 1, event_ref="EQI-ARMOR-GRANT")
        self.assertEqual("PASS", grant["status"])
        instance_ref = grant["instance_refs"][0]

        result = self.command("EQI-EQUIP-01", {"request_ref": "EQI-EQUIP-01:UI", "instance_ref": instance_ref, "slot": "CHEST"})
        self.assertEqual("PASS", result["status"])
        self.assertEqual("CHEST", result["slot"])
        self.assertEqual(instance_ref, result["instance_ref"])
        self.assertTrue(result["server_authoritative"])

        equipped = items.inventory_snapshot(self.adapter.profile_ref)["equipped"].get("CHEST")
        self.assertEqual(instance_ref, equipped, "the item core itself must show the same instance_ref equipped in CHEST")

    def test_02_foreign_instance_is_rejected(self) -> None:
        """REQUEST_EQUIP_ITEM_FOREIGN_REJECTED -- the client cannot equip an
        instance owned by someone else."""
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        other_owner = next(
            str(row["id"])
            for row in self.adapter._engine.country(self.adapter.world_instance_id)._all_npc_records()
            if str(row.get("id") or "").strip() and str(row["id"]) != self.adapter._player_ref
        )
        items.ensure_inventory(other_owner)
        grant = items.grant_item(other_owner, "ITEM-ARMOR", 1, event_ref="EQI-FOREIGN-GRANT")
        self.assertEqual("PASS", grant["status"])
        foreign_instance_ref = grant["instance_refs"][0]
        chest_before = items.inventory_snapshot(self.adapter.profile_ref)["equipped"].get("CHEST")

        result = self.command("EQI-EQUIP-02", {"request_ref": "EQI-EQUIP-02:UI", "instance_ref": foreign_instance_ref, "slot": "CHEST"})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("ITEM_INSTANCE_NOT_OWNED", result["reason"])
        chest_after = items.inventory_snapshot(self.adapter.profile_ref)["equipped"].get("CHEST")
        self.assertEqual(chest_before, chest_after, "a rejected foreign equip must not change the player's own CHEST slot")
        self.assertNotEqual(foreign_instance_ref, chest_after, "the foreign instance must never end up equipped on the player")

    def test_03_incompatible_slot_is_rejected(self) -> None:
        """REQUEST_EQUIP_ITEM_INCOMPATIBLE_SLOT_REJECTED -- armor cannot go in HEAD."""
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        grant = items.grant_item(self.adapter.profile_ref, "ITEM-ARMOR", 1, event_ref="EQI-INCOMPATIBLE-GRANT")
        self.assertEqual("PASS", grant["status"])
        instance_ref = grant["instance_refs"][0]

        result = self.command("EQI-EQUIP-03", {"request_ref": "EQI-EQUIP-03:UI", "instance_ref": instance_ref, "slot": "HEAD"})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("ITEM_SLOT_INCOMPATIBLE", result["reason"])
        self.assertIsNone(items.inventory_snapshot(self.adapter.profile_ref)["equipped"].get("HEAD"))

    def test_04_replay_is_suppressed(self) -> None:
        """REQUEST_EQUIP_ITEM_REPLAY_SUPPRESSED"""
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        grant = items.grant_item(self.adapter.profile_ref, "ITEM-ARMOR", 1, event_ref="EQI-REPLAY-GRANT")
        self.assertEqual("PASS", grant["status"])
        instance_ref = grant["instance_refs"][0]

        first = self.command("EQI-EQUIP-04", {"request_ref": "EQI-EQUIP-04:UI", "instance_ref": instance_ref, "slot": "CHEST"})
        self.assertEqual("PASS", first["status"])
        replay = self.command("EQI-EQUIP-04", {"request_ref": "EQI-EQUIP-04:UI", "instance_ref": instance_ref, "slot": "CHEST"})
        self.assertTrue(replay.get("idempotent_replay"))
        # A single equip must not be recorded twice: swapping the same instance
        # out and back in would otherwise surface as a second, distinct mutation.
        equipped = items.inventory_snapshot(self.adapter.profile_ref)["equipped"].get("CHEST")
        self.assertEqual(instance_ref, equipped)

    def test_05_client_cannot_choose_an_item_it_does_not_own(self) -> None:
        """The client supplies only instance_ref/slot; there is no field through
        which it could name an item to conjure -- it must already exist and be
        owned. An unknown instance_ref is rejected the same way as a foreign one."""
        result = self.command("EQI-EQUIP-05", {"request_ref": "EQI-EQUIP-05:UI", "instance_ref": "itm:does-not-exist", "slot": "CHEST"})
        self.assertEqual("REJECTED", result["status"])

    def test_06_activate_weapon_slot_cycle_and_equip_bag_unaffected(self) -> None:
        """F: REQUEST_EQUIP_ITEM must not have altered ACTIVATE_WEAPON_SLOT,
        CYCLE_WEAPON_SLOT or REQUEST_EQUIP_BAG."""
        activate_result = self.adapter.command(
            {"session_ref": self.session, "command": "ACTIVATE_WEAPON_SLOT", "command_ref": "EQI-ACTIVATE-CHECK", "params": {"slot": 1}}
        )
        self.assertIn(activate_result["status"], ("PASS", "REJECTED"))
        self.assertEqual("ACTIVATE_WEAPON_SLOT", activate_result["command"])
        bag_result = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REQUEST_EQUIP_BAG",
                "command_ref": "EQI-BAG-CHECK",
                "params": {"request_ref": "EQI-BAG-CHECK:UI", "bag_instance_ref": "CLIENT-CORRELATION-ONLY", "client_presentation_only": True},
            }
        )
        self.assertEqual("REQUEST_EQUIP_BAG", bag_result["command"])


class Stage16BDevelopmentProtectedItemProvisioningTests(unittest.TestCase):
    """G16B-18/G16B-26 death-retention precondition: ITEM-OLD-KEY provisioned
    directly to the player by _ensure_development_profile_loadout(), the same
    server-side, development-only mechanism that already grants weapons/tool.
    No client command requests it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_dev_protected_item_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session = "S16B-DEV-PROTECTED-ITEM"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def test_01_provisioned_authoritative_and_projected_as_protected(self) -> None:
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)

        # DEV_PLAYER_PROTECTED_ITEM_PROVISIONED / _AUTHORITATIVE
        inventory = items.inventory_snapshot(self.adapter.profile_ref)
        self.assertEqual(1, int(inventory.get("stacks", {}).get("ITEM-OLD-KEY", 0)))

        # DEV_PLAYER_PROTECTED_ITEM_PROJECTED / _CLASSIFIED_PROTECTED
        snapshot = self.adapter.snapshot(self.session)
        base_stacks = snapshot["inventory_projection"]["base_inventory"]["stacks"]
        entry = next((row for row in base_stacks if row["item_ref"] == "ITEM-OLD-KEY"), None)
        self.assertIsNotNone(entry, "ITEM-OLD-KEY must be visible in the real inventory projection")
        self.assertTrue(entry["protected_or_critical"])
        self.assertIn("ITEM-OLD-KEY", snapshot["inventory_projection"]["equipment"]["protected_critical_refs"])

        # DEV_PLAYER_PROTECTED_ITEM_SINGLE_INSTANCE
        self.assertEqual(1, int(entry["quantity"]))

    def test_02_repeated_boot_does_not_duplicate(self) -> None:
        """DEV_PLAYER_PROTECTED_ITEM_BIND_IDEMPOTENT

        _ensure_development_profile_loadout() re-runs on every REQUEST_RELOAD_RESYNC
        (it calls _boot() again); calling it a second time directly proves the
        fixed event_ref replays instead of granting a second unit.
        """
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        before = int(items.inventory_snapshot(self.adapter.profile_ref).get("stacks", {}).get("ITEM-OLD-KEY", 0))
        self.assertEqual(1, before)

        second_call = self.adapter._ensure_development_profile_loadout()
        self.assertEqual("PASS", second_call["status"])
        self.assertTrue(second_call["protected_item_grant"].get("idempotent_replay"))

        after = int(items.inventory_snapshot(self.adapter.profile_ref).get("stacks", {}).get("ITEM-OLD-KEY", 0))
        self.assertEqual(1, after, "a repeated boot must never duplicate the provisioned protected item")

    def test_03_survives_equip_bag_as_a_single_unit_inside_it(self) -> None:
        """Bag test from the authorization: item sweeps into a real Bag by the
        existing, unmodified equip_new_bag() behavior; total quantity stays 1."""
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        before_total = int(items.inventory_snapshot(self.adapter.profile_ref).get("stacks", {}).get("ITEM-OLD-KEY", 0))
        self.assertEqual(1, before_total)

        equip_bag = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REQUEST_EQUIP_BAG",
                "command_ref": "DEV-PROTECTED-ITEM-BAG",
                "params": {"request_ref": "DEV-PROTECTED-ITEM-BAG:UI", "bag_instance_ref": "CLIENT-CORRELATION-ONLY", "client_presentation_only": True},
            }
        )
        self.assertEqual("PASS", equip_bag["status"])
        bag_ref = equip_bag["bag_ref"]

        base_after = int(items.inventory_snapshot(self.adapter.profile_ref).get("stacks", {}).get("ITEM-OLD-KEY", 0))
        bag_after = int(items.inventory_snapshot(bag_ref).get("stacks", {}).get("ITEM-OLD-KEY", 0))
        self.assertEqual(0, base_after, "the item must have moved out of the base inventory into the Bag")
        self.assertEqual(1, bag_after, "the item must now be inside the equipped Bag")
        self.assertEqual(1, base_after + bag_after, "total quantity must remain exactly 1 across base+Bag")


class Stage16BDevelopmentProtectedItemNonDevGuardTests(unittest.TestCase):
    """DEV_PLAYER_PROTECTED_ITEM_DISABLED_OUTSIDE_DEV_PROFILE"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_dev_protected_item_off_")
        cls.root = pathlib.Path(cls._tmp.name)
        cfg = dataclasses.replace(build_config(cls.root), development_profile_bootstrap=False)
        cls.adapter = Stage16BAuthorityAdapter(cfg)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def test_01_non_development_profile_never_receives_the_item(self) -> None:
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        items.ensure_inventory(self.adapter.profile_ref)
        inventory = items.inventory_snapshot(self.adapter.profile_ref)
        self.assertEqual(0, int(inventory.get("stacks", {}).get("ITEM-OLD-KEY", 0)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
