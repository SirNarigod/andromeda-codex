"""Fase 8.4 (Stage17, 14/09): migração agregada de fauna entre territórios
registrados no PlanetSystem (fase 7.2) - sistema novo e paralelo ao pipeline
de migração individual eco.migrate (esse continua servindo só fauna
modelada como entidade individual via EcologySystem, um modelo diferente)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))

from living_runtime import LivingRuntime, ConflictError  # noqa: E402
from planet_runtime import PlanetSystem  # noqa: E402
from fauna_territorial_migration import FaunaTerritorialMigration  # noqa: E402

MASTER = os.environ.get("ANDROMEDA_MASTER_RELEASE", "/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip")

_COMMON_SPECIES = "FAU-GRAZER"


@unittest.skipUnless(os.path.isfile(MASTER), "requires ANDROMEDA_MASTER_RELEASE zip")
class FaunaTerritorialMigrationTests(unittest.TestCase):
    def setUp(self):
        self.runtime = LivingRuntime(":memory:")
        world = self.runtime.create_world("test-owner", 8401)
        self.wid = world["world_instance_id"]
        self.planet = PlanetSystem(self.runtime, self.wid, MASTER, territory_ids=("TER-011", "TER-003"), seed=1201)
        self.mig = FaunaTerritorialMigration(self.planet)

    def test_migrate_moves_count_between_territories(self):
        before_source = self.mig.fauna_total("TER-011", _COMMON_SPECIES)
        before_dest = self.mig.fauna_total("TER-003", _COMMON_SPECIES)
        result = self.mig.migrate_fauna_delta(
            "TER-011", "TER-003", _COMMON_SPECIES, 5, event_ref="EVT-1"
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual(before_source - 5, self.mig.fauna_total("TER-011", _COMMON_SPECIES))
        self.assertEqual(before_dest + 5, self.mig.fauna_total("TER-003", _COMMON_SPECIES))

    def test_insufficient_source_rejected(self):
        result = self.mig.migrate_fauna_delta(
            "TER-011", "TER-003", _COMMON_SPECIES, 10**9, event_ref="EVT-2"
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("INSUFFICIENT_SOURCE_FAUNA", result["reason"])

    def test_no_matching_population_in_destination_rejected(self):
        # FAUNA_POOL e generico o bastante que toda especie de TER-011 tambem
        # existe em TER-003 nesta seed - simula o caso real (populacao
        # ausente num bioma especifico de destino) removendo as entradas
        # dessa especie so do lado de destino, sem tocar a geracao real.
        dest = self.planet.territory_ref("TER-003")
        for state in dest.world["country"]["states"]:
            for block in state["blocks"]:
                block["fauna"] = [f for f in block["fauna"] if f["species_ref"] != _COMMON_SPECIES]
        result = self.mig.migrate_fauna_delta(
            "TER-011", "TER-003", _COMMON_SPECIES, 1, event_ref="EVT-3"
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("NO_MATCHING_FAUNA_POPULATION_IN_DESTINATION", result["reason"])

    def test_replay_is_idempotent(self):
        r1 = self.mig.migrate_fauna_delta("TER-011", "TER-003", _COMMON_SPECIES, 3, event_ref="EVT-4")
        r2 = self.mig.migrate_fauna_delta("TER-011", "TER-003", _COMMON_SPECIES, 3, event_ref="EVT-4")
        self.assertFalse(r1["idempotent_replay"])
        self.assertTrue(r2["idempotent_replay"])
        # nao duplica - o total migrado permanece 3, nao 6
        self.assertEqual(r1["source_remaining"], r2["source_remaining"])

    def test_conflicting_replay_raises(self):
        self.mig.migrate_fauna_delta("TER-011", "TER-003", _COMMON_SPECIES, 3, event_ref="EVT-5")
        with self.assertRaises(ConflictError):
            self.mig.migrate_fauna_delta("TER-011", "TER-003", _COMMON_SPECIES, 4, event_ref="EVT-5")

    def test_same_source_and_dest_rejected(self):
        result = self.mig.migrate_fauna_delta("TER-011", "TER-011", _COMMON_SPECIES, 1, event_ref="EVT-6")
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("SOURCE_AND_DEST_MUST_DIFFER", result["reason"])

    def test_unregistered_territory_rejected(self):
        result = self.mig.migrate_fauna_delta("TER-011", "TER-999", _COMMON_SPECIES, 1, event_ref="EVT-7")
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("TERRITORY_NOT_REGISTERED", result["reason"])


if __name__ == "__main__":
    unittest.main()
