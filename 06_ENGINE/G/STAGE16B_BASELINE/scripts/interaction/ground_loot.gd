extends AndromedaInteractionTarget
class_name AndromedaGroundLoot

## B07 physical Ground Loot projection. Physics may settle locally, but item grants,
## inventory, ownership, authoritative quantity and water TTL remain upstream.

signal local_settling_changed(target_ref_value: String, locally_settled: bool)
signal authoritative_projection_applied(result: Dictionary)

const GROUND_LOOT_AUTHORITY := "GODOT_GROUND_LOOT_PHYSICS_PRESENTATION_ONLY"
const LAYER_GROUND_LOOT := 16
const WATER_EXPOSURE_CONTRACT_S := 900.0
const LOCAL_SETTLE_LINEAR_SPEED_MPS := 0.045
const LOCAL_SETTLE_ANGULAR_SPEED_RAD_S := 0.08
const LOCAL_SETTLE_STABLE_FRAMES := 10

const UNIVERSAL_SOURCE_KINDS: Array[String] = [
	"ENEMY",
	"TREE",
	"ROCK",
	"ORE",
	"FLORA",
	"AGRICULTURE",
	"HUNTING",
	"FISHING",
	"CONTAINER",
	"PHYSICAL_PRODUCTION",
	"PLAYER_DROP",
]

const ACTIVE_STATES: Array[String] = ["ACTIVE", "RECOVERABLE_IN_WATER"]
const TERMINAL_PRESENTATION_STATES: Array[String] = ["COLLECTED", "SUNK", "REMOVED"]

const ICON_CATEGORY_BY_ITEM_KIND := {
	"WEAPON": "ICON_WEAPON",
	"ARMOR": "ICON_ARMOR",
	"TOOL": "ICON_TOOL",
	"CONSUMABLE": "ICON_CONSUMABLE",
	"FOOD": "ICON_FOOD",
	"MATERIAL": "ICON_MATERIAL",
	"RESOURCE": "ICON_MATERIAL",
	"ORE": "ICON_MINERAL",
	"MINERAL": "ICON_MINERAL",
	"WOOD": "ICON_NATURAL_RESOURCE",
	"FLORA": "ICON_FLORA",
	"TECH_COMPONENT": "ICON_TECH_COMPONENT",
	"RUNE": "ICON_RUNE",
	"QUEST": "ICON_QUEST",
	"CURRENCY": "ICON_CURRENCY",
}

const CATEGORY_COLORS := {
	"ICON_WEAPON": Color("d9a15f"),
	"ICON_ARMOR": Color("d8d8d2"),
	"ICON_TOOL": Color("c7b18b"),
	"ICON_CONSUMABLE": Color("d7c36b"),
	"ICON_FOOD": Color("d6a87a"),
	"ICON_MATERIAL": Color("c8bd77"),
	"ICON_MINERAL": Color("aeb7c4"),
	"ICON_NATURAL_RESOURCE": Color("b7a06d"),
	"ICON_FLORA": Color("a8bd82"),
	"ICON_TECH_COMPONENT": Color("a9c2c7"),
	"ICON_RUNE": Color("c1a8ca"),
	"ICON_QUEST": Color("d9a15f"),
	"ICON_CURRENCY": Color("dcc866"),
	"ICON_GENERIC_ITEM_TYPE": Color("d2c86f"),
}

@export var source_ref: String = "SOURCE-B07-PLACEHOLDER"
@export_enum(
	"ENEMY",
	"TREE",
	"ROCK",
	"ORE",
	"FLORA",
	"AGRICULTURE",
	"HUNTING",
	"FISHING",
	"CONTAINER",
	"PHYSICAL_PRODUCTION",
	"PLAYER_DROP"
) var source_kind: String = "PLAYER_DROP"
@export var item_ref: String = "ITEM-B07-PLACEHOLDER"
@export var item_kind: String = "MATERIAL"
@export_range(1, 999999, 1) var projected_quantity: int = 1
@export var projected_reachable: bool = true

var _icon_category: String = "ICON_MATERIAL"
var _authoritative_state: String = "ACTIVE"
var _projection_session_ref: String = ""
var _last_projection_sequence: int = -1
var _last_lifecycle_sequence: int = -1
var _water_exposure_s: float = 0.0
var _locally_settled: bool = true
var _physical_settle_observed: bool = false
var _stable_physics_frames: int = 0
var _authoritative_projection_seen: bool = false
var _compatibility_source_alias_received: bool = false


func _ready() -> void:
	target_kind = AndromedaInputRouter.HIT_GROUND_LOOT
	source_kind = _normalize_source_kind(source_kind)
	item_kind = item_kind.strip_edges().to_upper()
	_icon_category = icon_category_for_item_kind(item_kind)
	_locally_settled = settled
	add_to_group("andromeda_ground_loot")
	super._ready()
	_apply_category_presentation()
	_apply_active_presentation()


func _physics_process(_delta: float) -> void:
	if not is_active_for_pickup():
		return
	if not bool(get("freeze")):
		_physical_settle_observed = true
		_set_local_settled(false)
		if (
			_physical_linear_velocity().length() <= LOCAL_SETTLE_LINEAR_SPEED_MPS
			and _physical_angular_velocity().length() <= LOCAL_SETTLE_ANGULAR_SPEED_RAD_S
		):
			_stable_physics_frames += 1
		else:
			_stable_physics_frames = 0
		if _stable_physics_frames >= LOCAL_SETTLE_STABLE_FRAMES:
			set("freeze", true)
			set("linear_velocity", Vector3.ZERO)
			set("angular_velocity", Vector3.ZERO)
			_on_local_physics_settled()
		return
	if _physical_settle_observed and not _locally_settled:
		_on_local_physics_settled()


func configure_spawn_identity(
	target_ref_value: String,
	source_ref_value: String,
	source_kind_value: String,
	item_ref_value: String,
	item_kind_value: String
) -> Dictionary:
	if is_inside_tree():
		return _rejected("SPAWN_IDENTITY_MUST_BE_CONFIGURED_BEFORE_TREE_ENTRY")
	var normalized_target_ref: String = target_ref_value.strip_edges()
	var normalized_source_kind: String = _normalize_source_kind(source_kind_value)
	if normalized_target_ref.is_empty():
		return _rejected("EMPTY_TARGET_REF")
	if normalized_source_kind not in UNIVERSAL_SOURCE_KINDS:
		return _rejected("UNSUPPORTED_PHYSICAL_DROP_SOURCE")
	target_ref = normalized_target_ref
	source_ref = source_ref_value.strip_edges()
	source_kind = normalized_source_kind
	item_ref = item_ref_value.strip_edges()
	item_kind = item_kind_value.strip_edges().to_upper()
	return {"status": "PASS", "target_ref": target_ref, "authority": GROUND_LOOT_AUTHORITY}


func begin_local_physical_settle() -> Dictionary:
	if not is_active_for_pickup():
		return _rejected("GROUND_LOOT_NOT_ACTIVE")
	if not is_class("RigidBody3D"):
		return _rejected("GROUND_LOOT_BODY_REQUIRED")
	_physical_settle_observed = true
	_stable_physics_frames = 0
	_set_local_settled(false)
	set("freeze", false)
	set("sleeping", false)
	set("gravity_scale", 1.0)
	var projected_settled: Variant = null
	if _authoritative_projection_seen:
		projected_settled = settled
	return {
		"status": "PASS",
		"locally_settled": false,
		"authoritative_settled": projected_settled,
		"authority": GROUND_LOOT_AUTHORITY,
	}


func settle_on_surface_local(surface_position: Vector3) -> Dictionary:
	if not is_active_for_pickup():
		return _rejected("GROUND_LOOT_NOT_ACTIVE")
	global_position = surface_position
	set("freeze", true)
	set("linear_velocity", Vector3.ZERO)
	set("angular_velocity", Vector3.ZERO)
	_physical_settle_observed = true
	_on_local_physics_settled()
	return {
		"status": "PASS",
		"locally_settled": _locally_settled,
		"pickup_settled": is_pickup_settled(),
		"authority": GROUND_LOOT_AUTHORITY,
	}


func apply_authoritative_projection(
	payload: Dictionary,
	session_ref_value: String,
	snapshot_sequence: int
) -> Dictionary:
	var validation: Dictionary = _validate_projection_identity(payload, session_ref_value, snapshot_sequence)
	if validation.get("status") != "PASS":
		return validation
	var next_source_kind: String = _normalize_source_kind(str(payload.get("source_kind", source_kind)))
	if next_source_kind not in UNIVERSAL_SOURCE_KINDS:
		return _rejected("UNSUPPORTED_PHYSICAL_DROP_SOURCE")
	var quantity_value: Variant = payload.get("quantity", projected_quantity)
	if not _valid_positive_integral_wire_number(quantity_value):
		return _rejected("INVALID_PROJECTED_QUANTITY")
	var next_item_kind: String = str(payload.get("item_kind", item_kind)).strip_edges().to_upper()
	if next_item_kind.is_empty():
		return _rejected("EMPTY_ITEM_KIND")
	var next_state: String = str(payload.get("state", _authoritative_state)).strip_edges().to_upper()
	if next_state not in ACTIVE_STATES and next_state not in TERMINAL_PRESENTATION_STATES:
		return _rejected("UNSUPPORTED_GROUND_LOOT_STATE")
	var exposure_value: Variant = payload.get("water_exposure_s", _water_exposure_s)
	if not _valid_nonnegative_number(exposure_value):
		return _rejected("INVALID_WATER_EXPOSURE")

	_projection_session_ref = session_ref_value.strip_edges()
	_last_projection_sequence = snapshot_sequence
	_authoritative_projection_seen = true
	source_ref = str(payload.get("source_ref", source_ref)).strip_edges()
	source_kind = next_source_kind
	item_ref = str(payload.get("item_ref", item_ref)).strip_edges()
	item_kind = next_item_kind
	projected_quantity = int(quantity_value)
	projected_reachable = bool(payload.get("reachable", projected_reachable))
	_water_exposure_s = float(exposure_value)
	_authoritative_state = next_state
	_icon_category = icon_category_for_item_kind(item_kind)
	var projected_settled: bool = bool(payload.get("settled", settled))
	set_settled(projected_settled)
	if projected_settled:
		_set_local_settled(true)
	_apply_category_presentation()
	_apply_active_presentation()
	var result := {
		"status": "PASS",
		"target_ref": target_ref,
		"state": _authoritative_state,
		"snapshot_sequence": _last_projection_sequence,
		"quantity": projected_quantity,
		"icon_category": _icon_category,
		"water_exposure_s": _water_exposure_s,
		"locally_sunk_by_timer": false,
		"inventory_mutated": false,
		"authority": GROUND_LOOT_AUTHORITY,
	}
	authoritative_projection_applied.emit(result.duplicate(true))
	return result


func apply_external_lifecycle_result(
	next_state_value: String,
	session_ref_value: String,
	result_sequence: int
) -> Dictionary:
	var normalized_session: String = session_ref_value.strip_edges()
	if normalized_session.is_empty() or normalized_session != _projection_session_ref:
		return _rejected("GROUND_LOOT_SESSION_MISMATCH")
	if result_sequence <= _last_lifecycle_sequence:
		return _rejected("STALE_OR_DUPLICATE_GROUND_LOOT_RESULT")
	var next_state: String = next_state_value.strip_edges().to_upper()
	if next_state not in ACTIVE_STATES and next_state not in TERMINAL_PRESENTATION_STATES:
		return _rejected("UNSUPPORTED_GROUND_LOOT_STATE")
	_last_lifecycle_sequence = result_sequence
	_authoritative_state = next_state
	_apply_active_presentation()
	return {
		"status": "PASS",
		"target_ref": target_ref,
		"state": _authoritative_state,
		"result_sequence": _last_lifecycle_sequence,
		"inventory_mutated": false,
		"authority": GROUND_LOOT_AUTHORITY,
	}


func set_hovered(value: bool) -> void:
	super.set_hovered(value)
	_apply_minimal_label_visibility()


func set_selected(value: bool) -> void:
	super.set_selected(value)
	_apply_minimal_label_visibility()


func is_active_for_pickup() -> bool:
	return _authoritative_state in ACTIVE_STATES


func is_pickup_settled() -> bool:
	if _authoritative_projection_seen:
		return settled and _locally_settled
	return settled and _locally_settled


func is_locally_settled() -> bool:
	return _locally_settled


func authoritative_state() -> String:
	return _authoritative_state


func water_exposure_s() -> float:
	return _water_exposure_s


func icon_category() -> String:
	return _icon_category


func projection_session_ref() -> String:
	return _projection_session_ref


func last_projection_sequence() -> int:
	return _last_projection_sequence


func physical_distance_to(actor: Node3D) -> float:
	if actor == null:
		return INF
	return actor.global_position.distance_to(global_position)


func icon_category_for_item_kind(item_kind_value: String) -> String:
	return str(ICON_CATEGORY_BY_ITEM_KIND.get(
		item_kind_value.strip_edges().to_upper(),
		"ICON_GENERIC_ITEM_TYPE"
	))


func universal_source_kinds() -> Array[String]:
	return UNIVERSAL_SOURCE_KINDS.duplicate()


func presentation_snapshot() -> Dictionary:
	var water_presenter := get_node_or_null("WaterWorldItemPresenter") as AndromedaWaterWorldItemPresenter
	return {
		"target_ref": target_ref,
		"target_kind": target_kind,
		"source_ref": source_ref,
		"source_kind": source_kind,
		"item_ref": item_ref,
		"item_kind": item_kind,
		"quantity": projected_quantity,
		"icon_category": _icon_category,
		"state": _authoritative_state,
		"active": is_active_for_pickup(),
		"settled_authoritative_projection": settled,
		"settled_local_physics": _locally_settled,
		"pickup_settled": is_pickup_settled(),
		"reachable_projection": projected_reachable,
		"water_exposure_s": _water_exposure_s,
		"water_ttl_s_contract": WATER_EXPOSURE_CONTRACT_S,
		"water_physics_state": water_presenter.presentation_state() if water_presenter != null else "NOT_PRESENT",
		"water_ttl_advanced_locally": false,
		"local_timer_can_sink": false,
		"projection_session_ref": _projection_session_ref,
		"last_projection_sequence": _last_projection_sequence,
		"compatibility_source_alias_received": _compatibility_source_alias_received,
		"item_grant_authority": false,
		"quantity_authority": false,
		"inventory_authority": false,
		"ownership_authority": false,
		"ttl_authority": false,
		"authority": GROUND_LOOT_AUTHORITY,
	}


func _on_local_physics_settled() -> void:
	set("freeze", true)
	set("linear_velocity", Vector3.ZERO)
	set("angular_velocity", Vector3.ZERO)
	_set_local_settled(true)
	if not _authoritative_projection_seen:
		set_settled(true)


func _set_local_settled(value: bool) -> void:
	if _locally_settled == value:
		return
	_locally_settled = value
	local_settling_changed.emit(target_ref, _locally_settled)
	if not _authoritative_projection_seen:
		set_settled(_locally_settled)


func _validate_projection_identity(
	payload: Dictionary,
	session_ref_value: String,
	snapshot_sequence: int
) -> Dictionary:
	var normalized_session: String = session_ref_value.strip_edges()
	if normalized_session.is_empty():
		return _rejected("EMPTY_PROJECTION_SESSION_REF")
	if not _projection_session_ref.is_empty() and normalized_session != _projection_session_ref:
		return _rejected("GROUND_LOOT_SESSION_MISMATCH")
	if snapshot_sequence < 0:
		return _rejected("INVALID_GROUND_LOOT_SNAPSHOT_SEQUENCE")
	if snapshot_sequence <= _last_projection_sequence:
		return _rejected("STALE_OR_DUPLICATE_GROUND_LOOT_SNAPSHOT")
	var payload_ref: String = str(payload.get("target_ref", payload.get("drop_ref", ""))).strip_edges()
	if payload_ref.is_empty() or payload_ref != target_ref:
		return _rejected("GROUND_LOOT_TARGET_REF_MISMATCH")
	return {"status": "PASS", "authority": GROUND_LOOT_AUTHORITY}


func _normalize_source_kind(source_kind_value: String) -> String:
	var normalized: String = source_kind_value.strip_edges().to_upper()
	if normalized == "PRODUCTION":
		_compatibility_source_alias_received = true
		return "PHYSICAL_PRODUCTION"
	return normalized


func _apply_category_presentation() -> void:
	var visual := get_node_or_null("PlaceholderVisual") as MeshInstance3D
	if visual != null and visual.mesh != null:
		visual.mesh = visual.mesh.duplicate(true)
		var material := visual.mesh.surface_get_material(0) as StandardMaterial3D
		if material != null:
			material = material.duplicate(true)
			material.albedo_color = CATEGORY_COLORS.get(_icon_category, Color("d2c86f")) as Color
			visual.mesh.surface_set_material(0, material)
	var label := get_node_or_null("OptionalMinimalLabel") as Label3D
	if label != null:
		label.text = "%s  x%d" % [_icon_category.trim_prefix("ICON_"), projected_quantity]
	_apply_minimal_label_visibility()


func _apply_active_presentation() -> void:
	var active: bool = is_active_for_pickup()
	visible = active
	selectable = active
	set("collision_layer", LAYER_GROUND_LOOT if active else 0)
	var pickup_sensor := get_node_or_null("PickupSensor") as Area3D
	if pickup_sensor != null:
		pickup_sensor.collision_layer = LAYER_GROUND_LOOT if active else 0
		pickup_sensor.monitorable = active
	_apply_minimal_label_visibility()


func _apply_minimal_label_visibility() -> void:
	var label := get_node_or_null("OptionalMinimalLabel") as Label3D
	if label != null:
		label.visible = is_active_for_pickup() and (is_hovered() or is_selected())


func _physical_linear_velocity() -> Vector3:
	var value: Variant = get("linear_velocity")
	return value as Vector3 if value is Vector3 else Vector3.ZERO


func _physical_angular_velocity() -> Vector3:
	var value: Variant = get("angular_velocity")
	return value as Vector3 if value is Vector3 else Vector3.ZERO


func _valid_nonnegative_number(value: Variant) -> bool:
	if typeof(value) != TYPE_INT and typeof(value) != TYPE_FLOAT:
		return false
	return is_finite(float(value)) and float(value) >= 0.0


func _valid_positive_integral_wire_number(value: Variant) -> bool:
	if typeof(value) == TYPE_BOOL:
		return false
	if typeof(value) == TYPE_INT:
		return int(value) > 0
	if typeof(value) != TYPE_FLOAT or not is_finite(float(value)):
		return false
	return float(value) > 0.0 and is_equal_approx(float(value), round(float(value)))


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": GROUND_LOOT_AUTHORITY}
