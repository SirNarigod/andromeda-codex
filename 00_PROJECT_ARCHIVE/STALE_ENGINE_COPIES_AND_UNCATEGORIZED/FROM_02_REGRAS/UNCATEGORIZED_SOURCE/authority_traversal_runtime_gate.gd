extends Node

const SESSION_REF := "GODOT-AUTHORITY-TRAVERSAL-V080"
const WAIT_TIMEOUT_S := 45.0

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _checks: int = 0
var _failures: Array[String] = []
var _bind_results: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []
var _move_results: Array[Dictionary] = []
var _results: Array[Dictionary] = []


func _ready() -> void:
	await _run_gate()


func _run_gate() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_check("SESSION_AUTOLOAD", session != null)
	_check("BRIDGE_AUTOLOAD", bridge != null)
	_check("TRAVERSAL_CLIENT_PRESENT", main != null and main.traversal_authority_client != null)
	if session == null or bridge == null or main == null:
		await _finish()
		return
	bridge.authority_session_bound.connect(func(result: Dictionary) -> void:
		_bind_results.append(result.duplicate(true))
	)
	bridge.snapshot_applied.connect(func(snapshot: Dictionary) -> void:
		_snapshots.append(snapshot.duplicate(true))
	)
	bridge.command_result_received.connect(func(result: Dictionary) -> void:
		var command_name: String = str(result.get("command", ""))
		if command_name == "REPORT_TRAVERSAL_SAMPLE":
			_results.append(result.duplicate(true))
		elif command_name == "MOVE_TO_POINT":
			_move_results.append(result.duplicate(true))
	)

	if session.has_active_session():
		session.revoke_session()
	_check("LOCAL_BIND", session.bind_session(SESSION_REF).get("status") == "PASS")
	_check("AUTHORITY_BIND_STARTED", bridge.bind_authoritative_session().get("status") == "PASS")
	if not await _wait_for_size(_bind_results, 1) or not await _wait_for_size(_snapshots, 1):
		_failures.append("INITIAL_AUTHORITY_SYNC_TIMEOUT")
		await _finish()
		return
	var initial: Dictionary = _snapshots[0]
	_check("TRAVERSAL_COMMAND_ENABLED", _bind_results[0].get("enabled_commands", []).has("REPORT_TRAVERSAL_SAMPLE"))
	_check("STAMINA_SNAPSHOT_PRESENT", initial.get("stamina") is Dictionary)
	_check("STAMINA_SNAPSHOT_AUTHORITATIVE", str(initial.get("stamina", {}).get("authority", "")).contains("SERVER_AUTHORITATIVE"))
	var initial_fraction: float = float(initial.get("stamina", {}).get("fraction", -1.0))
	_check("STAMINA_INITIAL_RANGE", initial_fraction >= 0.0 and initial_fraction <= 1.0)
	_check("HUD_INITIAL_STAMINA_MATCH", is_equal_approx(main.hud.stamina_ring.stamina_fraction(), initial_fraction))

	var submission: Dictionary = main.traversal_authority_client.force_submit_sample(2.0, 10.0, "GRASS_FIELD", true)
	_check("GODOT_SURFACE_OBSERVATION_SUBMITTED", submission.get("status") == "PASS" and submission.get("transport_submitted") == true, JSON.stringify(submission))
	_check("CLIENT_DID_NOT_CALCULATE_LOAD", submission.get("load_calculated_locally") == false)
	_check("CLIENT_DID_NOT_MUTATE_STAMINA", submission.get("stamina_mutated_locally") == false)
	var submitted_params: Dictionary = submission.get("intent_envelope", {}).get("envelope", {}).get("params", {})
	_check("TRAVERSAL_ENVELOPE_OBSERVATION_ONLY", submitted_params.keys().size() == 4 and not submitted_params.has("current_weight") and not submitted_params.has("stamina"), JSON.stringify(submitted_params))
	if not await _wait_for_size(_results, 1) or not await _wait_for_size(_snapshots, 2):
		_failures.append("TRAVERSAL_ROUNDTRIP_TIMEOUT")
		await _finish()
		return
	var first: Dictionary = _results[0]
	var first_snapshot: Dictionary = _snapshots[1]
	_check("TRAVERSAL_CORE_PASS", first.get("status") == "PASS", JSON.stringify(first))
	_check("TRAVERSAL_SERVER_AUTHORITATIVE", first.get("server_authoritative") == true)
	_check("TRAVERSAL_STAGE16A_SURFACE", first.get("traversal", {}).get("surface_ref") == "GRASS_FIELD")
	_check("TRAVERSAL_STAGE16A_SLOPE", first.get("traversal", {}).get("slope", {}).get("band") == "LIGHT")
	_check("TRAVERSAL_LOAD_FROM_INVENTORY_CORE", first.get("traversal", {}).get("load", {}).get("inventory_authority") == "STAGE05_UNIVERSAL_ITEM_CORE")
	var first_fraction: float = float(first_snapshot.get("stamina", {}).get("fraction", -1.0))
	_check("STAMINA_DECREASED_IN_AUTHORITY", first_fraction < initial_fraction)
	_check("HUD_PROJECTED_AUTHORITY_STAMINA", is_equal_approx(main.hud.stamina_ring.stamina_fraction(), first_fraction))
	_check("STAMINA_RING_VISIBLE_AFTER_COST", main.hud.stamina_ring.should_be_visible())

	var replay_ref: String = str(submission.get("intent_envelope", {}).get("envelope", {}).get("command_ref", ""))
	_check("TRAVERSAL_COMMAND_REF_PRESENT", not replay_ref.is_empty())
	_check("TRAVERSAL_REPLAY_QUEUED", bridge.submit_command("REPORT_TRAVERSAL_SAMPLE", submitted_params, replay_ref).get("status") == "PASS")
	if not await _wait_for_size(_results, 2) or not await _wait_for_size(_snapshots, 3):
		_failures.append("TRAVERSAL_REPLAY_TIMEOUT")
		await _finish()
		return
	_check("TRAVERSAL_REPLAY_SUPPRESSED", _results[1].get("idempotent_replay") == true and _results[1].get("replay_suppressed") == true)
	_check("TRAVERSAL_REPLAY_NO_DOUBLE_STAMINA", is_equal_approx(float(_snapshots[2].get("stamina", {}).get("fraction", -1.0)), first_fraction))

	var road_index: int = _results.size()
	var road_snapshot_index: int = _snapshots.size()
	main.traversal_authority_client.force_submit_sample(1.0, 0.0, "ROAD_GOOD", true)
	if not await _wait_for_size(_results, road_index + 1) or not await _wait_for_size(_snapshots, road_snapshot_index + 1):
		_failures.append("ROAD_SAMPLE_TIMEOUT")
		await _finish()
		return
	var road: Dictionary = _results[road_index]
	var mud_index: int = _results.size()
	var mud_snapshot_index: int = _snapshots.size()
	main.traversal_authority_client.force_submit_sample(1.0, 0.0, "MUD", true)
	if not await _wait_for_size(_results, mud_index + 1) or not await _wait_for_size(_snapshots, mud_snapshot_index + 1):
		_failures.append("MUD_SAMPLE_TIMEOUT")
		await _finish()
		return
	var mud: Dictionary = _results[mud_index]
	_check("ROAD_ADVANTAGE_AUTHORITATIVE", float(road.get("traversal", {}).get("stamina_cost", INF)) < float(mud.get("traversal", {}).get("stamina_cost", -INF)))
	_check("MUD_SPEED_PENALTY_AUTHORITATIVE", float(mud.get("traversal", {}).get("effective_speed_mps", INF)) < float(road.get("traversal", {}).get("effective_speed_mps", -INF)))

	var moderate_index: int = _results.size()
	var moderate_snapshot_index: int = _snapshots.size()
	main.traversal_authority_client.force_submit_sample(1.0, 20.0, "GRASS_FIELD", true)
	if not await _wait_for_size(_results, moderate_index + 1) or not await _wait_for_size(_snapshots, moderate_snapshot_index + 1):
		_failures.append("MODERATE_SAMPLE_TIMEOUT")
		await _finish()
		return
	var moderate: Dictionary = _results[moderate_index]
	_check("MODERATE_SLOPE_AUTHORITATIVE", moderate.get("traversal", {}).get("slope", {}).get("band") == "MODERATE")
	_check("MODERATE_SLOPE_COST_ABOVE_FLAT_ROAD", float(moderate.get("traversal", {}).get("stamina_cost", 0.0)) > float(road.get("traversal", {}).get("stamina_cost", INF)))

	var before_blocked_snapshot_count: int = _snapshots.size()
	var before_blocked_fraction: float = float(_snapshots.back().get("stamina", {}).get("fraction", -1.0))
	var blocked_index: int = _results.size()
	main.traversal_authority_client.force_submit_sample(1.0, 32.0001, "FIRM_GROUND", true)
	if not await _wait_for_size(_results, blocked_index + 1) or not await _wait_for_size(_snapshots, before_blocked_snapshot_count + 1):
		_failures.append("BLOCKED_SLOPE_TIMEOUT")
		await _finish()
		return
	var blocked: Dictionary = _results[blocked_index]
	_check("SLOPE_ABOVE_32_REJECTED_BY_CORE", blocked.get("status") == "REJECTED" and blocked.get("reason") == "SLOPE_EXCEEDS_PRE_GODOT_WALKABLE_CANDIDATE", JSON.stringify(blocked))
	_check("BLOCKED_SLOPE_NO_STAMINA_COST", is_equal_approx(float(_snapshots.back().get("stamina", {}).get("fraction", -2.0)), before_blocked_fraction))

	var forged_index: int = _results.size()
	var forged_params := {
		"distance_m": 1.0,
		"slope_deg": 0.0,
		"surface_ref": "FIRM_GROUND",
		"ascending": true,
		"current_weight": 0.0,
	}
	_check("FORGED_LOAD_REQUEST_QUEUED_FOR_SERVER_GUARD", bridge.submit_command("REPORT_TRAVERSAL_SAMPLE", forged_params, _unique_ref("FORGED-LOAD")).get("status") == "PASS")
	if not await _wait_for_size(_results, forged_index + 1):
		_failures.append("FORGED_LOAD_REJECTION_TIMEOUT")
		await _finish()
		return
	_check("FORGED_LOAD_REJECTED_BY_SERVER", _results[forged_index].get("reason") == "UNEXPECTED_COMMAND_PARAM", JSON.stringify(_results[forged_index]))
	_check("FORGED_STAMINA_REJECTED_BY_CLIENT_GUARD", bridge.build_command_envelope("REPORT_TRAVERSAL_SAMPLE", {"stamina": 100.0}).get("reason") == "CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN")
	# G16B-08 'refills': the ring must climb back when the authority restores stamina.
	# The client never adds stamina; it walks and projects whatever the core reports.
	var drained_fraction: float = main.hud.stamina_ring.stamina_fraction()
	var refilled_fraction: float = drained_fraction
	var refill_diagnostic: String = "NO_STEP_ATTEMPTED"
	for step: int in range(1, 16):
		var move_index: int = _move_results.size()
		var move_params: Dictionary = {
			"iso_x_m": float(_snapshots.back().get("transform", {}).get("iso_x_m", 0.0)) + 5.0,
			"iso_y_m": float(_snapshots.back().get("transform", {}).get("iso_y_m", 0.0)),
			"duration_s": 0.25,
			"mode": "WALK",
		}
		var queued: Dictionary = bridge.submit_command("MOVE_TO_POINT", move_params, _unique_ref("REFILL-%d" % step))
		if queued.get("status") != "PASS":
			refill_diagnostic = "QUEUE_REJECTED:%s" % JSON.stringify(queued)
			break
		if not await _wait_for_size(_move_results, move_index + 1):
			refill_diagnostic = "RESULT_TIMEOUT_AT_STEP_%d" % step
			break
		var move_result: Dictionary = _move_results[move_index]
		if move_result.get("status") != "PASS":
			refill_diagnostic = "MOVE_REJECTED:%s" % JSON.stringify(move_result)
			break
		await _wait_bridge_ready(bridge)
		refilled_fraction = main.hud.stamina_ring.stamina_fraction()
		refill_diagnostic = "STEPS=%d authority_stamina=%s ring=%f" % [
			step,
			str(move_result.get("stamina", "absent")),
			refilled_fraction,
		]
		if refilled_fraction > drained_fraction:
			break
	_check(
		"STAMINA_RING_REFILLS_FROM_AUTHORITY",
		refilled_fraction > drained_fraction,
		"drained=%f refilled=%f %s" % [drained_fraction, refilled_fraction, refill_diagnostic]
	)
	_check(
		"REFILL_MATCHES_AUTHORITATIVE_SNAPSHOT",
		is_equal_approx(
			main.hud.stamina_ring.stamina_fraction(),
			float(_snapshots.back().get("stamina", {}).get("fraction", -1.0))
		),
		JSON.stringify(_snapshots.back().get("stamina", {}))
	)

	var contract: Dictionary = main.traversal_authority_client.contract_snapshot()
	_check("NO_LOAD_AUTHORITY_IN_GDSCRIPT", contract.get("load_authority_in_gdscript") == false)
	_check("NO_STAMINA_AUTHORITY_IN_GDSCRIPT", contract.get("stamina_authority_in_gdscript") == false)
	await _wait_bridge_ready(bridge)
	_check("BRIDGE_FINAL_READY", bridge.connection_state().get("state") == "READY")
	await _finish()


func _unique_ref(label: String) -> String:
	return "GODOT-TRAVERSAL-%s-%d" % [label, Time.get_ticks_usec()]


func _wait_for_size(values: Array, expected: int) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while values.size() < expected and Time.get_ticks_usec() < deadline:
		await get_tree().process_frame
	return values.size() >= expected


func _wait_bridge_ready(bridge: AndromedaRuntimeBridge) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while bridge.connection_state().get("state") != "READY" and Time.get_ticks_usec() < deadline:
		await get_tree().process_frame
	return bridge.connection_state().get("state") == "READY"


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
		"gate": "STAGE16B_AUTHORITY_TRAVERSAL_STAMINA",
		"backend_roundtrip_executed": true,
		"authority": "STAGE16A_TERRAIN_LOAD_TRAVERSAL_AND_MOVEMENT_STAMINA",
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_AUTHORITY_TRAVERSAL_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_AUTHORITY_TRAVERSAL_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_AUTHORITY_TRAVERSAL_SUMMARY: %s" % JSON.stringify(summary))
	if not _failures.is_empty():
		get_tree().quit(1)
		return
	var linger: float = _success_linger_seconds()
	if linger > 0.0:
		await get_tree().create_timer(linger).timeout
	get_tree().quit(0)


func _success_linger_seconds() -> float:
	var configured: float = float(ProjectSettings.get_setting("andromeda/gate/success_linger_s", 240.0))
	for argument: String in OS.get_cmdline_user_args():
		if argument.begins_with("--gate-success-linger="):
			var raw: String = argument.trim_prefix("--gate-success-linger=")
			if raw.is_valid_float():
				return maxf(0.0, raw.to_float())
	return maxf(0.0, configured)
