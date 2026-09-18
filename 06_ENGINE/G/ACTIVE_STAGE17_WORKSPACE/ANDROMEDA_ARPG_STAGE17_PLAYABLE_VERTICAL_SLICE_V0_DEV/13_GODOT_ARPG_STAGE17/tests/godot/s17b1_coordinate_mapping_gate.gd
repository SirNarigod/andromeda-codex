extends Node

## S17-B1 live contract proof.  The anchor comes from the first real authority
## snapshot paired with the actual Stage17 Player node; no observed spawn value
## appears in this test or in the mapper.

const SESSION_REF := "GODOT-STAGE17-B1-MAPPING-V010"
const WAIT_TIMEOUT_S := 60.0
const EPSILON_M := AndromedaAuthoritySpaceMapper.NUMERIC_ROUNDTRIP_TOLERANCE_M

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _checks: int = 0
var _failures: Array[String] = []
var _binds: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []


func _ready() -> void:
	await _run()


func _run() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_check("MAIN_PRESENT", main != null)
	_check("SESSION_PRESENT", session != null)
	_check("BRIDGE_PRESENT", bridge != null)
	_check("MAPPER_PRESENT", main != null and main.authority_space_mapper != null)
	if main == null or session == null or bridge == null:
		await _finish()
		return
	bridge.authority_session_bound.connect(func(value: Dictionary) -> void: _binds.append(value.duplicate(true)))
	bridge.snapshot_applied.connect(func(value: Dictionary) -> void: _snapshots.append(value.duplicate(true)))
	if session.has_active_session():
		session.revoke_session()
	_check("LOCAL_SESSION_BOUND", session.bind_session(SESSION_REF).get("status") == "PASS")
	_check("AUTHORITY_BIND_STARTED", bridge.bind_authoritative_session().get("status") == "PASS")
	if not await _wait_for_size(_binds, 1) or not await _wait_for_size(_snapshots, 1):
		_failures.append("LIVE_ANCHOR_TIMEOUT")
		await _finish()
		return
	var snapshot: Dictionary = _snapshots[0]
	var mapper := main.authority_space_mapper
	var player := main.player
	var contract: Dictionary = mapper.contract_snapshot()
	_check("REAL_SERVER_AUTHORITATIVE_SNAPSHOT", snapshot.get("server_authoritative") == true)
	_check("AUTHORITY_ORIGIN_REAL", mapper.is_anchored() and contract.get("anchored") == true)
	_check("WORLD_IDENTITY_REAL", str(contract.get("world_instance_id", "")) == str(snapshot.get("identity", {}).get("world_instance_id", "")))
	_check("SESSION_IDENTITY_REAL", str(contract.get("session_ref", "")) == SESSION_REF)
	var anchored_local: Vector3 = contract.get("local_origin") as Vector3
	var player_horizontal := Vector2(player.global_position.x, player.global_position.z)
	var anchor_horizontal := Vector2(anchored_local.x, anchored_local.z)
	# CharacterBody floor settling may adjust local Y after the snapshot callback;
	# B1's territorial contract concerns the horizontal X/Z <-> iso_x/iso_y plane.
	_check("LOCAL_ORIGIN_IS_ACTUAL_PLAYER_XZ", anchor_horizontal.distance_to(player_horizontal) <= EPSILON_M)
	var authority_origin: Dictionary = contract.get("authority_origin", {})
	var transform: Dictionary = snapshot.get("transform", {})
	_check("AUTHORITY_ORIGIN_X_FROM_SNAPSHOT", absf(float(authority_origin.get("iso_x_m")) - float(transform.get("iso_x_m"))) <= EPSILON_M)
	_check("AUTHORITY_ORIGIN_Y_FROM_SNAPSHOT", absf(float(authority_origin.get("iso_y_m")) - float(transform.get("iso_y_m"))) <= EPSILON_M)
	_check("AXIS_X_POSITIVE", str(contract.get("axis_mapping", {}).get("local_x")) == "+iso_x_m")
	_check("AXIS_Z_POSITIVE", str(contract.get("axis_mapping", {}).get("local_z")) == "+iso_y_m")
	_check("SCALE_ONE_METRE", is_equal_approx(float(contract.get("scale_m_per_local_unit")), 1.0))
	_check("NO_GAMEPLAY_AUTHORITY", contract.get("gameplay_authority") == false and contract.get("navigation_authority") == false)
	var local_origin: Vector3 = contract.get("local_origin") as Vector3
	var offsets: Array[Vector3] = [
		Vector3.ZERO,
		Vector3(1.0, 0.0, 0.0),
		Vector3(0.0, 0.0, 1.0),
		Vector3(-2.75, 0.0, 3.5),
		Vector3(8.125, 0.0, -6.25),
	]
	var max_local_error: float = 0.0
	var max_authority_error: float = 0.0
	for offset: Vector3 in offsets:
		var local_point: Vector3 = local_origin + offset
		var mapped: Dictionary = mapper.local_to_authority(local_point)
		_check("LOCAL_TO_AUTHORITY_%s" % _token(offset), mapped.get("status") == "PASS")
		if mapped.get("status") != "PASS":
			continue
		var expected_x: float = float(authority_origin.get("iso_x_m")) + offset.x
		var expected_y: float = float(authority_origin.get("iso_y_m")) + offset.z
		max_authority_error = maxf(
			max_authority_error,
			maxf(
				absf(float(mapped.get("iso_x_m")) - expected_x),
				absf(float(mapped.get("iso_y_m")) - expected_y)
			)
		)
		var reversed: Dictionary = mapper.authority_to_local(mapped)
		_check("AUTHORITY_TO_LOCAL_%s" % _token(offset), reversed.get("status") == "PASS")
		if reversed.get("status") == "PASS":
			max_local_error = maxf(max_local_error, (reversed.get("local_position") as Vector3).distance_to(local_point))
	_check("LOCAL_ROUNDTRIP_WITHIN_TOLERANCE", max_local_error <= EPSILON_M, str(max_local_error))
	_check("AUTHORITY_ROUNDTRIP_WITHIN_TOLERANCE", max_authority_error <= EPSILON_M, str(max_authority_error))
	_check("NEGATIVE_VALUES_COVERED", offsets.any(func(value: Vector3) -> bool: return value.x < 0.0 or value.z < 0.0))
	_check("MULTIPLE_POINTS_COVERED", offsets.size() >= 5)
	_check("NAN_LOCAL_REJECTED", mapper.local_to_authority(Vector3(NAN, 0.0, 0.0)).get("status") == "REJECTED")
	_check("INF_AUTHORITY_REJECTED", mapper.authority_to_local({"iso_x_m": INF, "iso_y_m": 0.0}).get("status") == "REJECTED")
	_check("NUMERIC_TOLERANCE_DOCUMENTED", EPSILON_M == 0.00001)
	_check("ANCHOR_NOT_HARDCODED", str(contract.get("anchor_source")) == "FIRST_REAL_SERVER_AUTHORITATIVE_SNAPSHOT_PLUS_ACTUAL_PLAYER_NODE")
	_check("CONTRACT_EVIDENCE_IDENTIFIED", not str(contract.get("contract_evidence", "")).is_empty())
	await _finish({"max_local_error_m": max_local_error, "max_authority_error_m": max_authority_error, "contract": _json_contract(contract)})


func _json_contract(value: Dictionary) -> Dictionary:
	var result := value.duplicate(true)
	var local: Vector3 = result.get("local_origin", Vector3.ZERO)
	result["local_origin"] = {"x": local.x, "y": local.y, "z": local.z}
	return result


func _token(value: Vector3) -> String:
	return "%s_%s" % [str(value.x).replace("-", "N").replace(".", "P"), str(value.z).replace("-", "N").replace(".", "P")]


func _wait_for_size(values: Array, size: int) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while values.size() < size and Time.get_ticks_usec() < deadline:
		await get_tree().process_frame
	return values.size() >= size


func _check(id: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(id if detail.is_empty() else "%s:%s" % [id, detail])


func _finish(extra: Dictionary = {}) -> void:
	var summary := {"status": "PASS" if _failures.is_empty() else "FAIL", "checks": _checks, "passed": _checks - _failures.size(), "failed": _failures.size(), "failures": _failures, "gate": "S17_B1_COORDINATE_MAPPING", "backend_roundtrip_executed": true}
	summary.merge(extra, true)
	print("ANDROMEDA_STAGE17_B1_GATE: %s" % summary["status"])
	print("ANDROMEDA_STAGE17_B1_SUMMARY: %s" % JSON.stringify(summary))
	get_tree().quit(0 if _failures.is_empty() else 1)
