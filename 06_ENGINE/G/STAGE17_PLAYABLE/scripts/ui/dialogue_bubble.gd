extends Control
class_name AndromedaDialogueBubble

## Realtime world-bubble presenter. Text and choices must arrive from an external authority or gate fixture.

signal choice_intent_requested(npc_ref: String, choice_ref: String)
signal presentation_finished(line_ref: String)

const AUTHORITY := "GODOT_DIALOGUE_PRESENTATION_ONLY"
const NORMAL_TEXT := Color("6b6b6b")
const IMPORTANT_TEXT := Color("d9a15f")
const MIN_DURATION_S := 1.8
const MAX_DURATION_S := 8.0

@onready var _dialogue_text: Label = $RoundedWhiteBubble/Margin/Content/DialogueText
@onready var _choice_list: VBoxContainer = $RoundedWhiteBubble/Margin/Content/ChoiceList
@onready var _choice_buttons: Array[Button] = [
	$RoundedWhiteBubble/Margin/Content/ChoiceList/Choice1,
	$RoundedWhiteBubble/Margin/Content/ChoiceList/Choice2,
	$RoundedWhiteBubble/Margin/Content/ChoiceList/Choice3,
]

var _anchor: Node3D
var _camera: Camera3D
var _line_ref: String = ""
var _speaker_ref: String = ""
var _npc_ref: String = ""
var _conversation_ref: String = ""
var _turn_index: int = 0
var _important: bool = false
var _remaining_s: float = 0.0
var _line_active: bool = false
var _choice_refs: Array[String] = []


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	for index: int in range(_choice_buttons.size()):
		_choice_buttons[index].pressed.connect(_on_choice_pressed.bind(index))
		_choice_buttons[index].visible = false
	visible = false


func _process(delta: float) -> void:
	if not _line_active:
		return
	_update_projection()
	_remaining_s = maxf(0.0, _remaining_s - delta)
	if _remaining_s <= 0.0 and not choices_visible():
		hide_presentation()


func project_line(anchor: Node3D, camera: Camera3D, payload: Dictionary) -> Dictionary:
	var text_value: String = str(payload.get("text", "")).strip_edges()
	var line_value: String = str(payload.get("line_ref", "")).strip_edges()
	var speaker_value: String = str(payload.get("speaker_ref", "")).strip_edges()
	if text_value.is_empty() or line_value.is_empty() or speaker_value.is_empty():
		return _rejected("LINE_REF_SPEAKER_AND_TEXT_REQUIRED")
	if anchor == null or camera == null:
		return _rejected("DIALOGUE_ANCHOR_AND_CAMERA_REQUIRED")
	_anchor = anchor
	_camera = camera
	_line_ref = line_value
	_speaker_ref = speaker_value
	_npc_ref = str(payload.get("npc_ref", speaker_value)).strip_edges()
	_conversation_ref = str(payload.get("conversation_ref", "")).strip_edges()
	_turn_index = int(payload.get("turn_index", 0))
	_important = bool(payload.get("important", false))
	var requested_duration: float = float(payload.get("duration_seconds", _reading_duration(text_value, _important)))
	_remaining_s = clampf(requested_duration, MIN_DURATION_S, MAX_DURATION_S)
	_dialogue_text.text = text_value
	_dialogue_text.add_theme_color_override("font_color", IMPORTANT_TEXT if _important else NORMAL_TEXT)
	clear_choices()
	_line_active = true
	visible = true
	_update_projection()
	return {
		"status": "PASS",
		"line_ref": _line_ref,
		"speaker_ref": _speaker_ref,
		"conversation_ref": _conversation_ref,
		"turn_index": _turn_index,
		"important": _important,
		"duration_seconds": _remaining_s,
		"auto_advance": true,
		"next_button": false,
		"movement_lock": false,
		"world_pause": false,
		"authority": AUTHORITY,
	}


func project_choices(choices: Array) -> Dictionary:
	clear_choices()
	if choices.is_empty():
		return _rejected("CHOICES_REQUIRED")
	var visible_count: int = mini(choices.size(), _choice_buttons.size())
	for index: int in range(visible_count):
		var raw_choice: Variant = choices[index]
		var choice_ref: String = "CHOICE-%d" % (index + 1)
		var label: String = ""
		if raw_choice is Dictionary:
			var choice_dictionary: Dictionary = raw_choice
			choice_ref = str(choice_dictionary.get("choice_ref", choice_ref)).strip_edges()
			label = str(choice_dictionary.get("label", "")).strip_edges()
		else:
			label = str(raw_choice).strip_edges()
		if label.is_empty():
			clear_choices()
			return _rejected("CHOICE_LABEL_REQUIRED")
		_choice_refs.append(choice_ref)
		_choice_buttons[index].text = label
		_choice_buttons[index].visible = true
	_choice_list.visible = true
	_remaining_s = maxf(_remaining_s, MAX_DURATION_S)
	return {
		"status": "PASS",
		"visible": true,
		"choice_count": visible_count,
		"presentation": "SMALL_TEMPORARY_OPTIONS_NEAR_NPC",
		"large_modal": false,
		"next_button": false,
		"movement_lock": false,
		"authority": AUTHORITY,
	}


func clear_choices() -> void:
	_choice_refs.clear()
	for button: Button in _choice_buttons:
		button.visible = false
		button.text = ""
	_choice_list.visible = false


func hide_presentation() -> void:
	var finished_ref: String = _line_ref
	_line_active = false
	_remaining_s = 0.0
	clear_choices()
	visible = false
	if not finished_ref.is_empty():
		presentation_finished.emit(finished_ref)


func is_line_active() -> bool:
	return _line_active


func choices_visible() -> bool:
	return _choice_list.visible and not _choice_refs.is_empty()


func current_line_ref() -> String:
	return _line_ref


func current_speaker_ref() -> String:
	return _speaker_ref


func current_conversation_ref() -> String:
	return _conversation_ref


func current_turn_index() -> int:
	return _turn_index


func is_important() -> bool:
	return _important


func displayed_text() -> String:
	return _dialogue_text.text


func text_color() -> Color:
	return _dialogue_text.get_theme_color("font_color")


func anchor_screen_position() -> Vector2:
	if _anchor == null or _camera == null:
		return Vector2.ZERO
	return _camera.unproject_position(_anchor.global_position)


func contract_snapshot() -> Dictionary:
	return {
		"bubble_shape": "ROUNDED_WHITE",
		"normal_text_hex": "#6B6B6B",
		"important_text_hex": "#D9A15F",
		"next_button": false,
		"world_pause": false,
		"movement_lock": false,
		"choices_near_npc": true,
		"gameplay_authority_in_gdscript": false,
		"authority": AUTHORITY,
	}


func _on_choice_pressed(index: int) -> void:
	if index < 0 or index >= _choice_refs.size():
		return
	choice_intent_requested.emit(_npc_ref, _choice_refs[index])


func _update_projection() -> void:
	if _anchor == null or not is_instance_valid(_anchor) or _camera == null or not is_instance_valid(_camera):
		visible = false
		return
	if _camera.is_position_behind(_anchor.global_position):
		visible = false
		return
	var viewport_size: Vector2 = get_viewport_rect().size
	var projected: Vector2 = _camera.unproject_position(_anchor.global_position)
	var desired: Vector2 = projected - Vector2(size.x * 0.5, size.y + 12.0)
	desired.x = clampf(desired.x, 8.0, maxf(8.0, viewport_size.x - size.x - 8.0))
	desired.y = clampf(desired.y, 8.0, maxf(8.0, viewport_size.y - size.y - 8.0))
	position = desired
	visible = _line_active


func _reading_duration(text_value: String, important: bool) -> float:
	var base: float = float(text_value.length()) / 15.0
	if important:
		base *= 1.15
	return clampf(base, MIN_DURATION_S, MAX_DURATION_S)


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}

