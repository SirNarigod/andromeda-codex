"""Fase 8.7 (Stage17, 14/09): WorldSystems (economia/facções macro, fase
7.2) finalmente ligado ao adapter/jogador - achado da fase 8: nunca era
instanciado em produção antes desta fase, só isolado em teste.

Roda num LivingRuntime PRÓPRIO (separado de qualquer motor de território),
porque desde a fase 8.3 não existe mais "o" motor único do jogador - cada
território tem seu próprio motor completo e independente, e economia/facções
precisam sobreviver à troca de território ativo.
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


class EconomyFactionProjectionTests(unittest.TestCase):
    adapter: Stage16BAuthorityAdapter

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s17_econ_")
        cls.tmp = pathlib.Path(cls._tmp.name)
        cls.config = build_config(cls.tmp)
        cls.adapter = Stage16BAuthorityAdapter(cls.config)
        cls.adapter.bind_session(VALID_SESSION)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def test_01_projection_present_in_snapshot(self) -> None:
        snap = self.adapter.snapshot(VALID_SESSION)
        self.assertEqual("PASS", snap["status"])
        ef = snap["economy_faction_projection"]
        self.assertEqual("PASS", ef["status"])
        self.assertEqual("TER-011", ef["territory_id"])

    def test_02_planet_summary_reflects_real_canon_counts(self) -> None:
        snap = self.adapter.snapshot(VALID_SESSION)
        summary = snap["economy_faction_projection"]["planet_summary"]
        # Contagens reais confirmadas via WorldSystems.bootstrap_world_contextual
        # com o MASTER real: 34 rotas runtime, 7 fluxos, 14 populações, 3 facções.
        self.assertEqual(34, summary["routes"])
        self.assertEqual(7, summary["flows"])
        self.assertEqual(14, summary["populations"])
        self.assertEqual(3, summary["factions"])

    def test_03_ter011_has_no_local_faction_by_canon(self) -> None:
        # Confirmado real: as 3 facções do canon estão sediadas em
        # TER-001/TER-003/TER-010 - nenhuma em TER-011. Não é bug.
        snap = self.adapter.snapshot(VALID_SESSION)
        ef = snap["economy_faction_projection"]
        self.assertEqual([], ef["local_factions"])

    def test_04_food_pressure_scoped_to_active_territory(self) -> None:
        snap = self.adapter.snapshot(VALID_SESSION)
        pressure = snap["economy_faction_projection"]["food_pressure"]
        self.assertEqual("TER-011", pressure["territory_ref"])
        self.assertEqual("FOOD", pressure["category"])

    def test_05_projection_follows_player_across_territory_travel(self) -> None:
        result = self.adapter.command(
            {
                "session_ref": VALID_SESSION,
                "command": "REQUEST_CROSS_TERRITORY_TRAVEL",
                "command_ref": "CMDREF-S17-ECON-TRAVEL-1",
                "params": {"route_ref": "RTE-003"},
            }
        )
        self.assertEqual("PASS", result["status"])
        snap = self.adapter.snapshot(VALID_SESSION)
        ef = snap["economy_faction_projection"]
        self.assertEqual("TER-003", ef["territory_id"])
        # TER-003 tem FAC-002 sediada la, confirmado real.
        self.assertEqual(["FAC-002"], [f["faction_ref"] for f in ef["local_factions"]])
        # planet_summary nao muda so por trocar de territorio - e o mesmo
        # WorldSystems compartilhado, nunca recriado por travessia.
        self.assertEqual(34, ef["planet_summary"]["routes"])


if __name__ == "__main__":
    unittest.main()
