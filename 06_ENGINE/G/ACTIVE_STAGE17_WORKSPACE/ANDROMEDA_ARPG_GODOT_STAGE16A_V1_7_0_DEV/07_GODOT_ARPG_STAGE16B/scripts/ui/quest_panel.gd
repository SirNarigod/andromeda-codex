extends Control
class_name AndromedaQuestPanel

## B09 quest presentation. Offers, objectives, completion and rewards are projected
## from external state; this panel only emits player intent.

signal quest_accept_requested(quest_ref: String)
signal quest_choice_requested(quest_ref: String, choice_ref: String)
signal close_requested()

const AUTHORITY := "GODOT_QUEST_UI_PRESENTATION_ONLY"
const SCROLL_STEP_PX := 64

@onready var _scroll: ScrollContainer = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll
@onready var _title: Label = $Backdrop/RoundedWhitePanel/Margin/Layout/Title
@onready var _state: Label = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/State
@onready var _objectives: VBoxContainer = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/Objectives
@onready var _accept: Button = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/Accept
@onready var _choices: VBoxContainer = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/Choices
@onready var _close: Button = $Backdrop/RoundedWhitePanel/Margin/Layout/Header/Close

var _quest_ref: String = ""
var _offer: Dictionary = {}
var _quest_projection: Dictionary = {}


func _ready() -> void:
	_accept.pressed.connect(_on_accept_pressed)
	_close.pressed.connect(_on_close_pressed)
	set_open(false)


func set_open(value: bool) -> void:
	visible = value
	mouse_filter = Control.MOUSE_FILTER_STOP if value else Control.MOUSE_FILTER_IGNORE


func is_open() -> bool:
	return visible


func project_offer(offer: Dictionary, externally_validated: bool) -> Dictionary:
	if not externally_validated:
		return _rejected("EXTERNAL_QUEST_OFFER_VALIDATION_REQUIRED")
	_offer = offer.duplicate(true)
	_quest_ref = str(_offer.get("quest_ref", "")).strip_edges()
	_title.text = str(_offer.get("title", _quest_ref))
	_state.text = "Oferta recebida externamente"
	_accept.visible = true
	_rebuild_objectives(_offer.get("objectives", []))
	_rebuild_choices(_offer.get("choices", []))
	set_open(true)
	return {
		"status": "PASS",
		"quest_ref": _quest_ref,
		"accepted_locally": false,
		"completed_locally": false,
		"authority": AUTHORITY,
	}


func project_quest_state(projection: Dictionary, externally_validated: bool) -> Dictionary:
	if not externally_validated:
		return _rejected("EXTERNAL_QUEST_STATE_VALIDATION_REQUIRED")
	_quest_projection = projection.duplicate(true)
	_quest_ref = str(_quest_projection.get("quest_ref", "")).strip_edges()
	_title.text = str(_quest_projection.get("title", _quest_ref))
	_state.text = "Estado  ·  %s" % str(_quest_projection.get("state", "UNKNOWN"))
	_accept.visible = false
	_rebuild_objectives(_quest_projection.get("objectives", []))
	_rebuild_choices(_quest_projection.get("choices", []))
	set_open(true)
	return {
		"status": "PASS",
		"quest_ref": _quest_ref,
		"state": str(_quest_projection.get("state", "")),
		"objective_completion_decided_locally": false,
		"quest_completion_decided_locally": false,
		"reward_granted_locally": false,
		"authority": AUTHORITY,
	}


func present_external_event(event: Dictionary, externally_validated: bool) -> Dictionary:
	if not externally_validated:
		return _rejected("EXTERNAL_QUEST_EVENT_VALIDATION_REQUIRED")
	_state.text = str(event.get("feedback_text", "Atualização de quest recebida."))
	return {
		"status": "PASS",
		"event_ref": str(event.get("event_ref", "")),
		"local_progress_changed": false,
		"local_reward_granted": false,
		"authority": AUTHORITY,
	}


func scroll_by(direction: int) -> Dictionary:
	if not visible:
		return _rejected("QUEST_MENU_CLOSED")
	if direction == 0:
		return _rejected("ZERO_SCROLL_DIRECTION")
	var before: int = _scroll.scroll_vertical
	var scrollbar: VScrollBar = _scroll.get_v_scroll_bar()
	var maximum: int = maxi(0, int(round(scrollbar.max_value - scrollbar.page)))
	_scroll.scroll_vertical = clampi(before + direction * SCROLL_STEP_PX, 0, maximum)
	return {
		"status": "PASS",
		"before": before,
		"after": _scroll.scroll_vertical,
		"weapon_slot_changed": false,
		"camera_zoom_changed": false,
		"authority": AUTHORITY,
	}


func current_quest_ref() -> String:
	return _quest_ref


func projected_offer() -> Dictionary:
	return _offer.duplicate(true)


func projected_quest_state() -> Dictionary:
	return _quest_projection.duplicate(true)


func contract_snapshot() -> Dictionary:
	return {
		"realtime_world_first": true,
		"next_button": false,
		"offer_authority": false,
		"objective_authority": false,
		"completion_authority": false,
		"reward_authority": false,
		"xp_authority": false,
		"local_kill_counting": false,
		"local_pickup_counting": false,
		"ui_family": "WHITE_OFF_WHITE_ROUNDED_CLEAN_CONSOLE",
		"permanent_panel": false,
		"final_art": false,
		"authority": AUTHORITY,
	}


func _rebuild_objectives(value: Variant) -> void:
	for child: Node in _objectives.get_children():
		child.queue_free()
	if not value is Array:
		return
	for objective_value: Variant in value:
		if not objective_value is Dictionary:
			continue
		var objective: Dictionary = objective_value
		var label := Label.new()
		label.text = "• %s  ·  %s" % [
			str(objective.get("text", objective.get("objective_ref", "Objetivo"))),
			str(objective.get("state", "PENDING")),
		]
		label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		_objectives.add_child(label)


func _rebuild_choices(value: Variant) -> void:
	for child: Node in _choices.get_children():
		child.queue_free()
	if not value is Array:
		return
	for choice_value: Variant in value:
		if not choice_value is Dictionary:
			continue
		var choice: Dictionary = choice_value
		var choice_ref: String = str(choice.get("choice_ref", "")).strip_edges()
		if choice_ref.is_empty():
			continue
		var button := Button.new()
		button.text = str(choice.get("label", choice_ref))
		button.pressed.connect(_on_choice_pressed.bind(choice_ref))
		_choices.add_child(button)


func _on_accept_pressed() -> void:
	if not _quest_ref.is_empty():
		quest_accept_requested.emit(_quest_ref)


func _on_choice_pressed(choice_ref: String) -> void:
	if not _quest_ref.is_empty():
		quest_choice_requested.emit(_quest_ref, choice_ref)


func _on_close_pressed() -> void:
	close_requested.emit()


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
