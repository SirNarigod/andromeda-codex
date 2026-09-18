from __future__ import annotations

import pathlib
import tempfile
import time
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
import sys

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
        owner_scope="stage16b:save-death-water-authority-test",
        world_seed=160800,
        player_class="WARRIOR",
        development_profile_bootstrap=True,
    )


class Stage16BAuthoritySaveDeathWaterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_save_death_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.config = build_config(cls.root)
        cls.adapter = Stage16BAuthorityAdapter(cls.config)
        cls.session = "S16B-SAVE-DEATH"
        cls.adapter.bind_session(cls.session)
        cls.saved_position: dict = {}
        cls.restore_result: dict = {}
        cls.first_save_result: dict = {}
        cls.water_bag_ref = ""
        cls.water_drop_ref = ""

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    @classmethod
    def command(cls, name: str, ref: str, params: dict) -> dict:
        return cls.adapter.command(
            {
                "session_ref": cls.session,
                "command": name,
                "command_ref": ref,
                "params": params,
            }
        )

    @classmethod
    def player_position(cls) -> dict:
        return cls.adapter._engine.movement(cls.adapter.world_instance_id).state(
            cls.adapter._player_ref
        )

    @classmethod
    def sync_player_to_iso(cls, position: dict) -> None:
        spatial = cls.adapter._engine.spatial(cls.adapter.world_instance_id)
        coordinate = spatial.isometric_to_geodetic(
            float(position["iso_x_m"]),
            float(position["iso_y_m"]),
            float(position.get("altitude_m", 0.0)),
        )
        cls.adapter._engine.movement(cls.adapter.world_instance_id).sync_to_geodetic(
            cls.adapter._player_ref,
            coordinate,
            reason="AUTHORITY_TEST_PHYSICAL_APPROACH",
        )

    def test_01_real_save_contains_profile_bag_and_session_state(self) -> None:
        before = self.adapter.snapshot(self.session)
        if before["inventory_projection"]["bag"]["state"] == "NO_BAG":
            equipped = self.command(
                "REQUEST_EQUIP_BAG",
                "B10-EQUIP-BAG",
                {
                    "request_ref": "B10-EQUIP-BAG:UI",
                    "bag_instance_ref": "CLIENT-CORRELATION-ONLY",
                    "client_presentation_only": True,
                },
            )
            self.assertEqual("PASS", equipped["status"])
        preference = self.command(
            "SET_AUTO_PICKUP", "B10-PREF-ON", {"enabled": True}
        )
        self.assertEqual("PASS", preference["status"])
        position = self.player_position()
        type(self).saved_position = dict(position)
        saved = self.command(
            "REQUEST_SAVE",
            "B10-SAVE-MANUAL-1",
            {
                "request_ref": "B10-SAVE-MANUAL-1:UI",
                "slot_ref": "manual",
                "save_kind": "MANUAL",
                "reason": "AUTHORITY_TEST",
                "client_presentation_only": True,
            },
        )
        self.assertEqual("CONFIRMED", saved["result"])
        self.assertEqual("PASS", saved["snapshot_integrity"]["status"])
        self.assertTrue(saved["server_authoritative"])
        type(self).first_save_result = dict(saved)

    def test_02_reload_reopens_real_stage16a_and_restores_saved_state(self) -> None:
        self.command("SET_AUTO_PICKUP", "B10-PREF-OFF-AFTER-SAVE", {"enabled": False})
        position = self.player_position()
        moved = self.command(
            "MOVE_TO_POINT",
            "B10-MOVE-AFTER-SAVE",
            {
                "iso_x_m": float(position["iso_x_m"]) + 0.25,
                "iso_y_m": float(position["iso_y_m"]),
                "duration_s": 0.25,
                "mode": "WALK",
            },
        )
        self.assertEqual("PASS", moved["status"])
        cursor_before_restore = self.adapter.snapshot(self.session)["snapshot_sequence"]
        restored = self.command(
            "REQUEST_RELOAD_RESYNC",
            "B10-RELOAD-MANUAL-1",
            {
                "request_ref": "B10-RELOAD-MANUAL-1:UI",
                "slot_ref": "manual",
                "require_resync_before_ready": True,
                "client_presentation_only": True,
            },
        )
        type(self).restore_result = restored
        self.assertEqual("PASS", restored["status"])
        projection = restored["restore_snapshot"]
        self.assertTrue(projection["profile_preference"]["auto_pickup"])
        self.assertEqual("BAG_EQUIPPED", projection["inventory_snapshot"]["bag"]["state"])
        current = self.player_position()
        self.assertAlmostEqual(float(self.saved_position["iso_x_m"]), current["iso_x_m"], places=6)
        self.assertAlmostEqual(float(self.saved_position["iso_y_m"]), current["iso_y_m"], places=6)
        self.assertTrue(projection["server_authoritative"])
        fresh = self.adapter.snapshot(self.session)
        self.assertGreater(fresh["snapshot_sequence"], cursor_before_restore)
        replayed_post_save_mutation = self.command(
            "SET_AUTO_PICKUP", "B10-PREF-OFF-AFTER-SAVE", {"enabled": False}
        )
        self.assertTrue(replayed_post_save_mutation["idempotent_replay"])
        self.assertTrue(replayed_post_save_mutation["replay_suppressed"])
        self.assertTrue(self.adapter.snapshot(self.session)["profile_preferences"]["auto_pickup"])
        second_save = self.command(
            "REQUEST_SAVE",
            "B10-SAVE-MANUAL-2",
            {
                "request_ref": "B10-SAVE-MANUAL-2:UI",
                "slot_ref": "manual",
                "save_kind": "MANUAL",
                "reason": "CURSOR_CONTINUITY",
                "client_presentation_only": True,
            },
        )
        self.assertGreater(
            second_save["result_sequence"], self.first_save_result["result_sequence"]
        )
        self.assertGreater(second_save["save_sequence"], self.first_save_result["save_sequence"])

    def test_03_duplicate_reload_is_transport_replay_not_second_restore(self) -> None:
        replay = self.command(
            "REQUEST_RELOAD_RESYNC",
            "B10-RELOAD-MANUAL-1",
            {
                "request_ref": "B10-RELOAD-MANUAL-1:UI",
                "slot_ref": "manual",
                "require_resync_before_ready": True,
                "client_presentation_only": True,
            },
        )
        self.assertTrue(replay["idempotent_replay"])
        self.assertTrue(replay["replay_suppressed"])
        self.assertEqual(
            self.restore_result["restore_snapshot"]["restore_ref"],
            replay["restore_snapshot"]["restore_ref"],
        )

    def test_04_process_restart_resumes_the_restored_authority(self) -> None:
        self.adapter.close()
        type(self).adapter = Stage16BAuthorityAdapter(self.config)
        rebound = self.adapter.bind_session(self.session)
        self.assertEqual("PASS", rebound["status"])
        snapshot = self.adapter.snapshot(self.session)
        self.assertTrue(snapshot["profile_preferences"]["auto_pickup"])
        self.assertEqual("BAG_EQUIPPED", snapshot["inventory_projection"]["bag"]["state"])
        self.assertEqual("RESUMED", self.adapter.bootstrap_mode)

    def test_05_water_authority_exhausts_then_confirms_death_and_single_bag(self) -> None:
        traversal = self.command(
            "REPORT_WATER_TRAVERSAL",
            "B10-WATER-EXHAUST-STAMINA",
            {
                "request_ref": "B10-WATER-EXHAUST-STAMINA:UI",
                "volume_ref": "WATER-B10-DEEP",
                "depth_m": 8.0,
                "flow_speed_mps": 8.0,
                "distance_m": 100.0,
                "under_bridge": False,
                "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", traversal["status"])
        self.assertEqual(0.0, traversal["stamina"]["stamina_after"])
        first = self.command(
            "REPORT_WATER_EXHAUSTION",
            "B10-WATER-GRACE-START",
            {
                "request_ref": "B10-WATER-GRACE-START:UI",
                "volume_ref": "WATER-B10-DEEP",
                "in_water": True,
                "client_presentation_only": True,
            },
        )
        self.assertEqual("STAMINA_ZERO_GRACE", first["exhaustion_snapshot"]["state"])
        time.sleep(4.1)
        defeated = self.command(
            "REPORT_WATER_EXHAUSTION",
            "B10-WATER-GRACE-DEFEAT",
            {
                "request_ref": "B10-WATER-GRACE-DEFEAT:UI",
                "volume_ref": "WATER-B10-DEEP",
                "in_water": True,
                "client_presentation_only": True,
            },
        )
        self.assertTrue(defeated["defeat_required"])
        self.assertEqual("DEAD_AWAITING_RESPAWN", defeated["death_event"]["state"])
        self.assertTrue(defeated["death_event"]["bag_drop"]["single_container"])
        entries = defeated["death_event"]["bag_drop"]["dropped_bag_snapshot"]["dropped_bags"]
        self.assertEqual(1, len(entries))
        self.assertEqual("DROPPED_WATER_FLOATING", entries[0]["state"])
        type(self).water_bag_ref = entries[0]["bag_ref"]

    def test_06_dead_player_cannot_recover_bag(self) -> None:
        rejected = self.command(
            "REQUEST_BAG_RECOVERY",
            "B10-DEAD-RECOVERY-REJECT",
            {
                "request_ref": "B10-DEAD-RECOVERY-REJECT:UI",
                "bag_ref": self.water_bag_ref,
                "target_ref": self.water_bag_ref,
                "target_kind": "DROPPED_BAG",
                "physical_distance_m": 0.0,
                "client_range_candidate_m": 0.5,
                "client_guard_passed": True,
                "client_presentation_only": True,
            },
        )
        self.assertEqual("BAG_RECOVERY_REQUIRES_LIVING_PLAYER", rejected["reason"])
        self.assertEqual("REJECTED", rejected["result"])

    def test_07_respawn_uses_stage15_safe_waypoint_and_preserves_state(self) -> None:
        before_xp = self.adapter._engine.character(self.adapter.world_instance_id).ensure_profile(
            self.adapter.profile_ref
        )["experience"]
        respawn = self.command(
            "REQUEST_RESPAWN",
            "B10-RESPAWN-1",
            {
                "request_ref": "B10-RESPAWN-1:UI",
                "death_ref": "DEATH-WATER-B10-WATER-GRACE-DEFEAT",
                "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", respawn["status"])
        self.assertTrue(respawn["experience_preserved"])
        self.assertTrue(respawn["inventory_preserved"])
        self.assertEqual("READY", respawn["respawn_snapshot"]["state"])
        after = self.adapter._engine.character(self.adapter.world_instance_id).ensure_profile(
            self.adapter.profile_ref
        )
        self.assertEqual("ALIVE", after["vitals"]["life_state"])
        self.assertEqual(before_xp, after["experience"])

    def test_08_own_bag_recovery_is_authoritative_and_preserves_identity(self) -> None:
        bag = self.adapter._engine.stage16a(self.adapter.world_instance_id).water_bag.bag(
            self.water_bag_ref
        )
        self.sync_player_to_iso(bag["position"])
        recovered = self.command(
            "REQUEST_BAG_RECOVERY",
            "B10-OWN-BAG-RECOVERY",
            {
                "request_ref": "B10-OWN-BAG-RECOVERY:UI",
                "bag_ref": self.water_bag_ref,
                "target_ref": self.water_bag_ref,
                "target_kind": "DROPPED_BAG",
                "physical_distance_m": 0.0,
                "client_range_candidate_m": 0.5,
                "client_guard_passed": True,
                "client_presentation_only": True,
            },
        )
        self.assertEqual("ACCEPTED", recovered["result"])
        self.assertEqual("RECOVERED", recovered["bag_projection"]["state"])
        self.assertEqual(self.adapter.profile_ref, recovered["bag_projection"]["original_owner_ref"])
        carry = self.adapter._engine.stage16a(self.adapter.world_instance_id).water_bag.ensure_carry_profile(
            self.adapter.profile_ref
        )
        self.assertEqual(self.water_bag_ref, carry["equipped_bag_ref"])

    def test_09_ground_loot_899_seconds_survives_real_save_reload_then_sinks(self) -> None:
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        snapshot = self.adapter.snapshot(self.session)
        item_ref = snapshot["vendor_stock"][0]["items"][0]["item_ref"]
        position = self.player_position()
        spawned = stage16a.ground_loot.spawn_drop(
            source_ref="B10-WATER-TTL-SOURCE",
            source_kind="PLAYER_DROP",
            item_ref=item_ref,
            item_kind="MATERIAL",
            quantity=1,
            candidate_position=position,
            event_ref="B10-WATER-TTL-SPAWN",
        )
        drop_ref = spawned["drop_ref"]
        type(self).water_drop_ref = drop_ref
        stage16a.confirm_drop_settled(
            drop_ref,
            settled_position=position,
            reachable=True,
            event_ref="B10-WATER-TTL-SETTLED",
        )
        marked = self.command(
            "REPORT_GROUND_LOOT_WATER_STATE",
            "B10-WATER-TTL-MARK",
            {
                "request_ref": "B10-WATER-TTL-MARK:UI",
                "target_ref": drop_ref,
                "drop_ref": drop_ref,
                "in_water": True,
                "flow_speed_mps": 0.3,
                "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", marked["status"])
        stage16a.advance_water_time(899.0, event_ref="B10-WATER-TTL-899")
        saved = self.command(
            "REQUEST_SAVE",
            "B10-SAVE-WATER-899",
            {
                "request_ref": "B10-SAVE-WATER-899:UI",
                "slot_ref": "water899",
                "save_kind": "MANUAL",
                "reason": "WATER_CONTINUITY",
                "client_presentation_only": True,
            },
        )
        self.assertEqual("CONFIRMED", saved["result"])
        stage16a.advance_water_time(1.0, event_ref="B10-WATER-TTL-900")
        self.assertEqual("SUNK", stage16a.ground_loot.drop(drop_ref)["state"])
        restored = self.command(
            "REQUEST_RELOAD_RESYNC",
            "B10-RELOAD-WATER-899",
            {
                "request_ref": "B10-RELOAD-WATER-899:UI",
                "slot_ref": "water899",
                "require_resync_before_ready": True,
                "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", restored["status"])
        restored_drop = self.adapter._engine.stage16a(self.adapter.world_instance_id).ground_loot.drop(drop_ref)
        self.assertEqual("ACTIVE", restored_drop["state"])
        self.assertEqual("WATER", restored_drop["environment"])
        self.assertAlmostEqual(899.0, restored_drop["water_exposure_s"], places=5)
        wire_drop = next(
            entry
            for entry in restored["restore_snapshot"]["ground_loot_snapshot"]["ground_loot"]
            if entry["target_ref"] == drop_ref
        )
        self.assertEqual("RECOVERABLE_IN_WATER", wire_drop["state"])
        self.adapter._engine.stage16a(self.adapter.world_instance_id).advance_water_time(
            1.0, event_ref="B10-WATER-TTL-900-AFTER-RESTORE"
        )
        self.assertEqual(
            "SUNK",
            self.adapter._engine.stage16a(self.adapter.world_instance_id).ground_loot.drop(drop_ref)["state"],
        )

    def test_10_land_bag_has_no_expiry_and_foreign_npc_cannot_steal(self) -> None:
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        npcs = [
            row["id"]
            for row in self.adapter._engine.country(self.adapter.world_instance_id)._all_npc_records()
            if row["id"] != self.adapter._player_ref
        ]
        owner, foreign_npc = npcs[0], npcs[1]
        stage16a.water_bag.equip_new_bag(owner, event_ref="B10-NPC-LAND-EQUIP")
        position = self.player_position()
        dropped = stage16a.drop_bag_for_death(
            owner,
            in_water=False,
            position=position,
            event_ref="B10-NPC-LAND-DROP",
        )
        bag_ref = dropped["bag_ref"]
        stage16a.advance_water_time(100000.0, event_ref="B10-NPC-LAND-NO-EXPIRY")
        self.assertEqual("DROPPED_LAND", stage16a.water_bag.bag(bag_ref)["state"])
        theft = stage16a.recover_bag(
            bag_ref,
            foreign_npc,
            claimant_kind="NPC",
            event_ref="B10-NPC-FOREIGN-NO-THEFT",
        )
        self.assertEqual("FOREIGN_NPC_BAG_RECOVERY_NOT_ENABLED", theft["reason"])
        recovered = self.command(
            "REQUEST_BAG_RECOVERY",
            "B10-PLAYER-RECOVERS-NPC-BAG",
            {
                "request_ref": "B10-PLAYER-RECOVERS-NPC-BAG:UI",
                "bag_ref": bag_ref,
                "target_ref": bag_ref,
                "target_kind": "DROPPED_BAG",
                "physical_distance_m": 0.0,
                "client_range_candidate_m": 0.5,
                "client_guard_passed": True,
                "client_presentation_only": True,
            },
        )
        self.assertEqual("ACCEPTED", recovered["result"])
        self.assertEqual("RECOVERED_FOREIGN", recovered["bag_projection"]["state"])
        self.assertEqual(owner, recovered["bag_projection"]["original_owner_ref"])
        self.assertEqual(owner, recovered["property_owner_ref"])
        self.assertFalse(recovered["auto_theft"])

    def test_11_water_bag_1799_seconds_survives_save_reload_then_sinks(self) -> None:
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        owner = next(
            row["id"]
            for row in self.adapter._engine.country(self.adapter.world_instance_id)._all_npc_records()
            if row["id"] != self.adapter._player_ref
            and not stage16a.water_bag.ensure_carry_profile(row["id"]).get("equipped_bag_ref")
        )
        stage16a.water_bag.equip_new_bag(owner, event_ref="B10-NPC-WATER-EQUIP")
        dropped = stage16a.drop_bag_for_death(
            owner,
            in_water=True,
            position=self.player_position(),
            event_ref="B10-NPC-WATER-DROP",
        )
        bag_ref = dropped["bag_ref"]
        stage16a.advance_water_time(1799.0, event_ref="B10-NPC-WATER-1799")
        self.assertEqual("DROPPED_WATER_FLOATING", stage16a.water_bag.bag(bag_ref)["state"])
        self.command(
            "REQUEST_SAVE",
            "B10-SAVE-BAG-1799",
            {
                "request_ref": "B10-SAVE-BAG-1799:UI",
                "slot_ref": "bag1799",
                "save_kind": "MANUAL",
                "reason": "BAG_WATER_CONTINUITY",
                "client_presentation_only": True,
            },
        )
        stage16a.advance_water_time(1.0, event_ref="B10-NPC-WATER-1800")
        self.assertEqual("SUNK", stage16a.water_bag.bag(bag_ref)["state"])
        restored = self.command(
            "REQUEST_RELOAD_RESYNC",
            "B10-RELOAD-BAG-1799",
            {
                "request_ref": "B10-RELOAD-BAG-1799:UI",
                "slot_ref": "bag1799",
                "require_resync_before_ready": True,
                "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", restored["status"])
        bag = self.adapter._engine.stage16a(self.adapter.world_instance_id).water_bag.bag(bag_ref)
        self.assertEqual("DROPPED_WATER_FLOATING", bag["state"])
        self.assertAlmostEqual(1799.0, bag["water_exposure_s"], places=5)
        self.adapter._engine.stage16a(self.adapter.world_instance_id).advance_water_time(
            1.0, event_ref="B10-NPC-WATER-1800-AFTER-RESTORE"
        )
        self.assertEqual(
            "SUNK",
            self.adapter._engine.stage16a(self.adapter.world_instance_id).water_bag.bag(bag_ref)["state"],
        )

    def test_12_no_client_authority_fields_are_accepted_for_b10(self) -> None:
        before = self.adapter._engine.character(self.adapter.world_instance_id).ensure_profile(
            self.adapter.profile_ref
        )["vitals"]["life_state"]
        forged = self.command(
            "REQUEST_RESPAWN",
            "B10-FORGED-DEATH-RESULT",
            {
                "request_ref": "B10-FORGED-DEATH-RESULT:UI",
                "death_ref": "FORGED",
                "death_result": {"life_state": "DEAD"},
                "client_presentation_only": True,
            },
        )
        after = self.adapter._engine.character(self.adapter.world_instance_id).ensure_profile(
            self.adapter.profile_ref
        )["vitals"]["life_state"]
        self.assertEqual("CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN", forged["reason"])
        self.assertEqual(before, after)

    def _player_stamina(self) -> float:
        return float(
            self.adapter._engine.movement(self.adapter.world_instance_id)
            .state(self.adapter._player_ref)["stamina"]
        )

    def test_13_water_traversal_actor_kind_absent_preserves_legacy_player_route(self) -> None:
        """A. actor_kind ausente -> comportamento legado PLAYER preservado.

        Player stamina may already be at 0 by this point in the shared class
        fixture (test_05 deliberately exhausts it and nothing restores it), so
        this asserts the route itself ran -- water_traversal_effect()'s own
        response shape (profile_ref/traversal/stamina, with a real positive
        requested_cost computed from the sample) -- rather than an absolute
        stamina delta that a floor-clamped value cannot express.
        """
        result = self.command(
            "REPORT_WATER_TRAVERSAL",
            "G25-VEHICLE-A-ABSENT",
            {
                "request_ref": "G25-VEHICLE-A-ABSENT:UI",
                "depth_m": 0.3,
                "flow_speed_mps": 0.2,
                "distance_m": 1.0,
                "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual("PLAYER", result["actor_kind"])
        self.assertEqual(self.adapter.profile_ref, result.get("profile_ref"))
        self.assertIn("traversal", result)
        self.assertIn("stamina", result)
        self.assertGreater(float(result["stamina"]["requested_cost"]), 0.0)

    def test_14_water_traversal_actor_kind_player_matches_legacy_behavior(self) -> None:
        """B. actor_kind="PLAYER" -> comportamento PLAYER atual preservado (same
        proof and same caveat about already-zero shared-fixture stamina as test_13)."""
        result = self.command(
            "REPORT_WATER_TRAVERSAL",
            "G25-VEHICLE-B-PLAYER",
            {
                "request_ref": "G25-VEHICLE-B-PLAYER:UI",
                "depth_m": 0.3,
                "flow_speed_mps": 0.2,
                "distance_m": 1.0,
                "actor_kind": "PLAYER",
                "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual("PLAYER", result["actor_kind"])
        self.assertEqual(self.adapter.profile_ref, result.get("profile_ref"))
        self.assertIn("traversal", result)
        self.assertIn("stamina", result)
        self.assertGreater(float(result["stamina"]["requested_cost"]), 0.0)

    def test_15_water_traversal_actor_kind_vehicle_routes_to_vehicle_water_traversal(self) -> None:
        """C. actor_kind="VEHICLE" -> rota vehicle_water_traversal realmente executada.
        E. VEHICLE nunca aplica apply_external_stamina_cost ao avatar do player."""
        before = self._player_stamina()
        result = self.command(
            "REPORT_WATER_TRAVERSAL",
            "G25-VEHICLE-C-DEEP",
            {
                "request_ref": "G25-VEHICLE-C-DEEP:UI",
                "depth_m": 1.0,
                "flow_speed_mps": 0.2,
                "distance_m": 1.0,
                "actor_kind": "VEHICLE",
                "client_presentation_only": True,
            },
        )
        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual("VEHICLE_WATER_TOO_DEEP", result["reason"])
        self.assertEqual("VEHICLE", result["actor_kind"])
        # vehicle_water_traversal() returns the raw water_traversal_sample() payload
        # (mode/stamina_cost/flow_class/...), never water_traversal_effect()'s
        # profile_ref/traversal/stamina nesting -- proof the VEHICLE branch, not the
        # PLAYER branch, actually produced this result.
        self.assertNotIn("profile_ref", result)
        self.assertNotIn("traversal", result)
        self.assertNotIn("stamina", result)
        self.assertEqual(0.0, float(result["stamina_cost"]))
        after = self._player_stamina()
        self.assertEqual(before, after, "a VEHICLE report must never touch player stamina")

    def test_16_water_traversal_actor_kind_vehicle_shallow_uses_traction_not_stamina(self) -> None:
        """C/E continued: a passing (shallow) VEHICLE sample also never touches
        player stamina and uses the traction/speed penalty contract instead."""
        before = self._player_stamina()
        result = self.command(
            "REPORT_WATER_TRAVERSAL",
            "G25-VEHICLE-SHALLOW",
            {
                "request_ref": "G25-VEHICLE-SHALLOW:UI",
                "depth_m": 0.3,
                "flow_speed_mps": 0.2,
                "distance_m": 1.0,
                "actor_kind": "VEHICLE",
                "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual("WADE_VEHICLE", result["mode"])
        self.assertEqual(0.0, float(result["stamina_cost"]))
        self.assertIn("speed_factor", result)
        self.assertIn("traction_penalty", result)
        self.assertNotIn("traversal", result)
        self.assertNotIn("stamina", result)
        after = self._player_stamina()
        self.assertEqual(before, after, "a passing VEHICLE report must never touch player stamina either")

    def test_17_water_traversal_actor_kind_invalid_is_rejected_explicitly(self) -> None:
        """D. actor_kind inválido -> rejeição explícita, sem fallback silencioso para PLAYER."""
        before = self._player_stamina()
        result = self.command(
            "REPORT_WATER_TRAVERSAL",
            "G25-VEHICLE-D-INVALID",
            {
                "request_ref": "G25-VEHICLE-D-INVALID:UI",
                "depth_m": 0.3,
                "flow_speed_mps": 0.2,
                "distance_m": 1.0,
                "actor_kind": "BOAT",
                "client_presentation_only": True,
            },
        )
        self.assertEqual("UNSUPPORTED_WATER_TRAVERSAL_ACTOR_KIND", result["reason"])
        self.assertNotIn("traversal", result)
        after = self._player_stamina()
        self.assertEqual(before, after, "an invalid actor_kind must not silently fall back to spending player stamina")

    def test_18_shallow_water_is_wade_and_traversable(self) -> None:
        """G16B-24 clause 1: shallow water (depth <= SHALLOW_DEPTH_M = 0.65) is WADE,
        not SWIM, and never blocked."""
        result = self.command(
            "REPORT_WATER_TRAVERSAL",
            "G24-SHALLOW-A",
            {
                "request_ref": "G24-SHALLOW-A:UI",
                "depth_m": 0.3,
                "flow_speed_mps": 0.2,
                "distance_m": 1.0,
                "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual("WADE", result["traversal"]["mode"])
        self.assertNotEqual("SWIM", result["traversal"]["mode"])
        self.assertTrue(result["traversal"]["shallow"])

    def test_19_under_bridge_shallow_preserves_traversability(self) -> None:
        """G16B-24 clause 2: under_bridge=true is preserved by the authority and
        never artificially blocks an otherwise-valid shallow crossing."""
        result = self.command(
            "REPORT_WATER_TRAVERSAL",
            "G24-UNDER-BRIDGE-B",
            {
                "request_ref": "G24-UNDER-BRIDGE-B:UI",
                "depth_m": 0.3,
                "flow_speed_mps": 0.2,
                "distance_m": 1.0,
                "under_bridge": True,
                "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual("WADE", result["traversal"]["mode"])
        self.assertTrue(result["traversal"]["under_bridge"])

    def test_20_stronger_current_increases_authoritative_stamina_cost(self) -> None:
        """G16B-24 clause 3: same depth/distance, only flow_speed_mps differs across
        the official CALM/STRONG_CURRENT boundary (_flow_class: <0.45 CALM,
        >=1.15 STRONG_CURRENT). Compared on the authoritative computed cost
        returned in the response, not on the shared fixture's avatar stamina
        (already at or near zero by this point from earlier tests; never
        artificially restored just to make this pass -- see
        Stage16BWaterCurrentStaminaMutationTests below for the real-avatar-delta
        proof on a fresh, full-stamina world)."""
        low = self.command(
            "REPORT_WATER_TRAVERSAL",
            "G24-CURRENT-LOW",
            {
                "request_ref": "G24-CURRENT-LOW:UI",
                "depth_m": 0.3,
                "flow_speed_mps": 0.2,
                "distance_m": 1.0,
                "client_presentation_only": True,
            },
        )
        high = self.command(
            "REPORT_WATER_TRAVERSAL",
            "G24-CURRENT-HIGH",
            {
                "request_ref": "G24-CURRENT-HIGH:UI",
                "depth_m": 0.3,
                "flow_speed_mps": 1.2,
                "distance_m": 1.0,
                "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", low["status"])
        self.assertEqual("PASS", high["status"])
        self.assertEqual("CALM", low["traversal"]["flow_class"])
        self.assertEqual("STRONG_CURRENT", high["traversal"]["flow_class"])
        self.assertGreater(
            float(high["traversal"]["stamina_cost"]),
            float(low["traversal"]["stamina_cost"]),
            "a stronger current must cost more stamina than a calmer one at the same depth/distance",
        )
        self.assertGreater(float(high["stamina"]["requested_cost"]), 0.0)

    def test_21_vehicle_shallow_uses_speed_and_traction_penalty_not_stamina(self) -> None:
        """G16B-24 clause 4: a shallow VEHICLE report uses speed_factor/traction_penalty,
        costs zero stamina, and never touches the player's own stamina."""
        before = self._player_stamina()
        result = self.command(
            "REPORT_WATER_TRAVERSAL",
            "G24-VEHICLE-SHALLOW",
            {
                "request_ref": "G24-VEHICLE-SHALLOW:UI",
                "depth_m": 0.3,
                "flow_speed_mps": 0.2,
                "distance_m": 1.0,
                "actor_kind": "VEHICLE",
                "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual("WADE_VEHICLE", result["mode"])
        self.assertEqual(0.0, float(result["stamina_cost"]))
        self.assertIn("speed_factor", result)
        self.assertLess(float(result["speed_factor"]), 1.0, "a shallow VEHICLE crossing must carry a real speed penalty")
        self.assertIn("traction_penalty", result)
        self.assertGreater(float(result["traction_penalty"]), 0.0)
        after = self._player_stamina()
        self.assertEqual(before, after)


class Stage16BWaterCurrentStaminaMutationTests(unittest.TestCase):
    """Isolated, fresh-stamina proof (own world, never shared with the drained
    class-level fixture above) that a stronger current really costs the PLAYER
    avatar more stamina in practice, not only in the returned computation.
    Stamina is never artificially restored/healed -- this class simply runs on
    its own untouched world instead."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_water_current_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session = "S16B-WATER-CURRENT"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def _stamina(self) -> float:
        return float(
            self.adapter._engine.movement(self.adapter.world_instance_id)
            .state(self.adapter._player_ref)["stamina"]
        )

    def test_01_stronger_current_costs_more_real_avatar_stamina(self) -> None:
        before_low = self._stamina()
        self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REPORT_WATER_TRAVERSAL",
                "command_ref": "G24-REAL-CURRENT-LOW",
                "params": {
                    "request_ref": "G24-REAL-CURRENT-LOW:UI",
                    "depth_m": 0.3,
                    "flow_speed_mps": 0.2,
                    "distance_m": 1.0,
                    "client_presentation_only": True,
                },
            }
        )
        after_low = self._stamina()
        low_spend = before_low - after_low
        self.assertGreater(low_spend, 0.0, "setup requires the low-current sample to have room to spend real stamina")

        before_high = self._stamina()
        self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REPORT_WATER_TRAVERSAL",
                "command_ref": "G24-REAL-CURRENT-HIGH",
                "params": {
                    "request_ref": "G24-REAL-CURRENT-HIGH:UI",
                    "depth_m": 0.3,
                    "flow_speed_mps": 1.2,
                    "distance_m": 1.0,
                    "client_presentation_only": True,
                },
            }
        )
        after_high = self._stamina()
        high_spend = before_high - after_high
        self.assertGreater(high_spend, 0.0, "setup requires the high-current sample to also have room to spend real stamina")
        self.assertGreater(high_spend, low_spend, "the stronger current must spend more real avatar stamina than the weaker one")


class Stage16BDeathRetentionTests(unittest.TestCase):
    """G16B-18/G16B-26 shared death-retention proof: XP, armor, a protected
    QUEST_UTILITY item, and ordinary Bag content across a real authoritative
    player death.

    Isolated world (own adapter), never shared with the drained fixture above,
    so before/after comparisons are meaningful and nothing here is restored or
    healed artificially. All setup uses existing, real engine methods
    (award_experience, items_arpg().grant_item()/equip(), REQUEST_EQUIP_BAG,
    REPORT_WATER_TRAVERSAL/REPORT_WATER_EXHAUSTION) -- the same pattern already
    used elsewhere in this suite for NPC bags and quest items. No new runtime.

    CLOTHES could not be included: _classify() (01_RUNTIME/arpg_item_core.py)
    never produces item_kind CLOTHES/CLOTHING/GARMENT anywhere in the catalog,
    so equipped_clothes_refs can never be populated with real data today. This
    is reported, not worked around -- see the round's final report.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_death_retention_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session = "S16B-DEATH-RETENTION"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, name: str, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {
                "session_ref": self.session,
                "command": name,
                "command_ref": ref,
                "params": params,
            }
        )

    def test_01_death_retains_xp_armor_protected_and_common_bag_content(self) -> None:
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        character = self.adapter._engine.character(self.adapter.world_instance_id)
        profile_ref = self.adapter.profile_ref

        # --- setup: existing engine methods only, no new runtime -------------
        xp_before = int(character.state(profile_ref)["experience"])
        award = character.award_experience(profile_ref, 500, event_ref="DR-XP-AWARD")
        self.assertEqual("PASS", award["status"])
        xp_after_award = int(award["experience"])
        self.assertGreater(xp_after_award, xp_before, "setup requires XP to actually change so retention is provable")

        armor_grant = items.grant_item(profile_ref, "ITEM-ARMOR", 1, event_ref="DR-ARMOR-GRANT")
        self.assertEqual("PASS", armor_grant["status"])
        armor_instance_ref = armor_grant["instance_refs"][0]
        equip_armor = items.equip(profile_ref, armor_instance_ref, "CHEST", event_ref="DR-ARMOR-EQUIP")
        self.assertEqual("PASS", equip_armor["status"])

        # ITEM-OLD-KEY is no longer granted manually here: _ensure_development_profile_loadout()
        # now provisions exactly one unit to every development-profile player at
        # boot (see andromeda_authority_adapter.py). Granting it again here would
        # double the quantity; the boot-time unit is what this test exercises.
        self.assertEqual("QUEST_UTILITY", items.definition("ITEM-OLD-KEY")["item_kind"])

        common_grant_before_bag = items.grant_item(profile_ref, "ITEM-GRAIN", 5, event_ref="DR-COMMON-GRANT")
        self.assertEqual("PASS", common_grant_before_bag["status"])

        equip_bag = self.command(
            "REQUEST_EQUIP_BAG",
            "DR-EQUIP-BAG",
            {"request_ref": "DR-EQUIP-BAG:UI", "bag_instance_ref": "CLIENT-CORRELATION-ONLY", "client_presentation_only": True},
        )
        self.assertEqual("PASS", equip_bag["status"])
        bag_ref = equip_bag["bag_ref"]

        # The quest item and the common stack are swept into the Bag by
        # equip_new_bag() (it only excludes already-equipped/retained
        # instances) -- this is the real, existing behavior, not a defect
        # this test works around.
        bag_contents_before = items.inventory_snapshot(bag_ref)
        self.assertEqual(1, int(bag_contents_before.get("stacks", {}).get("ITEM-OLD-KEY", 0)), "setup requires the quest item to start out inside the dropped Bag")
        self.assertEqual(5, int(bag_contents_before.get("stacks", {}).get("ITEM-GRAIN", 0)), "setup requires the common item to start out inside the dropped Bag")

        # COMMON_ITEM_NOT_MISCLASSIFIED_AS_PROTECTED / cross-check that the fixed
        # classifier is neither too narrow (test above) nor too broad here.
        bag_entries_before = self.adapter._inventory_entries(bag_contents_before)
        quest_entry = next(e for e in bag_entries_before if e["item_ref"] == "ITEM-OLD-KEY")
        common_entry = next(e for e in bag_entries_before if e["item_ref"] == "ITEM-GRAIN")
        self.assertTrue(quest_entry["protected_or_critical"], "PROTECTED_QUEST_UTILITY_PROJECTED")
        self.assertFalse(common_entry["protected_or_critical"], "an ordinary MATERIAL item must never be classified as protected_or_critical")

        armor_still_equipped_before_death = items.inventory_snapshot(profile_ref)["equipped"].get("CHEST")
        self.assertEqual(armor_instance_ref, armor_still_equipped_before_death, "setup requires the armor to be equipped (not swept into the Bag) before death")

        # --- real authoritative death: same exhaustion/grace/defeat sequence
        # already used elsewhere in this file, no forged death_result. --------
        traversal = self.command(
            "REPORT_WATER_TRAVERSAL",
            "DR-WATER-EXHAUST",
            {"request_ref": "DR-WATER-EXHAUST:UI", "depth_m": 8.0, "flow_speed_mps": 8.0, "distance_m": 100.0, "client_presentation_only": True},
        )
        self.assertEqual("PASS", traversal["status"])
        self.assertEqual(0.0, traversal["stamina"]["stamina_after"])
        grace_start = self.command(
            "REPORT_WATER_EXHAUSTION",
            "DR-GRACE-START",
            {"request_ref": "DR-GRACE-START:UI", "in_water": True, "client_presentation_only": True},
        )
        self.assertEqual("STAMINA_ZERO_GRACE", grace_start["exhaustion_snapshot"]["state"])
        time.sleep(4.1)
        defeated = self.command(
            "REPORT_WATER_EXHAUSTION",
            "DR-GRACE-DEFEAT",
            {"request_ref": "DR-GRACE-DEFEAT:UI", "in_water": True, "client_presentation_only": True},
        )
        self.assertTrue(defeated["defeat_required"])
        death_event = defeated["death_event"]
        self.assertEqual("DEAD_AWAITING_RESPAWN", death_event["state"])

        # --- DEATH_XP_PRESERVED ------------------------------------------------
        retention = death_event["retention"]
        self.assertTrue(retention["xp_retained"])
        self.assertEqual(xp_after_award, int(retention["experience"]), "XP after death must equal XP just before death -- not reduced, not reset")
        xp_after_death = int(character.state(profile_ref)["experience"])
        self.assertEqual(xp_after_award, xp_after_death, "the character core's own XP value must be unchanged by death, read independently of the projection")

        # --- DEATH_ARMOR_RETAINED ----------------------------------------------
        self.assertIn(armor_instance_ref, retention["equipped_armor_refs"])
        armor_owner_after_death = items.inventory_snapshot(profile_ref)["equipped"].get("CHEST")
        self.assertEqual(armor_instance_ref, armor_owner_after_death, "the armor instance must still be equipped on the player after death, read directly from the item core")

        # --- DEATH_RETENTION_TWO_SLOTS (already covered by the shared fixture
        # class and by the Godot gate; not duplicated here as its own check,
        # but the loadout is confirmed untouched as part of this same death) --
        loadout_after_death = self.adapter._engine.stage16a(self.adapter.world_instance_id).ensure_weapon_loadout(profile_ref)
        self.assertEqual(2, len(loadout_after_death["slots"]))

        # --- DEATH_PROTECTED_CRITICAL_RETAINED + DEATH_PROTECTED_ITEM_NOT_LEFT_IN_DROPPED_BAG
        # PROTECTED_QUEST_UTILITY_PROJECTED / PROTECTED_CRITICAL_REFS_MATCH_REAL_RETENTION
        #
        # _inventory_entries()'s protected_or_critical classifier now mirrors
        # WaterBagSurvivalCore._is_protected_definition() (same item_kind set:
        # QUEST/QUEST_ITEM/QUEST_UTILITY, same SINGULAR-rarity rule for
        # instances) instead of a narrower, independently-drifted set. A real
        # QUEST_UTILITY item must now actually appear in the projection.
        self.assertIn(
            "ITEM-OLD-KEY", retention["protected_critical_refs"],
            "the projection must report what the real protection core already protects",
        )
        quest_owner_after_death = items.inventory_snapshot(profile_ref)
        self.assertEqual(
            1, int(quest_owner_after_death.get("stacks", {}).get("ITEM-OLD-KEY", 0)),
            "PROTECTED_ITEM_RETURNED_TO_OWNER: the protected quest item must be back with the player",
        )

        # --- DEATH_SINGLE_BAG_CONTAINER_PRESERVED + DEATH_COMMON_BAG_CONTENT_PRESERVED
        bag_drop = death_event["bag_drop"]
        self.assertTrue(bag_drop["dropped"])
        self.assertTrue(bag_drop["single_container"])
        dropped_bags = bag_drop["dropped_bag_snapshot"]["dropped_bags"]
        self.assertEqual(1, len(dropped_bags), "exactly one Bag object must be dropped, never the contents scattered individually")
        self.assertEqual(bag_ref, dropped_bags[0]["bag_ref"])

        bag_contents_after = items.inventory_snapshot(bag_ref)
        self.assertEqual(0, int(bag_contents_after.get("stacks", {}).get("ITEM-OLD-KEY", 0)), "the protected item must have left the Bag before it dropped")
        self.assertEqual(
            5, int(bag_contents_after.get("stacks", {}).get("ITEM-GRAIN", 0)),
            "the ordinary, non-protected common item must still be inside the same dropped Bag container, undisturbed",
        )

        # PROTECTED_ITEM_NO_DUPLICATION: exactly the one unit granted exists
        # anywhere afterwards -- not with the player AND left behind in the Bag.
        total_old_key = (
            int(quest_owner_after_death.get("stacks", {}).get("ITEM-OLD-KEY", 0))
            + int(bag_contents_after.get("stacks", {}).get("ITEM-OLD-KEY", 0))
        )
        self.assertEqual(1, total_old_key, "the protected item must exist exactly once across player and Bag combined")

        # Death behavior itself is unchanged by this projection-only fix: the
        # same defeat/single-container facts already asserted above still hold.
        self.assertTrue(defeated["defeat_required"])
        self.assertTrue(bag_drop["single_container"])


class Stage16BBaseSlotLimitWithoutBagTests(unittest.TestCase):
    """G16B-26: proves BASE_SLOT_LIMIT=8 end to end when no Bag is equipped.

    Isolated world (own adapter), same pattern as Stage16BDeathRetentionTests.
    Real slot semantics (arpg_water_bag_survival_core.py::can_accept_carried()):
    used_slots (01_RUNTIME/arpg_item_core.py) counts, per distinct item_ref,
    ceil(existing_quantity / stack_max) for stackable stacks, or 1 per unit
    for non-stackable (UNIQUE_INSTANCE) items -- never "1 slot per unit" for a
    stack and never "quantity=N in one stack = N slots". A single stack never
    grows past ceil(qty/stack_max) slots regardless of quantity, so this test
    uses DISTINCT item_refs (quantity within stack_max) to occupy exactly one
    slot each, per the real formula in can_accept_carried().

    The development-profile boot (_ensure_development_profile_loadout(),
    andromeda_authority_adapter.py) already grants 2 MAIN/OFF weapon
    instances + 1 spare weapon instance + 1 work tool instance + 1
    ITEM-OLD-KEY (QUEST_UTILITY, qty 1, stack_max 20 -> 1 slot) directly via
    items.grant_item() (bypassing the carry policy, but still occupying real
    slots in the same base inventory can_accept_carried() reads) -- exactly 5
    slots before this test adds anything. That real, measured baseline
    (never assumed) is why this test fills only 3 more distinct items to
    reach 8, then attempts a 4th (the real 9th slot).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_base_slot_limit_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session = "S16B-BASE-SLOT-LIMIT"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, name: str, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {
                "session_ref": self.session,
                "command": name,
                "command_ref": ref,
                "params": params,
            }
        )

    def test_01_base_slot_limit_without_bag_end_to_end(self) -> None:
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        water_bag = stage16a.water_bag
        profile_ref = self.adapter.profile_ref

        # BASE_INVENTORY_OWNER_WITHOUT_BAG: no Bag equipped yet.
        effective_owner_no_bag = water_bag.effective_inventory_owner(profile_ref)
        self.assertEqual(profile_ref, effective_owner_no_bag)

        # Real, measured baseline -- never assumed. The dev-profile boot
        # already occupies 6 slots (2 weapons + 1 spare weapon + 1 tool +
        # 1 ITEM-OLD-KEY + 1 S16B-DEV-CLOTHES-LEGS-001), all distinct,
        # non-stackable-or-qty-1 items. The clothes instance occupies a real
        # slot from grant onward regardless of equip state (equip() never
        # removes an instance from instance_refs -- see arpg_item_core.py
        # ::equip()), so this count includes it even before any equip.
        initial_snapshot = items.inventory_snapshot(profile_ref)
        initial_used_slots = int(initial_snapshot["metrics"]["used_slots"])
        self.assertEqual(6, initial_used_slots, "development-profile boot baseline changed -- re-measure before trusting the rest of this test")

        # BASE_SLOT_LIMIT_EXACTLY_EIGHT
        self.assertEqual(8, water_bag.BASE_SLOT_LIMIT)

        # Fill the remaining slots up to exactly 8 with DISTINCT item_refs
        # (quantity 1, well within each one's own stack_max), via
        # grant_carried_item() -- the real function can_accept_carried()
        # itself backs, not a bypass through items.grant_item().
        fill_item_refs = ["ITEM-FOOD", "ITEM-FRUIT"]
        self.assertEqual(8 - initial_used_slots, len(fill_item_refs), "fill list must exactly close the gap to 8 real slots")
        for idx, item_ref in enumerate(fill_item_refs):
            grant = water_bag.grant_carried_item(profile_ref, item_ref, 1, event_ref=f"BSL-FILL-{idx}")
            self.assertEqual("PASS", grant["status"], grant)
            self.assertEqual(profile_ref, grant["effective_inventory_owner_ref"])
            self.assertFalse(grant["bag_equipped"])

        # BASE_SLOT_1_TO_8_ACCEPTED
        snapshot_at_eight = items.inventory_snapshot(profile_ref)
        used_slots_at_eight = int(snapshot_at_eight["metrics"]["used_slots"])
        self.assertEqual(8, used_slots_at_eight)
        for item_ref in fill_item_refs:
            self.assertEqual(1, int(snapshot_at_eight.get("stacks", {}).get(item_ref, 0)))

        # BASE_SLOT_NINE_REJECTED / BASE_SLOT_NINE_REJECTION_REASON
        ninth_item_ref = "ITEM-MANA-CRYSTAL"
        self.assertNotIn(ninth_item_ref, snapshot_at_eight.get("stacks", {}), "the 9th-slot probe item must not already be present")
        fit_check = water_bag.can_accept_carried(profile_ref, ninth_item_ref, 1)
        self.assertEqual("REJECTED", fit_check["status"])
        self.assertEqual("BASE_INVENTORY_SLOT_LIMIT_WITHOUT_BAG", fit_check["reason"])
        self.assertEqual(9, fit_check["projected_used_slots"])
        self.assertEqual(8, fit_check["logical_slot_limit"])

        ninth_grant = water_bag.grant_carried_item(profile_ref, ninth_item_ref, 1, event_ref="BSL-NINTH")
        self.assertEqual("REJECTED", ninth_grant["status"])
        self.assertEqual("BASE_INVENTORY_SLOT_LIMIT_WITHOUT_BAG", ninth_grant["reason"])

        # BASE_SLOT_NINE_NO_PARTIAL_MUTATION / BASE_SLOT_NINE_NO_DUPLICATION
        snapshot_after_rejection = items.inventory_snapshot(profile_ref)
        used_slots_after_rejection = int(snapshot_after_rejection["metrics"]["used_slots"])
        self.assertEqual(8, used_slots_after_rejection, "a rejected grant must not partially mutate used_slots")
        self.assertNotIn(ninth_item_ref, snapshot_after_rejection.get("stacks", {}), "a rejected grant must never place the item in the inventory")
        for item_ref in fill_item_refs:
            self.assertEqual(
                1, int(snapshot_after_rejection.get("stacks", {}).get(item_ref, 0)),
                "the 8 already-accepted items must be untouched -- no duplication, no loss",
            )
        # No Bag was created or equipped implicitly by any of the above.
        self.assertEqual(profile_ref, water_bag.effective_inventory_owner(profile_ref))

        # EQUIPPED_BAG_CHANGES_EFFECTIVE_OWNER: only after this point does a
        # real Bag equip change routing -- confirming the base-slot policy
        # above was specifically the no-Bag path, not a permanent ceiling.
        equip_bag = self.command(
            "REQUEST_EQUIP_BAG",
            "BSL-EQUIP-BAG",
            {"request_ref": "BSL-EQUIP-BAG:UI", "bag_instance_ref": "CLIENT-CORRELATION-ONLY", "client_presentation_only": True},
        )
        self.assertEqual("PASS", equip_bag["status"])
        bag_ref = equip_bag["bag_ref"]
        effective_owner_with_bag = water_bag.effective_inventory_owner(profile_ref)
        self.assertEqual(bag_ref, effective_owner_with_bag)
        self.assertNotEqual(profile_ref, effective_owner_with_bag)

        # The same item that was rejected above is now routed to the bag_ref,
        # not the player's base inventory -- effective destination changed.
        post_bag_grant = water_bag.grant_carried_item(profile_ref, ninth_item_ref, 1, event_ref="BSL-POST-BAG")
        self.assertEqual("PASS", post_bag_grant["status"])
        self.assertEqual(bag_ref, post_bag_grant["effective_inventory_owner_ref"])
        self.assertTrue(post_bag_grant["bag_equipped"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
