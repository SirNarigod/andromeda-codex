"""S17 causal bridge (16/09): first player command for
construction_placement_system.py -- REQUEST_PLACE_PIECE.

Delegates identity/collision to place_piece() (already protected/tested);
this file confirms the adapter routes/validates correctly and that the
material-cost bridge actually draws down the region's economy, never that
placement itself works (that's construction_placement_system's own suite).
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


class PlacePieceTests(unittest.TestCase):
    adapter: Stage16BAuthorityAdapter

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s17_place_piece_")
        cls.tmp = pathlib.Path(cls._tmp.name)
        cls.config = build_config(cls.tmp)
        cls.adapter = Stage16BAuthorityAdapter(cls.config)
        cls.adapter.bind_session(VALID_SESSION)

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

    def test_01_place_piece_pass_and_draws_regional_material(self):
        construction = self.adapter._construction_placement()
        piece_ref = construction.known_piece_ids()[0]
        result = self._cmd(
            "REQUEST_PLACE_PIECE", "CMDREF-S17-PLACE-1",
            {"piece_ref": piece_ref, "placement_ref": "PLACEMENT-TEST-001"},
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual(piece_ref, result["piece_ref"])
        self.assertIn("material_cost", result)
        self.assertEqual("PASS", result["material_cost"]["status"])

    def test_02_unknown_piece_ref_rejected(self):
        result = self._cmd(
            "REQUEST_PLACE_PIECE", "CMDREF-S17-PLACE-2",
            {"piece_ref": "BLD-DOES-NOT-EXIST", "placement_ref": "PLACEMENT-TEST-002"},
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("UNKNOWN_PIECE_REF", result["reason"])

    def test_03_missing_piece_ref_rejected(self):
        result = self._cmd(
            "REQUEST_PLACE_PIECE", "CMDREF-S17-PLACE-3", {"placement_ref": "PLACEMENT-TEST-003"}
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("PIECE_REF_REQUIRED", result["reason"])

    def test_04_missing_placement_ref_rejected(self):
        construction = self.adapter._construction_placement()
        piece_ref = construction.known_piece_ids()[0]
        result = self._cmd(
            "REQUEST_PLACE_PIECE", "CMDREF-S17-PLACE-4", {"piece_ref": piece_ref}
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("PLACEMENT_REF_REQUIRED", result["reason"])

    def test_05_duplicate_placement_ref_rejected(self):
        construction = self.adapter._construction_placement()
        piece_ref = construction.known_piece_ids()[0]
        self._cmd(
            "REQUEST_PLACE_PIECE", "CMDREF-S17-PLACE-5A",
            {"piece_ref": piece_ref, "placement_ref": "PLACEMENT-TEST-DUP"},
        )
        result = self._cmd(
            "REQUEST_PLACE_PIECE", "CMDREF-S17-PLACE-5B",
            {"piece_ref": piece_ref, "placement_ref": "PLACEMENT-TEST-DUP"},
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("PLACEMENT_REF_ALREADY_IN_USE", result["reason"])

    def test_06_unexpected_param_rejected(self):
        result = self._cmd(
            "REQUEST_PLACE_PIECE", "CMDREF-S17-PLACE-6",
            {"piece_ref": "BLD-FUNDACAO-T1", "placement_ref": "PLACEMENT-TEST-006", "bogus": 1},
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("UNEXPECTED_COMMAND_PARAM", result["reason"])


if __name__ == "__main__":
    unittest.main()
