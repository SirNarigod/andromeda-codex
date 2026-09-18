extends Node
class_name AndromedaWaterWorldItemPresenter

## Local world-item physics/presentation adapter. It never advances authoritative TTL.

signal presentation_state_changed(state: String)

const AUTHORITY := "GODOT_WORLD_ITEM_PRESENTATION_ONLY"
const ITEM_WATER_TTL_S_CONTRACT := 900.0
const BAG_WATER_TTL_S_CONTRACT := 1800.0

@export_enum("INDIVIDUAL_LOOT", "DROPPED_BAG") var item_kind: String = "INDIVIDUAL_LOOT"
@export var settle_speed_mps: float = 0.08
@export var settle_delay_s: float = 0.35

var _state: String = "FROZEN_PLACEHOLDER"
var _settle_elapsed_s: float = 0.0
var _water_volume: AndromedaWaterVolume


func _ready() -> void:
	process_physics_priority = 10
	_set_state("LANDED_STABLE" if _body().freeze else "SETTLING_LAND")
	_body().set_meta("water_presentation_state", _state)
	_body().set_meta("authoritative_ttl_advanced_locally", false)


func _physics_process(delta: float) -> void:
	var body := _body()
	if _state == "SETTLING_LAND":
		_settle_elapsed_s += delta
		if _settle_elapsed_s >= settle_delay_s and body.linear_velocity.length() <= settle_speed_mps:
			body.freeze = true
			body.linear_velocity = Vector3.ZERO
			body.angular_velocity = Vector3.ZERO
			_set_state("LANDED_STABLE")
	elif _state == "FLOATING" and is_instance_valid(_water_volume):
		body.global_position.y = _water_volume.surface_world_y() - 0.04
		body.global_position += _water_volume.presentation_current_displacement(delta)


func begin_physical_settle() -> void:
	var body := _body()
	_water_volume = null
	_settle_elapsed_s = 0.0
	body.freeze = false
	body.gravity_scale = 1.0
	body.linear_velocity = Vector3.ZERO
	body.angular_velocity = Vector3.ZERO
	_set_state("SETTLING_LAND")


func settle_on_terrain(surface_position: Vector3) -> void:
	var body := _body()
	_water_volume = null
	body.freeze = true
	body.gravity_scale = 1.0
	body.linear_velocity = Vector3.ZERO
	body.angular_velocity = Vector3.ZERO
	body.global_position = surface_position
	_set_state("LANDED_STABLE")


func enter_water(volume: AndromedaWaterVolume) -> void:
	if volume == null:
		return
	var body := _body()
	_water_volume = volume
	body.freeze = true
	body.linear_velocity = Vector3.ZERO
	body.angular_velocity = Vector3.ZERO
	if item_kind == "DROPPED_BAG":
		# Keep the bag's physical root just inside the Area3D while its visual body
		# remains above the water line; this prevents enter/exit oscillation.
		body.global_position.y = volume.surface_world_y() - 0.04
		_set_state("FLOATING")
	else:
		body.global_position.y = minf(body.global_position.y, volume.surface_world_y() - 0.08)
		_set_state("RECOVERABLE_IN_WATER")


func exit_water(volume: AndromedaWaterVolume) -> void:
	if volume != _water_volume:
		return
	_water_volume = null
	if _state in ["FLOATING", "RECOVERABLE_IN_WATER"]:
		_set_state("LANDED_STABLE")


func presentation_state() -> String:
	return _state


func contract_snapshot() -> Dictionary:
	var in_water: bool = _state in ["FLOATING", "RECOVERABLE_IN_WATER"]
	var ttl_contract: Variant = null
	if in_water:
		ttl_contract = BAG_WATER_TTL_S_CONTRACT if item_kind == "DROPPED_BAG" else ITEM_WATER_TTL_S_CONTRACT
	var land_expiry: Variant = "NOT_APPLICABLE"
	if item_kind == "DROPPED_BAG" and not in_water:
		land_expiry = null
	return {
		"item_kind": item_kind,
		"state": _state,
		"in_water": in_water,
		"floats": item_kind == "DROPPED_BAG" and _state == "FLOATING",
		"authoritative_ttl_s_contract": ttl_contract,
		"land_expiry": land_expiry,
		"authoritative_ttl_advanced_locally": false,
		"ttl_authority": "STAGE16A_BACKEND_SNAPSHOT_REQUIRED",
		"physics_state_local_only": true,
		"authority": AUTHORITY,
	}


func _body() -> RigidBody3D:
	return get_parent() as RigidBody3D


func _set_state(next_state: String) -> void:
	if _state == next_state:
		return
	_state = next_state
	var body := _body()
	if body != null:
		body.set_meta("water_presentation_state", _state)
	presentation_state_changed.emit(_state)
