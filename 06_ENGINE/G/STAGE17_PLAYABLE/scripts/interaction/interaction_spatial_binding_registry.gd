extends Node
class_name AndromedaInteractionSpatialBindingRegistry

## Stage17 ref -> spatial presentation binding.
##
## The Python projection is the only source of target identity and territorial
## position.  The AuthoritySpaceMapper is the only coordinate converter.  A
## Node3D is a presentation sink: this registry may place it, but never reads its
## transform to manufacture an authority position or a gameplay distance.

signal target_bound(evidence: Dictionary)
signal target_invalidated(evidence: Dictionary)

const AUTHORITY := "STAGE17_INTERACTION_SPATIAL_BINDING_PRESENTATION_ONLY"

var _mapper: AndromedaAuthoritySpaceMapper
var _bindings: Dictionary = {}
var _last_sequence_by_ref: Dictionary = {}
var _world_instance_id: String = ""
var _session_ref: String = ""
var _metrics := {
	"projection_updates": 0,
	"stale_projections_ignored": 0,
	"target_invalidations": 0,
	"world_invalidations": 0,
	"session_invalidations": 0,
}


func bind_runtime(mapper_value: AndromedaAuthoritySpaceMapper) -> Dictionary:
	if mapper_value == null:
		return _rejected("AUTHORITY_SPACE_MAPPER_REQUIRED")
	_mapper = mapper_value
	var session := _session()
	if session != null:
		if not session.session_revoked.is_connected(_on_session_revoked):
			session.session_revoked.connect(_on_session_revoked)
	var bridge := _bridge()
	if bridge != null:
		if not bridge.connection_state_changed.is_connected(_on_connection_state_changed):
			bridge.connection_state_changed.connect(_on_connection_state_changed)
	return {
		"status": "PASS",
		"authority_position_source": "SERVER_AUTHORITATIVE_PROJECTION_ONLY",
		"presentation_node_is_authority_source": false,
		"gameplay_distance_authority": false,
		"authority": AUTHORITY,
	}


func project_target(
	snapshot: Dictionary,
	entry: Dictionary,
	presentation_node: AndromedaInteractionTarget,
	required_target_kind: String
) -> Dictionary:
	var envelope: Dictionary = _validate_snapshot_envelope(snapshot)
	if envelope.get("status") != "PASS":
		return envelope
	var world_instance_id: String = str(envelope.get("world_instance_id"))
	var session_ref_value: String = str(envelope.get("session_ref"))
	var sequence: int = int(envelope.get("snapshot_sequence"))
	if not _world_instance_id.is_empty() and world_instance_id != _world_instance_id:
		var previous_world: String = _world_instance_id
		invalidate_all("WORLD_INSTANCE_CHANGED", true)
		_metrics["world_invalidations"] = int(_metrics["world_invalidations"]) + 1
		return _rejected("WORLD_INSTANCE_CHANGED_REQUIRES_FRESH_MAPPER_ANCHOR", {
			"previous_world_instance_id": previous_world,
			"snapshot_world_instance_id": world_instance_id,
		})
	if not _session_ref.is_empty() and session_ref_value != _session_ref:
		invalidate_all("SESSION_CHANGED_AWAITING_FRESH_PROJECTION", true)
		_metrics["session_invalidations"] = int(_metrics["session_invalidations"]) + 1
	if _mapper == null or not _mapper.is_anchored():
		return _rejected("AUTHORITY_SPACE_MAPPER_NOT_READY")
	var mapper_contract: Dictionary = _mapper.contract_snapshot()
	if str(mapper_contract.get("world_instance_id", "")) != world_instance_id:
		return _rejected("MAPPER_WORLD_INSTANCE_MISMATCH")
	var target_ref: String = str(entry.get("target_ref", "")).strip_edges()
	var target_kind: String = str(entry.get("target_kind", "")).strip_edges().to_upper()
	var expected_kind: String = required_target_kind.strip_edges().to_upper()
	if target_ref.is_empty():
		return _rejected("TARGET_REF_REQUIRED")
	if target_kind.is_empty() or target_kind != expected_kind:
		return _rejected("TARGET_KIND_MISMATCH")
	if entry.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_TARGET_PROJECTION")
	var position_authority: String = str(entry.get("position_authority", "")).strip_edges()
	if position_authority.is_empty() or position_authority == "GODOT_LOCAL_PLACEHOLDER_ONLY":
		return _rejected("AUTHORITATIVE_TARGET_POSITION_SOURCE_REQUIRED")
	var authority_position_value: Variant = entry.get("position")
	if not authority_position_value is Dictionary:
		return _rejected("TARGET_AUTHORITY_POSITION_REQUIRED")
	var authority_position: Dictionary = authority_position_value
	if not _valid_authority_position(authority_position):
		return _rejected("INVALID_TARGET_AUTHORITY_POSITION")
	if presentation_node == null or not is_instance_valid(presentation_node):
		return _rejected("PRESENTATION_NODE_REQUIRED")
	if presentation_node.target_ref != target_ref:
		return _rejected("PRESENTATION_NODE_TARGET_REF_MISMATCH")
	var previous_sequence: int = int(_last_sequence_by_ref.get(target_ref, -1))
	if sequence <= previous_sequence:
		_metrics["stale_projections_ignored"] = int(_metrics["stale_projections_ignored"]) + 1
		return _rejected("STALE_OR_DUPLICATE_TARGET_POSITION_PROJECTION", {
			"target_ref": target_ref,
			"snapshot_sequence": sequence,
			"previous_sequence": previous_sequence,
		})
	var mapped: Dictionary = _mapper.authority_to_local(authority_position)
	if mapped.get("status") != "PASS":
		return _rejected("TARGET_AUTHORITY_TO_LOCAL_MAPPING_REJECTED", {
			"mapper_result": mapped,
		})
	var local_position_value: Variant = mapped.get("local_position")
	if not local_position_value is Vector3 or not _valid_vector(local_position_value):
		return _rejected("INVALID_MAPPED_TARGET_LOCAL_POSITION")
	var local_position: Vector3 = local_position_value
	presentation_node.global_position = local_position
	presentation_node.visible = true
	presentation_node.selectable = true
	presentation_node.set_meta("authority_spatial_binding_valid", true)
	presentation_node.set_meta("authority_position", authority_position.duplicate(true))
	presentation_node.set_meta("authority_position_source", position_authority)
	presentation_node.set_meta("authority_world_instance_id", world_instance_id)
	presentation_node.set_meta("authority_projection_sequence", sequence)
	_world_instance_id = world_instance_id
	_session_ref = session_ref_value
	_last_sequence_by_ref[target_ref] = sequence
	_bindings[target_ref] = {
		"target_ref": target_ref,
		"target_kind": target_kind,
		"authority_position": authority_position.duplicate(true),
		"local_position": local_position,
		"world_instance_id": world_instance_id,
		"session_ref": session_ref_value,
		"snapshot_sequence": sequence,
		"source_authority": position_authority,
		"presentation_node_instance_id": presentation_node.get_instance_id(),
		"presentation_node": weakref(presentation_node),
		"node_is_authority_source": false,
	}
	_metrics["projection_updates"] = int(_metrics["projection_updates"]) + 1
	var evidence: Dictionary = binding_for_ref(target_ref)
	target_bound.emit(evidence.duplicate(true))
	return evidence


func binding_for_ref(target_ref_value: String) -> Dictionary:
	var target_ref: String = target_ref_value.strip_edges()
	if not _bindings.has(target_ref):
		return _rejected("TARGET_SPATIAL_BINDING_NOT_FOUND", {"target_ref": target_ref})
	var stored: Dictionary = _bindings[target_ref] as Dictionary
	var node_reference: Variant = stored.get("presentation_node")
	var node: Variant = node_reference.get_ref() if node_reference is WeakRef else null
	if not is_instance_valid(node):
		invalidate_target(target_ref, "PRESENTATION_NODE_FREED", false)
		return _rejected("TARGET_PRESENTATION_NODE_STALE", {"target_ref": target_ref})
	var result: Dictionary = stored.duplicate(true)
	result.erase("presentation_node")
	result["status"] = "PASS"
	result["presentation_node"] = node
	result["authority"] = AUTHORITY
	return result


func authoritative_target_local_position(target_ref_value: String) -> Dictionary:
	var binding: Dictionary = binding_for_ref(target_ref_value)
	if binding.get("status") != "PASS":
		return binding
	return {
		"status": "PASS",
		"target_ref": str(binding.get("target_ref")),
		"local_position": binding.get("local_position"),
		"authority_position": (binding.get("authority_position", {}) as Dictionary).duplicate(true),
		"world_instance_id": str(binding.get("world_instance_id")),
		"snapshot_sequence": int(binding.get("snapshot_sequence", -1)),
		"node_is_authority_source": false,
		"authority": AUTHORITY,
	}


func invalidate_target(target_ref_value: String, reason: String, hide_node: bool = true) -> Dictionary:
	var target_ref: String = target_ref_value.strip_edges()
	var existed: bool = _bindings.has(target_ref)
	if existed:
		var stored: Dictionary = _bindings[target_ref] as Dictionary
		var node_reference: Variant = stored.get("presentation_node")
		var node: Variant = node_reference.get_ref() if node_reference is WeakRef else null
		if is_instance_valid(node):
			node.set_meta("authority_spatial_binding_valid", false)
			node.selectable = false
			if hide_node:
				node.visible = false
	_bindings.erase(target_ref)
	_last_sequence_by_ref.erase(target_ref)
	if existed:
		_metrics["target_invalidations"] = int(_metrics["target_invalidations"]) + 1
	var evidence := {
		"status": "PASS",
		"target_ref": target_ref,
		"invalidated": existed,
		"reason": reason,
		"authority": AUTHORITY,
	}
	target_invalidated.emit(evidence.duplicate(true))
	return evidence


func invalidate_all(reason: String, hide_nodes: bool = true) -> Dictionary:
	var refs: Array[String] = []
	for value: Variant in _bindings.keys():
		refs.append(str(value))
	for target_ref: String in refs:
		invalidate_target(target_ref, reason, hide_nodes)
	_bindings.clear()
	_last_sequence_by_ref.clear()
	_world_instance_id = ""
	_session_ref = ""
	return {
		"status": "PASS",
		"invalidated_count": refs.size(),
		"reason": reason,
		"authority": AUTHORITY,
	}


func binding_count() -> int:
	return _bindings.size()


func metrics_snapshot() -> Dictionary:
	return _metrics.merged({
		"status": "PASS",
		"binding_count": _bindings.size(),
		"world_instance_id": _world_instance_id,
		"session_ref": _session_ref,
		"presentation_node_is_authority_source": false,
		"gameplay_distance_authority": false,
		"authority": AUTHORITY,
	}, true)


func contract_snapshot() -> Dictionary:
	return {
		"status": "PASS" if _mapper != null else "NOT_READY",
		"target_identity_source": "SERVER_AUTHORITATIVE_PROJECTION",
		"target_position_source": "SERVER_AUTHORITATIVE_PROJECTION",
		"coordinate_converter": "AndromedaAuthoritySpaceMapper",
		"presentation_node_is_authority_source": false,
		"gameplay_distance_authority": false,
		"world_scoped": true,
		"session_scoped": true,
		"authority": AUTHORITY,
	}


func _validate_snapshot_envelope(snapshot: Dictionary) -> Dictionary:
	if snapshot.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_TARGET_SNAPSHOT")
	var identity_value: Variant = snapshot.get("identity")
	if not identity_value is Dictionary:
		return _rejected("TARGET_SNAPSHOT_IDENTITY_REQUIRED")
	var world_instance_id: String = str((identity_value as Dictionary).get("world_instance_id", "")).strip_edges()
	var session_ref_value: String = str(snapshot.get("session_ref", "")).strip_edges()
	var sequence_value: Variant = snapshot.get("snapshot_sequence")
	if world_instance_id.is_empty():
		return _rejected("TARGET_WORLD_INSTANCE_ID_REQUIRED")
	if session_ref_value.is_empty():
		return _rejected("TARGET_SESSION_REF_REQUIRED")
	if typeof(sequence_value) != TYPE_INT or int(sequence_value) < 0:
		return _rejected("INVALID_TARGET_SNAPSHOT_SEQUENCE")
	return {
		"status": "PASS",
		"world_instance_id": world_instance_id,
		"session_ref": session_ref_value,
		"snapshot_sequence": int(sequence_value),
		"authority": AUTHORITY,
	}


func _on_session_revoked(_previous_session_ref: String, _session_epoch: int) -> void:
	invalidate_all("SESSION_REVOKED_AWAITING_FRESH_PROJECTION", true)
	_metrics["session_invalidations"] = int(_metrics["session_invalidations"]) + 1


func _on_connection_state_changed(state: String, _detail: String) -> void:
	if state not in [
		AndromedaRuntimeBridge.STATE_RECONNECT_WAIT,
		AndromedaRuntimeBridge.STATE_DISCONNECTED,
	]:
		return
	invalidate_all("TRANSPORT_NOT_READY_AWAITING_FRESH_PROJECTION", true)
	_metrics["session_invalidations"] = int(_metrics["session_invalidations"]) + 1


func _session() -> AndromedaClientSession:
	return get_node_or_null("/root/ClientSession") as AndromedaClientSession


func _bridge() -> AndromedaRuntimeBridge:
	return get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge


func _valid_authority_position(value: Dictionary) -> bool:
	return (
		_valid_number(value.get("iso_x_m"))
		and _valid_number(value.get("iso_y_m"))
		and _valid_number(value.get("altitude_m", 0.0))
	)


func _valid_vector(value: Vector3) -> bool:
	return is_finite(value.x) and is_finite(value.y) and is_finite(value.z)


func _valid_number(value: Variant) -> bool:
	return typeof(value) in [TYPE_INT, TYPE_FLOAT] and is_finite(float(value))


func _rejected(reason: String, detail: Dictionary = {}) -> Dictionary:
	var result := {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
	result.merge(detail, true)
	return result
