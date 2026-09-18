extends Node
class_name AndromedaCombatAuthorityClient

## Client orchestration for Stage03/07 authoritative combat.
## Godot owns target presentation, navigation approach and semantic feedback only.
## Hostility, range, hit, critical, damage, cooldown, HP, defeat and XP are
## resolved by the protected Python cores behind AndromedaBridge.

signal attack_request_prepared(result: Dictionary)
signal attack_result_projected(result: Dictionary)
signal combat_snapshot_projected(result: Dictionary)

const AUTHORITY := "GODOT_COMBAT_CLIENT_ORCHESTRATION_ONLY"
const BLOCKER_MASK := 1 | 128
const PRESENTATION_STAND_OFF_FACTOR := 0.72
const MIN_PRESENTATION_STAND_OFF_M := 0.35

var _main_runtime: AndromedaMainRuntime
var _player: AndromedaPlayerController
var _hud: AndromedaHUDController
var _ground_loot_client: AndromedaGroundLootPickupClient
var _common_actor: AndromedaInteractionTarget
var _alpha_actor: AndromedaInteractionTarget
var _actors_by_ref: Dictionary = {}
var _pending_approach: Dictionary = {}
var _inflight_requests: Dictionary = {}
var _result_sequences: Dictionary = {}
var _snapshot_session_ref: String = ""
var _last_snapshot_sequence: int = -1
var _server_anchor: Vector3 = Vector3.ZERO
var _client_anchor: Vector3 = Vector3.ZERO
var _anchor_initialized: bool = false
var _last_request: Dictionary = {}
var _last_projection: Dictionary = {}
var _bound: bool = false


func _ready() -> void:
	process_physics_priority = 76


func _physics_process(_delta: float) -> void:
	if _bound:
		process_pending_approach_once()


func bind_runtime(
	main_runtime_value: AndromedaMainRuntime,
	player_value: AndromedaPlayerController,
	hud_value: AndromedaHUDController,
	ground_loot_client_value: AndromedaGroundLootPickupClient,
	common_actor_value: AndromedaInteractionTarget,
	alpha_actor_value: AndromedaInteractionTarget
) -> Dictionary:
	if (
		main_runtime_value == null
		or player_value == null
		or hud_value == null
		or ground_loot_client_value == null
		or common_actor_value == null
		or alpha_actor_value == null
	):
		return _rejected("MAIN_PLAYER_HUD_LOOT_AND_COMBAT_ACTORS_REQUIRED")
	_main_runtime = main_runtime_value
	_player = player_value
	_hud = hud_value
	_ground_loot_client = ground_loot_client_value
	_common_actor = common_actor_value
	_alpha_actor = alpha_actor_value
	if not _bound:
		var bridge := _bridge()
		if bridge != null:
			if not bridge.snapshot_applied.is_connected(_on_bridge_snapshot_applied):
				bridge.snapshot_applied.connect(_on_bridge_snapshot_applied)
			if not bridge.command_result_received.is_connected(_on_bridge_command_result_received):
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
		"actor_slots": ["COMMON", "ALPHA"],
		"damage_authority_in_gdscript": false,
		"cooldown_authority_in_gdscript": false,
		"authority": AUTHORITY,
	}


func handle_manual_hostile_intent(
	resolved: Dictionary,
	target: AndromedaInteractionTarget
) -> Dictionary:
	if resolved.get("status") != "PASS":
		return _rejected("POINTER_INTENT_NOT_PASS")
	if str(resolved.get("intent", "")).strip_edges().to_upper() != "CHASE_ATTACK":
		return _rejected("UNSUPPORTED_COMBAT_POINTER_INTENT")
	if target == null or not is_instance_valid(target):
		return _rejected("COMBAT_TARGET_REQUIRED")
	if str(resolved.get("target_ref", "")).strip_edges() != target.target_ref:
		return _rejected("COMBAT_TARGET_REF_MISMATCH")
	return begin_attack(target, "RIGHT_CLICK")


func handle_selected_attack(target: AndromedaInteractionTarget) -> Dictionary:
	if target == null or not is_instance_valid(target):
		return _rejected("SELECTED_COMBAT_TARGET_REQUIRED")
	return begin_attack(target, "SPACE_SELECTED_ATTACK")


func begin_attack(target: AndromedaInteractionTarget, request_source: String) -> Dictionary:
	var validation: Dictionary = _validate_target(target)
	if validation.get("status") != "PASS":
		return validation
	if _inflight_requests.has(target.target_ref):
		return _rejected("ATTACK_REQUEST_ALREADY_INFLIGHT", {
			"target_ref": target.target_ref,
			"deduplicated": true,
		})
	var attack_range_m: float = float(target.get_meta("authority_attack_range_m", 0.0))
	if attack_range_m <= 0.0:
		return _rejected("AUTHORITATIVE_ATTACK_RANGE_NOT_PROJECTED")
	var distance_m: float = _physical_distance_to(target)
	var blocker: Dictionary = blocker_probe(target)
	if distance_m <= attack_range_m and blocker.get("blocked") != true:
		return _prepare_attack_request(target, request_source)
	var destination: Vector3 = approach_destination_for(target, attack_range_m)
	var path: Dictionary = _player.validate_destination(destination)
	if path.get("status") != "PASS":
		_present_blocked(target, "COMBAT_PATH_INVALID")
		return _rejected("COMBAT_PATH_INVALID", {"path_result": path})
	var movement: Dictionary = _player.request_move(destination)
	if movement.get("status") != "PASS":
		_present_blocked(target, "COMBAT_APPROACH_REJECTED")
		return _rejected("COMBAT_APPROACH_REJECTED", {"movement_result": movement})
	_pending_approach.clear()
	_pending_approach[target.target_ref] = {
		"target_ref": target.target_ref,
		"instance_id": target.get_instance_id(),
		"request_source": request_source,
		"selection_ref_at_start": _main_runtime.selected_target_ref(),
		"approach_destination": destination,
	}
	_observe_attack(true, target.target_ref)
	return {
		"status": "PASS",
		"intent": "CHASE_ATTACK_PENDING",
		"target_ref": target.target_ref,
		"physical_distance_m": distance_m,
		"attack_range_m": attack_range_m,
		"movement_result": movement,
		"attack_requested": false,
		"remote_attack": false,
		"authority": AUTHORITY,
	}


func process_pending_approach_once() -> Dictionary:
	if _pending_approach.is_empty():
		return {"status": "PASS", "pending": false, "authority": AUTHORITY}
	var target_ref_value: String = str(_pending_approach.keys()[0])
	var target: AndromedaInteractionTarget = actor_for_ref(target_ref_value)
	if target == null:
		_pending_approach.clear()
		_observe_attack(false, "")
		return _rejected("STALE_OR_REMOVED_COMBAT_TARGET")
	var validation: Dictionary = evaluate_attack_candidate(target)
	if validation.get("status") == "PASS":
		var request_source: String = str(
			_pending_approach[target_ref_value].get("request_source", "UNKNOWN")
		)
		_pending_approach.clear()
		return _prepare_attack_request(target, "%s_AFTER_APPROACH" % request_source)
	if str(validation.get("reason", "")) == "COMBAT_DISTANCE_EXCEEDED":
		return {
			"status": "PASS",
			"pending": true,
			"target_ref": target_ref_value,
			"authority": AUTHORITY,
		}
	_pending_approach.clear()
	_observe_attack(false, "")
	_present_blocked(target, str(validation.get("reason", "INTERACTION_BLOCKED")))
	return validation


func evaluate_attack_candidate(target: AndromedaInteractionTarget) -> Dictionary:
	var validation: Dictionary = _validate_target(target)
	if validation.get("status") != "PASS":
		return validation
	var range_m: float = float(target.get_meta("authority_attack_range_m", 0.0))
	var distance_m: float = _physical_distance_to(target)
	if not is_finite(distance_m) or range_m <= 0.0 or distance_m > range_m:
		return _rejected("COMBAT_DISTANCE_EXCEEDED", {
			"physical_distance_m": distance_m,
			"attack_range_m": range_m,
		})
	var blocker: Dictionary = blocker_probe(target)
	if blocker.get("blocked") == true:
		return _rejected("COMBAT_BLOCKED_BY_COLLISION", {"blocker_result": blocker})
	return {
		"status": "PASS",
		"target_ref": target.target_ref,
		"physical_distance_m": distance_m,
		"attack_range_m": range_m,
		"authority": AUTHORITY,
	}


func approach_destination_for(target: AndromedaInteractionTarget, attack_range_m: float) -> Vector3:
	var target_position: Vector3 = target.global_position
	var away := Vector2(
		_player.global_position.x - target_position.x,
		_player.global_position.z - target_position.z
	)
	if away.length_squared() <= 0.000001:
		away = Vector2.RIGHT
	away = away.normalized()
	var stand_off: float = maxf(
		MIN_PRESENTATION_STAND_OFF_M,
		attack_range_m * PRESENTATION_STAND_OFF_FACTOR
	)
	return Vector3(
		target_position.x + away.x * stand_off,
		target_position.y,
		target_position.z + away.y * stand_off
	)


func blocker_probe(target: AndromedaInteractionTarget) -> Dictionary:
	if _player == null or target == null or not is_instance_valid(target):
		return _rejected("PLAYER_AND_COMBAT_TARGET_REQUIRED")
	var world: World3D = _player.get_world_3d()
	if world == null:
		return _rejected("WORLD_3D_REQUIRED")
	var start: Vector3 = _player.global_position + Vector3(0.0, 0.65, 0.0)
	var finish: Vector3 = target.pointer_world_position()
	var query := PhysicsRayQueryParameters3D.create(start, finish, BLOCKER_MASK, [_player.get_rid()])
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


func project_combat_snapshot(snapshot: Dictionary) -> Dictionary:
	var envelope: Dictionary = _validate_external_snapshot(snapshot)
	if envelope.get("status") != "PASS":
		return envelope
	var sequence: int = int(snapshot.get("snapshot_sequence", -1))
	if sequence <= _last_snapshot_sequence:
		return _rejected("STALE_OR_DUPLICATE_COMBAT_SNAPSHOT")
	var targets_value: Variant = snapshot.get("combat_targets", [])
	if not targets_value is Array:
		return _rejected("INVALID_COMBAT_TARGET_LIST")
	var by_slot: Dictionary = {}
	for value: Variant in targets_value:
		if not value is Dictionary:
			return _rejected("INVALID_COMBAT_TARGET_ENTRY")
		var entry: Dictionary = value
		var slot: String = str(entry.get("slot", "")).strip_edges().to_upper()
		var preflight: Dictionary = _preflight_target_entry(entry)
		if preflight.get("status") != "PASS":
			return preflight
		if by_slot.has(slot):
			return _rejected("DUPLICATE_COMBAT_TARGET_SLOT")
		by_slot[slot] = entry
	if not by_slot.has("COMMON") or not by_slot.has("ALPHA"):
		return _rejected("COMMON_AND_ALPHA_TARGETS_REQUIRED")
	var player_transform: Dictionary = snapshot.get("transform", {})
	if not _anchor_initialized:
		_server_anchor = _position_from_dictionary(player_transform)
		_client_anchor = _player.global_position
		_anchor_initialized = true
	var projected: Array[Dictionary] = []
	_actors_by_ref.clear()
	for slot: String in ["COMMON", "ALPHA"]:
		var actor: AndromedaInteractionTarget = _common_actor if slot == "COMMON" else _alpha_actor
		var entry: Dictionary = by_slot[slot]
		var previous_ref: String = actor.target_ref
		var next_ref: String = str(entry.get("target_ref", "")).strip_edges()
		if previous_ref != next_ref and _main_runtime.selected_target_ref() == previous_ref:
			_main_runtime.clear_selection_if_target_ref(previous_ref)
		var identity: Dictionary = actor.project_external_identity(
			next_ref,
			str(entry.get("display_name", next_ref)),
			bool(entry.get("hostile", false)),
			true
		)
		if identity.get("status") != "PASS":
			return identity
		actor.set_meta("combat_rank", "ALPHA" if slot == "ALPHA" else "COMMON")
		actor.set_meta("authority_combat_rank", str(entry.get("combat_rank", "COMMON")))
		actor.set_meta("authority_attack_range_m", float(entry.get("attack_range_m", 0.0)))
		actor.set_meta("authority_position", (entry.get("position", {}) as Dictionary).duplicate(true))
		var server_position: Vector3 = _position_from_dictionary(entry.get("position", {}))
		var local_position: Vector3 = _client_anchor + (server_position - _server_anchor)
		if slot == "ALPHA" and local_position.distance_to(_client_anchor) < 0.5:
			local_position += Vector3(0.0, 0.0, -2.2)
		actor.global_position = Vector3(local_position.x, actor.global_position.y, local_position.z)
		_actors_by_ref[next_ref] = actor
		projected.append({
			"slot": slot,
			"target_ref": next_ref,
			"identity": identity,
			"local_position": actor.global_position,
			"server_position": server_position,
		})
	var combat_actors: Array[Node3D] = [_common_actor, _alpha_actor]
	var rebind: Dictionary = _hud.rebind_external_combat_actors(combat_actors)
	if rebind.get("status") != "PASS":
		return rebind
	var combat: Dictionary = snapshot.get("combat_presentation", {})
	var player_projection: Dictionary = combat.get("player", {})
	if player_projection.has("hp_fraction"):
		_hud.project_player_combat_vitals(
			float(player_projection.get("hp_fraction", 1.0)),
			float(player_projection.get("protection_fraction", 0.0)),
			bool(player_projection.get("relevant", false)),
			"AUTHORITATIVE_COMBAT_SNAPSHOT"
		)
	for entry_value: Variant in combat.get("targets", []):
		if entry_value is Dictionary:
			var entry: Dictionary = entry_value
			_hud.project_enemy_combat_vitals(
				str(entry.get("target_ref", "")),
				float(entry.get("hp_fraction", 1.0)),
				float(entry.get("shield_fraction", 0.0)),
				bool(entry.get("engaged", false)),
				"AUTHORITATIVE_COMBAT_SNAPSHOT"
			)
	_snapshot_session_ref = str(snapshot.get("session_ref", ""))
	_last_snapshot_sequence = sequence
	_last_projection = {
		"status": "PASS",
		"snapshot_sequence": sequence,
		"projected_targets": projected,
		"hud_rebind": rebind,
		"combat_outcomes_decided_locally": false,
		"authority": AUTHORITY,
	}
	combat_snapshot_projected.emit(_last_projection.duplicate(true))
	return _last_projection.duplicate(true)


func project_attack_result(result: Dictionary) -> Dictionary:
	if result.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_COMBAT_RESULT")
	var session := _session()
	if session == null or str(result.get("session_ref", "")) != session.session_ref():
		return _rejected("COMBAT_RESULT_SESSION_MISMATCH")
	var target_ref_value: String = str(result.get("target_ref", "")).strip_edges()
	var target: AndromedaInteractionTarget = actor_for_ref(target_ref_value)
	if target == null:
		return _rejected("COMBAT_RESULT_TARGET_NOT_FOUND")
	var sequence_value: Variant = result.get("result_sequence", null)
	if typeof(sequence_value) != TYPE_INT or int(sequence_value) < 0:
		return _rejected("INVALID_COMBAT_RESULT_SEQUENCE")
	if int(sequence_value) <= int(_result_sequences.get(target_ref_value, -1)):
		return _rejected("STALE_OR_DUPLICATE_COMBAT_RESULT")
	_result_sequences[target_ref_value] = int(sequence_value)
	_pending_approach.erase(target_ref_value)
	_inflight_requests.erase(target_ref_value)
	_observe_attack(false, "")
	var target_state: Dictionary = result.get("target_state", {})
	if not target_state.is_empty():
		var maximum: float = float(target_state.get("max_health", 0.0))
		var current: float = float(target_state.get("health", 0.0))
		var fraction: float = 0.0 if maximum <= 0.0 else clampf(current / maximum, 0.0, 1.0)
		_hud.project_enemy_combat_vitals(
			target_ref_value,
			fraction,
			0.0,
			true,
			"AUTHORITATIVE_COMBAT_RESULT"
		)
	var semantic_feedback: Dictionary = {}
	if str(result.get("status", "")).to_upper() == "PASS":
		if bool(result.get("lethal", false)):
			semantic_feedback = _hud.present_combat_event({
				"token": "TARGET_DEFEATED",
				"target_ref": target_ref_value,
				"confirmed_externally": true,
			})
		elif bool(result.get("hit", false)):
			semantic_feedback = _hud.present_combat_event({
				"token": "COMBAT_CRITICAL_HIT" if bool(result.get("critical", false)) else "COMBAT_HIT",
				"target_ref": target_ref_value,
				"strength": "NORMAL",
				"confirmed_externally": true,
			})
	else:
		semantic_feedback = _hud.present_combat_event({
			"token": "INTERACTION_BLOCKED",
			"target_ref": target_ref_value,
			"confirmed_externally": true,
		})
	var projected := {
		"status": "PASS",
		"authoritative_result_status": str(result.get("status", "REJECTED")),
		"reason": str(result.get("reason", "")),
		"target_ref": target_ref_value,
		"result_sequence": int(sequence_value),
		"semantic_feedback": semantic_feedback,
		"selection_preserved": _main_runtime.selected_target_ref() == str(
			_last_request.get("selection_ref_at_request", _main_runtime.selected_target_ref())
		),
		"damage_decided_locally": false,
		"hit_decided_locally": false,
		"critical_decided_locally": false,
		"cooldown_decided_locally": false,
		"death_decided_locally": false,
		"authority": AUTHORITY,
	}
	attack_result_projected.emit(projected.duplicate(true))
	return projected


func actor_for_ref(target_ref_value: String) -> AndromedaInteractionTarget:
	var value: Variant = _actors_by_ref.get(target_ref_value.strip_edges())
	if not is_instance_valid(value):
		_actors_by_ref.erase(target_ref_value.strip_edges())
		return null
	return value as AndromedaInteractionTarget


func pending_target_ref() -> String:
	return str(_pending_approach.keys()[0]) if not _pending_approach.is_empty() else ""


func inflight_request_count() -> int:
	return _inflight_requests.size()


func has_inflight_request(target_ref_value: String) -> bool:
	return _inflight_requests.has(target_ref_value.strip_edges())


func last_request() -> Dictionary:
	return _last_request.duplicate(true)


func last_projection() -> Dictionary:
	return _last_projection.duplicate(true)


func clear_client_request_tracking() -> void:
	_pending_approach.clear()
	_inflight_requests.clear()
	_last_request.clear()
	_observe_attack(false, "")


func contract_snapshot() -> Dictionary:
	return {
		"client_command": "REQUEST_ATTACK",
		"client_params": ["target_ref"],
		"hostility_authority": false,
		"range_authority": false,
		"hit_authority": false,
		"critical_authority": false,
		"damage_authority": false,
		"cooldown_authority": false,
		"hp_authority": false,
		"death_authority": false,
		"xp_authority": false,
		"loot_authority": false,
		"backend_substitute": false,
		"authority": AUTHORITY,
	}


func _prepare_attack_request(
	target: AndromedaInteractionTarget,
	request_source: String
) -> Dictionary:
	var eligibility: Dictionary = evaluate_attack_candidate(target)
	if eligibility.get("status") != "PASS":
		_present_blocked(target, str(eligibility.get("reason", "INTERACTION_BLOCKED")))
		return eligibility
	if _inflight_requests.has(target.target_ref):
		return _rejected("ATTACK_REQUEST_ALREADY_INFLIGHT", {
			"target_ref": target.target_ref,
			"deduplicated": true,
		})
	var bridge := _bridge()
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	var params := {"target_ref": target.target_ref}
	var built: Dictionary = bridge.build_command_envelope("REQUEST_ATTACK", params)
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
			"REQUEST_ATTACK", params, str(envelope.get("command_ref", ""))
		)
		submitted = transport_result.get("status") == "PASS"
	_last_request = {
		"status": "PASS",
		"intent": "REQUEST_ATTACK",
		"target_ref": target.target_ref,
		"request_source": request_source,
		"selection_ref_at_request": _main_runtime.selected_target_ref(),
		"physical_distance_m": float(eligibility.get("physical_distance_m", INF)),
		"attack_range_m": float(eligibility.get("attack_range_m", 0.0)),
		"intent_envelope": built,
		"transport_result": transport_result,
		"transport_submitted": submitted,
		"player_ref_supplied": false,
		"damage_supplied": false,
		"critical_supplied": false,
		"hit_supplied": false,
		"cooldown_supplied": false,
		"authority": AUTHORITY,
	}
	_pending_approach.erase(target.target_ref)
	_inflight_requests[target.target_ref] = _last_request.duplicate(true)
	_observe_attack(true, target.target_ref)
	attack_request_prepared.emit(_last_request.duplicate(true))
	return _last_request.duplicate(true)


func _validate_target(target: AndromedaInteractionTarget) -> Dictionary:
	if target == null or not is_instance_valid(target) or not target.is_inside_tree():
		return _rejected("STALE_OR_REMOVED_COMBAT_TARGET")
	if actor_for_ref(target.target_ref) != target:
		return _rejected("WRONG_OR_UNREGISTERED_COMBAT_TARGET")
	if target.target_kind != AndromedaInputRouter.HIT_ACTOR or not target.hostile:
		return _rejected("TARGET_NOT_PROJECTED_HOSTILE_ACTOR")
	return {"status": "PASS", "authority": AUTHORITY}


func _physical_distance_to(target: AndromedaInteractionTarget) -> float:
	return _player.global_position.distance_to(target.global_position)


func _preflight_target_entry(entry: Dictionary) -> Dictionary:
	var slot: String = str(entry.get("slot", "")).strip_edges().to_upper()
	if slot not in ["COMMON", "ALPHA"]:
		return _rejected("UNSUPPORTED_COMBAT_TARGET_SLOT")
	if str(entry.get("target_ref", "")).strip_edges().is_empty():
		return _rejected("EMPTY_COMBAT_TARGET_REF")
	if entry.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_COMBAT_TARGET")
	if str(entry.get("target_kind", "")).strip_edges().to_upper() != "ACTOR":
		return _rejected("UNSUPPORTED_COMBAT_TARGET_KIND")
	if not bool(entry.get("hostile", false)):
		return _rejected("NON_HOSTILE_COMBAT_TARGET_PROJECTION")
	if not _valid_number(entry.get("attack_range_m")) or float(entry.get("attack_range_m")) <= 0.0:
		return _rejected("INVALID_AUTHORITATIVE_ATTACK_RANGE")
	var position: Variant = entry.get("position")
	if not position is Dictionary:
		return _rejected("INVALID_COMBAT_TARGET_POSITION")
	for key: String in ["iso_x_m", "iso_y_m", "altitude_m"]:
		if not _valid_number((position as Dictionary).get(key)):
			return _rejected("INVALID_COMBAT_TARGET_POSITION")
	return {"status": "PASS", "authority": AUTHORITY}


func _validate_external_snapshot(snapshot: Dictionary) -> Dictionary:
	if snapshot.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_COMBAT_SNAPSHOT")
	var session := _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	var session_ref_value: String = str(snapshot.get("session_ref", "")).strip_edges()
	if session_ref_value != session.session_ref():
		return _rejected("COMBAT_SNAPSHOT_SESSION_MISMATCH")
	if not _snapshot_session_ref.is_empty() and session_ref_value != _snapshot_session_ref:
		return _rejected("COMBAT_SNAPSHOT_SESSION_CHANGED_WITHOUT_RESET")
	var sequence_value: Variant = snapshot.get("snapshot_sequence", null)
	if typeof(sequence_value) != TYPE_INT or int(sequence_value) < 0:
		return _rejected("INVALID_COMBAT_SNAPSHOT_SEQUENCE")
	return {"status": "PASS", "authority": AUTHORITY}


func _position_from_dictionary(value: Variant) -> Vector3:
	if not value is Dictionary:
		return Vector3.ZERO
	var position: Dictionary = value
	return Vector3(
		float(position.get("iso_x_m", 0.0)),
		float(position.get("altitude_m", 0.0)),
		float(position.get("iso_y_m", 0.0))
	)


func _present_blocked(target: AndromedaInteractionTarget, _reason: String) -> void:
	if _hud != null:
		_hud.present_combat_event({
			"token": "INTERACTION_BLOCKED",
			"target_ref": target.target_ref if target != null else "",
		})


func _observe_attack(active: bool, target_ref_value: String) -> void:
	if _ground_loot_client == null:
		return
	var previous: Dictionary = _ground_loot_client.observed_action_context()
	_ground_loot_client.observe_action_context({
		"attack_active": active,
		"interaction_active": bool(previous.get("interaction_active", false)),
		"chase_target_ref": target_ref_value if active else "",
	})


func _on_bridge_snapshot_applied(snapshot: Dictionary) -> void:
	if snapshot.has("combat_targets"):
		project_combat_snapshot(snapshot)


func _on_bridge_command_result_received(result: Dictionary) -> void:
	if str(result.get("command", "")).strip_edges().to_upper() == "REQUEST_ATTACK":
		project_attack_result(result)


func _on_session_bound(session_ref_value: String, _session_epoch: int) -> void:
	if _snapshot_session_ref.is_empty() or _snapshot_session_ref == session_ref_value:
		return
	_reset_projection_caches()


func _on_session_revoked(_previous_session_ref: String, _session_epoch: int) -> void:
	_reset_projection_caches()


func _reset_projection_caches() -> void:
	_snapshot_session_ref = ""
	_last_snapshot_sequence = -1
	_result_sequences.clear()
	_pending_approach.clear()
	_inflight_requests.clear()
	_actors_by_ref.clear()
	_anchor_initialized = false
	_last_request.clear()
	_last_projection.clear()
	_observe_attack(false, "")


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
