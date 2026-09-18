from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "01_RUNTIME"
ARPG = ROOT / "10_ARPG"
MASTER = Path(os.environ.get("ANDROMEDA_MASTER_V201", "/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip"))
LIVING = Path(os.environ.get("ANDROMEDA_LIVING_V100", "/mnt/data/ANDROMEDA_LIVING_SIM_ENGINE_V1_0_0_RELEASE(1).zip"))
SOURCE_COUNTRY = Path(os.environ.get("ANDROMEDA_COUNTRY_V150_SOURCE", "/mnt/data/ANDROMEDA_LIVING_COUNTRY_SCALE_V1_5_0_DEV(1).zip"))
MASTER_SHA = "6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2"
LIVING_SHA = "6f12c9db0976e234ef55cdfe23b998c07240fa8d80eb0d0c247d12bbd16ebabc"
COUNTRY_SHA = "1f49dfa4102c290a4fea67ec6e9f66b31dc1ebcacae1e8b2660a61a6c4ad4444"

sys.path.insert(0, str(RUNTIME))
from integrated_engine import IntegratedLivingEngineV11  # noqa: E402
from integrated_engine_v15 import IntegratedLivingEngineV15  # noqa: E402
from living_runtime import LivingRuntime  # noqa: E402

checks: list[dict] = []
metrics: dict = {}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ck(name: str, ok: bool, detail=None) -> None:
    checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})


# Baseline integrity.
ck("MASTER_PRESENT", MASTER.exists(), str(MASTER))
ck("MASTER_SHA256", MASTER.exists() and sha(MASTER) == MASTER_SHA, sha(MASTER) if MASTER.exists() else "missing")
ck("LIVING_PRESENT", LIVING.exists(), str(LIVING))
ck("LIVING_SHA256", LIVING.exists() and sha(LIVING) == LIVING_SHA, sha(LIVING) if LIVING.exists() else "missing")
ck("COUNTRY_SOURCE_PRESENT", SOURCE_COUNTRY.exists(), str(SOURCE_COUNTRY))
ck("COUNTRY_SOURCE_SHA256", SOURCE_COUNTRY.exists() and sha(SOURCE_COUNTRY) == COUNTRY_SHA, sha(SOURCE_COUNTRY) if SOURCE_COUNTRY.exists() else "missing")
master_before = sha(MASTER)

# Active runtime must not claim the unavailable Master V2.1.0.
v21_active = []
for base in (RUNTIME, ROOT / "02_CONTRACTS"):
    for p in base.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in {".py", ".json", ".md", ".gd", ".mjs", ".js"}:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if "V2.1.0" in text or "V2_1_0" in text or "9677b10890c24dfc04916178a2b9fd40a9ea131f2a13c1ec8255186ab203a98b" in text:
            v21_active.append(str(p.relative_to(ROOT)))
ck("NO_ACTIVE_V21_DEPENDENCY", not v21_active, v21_active[:25])

# Syntax integrity for active Python runtime.
syntax_fail = []
for p in sorted(RUNTIME.glob("*.py")):
    try:
        ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
    except Exception as exc:
        syntax_fail.append(f"{p.name}: {exc}")
ck("RUNTIME_PYTHON_SYNTAX", not syntax_fail, syntax_fail)

# Governance decisions and stage-count correction.
policy = json.loads((ARPG / "00_GOVERNANCE/ARPG_BASELINE_AUTHORITY_V0_1_0.json").read_text(encoding="utf-8"))
decisions = json.loads((ARPG / "00_GOVERNANCE/ARPG_AUTHORIAL_DECISIONS_V0_1_0.json").read_text(encoding="utf-8"))
stage_plan = json.loads((ARPG / "00_GOVERNANCE/ARPG_STAGE_PLAN_V0_1_0.json").read_text(encoding="utf-8"))
visual_gate = json.loads((ARPG / "18_VISUAL_PIPELINE/VISUAL_PIPELINE_GATE_V0_1_0.json").read_text(encoding="utf-8"))
ck("BASELINE_POLICY_ACTIVE", policy.get("status") == "ACTIVE")
ck("MASTER_POLICY_V201_READ_ONLY", policy["authority_order"][0].get("version") == "V2.0.1" and policy["authority_order"][0].get("mode") == "READ_ONLY")
ck("AUTHORIAL_DECISIONS_APPROVED", decisions.get("status") == "AUTHOR_APPROVED")
vals = decisions.get("decisions", {})
ck("DECISION_CHARACTER_D", vals.get("playable_character_model", {}).get("choice") == "D")
ck("DECISION_CLASSES_D", vals.get("class_system", {}).get("choice") == "D")
ck("DECISION_CONTROL_A", vals.get("primary_control", {}).get("choice") == "A")
ck("DECISION_NETWORK_C", vals.get("development_network_scope", {}).get("choice") == "C")
ck("DECISION_ITEMIZATION_C", vals.get("itemization", {}).get("choice") == "C")
ck("STAGE_COUNT_19", stage_plan.get("stage_count") == 19 and len(stage_plan.get("stages", [])) == 19)
ck("VISUAL_GATE_LOCKED", visual_gate.get("status") == "LOCKED" and visual_gate.get("unlock_condition") == "STAGE_17_PRE_ART_STATUS_PASS")

# Runtime accepts exactly the sealed Master baseline for this branch.
rt = LivingRuntime(":memory:", master_release_path=str(MASTER))
try:
    ck("RUNTIME_DETECTS_V201", rt.master_version == "V2.0.1", rt.master_version)
    ck("RUNTIME_DETECTS_MASTER_HASH", rt.master_release_sha256 == MASTER_SHA, rt.master_release_sha256)
    ck("DUNGEON_DEV_ITEM_NOT_CANONICAL", rt.canonical_ref_resolves("WPN-DNG-SWORD-001") is False)
finally:
    rt.close()

legacy = IntegratedLivingEngineV11(":memory:", master_release_path=str(MASTER))
try:
    legacy_report = legacy.create_world("arpg-stage00-legacy-compat", 1199, load_relationships=False)
    ck("LEGACY_V11_CATALOG_30", legacy_report.get("commerce", {}).get("count") == 30, legacy_report.get("commerce"))
    ck("LEGACY_V11_HEALTH", legacy_report.get("health", {}).get("status") == "PASS", legacy_report.get("health", {}).get("failures"))
finally:
    legacy.close()

# Integrated V1.5 on V2.0.1: world creation, catalog, commerce, combat, movement, discovery, pathing, dungeon item, persistence.
fd, db_path = tempfile.mkstemp(suffix=".sqlite")
os.close(fd)
engine = None
wid = None
try:
    engine = IntegratedLivingEngineV15(db_path, master_release_path=str(MASTER))
    report = engine.create_world("arpg-stage00", 1201, load_relationships=False)
    wid = report["world"]["world_instance_id"]
    metrics["world_instance_id"] = wid
    health = engine.health_v15(wid)
    ck("V15_WORLD_CREATE", report.get("version") == "V1.5.0", report.get("version"))
    ck("V15_HEALTH", health.get("status") == "PASS", health.get("failures"))
    ck("V15_MASTER_V201", engine.runtime.master_version == "V2.0.1", engine.runtime.master_version)

    commerce = report.get("commerce", {})
    metrics["commerce_catalog_count"] = commerce.get("count")
    metrics["commerce_by_source"] = commerce.get("by_source")
    ck("COMMERCE_CATALOG_84", commerce.get("count") == 84, commerce)
    ck("COMMERCE_MASTER_WEAPONS_30", commerce.get("by_source", {}).get("ANDROMEDA_CODEX_MASTER/05_MAR/FUNCTIONAL/01_MAR/MAR_WEAPONS_FUNCTIONAL_V1_0.json") == 30, commerce.get("by_source"))
    ck("COMMERCE_DERIVED_ITEMS_54", commerce.get("by_source", {}).get("RUNTIME_DERIVED_CONTENT_CATALOG_V1_2_1") == 54, commerce.get("by_source"))
    derived = engine.commerce.catalog_item("WPN-DNG-SWORD-001")
    ck("DERIVED_DUNGEON_ITEM_TAG", derived.get("canonical_status") == "DERIVED_GAMEPLAY_NOT_CANON", derived.get("canonical_status"))

    country = engine.country(wid)
    ck("COUNTRY_AUTHORITY_V201_DERIVED", "MASTER_V2_0_1" in country.AUTHORITY, country.AUTHORITY)
    ck("COUNTRY_VALIDATE", country.validate().get("status") == "PASS", country.validate().get("failures"))

    # Trade/hunt context in one block.
    context = None
    for st in country.world["country"]["states"]:
        for block in st["blocks"]:
            predator = next((f for f in block.get("fauna", []) if f.get("role") == "PREDATOR" and int(f.get("count", 0)) > 0), None)
            for city in block.get("cities", []):
                actor = next((n for n in city.get("npcs", []) if n.get("class") in {"WARRIOR", "MERCENARY"} and n.get("protection", {}).get("combat_targetable")), None)
                shop = next((s for s in city.get("shops", []) if any(str(k).startswith("WPN-") and int(v) > 0 for k, v in s.get("inventory", {}).items())), None)
                if predator and actor and shop:
                    weapon = next(k for k, v in shop["inventory"].items() if str(k).startswith("WPN-") and int(v) > 0)
                    context = (block, city, actor, shop, predator, weapon)
                    break
            if context:
                break
        if context:
            break
    ck("GAMEPLAY_CONTEXT_FOUND", context is not None)
    if context:
        block, city, actor, shop, predator, weapon = context
        money_before = round(float(actor["wallet"]["balance"]) + float(shop["wallet"]["balance"]), 4)
        purchase = country.purchase(shop["id"], actor["id"], weapon, 1)
        ck("LIVE_PURCHASE", purchase.get("status") == "PASS", purchase)
        money_after = round(float(actor["wallet"]["balance"]) + float(shop["wallet"]["balance"]), 4)
        ck("MONEY_CONSERVATION", abs(money_before - money_after) <= 0.01, {"before": money_before, "after": money_after})
        equip = engine.bridge(wid).equip_country_weapon(actor["id"], weapon)
        ck("LIVE_EQUIP", equip.get("status") == "PASS", equip)
        before_count = int(predator["count"])
        hunt = country.hunt_fauna(block["id"], predator["id"], 1, actor["id"])
        ck("LIVE_COMBAT_HUNT", hunt.get("status") == "PASS" and hunt.get("killed", 0) >= 1, hunt)
        ck("FAUNA_PROJECTION_UPDATED", int(predator["count"]) == before_count - int(hunt.get("killed", 0)), {"before": before_count, "after": predator["count"], "killed": hunt.get("killed")})

    # Mouse-oriented movement backend / pathing / discovery surfaces.
    mover = next(n for n in country._all_npc_records() if n.get("class") == "WARRIOR")
    g = engine.godot(wid)
    session = "ARPG-STAGE00-SESSION"
    ck("SESSION_BIND", g.bind_session(session, mover["id"]).get("status") == "PASS")
    before = engine.movement(wid).state(mover["id"])
    move = g.command(mover["id"], "MOVE_VECTOR", {"dx": 1, "dy": 0, "duration_s": 0.25, "mode": "WALK"})
    after = engine.movement(wid).state(mover["id"])
    ck("MOVE_VECTOR", move.get("status") == "PASS" and after["iso_x_m"] > before["iso_x_m"], {"move": move, "before_x": before["iso_x_m"], "after_x": after["iso_x_m"]})
    ck("DISCOVERY_VERIFY", engine.discovery(wid).verify().get("status") == "PASS")
    blocks = [b for st in country.world["country"]["states"] for b in st["blocks"]]
    origin = country.block(mover["block_id"])
    destination = next(b for b in blocks if b["id"] != origin["id"])
    path = engine.navigation(wid).plan_blocks(origin["id"], destination["id"])
    ck("PATHFINDING_RESPONDS", path.get("status") in {"PASS", "REJECTED"}, path.get("status"))
    ck("STREAMING_INTEGRITY", engine.streaming(wid).full_integrity_check().get("status") == "PASS")

    # Prove a DEV-only dungeon weapon can be picked up/equipped without becoming canon.
    derived_weapon_result = None
    for st in country.world["country"]["states"]:
        for block in st["blocks"]:
            if not block.get("dungeons"):
                continue
            npc = next((n for n in country._all_npc_records() if n.get("class") in {"WARRIOR", "MERCENARY", "MAGE"} and n.get("id")), None)
            if not npc:
                continue
            dungeon = block["dungeons"][0]
            country.relocate_npc(npc["id"], block["id"])
            enter = engine.scenes(wid).enter_dungeon(npc["id"], dungeon["id"])
            if enter.get("status") != "PASS":
                continue
            ground = next((o for o in dungeon.get("objects", []) if o.get("object_type") == "GROUND_WEAPON" and str(o.get("item_ref", "")).startswith("WPN-DNG-")), None)
            if not ground:
                continue
            take = engine.scenes(wid).interact(npc["id"], ground["id"], "TAKE")
            if take.get("status") != "PASS":
                continue
            derived_weapon_result = engine.bridge(wid).equip_country_weapon(npc["id"], ground["item_ref"])
            break
        if derived_weapon_result is not None:
            break
    ck("DERIVED_DUNGEON_WEAPON_PLAYABLE", derived_weapon_result is not None and derived_weapon_result.get("status") == "PASS", derived_weapon_result)

    # Persisted state must survive process restart.
    snap_before = g.client_snapshot(session)
    ck("CLIENT_SNAPSHOT_LIVE", snap_before.get("status") == "PASS" and snap_before.get("server_authoritative") is True)
    engine.close()
    engine = None

    engine2 = IntegratedLivingEngineV15(db_path, master_release_path=str(MASTER))
    try:
        resumed = engine2.resume_world(wid)
        ck("PROCESS_RESUME", resumed.get("status") == "PASS" and resumed.get("world_instance_id") == wid, resumed)
        ck("RESUME_HEALTH", engine2.health_v15(wid).get("status") == "PASS", engine2.health_v15(wid).get("failures"))
        snap_after = engine2.godot(wid).client_snapshot(session)
        ck("SESSION_PERSISTS_AFTER_RESUME", snap_after.get("status") == "PASS" and snap_after.get("server_authoritative") is True, snap_after.get("status"))
        ck("BRIDGE_INTEGRITY_AFTER_RESUME", engine2.bridge(wid).full_integrity_check().get("status") == "PASS", engine2.bridge(wid).full_integrity_check().get("failures"))
    finally:
        engine2.close()
finally:
    if engine is not None:
        engine.close()
    try:
        os.unlink(db_path)
    except FileNotFoundError:
        pass

# No writes to sealed baseline.
master_after = sha(MASTER)
ck("MASTER_UNCHANGED_AFTER_SIMULATION", master_before == master_after == MASTER_SHA, {"before": master_before, "after": master_after})

# Hygiene in active branch; Python runs above are configured not to emit bytecode.
transients = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and ("__pycache__" in p.parts or p.suffix.lower() in {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3", ".tmp"})]
ck("NO_TRANSIENT_ARTIFACTS", not transients, transients[:25])

godot = shutil.which("godot4") or shutil.which("godot")
external = {
    "godot_executable": godot,
    "runtime_gate": "AVAILABLE" if godot else "PENDING_NOT_REQUIRED_FOR_STAGE00",
    "note": None if godot else "Godot executable is unavailable in this validation environment; Stage 00 does not claim rendered-client execution.",
}

failed = [c for c in checks if c["status"] == "FAIL"]
report = {
    "record_id": "ARPG-STAGE00-VALIDATION-V0.1.0",
    "project": "ANDRÔMEDA CÓDEX",
    "branch": "ANDROMEDA_ARPG_FOUNDATION_V0_1_0_DEV",
    "stage": "00/18",
    "stage_count": 19,
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
out = ROOT / "04_REPORTS/ARPG_STAGE00/ARPG_STAGE00_VALIDATION_V0_1_0.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: report[k] for k in ("record_id", "checks", "passed", "failed", "status", "external_godot")}, ensure_ascii=False))
if failed:
    print(json.dumps(failed[:20], ensure_ascii=False, indent=2))
raise SystemExit(1 if failed else 0)
