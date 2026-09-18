extends Node

var _checks: int = 0
var _failures: Array[String] = []
var _display_transitions: Array[String] = []
var _main: AndromedaMainRuntime
var _presenter: AndromedaAuthorityConnectionStatus


func _ready() -> void:
	print("ANDROMEDA_STAGE17_S17A_GATE: START")
	await _run_gate()


func _check(check_id: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(check_id if detail.is_empty() else "%s:%s" % [check_id, detail])


func _run_gate() -> void:
	var expect_failure: bool = OS.get_cmdline_user_args().has("--expect-authority-failure")
	_check("STAGE17_PROJECT_IDENTITY", ProjectSettings.get_setting("application/config/name") == "Andromeda ARPG Stage17 Playable V0 Dev")
	_check("STAGE17_SESSION_IDENTITY", ProjectSettings.get_setting("andromeda/bridge/default_session_ref") == "GODOT-STAGE17-PLAYABLE-V0-DEV-001")
	_check("STAGE17_LOOPBACK_AUTHORITY", ProjectSettings.get_setting("andromeda/bridge/server_url") == "http://127.0.0.1:8000")

	var packed_main: PackedScene = load("res://scenes/Main.tscn")
	_check("MAIN_SCENE_LOADS", packed_main != null)
	if packed_main == null:
		await _finish(expect_failure)
		return
	_main = packed_main.instantiate() as AndromedaMainRuntime
	_presenter = _main.get_node("UILayer/AuthorityConnectionStatus") as AndromedaAuthorityConnectionStatus
	_check("CONNECTION_PRESENTER_PRESENT", _presenter != null)
	if _presenter != null:
		_presenter.display_state_changed.connect(_on_display_state_changed)
	await get_tree().process_frame
	get_tree().root.add_child(_main)
	get_tree().current_scene = _main

	if expect_failure:
		# Exercise the bridge's existing failure/reconnect path without creating a
		# fake authority.  The backend is deliberately absent; this is the same
		# transport-error signal the real HTTP layer records after a failed request.
		var failure_bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
		if failure_bridge != null:
			failure_bridge.record_transport_error("S17A_CONTROLLED_BACKEND_UNAVAILABLE")
		await _wait_for_display_state(AndromedaAuthorityConnectionStatus.DISPLAY_FAILED, 3.0)
		var failure_status: Dictionary = _presenter.status_snapshot()
		_check("FAILED_STATE_OBSERVED", failure_status.get("display_state") == "FAILED", JSON.stringify(failure_status))
		_check("FAILED_NEVER_READY", not _display_transitions.has("READY"), JSON.stringify(_display_transitions))
		_check("FAILED_BRIDGE_NOT_READY", failure_bridge != null and failure_bridge.connection_state().get("state") != AndromedaRuntimeBridge.STATE_READY)
		_check("FAILED_NO_COMMAND_QUEUED", failure_bridge != null and int(failure_bridge.connection_state().get("queued_commands", -1)) == 0, JSON.stringify(failure_bridge.connection_state() if failure_bridge != null else {}))
		await _finish(true)
		return

	await _wait_for_display_state(AndromedaAuthorityConnectionStatus.DISPLAY_READY, 30.0)
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	var presenter_status: Dictionary = _presenter.status_snapshot() if _presenter != null else {}
	var bridge_state: Dictionary = bridge.connection_state() if bridge != null else {}
	var snapshot: Dictionary = bridge.current_snapshot() if bridge != null else {}
	_check("CONNECTING_TRANSITION_OBSERVED", _display_transitions.has("CONNECTING"), JSON.stringify(_display_transitions))
	_check("READY_TRANSITION_OBSERVED", _display_transitions.has("READY"), JSON.stringify(_display_transitions))
	_check("SESSION_BIND_PASS", session != null and session.has_active_session())
	_check("SESSION_REF_STAGE17", session != null and session.session_ref() == "GODOT-STAGE17-PLAYABLE-V0-DEV-001")
	_check("BRIDGE_READY", bridge_state.get("state") == AndromedaRuntimeBridge.STATE_READY, JSON.stringify(bridge_state))
	_check("AUTHORITY_SESSION_BOUND", bridge_state.get("authority_session_bound") == true, JSON.stringify(bridge_state))
	_check("SNAPSHOT_SERVER_AUTHORITATIVE", snapshot.get("server_authoritative") == true, JSON.stringify(snapshot))
	_check("SNAPSHOT_ID_PRESENT", not str(snapshot.get("snapshot_id", "")).is_empty())
	_check("SNAPSHOT_SEQUENCE_PRESENT", int(snapshot.get("snapshot_sequence", -1)) >= 0)
	_check("READY_AFTER_BIND_AND_SNAPSHOT", presenter_status.get("ready") == true and presenter_status.get("session_bound") == true and presenter_status.get("snapshot_ready") == true, JSON.stringify(presenter_status))
	_check("PRESENTER_AUTHORITY_READY", _presenter.is_authority_ready())
	_check("STAGE17_OWNER_SCOPE", str(snapshot.get("identity", {}).get("owner_scope", "")) == "stage17:playable-v0-dev", JSON.stringify(snapshot.get("identity", {})))
	await _finish(false)


func _on_display_state_changed(display_state: String, _detail: String) -> void:
	_display_transitions.append(display_state)


func _wait_for_display_state(expected: String, timeout_s: float) -> void:
	var deadline_ms: int = Time.get_ticks_msec() + int(timeout_s * 1000.0)
	while Time.get_ticks_msec() < deadline_ms:
		if _presenter != null and _presenter.status_snapshot().get("display_state") == expected:
			return
		await get_tree().process_frame


func _finish(expect_failure: bool) -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"mode": "FAILED_PATH" if expect_failure else "LIVE_AUTHORITY",
		"display_transitions": _display_transitions,
		"gate": "S17_A_PLAYABLE_STARTUP",
		"authority": "REAL_B01_BIND_AND_SNAPSHOT" if not expect_failure else "CONTROLLED_BACKEND_UNAVAILABLE",
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE17_S17A_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE17_S17A_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE17_S17A_SUMMARY: %s" % JSON.stringify(summary))
	if _main != null and is_instance_valid(_main):
		_main.queue_free()
		await get_tree().process_frame
		await get_tree().process_frame
	get_tree().quit(0 if _failures.is_empty() else 1)
