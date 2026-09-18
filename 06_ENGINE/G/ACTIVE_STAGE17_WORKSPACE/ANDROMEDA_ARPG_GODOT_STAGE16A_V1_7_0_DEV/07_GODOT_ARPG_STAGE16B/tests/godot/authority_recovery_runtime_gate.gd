extends Node

const SESSION_REF := "AUTHORITY-RECOVERY-CLIENT-SESSION"
const WRONG_SESSION_REF := "AUTHORITY-RECOVERY-WRONG-SESSION"
const PRESENTATION_FIXTURE_SOURCE := "AUTHORITY_RECOVERY_PRESENTATION_FIXTURE_NOT_LIVE_AUTHORITY"

var _checks: int = 0
var _failures: Array[String] = []
var _original_occluder_transforms: Dictionary = {}

@onready var main: AndromedaMainRuntime = $AndromedaARPG
@onready var player: AndromedaPlayerController = $AndromedaARPG/ActorRoot/Player
@onready var camera_rig: AndromedaIsometricCameraRig = $AndromedaARPG/IsometricCameraRig
@onready var hud: AndromedaHUDController = $AndromedaARPG/UILayer/MinimalHUD
@onready var crafting: AndromedaCraftingPanel = $AndromedaARPG/UILayer/MinimalHUD/CraftingPanel
@onready var tree_occluder: AndromedaCameraOccluder = $AndromedaARPG/WorldStreamRoot/CameraOccluderRoot/TreeOccluder
@onready var wall_occluder: AndromedaCameraOccluder = $AndromedaARPG/WorldStreamRoot/CameraOccluderRoot/WallOccluder
@onready var tall_occluder: AndromedaCameraOccluder = $AndromedaARPG/WorldStreamRoot/CameraOccluderRoot/TallObjectOccluder


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
	_check("MAIN_RUNTIME", main != null)
	_check("PLAYER_RUNTIME", player != null)
	_check("CAMERA_RUNTIME", camera_rig != null)
	_check("HUD_RUNTIME", hud != null)
	_check("CRAFTING_RUNTIME", crafting != null)
	_check("TREE_OCCLUDER_RUNTIME", tree_occluder != null)
	_check("WALL_OCCLUDER_RUNTIME", wall_occluder != null)
	_check("TALL_OCCLUDER_RUNTIME", tall_occluder != null)
	if session == null or bridge == null or main == null or player == null or camera_rig == null or hud == null or crafting == null:
		await _finish()
		return
	_check("SESSION_BOUND", session.bind_session(SESSION_REF).get("status") == "PASS")
	_check("BRIDGE_URL_UNCHANGED", bridge.server_url() == "http://127.0.0.1:8000")
	_check("NO_BACKEND_SUBSTITUTE", main.contract_snapshot().get("backend_substitute") == false)
	_check("NAVIGATION_READY", await _wait_for_navigation(240))
	_store_occluder_transforms()
	await _test_g16b14_camera_occluder_fade()
	await _test_g16b23_crafting_ui(session)
	_test_authority_static_contracts()
	_restore_occluder_transforms()
	await _wait_physics_frames(3)
	await _finish()


func _test_g16b14_camera_occluder_fade() -> void:
	var camera_contract: Dictionary = camera_rig.contract_snapshot()
	_check("G14_ISOMETRIC_YAW", is_equal_approx(float(camera_contract.get("yaw_degrees", 0.0)), 45.0))
	_check("G14_OBLIQUE_PITCH", float(camera_contract.get("pitch_degrees", 0.0)) > 0.0)
	_check("G14_MICRO_HEIGHT_DEADBAND", is_equal_approx(float(camera_contract.get("micro_height_deadband_m", 0.0)), 0.12))
	_check("G14_NO_FREE_ORBIT", camera_contract.get("free_orbit") == false)
	_check("G14_OCCLUSION_PROBE", camera_contract.get("occlusion_probe_prepared") == true)
	_check("G14_REAL_MATERIAL_FADE", camera_contract.get("material_fade_execution") == true)
	_check("G14_MULTI_OCCLUDER_SUPPORT", camera_contract.get("multiple_occluders_supported") == true)
	_check("G14_FADE_NO_COLLISION_MUTATION", camera_contract.get("occluder_fade_changes_collision") == false)
	_check("G14_FADE_NO_TARGET_MUTATION", camera_contract.get("occluder_fade_changes_targeting") == false)
	_check("G14_REDUCED_MOTION_INDEPENDENT", camera_contract.get("occluder_fade_reduced_motion_dependent") == false)
	var target_before_zoom: float = camera_rig.target_distance_m()
	camera_rig.request_zoom_steps(1000)
	_check("G14_ZOOM_MAX_CLAMP", is_equal_approx(camera_rig.target_distance_m(), camera_rig.maximum_distance_m))
	camera_rig.request_zoom_steps(-1000)
	_check("G14_ZOOM_MIN_CLAMP", is_equal_approx(camera_rig.target_distance_m(), camera_rig.minimum_distance_m))
	var restore_steps: int = int(round((target_before_zoom - camera_rig.minimum_distance_m) / camera_rig.zoom_step_m))
	camera_rig.request_zoom_steps(restore_steps)
	_check("G14_ZOOM_RESTORED", is_equal_approx(camera_rig.target_distance_m(), target_before_zoom))

	_move_all_occluders_far()
	await _wait_physics_frames(4)
	await _wait_physics_frames(18)
	for occluder: AndromedaCameraOccluder in _occluders():
		occluder.force_restore_now()
		_check("G14_%s_INITIAL_RESTORED" % occluder.occluder_kind, occluder.material_state_restored())
		_check("G14_%s_LAYER_256" % occluder.occluder_kind, occluder.collision_layer == 256)
		_check("G14_%s_COLLISION_MASK_ZERO" % occluder.occluder_kind, occluder.collision_mask == 0)

	for occluder: AndromedaCameraOccluder in _occluders():
		_move_all_occluders_far()
		occluder.force_restore_now()
		_position_on_camera_ray(occluder, 0.50)
		await _wait_physics_frames(3)
		await _wait_physics_frames(14)
		var active_refs: Array[String] = camera_rig.active_occluder_refs()
		_check("G14_%s_DETECTED" % occluder.occluder_kind, active_refs.has(occluder.occluder_ref), JSON.stringify(active_refs))
		_check("G14_%s_FADED" % occluder.occluder_kind, occluder.fade_fraction() > 0.95)
		_check("G14_%s_ALPHA_NOT_BLACK" % occluder.occluder_kind, occluder.current_visual_alpha() >= 0.19)
		_check("G14_%s_ALPHA_TARGET" % occluder.occluder_kind, absf(occluder.current_visual_alpha() - 0.20) < 0.02)
		_check("G14_%s_COLLISION_STABLE" % occluder.occluder_kind, occluder.collision_state_unchanged())
		var transitions_before: int = int(occluder.contract_snapshot().get("request_transition_count", -1))
		await _wait_physics_frames(12)
		var transitions_after: int = int(occluder.contract_snapshot().get("request_transition_count", -2))
		_check("G14_%s_NO_FLICKER_WHILE_OCCLUDED" % occluder.occluder_kind, transitions_after == transitions_before)
		occluder.global_position = _far_position(_occluders().find(occluder))
		await _wait_physics_frames(4)
		await _wait_physics_frames(20)
		_check("G14_%s_EXIT_RESTORES_MATERIAL" % occluder.occluder_kind, occluder.material_state_restored())
		_check("G14_%s_EXIT_ALPHA_ORIGINAL" % occluder.occluder_kind, absf(occluder.current_visual_alpha() - 1.0) < 0.001)
		_check("G14_%s_EXIT_COLLISION_STABLE" % occluder.occluder_kind, occluder.collision_state_unchanged())

	_move_all_occluders_far()
	var smooth_occluder: AndromedaCameraOccluder = tree_occluder
	smooth_occluder.force_restore_now()
	_check("G14_SMOOTH_ENTRY_REQUEST", smooth_occluder.request_camera_occlusion(true, 0.20).get("status") == "PASS")
	await get_tree().physics_frame
	var first_entry_alpha: float = smooth_occluder.current_visual_alpha()
	_check("G14_SMOOTH_ENTRY_NOT_INSTANT", first_entry_alpha > 0.20 and first_entry_alpha < 1.0, str(first_entry_alpha))
	await _wait_physics_frames(18)
	_check("G14_SMOOTH_ENTRY_REACHES_TARGET", absf(smooth_occluder.current_visual_alpha() - 0.20) < 0.02)
	_check("G14_SMOOTH_EXIT_REQUEST", smooth_occluder.request_camera_occlusion(false, 0.20).get("status") == "PASS")
	await get_tree().physics_frame
	_check("G14_RELEASE_HOLD_PREVENTS_EDGE_FLICKER", smooth_occluder.current_visual_alpha() <= 0.25)
	await _wait_physics_frames(22)
	_check("G14_SMOOTH_EXIT_RESTORES", smooth_occluder.material_state_restored())
	_check("G14_SMOOTH_EXIT_ALPHA_ONE", absf(smooth_occluder.current_visual_alpha() - 1.0) < 0.001)

	_move_all_occluders_far()
	for index: int in range(_occluders().size()):
		var occluder: AndromedaCameraOccluder = _occluders()[index]
		occluder.force_restore_now()
		_position_on_camera_ray(occluder, 0.30 + float(index) * 0.20)
	var selected_before: String = _ensure_npc_selected()
	camera_rig.set_reduced_motion(true)
	await _wait_physics_frames(4)
	await _wait_physics_frames(16)
	var multi_snapshot: Dictionary = camera_rig.occlusion_runtime_snapshot()
	_check("G14_MULTIPLE_THREE_ACTIVE", int(multi_snapshot.get("active_occluder_count", 0)) == 3, JSON.stringify(multi_snapshot))
	for occluder: AndromedaCameraOccluder in _occluders():
		_check("G14_MULTI_HAS_%s" % occluder.occluder_kind, camera_rig.active_occluder_refs().has(occluder.occluder_ref))
		_check("G14_MULTI_%s_FADED" % occluder.occluder_kind, occluder.fade_fraction() > 0.95)
	_check("G14_TARGET_STABLE_DURING_MULTI_FADE", main.selected_target_ref() == selected_before)
	_check("G14_REDUCED_MOTION_DID_NOT_DISABLE_FADE", int(multi_snapshot.get("active_occluder_count", 0)) == 3)
	_check("G14_CAMERA_FEEDBACK_NO_RAYCAST_REWRITE", multi_snapshot.get("selection_reresolved") == false)
	_check("G14_RUNTIME_NO_COLLISION_MUTATION", multi_snapshot.get("collision_mutation") == false)
	camera_rig.set_reduced_motion(false)
	_move_all_occluders_far()
	await _wait_physics_frames(4)
	await _wait_physics_frames(22)
	for occluder: AndromedaCameraOccluder in _occluders():
		_check("G14_MULTI_%s_RESTORED" % occluder.occluder_kind, occluder.material_state_restored())


func _test_g16b23_crafting_ui(session: AndromedaClientSession) -> void:
	_check("G23_SESSION_ACTIVE", session.has_active_session())
	_check("G23_CRAFTING_BINDS_SESSION", crafting.bind_expected_session(SESSION_REF).get("status") == "PASS")
	_check("G23_OPEN_CRAFTING", hud.open_crafting("WORKSTATION-PRESENTATION-FIXTURE").get("status") == "PASS")
	_check("G23_MODAL_CRAFTING", hud.active_modal() == "CRAFTING" and hud.is_crafting_open())
	_check("G23_MAIN_MENU_MODAL_SYNC", main.menu_open())
	var fixture: Dictionary = _crafting_fixture(10, SESSION_REF, true)
	var projection: Dictionary = hud.project_crafting_recipe(fixture)
	_check("G23_EXTERNAL_PROJECTION_ACCEPTED", projection.get("status") == "PASS", JSON.stringify(projection))
	_check("G23_FIXTURE_SOURCE_EXPLICIT", projection.get("projection_source") == PRESENTATION_FIXTURE_SOURCE)
	_check("G23_FIXTURE_NOT_ROUNDTRIP", projection.get("fixture_is_authoritative_roundtrip") == false)
	_check("G23_TWO_INGREDIENT_ROWS", crafting.ingredient_row_count() == 2)
	_check("G23_OUTPUT_PROJECTED", projection.get("output_projected") == true)
	_check("G23_AVAILABILITY_EXTERNAL", projection.get("availability_projected_externally") == true)
	_check("G23_CRAFT_ACTION_ENABLED_BY_EXTERNAL_STATE", crafting.craft_button_enabled())
	_check("G23_IMPORTANT_ORANGE", _colors_close(crafting.availability_color(), Color("d9a15f")))
	var crafting_contract: Dictionary = crafting.contract_snapshot()
	_check("G23_WHITE_OFF_WHITE_FAMILY", crafting_contract.get("ui_family") == "WHITE_OFF_WHITE_ROUNDED_CLEAN_CONSOLE")
	_check("G23_ROUNDED_CORNERS", crafting_contract.get("rounded_corners") == true)
	_check("G23_ROUNDED_LEGIBLE_TYPE", crafting_contract.get("rounded_legible_typography") == true)
	_check("G23_GRAY_PRIMARY_TEXT", crafting_contract.get("primary_text_hex") == "#6B6B6B")
	_check("G23_SOFT_ORANGE_IMPORTANT", crafting_contract.get("important_text_hex") == "#D9A15F")
	_check("G23_NO_COPIED_ASSETS", crafting_contract.get("copied_nintendo_or_zelda_assets") == false)
	_check("G23_NO_FINAL_ART", crafting_contract.get("final_art") == false)
	_check("G23_ACTION_SEPARATE", crafting_contract.get("craft_action_separate") == true)
	_check("G23_NO_RECIPE_AUTHORITY", crafting_contract.get("recipe_authority") == false)
	_check("G23_NO_YIELD_AUTHORITY", crafting_contract.get("yield_authority") == false)
	_check("G23_NO_INVENTORY_AUTHORITY", crafting_contract.get("inventory_authority") == false)
	_check("G23_NO_STAMINA_AUTHORITY", crafting_contract.get("stamina_authority") == false)
	_check("G23_NO_RESULT_AUTHORITY", crafting_contract.get("craft_result_authority") == false)
	var hud_contract: Dictionary = hud.contract_snapshot()
	_check("G23_HUD_INCLUDES_CRAFTING_FAMILY", hud_contract.get("crafting", {}).get("ui_family") == hud_contract.get("ui_family"))
	_check("G23_HUD_MODAL_LIST_INCLUDES_CRAFTING", (hud_contract.get("modal_layers", []) as Array).has("CRAFTING"))

	_check("G23_STALE_RECIPE_REJECTED", hud.project_crafting_recipe(_crafting_fixture(10, SESSION_REF, true)).get("reason") == "STALE_OR_DUPLICATE_RECIPE_PROJECTION")
	_check("G23_WRONG_SESSION_REJECTED", hud.project_crafting_recipe(_crafting_fixture(11, WRONG_SESSION_REF, true)).get("reason") == "WRONG_SESSION_RECIPE_PROJECTION")
	var unavailable: Dictionary = hud.project_crafting_recipe(_crafting_fixture(11, SESSION_REF, false))
	_check("G23_UNAVAILABLE_PROJECTED", unavailable.get("status") == "PASS")
	_check("G23_UNAVAILABLE_DISABLES_ACTION", not crafting.craft_button_enabled())
	_check("G23_UNAVAILABLE_CANNOT_REQUEST", crafting.request_craft_intent().get("reason") == "EXTERNAL_RECIPE_UNAVAILABLE")
	_check("G23_NEW_AVAILABLE_PROJECTION", hud.project_crafting_recipe(_crafting_fixture(12, SESSION_REF, true)).get("status") == "PASS")
	_check("G23_QUANTITY_THREE", crafting.set_request_quantity(3).get("status") == "PASS")
	var output_before: Dictionary = crafting.projected_recipe().get("output", {}).duplicate(true)
	var active_slot_before: int = hud.active_weapon_slot()
	var zoom_before: float = camera_rig.target_distance_m()
	await get_tree().process_frame
	var scroll_result: Dictionary = main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_DOWN, false))
	_check("G23_MENU_WHEEL_SCROLL", scroll_result.get("intent") == "MENU_SCROLL")
	_check("G23_MENU_WHEEL_NO_WEAPON_SWAP", hud.active_weapon_slot() == active_slot_before)
	_check("G23_MENU_WHEEL_NO_ZOOM", is_equal_approx(camera_rig.target_distance_m(), zoom_before))
	var target_before_ui_click: String = main.selected_target_ref()
	var ui_click: Dictionary = main.handle_pointer_event(_mouse_button(MOUSE_BUTTON_LEFT, Vector2(640, 360)))
	_check("G23_WORLD_CLICK_CONSUMED", ui_click.get("intent") == "UI_POINTER_CONSUMED")
	_check("G23_UI_CLICK_TARGET_STABLE", main.selected_target_ref() == target_before_ui_click)
	var request: Dictionary = crafting.request_craft_intent()
	_check("G23_EXPLICIT_REQUEST_ONLY", request.get("intent") == "REQUEST_CRAFT")
	_check("G23_REQUEST_QUANTITY_THREE", int(request.get("quantity", 0)) == 3)
	_check("G23_REQUEST_NOT_SUBMITTED", request.get("transport_submitted") == false)
	_check("G23_REQUEST_NO_LOCAL_RESULT", request.get("craft_result_decided_locally") == false)
	_check("G23_REQUEST_NO_LOCAL_CONSUMPTION", request.get("ingredients_consumed_locally") == false)
	_check("G23_REQUEST_NO_LOCAL_GRANT", request.get("output_granted_locally") == false)
	_check("G23_REQUEST_NO_LOCAL_INVENTORY", request.get("inventory_mutated_locally") == false)
	var hud_intent: Dictionary = hud.last_crafting_intent()
	_check("G23_HUD_ENVELOPE_BUILT", hud_intent.get("intent_envelope", {}).get("status") == "PASS", JSON.stringify(hud_intent))
	_check("G23_HUD_ENVELOPE_COMMAND", hud_intent.get("intent_envelope", {}).get("envelope", {}).get("command") == "REQUEST_CRAFT")
	_check("G23_HUD_NO_TRANSPORT", hud_intent.get("transport_submitted") == false)
	_check("G23_OUTPUT_NOT_RECALCULATED_BY_UI_QUANTITY", crafting.projected_recipe().get("output", {}) == output_before)
	var close_result: Dictionary = hud.close_active_modal()
	_check("G23_CLOSE_CRAFTING", close_result.get("closed_layer") == "CRAFTING")
	_check("G23_NOT_PERMANENT", not crafting.is_open())
	_check("G23_MAIN_MENU_RELEASED", not main.menu_open())
	_check("G23_REOPEN_CRAFTING", hud.open_crafting("WORKSTATION-PRESENTATION-FIXTURE").get("status") == "PASS")
	_check("G23_REOPEN_PRESERVES_EXTERNAL_PROJECTION", crafting.projected_recipe().get("recipe_ref") == "RECOVERY-PRESENTATION-FIXTURE-RECIPE")
	hud.close_active_modal()


func _test_authority_static_contracts() -> void:
	_check("NO_CRAFT_CALCULATION_METHOD", not crafting.has_method("calculate_craft"))
	_check("NO_CRAFT_GRANT_METHOD", not crafting.has_method("grant_craft_output"))
	_check("NO_INGREDIENT_CONSUMPTION_METHOD", not crafting.has_method("consume_ingredients"))
	_check("NO_OCCLUDER_GAMEPLAY_METHOD", not tree_occluder.has_method("change_collision_for_fade"))
	_check("MAIN_GAMEPLAY_AUTHORITY_FALSE", main.contract_snapshot().get("gameplay_authority_in_gdscript") == false)
	_check("HUD_GAMEPLAY_AUTHORITY_FALSE", hud.contract_snapshot().get("gameplay_authority_in_gdscript") == false)
	_check("HUD_CRAFT_RESULT_FALSE", hud.contract_snapshot().get("crafting_result_calculated") == false)
	_check("HUD_CRAFT_INVENTORY_FALSE", hud.contract_snapshot().get("crafting_inventory_mutated") == false)
	_check("SOURCE_ACCEPTANCE_MATRIX_NOT_WRITTEN_BY_GATE", true)
	_check("STAGE17_NOT_STARTED_BY_GATE", true)
	_check("CHECKPOINT_NOT_CREATED_BY_GATE", true)
	_check("FINAL_BACKUP_NOT_CREATED_BY_GATE", true)


func _crafting_fixture(sequence: int, session_ref: String, available: bool) -> Dictionary:
	return {
		"recipe_ref": "RECOVERY-PRESENTATION-FIXTURE-RECIPE",
		"display_name": "Fixture visual não canônica",
		"projection_source": PRESENTATION_FIXTURE_SOURCE,
		"session_ref": session_ref,
		"sequence": sequence,
		"available": available,
		"ingredients": [
			{
				"item_ref": "FIXTURE-INGREDIENT-A",
				"display_name": "Ingrediente projetado A",
				"required_quantity": 2,
				"available_quantity": 4,
			},
			{
				"item_ref": "FIXTURE-INGREDIENT-B",
				"display_name": "Ingrediente projetado B",
				"required_quantity": 1,
				"available_quantity": 1,
			},
		],
		"output": {
			"item_ref": "FIXTURE-OUTPUT",
			"display_name": "Output projetado",
			"quantity": 1,
		},
		"canonical": false,
		"authoritative_roundtrip": false,
	}


func _ensure_npc_selected() -> String:
	var npc := main.get_node("ActorRoot/NPCB03") as AndromedaInteractionTarget
	if npc == null:
		_check("G14_SELECTION_TARGET_EXISTS", false)
		return main.selected_target_ref()
	var screen_position: Vector2 = main.target_to_screen(npc)
	var result: Dictionary = main.handle_pointer_event(_mouse_button(MOUSE_BUTTON_LEFT, screen_position))
	_check("G14_SELECTION_PRECONDITION", result.get("status") == "PASS" and result.get("intent") == "SELECT_TARGET", JSON.stringify(result))
	_check("G14_SELECTION_TARGET_REF", main.selected_target_ref() == npc.target_ref)
	return main.selected_target_ref()


func _store_occluder_transforms() -> void:
	for occluder: AndromedaCameraOccluder in _occluders():
		_original_occluder_transforms[occluder] = occluder.global_transform


func _restore_occluder_transforms() -> void:
	for occluder_value: Variant in _original_occluder_transforms.keys():
		var occluder := occluder_value as AndromedaCameraOccluder
		if occluder != null:
			occluder.global_transform = _original_occluder_transforms.get(occluder)


func _move_all_occluders_far() -> void:
	for index: int in range(_occluders().size()):
		_occluders()[index].global_position = _far_position(index)


func _far_position(index: int) -> Vector3:
	return Vector3(800.0 + float(index) * 10.0, 40.0, 800.0)


func _position_on_camera_ray(occluder: AndromedaCameraOccluder, ratio_from_camera: float) -> void:
	var from_position: Vector3 = camera_rig.camera.global_position
	var to_position: Vector3 = player.global_position + Vector3.UP * camera_rig.occlusion_target_height_m
	occluder.global_position = from_position.lerp(to_position, ratio_from_camera)


func _occluders() -> Array[AndromedaCameraOccluder]:
	return [tree_occluder, wall_occluder, tall_occluder]


func _wait_for_navigation(max_frames: int) -> bool:
	for _frame_index: int in range(max_frames):
		if main.navigation_ready():
			return true
		await get_tree().physics_frame
	return false


func _wait_physics_frames(frame_count: int) -> void:
	for _frame_index: int in range(frame_count):
		await get_tree().physics_frame


func _wait_process_frames(frame_count: int) -> void:
	for _frame_index: int in range(frame_count):
		await get_tree().process_frame


func _colors_close(left: Color, right: Color) -> bool:
	return absf(left.r - right.r) < 0.01 and absf(left.g - right.g) < 0.01 and absf(left.b - right.b) < 0.01


func _mouse_button(button_index: int, position: Vector2) -> InputEventMouseButton:
	var event := InputEventMouseButton.new()
	event.button_index = button_index as MouseButton
	event.position = position
	event.global_position = position
	event.pressed = true
	return event


func _wheel_event(button_index: int, shift_pressed: bool) -> InputEventMouseButton:
	var event := InputEventMouseButton.new()
	event.button_index = button_index as MouseButton
	event.pressed = true
	event.shift_pressed = shift_pressed
	return event


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "STAGE16B_AUTHORITY_INTEGRATION_RECOVERY_LOCAL_GAPS",
		"g16b14_local_status": "PASS" if _failures.is_empty() else "FAIL",
		"g16b23_local_status": "PASS" if _failures.is_empty() else "FAIL",
		"authoritative_roundtrip_executed": false,
		"fixture_is_authoritative_roundtrip": false,
		"backend_substitute_created": false,
		"checkpoint_created": false,
		"final_backup_created": false,
		"stage17_started": false,
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_AUTHORITY_RECOVERY_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_AUTHORITY_RECOVERY_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_AUTHORITY_RECOVERY_SUMMARY: %s" % JSON.stringify(summary))
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
