"""STAGE17 FINAL CLOSURE -- formal DEV recovery tool.

DEV COMBAT STATE RECOVERY (S17-C3R6)
-------------------------------------
Clears ONLY the gameplay-derived combat-state overlay for NPCs that this
engagement's OWN repeated live-world Combat/G19 regression testing left
damaged or defeated, so the already-correct COMMON/ALPHA spatial-eligibility
boundary (S17-C3R5) can once again find two pristine local candidates.

What this tool touches (all three are gameplay-derived overlay tables owned
by the protected Stage03/Stage07 cores -- never canon, per their own module
docstrings):
    * arpg_enemy_combat_state  (ARPGCombatCore  -- health / life_state)
    * arpg_combat_overlay      (ARPGCombatCore  -- cooldowns/stagger/statuses;
                                 NPC rows only, the player's own row is never
                                 read, matched or written by this tool)
    * arpg_actor_ai_state      (ARPGActorCore   -- AI FSM state)

What this tool NEVER touches:
    * arpg_actor_profiles (disposition/rank -- re-derived idempotently by the
      adapter's own set_disposition()/set_combat_rank() the next time a given
      ref is actually selected as a combat encounter target; not part of the
      eligibility gate itself, see AUDIT NOTE below)
    * arpg_combat_events / arpg_actor_events (permanent, append-only audit
      trails -- deleting these would destroy the very auditability this round
      requires; both are left completely alone)
    * any Country/NPC canonical record, position/movement row, inventory,
      quest, economy or relationship table
    * 01_RUNTIME, Stage16A, Stage16B or Master -- this file is Stage17-owned
      and imports the protected cores exactly the way the authority adapter
      itself already does, without editing any of them

AUDIT NOTE (Section 3 of the S17-C3R6 authorization): arpg_actor_ai_state is
audited and reset here for full "combat-ready" cleanliness (Section 9), but
reading _ensure_development_combat_encounter()'s own candidate search
confirms it does NOT gate COMMON/ALPHA eligibility -- only
arpg_enemy_combat_state's life_state/health does, together with the metric
spatial bound. This is reported explicitly rather than left implicit.

Mechanism: this tool invents no combat values of its own. It only DELETEs an
exact (world_instance_id, actor_ref) row already loaded and confirmed
non-pristine, then immediately calls the SAME protected, already-existing
accessor the rest of the system uses on every access
(ARPGCombatCore.ensure_enemy / ARPGActorCore.ensure_actor) to regenerate a
fresh row deterministically from the NPC's own canonical class/tier -- the
exact same formula that produced its very first combat-ready state. No
public reset/respawn API exists on either core (confirmed by reading both
modules in full before writing this tool); a narrowly-scoped, single-row,
transactional DELETE inside this formal tool is therefore the documented,
permitted fallback (Section 7 of the authorization).

Target-set discovery is dynamic: it re-derives the exact same eligibility
filter already authoritative in
Stage16BAuthorityAdapter._ensure_development_combat_encounter() (ACTIVE
status, class not in {CHILD, PLAYER_AVATAR}, not protected, combat_targetable,
never the player) plus the SAME metric spatial bound method
(_within_active_engagement_metric_bound), called directly on a real
constructed adapter instance rather than reimplemented by hand -- no NPC ref,
count or distance is hardcoded anywhere in this file.

CLI:
    python reset_stage17_local_combat_test_state.py --db PATH --world-instance-id ID [--apply]

    Default is a DRY RUN (report only, zero writes). --apply performs the
    single transactional recovery pass. Safe to re-run in either mode any
    number of times: once every eligible actor is pristine, both modes
    report zero rows to change (idempotent).
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

TOOL_VERSION = "V1.0.0-S17-C3R6-COMBAT-STATE-RECOVERY"
AUTHORITY = "STAGE17_DEV_COMBAT_TEST_STATE_RECOVERY_TOOL"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = PROJECT_ROOT / "01_RUNTIME"
BACKEND_DIR = PROJECT_ROOT / "12_AUTHORITY_BACKEND_STAGE17"

DEFAULT_MASTER_RELEASE = Path(r"C:\Users\thall\ANDROMEDA_PRODUCT\ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip")
DEFAULT_SAVE_ROOT = PROJECT_ROOT / "STAGE17_RUNTIME_STATE" / "saves"
DEFAULT_RESOURCE_MANIFEST = (
    PROJECT_ROOT / "STAGE17_CONTENT" / "RESOURCE_PLACEMENT" / "CANONICAL" / "S17_RESOURCE_METRIC_PLACEMENTS_R0001.json"
)
DEFAULT_OWNER_SCOPE = "stage17:playable-v0-dev"
DEFAULT_WORLD_SEED = "160800"

PRISTINE_OVERLAY_DEFAULTS = {
    "attack_cooldown_remaining_s": 0.0,
    "stagger_remaining_s": 0.0,
    "statuses": [],
    "last_target_ref": None,
    "combat_state": "READY",
}
PRISTINE_AI_DEFAULTS = {
    "state": "IDLE",
    "target_profile_ref": None,
    "target_actor_ref": None,
    "decision_sequence": 0,
    "attack_cooldown_s": 0.0,
    "last_distance_m": None,
    "last_reason": None,
}


def _enemy_state_pristine(payload: dict[str, Any] | None) -> bool:
    if payload is None:
        return True  # never engaged -- ensure_enemy() will produce a fresh combat-ready row
    if str(payload.get("life_state")) != "ALIVE":
        return False
    try:
        return float(payload.get("health", 0.0)) >= float(payload.get("max_health", 0.0))
    except (TypeError, ValueError):
        return False


def _overlay_pristine(payload: dict[str, Any] | None) -> bool:
    if payload is None:
        return True
    return all(payload.get(key) == value for key, value in PRISTINE_OVERLAY_DEFAULTS.items())


def _ai_state_pristine(payload: dict[str, Any] | None) -> bool:
    if payload is None:
        return True
    return all(payload.get(key) == value for key, value in PRISTINE_AI_DEFAULTS.items())


def _load_row(conn, table: str, world_instance_id: str, actor_ref: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT payload_json,payload_hash FROM {table} WHERE world_instance_id=? AND actor_ref=?",
        (world_instance_id, actor_ref),
    ).fetchone()
    if row is None:
        return None
    from living_runtime import sha256_text  # noqa: PLC0415

    if sha256_text(row["payload_json"]) != row["payload_hash"]:
        raise RuntimeError(f"STATE_HASH_MISMATCH:{table}:{actor_ref}")
    return json.loads(row["payload_json"])


def _delete_row(conn, table: str, world_instance_id: str, actor_ref: str) -> int:
    cur = conn.execute(
        f"DELETE FROM {table} WHERE world_instance_id=? AND actor_ref=?",
        (world_instance_id, actor_ref),
    )
    return cur.rowcount


def build_adapter(db_path: Path, world_instance_id: str, *, resource_manifest: Path, master_release: Path,
                   save_root: Path, owner_scope: str, world_seed: str):
    """Construct a real Stage16BAuthorityAdapter with dev-profile bootstrap
    disabled for THIS tool's own read/fix pass only -- never sets this for the
    real server. Reuses the exact same adapter class the backend boots with;
    nothing about the adapter itself is modified or subclassed.
    """
    os.environ["ANDROMEDA_S16B_DB"] = str(db_path)
    os.environ["ANDROMEDA_S16B_SAVE_ROOT"] = str(save_root)
    os.environ["ANDROMEDA_S17_RESOURCE_PLACEMENT_MANIFEST"] = str(resource_manifest)
    os.environ["ANDROMEDA_MASTER_RELEASE"] = str(master_release)
    os.environ["ANDROMEDA_S16B_OWNER_SCOPE"] = owner_scope
    os.environ["ANDROMEDA_S16B_SEED"] = world_seed
    os.environ["ANDROMEDA_S16B_DEV_PROFILE_BOOTSTRAP"] = "0"

    for p in (str(RUNTIME_DIR), str(BACKEND_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from andromeda_authority_adapter import Stage16BAuthorityAdapter  # noqa: PLC0415

    adapter = Stage16BAuthorityAdapter()
    if adapter.world_instance_id != world_instance_id:
        adapter.close()
        raise RuntimeError(
            f"WORLD_INSTANCE_ID_MISMATCH: expected {world_instance_id!r}, "
            f"DB actually resumed {adapter.world_instance_id!r} -- refusing to proceed"
        )
    return adapter


def discover_target_set(adapter: Any) -> list[str]:
    """Exact same eligibility filter as _ensure_development_combat_encounter()'s
    candidate search (class/status/protection) plus the same metric spatial
    bound method, called directly on the real adapter -- not reimplemented.
    """
    country = adapter._engine.country(adapter.world_instance_id)
    movement = adapter._engine.movement(adapter.world_instance_id)
    excluded = {adapter._player_ref}
    target_set: list[str] = []
    for npc in country._all_npc_records():
        ref = str(npc.get("id") or "").strip()
        protection = npc.get("protection") or {}
        if (
            not ref
            or ref in excluded
            or str(npc.get("status", "ACTIVE")).upper() != "ACTIVE"
            or str(npc.get("class") or "").upper() in {"CHILD", "PLAYER_AVATAR"}
            or bool(protection.get("protected", False))
            or not bool(protection.get("combat_targetable", True))
        ):
            continue
        try:
            position = movement.state(ref)
        except Exception:
            continue
        if not adapter._within_active_engagement_metric_bound(
            float(position["iso_x_m"]), float(position["iso_y_m"])
        ):
            continue
        target_set.append(ref)
    return sorted(target_set)


def audit(adapter: Any, target_set: list[str]) -> dict[str, Any]:
    conn = adapter._engine.runtime.conn
    wid = adapter.world_instance_id
    entries = []
    for ref in target_set:
        enemy_state = _load_row(conn, "arpg_enemy_combat_state", wid, ref)
        overlay = _load_row(conn, "arpg_combat_overlay", wid, ref)
        ai_state = _load_row(conn, "arpg_actor_ai_state", wid, ref)
        enemy_pristine = _enemy_state_pristine(enemy_state)
        overlay_pristine = _overlay_pristine(overlay)
        ai_pristine = _ai_state_pristine(ai_state)
        entries.append(
            {
                "target_ref": ref,
                "base_npc_exists": True,  # guaranteed: ref came from country._all_npc_records() itself
                "enemy_combat_state": enemy_state,
                "enemy_combat_state_pristine": enemy_pristine,
                "combat_overlay": overlay,
                "combat_overlay_pristine": overlay_pristine,
                "actor_ai_state": ai_state,
                "actor_ai_state_pristine": ai_pristine,
                "fully_pristine": enemy_pristine and overlay_pristine and ai_pristine,
                "eligible_for_selection_now": enemy_pristine,  # the ONLY state that actually gates COMMON/ALPHA
                "action_needed": "RESET" if not (enemy_pristine and overlay_pristine and ai_pristine) else "NONE",
            }
        )
    return {
        "target_set_size": len(target_set),
        "eligible_now": sum(1 for e in entries if e["eligible_for_selection_now"]),
        "fully_pristine_now": sum(1 for e in entries if e["fully_pristine"]),
        "needing_reset": sum(1 for e in entries if e["action_needed"] == "RESET"),
        "entries": entries,
    }


def apply_recovery(adapter: Any, audit_before: dict[str, Any]) -> dict[str, Any]:
    """Single transactional pass: delete exactly the non-pristine rows already
    identified by audit_before, then immediately regenerate through the
    protected cores' own accessors so the report shows real post-state, not
    an assumption.
    """
    engine = adapter._engine
    conn = engine.runtime.conn
    wid = adapter.world_instance_id
    combat_core = engine.combat_arpg(wid)
    actor_core = engine.actors_arpg(wid)

    deleted: dict[str, list[str]] = {"arpg_enemy_combat_state": [], "arpg_combat_overlay": [], "arpg_actor_ai_state": []}
    regenerated: list[dict[str, Any]] = []

    with engine.runtime._write_lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for entry in audit_before["entries"]:
                if entry["action_needed"] != "RESET":
                    continue
                ref = entry["target_ref"]
                if not entry["enemy_combat_state_pristine"]:
                    if _delete_row(conn, "arpg_enemy_combat_state", wid, ref):
                        deleted["arpg_enemy_combat_state"].append(ref)
                if not entry["combat_overlay_pristine"]:
                    # Extra safety: never delete a PLAYER-kind overlay row, even
                    # though `ref` can never be the player (excluded at
                    # discovery time) -- verified again here defensively.
                    payload = entry.get("combat_overlay") or {}
                    if payload.get("actor_kind") == "PLAYER":
                        raise RuntimeError(f"REFUSING_PLAYER_OVERLAY_DELETE:{ref}")
                    if _delete_row(conn, "arpg_combat_overlay", wid, ref):
                        deleted["arpg_combat_overlay"].append(ref)
                if not entry["actor_ai_state_pristine"]:
                    if _delete_row(conn, "arpg_actor_ai_state", wid, ref):
                        deleted["arpg_actor_ai_state"].append(ref)
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

    # Checkpoint immediately -- a prior round found post-commit read-only
    # verification can otherwise observe stale pre-checkpoint WAL bytes.
    try:
        conn.execute("PRAGMA wal_checkpoint(FULL)")
    except Exception:
        pass

    # Regenerate through the SAME protected accessors every other caller
    # uses -- proves the post-state, does not merely assume it.
    for entry in audit_before["entries"]:
        if entry["action_needed"] != "RESET":
            continue
        ref = entry["target_ref"]
        fresh_enemy = combat_core.ensure_enemy(ref) if ref in deleted["arpg_enemy_combat_state"] else None
        fresh_actor = actor_core.ensure_actor(ref) if ref in deleted["arpg_actor_ai_state"] else None
        fresh_ai = actor_core.ai_state(ref) if ref in deleted["arpg_actor_ai_state"] else None
        regenerated.append(
            {
                "target_ref": ref,
                "regenerated_enemy_combat_state": fresh_enemy,
                "regenerated_actor_profile_ai_enabled": (fresh_actor or {}).get("ai_enabled") if fresh_actor else None,
                "regenerated_actor_ai_state": fresh_ai,
            }
        )

    return {
        "status": "PASS",
        "deleted_rows": deleted,
        "deleted_row_count": sum(len(v) for v in deleted.values()),
        "regenerated": regenerated,
        "authority": AUTHORITY,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--world-instance-id", required=True, type=str)
    parser.add_argument("--master-release", type=Path, default=DEFAULT_MASTER_RELEASE)
    parser.add_argument("--save-root", type=Path, default=DEFAULT_SAVE_ROOT)
    parser.add_argument("--resource-placement-manifest", type=Path, default=DEFAULT_RESOURCE_MANIFEST)
    parser.add_argument("--owner-scope", type=str, default=DEFAULT_OWNER_SCOPE)
    parser.add_argument("--world-seed", type=str, default=DEFAULT_WORLD_SEED)
    parser.add_argument("--apply", action="store_true", help="Execute the recovery. Default is dry-run (report only).")
    parser.add_argument("--out", type=Path, default=None, help="Optional path to also write the JSON report to.")
    args = parser.parse_args()

    adapter = build_adapter(
        args.db,
        args.world_instance_id,
        resource_manifest=args.resource_placement_manifest,
        master_release=args.master_release,
        save_root=args.save_root,
        owner_scope=args.owner_scope,
        world_seed=args.world_seed,
    )
    try:
        target_set = discover_target_set(adapter)
        audit_before = audit(adapter, target_set)
        report: dict[str, Any] = {
            "tool_version": TOOL_VERSION,
            "authority": AUTHORITY,
            "mode": "APPLY" if args.apply else "DRY_RUN",
            "db_path": str(args.db),
            "world_instance_id": adapter.world_instance_id,
            "engagement_center_and_radius": adapter._active_engagement_center_and_radius_m(),
            "audit_before": audit_before,
        }
        if args.apply:
            result = apply_recovery(adapter, audit_before)
            report["recovery_result"] = result
            target_set_after = discover_target_set(adapter)
            report["audit_after"] = audit(adapter, target_set_after)
        print(json.dumps(report, indent=2, default=str))
        if args.out:
            args.out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        return 0
    finally:
        adapter.close()


if __name__ == "__main__":
    raise SystemExit(main())
