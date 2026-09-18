extends Node

var _checks: int = 0
var _failures: Array[String] = []

@onready var main: AndromedaMainRuntime = $AndromedaARPG
@onready var player: AndromedaPlayerController = $AndromedaARPG/ActorRoot/Player
@onready var camera_rig: AndromedaIsometricCameraRig = $AndromedaARPG/IsometricCameraRig


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

	var bind_result: Dictionary = session.bind_session("B02-GATE-SESSION")
	_check("SESSION_BOUND_FOR_ENVELOPE_ONLY", bind_result.get("status") == "PASS", JSON.stringify(bind_result))
	_check("EXISTING_BACKEND_URL_UNCHANGED", bridge.server_url() == "http://127.0.0.1:8000")
	_check("NO_BACKEND_SUBSTITUTE", main.contract_snapshot().get("backend_substitute") == false)
	_check("NO_GDSCRIPT_GAMEPLAY_AUTHORITY", main.contract_snapshot().get("gameplay_authority_in_gdscript") == false)
	_check("MAIN_SCENE_CONFIGURED",
		str(ProjectSettings.get_setting("application/run/main_scene")) == "res://scenes/Main.tscn",
		str(ProjectSettings.get_setting("application/run/main_scene")))
	for action_name: String in [
		"pointer_left",
		"pointer_right",
		"camera_zoom_modifier",
		"camera_zoom_in",
		"camera_zoom_out",
	]:
		_check("INPUT_MAP_%s" % action_name.to_upper(),
			InputMap.has_action(action_name) and not InputMap.action_get_events(action_name).is_empty())

	_check("MAIN_ROOT_NAME", main.name == "AndromedaARPG")
	_check("MAIN_RUNTIME_BRIDGE_ROOT", main.has_node("RuntimeBridge"))
	_check("MAIN_WORLD_STREAM_ROOT", main.has_node("WorldStreamRoot"))
	_check("MAIN_ACTOR_ROOT", main.has_node("ActorRoot"))
	_check("MAIN_GROUND_LOOT_ROOT", main.has_node("GroundLootRoot"))
	_check("MAIN_EFFECTS_ROOT", main.has_node("EffectsRoot"))
	_check("MAIN_CAMERA_RIG", main.has_node("IsometricCameraRig"))
	_check("MAIN_UI_LAYER", main.has_node("UILayer"))
	_check("PLAYER_CHARACTER_BODY", player is CharacterBody3D)
	_check("PLAYER_COLLISION_SHAPE", player.has_node("CollisionShape3D"))
	_check("PLAYER_NAVIGATION_AGENT", player.has_node("NavigationAgent3D"))
	_check("PLAYER_VISUAL_ROOT", player.has_node("VisualRoot"))
	_check("PLAYER_HURTBOX", player.has_node("Hurtbox"))
	_check("PLAYER_DIALOGUE_ANCHOR", player.has_node("DialogueAnchor"))
	_check("PLAYER_TARGET_ANCHOR", player.has_node("TargetAnchor"))
	_check("PLAYER_SPAWN", player.global_position.distance_to(Vector3(-7.0, 0.0, 0.0)) < 0.02, str(player.global_position))
	_check("VISUAL_COLLISION_TRAVERSAL_SEPARATED",
		main.has_node("WorldStreamRoot/VisualSurface")
		and main.has_node("WorldStreamRoot/CollisionSurface")
		and main.has_node("WorldStreamRoot/TraversalSurface"))

	var navigation_became_ready: bool = await _wait_for_navigation(180)
	_check("NAVIGATION_MAP_READY", navigation_became_ready)
	if not navigation_became_ready:
		await _finish()
		return
	_check("NAVIGATION_MESH_EIGHT_WALKABLE_CELLS", main.navigation_mesh_polygon_count() == 8, str(main.navigation_mesh_polygon_count()))
	var upper_left_probe := Vector3(-8.0, 0.0, 5.5)
	_check("NAVIGATION_UPPER_LEFT_CELL_PRESENT",
		_horizontal_distance(main.closest_navigation_point(upper_left_probe), upper_left_probe) < 0.02,
		"requested=%s closest=%s" % [upper_left_probe, main.closest_navigation_point(upper_left_probe)])

	_test_input_contract(router)
	await _test_impossible_destination()
	await _test_actual_clicks_target_stability_and_smoothing()
	await _test_consecutive_and_rapid_destinations()
	await _test_navigation_collision_and_arrival()
	await _test_camera_contract()

	await _finish()


func _test_input_contract(router: AndromedaInputRouter) -> void:
	var left_ground: Dictionary = router.resolve_pointer_click(
		MOUSE_BUTTON_LEFT,
		AndromedaInputRouter.HIT_GROUND,
		Vector3(-6.0, 0.0, 2.0)
	)
	_check("LEFT_GROUND_MOVE", left_ground.get("intent") == "MOVE_TO_POINT", JSON.stringify(left_ground))
	var right_ground: Dictionary = router.resolve_pointer_click(
		MOUSE_BUTTON_RIGHT,
		AndromedaInputRouter.HIT_GROUND,
		Vector3(-6.0, 0.0, -2.0)
	)
	_check("RIGHT_GROUND_MOVE", right_ground.get("intent") == "MOVE_TO_POINT", JSON.stringify(right_ground))
	var left_target: Dictionary = router.resolve_pointer_click(
		MOUSE_BUTTON_LEFT,
		AndromedaInputRouter.HIT_NPC,
		Vector3.ZERO,
		"NPC-B02"
	)
	_check("LEFT_TARGET_SELECT_ONLY",
		left_target.get("intent") == "SELECT_TARGET" and left_target.get("movement_change") == "NONE",
		JSON.stringify(left_target))
	var right_hostile: Dictionary = router.resolve_pointer_click(
		MOUSE_BUTTON_RIGHT,
		AndromedaInputRouter.HIT_ACTOR,
		Vector3.ZERO,
		"ENEMY-B02",
		true
	)
	_check("RIGHT_HOSTILE_FUTURE_CHASE_ATTACK",
		right_hostile.get("intent") == "CHASE_ATTACK" and right_hostile.get("implementation_stage") == "FUTURE",
		JSON.stringify(right_hostile))
	var right_npc: Dictionary = router.resolve_pointer_click(
		MOUSE_BUTTON_RIGHT,
		AndromedaInputRouter.HIT_NPC,
		Vector3.ZERO,
		"NPC-B02"
	)
	_check("RIGHT_NPC_FUTURE_APPROACH_INTERACT",
		right_npc.get("intent") == "APPROACH_INTERACT" and right_npc.get("implementation_stage") == "FUTURE",
		JSON.stringify(right_npc))
	var loot_approach: Dictionary = router.resolve_pointer_click(
		MOUSE_BUTTON_LEFT,
		AndromedaInputRouter.HIT_GROUND_LOOT,
		Vector3(-3.5, 0.0, 3.0),
		"LOOT-B02",
		false,
		2.0,
		true
	)
	_check("GROUND_LOOT_MOVEMENT_EXCEPTION", loot_approach.get("intent") == "APPROACH_PICKUP", JSON.stringify(loot_approach))
	var loot_near: Dictionary = router.resolve_pointer_click(
		MOUSE_BUTTON_LEFT,
		AndromedaInputRouter.HIT_GROUND_LOOT,
		Vector3.ZERO,
		"LOOT-B02",
		false,
		0.5,
		true
	)
	_check("GROUND_LOOT_PICKUP_RADIUS_PRESERVED",
		loot_near.get("intent") == "PICKUP" and is_equal_approx(float(loot_near.get("max_pickup_distance_m")), 0.5),
		JSON.stringify(loot_near))
	var ordinary_wheel: Dictionary = router.resolve_wheel(MOUSE_BUTTON_WHEEL_UP, false, false)
	_check("UNMODIFIED_WHEEL_WEAPON_CYCLE_ONLY",
		ordinary_wheel.get("intent") == "WEAPON_QUICK_SLOT_CYCLE" and ordinary_wheel.get("quick_slot_count") == 2,
		JSON.stringify(ordinary_wheel))
	var modified_wheel: Dictionary = router.resolve_wheel(MOUSE_BUTTON_WHEEL_UP, true, false)
	_check("MODIFIED_WHEEL_CAMERA_ZOOM_ONLY", modified_wheel.get("intent") == "CAMERA_ZOOM", JSON.stringify(modified_wheel))
	var menu_wheel: Dictionary = router.resolve_wheel(MOUSE_BUTTON_WHEEL_UP, true, true)
	_check("MENU_WHEEL_SCROLL_ONLY", menu_wheel.get("intent") == "MENU_SCROLL", JSON.stringify(menu_wheel))


func _test_impossible_destination() -> void:
	var before_destination: Vector3 = player.requested_destination()
	var impossible_validation: Dictionary = player.validate_destination(Vector3(0.0, 0.0, 0.0))
	_check("IMPOSSIBLE_DESTINATION_VALIDATION_REJECTED",
		impossible_validation.get("status") == "REJECTED"
		and impossible_validation.get("reason") == "UNREACHABLE_DESTINATION",
		JSON.stringify(impossible_validation))
	var impossible_click: Dictionary = main.handle_pointer_event(
		_mouse_button(MOUSE_BUTTON_LEFT, main.world_to_screen(Vector3(0.0, 1.0, 0.0)))
	)
	_check("IMPOSSIBLE_CLICK_REJECTED",
		impossible_click.get("status") == "REJECTED"
		and impossible_click.get("reason") == "UNREACHABLE_DESTINATION",
		JSON.stringify(impossible_click))
	_check("IMPOSSIBLE_CLICK_PRESERVES_DESTINATION", player.requested_destination().is_equal_approx(before_destination))
	await get_tree().physics_frame


func _test_actual_clicks_target_stability_and_smoothing() -> void:
	var camera_before: Vector3 = camera_rig.global_position
	var move_click: Dictionary = main.handle_pointer_event(
		_mouse_button(MOUSE_BUTTON_LEFT, main.world_to_screen(Vector3(-8.0, 0.0, 5.5)))
	)
	_check("ACTUAL_LEFT_CLICK_RAYCAST_MOVE",
		move_click.get("status") == "PASS" and move_click.get("intent") == "MOVE_TO_POINT",
		JSON.stringify(move_click))
	_check("MOVE_BRIDGE_ENVELOPE_BUILT",
		move_click.get("movement_result", {}).get("bridge_envelope", {}).get("status") == "PASS",
		JSON.stringify(move_click))
	var bridge_envelope: Dictionary = move_click.get("movement_result", {}).get("bridge_envelope", {}).get("envelope", {})
	_check("MOVE_ENVELOPE_SESSION_NOT_PLAYER_REF",
		bridge_envelope.get("session_ref") == "B02-GATE-SESSION"
		and bridge_envelope.get("command") == "MOVE_TO_POINT"
		and not bridge_envelope.has("player_ref")
		and not bridge_envelope.get("params", {}).has("player_ref"),
		JSON.stringify(bridge_envelope))
	await _wait_physics_frames(5)
	_check("PLAYER_STARTED_MOVING", _horizontal_speed(player.velocity) > 0.05, str(player.velocity))
	var camera_lag_m: float = _horizontal_distance(camera_rig.global_position, player.global_position)
	_check("CAMERA_SMOOTHING_NOT_SNAP", camera_lag_m > 0.005, str(camera_lag_m))
	_check("CAMERA_STARTED_FOLLOWING", _horizontal_distance(camera_rig.global_position, camera_before) > 0.001)

	var destination_before_target: Vector3 = player.requested_destination()
	var npc: Area3D = main.get_node("ActorRoot/NpcPointerPlaceholder") as Area3D
	var target_click: Dictionary = main.handle_pointer_event(
		_mouse_button(MOUSE_BUTTON_LEFT, main.world_to_screen(npc.global_position))
	)
	_check("ACTUAL_TARGET_CLICK_SELECTS", target_click.get("intent") == "SELECT_TARGET", JSON.stringify(target_click))
	_check("TARGET_CLICK_DOES_NOT_CHANGE_MOVEMENT",
		player.requested_destination().is_equal_approx(destination_before_target),
		"before=%s after=%s" % [destination_before_target, player.requested_destination()])
	var target_ref_before_camera_motion: String = main.last_pointer_target_ref()
	var serial_before_camera_motion: int = main.pointer_resolution_serial()
	await _wait_physics_frames(24)
	_check("CAMERA_MOTION_DOES_NOT_REQUERY_TARGET",
		main.last_pointer_target_ref() == target_ref_before_camera_motion
		and main.pointer_resolution_serial() == serial_before_camera_motion,
		"target=%s serial=%d" % [main.last_pointer_target_ref(), main.pointer_resolution_serial()])
	var destination_before_loot: Vector3 = player.requested_destination()
	var loot: Area3D = main.get_node("GroundLootRoot/GroundLootPlaceholder") as Area3D
	var loot_click: Dictionary = main.handle_pointer_event(
		_mouse_button(MOUSE_BUTTON_LEFT, main.world_to_screen(loot.global_position))
	)
	_check("ACTUAL_GROUND_LOOT_CLICK_APPROACHES",
		loot_click.get("status") == "PASS" and loot_click.get("intent") == "APPROACH_PICKUP",
		JSON.stringify(loot_click))
	_check("GROUND_LOOT_EXCEPTION_CHANGES_DESTINATION",
		not player.requested_destination().is_equal_approx(destination_before_loot)
		and _horizontal_distance(player.requested_destination(), loot.global_position) < 0.08,
		"before=%s after=%s loot=%s" % [destination_before_loot, player.requested_destination(), loot.global_position])
	player.stop_local_prediction()


func _test_consecutive_and_rapid_destinations() -> void:
	var first: Dictionary = main.handle_pointer_event(
		_mouse_button(MOUSE_BUTTON_LEFT, main.world_to_screen(Vector3(-9.0, 0.0, 4.0)))
	)
	var second: Dictionary = main.handle_pointer_event(
		_mouse_button(MOUSE_BUTTON_RIGHT, main.world_to_screen(Vector3(-6.0, 0.0, 4.5)))
	)
	_check("CONSECUTIVE_DESTINATION_ONE_PASS", first.get("status") == "PASS", JSON.stringify(first))
	_check("CONSECUTIVE_DESTINATION_TWO_PASS", second.get("status") == "PASS", JSON.stringify(second))
	_check("LATEST_DESTINATION_REPLACES_PREVIOUS",
		_horizontal_distance(player.requested_destination(), Vector3(-6.0, 0.0, 4.5)) < 0.08,
		str(player.requested_destination()))
	var rapid_points: Array[Vector3] = [
		Vector3(-8.5, 0.0, 2.0),
		Vector3(-6.5, 0.0, 2.5),
		Vector3(-8.0, 0.0, 3.0),
		Vector3(-6.0, 0.0, 3.5),
		Vector3(-8.5, 0.0, 4.0),
		Vector3(-6.0, 0.0, 4.0),
	]
	var rapid_passes: int = 0
	for point: Vector3 in rapid_points:
		var rapid_result: Dictionary = main.handle_pointer_event(
			_mouse_button(MOUSE_BUTTON_LEFT, main.world_to_screen(point))
		)
		if rapid_result.get("status") == "PASS":
			rapid_passes += 1
	_check("RAPID_CLICK_NO_LOCK", rapid_passes == rapid_points.size(), "%d/%d" % [rapid_passes, rapid_points.size()])
	_check("RAPID_CLICK_FINAL_DESTINATION",
		_horizontal_distance(player.requested_destination(), rapid_points[rapid_points.size() - 1]) < 0.08,
		str(player.requested_destination()))
	var arrived: Dictionary = await _wait_for_arrival(480)
	_check("RAPID_FINAL_DESTINATION_ARRIVED", arrived.get("arrived") == true, JSON.stringify(arrived))
	_check("ARRIVAL_CLEARS_DESTINATION", not player.has_destination())
	_check("ARRIVAL_ZERO_HORIZONTAL_VELOCITY", _horizontal_speed(player.velocity) < 0.001, str(player.velocity))
	var stopped_position: Vector3 = player.global_position
	await _wait_physics_frames(24)
	_check("ARRIVAL_STAYS_STOPPED", _horizontal_distance(stopped_position, player.global_position) < 0.005,
		"before=%s after=%s" % [stopped_position, player.global_position])


func _test_navigation_collision_and_arrival() -> void:
	var cross_destination := Vector3(7.0, 0.0, 0.0)
	var path: PackedVector3Array = player.preview_path(cross_destination)
	_check("NAVIGATION_PATH_VALID", path.size() >= 3, str(path))
	var detours_around_blocker: bool = false
	for path_point: Vector3 in path:
		if absf(path_point.z) >= 4.7:
			detours_around_blocker = true
			break
	_check("NAVIGATION_PATH_DETOURS_COLLISION", detours_around_blocker, str(path))
	var collision_query: PhysicsRayQueryParameters3D = PhysicsRayQueryParameters3D.create(
		Vector3(-2.0, 1.0, 0.0),
		Vector3(2.0, 1.0, 0.0),
		1,
		[player.get_rid()]
	)
	var collision_hit: Dictionary = player.get_world_3d().direct_space_state.intersect_ray(collision_query)
	_check("CENTRAL_BLOCKER_COLLISION_PRESENT",
		not collision_hit.is_empty() and str(collision_hit.get("collider").name) == "CentralBlocker",
		str(collision_hit))
	var cross_request: Dictionary = player.request_move(cross_destination)
	_check("CROSS_OBSTACLE_REQUEST_PASS", cross_request.get("status") == "PASS", JSON.stringify(cross_request))
	var arrived: Dictionary = await _wait_for_arrival(900, true)
	_check("PLAYER_NEVER_ENTERED_BLOCKER", arrived.get("entered_blocker") == false, JSON.stringify(arrived))
	_check("CROSS_OBSTACLE_ARRIVED", arrived.get("arrived") == true, JSON.stringify(arrived))
	_check("NO_MOVEMENT_STEP_SPIKE", float(arrived.get("maximum_step_m", INF)) < 0.18, JSON.stringify(arrived))
	_check("CROSS_DESTINATION_ACCURATE", _horizontal_distance(player.global_position, cross_destination) < 0.2, str(player.global_position))
	var final_position: Vector3 = player.global_position
	await _wait_physics_frames(30)
	_check("CROSS_ARRIVAL_NO_JITTER", _horizontal_distance(final_position, player.global_position) < 0.005,
		"before=%s after=%s" % [final_position, player.global_position])
	await _wait_physics_frames(120)
	_check("CAMERA_CONVERGES_ON_PLAYER",
		_horizontal_distance(camera_rig.global_position, player.global_position) < 0.04,
		"camera=%s player=%s" % [camera_rig.global_position, player.global_position])


func _test_camera_contract() -> void:
	var camera_contract: Dictionary = camera_rig.contract_snapshot()
	_check("CAMERA_ISOMETRIC_YAW", is_equal_approx(float(camera_contract.get("yaw_degrees")), 45.0))
	_check("CAMERA_OBLIQUE_PITCH", is_equal_approx(float(camera_contract.get("pitch_degrees")), 55.0))
	_check("CAMERA_NO_FREE_ORBIT", camera_contract.get("free_orbit") == false)
	_check("CAMERA_OCCLUSION_PROBE_PREPARED",
		camera_contract.get("occlusion_probe_prepared") == true
		and is_equal_approx(float(camera_contract.get("occluder_fade_alpha")), 0.2),
		JSON.stringify(camera_contract))
	_check("CAMERA_FOLLOWS_PLAYER", camera_rig.follow_target() == player)

	var initial_zoom_target: float = camera_rig.target_distance_m()
	var ordinary_wheel: Dictionary = main.handle_pointer_event(_mouse_button(MOUSE_BUTTON_WHEEL_UP, Vector2.ZERO))
	_check("ACTUAL_UNMODIFIED_WHEEL_NOT_ZOOM",
		ordinary_wheel.get("intent") == "WEAPON_QUICK_SLOT_CYCLE"
		and is_equal_approx(camera_rig.target_distance_m(), initial_zoom_target),
		JSON.stringify(ordinary_wheel))
	var modified_wheel: Dictionary = main.handle_pointer_event(_mouse_button(MOUSE_BUTTON_WHEEL_UP, Vector2.ZERO, true))
	_check("ACTUAL_MODIFIED_WHEEL_ZOOMS",
		modified_wheel.get("intent") == "CAMERA_ZOOM"
		and camera_rig.target_distance_m() < initial_zoom_target,
		JSON.stringify(modified_wheel))
	for index: int in range(40):
		main.handle_pointer_event(_mouse_button(MOUSE_BUTTON_WHEEL_UP, Vector2.ZERO, true))
	_check("CAMERA_ZOOM_MIN_CLAMP", is_equal_approx(camera_rig.target_distance_m(), camera_rig.minimum_distance_m))
	for index: int in range(80):
		main.handle_pointer_event(_mouse_button(MOUSE_BUTTON_WHEEL_DOWN, Vector2.ZERO, true))
	_check("CAMERA_ZOOM_MAX_CLAMP", is_equal_approx(camera_rig.target_distance_m(), camera_rig.maximum_distance_m))
	await _wait_physics_frames(90)
	_check("CAMERA_CURRENT_ZOOM_WITHIN_CLAMPS",
		camera_rig.camera_distance_m() >= camera_rig.minimum_distance_m - 0.001
		and camera_rig.camera_distance_m() <= camera_rig.maximum_distance_m + 0.001,
		str(camera_rig.camera_distance_m()))
	main.set_menu_open(true)
	var menu_wheel: Dictionary = main.handle_pointer_event(_mouse_button(MOUSE_BUTTON_WHEEL_DOWN, Vector2.ZERO, true))
	main.set_menu_open(false)
	_check("ACTUAL_MENU_WHEEL_SCROLL_ONLY", menu_wheel.get("intent") == "MENU_SCROLL", JSON.stringify(menu_wheel))

	var yaw_before_motion: float = camera_rig.yaw_degrees
	var pitch_before_motion: float = camera_rig.pitch_degrees
	var mouse_motion := InputEventMouseMotion.new()
	mouse_motion.relative = Vector2(120.0, -80.0)
	main.handle_pointer_event(mouse_motion)
	await get_tree().physics_frame
	_check("MOUSE_MOTION_CANNOT_ORBIT",
		is_equal_approx(camera_rig.yaw_degrees, yaw_before_motion)
		and is_equal_approx(camera_rig.pitch_degrees, pitch_before_motion))

	var proxy := Node3D.new()
	proxy.name = "B02MicroHeightProbe"
	main.get_node("ActorRoot").add_child(proxy)
	proxy.global_position = player.global_position
	camera_rig.set_follow_target(proxy, true)
	var camera_height_before: float = camera_rig.global_position.y
	var micro_position: Vector3 = proxy.global_position
	micro_position.y += 0.08
	proxy.global_position = micro_position
	await _wait_physics_frames(30)
	_check("CAMERA_IGNORES_MICRO_HEIGHT",
		absf(camera_rig.global_position.y - camera_height_before) < 0.002,
		"before=%f after=%f" % [camera_height_before, camera_rig.global_position.y])
	var material_height_position: Vector3 = proxy.global_position
	material_height_position.y += 0.30
	proxy.global_position = material_height_position
	await _wait_physics_frames(60)
	_check("CAMERA_SMOOTHS_MATERIAL_HEIGHT_CHANGE",
		camera_rig.global_position.y > camera_height_before + 0.20,
		"before=%f after=%f" % [camera_height_before, camera_rig.global_position.y])
	camera_rig.set_follow_target(player, true)
	proxy.queue_free()


func _wait_for_navigation(max_frames: int) -> bool:
	for frame_index: int in range(max_frames):
		if main.navigation_ready():
			return true
		await get_tree().physics_frame
	return false


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
			return {
				"arrived": true,
				"frames": frame_index + 1,
				"entered_blocker": entered_blocker,
				"maximum_step_m": maximum_step_m,
			}
	return {
		"arrived": false,
		"frames": max_frames,
		"entered_blocker": entered_blocker,
		"maximum_step_m": maximum_step_m,
	}


func _wait_physics_frames(frame_count: int) -> void:
	for frame_index: int in range(frame_count):
		await get_tree().physics_frame


func _mouse_button(button_index: int, position: Vector2, shift_pressed: bool = false) -> InputEventMouseButton:
	var event := InputEventMouseButton.new()
	event.button_index = button_index as MouseButton
	event.position = position
	event.global_position = position
	event.shift_pressed = shift_pressed
	event.pressed = true
	return event


func _horizontal_distance(first: Vector3, second: Vector3) -> float:
	return Vector2(first.x, first.z).distance_to(Vector2(second.x, second.z))


func _horizontal_speed(value: Vector3) -> float:
	return Vector2(value.x, value.z).length()


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "B02_MAIN_PLAYER_CAMERA_CLICK_NAVIGATION",
		"acceptance_scope": ["G16B-02"],
		"partial_evidence_only": ["G16B-14", "G16B-20"],
		"authority": "GODOT_INPUT_SCENE_PHYSICS_PRESENTATION_ONLY",
		"backend_roundtrip_executed": false,
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_B02_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_B02_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_B02_SUMMARY: %s" % JSON.stringify(summary))
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
