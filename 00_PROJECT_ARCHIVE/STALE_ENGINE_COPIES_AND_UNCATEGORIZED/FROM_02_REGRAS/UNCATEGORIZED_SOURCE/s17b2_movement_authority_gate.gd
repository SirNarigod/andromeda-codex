extends Node

## S17-B2 live click-to-move orchestration proof. All destinations enter through
## Player.request_move(), exactly the API used by normal left/right ground click.

const SESSION_REF := "GODOT-STAGE17-B2-MOVEMENT-V010"
const WAIT_TIMEOUT_S := 75.0
const PRESENTATION_TEST_ACTOR_CLEARANCE_M := 1.25

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _checks: int = 0
var _failures: Array[String] = []
var _binds: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []
var _accepted: Array[Dictionary] = []
var _rejected: Array[Dictionary] = []
var _stale: Array[Dictionary] = []
var _reconnects: Array[Dictionary] = []
var _evidence: Array[Dictionary] = []
var _raw_command_results: Array[Dictionary] = []


func _ready() -> void:
	await _run()


func _run() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_check("RUNTIME_PRESENT", main != null and session != null and bridge != null)
	if main == null or session == null or bridge == null:
		await _finish()
		return
	main.movement_authority_client.movement_accepted.connect(func(value: Dictionary) -> void: _accepted.append(value.duplicate(true)))
	main.movement_authority_client.movement_rejected.connect(func(value: Dictionary) -> void: _rejected.append(value.duplicate(true)))
	main.movement_authority_client.movement_result_ignored_as_stale.connect(func(value: Dictionary) -> void: _stale.append(value.duplicate(true)))
	main.movement_authority_client.reconnect_reconciled.connect(func(value: Dictionary) -> void: _reconnects.append(value.duplicate(true)))
	bridge.authority_session_bound.connect(func(value: Dictionary) -> void: _binds.append(value.duplicate(true)))
	bridge.snapshot_applied.connect(func(value: Dictionary) -> void: _snapshots.append(value.duplicate(true)))
	bridge.command_result_received.connect(func(value: Dictionary) -> void: _raw_command_results.append(value.duplicate(true)))
	# Main's greybox Player starts intersecting the terrain collider by design and
	# CharacterBody resolves upward on the first physics ticks. Normal manual play
	# naturally finishes this before authority READY; the gate must do the same so
	# it measures movement rather than spawn-collider settlement.
	var spawn_settled: bool = false
	for settle_frame: int in range(180):
		await get_tree().physics_frame
		if settle_frame >= 10 and main.player.is_on_floor() and absf(main.player.velocity.y) <= 0.01:
			spawn_settled = true
			break
	_check("PLAYER_SPAWN_PHYSICS_SETTLED", spawn_settled, str(main.player.global_position))
	if session.has_active_session():
		session.revoke_session()
	_check("LOCAL_SESSION_BOUND", session.bind_session(SESSION_REF).get("status") == "PASS")
	_check("AUTHORITY_BIND_STARTED", bridge.bind_authoritative_session().get("status") == "PASS")
	if not await _wait_for_size(_binds, 1) or not await _wait_for_size(_snapshots, 1):
		_failures.append("LIVE_STARTUP_TIMEOUT")
		await _finish()
		return
	await get_tree().physics_frame
	await get_tree().physics_frame
	_check("BRIDGE_READY", bridge.connection_state().get("state") == AndromedaRuntimeBridge.STATE_READY)
	_check("MAPPER_ANCHORED", main.authority_space_mapper.is_anchored())
	var initial_authority: Dictionary = _snapshot_position(_snapshots.back())
	var initial_local: Vector3 = main.player.global_position

	# C0 projects real combat actors into this greybox. Select deterministic local
	# presentation points whose path does not cross those actor colliders; B2 tests
	# movement mapping/reconciliation, not collision with interaction targets.
	var d1: Vector3 = _validated_clear_offset([
		Vector3(0.0, 0.0, -1.25), Vector3(0.0, 0.0, 1.25),
		Vector3(-1.25, 0.0, 0.0), Vector3(1.25, 0.0, 0.0),
	])
	_check("SHORT_DESTINATION_VALID", d1 != Vector3.INF)
	if d1 == Vector3.INF:
		await _finish()
		return
	var first: Dictionary = await _execute_destination("D1_SHORT", d1)
	var d2: Vector3 = _validated_clear_offset([
		Vector3(0.0, 0.0, -2.0), Vector3(-2.0, 0.0, 0.0),
		Vector3(2.0, 0.0, 0.0), Vector3(0.0, 0.0, 2.0),
	])
	_check("MEDIUM_DESTINATION_VALID", d2 != Vector3.INF)
	if d2 == Vector3.INF:
		await _finish()
		return
	var second: Dictionary = await _execute_destination("D2_MEDIUM", d2)
	var d3: Vector3 = _validated_clear_offset([
		Vector3(0.0, 0.0, 1.5), Vector3(-1.0, 0.0, 1.5),
		Vector3(1.0, 0.0, 1.5), Vector3(0.0, 0.0, -1.5),
	])
	_check("OPPOSITE_DESTINATION_VALID", d3 != Vector3.INF)
	if d3 == Vector3.INF:
		await _finish()
		return
	var third: Dictionary = await _execute_destination("D3_OPPOSITE", d3)
	_check("AUTHORITY_P1_DIFFERS_P0", _authority_distance(initial_authority, first.get("authority_result_position", {})) > 0.0)
	_check("AUTHORITY_P2_DIFFERS_P1", _authority_distance(first.get("authority_result_position", {}), second.get("authority_result_position", {})) > 0.0)
	_check("AUTHORITY_P3_DIFFERS_P2", _authority_distance(second.get("authority_result_position", {}), third.get("authority_result_position", {})) > 0.0)

	# Rapid replacement: bridge serializes transport, so A returns after B has
	# become latest. A must be ignored and must not replace B's local destination.
	var stale_before: int = _stale.size()
	var accepted_before: int = _accepted.size()
	var rapid_a: Vector3 = _validated_clear_offset([
		Vector3(1.0, 0.0, 1.0), Vector3(-1.0, 0.0, 1.0),
		Vector3(1.0, 0.0, -1.0), Vector3(-1.0, 0.0, -1.0),
	])
	var rapid_b: Vector3 = _validated_clear_offset([
		Vector3(2.0, 0.0, -0.5), Vector3(-2.0, 0.0, -0.5),
		Vector3(2.0, 0.0, 0.5), Vector3(-2.0, 0.0, 0.5),
	])
	var submit_a: Dictionary = main.player.request_move(rapid_a)
	var submit_b: Dictionary = main.player.request_move(rapid_b)
	_check("RAPID_A_SUBMITTED", submit_a.get("status") == "PASS" and submit_a.get("transport_submitted") == true)
	_check("RAPID_B_SUBMITTED", submit_b.get("status") == "PASS" and submit_b.get("transport_submitted") == true)
	_check("RAPID_DESTINATIONS_USE_DIFFERENT_COMMAND_REFS", _command_ref(submit_a) != _command_ref(submit_b))
	_check("RAPID_LATEST_DESTINATION_IS_B", main.player.requested_destination().distance_to(rapid_b) <= 0.01)
	_check("RAPID_STALE_A_SIGNAL", await _wait_for_size(_stale, stale_before + 1))
	_check("RAPID_B_ACCEPTED", await _wait_for_size(_accepted, accepted_before + 1))
	var rapid_accept: Dictionary = _accepted.back()
	_check("RAPID_ACCEPT_IS_B", str(rapid_accept.get("command_ref")) == _command_ref(submit_b))
	_check("RAPID_STALE_DID_NOT_RESTORE_A", main.player.requested_destination().distance_to(rapid_a) > 0.01)
	await _wait_for_visual_position(rapid_accept.get("reprojected_local_position", rapid_b), 10.0)
	_evidence.append(_compact_evidence("RAPID_B", rapid_accept))

	# A deliberately invalid presentation mode reaches the real authority and
	# proves rejection cancellation/rollback; it is not a debug teleport.
	var rejected_before: int = _rejected.size()
	# Current position is always the least ambiguous valid navigation destination;
	# only the mode is deliberately invalid, so the rejection source is authority
	# policy rather than local path validation.
	var rejection_target: Vector3 = _validated_offset(Vector3.ZERO)
	_check("REJECTION_DESTINATION_LOCALLY_VALID", rejection_target != Vector3.INF)
	var rejection_submit: Dictionary = main.player.request_move(rejection_target, "FLY")
	_check("REJECTION_REQUEST_SUBMITTED", rejection_submit.get("status") == "PASS" and rejection_submit.get("transport_submitted") == true)
	var rejection_command_ref: String = _command_ref(rejection_submit)
	var raw_rejection_arrived: bool = await _wait_for_raw_command_ref(rejection_command_ref)
	_check("RAW_REJECTION_RESULT_RECEIVED", raw_rejection_arrived, JSON.stringify(rejection_submit))
	var raw_rejection: Dictionary = _raw_result_for_ref(rejection_command_ref)
	if raw_rejection_arrived:
		_check("RAW_REJECTION_IS_AUTHORITY_REJECTION", raw_rejection.get("status") == "REJECTED", JSON.stringify(raw_rejection))
	var rejection_arrived: bool = await _wait_for_size(_rejected, rejected_before + 1)
	_check("REAL_REJECTION_RECEIVED", rejection_arrived, JSON.stringify(raw_rejection if raw_rejection_arrived else rejection_submit))
	if not rejection_arrived:
		await _finish({"destinations": _evidence, "metrics": main.movement_authority_client.metrics_snapshot(), "rejection_submit": rejection_submit})
		return
	var rejection: Dictionary = _rejected.back()
	_check("REJECTION_MATCHES_LATEST_COMMAND", str(rejection.get("command_ref")) == _command_ref(rejection_submit))
	_check("REJECTION_CANCELLED_LOCAL_TARGET", not main.player.has_destination() or main.player.reconciliation_active())
	_check("REJECTION_HAS_NO_TELEPORT", str(rejection.get("reconciliation", {}).get("action", "")) != "TELEPORT")

	# Existing bridge owns exponential reconnect. The movement client observes it,
	# stops presentation, sends no duplicate, and accepts the fresh snapshot.
	var submitted_before_reconnect: int = int(main.movement_authority_client.metrics_snapshot().get("submitted"))
	var reconnect_before: int = _reconnects.size()
	_check("CONTROLLED_TRANSPORT_ERROR_RECORDED", bridge.record_transport_error("S17_B2_CONTROLLED_RECONNECT").get("status") == "PASS")
	_check("RECONNECT_STATE_ENTERED", bridge.connection_state().get("state") == AndromedaRuntimeBridge.STATE_RECONNECT_WAIT)
	_check("RECONNECT_SNAPSHOT_RECONCILED", await _wait_for_size(_reconnects, reconnect_before + 1))
	_check(
		"RECONNECT_RETURNS_AUTHORITY_AVAILABLE",
		bridge.connection_state().get("authority_session_bound") == true
		and bridge.connection_state().get("state") in [AndromedaRuntimeBridge.STATE_READY, AndromedaRuntimeBridge.STATE_SYNCING],
		JSON.stringify(bridge.connection_state())
	)
	_check("RECONNECT_DID_NOT_RESUBMIT_MOVEMENT", int(main.movement_authority_client.metrics_snapshot().get("submitted")) == submitted_before_reconnect)
	_check("RECONNECT_PENDING_EMPTY", main.movement_authority_client.pending_command_refs().is_empty())

	# Replay the exact D1 envelope after later destinations. The persisted journal
	# must return the original result without moving the current world backwards.
	var replay_ref: String = str(first.get("command_ref", ""))
	var replay_params: Dictionary = first.get("params", {}).duplicate(true)
	var replay_results_before: int = _raw_result_count(replay_ref)
	var replay_snapshots_before: int = _snapshots.size()
	var authority_before_replay: Dictionary = _snapshot_position(_snapshots.back())
	var movement_submits_before_replay: int = int(main.movement_authority_client.metrics_snapshot().get("submitted"))
	var replay_submit: Dictionary = bridge.submit_command("MOVE_TO_POINT", replay_params, replay_ref)
	_check("IDEMPOTENT_REPLAY_QUEUED", replay_submit.get("status") == "PASS")
	_check("IDEMPOTENT_REPLAY_RESULT_RECEIVED", await _wait_for_raw_ref_count(replay_ref, replay_results_before + 1))
	var replay_result: Dictionary = _last_raw_result_for_ref(replay_ref)
	_check("IDEMPOTENT_REPLAY_IDENTIFIED", replay_result.get("idempotent_replay") == true, JSON.stringify(replay_result))
	_check("IDEMPOTENT_REPLAY_SUPPRESSED", replay_result.get("replay_suppressed") == true, JSON.stringify(replay_result))
	_check("IDEMPOTENT_REPLAY_SNAPSHOT_RECEIVED", await _wait_for_size(_snapshots, replay_snapshots_before + 1))
	_check("IDEMPOTENT_REPLAY_DID_NOT_MOVE_WORLD", _authority_distance(authority_before_replay, _snapshot_position(_snapshots.back())) <= 0.000001)
	_check("IDEMPOTENT_REPLAY_NOT_COUNTED_AS_NEW_DESTINATION", int(main.movement_authority_client.metrics_snapshot().get("submitted")) == movement_submits_before_replay)

	var metrics: Dictionary = main.movement_authority_client.metrics_snapshot()
	_check("ONE_COMMAND_PER_EXPLICIT_DESTINATION", int(metrics.get("command_per_explicit_destination")) == 1)
	_check("NO_PER_FRAME_COMMAND_SPAM", int(metrics.get("submitted")) == 6, JSON.stringify(metrics))
	_check("STALE_RESULT_COUNTED", int(metrics.get("stale_results_ignored")) >= 1)
	_check("REJECTION_COUNTED", int(metrics.get("rejected")) >= 1)
	_check("RECONNECT_COUNTED", int(metrics.get("reconnects")) >= 1)
	_check("PRESENTATION_TOLERANCE_IS_NAV_ARRIVAL", is_equal_approx(main.player.presentation_reconciliation_tolerance_m(), main.player.arrival_distance_m))
	_check("NAVIGATION_REMAINS_GODOT_PRESENTATION", AndromedaPlayerController.AUTHORITY == "GODOT_NAVIGATION_PRESENTATION_ONLY")
	_check("MOVEMENT_CLIENT_HAS_NO_GAMEPLAY_AUTHORITY", AndromedaMovementAuthorityClient.AUTHORITY == "STAGE17_GODOT_MOVEMENT_CLIENT_ORCHESTRATION_ONLY")
	await _finish({"destinations": _evidence, "metrics": metrics, "initial_local": _vector_json(initial_local), "initial_authority": initial_authority})


func _execute_destination(label: String, destination: Vector3) -> Dictionary:
	var before: int = _accepted.size()
	var request: Dictionary = main.player.request_move(destination)
	_check("%s_REQUEST_PASS" % label, request.get("status") == "PASS", JSON.stringify(request))
	_check("%s_REAL_COMMAND_SUBMITTED" % label, request.get("transport_submitted") == true, JSON.stringify(request))
	_check("%s_COMMAND_REF_PRESENT" % label, not _command_ref(request).is_empty())
	if not await _wait_for_size(_accepted, before + 1):
		_failures.append("%s_AUTHORITY_RESULT_TIMEOUT" % label)
		return {}
	var accepted: Dictionary = _accepted.back()
	_check("%s_COMMAND_REF_CORRELATED" % label, str(accepted.get("command_ref")) == _command_ref(request))
	_check("%s_CORE_DELEGATED" % label, str(accepted.get("authority_result", {}).get("delegated_core_command", "")) == "MOVE_VECTOR")
	_check("%s_AUTHORITY_POSITION_PRESENT" % label, _valid_authority(accepted.get("authority_result_position", {})))
	var reprojection: Vector3 = accepted.get("reprojected_local_position", Vector3.INF)
	var reached: bool = await _wait_for_visual_position(reprojection, 10.0)
	var error: float = Vector2(main.player.global_position.x, main.player.global_position.z).distance_to(Vector2(reprojection.x, reprojection.z))
	_check("%s_VISUAL_RECONCILED" % label, reached, str(error))
	_check("%s_ERROR_WITHIN_TOLERANCE" % label, error <= main.player.presentation_reconciliation_tolerance_m(), str(error))
	var evidence: Dictionary = _compact_evidence(label, accepted)
	evidence["snapshot_authority_position"] = _snapshot_position(_snapshots.back())
	evidence["visual_player_position"] = _vector_json(main.player.global_position)
	evidence["error_distance_m"] = error
	_evidence.append(evidence)
	return accepted


func _validated_offset(offset: Vector3) -> Vector3:
	var desired: Vector3 = main.player.global_position + offset
	var validation: Dictionary = main.player.validate_destination(desired)
	if validation.get("status") != "PASS":
		return Vector3.INF
	return validation.get("navigation_destination", Vector3.INF)


func _validated_clear_offset(offsets: Array) -> Vector3:
	for value: Variant in offsets:
		if not value is Vector3:
			continue
		var candidate: Vector3 = _validated_offset(value)
		if candidate == Vector3.INF:
			continue
		if _segment_clears_bound_combat_actors(main.player.global_position, candidate):
			return candidate
	return Vector3.INF


func _segment_clears_bound_combat_actors(start: Vector3, finish: Vector3) -> bool:
	for actor: AndromedaInteractionTarget in [main.combat_enemy_common, main.combat_enemy_alpha]:
		if actor == null or actor.target_ref.is_empty():
			continue
		var binding: Dictionary = main.interaction_spatial_binding_registry.binding_for_ref(actor.target_ref)
		if binding.get("status") != "PASS" or not binding.get("local_position") is Vector3:
			continue
		var point: Vector3 = binding.get("local_position")
		if _point_to_segment_distance_xz(point, start, finish) < PRESENTATION_TEST_ACTOR_CLEARANCE_M:
			return false
	return true


func _point_to_segment_distance_xz(point: Vector3, start: Vector3, finish: Vector3) -> float:
	var a := Vector2(start.x, start.z)
	var b := Vector2(finish.x, finish.z)
	var p := Vector2(point.x, point.z)
	var segment := b - a
	if segment.length_squared() <= 0.000001:
		return p.distance_to(a)
	var t: float = clampf((p - a).dot(segment) / segment.length_squared(), 0.0, 1.0)
	return p.distance_to(a + segment * t)


func _wait_for_visual_position(value: Variant, timeout_s: float) -> bool:
	if not value is Vector3:
		return false
	var target: Vector3 = value
	var deadline: int = Time.get_ticks_usec() + int(timeout_s * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		var error: float = Vector2(main.player.global_position.x, main.player.global_position.z).distance_to(Vector2(target.x, target.z))
		if error <= main.player.presentation_reconciliation_tolerance_m():
			return true
		await get_tree().physics_frame
	return false


func _wait_for_size(values: Array, size: int) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while values.size() < size and Time.get_ticks_usec() < deadline:
		await get_tree().process_frame
	return values.size() >= size


func _wait_for_raw_command_ref(command_ref: String) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		if not _raw_result_for_ref(command_ref).is_empty():
			return true
		await get_tree().process_frame
	return false


func _raw_result_for_ref(command_ref: String) -> Dictionary:
	for value: Dictionary in _raw_command_results:
		if str(value.get("command_ref", "")) == command_ref:
			return value
	return {}


func _raw_result_count(command_ref: String) -> int:
	var count: int = 0
	for value: Dictionary in _raw_command_results:
		if str(value.get("command_ref", "")) == command_ref:
			count += 1
	return count


func _wait_for_raw_ref_count(command_ref: String, expected: int) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		if _raw_result_count(command_ref) >= expected:
			return true
		await get_tree().process_frame
	return false


func _last_raw_result_for_ref(command_ref: String) -> Dictionary:
	for index: int in range(_raw_command_results.size() - 1, -1, -1):
		var value: Dictionary = _raw_command_results[index]
		if str(value.get("command_ref", "")) == command_ref:
			return value
	return {}


func _command_ref(request: Dictionary) -> String:
	return str(request.get("authority_submission", {}).get("command_ref", ""))


func _snapshot_position(snapshot: Dictionary) -> Dictionary:
	var transform: Dictionary = snapshot.get("transform", {})
	return {"iso_x_m": transform.get("iso_x_m"), "iso_y_m": transform.get("iso_y_m"), "altitude_m": transform.get("altitude_m", 0.0)}


func _authority_distance(a: Dictionary, b: Dictionary) -> float:
	if not _valid_authority(a) or not _valid_authority(b):
		return 0.0
	return Vector2(float(a.get("iso_x_m")), float(a.get("iso_y_m"))).distance_to(Vector2(float(b.get("iso_x_m")), float(b.get("iso_y_m"))))


func _valid_authority(value: Variant) -> bool:
	return value is Dictionary and typeof(value.get("iso_x_m")) in [TYPE_INT, TYPE_FLOAT] and typeof(value.get("iso_y_m")) in [TYPE_INT, TYPE_FLOAT]


func _compact_evidence(label: String, accepted: Dictionary) -> Dictionary:
	return {"label": label, "local_destination": _vector_json(accepted.get("local_destination", Vector3.ZERO)), "mapped_authority_destination": accepted.get("mapped_authority_destination", {}).duplicate(true), "command_ref": accepted.get("command_ref", ""), "authority_result_position": accepted.get("authority_result_position", {}).duplicate(true), "reprojected_local_position": _vector_json(accepted.get("reprojected_local_position", Vector3.ZERO)), "reconciliation": accepted.get("reconciliation", {}).duplicate(true)}


func _vector_json(value: Vector3) -> Dictionary:
	return {"x": value.x, "y": value.y, "z": value.z}


func _check(id: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(id if detail.is_empty() else "%s:%s" % [id, detail])


func _finish(extra: Dictionary = {}) -> void:
	var summary := {"status": "PASS" if _failures.is_empty() else "FAIL", "checks": _checks, "passed": _checks - _failures.size(), "failed": _failures.size(), "failures": _failures, "gate": "S17_B2_AUTHORITATIVE_CLICK_TO_MOVE", "backend_roundtrip_executed": true}
	summary.merge(extra, true)
	print("ANDROMEDA_STAGE17_B2_GATE: %s" % summary["status"])
	print("ANDROMEDA_STAGE17_B2_SUMMARY: %s" % JSON.stringify(summary))
	if not _failures.is_empty():
		get_tree().quit(1)
		return
	var linger_s: float = _success_linger_seconds()
	if linger_s > 0.0:
		await get_tree().create_timer(linger_s).timeout
	get_tree().quit(0)


func _success_linger_seconds() -> float:
	var configured: float = float(ProjectSettings.get_setting("andromeda/gate/success_linger_s", 240.0))
	for argument: String in OS.get_cmdline_user_args():
		if argument.begins_with("--gate-success-linger="):
			var raw: String = argument.trim_prefix("--gate-success-linger=")
			if raw.is_valid_float():
				return maxf(0.0, raw.to_float())
	return maxf(0.0, configured)
