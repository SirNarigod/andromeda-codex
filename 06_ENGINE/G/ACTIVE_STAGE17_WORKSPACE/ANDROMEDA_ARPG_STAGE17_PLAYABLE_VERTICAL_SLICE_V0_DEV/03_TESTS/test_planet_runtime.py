from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))

from living_runtime import LivingRuntime  # noqa: E402
from planet_runtime import PlanetSystem  # noqa: E402
from root_corruption_system import RootCorruptionSystem  # noqa: E402

MASTER = os.environ.get("ANDROMEDA_MASTER_RELEASE", "/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip")


@unittest.skipUnless(os.path.isfile(MASTER), "requires ANDROMEDA_MASTER_RELEASE zip (see MASTER path above)")
class PlanetRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = LivingRuntime(":memory:")
        world = self.runtime.create_world("test-owner", 7301)
        self.wid = world["world_instance_id"]

    def test_registers_all_requested_territories(self):
        planet = PlanetSystem(self.runtime, self.wid, MASTER, territory_ids=("TER-011", "TER-003"), seed=1201)
        self.assertEqual(planet.registered_territory_ids(), ["TER-003", "TER-011"])

    def test_territories_isolated_no_overwrite(self):
        planet = PlanetSystem(self.runtime, self.wid, MASTER, territory_ids=("TER-011", "TER-003"), seed=1201)
        name_011 = planet.territory_ref("TER-011").country_source.get("name")
        name_003 = planet.territory_ref("TER-003").country_source.get("name")
        self.assertNotEqual(name_011, name_003)
        self.assertNotEqual(
            planet.child_world_instance_id("TER-011"),
            planet.child_world_instance_id("TER-003"),
        )

    def test_subregion_count_is_positive_real_count(self):
        planet = PlanetSystem(self.runtime, self.wid, MASTER, territory_ids=("TER-011",), seed=1201)
        count = planet.subregion_count("TER-011")
        self.assertGreater(count, 0)
        self.assertIsInstance(count, int)

    def test_unknown_territory_rejected(self):
        planet = PlanetSystem(self.runtime, self.wid, MASTER, territory_ids=("TER-011",), seed=1201)
        with self.assertRaises(KeyError):
            planet.territory_ref("TER-999")

    def test_persistence_integrity_pass(self):
        planet = PlanetSystem(self.runtime, self.wid, MASTER, territory_ids=("TER-011", "TER-003"), seed=1201)
        result = planet.persistence_integrity()
        self.assertEqual(result["status"], "PASS")
        self.assertIn("TER-011", result["territories"])
        self.assertIn("TER-003", result["territories"])

    def test_rehydration_reuses_same_child_worlds_and_territory_list(self):
        planet1 = PlanetSystem(self.runtime, self.wid, MASTER, territory_ids=("TER-011", "TER-003"), seed=1201)
        child_011_first = planet1.child_world_instance_id("TER-011")
        subregions_first = planet1.subregion_count("TER-011")

        # segunda instancia, mesmo world_instance_id, SEM passar territory_ids
        planet2 = PlanetSystem(self.runtime, self.wid, MASTER, seed=1201)
        self.assertEqual(planet2.registered_territory_ids(), ["TER-003", "TER-011"])
        self.assertEqual(planet2.child_world_instance_id("TER-011"), child_011_first)
        self.assertEqual(planet2.subregion_count("TER-011"), subregions_first)

    def test_world_systems_shared_layer_attached(self):
        planet = PlanetSystem(self.runtime, self.wid, MASTER, territory_ids=("TER-011",), seed=1201)
        self.assertIsNotNone(planet.world_systems)

    def test_subregion_count_feeds_real_root_corruption_expansion(self):
        # Fase 6 (root_corruption_system.py) recebe total_subregions_in_territory
        # de fora - aqui a fonte real e planet.subregion_count(), nao um numero
        # manual, fechando o gap deixado deliberadamente aberto na fase 6.
        planet = PlanetSystem(self.runtime, self.wid, MASTER, territory_ids=("TER-003",), seed=1201)
        corruption = RootCorruptionSystem(self.runtime, self.wid)
        total = planet.subregion_count("TER-003")
        self.assertGreater(total, 0)
        result = corruption.corrupt_subregion(
            "SUB-003-999", "TER-003", intensity="BAIXA",
            total_subregions_in_territory=total, event_ref="EVT-REAL-1",
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["territory_corrupted_count"], 1)


if __name__ == "__main__":
    unittest.main()
