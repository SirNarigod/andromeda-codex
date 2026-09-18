from __future__ import annotations
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "01_RUNTIME"))
from arpg_terrain_traversal_streaming_core import TerrainTraversalStreamingCore


class TestStage16ATerrainTraversalStreaming(unittest.TestCase):
    def setUp(self):
        self.core = TerrainTraversalStreamingCore()

    def test_01_body_balance_absent(self):
        self.assertFalse(self.core.terrain_contract()["body_balance_mechanic"])

    def test_02_subtle_slope_walkable(self):
        r = self.core.slope_profile(4.0)
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(r["band"], "SUBTLE")

    def test_03_excessive_slope_blocked(self):
        r = self.core.slope_profile(33.0)
        self.assertEqual(r["status"], "BLOCKED")

    def test_04_uphill_costs_more_than_downhill(self):
        up = self.core.traversal_sample(distance_m=100, slope_deg=20, surface_ref="FIRM_GROUND", current_weight=10, weight_capacity=100, ascending=True)
        down = self.core.traversal_sample(distance_m=100, slope_deg=20, surface_ref="FIRM_GROUND", current_weight=10, weight_capacity=100, ascending=False)
        self.assertGreater(up["stamina_cost"], down["stamina_cost"])

    def test_05_heavy_load_costs_more(self):
        light = self.core.traversal_sample(distance_m=100, slope_deg=5, surface_ref="FIRM_GROUND", current_weight=10, weight_capacity=100)
        heavy = self.core.traversal_sample(distance_m=100, slope_deg=5, surface_ref="FIRM_GROUND", current_weight=90, weight_capacity=100)
        self.assertGreater(heavy["stamina_cost"], light["stamina_cost"])
        self.assertLess(heavy["effective_speed_mps"], light["effective_speed_mps"])

    def test_06_road_can_beat_shorter_bad_ground(self):
        r = self.core.route_compare([
            dict(distance_m=100, slope_deg=16, surface_ref="ROCKY_GROUND", current_weight=70, weight_capacity=100),
            dict(distance_m=120, slope_deg=5, surface_ref="ROAD_GOOD", current_weight=70, weight_capacity=100),
        ])
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(r["recommended_candidate_index"], 1)

    def test_07_unknown_surface_rejected(self):
        with self.assertRaises(ValueError):
            self.core.traversal_sample(distance_m=10, slope_deg=0, surface_ref="MAGIC_UNKNOWN", current_weight=0, weight_capacity=100)

    def test_08_zero_distance_zero_cost(self):
        r = self.core.traversal_sample(distance_m=0, slope_deg=0, surface_ref="FIRM_GROUND", current_weight=0, weight_capacity=100)
        self.assertEqual(r["stamina_cost"], 0)

    def test_09_area_sizes_are_variable(self):
        small = self.core.area_policy("POI")
        large = self.core.area_policy("REGION")
        self.assertLess(small["logical_extent_m"], large["logical_extent_m"])

    def test_10_large_area_partitioned(self):
        p = self.core.area_policy("REGION")
        self.assertTrue(p["large_area_partitioned"])
        self.assertLess(p["cell_size_m"], p["logical_extent_m"])

    def test_11_interior_is_single_cell(self):
        p = self.core.stream_plan(area_ref="HOUSE-1", area_scale="INTERIOR", active_cell_x=0, active_cell_y=0)
        self.assertEqual(p["total_logical_cells"], 1)
        self.assertEqual(p["loaded_scene_cell_count"], 1)

    def test_12_region_only_loads_local_ring(self):
        p = self.core.stream_plan(area_ref="REG-TEST", area_scale="REGION", active_cell_x=8, active_cell_y=8)
        self.assertEqual(p["loaded_scene_cell_count"], 9)
        self.assertGreater(p["systemic_unloaded_cell_count"], 0)

    def test_13_edge_stream_ring_clamped(self):
        p = self.core.stream_plan(area_ref="REG-TEST", area_scale="REGION", active_cell_x=0, active_cell_y=0)
        self.assertEqual(p["loaded_scene_cell_count"], 4)

    def test_14_unloaded_cells_continue_living(self):
        p = self.core.stream_plan(area_ref="REG-TEST", area_scale="REGION", active_cell_x=0, active_cell_y=0)
        self.assertEqual(p["living_lod_policy"], "UNLOADED_GODOT_CELLS_CONTINUE_SYSTEMIC_SIMULATION")

    def test_15_position_maps_deterministically(self):
        a = self.core.cell_for_local_position(area_ref="A", area_scale="SUBREGION", x_m=0, y_m=0)
        b = self.core.cell_for_local_position(area_ref="A", area_scale="SUBREGION", x_m=0, y_m=0)
        self.assertEqual(a, b)

    def test_16_outside_area_not_loaded(self):
        r = self.core.cell_for_local_position(area_ref="A", area_scale="POI", x_m=500, y_m=0)
        self.assertEqual(r["status"], "OUTSIDE_AREA")

    def test_17_candidate_physics_contract_requires_godot(self):
        p = self.core.terrain_contract()["physics_policy"]
        self.assertTrue(p["godot_validation_required"])
        self.assertGreater(p["max_step_height_m_candidate"], 0)

    def test_18_deterministic_signature(self):
        self.assertEqual(self.core.deterministic_signature(), TerrainTraversalStreamingCore().deterministic_signature())


if __name__ == "__main__":
    unittest.main(verbosity=2)
