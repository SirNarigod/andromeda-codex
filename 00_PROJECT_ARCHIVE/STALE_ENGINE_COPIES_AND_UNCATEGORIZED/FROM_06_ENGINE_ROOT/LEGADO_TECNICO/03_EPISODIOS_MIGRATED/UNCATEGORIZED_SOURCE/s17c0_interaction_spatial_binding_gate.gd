extends Node

## C0 proves one real ENEMY target end-to-end:
## server movement-state position -> snapshot -> one Stage17 registry -> approved
## mapper -> greybox node -> normal right-click -> MOVE_TO_POINT -> REQUEST_ATTACK.

const SESSION_REF := "GODOT-STAGE17-C0-ENEMY-V010"
const WAIT_TIMEOUT_S := 90.0
const TARGET_KIND := "ACTOR"

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _checks: int = 0
var _failures: Array[String] = []
var _binds: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []
var _movement_accepts: Array[Dictionary] = []
var _attack_projections: Array[Dictionary] = []
var _raw_attack_results: Array[Dictionary] = []
var _binding_updates: Array[Dictionary] = []
var _binding_invalidations: Array[Dictionary] = []
var _live_evidence: Dictionary = {}


func _ready() -> void:
	await _run()


func _run() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	var registry: AndromedaInteractionSpatialBindingRegistry = main.interaction_spatial_binding_registry
	_check("RUNTIME_PRESENT", main != null and session != null and bridge != null and registry != null)
	if main == null or session == null or bridge == null or registry == null:
		await _finish()
		return
	bridge.authority_session_bound.connect(func(value: Dictionary) -> void: _binds.append(value.duplicate(true)))
	bridge.snapshot_applied.connect(func(value: Dictionary) -> void: _snapshots.append(value.duplicate(true)))
	bridge.command_result_received.connect(_on_raw_command_result)
	main.movement_authority_client.movement_accepted.connect(func(value: Dictionary) -> void: _movement_accepts.append(value.duplicate(true)))
	main.combat_authority_client.attack_result_projected.connect(func(value: Dictionary) -> void: _attack_projections.append(value.duplicate(true)))
	registry.target_bound.connect(func(value: Dictionary) -> void: _binding_updates.append(value.duplicate(true)))
	registry.target_invalidated.connect(func(value: Dictionary) -> void: _binding_invalidations.append(value.duplicate(true)))

	var spawn_settled: bool = await _wait_for_spawn_settle()
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
	var initial_snapshot: Dictionary = _snapshots.back()
	_check("BRIDGE_READY", bridge.connection_state().get("state") == AndromedaRuntimeBridge.STATE_READY)
	_check("MAPPER_READY", main.authority_space_mapper.is_anchored())
	_check("SNAPSHOT_SERVER_AUTHORITATIVE", initial_snapshot.get("server_authoritative") == true)
	var world_instance_id: String = str((initial_snapshot.get("identity", {}) as Dictionary).get("world_instance_id", ""))
	_check("WORLD_INSTANCE_ID_PRESENT", not world_instance_id.is_empty())
	var combat_targets: Array = initial_snapshot.get("combat_targets", []) as Array
	_check("REAL_COMBAT_TARGET_PROJECTION_PRESENT", not combat_targets.is_empty())
	if combat_targets.is_empty():
		await _finish()
		return
	var target_entry: Dictionary = combat_targets[0] as Dictionary
	var target_ref: String = str(target_entry.get("target_ref", "")).strip_edges()
	var target: AndromedaInteractionTarget = main.combat_authority_client.actor_for_ref(target_ref)
	_check("TARGET_REF_REAL", not target_ref.is_empty())
	_check("TARGET_KIND_REAL", str(target_entry.get("target_kind", "")).to_upper() == TARGET_KIND)
	_check("TARGET_POSITION_REAL", _valid_authority_position(target_entry.get("position", {})))
	_check("TARGET_POSITION_AUTHORITY_REAL", str(target_entry.get("position_authority", "")) == "LIVING_CONTINUOUS_ISOMETRIC_MOVEMENT_RUNTIME")
	_check("TARGET_SAME_WORLD", str(registry.metrics_snapshot().get("world_instance_id", "")) == world_instance_id)
	_check("PRESENTATION_NODE_BOUND", target != null and registry.binding_for_ref(target_ref).get("status") == "PASS")
	if target == null:
		await _finish()
		return
	var binding: Dictionary = registry.binding_for_ref(target_ref)
	_check("NODE_REF_EQUALS_AUTHORITY_REF", target.target_ref == target_ref)
	_check("NODE_NOT_AUTHORITY_SOURCE", binding.get("node_is_authority_source") == false)
	_check("NODE_POSITION_SOURCE_IS_AUTHORITY", str(binding.get("source_authority")) == str(target_entry.get("position_authority")))
	var target_local: Vector3 = binding.get("local_position", Vector3.INF)
	_check("TARGET_AUTHORITY_TO_LOCAL_FINITE", _valid_vector(target_local))
	_check("NODE_POSITION_DERIVED_FROM_AUTHORITY", target.global_position.distance_to(target_local) <= 0.00001)
	var round_trip: Dictionary = main.authority_space_mapper.local_to_authority(target_local)
	_check("TARGET_LOCAL_TO_AUTHORITY_ROUND_TRIP", _authority_distance(round_trip, target_entry.get("position", {})) <= 0.00001)
	var registry_contract: Dictionary = registry.contract_snapshot()
	_check("REGISTRY_REUSES_SINGLE_MAPPER", registry_contract.get("coordinate_converter") == "AndromedaAuthoritySpaceMapper")
	_check("REGISTRY_HAS_NO_GAMEPLAY_DISTANCE_AUTHORITY", registry_contract.get("gameplay_distance_authority") == false)
	_check("NO_HARDCODED_LIVE_TARGET_REF", not _source_contains_live_value(target_ref))
	_check("NO_HARDCODED_AUTHORITY_POSITION", not _source_contains_live_value(str((target_entry.get("position", {}) as Dictionary).get("iso_x_m"))))

	# Establish a deterministic out-of-range P0 through the same authority movement
	# client. This is setup, not a teleport or database mutation.
	var attack_range_m: float = float(target_entry.get("attack_range_m", 0.0))
	_check("AUTHORITY_ATTACK_RANGE_PRESENT", attack_range_m > 0.0)
	var setup: Dictionary = await _establish_out_of_range_position(target_local, attack_range_m)
	var setup_destination: Vector3 = setup.get("destination", Vector3.INF)
	_check("SETUP_DESTINATION_VALID", setup_destination != Vector3.INF)
	if setup_destination == Vector3.INF:
		await _finish()
		return
	var setup_request: Dictionary = setup.get("request", {}) as Dictionary
	_check("SETUP_USES_REAL_MOVE_TO_POINT", setup_request.get("status") == "PASS" and setup_request.get("transport_submitted") == true)
	var setup_accept: Dictionary = setup.get("accept", {}) as Dictionary
	_check("SETUP_MOVEMENT_ACCEPTED", setup_accept.get("status") == "PASS")
	_check("SETUP_VISUAL_RECONCILED", setup.get("visual_reconciled") == true)
	var p0: Dictionary = setup_accept.get("authority_result_position", {}) as Dictionary
	_check("P0_OUTSIDE_ATTACK_RANGE", _authority_distance(p0, target_entry.get("position", {})) > attack_range_m)

	# Use the normal Main pointer path. Because two real combat actors may occupy the
	# same authoritative position, ask the actual pointer resolver which ref is under
	# the cursor and continue with that exact target rather than imposing type/ref order.
	await get_tree().process_frame
	var screen_position: Vector2 = main.world_to_screen(target.pointer_world_position())
	var resolved_under_cursor: Dictionary = main.pointer_target_at_screen(screen_position)
	var pointer_ref: String = str(resolved_under_cursor.get("target_ref", "")).strip_edges()
	if not pointer_ref.is_empty() and pointer_ref != target_ref:
		target_ref = pointer_ref
		target = main.combat_authority_client.actor_for_ref(target_ref)
		target_entry = _entry_by_ref(_snapshots.back().get("combat_targets", []) as Array, target_ref)
		binding = registry.binding_for_ref(target_ref)
		target_local = binding.get("local_position", Vector3.INF)
		screen_position = main.world_to_screen(target.pointer_world_position()) if target != null else screen_position
	_check("NORMAL_POINTER_RESOLVES_REAL_TARGET", target != null and not target_ref.is_empty())
	_check("POINTER_TARGET_HAS_AUTHORITY_BINDING", registry.binding_for_ref(target_ref).get("status") == "PASS")
	var movement_metrics_before: Dictionary = main.movement_authority_client.metrics_snapshot()
	var combat_contract_before: Dictionary = main.combat_authority_client.contract_snapshot()
	var move_accept_before: int = _movement_accepts.size()
	var attack_before: int = _attack_projections.size()
	var raw_attack_before: int = _raw_attack_results.size()
	var click_result: Dictionary = main.handle_pointer_event(_right_click(screen_position))
	_check("NORMAL_RIGHT_CLICK_PASS", click_result.get("status") == "PASS", JSON.stringify(click_result))
	_check("NORMAL_RIGHT_CLICK_CHASE_ATTACK", click_result.get("intent") == "CHASE_ATTACK", JSON.stringify(click_result))
	var combat_result: Dictionary = click_result.get("combat_client_result", {}) as Dictionary
	_check("APPROACH_STARTED_FROM_NORMAL_INPUT", combat_result.get("intent") == "CHASE_ATTACK_PENDING", JSON.stringify(combat_result))
	_check("APPROACH_MOVE_TO_POINT_SUBMITTED", (combat_result.get("movement_result", {}) as Dictionary).get("transport_submitted") == true)
	_check("APPROACH_MOVEMENT_ACCEPTED", await _wait_for_size(_movement_accepts, move_accept_before + 1))
	_check("REPRESENTATIVE_ATTACK_RESULT_PROJECTED", await _wait_for_size(_attack_projections, attack_before + 1))
	_check("REPRESENTATIVE_RAW_ATTACK_RESULT_RECEIVED", await _wait_for_size(_raw_attack_results, raw_attack_before + 1))
	var attack_projection: Dictionary = _attack_projections.back()
	var raw_attack: Dictionary = _raw_attack_results.back()
	_check("ATTACK_TARGET_REF_PRESERVED", str(attack_projection.get("target_ref")) == target_ref)
	_check("REQUEST_ATTACK_AUTHORITY_PASS", raw_attack.get("status") == "PASS", JSON.stringify(raw_attack))
	_check("REQUEST_ATTACK_DISTANCE_AUTHORITY_BACKEND", _valid_number(raw_attack.get("distance_m")) and _valid_number(raw_attack.get("range_m")))
	_check("REQUEST_ATTACK_WITHIN_BACKEND_RANGE", float(raw_attack.get("distance_m", INF)) <= float(raw_attack.get("range_m", 0.0)))
	var approach_accept: Dictionary = _movement_accepts.back()
	var p1: Dictionary = approach_accept.get("authority_result_position", {}) as Dictionary
	var authority_target_position: Dictionary = (binding.get("authority_position", {}) as Dictionary).duplicate(true)
	_check("P1_CHANGED_FROM_P0", _authority_distance(p0, p1) > 0.0)
	_check("TARGET_T_UNCHANGED_DURING_APPROACH", _authority_distance(authority_target_position, (registry.binding_for_ref(target_ref).get("authority_position", {}) as Dictionary)) <= 0.00001)
	_check("P1_COHERENT_FOR_INTERACTION", float(raw_attack.get("distance_m", INF)) <= attack_range_m)
	var movement_metrics_after: Dictionary = main.movement_authority_client.metrics_snapshot()
	var combat_contract_after: Dictionary = main.combat_authority_client.contract_snapshot()
	var approach_movement_delta: int = int(movement_metrics_after.get("submitted")) - int(movement_metrics_before.get("submitted"))
	var approach_request_delta: int = int(combat_contract_after.get("authority_approach_requests")) - int(combat_contract_before.get("authority_approach_requests"))
	var approach_command_delta: int = int(combat_contract_after.get("authority_approach_movement_commands")) - int(combat_contract_before.get("authority_approach_movement_commands"))
	_check("ONE_EXPLICIT_APPROACH_REQUEST", approach_request_delta == 1)
	_check("ONE_MOVE_COMMAND_FOR_APPROACH", approach_command_delta == 1 and approach_movement_delta == 1)
	_check("NO_PER_FRAME_APPROACH_COMMAND_SPAM", approach_movement_delta <= 1)

	# A mutated duplicate must not move the Node.
	var latest_snapshot: Dictionary = _snapshots.back()
	var latest_entry: Dictionary = _entry_by_ref(latest_snapshot.get("combat_targets", []) as Array, target_ref)
	var stale_entry: Dictionary = latest_entry.duplicate(true)
	var stale_position: Dictionary = (stale_entry.get("position", {}) as Dictionary).duplicate(true)
	stale_position["iso_x_m"] = float(stale_position.get("iso_x_m")) + 1000.0
	stale_entry["position"] = stale_position
	var node_before_stale: Vector3 = target.global_position
	var stale_result: Dictionary = registry.project_target(latest_snapshot, stale_entry, target, TARGET_KIND)
	_check("STALE_PROJECTION_REJECTED", stale_result.get("reason") == "STALE_OR_DUPLICATE_TARGET_POSITION_PROJECTION")
	_check("STALE_PROJECTION_DID_NOT_MOVE_NODE", target.global_position.distance_to(node_before_stale) <= 0.00001)

	# A different world invalidates every old binding and is never mapped with the old
	# anchor. A subsequent real snapshot re-establishes the actual world binding.
	var wrong_world_snapshot: Dictionary = latest_snapshot.duplicate(true)
	var wrong_identity: Dictionary = (wrong_world_snapshot.get("identity", {}) as Dictionary).duplicate(true)
	wrong_identity["world_instance_id"] = "%s-WRONG" % world_instance_id
	wrong_world_snapshot["identity"] = wrong_identity
	wrong_world_snapshot["snapshot_sequence"] = int(latest_snapshot.get("snapshot_sequence")) + 1
	var wrong_world_result: Dictionary = registry.project_target(wrong_world_snapshot, latest_entry, target, TARGET_KIND)
	_check("WORLD_CHANGE_REJECTED", wrong_world_result.get("reason") == "WORLD_INSTANCE_CHANGED_REQUIRES_FRESH_MAPPER_ANCHOR")
	_check("WORLD_CHANGE_INVALIDATES_OLD_BINDINGS", registry.binding_count() == 0 and not target.visible)
	var snapshots_before_world_restore: int = _snapshots.size()
	_check("REAL_WORLD_REFRESH_REQUESTED", bridge.request_snapshot().get("status") == "PASS")
	_check("REAL_WORLD_REFRESH_RECEIVED", await _wait_for_size(_snapshots, snapshots_before_world_restore + 1))
	_check("REAL_WORLD_BINDING_RESTORED", await _wait_for_binding(target_ref))
	target = main.combat_authority_client.actor_for_ref(target_ref)
	_check("REAL_WORLD_NODE_VISIBLE_AGAIN", target != null and target.visible)

	# Explicit despawn invalidation cancels any pending approach and hides the Node;
	# a fresh complete projection may bind the same real ref again.
	var cancelled_before: int = int(main.combat_authority_client.contract_snapshot().get("invalidated_approaches_cancelled"))
	var target_binding_after_restore: Dictionary = registry.binding_for_ref(target_ref)
	var target_local_after_restore: Vector3 = target_binding_after_restore.get("local_position", Vector3.INF)
	await _establish_out_of_range_position(target_local_after_restore, attack_range_m)
	var pending_probe: Dictionary = main.combat_authority_client.begin_attack(target, "C0_DESPAWN_CANCELLATION_PROBE")
	_check("DESPAWN_PROBE_APPROACH_PENDING", pending_probe.get("intent") == "CHASE_ATTACK_PENDING", JSON.stringify(pending_probe))
	var despawn_result: Dictionary = registry.invalidate_target(target_ref, "EXTERNAL_DESPAWN_PROJECTION", true)
	_check("DESPAWN_INVALIDATES_BINDING", despawn_result.get("invalidated") == true and registry.binding_for_ref(target_ref).get("status") == "REJECTED")
	_check("DESPAWN_HIDES_NODE", not target.visible and not target.selectable)
	_check("DESPAWN_CANCELS_PENDING_APPROACH", main.combat_authority_client.pending_target_ref().is_empty())
	_check("DESPAWN_CANCELLATION_COUNTED", int(main.combat_authority_client.contract_snapshot().get("invalidated_approaches_cancelled")) == cancelled_before + 1)
	var snapshots_before_despawn_restore: int = _snapshots.size()
	_check("DESPAWN_REFRESH_REQUESTED", bridge.request_snapshot().get("status") == "PASS")
	_check("DESPAWN_REFRESH_RECEIVED", await _wait_for_size(_snapshots, snapshots_before_despawn_restore + 1))
	_check("DESPAWN_REBIND_FROM_FRESH_PROJECTION", await _wait_for_binding(target_ref))

	# Reconnect makes the cached binding unavailable. Only the reconnect snapshot may
	# rebind it; no cached ref/position is promoted during transport downtime.
	var snapshots_before_reconnect: int = _snapshots.size()
	_check("CONTROLLED_RECONNECT_STARTED", bridge.record_transport_error("S17_C0_CONTROLLED_RECONNECT").get("status") == "PASS")
	_check("RECONNECT_INVALIDATES_BINDINGS", registry.binding_count() == 0)
	_check("RECONNECT_FRESH_SNAPSHOT_RECEIVED", await _wait_for_size(_snapshots, snapshots_before_reconnect + 1))
	_check("RECONNECT_REBINDS_FROM_FRESH_PROJECTION", await _wait_for_binding(target_ref))
	_check("RECONNECT_RETURNS_AUTHORITY_AVAILABLE", bridge.connection_state().get("authority_session_bound") == true)

	var metrics: Dictionary = registry.metrics_snapshot()
	_check("PROJECTION_UPDATES_COUNTED", int(metrics.get("projection_updates")) >= 4)
	_check("STALE_PROJECTION_COUNTED", int(metrics.get("stale_projections_ignored")) >= 1)
	_check("INVALIDATIONS_COUNTED", int(metrics.get("target_invalidations")) >= 3)
	_check("NO_GAMEPLAY_AUTHORITY_IN_REGISTRY", metrics.get("gameplay_distance_authority") == false)
	_live_evidence = {
		"target_ref": target_ref,
		"target_kind": TARGET_KIND,
		"world_instance_id": world_instance_id,
		"target_authority_position": authority_target_position,
		"target_local_position": target_local,
		"p0_authority": p0,
		"p1_authority": p1,
		"backend_distance_m": raw_attack.get("distance_m"),
		"backend_range_m": raw_attack.get("range_m"),
		"representative_action": "REQUEST_ATTACK",
		"approach_requests": approach_request_delta,
		"approach_movement_commands": approach_command_delta,
		"registry_metrics": metrics,
		"movement_metrics": main.movement_authority_client.metrics_snapshot(),
		"combat_metrics": main.combat_authority_client.contract_snapshot(),
	}
	await _finish({"live_evidence": _live_evidence})


func _on_raw_command_result(result: Dictionary) -> void:
	if str(result.get("command", "")).strip_edges().to_upper() == "REQUEST_ATTACK":
		_raw_attack_results.append(result.duplicate(true))


func _wait_for_spawn_settle() -> bool:
	for frame: int in range(180):
		await get_tree().physics_frame
		if frame >= 10 and main.player.is_on_floor() and absf(main.player.velocity.y) <= 0.01:
			return true
	return false


func _valid_out_of_range_destinations(target_local: Vector3, attack_range_m: float) -> Array[Vector3]:
	var valid: Array[Vector3] = []
	if target_local == Vector3.INF or attack_range_m <= 0.0:
		return valid
	var away := Vector2(
		main.player.global_position.x - target_local.x,
		main.player.global_position.z - target_local.z
	)
	if away.length_squared() <= 0.000001:
		away = Vector2.RIGHT
	away = away.normalized()
	var radius: float = attack_range_m + 1.25
	var directions: Array[Vector2] = [away, Vector2.RIGHT, Vector2.LEFT, Vector2.UP, Vector2.DOWN]
	for direction: Vector2 in directions:
		var candidate := Vector3(
			target_local.x + direction.x * radius,
			target_local.y,
			target_local.z + direction.y * radius
		)
		if main.player.validate_destination(candidate).get("status") == "PASS":
			if not valid.has(candidate):
				valid.append(candidate)
	return valid


func _establish_out_of_range_position(target_local: Vector3, attack_range_m: float) -> Dictionary:
	## Test-only deterministic setup. Every attempted point is a real explicit
	## MOVE_TO_POINT; the first authority result whose Godot presentation also reaches
	## the reprojected point wins. No target transform is ever used as authority input.
	for candidate: Vector3 in _valid_out_of_range_destinations(target_local, attack_range_m):
		var accepts_before: int = _movement_accepts.size()
		var request: Dictionary = main.player.request_move(candidate)
		if request.get("status") != "PASS" or request.get("transport_submitted") != true:
			continue
		if not await _wait_for_size(_movement_accepts, accepts_before + 1):
			main.player.stop_local_prediction()
			continue
		var accept: Dictionary = _movement_accepts.back()
		var reprojected: Variant = accept.get("reprojected_local_position", candidate)
		if await _wait_for_visual_position(reprojected, 12.0):
			return {
				"status": "PASS",
				"destination": candidate,
				"request": request,
				"accept": accept,
				"visual_reconciled": true,
			}
		main.player.stop_local_prediction()
	return {
		"status": "REJECTED",
		"destination": Vector3.INF,
		"request": {},
		"accept": {},
		"visual_reconciled": false,
	}


func _wait_for_visual_position(value: Variant, timeout_s: float) -> bool:
	if not value is Vector3:
		return false
	var desired: Vector3 = value
	var started: int = Time.get_ticks_msec()
	while float(Time.get_ticks_msec() - started) / 1000.0 < timeout_s:
		var horizontal_error := Vector2(
			main.player.global_position.x,
			main.player.global_position.z
		).distance_to(Vector2(desired.x, desired.z))
		if horizontal_error <= main.player.presentation_reconciliation_tolerance_m():
			return true
		await get_tree().physics_frame
	return false


func _wait_for_binding(target_ref: String) -> bool:
	var started: int = Time.get_ticks_msec()
	while float(Time.get_ticks_msec() - started) / 1000.0 < WAIT_TIMEOUT_S:
		if main.interaction_spatial_binding_registry.binding_for_ref(target_ref).get("status") == "PASS":
			return true
		await get_tree().process_frame
	return false


func _wait_for_size(values: Array, expected: int) -> bool:
	var started: int = Time.get_ticks_msec()
	while values.size() < expected and float(Time.get_ticks_msec() - started) / 1000.0 < WAIT_TIMEOUT_S:
		await get_tree().process_frame
	return values.size() >= expected


func _entry_by_ref(entries: Array, target_ref: String) -> Dictionary:
	for value: Variant in entries:
		if value is Dictionary and str((value as Dictionary).get("target_ref", "")) == target_ref:
			return (value as Dictionary).duplicate(true)
	return {}


func _right_click(screen_position: Vector2) -> InputEventMouseButton:
	var event := InputEventMouseButton.new()
	event.button_index = MOUSE_BUTTON_RIGHT
	event.pressed = true
	event.position = screen_position
	event.global_position = screen_position
	return event


func _source_contains_live_value(value: String) -> bool:
	if value.is_empty():
		return false
	for path: String in [
		"res://scripts/interaction/interaction_spatial_binding_registry.gd",
		"res://scripts/interaction/combat_authority_client.gd",
	]:
		if FileAccess.get_file_as_string(path).contains(value):
			return true
	return false


func _valid_authority_position(value: Variant) -> bool:
	if not value is Dictionary:
		return false
	var position: Dictionary = value
	return (
		_valid_number(position.get("iso_x_m"))
		and _valid_number(position.get("iso_y_m"))
		and _valid_number(position.get("altitude_m", 0.0))
	)


func _valid_vector(value: Vector3) -> bool:
	return is_finite(value.x) and is_finite(value.y) and is_finite(value.z)


func _valid_number(value: Variant) -> bool:
	return typeof(value) in [TYPE_INT, TYPE_FLOAT] and is_finite(float(value))


func _authority_distance(a: Dictionary, b: Dictionary) -> float:
	if not _valid_authority_position(a) or not _valid_authority_position(b):
		return INF
	return Vector2(
		float(a.get("iso_x_m")),
		float(a.get("iso_y_m"))
	).distance_to(Vector2(
		float(b.get("iso_x_m")),
		float(b.get("iso_y_m"))
	))


func _check(label: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if condition:
		return
	_failures.append("%s%s" % [label, ":%s" % detail if not detail.is_empty() else ""])


func _finish(extra: Dictionary = {}) -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "S17_C0_INTERACTION_SPATIAL_BINDING_CONTRACT",
		"target_class": "ENEMY",
		"backend_roundtrip_executed": true,
		"gameplay_authority_in_gdscript": false,
	}
	summary.merge(extra, true)
	print("ANDROMEDA_STAGE17_C0_GATE: %s" % summary["status"])
	print("ANDROMEDA_STAGE17_C0_SUMMARY: %s" % JSON.stringify(summary))
	var linger_seconds: float = _gate_success_linger_seconds()
	if linger_seconds > 0.0:
		await get_tree().create_timer(linger_seconds).timeout
	get_tree().quit(0 if _failures.is_empty() else 1)


func _gate_success_linger_seconds() -> float:
	for argument: String in OS.get_cmdline_user_args():
		if argument.begins_with("--gate-success-linger="):
			return maxf(0.0, float(argument.get_slice("=", 1)))
	return 8.0
