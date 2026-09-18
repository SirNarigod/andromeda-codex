extends Node

const SESSION_REF := "GODOT-STAGE17-B2-PERFORMANCE-V010"
const DURATION_S := 60.0
const WAIT_TIMEOUT_S := 75.0

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _checks: int = 0
var _failures: Array[String] = []
var _binds: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []
var _accepted: Array[Dictionary] = []
var _frame_times_ms: Array[float] = []


func _ready() -> void:
	await _run()


func _run() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_check("RUNTIME_PRESENT", main != null and session != null and bridge != null)
	if main == null or session == null or bridge == null:
		await _finish()
		return
	bridge.authority_session_bound.connect(func(value: Dictionary) -> void: _binds.append(value.duplicate(true)))
	bridge.snapshot_applied.connect(func(value: Dictionary) -> void: _snapshots.append(value.duplicate(true)))
	main.movement_authority_client.movement_accepted.connect(func(value: Dictionary) -> void: _accepted.append(value.duplicate(true)))
	if session.has_active_session():
		session.revoke_session()
	_check("LOCAL_SESSION_BOUND", session.bind_session(SESSION_REF).get("status") == "PASS")
	_check("AUTHORITY_BIND_STARTED", bridge.bind_authoritative_session().get("status") == "PASS")
	if not await _wait_for_size(_binds, 1) or not await _wait_for_size(_snapshots, 1):
		_failures.append("STARTUP_TIMEOUT")
		await _finish()
		return
	var start_nodes: int = int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT))
	var start_usec: int = Time.get_ticks_usec()
	var previous_usec: int = start_usec
	var next_submit_s: float = 2.0
	var submitted_requests: int = 0
	var submit_failures: Array[Dictionary] = []
	while float(Time.get_ticks_usec() - start_usec) / 1000000.0 < DURATION_S:
		await get_tree().process_frame
		var now_usec: int = Time.get_ticks_usec()
		_frame_times_ms.append(float(now_usec - previous_usec) / 1000.0)
		previous_usec = now_usec
		var elapsed_s: float = float(now_usec - start_usec) / 1000000.0
		if elapsed_s >= next_submit_s and submitted_requests < 6:
			var offset := Vector3(1.0, 0.0, 0.65) if submitted_requests % 2 == 0 else Vector3(-1.0, 0.0, -0.65)
			var desired: Vector3 = main.player.global_position + offset
			var validation: Dictionary = main.player.validate_destination(desired)
			if validation.get("status") == "PASS":
				var request: Dictionary = main.player.request_move(validation.get("navigation_destination", desired))
				if request.get("status") != "PASS" or request.get("transport_submitted") != true:
					submit_failures.append(request)
			else:
				submit_failures.append(validation)
			submitted_requests += 1
			next_submit_s += 10.0
	var settle_deadline: int = Time.get_ticks_usec() + 10000000
	while not main.movement_authority_client.pending_command_refs().is_empty() and Time.get_ticks_usec() < settle_deadline:
		await get_tree().process_frame
	var duration_s: float = float(Time.get_ticks_usec() - start_usec) / 1000000.0
	var end_nodes: int = int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT))
	var metrics: Dictionary = main.movement_authority_client.metrics_snapshot()
	var sorted: Array[float] = _frame_times_ms.duplicate()
	sorted.sort()
	var p95_index: int = clampi(int(ceil(float(sorted.size()) * 0.95)) - 1, 0, maxi(0, sorted.size() - 1))
	var average_frame_ms: float = 0.0
	for value: float in _frame_times_ms:
		average_frame_ms += value
	if not _frame_times_ms.is_empty():
		average_frame_ms /= float(_frame_times_ms.size())
	var report := {
		"duration_s": duration_s,
		"frame_count": _frame_times_ms.size(),
		"observed_fps": float(_frame_times_ms.size()) / duration_s,
		"average_frame_time_ms": average_frame_ms,
		"p95_frame_time_ms": sorted[p95_index] if not sorted.is_empty() else 0.0,
		"max_frame_time_ms": sorted.back() if not sorted.is_empty() else 0.0,
		"move_to_point_command_count": metrics.get("submitted"),
		"movement_accept_count": metrics.get("accepted"),
		"movement_rejection_count": metrics.get("rejected"),
		"reconciliation_count": metrics.get("reconciliations"),
		"max_reconciliation_error_m": metrics.get("max_reconciliation_error_m"),
		"node_count_start": start_nodes,
		"node_count_end": end_nodes,
		"node_count_delta": end_nodes - start_nodes,
		"threshold_invented": false,
	}
	_check("RAN_AT_LEAST_60_SECONDS", duration_s >= DURATION_S, str(duration_s))
	_check("SIX_EXPLICIT_DESTINATIONS_SUBMITTED", submitted_requests == 6)
	_check("ALL_SUBMISSIONS_LOCALLY_ACCEPTED", submit_failures.is_empty(), JSON.stringify(submit_failures))
	_check("ONE_COMMAND_PER_DESTINATION", int(metrics.get("submitted")) == 6, JSON.stringify(metrics))
	_check("ALL_AUTHORITY_RESULTS_ACCEPTED", int(metrics.get("accepted")) == 6, JSON.stringify(metrics))
	_check("NO_AUTHORITY_REJECTION", int(metrics.get("rejected")) == 0, JSON.stringify(metrics))
	_check("NO_PENDING_MOVEMENT", main.movement_authority_client.pending_command_refs().is_empty())
	_check("FRAME_METRICS_COLLECTED", _frame_times_ms.size() > 100)
	_check("NO_RUNAWAY_NODE_GROWTH", end_nodes - start_nodes < 20, str(end_nodes - start_nodes))
	await _finish({"performance": report, "movement_metrics": metrics})


func _wait_for_size(values: Array, size: int) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while values.size() < size and Time.get_ticks_usec() < deadline:
		await get_tree().process_frame
	return values.size() >= size


func _check(id: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(id if detail.is_empty() else "%s:%s" % [id, detail])


func _finish(extra: Dictionary = {}) -> void:
	var summary := {"status": "PASS" if _failures.is_empty() else "FAIL", "checks": _checks, "passed": _checks - _failures.size(), "failed": _failures.size(), "failures": _failures, "gate": "S17_B2_60_SECOND_PERFORMANCE_SMOKE"}
	summary.merge(extra, true)
	print("ANDROMEDA_STAGE17_B2_PERFORMANCE: %s" % summary["status"])
	print("ANDROMEDA_STAGE17_B2_PERFORMANCE_SUMMARY: %s" % JSON.stringify(summary))
	get_tree().quit(0 if _failures.is_empty() else 1)
