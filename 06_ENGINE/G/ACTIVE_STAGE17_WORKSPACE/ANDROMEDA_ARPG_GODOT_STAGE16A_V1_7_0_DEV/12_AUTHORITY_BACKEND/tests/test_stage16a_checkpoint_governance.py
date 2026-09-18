"""Stage16A protected-checkpoint GOVERNANCE suite.

Proves the V0.8.0 -> V0.8.1 baseline succession itself, separate from the
verify() contract fix that V0.8.1 carries. V0.8.0 stays sealed and restorable
as the historical predecessor; V0.8.1 is the checkpoint the live tree is now
compared against by run_stage16b_authority_validation.py and
tests/test_stage16b_authority_adapter.py::test_05_protected_checkpoint_unchanged.

Nothing here re-verifies the verify() logic itself -- that is
test_stage16a_item_definitions_verify_contract.py's job.
"""

from __future__ import annotations

import hashlib
import pathlib
import unittest
import zipfile

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
REPO_ROOT = PROJECT_ROOT.parent

CHECKPOINT_DIR = pathlib.Path(r"C:\Users\thall\Documents\ARPG CODEX")
V0_8_0_ZIP = CHECKPOINT_DIR / "ANDROMEDA_ARPG_STAGE16A_PRE_GODOT_V1_8_0_DEV_CHECKPOINT_V0_8_0.zip"
V0_8_1_ZIP = CHECKPOINT_DIR / "ANDROMEDA_ARPG_STAGE16A_PRE_GODOT_V1_8_0_DEV_CHECKPOINT_V0_8_1.zip"
V0_8_1_SEALED_RECORD = CHECKPOINT_DIR / "STAGE16A_CHECKPOINT_V0_8_1_SEALED.json"

V0_8_0_EXPECTED_SHA256 = "21626a3152cb37e167eee24bff9d3142c5d389a8ca2827594b34211591525a6a"
V0_8_1_EXPECTED_SHA256 = "03bc6b621a5ae8e0bf6542803412611855b32503154221ec7ea1b7aaf28befc4"

# The active checkpoint the live validators actually compare against right
# now. Read from run_stage16b_authority_validation.py's own constant so this
# suite can never silently drift from what the real validator uses.
import sys  # noqa: E402

sys.path.insert(0, str(BACKEND_DIR))
from run_stage16b_authority_validation import CHECKPOINT_ZIP as ACTIVE_CHECKPOINT_ZIP  # noqa: E402


def _file_sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


class Stage16ACheckpointGovernanceTests(unittest.TestCase):
    def test_active_stage16a_baseline_is_v0_8_1(self) -> None:
        self.assertEqual(
            V0_8_1_ZIP.resolve(),
            ACTIVE_CHECKPOINT_ZIP.resolve(),
            "ACTIVE_STAGE16A_BASELINE_IS_V0_8_1",
        )

    def test_active_stage16a_checkpoint_724_of_724(self) -> None:
        self.assertTrue(ACTIVE_CHECKPOINT_ZIP.is_file())
        with zipfile.ZipFile(ACTIVE_CHECKPOINT_ZIP) as archive:
            names = [n for n in archive.namelist() if not n.endswith("/")]
        self.assertEqual(724, len(names), "ACTIVE_STAGE16A_CHECKPOINT_724_OF_724")

    def test_active_stage16a_checkpoint_zero_altered_zero_missing(self) -> None:
        missing: list[str] = []
        mismatch: list[str] = []
        with zipfile.ZipFile(ACTIVE_CHECKPOINT_ZIP) as archive:
            names = [n for n in archive.namelist() if not n.endswith("/")]
            for name in names:
                target = REPO_ROOT / name
                if not target.is_file():
                    missing.append(name)
                    continue
                if hashlib.sha256(archive.read(name)).digest() != hashlib.sha256(target.read_bytes()).digest():
                    mismatch.append(name)
        self.assertEqual([], missing, "ACTIVE_STAGE16A_CHECKPOINT_ZERO_MISSING")
        self.assertEqual([], mismatch, "ACTIVE_STAGE16A_CHECKPOINT_ZERO_ALTERED")

    def test_v0_8_0_predecessor_still_present(self) -> None:
        self.assertTrue(V0_8_0_ZIP.is_file(), "V0_8_0_PREDECESSOR_STILL_PRESENT")

    def test_v0_8_0_predecessor_sha_unchanged(self) -> None:
        self.assertEqual(
            V0_8_0_EXPECTED_SHA256,
            _file_sha256(V0_8_0_ZIP),
            "V0_8_0_PREDECESSOR_SHA_UNCHANGED",
        )

    def test_v0_8_1_sha_matches_seal(self) -> None:
        self.assertTrue(V0_8_1_ZIP.is_file())
        self.assertEqual(
            V0_8_1_EXPECTED_SHA256,
            _file_sha256(V0_8_1_ZIP),
            "V0_8_1_SHA_MATCHES_SEAL",
        )
        # The seal record itself must exist and name this exact hash, so the
        # seal and the on-disk zip can never silently diverge.
        self.assertTrue(V0_8_1_SEALED_RECORD.is_file(), "V0_8_1 sealed record missing")
        seal_text = V0_8_1_SEALED_RECORD.read_text(encoding="utf-8")
        self.assertIn(V0_8_1_EXPECTED_SHA256, seal_text)

    def test_v0_8_1_restore_reference_valid(self) -> None:
        # A restore reference is "valid" when the zip actually opens, lists
        # exactly the expected entry count, and every entry is individually
        # readable/hashable -- i.e. the archive is not corrupt and is usable
        # as a real restore source, not merely present on disk.
        with zipfile.ZipFile(V0_8_1_ZIP) as archive:
            bad = archive.testzip()
            self.assertIsNone(bad, f"V0_8_1_RESTORE_REFERENCE_VALID: corrupt entry {bad}")
            names = [n for n in archive.namelist() if not n.endswith("/")]
            self.assertEqual(724, len(names), "V0_8_1_RESTORE_REFERENCE_VALID")

    def test_v0_8_0_and_v0_8_1_relationship(self) -> None:
        # The two baselines must never be the same file/hash -- otherwise
        # "predecessor" and "active" would silently collapse into one.
        self.assertNotEqual(V0_8_0_EXPECTED_SHA256, V0_8_1_EXPECTED_SHA256)
        self.assertNotEqual(V0_8_0_ZIP.resolve(), V0_8_1_ZIP.resolve())


if __name__ == "__main__":
    unittest.main()
