extends Node
class_name LivingWorldClient

signal snapshot_applied(snapshot: Dictionary)
signal command_built(envelope: Dictionary)
signal command_rejected(reason: String)

var session_ref: String = ""
var current_chunk_id: String = ""
var iso_position_m: Vector2 = Vector2.ZERO
var altitude_m: float = 0.0
var heading_deg: float = 0.0
var environment: Dictionary = {}
var visible_entities: Dictionary = {}

func bind_session(value: String) -> void:
    session_ref = value.strip_edges()

func apply_snapshot(snapshot: Dictionary) -> bool:
    if snapshot.get("status") != "PASS":
        command_rejected.emit(str(snapshot.get("reason", "SNAPSHOT_REJECTED")))
        return false
    if snapshot.get("server_authoritative") != true:
        command_rejected.emit("NON_AUTHORITATIVE_SNAPSHOT")
        return false
    var transform: Dictionary = snapshot.get("transform", {})
    var chunk: Dictionary = snapshot.get("chunk", {})
    if not transform.has("iso_x_m") or not transform.has("iso_y_m"):
        command_rejected.emit("INVALID_TRANSFORM")
        return false
    current_chunk_id = str(chunk.get("chunk_id", ""))
    iso_position_m = Vector2(float(transform["iso_x_m"]), float(transform["iso_y_m"]))
    altitude_m = float(transform.get("altitude_m", 0.0))
    heading_deg = float(transform.get("heading_deg", 0.0))
    environment = snapshot.get("environment", {}).duplicate(true)
    visible_entities.clear()
    for entry in chunk.get("entities", []):
        var ref := str(entry.get("entity_ref", ""))
        if not ref.is_empty():
            visible_entities[ref] = entry.duplicate(true)
    snapshot_applied.emit(snapshot.duplicate(true))
    return true

func build_move_vector(direction: Vector2, duration_s: float, mode: String = "WALK") -> Dictionary:
    return _build("MOVE_VECTOR", {
        "dx": direction.x,
        "dy": direction.y,
        "duration_s": clampf(duration_s, 0.01, 10.0),
        "mode": mode.to_upper(),
    })

func build_interaction(object_id: String, action: String, max_distance_m: float = 2.5) -> Dictionary:
    return _build("INTERACT", {
        "object_id": object_id,
        "action": action.to_upper(),
        "max_distance_m": max_distance_m,
    })

func build_discovery(radius_m: float = 250.0) -> Dictionary:
    return _build("DISCOVER", {"radius_m": radius_m})

func build_path_plan(destination_block_id: String) -> Dictionary:
    return _build("PATH_PLAN", {"destination_block_id": destination_block_id})

func build_dungeon_move(to_room_id: String) -> Dictionary:
    return _build("DUNGEON_MOVE", {"to_room_id": to_room_id})

func _build(command: String, params: Dictionary) -> Dictionary:
    if session_ref.is_empty():
        command_rejected.emit("SESSION_NOT_BOUND")
        return {}
    var envelope := {
        "session_ref": session_ref,
        "command": command,
        "params": params.duplicate(true),
    }
    command_built.emit(envelope.duplicate(true))
    return envelope
