"""Live HTTP round-trip suite for the Stage16B authority backend.

Boots a real uvicorn process, exercises the B01 transport contract over the wire,
then shuts the process down and boots it again on the same SQLite world to prove
session, motion state, snapshot cursor and command journal persistence.
"""

from __future__ import annotations

import json
import os
import pathlib
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from authority_config import _resolve_master_path  # noqa: E402
from andromeda_authority_adapter import Stage16BAuthorityAdapter  # noqa: E402

PYTHON = sys.executable
BOOT_TIMEOUT_S = 300.0
SESSION = "GODOT-STAGE16B-HTTP-001"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class LiveServer:
    def __init__(self, port: int, var_dir: pathlib.Path, log_path: pathlib.Path) -> None:
        self.port = port
        self.var_dir = var_dir
        self.log_path = log_path
        self.process: subprocess.Popen | None = None
        self._log = None

    def start(self) -> None:
        env = dict(os.environ)
        env["ANDROMEDA_MASTER_RELEASE"] = str(_resolve_master_path())
        env["ANDROMEDA_S16B_VAR"] = str(self.var_dir)
        env["ANDROMEDA_S16B_DB"] = str(self.var_dir / "world.sqlite")
        env["ANDROMEDA_S16B_SAVE_ROOT"] = str(self.var_dir / "saves")
        env["ANDROMEDA_S16B_SEED"] = "160822"
        env["ANDROMEDA_S16B_OWNER_SCOPE"] = "stage16b:http"
        env["PYTHONUNBUFFERED"] = "1"
        self._log = open(self.log_path, "ab")
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self.process = subprocess.Popen(
            [
                PYTHON, "-m", "uvicorn", "stage16b_authority_api:app",
                "--host", "127.0.0.1", "--port", str(self.port),
                "--workers", "1", "--log-level", "warning",
            ],
            cwd=str(BACKEND_DIR),
            env=env,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )

    def wait_ready(self) -> dict:
        deadline = time.time() + BOOT_TIMEOUT_S
        last = ""
        while time.time() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(f"server exited early; log: {self.log_path.read_text(errors='replace')[-2000:]}")
            try:
                status, body = self.get("/health")
                if status == 200 and body.get("status") == "PASS":
                    return body
                last = json.dumps(body)[:400]
            except (urllib.error.URLError, ConnectionError, OSError):
                last = "not listening yet"
            time.sleep(1.0)
        raise RuntimeError(f"server not ready within {BOOT_TIMEOUT_S}s: {last}")

    def stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            try:
                if hasattr(signal, "CTRL_BREAK_EVENT"):
                    self.process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self.process.terminate()
                self.process.wait(timeout=30)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                self.process.kill()
                self.process.wait(timeout=30)
        self.process = None
        if self._log is not None:
            self._log.close()
            self._log = None

    # ------------------------------------------------------------------ http

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path: str, headers: dict | None = None) -> tuple[int, dict]:
        request = urllib.request.Request(self._url(path), headers=headers or {})
        return self._send(request)

    def post(self, path: str, payload, raw: bytes | None = None) -> tuple[int, dict]:
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._url(path), data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        return self._send(request)

    @staticmethod
    def _send(request: urllib.request.Request) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


class Stage16BAuthorityHttpTests(unittest.TestCase):
    server: LiveServer

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_http_")
        cls.var_dir = pathlib.Path(cls._tmp.name)
        cls.log_path = cls.var_dir / "uvicorn.log"
        cls.port = free_port()
        cls.server = LiveServer(cls.port, cls.var_dir, cls.log_path)
        cls.server.start()
        cls.boot_health = cls.server.wait_ready()
        cls.server.post("/session/bind", {"session_ref": SESSION})

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        try:
            cls._tmp.cleanup()
        except OSError:
            pass

    # ------------------------------------------------------------------ health

    def test_01_health_over_http(self) -> None:
        status, body = self.server.get("/health")
        self.assertEqual(200, status)
        self.assertEqual("PASS", body["status"])
        self.assertEqual("ANDROMEDA_STAGE16B_AUTHORITY_ADAPTER", body["service"])
        self.assertTrue(body["server_authoritative"])
        self.assertEqual("V2.0.1", body["master"]["version"])
        self.assertEqual("PASS", body["stage16a_health"])
        self.assertEqual(list(Stage16BAuthorityAdapter.ENABLED_COMMANDS), body["enabled_commands"])

    # ------------------------------------------------------------------ snapshot

    def test_10_snapshot_requires_session_ref(self) -> None:
        status, body = self.server.get("/snapshot")
        self.assertEqual(200, status, "domain rejections must not look like transport failures")
        self.assertEqual("REJECTED", body["status"])
        self.assertEqual("SESSION_REF_REQUIRED", body["reason"])

    def test_11_snapshot_accepts_query_and_header(self) -> None:
        status, query = self.server.get(f"/snapshot?session_ref={SESSION}")
        self.assertEqual(200, status)
        self.assertEqual("PASS", query["status"])
        status, header = self.server.get("/snapshot", {"X-Andromeda-Session": SESSION})
        self.assertEqual(200, status)
        self.assertEqual("PASS", header["status"])
        self.assertGreater(header["snapshot_sequence"], query["snapshot_sequence"])

    def test_12_snapshot_carries_the_full_b01_contract(self) -> None:
        _, body = self.server.get(f"/snapshot?session_ref={SESSION}")
        self.assertEqual("PASS", body["status"])
        self.assertIs(True, body["server_authoritative"])
        self.assertEqual(SESSION, body["session_ref"])
        self.assertIsInstance(body["snapshot_id"], str)
        self.assertTrue(body["snapshot_id"])
        self.assertIsInstance(body["snapshot_sequence"], int)
        self.assertIn("world_instance_id", body["identity"])
        self.assertIn("profile_ref", body["identity"])
        self.assertEqual("V2.0.1", body["identity"]["master_version"])
        self.assertIn("iso_x_m", body["transform"])
        self.assertIn("entities", body["chunk"])

    def test_13_snapshot_1_and_2_are_ordered(self) -> None:
        _, first = self.server.get(f"/snapshot?session_ref={SESSION}")
        _, second = self.server.get(f"/snapshot?session_ref={SESSION}")
        self.assertEqual(first["snapshot_sequence"] + 1, second["snapshot_sequence"])
        self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])

    def test_14_wrong_session_snapshot_rejected(self) -> None:
        status, body = self.server.get("/snapshot?session_ref=HTTP-WRONG-SESSION")
        self.assertEqual(200, status)
        self.assertEqual("REJECTED", body["status"])
        self.assertEqual("UNKNOWN_OR_INACTIVE_SESSION", body["reason"])

    # ------------------------------------------------------------------ command

    def _player_position(self) -> tuple[float, float]:
        _, snap = self.server.get(f"/snapshot?session_ref={SESSION}")
        return float(snap["transform"]["iso_x_m"]), float(snap["transform"]["iso_y_m"])

    def test_20_move_to_point_round_trip(self) -> None:
        x, y = self._player_position()
        status, body = self.server.post(
            "/command",
            {
                "session_ref": SESSION,
                "command": "MOVE_TO_POINT",
                "command_ref": "HTTP-CR-MOVE-01",
                "params": {"iso_x_m": x + 3.0, "iso_y_m": y, "duration_s": 0.25},
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("PASS", body["status"])
        self.assertEqual("MOVE_TO_POINT", body["command"])
        self.assertGreater(body["moved_m"], 0.0)
        self.assertFalse(body["idempotent_replay"])
        new_x, _ = self._player_position()
        self.assertNotAlmostEqual(x, new_x, places=6)

    def test_21_duplicate_command_over_http_is_suppressed(self) -> None:
        x, y = self._player_position()
        envelope = {
            "session_ref": SESSION,
            "command": "MOVE_TO_POINT",
            "command_ref": "HTTP-CR-MOVE-DUP",
            "params": {"iso_x_m": x + 3.0, "iso_y_m": y, "duration_s": 0.25},
        }
        _, first = self.server.post("/command", envelope)
        mid_x, mid_y = self._player_position()
        _, second = self.server.post("/command", envelope)
        after_x, after_y = self._player_position()

        self.assertEqual("PASS", first["status"])
        self.assertEqual("PASS", second["status"])
        self.assertTrue(second["idempotent_replay"])
        self.assertTrue(second["replay_suppressed"])
        self.assertEqual(first["moved_m"], second["moved_m"])
        self.assertEqual(mid_x, after_x)
        self.assertEqual(mid_y, after_y)

    def test_22_wrong_session_command_rejected(self) -> None:
        x, y = self._player_position()
        status, body = self.server.post(
            "/command",
            {
                "session_ref": "HTTP-WRONG-SESSION",
                "command": "MOVE_TO_POINT",
                "command_ref": "HTTP-CR-WRONG",
                "params": {"iso_x_m": x + 5.0, "iso_y_m": y},
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("REJECTED", body["status"])
        self.assertEqual("UNKNOWN_OR_INACTIVE_SESSION", body["reason"])
        self.assertEqual((x, y), self._player_position())

    def test_23_forged_player_ref_rejected(self) -> None:
        x, y = self._player_position()
        status, body = self.server.post(
            "/command",
            {
                "session_ref": SESSION,
                "command": "MOVE_TO_POINT",
                "command_ref": "HTTP-CR-FORGED-PLAYER",
                "params": {"iso_x_m": x + 5.0, "iso_y_m": y, "player_ref": "FORGED-PLAYER"},
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("REJECTED", body["status"])
        self.assertEqual("CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN", body["reason"])
        self.assertEqual((x, y), self._player_position())

    def test_24_forged_authority_rejected(self) -> None:
        x, y = self._player_position()
        status, body = self.server.post(
            "/command",
            {
                "session_ref": SESSION,
                "command": "MOVE_TO_POINT",
                "command_ref": "HTTP-CR-FORGED-AUTHORITY",
                "params": {
                    "iso_x_m": x + 5.0,
                    "iso_y_m": y,
                    "authority": "FORGED",
                    "damage_result": {"amount": 9999},
                },
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("REJECTED", body["status"])
        self.assertEqual("CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN", body["reason"])
        self.assertEqual((x, y), self._player_position())

    def test_25_invalid_json_body_is_a_domain_rejection(self) -> None:
        status, body = self.server.post("/command", None, raw=b"{not json")
        self.assertEqual(200, status)
        self.assertEqual("REJECTED", body["status"])
        self.assertEqual("INVALID_JSON_BODY", body["reason"])

    def test_26_command_ref_required_over_http(self) -> None:
        x, y = self._player_position()
        _, body = self.server.post(
            "/command",
            {
                "session_ref": SESSION,
                "command": "MOVE_TO_POINT",
                "params": {"iso_x_m": x + 1.0, "iso_y_m": y},
            },
        )
        self.assertEqual("REJECTED", body["status"])
        self.assertEqual("COMMAND_REF_REQUIRED", body["reason"])

    # ------------------------------------------------------------------ resync

    def test_30_resync_reports_stale_cursor_and_returns_fresh_snapshot(self) -> None:
        _, snap = self.server.get(f"/snapshot?session_ref={SESSION}")
        self.server.get(f"/snapshot?session_ref={SESSION}")
        status, body = self.server.post(
            "/session/resync",
            {
                "session_ref": SESSION,
                "last_snapshot_sequence": snap["snapshot_sequence"],
                "last_snapshot_id": snap["snapshot_id"],
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("PASS", body["status"])
        self.assertTrue(body["resync"])
        self.assertEqual("STALE_OR_DUPLICATE", body["cursor"]["cursor_status"])
        self.assertEqual("PASS", body["snapshot"]["status"])
        self.assertGreater(body["snapshot"]["snapshot_sequence"], snap["snapshot_sequence"])

    def test_31_reconnect_after_revoke(self) -> None:
        session = "GODOT-STAGE16B-HTTP-RECONNECT"
        self.server.post("/session/bind", {"session_ref": session})
        _, before = self.server.get(f"/snapshot?session_ref={session}")
        self.assertEqual("PASS", before["status"])

        _, revoked = self.server.post("/session/revoke", {"session_ref": session})
        self.assertEqual("PASS", revoked["status"])
        _, dead = self.server.get(f"/snapshot?session_ref={session}")
        self.assertEqual("UNKNOWN_OR_INACTIVE_SESSION", dead["reason"])

        _, rebound = self.server.post("/session/bind", {"session_ref": session})
        self.assertEqual("PASS", rebound["status"])
        _, after = self.server.get(f"/snapshot?session_ref={session}")
        self.assertEqual("PASS", after["status"])
        self.assertGreater(after["snapshot_sequence"], before["snapshot_sequence"])
        self.server.post("/session/revoke", {"session_ref": session})

    # ------------------------------------------------------------------ G16B-04

    def test_40_pickup_through_a_blocker_is_rejected_over_the_wire(self) -> None:
        """G16B-04 'through blocker' proved as a live HTTP round-trip.

        The Godot gate cannot hold this state: its ground-loot client re-confirms
        settle with its own reachability observation and overwrites reachable=false.
        Over plain HTTP there is no such client, so the authority decision is visible.
        """
        _, snapshot = self.server.get(f"/snapshot?session_ref={SESSION}")
        node = next(
            row
            for row in snapshot["gathering_nodes"]
            if str(row["activity_type"]) in {"LOGGING", "MINING", "FORAGING", "AGRICULTURE"}
            and int(row.get("remaining_units", 0)) > 4
        )

        drop_ref = ""
        for attempt in range(1, 9):
            _, gathered = self.server.post(
                "/command",
                {
                    "session_ref": SESSION,
                    "command": "REQUEST_GATHER",
                    "command_ref": f"HTTP-BLOCKER-GATHER-{attempt}",
                    "params": {"target_ref": node["target_ref"], "requested_units": 1},
                },
            )
            drop_ref = str(gathered.get("drop_ref") or "")
            if gathered.get("status") == "PASS" and drop_ref:
                break
        self.assertTrue(drop_ref, "authority produced no physical drop to test against")

        _, snapshot = self.server.get(f"/snapshot?session_ref={SESSION}")
        entry = next(row for row in snapshot["ground_loot"] if row["drop_ref"] == drop_ref)
        position = entry["candidate_position"]

        # Settle it in reach but behind a blocker.
        _, settled = self.server.post(
            "/command",
            {
                "session_ref": SESSION,
                "command": "CONFIRM_DROP_SETTLED",
                "command_ref": "HTTP-BLOCKER-SETTLE",
                "params": {
                    "target_ref": drop_ref,
                    "settled_position": {
                        "iso_x_m": float(position["iso_x_m"]),
                        "iso_y_m": float(position["iso_y_m"]),
                        "altitude_m": float(position["altitude_m"]),
                    },
                    "reachable": False,
                },
            },
        )
        self.assertEqual("PASS", settled["status"])

        status, pickup = self.server.post(
            "/command",
            {
                "session_ref": SESSION,
                "command": "REQUEST_PICKUP",
                "command_ref": "HTTP-BLOCKER-PICKUP",
                "params": {"target_ref": drop_ref},
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("REJECTED", pickup["status"])
        self.assertEqual("GROUND_LOOT_UNREACHABLE", pickup["reason"])
        self.assertTrue(pickup["reachable_evaluated_server_side"])

        # The drop is still there: a rejected pickup must not consume it.
        _, after = self.server.get(f"/snapshot?session_ref={SESSION}")
        self.assertIn(drop_ref, {row["drop_ref"] for row in after["ground_loot"]})

    # ------------------------------------------------------------------ restart

    def test_90_server_restart_preserves_authority_state(self) -> None:
        x, y = self._player_position()
        move_params = {"iso_x_m": x + 2.5, "iso_y_m": y, "duration_s": 0.25}
        _, moved = self.server.post(
            "/command",
            {
                "session_ref": SESSION,
                "command": "MOVE_TO_POINT",
                "command_ref": "HTTP-CR-RESTART",
                "params": move_params,
            },
        )
        self.assertEqual("PASS", moved["status"])
        _, last_snapshot = self.server.get(f"/snapshot?session_ref={SESSION}")
        position_before = self._player_position()
        world_before = last_snapshot["identity"]["world_instance_id"]

        self.server.stop()
        self.assertRaises(
            (urllib.error.URLError, ConnectionError, OSError),
            self.server.get,
            "/health",
        )

        restarted = LiveServer(self.port, self.var_dir, self.log_path)
        type(self).server = restarted
        restarted.start()
        health = restarted.wait_ready()

        self.assertEqual("RESUMED", health["bootstrap_mode"])
        self.assertEqual(world_before, health["identity"]["world_instance_id"])
        self.assertEqual("PASS", health["stage16a_health"])

        # Session survived: no rebind required.
        _, resumed = restarted.get(f"/snapshot?session_ref={SESSION}")
        self.assertEqual("PASS", resumed["status"])
        self.assertGreater(resumed["snapshot_sequence"], last_snapshot["snapshot_sequence"])

        # Motion state survived.
        self.assertAlmostEqual(position_before[0], float(resumed["transform"]["iso_x_m"]), places=6)
        self.assertAlmostEqual(position_before[1], float(resumed["transform"]["iso_y_m"]), places=6)

        # Command journal survived: the same command_ref is still suppressed.
        _, replay = restarted.post(
            "/command",
            {
                "session_ref": SESSION,
                "command": "MOVE_TO_POINT",
                "command_ref": "HTTP-CR-RESTART",
                "params": move_params,
            },
        )
        self.assertEqual("PASS", replay["status"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertTrue(replay["replay_suppressed"])
        self.assertEqual(position_before, self._player_position())


if __name__ == "__main__":
    unittest.main(verbosity=2)
