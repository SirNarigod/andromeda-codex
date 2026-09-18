extends PanelContainer
class_name AndromedaPlayerCombatVitals

## B06 player combat HUD. Values are projected; this node never derives gameplay outcomes.

const AUTHORITY := "GODOT_COMBAT_VITALS_PRESENTATION_ONLY"
const IDLE_ALPHA := 0.22
const ACTIVE_ALPHA := 0.92
const FEEDBACK_RELEVANCE_S := 0.9

@onready var _hp_bar: ProgressBar = $Margin/Layout/HPRow/HPBar
@onready var _protection_row: HBoxContainer = $Margin/Layout/ProtectionRow
@onready var _protection_bar: ProgressBar = $Margin/Layout/ProtectionRow/ProtectionBar
@onready var _state_label: Label = $Margin/Layout/StateLabel

var _hp_fraction: float = 1.0
var _protection_fraction: float = 0.0
var _externally_relevant: bool = false
var _feedback_remaining_s: float = 0.0
var _projection_source: String = "UNBOUND"
var _last_feedback_token: String = ""


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_apply_values()
	_apply_relevance()


func _process(delta: float) -> void:
	if _feedback_remaining_s <= 0.0:
		return
	_feedback_remaining_s = maxf(0.0, _feedback_remaining_s - delta)
	if _feedback_remaining_s <= 0.0:
		_apply_relevance()


func project_vitals(
	hp_fraction_value: float,
	protection_fraction_value: float,
	relevant: bool,
	source: String
) -> Dictionary:
	if not _valid_fraction(hp_fraction_value) or not _valid_fraction(protection_fraction_value):
		return _rejected("FRACTION_OUT_OF_RANGE")
	if source.strip_edges().is_empty():
		return _rejected("PROJECTION_SOURCE_REQUIRED")
	_hp_fraction = hp_fraction_value
	_protection_fraction = protection_fraction_value
	_externally_relevant = relevant
	_projection_source = source
	_apply_values()
	_apply_relevance()
	return {
		"status": "PASS",
		"hp_fraction": _hp_fraction,
		"protection_fraction": _protection_fraction,
		"relevant": _externally_relevant,
		"source": _projection_source,
		"authoritative_hp_mutated": false,
		"authoritative_protection_mutated": false,
		"authority": AUTHORITY,
	}


func present_semantic_feedback(token: String) -> Dictionary:
	if token not in ["PLAYER_HURT", "PLAYER_SHIELD_HIT"]:
		return _rejected("UNSUPPORTED_PLAYER_FEEDBACK_TOKEN")
	_last_feedback_token = token
	_feedback_remaining_s = FEEDBACK_RELEVANCE_S
	_state_label.text = "PROTEÇÃO" if token == "PLAYER_SHIELD_HIT" else "IMPACTO"
	_state_label.add_theme_color_override(
		"font_color",
		Color("d9a15f") if token == "PLAYER_SHIELD_HIT" else Color("b86f58")
	)
	modulate.a = ACTIVE_ALPHA
	return {
		"status": "PASS",
		"token": token,
		"hp_fraction_unchanged": _hp_fraction,
		"protection_fraction_unchanged": _protection_fraction,
		"authority": AUTHORITY,
	}


func set_relevant(relevant: bool) -> void:
	_externally_relevant = relevant
	_apply_relevance()


func hp_fraction() -> float:
	return _hp_fraction


func protection_fraction() -> float:
	return _protection_fraction


func projection_source() -> String:
	return _projection_source


func presentation_alpha() -> float:
	return modulate.a


func protection_channel_visible() -> bool:
	return _protection_row.visible


func last_feedback_token() -> String:
	return _last_feedback_token


func contract_snapshot() -> Dictionary:
	return {
		"layout": "SMALL_CONTEXTUAL_ROUNDED",
		"idle_alpha": IDLE_ALPHA,
		"active_alpha": ACTIVE_ALPHA,
		"hp_channel": true,
		"protection_channel": true,
		"stamina_channel": false,
		"permanent_large_bar": false,
		"damage_calculation": false,
		"protection_consumption_calculation": false,
		"gameplay_authority_in_gdscript": false,
		"authority": AUTHORITY,
	}


func _apply_values() -> void:
	_hp_bar.value = _hp_fraction * 100.0
	_protection_bar.value = _protection_fraction * 100.0
	_protection_row.visible = _protection_fraction > 0.0 or _externally_relevant


func _apply_relevance() -> void:
	modulate.a = ACTIVE_ALPHA if _externally_relevant or _feedback_remaining_s > 0.0 else IDLE_ALPHA
	if _feedback_remaining_s <= 0.0:
		_state_label.text = "COMBATE" if _externally_relevant else "ESTADO"
		_state_label.add_theme_color_override("font_color", Color("8a8a8a"))


func _valid_fraction(value: float) -> bool:
	return not is_nan(value) and not is_inf(value) and value >= 0.0 and value <= 1.0


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
