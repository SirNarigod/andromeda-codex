extends Node

## Live C1 contract gate.  Resource identity and metric position originate in
## the materialized Stage17 backend, traverse the normal snapshot, reuse the C0
## registry + B1 mapper, and terminate at the greybox ResourceNode as presentation.

const SESSION_REF := "GODOT-STAGE17-C1-RESOURCE-V010"
const WAIT_TIMEOUT_S := 90.0
const EXPECTED_KINDS: Array[String] = ["TREE", "ORE"]

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _checks: int = 0
var _failures: Array[String] = []
var _binds: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []
var _evidence: Dictionary = {}


func _ready() -> void:
	await _run()


func _run() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	var registry: AndromedaInteractionSpatialBindingRegistry = main.interaction_spatial_binding_registry
	_check("RUNTIME_PRESENT", main != null and session != null and bridge != null and registry != null)
	if main == null or session == null or bridge == null or registry == null:
		await _finish()
		return
	bridge.authority_session_bound.connect(func(value: Dictionary) -> void: _binds.append(value.duplicate(true)))
	bridge.snapshot_applied.connect(func(value: Dictionary) -> void: _snapshots.append(value.duplicate(true)))
	if session.has_active_session():
		session.revoke_session()
	_check("LOCAL_SESSION_BOUND", session.bind_session(SESSION_REF).get("status") == "PASS")
	_check("AUTHORITY_BIND_STARTED", bridge.bind_authoritative_session().get("status") == "PASS")
	if not await _wait_for_size(_binds, 1) or not await _wait_for_size(_snapshots, 1):
		_failures.append("LIVE_STARTUP_TIMEOUT")
		await _finish()
		return
	await get_tree().physics_frame
	await get_tree().physics_frame
	var snapshot: Dictionary = _snapshots.back()
	var world_instance_id: String = str((snapshot.get("identity", {}) as Dictionary).get("world_instance_id", ""))
	var resources: Array = snapshot.get("resources", []) as Array
	_check("BRIDGE_READY", bridge.connection_state().get("state") == AndromedaRuntimeBridge.STATE_READY)
	_check("MAPPER_READY", main.authority_space_mapper.is_anchored())
	_check("SNAPSHOT_SERVER_AUTHORITATIVE", snapshot.get("server_authoritative") == true)
	_check("WORLD_INSTANCE_ID_PRESENT", not world_instance_id.is_empty())
	_check("ACTIVE_RESOURCE_SUBSET_COUNT", resources.size() == 2, str(resources.size()))
	_check("ACTIVE_RESOURCE_KINDS_TREE_ORE", _kinds(resources) == ["ORE", "TREE"])
	_check("SNAPSHOT_PAYLOAD_BOUNDED", JSON.stringify(resources).to_utf8_buffer().size() < 8192)

	var per_kind: Dictionary = {}
	for kind: String in EXPECTED_KINDS:
		var entry: Dictionary = _entry_by_kind(resources, kind)
		var placement_ref: String = str(entry.get("placement_ref", "")).strip_edges()
		var logical_ref: String = str(entry.get("logical_node_ref", "")).strip_edges()
		var resource: AndromedaResourceNode = main.gathering_client.resource_for_ref(placement_ref)
		var binding: Dictionary = registry.binding_for_ref(placement_ref)
		_check("%s_PHYSICAL_REF_REAL" % kind, placement_ref.begins_with("RESOURCE-PLACEMENT-S17-"))
		_check("%s_LOGICAL_GTH_REAL" % kind, logical_ref.begins_with("GTH-"))
		_check("%s_IDENTITIES_SEPARATE" % kind, placement_ref != logical_ref)
		_check("%s_TARGET_KIND_RESOURCE" % kind, str(entry.get("target_kind", "")) == "RESOURCE")
		_check("%s_POSITION_REAL" % kind, _valid_authority_position(entry.get("position", {})))
		_check("%s_POSITION_AUTHORITY_REAL" % kind, str(entry.get("position_authority", "")) == "STAGE17_RESOURCE_METRIC_PLACEMENT_MATERIALIZED")
		_check("%s_SAME_WORLD" % kind, str(entry.get("world_instance_id", "")) == world_instance_id)
		_check("%s_REVISION_PRESENT" % kind, not str(entry.get("placement_revision", "")).is_empty())
		_check("%s_SERVER_AUTHORITATIVE" % kind, entry.get("server_authoritative") == true)
		_check("%s_NODE_BOUND" % kind, resource != null and binding.get("status") == "PASS")
		if resource == null or binding.get("status") != "PASS":
			continue
		var local_position: Variant = binding.get("local_position")
		_check("%s_NODE_PHYSICAL_REF" % kind, resource.target_ref == placement_ref and resource.placement_ref == placement_ref)
		_check("%s_NODE_LOGICAL_REF" % kind, resource.logical_node_ref == logical_ref)
		_check("%s_NODE_NOT_AUTHORITY_SOURCE" % kind, binding.get("node_is_authority_source") == false)
		_check("%s_MAPPED_LOCAL_FINITE" % kind, local_position is Vector3 and _valid_vector(local_position as Vector3))
		_check("%s_NODE_POSITION_DERIVED_FROM_AUTHORITY" % kind, local_position is Vector3 and resource.global_position.distance_to(local_position as Vector3) <= 0.00001)
		var round_trip: Dictionary = main.authority_space_mapper.local_to_authority(local_position as Vector3)
		_check("%s_MAPPING_ROUND_TRIP" % kind, _authority_distance(round_trip, entry.get("position", {})) <= 0.00001)
		_check("%s_SCENE_TRANSFORM_NOT_AUTHORITY" % kind, resource.presentation_snapshot().get("scene_transform_is_authority") == false)
		_check("%s_GATHER_RANGE_PROJECTED" % kind, is_equal_approx(resource.interaction_range_m, 1.5))
		per_kind[kind] = {
			"placement_ref": placement_ref,
			"logical_node_ref": logical_ref,
			"authority_position": (entry.get("position", {}) as Dictionary).duplicate(true),
			"local_position": local_position,
			"placement_revision": str(entry.get("placement_revision", "")),
		}

	var registry_contract: Dictionary = registry.contract_snapshot()
	_check("REGISTRY_REUSES_B1_MAPPER", registry_contract.get("coordinate_converter") == "AndromedaAuthoritySpaceMapper")
	_check("REGISTRY_HAS_NO_GAMEPLAY_DISTANCE_AUTHORITY", registry_contract.get("gameplay_distance_authority") == false)
	_check("NO_RUNTIME_LOCAL_PLACEHOLDER_AUTHORITY", not JSON.stringify(resources).contains("GODOT_LOCAL_PLACEHOLDER_ONLY"))
	_check("NO_HARDCODED_LIVE_REFS", not _sources_contain_live_refs(per_kind))

	# Stale projections cannot move a live Resource Node.
	var tree_entry: Dictionary = _entry_by_kind(resources, "TREE")
	var tree_ref: String = str(tree_entry.get("placement_ref", ""))
	var tree: AndromedaResourceNode = main.gathering_client.resource_for_ref(tree_ref)
	if tree != null:
		var before_position: Vector3 = tree.global_position
		var stale_snapshot: Dictionary = snapshot.duplicate(true)
		stale_snapshot["snapshot_sequence"] = int(snapshot.get("snapshot_sequence", 0))
		var stale: Dictionary = registry.project_target(stale_snapshot, tree_entry, tree, "RESOURCE")
		_check("STALE_PROJECTION_REJECTED", stale.get("reason") == "STALE_OR_DUPLICATE_TARGET_POSITION_PROJECTION")
		_check("STALE_PROJECTION_DID_NOT_MOVE_NODE", tree.global_position.distance_to(before_position) <= 0.00001)

	# A world mismatch invalidates all bindings, then a real fresh snapshot rebuilds
	# the same physical identities in the actual world.
	var world_fake: Dictionary = snapshot.duplicate(true)
	var fake_identity: Dictionary = (snapshot.get("identity", {}) as Dictionary).duplicate(true)
	fake_identity["world_instance_id"] = "rt:world:C1-WRONG-WORLD"
	world_fake["identity"] = fake_identity
	world_fake["snapshot_sequence"] = int(snapshot.get("snapshot_sequence", 0)) + 1000
	var world_changed: Dictionary = registry.project_target(world_fake, tree_entry, tree, "RESOURCE") if tree != null else {}
	_check("WORLD_CHANGE_REJECTED", world_changed.get("reason") == "WORLD_INSTANCE_CHANGED_REQUIRES_FRESH_MAPPER_ANCHOR")
	_check("WORLD_CHANGE_INVALIDATED_BINDINGS", registry.binding_count() == 0)
	var snapshots_before: int = _snapshots.size()
	_check("FRESH_SNAPSHOT_REQUEST_AFTER_WORLD_INVALIDATION", bridge.request_snapshot().get("status") == "PASS")
	_check("FRESH_SNAPSHOT_ARRIVED_AFTER_WORLD_INVALIDATION", await _wait_for_size(_snapshots, snapshots_before + 1))
	await get_tree().physics_frame
	_check("TREE_REBOUND_AFTER_FRESH_WORLD", registry.binding_for_ref(tree_ref).get("status") == "PASS")

	# Session-scoped cache invalidation is also explicit. A synthetic call cannot
	# enter through the bridge (B01 rejects it), but proves the registry discards
	# prior session bindings before accepting any new projection.
	snapshot = _snapshots.back()
	tree_entry = _entry_by_kind(snapshot.get("resources", []) as Array, "TREE")
	tree = main.gathering_client.resource_for_ref(tree_ref)
	var fake_session: Dictionary = snapshot.duplicate(true)
	fake_session["session_ref"] = "GODOT-STAGE17-C1-OTHER-SESSION"
	fake_session["snapshot_sequence"] = int(snapshot.get("snapshot_sequence", 0)) + 1000
	var session_changed: Dictionary = registry.project_target(fake_session, tree_entry, tree, "RESOURCE") if tree != null else {}
	_check("SESSION_CHANGE_INVALIDATES_THEN_REBINDS", session_changed.get("status") == "PASS")
	_check("SESSION_CHANGE_METRIC_RECORDED", int(registry.metrics_snapshot().get("session_invalidations", 0)) >= 1)
	snapshots_before = _snapshots.size()
	_check("REAL_SESSION_REFRESH_REQUESTED", bridge.request_snapshot().get("status") == "PASS")
	_check("REAL_SESSION_REFRESH_ARRIVED", await _wait_for_size(_snapshots, snapshots_before + 1))
	await get_tree().physics_frame
	_check("REGISTRY_RETURNED_TO_REAL_SESSION", str(registry.metrics_snapshot().get("session_ref", "")) == SESSION_REF)
	_check("TREE_REBOUND_AFTER_REAL_SESSION", registry.binding_for_ref(tree_ref).get("status") == "PASS")
	_check("BOTH_RESOURCES_REBOUND", registry.binding_count() >= 2)

	_evidence = {
		"world_instance_id": world_instance_id,
		"resources": per_kind,
		"snapshot_resource_bytes": JSON.stringify(resources).to_utf8_buffer().size(),
		"registry_metrics": registry.metrics_snapshot(),
		"gathering_metrics": main.gathering_client.stage17_metric_metrics_snapshot(),
	}
	await _finish({"live_evidence": _evidence})


func _entry_by_kind(entries: Array, kind: String) -> Dictionary:
	for value: Variant in entries:
		if value is Dictionary and str((value as Dictionary).get("resource_kind", "")) == kind:
			return (value as Dictionary).duplicate(true)
	return {}


func _kinds(entries: Array) -> Array[String]:
	var values: Array[String] = []
	for value: Variant in entries:
		if value is Dictionary:
			values.append(str((value as Dictionary).get("resource_kind", "")))
	values.sort()
	return values


func _sources_contain_live_refs(per_kind: Dictionary) -> bool:
	var sources: String = FileAccess.get_file_as_string("res://scripts/interaction/gathering_client.gd")
	sources += FileAccess.get_file_as_string("res://scripts/interaction/resource_node.gd")
	for value: Variant in per_kind.values():
		var evidence: Dictionary = value as Dictionary
		if sources.contains(str(evidence.get("placement_ref", ""))):
			return true
		if sources.contains(str(evidence.get("logical_node_ref", ""))):
			return true
	return false


func _valid_authority_position(value: Variant) -> bool:
	if not value is Dictionary:
		return false
	var position: Dictionary = value
	return (
		_valid_number(position.get("iso_x_m"))
		and _valid_number(position.get("iso_y_m"))
		and _valid_number(position.get("altitude_m", 0.0))
	)


func _valid_number(value: Variant) -> bool:
	return typeof(value) in [TYPE_INT, TYPE_FLOAT] and is_finite(float(value))


func _valid_vector(value: Vector3) -> bool:
	return is_finite(value.x) and is_finite(value.y) and is_finite(value.z)


func _authority_distance(a: Dictionary, b: Variant) -> float:
	if not b is Dictionary or not _valid_authority_position(a) or not _valid_authority_position(b):
		return INF
	var target: Dictionary = b
	return Vector3(
		float(a.get("iso_x_m")), float(a.get("altitude_m", 0.0)), float(a.get("iso_y_m"))
	).distance_to(Vector3(
		float(target.get("iso_x_m")), float(target.get("altitude_m", 0.0)), float(target.get("iso_y_m"))
	))


func _wait_for_size(values: Array, expected: int) -> bool:
	var started: int = Time.get_ticks_msec()
	while values.size() < expected and float(Time.get_ticks_msec() - started) / 1000.0 < WAIT_TIMEOUT_S:
		await get_tree().process_frame
	return values.size() >= expected


func _check(label: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if condition:
		return
	_failures.append("%s%s" % [label, ":%s" % detail if not detail.is_empty() else ""])


func _finish(extra: Dictionary = {}) -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "S17_C1_RESOURCE_AUTHORITY_POSITION_CONTRACT",
		"resource_kinds": EXPECTED_KINDS,
		"backend_roundtrip_executed": true,
		"runtime_godot_transform_is_authority": false,
		"gameplay_authority_in_gdscript": false,
	}
	summary.merge(extra, true)
	print("ANDROMEDA_STAGE17_C1_GATE: %s" % summary["status"])
	print("ANDROMEDA_STAGE17_C1_SUMMARY: %s" % JSON.stringify(summary))
	get_tree().quit(0 if _failures.is_empty() else 1)
