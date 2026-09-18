extends PanelContainer
class_name AndromedaDeathRecoveryOverlay

## Compact B10 status surface. It presents client pending state or externally-confirmed
## save/death/recovery/respawn state and never resolves gameplay outcomes.

const AUTHORITY := "GODOT_B10_STATUS_PRESENTATION_ONLY"
const EXTERNAL_STATES: Array[String] = [
	"SAVE_CONFIRMED",
	"SAVE_FAILED",
	"RESTORED",
	"DEFEATED",
	"DEAD_AWAITING_RESPAWN",
	"BAG_RECOVERY_ACCEPTED",
	"BAG_RECOVERY_REJECTED",
	"RESPAWNED",
	"WATER_EXHAUSTION",
]
const CLIENT_PENDING_STATES: Array[String] = [
	"SAVE_PENDING",
	"AUTOSAVE_PENDING",
	"RELOAD_PENDING",
	"RESYNC_REQUIRED",
	"RESPAWN_PENDING",
	"BAG_RECOVERY_PENDING",
]

@onready var _state_label: Label = $Margin/Layout/State
@onready var _detail_label: Label = $Margin/Layout/Detail

var _state: String = "HIDDEN"
var _externally_confirmed: bool = false
var _projection: Dictionary = {}


func _ready() -> void:
	visible = false
	mouse_filter = Control.MOUSE_FILTER_IGNORE


func present_client_pending(state_value: String, detail: String) -> Dictionary:
	var state: String = state_value.strip_edges().to_upper()
	if state not in CLIENT_PENDING_STATES:
		return _rejected("INVALID_CLIENT_PENDING_STATE")
	_state = state
	_externally_confirmed = false
	_projection = {
		"state": state,
		"detail": detail,
		"externally_confirmed": false,
	}
	_render(false)
	return _result()


func project_external_state(state_value: String, detail: String, important: bool = false) -> Dictionary:
	var state: String = state_value.strip_edges().to_upper()
	if state not in EXTERNAL_STATES:
		return _rejected("INVALID_EXTERNAL_B10_UI_STATE")
	_state = state
	_externally_confirmed = true
	_projection = {
		"state": state,
		"detail": detail,
		"externally_confirmed": true,
		"important": important,
	}
	_render(important)
	return _result()


func hide_presentation() -> Dictionary:
	_state = "HIDDEN"
	_externally_confirmed = false
	_projection.clear()
	visible = false
	return _result()


func presentation_state() -> String:
	return _state


func projection() -> Dictionary:
	return _projection.duplicate(true)


func contract_snapshot() -> Dictionary:
	return {
		"ui_family": "WHITE_OFF_WHITE_ROUNDED_CLEAN",
		"world_first": true,
		"large_permanent_panel": false,
		"scene_tree_pause": false,
		"save_authority": false,
		"death_authority": false,
		"recovery_authority": false,
		"respawn_authority": false,
		"ttl_authority": false,
		"final_art": false,
		"authority": AUTHORITY,
	}


func _render(important: bool) -> void:
	_state_label.text = _state.replace("_", " ").capitalize()
	_detail_label.text = str(_projection.get("detail", ""))
	_state_label.add_theme_color_override("font_color", Color("d9a15f") if important else Color("6b6b6b"))
	_detail_label.add_theme_color_override("font_color", Color("808080"))
	visible = true


func _result() -> Dictionary:
	return {
		"status": "PASS",
		"state": _state,
		"visible": visible,
		"externally_confirmed": _externally_confirmed,
		"gameplay_state_mutated": false,
		"authority": AUTHORITY,
	}


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
