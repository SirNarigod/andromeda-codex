"""G16B-18/G16B-26 CLOTHES: the first real Stage16B CLOTHES item.

S16B-DEV-CLOTHES-LEGS-001 -- development-only, non-canonical, owned entirely
by _ensure_development_clothes_definition()/_ensure_development_profile_
loadout() in andromeda_authority_adapter.py. Nothing here fabricates a
projection manually: every assertion reads real engine/adapter state through
the same paths REQUEST_EQUIP_ITEM, inventory_snapshot(), _retention_
projection() and save/reload already use for armor/protected-item/common-item
in the existing death-retention suite.
"""

from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
import sys

sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "01_RUNTIME"))

from andromeda_authority_adapter import Stage16BAuthorityAdapter, AuthorityBootError  # noqa: E402
from authority_config import AuthorityConfig, _resolve_master_path, verify_master  # noqa: E402
from living_runtime import NotFoundError  # noqa: E402

CLOTHES_REF = "S16B-DEV-CLOTHES-LEGS-001"


def build_config(root: pathlib.Path) -> AuthorityConfig:
    master = _resolve_master_path()
    return AuthorityConfig(
        master_release_path=master,
        master_release_sha256=verify_master(master),
        runtime_dir=PROJECT_ROOT / "01_RUNTIME",
        db_path=root / "world.sqlite",
        save_root=root / "saves",
        owner_scope="stage16b:clothes-authority-test",
        world_seed=160830,
        player_class="WARRIOR",
        development_profile_bootstrap=True,
    )


class Stage16BClothesDefinitionTests(unittest.TestCase):
    """Definition schema, provenance, hash, idempotency, drift rejection."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_clothes_def_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.adapter.bind_session("S16B-CLOTHES-DEF")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def test_01_definition_created_and_schema_valid(self) -> None:
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        d = items.definition(CLOTHES_REF)
        # DEV_CLOTHES_DEFINITION_CREATED / DEV_CLOTHES_DEFINITION_SCHEMA_VALID
        self.assertEqual("CLOTHES", d["item_kind"])
        self.assertEqual(["LEGS"], d["equip_slots"])
        self.assertEqual(1, d["stack_max"])
        self.assertEqual("UNIQUE_INSTANCE", d["instance_policy"])
        self.assertFalse(d["stackable"])
        self.assertFalse(d["canonical_identity"])
        self.assertEqual("STAGE16B_DEVELOPMENT_ONLY", d["source_kind"])
        self.assertNotIn("STAGE09_", d["source_kind"])
        self.assertNotIn("STAGE13_", d["source_kind"])

    def test_02_definition_idempotent_across_reboot(self) -> None:
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        before = items.definition(CLOTHES_REF)
        # Re-run the provider directly -- must be a pure no-op, same bytes.
        result = self.adapter._ensure_development_clothes_definition()
        self.assertEqual("PASS", result["status"])
        self.assertFalse(result["created_this_call"], "DEV_CLOTHES_DEFINITION_IDEMPOTENT")
        after = items.definition(CLOTHES_REF)
        self.assertEqual(before, after)

    def test_03_definition_survives_resume_world(self) -> None:
        wid = self.adapter.world_instance_id
        self.adapter.close()
        second = Stage16BAuthorityAdapter(build_config(self.root))
        try:
            second.bind_session("S16B-CLOTHES-DEF-RESUME")
            self.assertEqual(wid, second.world_instance_id)
            items = second._engine.items_arpg(second.world_instance_id)
            d = items.definition(CLOTHES_REF)
            self.assertEqual("CLOTHES", d["item_kind"])
            # DEV_CLOTHES_DEFINITION_SURVIVES_RESUME / DEV_CLOTHES_PROVIDER_VERIFY_PASS
            report = items.verify()
            self.assertEqual("PASS", report["status"], report["failures"])
            for f in report["failures"]:
                self.assertNotIn("ITEM_DEFINITION_CATALOG_REF_MISSING", f, "NO_ITEM_DEFINITION_CATALOG_REF_MISSING")
        finally:
            second.close()
            # Re-open once more so tearDownClass's own adapter.close() has a
            # live adapter to close (matches this class's fixture contract).
            type(self).adapter = Stage16BAuthorityAdapter(build_config(self.root))
            self.adapter.bind_session("S16B-CLOTHES-DEF-REOPEN")

    def test_04_delete_is_blocked_by_the_immutability_trigger(self) -> None:
        # arpg_item_definitions forbids DELETE at the schema level (see
        # arpg_item_core.py::_init_schema()'s arpg_item_definition_no_delete
        # trigger) -- confirm that guarantee holds for this provider's own
        # row too, not just for catalog-sourced rows.
        import sqlite3

        conn = self.adapter._engine.runtime.conn
        with self.assertRaises(sqlite3.IntegrityError):
            with self.adapter._engine.runtime._write_lock:
                conn.execute("DELETE FROM arpg_item_definitions WHERE item_ref=?", (CLOTHES_REF,))

    def test_05_drift_is_rejected_not_silently_accepted(self) -> None:
        # DELETE is blocked (test_04), so the only way to observe this
        # provider's own drift path is at the Python level: if a future edit
        # of _expected_dev_clothes_legs_definition() ever disagreed with what
        # is already stored, the provider must raise, never silently accept
        # the stored (now-mismatched) row and never attempt UPDATE/DELETE+
        # INSERT. This calls the real provider method with its own expected-
        # definition builder swapped for one call, proving that exact
        # hash-mismatch branch fires.
        real_expected = type(self.adapter)._expected_dev_clothes_legs_definition

        def drifted_expected(self_inner):
            d = dict(real_expected(self_inner))
            d["equip_slots"] = ["CHEST"]  # deliberate mismatch vs. what is stored
            return d

        type(self.adapter)._expected_dev_clothes_legs_definition = drifted_expected
        try:
            with self.assertRaises(AuthorityBootError):
                self.adapter._ensure_development_clothes_definition()
        finally:
            type(self.adapter)._expected_dev_clothes_legs_definition = real_expected

        # DEV_CLOTHES_DEFINITION_DRIFT_REJECTED: the stored row itself must be
        # completely untouched by the rejected attempt -- still the original,
        # correct definition, still passing verify().
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        d = items.definition(CLOTHES_REF)
        self.assertEqual(["LEGS"], d["equip_slots"])
        report = items.verify()
        self.assertEqual("PASS", report["status"], report["failures"])


class Stage16BClothesProvisioningTests(unittest.TestCase):
    """Grant, single-instance, boot idempotency, equip, projections, save/reload, death."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_clothes_prov_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session = "S16B-CLOTHES-PROV"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, name: str, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {"session_ref": self.session, "command": name, "command_ref": ref, "params": params}
        )

    def test_01_provisioned_single_instance(self) -> None:
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        profile_ref = self.adapter.profile_ref
        snap = items.inventory_snapshot(profile_ref)
        matches = [i for i in snap.get("instance_refs", []) if items.instance(i)["item_ref"] == CLOTHES_REF]
        # DEV_CLOTHES_PROVISIONED / DEV_CLOTHES_SINGLE_INSTANCE
        self.assertEqual(1, len(matches), matches)
        type(self).clothes_instance_ref = matches[0]

    def test_02_boot_idempotent_no_duplication(self) -> None:
        wid = self.adapter.world_instance_id
        self.adapter.close()
        second = Stage16BAuthorityAdapter(build_config(self.root))
        try:
            second.bind_session("S16B-CLOTHES-PROV-REBOOT")
            self.assertEqual(wid, second.world_instance_id)
            items = second._engine.items_arpg(second.world_instance_id)
            snap = items.inventory_snapshot(second.profile_ref)
            matches = [i for i in snap.get("instance_refs", []) if items.instance(i)["item_ref"] == CLOTHES_REF]
            # DEV_CLOTHES_BOOT_IDEMPOTENT
            self.assertEqual(1, len(matches), matches)
            self.assertEqual(self.clothes_instance_ref, matches[0])
        finally:
            second.close()
            type(self).adapter = Stage16BAuthorityAdapter(build_config(self.root))
            self.adapter.bind_session(self.session)

    def test_03_equip_legs_authoritative(self) -> None:
        equip = self.command(
            "REQUEST_EQUIP_ITEM",
            "CLOTHES-EQUIP-LEGS",
            {"request_ref": "CLOTHES-EQUIP-LEGS:UI", "instance_ref": self.clothes_instance_ref, "slot": "LEGS"},
        )
        # DEV_CLOTHES_EQUIP_COMMAND_AUTHORITATIVE / DEV_CLOTHES_EQUIP_PASS
        self.assertEqual("PASS", equip.get("status"), equip)

        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        snap = items.inventory_snapshot(self.adapter.profile_ref)
        # DEV_CLOTHES_LEGS_SLOT_ACTIVE / DEV_CLOTHES_SAME_INSTANCE_EQUIPPED
        self.assertEqual(self.clothes_instance_ref, snap.get("equipped", {}).get("LEGS"))

    def test_04_incompatible_slot_rejected_by_item_core(self) -> None:
        rejected = self.command(
            "REQUEST_EQUIP_ITEM",
            "CLOTHES-EQUIP-CHEST-BAD",
            {"request_ref": "CLOTHES-EQUIP-CHEST-BAD:UI", "instance_ref": self.clothes_instance_ref, "slot": "CHEST"},
        )
        self.assertEqual("REJECTED", rejected.get("status"), rejected)
        self.assertEqual("ITEM_SLOT_INCOMPATIBLE", rejected.get("reason"))
        # LEGS must still hold the same instance -- the rejected attempt did nothing.
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        snap = items.inventory_snapshot(self.adapter.profile_ref)
        self.assertEqual(self.clothes_instance_ref, snap.get("equipped", {}).get("LEGS"))

    def test_05_projected_as_clothes_not_armor(self) -> None:
        projection = self.adapter._retention_projection()
        # DEV_CLOTHES_PROJECTED_AS_CLOTHES / DEV_CLOTHES_NOT_PROJECTED_AS_ARMOR
        self.assertIn(self.clothes_instance_ref, projection["equipped_clothes_refs"])
        self.assertNotIn(self.clothes_instance_ref, projection["equipped_armor_refs"])
        # DEV_CLOTHES_RETENTION_PROJECTION_READY: the projection call itself
        # succeeded and returned a well-formed dict with both lists present.
        self.assertIsInstance(projection["equipped_armor_refs"], list)
        self.assertIsInstance(projection["equipped_clothes_refs"], list)

    def test_06_save_reload_preserves_same_instance(self) -> None:
        save = self.command(
            "REQUEST_SAVE",
            "CLOTHES-SAVE-1",
            {
                "request_ref": "CLOTHES-SAVE-1:UI",
                "slot_ref": "clothes-test",
                "save_kind": "MANUAL",
                "reason": "CLOTHES_AUTHORITY_TEST",
                "client_presentation_only": True,
            },
        )
        self.assertEqual("CONFIRMED", save.get("result"), save)

        wid = self.adapter.world_instance_id
        self.adapter.close()
        second = Stage16BAuthorityAdapter(build_config(self.root))
        try:
            second.bind_session("S16B-CLOTHES-RELOAD")
            self.assertEqual(wid, second.world_instance_id)
            items = second._engine.items_arpg(second.world_instance_id)
            snap = items.inventory_snapshot(second.profile_ref)
            # DEV_CLOTHES_SAVE_RELOAD_PRESERVED / DEV_CLOTHES_SAVE_RELOAD_SAME_INSTANCE
            self.assertEqual(self.clothes_instance_ref, snap.get("equipped", {}).get("LEGS"))
            matches = [i for i in snap.get("instance_refs", []) if items.instance(i)["item_ref"] == CLOTHES_REF]
            # DEV_CLOTHES_SAVE_RELOAD_NO_DUPLICATION
            self.assertEqual([self.clothes_instance_ref], matches)
            projection = second._retention_projection()
            self.assertIn(self.clothes_instance_ref, projection["equipped_clothes_refs"])
        finally:
            second.close()
            type(self).adapter = Stage16BAuthorityAdapter(build_config(self.root))
            self.adapter.bind_session(self.session)


class Stage16BClothesDeathRetentionTests(unittest.TestCase):
    """Isolated world: real player death, clothes must survive it untouched."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_clothes_death_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session = "S16B-CLOTHES-DEATH"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, name: str, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {"session_ref": self.session, "command": name, "command_ref": ref, "params": params}
        )

    def test_01_death_retains_clothes_same_instance_not_dropped(self) -> None:
        import time as _time

        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        profile_ref = self.adapter.profile_ref

        snap0 = items.inventory_snapshot(profile_ref)
        clothes_instance_ref = [i for i in snap0.get("instance_refs", []) if items.instance(i)["item_ref"] == CLOTHES_REF]
        self.assertEqual(1, len(clothes_instance_ref))
        clothes_instance_ref = clothes_instance_ref[0]

        equip = items.equip(profile_ref, clothes_instance_ref, "LEGS", event_ref="CD-EQUIP-LEGS")
        self.assertEqual("PASS", equip["status"])

        # --- before death: real, measured state -------------------------------
        projection_before = self.adapter._retention_projection()
        # DEATH_CLOTHES_PRESENT_BEFORE_DEATH
        self.assertIn(clothes_instance_ref, projection_before["equipped_clothes_refs"])
        snap_before = items.inventory_snapshot(profile_ref)
        self.assertEqual(clothes_instance_ref, snap_before.get("equipped", {}).get("LEGS"))

        # --- real authoritative death: same exhaustion/grace/defeat sequence
        # already proved in Stage16BDeathRetentionTests (save_death_water),
        # no forged death_result. ------------------------------------------
        traversal = self.command(
            "REPORT_WATER_TRAVERSAL",
            "CD-WATER-EXHAUST",
            {"request_ref": "CD-WATER-EXHAUST:UI", "depth_m": 8.0, "flow_speed_mps": 8.0, "distance_m": 100.0, "client_presentation_only": True},
        )
        self.assertEqual("PASS", traversal["status"])
        self.assertEqual(0.0, traversal["stamina"]["stamina_after"])
        grace_start = self.command(
            "REPORT_WATER_EXHAUSTION",
            "CD-GRACE-START",
            {"request_ref": "CD-GRACE-START:UI", "in_water": True, "client_presentation_only": True},
        )
        self.assertEqual("STAMINA_ZERO_GRACE", grace_start["exhaustion_snapshot"]["state"])
        _time.sleep(4.1)
        defeated = self.command(
            "REPORT_WATER_EXHAUSTION",
            "CD-GRACE-DEFEAT",
            {"request_ref": "CD-GRACE-DEFEAT:UI", "in_water": True, "client_presentation_only": True},
        )
        self.assertTrue(defeated["defeat_required"])
        death_event = defeated["death_event"]
        self.assertEqual("DEAD_AWAITING_RESPAWN", death_event["state"])
        retention = death_event["retention"]

        # --- after death: same instance, still equipped, never dropped --------
        # DEATH_CLOTHES_RETAINED / DEATH_CLOTHES_SAME_INSTANCE_RETAINED
        self.assertIn(clothes_instance_ref, retention["equipped_clothes_refs"])
        snap_after = items.inventory_snapshot(profile_ref)
        self.assertEqual(clothes_instance_ref, snap_after.get("equipped", {}).get("LEGS"))
        projection_after = self.adapter._retention_projection()
        self.assertIn(clothes_instance_ref, projection_after["equipped_clothes_refs"])

        matches_after = [i for i in snap_after.get("instance_refs", []) if items.instance(i)["item_ref"] == CLOTHES_REF]
        # DEATH_CLOTHES_NO_DUPLICATION
        self.assertEqual([clothes_instance_ref], matches_after)

        # DEATH_CLOTHES_NOT_DROPPED: still equipped on the player (checked
        # above) is itself the proof -- equipped instances are never swept
        # into a Bag by equip_new_bag()/drop_bag_for_death() (same rule
        # already relied on for armor retention).


class Stage16BClothesNonDevelopmentGuardTests(unittest.TestCase):
    """DEV_CLOTHES_DISABLED_OUTSIDE_DEVELOPMENT_PROFILE."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_clothes_nodev_")
        cls.root = pathlib.Path(cls._tmp.name)
        cfg = dataclasses.replace(build_config(cls.root), development_profile_bootstrap=False)
        cls.adapter = Stage16BAuthorityAdapter(cfg)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def test_01_no_definition_no_grant_outside_dev_profile(self) -> None:
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        with self.assertRaises(NotFoundError):
            items.definition(CLOTHES_REF)
        items.ensure_inventory(self.adapter.profile_ref)
        snap = items.inventory_snapshot(self.adapter.profile_ref)
        matches = [i for i in snap.get("instance_refs", []) if items.instance(i)["item_ref"] == CLOTHES_REF]
        self.assertEqual([], matches)


if __name__ == "__main__":
    unittest.main()
