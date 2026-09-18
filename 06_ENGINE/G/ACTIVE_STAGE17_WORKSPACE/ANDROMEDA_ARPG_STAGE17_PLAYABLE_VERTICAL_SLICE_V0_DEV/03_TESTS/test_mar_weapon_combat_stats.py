from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))

from mar_weapon_combat_stats import MARWeaponCombatStatsIndex, compute_concrete_stats  # noqa: E402


class MARWeaponCombatStatsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = MARWeaponCombatStatsIndex()

    def test_loads_all_96_weapons(self):
        self.assertEqual(len(self.idx.weapon_ids()), 96)

    def test_ranged_firearm_has_full_concrete_stats(self):
        stats = self.idx.stats_for("WPN-FUZ-001")
        self.assertIn("damage", stats)
        self.assertIn("fire_rate_per_min", stats)
        self.assertIn("capacity", stats)
        self.assertIn(stats["fire_mode"], ("SEMI-AUTOMATICO", "RAJADA/AUTOMATICO"))

    def test_equipment_weapon_omits_damage_and_capacity(self):
        stats = self.idx.stats_for("WPN-TEC-009")  # Escudo Reativo Compacto - equipamento passivo
        self.assertNotIn("damage", stats)
        self.assertNotIn("fire_rate_per_min", stats)
        self.assertNotIn("capacity", stats)
        self.assertEqual(stats["fire_mode"], "N/A_EQUIPAMENTO_PASSIVO")

    def test_no_duplicate_concrete_stats_within_same_functional_family(self):
        result = self.idx.verify_no_duplicate_stats_within_family()
        self.assertEqual(result["status"], "PASS", result["collisions"])
        self.assertEqual(result["total_weapons"], 96)

    def test_higher_tier_increases_damage_for_same_power(self):
        base = {"physics": {"trajectory_type": "RETA"}, "stats": {"power": 50, "handling": 50, "utility": 50}}
        low = compute_concrete_stats("WPN-FUZ-900", {**base, "runification_tier": "R0"})
        high = compute_concrete_stats("WPN-FUZ-901", {**base, "runification_tier": "R3"})
        self.assertGreater(high["damage"], low["damage"])

    def test_corrupted_class_schema_fallback_via_corruption_affinity(self):
        # WPN-PRO/RAD nao tem runification_tier/class - so corruption_affinity
        weapon = {"physics": {"trajectory_type": "ARCO_BALÍSTICO"},
                  "stats": {"power": 60, "handling": 40, "utility": 30, "corruption_affinity": 90}}
        stats = compute_concrete_stats("WPN-PRO-099", weapon)
        self.assertEqual(stats["tier_index"], 3)  # 90/33 ~= 2.7 -> round -> 3

    def test_invalid_weapon_id_rejected(self):
        with self.assertRaises(ValueError):
            compute_concrete_stats("NOT-A-WEAPON-ID", {})


if __name__ == "__main__":
    unittest.main()
