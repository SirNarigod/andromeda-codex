from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))

from living_runtime import ConflictError, LivingRuntime  # noqa: E402
from root_corruption_system import RootCorruptionSystem, risk_outcome  # noqa: E402


class RootCorruptionSystemTests(unittest.TestCase):
    def setUp(self):
        self.runtime = LivingRuntime(":memory:")
        world = self.runtime.create_world("test-owner", 4201)
        self.wid = world["world_instance_id"]
        self.sys = RootCorruptionSystem(self.runtime, self.wid)

    def test_seeds_10_subregions_from_gate(self):
        self.assertEqual(len(self.sys.corrupted_subregions()), 10)

    def test_seed_phase_is_alimentacao_silenciosa(self):
        self.assertEqual(self.sys.current_phase(), "ALIMENTACAO_SILENCIOSA")

    def test_ter_012_has_3_seeded_subregions(self):
        rows = self.sys.corrupted_subregions("TER-012")
        self.assertEqual(len(rows), 3)

    def test_expand_subregion_pass(self):
        result = self.sys.corrupt_subregion(
            "SUB-020-001", "TER-020", intensity="MEDIA",
            total_subregions_in_territory=5, event_ref="EVT-1",
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["territory_corrupted_count"], 1)

    def test_containment_principle_blocks_over_50_percent(self):
        self.sys.corrupt_subregion("SUB-020-001", "TER-020", intensity="MEDIA",
                                    total_subregions_in_territory=5, event_ref="EVT-1")
        self.sys.corrupt_subregion("SUB-020-002", "TER-020", intensity="ALTA",
                                    total_subregions_in_territory=5, event_ref="EVT-2")
        result = self.sys.corrupt_subregion("SUB-020-003", "TER-020", intensity="BAIXA",
                                             total_subregions_in_territory=5, event_ref="EVT-3")
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["reason"], "CONTAINMENT_PRINCIPLE_EXCEEDED")

    def test_no_territory_fully_corrupted_even_for_ter_012(self):
        result = self.sys.corrupt_subregion("SUB-012-999", "TER-012", intensity="ALTA",
                                             total_subregions_in_territory=3, event_ref="EVT-4")
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["reason"], "NO_TERRITORY_FULLY_CORRUPTED")

    def test_expand_idempotent_replay(self):
        r1 = self.sys.corrupt_subregion("SUB-021-001", "TER-021", intensity="BAIXA",
                                         total_subregions_in_territory=4, event_ref="EVT-5")
        r2 = self.sys.corrupt_subregion("SUB-021-001", "TER-021", intensity="BAIXA",
                                         total_subregions_in_territory=4, event_ref="EVT-5")
        self.assertFalse(r1["idempotent_replay"])
        self.assertTrue(r2["idempotent_replay"])

    def test_expand_conflicting_replay_raises(self):
        self.sys.corrupt_subregion("SUB-022-001", "TER-022", intensity="BAIXA",
                                    total_subregions_in_territory=4, event_ref="EVT-6")
        with self.assertRaises(ConflictError):
            self.sys.corrupt_subregion("SUB-022-001", "TER-022", intensity="ALTA",
                                        total_subregions_in_territory=4, event_ref="EVT-6")

    def test_expand_already_corrupted_subregion_rejected(self):
        result = self.sys.corrupt_subregion("SUB-012-001", "TER-012", intensity="BAIXA",
                                             total_subregions_in_territory=10, event_ref="EVT-7")
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["reason"], "SUBREGION_ALREADY_CORRUPTED")

    def test_advance_phase_one_step_pass(self):
        result = self.sys.advance_phase(requested_phase="CORRUPCAO", event_ref="EVT-P1")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(self.sys.current_phase(), "CORRUPCAO")

    def test_advance_phase_skip_rejected(self):
        result = self.sys.advance_phase(requested_phase="EMERGENCIA", event_ref="EVT-P2")
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["reason"], "PHASE_MUST_ADVANCE_ONE_STEP_AT_A_TIME")

    def test_advance_beyond_corrupcao_without_gate_rejected(self):
        self.sys.advance_phase(requested_phase="CORRUPCAO", event_ref="EVT-P3")
        result = self.sys.advance_phase(requested_phase="EMERGENCIA", event_ref="EVT-P4")
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["reason"], "NO_ROOT_PHASE_BEYOND_ALIMENTACAO_CORRUPCAO_WITHOUT_NEW_GATE")

    def test_advance_beyond_corrupcao_with_gate_override_pass(self):
        self.sys.advance_phase(requested_phase="CORRUPCAO", event_ref="EVT-P5")
        result = self.sys.advance_phase(requested_phase="EMERGENCIA", gate_override=True, event_ref="EVT-P6")
        self.assertEqual(result["status"], "PASS")

    def test_risk_outcome_bands(self):
        self.assertEqual(risk_outcome("BAIXA", 0.1), "SAFE")
        self.assertEqual(risk_outcome("BAIXA", 0.9), "CORRUPTION_RISK")
        self.assertEqual(risk_outcome("BAIXA", 0.99), "DEATH_RISK")
        self.assertEqual(risk_outcome("ALTA", 0.5), "CORRUPTION_RISK")

    def test_corruption_risk_roll_on_corrupted_subregion(self):
        result = self.sys.corruption_risk_roll("PLAYER-1", "SUB-012-001", roll=0.99, event_ref="EVT-R1")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["outcome"], "DEATH_RISK")

    def test_corruption_risk_roll_on_uncorrupted_subregion_rejected(self):
        result = self.sys.corruption_risk_roll("PLAYER-1", "SUB-999-999", roll=0.1, event_ref="EVT-R2")
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["reason"], "SUBREGION_NOT_CORRUPTED")

    def test_seed_is_not_reapplied_on_reconstruction(self):
        self.sys.corrupt_subregion("SUB-023-001", "TER-023", intensity="BAIXA",
                                    total_subregions_in_territory=4, event_ref="EVT-8")
        sys2 = RootCorruptionSystem(self.runtime, self.wid)
        self.assertEqual(len(sys2.corrupted_subregions()), 11)

    def test_verify_passes_on_clean_fixture(self):
        self.assertEqual(self.sys.verify()["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
