extends Node

## G16B-04 client/authority position divergence diagnostic.
##
## Read-only investigation. It changes no rule, no tolerance and no authority.
## For one target_ref at a time it records the authoritative view and every Godot
## geometric reference, so the divergence can be attributed instead of guessed.

const SESSION_REF := "GODOT-G16B04-DIAGNOSTIC"
const WAIT_TIMEOUT_S := 45.0
const SAMPLE_COUNT := 30

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _snapshots: Array[Dictionary] = []
var _results: Array[Dictionary] = []
var _samples: Array[Dictionary] = []
var _notes: Array[String] = []


func _ready() -> void:
	await _run()


func _run() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if session == null or bridge == null or main == null:
		_notes.append("MISSING_AUTOLOAD")
		await _finish()
		return
	bridge.snapshot_applied.connect(func(s: Dictionary) -> void: _snapshots.append(s.duplicate(true)))
	bridge.command_result_received.connect(func(r: Dictionary) -> void: _results.append(r.duplicate(true)))

	if session.has_active_session():
		session.revoke_session()
	session.bind_session(SESSION_REF)
	bridge.bind_authoritative_session()
	if not await _wait_size(_snapshots, 1):
		_notes.append("NO_INITIAL_SNAPSHOT")
		await _finish()
		return

	# The anchor the presentation layer freezes on its first snapshot.
	var anchor_snapshot: Dictionary = _snapshots[0]
	var anchor_authority := Vector3(
		float(anchor_snapshot.get("transform", {}).get("iso_x_m", 0.0)),
		float(anchor_snapshot.get("transform", {}).get("altitude_m", 0.0)),
		float(anchor_snapshot.get("transform", {}).get("iso_y_m", 0.0))
	)
	var anchor_presentation: Vector3 = main.player.global_position

	await _await_command(bridge, "SET_AUTO_PICKUP", {"enabled": false}, "DIAG-AUTOPICKUP")

	var node_ref: String = _static_node(anchor_snapshot)
	if node_ref.is_empty():
		_notes.append("NO_STATIC_GATHERING_NODE")
		await _finish()
		return

	for index: int in range(1, SAMPLE_COUNT + 1):
		var sample: Dictionary = await _sample_once(bridge, node_ref, index, anchor_authority, anchor_presentation)
		if sample.is_empty():
			_notes.append("SAMPLE_%d_ABORTED" % index)
			break
		_samples.append(sample)

	await _finish()


func _sample_once(
	bridge: AndromedaRuntimeBridge,
	node_ref: String,
	index: int,
	anchor_authority: Vector3,
	anchor_presentation: Vector3
) -> Dictionary:
	# 1. Authority creates the drop wherever the player currently is.
	var gathered: Dictionary = {}
	for attempt: int in range(1, 6):
		gathered = await _await_command(
			bridge, "REQUEST_GATHER", {"target_ref": node_ref, "requested_units": 1},
			"DIAG-GATHER-%d-%d" % [index, attempt]
		)
		if gathered.get("status") == "PASS" and not str(gathered.get("drop_ref", "")).is_empty():
			break
	var drop_ref: String = str(gathered.get("drop_ref", ""))
	if drop_ref.is_empty():
		return {}

	# 2. Move the player a known authoritative distance away from the drop.
	var target: Dictionary = _latest().get("transform", {})
	var move_x: float = float(target.get("iso_x_m", 0.0)) - 0.5
	var move_y: float = float(target.get("iso_y_m", 0.0))
	for step: int in range(1, 21):
		var moved: Dictionary = await _await_command(bridge, "MOVE_TO_POINT", {
			"iso_x_m": move_x, "iso_y_m": move_y, "duration_s": 0.25, "mode": "WALK",
		}, "DIAG-MOVE-%d-%d" % [index, step])
		if moved.get("status") != "PASS":
			break
		if bool(moved.get("arrived", false)):
			break

	# 3. Settle it where the authority placed it.
	var staged: Dictionary = await _fresh_snapshot(bridge)
	var entry: Dictionary = _entry(staged, drop_ref)
	var candidate: Variant = entry.get("candidate_position")
	if not candidate is Dictionary:
		return {}
	var candidate_position: Dictionary = candidate
	await _await_command(bridge, "CONFIRM_DROP_SETTLED", {
		"target_ref": drop_ref,
		"settled_position": {
			"iso_x_m": float(candidate_position.get("iso_x_m", 0.0)),
			"iso_y_m": float(candidate_position.get("iso_y_m", 0.0)),
			"altitude_m": float(candidate_position.get("altitude_m", 0.0)),
		},
		"reachable": true,
	}, "DIAG-SETTLE-%d" % index)

	# 4. Temporal gate: only measure once the authority reports settled, the body is
	#    frozen and a physics frame has completed after the snapshot was applied.
	var settled_snapshot: Dictionary = {}
	var loot: AndromedaGroundLoot = null
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		settled_snapshot = await _fresh_snapshot(bridge)
		entry = _entry(settled_snapshot, drop_ref)
		loot = main.ground_loot_client.ground_loot_for_ref(drop_ref)
		if loot != null and entry.get("settled") == true:
			await get_tree().physics_frame
			await get_tree().physics_frame
			if bool(loot.get("freeze")) and _speed(loot) <= 0.001:
				break
	if loot == null or entry.is_empty():
		return {}

	var settled_position: Variant = entry.get("settled_position", entry.get("candidate_position"))
	var loot_authority := Vector3(0, 0, 0)
	if settled_position is Dictionary:
		var settled_data: Dictionary = settled_position
		loot_authority = Vector3(
			float(settled_data.get("iso_x_m", 0.0)),
			float(settled_data.get("altitude_m", 0.0)),
			float(settled_data.get("iso_y_m", 0.0))
		)
	var player_authority := Vector3(
		float(settled_snapshot.get("transform", {}).get("iso_x_m", 0.0)),
		float(settled_snapshot.get("transform", {}).get("altitude_m", 0.0)),
		float(settled_snapshot.get("transform", {}).get("iso_y_m", 0.0))
	)

	# Horizontal authoritative distance, the quantity the pickup rule uses.
	var authority_distance: float = Vector2(
		loot_authority.x - player_authority.x,
		loot_authority.z - player_authority.z
	).length()

	var collider: Node3D = loot.get_node_or_null("CollisionShape3D") as Node3D
	var mesh: Node3D = loot.get_node_or_null("PlaceholderVisual") as Node3D
	var sensor: Node3D = loot.get_node_or_null("PickupSensor") as Node3D
	var presentation_distance: float = loot.physical_distance_to(main.player)

	# What the presentation *would* be if the anchor were refreshed to the current
	# authoritative player position instead of the one frozen at the first snapshot.
	var reanchored: Vector3 = main.player.global_position + Vector3(
		loot_authority.x - player_authority.x,
		loot_authority.y - player_authority.y,
		loot_authority.z - player_authority.z
	)
	var reanchored_distance: float = reanchored.distance_to(main.player.global_position)

	return {
		"index": index,
		"target_ref": drop_ref,
		"authority": {
			"loot_iso": [loot_authority.x, loot_authority.z, loot_authority.y],
			"player_iso": [player_authority.x, player_authority.z, player_authority.y],
			"distance_m": authority_distance,
			"settled": entry.get("settled"),
			"reachable": entry.get("reachable"),
			"state": entry.get("state"),
			"snapshot_id": settled_snapshot.get("snapshot_id"),
			"snapshot_sequence": settled_snapshot.get("snapshot_sequence"),
		},
		"godot": {
			"root_global": _v(loot.global_position),
			"collider_global": _v(collider.global_position) if collider != null else null,
			"mesh_global": _v(mesh.global_position) if mesh != null else null,
			"sensor_global": _v(sensor.global_position) if sensor != null else null,
			"player_node_global": _v(main.player.global_position),
			"freeze": bool(loot.get("freeze")),
			"sleeping": bool(loot.get("sleeping")),
			"linear_speed": _speed(loot),
			"physics_frame": Engine.get_physics_frames(),
			"render_frame": Engine.get_frames_drawn(),
		},
		"anchor": {
			"authority_at_first_snapshot": _v(anchor_authority),
			"presentation_at_first_snapshot": _v(anchor_presentation),
			"player_node_drift_since_anchor": _v(main.player.global_position - anchor_presentation),
			"player_authority_drift_since_anchor": [
				player_authority.x - anchor_authority.x,
				player_authority.z - anchor_authority.z,
			],
		},
		"measured": {
			"presentation_distance_m": presentation_distance,
			"authority_distance_m": authority_distance,
			"delta_m": presentation_distance - authority_distance,
			"reanchored_distance_m": reanchored_distance,
			"reanchored_delta_m": reanchored_distance - authority_distance,
		},
	}


func _speed(loot: AndromedaGroundLoot) -> float:
	var value: Variant = loot.get("linear_velocity")
	return (value as Vector3).length() if value is Vector3 else 0.0


func _v(vector: Vector3) -> Array:
	return [vector.x, vector.y, vector.z]


func _latest() -> Dictionary:
	return _snapshots.back() if not _snapshots.is_empty() else {}


func _entry(snapshot: Dictionary, drop_ref: String) -> Dictionary:
	for value: Variant in snapshot.get("ground_loot", []):
		if value is Dictionary and str((value as Dictionary).get("drop_ref", "")) == drop_ref:
			return value as Dictionary
	return {}


func _static_node(snapshot: Dictionary) -> String:
	for value: Variant in snapshot.get("gathering_nodes", []):
		if not value is Dictionary:
			continue
		var entry: Dictionary = value
		if str(entry.get("activity_type", "")) in ["LOGGING", "MINING", "FORAGING", "AGRICULTURE"]:
			if int(entry.get("remaining_units", 0)) > 80:
				return str(entry.get("target_ref", ""))
	return ""


func _await_command(bridge: AndromedaRuntimeBridge, command: String, params: Dictionary, label: String) -> Dictionary:
	var command_ref: String = "%s-%d" % [label, Time.get_ticks_usec()]
	if bridge.submit_command(command, params, command_ref).get("status") != "PASS":
		return {}
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		for entry: Dictionary in _results:
			if str(entry.get("command_ref", "")) == command_ref:
				return entry.duplicate(true)
		await get_tree().process_frame
	return {}


func _fresh_snapshot(bridge: AndromedaRuntimeBridge) -> Dictionary:
	var base: int = _snapshots.size()
	bridge.request_snapshot()
	if not await _wait_size(_snapshots, base + 1):
		return _latest()
	return _snapshots.back()


func _wait_size(values: Array, expected: int) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		if values.size() >= expected:
			return true
		await get_tree().process_frame
	return false


func _finish() -> void:
	print("ANDROMEDA_G16B04_DIAGNOSTIC_SAMPLES: %s" % JSON.stringify(_samples))
	print("ANDROMEDA_G16B04_DIAGNOSTIC_NOTES: %s" % JSON.stringify(_notes))
	print("ANDROMEDA_G16B04_DIAGNOSTIC_DONE: %d" % _samples.size())
	get_tree().quit(0)
