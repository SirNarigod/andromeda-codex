"""Fase 8.3 (Stage17, 14/09): ARPGWorldCore generalizado pra qualquer território.

PILOT_TERRITORY_ID/NAME e os ids de bioma/clima/hidrologia eram constantes de
classe fixas em TER-011 - agora sao auto-derivados do CountryScaleSystem ja
anexado ao mundo (country.country_territory_id). Este arquivo confirma: (a)
TER-011 continua 100% idêntico ao comportamento anterior (ja coberto também
por test_arpg_world_core_stage08.py, que passa inalterado); (b) um 2o
território real (TER-003) agora bootstrap e passa verify() limpo, sob seu
próprio world_instance_id.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))

from integrated_arpg_engine_v16a import IntegratedARPGEngineV16A  # noqa: E402

MASTER = os.environ.get("ANDROMEDA_MASTER_RELEASE", "/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip")


@unittest.skipUnless(os.path.isfile(MASTER), "requires ANDROMEDA_MASTER_RELEASE zip")
class MultiTerritoryWorldCoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="s17_multiter_")
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _engine(self, save_subdir: str) -> IntegratedARPGEngineV16A:
        return IntegratedARPGEngineV16A(
            ":memory:", master_release_path=MASTER, save_root=str(self.tmp / save_subdir)
        )

    def test_ter_011_default_unchanged(self):
        e = self._engine("ter011")
        r = e.create_world("multiter:ter011", 8301, load_relationships=False)
        wc = e.world_arpg(r["world"]["world_instance_id"])
        self.assertEqual("TER-011", wc.PILOT_TERRITORY_ID)
        self.assertEqual("Terras Livres", wc.PILOT_TERRITORY_NAME)
        self.assertEqual("BIO-002", wc.MAJOR_BIOME_ID)
        self.assertEqual("BIO-008", wc.PRIMARY_BIOME_ID)
        self.assertEqual("CLM-002", wc.CLIMATE_ID)
        self.assertEqual("PASS", wc.verify()["status"])

    def test_ter_003_real_territory_bootstraps_and_verifies(self):
        e = self._engine("ter003")
        r = e.create_world(
            "multiter:ter003", 8302, load_relationships=False, country_territory_id="TER-003"
        )
        wc = e.world_arpg(r["world"]["world_instance_id"])
        self.assertEqual("TER-003", wc.PILOT_TERRITORY_ID)
        self.assertGreater(len(wc.list_zones()), 0)
        result = wc.verify()
        self.assertEqual("PASS", result["status"], result.get("failures"))

    def test_ter_003_canonical_start_is_cit_002(self):
        e = self._engine("ter003start")
        r = e.create_world(
            "multiter:ter003start", 8303, load_relationships=False, country_territory_id="TER-003"
        )
        wc = e.world_arpg(r["world"]["world_instance_id"])
        _, start_wp = wc._find_start_zone()
        self.assertEqual("WP-CANON-CIT-002", start_wp)

    def test_ter_011_and_ter_003_isolated_under_separate_engines(self):
        e1 = self._engine("iso011")
        e2 = self._engine("iso003")
        r1 = e1.create_world("multiter:iso011", 8304, load_relationships=False)
        r2 = e2.create_world(
            "multiter:iso003", 8305, load_relationships=False, country_territory_id="TER-003"
        )
        wc1 = e1.world_arpg(r1["world"]["world_instance_id"])
        wc2 = e2.world_arpg(r2["world"]["world_instance_id"])
        self.assertNotEqual(wc1.PILOT_TERRITORY_ID, wc2.PILOT_TERRITORY_ID)
        self.assertNotEqual(len(wc1.list_zones()), 0)
        self.assertNotEqual(len(wc2.list_zones()), 0)


if __name__ == "__main__":
    unittest.main()
