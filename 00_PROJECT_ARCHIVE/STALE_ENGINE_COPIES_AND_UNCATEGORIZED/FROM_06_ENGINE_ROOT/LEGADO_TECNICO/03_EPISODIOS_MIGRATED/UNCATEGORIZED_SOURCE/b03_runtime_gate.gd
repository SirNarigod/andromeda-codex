extends Node

var _checks: int = 0
var _failures: Array[String] = []

@onready var main: AndromedaMainRuntime = $AndromedaARPG
@onready var player: AndromedaPlayerController = $AndromedaARPG/ActorRoot/Player
@onready var camera_rig: AndromedaIsometricCameraRig = $AndromedaARPG/IsometricCameraRig
@onready var npc: AndromedaInteractionTarget = $AndromedaARPG/ActorRoot/NPCB03
@onready var enemy: AndromedaInteractionTarget = $AndromedaARPG/ActorRoot/EnemyB03
@onready var animal: AndromedaInteractionTarget = $AndromedaARPG/ActorRoot/AnimalB03
@onready var tree_resource: AndromedaInteractionTarget = $AndromedaARPG/WorldStreamRoot/B03InteractionTargets/TreeB03
@onready var rock_resource: AndromedaInteractionTarget = $AndromedaARPG/WorldStreamRoot/B03InteractionTargets/RockB03
@onready var ore_resource: AndromedaInteractionTarget = $AndromedaARPG/WorldStreamRoot/B03InteractionTargets/OreB03
@onready var flora_resource: AndromedaInteractionTarget = $AndromedaARPG/WorldStreamRoot/B03InteractionTargets/FloraB03
@onready var interactive_object: AndromedaInteractionTarget = $AndromedaARPG/WorldStreamRoot/B03InteractionTargets/InteractiveObjectB03
@onready var vehicle: AndromedaInteractionTarget = $AndromedaARPG/WorldStreamRoot/B03InteractionTargets/VehicleB03
@onready var ground_loot: AndromedaInteractionTarget = $AndromedaARPG/GroundLootRoot/GroundLootB03
@onready var unreachable_loot: AndromedaInteractionTarget = $AndromedaARPG/GroundLootRoot/GroundLootUnreachableB03
@onready var unsettled_loot: AndromedaInteractionTarget = $AndromedaARPG/GroundLootRoot/GroundLootUnsettledB03
@onready var blocked_loot: AndromedaInteractionTarget = $AndromedaARPG/GroundLootRoot/GroundLootBlockedB03


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

	var bind_result: Dictionary = session.bind_session("B03-GATE-SESSION")
	_check("SESSION_BOUND_FOR_INTENT_ENVELOPES_ONLY", bind_result.get("status") == "PASS", JSON.stringify(bind_result))
	_check("EXISTING_BACKEND_URL_UNCHANGED", bridge.server_url() == "http://127.0.0.1:8000")
	_check("NO_BACKEND_SUBSTITUTE", main.contract_snapshot().get("backend_substitute") == false)
	_check("NO_GDSCRIPT_GAMEPLAY_AUTHORITY", main.contract_snapshot().get("gameplay_authority_in_gdscript") == false)
	_check("NO_B03_TRANSPORT_SUBMISSION", main.contract_snapshot().get("backend_command_submission_in_b03") == false)
	_check("B03_TARGET_PRIORITY_CONTRACT", main.contract_snapshot().get("target_resolution_order") == [
		"SCREEN_DISTANCE", "DEPTH", "SEMANTIC_TIEBREAK", "TARGET_REF"
	])
	_check("SEMANTIC_PRIORITY_TIEBREAK_ONLY", main.contract_snapshot().get("semantic_priority_is_tiebreak_only") == true)
	_check("PICKUP_RADIUS_CONTRACT", is_equal_approx(
		float(main.contract_snapshot().get("ground_loot_pickup_radius_m", -1.0)), 0.5
	))

	_test_collision_layer_contract()
	_test_target_scene_contracts()
	var navigation_became_ready: bool = await _wait_for_navigation(180)
	_check("NAVIGATION_MAP_READY", navigation_became_ready)
	if not navigation_became_ready:
		await _finish()
		return

	await get_tree().physics_frame
	_test_hover_contract()
	await _test_left_click_selection_and_stability()
	_test_left_click_target_matrix()
	await _test_ground_loot_contract(router)
	_test_right_click_matrix()
	await _test_overlap_depth_and_cursor_priority(router)
	_test_blocker_and_inaccessible_targets()
	_test_no_gameplay_authority_surface(bridge)

	await _finish()


func _test_collision_layer_contract() -> void:
	var expected_layers: Array[Dictionary] = [
		{"name": "WORLD_STATIC", "index": 1, "bit": 1},
		{"name": "PLAYER", "index": 2, "bit": 2},
		{"name": "ACTOR_BODY", "index": 3, "bit": 4},
		{"name": "INTERACTABLE", "index": 4, "bit": 8},
		{"name": "GROUND_LOOT", "index": 5, "bit": 16},
		{"name": "RESOURCE_NODE", "index": 6, "bit": 32},
		{"name": "VEHICLE", "index": 7, "bit": 64},
		{"name": "NAV_BLOCKER", "index": 8, "bit": 128},
		{"name": "CAMERA_OCCLUDER", "index": 9, "bit": 256},
		{"name": "HIT_HURT_SENSOR", "index": 10, "bit": 512},
		{"name": "WORLD_TRIGGER", "index": 11, "bit": 1024},
		{"name": "WATER_VOLUME", "index": 12, "bit": 2048},
		{"name": "DROPPED_BAG", "index": 13, "bit": 4096},
	]
	var layer_contract: Dictionary = main.collision_layer_contract()
	for layer: Dictionary in expected_layers:
		var layer_name: String = str(layer.get("name", ""))
		var layer_index: int = int(layer.get("index", 0))
		var expected_bit: int = int(layer.get("bit", 0))
		_check("LAYER_NAME_%02d_%s" % [layer_index, layer_name],
			str(ProjectSettings.get_setting("layer_names/3d_physics/layer_%d" % layer_index, "")) == layer_name)
		_check("LAYER_BIT_%02d_%s" % [layer_index, layer_name],
			int(layer_contract.get(layer_name, 0)) == expected_bit,
			JSON.stringify(layer_contract))
	_check("PLAYER_LAYER_EXACT", int(player.get("collision_layer")) == 2)
	_check("PLAYER_MASK_B03_BLOCKING_SURFACES", int(player.get("collision_mask")) == 229,
		str(player.get("collision_mask")))
	_check("CAMERA_OCCLUDER_MASK_EXACT", camera_rig.occlusion_probe.collision_mask == 256)
	var b02_npc := main.get_node("ActorRoot/NpcPointerPlaceholder") as Area3D
	var b02_loot := main.get_node("GroundLootRoot/GroundLootPlaceholder") as Area3D
	_check("B02_NPC_PLACEHOLDER_PATH_TYPE_PRESERVED", b02_npc != null)
	_check("B02_NPC_LAYER_CORRECTED_TO_INTERACTABLE", b02_npc != null and b02_npc.collision_layer == 8)
	_check("B02_LOOT_PLACEHOLDER_PATH_TYPE_PRESERVED", b02_loot != null)
	_check("B02_LOOT_LAYER_CORRECTED_TO_GROUND_LOOT", b02_loot != null and b02_loot.collision_layer == 16)
	var nav_blocker := main.get_node("WorldStreamRoot/CollisionSurface/B03RaycastBlocker") as StaticBody3D
	var camera_occluder := main.get_node("WorldStreamRoot/CollisionSurface/B03CameraOccluder") as StaticBody3D
	_check("NAV_BLOCKER_LAYER_EXACT", nav_blocker.collision_layer == 128)
	_check("CAMERA_OCCLUDER_LAYER_EXACT", camera_occluder.collision_layer == 256)


func _test_target_scene_contracts() -> void:
	var target_specs: Array[Dictionary] = [
		{"id": "NPC", "target": npc, "kind": "NPC", "layer": 4, "sensor": "InteractionSensor", "sensor_layer": 8},
		{"id": "ENEMY", "target": enemy, "kind": "ACTOR", "layer": 4, "sensor": "InteractionSensor", "sensor_layer": 8},
		{"id": "ANIMAL", "target": animal, "kind": "ANIMAL", "layer": 4, "sensor": "InteractionSensor", "sensor_layer": 8},
		{"id": "TREE", "target": tree_resource, "kind": "GATHER_NODE", "layer": 32, "sensor": "InteractionSensor", "sensor_layer": 8},
		{"id": "ROCK", "target": rock_resource, "kind": "GATHER_NODE", "layer": 32, "sensor": "InteractionSensor", "sensor_layer": 8},
		{"id": "ORE", "target": ore_resource, "kind": "GATHER_NODE", "layer": 32, "sensor": "InteractionSensor", "sensor_layer": 8},
		{"id": "FLORA", "target": flora_resource, "kind": "GATHER_NODE", "layer": 32, "sensor": "InteractionSensor", "sensor_layer": 8},
		{"id": "OBJECT", "target": interactive_object, "kind": "SCENE_OBJECT", "layer": 1, "sensor": "InteractionSensor", "sensor_layer": 8},
		{"id": "VEHICLE", "target": vehicle, "kind": "VEHICLE", "layer": 64, "sensor": "InteractionSensor", "sensor_layer": 8},
		{"id": "GROUND_LOOT", "target": ground_loot, "kind": "GROUND_LOOT", "layer": 16, "sensor": "PickupSensor", "sensor_layer": 16},
	]
	var unique_refs: Dictionary = {}
	for spec: Dictionary in target_specs:
		var check_prefix: String = str(spec.get("id", "TARGET"))
		var target_value: Variant = spec.get("target")
		_check("%s_TARGET_COMPONENT" % check_prefix, target_value is AndromedaInteractionTarget)
		if not target_value is AndromedaInteractionTarget:
			continue
		var target := target_value as AndromedaInteractionTarget
		var snapshot: Dictionary = target.interaction_snapshot()
		_check("%s_TARGET_REF_PRESENT" % check_prefix, not target.target_ref.is_empty(), target.target_ref)
		_check("%s_TARGET_REF_UNIQUE" % check_prefix, not unique_refs.has(target.target_ref), target.target_ref)
		unique_refs[target.target_ref] = true
		_check("%s_TARGET_KIND" % check_prefix, target.target_kind == str(spec.get("kind", "")), JSON.stringify(snapshot))
		_check("%s_ROOT_COLLISION_LAYER" % check_prefix,
			int(target.get("collision_layer")) == int(spec.get("layer", 0)), JSON.stringify(snapshot))
		_check("%s_COLLISION_SHAPE" % check_prefix, target.has_node("CollisionShape3D"))
		_check("%s_VISUAL_PLACEHOLDER" % check_prefix,
			target.has_node("VisualRoot") or target.has_node("PlaceholderVisual"))
		var sensor_path: String = str(spec.get("sensor", ""))
		var sensor := target.get_node_or_null(sensor_path) as CollisionObject3D
		_check("%s_POINTER_SENSOR" % check_prefix, sensor != null)
		_check("%s_POINTER_SENSOR_LAYER" % check_prefix,
			sensor != null and sensor.collision_layer == int(spec.get("sensor_layer", 0)))
		_check("%s_ROOT_METADATA_REF" % check_prefix,
			str(target.get_meta("target_ref", "")) == target.target_ref)
		_check("%s_SENSOR_METADATA_REF" % check_prefix,
			sensor != null and str(sensor.get_meta("target_ref", "")) == target.target_ref)
		_check("%s_PRESENTATION_AUTHORITY_ONLY" % check_prefix,
			snapshot.get("authority") == "GODOT_INTERACTION_PRESENTATION_ONLY")

	_check("NPC_CHARACTER_BODY_PLACEHOLDER", npc.is_class("CharacterBody3D"))
	_check("NPC_CONTRACT_TOPOLOGY", npc.has_node("NavigationAgent3D") and npc.has_node("DialogueAnchor")
		and npc.has_node("HealthBarAnchor"))
	_check("NPC_NEUTRAL_IDENTITY", not npc.hostile and npc.target_kind == "NPC")
	_check("NPC_NAME_HIDDEN_BY_DEFAULT", not npc.get_node("HoverFeedback/HoverName").visible)
	_check("ENEMY_CHARACTER_BODY_PLACEHOLDER", enemy.is_class("CharacterBody3D"))
	_check("ENEMY_HOSTILE_IDENTITY", enemy.hostile and enemy.target_kind == "ACTOR")
	_check("ENEMY_HURTBOX_LAYER", int(enemy.get_node("Hurtbox").get("collision_layer")) == 512)
	_check("ANIMAL_CHARACTER_BODY_PLACEHOLDER", animal.is_class("CharacterBody3D"))
	_check("ANIMAL_NOT_AUTOMATIC_ENEMY", not animal.hostile and animal.target_kind == "ANIMAL")
	_check("GROUND_LOOT_PHYSICAL_RIGID_BODY", ground_loot.is_class("RigidBody3D"))
	_check("GROUND_LOOT_SETTLED_FROZEN_PLACEHOLDER", ground_loot.settled and bool(ground_loot.get("freeze")))
	_check("GROUND_LOOT_UNSETTLED_FIXTURE", not unsettled_loot.settled)
	for resource_target: AndromedaInteractionTarget in [tree_resource, rock_resource, ore_resource, flora_resource]:
		_check("RESOURCE_%s_INDIVIDUALLY_IDENTIFIED" % resource_target.resource_kind,
			not resource_target.resource_kind.is_empty() and resource_target.target_ref.contains(resource_target.resource_kind))
		_check("RESOURCE_%s_DROP_ANCHOR" % resource_target.resource_kind, resource_target.has_node("DropAnchor"))
		_check("RESOURCE_%s_NO_INVENTORY_TRANSFER_NODE" % resource_target.resource_kind,
			not resource_target.has_node("Inventory") and not resource_target.has_node("LootTable"))


func _test_hover_contract() -> void:
	var npc_name := npc.get_node("HoverFeedback/HoverName") as Label3D
	_check("NPC_NAME_NOT_PERMANENT_BEFORE_HOVER", not npc_name.visible)
	var npc_hover: Dictionary = main.handle_pointer_hover(main.target_to_screen(npc))
	_check("HOVER_NPC_RESOLVED", npc_hover.get("intent") == "HOVER_TARGET"
		and npc_hover.get("target_ref") == npc.target_ref, JSON.stringify(npc_hover))
	_check("HOVER_NPC_CURSOR_TALK", npc_hover.get("cursor") == "TALK", JSON.stringify(npc_hover))
	_check("HOVER_NPC_COMPONENT_STATE", npc.is_hovered() and main.hovered_target_ref() == npc.target_ref)
	_check("NPC_NAME_APPEARS_ONLY_ON_HOVER", npc_name.visible and npc_name.text == npc.display_name)

	var clear_hover: Dictionary = main.handle_pointer_hover(main.world_to_screen(Vector3(-9.0, 0.0, 3.0)))
	_check("HOVER_CLEAR_ON_GROUND", clear_hover.get("intent") == "HOVER_CLEAR", JSON.stringify(clear_hover))
	_check("NPC_NAME_HIDDEN_AFTER_HOVER_EXIT", not npc_name.visible and not npc.is_hovered())

	var enemy_hover: Dictionary = main.handle_pointer_hover(main.target_to_screen(enemy))
	_check("HOVER_ENEMY_RESOLVED", enemy_hover.get("target_ref") == enemy.target_ref, JSON.stringify(enemy_hover))
	_check("HOVER_ENEMY_ATTACK_FEEDBACK", enemy_hover.get("cursor") == "ATTACK" and enemy.is_hovered())
	_check("HOVER_ENEMY_SUBTLE_HINT", enemy.get_node("HoverFeedback/HoverHint").visible)

	var resource_hover: Dictionary = main.handle_pointer_hover(main.target_to_screen(ore_resource))
	_check("HOVER_RESOURCE_RESOLVED", resource_hover.get("target_ref") == ore_resource.target_ref, JSON.stringify(resource_hover))
	_check("HOVER_RESOURCE_HARVEST_FEEDBACK", resource_hover.get("cursor") == "HARVEST" and ore_resource.is_hovered())
	_check("PREVIOUS_ENEMY_HOVER_CLEARED", not enemy.is_hovered())

	var loot_hover: Dictionary = main.handle_pointer_hover(main.target_to_screen(ground_loot))
	_check("HOVER_GROUND_LOOT_RESOLVED", loot_hover.get("target_ref") == ground_loot.target_ref, JSON.stringify(loot_hover))
	_check("HOVER_GROUND_LOOT_PICKUP_FEEDBACK", loot_hover.get("cursor") == "PICKUP" and ground_loot.is_hovered())
	var unsettled_hover: Dictionary = main.handle_pointer_hover(main.target_to_screen(unsettled_loot))
	_check("HOVER_UNSETTLED_LOOT_BLOCKED", unsettled_hover.get("target_ref") == unsettled_loot.target_ref
		and unsettled_hover.get("cursor") == "BLOCKED", JSON.stringify(unsettled_hover))


func _test_left_click_selection_and_stability() -> void:
	var move_result: Dictionary = player.request_move(Vector3(-8.0, 0.0, 5.5))
	_check("PREPARE_ACTIVE_MOVEMENT", move_result.get("status") == "PASS", JSON.stringify(move_result))
	await _wait_physics_frames(8)
	var destination_before_selection: Vector3 = player.requested_destination()
	var npc_click: Dictionary = _click_target(npc, MOUSE_BUTTON_LEFT)
	_check("LEFT_CLICK_NPC_SELECTS", npc_click.get("status") == "PASS"
		and npc_click.get("intent") == "SELECT_TARGET"
		and npc_click.get("target_ref") == npc.target_ref, JSON.stringify(npc_click))
	_check("LEFT_SELECTION_DOES_NOT_INTERRUPT_MOVEMENT",
		player.has_destination() and player.requested_destination().is_equal_approx(destination_before_selection))
	_check("LEFT_SELECTION_STATE_STORED", main.selected_target_ref() == npc.target_ref
		and main.selected_target_kind() == "NPC" and npc.is_selected())
	_check("LEFT_SELECTION_INDICATOR_VISIBLE", npc.get_node("HoverFeedback/SelectionIndicator").visible)
	_check("LEFT_SELECTION_INTENT_ENVELOPE", _valid_intent_envelope(npc_click, "SELECT_TARGET", npc.target_ref),
		JSON.stringify(npc_click))
	_check("LEFT_SELECTION_NOT_SUBMITTED", npc_click.get("transport_submitted") == false
		and npc_click.get("dispatched_to_gameplay") == false)

	var clicked_ref_before_camera_motion: String = main.last_pointer_target_ref()
	var selected_ref_before_camera_motion: String = main.selected_target_ref()
	var serial_before_camera_motion: int = main.pointer_resolution_serial()
	await _wait_physics_frames(24)
	_check("CAMERA_MOVEMENT_CANNOT_REWRITE_CLICKED_TARGET",
		main.last_pointer_target_ref() == clicked_ref_before_camera_motion
		and main.pointer_resolution_serial() == serial_before_camera_motion)
	_check("CAMERA_MOVEMENT_CANNOT_REWRITE_SELECTION",
		main.selected_target_ref() == selected_ref_before_camera_motion and npc.is_selected())

	main.handle_pointer_hover(main.target_to_screen(enemy))
	_check("HOVER_FEEDBACK_CANNOT_REWRITE_SELECTION", main.selected_target_ref() == npc.target_ref
		and main.last_pointer_target_ref() == npc.target_ref)
	player.stop_local_prediction()


func _test_left_click_target_matrix() -> void:
	var selectable_targets: Array[AndromedaInteractionTarget] = [
		npc,
		enemy,
		animal,
		tree_resource,
		rock_resource,
		ore_resource,
		flora_resource,
		interactive_object,
		vehicle,
	]
	for target: AndromedaInteractionTarget in selectable_targets:
		var destination_before: Vector3 = player.requested_destination()
		var click_result: Dictionary = _click_target(target, MOUSE_BUTTON_LEFT)
		var check_prefix: String = target.resource_kind if target.target_kind == "GATHER_NODE" else target.target_kind
		_check("LEFT_SELECT_%s" % check_prefix,
			click_result.get("status") == "PASS"
			and click_result.get("intent") == "SELECT_TARGET"
			and click_result.get("target_ref") == target.target_ref,
			JSON.stringify(click_result))
		_check("LEFT_SELECT_%s_NO_MOVEMENT_CHANGE" % check_prefix,
			player.requested_destination().is_equal_approx(destination_before))
		_check("LEFT_SELECT_%s_STABLE_REF" % check_prefix, main.selected_target_ref() == target.target_ref)
		_check("LEFT_SELECT_%s_ENVELOPE_ONLY" % check_prefix,
			_valid_intent_envelope(click_result, "SELECT_TARGET", target.target_ref)
			and click_result.get("transport_submitted") == false)
	_check("NPC_REMAINS_NEUTRAL_AFTER_OTHER_SELECTIONS", not npc.hostile and npc.target_kind == "NPC")
	_check("ANIMAL_REMAINS_NON_HOSTILE_AFTER_SELECTIONS", not animal.hostile and animal.target_kind == "ANIMAL")


func _test_ground_loot_contract(router: AndromedaInputRouter) -> void:
	var direct_near: Dictionary = router.resolve_pointer_click(
		MOUSE_BUTTON_LEFT, "GROUND_LOOT", Vector3.ZERO, "LOOT-NEAR", false, 0.5, true, true
	)
	_check("GROUND_LOOT_RADIUS_INCLUSIVE_0_5", direct_near.get("intent") == "PICKUP", JSON.stringify(direct_near))
	var direct_over_radius: Dictionary = router.resolve_pointer_click(
		MOUSE_BUTTON_LEFT, "GROUND_LOOT", Vector3.ZERO, "LOOT-FAR", false, 0.5001, true, true
	)
	_check("GROUND_LOOT_OVER_0_5_MUST_APPROACH", direct_over_radius.get("intent") == "APPROACH_PICKUP",
		JSON.stringify(direct_over_radius))
	var direct_unreachable: Dictionary = router.resolve_pointer_click(
		MOUSE_BUTTON_LEFT, "GROUND_LOOT", Vector3.ZERO, "LOOT-BLOCKED", false, 2.0, false, true
	)
	_check("GROUND_LOOT_INVALID_PATH_REJECTED", direct_unreachable.get("status") == "REJECTED"
		and direct_unreachable.get("reason") == "GROUND_LOOT_UNREACHABLE", JSON.stringify(direct_unreachable))
	var direct_unsettled: Dictionary = router.resolve_pointer_click(
		MOUSE_BUTTON_LEFT, "GROUND_LOOT", Vector3.ZERO, "LOOT-MOVING", false, 0.2, true, false
	)
	_check("GROUND_LOOT_BEFORE_SETTLED_REJECTED", direct_unsettled.get("status") == "REJECTED"
		and direct_unsettled.get("reason") == "GROUND_LOOT_NOT_SETTLED", JSON.stringify(direct_unsettled))

	var selection_before_loot: String = main.selected_target_ref()
	var destination_before_far_loot: Vector3 = player.requested_destination()
	var far_loot_click: Dictionary = _click_target(ground_loot, MOUSE_BUTTON_LEFT)
	_check("GROUND_LOOT_LEFT_CLICK_MOVEMENT_EXCEPTION", far_loot_click.get("status") == "PASS"
		and far_loot_click.get("intent") == "APPROACH_PICKUP", JSON.stringify(far_loot_click))
	_check("GROUND_LOOT_LEFT_CLICK_CHANGES_DESTINATION",
		not player.requested_destination().is_equal_approx(destination_before_far_loot)
		and _horizontal_distance(player.requested_destination(), ground_loot.global_position) < 0.08)
	_check("GROUND_LOOT_EXCEPTION_DOES_NOT_REPLACE_SELECTION", main.selected_target_ref() == selection_before_loot)
	_check("GROUND_LOOT_REMAINS_PHYSICAL_AFTER_APPROACH_INTENT", is_instance_valid(ground_loot)
		and ground_loot.is_inside_tree())
	_check("GROUND_LOOT_APPROACH_ENVELOPE_NOT_SUBMITTED", _valid_intent_envelope(
		far_loot_click, "APPROACH_PICKUP", ground_loot.target_ref
	) and far_loot_click.get("transport_submitted") == false)
	player.stop_local_prediction()

	var original_loot_position: Vector3 = ground_loot.global_position
	ground_loot.global_position = player.global_position + Vector3(0.4, 0.0, 0.0)
	await get_tree().physics_frame
	var destination_before_near_pickup: Vector3 = player.requested_destination()
	var near_loot_click: Dictionary = _click_target(ground_loot, MOUSE_BUTTON_LEFT)
	_check("PHYSICAL_LOOT_AT_0_4_M_PICKUP_INTENT", near_loot_click.get("status") == "PASS"
		and near_loot_click.get("intent") == "PICKUP", JSON.stringify(near_loot_click))
	_check("PICKUP_INTENT_DOES_NOT_TELEPORT_ITEM", ground_loot.global_position.distance_to(
		player.global_position + Vector3(0.4, 0.0, 0.0)
	) < 0.02)
	_check("PICKUP_INTENT_DOES_NOT_MOVE_PLAYER",
		player.requested_destination().is_equal_approx(destination_before_near_pickup))
	_check("PICKUP_REQUIRES_AUTHORITATIVE_RESULT", near_loot_click.get("gameplay_authority_preserved") == true
		and near_loot_click.get("transport_submitted") == false)
	_check("PICKUP_INTENT_DOES_NOT_DELETE_PHYSICAL_LOOT", is_instance_valid(ground_loot)
		and ground_loot.is_inside_tree())
	ground_loot.global_position = original_loot_position
	await get_tree().physics_frame

	var loot_count_before_idle: int = main.get_node("GroundLootRoot").get_child_count()
	await _wait_physics_frames(12)
	_check("AUTO_PICKUP_NOT_IMPLEMENTED_AS_REMOTE_COLLECTION",
		main.get_node("GroundLootRoot").get_child_count() == loot_count_before_idle)


func _test_right_click_matrix() -> void:
	var ground_destination := Vector3(-9.0, 0.0, 4.0)
	var right_ground: Dictionary = main.handle_pointer_event(_mouse_button(
		MOUSE_BUTTON_RIGHT, main.world_to_screen(ground_destination)
	))
	_check("RIGHT_CLICK_GROUND_MOVES", right_ground.get("status") == "PASS"
		and right_ground.get("intent") == "MOVE_TO_POINT", JSON.stringify(right_ground))
	_check("RIGHT_CLICK_GROUND_DESTINATION", _horizontal_distance(
		player.requested_destination(), ground_destination
	) < 0.08)
	var contextual_destination: Vector3 = player.requested_destination()

	var context_specs: Array[Dictionary] = [
		{"id": "NPC", "target": npc, "intent": "APPROACH_INTERACT", "cursor": "TALK"},
		{"id": "ENEMY", "target": enemy, "intent": "CHASE_ATTACK", "cursor": "ATTACK"},
		{"id": "ANIMAL", "target": animal, "intent": "APPROACH_INTERACT", "cursor": "INTERACT"},
		{"id": "TREE", "target": tree_resource, "intent": "APPROACH_HARVEST", "cursor": "HARVEST"},
		{"id": "ROCK", "target": rock_resource, "intent": "APPROACH_HARVEST", "cursor": "HARVEST"},
		{"id": "ORE", "target": ore_resource, "intent": "APPROACH_HARVEST", "cursor": "HARVEST"},
		{"id": "FLORA", "target": flora_resource, "intent": "APPROACH_HARVEST", "cursor": "HARVEST"},
		{"id": "OBJECT", "target": interactive_object, "intent": "APPROACH_INTERACT", "cursor": "INTERACT"},
		{"id": "VEHICLE", "target": vehicle, "intent": "APPROACH_INTERACT", "cursor": "INTERACT"},
	]
	var actor_positions: Dictionary = {
		npc.target_ref: npc.global_position,
		enemy.target_ref: enemy.global_position,
		animal.target_ref: animal.global_position,
	}
	for spec: Dictionary in context_specs:
		var target := spec.get("target") as AndromedaInteractionTarget
		var context_result: Dictionary = _click_target(target, MOUSE_BUTTON_RIGHT)
		var check_prefix: String = str(spec.get("id", "TARGET"))
		var expected_intent: String = str(spec.get("intent", ""))
		_check("RIGHT_%s_CONTEXT_INTENT" % check_prefix,
			context_result.get("status") == "PASS"
			and context_result.get("intent") == expected_intent
			and context_result.get("target_ref") == target.target_ref,
			JSON.stringify(context_result))
		_check("RIGHT_%s_CONTEXT_CURSOR" % check_prefix,
			context_result.get("cursor") == spec.get("cursor"), JSON.stringify(context_result))
		_check("RIGHT_%s_INTENT_ENVELOPE" % check_prefix,
			_valid_intent_envelope(context_result, expected_intent, target.target_ref))
		_check("RIGHT_%s_NOT_LOCALLY_RESOLVED" % check_prefix,
			context_result.get("transport_submitted") == false
			and context_result.get("gameplay_authority_preserved") == true
			and player.requested_destination().is_equal_approx(contextual_destination))
	_check("RIGHT_NPC_DOES_NOT_CHANGE_NEUTRAL_IDENTITY", not npc.hostile and npc.target_kind == "NPC")
	_check("RIGHT_ANIMAL_NOT_RECLASSIFIED_AS_ENEMY", not animal.hostile and animal.target_kind == "ANIMAL")
	_check("RIGHT_CONTEXT_DOES_NOT_TELEPORT_NPC", npc.global_position.is_equal_approx(actor_positions.get(npc.target_ref)))
	_check("RIGHT_CONTEXT_DOES_NOT_TELEPORT_ENEMY", enemy.global_position.is_equal_approx(actor_positions.get(enemy.target_ref)))
	_check("RIGHT_CONTEXT_DOES_NOT_TELEPORT_ANIMAL", animal.global_position.is_equal_approx(actor_positions.get(animal.target_ref)))

	var right_loot: Dictionary = _click_target(ground_loot, MOUSE_BUTTON_RIGHT)
	_check("RIGHT_GROUND_LOOT_APPROACH_COLLECT", right_loot.get("status") == "PASS"
		and right_loot.get("intent") == "APPROACH_PICKUP", JSON.stringify(right_loot))
	_check("RIGHT_GROUND_LOOT_PATH_REQUESTED", right_loot.get("requires_path") == true
		and right_loot.get("movement_result", {}).get("status") == "PASS")
	_check("RIGHT_GROUND_LOOT_NOT_COLLECTED_REMOTELY", is_instance_valid(ground_loot)
		and right_loot.get("transport_submitted") == false)
	player.stop_local_prediction()


func _test_overlap_depth_and_cursor_priority(router: AndromedaInputRouter) -> void:
	var cursor_wins: Dictionary = router.choose_pointer_target([
		{
			"target_ref": "OBJECT-UNDER-CURSOR",
			"target_kind": "SCENE_OBJECT",
			"screen_distance_px": 0.1,
			"depth_m": 20.0,
			"direct_hit": true,
		},
		{
			"target_ref": "LOOT-NOT-UNDER-CURSOR",
			"target_kind": "GROUND_LOOT",
			"screen_distance_px": 3.0,
			"depth_m": 2.0,
			"direct_hit": true,
		},
	])
	_check("ACTUAL_CURSOR_POSITION_BEATS_TYPE_AND_DEPTH",
		cursor_wins.get("target_ref") == "OBJECT-UNDER-CURSOR", JSON.stringify(cursor_wins))
	var depth_wins: Dictionary = router.choose_pointer_target([
		{
			"target_ref": "OBJECT-NEAR",
			"target_kind": "SCENE_OBJECT",
			"screen_distance_px": 0.0,
			"depth_m": 2.0,
			"direct_hit": true,
		},
		{
			"target_ref": "LOOT-FAR",
			"target_kind": "GROUND_LOOT",
			"screen_distance_px": 0.0,
			"depth_m": 3.0,
			"direct_hit": true,
		},
	])
	_check("DEPTH_BEATS_SEMANTIC_TYPE", depth_wins.get("target_ref") == "OBJECT-NEAR", JSON.stringify(depth_wins))
	var semantic_tie: Dictionary = router.choose_pointer_target([
		{
			"target_ref": "OBJECT-TIE",
			"target_kind": "SCENE_OBJECT",
			"screen_distance_px": 0.0,
			"depth_m": 3.0,
			"direct_hit": true,
		},
		{
			"target_ref": "LOOT-TIE",
			"target_kind": "GROUND_LOOT",
			"screen_distance_px": 0.0,
			"depth_m": 3.0,
			"direct_hit": true,
		},
	])
	_check("TYPE_USED_ONLY_AS_FINAL_TIEBREAK", semantic_tie.get("target_ref") == "LOOT-TIE",
		JSON.stringify(semantic_tie))

	var original_object_position: Vector3 = interactive_object.global_position
	var original_loot_position: Vector3 = ground_loot.global_position
	var far_loot_aim := Vector3(4.0, 0.28, -10.0)
	ground_loot.global_position = far_loot_aim - ground_loot.pointer_aim_offset
	var overlap_screen: Vector2 = main.world_to_screen(far_loot_aim)
	var ray_origin: Vector3 = camera_rig.camera.project_ray_origin(overlap_screen)
	var ray_direction: Vector3 = camera_rig.camera.project_ray_normal(overlap_screen)
	var far_depth: float = ray_origin.distance_to(far_loot_aim)
	var near_object_aim: Vector3 = ray_origin + ray_direction * (far_depth - 3.0)
	interactive_object.global_position = near_object_aim - interactive_object.pointer_aim_offset
	await _wait_physics_frames(2)
	var physical_overlap: Dictionary = main.pointer_target_at_screen(overlap_screen)
	_check("PHYSICAL_OVERLAP_RAYCAST_RESOLVED", physical_overlap.get("status") == "PASS", JSON.stringify(physical_overlap))
	_check("PHYSICAL_OVERLAP_NEAREST_VISUAL_TARGET_WINS",
		physical_overlap.get("target_ref") == interactive_object.target_ref, JSON.stringify(physical_overlap))
	var destination_before_overlap_click: Vector3 = player.requested_destination()
	var overlap_click: Dictionary = main.handle_pointer_event(_mouse_button(MOUSE_BUTTON_LEFT, overlap_screen))
	_check("CLICK_TWO_OVERLAPPED_TARGETS_SELECTS_FRONT_TARGET",
		overlap_click.get("intent") == "SELECT_TARGET"
		and overlap_click.get("target_ref") == interactive_object.target_ref,
		JSON.stringify(overlap_click))
	_check("OVERLAPPED_TARGET_CLICK_DOES_NOT_TRIGGER_FAR_LOOT_EXCEPTION",
		player.requested_destination().is_equal_approx(destination_before_overlap_click)
		and main.selected_target_ref() == interactive_object.target_ref)
	interactive_object.global_position = original_object_position
	ground_loot.global_position = original_loot_position
	await _wait_physics_frames(2)


func _test_blocker_and_inaccessible_targets() -> void:
	var blocked_position_before: Vector3 = blocked_loot.global_position
	var blocked_ray: Dictionary = main.raycast_target_from_world_ray(
		Vector3(-10.0, 0.35, 0.0),
		Vector3(-10.0, 0.35, -10.0)
	)
	_check("RAYCAST_BLOCKER_DETECTED", blocked_ray.get("blocked") == true
		and blocked_ray.get("blocker") == "B03RaycastBlocker", JSON.stringify(blocked_ray))
	_check("RAYCAST_DOES_NOT_CROSS_BLOCKING_COLLISION", not blocked_ray.has("target_ref"), JSON.stringify(blocked_ray))
	_check("BLOCKED_LOOT_NOT_TELEPORTED", blocked_loot.global_position.is_equal_approx(blocked_position_before))
	_check("BLOCKED_LOOT_REMAINS_PHYSICAL", is_instance_valid(blocked_loot) and blocked_loot.is_inside_tree())

	var unreachable_position_before: Vector3 = unreachable_loot.global_position
	var destination_before_unreachable: Vector3 = player.requested_destination()
	var unreachable_click: Dictionary = _click_target(unreachable_loot, MOUSE_BUTTON_LEFT)
	_check("INACCESSIBLE_LOOT_CLICK_REJECTED", unreachable_click.get("status") == "REJECTED"
		and unreachable_click.get("reason") == "GROUND_LOOT_UNREACHABLE", JSON.stringify(unreachable_click))
	_check("INACCESSIBLE_LOOT_PATH_PREVENTS_PICKUP", player.requested_destination().is_equal_approx(
		destination_before_unreachable
	))
	_check("INACCESSIBLE_LOOT_NOT_TELEPORTED", unreachable_loot.global_position.is_equal_approx(
		unreachable_position_before
	))
	_check("INACCESSIBLE_LOOT_NOT_DELETED", is_instance_valid(unreachable_loot)
		and unreachable_loot.is_inside_tree())

	var unsettled_position_before: Vector3 = unsettled_loot.global_position
	var unsettled_click: Dictionary = _click_target(unsettled_loot, MOUSE_BUTTON_RIGHT)
	_check("UNSETTLED_LOOT_CLICK_REJECTED", unsettled_click.get("status") == "REJECTED"
		and unsettled_click.get("reason") == "GROUND_LOOT_NOT_SETTLED", JSON.stringify(unsettled_click))
	_check("UNSETTLED_LOOT_NOT_TELEPORTED", unsettled_loot.global_position.is_equal_approx(unsettled_position_before))
	_check("UNSETTLED_LOOT_NOT_COLLECTED", is_instance_valid(unsettled_loot)
		and unsettled_loot.is_inside_tree())


func _test_no_gameplay_authority_surface(bridge: AndromedaRuntimeBridge) -> void:
	_check("BRIDGE_REMAINS_LOCAL_SESSION_STATE_WITHOUT_ROUNDTRIP",
		bridge.connection_state().get("state") == AndromedaRuntimeBridge.STATE_CONNECTING,
		JSON.stringify(bridge.connection_state()))
	for target: AndromedaInteractionTarget in [
		npc, enemy, animal, tree_resource, rock_resource, ore_resource, flora_resource,
		interactive_object, vehicle, ground_loot,
	]:
		_check("NO_DAMAGE_AUTHORITY_%s" % target.target_ref, not target.has_method("apply_damage")
			and not target.has_method("take_damage"))
		_check("NO_INVENTORY_AUTHORITY_%s" % target.target_ref, not target.has_method("grant_item")
			and not target.has_method("collect_authoritatively"))
	_check("NO_FINAL_AI_IMPLEMENTED_IN_B03", not enemy.has_method("choose_combat_action")
		and not npc.has_method("choose_dialogue_result") and not animal.has_method("choose_behavior"))
	_check("NO_LOOT_TABLE_VENDOR_GATHERING_QUEST_RESULTS", not main.has_node("LootTable")
		and not main.has_node("Vendor") and not main.has_node("QuestResolver"))


func _click_target(target: AndromedaInteractionTarget, button_index: int) -> Dictionary:
	return main.handle_pointer_event(_mouse_button(button_index, main.target_to_screen(target)))


func _valid_intent_envelope(result: Dictionary, command: String, target_ref: String) -> bool:
	var built_value: Variant = result.get("intent_envelope", {})
	if not built_value is Dictionary:
		return false
	var built: Dictionary = built_value
	if built.get("status") != "PASS":
		return false
	var envelope_value: Variant = built.get("envelope", {})
	if not envelope_value is Dictionary:
		return false
	var envelope: Dictionary = envelope_value
	var params_value: Variant = envelope.get("params", {})
	if not params_value is Dictionary:
		return false
	var params: Dictionary = params_value
	return (
		envelope.get("session_ref") == "B03-GATE-SESSION"
		and envelope.get("command") == command
		and params.get("target_ref") == target_ref
		and params.get("client_presentation_only") == true
		and not envelope.has("player_ref")
		and not params.has("player_ref")
		and not params.has("damage")
		and not params.has("inventory_grant")
	)


func _wait_for_navigation(max_frames: int) -> bool:
	for _frame_index: int in range(max_frames):
		if main.navigation_ready():
			return true
		await get_tree().physics_frame
	return false


func _wait_physics_frames(frame_count: int) -> void:
	for _frame_index: int in range(frame_count):
		await get_tree().physics_frame


func _mouse_button(button_index: int, position: Vector2) -> InputEventMouseButton:
	var event := InputEventMouseButton.new()
	event.button_index = button_index as MouseButton
	event.position = position
	event.global_position = position
	event.pressed = true
	return event


func _horizontal_distance(first: Vector3, second: Vector3) -> float:
	return Vector2(first.x, first.z).distance_to(Vector2(second.x, second.z))


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "B03_INTERACTION_TARGETS_NPC_ENEMY_RESOURCE_NODES",
		"acceptance_scope_pass": [],
		"partial_evidence_only": ["G16B-03", "G16B-04", "G16B-11", "G16B-20"],
		"not_run_by_b03": ["G16B-05", "G16B-21", "G16B-22"],
		"authority": "GODOT_TARGET_DETECTION_INTENT_PRESENTATION_ONLY",
		"backend_roundtrip_executed": false,
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_B03_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_B03_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_B03_SUMMARY: %s" % JSON.stringify(summary))
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
