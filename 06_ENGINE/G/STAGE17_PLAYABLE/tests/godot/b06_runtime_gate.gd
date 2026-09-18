extends Node

class WorldTickProbe:
	extends Node
	var process_ticks: int = 0
	var physics_ticks: int = 0

	func _process(_delta: float) -> void:
		process_ticks += 1

	func _physics_process(_delta: float) -> void:
		physics_ticks += 1


var _checks: int = 0
var _failures: Array[String] = []

@onready var main: AndromedaMainRuntime = $AndromedaARPG
@onready var player: AndromedaPlayerController = $AndromedaARPG/ActorRoot/Player
@onready var camera_rig: AndromedaIsometricCameraRig = $AndromedaARPG/IsometricCameraRig
@onready var hud: AndromedaHUDController = $AndromedaARPG/UILayer/MinimalHUD
@onready var enemy_common: AndromedaInteractionTarget = $AndromedaARPG/ActorRoot/EnemyB03
@onready var enemy_alpha: AndromedaInteractionTarget = $AndromedaARPG/ActorRoot/EnemyB06Alpha

var _common_original_position: Vector3
var _alpha_original_position: Vector3
var _player_original_position: Vector3
var _common_original_rotation: Vector3
var _alpha_original_rotation: Vector3


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
	var bind_result: Dictionary = session.bind_session("B06-GATE-SESSION")
	_check("SESSION_BOUND_ENVELOPES_ONLY", bind_result.get("status") == "PASS", JSON.stringify(bind_result))
	var project_label: String = str(ProjectSettings.get_setting("application/config/name"))
	_check("PROJECT_LABEL_B06_THROUGH_B11", project_label in ["Andromeda ARPG Stage16B B06", "Andromeda ARPG Stage16B B07", "Andromeda ARPG Stage16B B08", "Andromeda ARPG Stage16B B09", "Andromeda ARPG Stage16B B10", "Andromeda ARPG Stage16B B11"], project_label)
	_check("MAIN_SCENE_PRESERVED", str(ProjectSettings.get_setting("application/run/main_scene")) == "res://scenes/Main.tscn")
	_check("BACKEND_URL_UNCHANGED", bridge.server_url() == "http://127.0.0.1:8000")

	_common_original_position = enemy_common.global_position
	_alpha_original_position = enemy_alpha.global_position
	_player_original_position = player.global_position
	_common_original_rotation = enemy_common.rotation
	_alpha_original_rotation = enemy_alpha.rotation
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	enemy_common.global_position = Vector3(-3.5, 0.0, -4.0)
	enemy_alpha.global_position = Vector3(3.0, 0.0, -4.0)
	camera_rig.set_follow_target(player, true)
	await _wait_physics_frames(5)

	_test_architecture_and_authority()
	_test_player_vitals_and_stamina()
	await _test_enemy_bars()
	_test_snapshot_projection()
	await _test_feedback_and_local_freeze()
	await _test_reduced_motion_and_priority()
	await _test_targeting_camera_and_click_to_move()
	_restore_gate_state()
	await _finish()


func _test_architecture_and_authority() -> void:
	var main_contract: Dictionary = main.contract_snapshot()
	var hud_contract: Dictionary = hud.contract_snapshot()
	var feedback_contract: Dictionary = hud.combat_feedback.contract_snapshot()
	_check("MAIN_NO_GDSCRIPT_GAMEPLAY_AUTHORITY", main_contract.get("gameplay_authority_in_gdscript") == false)
	_check("MAIN_NO_BACKEND_SUBSTITUTE", main_contract.get("backend_substitute") == false)
	_check("MAIN_COMBAT_PRESENTATION_PRESENT", main_contract.get("combat_presentation_present") == true)
	_check("MAIN_COMBAT_OUTCOME_NOT_CALCULATED", main_contract.get("combat_outcome_calculated_in_gdscript") == false)
	_check("MAIN_COMBAT_SNAPSHOT_NOT_MUTATED", main_contract.get("combat_snapshot_mutated_in_gdscript") == false)
	_check("MAIN_GLOBAL_HITSTOP_FALSE", main_contract.get("global_hit_stop") == false)
	_check("HUD_ROOT_PRESENT", main.hud == hud)
	_check("HUD_MOUSE_FILTER_IGNORE", hud.mouse_filter == Control.MOUSE_FILTER_IGNORE)
	_check("HUD_COMBAT_OUTCOME_NOT_CALCULATED", hud_contract.get("combat_outcome_calculated") == false)
	_check("HUD_COMBAT_SNAPSHOT_NOT_MUTATED", hud_contract.get("combat_snapshot_mutated") == false)
	_check("HUD_GAMEPLAY_AUTHORITY_FALSE", hud_contract.get("gameplay_authority_in_gdscript") == false)
	_check("HUD_FINAL_ART_FALSE", hud_contract.get("final_art") == false)
	_check("HUD_UI_FAMILY_PRESERVED", hud_contract.get("ui_family") == "WHITE_OFF_WHITE_ROUNDED_CLEAN_CONSOLE")
	_check("HUD_PRIMARY_TEXT_PRESERVED", hud_contract.get("primary_text_hex") == "#6B6B6B")
	_check("HUD_IMPORTANT_TEXT_PRESERVED", hud_contract.get("important_text_hex") == "#D9A15F")
	_check("PLAYER_COMBAT_VITALS_NODE", hud.has_node("PlayerCombatVitals"))
	_check("ENEMY_COMBAT_BAR_LAYER_NODE", hud.has_node("WorldUIRoot/EnemyCombatBarLayer"))
	_check("COMBAT_FEEDBACK_NODE", hud.has_node("CombatFeedbackPresenter"))
	_check("COMBAT_ACTOR_COUNT_TWO", hud.registered_combat_actor_count() == 2, str(hud.registered_combat_actor_count()))
	_check("ENEMY_BAR_COUNT_TWO", hud.enemy_bar_count() == 2, str(hud.enemy_bar_count()))
	_check("COMMON_ENEMY_REUSES_B03_SCENE", enemy_common.has_node("HealthBarAnchor") and enemy_common.has_node("VisualRoot"))
	_check("ALPHA_ENEMY_REUSES_B03_SCENE", enemy_alpha.has_node("HealthBarAnchor") and enemy_alpha.has_node("VisualRoot"))
	_check("ALPHA_METADATA_ONLY", str(enemy_alpha.get_meta("combat_rank", "")) == "ALPHA")
	_check("HIT_HURT_LAYER_PRESERVED", main.collision_layer_contract().get("HIT_HURT_SENSOR") == 512)
	_check("PLAYER_HURTBOX_LAYER_PRESERVED", int(player.get_node("Hurtbox").collision_layer) == 512)
	_check("COMMON_HURTBOX_LAYER_PRESERVED", int(enemy_common.get_node("Hurtbox").collision_layer) == 512)
	_check("FEEDBACK_NORMAL_28", feedback_contract.get("normal_hit_stop_ms_candidate") == 28)
	_check("FEEDBACK_STRONG_42", feedback_contract.get("strong_hit_stop_ms_candidate") == 42)
	_check("FEEDBACK_CRITICAL_58", feedback_contract.get("critical_hit_stop_ms_candidate") == 58)
	_check("FEEDBACK_CAMERA_CAP_018", is_equal_approx(float(feedback_contract.get("camera_impulse_max_candidate_m")), 0.18))
	_check("FEEDBACK_MAX_VISIBLE_THREE", feedback_contract.get("max_visible_feedback") == 3)
	_check("FEEDBACK_GLOBAL_HITSTOP_FALSE", feedback_contract.get("global_hit_stop") == false)
	_check("FEEDBACK_LOCAL_VISUAL_ONLY", feedback_contract.get("local_visual_root_only") == true)
	_check("FEEDBACK_DAMAGE_AUTHORITY_FALSE", feedback_contract.get("damage_authority") == false)
	_check("FEEDBACK_CRITICAL_AUTHORITY_FALSE", feedback_contract.get("critical_authority") == false)
	_check("FEEDBACK_DEATH_AUTHORITY_FALSE", feedback_contract.get("death_authority") == false)
	_check("FEEDBACK_COOLDOWN_AUTHORITY_FALSE", feedback_contract.get("cooldown_authority") == false)
	_check("FEEDBACK_FINAL_AUDIO_FALSE", feedback_contract.get("final_audio_assets") == false)
	var semantic_tokens: Array = feedback_contract.get("semantic_tokens", [])
	for token: String in ["COMBAT_HIT", "COMBAT_CRITICAL_HIT", "PLAYER_HURT", "PLAYER_SHIELD_HIT", "TARGET_DEFEATED", "INTERACTION_BLOCKED"]:
		_check("SEMANTIC_TOKEN_%s" % token, semantic_tokens.has(token), str(semantic_tokens))


func _test_player_vitals_and_stamina() -> void:
	var vitals: AndromedaPlayerCombatVitals = hud.player_combat_vitals
	var contract: Dictionary = vitals.contract_snapshot()
	_check("PLAYER_VITALS_SMALL_WIDTH", vitals.size.x <= 240.0, str(vitals.size))
	_check("PLAYER_VITALS_SMALL_HEIGHT", vitals.size.y <= 90.0, str(vitals.size))
	_check("PLAYER_VITALS_NO_LARGE_PERMANENT_BAR", contract.get("permanent_large_bar") == false)
	_check("PLAYER_VITALS_HAS_HP", contract.get("hp_channel") == true)
	_check("PLAYER_VITALS_HAS_PROTECTION", contract.get("protection_channel") == true)
	_check("PLAYER_VITALS_DOES_NOT_REPLACE_STAMINA", contract.get("stamina_channel") == false)
	_check("PLAYER_VITALS_DAMAGE_CALC_FALSE", contract.get("damage_calculation") == false)
	_check("PLAYER_VITALS_PROTECTION_CALC_FALSE", contract.get("protection_consumption_calculation") == false)
	var idle_result: Dictionary = hud.project_player_combat_vitals(1.0, 0.0, false, "LOCAL_GATE_PLACEHOLDER")
	_check("PLAYER_VITALS_IDLE_PASS", idle_result.get("status") == "PASS", JSON.stringify(idle_result))
	_check("PLAYER_HP_FULL_PROJECTED", is_equal_approx(vitals.hp_fraction(), 1.0))
	_check("PLAYER_PROTECTION_ZERO_PROJECTED", is_equal_approx(vitals.protection_fraction(), 0.0))
	_check("PLAYER_VITALS_IDLE_ALPHA", is_equal_approx(vitals.presentation_alpha(), 0.22), str(vitals.presentation_alpha()))
	_check("PLAYER_PROTECTION_IDLE_HIDDEN", not vitals.protection_channel_visible())
	var active_result: Dictionary = hud.project_player_combat_vitals(0.73, 0.48, true, "LOCAL_GATE_PLACEHOLDER")
	_check("PLAYER_VITALS_ACTIVE_PASS", active_result.get("status") == "PASS", JSON.stringify(active_result))
	_check("PLAYER_HP_PROJECTED_073", is_equal_approx(vitals.hp_fraction(), 0.73))
	_check("PLAYER_PROTECTION_PROJECTED_048", is_equal_approx(vitals.protection_fraction(), 0.48))
	_check("PLAYER_VITALS_ACTIVE_ALPHA", is_equal_approx(vitals.presentation_alpha(), 0.92), str(vitals.presentation_alpha()))
	_check("PLAYER_PROTECTION_ACTIVE_VISIBLE", vitals.protection_channel_visible())
	_check("PLAYER_VITALS_SOURCE_MARKED_PLACEHOLDER", vitals.projection_source() == "LOCAL_GATE_PLACEHOLDER")
	var separate_result: Dictionary = hud.project_player_combat_vitals(0.51, 0.23, true, "LOCAL_GATE_PLACEHOLDER")
	_check("PLAYER_SEPARATE_CHANNEL_UPDATE_PASS", separate_result.get("status") == "PASS")
	_check("PLAYER_HP_SEPARATE_051", is_equal_approx(vitals.hp_fraction(), 0.51))
	_check("PLAYER_PROTECTION_SEPARATE_023", is_equal_approx(vitals.protection_fraction(), 0.23))
	_check("PLAYER_BAD_HP_REJECTED", hud.project_player_combat_vitals(-0.1, 0.2, true, "LOCAL_GATE_PLACEHOLDER").get("status") == "REJECTED")
	_check("PLAYER_BAD_PROTECTION_REJECTED", hud.project_player_combat_vitals(0.8, 1.1, true, "LOCAL_GATE_PLACEHOLDER").get("status") == "REJECTED")
	_check("PLAYER_SOURCE_REQUIRED", hud.project_player_combat_vitals(0.8, 0.2, true, "").get("status") == "REJECTED")
	var stamina_consuming: Dictionary = hud.project_stamina(0.61, "CONSUMING", "LOCAL_GATE_PLACEHOLDER")
	_check("B05_STAMINA_CONSUMING_PRESERVED", stamina_consuming.get("status") == "PASS" and hud.stamina_ring.visible)
	_check("B05_STAMINA_FRACTION_PRESERVED", is_equal_approx(hud.stamina_ring.stamina_fraction(), 0.61))
	_check("B05_STAMINA_RADIAL_PRESERVED", hud.stamina_ring.contract_snapshot().get("shape") == "CIRCLE_RADIAL")
	_check("B05_STAMINA_NOT_HORIZONTAL", hud.stamina_ring.contract_snapshot().get("horizontal_bar") == false)
	hud.project_stamina(1.0, "INACTIVE", "LOCAL_GATE_PLACEHOLDER")
	_check("B05_STAMINA_FULL_IDLE_HIDDEN", not hud.stamina_ring.visible)


func _test_enemy_bars() -> void:
	var common_bar: AndromedaEnemyCombatBar = hud.enemy_bar_for_ref(enemy_common.target_ref)
	var alpha_bar: AndromedaEnemyCombatBar = hud.enemy_bar_for_ref(enemy_alpha.target_ref)
	_check("COMMON_BAR_FOUND", common_bar != null)
	_check("ALPHA_BAR_FOUND", alpha_bar != null)
	if common_bar == null or alpha_bar == null:
		return
	_check("BARS_ARE_DISTINCT", common_bar != alpha_bar)
	_check("COMMON_BAR_TARGET_REF", common_bar.target_ref() == enemy_common.target_ref)
	_check("ALPHA_BAR_TARGET_REF", alpha_bar.target_ref() == enemy_alpha.target_ref)
	_check("COMMON_BAR_ACTOR_BINDING", common_bar.actor() == enemy_common)
	_check("ALPHA_BAR_ACTOR_BINDING", alpha_bar.actor() == enemy_alpha)
	_check("COMMON_NOT_ALPHA", not common_bar.is_alpha_rank())
	_check("ALPHA_RANK_TRUE", alpha_bar.is_alpha_rank())
	_check("COMMON_BAR_HIDDEN_NOT_ENGAGED", not common_bar.visible)
	_check("ALPHA_BAR_HIDDEN_NOT_ENGAGED", not alpha_bar.visible)
	var common_result: Dictionary = hud.project_enemy_combat_vitals(enemy_common.target_ref, 0.72, 0.0, true, "LOCAL_GATE_PLACEHOLDER")
	var alpha_result: Dictionary = hud.project_enemy_combat_vitals(enemy_alpha.target_ref, 0.88, 0.63, true, "LOCAL_GATE_PLACEHOLDER")
	await _wait_process_frames(2)
	_check("COMMON_HP_PROJECTION_PASS", common_result.get("status") == "PASS", JSON.stringify(common_result))
	_check("ALPHA_HP_SHIELD_PROJECTION_PASS", alpha_result.get("status") == "PASS", JSON.stringify(alpha_result))
	_check("COMMON_BAR_VISIBLE_ENGAGED", common_bar.visible)
	_check("ALPHA_BAR_VISIBLE_ENGAGED", alpha_bar.visible)
	_check("COMMON_HP_072", is_equal_approx(common_bar.hp_fraction(), 0.72))
	_check("COMMON_SHIELD_ZERO", is_equal_approx(common_bar.shield_fraction(), 0.0))
	_check("ALPHA_HP_088", is_equal_approx(alpha_bar.hp_fraction(), 0.88))
	_check("ALPHA_SHIELD_063", is_equal_approx(alpha_bar.shield_fraction(), 0.63))
	_check("COMMON_SOURCE_PLACEHOLDER", common_bar.projection_source() == "LOCAL_GATE_PLACEHOLDER")
	_check("ALPHA_SOURCE_PLACEHOLDER", alpha_bar.projection_source() == "LOCAL_GATE_PLACEHOLDER")
	_check("COMMON_SHIELD_NODE_HIDDEN", not common_bar.get_node("ShieldBar").visible)
	_check("ALPHA_SHIELD_NODE_VISIBLE", alpha_bar.get_node("ShieldBar").visible)
	_check("ALPHA_SHIELD_SMALLER_THAN_HP", alpha_bar.shield_height_px() < alpha_bar.hp_height_px(), "%f/%f" % [alpha_bar.shield_height_px(), alpha_bar.hp_height_px()])
	_check("COMMON_BAR_STRAIGHT", is_zero_approx(common_bar.rotation))
	_check("ALPHA_BAR_STRAIGHT", is_zero_approx(alpha_bar.rotation))
	_check("COMMON_BAR_FILL_NOT_BLACK", _color_not_black(common_bar.hp_fill_color()), str(common_bar.hp_fill_color()))
	_check("COMMON_BAR_TRACK_NOT_BLACK", _color_not_black(common_bar.track_color()), str(common_bar.track_color()))
	_check("ALPHA_BAR_FILL_NOT_BLACK", _color_not_black(alpha_bar.hp_fill_color()), str(alpha_bar.hp_fill_color()))
	var common_expected_bottom: Vector2 = common_bar.anchor_screen_position() + Vector2(0.0, -8.0)
	var common_actual_bottom: Vector2 = common_bar.position + common_bar.size * Vector2(0.5, 1.0)
	_check("COMMON_BAR_ABOVE_HEAD_ALIGNMENT", common_actual_bottom.distance_to(common_expected_bottom) < 1.0, "%s/%s" % [common_actual_bottom, common_expected_bottom])
	var anchor_before: Vector2 = common_bar.anchor_screen_position()
	enemy_common.global_position.x += 1.25
	await _wait_process_frames(3)
	_check("COMMON_BAR_FOLLOWS_MOVING_TARGET", common_bar.anchor_screen_position().distance_to(anchor_before) > 1.0, "%s/%s" % [anchor_before, common_bar.anchor_screen_position()])
	common_expected_bottom = common_bar.anchor_screen_position() + Vector2(0.0, -8.0)
	common_actual_bottom = common_bar.position + common_bar.size * Vector2(0.5, 1.0)
	_check("COMMON_BAR_REMAINS_ANCHORED_AFTER_MOVE", common_actual_bottom.distance_to(common_expected_bottom) < 1.0)
	enemy_common.rotation_degrees.y = 137.0
	enemy_alpha.rotation_degrees.y = -93.0
	await _wait_process_frames(2)
	_check("COMMON_BAR_DOES_NOT_ROTATE_WITH_ACTOR", is_zero_approx(common_bar.rotation))
	_check("ALPHA_BAR_DOES_NOT_ROTATE_WITH_ACTOR", is_zero_approx(alpha_bar.rotation))
	var hp_before_shield_change: float = alpha_bar.hp_fraction()
	var shield_separate: Dictionary = hud.project_enemy_combat_vitals(enemy_alpha.target_ref, hp_before_shield_change, 0.19, true, "LOCAL_GATE_PLACEHOLDER")
	_check("ALPHA_SHIELD_SEPARATE_UPDATE_PASS", shield_separate.get("status") == "PASS")
	_check("ALPHA_HP_UNCHANGED_ON_SHIELD_PROJECTION", is_equal_approx(alpha_bar.hp_fraction(), hp_before_shield_change))
	_check("ALPHA_SHIELD_REDUCED_SEPARATELY", is_equal_approx(alpha_bar.shield_fraction(), 0.19))
	var hp_reduced: Dictionary = hud.project_enemy_combat_vitals(enemy_common.target_ref, 0.31, 0.0, true, "LOCAL_GATE_PLACEHOLDER")
	_check("COMMON_HP_VISUAL_REDUCTION_PASS", hp_reduced.get("status") == "PASS")
	_check("COMMON_HP_VISUAL_REDUCED_031", is_equal_approx(common_bar.hp_fraction(), 0.31))
	_check("COMMON_SHIELD_CHANNEL_REJECTED", hud.project_enemy_combat_vitals(enemy_common.target_ref, 0.31, 0.2, true, "LOCAL_GATE_PLACEHOLDER").get("status") == "REJECTED")
	_check("UNKNOWN_ENEMY_BAR_REJECTED", hud.project_enemy_combat_vitals("ENEMY-NOT-BOUND", 1.0, 0.0, true, "LOCAL_GATE_PLACEHOLDER").get("status") == "REJECTED")
	var immutable_result: Dictionary = common_bar.bind_projection(enemy_alpha, camera_rig.camera, enemy_alpha.target_ref, true)
	_check("BAR_TARGET_REF_BINDING_IMMUTABLE", immutable_result.get("status") == "REJECTED" and common_bar.target_ref() == enemy_common.target_ref)
	hud.project_enemy_combat_vitals(enemy_common.target_ref, 0.31, 0.0, false, "LOCAL_GATE_PLACEHOLDER")
	await _wait_process_frames(2)
	_check("COMMON_BAR_HIDES_AFTER_DISENGAGE", not common_bar.visible)
	hud.project_enemy_combat_vitals(enemy_common.target_ref, 0.31, 0.0, true, "LOCAL_GATE_PLACEHOLDER")
	await _wait_process_frames(2)
	_check("COMMON_BAR_REAPPEARS_ON_ENGAGE", common_bar.visible)
	var common_pre_overlap_ref: String = common_bar.target_ref()
	var alpha_pre_overlap_ref: String = alpha_bar.target_ref()
	var alpha_token_before: String = alpha_bar.last_feedback_token()
	enemy_alpha.global_position = enemy_common.global_position
	await _wait_process_frames(3)
	_check("OVERLAP_BARS_KEEP_COMMON_REF", common_bar.target_ref() == common_pre_overlap_ref)
	_check("OVERLAP_BARS_KEEP_ALPHA_REF", alpha_bar.target_ref() == alpha_pre_overlap_ref)
	_check("OVERLAP_BARS_REMAIN_DISTINCT", common_bar.get_instance_id() != alpha_bar.get_instance_id())
	var overlap_feedback: Dictionary = hud.present_combat_event({
		"token": "COMBAT_HIT",
		"target_ref": enemy_common.target_ref,
		"confirmed_externally": true,
	})
	_check("OVERLAP_FEEDBACK_COMMON_PASS", overlap_feedback.get("status") == "PASS", JSON.stringify(overlap_feedback))
	_check("OVERLAP_FEEDBACK_STAYS_COMMON_BAR", common_bar.last_feedback_token() == "COMBAT_HIT")
	_check("OVERLAP_FEEDBACK_DOES_NOT_SWAP_ALPHA_BAR", alpha_bar.last_feedback_token() == alpha_token_before)
	enemy_alpha.global_position = Vector3(3.0, 0.0, -4.0)
	enemy_common.global_position = Vector3(-3.5, 0.0, -4.0)
	enemy_common.rotation = Vector3.ZERO
	enemy_alpha.rotation = Vector3.ZERO
	hud.combat_feedback.clear_presentation_feedback()


func _test_snapshot_projection() -> void:
	var snapshot := {
		"combat_presentation": {
			"player": {"hp_fraction": 0.66, "protection_fraction": 0.37, "relevant": true},
			"targets": [
				{"target_ref": enemy_common.target_ref, "hp_fraction": 0.58, "shield_fraction": 0.0, "engaged": true},
				{"target_ref": enemy_alpha.target_ref, "hp_fraction": 0.81, "shield_fraction": 0.44, "engaged": true},
			],
		},
	}
	var snapshot_before: String = JSON.stringify(snapshot)
	var result: Dictionary = hud.apply_presentation_snapshot(snapshot)
	var channels: Array = result.get("projected_channels", [])
	var common_bar: AndromedaEnemyCombatBar = hud.enemy_bar_for_ref(enemy_common.target_ref)
	var alpha_bar: AndromedaEnemyCombatBar = hud.enemy_bar_for_ref(enemy_alpha.target_ref)
	_check("COMBAT_SNAPSHOT_PROJECTION_PASS", result.get("status") == "PASS", JSON.stringify(result))
	_check("COMBAT_SNAPSHOT_PLAYER_CHANNEL", channels.has("PLAYER_COMBAT_VITALS"), str(channels))
	_check("COMBAT_SNAPSHOT_COMMON_CHANNEL", channels.has("ENEMY_COMBAT_VITALS:%s" % enemy_common.target_ref), str(channels))
	_check("COMBAT_SNAPSHOT_ALPHA_CHANNEL", channels.has("ENEMY_COMBAT_VITALS:%s" % enemy_alpha.target_ref), str(channels))
	_check("COMBAT_SNAPSHOT_PLAYER_HP", is_equal_approx(hud.player_combat_vitals.hp_fraction(), 0.66))
	_check("COMBAT_SNAPSHOT_PLAYER_PROTECTION", is_equal_approx(hud.player_combat_vitals.protection_fraction(), 0.37))
	_check("COMBAT_SNAPSHOT_COMMON_HP", common_bar != null and is_equal_approx(common_bar.hp_fraction(), 0.58))
	_check("COMBAT_SNAPSHOT_ALPHA_HP", alpha_bar != null and is_equal_approx(alpha_bar.hp_fraction(), 0.81))
	_check("COMBAT_SNAPSHOT_ALPHA_SHIELD", alpha_bar != null and is_equal_approx(alpha_bar.shield_fraction(), 0.44))
	_check("COMBAT_SNAPSHOT_PLAYER_SOURCE", hud.player_combat_vitals.projection_source() == "AUTHORITATIVE_SNAPSHOT")
	_check("COMBAT_SNAPSHOT_COMMON_SOURCE", common_bar != null and common_bar.projection_source() == "AUTHORITATIVE_SNAPSHOT")
	_check("COMBAT_SNAPSHOT_ALPHA_SOURCE", alpha_bar != null and alpha_bar.projection_source() == "AUTHORITATIVE_SNAPSHOT")
	_check("COMBAT_SNAPSHOT_NOT_MUTATED", result.get("snapshot_mutated") == false and JSON.stringify(snapshot) == snapshot_before)


func _test_feedback_and_local_freeze() -> void:
	var feedback: AndromedaCombatFeedbackPresenter = hud.combat_feedback
	var common_bar: AndromedaEnemyCombatBar = hud.enemy_bar_for_ref(enemy_common.target_ref)
	feedback.clear_presentation_feedback()
	hud.set_reduced_motion(false)
	_check("UNCONFIRMED_HIT_REJECTED", hud.present_combat_event({"token": "COMBAT_HIT", "target_ref": enemy_common.target_ref}).get("status") == "REJECTED")
	_check("UNCONFIRMED_CRITICAL_REJECTED", hud.present_combat_event({"token": "COMBAT_CRITICAL_HIT", "target_ref": enemy_common.target_ref}).get("status") == "REJECTED")
	_check("UNCONFIRMED_DEFEAT_REJECTED", hud.present_combat_event({"token": "TARGET_DEFEATED", "target_ref": enemy_common.target_ref}).get("status") == "REJECTED")
	_check("UNKNOWN_TOKEN_REJECTED", hud.present_combat_event({"token": "DAMAGE_DECIDED_LOCALLY", "confirmed_externally": true}).get("status") == "REJECTED")
	_check("DAMAGE_FIELD_REJECTED", hud.present_combat_event({"token": "COMBAT_HIT", "target_ref": enemy_common.target_ref, "confirmed_externally": true, "damage": 99}).get("status") == "REJECTED")
	_check("CRITICAL_ROLL_FIELD_REJECTED", hud.present_combat_event({"token": "COMBAT_HIT", "target_ref": enemy_common.target_ref, "confirmed_externally": true, "critical_roll": 0.1}).get("status") == "REJECTED")
	_check("TARGET_REF_REQUIRED_FOR_HIT", hud.present_combat_event({"token": "COMBAT_HIT", "confirmed_externally": true}).get("status") == "REJECTED")

	var probe := WorldTickProbe.new()
	probe.name = "WorldTickProbe"
	add_child(probe)
	await _wait_process_frames(2)
	var world_process_before: int = probe.process_ticks
	var world_physics_frame_before: int = Engine.get_physics_frames()
	var hp_before_hit: float = common_bar.hp_fraction()
	var shield_before_hit: float = common_bar.shield_fraction()
	var target_visual: Node = enemy_common.get_node("VisualRoot")
	var target_root_mode_before: ProcessMode = enemy_common.process_mode
	var normal_result: Dictionary = hud.present_combat_event({
		"token": "COMBAT_HIT",
		"target_ref": enemy_common.target_ref,
		"confirmed_externally": true,
		"strength": "NORMAL",
	})
	_check("NORMAL_HIT_PRESENTATION_PASS", normal_result.get("status") == "PASS", JSON.stringify(normal_result))
	_check("NORMAL_HIT_FREEZE_28", normal_result.get("local_visual_freeze_ms") == 28)
	_check("NORMAL_HIT_IMPULSE_008", is_equal_approx(float(normal_result.get("camera_impulse_m")), 0.08))
	_check("NORMAL_HIT_PRIORITY_80", normal_result.get("priority") == 80)
	_check("NORMAL_HIT_SEMANTIC_TOKEN", normal_result.get("semantic_audio_token") == "COMBAT_HIT")
	_check("NORMAL_HIT_NO_FINAL_AUDIO", normal_result.get("final_audio_asset") == false)
	_check("NORMAL_HIT_NO_GLOBAL_PAUSE", normal_result.get("global_world_pause") == false and not get_tree().paused)
	_check("NORMAL_HIT_LOCAL_VISUAL_FROZEN", target_visual.process_mode == Node.PROCESS_MODE_DISABLED)
	_check("NORMAL_HIT_ACTOR_ROOT_NOT_FROZEN", enemy_common.process_mode == target_root_mode_before)
	_check("NORMAL_HIT_FEEDBACK_TRACKED", feedback.is_target_locally_frozen(enemy_common.target_ref))
	_check("NORMAL_HIT_BAR_TARGET_CORRECT", common_bar.last_feedback_token() == "COMBAT_HIT" and common_bar.target_ref() == enemy_common.target_ref)
	_check("NORMAL_HIT_HP_UNCHANGED", is_equal_approx(common_bar.hp_fraction(), hp_before_hit))
	_check("NORMAL_HIT_SHIELD_UNCHANGED", is_equal_approx(common_bar.shield_fraction(), shield_before_hit))
	await _wait_process_frames(1)
	_check("WORLD_PROCESS_CONTINUES_DURING_LOCAL_FREEZE", probe.process_ticks > world_process_before, "%d/%d" % [world_process_before, probe.process_ticks])
	await _wait_physics_frames(1)
	_check("WORLD_PHYSICS_CONTINUES_DURING_LOCAL_FREEZE", Engine.get_physics_frames() > world_physics_frame_before, "%d/%d" % [world_physics_frame_before, Engine.get_physics_frames()])
	await get_tree().create_timer(0.05).timeout
	_check("LOCAL_FREEZE_RESTORES_VISUAL_ROOT", target_visual.process_mode != Node.PROCESS_MODE_DISABLED)
	_check("LOCAL_FREEZE_TRACKER_CLEARS", not feedback.is_target_locally_frozen(enemy_common.target_ref))
	probe.queue_free()

	feedback.clear_presentation_feedback()
	var strong_result: Dictionary = hud.present_combat_event({
		"token": "COMBAT_HIT",
		"target_ref": enemy_common.target_ref,
		"confirmed_externally": true,
		"strength": "STRONG",
	})
	_check("STRONG_HIT_PRESENTATION_PASS", strong_result.get("status") == "PASS")
	_check("STRONG_HIT_FREEZE_42", strong_result.get("local_visual_freeze_ms") == 42)
	_check("STRONG_HIT_IMPULSE_013", is_equal_approx(float(strong_result.get("camera_impulse_m")), 0.13))
	_check("STRONG_HIT_LOCAL_ONLY", strong_result.get("local_animation_only") == true and strong_result.get("gameplay_result_changed") == false)
	await get_tree().create_timer(0.06).timeout

	feedback.clear_presentation_feedback()
	var critical_result: Dictionary = hud.present_combat_event({
		"token": "COMBAT_CRITICAL_HIT",
		"target_ref": enemy_common.target_ref,
		"confirmed_externally": true,
		"strength": "NORMAL",
	})
	_check("CRITICAL_PRESENTATION_PASS", critical_result.get("status") == "PASS")
	_check("CRITICAL_FREEZE_58", critical_result.get("local_visual_freeze_ms") == 58)
	_check("CRITICAL_IMPULSE_013", is_equal_approx(float(critical_result.get("camera_impulse_m")), 0.13))
	_check("CRITICAL_PRIORITY_85", critical_result.get("priority") == 85)
	_check("CRITICAL_NOT_DECIDED_CLIENT", critical_result.get("critical_decided") == false)
	_check("CRITICAL_BAR_TOKEN", common_bar.last_feedback_token() == "COMBAT_CRITICAL_HIT")
	await _wait_physics_frames(1)
	_check("CAMERA_IMPULSE_ACTIVE", camera_rig.presentation_impulse_active())
	_check("CAMERA_IMPULSE_OFFSET_NONZERO", camera_rig.current_presentation_offset_m().length() > 0.0, str(camera_rig.current_presentation_offset_m()))
	_check("CAMERA_IMPULSE_WITHIN_CAP", camera_rig.current_presentation_offset_m().length() <= 0.1801, str(camera_rig.current_presentation_offset_m().length()))
	await get_tree().create_timer(0.14).timeout
	_check("CAMERA_IMPULSE_RESTORES_ZERO", camera_rig.current_presentation_offset_m().length() < 0.0001, str(camera_rig.current_presentation_offset_m()))

	var max_impulse_result: Dictionary = hud.present_combat_event({
		"token": "COMBAT_CRITICAL_HIT",
		"target_ref": enemy_common.target_ref,
		"confirmed_externally": true,
		"strength": "STRONG",
	})
	_check("STRONG_CRITICAL_IMPULSE_MAX_018", is_equal_approx(float(max_impulse_result.get("camera_impulse_m")), 0.18), JSON.stringify(max_impulse_result))
	_check("CAMERA_REQUEST_OVER_CAP_CLAMPS", is_equal_approx(float(camera_rig.request_presentation_impulse(0.9).get("applied_impulse_m")), 0.18))
	_check("CAMERA_NEGATIVE_IMPULSE_REJECTED", camera_rig.request_presentation_impulse(-0.1).get("status") == "REJECTED")
	await get_tree().create_timer(0.14).timeout

	var player_hp_before: float = hud.player_combat_vitals.hp_fraction()
	var player_shield_before: float = hud.player_combat_vitals.protection_fraction()
	var player_hurt_result: Dictionary = hud.present_combat_event({
		"token": "PLAYER_HURT",
		"confirmed_externally": true,
	})
	_check("PLAYER_HURT_PRESENTATION_PASS", player_hurt_result.get("status") == "PASS")
	_check("PLAYER_HURT_PRIORITY_95", player_hurt_result.get("priority") == 95)
	_check("PLAYER_HURT_IMPULSE_008", is_equal_approx(float(player_hurt_result.get("camera_impulse_m")), 0.08))
	_check("PLAYER_HURT_NO_LOCAL_HITSTOP", player_hurt_result.get("local_visual_freeze_ms") == 0)
	_check("PLAYER_HURT_EDGE_FLASH", feedback.edge_flash_visible())
	_check("PLAYER_HURT_VITALS_TOKEN", hud.player_combat_vitals.last_feedback_token() == "PLAYER_HURT")
	_check("PLAYER_HURT_HP_UNCHANGED", is_equal_approx(hud.player_combat_vitals.hp_fraction(), player_hp_before))
	_check("PLAYER_HURT_PROTECTION_UNCHANGED", is_equal_approx(hud.player_combat_vitals.protection_fraction(), player_shield_before))
	var critical_received_result: Dictionary = hud.present_combat_event({
		"token": "PLAYER_HURT",
		"confirmed_externally": true,
		"critical_received": true,
	})
	_check("PLAYER_CRITICAL_DAMAGE_PRIORITY_100", critical_received_result.get("priority") == 100)
	_check("PLAYER_CRITICAL_DAMAGE_IMPULSE_014", is_equal_approx(float(critical_received_result.get("camera_impulse_m")), 0.14))
	var shield_hit_result: Dictionary = hud.present_combat_event({
		"token": "PLAYER_SHIELD_HIT",
		"confirmed_externally": true,
	})
	_check("PLAYER_SHIELD_HIT_PASS", shield_hit_result.get("status") == "PASS")
	_check("PLAYER_SHIELD_HIT_PRIORITY_95", shield_hit_result.get("priority") == 95)
	_check("PLAYER_SHIELD_HIT_TOKEN", hud.player_combat_vitals.last_feedback_token() == "PLAYER_SHIELD_HIT")
	_check("PLAYER_SHIELD_HIT_HP_UNCHANGED", is_equal_approx(hud.player_combat_vitals.hp_fraction(), player_hp_before))
	_check("PLAYER_SHIELD_HIT_PROTECTION_UNCHANGED", is_equal_approx(hud.player_combat_vitals.protection_fraction(), player_shield_before))

	var actor_still_parented: Node = enemy_common.get_parent()
	var hp_before_defeat: float = common_bar.hp_fraction()
	var defeat_result: Dictionary = hud.present_combat_event({
		"token": "TARGET_DEFEATED",
		"target_ref": enemy_common.target_ref,
		"confirmed_externally": true,
	})
	_check("DEFEAT_PRESENTATION_PASS", defeat_result.get("status") == "PASS")
	_check("DEFEAT_EXTERNALLY_CONFIRMED_TOKEN", defeat_result.get("semantic_audio_token") == "TARGET_DEFEATED")
	_check("DEFEAT_NOT_DECIDED_CLIENT", defeat_result.get("death_decided") == false)
	_check("DEFEAT_BAR_CONFIRMED", common_bar.defeat_confirmed())
	_check("DEFEAT_BAR_TOKEN", common_bar.last_feedback_token() == "TARGET_DEFEATED")
	_check("DEFEAT_DOES_NOT_REMOVE_ACTOR", is_instance_valid(enemy_common) and enemy_common.get_parent() == actor_still_parented)
	_check("DEFEAT_DOES_NOT_CHANGE_HP", is_equal_approx(common_bar.hp_fraction(), hp_before_defeat))
	var blocked_result: Dictionary = hud.present_combat_event({"token": "INTERACTION_BLOCKED"})
	_check("INTERACTION_BLOCKED_PASS", blocked_result.get("status") == "PASS")
	_check("INTERACTION_BLOCKED_PRIORITY_72", blocked_result.get("priority") == 72)
	_check("INTERACTION_BLOCKED_NO_IMPULSE", is_equal_approx(float(blocked_result.get("camera_impulse_m")), 0.0))
	_check("INTERACTION_BLOCKED_NO_GAMEPLAY_CHANGE", blocked_result.get("gameplay_result_changed") == false)
	feedback.clear_presentation_feedback()


func _test_reduced_motion_and_priority() -> void:
	var feedback: AndromedaCombatFeedbackPresenter = hud.combat_feedback
	feedback.clear_presentation_feedback()
	var reduced_result: Dictionary = hud.set_reduced_motion(true)
	_check("REDUCED_MOTION_ENABLE_PASS", reduced_result.get("status") == "PASS")
	_check("REDUCED_MOTION_TRUE", feedback.reduced_motion() and camera_rig.reduced_motion())
	_check("REDUCED_MOTION_STRUCTURAL_ZERO_IMPULSE", is_equal_approx(float(reduced_result.get("camera_impulse_m")), 0.0))
	_check("REDUCED_MOTION_STRUCTURAL_ZERO_FREEZE", reduced_result.get("local_visual_freeze_ms") == 0)
	_check("REDUCED_MOTION_INFORMATION_PRESERVED", reduced_result.get("information_preserved_without_motion") == true)
	var target_visual: Node = enemy_common.get_node("VisualRoot")
	var reduced_critical: Dictionary = hud.present_combat_event({
		"token": "COMBAT_CRITICAL_HIT",
		"target_ref": enemy_common.target_ref,
		"confirmed_externally": true,
		"strength": "STRONG",
	})
	_check("REDUCED_CRITICAL_PRESENTATION_PASS", reduced_critical.get("status") == "PASS")
	_check("REDUCED_CRITICAL_FREEZE_ZERO", reduced_critical.get("local_visual_freeze_ms") == 0)
	_check("REDUCED_CRITICAL_IMPULSE_ZERO", is_equal_approx(float(reduced_critical.get("camera_impulse_m")), 0.0))
	_check("REDUCED_CRITICAL_VISUAL_NOT_DISABLED", target_visual.process_mode != Node.PROCESS_MODE_DISABLED)
	_check("REDUCED_CRITICAL_NO_FREEZE_TRACKER", feedback.local_freeze_count() == 0)
	_check("REDUCED_CRITICAL_SEMANTIC_INFO_VISIBLE", feedback.visible_tokens().has("COMBAT_CRITICAL_HIT"))
	await _wait_physics_frames(2)
	_check("REDUCED_CAMERA_OFFSET_ZERO", camera_rig.current_presentation_offset_m().length() < 0.0001)
	hud.set_reduced_motion(false)
	_check("REDUCED_MOTION_DISABLE_PASS", not feedback.reduced_motion() and not camera_rig.reduced_motion())

	feedback.clear_presentation_feedback()
	hud.present_combat_event({"token": "INTERACTION_BLOCKED"})
	hud.present_combat_event({"token": "COMBAT_HIT", "target_ref": enemy_common.target_ref, "confirmed_externally": true})
	hud.present_combat_event({"token": "COMBAT_CRITICAL_HIT", "target_ref": enemy_common.target_ref, "confirmed_externally": true})
	hud.present_combat_event({"token": "PLAYER_HURT", "confirmed_externally": true})
	var priorities: Array[int] = feedback.visible_priorities()
	var tokens: Array[String] = feedback.visible_tokens()
	_check("MULTI_FEEDBACK_LIMIT_THREE", tokens.size() == 3, str(tokens))
	_check("MULTI_FEEDBACK_PRIORITY_SORTED", priorities == [95, 85, 80], str(priorities))
	_check("MULTI_FEEDBACK_PLAYER_DAMAGE_FIRST", tokens[0] == "PLAYER_HURT", str(tokens))
	_check("MULTI_FEEDBACK_CRITICAL_BEFORE_HIT", tokens[1] == "COMBAT_CRITICAL_HIT" and tokens[2] == "COMBAT_HIT", str(tokens))
	_check("MULTI_FEEDBACK_BLOCKED_DROPPED_FIRST", not tokens.has("INTERACTION_BLOCKED"), str(tokens))
	var priority_contract: Dictionary = feedback.priority_contract_snapshot()
	_check("PRIORITY_CRITICAL_RECEIVED_100", priority_contract.get("PLAYER_CRITICAL_DAMAGE") == 100)
	_check("PRIORITY_DAMAGE_RECEIVED_95", priority_contract.get("PLAYER_DAMAGE") == 95)
	_check("PRIORITY_BOSS_DANGER_90", priority_contract.get("BOSS_DANGER") == 90)
	_check("PRIORITY_CRITICAL_CAUSED_85", priority_contract.get("CRITICAL_HIT_CONFIRM") == 85)
	_check("PRIORITY_HIT_CONFIRMED_80", priority_contract.get("HIT_CONFIRM") == 80)
	_check("PRIORITY_BLOCKED_72", priority_contract.get("BLOCKED_INTERACTION") == 72)
	_check("PRIORITY_QUEST_68", priority_contract.get("QUEST_UPDATE") == 68)
	_check("PRIORITY_INTERACTION_60", priority_contract.get("INTERACTION_CONFIRM") == 60)
	_check("PRIORITY_PICKUP_50", priority_contract.get("PICKUP") == 50)
	_check("PRIORITY_MOVE_20", priority_contract.get("MOVE_CLICK") == 20)
	_check("PRIORITY_AMBIENT_10", priority_contract.get("AMBIENT") == 10)
	_check("PICKUP_CANNOT_HIDE_SERIOUS_DAMAGE", int(priority_contract.get("PLAYER_DAMAGE")) > int(priority_contract.get("PICKUP")))
	feedback.clear_presentation_feedback()
	await _wait_process_frames(1)


func _test_targeting_camera_and_click_to_move() -> void:
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	player.velocity = Vector3.ZERO
	enemy_common.global_position = Vector3(8.0, 0.0, -8.0)
	enemy_alpha.global_position = Vector3(10.0, 0.0, -3.0)
	camera_rig.set_follow_target(player, true)
	await _wait_physics_frames(6)
	var enemy_screen: Vector2 = main.target_to_screen(enemy_common)
	var select_result: Dictionary = main.handle_pointer_event(_mouse_button_event(MOUSE_BUTTON_LEFT, enemy_screen))
	_check("TARGET_SELECT_FOR_FEEDBACK_PASS", select_result.get("status") == "PASS", JSON.stringify(select_result))
	_check("TARGET_SELECT_FOR_FEEDBACK_INTENT", select_result.get("intent") == "SELECT_TARGET", JSON.stringify(select_result))
	_check("TARGET_SELECT_COMMON_REF", main.selected_target_ref() == enemy_common.target_ref, main.selected_target_ref())
	var selected_before: String = main.selected_target_ref()
	var pointer_serial_before: int = main.pointer_resolution_serial()
	var target_distance_before: float = camera_rig.target_distance_m()
	var camera_root_before: Vector3 = camera_rig.global_position
	var common_bar: AndromedaEnemyCombatBar = hud.enemy_bar_for_ref(enemy_common.target_ref)
	var alpha_bar: AndromedaEnemyCombatBar = hud.enemy_bar_for_ref(enemy_alpha.target_ref)
	var alpha_token_before: String = alpha_bar.last_feedback_token()
	var critical_result: Dictionary = hud.present_combat_event({
		"token": "COMBAT_CRITICAL_HIT",
		"target_ref": enemy_common.target_ref,
		"confirmed_externally": true,
	})
	_check("TARGETED_FEEDBACK_PASS", critical_result.get("status") == "PASS")
	await _wait_physics_frames(3)
	_check("FEEDBACK_DOES_NOT_CHANGE_SELECTED_REF", main.selected_target_ref() == selected_before)
	_check("FEEDBACK_DOES_NOT_COMMIT_POINTER_AGAIN", main.pointer_resolution_serial() == pointer_serial_before)
	_check("FEEDBACK_BAR_REMAINS_COMMON", common_bar.last_feedback_token() == "COMBAT_CRITICAL_HIT" and common_bar.target_ref() == selected_before)
	_check("FEEDBACK_DOES_NOT_SWAP_ALPHA_BAR", alpha_bar.target_ref() == enemy_alpha.target_ref and alpha_bar.last_feedback_token() == alpha_token_before)
	_check("FEEDBACK_NO_FORCED_COMBAT_ZOOM", is_equal_approx(camera_rig.target_distance_m(), target_distance_before))
	_check("FEEDBACK_CAMERA_ROOT_FOLLOW_UNCHANGED", camera_rig.global_position.distance_to(camera_root_before) < 0.001, "%s/%s" % [camera_root_before, camera_rig.global_position])
	_check("FEEDBACK_CAMERA_FREE_ORBIT_FALSE", camera_rig.contract_snapshot().get("free_orbit") == false)
	_check("FEEDBACK_CAMERA_SELECTION_RERESOLVE_FALSE", camera_rig.contract_snapshot().get("presentation_impulse_rewrites_selection") == false)
	await get_tree().create_timer(0.14).timeout

	enemy_common.global_position = Vector3(12.0, 0.0, -12.0)
	enemy_alpha.global_position = Vector3(14.0, 0.0, -12.0)
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	player.velocity = Vector3.ZERO
	camera_rig.set_follow_target(player, true)
	await _wait_physics_frames(5)
	var hurt_before_move: Dictionary = hud.present_combat_event({"token": "PLAYER_HURT", "confirmed_externally": true})
	_check("FEEDBACK_BEFORE_CLICK_MOVE_PASS", hurt_before_move.get("status") == "PASS")
	var ground_world := Vector3(-8.0, 0.0, 4.0)
	var ground_screen: Vector2 = main.world_to_screen(ground_world)
	var move_result: Dictionary = main.handle_pointer_event(_mouse_button_event(MOUSE_BUTTON_LEFT, ground_screen))
	_check("CLICK_TO_MOVE_DURING_FEEDBACK_PASS", move_result.get("status") == "PASS", JSON.stringify(move_result))
	_check("CLICK_TO_MOVE_DURING_FEEDBACK_INTENT", move_result.get("intent") == "MOVE_TO_POINT", JSON.stringify(move_result))
	_check("CLICK_TO_MOVE_DURING_FEEDBACK_REQUESTED", move_result.get("movement_result", {}).get("status") == "PASS", JSON.stringify(move_result))
	var player_before_move: Vector3 = player.global_position
	await _wait_physics_frames(18)
	_check("CLICK_TO_MOVE_DURING_FEEDBACK_MOVES", _horizontal_distance(player_before_move, player.global_position) > 0.05, "%s/%s" % [player_before_move, player.global_position])
	_check("CLICK_TO_MOVE_FEEDBACK_DOES_NOT_CHANGE_TARGET", main.selected_target_ref() == selected_before)
	_check("HUD_STILL_IGNORES_WORLD_POINTER", hud.mouse_filter == Control.MOUSE_FILTER_IGNORE)
	_check("FEEDBACK_LAYER_IGNORES_WORLD_POINTER", hud.combat_feedback.mouse_filter == Control.MOUSE_FILTER_IGNORE)
	player.stop_local_prediction()
	var camera_y_before: float = camera_rig.global_position.y
	player.global_position.y += 0.05
	await _wait_physics_frames(8)
	_check("CAMERA_MICRO_HEIGHT_STABILITY_PRESERVED", absf(camera_rig.global_position.y - camera_y_before) < 0.001, "%f/%f" % [camera_y_before, camera_rig.global_position.y])
	_check("MICRO_HEIGHT_FEEDBACK_TARGET_STABLE", main.selected_target_ref() == selected_before)
	_check("CAMERA_FOLLOW_TARGET_PRESERVED", camera_rig.follow_target() == player)
	_check("CAMERA_IMPULSE_FINAL_ZERO", camera_rig.current_presentation_offset_m().length() < 0.0001)
	hud.combat_feedback.clear_presentation_feedback()


func _mouse_button_event(button: int, position: Vector2) -> InputEventMouseButton:
	var event := InputEventMouseButton.new()
	event.button_index = button as MouseButton
	event.pressed = true
	event.position = position
	return event


func _color_not_black(color: Color) -> bool:
	return color.a > 0.1 and (color.r > 0.08 or color.g > 0.08 or color.b > 0.08)


func _horizontal_distance(first: Vector3, second: Vector3) -> float:
	return Vector2(first.x, first.z).distance_to(Vector2(second.x, second.z))


func _wait_process_frames(frame_count: int) -> void:
	for frame_index: int in range(frame_count):
		await get_tree().process_frame


func _wait_physics_frames(frame_count: int) -> void:
	for frame_index: int in range(frame_count):
		await get_tree().physics_frame


func _restore_gate_state() -> void:
	hud.combat_feedback.clear_presentation_feedback()
	hud.set_reduced_motion(false)
	hud.project_player_combat_vitals(1.0, 0.0, false, "LOCAL_GATE_PLACEHOLDER")
	hud.project_enemy_combat_vitals(enemy_common.target_ref, 1.0, 0.0, false, "LOCAL_GATE_PLACEHOLDER")
	hud.project_enemy_combat_vitals(enemy_alpha.target_ref, 1.0, 1.0, false, "LOCAL_GATE_PLACEHOLDER")
	hud.project_stamina(1.0, "INACTIVE", "LOCAL_GATE_PLACEHOLDER")
	main.set_menu_open(false)
	player.stop_local_prediction()
	player.global_position = _player_original_position
	player.velocity = Vector3.ZERO
	enemy_common.global_position = _common_original_position
	enemy_alpha.global_position = _alpha_original_position
	enemy_common.rotation = _common_original_rotation
	enemy_alpha.rotation = _alpha_original_rotation
	camera_rig.set_follow_target(player, true)


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "B06_COMBAT_PRESENTATION_HP_SHIELD_ENEMY_BARS_GAME_FEEL",
		"acceptance_scope_pass": ["G16B-13", "G16B-15"],
		"partial_evidence_only": ["G16B-14", "G16B-20", "G16B-23"],
		"not_available_without_authoritative_backend": ["LIVE_COMBAT_HP_SHIELD_HIT_CRIT_DEFEAT_ROUNDTRIP", "AUTHORITATIVE_COOLDOWN"],
		"authority": "GODOT_COMBAT_PRESENTATION_ONLY",
		"backend_roundtrip_executed": false,
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_B06_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_B06_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_B06_SUMMARY: %s" % JSON.stringify(summary))
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
