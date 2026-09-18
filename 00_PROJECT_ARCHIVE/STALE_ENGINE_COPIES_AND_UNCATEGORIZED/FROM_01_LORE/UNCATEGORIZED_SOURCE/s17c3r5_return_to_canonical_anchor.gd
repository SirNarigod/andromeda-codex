extends Node

## S17-C3R5 one-shot corrective utility -- NOT the emergency player-recovery
## tool. Issues exactly ONE ordinary, real, authoritative MOVE_TO_POINT (the
## same public command any normal Player click/keypress uses) toward the
## canonical resource-placement anchor position, expressed via THIS session's
## own freshly-established AuthoritySpaceMapper anchor. Corrects the small
## (~10m) drift this round's own repeated C2 gate runs accumulated (each
## run's internal test movements left the player near ORE/TREE rather than
## back at the canonical anchor, so the NEXT run's session anchor -- captured
## from wherever the player currently is -- drifted a bit further each time).
## No SQL, no sync_to_geodetic, no direct DB writes, no bypass of movement
## duration/authority: exactly the sequence a real player walking home would
## produce.

const WAIT_TIMEOUT_S := 60.0
const ANCHOR_ISO_X_M := 137108.156775035
const ANCHOR_ISO_Y_M := -1336956.95467694
const ANCHOR_ALTITUDE_M := 0.0

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _movement_accepts: Array[Dictionary] = []
var _movement_rejections: Array[Dictionary] = []


func _ready() -> void:
	await _run()


func _run() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if main == null or session == null or bridge == null:
		print("ANDROMEDA_S17C3R5_RETURN_GATE: FAIL missing runtime")
		get_tree().quit(1)
		return
	main.movement_authority_client.movement_accepted.connect(func(value: Dictionary) -> void: _movement_accepts.append(value.duplicate(true)))
	main.movement_authority_client.movement_rejected.connect(func(value: Dictionary) -> void: _movement_rejections.append(value.duplicate(true)))
	if session.has_active_session():
		session.revoke_session()
	var bound: Dictionary = session.bind_session("GODOT-STAGE17-C3R5-RETURN-ANCHOR")
	var auth_started: Dictionary = bridge.bind_authoritative_session()
	var binds: Array = []
	bridge.authority_session_bound.connect(func(value: Dictionary) -> void: binds.append(value))
	var snapshots: Array = []
	bridge.snapshot_applied.connect(func(value: Dictionary) -> void: snapshots.append(value))
	var started_wait: int = Time.get_ticks_msec()
	while snapshots.is_empty() and float(Time.get_ticks_msec() - started_wait) / 1000.0 < WAIT_TIMEOUT_S:
		await get_tree().process_frame
	if snapshots.is_empty() or not main.authority_space_mapper.is_anchored():
		print("ANDROMEDA_S17C3R5_RETURN_GATE: FAIL anchor not established bound=%s auth=%s" % [JSON.stringify(bound), JSON.stringify(auth_started)])
		get_tree().quit(1)
		return

	var target: Dictionary = main.authority_space_mapper.authority_to_local({
		"iso_x_m": ANCHOR_ISO_X_M,
		"iso_y_m": ANCHOR_ISO_Y_M,
		"altitude_m": ANCHOR_ALTITUDE_M,
	})
	if target.get("status") != "PASS":
		print("ANDROMEDA_S17C3R5_RETURN_GATE: FAIL local mapping rejected %s" % JSON.stringify(target))
		get_tree().quit(1)
		return
	var local_destination: Vector3 = target["local_position"]
	print("ANDROMEDA_S17C3R5_RETURN_GATE: player_local_before=%s target_local=%s" % [JSON.stringify(main.player.global_position), JSON.stringify(local_destination)])

	var request: Dictionary = main.player.request_move(local_destination)
	if request.get("status") != "PASS" or request.get("transport_submitted") != true:
		print("ANDROMEDA_S17C3R5_RETURN_GATE: FAIL move not submitted %s" % JSON.stringify(request))
		get_tree().quit(1)
		return
	started_wait = Time.get_ticks_msec()
	while (
		_movement_accepts.is_empty()
		and _movement_rejections.is_empty()
		and float(Time.get_ticks_msec() - started_wait) / 1000.0 < WAIT_TIMEOUT_S
	):
		await get_tree().process_frame
	if not _movement_rejections.is_empty():
		print("ANDROMEDA_S17C3R5_RETURN_GATE: FAIL movement rejected %s" % JSON.stringify(_movement_rejections.back()))
		get_tree().quit(1)
		return
	if _movement_accepts.is_empty():
		print("ANDROMEDA_S17C3R5_RETURN_GATE: FAIL movement result timeout")
		get_tree().quit(1)
		return
	var accepted: Dictionary = _movement_accepts.back()
	var authority_position: Dictionary = accepted.get("authority_result_position", {}) as Dictionary
	print("ANDROMEDA_S17C3R5_RETURN_GATE: PASS authority_result_position=%s" % JSON.stringify(authority_position))
	get_tree().quit(0)
