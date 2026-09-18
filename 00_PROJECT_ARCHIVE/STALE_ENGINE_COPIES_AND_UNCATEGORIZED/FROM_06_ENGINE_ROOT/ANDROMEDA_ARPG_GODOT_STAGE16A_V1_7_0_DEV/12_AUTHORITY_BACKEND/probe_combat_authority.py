"""Read-only probe for the live Stage16B combat authority database.

This script never boots the engine and never writes.  It is safe to run while the
single authoritative uvicorn worker owns the runtime connection.
"""

from __future__ import annotations

import json
import math
import sqlite3

from authority_config import load_config


def main() -> None:
    config = load_config()
    uri = config.db_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = [
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        bootstrap = {
            str(row["key"]): str(row["value"])
            for row in connection.execute("SELECT key,value FROM s16b_bootstrap")
        }
        player_ref = bootstrap["player_ref"]
        player = dict(
            connection.execute(
                "SELECT entity_ref,iso_x_m,iso_y_m,altitude_m,stamina "
                "FROM v15_motion_state WHERE entity_ref=?",
                (player_ref,),
            ).fetchone()
        )
        nearby: list[dict[str, object]] = []
        for row in connection.execute(
            "SELECT entity_ref,iso_x_m,iso_y_m,altitude_m FROM v15_motion_state "
            "WHERE entity_ref<>?",
            (player_ref,),
        ):
            distance = math.hypot(
                float(row["iso_x_m"]) - float(player["iso_x_m"]),
                float(row["iso_y_m"]) - float(player["iso_y_m"]),
            )
            nearby.append(
                {
                    "entity_ref": str(row["entity_ref"]),
                    "distance_m": round(distance, 6),
                    "iso_x_m": float(row["iso_x_m"]),
                    "iso_y_m": float(row["iso_y_m"]),
                    "altitude_m": float(row["altitude_m"]),
                }
            )
        nearby.sort(key=lambda entry: (float(entry["distance_m"]), str(entry["entity_ref"])))
        report = {
            "status": "PASS",
            "read_only": True,
            "db_path": str(config.db_path),
            "world_instance_id": bootstrap.get("world_instance_id"),
            "profile_ref": bootstrap.get("profile_ref"),
            "player": player,
            "motion_actor_count": len(nearby) + 1,
            "nearest_motion_actors": nearby[:20],
            "combat_tables": [name for name in tables if "combat" in name],
        }
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
