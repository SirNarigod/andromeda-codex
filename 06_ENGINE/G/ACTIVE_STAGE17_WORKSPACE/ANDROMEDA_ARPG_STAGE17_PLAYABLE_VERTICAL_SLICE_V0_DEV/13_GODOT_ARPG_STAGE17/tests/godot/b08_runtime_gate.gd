extends Node

const RESOURCE_NODE_SCENE: PackedScene = preload("res://scenes/interaction/ResourceNode.tscn")
const SESSION_REF := "B08-GATE-SESSION"
const WRONG_SESSION_REF := "B08-GATE-WRONG-SESSION"

var _checks: int = 0
var _failures: Array[String] = []
var _resource_snapshot_sequence: int = 0
var _output_event_sequence: int = 0
var _ground_loot_snapshot_sequence: int = 0
var _temporary_nodes: Array[Node] = []
var _projected_output_refs: Array[String] = []

@onready var main: AndromedaMainRuntime = $AndromedaARPG
@onready var player: AndromedaPlayerController = $AndromedaARPG/ActorRoot/Player
@onready var camera_rig: AndromedaIsometricCameraRig = $AndromedaARPG/IsometricCameraRig
@onready var hud: AndromedaHUDController = $AndromedaARPG/UILayer/MinimalHUD
@onready var gathering: AndromedaGatheringClient = $AndromedaARPG/GatheringClient
@onready var pickup_client: AndromedaGroundLootPickupClient = $AndromedaARPG/GroundLootPickupClient
@onready var resource_root: Node3D = $AndromedaARPG/WorldStreamRoot/B03InteractionTargets
@onready var loot_root: Node3D = $AndromedaARPG/GroundLootRoot
@onready var streaming: AndromedaStreamingManager = $AndromedaARPG/WorldStreamRoot/TerrainFoundation/CELL_STREAMING
@onready var tree_resource: AndromedaResourceNode = $AndromedaARPG/WorldStreamRoot/B03InteractionTargets/TreeB03
@onready var rock_resource: AndromedaResourceNode = $AndromedaARPG/WorldStreamRoot/B03InteractionTargets/RockB03
@onready var ore_resource: AndromedaResourceNode = $AndromedaARPG/WorldStreamRoot/B03InteractionTargets/OreB03
@onready var flora_resource: AndromedaResourceNode = $AndromedaARPG/WorldStreamRoot/B03InteractionTargets/FloraB03
@onready var agriculture_resource: AndromedaResourceNode = $AndromedaARPG/WorldStreamRoot/B03InteractionTargets/AgricultureB08
@onready var enemy: AndromedaInteractionTarget = $AndromedaARPG/ActorRoot/EnemyB03


func _ready() -> void:
	await _run_gate()


func _check(check_id: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(check_id if detail.is_empty() else "%s:%s" % [check_id, detail])


func _run_gate() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	var router := get_node_or_null("/root/InputRouter") as AndromedaInputRouter
	_check("AUTOLOAD_CLIENT_SESSION", session != null)
	_check("AUTOLOAD_ANDROMEDA_BRIDGE", bridge != null)
	_check("AUTOLOAD_INPUT_ROUTER", router != null)
	if session == null or bridge == null or router == null:
		await _finish()
		return
	var bind_result: Dictionary = session.bind_session(SESSION_REF)
	_check("SESSION_BOUND", bind_result.get("status") == "PASS", JSON.stringify(bind_result))
	_check("PROJECT_LABEL_B08_THROUGH_B11", str(ProjectSettings.get_setting("application/config/name")) in ["Andromeda ARPG Stage16B B08", "Andromeda ARPG Stage16B B09", "Andromeda ARPG Stage16B B10", "Andromeda ARPG Stage16B B11"])
	_check("MAIN_SCENE_PRESERVED", str(ProjectSettings.get_setting("application/run/main_scene")) == "res://scenes/Main.tscn")
	_check("BACKEND_URL_UNCHANGED", bridge.server_url() == "http://127.0.0.1:8000")
	_check("NAVIGATION_READY", await _wait_for_navigation(240))
	_test_architecture_and_authority(bridge)
	_test_resource_types_and_external_state()
	await _test_selection_context_input_and_approach()
	await _test_range_blocker_path_and_stale_targets()
	await _test_output_pipeline()
	_test_streaming_integration()
	await _test_b05_b06_b07_interactions()
	_test_stamina_projection_only()
	await _cleanup_temporary_nodes()
	await _finish()


func _test_architecture_and_authority(bridge: AndromedaRuntimeBridge) -> void:
	var probe := RESOURCE_NODE_SCENE.instantiate() as AndromedaResourceNode
	_check("RESOURCE_NODE_SCENE_INSTANTIATES", probe != null)
	_check("RESOURCE_NODE_ROOT_STATIC_BODY", probe != null and probe.is_class("StaticBody3D"))
	_check("RESOURCE_NODE_COLLISION_SHAPE", probe != null and probe.has_node("CollisionShape3D"))
	_check("RESOURCE_NODE_VISUAL_ROOT", probe != null and probe.has_node("VisualRoot"))
	_check("RESOURCE_NODE_INTERACTION_SENSOR", probe != null and probe.has_node("InteractionSensor"))
	_check("RESOURCE_NODE_DROP_ANCHOR", probe != null and probe.has_node("DropAnchor"))
	_check("RESOURCE_NODE_PLACEHOLDER_VISUAL", probe != null and probe.has_node("VisualRoot/PlaceholderMesh"))
	_check("RESOURCE_NODE_NO_FINAL_ART", probe != null and probe.get_node("VisualRoot/PlaceholderMesh") is MeshInstance3D)
	if probe != null:
		var probe_contract: Dictionary = probe.contract_snapshot()
		_check("RESOURCE_NODE_MANIFEST_CHILDREN_EXACT", probe_contract.get("required_children") == ["CollisionShape3D", "VisualRoot", "InteractionSensor", "DropAnchor"])
		_check("RESOURCE_NODE_LAYER_32", int(probe.get("collision_layer")) == 32)
		_check("RESOURCE_SENSOR_LAYER_8", int((probe.get_node("InteractionSensor") as Area3D).collision_layer) == 8)
		_check("RESOURCE_KINDS_CONTRACT", probe_contract.get("resource_kinds") == ["TREE", "ROCK", "ORE", "FLORA", "AGRICULTURE"])
		_check("RESOURCE_NO_LOCAL_YIELD", probe_contract.get("local_yield_calculation") == false)
		_check("RESOURCE_NO_LOCAL_TOOL_RULE", probe_contract.get("local_tool_validation") == false)
		_check("RESOURCE_NO_LOCAL_STAMINA", probe_contract.get("local_stamina_mutation") == false)
		_check("RESOURCE_NO_LOCAL_DEPLETION", probe_contract.get("local_depletion_decision") == false)
		_check("RESOURCE_NO_LOCAL_RESPAWN", probe_contract.get("local_respawn_timer") == false)
		_check("RESOURCE_NO_LOCAL_INVENTORY", probe_contract.get("local_inventory_grant") == false)
		probe.free()
	var contract: Dictionary = gathering.contract_snapshot()
	_check("GATHER_CLIENT_PRESENT", main.contract_snapshot().get("gathering_client_present") == true)
	_check("GATHER_FLOW_ENDS_GROUND_LOOT", contract.get("flow", []).back() == "GROUND_LOOT_B07")
	_check("GATHER_OUTPUT_DELIVERY_B07_ONLY", contract.get("output_delivery") == "GROUND_LOOT_B07_ONLY")
	_check("GATHER_NO_DIRECT_INVENTORY", contract.get("direct_inventory_delivery") == false)
	_check("GATHER_NO_PLAYER_REF", contract.get("player_ref_supplied_by_client") == false)
	_check("GATHER_NO_YIELD_AUTHORITY", contract.get("yield_authority") == false)
	_check("GATHER_NO_QUANTITY_AUTHORITY", contract.get("quantity_authority") == false)
	_check("GATHER_NO_TOOL_AUTHORITY", contract.get("tool_rule_authority") == false)
	_check("GATHER_NO_STAMINA_AUTHORITY", contract.get("stamina_authority") == false)
	_check("GATHER_NO_DEPLETION_AUTHORITY", contract.get("depletion_authority") == false)
	_check("GATHER_NO_RESPAWN_AUTHORITY", contract.get("respawn_authority") == false)
	_check("GATHER_NO_INVENTORY_AUTHORITY", contract.get("inventory_authority") == false)
	_check("GATHER_NO_XP_AUTHORITY", contract.get("xp_authority") == false)
	_check("GATHER_NO_PROFESSION_AUTHORITY", contract.get("profession_authority") == false)
	_check("GATHER_NO_ECONOMY_AUTHORITY", contract.get("economy_authority") == false)
	_check("GATHER_NO_LIVING_PARALLEL", contract.get("living_parallel_implementation") == false)
	_check("GATHER_NO_BACKEND_SUBSTITUTE", contract.get("backend_substitute") == false)
	_check("GATHER_NO_INVENTED_ENDPOINT", contract.get("invented_endpoint") == false)
	_check("GATHER_SOURCE_KINDS_EXACT", contract.get("resource_source_kinds") == ["TREE", "ROCK", "ORE", "FLORA", "AGRICULTURE"])
	_check("GATHER_OUTPUT_SOURCES_EXACT", contract.get("universal_b08_output_sources") == ["TREE", "ROCK", "ORE", "FLORA", "AGRICULTURE", "HUNTING", "FISHING", "ENEMY"])
	_check("NO_CALCULATE_YIELD_METHOD", not gathering.has_method("calculate_yield"))
	_check("NO_VALIDATE_TOOL_AUTHORITY_METHOD", not gathering.has_method("validate_tool_authoritatively"))
	_check("NO_CONSUME_STAMINA_METHOD", not gathering.has_method("consume_stamina"))
	_check("NO_DEPLETE_RESOURCE_METHOD", not gathering.has_method("deplete_resource"))
	_check("NO_SCHEDULE_RESPAWN_METHOD", not gathering.has_method("schedule_respawn"))
	_check("NO_GRANT_INVENTORY_METHOD", not gathering.has_method("grant_inventory"))
	_check("BRIDGE_REJECTS_PLAYER_REF", bridge.build_command_envelope("REQUEST_GATHER", {
		"target_ref": "RESOURCE-SECURITY",
		"player_ref": "CLIENT-FORGED",
	}).get("status") == "REJECTED")
	_check("BRIDGE_REJECTS_INVENTORY_GRANT", bridge.build_command_envelope("REQUEST_GATHER", {
		"target_ref": "RESOURCE-SECURITY",
		"inventory_grant": {"item_ref": "FORGED"},
	}).get("status") == "REJECTED")
	var non_authoritative_snapshot: Dictionary = gathering.project_resource_snapshot({
		"server_authoritative": false,
		"session_ref": SESSION_REF,
		"snapshot_sequence": 0,
		"resources": [],
	})
	_check("NON_AUTHORITATIVE_RESOURCE_SNAPSHOT_REJECTED", non_authoritative_snapshot.get("reason") == "NON_AUTHORITATIVE_RESOURCE_SNAPSHOT")
	var non_authoritative_output: Dictionary = gathering.project_physical_output_event({
		"server_authoritative": false,
		"session_ref": SESSION_REF,
		"event_ref": "NONAUTH",
		"event_sequence": 0,
		"source_kind": "TREE",
		"source_ref": tree_resource.target_ref,
		"outputs": [],
	})
	_check("NON_AUTHORITATIVE_OUTPUT_REJECTED", non_authoritative_output.get("reason") == "NON_AUTHORITATIVE_PHYSICAL_OUTPUT_EVENT")


func _test_resource_types_and_external_state() -> void:
	var resources: Array[AndromedaResourceNode] = _main_resources()
	var expected_kinds: Array[String] = ["TREE", "ROCK", "ORE", "FLORA", "AGRICULTURE"]
	_check("MAIN_RESOURCE_COUNT_FIVE", resources.size() == 5)
	_check("CLIENT_DISCOVERS_FIVE_RESOURCES", gathering.registered_resource_count() >= 5)
	var entries: Array[Dictionary] = []
	for resource: AndromedaResourceNode in resources:
		entries.append(_resource_entry(resource, "AVAILABLE", "ACTIVE"))
	var initial_snapshot: Dictionary = _next_resource_snapshot(entries)
	var initial_result: Dictionary = gathering.project_resource_snapshot(initial_snapshot)
	_check("INITIAL_RESOURCE_SNAPSHOT_PASS", initial_result.get("status") == "PASS", JSON.stringify(initial_result))
	_check("INITIAL_RESOURCE_SNAPSHOT_ALL_PROJECTED", initial_result.get("projected", []).size() == 5)
	var refs: Dictionary = {}
	for index: int in range(resources.size()):
		var resource: AndromedaResourceNode = resources[index]
		var kind: String = expected_kinds[index]
		var prefix := "RESOURCE_%s" % kind
		_check("%s_SPECIALIZED_COMPONENT" % prefix, resource is AndromedaResourceNode)
		_check("%s_KIND" % prefix, resource.resource_kind == kind)
		_check("%s_TARGET_KIND" % prefix, resource.target_kind == AndromedaInputRouter.HIT_GATHER_NODE)
		_check("%s_TARGET_REF_STABLE" % prefix, not resource.target_ref.is_empty())
		_check("%s_TARGET_REF_UNIQUE" % prefix, not refs.has(resource.target_ref))
		refs[resource.target_ref] = true
		_check("%s_LAYER" % prefix, int(resource.get("collision_layer")) == 32)
		_check("%s_STATE_AVAILABLE" % prefix, resource.projected_state() == AndromedaResourceNode.STATE_AVAILABLE)
		_check("%s_STATE_KNOWN" % prefix, resource.state_is_known())
		_check("%s_STREAM_ACTIVE" % prefix, resource.stream_phase() == AndromedaResourceNode.STREAM_ACTIVE)
		_check("%s_CAN_GATHER" % prefix, resource.can_prepare_gather_intent().get("status") == "PASS")
		_check("%s_DROP_ANCHOR_FINITE" % prefix, resource.drop_anchor_world_position().is_finite())
		_check("%s_REGISTERED_IDENTITY" % prefix, gathering.resource_for_ref(resource.target_ref) == resource)
	var duplicate_snapshot_result: Dictionary = gathering.project_resource_snapshot(initial_snapshot)
	_check("DUPLICATE_RESOURCE_SNAPSHOT_REJECTED", duplicate_snapshot_result.get("reason") == "STALE_OR_DUPLICATE_RESOURCE_SNAPSHOT")
	var stale_snapshot: Dictionary = initial_snapshot.duplicate(true)
	stale_snapshot["snapshot_sequence"] = 0
	_check("OUT_OF_ORDER_RESOURCE_SNAPSHOT_REJECTED", gathering.project_resource_snapshot(stale_snapshot).get("reason") == "STALE_OR_DUPLICATE_RESOURCE_SNAPSHOT")
	var wrong_session_snapshot: Dictionary = initial_snapshot.duplicate(true)
	wrong_session_snapshot["session_ref"] = WRONG_SESSION_REF
	wrong_session_snapshot["snapshot_sequence"] = _resource_snapshot_sequence + 1
	_check("WRONG_SESSION_RESOURCE_SNAPSHOT_REJECTED", gathering.project_resource_snapshot(wrong_session_snapshot).get("reason") == "SESSION_MISMATCH")
	var busy_result: Dictionary = gathering.project_resource_snapshot(_next_resource_snapshot([
		_resource_entry(agriculture_resource, "BUSY", "ACTIVE"),
	]))
	_check("BUSY_STATE_PROJECTION_PASS", busy_result.get("status") == "PASS")
	_check("BUSY_NORMALIZED_IN_PROGRESS", agriculture_resource.projected_state() == AndromedaResourceNode.STATE_IN_PROGRESS)
	var busy_request: Dictionary = gathering.begin_gather_interaction(agriculture_resource, "B08_BUSY_TEST")
	_check("BUSY_CANNOT_REQUEST_GATHER", busy_request.get("reason") == "RESOURCE_BUSY")
	_check("BUSY_CREATES_NO_INFLIGHT", not gathering.has_inflight_request(agriculture_resource.target_ref))
	var unavailable_result: Dictionary = gathering.project_resource_snapshot(_next_resource_snapshot([
		_resource_entry(agriculture_resource, "DEPLETED", "ACTIVE"),
	]))
	_check("DEPLETED_STATE_PROJECTION_PASS", unavailable_result.get("status") == "PASS")
	_check("DEPLETED_NORMALIZED_UNAVAILABLE", agriculture_resource.projected_state() == AndromedaResourceNode.STATE_UNAVAILABLE)
	var unavailable_request: Dictionary = gathering.begin_gather_interaction(agriculture_resource, "B08_UNAVAILABLE_TEST")
	_check("UNAVAILABLE_CANNOT_REQUEST_GATHER", unavailable_request.get("reason") == "RESOURCE_UNAVAILABLE")
	_check("UNAVAILABLE_GENERATES_NO_LOOT", _projected_output_refs.is_empty())
	var restore_result: Dictionary = gathering.project_resource_snapshot(_next_resource_snapshot([
		_resource_entry(agriculture_resource, "ACTIVE", "ACTIVE"),
	]))
	_check("EXTERNAL_REPLENISHMENT_PROJECTION_PASS", restore_result.get("status") == "PASS")
	_check("EXTERNAL_REPLENISHMENT_AVAILABLE", agriculture_resource.projected_state() == AndromedaResourceNode.STATE_AVAILABLE)
	_check("NO_LOCAL_RESPAWN_TIMER_NODE", not agriculture_resource.has_node("RespawnTimer"))
	_check("NO_LOCAL_RESPAWN_TIMER_CLIENT", not gathering.has_method("advance_respawn_timer"))
	var direct_wrong_session: Dictionary = tree_resource.apply_authoritative_projection(
		_resource_entry(tree_resource, "AVAILABLE", "ACTIVE"),
		WRONG_SESSION_REF,
		999,
		true
	)
	_check("NODE_WRONG_SESSION_REJECTED", direct_wrong_session.get("reason") == "RESOURCE_STATE_SESSION_MISMATCH")


func _test_selection_context_input_and_approach() -> void:
	gathering.clear_client_request_tracking()
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	await _wait_physics_frames(2)
	var movement: Dictionary = player.request_move(Vector3(-5.5, 0.0, 5.5))
	_check("PRE_SELECTION_MOVEMENT_STARTED", movement.get("status") == "PASS")
	var destination_before: Vector3 = player.requested_destination()
	var left_result: Dictionary = main.handle_pointer_event(_mouse_button(
		MOUSE_BUTTON_LEFT,
		main.world_to_screen(tree_resource.pointer_world_position())
	))
	_check("LEFT_RESOURCE_SELECT_PASS", left_result.get("status") == "PASS", JSON.stringify(left_result))
	_check("LEFT_RESOURCE_SELECT_INTENT", left_result.get("intent") == "SELECT_TARGET")
	_check("LEFT_RESOURCE_TARGET_REF", left_result.get("target_ref") == tree_resource.target_ref)
	_check("LEFT_RESOURCE_SELECTION_STABLE", main.selected_target_ref() == tree_resource.target_ref)
	_check("LEFT_RESOURCE_NO_GATHER_REQUEST", not left_result.has("gathering_client_result"))
	_check("LEFT_RESOURCE_MOVEMENT_PRESERVED", player.has_destination())
	_check("LEFT_RESOURCE_DESTINATION_PRESERVED", player.requested_destination().is_equal_approx(destination_before))
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	await _wait_physics_frames(2)
	var player_before_right: Vector3 = player.global_position
	var right_result: Dictionary = main.handle_pointer_event(_mouse_button(
		MOUSE_BUTTON_RIGHT,
		main.world_to_screen(tree_resource.pointer_world_position())
	))
	_check("RIGHT_RESOURCE_CONTEXT_PASS", right_result.get("status") == "PASS", JSON.stringify(right_result))
	_check("RIGHT_RESOURCE_CONTEXT_INTENT", right_result.get("intent") == "APPROACH_HARVEST")
	_check("RIGHT_RESOURCE_CONTEXT_CLICK_ONLY", right_result.get("input_mode") == "CLICK_ONLY")
	var right_gather: Dictionary = right_result.get("gathering_client_result", {})
	_check("RIGHT_RESOURCE_GATHER_CLIENT_PASS", right_gather.get("status") == "PASS", JSON.stringify(right_gather))
	_check("RIGHT_RESOURCE_APPROACH_PENDING", right_gather.get("intent") == "APPROACH_GATHERING_PENDING")
	_check("RIGHT_RESOURCE_NO_REMOTE_GATHER", right_gather.get("remote_gathering") == false)
	_check("RIGHT_RESOURCE_MOVEMENT_STARTED", player.has_destination())
	_check("RIGHT_RESOURCE_NO_TELEPORT", player.global_position.distance_to(player_before_right) < 0.05)
	_check("RIGHT_RESOURCE_TARGET_STABLE", main.selected_target_ref() == tree_resource.target_ref)
	_check("RIGHT_RESOURCE_PENDING_REF_CORRECT", gathering.pending_target_ref() == tree_resource.target_ref)
	gathering.clear_client_request_tracking()
	player.stop_local_prediction()
	player.global_position = tree_resource.global_position + Vector3(tree_resource.interaction_range_m, 0.0, 0.0)
	await _wait_physics_frames(2)
	var e_result: Dictionary = main.handle_action_event(_key_event(KEY_E))
	_check("E_SELECTED_RESOURCE_PASS", e_result.get("status") == "PASS", JSON.stringify(e_result))
	_check("E_SELECTED_RESOURCE_INTENT", e_result.get("intent") == "CONTEXT_INTERACT_SELECTED")
	var e_gather: Dictionary = e_result.get("gathering_client_result", {})
	_check("E_GATHER_REQUEST_PREPARED", e_gather.get("intent") == "REQUEST_GATHER", JSON.stringify(e_gather))
	_check("E_EXACT_RANGE_ACCEPTED", is_equal_approx(float(e_gather.get("physical_distance_m", -1.0)), tree_resource.interaction_range_m))
	_check("E_TARGET_REF_CORRECT", e_gather.get("target_ref") == tree_resource.target_ref)
	_check("E_RESOURCE_KIND_CORRECT", e_gather.get("resource_kind") == "TREE")
	_check("E_REQUEST_INFLIGHT", gathering.has_inflight_request(tree_resource.target_ref))
	_check("E_BACKEND_NOT_FABRICATED", e_gather.get("transport_submitted") == false)
	var built: Dictionary = e_gather.get("intent_envelope", {})
	var envelope: Dictionary = built.get("envelope", {})
	var params: Dictionary = envelope.get("params", {})
	_check("GATHER_ENVELOPE_COMMAND", envelope.get("command") == "REQUEST_GATHER")
	_check("GATHER_ENVELOPE_SESSION", envelope.get("session_ref") == SESSION_REF)
	_check("GATHER_ENVELOPE_TARGET", params.get("target_ref") == tree_resource.target_ref)
	_check(
		"GATHER_ENVELOPE_KIND",
		not params.has("resource_kind") and params.get("requested_units") == 1,
		"resource kind is resolved server-side from target_ref"
	)
	_check("GATHER_ENVELOPE_NO_PLAYER_REF", not params.has("player_ref"))
	_check("GATHER_ENVELOPE_NO_TOOL_DECISION", not params.has("tool_valid") and not params.has("required_tool"))
	_check("GATHER_ENVELOPE_NO_YIELD", not params.has("yield") and not params.has("quantity"))
	_check("GATHER_ENVELOPE_NO_STAMINA_MUTATION", not params.has("stamina_cost") and not params.has("stamina_delta"))
	_check("GATHER_ENVELOPE_NO_INVENTORY", not params.has("inventory") and not params.has("inventory_grant"))
	var duplicate_request: Dictionary = gathering.begin_gather_interaction(tree_resource, "CLICK_SPAM")
	_check("GATHER_CLICK_SPAM_DEDUPLICATED", duplicate_request.get("reason") == "GATHER_REQUEST_ALREADY_INFLIGHT")
	_check("GATHER_CLICK_SPAM_SINGLE_INFLIGHT", gathering.inflight_request_count() == 1)
	var non_authoritative_result: Dictionary = gathering.project_gathering_result({
		"server_authoritative": false,
		"session_ref": SESSION_REF,
		"target_ref": tree_resource.target_ref,
		"result_sequence": 0,
		"status": "PASS",
	})
	_check("NON_AUTHORITATIVE_GATHER_RESULT_REJECTED", non_authoritative_result.get("reason") == "NON_AUTHORITATIVE_GATHERING_RESULT")
	var wrong_session_result: Dictionary = gathering.project_gathering_result({
		"server_authoritative": true,
		"session_ref": WRONG_SESSION_REF,
		"target_ref": tree_resource.target_ref,
		"result_sequence": 0,
		"status": "PASS",
	})
	_check("WRONG_SESSION_GATHER_RESULT_REJECTED", wrong_session_result.get("reason") == "SESSION_MISMATCH")
	var accepted_result: Dictionary = gathering.project_gathering_result({
		"server_authoritative": true,
		"session_ref": SESSION_REF,
		"target_ref": tree_resource.target_ref,
		"result_sequence": 0,
		"status": "PASS",
	})
	_check("EXTERNAL_GATHER_ACCEPTED_PROJECTED", accepted_result.get("status") == "PASS")
	_check("GATHER_ACCEPTED_SPAWNS_NO_OUTPUT_BY_ITSELF", accepted_result.get("output_spawned") == false)
	_check("GATHER_ACCEPTED_NO_LOCAL_YIELD", accepted_result.get("yield_calculated_locally") == false)
	_check("GATHER_ACCEPTED_CLEARS_INFLIGHT", not gathering.has_inflight_request(tree_resource.target_ref))
	var duplicate_result: Dictionary = gathering.project_gathering_result({
		"server_authoritative": true,
		"session_ref": SESSION_REF,
		"target_ref": tree_resource.target_ref,
		"result_sequence": 0,
		"status": "PASS",
	})
	_check("DUPLICATE_GATHER_RESULT_REJECTED", duplicate_result.get("reason") == "STALE_OR_DUPLICATE_GATHERING_RESULT")


func _test_range_blocker_path_and_stale_targets() -> void:
	gathering.clear_client_request_tracking()
	player.stop_local_prediction()
	player.global_position = tree_resource.global_position + Vector3(0.5, 0.0, 0.0)
	await _wait_physics_frames(2)
	var near_result: Dictionary = gathering.begin_gather_interaction(tree_resource, "NEAR_TEST")
	_check("NEAR_RESOURCE_REQUEST_PASS", near_result.get("intent") == "REQUEST_GATHER", JSON.stringify(near_result))
	_check("NEAR_RESOURCE_PHYSICAL_DISTANCE", float(near_result.get("physical_distance_m", INF)) <= tree_resource.interaction_range_m)
	var rejected_result: Dictionary = gathering.project_gathering_result({
		"server_authoritative": true,
		"session_ref": SESSION_REF,
		"target_ref": tree_resource.target_ref,
		"result_sequence": 1,
		"status": "REJECTED",
		"reason": "TOOL_REJECTED_EXTERNALLY",
	})
	_check("EXTERNAL_TOOL_REJECTION_PROJECTED", rejected_result.get("status") == "PASS")
	_check("EXTERNAL_TOOL_REJECTION_NO_LOCAL_OUTPUT", rejected_result.get("output_spawned") == false)
	gathering.clear_client_request_tracking()
	player.stop_local_prediction()
	player.global_position = tree_resource.global_position + Vector3(tree_resource.interaction_range_m + 0.0001, 0.0, 0.0)
	await _wait_physics_frames(2)
	var beyond_result: Dictionary = gathering.begin_gather_interaction(tree_resource, "JUST_BEYOND_TEST")
	_check("JUST_BEYOND_RANGE_APPROACHES", beyond_result.get("intent") == "APPROACH_GATHERING_PENDING", JSON.stringify(beyond_result))
	_check("JUST_BEYOND_RANGE_NO_REQUEST", not gathering.has_inflight_request(tree_resource.target_ref))
	_check("JUST_BEYOND_RANGE_PHYSICAL_NOT_SCREEN", float(beyond_result.get("physical_distance_m", 0.0)) > tree_resource.interaction_range_m)
	gathering.clear_client_request_tracking()
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	var far_result: Dictionary = gathering.begin_gather_interaction(tree_resource, "FAR_TEST")
	_check("FAR_RESOURCE_APPROACHES", far_result.get("intent") == "APPROACH_GATHERING_PENDING", JSON.stringify(far_result))
	_check("FAR_RESOURCE_PATH_PRESENT", far_result.get("movement_result", {}).get("path_point_count", 0) > 0)
	_check("FAR_RESOURCE_NOT_GATHERED_REMOTELY", far_result.get("gather_requested") == false)
	gathering.clear_client_request_tracking()
	player.stop_local_prediction()
	player.global_position = tree_resource.global_position + Vector3(1.0, 0.0, 0.0)
	var blocker := StaticBody3D.new()
	blocker.name = "B08GatherBlocker"
	blocker.collision_layer = 128
	blocker.collision_mask = 0
	blocker.position = tree_resource.global_position + Vector3(0.5, 0.55, 0.0)
	var blocker_shape := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(0.18, 1.1, 0.9)
	blocker_shape.shape = box
	blocker.add_child(blocker_shape)
	main.add_child(blocker)
	_temporary_nodes.append(blocker)
	await _wait_physics_frames(2)
	var blocker_probe: Dictionary = gathering.blocker_probe(tree_resource)
	_check("GATHER_BLOCKER_DETECTED", blocker_probe.get("blocked") == true, JSON.stringify(blocker_probe))
	_check("GATHER_BLOCKER_LAYER_128", int(blocker_probe.get("collision_layer", 0)) == 128)
	var blocked_result: Dictionary = gathering.begin_gather_interaction(tree_resource, "BLOCKER_TEST")
	_check("GATHER_THROUGH_BLOCKER_REJECTED", blocked_result.get("reason") == "GATHER_BLOCKED_BY_COLLISION", JSON.stringify(blocked_result))
	_check("BLOCKER_GENERATES_NO_INFLIGHT", not gathering.has_inflight_request(tree_resource.target_ref))
	blocker.collision_layer = 0
	await _wait_physics_frames(1)
	var invalid_path_resource: AndromedaResourceNode = await _create_test_resource(
		"RESOURCE-B08-INVALID-PATH",
		"ROCK",
		Vector3(18.0, 0.0, 18.0)
	)
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	player.stop_local_prediction()
	var invalid_path_result: Dictionary = gathering.begin_gather_interaction(invalid_path_resource, "INVALID_PATH_TEST")
	_check("INVALID_PATH_REJECTED", invalid_path_result.get("reason") == "RESOURCE_PATH_INVALID", JSON.stringify(invalid_path_result))
	_check("INVALID_PATH_NO_TELEPORT", player.global_position.is_equal_approx(Vector3(-7.0, 0.0, 0.0)))
	_check("INVALID_PATH_NO_INFLIGHT", not gathering.has_inflight_request(invalid_path_resource.target_ref))
	var obstacle_resource: AndromedaResourceNode = await _create_test_resource(
		"RESOURCE-B08-OBSTACLE-ROUTE",
		"TREE",
		Vector3(4.0, 0.0, 0.0)
	)
	player.global_position = Vector3(-4.0, 0.0, 0.0)
	player.stop_local_prediction()
	var open_path: PackedVector3Array = player.preview_path(gathering.approach_destination_for(obstacle_resource))
	_check("RESOURCE_OTHER_SIDE_OBSTACLE_PATH_VALID", open_path.size() >= 3, str(open_path))
	var obstacle_begin: Dictionary = gathering.begin_gather_interaction(obstacle_resource, "OBSTACLE_ROUTE_TEST")
	_check("RESOURCE_OTHER_SIDE_OBSTACLE_APPROACH_PASS", obstacle_begin.get("status") == "PASS", JSON.stringify(obstacle_begin))
	_check("RESOURCE_OTHER_SIDE_OBSTACLE_NO_TELEPORT", player.global_position.is_equal_approx(Vector3(-4.0, 0.0, 0.0)))
	gathering.clear_client_request_tracking()
	player.stop_local_prediction()
	var open_uses_north: bool = false
	var open_uses_south: bool = false
	for path_point: Vector3 in open_path:
		open_uses_north = open_uses_north or path_point.z >= 4.7
		open_uses_south = open_uses_south or path_point.z <= -4.7
	_check("PATH_CHANGE_INITIAL_DETOUR", open_uses_north or open_uses_south, str(open_path))
	var close_result: Dictionary = main.set_b04_base_route_closure(open_uses_north, not open_uses_north)
	_check("PATH_CHANGE_APPLIED", close_result.get("status") == "PASS")
	await _wait_physics_frames(12)
	var replanned_path: PackedVector3Array = player.preview_path(gathering.approach_destination_for(obstacle_resource))
	_check("PATH_CHANGE_REPLANS", not replanned_path.is_empty())
	var replanned_uses_opposite: bool = false
	for path_point: Vector3 in replanned_path:
		replanned_uses_opposite = replanned_uses_opposite or (
			path_point.z <= -4.7 if open_uses_north else path_point.z >= 4.7
		)
	_check("PATH_CHANGE_DIFFERS", replanned_uses_opposite, str(replanned_path))
	main.set_b04_base_route_closure(false, false)
	await _wait_physics_frames(8)
	var removable: AndromedaResourceNode = await _create_test_resource(
		"RESOURCE-B08-REMOVED-DURING-APPROACH",
		"FLORA",
		Vector3(-2.0, 0.0, 8.0)
	)
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	player.stop_local_prediction()
	var removal_begin: Dictionary = gathering.begin_gather_interaction(removable, "REMOVE_DURING_APPROACH")
	_check("REMOVAL_TEST_APPROACH_PENDING", removal_begin.get("intent") == "APPROACH_GATHERING_PENDING")
	_check("REMOVAL_TEST_PENDING_REF", gathering.pending_target_ref() == removable.target_ref)
	var removal_result: Dictionary = gathering.project_resource_snapshot(_next_resource_snapshot([{
		"target_ref": removable.target_ref,
		"resource_kind": removable.resource_kind,
		"state": "REMOVED",
	}]))
	_check("REMOVED_TARGET_EXTERNAL_PROJECTION_PASS", removal_result.get("status") == "PASS", JSON.stringify(removal_result))
	await _wait_physics_frames(2)
	_check("REMOVED_TARGET_UNREGISTERED", gathering.resource_for_ref("RESOURCE-B08-REMOVED-DURING-APPROACH") == null)
	_check("REMOVED_TARGET_PENDING_CLEARED", gathering.pending_target_ref().is_empty())
	_check("REMOVED_TARGET_TOMBSTONE", not gathering.resource_tombstone("RESOURCE-B08-REMOVED-DURING-APPROACH").is_empty())
	var removed_output: Dictionary = _output_event(
		"FLORA",
		"RESOURCE-B08-REMOVED-DURING-APPROACH",
		[_output_entry("LOOT-B08-REMOVED-SOURCE", "ITEM-FLORA", "FLORA", 1)],
		Vector3.ZERO,
		false
	)
	var removed_output_result: Dictionary = gathering.project_physical_output_event(removed_output)
	_check("REMOVED_SOURCE_OUTPUT_REJECTED", removed_output_result.get("reason") == "RESOURCE_OUTPUT_SOURCE_NOT_FOUND")
	_check("REMOVED_SOURCE_OUTPUT_NOT_SPAWNED", pickup_client.ground_loot_for_ref("LOOT-B08-REMOVED-SOURCE") == null)
	var wrong_target := AndromedaInteractionTarget.new()
	wrong_target.target_ref = "OBJECT-B08-WRONG-TARGET"
	var wrong_target_result: Dictionary = gathering.handle_selected_interaction(wrong_target)
	_check("WRONG_TARGET_KIND_REJECTED", wrong_target_result.get("reason") == "SELECTED_TARGET_NOT_RESOURCE_NODE")
	wrong_target.free()
	var stale_resource: AndromedaResourceNode = await _create_test_resource(
		"RESOURCE-B08-STALE",
		"ORE",
		Vector3(-6.0, 0.0, 6.0)
	)
	stale_resource.queue_free()
	await _wait_physics_frames(2)
	_check("STALE_RESOURCE_REGISTRY_CLEARS", gathering.resource_for_ref("RESOURCE-B08-STALE") == null)


func _test_output_pipeline() -> void:
	var source_cases: Array[Dictionary] = [
		{"kind": "TREE", "source_ref": tree_resource.target_ref, "position": Vector3.ZERO, "item_kind": "MATERIAL", "quantity": 4},
		{"kind": "ROCK", "source_ref": rock_resource.target_ref, "position": Vector3.ZERO, "item_kind": "MINERAL", "quantity": 1},
		{"kind": "ORE", "source_ref": ore_resource.target_ref, "position": Vector3.ZERO, "item_kind": "MINERAL", "quantity": 3},
		{"kind": "FLORA", "source_ref": flora_resource.target_ref, "position": Vector3.ZERO, "item_kind": "FLORA", "quantity": 1},
		{"kind": "AGRICULTURE", "source_ref": agriculture_resource.target_ref, "position": Vector3.ZERO, "item_kind": "FOOD", "quantity": 2},
		{"kind": "HUNTING", "source_ref": "ANIMAL-B08-EXTERNAL", "position": Vector3(5.0, 0.45, 7.5), "item_kind": "MATERIAL", "quantity": 1},
		{"kind": "FISHING", "source_ref": "FISHING-B08-EXTERNAL", "position": Vector3(32.0, 0.35, -10.0), "item_kind": "FOOD", "quantity": 2},
		{"kind": "ENEMY", "source_ref": enemy.target_ref, "position": Vector3(8.0, 0.45, -7.0), "item_kind": "MATERIAL", "quantity": 1},
	]
	var expected_resource_by_kind := {
		"TREE": tree_resource,
		"ROCK": rock_resource,
		"ORE": ore_resource,
		"FLORA": flora_resource,
		"AGRICULTURE": agriculture_resource,
	}
	for index: int in range(source_cases.size()):
		var source: Dictionary = source_cases[index]
		var kind: String = str(source["kind"])
		var drop_ref := "LOOT-B08-%s-%02d" % [kind, index]
		var output: Dictionary = _output_entry(
			drop_ref,
			"ITEM-B08-%s" % kind,
			str(source["item_kind"]),
			int(source["quantity"])
		)
		var event: Dictionary = _output_event(
			kind,
			str(source["source_ref"]),
			[output],
			source["position"],
			true
		)
		var projection: Dictionary = gathering.project_physical_output_event(event)
		_check("OUTPUT_%s_EVENT_PASS" % kind, projection.get("status") == "PASS", JSON.stringify(projection))
		_check("OUTPUT_%s_SOURCE_KIND" % kind, projection.get("source_kind") == kind)
		_check("OUTPUT_%s_COUNT_ONE" % kind, int(projection.get("output_count", 0)) == 1)
		_check("OUTPUT_%s_GROUND_LOOT_BEFORE_INVENTORY" % kind, projection.get("ground_loot_before_inventory") == true)
		_check("OUTPUT_%s_NO_DIRECT_INVENTORY" % kind, projection.get("direct_inventory_delivery") == false)
		_check("OUTPUT_%s_NO_LOCAL_YIELD" % kind, projection.get("yield_calculated_locally") == false)
		_check("OUTPUT_%s_NO_LOCAL_QUANTITY" % kind, projection.get("quantity_calculated_locally") == false)
		var loot: AndromedaGroundLoot = pickup_client.ground_loot_for_ref(drop_ref)
		_check("OUTPUT_%s_LOOT_EXISTS" % kind, loot != null)
		if loot == null:
			continue
		_projected_output_refs.append(drop_ref)
		var loot_snapshot: Dictionary = loot.presentation_snapshot()
		_check("OUTPUT_%s_PHYSICAL_RIGIDBODY" % kind, loot.is_class("RigidBody3D"))
		_check("OUTPUT_%s_IN_WORLD_ROOT" % kind, loot.get_parent() == loot_root)
		_check("OUTPUT_%s_TARGET_REF" % kind, loot.target_ref == drop_ref)
		_check("OUTPUT_%s_SOURCE_REF" % kind, loot_snapshot.get("source_ref") == source["source_ref"])
		_check("OUTPUT_%s_SOURCE_KIND_PRESERVED" % kind, loot_snapshot.get("source_kind") == kind)
		_check("OUTPUT_%s_QUANTITY_EXTERNAL" % kind, int(loot_snapshot.get("quantity", 0)) == int(source["quantity"]))
		_check("OUTPUT_%s_ITEM_KIND" % kind, loot_snapshot.get("item_kind") == source["item_kind"])
		_check("OUTPUT_%s_INITIAL_SETTLING" % kind, not loot.is_pickup_settled())
		_check("OUTPUT_%s_NO_ITEM_GRANT" % kind, loot_snapshot.get("item_grant_authority") == false)
		if expected_resource_by_kind.has(kind):
			var source_resource: AndromedaResourceNode = expected_resource_by_kind[kind]
			_check("OUTPUT_%s_DROP_ANCHOR_USED" % kind, loot.global_position.distance_to(source_resource.drop_anchor_world_position()) < 0.02)
		else:
			_check("OUTPUT_%s_AUTHORIZED_POSITION_USED" % kind, loot.global_position.distance_to(source["position"]) < 0.02)
	_check("ALL_EIGHT_REQUIRED_OUTPUT_SOURCES", _projected_output_refs.size() == 8)
	var tree_loot: AndromedaGroundLoot = pickup_client.ground_loot_for_ref("LOOT-B08-TREE-00")
	var ore_loot: AndromedaGroundLoot = pickup_client.ground_loot_for_ref("LOOT-B08-ORE-02")
	_check("STACK_QUANTITY_GREATER_THAN_ONE", tree_loot != null and tree_loot.projected_quantity == 4)
	_check("STACK_QUANTITY_ONE", pickup_client.ground_loot_for_ref("LOOT-B08-ROCK-01").projected_quantity == 1)
	_check("CATEGORY_ICON_MINERAL", ore_loot != null and ore_loot.icon_category() == "ICON_MINERAL")
	_check("CATEGORY_ICON_BY_CATEGORY_NOT_ITEM", ore_loot != null and not ore_loot.icon_category().contains(ore_loot.item_ref))
	var count_before_zero: int = pickup_client.registered_loot_count()
	var zero_event: Dictionary = _output_event(
		"HUNTING",
		"ANIMAL-B08-ZERO-OUTPUT",
		[],
		Vector3(6.0, 0.3, 7.0),
		true
	)
	var zero_result: Dictionary = gathering.project_physical_output_event(zero_event)
	_check("ZERO_OUTPUT_EVENT_PASS", zero_result.get("status") == "PASS", JSON.stringify(zero_result))
	_check("ZERO_OUTPUT_COUNT_ZERO", int(zero_result.get("output_count", -1)) == 0)
	_check("ZERO_OUTPUT_SPAWNS_NOTHING", pickup_client.registered_loot_count() == count_before_zero)
	var invalid_quantity_event: Dictionary = _output_event(
		"TREE",
		tree_resource.target_ref,
		[_output_entry("LOOT-B08-INVALID-QUANTITY", "ITEM", "MATERIAL", 0)],
		Vector3.ZERO,
		false
	)
	var invalid_quantity_result: Dictionary = gathering.project_physical_output_event(invalid_quantity_event)
	_check("INVALID_QUANTITY_REJECTED", invalid_quantity_result.get("reason") == "INVALID_EXTERNAL_OUTPUT_QUANTITY")
	_check("INVALID_QUANTITY_NOT_SPAWNED", pickup_client.ground_loot_for_ref("LOOT-B08-INVALID-QUANTITY") == null)
	var duplicate_source_event: Dictionary = _output_event(
		"ENEMY",
		enemy.target_ref,
		[_output_entry("LOOT-B08-DUPLICATE-EVENT", "ITEM", "MATERIAL", 1)],
		Vector3(7.0, 0.4, -7.0),
		true
	)
	var duplicate_source_first: Dictionary = gathering.project_physical_output_event(duplicate_source_event)
	_check("DUPLICATE_EVENT_FIRST_PASS", duplicate_source_first.get("status") == "PASS")
	var duplicate_source_second: Dictionary = gathering.project_physical_output_event(duplicate_source_event)
	_check("DUPLICATE_EVENT_SECOND_REJECTED", duplicate_source_second.get("reason") == "DUPLICATE_PHYSICAL_OUTPUT_EVENT")
	_check("DUPLICATE_EVENT_SINGLE_LOOT", pickup_client.ground_loot_for_ref("LOOT-B08-DUPLICATE-EVENT") != null)
	var stale_event: Dictionary = duplicate_source_event.duplicate(true)
	stale_event["event_ref"] = "B08-STALE-OUTPUT-EVENT"
	stale_event["event_sequence"] = _output_event_sequence - 1
	stale_event["outputs"] = [_output_entry("LOOT-B08-STALE-EVENT", "ITEM", "MATERIAL", 1)]
	_check("STALE_OUTPUT_REJECTED", gathering.project_physical_output_event(stale_event).get("reason") == "STALE_PHYSICAL_OUTPUT_EVENT")
	_check("STALE_OUTPUT_NOT_SPAWNED", pickup_client.ground_loot_for_ref("LOOT-B08-STALE-EVENT") == null)
	var wrong_session_event: Dictionary = duplicate_source_event.duplicate(true)
	wrong_session_event["event_ref"] = "B08-WRONG-SESSION-OUTPUT"
	wrong_session_event["event_sequence"] = _output_event_sequence + 1
	wrong_session_event["session_ref"] = WRONG_SESSION_REF
	wrong_session_event["outputs"] = [_output_entry("LOOT-B08-WRONG-SESSION", "ITEM", "MATERIAL", 1)]
	_check("WRONG_SESSION_OUTPUT_REJECTED", gathering.project_physical_output_event(wrong_session_event).get("reason") == "SESSION_MISMATCH")
	_check("WRONG_SESSION_OUTPUT_NOT_SPAWNED", pickup_client.ground_loot_for_ref("LOOT-B08-WRONG-SESSION") == null)
	var direct_inventory_event: Dictionary = _output_event(
		"TREE",
		tree_resource.target_ref,
		[],
		Vector3.ZERO,
		false
	)
	direct_inventory_event["inventory_grant"] = {"item_ref": "FORGED"}
	_check("DIRECT_INVENTORY_EVENT_REJECTED", gathering.project_physical_output_event(direct_inventory_event).get("reason") == "DIRECT_INVENTORY_OUTPUT_FORBIDDEN")
	var simultaneous_event: Dictionary = _output_event(
		"TREE",
		tree_resource.target_ref,
		[
			_output_entry("LOOT-B08-SIMULTANEOUS-A", "ITEM-A", "MATERIAL", 1),
			_output_entry("LOOT-B08-SIMULTANEOUS-B", "ITEM-B", "MATERIAL", 5),
		],
		Vector3.ZERO,
		true
	)
	var simultaneous_result: Dictionary = gathering.project_physical_output_event(simultaneous_event)
	_check("SIMULTANEOUS_OUTPUT_EVENT_PASS", simultaneous_result.get("status") == "PASS", JSON.stringify(simultaneous_result))
	_check("SIMULTANEOUS_OUTPUT_COUNT_TWO", simultaneous_result.get("output_count") == 2)
	_check("SIMULTANEOUS_OUTPUT_A_EXISTS", pickup_client.ground_loot_for_ref("LOOT-B08-SIMULTANEOUS-A") != null)
	_check("SIMULTANEOUS_OUTPUT_B_EXISTS", pickup_client.ground_loot_for_ref("LOOT-B08-SIMULTANEOUS-B") != null)
	_check("SIMULTANEOUS_STACK_QUANTITY", pickup_client.ground_loot_for_ref("LOOT-B08-SIMULTANEOUS-B").projected_quantity == 5)
	var duplicate_refs_event: Dictionary = _output_event(
		"ROCK",
		rock_resource.target_ref,
		[
			_output_entry("LOOT-B08-DUP-REF", "ITEM-A", "MINERAL", 1),
			_output_entry("LOOT-B08-DUP-REF", "ITEM-B", "MINERAL", 1),
		],
		Vector3.ZERO,
		false
	)
	_check("DUPLICATE_OUTPUT_REFS_REJECTED", gathering.project_physical_output_event(duplicate_refs_event).get("reason") == "DUPLICATE_OUTPUT_TARGET_REF_IN_EVENT")
	await _wait_physics_frames(180)
	for kind: String in ["TREE", "ROCK", "ORE", "FLORA", "AGRICULTURE", "HUNTING", "ENEMY"]:
		var index: int = ["TREE", "ROCK", "ORE", "FLORA", "AGRICULTURE", "HUNTING", "FISHING", "ENEMY"].find(kind)
		var loot_ref := "LOOT-B08-%s-%02d" % [kind, index]
		var settled_loot: AndromedaGroundLoot = pickup_client.ground_loot_for_ref(loot_ref)
		_check("OUTPUT_%s_SETTLES" % kind, settled_loot != null and settled_loot.is_locally_settled(), loot_ref)
		_check("OUTPUT_%s_FREEZES_AFTER_SETTLE" % kind, settled_loot != null and bool(settled_loot.get("freeze")), loot_ref)
		_check("OUTPUT_%s_REMAINS_WORLD_OBJECT" % kind, settled_loot != null and settled_loot.is_inside_tree(), loot_ref)
	var fishing_loot: AndromedaGroundLoot = pickup_client.ground_loot_for_ref("LOOT-B08-FISHING-06")
	_check("FISHING_OUTPUT_NEAR_WATER_EXISTS", fishing_loot != null)
	_check("FISHING_OUTPUT_WATER_PRESENTER", fishing_loot != null and fishing_loot.has_node("WaterWorldItemPresenter"))
	_check("FISHING_OUTPUT_REMAINS_ACTIVE", fishing_loot != null and fishing_loot.is_active_for_pickup())
	_check("B07_PICKUP_RADIUS_PRESERVED", is_equal_approx(float(pickup_client.contract_snapshot().get("pickup_radius_m", -1.0)), 0.5))
	_check("B07_SETTLING_CONTRACT_PRESERVED", tree_loot != null and AndromedaGroundLoot.LOCAL_SETTLE_STABLE_FRAMES == 10)


func _test_streaming_integration() -> void:
	var manager_before: Dictionary = streaming.state_snapshot()
	var instance_id_before: int = agriculture_resource.get_instance_id()
	var loot_count_before: int = pickup_client.registered_loot_count()
	var preload_result: Dictionary = gathering.project_resource_stream_phase(
		agriculture_resource.target_ref,
		"PRELOAD",
		SESSION_REF,
		agriculture_resource.last_stream_sequence() + 1,
		true
	)
	_check("STREAM_ACTIVE_TO_PRELOAD_PASS", preload_result.get("status") == "PASS", JSON.stringify(preload_result))
	_check("STREAM_PRELOAD_STATE", agriculture_resource.stream_phase() == "PRELOAD")
	_check("STREAM_PRELOAD_REDUCED_VISUAL", agriculture_resource.presentation_snapshot().get("reduced_preload_representation") == true)
	_check("STREAM_PRELOAD_NOT_DETAILED", agriculture_resource.presentation_snapshot().get("detailed_resource_materialized") == false)
	_check("STREAM_PRELOAD_NOT_INTERACTIVE", agriculture_resource.can_prepare_gather_intent().get("reason") == "RESOURCE_NOT_ACTIVE_IN_STREAM")
	var active_again: Dictionary = gathering.project_resource_stream_phase(
		agriculture_resource.target_ref,
		"ACTIVE",
		SESSION_REF,
		agriculture_resource.last_stream_sequence() + 1,
		true
	)
	_check("STREAM_PRELOAD_TO_ACTIVE_PASS", active_again.get("status") == "PASS")
	_check("STREAM_ACTIVE_DETAILED", agriculture_resource.presentation_snapshot().get("detailed_resource_materialized") == true)
	_check("STREAM_ACTIVE_INTERACTIVE", agriculture_resource.can_prepare_gather_intent().get("status") == "PASS")
	var systemic: Dictionary = gathering.project_resource_stream_phase(
		agriculture_resource.target_ref,
		"SYSTEMIC",
		SESSION_REF,
		agriculture_resource.last_stream_sequence() + 1,
		true
	)
	_check("STREAM_ACTIVE_TO_SYSTEMIC_PASS", systemic.get("status") == "PASS", JSON.stringify(systemic))
	_check("STREAM_SYSTEMIC_REFERENCE_ONLY", agriculture_resource.presentation_snapshot().get("systemic_reference_only") == true)
	_check("STREAM_SYSTEMIC_VISUAL_UNLOADED", not agriculture_resource.visual_root.visible)
	_check("STREAM_SYSTEMIC_COLLISION_UNLOADED", int(agriculture_resource.get("collision_layer")) == 0)
	_check("STREAM_SYSTEMIC_NOT_SELECTABLE", agriculture_resource.selectable == false)
	_check("STREAM_SYSTEMIC_LIVING_REFERENCE", systemic.get("living_macro_ref") == manager_before.get("living_macro_ref"))
	_check("STREAM_SYSTEMIC_EXTERNAL_LIVING_SOURCE", systemic.get("systemic_state_source") == "EXTERNAL_LIVING_REFERENCE_ONLY")
	var systemic_instance_id: int = agriculture_resource.get_instance_id()
	var materialize_again: Dictionary = gathering.project_resource_stream_phase(
		agriculture_resource.target_ref,
		"ACTIVE",
		SESSION_REF,
		agriculture_resource.last_stream_sequence() + 1,
		true
	)
	_check("STREAM_SYSTEMIC_TO_ACTIVE_PASS", materialize_again.get("status") == "PASS")
	_check("STREAM_RELOAD_REUSES_IDENTITY", agriculture_resource.get_instance_id() == instance_id_before and instance_id_before == systemic_instance_id)
	_check("STREAM_RELOAD_NO_DUPLICATE_NODE", gathering.resource_for_ref(agriculture_resource.target_ref) == agriculture_resource)
	_check("STREAM_RELOAD_RESOURCE_COUNT_STABLE", gathering.registered_resource_count() >= 5)
	_check("STREAM_RELOAD_NO_DUPLICATE_GROUND_LOOT", pickup_client.registered_loot_count() == loot_count_before)
	var stale_stream: Dictionary = gathering.project_resource_stream_phase(
		agriculture_resource.target_ref,
		"PRELOAD",
		SESSION_REF,
		agriculture_resource.last_stream_sequence(),
		true
	)
	_check("STALE_STREAM_PHASE_REJECTED", stale_stream.get("reason") == "STALE_OR_DUPLICATE_RESOURCE_STREAM_PHASE")
	var wrong_session_stream: Dictionary = gathering.project_resource_stream_phase(
		agriculture_resource.target_ref,
		"PRELOAD",
		WRONG_SESSION_REF,
		agriculture_resource.last_stream_sequence() + 1,
		true
	)
	_check("WRONG_SESSION_STREAM_REJECTED", wrong_session_stream.get("reason") == "SESSION_MISMATCH")
	var manager_after: Dictionary = streaming.state_snapshot()
	_check("B04_STREAMING_MANAGER_UNCHANGED", manager_after.get("active_cells") == manager_before.get("active_cells") and manager_after.get("preload_cells") == manager_before.get("preload_cells"))
	_check("B04_LIVING_MACRO_REF_PRESERVED", manager_after.get("living_macro_ref") == manager_before.get("living_macro_ref"))
	_check("B04_NO_LIVING_PARALLEL", manager_after.get("living_parallel_implementation") == false)


func _test_b05_b06_b07_interactions() -> void:
	gathering.clear_client_request_tracking()
	pickup_client.clear_client_request_tracking()
	player.stop_local_prediction()
	player.global_position = tree_resource.global_position + Vector3(0.5, 0.0, 0.0)
	await _wait_physics_frames(2)
	var gather_request: Dictionary = gathering.begin_gather_interaction(tree_resource, "AUTO_PICKUP_INTEROP")
	_check("INTEROP_GATHER_REQUEST_ACTIVE", gather_request.get("intent") == "REQUEST_GATHER")
	_check("INTEROP_GATHER_INFLIGHT", gathering.has_inflight_request(tree_resource.target_ref))
	var selected_before: String = main.selected_target_ref()
	var projected_preference: Dictionary = pickup_client.project_profile_preference(true, SESSION_REF, 0, true)
	_check("AUTO_PICKUP_EXTERNAL_PREFERENCE_PASS", projected_preference.get("status") == "PASS", JSON.stringify(projected_preference))
	_check("AUTO_PICKUP_ON", pickup_client.auto_pickup_enabled())
	pickup_client.observe_action_context({
		"attack_active": true,
		"interaction_active": true,
		"chase_target_ref": enemy.target_ref,
	})
	var action_before: Dictionary = pickup_client.observed_action_context()
	var movement_before: bool = player.has_destination()
	var destination_before: Vector3 = player.requested_destination()
	var auto_scan: Dictionary = pickup_client.scan_auto_pickup_once()
	_check("AUTO_PICKUP_SCAN_DURING_GATHER_PASS", auto_scan.get("status") == "PASS")
	_check("AUTO_PICKUP_DOES_NOT_INTERRUPT_GATHER", gathering.has_inflight_request(tree_resource.target_ref))
	_check("AUTO_PICKUP_DOES_NOT_CHANGE_RESOURCE_TARGET", main.selected_target_ref() == selected_before)
	_check("AUTO_PICKUP_DOES_NOT_CHANGE_ATTACK_CONTEXT", pickup_client.observed_action_context() == action_before)
	_check("AUTO_PICKUP_DOES_NOT_CHANGE_MOVEMENT", player.has_destination() == movement_before)
	_check("AUTO_PICKUP_DOES_NOT_CHANGE_DESTINATION", player.requested_destination().is_equal_approx(destination_before))
	_check("AUTO_PICKUP_NO_REMOTE_CONTRACT", pickup_client.contract_snapshot().get("auto_pickup_remote") == false)
	var target_before_feedback: String = main.selected_target_ref()
	var camera_logic_before: Vector3 = camera_rig.global_position
	var physical_distance_before_feedback: float = player.global_position.distance_to(tree_resource.interaction_anchor_world_position())
	var combat_feedback: Dictionary = hud.present_combat_event({
		"token": "COMBAT_HIT",
		"target_ref": enemy.target_ref,
		"confirmed_externally": true,
		"presentation_target": enemy,
		"strength": "NORMAL",
	})
	_check("COMBAT_FEEDBACK_PASS_DURING_GATHER", combat_feedback.get("status") == "PASS", JSON.stringify(combat_feedback))
	_check("COMBAT_FEEDBACK_TARGET_STABLE", main.selected_target_ref() == target_before_feedback)
	_check("COMBAT_FEEDBACK_GATHER_INFLIGHT", gathering.has_inflight_request(tree_resource.target_ref))
	_check("COMBAT_FEEDBACK_CAMERA_LOGIC_STABLE", camera_rig.global_position.is_equal_approx(camera_logic_before))
	_check("COMBAT_FEEDBACK_LOCAL_ONLY", combat_feedback.get("global_world_pause") == false)
	_check("COMBAT_FEEDBACK_NO_DISTANCE_REWRITE", is_equal_approx(
		player.global_position.distance_to(tree_resource.interaction_anchor_world_position()),
		physical_distance_before_feedback
	))
	var rejection: Dictionary = gathering.project_gathering_result({
		"server_authoritative": true,
		"session_ref": SESSION_REF,
		"target_ref": tree_resource.target_ref,
		"result_sequence": 2,
		"status": "REJECTED",
		"reason": "EXTERNAL_REJECTION",
	})
	_check("INTERACTION_REJECTION_FEEDBACK_PASS", rejection.get("status") == "PASS")
	_check("INTERACTION_REJECTION_NO_INVENTORY", rejection.get("inventory_mutated") == false)
	_check("FEEDBACK_STACK_MAX_THREE", hud.combat_feedback.visible_tokens().size() <= 3)
	_check("B05_STAMINA_RING_SINGLE", hud.get_node("WorldUIRoot/StaminaWorldRing") == hud.stamina_ring)
	_check("B05_QUICK_SLOTS_PRESERVED", hud.weapon_quick_slots.contract_snapshot().get("max_quick_slots") == 2)
	_check("B07_PICKUP_05M_PRESERVED", pickup_client.contract_snapshot().get("pickup_radius_m") == 0.5)
	_check("B07_AUTO_PICKUP_NO_INTERACTION_INTERRUPT", pickup_client.contract_snapshot().get("auto_pickup_interrupts_interaction") == false)


func _test_stamina_projection_only() -> void:
	var ring_instance_id: int = hud.stamina_ring.get_instance_id()
	var non_authoritative: Dictionary = gathering.project_gathering_stamina_snapshot({
		"server_authoritative": false,
		"session_ref": SESSION_REF,
		"stamina_sequence": 0,
		"stamina_fraction": 0.8,
		"activity": "CONSUMING",
	})
	_check("NON_AUTHORITATIVE_STAMINA_REJECTED", non_authoritative.get("reason") == "NON_AUTHORITATIVE_GATHERING_STAMINA")
	var projected: Dictionary = gathering.project_gathering_stamina_snapshot({
		"server_authoritative": true,
		"session_ref": SESSION_REF,
		"stamina_sequence": 0,
		"stamina_fraction": 0.72,
		"activity": "CONSUMING",
	})
	_check("EXTERNAL_STAMINA_PROJECTION_PASS", projected.get("status") == "PASS", JSON.stringify(projected))
	_check("EXTERNAL_STAMINA_FRACTION", is_equal_approx(hud.stamina_ring.stamina_fraction(), 0.72))
	_check("EXTERNAL_STAMINA_ACTIVITY", hud.stamina_ring.activity_state() == "CONSUMING")
	_check("EXTERNAL_STAMINA_SOURCE", hud.stamina_ring.projection_source() == "EXTERNAL_STAGE16A_GATHERING_SNAPSHOT")
	_check("STAMINA_NOT_SUBTRACTED_LOCALLY", projected.get("stamina_subtracted_locally") == false)
	_check("NO_SECOND_STAMINA_CREATED", projected.get("second_stamina_created") == false and hud.stamina_ring.get_instance_id() == ring_instance_id)
	var stale: Dictionary = gathering.project_gathering_stamina_snapshot({
		"server_authoritative": true,
		"session_ref": SESSION_REF,
		"stamina_sequence": 0,
		"stamina_fraction": 0.5,
		"activity": "CONSUMING",
	})
	_check("STALE_STAMINA_PROJECTION_REJECTED", stale.get("reason") == "STALE_OR_DUPLICATE_GATHERING_STAMINA")
	_check("STALE_STAMINA_DOES_NOT_CHANGE_RING", is_equal_approx(hud.stamina_ring.stamina_fraction(), 0.72))
	_check("G16B08_NOT_PROMOTED_BY_CLIENT", gathering.contract_snapshot().get("stamina_authority") == false)


func _main_resources() -> Array[AndromedaResourceNode]:
	return [tree_resource, rock_resource, ore_resource, flora_resource, agriculture_resource]


func _resource_entry(resource: AndromedaResourceNode, state: String, stream_phase: String = "ACTIVE") -> Dictionary:
	return {
		"target_ref": resource.target_ref,
		"resource_kind": resource.resource_kind,
		"state": state,
		"stream_phase": stream_phase,
	}


func _next_resource_snapshot(entries: Array[Dictionary]) -> Dictionary:
	_resource_snapshot_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": SESSION_REF,
		"snapshot_sequence": _resource_snapshot_sequence,
		"resources": entries,
	}


func _output_entry(target_ref_value: String, item_ref_value: String, item_kind_value: String, quantity_value: int) -> Dictionary:
	return {
		"target_ref": target_ref_value,
		"item_ref": item_ref_value,
		"item_kind": item_kind_value,
		"quantity": quantity_value,
		"state": "ACTIVE",
		"settled": false,
		"reachable": true,
		"water_exposure_s": 0.0,
	}


func _output_event(
	source_kind: String,
	source_ref: String,
	outputs: Array,
	authorized_position: Vector3,
	advance_sequences: bool
) -> Dictionary:
	var next_event_sequence: int = _output_event_sequence + 1
	var next_loot_sequence: int = _ground_loot_snapshot_sequence + 1
	if advance_sequences:
		_output_event_sequence = next_event_sequence
		if not outputs.is_empty():
			_ground_loot_snapshot_sequence = next_loot_sequence
	return {
		"server_authoritative": true,
		"session_ref": SESSION_REF,
		"event_ref": "B08-OUTPUT-EVENT-%04d-%s" % [next_event_sequence, source_kind],
		"event_sequence": next_event_sequence,
		"ground_loot_snapshot_sequence": next_loot_sequence,
		"source_kind": source_kind,
		"source_ref": source_ref,
		"authorized_position": _position_dictionary(authorized_position),
		"outputs": outputs,
	}


func _create_test_resource(
	target_ref_value: String,
	resource_kind_value: String,
	position_value: Vector3
) -> AndromedaResourceNode:
	var resource := RESOURCE_NODE_SCENE.instantiate() as AndromedaResourceNode
	resource.target_ref = target_ref_value
	resource.target_kind = AndromedaInputRouter.HIT_GATHER_NODE
	resource.resource_kind = resource_kind_value
	resource.display_name = "%s B08 Test Placeholder" % resource_kind_value
	resource.position = position_value
	resource_root.add_child(resource)
	_temporary_nodes.append(resource)
	await _wait_physics_frames(1)
	var registration: Dictionary = gathering.register_resource(resource)
	_check("TEMP_%s_REGISTERED" % target_ref_value, registration.get("status") == "PASS", JSON.stringify(registration))
	var projection: Dictionary = resource.apply_authoritative_projection(
		{
			"server_authoritative": true,
			"target_ref": target_ref_value,
			"resource_kind": resource_kind_value,
			"state": "AVAILABLE",
		},
		SESSION_REF,
		0,
		true
	)
	_check("TEMP_%s_STATE_PROJECTED" % target_ref_value, projection.get("status") == "PASS", JSON.stringify(projection))
	return resource


func _position_dictionary(value: Vector3) -> Dictionary:
	return {"iso_x_m": value.x, "iso_y_m": value.z, "altitude_m": value.y}


func _mouse_button(button_index: int, position: Vector2) -> InputEventMouseButton:
	var event := InputEventMouseButton.new()
	event.button_index = button_index as MouseButton
	event.position = position
	event.global_position = position
	event.pressed = true
	return event


func _key_event(keycode: Key) -> InputEventKey:
	var event := InputEventKey.new()
	event.keycode = keycode
	event.pressed = true
	return event


func _wait_for_navigation(max_frames: int) -> bool:
	for _frame_index: int in range(max_frames):
		if main.navigation_ready():
			return true
		await get_tree().physics_frame
	return false


func _wait_physics_frames(frame_count: int) -> void:
	for _frame_index: int in range(frame_count):
		await get_tree().physics_frame


func _cleanup_temporary_nodes() -> void:
	for node: Node in _temporary_nodes:
		if node != null and is_instance_valid(node):
			node.queue_free()
	_temporary_nodes.clear()
	await _wait_physics_frames(2)


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "B08_RESOURCE_NODES_GATHERING_TO_GROUND_LOOT",
		"acceptance_scope_pass": [],
		"partial_evidence_only": ["G16B-03", "G16B-04", "G16B-05", "G16B-06", "G16B-08", "G16B-09", "G16B-20"],
		"authoritative_roundtrip_executed": false,
		"backend_status": "NOT_AVAILABLE",
		"fixtures_are_external_projection_contract_tests_only": true,
		"authority": "GODOT_GATHERING_CLIENT_ORCHESTRATION_ONLY",
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_B08_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_B08_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_B08_SUMMARY: %s" % JSON.stringify(summary))
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
