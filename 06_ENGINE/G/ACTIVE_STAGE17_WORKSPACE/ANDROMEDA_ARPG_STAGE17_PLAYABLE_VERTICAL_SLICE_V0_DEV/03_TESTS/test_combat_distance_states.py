"""Testes de combat_distance_states.py - harness sem MASTER_V2 zip, com 2 NPCs
(precisa de posicoes reais via ContinuousMovementSystem)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))

from living_runtime import LivingRuntime
from spatial_coordinates import SpatialCoordinateSystem
from streaming_system import ChunkStreamingSystem
from continuous_movement import ContinuousMovementSystem
from combat_distance_states import CombatDistanceStateMachine, CLINCH, IN_FIGHTING, ECQ, MID_RANGE, LONG_RANGE


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
            "NPC-1": {"id": "NPC-1", "block_id": "BLK-1", "city_id": None, "scene_id": None, "dungeon_id": None, "state_id": "ST-1"},
            "NPC-2": {"id": "NPC-2", "block_id": "BLK-1", "city_id": None, "scene_id": None, "dungeon_id": None, "state_id": "ST-1"},
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


class CombatDistanceStateTests(unittest.TestCase):
    def setUp(self):
        self.runtime = LivingRuntime(":memory:")
        world = self.runtime.create_world("test-owner", 1201)
        self.wid = world["world_instance_id"]
        self.country = FakeCountryTwoNpcs()
        self.spatial = SpatialCoordinateSystem(self.country)
        self.streaming = ChunkStreamingSystem(self.runtime, self.wid, self.country, self.spatial)
        self.movement = ContinuousMovementSystem(self.runtime, self.wid, self.country, self.spatial, self.streaming)
        self.fsm = CombatDistanceStateMachine(self.runtime, self.wid, self.movement)

    def _put_npc2_at(self, target_x_m: float):
        # NPC-2 comeca em (0,0); anda em passos ate iso_x_m ~= target_x_m
        current = self.movement.state("NPC-2")["iso_x_m"]
        remaining = target_x_m - current
        if abs(remaining) < 1e-9:
            return
        self.movement.step_vector("NPC-2", dx=remaining, dy=0.0, duration_s=remaining / 4.8, mode="RUN")

    def test_band_progression_as_distance_increases(self):
        expectations = [(0.5, CLINCH), (2.0, IN_FIGHTING), (5.0, ECQ), (15.0, MID_RANGE), (30.0, LONG_RANGE)]
        for target_x, expected_band in expectations:
            self._put_npc2_at(target_x)
            result = self.fsm.update("NPC-1", "NPC-2")
            self.assertEqual(result["to_state"], expected_band, f"a {target_x}m deveria ser {expected_band}")

    def test_changed_flag_true_on_transition_false_within_band(self):
        self._put_npc2_at(0.5)
        r1 = self.fsm.update("NPC-1", "NPC-2")
        self.assertTrue(r1["changed"])  # primeira vez, from_state=None
        r2 = self.fsm.update("NPC-1", "NPC-2")
        self.assertFalse(r2["changed"])  # mesma banda (CLINCH), nao mudou
        self._put_npc2_at(5.0)
        r3 = self.fsm.update("NPC-1", "NPC-2")
        self.assertTrue(r3["changed"])  # CLINCH -> ECQ
        self.assertEqual(r3["from_state"], CLINCH)
        self.assertEqual(r3["to_state"], ECQ)

    def test_boundary_values_exact(self):
        cases = [(1.0, CLINCH), (1.0001, IN_FIGHTING), (2.75, IN_FIGHTING), (2.7501, ECQ),
                  (6.0, ECQ), (6.0001, MID_RANGE), (20.0, MID_RANGE), (20.0001, LONG_RANGE)]
        for dist, expected in cases:
            self.assertEqual(CombatDistanceStateMachine.classify(dist), expected, f"distancia {dist}")

    def test_pair_symmetry(self):
        self._put_npc2_at(3.0)
        r_ab = self.fsm.update("NPC-1", "NPC-2")
        r_ba = self.fsm.update("NPC-2", "NPC-1")
        self.assertEqual(r_ab["pair_ref"], r_ba["pair_ref"])

    def test_combat_modifiers_for_all_five_states(self):
        for state in (CLINCH, IN_FIGHTING, ECQ, MID_RANGE, LONG_RANGE):
            mods = CombatDistanceStateMachine.combat_modifiers_for_state(state)
            self.assertIsInstance(mods, dict)
            self.assertGreater(len(mods), 0)
        with self.assertRaises(KeyError):
            CombatDistanceStateMachine.combat_modifiers_for_state("NOT_A_REAL_STATE")

    def test_distance_modifiers_for_pair_matches_engine_modifier_envelope_shape(self):
        # achado da auditoria de 13/09: ARPGCombatCore ja consome modificadores de
        # outros subsistemas no formato {"modifiers": {...}} (self.engine.skills_arpg(
        # ...).combat_modifiers(profile_ref) / .items_arpg(...).equipment_modifiers(...)) -
        # este teste confirma que distance_modifiers_for_pair() produz o MESMO
        # envelope, pronto pra um accessor de engine futuro consumir sem adaptacao.
        self._put_npc2_at(5.0)
        result = self.fsm.distance_modifiers_for_pair("NPC-1", "NPC-2")
        self.assertEqual(result["state"], ECQ)
        self.assertIn("modifiers", result)
        self.assertEqual(result["modifiers"], CombatDistanceStateMachine.combat_modifiers_for_state(ECQ))
        self.assertAlmostEqual(result["distance_m"], 5.0, places=3)

    def test_verify_passes_and_detects_tampering(self):
        self._put_npc2_at(3.0)
        self.fsm.update("NPC-1", "NPC-2")
        self.assertEqual(self.fsm.verify()["status"], "PASS")
        pair_ref = self.fsm._pair_ref("NPC-1", "NPC-2")
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "UPDATE v17_combat_distance_pairs SET payload_hash='deadbeef' WHERE world_instance_id=? AND pair_ref=?",
                (self.wid, pair_ref),
            )
        with self.assertRaises(ValueError):
            self.fsm.state_for_pair("NPC-1", "NPC-2")

    def test_distance_matches_manual_hypot(self):
        self._put_npc2_at(7.0)
        import math
        a = self.movement.state("NPC-1")
        b = self.movement.state("NPC-2")
        expected = math.hypot(a["iso_x_m"] - b["iso_x_m"], a["iso_y_m"] - b["iso_y_m"])
        self.assertAlmostEqual(self.fsm.distance("NPC-1", "NPC-2"), expected, places=6)


if __name__ == "__main__":
    unittest.main()
