extends Node
class_name AndromedaMovementAuthorityClient

## Single-player Stage17 movement orchestration.
## Godot owns input, NavigationAgent3D, physics and presentation. The backend owns
## iso position, collision acceptance, movement distance, stamina, chunk and time.

signal movement_submitted(evidence: Dictionary)
signal movement_accepted(evidence: Dictionary)
signal movement_rejected(evidence: Dictionary)
signal movement_result_ignored_as_stale(evidence: Dictionary)
signal movement_reconciled(evidence: Dictionary)
signal reconnect_reconciled(evidence: Dictionary)

const AUTHORITY := "STAGE17_GODOT_MOVEMENT_CLIENT_ORCHESTRATION_ONLY"
const COMMAND := "MOVE_TO_POINT"
const REQUEST_STEP_BUDGET_S := 10.0

var _player: AndromedaPlayerController
var _mapper: AndromedaAuthoritySpaceMapper
var _submission_serial: int = 0
var _latest_submission_serial: int = -1
var _latest_command_ref: String = ""
var _pending_by_ref: Dictionary = {}
var _last_authority_position: Dictionary = {}
var _last_snapshot_sequence: int = -1
var _reconnect_waiting_for_snapshot: bool = false
var _metrics := {
	"submitted": 0,
	"accepted": 0,
	"rejected": 0,
	"stale_results_ignored": 0,
	"reconnects": 0,
	"reconciliations": 0,
	"max_reconciliation_error_m": 0.0,
}


func bind_runtime(player: AndromedaPlayerController, mapper: AndromedaAuthoritySpaceMapper) -> void:
	_player = player
	_mapper = mapper
	var bridge: AndromedaRuntimeBridge = _bridge()
	if bridge == null:
		return
	if not bridge.snapshot_applied.is_connected(_on_snapshot_applied):
		bridge.snapshot_applied.connect(_on_snapshot_applied)
	if not bridge.command_result_received.is_connected(_on_command_result_received):
		bridge.command_result_received.connect(_on_command_result_received)
	if not bridge.connection_state_changed.is_connected(_on_connection_state_changed):
		bridge.connection_state_changed.connect(_on_connection_state_changed)


func submit_local_destination(local_destination: Vector3, mode: String = "WALK") -> Dictionary:
	if _player == null or _mapper == null:
		return _rejected("MOVEMENT_CLIENT_NOT_BOUND")
	if not _valid_vector(local_destination):
		return _rejected("INVALID_LOCAL_DESTINATION")
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge: AndromedaRuntimeBridge = _bridge()
	# Historical local navigation gates instantiate Player without an active session.
	# That remains a presentation-only path and never creates an authority command.
	if session == null or not session.has_active_session():
		return {
			"status": "PASS",
			"submitted": false,
			"local_only": true,
			"reason": "NO_ACTIVE_SESSION_PRESENTATION_ONLY",
			"authority": AUTHORITY,
		}
	if bridge == null or bridge.connection_state().get("authority_session_bound") != true:
		return _rejected("AUTHORITY_MOVEMENT_NOT_READY")
	# SYNCING is a normal short-lived state after every accepted/rejected command
	# while the bridge fetches its follow-up snapshot.  Once the session is bound
	# and a real anchor exists, a new explicit destination may safely queue there.
	# Only genuine connectivity loss blocks new movement intent.
	var bridge_state: String = str(bridge.connection_state().get("state", ""))
	if bridge_state in [
		AndromedaRuntimeBridge.STATE_DISCONNECTED,
		AndromedaRuntimeBridge.STATE_CONNECTING,
		AndromedaRuntimeBridge.STATE_RECONNECT_WAIT,
	]:
		return _rejected("AUTHORITY_MOVEMENT_NOT_READY")
	if not _mapper.is_anchored():
		return _rejected("AUTHORITY_SPACE_ANCHOR_NOT_READY")
	var mapped: Dictionary = _mapper.local_to_authority(local_destination)
	if mapped.get("status") != "PASS":
		return mapped
	var params := {
		"iso_x_m": float(mapped.get("iso_x_m")),
		"iso_y_m": float(mapped.get("iso_y_m")),
		"duration_s": REQUEST_STEP_BUDGET_S,
		"mode": mode.strip_edges().to_upper(),
	}
	var built: Dictionary = bridge.build_command_envelope(COMMAND, params)
	if built.get("status") != "PASS":
		return built
	var envelope: Dictionary = built.get("envelope", {}) as Dictionary
	var command_ref: String = str(envelope.get("command_ref", ""))
	_submission_serial += 1
	_latest_submission_serial = _submission_serial
	_latest_command_ref = command_ref
	var pending := {
		"serial": _submission_serial,
		"command_ref": command_ref,
		"local_destination": local_destination,
		"mapped_authority_destination": {
			"iso_x_m": params["iso_x_m"],
			"iso_y_m": params["iso_y_m"],
		},
		"params": params.duplicate(true),
	}
	_pending_by_ref[command_ref] = pending
	var submitted: Dictionary = bridge.submit_command(COMMAND, params, command_ref)
	if submitted.get("status") != "PASS":
		_pending_by_ref.erase(command_ref)
		return submitted
	_metrics["submitted"] = int(_metrics["submitted"]) + 1
	var evidence: Dictionary = pending.duplicate(true)
	evidence.merge({"status": "PASS", "submitted": true, "authority": AUTHORITY}, true)
	movement_submitted.emit(evidence.duplicate(true))
	return evidence


func metrics_snapshot() -> Dictionary:
	var result: Dictionary = _metrics.duplicate(true)
	result.merge({
		"latest_command_ref": _latest_command_ref,
		"latest_submission_serial": _latest_submission_serial,
		"pending_count": _pending_by_ref.size(),
		"last_authority_position": _last_authority_position.duplicate(true),
		"last_snapshot_sequence": _last_snapshot_sequence,
		"request_step_budget_s": REQUEST_STEP_BUDGET_S,
		"command_per_explicit_destination": 1,
		"gameplay_authority": false,
		"authority": AUTHORITY,
	}, true)
	return result


func pending_command_refs() -> Array[String]:
	var refs: Array[String] = []
	for value: Variant in _pending_by_ref.keys():
		refs.append(str(value))
	return refs


func _on_snapshot_applied(snapshot: Dictionary) -> void:
	if _player == null or _mapper == null:
		return
	var anchor_result: Dictionary = _mapper.establish_from_snapshot(snapshot, _player.global_position)
	if anchor_result.get("status") != "PASS":
		return
	var transform: Dictionary = snapshot.get("transform", {}) as Dictionary
	_last_authority_position = {
		"iso_x_m": float(transform.get("iso_x_m")),
		"iso_y_m": float(transform.get("iso_y_m")),
		"altitude_m": float(transform.get("altitude_m", 0.0)),
	}
	_last_snapshot_sequence = int(snapshot.get("snapshot_sequence", _last_snapshot_sequence))
	if not _pending_by_ref.is_empty():
		return
	var local_result: Dictionary = _mapper.authority_to_local(_last_authority_position)
	if local_result.get("status") != "PASS":
		return
	var evidence: Dictionary = _player.reconcile_authoritative_position(
		local_result.get("local_position", _player.global_position),
		"RECONNECT_SNAPSHOT" if _reconnect_waiting_for_snapshot else "AUTHORITATIVE_SNAPSHOT",
		""
	)
	_record_reconciliation(evidence)
	if _reconnect_waiting_for_snapshot:
		_reconnect_waiting_for_snapshot = false
		reconnect_reconciled.emit(evidence.duplicate(true))


func _on_command_result_received(result: Dictionary) -> void:
	if str(result.get("command", "")).strip_edges().to_upper() != COMMAND:
		return
	var command_ref: String = str(result.get("command_ref", ""))
	if not _pending_by_ref.has(command_ref):
		return
	var pending: Dictionary = _pending_by_ref[command_ref] as Dictionary
	_pending_by_ref.erase(command_ref)
	var serial: int = int(pending.get("serial", -1))
	if serial < _latest_submission_serial or command_ref != _latest_command_ref:
		_metrics["stale_results_ignored"] = int(_metrics["stale_results_ignored"]) + 1
		var stale := {
			"status": "PASS",
			"ignored": true,
			"command_ref": command_ref,
			"serial": serial,
			"latest_command_ref": _latest_command_ref,
			"latest_serial": _latest_submission_serial,
			"authority": AUTHORITY,
		}
		movement_result_ignored_as_stale.emit(stale.duplicate(true))
		return
	if result.get("status") != "PASS":
		_metrics["rejected"] = int(_metrics["rejected"]) + 1
		var rejection := pending.duplicate(true)
		rejection.merge({
			"status": "REJECTED",
			"reason": str(result.get("reason", "MOVEMENT_REJECTED_BY_AUTHORITY")),
			"authority_result": result.duplicate(true),
			"authority": AUTHORITY,
		}, true)
		_player.stop_local_prediction()
		if not _last_authority_position.is_empty():
			var rollback_local: Dictionary = _mapper.authority_to_local(_last_authority_position)
			if rollback_local.get("status") == "PASS":
				var rollback: Dictionary = _player.reconcile_authoritative_position(
					rollback_local.get("local_position", _player.global_position),
					"AUTHORITY_REJECTION",
					command_ref
				)
				_record_reconciliation(rollback)
				rejection["reconciliation"] = rollback
		movement_rejected.emit(rejection.duplicate(true))
		return
	if not _valid_number(result.get("iso_x_m")) or not _valid_number(result.get("iso_y_m")):
		return
	_last_authority_position = {
		"iso_x_m": float(result.get("iso_x_m")),
		"iso_y_m": float(result.get("iso_y_m")),
		"altitude_m": float(result.get("altitude_m", _last_authority_position.get("altitude_m", 0.0))),
	}
	var local_result: Dictionary = _mapper.authority_to_local(_last_authority_position)
	if local_result.get("status") != "PASS":
		return
	var reconciliation: Dictionary = _player.reconcile_authoritative_position(
		local_result.get("local_position", _player.global_position),
		"AUTHORITY_COMMAND_RESULT",
		command_ref
	)
	_record_reconciliation(reconciliation)
	_metrics["accepted"] = int(_metrics["accepted"]) + 1
	var accepted: Dictionary = pending.duplicate(true)
	accepted.merge({
		"status": "PASS",
		"authority_result": result.duplicate(true),
		"authority_result_position": _last_authority_position.duplicate(true),
		"reprojected_local_position": local_result.get("local_position"),
		"reconciliation": reconciliation,
		"authority": AUTHORITY,
	}, true)
	movement_accepted.emit(accepted.duplicate(true))
	movement_reconciled.emit(accepted.duplicate(true))


func _on_connection_state_changed(state: String, _detail: String) -> void:
	if state != AndromedaRuntimeBridge.STATE_RECONNECT_WAIT and state != AndromedaRuntimeBridge.STATE_DISCONNECTED:
		return
	if _player != null:
		_player.stop_local_prediction()
	_pending_by_ref.clear()
	_latest_command_ref = ""
	_reconnect_waiting_for_snapshot = true
	_metrics["reconnects"] = int(_metrics["reconnects"]) + 1


func _record_reconciliation(evidence: Dictionary) -> void:
	if evidence.get("status") != "PASS":
		return
	_metrics["reconciliations"] = int(_metrics["reconciliations"]) + 1
	_metrics["max_reconciliation_error_m"] = maxf(
		float(_metrics["max_reconciliation_error_m"]),
		float(evidence.get("error_distance_m", 0.0))
	)


func _bridge() -> AndromedaRuntimeBridge:
	return get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge


func _valid_vector(value: Vector3) -> bool:
	return is_finite(value.x) and is_finite(value.y) and is_finite(value.z)


func _valid_number(value: Variant) -> bool:
	return (typeof(value) == TYPE_INT or typeof(value) == TYPE_FLOAT) and is_finite(float(value))


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
