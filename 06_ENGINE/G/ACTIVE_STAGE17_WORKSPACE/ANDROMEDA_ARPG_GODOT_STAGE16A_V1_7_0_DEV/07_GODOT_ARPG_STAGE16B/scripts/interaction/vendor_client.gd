extends Node
class_name AndromedaVendorClient

## B09 client orchestration for vendor approach, quote and explicit execute.
## Stage13/Stage16A remains authoritative for stock, price, wallet, ownership and trade.

signal vendor_opened(result: Dictionary)
signal quote_request_prepared(result: Dictionary)
signal quote_projected(result: Dictionary)
signal trade_request_prepared(result: Dictionary)
signal trade_result_projected(result: Dictionary)

const AUTHORITY := "GODOT_VENDOR_CLIENT_ORCHESTRATION_ONLY"
const BLOCKER_MASK := 1 | 128
const OPERATIONS: Array[String] = ["BUY", "SELL"]

var _main_runtime: AndromedaMainRuntime
var _player: AndromedaPlayerController
var _hud: AndromedaHUDController
var _registered_vendors: Dictionary = {}
var _pending_approach: Dictionary = {}
var _open_vendor_ref: String = ""
var _open_target_ref: String = ""
var _stock_by_vendor: Dictionary = {}
var _current_quote: Dictionary = {}
var _last_stock_sequence: int = -1
var _last_quote_sequence: int = -1
var _last_trade_result_sequence: int = -1
var _projection_session_ref: String = ""
var _processed_quote_refs: Dictionary = {}
var _processed_trade_events: Dictionary = {}
var _execute_by_confirmation: Dictionary = {}
var _quote_request_serial: int = 0
var _execute_serial: int = 0
var _last_quote_request: Dictionary = {}
var _last_execute_request: Dictionary = {}
var _wallet_projection_revision: int = 0
var _inventory_projection_revision: int = 0
var _needs_resync: bool = true
var _bound: bool = false


func _ready() -> void:
	process_physics_priority = 82


func _physics_process(_delta: float) -> void:
	if _bound:
		process_pending_approach_once()


func bind_runtime(
	main_runtime_value: AndromedaMainRuntime,
	player_value: AndromedaPlayerController,
	hud_value: AndromedaHUDController,
	vendors: Array[AndromedaVendorTarget]
) -> Dictionary:
	if main_runtime_value == null or player_value == null or hud_value == null:
		return _rejected("MAIN_PLAYER_HUD_REQUIRED")
	_main_runtime = main_runtime_value
	_player = player_value
	_hud = hud_value
	for vendor: AndromedaVendorTarget in vendors:
		if vendor != null:
			var registration: Dictionary = register_vendor(vendor)
			if registration.get("status") != "PASS":
				return registration
	if not _bound:
		var bridge: AndromedaRuntimeBridge = _bridge()
		if bridge != null:
			if not bridge.snapshot_applied.is_connected(_on_bridge_snapshot_applied):
				bridge.snapshot_applied.connect(_on_bridge_snapshot_applied)
			if not bridge.command_result_received.is_connected(_on_bridge_command_result_received):
				bridge.command_result_received.connect(_on_bridge_command_result_received)
		var session: AndromedaClientSession = _session()
		if session != null:
			if not session.session_bound.is_connected(_on_session_bound):
				session.session_bound.connect(_on_session_bound)
			if not session.session_revoked.is_connected(_on_session_revoked):
				session.session_revoked.connect(_on_session_revoked)
		_hud.vendor_panel.quote_requested.connect(_on_ui_quote_requested)
		_hud.vendor_panel.execute_requested.connect(_on_ui_execute_requested)
		_hud.vendor_panel.close_requested.connect(_on_ui_close_requested)
		_bound = true
	return {
		"status": "PASS",
		"vendor_count": _registered_vendors.size(),
		"authority": AUTHORITY,
	}


func register_vendor(vendor: AndromedaVendorTarget) -> Dictionary:
	if vendor == null or not is_instance_valid(vendor):
		return _rejected("VENDOR_INSTANCE_REQUIRED")
	if vendor.vendor_ref.is_empty() or vendor.target_ref.is_empty():
		return _rejected("VENDOR_IDENTITY_REQUIRED")
	if _registered_vendors.has(vendor.vendor_ref):
		var existing: Variant = _registered_vendors[vendor.vendor_ref]
		if is_instance_valid(existing) and existing != vendor:
			return _rejected("DUPLICATE_ACTIVE_VENDOR_REF")
		return {"status": "PASS", "idempotent": true, "vendor_ref": vendor.vendor_ref, "authority": AUTHORITY}
	_registered_vendors[vendor.vendor_ref] = vendor
	return {"status": "PASS", "idempotent": false, "vendor_ref": vendor.vendor_ref, "authority": AUTHORITY}


func vendor_for_ref(vendor_ref_value: String) -> AndromedaVendorTarget:
	var normalized: String = vendor_ref_value.strip_edges()
	var value: Variant = _registered_vendors.get(normalized)
	if not is_instance_valid(value):
		_registered_vendors.erase(normalized)
		return null
	return value as AndromedaVendorTarget


func handle_manual_vendor_intent(resolved: Dictionary, target: AndromedaInteractionTarget) -> Dictionary:
	if resolved.get("status") != "PASS" or str(resolved.get("intent", "")) != "APPROACH_INTERACT":
		return _rejected("VENDOR_CONTEXT_POINTER_INTENT_REQUIRED")
	if not target is AndromedaVendorTarget:
		return _rejected("SPECIALIZED_VENDOR_TARGET_REQUIRED")
	var vendor := target as AndromedaVendorTarget
	if str(resolved.get("target_ref", "")) != vendor.target_ref:
		return _rejected("VENDOR_TARGET_REF_MISMATCH")
	return begin_vendor_interaction(vendor, "RIGHT_CLICK")


func handle_selected_interaction(target: AndromedaInteractionTarget) -> Dictionary:
	if not target is AndromedaVendorTarget:
		return _rejected("SELECTED_TARGET_NOT_VENDOR")
	return begin_vendor_interaction(target as AndromedaVendorTarget, "CONTEXT_KEY_E")


func begin_vendor_interaction(vendor: AndromedaVendorTarget, request_source: String) -> Dictionary:
	var registration: Dictionary = register_vendor(vendor)
	if registration.get("status") != "PASS":
		return registration
	if not vendor.is_inside_tree():
		return _rejected("STALE_OR_REMOVED_VENDOR_TARGET")
	var distance_m: float = _physical_distance(vendor)
	if distance_m <= vendor.interaction_range_m:
		var guard: Dictionary = _evaluate_vendor_access(vendor)
		if guard.get("status") != "PASS":
			return guard
		return _open_vendor(vendor, request_source)
	var destination: Vector3 = approach_destination_for(vendor)
	var path_result: Dictionary = _player.validate_destination(destination)
	if path_result.get("status") != "PASS":
		return _rejected("VENDOR_PATH_INVALID", {"path_result": path_result})
	var movement: Dictionary = _player.request_move(destination)
	if movement.get("status") != "PASS":
		return _rejected("VENDOR_APPROACH_REJECTED", {"movement_result": movement})
	_pending_approach = {
		"vendor_ref": vendor.vendor_ref,
		"target_ref": vendor.target_ref,
		"instance_id": vendor.get_instance_id(),
		"request_source": request_source,
	}
	return {
		"status": "PASS",
		"intent": "APPROACH_VENDOR_PENDING",
		"vendor_ref": vendor.vendor_ref,
		"target_ref": vendor.target_ref,
		"physical_distance_m": distance_m,
		"interaction_range_m": vendor.interaction_range_m,
		"movement_result": movement,
		"vendor_ui_opened": false,
		"trade_executed": false,
		"authority": AUTHORITY,
	}


func process_pending_approach_once() -> Dictionary:
	if _pending_approach.is_empty():
		return {"status": "PASS", "pending": false, "authority": AUTHORITY}
	var vendor_ref_value: String = str(_pending_approach.get("vendor_ref", ""))
	var vendor: AndromedaVendorTarget = vendor_for_ref(vendor_ref_value)
	if vendor == null or not vendor.is_inside_tree() or vendor.get_instance_id() != int(_pending_approach.get("instance_id", -1)):
		_pending_approach.clear()
		return _rejected("STALE_OR_REMOVED_VENDOR_TARGET")
	var distance_m: float = _physical_distance(vendor)
	if distance_m > vendor.interaction_range_m:
		return {"status": "PASS", "pending": true, "physical_distance_m": distance_m, "authority": AUTHORITY}
	var guard: Dictionary = _evaluate_vendor_access(vendor)
	if guard.get("status") != "PASS":
		_pending_approach.clear()
		return guard
	var source: String = str(_pending_approach.get("request_source", "APPROACH"))
	_pending_approach.clear()
	return _open_vendor(vendor, "%s_AFTER_APPROACH" % source)


func approach_destination_for(vendor: AndromedaVendorTarget) -> Vector3:
	if _player == null or vendor == null:
		return Vector3.ZERO
	var target_position: Vector3 = vendor.interaction_anchor_world_position()
	var away := Vector2(_player.global_position.x - target_position.x, _player.global_position.z - target_position.z)
	if away.length_squared() <= 0.000001:
		away = Vector2.RIGHT
	away = away.normalized()
	var stand_off: float = maxf(0.2, vendor.interaction_range_m * 0.72)
	return Vector3(target_position.x + away.x * stand_off, target_position.y, target_position.z + away.y * stand_off)


func request_quote(
	vendor_ref_value: String,
	item_ref: String,
	operation_value: String,
	quantity: int,
	instance_ref: String = ""
) -> Dictionary:
	if _needs_resync:
		return _rejected("VENDOR_RESYNC_REQUIRED")
	var vendor_ref_normalized: String = vendor_ref_value.strip_edges()
	var operation: String = operation_value.strip_edges().to_upper()
	if vendor_ref_normalized != _open_vendor_ref or not _hud.is_vendor_open():
		return _rejected("VENDOR_UI_NOT_OPEN_FOR_REF")
	if operation not in OPERATIONS:
		return _rejected("INVALID_TRADE_OPERATION")
	if item_ref.strip_edges().is_empty():
		return _rejected("EMPTY_TRADE_ITEM_REF")
	if quantity <= 0:
		return _rejected("INVALID_TRADE_QUANTITY")
	if operation == "BUY" and not _stock_contains(vendor_ref_normalized, item_ref):
		return _rejected("ITEM_NOT_IN_PROJECTED_VENDOR_STOCK")
	var bridge: AndromedaRuntimeBridge = _bridge()
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	_quote_request_serial += 1
	var request_ref: String = "B09-QUOTE-REQUEST-%06d" % _quote_request_serial
	var params := {
		"request_ref": request_ref,
		"vendor_ref": vendor_ref_normalized,
		"item_ref": item_ref.strip_edges(),
		"direction": operation,
		"quantity": quantity,
		"client_presentation_only": true,
	}
	if not instance_ref.strip_edges().is_empty():
		params["instance_ref"] = instance_ref.strip_edges()
	var built: Dictionary = bridge.build_command_envelope("REQUEST_TRADE_QUOTE", params)
	if built.get("status") != "PASS":
		return built
	var transport_result: Dictionary = {
		"status": "NOT_AVAILABLE",
		"reason": "BRIDGE_NOT_READY_NO_LIVE_BACKEND",
	}
	var submitted: bool = false
	if bridge.connection_state().get("authority_session_bound") == true:
		var envelope: Dictionary = built.get("envelope", {}) as Dictionary
		transport_result = bridge.submit_command(
			"REQUEST_TRADE_QUOTE", params, str(envelope.get("command_ref", ""))
		)
		submitted = transport_result.get("status") == "PASS"
	_last_quote_request = {
		"status": "PASS",
		"intent": "REQUEST_QUOTE",
		"request_ref": request_ref,
		"vendor_ref": vendor_ref_normalized,
		"item_ref": item_ref.strip_edges(),
		"operation": operation,
		"quantity": quantity,
		"intent_envelope": built,
		"transport_result": transport_result,
		"transport_submitted": submitted,
		"price_calculated_locally": false,
		"wallet_mutated_locally": false,
		"inventory_mutated_locally": false,
		"authority": AUTHORITY,
	}
	_current_quote.clear()
	quote_request_prepared.emit(_last_quote_request.duplicate(true))
	return _last_quote_request.duplicate(true)


func project_stock_snapshot(snapshot: Dictionary) -> Dictionary:
	var external: Dictionary = _validate_external(snapshot, "VENDOR_STOCK_SNAPSHOT")
	if external.get("status") != "PASS":
		return external
	var sequence: int = _required_nonnegative_int(snapshot.get("snapshot_sequence"), "INVALID_VENDOR_STOCK_SEQUENCE")
	if sequence < 0:
		return _rejected("INVALID_VENDOR_STOCK_SEQUENCE")
	if sequence <= _last_stock_sequence:
		return _rejected("STALE_OR_DUPLICATE_VENDOR_STOCK_SNAPSHOT")
	var vendor_ref_value: String = str(snapshot.get("vendor_ref", "")).strip_edges()
	if vendor_for_ref(vendor_ref_value) == null:
		return _rejected("VENDOR_STOCK_TARGET_NOT_FOUND")
	var items_value: Variant = snapshot.get("items", [])
	if not items_value is Array:
		return _rejected("INVALID_VENDOR_STOCK_ITEMS")
	var items: Array[Dictionary] = []
	var refs: Dictionary = {}
	for item_value: Variant in items_value:
		if not item_value is Dictionary:
			return _rejected("INVALID_VENDOR_STOCK_ENTRY")
		var item: Dictionary = item_value
		var item_ref: String = str(item.get("item_ref", "")).strip_edges()
		if item_ref.is_empty() or refs.has(item_ref):
			return _rejected("INVALID_OR_DUPLICATE_VENDOR_STOCK_ITEM_REF")
		refs[item_ref] = true
		items.append(item.duplicate(true))
	_projection_session_ref = str(snapshot.get("session_ref", ""))
	_last_stock_sequence = sequence
	_stock_by_vendor[vendor_ref_value] = items.duplicate(true)
	_needs_resync = false
	var ui_result: Dictionary = _hud.project_vendor_stock(vendor_ref_value, items)
	return {
		"status": "PASS",
		"vendor_ref": vendor_ref_value,
		"snapshot_sequence": sequence,
		"item_count": items.size(),
		"ui_projection": ui_result,
		"price_calculated_locally": false,
		"authority": AUTHORITY,
	}


func project_quote(quote: Dictionary) -> Dictionary:
	var external: Dictionary = _validate_external(quote, "VENDOR_QUOTE")
	if external.get("status") != "PASS":
		return external
	var sequence: int = _required_nonnegative_int(quote.get("quote_sequence"), "INVALID_QUOTE_SEQUENCE")
	if sequence < 0:
		return _rejected("INVALID_QUOTE_SEQUENCE")
	if sequence <= _last_quote_sequence:
		return _rejected("STALE_OR_DUPLICATE_QUOTE_SEQUENCE")
	var quote_ref: String = str(quote.get("quote_ref", "")).strip_edges()
	if quote_ref.is_empty() or _processed_quote_refs.has(quote_ref):
		return _rejected("EMPTY_OR_DUPLICATE_QUOTE_REF")
	var identity: Dictionary = _validate_quote_identity(quote, _last_quote_request)
	if identity.get("status") != "PASS":
		return identity
	if not _valid_external_price(quote.get("unit_price")) or not _valid_external_price(quote.get("total_price")):
		return _rejected("INVALID_EXTERNAL_QUOTE_PRICE")
	_last_quote_sequence = sequence
	_processed_quote_refs[quote_ref] = true
	_current_quote = quote.duplicate(true)
	_current_quote["operation"] = str(quote.get("operation", quote.get("direction", ""))).to_upper()
	_current_quote["active"] = bool(quote.get("active", true))
	_current_quote["total_price_display"] = str(quote.get("total_price"))
	var ui_result: Dictionary = _hud.project_vendor_quote(_current_quote)
	var projected := {
		"status": "PASS",
		"quote_ref": quote_ref,
		"quote_sequence": sequence,
		"ui_projection": ui_result,
		"price_recalculated_locally": false,
		"trade_executed": false,
		"authority": AUTHORITY,
	}
	quote_projected.emit(projected.duplicate(true))
	return projected


func execute_trade(
	quote_ref: String,
	vendor_ref_value: String,
	item_ref: String,
	operation_value: String,
	quantity: int,
	confirmation_ref: String,
	user_confirmed: bool = true
) -> Dictionary:
	if _needs_resync:
		return _rejected("VENDOR_RESYNC_REQUIRED")
	if not user_confirmed:
		return _rejected("EXPLICIT_USER_CONFIRMATION_REQUIRED")
	var confirmation: String = confirmation_ref.strip_edges()
	if confirmation.is_empty():
		return _rejected("EXPLICIT_CONFIRMATION_REF_REQUIRED")
	if _execute_by_confirmation.has(confirmation):
		var existing: Dictionary = _execute_by_confirmation[confirmation]
		var retry := existing.duplicate(true)
		retry["idempotent_retry"] = true
		return retry
	if _current_quote.is_empty():
		return _rejected("EXECUTE_REQUIRES_PROJECTED_QUOTE")
	var supplied := {
		"quote_ref": quote_ref.strip_edges(),
		"vendor_ref": vendor_ref_value.strip_edges(),
		"item_ref": item_ref.strip_edges(),
		"operation": operation_value.strip_edges().to_upper(),
		"quantity": quantity,
	}
	var identity: Dictionary = _validate_quote_identity(supplied, _current_quote)
	if identity.get("status") != "PASS":
		return identity
	if not bool(_current_quote.get("active", true)):
		return _rejected("QUOTE_EXTERNALLY_INACTIVE_OR_EXPIRED")
	var bridge: AndromedaRuntimeBridge = _bridge()
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	_execute_serial += 1
	var event_ref: String = "B09-TRADE-EXECUTE-%06d" % _execute_serial
	var params := {
		"quote_ref": quote_ref.strip_edges(),
		"event_ref": event_ref,
		"confirmation_ref": confirmation,
		"vendor_ref": vendor_ref_value.strip_edges(),
		"item_ref": item_ref.strip_edges(),
		"direction": operation_value.strip_edges().to_upper(),
		"quantity": quantity,
		"explicit_user_confirmation": true,
		"client_presentation_only": true,
	}
	var built: Dictionary = bridge.build_command_envelope("EXECUTE_TRADE", params)
	if built.get("status") != "PASS":
		return built
	var transport_result: Dictionary = {
		"status": "NOT_AVAILABLE",
		"reason": "BRIDGE_NOT_READY_NO_LIVE_BACKEND",
	}
	var submitted: bool = false
	if bridge.connection_state().get("authority_session_bound") == true:
		var envelope: Dictionary = built.get("envelope", {}) as Dictionary
		transport_result = bridge.submit_command(
			"EXECUTE_TRADE", params, str(envelope.get("command_ref", ""))
		)
		submitted = transport_result.get("status") == "PASS"
	_last_execute_request = {
		"status": "PASS",
		"intent": "EXECUTE_TRADE",
		"event_ref": event_ref,
		"confirmation_ref": confirmation,
		"quote_ref": quote_ref.strip_edges(),
		"vendor_ref": vendor_ref_value.strip_edges(),
		"item_ref": item_ref.strip_edges(),
		"operation": operation_value.strip_edges().to_upper(),
		"quantity": quantity,
		"intent_envelope": built,
		"transport_result": transport_result,
		"transport_submitted": submitted,
		"wallet_mutated_locally": false,
		"inventory_mutated_locally": false,
		"ownership_mutated_locally": false,
		"authority": AUTHORITY,
	}
	_execute_by_confirmation[confirmation] = _last_execute_request.duplicate(true)
	trade_request_prepared.emit(_last_execute_request.duplicate(true))
	return _last_execute_request.duplicate(true)


func project_trade_result(result: Dictionary) -> Dictionary:
	var external: Dictionary = _validate_external(result, "TRADE_RESULT")
	if external.get("status") != "PASS":
		return external
	var sequence: int = _required_nonnegative_int(result.get("result_sequence"), "INVALID_TRADE_RESULT_SEQUENCE")
	if sequence < 0:
		return _rejected("INVALID_TRADE_RESULT_SEQUENCE")
	if sequence <= _last_trade_result_sequence:
		return _rejected("STALE_OR_DUPLICATE_TRADE_RESULT")
	var event_ref: String = str(result.get("event_ref", "")).strip_edges()
	if event_ref.is_empty() or _processed_trade_events.has(event_ref):
		return _rejected("EMPTY_OR_DUPLICATE_TRADE_EVENT_REF")
	if event_ref != str(_last_execute_request.get("event_ref", "")):
		return _rejected("TRADE_RESULT_EVENT_REF_MISMATCH")
	if str(result.get("quote_ref", "")) != str(_last_execute_request.get("quote_ref", "")):
		return _rejected("TRADE_RESULT_QUOTE_REF_MISMATCH")
	var external_result: String = str(result.get("result", "")).strip_edges().to_upper()
	if external_result not in ["ACCEPTED", "REJECTED"]:
		return _rejected("INVALID_EXTERNAL_TRADE_RESULT")
	_last_trade_result_sequence = sequence
	_processed_trade_events[event_ref] = true
	_wallet_projection_revision = int(result.get("wallet_revision", _wallet_projection_revision))
	_inventory_projection_revision = int(result.get("inventory_revision", _inventory_projection_revision))
	var ui_result: Dictionary = _hud.project_vendor_trade_result(result)
	var projected := {
		"status": "PASS",
		"event_ref": event_ref,
		"external_result": external_result,
		"reason": str(result.get("reason", "")),
		"ui_projection": ui_result,
		"wallet_mutated_locally": false,
		"inventory_mutated_locally": false,
		"ownership_mutated_locally": false,
		"authority": AUTHORITY,
	}
	trade_result_projected.emit(projected.duplicate(true))
	return projected


func invalidate_current_quote_externally(quote_ref: String, externally_confirmed: bool) -> Dictionary:
	if not externally_confirmed:
		return _rejected("EXTERNAL_QUOTE_INVALIDATION_REQUIRED")
	if str(_current_quote.get("quote_ref", "")) != quote_ref.strip_edges():
		return _rejected("QUOTE_REF_NOT_CURRENT")
	_current_quote["active"] = false
	return {"status": "PASS", "quote_ref": quote_ref, "authority": AUTHORITY}


func current_quote() -> Dictionary:
	return _current_quote.duplicate(true)


func last_quote_request() -> Dictionary:
	return _last_quote_request.duplicate(true)


func last_execute_request() -> Dictionary:
	return _last_execute_request.duplicate(true)


func pending_vendor_ref() -> String:
	return str(_pending_approach.get("vendor_ref", ""))


func needs_resync() -> bool:
	return _needs_resync


func clear_client_tracking() -> void:
	_pending_approach.clear()
	_last_quote_request.clear()
	_last_execute_request.clear()
	_current_quote.clear()
	_execute_by_confirmation.clear()


func contract_snapshot() -> Dictionary:
	return {
		"flow": ["SELECT", "PHYSICAL_APPROACH", "OPEN_UI", "REQUEST_QUOTE", "PROJECT_QUOTE", "EXPLICIT_CONFIRM", "EXECUTE_TRADE", "PROJECT_RESULT"],
		"operations": OPERATIONS.duplicate(),
		"click_auto_purchase": false,
		"approach_auto_purchase": false,
		"open_auto_purchase": false,
		"selection_auto_purchase": false,
		"quote_auto_execute": false,
		"explicit_confirmation_required": true,
		"owner_ref_supplied_by_client": false,
		"player_ref_supplied_by_client": false,
		"price_authority": false,
		"wallet_authority": false,
		"inventory_authority": false,
		"ownership_authority": false,
		"quote_expiry_authority": false,
		"backend_substitute": false,
		"invented_endpoint": false,
		"authority": AUTHORITY,
	}


func _open_vendor(vendor: AndromedaVendorTarget, request_source: String) -> Dictionary:
	_open_vendor_ref = vendor.vendor_ref
	_open_target_ref = vendor.target_ref
	var ui_result: Dictionary = _hud.open_vendor(vendor.target_ref, vendor.vendor_ref)
	var stock_value: Variant = _stock_by_vendor.get(vendor.vendor_ref, [])
	if ui_result.get("status") == "PASS" and stock_value is Array:
		var typed_stock: Array[Dictionary] = []
		for item_value: Variant in stock_value:
			if item_value is Dictionary:
				typed_stock.append((item_value as Dictionary).duplicate(true))
		ui_result["stock_projection"] = _hud.project_vendor_stock(
			vendor.vendor_ref,
			typed_stock
		)
	var result := {
		"status": "PASS",
		"intent": "OPEN_VENDOR_UI",
		"request_source": request_source,
		"vendor_ref": vendor.vendor_ref,
		"target_ref": vendor.target_ref,
		"ui_projection": ui_result,
		"auto_purchase": false,
		"quote_requested": false,
		"trade_executed": false,
		"wallet_mutated_locally": false,
		"inventory_mutated_locally": false,
		"authority": AUTHORITY,
	}
	vendor_opened.emit(result.duplicate(true))
	return result


func _evaluate_vendor_access(vendor: AndromedaVendorTarget) -> Dictionary:
	if vendor == null or not is_instance_valid(vendor) or not vendor.is_inside_tree():
		return _rejected("STALE_OR_REMOVED_VENDOR_TARGET")
	if vendor_for_ref(vendor.vendor_ref) != vendor:
		return _rejected("WRONG_OR_UNREGISTERED_VENDOR_TARGET")
	if _physical_distance(vendor) > vendor.interaction_range_m:
		return _rejected("VENDOR_DISTANCE_EXCEEDED")
	var blocker: Dictionary = blocker_probe(vendor)
	if blocker.get("blocked") == true:
		return _rejected("VENDOR_BLOCKED_BY_COLLISION", {"blocker_result": blocker})
	var path_result: Dictionary = _player.validate_destination(approach_destination_for(vendor))
	if path_result.get("status") != "PASS":
		return _rejected("VENDOR_PATH_INVALID", {"path_result": path_result})
	return {"status": "PASS", "authority": AUTHORITY}


func blocker_probe(vendor: AndromedaVendorTarget) -> Dictionary:
	if _player == null or vendor == null:
		return _rejected("PLAYER_AND_VENDOR_REQUIRED")
	var world: World3D = _player.get_world_3d()
	if world == null:
		return _rejected("WORLD_3D_REQUIRED")
	var start: Vector3 = _player.global_position + Vector3(0.0, 0.55, 0.0)
	var finish: Vector3 = vendor.interaction_anchor_world_position() + Vector3(0.0, 0.55, 0.0)
	var excluded: Array[RID] = [_player.get_rid()]
	if vendor.has_method("get_rid"):
		var vendor_rid: RID = vendor.call("get_rid")
		if vendor_rid.is_valid():
			excluded.append(vendor_rid)
	var query := PhysicsRayQueryParameters3D.create(start, finish, BLOCKER_MASK, excluded)
	query.collide_with_areas = false
	query.collide_with_bodies = true
	var hit: Dictionary = world.direct_space_state.intersect_ray(query)
	return {
		"status": "PASS",
		"blocked": not hit.is_empty(),
		"authority": AUTHORITY,
	}


func _physical_distance(vendor: AndromedaVendorTarget) -> float:
	return _player.global_position.distance_to(vendor.interaction_anchor_world_position())


func _stock_contains(vendor_ref_value: String, item_ref_value: String) -> bool:
	var value: Variant = _stock_by_vendor.get(vendor_ref_value, [])
	if not value is Array:
		return false
	for item_value: Variant in value:
		if item_value is Dictionary and str(item_value.get("item_ref", "")) == item_ref_value.strip_edges():
			return true
	return false


func _validate_quote_identity(candidate: Dictionary, expected: Dictionary) -> Dictionary:
	if expected.is_empty():
		return _rejected("QUOTE_REQUEST_OR_CURRENT_QUOTE_REQUIRED")
	var candidate_operation: String = str(candidate.get("operation", candidate.get("direction", ""))).to_upper()
	var expected_operation: String = str(expected.get("operation", expected.get("direction", ""))).to_upper()
	for key: String in ["vendor_ref", "item_ref"]:
		if str(candidate.get(key, "")) != str(expected.get(key, "")):
			return _rejected("QUOTE_%s_MISMATCH" % key.to_upper())
	if candidate_operation != expected_operation:
		return _rejected("QUOTE_OPERATION_MISMATCH")
	if int(candidate.get("quantity", 0)) != int(expected.get("quantity", 0)):
		return _rejected("QUOTE_QUANTITY_MISMATCH")
	if expected.has("quote_ref") and str(candidate.get("quote_ref", "")) != str(expected.get("quote_ref", "")):
		return _rejected("QUOTE_REF_MISMATCH")
	return {"status": "PASS", "authority": AUTHORITY}


func _validate_external(payload: Dictionary, label: String) -> Dictionary:
	if payload.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_%s" % label)
	var session: AndromedaClientSession = _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	var session_ref_value: String = str(payload.get("session_ref", "")).strip_edges()
	if session_ref_value != session.session_ref():
		return _rejected("SESSION_MISMATCH")
	if not _projection_session_ref.is_empty() and session_ref_value != _projection_session_ref:
		return _rejected("PROJECTION_SESSION_MISMATCH")
	return {"status": "PASS", "authority": AUTHORITY}


func _required_nonnegative_int(value: Variant, _reason: String) -> int:
	if typeof(value) != TYPE_INT or typeof(value) == TYPE_BOOL or int(value) < 0:
		return -1
	return int(value)


func _valid_external_price(value: Variant) -> bool:
	return typeof(value) in [TYPE_INT, TYPE_FLOAT] and typeof(value) != TYPE_BOOL and is_finite(float(value)) and float(value) >= 0.0


func _on_ui_quote_requested(vendor_ref_value: String, item_ref: String, operation: String, quantity: int) -> void:
	request_quote(vendor_ref_value, item_ref, operation, quantity)


func _on_ui_execute_requested(
	quote_ref: String,
	vendor_ref_value: String,
	item_ref: String,
	operation: String,
	quantity: int,
	confirmation_ref: String
) -> void:
	execute_trade(quote_ref, vendor_ref_value, item_ref, operation, quantity, confirmation_ref, true)


func _on_ui_close_requested() -> void:
	_hud.close_active_modal()


func _on_bridge_snapshot_applied(snapshot: Dictionary) -> void:
	var stocks_value: Variant = snapshot.get("vendor_stock", [])
	if not stocks_value is Array:
		return
	for stock_value: Variant in stocks_value:
		if not stock_value is Dictionary:
			continue
		var stock: Dictionary = (stock_value as Dictionary).duplicate(true)
		if vendor_for_ref(str(stock.get("vendor_ref", ""))) == null:
			continue
		stock["server_authoritative"] = snapshot.get("server_authoritative")
		stock["session_ref"] = snapshot.get("session_ref")
		stock["snapshot_sequence"] = snapshot.get("snapshot_sequence")
		project_stock_snapshot(stock)


func _on_bridge_command_result_received(result: Dictionary) -> void:
	match str(result.get("command", "")).to_upper():
		"REQUEST_TRADE_QUOTE":
			project_quote(result)
		"EXECUTE_TRADE":
			project_trade_result(result)


func _on_session_bound(session_ref_value: String, _session_epoch: int) -> void:
	if not _projection_session_ref.is_empty() and _projection_session_ref != session_ref_value:
		_reset_projection_caches()
	_needs_resync = true


func _on_session_revoked(_previous_session_ref: String, _session_epoch: int) -> void:
	_pending_approach.clear()
	_open_vendor_ref = ""
	_open_target_ref = ""
	_needs_resync = true


func _reset_projection_caches() -> void:
	_projection_session_ref = ""
	_last_stock_sequence = -1
	_last_quote_sequence = -1
	_last_trade_result_sequence = -1
	_stock_by_vendor.clear()
	_current_quote.clear()
	_processed_quote_refs.clear()
	_processed_trade_events.clear()
	_execute_by_confirmation.clear()
	_last_quote_request.clear()
	_last_execute_request.clear()


func _bridge() -> AndromedaRuntimeBridge:
	return get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge


func _session() -> AndromedaClientSession:
	return get_node_or_null("/root/ClientSession") as AndromedaClientSession


func _rejected(reason: String, detail: Dictionary = {}) -> Dictionary:
	var result := {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
	result.merge(detail, true)
	return result
