"""G16B-19B: REQUEST_NPC_DIALOGUE backend authority suite.

Covers the minimal production dialogue transport that closes G16B-19's
DIALOGUE_TRANSPORT_GAP at the backend layer only (Godot integration is
explicitly deferred to G16B-19C -- see andromeda_authority_adapter.py's
_request_npc_dialogue() docstring and authority_npc_dialogue_content.py).
"""

from __future__ import annotations

import dataclasses
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
sys.path.insert(0, str(PROJECT_ROOT / "01_RUNTIME"))

from andromeda_authority_adapter import Stage16BAuthorityAdapter  # noqa: E402
from authority_config import AuthorityConfig, _resolve_master_path, verify_master  # noqa: E402
from authority_npc_dialogue_content import DIALOGUE_CONTENT  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

COMMAND = "REQUEST_NPC_DIALOGUE"
DIALOGUE_REF = "DLG-S12-FRONTIER"
RELATED_QUEST_REF = "QST-S12-VARGA-ORIENTATION"


def build_config(root: pathlib.Path, owner_scope: str, *, seed: int = 990111) -> AuthorityConfig:
    master = _resolve_master_path()
    return AuthorityConfig(
        master_release_path=master,
        master_release_sha256=verify_master(master),
        runtime_dir=PROJECT_ROOT / "01_RUNTIME",
        db_path=root / "world.sqlite",
        save_root=root / "saves",
        owner_scope=owner_scope,
        world_seed=seed,
        player_class="WARRIOR",
        development_profile_bootstrap=True,
    )


class Stage16BNpcDialogueTransportTests(unittest.TestCase):
    """Backend-only: identity, content, transport, security, replay."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_npcdialogue_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root, "stage16b:npc-dialogue"))
        cls.session = "S16B-NPCDIALOGUE"
        cls.bind = cls.adapter.bind_session(cls.session)
        cls.npc_ref = cls.adapter.development_profile_bootstrap["dialogue_npc_ref"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {"session_ref": self.session, "command": COMMAND, "command_ref": ref, "params": params}
        )

    # -- 1/4/7/8/9 real NPC, anchor, speech acts, copy authority --------

    def test_01_advertised_in_enabled_commands(self) -> None:
        self.assertIn(COMMAND, self.bind["enabled_commands"])

    def test_02_dev_bootstrap_seeded_a_real_eligible_npc(self) -> None:
        self.assertTrue(self.npc_ref)
        country = self.adapter._engine.country(self.adapter.world_instance_id)
        npc = country.npc(self.npc_ref)  # raises KeyError if not real
        self.assertNotEqual("CHILD", npc.get("class"))
        self.assertFalse((npc.get("protection") or {}).get("protected", False))

    def test_03_npc_real_dialogue_brief_real_content_bound(self) -> None:
        result = self.command("NPCD-BASIC", {"request_ref": "NPCD-BASIC:UI", "npc_target_ref": self.npc_ref})
        self.assertEqual("PASS", result["status"])
        self.assertEqual(self.npc_ref, result["npc_ref"])
        self.assertEqual(DIALOGUE_REF, result["dialogue_ref"])
        self.assertEqual("CIT-001", result["anchor_ref"])
        self.assertEqual(DIALOGUE_CONTENT[DIALOGUE_REF]["line"], result["line"])
        self.assertTrue(result["speech_acts"])
        self.assertTrue(result["source_refs"])
        self.assertEqual(
            "GAMEPLAY_PLACEHOLDER_COPY_NOT_CANON_DIALOGUE", result["copy_authority"]
        )
        self.assertTrue(result["server_authoritative"])
        self.assertEqual("ANDROMEDA_ARPG_STAGE12_NARRATIVE_CULTURE_QUESTS", result["authority"])

    # -- 5/6 real quest binding -------------------------------------------

    def test_04_related_quest_real_and_validated(self) -> None:
        result = self.command("NPCD-QUEST", {"request_ref": "NPCD-QUEST:UI", "npc_target_ref": self.npc_ref})
        self.assertEqual(RELATED_QUEST_REF, result["related_quest_ref"])
        narrative = self.adapter._engine.narrative_arpg(self.adapter.world_instance_id)
        known = {str(t["quest_ref"]) for t in narrative.list_quest_templates()}
        self.assertIn(result["related_quest_ref"], known)

    # -- 12/13 choices not required, branching explicit -------------------

    def test_05_no_branching_required(self) -> None:
        result = self.command("NPCD-CHOICES", {"request_ref": "NPCD-CHOICES:UI", "npc_target_ref": self.npc_ref})
        self.assertEqual([], result["choices"])
        self.assertFalse(result["branching_required"])

    # -- 5/6 security: unknown/forbidden/invalid ---------------------------

    def test_06_unknown_npc_ref_rejected(self) -> None:
        result = self.command("NPCD-UNKNOWN", {"request_ref": "NPCD-UNKNOWN:UI", "npc_target_ref": "NPC-DOES-NOT-EXIST"})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("UNKNOWN_NPC_REF", result["reason"])

    def test_07_client_supplied_dialogue_ref_rejected(self) -> None:
        result = self.command(
            "NPCD-FORBID-DREF",
            {"request_ref": "NPCD-FORBID-DREF:UI", "npc_target_ref": self.npc_ref, "dialogue_ref": "DLG-S12-WORKSHOP"},
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("UNEXPECTED_COMMAND_PARAM", result["reason"])

    def test_08_client_supplied_line_rejected(self) -> None:
        result = self.command(
            "NPCD-FORBID-LINE",
            {"request_ref": "NPCD-FORBID-LINE:UI", "npc_target_ref": self.npc_ref, "line": "hacked line"},
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("UNEXPECTED_COMMAND_PARAM", result["reason"])

    def test_09_client_supplied_quest_ref_rejected(self) -> None:
        result = self.command(
            "NPCD-FORBID-QREF",
            {"request_ref": "NPCD-FORBID-QREF:UI", "npc_target_ref": self.npc_ref, "quest_ref": "QST-S12-BRIDGE-CONTINUITY"},
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("UNEXPECTED_COMMAND_PARAM", result["reason"])

    def test_10_forbidden_authority_keys_rejected(self) -> None:
        for field, value in (("npc_ref", self.npc_ref), ("actor_ref", self.npc_ref), ("entity_ref", self.npc_ref)):
            with self.subTest(field=field):
                result = self.command(
                    f"NPCD-FORBID-{field}",
                    {"request_ref": f"NPCD-FORBID-{field}:UI", "npc_target_ref": self.npc_ref, field: value},
                )
                self.assertEqual("REJECTED", result["status"])

    def test_11_missing_npc_target_ref_rejected(self) -> None:
        result = self.command("NPCD-MISSING", {"request_ref": "NPCD-MISSING:UI"})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("NPC_TARGET_REF_REQUIRED", result["reason"])

    def test_12_child_npc_rejected(self) -> None:
        country = self.adapter._engine.country(self.adapter.world_instance_id)
        child_ref = next(n["id"] for n in country._all_npc_records() if n.get("class") == "CHILD")
        result = self.command("NPCD-CHILD", {"request_ref": "NPCD-CHILD:UI", "npc_target_ref": child_ref})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("NPC_NOT_DIALOGUE_ELIGIBLE", result["reason"])

    def test_13_protected_worker_npc_rejected(self) -> None:
        country = self.adapter._engine.country(self.adapter.world_instance_id)
        worker_ref = next(
            n["id"] for n in country._all_npc_records()
            if n.get("class") == "WORKER" and (n.get("protection") or {}).get("protected")
        )
        result = self.command("NPCD-WORKER", {"request_ref": "NPCD-WORKER:UI", "npc_target_ref": worker_ref})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("NPC_NOT_DIALOGUE_ELIGIBLE", result["reason"])

    # -- 10/11 replay/idempotency ------------------------------------------

    def test_14_replay_same_command_ref_same_result(self) -> None:
        first = self.command("NPCD-REPLAY", {"request_ref": "NPCD-REPLAY:UI", "npc_target_ref": self.npc_ref})
        self.assertEqual("PASS", first["status"])
        second = self.command("NPCD-REPLAY", {"request_ref": "NPCD-REPLAY:UI", "npc_target_ref": self.npc_ref})
        self.assertEqual("PASS", second["status"])
        self.assertEqual(first["line"], second["line"])
        self.assertEqual(first["dialogue_ref"], second["dialogue_ref"])
        self.assertEqual(first["related_quest_ref"], second["related_quest_ref"])

    def test_15_no_quest_mutation_before_accept_quest(self) -> None:
        narrative = self.adapter._engine.narrative_arpg(self.adapter.world_instance_id)
        before = narrative.list_quests(self.adapter.profile_ref)
        self.command("NPCD-NOMUTATE", {"request_ref": "NPCD-NOMUTATE:UI", "npc_target_ref": self.npc_ref})
        after = narrative.list_quests(self.adapter.profile_ref)
        self.assertEqual(before, after, "dialogue must never itself accept/mutate the quest")

    def test_16_json_serializable_no_nan_or_inf(self) -> None:
        result = self.command("NPCD-JSON", {"request_ref": "NPCD-JSON:UI", "npc_target_ref": self.npc_ref})
        response = JSONResponse(result)
        rendered = response.render(result)  # raises ValueError on NaN/inf (allow_nan=False)
        self.assertGreater(len(rendered), 0)

    # -- 20 dialogue -> ACCEPT_QUEST backend chain, no Godot ---------------

    def test_17_dialogue_to_accept_quest_backend_chain_real(self) -> None:
        dialogue = self.command(
            "NPCD-CHAIN-DIALOGUE", {"request_ref": "NPCD-CHAIN-DIALOGUE:UI", "npc_target_ref": self.npc_ref}
        )
        self.assertEqual("PASS", dialogue["status"], "DIALOGUE_RELATED_QUEST_REAL")
        quest_ref = dialogue["related_quest_ref"]
        self.assertTrue(quest_ref)

        accept = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "ACCEPT_QUEST",
                "command_ref": "NPCD-CHAIN-ACCEPT",
                "params": {"request_ref": "NPCD-CHAIN-ACCEPT:UI", "quest_ref": quest_ref},
            }
        )
        self.assertEqual("PASS", accept["status"], "DIALOGUE_TO_ACCEPT_QUEST_BACKEND_CHAIN_REAL")
        self.assertEqual("ACTIVE", accept["quest"]["state"])


class Stage16BDialogueNpcProjectionTests(unittest.TestCase):
    """G16B-19C1: dialogue_npc_projection closes DIALOGUE_TARGET_IDENTITY_PROJECTION_GAP."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_npcdialogue_projection_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root, "stage16b:npc-dialogue-projection"))
        cls.session = "S16B-NPCDIALOGUE-PROJECTION"
        cls.adapter.bind_session(cls.session)
        cls.snapshot = cls.adapter.snapshot(cls.session)
        cls.projection = cls.snapshot["dialogue_npc_projection"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def test_01_bootstrap_produced_a_real_dialogue_npc_ref(self) -> None:
        bootstrap_ref = self.adapter.development_profile_bootstrap.get("dialogue_npc_ref")
        self.assertTrue(bootstrap_ref)

    def test_02_snapshot_contains_dialogue_npc_projection(self) -> None:
        self.assertEqual("PASS", self.snapshot["status"])
        self.assertIn("dialogue_npc_projection", self.snapshot)

    def test_03_projected_npc_ref_equals_bootstrap_ref(self) -> None:
        bootstrap_ref = self.adapter.development_profile_bootstrap.get("dialogue_npc_ref")
        self.assertTrue(self.projection["available"])
        self.assertEqual(bootstrap_ref, self.projection["npc_ref"])

    def test_04_projected_npc_ref_resolves_in_country_npc(self) -> None:
        country = self.adapter._engine.country(self.adapter.world_instance_id)
        npc = country.npc(self.projection["npc_ref"])  # raises KeyError if not real
        self.assertTrue(npc.get("id"))

    def test_05_projected_target_is_dialogue_eligible(self) -> None:
        country = self.adapter._engine.country(self.adapter.world_instance_id)
        npc = country.npc(self.projection["npc_ref"])
        self.assertNotEqual("CHILD", npc.get("class"))
        self.assertFalse((npc.get("protection") or {}).get("protected", False))
        self.assertEqual("ACTIVE", str(npc.get("status", "ACTIVE")).upper())

    def test_06_projected_target_is_not_combat_common(self) -> None:
        common_ref = self.adapter._bootstrap_get("combat_target_common_ref")
        self.assertNotEqual(common_ref, self.projection["npc_ref"])

    def test_07_projected_target_is_not_combat_alpha(self) -> None:
        alpha_ref = self.adapter._bootstrap_get("combat_target_alpha_ref")
        self.assertNotEqual(alpha_ref, self.projection["npc_ref"])

    def test_08_authority_label_explicit_and_non_canonical(self) -> None:
        self.assertEqual(
            "STAGE16B_SERVER_SELECTED_DEVELOPMENT_DIALOGUE_TARGET", self.projection["authority"]
        )
        self.assertFalse(self.projection["canonical_identity"])

    def test_09_full_bootstrap_dict_not_leaked(self) -> None:
        leaking_keys = {"combat_encounter", "granted_instance_refs_this_boot", "weapon_loadout", "clothes_grant"}
        self.assertFalse(leaking_keys & set(self.projection.keys()))
        self.assertEqual({"available", "npc_ref", "canonical_identity", "authority"}, set(self.projection.keys()))

    def test_10_json_serializable(self) -> None:
        response = JSONResponse(self.snapshot)
        rendered = response.render(self.snapshot)  # raises ValueError on NaN/inf
        self.assertGreater(len(rendered), 0)

    def test_11_request_npc_dialogue_using_projected_ref_pass(self) -> None:
        result = self.adapter.command(
            {
                "session_ref": self.session,
                "command": COMMAND,
                "command_ref": "PROJ-DIALOGUE-01",
                "params": {"request_ref": "PROJ-DIALOGUE-01:UI", "npc_target_ref": self.projection["npc_ref"]},
            }
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual(self.projection["npc_ref"], result["npc_ref"])
        self.assertTrue(result["server_authoritative"])

    def test_12_related_quest_still_real(self) -> None:
        result = self.adapter.command(
            {
                "session_ref": self.session,
                "command": COMMAND,
                "command_ref": "PROJ-DIALOGUE-02",
                "params": {"request_ref": "PROJ-DIALOGUE-02:UI", "npc_target_ref": self.projection["npc_ref"]},
            }
        )
        self.assertEqual(RELATED_QUEST_REF, result["related_quest_ref"])

    def test_13_accept_quest_still_works_with_projected_chain(self) -> None:
        dialogue = self.adapter.command(
            {
                "session_ref": self.session,
                "command": COMMAND,
                "command_ref": "PROJ-DIALOGUE-03",
                "params": {"request_ref": "PROJ-DIALOGUE-03:UI", "npc_target_ref": self.projection["npc_ref"]},
            }
        )
        accept = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "ACCEPT_QUEST",
                "command_ref": "PROJ-ACCEPT-03",
                "params": {"request_ref": "PROJ-ACCEPT-03:UI", "quest_ref": dialogue["related_quest_ref"]},
            }
        )
        self.assertEqual("PASS", accept["status"])
        self.assertEqual("ACTIVE", accept["quest"]["state"])


class Stage16BDialogueNpcProjectionNoDevTests(unittest.TestCase):
    """Section 14 item: outside development bootstrap, projection is explicit, never fabricated."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_npcdialogue_projection_nodev_")
        cls.root = pathlib.Path(cls._tmp.name)
        cfg = dataclasses.replace(
            build_config(cls.root, "stage16b:npc-dialogue-projection-nodev"),
            development_profile_bootstrap=False,
        )
        cls.adapter = Stage16BAuthorityAdapter(cfg)
        cls.session = "S16B-NPCDIALOGUE-PROJECTION-NODEV"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def test_01_projection_explicitly_unavailable_not_fabricated(self) -> None:
        projection = self.adapter._dialogue_npc_projection()
        self.assertFalse(projection["available"])
        self.assertIsNone(projection["npc_ref"])
        self.assertEqual(
            "STAGE16B_SERVER_SELECTED_DEVELOPMENT_DIALOGUE_TARGET", projection["authority"]
        )

    def test_02_no_exception_raised(self) -> None:
        # The mere act of calling it outside development profile must not raise.
        try:
            self.adapter._dialogue_npc_projection()
        except Exception as exc:  # pragma: no cover - defensive
            self.fail(f"_dialogue_npc_projection() raised outside dev profile: {exc}")


class Stage16BNpcDialogueGuardTests(unittest.TestCase):
    """development_profile_bootstrap=False must not disable REQUEST_NPC_DIALOGUE.

    Unlike the ATTEMPT_DEVELOPMENT_*/ADVANCE_DEVELOPMENT_* commands, this is a
    PRODUCTION command (Section 8) -- it must keep working with any real,
    eligible npc_target_ref regardless of the development bootstrap flag. Only
    the convenience dialogue_npc_ref seed is unavailable outside development
    bootstrap, so this test discovers a real eligible NPC itself.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_npcdialogue_noprofile_")
        cls.root = pathlib.Path(cls._tmp.name)
        cfg = dataclasses.replace(
            build_config(cls.root, "stage16b:npc-dialogue-noprofile"),
            development_profile_bootstrap=False,
        )
        cls.adapter = Stage16BAuthorityAdapter(cfg)
        cls.session = "S16B-NPCDIALOGUE-NOPROFILE"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def test_01_command_available_outside_development_profile(self) -> None:
        npc_ref = self.adapter._select_dialogue_eligible_npc()
        self.assertTrue(npc_ref)
        result = self.adapter.command(
            {
                "session_ref": self.session,
                "command": COMMAND,
                "command_ref": "NPCD-NOPROFILE",
                "params": {"request_ref": "NPCD-NOPROFILE:UI", "npc_target_ref": npc_ref},
            }
        )
        self.assertEqual("PASS", result["status"])
        self.assertFalse(result.get("development_only", False))


# ------------------------------------------------------------------ HTTP


PYTHON = sys.executable
BOOT_TIMEOUT_S = 300.0


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _LiveServer:
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
        env["ANDROMEDA_S16B_SEED"] = "990111"
        env["ANDROMEDA_S16B_OWNER_SCOPE"] = "stage16b:npc-dialogue-http"
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

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path: str, headers: dict | None = None) -> tuple[int, dict]:
        request = urllib.request.Request(self._url(path), headers=headers or {})
        return self._send(request)

    def post(self, path: str, payload) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
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


class Stage16BNpcDialogueHttpTests(unittest.TestCase):
    """Section 19: REQUEST_NPC_DIALOGUE executed for real over HTTP."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_npcdialogue_http_")
        cls.var_dir = pathlib.Path(cls._tmp.name)
        cls.log_path = cls.var_dir / "uvicorn.log"
        cls.port = free_port()
        cls.server = _LiveServer(cls.port, cls.var_dir, cls.log_path)
        cls.server.start()
        cls.server.wait_ready()
        cls.session = "HTTP-NPCDIALOGUE-001"
        cls.server.post("/session/bind", {"session_ref": cls.session})
        _, health = cls.server.get("/health")
        cls.npc_ref = health["development_profile_bootstrap"]["dialogue_npc_ref"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        try:
            cls._tmp.cleanup()
        except OSError:
            pass

    def test_01_dialogue_over_http_pass_no_nan_or_inf(self) -> None:
        self.assertTrue(self.npc_ref)
        status, body = self.server.post(
            "/command",
            {
                "session_ref": self.session,
                "command": COMMAND,
                "command_ref": "HTTP-NPCD-01",
                "params": {"request_ref": "HTTP-NPCD-01:UI", "npc_target_ref": self.npc_ref},
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("PASS", body["status"])
        self.assertEqual(DIALOGUE_REF, body["dialogue_ref"])
        self.assertEqual(RELATED_QUEST_REF, body["related_quest_ref"])
        response = JSONResponse(body)
        rendered = response.render(body)  # raises ValueError on NaN/inf
        self.assertGreater(len(rendered), 0)

    def test_03_snapshot_projects_dialogue_npc_then_dialogue_over_http(self) -> None:
        """Section 9: REQUEST_SNAPSHOT -> dialogue_npc_projection.npc_ref -> REQUEST_NPC_DIALOGUE, no local injection."""
        status, snap = self.server.get(f"/snapshot?session_ref={self.session}")
        self.assertEqual(200, status)
        self.assertEqual("PASS", snap["status"])
        projection = snap["dialogue_npc_projection"]
        self.assertTrue(projection["available"])
        projected_ref = projection["npc_ref"]
        self.assertTrue(projected_ref)

        status, body = self.server.post(
            "/command",
            {
                "session_ref": self.session,
                "command": COMMAND,
                "command_ref": "HTTP-NPCD-03",
                "params": {"request_ref": "HTTP-NPCD-03:UI", "npc_target_ref": projected_ref},
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("PASS", body["status"])
        self.assertTrue(body["server_authoritative"])
        self.assertEqual(projected_ref, body["npc_ref"])

    def test_02_unknown_npc_over_http_is_a_domain_rejection_not_a_500(self) -> None:
        status, body = self.server.post(
            "/command",
            {
                "session_ref": self.session,
                "command": COMMAND,
                "command_ref": "HTTP-NPCD-02",
                "params": {"request_ref": "HTTP-NPCD-02:UI", "npc_target_ref": "NPC-DOES-NOT-EXIST"},
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("REJECTED", body["status"])
        self.assertEqual("UNKNOWN_NPC_REF", body["reason"])


if __name__ == "__main__":
    unittest.main()
