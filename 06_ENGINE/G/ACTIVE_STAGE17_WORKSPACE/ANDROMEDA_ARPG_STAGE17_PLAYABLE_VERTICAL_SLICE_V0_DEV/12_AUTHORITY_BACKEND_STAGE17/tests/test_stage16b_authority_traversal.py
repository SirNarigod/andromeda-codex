from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from andromeda_authority_adapter import Stage16BAuthorityAdapter  # noqa: E402
from authority_config import AuthorityConfig, _resolve_master_path, verify_master  # noqa: E402


def build_config(root: pathlib.Path) -> AuthorityConfig:
    master = _resolve_master_path()
    return AuthorityConfig(
        master_release_path=master,
        master_release_sha256=verify_master(master),
        runtime_dir=PROJECT_ROOT / "01_RUNTIME",
        db_path=root / "world.sqlite",
        save_root=root / "saves",
        owner_scope="stage16b:traversal-authority-test",
        world_seed=160825,
        player_class="WARRIOR",
        development_profile_bootstrap=True,
    )


class Stage16BAuthorityTraversalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_traversal_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.config = build_config(cls.root)
        cls.adapter = Stage16BAuthorityAdapter(cls.config)
        cls.session = "S16B-TRAVERSAL"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, params: dict, ref: str) -> dict:
        return self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REPORT_TRAVERSAL_SAMPLE",
                "command_ref": ref,
                "params": params,
            }
        )

    @staticmethod
    def sample(surface: str = "FIRM_GROUND", slope: float = 0.0, distance: float = 10.0) -> dict:
        return {
            "distance_m": distance,
            "slope_deg": slope,
            "surface_ref": surface,
            "ascending": True,
        }

    def stamina(self) -> float:
        return float(
            self.adapter._engine.movement(self.adapter.world_instance_id)
            .state(self.adapter._player_ref)["stamina"]
        )

    def test_01_snapshot_projects_authoritative_stamina(self) -> None:
        snapshot = self.adapter.snapshot(self.session)
        self.assertEqual(1.0, snapshot["stamina"]["fraction"])
        self.assertEqual("INACTIVE", snapshot["stamina"]["activity"])
        self.assertIn("SERVER_AUTHORITATIVE", snapshot["stamina"]["authority"])

    def test_02_surface_sample_consumes_stamina_through_stage16a(self) -> None:
        before = self.stamina()
        out = self.command(self.sample("ROAD_GOOD"), "S16B-TRAVERSAL-ROAD")
        after = self.stamina()
        self.assertEqual("PASS", out["status"])
        self.assertLess(after, before)
        self.assertEqual(after, out["stamina"]["stamina_after"])
        self.assertTrue(out["load_evaluated_server_side"])
        self.assertTrue(out["stamina_evaluated_server_side"])

    def test_03_bad_surface_costs_more_than_road(self) -> None:
        road = self.command(self.sample("ROAD_GOOD"), "S16B-TRAVERSAL-COMPARE-ROAD")
        mud = self.command(self.sample("MUD"), "S16B-TRAVERSAL-COMPARE-MUD")
        self.assertGreater(mud["traversal"]["stamina_cost"], road["traversal"]["stamina_cost"])
        self.assertLess(mud["traversal"]["effective_speed_mps"], road["traversal"]["effective_speed_mps"])

    def test_04_slope_changes_authoritative_cost(self) -> None:
        flat = self.command(self.sample("GRASS_FIELD", 0.0), "S16B-TRAVERSAL-FLAT")
        moderate = self.command(self.sample("GRASS_FIELD", 20.0), "S16B-TRAVERSAL-MODERATE")
        self.assertGreater(moderate["traversal"]["stamina_cost"], flat["traversal"]["stamina_cost"])
        self.assertEqual("MODERATE", moderate["traversal"]["slope"]["band"])

    def test_05_slope_above_32_is_blocked_without_stamina_change(self) -> None:
        before = self.stamina()
        out = self.command(self.sample("FIRM_GROUND", 32.0001), "S16B-TRAVERSAL-BLOCKED")
        after = self.stamina()
        self.assertEqual("REJECTED", out["status"])
        self.assertEqual("SLOPE_EXCEEDS_PRE_GODOT_WALKABLE_CANDIDATE", out["reason"])
        self.assertEqual(before, after)

    def test_06_client_cannot_supply_load_or_stamina(self) -> None:
        load = self.command({**self.sample(), "current_weight": 0.0}, "S16B-TRAVERSAL-FORGED-LOAD")
        stamina = self.command({**self.sample(), "stamina": 100.0}, "S16B-TRAVERSAL-FORGED-STAMINA")
        self.assertEqual("UNEXPECTED_COMMAND_PARAM", load["reason"])
        self.assertEqual("CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN", stamina["reason"])

    def test_07_duplicate_sample_does_not_double_charge(self) -> None:
        envelope = {
            "session_ref": self.session,
            "command": "REPORT_TRAVERSAL_SAMPLE",
            "command_ref": "S16B-TRAVERSAL-REPLAY",
            "params": self.sample("ROCKY_GROUND", 12.0, 3.0),
        }
        first = self.adapter.command(envelope)
        middle = self.stamina()
        second = self.adapter.command(envelope)
        after = self.stamina()
        self.assertEqual("PASS", first["status"])
        self.assertTrue(second["idempotent_replay"])
        self.assertTrue(second["replay_suppressed"])
        self.assertEqual(middle, after)

    def test_08_snapshot_reflects_the_persisted_core_value(self) -> None:
        snapshot = self.adapter.snapshot(self.session)
        self.assertAlmostEqual(self.stamina() / 100.0, snapshot["stamina"]["fraction"], places=8)
        self.assertEqual("CONSUMING", snapshot["stamina"]["activity"])


    def move(self, ref: str, mode: str = "WALK") -> dict:
        """One authoritative step forward. The movement core owns the outcome."""
        state = self.adapter._engine.movement(self.adapter.world_instance_id).state(
            self.adapter._player_ref
        )
        return self.adapter.command(
            {
                "session_ref": self.session,
                "command": "MOVE_TO_POINT",
                "command_ref": ref,
                "params": {
                    "iso_x_m": float(state["iso_x_m"]) + 5.0,
                    "iso_y_m": float(state["iso_y_m"]),
                    "duration_s": 0.25,
                    "mode": mode,
                },
            }
        )

    def test_10_walking_refills_stamina_in_the_authority(self) -> None:
        """G16B-08 'refills': the core restores stamina on a non-running step."""
        spent = self.command(self.sample("ROCKY_GROUND", 18.0, 40.0), "S16B-TRAVERSAL-DRAIN")
        self.assertEqual("PASS", spent["status"])
        drained = self.stamina()
        self.assertLess(drained, 100.0, "the sample must leave room to refill")

        recovered = drained
        for step in range(1, 13):
            out = self.move(f"S16B-TRAVERSAL-REFILL-{step:02d}")
            self.assertEqual("PASS", out["status"], out.get("reason"))
            recovered = self.stamina()
            if recovered > drained:
                break
        self.assertGreater(recovered, drained, "walking must refill authoritative stamina")
        self.assertLessEqual(recovered, 100.0, "refill must never exceed the core ceiling")

    def test_11_refill_is_projected_into_the_snapshot(self) -> None:
        before = self.adapter.snapshot(self.session)["stamina"]["fraction"]
        self.move("S16B-TRAVERSAL-REFILL-PROJECTION")
        after = self.adapter.snapshot(self.session)["stamina"]
        self.assertAlmostEqual(self.stamina() / 100.0, after["fraction"], places=8)
        self.assertGreaterEqual(after["fraction"], before)

    def test_12_client_cannot_ask_for_a_refill(self) -> None:
        """Recovery is a consequence of an authoritative step, never a client request."""
        before = self.stamina()
        out = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REPORT_TRAVERSAL_SAMPLE",
                "command_ref": "S16B-TRAVERSAL-FORGED-REFILL",
                "params": {**self.sample(), "stamina": 100.0},
            }
        )
        self.assertEqual("REJECTED", out["status"])
        self.assertEqual("CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN", out["reason"])
        self.assertEqual(before, self.stamina())


if __name__ == "__main__":
    unittest.main(verbosity=2)
