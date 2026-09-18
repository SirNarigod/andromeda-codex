extends Control
class_name AndromedaConnectionHud

## Minimal, always-legible status readout: connection state + basic controls
## hint. Replaces the old scattered UI with one clear top-left panel.

@onready var _status_label: Label = $Panel/VBoxContainer/StatusLabel
@onready var _hint_label: Label = $Panel/VBoxContainer/HintLabel


func _ready() -> void:
	_hint_label.text = "WASD move | Space jump | Shift dodge | C climb | V swim | Wheel zoom | I inventory | E interact"
	var bridge: AndromedaRuntimeBridge = get_node_or_null("/root/AndromedaBridge")
	if bridge != null:
		bridge.connection_state_changed.connect(_on_connection_state_changed)
		var state: Dictionary = bridge.connection_state()
		_on_connection_state_changed(state.get("state", "UNKNOWN"), "")


func _on_connection_state_changed(state: String, _detail: String) -> void:
	_status_label.text = "Backend: %s" % state
	match state:
		"CONNECTED", "BOUND":
			_status_label.modulate = Color(0.55, 0.9, 0.55)
		"CONNECTING", "RECONNECTING":
			_status_label.modulate = Color(0.95, 0.85, 0.45)
		_:
			_status_label.modulate = Color(0.95, 0.5, 0.5)
