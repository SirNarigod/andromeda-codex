extends PanelContainer
class_name AndromedaAuthorityConnectionStatus

## Stage17 startup-only observer. The B01 bridge remains the sole connection owner.

signal display_state_changed(display_state: String, detail: String)

const DISPLAY_CONNECTING := "CONNECTING"
const DISPLAY_READY := "READY"
const DISPLAY_FAILED := "FAILED"
const AUTHORITY := "GODOT_CONNECTION_PRESENTATION_ONLY"

@onready var status_label: Label = $Margin/StatusLabel

var _bridge: AndromedaRuntimeBridge
var _session: AndromedaClientSession
var _display_state: String = DISPLAY_CONNECTING
var _display_detail: String = "WAITING_FOR_AUTHORITY"
var _session_bound_observed: bool = false
var _snapshot_observed: bool = false
var _snapshot_id: String = ""
var _snapshot_sequence: int = -1


func _ready() -> void:
	_bridge = get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_session = get_node_or_null("/root/ClientSession") as AndromedaClientSession
	if _bridge == null or _session == null:
		_set_display_state(DISPLAY_FAILED, "RUNTIME_AUTOLOAD_NOT_FOUND")
		return
	if not _bridge.connection_state_changed.is_connected(_on_connection_state_changed):
		_bridge.connection_state_changed.connect(_on_connection_state_changed)
	if not _bridge.authority_session_bound.is_connected(_on_authority_session_bound):
		_bridge.authority_session_bound.connect(_on_authority_session_bound)
	if not _bridge.authority_session_rejected.is_connected(_on_authority_session_rejected):
		_bridge.authority_session_rejected.connect(_on_authority_session_rejected)
	if not _bridge.snapshot_applied.is_connected(_on_snapshot_applied):
		_bridge.snapshot_applied.connect(_on_snapshot_applied)
	if not _bridge.transport_error.is_connected(_on_transport_error):
		_bridge.transport_error.connect(_on_transport_error)
	if not _session.session_revoked.is_connected(_on_session_revoked):
		_session.session_revoked.connect(_on_session_revoked)
	_refresh_from_bridge()


func is_authority_ready() -> bool:
	if _bridge == null or _session == null:
		return false
	var bridge_state: Dictionary = _bridge.connection_state()
	return (
		_display_state == DISPLAY_READY
		and _session.has_active_session()
		and bool(bridge_state.get("authority_session_bound", false))
		and _session_bound_observed
		and _snapshot_observed
		and not _snapshot_id.is_empty()
		and _snapshot_sequence >= 0
	)


func status_snapshot() -> Dictionary:
	var bridge_state: Dictionary = _bridge.connection_state() if _bridge != null else {}
	return {
		"display_state": _display_state,
		"detail": _display_detail,
		"backend_ready": str(bridge_state.get("state", "")) == AndromedaRuntimeBridge.STATE_READY,
		"session_bound": bool(bridge_state.get("authority_session_bound", false)) and _session_bound_observed,
		"snapshot_ready": _snapshot_observed,
		"snapshot_id": _snapshot_id,
		"snapshot_sequence": _snapshot_sequence,
		"ready": is_authority_ready(),
		"authority": AUTHORITY,
	}


func _on_connection_state_changed(state: String, detail: String) -> void:
	if state in [AndromedaRuntimeBridge.STATE_CONNECTING, AndromedaRuntimeBridge.STATE_SYNCING]:
		if state == AndromedaRuntimeBridge.STATE_CONNECTING:
			_session_bound_observed = false
			_snapshot_observed = false
			_snapshot_id = ""
			_snapshot_sequence = -1
		_set_display_state(DISPLAY_CONNECTING, detail)
		return
	if state == AndromedaRuntimeBridge.STATE_READY:
		_refresh_from_bridge()
		return
	if state == AndromedaRuntimeBridge.STATE_RECONNECT_WAIT:
		_session_bound_observed = false
		_snapshot_observed = false
		_set_display_state(DISPLAY_FAILED, detail)
		return
	if state == AndromedaRuntimeBridge.STATE_DISCONNECTED:
		var connection_requested: bool = bool(
			_bridge.connection_state().get("authority_connection_requested", false)
		)
		_set_display_state(
			DISPLAY_FAILED if connection_requested else DISPLAY_CONNECTING,
			detail
		)


func _on_authority_session_bound(result: Dictionary) -> void:
	_session_bound_observed = result.get("status") == "PASS"
	_refresh_from_bridge()


func _on_authority_session_rejected(reason: String) -> void:
	_session_bound_observed = false
	_snapshot_observed = false
	_set_display_state(DISPLAY_FAILED, reason)


func _on_snapshot_applied(snapshot: Dictionary) -> void:
	var snapshot_session_ref: String = str(snapshot.get("session_ref", ""))
	var expected_session_ref: String = _session.session_ref() if _session != null else ""
	_snapshot_observed = (
		snapshot.get("server_authoritative") == true
		and not snapshot_session_ref.is_empty()
		and snapshot_session_ref == expected_session_ref
		and not str(snapshot.get("snapshot_id", "")).is_empty()
		and int(snapshot.get("snapshot_sequence", -1)) >= 0
	)
	_snapshot_id = str(snapshot.get("snapshot_id", "")) if _snapshot_observed else ""
	_snapshot_sequence = int(snapshot.get("snapshot_sequence", -1)) if _snapshot_observed else -1
	_refresh_from_bridge()


func _on_transport_error(reason: String, _reconnect_delay_s: float) -> void:
	_session_bound_observed = false
	_snapshot_observed = false
	_set_display_state(DISPLAY_FAILED, reason)


func _on_session_revoked(_previous_session_ref: String, _session_epoch: int) -> void:
	_session_bound_observed = false
	_snapshot_observed = false
	_snapshot_id = ""
	_snapshot_sequence = -1
	_set_display_state(DISPLAY_CONNECTING, "SESSION_REVOKED")


func _refresh_from_bridge() -> void:
	if _bridge == null or _session == null:
		_set_display_state(DISPLAY_FAILED, "RUNTIME_AUTOLOAD_NOT_FOUND")
		return
	var bridge_state: Dictionary = _bridge.connection_state()
	var transport_ready: bool = str(bridge_state.get("state", "")) == AndromedaRuntimeBridge.STATE_READY
	var session_ready: bool = bool(bridge_state.get("authority_session_bound", false))
	if transport_ready and session_ready and _session_bound_observed and _snapshot_observed:
		_set_display_state(DISPLAY_READY, "AUTHORITATIVE_SNAPSHOT_APPLIED")
	else:
		_set_display_state(DISPLAY_CONNECTING, str(bridge_state.get("detail", "WAITING_FOR_AUTHORITY")))


func _set_display_state(next_state: String, detail: String) -> void:
	_display_state = next_state
	_display_detail = detail
	if status_label != null:
		match _display_state:
			DISPLAY_READY:
				status_label.text = "AUTORIDADE · PRONTA"
				status_label.modulate = Color(0.34, 0.56, 0.32, 1.0)
			DISPLAY_FAILED:
				status_label.text = "AUTORIDADE · FALHOU"
				status_label.modulate = Color(0.92, 0.57, 0.26, 1.0)
			_:
				status_label.text = "AUTORIDADE · CONECTANDO"
				status_label.modulate = Color(0.48, 0.48, 0.46, 1.0)
	tooltip_text = _display_detail
	display_state_changed.emit(_display_state, _display_detail)

