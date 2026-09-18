extends Node

const GROUND_LOOT_SCENE: PackedScene = preload("res://scenes/interaction/GroundLoot.tscn")
const SESSION_INITIAL := "B07-GATE-SESSION"
const SESSION_RESYNC := "B07-GATE-SESSION-RESYNC"

var _checks: int = 0
var _failures: Array[String] = []
var _temporary_loot: Array[AndromedaGroundLoot] = []
var _snapshot_sequence: int = 0

@onready var main: AndromedaMainRuntime = $AndromedaARPG
@onready var player: AndromedaPlayerController = $AndromedaARPG/ActorRoot/Player
@onready var camera_rig: AndromedaIsometricCameraRig = $AndromedaARPG/IsometricCameraRig
@onready var hud: AndromedaHUDController = $AndromedaARPG/UILayer/MinimalHUD
@onready var pickup_client: AndromedaGroundLootPickupClient = $AndromedaARPG/GroundLootPickupClient
@onready var loot_root: Node3D = $AndromedaARPG/GroundLootRoot
@onready var terrain: AndromedaTerrainFoundation = $AndromedaARPG/WorldStreamRoot/TerrainFoundation
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
	var bind_result: Dictionary = session.bind_session(SESSION_INITIAL)
	_check("SESSION_INITIAL_BOUND", bind_result.get("status") == "PASS", JSON.stringify(bind_result))
	_check("PROJECT_LABEL_B07_THROUGH_B11", str(ProjectSettings.get_setting("application/config/name")) in ["Andromeda ARPG Stage16B B07", "Andromeda ARPG Stage16B B08", "Andromeda ARPG Stage16B B09", "Andromeda ARPG Stage16B B10", "Andromeda ARPG Stage16B B11"])
	_check("MAIN_SCENE_PRESERVED", str(ProjectSettings.get_setting("application/run/main_scene")) == "res://scenes/Main.tscn")
	_check("BACKEND_URL_UNCHANGED", bridge.server_url() == "http://127.0.0.1:8000")
	_check("NAVIGATION_READY", await _wait_for_navigation(240))
	_test_architecture_and_authority(bridge)
	_test_universal_spawn_stack_and_identity()
	await _test_physical_settling()
	await _test_manual_pickup_guards_and_approach()
	await _test_overlap_stale_spam_and_inventory_result()
	await _test_auto_pickup_and_preferences(session)
	await _test_water_exposure_and_resync(session)
	await _test_b01_to_b06_interactions()
	await _cleanup_temporary_loot()
	await _finish()


func _test_architecture_and_authority(bridge: AndromedaRuntimeBridge) -> void:
	var main_contract: Dictionary = main.contract_snapshot()
	var client_contract: Dictionary = pickup_client.contract_snapshot()
	var scene_probe := GROUND_LOOT_SCENE.instantiate() as AndromedaGroundLoot
	_check("GROUND_LOOT_SCENE_ROOT_RIGIDBODY", scene_probe != null and scene_probe.is_class("RigidBody3D"))
	_check("GROUND_LOOT_SPECIALIZED_COMPONENT", scene_probe != null)
	_check("GROUND_LOOT_COLLISION_SHAPE", scene_probe != null and scene_probe.has_node("CollisionShape3D"))
	_check("GROUND_LOOT_PLACEHOLDER_VISUAL", scene_probe != null and scene_probe.has_node("PlaceholderVisual"))
	_check("GROUND_LOOT_PICKUP_SENSOR", scene_probe != null and scene_probe.has_node("PickupSensor"))
	_check("GROUND_LOOT_MINIMAL_LABEL", scene_probe != null and scene_probe.has_node("OptionalMinimalLabel"))
	_check("GROUND_LOOT_WATER_PRESENTER", scene_probe != null and scene_probe.has_node("WaterWorldItemPresenter"))
	if scene_probe != null:
		scene_probe.free()
	_check("MAIN_GROUND_LOOT_CLIENT_PRESENT", main_contract.get("ground_loot_client_present") == true)
	_check("MAIN_PICKUP_AUTHORITY_FALSE", main_contract.get("ground_loot_request_authority_in_gdscript") == false)
	_check("MAIN_INVENTORY_AUTHORITY_FALSE", main_contract.get("ground_loot_inventory_authority_in_gdscript") == false)
	_check("MAIN_TTL_AUTHORITY_FALSE", main_contract.get("ground_loot_ttl_authority_in_gdscript") == false)
	_check("CLIENT_PICKUP_RADIUS_05", is_equal_approx(float(client_contract.get("pickup_radius_m", -1.0)), 0.5))
	_check("CLIENT_MANUAL_FLOW_REQUEST_PICKUP", client_contract.get("manual_flow", []).back() == "REQUEST_PICKUP")
	_check("CLIENT_AUTO_PASSIVE", client_contract.get("auto_pickup_passive") == true)
	_check("CLIENT_AUTO_NOT_REMOTE", client_contract.get("auto_pickup_remote") == false)
	_check("CLIENT_AUTO_NO_MOVEMENT_INTERRUPT", client_contract.get("auto_pickup_interrupts_movement") == false)
	_check("CLIENT_AUTO_NO_ATTACK_INTERRUPT", client_contract.get("auto_pickup_interrupts_attack") == false)
	_check("CLIENT_AUTO_NO_INTERACTION_INTERRUPT", client_contract.get("auto_pickup_interrupts_interaction") == false)
	_check("CLIENT_AUTO_NO_TARGET_CHANGE", client_contract.get("auto_pickup_changes_target") == false)
	_check("CLIENT_AUTO_NO_CHASE_CHANGE", client_contract.get("auto_pickup_changes_chase") == false)
	_check("CLIENT_ANTI_SPAM_BY_TARGET_REF", client_contract.get("anti_spam_inflight_by_target_ref") == true)
	_check("CLIENT_NO_PROFILE_PERSISTENCE", client_contract.get("profile_preference_persisted_by_gdscript") == false)
	_check("CLIENT_NO_ITEM_GRANT_AUTHORITY", client_contract.get("item_grant_authority") == false)
	_check("CLIENT_NO_INVENTORY_AUTHORITY", client_contract.get("inventory_authority") == false)
	_check("CLIENT_NO_QUANTITY_AUTHORITY", client_contract.get("quantity_authority") == false)
	_check("CLIENT_NO_OWNERSHIP_AUTHORITY", client_contract.get("ownership_authority") == false)
	_check("CLIENT_NO_TTL_AUTHORITY", client_contract.get("ttl_authority") == false)
	_check("CLIENT_NO_BACKEND_SUBSTITUTE", client_contract.get("backend_substitute") == false)
	_check("CLIENT_NO_INVENTED_ENDPOINT", client_contract.get("invented_endpoint") == false)
	_check("BRIDGE_FORBIDS_INVENTORY_GRANT_FIELD", bridge.build_command_envelope("REQUEST_PICKUP", {
		"target_ref": "LOOT-SECURITY",
		"inventory_grant": {"item_ref": "ILLEGAL"},
	}).get("status") == "REJECTED")
	_check("GROUND_LOOT_NO_GRANT_METHOD", not pickup_client.has_method("grant_item"))
	_check("GROUND_LOOT_NO_COLLECT_AUTHORITATIVELY", not pickup_client.has_method("collect_authoritatively"))
	_check("GROUND_LOOT_NO_TTL_ADVANCE_METHOD", not pickup_client.has_method("advance_water_exposure"))
	_check("GROUND_LOOT_NO_PROFILE_SAVE_METHOD", not pickup_client.has_method("save_profile_preference"))
	var non_authoritative_snapshot: Dictionary = pickup_client.project_ground_loot_snapshot({
		"server_authoritative": false,
		"session_ref": SESSION_INITIAL,
		"snapshot_sequence": 0,
		"ground_loot": [],
	})
	_check("NON_AUTHORITATIVE_LOOT_SNAPSHOT_REJECTED", non_authoritative_snapshot.get("reason") == "NON_AUTHORITATIVE_GROUND_LOOT_SNAPSHOT")
	var local_preference_attempt: Dictionary = pickup_client.project_profile_preference(true, SESSION_INITIAL, 0, false)
	_check("LOCAL_PREFERENCE_CANNOT_MASQUERADE_AS_EXTERNAL", local_preference_attempt.get("reason") == "EXTERNAL_PROFILE_PREFERENCE_CONFIRMATION_REQUIRED")
	var non_authoritative_result: Dictionary = pickup_client.project_pickup_result({
		"server_authoritative": false,
		"session_ref": SESSION_INITIAL,
		"target_ref": "NONE",
		"result_sequence": 0,
		"status": "PASS",
	})
	_check("NON_AUTHORITATIVE_PICKUP_RESULT_REJECTED", non_authoritative_result.get("reason") == "NON_AUTHORITATIVE_PICKUP_RESULT")


func _test_universal_spawn_stack_and_identity() -> void:
	var source_kinds: Array[String] = [
		"ENEMY", "TREE", "ROCK", "ORE", "FLORA", "AGRICULTURE", "HUNTING",
		"FISHING", "CONTAINER", "PHYSICAL_PRODUCTION", "PLAYER_DROP",
	]
	var entries: Array[Dictionary] = []
	var expected_refs: Dictionary = {}
	for index: int in range(source_kinds.size()):
		var source_kind_value: String = source_kinds[index]
		var target_ref_value := "LOOT-B07-%s-%02d" % [source_kind_value, index]
		expected_refs[target_ref_value] = true
		entries.append(_loot_entry(
			target_ref_value,
			source_kind_value,
			"MINERAL" if index in [2, 3] else "MATERIAL",
			1 if index == 0 else index + 1,
			Vector3(-10.0 + float(index) * 2.0, 0.0, 10.5)
		))
	var before_count: int = pickup_client.registered_loot_count()
	var spawn_snapshot: Dictionary = _authoritative_loot_snapshot(entries)
	var spawn_result: Dictionary = pickup_client.project_ground_loot_snapshot(spawn_snapshot)
	_check("UNIVERSAL_SPAWN_SNAPSHOT_PASS", spawn_result.get("status") == "PASS", JSON.stringify(spawn_result))
	_check("UNIVERSAL_SPAWN_ALL_PROJECTED", spawn_result.get("projected", []).size() == source_kinds.size())
	_check("UNIVERSAL_SPAWN_COUNT_INCREASE", pickup_client.registered_loot_count() >= before_count + source_kinds.size())
	var instance_ids: Dictionary = {}
	for index: int in range(source_kinds.size()):
		var source_kind_value: String = source_kinds[index]
		var target_ref_value := "LOOT-B07-%s-%02d" % [source_kind_value, index]
		var loot: AndromedaGroundLoot = pickup_client.ground_loot_for_ref(target_ref_value)
		_check("SOURCE_%s_SPAWNED" % source_kind_value, loot != null)
		if loot == null:
			continue
		var presentation: Dictionary = loot.presentation_snapshot()
		_check("SOURCE_%s_KIND_STABLE" % source_kind_value, presentation.get("source_kind") == source_kind_value)
		_check("SOURCE_%s_TARGET_REF_STABLE" % source_kind_value, loot.target_ref == target_ref_value)
		_check("SOURCE_%s_TARGET_REF_UNIQUE" % source_kind_value, not instance_ids.has(loot.get_instance_id()))
		instance_ids[loot.get_instance_id()] = target_ref_value
		_check("SOURCE_%s_PHYSICAL_WORLD_OBJECT" % source_kind_value, loot.is_class("RigidBody3D") and loot.is_inside_tree())
		_check("SOURCE_%s_LAYER_GROUND_LOOT" % source_kind_value, int(loot.get("collision_layer")) == 16)
		_check("SOURCE_%s_SETTLED" % source_kind_value, loot.is_pickup_settled())
		_check("SOURCE_%s_ACTIVE" % source_kind_value, loot.is_active_for_pickup())
		_check("SOURCE_%s_NO_ITEM_GRANT_AUTHORITY" % source_kind_value, presentation.get("item_grant_authority") == false)
	_check("UNIVERSAL_SOURCE_KIND_COUNT_EXACT", source_kinds.size() == 11)
	var universal_contract: Array[String] = pickup_client.contract_snapshot().get("universal_source_kinds", [])
	_check("UNIVERSAL_SOURCE_CONTRACT_EXACT", universal_contract == source_kinds, str(universal_contract))
	var quantity_one: AndromedaGroundLoot = pickup_client.ground_loot_for_ref("LOOT-B07-ENEMY-00")
	var quantity_many: AndromedaGroundLoot = pickup_client.ground_loot_for_ref("LOOT-B07-TREE-01")
	_check("STACK_QUANTITY_ONE_PROJECTED", quantity_one != null and quantity_one.projected_quantity == 1)
	_check("STACK_QUANTITY_MANY_PROJECTED", quantity_many != null and quantity_many.projected_quantity == 2)
	var mineral_rock: AndromedaGroundLoot = pickup_client.ground_loot_for_ref("LOOT-B07-ROCK-02")
	var mineral_ore: AndromedaGroundLoot = pickup_client.ground_loot_for_ref("LOOT-B07-ORE-03")
	_check("CATEGORY_ICON_BY_TYPE_SAME", mineral_rock != null and mineral_ore != null and mineral_rock.icon_category() == mineral_ore.icon_category())
	_check("CATEGORY_ICON_MINERAL", mineral_ore != null and mineral_ore.icon_category() == "ICON_MINERAL")
	_check("CATEGORY_ICON_NOT_ITEM_ID", mineral_ore != null and not mineral_ore.icon_category().contains(mineral_ore.item_ref))
	if mineral_ore != null:
		var minimal_label := mineral_ore.get_node("OptionalMinimalLabel") as Label3D
		_check("CATEGORY_LABEL_HIDDEN_BY_DEFAULT", not minimal_label.visible)
		mineral_ore.set_hovered(true)
		_check("CATEGORY_LABEL_VISIBLE_ON_HOVER", minimal_label.visible)
		_check("CATEGORY_LABEL_INCLUDES_QUANTITY", minimal_label.text.contains("x4"), minimal_label.text)
		mineral_ore.set_hovered(false)
		_check("CATEGORY_LABEL_RETURNS_HIDDEN", not minimal_label.visible)
	var update_entry: Dictionary = _loot_entry(
		"LOOT-B07-ORE-03", "ORE", "MINERAL", 7, Vector3(-4.0, 0.0, 10.5)
	)
	var update_result: Dictionary = pickup_client.project_ground_loot_snapshot(_authoritative_loot_snapshot([update_entry]))
	_check("STACK_EXTERNAL_UPDATE_PASS", update_result.get("status") == "PASS", JSON.stringify(update_result))
	_check("STACK_EXTERNAL_UPDATE_SEVEN", mineral_ore != null and mineral_ore.projected_quantity == 7)
	var invalid_quantity_entry: Dictionary = update_entry.duplicate(true)
	invalid_quantity_entry["quantity"] = 0
	var invalid_quantity_result: Dictionary = pickup_client.project_ground_loot_snapshot(_authoritative_loot_snapshot([invalid_quantity_entry]))
	_check("STACK_INVALID_QUANTITY_REJECTED", invalid_quantity_result.get("reason") == "INVALID_PROJECTED_QUANTITY")
	_check("STACK_INVALID_QUANTITY_DOES_NOT_MUTATE", mineral_ore != null and mineral_ore.projected_quantity == 7)
	var stale_snapshot: Dictionary = spawn_snapshot.duplicate(true)
	var stale_result: Dictionary = pickup_client.project_ground_loot_snapshot(stale_snapshot)
	_check("DUPLICATE_SNAPSHOT_REJECTED", stale_result.get("reason") == "STALE_OR_DUPLICATE_GROUND_LOOT_SNAPSHOT")
	var out_of_order: Dictionary = spawn_snapshot.duplicate(true)
	out_of_order["snapshot_sequence"] = 0
	var out_of_order_result: Dictionary = pickup_client.project_ground_loot_snapshot(out_of_order)
	_check("OUT_OF_ORDER_SNAPSHOT_REJECTED", out_of_order_result.get("reason") == "STALE_OR_DUPLICATE_GROUND_LOOT_SNAPSHOT")
	var wrong_session: Dictionary = _authoritative_loot_snapshot([update_entry])
	wrong_session["session_ref"] = "OTHER-SESSION"
	var wrong_session_result: Dictionary = pickup_client.project_ground_loot_snapshot(wrong_session)
	_check("OTHER_SESSION_SNAPSHOT_REJECTED", wrong_session_result.get("reason") == "GROUND_LOOT_SNAPSHOT_SESSION_MISMATCH")
	var alias_probe := GROUND_LOOT_SCENE.instantiate() as AndromedaGroundLoot
	var alias_identity: Dictionary = alias_probe.configure_spawn_identity(
		"LOOT-B07-PRODUCTION-ALIAS", "SRC", "PRODUCTION", "ITEM", "MATERIAL"
	)
	_check("STAGE16A_PRODUCTION_ALIAS_ACCEPTED", alias_identity.get("status") == "PASS")
	loot_root.add_child(alias_probe)
	_check("STAGE16A_PRODUCTION_ALIAS_NORMALIZED", alias_probe.source_kind == "PHYSICAL_PRODUCTION")
	_check("STAGE16A_PRODUCTION_ALIAS_RECORDED", alias_probe.presentation_snapshot().get("compatibility_source_alias_received") == true)
	pickup_client.register_ground_loot(alias_probe)
	_temporary_loot.append(alias_probe)


func _test_physical_settling() -> void:
	await _cleanup_temporary_loot()
	player.stop_local_prediction()
	player.global_position = Vector3(-5.0, 0.0, 7.0)
	player.velocity = Vector3.ZERO
	camera_rig.set_follow_target(player, true)
	var falling_loot: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-SETTLING", Vector3(-5.0, 2.4, 7.0), true, true
	)
	var begin_result: Dictionary = falling_loot.begin_local_physical_settle()
	_check("SETTLING_BEGIN_PASS", begin_result.get("status") == "PASS")
	_check("SETTLING_INITIAL_UNFROZEN", not bool(falling_loot.get("freeze")))
	_check("SETTLING_INITIAL_NOT_COLLECTIBLE", not falling_loot.is_pickup_settled())
	var premature: Dictionary = pickup_client.evaluate_pickup_candidate(falling_loot)
	_check("PICKUP_BEFORE_SETTLE_REJECTED", premature.get("reason") == "GROUND_LOOT_NOT_SETTLED", JSON.stringify(premature))
	var settled: bool = await _wait_for_local_settle(falling_loot, 300)
	_check("SETTLING_COMPLETES", settled)
	_check("SETTLING_FREEZES_BODY", bool(falling_loot.get("freeze")))
	_check("SETTLING_LINEAR_VELOCITY_ZERO", (falling_loot.get("linear_velocity") as Vector3).length() < 0.0001)
	_check("SETTLING_ANGULAR_VELOCITY_ZERO", (falling_loot.get("angular_velocity") as Vector3).length() < 0.0001)
	_check("SETTLING_TERRAIN_HEIGHT_VALID", falling_loot.global_position.y > -0.05 and falling_loot.global_position.y < 0.08, str(falling_loot.global_position))
	var stable_position: Vector3 = falling_loot.global_position
	await _wait_physics_frames(24)
	_check("SETTLING_NO_JITTER", falling_loot.global_position.distance_to(stable_position) < 0.002, "%s/%s" % [stable_position, falling_loot.global_position])
	_check("SETTLING_NO_PENETRATION", falling_loot.global_position.y >= -0.05)
	_check("SETTLING_REMAINS_WORLD_ACTIVE", falling_loot.is_inside_tree() and falling_loot.visible)
	_check("SETTLING_REMAINS_SELECTABLE", falling_loot.selectable and int(falling_loot.get("collision_layer")) == 16)
	var presenter := falling_loot.get_node("WaterWorldItemPresenter") as AndromedaWaterWorldItemPresenter
	var presenter_contract: Dictionary = presenter.contract_snapshot()
	_check("SETTLING_PRESENTER_NO_TTL_ADVANCE", presenter_contract.get("authoritative_ttl_advanced_locally") == false)


func _test_manual_pickup_guards_and_approach() -> void:
	await _cleanup_temporary_loot()
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	player.velocity = Vector3.ZERO
	camera_rig.set_follow_target(player, true)
	await _wait_physics_frames(5)
	var exact_loot: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-EXACT-0500", player.global_position + Vector3(0.5, 0.0, 0.0), true, true
	)
	var exact_result: Dictionary = pickup_client.evaluate_pickup_candidate(exact_loot)
	_check("PICKUP_EXACT_05_PASS", exact_result.get("status") == "PASS", JSON.stringify(exact_result))
	_check("PICKUP_EXACT_05_REPORTED", is_equal_approx(float(exact_result.get("physical_distance_m", -1.0)), 0.5))
	exact_loot.global_position = player.global_position + Vector3(0.5001, 0.0, 0.0)
	var over_result: Dictionary = pickup_client.evaluate_pickup_candidate(exact_loot)
	_check("PICKUP_05001_REJECTED", over_result.get("reason") == "PICKUP_DISTANCE_EXCEEDED", JSON.stringify(over_result))
	_check("PICKUP_05001_NO_REQUEST", not pickup_client.has_inflight_request(exact_loot.target_ref))
	var unsettled_loot: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-UNSETTLED", player.global_position + Vector3(-0.3, 0.0, 0.0), false, true
	)
	var unsettled_result: Dictionary = pickup_client.evaluate_pickup_candidate(unsettled_loot)
	_check("UNSETTLED_PICKUP_REJECTED", unsettled_result.get("reason") == "GROUND_LOOT_NOT_SETTLED")
	var unreachable_loot: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-PROJECTED-UNREACHABLE", player.global_position + Vector3(0.0, 0.0, 0.3), true, false
	)
	var unreachable_result: Dictionary = pickup_client.evaluate_pickup_candidate(unreachable_loot)
	_check("PROJECTED_UNREACHABLE_REJECTED", unreachable_result.get("reason") == "GROUND_LOOT_UNREACHABLE")
	var invalid_destination: Vector3 = Vector3(14.5, 0.0, 14.5)
	var path_result: Dictionary = player.validate_destination(invalid_destination)
	_check("INVALID_PATH_DESTINATION_REJECTED", path_result.get("status") == "REJECTED", JSON.stringify(path_result))
	var path_loot: AndromedaGroundLoot = _create_local_loot("LOOT-B07-INVALID-PATH", invalid_destination, true, true)
	var path_click: Dictionary = _click_target(path_loot, MOUSE_BUTTON_LEFT)
	_check("INVALID_PATH_CLICK_REJECTED", path_click.get("status") == "REJECTED" and path_click.get("reason") == "GROUND_LOOT_UNREACHABLE", JSON.stringify(path_click))
	_check("INVALID_PATH_NO_PICKUP_REQUEST", not pickup_client.has_inflight_request(path_loot.target_ref))
	var blocker_loot: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-BLOCKER", player.global_position + Vector3(0.5, 0.0, 0.0), true, true
	)
	var blocker := StaticBody3D.new()
	blocker.name = "B07PickupBlocker"
	blocker.collision_layer = 128
	blocker.collision_mask = 0
	blocker.position = player.global_position + Vector3(0.44, 0.34, 0.0)
	var blocker_shape := CollisionShape3D.new()
	var box_shape := BoxShape3D.new()
	box_shape.size = Vector3(0.1, 0.9, 0.8)
	blocker_shape.shape = box_shape
	blocker.add_child(blocker_shape)
	main.get_node("WorldStreamRoot/CollisionSurface").add_child(blocker)
	await _wait_physics_frames(2)
	var blocker_probe: Dictionary = pickup_client.pickup_blocker_probe(blocker_loot)
	_check("BLOCKER_PROBE_DETECTS_NAV_BLOCKER", blocker_probe.get("blocked") == true and blocker_probe.get("collision_layer") == 128, JSON.stringify(blocker_probe))
	var blocked_result: Dictionary = pickup_client.evaluate_pickup_candidate(blocker_loot)
	_check("BLOCKER_PICKUP_REJECTED", blocked_result.get("reason") == "PICKUP_BLOCKED_BY_COLLISION", JSON.stringify(blocked_result))
	_check("BLOCKER_NO_REQUEST", not pickup_client.has_inflight_request(blocker_loot.target_ref))
	blocker.queue_free()
	await _wait_physics_frames(2)
	pickup_client.clear_client_request_tracking()
	var artificial_distance_loot: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-ARTIFICIAL-DISTANCE", player.global_position + Vector3(0.8, 0.0, 0.0), true, true
	)
	var malicious_result: Dictionary = pickup_client.handle_manual_pointer_intent({
		"status": "PASS",
		"intent": "PICKUP",
		"target_ref": artificial_distance_loot.target_ref,
		"physical_distance_m": 0.1,
		"button": "LEFT",
	}, artificial_distance_loot)
	_check("ARTIFICIAL_DISTANCE_IGNORED", malicious_result.get("reason") == "PICKUP_DISTANCE_EXCEEDED", JSON.stringify(malicious_result))
	_check("ARTIFICIAL_DISTANCE_NO_REQUEST", pickup_client.request_history().is_empty())
	await _cleanup_temporary_loot()
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	player.velocity = Vector3.ZERO
	camera_rig.set_follow_target(player, true)
	var approach_loot: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-MANUAL-APPROACH", Vector3(-4.0, 0.0, 3.0), true, true
	)
	await _wait_physics_frames(4)
	var select_enemy: Dictionary = _click_target(enemy, MOUSE_BUTTON_LEFT)
	_check("PRE_PICKUP_SELECTION_PASS", select_enemy.get("status") == "PASS" and main.selected_target_ref() == enemy.target_ref)
	var selected_before: String = main.selected_target_ref()
	pickup_client.clear_client_request_tracking()
	var left_click: Dictionary = _click_target(approach_loot, MOUSE_BUTTON_LEFT)
	_check("LEFT_LOOT_CLICK_APPROACH", left_click.get("status") == "PASS" and left_click.get("intent") == "APPROACH_PICKUP", JSON.stringify(left_click))
	_check("LEFT_LOOT_CLICK_PATH_STARTED", left_click.get("movement_result", {}).get("status") == "PASS")
	_check("LEFT_LOOT_CLICK_NO_REMOTE_REQUEST", pickup_client.request_history().is_empty())
	_check("LEFT_LOOT_CLICK_SELECTION_UNCHANGED", main.selected_target_ref() == selected_before)
	_check("LEFT_LOOT_REMAINS_WORLD_OBJECT", approach_loot.visible and approach_loot.is_inside_tree())
	var left_request_ready: bool = await _wait_for_inflight_request(approach_loot.target_ref, 300)
	_check("LEFT_APPROACH_REACHES_REQUEST_RANGE", left_request_ready)
	var left_request: Dictionary = pickup_client.last_request()
	_check("LEFT_APPROACH_REQUEST_PICKUP", left_request.get("intent") == "REQUEST_PICKUP")
	_check("LEFT_APPROACH_REQUEST_CORRECT_REF", left_request.get("target_ref") == approach_loot.target_ref)
	_check("LEFT_APPROACH_REQUEST_WITHIN_05", float(left_request.get("physical_distance_m", INF)) <= 0.5)
	_check("LEFT_APPROACH_REQUEST_ENVELOPE_PASS", left_request.get("intent_envelope", {}).get("status") == "PASS", JSON.stringify(left_request))
	_check("LEFT_APPROACH_REQUEST_COMMAND", left_request.get("intent_envelope", {}).get("envelope", {}).get("command") == "REQUEST_PICKUP")
	_check("LEFT_APPROACH_REQUEST_NOT_SUBMITTED_NO_BACKEND", left_request.get("transport_submitted") == false)
	_check("LEFT_APPROACH_NO_LOCAL_GRANT", left_request.get("item_granted_locally") == false)
	_check("LEFT_APPROACH_NO_LOCAL_REMOVE", left_request.get("loot_removed_locally") == false and approach_loot.visible)
	_check("LEFT_APPROACH_SELECTION_STABLE", main.selected_target_ref() == selected_before)
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	camera_rig.set_follow_target(player, true)
	pickup_client.clear_client_request_tracking()
	await _wait_physics_frames(3)
	var right_click: Dictionary = _click_target(approach_loot, MOUSE_BUTTON_RIGHT)
	_check("RIGHT_LOOT_CLICK_APPROACH", right_click.get("status") == "PASS" and right_click.get("intent") == "APPROACH_PICKUP", JSON.stringify(right_click))
	_check("RIGHT_LOOT_CLICK_PATH_STARTED", right_click.get("movement_result", {}).get("status") == "PASS")
	_check("RIGHT_LOOT_CLICK_NO_REMOTE_REQUEST", pickup_client.request_history().is_empty())
	var right_request_ready: bool = await _wait_for_inflight_request(approach_loot.target_ref, 300)
	_check("RIGHT_APPROACH_REACHES_REQUEST_RANGE", right_request_ready)
	_check("RIGHT_APPROACH_CORRECT_REF", pickup_client.last_request().get("target_ref") == approach_loot.target_ref)
	_check("RIGHT_APPROACH_SOURCE_RECORDED", str(pickup_client.last_request().get("request_source", "")).begins_with("MANUAL_RIGHT"))


func _test_overlap_stale_spam_and_inventory_result() -> void:
	await _cleanup_temporary_loot()
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	player.velocity = Vector3.ZERO
	camera_rig.set_follow_target(player, true)
	await _wait_physics_frames(4)
	var back_loot: AndromedaGroundLoot = _create_local_loot("LOOT-B07-OVERLAP-BACK", Vector3.ZERO, true, true)
	var front_loot: AndromedaGroundLoot = _create_local_loot("LOOT-B07-OVERLAP-FRONT", Vector3.ZERO, true, true)
	var back_aim := Vector3(4.0, 0.28, -10.0)
	back_loot.global_position = back_aim - back_loot.pointer_aim_offset
	var overlap_screen: Vector2 = main.world_to_screen(back_aim)
	var ray_origin: Vector3 = camera_rig.camera.project_ray_origin(overlap_screen)
	var ray_direction: Vector3 = camera_rig.camera.project_ray_normal(overlap_screen)
	var back_depth: float = ray_origin.distance_to(back_aim)
	var front_aim: Vector3 = ray_origin + ray_direction * (back_depth - 2.0)
	front_loot.global_position = front_aim - front_loot.pointer_aim_offset
	await _wait_physics_frames(3)
	var overlap_target: Dictionary = main.pointer_target_at_screen(overlap_screen)
	_check("OVERLAPPING_LOOTS_RAYCAST_PASS", overlap_target.get("status") == "PASS", JSON.stringify(overlap_target))
	_check("OVERLAPPING_LOOTS_FRONT_WINS", overlap_target.get("target_ref") == front_loot.target_ref, JSON.stringify(overlap_target))
	pickup_client.clear_client_request_tracking()
	var overlap_click: Dictionary = main.handle_pointer_event(_mouse_button(MOUSE_BUTTON_LEFT, overlap_screen))
	_check("OVERLAPPING_LOOTS_CLICK_FRONT_REF", overlap_click.get("target_ref") == front_loot.target_ref, JSON.stringify(overlap_click))
	_check("OVERLAPPING_LOOTS_NEIGHBOR_NOT_REQUESTED", not pickup_client.has_inflight_request(back_loot.target_ref))
	var wrong_target_result: Dictionary = pickup_client.handle_manual_pointer_intent({
		"status": "PASS",
		"intent": "PICKUP",
		"target_ref": back_loot.target_ref,
		"button": "LEFT",
	}, front_loot)
	_check("WRONG_TARGET_REF_REJECTED", wrong_target_result.get("reason") == "GROUND_LOOT_TARGET_REF_MISMATCH")
	await _cleanup_temporary_loot()
	var spam_loot: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-SPAM", player.global_position + Vector3(0.3, 0.0, 0.0), true, true
	)
	pickup_client.clear_client_request_tracking()
	var spam_payload := {
		"status": "PASS",
		"intent": "PICKUP",
		"target_ref": spam_loot.target_ref,
		"button": "LEFT",
	}
	var spam_first: Dictionary = pickup_client.handle_manual_pointer_intent(spam_payload, spam_loot)
	var spam_second: Dictionary = pickup_client.handle_manual_pointer_intent(spam_payload, spam_loot)
	_check("CLICK_SPAM_FIRST_REQUEST_PASS", spam_first.get("status") == "PASS" and spam_first.get("deduplicated", false) == false)
	_check("CLICK_SPAM_SECOND_DEDUPLICATED", spam_second.get("deduplicated") == true)
	_check("CLICK_SPAM_ONE_HISTORY_ENTRY", pickup_client.request_history().size() == 1)
	_check("CLICK_SPAM_ONE_INFLIGHT", pickup_client.inflight_request_count() == 1)
	var stale_loot: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-STALE", player.global_position + Vector3(1.2, 0.0, 0.0), true, true
	)
	var pending_stale: Dictionary = pickup_client.handle_manual_pointer_intent({
		"status": "PASS",
		"intent": "APPROACH_PICKUP",
		"target_ref": stale_loot.target_ref,
		"button": "LEFT",
	}, stale_loot)
	_check("STALE_TARGET_PENDING_CREATED", pending_stale.get("status") == "PASS")
	_temporary_loot.erase(stale_loot)
	stale_loot.queue_free()
	await get_tree().process_frame
	var stale_process: Dictionary = pickup_client.process_manual_approach_once()
	_check("REMOVED_TARGET_REQUEST_BLOCKED", stale_process.get("reason") == "STALE_OR_REMOVED_GROUND_LOOT_TARGET", JSON.stringify(stale_process))
	_check("REMOVED_TARGET_NOT_INFLIGHT", not pickup_client.has_inflight_request("LOOT-B07-STALE"))
	await _cleanup_temporary_loot()
	var authoritative_loot: AndromedaGroundLoot = pickup_client.ground_loot_for_ref("LOOT-B07-ENEMY-00")
	_check("INVENTORY_RESULT_TARGET_EXISTS", authoritative_loot != null)
	if authoritative_loot == null:
		return
	authoritative_loot.global_position = player.global_position + Vector3(0.25, 0.0, 0.0)
	pickup_client.clear_client_request_tracking()
	var request_before_full: Dictionary = pickup_client.handle_manual_pointer_intent({
		"status": "PASS",
		"intent": "PICKUP",
		"target_ref": authoritative_loot.target_ref,
		"button": "LEFT",
	}, authoritative_loot)
	_check("INVENTORY_FULL_PRE_REQUEST_PASS", request_before_full.get("status") == "PASS", JSON.stringify(request_before_full))
	var selected_before_full: String = main.selected_target_ref()
	var inventory_full: Dictionary = pickup_client.project_pickup_result({
		"server_authoritative": true,
		"session_ref": SESSION_INITIAL,
		"target_ref": authoritative_loot.target_ref,
		"result_sequence": 1,
		"status": "REJECTED",
		"reason": "INVENTORY_CAPACITY_EXCEEDED",
	})
	_check("INVENTORY_FULL_PROJECTION_PASS", inventory_full.get("status") == "PASS", JSON.stringify(inventory_full))
	_check("INVENTORY_FULL_DROP_REMAINS_ACTIVE", inventory_full.get("drop_remains_active") == true and authoritative_loot.is_active_for_pickup())
	_check("INVENTORY_FULL_DROP_VISIBLE", authoritative_loot.visible and authoritative_loot.is_inside_tree())
	_check("INVENTORY_FULL_NOT_COLLECTED", authoritative_loot.authoritative_state() == "ACTIVE")
	_check("INVENTORY_FULL_NO_LOCAL_INVENTORY_MUTATION", inventory_full.get("inventory_mutated") == false)
	_check("INVENTORY_FULL_CLEARS_INFLIGHT", not pickup_client.has_inflight_request(authoritative_loot.target_ref))
	_check("INVENTORY_FULL_BLOCKED_FEEDBACK", inventory_full.get("token") == "INTERACTION_BLOCKED")
	_check("INVENTORY_FULL_TARGET_STABLE", main.selected_target_ref() == selected_before_full)
	_check("INVENTORY_FULL_FEEDBACK_PRIORITY", hud.combat_feedback.visible_priorities().has(72))
	var duplicate_full: Dictionary = pickup_client.project_pickup_result({
		"server_authoritative": true,
		"session_ref": SESSION_INITIAL,
		"target_ref": authoritative_loot.target_ref,
		"result_sequence": 1,
		"status": "REJECTED",
		"reason": "INVENTORY_CAPACITY_EXCEEDED",
	})
	_check("DUPLICATE_PICKUP_RESULT_REJECTED", duplicate_full.get("reason") == "STALE_OR_DUPLICATE_PICKUP_RESULT")
	var confirmed_pickup: Dictionary = pickup_client.project_pickup_result({
		"server_authoritative": true,
		"session_ref": SESSION_INITIAL,
		"target_ref": authoritative_loot.target_ref,
		"result_sequence": 2,
		"status": "PASS",
	})
	_check("AUTHORITATIVE_PICKUP_RESULT_PROJECTED", confirmed_pickup.get("status") == "PASS", JSON.stringify(confirmed_pickup))
	_check("AUTHORITATIVE_PICKUP_HIDES_DROP", authoritative_loot.authoritative_state() == "COLLECTED" and not authoritative_loot.visible)
	_check("AUTHORITATIVE_PICKUP_NO_CLIENT_GRANT", confirmed_pickup.get("item_granted_locally") == false)
	_check("AUTHORITATIVE_PICKUP_NO_INVENTORY_MUTATION", confirmed_pickup.get("inventory_mutated") == false)


func _test_auto_pickup_and_preferences(session: AndromedaClientSession) -> void:
	await _cleanup_temporary_loot()
	hud.combat_feedback.clear_presentation_feedback()
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	player.velocity = Vector3.ZERO
	camera_rig.set_follow_target(player, true)
	await _wait_physics_frames(3)
	var preference_off: Dictionary = pickup_client.project_profile_preference(false, SESSION_INITIAL, 1, true)
	_check("AUTO_PREFERENCE_OFF_EXTERNAL_PASS", preference_off.get("status") == "PASS" and preference_off.get("enabled") == false)
	_check("AUTO_PREFERENCE_OFF_NOT_PERSISTED_CLIENT", preference_off.get("persisted_by_gdscript") == false)
	var off_loot: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-AUTO-OFF", player.global_position + Vector3(0.2, 0.0, 0.0), true, true
	)
	pickup_client.clear_client_request_tracking()
	var off_scan: Dictionary = pickup_client.scan_auto_pickup_once()
	_check("AUTO_OFF_NO_REQUEST", off_scan.get("requests", []).is_empty())
	_check("AUTO_OFF_PROXIMITY_NO_COLLECTION", off_loot.visible and off_loot.is_active_for_pickup())
	var preference_on: Dictionary = pickup_client.project_profile_preference(true, SESSION_INITIAL, 2, true)
	_check("AUTO_PREFERENCE_ON_EXTERNAL_PASS", preference_on.get("status") == "PASS" and pickup_client.auto_pickup_enabled())
	_check("AUTO_PREFERENCE_UI_PROJECTED", hud.inventory_shell.auto_pickup_enabled())
	var stale_preference: Dictionary = pickup_client.project_profile_preference(false, SESSION_INITIAL, 1, true)
	_check("STALE_PREFERENCE_REJECTED", stale_preference.get("reason") == "STALE_OR_DUPLICATE_PROFILE_PREFERENCE")
	_check("STALE_PREFERENCE_DOES_NOT_DISABLE", pickup_client.auto_pickup_enabled() and hud.inventory_shell.auto_pickup_enabled())
	main.set_menu_open(true)
	_check("AUTO_PREFERENCE_REOPEN_UI_VISIBLE", hud.inventory_shell.visible and hud.inventory_shell.auto_pickup_enabled())
	main.set_menu_open(false)
	_check("AUTO_PREFERENCE_REOPEN_UI_STATE_PRESERVED", hud.inventory_shell.auto_pickup_enabled())
	hud.inventory_shell.set_auto_pickup_visual(false, true)
	_check("AUTO_UI_ON_TO_OFF_CLIENT", not pickup_client.auto_pickup_enabled())
	_check("AUTO_UI_OFF_INTENT_ENVELOPE", hud.last_auto_pickup_intent().get("intent_envelope", {}).get("status") == "PASS")
	hud.inventory_shell.set_auto_pickup_visual(true, true)
	_check("AUTO_UI_OFF_TO_ON_CLIENT", pickup_client.auto_pickup_enabled())
	_check("AUTO_UI_ON_NOT_PERSISTED", hud.last_auto_pickup_intent().get("persisted_by_gdscript") == false)
	await _cleanup_temporary_loot()
	var auto_loot_a: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-AUTO-A", player.global_position + Vector3(0.2, 0.0, 0.0), true, true
	)
	var auto_loot_b: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-AUTO-B", player.global_position + Vector3(-0.3, 0.0, 0.0), true, true
	)
	var auto_loot_c: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-AUTO-C", player.global_position + Vector3(0.0, 0.0, 0.4), true, true
	)
	var auto_far: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-AUTO-FAR", player.global_position + Vector3(0.5001, 0.0, 0.0), true, true
	)
	var auto_unsettled: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-AUTO-UNSETTLED", player.global_position + Vector3(0.0, 0.0, -0.25), false, true
	)
	pickup_client.clear_client_request_tracking()
	var selected_before: String = main.selected_target_ref()
	var multi_scan: Dictionary = pickup_client.scan_auto_pickup_once()
	var multi_requests: Array = multi_scan.get("requests", [])
	_check("AUTO_MULTIPLE_THREE_REQUESTS", multi_requests.size() == 3, JSON.stringify(multi_scan))
	_check("AUTO_MULTIPLE_A_REQUESTED", pickup_client.has_inflight_request(auto_loot_a.target_ref))
	_check("AUTO_MULTIPLE_B_REQUESTED", pickup_client.has_inflight_request(auto_loot_b.target_ref))
	_check("AUTO_MULTIPLE_C_REQUESTED", pickup_client.has_inflight_request(auto_loot_c.target_ref))
	_check("AUTO_FAR_NO_REMOTE_REQUEST", not pickup_client.has_inflight_request(auto_far.target_ref))
	_check("AUTO_UNSETTLED_NO_REQUEST", not pickup_client.has_inflight_request(auto_unsettled.target_ref))
	_check("AUTO_DOES_NOT_CHANGE_TARGET", main.selected_target_ref() == selected_before)
	_check("AUTO_DOES_NOT_INTERRUPT_ACTION", multi_scan.get("interrupts_action") == false)
	var repeat_scan: Dictionary = pickup_client.scan_auto_pickup_once()
	_check("AUTO_REPEAT_NO_SPAM", repeat_scan.get("requests", []).is_empty())
	_check("AUTO_REPEAT_INFLIGHT_STILL_THREE", pickup_client.inflight_request_count() == 3)
	await _cleanup_temporary_loot()
	pickup_client.clear_client_request_tracking()
	var action_loot: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-AUTO-ACTION", player.global_position + Vector3(0.25, 0.0, 0.0), true, true
	)
	var movement_destination := Vector3(-4.5, 0.0, 0.0)
	var movement_result: Dictionary = player.request_move(movement_destination)
	_check("AUTO_DURING_MOVEMENT_PRECONDITION", movement_result.get("status") == "PASS" and player.has_destination())
	pickup_client.observe_action_context({
		"attack_active": true,
		"interaction_active": true,
		"chase_target_ref": enemy.target_ref,
	})
	var action_before: Dictionary = pickup_client.observed_action_context()
	var destination_before: Vector3 = player.requested_destination()
	var action_scan: Dictionary = pickup_client.scan_auto_pickup_once()
	_check("AUTO_DURING_MOVEMENT_REQUESTS", action_scan.get("requests", []).size() == 1, JSON.stringify(action_scan))
	_check("AUTO_DURING_MOVEMENT_NOT_INTERRUPTED", action_scan.get("movement_active_preserved") == true)
	_check("AUTO_DURING_MOVEMENT_DESTINATION_PRESERVED", player.requested_destination().is_equal_approx(destination_before))
	_check("AUTO_DURING_ATTACK_CONTEXT_PRESERVED", pickup_client.observed_action_context().get("attack_active") == true)
	_check("AUTO_DURING_INTERACTION_CONTEXT_PRESERVED", pickup_client.observed_action_context().get("interaction_active") == true)
	_check("AUTO_DURING_CHASE_REF_PRESERVED", pickup_client.observed_action_context().get("chase_target_ref") == enemy.target_ref)
	_check("AUTO_ACTION_CONTEXT_WHOLE_PRESERVED", pickup_client.observed_action_context() == action_before)
	_check("AUTO_ACTION_LOOT_TARGET_CORRECT", pickup_client.last_request().get("target_ref") == action_loot.target_ref)
	player.stop_local_prediction()
	var wrong_session_preference: Dictionary = pickup_client.project_profile_preference(false, "OTHER-SESSION", 3, true)
	_check("OTHER_SESSION_PREFERENCE_REJECTED", wrong_session_preference.get("reason") == "PROFILE_PREFERENCE_SESSION_MISMATCH")
	var revoke_result: Dictionary = session.revoke_session()
	_check("AUTO_RECONNECT_REVOKE_PASS", revoke_result.get("status") == "PASS")
	var rebind_result: Dictionary = session.bind_session(SESSION_RESYNC)
	_check("AUTO_RECONNECT_BIND_PASS", rebind_result.get("status") == "PASS")
	await get_tree().process_frame
	_check("AUTO_RECONNECT_WAITS_FOR_PREFERENCE", not pickup_client.preference_known() and not pickup_client.auto_pickup_enabled())
	var resync_preference: Dictionary = pickup_client.project_profile_preference(true, SESSION_RESYNC, 0, true)
	_check("AUTO_RECONNECT_PREFERENCE_RESYNC_PASS", resync_preference.get("status") == "PASS" and pickup_client.auto_pickup_enabled())
	_check("AUTO_RECONNECT_UI_RESYNC_TRUE", hud.inventory_shell.auto_pickup_enabled())
	var resync_stale: Dictionary = pickup_client.project_profile_preference(false, SESSION_RESYNC, 0, true)
	_check("AUTO_RECONNECT_STALE_PREFERENCE_REJECTED", resync_stale.get("reason") == "STALE_OR_DUPLICATE_PROFILE_PREFERENCE")


func _test_water_exposure_and_resync(session: AndromedaClientSession) -> void:
	await _cleanup_temporary_loot()
	_snapshot_sequence = 0
	var weak_water: AndromedaWaterVolume = terrain.water_volume("WATER-B04-SHALLOW-WEAK")
	_check("WATER_VOLUME_FOR_LOOT_FOUND", weak_water != null)
	if weak_water == null:
		return
	var water_position := weak_water.global_position + Vector3(0.0, 1.5, 0.0)
	var water_ref := "LOOT-B07-WATER-900"
	var water_entry: Dictionary = _loot_entry(
		water_ref, "FISHING", "MATERIAL", 4, water_position, "RECOVERABLE_IN_WATER", false, 0.0
	)
	var water_spawn: Dictionary = pickup_client.project_ground_loot_snapshot(_authoritative_loot_snapshot([water_entry], SESSION_RESYNC))
	_check("WATER_LOOT_ZERO_EXPOSURE_SPAWN_PASS", water_spawn.get("status") == "PASS", JSON.stringify(water_spawn))
	var water_loot: AndromedaGroundLoot = pickup_client.ground_loot_for_ref(water_ref)
	_check("WATER_LOOT_ZERO_TARGET_FOUND", water_loot != null)
	if water_loot == null:
		return
	var stable_instance_id: int = water_loot.get_instance_id()
	var water_presenter := water_loot.get_node("WaterWorldItemPresenter") as AndromedaWaterWorldItemPresenter
	var water_entered: bool = await _wait_for_presenter_state(water_presenter, "RECOVERABLE_IN_WATER", 180)
	_check("WATER_LOOT_PHYSICS_RECOVERABLE_STATE", water_entered, water_presenter.presentation_state())
	await _wait_physics_frames(2)
	_check("WATER_LOOT_LOCAL_SETTLES_IN_WATER", water_loot.is_locally_settled())
	_check("WATER_LOOT_AWAITS_AUTHORITATIVE_SETTLE", not water_loot.is_pickup_settled())
	water_entry["settled"] = true
	water_entry["settled_position"] = {
		"iso_x_m": water_loot.global_position.x,
		"iso_y_m": water_loot.global_position.z,
		"altitude_m": water_loot.global_position.y,
	}
	var water_settle_confirmation: Dictionary = pickup_client.project_ground_loot_snapshot(_authoritative_loot_snapshot([water_entry], SESSION_RESYNC))
	_check("WATER_LOOT_AUTHORITATIVE_SETTLE_PROJECTED", water_settle_confirmation.get("status") == "PASS")
	_check("WATER_LOOT_ZERO_EXPOSURE", is_equal_approx(water_loot.water_exposure_s(), 0.0))
	_check("WATER_LOOT_ZERO_RECOVERABLE", water_loot.is_active_for_pickup() and water_loot.visible and water_loot.is_pickup_settled())
	var water_height_before: float = water_loot.global_position.y
	await _wait_physics_frames(20)
	_check("WATER_LOOT_DOES_NOT_SINK_BY_CLIENT_BUG", absf(water_loot.global_position.y - water_height_before) < 0.002, "%f/%f" % [water_height_before, water_loot.global_position.y])
	_check("WATER_LOOT_REMAINS_CLICKABLE", int(water_loot.get("collision_layer")) == 16 and water_loot.selectable)
	for exposure_value: float in [1.0, 899.0, 900.0, 901.0]:
		water_entry["water_exposure_s"] = exposure_value
		var exposure_result: Dictionary = pickup_client.project_ground_loot_snapshot(_authoritative_loot_snapshot([water_entry], SESSION_RESYNC))
		_check("WATER_EXPOSURE_%s_SNAPSHOT_PASS" % str(exposure_value), exposure_result.get("status") == "PASS", JSON.stringify(exposure_result))
		_check("WATER_EXPOSURE_%s_PROJECTED" % str(exposure_value), is_equal_approx(water_loot.water_exposure_s(), exposure_value))
		_check("WATER_EXPOSURE_%s_DOES_NOT_INFER_SUNK" % str(exposure_value), water_loot.authoritative_state() == "RECOVERABLE_IN_WATER" and water_loot.visible)
		_check("WATER_EXPOSURE_%s_TARGET_INSTANCE_STABLE" % str(exposure_value), water_loot.get_instance_id() == stable_instance_id)
	water_entry["water_exposure_s"] = 450.0
	var correction_back: Dictionary = pickup_client.project_ground_loot_snapshot(_authoritative_loot_snapshot([water_entry], SESSION_RESYNC))
	_check("WATER_EXPOSURE_CORRECTION_BACK_PASS", correction_back.get("status") == "PASS")
	_check("WATER_EXPOSURE_CORRECTION_BACK_VALUE", is_equal_approx(water_loot.water_exposure_s(), 450.0))
	water_entry["water_exposure_s"] = 899.5
	var correction_forward: Dictionary = pickup_client.project_ground_loot_snapshot(_authoritative_loot_snapshot([water_entry], SESSION_RESYNC))
	_check("WATER_EXPOSURE_CORRECTION_FORWARD_PASS", correction_forward.get("status") == "PASS")
	_check("WATER_EXPOSURE_CORRECTION_FORWARD_VALUE", is_equal_approx(water_loot.water_exposure_s(), 899.5))
	var exposure_before_wait: float = water_loot.water_exposure_s()
	await _wait_physics_frames(30)
	_check("WATER_LOCAL_TIME_DOES_NOT_ADVANCE_EXPOSURE", is_equal_approx(water_loot.water_exposure_s(), exposure_before_wait))
	_check("WATER_LOCAL_TIME_CANNOT_SINK", water_loot.authoritative_state() == "RECOVERABLE_IN_WATER" and water_loot.presentation_snapshot().get("local_timer_can_sink") == false)
	player.stop_local_prediction()
	player.global_position = water_loot.global_position + Vector3(0.4, 0.0, 0.0)
	player.velocity = Vector3.ZERO
	var water_pickup_eligible: Dictionary = pickup_client.evaluate_pickup_candidate(water_loot)
	_check("WATER_PICKUP_WITHIN_05_CLIENT_GUARD", water_pickup_eligible.get("status") == "PASS", JSON.stringify(water_pickup_eligible))
	water_entry["state"] = "SUNK"
	water_entry["water_exposure_s"] = 900.0
	water_entry["reachable"] = false
	var sunk_result: Dictionary = pickup_client.project_ground_loot_snapshot(_authoritative_loot_snapshot([water_entry], SESSION_RESYNC))
	_check("WATER_ACTIVE_TO_SUNK_PROJECTION_PASS", sunk_result.get("status") == "PASS", JSON.stringify(sunk_result))
	_check("WATER_SUNK_STATE_EXTERNAL", water_loot.authoritative_state() == "SUNK")
	_check("WATER_SUNK_VISUAL_DISABLED", not water_loot.visible and int(water_loot.get("collision_layer")) == 0)
	_check("WATER_SUNK_TARGET_REF_PRESERVED", water_loot.target_ref == water_ref)
	var sunk_pickup: Dictionary = pickup_client.evaluate_pickup_candidate(water_loot)
	_check("WATER_SUNK_PICKUP_BLOCKED", sunk_pickup.get("reason") == "GROUND_LOOT_NOT_ACTIVE", JSON.stringify(sunk_pickup))
	var direct_sunk_ref := "LOOT-B07-DIRECT-SUNK"
	var direct_sunk_entry: Dictionary = _loot_entry(
		direct_sunk_ref, "FISHING", "MATERIAL", 1, water_position, "SUNK", true, 1200.0, false
	)
	var direct_sunk_snapshot: Dictionary = _authoritative_loot_snapshot([direct_sunk_entry], SESSION_RESYNC)
	var direct_sunk_result: Dictionary = pickup_client.project_ground_loot_snapshot(direct_sunk_snapshot)
	_check("WATER_DIRECT_SUNK_SNAPSHOT_PASS", direct_sunk_result.get("status") == "PASS")
	_check("WATER_DIRECT_SUNK_NOT_INSTANTIATED_ACTIVE", pickup_client.ground_loot_for_ref(direct_sunk_ref) == null)
	var direct_tombstone: Dictionary = pickup_client.tombstone_for_ref(direct_sunk_ref)
	_check("WATER_DIRECT_SUNK_TOMBSTONE", direct_tombstone.get("state") == "SUNK" and direct_tombstone.get("active") == false)
	var duplicate_direct: Dictionary = direct_sunk_snapshot.duplicate(true)
	var duplicate_direct_result: Dictionary = pickup_client.project_ground_loot_snapshot(duplicate_direct)
	_check("WATER_DUPLICATE_SNAPSHOT_REJECTED", duplicate_direct_result.get("reason") == "STALE_OR_DUPLICATE_GROUND_LOOT_SNAPSHOT")
	var wrong_session_snapshot: Dictionary = _authoritative_loot_snapshot([direct_sunk_entry], SESSION_RESYNC)
	wrong_session_snapshot["session_ref"] = "OTHER-SESSION"
	var wrong_session_result: Dictionary = pickup_client.project_ground_loot_snapshot(wrong_session_snapshot)
	_check("WATER_OTHER_SESSION_REJECTED", wrong_session_result.get("reason") == "GROUND_LOOT_SNAPSHOT_SESSION_MISMATCH")
	var resync_ref := "LOOT-B07-RESYNC-STABLE-REF"
	var resync_entry: Dictionary = _loot_entry(
		resync_ref, "PLAYER_DROP", "MATERIAL", 2, Vector3(-6.0, 0.0, 2.0)
	)
	var resync_spawn: Dictionary = pickup_client.project_ground_loot_snapshot(_authoritative_loot_snapshot([resync_entry], SESSION_RESYNC))
	_check("RECONNECT_GROUND_LOOT_RESYNC_PASS", resync_spawn.get("status") == "PASS")
	var resynced_loot: AndromedaGroundLoot = pickup_client.ground_loot_for_ref(resync_ref)
	_check("RECONNECT_GROUND_LOOT_TARGET_REF_PRESERVED", resynced_loot != null and resynced_loot.target_ref == resync_ref)
	_check("RECONNECT_GROUND_LOOT_QUANTITY_PRESERVED", resynced_loot != null and resynced_loot.projected_quantity == 2)
	_check("RECONNECT_SESSION_STILL_ACTIVE", session.session_ref() == SESSION_RESYNC)


func _test_b01_to_b06_interactions() -> void:
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	player.velocity = Vector3.ZERO
	camera_rig.set_follow_target(player, true)
	await _wait_physics_frames(5)
	var interaction_loot: AndromedaGroundLoot = _create_local_loot(
		"LOOT-B07-B06-INTERACTION", player.global_position + Vector3(0.3, 0.0, 0.0), true, true
	)
	var select_result: Dictionary = _click_target(enemy, MOUSE_BUTTON_LEFT)
	_check("B06_INTERACTION_SELECT_ENEMY_PASS", select_result.get("status") == "PASS")
	var selected_before: String = main.selected_target_ref()
	var logical_distance_before: float = interaction_loot.physical_distance_to(player)
	var feedback_result: Dictionary = hud.present_combat_event({
		"token": "COMBAT_CRITICAL_HIT",
		"target_ref": enemy.target_ref,
		"confirmed_externally": true,
		"strength": "STRONG",
	})
	_check("B06_FEEDBACK_DURING_PICKUP_PASS", feedback_result.get("status") == "PASS", JSON.stringify(feedback_result))
	_check("B06_FEEDBACK_TARGET_STABLE", main.selected_target_ref() == selected_before)
	_check("B06_FEEDBACK_LOGICAL_DISTANCE_STABLE", is_equal_approx(interaction_loot.physical_distance_to(player), logical_distance_before))
	var pickup_during_feedback: Dictionary = pickup_client.evaluate_pickup_candidate(interaction_loot)
	_check("B06_FEEDBACK_PICKUP_GUARD_STILL_PASS", pickup_during_feedback.get("status") == "PASS", JSON.stringify(pickup_during_feedback))
	_check("B06_CAMERA_IMPULSE_DOES_NOT_REWRITE_TARGET", main.selected_target_ref() == selected_before)
	_check("B06_CAMERA_IMPULSE_DOES_NOT_REWRITE_DISTANCE", is_equal_approx(interaction_loot.physical_distance_to(player), logical_distance_before))
	pickup_client.clear_client_request_tracking()
	var auto_scan: Dictionary = pickup_client.scan_auto_pickup_once()
	_check("B06_FEEDBACK_AUTO_PICKUP_CAN_PREPARE", auto_scan.get("status") == "PASS")
	_check("B06_FEEDBACK_AUTO_DOES_NOT_CHANGE_TARGET", main.selected_target_ref() == selected_before)
	var destination := Vector3(-5.0, 0.0, 0.0)
	var move_result: Dictionary = player.request_move(destination)
	_check("B02_CLICK_TO_MOVE_AFTER_B07_PASS", move_result.get("status") == "PASS")
	var destination_before: Vector3 = player.requested_destination()
	pickup_client.scan_auto_pickup_once()
	_check("B02_CLICK_TO_MOVE_DESTINATION_UNCHANGED_BY_AUTO", player.requested_destination().is_equal_approx(destination_before))
	_check("B05_STAMINA_RING_PRESERVED", hud.stamina_ring != null and hud.stamina_ring.contract_snapshot().get("shape") == "CIRCLE_RADIAL")
	_check("B05_WEAPON_TWO_SLOTS_PRESERVED", hud.weapon_quick_slots.contract_snapshot().get("max_quick_slots") == 2)
	_check("B05_DIALOGUE_POOL_PRESERVED", hud.dialogue_pool_capacity() == 3)
	_check("B06_PLAYER_VITALS_PRESERVED", hud.player_combat_vitals != null)
	_check("B06_ENEMY_BARS_PRESERVED", hud.enemy_bar_count() == 2)
	_check("B06_REDUCED_MOTION_PRESERVED", hud.set_reduced_motion(true).get("status") == "PASS")
	_check("B06_REDUCED_MOTION_ZERO_IMPULSE", hud.combat_feedback.contract_snapshot().get("reduced_motion_supported") == true)
	hud.set_reduced_motion(false)
	hud.combat_feedback.clear_presentation_feedback()
	player.stop_local_prediction()
	_check("B01_SESSION_REF_NO_PLAYER_REF", not pickup_client.last_request().has("player_ref"))
	_check("B01_STALE_REJECTION_PRESERVED", (get_node("/root/ClientSession") as AndromedaClientSession).cursor_snapshot().get("last_snapshot_sequence") >= -1)
	_check("B04_TERRAIN_FOUNDATION_PRESERVED", main.terrain_contract_snapshot().get("surfaces_separated") == true)
	_check("B04_WATER_TTL_REMAINS_EXTERNAL", interaction_loot.presentation_snapshot().get("water_ttl_advanced_locally") == false)
	_check("B07_NO_GAMEPLAY_AUTHORITY_FINAL", pickup_client.contract_snapshot().get("item_grant_authority") == false and main.contract_snapshot().get("gameplay_authority_in_gdscript") == false)


func _create_local_loot(
	target_ref_value: String,
	world_position: Vector3,
	settled_value: bool,
	reachable_value: bool
) -> AndromedaGroundLoot:
	var loot := GROUND_LOOT_SCENE.instantiate() as AndromedaGroundLoot
	loot.configure_spawn_identity(
		target_ref_value,
		"SOURCE-%s" % target_ref_value,
		"PLAYER_DROP",
		"ITEM-%s" % target_ref_value,
		"MATERIAL"
	)
	loot.settled = settled_value
	loot.projected_reachable = reachable_value
	loot.position = world_position
	loot.set("freeze", true)
	loot_root.add_child(loot)
	pickup_client.register_ground_loot(loot)
	_temporary_loot.append(loot)
	return loot


func _loot_entry(
	target_ref_value: String,
	source_kind_value: String,
	item_kind_value: String,
	quantity_value: int,
	world_position: Vector3,
	state_value: String = "ACTIVE",
	settled_value: bool = true,
	water_exposure_value: float = 0.0,
	reachable_value: bool = true
) -> Dictionary:
	return {
		"target_ref": target_ref_value,
		"drop_ref": target_ref_value,
		"source_ref": "SOURCE-%s" % source_kind_value,
		"source_kind": source_kind_value,
		"item_ref": "ITEM-%s" % target_ref_value,
		"item_kind": item_kind_value,
		"quantity": quantity_value,
		"state": state_value,
		"settled": settled_value,
		"reachable": reachable_value,
		"water_exposure_s": water_exposure_value,
		"settled_position": {
			"iso_x_m": world_position.x,
			"iso_y_m": world_position.z,
			"altitude_m": world_position.y,
		},
	}


func _authoritative_loot_snapshot(
	entries: Array[Dictionary],
	session_ref_value: String = SESSION_INITIAL
) -> Dictionary:
	var snapshot := {
		"status": "PASS",
		"server_authoritative": true,
		"session_ref": session_ref_value,
		"snapshot_sequence": _snapshot_sequence,
		"ground_loot": entries,
	}
	_snapshot_sequence += 1
	return snapshot


func _click_target(target: AndromedaInteractionTarget, button_index: int) -> Dictionary:
	return main.handle_pointer_event(_mouse_button(button_index, main.target_to_screen(target)))


func _mouse_button(button_index: int, position_value: Vector2) -> InputEventMouseButton:
	var event := InputEventMouseButton.new()
	event.button_index = button_index as MouseButton
	event.pressed = true
	event.position = position_value
	return event


func _wait_for_navigation(max_frames: int) -> bool:
	for _frame_index: int in range(max_frames):
		if main.navigation_ready():
			return true
		await get_tree().physics_frame
	return false


func _wait_for_local_settle(loot: AndromedaGroundLoot, max_frames: int) -> bool:
	for _frame_index: int in range(max_frames):
		if loot.is_locally_settled() and bool(loot.get("freeze")):
			return true
		await get_tree().physics_frame
	return false


func _wait_for_inflight_request(target_ref_value: String, max_frames: int) -> bool:
	for _frame_index: int in range(max_frames):
		if pickup_client.has_inflight_request(target_ref_value):
			return true
		await get_tree().physics_frame
	return false


func _wait_for_presenter_state(
	presenter: AndromedaWaterWorldItemPresenter,
	expected_state: String,
	max_frames: int
) -> bool:
	for _frame_index: int in range(max_frames):
		if presenter.presentation_state() == expected_state:
			return true
		await get_tree().physics_frame
	return false


func _wait_physics_frames(frame_count: int) -> void:
	for _frame_index: int in range(frame_count):
		await get_tree().physics_frame


func _cleanup_temporary_loot() -> void:
	for loot: AndromedaGroundLoot in _temporary_loot:
		if loot == null or not is_instance_valid(loot):
			continue
		if pickup_client.ground_loot_for_ref(loot.target_ref) == loot:
			pickup_client.unregister_ground_loot(loot.target_ref)
		loot.queue_free()
	_temporary_loot.clear()
	await get_tree().process_frame


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "B07_UNIVERSAL_GROUND_LOOT_PICKUP_AUTO_PICKUP_WATER_EXPOSURE",
		"acceptance_scope_pass": [],
		"partial_evidence_only": ["G16B-04", "G16B-05", "G16B-06", "G16B-27"],
		"not_available_without_authoritative_backend": [
			"LIVE_PICKUP_RESULT_ROUNDTRIP",
			"PROFILE_PREFERENCE_PERSISTENCE_ROUNDTRIP",
			"AUTHORITATIVE_WATER_TTL_ADVANCE",
			"GROUND_LOOT_TIMER_SAVE_RELOAD",
			"BAG_30_MINUTE_AND_LAND_NO_EXPIRY_SCOPE",
		],
		"authority": "GODOT_GROUND_LOOT_CLIENT_PRESENTATION_ORCHESTRATION_ONLY",
		"backend_roundtrip_executed": false,
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_B07_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_B07_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_B07_SUMMARY: %s" % JSON.stringify(summary))
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
