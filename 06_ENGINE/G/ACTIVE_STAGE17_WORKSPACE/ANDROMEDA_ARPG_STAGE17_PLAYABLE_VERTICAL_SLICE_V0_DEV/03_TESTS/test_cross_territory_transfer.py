"""Fase 8.3 (Stage17, 14/09): transferência de profile entre 2 motores
IntegratedARPGEngineV16A completos e independentes (1 por território)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))

from integrated_arpg_engine_v16a import IntegratedARPGEngineV16A  # noqa: E402
from cross_territory_transfer import transfer_profile  # noqa: E402

MASTER = os.environ.get("ANDROMEDA_MASTER_RELEASE", "/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip")


@unittest.skipUnless(os.path.isfile(MASTER), "requires ANDROMEDA_MASTER_RELEASE zip")
class CrossTerritoryTransferTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="s17_xfer_")
        self.tmp = Path(self._tmp.name)
        self.e011 = IntegratedARPGEngineV16A(
            ":memory:", master_release_path=MASTER, save_root=str(self.tmp / "a")
        )
        r011 = self.e011.create_world("xfer:ter011", 9001, load_relationships=False)
        self.wid011 = r011["world"]["world_instance_id"]
        self.e003 = IntegratedARPGEngineV16A(
            ":memory:", master_release_path=MASTER, save_root=str(self.tmp / "b")
        )
        r003 = self.e003.create_world(
            "xfer:ter003", 9002, load_relationships=False, country_territory_id="TER-003"
        )
        self.wid003 = r003["world"]["world_instance_id"]

    def tearDown(self):
        self._tmp.cleanup()

    def _make_traveler(self):
        p = self.e011.arpg(self.wid011).create_profile(
            "xfer:ter011", origin_mode="CREATED", display_name="Traveler"
        )["profile"]
        pref = p["profile_ref"]
        econ = self.e011.economy_arpg(self.wid011)
        econ.ensure_wallet(pref)
        econ._set_balance(pref, 777.0)
        items = self.e011.items_arpg(self.wid011)
        item_ref = items.runtime.conn.execute(
            "SELECT item_ref FROM arpg_item_definitions LIMIT 1"
        ).fetchone()["item_ref"]
        items.grant_item(pref, item_ref, 5, event_ref="XFER-SETUP-GRANT")
        return pref, item_ref

    def test_transfer_preserves_profile_ref_and_inventory_and_wallet(self):
        pref, item_ref = self._make_traveler()
        result = transfer_profile(self.e011, self.wid011, self.e003, self.wid003, pref)
        self.assertEqual("PASS", result["status"])
        self.assertFalse(result["idempotent_replay"])
        self.assertEqual({item_ref: 5}, result["transferred_stacks"])
        self.assertEqual(777.0, result["transferred_balance"])

        dest_profiles = [p["profile_ref"] for p in self.e003.arpg(self.wid003).list_profiles()]
        self.assertIn(pref, dest_profiles)
        self.assertEqual({item_ref: 5}, self.e003.items_arpg(self.wid003).inventory_snapshot(pref)["stacks"])
        self.assertEqual(777.0, self.e003.economy_arpg(self.wid003).wallet(pref)["balance"])

    def test_transfer_replay_is_idempotent(self):
        pref, _ = self._make_traveler()
        r1 = transfer_profile(self.e011, self.wid011, self.e003, self.wid003, pref)
        r2 = transfer_profile(self.e011, self.wid011, self.e003, self.wid003, pref)
        self.assertFalse(r1["idempotent_replay"])
        self.assertTrue(r2["idempotent_replay"])
        # replay nao duplica o item transferido
        stacks = self.e003.items_arpg(self.wid003).inventory_snapshot(pref)["stacks"]
        self.assertEqual(5, list(stacks.values())[0])

    def test_transfer_unknown_source_profile_rejected(self):
        result = transfer_profile(
            self.e011, self.wid011, self.e003, self.wid003,
            "rt:player_profile:00000000-0000-4000-8000-000000000000",
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("SOURCE_PROFILE_NOT_FOUND", result["reason"])


if __name__ == "__main__":
    unittest.main()
