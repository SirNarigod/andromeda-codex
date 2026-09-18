from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))

from vehicle_content_profiles import VehicleContentProfileIndex  # noqa: E402
from vehicle_movement import DEFAULT_HANDLING_BY_CLASS  # noqa: E402


class VehicleContentProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = VehicleContentProfileIndex()

    def test_loads_all_23_vehicles(self):
        self.assertEqual(len(self.idx.vehicle_ids()), 23)

    def test_all_profiles_use_a_known_vehicle_class(self):
        for vid in self.idx.vehicle_ids():
            profile = self.idx.profile_for(vid)
            self.assertIn(profile["vehicle_class"], DEFAULT_HANDLING_BY_CLASS)
            self.assertEqual(profile["handling"], DEFAULT_HANDLING_BY_CLASS[profile["vehicle_class"]])

    def test_all_profiles_have_positive_speed(self):
        for vid in self.idx.vehicle_ids():
            self.assertGreater(self.idx.profile_for(vid)["max_speed_mps"], 0)

    def test_the_3_engine_crossref_vehicles_use_real_source(self):
        expected = {"VEI-004": "ROAD_CARGO", "VEI-006": "SCOUT", "VEI-008": "ROAD_SERVICE"}
        for vid, expected_class in expected.items():
            profile = self.idx.profile_for(vid)
            self.assertEqual(profile["source"], "engine_crossref")
            self.assertEqual(profile["vehicle_class"], expected_class)

    def test_other_20_vehicles_use_estimated_source(self):
        crossref_ids = {"VEI-004", "VEI-006", "VEI-008"}
        estimated = [vid for vid in self.idx.vehicle_ids() if vid not in crossref_ids]
        self.assertEqual(len(estimated), 20)
        for vid in estimated:
            self.assertEqual(self.idx.profile_for(vid)["source"], "estimated_from_content")

    def test_aquatic_terrestre_vehicles_map_to_watercraft(self):
        # VEI-002 Caravela de Navyr e VEI-007 Barcaca Encantada - category
        # TERRESTRE mas transport_mode NAVAL_SUPERFICIE/FLUVIAL -> AQUATIC/WATERCRAFT
        for vid in ("VEI-002", "VEI-007"):
            profile = self.idx.profile_for(vid)
            self.assertEqual(profile["domain"], "AQUATIC")
            self.assertEqual(profile["vehicle_class"], "WATERCRAFT")

    def test_legado_fora_da_grade_falls_back_to_ground_road_cargo(self):
        profile = self.idx.profile_for("VEI-005")
        self.assertEqual(profile["domain"], "GROUND")
        self.assertEqual(profile["vehicle_class"], "ROAD_CARGO")

    def test_flying_and_submerged_domains_use_correct_default_class(self):
        counts = {"AIRCRAFT": 0, "SUBMERSIBLE": 0}
        for vid in self.idx.vehicle_ids():
            profile = self.idx.profile_for(vid)
            if profile["domain"] == "FLYING":
                self.assertEqual(profile["vehicle_class"], "AIRCRAFT")
                counts["AIRCRAFT"] += 1
            elif profile["domain"] == "SUBMERGED":
                self.assertEqual(profile["vehicle_class"], "SUBMERSIBLE")
                counts["SUBMERSIBLE"] += 1
        self.assertGreater(counts["AIRCRAFT"], 0)
        self.assertGreater(counts["SUBMERSIBLE"], 0)


if __name__ == "__main__":
    unittest.main()
