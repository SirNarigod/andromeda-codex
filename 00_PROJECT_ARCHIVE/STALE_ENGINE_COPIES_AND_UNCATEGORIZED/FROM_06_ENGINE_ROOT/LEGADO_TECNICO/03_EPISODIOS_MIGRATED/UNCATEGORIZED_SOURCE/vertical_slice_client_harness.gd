extends Node
class_name AndromedaB11VerticalSliceClient

## B11 test/instrumentation orchestrator. External outcomes below are explicit fixtures
## used only to exercise client projection paths; they are never classified as live
## backend round-trips and never run unless a gate calls run_integrated_vertical_slice().

const AUTHORITY := "GODOT_B11_TEST_ORCHESTRATION_PRESENTATION_ONLY"
const PROJECTION_SOURCE := "B11_EXTERNAL_PROJECTION_FIXTURE_NOT_LIVE_AUTHORITY"
const DEFAULT_SESSION_REF := "B11-INTEGRATED-SESSION"
const WRONG_SESSION_REF := "B11-WRONG-SESSION"
const QUEST_REF := "QST-S12-VARGA-ORIENTATION"
const QUEST_CHOICE_REF := "CHOICE-S12-ORIENTATION-ACCEPT"
const VENDOR_REF := "SHOP-S13-91CDF9F934810A65B2"
const VENDOR_ITEM_REF := "ITEM-S13-BUY-PLACEHOLDER"
const PLAYER_OWNER_REF := "PROFILE-B11-PROJECTION"
const BAG_REF := "BAG-B11-EQUIPPED"
const DROPPED_BAG_REF := "BAG-B11-DROPPED-LAND"
const ENEMY_LOOT_REF := "LOOT-B11-ENEMY"
const RESOURCE_LOOT_REF := "LOOT-B11-TREE"

const REQUIRED_STAGE_ORDER: Array[String] = [
	"SPAWN",
	"EXPLORE",
	"WATER_TERRAIN_TRAVERSAL",
	"DIALOGUE",
	"QUEST",
	"COMBAT",
	"LOOT",
	"GATHER",
	"VENDOR",
	"SAVE",
	"DEATH_BAG_DROP",
	"RESPAWN",
]

var _main: AndromedaMainRuntime
var _performance: AndromedaB11PerformanceProbe
var _session: AndromedaClientSession
var _bridge: AndromedaRuntimeBridge
var _router: AndromedaInputRouter
var _timeline: Array[Dictionary] = []
var _running: bool = false
var _last_result: Dictionary = {}
var _session_ref: String = ""
var _resource_sequence: int = 0
var _output_sequence: int = 0
var _ground_loot_sequence: int = 0
var _preference_sequence: int = 0
var _inventory_sequence: int = 0
var _offer_sequence: int = 0
var _quest_sequence: int = 0
var _quest_event_sequence: int = 0
var _stock_sequence: int = 0
var _quote_sequence: int = 0
var _trade_sequence: int = 0
var _save_result_sequence: int = 0
var _death_sequence: int = 0
var _bag_sequence: int = 0
var _respawn_sequence: int = 0
var _exhaustion_sequence: int = 0


func bind_runtime(
	main_value: AndromedaMainRuntime,
	performance_value: AndromedaB11PerformanceProbe
) -> Dictionary:
	if main_value == null or performance_value == null:
		return _rejected("MAIN_AND_PERFORMANCE_PROBE_REQUIRED")
	_main = main_value
	_performance = performance_value
	_session = get_node_or_null("/root/ClientSession") as AndromedaClientSession
	_bridge = get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_router = get_node_or_null("/root/InputRouter") as AndromedaInputRouter
	if _session == null or _bridge == null or _router == null:
		return _rejected("B01_AUTOLOADS_REQUIRED")
	return {
		"status": "PASS",
		"inert_until_explicitly_called": true,
		"authoritative_roundtrip": false,
		"authority": AUTHORITY,
	}


func run_integrated_vertical_slice(session_ref_value: String = DEFAULT_SESSION_REF) -> Dictionary:
	if _running:
		return _rejected("VERTICAL_SLICE_ALREADY_RUNNING")
	if _main == null or _performance == null or _session == null or _bridge == null or _router == null:
		return _rejected("B11_HARNESS_NOT_BOUND")
	var normalized_session: String = session_ref_value.strip_edges()
	if normalized_session.is_empty():
		return _rejected("EMPTY_B11_SESSION_REF")
	_running = true
	_reset_run_state()
	_session_ref = normalized_session
	if _session.has_active_session() and _session.session_ref() != _session_ref:
		_session.revoke_session()
	var bind_result: Dictionary = _session.bind_session(_session_ref)
	if bind_result.get("status") != "PASS":
		_running = false
		return bind_result
	var perf_begin: Dictionary = _performance.begin_capture("B11_INTEGRATED_VERTICAL_SLICE", {
		"session_ref": _session_ref,
		"required_stage_order": REQUIRED_STAGE_ORDER.duplicate(),
		"external_projection_source": PROJECTION_SOURCE,
		"authoritative_roundtrip": false,
	})
	if perf_begin.get("status") != "PASS":
		_running = false
		return perf_begin

	await _wait_physics_frames(2)
	await _execute_stage("SPAWN", _stage_spawn())
	await _execute_stage("EXPLORE", await _stage_explore())
	await _execute_stage("WATER_TERRAIN_TRAVERSAL", _stage_water_terrain())
	await _execute_stage("DIALOGUE", _stage_dialogue())
	await _execute_stage("QUEST", await _stage_quest())
	await _execute_stage("COMBAT", await _stage_combat())
	await _execute_stage("LOOT", await _stage_loot())
	await _execute_stage("GATHER", await _stage_gather())
	await _execute_stage("VENDOR", await _stage_vendor())
	await _execute_stage("SAVE", _stage_save())
	await _execute_stage("DEATH_BAG_DROP", _stage_death_bag_drop())
	await _execute_stage("RESPAWN", await _stage_respawn())

	await _wait_process_frames(30)
	var performance_report: Dictionary = _performance.end_capture({
		"streaming_transitions": 4,
		"ground_loot_density": _main.ground_loot_client.registered_loot_count(),
		"npc_density": 3,
		"enemy_density": 2,
		"resource_density": _main.gathering_client.registered_resource_count(),
		"expected_persistent_world_additions": [ENEMY_LOOT_REF, RESOURCE_LOOT_REF, DROPPED_BAG_REF],
	})
	var failed_stages: Array[String] = []
	for stage: Dictionary in _timeline:
		if stage.get("status") != "PASS":
			failed_stages.append(str(stage.get("stage", "UNKNOWN")))
	var observed_order: Array[String] = []
	for stage: Dictionary in _timeline:
		observed_order.append(str(stage.get("stage", "")))
	var all_pass: bool = failed_stages.is_empty() and observed_order == REQUIRED_STAGE_ORDER
	_last_result = {
		"status": "PASS" if all_pass else "REJECTED",
		"reason": "" if all_pass else "INTEGRATED_STAGE_FAILURE",
		"session_ref": _session_ref,
		"session_epoch": _session.session_epoch(),
		"required_stage_order": REQUIRED_STAGE_ORDER.duplicate(),
		"observed_stage_order": observed_order,
		"timeline": _timeline.duplicate(true),
		"failed_stages": failed_stages,
		"integrated_client_flow_completed": all_pass,
		"single_main_instance": true,
		"single_session_continuity": _timeline_session_continuous(),
		"external_projection_source": PROJECTION_SOURCE,
		"authoritative_roundtrip": false,
		"backend_listener_observed": false,
		"g16b19_global_pass_eligible": false,
		"transport_submission_count": _transport_submission_count(),
		"gameplay_authority_moved_to_gdscript": false,
		"performance": performance_report,
		"authority": AUTHORITY,
	}
	_running = false
	return _last_result.duplicate(true)


func last_result() -> Dictionary:
	return _last_result.duplicate(true)


func required_stage_order() -> Array[String]:
	return REQUIRED_STAGE_ORDER.duplicate()


func contract_snapshot() -> Dictionary:
	return {
		"required_stage_order": REQUIRED_STAGE_ORDER.duplicate(),
		"inert_until_explicitly_called": true,
		"external_projection_fixture": true,
		"authoritative_roundtrip": false,
		"fixture_may_promote_authoritative_gate": false,
		"damage_authority": false,
		"critical_authority": false,
		"cooldown_authority": false,
		"loot_grant_authority": false,
		"inventory_authority": false,
		"quest_authority": false,
		"economy_authority": false,
		"save_authority": false,
		"death_authority": false,
		"ttl_authority": false,
		"ownership_authority": false,
		"respawn_point_authority": false,
		"backend_substitute": false,
		"invented_endpoint": false,
		"authority": AUTHORITY,
	}


func _execute_stage(stage_name: String, result: Dictionary) -> void:
	var entry: Dictionary = result.duplicate(true)
	entry["stage"] = stage_name
	entry["stage_index"] = _timeline.size()
	entry["session_ref"] = _session_ref
	entry["session_epoch"] = _session.session_epoch()
	entry["external_projection_source"] = PROJECTION_SOURCE
	entry["authoritative_roundtrip"] = false
	entry["gameplay_authority_changed"] = false
	_timeline.append(entry)
	_performance.mark_event(stage_name, {
		"status": entry.get("status", "REJECTED"),
		"target_ref": entry.get("target_ref", ""),
	})
	await _wait_process_frames(1)


func _stage_spawn() -> Dictionary:
	var cursor: Dictionary = _session.accept_snapshot_cursor(0, "B11-SPAWN-PROJECTION-000")
	var spawn_position := Vector3(-7.0, 0.0, 0.0)
	_main.player.global_position = spawn_position
	_main.player.stop_local_prediction()
	var inventory: Dictionary = _main.inventory_client.project_inventory_snapshot(_inventory_snapshot(true))
	var preference: Dictionary = _main.ground_loot_client.project_profile_preference(
		false,
		_session_ref,
		_next_preference_sequence(),
		true
	)
	return {
		"status": "PASS" if cursor.get("status") == "PASS" and inventory.get("status") == "PASS" and preference.get("status") == "PASS" else "REJECTED",
		"cursor": cursor,
		"spawn_position": spawn_position,
		"player_present": _main.player != null,
		"camera_follow": _main.camera_rig.follow_target() == _main.player,
		"inventory_projection": inventory,
		"profile_preference_projection": preference,
		"transport_submitted": false,
		"spawn_decided_locally": false,
	}


func _stage_explore() -> Dictionary:
	_main.player.stop_local_prediction()
	var first_move: Dictionary = _main.player.request_move(Vector3(-4.0, 0.0, 4.0))
	var first_destination: Vector3 = _main.player.requested_destination()
	var second_move: Dictionary = _main.player.request_move(Vector3(-3.0, 0.0, 5.0))
	var second_destination: Vector3 = _main.player.requested_destination()
	await _wait_physics_frames(10)
	var stream_a: Dictionary = _main.streaming_manager.set_active_cell(Vector2i(1, 0))
	var stream_b: Dictionary = _main.streaming_manager.set_active_cell(Vector2i(1, 1))
	var stream_c: Dictionary = _main.streaming_manager.set_active_cell(Vector2i(0, 1))
	var stream_d: Dictionary = _main.streaming_manager.set_active_cell(Vector2i(0, 0))
	var stream_snapshot: Dictionary = _main.streaming_manager.state_snapshot()
	var passable: bool = (
		first_move.get("status") == "PASS"
		and second_move.get("status") == "PASS"
		and not first_destination.is_equal_approx(second_destination)
		and stream_a.get("status") == "PASS"
		and stream_b.get("status") == "PASS"
		and stream_c.get("status") == "PASS"
		and stream_d.get("status") == "PASS"
	)
	return {
		"status": "PASS" if passable else "REJECTED",
		"first_move": first_move,
		"second_move": second_move,
		"multiple_destinations": not first_destination.is_equal_approx(second_destination),
		"navigation_ready": _main.navigation_ready(),
		"camera_follow": _main.camera_rig.follow_target() == _main.player,
		"streaming": stream_snapshot,
		"streaming_transitions": [stream_a, stream_b, stream_c, stream_d],
		"scene_tree_paused": get_tree().paused,
	}


func _stage_water_terrain() -> Dictionary:
	var terrain: Dictionary = _main.terrain_contract_snapshot()
	var shallow: AndromedaWaterVolume = _main.terrain_foundation.water_volume("WATER-B04-SHALLOW-CALM")
	var strong: AndromedaWaterVolume = _main.terrain_foundation.water_volume("WATER-B04-SHALLOW-STRONG")
	var under_bridge: AndromedaWaterVolume = _main.terrain_foundation.water_volume("WATER-B04-SHALLOW-UNDER-BRIDGE")
	var deep: AndromedaWaterVolume = _main.terrain_foundation.water_volume("WATER-B04-DEEP-SWIMMABLE")
	if shallow == null or strong == null or under_bridge == null or deep == null:
		return _rejected("WATER_FOUNDATION_INCOMPLETE")
	var shallow_player: Dictionary = shallow.sample_for_actor("PLAYER")
	var shallow_npc: Dictionary = shallow.sample_for_actor("NPC")
	var shallow_animal: Dictionary = shallow.sample_for_actor("ANIMAL")
	var shallow_vehicle: Dictionary = shallow.sample_for_actor("VEHICLE")
	var strong_player: Dictionary = strong.sample_for_actor("PLAYER")
	var bridge_player: Dictionary = under_bridge.sample_for_actor("PLAYER")
	var deep_player: Dictionary = deep.sample_for_actor("PLAYER")
	var deep_npc: Dictionary = deep.sample_for_actor("NPC")
	var deep_animal: Dictionary = deep.sample_for_actor("ANIMAL")
	var deep_vehicle: Dictionary = deep.sample_for_actor("VEHICLE")
	var stamina: Dictionary = _main.hud.project_stamina(0.62, "CONSUMING", PROJECTION_SOURCE)
	var exhaustion: Dictionary = _main.death_respawn_client.project_water_exhaustion({
		"server_authoritative": true,
		"session_ref": _session_ref,
		"exhaustion_sequence": _next_exhaustion_sequence(),
		"state": "STAMINA_ZERO_GRACE",
		"grace_remaining_s": 4.0,
	})
	var recovered: Dictionary = _main.death_respawn_client.project_water_exhaustion({
		"server_authoritative": true,
		"session_ref": _session_ref,
		"exhaustion_sequence": _next_exhaustion_sequence(),
		"state": "RECOVERED",
		"grace_remaining_s": 0.0,
	})
	var passable: bool = (
		terrain.get("status") == "PASS"
		and shallow_player.get("status") == "PASS"
		and shallow_npc.get("status") == "PASS"
		and shallow_animal.get("status") == "PASS"
		and shallow_vehicle.get("status") == "PASS"
		and strong_player.get("current_class") == "STRONG_CURRENT"
		and bridge_player.get("under_bridge") == true
		and deep_player.get("mode") == "SWIM"
		and deep_npc.get("mode") == "SWIM"
		and deep_animal.get("mode") == "SWIM"
		and deep_vehicle.get("status") == "BLOCKED"
		and stamina.get("status") == "PASS"
		and exhaustion.get("status") == "PASS"
		and recovered.get("status") == "PASS"
	)
	return {
		"status": "PASS" if passable else "REJECTED",
		"terrain": terrain,
		"shallow": {"player": shallow_player, "npc": shallow_npc, "animal": shallow_animal, "vehicle": shallow_vehicle},
		"strong_current": strong_player,
		"under_bridge": bridge_player,
		"deep": {"player": deep_player, "npc": deep_npc, "animal": deep_animal, "vehicle": deep_vehicle},
		"stamina_projection": stamina,
		"exhaustion_projection": exhaustion,
		"recovery_projection": recovered,
		"stamina_authority_local": false,
		"death_authority_local": false,
	}


func _stage_dialogue() -> Dictionary:
	var npc: AndromedaInteractionTarget = _main.dialogue_npc_primary
	var peer: AndromedaInteractionTarget = _main.dialogue_npc_peer
	var normal: Dictionary = _main.hud.present_dialogue_line(npc, {
		"line_ref": "B11-CONTRACTED-ORIENTATION-LINE",
		"speaker_ref": npc.target_ref,
		"conversation_ref": "B11-CONTRACTED-VARGA-CONVERSATION",
		"turn_index": 0,
		"text": "Orientacao de Varga",
		"important": false,
		"duration_seconds": 8.0,
	})
	var important: Dictionary = _main.hud.present_dialogue_line(peer, {
		"line_ref": "B11-CONTRACTED-WATER-WARNING",
		"speaker_ref": peer.target_ref,
		"conversation_ref": "B11-CONTRACTED-VARGA-CONVERSATION",
		"turn_index": 1,
		"text": "A corrente esta forte; atravesse com cuidado.",
		"important": true,
		"duration_seconds": 8.0,
	})
	var choices: Dictionary = _main.hud.present_choices(peer, [{
		"choice_ref": QUEST_CHOICE_REF,
		"label": "Aceitar",
	}], 1.5)
	var passable: bool = (
		normal.get("status") == "PASS"
		and important.get("status") == "PASS"
		and choices.get("status") == "PASS"
		and important.get("next_button") == false
		and important.get("world_pause") == false
		and _main.hud.important_dialogue_line_visible()
		and not get_tree().paused
	)
	return {
		"status": "PASS" if passable else "REJECTED",
		"normal_line": normal,
		"important_line": important,
		"choices": choices,
		"important_accessibility_line": _main.hud.important_dialogue_line_visible(),
		"world_paused": get_tree().paused,
		"narrative_authored_locally": false,
	}


func _stage_quest() -> Dictionary:
	var offer: Dictionary = _main.quest_client.project_offer_snapshot(_offer_snapshot())
	_main.player.stop_local_prediction()
	_main.player.global_position = _main.dialogue_npc_primary.global_position + Vector3(1.25, 0.0, 0.0)
	await _wait_physics_frames(2)
	var interaction: Dictionary = _main.quest_client.begin_quest_interaction(
		_main.dialogue_npc_primary,
		"B11_INTEGRATED_CONTEXT"
	)
	var accept: Dictionary = _main.quest_client.request_accept(QUEST_REF)
	var active: Dictionary = _main.quest_client.project_quest_snapshot(_quest_snapshot("ACTIVE", "PENDING"))
	var update: Dictionary = _main.quest_client.project_quest_event(_quest_event("B11-QUEST-OBJECTIVE-UPDATE"))
	var complete: Dictionary = _main.quest_client.project_quest_snapshot(_quest_snapshot("COMPLETED", "COMPLETE"))
	_main.hud.close_active_modal()
	var passable: bool = (
		offer.get("status") == "PASS"
		and interaction.get("status") == "PASS"
		and accept.get("status") == "PASS"
		and active.get("status") == "PASS"
		and update.get("status") == "PASS"
		and complete.get("status") == "PASS"
	)
	return {
		"status": "PASS" if passable else "REJECTED",
		"offer": offer,
		"interaction": interaction,
		"accept_intent": accept,
		"active_projection": active,
		"objective_event": update,
		"completion_projection": complete,
		"completion_decided_locally": false,
		"reward_granted_locally": false,
		"xp_granted_locally": false,
	}


func _stage_combat() -> Dictionary:
	_main.set_menu_open(false)
	_main.player.stop_local_prediction()
	_main.player.global_position = Vector3(-7.0, 0.0, 0.0)
	await _wait_physics_frames(3)
	var enemy: AndromedaInteractionTarget = _main.combat_enemy_common
	var left: Dictionary = _main.handle_pointer_event(_mouse_button(MOUSE_BUTTON_LEFT, _main.target_to_screen(enemy)))
	var target_before: String = _main.selected_target_ref()
	var right: Dictionary = _router.resolve_pointer_click(
		MOUSE_BUTTON_RIGHT,
		AndromedaInputRouter.HIT_ACTOR,
		enemy.global_position,
		enemy.target_ref,
		true
	)
	var common_vitals: Dictionary = _main.hud.project_enemy_combat_vitals(enemy.target_ref, 0.55, 0.0, true, PROJECTION_SOURCE)
	var alpha_vitals: Dictionary = _main.hud.project_enemy_combat_vitals(
		_main.combat_enemy_alpha.target_ref,
		0.80,
		0.35,
		true,
		PROJECTION_SOURCE
	)
	var hit: Dictionary = _main.hud.present_combat_event({
		"token": "COMBAT_HIT",
		"target_ref": enemy.target_ref,
		"strength": "NORMAL",
		"confirmed_externally": true,
	})
	var strong: Dictionary = _main.hud.present_combat_event({
		"token": "COMBAT_HIT",
		"target_ref": enemy.target_ref,
		"strength": "STRONG",
		"confirmed_externally": true,
	})
	var critical: Dictionary = _main.hud.present_combat_event({
		"token": "COMBAT_CRITICAL_HIT",
		"target_ref": enemy.target_ref,
		"confirmed_externally": true,
	})
	var target_after: String = _main.selected_target_ref()
	var reduced: Dictionary = _main.hud.set_reduced_motion(true)
	var reduced_hit: Dictionary = _main.hud.present_combat_event({
		"token": "COMBAT_CRITICAL_HIT",
		"target_ref": enemy.target_ref,
		"confirmed_externally": true,
	})
	_main.hud.set_reduced_motion(false)
	var passable: bool = (
		left.get("status") == "PASS"
		and target_before == enemy.target_ref
		and right.get("intent") == "CHASE_ATTACK"
		and right.get("input_mode") == "CLICK_ONLY"
		and common_vitals.get("status") == "PASS"
		and alpha_vitals.get("status") == "PASS"
		and hit.get("local_visual_freeze_ms") == 28
		and strong.get("local_visual_freeze_ms") == 42
		and critical.get("local_visual_freeze_ms") == 58
		and reduced.get("status") == "PASS"
		and reduced_hit.get("local_visual_freeze_ms") == 0
		and is_zero_approx(float(reduced_hit.get("camera_impulse_m", -1.0)))
		and target_before == target_after
		and not get_tree().paused
	)
	return {
		"status": "PASS" if passable else "REJECTED",
		"target_ref": enemy.target_ref,
		"left_selection": left,
		"right_click": right,
		"common_vitals": common_vitals,
		"alpha_vitals": alpha_vitals,
		"hit": hit,
		"strong": strong,
		"critical": critical,
		"reduced_motion_hit": reduced_hit,
		"target_preserved": target_before == target_after,
		"damage_decided_locally": false,
		"cooldown_decided_locally": false,
		"defeat_decided_locally": false,
	}


func _stage_loot() -> Dictionary:
	var output_event: Dictionary = _physical_output_event(
		"ENEMY",
		_main.combat_enemy_common.target_ref,
		ENEMY_LOOT_REF,
		"MATERIAL",
		2,
		Vector3(-5.0, 0.3, 5.0)
	)
	var output: Dictionary = _main.gathering_client.project_physical_output_event(output_event)
	var loot: AndromedaGroundLoot = _main.ground_loot_client.ground_loot_for_ref(ENEMY_LOOT_REF)
	if output.get("status") != "PASS" or loot == null:
		return _rejected("ENEMY_GROUND_LOOT_PROJECTION_FAILED")
	var settle: Dictionary = _main.ground_loot_client.project_ground_loot_snapshot(_ground_loot_snapshot([
		_loot_entry(ENEMY_LOOT_REF, "ENEMY", _main.combat_enemy_common.target_ref, "MATERIAL", 2, loot.global_position, true),
	]))
	loot = _main.ground_loot_client.ground_loot_for_ref(ENEMY_LOOT_REF)
	_main.player.stop_local_prediction()
	_main.player.global_position = loot.global_position + Vector3(0.45, 0.0, 0.0)
	await _wait_physics_frames(2)
	var eligibility: Dictionary = _main.ground_loot_client.evaluate_pickup_candidate(loot)
	var resolved: Dictionary = _router.resolve_pointer_click(
		MOUSE_BUTTON_LEFT,
		AndromedaInputRouter.HIT_GROUND_LOOT,
		loot.global_position,
		loot.target_ref,
		false,
		loot.physical_distance_to(_main.player),
		true,
		loot.is_pickup_settled()
	)
	var request: Dictionary = _main.ground_loot_client.handle_manual_pointer_intent(resolved, loot)
	var full_projection: Dictionary = _main.ground_loot_client.project_pickup_result({
		"server_authoritative": true,
		"session_ref": _session_ref,
		"target_ref": ENEMY_LOOT_REF,
		"result_sequence": 0,
		"status": "REJECTED",
		"reason": "INVENTORY_FULL",
	})
	var passable: bool = (
		output.get("status") == "PASS"
		and output.get("ground_loot_before_inventory") == true
		and settle.get("status") == "PASS"
		and loot.is_pickup_settled()
		and eligibility.get("status") == "PASS"
		and float(eligibility.get("physical_distance_m", INF)) <= 0.5
		and request.get("intent") == "REQUEST_PICKUP"
		and request.get("transport_submitted") == false
		and full_projection.get("status") == "PASS"
		and _main.ground_loot_client.ground_loot_for_ref(ENEMY_LOOT_REF) != null
	)
	return {
		"status": "PASS" if passable else "REJECTED",
		"target_ref": ENEMY_LOOT_REF,
		"output": output,
		"settle": settle,
		"eligibility": eligibility,
		"pickup_request": request,
		"inventory_full_projection": full_projection,
		"loot_remains_after_inventory_full": _main.ground_loot_client.ground_loot_for_ref(ENEMY_LOOT_REF) != null,
		"item_granted_locally": false,
		"inventory_mutated_locally": false,
	}


func _stage_gather() -> Dictionary:
	var resources: Array[Dictionary] = []
	for child: Node in _main.resource_root.get_children():
		var resource: AndromedaResourceNode = child as AndromedaResourceNode
		if resource != null:
			resources.append({
				"target_ref": resource.target_ref,
				"resource_kind": resource.resource_kind,
				"state": "AVAILABLE",
				"stream_phase": "ACTIVE",
			})
	var resource_projection: Dictionary = _main.gathering_client.project_resource_snapshot(_resource_snapshot(resources))
	var tree: AndromedaResourceNode = _main.gathering_client.resource_for_ref("RESOURCE-B03-TREE-001")
	if tree == null:
		return _rejected("TREE_RESOURCE_NOT_FOUND")
	_main.player.stop_local_prediction()
	_main.player.global_position = tree.global_position + Vector3(0.5, 0.0, 0.0)
	await _wait_physics_frames(2)
	var request: Dictionary = _main.gathering_client.begin_gather_interaction(tree, "B11_INTEGRATED_E")
	var result: Dictionary = _main.gathering_client.project_gathering_result({
		"server_authoritative": true,
		"session_ref": _session_ref,
		"target_ref": tree.target_ref,
		"result_sequence": 0,
		"status": "PASS",
	})
	var stamina: Dictionary = _main.gathering_client.project_gathering_stamina_snapshot({
		"server_authoritative": true,
		"session_ref": _session_ref,
		"stamina_sequence": 0,
		"stamina_fraction": 0.48,
		"activity": "CONSUMING",
	})
	var output_event: Dictionary = _physical_output_event(
		"TREE",
		tree.target_ref,
		RESOURCE_LOOT_REF,
		"MATERIAL",
		4,
		tree.drop_anchor_world_position()
	)
	var output: Dictionary = _main.gathering_client.project_physical_output_event(output_event)
	var tree_loot: AndromedaGroundLoot = _main.ground_loot_client.ground_loot_for_ref(RESOURCE_LOOT_REF)
	if output.get("status") != "PASS" or tree_loot == null:
		return _rejected("TREE_OUTPUT_GROUND_LOOT_PROJECTION_FAILED")
	var settle: Dictionary = _main.ground_loot_client.project_ground_loot_snapshot(_ground_loot_snapshot([
		_loot_entry(ENEMY_LOOT_REF, "ENEMY", _main.combat_enemy_common.target_ref, "MATERIAL", 2, _main.ground_loot_client.ground_loot_for_ref(ENEMY_LOOT_REF).global_position, true),
		_loot_entry(RESOURCE_LOOT_REF, "TREE", tree.target_ref, "MATERIAL", 4, tree_loot.global_position, true),
	]))
	_main.ground_loot_client.observe_action_context({
		"attack_active": true,
		"interaction_active": true,
		"chase_target_ref": _main.combat_enemy_common.target_ref,
	})
	var preference: Dictionary = _main.ground_loot_client.project_profile_preference(
		true,
		_session_ref,
		_next_preference_sequence(),
		true
	)
	var auto_scan: Dictionary = _main.ground_loot_client.scan_auto_pickup_once()
	var passable: bool = (
		resource_projection.get("status") == "PASS"
		and request.get("intent") == "REQUEST_GATHER"
		and request.get("transport_submitted") == false
		and result.get("status") == "PASS"
		and result.get("output_spawned") == false
		and stamina.get("status") == "PASS"
		and output.get("status") == "PASS"
		and output.get("ground_loot_before_inventory") == true
		and settle.get("status") == "PASS"
		and preference.get("status") == "PASS"
		and auto_scan.get("interrupts_action") == false
		and auto_scan.get("action_context_preserved") == true
	)
	return {
		"status": "PASS" if passable else "REJECTED",
		"target_ref": tree.target_ref,
		"resource_projection": resource_projection,
		"gather_request": request,
		"gather_result": result,
		"stamina_projection": stamina,
		"physical_output": output,
		"settle": settle,
		"auto_pickup_during_gathering": auto_scan,
		"yield_calculated_locally": false,
		"inventory_mutated_locally": false,
	}


func _stage_vendor() -> Dictionary:
	var stock: Dictionary = _main.vendor_client.project_stock_snapshot(_stock_snapshot())
	_main.player.stop_local_prediction()
	_main.player.global_position = _main.vendor_npc.global_position + Vector3(1.25, 0.0, 0.0)
	await _wait_physics_frames(2)
	var open: Dictionary = _main.vendor_client.begin_vendor_interaction(_main.vendor_npc, "B11_INTEGRATED_RIGHT_CLICK")
	var quote_request: Dictionary = _main.vendor_client.request_quote(VENDOR_REF, VENDOR_ITEM_REF, "BUY", 2)
	var quote: Dictionary = _quote_payload(quote_request)
	var quote_projection: Dictionary = _main.vendor_client.project_quote(quote)
	var execute: Dictionary = _main.vendor_client.execute_trade(
		str(quote.get("quote_ref", "")),
		VENDOR_REF,
		VENDOR_ITEM_REF,
		"BUY",
		2,
		"B11-EXPLICIT-CONFIRMATION",
		true
	)
	var trade: Dictionary = _main.vendor_client.project_trade_result(_trade_result_payload(execute))
	_main.hud.close_active_modal()
	var passable: bool = (
		stock.get("status") == "PASS"
		and open.get("status") == "PASS"
		and open.get("auto_purchase") == false
		and quote_request.get("status") == "PASS"
		and quote_request.get("transport_submitted") == false
		and quote_projection.get("status") == "PASS"
		and execute.get("status") == "PASS"
		and str(execute.get("confirmation_ref", "")) == "B11-EXPLICIT-CONFIRMATION"
		and execute.get("intent_envelope", {}).get("envelope", {}).get("params", {}).get("explicit_user_confirmation") == true
		and execute.get("transport_submitted") == false
		and trade.get("status") == "PASS"
		and trade.get("wallet_mutated_locally") == false
		and trade.get("inventory_mutated_locally") == false
	)
	return {
		"status": "PASS" if passable else "REJECTED",
		"target_ref": _main.vendor_npc.target_ref,
		"stock": stock,
		"open": open,
		"quote_request": quote_request,
		"quote_projection": quote_projection,
		"execute_request": execute,
		"trade_projection": trade,
		"auto_purchase": false,
		"price_calculated_locally": false,
		"wallet_mutated_locally": false,
		"inventory_mutated_locally": false,
	}


func _stage_save() -> Dictionary:
	var intent: Dictionary = _main.save_reload_client.request_manual_save("B11-INTEGRATED")
	var result: Dictionary = _main.save_reload_client.project_save_result(_save_result_payload(intent))
	var passable: bool = (
		intent.get("status") == "PASS"
		and intent.get("transport_submitted") == false
		and result.get("status") == "PASS"
		and result.get("success_confirmed_externally") == true
		and result.get("save_written_locally") == false
	)
	return {
		"status": "PASS" if passable else "REJECTED",
		"save_intent": intent,
		"save_projection": result,
		"save_written_locally": false,
		"authoritative_persistence_proven": false,
	}


func _stage_death_bag_drop() -> Dictionary:
	var bag_snapshot: Dictionary = _bag_snapshot([_bag_entry(DROPPED_BAG_REF, "DROPPED_LAND", "LAND", 0.0)])
	var death: Dictionary = _main.death_respawn_client.project_death_event({
		"server_authoritative": true,
		"session_ref": _session_ref,
		"death_sequence": _next_death_sequence(),
		"death_ref": "DEATH-B11-INTEGRATED",
		"state": "DEAD_AWAITING_RESPAWN",
		"retention": _retention_projection(),
		"bag_drop": {
			"dropped": true,
			"reason": "EQUIPPED_BAG_EXTERNAL_DROP",
			"single_container": true,
			"dropped_bag_snapshot": bag_snapshot,
		},
	})
	var bag: AndromedaDroppedBag = _main.dropped_bag_client.dropped_bag_for_ref(DROPPED_BAG_REF)
	var passable: bool = (
		death.get("status") == "PASS"
		and death.get("bag_dropped") == true
		and death.get("xp_retained_projection") == true
		and death.get("death_decided_locally") == false
		and death.get("items_mutated_locally") == false
		and bag != null
		and bag.environment() == "LAND"
		and bag.water_ttl_s() == null
		and _main.world_input_blocked()
	)
	return {
		"status": "PASS" if passable else "REJECTED",
		"target_ref": DROPPED_BAG_REF,
		"death_projection": death,
		"bag_projection": bag.presentation_snapshot() if bag != null else {},
		"single_container": true,
		"death_decided_locally": false,
		"bag_drop_decided_locally": false,
		"ttl_advanced_locally": false,
	}


func _stage_respawn() -> Dictionary:
	var request: Dictionary = _main.death_respawn_client.request_respawn()
	var snapshot: Dictionary = {
		"server_authoritative": true,
		"session_ref": _session_ref,
		"respawn_sequence": _next_respawn_sequence(),
		"request_ref": str(request.get("request_ref", "")),
		"state": "READY",
		"position": _position_dict(Vector3(-6.25, 0.0, 1.25)),
		"safe_waypoint_ref": "EXTERNAL-SAFE-WAYPOINT-B11",
	}
	var projection: Dictionary = _main.death_respawn_client.project_respawn_snapshot(snapshot)
	await _wait_physics_frames(3)
	var bag_remains: AndromedaDroppedBag = _main.dropped_bag_client.dropped_bag_for_ref(DROPPED_BAG_REF)
	var inventory: Dictionary = _main.inventory_client.projected_state()
	var quick_slots: Array = inventory.get("weapon_loadout", {}).get("quick_slots", []) as Array
	var passable: bool = (
		request.get("status") == "PASS"
		and request.get("transport_submitted") == false
		and projection.get("status") == "PASS"
		and projection.get("camera_follow_restored") == true
		and projection.get("world_input_blocked") == false
		and bag_remains != null
		and quick_slots.size() == 2
		and not get_tree().paused
	)
	return {
		"status": "PASS" if passable else "REJECTED",
		"respawn_request": request,
		"respawn_projection": projection,
		"dropped_bag_remains": bag_remains != null,
		"quick_slot_count": quick_slots.size(),
		"camera_follow": _main.camera_rig.follow_target() == _main.player,
		"target_cleared": _main.selected_target_ref().is_empty(),
		"respawn_point_selected_locally": false,
	}


func _resource_snapshot(resources: Array[Dictionary]) -> Dictionary:
	var sequence: int = _resource_sequence
	_resource_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _session_ref,
		"snapshot_sequence": sequence,
		"resources": resources,
	}


func _physical_output_event(
	source_kind: String,
	source_ref: String,
	target_ref: String,
	item_kind: String,
	quantity: int,
	authorized_position: Vector3
) -> Dictionary:
	var event_sequence: int = _output_sequence
	_output_sequence += 1
	var loot_sequence: int = _ground_loot_sequence
	_ground_loot_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _session_ref,
		"event_ref": "B11-OUTPUT-%s-%03d" % [source_kind, event_sequence],
		"event_sequence": event_sequence,
		"ground_loot_snapshot_sequence": loot_sequence,
		"source_kind": source_kind,
		"source_ref": source_ref,
		"authorized_position": _position_dict(authorized_position),
		"outputs": [{
			"target_ref": target_ref,
			"item_ref": "ITEM-B11-%s" % source_kind,
			"item_kind": item_kind,
			"quantity": quantity,
			"state": "ACTIVE",
			"settled": false,
			"reachable": true,
			"water_exposure_s": 0.0,
		}],
	}


func _ground_loot_snapshot(entries: Array[Dictionary]) -> Dictionary:
	var sequence: int = _ground_loot_sequence
	_ground_loot_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _session_ref,
		"snapshot_sequence": sequence,
		"ground_loot": entries,
	}


func _loot_entry(
	target_ref: String,
	source_kind: String,
	source_ref: String,
	item_kind: String,
	quantity: int,
	position: Vector3,
	settled: bool
) -> Dictionary:
	return {
		"target_ref": target_ref,
		"drop_ref": target_ref,
		"source_ref": source_ref,
		"source_kind": source_kind,
		"item_ref": "ITEM-B11-%s" % source_kind,
		"item_kind": item_kind,
		"quantity": quantity,
		"state": "ACTIVE",
		"settled": settled,
		"reachable": true,
		"water_exposure_s": 0.0,
		"settled_position": _position_dict(position),
	}


func _inventory_snapshot(with_bag: bool) -> Dictionary:
	var sequence: int = _inventory_sequence
	_inventory_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _session_ref,
		"snapshot_sequence": sequence,
		"base_inventory": {
			"owner_ref": PLAYER_OWNER_REF,
			"slot_limit": 8,
			"weight_limit": 20.0,
			"stacks": [{"item_ref": "BASE-B11", "quantity": 2, "protected": false}],
		},
		"bag": {
			"state": "BAG_EQUIPPED" if with_bag else "NO_BAG",
			"bag_ref": BAG_REF if with_bag else "",
			"capacity_slots": 30 if with_bag else 0,
			"capacity_weight": 80.0 if with_bag else 0.0,
			"contents": [{"item_ref": "COMMON-B11-CARRIED", "quantity": 4}] if with_bag else [],
		},
		"equipment": {
			"slots": {"ARMOR": "ARMOR-B11", "CLOTHES": "CLOTHES-B11"},
			"protected_critical_refs": ["QUEST-CRITICAL-B11", "UNIQUE-CRITICAL-B11"],
		},
		"weapon_loadout": {
			"quick_slots": [
				{"slot": 1, "item_ref": "WEAPON-B11-ONE"},
				{"slot": 2, "item_ref": "WEAPON-B11-TWO"},
			],
			"active_slot": 2,
		},
		"carry": {
			"current_weight": 14.0 if with_bag else 4.0,
			"max_weight": 80.0 if with_bag else 20.0,
			"used_slots": 2 if with_bag else 1,
			"max_slots": 38 if with_bag else 8,
		},
		"routing": {
			"source": "EQUIPPED_BAG" if with_bag else "BASE_INVENTORY",
			"effective_inventory_owner_ref": BAG_REF if with_bag else PLAYER_OWNER_REF,
			"currency_wallet_owner_ref": PLAYER_OWNER_REF,
		},
	}


func _offer_snapshot() -> Dictionary:
	var sequence: int = _offer_sequence
	_offer_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _session_ref,
		"snapshot_sequence": sequence,
		"offers": [{
			"quest_ref": QUEST_REF,
			"npc_ref": _main.dialogue_npc_primary.target_ref,
			"title": "Orientacao de Varga",
			"objectives": [{"objective_ref": "OBJ-S12-ORIENTATION", "text": "Objetivo contratual", "state": "PENDING"}],
			"choices": [{"choice_ref": QUEST_CHOICE_REF, "label": "Aceitar"}],
		}],
	}


func _quest_snapshot(state_value: String, objective_state: String) -> Dictionary:
	var sequence: int = _quest_sequence
	_quest_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _session_ref,
		"snapshot_sequence": sequence,
		"quests": [{
			"quest_ref": QUEST_REF,
			"npc_ref": _main.dialogue_npc_primary.target_ref,
			"title": "Orientacao de Varga",
			"state": state_value,
			"objectives": [{"objective_ref": "OBJ-S12-ORIENTATION", "text": "Objetivo contratual", "state": objective_state}],
			"choices": [],
		}],
	}


func _quest_event(event_ref: String) -> Dictionary:
	var sequence: int = _quest_event_sequence
	_quest_event_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _session_ref,
		"event_sequence": sequence,
		"event_ref": event_ref,
		"quest_ref": QUEST_REF,
		"feedback_text": "Objetivo atualizado externamente",
	}


func _stock_snapshot() -> Dictionary:
	var sequence: int = _stock_sequence
	_stock_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _session_ref,
		"snapshot_sequence": sequence,
		"vendor_ref": VENDOR_REF,
		"items": [{
			"item_ref": VENDOR_ITEM_REF,
			"display_name": "Item de compra placeholder",
			"operation_flags": ["BUY"],
		}],
	}


func _quote_payload(request: Dictionary) -> Dictionary:
	var sequence: int = _quote_sequence
	_quote_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _session_ref,
		"quote_sequence": sequence,
		"quote_ref": "QUOTE-B11-%03d" % sequence,
		"vendor_ref": str(request.get("vendor_ref", "")),
		"item_ref": str(request.get("item_ref", "")),
		"direction": str(request.get("operation", "")),
		"quantity": int(request.get("quantity", 0)),
		"unit_price": 5.0,
		"total_price": 10.0,
		"currency": "CURRENCY-S13",
		"active": true,
	}


func _trade_result_payload(execute: Dictionary) -> Dictionary:
	var sequence: int = _trade_sequence
	_trade_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _session_ref,
		"result_sequence": sequence,
		"event_ref": str(execute.get("event_ref", "")),
		"quote_ref": str(execute.get("quote_ref", "")),
		"result": "ACCEPTED",
		"reason": "",
		"wallet_revision": 100 + sequence,
		"inventory_revision": 200 + sequence,
	}


func _save_result_payload(intent: Dictionary) -> Dictionary:
	var sequence: int = _save_result_sequence
	_save_result_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _session_ref,
		"result_sequence": sequence,
		"request_ref": str(intent.get("request_ref", "")),
		"result": "CONFIRMED",
		"reason": "",
		"save_ref": "SAVE-B11-%03d" % sequence,
		"save_sequence": 100 + sequence,
	}


func _bag_entry(bag_ref_value: String, state_value: String, environment_value: String, exposure_s: float) -> Dictionary:
	var water_ttl_projection: Variant = null
	if environment_value != "LAND":
		water_ttl_projection = 1800.0
	return {
		"bag_ref": bag_ref_value,
		"target_ref": bag_ref_value,
		"original_owner_ref": PLAYER_OWNER_REF,
		"property_owner_ref": PLAYER_OWNER_REF,
		"carrier_ref": "",
		"state": state_value,
		"environment": environment_value,
		"location_kind": environment_value,
		"recoverable": true,
		"water_exposure_s": exposure_s,
		"water_ttl_s": water_ttl_projection,
		"contents_summary": [{"item_ref": "COMMON-B11-CARRIED", "quantity": 4}],
		"context_metadata": {"origin": PROJECTION_SOURCE, "canonical_mutation": false},
		"position": _position_dict(Vector3(-6.0, 0.0, 1.5)),
	}


func _bag_snapshot(entries: Array[Dictionary]) -> Dictionary:
	var sequence: int = _bag_sequence
	_bag_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _session_ref,
		"snapshot_sequence": sequence,
		"dropped_bags": entries,
		"complete_projection": false,
	}


func _retention_projection() -> Dictionary:
	return {
		"xp_retained": true,
		"quick_slots": [
			{"slot": 1, "item_ref": "WEAPON-B11-ONE"},
			{"slot": 2, "item_ref": "WEAPON-B11-TWO"},
		],
		"active_slot": 2,
		"equipped_armor_refs": ["ARMOR-B11"],
		"equipped_clothes_refs": ["CLOTHES-B11"],
		"protected_critical_refs": ["QUEST-CRITICAL-B11", "UNIQUE-CRITICAL-B11"],
	}


func _timeline_session_continuous() -> bool:
	if _timeline.size() != REQUIRED_STAGE_ORDER.size():
		return false
	for stage: Dictionary in _timeline:
		if str(stage.get("session_ref", "")) != _session_ref:
			return false
		if int(stage.get("session_epoch", -1)) != _session.session_epoch():
			return false
	return true


func _transport_submission_count() -> int:
	var count: int = 0
	for stage: Dictionary in _timeline:
		count += _count_true_key_recursive(stage, "transport_submitted")
	return count


func _count_true_key_recursive(value: Variant, key_name: String) -> int:
	var count: int = 0
	if value is Dictionary:
		var dictionary: Dictionary = value
		if dictionary.get(key_name) == true:
			count += 1
		for nested: Variant in dictionary.values():
			count += _count_true_key_recursive(nested, key_name)
	elif value is Array:
		for nested: Variant in value:
			count += _count_true_key_recursive(nested, key_name)
	return count


func _reset_run_state() -> void:
	_timeline.clear()
	_last_result.clear()
	_resource_sequence = 0
	_output_sequence = 0
	_ground_loot_sequence = 0
	_preference_sequence = 0
	_inventory_sequence = 0
	_offer_sequence = 0
	_quest_sequence = 0
	_quest_event_sequence = 0
	_stock_sequence = 0
	_quote_sequence = 0
	_trade_sequence = 0
	_save_result_sequence = 0
	_death_sequence = 0
	_bag_sequence = 0
	_respawn_sequence = 0
	_exhaustion_sequence = 0


func _next_preference_sequence() -> int:
	var value: int = _preference_sequence
	_preference_sequence += 1
	return value


func _next_death_sequence() -> int:
	var value: int = _death_sequence
	_death_sequence += 1
	return value


func _next_respawn_sequence() -> int:
	var value: int = _respawn_sequence
	_respawn_sequence += 1
	return value


func _next_exhaustion_sequence() -> int:
	var value: int = _exhaustion_sequence
	_exhaustion_sequence += 1
	return value


func _position_dict(position: Vector3) -> Dictionary:
	return {"iso_x_m": position.x, "iso_y_m": position.z, "altitude_m": position.y}


func _mouse_button(button_index: int, position: Vector2) -> InputEventMouseButton:
	var event := InputEventMouseButton.new()
	event.button_index = button_index as MouseButton
	event.position = position
	event.global_position = position
	event.pressed = true
	return event


func _wait_physics_frames(count: int) -> void:
	for _index: int in range(count):
		await get_tree().physics_frame


func _wait_process_frames(count: int) -> void:
	for _index: int in range(count):
		await get_tree().process_frame


func _rejected(reason: String) -> Dictionary:
	return {
		"status": "REJECTED",
		"reason": reason,
		"authoritative_roundtrip": false,
		"authority": AUTHORITY,
	}
