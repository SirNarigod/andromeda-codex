extends Node
class_name AndromedaClientSession

## Client-side session cursor only. The backend binds session_ref to the actor.
## This node never stores or sends player_ref and never decides gameplay results.

signal session_bound(session_ref: String, session_epoch: int)
signal session_revoked(previous_session_ref: String, session_epoch: int)
signal snapshot_cursor_advanced(snapshot_sequence: int, snapshot_id: String)

const AUTHORITY := "GODOT_CLIENT_SESSION_CACHE_ONLY"
const STATE_UNBOUND := "UNBOUND"
const STATE_BOUND := "BOUND"
const STATE_REVOKED := "REVOKED"

var _state: String = STATE_UNBOUND
var _session_ref: String = ""
var _session_epoch: int = 0
var _last_snapshot_sequence: int = -1
var _last_snapshot_id: String = ""
var _legacy_snapshot_count: int = 0


func bind_session(value: String) -> Dictionary:
	var normalized: String = value.strip_edges()
	if normalized.is_empty():
		return _rejected("EMPTY_SESSION_REF")
	if _state == STATE_BOUND and _session_ref == normalized:
		return {
			"status": "PASS",
			"session_ref": _session_ref,
			"session_epoch": _session_epoch,
			"idempotent": true,
			"authority": AUTHORITY,
		}
	_session_epoch += 1
	_state = STATE_BOUND
	_session_ref = normalized
	_reset_snapshot_cursor()
	session_bound.emit(_session_ref, _session_epoch)
	return {
		"status": "PASS",
		"session_ref": _session_ref,
		"session_epoch": _session_epoch,
		"idempotent": false,
		"authority": AUTHORITY,
	}


func revoke_session() -> Dictionary:
	if not has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	var previous: String = _session_ref
	_state = STATE_REVOKED
	_session_ref = ""
	_reset_snapshot_cursor()
	session_revoked.emit(previous, _session_epoch)
	return {
		"status": "PASS",
		"revoked": true,
		"previous_session_ref": previous,
		"session_epoch": _session_epoch,
		"authority": AUTHORITY,
	}


func has_active_session() -> bool:
	return _state == STATE_BOUND and not _session_ref.is_empty()


func session_ref() -> String:
	return _session_ref


func session_epoch() -> int:
	return _session_epoch


func state() -> String:
	return _state


func accept_snapshot_cursor(snapshot_sequence: Variant, snapshot_id: String) -> Dictionary:
	if not has_active_session():
		return _rejected("NO_ACTIVE_SESSION")
	var normalized_id: String = snapshot_id.strip_edges()
	if normalized_id.is_empty():
		return _rejected("EMPTY_SNAPSHOT_ID")
	if snapshot_sequence == null:
		_legacy_snapshot_count += 1
		_last_snapshot_id = normalized_id
		return {
			"status": "PASS",
			"ordering_mode": "LEGACY_RECEIVE_ORDER",
			"legacy_receive_index": _legacy_snapshot_count,
			"snapshot_id": normalized_id,
			"authority": AUTHORITY,
		}
	var sequence: int
	if typeof(snapshot_sequence) == TYPE_INT:
		sequence = int(snapshot_sequence)
	elif typeof(snapshot_sequence) == TYPE_FLOAT:
		var wire_sequence: float = float(snapshot_sequence)
		if not is_finite(wire_sequence) or wire_sequence != floor(wire_sequence):
			return _rejected("INVALID_SNAPSHOT_SEQUENCE_TYPE")
		sequence = int(wire_sequence)
	else:
		return _rejected("INVALID_SNAPSHOT_SEQUENCE_TYPE")
	if sequence < 0:
		return _rejected("INVALID_SNAPSHOT_SEQUENCE")
	if sequence <= _last_snapshot_sequence:
		return {
			"status": "REJECTED",
			"reason": "STALE_OR_DUPLICATE_SNAPSHOT",
			"snapshot_sequence": sequence,
			"last_snapshot_sequence": _last_snapshot_sequence,
			"authority": AUTHORITY,
		}
	_last_snapshot_sequence = sequence
	_last_snapshot_id = normalized_id
	snapshot_cursor_advanced.emit(sequence, normalized_id)
	return {
		"status": "PASS",
		"ordering_mode": "SERVER_SEQUENCE",
		"snapshot_sequence": sequence,
		"snapshot_id": normalized_id,
		"authority": AUTHORITY,
	}


func cursor_snapshot() -> Dictionary:
	return {
		"last_snapshot_sequence": _last_snapshot_sequence,
		"last_snapshot_id": _last_snapshot_id,
		"legacy_snapshot_count": _legacy_snapshot_count,
	}


func inspect_state() -> Dictionary:
	return {
		"state": _state,
		"session_ref": _session_ref,
		"session_epoch": _session_epoch,
		"cursor": cursor_snapshot(),
		"authority": AUTHORITY,
	}


func _reset_snapshot_cursor() -> void:
	_last_snapshot_sequence = -1
	_last_snapshot_id = ""
	_legacy_snapshot_count = 0


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
