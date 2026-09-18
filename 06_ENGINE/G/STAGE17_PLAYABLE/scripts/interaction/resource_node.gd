extends AndromedaInteractionTarget
class_name AndromedaResourceNode

## B08 resource-node presentation component.
## Availability, depletion and replenishment arrive from Stage16A/Living authority.
## This node only exposes stable identity, anchors, pointer feedback and streamed visuals.

signal authoritative_state_projected(result: Dictionary)
signal stream_phase_projected(result: Dictionary)
signal resource_feedback_presented(result: Dictionary)

const RESOURCE_KINDS: Array[String] = ["TREE", "ROCK", "ORE", "FLORA", "AGRICULTURE"]
const STATE_UNCONFIRMED := "UNCONFIRMED"
const STATE_AVAILABLE := "AVAILABLE"
const STATE_IN_PROGRESS := "IN_PROGRESS"
const STATE_UNAVAILABLE := "UNAVAILABLE"
const STATE_REMOVED := "REMOVED"
const STREAM_ACTIVE := "ACTIVE"
const STREAM_PRELOAD := "PRELOAD"
const STREAM_SYSTEMIC := "SYSTEMIC"
const BODY_LAYER_RESOURCE_NODE := 32
const SENSOR_LAYER_INTERACTABLE := 8
const VALID_FEEDBACK: Array[String] = [
	"GATHER_REQUESTED",
	"GATHER_ACCEPTED",
	"GATHER_REJECTED",
	"RESOURCE_UNAVAILABLE",
	"OUTPUT_PRODUCED",
	"INTERACTION_BLOCKED",
]

@export_range(0.25, 4.0, 0.05) var interaction_range_m: float = 1.25

@onready var visual_root: Node3D = $VisualRoot
@onready var placeholder_visual: MeshInstance3D = $VisualRoot/PlaceholderMesh
@onready var interaction_sensor: Area3D = $InteractionSensor
@onready var drop_anchor: Marker3D = $DropAnchor
@onready var hover_hint: Label3D = $HoverFeedback/HoverHint

var _projected_state: String = STATE_UNCONFIRMED
var _state_session_ref: String = ""
var _last_state_sequence: int = -1
var _stream_phase: String = STREAM_ACTIVE
var _stream_session_ref: String = ""
var _last_stream_sequence: int = -1
var _latest_feedback: String = ""
var placement_ref: String = ""
var logical_node_ref: String = ""
var position_authority: String = ""
var placement_revision: String = ""
var source_manifest_hash: String = ""


func _ready() -> void:
	target_kind = AndromedaInputRouter.HIT_GATHER_NODE
	super._ready()
	_apply_stream_presentation()
	_refresh_resource_hint()


func hover_cursor() -> String:
	if _projected_state == STATE_UNAVAILABLE:
		return "UNAVAILABLE"
	if _projected_state == STATE_IN_PROGRESS:
		return "IN PROGRESS"
	if _stream_phase != STREAM_ACTIVE:
		return "STREAMED"
	return "HARVEST"


func apply_metric_identity_projection(entry: Dictionary, externally_confirmed: bool = false) -> Dictionary:
	## The authored transform is only an offline source. Runtime identity and
	## position are accepted exclusively from the server placement projection;
	## InteractionSpatialBindingRegistry applies the mapped position separately.
	if not externally_confirmed or entry.get("server_authoritative") != true:
		return _rejected("EXTERNAL_RESOURCE_PLACEMENT_CONFIRMATION_REQUIRED")
	var projected_placement_ref: String = str(entry.get("placement_ref", entry.get("target_ref", ""))).strip_edges()
	var projected_target_ref: String = str(entry.get("target_ref", "")).strip_edges()
	var projected_logical_ref: String = str(entry.get("logical_node_ref", "")).strip_edges()
	var projected_position_authority: String = str(entry.get("position_authority", "")).strip_edges()
	if projected_placement_ref.is_empty() or projected_target_ref != projected_placement_ref:
		return _rejected("RESOURCE_PHYSICAL_PLACEMENT_IDENTITY_REQUIRED")
	if not projected_logical_ref.begins_with("GTH-"):
		return _rejected("RESOURCE_LOGICAL_GTH_IDENTITY_REQUIRED")
	if projected_position_authority.is_empty() or projected_position_authority == "GODOT_LOCAL_PLACEHOLDER_ONLY":
		return _rejected("RESOURCE_METRIC_POSITION_AUTHORITY_REQUIRED")
	var projected_kind: String = str(entry.get("resource_kind", "")).strip_edges().to_upper()
	if projected_kind not in RESOURCE_KINDS:
		return _rejected("RESOURCE_KIND_MISMATCH")
	var range_value: Variant = entry.get("gather_range_m", interaction_range_m)
	if typeof(range_value) not in [TYPE_INT, TYPE_FLOAT] or not is_finite(float(range_value)) or float(range_value) <= 0.0:
		return _rejected("INVALID_PROJECTED_GATHER_RANGE")
	placement_ref = projected_placement_ref
	logical_node_ref = projected_logical_ref
	target_ref = projected_placement_ref
	resource_kind = projected_kind
	position_authority = projected_position_authority
	placement_revision = str(entry.get("placement_revision", "")).strip_edges()
	source_manifest_hash = str(entry.get("source_manifest_hash", "")).strip_edges()
	interaction_range_m = float(range_value)
	set_meta("resource_placement_ref", placement_ref)
	set_meta("resource_logical_node_ref", logical_node_ref)
	set_meta("resource_position_authority", position_authority)
	set_meta("scene_transform_is_initial_presentation_only", true)
	_propagate_pointer_metadata(self)
	return {
		"status": "PASS",
		"target_ref": target_ref,
		"placement_ref": placement_ref,
		"logical_node_ref": logical_node_ref,
		"resource_kind": resource_kind,
		"position_authority": position_authority,
		"placement_revision": placement_revision,
		"scene_transform_is_authority": false,
		"authority": AUTHORITY,
	}


func apply_authoritative_projection(
	entry: Dictionary,
	session_ref_value: String,
	sequence: int,
	externally_confirmed: bool = false
) -> Dictionary:
	if not externally_confirmed or entry.get("server_authoritative", true) != true:
		return _rejected("EXTERNAL_RESOURCE_STATE_CONFIRMATION_REQUIRED")
	var normalized_session: String = session_ref_value.strip_edges()
	if normalized_session.is_empty():
		return _rejected("EMPTY_RESOURCE_STATE_SESSION")
	if not _state_session_ref.is_empty() and normalized_session != _state_session_ref:
		return _rejected("RESOURCE_STATE_SESSION_MISMATCH")
	if sequence < 0:
		return _rejected("INVALID_RESOURCE_STATE_SEQUENCE")
	if sequence <= _last_state_sequence:
		return _rejected("STALE_OR_DUPLICATE_RESOURCE_STATE")
	var projected_ref: String = str(entry.get("target_ref", "")).strip_edges()
	if projected_ref != target_ref:
		return _rejected("RESOURCE_TARGET_REF_MISMATCH")
	var projected_kind: String = str(entry.get("resource_kind", resource_kind)).strip_edges().to_upper()
	if projected_kind != resource_kind or projected_kind not in RESOURCE_KINDS:
		return _rejected("RESOURCE_KIND_MISMATCH")
	var normalized_state: String = _normalize_state(str(entry.get("state", "")))
	if normalized_state.is_empty():
		return _rejected("UNSUPPORTED_RESOURCE_STATE")
	_projected_state = normalized_state
	_state_session_ref = normalized_session
	_last_state_sequence = sequence
	selectable = _projected_state != STATE_REMOVED and _stream_phase == STREAM_ACTIVE
	_propagate_pointer_metadata(self)
	_refresh_resource_hint()
	var result := {
		"status": "PASS",
		"target_ref": target_ref,
		"resource_kind": resource_kind,
		"projected_state": _projected_state,
		"state_sequence": _last_state_sequence,
		"state_changed_by_gdscript": false,
		"depletion_decided_locally": false,
		"respawn_timer_created": false,
		"authority": AUTHORITY,
	}
	authoritative_state_projected.emit(result.duplicate(true))
	return result


func project_stream_phase(
	next_phase: String,
	session_ref_value: String,
	sequence: int,
	externally_confirmed: bool = false
) -> Dictionary:
	if not externally_confirmed:
		return _rejected("EXTERNAL_STREAM_PHASE_CONFIRMATION_REQUIRED")
	var normalized_phase: String = next_phase.strip_edges().to_upper()
	if normalized_phase not in [STREAM_ACTIVE, STREAM_PRELOAD, STREAM_SYSTEMIC]:
		return _rejected("UNSUPPORTED_RESOURCE_STREAM_PHASE")
	var normalized_session: String = session_ref_value.strip_edges()
	if normalized_session.is_empty():
		return _rejected("EMPTY_RESOURCE_STREAM_SESSION")
	if not _stream_session_ref.is_empty() and normalized_session != _stream_session_ref:
		return _rejected("RESOURCE_STREAM_SESSION_MISMATCH")
	if sequence < 0:
		return _rejected("INVALID_RESOURCE_STREAM_SEQUENCE")
	if sequence <= _last_stream_sequence:
		return _rejected("STALE_OR_DUPLICATE_RESOURCE_STREAM_PHASE")
	_stream_phase = normalized_phase
	_stream_session_ref = normalized_session
	_last_stream_sequence = sequence
	selectable = _stream_phase == STREAM_ACTIVE and _projected_state != STATE_REMOVED
	_apply_stream_presentation()
	_propagate_pointer_metadata(self)
	_refresh_resource_hint()
	var result := {
		"status": "PASS",
		"target_ref": target_ref,
		"stream_phase": _stream_phase,
		"stream_sequence": _last_stream_sequence,
		"detailed_resource_materialized": _stream_phase == STREAM_ACTIVE,
		"living_state_duplicated": false,
		"authority": AUTHORITY,
	}
	stream_phase_projected.emit(result.duplicate(true))
	return result


func can_prepare_gather_intent() -> Dictionary:
	if _stream_phase != STREAM_ACTIVE:
		return _rejected("RESOURCE_NOT_ACTIVE_IN_STREAM")
	if _projected_state == STATE_UNCONFIRMED:
		return _rejected("RESOURCE_STATE_NOT_PROJECTED")
	if _projected_state == STATE_IN_PROGRESS:
		return _rejected("RESOURCE_BUSY")
	if _projected_state in [STATE_UNAVAILABLE, STATE_REMOVED]:
		return _rejected("RESOURCE_UNAVAILABLE")
	return {
		"status": "PASS",
		"target_ref": target_ref,
		"resource_kind": resource_kind,
		"projected_state": _projected_state,
		"authority": AUTHORITY,
	}


func interaction_anchor_world_position() -> Vector3:
	return global_position


func drop_anchor_world_position() -> Vector3:
	return drop_anchor.global_position if drop_anchor != null else global_position


func projected_state() -> String:
	return _projected_state


func state_is_known() -> bool:
	return _projected_state != STATE_UNCONFIRMED


func stream_phase() -> String:
	return _stream_phase


func last_state_sequence() -> int:
	return _last_state_sequence


func last_stream_sequence() -> int:
	return _last_stream_sequence


func reset_client_projection_cache() -> Dictionary:
	_projected_state = STATE_UNCONFIRMED
	_state_session_ref = ""
	_last_state_sequence = -1
	_stream_phase = STREAM_ACTIVE
	_stream_session_ref = ""
	_last_stream_sequence = -1
	_latest_feedback = ""
	selectable = true
	_apply_stream_presentation()
	_propagate_pointer_metadata(self)
	_refresh_resource_hint()
	return {
		"status": "PASS",
		"target_ref": target_ref,
		"authoritative_state_fabricated": false,
		"authority": AUTHORITY,
	}


func present_client_feedback(token_value: String, externally_confirmed: bool = false) -> Dictionary:
	var token: String = token_value.strip_edges().to_upper()
	if token not in VALID_FEEDBACK:
		return _rejected("UNSUPPORTED_RESOURCE_FEEDBACK")
	if token in ["GATHER_ACCEPTED", "GATHER_REJECTED", "OUTPUT_PRODUCED"] and not externally_confirmed:
		return _rejected("EXTERNAL_GATHERING_FEEDBACK_CONFIRMATION_REQUIRED")
	_latest_feedback = token
	_refresh_resource_hint()
	var result := {
		"status": "PASS",
		"token": token,
		"target_ref": target_ref,
		"gameplay_result_changed": false,
		"authority": AUTHORITY,
	}
	resource_feedback_presented.emit(result.duplicate(true))
	return result


func presentation_snapshot() -> Dictionary:
	return {
		"target_ref": target_ref,
		"placement_ref": placement_ref,
		"logical_node_ref": logical_node_ref,
		"target_kind": target_kind,
		"resource_kind": resource_kind,
		"projected_state": _projected_state,
		"state_known": state_is_known(),
		"state_session_ref": _state_session_ref,
		"state_sequence": _last_state_sequence,
		"stream_phase": _stream_phase,
		"stream_sequence": _last_stream_sequence,
		"interaction_range_m": interaction_range_m,
		"position_authority": position_authority,
		"placement_revision": placement_revision,
		"source_manifest_hash": source_manifest_hash,
		"scene_transform_is_authority": false,
		"drop_anchor_world_position": drop_anchor_world_position(),
		"detailed_resource_materialized": _stream_phase == STREAM_ACTIVE,
		"reduced_preload_representation": _stream_phase == STREAM_PRELOAD,
		"systemic_reference_only": _stream_phase == STREAM_SYSTEMIC,
		"latest_feedback": _latest_feedback,
		"yield_authority": false,
		"tool_rule_authority": false,
		"stamina_authority": false,
		"depletion_authority": false,
		"respawn_authority": false,
		"inventory_authority": false,
		"authority": AUTHORITY,
	}


func contract_snapshot() -> Dictionary:
	return {
		"root_type": "StaticBody3D",
		"required_children": ["CollisionShape3D", "VisualRoot", "InteractionSensor", "DropAnchor"],
		"resource_kinds": RESOURCE_KINDS.duplicate(),
		"resource_collision_layer": BODY_LAYER_RESOURCE_NODE,
		"interaction_sensor_layer": SENSOR_LAYER_INTERACTABLE,
		"state_source": "EXTERNAL_STAGE16A_LIVING_PROJECTION_ONLY",
		"stream_states": [STREAM_ACTIVE, STREAM_PRELOAD, STREAM_SYSTEMIC],
		"local_respawn_timer": false,
		"local_yield_calculation": false,
		"local_tool_validation": false,
		"local_stamina_mutation": false,
		"local_depletion_decision": false,
		"local_inventory_grant": false,
		"physical_placement_identity_separate_from_logical_gth": true,
		"runtime_node_transform_is_authority": false,
		"authority": AUTHORITY,
	}


func _normalize_state(value: String) -> String:
	match value.strip_edges().to_upper():
		"ACTIVE", "AVAILABLE":
			return STATE_AVAILABLE
		"BUSY", "IN_PROGRESS":
			return STATE_IN_PROGRESS
		"DEPLETED", "UNAVAILABLE":
			return STATE_UNAVAILABLE
		"REMOVED":
			return STATE_REMOVED
		_:
			return ""


func _apply_stream_presentation() -> void:
	if not is_node_ready():
		return
	visual_root.visible = _stream_phase != STREAM_SYSTEMIC
	placeholder_visual.transparency = 0.55 if _stream_phase == STREAM_PRELOAD else 0.0
	set("collision_layer", BODY_LAYER_RESOURCE_NODE if _stream_phase != STREAM_SYSTEMIC else 0)
	interaction_sensor.collision_layer = SENSOR_LAYER_INTERACTABLE if _stream_phase == STREAM_ACTIVE else 0
	set_meta("b08_detailed_resource_materialized", _stream_phase == STREAM_ACTIVE)
	set_meta("b08_systemic_reference_only", _stream_phase == STREAM_SYSTEMIC)


func _refresh_resource_hint() -> void:
	if not is_node_ready():
		return
	var text_value: String = hover_cursor()
	if not _latest_feedback.is_empty():
		text_value = {
			"GATHER_REQUESTED": "GATHERING…",
			"GATHER_ACCEPTED": "GATHERING",
			"GATHER_REJECTED": "BLOCKED",
			"RESOURCE_UNAVAILABLE": "UNAVAILABLE",
			"OUTPUT_PRODUCED": "OUTPUT",
			"INTERACTION_BLOCKED": "BLOCKED",
		}.get(_latest_feedback, text_value)
	hover_hint.text = text_value
	hover_hint.modulate = Color("d9a15f") if _latest_feedback in ["OUTPUT_PRODUCED", "GATHER_ACCEPTED"] else Color("e9d9bd")


func _rejected(reason: String, detail: Dictionary = {}) -> Dictionary:
	var result := {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
	result.merge(detail, true)
	return result
