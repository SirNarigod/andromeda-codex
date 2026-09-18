from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))

from living_runtime import ConflictError, LivingRuntime  # noqa: E402
from construction_placement_system import ConstructionPlacementSystem  # noqa: E402


class ConstructionPlacementSystemTests(unittest.TestCase):
    def setUp(self):
        self.runtime = LivingRuntime(":memory:")
        world = self.runtime.create_world("test-owner", 1201)
        self.wid = world["world_instance_id"]
        self.sys = ConstructionPlacementSystem(self.runtime, self.wid)

    def test_catalog_loads_all_24_pieces(self):
        self.assertEqual(len(self.sys.known_piece_ids()), 24)

    def test_place_piece_pass(self):
        result = self.sys.place_piece(
            "PLAYER-1", "BLD-FUNDACAO-T1", iso_x_m=10.0, iso_y_m=20.0,
            placement_ref="PLC-1", event_ref="EVT-1",
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["piece_type"], "FUNDACAO")
        self.assertEqual(result["tier"], "MADEIRA")
        self.assertFalse(result["idempotent_replay"])

    def test_place_piece_unknown_piece_rejected(self):
        result = self.sys.place_piece(
            "PLAYER-1", "BLD-NOT-REAL", iso_x_m=0.0, iso_y_m=0.0,
            placement_ref="PLC-2", event_ref="EVT-2",
        )
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["reason"], "UNKNOWN_PIECE_REF")

    def test_place_piece_duplicate_placement_ref_rejected(self):
        self.sys.place_piece("PLAYER-1", "BLD-CHAO-T1", iso_x_m=0.0, iso_y_m=0.0,
                              placement_ref="PLC-3", event_ref="EVT-3")
        result = self.sys.place_piece("PLAYER-1", "BLD-PAREDE-T1", iso_x_m=1.0, iso_y_m=1.0,
                                       placement_ref="PLC-3", event_ref="EVT-4")
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["reason"], "PLACEMENT_REF_ALREADY_IN_USE")

    def test_place_piece_idempotent_replay(self):
        r1 = self.sys.place_piece("PLAYER-1", "BLD-TETO-T1", iso_x_m=5.0, iso_y_m=5.0,
                                   placement_ref="PLC-5", event_ref="EVT-5")
        r2 = self.sys.place_piece("PLAYER-1", "BLD-TETO-T1", iso_x_m=5.0, iso_y_m=5.0,
                                   placement_ref="PLC-5", event_ref="EVT-5")
        self.assertFalse(r1["idempotent_replay"])
        self.assertTrue(r2["idempotent_replay"])
        self.assertEqual(r1["placement_ref"], r2["placement_ref"])

    def test_place_piece_conflicting_replay_raises(self):
        self.sys.place_piece("PLAYER-1", "BLD-PORTA-T1", iso_x_m=0.0, iso_y_m=0.0,
                              placement_ref="PLC-6", event_ref="EVT-6")
        with self.assertRaises(ConflictError):
            self.sys.place_piece("PLAYER-1", "BLD-PORTA-T1", iso_x_m=99.0, iso_y_m=99.0,
                                  placement_ref="PLC-6", event_ref="EVT-6")

    def test_remove_piece_by_owner_pass(self):
        self.sys.place_piece("PLAYER-1", "BLD-JANELA-T1", iso_x_m=0.0, iso_y_m=0.0,
                              placement_ref="PLC-7", event_ref="EVT-7")
        result = self.sys.remove_piece("PLC-7", requested_by_ref="PLAYER-1", event_ref="EVT-8")
        self.assertEqual(result["status"], "PASS")
        with self.assertRaises(KeyError):
            self.sys.state("PLC-7")

    def test_remove_piece_not_owner_rejected(self):
        self.sys.place_piece("PLAYER-1", "BLD-RAMPA-T1", iso_x_m=0.0, iso_y_m=0.0,
                              placement_ref="PLC-9", event_ref="EVT-9")
        result = self.sys.remove_piece("PLC-9", requested_by_ref="PLAYER-2", event_ref="EVT-10")
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["reason"], "NOT_OWNER")
        self.sys.state("PLC-9")  # ainda existe

    def test_remove_piece_not_found_rejected(self):
        result = self.sys.remove_piece("PLC-DOES-NOT-EXIST", requested_by_ref="PLAYER-1", event_ref="EVT-11")
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["reason"], "PLACEMENT_NOT_FOUND")

    def test_pieces_in_area_finds_nearby_and_excludes_far(self):
        self.sys.place_piece("PLAYER-1", "BLD-PILAR-T1", iso_x_m=0.0, iso_y_m=0.0,
                              placement_ref="PLC-NEAR", event_ref="EVT-NEAR")
        self.sys.place_piece("PLAYER-1", "BLD-PILAR-T2", iso_x_m=500.0, iso_y_m=500.0,
                              placement_ref="PLC-FAR", event_ref="EVT-FAR")
        found = self.sys.pieces_in_area(0.0, 0.0, radius_m=10.0)
        refs = {p["placement_ref"] for p in found}
        self.assertIn("PLC-NEAR", refs)
        self.assertNotIn("PLC-FAR", refs)

    def test_verify_passes_on_clean_fixture(self):
        self.sys.place_piece("PLAYER-1", "BLD-FUNDACAO-T3", iso_x_m=1.0, iso_y_m=1.0,
                              placement_ref="PLC-V", event_ref="EVT-V")
        self.assertEqual(self.sys.verify()["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
