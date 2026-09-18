extends CharacterBody3D
class_name AndromedaPlayerController

## Local movement prediction and Godot physics/navigation presentation only.
## The bridge envelope carries intent; this script never decides gameplay outcomes.

signal movement_intent_created(result: Dictionary)
signal destination_rejected(result: Dictionary)
signal destination_reached(world_position: Vector3)

const AUTHORITY := "GODOT_NAVIGATION_PRESENTATION_ONLY"
const MAX_DESTINATION_PROJECTION_M := 0.75

@export var movement_speed_mps: float = 5.0
@export var acceleration_mps2: float = 28.0
@export var deceleration_mps2: float = 36.0
@export var arrival_distance_m: float = 0.16

@onready var navigation_agent: NavigationAgent3D = $NavigationAgent3D

var _has_destination: bool = false
var _destination: Vector3 = Vector3.ZERO
var _last_request: Dictionary = {}


func _ready() -> void:
	navigation_agent.path_desired_distance = 0.12
	navigation_agent.target_desired_distance = arrival_distance_m
	navigation_agent.avoidance_enabled = false
	floor_stop_on_slope = true
	floor_snap_length = 0.2


func _physics_process(delta: float) -> void:
	_apply_vertical_velocity(delta)
	if not _has_destination:
		velocity.x = move_toward(velocity.x, 0.0, deceleration_mps2 * delta)
		velocity.z = move_toward(velocity.z, 0.0, deceleration_mps2 * delta)
		move_and_slide()
		return
	var horizontal_to_destination := Vector2(
		_destination.x - global_position.x,
		_destination.z - global_position.z
	)
	if horizontal_to_destination.length() <= arrival_distance_m:
		_complete_destination()
		move_and_slide()
		return
	var next_path_position: Vector3 = navigation_agent.get_next_path_position()
	var horizontal_direction := Vector2(
		next_path_position.x - global_position.x,
		next_path_position.z - global_position.z
	)
	if horizontal_direction.length_squared() <= 0.000001:
		horizontal_direction = horizontal_to_destination
	if horizontal_direction.length_squared() > 0.000001:
		horizontal_direction = horizontal_direction.normalized()
	var desired_x: float = horizontal_direction.x * movement_speed_mps
	var desired_z: float = horizontal_direction.y * movement_speed_mps
	velocity.x = move_toward(velocity.x, desired_x, acceleration_mps2 * delta)
	velocity.z = move_toward(velocity.z, desired_z, acceleration_mps2 * delta)
	move_and_slide()


func request_move(world_destination: Vector3) -> Dictionary:
	var validation: Dictionary = validate_destination(world_destination)
	if validation.get("status") != "PASS":
		_last_request = validation.duplicate(true)
		destination_rejected.emit(validation.duplicate(true))
		return validation
	_destination = validation["navigation_destination"]
	navigation_agent.target_position = _destination
	_has_destination = true
	var bridge_result: Dictionary = _build_bridge_envelope(_destination)
	_last_request = {
		"status": "PASS",
		"intent": "MOVE_TO_POINT",
		"navigation_destination": _destination,
		"path_point_count": int(validation.get("path_point_count", 0)),
		"bridge_envelope": bridge_result,
		"local_prediction": true,
		"authority": AUTHORITY,
	}
	movement_intent_created.emit(_last_request.duplicate(true))
	return _last_request.duplicate(true)


func validate_destination(world_destination: Vector3) -> Dictionary:
	var navigation_map: RID = navigation_agent.get_navigation_map()
	if not navigation_map.is_valid() or NavigationServer3D.map_get_iteration_id(navigation_map) <= 0:
		return _rejected("NAVIGATION_MAP_NOT_READY")
	var closest: Vector3 = NavigationServer3D.map_get_closest_point(navigation_map, world_destination)
	var projection_distance: float = Vector2(world_destination.x, world_destination.z).distance_to(
		Vector2(closest.x, closest.z)
	)
	if projection_distance > MAX_DESTINATION_PROJECTION_M:
		return _rejected("UNREACHABLE_DESTINATION", {
			"requested_destination": world_destination,
			"closest_navigation_point": closest,
			"projection_distance_m": projection_distance,
		})
	var path: PackedVector3Array = NavigationServer3D.map_get_path(
		navigation_map,
		global_position,
		closest,
		true
	)
	if path.is_empty():
		return _rejected("UNREACHABLE_DESTINATION", {"path_point_count": 0})
	var final_point: Vector3 = path[path.size() - 1]
	var final_distance: float = Vector2(final_point.x, final_point.z).distance_to(Vector2(closest.x, closest.z))
	if final_distance > arrival_distance_m:
		return _rejected("UNREACHABLE_DESTINATION", {"path_end_distance_m": final_distance})
	return {
		"status": "PASS",
		"navigation_destination": closest,
		"path": path,
		"path_point_count": path.size(),
		"authority": AUTHORITY,
	}


func preview_path(world_destination: Vector3) -> PackedVector3Array:
	var validation: Dictionary = validate_destination(world_destination)
	if validation.get("status") != "PASS":
		return PackedVector3Array()
	return validation.get("path", PackedVector3Array()) as PackedVector3Array


func has_destination() -> bool:
	return _has_destination


func requested_destination() -> Vector3:
	return _destination


func last_request() -> Dictionary:
	return _last_request.duplicate(true)


func stop_local_prediction() -> void:
	_has_destination = false
	velocity.x = 0.0
	velocity.z = 0.0
	navigation_agent.target_position = global_position


func _complete_destination() -> void:
	_has_destination = false
	velocity.x = 0.0
	velocity.z = 0.0
	global_position.x = _destination.x
	global_position.z = _destination.z
	destination_reached.emit(global_position)


func _apply_vertical_velocity(delta: float) -> void:
	if is_on_floor():
		velocity.y = 0.0
	else:
		velocity.y -= float(ProjectSettings.get_setting("physics/3d/default_gravity", 9.8)) * delta


func _build_bridge_envelope(world_destination: Vector3) -> Dictionary:
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	return bridge.build_command_envelope("MOVE_TO_POINT", {
		"iso_x_m": world_destination.x,
		"iso_y_m": world_destination.z,
		"duration_s": 0.25,
		"mode": "WALK",
	})


func _rejected(reason: String, detail: Dictionary = {}) -> Dictionary:
	var result: Dictionary = {
		"status": "REJECTED",
		"reason": reason,
		"authority": AUTHORITY,
	}
	result.merge(detail, true)
	return result
