extends Node

const SESSION_REF := "GODOT-AUTHORITY-ECONOMY-QUEST-V080"
const WAIT_TIMEOUT_S := 20.0

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _checks: int = 0
var _failures: Array[String] = []
var _bind_results: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []
var _results: Array[Dictionary] = []
var _rejections: Array[String] = []
var _quotes_projected: Array[Dictionary] = []
var _trades_projected: Array[Dictionary] = []
var _inventory_projected: Array[Dictionary] = []
var _quests_projected: Array[Dictionary] = []


func _ready() -> void:
	await _run_gate()


func _run_gate() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_check("SESSION_AUTOLOAD", session != null)
	_check("BRIDGE_AUTOLOAD", bridge != null)
	_check("MAIN_B09_CLIENTS", main != null and main.vendor_client != null and main.inventory_client != null and main.quest_client != null)
	if session == null or bridge == null or main == null:
		await _finish()
		return
	bridge.authority_session_bound.connect(func(result: Dictionary) -> void:
		_bind_results.append(result.duplicate(true))
	)
	bridge.snapshot_applied.connect(func(snapshot: Dictionary) -> void:
		_snapshots.append(snapshot.duplicate(true))
	)
	bridge.command_result_received.connect(func(result: Dictionary) -> void:
		_results.append(result.duplicate(true))
	)
	bridge.command_rejected.connect(func(reason: String) -> void:
		_rejections.append(reason)
	)
	main.vendor_client.quote_projected.connect(func(result: Dictionary) -> void:
		_quotes_projected.append(result.duplicate(true))
	)
	main.vendor_client.trade_result_projected.connect(func(result: Dictionary) -> void:
		_trades_projected.append(result.duplicate(true))
	)
	main.inventory_client.inventory_projected.connect(func(result: Dictionary) -> void:
		_inventory_projected.append(result.duplicate(true))
	)
	main.quest_client.quest_projection_changed.connect(func(result: Dictionary) -> void:
		_quests_projected.append(result.duplicate(true))
	)

	if session.has_active_session():
		session.revoke_session()
	_check("LOCAL_SESSION_BIND", session.bind_session(SESSION_REF).get("status") == "PASS")
	_check("AUTHORITY_BIND_STARTED", bridge.bind_authoritative_session().get("status") == "PASS")
	if not await _wait_for_size(_bind_results, 1):
		_failures.append("AUTHORITY_BIND_TIMEOUT")
		await _finish()
		return
	if not await _wait_for_size(_snapshots, 1):
		_failures.append("INITIAL_SNAPSHOT_TIMEOUT")
		await _finish()
		return
	var initial: Dictionary = _snapshots.back()
	var enabled: Array = _bind_results[0].get("enabled_commands", [])
	for command: String in ["REQUEST_TRADE_QUOTE", "EXECUTE_TRADE", "REQUEST_EQUIP_BAG", "ACCEPT_QUEST"]:
		_check("COMMAND_ENABLED_%s" % command, enabled.has(command), JSON.stringify(enabled))
	_check("SNAPSHOT_SERVER_AUTHORITATIVE", initial.get("server_authoritative") == true)
	_check("INVENTORY_PROJECTION_PRESENT", initial.get("inventory_projection") is Dictionary)
	_check("VENDOR_STOCK_PRESENT", initial.get("vendor_stock") is Array and not (initial.get("vendor_stock") as Array).is_empty())
	_check("ECONOMY_WALLET_PRESENT", initial.get("economy_projection", {}).get("wallet") is Dictionary)
	_check("QUEST_PROJECTION_PRESENT", initial.get("quest_projection") is Dictionary)
	_check("CLIENT_INVENTORY_PROJECTED", await _wait_for_size(_inventory_projected, 1))
	_check("CLIENT_QUEST_PROJECTIONS", await _wait_for_size(_quests_projected, 2))
	var inventory: Dictionary = main.inventory_client.projected_state()
	_check("BASE_INVENTORY_REDUCED_EIGHT", int(inventory.get("base_inventory", {}).get("slot_limit", 0)) == 8, JSON.stringify(inventory))
	_check("EXACTLY_TWO_QUICK_SLOTS", (inventory.get("weapon_loadout", {}).get("quick_slots", []) as Array).size() == 2)
	_check("ONE_ACTIVE_QUICK_SLOT", int(inventory.get("weapon_loadout", {}).get("active_slot", 0)) in [1, 2])
	_check("ROUTING_EXTERNAL", not str(inventory.get("routing", {}).get("effective_inventory_owner_ref", "")).is_empty())
	_check("NO_LOCAL_CAPACITY_AUTHORITY", main.inventory_client.contract_snapshot().get("capacity_authority") == false)

	var commands_before_open: int = _results.size()
	main.player.global_position = main.vendor_npc.global_position + Vector3(0.65, 0.0, 0.0)
	await _wait_physics_frames(3)
	var open: Dictionary = main.vendor_client.begin_vendor_interaction(main.vendor_npc, "AUTHORITY_GATE")
	_check("VENDOR_PHYSICAL_OPEN_PASS", open.get("status") == "PASS", JSON.stringify(open))
	_check("VENDOR_UI_OPEN", main.hud.is_vendor_open())
	_check("OPEN_DOES_NOT_PURCHASE", _results.size() == commands_before_open)
	_check("OPEN_DOES_NOT_REQUEST_QUOTE", open.get("quote_requested") == false)
	_check("OPEN_DOES_NOT_EXECUTE", open.get("trade_executed") == false)
	var stock: Array = (initial.get("vendor_stock") as Array)[0].get("items", [])
	var stock_item: Dictionary = stock[0]
	var quote_result_start: int = _results.size()
	var execute_count_before_quote: int = _command_count("EXECUTE_TRADE")
	var quote_projection_start: int = _quotes_projected.size()
	var quote_request: Dictionary = main.vendor_client.request_quote(
		main.vendor_npc.vendor_ref,
		str(stock_item.get("item_ref", "")),
		"BUY",
		1,
		str(stock_item.get("instance_ref", ""))
	)
	_check("QUOTE_REQUEST_PASS", quote_request.get("status") == "PASS", JSON.stringify(quote_request))
	_check("QUOTE_TRANSPORT_SUBMITTED", quote_request.get("transport_submitted") == true, JSON.stringify(quote_request))
	_check("QUOTE_NO_LOCAL_PRICE", quote_request.get("price_calculated_locally") == false)
	_check("QUOTE_NO_LOCAL_MUTATION", quote_request.get("wallet_mutated_locally") == false and quote_request.get("inventory_mutated_locally") == false)
	var quote_params: Dictionary = quote_request.get("intent_envelope", {}).get("envelope", {}).get("params", {})
	_check("QUOTE_CLIENT_NO_OWNER", not quote_params.has("owner_ref") and not quote_params.has("profile_ref"), JSON.stringify(quote_params))
	_check("QUOTE_CLIENT_NO_PRICE", not quote_params.has("unit_price") and not quote_params.has("total_price"))
	var quote: Dictionary = await _wait_for_command("REQUEST_TRADE_QUOTE", quote_result_start)
	_check("QUOTE_RESULT_RECEIVED", not quote.is_empty())
	_check("QUOTE_STAGE13_PASS", quote.get("status") == "PASS", JSON.stringify(quote))
	_check("QUOTE_SERVER_AUTHORITATIVE", quote.get("server_authoritative") == true)
	_check("QUOTE_PRICE_SERVER_SIDE", quote.get("price_evaluated_server_side") == true)
	_check("QUOTE_IDENTITY_STABLE", str(quote.get("vendor_ref", "")) == main.vendor_npc.vendor_ref and str(quote.get("item_ref", "")) == str(stock_item.get("item_ref", "")))
	_check("QUOTE_CLIENT_PROJECTED", await _wait_for_size(_quotes_projected, quote_projection_start + 1))
	_check("QUOTE_DOES_NOT_AUTO_EXECUTE", _command_count("EXECUTE_TRADE") == execute_count_before_quote)

	var trade_result_start: int = _results.size()
	var trade_projection_start: int = _trades_projected.size()
	var execute_request: Dictionary = main.vendor_client.execute_trade(
		str(quote.get("quote_ref", "")),
		str(quote.get("vendor_ref", "")),
		str(quote.get("item_ref", "")),
		str(quote.get("direction", "")),
		int(quote.get("quantity", 0)),
		"GODOT-B09-EXPLICIT-%d" % Time.get_ticks_usec(),
		true
	)
	_check("EXPLICIT_EXECUTE_REQUEST_PASS", execute_request.get("status") == "PASS", JSON.stringify(execute_request))
	_check("EXPLICIT_EXECUTE_TRANSPORT", execute_request.get("transport_submitted") == true, JSON.stringify(execute_request))
	_check("EXECUTE_NO_LOCAL_WALLET_INVENTORY", execute_request.get("wallet_mutated_locally") == false and execute_request.get("inventory_mutated_locally") == false)
	var execute_params: Dictionary = execute_request.get("intent_envelope", {}).get("envelope", {}).get("params", {})
	_check("EXECUTE_EXPLICIT_CONFIRMATION", execute_params.get("explicit_user_confirmation") == true and not str(execute_params.get("confirmation_ref", "")).is_empty())
	_check("EXECUTE_CLIENT_NO_OWNER", not execute_params.has("owner_ref") and not execute_params.has("inventory_owner_ref"))
	var trade: Dictionary = await _wait_for_command("EXECUTE_TRADE", trade_result_start)
	_check("TRADE_RESULT_RECEIVED", not trade.is_empty())
	_check("TRADE_STAGE16A_PASS", trade.get("status") == "PASS", JSON.stringify(trade))
	_check("TRADE_ACCEPTED_EXTERNAL", trade.get("result") == "ACCEPTED")
	_check("TRADE_OWNER_ROUTED_SERVER_SIDE", trade.get("owner_routing_evaluated_server_side") == true)
	_check("TRADE_CLIENT_PROJECTED", await _wait_for_size(_trades_projected, trade_projection_start + 1))
	var post_trade_snapshot_count: int = _snapshots.size() + 1
	_check("POST_TRADE_SNAPSHOT", await _wait_for_size(_snapshots, post_trade_snapshot_count))
	var post_trade: Dictionary = _snapshots.back()
	_check("WALLET_PROJECTED_AFTER_TRADE", post_trade.get("economy_projection", {}).get("wallet") is Dictionary)
	_check("INVENTORY_PROJECTED_AFTER_TRADE", post_trade.get("inventory_projection") is Dictionary)

	var no_confirm: Dictionary = main.vendor_client.execute_trade(
		str(quote.get("quote_ref", "")), str(quote.get("vendor_ref", "")),
		str(quote.get("item_ref", "")), str(quote.get("direction", "")),
		int(quote.get("quantity", 0)), "NO-CONFIRM", false
	)
	_check("NO_CONFIRM_REJECTED_LOCALLY", no_confirm.get("reason") == "EXPLICIT_USER_CONFIRMATION_REQUIRED")
	var forged: Dictionary = bridge.build_command_envelope("EXECUTE_TRADE", {"quote_ref": quote.get("quote_ref"), "owner_ref": "FORGED"})
	_check("FORGED_OWNER_REJECTED_CLIENT", forged.get("reason") == "CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN")

	var bag_before: String = str(main.inventory_client.bag_state())
	if bag_before == "NO_BAG":
		var bag_result_start: int = _results.size()
		var bag_request: Dictionary = main.inventory_client.request_bag_equip("UI-CORRELATION-BAG")
		_check("BAG_REQUEST_PASS", bag_request.get("status") == "PASS", JSON.stringify(bag_request))
		_check("BAG_TRANSPORT_SUBMITTED", bag_request.get("transport_submitted") == true)
		var bag_result: Dictionary = await _wait_for_command("REQUEST_EQUIP_BAG", bag_result_start)
		_check("BAG_STAGE16A_PASS", bag_result.get("status") == "PASS", JSON.stringify(bag_result))
		_check("BAG_CLIENT_REF_NOT_AUTHORITY", bag_result.get("client_bag_instance_ref_used_as_authority") == false)
		var bag_snapshot_count: int = _snapshots.size() + 1
		_check("BAG_POST_SNAPSHOT", await _wait_for_size(_snapshots, bag_snapshot_count))
	else:
		_check("BAG_ALREADY_REAL_EXTERNAL", bag_before == "BAG_EQUIPPED")
	var bag_projection: Dictionary = main.inventory_client.projected_state()
	_check("BAG_EQUIPPED_EXTERNAL", bag_projection.get("bag", {}).get("state") == "BAG_EQUIPPED", JSON.stringify(bag_projection))
	_check("BAG_EFFECTIVE_ROUTING_EXTERNAL", bag_projection.get("routing", {}).get("source") == "EQUIPPED_BAG")
	_check("QUICK_SLOTS_RETAINED_WITH_BAG", (bag_projection.get("weapon_loadout", {}).get("quick_slots", []) as Array).size() == 2)

	var quest_projection: Dictionary = _snapshots.back().get("quest_projection", {})
	var offers: Array = quest_projection.get("offers", [])
	if not offers.is_empty():
		var offer: Dictionary = offers[0]
		var quest_result_start: int = _results.size()
		var accept: Dictionary = main.quest_client.request_accept(str(offer.get("quest_ref", "")))
		_check("QUEST_ACCEPT_INTENT_PASS", accept.get("status") == "PASS", JSON.stringify(accept))
		_check("QUEST_ACCEPT_TRANSPORT", accept.get("transport_submitted") == true)
		var quest_result: Dictionary = await _wait_for_command("ACCEPT_QUEST", quest_result_start)
		_check("QUEST_STAGE12_PASS", quest_result.get("status") == "PASS", JSON.stringify(quest_result))
		_check("QUEST_ACTIVE_EXTERNAL", quest_result.get("quest", {}).get("state") == "ACTIVE")
		_check("QUEST_NO_LOCAL_COMPLETION_REWARD", quest_result.get("completion_decided_by_godot") == false and quest_result.get("reward_granted_by_godot") == false)
		var quest_snapshot_count: int = _snapshots.size() + 1
		_check("QUEST_POST_SNAPSHOT", await _wait_for_size(_snapshots, quest_snapshot_count))
		var post_quest: Dictionary = _snapshots.back().get("quest_projection", {})
		_check("QUEST_MOVED_TO_ACTIVE_PROJECTION", _contains_quest(post_quest.get("quests", []), str(offer.get("quest_ref", ""))))
	else:
		_check("QUESTS_ALREADY_EXTERNAL", not (quest_projection.get("quests", []) as Array).is_empty())

	var inventory_contract: Dictionary = main.inventory_client.contract_snapshot()
	var vendor_contract: Dictionary = main.vendor_client.contract_snapshot()
	var quest_contract: Dictionary = main.quest_client.contract_snapshot()
	_check("NO_GDSCRIPT_INVENTORY_OWNERSHIP", inventory_contract.get("inventory_transfer_authority") == false and inventory_contract.get("ownership_authority") == false)
	_check("NO_GDSCRIPT_VENDOR_PRICE_WALLET", vendor_contract.get("price_authority") == false and vendor_contract.get("wallet_authority") == false)
	_check("NO_GDSCRIPT_QUEST_COMPLETION_REWARD", quest_contract.get("completion_authority") == false and quest_contract.get("reward_authority") == false)
	_check("BRIDGE_FINAL_READY", await _wait_for_bridge_ready(bridge))
	await _finish()


func _contains_quest(values: Variant, quest_ref: String) -> bool:
	if not values is Array:
		return false
	for value: Variant in values:
		if value is Dictionary and str((value as Dictionary).get("quest_ref", "")) == quest_ref:
			return true
	return false


func _command_count(command: String) -> int:
	var count: int = 0
	for result: Dictionary in _results:
		if str(result.get("command", "")) == command:
			count += 1
	return count


func _wait_for_command(command: String, start_index: int) -> Dictionary:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		for index: int in range(start_index, _results.size()):
			if str(_results[index].get("command", "")) == command:
				return _results[index].duplicate(true)
		await get_tree().process_frame
	return {}


func _wait_for_bridge_ready(bridge: AndromedaRuntimeBridge) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		if bridge.connection_state().get("state") == AndromedaRuntimeBridge.STATE_READY:
			return true
		await get_tree().process_frame
	return false


func _wait_for_size(values: Array, expected: int) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while values.size() < expected and Time.get_ticks_usec() < deadline:
		await get_tree().process_frame
	return values.size() >= expected


func _wait_physics_frames(count: int) -> void:
	for _index: int in range(count):
		await get_tree().physics_frame


func _check(label: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(label if detail.is_empty() else "%s:%s" % [label, detail])


func _finish() -> void:
	await _wait_physics_frames(2)
	var summary := {
		"gate": "AUTHORITY_ECONOMY_INVENTORY_BAG_QUEST_ROUNDTRIP",
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"backend": "REAL_STAGE12_STAGE13_STAGE16A_AUTHORITY",
		"fixture_authority": false,
	}
	print("ANDROMEDA_STAGE16B_AUTHORITY_ECONOMY_QUEST_SUMMARY: ", JSON.stringify(summary))
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_AUTHORITY_ECONOMY_QUEST_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_AUTHORITY_ECONOMY_QUEST_GATE: FAIL %s" % JSON.stringify(_failures))
	var linger: float = _success_linger_seconds() if _failures.is_empty() else 8.0
	if linger > 0.0:
		await get_tree().create_timer(linger).timeout
	get_tree().quit(0 if _failures.is_empty() else 1)


func _success_linger_seconds() -> float:
	var configured: float = float(ProjectSettings.get_setting("andromeda/gate/success_linger_s", 240.0))
	for argument: String in OS.get_cmdline_user_args():
		if argument.begins_with("--gate-success-linger="):
			var raw: String = argument.trim_prefix("--gate-success-linger=")
			if raw.is_valid_float():
				return maxf(0.0, raw.to_float())
	return maxf(0.0, configured)
