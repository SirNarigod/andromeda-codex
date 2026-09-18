from __future__ import annotations

import pathlib
import tempfile
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
import sys

sys.path.insert(0, str(BACKEND_DIR))

from andromeda_authority_adapter import Stage16BAuthorityAdapter, canonical_json, sha256_text  # noqa: E402
from authority_config import AuthorityConfig, _resolve_master_path, verify_master  # noqa: E402


def build_config(root: pathlib.Path) -> AuthorityConfig:
    master = _resolve_master_path()
    return AuthorityConfig(
        master_release_path=master,
        master_release_sha256=verify_master(master),
        runtime_dir=PROJECT_ROOT / "01_RUNTIME",
        db_path=root / "world.sqlite",
        save_root=root / "saves",
        owner_scope="stage16a:item-definitions-verify-contract-test",
        world_seed=160801,
        player_class="WARRIOR",
        development_profile_bootstrap=False,
    )


class Stage16AItemDefinitionsVerifyContractTests(unittest.TestCase):
    """Successor V0_8_1 fix: ARPGItemCore.verify()'s catalog-membership check.

    Isolated world (own adapter), never shared with any other suite. Only
    ARPGItemCore.verify() itself and the schema/tables it already reads/writes
    are exercised -- nothing here disables triggers or mutates a protected
    row; "missing" and "extra" scenarios are fabricated additively (new rows
    only), the same discipline used everywhere else in this project.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16a_verify_contract_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session = "S16A-VERIFY-CONTRACT"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    # ------------------------------------------------------------------ helpers

    def _items(self):
        return self.adapter._engine.items_arpg(self.adapter.world_instance_id)

    def _conn(self):
        return self.adapter._engine.runtime.conn

    def _insert_commerce_ref(self, item_ref: str) -> None:
        """Additive-only: register a synthetic ref in commerce_catalog_snapshots
        with no corresponding arpg_item_definitions row, to fabricate the
        'missing' scenario without ever deleting/updating a real, protected row.
        """
        payload = {"id": item_ref, "name": "Synthetic Test Commerce Ref", "category": "TEST_ONLY"}
        text = canonical_json(payload)
        h = sha256_text(text)
        conn = self._conn()
        with self.adapter._engine.runtime._write_lock:
            conn.execute(
                "INSERT INTO commerce_catalog_snapshots(item_ref,item_kind,source_path,payload_json,payload_hash) VALUES(?,?,?,?,?)",
                (item_ref, "GAMEPLAY_DERIVED", "TEST_FABRICATED_MISSING_REF", text, h),
            )

    def _insert_extra_definition(
        self,
        item_ref: str,
        *,
        source_kind: str = "STAGE16B_TEST_PROVIDER_HONEST",
        stack_max: int = 10,
        payload_item_ref_override: str | None = None,
        payload_hash_override: str | None = None,
    ) -> None:
        """Additive-only: insert one extra, schema-complete definition row for a
        ref that is NOT in commerce_catalog_snapshots -- exactly the shape a
        legitimate independent provider (Stage09/Stage13/future Stage16B) uses,
        with an honest, arbitrary, non-STAGE09_/STAGE13_ source_kind.
        """
        payload = {
            "item_ref": payload_item_ref_override or item_ref,
            "name": "Synthetic Test Provider Item",
            "item_kind": "MATERIAL",
            "source_kind": source_kind,
            "canonical_identity": False,
            "canonical_status": "STAGE16B_TEST_ONLY_NOT_CANON",
            "source_authority": "GAMEPLAY_DERIVED_DEV_SOURCE",
            "source_category": "TEST_ONLY",
            "stackable": stack_max > 1,
            "stack_max": stack_max,
            "unit_weight": 0.5,
            "equip_slots": [],
            "instance_policy": "STACK",
            "base_durability": 0.0,
            "quality_policy": "NOT_APPLICABLE",
            "rarity_policy": "COMMON_STACK",
            "rarity_display_names_authority": "GAMEPLAY_DERIVED_RENAMEABLE",
            "base_modifiers": {
                "damage_flat": 0.0, "damage_pct": 0.0, "armor_flat": 0.0,
                "accuracy_flat": 0.0, "evasion_flat": 0.0, "crit_chance_pct": 0.0,
                "attack_speed_pct": 0.0, "range_bonus_m": 0.0,
                "resistances": {"FIRE": 0.0, "COLD": 0.0, "LIGHTNING": 0.0, "TOXIC": 0.0, "ARCANE": 0.0},
            },
            "consumable_effect": None,
            "socket_support": {"supported": False, "capacity_by_rarity": {}, "augmentation_binding": "NOT_APPLICABLE"},
            "source_snapshot_hash": sha256_text(f"TEST:{item_ref}"),
            "art_dependency": "NONE_PLACEHOLDER_READY",
            "authority": "ANDROMEDA_STAGE16B_TEST_PROVIDER",
        }
        text = canonical_json(payload)
        h = payload_hash_override if payload_hash_override is not None else sha256_text(text)
        conn = self._conn()
        with self.adapter._engine.runtime._write_lock:
            conn.execute(
                "INSERT INTO arpg_item_definitions(item_ref,source_kind,source_authority,payload_json,payload_hash) VALUES(?,?,?,?,?)",
                (item_ref, source_kind, payload["source_authority"], text, h),
            )

    # ------------------------------------------------------------------ tests

    def test_A_full_catalog_no_extension_passes(self) -> None:
        items = self._items()
        report = items.verify()
        self.assertEqual("PASS", report["status"], report["failures"])
        self.assertNotIn(
            "ITEM_DEFINITION_CATALOG_COUNT_MISMATCH",
            report["failures"],
            "old count-based failure code must never appear again",
        )

    def test_B_full_catalog_plus_stage09_stage13_passes(self) -> None:
        # Instantiating (or reusing) the gathering/economy cores triggers their
        # own, unmodified, real definition providers (Stage09 fishing,
        # Stage13 culinary/economy projections) -- exactly the two the old
        # check special-cased by prefix.
        self.adapter._engine.gathering_arpg(self.adapter.world_instance_id)
        self.adapter._engine.economy_arpg(self.adapter.world_instance_id)
        items = self._items()
        report = items.verify()
        self.assertEqual("PASS", report["status"], report["failures"])
        source_kinds = {
            row["source_kind"]
            for row in self._conn().execute(
                "SELECT source_kind FROM arpg_item_definitions"
            ).fetchall()
        }
        self.assertTrue(
            any(str(k).startswith("STAGE09_") for k in source_kinds),
            "Stage09 fishing definition must be present for this test to be meaningful",
        )
        self.assertTrue(
            any(str(k).startswith("STAGE13_") for k in source_kinds),
            "Stage13 economy definition must be present for this test to be meaningful",
        )

    def test_C_honest_arbitrary_provider_extra_passes(self) -> None:
        self._insert_extra_definition("TEST-C-HONEST-PROVIDER-REF-001", source_kind="STAGE16B_TEST_PROVIDER_HONEST")
        items = self._items()
        report = items.verify()
        self.assertEqual("PASS", report["status"], report["failures"])
        # The real item core itself can read it back through the normal path.
        d = items.definition("TEST-C-HONEST-PROVIDER-REF-001")
        self.assertEqual("MATERIAL", d["item_kind"])

    def test_D_missing_commerce_definition_fails(self) -> None:
        self._insert_commerce_ref("TEST-D-MISSING-COMMERCE-REF-001")
        items = self._items()
        report = items.verify()
        self.assertEqual("FAIL", report["status"])
        self.assertTrue(
            any(f.startswith("ITEM_DEFINITION_CATALOG_REF_MISSING:") and "TEST-D-MISSING-COMMERCE-REF-001" in f for f in report["failures"]),
            report["failures"],
        )

    def test_E_missing_commerce_plus_extra_provider_still_fails(self) -> None:
        # This is the exact class of bug the old count-only check could mask:
        # one commerce ref missing PLUS one legitimate non-catalog provider
        # extra numerically cancel out under a pure count comparison. The
        # set-difference check must not be fooled by that cancellation.
        self._insert_commerce_ref("TEST-E-MISSING-COMMERCE-REF-001")
        self._insert_extra_definition("TEST-E-HONEST-PROVIDER-REF-001", source_kind="STAGE16B_TEST_PROVIDER_HONEST_E")
        items = self._items()
        report = items.verify()
        self.assertEqual("FAIL", report["status"])
        self.assertTrue(
            any(f.startswith("ITEM_DEFINITION_CATALOG_REF_MISSING:") and "TEST-E-MISSING-COMMERCE-REF-001" in f for f in report["failures"]),
            report["failures"],
        )

    def test_F_invalid_hash_in_provider_extra_still_fails(self) -> None:
        self._insert_extra_definition(
            "TEST-F-BAD-HASH-REF-001",
            source_kind="STAGE16B_TEST_PROVIDER_BADHASH",
            payload_hash_override="0" * 64,
        )
        items = self._items()
        report = items.verify()
        self.assertEqual("FAIL", report["status"])
        self.assertIn("ITEM_DEFINITION_HASH:TEST-F-BAD-HASH-REF-001", report["failures"])

    def test_G_divergent_payload_item_ref_still_fails(self) -> None:
        self._insert_extra_definition(
            "TEST-G-REF-MISMATCH-001",
            source_kind="STAGE16B_TEST_PROVIDER_REFMISMATCH",
            payload_item_ref_override="TEST-G-REF-MISMATCH-WRONG-001",
        )
        items = self._items()
        report = items.verify()
        self.assertEqual("FAIL", report["status"])
        self.assertIn("ITEM_DEFINITION_REF:TEST-G-REF-MISMATCH-001", report["failures"])

    def test_H_stack_max_below_one_still_fails(self) -> None:
        self._insert_extra_definition(
            "TEST-H-STACK-MAX-ZERO-001",
            source_kind="STAGE16B_TEST_PROVIDER_STACKMAX",
            stack_max=0,
        )
        items = self._items()
        report = items.verify()
        self.assertEqual("FAIL", report["status"])
        self.assertIn("ITEM_STACK_MAX:TEST-H-STACK-MAX-ZERO-001", report["failures"])


class Stage16AItemDefinitionsProviderResumeTests(unittest.TestCase):
    """Section 8: the exact scenario that blocked the CLOTHES overlay attempt.

    An honest, arbitrary, non-STAGE09_/STAGE13_ provider definition must
    coexist with the real commerce catalog and survive boot -> world
    persistence -> a fresh resume_world() (a new process/adapter instance
    against the same on-disk world) without ITEM_DEFINITION_CATALOG_COUNT_
    MISMATCH or any equivalent failure. This test never adds the definition
    to the canonical catalog or to Godot -- it only proves the provider
    architecture itself, isolated from CLOTHES.
    """

    def test_honest_provider_extra_survives_boot_then_resume_world(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="s16a_verify_resume_")
        try:
            root = pathlib.Path(tmp.name)
            config = build_config(root)

            first = Stage16BAuthorityAdapter(config)
            first.bind_session("S16A-VERIFY-RESUME-FIRST")
            items_first = first._engine.items_arpg(first.world_instance_id)
            text = canonical_json({
                "item_ref": "TEST-RESUME-HONEST-PROVIDER-001",
                "name": "Synthetic Resume Provider Item",
                "item_kind": "MATERIAL",
                "source_kind": "STAGE16B_TEST_PROVIDER_RESUME",
                "canonical_identity": False,
                "canonical_status": "STAGE16B_TEST_ONLY_NOT_CANON",
                "source_authority": "GAMEPLAY_DERIVED_DEV_SOURCE",
                "source_category": "TEST_ONLY",
                "stackable": True,
                "stack_max": 10,
                "unit_weight": 0.5,
                "equip_slots": [],
                "instance_policy": "STACK",
                "base_durability": 0.0,
                "quality_policy": "NOT_APPLICABLE",
                "rarity_policy": "COMMON_STACK",
                "rarity_display_names_authority": "GAMEPLAY_DERIVED_RENAMEABLE",
                "base_modifiers": {
                    "damage_flat": 0.0, "damage_pct": 0.0, "armor_flat": 0.0,
                    "accuracy_flat": 0.0, "evasion_flat": 0.0, "crit_chance_pct": 0.0,
                    "attack_speed_pct": 0.0, "range_bonus_m": 0.0,
                    "resistances": {"FIRE": 0.0, "COLD": 0.0, "LIGHTNING": 0.0, "TOXIC": 0.0, "ARCANE": 0.0},
                },
                "consumable_effect": None,
                "socket_support": {"supported": False, "capacity_by_rarity": {}, "augmentation_binding": "NOT_APPLICABLE"},
                "source_snapshot_hash": sha256_text("TEST:TEST-RESUME-HONEST-PROVIDER-001"),
                "art_dependency": "NONE_PLACEHOLDER_READY",
                "authority": "ANDROMEDA_STAGE16B_TEST_PROVIDER",
            })
            h = sha256_text(text)
            with first._engine.runtime._write_lock:
                first._engine.runtime.conn.execute(
                    "INSERT INTO arpg_item_definitions(item_ref,source_kind,source_authority,payload_json,payload_hash) VALUES(?,?,?,?,?)",
                    ("TEST-RESUME-HONEST-PROVIDER-001", "STAGE16B_TEST_PROVIDER_RESUME", "GAMEPLAY_DERIVED_DEV_SOURCE", text, h),
                )
            report_first = items_first.verify()
            self.assertEqual("PASS", report_first["status"], report_first["failures"])
            world_instance_id = first.world_instance_id
            first.close()

            # Fresh adapter against the SAME on-disk world -- this is exactly
            # resume_world(), not a same-process reload/resync.
            second = Stage16BAuthorityAdapter(config)
            second.bind_session("S16A-VERIFY-RESUME-SECOND")
            self.assertEqual(world_instance_id, second.world_instance_id)
            items_second = second._engine.items_arpg(second.world_instance_id)
            definition = items_second.definition("TEST-RESUME-HONEST-PROVIDER-001")
            self.assertEqual("MATERIAL", definition["item_kind"])
            report_second = items_second.verify()
            self.assertEqual("PASS", report_second["status"], report_second["failures"])
            for f in report_second["failures"]:
                self.assertNotIn("ITEM_DEFINITION_CATALOG_COUNT_MISMATCH", f)
            second.close()
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
