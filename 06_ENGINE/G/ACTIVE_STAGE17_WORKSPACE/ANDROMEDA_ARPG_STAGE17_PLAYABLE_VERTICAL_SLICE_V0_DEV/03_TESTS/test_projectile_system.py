"""Testes de projectile_system.py - harness leve (sem MASTER_V2 zip, sem
ContinuousMovementSystem/streaming/NPCs - so LivingRuntime + FakeCountry + spatial)."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))

from living_runtime import LivingRuntime, ConflictError
from spatial_coordinates import SpatialCoordinateSystem
from projectile_system import (
    ProjectileParams, SphereObstacle, position_at, time_to_ground_impact,
    find_first_obstacle_hit, resolve_trajectory, ProjectileSystem,
)


class FakeCountryMinimal:
    """So o que SpatialCoordinateSystem le - nem NPC, nem streaming, nem movimento."""
    def __init__(self):
        self.world = {"country": {"coordinate_center": {"longitude": 0.0, "latitude": 0.0, "altitude_m": 0.0},
                                   "states": []}}


class PureTrajectoryTests(unittest.TestCase):
    def test_position_at_t0_is_origin(self):
        p = ProjectileParams(origin=(1.0, 2.0, 3.0), direction=(1.0, 0.0, 0.0), speed_mps=10.0, gravity_mps2=0.0)
        self.assertEqual(position_at(p, 0.0), (1.0, 2.0, 3.0))

    def test_flat_shot_no_gravity_travels_straight(self):
        p = ProjectileParams(origin=(0.0, 0.0, 0.0), direction=(1.0, 0.0, 0.0), speed_mps=10.0, gravity_mps2=0.0)
        x, y, z = position_at(p, 2.0)
        self.assertAlmostEqual(x, 20.0)
        self.assertAlmostEqual(y, 0.0)
        self.assertAlmostEqual(z, 0.0)

    def test_time_to_ground_impact_matches_independent_quadratic(self):
        p = ProjectileParams(origin=(0.0, 0.0, 10.0), direction=(1.0, 0.0, -0.3), speed_mps=5.0, gravity_mps2=9.8)
        t = time_to_ground_impact(p, ground_altitude_m=0.0)
        self.assertIsNotNone(t)
        # verificacao independente: recalcula a raiz da mesma quadratica na mao
        ux, uy, uz = p.unit_direction()
        a = -0.5 * p.gravity_mps2
        b = p.speed_mps * uz
        c = p.origin[2]
        disc = b * b - 4 * a * c
        t_expected = min(x for x in ((-b + math.sqrt(disc)) / (2 * a), (-b - math.sqrt(disc)) / (2 * a)) if x > 0)
        self.assertAlmostEqual(t, t_expected, places=6)
        # z(t) deveria realmente bater em 0
        _, _, z = position_at(p, t)
        self.assertAlmostEqual(z, 0.0, places=4)

    def test_obstacle_on_path_is_hit_off_path_is_missed(self):
        p = ProjectileParams(origin=(0.0, 0.0, 0.0), direction=(1.0, 0.0, 0.0), speed_mps=10.0, gravity_mps2=0.0)
        on_path = SphereObstacle(ref="OBST-ON", center=(5.0, 0.0, 0.0), radius_m=0.5)
        off_path = SphereObstacle(ref="OBST-OFF", center=(5.0, 10.0, 0.0), radius_m=0.5)
        hit = find_first_obstacle_hit(p, [off_path, on_path], t_max=5.0)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.obstacle_ref, "OBST-ON")

    def test_resolve_trajectory_max_range_when_nothing_hit(self):
        p = ProjectileParams(origin=(0.0, 0.0, 5.0), direction=(1.0, 0.0, 0.0), speed_mps=10.0, gravity_mps2=0.0)
        result = resolve_trajectory(p, ground_altitude_m=-1000.0, max_time_s=2.0)
        self.assertEqual(result.impact_type, "MAX_RANGE")
        self.assertFalse(result.hit)


class ProjectileSystemTests(unittest.TestCase):
    def setUp(self):
        self.runtime = LivingRuntime(":memory:")
        world = self.runtime.create_world("test-owner", 1201)
        self.wid = world["world_instance_id"]
        self.spatial = SpatialCoordinateSystem(FakeCountryMinimal())
        self.system = ProjectileSystem(self.runtime, self.wid, self.spatial)

    def test_fire_flat_reta_reaches_max_range(self):
        result = self.system.fire(event_ref="EV-1", origin={"longitude": 0.0, "latitude": 0.0, "altitude_m": 5.0},
                                   heading_deg=0.0, pitch_deg=0.0, speed_mps=50.0, gravity_mps2=0.0,
                                   ground_altitude_m=-1000.0, max_time_s=1.0, projectile_kind="WPN-FUZ")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["impact_type"], "MAX_RANGE")

    def test_fire_lobbed_arco_balistico_hits_ground(self):
        result = self.system.fire(event_ref="EV-2", origin={"longitude": 0.0, "latitude": 0.0, "altitude_m": 0.0},
                                   heading_deg=0.0, pitch_deg=45.0, speed_mps=20.0, gravity_mps2=9.8,
                                   ground_altitude_m=0.0, max_time_s=10.0, projectile_kind="WPN-ARR")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["impact_type"], "GROUND")
        self.assertGreater(result["impact_time_s"], 0.0)

    def test_fire_hits_obstacle(self):
        result = self.system.fire(
            event_ref="EV-3", origin={"longitude": 0.0, "latitude": 0.0, "altitude_m": 0.0},
            heading_deg=0.0, pitch_deg=0.0, speed_mps=10.0, gravity_mps2=0.0,
            obstacles=[{"ref": "NPC-TARGET", "longitude": 0.0, "latitude": 0.0, "radius_m": 1.0, "altitude_m": 0.0}],
            ground_altitude_m=-1000.0, max_time_s=5.0,
        )
        # obstaculo na origem geodetica (0,0) -> mesma posicao do tiro; deve ser atingido quase de imediato
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["impact_type"], "OBSTACLE")
        self.assertEqual(result["hit_obstacle_ref"], "NPC-TARGET")

    def test_invalid_pitch_rejected(self):
        result = self.system.fire(event_ref="EV-4", origin={"longitude": 0.0, "latitude": 0.0, "altitude_m": 0.0},
                                   heading_deg=0.0, pitch_deg=120.0, speed_mps=10.0)
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["reason"], "INVALID_PITCH_DEG")

    def test_idempotent_replay_same_payload(self):
        args = dict(event_ref="EV-5", origin={"longitude": 0.0, "latitude": 0.0, "altitude_m": 0.0},
                    heading_deg=0.0, pitch_deg=0.0, speed_mps=10.0, gravity_mps2=0.0, ground_altitude_m=-1000.0, max_time_s=1.0)
        first = self.system.fire(**args)
        second = self.system.fire(**args)
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(first["impact_type"], second["impact_type"])

    def test_idempotent_conflict_different_payload(self):
        self.system.fire(event_ref="EV-6", origin={"longitude": 0.0, "latitude": 0.0, "altitude_m": 0.0},
                          heading_deg=0.0, pitch_deg=0.0, speed_mps=10.0, gravity_mps2=0.0, ground_altitude_m=-1000.0, max_time_s=1.0)
        with self.assertRaises(ConflictError):
            self.system.fire(event_ref="EV-6", origin={"longitude": 0.0, "latitude": 0.0, "altitude_m": 0.0},
                              heading_deg=90.0, pitch_deg=0.0, speed_mps=10.0, gravity_mps2=0.0, ground_altitude_m=-1000.0, max_time_s=1.0)

    def test_verify_passes(self):
        self.system.fire(event_ref="EV-7", origin={"longitude": 0.0, "latitude": 0.0, "altitude_m": 0.0},
                          heading_deg=0.0, pitch_deg=0.0, speed_mps=10.0, gravity_mps2=0.0, ground_altitude_m=-1000.0, max_time_s=1.0)
        result = self.system.verify()
        self.assertEqual(result["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
