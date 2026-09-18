extends Node

var _checks: int = 0
var _failures: Array[String] = []


func _ready() -> void:
	await _run_gate()


func _check(check_id: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(check_id if detail.is_empty() else "%s:%s" % [check_id, detail])


func _expect_reason(check_id: String, result: Dictionary, reason: String) -> void:
	_check(check_id, result.get("status") == "REJECTED" and result.get("reason") == reason, JSON.stringify(result))


func _snapshot(sequence: Variant = 1, session_ref: String = "B01-GATE-SESSION") -> Dictionary:
	var snapshot := {
		"status": "PASS",
		"server_authoritative": true,
		"authority": "INTEGRATED_ARPG_ENGINE_V16A",
		"session_ref": session_ref,
		"snapshot_id": "SNAP-B01-%s" % str(sequence),
		"transform": {
			"iso_x_m": 12.5,
			"iso_y_m": -4.25,
			"altitude_m": 3.0,
			"heading_deg": 90.0,
		},
		"chunk": {
			"chunk_id": "CHK-B01",
			"entities": [
				{
					"entity_ref": "NPC-B01",
					"kind": "NPC",
					"isometric": {"x_m": 12.5, "y_m": -4.25, "z_m": 3.0},
				}
			],
		},
		"environment": {"temperature_c": 22.0, "daylight": 0.75},
	}
	if sequence != null:
		snapshot["snapshot_sequence"] = sequence
	return snapshot


func _run_gate() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_check("AUTOLOAD_CLIENT_SESSION", session != null)
	_check("AUTOLOAD_ANDROMEDA_BRIDGE", bridge != null)
	if session == null or bridge == null:
		await _finish()
		return

	_check("GODOT_VERSION_4_7", Engine.get_version_info().get("major") == 4 and Engine.get_version_info().get("minor") == 7)
	_check("EXISTING_SERVER_URL", bridge.server_url() == "http://127.0.0.1:8000", bridge.server_url())
	_check("EXISTING_SNAPSHOT_PATH", bridge.snapshot_path() == "/snapshot")
	_check("EXISTING_COMMAND_PATH", bridge.command_path() == "/command")
	_check("CLIENT_ONLY_AUTHORITY", bridge.AUTHORITY == "GODOT_CLIENT_TRANSPORT_PRESENTATION_ONLY")

	_expect_reason("SNAPSHOT_REQUIRES_SESSION", bridge.apply_snapshot(_snapshot()), "NO_ACTIVE_SESSION")
	_expect_reason("EMPTY_SESSION_REJECTED", session.bind_session("   "), "EMPTY_SESSION_REF")
	_check("EMPTY_SESSION_STAYS_UNBOUND", not session.has_active_session())

	var bind: Dictionary = session.bind_session("  B01-GATE-SESSION  ")
	_check("SESSION_BIND_PASS", bind.get("status") == "PASS", JSON.stringify(bind))
	_check("SESSION_TRIMMED", session.session_ref() == "B01-GATE-SESSION")
	_check("SESSION_EPOCH_ONE", session.session_epoch() == 1)
	_check("BRIDGE_CONNECTING_AFTER_BIND", bridge.connection_state().get("state") == bridge.STATE_CONNECTING)
	var bind_replay: Dictionary = session.bind_session("B01-GATE-SESSION")
	_check("SESSION_BIND_IDEMPOTENT", bind_replay.get("idempotent") == true and session.session_epoch() == 1)

	var authoritative: Dictionary = _snapshot(1)
	var applied: Dictionary = bridge.apply_snapshot(authoritative)
	_check("AUTHORITATIVE_SNAPSHOT_PASS", applied.get("status") == "PASS", JSON.stringify(applied))
	_check("BRIDGE_READY_AFTER_SNAPSHOT", bridge.connection_state().get("state") == bridge.STATE_READY)
	_check("SNAPSHOT_CURSOR_ONE", session.cursor_snapshot().get("last_snapshot_sequence") == 1)
	_check("VISIBLE_ENTITY_PROJECTED", bridge.visible_entities().has("NPC-B01"))
	_check("SNAPSHOT_TRANSFORM_PROJECTED", is_equal_approx(float(bridge.current_snapshot()["transform"]["iso_x_m"]), 12.5))
	authoritative["transform"]["iso_x_m"] = 999.0
	_check("SNAPSHOT_DEEP_COPIED", is_equal_approx(float(bridge.current_snapshot()["transform"]["iso_x_m"]), 12.5))

	var non_authoritative: Dictionary = _snapshot(2)
	non_authoritative["server_authoritative"] = false
	_expect_reason("NON_AUTHORITATIVE_REJECTED", bridge.apply_snapshot(non_authoritative), "NON_AUTHORITATIVE_SNAPSHOT")
	_check("REJECTED_SNAPSHOT_DOES_NOT_ADVANCE_CURSOR", session.cursor_snapshot().get("last_snapshot_sequence") == 1)

	var malformed: Dictionary = _snapshot(2)
	malformed["transform"].erase("iso_y_m")
	_expect_reason("MALFORMED_TRANSFORM_REJECTED", bridge.apply_snapshot(malformed), "INVALID_TRANSFORM")
	_check("MALFORMED_SNAPSHOT_DOES_NOT_ADVANCE_CURSOR", session.cursor_snapshot().get("last_snapshot_sequence") == 1)

	var second: Dictionary = _snapshot(2)
	_check("SECOND_SNAPSHOT_PASS", bridge.apply_snapshot(second).get("status") == "PASS")
	_expect_reason("STALE_SNAPSHOT_REJECTED", bridge.apply_snapshot(_snapshot(1)), "STALE_OR_DUPLICATE_SNAPSHOT")
	_expect_reason("SESSION_MISMATCH_REJECTED", bridge.apply_snapshot(_snapshot(3, "OTHER-SESSION")), "SNAPSHOT_SESSION_MISMATCH")

	var duplicate_entity: Dictionary = _snapshot(3)
	duplicate_entity["chunk"]["entities"].append(duplicate_entity["chunk"]["entities"][0].duplicate(true))
	_expect_reason("DUPLICATE_ENTITY_REJECTED", bridge.apply_snapshot(duplicate_entity), "DUPLICATE_ENTITY_REF")

	var params := {"dx": 1.0, "dy": 0.25, "duration_s": 0.5, "mode": "WALK"}
	var built: Dictionary = bridge.build_command_envelope("move_vector", params)
	_check("COMMAND_ENVELOPE_PASS", built.get("status") == "PASS", JSON.stringify(built))
	var envelope: Dictionary = built.get("envelope", {})
	_check("COMMAND_NORMALIZED", envelope.get("command") == "MOVE_VECTOR")
	_check("COMMAND_SESSION_BOUND", envelope.get("session_ref") == "B01-GATE-SESSION")
	_check("COMMAND_NO_PLAYER_REF", not envelope.has("player_ref") and not envelope["params"].has("player_ref"))
	params["dx"] = 999.0
	_check("COMMAND_PARAMS_DEEP_COPIED", is_equal_approx(float(envelope["params"]["dx"]), 1.0))
	_expect_reason("INVALID_COMMAND_NAME_REJECTED", bridge.build_command_envelope("bad command", {}), "INVALID_COMMAND_NAME")
	_expect_reason("DAMAGE_COMMAND_REJECTED", bridge.build_command_envelope("APPLY_DAMAGE", {"target_ref": "NPC-B01"}), "CLIENT_AUTHORITATIVE_COMMAND_FORBIDDEN")
	_expect_reason("PLAYER_REF_REJECTED", bridge.build_command_envelope("INTERACT", {"player_ref": "FORGED"}), "CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN")
	_expect_reason("NESTED_GRANT_REJECTED", bridge.build_command_envelope("INTERACT", {"payload": [{"inventory_grant": {"item_ref": "FORGED"}}]}), "CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN")
	_expect_reason("CANON_MUTATION_REJECTED", bridge.build_command_envelope("INTERACT", {"canonical_mutation": true}), "CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN")

	var reconnect_one: Dictionary = bridge.record_transport_error("GATE_OFFLINE_ONE")
	_check("RECONNECT_WAIT_ONE", reconnect_one.get("state") == bridge.STATE_RECONNECT_WAIT)
	_check("RECONNECT_DELAY_BASE", is_equal_approx(float(reconnect_one.get("reconnect_delay_s")), 0.5))
	var reconnect_two: Dictionary = bridge.record_transport_error("GATE_OFFLINE_TWO")
	_check("RECONNECT_DELAY_EXPONENTIAL", is_equal_approx(float(reconnect_two.get("reconnect_delay_s")), 1.0))
	bridge.mark_transport_connected()
	_check("CONNECTED_REQUIRES_RESYNC", bridge.connection_state().get("state") == bridge.STATE_SYNCING)
	_check("RESYNC_SNAPSHOT_PASS", bridge.apply_snapshot(_snapshot(3)).get("status") == "PASS")
	_check("RECONNECT_COUNTER_RESET", bridge.connection_state().get("reconnect_attempt") == 0)

	var legacy: Dictionary = _snapshot(null)
	legacy.erase("snapshot_id")
	_check("LEGACY_V15_SNAPSHOT_COMPATIBLE", bridge.apply_snapshot(legacy).get("status") == "PASS")
	_check("LEGACY_ORDERING_RECORDED", session.cursor_snapshot().get("legacy_snapshot_count") == 1)

	var revoke: Dictionary = session.revoke_session()
	_check("SESSION_REVOKE_PASS", revoke.get("status") == "PASS")
	_check("SESSION_REVOKED_LOCAL", not session.has_active_session() and session.state() == session.STATE_REVOKED)
	_check("BRIDGE_CLEARS_SNAPSHOT_ON_REVOKE", bridge.current_snapshot().is_empty())
	_expect_reason("COMMAND_REQUIRES_ACTIVE_SESSION", bridge.build_command_envelope("MOVE_VECTOR", {}), "NO_ACTIVE_SESSION")

	var rebind: Dictionary = session.bind_session("B01-GATE-SESSION-2")
	_check("SESSION_REBIND_PASS", rebind.get("status") == "PASS" and session.session_epoch() == 2)
	var rebound_snapshot: Dictionary = _snapshot(0, "B01-GATE-SESSION-2")
	_check("REBIND_RESETS_SNAPSHOT_CURSOR", bridge.apply_snapshot(rebound_snapshot).get("status") == "PASS")
	_check("ZERO_SEQUENCE_VALID_AFTER_REBIND", session.cursor_snapshot().get("last_snapshot_sequence") == 0)

	await _finish()


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "B01_BRIDGE_SESSION_SNAPSHOT",
		"acceptance_scope": ["G16B-01"],
		"authority": "GODOT_CLIENT_ONLY",
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_B01_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_B01_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_B01_SUMMARY: %s" % JSON.stringify(summary))
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
