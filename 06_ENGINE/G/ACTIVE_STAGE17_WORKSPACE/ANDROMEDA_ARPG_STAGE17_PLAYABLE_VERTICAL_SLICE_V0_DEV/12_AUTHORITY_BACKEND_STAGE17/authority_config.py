"""Stage16B authority backend configuration.

Pins the backend to the authorised Andrômeda Códex Master V2.0.1 release and to the
protected Stage16A runtime tree. Nothing here implements gameplay: it only resolves
paths and refuses to start against an unauthorised master.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / "01_RUNTIME"
BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_VAR_DIR = BACKEND_DIR / "var"

MASTER_V2_0_1_SHA256 = "6D9AC3CCE7DCF6A65FDCF73859C332A0211C1AF52D149077BEEF554BF7BBD0B2"
MASTER_V2_0_1_VERSION = "V2.0.1"
DEFAULT_MASTER_PATH = Path(
    r"C:\Users\thall\ANDROMEDA_PRODUCT\ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip"
)

# Stage16B must never be promoted onto the phantom Master V2.1.0 that the historical
# Living V1.5 test runners still reference.
FORBIDDEN_MASTER_TOKENS = ("V2_1_0", "V2.1.0")
FORBIDDEN_MASTER_SHA256 = "9677B10890C24DFC04916178A2B9FD40A9EA131F2A13C1EC8255186AB203A98B"

DEFAULT_OWNER_SCOPE = "stage16b:authority"
DEFAULT_WORLD_SEED = 160800
DEFAULT_PLAYER_CLASS = "WARRIOR"


class AuthorityConfigError(RuntimeError):
    """Raised when the backend is not allowed to start with the given configuration."""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


@dataclass(frozen=True)
class AuthorityConfig:
    master_release_path: Path
    master_release_sha256: str
    runtime_dir: Path
    db_path: Path
    save_root: Path
    owner_scope: str
    world_seed: int
    player_class: str
    development_profile_bootstrap: bool = True
    # Stage17-only additive authority. Historical Stage16B tests instantiate
    # AuthorityConfig directly and therefore leave this disabled; the Stage17
    # launcher explicitly supplies the canonical baked manifest.
    resource_placement_manifest_path: Path | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "master_release_path": str(self.master_release_path),
            "master_release_sha256": self.master_release_sha256,
            "master_version": MASTER_V2_0_1_VERSION,
            "master_read_only": True,
            "runtime_dir": str(self.runtime_dir),
            "db_path": str(self.db_path),
            "save_root": str(self.save_root),
            "owner_scope": self.owner_scope,
            "world_seed": self.world_seed,
            "player_class": self.player_class,
            "development_profile_bootstrap": self.development_profile_bootstrap,
            "resource_placement_manifest_path": (
                str(self.resource_placement_manifest_path)
                if self.resource_placement_manifest_path is not None
                else None
            ),
        }


def _resolve_master_path() -> Path:
    raw = (
        os.environ.get("ANDROMEDA_MASTER_RELEASE")
        or os.environ.get("ANDROMEDA_MASTER_V201")
        or os.environ.get("ANDROMEDA_MASTER")
    )
    return Path(raw) if raw else DEFAULT_MASTER_PATH


def verify_master(path: Path) -> str:
    """Return the uppercase SHA-256 of the master release, or raise."""
    text = str(path)
    for token in FORBIDDEN_MASTER_TOKENS:
        if token in text:
            raise AuthorityConfigError(
                f"master path references the unauthorised Master V2.1.0 lineage: {text}"
            )
    if not path.is_file():
        raise AuthorityConfigError(f"master release not found: {text}")
    actual = _file_sha256(path)
    if actual == FORBIDDEN_MASTER_SHA256:
        raise AuthorityConfigError("Master V2.1.0 detected; Stage16B authority requires V2.0.1")
    if actual != MASTER_V2_0_1_SHA256:
        raise AuthorityConfigError(
            f"master release sha256 mismatch: expected {MASTER_V2_0_1_SHA256}, got {actual}"
        )
    return actual


def load_config() -> AuthorityConfig:
    master_path = _resolve_master_path()
    master_sha = verify_master(master_path)

    if not (RUNTIME_DIR / "integrated_arpg_engine_v16a.py").is_file():
        raise AuthorityConfigError(f"Stage16A runtime not found under {RUNTIME_DIR}")

    var_dir = Path(os.environ.get("ANDROMEDA_S16B_VAR", str(DEFAULT_VAR_DIR)))
    db_path = Path(os.environ.get("ANDROMEDA_S16B_DB", str(var_dir / "stage16b_world.sqlite")))
    save_root = Path(os.environ.get("ANDROMEDA_S16B_SAVE_ROOT", str(var_dir / "saves")))
    placement_manifest_raw = os.environ.get(
        "ANDROMEDA_S17_RESOURCE_PLACEMENT_MANIFEST", ""
    ).strip()
    placement_manifest_path = Path(placement_manifest_raw) if placement_manifest_raw else None

    try:
        world_seed = int(os.environ.get("ANDROMEDA_S16B_SEED", str(DEFAULT_WORLD_SEED)))
    except ValueError as exc:
        raise AuthorityConfigError("ANDROMEDA_S16B_SEED must be an integer") from exc

    return AuthorityConfig(
        master_release_path=master_path,
        master_release_sha256=master_sha,
        runtime_dir=RUNTIME_DIR,
        db_path=db_path,
        save_root=save_root,
        owner_scope=os.environ.get("ANDROMEDA_S16B_OWNER_SCOPE", DEFAULT_OWNER_SCOPE),
        world_seed=world_seed,
        player_class=os.environ.get("ANDROMEDA_S16B_PLAYER_CLASS", DEFAULT_PLAYER_CLASS).upper(),
        development_profile_bootstrap=os.environ.get(
            "ANDROMEDA_S16B_DEV_PROFILE_BOOTSTRAP", "1"
        ).strip().lower() not in {"0", "false", "off", "no"},
        resource_placement_manifest_path=placement_manifest_path,
    )
