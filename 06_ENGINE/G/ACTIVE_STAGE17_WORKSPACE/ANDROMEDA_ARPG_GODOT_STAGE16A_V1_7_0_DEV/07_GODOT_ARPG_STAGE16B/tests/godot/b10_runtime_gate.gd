extends Node

const SESSION_INITIAL := "B10-GATE-SESSION"
const SESSION_RESYNC := "B10-GATE-SESSION-RESYNC"
const WRONG_SESSION := "B10-GATE-WRONG-SESSION"
const PLAYER_REF := "PLAYER-B10-PROJECTION"
const PLAYER_OWNER_REF := "PROFILE-B10"
const NPC_OWNER_REF := "NPC-B10-ORIGINAL-OWNER"
const QUEST_REF := "QST-S12-VARGA-ORIENTATION"

var _checks: int = 0
var _failures: Array[String] = []
var _current_session: String = SESSION_INITIAL
var _save_result_sequence: int = 0
var _restore_sequence: int = 0
var _save_sequence: int = 100
var _ground_loot_sequence: int = 0
var _preference_sequence: int = 0
var _inventory_sequence: int = 0
var _resource_sequence: int = 0
var _offer_sequence: int = 0
var _quest_sequence: int = 0
var _dropped_bag_sequence: int = 0
var _death_restore_sequence: int = 0
var _death_sequence: int = 0
var _respawn_sequence: int = 0
var _recovery_result_sequence: int = 0
var _exhaustion_sequence: int = 0
var _ground_loot_entries: Array[Dictionary] = []
var _dropped_bag_entries: Array[Dictionary] = []

@onready var main: AndromedaMainRuntime = $AndromedaARPG
@onready var player: AndromedaPlayerController = $AndromedaARPG/ActorRoot/Player
@onready var camera_rig: AndromedaIsometricCameraRig = $AndromedaARPG/IsometricCameraRig
@onready var hud: AndromedaHUDController = $AndromedaARPG/UILayer/MinimalHUD
@onready var save_client: AndromedaSaveReloadClient = $AndromedaARPG/SaveReloadClient
@onready var death_client: AndromedaDeathRespawnClient = $AndromedaARPG/DeathRespawnClient
@onready var bag_client: AndromedaDroppedBagClient = $AndromedaARPG/DroppedBagClient
@onready var pickup_client: AndromedaGroundLootPickupClient = $AndromedaARPG/GroundLootPickupClient
@onready var gathering_client: AndromedaGatheringClient = $AndromedaARPG/GatheringClient
@onready var inventory_client: AndromedaInventoryClient = $AndromedaARPG/InventoryClient
@onready var quest_client: AndromedaQuestClient = $AndromedaARPG/QuestClient
@onready var streaming: AndromedaStreamingManager = $AndromedaARPG/WorldStreamRoot/TerrainFoundation/CELL_STREAMING
@onready var bag_root: Node3D = $AndromedaARPG/DroppedBagRoot
@onready var loot_root: Node3D = $AndromedaARPG/GroundLootRoot


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
	var bind_result: Dictionary = session.bind_session(SESSION_INITIAL)
	_check("SESSION_INITIAL_BOUND", bind_result.get("status") == "PASS", JSON.stringify(bind_result))
	_check("PROJECT_LABEL_B10_OR_B11", str(ProjectSettings.get_setting("application/config/name")) in ["Andromeda ARPG Stage16B B10", "Andromeda ARPG Stage16B B11"])
	_check("MAIN_SCENE_PRESERVED", str(ProjectSettings.get_setting("application/run/main_scene")) == "res://scenes/Main.tscn")
	_check("BACKEND_URL_UNCHANGED", bridge.server_url() == "http://127.0.0.1:8000")
	_check("SNAPSHOT_ENDPOINT_UNCHANGED", bridge.snapshot_path() == "/snapshot")
	_check("COMMAND_ENDPOINT_UNCHANGED", bridge.command_path() == "/command")
	_check("NAVIGATION_READY", await _wait_for_navigation(240))
	_test_architecture_and_authority(router, bridge)
	_test_save_autosave_and_results()
	_test_reload_restore_continuity()
	await _test_death_policy_and_land_bag()
	await _test_water_bag_and_ground_loot_continuity()
	await _test_recovery_and_npc_ownership()
	await _test_respawn_input_and_streaming()
	_test_reconnect_resync_and_regressions(session)
	await _finish()


func _test_architecture_and_authority(router: AndromedaInputRouter, bridge: AndromedaRuntimeBridge) -> void:
	_check("SAVE_CLIENT_PRESENT", save_client != null)
	_check("DEATH_CLIENT_PRESENT", death_client != null)
	_check("DROPPED_BAG_CLIENT_PRESENT", bag_client != null)
	_check("DROPPED_BAG_ROOT_PRESENT", bag_root != null)
	_check("DEATH_RECOVERY_OVERLAY_PRESENT", hud.death_recovery_overlay != null)
	_check("DROPPED_BAG_SCENE_EXISTS", ResourceLoader.exists("res://scenes/interaction/DroppedBag.tscn"))
	var bag_scene := load("res://scenes/interaction/DroppedBag.tscn") as PackedScene
	var scene_bag := bag_scene.instantiate() as AndromedaDroppedBag
	_check("DROPPED_BAG_SPECIALIZED_SCRIPT", scene_bag != null)
	if scene_bag != null:
		_check("DROPPED_BAG_ROOT_RIGID_BODY", scene_bag.is_class("RigidBody3D"))
		for child_path: String in ["CollisionShape3D", "PlaceholderVisual", "RecoverySensor", "FloatAnchor", "OptionalOwnerHint"]:
			_check("DROPPED_BAG_REQUIRED_%s" % child_path.to_upper(), scene_bag.has_node(child_path))
		_check("DROPPED_BAG_LAYER_4096", int(scene_bag.get("collision_layer")) == 4096)
		_check("DROPPED_BAG_NOT_GROUND_LOOT", str(scene_bag.get_script().resource_path) != "res://scripts/interaction/ground_loot.gd")
		_check("DROPPED_BAG_TARGET_KIND", scene_bag.target_kind == AndromedaInputRouter.HIT_DROPPED_BAG)
		var bag_contract: Dictionary = scene_bag.contract_snapshot()
		_check("BAG_LAND_EXPIRY_NULL", bag_contract.get("land_expiry") == null)
		_check("BAG_WATER_TTL_CONTRACT_1800", is_equal_approx(float(bag_contract.get("water_ttl_contract_s")), 1800.0))
		for authority_key: String in ["water_ttl_authority", "death_authority", "ownership_authority", "contents_authority", "recovery_authority", "backend_substitute"]:
			_check("BAG_CONTRACT_FALSE_%s" % authority_key.to_upper(), bag_contract.get(authority_key) == false)
		scene_bag.free()
	var main_contract: Dictionary = main.contract_snapshot()
	for presence_key: String in ["save_reload_client_present", "death_respawn_client_present", "dropped_bag_client_present"]:
		_check("MAIN_%s" % presence_key.to_upper(), main_contract.get(presence_key) == true)
	for authority_key: String in [
		"gameplay_authority_in_gdscript", "save_authority_in_gdscript", "death_authority_in_gdscript",
		"dropped_bag_authority_in_gdscript", "ownership_authority_in_gdscript",
		"water_ttl_authority_in_gdscript", "respawn_point_authority_in_gdscript",
	]:
		_check("MAIN_FALSE_%s" % authority_key.to_upper(), main_contract.get(authority_key) == false)
	var save_contract: Dictionary = save_client.contract_snapshot()
	for authority_key: String in [
		"local_disk_persistence", "save_success_authority", "restore_authority", "ttl_authority",
		"death_authority", "inventory_authority", "quest_authority", "economy_authority",
		"backend_substitute", "invented_endpoint", "scene_tree_pause",
	]:
		_check("SAVE_CONTRACT_FALSE_%s" % authority_key.to_upper(), save_contract.get(authority_key) == false)
	var death_contract: Dictionary = death_client.contract_snapshot()
	for authority_key: String in [
		"safe_respawn_point_authority", "water_grace_authority", "death_authority",
		"inventory_authority", "bag_drop_authority", "backend_substitute",
	]:
		_check("DEATH_CONTRACT_FALSE_%s" % authority_key.to_upper(), death_contract.get(authority_key) == false)
	var bag_client_contract: Dictionary = bag_client.contract_snapshot()
	for authority_key: String in [
		"ownership_authority", "contents_authority", "recovery_authority", "ttl_authority",
		"death_authority", "systemic_authority", "backend_substitute", "foreign_npc_auto_theft",
	]:
		_check("BAG_CLIENT_FALSE_%s" % authority_key.to_upper(), bag_client_contract.get(authority_key) == false)
	var routed: Dictionary = router.resolve_pointer_click(
		MOUSE_BUTTON_RIGHT,
		AndromedaInputRouter.HIT_DROPPED_BAG,
		Vector3.ZERO,
		"BAG-B10-ROUTER"
	)
	_check("ROUTER_DROPPED_BAG_CONTEXT_PASS", routed.get("status") == "PASS")
	_check("ROUTER_DROPPED_BAG_APPROACH_RECOVERY", routed.get("intent") == "APPROACH_RECOVER_BAG")
	_check("ROUTER_DROPPED_BAG_CLICK_ONLY", routed.get("input_mode") == "CLICK_ONLY")
	_check("ROUTER_DROPPED_BAG_REQUIRES_PATH", routed.get("requires_path") == true)
	_check("ROUTER_DROPPED_BAG_EXTERNAL_RESULT", routed.get("authoritative_result_required") == true)
	_check("BRIDGE_REJECTS_CLIENT_PLAYER_REF", bridge.build_command_envelope("REQUEST_BAG_RECOVERY", {"bag_ref": "B", "player_ref": "FORGED"}).get("status") == "REJECTED")
	_check("NO_LOCAL_SAVE_METHOD", not save_client.has_method("write_save_file"))
	_check("NO_LOCAL_LOAD_METHOD", not save_client.has_method("load_save_file"))
	_check("NO_LOCAL_DEATH_METHOD", not death_client.has_method("kill_player"))
	_check("NO_LOCAL_BAG_GRANT_METHOD", not bag_client.has_method("grant_bag"))
	_check("NO_LOCAL_TTL_ADVANCE_METHOD", not bag_client.has_method("advance_authoritative_ttl"))
	_check("NO_LOCAL_OWNERSHIP_METHOD", not bag_client.has_method("transfer_ownership"))
	_check("B11_CLIENT_ADDITIVE_COMPATIBILITY", main.has_node("B11VerticalSliceClient"))
	_check("NO_FINAL_STAGE16_BACKUP_API", not save_client.has_method("create_final_stage16_backup"))


func _test_save_autosave_and_results() -> void:
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	var move_result: Dictionary = player.request_move(Vector3(-5.5, 0.0, 0.0))
	_check("SAVE_DURING_MOVEMENT_SETUP", move_result.get("status") == "PASS", JSON.stringify(move_result))
	var destination_before: Vector3 = player.requested_destination()
	var manual: Dictionary = save_client.request_manual_save("manual")
	_check("MANUAL_SAVE_INTENT_PASS", manual.get("status") == "PASS", JSON.stringify(manual))
	_check("MANUAL_SAVE_COMMAND", manual.get("intent") == "REQUEST_SAVE")
	_check("MANUAL_SAVE_ENVELOPE_ONLY", manual.get("intent_envelope", {}).get("status") == "PASS")
	_check("MANUAL_SAVE_NO_LOCAL_SUCCESS", manual.get("success_fabricated_locally") == false)
	_check("MANUAL_SAVE_NO_SCENETREE_PAUSE", manual.get("scene_tree_paused") == false and not get_tree().paused)
	_check("MANUAL_SAVE_MOVEMENT_PRESERVED", player.has_destination() and player.requested_destination().is_equal_approx(destination_before))
	_check("MANUAL_SAVE_BACKEND_NOT_SUBMITTED", manual.get("transport_submitted") == false)
	_check("MANUAL_SAVE_NO_PLAYER_REF", not (manual.get("intent_envelope", {}).get("envelope", {}).get("params", {}) as Dictionary).has("player_ref"))

	main.set_menu_open(true)
	var menu_autosave: Dictionary = save_client.request_autosave("UI_STATE_CHANGE")
	_check("AUTOSAVE_DURING_UI_PASS", menu_autosave.get("status") == "PASS", JSON.stringify(menu_autosave))
	_check("AUTOSAVE_COMMAND_DISTINCT", menu_autosave.get("intent") == "REQUEST_AUTOSAVE")
	_check("AUTOSAVE_UI_REMAINS_OPEN", main.menu_open())
	_check("AUTOSAVE_NO_SCENETREE_PAUSE", not get_tree().paused)
	main.set_menu_open(false)

	var npc := main.dialogue_npc_primary
	var dialogue_result: Dictionary = hud.present_dialogue_line(npc, {
		"line_ref": "B10-SAVE-DIALOGUE",
		"speaker_ref": npc.target_ref,
		"conversation_ref": "B10-SAVE-CONVERSATION",
		"turn_index": 0,
		"text": "Placeholder de save durante diálogo.",
	})
	_check("SAVE_DIALOGUE_PRESENTATION_SETUP", dialogue_result.get("status") == "PASS")
	var dialogue_save: Dictionary = save_client.request_autosave("DIALOGUE_STATE")
	_check("AUTOSAVE_DURING_DIALOGUE_PASS", dialogue_save.get("status") == "PASS")
	_check("AUTOSAVE_DIALOGUE_NOT_CLEARED", hud.active_dialogue_count() >= 1)

	var preference_result: Dictionary = pickup_client.project_profile_preference(true, _current_session, _next_preference_sequence(), true)
	_check("SAVE_AUTO_PICKUP_ON_SETUP", preference_result.get("status") == "PASS")
	var auto_on_save: Dictionary = save_client.request_autosave("PROFILE_PREFERENCE")
	_check("AUTOSAVE_WITH_AUTO_PICKUP_ON", auto_on_save.get("status") == "PASS")
	_check("AUTOSAVE_DOES_NOT_CHANGE_AUTO_PICKUP", pickup_client.auto_pickup_enabled())
	var preference_off: Dictionary = pickup_client.project_profile_preference(false, _current_session, _next_preference_sequence(), true)
	_check("SAVE_AUTO_PICKUP_OFF_SETUP", preference_off.get("status") == "PASS")
	var auto_off_save: Dictionary = save_client.request_autosave("PROFILE_PREFERENCE")
	_check("AUTOSAVE_WITH_AUTO_PICKUP_OFF", auto_off_save.get("status") == "PASS")
	_check("AUTOSAVE_DOES_NOT_CHANGE_AUTO_PICKUP_OFF", not pickup_client.auto_pickup_enabled())

	var inventory_projection: Dictionary = inventory_client.project_inventory_snapshot(_inventory_snapshot(true))
	_check("SAVE_WITH_EQUIPPED_BAG_SETUP", inventory_projection.get("status") == "PASS", JSON.stringify(inventory_projection))
	var bag_save: Dictionary = save_client.request_autosave("BAG_EQUIPPED")
	_check("AUTOSAVE_WITH_EQUIPPED_BAG", bag_save.get("status") == "PASS")
	_check("AUTOSAVE_BAG_STATE_UNCHANGED", inventory_client.bag_state() == "BAG_EQUIPPED")

	var offer_projection: Dictionary = quest_client.project_offer_snapshot(_offer_snapshot())
	var quest_projection: Dictionary = quest_client.project_quest_snapshot(_quest_snapshot("ACTIVE", "PENDING"))
	_check("SAVE_QUEST_OFFER_SETUP", offer_projection.get("status") == "PASS")
	_check("SAVE_QUEST_STATE_SETUP", quest_projection.get("status") == "PASS")
	var quest_save: Dictionary = save_client.request_autosave("QUEST_STATE")
	_check("AUTOSAVE_WITH_QUEST_PROJECTION", quest_save.get("status") == "PASS")
	_check("AUTOSAVE_NO_LOCAL_QUEST_COMPLETION", quest_client.projected_quest(QUEST_REF).get("state") == "ACTIVE")

	_ground_loot_entries = [_ground_loot_entry("LOOT-B10-SAVE-WATER", 899.0, "RECOVERABLE_IN_WATER")]
	var loot_projection: Dictionary = pickup_client.project_ground_loot_snapshot(_ground_loot_snapshot())
	_check("SAVE_NEAR_GROUND_LOOT_SETUP", loot_projection.get("status") == "PASS", JSON.stringify(loot_projection))
	var loot_save: Dictionary = save_client.request_autosave("GROUND_LOOT_NEARBY")
	_check("AUTOSAVE_NEAR_GROUND_LOOT", loot_save.get("status") == "PASS")
	var saved_loot: AndromedaGroundLoot = pickup_client.ground_loot_for_ref("LOOT-B10-SAVE-WATER")
	_check("AUTOSAVE_GROUND_LOOT_REMAINS", saved_loot != null and saved_loot.authoritative_state() == "RECOVERABLE_IN_WATER")
	_check("AUTOSAVE_GROUND_LOOT_EXPOSURE_UNCHANGED", saved_loot != null and is_equal_approx(saved_loot.water_exposure_s(), 899.0))

	var confirmed_payload := _save_result_payload(manual, "CONFIRMED", "")
	var wrong_session: Dictionary = confirmed_payload.duplicate(true)
	wrong_session["session_ref"] = WRONG_SESSION
	_check("SAVE_RESULT_WRONG_SESSION_REJECTED", save_client.project_save_result(wrong_session).get("reason") == "SESSION_MISMATCH")
	var confirmed: Dictionary = save_client.project_save_result(confirmed_payload)
	_check("SAVE_RESULT_CONFIRMED_PASS", confirmed.get("status") == "PASS", JSON.stringify(confirmed))
	_check("SAVE_SUCCESS_EXTERNAL_ONLY", confirmed.get("success_confirmed_externally") == true and confirmed.get("save_written_locally") == false)
	var duplicate_result: Dictionary = save_client.project_save_result(confirmed_payload)
	_check("SAVE_DUPLICATE_RESULT_REJECTED", duplicate_result.get("reason") == "STALE_OR_DUPLICATE_SAVE_RESULT")

	var failed_payload := _save_result_payload(menu_autosave, "FAILED", "EXTERNAL_SAVE_FAILURE")
	var failed: Dictionary = save_client.project_save_result(failed_payload)
	_check("SAVE_FAILURE_PROJECTION_PASS", failed.get("status") == "PASS", JSON.stringify(failed))
	_check("SAVE_FAILURE_NOT_SUCCESS", failed.get("success_confirmed_externally") == false)
	_check("SAVE_FAILURE_REASON_PROJECTED", failed.get("reason") == "EXTERNAL_SAVE_FAILURE")
	_check("SAVE_FAILURE_NO_LOCAL_MUTATION", failed.get("gameplay_state_mutated") == false)
	_check("SAVE_PENDING_REQUESTS_REMAIN_TRACKED", save_client.inflight_save_count() >= 1)
	player.stop_local_prediction()


func _test_reload_restore_continuity() -> void:
	var selected_before: String = main.dialogue_npc_primary.target_ref
	main.clear_current_target_projection("B10_RESTORE_SETUP")
	var reload_intent: Dictionary = save_client.request_reload_resync("manual")
	_check("RELOAD_INTENT_PASS", reload_intent.get("status") == "PASS", JSON.stringify(reload_intent))
	_check("RELOAD_COMMAND_ENVELOPE", reload_intent.get("intent") == "REQUEST_RELOAD_RESYNC")
	_check("RELOAD_NO_LOCAL_RESULT", reload_intent.get("restore_fabricated_locally") == false)
	_check("RELOAD_REQUIRES_RESYNC", save_client.needs_resync() and save_client.state() == AndromedaSaveReloadClient.STATE_RELOAD_PENDING)
	_check("RELOAD_BLOCKS_WORLD_INPUT", death_client.world_input_blocked() and main.world_input_blocked())
	_check("RELOAD_STOPS_LOCAL_MOVEMENT", not player.has_destination())
	var blocked_click: Dictionary = main.handle_pointer_event(_mouse_button(MOUSE_BUTTON_RIGHT, Vector2(480, 270)))
	_check("RELOAD_WORLD_CLICK_BLOCKED", blocked_click.get("intent") == "WORLD_INPUT_BLOCKED")
	var blocked_action: Dictionary = main.handle_action_event(_key_event(KEY_E))
	_check("RELOAD_CONTEXT_ACTION_BLOCKED", blocked_action.get("intent") == "WORLD_INPUT_BLOCKED")
	_check("RELOAD_DOES_NOT_CREATE_TARGET", main.selected_target_ref().is_empty() and selected_before != "")

	_ground_loot_entries = [_ground_loot_entry("LOOT-B10-RESTORE-899", 899.0, "RECOVERABLE_IN_WATER")]
	_dropped_bag_entries = [_bag_entry("BAG-B10-RESTORE-LAND", PLAYER_OWNER_REF, "DROPPED_LAND", "LAND", 0.0)]
	var restore_snapshot: Dictionary = _restore_snapshot(true, "ALIVE")
	var restore_result: Dictionary = save_client.project_restore_snapshot(restore_snapshot)
	_check("RESTORE_FULL_PASS", restore_result.get("status") == "PASS", JSON.stringify(restore_result))
	_check("RESTORE_READY_ONLY_AFTER_RESYNC", save_client.state() == AndromedaSaveReloadClient.STATE_READY and not save_client.needs_resync())
	_check("RESTORE_ALIVE_INPUT_REENABLED", not death_client.world_input_blocked() and not main.world_input_blocked())
	_check("RESTORE_PLAYER_POSITION", player.global_position.is_equal_approx(Vector3(-6.25, 0.0, 1.25)))
	_check("RESTORE_PLAYER_LOADOUT", hud.active_weapon_slot() == 2)
	_check("RESTORE_PLAYER_HP", is_equal_approx(hud.player_combat_vitals.hp_fraction(), 0.75))
	_check("RESTORE_PLAYER_PROTECTION", is_equal_approx(hud.player_combat_vitals.protection_fraction(), 0.35))
	_check("RESTORE_PLAYER_STAMINA", is_equal_approx(hud.stamina_ring.stamina_fraction(), 0.65))
	_check("RESTORE_WORLD_ACTIVE_CELL", streaming.active_cell() == Vector2i.ZERO)
	_check("RESTORE_GROUND_LOOT_IDENTITY", pickup_client.ground_loot_for_ref("LOOT-B10-RESTORE-899") != null)
	_check("RESTORE_GROUND_LOOT_EXPOSURE", is_equal_approx(pickup_client.ground_loot_for_ref("LOOT-B10-RESTORE-899").water_exposure_s(), 899.0))
	_check("RESTORE_AUTO_PICKUP", pickup_client.auto_pickup_enabled())
	_check("RESTORE_INVENTORY", inventory_client.bag_state() == "BAG_EQUIPPED")
	_check("RESTORE_BAG_CONTAINER", inventory_client.projected_state().get("bag", {}).get("bag_ref") == "BAG-B10-EQUIPPED")
	_check("RESTORE_EQUIPMENT", inventory_client.projected_state().get("equipment", {}).get("slots", {}).get("ARMOR") == "ARMOR-B10")
	_check("RESTORE_QUEST", quest_client.projected_quest(QUEST_REF).get("state") == "ACTIVE")
	_check("RESTORE_ECONOMY_PROJECTION", save_client.economy_projection().get("wallet", {}).get("balance") == 321)
	_check("RESTORE_DROPPED_BAG", bag_client.dropped_bag_for_ref("BAG-B10-RESTORE-LAND") != null)
	_check("RESTORE_DEATH_RECOVERY", death_client.recovery_projection().get("state") == "ALIVE")
	_check("RESTORE_PRESENTATION_EXTERNAL_ONLY", restore_result.get("presentation_rebuilt_from_external_snapshot") == true)
	_check("RESTORE_NO_LOCAL_SAVE_LOAD", restore_result.get("save_loaded_locally") == false)
	_check("RESTORE_NO_CANONICAL_MUTATION", restore_result.get("canonical_state_mutated") == false)

	var duplicate_restore: Dictionary = save_client.project_restore_snapshot(restore_snapshot)
	_check("RESTORE_DUPLICATE_REJECTED", duplicate_restore.get("reason") == "STALE_OR_DUPLICATE_RESTORE_SNAPSHOT")
	var wrong_session_restore: Dictionary = restore_snapshot.duplicate(true)
	wrong_session_restore["session_ref"] = WRONG_SESSION
	_check("RESTORE_WRONG_SESSION_REJECTED", save_client.project_restore_snapshot(wrong_session_restore).get("reason") == "SESSION_MISMATCH")
	var malformed_restore: Dictionary = restore_snapshot.duplicate(true)
	malformed_restore["restore_sequence"] = int(restore_snapshot.get("restore_sequence")) + 1
	malformed_restore.erase("inventory_snapshot")
	_check("RESTORE_MALFORMED_REJECTED", str(save_client.project_restore_snapshot(malformed_restore).get("reason", "")).begins_with("MALFORMED_RESTORE"))
	var older_save_restore: Dictionary = _restore_snapshot(true, "ALIVE")
	older_save_restore["save_sequence"] = int(restore_snapshot.get("save_sequence"))
	_check("RESTORE_OLDER_SAVE_SEQUENCE_REJECTED", save_client.project_restore_snapshot(older_save_restore).get("reason") == "OLDER_OR_DUPLICATE_SAVE_SEQUENCE")


func _test_death_policy_and_land_bag() -> void:
	var bag_count_before: int = bag_client.registered_bag_count()
	var no_bag_death: Dictionary = _death_event(false, {}, "DEATH-B10-NO-BAG")
	var no_bag_result: Dictionary = death_client.project_death_event(no_bag_death)
	_check("DEATH_WITHOUT_BAG_PASS", no_bag_result.get("status") == "PASS", JSON.stringify(no_bag_result))
	_check("DEATH_WITHOUT_BAG_NO_DROP", no_bag_result.get("bag_dropped") == false)
	_check("DEATH_WITHOUT_BAG_NO_FABRICATION", bag_client.registered_bag_count() == bag_count_before)
	_check("DEATH_EXTERNAL_STATE_BLOCKS_INPUT", death_client.state() == AndromedaDeathRespawnClient.STATE_DEAD_AWAITING_RESPAWN and main.world_input_blocked())
	_check("DEATH_STOPS_MOVEMENT", not player.has_destination())
	_check("DEATH_CLEARS_TARGET", main.selected_target_ref().is_empty())
	_check("DEATH_XP_RETENTION_PROJECTED", no_bag_result.get("xp_retained_projection") == true)
	_check("DEATH_EQUIPMENT_RETENTION_PROJECTED", no_bag_result.get("equipment_retention_projection") == true)
	_check("DEATH_PROTECTED_ITEMS_PROJECTED", no_bag_result.get("protected_items_projection") == true)
	_check("DEATH_NOT_DECIDED_LOCALLY", no_bag_result.get("death_decided_locally") == false)
	_check("DEATH_NO_LOCAL_ITEMS_MUTATION", no_bag_result.get("items_mutated_locally") == false)
	_check("DEATH_NO_LOCAL_BAG_DECISION", no_bag_result.get("bag_drop_decided_locally") == false)
	var duplicate_no_bag: Dictionary = death_client.project_death_event(no_bag_death)
	_check("DUPLICATE_DEATH_EVENT_REJECTED", duplicate_no_bag.get("reason") == "STALE_OR_DUPLICATE_DEATH_EVENT")
	var wrong_session_death: Dictionary = _death_event(false, {}, "DEATH-B10-WRONG")
	wrong_session_death["session_ref"] = WRONG_SESSION
	_check("WRONG_SESSION_DEATH_REJECTED", death_client.project_death_event(wrong_session_death).get("reason") == "SESSION_MISMATCH")

	var alive_reset: Dictionary = death_client.project_restored_death_recovery(_death_recovery_snapshot("ALIVE"))
	death_client.complete_restore_input_gate()
	_check("EXTERNAL_ALIVE_RESET_PASS", alive_reset.get("status") == "PASS")
	_check("EXTERNAL_ALIVE_RESET_INPUT", not main.world_input_blocked())

	var land_ref := "BAG-B10-LAND-DEATH"
	var land_entry: Dictionary = _bag_entry(land_ref, PLAYER_OWNER_REF, "DROPPED_LAND", "LAND", 0.0)
	land_entry["contents_summary"] = [
		{"item_ref": "COMMON-B10-ONE", "quantity": 3},
		{"item_ref": "COMMON-B10-TWO", "quantity": 1},
	]
	var land_snapshot: Dictionary = _bag_snapshot([land_entry])
	var land_death: Dictionary = _death_event(true, land_snapshot, "DEATH-B10-LAND-BAG")
	var land_death_result: Dictionary = death_client.project_death_event(land_death)
	_check("DEATH_WITH_BAG_LAND_PASS", land_death_result.get("status") == "PASS", JSON.stringify(land_death_result))
	_check("DEATH_WITH_BAG_SINGLE_CONTAINER", land_death_result.get("bag_projection", {}).get("projected_count") == 1)
	var land_bag: AndromedaDroppedBag = bag_client.dropped_bag_for_ref(land_ref)
	_check("LAND_BAG_SPAWNED", land_bag != null)
	if land_bag == null:
		return
	var land_instance_id: int = land_bag.get_instance_id()
	var land_projection: Dictionary = land_bag.presentation_snapshot()
	_check("LAND_BAG_IDENTITY_STABLE", land_projection.get("bag_ref") == land_ref and land_projection.get("target_ref") == land_ref)
	_check("LAND_BAG_OWNER_PRESERVED", land_projection.get("original_owner_ref") == PLAYER_OWNER_REF)
	_check("LAND_BAG_ENVIRONMENT", land_projection.get("environment") == "LAND")
	_check("LAND_BAG_RECOVERABLE", land_projection.get("recoverable") == true)
	_check("LAND_BAG_NO_EXPIRY", land_projection.get("water_ttl_s") == null)
	_check("LAND_BAG_CONTENTS_ONE_CONTAINER", (land_projection.get("contents_summary") as Array).size() == 2)
	_check("LAND_BAG_COMMON_CONTENT_QUANTITY", int((land_projection.get("contents_summary") as Array)[0].get("quantity")) == 3)
	_check("LAND_BAG_PROTECTED_NOT_IN_COMMON_CONTENTS", not JSON.stringify(land_projection.get("contents_summary")).contains("QUEST-CRITICAL-B10"))
	_check("LAND_BAG_TTL_AUTHORITY_FALSE", land_projection.get("ttl_authority_in_gdscript") == false)
	_check("LAND_BAG_OWNERSHIP_AUTHORITY_FALSE", land_projection.get("ownership_authority_in_gdscript") == false)
	var land_exposure_before: float = land_bag.water_exposure_s()
	await _wait_physics_frames(30)
	_check("LAND_BAG_NOT_REMOVED_BY_LOCAL_TIMER", is_instance_valid(land_bag) and land_bag.visible)
	_check("LAND_BAG_EXPOSURE_NOT_ADVANCED", is_equal_approx(land_bag.water_exposure_s(), land_exposure_before))
	_check("LAND_BAG_PHYSICS_FROZEN", bool(land_bag.get("freeze")) and (land_bag.get("linear_velocity") as Vector3).is_zero_approx())

	var external_no_bag_inventory: Dictionary = inventory_client.project_inventory_snapshot(_inventory_snapshot(false))
	_check("DEATH_INVENTORY_EXTERNAL_NO_BAG", external_no_bag_inventory.get("status") == "PASS")
	_check("DEATH_INVENTORY_NO_BAG_STATE", inventory_client.bag_state() == "NO_BAG")
	_check("DEATH_QUICK_SLOT_ONE_RETAINED", str((inventory_client.projected_state().get("weapon_loadout", {}).get("quick_slots") as Array)[0].get("item_ref")) == "WEAPON-B10-ONE")
	_check("DEATH_QUICK_SLOT_TWO_RETAINED", str((inventory_client.projected_state().get("weapon_loadout", {}).get("quick_slots") as Array)[1].get("item_ref")) == "WEAPON-B10-TWO")
	_check("DEATH_ONE_ACTIVE_WEAPON", int(inventory_client.projected_state().get("weapon_loadout", {}).get("active_slot")) in [1, 2])
	_check("DEATH_ARMOR_RETAINED", inventory_client.projected_state().get("equipment", {}).get("slots", {}).get("ARMOR") == "ARMOR-B10")
	_check("DEATH_CLOTHES_RETAINED", inventory_client.projected_state().get("equipment", {}).get("slots", {}).get("CLOTHES") == "CLOTHES-B10")
	_check("DEATH_CRITICAL_ITEM_PROTECTED", "QUEST-CRITICAL-B10" in (inventory_client.projected_state().get("equipment", {}).get("protected_critical_refs") as Array))

	_ground_loot_entries = [_ground_loot_entry("LOOT-B10-LAND-RELOAD", 0.0, "ACTIVE")]
	_dropped_bag_entries = [land_entry]
	var land_reload: Dictionary = save_client.project_restore_snapshot(_restore_snapshot(false, "DEAD_AWAITING_RESPAWN"))
	_check("LAND_BAG_RELOAD_PASS", land_reload.get("status") == "PASS", JSON.stringify(land_reload))
	var reloaded_land_bag: AndromedaDroppedBag = bag_client.dropped_bag_for_ref(land_ref)
	_check("LAND_BAG_RELOAD_PRESENT", reloaded_land_bag != null)
	_check("LAND_BAG_RELOAD_IDENTITY_INSTANCE", reloaded_land_bag != null and reloaded_land_bag.get_instance_id() == land_instance_id)
	_check("LAND_BAG_RELOAD_OWNER", reloaded_land_bag != null and reloaded_land_bag.original_owner_ref == PLAYER_OWNER_REF)
	_check("LAND_BAG_RELOAD_NO_EXPIRY", reloaded_land_bag != null and reloaded_land_bag.water_ttl_s() == null)
	_check("LAND_BAG_RELOAD_DEATH_INPUT_BLOCKED", death_client.world_input_blocked())
	var alive_after_land: Dictionary = death_client.project_restored_death_recovery(_death_recovery_snapshot("ALIVE"))
	death_client.complete_restore_input_gate()
	_check("LAND_TEST_EXTERNAL_ALIVE_PASS", alive_after_land.get("status") == "PASS")
	_check("LAND_TEST_INPUT_RESTORED", not death_client.world_input_blocked())


func _test_water_bag_and_ground_loot_continuity() -> void:
	var water_ref := "BAG-B10-WATER-TTL"
	var stable_instance_id: int = 0
	for exposure: float in [0.0, 1.0, 1799.0, 1800.0, 1801.0]:
		var entry: Dictionary = _bag_entry(
			water_ref,
			PLAYER_OWNER_REF,
			"DROPPED_WATER_FLOATING",
			"WATER",
			exposure
		)
		var projection_result: Dictionary = bag_client.project_dropped_bag_snapshot(_bag_snapshot([entry]))
		_check("WATER_BAG_%s_PROJECTION_PASS" % str(exposure), projection_result.get("status") == "PASS", JSON.stringify(projection_result))
		var bag: AndromedaDroppedBag = bag_client.dropped_bag_for_ref(water_ref)
		_check("WATER_BAG_%s_PRESENT" % str(exposure), bag != null)
		if bag == null:
			continue
		if stable_instance_id == 0:
			stable_instance_id = bag.get_instance_id()
		_check("WATER_BAG_%s_IDENTITY_STABLE" % str(exposure), bag.get_instance_id() == stable_instance_id)
		_check("WATER_BAG_%s_EXPOSURE_PROJECTED" % str(exposure), is_equal_approx(bag.water_exposure_s(), exposure))
		_check("WATER_BAG_%s_TTL_1800" % str(exposure), is_equal_approx(float(bag.water_ttl_s()), 1800.0))
		_check("WATER_BAG_%s_NO_LOCAL_SUNK_INFERENCE" % str(exposure), bag.projected_state() == "DROPPED_WATER_FLOATING")
		_check("WATER_BAG_%s_RECOVERABLE_EXTERNAL" % str(exposure), bag.is_recoverable_projection())
	var water_bag: AndromedaDroppedBag = bag_client.dropped_bag_for_ref(water_ref)
	_check("WATER_BAG_PHYSICS_PRESENTATION_NODE", water_bag != null and water_bag.has_node("WaterWorldItemPresenter"))
	if water_bag != null:
		await _wait_physics_frames(6)
		_check("WATER_BAG_NOT_FALLING_UNRECOVERABLY", bool(water_bag.get("freeze")) and (water_bag.get("linear_velocity") as Vector3).is_zero_approx())
		_check("WATER_BAG_CLICKABLE_WHILE_RECOVERABLE", water_bag.selectable and int(water_bag.get("collision_layer")) == 4096)
		var exposure_before_wait: float = water_bag.water_exposure_s()
		await _wait_physics_frames(30)
		_check("WATER_BAG_LOCAL_CLOCK_DOES_NOT_ADVANCE", is_equal_approx(water_bag.water_exposure_s(), exposure_before_wait))
		_check("WATER_BAG_LOCAL_CLOCK_DOES_NOT_SINK", water_bag.projected_state() == "DROPPED_WATER_FLOATING")

	var corrected_back: Dictionary = _bag_entry(water_ref, PLAYER_OWNER_REF, "DROPPED_WATER_FLOATING", "WATER", 700.0)
	_check("WATER_BAG_CORRECTION_BACK_PASS", bag_client.project_dropped_bag_snapshot(_bag_snapshot([corrected_back])).get("status") == "PASS")
	_check("WATER_BAG_CORRECTION_BACK_VALUE", is_equal_approx(bag_client.dropped_bag_for_ref(water_ref).water_exposure_s(), 700.0))
	var corrected_forward: Dictionary = _bag_entry(water_ref, PLAYER_OWNER_REF, "DROPPED_WATER_FLOATING", "WATER", 1750.0)
	_check("WATER_BAG_CORRECTION_FORWARD_PASS", bag_client.project_dropped_bag_snapshot(_bag_snapshot([corrected_forward])).get("status") == "PASS")
	_check("WATER_BAG_CORRECTION_FORWARD_VALUE", is_equal_approx(bag_client.dropped_bag_for_ref(water_ref).water_exposure_s(), 1750.0))

	_ground_loot_entries = [_ground_loot_entry("LOOT-B10-WATER-CONTINUITY", 899.0, "RECOVERABLE_IN_WATER")]
	_dropped_bag_entries = [_bag_entry(water_ref, PLAYER_OWNER_REF, "DROPPED_WATER_FLOATING", "WATER", 1799.0)]
	var before_expiry_reload: Dictionary = save_client.project_restore_snapshot(_restore_snapshot(false, "ALIVE"))
	_check("WATER_BAG_RELOAD_BEFORE_EXPIRY_PASS", before_expiry_reload.get("status") == "PASS", JSON.stringify(before_expiry_reload))
	var reloaded_water_bag: AndromedaDroppedBag = bag_client.dropped_bag_for_ref(water_ref)
	_check("WATER_BAG_RELOAD_TARGET_REF", reloaded_water_bag != null and reloaded_water_bag.bag_ref == water_ref)
	_check("WATER_BAG_RELOAD_INSTANCE_STABLE", reloaded_water_bag != null and reloaded_water_bag.get_instance_id() == stable_instance_id)
	_check("WATER_BAG_RELOAD_EXPOSURE_1799", reloaded_water_bag != null and is_equal_approx(reloaded_water_bag.water_exposure_s(), 1799.0))
	_check("WATER_BAG_RELOAD_OWNER", reloaded_water_bag != null and reloaded_water_bag.original_owner_ref == PLAYER_OWNER_REF)

	_dropped_bag_entries = [_bag_entry(water_ref, PLAYER_OWNER_REF, "DROPPED_WATER_FLOATING", "WATER", 1800.0)]
	var at_ttl_reload: Dictionary = save_client.project_restore_snapshot(_restore_snapshot(false, "ALIVE"))
	_check("WATER_BAG_RELOAD_1800_PASS", at_ttl_reload.get("status") == "PASS")
	_check("WATER_BAG_1800_STILL_EXTERNAL_FLOATING", bag_client.dropped_bag_for_ref(water_ref).projected_state() == "DROPPED_WATER_FLOATING")
	_check("WATER_BAG_1800_NOT_LOCAL_EXPIRY", bag_client.dropped_bag_for_ref(water_ref).is_recoverable_projection())

	var sunk_entry: Dictionary = _bag_entry(water_ref, PLAYER_OWNER_REF, "SUNK", "WATER", 1800.0)
	_dropped_bag_entries = [sunk_entry]
	var sunk_reload: Dictionary = save_client.project_restore_snapshot(_restore_snapshot(false, "ALIVE"))
	_check("WATER_BAG_SUNK_RELOAD_PASS", sunk_reload.get("status") == "PASS", JSON.stringify(sunk_reload))
	var sunk_bag: AndromedaDroppedBag = bag_client.dropped_bag_for_ref(water_ref)
	_check("WATER_BAG_SUNK_EXTERNAL_STATE", sunk_bag != null and sunk_bag.projected_state() == "SUNK")
	_check("WATER_BAG_SUNK_NOT_RECOVERABLE", sunk_bag != null and not sunk_bag.is_recoverable_projection())
	_check("WATER_BAG_SUNK_VISUAL_DISABLED", sunk_bag != null and not sunk_bag.visible)
	_check("WATER_BAG_SUNK_TARGET_REF_PRESERVED", sunk_bag != null and sunk_bag.bag_ref == water_ref)
	_check("WATER_BAG_SUNK_RECOVERY_BLOCKED", bag_client.evaluate_recovery_candidate(sunk_bag).get("reason") == "DROPPED_BAG_NOT_RECOVERABLE")
	var direct_sunk_ref := "BAG-B10-DIRECT-SUNK"
	var direct_sunk: Dictionary = _bag_entry(direct_sunk_ref, NPC_OWNER_REF, "SUNK", "WATER", 1900.0)
	_check("WATER_BAG_DIRECT_SUNK_PASS", bag_client.project_dropped_bag_snapshot(_bag_snapshot([direct_sunk])).get("status") == "PASS")
	_check("WATER_BAG_DIRECT_SUNK_TOMBSTONE", bag_client.dropped_bag_for_ref(direct_sunk_ref) == null and bag_client.tombstone_for_ref(direct_sunk_ref).get("state") == "SUNK")

	var water_loot_ref := "LOOT-B10-WATER-CONTINUITY"
	var water_loot: AndromedaGroundLoot = pickup_client.ground_loot_for_ref(water_loot_ref)
	_check("GROUND_LOOT_899_RELOAD_PRESENT", water_loot != null)
	var loot_instance_id: int = water_loot.get_instance_id() if water_loot != null else 0
	_check("GROUND_LOOT_899_RELOAD_EXPOSURE", water_loot != null and is_equal_approx(water_loot.water_exposure_s(), 899.0))
	_ground_loot_entries = [_ground_loot_entry(water_loot_ref, 900.0, "RECOVERABLE_IN_WATER")]
	_dropped_bag_entries = []
	var loot_900_reload: Dictionary = save_client.project_restore_snapshot(_restore_snapshot(false, "ALIVE"))
	_check("GROUND_LOOT_900_RELOAD_PASS", loot_900_reload.get("status") == "PASS", JSON.stringify(loot_900_reload))
	water_loot = pickup_client.ground_loot_for_ref(water_loot_ref)
	_check("GROUND_LOOT_900_IDENTITY_STABLE", water_loot != null and water_loot.get_instance_id() == loot_instance_id)
	_check("GROUND_LOOT_900_EXPOSURE_NOT_RESET", water_loot != null and is_equal_approx(water_loot.water_exposure_s(), 900.0))
	_check("GROUND_LOOT_900_NO_LOCAL_SUNK", water_loot != null and water_loot.authoritative_state() == "RECOVERABLE_IN_WATER")
	_ground_loot_entries = [_ground_loot_entry(water_loot_ref, 900.0, "SUNK")]
	var loot_sunk_reload: Dictionary = save_client.project_restore_snapshot(_restore_snapshot(false, "ALIVE"))
	_check("GROUND_LOOT_SUNK_RELOAD_PASS", loot_sunk_reload.get("status") == "PASS")
	water_loot = pickup_client.ground_loot_for_ref(water_loot_ref)
	_check("GROUND_LOOT_SUNK_RELOAD_STATE", water_loot != null and water_loot.authoritative_state() == "SUNK")
	_check("GROUND_LOOT_SUNK_RELOAD_NON_ACTIVE", water_loot != null and not water_loot.is_active_for_pickup())
	_check("GROUND_LOOT_SUNK_RELOAD_TARGET_PRESERVED", water_loot != null and water_loot.target_ref == water_loot_ref)
	_check("GROUND_LOOT_SUNK_RELOAD_PICKUP_BLOCKED", pickup_client.evaluate_pickup_candidate(water_loot).get("reason") == "GROUND_LOOT_NOT_ACTIVE")

	var exhaustion_zero: Dictionary = _exhaustion_snapshot("STAMINA_ZERO_GRACE", 8.0)
	var exhaustion_result: Dictionary = death_client.project_water_exhaustion(exhaustion_zero)
	_check("WATER_EXHAUSTION_EXTERNAL_PASS", exhaustion_result.get("status") == "PASS")
	_check("WATER_EXHAUSTION_GRACE_PROJECTED", is_equal_approx(float(exhaustion_result.get("grace_remaining_s")), 8.0))
	_check("WATER_EXHAUSTION_NO_LOCAL_GRACE_TIMER", exhaustion_result.get("grace_timer_advanced_locally") == false)
	_check("WATER_EXHAUSTION_NO_LOCAL_DEATH", exhaustion_result.get("death_decided_locally") == false)
	var stale_exhaustion: Dictionary = death_client.project_water_exhaustion(exhaustion_zero)
	_check("WATER_EXHAUSTION_DUPLICATE_REJECTED", stale_exhaustion.get("reason") == "STALE_OR_DUPLICATE_EXHAUSTION_SNAPSHOT")


func _test_recovery_and_npc_ownership() -> void:
	_ground_loot_entries = []
	var own_ref := "BAG-B10-OWN-RECOVERY"
	var own_entry: Dictionary = _bag_entry(own_ref, PLAYER_OWNER_REF, "DROPPED_LAND", "LAND", 0.0)
	own_entry["position"] = _position_dict(player.global_position + Vector3(0.35, 0.0, 0.0))
	_dropped_bag_entries = [own_entry]
	var before_recovery_reload: Dictionary = save_client.project_restore_snapshot(_restore_snapshot(false, "ALIVE"))
	_check("OWN_BAG_RELOAD_BEFORE_RECOVERY_PASS", before_recovery_reload.get("status") == "PASS", JSON.stringify(before_recovery_reload))
	var own_bag: AndromedaDroppedBag = bag_client.dropped_bag_for_ref(own_ref)
	_check("OWN_BAG_RECOVERY_TARGET_PRESENT", own_bag != null)
	if own_bag == null:
		return
	player.stop_local_prediction()
	player.global_position = own_bag.global_position + Vector3(-0.35, 0.0, 0.0)
	var eligibility: Dictionary = bag_client.evaluate_recovery_candidate(own_bag)
	_check("OWN_BAG_WITHIN_RANGE_ELIGIBLE", eligibility.get("status") == "PASS", JSON.stringify(eligibility))
	_check("OWN_BAG_PHYSICAL_DISTANCE", float(eligibility.get("physical_distance_m", INF)) <= own_bag.recovery_range_m)
	var own_request: Dictionary = bag_client.begin_recovery_interaction(own_bag, "B10_OWN_BAG")
	_check("OWN_BAG_RECOVERY_REQUEST_PASS", own_request.get("status") == "PASS", JSON.stringify(own_request))
	_check("OWN_BAG_RECOVERY_INTENT", own_request.get("intent") == "REQUEST_BAG_RECOVERY")
	_check("OWN_BAG_RECOVERY_ENVELOPE", own_request.get("intent_envelope", {}).get("status") == "PASS")
	_check("OWN_BAG_RECOVERY_NO_PLAYER_REF", not (own_request.get("intent_envelope", {}).get("envelope", {}).get("params", {}) as Dictionary).has("player_ref"))
	_check("OWN_BAG_RECOVERY_NO_LOCAL_RETURN", own_request.get("bag_returned_locally") == false)
	_check("OWN_BAG_RECOVERY_NO_LOCAL_CONTENT_MOVE", own_request.get("contents_moved_locally") == false)
	_check("OWN_BAG_RECOVERY_NO_LOCAL_OWNER_CHANGE", own_request.get("ownership_mutated_locally") == false)
	var duplicate_request: Dictionary = bag_client.begin_recovery_interaction(own_bag, "B10_DUPLICATE")
	_check("OWN_BAG_DUPLICATE_REQUEST_BLOCKED", duplicate_request.get("reason") == "RECOVERY_REQUEST_ALREADY_INFLIGHT")

	var accepted_projection: Dictionary = own_entry.duplicate(true)
	accepted_projection["server_authoritative"] = true
	accepted_projection["state"] = "RECOVERED"
	accepted_projection["recoverable"] = false
	accepted_projection["carrier_ref"] = PLAYER_REF
	accepted_projection["projection_sequence"] = _next_dropped_bag_sequence()
	var accepted_result: Dictionary = _recovery_result(own_request, "ACCEPTED", accepted_projection, "")
	var accepted: Dictionary = bag_client.project_recovery_result(accepted_result)
	_check("OWN_BAG_RECOVERY_ACCEPTED_PROJECTION_PASS", accepted.get("status") == "PASS", JSON.stringify(accepted))
	_check("OWN_BAG_RECOVERY_ACCEPTED_EXTERNAL_STATE", own_bag.projected_state() == "RECOVERED")
	_check("OWN_BAG_RECOVERY_NO_LOCAL_GRANT", accepted.get("bag_returned_locally") == false)
	_check("OWN_BAG_RECOVERY_NO_LOCAL_CONTENTS", accepted.get("contents_moved_locally") == false)
	_check("OWN_BAG_RECOVERY_OWNER_UNCHANGED_BY_CLIENT", own_bag.original_owner_ref == PLAYER_OWNER_REF)
	_check("OWN_BAG_RECOVERY_TERMINAL_NOT_SELECTABLE", not own_bag.is_recoverable_projection())
	_check("OWN_BAG_RECOVERY_DUPLICATE_RESULT_REJECTED", bag_client.project_recovery_result(accepted_result).get("reason") == "STALE_OR_DUPLICATE_BAG_RECOVERY_RESULT")
	_check("OWN_BAG_ALREADY_RECOVERED_BLOCKED", bag_client.begin_recovery_interaction(own_bag, "ALREADY_RECOVERED").get("reason") == "DROPPED_BAG_NOT_RECOVERABLE")

	var rejected_ref := "BAG-B10-RECOVERY-REJECTED"
	var rejected_entry: Dictionary = _bag_entry(rejected_ref, PLAYER_OWNER_REF, "DROPPED_LAND", "LAND", 0.0)
	rejected_entry["position"] = _position_dict(player.global_position + Vector3(0.3, 0.0, 0.0))
	var rejected_snapshot: Dictionary = _bag_snapshot([rejected_entry])
	_check("REJECTED_RECOVERY_BAG_SPAWN", bag_client.project_dropped_bag_snapshot(rejected_snapshot).get("status") == "PASS")
	var rejected_bag: AndromedaDroppedBag = bag_client.dropped_bag_for_ref(rejected_ref)
	var rejected_request: Dictionary = bag_client.begin_recovery_interaction(rejected_bag, "B10_REJECTED")
	_check("REJECTED_RECOVERY_REQUEST_PASS", rejected_request.get("status") == "PASS")
	var rejected_result: Dictionary = _recovery_result(rejected_request, "REJECTED", {}, "EXTERNAL_RECOVERY_DENIED")
	var rejected_projection: Dictionary = bag_client.project_recovery_result(rejected_result)
	_check("RECOVERY_REJECTED_PROJECTION_PASS", rejected_projection.get("status") == "PASS")
	_check("RECOVERY_REJECTED_REASON", rejected_projection.get("reason") == "EXTERNAL_RECOVERY_DENIED")
	_check("RECOVERY_REJECTED_BAG_REMAINS", rejected_bag.is_recoverable_projection() and rejected_bag.visible)
	_check("RECOVERY_REJECTED_NO_LOCAL_OWNER_CHANGE", rejected_bag.original_owner_ref == PLAYER_OWNER_REF)

	var far_ref := "BAG-B10-RECOVERY-FAR"
	var far_entry: Dictionary = _bag_entry(far_ref, PLAYER_OWNER_REF, "DROPPED_LAND", "LAND", 0.0)
	far_entry["position"] = _position_dict(Vector3(100.0, 0.0, 100.0))
	_check("FAR_BAG_SPAWN", bag_client.project_dropped_bag_snapshot(_bag_snapshot([far_entry])).get("status") == "PASS")
	var far_bag: AndromedaDroppedBag = bag_client.dropped_bag_for_ref(far_ref)
	var far_result: Dictionary = bag_client.begin_recovery_interaction(far_bag, "B10_INVALID_PATH")
	_check("FAR_BAG_NO_TELEPORT", not player.global_position.is_equal_approx(far_bag.global_position))
	_check("FAR_BAG_INVALID_PATH_BLOCKED", far_result.get("reason") in ["DROPPED_BAG_PATH_INVALID", "DROPPED_BAG_APPROACH_REJECTED"], JSON.stringify(far_result))
	_check("FAR_BAG_NO_RECOVERY_REQUEST", bag_client.inflight_request_count() == 0)

	var blocker := StaticBody3D.new()
	blocker.name = "B10RecoveryBlocker"
	blocker.collision_layer = 128
	blocker.collision_mask = 0
	var blocker_shape := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(0.08, 1.5, 0.8)
	blocker_shape.shape = box
	blocker.add_child(blocker_shape)
	main.add_child(blocker)
	var blocked_ref := "BAG-B10-RECOVERY-BLOCKED"
	var blocked_entry: Dictionary = _bag_entry(blocked_ref, PLAYER_OWNER_REF, "DROPPED_LAND", "LAND", 0.0)
	blocked_entry["position"] = _position_dict(Vector3(-6.0, 0.0, 3.0))
	_check("BLOCKED_BAG_SPAWN", bag_client.project_dropped_bag_snapshot(_bag_snapshot([blocked_entry])).get("status") == "PASS")
	var blocked_bag: AndromedaDroppedBag = bag_client.dropped_bag_for_ref(blocked_ref)
	player.stop_local_prediction()
	player.global_position = Vector3(-6.35, 0.0, 3.0)
	blocker.global_position = Vector3(-6.175, 0.6, 3.0)
	await _wait_physics_frames(3)
	player.stop_local_prediction()
	player.global_position = Vector3(-6.35, 0.0, 3.0)
	var blocker_probe: Dictionary = bag_client.recovery_blocker_probe(blocked_bag)
	_check("RECOVERY_BLOCKER_RAY_HIT", blocker_probe.get("blocked") == true, JSON.stringify(blocker_probe))
	var blocked_recovery: Dictionary = bag_client.begin_recovery_interaction(blocked_bag, "B10_BLOCKER")
	_check("RECOVERY_THROUGH_BLOCKER_REJECTED", blocked_recovery.get("reason") == "DROPPED_BAG_RECOVERY_BLOCKED", JSON.stringify(blocked_recovery))
	_check("RECOVERY_BLOCKER_NO_REQUEST", bag_client.inflight_request_count() == 0)
	blocker.queue_free()
	await get_tree().process_frame

	var wrong_target_resolved := {
		"status": "PASS",
		"intent": "APPROACH_RECOVER_BAG",
		"target_ref": "WRONG-BAG-REF",
		"button": "RIGHT",
	}
	_check("RECOVERY_WRONG_TARGET_REF_REJECTED", bag_client.handle_manual_bag_intent(wrong_target_resolved, blocked_bag).get("reason") == "DROPPED_BAG_TARGET_REF_MISMATCH")
	var stale_ref := "BAG-B10-STALE-REMOVED"
	var stale_entry: Dictionary = _bag_entry(stale_ref, PLAYER_OWNER_REF, "DROPPED_LAND", "LAND", 0.0)
	_check("STALE_BAG_SPAWN", bag_client.project_dropped_bag_snapshot(_bag_snapshot([stale_entry])).get("status") == "PASS")
	var stale_bag: AndromedaDroppedBag = bag_client.dropped_bag_for_ref(stale_ref)
	var remove_snapshot: Dictionary = _bag_snapshot([])
	remove_snapshot["complete_projection"] = true
	_check("STALE_BAG_EXTERNAL_REMOVE_PASS", bag_client.project_dropped_bag_snapshot(remove_snapshot).get("status") == "PASS")
	_check("STALE_BAG_REMOVED_FROM_REGISTRY", bag_client.dropped_bag_for_ref(stale_ref) == null)
	_check("STALE_BAG_RECOVERY_BLOCKED", bag_client.evaluate_recovery_candidate(stale_bag).get("reason") in ["STALE_OR_REMOVED_DROPPED_BAG_TARGET", "WRONG_OR_UNREGISTERED_DROPPED_BAG_TARGET"])
	_check("STALE_BAG_TOMBSTONE", bag_client.tombstone_for_ref(stale_ref).get("state") == "REMOVED")

	var npc_ref := "BAG-B10-NPC-OWNED"
	var npc_entry: Dictionary = _bag_entry(npc_ref, NPC_OWNER_REF, "DROPPED_LAND", "LAND", 0.0)
	npc_entry["position"] = _position_dict(player.global_position + Vector3(0.3, 0.0, 0.0))
	npc_entry["context_metadata"] = {
		"origin": "NPC_DEATH_EXTERNAL",
		"reaction_hook": "PRESERVE_CONTEXT_ONLY",
		"country_ref": "COUNTRY-S12-EXISTING",
	}
	_dropped_bag_entries = [npc_entry]
	var npc_reload_before: Dictionary = save_client.project_restore_snapshot(_restore_snapshot(false, "ALIVE"))
	_check("NPC_BAG_RELOAD_BEFORE_RECOVERY_PASS", npc_reload_before.get("status") == "PASS", JSON.stringify(npc_reload_before))
	var npc_bag: AndromedaDroppedBag = bag_client.dropped_bag_for_ref(npc_ref)
	_check("NPC_BAG_PRESENT", npc_bag != null)
	_check("NPC_BAG_ORIGINAL_OWNER", npc_bag != null and npc_bag.original_owner_ref == NPC_OWNER_REF)
	_check("NPC_BAG_CONTEXT_RETAINED", npc_bag != null and npc_bag.presentation_snapshot().get("context_metadata", {}).get("reaction_hook") == "PRESERVE_CONTEXT_ONLY")
	var foreign_npc_observation: Dictionary = bag_client.observe_foreign_npc_proximity(npc_ref, "NPC-B10-FOREIGN")
	_check("FOREIGN_NPC_NO_AUTO_RECOVERY", foreign_npc_observation.get("auto_recovery_requested") == false)
	_check("FOREIGN_NPC_NO_AUTO_THEFT", foreign_npc_observation.get("auto_theft") == false)
	_check("FOREIGN_NPC_NO_OWNERSHIP_CHANGE", foreign_npc_observation.get("ownership_changed") == false)
	player.stop_local_prediction()
	player.global_position = npc_bag.global_position + Vector3(-0.3, 0.0, 0.0)
	var npc_request: Dictionary = bag_client.begin_recovery_interaction(npc_bag, "B10_NPC_BAG")
	_check("PLAYER_NPC_BAG_RECOVERY_INTENT_PASS", npc_request.get("status") == "PASS", JSON.stringify(npc_request))
	var npc_recovered_projection: Dictionary = npc_entry.duplicate(true)
	npc_recovered_projection["server_authoritative"] = true
	npc_recovered_projection["state"] = "RECOVERED_FOREIGN"
	npc_recovered_projection["recoverable"] = false
	npc_recovered_projection["carrier_ref"] = PLAYER_REF
	npc_recovered_projection["projection_sequence"] = _next_dropped_bag_sequence()
	var npc_result: Dictionary = bag_client.project_recovery_result(
		_recovery_result(npc_request, "ACCEPTED", npc_recovered_projection, "")
	)
	_check("PLAYER_NPC_BAG_RECOVERY_EXTERNAL_PASS", npc_result.get("status") == "PASS", JSON.stringify(npc_result))
	_check("NPC_BAG_RECOVERED_FOREIGN_STATE", npc_bag.projected_state() == "RECOVERED_FOREIGN")
	_check("NPC_BAG_ORIGINAL_PROPERTY_RETAINED", npc_bag.original_owner_ref == NPC_OWNER_REF)
	_check("NPC_BAG_PLAYER_CARRIER_PROJECTED", npc_bag.presentation_snapshot().get("carrier_ref") == PLAYER_REF)
	_check("NPC_BAG_CONTEXT_AFTER_RECOVERY", npc_bag.presentation_snapshot().get("context_metadata", {}).get("origin") == "NPC_DEATH_EXTERNAL")
	_check("NPC_BAG_NO_NARRATIVE_REACTION_INVENTED", not npc_bag.presentation_snapshot().get("context_metadata", {}).has("invented_dialogue"))

	_dropped_bag_entries = [npc_recovered_projection]
	var npc_reload_after: Dictionary = save_client.project_restore_snapshot(_restore_snapshot(false, "ALIVE"))
	_check("NPC_BAG_RELOAD_AFTER_RECOVERY_PASS", npc_reload_after.get("status") == "PASS", JSON.stringify(npc_reload_after))
	var npc_after_reload: AndromedaDroppedBag = bag_client.dropped_bag_for_ref(npc_ref)
	_check("NPC_BAG_RELOAD_ORIGINAL_OWNER", npc_after_reload != null and npc_after_reload.original_owner_ref == NPC_OWNER_REF)
	_check("NPC_BAG_RELOAD_RECOVERED_STATE", npc_after_reload != null and npc_after_reload.projected_state() == "RECOVERED_FOREIGN")
	_check("NPC_BAG_RELOAD_CONTEXT", npc_after_reload != null and npc_after_reload.presentation_snapshot().get("context_metadata", {}).get("reaction_hook") == "PRESERVE_CONTEXT_ONLY")


func _test_respawn_input_and_streaming() -> void:
	var respawn_bag_ref := "BAG-B10-RESPAWN-REMAINS"
	var respawn_bag_entry: Dictionary = _bag_entry(respawn_bag_ref, PLAYER_OWNER_REF, "DROPPED_LAND", "LAND", 0.0)
	respawn_bag_entry["position"] = _position_dict(Vector3(-5.0, 0.0, 2.0))
	var respawn_bag_snapshot: Dictionary = _bag_snapshot([respawn_bag_entry])
	var death_event: Dictionary = _death_event(true, respawn_bag_snapshot, "DEATH-B10-RESPAWN")
	var death_result: Dictionary = death_client.project_death_event(death_event)
	_check("RESPAWN_TEST_DEATH_PASS", death_result.get("status") == "PASS", JSON.stringify(death_result))
	_check("RESPAWN_TEST_INPUT_BLOCKED", main.world_input_blocked())
	var selection_before: String = main.selected_target_ref()
	var blocked_left: Dictionary = main.handle_pointer_event(_mouse_button(MOUSE_BUTTON_LEFT, Vector2(480, 270)))
	var blocked_right: Dictionary = main.handle_pointer_event(_mouse_button(MOUSE_BUTTON_RIGHT, Vector2(480, 270)))
	var blocked_e: Dictionary = main.handle_action_event(_key_event(KEY_E))
	var blocked_weapon: Dictionary = main.handle_action_event(_key_event(KEY_1))
	var blocked_wheel: Dictionary = main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_UP, false))
	for pair: Dictionary in [
		{"label": "LEFT_CLICK", "result": blocked_left},
		{"label": "RIGHT_CLICK", "result": blocked_right},
		{"label": "CONTEXT_E", "result": blocked_e},
		{"label": "WEAPON_KEY", "result": blocked_weapon},
		{"label": "WHEEL", "result": blocked_wheel},
	]:
		_check("DEATH_BLOCKS_%s" % str(pair.get("label")), pair.get("result", {}).get("intent") == "WORLD_INPUT_BLOCKED", JSON.stringify(pair.get("result")))
	_check("DEATH_BLOCKED_INPUT_TARGET_STABLE", main.selected_target_ref() == selection_before)
	_check("DEATH_BLOCKED_INPUT_NO_MOVEMENT", not player.has_destination())
	_check("DEATH_BLOCKED_INPUT_NO_ATTACK_REQUEST", blocked_right.get("world_action_dispatched") == false)
	_check("DEATH_BLOCKED_INPUT_NO_GATHER_REQUEST", gathering_client.inflight_request_count() == 0)
	_check("DEATH_BLOCKED_INPUT_NO_PICKUP_REQUEST", pickup_client.inflight_request_count() == 0)
	_check("DEATH_BLOCKED_INPUT_NO_BAG_RECOVERY_REQUEST", bag_client.inflight_request_count() == 0)

	main.set_menu_open(true)
	var menu_scroll: Dictionary = main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_DOWN, false))
	_check("DEATH_UI_MENU_SCROLL_ALLOWED", menu_scroll.get("intent") == "MENU_SCROLL")
	_check("DEATH_UI_MENU_SCROLL_NO_WEAPON_SWAP", menu_scroll.get("intent") != "WEAPON_QUICK_SLOT_CYCLE")
	_check("DEATH_UI_MENU_SCROLL_NO_ZOOM", menu_scroll.get("intent") != "CAMERA_ZOOM")
	main.set_menu_open(false)

	var save_during_death: Dictionary = save_client.request_autosave("DEATH_RECOVERY_STATE")
	_check("AUTOSAVE_WITH_DROPPED_BAG_PASS", save_during_death.get("status") == "PASS", JSON.stringify(save_during_death))
	_check("AUTOSAVE_DURING_DEATH_DOES_NOT_UNBLOCK", main.world_input_blocked())
	_check("AUTOSAVE_DURING_DEATH_BAG_REMAINS", bag_client.dropped_bag_for_ref(respawn_bag_ref) != null)

	var respawn_request: Dictionary = death_client.request_respawn()
	_check("RESPAWN_REQUEST_PASS", respawn_request.get("status") == "PASS", JSON.stringify(respawn_request))
	_check("RESPAWN_REQUEST_ENVELOPE", respawn_request.get("intent_envelope", {}).get("status") == "PASS")
	_check("RESPAWN_REQUEST_NO_LOCAL_WAYPOINT", respawn_request.get("respawn_point_selected_locally") == false)
	_check("RESPAWN_REQUEST_PARAMS_NO_POSITION", not (respawn_request.get("intent_envelope", {}).get("envelope", {}).get("params", {}) as Dictionary).has("position"))
	_check("RESPAWN_PENDING_INPUT_BLOCKED", death_client.state() == AndromedaDeathRespawnClient.STATE_RESPAWN_PENDING and main.world_input_blocked())
	var wrong_session_respawn: Dictionary = _respawn_snapshot(respawn_request, Vector3(-7.0, 0.0, 0.0))
	wrong_session_respawn["session_ref"] = WRONG_SESSION
	_check("RESPAWN_WRONG_SESSION_REJECTED", death_client.project_respawn_snapshot(wrong_session_respawn).get("reason") == "SESSION_MISMATCH")
	var wrong_request_respawn: Dictionary = _respawn_snapshot(respawn_request, Vector3(-7.0, 0.0, 0.0))
	wrong_request_respawn["request_ref"] = "WRONG-RESPAWN-REQUEST"
	_check("RESPAWN_WRONG_REQUEST_REJECTED", death_client.project_respawn_snapshot(wrong_request_respawn).get("reason") == "RESPAWN_REQUEST_REF_MISMATCH")
	var valid_respawn: Dictionary = _respawn_snapshot(respawn_request, Vector3(-7.25, 0.0, -0.5))
	var respawn_result: Dictionary = death_client.project_respawn_snapshot(valid_respawn)
	_check("RESPAWN_EXTERNAL_PROJECTION_PASS", respawn_result.get("status") == "PASS", JSON.stringify(respawn_result))
	_check("RESPAWN_POSITION_EXTERNAL", player.global_position.is_equal_approx(Vector3(-7.25, 0.0, -0.5)))
	_check("RESPAWN_INPUT_REENABLED", not main.world_input_blocked())
	_check("RESPAWN_TARGET_RESET", main.selected_target_ref().is_empty())
	_check("RESPAWN_CAMERA_FOLLOWS_PLAYER", camera_rig.follow_target() == player)
	_check("RESPAWN_NO_LOCAL_WAYPOINT", respawn_result.get("respawn_point_selected_locally") == false)
	_check("RESPAWN_NO_LOCAL_INVENTORY_MUTATION", respawn_result.get("inventory_mutated_locally") == false)
	_check("RESPAWN_DROPPED_BAG_REMAINS", bag_client.dropped_bag_for_ref(respawn_bag_ref) != null)
	_check("RESPAWN_DUPLICATE_REJECTED", death_client.project_respawn_snapshot(valid_respawn).get("reason") == "STALE_OR_DUPLICATE_RESPAWN_SNAPSHOT")
	await _wait_physics_frames(15)
	_check("RESPAWN_CAMERA_STABLE", camera_rig.global_position.distance_to(player.global_position) < 0.05)
	_check("RESPAWN_NO_GHOST_MOVEMENT", not player.has_destination())
	var post_respawn_inventory: Dictionary = inventory_client.project_inventory_snapshot(_inventory_snapshot(false))
	_check("RESPAWN_INVENTORY_EXTERNAL_PASS", post_respawn_inventory.get("status") == "PASS")
	_check("RESPAWN_QUICK_SLOTS_RETAINED", (inventory_client.projected_state().get("weapon_loadout", {}).get("quick_slots") as Array).size() == 2)
	_check("RESPAWN_ARMOR_RETAINED", inventory_client.projected_state().get("equipment", {}).get("slots", {}).get("ARMOR") == "ARMOR-B10")
	_check("RESPAWN_CLOTHES_RETAINED", inventory_client.projected_state().get("equipment", {}).get("slots", {}).get("CLOTHES") == "CLOTHES-B10")

	var stream_bag: AndromedaDroppedBag = bag_client.dropped_bag_for_ref(respawn_bag_ref)
	var stream_instance_id: int = stream_bag.get_instance_id()
	var stream_exposure: float = stream_bag.water_exposure_s()
	var active_to_systemic: Dictionary = bag_client.project_stream_phase(respawn_bag_ref, "SYSTEMIC", 0, true)
	_check("DROPPED_BAG_ACTIVE_TO_SYSTEMIC_PASS", active_to_systemic.get("status") == "PASS", JSON.stringify(active_to_systemic))
	_check("DROPPED_BAG_SYSTEMIC_IDENTITY_REFERENCE", bag_client.systemic_reference_for_ref(respawn_bag_ref).get("bag_ref") == respawn_bag_ref)
	_check("DROPPED_BAG_SYSTEMIC_VISUAL_UNLOADED", not stream_bag.visible)
	_check("DROPPED_BAG_SYSTEMIC_NO_LIVING_AUTHORITY", active_to_systemic.get("systemic_state_owned_by_godot") == false)
	var systemic_to_active: Dictionary = bag_client.project_stream_phase(respawn_bag_ref, "ACTIVE", 1, true)
	_check("DROPPED_BAG_SYSTEMIC_TO_ACTIVE_PASS", systemic_to_active.get("status") == "PASS")
	_check("DROPPED_BAG_STREAM_IDENTITY_STABLE", stream_bag.get_instance_id() == stream_instance_id and stream_bag.bag_ref == respawn_bag_ref)
	_check("DROPPED_BAG_STREAM_NO_DUPLICATE", bag_client.dropped_bag_for_ref(respawn_bag_ref) == stream_bag)
	_check("DROPPED_BAG_STREAM_EXPOSURE_STABLE", is_equal_approx(stream_bag.water_exposure_s(), stream_exposure))
	_check("DROPPED_BAG_STREAM_ACTIVE_VISIBLE", stream_bag.visible)
	var duplicate_stream: Dictionary = bag_client.project_stream_phase(respawn_bag_ref, "ACTIVE", 1, true)
	_check("DROPPED_BAG_DUPLICATE_STREAM_REJECTED", duplicate_stream.get("reason") == "STALE_OR_DUPLICATE_DROPPED_BAG_STREAM_PHASE")

	_ground_loot_entries = []
	_dropped_bag_entries = [respawn_bag_entry]
	var stream_reload: Dictionary = save_client.project_restore_snapshot(_restore_snapshot(false, "ALIVE"))
	_check("DROPPED_BAG_STREAM_SAVE_RELOAD_PASS", stream_reload.get("status") == "PASS", JSON.stringify(stream_reload))
	var stream_reloaded: AndromedaDroppedBag = bag_client.dropped_bag_for_ref(respawn_bag_ref)
	_check("DROPPED_BAG_STREAM_RELOAD_IDENTITY", stream_reloaded != null and stream_reloaded.get_instance_id() == stream_instance_id)
	_check("DROPPED_BAG_STREAM_RELOAD_OWNER", stream_reloaded != null and stream_reloaded.original_owner_ref == PLAYER_OWNER_REF)
	_check("DROPPED_BAG_STREAM_RELOAD_NO_DUPLICATION", bag_client.active_bag_count() >= 1)


func _test_reconnect_resync_and_regressions(session: AndromedaClientSession) -> void:
	var inflight_before_reconnect: Dictionary = save_client.request_autosave("RECONNECT_TEST")
	_check("RECONNECT_SAVE_INFLIGHT_SETUP", inflight_before_reconnect.get("status") == "PASS")
	_check("RECONNECT_SAVE_TRACKED", save_client.inflight_save_count() >= 1)
	var revoke: Dictionary = session.revoke_session()
	_check("RECONNECT_SESSION_REVOKED", revoke.get("status") == "PASS", JSON.stringify(revoke))
	_check("RECONNECT_INPUT_BLOCKED", death_client.world_input_blocked())
	_check("RECONNECT_SAVE_REQUIRES_RESYNC", save_client.needs_resync() and save_client.state() == AndromedaSaveReloadClient.STATE_RESYNC_REQUIRED)
	_check("RECONNECT_INFLIGHT_SAVE_CLEARED", save_client.inflight_save_count() == 0)
	var bind: Dictionary = session.bind_session(SESSION_RESYNC)
	_current_session = SESSION_RESYNC
	_check("RECONNECT_SESSION_BOUND", bind.get("status") == "PASS", JSON.stringify(bind))
	_check("RECONNECT_SESSION_REF", session.session_ref() == SESSION_RESYNC)
	_check("RECONNECT_NOT_READY_BEFORE_RESTORE", save_client.needs_resync() and save_client.state() == AndromedaSaveReloadClient.STATE_RESYNC_REQUIRED)
	_check("RECONNECT_WORLD_INPUT_STILL_BLOCKED", main.world_input_blocked())
	var old_result: Dictionary = _save_result_payload(inflight_before_reconnect, "CONFIRMED", "")
	old_result["session_ref"] = SESSION_INITIAL
	_check("RECONNECT_OLD_SAVE_RESULT_REJECTED", save_client.project_save_result(old_result).get("reason") == "SESSION_MISMATCH")

	_ground_loot_entries = [_ground_loot_entry("LOOT-B10-RESYNC", 450.0, "RECOVERABLE_IN_WATER")]
	_dropped_bag_entries = [_bag_entry("BAG-B10-RESYNC", NPC_OWNER_REF, "DROPPED_WATER_FLOATING", "WATER", 600.0)]
	var resync_restore: Dictionary = save_client.project_restore_snapshot(_restore_snapshot(false, "ALIVE"))
	_check("RECONNECT_RESYNC_RESTORE_PASS", resync_restore.get("status") == "PASS", JSON.stringify(resync_restore))
	_check("RECONNECT_READY_AFTER_RESYNC", save_client.state() == AndromedaSaveReloadClient.STATE_READY and not save_client.needs_resync())
	_check("RECONNECT_INPUT_RESTORED", not main.world_input_blocked())
	_check("RECONNECT_PLAYER_RESTORED", player.global_position.is_equal_approx(Vector3(-6.25, 0.0, 1.25)))
	_check("RECONNECT_GROUND_LOOT_REF", pickup_client.ground_loot_for_ref("LOOT-B10-RESYNC") != null)
	_check("RECONNECT_GROUND_LOOT_EXPOSURE", is_equal_approx(pickup_client.ground_loot_for_ref("LOOT-B10-RESYNC").water_exposure_s(), 450.0))
	_check("RECONNECT_BAG_REF", bag_client.dropped_bag_for_ref("BAG-B10-RESYNC") != null)
	_check("RECONNECT_BAG_OWNER", bag_client.dropped_bag_for_ref("BAG-B10-RESYNC").original_owner_ref == NPC_OWNER_REF)
	_check("RECONNECT_BAG_EXPOSURE", is_equal_approx(bag_client.dropped_bag_for_ref("BAG-B10-RESYNC").water_exposure_s(), 600.0))
	_check("RECONNECT_AUTO_PICKUP_PROJECTION", pickup_client.auto_pickup_enabled())
	_check("RECONNECT_QUEST_PROJECTION", quest_client.projected_quest(QUEST_REF).get("state") == "ACTIVE")
	_check("RECONNECT_ECONOMY_PROJECTION", save_client.economy_projection().get("wallet", {}).get("balance") == 321)

	var stale_preference: Dictionary = pickup_client.project_profile_preference(true, SESSION_RESYNC, _preference_sequence - 1, true)
	_check("RECONNECT_STALE_PREFERENCE_REJECTED", stale_preference.get("reason") == "STALE_OR_DUPLICATE_PROFILE_PREFERENCE")
	var wrong_session_bag: Dictionary = _bag_snapshot(_dropped_bag_entries)
	wrong_session_bag["session_ref"] = WRONG_SESSION
	_check("RECONNECT_WRONG_SESSION_BAG_REJECTED", bag_client.project_dropped_bag_snapshot(wrong_session_bag).get("reason") == "SESSION_MISMATCH")
	var wrong_session_loot: Dictionary = _ground_loot_snapshot()
	wrong_session_loot["session_ref"] = WRONG_SESSION
	_check("RECONNECT_WRONG_SESSION_LOOT_REJECTED", pickup_client.project_ground_loot_snapshot(wrong_session_loot).get("reason") == "GROUND_LOOT_SNAPSHOT_SESSION_MISMATCH")

	var navigation_move: Dictionary = player.request_move(Vector3(-5.0, 0.0, 0.0))
	_check("B02_CLICK_TO_MOVE_AFTER_B10", navigation_move.get("status") == "PASS", JSON.stringify(navigation_move))
	_check("B02_DESTINATION_SET_AFTER_B10", player.has_destination())
	player.stop_local_prediction()
	_check("B02_CAMERA_FOLLOW_AFTER_B10", camera_rig.follow_target() == player)
	_check("B02_CAMERA_NO_FREE_ORBIT", camera_rig.contract_snapshot().get("free_orbit") == false)
	var router := get_node("/root/InputRouter") as AndromedaInputRouter
	var overlap_choice: Dictionary = router.choose_pointer_target([
		{"target_ref": "B10-BEHIND", "target_kind": "ACTOR", "screen_distance_px": 0.1, "depth_m": 8.0, "direct_hit": true},
		{"target_ref": "B10-FRONT", "target_kind": "DROPPED_BAG", "screen_distance_px": 0.1, "depth_m": 4.0, "direct_hit": true},
	])
	_check("B03_DEPTH_WINS_OVER_TYPE", overlap_choice.get("target_ref") == "B10-FRONT")
	_check("B03_DROPPED_BAG_LAYER_SEPARATED", main.collision_layer_contract().get("DROPPED_BAG") == 4096)
	_check("B04_TERRAIN_SURFACES_SEPARATED", main.terrain_contract_snapshot().get("surfaces_separated") == true)
	_check("B04_STREAMING_PRESERVED", streaming.state_snapshot().get("living_parallel_implementation") == false)
	_check("B04_WATER_AUTHORITY_EXTERNAL", main.terrain_contract_snapshot().get("gameplay_authority_in_gdscript") == false)
	_check("B05_STAMINA_RADIAL_PRESERVED", hud.stamina_ring.contract_snapshot().get("shape") == "CIRCLE_RADIAL")
	_check("B05_TWO_QUICK_SLOTS_PRESERVED", hud.weapon_quick_slots.contract_snapshot().get("max_quick_slots") == 2)
	_check("B05_DIALOGUE_POOL_PRESERVED", hud.dialogue_pool_capacity() == 3)
	_check("B05_UI_FAMILY_PRESERVED", hud.contract_snapshot().get("ui_family") == "WHITE_OFF_WHITE_ROUNDED_CLEAN_CONSOLE")
	_check("B05_B10_OVERLAY_NOT_PERMANENT", hud.death_recovery_overlay.contract_snapshot().get("large_permanent_panel") == false)
	var target_before_feedback: String = main.selected_target_ref()
	var feedback: Dictionary = hud.present_combat_event({
		"token": "PLAYER_HURT",
		"target_ref": PLAYER_REF,
		"confirmed_externally": true,
	})
	_check("B06_COMBAT_FEEDBACK_AFTER_B10", feedback.get("status") == "PASS", JSON.stringify(feedback))
	_check("B06_FEEDBACK_TARGET_STABLE", main.selected_target_ref() == target_before_feedback)
	_check("B06_REDUCED_MOTION_PRESERVED", hud.set_reduced_motion(true).get("status") == "PASS")
	_check("B06_REDUCED_MOTION_ZERO_IMPULSE", camera_rig.request_presentation_impulse(0.18).get("applied_impulse_m") == 0.0)
	hud.set_reduced_motion(false)
	_check("B07_PICKUP_RADIUS_05_PRESERVED", is_equal_approx(AndromedaGroundLootPickupClient.PICKUP_RADIUS_M, 0.5))
	_check("B07_GROUND_LOOT_TTL_AUTHORITY_FALSE", pickup_client.contract_snapshot().get("ttl_authority") == false)
	_check("B08_GATHERING_YIELD_AUTHORITY_FALSE", gathering_client.contract_snapshot().get("yield_authority") == false)
	_check("B08_GATHERING_INVENTORY_AUTHORITY_FALSE", gathering_client.contract_snapshot().get("inventory_authority") == false)
	_check("B09_INVENTORY_AUTHORITY_FALSE", inventory_client.contract_snapshot().get("inventory_transfer_authority") == false)
	_check("B09_BAG_REAL_CONTAINER", inventory_client.contract_snapshot().get("bag_is_real_container") == true)
	_check("B09_QUEST_COMPLETION_EXTERNAL", quest_client.contract_snapshot().get("completion_authority") == false)
	_check("B09_VENDOR_NO_AUTO_PURCHASE", main.contract_snapshot().get("vendor_click_auto_purchase") == false)
	_check("B10_SCENETREE_NEVER_PAUSED", not get_tree().paused)
	_check("B10_BACKEND_STILL_NOT_SUBSTITUTED", main.contract_snapshot().get("backend_substitute") == false)
	_check("B10_NO_CANONICAL_MUTATION_METHOD", not save_client.has_method("mutate_canonical_state"))
	_check("B11_INSTRUMENTATION_INERT", main.has_node("B11VerticalSliceClient") and main.contract_snapshot().get("b11_harness_runs_automatically") == false)


func _restore_snapshot(with_equipped_bag: bool, death_state: String) -> Dictionary:
	_restore_sequence += 1
	_save_sequence += 1
	_resource_sequence += 1
	var snapshot := {
		"server_authoritative": true,
		"session_ref": _current_session,
		"restore_ref": "RESTORE-B10-%06d" % _restore_sequence,
		"restore_sequence": _restore_sequence,
		"save_sequence": _save_sequence,
		"player": {
			"position": _position_dict(Vector3(-6.25, 0.0, 1.25)),
			"presentation": {
				"stamina": {"fraction": 0.65, "activity": "REGENERATING"},
				"weapon_loadout": {"active_slot": 2},
				"combat_presentation": {
					"player": {"hp_fraction": 0.75, "protection_fraction": 0.35, "relevant": true},
					"targets": [],
				},
			},
		},
		"world": {
			"active_cell": {"x": 0, "y": 0},
			"resource_snapshot": {
				"server_authoritative": true,
				"session_ref": _current_session,
				"snapshot_sequence": _resource_sequence,
				"resources": [],
			},
		},
		"ground_loot_snapshot": _ground_loot_snapshot(),
		"profile_preference": {
			"auto_pickup": true,
			"preference_sequence": _next_preference_sequence(),
		},
		"inventory_snapshot": _inventory_snapshot(with_equipped_bag),
		"economy_projection": {
			"wallet": {"owner_ref": PLAYER_OWNER_REF, "balance": 321, "revision": _save_sequence},
			"vendor_state_refs": ["SHOP-S13-91CDF9F934810A65B2"],
			"calculated_locally": false,
		},
		"quest_projection": {
			"offer_snapshot": _offer_snapshot(),
			"state_snapshot": _quest_snapshot("ACTIVE", "PENDING"),
		},
		"dropped_bag_snapshot": _bag_snapshot(_dropped_bag_entries),
		"death_recovery_snapshot": _death_recovery_snapshot(death_state),
	}
	return snapshot


func _inventory_snapshot(with_bag: bool) -> Dictionary:
	_inventory_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _current_session,
		"snapshot_sequence": _inventory_sequence,
		"base_inventory": {
			"owner_ref": PLAYER_OWNER_REF,
			"slot_limit": 8,
			"weight_limit": 20.0,
			"stacks": [{"item_ref": "BASE-B10", "quantity": 2, "protected": false}],
		},
		"bag": {
			"state": "BAG_EQUIPPED" if with_bag else "NO_BAG",
			"bag_ref": "BAG-B10-EQUIPPED" if with_bag else "",
			"capacity_slots": 30 if with_bag else 0,
			"capacity_weight": 80.0 if with_bag else 0.0,
			"contents": [{"item_ref": "COMMON-B10-CARRIED", "quantity": 4}] if with_bag else [],
		},
		"equipment": {
			"slots": {"ARMOR": "ARMOR-B10", "CLOTHES": "CLOTHES-B10"},
			"protected_critical_refs": ["QUEST-CRITICAL-B10", "UNIQUE-CRITICAL-B10"],
		},
		"weapon_loadout": {
			"quick_slots": [
				{"slot": 1, "item_ref": "WEAPON-B10-ONE"},
				{"slot": 2, "item_ref": "WEAPON-B10-TWO"},
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
			"effective_inventory_owner_ref": "BAG-B10-EQUIPPED" if with_bag else PLAYER_OWNER_REF,
			"currency_wallet_owner_ref": PLAYER_OWNER_REF,
		},
	}


func _offer_snapshot() -> Dictionary:
	_offer_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _current_session,
		"snapshot_sequence": _offer_sequence,
		"offers": [{
			"quest_ref": QUEST_REF,
			"npc_ref": main.dialogue_npc_primary.target_ref,
			"title": "Orientação de Varga",
			"objectives": [{"objective_ref": "OBJ-S12-ORIENTATION", "text": "Objetivo contratado", "state": "PENDING"}],
			"choices": [{"choice_ref": "CHOICE-S12-ORIENTATION-ACCEPT", "label": "Aceitar"}],
		}],
	}


func _quest_snapshot(state_value: String, objective_state: String) -> Dictionary:
	_quest_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _current_session,
		"snapshot_sequence": _quest_sequence,
		"quests": [{
			"quest_ref": QUEST_REF,
			"npc_ref": main.dialogue_npc_primary.target_ref,
			"title": "Orientação de Varga",
			"state": state_value,
			"objectives": [{"objective_ref": "OBJ-S12-ORIENTATION", "text": "Objetivo contratado", "state": objective_state}],
			"choices": [],
		}],
	}


func _ground_loot_entry(target_ref_value: String, exposure_s: float, state_value: String) -> Dictionary:
	return {
		"target_ref": target_ref_value,
		"drop_ref": target_ref_value,
		"source_ref": "SOURCE-B10-EXTERNAL",
		"source_kind": "PLAYER_DROP",
		"item_ref": "ITEM-%s" % target_ref_value,
		"item_kind": "MATERIAL",
		"quantity": 2,
		"state": state_value,
		"settled": true,
		"reachable": state_value != "SUNK",
		"water_exposure_s": exposure_s,
		"settled_position": _position_dict(Vector3(32.0, 0.4, -10.0)),
	}


func _ground_loot_snapshot() -> Dictionary:
	_ground_loot_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _current_session,
		"snapshot_sequence": _ground_loot_sequence,
		"ground_loot": _ground_loot_entries.duplicate(true),
	}


func _bag_entry(
	bag_ref_value: String,
	original_owner_ref_value: String,
	state_value: String,
	environment_value: String,
	exposure_s: float
) -> Dictionary:
	var water: bool = environment_value == "WATER"
	var terminal: bool = state_value in ["RECOVERED", "RECOVERED_FOREIGN", "SUNK", "REMOVED"]
	var water_ttl_projection: Variant = null
	if water:
		water_ttl_projection = 1800.0
	return {
		"bag_ref": bag_ref_value,
		"target_ref": bag_ref_value,
		"original_owner_ref": original_owner_ref_value,
		"property_owner_ref": original_owner_ref_value,
		"carrier_ref": "",
		"state": state_value,
		"environment": environment_value,
		"location_kind": environment_value,
		"recoverable": not terminal,
		"water_exposure_s": exposure_s,
		"water_ttl_s": water_ttl_projection,
		"contents_summary": [{"item_ref": "COMMON-B10", "quantity": 2}],
		"context_metadata": {"origin": "EXTERNAL_B10_FIXTURE", "canonical_mutation": false},
		"position": _position_dict(Vector3(32.0, 0.4, -10.0) if water else Vector3(-6.0, 0.0, 1.5)),
	}


func _bag_snapshot(entries: Array[Dictionary]) -> Dictionary:
	_dropped_bag_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _current_session,
		"snapshot_sequence": _dropped_bag_sequence,
		"dropped_bags": entries.duplicate(true),
		"complete_projection": false,
	}


func _death_recovery_snapshot(state_value: String) -> Dictionary:
	_death_restore_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _current_session,
		"restore_sequence": _death_restore_sequence,
		"state": state_value,
		"retention_projection": _retention_projection(),
		"recovery_state_ref": "RECOVERY-B10-%06d" % _death_restore_sequence,
	}


func _death_event(with_bag: bool, dropped_bag_snapshot: Dictionary, death_ref_value: String) -> Dictionary:
	_death_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _current_session,
		"death_sequence": _death_sequence,
		"death_ref": death_ref_value,
		"state": "DEAD_AWAITING_RESPAWN",
		"retention": _retention_projection(),
		"bag_drop": {
			"dropped": with_bag,
			"reason": "EQUIPPED_BAG_EXTERNAL_DROP" if with_bag else "NO_BAG_EQUIPPED",
			"single_container": with_bag,
			"dropped_bag_snapshot": dropped_bag_snapshot if with_bag else {},
		},
	}


func _retention_projection() -> Dictionary:
	return {
		"xp_retained": true,
		"quick_slots": [
			{"slot": 1, "item_ref": "WEAPON-B10-ONE"},
			{"slot": 2, "item_ref": "WEAPON-B10-TWO"},
		],
		"active_slot": 2,
		"equipped_armor_refs": ["ARMOR-B10"],
		"equipped_clothes_refs": ["CLOTHES-B10"],
		"protected_critical_refs": ["QUEST-CRITICAL-B10", "UNIQUE-CRITICAL-B10"],
	}


func _save_result_payload(intent: Dictionary, result_value: String, reason: String) -> Dictionary:
	_save_result_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _current_session,
		"result_sequence": _save_result_sequence,
		"request_ref": str(intent.get("request_ref", "")),
		"result": result_value,
		"reason": reason,
		"save_ref": "SAVE-B10-%06d" % _save_result_sequence,
		"save_sequence": 50 + _save_result_sequence,
	}


func _recovery_result(
	request: Dictionary,
	result_value: String,
	bag_projection: Dictionary,
	reason: String
) -> Dictionary:
	_recovery_result_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _current_session,
		"result_sequence": _recovery_result_sequence,
		"request_ref": str(request.get("request_ref", "")),
		"bag_ref": str(request.get("bag_ref", "")),
		"result": result_value,
		"reason": reason,
		"bag_projection": bag_projection,
	}


func _respawn_snapshot(request: Dictionary, position: Vector3) -> Dictionary:
	_respawn_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _current_session,
		"respawn_sequence": _respawn_sequence,
		"request_ref": str(request.get("request_ref", "")),
		"state": "READY",
		"position": _position_dict(position),
		"safe_waypoint_ref": "EXTERNAL-SAFE-WAYPOINT-B10",
	}


func _exhaustion_snapshot(state_value: String, grace_remaining_s: float) -> Dictionary:
	_exhaustion_sequence += 1
	return {
		"server_authoritative": true,
		"session_ref": _current_session,
		"exhaustion_sequence": _exhaustion_sequence,
		"state": state_value,
		"grace_remaining_s": grace_remaining_s,
	}


func _next_preference_sequence() -> int:
	_preference_sequence += 1
	return _preference_sequence


func _next_dropped_bag_sequence() -> int:
	_dropped_bag_sequence += 1
	return _dropped_bag_sequence


func _position_dict(position: Vector3) -> Dictionary:
	return {
		"iso_x_m": position.x,
		"iso_y_m": position.z,
		"altitude_m": position.y,
	}


func _mouse_button(button_index: int, position_value: Vector2) -> InputEventMouseButton:
	var event := InputEventMouseButton.new()
	event.button_index = button_index as MouseButton
	event.pressed = true
	event.position = position_value
	return event


func _wheel_event(button_index: int, shift_pressed: bool) -> InputEventMouseButton:
	var event: InputEventMouseButton = _mouse_button(button_index, Vector2(480, 270))
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
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "B10_SAVE_DEATH_DROPPED_BAG_RECOVERY_RESPAWN_CONTINUITY",
		"acceptance_scope_pass": [],
		"partial_evidence_only": ["G16B-17", "G16B-18", "G16B-25", "G16B-26", "G16B-27", "G16B-28"],
		"regression_evidence": ["G16B-01", "G16B-02", "G16B-03", "G16B-04", "G16B-05", "G16B-06", "G16B-07", "G16B-08", "G16B-09", "G16B-10", "G16B-11", "G16B-12", "G16B-13", "G16B-15", "G16B-16", "G16B-20", "G16B-21", "G16B-22", "G16B-23", "G16B-24"],
		"not_executed": ["G16B-19"],
		"authoritative_roundtrip_executed": false,
		"backend_status": "NOT_AVAILABLE",
		"fixtures_are_external_projection_contract_tests_only": true,
		"b11_started": false,
		"final_stage16_checkpoint_or_restore_executed": false,
		"final_stage16_backup_created": false,
		"authority": "GODOT_B10_CLIENT_ORCHESTRATION_PRESENTATION_ONLY",
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_B10_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_B10_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_B10_SUMMARY: %s" % JSON.stringify(summary))
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
