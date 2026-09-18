"""Read-only gathering authority inventory for Stage16B integration work."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent / "var" / "stage16b_world.sqlite"


def main() -> None:
    connection = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    queries = {
        "bootstrap": "SELECT * FROM s16b_bootstrap ORDER BY key",
        "node_counts": (
            "SELECT activity_type, COUNT(*) AS count FROM arpg_gathering_nodes "
            "GROUP BY activity_type ORDER BY activity_type"
        ),
        "node_samples": (
            "SELECT node_ref,zone_ref,block_ref,activity_type,source_kind,output_item_ref "
            "FROM arpg_gathering_nodes ORDER BY activity_type,node_ref LIMIT 30"
        ),
        "current_zone_nodes": (
            "SELECT node_ref,zone_ref,block_ref,activity_type,source_kind,output_item_ref,"
            "definition_json FROM arpg_gathering_nodes "
            "WHERE zone_ref='ZONE-STA-05-BLK-04' ORDER BY activity_type,node_ref"
        ),
        "profile_state": "SELECT * FROM arpg_world_profile_state",
        "recent_commands": (
            "SELECT command_ref,session_ref,command,result_json FROM s16b_command_journal "
            "ORDER BY rowid DESC LIMIT 20"
        ),
    }
    for label, query in queries.items():
        rows = [dict(row) for row in connection.execute(query)]
        print(label, json.dumps(rows, ensure_ascii=False, indent=2))
    connection.close()


if __name__ == "__main__":
    main()
