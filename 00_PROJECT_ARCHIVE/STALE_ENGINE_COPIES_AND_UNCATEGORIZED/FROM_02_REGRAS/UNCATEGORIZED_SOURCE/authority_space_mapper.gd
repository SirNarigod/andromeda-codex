extends Node
class_name AndromedaAuthoritySpaceMapper

## Stage17 presentation-space mapping only.
##
## AUTHORITY POSITION: backend v15_motion_state iso_x_m / iso_y_m.
## LOCAL PRESENTATION: Godot CharacterBody3D X/Z metres.
## MAPPING: the first authoritative snapshot is paired with the actual Player node
## position.  The accepted Stage16B G16B-04 evidence proves +X <-> +iso_x,
## +Z <-> +iso_y and 1 metre : 1 metre.  No observed spawn coordinate is hardcoded.

signal anchor_established(contract: Dictionary)
signal anchor_rejected(reason: String)

const AUTHORITY := "STAGE17_GODOT_AUTHORITY_SPACE_PRESENTATION_MAPPING"
const CONTRACT_EVIDENCE := "AUTHORITY_G16B_04_ROOT_CAUSE_V0_8_3"
const NUMERIC_ROUNDTRIP_TOLERANCE_M := 0.00001

var _anchored: bool = false
var _world_instance_id: String = ""
var _session_ref: String = ""
var _authority_origin_iso_x_m: float = 0.0
var _authority_origin_iso_y_m: float = 0.0
var _authority_origin_altitude_m: float = 0.0
var _local_origin: Vector3 = Vector3.ZERO


func establish_from_snapshot(snapshot: Dictionary, local_player_position: Vector3) -> Dictionary:
	var validation: Dictionary = validate_snapshot_transform(snapshot)
	if validation.get("status") != "PASS":
		anchor_rejected.emit(str(validation.get("reason", "INVALID_AUTHORITY_TRANSFORM")))
		return validation
	if not _valid_vector(local_player_position):
		return _rejected("INVALID_LOCAL_ANCHOR")
	var identity: Dictionary = snapshot.get("identity", {}) as Dictionary
	var world_instance_id: String = str(identity.get("world_instance_id", "")).strip_edges()
	if world_instance_id.is_empty():
		return _rejected("WORLD_INSTANCE_ID_REQUIRED")
	if _anchored:
		if world_instance_id != _world_instance_id:
			return _rejected("WORLD_INSTANCE_CHANGED_REQUIRES_EXPLICIT_RESET", {
				"anchored_world_instance_id": _world_instance_id,
				"snapshot_world_instance_id": world_instance_id,
			})
		return {
			"status": "PASS",
			"retained": true,
			"contract": contract_snapshot(),
			"authority": AUTHORITY,
		}
	var transform: Dictionary = snapshot.get("transform", {}) as Dictionary
	_authority_origin_iso_x_m = float(transform.get("iso_x_m"))
	_authority_origin_iso_y_m = float(transform.get("iso_y_m"))
	_authority_origin_altitude_m = float(transform.get("altitude_m", 0.0))
	_local_origin = local_player_position
	_world_instance_id = world_instance_id
	_session_ref = str(snapshot.get("session_ref", "")).strip_edges()
	_anchored = true
	var contract: Dictionary = contract_snapshot()
	anchor_established.emit(contract.duplicate(true))
	return {"status": "PASS", "retained": false, "contract": contract, "authority": AUTHORITY}


func reset_for_world_change(expected_previous_world_instance_id: String) -> Dictionary:
	if not _anchored:
		return {"status": "PASS", "reset": false, "authority": AUTHORITY}
	if expected_previous_world_instance_id != _world_instance_id:
		return _rejected("WORLD_RESET_IDENTITY_MISMATCH")
	_anchored = false
	_world_instance_id = ""
	_session_ref = ""
	return {"status": "PASS", "reset": true, "authority": AUTHORITY}


func is_anchored() -> bool:
	return _anchored


func local_to_authority(local_position: Vector3) -> Dictionary:
	if not _anchored:
		return _rejected("AUTHORITY_SPACE_ANCHOR_NOT_READY")
	if not _valid_vector(local_position):
		return _rejected("INVALID_LOCAL_POSITION")
	var delta: Vector3 = local_position - _local_origin
	return {
		"status": "PASS",
		"iso_x_m": _authority_origin_iso_x_m + float(delta.x),
		"iso_y_m": _authority_origin_iso_y_m + float(delta.z),
		"altitude_m": _authority_origin_altitude_m + float(delta.y),
		"authority": AUTHORITY,
	}


func authority_to_local(authority_position: Dictionary) -> Dictionary:
	if not _anchored:
		return _rejected("AUTHORITY_SPACE_ANCHOR_NOT_READY")
	if not _valid_number(authority_position.get("iso_x_m")) or not _valid_number(authority_position.get("iso_y_m")):
		return _rejected("INVALID_AUTHORITY_POSITION")
	var altitude_value: Variant = authority_position.get("altitude_m", _authority_origin_altitude_m)
	if not _valid_number(altitude_value):
		return _rejected("INVALID_AUTHORITY_ALTITUDE")
	# Subtract at 64-bit scalar precision before constructing Vector3.  Country-scale
	# values otherwise lose sub-metre distinctions in a float Vector3.
	var local_position := _local_origin + Vector3(
		float(authority_position.get("iso_x_m")) - _authority_origin_iso_x_m,
		float(altitude_value) - _authority_origin_altitude_m,
		float(authority_position.get("iso_y_m")) - _authority_origin_iso_y_m
	)
	return {"status": "PASS", "local_position": local_position, "authority": AUTHORITY}


func validate_snapshot_transform(snapshot: Dictionary) -> Dictionary:
	if snapshot.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_ANCHOR_SNAPSHOT")
	var transform_value: Variant = snapshot.get("transform")
	if not transform_value is Dictionary:
		return _rejected("INVALID_AUTHORITY_TRANSFORM")
	var transform: Dictionary = transform_value
	if not _valid_number(transform.get("iso_x_m")) or not _valid_number(transform.get("iso_y_m")):
		return _rejected("INVALID_AUTHORITY_TRANSFORM")
	if transform.has("altitude_m") and not _valid_number(transform.get("altitude_m")):
		return _rejected("INVALID_AUTHORITY_ALTITUDE")
	return {"status": "PASS", "authority": AUTHORITY}


func contract_snapshot() -> Dictionary:
	return {
		"status": "PASS" if _anchored else "NOT_READY",
		"anchored": _anchored,
		"world_instance_id": _world_instance_id,
		"session_ref": _session_ref,
		"authority_origin": {
			"iso_x_m": _authority_origin_iso_x_m,
			"iso_y_m": _authority_origin_iso_y_m,
			"altitude_m": _authority_origin_altitude_m,
		},
		"local_origin": _local_origin,
		"axis_mapping": {"local_x": "+iso_x_m", "local_z": "+iso_y_m", "local_y": "+altitude_m"},
		"scale_m_per_local_unit": 1.0,
		"numeric_roundtrip_tolerance_m": NUMERIC_ROUNDTRIP_TOLERANCE_M,
		"anchor_source": "FIRST_REAL_SERVER_AUTHORITATIVE_SNAPSHOT_PLUS_ACTUAL_PLAYER_NODE",
		"contract_evidence": CONTRACT_EVIDENCE,
		"gameplay_authority": false,
		"navigation_authority": false,
		"authority": AUTHORITY,
	}


func _valid_vector(value: Vector3) -> bool:
	return is_finite(value.x) and is_finite(value.y) and is_finite(value.z)


func _valid_number(value: Variant) -> bool:
	return (typeof(value) == TYPE_INT or typeof(value) == TYPE_FLOAT) and is_finite(float(value))


func _rejected(reason: String, detail: Dictionary = {}) -> Dictionary:
	var result := {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
	result.merge(detail, true)
	return result
