extends Control
class_name AndromedaStaminaWorldRing

## Screen-space projection of authoritative stamina. This node only presents a fraction and phase.

const AUTHORITY := "GODOT_STAMINA_PRESENTATION_ONLY"
const ACTIVITY_INACTIVE := "INACTIVE"
const ACTIVITY_CONSUMING := "CONSUMING"
const ACTIVITY_REGENERATING := "REGENERATING"
const FULL_EPSILON := 0.000001
const SOFT_YELLOW := Color("f2cf58")
const TRACK_COLOR := Color(0.33, 0.32, 0.27, 0.24)
const SHADOW_COLOR := Color(0.08, 0.08, 0.09, 0.3)

@export var player_offset_world: Vector3 = Vector3(0.55, 1.35, 0.0)
@export var screen_offset_px: Vector2 = Vector2(18.0, -8.0)
@export var radius_px: float = 17.0
@export var thickness_px: float = 5.0

var _fraction: float = 1.0
var _activity: String = ACTIVITY_INACTIVE
var _source: String = "NONE"
var _anchor: Node3D
var _camera: Camera3D
var _projection_available: bool = false


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	visible = false
	queue_redraw()


func _process(_delta: float) -> void:
	_update_projection()


func bind_projection(anchor: Node3D, camera: Camera3D) -> void:
	_anchor = anchor
	_camera = camera
	_update_projection()


func project_stamina(fraction_value: float, activity_value: String, source_value: String) -> Dictionary:
	if is_nan(fraction_value) or is_inf(fraction_value):
		return _rejected("NON_FINITE_STAMINA_FRACTION")
	var normalized_activity: String = activity_value.strip_edges().to_upper()
	if normalized_activity not in [ACTIVITY_INACTIVE, ACTIVITY_CONSUMING, ACTIVITY_REGENERATING]:
		return _rejected("UNKNOWN_STAMINA_ACTIVITY")
	_fraction = clampf(fraction_value, 0.0, 1.0)
	_activity = normalized_activity
	_source = source_value.strip_edges().to_upper()
	_apply_contract_visibility()
	queue_redraw()
	return {
		"status": "PASS",
		"fraction": _fraction,
		"activity": _activity,
		"visible": visible,
		"source": _source,
		"authoritative_stamina_mutated": false,
		"authority": AUTHORITY,
	}


func stamina_fraction() -> float:
	return _fraction


func activity_state() -> String:
	return _activity


func projection_source() -> String:
	return _source


func should_be_visible() -> bool:
	return _activity != ACTIVITY_INACTIVE or _fraction < 1.0 - FULL_EPSILON


func contract_snapshot() -> Dictionary:
	return {
		"shape": "CIRCLE_RADIAL",
		"color": "SOFT_YELLOW",
		"placement": "PLAYER_ADJACENT_SCREEN_SPACE",
		"hide_when_full_and_inactive": true,
		"permanent_numbers": false,
		"horizontal_bar": false,
		"fraction": _fraction,
		"activity": _activity,
		"visible": visible,
		"gameplay_authority_in_gdscript": false,
		"authority": AUTHORITY,
	}


func _draw() -> void:
	var center: Vector2 = size * 0.5
	draw_arc(center + Vector2(1.5, 2.0), radius_px, 0.0, TAU, 64, SHADOW_COLOR, thickness_px + 2.0, true)
	draw_arc(center, radius_px, 0.0, TAU, 64, TRACK_COLOR, thickness_px, true)
	if _fraction <= FULL_EPSILON:
		return
	var start_angle: float = -PI * 0.5
	var end_angle: float = start_angle + TAU * _fraction
	draw_arc(center, radius_px, start_angle, end_angle, 64, SOFT_YELLOW, thickness_px, true)


func _update_projection() -> void:
	_projection_available = (
		_anchor != null
		and is_instance_valid(_anchor)
		and _camera != null
		and is_instance_valid(_camera)
	)
	if not _projection_available:
		visible = false
		return
	var world_anchor: Vector3 = _anchor.global_position + player_offset_world
	if _camera.is_position_behind(world_anchor):
		visible = false
		return
	position = _camera.unproject_position(world_anchor) + screen_offset_px - size * 0.5
	_apply_contract_visibility()


func _apply_contract_visibility() -> void:
	visible = _projection_available and should_be_visible()


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}

