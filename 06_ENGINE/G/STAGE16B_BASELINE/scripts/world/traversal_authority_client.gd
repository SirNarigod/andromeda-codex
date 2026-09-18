extends Node
class_name AndromedaTraversalAuthorityClient

## Samples Godot traversal physics and sends observations upstream. Surface/load
## coefficients and stamina mutation remain entirely in Stage16A.

signal traversal_sample_submitted(result: Dictionary)
signal traversal_result_received(result: Dictionary)

const AUTHORITY := "GODOT_TRAVERSAL_SENSOR_CLIENT_ONLY"
const SAMPLE_INTERVAL_S := 0.25
const MIN_SAMPLE_DISTANCE_M := 0.01

var _player: AndromedaPlayerController
var _terrain: AndromedaTerrainFoundation
var _bound: bool = false
var _previous_position: Vector3 = Vector3.ZERO
var _distance_accumulator_m: float = 0.0
var _sample_elapsed_s: float = 0.0
var _ascending: bool = true
var _command_pending: bool = false
var _last_submission: Dictionary = {}
var _last_authoritative_result: Dictionary = {}


func _ready() -> void:
	process_physics_priority = 95


func bind_runtime(
	player_value: AndromedaPlayerController,
	terrain_value: AndromedaTerrainFoundation
) -> Dictionary:
	if player_value == null or terrain_value == null:
		return _rejected("PLAYER_AND_TERRAIN_REQUIRED")
	_player = player_value
	_terrain = terrain_value
	_previous_position = _player.global_position
	var bridge := _bridge()
	if bridge != null and not bridge.command_result_received.is_connected(_on_command_result_received):
		bridge.command_result_received.connect(_on_command_result_received)
	_bound = true
	return {"status": "PASS", "authority": AUTHORITY}


func _physics_process(delta: float) -> void:
	if not _bound or _player == null or _terrain == null:
		return
	var current: Vector3 = _player.global_position
	var horizontal_delta := Vector2(current.x - _previous_position.x, current.z - _previous_position.z)
	var distance: float = horizontal_delta.length()
	if distance > 0.0:
		_distance_accumulator_m += distance
		_ascending = current.y >= _previous_position.y
	_previous_position = current
	_sample_elapsed_s += delta
	if _sample_elapsed_s < SAMPLE_INTERVAL_S or _distance_accumulator_m < MIN_SAMPLE_DISTANCE_M:
		return
	_sample_elapsed_s = 0.0
	if _command_pending:
		return
	var sample: Dictionary = _terrain.surface_sample(current)
	var surface_ref: String = str(sample.get("surface_kind", "")).strip_edges().to_upper()
	# Water has its own Stage16A authority contract and is integrated separately.
	if surface_ref.begins_with("WATER_"):
		_distance_accumulator_m = 0.0
		return
	force_submit_sample(
		_distance_accumulator_m,
		float(sample.get("slope_deg", 0.0)),
		surface_ref,
		_ascending
	)
	_distance_accumulator_m = 0.0


func force_submit_sample(
	distance_m: float,
	slope_deg: float,
	surface_ref: String,
	ascending: bool = true
) -> Dictionary:
	if not _bound:
		return _rejected("TRAVERSAL_CLIENT_NOT_BOUND")
	if not is_finite(distance_m) or distance_m < 0.0 or not is_finite(slope_deg):
		return _rejected("INVALID_TRAVERSAL_OBSERVATION")
	var normalized_surface: String = surface_ref.strip_edges().to_upper()
	if normalized_surface.is_empty() or normalized_surface.begins_with("WATER_"):
		return _rejected("LAND_TRAVERSAL_SURFACE_REQUIRED")
	var bridge := _bridge()
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	var params := {
		"distance_m": distance_m,
		"slope_deg": slope_deg,
		"surface_ref": normalized_surface,
		"ascending": ascending,
	}
	var built: Dictionary = bridge.build_command_envelope("REPORT_TRAVERSAL_SAMPLE", params)
	if built.get("status") != "PASS":
		return built
	var transport: Dictionary = {"status": "NOT_AVAILABLE", "reason": "AUTHORITY_NOT_READY"}
	var authority_state: Dictionary = bridge.connection_state()
	if authority_state.get("authority_session_bound") == true:
		var command_ref: String = str(built.get("envelope", {}).get("command_ref", ""))
		transport = bridge.submit_command("REPORT_TRAVERSAL_SAMPLE", params, command_ref)
		_command_pending = transport.get("status") == "PASS"
	_last_submission = {
		"status": "PASS",
		"intent": "REPORT_TRAVERSAL_SAMPLE",
		"observation": params,
		"intent_envelope": built,
		"transport_result": transport,
		"transport_submitted": transport.get("status") == "PASS",
		"load_calculated_locally": false,
		"stamina_mutated_locally": false,
		"authority": AUTHORITY,
	}
	traversal_sample_submitted.emit(_last_submission.duplicate(true))
	return _last_submission.duplicate(true)


func last_submission() -> Dictionary:
	return _last_submission.duplicate(true)


func last_authoritative_result() -> Dictionary:
	return _last_authoritative_result.duplicate(true)


func contract_snapshot() -> Dictionary:
	return {
		"surface_observation_in_godot": true,
		"load_authority_in_gdscript": false,
		"stamina_authority_in_gdscript": false,
		"water_authority_in_gdscript": false,
		"sample_interval_s": SAMPLE_INTERVAL_S,
		"authority": AUTHORITY,
	}


func _on_command_result_received(result: Dictionary) -> void:
	if str(result.get("command", "")).strip_edges().to_upper() != "REPORT_TRAVERSAL_SAMPLE":
		return
	_command_pending = false
	_last_authoritative_result = result.duplicate(true)
	traversal_result_received.emit(_last_authoritative_result.duplicate(true))


func _bridge() -> AndromedaRuntimeBridge:
	return get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
