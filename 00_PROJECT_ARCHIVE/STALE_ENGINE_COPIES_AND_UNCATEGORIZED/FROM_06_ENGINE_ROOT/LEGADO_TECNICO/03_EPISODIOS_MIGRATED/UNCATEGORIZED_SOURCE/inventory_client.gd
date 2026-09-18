extends Node
class_name AndromedaInventoryClient

## B09 inventory/Bag/equipment projection boundary. It validates external state and
## emits contracted intents, but never computes capacity, routing, ownership or transfer.

signal inventory_projected(result: Dictionary)
signal inventory_intent_prepared(result: Dictionary)

const AUTHORITY := "GODOT_INVENTORY_CLIENT_PROJECTION_ONLY"
const BAG_NO_BAG := "NO_BAG"
const BAG_EQUIPPED := "BAG_EQUIPPED"
const BASE_REDUCED_SLOT_CANDIDATE := 8

var _hud: AndromedaHUDController
var _projection: Dictionary = {}
var _projection_session_ref: String = ""
var _last_snapshot_sequence: int = -1
var _needs_resync: bool = true
var _request_serial: int = 0
var _last_intent: Dictionary = {}
var _bound: bool = false


func bind_runtime(hud_value: AndromedaHUDController) -> Dictionary:
	if hud_value == null:
		return _rejected("HUD_REQUIRED")
	_hud = hud_value
	if not _bound:
		var bridge: AndromedaRuntimeBridge = _bridge()
		if bridge != null and not bridge.snapshot_applied.is_connected(_on_bridge_snapshot_applied):
			bridge.snapshot_applied.connect(_on_bridge_snapshot_applied)
		var session: AndromedaClientSession = _session()
		if session != null:
			if not session.session_bound.is_connected(_on_session_bound):
				session.session_bound.connect(_on_session_bound)
			if not session.session_revoked.is_connected(_on_session_revoked):
				session.session_revoked.connect(_on_session_revoked)
		_bound = true
	return {"status": "PASS", "authority": AUTHORITY}


func project_inventory_snapshot(snapshot: Dictionary) -> Dictionary:
	var external: Dictionary = _validate_external(snapshot)
	if external.get("status") != "PASS":
		return external
	var sequence_value: Variant = snapshot.get("snapshot_sequence")
	if typeof(sequence_value) != TYPE_INT or typeof(sequence_value) == TYPE_BOOL or int(sequence_value) < 0:
		return _rejected("INVALID_INVENTORY_SNAPSHOT_SEQUENCE")
	var sequence: int = int(sequence_value)
	if sequence <= _last_snapshot_sequence:
		return _rejected("STALE_OR_DUPLICATE_INVENTORY_SNAPSHOT")
	var shape: Dictionary = _validate_snapshot_shape(snapshot)
	if shape.get("status") != "PASS":
		return shape
	_projection_session_ref = str(snapshot.get("session_ref", ""))
	_last_snapshot_sequence = sequence
	_projection = {
		"snapshot_sequence": sequence,
		"base_inventory": (snapshot.get("base_inventory") as Dictionary).duplicate(true),
		"bag": (snapshot.get("bag") as Dictionary).duplicate(true),
		"equipment": (snapshot.get("equipment") as Dictionary).duplicate(true),
		"weapon_loadout": (snapshot.get("weapon_loadout") as Dictionary).duplicate(true),
		"carry": (snapshot.get("carry") as Dictionary).duplicate(true),
		"routing": (snapshot.get("routing") as Dictionary).duplicate(true),
	}
	_needs_resync = false
	var ui_result: Dictionary = _hud.project_inventory_state(_projection)
	var result := {
		"status": "PASS",
		"snapshot_sequence": sequence,
		"bag_state": str((_projection["bag"] as Dictionary).get("state", "")),
		"ui_projection": ui_result,
		"capacity_calculated_locally": false,
		"load_calculated_locally": false,
		"effective_owner_selected_locally": false,
		"contents_mutated_locally": false,
		"authority": AUTHORITY,
	}
	inventory_projected.emit(result.duplicate(true))
	return result


func request_equipment_intent(item_ref: String, slot_ref: String, equip: bool) -> Dictionary:
	if _needs_resync:
		return _rejected("INVENTORY_RESYNC_REQUIRED")
	if item_ref.strip_edges().is_empty() or slot_ref.strip_edges().is_empty():
		return _rejected("ITEM_AND_EQUIPMENT_SLOT_REQUIRED")
	var command: String = "REQUEST_EQUIP_ITEM" if equip else "REQUEST_UNEQUIP_ITEM"
	return _prepare_intent(command, {
		"item_ref": item_ref.strip_edges(),
		"equipment_slot": slot_ref.strip_edges(),
		"client_presentation_only": true,
	})


func request_bag_equip(bag_instance_ref: String) -> Dictionary:
	if _needs_resync:
		return _rejected("INVENTORY_RESYNC_REQUIRED")
	if bag_instance_ref.strip_edges().is_empty():
		return _rejected("BAG_INSTANCE_REF_REQUIRED")
	var bag: Dictionary = _projection.get("bag", {})
	if str(bag.get("state", "")) != BAG_NO_BAG:
		return _rejected("BAG_ALREADY_EQUIPPED_IN_EXTERNAL_PROJECTION")
	return _prepare_intent("REQUEST_EQUIP_BAG", {
		"bag_instance_ref": bag_instance_ref.strip_edges(),
		"client_presentation_only": true,
	})


func request_bag_unequip(_bag_instance_ref: String) -> Dictionary:
	return _rejected("BAG_UNEQUIP_NOT_CONTRACTED_IN_STAGE16A_B09")


func projected_state() -> Dictionary:
	return _projection.duplicate(true)


func bag_state() -> String:
	var bag: Dictionary = _projection.get("bag", {})
	return str(bag.get("state", ""))


func last_intent() -> Dictionary:
	return _last_intent.duplicate(true)


func needs_resync() -> bool:
	return _needs_resync


func contract_snapshot() -> Dictionary:
	return {
		"states": [BAG_NO_BAG, BAG_EQUIPPED],
		"base_reduced_slot_candidate": BASE_REDUCED_SLOT_CANDIDATE,
		"bag_is_real_container": true,
		"effective_carry_includes": ["BASE_INVENTORY", "EQUIPPED_BAG"],
		"quick_slot_count": 2,
		"simultaneously_active_weapons": 1,
		"owner_routing_source": "EXTERNAL_STAGE16A_PROJECTION",
		"capacity_authority": false,
		"load_authority": false,
		"stack_authority": false,
		"ownership_authority": false,
		"equipment_authority": false,
		"inventory_transfer_authority": false,
		"bag_contents_authority": false,
		"death_drop_logic": false,
		"dropped_bag_logic": false,
		"bag_recovery_logic": false,
		"save_reload_logic": false,
		"backend_substitute": false,
		"authority": AUTHORITY,
	}


func _validate_snapshot_shape(snapshot: Dictionary) -> Dictionary:
	for key: String in ["base_inventory", "bag", "equipment", "weapon_loadout", "carry", "routing"]:
		if not snapshot.get(key) is Dictionary:
			return _rejected("INVALID_INVENTORY_SNAPSHOT_%s" % key.to_upper())
	var base: Dictionary = snapshot.get("base_inventory")
	if str(base.get("owner_ref", "")).strip_edges().is_empty():
		return _rejected("BASE_INVENTORY_OWNER_REF_REQUIRED")
	if not base.get("stacks", []) is Array:
		return _rejected("INVALID_BASE_INVENTORY_STACKS")
	if not _valid_nonnegative_number(base.get("slot_limit")) or not _valid_nonnegative_number(base.get("weight_limit")):
		return _rejected("INVALID_BASE_INVENTORY_CAPACITY")
	var bag: Dictionary = snapshot.get("bag")
	var bag_state_value: String = str(bag.get("state", "")).to_upper()
	if bag_state_value not in [BAG_NO_BAG, BAG_EQUIPPED]:
		return _rejected("INVALID_BAG_STATE")
	if not bag.get("contents", []) is Array:
		return _rejected("INVALID_BAG_CONTENTS_PROJECTION")
	if bag_state_value == BAG_EQUIPPED and str(bag.get("bag_ref", "")).strip_edges().is_empty():
		return _rejected("EQUIPPED_BAG_REF_REQUIRED")
	var equipment: Dictionary = snapshot.get("equipment")
	if not equipment.get("slots", {}) is Dictionary:
		return _rejected("INVALID_EQUIPMENT_SLOTS")
	var loadout: Dictionary = snapshot.get("weapon_loadout")
	var quick_slots_value: Variant = loadout.get("quick_slots", [])
	if not quick_slots_value is Array or (quick_slots_value as Array).size() != 2:
		return _rejected("EXACTLY_TWO_WEAPON_QUICK_SLOTS_REQUIRED")
	if int(loadout.get("active_slot", 0)) not in [1, 2]:
		return _rejected("ONE_ACTIVE_WEAPON_SLOT_REQUIRED")
	var carry: Dictionary = snapshot.get("carry")
	for field: String in ["current_weight", "max_weight", "used_slots", "max_slots"]:
		if not _valid_nonnegative_number(carry.get(field)):
			return _rejected("INVALID_EXTERNAL_CARRY_%s" % field.to_upper())
	var routing: Dictionary = snapshot.get("routing")
	if str(routing.get("effective_inventory_owner_ref", "")).strip_edges().is_empty():
		return _rejected("EFFECTIVE_INVENTORY_OWNER_PROJECTION_REQUIRED")
	if str(routing.get("source", "")).to_upper() not in ["BASE_INVENTORY", "EQUIPPED_BAG"]:
		return _rejected("INVALID_EFFECTIVE_CARRY_ROUTING_SOURCE")
	return {"status": "PASS", "authority": AUTHORITY}


func _prepare_intent(command: String, params: Dictionary) -> Dictionary:
	var bridge: AndromedaRuntimeBridge = _bridge()
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	_request_serial += 1
	var prepared_params: Dictionary = params.duplicate(true)
	prepared_params["request_ref"] = "B09-INVENTORY-REQUEST-%06d" % _request_serial
	var built: Dictionary = bridge.build_command_envelope(command, prepared_params)
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
			command, prepared_params, str(envelope.get("command_ref", ""))
		)
		submitted = transport_result.get("status") == "PASS"
	_last_intent = {
		"status": "PASS",
		"intent": command,
		"request_ref": prepared_params["request_ref"],
		"intent_envelope": built,
		"transport_result": transport_result,
		"transport_submitted": submitted,
		"inventory_mutated_locally": false,
		"ownership_mutated_locally": false,
		"equipment_authorized_locally": false,
		"authority": AUTHORITY,
	}
	inventory_intent_prepared.emit(_last_intent.duplicate(true))
	return _last_intent.duplicate(true)


func _validate_external(snapshot: Dictionary) -> Dictionary:
	if snapshot.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_INVENTORY_SNAPSHOT")
	var session: AndromedaClientSession = _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	var session_ref_value: String = str(snapshot.get("session_ref", "")).strip_edges()
	if session_ref_value != session.session_ref():
		return _rejected("SESSION_MISMATCH")
	if not _projection_session_ref.is_empty() and session_ref_value != _projection_session_ref:
		return _rejected("INVENTORY_PROJECTION_SESSION_MISMATCH")
	return {"status": "PASS", "authority": AUTHORITY}


func _valid_nonnegative_number(value: Variant) -> bool:
	return typeof(value) in [TYPE_INT, TYPE_FLOAT] and typeof(value) != TYPE_BOOL and is_finite(float(value)) and float(value) >= 0.0


func _on_bridge_snapshot_applied(snapshot: Dictionary) -> void:
	var projection_value: Variant = snapshot.get("inventory_projection")
	if not projection_value is Dictionary:
		return
	var projection: Dictionary = (projection_value as Dictionary).duplicate(true)
	projection["server_authoritative"] = snapshot.get("server_authoritative")
	projection["session_ref"] = snapshot.get("session_ref")
	projection["snapshot_sequence"] = snapshot.get(
		"presentation_sequence", snapshot.get("snapshot_sequence")
	)
	project_inventory_snapshot(projection)


func _on_session_bound(session_ref_value: String, _session_epoch: int) -> void:
	if not _projection_session_ref.is_empty() and _projection_session_ref != session_ref_value:
		_projection.clear()
		_projection_session_ref = ""
		_last_snapshot_sequence = -1
	_needs_resync = true


func _on_session_revoked(_previous_session_ref: String, _session_epoch: int) -> void:
	_needs_resync = true


func _bridge() -> AndromedaRuntimeBridge:
	return get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge


func _session() -> AndromedaClientSession:
	return get_node_or_null("/root/ClientSession") as AndromedaClientSession


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
