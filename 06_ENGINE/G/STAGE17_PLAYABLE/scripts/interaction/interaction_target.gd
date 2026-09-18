extends Node3D
class_name AndromedaInteractionTarget

## Shared B03 presentation component for pointer targets.
## It exposes identity, hover and selection feedback, but never decides gameplay results.

signal hover_changed(target_ref: String, hovered: bool)
signal selection_changed(target_ref: String, selected: bool)

const AUTHORITY := "GODOT_INTERACTION_PRESENTATION_ONLY"

@export var target_ref: String = ""
@export var target_kind: String = "SCENE_OBJECT"
@export var display_name: String = "Placeholder"
@export var hostile: bool = false
@export var resource_kind: String = ""
@export var settled: bool = true
@export var selectable: bool = true
@export var pointer_aim_offset: Vector3 = Vector3(0.0, 0.5, 0.0)

var _hovered: bool = false
var _selected: bool = false


func _ready() -> void:
	target_kind = target_kind.strip_edges().to_upper()
	target_ref = target_ref.strip_edges()
	resource_kind = resource_kind.strip_edges().to_upper()
	_apply_feedback_text()
	_propagate_pointer_metadata(self)
	_apply_feedback_visibility()


func set_hovered(value: bool) -> void:
	if _hovered == value:
		return
	_hovered = value
	_apply_feedback_visibility()
	hover_changed.emit(target_ref, _hovered)


func is_hovered() -> bool:
	return _hovered


func set_selected(value: bool) -> void:
	if _selected == value:
		return
	_selected = value
	_apply_feedback_visibility()
	selection_changed.emit(target_ref, _selected)


func is_selected() -> bool:
	return _selected


func set_settled(value: bool) -> void:
	settled = value
	_propagate_pointer_metadata(self)


func project_external_identity(
	target_ref_value: String,
	display_name_value: String,
	hostile_value: bool,
	externally_confirmed: bool
) -> Dictionary:
	if not externally_confirmed:
		return {
			"status": "REJECTED",
			"reason": "EXTERNAL_IDENTITY_CONFIRMATION_REQUIRED",
			"authority": AUTHORITY,
		}
	var normalized_ref: String = target_ref_value.strip_edges()
	if normalized_ref.is_empty():
		return {
			"status": "REJECTED",
			"reason": "EMPTY_EXTERNAL_TARGET_REF",
			"authority": AUTHORITY,
		}
	var previous_ref: String = target_ref
	target_ref = normalized_ref
	display_name = display_name_value.strip_edges() if not display_name_value.strip_edges().is_empty() else normalized_ref
	hostile = hostile_value
	_apply_feedback_text()
	_propagate_pointer_metadata(self)
	return {
		"status": "PASS",
		"previous_target_ref": previous_ref,
		"target_ref": target_ref,
		"hostile": hostile,
		"gameplay_identity_decided_locally": false,
		"authority": AUTHORITY,
	}


func pointer_world_position() -> Vector3:
	return global_position + pointer_aim_offset


func hover_cursor() -> String:
	if target_kind == AndromedaInputRouter.HIT_GROUND_LOOT:
		return "PICKUP" if settled else "BLOCKED"
	if target_kind == AndromedaInputRouter.HIT_DROPPED_BAG:
		return "RECOVER" if selectable else "BLOCKED"
	if hostile and target_kind == AndromedaInputRouter.HIT_ACTOR:
		return "ATTACK"
	if target_kind == AndromedaInputRouter.HIT_NPC:
		return "TALK"
	if target_kind == AndromedaInputRouter.HIT_GATHER_NODE:
		return "HARVEST"
	return "INTERACT"


func interaction_snapshot() -> Dictionary:
	var root_collision_layer: int = int(get("collision_layer"))
	return {
		"target_ref": target_ref,
		"target_kind": target_kind,
		"display_name": display_name,
		"hostile": hostile,
		"resource_kind": resource_kind,
		"settled": settled,
		"selectable": selectable,
		"hovered": _hovered,
		"selected": _selected,
		"collision_layer": root_collision_layer,
		"authority": AUTHORITY,
	}


func _propagate_pointer_metadata(node: Node) -> void:
	if node is CollisionObject3D:
		var collision_object := node as CollisionObject3D
		collision_object.set_meta("pointer_kind", target_kind)
		collision_object.set_meta("target_ref", target_ref)
		collision_object.set_meta("hostile", hostile)
		collision_object.set_meta("resource_kind", resource_kind)
		collision_object.set_meta("ground_loot_settled", settled)
		collision_object.set_meta("selectable", selectable)
		collision_object.set_meta("target_owner_instance_id", get_instance_id())
	for child: Node in node.get_children():
		_propagate_pointer_metadata(child)


func _apply_feedback_text() -> void:
	var hover_name := get_node_or_null("HoverFeedback/HoverName") as Label3D
	if hover_name != null:
		hover_name.text = display_name
	var hover_hint := get_node_or_null("HoverFeedback/HoverHint") as Label3D
	if hover_hint != null:
		hover_hint.text = hover_cursor()


func _apply_feedback_visibility() -> void:
	var hover_name := get_node_or_null("HoverFeedback/HoverName") as Label3D
	if hover_name != null:
		hover_name.visible = _hovered and target_kind == AndromedaInputRouter.HIT_NPC
	var hover_hint := get_node_or_null("HoverFeedback/HoverHint") as Label3D
	if hover_hint != null:
		hover_hint.visible = _hovered and target_kind != AndromedaInputRouter.HIT_NPC
	var selection_indicator := get_node_or_null("HoverFeedback/SelectionIndicator") as MeshInstance3D
	if selection_indicator != null:
		selection_indicator.visible = _selected
