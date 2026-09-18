extends Node

const GROUND_LOOT_SCENE: PackedScene = preload("res://scenes/interaction/GroundLoot.tscn")
const DROPPED_BAG_SCENE: PackedScene = preload("res://scenes/interaction/DroppedBag.tscn")

var _checks: int = 0
var _failures: Array[String] = []

@onready var main: AndromedaMainRuntime = $AndromedaARPG
@onready var player: AndromedaPlayerController = $AndromedaARPG/ActorRoot/Player
@onready var camera_rig: AndromedaIsometricCameraRig = $AndromedaARPG/IsometricCameraRig
@onready var terrain: AndromedaTerrainFoundation = $AndromedaARPG/WorldStreamRoot/TerrainFoundation
@onready var streaming: AndromedaStreamingManager = $AndromedaARPG/WorldStreamRoot/TerrainFoundation/CELL_STREAMING


func _ready() -> void:
	await _run_gate()


func _check(check_id: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(check_id if detail.is_empty() else "%s:%s" % [check_id, detail])


func _run_gate() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_check("AUTOLOAD_CLIENT_SESSION", session != null)
	_check("AUTOLOAD_ANDROMEDA_BRIDGE", bridge != null)
	if session == null or bridge == null:
		await _finish()
		return
	var bind_result: Dictionary = session.bind_session("B04-GATE-SESSION")
	_check("SESSION_BOUND_FOR_ENVELOPES_ONLY", bind_result.get("status") == "PASS", JSON.stringify(bind_result))
	_check("EXISTING_BACKEND_URL_UNCHANGED", bridge.server_url() == "http://127.0.0.1:8000")
	_check("NO_BACKEND_SUBSTITUTE", main.contract_snapshot().get("backend_substitute") == false)
	_check("NO_GDSCRIPT_GAMEPLAY_AUTHORITY", main.contract_snapshot().get("gameplay_authority_in_gdscript") == false)
	_check("NO_TERRAIN_GAMEPLAY_AUTHORITY", main.contract_snapshot().get("terrain_traversal_authority_in_gdscript") == false)
	_check("PLAYER_SPAWN_ON_REAL_TERRAIN", player.global_position.distance_to(Vector3(-7.0, 0.0, 0.0)) < 0.02, str(player.global_position))

	var navigation_became_ready: bool = await _wait_for_navigation(240)
	_check("NAVIGATION_MAP_READY", navigation_became_ready)
	if not navigation_became_ready:
		await _finish()
		return

	_test_terrain_architecture()
	_test_surface_samples()
	_test_navigation_capabilities()
	_test_water_contracts()
	await _test_real_player_traversal()
	await _test_obstacle_and_replanning()
	await _test_world_item_terrain_and_water()
	await _test_streaming_foundation()
	await _test_camera_relief_stability()
	_restore_gate_state()
	await _finish()


func _test_terrain_architecture() -> void:
	var contract: Dictionary = terrain.contract_snapshot()
	_check("TERRAIN_FOUNDATION_PRESENT", main.terrain_foundation == terrain)
	_check("VISUAL_SURFACE_EXPLICIT", terrain.has_node("VISUAL_SURFACE"))
	_check("COLLISION_SURFACE_EXPLICIT", terrain.has_node("COLLISION_SURFACE"))
	_check("TRAVERSAL_SURFACE_EXPLICIT", terrain.has_node("TRAVERSAL_SURFACE"))
	_check("SURFACES_ARE_DISTINCT_NODES", contract.get("surfaces_separated") == true, JSON.stringify(contract))
	_check("OLD_VISUAL_GROUND_PLACEHOLDER_REMOVED", not main.has_node("WorldStreamRoot/VisualSurface/GroundPlaceholder"))
	_check("OLD_COLLISION_GROUND_PLACEHOLDER_REMOVED", not main.has_node("WorldStreamRoot/CollisionSurface/WalkableGround"))
	_check("PROCEDURAL_TERRAIN_VISUAL_PRESENT", terrain.has_node("VISUAL_SURFACE/MacroTerrainVisual"))
	_check("STABLE_MACRO_COLLISION_PRESENT", terrain.has_node("COLLISION_SURFACE/StableMacroCollision"))
	_check("SURFACE_ZONE_NODES_PRESENT", terrain.get_node("TRAVERSAL_SURFACE/SurfaceZones").get_child_count() >= 4)
	_check("TERRAIN_NAVIGATION_REGIONS_PRESENT", terrain.navigation_region_count() >= 12, str(terrain.navigation_region_count()))
	_check("TERRAIN_NAVIGATION_POLYGONS_PRESENT", terrain.navigation_region_polygon_count() >= 12, str(terrain.navigation_region_polygon_count()))
	_check("B02_BASE_NAVIGATION_PRESERVED", main.navigation_mesh_polygon_count() == 8, str(main.navigation_mesh_polygon_count()))
	_check("MAX_SLOPE_CANDIDATE_PRESERVED", is_equal_approx(float(contract.get("max_walkable_slope_deg_candidate")), 32.0))
	_check("MAX_STEP_CANDIDATE_PRESERVED", is_equal_approx(float(contract.get("max_step_height_m_candidate")), 0.35))
	_check("MICRO_FILTER_CANDIDATE_PRESERVED", is_equal_approx(float(contract.get("micro_relief_collision_filter_m_candidate")), 0.12))
	_check("NO_BODY_BALANCE_MECHANIC", contract.get("body_balance_mechanic") == false)
	_check("NO_FINAL_ART", contract.get("visual_final_art") == false)
	var layer_contract: Dictionary = contract.get("navigation_layers", {})
	_check("NAV_LAYER_LAND_SHALLOW", int(layer_contract.get("LAND_SHALLOW", 0)) == 1)
	_check("NAV_LAYER_DEEP_SWIM", int(layer_contract.get("DEEP_SWIM", 0)) == 2)
	_check("NAV_LAYER_BRIDGE", int(layer_contract.get("BRIDGE", 0)) == 4)
	var filter_contract: Dictionary = terrain.collision_filter_contract()
	_check("VISUAL_RELIEF_BELOW_COLLISION_FILTER", float(filter_contract.get("visual_micro_relief_max_abs_m", INF)) < 0.12, JSON.stringify(filter_contract))
	_check("MICRO_RELIEF_FILTERED_FROM_COLLISION", is_zero_approx(float(filter_contract.get("collision_micro_relief_m", INF))), JSON.stringify(filter_contract))
	_check("SMALL_STEP_IS_BELOW_CANDIDATE", float(filter_contract.get("implemented_small_step_height_m", INF)) <= 0.35)
	_check("SMALL_STEP_COLLISION_FILTERED", filter_contract.get("step_collision_transition") == "FILTERED_RAMP")
	var height_range: Vector2 = terrain.visual_height_range()
	_check("VISUAL_TERRAIN_HAS_SUBTLE_RELIEF", height_range.y - height_range.x > 0.04, str(height_range))


func _test_surface_samples() -> void:
	var flat: Dictionary = terrain.surface_sample(Vector3(-1.0, 0.0, 3.0))
	var gentle: Dictionary = terrain.surface_sample(Vector3(15.0, 0.5, 0.0))
	var moderate: Dictionary = terrain.surface_sample(Vector3(21.0, 2.0, 0.0))
	var blocked: Dictionary = terrain.surface_sample(Vector3(25.5, 5.0, 0.0))
	var step: Dictionary = terrain.surface_sample(Vector3(12.5, 0.15, 8.0))
	var road: Dictionary = terrain.surface_sample(Vector3(-7.0, 0.0, -2.0))
	var field: Dictionary = terrain.surface_sample(Vector3(-7.0, 0.0, 2.0))
	var rocky: Dictionary = terrain.surface_sample(Vector3(-8.0, 0.0, 8.0))
	var mud: Dictionary = terrain.surface_sample(Vector3(8.0, 0.0, 8.0))
	_check("FLAT_MOVEMENT_SAMPLE", flat.get("status") == "PASS" and is_zero_approx(float(flat.get("slope_deg", INF))), JSON.stringify(flat))
	_check("GENTLE_ASCENT_SAMPLE", gentle.get("status") == "PASS" and float(gentle.get("slope_deg", 0.0)) > 6.0 and float(gentle.get("slope_deg", 99.0)) < 14.0, JSON.stringify(gentle))
	_check("MODERATE_ASCENT_SAMPLE", moderate.get("status") == "PASS" and float(moderate.get("slope_deg", 0.0)) > 14.0 and float(moderate.get("slope_deg", 99.0)) < 24.0, JSON.stringify(moderate))
	_check("SLOPE_ABOVE_32_BLOCKED", blocked.get("status") == "BLOCKED" and float(blocked.get("slope_deg", 0.0)) > 32.0, JSON.stringify(blocked))
	_check("SMALL_STEP_SAMPLE_WALKABLE", step.get("status") == "PASS" and float(step.get("slope_deg", 99.0)) < 32.0, JSON.stringify(step))
	_check("ROAD_SURFACE_DETECTED", road.get("surface_kind") == "ROAD_GOOD" and road.get("flags", {}).get("road") == true, JSON.stringify(road))
	_check("FIELD_SURFACE_DETECTED", field.get("surface_kind") == "GRASS_FIELD" and field.get("flags", {}).get("field") == true, JSON.stringify(field))
	_check("ROAD_ADVANTAGE_OVER_FIELD", float(road.get("traversal_factor_candidate", INF)) < float(field.get("traversal_factor_candidate", -INF)), "road=%s field=%s" % [road, field])
	_check("ROCKY_SURFACE_DETECTED", rocky.get("surface_kind") == "ROCKY_GROUND" and rocky.get("flags", {}).get("rock") == true, JSON.stringify(rocky))
	_check("MUD_SURFACE_DETECTED", mud.get("surface_kind") == "MUD" and mud.get("flags", {}).get("mud") == true, JSON.stringify(mud))
	_check("MUD_COST_HINT_ABOVE_ROCK", float(mud.get("traversal_factor_candidate", 0.0)) > float(rocky.get("traversal_factor_candidate", INF)))
	for flag_name: String in ["road", "trail", "field", "rock", "mud", "water"]:
		_check("SURFACE_FLAG_%s_EXPOSED" % flag_name.to_upper(), flat.get("flags", {}).has(flag_name))
	_check("LOAD_INPUT_FORWARDED_ONLY", flat.get("load_input_forwarded") == true and flat.get("authoritative_stamina_applied") == false)
	_check("SURFACE_REQUIRES_AUTHORITATIVE_RESOLUTION", flat.get("requires_authoritative_traversal_resolution") == true)


func _test_navigation_capabilities() -> void:
	var gentle: Dictionary = terrain.validate_navigation_for_capability(Vector3(12.1, 0.02, 0.0), Vector3(17.9, 0.98, 0.0), "LAND_ONLY")
	var moderate: Dictionary = terrain.validate_navigation_for_capability(Vector3(18.1, 1.03, 0.0), Vector3(23.9, 2.97, 0.0), "LAND_ONLY")
	var blocked: Dictionary = terrain.validate_navigation_for_capability(Vector3(25.0, 4.3, 0.0), Vector3(26.5, 6.3, 0.0), "LAND_ONLY")
	var shallow: Dictionary = terrain.validate_navigation_for_capability(Vector3(29.2, 0.0, -10.0), Vector3(34.8, 0.0, -10.0), "NON_SWIMMER")
	var deep_swim: Dictionary = terrain.validate_navigation_for_capability(Vector3(53.2, 1.55, -10.0), Vector3(58.8, 1.55, -10.0), "SWIM_ONLY")
	var deep_vehicle: Dictionary = terrain.validate_navigation_for_capability(Vector3(53.2, 1.55, -10.0), Vector3(58.8, 1.55, -10.0), "VEHICLE")
	var under_bridge: Dictionary = terrain.validate_navigation_for_capability(Vector3(32.2, 0.0, 10.0), Vector3(43.8, 0.0, 10.0), "LAND_ONLY")
	var over_bridge: Dictionary = terrain.validate_navigation_for_capability(Vector3(38.0, 0.0, 4.1), Vector3(38.0, 0.0, 15.9), "BRIDGE_ONLY")
	_check("NAVIGATION_GENTLE_SLOPE_VALID", gentle.get("status") == "PASS", JSON.stringify(gentle))
	_check("NAVIGATION_MODERATE_SLOPE_VALID", moderate.get("status") == "PASS", JSON.stringify(moderate))
	_check("NAVIGATION_BLOCKED_SLOPE_REJECTED", blocked.get("status") == "BLOCKED", JSON.stringify(blocked))
	_check("NAVIGATION_SHALLOW_WATER_VALID", shallow.get("status") == "PASS", JSON.stringify(shallow))
	_check("NAVIGATION_DEEP_SWIMMER_VALID", deep_swim.get("status") == "PASS", JSON.stringify(deep_swim))
	_check("NAVIGATION_DEEP_VEHICLE_BLOCKED", deep_vehicle.get("status") == "BLOCKED", JSON.stringify(deep_vehicle))
	_check("NAVIGATION_UNDER_BRIDGE_VALID", under_bridge.get("status") == "PASS", JSON.stringify(under_bridge))
	_check("NAVIGATION_OVER_BRIDGE_VALID", over_bridge.get("status") == "PASS", JSON.stringify(over_bridge))
	var under_path: PackedVector3Array = under_bridge.get("path", PackedVector3Array()) as PackedVector3Array
	var bridge_path: PackedVector3Array = over_bridge.get("path", PackedVector3Array()) as PackedVector3Array
	_check("UNDER_BRIDGE_PATH_STAYS_LOW", _maximum_path_height(under_path) < 0.1, str(under_path))
	_check("BRIDGE_PATH_REACHES_DECK", _maximum_path_height(bridge_path) > 2.3, str(bridge_path))
	var clearance_query := PhysicsRayQueryParameters3D.create(Vector3(32.3, 1.0, 10.0), Vector3(43.7, 1.0, 10.0), 1, [player.get_rid()])
	var clearance_hit: Dictionary = player.get_world_3d().direct_space_state.intersect_ray(clearance_query)
	_check("UNDER_BRIDGE_PHYSICAL_CLEARANCE", clearance_hit.is_empty(), str(clearance_hit))


func _test_water_contracts() -> void:
	var calm := terrain.water_volume("WATER-B04-SHALLOW-CALM")
	var weak := terrain.water_volume("WATER-B04-SHALLOW-WEAK")
	var strong := terrain.water_volume("WATER-B04-SHALLOW-STRONG")
	var deep := terrain.water_volume("WATER-B04-DEEP-SWIMMABLE")
	var under_bridge := terrain.water_volume("WATER-B04-SHALLOW-UNDER-BRIDGE")
	_check("ALL_WATER_VOLUMES_FOUND", calm != null and weak != null and strong != null and deep != null and under_bridge != null)
	if calm == null or weak == null or strong == null or deep == null or under_bridge == null:
		return
	for actor_kind: String in ["PLAYER", "NPC", "ANIMAL"]:
		var sample: Dictionary = calm.sample_for_actor(actor_kind)
		_check("SHALLOW_%s_WADE" % actor_kind, sample.get("status") == "PASS" and sample.get("mode") == "WADE", JSON.stringify(sample))
		_check("SHALLOW_%s_AUTHORITY_EXTERNAL" % actor_kind, sample.get("authoritative_stamina_applied") == false and sample.get("requires_authoritative_snapshot") == true)
	var shallow_vehicle: Dictionary = calm.sample_for_actor("VEHICLE")
	_check("SHALLOW_VEHICLE_ALLOWED", shallow_vehicle.get("status") == "PASS" and shallow_vehicle.get("mode") == "WADE_VEHICLE", JSON.stringify(shallow_vehicle))
	_check("VEHICLE_USES_NO_STAMINA", is_zero_approx(float(shallow_vehicle.get("vehicle_stamina_cost", INF))))
	_check("VEHICLE_TRACTION_SPEED_INPUT", shallow_vehicle.get("vehicle_traction_speed_penalty_input") == true)
	var weak_player: Dictionary = weak.sample_for_actor("PLAYER")
	var strong_player: Dictionary = strong.sample_for_actor("PLAYER")
	_check("WEAK_CURRENT_DETECTED", weak_player.get("current_class") == "CURRENT", JSON.stringify(weak_player))
	_check("STRONG_CURRENT_DETECTED", strong_player.get("current_class") == "STRONG_CURRENT", JSON.stringify(strong_player))
	_check("STRONG_CURRENT_COST_INPUT_HIGHER", float(strong_player.get("current_factor_candidate", 0.0)) > float(weak_player.get("current_factor_candidate", INF)))
	var displacement: Vector3 = strong.presentation_current_displacement(1.0)
	_check("CURRENT_DISPLACEMENT_HORIZONTAL", is_zero_approx(displacement.y), str(displacement))
	_check("CURRENT_DISPLACEMENT_SMOOTHLY_CAPPED", displacement.length() <= 0.08001, str(displacement))
	var deep_player: Dictionary = deep.sample_for_actor("PLAYER")
	var deep_npc: Dictionary = deep.sample_for_actor("NPC")
	var deep_animal: Dictionary = deep.sample_for_actor("ANIMAL")
	var deep_vehicle: Dictionary = deep.sample_for_actor("VEHICLE")
	_check("DEEP_PLAYER_SWIM_PRESENTATION", deep_player.get("status") == "PASS" and deep_player.get("mode") == "SWIM", JSON.stringify(deep_player))
	_check("DEEP_NPC_SWIM_PRESENTATION", deep_npc.get("status") == "PASS" and deep_npc.get("mode") == "SWIM", JSON.stringify(deep_npc))
	_check("DEEP_ANIMAL_SWIM_PRESENTATION", deep_animal.get("status") == "PASS" and deep_animal.get("mode") == "SWIM", JSON.stringify(deep_animal))
	_check("DEEP_VEHICLE_BLOCKED", deep_vehicle.get("status") == "BLOCKED" and deep_vehicle.get("reason") == "VEHICLE_WATER_TOO_DEEP", JSON.stringify(deep_vehicle))
	_check("DEEP_DEATH_NOT_AUTHORED", deep_player.get("authoritative_death_applied") == false)
	var bridge_sample: Dictionary = under_bridge.sample_for_actor("PLAYER")
	_check("SHALLOW_UNDER_BRIDGE_FLAG", bridge_sample.get("status") == "PASS" and bridge_sample.get("under_bridge") == true)
	_check("WATER_LAYER_CONTRACT", calm.collision_layer == 2048)
	_check("NO_CHAOTIC_BALANCE_SYSTEM", calm.contract_snapshot().get("gameplay_authority_in_gdscript") == false)


func _test_real_player_traversal() -> void:
	await _reposition_player(Vector3(-7.0, 0.0, 0.0), 8)
	var flat_result: Dictionary = player.request_move(Vector3(-8.0, 0.0, 4.0))
	_check("REAL_FLAT_MOVE_REQUEST", flat_result.get("status") == "PASS", JSON.stringify(flat_result))
	var flat_arrival: Dictionary = await _wait_for_arrival(360)
	_check("REAL_FLAT_MOVE_ARRIVAL", flat_arrival.get("arrived") == true, JSON.stringify(flat_arrival))
	_check("REAL_FLAT_MOVE_NO_JITTER", float(flat_arrival.get("maximum_step_m", INF)) < 0.18, JSON.stringify(flat_arrival))

	await _reposition_player(Vector3(11.0, 0.0, 0.0), 8)
	var gentle_target := Vector3(17.5, terrain.terrain_surface_height(Vector3(17.5, 0.0, 0.0)), 0.0)
	var gentle_result: Dictionary = player.request_move(gentle_target)
	_check("REAL_GENTLE_ASCENT_REQUEST", gentle_result.get("status") == "PASS", JSON.stringify(gentle_result))
	var gentle_arrival: Dictionary = await _wait_for_arrival(480)
	_check("REAL_GENTLE_ASCENT_ARRIVAL", gentle_arrival.get("arrived") == true, JSON.stringify(gentle_arrival))
	_check("REAL_GENTLE_ASCENT_HEIGHT", player.global_position.y > 0.65, str(player.global_position))
	_check("REAL_GENTLE_ASCENT_NO_STEP_SPIKE", float(gentle_arrival.get("maximum_step_m", INF)) < 0.18, JSON.stringify(gentle_arrival))

	var moderate_target := Vector3(23.5, terrain.terrain_surface_height(Vector3(23.5, 0.0, 0.0)), 0.0)
	var moderate_result: Dictionary = player.request_move(moderate_target)
	_check("REAL_MODERATE_ASCENT_REQUEST", moderate_result.get("status") == "PASS", JSON.stringify(moderate_result))
	var moderate_arrival: Dictionary = await _wait_for_arrival(600)
	_check("REAL_MODERATE_ASCENT_ARRIVAL", moderate_arrival.get("arrived") == true, JSON.stringify(moderate_arrival))
	_check("REAL_MODERATE_ASCENT_HEIGHT", player.global_position.y > 2.35, str(player.global_position))
	_check("REAL_MODERATE_ASCENT_NO_STEP_SPIKE", float(moderate_arrival.get("maximum_step_m", INF)) < 0.18, JSON.stringify(moderate_arrival))
	var blocked_validation: Dictionary = player.validate_destination(Vector3(26.0, terrain.terrain_surface_height(Vector3(26.0, 0.0, 0.0)), 0.0))
	_check("REAL_BLOCKED_SLOPE_DESTINATION_REJECTED", blocked_validation.get("status") == "REJECTED", JSON.stringify(blocked_validation))

	await _reposition_player(Vector3(11.0, 0.0, 8.0), 8)
	var step_target := Vector3(16.0, 0.3, 8.0)
	var step_result: Dictionary = player.request_move(step_target)
	_check("REAL_SMALL_STEP_REQUEST", step_result.get("status") == "PASS", JSON.stringify(step_result))
	var step_arrival: Dictionary = await _wait_for_arrival(480)
	_check("REAL_SMALL_STEP_ARRIVAL", step_arrival.get("arrived") == true, JSON.stringify(step_arrival))
	_check("REAL_SMALL_STEP_HEIGHT", player.global_position.y > 0.20, str(player.global_position))
	_check("REAL_SMALL_STEP_NO_SNAG", float(step_arrival.get("maximum_step_m", INF)) < 0.18, JSON.stringify(step_arrival))


func _test_obstacle_and_replanning() -> void:
	await _reposition_player(Vector3(-7.0, 0.0, 0.0), 8)
	var destination := Vector3(7.0, 0.0, 0.0)
	var initial_path: PackedVector3Array = player.preview_path(destination)
	_check("OBSTACLE_PATH_VALID", initial_path.size() >= 3, str(initial_path))
	var uses_north: bool = _path_uses_side(initial_path, true)
	var uses_south: bool = _path_uses_side(initial_path, false)
	_check("OBSTACLE_PATH_DETOURS", uses_north or uses_south, str(initial_path))
	var move_result: Dictionary = player.request_move(destination)
	_check("REPLAN_INITIAL_MOVE_REQUEST", move_result.get("status") == "PASS", JSON.stringify(move_result))
	await _wait_physics_frames(12)
	var closure: Dictionary = main.set_b04_base_route_closure(uses_north, not uses_north)
	_check("DYNAMIC_ROUTE_CLOSURE_APPLIED", closure.get("status") == "PASS" and int(closure.get("navigation_polygon_count", 0)) == 7, JSON.stringify(closure))
	_check("MOVEMENT_PREDICTION_PRESERVED_DURING_CLOSURE", closure.get("movement_prediction_preserved") == true)
	await _wait_for_navigation_iteration_change(12)
	var replanned_path: PackedVector3Array = player.preview_path(destination)
	_check("REPLANNED_PATH_VALID", replanned_path.size() >= 3, str(replanned_path))
	_check("REPLANNED_PATH_SWITCHES_SIDE", _path_uses_side(replanned_path, not uses_north), str(replanned_path))
	var replan_request: Dictionary = player.request_move(destination)
	_check("REPLAN_REQUEST_REFRESHED", replan_request.get("status") == "PASS", JSON.stringify(replan_request))
	var arrival: Dictionary = await _wait_for_arrival(900, true)
	_check("REPLANNED_ROUTE_ARRIVED", arrival.get("arrived") == true, JSON.stringify(arrival))
	_check("REPLANNED_ROUTE_RESPECTS_COLLISION", arrival.get("entered_blocker") == false, JSON.stringify(arrival))
	_check("REPLANNED_ROUTE_STOPS_WITHOUT_JITTER", float(arrival.get("post_arrival_drift_m", INF)) < 0.006, JSON.stringify(arrival))
	var restore: Dictionary = main.set_b04_base_route_closure(false, false)
	_check("BASE_ROUTE_RESTORED", restore.get("status") == "PASS" and int(restore.get("navigation_polygon_count", 0)) == 8, JSON.stringify(restore))
	await _wait_for_navigation_iteration_change(8)


func _test_world_item_terrain_and_water() -> void:
	var loot_root := main.get_node("GroundLootRoot") as Node3D
	var land_loot := GROUND_LOOT_SCENE.instantiate() as RigidBody3D
	land_loot.name = "B04LandSettlingLoot"
	land_loot.position = Vector3(-5.0, 3.0, 7.0)
	loot_root.add_child(land_loot)
	var land_loot_presenter := land_loot.get_node("WaterWorldItemPresenter") as AndromedaWaterWorldItemPresenter
	land_loot_presenter.begin_physical_settle()
	var land_settled: bool = await _wait_for_item_state(land_loot_presenter, "LANDED_STABLE", 240)
	_check("GROUND_LOOT_SETTLES_ON_TERRAIN", land_settled, land_loot_presenter.presentation_state())
	_check("GROUND_LOOT_SETTLE_HEIGHT", land_loot.global_position.y > -0.05 and land_loot.global_position.y < 0.08, str(land_loot.global_position))
	var stable_position: Vector3 = land_loot.global_position
	await _wait_physics_frames(24)
	_check("GROUND_LOOT_STAYS_SETTLED", land_loot.freeze and land_loot.global_position.distance_to(stable_position) < 0.002)

	var weak := terrain.water_volume("WATER-B04-SHALLOW-WEAK")
	var water_loot := GROUND_LOOT_SCENE.instantiate() as RigidBody3D
	water_loot.name = "B04WaterLoot"
	loot_root.add_child(water_loot)
	water_loot.global_position = weak.global_position + Vector3(0.0, 1.5, 0.0)
	var water_loot_presenter := water_loot.get_node("WaterWorldItemPresenter") as AndromedaWaterWorldItemPresenter
	water_loot_presenter.begin_physical_settle()
	var loot_entered_water: bool = await _wait_for_item_state(water_loot_presenter, "RECOVERABLE_IN_WATER", 120)
	_check("GROUND_LOOT_ENTERS_WATER", loot_entered_water, water_loot_presenter.presentation_state())
	var water_loot_contract: Dictionary = water_loot_presenter.contract_snapshot()
	_check("GROUND_LOOT_WATER_TTL_CONTRACT_15_MIN", water_loot_contract.get("authoritative_ttl_s_contract") == 900.0, JSON.stringify(water_loot_contract))
	_check("GROUND_LOOT_TTL_NOT_ADVANCED_LOCALLY", water_loot_contract.get("authoritative_ttl_advanced_locally") == false)
	_check("GROUND_LOOT_WATER_REMAINS_PHYSICAL", water_loot.collision_layer == 16 and water_loot.freeze)

	var land_bag := DROPPED_BAG_SCENE.instantiate() as RigidBody3D
	land_bag.name = "B04LandBag"
	land_bag.position = Vector3(-8.0, 3.0, 7.0)
	loot_root.add_child(land_bag)
	var land_bag_presenter := land_bag.get_node("WaterWorldItemPresenter") as AndromedaWaterWorldItemPresenter
	land_bag_presenter.begin_physical_settle()
	var bag_settled: bool = await _wait_for_item_state(land_bag_presenter, "LANDED_STABLE", 240)
	_check("LAND_BAG_SETTLES", bag_settled, land_bag_presenter.presentation_state())
	var land_bag_contract: Dictionary = land_bag_presenter.contract_snapshot()
	_check("LAND_BAG_NO_EXPIRY", land_bag_contract.get("authoritative_ttl_s_contract") == null and land_bag_contract.get("land_expiry") == null, JSON.stringify(land_bag_contract))

	var strong := terrain.water_volume("WATER-B04-SHALLOW-STRONG")
	var water_bag := DROPPED_BAG_SCENE.instantiate() as RigidBody3D
	water_bag.name = "B04FloatingBag"
	loot_root.add_child(water_bag)
	water_bag.global_position = strong.global_position + Vector3(0.0, 1.5, 0.0)
	var water_bag_presenter := water_bag.get_node("WaterWorldItemPresenter") as AndromedaWaterWorldItemPresenter
	water_bag_presenter.begin_physical_settle()
	var bag_floating: bool = await _wait_for_item_state(water_bag_presenter, "FLOATING", 120)
	_check("WATER_BAG_FLOATS", bag_floating, water_bag_presenter.presentation_state())
	var water_bag_contract: Dictionary = water_bag_presenter.contract_snapshot()
	_check("WATER_BAG_TTL_CONTRACT_30_MIN", water_bag_contract.get("authoritative_ttl_s_contract") == 1800.0, JSON.stringify(water_bag_contract))
	_check("WATER_BAG_TTL_NOT_ADVANCED_LOCALLY", water_bag_contract.get("authoritative_ttl_advanced_locally") == false)
	var bag_before_current: Vector3 = water_bag.global_position
	await _wait_physics_frames(12)
	var bag_drift: Vector3 = water_bag.global_position - bag_before_current
	_check("WATER_BAG_CURRENT_DRIFT_PRESENT", bag_drift.length() > 0.01, str(bag_drift))
	_check("WATER_BAG_CURRENT_DRIFT_SMOOTH", bag_drift.length() < 0.45 and absf(bag_drift.y) < 0.01, str(bag_drift))
	_check("DROPPED_BAG_LAYER_SEPARATE", water_bag.collision_layer == 4096)

	land_loot.queue_free()
	water_loot.queue_free()
	land_bag.queue_free()
	water_bag.queue_free()
	await get_tree().physics_frame


func _test_streaming_foundation() -> void:
	var initial: Dictionary = streaming.state_snapshot()
	_check("STREAMING_TOTAL_LOGICAL_CELLS", int(initial.get("total_logical_cells", 0)) == 25, JSON.stringify(initial))
	_check("STREAMING_ONE_ACTIVE_CELL", (initial.get("active_cells", []) as Array).size() == 1, JSON.stringify(initial))
	_check("STREAMING_NEIGHBORS_PRELOAD", (initial.get("preload_cells", []) as Array).size() == 8, JSON.stringify(initial))
	_check("STREAMING_ACTIVE_PLUS_PRELOAD_ONLY", int(initial.get("loaded_scene_cell_count", 0)) == 9, JSON.stringify(initial))
	_check("STREAMING_DISTANT_SYSTEMIC_ONLY", int(initial.get("systemic_unloaded_cell_count", 0)) == 16 and initial.get("distant_visuals_loaded") == false, JSON.stringify(initial))
	_check("STREAMING_DOES_NOT_LOAD_ENTIRE_REGION", initial.get("entire_region_loaded") == false)
	_check("NO_PARALLEL_LIVING", initial.get("living_parallel_implementation") == false and initial.get("systemic_state_source") == "EXTERNAL_LIVING_REFERENCE_ONLY")
	var far_ref: String = streaming.cell_ref_for(Vector2i(-2, -2))
	var far_before: Dictionary = streaming.systemic_reference_for(far_ref)
	_check("SYSTEMIC_REFERENCE_EXISTS", far_before.get("systemic_state_preserved_by_reference") == true, JSON.stringify(far_before))
	var initial_preload_ref: String = streaming.cell_ref_for(Vector2i(-1, 0))
	_check("PRELOAD_CELL_HAS_SCENE", not streaming.loaded_cell_snapshot(initial_preload_ref).is_empty())
	var move_plan: Dictionary = streaming.set_active_cell(Vector2i(1, 0))
	_check("STREAMING_ACTIVE_CELL_CHANGE", move_plan.get("status") == "PASS", JSON.stringify(move_plan))
	await _wait_physics_frames(2)
	var moved: Dictionary = streaming.state_snapshot()
	_check("STREAMING_STILL_ONE_ACTIVE", (moved.get("active_cells", []) as Array).size() == 1)
	_check("STREAMING_STILL_RING_ONLY", int(moved.get("loaded_scene_cell_count", 0)) == 9, JSON.stringify(moved))
	_check("PREVIOUS_DISTANT_PRELOAD_UNLOADED", streaming.loaded_cell_snapshot(initial_preload_ref).is_empty())
	var now_systemic: Dictionary = streaming.systemic_reference_for(initial_preload_ref)
	_check("UNLOADED_CELL_SYSTEMIC_REF_PRESERVED", now_systemic.get("godot_scene_loaded") == false and now_systemic.get("living_macro_ref") == initial.get("living_macro_ref"), JSON.stringify(now_systemic))
	var far_after: Dictionary = streaming.systemic_reference_for(far_ref)
	_check("SYSTEMIC_REFERENCE_STABLE_ACROSS_STREAM", far_after.get("living_macro_ref") == far_before.get("living_macro_ref") and far_after.get("cell_ref") == far_before.get("cell_ref"), "before=%s after=%s" % [far_before, far_after])
	var previous_active_ref: String = streaming.cell_ref_for(Vector2i.ZERO)
	var previous_active_snapshot: Dictionary = streaming.loaded_cell_snapshot(previous_active_ref)
	_check("PREVIOUS_ACTIVE_BECOMES_PRELOAD", previous_active_snapshot.get("state") == "PRELOAD" and previous_active_snapshot.get("reduced_visual_loaded") == true, JSON.stringify(previous_active_snapshot))
	streaming.set_active_cell(Vector2i.ZERO)
	await _wait_physics_frames(2)


func _test_camera_relief_stability() -> void:
	await _reposition_player(Vector3(-10.0, 0.0, -9.0), 90)
	var camera_contract: Dictionary = camera_rig.contract_snapshot()
	_check("CAMERA_SMOOTHING_PRESERVED", float(camera_contract.get("follow_half_life_s", 0.0)) > 0.0, JSON.stringify(camera_contract))
	_check("CAMERA_MICRO_HEIGHT_DEADBAND_PRESERVED", is_equal_approx(float(camera_contract.get("micro_height_deadband_m", -1.0)), 0.12), JSON.stringify(camera_contract))
	_check("CAMERA_NO_FREE_ORBIT_PRESERVED", camera_contract.get("free_orbit") == false)
	_check("CAMERA_OCCLUSION_PREPARED_PARTIAL", camera_contract.get("occlusion_probe_prepared") == true)
	var move_result: Dictionary = player.request_move(Vector3(-3.0, 0.0, -9.0))
	_check("RELIEF_CAMERA_TEST_MOVE_REQUEST", move_result.get("status") == "PASS", JSON.stringify(move_result))
	var minimum_camera_y: float = camera_rig.global_position.y
	var maximum_camera_y: float = camera_rig.global_position.y
	var arrived: bool = false
	for frame_index: int in range(420):
		await get_tree().physics_frame
		minimum_camera_y = minf(minimum_camera_y, camera_rig.global_position.y)
		maximum_camera_y = maxf(maximum_camera_y, camera_rig.global_position.y)
		if not player.has_destination():
			arrived = true
			break
	_check("RELIEF_CAMERA_TEST_ARRIVAL", arrived)
	_check("CAMERA_STABLE_OVER_VISUAL_MICRO_RELIEF", maximum_camera_y - minimum_camera_y < 0.012, "min=%f max=%f" % [minimum_camera_y, maximum_camera_y])
	_check("PLAYER_COLLISION_HEIGHT_STABLE_OVER_MICRO_RELIEF", absf(player.global_position.y) < 0.03, str(player.global_position))
	var zoom_before: float = camera_rig.target_distance_m()
	camera_rig.request_zoom_steps(1)
	_check("CAMERA_ZOOM_STILL_OPERATIVE", camera_rig.target_distance_m() > zoom_before and camera_rig.target_distance_m() <= camera_rig.maximum_distance_m)


func _restore_gate_state() -> void:
	main.set_b04_base_route_closure(false, false)
	streaming.set_active_cell(Vector2i.ZERO)
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	player.velocity = Vector3.ZERO
	camera_rig.set_follow_target(player, true)


func _reposition_player(world_position: Vector3, settle_frames: int) -> void:
	player.stop_local_prediction()
	player.global_position = world_position
	player.velocity = Vector3.ZERO
	for frame_index: int in range(settle_frames):
		await get_tree().physics_frame


func _wait_for_navigation(max_frames: int) -> bool:
	for frame_index: int in range(max_frames):
		if main.navigation_ready() and terrain.navigation_region_count() >= 12:
			return true
		await get_tree().physics_frame
	return false


func _wait_for_navigation_iteration_change(frame_count: int) -> void:
	for frame_index: int in range(frame_count):
		await get_tree().physics_frame


func _wait_for_arrival(max_frames: int, monitor_blocker: bool = false) -> Dictionary:
	var entered_blocker: bool = false
	var previous_position: Vector3 = player.global_position
	var maximum_step_m: float = 0.0
	for frame_index: int in range(max_frames):
		await get_tree().physics_frame
		var current_position: Vector3 = player.global_position
		maximum_step_m = maxf(maximum_step_m, _horizontal_distance(previous_position, current_position))
		previous_position = current_position
		if monitor_blocker and absf(current_position.x) < 1.36 and absf(current_position.z) < 4.36:
			entered_blocker = true
		if not player.has_destination():
			var stopped_position: Vector3 = player.global_position
			await _wait_physics_frames(24)
			return {
				"arrived": true,
				"frames": frame_index + 1,
				"maximum_step_m": maximum_step_m,
				"entered_blocker": entered_blocker,
				"post_arrival_drift_m": _horizontal_distance(stopped_position, player.global_position),
			}
	return {
		"arrived": false,
		"frames": max_frames,
		"maximum_step_m": maximum_step_m,
		"entered_blocker": entered_blocker,
		"post_arrival_drift_m": INF,
	}


func _wait_for_item_state(presenter: AndromedaWaterWorldItemPresenter, expected_state: String, max_frames: int) -> bool:
	for frame_index: int in range(max_frames):
		if presenter.presentation_state() == expected_state:
			return true
		await get_tree().physics_frame
	return false


func _wait_physics_frames(frame_count: int) -> void:
	for frame_index: int in range(frame_count):
		await get_tree().physics_frame


func _path_uses_side(path: PackedVector3Array, north: bool) -> bool:
	for point: Vector3 in path:
		if north and point.z >= 4.7:
			return true
		if not north and point.z <= -4.7:
			return true
	return false


func _maximum_path_height(path: PackedVector3Array) -> float:
	var maximum_height: float = -INF
	for point: Vector3 in path:
		maximum_height = maxf(maximum_height, point.y)
	return maximum_height


func _horizontal_distance(first: Vector3, second: Vector3) -> float:
	return Vector2(first.x, first.z).distance_to(Vector2(second.x, second.z))


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "B04_TERRAIN_TRAVERSAL_WATER_STREAMING_FOUNDATION",
		"acceptance_scope_pass": ["G16B-07"],
		"partial_evidence_only": ["G16B-04", "G16B-08", "G16B-09", "G16B-14", "G16B-20", "G16B-24", "G16B-25", "G16B-27"],
		"not_available_without_authoritative_backend": ["STAMINA_MUTATION", "WATER_EXHAUSTION_DEFEAT", "TTL_ADVANCE_SAVE_RELOAD", "LIVING_SYSTEMIC_SNAPSHOT"],
		"authority": "GODOT_SCENE_PHYSICS_NAVIGATION_PRESENTATION_ONLY",
		"backend_roundtrip_executed": false,
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_B04_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_B04_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_B04_SUMMARY: %s" % JSON.stringify(summary))
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
