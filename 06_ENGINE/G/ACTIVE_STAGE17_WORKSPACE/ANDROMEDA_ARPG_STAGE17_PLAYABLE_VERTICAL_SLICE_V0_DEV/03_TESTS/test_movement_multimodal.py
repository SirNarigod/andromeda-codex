"""Testes de movement_multimodal.py - harness SEM MASTER_V2 zip (LivingRuntime(':memory:')
+ FakeCountry minimo), seguindo o plano aprovado. Roda em segundos, nao ~24s."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))

from living_runtime import LivingRuntime
from spatial_coordinates import SpatialCoordinateSystem
from streaming_system import ChunkStreamingSystem
from continuous_movement import ContinuousMovementSystem
from movement_multimodal import MultimodalMovementSystem


class FakeCountry:
    def __init__(self, seed=1201):
        self.seed = seed
        self.runtime = None
        self.world_instance_id = None
        self.world = {
            "country": {
                "id": "TER-TEST",
                "coordinate_center": {"longitude": 0.0, "latitude": 0.0, "altitude_m": 0.0},
                "bounding_region": [-1.0, -1.0, 1.0, 1.0],
                "states": [{
                    "id": "ST-1",
                    "blocks": [{
                        "id": "BLK-1", "state_id": "ST-1",
                        "bounding_region": [-1.0, -1.0, 1.0, 1.0],
                        "coordinate_center": {"longitude": 0.0, "latitude": 0.0, "altitude_m": 0.0},
                        "cities": [], "scene_objects": [], "dungeons": [], "subregions": [],
                    }],
                }],
            }
        }
        self._npcs = {
            "NPC-1": {"id": "NPC-1", "block_id": "BLK-1", "city_id": None, "scene_id": None, "dungeon_id": None, "state_id": "ST-1"},
        }

    def _all_npc_records(self):
        return list(self._npcs.values())

    def npc(self, npc_id):
        return self._npcs[npc_id]

    def block(self, block_id):
        for st in self.world["country"]["states"]:
            for b in st["blocks"]:
                if b["id"] == block_id:
                    return b
        raise KeyError(block_id)

    def city(self, city_id):
        for st in self.world["country"]["states"]:
            for b in st["blocks"]:
                for c in b.get("cities", []):
                    if c["id"] == city_id:
                        return c
        raise KeyError(city_id)

    def reconcile_country_inventory(self):
        return {"status": "PASS"}


class MultimodalMovementTests(unittest.TestCase):
    def setUp(self):
        self.runtime = LivingRuntime(":memory:")
        world = self.runtime.create_world("test-owner", 1201)
        self.wid = world["world_instance_id"]
        self.country = FakeCountry(seed=1201)
        self.spatial = SpatialCoordinateSystem(self.country)
        self.streaming = ChunkStreamingSystem(self.runtime, self.wid, self.country, self.spatial)
        self.movement = ContinuousMovementSystem(self.runtime, self.wid, self.country, self.spatial, self.streaming)
        self.multi = MultimodalMovementSystem(self.runtime, self.wid, self.country, self.spatial, self.streaming, self.movement)

    def test_ground_delegates_unchanged(self):
        # duas entidades identicas, uma movida direto pelo ContinuousMovementSystem,
        # outra via MultimodalMovementSystem.step_ground - evita reordenar chamadas
        # na MESMA entidade (o que confundiria campos de chunk/streaming dependentes
        # de ordem, que nao sao o que este teste quer provar).
        self.country._npcs["NPC-2"] = {"id": "NPC-2", "block_id": "BLK-1", "city_id": None, "scene_id": None, "dungeon_id": None, "state_id": "ST-1"}
        self.movement.bootstrap()
        self.multi.bootstrap()
        direct = self.movement.step_vector("NPC-1", dx=5.0, dy=0.0, duration_s=1.0, mode="WALK")
        via_multi = self.multi.step_ground("NPC-2", dx=5.0, dy=0.0, duration_s=1.0, mode="WALK")
        core_fields = ("status", "moved_m", "mode", "stamina", "iso_x_m", "iso_y_m", "geodetic",
                       "chunk_changed", "block_changed", "travel_ticks_advanced")
        for k in core_fields:
            self.assertEqual(direct[k], via_multi[k], f"campo {k} deveria ser identico")
        self.assertEqual(via_multi["domain"], "GROUND")

    def test_aquatic_shallow_wade(self):
        result = self.multi.step_aquatic("NPC-1", dx=2.0, dy=0.0, duration_s=1.0, depth_m=0.3)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["water_mode"], "WADE")
        self.assertEqual(result["domain"], "AQUATIC")
        self.assertLess(result["moved_m"], 1.6, "vadear deveria ser mais lento que WALK seco")

    def test_aquatic_deep_swim_goes_slightly_negative_altitude(self):
        result = self.multi.step_aquatic("NPC-1", dx=2.0, dy=0.0, duration_s=1.0, depth_m=2.0)
        self.assertEqual(result["water_mode"], "SWIM")
        self.assertLess(result["altitude_m"], 0.0)

    def test_submerged_sets_exact_depth_and_two_stamina_debits(self):
        result = self.multi.step_submerged("NPC-1", dx=1.0, dy=0.0, duration_s=1.0, target_depth_m=10.0)
        self.assertEqual(result["status"], "PASS")
        self.assertAlmostEqual(result["altitude_m"], -10.0)
        self.assertEqual(result["depth_state"], "DEEP")
        self.assertIsNotNone(result["stamina_cost_applied"])
        self.assertIsNotNone(result["pressure_cost_applied"])
        self.assertGreater(result["pressure_cost_applied"], 0.0)

    def test_submerged_depth_cap_rejected(self):
        result = self.multi.step_submerged("NPC-1", dx=1.0, dy=0.0, duration_s=1.0, target_depth_m=999.0)
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["reason"], "DEPTH_LIMIT_EXCEEDED")

    def test_flying_climbs_and_cruises(self):
        r1 = self.multi.step_flying("NPC-1", dx=10.0, dy=0.0, dz=5.0, duration_s=1.0, mode="CRUISE")
        self.assertEqual(r1["status"], "PASS")
        self.assertGreater(r1["altitude_m"], 0.0)
        self.assertEqual(r1["domain"], "FLYING")
        self.assertEqual(r1["stall_state"], "STABLE")
        r2 = self.multi.step_flying("NPC-1", dx=10.0, dy=0.0, dz=0.0, duration_s=1.0, mode="CRUISE")
        self.assertGreaterEqual(r2["altitude_m"], r1["altitude_m"])

    def test_flying_hover_never_stalls(self):
        # HOVER e voo parado sustentado (helicoptero/paira magico) - nunca estola,
        # mesmo mantido por varios ticks seguidos.
        self.multi.step_flying("NPC-1", dx=0.0, dy=0.0, dz=self.multi.VERTICAL_SPEED_MAX_MPS, duration_s=1.0, mode="HOVER")
        for _ in range(5):
            result = self.multi.step_flying("NPC-1", dx=0.0, dy=0.0, dz=0.0, duration_s=1.0, mode="HOVER")
        self.assertEqual(result["stall_state"], "STABLE")

    def test_flying_stall_then_auto_land(self):
        # sobe primeiro para ter altitude de sobra pra cair
        self.multi.step_flying("NPC-1", dx=1.0, dy=0.0, dz=self.multi.VERTICAL_SPEED_MAX_MPS, duration_s=1.0, mode="CRUISE")
        # fator de ambiente muito baixo (ex. vento contrario forte) derruba a velocidade
        # efetiva de CRUISE (16 m/s x 0.25 = 4 m/s) abaixo do minimo de sustentacao (5 m/s)
        result = None
        for _ in range(5):
            result = self.multi.step_flying("NPC-1", dx=1.0, dy=0.0, dz=0.0, duration_s=1.0, mode="CRUISE", environment_factor=0.25)
        self.assertIn(result["stall_state"], ("STALLING", "FALLING"))

    def test_land_forces_ground_domain(self):
        self.multi.step_flying("NPC-1", dx=5.0, dy=0.0, dz=5.0, duration_s=1.0, mode="CRUISE")
        result = self.multi.land("NPC-1")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["domain"], "GROUND")
        ds = self.multi.domain_state("NPC-1")
        self.assertEqual(ds["domain"], "GROUND")
        self.assertEqual(ds["stall_state"], "STABLE")

    def test_verify_passes_on_clean_fixture(self):
        self.multi.step_aquatic("NPC-1", dx=1.0, dy=0.0, duration_s=1.0, depth_m=0.3)
        result = self.multi.verify()
        self.assertEqual(result["status"], "PASS", result["failures"])


if __name__ == "__main__":
    unittest.main()
