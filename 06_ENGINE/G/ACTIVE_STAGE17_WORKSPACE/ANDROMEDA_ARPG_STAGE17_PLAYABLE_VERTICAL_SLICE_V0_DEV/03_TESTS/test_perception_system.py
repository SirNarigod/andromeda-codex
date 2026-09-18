"""Testes de perception_system.py - nucleo puro sem harness + harness com 2
entidades (molde de test_combat_distance_states.py, FakeCountryTwoNpcs)."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))

from living_runtime import LivingRuntime
from spatial_coordinates import SpatialCoordinateSystem
from streaming_system import ChunkStreamingSystem
from continuous_movement import ContinuousMovementSystem
from perception_system import (
    PerceptionSystem, CircleObstacle, building_to_circle_obstacle,
    segment_intersects_circle, angle_within_fov, line_of_sight_clear,
    STATE_IGNORED, STATE_UNAWARE, STATE_SUSPICIOUS, STATE_SEEN,
)


class PureGeometryTests(unittest.TestCase):
    def test_segment_intersects_circle_obstacle_on_path(self):
        obstacle = CircleObstacle(ref="EST-1", center_x=5.0, center_y=0.0, radius_m=1.0)
        self.assertTrue(segment_intersects_circle((0.0, 0.0), (10.0, 0.0), obstacle))

    def test_segment_intersects_circle_obstacle_off_path(self):
        obstacle = CircleObstacle(ref="EST-1", center_x=5.0, center_y=10.0, radius_m=1.0)
        self.assertFalse(segment_intersects_circle((0.0, 0.0), (10.0, 0.0), obstacle))

    def test_building_to_circle_obstacle_radius_from_area(self):
        c = building_to_circle_obstacle("EST-1", 3.0, 4.0, area_m2=math.pi * 4)  # area de circulo raio 2
        self.assertAlmostEqual(c.radius_m, 2.0, places=6)
        self.assertEqual(c.center_x, 3.0)

    def test_angle_within_fov_directly_ahead(self):
        # observador olhando pro leste (heading=0), alvo diretamente a leste
        self.assertTrue(angle_within_fov((0.0, 0.0), 0.0, 110.0, (10.0, 0.0)))

    def test_angle_within_fov_behind_is_out_of_narrow_cone(self):
        # alvo atras do observador (heading=0, alvo a oeste) - fora de um cone de 110 graus
        self.assertFalse(angle_within_fov((0.0, 0.0), 0.0, 110.0, (-10.0, 0.0)))

    def test_angle_within_fov_wraparound_350_vs_10(self):
        # observador olhando pra 350 graus, alvo a 10 graus de bearing - diferenca real e 20, nao 340
        target_x, target_y = math.cos(math.radians(10)), math.sin(math.radians(10))
        self.assertTrue(angle_within_fov((0.0, 0.0), 350.0, 60.0, (target_x, target_y)))
        self.assertFalse(angle_within_fov((0.0, 0.0), 350.0, 30.0, (target_x, target_y)))

    def test_line_of_sight_clear_with_no_obstacles(self):
        self.assertTrue(line_of_sight_clear((0.0, 0.0), (10.0, 0.0), ()))

    def test_line_of_sight_blocked_by_one_obstacle(self):
        obstacle = CircleObstacle(ref="EST-1", center_x=5.0, center_y=0.0, radius_m=1.0)
        self.assertFalse(line_of_sight_clear((0.0, 0.0), (10.0, 0.0), (obstacle,)))


class FakeCountryTwoNpcs:
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
            "OBS-1": {"id": "OBS-1", "block_id": "BLK-1", "city_id": None, "scene_id": None, "dungeon_id": None, "state_id": "ST-1"},
            "TGT-1": {"id": "TGT-1", "block_id": "BLK-1", "city_id": None, "scene_id": None, "dungeon_id": None, "state_id": "ST-1"},
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


class PerceptionSystemTests(unittest.TestCase):
    def setUp(self):
        self.runtime = LivingRuntime(":memory:")
        world = self.runtime.create_world("test-owner", 1201)
        self.wid = world["world_instance_id"]
        self.country = FakeCountryTwoNpcs()
        self.spatial = SpatialCoordinateSystem(self.country)
        self.streaming = ChunkStreamingSystem(self.runtime, self.wid, self.country, self.spatial)
        self.movement = ContinuousMovementSystem(self.runtime, self.wid, self.country, self.spatial, self.streaming)
        self.perception = PerceptionSystem(self.runtime, self.wid, self.movement)

    def _put_target_at(self, x, y, mode="WALK"):
        current = self.movement.state("TGT-1")
        dx = x - current["iso_x_m"]
        dy = y - current["iso_y_m"]
        dist = math.hypot(dx, dy)
        if dist < 1e-9:
            return
        speed = self.movement.SPEEDS_MPS[mode]
        self.movement.step_vector("TGT-1", dx=dx, dy=dy, duration_s=dist / speed, mode=mode)

    def test_can_go_hostile_false_always_ignored(self):
        self._put_target_at(1.0, 0.0)
        r = self.perception.check("OBS-1", "TGT-1", observer_heading_deg=0.0, can_go_hostile=False)
        self.assertEqual(r["state"], STATE_IGNORED)
        self.assertIsNone(r["last_known_x_m"])

    def test_seen_within_range_and_fov_and_clear_los(self):
        self._put_target_at(5.0, 0.0)
        r = self.perception.check("OBS-1", "TGT-1", observer_heading_deg=0.0, can_go_hostile=True,
                                   vision_category="HUMANOID")
        self.assertEqual(r["state"], STATE_SEEN)
        self.assertAlmostEqual(r["last_known_x_m"], 5.0, places=3)

    def test_outside_fov_but_within_hearing_radius_running_is_suspicious(self):
        # alvo atras do observador (fora do cone de 110 graus), correndo -> raio de audicao 22m
        self._put_target_at(-5.0, 0.0, mode="RUN")
        r = self.perception.check("OBS-1", "TGT-1", observer_heading_deg=0.0, can_go_hostile=True,
                                   vision_category="HUMANOID")
        self.assertEqual(r["state"], STATE_SUSPICIOUS)
        self.assertAlmostEqual(r["last_known_x_m"], -5.0, places=3)

    def test_same_distance_crouching_is_unaware(self):
        # mesma distancia (5m atras), mas agachado -> raio de audicao so 3m, nao alcanca
        self._put_target_at(-5.0, 0.0, mode="CROUCH")
        r = self.perception.check("OBS-1", "TGT-1", observer_heading_deg=0.0, can_go_hostile=True,
                                   vision_category="HUMANOID")
        self.assertEqual(r["state"], STATE_UNAWARE)

    def test_obstacle_blocks_line_of_sight_even_within_cone_and_range(self):
        self._put_target_at(10.0, 0.0, mode="WALK")
        obstacle = building_to_circle_obstacle("EST-1", 5.0, 0.0, area_m2=math.pi * 1.0)  # raio 1m bem no meio do caminho
        r = self.perception.check("OBS-1", "TGT-1", observer_heading_deg=0.0, can_go_hostile=True,
                                   vision_category="HUMANOID", obstacles=(obstacle,))
        self.assertNotEqual(r["state"], STATE_SEEN)
        # 10m de distancia, WALK -> raio de audicao 10m, exatamente no limite -> SUSPICIOUS
        self.assertEqual(r["state"], STATE_SUSPICIOUS)

    def test_unaware_keeps_last_known_position_from_previous_detection(self):
        self._put_target_at(5.0, 0.0)  # visto primeiro
        seen = self.perception.check("OBS-1", "TGT-1", observer_heading_deg=0.0, can_go_hostile=True,
                                      vision_category="HUMANOID")
        self.assertEqual(seen["state"], STATE_SEEN)
        # agora o alvo foge pra fora do alcance/cone/audicao -> UNAWARE, mas mantem o rastro anterior
        # (duration_s maximo por passo e 10s - acumula 3 passos de WALK pra cobrir ~48m)
        for _ in range(3):
            move = self.movement.step_vector("TGT-1", dx=-20.0, dy=15.0, duration_s=10.0, mode="WALK")
            self.assertEqual(move["status"], "PASS")
        unaware = self.perception.check("OBS-1", "TGT-1", observer_heading_deg=0.0, can_go_hostile=True,
                                         vision_category="HUMANOID")
        self.assertEqual(unaware["state"], STATE_UNAWARE)
        self.assertAlmostEqual(unaware["last_known_x_m"], 5.0, places=3)

    def test_default_vision_profile_used_when_no_category_given(self):
        self._put_target_at(5.0, 0.0)
        r = self.perception.check("OBS-1", "TGT-1", observer_heading_deg=0.0, can_go_hostile=True)
        self.assertEqual(r["state"], STATE_SEEN)

    def test_explicit_vision_params_override_category(self):
        self._put_target_at(30.0, 0.0)  # alem do alcance HUMANOID (20m)
        r = self.perception.check("OBS-1", "TGT-1", observer_heading_deg=0.0, can_go_hostile=True,
                                   vision_category="HUMANOID", vision_range_m=50.0)
        self.assertEqual(r["state"], STATE_SEEN)

    def test_state_for_pair_matches_last_check(self):
        self._put_target_at(5.0, 0.0)
        self.perception.check("OBS-1", "TGT-1", observer_heading_deg=0.0, can_go_hostile=True)
        s = self.perception.state_for_pair("OBS-1", "TGT-1")
        self.assertEqual(s["state"], STATE_SEEN)

    def test_verify_passes_on_clean_fixture(self):
        self._put_target_at(5.0, 0.0)
        self.perception.check("OBS-1", "TGT-1", observer_heading_deg=0.0, can_go_hostile=True)
        result = self.perception.verify()
        self.assertEqual(result["status"], "PASS", result["failures"])
        self.assertEqual(result["pairs"], 1)


if __name__ == "__main__":
    unittest.main()
