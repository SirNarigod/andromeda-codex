"""Backend-owned validation suite for the Stage16B authority adapter.

Covers the Phase 3 matrix: valid session, wrong session, forged player_ref, forged
authority fields, valid command, duplicate command, snapshot 1/2, stale snapshot,
reconnect, resync and persistence, plus the Master/baseline integrity invariants.
"""

from __future__ import annotations

import hashlib
import math
import pathlib
import sys
import tempfile
import unittest
import zipfile

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
REPO_ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(BACKEND_DIR))

from andromeda_authority_adapter import (  # noqa: E402
    ENV_FACTOR_MAX,
    ENV_FACTOR_MIN,
    STEP_DURATION_MAX_S,
    Stage16BAuthorityAdapter,
)
from authority_config import (  # noqa: E402
    MASTER_V2_0_1_SHA256,
    AuthorityConfig,
    AuthorityConfigError,
    _resolve_master_path,
    verify_master,
)

# Active Stage16A protected checkpoint (see run_stage16b_authority_validation.py's
# CHECKPOINT_ZIP comment for the V0.8.0 -> V0.8.1 succession record). V0.8.0
# stays sealed/restorable as the historical predecessor; this test compares
# the live tree against whichever checkpoint is currently active.
CHECKPOINT_ZIP = pathlib.Path(
    r"C:\Users\thall\Documents\ARPG CODEX"
    r"\ANDROMEDA_ARPG_STAGE16A_PRE_GODOT_V1_8_0_DEV_CHECKPOINT_V0_8_1.zip"
)

VALID_SESSION = "S16B-TEST-VALID"
WRONG_SESSION = "S16B-TEST-WRONG"


def build_config(tmp: pathlib.Path) -> AuthorityConfig:
    master = _resolve_master_path()
    return AuthorityConfig(
        master_release_path=master,
        master_release_sha256=verify_master(master),
        runtime_dir=PROJECT_ROOT / "01_RUNTIME",
        db_path=tmp / "world.sqlite",
        save_root=tmp / "saves",
        owner_scope="stage16b:test",
        world_seed=160811,
        player_class="WARRIOR",
    )


class Stage16BAuthorityAdapterTests(unittest.TestCase):
    adapter: Stage16BAuthorityAdapter

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_adapter_")
        cls.tmp = pathlib.Path(cls._tmp.name)
        cls.config = build_config(cls.tmp)
        cls.adapter = Stage16BAuthorityAdapter(cls.config)
        cls.adapter.bind_session(VALID_SESSION)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    # ------------------------------------------------------------ identity/health

    def test_01_master_sha256_is_v2_0_1(self) -> None:
        master = _resolve_master_path()
        digest = hashlib.sha256(master.read_bytes()).hexdigest().upper()
        self.assertEqual(MASTER_V2_0_1_SHA256, digest)
        self.assertEqual("V2.0.1", self.adapter._engine.runtime.master_version)

    def test_02_no_active_v2_1_0_path(self) -> None:
        for token in ("V2_1_0", "V2.1.0"):
            self.assertNotIn(token, str(self.config.master_release_path))
        with self.assertRaises(AuthorityConfigError):
            verify_master(pathlib.Path("C:/nope/ANDROMEDA_CODEX_MASTER_V2_1_0_RELEASE.zip"))

    def test_03_health_is_pass_and_authoritative(self) -> None:
        health = self.adapter.health()
        self.assertEqual("PASS", health["status"])
        self.assertTrue(health["server_authoritative"])
        self.assertEqual("PASS", health["arpg_health"])
        self.assertEqual("PASS", health["stage15_health"])
        self.assertEqual("PASS", health["stage16a_health"])
        self.assertEqual([], health["failures"])
        self.assertEqual("V2.0.1", health["master"]["version"])
        self.assertTrue(health["master"]["read_only"])
        self.assertEqual(list(Stage16BAuthorityAdapter.ENABLED_COMMANDS), health["enabled_commands"])
        self.assertEqual("IntegratedARPGEngineV16A", health["identity"]["engine_class"])

    def test_04_engine_is_stage16a_composition(self) -> None:
        engine = self.adapter._engine
        self.assertEqual("ANDROMEDA_ARPG_STAGE16A_VERTICAL_SLICE_PRE_GODOT", engine.AUTHORITY)
        self.assertEqual(
            "ANDROMEDA_ARPG_STAGE16A_VERTICAL_SLICE_ASSEMBLY_PRE_GODOT",
            engine.stage16a(self.adapter.world_instance_id).AUTHORITY,
        )

    def test_05_protected_checkpoint_unchanged(self) -> None:
        self.assertTrue(CHECKPOINT_ZIP.is_file(), "Stage16A protected checkpoint missing")
        mismatched: list[str] = []
        missing: list[str] = []
        with zipfile.ZipFile(CHECKPOINT_ZIP) as archive:
            names = [n for n in archive.namelist() if not n.endswith("/")]
            for name in names:
                target = REPO_ROOT / name
                if not target.is_file():
                    missing.append(name)
                    continue
                if hashlib.sha256(archive.read(name)).digest() != hashlib.sha256(
                    target.read_bytes()
                ).digest():
                    mismatched.append(name)
        self.assertEqual([], missing)
        self.assertEqual([], mismatched)
        self.assertEqual(724, len(names))

    # ------------------------------------------------------------ sessions

    def test_10_valid_session_snapshot(self) -> None:
        snap = self.adapter.snapshot(VALID_SESSION)
        self.assertEqual("PASS", snap["status"])
        self.assertTrue(snap["server_authoritative"])
        self.assertEqual(VALID_SESSION, snap["session_ref"])
        self.assertIsInstance(snap["snapshot_sequence"], int)
        self.assertNotIsInstance(snap["snapshot_sequence"], bool)
        self.assertGreaterEqual(snap["snapshot_sequence"], 0)
        self.assertTrue(str(snap["snapshot_id"]).strip())
        self.assertIn("transform", snap)
        self.assertIn("chunk", snap)
        self.assertEqual(self.adapter.world_instance_id, snap["identity"]["world_instance_id"])
        self.assertEqual(self.adapter.profile_ref, snap["identity"]["profile_ref"])

    def test_11_wrong_session_snapshot_rejected(self) -> None:
        snap = self.adapter.snapshot(WRONG_SESSION)
        self.assertEqual("REJECTED", snap["status"])
        self.assertEqual("UNKNOWN_OR_INACTIVE_SESSION", snap["reason"])
        self.assertNotIn("snapshot_sequence", snap)

    def test_12_missing_session_ref_rejected(self) -> None:
        self.assertEqual("SESSION_REF_REQUIRED", self.adapter.snapshot("")["reason"])
        self.assertEqual("SESSION_REF_REQUIRED", self.adapter.bind_session("")["reason"])

    def test_13_wrong_session_command_rejected_and_inert(self) -> None:
        player = self.adapter._player_ref
        before = self.adapter._engine.movement(self.adapter.world_instance_id).state(player)
        result = self.adapter.command(
            {
                "session_ref": WRONG_SESSION,
                "command": "MOVE_TO_POINT",
                "command_ref": "CR-WRONG-SESSION",
                "params": {"iso_x_m": before["iso_x_m"] + 5.0, "iso_y_m": before["iso_y_m"]},
            }
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("UNKNOWN_OR_INACTIVE_SESSION", result["reason"])
        after = self.adapter._engine.movement(self.adapter.world_instance_id).state(player)
        self.assertEqual(before["iso_x_m"], after["iso_x_m"])
        self.assertEqual(before["iso_y_m"], after["iso_y_m"])

    def test_14_bind_is_idempotent_and_never_takes_client_actor(self) -> None:
        first = self.adapter.bind_session(VALID_SESSION)
        self.assertEqual("PASS", first["status"])
        self.assertTrue(first["rebound"])
        self.assertEqual(self.adapter._player_ref, first["player_ref"])
        self.assertEqual("PLAYER", first["role"])

    # ------------------------------------------------------------ authority guard

    def test_20_forged_player_ref_in_params_rejected(self) -> None:
        result = self.adapter.command(
            {
                "session_ref": VALID_SESSION,
                "command": "MOVE_TO_POINT",
                "command_ref": "CR-FORGED-PLAYER-PARAM",
                "params": {"iso_x_m": 1.0, "iso_y_m": 1.0, "player_ref": "FORGED-PLAYER"},
            }
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN", result["reason"])
        self.assertEqual("$.params.player_ref", result["field_path"])

    def test_21_forged_player_ref_at_envelope_root_rejected(self) -> None:
        result = self.adapter.command(
            {
                "session_ref": VALID_SESSION,
                "command": "MOVE_TO_POINT",
                "command_ref": "CR-FORGED-PLAYER-ROOT",
                "player_ref": "FORGED-PLAYER",
                "params": {"iso_x_m": 1.0, "iso_y_m": 1.0},
            }
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN", result["reason"])
        self.assertEqual("$.player_ref", result["field_path"])

    def test_22_forged_authority_fields_rejected(self) -> None:
        for field in (
            "authority",
            "server_authoritative",
            "damage_result",
            "inventory_grant",
            "currency_result",
            "quest_completion",
            "canonical_mutation",
            "death_result",
            "bag_contents",
            "authoritative_ttl",
            "world_instance_id",
            "profile_ref",
            "role",
            "snapshot_sequence",
        ):
            with self.subTest(field=field):
                result = self.adapter.command(
                    {
                        "session_ref": VALID_SESSION,
                        "command": "MOVE_TO_POINT",
                        "command_ref": f"CR-FORGED-{field}",
                        "params": {"iso_x_m": 1.0, "iso_y_m": 1.0, field: "FORGED"},
                    }
                )
                self.assertEqual("REJECTED", result["status"])
                self.assertEqual("CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN", result["reason"])

    def test_23_nested_forged_authority_field_rejected(self) -> None:
        result = self.adapter.command(
            {
                "session_ref": VALID_SESSION,
                "command": "MOVE_TO_POINT",
                "command_ref": "CR-FORGED-NESTED",
                "params": {"iso_x_m": 1.0, "iso_y_m": 1.0, "meta": [{"ok": 1}, {"damage": 999}]},
            }
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN", result["reason"])
        self.assertEqual("$.params.meta[1].damage", result["field_path"])

    def test_24_forbidden_command_token_rejected(self) -> None:
        for name in ("APPLY_DAMAGE", "GRANT_ITEM", "QUEST_COMPLETION_SET", "CANON_WRITE"):
            with self.subTest(command=name):
                result = self.adapter.command(
                    {
                        "session_ref": VALID_SESSION,
                        "command": name,
                        "command_ref": f"CR-TOKEN-{name}",
                        "params": {},
                    }
                )
                self.assertEqual("REJECTED", result["status"])
                self.assertEqual("CLIENT_AUTHORITATIVE_COMMAND_FORBIDDEN", result["reason"])

    def test_25_unknown_envelope_field_rejected(self) -> None:
        result = self.adapter.command(
            {
                "session_ref": VALID_SESSION,
                "command": "MOVE_TO_POINT",
                "command_ref": "CR-UNKNOWN-FIELD",
                "params": {"iso_x_m": 1.0, "iso_y_m": 1.0},
                "priority": "HIGH",
            }
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("UNEXPECTED_ENVELOPE_FIELD", result["reason"])

    def test_26_commands_outside_this_round_rejected(self) -> None:
        for name in ("MOVE_VECTOR", "INTERACT", "DISCOVER", "DUNGEON_MOVE", "PATH_PLAN"):
            with self.subTest(command=name):
                result = self.adapter.command(
                    {
                        "session_ref": VALID_SESSION,
                        "command": name,
                        "command_ref": f"CR-SCOPE-{name}",
                        "params": {},
                    }
                )
                self.assertEqual("REJECTED", result["status"])
                self.assertEqual("COMMAND_NOT_ENABLED_IN_THIS_ROUND", result["reason"])

    def test_27_command_ref_required(self) -> None:
        result = self.adapter.command(
            {
                "session_ref": VALID_SESSION,
                "command": "MOVE_TO_POINT",
                "params": {"iso_x_m": 1.0, "iso_y_m": 1.0},
            }
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("COMMAND_REF_REQUIRED", result["reason"])

    # ------------------------------------------------------------ MOVE_TO_POINT

    def _state(self) -> dict:
        return self.adapter._engine.movement(self.adapter.world_instance_id).state(
            self.adapter._player_ref
        )

    def test_30_valid_move_to_point(self) -> None:
        before = self._state()
        target_x = before["iso_x_m"] + 3.0
        target_y = before["iso_y_m"]
        result = self.adapter.command(
            {
                "session_ref": VALID_SESSION,
                "command": "MOVE_TO_POINT",
                "command_ref": "CR-MOVE-01",
                "params": {"iso_x_m": target_x, "iso_y_m": target_y, "duration_s": 0.25},
            }
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual("MOVE_TO_POINT", result["command"])
        self.assertEqual("MOVE_VECTOR", result["delegated_core_command"])
        self.assertEqual(
            "LIVING_CONTINUOUS_ISOMETRIC_MOVEMENT_RUNTIME", result["authority"]
        )
        self.assertFalse(result["idempotent_replay"])
        self.assertFalse(result["replay_suppressed"])
        self.assertGreater(result["moved_m"], 0.0)
        after = self._state()
        self.assertNotEqual(before["iso_x_m"], after["iso_x_m"])
        self.assertLess(result["remaining_distance_m"], result["distance_before_m"])

    def test_31_duplicate_command_is_suppressed(self) -> None:
        before = self._state()
        envelope = {
            "session_ref": VALID_SESSION,
            "command": "MOVE_TO_POINT",
            "command_ref": "CR-MOVE-DUP",
            "params": {
                "iso_x_m": before["iso_x_m"] + 4.0,
                "iso_y_m": before["iso_y_m"],
                "duration_s": 0.25,
            },
        }
        first = self.adapter.command(dict(envelope))
        mid = self._state()
        second = self.adapter.command(dict(envelope))
        after = self._state()

        self.assertEqual("PASS", first["status"])
        self.assertFalse(first["idempotent_replay"])
        self.assertEqual("PASS", second["status"])
        self.assertTrue(second["idempotent_replay"])
        self.assertTrue(second["replay_suppressed"])
        self.assertEqual(first["iso_x_m"], second["iso_x_m"])
        self.assertEqual(first["moved_m"], second["moved_m"])
        # The decisive assertion: the world did not advance a second time.
        self.assertEqual(mid["iso_x_m"], after["iso_x_m"])
        self.assertEqual(mid["iso_y_m"], after["iso_y_m"])
        self.assertEqual(mid["elapsed_s"], after["elapsed_s"])

    def test_32_command_ref_payload_mismatch_rejected(self) -> None:
        before = self._state()
        base = {
            "session_ref": VALID_SESSION,
            "command": "MOVE_TO_POINT",
            "command_ref": "CR-MOVE-MISMATCH",
            "params": {"iso_x_m": before["iso_x_m"] + 1.0, "iso_y_m": before["iso_y_m"]},
        }
        self.assertEqual("PASS", self.adapter.command(dict(base))["status"])
        tampered = dict(base)
        tampered["params"] = {"iso_x_m": before["iso_x_m"] + 99.0, "iso_y_m": before["iso_y_m"]}
        result = self.adapter.command(tampered)
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("COMMAND_REF_PAYLOAD_MISMATCH", result["reason"])

    def test_33_command_ref_session_mismatch_rejected(self) -> None:
        other = "S16B-TEST-OTHER"
        self.assertEqual("PASS", self.adapter.bind_session(other)["status"])
        before = self._state()
        envelope = {
            "session_ref": VALID_SESSION,
            "command": "MOVE_TO_POINT",
            "command_ref": "CR-MOVE-CROSS-SESSION",
            "params": {"iso_x_m": before["iso_x_m"] + 1.0, "iso_y_m": before["iso_y_m"]},
        }
        self.assertEqual("PASS", self.adapter.command(dict(envelope))["status"])
        crossed = dict(envelope)
        crossed["session_ref"] = other
        result = self.adapter.command(crossed)
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("COMMAND_REF_SESSION_MISMATCH", result["reason"])
        self.adapter.revoke_session(other)

    def test_34_move_to_point_never_overshoots(self) -> None:
        before = self._state()
        # Target far closer than one WALK step, so the adapter must shorten the duration.
        result = self.adapter.command(
            {
                "session_ref": VALID_SESSION,
                "command": "MOVE_TO_POINT",
                "command_ref": "CR-MOVE-NO-OVERSHOOT",
                "params": {
                    "iso_x_m": before["iso_x_m"] + 0.05,
                    "iso_y_m": before["iso_y_m"],
                    "duration_s": 0.25,
                },
            }
        )
        self.assertEqual("PASS", result["status"])
        self.assertLessEqual(result["moved_m"], result["distance_before_m"] + 1e-6)
        self.assertLess(result["applied_duration_s"], result["requested_duration_s"])
        self.assertLessEqual(result["remaining_distance_m"], 1e-6)
        self.assertTrue(result["arrived"])

    def test_35_move_to_current_position_is_a_zero_step(self) -> None:
        before = self._state()
        result = self.adapter.command(
            {
                "session_ref": VALID_SESSION,
                "command": "MOVE_TO_POINT",
                "command_ref": "CR-MOVE-ZERO",
                "params": {"iso_x_m": before["iso_x_m"], "iso_y_m": before["iso_y_m"]},
            }
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual(0.0, result["moved_m"])
        self.assertTrue(result["arrived"])
        after = self._state()
        self.assertEqual(before["iso_x_m"], after["iso_x_m"])
        self.assertEqual(before["iso_y_m"], after["iso_y_m"])

    def test_36_invalid_move_parameters_rejected(self) -> None:
        before = self._state()
        cases = [
            ({"iso_x_m": "x", "iso_y_m": 1.0}, "INVALID_TARGET_POINT"),
            ({"iso_x_m": float("nan"), "iso_y_m": 1.0}, "INVALID_TARGET_POINT"),
            ({"iso_x_m": 1.0}, "INVALID_TARGET_POINT"),
            ({"iso_x_m": before["iso_x_m"], "iso_y_m": before["iso_y_m"], "mode": "FLY"}, "UNSUPPORTED_MOVE_MODE"),
            (
                {"iso_x_m": before["iso_x_m"] + 1, "iso_y_m": before["iso_y_m"], "duration_s": 0.0},
                "INVALID_STEP_DURATION",
            ),
            (
                {
                    "iso_x_m": before["iso_x_m"] + 1,
                    "iso_y_m": before["iso_y_m"],
                    "duration_s": STEP_DURATION_MAX_S + 0.001,
                },
                "INVALID_STEP_DURATION",
            ),
        ]
        for index, (params, reason) in enumerate(cases):
            with self.subTest(params=params):
                result = self.adapter.command(
                    {
                        "session_ref": VALID_SESSION,
                        "command": "MOVE_TO_POINT",
                        "command_ref": f"CR-MOVE-BAD-{index}",
                        "params": params,
                    }
                )
                self.assertEqual("REJECTED", result["status"])
                self.assertEqual(reason, result["reason"])

    def test_37_adapter_input_bands_match_the_core(self) -> None:
        """The mirrored bands must not drift away from continuous_movement.py."""
        movement = self.adapter._engine.movement(self.adapter.world_instance_id)
        player = self.adapter._player_ref
        self.assertEqual(
            {"WALK", "RUN", "CROUCH"}, set(movement.SPEEDS_MPS), "core move modes changed"
        )
        self.assertEqual(
            "REJECTED",
            movement.step_vector(player, 1.0, 0.0, duration_s=STEP_DURATION_MAX_S + 0.001)["status"],
        )
        self.assertEqual(
            "INVALID_STEP_DURATION",
            movement.step_vector(player, 1.0, 0.0, duration_s=0.0)["reason"],
        )
        block = self.adapter._engine.country(self.adapter.world_instance_id).npc(player)["block_id"]
        factor = self.adapter._engine.environment(self.adapter.world_instance_id).state_for_block(
            block
        )["movement_factor"]
        self.assertTrue(ENV_FACTOR_MIN <= factor <= ENV_FACTOR_MAX)

    # ------------------------------------------------------------ snapshot cursor

    def test_40_snapshot_sequence_is_monotonic(self) -> None:
        session = "S16B-TEST-SEQ"
        self.adapter.bind_session(session)
        first = self.adapter.snapshot(session)
        second = self.adapter.snapshot(session)
        third = self.adapter.snapshot(session)
        self.assertEqual(0, first["snapshot_sequence"])
        self.assertEqual(1, second["snapshot_sequence"])
        self.assertEqual(2, third["snapshot_sequence"])
        self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertNotEqual(second["snapshot_id"], third["snapshot_id"])
        self.adapter.revoke_session(session)

    def test_41_stale_and_forged_cursors_are_detected(self) -> None:
        session = "S16B-TEST-CURSOR"
        self.adapter.bind_session(session)
        self.adapter.snapshot(session)
        current = self.adapter.snapshot(session)

        stale = self.adapter.resync(session, current["snapshot_sequence"] - 1, None)
        self.assertEqual("STALE_OR_DUPLICATE", stale["cursor"]["cursor_status"])
        self.assertEqual("PASS", stale["status"])

        latest = self.adapter.snapshot(session)
        ahead = self.adapter.resync(session, latest["snapshot_sequence"] + 50, None)
        self.assertEqual("UNKNOWN_SNAPSHOT_SEQUENCE", ahead["cursor"]["cursor_status"])

        latest = self.adapter.snapshot(session)
        wrong_id = self.adapter.resync(session, latest["snapshot_sequence"], "S16B-FORGED-ID")
        self.assertEqual("SNAPSHOT_ID_MISMATCH", wrong_id["cursor"]["cursor_status"])

        latest = self.adapter.snapshot(session)
        good = self.adapter.resync(session, latest["snapshot_sequence"], latest["snapshot_id"])
        self.assertEqual("CURRENT", good["cursor"]["cursor_status"])

        bad_type = self.adapter.resync(session, "3", None)
        self.assertEqual("REJECTED", bad_type["status"])
        self.assertEqual("INVALID_SNAPSHOT_SEQUENCE_TYPE", bad_type["reason"])
        self.adapter.revoke_session(session)

    def test_42_resync_returns_a_fresh_authoritative_snapshot(self) -> None:
        session = "S16B-TEST-RESYNC"
        self.adapter.bind_session(session)
        first = self.adapter.snapshot(session)
        result = self.adapter.resync(session, first["snapshot_sequence"], first["snapshot_id"])
        self.assertEqual("PASS", result["status"])
        self.assertTrue(result["resync"])
        snap = result["snapshot"]
        self.assertEqual("PASS", snap["status"])
        self.assertTrue(snap["server_authoritative"])
        self.assertEqual(session, snap["session_ref"])
        self.assertGreater(snap["snapshot_sequence"], first["snapshot_sequence"])
        self.adapter.revoke_session(session)

    def test_43_resync_on_unknown_session_rejected(self) -> None:
        result = self.adapter.resync("S16B-NEVER-BOUND", None, None)
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("UNKNOWN_OR_INACTIVE_SESSION", result["reason"])

    # ------------------------------------------------------------ reconnect

    def test_50_revoke_then_reconnect(self) -> None:
        session = "S16B-TEST-RECONNECT"
        self.adapter.bind_session(session)
        before = self.adapter.snapshot(session)
        self.assertEqual("PASS", before["status"])

        revoked = self.adapter.revoke_session(session)
        self.assertEqual("PASS", revoked["status"])
        self.assertTrue(revoked["revoked"])

        dead = self.adapter.snapshot(session)
        self.assertEqual("REJECTED", dead["status"])
        self.assertEqual("UNKNOWN_OR_INACTIVE_SESSION", dead["reason"])

        dead_command = self.adapter.command(
            {
                "session_ref": session,
                "command": "MOVE_TO_POINT",
                "command_ref": "CR-AFTER-REVOKE",
                "params": {"iso_x_m": 1.0, "iso_y_m": 1.0},
            }
        )
        self.assertEqual("UNKNOWN_OR_INACTIVE_SESSION", dead_command["reason"])

        rebound = self.adapter.bind_session(session)
        self.assertEqual("PASS", rebound["status"])
        after = self.adapter.snapshot(session)
        self.assertEqual("PASS", after["status"])
        self.assertGreater(after["snapshot_sequence"], before["snapshot_sequence"])
        self.adapter.revoke_session(session)

    # ------------------------------------------------------------ persistence

    def test_60_state_survives_a_full_adapter_restart(self) -> None:
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="s16b_restart_", dir=self.tmp))
        config = build_config(tmp)
        first = Stage16BAuthorityAdapter(config)
        try:
            session = "S16B-RESTART"
            first.bind_session(session)
            snap = first.snapshot(session)
            player = first._player_ref
            state = first._engine.movement(first.world_instance_id).state(player)
            original_params = {
                "iso_x_m": state["iso_x_m"] + 2.0,
                "iso_y_m": state["iso_y_m"],
                "duration_s": 0.25,
            }
            move = first.command(
                {
                    "session_ref": session,
                    "command": "MOVE_TO_POINT",
                    "command_ref": "CR-RESTART-MOVE",
                    "params": dict(original_params),
                }
            )
            self.assertEqual("PASS", move["status"])
            world_id = first.world_instance_id
            profile_ref = first.profile_ref
            moved_state = first._engine.movement(world_id).state(player)
            last_sequence = snap["snapshot_sequence"]
        finally:
            first.close()

        second = Stage16BAuthorityAdapter(config)
        try:
            self.assertEqual("RESUMED", second.bootstrap_mode)
            self.assertEqual(world_id, second.world_instance_id)
            self.assertEqual(profile_ref, second.profile_ref)
            self.assertEqual(player, second._player_ref)
            self.assertEqual("PASS", second.health()["status"])

            # Session survives the restart: no rebind needed.
            resumed = second.snapshot("S16B-RESTART")
            self.assertEqual("PASS", resumed["status"])
            self.assertGreater(resumed["snapshot_sequence"], last_sequence)

            # Motion state survives the restart.
            after = second._engine.movement(world_id).state(player)
            self.assertAlmostEqual(moved_state["iso_x_m"], after["iso_x_m"], places=9)
            self.assertAlmostEqual(moved_state["iso_y_m"], after["iso_y_m"], places=9)

            # The command journal survives: the replay is still suppressed.
            replay = second.command(
                {
                    "session_ref": "S16B-RESTART",
                    "command": "MOVE_TO_POINT",
                    "command_ref": "CR-RESTART-MOVE",
                    "params": dict(original_params),
                }
            )
            self.assertTrue(replay["idempotent_replay"])
            self.assertTrue(replay["replay_suppressed"])
            post = second._engine.movement(world_id).state(player)
            self.assertEqual(after["iso_x_m"], post["iso_x_m"])
        finally:
            second.close()

    # ------------------------------------------------------------ non-duplication

    def test_70_adapter_declares_no_gameplay_tables(self) -> None:
        rows = self.adapter._engine.runtime.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 's16b_%'"
        ).fetchall()
        self.assertEqual(
            {
                "s16b_bootstrap",
                "s16b_command_journal",
                "s16b_snapshot_cursor",
                "s16b_result_cursor",
            },
            {str(r["name"]) for r in rows},
        )

    def test_71_adapter_source_contains_no_gameplay_rules(self) -> None:
        source = (BACKEND_DIR / "andromeda_authority_adapter.py").read_text(encoding="utf-8")
        banned = (
            "def _apply_damage",
            "def _grant_item",
            "def _resolve_combat",
            "def _compute_damage",
            "def _apply_currency",
            "def _resolve_quest",
            "def _apply_death",
            "arpg_item_core",
            "arpg_combat_core",
            "arpg_economy_crafting_core",
        )
        for token in banned:
            self.assertNotIn(token, source)
        self.assertIn("MOVE_VECTOR", source)
        self.assertIn("client_command", source)

    def test_72_snapshot_projection_shape_matches_b01(self) -> None:
        snap = self.adapter.snapshot(VALID_SESSION)
        transform = snap["transform"]
        for key in ("iso_x_m", "iso_y_m"):
            self.assertTrue(math.isfinite(float(transform[key])))
        entities = snap["chunk"]["entities"]
        refs = [str(e["entity_ref"]) for e in entities]
        self.assertEqual(len(refs), len(set(refs)), "B01 rejects duplicate entity_ref")
        self.assertTrue(all(refs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
