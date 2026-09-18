extends Node
class_name LivingWorldTransport

signal transport_ready()
signal transport_error(reason: String)

const SERVER_URL := "http://127.0.0.1:8000"

var living_client: LivingWorldClient

var _command_request: HTTPRequest
var _snapshot_request: HTTPRequest

var _command_queue: Array[Dictionary] = []
var _command_busy := false
var _snapshot_busy := false
var _snapshot_pending := false


func _ready() -> void:
	_command_request = HTTPRequest.new()
	_command_request.name = "CommandRequest"
	add_child(_command_request)

	_snapshot_request = HTTPRequest.new()
	_snapshot_request.name = "SnapshotRequest"
	add_child(_snapshot_request)

	_command_request.request_completed.connect(_on_command_completed)
	_snapshot_request.request_completed.connect(_on_snapshot_completed)


func connect_client(client: LivingWorldClient) -> void:
	living_client = client

	if not living_client.command_built.is_connected(_on_command_built):
		living_client.command_built.connect(_on_command_built)

	request_snapshot()


func request_snapshot() -> void:
	if _snapshot_busy:
		_snapshot_pending = true
		return

	_snapshot_busy = true

	var error := _snapshot_request.request(
		SERVER_URL + "/snapshot"
	)

	if error != OK:
		_snapshot_busy = false
		transport_error.emit(
			"SNAPSHOT_REQUEST_START_FAILED_%s" % error
		)


func _on_command_built(envelope: Dictionary) -> void:
	if envelope.is_empty():
		return

	_command_queue.append(
		envelope.duplicate(true)
	)

	_try_send_next_command()


func _try_send_next_command() -> void:
	if _command_busy:
		return

	if _command_queue.is_empty():
		return

	var envelope: Dictionary = _command_queue.pop_front()

	var headers := [
		"Content-Type: application/json"
	]

	var json_body := JSON.stringify(envelope)

	_command_busy = true

	var error := _command_request.request(
		SERVER_URL + "/command",
		headers,
		HTTPClient.METHOD_POST,
		json_body
	)

	if error != OK:
		_command_busy = false
		transport_error.emit(
			"COMMAND_REQUEST_START_FAILED_%s" % error
		)
		_try_send_next_command()


func _on_command_completed(
	_result,
	response_code,
	_headers,
	body
) -> void:
	_command_busy = false

	if response_code != 200:
		transport_error.emit(
			"COMMAND_HTTP_%s" % response_code
		)
		_try_send_next_command()
		return

	var data = JSON.parse_string(
		body.get_string_from_utf8()
	)

	if data == null:
		transport_error.emit(
			"COMMAND_INVALID_JSON"
		)
		_try_send_next_command()
		return

	if data.get("status") != "PASS":
		transport_error.emit(
			str(data.get("reason", "COMMAND_REJECTED"))
		)

	request_snapshot()
	_try_send_next_command()


func _on_snapshot_completed(
	_result,
	response_code,
	_headers,
	body
) -> void:
	_snapshot_busy = false

	if response_code != 200:
		transport_error.emit(
			"SNAPSHOT_HTTP_%s" % response_code
		)
		_finish_snapshot_cycle()
		return

	var data = JSON.parse_string(
		body.get_string_from_utf8()
	)

	if data == null:
		transport_error.emit(
			"SNAPSHOT_INVALID_JSON"
		)
		_finish_snapshot_cycle()
		return

	if not is_instance_valid(living_client):
		transport_error.emit(
			"LIVING_CLIENT_MISSING"
		)
		_finish_snapshot_cycle()
		return

	if living_client.apply_snapshot(data):
		transport_ready.emit()
	else:
		transport_error.emit(
			"SNAPSHOT_REJECTED_BY_CLIENT"
		)

	_finish_snapshot_cycle()


func _finish_snapshot_cycle() -> void:
	if _snapshot_pending:
		_snapshot_pending = false
		request_snapshot()
