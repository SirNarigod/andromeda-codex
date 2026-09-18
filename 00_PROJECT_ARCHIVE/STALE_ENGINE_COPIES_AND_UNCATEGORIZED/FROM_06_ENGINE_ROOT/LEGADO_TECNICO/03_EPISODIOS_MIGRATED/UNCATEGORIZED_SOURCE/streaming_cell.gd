extends Node3D
class_name AndromedaStreamingCell

const STATE_ACTIVE := "ACTIVE"
const STATE_PRELOAD := "PRELOAD"
const AUTHORITY := "GODOT_CELL_SCENE_PRESENTATION_ONLY"

@export var cell_ref: String = "CELL-B04-UNASSIGNED"
@export var living_macro_ref: String = "LIVING-MACRO-UNASSIGNED"

@onready var detailed_visual: Node3D = $DetailedVisual
@onready var reduced_visual: Node3D = $ReducedVisual
@onready var collision_proxy: Node3D = $CollisionProxy
@onready var traversal_proxy: Node3D = $TraversalProxy

var _state: String = STATE_PRELOAD


func configure(next_cell_ref: String, next_living_macro_ref: String, next_state: String) -> void:
	cell_ref = next_cell_ref
	living_macro_ref = next_living_macro_ref
	set_stream_state(next_state)


func set_stream_state(next_state: String) -> void:
	assert(next_state in [STATE_ACTIVE, STATE_PRELOAD])
	_state = next_state
	if not is_node_ready():
		return
	detailed_visual.visible = _state == STATE_ACTIVE
	reduced_visual.visible = _state == STATE_PRELOAD
	collision_proxy.set_meta("loaded", true)
	traversal_proxy.set_meta("loaded", true)
	set_meta("stream_state", _state)


func stream_state() -> String:
	return _state


func snapshot() -> Dictionary:
	return {
		"cell_ref": cell_ref,
		"state": _state,
		"living_macro_ref": living_macro_ref,
		"detailed_visual_loaded": detailed_visual.visible,
		"reduced_visual_loaded": reduced_visual.visible,
		"collision_proxy_loaded": bool(collision_proxy.get_meta("loaded", false)),
		"traversal_proxy_loaded": bool(traversal_proxy.get_meta("loaded", false)),
		"living_simulation_duplicated": false,
		"authority": AUTHORITY,
	}


func _ready() -> void:
	set_stream_state(_state)
