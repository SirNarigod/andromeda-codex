from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))

from integrated_arpg_engine_v10 import IntegratedARPGEngineV10  # noqa: E402
from living_runtime import ValidationError  # noqa: E402

MASTER = os.environ.get("ANDROMEDA_MASTER_RELEASE", "/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip")

# Fase 7.2 (Stage17): teste do metodo aditivo unlock_boundary_route() em
# arpg_mobility_infrastructure_core.py. NAO testa travel() ponta-a-ponta
# cruzando pra TER-003 - _segment_zone_pair() so resolve DERIVED_LOCAL_CONNECTOR
# e CANON_LOCAL_ROAD_REF pra zonas Stage08 (que sao inteiramente locais a
# TER-011); uma rota CANONICAL_BOUNDARY_GATE nunca teve zona de destino
# mapeada, entao travel() continua rejeitando com SEGMENT_NOT_ZONE_RESOLVED
# mesmo destravada - isso e esperado e correto (nao e um bug do unlock), so
# muda o motivo da rejeicao de BOUNDARY_ROUTE_LOCKED pra SEGMENT_NOT_ZONE_RESOLVED,
# provando que o lock especifico foi removido sem inventar resolucao de zona
# cross-pais que nao existe. Conectar viagem fisica completa exigiria mapear
# zonas de TER-003 (fora do escopo desta fase) - fica documentado como gap
# real, nao implementado.


@unittest.skipUnless(os.path.isfile(MASTER), "requires ANDROMEDA_MASTER_RELEASE zip")
class BoundaryRouteUnlockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = IntegratedARPGEngineV10(":memory:", master_release_path=MASTER)
        r = cls.e.create_world("s17:boundary-test", 730201)
        cls.wid = r["world"]["world_instance_id"]
        cls.m = cls.e.mobility_arpg(cls.wid)

    def test_boundary_routes_start_locked(self):
        for ref in ("RTE-001", "RTE-003", "RTE-013"):
            self.assertTrue(self.m.segment(ref)["boundary_locked"])

    def test_unlock_rejects_non_boundary_route(self):
        with self.assertRaises(ValidationError):
            self.m.unlock_boundary_route("SRTE-001", "TER-003")

    def test_unlock_rejects_unconfirmed_destination(self):
        result = self.m.unlock_boundary_route("RTE-001", "TER-002")
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["reason"], "DESTINATION_TERRITORY_NOT_CONFIRMED")
        self.assertTrue(self.m.segment("RTE-001")["boundary_locked"])  # inalterado

    def test_unlock_confirmed_route_flips_only_that_segment(self):
        result = self.m.unlock_boundary_route("RTE-003", "TER-003")
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(self.m.segment("RTE-003")["boundary_locked"])
        self.assertTrue(self.m.segment("RTE-001")["boundary_locked"])
        self.assertTrue(self.m.segment("RTE-013")["boundary_locked"])

    def test_travel_after_unlock_no_longer_boundary_locked(self):
        # profile/veiculo minimos so pra alcancar a checagem de lock em travel()
        profile = self.e.arpg(self.wid).create_profile(
            "s17:boundary-test", origin_mode="CREATED", display_name="BoundaryDriver"
        )["profile"]
        pref = profile["profile_ref"]
        vehicle = self.m.create_vehicle(pref, "VEH-PROFILE-SCOUT", event_ref="EVT-BND-VEH-1")["vehicle"]
        vref = vehicle["vehicle_ref"]
        self.m.board(pref, vref, event_ref="EVT-BND-BOARD-1", as_driver=True)

        before = self.m.travel(pref, vref, "RTE-003", event_ref="EVT-BND-TRAVEL-BEFORE")
        self.assertEqual(before["status"], "REJECTED")
        self.assertEqual(before["reason"], "BOUNDARY_ROUTE_LOCKED")

        self.m.unlock_boundary_route("RTE-003", "TER-003")

        after = self.m.travel(pref, vref, "RTE-003", event_ref="EVT-BND-TRAVEL-AFTER")
        self.assertEqual(after["status"], "REJECTED")
        # nao mais travado por fronteira - a rejeicao agora e por falta de
        # resolucao de zona cross-pais, um gap real e documentado, nao um bug.
        self.assertEqual(after["reason"], "SEGMENT_NOT_ZONE_RESOLVED")


if __name__ == "__main__":
    unittest.main()
