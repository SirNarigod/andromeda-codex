extends AndromedaInteractionTarget
class_name AndromedaDroppedBag

## B10 presentation for an externally-authorized dropped Bag container.
## This node never decides death, contents, ownership, recovery, TTL or SUNK.

const AUTHORITY_B10 := "GODOT_DROPPED_BAG_PRESENTATION_ONLY"
const STATE_DROPPED_LAND := "DROPPED_LAND"
const STATE_DROPPED_WATER_FLOATING := "DROPPED_WATER_FLOATING"
const STATE_RECOVERED := "RECOVERED"
const STATE_RECOVERED_FOREIGN := "RECOVERED_FOREIGN"
const STATE_SUNK := "SUNK"
const STATE_REMOVED := "REMOVED"
const ENVIRONMENT_LAND := "LAND"
const ENVIRONMENT_WATER := "WATER"
const STREAM_ACTIVE := "ACTIVE"
const STREAM_PRELOAD := "PRELOAD"
const STREAM_SYSTEMIC := "SYSTEMIC"
const WATER_TTL_CONTRACT_S := 1800.0
const ACTIVE_PRESENTATION_STATES: Array[String] = [
	STATE_DROPPED_LAND,
	STATE_DROPPED_WATER_FLOATING,
]
const TERMINAL_PRESENTATION_STATES: Array[String] = [
	STATE_RECOVERED,
	STATE_RECOVERED_FOREIGN,
	STATE_SUNK,
	STATE_REMOVED,
]

@export var bag_ref: String = ""
@export var original_owner_ref: String = ""
@export var recovery_range_m: float = 0.5

@onready var recovery_sensor: Area3D = $RecoverySensor
@onready var recovery_sensor_shape: CollisionShape3D = $RecoverySensor/CollisionShape3D
@onready var float_anchor: Marker3D = $FloatAnchor
@onready var owner_hint: Label3D = $OptionalOwnerHint
@onready var water_presenter: AndromedaWaterWorldItemPresenter = $WaterWorldItemPresenter

var _projection_session_ref: String = ""
var _last_projection_sequence: int = -1
var _projected_state: String = STATE_DROPPED_LAND
var _environment: String = ENVIRONMENT_LAND
var _recoverable: bool = false
var _water_exposure_s: float = 0.0
var _water_ttl_s: Variant = null
var _carrier_ref: String = ""
var _origin_context: Dictionary = {}
var _contents_summary: Array = []
var _stream_phase: String = STREAM_ACTIVE
var _stream_sequence: int = -1


func _ready() -> void:
	target_kind = AndromedaInputRouter.HIT_DROPPED_BAG
	if bag_ref.strip_edges().is_empty():
		bag_ref = target_ref.strip_edges()
	if target_ref.strip_edges().is_empty():
		target_ref = bag_ref.strip_edges()
	display_name = "Bolsa caída"
	settled = true
	super._ready()
	add_to_group("andromeda_dropped_bag")
	_apply_projection_presentation()


func configure_identity(
	bag_ref_value: String,
	original_owner_ref_value: String,
	origin_context_value: Dictionary = {}
) -> Dictionary:
	var normalized_bag_ref: String = bag_ref_value.strip_edges()
	var normalized_owner_ref: String = original_owner_ref_value.strip_edges()
	if normalized_bag_ref.is_empty():
		return _rejected("BAG_REF_REQUIRED")
	if normalized_owner_ref.is_empty():
		return _rejected("ORIGINAL_OWNER_REF_REQUIRED")
	if not bag_ref.is_empty() and bag_ref != normalized_bag_ref:
		return _rejected("BAG_IDENTITY_IMMUTABLE")
	bag_ref = normalized_bag_ref
	target_ref = normalized_bag_ref
	original_owner_ref = normalized_owner_ref
	_origin_context = origin_context_value.duplicate(true)
	return {
		"status": "PASS",
		"bag_ref": bag_ref,
		"target_ref": target_ref,
		"original_owner_ref": original_owner_ref,
		"authority": AUTHORITY_B10,
	}


func apply_authoritative_projection(
	projection: Dictionary,
	session_ref_value: String,
	projection_sequence: int
) -> Dictionary:
	if projection.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_DROPPED_BAG_PROJECTION")
	if session_ref_value.strip_edges().is_empty():
		return _rejected("SESSION_REF_REQUIRED")
	if projection_sequence < 0:
		return _rejected("INVALID_DROPPED_BAG_SEQUENCE")
	if not _projection_session_ref.is_empty() and _projection_session_ref != session_ref_value:
		return _rejected("DROPPED_BAG_PROJECTION_SESSION_MISMATCH")
	if projection_sequence <= _last_projection_sequence:
		return _rejected("STALE_OR_DUPLICATE_DROPPED_BAG_PROJECTION")
	var incoming_ref: String = str(projection.get("bag_ref", projection.get("target_ref", ""))).strip_edges()
	if incoming_ref != bag_ref or incoming_ref != target_ref:
		return _rejected("DROPPED_BAG_TARGET_REF_MISMATCH")
	var incoming_owner: String = str(
		projection.get("original_owner_ref", projection.get("property_owner_ref", ""))
	).strip_edges()
	if incoming_owner.is_empty() or incoming_owner != original_owner_ref:
		return _rejected("DROPPED_BAG_ORIGINAL_OWNER_MISMATCH")
	var incoming_state: String = str(projection.get("state", "")).strip_edges().to_upper()
	if incoming_state not in ACTIVE_PRESENTATION_STATES + TERMINAL_PRESENTATION_STATES:
		return _rejected("INVALID_DROPPED_BAG_STATE")
	var incoming_environment: String = str(
		projection.get("environment", projection.get("location_kind", ""))
	).strip_edges().to_upper()
	if incoming_environment not in [ENVIRONMENT_LAND, ENVIRONMENT_WATER]:
		return _rejected("INVALID_DROPPED_BAG_ENVIRONMENT")
	var exposure_value: Variant = projection.get("water_exposure_s", 0.0)
	if not _valid_nonnegative_number(exposure_value):
		return _rejected("INVALID_DROPPED_BAG_WATER_EXPOSURE")
	var ttl_value: Variant = projection.get("water_ttl_s", null)
	if incoming_environment == ENVIRONMENT_LAND and ttl_value != null:
		return _rejected("LAND_DROPPED_BAG_MUST_HAVE_NO_EXPIRY")
	if incoming_environment == ENVIRONMENT_WATER:
		if not _valid_nonnegative_number(ttl_value) or not is_equal_approx(float(ttl_value), WATER_TTL_CONTRACT_S):
			return _rejected("WATER_DROPPED_BAG_TTL_CONTRACT_MISMATCH")
	if not projection.get("contents_summary", []) is Array:
		return _rejected("INVALID_DROPPED_BAG_CONTENTS_SUMMARY")
	if not projection.get("context_metadata", projection.get("origin_context", {})) is Dictionary:
		return _rejected("INVALID_DROPPED_BAG_CONTEXT_METADATA")

	_projection_session_ref = session_ref_value
	_last_projection_sequence = projection_sequence
	_projected_state = incoming_state
	_environment = incoming_environment
	_recoverable = bool(projection.get("recoverable", false))
	_water_exposure_s = float(exposure_value)
	_water_ttl_s = ttl_value
	_carrier_ref = str(projection.get("carrier_ref", projection.get("current_holder_ref", ""))).strip_edges()
	_origin_context = (projection.get("context_metadata", projection.get("origin_context", {})) as Dictionary).duplicate(true)
	_contents_summary = (projection.get("contents_summary", []) as Array).duplicate(true)
	selectable = _recoverable and _projected_state in ACTIVE_PRESENTATION_STATES
	_apply_projection_presentation()
	_propagate_pointer_metadata(self)
	return {
		"status": "PASS",
		"bag_ref": bag_ref,
		"state": _projected_state,
		"environment": _environment,
		"recoverable": _recoverable,
		"water_exposure_s": _water_exposure_s,
		"water_ttl_s": _water_ttl_s,
		"ttl_advanced_locally": false,
		"ownership_mutated_locally": false,
		"contents_mutated_locally": false,
		"authority": AUTHORITY_B10,
	}


func project_stream_phase(phase_value: String, sequence: int, externally_confirmed: bool) -> Dictionary:
	if not externally_confirmed:
		return _rejected("EXTERNAL_STREAM_PHASE_REQUIRED")
	var phase: String = phase_value.strip_edges().to_upper()
	if phase not in [STREAM_ACTIVE, STREAM_PRELOAD, STREAM_SYSTEMIC]:
		return _rejected("INVALID_DROPPED_BAG_STREAM_PHASE")
	if sequence <= _stream_sequence:
		return _rejected("STALE_OR_DUPLICATE_DROPPED_BAG_STREAM_PHASE")
	_stream_phase = phase
	_stream_sequence = sequence
	_apply_projection_presentation()
	return {
		"status": "PASS",
		"bag_ref": bag_ref,
		"stream_phase": _stream_phase,
		"identity_preserved": true,
		"systemic_state_owned_by_godot": false,
		"authority": AUTHORITY_B10,
	}


func interaction_anchor_world_position() -> Vector3:
	if recovery_sensor != null:
		return recovery_sensor.global_position
	return global_position


func float_anchor_world_position() -> Vector3:
	return float_anchor.global_position if float_anchor != null else global_position


func is_recoverable_projection() -> bool:
	return _recoverable and _projected_state in ACTIVE_PRESENTATION_STATES


func projected_state() -> String:
	return _projected_state


func environment() -> String:
	return _environment


func water_exposure_s() -> float:
	return _water_exposure_s


func water_ttl_s() -> Variant:
	return _water_ttl_s


func projection_session_ref() -> String:
	return _projection_session_ref


func last_projection_sequence() -> int:
	return _last_projection_sequence


func stream_phase() -> String:
	return _stream_phase


func physical_distance_to(actor: Node3D) -> float:
	if actor == null:
		return INF
	return actor.global_position.distance_to(interaction_anchor_world_position())


func presentation_snapshot() -> Dictionary:
	return {
		"bag_ref": bag_ref,
		"target_ref": target_ref,
		"target_kind": target_kind,
		"original_owner_ref": original_owner_ref,
		"carrier_ref": _carrier_ref,
		"state": _projected_state,
		"environment": _environment,
		"recoverable": _recoverable,
		"water_exposure_s": _water_exposure_s,
		"water_ttl_s": _water_ttl_s,
		"contents_summary": _contents_summary.duplicate(true),
		"context_metadata": _origin_context.duplicate(true),
		"stream_phase": _stream_phase,
		"projection_session_ref": _projection_session_ref,
		"projection_sequence": _last_projection_sequence,
		"ttl_authority_in_gdscript": false,
		"ownership_authority_in_gdscript": false,
		"contents_authority_in_gdscript": false,
		"recovery_authority_in_gdscript": false,
		"authority": AUTHORITY_B10,
	}


func contract_snapshot() -> Dictionary:
	return {
		"semantic_identity": "DROPPED_BAG_CONTAINER_NOT_GROUND_LOOT",
		"collision_layer": int(get("collision_layer")),
		"required_children": ["CollisionShape3D", "PlaceholderVisual", "RecoverySensor", "FloatAnchor", "OptionalOwnerHint"],
		"land_expiry": null,
		"water_ttl_contract_s": WATER_TTL_CONTRACT_S,
		"water_ttl_authority": false,
		"death_authority": false,
		"ownership_authority": false,
		"contents_authority": false,
		"recovery_authority": false,
		"backend_substitute": false,
		"final_art": false,
		"authority": AUTHORITY_B10,
	}


func _apply_projection_presentation() -> void:
	var detailed_visible: bool = _stream_phase != STREAM_SYSTEMIC and _projected_state not in TERMINAL_PRESENTATION_STATES
	var visual := get_node_or_null("PlaceholderVisual") as MeshInstance3D
	if visual != null:
		visual.visible = detailed_visible
	var collision_shape := get_node_or_null("CollisionShape3D") as CollisionShape3D
	if collision_shape != null:
		collision_shape.disabled = not detailed_visible
	if recovery_sensor != null:
		recovery_sensor.monitoring = detailed_visible and _recoverable
		recovery_sensor.monitorable = detailed_visible and _recoverable
	if recovery_sensor_shape != null:
		recovery_sensor_shape.disabled = not detailed_visible or not _recoverable
	if owner_hint != null:
		owner_hint.text = "Bolsa  ·  origem preservada"
		owner_hint.visible = detailed_visible and is_hovered()
	visible = detailed_visible or _stream_phase == STREAM_PRELOAD
	set("freeze", true)
	set("linear_velocity", Vector3.ZERO)
	set("angular_velocity", Vector3.ZERO)


func set_hovered(value: bool) -> void:
	super.set_hovered(value)
	if owner_hint != null:
		owner_hint.visible = value and visible


func _valid_nonnegative_number(value: Variant) -> bool:
	return (
		typeof(value) in [TYPE_INT, TYPE_FLOAT]
		and typeof(value) != TYPE_BOOL
		and is_finite(float(value))
		and float(value) >= 0.0
	)


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY_B10}
