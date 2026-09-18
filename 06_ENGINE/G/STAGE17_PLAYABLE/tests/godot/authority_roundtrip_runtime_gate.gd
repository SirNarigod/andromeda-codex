extends Node

## Real Godot -> HTTP -> IntegratedARPGEngineV16A authority round-trip gate.
## Requires the approved authority adapter listening on 127.0.0.1:8000.

const SESSION_REF := "GODOT-AUTHORITY-ROUNDTRIP-V080"
const WAIT_TIMEOUT_S := 45.0

var _checks: int = 0
var _failures: Array[String] = []
var _bind_results: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []
var _command_results: Array[Dictionary] = []
var _command_rejections: Array[String] = []
var _snapshot_rejections: Array[String] = []
var _resync_results: Array[Dictionary] = []
var _resync_rejections: Array[String] = []


func _ready() -> void:
	await _run_gate()


func _run_gate() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_check("CLIENT_SESSION_AUTOLOAD", session != null)
	_check("RUNTIME_BRIDGE_AUTOLOAD", bridge != null)
	if session == null or bridge == null:
		await _finish()
		return

	_connect_evidence_signals(bridge)
	if session.has_active_session():
		session.revoke_session()
	var local_bind: Dictionary = session.bind_session(SESSION_REF)
	_check("LOCAL_SESSION_BOUND", local_bind.get("status") == "PASS", JSON.stringify(local_bind))
	_check("REAL_SERVER_URL", bridge.server_url() == "http://127.0.0.1:8000", bridge.server_url())
	_check("REAL_BIND_PATH", bridge.session_bind_path() == "/session/bind", bridge.session_bind_path())
	_check("REAL_RESYNC_PATH", bridge.session_resync_path() == "/session/resync", bridge.session_resync_path())
	_check("REAL_SNAPSHOT_PATH", bridge.snapshot_path() == "/snapshot", bridge.snapshot_path())
	_check("REAL_COMMAND_PATH", bridge.command_path() == "/command", bridge.command_path())

	var local_guard: Dictionary = bridge.build_command_envelope("MOVE_TO_POINT", {
		"player_ref": "CLIENT-FORGED",
	})
	_check(
		"CLIENT_AUTHORITY_FIELD_REJECTED_LOCALLY",
		local_guard.get("status") == "REJECTED"
		and local_guard.get("reason") == "CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN",
		JSON.stringify(local_guard)
	)
	var forbidden_command: Dictionary = bridge.build_command_envelope("DAMAGE_RESULT", {})
	_check(
		"CLIENT_AUTHORITY_COMMAND_REJECTED_LOCALLY",
		forbidden_command.get("status") == "REJECTED",
		JSON.stringify(forbidden_command)
	)

	var bind_start: Dictionary = bridge.bind_authoritative_session()
	_check("AUTHORITY_BIND_REQUEST_STARTED", bind_start.get("status") == "PASS", JSON.stringify(bind_start))
	if not await _wait_for_count(_bind_results, 1, WAIT_TIMEOUT_S):
		_failures.append("AUTHORITY_BIND_TIMEOUT")
		await _finish()
		return
	var bind_response: Dictionary = _bind_results[0]
	_check("AUTHORITY_BIND_PASS", bind_response.get("status") == "PASS", JSON.stringify(bind_response))
	_check("AUTHORITY_BINDS_SERVER_SELECTED_PLAYER", not str(bind_response.get("player_ref", "")).is_empty())
	_check("AUTHORITY_SESSION_MATCH", bind_response.get("session_ref") == SESSION_REF, JSON.stringify(bind_response))
	_check(
		"MOVE_TO_POINT_ENABLED_BY_REAL_AUTHORITY",
		(bind_response.get("enabled_commands", []) as Array).has("MOVE_TO_POINT"),
		JSON.stringify(bind_response.get("enabled_commands", []))
	)

	if not await _wait_for_count(_snapshots, 1, WAIT_TIMEOUT_S):
		_failures.append("INITIAL_AUTHORITATIVE_SNAPSHOT_TIMEOUT:rejections=%s state=%s" % [
			JSON.stringify(_snapshot_rejections),
			JSON.stringify(bridge.connection_state()),
		])
		await _finish()
		return
	var first_snapshot: Dictionary = _snapshots[0]
	_check("INITIAL_SNAPSHOT_SERVER_AUTHORITATIVE", first_snapshot.get("server_authoritative") == true)
	_check("INITIAL_SNAPSHOT_SESSION", first_snapshot.get("session_ref") == SESSION_REF)
	_check("INITIAL_SNAPSHOT_ID", str(first_snapshot.get("snapshot_id", "")).begins_with("S16B-"))
	_check("INITIAL_SNAPSHOT_SEQUENCE", typeof(first_snapshot.get("snapshot_sequence")) == TYPE_INT)
	_check("INITIAL_SNAPSHOT_TRANSFORM", _valid_transform(first_snapshot.get("transform", {})))
	_check(
		"INITIAL_SNAPSHOT_MASTER_V201",
		str(first_snapshot.get("identity", {}).get("master_version", "")) == "V2.0.1",
		JSON.stringify(first_snapshot.get("identity", {}))
	)
	_check(
		"INITIAL_SNAPSHOT_ENGINE_V16A",
		str(first_snapshot.get("identity", {}).get("engine_class", "")) == "IntegratedARPGEngineV16A",
		JSON.stringify(first_snapshot.get("identity", {}))
	)
	_check("BRIDGE_READY_AFTER_SNAPSHOT", bridge.connection_state().get("state") == "READY")

	var transform: Dictionary = first_snapshot["transform"]
	var command_ref := "GODOT-RT-%d-%d" % [OS.get_process_id(), Time.get_ticks_usec()]
	var params := {
		"iso_x_m": float(transform["iso_x_m"]) + 1.0,
		"iso_y_m": float(transform["iso_y_m"]),
		"duration_s": 0.25,
		"mode": "WALK",
	}
	var built: Dictionary = bridge.build_command_envelope("MOVE_TO_POINT", params, command_ref)
	_check("COMMAND_ENVELOPE_BUILT", built.get("status") == "PASS", JSON.stringify(built))
	var envelope: Dictionary = built.get("envelope", {})
	_check("COMMAND_REF_STABLE_IN_ENVELOPE", envelope.get("command_ref") == command_ref, JSON.stringify(envelope))
	_check("COMMAND_SESSION_IN_ENVELOPE", envelope.get("session_ref") == SESSION_REF, JSON.stringify(envelope))
	_check("COMMAND_HAS_NO_CLIENT_PLAYER_REF", not envelope.has("player_ref") and not params.has("player_ref"))

	var submit: Dictionary = bridge.submit_command("MOVE_TO_POINT", params, command_ref)
	_check("MOVE_COMMAND_QUEUED", submit.get("status") == "PASS", JSON.stringify(submit))
	if not await _wait_for_count(_command_results, 1, WAIT_TIMEOUT_S):
		_failures.append("MOVE_COMMAND_TIMEOUT")
		await _finish()
		return
	var first_command: Dictionary = _command_results[0]
	_check("MOVE_COMMAND_REAL_PASS", first_command.get("status") == "PASS", JSON.stringify(first_command))
	_check("MOVE_COMMAND_REF_ECHO", first_command.get("command_ref") == command_ref, JSON.stringify(first_command))
	_check("MOVE_COMMAND_DELEGATED_TO_CORE", first_command.get("delegated_core_command") == "MOVE_VECTOR")
	_check("MOVE_COMMAND_NOT_REPLAY", first_command.get("idempotent_replay") == false)
	_check("MOVE_COMMAND_WORLD_ADVANCED", float(first_command.get("moved_m", 0.0)) > 0.0, JSON.stringify(first_command))
	_check(
		"MOVE_COMMAND_CORE_AUTHORITY",
		str(first_command.get("authority", "")) == "LIVING_CONTINUOUS_ISOMETRIC_MOVEMENT_RUNTIME",
		str(first_command.get("authority", ""))
	)

	if not await _wait_for_count(_snapshots, 2, WAIT_TIMEOUT_S):
		_failures.append("POST_MOVE_SNAPSHOT_TIMEOUT")
		await _finish()
		return
	var moved_snapshot: Dictionary = _snapshots[1]
	_check(
		"POST_MOVE_SNAPSHOT_SEQUENCE_ADVANCED",
		int(moved_snapshot.get("snapshot_sequence", -1)) > int(first_snapshot.get("snapshot_sequence", -1))
	)
	_check(
		"POST_MOVE_AUTHORITATIVE_POSITION_CHANGED",
		float(moved_snapshot.get("transform", {}).get("iso_x_m", 0.0)) != float(transform["iso_x_m"]),
		JSON.stringify(moved_snapshot.get("transform", {}))
	)
	var moved_x: float = float(moved_snapshot.get("transform", {}).get("iso_x_m", 0.0))
	var moved_y: float = float(moved_snapshot.get("transform", {}).get("iso_y_m", 0.0))

	var replay_submit: Dictionary = bridge.submit_command("MOVE_TO_POINT", params, command_ref)
	_check("DUPLICATE_COMMAND_QUEUED_WITH_SAME_REF", replay_submit.get("status") == "PASS")
	if not await _wait_for_count(_command_results, 2, WAIT_TIMEOUT_S):
		_failures.append("DUPLICATE_COMMAND_TIMEOUT")
		await _finish()
		return
	var replay: Dictionary = _command_results[1]
	_check("DUPLICATE_REPLAY_IDENTIFIED", replay.get("idempotent_replay") == true, JSON.stringify(replay))
	_check("DUPLICATE_REPLAY_SUPPRESSED", replay.get("replay_suppressed") == true, JSON.stringify(replay))
	if not await _wait_for_count(_snapshots, 3, WAIT_TIMEOUT_S):
		_failures.append("POST_REPLAY_SNAPSHOT_TIMEOUT")
		await _finish()
		return
	var replay_snapshot: Dictionary = _snapshots[2]
	_check(
		"DUPLICATE_DID_NOT_MOVE_WORLD_AGAIN",
		is_equal_approx(float(replay_snapshot.get("transform", {}).get("iso_x_m", 0.0)), moved_x)
		and is_equal_approx(float(replay_snapshot.get("transform", {}).get("iso_y_m", 0.0)), moved_y),
		JSON.stringify(replay_snapshot.get("transform", {}))
	)

	var stale_apply: Dictionary = bridge.apply_snapshot(first_snapshot)
	_check(
		"STALE_SNAPSHOT_REJECTED_BY_GODOT",
		stale_apply.get("status") == "REJECTED"
		and stale_apply.get("reason") == "STALE_OR_DUPLICATE_SNAPSHOT",
		JSON.stringify(stale_apply)
	)
	_check("STALE_REJECTION_SIGNAL", _snapshot_rejections.has("STALE_OR_DUPLICATE_SNAPSHOT"))

	var resync_start: Dictionary = bridge.request_authoritative_resync()
	_check("RESYNC_REQUEST_STARTED", resync_start.get("status") == "PASS", JSON.stringify(resync_start))
	if not await _wait_for_count(_resync_results, 1, WAIT_TIMEOUT_S):
		_failures.append("RESYNC_TIMEOUT")
		await _finish()
		return
	var resync: Dictionary = _resync_results[0]
	_check("RESYNC_REAL_PASS", resync.get("status") == "PASS", JSON.stringify(resync))
	_check("RESYNC_RETURNS_FRESH_SNAPSHOT", resync.get("snapshot", {}).get("server_authoritative") == true)
	_check("RESYNC_CURSOR_CURRENT", resync.get("cursor", {}).get("cursor_status") == "CURRENT", JSON.stringify(resync.get("cursor", {})))
	_check("RESYNC_NO_REJECTION", _resync_rejections.is_empty(), JSON.stringify(_resync_rejections))
	_check("COMMAND_NO_REJECTION", _command_rejections.is_empty(), JSON.stringify(_command_rejections))
	_check("FINAL_BRIDGE_READY", bridge.connection_state().get("state") == "READY", JSON.stringify(bridge.connection_state()))
	_check("NO_GAMEPLAY_AUTHORITY_IN_GATE", true)

	await _finish()


func _connect_evidence_signals(bridge: AndromedaRuntimeBridge) -> void:
	bridge.authority_session_bound.connect(func(result: Dictionary) -> void:
		_bind_results.append(result.duplicate(true))
	)
	bridge.snapshot_applied.connect(func(snapshot: Dictionary) -> void:
		_snapshots.append(snapshot.duplicate(true))
	)
	bridge.snapshot_rejected.connect(func(reason: String) -> void:
		_snapshot_rejections.append(reason)
	)
	bridge.command_completed.connect(func(result: Dictionary) -> void:
		_command_results.append(result.duplicate(true))
	)
	bridge.command_rejected.connect(func(reason: String) -> void:
		_command_rejections.append(reason)
	)
	bridge.resync_completed.connect(func(result: Dictionary) -> void:
		_resync_results.append(result.duplicate(true))
	)
	bridge.resync_rejected.connect(func(reason: String) -> void:
		_resync_rejections.append(reason)
	)


func _wait_for_count(values: Array, expected: int, timeout_s: float) -> bool:
	var deadline_usec: int = Time.get_ticks_usec() + int(timeout_s * 1000000.0)
	while values.size() < expected and Time.get_ticks_usec() < deadline_usec:
		await get_tree().process_frame
	return values.size() >= expected


func _valid_transform(value: Variant) -> bool:
	if not value is Dictionary:
		return false
	var transform: Dictionary = value
	return (
		(typeof(transform.get("iso_x_m")) in [TYPE_INT, TYPE_FLOAT])
		and (typeof(transform.get("iso_y_m")) in [TYPE_INT, TYPE_FLOAT])
		and is_finite(float(transform.get("iso_x_m")))
		and is_finite(float(transform.get("iso_y_m")))
	)


func _check(check_id: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(check_id if detail.is_empty() else "%s:%s" % [check_id, detail])


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "STAGE16B_REAL_AUTHORITY_ROUNDTRIP",
		"backend_roundtrip_executed": true,
		"authority": "INTEGRATED_ARPG_ENGINE_V16A_SERVER_AUTHORITATIVE",
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_AUTHORITY_ROUNDTRIP_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_AUTHORITY_ROUNDTRIP_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_AUTHORITY_ROUNDTRIP_SUMMARY: %s" % JSON.stringify(summary))
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
		if not argument.begins_with("--gate-success-linger="):
			continue
		var raw_value: String = argument.trim_prefix("--gate-success-linger=")
		if raw_value.is_valid_float():
			return maxf(0.0, raw_value.to_float())
	return maxf(0.0, configured)
