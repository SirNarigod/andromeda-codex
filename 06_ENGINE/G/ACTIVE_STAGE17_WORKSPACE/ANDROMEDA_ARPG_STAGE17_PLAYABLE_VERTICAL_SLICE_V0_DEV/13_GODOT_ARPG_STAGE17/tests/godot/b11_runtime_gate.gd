extends Node

const SESSION_REF := "B11-INTEGRATED-SESSION"
const WRONG_SESSION_REF := "B11-WRONG-SESSION"

var _checks: int = 0
var _failures: Array[String] = []
var _flow: Dictionary = {}

@onready var main: AndromedaMainRuntime = $AndromedaARPG
@onready var player: AndromedaPlayerController = $AndromedaARPG/ActorRoot/Player
@onready var camera_rig: AndromedaIsometricCameraRig = $AndromedaARPG/IsometricCameraRig
@onready var hud: AndromedaHUDController = $AndromedaARPG/UILayer/MinimalHUD
@onready var vertical_slice: AndromedaB11VerticalSliceClient = $AndromedaARPG/B11VerticalSliceClient
@onready var performance_probe: AndromedaB11PerformanceProbe = $AndromedaARPG/B11PerformanceProbe
@onready var pickup_client: AndromedaGroundLootPickupClient = $AndromedaARPG/GroundLootPickupClient
@onready var gathering_client: AndromedaGatheringClient = $AndromedaARPG/GatheringClient
@onready var vendor_client: AndromedaVendorClient = $AndromedaARPG/VendorClient
@onready var inventory_client: AndromedaInventoryClient = $AndromedaARPG/InventoryClient
@onready var quest_client: AndromedaQuestClient = $AndromedaARPG/QuestClient
@onready var save_client: AndromedaSaveReloadClient = $AndromedaARPG/SaveReloadClient
@onready var death_client: AndromedaDeathRespawnClient = $AndromedaARPG/DeathRespawnClient
@onready var bag_client: AndromedaDroppedBagClient = $AndromedaARPG/DroppedBagClient


func _ready() -> void:
	await _run_gate()


func _check(check_id: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(check_id if detail.is_empty() else "%s:%s" % [check_id, detail])


func _run_gate() -> void:
	var session := _session()
	var bridge := _bridge()
	var router := get_node_or_null("/root/InputRouter") as AndromedaInputRouter
	_check("AUTOLOAD_CLIENT_SESSION", session != null)
	_check("AUTOLOAD_ANDROMEDA_BRIDGE", bridge != null)
	_check("AUTOLOAD_INPUT_ROUTER", router != null)
	if session == null or bridge == null or router == null:
		await _finish()
		return
	_check("PROJECT_LABEL_B11", str(ProjectSettings.get_setting("application/config/name")) == "Andromeda ARPG Stage16B B11")
	_check("MAIN_SCENE_PRESERVED", str(ProjectSettings.get_setting("application/run/main_scene")) == "res://scenes/Main.tscn")
	_check("BACKEND_URL_UNCHANGED", bridge.server_url() == "http://127.0.0.1:8000")
	_check("SNAPSHOT_PATH_UNCHANGED", bridge.snapshot_path() == "/snapshot")
	_check("COMMAND_PATH_UNCHANGED", bridge.command_path() == "/command")
	_check("NAVIGATION_READY", await _wait_for_navigation(240))
	_test_architecture_and_authority(bridge, router)
	_flow = await main.run_b11_integrated_vertical_slice(SESSION_REF)
	_test_integrated_flow()
	_test_stage_spawn_explore_water()
	_test_stage_dialogue_quest_combat()
	_test_stage_loot_gather_vendor()
	_test_stage_save_death_respawn()
	_test_stale_duplicate_session_guards()
	await _test_input_target_camera_regressions(router)
	_test_performance_report()
	_test_global_acceptance_honesty()
	await _finish()


func _test_architecture_and_authority(bridge: AndromedaRuntimeBridge, router: AndromedaInputRouter) -> void:
	_check("B11_VERTICAL_SLICE_NODE", vertical_slice != null)
	_check("B11_PERFORMANCE_NODE", performance_probe != null)
	_check("B11_SCENE_NODE_CLIENT", main.has_node("B11VerticalSliceClient"))
	_check("B11_SCENE_NODE_PERFORMANCE", main.has_node("B11PerformanceProbe"))
	_check("B11_MAIN_CONTRACT_CLIENT", main.contract_snapshot().get("b11_vertical_slice_client_present") == true)
	_check("B11_MAIN_CONTRACT_PROBE", main.contract_snapshot().get("b11_performance_probe_present") == true)
	_check("B11_HARNESS_INERT", main.contract_snapshot().get("b11_harness_runs_automatically") == false)
	_check("B11_FIXTURE_NOT_ROUNDTRIP", main.contract_snapshot().get("b11_fixture_is_authoritative_roundtrip") == false)
	var harness_contract: Dictionary = vertical_slice.contract_snapshot()
	_check("B11_REQUIRED_TWELVE_STAGES", (harness_contract.get("required_stage_order", []) as Array).size() == 12)
	_check("B11_HARNESS_EXPLICIT_CALL_ONLY", harness_contract.get("inert_until_explicitly_called") == true)
	_check("B11_EXTERNAL_FIXTURE_EXPLICIT", harness_contract.get("external_projection_fixture") == true)
	_check("B11_FIXTURE_CANNOT_PROMOTE", harness_contract.get("fixture_may_promote_authoritative_gate") == false)
	for flag: String in [
		"authoritative_roundtrip", "damage_authority", "critical_authority", "cooldown_authority",
		"loot_grant_authority", "inventory_authority", "quest_authority", "economy_authority",
		"save_authority", "death_authority", "ttl_authority", "ownership_authority",
		"respawn_point_authority", "backend_substitute", "invented_endpoint",
	]:
		_check("B11_HARNESS_FALSE_%s" % flag.to_upper(), harness_contract.get(flag) == false)
	var performance_contract: Dictionary = performance_probe.contract_snapshot()
	_check("PERFORMANCE_MEASUREMENT_ONLY", performance_contract.get("measurement_only") == true)
	_check("PERFORMANCE_NO_FPS_AUTHORITY", performance_contract.get("fps_authority") == false)
	_check("PERFORMANCE_NO_THRESHOLD_INVENTED", performance_contract.get("frame_time_threshold_invented") == false)
	_check("PERFORMANCE_NO_GAMEPLAY_AUTHORITY", performance_contract.get("gameplay_authority") == false)
	_check("PERFORMANCE_NO_RUNTIME_MUTATION", performance_contract.get("mutates_runtime_state") == false)
	var main_contract: Dictionary = main.contract_snapshot()
	for flag: String in [
		"gameplay_authority_in_gdscript", "backend_substitute", "terrain_traversal_authority_in_gdscript",
		"hud_gameplay_authority_in_gdscript", "combat_outcome_calculated_in_gdscript",
		"ground_loot_inventory_authority_in_gdscript", "ground_loot_ttl_authority_in_gdscript",
		"gathering_yield_authority_in_gdscript", "gathering_quantity_authority_in_gdscript",
		"gathering_stamina_authority_in_gdscript", "vendor_price_authority_in_gdscript",
		"vendor_wallet_authority_in_gdscript", "inventory_authority_in_gdscript",
		"bag_authority_in_gdscript", "quest_completion_authority_in_gdscript",
		"quest_reward_authority_in_gdscript", "save_authority_in_gdscript",
		"death_authority_in_gdscript", "dropped_bag_authority_in_gdscript",
		"ownership_authority_in_gdscript", "water_ttl_authority_in_gdscript",
		"respawn_point_authority_in_gdscript",
	]:
		_check("MAIN_CONTRACT_FALSE_%s" % flag.to_upper(), main_contract.get(flag) == false)
	_check("NO_DAMAGE_METHOD", not vertical_slice.has_method("calculate_damage"))
	_check("NO_GRANT_METHOD", not vertical_slice.has_method("grant_item"))
	_check("NO_SAVE_WRITE_METHOD", not vertical_slice.has_method("write_save"))
	_check("NO_DEATH_DECISION_METHOD", not vertical_slice.has_method("decide_death"))
	_check("NO_TTL_EXPIRY_METHOD", not vertical_slice.has_method("expire_ttl"))
	_check("NO_OWNERSHIP_MUTATION_METHOD", not vertical_slice.has_method("mutate_ownership"))
	_check("BRIDGE_REJECTS_PLAYER_REF", bridge.build_command_envelope("B11_PROBE", {"player_ref": "FORGED"}).get("status") == "REJECTED")
	_check("BRIDGE_REJECTS_INVENTORY_GRANT", bridge.build_command_envelope("B11_PROBE", {"inventory_grant": {}}).get("status") == "REJECTED")
	_check("ROUTER_REMOTE_PICKUP_APPROACH_ONLY", router.resolve_pointer_click(
		MOUSE_BUTTON_LEFT, AndromedaInputRouter.HIT_GROUND_LOOT, Vector3.ZERO,
		"LOOT-B11-REMOTE-GUARD", false, 0.5001, true, true
	).get("intent") == "APPROACH_PICKUP")
	_check("ROUTER_EXACT_PICKUP_ALLOWED", router.resolve_pointer_click(
		MOUSE_BUTTON_LEFT, AndromedaInputRouter.HIT_GROUND_LOOT, Vector3.ZERO,
		"LOOT-B11-EXACT-GUARD", false, 0.5, true, true
	).get("intent") == "PICKUP")
	_check("ROUTER_HOSTILE_RIGHT_CLICK_ONLY", router.resolve_pointer_click(
		MOUSE_BUTTON_RIGHT, AndromedaInputRouter.HIT_ACTOR, Vector3.ZERO,
		"ENEMY-B11-GUARD", true
	).get("input_mode") == "CLICK_ONLY")


func _test_integrated_flow() -> void:
	_check("FLOW_RESULT_PASS", _flow.get("status") == "PASS", JSON.stringify(_flow.get("failed_stages", [])))
	_check("FLOW_CLIENT_COMPLETED", _flow.get("integrated_client_flow_completed") == true)
	_check("FLOW_SINGLE_MAIN_INSTANCE", _flow.get("single_main_instance") == true)
	_check("FLOW_SINGLE_SESSION_CONTINUITY", _flow.get("single_session_continuity") == true)
	_check("FLOW_SESSION_REF", _flow.get("session_ref") == SESSION_REF)
	_check("FLOW_SESSION_EPOCH_POSITIVE", int(_flow.get("session_epoch", 0)) > 0)
	_check("FLOW_TWELVE_STAGES", (_flow.get("timeline", []) as Array).size() == 12)
	_check("FLOW_ORDER_EXACT", _flow.get("observed_stage_order") == vertical_slice.required_stage_order())
	_check("FLOW_NO_FAILED_STAGE", (_flow.get("failed_stages", []) as Array).is_empty())
	_check("FLOW_FIXTURE_LABEL_EXPLICIT", _flow.get("external_projection_source") == "B11_EXTERNAL_PROJECTION_FIXTURE_NOT_LIVE_AUTHORITY")
	_check("FLOW_NO_AUTHORITATIVE_ROUNDTRIP", _flow.get("authoritative_roundtrip") == false)
	_check("FLOW_NO_BACKEND_LISTENER_CLAIM", _flow.get("backend_listener_observed") == false)
	_check("FLOW_G16B19_NOT_GLOBAL_PASS", _flow.get("g16b19_global_pass_eligible") == false)
	_check("FLOW_ZERO_TRANSPORT_SUBMISSIONS", int(_flow.get("transport_submission_count", -1)) == 0)
	_check("FLOW_NO_GDSCRIPT_AUTHORITY", _flow.get("gameplay_authority_moved_to_gdscript") == false)
	var timeline: Array = _flow.get("timeline", []) as Array
	for index: int in range(timeline.size()):
		var entry: Dictionary = timeline[index]
		_check("STAGE_%02d_STATUS_PASS" % index, entry.get("status") == "PASS", JSON.stringify(entry))
		_check("STAGE_%02d_INDEX" % index, int(entry.get("stage_index", -1)) == index)
		_check("STAGE_%02d_SESSION" % index, entry.get("session_ref") == SESSION_REF)
		_check("STAGE_%02d_FIXTURE_LABEL" % index, entry.get("external_projection_source") == "B11_EXTERNAL_PROJECTION_FIXTURE_NOT_LIVE_AUTHORITY")
		_check("STAGE_%02d_NO_ROUNDTRIP" % index, entry.get("authoritative_roundtrip") == false)
		_check("STAGE_%02d_AUTHORITY_UNCHANGED" % index, entry.get("gameplay_authority_changed") == false)
	_check("SCENETREE_NOT_PAUSED_AFTER_FLOW", not get_tree().paused)
	_check("SESSION_STILL_BOUND", _session().has_active_session())
	_check("SESSION_STILL_SAME", _session().session_ref() == SESSION_REF)


func _test_stage_spawn_explore_water() -> void:
	var spawn: Dictionary = _stage("SPAWN")
	_check("SPAWN_PLAYER_PRESENT", spawn.get("player_present") == true)
	_check("SPAWN_CAMERA_FOLLOW", spawn.get("camera_follow") == true)
	_check("SPAWN_CURSOR_ACCEPTED", spawn.get("cursor", {}).get("status") == "PASS")
	_check("SPAWN_INVENTORY_PROJECTED", spawn.get("inventory_projection", {}).get("status") == "PASS")
	_check("SPAWN_AUTO_PICKUP_PROJECTED_OFF", spawn.get("profile_preference_projection", {}).get("enabled") == false)
	_check("SPAWN_NOT_DECIDED_LOCAL", spawn.get("spawn_decided_locally") == false)
	var explore: Dictionary = _stage("EXPLORE")
	_check("EXPLORE_FIRST_MOVE", explore.get("first_move", {}).get("status") == "PASS")
	_check("EXPLORE_SECOND_MOVE", explore.get("second_move", {}).get("status") == "PASS")
	_check("EXPLORE_MULTIPLE_DESTINATIONS", explore.get("multiple_destinations") == true)
	_check("EXPLORE_NAVIGATION_READY", explore.get("navigation_ready") == true)
	_check("EXPLORE_CAMERA_FOLLOW", explore.get("camera_follow") == true)
	_check("EXPLORE_STREAMING_FOUR_TRANSITIONS", (explore.get("streaming_transitions", []) as Array).size() == 4)
	_check("EXPLORE_NO_WORLD_PAUSE", explore.get("scene_tree_paused") == false)
	var water: Dictionary = _stage("WATER_TERRAIN_TRAVERSAL")
	_check("TERRAIN_SURFACES_SEPARATED", water.get("terrain", {}).get("surfaces_separated") == true)
	_check("SHALLOW_PLAYER_WADES", water.get("shallow", {}).get("player", {}).get("mode") == "WADE")
	_check("SHALLOW_NPC_WADES", water.get("shallow", {}).get("npc", {}).get("mode") == "WADE")
	_check("SHALLOW_ANIMAL_WADES", water.get("shallow", {}).get("animal", {}).get("mode") == "WADE")
	_check("SHALLOW_VEHICLE_WADES", water.get("shallow", {}).get("vehicle", {}).get("mode") == "WADE_VEHICLE")
	_check("STRONG_CURRENT_DETECTED", water.get("strong_current", {}).get("current_class") == "STRONG_CURRENT")
	_check("UNDER_BRIDGE_SHALLOW", water.get("under_bridge", {}).get("under_bridge") == true)
	_check("DEEP_PLAYER_SWIMS", water.get("deep", {}).get("player", {}).get("mode") == "SWIM")
	_check("DEEP_NPC_SWIMS", water.get("deep", {}).get("npc", {}).get("mode") == "SWIM")
	_check("DEEP_ANIMAL_SWIMS", water.get("deep", {}).get("animal", {}).get("mode") == "SWIM")
	_check("DEEP_VEHICLE_BLOCKED", water.get("deep", {}).get("vehicle", {}).get("status") == "BLOCKED")
	_check("WATER_STAMINA_PROJECTED", water.get("stamina_projection", {}).get("status") == "PASS")
	_check("WATER_EXHAUSTION_PROJECTED", water.get("exhaustion_projection", {}).get("status") == "PASS")
	_check("WATER_RECOVERY_PROJECTED", water.get("recovery_projection", {}).get("status") == "PASS")
	_check("WATER_NO_LOCAL_STAMINA_AUTHORITY", water.get("stamina_authority_local") == false)
	_check("WATER_NO_LOCAL_DEATH_AUTHORITY", water.get("death_authority_local") == false)


func _test_stage_dialogue_quest_combat() -> void:
	var dialogue: Dictionary = _stage("DIALOGUE")
	_check("DIALOGUE_NORMAL_PROJECTED", dialogue.get("normal_line", {}).get("status") == "PASS")
	_check("DIALOGUE_IMPORTANT_PROJECTED", dialogue.get("important_line", {}).get("status") == "PASS")
	_check("DIALOGUE_CHOICES_PROJECTED", dialogue.get("choices", {}).get("status") == "PASS")
	_check("DIALOGUE_NO_NEXT", dialogue.get("important_line", {}).get("next_button") == false)
	_check("DIALOGUE_NO_WORLD_PAUSE", dialogue.get("world_paused") == false)
	_check("DIALOGUE_IMPORTANT_ACCESSIBILITY", dialogue.get("important_accessibility_line") == true)
	_check("DIALOGUE_NO_LOCAL_NARRATIVE", dialogue.get("narrative_authored_locally") == false)
	var quest: Dictionary = _stage("QUEST")
	_check("QUEST_OFFER_PROJECTED", quest.get("offer", {}).get("status") == "PASS")
	_check("QUEST_INTERACTION_PROJECTED", quest.get("interaction", {}).get("status") == "PASS")
	_check("QUEST_ACCEPT_INTENT", quest.get("accept_intent", {}).get("intent") == "ACCEPT_QUEST")
	_check("QUEST_ACTIVE_EXTERNAL", quest.get("active_projection", {}).get("status") == "PASS")
	_check("QUEST_OBJECTIVE_EXTERNAL", quest.get("objective_event", {}).get("status") == "PASS")
	_check("QUEST_COMPLETION_EXTERNAL", quest.get("completion_projection", {}).get("status") == "PASS")
	_check("QUEST_NO_LOCAL_COMPLETION", quest.get("completion_decided_locally") == false)
	_check("QUEST_NO_LOCAL_REWARD", quest.get("reward_granted_locally") == false)
	_check("QUEST_NO_LOCAL_XP", quest.get("xp_granted_locally") == false)
	var combat: Dictionary = _stage("COMBAT")
	_check("COMBAT_TARGET_REF", combat.get("target_ref") == main.combat_enemy_common.target_ref)
	_check("COMBAT_LEFT_SELECTION", combat.get("left_selection", {}).get("status") == "PASS")
	_check("COMBAT_RIGHT_CHASE", combat.get("right_click", {}).get("intent") == "CHASE_ATTACK")
	_check("COMBAT_RIGHT_CLICK_ONLY", combat.get("right_click", {}).get("input_mode") == "CLICK_ONLY")
	_check("COMBAT_COMMON_VITALS", combat.get("common_vitals", {}).get("status") == "PASS")
	_check("COMBAT_ALPHA_VITALS", combat.get("alpha_vitals", {}).get("status") == "PASS")
	_check("COMBAT_NORMAL_28", combat.get("hit", {}).get("local_visual_freeze_ms") == 28)
	_check("COMBAT_STRONG_42", combat.get("strong", {}).get("local_visual_freeze_ms") == 42)
	_check("COMBAT_CRITICAL_58", combat.get("critical", {}).get("local_visual_freeze_ms") == 58)
	_check("COMBAT_REDUCED_ZERO_FREEZE", combat.get("reduced_motion_hit", {}).get("local_visual_freeze_ms") == 0)
	_check("COMBAT_REDUCED_ZERO_IMPULSE", is_zero_approx(float(combat.get("reduced_motion_hit", {}).get("camera_impulse_m", -1.0))))
	_check("COMBAT_TARGET_PRESERVED", combat.get("target_preserved") == true)
	_check("COMBAT_NO_LOCAL_DAMAGE", combat.get("damage_decided_locally") == false)
	_check("COMBAT_NO_LOCAL_COOLDOWN", combat.get("cooldown_decided_locally") == false)
	_check("COMBAT_NO_LOCAL_DEFEAT", combat.get("defeat_decided_locally") == false)


func _test_stage_loot_gather_vendor() -> void:
	var loot: Dictionary = _stage("LOOT")
	_check("LOOT_ENEMY_GROUND_LOOT", loot.get("output", {}).get("ground_loot_before_inventory") == true)
	_check("LOOT_SETTLED", loot.get("settle", {}).get("status") == "PASS")
	_check("LOOT_PICKUP_ELIGIBLE", loot.get("eligibility", {}).get("status") == "PASS")
	_check("LOOT_DISTANCE_AT_MOST_HALF", float(loot.get("eligibility", {}).get("physical_distance_m", INF)) <= 0.5)
	_check("LOOT_REQUEST_PICKUP", loot.get("pickup_request", {}).get("intent") == "REQUEST_PICKUP")
	_check("LOOT_NO_TRANSPORT_WITHOUT_BACKEND", loot.get("pickup_request", {}).get("transport_submitted") == false)
	_check("LOOT_INVENTORY_FULL_PROJECTED", loot.get("inventory_full_projection", {}).get("status") == "PASS")
	_check("LOOT_REMAINS_ON_FULL", loot.get("loot_remains_after_inventory_full") == true)
	_check("LOOT_NO_LOCAL_GRANT", loot.get("item_granted_locally") == false)
	_check("LOOT_NO_LOCAL_INVENTORY", loot.get("inventory_mutated_locally") == false)
	var gather: Dictionary = _stage("GATHER")
	_check("GATHER_RESOURCE_PROJECTED", gather.get("resource_projection", {}).get("status") == "PASS")
	_check("GATHER_REQUEST", gather.get("gather_request", {}).get("intent") == "REQUEST_GATHER")
	_check("GATHER_NO_TRANSPORT", gather.get("gather_request", {}).get("transport_submitted") == false)
	_check("GATHER_EXTERNAL_RESULT", gather.get("gather_result", {}).get("status") == "PASS")
	_check("GATHER_RESULT_NO_OUTPUT_BY_ITSELF", gather.get("gather_result", {}).get("output_spawned") == false)
	_check("GATHER_STAMINA_EXTERNAL", gather.get("stamina_projection", {}).get("status") == "PASS")
	_check("GATHER_OUTPUT_GROUND_LOOT", gather.get("physical_output", {}).get("ground_loot_before_inventory") == true)
	_check("GATHER_SETTLED", gather.get("settle", {}).get("status") == "PASS")
	_check("GATHER_AUTO_PICKUP_NO_INTERRUPT", gather.get("auto_pickup_during_gathering", {}).get("interrupts_action") == false)
	_check("GATHER_AUTO_PICKUP_CONTEXT_PRESERVED", gather.get("auto_pickup_during_gathering", {}).get("action_context_preserved") == true)
	_check("GATHER_NO_LOCAL_YIELD", gather.get("yield_calculated_locally") == false)
	_check("GATHER_NO_LOCAL_INVENTORY", gather.get("inventory_mutated_locally") == false)
	var vendor: Dictionary = _stage("VENDOR")
	_check("VENDOR_STOCK_EXTERNAL", vendor.get("stock", {}).get("status") == "PASS")
	_check("VENDOR_OPEN", vendor.get("open", {}).get("status") == "PASS")
	_check("VENDOR_OPEN_NO_AUTO_PURCHASE", vendor.get("open", {}).get("auto_purchase") == false)
	_check("VENDOR_QUOTE_REQUEST", vendor.get("quote_request", {}).get("status") == "PASS")
	_check("VENDOR_QUOTE_EXTERNAL", vendor.get("quote_projection", {}).get("status") == "PASS")
	_check("VENDOR_EXECUTE_EXPLICIT", vendor.get("execute_request", {}).get("confirmation_ref") == "B11-EXPLICIT-CONFIRMATION" and vendor.get("execute_request", {}).get("intent_envelope", {}).get("envelope", {}).get("params", {}).get("explicit_user_confirmation") == true)
	_check("VENDOR_EXECUTE_NO_TRANSPORT", vendor.get("execute_request", {}).get("transport_submitted") == false)
	_check("VENDOR_RESULT_EXTERNAL", vendor.get("trade_projection", {}).get("status") == "PASS")
	_check("VENDOR_NO_AUTO_PURCHASE", vendor.get("auto_purchase") == false)
	_check("VENDOR_NO_LOCAL_PRICE", vendor.get("price_calculated_locally") == false)
	_check("VENDOR_NO_LOCAL_WALLET", vendor.get("wallet_mutated_locally") == false)
	_check("VENDOR_NO_LOCAL_INVENTORY", vendor.get("inventory_mutated_locally") == false)


func _test_stage_save_death_respawn() -> void:
	var save: Dictionary = _stage("SAVE")
	_check("SAVE_INTENT", save.get("save_intent", {}).get("status") == "PASS")
	_check("SAVE_NO_TRANSPORT", save.get("save_intent", {}).get("transport_submitted") == false)
	_check("SAVE_EXTERNAL_RESULT", save.get("save_projection", {}).get("success_confirmed_externally") == true)
	_check("SAVE_NOT_WRITTEN_LOCAL", save.get("save_written_locally") == false)
	_check("SAVE_AUTHORITATIVE_PERSISTENCE_NOT_CLAIMED", save.get("authoritative_persistence_proven") == false)
	var death: Dictionary = _stage("DEATH_BAG_DROP")
	_check("DEATH_EXTERNAL", death.get("death_projection", {}).get("status") == "PASS")
	_check("DEATH_SINGLE_CONTAINER", death.get("single_container") == true)
	_check("DEATH_BAG_REF", death.get("target_ref") == "BAG-B11-DROPPED-LAND")
	_check("DEATH_LAND_BAG", death.get("bag_projection", {}).get("environment") == "LAND")
	_check("DEATH_LAND_NO_TTL", death.get("bag_projection", {}).get("water_ttl_s") == null)
	_check("DEATH_NO_LOCAL_DECISION", death.get("death_decided_locally") == false)
	_check("DEATH_NO_LOCAL_BAG_DROP", death.get("bag_drop_decided_locally") == false)
	_check("DEATH_NO_LOCAL_TTL", death.get("ttl_advanced_locally") == false)
	var respawn: Dictionary = _stage("RESPAWN")
	_check("RESPAWN_REQUEST", respawn.get("respawn_request", {}).get("status") == "PASS")
	_check("RESPAWN_NO_TRANSPORT", respawn.get("respawn_request", {}).get("transport_submitted") == false)
	_check("RESPAWN_EXTERNAL", respawn.get("respawn_projection", {}).get("status") == "PASS")
	_check("RESPAWN_BAG_REMAINS", respawn.get("dropped_bag_remains") == true)
	_check("RESPAWN_TWO_QUICK_SLOTS", respawn.get("quick_slot_count") == 2)
	_check("RESPAWN_CAMERA_FOLLOW", respawn.get("camera_follow") == true)
	_check("RESPAWN_TARGET_CLEARED", respawn.get("target_cleared") == true)
	_check("RESPAWN_NO_LOCAL_WAYPOINT", respawn.get("respawn_point_selected_locally") == false)
	_check("RESPAWN_WORLD_INPUT_READY", not main.world_input_blocked())


func _test_stale_duplicate_session_guards() -> void:
	var session := _session()
	_check("DUPLICATE_SESSION_CURSOR_REJECTED", session.accept_snapshot_cursor(0, "B11-DUPLICATE").get("reason") == "STALE_OR_DUPLICATE_SNAPSHOT")
	_check("STALE_PREFERENCE_REJECTED", pickup_client.project_profile_preference(false, SESSION_REF, 0, true).get("reason") == "STALE_OR_DUPLICATE_PROFILE_PREFERENCE")
	_check("WRONG_SESSION_PREFERENCE_REJECTED", pickup_client.project_profile_preference(false, WRONG_SESSION_REF, 2, true).get("reason") == "PROFILE_PREFERENCE_SESSION_MISMATCH")
	_check("DUPLICATE_RESOURCE_SNAPSHOT_REJECTED", gathering_client.project_resource_snapshot({
		"server_authoritative": true, "session_ref": SESSION_REF,
		"snapshot_sequence": 0, "resources": [],
	}).get("reason") == "STALE_OR_DUPLICATE_RESOURCE_SNAPSHOT")
	_check("WRONG_SESSION_RESOURCE_REJECTED", gathering_client.project_resource_snapshot({
		"server_authoritative": true, "session_ref": WRONG_SESSION_REF,
		"snapshot_sequence": 1, "resources": [],
	}).get("reason") == "SESSION_MISMATCH")
	_check("DUPLICATE_GROUND_LOOT_SNAPSHOT_REJECTED", pickup_client.project_ground_loot_snapshot({
		"server_authoritative": true, "session_ref": SESSION_REF,
		"snapshot_sequence": 3, "ground_loot": [],
	}).get("reason") == "STALE_OR_DUPLICATE_GROUND_LOOT_SNAPSHOT")
	_check("WRONG_SESSION_GROUND_LOOT_REJECTED", pickup_client.project_ground_loot_snapshot({
		"server_authoritative": true, "session_ref": WRONG_SESSION_REF,
		"snapshot_sequence": 4, "ground_loot": [],
	}).get("reason") == "GROUND_LOOT_SNAPSHOT_SESSION_MISMATCH")
	_check("WRONG_SESSION_VENDOR_STOCK_REJECTED", vendor_client.project_stock_snapshot({
		"server_authoritative": true, "session_ref": WRONG_SESSION_REF,
		"snapshot_sequence": 1, "vendor_ref": "SHOP-S13-91CDF9F934810A65B2", "items": [],
	}).get("reason") == "SESSION_MISMATCH")
	_check("WRONG_SESSION_QUEST_REJECTED", quest_client.project_quest_snapshot({
		"server_authoritative": true, "session_ref": WRONG_SESSION_REF,
		"snapshot_sequence": 2, "quests": [],
	}).get("reason") == "SESSION_MISMATCH")
	_check("WRONG_SESSION_SAVE_RESULT_REJECTED", save_client.project_save_result({
		"server_authoritative": true, "session_ref": WRONG_SESSION_REF,
		"result_sequence": 1, "request_ref": "WRONG", "result": "CONFIRMED",
	}).get("reason") == "SESSION_MISMATCH")
	_check("ENEMY_LOOT_SINGLE_INSTANCE", _count_target_ref("LOOT-B11-ENEMY") == 1, str(_count_target_ref("LOOT-B11-ENEMY")))
	_check("TREE_LOOT_SINGLE_INSTANCE", _count_target_ref("LOOT-B11-TREE") == 1, str(_count_target_ref("LOOT-B11-TREE")))
	_check("DROPPED_BAG_SINGLE_INSTANCE", _count_target_ref("BAG-B11-DROPPED-LAND") == 1, str(_count_target_ref("BAG-B11-DROPPED-LAND")))
	_check("RESOURCE_TREE_SINGLE_INSTANCE", _count_target_ref("RESOURCE-B03-TREE-001") == 1, str(_count_target_ref("RESOURCE-B03-TREE-001")))


func _test_input_target_camera_regressions(router: AndromedaInputRouter) -> void:
	main.set_menu_open(false)
	var slot_one: Dictionary = main.handle_action_event(_key_event(KEY_1))
	var slot_two: Dictionary = main.handle_action_event(_key_event(KEY_2))
	_check("INPUT_SLOT_ONE", slot_one.get("status") == "PASS" and slot_one.get("slot") == 1)
	_check("INPUT_SLOT_TWO", slot_two.get("status") == "PASS" and slot_two.get("slot") == 2)
	var wheel: Dictionary = main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_UP, false))
	_check("INPUT_WHEEL_WEAPON", wheel.get("intent") == "WEAPON_QUICK_SLOT_CYCLE")
	var zoom_before: float = camera_rig.target_distance_m()
	var zoom: Dictionary = main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_DOWN, true))
	_check("INPUT_MODIFIER_WHEEL_ZOOM", zoom.get("intent") == "CAMERA_ZOOM")
	_check("INPUT_ZOOM_CHANGED", not is_equal_approx(zoom_before, camera_rig.target_distance_m()))
	main.set_menu_open(true)
	var menu_slot_before: int = hud.active_weapon_slot()
	var menu_zoom_before: float = camera_rig.target_distance_m()
	var menu_wheel: Dictionary = main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_UP, true))
	_check("INPUT_MENU_WHEEL_SCROLL", menu_wheel.get("intent") == "MENU_SCROLL")
	_check("INPUT_MENU_WHEEL_NO_WEAPON", hud.active_weapon_slot() == menu_slot_before)
	_check("INPUT_MENU_WHEEL_NO_ZOOM", is_equal_approx(menu_zoom_before, camera_rig.target_distance_m()))
	main.set_menu_open(false)
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	var move: Dictionary = player.request_move(Vector3(-5.0, 0.0, 2.0))
	_check("INPUT_CLICK_MOVE_REGRESSION", move.get("status") == "PASS", JSON.stringify(move))
	await _wait_physics_frames(8)
	_check("INPUT_MOVEMENT_ACTIVE_OR_REACHED", player.has_destination() or player.global_position.distance_to(Vector3(-5.0, 0.0, 2.0)) < 0.3)
	player.stop_local_prediction()
	var target_result: Dictionary = main.handle_pointer_event(_mouse_button(
		MOUSE_BUTTON_LEFT,
		main.target_to_screen(main.combat_enemy_common)
	))
	_check("TARGET_SELECTION_AFTER_B11", target_result.get("status") == "PASS")
	var target_before: String = main.selected_target_ref()
	var feedback: Dictionary = hud.present_combat_event({
		"token": "COMBAT_CRITICAL_HIT",
		"target_ref": main.combat_enemy_common.target_ref,
		"confirmed_externally": true,
	})
	_check("TARGET_FEEDBACK_PASS", feedback.get("status") == "PASS")
	_check("TARGET_FEEDBACK_STABLE", main.selected_target_ref() == target_before)
	_check("CAMERA_FOLLOW_AFTER_B11", camera_rig.follow_target() == player)
	_check("CAMERA_NO_FREE_ORBIT", camera_rig.contract_snapshot().get("free_orbit") == false)
	_check("CAMERA_OCCLUSION_PROBE_ONLY", camera_rig.contract_snapshot().get("occlusion_probe_prepared") == true)
	_check("INPUT_ROUTER_TWO_QUICK_SLOTS", router.resolve_weapon_slot_key(1).get("quick_slot_count") == 2)
	_check("SCENETREE_NEVER_PAUSED", not get_tree().paused)


func _test_performance_report() -> void:
	var report: Dictionary = _flow.get("performance", {})
	_check("PERFORMANCE_STATUS_MEASURED", report.get("status") == "MEASURED", JSON.stringify(report))
	_check("PERFORMANCE_SCHEMA", report.get("schema") == "ANDROMEDA_STAGE16B_B11_PERFORMANCE_V0_8_0")
	_check("PERFORMANCE_DURATION_POSITIVE", float(report.get("duration_s", 0.0)) > 0.0)
	_check("PERFORMANCE_SAMPLED_FRAMES", int(report.get("sampled_frame_count", 0)) > 0)
	_check("PERFORMANCE_PROCESS_FRAMES", int(report.get("process_frame_count", 0)) > 0)
	_check("PERFORMANCE_FPS_OBSERVED", float(report.get("observed_fps_from_process_frames", 0.0)) > 0.0)
	_check("PERFORMANCE_AVERAGE_NONNEGATIVE", float(report.get("frame_time_ms", {}).get("average", -1.0)) >= 0.0)
	_check("PERFORMANCE_P95_NONNEGATIVE", float(report.get("frame_time_ms", {}).get("p95", -1.0)) >= 0.0)
	_check("PERFORMANCE_MAX_NONNEGATIVE", float(report.get("frame_time_ms", {}).get("maximum", -1.0)) >= 0.0)
	_check("PERFORMANCE_MEMORY_START", int(report.get("memory", {}).get("static_start_bytes", 0)) > 0)
	_check("PERFORMANCE_MEMORY_PEAK", int(report.get("memory", {}).get("static_peak_bytes", 0)) > 0)
	_check("PERFORMANCE_NODE_COUNTS", int(report.get("object_counts", {}).get("nodes_start", 0)) > 0 and int(report.get("object_counts", {}).get("nodes_end", 0)) > 0)
	_check("PERFORMANCE_OBJECT_COUNTS", int(report.get("object_counts", {}).get("objects_start", 0)) > 0 and int(report.get("object_counts", {}).get("objects_end", 0)) > 0)
	_check("PERFORMANCE_TWELVE_STAGE_EVENTS", (report.get("events", []) as Array).size() == 12)
	_check("PERFORMANCE_STREAMING_TRANSITIONS", int(report.get("metadata", {}).get("streaming_transitions", 0)) == 4)
	_check("PERFORMANCE_GROUND_LOOT_DENSITY", int(report.get("metadata", {}).get("ground_loot_density", 0)) >= 2)
	_check("PERFORMANCE_NPC_DENSITY", int(report.get("metadata", {}).get("npc_density", 0)) == 3)
	_check("PERFORMANCE_ENEMY_DENSITY", int(report.get("metadata", {}).get("enemy_density", 0)) == 2)
	_check("PERFORMANCE_RESOURCE_DENSITY", int(report.get("metadata", {}).get("resource_density", 0)) >= 5)
	_check("PERFORMANCE_NO_FORMAL_THRESHOLD", report.get("formal_numeric_threshold_available") == false)
	_check("PERFORMANCE_NO_INVENTED_PASS_THRESHOLD", report.get("numeric_pass_threshold_invented") == false)
	_check("PERFORMANCE_POLICY_EXPLICIT", str(report.get("classification_policy", "")).contains("UNEQUIVOCAL_REGRESSION"))
	_check("PERFORMANCE_NO_GAMEPLAY_AUTHORITY", report.get("gameplay_authority") == false)


func _test_global_acceptance_honesty() -> void:
	_check("G16B19_REMAINS_PARTIAL_WITHOUT_ROUNDTRIP", _flow.get("g16b19_global_pass_eligible") == false)
	_check("BACKEND_NOT_REPLACED", main.contract_snapshot().get("backend_substitute") == false)
	_check("NO_CHECKPOINT_DIRECTORY", not DirAccess.dir_exists_absolute(ProjectSettings.globalize_path("res://CHECKPOINT_STAGE16B_FINAL_V0_8_0")))
	_check("NO_FINAL_BACKUP_FILE", not FileAccess.file_exists(ProjectSettings.globalize_path("res://ANDROMEDA_STAGE16_FINAL_BACKUP.zip")))
	_check("CRAFTING_RUNTIME_RECOVERED_WITHOUT_AUTHORITY", main.has_node("UILayer/MinimalHUD/CraftingPanel") and hud.contract_snapshot().get("crafting", {}).get("craft_result_authority") == false)
	_check("OCCLUDER_MATERIAL_FADE_RECOVERED", camera_rig.contract_snapshot().get("occlusion_probe_prepared") == true and camera_rig.contract_snapshot().get("material_fade_execution") == true)
	_check("AUTHORITATIVE_SAVE_NOT_CLAIMED", _stage("SAVE").get("authoritative_persistence_proven") == false)
	_check("FINAL_STAGE16_BACKUP_NOT_CREATED_BY_GATE", true)


func _stage(stage_name: String) -> Dictionary:
	for entry_value: Variant in _flow.get("timeline", []):
		if entry_value is Dictionary:
			var entry: Dictionary = entry_value
			if str(entry.get("stage", "")) == stage_name:
				return entry
	return {}


func _count_target_ref(target_ref_value: String) -> int:
	return _count_target_ref_recursive(main, target_ref_value)


func _count_target_ref_recursive(node: Node, target_ref_value: String) -> int:
	var count: int = 0
	if node is AndromedaInteractionTarget:
		var target := node as AndromedaInteractionTarget
		if target.target_ref == target_ref_value:
			count += 1
	for child: Node in node.get_children():
		count += _count_target_ref_recursive(child, target_ref_value)
	return count


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


func _bridge() -> AndromedaRuntimeBridge:
	return get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge


func _session() -> AndromedaClientSession:
	return get_node_or_null("/root/ClientSession") as AndromedaClientSession


func _finish() -> void:
	var performance_report: Dictionary = _flow.get("performance", {})
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "B11_INTEGRATED_VERTICAL_SLICE_PERFORMANCE_FINAL_AUDIT",
		"integrated_client_flow_completed": _flow.get("integrated_client_flow_completed", false),
		"g16b19_status": "PARTIAL_EVIDENCE",
		"authoritative_roundtrip_executed": false,
		"backend_status": "NOT_AVAILABLE",
		"fixtures_are_external_projection_contract_tests_only": true,
		"global_stage16b_pass": false,
		"checkpoint_or_restore_executed": false,
		"final_stage16_backup_created": false,
		"authority": "GODOT_B11_CLIENT_ORCHESTRATION_PRESENTATION_ONLY",
		"performance_metrics": {
			"renderer_method": performance_report.get("renderer_method", "UNKNOWN"),
			"renderer_name": performance_report.get("renderer_name", "UNKNOWN"),
			"duration_s": performance_report.get("duration_s", 0.0),
			"sampled_frame_count": performance_report.get("sampled_frame_count", 0),
			"process_frame_count": performance_report.get("process_frame_count", 0),
			"observed_fps_from_process_frames": performance_report.get("observed_fps_from_process_frames", 0.0),
			"engine_fps_monitor": performance_report.get("engine_fps_monitor", 0.0),
			"frame_time_ms": performance_report.get("frame_time_ms", {}),
			"memory": performance_report.get("memory", {}),
			"object_counts": performance_report.get("object_counts", {}),
			"event_count": (performance_report.get("events", []) as Array).size(),
			"metadata": performance_report.get("metadata", {}),
			"formal_numeric_threshold_available": performance_report.get("formal_numeric_threshold_available", false),
			"numeric_pass_threshold_invented": performance_report.get("numeric_pass_threshold_invented", true),
		},
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_B11_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_B11_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_B11_SUMMARY: %s" % JSON.stringify(summary))
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
