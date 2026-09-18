extends Node

var http_request: HTTPRequest
var stage := 0
var initial_transform = {}


func _ready():
	http_request = HTTPRequest.new()
	add_child(http_request)

	http_request.request_completed.connect(_on_request_completed)

	print("=== ANDROMEDA LIVING NETWORK TEST ===")
	print("1. Solicitando snapshot inicial...")

	stage = 1

	var error = http_request.request(
		"http://127.0.0.1:8000/snapshot"
	)

	if error != OK:
		print("ERRO ao solicitar snapshot inicial: ", error)


func _on_request_completed(
	_result,
	response_code,
	_headers,
	body
):
	var text = body.get_string_from_utf8()
	var data = JSON.parse_string(text)

	print("HTTP CODE: ", response_code)

	if data == null:
		print("ERRO: resposta JSON invalida")
		print(text)
		return

	# ETAPA 1 — snapshot antes do movimento
	if stage == 1:
		print("SNAPSHOT INICIAL STATUS: ", data.get("status"))

		initial_transform = data.get("transform", {}).duplicate(true)

		print("POSICAO INICIAL: ", initial_transform)

		_send_move_command()

	# ETAPA 2 — comando MOVE_VECTOR
	elif stage == 2:
		print("MOVE STATUS: ", data.get("status"))
		print("MOVE RESPONSE: ", data)

		_request_final_snapshot()

	# ETAPA 3 — snapshot depois do movimento
	elif stage == 3:
		print("SNAPSHOT FINAL STATUS: ", data.get("status"))

		var final_transform = data.get("transform", {})

		print("POSICAO FINAL: ", final_transform)

		var changed = initial_transform != final_transform

		print("POSICAO MUDOU: ", changed)

		if (
			data.get("status") == "PASS"
			and data.get("server_authoritative") == true
			and changed
		):
			print("ANDROMEDA GODOT -> LIVING: PASS")
		else:
			print("ANDROMEDA GODOT -> LIVING: FAIL")


func _send_move_command():
	stage = 2

	var command = {
		"type": "MOVE_VECTOR",
		"payload": {
			"dx": 1.0,
			"dy": 0.25,
			"duration_s": 1.0,
			"mode": "WALK"
		}
	}

	var headers = [
		"Content-Type: application/json"
	]

	var json_body = JSON.stringify(command)

	print("2. Enviando MOVE_VECTOR...")

	var error = http_request.request(
		"http://127.0.0.1:8000/command",
		headers,
		HTTPClient.METHOD_POST,
		json_body
	)

	if error != OK:
		print("ERRO ao enviar MOVE_VECTOR: ", error)


func _request_final_snapshot():
	stage = 3

	print("3. Solicitando snapshot final...")

	var error = http_request.request(
		"http://127.0.0.1:8000/snapshot"
	)

	if error != OK:
		print("ERRO ao solicitar snapshot final: ", error)
