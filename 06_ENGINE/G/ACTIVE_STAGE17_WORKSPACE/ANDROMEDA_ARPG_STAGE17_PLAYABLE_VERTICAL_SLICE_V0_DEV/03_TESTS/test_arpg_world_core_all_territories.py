"""Fase 8 (correção 14/09): ARPGWorldCore generalizado pros 13 territórios
reais do canon (não só TER-011/TER-003, que coincidiam em ter exatamente 2
biome_ids/geometria Polygon simples).

Achados reais que quebravam a generalização anterior:
1. biome_ids varia de 1 a 3 entradas entre territórios (não sempre 2) —
   regra: major=biome_ids[0], primary=biome_ids[-1] (1 bioma → os dois iguais).
2. geometry.type varia (Polygon/MultiPolygon/MultiLineString/...) — bbox
   agora extraído recursivamente, não assumindo Polygon simples.
3. Só TER-011/TER-003 têm uma entrada CIT-* em major_location_ids — os
   outros 11 só têm LOC-*; início canônico cai pra primeira location listada
   quando não há CIT-*.
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

ALL_TERRITORIES = tuple(f"TER-{i:03d}" for i in range(1, 14))


@unittest.skipUnless(os.path.isfile(MASTER), "requires ANDROMEDA_MASTER_RELEASE zip")
class AllTerritoriesWorldCoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="s17_allter_")
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_all_13_territories_bootstrap_and_verify_pass(self):
        failures = {}
        for i, territory_id in enumerate(ALL_TERRITORIES):
            e = IntegratedARPGEngineV16A(
                ":memory:", master_release_path=MASTER,
                save_root=str(self.tmp / territory_id),
            )
            try:
                r = e.create_world(
                    f"allter:{territory_id}", 9300 + i,
                    load_relationships=False, country_territory_id=territory_id,
                )
                wc = e.world_arpg(r["world"]["world_instance_id"])
                result = wc.verify()
                if result["status"] != "PASS":
                    failures[territory_id] = result.get("failures")
                elif not wc.list_zones():
                    failures[territory_id] = "NO_ZONES"
            except Exception as exc:  # noqa: BLE001
                failures[territory_id] = f"{type(exc).__name__}: {exc}"
        self.assertEqual({}, failures)

    def test_ter_011_still_matches_original_baseline(self):
        # Regressao explicita: TER-011 (o territorio original, ja coberto
        # por test_arpg_world_core_stage08.py) continua com os mesmos ids
        # de bioma/clima que sempre teve.
        e = IntegratedARPGEngineV16A(
            ":memory:", master_release_path=MASTER, save_root=str(self.tmp / "baseline011"),
        )
        r = e.create_world("allter:baseline011", 9399, load_relationships=False)
        wc = e.world_arpg(r["world"]["world_instance_id"])
        self.assertEqual("BIO-002", wc.MAJOR_BIOME_ID)
        self.assertEqual("BIO-008", wc.PRIMARY_BIOME_ID)
        self.assertEqual("CLM-002", wc.CLIMATE_ID)


if __name__ == "__main__":
    unittest.main()
