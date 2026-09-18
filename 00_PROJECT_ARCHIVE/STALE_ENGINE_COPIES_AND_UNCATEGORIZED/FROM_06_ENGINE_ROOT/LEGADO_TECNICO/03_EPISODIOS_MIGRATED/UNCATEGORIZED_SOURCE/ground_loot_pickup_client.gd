extends Node
class_name AndromedaGroundLootPickupClient

## B07 client orchestration only. It observes real Godot distance/path/collision and
## prepares intent envelopes; authoritative pickup, inventory and TTL remain upstream.

signal pickup_request_prepared(result: Dictionary)
signal pickup_request_deduplicated(result: Dictionary)
signal pickup_feedback_projected(result: Dictionary)

const AUTHORITY := "GODOT_GROUND_LOOT_CLIENT_ORCHESTRATION_ONLY"
const PICKUP_RADIUS_M := 0.5
const BLOCKER_MASK := 1 | 128
const GROUND_LOOT_SCENE: PackedScene = preload("res://scenes/interaction/GroundLoot.tscn")

var _main_runtime: AndromedaMainRuntime
var _player: AndromedaPlayerController
var _hud: AndromedaHUDController
var _loot_root: Node3D
var _registered_loot: Dictionary = {}
var _tombstones: Dictionary = {}
var _manual_pending: Dictionary = {}
var _inflight_requests: Dictionary = {}
var _pickup_result_sequences: Dictionary = {}
var _settle_pending: Dictionary = {}
var _settle_inflight: Dictionary = {}
var _last_request: Dictionary = {}
var _request_history: Array[Dictionary] = []
var _request_serial: int = 0
var _auto_pickup_enabled: bool = false
var _preference_known: bool = false
var _preference_session_ref: String = ""
var _preference_sequence: int = -1
var _ground_loot_snapshot_session_ref: String = ""
var _last_ground_loot_snapshot_sequence: int = -1
var _authority_origin_known: bool = false
var _authority_origin_iso_x_m: float = 0.0
var _authority_origin_iso_y_m: float = 0.0
var _authority_origin_altitude_m: float = 0.0
var _presentation_origin: Vector3 = Vector3.ZERO
var _scan_accumulator_s: float = 0.0
var _scan_interval_s: float = 0.12
var _observed_action_context: Dictionary = {
	"attack_active": false,
	"interaction_active": false,
	"chase_target_ref": "",
}
var _bound: bool = false


func _ready() -> void:
	process_physics_priority = 90


func _physics_process(delta: float) -> void:
	if not _bound:
		return
	_discover_scene_loot()
	process_manual_approach_once()
	_process_pending_settle_observations()
	_scan_accumulator_s += delta
	if _scan_accumulator_s < _scan_interval_s:
		return
	_scan_accumulator_s = 0.0
	if _auto_pickup_enabled and _preference_known:
		scan_auto_pickup_once()


func bind_runtime(
	main_runtime_value: AndromedaMainRuntime,
	player_value: AndromedaPlayerController,
	hud_value: AndromedaHUDController,
	loot_root_value: Node3D
) -> Dictionary:
	if main_runtime_value == null or player_value == null or hud_value == null or loot_root_value == null:
		return _rejected("MAIN_PLAYER_HUD_LOOT_ROOT_REQUIRED")
	_main_runtime = main_runtime_value
	_player = player_value
	_hud = hud_value
	_loot_root = loot_root_value
	_discover_scene_loot()
	if not _bound:
		var inventory_shell: AndromedaInventoryShell = _hud.inventory_shell
		if not inventory_shell.auto_pickup_visual_changed.is_connected(_on_auto_pickup_visual_changed):
			inventory_shell.auto_pickup_visual_changed.connect(_on_auto_pickup_visual_changed)
		var bridge := _bridge()
		if bridge != null and not bridge.snapshot_applied.is_connected(_on_bridge_snapshot_applied):
			bridge.snapshot_applied.connect(_on_bridge_snapshot_applied)
		if bridge != null and not bridge.command_result_received.is_connected(_on_bridge_command_result_received):
			bridge.command_result_received.connect(_on_bridge_command_result_received)
		var session := _session()
		if session != null:
			if not session.session_bound.is_connected(_on_session_bound):
				session.session_bound.connect(_on_session_bound)
			if not session.session_revoked.is_connected(_on_session_revoked):
				session.session_revoked.connect(_on_session_revoked)
		_bound = true
	return {
		"status": "PASS",
		"registered_loot_count": _registered_loot.size(),
		"authority": AUTHORITY,
	}


func register_ground_loot(loot: AndromedaGroundLoot) -> Dictionary:
	if loot == null or not is_instance_valid(loot):
		return _rejected("GROUND_LOOT_INSTANCE_REQUIRED")
	var target_ref_value: String = loot.target_ref.strip_edges()
	if target_ref_value.is_empty():
		return _rejected("EMPTY_TARGET_REF")
	if _registered_loot.has(target_ref_value):
		var existing := _registered_loot[target_ref_value] as AndromedaGroundLoot
		if existing != loot:
			return _rejected("DUPLICATE_ACTIVE_TARGET_REF")
		return {
			"status": "PASS",
			"target_ref": target_ref_value,
			"idempotent": true,
			"authority": AUTHORITY,
		}
	_registered_loot[target_ref_value] = loot
	if not loot.local_settling_changed.is_connected(_on_loot_local_settling_changed):
		loot.local_settling_changed.connect(_on_loot_local_settling_changed)
	return {
		"status": "PASS",
		"target_ref": target_ref_value,
		"idempotent": false,
		"authority": AUTHORITY,
	}


func unregister_ground_loot(target_ref_value: String) -> Dictionary:
	var normalized_ref: String = target_ref_value.strip_edges()
	if not _registered_loot.has(normalized_ref):
		return _rejected("GROUND_LOOT_NOT_REGISTERED")
	_registered_loot.erase(normalized_ref)
	_manual_pending.erase(normalized_ref)
	_inflight_requests.erase(normalized_ref)
	_settle_pending.erase(normalized_ref)
	_settle_inflight.erase(normalized_ref)
	return {"status": "PASS", "target_ref": normalized_ref, "authority": AUTHORITY}


func handle_manual_pointer_intent(
	resolved: Dictionary,
	target: AndromedaInteractionTarget
) -> Dictionary:
	if resolved.get("status") != "PASS":
		return _rejected("POINTER_INTENT_NOT_PASS")
	if not target is AndromedaGroundLoot:
		return _rejected("SPECIALIZED_GROUND_LOOT_REQUIRED")
	var loot := target as AndromedaGroundLoot
	var target_ref_value: String = str(resolved.get("target_ref", "")).strip_edges()
	if target_ref_value != loot.target_ref:
		return _rejected("GROUND_LOOT_TARGET_REF_MISMATCH")
	var registration: Dictionary = register_ground_loot(loot)
	if registration.get("status") != "PASS":
		return registration
	var intent: String = str(resolved.get("intent", "")).strip_edges().to_upper()
	if intent == "PICKUP":
		return _prepare_pickup_request(loot, "MANUAL_%s" % str(resolved.get("button", "UNKNOWN")))
	if intent != "APPROACH_PICKUP":
		return _rejected("UNSUPPORTED_GROUND_LOOT_POINTER_INTENT")
	if _inflight_requests.has(target_ref_value):
		return _deduplicated(target_ref_value, "REQUEST_ALREADY_INFLIGHT")
	_manual_pending.clear()
	_manual_pending[target_ref_value] = {
		"target_ref": target_ref_value,
		"instance_id": loot.get_instance_id(),
		"button": str(resolved.get("button", "UNKNOWN")),
		"selection_ref_at_click": _main_runtime.selected_target_ref() if _main_runtime != null else "",
	}
	return {
		"status": "PASS",
		"intent": "APPROACH_PICKUP_PENDING",
		"target_ref": target_ref_value,
		"pickup_requested": false,
		"remote_collection": false,
		"authority": AUTHORITY,
	}


func process_manual_approach_once() -> Dictionary:
	if _manual_pending.is_empty():
		return {"status": "PASS", "pending": false, "authority": AUTHORITY}
	var target_ref_value: String = str(_manual_pending.keys()[0])
	var loot: AndromedaGroundLoot = ground_loot_for_ref(target_ref_value)
	if loot == null:
		_manual_pending.clear()
		return _rejected("STALE_OR_REMOVED_GROUND_LOOT_TARGET")
	var eligibility: Dictionary = evaluate_pickup_candidate(loot)
	if eligibility.get("status") == "PASS":
		var button: String = str(_manual_pending[target_ref_value].get("button", "UNKNOWN"))
		_manual_pending.clear()
		return _prepare_pickup_request(loot, "MANUAL_%s_AFTER_APPROACH" % button)
	var reason: String = str(eligibility.get("reason", ""))
	if reason in ["PICKUP_DISTANCE_EXCEEDED", "GROUND_LOOT_NOT_SETTLED"]:
		return {
			"status": "PASS",
			"pending": true,
			"reason": reason,
			"target_ref": target_ref_value,
			"authority": AUTHORITY,
		}
	_manual_pending.clear()
	return eligibility


func evaluate_pickup_candidate(loot: AndromedaGroundLoot) -> Dictionary:
	if _player == null:
		return _rejected("PLAYER_NOT_BOUND")
	if loot == null or not is_instance_valid(loot) or not loot.is_inside_tree():
		return _rejected("STALE_OR_REMOVED_GROUND_LOOT_TARGET")
	var target_ref_value: String = loot.target_ref.strip_edges()
	if ground_loot_for_ref(target_ref_value) != loot:
		return _rejected("WRONG_OR_UNREGISTERED_GROUND_LOOT_TARGET")
	if not loot.is_active_for_pickup():
		return _rejected("GROUND_LOOT_NOT_ACTIVE")
	if not loot.is_pickup_settled():
		return _rejected("GROUND_LOOT_NOT_SETTLED")
	if not loot.projected_reachable:
		return _rejected("GROUND_LOOT_UNREACHABLE")
	var physical_distance_m: float = loot.physical_distance_to(_player)
	if not is_finite(physical_distance_m) or physical_distance_m > PICKUP_RADIUS_M:
		return _rejected("PICKUP_DISTANCE_EXCEEDED", {
			"physical_distance_m": physical_distance_m,
			"max_distance_m": PICKUP_RADIUS_M,
		})
	var blocker_probe: Dictionary = pickup_blocker_probe(loot)
	if blocker_probe.get("blocked") == true:
		return _rejected("PICKUP_BLOCKED_BY_COLLISION")
	var path_validation: Dictionary = _player.validate_destination(loot.global_position)
	if path_validation.get("status") != "PASS":
		return _rejected("GROUND_LOOT_UNREACHABLE", {
			"path_result": path_validation,
		})
	return {
		"status": "PASS",
		"target_ref": target_ref_value,
		"physical_distance_m": physical_distance_m,
		"max_distance_m": PICKUP_RADIUS_M,
		"path_valid": true,
		"blocker_clear": true,
		"authority": AUTHORITY,
	}


func pickup_blocker_probe(loot: AndromedaGroundLoot) -> Dictionary:
	if _player == null or loot == null or not is_instance_valid(loot):
		return _rejected("PLAYER_AND_GROUND_LOOT_REQUIRED")
	var world: World3D = _player.get_world_3d()
	if world == null:
		return _rejected("WORLD_3D_REQUIRED")
	var ray_start: Vector3 = _player.global_position + Vector3(0.0, 0.34, 0.0)
	var ray_end: Vector3 = loot.global_position + Vector3(0.0, 0.28, 0.0)
	var excluded: Array[RID] = [_player.get_rid()]
	var query := PhysicsRayQueryParameters3D.create(ray_start, ray_end, BLOCKER_MASK, excluded)
	query.collide_with_areas = false
	query.collide_with_bodies = true
	var hit: Dictionary = world.direct_space_state.intersect_ray(query)
	var collider := hit.get("collider") as CollisionObject3D
	return {
		"status": "PASS",
		"blocked": not hit.is_empty(),
		"collider_name": str(collider.name) if collider != null else "",
		"collision_layer": collider.collision_layer if collider != null else 0,
		"ray_start": ray_start,
		"ray_end": ray_end,
		"authority": AUTHORITY,
	}


func scan_auto_pickup_once() -> Dictionary:
	if not _auto_pickup_enabled or not _preference_known:
		return {
			"status": "PASS",
			"enabled": false,
			"requests": [],
			"interrupts_action": false,
			"authority": AUTHORITY,
		}
	_discover_scene_loot()
	var refs: Array[String] = []
	for ref_value: Variant in _registered_loot.keys():
		refs.append(str(ref_value))
	refs.sort()
	var requests: Array[Dictionary] = []
	var rejected: Array[Dictionary] = []
	var action_before: Dictionary = _observed_action_context.duplicate(true)
	var movement_destination_before: Vector3 = _player.requested_destination()
	var movement_active_before: bool = _player.has_destination()
	var selection_before: String = _main_runtime.selected_target_ref() if _main_runtime != null else ""
	for target_ref_value: String in refs:
		var loot: AndromedaGroundLoot = ground_loot_for_ref(target_ref_value)
		if loot == null:
			continue
		var eligibility: Dictionary = evaluate_pickup_candidate(loot)
		if eligibility.get("status") != "PASS":
			rejected.append(eligibility)
			continue
		var request: Dictionary = _prepare_pickup_request(loot, "AUTO_PICKUP")
		if request.get("status") == "PASS" and not bool(request.get("deduplicated", false)):
			requests.append(request)
	return {
		"status": "PASS",
		"enabled": true,
		"requests": requests,
		"rejected_candidates": rejected,
		"interrupts_action": false,
		"movement_active_preserved": _player.has_destination() == movement_active_before,
		"movement_destination_preserved": _player.requested_destination().is_equal_approx(movement_destination_before),
		"selection_preserved": _main_runtime == null or _main_runtime.selected_target_ref() == selection_before,
		"action_context_preserved": _observed_action_context == action_before,
		"authority": AUTHORITY,
	}


func project_profile_preference(
	enabled: bool,
	session_ref_value: String,
	preference_sequence: int,
	externally_confirmed: bool = false
) -> Dictionary:
	if not externally_confirmed:
		return _rejected("EXTERNAL_PROFILE_PREFERENCE_CONFIRMATION_REQUIRED")
	var normalized_session: String = session_ref_value.strip_edges()
	var session := _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	if normalized_session != session.session_ref():
		return _rejected("PROFILE_PREFERENCE_SESSION_MISMATCH")
	if not _preference_session_ref.is_empty() and normalized_session != _preference_session_ref:
		return _rejected("PROFILE_PREFERENCE_SESSION_MISMATCH")
	if preference_sequence < 0:
		return _rejected("INVALID_PROFILE_PREFERENCE_SEQUENCE")
	if preference_sequence <= _preference_sequence:
		return _rejected("STALE_OR_DUPLICATE_PROFILE_PREFERENCE")
	_preference_session_ref = normalized_session
	_preference_sequence = preference_sequence
	_preference_known = true
	_auto_pickup_enabled = enabled
	if _hud != null:
		_hud.set_auto_pickup_projection(enabled, false)
	return {
		"status": "PASS",
		"enabled": _auto_pickup_enabled,
		"preference_sequence": _preference_sequence,
		"persisted_by_gdscript": false,
		"authoritative_persistence_confirmed": false,
		"authority": AUTHORITY,
	}


func project_ground_loot_snapshot(snapshot: Dictionary) -> Dictionary:
	if snapshot.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_GROUND_LOOT_SNAPSHOT")
	var session := _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	var session_ref_value: String = str(snapshot.get("session_ref", "")).strip_edges()
	if session_ref_value != session.session_ref():
		return _rejected("GROUND_LOOT_SNAPSHOT_SESSION_MISMATCH")
	var sequence_value: Variant = snapshot.get("snapshot_sequence", null)
	if typeof(sequence_value) != TYPE_INT or int(sequence_value) < 0:
		return _rejected("INVALID_GROUND_LOOT_SNAPSHOT_SEQUENCE")
	if (
		not _ground_loot_snapshot_session_ref.is_empty()
		and session_ref_value != _ground_loot_snapshot_session_ref
	):
		return _rejected("GROUND_LOOT_SNAPSHOT_SESSION_MISMATCH")
	if int(sequence_value) <= _last_ground_loot_snapshot_sequence:
		return _rejected("STALE_OR_DUPLICATE_GROUND_LOOT_SNAPSHOT")
	var entries_value: Variant = snapshot.get("ground_loot", [])
	if not entries_value is Array:
		return _rejected("INVALID_GROUND_LOOT_SNAPSHOT_LIST")
	var projected: Array[Dictionary] = []
	for entry_value: Variant in entries_value:
		if not entry_value is Dictionary:
			return _rejected("INVALID_GROUND_LOOT_SNAPSHOT_ENTRY")
		var entry: Dictionary = entry_value
		var result: Dictionary = _project_ground_loot_entry(entry, session_ref_value, int(sequence_value))
		if result.get("status") != "PASS":
			return result
		projected.append(result)
	_ground_loot_snapshot_session_ref = session_ref_value
	_last_ground_loot_snapshot_sequence = int(sequence_value)
	return {
		"status": "PASS",
		"snapshot_sequence": int(sequence_value),
		"projected": projected,
		"inventory_mutated": false,
		"ttl_advanced_locally": false,
		"authority": AUTHORITY,
	}


func project_pickup_result(result: Dictionary) -> Dictionary:
	if result.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_PICKUP_RESULT")
	var session := _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	var session_ref_value: String = str(result.get("session_ref", "")).strip_edges()
	if session_ref_value != session.session_ref():
		return _rejected("PICKUP_RESULT_SESSION_MISMATCH")
	var target_ref_value: String = str(result.get("target_ref", "")).strip_edges()
	var loot: AndromedaGroundLoot = ground_loot_for_ref(target_ref_value)
	if loot == null:
		return _rejected("PICKUP_RESULT_TARGET_NOT_FOUND")
	var sequence_value: Variant = result.get("result_sequence", null)
	if typeof(sequence_value) != TYPE_INT or int(sequence_value) < 0:
		return _rejected("INVALID_PICKUP_RESULT_SEQUENCE")
	var last_sequence: int = int(_pickup_result_sequences.get(target_ref_value, -1))
	if int(sequence_value) <= last_sequence:
		return _rejected("STALE_OR_DUPLICATE_PICKUP_RESULT")
	_pickup_result_sequences[target_ref_value] = int(sequence_value)
	_inflight_requests.erase(target_ref_value)
	var status: String = str(result.get("status", "REJECTED")).strip_edges().to_upper()
	if status != "PASS":
		var reason: String = str(result.get("reason", "PICKUP_REJECTED"))
		var feedback: Dictionary = {
			"status": "PASS",
			"token": "INTERACTION_BLOCKED",
			"reason": reason,
			"target_ref": target_ref_value,
			"drop_remains_active": loot.is_active_for_pickup(),
			"inventory_mutated": false,
			"authority": AUTHORITY,
		}
		if _hud != null:
			feedback["hud_feedback"] = _hud.present_combat_event({
				"token": "INTERACTION_BLOCKED",
				"target_ref": target_ref_value,
				"confirmed_externally": true,
			})
		pickup_feedback_projected.emit(feedback.duplicate(true))
		return feedback
	var lifecycle: Dictionary = loot.apply_external_lifecycle_result(
		"COLLECTED",
		session_ref_value,
		int(sequence_value)
	)
	return {
		"status": lifecycle.get("status", "REJECTED"),
		"target_ref": target_ref_value,
		"drop_state": loot.authoritative_state(),
		"item_granted_locally": false,
		"inventory_mutated": false,
		"authority": AUTHORITY,
	}


func observe_action_context(context: Dictionary) -> Dictionary:
	_observed_action_context = {
		"attack_active": bool(context.get("attack_active", false)),
		"interaction_active": bool(context.get("interaction_active", false)),
		"chase_target_ref": str(context.get("chase_target_ref", "")),
	}
	return _observed_action_context.duplicate(true)


func observed_action_context() -> Dictionary:
	return _observed_action_context.duplicate(true)


func auto_pickup_enabled() -> bool:
	return _auto_pickup_enabled and _preference_known


func preference_known() -> bool:
	return _preference_known


func ground_loot_for_ref(target_ref_value: String) -> AndromedaGroundLoot:
	var normalized_ref: String = target_ref_value.strip_edges()
	var value: Variant = _registered_loot.get(normalized_ref)
	if not is_instance_valid(value):
		_registered_loot.erase(normalized_ref)
		return null
	if value is AndromedaGroundLoot:
		return value as AndromedaGroundLoot
	return null


func registered_loot_count() -> int:
	var count: int = 0
	for target_ref_value: Variant in _registered_loot.keys():
		if ground_loot_for_ref(str(target_ref_value)) != null:
			count += 1
	return count


func inflight_request_count() -> int:
	return _inflight_requests.size()


func has_inflight_request(target_ref_value: String) -> bool:
	return _inflight_requests.has(target_ref_value.strip_edges())


func clear_client_request_tracking() -> void:
	_manual_pending.clear()
	_inflight_requests.clear()
	_last_request.clear()
	_request_history.clear()


func last_request() -> Dictionary:
	return _last_request.duplicate(true)


func request_history() -> Array[Dictionary]:
	return _request_history.duplicate(true)


func tombstone_for_ref(target_ref_value: String) -> Dictionary:
	var value: Variant = _tombstones.get(target_ref_value.strip_edges(), {})
	return value.duplicate(true) if value is Dictionary else {}


func contract_snapshot() -> Dictionary:
	return {
		"pickup_radius_m": PICKUP_RADIUS_M,
		"universal_source_kinds": AndromedaGroundLoot.UNIVERSAL_SOURCE_KINDS.duplicate(),
		"manual_flow": ["CLICK", "RESOLVE_LOOT", "PATH", "APPROACH", "REQUEST_PICKUP"],
		"auto_pickup_passive": true,
		"auto_pickup_remote": false,
		"auto_pickup_interrupts_movement": false,
		"auto_pickup_interrupts_attack": false,
		"auto_pickup_interrupts_interaction": false,
		"auto_pickup_changes_target": false,
		"auto_pickup_changes_chase": false,
		"anti_spam_inflight_by_target_ref": true,
		"profile_preference_persisted_by_gdscript": false,
		"item_grant_authority": false,
		"inventory_authority": false,
		"quantity_authority": false,
		"ownership_authority": false,
		"ttl_authority": false,
		"backend_substitute": false,
		"invented_endpoint": false,
		"authority": AUTHORITY,
	}


func _prepare_pickup_request(loot: AndromedaGroundLoot, request_source: String) -> Dictionary:
	var eligibility: Dictionary = evaluate_pickup_candidate(loot)
	if eligibility.get("status") != "PASS":
		return eligibility
	var target_ref_value: String = loot.target_ref
	if _inflight_requests.has(target_ref_value):
		return _deduplicated(target_ref_value, "REQUEST_ALREADY_INFLIGHT")
	var bridge := _bridge()
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	_request_serial += 1
	var request_ref := "B07-PICKUP-REQUEST-%06d" % _request_serial
	# Only identity crosses the authority boundary. The server derives physical
	# distance and reads settled/reachable state from its Stage16A world state.
	var params := {"target_ref": target_ref_value}
	var built: Dictionary = bridge.build_command_envelope("REQUEST_PICKUP", params)
	if built.get("status") != "PASS":
		return built
	var submitted: bool = false
	var transport_result: Dictionary = {
		"status": "NOT_AVAILABLE",
		"reason": "BRIDGE_NOT_READY_NO_LIVE_BACKEND",
	}
	if bridge.connection_state().get("authority_session_bound") == true:
		var command_ref: String = str(built.get("envelope", {}).get("command_ref", ""))
		transport_result = bridge.submit_command("REQUEST_PICKUP", params, command_ref)
		submitted = transport_result.get("status") == "PASS"
	var action_context_before: Dictionary = _observed_action_context.duplicate(true)
	var selection_ref: String = _main_runtime.selected_target_ref() if _main_runtime != null else ""
	_last_request = {
		"status": "PASS",
		"intent": "REQUEST_PICKUP",
		"request_ref": request_ref,
		"target_ref": target_ref_value,
		"request_source": request_source,
		"physical_distance_m": float(eligibility.get("physical_distance_m", INF)),
		"max_pickup_distance_m": PICKUP_RADIUS_M,
		"intent_envelope": built,
		"transport_result": transport_result,
		"transport_submitted": submitted,
		"item_granted_locally": false,
		"loot_removed_locally": false,
		"inventory_mutated": false,
		"interrupts_action": false,
		"selection_ref_preserved": selection_ref,
		"action_context_before": action_context_before,
		"authority": AUTHORITY,
	}
	_inflight_requests[target_ref_value] = _last_request.duplicate(true)
	_request_history.append(_last_request.duplicate(true))
	pickup_request_prepared.emit(_last_request.duplicate(true))
	return _last_request.duplicate(true)


func _project_ground_loot_entry(
	entry: Dictionary,
	session_ref_value: String,
	snapshot_sequence: int
) -> Dictionary:
	var target_ref_value: String = str(entry.get("target_ref", entry.get("drop_ref", ""))).strip_edges()
	if target_ref_value.is_empty():
		return _rejected("EMPTY_GROUND_LOOT_TARGET_REF")
	var state: String = str(entry.get("state", "ACTIVE")).strip_edges().to_upper()
	var loot: AndromedaGroundLoot = ground_loot_for_ref(target_ref_value)
	if loot == null and state in AndromedaGroundLoot.TERMINAL_PRESENTATION_STATES:
		_tombstones[target_ref_value] = {
			"target_ref": target_ref_value,
			"state": state,
			"session_ref": session_ref_value,
			"snapshot_sequence": snapshot_sequence,
			"active": false,
		}
		return {
			"status": "PASS",
			"target_ref": target_ref_value,
			"state": state,
			"tombstone_only": true,
			"authority": AUTHORITY,
		}
	if loot == null:
		loot = GROUND_LOOT_SCENE.instantiate() as AndromedaGroundLoot
		if loot == null:
			return _rejected("GROUND_LOOT_SCENE_INSTANTIATION_FAILED")
		var identity: Dictionary = loot.configure_spawn_identity(
			target_ref_value,
			str(entry.get("source_ref", "")),
			str(entry.get("source_kind", "")),
			str(entry.get("item_ref", "")),
			str(entry.get("item_kind", "MATERIAL"))
		)
		if identity.get("status") != "PASS":
			loot.free()
			return identity
		loot.name = "GroundLoot_%s" % _safe_node_fragment(target_ref_value)
		loot.position = _position_from_entry(entry)
		loot.set_meta("b07_snapshot_spawned", true)
		_loot_root.add_child(loot)
		var registration: Dictionary = register_ground_loot(loot)
		if registration.get("status") != "PASS":
			loot.queue_free()
			return registration
	var projection: Dictionary = loot.apply_authoritative_projection(entry, session_ref_value, snapshot_sequence)
	if projection.get("status") != "PASS":
		return projection
	loot.global_position = _position_from_entry(entry, loot.global_position)
	if bool(entry.get("settled", false)):
		loot.set("freeze", true)
		loot.set("linear_velocity", Vector3.ZERO)
		loot.set("angular_velocity", Vector3.ZERO)
	else:
		loot.global_position = _safe_unsettled_spawn_position(loot, loot.global_position)
		loot.begin_local_physical_settle()
	if state in AndromedaGroundLoot.TERMINAL_PRESENTATION_STATES:
		_tombstones[target_ref_value] = loot.presentation_snapshot()
	return projection


func _position_from_entry(entry: Dictionary, fallback: Vector3 = Vector3.ZERO) -> Vector3:
	var position_value: Variant = entry.get("settled_position", entry.get("candidate_position", {}))
	if not position_value is Dictionary:
		return fallback
	var position_data: Dictionary = position_value
	var x_value: Variant = position_data.get("iso_x_m", fallback.x)
	var z_value: Variant = position_data.get("iso_y_m", fallback.z)
	var y_value: Variant = position_data.get("altitude_m", fallback.y)
	if not _valid_number(x_value) or not _valid_number(y_value) or not _valid_number(z_value):
		return fallback
	if _authority_origin_known:
		# Subtract while values are still 64-bit GDScript floats. Constructing a
		# Vector3 at country-scale coordinates first loses the 0.5000/0.5001 m
		# distinction that the pickup contract explicitly requires.
		return _presentation_origin + Vector3(
			float(x_value) - _authority_origin_iso_x_m,
			float(y_value) - _authority_origin_altitude_m,
			float(z_value) - _authority_origin_iso_y_m
		)
	return Vector3(float(x_value), float(y_value), float(z_value))


func _safe_unsettled_spawn_position(loot: AndromedaGroundLoot, candidate: Vector3) -> Vector3:
	# A server candidate may map into a local placeholder blocker because Stage16A
	# owns country-scale coordinates while Godot owns this test terrain layout. Cast
	# against the real collision surface before unfreezing so the RigidBody cannot be
	# depenetrated downward and fall through the world. The observed final position
	# still requires CONFIRM_DROP_SETTLED round-trip before pickup is authorised.
	if loot == null or loot.get_world_3d() == null:
		return candidate
	var query := PhysicsRayQueryParameters3D.create(
		candidate + Vector3(0.0, 8.0, 0.0),
		candidate - Vector3(0.0, 4.0, 0.0),
		1,
		[loot.get_rid()]
	)
	query.collide_with_areas = false
	query.collide_with_bodies = true
	var hit: Dictionary = loot.get_world_3d().direct_space_state.intersect_ray(query)
	if hit.is_empty() or not hit.get("position") is Vector3:
		return candidate
	var surface_position: Vector3 = hit["position"]
	return Vector3(candidate.x, surface_position.y + 0.002, candidate.z)


func _authority_position_from_local(local_position: Vector3) -> Dictionary:
	var delta: Vector3 = local_position - _presentation_origin
	return {
		"iso_x_m": _authority_origin_iso_x_m + float(delta.x),
		"iso_y_m": _authority_origin_iso_y_m + float(delta.z),
		"altitude_m": _authority_origin_altitude_m + float(delta.y),
	}


func _on_loot_local_settling_changed(target_ref_value: String, locally_settled: bool) -> void:
	if locally_settled:
		_settle_pending[target_ref_value] = true
	else:
		_settle_pending.erase(target_ref_value)


func _process_pending_settle_observations() -> void:
	if _settle_pending.is_empty() or not _authority_origin_known:
		return
	var bridge := _bridge()
	if bridge == null or bridge.connection_state().get("authority_session_bound") != true:
		return
	for target_ref_value_variant: Variant in _settle_pending.keys():
		var target_ref_value: String = str(target_ref_value_variant)
		if _settle_inflight.has(target_ref_value):
			continue
		var loot: AndromedaGroundLoot = ground_loot_for_ref(target_ref_value)
		if loot == null or not loot.is_locally_settled():
			_settle_pending.erase(target_ref_value)
			continue
		var path_result: Dictionary = _player.validate_destination(loot.global_position)
		if path_result.get("reason") == "NAVIGATION_MAP_NOT_READY":
			continue
		var blocker_result: Dictionary = pickup_blocker_probe(loot)
		var reachable: bool = (
			path_result.get("status") == "PASS"
			and blocker_result.get("status") == "PASS"
			and blocker_result.get("blocked") != true
		)
		var params := {
			"target_ref": target_ref_value,
			"settled_position": _authority_position_from_local(loot.global_position),
			"reachable": reachable,
		}
		var built: Dictionary = bridge.build_command_envelope("CONFIRM_DROP_SETTLED", params)
		if built.get("status") != "PASS":
			continue
		var envelope: Dictionary = built.get("envelope", {}) as Dictionary
		var submitted: Dictionary = bridge.submit_command(
			"CONFIRM_DROP_SETTLED", params, str(envelope.get("command_ref", ""))
		)
		if submitted.get("status") == "PASS":
			_settle_inflight[target_ref_value] = {
				"command_ref": submitted.get("command_ref", ""),
				"reachable_observed": reachable,
			}


func _pickup_line_blocked(loot: AndromedaGroundLoot) -> bool:
	return pickup_blocker_probe(loot).get("blocked") == true


func _discover_scene_loot() -> void:
	if get_tree() == null:
		return
	for node: Node in get_tree().get_nodes_in_group("andromeda_ground_loot"):
		if node is AndromedaGroundLoot:
			var loot := node as AndromedaGroundLoot
			if not loot.target_ref.is_empty() and ground_loot_for_ref(loot.target_ref) == null:
				register_ground_loot(loot)


func _on_auto_pickup_visual_changed(enabled: bool) -> void:
	_auto_pickup_enabled = enabled
	_preference_known = true
	var session := _session()
	_preference_session_ref = session.session_ref() if session != null and session.has_active_session() else ""
	# This is an unconfirmed client preference projection. It is intentionally not
	# assigned an authoritative sequence and is never persisted by this node.


func _on_bridge_snapshot_applied(snapshot: Dictionary) -> void:
	var session_ref_value: String = str(snapshot.get("session_ref", ""))
	var snapshot_sequence: int = int(snapshot.get(
		"presentation_sequence", snapshot.get("snapshot_sequence", -1)
	))
	_update_authority_projection_anchor(snapshot)
	var preferences_value: Variant = snapshot.get("profile_preferences", {})
	if preferences_value is Dictionary:
		var preferences: Dictionary = preferences_value
		if preferences.has("auto_pickup"):
			var preference_sequence: int = int(preferences.get("preference_sequence", snapshot_sequence))
			project_profile_preference(
				bool(preferences.get("auto_pickup", false)),
				session_ref_value,
				preference_sequence,
				bool(snapshot.get("server_authoritative", false))
			)
	if snapshot.has("ground_loot"):
		var loot_snapshot: Dictionary = snapshot.duplicate(true)
		loot_snapshot["snapshot_sequence"] = snapshot_sequence
		project_ground_loot_snapshot(loot_snapshot)


func _on_bridge_command_result_received(result: Dictionary) -> void:
	var command: String = str(result.get("command", "")).strip_edges().to_upper()
	if command == "REQUEST_PICKUP":
		project_pickup_result(result)
	elif command == "CONFIRM_DROP_SETTLED":
		var target_ref_value: String = str(result.get("target_ref", "")).strip_edges()
		_settle_inflight.erase(target_ref_value)
		_settle_pending.erase(target_ref_value)


func _on_session_bound(session_ref_value: String, _session_epoch: int) -> void:
	_clear_previous_session_projections(session_ref_value)
	_preference_known = false
	_preference_session_ref = session_ref_value
	_preference_sequence = -1
	_auto_pickup_enabled = false
	_ground_loot_snapshot_session_ref = ""
	_last_ground_loot_snapshot_sequence = -1
	_authority_origin_known = false
	_manual_pending.clear()
	_inflight_requests.clear()
	_settle_pending.clear()
	_settle_inflight.clear()


func _on_session_revoked(_previous_session_ref: String, _session_epoch: int) -> void:
	_preference_known = false
	_preference_session_ref = ""
	_preference_sequence = -1
	_auto_pickup_enabled = false
	_ground_loot_snapshot_session_ref = ""
	_last_ground_loot_snapshot_sequence = -1
	_authority_origin_known = false
	_manual_pending.clear()
	_inflight_requests.clear()
	_settle_pending.clear()
	_settle_inflight.clear()


func _clear_previous_session_projections(next_session_ref: String) -> void:
	var refs_to_remove: Array[String] = []
	for target_ref_value: Variant in _registered_loot.keys():
		var loot: AndromedaGroundLoot = ground_loot_for_ref(str(target_ref_value))
		if loot == null:
			refs_to_remove.append(str(target_ref_value))
			continue
		if (
			bool(loot.get_meta("b07_snapshot_spawned", false))
			and not loot.projection_session_ref().is_empty()
			and loot.projection_session_ref() != next_session_ref
		):
			refs_to_remove.append(loot.target_ref)
			loot.queue_free()
	for target_ref_value: String in refs_to_remove:
		_registered_loot.erase(target_ref_value)


func _update_authority_projection_anchor(snapshot: Dictionary) -> void:
	## Re-anchor on every snapshot, not only the first.
	##
	## The iso->presentation mapping is anchored on a pair: the authoritative player
	## position and the player node position. The player node is driven by client
	## locomotion and does not follow the authoritative transform, so once the authority
	## moves the player the pair goes stale and every loot position mapped through it
	## inherits that displacement. Measured: the presentation distance drifted to the
	## authoritative distance plus the accumulated authoritative player movement (up to
	## 14.1 m over 30 samples), which made the client refuse pickups the authority
	## considered in range. Refreshing the pair each snapshot keeps the loot positioned
	## in the authoritative frame and returned the error to exactly 0.000000 m.
	if _player == null:
		return
	var transform_value: Variant = snapshot.get("transform", {})
	if not transform_value is Dictionary:
		return
	var transform_data: Dictionary = transform_value
	var x_value: Variant = transform_data.get("iso_x_m", null)
	var y_value: Variant = transform_data.get("altitude_m", 0.0)
	var z_value: Variant = transform_data.get("iso_y_m", null)
	if not _valid_number(x_value) or not _valid_number(y_value) or not _valid_number(z_value):
		return
	var first_anchor: bool = not _authority_origin_known
	_authority_origin_iso_x_m = float(x_value)
	_authority_origin_altitude_m = float(y_value)
	_authority_origin_iso_y_m = float(z_value)
	_presentation_origin = _player.global_position
	_authority_origin_known = true
	if first_anchor:
		_tombstones.clear()


func _deduplicated(target_ref_value: String, reason: String) -> Dictionary:
	var result := {
		"status": "PASS",
		"intent": "REQUEST_PICKUP",
		"target_ref": target_ref_value,
		"deduplicated": true,
		"reason": reason,
		"additional_request_created": false,
		"authority": AUTHORITY,
	}
	pickup_request_deduplicated.emit(result.duplicate(true))
	return result


func _safe_node_fragment(value: String) -> String:
	var output: String = ""
	for character: String in value:
		output += character if character.is_valid_identifier() and character.length() == 1 else "_"
	return output


func _bridge() -> AndromedaRuntimeBridge:
	return get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge


func _session() -> AndromedaClientSession:
	return get_node_or_null("/root/ClientSession") as AndromedaClientSession


func _valid_number(value: Variant) -> bool:
	return (typeof(value) == TYPE_INT or typeof(value) == TYPE_FLOAT) and is_finite(float(value))


func _rejected(reason: String, details: Dictionary = {}) -> Dictionary:
	var result := {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
	result.merge(details, true)
	return result
