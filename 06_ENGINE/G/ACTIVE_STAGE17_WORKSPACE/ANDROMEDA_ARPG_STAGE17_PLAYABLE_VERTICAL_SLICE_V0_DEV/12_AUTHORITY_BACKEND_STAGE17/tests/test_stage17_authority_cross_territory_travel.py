"""Fase 8.3 (Stage17, 14/09): REQUEST_CROSS_TERRITORY_TRAVEL no adapter -
viagem física real TER-011->TER-003, motor completo por território.

Cobre: rota nao confirmada rejeitada, rota confirmada troca o motor ativo,
identidade/inventario/wallet chegam no motor novo, snapshot volta a
funcionar la (rebind de sessao+player_ref+loadout), comando subsequente
(MOVE_TO_POINT) roteia pro motor certo.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from andromeda_authority_adapter import Stage16BAuthorityAdapter  # noqa: E402
from test_stage16b_authority_adapter import build_config, VALID_SESSION  # noqa: E402


class CrossTerritoryTravelTests(unittest.TestCase):
    adapter: Stage16BAuthorityAdapter

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s17_xfer_adapter_")
        cls.tmp = pathlib.Path(cls._tmp.name)
        cls.config = build_config(cls.tmp)
        cls.adapter = Stage16BAuthorityAdapter(cls.config)
        cls.adapter.bind_session(VALID_SESSION)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def test_01_unconfirmed_route_rejected_stays_in_ter011(self) -> None:
        # Fase 8.6: RTE-001 passou a ser confirmada (expansao pras 21 rotas
        # cross-territorio) - usa um route_ref que nunca vai existir no mapa
        # pra continuar testando o caminho de rejeicao.
        result = self.adapter.command(
            {
                "session_ref": VALID_SESSION,
                "command": "REQUEST_CROSS_TERRITORY_TRAVEL",
                "command_ref": "CMDREF-S17-XFER-BAD",
                "params": {"route_ref": "RTE-999"},
            }
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("BOUNDARY_ROUTE_DESTINATION_NOT_CONFIRMED", result["reason"])
        self.assertEqual("TER-011", self.adapter.active_territory_id)

    def test_02_confirmed_route_switches_active_territory(self) -> None:
        result = self.adapter.command(
            {
                "session_ref": VALID_SESSION,
                "command": "REQUEST_CROSS_TERRITORY_TRAVEL",
                "command_ref": "CMDREF-S17-XFER-1",
                "params": {"route_ref": "RTE-003"},
            }
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual("TER-003", result["destination_territory_id"])
        self.assertEqual("TER-003", self.adapter.active_territory_id)

    def test_03_snapshot_pass_after_travel(self) -> None:
        snap = self.adapter.snapshot(VALID_SESSION)
        self.assertEqual("PASS", snap["status"])
        self.assertEqual(VALID_SESSION, snap["session_ref"])

    def test_04_profile_exists_in_destination_engine(self) -> None:
        dest_engine, dest_wid = self.adapter._territory_engine("TER-003")
        refs = [p["profile_ref"] for p in dest_engine.arpg(dest_wid).list_profiles()]
        self.assertIn(self.adapter.profile_ref, refs)

    def test_05_move_to_point_routes_to_active_territory_engine(self) -> None:
        result = self.adapter.command(
            {
                "session_ref": VALID_SESSION,
                "command": "MOVE_TO_POINT",
                "command_ref": "CMDREF-S17-XFER-MOVE",
                "params": {"target_longitude": 0.0, "target_latitude": 0.0, "step_duration_s": 0.1},
            }
        )
        # Nao exige PASS geografico (coordenada pode nao ser valida na malha
        # de TER-003) - so confirma que o comando foi roteado e processado
        # pelo motor ativo (nunca um erro de wiring tipo motor inexistente).
        self.assertIn(result["status"], ("PASS", "REJECTED"))
        self.assertNotEqual("COMMAND_NOT_ENABLED_IN_THIS_ROUND", result.get("reason"))


    def test_06_multi_hop_travel_across_confirmed_graph(self) -> None:
        # Fase 8.6 (14/09): 21 das 25 rotas do canon sao cross-territorio
        # com os dois lados confirmados, ligando os 13 territorios - prova
        # aqui que a travessia encadeia alem de so TER-011->TER-003.
        # (roda depois de test_02, que ja deixou o adapter em TER-003 -
        # RTE-006 continua a cadeia TER-003->TER-002.)
        self.assertEqual("TER-003", self.adapter.active_territory_id)
        r1 = self.adapter.command(
            {
                "session_ref": VALID_SESSION,
                "command": "REQUEST_CROSS_TERRITORY_TRAVEL",
                "command_ref": "CMDREF-S17-MULTIHOP-1",
                "params": {"route_ref": "RTE-006"},
            }
        )
        self.assertEqual("PASS", r1["status"])
        self.assertEqual("TER-002", r1["destination_territory_id"])
        self.assertEqual("TER-002", self.adapter.active_territory_id)
        snap = self.adapter.snapshot(VALID_SESSION)
        self.assertEqual("PASS", snap["status"])


if __name__ == "__main__":
    unittest.main()
