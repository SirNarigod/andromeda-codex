from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "01_RUNTIME"
MASTER = Path(os.environ.get("ANDROMEDA_MASTER_V201", "/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip"))
LIVING = Path(os.environ.get("ANDROMEDA_LIVING_V100", "/mnt/data/ANDROMEDA_LIVING_SIM_ENGINE_V1_0_0_RELEASE(1).zip"))
MASTER_SHA = "6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2"
LIVING_SHA = "6f12c9db0976e234ef55cdfe23b998c07240fa8d80eb0d0c247d12bbd16ebabc"
sys.path.insert(0, str(RUNTIME))

from integrated_arpg_engine_v01 import IntegratedARPGEngineV01  # noqa: E402
from living_runtime import ValidationError, ConflictError  # noqa: E402

checks = []
metrics = {}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ck(name: str, ok: bool, detail=None) -> None:
    checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})


master_before = sha(MASTER)
living_before = sha(LIVING)
ck("MASTER_SHA256", master_before == MASTER_SHA, master_before)
ck("LIVING_SHA256", living_before == LIVING_SHA, living_before)

syntax_fail = []
for p in sorted(RUNTIME.glob("*.py")):
    try:
        ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
    except Exception as exc:
        syntax_fail.append(f"{p.name}:{exc}")
ck("ACTIVE_RUNTIME_SYNTAX", not syntax_fail, syntax_fail)

contract_path = ROOT / "02_CONTRACTS/ARPG_STAGE01/ARPG_GAME_CORE_CONTRACT_V0_2_0.json"
contract = json.loads(contract_path.read_text(encoding="utf-8"))
ck("CONTRACT_STAGE01", contract.get("stage") == "01/18")
ck("CONTRACT_MASTER_READ_ONLY", contract.get("canon_policy") == "MASTER_V2.0.1_READ_ONLY")
ck("CONTRACT_MOUSE_CONTROL", contract.get("control", {}).get("primary") == "MOUSE_POINTER_DIABLO_LIKE")
ck("CONTRACT_EMERGENT_CLASSES", contract.get("class_model", {}).get("type") == "EMERGENT_FROM_PLAYER_CHOICES")
ck("CONTRACT_MULTIPLAYER_READY", contract.get("network_readiness", {}).get("server_authoritative") is True)
ck("CONTRACT_ART_LOCKED", contract.get("deferred_systems", {}).get("art") == "LOCKED_UNTIL_STAGE17_PASS")

fd, db_path = tempfile.mkstemp(suffix=".sqlite")
os.close(fd)
engine = None
wid = None
try:
    engine = IntegratedARPGEngineV01(db_path, master_release_path=str(MASTER))
    report = engine.create_world("arpg-stage01-validation", 1201, load_relationships=False)
    wid = report["world"]["world_instance_id"]
    core = engine.arpg(wid)
    ck("WORLD_VERSION", report.get("version") == "ARPG-V0.2.0", report.get("version"))
    ck("WORLD_HEALTH_BOOT", engine.health_arpg_v01(wid).get("status") == "PASS", engine.health_arpg_v01(wid).get("failures"))
    ck("CORE_EMPTY_BOOT", core.verify().get("profiles") == 0, core.verify())

    created = core.create_profile("local:author", origin_mode="CREATED", display_name="Validation Hero")["profile"]
    ck("CREATED_PROFILE", created.get("origin_mode") == "CREATED" and created.get("canonical_ref") is None)
    ck("CREATED_CLASS_NULL", created.get("progression", {}).get("emergent_class") is None)
    ck("CREATED_CLASS_MODEL", created.get("progression", {}).get("class_model") == "EMERGENT_FROM_PLAYER_CHOICES")
    avatar = engine.country(wid).npc(created["avatar_ref"])
    ck("PLAYER_AVATAR_SEPARATE", avatar.get("class") == "PLAYER_AVATAR" and avatar.get("arpg_profile_ref") == created["profile_ref"])
    ck("PLAYER_AVATAR_STREAMED", created["avatar_ref"] in engine.streaming(wid).owners)
    ck("PLAYER_AVATAR_MOTION", engine.movement(wid).state(created["avatar_ref"]).get("entity_ref") == created["avatar_ref"])
    ck("PLAYER_AVATAR_LIVING_BOUND", engine.bridge(wid)._binding("NPC", created["avatar_ref"]) is not None)

    canonical = core.create_profile("local:canon", origin_mode="CANONICAL", canonical_ref="PER-002")["profile"]
    ck("CANONICAL_PROFILE", canonical.get("canonical_ref") == "PER-002")
    ck("CANONICAL_NAME_MASTER", canonical.get("display_name") == "Kenua Vaarn", canonical.get("display_name"))
    ck("CANONICAL_DOMAIN", canonical.get("canonical_character_metadata", {}).get("domain") == "narrativa/personagens")
    bad_ref = False
    try:
        core.create_profile("local:bad", origin_mode="CANONICAL", canonical_ref="TIM-027")
    except ValidationError:
        bad_ref = True
    ck("NON_CHARACTER_CANON_REJECTED", bad_ref)
    duplicate = False
    try:
        core.create_profile("local:dupe", origin_mode="CANONICAL", canonical_ref="PER-002")
    except ConflictError:
        duplicate = True
    ck("DUPLICATE_CANON_PROFILE_REJECTED", duplicate)

    wrong_owner = core.submit_command("local:intruder", created["profile_ref"], 1, "CANCEL_ACTION", {})
    ck("OWNERSHIP_GUARD", wrong_owner.get("reason") == "PROFILE_OWNERSHIP_MISMATCH", wrong_owner)

    st = engine.movement(wid).state(created["avatar_ref"])
    move = core.submit_command("local:author", created["profile_ref"], 1, "POINTER_PRIMARY", {
        "iso_x_m": st["iso_x_m"] + 1.25, "iso_y_m": st["iso_y_m"], "mode": "WALK"
    })
    ck("POINTER_MOVE_INTENT", move.get("status") == "PASS" and move.get("movement_intent") == "STARTED", move)
    frames = []
    for _ in range(30):
        f = core.tick(created["profile_ref"], delta_s=0.1)
        frames.append(f.get("frame_state"))
        if f.get("frame_state") == "ARRIVED":
            break
    ck("POINTER_MOVE_ARRIVAL", "ARRIVED" in frames, frames)
    ck("POINTER_MOVE_CLEARED", core.client_snapshot(created["profile_ref"])["input_state"].get("move_target") is None)

    far = engine.movement(wid).state(created["avatar_ref"])
    out_far = core.submit_command("local:author", created["profile_ref"], 2, "MOVE_POINTER", {
        "iso_x_m": far["iso_x_m"] + core.MAX_POINTER_DISTANCE_M + 1, "iso_y_m": far["iso_y_m"]
    })
    ck("POINTER_LOCAL_RANGE_GUARD", out_far.get("reason") == "POINTER_DESTINATION_OUT_OF_LOCAL_RANGE", out_far)

    replay = core.submit_command("local:author", created["profile_ref"], 2, "MOVE_POINTER", {
        "iso_x_m": far["iso_x_m"] + core.MAX_POINTER_DISTANCE_M + 1, "iso_y_m": far["iso_y_m"]
    })
    ck("COMMAND_IDEMPOTENT_REPLAY", replay.get("idempotent_replay") is True and replay.get("command_ref") == out_far.get("command_ref"), replay)
    conflict = core.submit_command("local:author", created["profile_ref"], 2, "CANCEL_ACTION", {})
    ck("COMMAND_SEQUENCE_CONFLICT", conflict.get("reason") == "CLIENT_SEQUENCE_CONFLICT", conflict)
    gap = core.submit_command("local:author", created["profile_ref"], 4, "CANCEL_ACTION", {})
    ck("COMMAND_OUT_OF_ORDER_GUARD", gap.get("reason") == "OUT_OF_ORDER_CLIENT_SEQUENCE", gap)
    cmd3 = core.submit_command("local:author", created["profile_ref"], 3, "CANCEL_ACTION", {})
    ck("COMMAND_SEQUENCE_RECOVERS", cmd3.get("status") == "PASS", cmd3)

    # Multiplayer-ready activation semantics: same controller switches; different controller may stay active.
    alt = core.create_profile("local:author", origin_mode="CREATED", display_name="Validation Alt", activate=False)["profile"]
    switched = core.activate_profile(alt["profile_ref"], controller_scope="local:author")
    ck("SAME_CONTROLLER_SWITCH", switched.get("status") == "PASS" and not core.profile(created["profile_ref"])["active"] and core.profile(alt["profile_ref"])["active"])
    ck("OTHER_CONTROLLER_REMAINS_ACTIVE", core.profile(canonical["profile_ref"])["active"] is True)
    ck("PER_CONTROLLER_ACTIVE_RULE", core.verify().get("status") == "PASS", core.verify().get("failures"))
    core.activate_profile(created["profile_ref"], controller_scope="local:author")

    # Pause/resume is runtime state and freezes pointer movement.
    st = engine.movement(wid).state(created["avatar_ref"])
    cmd4 = core.submit_command("local:author", created["profile_ref"], 4, "MOVE_POINTER", {"iso_x_m": st["iso_x_m"] + 2, "iso_y_m": st["iso_y_m"], "mode": "WALK"})
    pause = core.submit_command("local:author", created["profile_ref"], 5, "PAUSE", {})
    frozen_before = engine.movement(wid).state(created["avatar_ref"])
    frozen = core.tick(created["profile_ref"], delta_s=0.2)
    frozen_after = engine.movement(wid).state(created["avatar_ref"])
    ck("PAUSE_COMMAND", pause.get("clock_state") == "PAUSED")
    ck("PAUSE_FREEZES_TICK", frozen.get("frame_state") == "PAUSED" and frozen_before["iso_x_m"] == frozen_after["iso_x_m"])
    resume = core.submit_command("local:author", created["profile_ref"], 6, "RESUME", {})
    ck("RESUME_COMMAND", resume.get("clock_state") == "RUNNING")

    # NPC target is routed, but combat implementation is intentionally not pulled into Stage 01.
    target_npc = next(n for n in engine.country(wid)._all_npc_records() if n["id"] != created["avatar_ref"])
    routed = core.submit_command("local:author", created["profile_ref"], 7, "POINTER_PRIMARY", {"target_ref": target_npc["id"]})
    ck("NPC_CONTEXT_ROUTED", routed.get("route") == "NPC_CONTEXT", routed)
    ck("COMBAT_DEFERRED_CORRECTLY", routed.get("implementation_stage") == "COMBAT_STAGE03_DIALOGUE_STAGE11", routed)

    snap = core.client_snapshot(created["profile_ref"])
    ck("SNAPSHOT_SERVER_AUTHORITY", snap.get("server_authoritative") is True)
    ck("SNAPSHOT_CONTROL_MOUSE", snap.get("control_scheme") == "MOUSE_POINTER_DIABLO_LIKE")
    ck("SNAPSHOT_NO_ART_DEPENDENCY", snap.get("art_dependency") == "NONE_PLACEHOLDER_READY")
    ck("CORE_HEALTH_PRE_RESUME", core.verify().get("status") == "PASS", core.verify().get("failures"))
    ck("ENGINE_HEALTH_PRE_RESUME", engine.health_arpg_v01(wid).get("status") == "PASS", engine.health_arpg_v01(wid).get("failures"))
    history_before = core.command_history(created["profile_ref"])
    metrics["commands_created_profile"] = len(history_before)
    metrics["profiles"] = len(core.list_profiles())
    engine.close(); engine = None

    engine2 = IntegratedARPGEngineV01(db_path, master_release_path=str(MASTER))
    try:
        resumed_world = engine2.resume_world(wid)
        core2 = engine2.arpg(wid)
        ck("PROCESS_RESUME", resumed_world.get("status") == "PASS", resumed_world)
        ck("PROFILE_PERSISTS", core2.profile(created["profile_ref"])["display_name"] == "Validation Hero")
        ck("CANONICAL_PROFILE_PERSISTS", core2.profile(canonical["profile_ref"])["canonical_ref"] == "PER-002")
        ck("COMMAND_STREAM_PERSISTS", len(core2.command_history(created["profile_ref"])) == len(history_before))
        ck("SEQUENCE_PERSISTS", core2.client_snapshot(created["profile_ref"])["input_state"]["last_client_sequence"] == 7)
        ck("RESUME_CORE_HEALTH", core2.verify().get("status") == "PASS", core2.verify().get("failures"))
        ck("RESUME_ENGINE_HEALTH", engine2.health_arpg_v01(wid).get("status") == "PASS", engine2.health_arpg_v01(wid).get("failures"))
        ck("COUNTRY_PERSISTENCE", engine2.country(wid).persistence_integrity().get("status") == "PASS", engine2.country(wid).persistence_integrity().get("failures"))
        ck("STREAMING_PERSISTENCE", engine2.streaming(wid).full_integrity_check().get("status") == "PASS", engine2.streaming(wid).full_integrity_check().get("failures"))
    finally:
        engine2.close()
finally:
    if engine is not None:
        engine.close()
    try:
        os.unlink(db_path)
    except FileNotFoundError:
        pass

ck("MASTER_UNCHANGED", sha(MASTER) == master_before == MASTER_SHA, sha(MASTER))
ck("LIVING_UNCHANGED", sha(LIVING) == living_before == LIVING_SHA, sha(LIVING))
transients = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and ("__pycache__" in p.parts or p.suffix.lower() in {".pyc", ".pyo", ".sqlite", ".db", ".tmp"})]
ck("NO_TRANSIENT_ARTIFACTS", not transients, transients[:20])

godot = shutil.which("godot4") or shutil.which("godot")
external = {
    "godot_executable": godot,
    "runtime_gate": "AVAILABLE" if godot else "PENDING_FOR_STAGE15_NOT_REQUIRED_STAGE01",
    "claim": "NO_RENDERED_GODOT_EXECUTION" if not godot else "EXECUTABLE_AVAILABLE_NOT_PART_OF_STAGE01_GATE",
}
failed = [c for c in checks if c["status"] == "FAIL"]
report = {
    "record_id": "ARPG-STAGE01-VALIDATION-V0.2.0",
    "project": "ANDRÔMEDA CÓDEX",
    "branch": "ANDROMEDA_ARPG_GAME_CORE_V0_2_0_DEV",
    "stage": "01/18",
    "checks": len(checks),
    "passed": len(checks) - len(failed),
    "failed": len(failed),
    "status": "PASS" if not failed else "FAIL",
    "failures": failed,
    "metrics": metrics,
    "external_godot": external,
    "baseline": {"master_version": "V2.0.1", "master_sha256": MASTER_SHA, "living_version": "V1.0.0", "living_sha256": LIVING_SHA},
    "canon_mutations": 0,
    "art_pipeline": "LOCKED",
}
out = ROOT / "04_REPORTS/ARPG_STAGE01/ARPG_STAGE01_VALIDATION_V0_2_0.json"
out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: report[k] for k in ("record_id", "checks", "passed", "failed", "status", "metrics", "external_godot")}, ensure_ascii=False))
if failed:
    print(json.dumps(failed, ensure_ascii=False, indent=2))
raise SystemExit(1 if failed else 0)
