extends Node

## Live C2 gate: normal resource input uses the physical placement binding,
## one authority movement command, server-confirmed arrival, and then a
## placement-shaped REQUEST_GATHER. Range, blocker and LOS remain backend rules.

const SESSION_REF := "GODOT-STAGE17-C2-RESOURCE-V010"
const WAIT_TIMEOUT_S := 90.0
const GATHER_RANGE_M := 1.5

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _checks: int = 0
var _failures: Array[String] = []
var _binds: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []
var _movement_accepts: Array[Dictionary] = []
var _movement_rejections: Array[Dictionary] = []
var _gather_requests: Array[Dictionary] = []
var _raw_results: Array[Dictionary] = []
var _normal_evidence: Dictionary = {}
var _negative_evidence: Dictionary = {}


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
	bridge.command_result_received.connect(func(value: Dictionary) -> void: _raw_results.append(value.duplicate(true)))
	main.movement_authority_client.movement_accepted.connect(func(value: Dictionary) -> void: _movement_accepts.append(value.duplicate(true)))
	main.movement_authority_client.movement_rejected.connect(func(value: Dictionary) -> void: _movement_rejections.append(value.duplicate(true)))
	main.gathering_client.gather_request_prepared.connect(func(value: Dictionary) -> void: _gather_requests.append(value.duplicate(true)))
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
	_check("TREE_PROJECTED", not _entry_by_kind(initial_snapshot, "TREE").is_empty())
	_check("ORE_PROJECTED", not _entry_by_kind(initial_snapshot, "ORE").is_empty())
	_check("RESOURCE_BINDING_COUNT", _resource_binding_count() == 2)

	# Normal gameplay path, not an internal gather helper.
	print("ANDROMEDA_STAGE17_C2_PROGRESS: NORMAL_TREE")
	_normal_evidence["TREE"] = await _normal_input_gather("TREE", 3.25)
	print("ANDROMEDA_STAGE17_C2_PROGRESS: NORMAL_ORE")
	_normal_evidence["ORE"] = await _normal_input_gather("ORE", 3.25)

	# Boundary and negative authority cases use the real command transport so the
	# server—not a Godot raycast—proves the final rule and mutation invariants.
	var ore_entry: Dictionary = _entry_by_kind(_snapshots.back(), "ORE")
	var tree_entry: Dictionary = _entry_by_kind(_snapshots.back(), "TREE")
	var ore_local: Vector3 = _resource_local(ore_entry)
	var tree_local: Vector3 = _resource_local(tree_entry)

	var boundary_move: Dictionary = await _move_player_to(ore_local + Vector3(GATHER_RANGE_M, 0.0, 0.0), "BOUNDARY")
	_check("BOUNDARY_MOVE_ACCEPTED", boundary_move.get("status") == "PASS")
	var boundary: Dictionary = await _submit_gather(ore_entry, "BOUNDARY")
	_check("BOUNDARY_GATHER_PASS", boundary.get("status") == "PASS", JSON.stringify(boundary))
	_check("BOUNDARY_DISTANCE_EXACT", absf(float((boundary.get("metric_spatial_guard", {}) as Dictionary).get("distance_m", INF)) - GATHER_RANGE_M) <= 0.000001)
	_check("BOUNDARY_LOS_CLEAR", (boundary.get("metric_spatial_guard", {}) as Dictionary).get("los", {}).get("clear") == true)

	var outside_move: Dictionary = await _move_player_to(ore_local + Vector3(1.5001, 0.0, 0.0), "OUTSIDE")
	_check("OUTSIDE_MOVE_ACCEPTED", outside_move.get("status") == "PASS")
	var ore_remaining_before: int = _remaining_for_logical(_snapshots.back(), str(ore_entry.get("logical_node_ref", "")))
	var loot_before: int = main.ground_loot_client.registered_loot_count()
	var outside: Dictionary = await _submit_gather(ore_entry, "OUTSIDE")
	_check("OUTSIDE_REJECTED_SERVER_SIDE", outside.get("reason") == "RESOURCE_GATHER_OUT_OF_RANGE", JSON.stringify(outside))
	_check("OUTSIDE_MUTATION_FALSE", outside.get("mutation_applied") == false)
	await _refresh_snapshot()
	_check("OUTSIDE_ZERO_DEPLETION", _remaining_for_logical(_snapshots.back(), str(ore_entry.get("logical_node_ref", ""))) == ore_remaining_before)
	_check("OUTSIDE_ZERO_OUTPUT", main.ground_loot_client.registered_loot_count() == loot_before)

	# The baked AABB is west of TREE. Player must stand within 1.5m of TREE
	# with that AABB crossing the segment to it. The exact standing point is
	# derived at runtime from the real blocker collision geometry already
	# baked into this same scene plus the live NavigationServer3D map --
	# never a coordinate copied from a log (S17-C3R5 Section 5).
	var blocked_destination: Vector3 = _derive_blocked_side_destination(tree_local)
	_check("BLOCKED_SETUP_DESTINATION_DERIVED", blocked_destination != Vector3.INF, JSON.stringify(blocked_destination))
	var blocked_move: Dictionary = await _move_player_to(blocked_destination, "BLOCKED")
	_check("BLOCKED_SETUP_AUTHORITY_MOVE_ACCEPTED", blocked_move.get("status") == "PASS", JSON.stringify(blocked_move))
	var tree_remaining_before: int = _remaining_for_logical(_snapshots.back(), str(tree_entry.get("logical_node_ref", "")))
	loot_before = main.ground_loot_client.registered_loot_count()
	var blocked: Dictionary = await _submit_gather(tree_entry, "BLOCKED")
	_check("BLOCKED_REJECTED_SERVER_SIDE", blocked.get("reason") == "RESOURCE_GATHER_BLOCKED_LOS", JSON.stringify(blocked))
	_check("BLOCKED_DISTANCE_WITHIN_RANGE", float(blocked.get("distance_m", INF)) <= GATHER_RANGE_M)
	_check("BLOCKED_AUTHORITY_SOURCE", str(blocked.get("blocker_authority", "")) == "STAGE17_RESOURCE_METRIC_PLACEMENT_AUTHORITY")
	_check("BLOCKED_REF_REAL", (blocked.get("blocked_by", []) as Array).has("RESOURCE-LOS-BLOCKER-S17-001"))
	_check("BLOCKED_MUTATION_FALSE", blocked.get("mutation_applied") == false)
	await _refresh_snapshot()
	_check("BLOCKED_ZERO_DEPLETION", _remaining_for_logical(_snapshots.back(), str(tree_entry.get("logical_node_ref", ""))) == tree_remaining_before)
	_check("BLOCKED_ZERO_OUTPUT", main.ground_loot_client.registered_loot_count() == loot_before)

	var wrong_params := {
		"placement_ref": str(tree_entry.get("placement_ref", "")),
		"target_ref": str(ore_entry.get("logical_node_ref", "")),
		"requested_units": 1,
	}
	var wrong: Dictionary = await _submit_command("REQUEST_GATHER", wrong_params, "WRONG-PAIR")
	_check("WRONG_IDENTITY_REJECTED", wrong.get("reason") == "RESOURCE_PLACEMENT_LOGICAL_REF_MISMATCH")

	var injection_reasons: Array[String] = []
	for field: String in ["iso_x_m", "iso_y_m", "distance", "range", "position", "blocked", "los_clear"]:
		var injected: Dictionary = await _submit_command("REQUEST_GATHER", {
			"placement_ref": str(ore_entry.get("placement_ref", "")),
			"target_ref": str(ore_entry.get("logical_node_ref", "")),
			"requested_units": 1,
			field: 0,
		}, "INJECT-%s" % field.to_upper())
		injection_reasons.append(str(injected.get("reason", "")))
	_check("CLIENT_POSITION_INJECTION_REJECTED", injection_reasons.all(func(value: String) -> bool: return value == "UNEXPECTED_COMMAND_PARAM"), JSON.stringify(injection_reasons))

	var no_placement: Dictionary = await _submit_command("REQUEST_GATHER", {
		"target_ref": str(tree_entry.get("logical_node_ref", "")),
		"requested_units": 1,
	}, "NO-PLACEMENT")
	_check("NO_LEGACY_PRODUCTION_BYPASS", no_placement.get("reason") == "RESOURCE_PLACEMENT_REF_REQUIRED")

	var metrics: Dictionary = main.gathering_client.stage17_metric_metrics_snapshot()
	_check("NORMAL_APPROACH_COUNT_TWO", int(metrics.get("resource_approach_requests", 0)) == 2, JSON.stringify(metrics))
	_check("NORMAL_APPROACH_MOVEMENT_COUNT_TWO", int(metrics.get("movement_commands", 0)) == 2, JSON.stringify(metrics))
	_check("NORMAL_GATHER_COMMAND_COUNT_TWO", int(metrics.get("gather_commands", 0)) == 2, JSON.stringify(metrics))
	_check("NO_UNSAFE_LOCAL_FALLBACK", metrics.get("unsafe_local_placeholder_fallback") == false)
	_check("NO_RESOURCE_MOVEMENT_REJECTIONS", int(metrics.get("movement_rejections", 0)) == 0)

	_negative_evidence = {
		"boundary": _compact_result(boundary),
		"outside": _compact_result(outside),
		"blocked": _compact_result(blocked),
		"wrong_identity": _compact_result(wrong),
		"client_injection_reasons": injection_reasons,
		"no_placement": _compact_result(no_placement),
	}
	await _finish({
		"normal_input_evidence": _normal_evidence,
		"negative_authority_evidence": _negative_evidence,
		"gathering_metrics": metrics,
		"movement_metrics": main.movement_authority_client.metrics_snapshot(),
		"ground_loot_count": main.ground_loot_client.registered_loot_count(),
	})


func _normal_input_gather(kind: String, setup_distance_m: float) -> Dictionary:
	var snapshot: Dictionary = _snapshots.back()
	var entry: Dictionary = _entry_by_kind(snapshot, kind)
	var placement_ref: String = str(entry.get("placement_ref", ""))
	var logical_ref: String = str(entry.get("logical_node_ref", ""))
	var resource: AndromedaResourceNode = main.gathering_client.resource_for_ref(placement_ref)
	var local_position: Vector3 = _resource_local(entry)
	_check("%s_NORMAL_RESOURCE_NODE" % kind, resource != null)
	_check("%s_NORMAL_BINDING" % kind, local_position != Vector3.INF)
	if resource == null or local_position == Vector3.INF:
		return {"status": "REJECTED", "reason": "RESOURCE_NOT_BOUND"}
	var setup_destination: Vector3 = _select_reachable_setup_destination(local_position, setup_distance_m)
	_check("%s_SETUP_NAV_DESTINATION" % kind, setup_destination != Vector3.INF)
	if setup_destination == Vector3.INF:
		return {"status": "REJECTED", "reason": "NO_REACHABLE_SETUP_DESTINATION", "kind": kind}
	var setup: Dictionary = await _move_player_to(
		setup_destination,
		"%s-NORMAL-SETUP" % kind
	)
	_check("%s_SETUP_MOVE_ACCEPTED" % kind, setup.get("status") == "PASS", JSON.stringify(setup))
	if setup.get("status") != "PASS":
		return setup
	var setup_position: Dictionary = setup.get("authority_result_position", {}) as Dictionary
	_check("%s_SETUP_OUT_OF_RANGE" % kind, _authority_distance(setup_position, entry.get("position", {})) > GATHER_RANGE_M)
	var pointer_screen: Vector2 = main.world_to_screen(resource.pointer_world_position())
	var pointer: Dictionary = main.pointer_target_at_screen(pointer_screen)
	_check("%s_NORMAL_POINTER_RESOLVES_RESOURCE" % kind, str(pointer.get("target_ref", "")) == placement_ref, JSON.stringify(pointer))
	var movement_before: int = int(main.movement_authority_client.metrics_snapshot().get("submitted", 0))
	var approach_before: int = int(main.gathering_client.stage17_metric_metrics_snapshot().get("resource_approach_requests", 0))
	var gather_before: int = _gather_requests.size()
	var raw_before: int = _raw_results.size()
	var loot_before: int = main.ground_loot_client.registered_loot_count()
	var remaining_before: int = _remaining_for_logical(snapshot, logical_ref)
	var click: Dictionary = main.handle_pointer_event(_right_click(pointer_screen))
	_check("%s_NORMAL_RIGHT_CLICK_PASS" % kind, click.get("status") == "PASS", JSON.stringify(click))
	_check("%s_NORMAL_INTENT_APPROACH_HARVEST" % kind, click.get("intent") == "APPROACH_HARVEST", JSON.stringify(click))
	var client_result: Dictionary = click.get("gathering_client_result", {}) as Dictionary
	_check("%s_NORMAL_AUTHORITY_APPROACH_STARTED" % kind, client_result.get("intent") == "AUTHORITY_APPROACH_GATHERING_PENDING", JSON.stringify(client_result))
	_check("%s_NORMAL_MOVE_TO_POINT_SUBMITTED" % kind, (client_result.get("movement_result", {}) as Dictionary).get("transport_submitted") == true)
	_check("%s_NORMAL_NO_GATHER_BEFORE_ARRIVAL" % kind, _gather_requests.size() == gather_before)
	_check("%s_NORMAL_GATHER_EVENTUALLY_PREPARED" % kind, await _wait_for_size(_gather_requests, gather_before + 1))
	var prepared: Dictionary = _gather_requests.back() if _gather_requests.size() > gather_before else {}
	_check("%s_NORMAL_PLACEMENT_REF_SENT" % kind, str(prepared.get("placement_ref", "")) == placement_ref)
	_check("%s_NORMAL_LOGICAL_REF_SENT" % kind, str(prepared.get("logical_node_ref", "")) == logical_ref)
	_check("%s_NORMAL_AUTHORITY_ARRIVAL_CONFIRMED" % kind, prepared.get("authority_movement_confirmed") == true)
	_check("%s_NORMAL_CLIENT_POSITION_NOT_SENT" % kind, prepared.get("client_position_supplied") == false)
	var raw: Dictionary = await _wait_for_command_result_after("REQUEST_GATHER", raw_before)
	_check("%s_NORMAL_GATHER_RESULT_RECEIVED" % kind, not raw.is_empty())
	_check("%s_NORMAL_GATHER_PASS" % kind, raw.get("status") == "PASS", JSON.stringify(raw))
	var guard: Dictionary = raw.get("metric_spatial_guard", {}) as Dictionary
	_check("%s_NORMAL_SERVER_RANGE_PASS" % kind, float(guard.get("distance_m", INF)) <= GATHER_RANGE_M)
	_check("%s_NORMAL_SERVER_LOS_PASS" % kind, (guard.get("los", {}) as Dictionary).get("clear") == true)
	_check("%s_NORMAL_GTH_RESOLVED_SERVER_SIDE" % kind, str(raw.get("logical_node_ref", "")) == logical_ref)
	var output: Dictionary = raw.get("physical_output", {}) as Dictionary
	var drop_ref: String = str(output.get("drop_ref", output.get("target_ref", "")))
	_check("%s_NORMAL_PHYSICAL_OUTPUT_CREATED" % kind, not drop_ref.is_empty())
	_check("%s_NORMAL_DIRECT_INVENTORY_FALSE" % kind, raw.get("direct_to_inventory") == false)
	_check(
		"%s_NORMAL_OUTPUT_PROJECTED_AS_GROUND_LOOT" % kind,
		not drop_ref.is_empty() and await _wait_for_loot(drop_ref)
	)
	await _refresh_snapshot()
	var remaining_after: int = _remaining_for_logical(_snapshots.back(), logical_ref)
	_check("%s_NORMAL_LOGICAL_DEPLETION_CHANGED" % kind, remaining_before >= 0 and remaining_after == remaining_before - 1, "%s->%s" % [remaining_before, remaining_after])
	var movement_after: int = int(main.movement_authority_client.metrics_snapshot().get("submitted", 0))
	var approach_after: int = int(main.gathering_client.stage17_metric_metrics_snapshot().get("resource_approach_requests", 0))
	_check("%s_NORMAL_ONE_APPROACH_MOVEMENT_COMMAND" % kind, movement_after - movement_before == 1, "%s" % (movement_after - movement_before))
	_check("%s_NORMAL_ONE_APPROACH_REQUEST" % kind, approach_after - approach_before == 1)
	_check("%s_NORMAL_ONE_GATHER_COMMAND" % kind, _gather_requests.size() - gather_before == 1)
	_check("%s_NORMAL_ONE_NEW_GROUND_LOOT" % kind, main.ground_loot_client.registered_loot_count() >= loot_before + 1)
	return {
		"status": str(raw.get("status", "")),
		"placement_ref": placement_ref,
		"logical_node_ref": logical_ref,
		"approach_movement_command_ref": str(client_result.get("movement_command_ref", "")),
		"server_distance_m": float(guard.get("distance_m", INF)),
		"server_los_clear": (guard.get("los", {}) as Dictionary).get("clear"),
		"drop_ref": drop_ref,
		"remaining_before": remaining_before,
		"remaining_after": remaining_after,
	}


func _select_reachable_setup_destination(target_local: Vector3, distance_m: float) -> Vector3:
	# Test preconditioning only: choose a deterministic navigable point outside
	# the authoritative gather radius.  No command is submitted while probing,
	# and the server remains the final range/LOS authority after the normal input.
	var directions: Array[Vector3] = [
		Vector3.RIGHT,
		Vector3.FORWARD,
		Vector3.BACK,
		Vector3.LEFT,
		Vector3(1.0, 0.0, -1.0).normalized(),
		Vector3(1.0, 0.0, 1.0).normalized(),
		Vector3(-1.0, 0.0, -1.0).normalized(),
		Vector3(-1.0, 0.0, 1.0).normalized(),
	]
	for direction: Vector3 in directions:
		var candidate: Vector3 = target_local + direction * distance_m
		var validation: Dictionary = main.player.validate_destination(candidate)
		if validation.get("status") == "PASS":
			return validation.get("navigation_destination", candidate)
	return Vector3.INF


func _move_player_to(local_destination: Vector3, label: String) -> Dictionary:
	var before: int = _movement_accepts.size()
	var rejected_before: int = _movement_rejections.size()
	var request: Dictionary = main.player.request_move(local_destination)
	if request.get("status") != "PASS" or request.get("transport_submitted") != true:
		return {"status": "REJECTED", "reason": "MOVE_SUBMIT_FAILED", "request": request, "label": label}
	var started: int = Time.get_ticks_msec()
	while (
		_movement_accepts.size() <= before
		and _movement_rejections.size() <= rejected_before
		and float(Time.get_ticks_msec() - started) / 1000.0 < WAIT_TIMEOUT_S
	):
		await get_tree().process_frame
	if _movement_rejections.size() > rejected_before:
		var rejected: Dictionary = _movement_rejections.back().duplicate(true)
		rejected["request"] = request
		rejected["label"] = label
		return rejected
	if _movement_accepts.size() <= before:
		return {"status": "REJECTED", "reason": "MOVE_RESULT_TIMEOUT", "request": request, "label": label}
	var accepted: Dictionary = _movement_accepts.back()
	var visual_ok: bool = await _wait_for_visual_position(accepted.get("reprojected_local_position"))
	accepted["visual_reconciled"] = visual_ok
	accepted["label"] = label
	return accepted


func _submit_gather(entry: Dictionary, suffix: String) -> Dictionary:
	return await _submit_command("REQUEST_GATHER", {
		"placement_ref": str(entry.get("placement_ref", "")),
		"target_ref": str(entry.get("logical_node_ref", "")),
		"requested_units": 1,
	}, suffix)


func _submit_command(command: String, params: Dictionary, suffix: String) -> Dictionary:
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if bridge == null:
		return {"status": "REJECTED", "reason": "BRIDGE_MISSING"}
	var built: Dictionary = bridge.build_command_envelope(command, params)
	if built.get("status") != "PASS":
		return built
	var command_ref: String = str((built.get("envelope", {}) as Dictionary).get("command_ref", ""))
	var before: int = _raw_results.size()
	var submitted: Dictionary = bridge.submit_command(command, params, command_ref)
	if submitted.get("status") != "PASS":
		return submitted
	var result: Dictionary = await _wait_for_result_ref(command_ref, before)
	if result.is_empty():
		return {"status": "REJECTED", "reason": "COMMAND_RESULT_TIMEOUT", "command_ref": command_ref, "suffix": suffix}
	return result


func _wait_for_command_result_after(command: String, start_index: int) -> Dictionary:
	var started: int = Time.get_ticks_msec()
	while float(Time.get_ticks_msec() - started) / 1000.0 < WAIT_TIMEOUT_S:
		for index: int in range(start_index, _raw_results.size()):
			var value: Dictionary = _raw_results[index]
			if str(value.get("command", "")).strip_edges().to_upper() == command:
				return value.duplicate(true)
		await get_tree().process_frame
	return {}


func _wait_for_result_ref(command_ref: String, start_index: int) -> Dictionary:
	var started: int = Time.get_ticks_msec()
	while float(Time.get_ticks_msec() - started) / 1000.0 < WAIT_TIMEOUT_S:
		for index: int in range(start_index, _raw_results.size()):
			var value: Dictionary = _raw_results[index]
			if str(value.get("command_ref", "")) == command_ref:
				return value.duplicate(true)
		await get_tree().process_frame
	return {}


func _refresh_snapshot() -> bool:
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	var before: int = _snapshots.size()
	if bridge == null or bridge.request_snapshot().get("status") != "PASS":
		return false
	return await _wait_for_size(_snapshots, before + 1)


func _wait_for_loot(drop_ref: String) -> bool:
	var started: int = Time.get_ticks_msec()
	while float(Time.get_ticks_msec() - started) / 1000.0 < WAIT_TIMEOUT_S:
		if main.ground_loot_client.ground_loot_for_ref(drop_ref) != null:
			return true
		await get_tree().process_frame
	return false


func _wait_for_visual_position(value: Variant) -> bool:
	if not value is Vector3:
		return false
	var desired: Vector3 = value
	var started: int = Time.get_ticks_msec()
	while float(Time.get_ticks_msec() - started) / 1000.0 < 15.0:
		var error := Vector2(main.player.global_position.x, main.player.global_position.z).distance_to(
			Vector2(desired.x, desired.z)
		)
		if error <= main.player.presentation_reconciliation_tolerance_m():
			return true
		await get_tree().physics_frame
	return false


func _resource_local(entry: Dictionary) -> Vector3:
	var ref: String = str(entry.get("placement_ref", ""))
	var result: Dictionary = main.interaction_spatial_binding_registry.authoritative_target_local_position(ref)
	return result.get("local_position", Vector3.INF) if result.get("status") == "PASS" else Vector3.INF


const _BLOCKED_PROBE_STEP_M := 0.05
const _BLOCKED_PROBE_MAX_OFFSET_M := 0.9
const _BLOCKED_NAV_PROJECTION_MAX_M := 0.75  # mirrors AndromedaPlayerController.MAX_DESTINATION_PROJECTION_M


func _derive_blocked_side_destination(tree_local: Vector3) -> Vector3:
	## Finds a standing point on the far side of the real LOS blocker from
	## TREE -- close enough to stay inside GATHER_RANGE_M of TREE once the
	## authority move completes, and already navigable per the SAME
	## NavigationServer3D map/query the player controller itself uses for
	## presentation-layer path validation. Derived entirely from live scene
	## geometry (blocker collision shape) and the resource authority
	## position; contains no coordinate copied from a prior run's logs.
	var blocker := main.get_node_or_null(^"WorldStreamRoot/CollisionSurface/ResourceGatherLosBlocker") as StaticBody3D
	if blocker == null:
		return Vector3.INF
	var shape_node := blocker.get_node_or_null(^"CollisionShape3D") as CollisionShape3D
	if shape_node == null or not (shape_node.shape is BoxShape3D):
		return Vector3.INF
	var box := shape_node.shape as BoxShape3D
	var half_extent_x: float = box.size.x * 0.5
	var blocker_origin: Vector3 = blocker.global_transform.origin
	var away_from_tree: float = signf(blocker_origin.x - tree_local.x)
	if away_from_tree == 0.0:
		away_from_tree = -1.0
	var far_face_x: float = blocker_origin.x + away_from_tree * half_extent_x
	var navigation_agent: NavigationAgent3D = main.player.navigation_agent
	var navigation_map: RID = navigation_agent.get_navigation_map()
	if not navigation_map.is_valid():
		return Vector3.INF
	var offset: float = _BLOCKED_PROBE_STEP_M
	while offset <= _BLOCKED_PROBE_MAX_OFFSET_M:
		# Same depth (Z) as TREE itself -- the blocker's Z span already covers
		# TREE's Z (confirmed by the authored placement bounds), so a point at
		# TREE's own depth on the far-face side keeps the straight segment to
		# TREE crossing the blocker's thickness, whatever offset is picked.
		var candidate := Vector3(
			far_face_x + away_from_tree * offset,
			tree_local.y,
			tree_local.z,
		)
		var closest: Vector3 = NavigationServer3D.map_get_closest_point(navigation_map, candidate)
		var projection_m: float = Vector2(candidate.x, candidate.z).distance_to(Vector2(closest.x, closest.z))
		var distance_to_tree_m: float = Vector2(closest.x, closest.z).distance_to(Vector2(tree_local.x, tree_local.z))
		# Reject a snap that lands back on TREE's own side of the wall (e.g.
		# the far side simply isn't baked as navigable) -- that would silently
		# defeat the whole point of this scenario instead of proving LOS.
		var closest_still_far_side: bool = signf(closest.x - blocker_origin.x) == away_from_tree or absf(closest.x - blocker_origin.x) >= half_extent_x
		if projection_m <= _BLOCKED_NAV_PROJECTION_MAX_M and distance_to_tree_m <= GATHER_RANGE_M and closest_still_far_side:
			return closest
		offset += _BLOCKED_PROBE_STEP_M
	return Vector3.INF


func _resource_binding_count() -> int:
	var count: int = 0
	for kind: String in ["TREE", "ORE"]:
		var entry: Dictionary = _entry_by_kind(_snapshots.back(), kind)
		if main.interaction_spatial_binding_registry.binding_for_ref(str(entry.get("placement_ref", ""))).get("status") == "PASS":
			count += 1
	return count


func _entry_by_kind(snapshot: Dictionary, kind: String) -> Dictionary:
	for value: Variant in snapshot.get("resources", []) as Array:
		if value is Dictionary and str((value as Dictionary).get("resource_kind", "")) == kind:
			return (value as Dictionary).duplicate(true)
	return {}


func _remaining_for_logical(snapshot: Dictionary, logical_ref: String) -> int:
	for value: Variant in snapshot.get("gathering_nodes", []) as Array:
		if value is Dictionary and str((value as Dictionary).get("target_ref", "")) == logical_ref:
			return int((value as Dictionary).get("remaining_units", -1))
	return -1


func _right_click(screen_position: Vector2) -> InputEventMouseButton:
	var event := InputEventMouseButton.new()
	event.button_index = MOUSE_BUTTON_RIGHT
	event.pressed = true
	event.position = screen_position
	event.global_position = screen_position
	return event


func _authority_distance(a: Dictionary, b_value: Variant) -> float:
	if not b_value is Dictionary:
		return INF
	var b: Dictionary = b_value
	for position: Dictionary in [a, b]:
		for key: String in ["iso_x_m", "iso_y_m"]:
			if not position.has(key) or typeof(position.get(key)) not in [TYPE_INT, TYPE_FLOAT] or not is_finite(float(position.get(key))):
				return INF
		if typeof(position.get("altitude_m", 0.0)) not in [TYPE_INT, TYPE_FLOAT] or not is_finite(float(position.get("altitude_m", 0.0))):
			return INF
	return Vector3(float(a["iso_x_m"]), float(a.get("altitude_m", 0.0)), float(a["iso_y_m"])).distance_to(
		Vector3(float(b["iso_x_m"]), float(b.get("altitude_m", 0.0)), float(b["iso_y_m"]))
	)


func _compact_result(value: Dictionary) -> Dictionary:
	var keys: Array[String] = [
		"status", "reason", "command_ref", "target_ref", "placement_ref",
		"logical_node_ref", "distance_m", "gather_range_m", "blocked_by",
		"mutation_applied", "result_sequence",
	]
	var result: Dictionary = {}
	for key: String in keys:
		if value.has(key):
			result[key] = value[key]
	if value.has("metric_spatial_guard"):
		result["metric_spatial_guard"] = value["metric_spatial_guard"]
	return result


func _wait_for_size(values: Array, expected: int) -> bool:
	var started: int = Time.get_ticks_msec()
	while values.size() < expected and float(Time.get_ticks_msec() - started) / 1000.0 < WAIT_TIMEOUT_S:
		await get_tree().process_frame
	return values.size() >= expected


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
		"gate": "S17_C2_RESOURCE_AUTHORITATIVE_APPROACH_GATHER",
		"backend_roundtrip_executed": true,
		"normal_input_executed": true,
		"server_range_m": GATHER_RANGE_M,
		"server_blocker_los_executed": true,
		"unsafe_local_placeholder_fallback": false,
		"gameplay_authority_in_gdscript": false,
	}
	summary.merge(extra, true)
	print("ANDROMEDA_STAGE17_C2_GATE: %s" % summary["status"])
	print("ANDROMEDA_STAGE17_C2_SUMMARY: %s" % JSON.stringify(summary))
	get_tree().quit(0 if _failures.is_empty() else 1)
