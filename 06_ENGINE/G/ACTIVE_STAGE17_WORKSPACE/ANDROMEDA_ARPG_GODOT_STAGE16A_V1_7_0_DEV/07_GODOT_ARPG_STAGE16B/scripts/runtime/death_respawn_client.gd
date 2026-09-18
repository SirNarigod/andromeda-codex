extends Node
class_name AndromedaDeathRespawnClient

## B10 death/recovery/respawn presentation boundary. Every state transition applied
## here is externally confirmed; this node never decides death, retention or spawn.

signal death_projected(result: Dictionary)
signal respawn_request_prepared(result: Dictionary)
signal respawn_projected(result: Dictionary)
signal input_block_changed(blocked: bool, reason: String)

const AUTHORITY := "GODOT_DEATH_RESPAWN_CLIENT_PROJECTION_ONLY"
const STATE_ALIVE := "ALIVE"
const STATE_DEFEATED := "DEFEATED"
const STATE_DEAD_AWAITING_RESPAWN := "DEAD_AWAITING_RESPAWN"
const STATE_RESPAWN_PENDING := "RESPAWN_PENDING"
const STATE_READY := "READY"

var _main_runtime: AndromedaMainRuntime
var _player: AndromedaPlayerController
var _camera_rig: AndromedaIsometricCameraRig
var _hud: AndromedaHUDController
var _dropped_bag_client: AndromedaDroppedBagClient
var _inventory_client: AndromedaInventoryClient
var _state: String = STATE_ALIVE
var _world_input_blocked: bool = false
var _block_reason: String = ""
var _death_sequence: int = -1
var _respawn_sequence: int = -1
var _exhaustion_sequence: int = -1
var _restore_sequence: int = -1
var _request_serial: int = 0
var _last_respawn_request: Dictionary = {}
var _death_projection: Dictionary = {}
var _respawn_projection: Dictionary = {}
var _exhaustion_projection: Dictionary = {}
var _recovery_projection: Dictionary = {}
var _bound: bool = false


func bind_runtime(
	main_runtime_value: AndromedaMainRuntime,
	player_value: AndromedaPlayerController,
	camera_rig_value: AndromedaIsometricCameraRig,
	hud_value: AndromedaHUDController,
	dropped_bag_client_value: AndromedaDroppedBagClient,
	inventory_client_value: AndromedaInventoryClient
) -> Dictionary:
	if (
		main_runtime_value == null
		or player_value == null
		or camera_rig_value == null
		or hud_value == null
		or dropped_bag_client_value == null
		or inventory_client_value == null
	):
		return _rejected("B10_DEATH_RUNTIME_DEPENDENCIES_REQUIRED")
	_main_runtime = main_runtime_value
	_player = player_value
	_camera_rig = camera_rig_value
	_hud = hud_value
	_dropped_bag_client = dropped_bag_client_value
	_inventory_client = inventory_client_value
	if not _bound:
		var bridge: AndromedaRuntimeBridge = _bridge()
		if bridge != null and not bridge.command_result_received.is_connected(_on_bridge_command_result_received):
			bridge.command_result_received.connect(_on_bridge_command_result_received)
		var session: AndromedaClientSession = _session()
		if session != null:
			if not session.session_bound.is_connected(_on_session_bound):
				session.session_bound.connect(_on_session_bound)
			if not session.session_revoked.is_connected(_on_session_revoked):
				session.session_revoked.connect(_on_session_revoked)
		_bound = true
	return {"status": "PASS", "authority": AUTHORITY}


func project_death_event(event: Dictionary) -> Dictionary:
	var external: Dictionary = _validate_external(event, "DEATH_EVENT")
	if external.get("status") != "PASS":
		return external
	var sequence_result: Dictionary = _sequence_from(event, "death_sequence", "INVALID_DEATH_SEQUENCE")
	if sequence_result.get("status") != "PASS":
		return sequence_result
	var sequence: int = int(sequence_result.get("sequence"))
	if sequence <= _death_sequence:
		return _rejected("STALE_OR_DUPLICATE_DEATH_EVENT")
	var death_ref: String = str(event.get("death_ref", "")).strip_edges()
	var projected_state: String = str(event.get("state", "")).strip_edges().to_upper()
	if death_ref.is_empty():
		return _rejected("DEATH_REF_REQUIRED")
	if projected_state not in [STATE_DEFEATED, STATE_DEAD_AWAITING_RESPAWN]:
		return _rejected("INVALID_DEATH_PROJECTION_STATE")
	if not event.get("retention", {}) is Dictionary:
		return _rejected("DEATH_RETENTION_PROJECTION_REQUIRED")
	if not event.get("bag_drop", {}) is Dictionary:
		return _rejected("DEATH_BAG_DROP_PROJECTION_REQUIRED")
	var retention: Dictionary = event.get("retention")
	var retention_shape: Dictionary = _validate_retention_projection(retention)
	if retention_shape.get("status") != "PASS":
		return retention_shape
	var bag_drop: Dictionary = event.get("bag_drop")
	var bag_projection_result: Dictionary = {}
	if bool(bag_drop.get("dropped", false)):
		if not bag_drop.get("dropped_bag_snapshot", {}) is Dictionary:
			return _rejected("EXTERNAL_DROPPED_BAG_SNAPSHOT_REQUIRED")
		bag_projection_result = _dropped_bag_client.project_dropped_bag_snapshot(
			bag_drop.get("dropped_bag_snapshot") as Dictionary
		)
		if bag_projection_result.get("status") != "PASS":
			return bag_projection_result
	elif not str(bag_drop.get("reason", "")).to_upper() in ["NO_BAG_EQUIPPED", "NO_BAG"]:
		return _rejected("NO_BAG_DEATH_REASON_REQUIRED")

	_death_sequence = sequence
	_state = projected_state
	_death_projection = event.duplicate(true)
	_player.stop_local_prediction()
	_main_runtime.clear_current_target_projection("EXTERNAL_DEATH_PROJECTION")
	_set_world_input_blocked(true, projected_state)
	_hud.project_b10_external_state(projected_state, "Derrota confirmada externamente", true)
	var output := {
		"status": "PASS",
		"death_ref": death_ref,
		"state": _state,
		"bag_dropped": bool(bag_drop.get("dropped", false)),
		"bag_projection": bag_projection_result,
		"xp_retained_projection": bool(retention.get("xp_retained", false)),
		"equipment_retention_projection": true,
		"protected_items_projection": true,
		"death_decided_locally": false,
		"items_mutated_locally": false,
		"bag_drop_decided_locally": false,
		"authority": AUTHORITY,
	}
	death_projected.emit(output.duplicate(true))
	return output


func project_water_exhaustion(snapshot: Dictionary) -> Dictionary:
	var external: Dictionary = _validate_external(snapshot, "WATER_EXHAUSTION_SNAPSHOT")
	if external.get("status") != "PASS":
		return external
	var sequence_result: Dictionary = _sequence_from(snapshot, "exhaustion_sequence", "INVALID_EXHAUSTION_SEQUENCE")
	if sequence_result.get("status") != "PASS":
		return sequence_result
	var sequence: int = int(sequence_result.get("sequence"))
	if sequence <= _exhaustion_sequence:
		return _rejected("STALE_OR_DUPLICATE_EXHAUSTION_SNAPSHOT")
	var state_value: String = str(snapshot.get("state", "")).strip_edges().to_upper()
	if state_value not in ["STAMINA_ZERO_GRACE", "DEFEAT_ELIGIBLE", "RECOVERED"]:
		return _rejected("INVALID_WATER_EXHAUSTION_STATE")
	var grace_value: Variant = snapshot.get("grace_remaining_s", 0.0)
	if not _valid_nonnegative_number(grace_value):
		return _rejected("INVALID_EXTERNAL_GRACE_PROJECTION")
	_exhaustion_sequence = sequence
	_exhaustion_projection = snapshot.duplicate(true)
	if state_value != "RECOVERED":
		_hud.project_b10_external_state("WATER_EXHAUSTION", "Exaustão aquática projetada", true)
	return {
		"status": "PASS",
		"state": state_value,
		"grace_remaining_s": float(grace_value),
		"grace_timer_advanced_locally": false,
		"death_decided_locally": false,
		"authority": AUTHORITY,
	}


func request_respawn() -> Dictionary:
	if _state != STATE_DEAD_AWAITING_RESPAWN:
		return _rejected("RESPAWN_NOT_AVAILABLE_IN_CURRENT_EXTERNAL_STATE")
	var bridge: AndromedaRuntimeBridge = _bridge()
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	_request_serial += 1
	var request_ref: String = "B10-RESPAWN-%06d" % _request_serial
	var params := {
		"request_ref": request_ref,
		"death_ref": str(_death_projection.get("death_ref", "")),
		"client_presentation_only": true,
	}
	var built: Dictionary = bridge.build_command_envelope("REQUEST_RESPAWN", params)
	if built.get("status") != "PASS":
		return built
	var transport: Dictionary = {"status": "NOT_AVAILABLE", "reason": "BRIDGE_NOT_READY_NO_LIVE_BACKEND"}
	var submitted: bool = false
	if bridge.connection_state().get("state") == AndromedaRuntimeBridge.STATE_READY:
		transport = bridge.submit_command("REQUEST_RESPAWN", params)
		submitted = transport.get("status") == "PASS"
	_state = STATE_RESPAWN_PENDING
	_last_respawn_request = {
		"status": "PASS",
		"intent": "REQUEST_RESPAWN",
		"request_ref": request_ref,
		"intent_envelope": built,
		"transport_result": transport,
		"transport_submitted": submitted,
		"respawn_point_selected_locally": false,
		"player_repositioned_locally_without_authority": false,
		"authority": AUTHORITY,
	}
	_hud.present_b10_client_pending("RESPAWN_PENDING", "Aguardando snapshot de respawn")
	respawn_request_prepared.emit(_last_respawn_request.duplicate(true))
	return _last_respawn_request.duplicate(true)


func project_respawn_snapshot(snapshot: Dictionary) -> Dictionary:
	var external: Dictionary = _validate_external(snapshot, "RESPAWN_SNAPSHOT")
	if external.get("status") != "PASS":
		return external
	var sequence_result: Dictionary = _sequence_from(snapshot, "respawn_sequence", "INVALID_RESPAWN_SEQUENCE")
	if sequence_result.get("status") != "PASS":
		return sequence_result
	var sequence: int = int(sequence_result.get("sequence"))
	if sequence <= _respawn_sequence:
		return _rejected("STALE_OR_DUPLICATE_RESPAWN_SNAPSHOT")
	var request_ref: String = str(snapshot.get("request_ref", "")).strip_edges()
	if not _last_respawn_request.is_empty() and request_ref != str(_last_respawn_request.get("request_ref", "")):
		return _rejected("RESPAWN_REQUEST_REF_MISMATCH")
	var position_result: Dictionary = _position_from_projection(snapshot.get("position", {}))
	if position_result.get("status") != "PASS":
		return position_result
	if str(snapshot.get("state", "")).to_upper() not in [STATE_READY, STATE_ALIVE]:
		return _rejected("RESPAWN_READY_STATE_REQUIRED")
	_respawn_sequence = sequence
	_respawn_projection = snapshot.duplicate(true)
	_player.global_position = position_result.get("position", Vector3.ZERO)
	_player.stop_local_prediction()
	_camera_rig.set_follow_target(_player, true)
	_main_runtime.clear_current_target_projection("EXTERNAL_RESPAWN_PROJECTION")
	_state = STATE_READY
	_set_world_input_blocked(false, "RESPAWN_READY")
	_hud.project_b10_external_state("RESPAWNED", "Respawn confirmado externamente", false)
	var output := {
		"status": "PASS",
		"state": _state,
		"position": _player.global_position,
		"camera_follow_restored": _camera_rig.follow_target() == _player,
		"target_cleared": _main_runtime.selected_target_ref().is_empty(),
		"world_input_blocked": _world_input_blocked,
		"respawn_point_selected_locally": false,
		"inventory_mutated_locally": false,
		"authority": AUTHORITY,
	}
	respawn_projected.emit(output.duplicate(true))
	return output


func project_restored_death_recovery(snapshot: Dictionary) -> Dictionary:
	var external: Dictionary = _validate_external(snapshot, "RESTORED_DEATH_RECOVERY")
	if external.get("status") != "PASS":
		return external
	var sequence_result: Dictionary = _sequence_from(snapshot, "restore_sequence", "INVALID_DEATH_RECOVERY_RESTORE_SEQUENCE")
	if sequence_result.get("status") != "PASS":
		return sequence_result
	var sequence: int = int(sequence_result.get("sequence"))
	if sequence <= _restore_sequence:
		return _rejected("STALE_OR_DUPLICATE_DEATH_RECOVERY_RESTORE")
	var restored_state: String = str(snapshot.get("state", "")).to_upper()
	if restored_state not in [STATE_ALIVE, STATE_READY, STATE_DEFEATED, STATE_DEAD_AWAITING_RESPAWN]:
		return _rejected("INVALID_RESTORED_DEATH_RECOVERY_STATE")
	if not snapshot.get("retention_projection", {}) is Dictionary:
		return _rejected("RESTORED_RETENTION_PROJECTION_REQUIRED")
	_restore_sequence = sequence
	_recovery_projection = snapshot.duplicate(true)
	_state = restored_state
	var blocked: bool = restored_state in [STATE_DEFEATED, STATE_DEAD_AWAITING_RESPAWN]
	_set_world_input_blocked(blocked, "RESTORED_DEATH_RECOVERY")
	return {
		"status": "PASS",
		"state": _state,
		"world_input_blocked": _world_input_blocked,
		"death_recovery_reconstructed_from_external_snapshot": true,
		"local_policy_applied": false,
		"authority": AUTHORITY,
	}


func set_restore_input_blocked(blocked: bool, reason: String) -> void:
	_set_world_input_blocked(blocked, reason)


func complete_restore_input_gate() -> void:
	var must_remain_blocked: bool = _state in [STATE_DEFEATED, STATE_DEAD_AWAITING_RESPAWN, STATE_RESPAWN_PENDING]
	_set_world_input_blocked(must_remain_blocked, "RESTORED_DEATH_STATE" if must_remain_blocked else "RESTORE_READY")


func world_input_blocked() -> bool:
	return _world_input_blocked


func state() -> String:
	return _state


func death_projection() -> Dictionary:
	return _death_projection.duplicate(true)


func recovery_projection() -> Dictionary:
	return _recovery_projection.duplicate(true)


func exhaustion_projection() -> Dictionary:
	return _exhaustion_projection.duplicate(true)


func last_respawn_request() -> Dictionary:
	return _last_respawn_request.duplicate(true)


func contract_snapshot() -> Dictionary:
	return {
		"death_states": [STATE_DEFEATED, STATE_DEAD_AWAITING_RESPAWN],
		"equipped_weapon_retention_count": 2,
		"equipped_armor_retained_projection": true,
		"equipped_clothes_retained_projection": true,
		"protected_critical_items_projection": true,
		"bag_is_single_container": true,
		"no_bag_fabrication": true,
		"safe_respawn_point_authority": false,
		"water_grace_authority": false,
		"death_authority": false,
		"inventory_authority": false,
		"bag_drop_authority": false,
		"backend_substitute": false,
		"authority": AUTHORITY,
	}


func _validate_retention_projection(retention: Dictionary) -> Dictionary:
	if retention.get("xp_retained") != true:
		return _rejected("XP_RETENTION_PROJECTION_REQUIRED")
	if not retention.get("quick_slots", []) is Array or (retention.get("quick_slots") as Array).size() != 2:
		return _rejected("EXACTLY_TWO_RETAINED_QUICK_SLOTS_REQUIRED")
	var active_slot_value: Variant = retention.get("active_slot")
	if not _is_integral_wire_number(active_slot_value) or int(active_slot_value) not in [1, 2]:
		return _rejected("ONE_ACTIVE_RETAINED_WEAPON_REQUIRED")
	if not retention.get("equipped_armor_refs", []) is Array:
		return _rejected("INVALID_EQUIPPED_ARMOR_RETENTION")
	if not retention.get("equipped_clothes_refs", []) is Array:
		return _rejected("INVALID_EQUIPPED_CLOTHES_RETENTION")
	if not retention.get("protected_critical_refs", []) is Array:
		return _rejected("INVALID_PROTECTED_CRITICAL_RETENTION")
	return {"status": "PASS", "authority": AUTHORITY}


func _is_integral_wire_number(value: Variant) -> bool:
	if typeof(value) == TYPE_BOOL or typeof(value) not in [TYPE_INT, TYPE_FLOAT]:
		return false
	var numeric_value: float = float(value)
	return is_finite(numeric_value) and numeric_value == floor(numeric_value)


func _set_world_input_blocked(blocked: bool, reason: String) -> void:
	if _world_input_blocked == blocked and _block_reason == reason:
		return
	_world_input_blocked = blocked
	_block_reason = reason
	input_block_changed.emit(_world_input_blocked, _block_reason)


func _position_from_projection(value: Variant) -> Dictionary:
	if not value is Dictionary:
		return _rejected("INVALID_EXTERNAL_RESPAWN_POSITION")
	var position_data: Dictionary = value
	for key: String in ["iso_x_m", "iso_y_m", "altitude_m"]:
		var component: Variant = position_data.get(key)
		if typeof(component) not in [TYPE_INT, TYPE_FLOAT] or typeof(component) == TYPE_BOOL or not is_finite(float(component)):
			return _rejected("INVALID_EXTERNAL_RESPAWN_POSITION")
	return {
		"status": "PASS",
		"position": Vector3(
			float(position_data.get("iso_x_m")),
			float(position_data.get("altitude_m")),
			float(position_data.get("iso_y_m"))
		),
		"authority": AUTHORITY,
	}


func _sequence_from(payload: Dictionary, key: String, reason: String) -> Dictionary:
	var value: Variant = payload.get(key)
	if typeof(value) != TYPE_INT or typeof(value) == TYPE_BOOL or int(value) < 0:
		return _rejected(reason)
	return {"status": "PASS", "sequence": int(value), "authority": AUTHORITY}


func _validate_external(payload: Dictionary, label: String) -> Dictionary:
	if payload.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_%s" % label)
	var session: AndromedaClientSession = _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	if str(payload.get("session_ref", "")).strip_edges() != session.session_ref():
		return _rejected("SESSION_MISMATCH")
	return {"status": "PASS", "authority": AUTHORITY}


func _valid_nonnegative_number(value: Variant) -> bool:
	return typeof(value) in [TYPE_INT, TYPE_FLOAT] and typeof(value) != TYPE_BOOL and is_finite(float(value)) and float(value) >= 0.0


func _on_bridge_command_result_received(result: Dictionary) -> void:
	var command: String = str(result.get("command", "")).strip_edges().to_upper()
	if command == "REPORT_WATER_EXHAUSTION":
		var exhaustion_value: Variant = result.get("exhaustion_snapshot", {})
		if exhaustion_value is Dictionary and not (exhaustion_value as Dictionary).is_empty():
			project_water_exhaustion(exhaustion_value as Dictionary)
		var death_value: Variant = result.get("death_event", {})
		if death_value is Dictionary and not (death_value as Dictionary).is_empty():
			project_death_event(death_value as Dictionary)
	elif command == "REQUEST_RESPAWN":
		var respawn_value: Variant = result.get("respawn_snapshot", {})
		if respawn_value is Dictionary and not (respawn_value as Dictionary).is_empty():
			project_respawn_snapshot(respawn_value as Dictionary)


func _on_session_bound(_session_ref: String, _session_epoch: int) -> void:
	_death_sequence = -1
	_respawn_sequence = -1
	_exhaustion_sequence = -1
	_restore_sequence = -1
	_last_respawn_request.clear()


func _on_session_revoked(_previous_session_ref: String, _session_epoch: int) -> void:
	_player.stop_local_prediction()
	_set_world_input_blocked(true, "SESSION_REVOKED_RESYNC_REQUIRED")


func _bridge() -> AndromedaRuntimeBridge:
	return get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge


func _session() -> AndromedaClientSession:
	return get_node_or_null("/root/ClientSession") as AndromedaClientSession


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
