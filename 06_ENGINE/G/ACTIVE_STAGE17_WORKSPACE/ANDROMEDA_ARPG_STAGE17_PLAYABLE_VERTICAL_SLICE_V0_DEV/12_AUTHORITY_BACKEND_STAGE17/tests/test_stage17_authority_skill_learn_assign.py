"""Fase 8.1 (Stage17, 14/09): comandos de aprender/atribuir skill no adapter.

Fecha o resto da lacuna deixada deliberadamente aberta na fase 7.1
(REQUEST_USE_SKILL): REQUEST_LEARN_SKILL, REQUEST_ASSIGN_ACTIVE_SKILL,
REQUEST_ACTIVATE_PASSIVE_SKILL. Cada comando delega 100% aos metodos ja
protegidos/testados de ARPGSkillCore - este arquivo so confirma que o adapter
roteia/valida corretamente, nunca reimplementa regra de negocio.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from andromeda_authority_adapter import Stage16BAuthorityAdapter  # noqa: E402
from test_stage16b_authority_adapter import build_config, VALID_SESSION  # noqa: E402


class SkillLearnAssignTests(unittest.TestCase):
    adapter: Stage16BAuthorityAdapter

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s17_skill_")
        cls.tmp = pathlib.Path(cls._tmp.name)
        cls.config = build_config(cls.tmp)
        cls.adapter = Stage16BAuthorityAdapter(cls.config)
        cls.adapter.bind_session(VALID_SESSION)
        # S17 causal bridge (fase seguinte a 8.1): aprender skill agora cobra
        # ouro (system_causal_bridges.apply_skill_learn_cost). Este arquivo
        # so testa roteamento/validacao do comando, nao economia -- garante
        # saldo alto o bastante pra nenhum dos ~6 learns desta suite esbarrar
        # em REJECTED por falta de fundos.
        economy = cls.adapter._engine.economy_arpg(cls.adapter.world_instance_id)
        economy.ensure_wallet(cls.adapter.profile_ref)
        economy._set_balance(cls.adapter.profile_ref, 100000.0)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def _cmd(self, command: str, command_ref: str, params: dict) -> dict:
        return self.adapter.command(
            {
                "session_ref": VALID_SESSION,
                "command": command,
                "command_ref": command_ref,
                "params": params,
            }
        )

    def test_01_learn_skill_pass(self) -> None:
        result = self._cmd(
            "REQUEST_LEARN_SKILL", "CMDREF-S17-LEARN-1",
            {"skill_ref": "SKL-GP-PRECISION-STRIKE"},
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual("SKL-GP-PRECISION-STRIKE", result["skill_ref"])
        self.assertEqual(1, result["rank"])

    def test_02_learn_same_skill_twice_rejected(self) -> None:
        self._cmd("REQUEST_LEARN_SKILL", "CMDREF-S17-LEARN-2A",
                   {"skill_ref": "SKL-GP-FOCUS-PULSE"})
        result = self._cmd("REQUEST_LEARN_SKILL", "CMDREF-S17-LEARN-2B",
                            {"skill_ref": "SKL-GP-FOCUS-PULSE"})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("SKILL_ALREADY_LEARNED", result["reason"])

    def test_03_learn_missing_skill_ref_rejected(self) -> None:
        result = self._cmd("REQUEST_LEARN_SKILL", "CMDREF-S17-LEARN-3", {})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("SKILL_REF_REQUIRED", result["reason"])

    def test_04_learn_replay_is_idempotent(self) -> None:
        r1 = self._cmd("REQUEST_LEARN_SKILL", "CMDREF-S17-LEARN-4",
                        {"skill_ref": "SKL-GP-SWIFT-DISCIPLINE"})
        r2 = self._cmd("REQUEST_LEARN_SKILL", "CMDREF-S17-LEARN-4",
                        {"skill_ref": "SKL-GP-SWIFT-DISCIPLINE"})
        self.assertEqual("PASS", r1["status"])
        self.assertTrue(r2["idempotent_replay"])

    def test_10_assign_active_pass(self) -> None:
        self._cmd("REQUEST_LEARN_SKILL", "CMDREF-S17-ASSIGN-SETUP",
                   {"skill_ref": "SKL-GP-POWER-STRIKE"})
        result = self._cmd(
            "REQUEST_ASSIGN_ACTIVE_SKILL", "CMDREF-S17-ASSIGN-1",
            {"skill_ref": "SKL-GP-POWER-STRIKE", "slot": 2},
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual(2, result["slot"])

    def test_11_assign_active_out_of_range_rejected(self) -> None:
        result = self._cmd(
            "REQUEST_ASSIGN_ACTIVE_SKILL", "CMDREF-S17-ASSIGN-2",
            {"skill_ref": "SKL-GP-POWER-STRIKE", "slot": 99},
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("ACTIVE_SLOT_OUT_OF_RANGE", result["reason"])

    def test_12_assign_active_for_passive_skill_rejected(self) -> None:
        self._cmd("REQUEST_LEARN_SKILL", "CMDREF-S17-ASSIGN-SETUP-2",
                   {"skill_ref": "SKL-GP-GUARD-DISCIPLINE"})
        result = self._cmd(
            "REQUEST_ASSIGN_ACTIVE_SKILL", "CMDREF-S17-ASSIGN-3",
            {"skill_ref": "SKL-GP-GUARD-DISCIPLINE", "slot": 1},
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("SKILL_NOT_ACTIVE", result["reason"])

    def test_20_activate_passive_pass(self) -> None:
        self._cmd("REQUEST_LEARN_SKILL", "CMDREF-S17-PASSIVE-SETUP",
                   {"skill_ref": "SKL-GP-FOCUS-DISCIPLINE"})
        result = self._cmd(
            "REQUEST_ACTIVATE_PASSIVE_SKILL", "CMDREF-S17-PASSIVE-1",
            {"skill_ref": "SKL-GP-FOCUS-DISCIPLINE", "slot": 3},
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual(3, result["slot"])

    def test_21_activate_passive_out_of_range_rejected(self) -> None:
        result = self._cmd(
            "REQUEST_ACTIVATE_PASSIVE_SKILL", "CMDREF-S17-PASSIVE-2",
            {"skill_ref": "SKL-GP-FOCUS-DISCIPLINE", "slot": 99},
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("PASSIVE_SLOT_OUT_OF_RANGE", result["reason"])

    def test_30_snapshot_skill_projection_reflects_learn_and_assign(self) -> None:
        snap = self.adapter.snapshot(VALID_SESSION)
        skills = snap["skill_projection"]["skills"]
        self.assertIn("SKL-GP-PRECISION-STRIKE", skills)
        self.assertIn("SKL-GP-POWER-STRIKE", snap["skill_projection"]["active_slots"])
        self.assertIn("SKL-GP-FOCUS-DISCIPLINE", snap["skill_projection"]["passive_slots"])


if __name__ == "__main__":
    unittest.main()
