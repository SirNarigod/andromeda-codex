extends PanelContainer
class_name AndromedaWeaponQuickSlots

## Exactly-two-slot presentation. Active MAIN_HAND state remains authoritative outside Godot.

signal active_slot_projected(slot: int, source: String)

const AUTHORITY := "GODOT_WEAPON_QUICKSLOT_PRESENTATION_ONLY"
const SLOT_COUNT := 2
const IDLE_ALPHA := 0.58
const ACTIVE_ALPHA := 0.96

@onready var _slot_one: PanelContainer = $Margin/Slots/Slot1
@onready var _slot_two: PanelContainer = $Margin/Slots/Slot2
@onready var _slot_one_status: Label = $Margin/Slots/Slot1/Content/Status
@onready var _slot_two_status: Label = $Margin/Slots/Slot2/Content/Status

var _active_slot: int = 1
var _projection_source: String = "LOCAL_PLACEHOLDER"
var _emphasis_remaining_s: float = 0.0


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_apply_slot_styles()
	modulate.a = IDLE_ALPHA


func _process(delta: float) -> void:
	if _emphasis_remaining_s > 0.0:
		_emphasis_remaining_s = maxf(0.0, _emphasis_remaining_s - delta)
		modulate.a = lerpf(modulate.a, ACTIVE_ALPHA, minf(1.0, delta * 12.0))
	else:
		modulate.a = lerpf(modulate.a, IDLE_ALPHA, minf(1.0, delta * 4.0))


func project_active_slot(slot: int, source_value: String) -> Dictionary:
	if slot < 1 or slot > SLOT_COUNT:
		return _rejected("WEAPON_SLOT_MUST_BE_1_OR_2")
	_active_slot = slot
	_projection_source = source_value.strip_edges().to_upper()
	_emphasis_remaining_s = 1.2
	_apply_slot_styles()
	active_slot_projected.emit(_active_slot, _projection_source)
	return {
		"status": "PASS",
		"active_slot": _active_slot,
		"slot_count": SLOT_COUNT,
		"source": _projection_source,
		"authoritative_main_hand_changed": false,
		"authority": AUTHORITY,
	}


func cycle_slot(delta: int, source_value: String) -> Dictionary:
	if delta == 0:
		return _rejected("ZERO_SLOT_DELTA")
	var next_slot: int = 2 if _active_slot == 1 else 1
	return project_active_slot(next_slot, source_value)


func active_slot() -> int:
	return _active_slot


func slot_count() -> int:
	return SLOT_COUNT


func projection_source() -> String:
	return _projection_source


func contract_snapshot() -> Dictionary:
	return {
		"max_quick_slots": SLOT_COUNT,
		"visible_slots": [1, 2],
		"active_slot": _active_slot,
		"simultaneously_active_visual_slots": 1,
		"inactive_modifiers_applied": false,
		"presentation": "SMALL_WHITE_ROUNDED_QUICK_SLOTS",
		"idle_behavior": "FADE_TO_DISCREET_AFTER_SWAP",
		"gameplay_authority_in_gdscript": false,
		"authority": AUTHORITY,
	}


func _apply_slot_styles() -> void:
	_slot_one.add_theme_stylebox_override("panel", _slot_style(_active_slot == 1))
	_slot_two.add_theme_stylebox_override("panel", _slot_style(_active_slot == 2))
	_slot_one_status.text = "ATIVA" if _active_slot == 1 else "PRONTA"
	_slot_two_status.text = "ATIVA" if _active_slot == 2 else "PRONTA"
	_slot_one_status.add_theme_color_override("font_color", Color("d9a15f") if _active_slot == 1 else Color("8a8a8a"))
	_slot_two_status.add_theme_color_override("font_color", Color("d9a15f") if _active_slot == 2 else Color("8a8a8a"))


func _slot_style(active: bool) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = Color(1.0, 0.965, 0.89, 0.98) if active else Color(0.94, 0.935, 0.91, 0.86)
	style.border_width_left = 2 if active else 1
	style.border_width_top = 2 if active else 1
	style.border_width_right = 2 if active else 1
	style.border_width_bottom = 2 if active else 1
	style.border_color = Color(0.851, 0.631, 0.373, 0.9) if active else Color(0.72, 0.72, 0.69, 0.45)
	style.corner_radius_top_left = 12
	style.corner_radius_top_right = 12
	style.corner_radius_bottom_right = 12
	style.corner_radius_bottom_left = 12
	style.content_margin_left = 10.0
	style.content_margin_top = 7.0
	style.content_margin_right = 10.0
	style.content_margin_bottom = 7.0
	return style


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}

