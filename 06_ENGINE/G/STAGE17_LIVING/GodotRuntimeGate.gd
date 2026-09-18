extends SceneTree

var failures: Array[String] = []

func check(name: String, condition: bool) -> void:
    if not condition:
        failures.append(name)

func _initialize() -> void:
    var script = load("res://LivingWorldClient.gd")
    check("CLIENT_SCRIPT_LOAD", script != null)
    if script == null:
        _finish()
        return
    var client = script.new()
    root.add_child(client)
    client.bind_session("GODOT-GATE-SESSION")
    var snapshot := {
        "status": "PASS",
        "server_authoritative": true,
        "transform": {"iso_x_m": 12.5, "iso_y_m": -4.25, "altitude_m": 3.0, "heading_deg": 90.0},
        "chunk": {"chunk_id": "CHK-TEST", "entities": [{"entity_ref": "NPC-TEST", "kind": "NPC", "isometric": {"x_m": 12.5, "y_m": -4.25, "z_m": 3.0}}]},
        "environment": {"temperature_c": 22.0, "daylight": 0.75}
    }
    check("SNAPSHOT_APPLY", client.apply_snapshot(snapshot))
    check("POSITION_X", is_equal_approx(client.iso_position_m.x, 12.5))
    check("POSITION_Y", is_equal_approx(client.iso_position_m.y, -4.25))
    check("ENTITY_VISIBLE", client.visible_entities.has("NPC-TEST"))
    var envelopes := [
        client.build_move_vector(Vector2(1, 0), 0.25, "WALK"),
        client.build_interaction("DOOR-TEST", "OPEN"),
        client.build_discovery(100.0),
        client.build_path_plan("STA-TEST-BLK-02"),
        client.build_dungeon_move("ROOM-TEST-02")
    ]
    var expected := ["MOVE_VECTOR", "INTERACT", "DISCOVER", "PATH_PLAN", "DUNGEON_MOVE"]
    for i in range(envelopes.size()):
        check("COMMAND_%s" % expected[i], envelopes[i].get("command") == expected[i])
        check("SESSION_%s" % expected[i], envelopes[i].get("session_ref") == "GODOT-GATE-SESSION")
        check("NO_PLAYER_REF_%s" % expected[i], not envelopes[i].has("player_ref"))
    _finish()

func _finish() -> void:
    if failures.is_empty():
        print("ANDROMEDA_GODOT_V1_5_RUNTIME_GATE: PASS")
        quit(0)
    else:
        print("ANDROMEDA_GODOT_V1_5_RUNTIME_GATE: FAIL ", failures)
        quit(1)
