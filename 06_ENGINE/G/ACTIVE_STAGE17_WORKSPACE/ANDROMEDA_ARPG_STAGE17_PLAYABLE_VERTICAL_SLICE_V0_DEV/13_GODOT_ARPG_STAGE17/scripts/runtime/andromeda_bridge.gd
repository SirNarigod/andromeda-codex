extends Node
class_name AndromedaRuntimeBridge

## Stage16B B01 transport/session/snapshot boundary.
## It forwards intent envelopes and projects authoritative snapshots. It never resolves
## damage, inventory grants, currency, quests, death, Bag contents, TTL, or canon.

signal connection_state_changed(state: String, detail: String)
signal snapshot_applied(snapshot: Dictionary)
signal snapshot_rejected(reason: String)
signal command_enqueued(envelope: Dictionary)
signal command_result_received(result: Dictionary)
signal command_completed(result: Dictionary)
signal command_rejected(reason: String)
signal transport_error(reason: String, reconnect_delay_s: float)
signal authority_session_bound(result: Dictionary)
signal authority_session_rejected(reason: String)
signal authority_session_revoked(result: Dictionary)
signal resync_completed(result: Dictionary)
signal resync_rejected(reason: String)

const AUTHORITY := "GODOT_CLIENT_TRANSPORT_PRESENTATION_ONLY"
const EXISTING_SERVER_URL := "http://127.0.0.1:8000"
const EXISTING_SNAPSHOT_PATH := "/snapshot"
const EXISTING_COMMAND_PATH := "/command"
const EXISTING_SESSION_BIND_PATH := "/session/bind"
const EXISTING_SESSION_REVOKE_PATH := "/session/revoke"
const EXISTING_SESSION_RESYNC_PATH := "/session/resync"

const STATE_DISCONNECTED := "DISCONNECTED"
const STATE_CONNECTING := "CONNECTING"
const STATE_SYNCING := "SYNCING"
const STATE_READY := "READY"
const STATE_RECONNECT_WAIT := "RECONNECT_WAIT"

const FORBIDDEN_COMMAND_TOKENS: Array[String] = [
	"DAMAGE",
	"GRANT",
	"CURRENCY_RESULT",
	"QUEST_COMPLETION",
	"CANON",
	"DEATH_RESULT",
	"BAG_CONTENT",
	"TTL_RESULT",
]

const FORBIDDEN_AUTHORITY_KEYS := {
	"player_ref": true,
	"entity_ref": true,
	"actor_ref": true,
	"owner_ref": true,
	"npc_ref": true,
	"target_entity_ref": true,
	"profile_ref": true,
	"avatar_ref": true,
	"world_instance_id": true,
	"role": true,
	"authority": true,
	"server_authoritative": true,
	"adapter_authority": true,
	"snapshot_id": true,
	"snapshot_sequence": true,
	"idempotent_replay": true,
	"replay_suppressed": true,
	"damage": true,
	"damage_amount": true,
	"damage_result": true,
	"inventory_grant": true,
	"grant_item": true,
	"currency_result": true,
	"quest_completion": true,
	"quest_completed": true,
	"canonical_mutation": true,
	"canon_mutation": true,
	"death_result": true,
	"bag_contents": true,
	"authoritative_ttl": true,
	"stamina": true,
	"moved_m": true,
	"geodetic": true,
	"chunk_id": true,
}

var _state: String = STATE_DISCONNECTED
var _state_detail: String = "NOT_CONNECTED"
var _current_snapshot: Dictionary = {}
var _visible_entities: Dictionary = {}
var _reconnect_attempt: int = 0
var _last_reconnect_delay_s: float = 0.0
var _snapshot_busy: bool = false
var _snapshot_pending: bool = false
var _command_busy: bool = false
var _command_queue: Array[Dictionary] = []
var _inflight_command: Dictionary = {}
var _command_index: int = 0
var _command_nonce: String = ""
var _authority_connection_requested: bool = false
var _authority_session_bound: bool = false
var _authority_session_ref: String = ""
var _authority_identity: Dictionary = {}
var _authority_enabled_commands: Array = []
var _control_busy: bool = false
var _control_operation: String = ""
var _reconnect_scheduled: bool = false
var _snapshot_request: HTTPRequest
var _command_request: HTTPRequest
var _control_request: HTTPRequest


func _ready() -> void:
	_snapshot_request = HTTPRequest.new()
	_snapshot_request.name = "SnapshotRequest"
	add_child(_snapshot_request)
	_command_request = HTTPRequest.new()
	_command_request.name = "CommandRequest"
	add_child(_command_request)
	_control_request = HTTPRequest.new()
	_control_request.name = "AuthorityControlRequest"
	add_child(_control_request)
	_snapshot_request.request_completed.connect(_on_snapshot_request_completed)
	_command_request.request_completed.connect(_on_command_request_completed)
	_control_request.request_completed.connect(_on_control_request_completed)
	var session: AndromedaClientSession = _session()
	if session != null:
		session.session_bound.connect(_on_session_bound)
		session.session_revoked.connect(_on_session_revoked)


func server_url() -> String:
	return str(ProjectSettings.get_setting("andromeda/bridge/server_url", EXISTING_SERVER_URL)).trim_suffix("/")


func snapshot_path() -> String:
	return str(ProjectSettings.get_setting("andromeda/bridge/snapshot_path", EXISTING_SNAPSHOT_PATH))


func command_path() -> String:
	return str(ProjectSettings.get_setting("andromeda/bridge/command_path", EXISTING_COMMAND_PATH))


func session_bind_path() -> String:
	return str(ProjectSettings.get_setting("andromeda/bridge/session_bind_path", EXISTING_SESSION_BIND_PATH))


func session_revoke_path() -> String:
	return str(ProjectSettings.get_setting("andromeda/bridge/session_revoke_path", EXISTING_SESSION_REVOKE_PATH))


func session_resync_path() -> String:
	return str(ProjectSettings.get_setting("andromeda/bridge/session_resync_path", EXISTING_SESSION_RESYNC_PATH))


func connection_state() -> Dictionary:
	return {
		"state": _state,
		"detail": _state_detail,
		"reconnect_attempt": _reconnect_attempt,
		"reconnect_delay_s": _last_reconnect_delay_s,
		"server_url": server_url(),
		"authority_connection_requested": _authority_connection_requested,
		"authority_session_bound": _authority_session_bound,
		"authority_session_ref": _authority_session_ref,
		"authority_identity": _authority_identity.duplicate(true),
		"authority_enabled_commands": _authority_enabled_commands.duplicate(true),
		"queued_commands": _command_queue.size(),
		"command_inflight": not _inflight_command.is_empty(),
		"authority": AUTHORITY,
	}


func build_command_envelope(
	command_value: String,
	params: Dictionary = {},
	command_ref_value: String = ""
) -> Dictionary:
	var session: AndromedaClientSession = _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	var command: String = command_value.strip_edges().to_upper()
	if command.is_empty() or not command.is_valid_identifier():
		return _rejected("INVALID_COMMAND_NAME")
	for forbidden_token: String in FORBIDDEN_COMMAND_TOKENS:
		if command.contains(forbidden_token):
			return _rejected("CLIENT_AUTHORITATIVE_COMMAND_FORBIDDEN")
	var forbidden_path: String = _find_forbidden_authority_field(params)
	if not forbidden_path.is_empty():
		return {
			"status": "REJECTED",
			"reason": "CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN",
			"field_path": forbidden_path,
			"authority": AUTHORITY,
		}
	var command_ref: String = command_ref_value.strip_edges()
	if command_ref.is_empty():
		command_ref = _next_command_ref(session)
	if not _valid_transport_ref(command_ref):
		return _rejected("INVALID_COMMAND_REF")
	var envelope := {
		"session_ref": session.session_ref(),
		"command": command,
		"command_ref": command_ref,
		"params": params.duplicate(true),
	}
	return {"status": "PASS", "envelope": envelope, "authority": AUTHORITY}


func submit_command(
	command_value: String,
	params: Dictionary = {},
	command_ref_value: String = ""
) -> Dictionary:
	var built: Dictionary = build_command_envelope(command_value, params, command_ref_value)
	if built.get("status") != "PASS":
		command_rejected.emit(str(built.get("reason", "COMMAND_REJECTED")))
		return built
	var envelope: Dictionary = built["envelope"]
	_command_queue.append(envelope.duplicate(true))
	command_enqueued.emit(envelope.duplicate(true))
	_try_send_next_command()
	return {
		"status": "PASS",
		"queued": true,
		"command_ref": str(envelope.get("command_ref", "")),
		"queue_size": _command_queue.size() + (1 if _command_busy else 0),
		"authority": AUTHORITY,
	}


func bind_authoritative_session() -> Dictionary:
	var session: AndromedaClientSession = _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	if _control_busy:
		return _rejected("AUTHORITY_CONTROL_REQUEST_BUSY")
	_authority_connection_requested = true
	_authority_session_bound = false
	_authority_session_ref = ""
	_set_state(STATE_CONNECTING, "AUTHORITY_SESSION_BIND_REQUEST")
	return _start_control_request("BIND", session_bind_path(), {
		"session_ref": session.session_ref(),
	})


func request_authoritative_resync() -> Dictionary:
	var session: AndromedaClientSession = _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	if _control_busy:
		return _rejected("AUTHORITY_CONTROL_REQUEST_BUSY")
	var cursor: Dictionary = session.cursor_snapshot()
	var payload: Dictionary = {"session_ref": session.session_ref()}
	var sequence: int = int(cursor.get("last_snapshot_sequence", -1))
	if sequence >= 0:
		payload["last_snapshot_sequence"] = sequence
		var snapshot_id: String = str(cursor.get("last_snapshot_id", "")).strip_edges()
		if not snapshot_id.is_empty():
			payload["last_snapshot_id"] = snapshot_id
	_set_state(STATE_SYNCING, "AUTHORITY_RESYNC_REQUEST")
	return _start_control_request("RESYNC", session_resync_path(), payload)


func revoke_authoritative_session() -> Dictionary:
	var session: AndromedaClientSession = _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	if _control_busy:
		return _rejected("AUTHORITY_CONTROL_REQUEST_BUSY")
	return _start_control_request("REVOKE", session_revoke_path(), {
		"session_ref": session.session_ref(),
	})


func retry_pending_commands() -> Dictionary:
	if not _authority_session_bound:
		return _rejected("AUTHORITY_SESSION_NOT_BOUND")
	_try_send_next_command()
	return {
		"status": "PASS",
		"queue_size": _command_queue.size() + (1 if _command_busy else 0),
		"authority": AUTHORITY,
	}


func request_snapshot() -> Dictionary:
	var session: AndromedaClientSession = _session()
	if session == null or not session.has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	if _snapshot_busy:
		_snapshot_pending = true
		return {"status": "PASS", "queued": true, "authority": AUTHORITY}
	_set_state(STATE_SYNCING, "SNAPSHOT_REQUEST")
	_snapshot_busy = true
	var snapshot_url := "%s%s?session_ref=%s" % [
		server_url(),
		snapshot_path(),
		session.session_ref().uri_encode(),
	]
	var request_error: Error = _snapshot_request.request(snapshot_url)
	if request_error != OK:
		_snapshot_busy = false
		var reason := "SNAPSHOT_REQUEST_START_FAILED_%s" % request_error
		record_transport_error(reason)
		return _rejected(reason)
	return {"status": "PASS", "queued": false, "authority": AUTHORITY}


func apply_snapshot(snapshot: Dictionary) -> Dictionary:
	var session: AndromedaClientSession = _session()
	if session == null or not session.has_active_session():
		return _reject_snapshot("NO_ACTIVE_SESSION")
	if snapshot.get("status") != "PASS":
		return _reject_snapshot(str(snapshot.get("reason", "SNAPSHOT_STATUS_NOT_PASS")))
	if snapshot.get("server_authoritative") != true:
		return _reject_snapshot("NON_AUTHORITATIVE_SNAPSHOT")
	if snapshot.has("session_ref") and str(snapshot["session_ref"]) != session.session_ref():
		return _reject_snapshot("SNAPSHOT_SESSION_MISMATCH")
	var transform_value: Variant = snapshot.get("transform")
	if not transform_value is Dictionary:
		return _reject_snapshot("INVALID_TRANSFORM")
	var transform: Dictionary = transform_value
	if not _valid_number(transform.get("iso_x_m")) or not _valid_number(transform.get("iso_y_m")):
		return _reject_snapshot("INVALID_TRANSFORM")
	if transform.has("altitude_m") and not _valid_number(transform.get("altitude_m")):
		return _reject_snapshot("INVALID_ALTITUDE")
	if transform.has("heading_deg") and not _valid_number(transform.get("heading_deg")):
		return _reject_snapshot("INVALID_HEADING")
	var chunk_value: Variant = snapshot.get("chunk")
	if not chunk_value is Dictionary:
		return _reject_snapshot("INVALID_CHUNK")
	var chunk: Dictionary = chunk_value
	var entities_value: Variant = chunk.get("entities", [])
	if not entities_value is Array:
		return _reject_snapshot("INVALID_ENTITY_LIST")
	var entity_validation: Dictionary = _validate_entities(entities_value)
	if entity_validation.get("status") != "PASS":
		return _reject_snapshot(str(entity_validation.get("reason", "INVALID_ENTITY_LIST")))
	var snapshot_id: String = str(snapshot.get("snapshot_id", _legacy_snapshot_id(snapshot)))
	var sequence: Variant = snapshot.get("snapshot_sequence", null)
	var cursor: Dictionary = session.accept_snapshot_cursor(sequence, snapshot_id)
	if cursor.get("status") != "PASS":
		return _reject_snapshot(str(cursor.get("reason", "SNAPSHOT_CURSOR_REJECTED")))
	_current_snapshot = snapshot.duplicate(true)
	if sequence != null:
		_current_snapshot["snapshot_sequence"] = int(sequence)
	_visible_entities = entity_validation["entities_by_ref"]
	_reconnect_attempt = 0
	_last_reconnect_delay_s = 0.0
	_set_state(STATE_READY, "AUTHORITATIVE_SNAPSHOT_APPLIED")
	snapshot_applied.emit(_current_snapshot.duplicate(true))
	return {
		"status": "PASS",
		"snapshot_id": snapshot_id,
		"cursor": cursor,
		"visible_entity_count": _visible_entities.size(),
		"authority": AUTHORITY,
	}


func current_snapshot() -> Dictionary:
	return _current_snapshot.duplicate(true)


func visible_entities() -> Dictionary:
	return _visible_entities.duplicate(true)


func record_transport_error(reason: String) -> Dictionary:
	_reconnect_attempt += 1
	var base_delay: float = float(ProjectSettings.get_setting("andromeda/bridge/reconnect_base_delay_s", 0.5))
	var max_delay: float = float(ProjectSettings.get_setting("andromeda/bridge/reconnect_max_delay_s", 8.0))
	_last_reconnect_delay_s = minf(max_delay, base_delay * pow(2.0, float(_reconnect_attempt - 1)))
	_set_state(STATE_RECONNECT_WAIT, reason)
	transport_error.emit(reason, _last_reconnect_delay_s)
	_schedule_authority_reconnect()
	return {
		"status": "PASS",
		"state": _state,
		"reconnect_attempt": _reconnect_attempt,
		"reconnect_delay_s": _last_reconnect_delay_s,
		"authority": AUTHORITY,
	}


func mark_transport_connected() -> void:
	_set_state(STATE_SYNCING, "TRANSPORT_CONNECTED_AWAITING_SNAPSHOT")


func _try_send_next_command() -> void:
	if _command_busy or _command_queue.is_empty():
		return
	if not _authority_session_bound:
		return
	_inflight_command = _command_queue.pop_front().duplicate(true)
	var headers := PackedStringArray(["Content-Type: application/json"])
	_command_busy = true
	var request_error: Error = _command_request.request(
		server_url() + command_path(),
		headers,
		HTTPClient.METHOD_POST,
		JSON.stringify(_inflight_command)
	)
	if request_error != OK:
		_command_busy = false
		_requeue_inflight_command()
		record_transport_error("COMMAND_REQUEST_START_FAILED_%s" % request_error)


func _on_snapshot_request_completed(
	result_code: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	_snapshot_busy = false
	if result_code != HTTPRequest.RESULT_SUCCESS:
		record_transport_error("SNAPSHOT_TRANSPORT_%s" % result_code)
		_finish_snapshot_cycle()
		return
	if response_code != 200:
		record_transport_error("SNAPSHOT_HTTP_%s" % response_code)
		_finish_snapshot_cycle()
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if not parsed is Dictionary:
		record_transport_error("SNAPSHOT_INVALID_JSON")
		_finish_snapshot_cycle()
		return
	apply_snapshot(_normalize_wire_sequences(parsed) as Dictionary)
	_finish_snapshot_cycle()


func _on_command_request_completed(
	result_code: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	_command_busy = false
	if result_code != HTTPRequest.RESULT_SUCCESS:
		_requeue_inflight_command()
		record_transport_error("COMMAND_TRANSPORT_%s" % result_code)
		return
	if response_code != 200:
		_requeue_inflight_command()
		record_transport_error("COMMAND_HTTP_%s" % response_code)
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if not parsed is Dictionary:
		_requeue_inflight_command()
		record_transport_error("COMMAND_INVALID_JSON")
		return
	var result: Dictionary = _normalize_wire_sequences(parsed) as Dictionary
	_inflight_command.clear()
	command_result_received.emit(result.duplicate(true))
	if result.get("status") != "PASS":
		command_rejected.emit(str(result.get("reason", "COMMAND_REJECTED_BY_BACKEND")))
	else:
		command_completed.emit(result.duplicate(true))
	# Both accepted and rejected gameplay results are followed by an authoritative
	# state projection. Rejections such as inventory-full/cooldown may carry state
	# the client must reconcile even though no gameplay mutation was accepted.
	request_snapshot()
	_try_send_next_command()


func _normalize_wire_sequences(value: Variant) -> Variant:
	# JSON integral numbers may arrive as floats. Only fields explicitly named as
	# monotonic sequence cursors are normalized; gameplay measurements remain floats.
	if value is Dictionary:
		var normalized: Dictionary = {}
		for key_value: Variant in (value as Dictionary).keys():
			var key: String = str(key_value)
			var child: Variant = _normalize_wire_sequences((value as Dictionary)[key_value])
			if key.ends_with("_sequence") and typeof(child) == TYPE_FLOAT and is_finite(float(child)):
				var rounded: float = round(float(child))
				if is_equal_approx(float(child), rounded):
					child = int(rounded)
			normalized[key_value] = child
		return normalized
	if value is Array:
		var normalized_array: Array = []
		for child_value: Variant in value as Array:
			normalized_array.append(_normalize_wire_sequences(child_value))
		return normalized_array
	return value


func _start_control_request(operation: String, path: String, payload: Dictionary) -> Dictionary:
	var headers := PackedStringArray(["Content-Type: application/json"])
	_control_busy = true
	_control_operation = operation
	var request_error: Error = _control_request.request(
		server_url() + path,
		headers,
		HTTPClient.METHOD_POST,
		JSON.stringify(payload)
	)
	if request_error != OK:
		_control_busy = false
		_control_operation = ""
		var reason := "%s_REQUEST_START_FAILED_%s" % [operation, request_error]
		record_transport_error(reason)
		return _rejected(reason)
	return {
		"status": "PASS",
		"operation": operation,
		"queued": true,
		"authority": AUTHORITY,
	}


func _on_control_request_completed(
	result_code: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	var operation: String = _control_operation
	_control_busy = false
	_control_operation = ""
	if result_code != HTTPRequest.RESULT_SUCCESS:
		record_transport_error("%s_TRANSPORT_%s" % [operation, result_code])
		return
	if response_code != 200:
		record_transport_error("%s_HTTP_%s" % [operation, response_code])
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if not parsed is Dictionary:
		record_transport_error("%s_INVALID_JSON" % operation)
		return
	var response: Dictionary = parsed
	if response.get("status") != "PASS":
		var rejection_reason: String = str(response.get("reason", "%s_REJECTED_BY_BACKEND" % operation))
		if operation == "RESYNC":
			resync_rejected.emit(rejection_reason)
		else:
			authority_session_rejected.emit(rejection_reason)
		_set_state(STATE_DISCONNECTED, rejection_reason)
		return
	match operation:
		"BIND":
			var session: AndromedaClientSession = _session()
			if session == null or str(response.get("session_ref", "")) != session.session_ref():
				authority_session_rejected.emit("BIND_SESSION_MISMATCH")
				_set_state(STATE_DISCONNECTED, "BIND_SESSION_MISMATCH")
				return
			_authority_session_bound = true
			_authority_session_ref = session.session_ref()
			_authority_identity = response.get("identity", {}).duplicate(true)
			_authority_enabled_commands = response.get("enabled_commands", []).duplicate(true)
			_reconnect_attempt = 0
			_last_reconnect_delay_s = 0.0
			_set_state(STATE_SYNCING, "AUTHORITY_SESSION_BOUND_AWAITING_SNAPSHOT")
			authority_session_bound.emit(response.duplicate(true))
			request_snapshot()
		"RESYNC":
			var snapshot_value: Variant = response.get("snapshot")
			if not snapshot_value is Dictionary:
				resync_rejected.emit("RESYNC_SNAPSHOT_MISSING")
				_set_state(STATE_DISCONNECTED, "RESYNC_SNAPSHOT_MISSING")
				return
			var snapshot_result: Dictionary = apply_snapshot(snapshot_value)
			if snapshot_result.get("status") != "PASS":
				resync_rejected.emit(str(snapshot_result.get("reason", "RESYNC_SNAPSHOT_REJECTED")))
				return
			var completed := response.duplicate(true)
			completed["snapshot_apply_result"] = snapshot_result
			resync_completed.emit(completed)
			_try_send_next_command()
		"REVOKE":
			_authority_session_bound = false
			_authority_session_ref = ""
			_authority_identity.clear()
			_authority_enabled_commands.clear()
			authority_session_revoked.emit(response.duplicate(true))
			_set_state(STATE_DISCONNECTED, "AUTHORITY_SESSION_REVOKED")


func _finish_snapshot_cycle() -> void:
	if _snapshot_pending:
		_snapshot_pending = false
		request_snapshot()


func _on_session_bound(_session_ref: String, _session_epoch: int) -> void:
	_current_snapshot.clear()
	_visible_entities.clear()
	_reconnect_attempt = 0
	_last_reconnect_delay_s = 0.0
	_authority_session_bound = false
	_authority_session_ref = ""
	_authority_identity.clear()
	_authority_enabled_commands.clear()
	_set_state(STATE_CONNECTING, "SESSION_BOUND")


func _on_session_revoked(_previous_session_ref: String, _session_epoch: int) -> void:
	_current_snapshot.clear()
	_visible_entities.clear()
	_command_queue.clear()
	_inflight_command.clear()
	_command_busy = false
	_snapshot_pending = false
	_authority_connection_requested = false
	_authority_session_bound = false
	_authority_session_ref = ""
	_authority_identity.clear()
	_authority_enabled_commands.clear()
	_set_state(STATE_DISCONNECTED, "SESSION_REVOKED")


func _requeue_inflight_command() -> void:
	if _inflight_command.is_empty():
		return
	_command_queue.push_front(_inflight_command.duplicate(true))
	_inflight_command.clear()


func _next_command_ref(session: AndromedaClientSession) -> String:
	_command_index += 1
	if _command_nonce.is_empty():
		_command_nonce = "%d-%d" % [OS.get_process_id(), Time.get_ticks_usec()]
	var session_hash: String = session.session_ref().sha256_text().substr(0, 12)
	return "GODOT-%s-%s-%d-%d" % [
		session_hash,
		_command_nonce,
		session.session_epoch(),
		_command_index,
	]


func _valid_transport_ref(value: String) -> bool:
	if value.is_empty() or value.length() > 128:
		return false
	for index: int in range(value.length()):
		var code: int = value.unicode_at(index)
		var allowed := (
			(code >= 48 and code <= 57)
			or (code >= 65 and code <= 90)
			or (code >= 97 and code <= 122)
			or code in [45, 46, 58, 95]
		)
		if not allowed:
			return false
	return true


func _schedule_authority_reconnect() -> void:
	if not _authority_connection_requested or _reconnect_scheduled:
		return
	if not bool(ProjectSettings.get_setting("andromeda/bridge/auto_reconnect", true)):
		return
	_reconnect_scheduled = true
	var expected_attempt: int = _reconnect_attempt
	var expected_session_epoch: int = _session().session_epoch() if _session() != null else -1
	var timer := get_tree().create_timer(_last_reconnect_delay_s)
	timer.timeout.connect(func() -> void:
		_reconnect_scheduled = false
		var session: AndromedaClientSession = _session()
		if session == null or not session.has_active_session():
			return
		if session.session_epoch() != expected_session_epoch:
			return
		if _state != STATE_RECONNECT_WAIT or _reconnect_attempt != expected_attempt:
			return
		bind_authoritative_session()
	)


func _session() -> AndromedaClientSession:
	return get_node_or_null("/root/ClientSession") as AndromedaClientSession


func _set_state(value: String, detail: String) -> void:
	_state = value
	_state_detail = detail
	connection_state_changed.emit(_state, _state_detail)


func _reject_snapshot(reason: String) -> Dictionary:
	snapshot_rejected.emit(reason)
	return _rejected(reason)


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}


func _valid_number(value: Variant) -> bool:
	if typeof(value) != TYPE_INT and typeof(value) != TYPE_FLOAT:
		return false
	return is_finite(float(value))


func _validate_entities(value: Array) -> Dictionary:
	var by_ref: Dictionary = {}
	for entry_value: Variant in value:
		if not entry_value is Dictionary:
			return _rejected("INVALID_ENTITY_ENTRY")
		var entry: Dictionary = entry_value
		var entity_ref: String = str(entry.get("entity_ref", "")).strip_edges()
		if entity_ref.is_empty():
			return _rejected("EMPTY_ENTITY_REF")
		if by_ref.has(entity_ref):
			return _rejected("DUPLICATE_ENTITY_REF")
		by_ref[entity_ref] = entry.duplicate(true)
	return {"status": "PASS", "entities_by_ref": by_ref, "authority": AUTHORITY}


func _find_forbidden_authority_field(value: Variant, path: String = "params") -> String:
	if value is Dictionary:
		var dictionary: Dictionary = value
		for key_value: Variant in dictionary.keys():
			var key: String = str(key_value)
			var normalized_key: String = key.to_lower()
			var child_path := "%s.%s" % [path, key]
			if FORBIDDEN_AUTHORITY_KEYS.has(normalized_key):
				return child_path
			var nested_path: String = _find_forbidden_authority_field(dictionary[key_value], child_path)
			if not nested_path.is_empty():
				return nested_path
	elif value is Array:
		var array: Array = value
		for index: int in range(array.size()):
			var nested_path: String = _find_forbidden_authority_field(array[index], "%s[%d]" % [path, index])
			if not nested_path.is_empty():
				return nested_path
	return ""


func _legacy_snapshot_id(snapshot: Dictionary) -> String:
	var transform: Dictionary = snapshot.get("transform", {})
	var chunk: Dictionary = snapshot.get("chunk", {})
	return "LEGACY-%s-%s-%s" % [
		str(chunk.get("chunk_id", "NO-CHUNK")),
		str(transform.get("iso_x_m", "NO-X")),
		str(transform.get("iso_y_m", "NO-Y")),
	]
