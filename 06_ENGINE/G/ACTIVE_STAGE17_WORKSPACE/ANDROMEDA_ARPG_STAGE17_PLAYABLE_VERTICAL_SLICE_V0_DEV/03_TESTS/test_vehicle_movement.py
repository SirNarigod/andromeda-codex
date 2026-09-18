"""Testes de vehicle_movement.py - harness leve (sem MASTER_V2 zip, sem
ContinuousMovementSystem/streaming/NPCs - so LivingRuntime + FakeCountry + spatial),
mesmo espirito de test_projectile_system.py (autocontido, nao depende de entity_ref
ja registrado como NPC)."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))

from living_runtime import LivingRuntime, ConflictError
from spatial_coordinates import SpatialCoordinateSystem
from vehicle_movement import (
    VehicleMovementSystem, map_transport_category_to_domain,
    MAX_DIVE_DEPTH_M, VERTICAL_SPEED_MAX_MPS, DEFAULT_HANDLING_BY_CLASS,
)


class FakeCountryMinimal:
    """So o que SpatialCoordinateSystem le - nem NPC, nem streaming, nem movimento."""
    def __init__(self):
        self.world = {"country": {"coordinate_center": {"longitude": 0.0, "latitude": 0.0, "altitude_m": 0.0},
                                   "states": []}}


class MappingTests(unittest.TestCase):
    def test_voador_maps_to_flying(self):
        self.assertEqual(map_transport_category_to_domain("VOADOR", "AEREA"), "FLYING")

    def test_submerso_maps_to_submerged(self):
        self.assertEqual(map_transport_category_to_domain("SUBMERSO", "SUBMERSA"), "SUBMERGED")

    def test_terrestre_estrada_maps_to_ground(self):
        self.assertEqual(map_transport_category_to_domain("TERRESTRE", "TERRESTRE_ESTRADA"), "GROUND")

    def test_terrestre_ferroviaria_maps_to_ground(self):
        self.assertEqual(map_transport_category_to_domain("TERRESTRE", "FERROVIARIA"), "GROUND")

    def test_vei002_caravela_naval_superficie_maps_to_aquatic_despite_terrestre_category(self):
        self.assertEqual(map_transport_category_to_domain("TERRESTRE", "NAVAL_SUPERFICIE"), "AQUATIC")

    def test_vei007_barcaca_fluvial_maps_to_aquatic_despite_terrestre_category(self):
        self.assertEqual(map_transport_category_to_domain("TERRESTRE", "FLUVIAL"), "AQUATIC")

    def test_vei005_legado_fora_da_grade_is_unsupported(self):
        with self.assertRaises(ValueError):
            map_transport_category_to_domain("LEGADO_FORA_DA_GRADE", "SUBTERRANEA")


class VehicleMovementSystemTests(unittest.TestCase):
    def setUp(self):
        self.runtime = LivingRuntime(":memory:")
        world = self.runtime.create_world("test-owner", 1201)
        self.wid = world["world_instance_id"]
        self.spatial = SpatialCoordinateSystem(FakeCountryMinimal())
        self.system = VehicleMovementSystem(self.runtime, self.wid, self.spatial)

    def _spawn(self, ref, domain, heading_deg=0.0, altitude_m=0.0, event_ref=None):
        return self.system.spawn(
            ref, origin={"longitude": 0.0, "latitude": 0.0, "altitude_m": altitude_m},
            domain=domain, heading_deg=heading_deg, event_ref=event_ref or f"SPAWN-{ref}",
        )

    def test_spawn_ground_at_origin(self):
        r = self._spawn("CAR-1", "GROUND")
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(r["domain"], "GROUND")
        self.assertAlmostEqual(r["altitude_m"], 0.0)
        self.assertAlmostEqual(r["current_speed_mps"], 0.0)
        self.assertAlmostEqual(r["heading_deg"], 0.0)

    def test_drive_straight_line_ground_matches_expected_displacement(self):
        self._spawn("CAR-1", "GROUND", heading_deg=0.0)
        r = self.system.drive("CAR-1", target_heading_deg=0.0, commanded_speed_mps=10.0, duration_s=1.0,
                               max_speed_mps=10.0, max_turn_rate_deg_s=60.0, accel_mps2=2.0, decel_mps2=5.0,
                               event_ref="DRV-1")
        self.assertEqual(r["status"], "PASS")
        # accel=2.0 m/s^2 * 1.0s -> so alcanca 2.0 m/s neste tick (nao pula pra 10)
        self.assertAlmostEqual(r["current_speed_mps"], 2.0, places=6)
        self.assertAlmostEqual(r["heading_deg"], 0.0, places=6)
        self.assertAlmostEqual(r["iso_x_m"], 2.0, places=6)
        self.assertAlmostEqual(r["iso_y_m"], 0.0, places=6)
        self.assertAlmostEqual(r["moved_m"], 2.0, places=6)

    def test_turning_clamped_to_max_rate(self):
        self._spawn("CAR-1", "GROUND", heading_deg=0.0)
        r = self.system.drive("CAR-1", target_heading_deg=90.0, commanded_speed_mps=0.0, duration_s=1.0,
                               max_speed_mps=10.0, max_turn_rate_deg_s=10.0, accel_mps2=2.0, decel_mps2=5.0,
                               event_ref="DRV-1")
        # pediu 90 graus mas so pode girar 10 graus/s * 1s = 10 graus neste tick
        self.assertAlmostEqual(r["heading_deg"], 10.0, places=6)

    def test_turning_reaches_target_when_within_rate(self):
        self._spawn("CAR-1", "GROUND", heading_deg=0.0)
        r = self.system.drive("CAR-1", target_heading_deg=5.0, commanded_speed_mps=0.0, duration_s=1.0,
                               max_speed_mps=10.0, max_turn_rate_deg_s=60.0, accel_mps2=2.0, decel_mps2=5.0,
                               event_ref="DRV-1")
        self.assertAlmostEqual(r["heading_deg"], 5.0, places=6)

    def test_turning_wraparound_takes_shortest_path(self):
        self._spawn("CAR-1", "GROUND", heading_deg=350.0)
        # de 350 para 10 -> diferenca real e +20 (via 360/0), nao -340
        r = self.system.drive("CAR-1", target_heading_deg=10.0, commanded_speed_mps=0.0, duration_s=1.0,
                               max_speed_mps=10.0, max_turn_rate_deg_s=60.0, accel_mps2=2.0, decel_mps2=5.0,
                               event_ref="DRV-1")
        self.assertAlmostEqual(r["heading_deg"], 10.0, places=6)

    def test_acceleration_ramp_multiple_ticks(self):
        self._spawn("CAR-1", "GROUND", heading_deg=0.0)
        speeds = []
        for i in range(3):
            r = self.system.drive("CAR-1", target_heading_deg=0.0, commanded_speed_mps=10.0, duration_s=1.0,
                                   max_speed_mps=10.0, max_turn_rate_deg_s=60.0, accel_mps2=2.0, decel_mps2=5.0,
                                   event_ref=f"DRV-{i}")
            speeds.append(r["current_speed_mps"])
        self.assertAlmostEqual(speeds[0], 2.0, places=6)
        self.assertAlmostEqual(speeds[1], 4.0, places=6)
        self.assertAlmostEqual(speeds[2], 6.0, places=6)

    def test_deceleration_uses_decel_rate_not_accel(self):
        self._spawn("CAR-1", "GROUND", heading_deg=0.0)
        self.system.drive("CAR-1", target_heading_deg=0.0, commanded_speed_mps=10.0, duration_s=1.0,
                           max_speed_mps=10.0, max_turn_rate_deg_s=60.0, accel_mps2=10.0, decel_mps2=5.0,
                           event_ref="DRV-UP")
        # agora a 10 m/s; comanda parar - deve usar decel_mps2=5.0, nao accel
        r = self.system.drive("CAR-1", target_heading_deg=0.0, commanded_speed_mps=0.0, duration_s=1.0,
                               max_speed_mps=10.0, max_turn_rate_deg_s=60.0, accel_mps2=10.0, decel_mps2=5.0,
                               event_ref="DRV-BRAKE")
        self.assertAlmostEqual(r["current_speed_mps"], 5.0, places=6)

    def test_reverse_capped_at_30_percent_of_max_speed(self):
        self._spawn("CAR-1", "GROUND", heading_deg=0.0)
        r = self.system.drive("CAR-1", target_heading_deg=0.0, commanded_speed_mps=-100.0, duration_s=1.0,
                               max_speed_mps=10.0, max_turn_rate_deg_s=60.0, accel_mps2=10.0, decel_mps2=10.0,
                               allow_reverse=True, event_ref="DRV-REV")
        self.assertAlmostEqual(r["current_speed_mps"], -3.0, places=6)
        self.assertLess(r["iso_x_m"], 0.0)  # andou pra tras

    def test_reverse_disallowed_clamps_to_zero(self):
        self._spawn("CAR-1", "GROUND", heading_deg=0.0)
        r = self.system.drive("CAR-1", target_heading_deg=0.0, commanded_speed_mps=-100.0, duration_s=1.0,
                               max_speed_mps=10.0, max_turn_rate_deg_s=60.0, accel_mps2=10.0, decel_mps2=10.0,
                               allow_reverse=False, event_ref="DRV-NOREV")
        self.assertAlmostEqual(r["current_speed_mps"], 0.0, places=6)

    def test_ground_altitude_stays_zero_ignoring_dz_intent(self):
        self._spawn("CAR-1", "GROUND")
        r = self.system.drive("CAR-1", target_heading_deg=0.0, commanded_speed_mps=1.0, duration_s=1.0,
                               max_speed_mps=10.0, max_turn_rate_deg_s=60.0, accel_mps2=10.0, decel_mps2=10.0,
                               dz_intent=100.0, event_ref="DRV-1")
        self.assertAlmostEqual(r["altitude_m"], 0.0)

    def test_aquatic_altitude_stays_at_surface(self):
        self._spawn("BOAT-1", "AQUATIC")
        r = self.system.drive("BOAT-1", target_heading_deg=0.0, commanded_speed_mps=1.0, duration_s=1.0,
                               max_speed_mps=10.0, max_turn_rate_deg_s=20.0, accel_mps2=1.0, decel_mps2=1.5,
                               dz_intent=-100.0, event_ref="DRV-1")
        self.assertAlmostEqual(r["altitude_m"], 0.0)

    def test_submerged_depth_capped_at_max_dive_depth(self):
        self._spawn("SUB-1", "SUBMERGED", altitude_m=-5.0)
        for i in range(10):
            r = self.system.drive("SUB-1", target_heading_deg=0.0, commanded_speed_mps=0.0, duration_s=1.0,
                                   max_speed_mps=5.0, max_turn_rate_deg_s=15.0, accel_mps2=0.8, decel_mps2=1.2,
                                   dz_intent=-100.0, event_ref=f"DRV-{i}")
        self.assertAlmostEqual(r["altitude_m"], -MAX_DIVE_DEPTH_M, places=6)

    def test_submerged_cannot_surface_above_zero(self):
        self._spawn("SUB-1", "SUBMERGED", altitude_m=-2.0)
        r = self.system.drive("SUB-1", target_heading_deg=0.0, commanded_speed_mps=0.0, duration_s=5.0,
                               max_speed_mps=5.0, max_turn_rate_deg_s=15.0, accel_mps2=0.8, decel_mps2=1.2,
                               dz_intent=100.0, event_ref="DRV-1")
        self.assertAlmostEqual(r["altitude_m"], 0.0, places=6)

    def test_flying_climbs_freely_bounded_by_vertical_speed_max(self):
        self._spawn("PLANE-1", "FLYING", altitude_m=0.0)
        r = self.system.drive("PLANE-1", target_heading_deg=0.0, commanded_speed_mps=0.0, duration_s=1.0,
                               max_speed_mps=50.0, max_turn_rate_deg_s=25.0, accel_mps2=2.0, decel_mps2=2.0,
                               dz_intent=100.0, event_ref="DRV-1")
        self.assertAlmostEqual(r["altitude_m"], VERTICAL_SPEED_MAX_MPS, places=6)

    def test_flying_cannot_go_below_ground(self):
        self._spawn("PLANE-1", "FLYING", altitude_m=0.0)
        r = self.system.drive("PLANE-1", target_heading_deg=0.0, commanded_speed_mps=0.0, duration_s=1.0,
                               max_speed_mps=50.0, max_turn_rate_deg_s=25.0, accel_mps2=2.0, decel_mps2=2.0,
                               dz_intent=-100.0, event_ref="DRV-1")
        self.assertAlmostEqual(r["altitude_m"], 0.0, places=6)

    def test_default_handling_by_class_scout(self):
        self._spawn("SCOUT-1", "GROUND")
        r = self.system.drive("SCOUT-1", target_heading_deg=0.0, commanded_speed_mps=100.0, duration_s=1.0,
                               max_speed_mps=38.0, vehicle_class="SCOUT", event_ref="DRV-1")
        self.assertAlmostEqual(r["current_speed_mps"], DEFAULT_HANDLING_BY_CLASS["SCOUT"]["accel_mps2"], places=6)

    def test_handling_params_required_without_class_or_explicit_values(self):
        self._spawn("CAR-1", "GROUND")
        r = self.system.drive("CAR-1", target_heading_deg=0.0, commanded_speed_mps=10.0, duration_s=1.0,
                               max_speed_mps=10.0, event_ref="DRV-1")
        self.assertEqual(r["status"], "REJECTED")
        self.assertEqual(r["reason"], "HANDLING_PARAMS_REQUIRED")

    def test_idempotent_replay_spawn(self):
        first = self._spawn("CAR-1", "GROUND", event_ref="SPAWN-X")
        second = self._spawn("CAR-1", "GROUND", event_ref="SPAWN-X")
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])

    def test_idempotent_replay_drive(self):
        self._spawn("CAR-1", "GROUND")
        args = dict(target_heading_deg=0.0, commanded_speed_mps=10.0, duration_s=1.0, max_speed_mps=10.0,
                    max_turn_rate_deg_s=60.0, accel_mps2=2.0, decel_mps2=5.0, event_ref="DRV-1")
        first = self.system.drive("CAR-1", **args)
        second = self.system.drive("CAR-1", **args)
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(first["iso_x_m"], second["iso_x_m"])

    def test_idempotent_conflict_different_payload(self):
        self._spawn("CAR-1", "GROUND")
        self.system.drive("CAR-1", target_heading_deg=0.0, commanded_speed_mps=10.0, duration_s=1.0,
                           max_speed_mps=10.0, max_turn_rate_deg_s=60.0, accel_mps2=2.0, decel_mps2=5.0,
                           event_ref="DRV-1")
        with self.assertRaises(ConflictError):
            self.system.drive("CAR-1", target_heading_deg=90.0, commanded_speed_mps=10.0, duration_s=1.0,
                               max_speed_mps=10.0, max_turn_rate_deg_s=60.0, accel_mps2=2.0, decel_mps2=5.0,
                               event_ref="DRV-1")

    def test_verify_passes_with_one_vehicle_per_domain_driving_different_directions(self):
        self._spawn("CAR-1", "GROUND")
        self._spawn("BOAT-1", "AQUATIC")
        self._spawn("SUB-1", "SUBMERGED", altitude_m=-3.0)
        self._spawn("PLANE-1", "FLYING")

        self.system.drive("CAR-1", target_heading_deg=0.0, commanded_speed_mps=8.0, duration_s=1.0,
                           max_speed_mps=42.0, vehicle_class="ROAD_SERVICE", event_ref="D1")
        self.system.drive("BOAT-1", target_heading_deg=90.0, commanded_speed_mps=5.0, duration_s=1.0,
                           max_speed_mps=15.0, vehicle_class="WATERCRAFT", event_ref="D2")
        self.system.drive("SUB-1", target_heading_deg=180.0, commanded_speed_mps=3.0, duration_s=1.0,
                           max_speed_mps=10.0, vehicle_class="SUBMERSIBLE", dz_intent=-1.0, event_ref="D3")
        self.system.drive("PLANE-1", target_heading_deg=270.0, commanded_speed_mps=20.0, duration_s=1.0,
                           max_speed_mps=60.0, vehicle_class="AIRCRAFT", dz_intent=2.0, event_ref="D4")

        result = self.system.verify()
        self.assertEqual(result["status"], "PASS", result["failures"])
        self.assertEqual(result["vehicles"], 4)

    def test_state_returns_hash_verified_snapshot_with_geodetic(self):
        self._spawn("CAR-1", "GROUND")
        self.system.drive("CAR-1", target_heading_deg=0.0, commanded_speed_mps=10.0, duration_s=1.0,
                           max_speed_mps=10.0, max_turn_rate_deg_s=60.0, accel_mps2=2.0, decel_mps2=5.0,
                           event_ref="DRV-1")
        s = self.system.state("CAR-1")
        self.assertEqual(s["vehicle_ref"], "CAR-1")
        self.assertIn("geodetic", s)
        self.assertAlmostEqual(s["iso_x_m"], 2.0, places=6)


if __name__ == "__main__":
    unittest.main()
