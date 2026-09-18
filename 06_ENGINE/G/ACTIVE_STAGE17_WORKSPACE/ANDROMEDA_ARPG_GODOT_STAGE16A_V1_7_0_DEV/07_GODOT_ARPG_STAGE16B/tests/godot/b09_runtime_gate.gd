extends Node

const SESSION_REF := "B09-GATE-SESSION"
const SESSION_REF_2 := "B09-GATE-SESSION-RESYNC"
const WRONG_SESSION_REF := "B09-GATE-WRONG-SESSION"
const VENDOR_REF := "SHOP-S13-91CDF9F934810A65B2"
const BUY_ITEM_REF := "ITEM-S13-BUY-PLACEHOLDER"
const BASE_ITEM_REF := "ITEM-S13-BASE-CARRIED"
const BAG_ITEM_REF := "ITEM-S13-BAG-CARRIED"
const QUEST_REF := "QST-S12-VARGA-ORIENTATION"

var _checks: int = 0
var _failures: Array[String] = []
var _quote_sequence: int = 0
var _trade_result_sequence: int = 0
var _quest_event_sequence: int = 0

@onready var main: AndromedaMainRuntime = $AndromedaARPG
@onready var player: AndromedaPlayerController = $AndromedaARPG/ActorRoot/Player
@onready var camera_rig: AndromedaIsometricCameraRig = $AndromedaARPG/IsometricCameraRig
@onready var hud: AndromedaHUDController = $AndromedaARPG/UILayer/MinimalHUD
@onready var vendor: AndromedaVendorTarget = $AndromedaARPG/ActorRoot/VendorNPCB09
@onready var quest_npc: AndromedaInteractionTarget = $AndromedaARPG/ActorRoot/NPCB03
@onready var enemy: AndromedaInteractionTarget = $AndromedaARPG/ActorRoot/EnemyB03
@onready var vendor_client: AndromedaVendorClient = $AndromedaARPG/VendorClient
@onready var inventory_client: AndromedaInventoryClient = $AndromedaARPG/InventoryClient
@onready var quest_client: AndromedaQuestClient = $AndromedaARPG/QuestClient
@onready var gathering_client: AndromedaGatheringClient = $AndromedaARPG/GatheringClient
@onready var pickup_client: AndromedaGroundLootPickupClient = $AndromedaARPG/GroundLootPickupClient


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
	_check("PROJECT_LABEL_B09_THROUGH_B11", str(ProjectSettings.get_setting("application/config/name")) in ["Andromeda ARPG Stage16B B09", "Andromeda ARPG Stage16B B10", "Andromeda ARPG Stage16B B11"])
	_check("MAIN_SCENE_PRESERVED", str(ProjectSettings.get_setting("application/run/main_scene")) == "res://scenes/Main.tscn")
	_check("BACKEND_URL_UNCHANGED", bridge.server_url() == "http://127.0.0.1:8000")
	_check("NAVIGATION_READY", await _wait_for_navigation(240))
	_test_architecture_and_authority(bridge, router)
	_test_external_preflight_and_stale_guards()
	await _test_vendor_selection_approach_and_open()
	_test_quote_execute_buy_sell()
	_test_inventory_and_bag_projection()
	await _test_modal_input_safety()
	await _test_quest_loop()
	_test_b01_b08_client_regressions()
	_test_reconnect_resync(session)
	await _finish()


func _test_architecture_and_authority(bridge: AndromedaRuntimeBridge, router: AndromedaInputRouter) -> void:
	_check("VENDOR_SPECIALIZED_TARGET", vendor is AndromedaVendorTarget)
	_check("VENDOR_ROOT_CHARACTER_BODY", vendor.is_class("CharacterBody3D"))
	_check("VENDOR_COLLISION_SHAPE", vendor.has_node("CollisionShape3D"))
	_check("VENDOR_VISUAL_ROOT", vendor.has_node("VisualRoot"))
	_check("VENDOR_INTERACTION_SENSOR", vendor.has_node("InteractionSensor"))
	_check("VENDOR_INTERACTION_ANCHOR", vendor.has_node("InteractionAnchor"))
	_check("VENDOR_DIALOGUE_ANCHOR", vendor.has_node("DialogueAnchor"))
	_check("VENDOR_PLACEHOLDER_VISUAL", vendor.has_node("VisualRoot/PlaceholderMesh"))
	_check("VENDOR_ACTOR_LAYER", int(vendor.get("collision_layer")) == 4)
	_check("VENDOR_SENSOR_LAYER", int((vendor.get_node("InteractionSensor") as Area3D).collision_layer) == 8)
	_check("VENDOR_TARGET_KIND_NPC", vendor.target_kind == AndromedaInputRouter.HIT_NPC)
	_check("VENDOR_TARGET_REF_STABLE", vendor.target_ref == "NPC-S13-VENDOR-SERVICE-POI-002")
	_check("VENDOR_REF_CONTRACTED", vendor.vendor_ref == VENDOR_REF)
	_check("VENDOR_LOCATION_CONTRACTED", vendor.location_ref == "POI-002")
	_check("VENDOR_NOT_HOSTILE", not vendor.hostile)
	_check("VENDOR_NO_MERCHANT_IDENTITY_CLAIM", vendor.get_meta("merchant_identity_claimed") == false)
	_check("VENDOR_NO_FINAL_ART", vendor.contract_snapshot().get("final_art") == false)
	_check("VENDOR_CLIENT_PRESENT", main.contract_snapshot().get("vendor_client_present") == true)
	_check("INVENTORY_CLIENT_PRESENT", main.contract_snapshot().get("inventory_client_present") == true)
	_check("QUEST_CLIENT_PRESENT", main.contract_snapshot().get("quest_client_present") == true)
	_check("HUD_VENDOR_PANEL_PRESENT", hud.has_node("VendorPanel"))
	_check("HUD_INVENTORY_PANEL_PRESERVED", hud.has_node("InventoryPanel"))
	_check("HUD_QUEST_PANEL_PRESENT", hud.has_node("QuestPanel"))
	_check("HUD_QUEST_FEEDBACK_STACK", hud.has_node("QuestFeedbackStack"))
	_check("VENDOR_PANEL_ROUNDED_WHITE", hud.vendor_panel.has_node("Backdrop/RoundedWhitePanel"))
	_check("QUEST_PANEL_ROUNDED_WHITE", hud.quest_panel.has_node("Backdrop/RoundedWhitePanel"))
	_check("INVENTORY_PANEL_ROUNDED_WHITE", hud.inventory_shell.has_node("RoundedWhitePanel"))
	_check("QUEST_NO_NEXT_BUTTON", not _node_tree_has_name(hud.quest_panel, "Next") and not _node_tree_has_name(hud.quest_panel, "Proximo"))
	_check("TREE_NOT_PAUSED", not get_tree().paused)
	var vendor_contract: Dictionary = vendor_client.contract_snapshot()
	for flag: String in [
		"click_auto_purchase", "approach_auto_purchase", "open_auto_purchase",
		"selection_auto_purchase", "quote_auto_execute", "owner_ref_supplied_by_client",
		"player_ref_supplied_by_client", "price_authority", "wallet_authority",
		"inventory_authority", "ownership_authority", "quote_expiry_authority",
		"backend_substitute", "invented_endpoint",
	]:
		_check("VENDOR_CONTRACT_FALSE_%s" % flag.to_upper(), vendor_contract.get(flag) == false)
	_check("VENDOR_EXPLICIT_CONFIRMATION", vendor_contract.get("explicit_confirmation_required") == true)
	_check("VENDOR_BUY_SELL", vendor_contract.get("operations") == ["BUY", "SELL"])
	_check("VENDOR_QUOTE_EXECUTE_PHASES_DISTINCT", vendor_contract.get("flow", []).find("REQUEST_QUOTE") < vendor_contract.get("flow", []).find("EXECUTE_TRADE"))
	var inventory_contract: Dictionary = inventory_client.contract_snapshot()
	for flag: String in [
		"capacity_authority", "load_authority", "stack_authority", "ownership_authority",
		"equipment_authority", "inventory_transfer_authority", "bag_contents_authority",
		"death_drop_logic", "dropped_bag_logic", "bag_recovery_logic", "save_reload_logic",
		"backend_substitute",
	]:
		_check("INVENTORY_CONTRACT_FALSE_%s" % flag.to_upper(), inventory_contract.get(flag) == false)
	_check("INVENTORY_BAG_REAL_CONTAINER", inventory_contract.get("bag_is_real_container") == true)
	_check("INVENTORY_TWO_QUICK_SLOTS", inventory_contract.get("quick_slot_count") == 2)
	_check("INVENTORY_ONE_ACTIVE_WEAPON", inventory_contract.get("simultaneously_active_weapons") == 1)
	_check("INVENTORY_BASE_REDUCED_CANDIDATE", inventory_contract.get("base_reduced_slot_candidate") == 8)
	var quest_contract: Dictionary = quest_client.contract_snapshot()
	for flag: String in [
		"decline_intent_contracted", "objective_authority", "completion_authority",
		"reward_authority", "xp_authority", "canonical_authority", "local_kill_counting",
		"local_pickup_counting", "local_gather_counting", "backend_substitute",
		"invented_quest", "invented_endpoint",
	]:
		_check("QUEST_CONTRACT_FALSE_%s" % flag.to_upper(), quest_contract.get(flag) == false)
	_check("QUEST_REFS_EXACT_STAGE12", quest_contract.get("contracted_quest_refs") == [
		"QST-S12-VARGA-MEDIATION", "QST-S12-BRIDGE-CONTINUITY",
		"QST-S12-WORKSHOP-CIRCUIT", "QST-S12-FRONTIER-SUPPLY",
		"QST-S12-VARGA-ORIENTATION",
	])
	_check("QUEST_STATES_CONTRACTED", quest_contract.get("quest_states") == ["ACTIVE", "READY_TO_TURN_IN", "COMPLETED"])
	_check("QUEST_OBJECTIVE_STATES_CONTRACTED", quest_contract.get("objective_states") == ["PENDING", "COMPLETE"])
	_check("ROUTER_NPC_RIGHT_CLICK_ONLY", router.resolve_pointer_click(
		MOUSE_BUTTON_RIGHT, AndromedaInputRouter.HIT_NPC, Vector3.ZERO, vendor.target_ref
	).get("input_mode") == "CLICK_ONLY")
	_check("BRIDGE_REJECTS_PLAYER_REF", bridge.build_command_envelope("REQUEST_TRADE_QUOTE", {
		"vendor_ref": VENDOR_REF, "player_ref": "CLIENT-FORGED",
	}).get("status") == "REJECTED")
	_check("BRIDGE_REJECTS_INVENTORY_GRANT", bridge.build_command_envelope("EXECUTE_TRADE", {
		"quote_ref": "Q", "inventory_grant": {"item_ref": "FORGED"},
	}).get("status") == "REJECTED")
	_check("NO_VENDOR_CALCULATE_PRICE_METHOD", not vendor_client.has_method("calculate_price"))
	_check("NO_VENDOR_GRANT_ITEM_METHOD", not vendor_client.has_method("grant_item"))
	_check("NO_VENDOR_DEBIT_WALLET_METHOD", not vendor_client.has_method("debit_wallet"))
	_check("NO_INVENTORY_TRANSFER_METHOD", not inventory_client.has_method("transfer_item_authoritatively"))
	_check("NO_QUEST_COMPLETE_METHOD", not quest_client.has_method("complete_quest"))
	_check("NO_QUEST_GRANT_REWARD_METHOD", not quest_client.has_method("grant_reward"))
	_check("NO_QUEST_GRANT_XP_METHOD", not quest_client.has_method("grant_xp"))
	var b10_active: bool = str(ProjectSettings.get_setting("application/config/name")) in ["Andromeda ARPG Stage16B B10", "Andromeda ARPG Stage16B B11"]
	_check("B10_DROPPED_BAG_CLIENT_ADDITIVE_COMPATIBILITY", main.has_node("DroppedBagClient") == b10_active)
	_check("B10_SAVE_CLIENT_ADDITIVE_COMPATIBILITY", main.has_node("SaveReloadClient") == b10_active)
	_check("B10_DEATH_CLIENT_ADDITIVE_COMPATIBILITY", main.has_node("DeathRespawnClient") == b10_active)


func _test_external_preflight_and_stale_guards() -> void:
	var stock := _stock_snapshot(SESSION_REF, 0)
	var non_authoritative: Dictionary = stock.duplicate(true)
	non_authoritative["server_authoritative"] = false
	_check("NON_AUTHORITATIVE_STOCK_REJECTED", vendor_client.project_stock_snapshot(non_authoritative).get("reason") == "NON_AUTHORITATIVE_VENDOR_STOCK_SNAPSHOT")
	var wrong_session: Dictionary = stock.duplicate(true)
	wrong_session["session_ref"] = WRONG_SESSION_REF
	_check("WRONG_SESSION_STOCK_REJECTED", vendor_client.project_stock_snapshot(wrong_session).get("reason") == "SESSION_MISMATCH")
	var stock_result: Dictionary = vendor_client.project_stock_snapshot(stock)
	_check("EXTERNAL_STOCK_PROJECTION_PASS", stock_result.get("status") == "PASS", JSON.stringify(stock_result))
	_check("STOCK_HAS_TWO_EXTERNAL_ITEMS", stock_result.get("item_count") == 2)
	_check("STOCK_DEFERRED_WHILE_CLOSED", stock_result.get("ui_projection", {}).get("deferred_until_vendor_open") == true)
	_check("STOCK_DOES_NOT_CALCULATE_PRICE", stock_result.get("price_calculated_locally") == false)
	_check("VENDOR_RESYNC_SATISFIED_BY_EXTERNAL_STOCK", not vendor_client.needs_resync())
	_check("DUPLICATE_STOCK_REJECTED", vendor_client.project_stock_snapshot(stock).get("reason") == "STALE_OR_DUPLICATE_VENDOR_STOCK_SNAPSHOT")
	var stale_stock: Dictionary = stock.duplicate(true)
	stale_stock["snapshot_sequence"] = 0
	_check("STALE_STOCK_REJECTED", vendor_client.project_stock_snapshot(stale_stock).get("reason") == "STALE_OR_DUPLICATE_VENDOR_STOCK_SNAPSHOT")
	var malformed_stock: Dictionary = stock.duplicate(true)
	malformed_stock["snapshot_sequence"] = 1
	malformed_stock["items"] = "INVALID"
	_check("MALFORMED_STOCK_REJECTED", vendor_client.project_stock_snapshot(malformed_stock).get("reason") == "INVALID_VENDOR_STOCK_ITEMS")
	var nonauth_inventory: Dictionary = _inventory_snapshot(SESSION_REF, 0, false)
	nonauth_inventory["server_authoritative"] = false
	_check("NON_AUTHORITATIVE_INVENTORY_REJECTED", inventory_client.project_inventory_snapshot(nonauth_inventory).get("reason") == "NON_AUTHORITATIVE_INVENTORY_SNAPSHOT")
	var wrong_inventory: Dictionary = _inventory_snapshot(WRONG_SESSION_REF, 0, false)
	_check("WRONG_SESSION_INVENTORY_REJECTED", inventory_client.project_inventory_snapshot(wrong_inventory).get("reason") == "SESSION_MISMATCH")
	var nonauth_offer: Dictionary = _offer_snapshot(SESSION_REF, 0)
	nonauth_offer["server_authoritative"] = false
	_check("NON_AUTHORITATIVE_QUEST_OFFER_REJECTED", quest_client.project_offer_snapshot(nonauth_offer).get("reason") == "NON_AUTHORITATIVE_QUEST_OFFER_SNAPSHOT")
	var invented_offer: Dictionary = _offer_snapshot(SESSION_REF, 0)
	(invented_offer["offers"] as Array)[0]["quest_ref"] = "QST-B09-INVENTED"
	_check("INVENTED_QUEST_REJECTED", quest_client.project_offer_snapshot(invented_offer).get("reason") == "UNCONTRACTED_QUEST_REF")
	var offer_result: Dictionary = quest_client.project_offer_snapshot(_offer_snapshot(SESSION_REF, 0))
	_check("EXTERNAL_QUEST_OFFER_PROJECTION_PASS", offer_result.get("status") == "PASS", JSON.stringify(offer_result))
	_check("QUEST_OFFER_COUNT_ONE", offer_result.get("offer_count") == 1)
	_check("QUEST_OFFER_NOT_AUTHORED_LOCALLY", offer_result.get("offers_authored_locally") == false)
	_check("QUEST_RESYNC_SATISFIED_BY_EXTERNAL_OFFER", not quest_client.needs_resync())
	_check("DUPLICATE_QUEST_OFFER_REJECTED", quest_client.project_offer_snapshot(_offer_snapshot(SESSION_REF, 0)).get("reason") == "STALE_OR_DUPLICATE_QUEST_OFFER_SNAPSHOT")


func _test_vendor_selection_approach_and_open() -> void:
	main.set_menu_open(false)
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 2.0)
	await _wait_physics_frames(3)
	var pre_move: Dictionary = player.request_move(Vector3(-4.0, 0.0, 5.0))
	_check("VENDOR_PRE_SELECTION_MOVEMENT_STARTED", pre_move.get("status") == "PASS")
	var destination_before: Vector3 = player.requested_destination()
	var left_result: Dictionary = main.handle_pointer_event(_mouse_button(
		MOUSE_BUTTON_LEFT, main.world_to_screen(vendor.pointer_world_position())
	))
	_check("VENDOR_LEFT_SELECTION_PASS", left_result.get("status") == "PASS", JSON.stringify(left_result))
	_check("VENDOR_LEFT_SELECTION_INTENT", left_result.get("intent") == "SELECT_TARGET")
	_check("VENDOR_LEFT_TARGET_REF", left_result.get("target_ref") == vendor.target_ref)
	_check("VENDOR_SELECTION_STABLE", main.selected_target_ref() == vendor.target_ref)
	_check("VENDOR_LEFT_PRESERVES_MOVEMENT", player.has_destination())
	_check("VENDOR_LEFT_PRESERVES_DESTINATION", player.requested_destination().is_equal_approx(destination_before))
	_check("VENDOR_LEFT_NO_UI_OPEN", not hud.is_vendor_open())
	_check("VENDOR_LEFT_NO_QUOTE", vendor_client.last_quote_request().is_empty())
	_check("VENDOR_LEFT_NO_EXECUTE", vendor_client.last_execute_request().is_empty())
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 2.0)
	await _wait_physics_frames(2)
	var position_before: Vector3 = player.global_position
	var right_far: Dictionary = main.handle_pointer_event(_mouse_button(
		MOUSE_BUTTON_RIGHT, main.world_to_screen(vendor.pointer_world_position())
	))
	_check("VENDOR_RIGHT_FAR_POINTER_PASS", right_far.get("status") == "PASS", JSON.stringify(right_far))
	_check("VENDOR_RIGHT_FAR_CLICK_ONLY", right_far.get("input_mode") == "CLICK_ONLY")
	var approach: Dictionary = right_far.get("vendor_client_result", {})
	_check("VENDOR_RIGHT_FAR_CLIENT_PASS", approach.get("status") == "PASS", JSON.stringify(approach))
	_check("VENDOR_RIGHT_FAR_APPROACH_PENDING", approach.get("intent") == "APPROACH_VENDOR_PENDING")
	_check("VENDOR_RIGHT_FAR_NO_UI", approach.get("vendor_ui_opened") == false)
	_check("VENDOR_RIGHT_FAR_NO_TRADE", approach.get("trade_executed") == false)
	_check("VENDOR_RIGHT_FAR_MOVEMENT_STARTED", player.has_destination())
	_check("VENDOR_RIGHT_FAR_NO_TELEPORT", player.global_position.distance_to(position_before) < 0.05)
	_check("VENDOR_PENDING_REF_CORRECT", vendor_client.pending_vendor_ref() == VENDOR_REF)
	vendor_client.clear_client_tracking()
	player.stop_local_prediction()
	player.global_position = vendor.global_position + Vector3(1.25, 0.0, 0.0)
	await _wait_physics_frames(3)
	var right_near: Dictionary = main.handle_pointer_event(_mouse_button(
		MOUSE_BUTTON_RIGHT, main.world_to_screen(vendor.pointer_world_position())
	))
	_check("VENDOR_RIGHT_NEAR_POINTER_PASS", right_near.get("status") == "PASS", JSON.stringify(right_near))
	var open_result: Dictionary = right_near.get("vendor_client_result", {})
	_check("VENDOR_RIGHT_NEAR_OPENS_UI", open_result.get("intent") == "OPEN_VENDOR_UI", JSON.stringify(open_result))
	_check("VENDOR_RIGHT_NEAR_UI_VISIBLE", hud.is_vendor_open() and main.menu_open())
	_check("VENDOR_OPEN_NO_AUTO_PURCHASE", open_result.get("auto_purchase") == false)
	_check("VENDOR_OPEN_NO_QUOTE_REQUEST", open_result.get("quote_requested") == false)
	_check("VENDOR_OPEN_NO_EXECUTE", open_result.get("trade_executed") == false)
	_check("VENDOR_OPEN_STOCK_PROJECTED", open_result.get("ui_projection", {}).get("stock_projection", {}).get("status") == "PASS")
	hud.close_active_modal()
	_check("VENDOR_CLOSE_UI", not hud.is_vendor_open() and not main.menu_open())
	var e_result: Dictionary = main.handle_action_event(_key_event(KEY_E))
	_check("VENDOR_E_INTERACTION_PASS", e_result.get("status") == "PASS", JSON.stringify(e_result))
	_check("VENDOR_E_INTERACTION_CONTEXT", e_result.get("intent") == "CONTEXT_INTERACT_SELECTED")
	_check("VENDOR_E_OPENS_UI", e_result.get("vendor_client_result", {}).get("intent") == "OPEN_VENDOR_UI")
	_check("VENDOR_E_NO_EXECUTE", e_result.get("vendor_client_result", {}).get("trade_executed") == false)
	_check("VENDOR_UI_ACTIVE_MODAL", hud.active_modal() == "VENDOR")


func _test_quote_execute_buy_sell() -> void:
	var empty_execute: Dictionary = vendor_client.execute_trade(
		"NO-QUOTE", VENDOR_REF, BUY_ITEM_REF, "BUY", 1, "CONFIRM-NO-QUOTE", true
	)
	_check("EXECUTE_WITHOUT_QUOTE_REJECTED", empty_execute.get("reason") == "EXECUTE_REQUIRES_PROJECTED_QUOTE")
	_check("INVALID_QUOTE_ZERO_QUANTITY", vendor_client.request_quote(VENDOR_REF, BUY_ITEM_REF, "BUY", 0).get("reason") == "INVALID_TRADE_QUANTITY")
	_check("INVALID_QUOTE_OPERATION", vendor_client.request_quote(VENDOR_REF, BUY_ITEM_REF, "BARTER", 1).get("reason") == "INVALID_TRADE_OPERATION")
	_check("INVALID_QUOTE_ITEM", vendor_client.request_quote(VENDOR_REF, "", "BUY", 1).get("reason") == "EMPTY_TRADE_ITEM_REF")
	_check("BUY_ITEM_NOT_STOCK_REJECTED", vendor_client.request_quote(VENDOR_REF, "ITEM-NOT-STOCK", "BUY", 1).get("reason") == "ITEM_NOT_IN_PROJECTED_VENDOR_STOCK")
	var buy_request: Dictionary = vendor_client.request_quote(VENDOR_REF, BUY_ITEM_REF, "BUY", 2)
	_check("BUY_QUOTE_REQUEST_PASS", buy_request.get("status") == "PASS", JSON.stringify(buy_request))
	_check("BUY_QUOTE_REQUEST_INTENT", buy_request.get("intent") == "REQUEST_QUOTE")
	_check("BUY_QUOTE_NO_PRICE_CALC", buy_request.get("price_calculated_locally") == false)
	_check("BUY_QUOTE_NO_WALLET_MUTATION", buy_request.get("wallet_mutated_locally") == false)
	_check("BUY_QUOTE_NO_INVENTORY_MUTATION", buy_request.get("inventory_mutated_locally") == false)
	var buy_params: Dictionary = buy_request.get("intent_envelope", {}).get("envelope", {}).get("params", {})
	_check("BUY_QUOTE_VENDOR_REF", buy_params.get("vendor_ref") == VENDOR_REF)
	_check("BUY_QUOTE_ITEM_REF", buy_params.get("item_ref") == BUY_ITEM_REF)
	_check("BUY_QUOTE_DIRECTION", buy_params.get("direction") == "BUY")
	_check("BUY_QUOTE_QUANTITY", buy_params.get("quantity") == 2)
	_check("BUY_QUOTE_NO_PLAYER_REF", not buy_params.has("player_ref"))
	_check("BUY_QUOTE_NO_OWNER_REF", not buy_params.has("owner_ref"))
	_check("BUY_QUOTE_NO_CLIENT_PRICE", not buy_params.has("price") and not buy_params.has("unit_price") and not buy_params.has("total_price"))
	_check("QUOTE_REQUEST_DOES_NOT_BUY", vendor_client.last_execute_request().is_empty())
	var nonauth_quote: Dictionary = _quote_payload(_quote_sequence, "QUOTE-BUY-NONAUTH", buy_request, 24.0)
	nonauth_quote["server_authoritative"] = false
	_check("NON_AUTHORITATIVE_QUOTE_REJECTED", vendor_client.project_quote(nonauth_quote).get("reason") == "NON_AUTHORITATIVE_VENDOR_QUOTE")
	var wrong_session_quote: Dictionary = _quote_payload(_quote_sequence, "QUOTE-BUY-WRONG-SESSION", buy_request, 24.0)
	wrong_session_quote["session_ref"] = WRONG_SESSION_REF
	_check("WRONG_SESSION_QUOTE_REJECTED", vendor_client.project_quote(wrong_session_quote).get("reason") == "SESSION_MISMATCH")
	var wrong_vendor_quote: Dictionary = _quote_payload(_quote_sequence, "QUOTE-BUY-WRONG-VENDOR", buy_request, 24.0)
	wrong_vendor_quote["vendor_ref"] = "SHOP-WRONG"
	_check("WRONG_VENDOR_QUOTE_REJECTED", vendor_client.project_quote(wrong_vendor_quote).get("reason") == "QUOTE_VENDOR_REF_MISMATCH")
	var wrong_item_quote: Dictionary = _quote_payload(_quote_sequence, "QUOTE-BUY-WRONG-ITEM", buy_request, 24.0)
	wrong_item_quote["item_ref"] = "ITEM-WRONG"
	_check("WRONG_ITEM_QUOTE_REJECTED", vendor_client.project_quote(wrong_item_quote).get("reason") == "QUOTE_ITEM_REF_MISMATCH")
	var wrong_operation_quote: Dictionary = _quote_payload(_quote_sequence, "QUOTE-BUY-AS-SELL", buy_request, 24.0)
	wrong_operation_quote["direction"] = "SELL"
	_check("BUY_QUOTE_USED_AS_SELL_REJECTED", vendor_client.project_quote(wrong_operation_quote).get("reason") == "QUOTE_OPERATION_MISMATCH")
	var wrong_quantity_quote: Dictionary = _quote_payload(_quote_sequence, "QUOTE-BUY-WRONG-QTY", buy_request, 24.0)
	wrong_quantity_quote["quantity"] = 1
	_check("WRONG_QUANTITY_QUOTE_REJECTED", vendor_client.project_quote(wrong_quantity_quote).get("reason") == "QUOTE_QUANTITY_MISMATCH")
	var valid_quote: Dictionary = _quote_payload(_quote_sequence, "QUOTE-BUY-001", buy_request, 24.0)
	var quote_result: Dictionary = vendor_client.project_quote(valid_quote)
	_check("BUY_QUOTE_PROJECTION_PASS", quote_result.get("status") == "PASS", JSON.stringify(quote_result))
	_check("BUY_QUOTE_PROJECTED_REF", quote_result.get("quote_ref") == "QUOTE-BUY-001")
	_check("BUY_QUOTE_NO_RECALC", quote_result.get("price_recalculated_locally") == false)
	_check("BUY_QUOTE_NO_AUTO_EXECUTE", quote_result.get("trade_executed") == false)
	_check("BUY_QUOTE_UI_PRESENT", hud.vendor_panel.projected_quote().get("quote_ref") == "QUOTE-BUY-001")
	_check("DUPLICATE_QUOTE_REJECTED", vendor_client.project_quote(valid_quote).get("reason") == "STALE_OR_DUPLICATE_QUOTE_SEQUENCE")
	_quote_sequence += 1
	_check("EXECUTE_REQUIRES_EXPLICIT_BOOLEAN", vendor_client.execute_trade(
		"QUOTE-BUY-001", VENDOR_REF, BUY_ITEM_REF, "BUY", 2, "CONFIRM-FALSE", false
	).get("reason") == "EXPLICIT_USER_CONFIRMATION_REQUIRED")
	_check("EXECUTE_REQUIRES_CONFIRM_REF", vendor_client.execute_trade(
		"QUOTE-BUY-001", VENDOR_REF, BUY_ITEM_REF, "BUY", 2, "", true
	).get("reason") == "EXPLICIT_CONFIRMATION_REF_REQUIRED")
	_check("EXECUTE_WRONG_QUOTE_REF_REJECTED", vendor_client.execute_trade(
		"QUOTE-WRONG", VENDOR_REF, BUY_ITEM_REF, "BUY", 2, "CONFIRM-WRONG-QUOTE", true
	).get("reason") == "QUOTE_REF_MISMATCH")
	_check("EXECUTE_WRONG_VENDOR_REJECTED", vendor_client.execute_trade(
		"QUOTE-BUY-001", "SHOP-WRONG", BUY_ITEM_REF, "BUY", 2, "CONFIRM-WRONG-VENDOR", true
	).get("reason") == "QUOTE_VENDOR_REF_MISMATCH")
	_check("EXECUTE_WRONG_ITEM_REJECTED", vendor_client.execute_trade(
		"QUOTE-BUY-001", VENDOR_REF, "ITEM-WRONG", "BUY", 2, "CONFIRM-WRONG-ITEM", true
	).get("reason") == "QUOTE_ITEM_REF_MISMATCH")
	_check("EXECUTE_WRONG_OPERATION_REJECTED", vendor_client.execute_trade(
		"QUOTE-BUY-001", VENDOR_REF, BUY_ITEM_REF, "SELL", 2, "CONFIRM-WRONG-OP", true
	).get("reason") == "QUOTE_OPERATION_MISMATCH")
	_check("EXECUTE_WRONG_QUANTITY_REJECTED", vendor_client.execute_trade(
		"QUOTE-BUY-001", VENDOR_REF, BUY_ITEM_REF, "BUY", 1, "CONFIRM-WRONG-QTY", true
	).get("reason") == "QUOTE_QUANTITY_MISMATCH")
	var execute: Dictionary = vendor_client.execute_trade(
		"QUOTE-BUY-001", VENDOR_REF, BUY_ITEM_REF, "BUY", 2, "CONFIRM-BUY-001", true
	)
	_check("BUY_EXECUTE_EXPLICIT_PASS", execute.get("status") == "PASS", JSON.stringify(execute))
	_check("BUY_EXECUTE_INTENT", execute.get("intent") == "EXECUTE_TRADE")
	_check("BUY_EXECUTE_NO_WALLET_MUTATION", execute.get("wallet_mutated_locally") == false)
	_check("BUY_EXECUTE_NO_INVENTORY_MUTATION", execute.get("inventory_mutated_locally") == false)
	_check("BUY_EXECUTE_NO_OWNERSHIP_MUTATION", execute.get("ownership_mutated_locally") == false)
	var execute_params: Dictionary = execute.get("intent_envelope", {}).get("envelope", {}).get("params", {})
	_check("BUY_EXECUTE_CONFIRMATION_TRUE", execute_params.get("explicit_user_confirmation") == true)
	_check("BUY_EXECUTE_HAS_EVENT_REF", not str(execute_params.get("event_ref", "")).is_empty())
	_check("BUY_EXECUTE_NO_OWNER_ROUTING", not execute_params.has("owner_ref") and not execute_params.has("inventory_owner_ref"))
	_check("BUY_EXECUTE_NO_WALLET_FIELDS", not execute_params.has("wallet") and not execute_params.has("currency_result"))
	var retry: Dictionary = vendor_client.execute_trade(
		"QUOTE-BUY-001", VENDOR_REF, BUY_ITEM_REF, "BUY", 2, "CONFIRM-BUY-001", true
	)
	_check("BUY_EXECUTE_SAFE_RETRY_PASS", retry.get("status") == "PASS")
	_check("BUY_EXECUTE_SAFE_RETRY_IDEMPOTENT", retry.get("idempotent_retry") == true)
	_check("BUY_EXECUTE_SAFE_RETRY_SAME_EVENT", retry.get("event_ref") == execute.get("event_ref"))
	var wrong_result := _trade_result_payload(execute, "ACCEPTED", "")
	wrong_result["session_ref"] = WRONG_SESSION_REF
	_check("WRONG_SESSION_TRADE_RESULT_REJECTED", vendor_client.project_trade_result(wrong_result).get("reason") == "SESSION_MISMATCH")
	var accepted_result := _trade_result_payload(execute, "ACCEPTED", "")
	var accepted_projection: Dictionary = vendor_client.project_trade_result(accepted_result)
	_check("BUY_ACCEPTED_RESULT_PROJECTED", accepted_projection.get("status") == "PASS", JSON.stringify(accepted_projection))
	_check("BUY_ACCEPTED_EXTERNAL_RESULT", accepted_projection.get("external_result") == "ACCEPTED")
	_check("BUY_ACCEPTED_NO_LOCAL_WALLET", accepted_projection.get("wallet_mutated_locally") == false)
	_check("BUY_ACCEPTED_NO_LOCAL_INVENTORY", accepted_projection.get("inventory_mutated_locally") == false)
	_check("DUPLICATE_TRADE_RESULT_REJECTED", vendor_client.project_trade_result(accepted_result).get("reason") == "STALE_OR_DUPLICATE_TRADE_RESULT")
	_trade_result_sequence += 1
	_trade_rejection_cycle("SELL_BASE", "SELL", BASE_ITEM_REF, 1, "INSUFFICIENT_FUNDS")
	_trade_rejection_cycle("SELL_BAG", "SELL", BAG_ITEM_REF, 3, "INVENTORY_FULL")
	_trade_rejection_cycle("BUY_UNAVAILABLE", "BUY", BUY_ITEM_REF, 1, "ITEM_UNAVAILABLE")


func _test_inventory_and_bag_projection() -> void:
	var no_bag_snapshot: Dictionary = _inventory_snapshot(SESSION_REF, 0, false)
	var no_bag_result: Dictionary = inventory_client.project_inventory_snapshot(no_bag_snapshot)
	_check("NO_BAG_SNAPSHOT_PASS", no_bag_result.get("status") == "PASS", JSON.stringify(no_bag_result))
	_check("NO_BAG_STATE_PROJECTED", inventory_client.bag_state() == "NO_BAG")
	_check("NO_BAG_BASE_REDUCED_SLOTS_EXTERNAL", no_bag_snapshot.get("base_inventory", {}).get("slot_limit") == 8)
	_check("NO_BAG_EFFECTIVE_OWNER_BASE", no_bag_snapshot.get("routing", {}).get("source") == "BASE_INVENTORY")
	_check("NO_BAG_EFFECTIVE_OWNER_REF", no_bag_snapshot.get("routing", {}).get("effective_inventory_owner_ref") == "PROFILE-B09")
	_check("NO_BAG_UI_LABEL", hud.inventory_shell.bag_state_label().contains("NO_BAG"))
	_check("BASE_STACK_PROJECTED", hud.inventory_shell.external_projection().get("base_inventory", {}).get("stacks", []).size() == 1)
	_check("EQUIPMENT_PROJECTED", hud.inventory_shell.external_projection().get("equipment", {}).get("slots", {}).has("ARMOR"))
	_check("TWO_QUICK_SLOTS_PRESERVED", hud.inventory_shell.external_projection().get("weapon_loadout", {}).get("quick_slots", []).size() == 2)
	_check("ONE_ACTIVE_WEAPON_PROJECTED", hud.active_weapon_slot() == 1)
	_check("INVENTORY_NO_LOCAL_CAPACITY_CALC", no_bag_result.get("capacity_calculated_locally") == false)
	_check("INVENTORY_NO_LOCAL_LOAD_CALC", no_bag_result.get("load_calculated_locally") == false)
	_check("INVENTORY_NO_LOCAL_OWNER_SELECTION", no_bag_result.get("effective_owner_selected_locally") == false)
	var before_equip: Dictionary = inventory_client.projected_state()
	var bag_equip_intent: Dictionary = inventory_client.request_bag_equip("BAG-INSTANCE-B09-001")
	_check("BAG_EQUIP_INTENT_PASS", bag_equip_intent.get("status") == "PASS", JSON.stringify(bag_equip_intent))
	_check("BAG_EQUIP_INTENT_NO_LOCAL_MUTATION", bag_equip_intent.get("inventory_mutated_locally") == false)
	_check("BAG_EQUIP_INTENT_NO_OWNERSHIP_MUTATION", bag_equip_intent.get("ownership_mutated_locally") == false)
	_check("BAG_EQUIP_STATE_UNCHANGED_UNTIL_SNAPSHOT", inventory_client.projected_state() == before_equip)
	_check("BAG_UNEQUIP_NOT_INVENTED", inventory_client.request_bag_unequip("BAG-INSTANCE-B09-001").get("reason") == "BAG_UNEQUIP_NOT_CONTRACTED_IN_STAGE16A_B09")
	var equipment_intent: Dictionary = inventory_client.request_equipment_intent("ARMOR-B09", "ARMOR", true)
	_check("EQUIPMENT_INTENT_PASS", equipment_intent.get("status") == "PASS")
	_check("EQUIPMENT_INTENT_EXTERNAL_AUTH_REQUIRED", equipment_intent.get("equipment_authorized_locally") == false)
	_check("EQUIPMENT_STATE_UNCHANGED_UNTIL_SNAPSHOT", inventory_client.projected_state() == before_equip)
	var bag_snapshot: Dictionary = _inventory_snapshot(SESSION_REF, 1, true)
	var bag_result: Dictionary = inventory_client.project_inventory_snapshot(bag_snapshot)
	_check("BAG_EQUIPPED_SNAPSHOT_PASS", bag_result.get("status") == "PASS", JSON.stringify(bag_result))
	_check("BAG_EQUIPPED_STATE", inventory_client.bag_state() == "BAG_EQUIPPED")
	_check("BAG_REAL_REF_PROJECTED", inventory_client.projected_state().get("bag", {}).get("bag_ref") == "BAG-INSTANCE-B09-001")
	_check("BAG_CONTENTS_EXTERNAL", inventory_client.projected_state().get("bag", {}).get("contents", []).size() == 1)
	_check("BAG_EFFECTIVE_OWNER_ROUTE", inventory_client.projected_state().get("routing", {}).get("source") == "EQUIPPED_BAG")
	_check("BAG_EFFECTIVE_OWNER_REF", inventory_client.projected_state().get("routing", {}).get("effective_inventory_owner_ref") == "BAG-INSTANCE-B09-001")
	_check("EFFECTIVE_CARRY_EXTERNAL", hud.inventory_shell.carry_projection_label().contains("18.5/80"))
	_check("ACTIVE_WEAPON_TWO_EXTERNAL", hud.active_weapon_slot() == 2)
	_check("DUPLICATE_INVENTORY_SNAPSHOT_REJECTED", inventory_client.project_inventory_snapshot(bag_snapshot).get("reason") == "STALE_OR_DUPLICATE_INVENTORY_SNAPSHOT")
	var stale: Dictionary = _inventory_snapshot(SESSION_REF, 0, false)
	_check("STALE_INVENTORY_SNAPSHOT_REJECTED", inventory_client.project_inventory_snapshot(stale).get("reason") == "STALE_OR_DUPLICATE_INVENTORY_SNAPSHOT")
	var invalid_slots: Dictionary = _inventory_snapshot(SESSION_REF, 2, true)
	invalid_slots["weapon_loadout"]["quick_slots"] = [{"slot": 1, "item_ref": "ONLY-ONE"}]
	_check("INVALID_QUICKSLOT_COUNT_REJECTED", inventory_client.project_inventory_snapshot(invalid_slots).get("reason") == "EXACTLY_TWO_WEAPON_QUICK_SLOTS_REQUIRED")
	var invalid_bag: Dictionary = _inventory_snapshot(SESSION_REF, 2, true)
	invalid_bag["bag"]["state"] = "DROPPED_AFTER_DEATH"
	_check("B10_BAG_STATE_REJECTED_IN_B09", inventory_client.project_inventory_snapshot(invalid_bag).get("reason") == "INVALID_BAG_STATE")
	_check("BAG_EQUIP_WHILE_EQUIPPED_REJECTED", inventory_client.request_bag_equip("BAG-OTHER").get("reason") == "BAG_ALREADY_EQUIPPED_IN_EXTERNAL_PROJECTION")
	_check("NO_DEATH_DROP_LOGIC_METHOD", not inventory_client.has_method("drop_bag_on_death"))
	_check("NO_BAG_WATER_TTL_METHOD", not inventory_client.has_method("start_bag_water_ttl"))
	_check("NO_RESPAWN_METHOD", not inventory_client.has_method("respawn_player"))


func _test_modal_input_safety() -> void:
	hud.close_active_modal()
	var open_inventory: Dictionary = main.handle_action_event(_key_event(KEY_I))
	_check("I_OPENS_INVENTORY", open_inventory.get("status") == "PASS" and hud.is_inventory_open() and main.menu_open())
	_check("INVENTORY_NOT_PERMANENT", hud.inventory_shell.visible)
	var slot_before: int = hud.active_weapon_slot()
	var zoom_before: float = camera_rig.target_distance_m()
	var wheel: Dictionary = main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_DOWN, false))
	_check("INVENTORY_WHEEL_PASS", wheel.get("status") == "PASS")
	_check("INVENTORY_WHEEL_SCROLL", wheel.get("intent") == "MENU_SCROLL")
	_check("INVENTORY_WHEEL_NO_WEAPON", hud.active_weapon_slot() == slot_before)
	_check("INVENTORY_WHEEL_NO_ZOOM", is_equal_approx(camera_rig.target_distance_m(), zoom_before))
	var key_one: Dictionary = main.handle_action_event(_key_event(KEY_1))
	_check("INVENTORY_CONSUMES_WEAPON_KEY", key_one.get("intent") == "UI_INPUT_CONSUMED")
	_check("INVENTORY_WEAPON_KEY_NO_CHANGE", hud.active_weapon_slot() == slot_before)
	var key_e: Dictionary = main.handle_action_event(_key_event(KEY_E))
	_check("INVENTORY_CONSUMES_E", key_e.get("intent") == "UI_INPUT_CONSUMED")
	var key_space: Dictionary = main.handle_action_event(_key_event(KEY_SPACE))
	_check("INVENTORY_CONSUMES_SPACE", key_space.get("intent") == "UI_INPUT_CONSUMED")
	var selected_before: String = main.selected_target_ref()
	var player_position_before: Vector3 = player.global_position
	var world_click: Dictionary = main.handle_pointer_event(_mouse_button(MOUSE_BUTTON_LEFT, Vector2(480, 270)))
	_check("MODAL_CONSUMES_WORLD_CLICK", world_click.get("intent") == "UI_POINTER_CONSUMED")
	_check("MODAL_WORLD_CLICK_NO_SELECTION", main.selected_target_ref() == selected_before)
	_check("MODAL_WORLD_CLICK_NO_MOVEMENT", player.global_position.is_equal_approx(player_position_before))
	var esc: Dictionary = main.handle_action_event(_key_event(KEY_ESCAPE))
	_check("ESC_CLOSES_INVENTORY", esc.get("intent") == "CLOSE_ACTIVE_MODAL")
	_check("ESC_CLOSE_NO_GAMEPLAY_CHANGE", esc.get("gameplay_state_changed") == false)
	_check("INVENTORY_CLOSED", not hud.is_inventory_open() and not main.menu_open())
	player.global_position = vendor.global_position + Vector3(1.25, 0.0, 0.0)
	await _wait_physics_frames(2)
	var vendor_open: Dictionary = vendor_client.begin_vendor_interaction(vendor, "B09_MODAL_TEST")
	_check("VENDOR_MODAL_REOPEN_PASS", vendor_open.get("status") == "PASS")
	var vendor_slot_before: int = hud.active_weapon_slot()
	var vendor_zoom_before: float = camera_rig.target_distance_m()
	var vendor_wheel: Dictionary = main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_UP, true))
	_check("VENDOR_WHEEL_SCROLL_ONLY", vendor_wheel.get("intent") == "MENU_SCROLL")
	_check("VENDOR_WHEEL_NO_WEAPON", hud.active_weapon_slot() == vendor_slot_before)
	_check("VENDOR_WHEEL_NO_ZOOM", is_equal_approx(camera_rig.target_distance_m(), vendor_zoom_before))
	_check("VENDOR_WORLD_NOT_PAUSED", not get_tree().paused)
	hud.close_active_modal()


func _test_quest_loop() -> void:
	player.stop_local_prediction()
	player.global_position = quest_npc.global_position + Vector3(1.3, 0.0, 0.0)
	await _wait_physics_frames(3)
	var left_result: Dictionary = main.handle_pointer_event(_mouse_button(
		MOUSE_BUTTON_LEFT, main.world_to_screen(quest_npc.pointer_world_position())
	))
	_check("QUEST_NPC_LEFT_SELECT_PASS", left_result.get("status") == "PASS", JSON.stringify(left_result))
	_check("QUEST_NPC_SELECTED", main.selected_target_ref() == quest_npc.target_ref)
	_check("QUEST_NPC_LEFT_NO_ACCEPT", quest_client.last_intent().is_empty())
	var right_result: Dictionary = main.handle_pointer_event(_mouse_button(
		MOUSE_BUTTON_RIGHT, main.world_to_screen(quest_npc.pointer_world_position())
	))
	_check("QUEST_NPC_RIGHT_PASS", right_result.get("status") == "PASS", JSON.stringify(right_result))
	_check("QUEST_NPC_RIGHT_CLICK_ONLY", right_result.get("input_mode") == "CLICK_ONLY")
	var quest_open: Dictionary = right_result.get("quest_client_result", {})
	_check("QUEST_UI_OPEN_PASS", quest_open.get("intent") == "OPEN_QUEST_UI", JSON.stringify(quest_open))
	_check("QUEST_UI_VISIBLE", hud.is_quest_open() and hud.active_modal() == "QUEST")
	_check("QUEST_OFFER_REF", hud.quest_panel.current_quest_ref() == QUEST_REF)
	_check("QUEST_OPEN_NO_ACCEPT", quest_open.get("quest_accepted") == false)
	_check("QUEST_OPEN_NO_COMPLETE", quest_open.get("quest_completed") == false)
	_check("QUEST_OPEN_NO_REWARD", quest_open.get("reward_granted") == false)
	var accept: Dictionary = quest_client.request_accept(QUEST_REF)
	_check("QUEST_ACCEPT_INTENT_PASS", accept.get("status") == "PASS", JSON.stringify(accept))
	_check("QUEST_ACCEPT_INTENT_NAME", accept.get("intent") == "ACCEPT_QUEST")
	_check("QUEST_ACCEPT_NO_LOCAL_OBJECTIVE", accept.get("objective_mutated_locally") == false)
	_check("QUEST_ACCEPT_NO_LOCAL_COMPLETION", accept.get("quest_completed_locally") == false)
	_check("QUEST_ACCEPT_NO_LOCAL_REWARD", accept.get("reward_granted_locally") == false)
	_check("QUEST_ACCEPT_NO_LOCAL_XP", accept.get("xp_granted_locally") == false)
	var accept_params: Dictionary = accept.get("intent_envelope", {}).get("envelope", {}).get("params", {})
	_check("QUEST_ACCEPT_REF", accept_params.get("quest_ref") == QUEST_REF)
	_check("QUEST_ACCEPT_NO_PLAYER_REF", not accept_params.has("player_ref"))
	_check("QUEST_ACCEPT_NO_COMPLETION_FIELD", not accept_params.has("quest_completion"))
	_check("QUEST_ACCEPT_NO_REWARD_FIELD", not accept_params.has("reward"))
	_check("QUEST_ACCEPT_DOES_NOT_CREATE_ACTIVE_LOCALLY", quest_client.projected_quest(QUEST_REF).is_empty())
	_check("QUEST_DECLINE_NOT_INVENTED", quest_client.request_decline(QUEST_REF).get("reason") == "QUEST_DECLINE_NOT_CONTRACTED_IN_STAGE16A_B09")
	var bad_choice: Dictionary = quest_client.request_choice(QUEST_REF, "CHOICE-INVENTED")
	_check("QUEST_UNKNOWN_CHOICE_REJECTED", bad_choice.get("reason") == "QUEST_CHOICE_NOT_PROJECTED")
	var choice: Dictionary = quest_client.request_choice(QUEST_REF, "CHOICE-S12-ORIENTATION-ACCEPT")
	_check("QUEST_PROJECTED_CHOICE_PASS", choice.get("status") == "PASS")
	_check("QUEST_CHOICE_NO_LOCAL_COMPLETION", choice.get("quest_completed_locally") == false)
	var active_snapshot: Dictionary = _quest_state_snapshot(SESSION_REF, 0, "ACTIVE", "PENDING")
	var active_result: Dictionary = quest_client.project_quest_snapshot(active_snapshot)
	_check("QUEST_ACTIVE_EXTERNAL_PASS", active_result.get("status") == "PASS", JSON.stringify(active_result))
	_check("QUEST_ACTIVE_STATE", quest_client.projected_quest(QUEST_REF).get("state") == "ACTIVE")
	_check("QUEST_ACTIVE_OBJECTIVE_PENDING", quest_client.projected_quest(QUEST_REF).get("objectives", [])[0].get("state") == "PENDING")
	_check("QUEST_ACTIVE_NO_LOCAL_COMPLETION", active_result.get("quest_completion_decided_locally") == false)
	_check("QUEST_ACTIVE_NO_LOCAL_REWARD", active_result.get("reward_granted_locally") == false)
	var duplicate_active: Dictionary = quest_client.project_quest_snapshot(active_snapshot)
	_check("QUEST_DUPLICATE_STATE_REJECTED", duplicate_active.get("reason") == "STALE_OR_DUPLICATE_QUEST_STATE_SNAPSHOT")
	var wrong_state: Dictionary = _quest_state_snapshot(WRONG_SESSION_REF, 1, "ACTIVE", "PENDING")
	_check("QUEST_WRONG_SESSION_STATE_REJECTED", quest_client.project_quest_snapshot(wrong_state).get("reason") == "SESSION_MISMATCH")
	var objective_update: Dictionary = _quest_state_snapshot(SESSION_REF, 1, "READY_TO_TURN_IN", "COMPLETE")
	var objective_result: Dictionary = quest_client.project_quest_snapshot(objective_update)
	_check("QUEST_OBJECTIVE_EXTERNAL_UPDATE_PASS", objective_result.get("status") == "PASS")
	_check("QUEST_OBJECTIVE_EXTERNAL_COMPLETE", quest_client.projected_quest(QUEST_REF).get("objectives", [])[0].get("state") == "COMPLETE")
	_check("QUEST_READY_EXTERNAL", quest_client.projected_quest(QUEST_REF).get("state") == "READY_TO_TURN_IN")
	for index: int in range(4):
		var event := _quest_event_payload("QUEST-EVENT-%d" % index, "Quest update %d" % index)
		var event_result: Dictionary = quest_client.project_quest_event(event)
		_check("QUEST_EVENT_%d_PASS" % index, event_result.get("status") == "PASS", JSON.stringify(event_result))
		if index == 0:
			_check("QUEST_EVENT_NO_LOCAL_PROGRESS", event_result.get("local_progress_changed") == false)
			_check("QUEST_EVENT_NO_LOCAL_REWARD", event_result.get("local_reward_granted") == false)
		_quest_event_sequence += 1
	_check("QUEST_FEEDBACK_MAX_THREE", hud.quest_feedback_count() == 3)
	_check("QUEST_FEEDBACK_PRIORITY", hud.contract_snapshot().get("quest_feedback_priority") == 60)
	var duplicate_event := _quest_event_payload("QUEST-EVENT-DUP", "Duplicate")
	duplicate_event["event_sequence"] = _quest_event_sequence - 1
	_check("QUEST_STALE_EVENT_REJECTED", quest_client.project_quest_event(duplicate_event).get("reason") == "STALE_OR_DUPLICATE_QUEST_EVENT")
	var wrong_event := _quest_event_payload("QUEST-EVENT-WRONG-SESSION", "Wrong")
	wrong_event["session_ref"] = WRONG_SESSION_REF
	_check("QUEST_WRONG_SESSION_EVENT_REJECTED", quest_client.project_quest_event(wrong_event).get("reason") == "SESSION_MISMATCH")
	var completed_snapshot: Dictionary = _quest_state_snapshot(SESSION_REF, 2, "COMPLETED", "COMPLETE")
	completed_snapshot["quests"][0]["reward_projection"] = {"externally_confirmed": true, "reward_ref": "REWARD-S12-ORIENTATION"}
	var completed_result: Dictionary = quest_client.project_quest_snapshot(completed_snapshot)
	_check("QUEST_COMPLETION_EXTERNAL_PASS", completed_result.get("status") == "PASS")
	_check("QUEST_COMPLETED_EXTERNAL_STATE", quest_client.projected_quest(QUEST_REF).get("state") == "COMPLETED")
	_check("QUEST_COMPLETION_NOT_LOCAL", completed_result.get("quest_completion_decided_locally") == false)
	_check("QUEST_REWARD_NOT_LOCAL", completed_result.get("reward_granted_locally") == false)
	_check("QUEST_XP_NOT_LOCAL", completed_result.get("xp_granted_locally") == false)
	_check("QUEST_WORLD_NOT_PAUSED", not get_tree().paused)
	var quest_slot_before: int = hud.active_weapon_slot()
	var quest_zoom_before: float = camera_rig.target_distance_m()
	var quest_wheel: Dictionary = main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_DOWN, true))
	_check("QUEST_WHEEL_SCROLL_ONLY", quest_wheel.get("intent") == "MENU_SCROLL")
	_check("QUEST_WHEEL_NO_WEAPON", hud.active_weapon_slot() == quest_slot_before)
	_check("QUEST_WHEEL_NO_ZOOM", is_equal_approx(camera_rig.target_distance_m(), quest_zoom_before))
	hud.close_active_modal()
	var e_reopen: Dictionary = main.handle_action_event(_key_event(KEY_E))
	_check("QUEST_E_REOPEN_PASS", e_reopen.get("status") == "PASS")
	_check("QUEST_E_REOPEN_STATE", e_reopen.get("quest_client_result", {}).get("intent") == "OPEN_QUEST_UI")
	hud.close_active_modal()


func _test_b01_b08_client_regressions() -> void:
	_check("B01_SESSION_ACTIVE", (_session()).has_active_session())
	_check("B01_BRIDGE_URL_PRESERVED", (_bridge()).server_url() == "http://127.0.0.1:8000")
	_check("B02_CLICK_TO_MOVE_AUTHORITY_PRESERVED", main.contract_snapshot().get("gameplay_authority_in_gdscript") == false)
	_check("B03_TARGET_SELECTION_PRESERVED", not main.selected_target_ref().is_empty())
	var target_before: String = main.selected_target_ref()
	var combat_feedback: Dictionary = hud.present_combat_event({
		"token": "COMBAT_HIT",
		"target_ref": enemy.target_ref,
		"confirmed_externally": true,
	})
	_check("B06_COMBAT_FEEDBACK_PASS", combat_feedback.get("status") == "PASS", JSON.stringify(combat_feedback))
	_check("B06_FEEDBACK_TARGET_STABLE", main.selected_target_ref() == target_before)
	_check("B06_FEEDBACK_NO_GAMEPLAY_RESULT", combat_feedback.get("gameplay_result_changed") == false)
	_check("B04_TERRAIN_FOUNDATION_PRESERVED", main.contract_snapshot().get("terrain_foundation_present") == true)
	_check("B05_STAMINA_RADIAL_PRESERVED", hud.stamina_ring.contract_snapshot().get("shape") == "CIRCLE_RADIAL" and hud.stamina_ring.contract_snapshot().get("color") == "SOFT_YELLOW")
	_check("B05_TWO_QUICK_SLOTS_PRESERVED", hud.weapon_quick_slots.slot_count() == 2)
	_check("B05_DIALOGUE_NO_NEXT", hud.contract_snapshot().get("next_button") == false)
	_check("B07_GROUND_LOOT_CLIENT_PRESERVED", main.contract_snapshot().get("ground_loot_client_present") == true)
	_check("B07_PICKUP_RADIUS_PRESERVED", is_equal_approx(float(pickup_client.contract_snapshot().get("pickup_radius_m")), 0.5))
	_check("B08_GATHERING_CLIENT_PRESERVED", main.contract_snapshot().get("gathering_client_present") == true)
	_check("B08_GATHERING_GROUND_LOOT_ONLY", gathering_client.contract_snapshot().get("output_delivery") == "GROUND_LOOT_B07_ONLY")
	_check("B08_NO_GATHER_INVENTORY_AUTHORITY", gathering_client.contract_snapshot().get("inventory_authority") == false)
	_check("AUTO_PICKUP_UI_PRESERVED", hud.inventory_shell.contract_snapshot().get("bag_slot_present") == true)
	_check("AUTO_PICKUP_DOES_NOT_PAUSE_WORLD", not get_tree().paused)
	_check("UI_FAMILY_UNIFIED", hud.contract_snapshot().get("ui_family") == "WHITE_OFF_WHITE_ROUNDED_CLEAN_CONSOLE")
	_check("UI_MAX_QUEST_FEEDBACK_THREE", hud.contract_snapshot().get("max_simultaneous_quest_feedback") == 3)
	_check("NO_GAMEPLAY_AUTHORITY_MAIN", main.contract_snapshot().get("vendor_price_authority_in_gdscript") == false and main.contract_snapshot().get("quest_completion_authority_in_gdscript") == false)


func _test_reconnect_resync(session: AndromedaClientSession) -> void:
	hud.close_active_modal()
	var revoke: Dictionary = session.revoke_session()
	_check("RECONNECT_REVOKE_PASS", revoke.get("status") == "PASS")
	_check("RECONNECT_VENDOR_NEEDS_RESYNC", vendor_client.needs_resync())
	_check("RECONNECT_INVENTORY_NEEDS_RESYNC", inventory_client.needs_resync())
	_check("RECONNECT_QUEST_NEEDS_RESYNC", quest_client.needs_resync())
	var rebind: Dictionary = session.bind_session(SESSION_REF_2)
	_check("RECONNECT_BIND_NEW_SESSION_PASS", rebind.get("status") == "PASS")
	_check("SENSITIVE_INVENTORY_BLOCKED_BEFORE_RESYNC", inventory_client.request_equipment_intent("ITEM", "ARMOR", true).get("reason") == "INVENTORY_RESYNC_REQUIRED")
	_check("SENSITIVE_QUEST_BLOCKED_BEFORE_RESYNC", quest_client.request_accept(QUEST_REF).get("reason") == "QUEST_RESYNC_REQUIRED")
	player.global_position = vendor.global_position + Vector3(1.25, 0.0, 0.0)
	var open_result: Dictionary = vendor_client.begin_vendor_interaction(vendor, "RECONNECT_TEST")
	_check("RECONNECT_VENDOR_UI_CAN_OPEN_PRESENTATION", open_result.get("status") == "PASS")
	_check("SENSITIVE_QUOTE_BLOCKED_BEFORE_RESYNC", vendor_client.request_quote(VENDOR_REF, BUY_ITEM_REF, "BUY", 1).get("reason") == "VENDOR_RESYNC_REQUIRED")
	var stale_session_stock: Dictionary = _stock_snapshot(SESSION_REF, 0)
	_check("OLD_SESSION_STOCK_REJECTED_AFTER_RECONNECT", vendor_client.project_stock_snapshot(stale_session_stock).get("reason") == "SESSION_MISMATCH")
	var new_stock: Dictionary = vendor_client.project_stock_snapshot(_stock_snapshot(SESSION_REF_2, 0))
	_check("RECONNECT_VENDOR_STOCK_RESYNC_PASS", new_stock.get("status") == "PASS")
	var new_inventory: Dictionary = inventory_client.project_inventory_snapshot(_inventory_snapshot(SESSION_REF_2, 0, true))
	_check("RECONNECT_INVENTORY_RESYNC_PASS", new_inventory.get("status") == "PASS")
	var new_offers: Dictionary = quest_client.project_offer_snapshot(_offer_snapshot(SESSION_REF_2, 0))
	_check("RECONNECT_QUEST_RESYNC_PASS", new_offers.get("status") == "PASS")
	_check("RECONNECT_VENDOR_READY", not vendor_client.needs_resync())
	_check("RECONNECT_INVENTORY_READY", not inventory_client.needs_resync())
	_check("RECONNECT_QUEST_READY", not quest_client.needs_resync())
	var quote_after_resync: Dictionary = vendor_client.request_quote(VENDOR_REF, BUY_ITEM_REF, "BUY", 1)
	_check("SENSITIVE_QUOTE_ALLOWED_AFTER_RESYNC", quote_after_resync.get("status") == "PASS")
	_check("RECONNECT_NO_LOCAL_MUTATION", quote_after_resync.get("wallet_mutated_locally") == false and quote_after_resync.get("inventory_mutated_locally") == false)
	hud.close_active_modal()


func _trade_rejection_cycle(label: String, operation: String, item_ref: String, quantity: int, reason: String) -> void:
	var request: Dictionary = vendor_client.request_quote(VENDOR_REF, item_ref, operation, quantity)
	_check("%s_QUOTE_REQUEST_PASS" % label, request.get("status") == "PASS", JSON.stringify(request))
	var quote_ref: String = "QUOTE-%s-%03d" % [label, _quote_sequence]
	var quote: Dictionary = _quote_payload(_quote_sequence, quote_ref, request, 11.0 * quantity)
	var quote_result: Dictionary = vendor_client.project_quote(quote)
	_check("%s_QUOTE_PROJECTION_PASS" % label, quote_result.get("status") == "PASS", JSON.stringify(quote_result))
	_quote_sequence += 1
	var execute: Dictionary = vendor_client.execute_trade(
		quote_ref, VENDOR_REF, item_ref, operation, quantity, "CONFIRM-%s" % label, true
	)
	_check("%s_EXECUTE_PASS" % label, execute.get("status") == "PASS", JSON.stringify(execute))
	var projection_before: Dictionary = inventory_client.projected_state()
	var result: Dictionary = _trade_result_payload(execute, "REJECTED", reason)
	var projected: Dictionary = vendor_client.project_trade_result(result)
	_check("%s_REJECTION_PROJECTED" % label, projected.get("status") == "PASS", JSON.stringify(projected))
	_check("%s_REASON_PROJECTED" % label, projected.get("reason") == reason)
	_check("%s_NO_LOCAL_INVENTORY_CHANGE" % label, inventory_client.projected_state() == projection_before)
	_check("%s_NO_LOCAL_WALLET_CHANGE" % label, projected.get("wallet_mutated_locally") == false)
	_trade_result_sequence += 1


func _stock_snapshot(session_ref_value: String, sequence: int) -> Dictionary:
	return {
		"server_authoritative": true,
		"session_ref": session_ref_value,
		"snapshot_sequence": sequence,
		"vendor_ref": VENDOR_REF,
		"items": [
			{"item_ref": BUY_ITEM_REF, "display_name": "Item de compra placeholder", "operation_flags": ["BUY"]},
			{"item_ref": "ITEM-S13-SECOND-PLACEHOLDER", "display_name": "Segundo item placeholder", "operation_flags": ["BUY"]},
		],
	}


func _quote_payload(sequence: int, quote_ref: String, request: Dictionary, total_price: float) -> Dictionary:
	return {
		"server_authoritative": true,
		"session_ref": SESSION_REF,
		"quote_sequence": sequence,
		"quote_ref": quote_ref,
		"vendor_ref": str(request.get("vendor_ref", "")),
		"item_ref": str(request.get("item_ref", "")),
		"direction": str(request.get("operation", "")),
		"quantity": int(request.get("quantity", 0)),
		"unit_price": total_price / maxf(1.0, float(request.get("quantity", 1))),
		"total_price": total_price,
		"currency": "CURRENCY-S13",
		"active": true,
	}


func _trade_result_payload(execute: Dictionary, external_result: String, reason: String) -> Dictionary:
	return {
		"server_authoritative": true,
		"session_ref": SESSION_REF,
		"result_sequence": _trade_result_sequence,
		"event_ref": str(execute.get("event_ref", "")),
		"quote_ref": str(execute.get("quote_ref", "")),
		"result": external_result,
		"reason": reason,
		"wallet_revision": 100 + _trade_result_sequence,
		"inventory_revision": 200 + _trade_result_sequence,
	}


func _inventory_snapshot(session_ref_value: String, sequence: int, with_bag: bool) -> Dictionary:
	return {
		"server_authoritative": true,
		"session_ref": session_ref_value,
		"snapshot_sequence": sequence,
		"base_inventory": {
			"owner_ref": "PROFILE-B09",
			"slot_limit": 8,
			"weight_limit": 20.0,
			"stacks": [{"item_ref": BASE_ITEM_REF, "quantity": 2, "protected": false}],
		},
		"bag": {
			"state": "BAG_EQUIPPED" if with_bag else "NO_BAG",
			"bag_ref": "BAG-INSTANCE-B09-001" if with_bag else "",
			"capacity_slots": 30 if with_bag else 0,
			"capacity_weight": 80.0 if with_bag else 0.0,
			"contents": [{"item_ref": BAG_ITEM_REF, "quantity": 3}] if with_bag else [],
		},
		"equipment": {
			"slots": {"ARMOR": "ARMOR-B09", "CLOTHES": "CLOTHES-B09"},
			"protected_critical_refs": ["QUEST-ITEM-B09"],
		},
		"weapon_loadout": {
			"quick_slots": [
				{"slot": 1, "item_ref": "WEAPON-B09-ONE"},
				{"slot": 2, "item_ref": "WEAPON-B09-TWO"},
			],
			"active_slot": 2 if with_bag else 1,
		},
		"carry": {
			"current_weight": 18.5 if with_bag else 4.0,
			"max_weight": 80.0 if with_bag else 20.0,
			"used_slots": 2 if with_bag else 1,
			"max_slots": 38 if with_bag else 8,
		},
		"routing": {
			"source": "EQUIPPED_BAG" if with_bag else "BASE_INVENTORY",
			"effective_inventory_owner_ref": "BAG-INSTANCE-B09-001" if with_bag else "PROFILE-B09",
			"currency_wallet_owner_ref": "PROFILE-B09",
		},
	}


func _offer_snapshot(session_ref_value: String, sequence: int) -> Dictionary:
	return {
		"server_authoritative": true,
		"session_ref": session_ref_value,
		"snapshot_sequence": sequence,
		"offers": [{
			"quest_ref": QUEST_REF,
			"npc_ref": quest_npc.target_ref,
			"title": "Orientação de Varga",
			"objectives": [{"objective_ref": "OBJ-S12-ORIENTATION", "text": "Objetivo contratual", "state": "PENDING"}],
			"choices": [{"choice_ref": "CHOICE-S12-ORIENTATION-ACCEPT", "label": "Aceitar"}],
		}],
	}


func _quest_state_snapshot(session_ref_value: String, sequence: int, state: String, objective_state: String) -> Dictionary:
	return {
		"server_authoritative": true,
		"session_ref": session_ref_value,
		"snapshot_sequence": sequence,
		"quests": [{
			"quest_ref": QUEST_REF,
			"npc_ref": quest_npc.target_ref,
			"title": "Orientação de Varga",
			"state": state,
			"objectives": [{"objective_ref": "OBJ-S12-ORIENTATION", "text": "Objetivo contratual", "state": objective_state}],
			"choices": [],
		}],
	}


func _quest_event_payload(event_ref: String, feedback_text: String) -> Dictionary:
	return {
		"server_authoritative": true,
		"session_ref": SESSION_REF,
		"event_sequence": _quest_event_sequence,
		"event_ref": event_ref,
		"quest_ref": QUEST_REF,
		"feedback_text": feedback_text,
	}


func _node_tree_has_name(root: Node, fragment: String) -> bool:
	if root.name.to_lower().contains(fragment.to_lower()):
		return true
	for child: Node in root.get_children():
		if _node_tree_has_name(child, fragment):
			return true
	return false


func _mouse_button(button_index: int, position: Vector2) -> InputEventMouseButton:
	var event := InputEventMouseButton.new()
	event.button_index = button_index as MouseButton
	event.position = position
	event.global_position = position
	event.pressed = true
	return event


func _wheel_event(button_index: int, shift_pressed: bool) -> InputEventMouseButton:
	var event := _mouse_button(button_index, Vector2(480, 270))
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
		"gate": "B09_VENDOR_INVENTORY_BAG_QUEST_LOOP",
		"acceptance_scope_pass": [],
		"partial_evidence_only": ["G16B-03", "G16B-06", "G16B-16", "G16B-23", "G16B-26"],
		"regression_evidence": ["G16B-10", "G16B-11", "G16B-12", "G16B-13", "G16B-15", "G16B-20", "G16B-21", "G16B-22"],
		"not_executed": ["G16B-17", "G16B-18", "G16B-19", "G16B-28"],
		"authoritative_roundtrip_executed": false,
		"backend_status": "NOT_AVAILABLE",
		"fixtures_are_external_projection_contract_tests_only": true,
		"b10_started": false,
		"authority": "GODOT_B09_CLIENT_ORCHESTRATION_PRESENTATION_ONLY",
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_B09_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_B09_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_B09_SUMMARY: %s" % JSON.stringify(summary))
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
