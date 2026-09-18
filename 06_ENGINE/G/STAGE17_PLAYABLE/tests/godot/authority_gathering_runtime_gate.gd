extends Node

const SESSION_REF := "GODOT-AUTHORITY-GATHERING-V080"
const WAIT_TIMEOUT_S := 15.0

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _checks: int = 0
var _failures: Array[String] = []
var _bind_results: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []
var _results: Array[Dictionary] = []
var _rejections: Array[String] = []


func _ready() -> void:
	await _run_gate()


func _run_gate() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_check("SESSION_AUTOLOAD", session != null)
	_check("BRIDGE_AUTOLOAD", bridge != null)
	_check("MAIN_GATHERING_CLIENT", main != null and main.gathering_client != null)
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
		_results.append(result.duplicate(true))
	)
	bridge.command_rejected.connect(func(reason: String) -> void:
		_rejections.append(reason)
	)

	if session.has_active_session():
		session.revoke_session()
	_check("LOCAL_SESSION_BIND", session.bind_session(SESSION_REF).get("status") == "PASS")
	_check("AUTHORITY_BIND_STARTED", bridge.bind_authoritative_session().get("status") == "PASS")
	if not await _wait_for_size(_bind_results, 1):
		_failures.append("AUTHORITY_BIND_TIMEOUT")
		await _finish()
		return
	if not await _wait_for_size(_snapshots, 1):
		_failures.append("INITIAL_SNAPSHOT_TIMEOUT")
		await _finish()
		return

	var initial: Dictionary = _snapshots.back()
	var enabled: Array = _bind_results[0].get("enabled_commands", [])
	_check("REQUEST_GATHER_ENABLED", enabled.has("REQUEST_GATHER"), JSON.stringify(enabled))
	_check("CONFIRM_SETTLE_ENABLED", enabled.has("CONFIRM_DROP_SETTLED"), JSON.stringify(enabled))
	_check("SNAPSHOT_SERVER_AUTHORITATIVE", initial.get("server_authoritative") == true)
	_check("RESOURCE_LIST_PRESENT", initial.get("resources") is Array)
	_check("GATHERING_CATALOG_PRESENT", initial.get("gathering_nodes") is Array)
	var kinds: Dictionary = {}
	for entry_value: Variant in initial.get("resources", []):
		if entry_value is Dictionary:
			kinds[str((entry_value as Dictionary).get("resource_kind", ""))] = true
	_check("FIVE_STATIC_RESOURCE_KINDS", kinds.keys().size() == 5)
	for expected_kind: String in ["TREE", "ROCK", "ORE", "FLORA", "AGRICULTURE"]:
		_check("RESOURCE_KIND_%s" % expected_kind, kinds.has(expected_kind))

	var tree_entry: Dictionary = _resource_entry(initial, "TREE")
	_check("TREE_AUTHORITY_TARGET", str(tree_entry.get("target_ref", "")).begins_with("GTH-"))
	if not await _wait_for_resource(str(tree_entry.get("target_ref", ""))):
		_failures.append("TREE_RESOURCE_PROJECTION_TIMEOUT")
		await _finish()
		return
	var tree := main.gathering_client.resource_for_ref(str(tree_entry.get("target_ref", "")))
	_check("TREE_PROJECTED_IN_REAL_MAIN", tree != null)
	if tree == null:
		await _finish()
		return
	# The scenario must be built against a player node that has stopped moving.
	# Measured: for the first physics frames after spawn the controller is still
	# settling the node onto the terrain and drifting horizontally (observed the node
	# leaving 0.750 m and reaching 1.551 m within three frames), so a tree placed
	# relative to the player before that lands outside interaction_range_m. This gate
	# previously only passed when another gate had run first and absorbed that settle,
	# which made it depend on execution order.
	_check(
		"GATHERING_PLAYER_INTERACTION_STATE_CLEAN",
		await _await_player_node_settled(),
		"player=%s" % JSON.stringify(_v(main.player.global_position))
	)
	tree.global_position = main.player.global_position + Vector3(0.75, 0.0, 0.0)
	await _wait_physics_frames(3)
	var initial_range_m: float = main.player.global_position.distance_to(tree.interaction_anchor_world_position())
	_check(
		"TREE_INITIAL_RANGE_WITHIN_CONTRACT",
		initial_range_m <= tree.interaction_range_m,
		"distance=%f interaction_range_m=%f player=%s tree=%s" % [
			initial_range_m, tree.interaction_range_m,
			JSON.stringify(_v(main.player.global_position)),
			JSON.stringify(_v(tree.global_position)),
		]
	)
	var local_eval: Dictionary = main.gathering_client.evaluate_gather_candidate(tree)
	_check("TREE_LOCAL_APPROACH_GUARDS_PASS", local_eval.get("status") == "PASS", JSON.stringify(local_eval))
	main.gathering_client.clear_client_request_tracking()
	var result_start: int = _results.size()
	var request: Dictionary = main.gathering_client.begin_gather_interaction(tree, "AUTHORITY_GATE_E")
	_check("TREE_REQUEST_PREPARED", request.get("status") == "PASS", JSON.stringify(request))
	_check("TREE_REQUEST_TRANSPORT_SUBMITTED", request.get("transport_submitted") == true, JSON.stringify(request))
	var params: Dictionary = request.get("intent_envelope", {}).get("envelope", {}).get("params", {})
	_check("TREE_MINIMAL_AUTHORITY_ENVELOPE", params.keys().size() == 2 and params.get("target_ref") == tree.target_ref and params.get("requested_units") == 1, JSON.stringify(params))
	_check("TREE_NO_CLIENT_YIELD_TOOL_DISTANCE", not params.has("yield") and not params.has("tool_instance_ref") and not params.has("physical_distance_m"))
	var tree_result: Dictionary = await _wait_for_command_result("REQUEST_GATHER", tree.target_ref, result_start)
	_check("TREE_GATHER_RESULT_RECEIVED", not tree_result.is_empty())
	_check("TREE_GATHER_CORE_PASS", tree_result.get("status") == "PASS", JSON.stringify(tree_result))
	_check("TREE_YIELD_SERVER_SIDE", tree_result.get("yield_evaluated_server_side") == true)
	_check("TREE_TOOL_SERVER_SIDE", tree_result.get("tool_evaluated_server_side") == true)
	_check("TREE_LOCATION_SERVER_SIDE", tree_result.get("location_evaluated_server_side") == true)
	_check("TREE_DEPLETION_SERVER_SIDE", tree_result.get("depletion_evaluated_server_side") == true)
	_check("TREE_PHYSICAL_WORLD_FIRST", tree_result.get("physical_output", {}).get("physical_world_first") == true)
	_check("TREE_NO_DIRECT_INVENTORY", tree_result.get("direct_to_inventory") == false)
	var tree_drop_ref: String = str(tree_result.get("drop_ref", ""))
	_check("TREE_DROP_REF_CREATED", tree_drop_ref.begins_with("DROP-S16A-"), tree_drop_ref)
	if not await _wait_for_loot(tree_drop_ref):
		_failures.append("TREE_GROUND_LOOT_PROJECTION_TIMEOUT")
		await _finish()
		return
	var tree_loot := main.ground_loot_client.ground_loot_for_ref(tree_drop_ref)
	_check("TREE_GROUND_LOOT_CLIENT_PROJECTED", tree_loot != null)
	_check("TREE_DROP_INITIAL_UNSETTLED", tree_result.get("physical_output", {}).get("settled") == false)
	var settle_result: Dictionary = await _wait_for_command_result("CONFIRM_DROP_SETTLED", tree_drop_ref, result_start)
	var settle_diagnostics: Dictionary = tree_loot.presentation_snapshot() if tree_loot != null else {}
	if tree_loot != null:
		settle_diagnostics["global_position"] = tree_loot.global_position
		settle_diagnostics["freeze"] = tree_loot.freeze
		settle_diagnostics["sleeping"] = tree_loot.sleeping
		settle_diagnostics["linear_velocity"] = tree_loot.linear_velocity
		settle_diagnostics["angular_velocity"] = tree_loot.angular_velocity
	_check("TREE_SETTLE_ROUNDTRIP_RECEIVED", not settle_result.is_empty(), JSON.stringify(settle_diagnostics))
	_check("TREE_SETTLE_STAGE16A_PASS", settle_result.get("status") == "PASS", JSON.stringify(settle_result))
	_check("TREE_SETTLE_FROM_GODOT_PHYSICS", settle_result.get("physics_observation_source") == "GODOT_RIGIDBODY3D")
	if tree_loot != null:
		_check("TREE_AUTHORITATIVE_SETTLED_PROJECTED", await _wait_for_authoritative_settle(tree_loot))

	var replay_start: int = _results.size()
	var replay_ref: String = str(tree_result.get("command_ref", ""))
	_check("TREE_REPLAY_SUBMITTED", bridge.submit_command("REQUEST_GATHER", {"target_ref": tree.target_ref, "requested_units": 1}, replay_ref).get("status") == "PASS")
	var replay: Dictionary = await _wait_for_command_result("REQUEST_GATHER", tree.target_ref, replay_start)
	_check("TREE_REPLAY_SUPPRESSED", replay.get("idempotent_replay") == true and replay.get("replay_suppressed") == true, JSON.stringify(replay))
	_check("TREE_REPLAY_SAME_DROP", replay.get("drop_ref") == tree_drop_ref)

	var catalog: Array = initial.get("gathering_nodes", []) as Array
	var source_expectations := {
		"ROCK": "ORE",
		"ORE": "ORE",
		"FLORA": "FLORA",
		"AGRICULTURE": "AGRICULTURE",
	}
	for visual_kind: String in source_expectations:
		var entry: Dictionary = _resource_entry(initial, visual_kind)
		var out: Dictionary = await _submit_gather_until_output(bridge, str(entry.get("target_ref", "")), "STATIC_%s" % visual_kind, 1)
		_check("%s_AUTHORITY_PASS" % visual_kind, out.get("status") == "PASS", JSON.stringify(out))
		_check("%s_VISUAL_TARGET_KIND" % visual_kind, out.get("resource_kind") == visual_kind)
		_check("%s_PHYSICAL_OUTPUT" % visual_kind, str(out.get("drop_ref", "")).begins_with("DROP-S16A-"))
		_check("%s_OUTPUT_SOURCE_CONTRACT" % visual_kind, out.get("physical_output", {}).get("source_kind") == source_expectations[visual_kind], JSON.stringify(out.get("physical_output", {})))
		_check("%s_NOT_DIRECT_INVENTORY" % visual_kind, out.get("direct_to_inventory") == false)

	var hunting_node: Dictionary = _catalog_entry(catalog, "HUNTING", true)
	var fishing_node: Dictionary = _catalog_entry(catalog, "FISHING", false)
	_check("HUNTING_REAL_NODE_AVAILABLE", not hunting_node.is_empty())
	_check("FISHING_REAL_NODE_AVAILABLE", not fishing_node.is_empty())
	var hunt: Dictionary = await _submit_gather_until_output(bridge, str(hunting_node.get("target_ref", "")), "HUNTING", 12)
	var fish: Dictionary = await _submit_gather_until_output(bridge, str(fishing_node.get("target_ref", "")), "FISHING", 12)
	_check("HUNTING_AUTHORITY_OUTPUT", hunt.get("physical_output", {}).get("source_kind") == "HUNTING", JSON.stringify(hunt))
	_check("FISHING_AUTHORITY_OUTPUT", fish.get("physical_output", {}).get("source_kind") == "FISHING", JSON.stringify(fish))
	_check("HUNTING_NOT_RESOURCE_NODE_FABRICATION", hunt.get("resource_kind") == null)
	_check("FISHING_NOT_RESOURCE_NODE_FABRICATION", fish.get("resource_kind") == null)
	_check("HUNTING_PHYSICAL_BEFORE_INVENTORY", hunt.get("direct_to_inventory") == false)
	_check("FISHING_PHYSICAL_BEFORE_INVENTORY", fish.get("direct_to_inventory") == false)

	var forged_local: Dictionary = bridge.build_command_envelope("REQUEST_GATHER", {
		"target_ref": tree.target_ref,
		"requested_units": 1,
		"inventory_grant": true,
	})
	_check("CLIENT_FORGED_GRANT_REJECTED", forged_local.get("reason") == "CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN")
	var unexpected_start: int = _results.size()
	_check("UNEXPECTED_YIELD_SUBMITTED_FOR_SERVER_REJECTION", bridge.submit_command("REQUEST_GATHER", {"target_ref": tree.target_ref, "requested_units": 1, "yield": 999}, _unique_ref("FORGED_YIELD")).get("status") == "PASS")
	var unexpected: Dictionary = await _wait_for_command_result("REQUEST_GATHER", "", unexpected_start)
	_check("SERVER_REJECTS_CLIENT_YIELD", unexpected.get("reason") == "UNEXPECTED_COMMAND_PARAM", JSON.stringify(unexpected))
	_check("BRIDGE_FINAL_READY", await _wait_for_bridge_ready(bridge))
	_check("DEBUG_REJECTION_ONLY_EXPECTED", _rejections.has("UNEXPECTED_COMMAND_PARAM"))
	_check("NO_GDSCRIPT_GAMEPLAY_AUTHORITY", main.gathering_client.contract_snapshot().get("yield_authority") == false and main.gathering_client.contract_snapshot().get("inventory_authority") == false)
	await _finish()


func _await_player_node_settled() -> bool:
	## Hold until the player node stops moving. The controller settles the node onto
	## the terrain over the first physics frames after spawn; building a distance
	## scenario before that finishes is what made this gate order-dependent.
	var stable: int = 0
	var previous: Vector3 = main.player.global_position
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		await get_tree().physics_frame
		var current: Vector3 = main.player.global_position
		if current.distance_to(previous) <= 0.000001:
			stable += 1
			if stable >= 20:
				return true
		else:
			stable = 0
		previous = current
	return false


func _v(vector: Vector3) -> Array:
	return [snappedf(vector.x, 0.000001), snappedf(vector.y, 0.000001), snappedf(vector.z, 0.000001)]


func _resource_entry(snapshot: Dictionary, resource_kind: String) -> Dictionary:
	for value: Variant in snapshot.get("resources", []):
		if value is Dictionary and str((value as Dictionary).get("resource_kind", "")) == resource_kind:
			return (value as Dictionary).duplicate(true)
	return {}


func _catalog_entry(catalog: Array, activity: String, require_non_predator: bool) -> Dictionary:
	for value: Variant in catalog:
		if not value is Dictionary:
			continue
		var entry: Dictionary = value
		if str(entry.get("activity_type", "")) != activity:
			continue
		if require_non_predator and str(entry.get("source_role", "")) == "PREDATOR":
			continue
		return entry.duplicate(true)
	return {}


func _submit_gather_until_output(bridge: AndromedaRuntimeBridge, target_ref: String, label: String, max_attempts: int) -> Dictionary:
	for attempt: int in range(max_attempts):
		var start: int = _results.size()
		var submitted: Dictionary = bridge.submit_command(
			"REQUEST_GATHER",
			{"target_ref": target_ref, "requested_units": 1},
			_unique_ref("%s_%02d" % [label, attempt])
		)
		if submitted.get("status") != "PASS":
			return submitted
		var out: Dictionary = await _wait_for_command_result("REQUEST_GATHER", target_ref, start)
		if out.is_empty():
			return {"status": "REJECTED", "reason": "RESULT_TIMEOUT"}
		if out.get("drop_ref") != null and not str(out.get("drop_ref", "")).is_empty():
			return out
	return {"status": "REJECTED", "reason": "NO_PHYSICAL_OUTPUT_AFTER_ATTEMPTS"}


func _wait_for_command_result(command: String, target_ref: String, start_index: int) -> Dictionary:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		for index: int in range(start_index, _results.size()):
			var result: Dictionary = _results[index]
			if str(result.get("command", "")) != command:
				continue
			if not target_ref.is_empty() and str(result.get("target_ref", "")) != target_ref:
				continue
			return result.duplicate(true)
		await get_tree().process_frame
	return {}


func _wait_for_resource(target_ref: String) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		if main.gathering_client.resource_for_ref(target_ref) != null:
			return true
		await get_tree().process_frame
	return false


func _wait_for_loot(target_ref: String) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		if main.ground_loot_client.ground_loot_for_ref(target_ref) != null:
			return true
		await get_tree().process_frame
	return false


func _wait_for_authoritative_settle(loot: AndromedaGroundLoot) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		if loot != null and is_instance_valid(loot) and loot.is_pickup_settled():
			return true
		await get_tree().process_frame
	return false


func _wait_for_bridge_ready(bridge: AndromedaRuntimeBridge) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		if bridge.connection_state().get("state") == AndromedaRuntimeBridge.STATE_READY:
			return true
		await get_tree().process_frame
	return false


func _wait_for_size(values: Array, expected: int) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while values.size() < expected and Time.get_ticks_usec() < deadline:
		await get_tree().process_frame
	return values.size() >= expected


func _wait_physics_frames(count: int) -> void:
	for _index: int in range(count):
		await get_tree().physics_frame


func _unique_ref(label: String) -> String:
	return "GODOT-GATHER-%s-%d" % [label, Time.get_ticks_usec()]


func _check(label: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if condition:
		return
	_failures.append(label if detail.is_empty() else "%s:%s" % [label, detail])


func _finish() -> void:
	await _wait_physics_frames(2)
	var passed: int = _checks - _failures.size()
	var status: String = "PASS" if _failures.is_empty() else "FAIL"
	var summary := {
		"gate": "AUTHORITY_GATHERING_ROUNDTRIP",
		"status": status,
		"checks": _checks,
		"passed": passed,
		"failed": _failures.size(),
		"failures": _failures,
		"backend": "REAL_STAGE16A_AUTHORITY",
		"fixture_authority": false,
		"rock_output_contract_gap": "STAGE16A_MINING_OUTPUT_IS_ORE",
	}
	print("ANDROMEDA_STAGE16B_AUTHORITY_GATHERING_SUMMARY: ", JSON.stringify(summary))
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_AUTHORITY_GATHERING_GATE: PASS")
		# Keep the completed process observable long enough for the real Editor Bridge
		# debugger collector to read the marker before controlled shutdown.
		await get_tree().create_timer(8.0).timeout
		get_tree().quit(0)
	else:
		push_error("ANDROMEDA_STAGE16B_AUTHORITY_GATHERING_GATE: FAIL %s" % JSON.stringify(_failures))
		await get_tree().create_timer(8.0).timeout
		get_tree().quit(1)
