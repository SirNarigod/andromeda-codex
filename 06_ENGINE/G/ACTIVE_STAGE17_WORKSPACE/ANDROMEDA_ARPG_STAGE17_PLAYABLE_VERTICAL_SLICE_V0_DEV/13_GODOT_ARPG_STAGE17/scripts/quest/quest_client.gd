extends Node
class_name AndromedaQuestClient

## B09 quest intent/projection boundary. It uses only Stage12/Stage16A quest IDs and
## never counts progress, completes quests, grants rewards/XP or writes canon.

signal quest_intent_prepared(result: Dictionary)
signal quest_projection_changed(result: Dictionary)
signal quest_feedback_projected(result: Dictionary)

const AUTHORITY := "GODOT_QUEST_CLIENT_PROJECTION_ONLY"
const INTERACTION_RANGE_M := 1.5
const BLOCKER_MASK := 1 | 128
const QUEST_STATES: Array[String] = ["ACTIVE", "READY_TO_TURN_IN", "COMPLETED"]
const OBJECTIVE_STATES: Array[String] = ["PENDING", "COMPLETE"]
const CONTRACTED_QUEST_REFS: Array[String] = [
	"QST-S12-VARGA-MEDIATION",
	"QST-S12-BRIDGE-CONTINUITY",
	"QST-S12-WORKSHOP-CIRCUIT",
	"QST-S12-FRONTIER-SUPPLY",
	"QST-S12-VARGA-ORIENTATION",
]

var _main_runtime: AndromedaMainRuntime
var _player: AndromedaPlayerController
var _hud: AndromedaHUDController
var _npcs_by_ref: Dictionary = {}
var _offers_by_quest: Dictionary = {}
var _offer_by_npc: Dictionary = {}
var _quests_by_ref: Dictionary = {}
var _pending_approach: Dictionary = {}
var _processed_events: Dictionary = {}
var _projection_session_ref: String = ""
var _last_offer_sequence: int = -1
var _last_quest_sequence: int = -1
var _last_event_sequence: int = -1
var _request_serial: int = 0
var _last_intent: Dictionary = {}
var _needs_resync: bool = true
var _bound: bool = false


func _ready() -> void:
	process_physics_priority = 83


func _physics_process(_delta: float) -> void:
	if _bound:
		process_pending_approach_once()


func bind_runtime(
	main_runtime_value: AndromedaMainRuntime,
	player_value: AndromedaPlayerController,
	hud_value: AndromedaHUDController,
	npcs: Array[AndromedaInteractionTarget]
) -> Dictionary:
	if main_runtime_value == null or player_value == null or hud_value == null:
		return _rejected("MAIN_PLAYER_HUD_REQUIRED")
	_main_runtime = main_runtime_value
	_player = player_value
	_hud = hud_value
	for npc: AndromedaInteractionTarget in npcs:
		if npc == null or npc.target_kind != AndromedaInputRouter.HIT_NPC or npc.target_ref.is_empty():
			continue
		_npcs_by_ref[npc.target_ref] = npc
	if not _bound:
		var bridge: AndromedaRuntimeBridge = _bridge()
		if bridge != null and not bridge.snapshot_applied.is_connected(_on_bridge_snapshot_applied):
			bridge.snapshot_applied.connect(_on_bridge_snapshot_applied)
		var session: AndromedaClientSession = _session()
		if session != null:
			if not session.session_bound.is_connected(_on_session_bound):
				session.session_bound.connect(_on_session_bound)
			if not session.session_revoked.is_connected(_on_session_revoked):
				session.session_revoked.connect(_on_session_revoked)
		_hud.quest_panel.quest_accept_requested.connect(_on_ui_accept_requested)
		_hud.quest_panel.quest_choice_requested.connect(_on_ui_choice_requested)
		_hud.quest_panel.close_requested.connect(_on_ui_close_requested)
		_bound = true
	return {"status": "PASS", "npc_count": _npcs_by_ref.size(), "authority": AUTHORITY}


func handle_manual_npc_intent(resolved: Dictionary, target: AndromedaInteractionTarget) -> Dictionary:
	if resolved.get("status") != "PASS" or str(resolved.get("intent", "")) != "APPROACH_INTERACT":
		return _rejected("NPC_CONTEXT_POINTER_INTENT_REQUIRED")
	if target == null or target.target_kind != AndromedaInputRouter.HIT_NPC:
		return _rejected("QUEST_NPC_TARGET_REQUIRED")
	if str(resolved.get("target_ref", "")) != target.target_ref:
		return _rejected("QUEST_NPC_TARGET_REF_MISMATCH")
	return begin_quest_interaction(target, "RIGHT_CLICK")


func handle_selected_interaction(target: AndromedaInteractionTarget) -> Dictionary:
	if target == null or target.target_kind != AndromedaInputRouter.HIT_NPC:
		return _rejected("SELECTED_TARGET_NOT_QUEST_NPC")
	return begin_quest_interaction(target, "CONTEXT_KEY_E")


func begin_quest_interaction(npc: AndromedaInteractionTarget, request_source: String) -> Dictionary:
	if npc == null or not is_instance_valid(npc) or not npc.is_inside_tree():
		return _rejected("STALE_OR_REMOVED_QUEST_NPC")
	if not _npcs_by_ref.has(npc.target_ref) or _npcs_by_ref[npc.target_ref] != npc:
		return _rejected("WRONG_OR_UNREGISTERED_QUEST_NPC")
	if not _offer_by_npc.has(npc.target_ref) and _quest_for_npc(npc.target_ref).is_empty():
		return _rejected("QUEST_STATE_NOT_PROJECTED_FOR_NPC")
	var distance_m: float = _player.global_position.distance_to(npc.global_position)
	if distance_m <= INTERACTION_RANGE_M:
		var access: Dictionary = _evaluate_access(npc)
		if access.get("status") != "PASS":
			return access
		return _open_quest_for_npc(npc, request_source)
	var destination: Vector3 = _approach_destination(npc)
	var path_result: Dictionary = _player.validate_destination(destination)
	if path_result.get("status") != "PASS":
		return _rejected("QUEST_NPC_PATH_INVALID", {"path_result": path_result})
	var movement: Dictionary = _player.request_presentation_approach(destination)
	if movement.get("status") != "PASS":
		return _rejected("QUEST_NPC_APPROACH_REJECTED", {"movement_result": movement})
	_pending_approach = {
		"npc_ref": npc.target_ref,
		"instance_id": npc.get_instance_id(),
		"request_source": request_source,
	}
	return {
		"status": "PASS",
		"intent": "APPROACH_QUEST_NPC_PENDING",
		"npc_ref": npc.target_ref,
		"physical_distance_m": distance_m,
		"interaction_range_m": INTERACTION_RANGE_M,
		"movement_result": movement,
		"quest_ui_opened": false,
		"quest_accepted": false,
		"authority": AUTHORITY,
	}


func process_pending_approach_once() -> Dictionary:
	if _pending_approach.is_empty():
		return {"status": "PASS", "pending": false, "authority": AUTHORITY}
	var npc_ref: String = str(_pending_approach.get("npc_ref", ""))
	var npc_value: Variant = _npcs_by_ref.get(npc_ref)
	if not is_instance_valid(npc_value):
		_pending_approach.clear()
		return _rejected("STALE_OR_REMOVED_QUEST_NPC")
	var npc := npc_value as AndromedaInteractionTarget
	if npc.get_instance_id() != int(_pending_approach.get("instance_id", -1)):
		_pending_approach.clear()
		return _rejected("STALE_OR_REPLACED_QUEST_NPC")
	var distance_m: float = _player.global_position.distance_to(npc.global_position)
	if distance_m > INTERACTION_RANGE_M:
		return {"status": "PASS", "pending": true, "physical_distance_m": distance_m, "authority": AUTHORITY}
	var access: Dictionary = _evaluate_access(npc)
	if access.get("status") != "PASS":
		_pending_approach.clear()
		return access
	var source: String = str(_pending_approach.get("request_source", "APPROACH"))
	_pending_approach.clear()
	return _open_quest_for_npc(npc, "%s_AFTER_APPROACH" % source)


func project_offer_snapshot(snapshot: Dictionary) -> Dictionary:
	var external: Dictionary = _validate_external(snapshot, "QUEST_OFFER_SNAPSHOT")
	if external.get("status") != "PASS":
		return external
	var sequence: int = _sequence(snapshot.get("snapshot_sequence"))
	if sequence < 0:
		return _rejected("INVALID_QUEST_OFFER_SEQUENCE")
	if sequence <= _last_offer_sequence:
		return _rejected("STALE_OR_DUPLICATE_QUEST_OFFER_SNAPSHOT")
	var offers_value: Variant = snapshot.get("offers", [])
	if not offers_value is Array:
		return _rejected("INVALID_QUEST_OFFER_LIST")
	var next_offers: Dictionary = {}
	var next_by_npc: Dictionary = {}
	for offer_value: Variant in offers_value:
		if not offer_value is Dictionary:
			return _rejected("INVALID_QUEST_OFFER_ENTRY")
		var offer: Dictionary = offer_value
		var quest_ref: String = str(offer.get("quest_ref", "")).strip_edges()
		var npc_ref: String = str(offer.get("npc_ref", "")).strip_edges()
		if quest_ref not in CONTRACTED_QUEST_REFS:
			return _rejected("UNCONTRACTED_QUEST_REF")
		if not _npcs_by_ref.has(npc_ref):
			return _rejected("QUEST_OFFER_NPC_NOT_FOUND")
		if next_offers.has(quest_ref):
			return _rejected("DUPLICATE_QUEST_OFFER_REF")
		if not offer.get("objectives", []) is Array or not offer.get("choices", []) is Array:
			return _rejected("INVALID_QUEST_OFFER_PRESENTATION_FIELDS")
		next_offers[quest_ref] = offer.duplicate(true)
		next_by_npc[npc_ref] = quest_ref
	_projection_session_ref = str(snapshot.get("session_ref", ""))
	_last_offer_sequence = sequence
	_offers_by_quest = next_offers
	_offer_by_npc = next_by_npc
	_needs_resync = false
	var result := {
		"status": "PASS",
		"snapshot_sequence": sequence,
		"offer_count": _offers_by_quest.size(),
		"offers_authored_locally": false,
		"authority": AUTHORITY,
	}
	quest_projection_changed.emit(result.duplicate(true))
	return result


func project_quest_snapshot(snapshot: Dictionary) -> Dictionary:
	var external: Dictionary = _validate_external(snapshot, "QUEST_STATE_SNAPSHOT")
	if external.get("status") != "PASS":
		return external
	var sequence: int = _sequence(snapshot.get("snapshot_sequence"))
	if sequence < 0:
		return _rejected("INVALID_QUEST_STATE_SEQUENCE")
	if sequence <= _last_quest_sequence:
		return _rejected("STALE_OR_DUPLICATE_QUEST_STATE_SNAPSHOT")
	var quests_value: Variant = snapshot.get("quests", [])
	if not quests_value is Array:
		return _rejected("INVALID_QUEST_STATE_LIST")
	var next_quests: Dictionary = {}
	for quest_value: Variant in quests_value:
		if not quest_value is Dictionary:
			return _rejected("INVALID_QUEST_STATE_ENTRY")
		var quest: Dictionary = quest_value
		var validation: Dictionary = _validate_quest_projection(quest)
		if validation.get("status") != "PASS":
			return validation
		var quest_ref: String = str(quest.get("quest_ref", ""))
		if next_quests.has(quest_ref):
			return _rejected("DUPLICATE_QUEST_STATE_REF")
		next_quests[quest_ref] = quest.duplicate(true)
	_projection_session_ref = str(snapshot.get("session_ref", ""))
	_last_quest_sequence = sequence
	_quests_by_ref = next_quests
	_needs_resync = false
	var current: Dictionary = {}
	if not _hud.quest_panel.current_quest_ref().is_empty():
		current = _quests_by_ref.get(_hud.quest_panel.current_quest_ref(), {})
	var ui_result: Dictionary = {}
	if not current.is_empty():
		ui_result = _hud.project_quest_state(current)
	var result := {
		"status": "PASS",
		"snapshot_sequence": sequence,
		"quest_count": _quests_by_ref.size(),
		"ui_projection": ui_result,
		"objective_completion_decided_locally": false,
		"quest_completion_decided_locally": false,
		"reward_granted_locally": false,
		"xp_granted_locally": false,
		"authority": AUTHORITY,
	}
	quest_projection_changed.emit(result.duplicate(true))
	return result


func project_quest_event(event: Dictionary) -> Dictionary:
	var external: Dictionary = _validate_external(event, "QUEST_EVENT")
	if external.get("status") != "PASS":
		return external
	var sequence: int = _sequence(event.get("event_sequence"))
	if sequence < 0:
		return _rejected("INVALID_QUEST_EVENT_SEQUENCE")
	if sequence <= _last_event_sequence:
		return _rejected("STALE_OR_DUPLICATE_QUEST_EVENT")
	var event_ref: String = str(event.get("event_ref", "")).strip_edges()
	if event_ref.is_empty() or _processed_events.has(event_ref):
		return _rejected("EMPTY_OR_DUPLICATE_QUEST_EVENT_REF")
	var quest_ref: String = str(event.get("quest_ref", "")).strip_edges()
	if quest_ref not in CONTRACTED_QUEST_REFS:
		return _rejected("UNCONTRACTED_QUEST_REF")
	_last_event_sequence = sequence
	_processed_events[event_ref] = true
	var ui_result: Dictionary = _hud.present_quest_event(event)
	var result := {
		"status": "PASS",
		"event_ref": event_ref,
		"quest_ref": quest_ref,
		"ui_projection": ui_result,
		"local_progress_changed": false,
		"local_completion_changed": false,
		"local_reward_granted": false,
		"local_xp_granted": false,
		"authority": AUTHORITY,
	}
	quest_feedback_projected.emit(result.duplicate(true))
	return result


func request_accept(quest_ref_value: String) -> Dictionary:
	if _needs_resync:
		return _rejected("QUEST_RESYNC_REQUIRED")
	var quest_ref: String = quest_ref_value.strip_edges()
	if not _offers_by_quest.has(quest_ref):
		return _rejected("QUEST_OFFER_NOT_PROJECTED")
	return _prepare_intent("ACCEPT_QUEST", {
		"quest_ref": quest_ref,
		"client_presentation_only": true,
	})


func request_decline(_quest_ref_value: String) -> Dictionary:
	return _rejected("QUEST_DECLINE_NOT_CONTRACTED_IN_STAGE16A_B09")


func request_choice(quest_ref_value: String, choice_ref_value: String) -> Dictionary:
	if _needs_resync:
		return _rejected("QUEST_RESYNC_REQUIRED")
	var quest_ref: String = quest_ref_value.strip_edges()
	var choice_ref: String = choice_ref_value.strip_edges()
	var source: Dictionary = _offers_by_quest.get(quest_ref, _quests_by_ref.get(quest_ref, {}))
	if source.is_empty():
		return _rejected("QUEST_STATE_NOT_PROJECTED")
	if not _choice_exists(source, choice_ref):
		return _rejected("QUEST_CHOICE_NOT_PROJECTED")
	return _prepare_intent("QUEST_INTERACTION_CHOICE", {
		"quest_ref": quest_ref,
		"choice_ref": choice_ref,
		"client_presentation_only": true,
	})


func projected_offer(quest_ref: String) -> Dictionary:
	var value: Variant = _offers_by_quest.get(quest_ref.strip_edges(), {})
	return value.duplicate(true) if value is Dictionary else {}


func projected_quest(quest_ref: String) -> Dictionary:
	var value: Variant = _quests_by_ref.get(quest_ref.strip_edges(), {})
	return value.duplicate(true) if value is Dictionary else {}


func last_intent() -> Dictionary:
	return _last_intent.duplicate(true)


func needs_resync() -> bool:
	return _needs_resync


func contract_snapshot() -> Dictionary:
	return {
		"contracted_quest_refs": CONTRACTED_QUEST_REFS.duplicate(),
		"quest_states": QUEST_STATES.duplicate(),
		"objective_states": OBJECTIVE_STATES.duplicate(),
		"decline_intent_contracted": false,
		"objective_authority": false,
		"completion_authority": false,
		"reward_authority": false,
		"xp_authority": false,
		"canonical_authority": false,
		"local_kill_counting": false,
		"local_pickup_counting": false,
		"local_gather_counting": false,
		"backend_substitute": false,
		"invented_quest": false,
		"invented_endpoint": false,
		"authority": AUTHORITY,
	}


func _open_quest_for_npc(npc: AndromedaInteractionTarget, request_source: String) -> Dictionary:
	var quest_ref: String = str(_offer_by_npc.get(npc.target_ref, ""))
	var ui_result: Dictionary
	if not quest_ref.is_empty():
		ui_result = _hud.open_quest_offer(_offers_by_quest[quest_ref])
	else:
		var quest: Dictionary = _quest_for_npc(npc.target_ref)
		if quest.is_empty():
			return _rejected("NO_PROJECTED_QUEST_FOR_NPC")
		quest_ref = str(quest.get("quest_ref", ""))
		ui_result = _hud.open_quest_state(quest)
	return {
		"status": "PASS",
		"intent": "OPEN_QUEST_UI",
		"request_source": request_source,
		"npc_ref": npc.target_ref,
		"quest_ref": quest_ref,
		"ui_projection": ui_result,
		"quest_accepted": false,
		"quest_completed": false,
		"reward_granted": false,
		"authority": AUTHORITY,
	}


func _quest_for_npc(npc_ref: String) -> Dictionary:
	for quest_value: Variant in _quests_by_ref.values():
		if quest_value is Dictionary and str(quest_value.get("npc_ref", "")) == npc_ref:
			return (quest_value as Dictionary).duplicate(true)
	return {}


func _validate_quest_projection(quest: Dictionary) -> Dictionary:
	var quest_ref: String = str(quest.get("quest_ref", "")).strip_edges()
	if quest_ref not in CONTRACTED_QUEST_REFS:
		return _rejected("UNCONTRACTED_QUEST_REF")
	if str(quest.get("state", "")).to_upper() not in QUEST_STATES:
		return _rejected("INVALID_QUEST_STATE")
	if str(quest.get("npc_ref", "")).strip_edges().is_empty():
		return _rejected("QUEST_NPC_REF_REQUIRED")
	var objectives_value: Variant = quest.get("objectives", [])
	if not objectives_value is Array:
		return _rejected("INVALID_QUEST_OBJECTIVES")
	for objective_value: Variant in objectives_value:
		if not objective_value is Dictionary:
			return _rejected("INVALID_QUEST_OBJECTIVE_ENTRY")
		if str(objective_value.get("state", "")).to_upper() not in OBJECTIVE_STATES:
			return _rejected("INVALID_QUEST_OBJECTIVE_STATE")
	if not quest.get("choices", []) is Array:
		return _rejected("INVALID_QUEST_CHOICES")
	return {"status": "PASS", "authority": AUTHORITY}


func _prepare_intent(command: String, params: Dictionary) -> Dictionary:
	var bridge: AndromedaRuntimeBridge = _bridge()
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	_request_serial += 1
	var prepared_params: Dictionary = params.duplicate(true)
	prepared_params["request_ref"] = "B09-QUEST-REQUEST-%06d" % _request_serial
	var built: Dictionary = bridge.build_command_envelope(command, prepared_params)
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
			command, prepared_params, str(envelope.get("command_ref", ""))
		)
		submitted = transport_result.get("status") == "PASS"
	_last_intent = {
		"status": "PASS",
		"intent": command,
		"request_ref": prepared_params["request_ref"],
		"intent_envelope": built,
		"transport_result": transport_result,
		"transport_submitted": submitted,
		"objective_mutated_locally": false,
		"quest_completed_locally": false,
		"reward_granted_locally": false,
		"xp_granted_locally": false,
		"canonical_mutation": false,
		"authority": AUTHORITY,
	}
	quest_intent_prepared.emit(_last_intent.duplicate(true))
	return _last_intent.duplicate(true)


func _evaluate_access(npc: AndromedaInteractionTarget) -> Dictionary:
	if _player.global_position.distance_to(npc.global_position) > INTERACTION_RANGE_M:
		return _rejected("QUEST_NPC_DISTANCE_EXCEEDED")
	var world: World3D = _player.get_world_3d()
	if world == null:
		return _rejected("WORLD_3D_REQUIRED")
	var start: Vector3 = _player.global_position + Vector3(0.0, 0.55, 0.0)
	var finish: Vector3 = npc.global_position + Vector3(0.0, 0.55, 0.0)
	var excluded: Array[RID] = [_player.get_rid()]
	if npc.has_method("get_rid"):
		var npc_rid: RID = npc.call("get_rid")
		if npc_rid.is_valid():
			excluded.append(npc_rid)
	var query := PhysicsRayQueryParameters3D.create(start, finish, BLOCKER_MASK, excluded)
	query.collide_with_areas = false
	query.collide_with_bodies = true
	if not world.direct_space_state.intersect_ray(query).is_empty():
		return _rejected("QUEST_NPC_BLOCKED_BY_COLLISION")
	var path_result: Dictionary = _player.validate_destination(_approach_destination(npc))
	if path_result.get("status") != "PASS":
		return _rejected("QUEST_NPC_PATH_INVALID")
	return {"status": "PASS", "authority": AUTHORITY}


func _approach_destination(npc: AndromedaInteractionTarget) -> Vector3:
	var target_position: Vector3 = npc.global_position
	var away := Vector2(_player.global_position.x - target_position.x, _player.global_position.z - target_position.z)
	if away.length_squared() <= 0.000001:
		away = Vector2.RIGHT
	away = away.normalized()
	return Vector3(target_position.x + away.x, target_position.y, target_position.z + away.y)


func _choice_exists(source: Dictionary, choice_ref: String) -> bool:
	var choices_value: Variant = source.get("choices", [])
	if not choices_value is Array:
		return false
	for choice_value: Variant in choices_value:
		if choice_value is Dictionary and str(choice_value.get("choice_ref", "")) == choice_ref:
			return true
	return false


func _validate_external(payload: Dictionary, label: String) -> Dictionary:
	if payload.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_%s" % label)
	var session: AndromedaClientSession = _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	var session_ref_value: String = str(payload.get("session_ref", "")).strip_edges()
	if session_ref_value != session.session_ref():
		return _rejected("SESSION_MISMATCH")
	if not _projection_session_ref.is_empty() and session_ref_value != _projection_session_ref:
		return _rejected("QUEST_PROJECTION_SESSION_MISMATCH")
	return {"status": "PASS", "authority": AUTHORITY}


func _sequence(value: Variant) -> int:
	if typeof(value) != TYPE_INT or typeof(value) == TYPE_BOOL or int(value) < 0:
		return -1
	return int(value)


func _on_ui_accept_requested(quest_ref: String) -> void:
	request_accept(quest_ref)


func _on_ui_choice_requested(quest_ref: String, choice_ref: String) -> void:
	request_choice(quest_ref, choice_ref)


func _on_ui_close_requested() -> void:
	_hud.close_active_modal()


func _on_bridge_snapshot_applied(snapshot: Dictionary) -> void:
	var projection_value: Variant = snapshot.get("quest_projection")
	if not projection_value is Dictionary:
		return
	var projection: Dictionary = projection_value as Dictionary
	var common := {
		"server_authoritative": snapshot.get("server_authoritative"),
		"session_ref": snapshot.get("session_ref"),
		"snapshot_sequence": snapshot.get(
			"presentation_sequence", snapshot.get("snapshot_sequence")
		),
	}
	var offer_snapshot: Dictionary = common.duplicate(true)
	offer_snapshot["offers"] = (projection.get("offers", []) as Array).duplicate(true)
	project_offer_snapshot(offer_snapshot)
	var quest_snapshot: Dictionary = common.duplicate(true)
	quest_snapshot["quests"] = (projection.get("quests", []) as Array).duplicate(true)
	project_quest_snapshot(quest_snapshot)


func _on_session_bound(session_ref_value: String, _session_epoch: int) -> void:
	if not _projection_session_ref.is_empty() and _projection_session_ref != session_ref_value:
		_projection_session_ref = ""
		_last_offer_sequence = -1
		_last_quest_sequence = -1
		_last_event_sequence = -1
		_offers_by_quest.clear()
		_offer_by_npc.clear()
		_quests_by_ref.clear()
		_processed_events.clear()
	_needs_resync = true


func _on_session_revoked(_previous_session_ref: String, _session_epoch: int) -> void:
	_pending_approach.clear()
	_needs_resync = true


func _bridge() -> AndromedaRuntimeBridge:
	return get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge


func _session() -> AndromedaClientSession:
	return get_node_or_null("/root/ClientSession") as AndromedaClientSession


func _rejected(reason: String, detail: Dictionary = {}) -> Dictionary:
	var result := {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
	result.merge(detail, true)
	return result
