extends Node
class_name AndromedaSaveReloadClient

## B10 save/reload client boundary. It prepares command envelopes and rebuilds
## presentation from externally-authoritative restore snapshots; it persists nothing.

signal save_intent_prepared(result: Dictionary)
signal save_result_projected(result: Dictionary)
signal restore_projected(result: Dictionary)
signal restore_state_changed(state: String)

const AUTHORITY := "GODOT_SAVE_RELOAD_CLIENT_ORCHESTRATION_ONLY"
const STATE_READY := "READY"
const STATE_SAVE_PENDING := "SAVE_PENDING"
const STATE_RELOAD_PENDING := "RELOAD_PENDING"
const STATE_RESYNC_REQUIRED := "RESYNC_REQUIRED"
const STATE_RESTORING := "RESTORING"

var _main_runtime: AndromedaMainRuntime
var _player: AndromedaPlayerController
var _hud: AndromedaHUDController
var _ground_loot_client: AndromedaGroundLootPickupClient
var _gathering_client: AndromedaGatheringClient
var _inventory_client: AndromedaInventoryClient
var _vendor_client: AndromedaVendorClient
var _quest_client: AndromedaQuestClient
var _dropped_bag_client: AndromedaDroppedBagClient
var _death_respawn_client: AndromedaDeathRespawnClient
var _streaming_manager: AndromedaStreamingManager
var _state: String = STATE_READY
var _needs_resync: bool = false
var _request_serial: int = 0
var _result_sequence: int = -1
var _restore_sequence: int = -1
# Keyed by save slot_ref. The backend tracks save_sequence PER SLOT
# (andromeda_authority_adapter.py::_request_save():
# self._next_result_sequence("SAVE_SEQUENCE:" + slot_ref)) -- a single global
# "must strictly increase" guard here would reject a legitimate restore of a
# DIFFERENT slot (e.g. "autosave") whose own save_sequence starts at 0/1
# independently of whatever the "manual" slot's sequence has already
# reached. restore_sequence (below) stays a single global int on purpose:
# it comes from _next_transport_sequence(), which IS globally monotonic
# across every command/snapshot, so no per-slot split is needed there.
var _last_restored_save_sequence_by_slot: Dictionary = {}
# request_ref of the REQUEST_RELOAD_RESYNC currently awaiting an authoritative
# result. Used to correlate an incoming REJECTED result to the pending
# reload before releasing RELOAD_PENDING -- a rejection of an unrelated
# command_ref must never clear this client's pending reload.
var _pending_reload_request_ref: String = ""
# Operational state captured immediately before entering RELOAD_PENDING, so a
# legitimate rejection (e.g. OLDER_OR_DUPLICATE_SAVE_SEQUENCE,
# STALE_OR_DUPLICATE_RESTORE_SNAPSHOT) can return the client to where it
# actually was instead of guessing READY.
var _state_before_reload_pending: String = STATE_READY
var _inflight_save_requests: Dictionary = {}
var _last_save_intent: Dictionary = {}
var _last_save_result: Dictionary = {}
var _last_reload_intent: Dictionary = {}
var _restored_projection: Dictionary = {}
var _economy_projection: Dictionary = {}
var _world_projection: Dictionary = {}
var _seen_bound_session: bool = false
var _bound_session_ref: String = ""
var _bound: bool = false


func bind_runtime(
	main_runtime_value: AndromedaMainRuntime,
	player_value: AndromedaPlayerController,
	hud_value: AndromedaHUDController,
	ground_loot_client_value: AndromedaGroundLootPickupClient,
	gathering_client_value: AndromedaGatheringClient,
	inventory_client_value: AndromedaInventoryClient,
	vendor_client_value: AndromedaVendorClient,
	quest_client_value: AndromedaQuestClient,
	dropped_bag_client_value: AndromedaDroppedBagClient,
	death_respawn_client_value: AndromedaDeathRespawnClient,
	streaming_manager_value: AndromedaStreamingManager
) -> Dictionary:
	if (
		main_runtime_value == null
		or player_value == null
		or hud_value == null
		or ground_loot_client_value == null
		or gathering_client_value == null
		or inventory_client_value == null
		or vendor_client_value == null
		or quest_client_value == null
		or dropped_bag_client_value == null
		or death_respawn_client_value == null
		or streaming_manager_value == null
	):
		return _rejected("B10_SAVE_RELOAD_DEPENDENCIES_REQUIRED")
	_main_runtime = main_runtime_value
	_player = player_value
	_hud = hud_value
	_ground_loot_client = ground_loot_client_value
	_gathering_client = gathering_client_value
	_inventory_client = inventory_client_value
	_vendor_client = vendor_client_value
	_quest_client = quest_client_value
	_dropped_bag_client = dropped_bag_client_value
	_death_respawn_client = death_respawn_client_value
	_streaming_manager = streaming_manager_value
	if not _bound:
		var bridge: AndromedaRuntimeBridge = _bridge()
		if bridge != null and not bridge.command_result_received.is_connected(_on_bridge_command_result_received):
			bridge.command_result_received.connect(_on_bridge_command_result_received)
		var session: AndromedaClientSession = _session()
		if session != null:
			if not session.session_bound.is_connected(_on_session_bound):
				session.session_bound.connect(_on_session_bound)
			if not session.session_revoked.is_connected(_on_session_revoked):
				session.session_revoked.connect(_on_session_revoked)
			if session.has_active_session():
				_seen_bound_session = true
				_bound_session_ref = session.session_ref()
		_bound = true
	return {"status": "PASS", "state": _state, "authority": AUTHORITY}


func request_manual_save(slot_ref: String = "manual") -> Dictionary:
	return _prepare_save_intent("MANUAL", slot_ref, "USER_REQUEST")


func request_autosave(reason: String) -> Dictionary:
	var normalized_reason: String = reason.strip_edges().to_upper()
	if normalized_reason.is_empty():
		return _rejected("AUTOSAVE_REASON_REQUIRED")
	return _prepare_save_intent("AUTOSAVE", "autosave", normalized_reason)


func project_save_result(result: Dictionary) -> Dictionary:
	var external: Dictionary = _validate_external(result, "SAVE_RESULT")
	if external.get("status") != "PASS":
		return external
	var sequence_value: Variant = result.get("result_sequence")
	if typeof(sequence_value) != TYPE_INT or typeof(sequence_value) == TYPE_BOOL or int(sequence_value) < 0:
		return _rejected("INVALID_SAVE_RESULT_SEQUENCE")
	var sequence: int = int(sequence_value)
	if sequence <= _result_sequence:
		return _rejected("STALE_OR_DUPLICATE_SAVE_RESULT")
	var request_ref: String = str(result.get("request_ref", "")).strip_edges()
	if request_ref.is_empty() or not _inflight_save_requests.has(request_ref):
		return _rejected("UNKNOWN_OR_CLEARED_SAVE_REQUEST")
	var projected_result: String = str(result.get("result", "")).strip_edges().to_upper()
	if projected_result not in ["CONFIRMED", "FAILED"]:
		return _rejected("INVALID_SAVE_RESULT")
	_result_sequence = sequence
	_inflight_save_requests.erase(request_ref)
	_last_save_result = {
		"status": "PASS",
		"request_ref": request_ref,
		"result": projected_result,
		"save_ref": str(result.get("save_ref", "")),
		"save_sequence": int(result.get("save_sequence", -1)),
		"reason": str(result.get("reason", "")),
		"success_confirmed_externally": projected_result == "CONFIRMED",
		"save_written_locally": false,
		"gameplay_state_mutated": false,
		"authority": AUTHORITY,
	}
	_state = STATE_READY if _inflight_save_requests.is_empty() else STATE_SAVE_PENDING
	if projected_result == "CONFIRMED":
		_hud.project_b10_external_state("SAVE_CONFIRMED", "Save confirmado externamente", false)
	else:
		_hud.project_b10_external_state("SAVE_FAILED", "Falha de save recebida", true)
	save_result_projected.emit(_last_save_result.duplicate(true))
	return _last_save_result.duplicate(true)


func request_reload_resync(slot_ref: String = "manual") -> Dictionary:
	var normalized_slot: String = slot_ref.strip_edges()
	if normalized_slot.is_empty():
		return _rejected("RELOAD_SLOT_REF_REQUIRED")
	var bridge: AndromedaRuntimeBridge = _bridge()
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	_request_serial += 1
	var request_ref: String = "B10-RELOAD-%06d" % _request_serial
	var params := {
		"request_ref": request_ref,
		"slot_ref": normalized_slot,
		"require_resync_before_ready": true,
		"client_presentation_only": true,
	}
	var built: Dictionary = bridge.build_command_envelope("REQUEST_RELOAD_RESYNC", params)
	if built.get("status") != "PASS":
		return built
	var transport: Dictionary = {"status": "NOT_AVAILABLE", "reason": "BRIDGE_NOT_READY_NO_LIVE_BACKEND"}
	var submitted: bool = false
	if bridge.connection_state().get("state") == AndromedaRuntimeBridge.STATE_READY:
		transport = bridge.submit_command("REQUEST_RELOAD_RESYNC", params)
		submitted = transport.get("status") == "PASS"
	if _state != STATE_RELOAD_PENDING:
		_state_before_reload_pending = _state
	_pending_reload_request_ref = request_ref
	_state = STATE_RELOAD_PENDING
	_needs_resync = true
	_player.stop_local_prediction()
	_death_respawn_client.set_restore_input_blocked(true, "RELOAD_RESYNC_PENDING")
	_hud.present_b10_client_pending("RELOAD_PENDING", "Aguardando restore autoritativo")
	_last_reload_intent = {
		"status": "PASS",
		"intent": "REQUEST_RELOAD_RESYNC",
		"request_ref": request_ref,
		"slot_ref": normalized_slot,
		"intent_envelope": built,
		"transport_result": transport,
		"transport_submitted": submitted,
		"restore_fabricated_locally": false,
		"ready_before_resync": false,
		"authority": AUTHORITY,
	}
	restore_state_changed.emit(_state)
	return _last_reload_intent.duplicate(true)


func project_restore_snapshot(snapshot: Dictionary, slot_ref: String = "", request_ref: String = "") -> Dictionary:
	var external: Dictionary = _validate_external(snapshot, "RESTORE_SNAPSHOT")
	if external.get("status") != "PASS":
		# A malformed/non-authoritative payload never reaches the sequence
		# guards below, so nothing else would release RELOAD_PENDING here.
		_release_reload_pending(request_ref)
		return external
	var preflight: Dictionary = _preflight_restore_snapshot(snapshot)
	if preflight.get("status") != "PASS":
		_release_reload_pending(request_ref)
		return preflight
	var restore_sequence: int = int(snapshot.get("restore_sequence"))
	var save_sequence: int = int(snapshot.get("save_sequence"))
	if restore_sequence <= _restore_sequence:
		# This is the client's OWN anti-replay guard -- the backend command
		# itself already returned PASS (it performs the DB swap unconditionally
		# once the slot verifies; andromeda_authority_adapter.py::
		# _request_reload_resync() has no replay check of its own). A legitimate
		# rejection here must still release RELOAD_PENDING or every later
		# operation stays blocked with SAVE_BLOCKED_UNTIL_RESYNC_READY forever.
		_release_reload_pending(request_ref)
		return _rejected("STALE_OR_DUPLICATE_RESTORE_SNAPSHOT")
	# Namespace key comes from the authoritative slot_ref the backend itself
	# returned alongside this restore_snapshot on the REQUEST_RELOAD_RESYNC
	# result (see _on_bridge_command_result_received below) -- never a
	# locally invented label. Callers that omit it (pre-existing direct unit
	# calls with fabricated single-slot fixtures, e.g. b10_runtime_gate.gd)
	# all share the same "" bucket, which reproduces the exact prior
	# behavior among themselves since they never exercised more than one
	# slot in the first place.
	var slot_namespace: String = slot_ref.strip_edges()
	var last_for_slot: int = int(_last_restored_save_sequence_by_slot.get(slot_namespace, -1))
	if save_sequence <= last_for_slot:
		_release_reload_pending(request_ref)
		return _rejected("OLDER_OR_DUPLICATE_SAVE_SEQUENCE")

	_state = STATE_RESTORING
	_needs_resync = true
	_player.stop_local_prediction()
	_death_respawn_client.set_restore_input_blocked(true, "RESTORE_APPLYING")
	restore_state_changed.emit(_state)
	var projections: Dictionary = {}
	var player_projection: Dictionary = snapshot.get("player")
	var position_result: Dictionary = _position_from_projection(player_projection.get("position", {}))
	_player.global_position = position_result.get("position", _player.global_position)
	_player.stop_local_prediction()
	projections["player"] = _hud.apply_presentation_snapshot(
		player_projection.get("presentation", {}) as Dictionary
	)

	var restored_world: Dictionary = snapshot.get("world")
	var active_cell: Dictionary = restored_world.get("active_cell")
	var stream_result: Dictionary = _streaming_manager.set_active_cell(Vector2i(
		int(active_cell.get("x")),
		int(active_cell.get("y"))
	))
	if stream_result.get("status") != "PASS":
		return _restore_failed("WORLD_STREAM_RESTORE_REJECTED", stream_result)
	_world_projection = restored_world.duplicate(true)
	projections["world_streaming"] = stream_result
	if not (restored_world.get("resource_snapshot") as Dictionary).is_empty():
		var resource_result: Dictionary = _gathering_client.project_resource_snapshot(
			restored_world.get("resource_snapshot") as Dictionary
		)
		if resource_result.get("status") != "PASS":
			return _restore_failed("RESOURCE_RESTORE_REJECTED", resource_result)
		projections["resource_nodes"] = resource_result

	var ground_loot_result: Dictionary = _ground_loot_client.project_ground_loot_snapshot(
		snapshot.get("ground_loot_snapshot") as Dictionary
	)
	if ground_loot_result.get("status") != "PASS":
		return _restore_failed("GROUND_LOOT_RESTORE_REJECTED", ground_loot_result)
	projections["ground_loot"] = ground_loot_result

	var preference: Dictionary = snapshot.get("profile_preference")
	var preference_result: Dictionary = _ground_loot_client.project_profile_preference(
		bool(preference.get("auto_pickup")),
		str(snapshot.get("session_ref")),
		int(preference.get("preference_sequence")),
		true
	)
	if preference_result.get("status") != "PASS":
		return _restore_failed("PROFILE_PREFERENCE_RESTORE_REJECTED", preference_result)
	projections["profile_preference"] = preference_result

	var inventory_result: Dictionary = _inventory_client.project_inventory_snapshot(
		snapshot.get("inventory_snapshot") as Dictionary
	)
	if inventory_result.get("status") != "PASS":
		return _restore_failed("INVENTORY_RESTORE_REJECTED", inventory_result)
	projections["inventory"] = inventory_result

	_economy_projection = (snapshot.get("economy_projection") as Dictionary).duplicate(true)
	projections["economy"] = {
		"status": "PASS",
		"projected": true,
		"wallet_mutated_locally": false,
		"authority": AUTHORITY,
	}

	var quest_projection: Dictionary = snapshot.get("quest_projection")
	if not (quest_projection.get("offer_snapshot") as Dictionary).is_empty():
		var offer_result: Dictionary = _quest_client.project_offer_snapshot(
			quest_projection.get("offer_snapshot") as Dictionary
		)
		if offer_result.get("status") != "PASS":
			return _restore_failed("QUEST_OFFER_RESTORE_REJECTED", offer_result)
		projections["quest_offer"] = offer_result
	if not (quest_projection.get("state_snapshot") as Dictionary).is_empty():
		var quest_result: Dictionary = _quest_client.project_quest_snapshot(
			quest_projection.get("state_snapshot") as Dictionary
		)
		if quest_result.get("status") != "PASS":
			return _restore_failed("QUEST_STATE_RESTORE_REJECTED", quest_result)
		projections["quest_state"] = quest_result

	var bag_result: Dictionary = _dropped_bag_client.project_dropped_bag_snapshot(
		snapshot.get("dropped_bag_snapshot") as Dictionary
	)
	if bag_result.get("status") != "PASS":
		return _restore_failed("DROPPED_BAG_RESTORE_REJECTED", bag_result)
	projections["dropped_bags"] = bag_result

	var death_result: Dictionary = _death_respawn_client.project_restored_death_recovery(
		snapshot.get("death_recovery_snapshot") as Dictionary
	)
	if death_result.get("status") != "PASS":
		return _restore_failed("DEATH_RECOVERY_RESTORE_REJECTED", death_result)
	projections["death_recovery"] = death_result

	_restore_sequence = restore_sequence
	_last_restored_save_sequence_by_slot[slot_namespace] = save_sequence
	_restored_projection = snapshot.duplicate(true)
	_pending_reload_request_ref = ""
	_state = STATE_READY
	_needs_resync = false
	_main_runtime.clear_current_target_projection("EXTERNAL_RESTORE_COMPLETE")
	_death_respawn_client.complete_restore_input_gate()
	_hud.project_b10_external_state("RESTORED", "Estado restaurado externamente", false)
	var output := {
		"status": "PASS",
		"restore_ref": str(snapshot.get("restore_ref")),
		"restore_sequence": restore_sequence,
		"save_sequence": save_sequence,
		"projected_channels": projections,
		"ready_after_resync": true,
		"world_input_blocked": _death_respawn_client.world_input_blocked(),
		"presentation_rebuilt_from_external_snapshot": true,
		"save_loaded_locally": false,
		"canonical_state_mutated": false,
		"authority": AUTHORITY,
	}
	restore_state_changed.emit(_state)
	restore_projected.emit(output.duplicate(true))
	return output


func state() -> String:
	return _state


func needs_resync() -> bool:
	return _needs_resync


func last_save_intent() -> Dictionary:
	return _last_save_intent.duplicate(true)


func last_save_result() -> Dictionary:
	return _last_save_result.duplicate(true)


func last_reload_intent() -> Dictionary:
	return _last_reload_intent.duplicate(true)


func restored_projection() -> Dictionary:
	return _restored_projection.duplicate(true)


func economy_projection() -> Dictionary:
	return _economy_projection.duplicate(true)


func world_projection() -> Dictionary:
	return _world_projection.duplicate(true)


func inflight_save_count() -> int:
	return _inflight_save_requests.size()


func contract_snapshot() -> Dictionary:
	return {
		"states": [STATE_READY, STATE_SAVE_PENDING, STATE_RELOAD_PENDING, STATE_RESYNC_REQUIRED, STATE_RESTORING],
		"manual_save_intent": true,
		"autosave_intent": true,
		"resync_before_ready": true,
		"restores": ["PLAYER", "WORLD", "GROUND_LOOT", "PROFILE", "INVENTORY", "BAG", "QUEST", "ECONOMY", "WATER_EXPOSURE", "DEATH_RECOVERY"],
		"scene_tree_pause": false,
		"local_disk_persistence": false,
		"save_success_authority": false,
		"restore_authority": false,
		"ttl_authority": false,
		"death_authority": false,
		"inventory_authority": false,
		"quest_authority": false,
		"economy_authority": false,
		"backend_substitute": false,
		"invented_endpoint": false,
		"authority": AUTHORITY,
	}


func _prepare_save_intent(save_kind: String, slot_ref: String, reason: String) -> Dictionary:
	var session: AndromedaClientSession = _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	if _state in [STATE_RELOAD_PENDING, STATE_RESTORING, STATE_RESYNC_REQUIRED]:
		return _rejected("SAVE_BLOCKED_UNTIL_RESYNC_READY")
	var normalized_slot: String = slot_ref.strip_edges()
	if normalized_slot.is_empty():
		return _rejected("SAVE_SLOT_REF_REQUIRED")
	var bridge: AndromedaRuntimeBridge = _bridge()
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	_request_serial += 1
	var request_ref: String = "B10-%s-SAVE-%06d" % [save_kind, _request_serial]
	var params := {
		"request_ref": request_ref,
		"slot_ref": normalized_slot,
		"save_kind": save_kind,
		"reason": reason,
		"client_presentation_only": true,
	}
	var command: String = "REQUEST_AUTOSAVE" if save_kind == "AUTOSAVE" else "REQUEST_SAVE"
	var built: Dictionary = bridge.build_command_envelope(command, params)
	if built.get("status") != "PASS":
		return built
	var transport: Dictionary = {"status": "NOT_AVAILABLE", "reason": "BRIDGE_NOT_READY_NO_LIVE_BACKEND"}
	var submitted: bool = false
	if bridge.connection_state().get("state") == AndromedaRuntimeBridge.STATE_READY:
		transport = bridge.submit_command(command, params)
		submitted = transport.get("status") == "PASS"
	_last_save_intent = {
		"status": "PASS",
		"intent": command,
		"request_ref": request_ref,
		"slot_ref": normalized_slot,
		"save_kind": save_kind,
		"reason": reason,
		"intent_envelope": built,
		"transport_result": transport,
		"transport_submitted": submitted,
		"success_fabricated_locally": false,
		"scene_tree_paused": get_tree().paused,
		"gameplay_state_mutated": false,
		"authority": AUTHORITY,
	}
	_inflight_save_requests[request_ref] = _last_save_intent.duplicate(true)
	_state = STATE_SAVE_PENDING
	_hud.present_b10_client_pending(
		"AUTOSAVE_PENDING" if save_kind == "AUTOSAVE" else "SAVE_PENDING",
		"Aguardando confirmação externa"
	)
	save_intent_prepared.emit(_last_save_intent.duplicate(true))
	return _last_save_intent.duplicate(true)


func _preflight_restore_snapshot(snapshot: Dictionary) -> Dictionary:
	for key: String in [
		"player", "world", "ground_loot_snapshot", "profile_preference",
		"inventory_snapshot", "economy_projection", "quest_projection",
		"dropped_bag_snapshot", "death_recovery_snapshot",
	]:
		if not snapshot.get(key) is Dictionary:
			return _rejected("MALFORMED_RESTORE_%s" % key.to_upper())
	for sequence_key: String in ["restore_sequence", "save_sequence"]:
		var value: Variant = snapshot.get(sequence_key)
		if typeof(value) != TYPE_INT or typeof(value) == TYPE_BOOL or int(value) < 0:
			return _rejected("INVALID_%s" % sequence_key.to_upper())
	if str(snapshot.get("restore_ref", "")).strip_edges().is_empty():
		return _rejected("RESTORE_REF_REQUIRED")
	var player_projection: Dictionary = snapshot.get("player")
	if not player_projection.get("presentation", {}) is Dictionary:
		return _rejected("MALFORMED_RESTORE_PLAYER_PRESENTATION")
	var position_result: Dictionary = _position_from_projection(player_projection.get("position", {}))
	if position_result.get("status") != "PASS":
		return position_result
	var restored_world: Dictionary = snapshot.get("world")
	if not restored_world.get("active_cell", {}) is Dictionary:
		return _rejected("MALFORMED_RESTORE_WORLD_ACTIVE_CELL")
	if not restored_world.get("resource_snapshot", {}) is Dictionary:
		return _rejected("MALFORMED_RESTORE_RESOURCE_SNAPSHOT")
	var active_cell: Dictionary = restored_world.get("active_cell")
	for coordinate_key: String in ["x", "y"]:
		var coordinate: Variant = active_cell.get(coordinate_key)
		if not _is_integral_wire_number(coordinate):
			return _rejected("INVALID_RESTORE_ACTIVE_CELL")
	var preference: Dictionary = snapshot.get("profile_preference")
	if typeof(preference.get("auto_pickup")) != TYPE_BOOL:
		return _rejected("INVALID_RESTORE_AUTO_PICKUP")
	var preference_sequence: Variant = preference.get("preference_sequence")
	if typeof(preference_sequence) != TYPE_INT or typeof(preference_sequence) == TYPE_BOOL or int(preference_sequence) < 0:
		return _rejected("INVALID_RESTORE_PREFERENCE_SEQUENCE")
	var quest_projection: Dictionary = snapshot.get("quest_projection")
	if not quest_projection.get("offer_snapshot", {}) is Dictionary or not quest_projection.get("state_snapshot", {}) is Dictionary:
		return _rejected("MALFORMED_RESTORE_QUEST_PROJECTION")
	return {"status": "PASS", "authority": AUTHORITY}


func _is_integral_wire_number(value: Variant) -> bool:
	if typeof(value) == TYPE_BOOL or typeof(value) not in [TYPE_INT, TYPE_FLOAT]:
		return false
	var numeric_value: float = float(value)
	return is_finite(numeric_value) and numeric_value == floor(numeric_value)


func _position_from_projection(value: Variant) -> Dictionary:
	if not value is Dictionary:
		return _rejected("INVALID_RESTORE_PLAYER_POSITION")
	var position_data: Dictionary = value
	for key: String in ["iso_x_m", "iso_y_m", "altitude_m"]:
		var component: Variant = position_data.get(key)
		if typeof(component) not in [TYPE_INT, TYPE_FLOAT] or typeof(component) == TYPE_BOOL or not is_finite(float(component)):
			return _rejected("INVALID_RESTORE_PLAYER_POSITION")
	return {
		"status": "PASS",
		"position": Vector3(
			float(position_data.get("iso_x_m")),
			float(position_data.get("altitude_m")),
			float(position_data.get("iso_y_m"))
		),
		"authority": AUTHORITY,
	}


## Releases RELOAD_PENDING back to whatever operational state preceded the
## reload, when a rejection -- either an authority-level command REJECTED
## with no restore_snapshot, or the client's own replay/validation guard
## inside project_restore_snapshot() -- belongs to the currently pending
## REQUEST_RELOAD_RESYNC. Correlated strictly by request_ref: a rejection for
## a different (or already-resolved) request_ref must never disturb the
## client's current RELOAD_PENDING (UNRELATED_REJECTION_DOES_NOT_CLEAR_
## RELOAD_PENDING).
func _release_reload_pending(request_ref: String) -> void:
	var normalized_ref: String = request_ref.strip_edges()
	if normalized_ref.is_empty() or normalized_ref != _pending_reload_request_ref:
		return
	_pending_reload_request_ref = ""
	if _state != STATE_RELOAD_PENDING:
		return
	_state = _state_before_reload_pending
	_needs_resync = false
	_death_respawn_client.complete_restore_input_gate()
	_hud.project_b10_external_state("RELOAD_REJECTED", "Reload recusado ou stale/duplicado", true)
	restore_state_changed.emit(_state)


func _restore_failed(reason: String, detail: Dictionary) -> Dictionary:
	_pending_reload_request_ref = ""
	_state = STATE_RESYNC_REQUIRED
	_needs_resync = true
	_death_respawn_client.set_restore_input_blocked(true, reason)
	restore_state_changed.emit(_state)
	return _rejected(reason, {"detail": detail, "ready_after_resync": false})


func _validate_external(payload: Dictionary, label: String) -> Dictionary:
	if payload.get("server_authoritative") != true:
		return _rejected("NON_AUTHORITATIVE_%s" % label)
	var session: AndromedaClientSession = _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	if str(payload.get("session_ref", "")).strip_edges() != session.session_ref():
		return _rejected("SESSION_MISMATCH")
	return {"status": "PASS", "authority": AUTHORITY}


func _on_bridge_command_result_received(result: Dictionary) -> void:
	var command: String = str(result.get("command", "")).strip_edges().to_upper()
	if command in ["REQUEST_SAVE", "REQUEST_AUTOSAVE"] and result.has("result"):
		project_save_result(result)
	elif command == "REQUEST_RELOAD_RESYNC":
		var restore_value: Variant = result.get("restore_snapshot", {})
		if restore_value is Dictionary and not (restore_value as Dictionary).is_empty():
			# slot_ref/request_ref are the backend's own authoritative fields on
			# this same command result (andromeda_authority_adapter.py::
			# _request_reload_resync()'s return dict), sitting alongside --
			# not inside -- restore_snapshot. Threaded through here so the
			# replay guard can namespace by the real slot instead of a single
			# global counter, and so a client-side rejection inside
			# project_restore_snapshot() (STALE_OR_DUPLICATE_RESTORE_SNAPSHOT,
			# OLDER_OR_DUPLICATE_SAVE_SEQUENCE, malformed payload) can still
			# correlate back to the pending reload it belongs to.
			project_restore_snapshot(
				restore_value as Dictionary,
				str(result.get("slot_ref", "")),
				str(result.get("request_ref", ""))
			)
		else:
			# No restore_snapshot means the AUTHORITY itself rejected the
			# command pre-execution (e.g. SAVE_SLOT_VERIFY_FAILED,
			# RELOAD_REQUEST_REF_REQUIRED) -- distinct from the client-side
			# replay rejections above, which do receive a real restore_snapshot
			# from a PASS command result and are handled inside
			# project_restore_snapshot() itself. Either way nothing else would
			# clear RELOAD_PENDING here, so release it explicitly.
			_release_reload_pending(str(result.get("request_ref", "")))


func _on_session_bound(session_ref_value: String, _session_epoch: int) -> void:
	var reconnect: bool = _seen_bound_session and not _bound_session_ref.is_empty() and _bound_session_ref != session_ref_value
	_seen_bound_session = true
	_bound_session_ref = session_ref_value
	_result_sequence = -1
	_restore_sequence = -1
	_last_restored_save_sequence_by_slot.clear()
	_pending_reload_request_ref = ""
	_inflight_save_requests.clear()
	if reconnect:
		_state = STATE_RESYNC_REQUIRED
		_needs_resync = true
		_death_respawn_client.set_restore_input_blocked(true, "RECONNECT_RESYNC_REQUIRED")
		_hud.present_b10_client_pending("RESYNC_REQUIRED", "Reconexão exige snapshot restaurado")
		restore_state_changed.emit(_state)
	else:
		_state = STATE_READY
		_needs_resync = false


func _on_session_revoked(_previous_session_ref: String, _session_epoch: int) -> void:
	_state = STATE_RESYNC_REQUIRED
	_needs_resync = true
	_pending_reload_request_ref = ""
	_inflight_save_requests.clear()
	_player.stop_local_prediction()
	_death_respawn_client.set_restore_input_blocked(true, "SESSION_REVOKED_RESYNC_REQUIRED")
	_hud.present_b10_client_pending("RESYNC_REQUIRED", "Sessão revogada")
	restore_state_changed.emit(_state)


func _bridge() -> AndromedaRuntimeBridge:
	return get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge


func _session() -> AndromedaClientSession:
	return get_node_or_null("/root/ClientSession") as AndromedaClientSession


func _rejected(reason: String, detail: Dictionary = {}) -> Dictionary:
	var result := {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
	result.merge(detail, true)
	return result
