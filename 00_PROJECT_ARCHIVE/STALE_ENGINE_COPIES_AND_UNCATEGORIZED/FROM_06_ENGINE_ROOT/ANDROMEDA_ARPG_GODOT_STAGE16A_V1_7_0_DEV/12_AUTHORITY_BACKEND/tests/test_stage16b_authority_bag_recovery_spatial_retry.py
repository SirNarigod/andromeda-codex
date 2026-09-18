"""Corrective regression: REQUEST_BAG_RECOVERY retried on a non-DROPPED bag
must never raise INTERNAL_ADAPTER_ERROR.

Root cause (found live, reproduced in isolation, fixed in
andromeda_authority_adapter.py::_request_bag_recovery()):

  stage16a.recover_bag()'s non-OWNER branches (RECOVERED_FOREIGN, and every
  other terminal state reached via EQUIPPED/SUNK/etc.) set the bag's
  `position` to None -- there is no longer a real world position once a bag
  stops being a physically DROPPED object. But _request_bag_recovery() ran
  its own pre-core distance/collision precondition unconditionally, before
  ever asking the core whether the state was even recoverable. With
  `position=None`, `position.get("iso_x_m", math.inf)` fed math.inf into
  `physical_distance_m` on the REJECTED response payload. Starlette's
  JSONResponse.render() calls `json.dumps(..., allow_nan=False)`, which
  raises ValueError on that inf -- caught by stage16b_authority_api.py's
  generic `except Exception` handler and surfaced to Godot as
  "INTERNAL_ADAPTER_ERROR", masking what should have been a completely
  normal, core-decided BAG_NOT_RECOVERABLE rejection.

Fix: the adapter's spatial (distance/collision) precondition now only runs
when the bag is in one of the exact two states stage16a.recover_bag() itself
treats as spatially "DROPPED" (DROPPED_LAND / DROPPED_WATER_FLOATING) --
mirroring the core's own state check. For every other state, the adapter
defers straight to the core, which decides pass/reject on its own terms, as
it always has. This test module does NOT touch ownership semantics, TTL,
foreign-recovery semantics, or the 0.5m distance/collision gate for actually
DROPPED bags -- see the explicit non-regression assertions below.
"""

from __future__ import annotations

import dataclasses
import math
import pathlib
import sys
import tempfile
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "01_RUNTIME"))

from andromeda_authority_adapter import Stage16BAuthorityAdapter  # noqa: E402
from authority_config import AuthorityConfig, _resolve_master_path, verify_master  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402


def build_config(root: pathlib.Path, owner_scope: str) -> AuthorityConfig:
    master = _resolve_master_path()
    return AuthorityConfig(
        master_release_path=master,
        master_release_sha256=verify_master(master),
        runtime_dir=PROJECT_ROOT / "01_RUNTIME",
        db_path=root / "world.sqlite",
        save_root=root / "saves",
        owner_scope=owner_scope,
        world_seed=160840,
        player_class="WARRIOR",
        development_profile_bootstrap=True,
    )


def recovery_params(bag_ref: str) -> dict:
    return {
        "request_ref": f"{bag_ref}:UI",
        "bag_ref": bag_ref,
        "target_ref": bag_ref,
        "target_kind": "DROPPED_BAG",
        "physical_distance_m": 0.0,
        "client_range_candidate_m": 0.5,
        "client_guard_passed": True,
        "client_presentation_only": True,
    }


class Stage16BBagRecoverySpatialRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_bagrecov_spatial_retry_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(
            build_config(cls.root, "stage16b:bag-recovery-spatial-retry-test")
        )
        cls.session = "S16B-BAGRECOV-SPATIAL-RETRY"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {"session_ref": self.session, "command": "REQUEST_BAG_RECOVERY", "command_ref": ref, "params": params}
        )

    @staticmethod
    def assert_json_serializable(payload: dict) -> None:
        # Round-trip through the real Starlette response class used by
        # stage16b_authority_api.py -- proves the fix at the exact layer the
        # anomaly was originally observed in, not just at the adapter return.
        JSONResponse(status_code=200, content=payload)

    def _drop_npc_bag(self, label: str) -> tuple[str, str]:
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        npcs = [
            row["id"]
            for row in self.adapter._engine.country(self.adapter.world_instance_id)._all_npc_records()
            if row["id"] != self.adapter._player_ref
            and not stage16a.water_bag.ensure_carry_profile(row["id"]).get("equipped_bag_ref")
        ]
        owner = npcs[0]
        stage16a.water_bag.equip_new_bag(owner, event_ref=f"{label}-EQUIP")
        position = self.adapter._engine.movement(self.adapter.world_instance_id).state(
            self.adapter._player_ref
        )
        dropped = stage16a.drop_bag_for_death(
            owner, in_water=False,
            position={k: float(position.get(k, 0.0)) for k in ("iso_x_m", "iso_y_m", "altitude_m")},
            event_ref=f"{label}-DROP",
        )
        return dropped["bag_ref"], owner

    def test_01_recovered_foreign_retry_no_internal_error_core_decides(self) -> None:
        bag_ref, owner = self._drop_npc_bag("T01")
        first = self.command("T01-FOREIGN", recovery_params(bag_ref))
        self.assertEqual("ACCEPTED", first["result"])
        self.assertEqual("RECOVERED_FOREIGN", first["bag_projection"]["state"])

        retry = self.command("T01-RETRY", recovery_params(bag_ref))
        self.assertNotEqual("FAIL", retry["status"])
        self.assertNotEqual("INTERNAL_ADAPTER_ERROR", retry.get("reason"))
        self.assertEqual("BAG_NOT_RECOVERABLE", retry["reason"])
        self.assertEqual("REJECTED", retry["result"])
        self.assert_json_serializable(retry)

        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        bag_after = stage16a.water_bag.bag(bag_ref)
        self.assertEqual(owner, bag_after["property_owner_ref"])
        self.assertEqual(self.adapter.profile_ref, bag_after["foreign_recovery_ref"])
        self.assertEqual("RECOVERED_FOREIGN", bag_after["state"])
        self.assertEqual("rt:player_profile:" in bag_after["carrier_ref"], True)

    def test_02_owner_recovered_retry_no_internal_error_core_decides(self) -> None:
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        position = self.adapter._engine.movement(self.adapter.world_instance_id).state(
            self.adapter._player_ref
        )
        stage16a.water_bag.equip_new_bag(self.adapter.profile_ref, event_ref="T02-EQUIP")
        dropped = stage16a.drop_bag_for_death(
            self.adapter.profile_ref, in_water=False,
            position={k: float(position.get(k, 0.0)) for k in ("iso_x_m", "iso_y_m", "altitude_m")},
            event_ref="T02-DROP",
        )
        bag_ref = dropped["bag_ref"]

        first = self.command("T02-OWN", recovery_params(bag_ref))
        self.assertEqual("ACCEPTED", first["result"])
        self.assertEqual("RECOVERED", first["bag_projection"]["state"])

        retry = self.command("T02-RETRY", recovery_params(bag_ref))
        self.assertNotEqual("FAIL", retry["status"])
        self.assertNotEqual("INTERNAL_ADAPTER_ERROR", retry.get("reason"))
        self.assertEqual("BAG_NOT_RECOVERABLE", retry["reason"])
        self.assert_json_serializable(retry)

    def test_03_sunk_retry_no_internal_error_core_decides(self) -> None:
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        npcs = [
            row["id"]
            for row in self.adapter._engine.country(self.adapter.world_instance_id)._all_npc_records()
            if row["id"] != self.adapter._player_ref
        ]
        owner = npcs[0]
        stage16a.water_bag.equip_new_bag(owner, event_ref="T03-EQUIP")
        position = self.adapter._engine.movement(self.adapter.world_instance_id).state(
            self.adapter._player_ref
        )
        dropped = stage16a.drop_bag_for_death(
            owner, in_water=True,
            position={k: float(position.get(k, 0.0)) for k in ("iso_x_m", "iso_y_m", "altitude_m")},
            event_ref="T03-DROP",
        )
        bag_ref = dropped["bag_ref"]
        bag = stage16a.water_bag.bag(bag_ref)
        bag["state"] = "SUNK"
        bag["float_state"] = "SUNK"
        stage16a.water_bag._save_bag(bag)  # simulate the real TTL-expiry SUNK transition

        retry = self.command("T03-SUNK-RETRY", recovery_params(bag_ref))
        self.assertNotEqual("FAIL", retry["status"])
        self.assertNotEqual("INTERNAL_ADAPTER_ERROR", retry.get("reason"))
        self.assertEqual("BAG_NOT_RECOVERABLE", retry["reason"])
        self.assert_json_serializable(retry)

    def test_04_dropped_bag_far_still_rejected_distance_exceeded(self) -> None:
        # Non-regression: the 0.5m spatial gate must still apply, unweakened,
        # to a bag that IS actually DROPPED and spatially real.
        bag_ref, owner = self._drop_npc_bag("T04")
        self.adapter._engine.movement(self.adapter.world_instance_id).sync_to_geodetic(
            self.adapter._player_ref,
            {"longitude": 0.0, "latitude": 0.0, "altitude_m": 0.0},
            reason="T04-DISPLACE",
        )
        far = self.command("T04-FAR", recovery_params(bag_ref))
        self.assertEqual("REJECTED", far["result"])
        self.assertEqual("BAG_RECOVERY_DISTANCE_EXCEEDED", far["reason"])
        self.assertGreater(far["physical_distance_m"], 0.5)
        self.assert_json_serializable(far)

    def test_05_dropped_bag_close_still_recoverable(self) -> None:
        # Non-regression: a bag dropped at the player's own position (0.0m)
        # must still be recoverable -- proven directly, not inferred from
        # tests 01/02's "first" calls, so this scenario has its own signal.
        bag_ref, owner = self._drop_npc_bag("T05")
        close = self.command("T05-CLOSE", recovery_params(bag_ref))
        self.assertEqual("ACCEPTED", close["result"])
        self.assertEqual(0.0, close["physical_distance_m"])
        self.assertEqual("RECOVERED_FOREIGN", close["bag_projection"]["state"])
        self.assert_json_serializable(close)


if __name__ == "__main__":
    unittest.main()
