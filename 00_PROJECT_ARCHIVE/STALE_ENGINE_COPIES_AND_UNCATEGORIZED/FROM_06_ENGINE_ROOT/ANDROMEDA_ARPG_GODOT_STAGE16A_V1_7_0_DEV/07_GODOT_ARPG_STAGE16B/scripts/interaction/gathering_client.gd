extends Node
class_name AndromedaGatheringClient

## B08 client orchestration for resource interaction and externally confirmed physical output.
## Stage16A/Living remains authoritative for tools, work, yield, stamina, depletion,
## respawn and inventory. This component only guards local approach and projects results.

signal gather_request_prepared(result: Dictionary)
signal gather_feedback_projected(result: Dictionary)
signal physical_output_projected(result: Dictionary)
signal resource_stream_projection_changed(result: Dictionary)

const AUTHORITY := "GODOT_GATHERING_CLIENT_ORCHESTRATION_ONLY"
const RESOURCE_NODE_SCENE: PackedScene = preload("res://scenes/interaction/ResourceNode.tscn")
const RESOURCE_SOURCE_KINDS: Array[String] = ["TREE", "ROCK", "ORE", "FLORA", "AGRICULTURE"]
const UNIVERSAL_B08_OUTPUT_SOURCES: Array[String] = [
	"TREE", "ROCK", "ORE", "FLORA", "AGRICULTURE", "HUNTING", "FISHING", "ENEMY",
]
const BLOCKER_MASK := 1 | 128

var _main_runtime: AndromedaMainRuntime
var _player: AndromedaPlayerController
var _hud: AndromedaHUDController
var _resource_root: Node3D
var _ground_loot_client: AndromedaGroundLootPickupClient
var _streaming_manager: AndromedaStreamingManager
var _registered_resources: Dictionary = {}
var _resource_tombstones: Dictionary = {}
var _pending_approach: Dictionary = {}
var _inflight_requests: Dictionary = {}
var _request_result_sequences: Dictionary = {}
var _processed_output_events: Dictionary = {}
var _last_resource_snapshot_sequence: int = -1
var _resource_snapshot_session_ref: String = ""
var _last_output_event_sequence: int = -1
var _last_output_session_ref: String = ""
var _last_stamina_projection_sequence: int = -1
var _last_request: Dictionary = {}
var _request_history: Array[Dictionary] = []
var _request_serial: int = 0
var _bound: bool = false


func _ready() -> void:
	process_physics_priority = 80


func _physics_process(_delta: float) -> void:
	if not _bound:
		return
	_discover_scene_resources()
	process_pending_approach_once()


func bind_runtime(
	main_runtime_value: AndromedaMainRuntime,
	player_value: AndromedaPlayerController,
	hud_value: AndromedaHUDController,
	resource_root_value: Node3D,
	ground_loot_client_value: AndromedaGroundLootPickupClient,
	streaming_manager_value: AndromedaStreamingManager
) -> Dictionary:
	if (
		main_runtime_value == null
		or player_value == null
		or hud_value == null
		or resource_root_value == null
		or ground_loot_client_value == null
		or streaming_manager_value == null
	):
		return _rejected("MAIN_PLAYER_HUD_RESOURCE_LOOT_STREAMING_REQUIRED")
	_main_runtime = main_runtime_value
	_player = player_value
	_hud = hud_value
	_resource_root = resource_root_value
	_ground_loot_client = ground_loot_client_value
	_streaming_manager = streaming_manager_value
	_discover_scene_resources()
	if not _bound:
		var session := _session()
		if session != null:
			if not session.session_bound.is_connected(_on_session_bound):
				session.session_bound.connect(_on_session_bound)
			if not session.session_revoked.is_connected(_on_session_revoked):
				session.session_revoked.connect(_on_session_revoked)
		var bridge := _bridge()
		if bridge != null:
			if not bridge.snapshot_applied.is_connected(_on_bridge_snapshot_applied):
				bridge.snapshot_applied.connect(_on_bridge_snapshot_applied)
			if not bridge.command_result_received.is_connected(_on_bridge_command_result_received):
				bridge.command_result_received.connect(_on_bridge_command_result_received)
		_bound = true
	return {
		"status": "PASS",
		"registered_resource_count": registered_resource_count(),
		"living_macro_ref": str(_streaming_manager.state_snapshot().get("living_macro_ref", "")),
		"authority": AUTHORITY,
	}


func register_resource(resource: AndromedaResourceNode) -> Dictionary:
	if resource == null or not is_instance_valid(resource):
		return _rejected("RESOURCE_NODE_INSTANCE_REQUIRED")
	var target_ref_value: String = resource.target_ref.strip_edges()
	if target_ref_value.is_empty():
		return _rejected("EMPTY_RESOURCE_TARGET_REF")
	if resource.resource_kind not in RESOURCE_SOURCE_KINDS:
		return _rejected("UNSUPPORTED_RESOURCE_KIND")
	if _registered_resources.has(target_ref_value):
		var existing: Variant = _registered_resources[target_ref_value]
		if is_instance_valid(existing) and existing != resource:
			return _rejected("DUPLICATE_ACTIVE_RESOURCE_TARGET_REF")
		_registered_resources[target_ref_value] = resource
		return {
			"status": "PASS",
			"target_ref": target_ref_value,
			"idempotent": true,
			"authority": AUTHORITY,
		}
	_registered_resources[target_ref_value] = resource
	return {
		"status": "PASS",
		"target_ref": target_ref_value,
		"idempotent": false,
		"authority": AUTHORITY,
	}


func resource_for_ref(target_ref_value: String) -> AndromedaResourceNode:
	var normalized_ref: String = target_ref_value.strip_edges()
	var value: Variant = _registered_resources.get(normalized_ref)
	if not is_instance_valid(value):
		_registered_resources.erase(normalized_ref)
		return null
	return value as AndromedaResourceNode


func registered_resource_count() -> int:
	var count: int = 0
	for target_ref_value: Variant in _registered_resources.keys():
		if resource_for_ref(str(target_ref_value)) != null:
			count += 1
	return count


func handle_manual_resource_intent(
	resolved: Dictionary,
	target: AndromedaInteractionTarget
) -> Dictionary:
	if resolved.get("status") != "PASS":
		return _rejected("POINTER_INTENT_NOT_PASS")
	if str(resolved.get("intent", "")).strip_edges().to_upper() != "APPROACH_HARVEST":
		return _rejected("UNSUPPORTED_RESOURCE_POINTER_INTENT")
	if not target is AndromedaResourceNode:
		return _rejected("SPECIALIZED_RESOURCE_NODE_REQUIRED")
	var resource := target as AndromedaResourceNode
	if str(resolved.get("target_ref", "")).strip_edges() != resource.target_ref:
		return _rejected("RESOURCE_TARGET_REF_MISMATCH")
	return begin_gather_interaction(resource, "RIGHT_CLICK")


func handle_selected_interaction(target: AndromedaInteractionTarget) -> Dictionary:
	if not target is AndromedaResourceNode:
		return _rejected("SELECTED_TARGET_NOT_RESOURCE_NODE")
	return begin_gather_interaction(target as AndromedaResourceNode, "CONTEXT_KEY_E")


func begin_gather_interaction(resource: AndromedaResourceNode, request_source: String) -> Dictionary:
	var registration: Dictionary = register_resource(resource)
	if registration.get("status") != "PASS":
		return registration
	var base_validation: Dictionary = _validate_resource_state(resource)
	if base_validation.get("status") != "PASS":
		_present_blocked(resource, str(base_validation.get("reason", "INTERACTION_BLOCKED")))
		return base_validation
	var physical_distance_m: float = _physical_distance_to(resource)
	if physical_distance_m <= resource.interaction_range_m:
		return _prepare_gather_request(resource, request_source)
	var approach_destination: Vector3 = approach_destination_for(resource)
	var path_validation: Dictionary = _player.validate_destination(approach_destination)
	if path_validation.get("status") != "PASS":
		_present_blocked(resource, "RESOURCE_PATH_INVALID")
		return _rejected("RESOURCE_PATH_INVALID", {"path_result": path_validation})
	var movement: Dictionary = _player.request_move(approach_destination)
	if movement.get("status") != "PASS":
		_present_blocked(resource, "RESOURCE_APPROACH_REJECTED")
		return _rejected("RESOURCE_APPROACH_REJECTED", {"movement_result": movement})
	_pending_approach.clear()
	_pending_approach[resource.target_ref] = {
		"target_ref": resource.target_ref,
		"instance_id": resource.get_instance_id(),
		"request_source": request_source,
		"selection_ref_at_start": _main_runtime.selected_target_ref() if _main_runtime != null else "",
		"approach_destination": approach_destination,
	}
	_observe_gathering_action(true)
	resource.present_client_feedback("GATHER_REQUESTED", false)
	return {
		"status": "PASS",
		"intent": "APPROACH_GATHERING_PENDING",
		"target_ref": resource.target_ref,
		"resource_kind": resource.resource_kind,
		"physical_distance_m": physical_distance_m,
		"interaction_range_m": resource.interaction_range_m,
		"approach_destination": approach_destination,
		"movement_result": movement,
		"gather_requested": false,
		"remote_gathering": false,
		"authority": AUTHORITY,
	}


func process_pending_approach_once() -> Dictionary:
	if _pending_approach.is_empty():
		return {"status": "PASS", "pending": false, "authority": AUTHORITY}
	var target_ref_value: String = str(_pending_approach.keys()[0])
	var resource: AndromedaResourceNode = resource_for_ref(target_ref_value)
	if resource == null:
		_pending_approach.clear()
		_observe_gathering_action(false)
		return _rejected("STALE_OR_REMOVED_RESOURCE_TARGET")
	var validation: Dictionary = evaluate_gather_candidate(resource)
	if validation.get("status") == "PASS":
		var request_source: String = str(_pending_approach[target_ref_value].get("request_source", "UNKNOWN"))
		_pending_approach.clear()
		return _prepare_gather_request(resource, "%s_AFTER_APPROACH" % request_source)
	var reason: String = str(validation.get("reason", ""))
	if reason == "GATHER_DISTANCE_EXCEEDED":
		return {
			"status": "PASS",
			"pending": true,
			"reason": reason,
			"target_ref": target_ref_value,
			"authority": AUTHORITY,
		}
	_pending_approach.clear()
	_observe_gathering_action(false)
	_present_blocked(resource, reason)
	return validation


func evaluate_gather_candidate(resource: AndromedaResourceNode) -> Dictionary:
	if _player == null:
		return _rejected("PLAYER_NOT_BOUND")
	if resource == null or not is_instance_valid(resource) or not resource.is_inside_tree():
		return _rejected("STALE_OR_REMOVED_RESOURCE_TARGET")
	if resource_for_ref(resource.target_ref) != resource:
		return _rejected("WRONG_OR_UNREGISTERED_RESOURCE_TARGET")
	var state_validation: Dictionary = _validate_resource_state(resource)
	if state_validation.get("status") != "PASS":
		return state_validation
	var physical_distance_m: float = _physical_distance_to(resource)
	if not is_finite(physical_distance_m) or physical_distance_m > resource.interaction_range_m:
		return _rejected("GATHER_DISTANCE_EXCEEDED", {
			"physical_distance_m": physical_distance_m,
			"interaction_range_m": resource.interaction_range_m,
		})
	var blocker_result: Dictionary = blocker_probe(resource)
	if blocker_result.get("blocked") == true:
		return _rejected("GATHER_BLOCKED_BY_COLLISION", {"blocker_result": blocker_result})
	var approach_destination: Vector3 = approach_destination_for(resource)
	var path_validation: Dictionary = _player.validate_destination(approach_destination)
	if path_validation.get("status") != "PASS":
		return _rejected("RESOURCE_PATH_INVALID", {"path_result": path_validation})
	return {
		"status": "PASS",
		"target_ref": resource.target_ref,
		"resource_kind": resource.resource_kind,
		"physical_distance_m": physical_distance_m,
		"interaction_range_m": resource.interaction_range_m,
		"blocker_clear": true,
		"path_valid": true,
		"authority": AUTHORITY,
	}


func approach_destination_for(resource: AndromedaResourceNode) -> Vector3:
	if _player == null or resource == null:
		return Vector3.ZERO
	var target_position: Vector3 = resource.interaction_anchor_world_position()
	var away := Vector2(_player.global_position.x - target_position.x, _player.global_position.z - target_position.z)
	if away.length_squared() <= 0.000001:
		away = Vector2.RIGHT
	away = away.normalized()
	var stand_off: float = maxf(0.2, resource.interaction_range_m * 0.72)
	return Vector3(
		target_position.x + away.x * stand_off,
		target_position.y,
		target_position.z + away.y * stand_off
	)


func blocker_probe(resource: AndromedaResourceNode) -> Dictionary:
	if _player == null or resource == null or not is_instance_valid(resource):
		return _rejected("PLAYER_AND_RESOURCE_REQUIRED")
	var world: World3D = _player.get_world_3d()
	if world == null:
		return _rejected("WORLD_3D_REQUIRED")
	var ray_start: Vector3 = _player.global_position + Vector3(0.0, 0.55, 0.0)
	var ray_end: Vector3 = resource.interaction_anchor_world_position() + Vector3(0.0, 0.55, 0.0)
	var query := PhysicsRayQueryParameters3D.create(ray_start, ray_end, BLOCKER_MASK, [_player.get_rid()])
	query.collide_with_areas = false
	query.collide_with_bodies = true
	var hit: Dictionary = world.direct_space_state.intersect_ray(query)
	var collider := hit.get("collider") as CollisionObject3D
	return {
		"status": "PASS",
		"blocked": not hit.is_empty(),
		"collider_name": str(collider.name) if collider != null else "",
		"collision_layer": collider.collision_layer if collider != null else 0,
		"authority": AUTHORITY,
	}


func project_resource_snapshot(snapshot: Dictionary) -> Dictionary:
	var envelope_validation: Dictionary = _validate_external_envelope(snapshot, "RESOURCE_SNAPSHOT")
	if envelope_validation.get("status") != "PASS":
		return envelope_validation
	var session_ref_value: String = str(snapshot.get("session_ref", "")).strip_edges()
	var sequence_value: Variant = snapshot.get("snapshot_sequence", null)
	if typeof(sequence_value) != TYPE_INT or int(sequence_value) < 0:
		return _rejected("INVALID_RESOURCE_SNAPSHOT_SEQUENCE")
	if not _resource_snapshot_session_ref.is_empty() and session_ref_value != _resource_snapshot_session_ref:
		return _rejected("RESOURCE_SNAPSHOT_SESSION_MISMATCH")
	if int(sequence_value) <= _last_resource_snapshot_sequence:
		return _rejected("STALE_OR_DUPLICATE_RESOURCE_SNAPSHOT")
	var entries_value: Variant = snapshot.get("resources", [])
	if not entries_value is Array:
		return _rejected("INVALID_RESOURCE_SNAPSHOT_LIST")
	for entry_value: Variant in entries_value:
		if not entry_value is Dictionary:
			return _rejected("INVALID_RESOURCE_SNAPSHOT_ENTRY")
		var preflight: Dictionary = _preflight_resource_entry(entry_value as Dictionary)
		if preflight.get("status") != "PASS":
			return preflight
	var projected: Array[Dictionary] = []
	for entry_value: Variant in entries_value:
		var result: Dictionary = _project_resource_entry(
			entry_value as Dictionary,
			session_ref_value,
			int(sequence_value)
		)
		if result.get("status") != "PASS":
			return result
		projected.append(result)
	_resource_snapshot_session_ref = session_ref_value
	_last_resource_snapshot_sequence = int(sequence_value)
	return {
		"status": "PASS",
		"snapshot_sequence": _last_resource_snapshot_sequence,
		"projected": projected,
		"depletion_decided_locally": false,
		"respawn_scheduled_locally": false,
		"authority": AUTHORITY,
	}


func project_resource_stream_phase(
	target_ref_value: String,
	next_phase: String,
	session_ref_value: String,
	sequence: int,
	externally_confirmed: bool = false
) -> Dictionary:
	if not externally_confirmed:
		return _rejected("EXTERNAL_STREAM_PHASE_CONFIRMATION_REQUIRED")
	var session_validation: Dictionary = _validate_session_ref(session_ref_value)
	if session_validation.get("status") != "PASS":
		return session_validation
	var resource: AndromedaResourceNode = resource_for_ref(target_ref_value)
	if resource == null:
		return _rejected("RESOURCE_TARGET_NOT_FOUND")
	var result: Dictionary = resource.project_stream_phase(
		next_phase,
		session_ref_value,
		sequence,
		true
	)
	if result.get("status") == "PASS":
		if resource.stream_phase() != AndromedaResourceNode.STREAM_ACTIVE:
			_pending_approach.erase(resource.target_ref)
			if _main_runtime != null:
				_main_runtime.clear_selection_if_target_ref(resource.target_ref)
		result["living_macro_ref"] = str(_streaming_manager.state_snapshot().get("living_macro_ref", ""))
		result["systemic_state_source"] = "EXTERNAL_LIVING_REFERENCE_ONLY"
		resource_stream_projection_changed.emit(result.duplicate(true))
	return result


func project_gathering_result(result: Dictionary) -> Dictionary:
	var envelope_validation: Dictionary = _validate_external_envelope(result, "GATHERING_RESULT")
	if envelope_validation.get("status") != "PASS":
		return envelope_validation
	var target_ref_value: String = str(result.get("target_ref", "")).strip_edges()
	var resource: AndromedaResourceNode = resource_for_ref(target_ref_value)
	if resource == null:
		return _rejected("GATHERING_RESULT_TARGET_NOT_FOUND")
	var sequence_value: Variant = result.get("result_sequence", null)
	if typeof(sequence_value) != TYPE_INT or int(sequence_value) < 0:
		return _rejected("INVALID_GATHERING_RESULT_SEQUENCE")
	var last_sequence: int = int(_request_result_sequences.get(target_ref_value, -1))
	if int(sequence_value) <= last_sequence:
		return _rejected("STALE_OR_DUPLICATE_GATHERING_RESULT")
	var status_value: String = str(result.get("status", "REJECTED")).strip_edges().to_upper()
	if status_value not in ["PASS", "REJECTED"]:
		return _rejected("UNSUPPORTED_GATHERING_RESULT_STATUS")
	_request_result_sequences[target_ref_value] = int(sequence_value)
	_pending_approach.erase(target_ref_value)
	_inflight_requests.erase(target_ref_value)
	_observe_gathering_action(false)
	var token: String = "GATHER_ACCEPTED" if status_value == "PASS" else "GATHER_REJECTED"
	var feedback: Dictionary = resource.present_client_feedback(token, true)
	if status_value != "PASS" and _hud != null:
		feedback["hud_feedback"] = _hud.present_combat_event({
			"token": "INTERACTION_BLOCKED",
			"target_ref": target_ref_value,
			"confirmed_externally": true,
		})
	var projected := {
		"status": "PASS",
		"authoritative_result_status": status_value,
		"target_ref": target_ref_value,
		"result_sequence": int(sequence_value),
		"feedback": feedback,
		"output_spawned": false,
		"yield_calculated_locally": false,
		"inventory_mutated": false,
		"authority": AUTHORITY,
	}
	gather_feedback_projected.emit(projected.duplicate(true))
	return projected


func project_physical_output_event(event: Dictionary) -> Dictionary:
	var envelope_validation: Dictionary = _validate_external_envelope(event, "PHYSICAL_OUTPUT_EVENT")
	if envelope_validation.get("status") != "PASS":
		return envelope_validation
	for forbidden_field: String in ["inventory_grant", "inventory_delta", "grant", "direct_inventory"]:
		if event.has(forbidden_field):
			return _rejected("DIRECT_INVENTORY_OUTPUT_FORBIDDEN")
	var session_ref_value: String = str(event.get("session_ref", "")).strip_edges()
	if not _last_output_session_ref.is_empty() and session_ref_value != _last_output_session_ref:
		return _rejected("PHYSICAL_OUTPUT_SESSION_MISMATCH")
	var event_ref: String = str(event.get("event_ref", "")).strip_edges()
	if event_ref.is_empty():
		return _rejected("EMPTY_PHYSICAL_OUTPUT_EVENT_REF")
	if _processed_output_events.has(event_ref):
		return _rejected("DUPLICATE_PHYSICAL_OUTPUT_EVENT")
	var sequence_value: Variant = event.get("event_sequence", null)
	if typeof(sequence_value) != TYPE_INT or int(sequence_value) < 0:
		return _rejected("INVALID_PHYSICAL_OUTPUT_EVENT_SEQUENCE")
	if int(sequence_value) <= _last_output_event_sequence:
		return _rejected("STALE_PHYSICAL_OUTPUT_EVENT")
	var source_kind: String = str(event.get("source_kind", "")).strip_edges().to_upper()
	if source_kind not in UNIVERSAL_B08_OUTPUT_SOURCES:
		return _rejected("UNSUPPORTED_B08_OUTPUT_SOURCE")
	var source_ref: String = str(event.get("source_ref", "")).strip_edges()
	var source_resource: AndromedaResourceNode
	if source_kind in RESOURCE_SOURCE_KINDS:
		source_resource = resource_for_ref(source_ref)
		if source_resource == null:
			return _rejected("RESOURCE_OUTPUT_SOURCE_NOT_FOUND")
		if source_resource.resource_kind != source_kind:
			return _rejected("RESOURCE_OUTPUT_SOURCE_KIND_MISMATCH")
	var outputs_value: Variant = event.get("outputs", [])
	if not outputs_value is Array:
		return _rejected("INVALID_PHYSICAL_OUTPUT_LIST")
	var output_refs: Dictionary = {}
	for output_value: Variant in outputs_value:
		if not output_value is Dictionary:
			return _rejected("INVALID_PHYSICAL_OUTPUT_ENTRY")
		var output: Dictionary = output_value
		var drop_ref: String = str(output.get("target_ref", output.get("drop_ref", ""))).strip_edges()
		if drop_ref.is_empty():
			return _rejected("EMPTY_PHYSICAL_OUTPUT_TARGET_REF")
		if output_refs.has(drop_ref):
			return _rejected("DUPLICATE_OUTPUT_TARGET_REF_IN_EVENT")
		output_refs[drop_ref] = true
		var quantity_value: Variant = output.get("quantity", null)
		if typeof(quantity_value) != TYPE_INT or typeof(quantity_value) == TYPE_BOOL or int(quantity_value) <= 0:
			return _rejected("INVALID_EXTERNAL_OUTPUT_QUANTITY")
		if str(output.get("item_kind", "")).strip_edges().is_empty():
			return _rejected("EMPTY_EXTERNAL_OUTPUT_ITEM_KIND")
	var projected: Array = []
	if not (outputs_value as Array).is_empty():
		var loot_sequence_value: Variant = event.get("ground_loot_snapshot_sequence", null)
		if typeof(loot_sequence_value) != TYPE_INT or int(loot_sequence_value) < 0:
			return _rejected("INVALID_GROUND_LOOT_SNAPSHOT_SEQUENCE")
		var loot_entries: Array[Dictionary] = []
		for output_value: Variant in outputs_value:
			loot_entries.append(_ground_loot_entry_from_external_output(
				output_value as Dictionary,
				source_kind,
				source_ref,
				source_resource,
				event
			))
		var loot_projection: Dictionary = _ground_loot_client.project_ground_loot_snapshot({
			"server_authoritative": true,
			"session_ref": session_ref_value,
			"snapshot_sequence": int(loot_sequence_value),
			"ground_loot": loot_entries,
		})
		if loot_projection.get("status") != "PASS":
			return _rejected("GROUND_LOOT_PROJECTION_REJECTED", {"ground_loot_result": loot_projection})
		projected = loot_projection.get("projected", []) as Array
	_processed_output_events[event_ref] = {
		"event_ref": event_ref,
		"event_sequence": int(sequence_value),
		"source_kind": source_kind,
		"output_count": (outputs_value as Array).size(),
	}
	_last_output_event_sequence = int(sequence_value)
	_last_output_session_ref = session_ref_value
	if source_resource != null:
		source_resource.present_client_feedback("OUTPUT_PRODUCED", true)
	var result := {
		"status": "PASS",
		"event_ref": event_ref,
		"event_sequence": _last_output_event_sequence,
		"source_kind": source_kind,
		"source_ref": source_ref,
		"output_count": (outputs_value as Array).size(),
		"projected": projected,
		"ground_loot_before_inventory": true,
		"direct_inventory_delivery": false,
		"quantity_calculated_locally": false,
		"yield_calculated_locally": false,
		"inventory_mutated": false,
		"authority": AUTHORITY,
	}
	physical_output_projected.emit(result.duplicate(true))
	return result


func project_gathering_stamina_snapshot(snapshot: Dictionary) -> Dictionary:
	var envelope_validation: Dictionary = _validate_external_envelope(snapshot, "GATHERING_STAMINA")
	if envelope_validation.get("status") != "PASS":
		return envelope_validation
	var sequence_value: Variant = snapshot.get("stamina_sequence", null)
	if typeof(sequence_value) != TYPE_INT or int(sequence_value) < 0:
		return _rejected("INVALID_GATHERING_STAMINA_SEQUENCE")
	if int(sequence_value) <= _last_stamina_projection_sequence:
		return _rejected("STALE_OR_DUPLICATE_GATHERING_STAMINA")
	var fraction_value: Variant = snapshot.get("stamina_fraction", null)
	if not _valid_number(fraction_value) or float(fraction_value) < 0.0 or float(fraction_value) > 1.0:
		return _rejected("INVALID_GATHERING_STAMINA_FRACTION")
	_last_stamina_projection_sequence = int(sequence_value)
	var hud_result: Dictionary = _hud.project_stamina(
		float(fraction_value),
		str(snapshot.get("activity", "GATHERING")),
		"EXTERNAL_STAGE16A_GATHERING_SNAPSHOT"
	)
	return {
		"status": hud_result.get("status", "REJECTED"),
		"stamina_sequence": _last_stamina_projection_sequence,
		"hud_projection": hud_result,
		"stamina_subtracted_locally": false,
		"second_stamina_created": false,
		"authority": AUTHORITY,
	}


func pending_target_ref() -> String:
	return str(_pending_approach.keys()[0]) if not _pending_approach.is_empty() else ""


func inflight_request_count() -> int:
	return _inflight_requests.size()


func has_inflight_request(target_ref_value: String) -> bool:
	return _inflight_requests.has(target_ref_value.strip_edges())


func last_request() -> Dictionary:
	return _last_request.duplicate(true)


func request_history() -> Array[Dictionary]:
	return _request_history.duplicate(true)


func output_event_seen(event_ref: String) -> bool:
	return _processed_output_events.has(event_ref.strip_edges())


func resource_tombstone(target_ref_value: String) -> Dictionary:
	var value: Variant = _resource_tombstones.get(target_ref_value.strip_edges(), {})
	return value.duplicate(true) if value is Dictionary else {}


func clear_client_request_tracking() -> void:
	_pending_approach.clear()
	_inflight_requests.clear()
	_last_request.clear()
	_request_history.clear()
	_observe_gathering_action(false)


func contract_snapshot() -> Dictionary:
	return {
		"resource_scene_root": "StaticBody3D",
		"resource_source_kinds": RESOURCE_SOURCE_KINDS.duplicate(),
		"universal_b08_output_sources": UNIVERSAL_B08_OUTPUT_SOURCES.duplicate(),
		"flow": [
			"SELECT_RESOURCE", "APPROACH", "REQUEST_GATHER", "WAIT_EXTERNAL_RESULT",
			"PROJECT_EXTERNAL_OUTPUT", "GROUND_LOOT_B07",
		],
		"output_delivery": "GROUND_LOOT_B07_ONLY",
		"direct_inventory_delivery": false,
		"player_ref_supplied_by_client": false,
		"yield_authority": false,
		"quantity_authority": false,
		"tool_rule_authority": false,
		"stamina_authority": false,
		"depletion_authority": false,
		"respawn_authority": false,
		"inventory_authority": false,
		"xp_authority": false,
		"profession_authority": false,
		"economy_authority": false,
		"living_parallel_implementation": false,
		"backend_substitute": false,
		"invented_endpoint": false,
		"authority": AUTHORITY,
	}


func _prepare_gather_request(resource: AndromedaResourceNode, request_source: String) -> Dictionary:
	var eligibility: Dictionary = evaluate_gather_candidate(resource)
	if eligibility.get("status") != "PASS":
		_present_blocked(resource, str(eligibility.get("reason", "INTERACTION_BLOCKED")))
		return eligibility
	if _inflight_requests.has(resource.target_ref):
		return _rejected("GATHER_REQUEST_ALREADY_INFLIGHT", {
			"target_ref": resource.target_ref,
			"deduplicated": true,
		})
	var bridge := _bridge()
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	_request_serial += 1
	var request_ref := "B08-GATHER-REQUEST-%06d" % _request_serial
	var params := {
		"target_ref": resource.target_ref,
		"requested_units": 1,
	}
	var built: Dictionary = bridge.build_command_envelope("REQUEST_GATHER", params)
	if built.get("status") != "PASS":
		return built
	var transport_result: Dictionary = {
		"status": "NOT_AVAILABLE",
		"reason": "BRIDGE_NOT_READY_NO_LIVE_BACKEND",
	}
	var submitted: bool = false
	if bridge.connection_state().get("authority_session_bound") == true:
		var envelope: Dictionary = built.get("envelope", {}) as Dictionary
		transport_result = bridge.submit_command(
			"REQUEST_GATHER", params, str(envelope.get("command_ref", ""))
		)
		submitted = transport_result.get("status") == "PASS"
	_last_request = {
		"status": "PASS",
		"intent": "REQUEST_GATHER",
		"request_ref": request_ref,
		"target_ref": resource.target_ref,
		"resource_kind": resource.resource_kind,
		"request_source": request_source,
		"physical_distance_m": float(eligibility.get("physical_distance_m", INF)),
		"interaction_range_m": resource.interaction_range_m,
		"intent_envelope": built,
		"transport_result": transport_result,
		"transport_submitted": submitted,
		"player_ref_supplied": false,
		"yield_calculated_locally": false,
		"stamina_mutated_locally": false,
		"inventory_mutated": false,
		"authority": AUTHORITY,
	}
	_pending_approach.erase(resource.target_ref)
	_inflight_requests[resource.target_ref] = _last_request.duplicate(true)
	_request_history.append(_last_request.duplicate(true))
	_observe_gathering_action(true)
	resource.present_client_feedback("GATHER_REQUESTED", false)
	gather_request_prepared.emit(_last_request.duplicate(true))
	return _last_request.duplicate(true)


func _validate_resource_state(resource: AndromedaResourceNode) -> Dictionary:
	if resource == null or not is_instance_valid(resource):
		return _rejected("RESOURCE_NODE_REQUIRED")
	if resource_for_ref(resource.target_ref) != resource:
		return _rejected("WRONG_OR_UNREGISTERED_RESOURCE_TARGET")
	return resource.can_prepare_gather_intent()


func _physical_distance_to(resource: AndromedaResourceNode) -> float:
	return _player.global_position.distance_to(resource.interaction_anchor_world_position())


func _project_resource_entry(entry: Dictionary, session_ref_value: String, sequence: int) -> Dictionary:
	var target_ref_value: String = str(entry.get("target_ref", "")).strip_edges()
	var state_value: String = str(entry.get("state", "")).strip_edges().to_upper()
	var resource: AndromedaResourceNode = resource_for_ref(target_ref_value)
	if resource == null and state_value == "REMOVED":
		_resource_tombstones[target_ref_value] = {
			"target_ref": target_ref_value,
			"state": "REMOVED",
			"session_ref": session_ref_value,
			"snapshot_sequence": sequence,
		}
		return {
			"status": "PASS",
			"target_ref": target_ref_value,
			"tombstone_only": true,
			"authority": AUTHORITY,
		}
	if resource == null:
		resource = RESOURCE_NODE_SCENE.instantiate() as AndromedaResourceNode
		if resource == null:
			return _rejected("RESOURCE_NODE_SCENE_INSTANTIATION_FAILED")
		resource.target_ref = target_ref_value
		resource.target_kind = AndromedaInputRouter.HIT_GATHER_NODE
		resource.resource_kind = str(entry.get("resource_kind", "")).strip_edges().to_upper()
		resource.display_name = str(entry.get("display_name", "%s Placeholder" % resource.resource_kind))
		resource.position = _resource_presentation_position(entry)
		resource.name = "Resource_%s" % _safe_node_fragment(target_ref_value)
		resource.set_meta("b08_snapshot_spawned", true)
		_resource_root.add_child(resource)
		var registration: Dictionary = register_resource(resource)
		if registration.get("status") != "PASS":
			resource.queue_free()
			return registration
	var projection_entry: Dictionary = entry.duplicate(true)
	projection_entry["server_authoritative"] = true
	var state_result: Dictionary = resource.apply_authoritative_projection(
		projection_entry,
		session_ref_value,
		sequence,
		true
	)
	if state_result.get("status") != "PASS":
		return state_result
	if entry.has("stream_phase"):
		var stream_result: Dictionary = resource.project_stream_phase(
			str(entry.get("stream_phase", "ACTIVE")),
			session_ref_value,
			sequence,
			true
		)
		if stream_result.get("status") != "PASS":
			return stream_result
		state_result["stream_projection"] = stream_result
	if resource.projected_state() == AndromedaResourceNode.STATE_REMOVED:
		_resource_tombstones[target_ref_value] = resource.presentation_snapshot()
		_registered_resources.erase(target_ref_value)
		_pending_approach.erase(target_ref_value)
		_inflight_requests.erase(target_ref_value)
		if _main_runtime != null:
			_main_runtime.clear_selection_if_target_ref(target_ref_value)
		resource.queue_free()
		state_result["removed_from_scene"] = true
	return state_result


func _preflight_resource_entry(entry: Dictionary) -> Dictionary:
	var target_ref_value: String = str(entry.get("target_ref", "")).strip_edges()
	if target_ref_value.is_empty():
		return _rejected("EMPTY_RESOURCE_TARGET_REF")
	var state_value: String = str(entry.get("state", "")).strip_edges().to_upper()
	if state_value not in ["ACTIVE", "AVAILABLE", "BUSY", "IN_PROGRESS", "DEPLETED", "UNAVAILABLE", "REMOVED"]:
		return _rejected("UNSUPPORTED_RESOURCE_STATE")
	var resource_kind_value: String = str(entry.get("resource_kind", "")).strip_edges().to_upper()
	var existing: AndromedaResourceNode = resource_for_ref(target_ref_value)
	if resource_kind_value.is_empty() and existing != null:
		resource_kind_value = existing.resource_kind
	if state_value != "REMOVED" and resource_kind_value not in RESOURCE_SOURCE_KINDS:
		return _rejected("UNSUPPORTED_RESOURCE_KIND")
	if existing != null and not resource_kind_value.is_empty() and existing.resource_kind != resource_kind_value:
		return _rejected("RESOURCE_KIND_MISMATCH")
	if entry.has("stream_phase") and str(entry.get("stream_phase", "")).strip_edges().to_upper() not in ["ACTIVE", "PRELOAD", "SYSTEMIC"]:
		return _rejected("UNSUPPORTED_RESOURCE_STREAM_PHASE")
	return {"status": "PASS", "authority": AUTHORITY}


func _ground_loot_entry_from_external_output(
	output: Dictionary,
	source_kind: String,
	source_ref: String,
	source_resource: AndromedaResourceNode,
	event: Dictionary
) -> Dictionary:
	var spawn_position: Vector3
	if source_resource != null:
		spawn_position = source_resource.drop_anchor_world_position()
	else:
		spawn_position = _position_from_dictionary(event.get("authorized_position", {}), Vector3.ZERO)
	return {
		"target_ref": str(output.get("target_ref", output.get("drop_ref", ""))).strip_edges(),
		"source_ref": source_ref,
		"source_kind": source_kind,
		"item_ref": str(output.get("item_ref", "")).strip_edges(),
		"item_kind": str(output.get("item_kind", "MATERIAL")).strip_edges().to_upper(),
		"quantity": int(output.get("quantity", 0)),
		"state": str(output.get("state", "ACTIVE")).strip_edges().to_upper(),
		"settled": bool(output.get("settled", false)),
		"reachable": bool(output.get("reachable", true)),
		"water_exposure_s": float(output.get("water_exposure_s", 0.0)),
		"candidate_position": _position_dictionary(spawn_position),
	}


func _validate_external_envelope(payload: Dictionary, kind: String) -> Dictionary:
	if payload.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_%s" % kind)
	return _validate_session_ref(str(payload.get("session_ref", "")))


func _validate_session_ref(session_ref_value: String) -> Dictionary:
	var session := _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	if session_ref_value.strip_edges() != session.session_ref():
		return _rejected("SESSION_MISMATCH")
	return {"status": "PASS", "authority": AUTHORITY}


func _position_dictionary(position_value: Vector3) -> Dictionary:
	return {
		"iso_x_m": position_value.x,
		"iso_y_m": position_value.z,
		"altitude_m": position_value.y,
	}


func _position_from_dictionary(value: Variant, fallback: Vector3) -> Vector3:
	if not value is Dictionary:
		return fallback
	var data: Dictionary = value
	var x_value: Variant = data.get("iso_x_m", fallback.x)
	var z_value: Variant = data.get("iso_y_m", fallback.z)
	var y_value: Variant = data.get("altitude_m", fallback.y)
	if not _valid_number(x_value) or not _valid_number(y_value) or not _valid_number(z_value):
		return fallback
	return Vector3(float(x_value), float(y_value), float(z_value))


func _resource_presentation_position(entry: Dictionary) -> Vector3:
	if entry.has("position"):
		return _position_from_dictionary(entry.get("position"), Vector3.ZERO)
	# Stage16A exposes the authoritative zone/block and resource identity, but its
	# node definition explicitly does not claim an exact canonical location. Godot
	# therefore owns only this deterministic placeholder arrangement around the
	# current Player; it is never sent back as resource/yield authority.
	var origin: Vector3 = _player.global_position if _player != null else Vector3.ZERO
	var order: int = maxi(0, int(entry.get("presentation_order", 0)))
	var column: int = order % 6
	var row: int = floori(float(order) / 6.0)
	return origin + Vector3(-5.0 + float(column) * 2.0, 0.0, 3.0 + float(row) * 2.0)


func _present_blocked(resource: AndromedaResourceNode, reason: String) -> void:
	if resource != null and is_instance_valid(resource):
		resource.present_client_feedback(
			"RESOURCE_UNAVAILABLE" if reason in ["RESOURCE_UNAVAILABLE", "RESOURCE_BUSY"] else "INTERACTION_BLOCKED",
			false
		)
	if _hud != null:
		_hud.present_combat_event({
			"token": "INTERACTION_BLOCKED",
			"target_ref": resource.target_ref if resource != null else "",
			"confirmed_externally": false,
		})


func _observe_gathering_action(active: bool) -> void:
	if _ground_loot_client == null:
		return
	var previous: Dictionary = _ground_loot_client.observed_action_context()
	_ground_loot_client.observe_action_context({
		"attack_active": bool(previous.get("attack_active", false)),
		"interaction_active": active,
		"chase_target_ref": str(previous.get("chase_target_ref", "")),
	})


func _discover_scene_resources() -> void:
	if _resource_root == null:
		return
	for child: Node in _resource_root.get_children():
		if child is AndromedaResourceNode:
			register_resource(child as AndromedaResourceNode)


func _on_bridge_snapshot_applied(snapshot: Dictionary) -> void:
	if snapshot.has("resources"):
		var resource_snapshot: Dictionary = snapshot.duplicate(true)
		resource_snapshot["snapshot_sequence"] = snapshot.get(
			"presentation_sequence", snapshot.get("snapshot_sequence")
		)
		project_resource_snapshot(resource_snapshot)


func _on_bridge_command_result_received(result: Dictionary) -> void:
	if str(result.get("command", "")).strip_edges().to_upper() != "REQUEST_GATHER":
		return
	project_gathering_result(result)


func _on_session_bound(session_ref_value: String, _session_epoch: int) -> void:
	if _resource_snapshot_session_ref.is_empty() or _resource_snapshot_session_ref == session_ref_value:
		return
	_reset_projection_caches_for_session_change()


func _on_session_revoked(_previous_session_ref: String, _session_epoch: int) -> void:
	_pending_approach.clear()
	_inflight_requests.clear()
	_observe_gathering_action(false)


func _reset_projection_caches_for_session_change() -> void:
	_resource_snapshot_session_ref = ""
	_last_resource_snapshot_sequence = -1
	_last_output_session_ref = ""
	_last_output_event_sequence = -1
	_last_stamina_projection_sequence = -1
	_request_result_sequences.clear()
	_processed_output_events.clear()
	_pending_approach.clear()
	_inflight_requests.clear()
	_resource_tombstones.clear()
	for resource_value: Variant in _registered_resources.values():
		if resource_value is AndromedaResourceNode and is_instance_valid(resource_value):
			(resource_value as AndromedaResourceNode).reset_client_projection_cache()
	_observe_gathering_action(false)


func _safe_node_fragment(value: String) -> String:
	var result: String = ""
	for character: String in value:
		result += character if character.is_valid_identifier() or character.is_valid_int() else "_"
	return result


func _bridge() -> AndromedaRuntimeBridge:
	return get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge


func _session() -> AndromedaClientSession:
	return get_node_or_null("/root/ClientSession") as AndromedaClientSession


func _valid_number(value: Variant) -> bool:
	return typeof(value) in [TYPE_INT, TYPE_FLOAT] and is_finite(float(value))


func _rejected(reason: String, detail: Dictionary = {}) -> Dictionary:
	var result := {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
	result.merge(detail, true)
	return result
