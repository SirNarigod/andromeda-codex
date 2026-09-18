"""Stage17 / Etapa 31 -- S17-C3R1 unit tests for the hardened player-position
recovery tool.

These tests never touch the real Stage17 world DB and never call --apply.
They exercise the pure manifest-validation logic against synthetic fixtures,
the world-guard comparison logic, and static source-inspection checks that
the tool itself contains no hardcoded destination/avatar_ref, no SQL DML,
and no reference to the protected C1B/C1/C2 resource-placement module.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_PATH = (
    Path(__file__).resolve().parents[1]
    / "recovery"
    / "repair_stage17_player_position.py"
)

_spec = importlib.util.spec_from_file_location("repair_stage17_player_position", TOOL_PATH)
tool = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = tool
_spec.loader.exec_module(tool)  # type: ignore[union-attr]


def _write_manifest(tmp_path: Path, canonical_manifest: dict) -> Path:
    envelope = {
        "canonical_manifest": canonical_manifest,
        "canonical_manifest_hash": tool.load_and_validate_manifest.__module__ and "",
        "schema": "S17_RESOURCE_PLACEMENT_ENVELOPE_V1",
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    return path


def _valid_canonical_manifest(**overrides) -> dict:
    base = {
        "schema_version": tool.EXPECTED_SCHEMA_VERSION,
        "placement_revision": "S17-RESOURCE-PLACEMENT-DEV-R0001",
        "placements": [{"placement_ref": "RESOURCE-PLACEMENT-S17-TEST0000000000000000"}],
        "constraints": [],
        "world_binding": {
            "world_instance_id": "rt:world:testworld00000000000000000000",
            "anchor_kind": next(iter(tool.ACCEPTED_ANCHOR_KINDS)),
            "anchor_player_ref": "PLY-TEST0000000000000000000000000000",
            "anchor_snapshot_hash": "deadbeef",
            "anchor_position": {"iso_x_m": 10.0, "iso_y_m": -20.0, "altitude_m": 0.0},
            "zone_ref": "ZONE-TEST",
            "block_ref": "BLK-TEST",
        },
    }
    base.update(overrides)
    return base


class ManifestValidationTests(unittest.TestCase):
    def test_01_valid_manifest_parses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_manifest(Path(tmp), _valid_canonical_manifest())
            info = tool.load_and_validate_manifest(path)
            self.assertEqual(info["anchor_position"]["iso_x_m"], 10.0)
            self.assertEqual(info["manifest_world_instance_id"], "rt:world:testworld00000000000000000000")
            self.assertEqual(len(info["manifest_sha256"]), 64)

    def test_02_missing_file_raises_manifest_not_found(self) -> None:
        with self.assertRaises(tool.RecoveryError) as ctx:
            tool.load_and_validate_manifest(Path("/does/not/exist/manifest.json"))
        self.assertEqual(ctx.exception.code, "MANIFEST_NOT_FOUND")

    def test_03_wrong_schema_version_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_manifest(Path(tmp), _valid_canonical_manifest(schema_version="WRONG_VERSION"))
            with self.assertRaises(tool.RecoveryError) as ctx:
                tool.load_and_validate_manifest(path)
            self.assertEqual(ctx.exception.code, "MANIFEST_INVALID")

    def test_04_nan_anchor_rejected(self) -> None:
        manifest = _valid_canonical_manifest()
        manifest["world_binding"]["anchor_position"] = {"iso_x_m": float("nan"), "iso_y_m": 1.0, "altitude_m": 0.0}
        with tempfile.TemporaryDirectory() as tmp:
            # json.dumps cannot emit NaN as valid JSON by default in this tool's
            # reader (it uses json.loads on strict text), so inject a literal
            # NaN token the way a corrupted file might contain it.
            path = Path(tmp) / "manifest.json"
            envelope_text = json.dumps({
                "canonical_manifest": {k: v for k, v in manifest.items() if k != "world_binding"},
                "canonical_manifest_hash": "",
                "schema": "S17_RESOURCE_PLACEMENT_ENVELOPE_V1",
            })
            # Reconstruct by hand so we can splice a NaN literal in (Python's
            # json.dumps refuses allow_nan=False, and we want the reader's own
            # guard exercised, not the writer's).
            wb = dict(manifest["world_binding"])
            wb["anchor_position"] = {"iso_x_m": "__NAN__", "iso_y_m": 1.0, "altitude_m": 0.0}
            full = dict(manifest)
            full["world_binding"] = wb
            text = json.dumps({"canonical_manifest": full, "canonical_manifest_hash": "", "schema": "x"})
            text = text.replace('"__NAN__"', "NaN")
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(tool.RecoveryError) as ctx:
                tool.load_and_validate_manifest(path)
            self.assertEqual(ctx.exception.code, "NON_FINITE_POSITION")

    def test_05_missing_world_binding_rejected(self) -> None:
        manifest = _valid_canonical_manifest()
        del manifest["world_binding"]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_manifest(Path(tmp), manifest)
            with self.assertRaises(tool.RecoveryError) as ctx:
                tool.load_and_validate_manifest(path)
            self.assertEqual(ctx.exception.code, "MANIFEST_INVALID")

    def test_06_unaccepted_anchor_kind_rejected(self) -> None:
        manifest = _valid_canonical_manifest()
        manifest["world_binding"]["anchor_kind"] = "SOME_OTHER_KIND"
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_manifest(Path(tmp), manifest)
            with self.assertRaises(tool.RecoveryError) as ctx:
                tool.load_and_validate_manifest(path)
            self.assertEqual(ctx.exception.code, "ANCHOR_INVALID")

    def test_07_missing_altitude_rejected_not_defaulted(self) -> None:
        manifest = _valid_canonical_manifest()
        manifest["world_binding"]["anchor_position"] = {"iso_x_m": 1.0, "iso_y_m": 2.0}
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_manifest(Path(tmp), manifest)
            with self.assertRaises(tool.RecoveryError) as ctx:
                tool.load_and_validate_manifest(path)
            self.assertEqual(ctx.exception.code, "ANCHOR_INVALID")


class WorldGuardTests(unittest.TestCase):
    def test_08_matching_world_passes(self) -> None:
        tool.enforce_world_guard("rt:world:aaa", "rt:world:aaa")  # must not raise

    def test_09_mismatched_world_aborts(self) -> None:
        with self.assertRaises(tool.RecoveryError) as ctx:
            tool.enforce_world_guard("rt:world:aaa", "rt:world:bbb")
        self.assertEqual(ctx.exception.code, "STAGE17_RECOVERY_WORLD_MISMATCH")


class AnchorProvenanceTests(unittest.TestCase):
    def test_10_matching_avatar_reports_match(self) -> None:
        self.assertEqual(tool.check_anchor_player_provenance("PLY-A", "PLY-A"), "MATCH")

    def test_11_mismatched_avatar_reports_non_fatal(self) -> None:
        self.assertEqual(
            tool.check_anchor_player_provenance("PLY-A", "PLY-B"), "PROVENANCE_MISMATCH_NON_FATAL"
        )


class DeterministicChunkHelperTests(unittest.TestCase):
    def test_12_finite_helper(self) -> None:
        self.assertTrue(tool._finite(1.0))
        self.assertFalse(tool._finite(float("nan")))
        self.assertFalse(tool._finite(float("inf")))
        self.assertFalse(tool._finite(True))  # bool must not pass as a real number


class SourceIntegrityTests(unittest.TestCase):
    """Static, source-text checks -- no DB, no engine, no execution."""

    def setUp(self) -> None:
        self.source = TOOL_PATH.read_text(encoding="utf-8")

    def test_13_no_hardcoded_home_coordinates(self) -> None:
        # The two literal float constants the original scratch script used.
        for banned in ("137104.156775035", "-1336965.95467694", "HOME_ISO_X", "HOME_ISO_Y"):
            self.assertNotIn(banned, self.source, f"found banned hardcoded literal: {banned}")

    def test_14_no_hardcoded_player_ref(self) -> None:
        self.assertIsNone(
            re.search(r'PLAYER_REF\s*=\s*"PLY-', self.source),
            "found a hardcoded PLY-... literal assigned to a constant",
        )
        self.assertNotIn("PLY-455FEDE6124F42819BDA63A8E82355F4", self.source)

    def test_15_no_sql_dml(self) -> None:
        # Check inside string literals passed to .execute(...) specifically --
        # not the whole file text, which also contains unrelated Python calls
        # like sys.path.insert(...) that a bare substring/word-boundary search
        # would misfire on.
        execute_args = re.findall(r"\.execute\(\s*(\"\"\".*?\"\"\"|\"[^\"]*\"|'[^']*')", self.source, re.DOTALL)
        dml_pattern = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER)\b", re.IGNORECASE)
        offenders = [s for s in execute_args if dml_pattern.search(s)]
        self.assertEqual(offenders, [], f"found SQL DML/DDL keyword(s) inside a .execute(...) call: {offenders}")

    def test_16_no_protected_module_reference(self) -> None:
        # Check only real `import` statements, not prose in comments/docstrings
        # that explicitly documents *not* using these modules (which would
        # otherwise trip a bare substring search on its own compliance claim).
        import_lines = [
            line for line in self.source.splitlines()
            if re.match(r"^\s*(from|import)\s+\S", line)
        ]
        banned = ("resource_metric_placement", "andromeda_authority_adapter")
        offenders = [line for line in import_lines for b in banned if b in line]
        self.assertEqual(offenders, [], f"tool must never import: {offenders}")

    def test_17_apply_gate_present(self) -> None:
        self.assertIn("--apply", self.source)
        self.assertIn("args.apply", self.source)

    def test_18_immutable_readonly_connection_used(self) -> None:
        self.assertIn("immutable=1", self.source)


if __name__ == "__main__":
    unittest.main()
