extends Node
class_name AndromedaDroppedBagClient

## B10 client orchestration for externally-authorized DroppedBag projections.
## It may navigate and prepare recovery intents; ownership and recovery remain upstream.

signal recovery_request_prepared(result: Dictionary)
signal recovery_result_projected(result: Dictionary)
signal dropped_bag_snapshot_projected(result: Dictionary)

const AUTHORITY := "GODOT_DROPPED_BAG_CLIENT_ORCHESTRATION_ONLY"
const CLIENT_RECOVERY_RANGE_CANDIDATE_M := 0.5
const BLOCKER_MASK := 1 | 128
const DROPPED_BAG_SCENE: PackedScene = preload("res://scenes/interaction/DroppedBag.tscn")

var _main_runtime: AndromedaMainRuntime
var _player: AndromedaPlayerController
var _hud: AndromedaHUDController
var _bag_root: Node3D
var _registered_bags: Dictionary = {}
var _tombstones: Dictionary = {}
var _systemic_references: Dictionary = {}
var _pending_approach: Dictionary = {}
var _inflight_requests: Dictionary = {}
var _result_sequences: Dictionary = {}
var _snapshot_session_ref: String = ""
var _last_snapshot_sequence: int = -1
var _request_serial: int = 0
var _last_request: Dictionary = {}
var _bound: bool = false


func _ready() -> void:
	process_physics_priority = 92


func _physics_process(_delta: float) -> void:
	if not _bound:
		return
	_discover_scene_bags()
	process_pending_approach_once()


func bind_runtime(
	main_runtime_value: AndromedaMainRuntime,
	player_value: AndromedaPlayerController,
	hud_value: AndromedaHUDController,
	bag_root_value: Node3D
) -> Dictionary:
	if main_runtime_value == null or player_value == null or hud_value == null or bag_root_value == null:
		return _rejected("MAIN_PLAYER_HUD_BAG_ROOT_REQUIRED")
	_main_runtime = main_runtime_value
	_player = player_value
	_hud = hud_value
	_bag_root = bag_root_value
	_discover_scene_bags()
	if not _bound:
		var bridge: AndromedaRuntimeBridge = _bridge()
		if bridge != null:
			if not bridge.snapshot_applied.is_connected(_on_bridge_snapshot_applied):
				bridge.snapshot_applied.connect(_on_bridge_snapshot_applied)
			if not bridge.command_result_received.is_connected(_on_bridge_command_result_received):
				bridge.command_result_received.connect(_on_bridge_command_result_received)
		var session: AndromedaClientSession = _session()
		if session != null:
			if not session.session_bound.is_connected(_on_session_bound):
				session.session_bound.connect(_on_session_bound)
			if not session.session_revoked.is_connected(_on_session_revoked):
				session.session_revoked.connect(_on_session_revoked)
		_bound = true
	return {
		"status": "PASS",
		"registered_bag_count": _registered_bags.size(),
		"authority": AUTHORITY,
	}


func register_dropped_bag(bag: AndromedaDroppedBag) -> Dictionary:
	if bag == null or not is_instance_valid(bag):
		return _rejected("DROPPED_BAG_INSTANCE_REQUIRED")
	var ref: String = bag.bag_ref.strip_edges()
	if ref.is_empty() or ref != bag.target_ref.strip_edges():
		return _rejected("STABLE_BAG_TARGET_REF_REQUIRED")
	if _registered_bags.has(ref):
		var existing := _registered_bags[ref] as AndromedaDroppedBag
		if existing != bag:
			return _rejected("DUPLICATE_ACTIVE_BAG_REF")
		return {"status": "PASS", "bag_ref": ref, "idempotent": true, "authority": AUTHORITY}
	_registered_bags[ref] = bag
	return {"status": "PASS", "bag_ref": ref, "idempotent": false, "authority": AUTHORITY}


func dropped_bag_for_ref(bag_ref_value: String) -> AndromedaDroppedBag:
	var value: Variant = _registered_bags.get(bag_ref_value.strip_edges())
	if value is AndromedaDroppedBag and is_instance_valid(value):
		return value as AndromedaDroppedBag
	return null


func handle_manual_bag_intent(resolved: Dictionary, target: AndromedaInteractionTarget) -> Dictionary:
	if resolved.get("status") != "PASS":
		return _rejected("POINTER_INTENT_NOT_PASS")
	if not target is AndromedaDroppedBag:
		return _rejected("SPECIALIZED_DROPPED_BAG_REQUIRED")
	var bag := target as AndromedaDroppedBag
	if str(resolved.get("target_ref", "")).strip_edges() != bag.bag_ref:
		return _rejected("DROPPED_BAG_TARGET_REF_MISMATCH")
	if str(resolved.get("intent", "")).to_upper() != "APPROACH_RECOVER_BAG":
		return _rejected("UNSUPPORTED_DROPPED_BAG_POINTER_INTENT")
	return begin_recovery_interaction(bag, "POINTER_%s" % str(resolved.get("button", "UNKNOWN")))


func handle_selected_interaction(target: AndromedaInteractionTarget) -> Dictionary:
	if not target is AndromedaDroppedBag:
		return _rejected("SELECTED_TARGET_NOT_DROPPED_BAG")
	return begin_recovery_interaction(target as AndromedaDroppedBag, "CONTEXT_E")


func begin_recovery_interaction(bag: AndromedaDroppedBag, request_source: String) -> Dictionary:
	var eligibility: Dictionary = evaluate_recovery_candidate(bag)
	if eligibility.get("status") == "PASS":
		return _prepare_recovery_request(bag, request_source)
	var reason: String = str(eligibility.get("reason", ""))
	if reason != "RECOVERY_DISTANCE_EXCEEDED":
		return eligibility
	var destination: Vector3 = approach_destination_for(bag)
	var path_validation: Dictionary = _player.validate_destination(destination)
	if path_validation.get("status") != "PASS":
		return _rejected("DROPPED_BAG_PATH_INVALID", {"path_result": path_validation})
	var movement: Dictionary = _player.request_move(destination)
	if movement.get("status") != "PASS":
		return _rejected("DROPPED_BAG_APPROACH_REJECTED", {"movement_result": movement})
	_pending_approach.clear()
	_pending_approach[bag.bag_ref] = {
		"bag_ref": bag.bag_ref,
		"instance_id": bag.get_instance_id(),
		"request_source": request_source,
	}
	return {
		"status": "PASS",
		"intent": "APPROACH_RECOVER_BAG_PENDING",
		"bag_ref": bag.bag_ref,
		"movement_result": movement,
		"recovery_requested": false,
		"bag_returned_locally": false,
		"authority": AUTHORITY,
	}


func process_pending_approach_once() -> Dictionary:
	if _pending_approach.is_empty():
		return {"status": "PASS", "pending": false, "authority": AUTHORITY}
	var ref: String = str(_pending_approach.keys()[0])
	var bag: AndromedaDroppedBag = dropped_bag_for_ref(ref)
	if bag == null:
		_pending_approach.clear()
		return _rejected("STALE_OR_REMOVED_DROPPED_BAG_TARGET")
	var eligibility: Dictionary = evaluate_recovery_candidate(bag)
	if eligibility.get("status") == "PASS":
		var source: String = str(_pending_approach[ref].get("request_source", "APPROACH"))
		_pending_approach.clear()
		return _prepare_recovery_request(bag, "%s_AFTER_APPROACH" % source)
	if str(eligibility.get("reason", "")) == "RECOVERY_DISTANCE_EXCEEDED":
		return {"status": "PASS", "pending": true, "bag_ref": ref, "authority": AUTHORITY}
	_pending_approach.clear()
	return eligibility


func evaluate_recovery_candidate(bag: AndromedaDroppedBag) -> Dictionary:
	if _player == null:
		return _rejected("PLAYER_NOT_BOUND")
	if bag == null or not is_instance_valid(bag) or not bag.is_inside_tree():
		return _rejected("STALE_OR_REMOVED_DROPPED_BAG_TARGET")
	if dropped_bag_for_ref(bag.bag_ref) != bag:
		return _rejected("WRONG_OR_UNREGISTERED_DROPPED_BAG_TARGET")
	if not bag.is_recoverable_projection():
		return _rejected("DROPPED_BAG_NOT_RECOVERABLE")
	if _inflight_requests.has(bag.bag_ref):
		return _rejected("RECOVERY_REQUEST_ALREADY_INFLIGHT")
	var physical_distance: float = bag.physical_distance_to(_player)
	var maximum_distance: float = bag.recovery_range_m
	if not is_finite(physical_distance) or physical_distance > maximum_distance:
		return _rejected("RECOVERY_DISTANCE_EXCEEDED", {
			"physical_distance_m": physical_distance,
			"client_range_candidate_m": maximum_distance,
		})
	var blocker: Dictionary = recovery_blocker_probe(bag)
	if blocker.get("blocked") == true:
		return _rejected("DROPPED_BAG_RECOVERY_BLOCKED", {"blocker": blocker})
	var path_result: Dictionary = _player.validate_destination(bag.interaction_anchor_world_position())
	if path_result.get("status") != "PASS":
		return _rejected("DROPPED_BAG_PATH_INVALID", {"path_result": path_result})
	return {
		"status": "PASS",
		"bag_ref": bag.bag_ref,
		"physical_distance_m": physical_distance,
		"client_range_candidate_m": maximum_distance,
		"authority": AUTHORITY,
	}


func recovery_blocker_probe(bag: AndromedaDroppedBag) -> Dictionary:
	if _player == null or bag == null or not is_instance_valid(bag):
		return {"blocked": true, "reason": "INVALID_PROBE_PARTICIPANT", "authority": AUTHORITY}
	var from: Vector3 = _player.global_position + Vector3.UP * 0.45
	var to: Vector3 = bag.interaction_anchor_world_position() + Vector3.UP * 0.1
	var query := PhysicsRayQueryParameters3D.create(from, to, BLOCKER_MASK, [_player.get_rid(), bag.get_rid()])
	query.collide_with_areas = false
	query.collide_with_bodies = true
	var hit: Dictionary = _player.get_world_3d().direct_space_state.intersect_ray(query)
	return {
		"blocked": not hit.is_empty(),
		"collider": str((hit.get("collider") as Node).name) if hit.get("collider") is Node else "",
		"authority": AUTHORITY,
	}


func approach_destination_for(bag: AndromedaDroppedBag) -> Vector3:
	if _player == null or bag == null:
		return Vector3.ZERO
	var anchor: Vector3 = bag.interaction_anchor_world_position()
	var away: Vector3 = _player.global_position - anchor
	away.y = 0.0
	if away.length_squared() < 0.0001:
		away = Vector3.RIGHT
	var candidate: Vector3 = anchor + away.normalized() * maxf(0.1, bag.recovery_range_m * 0.75)
	return _main_runtime.closest_navigation_point(candidate) if _main_runtime != null else candidate


func project_dropped_bag_snapshot(snapshot: Dictionary) -> Dictionary:
	var external: Dictionary = _validate_external(snapshot, "DROPPED_BAG_SNAPSHOT")
	if external.get("status") != "PASS":
		return external
	var sequence_value: Variant = snapshot.get("snapshot_sequence")
	if typeof(sequence_value) != TYPE_INT or typeof(sequence_value) == TYPE_BOOL or int(sequence_value) < 0:
		return _rejected("INVALID_DROPPED_BAG_SNAPSHOT_SEQUENCE")
	var sequence: int = int(sequence_value)
	if sequence <= _last_snapshot_sequence:
		return _rejected("STALE_OR_DUPLICATE_DROPPED_BAG_SNAPSHOT")
	if not snapshot.get("dropped_bags", []) is Array:
		return _rejected("INVALID_DROPPED_BAG_SNAPSHOT_ENTRIES")
	var entries: Array = snapshot.get("dropped_bags", [])
	var refs_seen: Dictionary = {}
	for entry_value: Variant in entries:
		if not entry_value is Dictionary:
			return _rejected("MALFORMED_DROPPED_BAG_ENTRY")
		var entry: Dictionary = entry_value
		var preflight: Dictionary = _preflight_entry(entry)
		if preflight.get("status") != "PASS":
			return preflight
		var ref: String = str(entry.get("bag_ref", entry.get("target_ref", ""))).strip_edges()
		if refs_seen.has(ref):
			return _rejected("DUPLICATE_BAG_REF_IN_SNAPSHOT")
		refs_seen[ref] = true

	_snapshot_session_ref = str(snapshot.get("session_ref", ""))
	_last_snapshot_sequence = sequence
	var projected: Array[Dictionary] = []
	for entry_value: Variant in entries:
		var entry: Dictionary = (entry_value as Dictionary).duplicate(true)
		entry["server_authoritative"] = true
		var result: Dictionary = _project_entry(entry, _snapshot_session_ref, sequence)
		if result.get("status") != "PASS":
			return result
		projected.append(result)
	if bool(snapshot.get("complete_projection", false)):
		_remove_missing_external_refs(refs_seen, sequence)
	var output := {
		"status": "PASS",
		"snapshot_sequence": sequence,
		"projected_count": projected.size(),
		"active_bag_count": active_bag_count(),
		"identity_deduplicated": true,
		"ownership_mutated_locally": false,
		"ttl_advanced_locally": false,
		"authority": AUTHORITY,
	}
	dropped_bag_snapshot_projected.emit(output.duplicate(true))
	return output


func project_recovery_result(result: Dictionary) -> Dictionary:
	var external: Dictionary = _validate_external(result, "BAG_RECOVERY_RESULT")
	if external.get("status") != "PASS":
		return external
	var result_sequence_value: Variant = result.get("result_sequence")
	if typeof(result_sequence_value) != TYPE_INT or typeof(result_sequence_value) == TYPE_BOOL or int(result_sequence_value) < 0:
		return _rejected("INVALID_BAG_RECOVERY_RESULT_SEQUENCE")
	var ref: String = str(result.get("bag_ref", "")).strip_edges()
	var request_ref: String = str(result.get("request_ref", "")).strip_edges()
	if ref.is_empty() or request_ref.is_empty():
		return _rejected("BAG_AND_REQUEST_REF_REQUIRED")
	var sequence: int = int(result_sequence_value)
	if sequence <= int(_result_sequences.get(ref, -1)):
		return _rejected("STALE_OR_DUPLICATE_BAG_RECOVERY_RESULT")
	if not _inflight_requests.has(ref):
		return _rejected("NO_INFLIGHT_BAG_RECOVERY_REQUEST")
	var inflight: Dictionary = _inflight_requests[ref]
	if str(inflight.get("request_ref", "")) != request_ref:
		return _rejected("BAG_RECOVERY_REQUEST_REF_MISMATCH")
	var outcome: String = str(result.get("result", "")).to_upper()
	if outcome not in ["ACCEPTED", "REJECTED"]:
		return _rejected("INVALID_BAG_RECOVERY_RESULT")
	var projection_result: Dictionary = {}
	if outcome == "ACCEPTED":
		if not result.get("bag_projection", {}) is Dictionary:
			return _rejected("ACCEPTED_RECOVERY_REQUIRES_EXTERNAL_BAG_PROJECTION")
		var projection: Dictionary = (result.get("bag_projection") as Dictionary).duplicate(true)
		projection["server_authoritative"] = true
		var bag: AndromedaDroppedBag = dropped_bag_for_ref(ref)
		if bag == null:
			return _rejected("RECOVERED_BAG_PROJECTION_TARGET_MISSING")
		projection_result = bag.apply_authoritative_projection(
			projection,
			str(result.get("session_ref", "")),
			int(projection.get("projection_sequence", sequence))
		)
		if projection_result.get("status") != "PASS":
			return projection_result
	_result_sequences[ref] = sequence
	_inflight_requests.erase(ref)
	var output := {
		"status": "PASS",
		"bag_ref": ref,
		"request_ref": request_ref,
		"result": outcome,
		"reason": str(result.get("reason", "")),
		"bag_projection": projection_result,
		"bag_returned_locally": false,
		"contents_moved_locally": false,
		"ownership_mutated_locally": false,
		"authority": AUTHORITY,
	}
	recovery_result_projected.emit(output.duplicate(true))
	return output


func project_stream_phase(bag_ref_value: String, phase: String, sequence: int, externally_confirmed: bool) -> Dictionary:
	var ref: String = bag_ref_value.strip_edges()
	var bag: AndromedaDroppedBag = dropped_bag_for_ref(ref)
	if bag == null:
		return _rejected("DROPPED_BAG_NOT_REGISTERED")
	var result: Dictionary = bag.project_stream_phase(phase, sequence, externally_confirmed)
	if result.get("status") != "PASS":
		return result
	if phase.to_upper() == AndromedaDroppedBag.STREAM_SYSTEMIC:
		_systemic_references[ref] = bag.presentation_snapshot()
	else:
		_systemic_references.erase(ref)
	return result


func observe_foreign_npc_proximity(bag_ref_value: String, npc_ref: String) -> Dictionary:
	return {
		"status": "PASS",
		"bag_ref": bag_ref_value.strip_edges(),
		"npc_ref": npc_ref.strip_edges(),
		"auto_recovery_requested": false,
		"auto_theft": false,
		"ownership_changed": false,
		"authority": AUTHORITY,
	}


func active_bag_count() -> int:
	var count: int = 0
	for value: Variant in _registered_bags.values():
		if value is AndromedaDroppedBag:
			var bag := value as AndromedaDroppedBag
			if is_instance_valid(bag) and bag.projected_state() in AndromedaDroppedBag.ACTIVE_PRESENTATION_STATES:
				count += 1
	return count


func registered_bag_count() -> int:
	return _registered_bags.size()


func inflight_request_count() -> int:
	return _inflight_requests.size()


func last_request() -> Dictionary:
	return _last_request.duplicate(true)


func tombstone_for_ref(bag_ref_value: String) -> Dictionary:
	return (_tombstones.get(bag_ref_value.strip_edges(), {}) as Dictionary).duplicate(true)


func systemic_reference_for_ref(bag_ref_value: String) -> Dictionary:
	return (_systemic_references.get(bag_ref_value.strip_edges(), {}) as Dictionary).duplicate(true)


func clear_client_request_tracking() -> void:
	_pending_approach.clear()
	_inflight_requests.clear()


func contract_snapshot() -> Dictionary:
	return {
		"target_kind": AndromedaInputRouter.HIT_DROPPED_BAG,
		"client_recovery_range_candidate_m": CLIENT_RECOVERY_RANGE_CANDIDATE_M,
		"recovery_requires_external_confirmation": true,
		"foreign_npc_auto_theft": false,
		"ownership_authority": false,
		"contents_authority": false,
		"recovery_authority": false,
		"ttl_authority": false,
		"death_authority": false,
		"systemic_authority": false,
		"backend_substitute": false,
		"authority": AUTHORITY,
	}


func _prepare_recovery_request(bag: AndromedaDroppedBag, request_source: String) -> Dictionary:
	var eligibility: Dictionary = evaluate_recovery_candidate(bag)
	if eligibility.get("status") != "PASS":
		return eligibility
	var bridge: AndromedaRuntimeBridge = _bridge()
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	_request_serial += 1
	var request_ref: String = "B10-BAG-RECOVERY-%06d" % _request_serial
	var params := {
		"request_ref": request_ref,
		"bag_ref": bag.bag_ref,
		"target_ref": bag.target_ref,
		"target_kind": AndromedaInputRouter.HIT_DROPPED_BAG,
		"request_source": request_source,
		"physical_distance_m": float(eligibility.get("physical_distance_m", INF)),
		"client_range_candidate_m": bag.recovery_range_m,
		"client_guard_passed": true,
		"client_presentation_only": true,
	}
	var built: Dictionary = bridge.build_command_envelope("REQUEST_BAG_RECOVERY", params)
	if built.get("status") != "PASS":
		return built
	var transport_result: Dictionary = {
		"status": "NOT_AVAILABLE",
		"reason": "BRIDGE_NOT_READY_NO_LIVE_BACKEND",
	}
	var submitted: bool = false
	if bridge.connection_state().get("state") == AndromedaRuntimeBridge.STATE_READY:
		transport_result = bridge.submit_command("REQUEST_BAG_RECOVERY", params)
		submitted = transport_result.get("status") == "PASS"
	_last_request = {
		"status": "PASS",
		"intent": "REQUEST_BAG_RECOVERY",
		"request_ref": request_ref,
		"bag_ref": bag.bag_ref,
		"target_ref": bag.target_ref,
		"request_source": request_source,
		"intent_envelope": built,
		"transport_result": transport_result,
		"transport_submitted": submitted,
		"bag_returned_locally": false,
		"contents_moved_locally": false,
		"ownership_mutated_locally": false,
		"authority": AUTHORITY,
	}
	_inflight_requests[bag.bag_ref] = _last_request.duplicate(true)
	recovery_request_prepared.emit(_last_request.duplicate(true))
	return _last_request.duplicate(true)


func _project_entry(entry: Dictionary, session_ref_value: String, sequence: int) -> Dictionary:
	var ref: String = str(entry.get("bag_ref", entry.get("target_ref", ""))).strip_edges()
	var original_owner_value: String = str(entry.get("original_owner_ref", entry.get("property_owner_ref", ""))).strip_edges()
	var state: String = str(entry.get("state", "")).to_upper()
	var bag: AndromedaDroppedBag = dropped_bag_for_ref(ref)
	if bag == null and state in AndromedaDroppedBag.TERMINAL_PRESENTATION_STATES:
		_tombstones[ref] = {
			"bag_ref": ref,
			"original_owner_ref": original_owner_value,
			"state": state,
			"session_ref": session_ref_value,
			"snapshot_sequence": sequence,
			"active": false,
		}
		return {"status": "PASS", "bag_ref": ref, "tombstone_only": true, "authority": AUTHORITY}
	if bag == null:
		bag = DROPPED_BAG_SCENE.instantiate() as AndromedaDroppedBag
		if bag == null:
			return _rejected("DROPPED_BAG_SCENE_INSTANTIATION_FAILED")
		var identity: Dictionary = bag.configure_identity(
			ref,
			original_owner_value,
			entry.get("context_metadata", entry.get("origin_context", {})) as Dictionary
		)
		if identity.get("status") != "PASS":
			bag.free()
			return identity
		bag.name = "DroppedBag_%s" % _safe_node_fragment(ref)
		bag.position = _position_from_entry(entry)
		bag.set_meta("b10_snapshot_spawned", true)
		_bag_root.add_child(bag)
		var registration: Dictionary = register_dropped_bag(bag)
		if registration.get("status") != "PASS":
			bag.queue_free()
			return registration
	var projection: Dictionary = bag.apply_authoritative_projection(entry, session_ref_value, sequence)
	if projection.get("status") != "PASS":
		return projection
	bag.global_position = _position_from_entry(entry, bag.global_position)
	if state in AndromedaDroppedBag.TERMINAL_PRESENTATION_STATES:
		_tombstones[ref] = bag.presentation_snapshot()
		_pending_approach.erase(ref)
		_inflight_requests.erase(ref)
		if _main_runtime != null:
			_main_runtime.clear_selection_if_target_ref(ref)
	return projection


func _preflight_entry(entry: Dictionary) -> Dictionary:
	var ref: String = str(entry.get("bag_ref", entry.get("target_ref", ""))).strip_edges()
	var original_owner_value: String = str(entry.get("original_owner_ref", entry.get("property_owner_ref", ""))).strip_edges()
	if ref.is_empty():
		return _rejected("BAG_REF_REQUIRED")
	if original_owner_value.is_empty():
		return _rejected("ORIGINAL_OWNER_REF_REQUIRED")
	if str(entry.get("state", "")).to_upper() not in (
		AndromedaDroppedBag.ACTIVE_PRESENTATION_STATES + AndromedaDroppedBag.TERMINAL_PRESENTATION_STATES
	):
		return _rejected("INVALID_DROPPED_BAG_STATE")
	if not entry.get("contents_summary", []) is Array:
		return _rejected("INVALID_DROPPED_BAG_CONTENTS_SUMMARY")
	return {"status": "PASS", "authority": AUTHORITY}


func _remove_missing_external_refs(refs_seen: Dictionary, sequence: int) -> void:
	for ref_value: Variant in _registered_bags.keys().duplicate():
		var ref: String = str(ref_value)
		if refs_seen.has(ref):
			continue
		var bag: AndromedaDroppedBag = dropped_bag_for_ref(ref)
		if bag == null or not bool(bag.get_meta("b10_snapshot_spawned", false)):
			continue
		_tombstones[ref] = {
			"bag_ref": ref,
			"original_owner_ref": bag.original_owner_ref,
			"state": AndromedaDroppedBag.STATE_REMOVED,
			"snapshot_sequence": sequence,
			"externally_absent_from_complete_projection": true,
		}
		if _main_runtime != null:
			_main_runtime.clear_selection_if_target_ref(ref)
		_registered_bags.erase(ref)
		_pending_approach.erase(ref)
		_inflight_requests.erase(ref)
		bag.queue_free()


func _position_from_entry(entry: Dictionary, fallback: Vector3 = Vector3.ZERO) -> Vector3:
	var position_value: Variant = entry.get("position", entry.get("drop_position", {}))
	if not position_value is Dictionary:
		return fallback
	var position_data: Dictionary = position_value
	for key: String in ["iso_x_m", "iso_y_m", "altitude_m"]:
		var value: Variant = position_data.get(key)
		if typeof(value) not in [TYPE_INT, TYPE_FLOAT] or typeof(value) == TYPE_BOOL or not is_finite(float(value)):
			return fallback
	return Vector3(
		float(position_data.get("iso_x_m")),
		float(position_data.get("altitude_m")),
		float(position_data.get("iso_y_m"))
	)


func _validate_external(payload: Dictionary, label: String) -> Dictionary:
	if payload.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_%s" % label)
	var session: AndromedaClientSession = _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	var ref: String = str(payload.get("session_ref", "")).strip_edges()
	if ref != session.session_ref():
		return _rejected("SESSION_MISMATCH")
	if not _snapshot_session_ref.is_empty() and ref != _snapshot_session_ref:
		return _rejected("DROPPED_BAG_PROJECTION_SESSION_MISMATCH")
	return {"status": "PASS", "authority": AUTHORITY}


func _on_bridge_snapshot_applied(snapshot: Dictionary) -> void:
	var entries_value: Variant = snapshot.get("dropped_bags", null)
	if not entries_value is Array:
		return
	project_dropped_bag_snapshot({
		"server_authoritative": snapshot.get("server_authoritative"),
		"session_ref": snapshot.get("session_ref"),
		"snapshot_sequence": snapshot.get(
			"presentation_sequence", snapshot.get("snapshot_sequence")
		),
		"dropped_bags": (entries_value as Array).duplicate(true),
		"complete_projection": true,
	})


func _on_bridge_command_result_received(result: Dictionary) -> void:
	if str(result.get("command", "")).strip_edges().to_upper() == "REQUEST_BAG_RECOVERY":
		project_recovery_result(result)


func _discover_scene_bags() -> void:
	if get_tree() == null:
		return
	for node: Node in get_tree().get_nodes_in_group("andromeda_dropped_bag"):
		if node is AndromedaDroppedBag:
			var bag := node as AndromedaDroppedBag
			if not bag.bag_ref.is_empty() and dropped_bag_for_ref(bag.bag_ref) == null:
				register_dropped_bag(bag)


func _on_session_bound(session_ref_value: String, _session_epoch: int) -> void:
	if not _snapshot_session_ref.is_empty() and _snapshot_session_ref != session_ref_value:
		_clear_previous_session_projections(session_ref_value)
	_snapshot_session_ref = ""
	_last_snapshot_sequence = -1
	_result_sequences.clear()
	_pending_approach.clear()
	_inflight_requests.clear()


func _on_session_revoked(_previous_session_ref: String, _session_epoch: int) -> void:
	_pending_approach.clear()
	_inflight_requests.clear()


func _clear_previous_session_projections(next_session_ref: String) -> void:
	for ref_value: Variant in _registered_bags.keys().duplicate():
		var ref: String = str(ref_value)
		var bag: AndromedaDroppedBag = dropped_bag_for_ref(ref)
		if bag == null:
			_registered_bags.erase(ref)
			continue
		if (
			bool(bag.get_meta("b10_snapshot_spawned", false))
			and not bag.projection_session_ref().is_empty()
			and bag.projection_session_ref() != next_session_ref
		):
			_registered_bags.erase(ref)
			bag.queue_free()
	_tombstones.clear()
	_systemic_references.clear()


func _safe_node_fragment(value: String) -> String:
	var output: String = ""
	for character: String in value:
		output += character if character.is_valid_identifier() and character.length() == 1 else "_"
	return output


func _bridge() -> AndromedaRuntimeBridge:
	return get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge


func _session() -> AndromedaClientSession:
	return get_node_or_null("/root/ClientSession") as AndromedaClientSession


func _rejected(reason: String, detail: Dictionary = {}) -> Dictionary:
	var result := {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
	result.merge(detail, true)
	return result
