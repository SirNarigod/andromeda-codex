"""Seed server-owned Ground Loot preconditions for the real Godot pickup gate.

This is deliberately not an HTTP endpoint and not a gameplay authority. It runs
only while the authority process is stopped, creates physical drops through the
protected Stage16A GroundLootCore, and records exactly which preconditions were
created. Pickup outcomes remain real Stage16A decisions over the persisted world.
"""

from __future__ import annotations

import argparse
import json
import time

from andromeda_authority_adapter import Stage16BAuthorityAdapter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-ref", default=f"PICKUP-{int(time.time())}")
    args = parser.parse_args()

    adapter = Stage16BAuthorityAdapter()
    try:
        stage16a = adapter._engine.stage16a(adapter.world_instance_id)
        movement = adapter._engine.movement(adapter.world_instance_id)
        state = movement.state(adapter._player_ref)
        origin = {
            "iso_x_m": float(state["iso_x_m"]),
            "iso_y_m": float(state["iso_y_m"]),
            "altitude_m": float(state.get("altitude_m", 0.0)),
        }
        specs = (
            ("EXACT", 0.5, True, True),
            ("FAR", 0.5001, True, True),
            ("UNSETTLED", 0.1, False, False),
            ("UNREACHABLE", 0.1, True, False),
        )
        drops = []
        for label, distance_m, settled, reachable in specs:
            source_ref = f"S16B-GODOT-PICKUP-PROBE:{args.probe_ref}:{label}"
            position = {
                "iso_x_m": origin["iso_x_m"] + distance_m,
                "iso_y_m": origin["iso_y_m"],
                "altitude_m": origin["altitude_m"],
            }
            event_prefix = f"S16B:GODOT:{args.probe_ref}:{label}"
            spawned = stage16a.ground_loot.spawn_drop(
                source_ref=source_ref,
                source_kind="PLAYER_DROP",
                item_ref="ITEM-GRAIN",
                item_kind="MATERIAL",
                quantity=1,
                candidate_position=position,
                event_ref=event_prefix + ":SPAWN",
            )
            if spawned.get("status") != "PASS":
                raise RuntimeError(f"probe spawn failed: {spawned}")
            drop_ref = str(spawned["drop_ref"])
            if settled:
                settled_result = stage16a.confirm_drop_settled(
                    drop_ref,
                    settled_position=position,
                    reachable=reachable,
                    event_ref=event_prefix + ":SETTLE",
                )
                if settled_result.get("status") != "PASS":
                    raise RuntimeError(f"probe settle failed: {settled_result}")
            drops.append(
                {
                    "label": label,
                    "drop_ref": drop_ref,
                    "source_ref": source_ref,
                    "distance_m": distance_m,
                    "settled": settled,
                    "reachable": reachable,
                    "position": position,
                }
            )
        report = {
            "status": "PASS",
            "probe_ref": args.probe_ref,
            "world_instance_id": adapter.world_instance_id,
            "profile_ref": adapter.profile_ref,
            "player_ref": adapter._player_ref,
            "profile_avatar_ref": adapter.avatar_ref,
            "same_profile_actor": adapter._player_ref == adapter.avatar_ref,
            "server_owned_test_precondition": True,
            "canonical_mutation": False,
            "http_test_endpoint_created": False,
            "pickup_outcome_seeded": False,
            "drops": drops,
        }
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        adapter.close()


if __name__ == "__main__":
    raise SystemExit(main())
