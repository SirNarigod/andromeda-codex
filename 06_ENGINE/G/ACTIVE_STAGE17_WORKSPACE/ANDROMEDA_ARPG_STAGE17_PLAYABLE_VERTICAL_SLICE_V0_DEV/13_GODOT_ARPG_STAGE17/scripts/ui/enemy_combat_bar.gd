extends Control
class_name AndromedaEnemyCombatBar

## Screen-space combat bar keyed to one immutable target_ref.

const AUTHORITY := "GODOT_ENEMY_BAR_PRESENTATION_ONLY"
const SCREEN_OFFSET_PX := Vector2(0.0, -8.0)

@onready var _hp_bar: ProgressBar = $HPBar
@onready var _shield_bar: ProgressBar = $ShieldBar
@onready var _alpha_accent: ColorRect = $AlphaAccent

var _actor: Node3D
var _anchor: Node3D
var _camera: Camera3D
var _target_ref: String = ""
var _alpha_rank: bool = false
var _engaged: bool = false
var _hp_fraction: float = 1.0
var _shield_fraction: float = 0.0
var _projection_source: String = "UNBOUND"
var _defeat_confirmed: bool = false
var _last_feedback_token: String = ""
var _last_anchor_screen_position: Vector2 = Vector2.ZERO


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	visible = false
	_shield_bar.visible = false
	_alpha_accent.visible = false


func _process(_delta: float) -> void:
	_update_screen_projection()


func bind_projection(
	actor_node: Node3D,
	camera: Camera3D,
	target_ref_value: String,
	alpha_rank: bool
) -> Dictionary:
	var normalized_ref: String = target_ref_value.strip_edges()
	if actor_node == null or camera == null or normalized_ref.is_empty():
		return _rejected("ACTOR_CAMERA_TARGET_REF_REQUIRED")
	if not _target_ref.is_empty() and _target_ref != normalized_ref:
		return _rejected("TARGET_REF_BINDING_IMMUTABLE")
	var actor_ref: String = str(actor_node.get("target_ref")).strip_edges()
	if not actor_ref.is_empty() and actor_ref != normalized_ref:
		return _rejected("ACTOR_TARGET_REF_MISMATCH")
	_actor = actor_node
	_camera = camera
	_target_ref = normalized_ref
	_alpha_rank = alpha_rank
	_anchor = actor_node.get_node_or_null("HealthBarAnchor") as Node3D
	if _anchor == null:
		_anchor = actor_node
	_shield_bar.visible = _alpha_rank and _engaged
	_alpha_accent.visible = _alpha_rank and _engaged
	_update_screen_projection()
	return {
		"status": "PASS",
		"target_ref": _target_ref,
		"alpha_rank": _alpha_rank,
		"screen_aligned": true,
		"authority": AUTHORITY,
	}


func project_vitals(
	hp_fraction_value: float,
	shield_fraction_value: float,
	engaged: bool,
	source: String
) -> Dictionary:
	if _target_ref.is_empty():
		return _rejected("BAR_NOT_BOUND")
	if not _valid_fraction(hp_fraction_value) or not _valid_fraction(shield_fraction_value):
		return _rejected("FRACTION_OUT_OF_RANGE")
	if not _alpha_rank and shield_fraction_value > 0.0:
		return _rejected("COMMON_ENEMY_HAS_NO_SHIELD_CHANNEL")
	if source.strip_edges().is_empty():
		return _rejected("PROJECTION_SOURCE_REQUIRED")
	_hp_fraction = hp_fraction_value
	_shield_fraction = shield_fraction_value if _alpha_rank else 0.0
	_engaged = engaged
	_projection_source = source
	_defeat_confirmed = false
	_hp_bar.value = _hp_fraction * 100.0
	_shield_bar.value = _shield_fraction * 100.0
	_shield_bar.visible = _alpha_rank and _engaged
	_alpha_accent.visible = _alpha_rank and _engaged
	modulate = Color.WHITE
	_update_screen_projection()
	return {
		"status": "PASS",
		"target_ref": _target_ref,
		"hp_fraction": _hp_fraction,
		"shield_fraction": _shield_fraction,
		"engaged": _engaged,
		"source": _projection_source,
		"authoritative_hp_mutated": false,
		"authoritative_shield_mutated": false,
		"authority": AUTHORITY,
	}


func present_semantic_feedback(token: String) -> Dictionary:
	if token not in ["COMBAT_HIT", "COMBAT_CRITICAL_HIT", "TARGET_DEFEATED"]:
		return _rejected("UNSUPPORTED_TARGET_FEEDBACK_TOKEN")
	_last_feedback_token = token
	if token == "TARGET_DEFEATED":
		_defeat_confirmed = true
		modulate = Color(1.0, 0.82, 0.62, 0.62)
	else:
		modulate = Color(1.0, 0.92, 0.78, 1.0) if token == "COMBAT_CRITICAL_HIT" else Color(1.0, 0.97, 0.9, 1.0)
	return {
		"status": "PASS",
		"target_ref": _target_ref,
		"token": token,
		"hp_fraction_unchanged": _hp_fraction,
		"shield_fraction_unchanged": _shield_fraction,
		"actor_removed": false,
		"authority": AUTHORITY,
	}


func target_ref() -> String:
	return _target_ref


func actor() -> Node3D:
	return _actor


func is_alpha_rank() -> bool:
	return _alpha_rank


func is_engaged() -> bool:
	return _engaged


func hp_fraction() -> float:
	return _hp_fraction


func shield_fraction() -> float:
	return _shield_fraction


func projection_source() -> String:
	return _projection_source


func defeat_confirmed() -> bool:
	return _defeat_confirmed


func last_feedback_token() -> String:
	return _last_feedback_token


func anchor_screen_position() -> Vector2:
	return _last_anchor_screen_position


func hp_height_px() -> float:
	return _hp_bar.size.y


func shield_height_px() -> float:
	return _shield_bar.size.y


func hp_fill_color() -> Color:
	var style := _hp_bar.get_theme_stylebox("fill") as StyleBoxFlat
	return Color.TRANSPARENT if style == null else style.bg_color


func track_color() -> Color:
	var style := _hp_bar.get_theme_stylebox("background") as StyleBoxFlat
	return Color.TRANSPARENT if style == null else style.bg_color


func contract_snapshot() -> Dictionary:
	return {
		"placement": "FIXED_STRAIGHT_ABOVE_HEAD",
		"screen_aligned": true,
		"inherits_actor_rotation": false,
		"common_hp_only": true,
		"alpha_hp_and_shield": true,
		"shield_smaller_than_hp": true,
		"hidden_when_not_engaged": true,
		"black_failure_state": false,
		"binding_key": "TARGET_REF_IMMUTABLE",
		"gameplay_authority_in_gdscript": false,
		"authority": AUTHORITY,
	}


func _update_screen_projection() -> void:
	if _actor == null or _anchor == null or _camera == null:
		visible = false
		return
	if not is_instance_valid(_actor) or not is_instance_valid(_anchor) or not is_instance_valid(_camera):
		visible = false
		return
	if _camera.is_position_behind(_anchor.global_position):
		visible = false
		return
	_last_anchor_screen_position = _camera.unproject_position(_anchor.global_position)
	position = _last_anchor_screen_position - size * Vector2(0.5, 1.0) + SCREEN_OFFSET_PX
	rotation = 0.0
	visible = _engaged


func _valid_fraction(value: float) -> bool:
	return not is_nan(value) and not is_inf(value) and value >= 0.0 and value <= 1.0


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
