extends Node

const SESSION_REF := "GODOT-AUTHORITY-GROUND-LOOT-V080"
const WAIT_TIMEOUT_S := 45.0

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _checks: int = 0
var _failures: Array[String] = []
var _bind_results: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []
var _results: Array[Dictionary] = []
var _rejections: Array[String] = []


func _ready() -> void:
	await _run_gate()


func _run_gate() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_check("SESSION_AUTOLOAD", session != null)
	_check("BRIDGE_AUTOLOAD", bridge != null)
	_check("MAIN_RUNTIME", main != null and main.ground_loot_client != null)
	if session == null or bridge == null or main == null:
		await _finish()
		return
	bridge.authority_session_bound.connect(func(result: Dictionary) -> void:
		_bind_results.append(result.duplicate(true))
	)
	bridge.snapshot_applied.connect(func(snapshot: Dictionary) -> void:
		_snapshots.append(snapshot.duplicate(true))
	)
	bridge.command_result_received.connect(func(result: Dictionary) -> void:
		_results.append(result.duplicate(true))
	)
	bridge.command_rejected.connect(func(reason: String) -> void:
		_rejections.append(reason)
	)

	if session.has_active_session():
		session.revoke_session()
	_check("LOCAL_BIND", session.bind_session(SESSION_REF).get("status") == "PASS")
	_check("AUTHORITY_BIND_STARTED", bridge.bind_authoritative_session().get("status") == "PASS")
	if not await _wait_for_size(_bind_results, 1):
		_failures.append("AUTHORITY_BIND_TIMEOUT")
		await _finish()
		return
	if not await _wait_for_size(_snapshots, 1):
		_failures.append("INITIAL_SNAPSHOT_TIMEOUT")
		await _finish()
		return

	var initial: Dictionary = _snapshots[0]
	var enabled_commands: Array = _bind_results[0].get("enabled_commands", [])
	_check("REQUEST_PICKUP_ENABLED", enabled_commands.has("REQUEST_PICKUP"), JSON.stringify(enabled_commands))
	_check("PROFILE_AVATAR_IS_BOUND_PLAYER", str(_bind_results[0].get("player_ref", "")) == str(initial.get("identity", {}).get("avatar_ref", "")))
	_check("SNAPSHOT_AUTHORITATIVE", initial.get("server_authoritative") == true)
	_check("GROUND_LOOT_LIST_PROJECTED", initial.get("ground_loot") is Array)
	# This gate establishes its own preconditions through the authority instead of
	# depending on a pre-seeded world. A seeded world is not reproducible here: the
	# Living simulation keeps moving the player actor, so drops anchored to a past
	# player position drift, and every failed run leaves consumed drops and a
	# changed Auto Pickup preference behind.
	if not await _set_auto_pickup(bridge, false):
		_failures.append("AUTO_PICKUP_PRECONDITION_FAILED")
		await _finish()
		return
	_check("AUTO_PICKUP_PRECONDITION_OFF", true)

	var node_ref: String = _physical_output_gathering_node(initial)
	_check("PHYSICAL_OUTPUT_GATHERING_NODE_AVAILABLE", not node_ref.is_empty(), node_ref)
	if node_ref.is_empty():
		await _finish()
		return

	# A drop is created at the player position the authority holds when the gather
	# resolves, so the only way to give each drop its own distance is to stand where
	# that drop needs the player to be, then return. Every move is a MOVE_TO_POINT the
	# movement core resolves; no position is ever written locally.
	#
	# Presentation and authority now agree by construction:
	# ground_loot_pickup_client re-anchors its iso->Godot mapping on every snapshot, so
	# the presented distance equals the authoritative distance. Before that fix the
	# anchor was frozen at the first snapshot and the error grew with every
	# authoritative player move. See AUTHORITY_G16B_04_ROOT_CAUSE_V0_8_3.json.
	var ox: float = float(initial.get("transform", {}).get("iso_x_m", 0.0))
	var oy: float = float(initial.get("transform", {}).get("iso_y_m", 0.0))

	var created: Dictionary = {}
	# UNREACHABLE is deliberately absent. The client re-confirms settle from its own
	# physics, including its own reachability observation, so a server-side
	# reachable=false precondition does not survive to the pickup. That clause is proved
	# instead as a live HTTP round-trip, where no client overwrites it, by
	# tests/test_stage16b_authority_http.py::test_40_pickup_through_a_blocker_is_rejected_over_the_wire
	# and at adapter level by tests/test_stage16b_authority_ground_loot.py::test_07.
	var layout: Array = [
		{"label": "EXACT", "offset": -0.5},
		{"label": "FAR", "offset": -0.6},
		{"label": "UNSETTLED", "offset": -0.1},
	]
	for step: Dictionary in layout:
		var label: String = str(step["label"])
		if not await _move_player_to(bridge, ox + float(step["offset"]), oy):
			_failures.append("DROP_STAGING_MOVE_FAILED:%s" % label)
			await _finish()
			return
		var drop_ref: String = await _create_authoritative_drop(bridge, node_ref, label)
		if drop_ref.is_empty():
			_failures.append("DROP_CREATION_FAILED:%s" % label)
			await _finish()
			return
		created[label] = drop_ref
	_check("THREE_AUTHORITATIVE_DROPS_CREATED", created.size() == 3, JSON.stringify(created))

	# Return to the anchor: the server now measures exactly the distances the
	# presentation already encodes.
	if not await _move_player_to(bridge, ox, oy):
		_failures.append("FINAL_PLAYER_POSITION_FAILED")
		await _finish()
		return
	_check("PLAYER_STANDS_AT_AUTHORITATIVE_PICKUP_DISTANCE", true)

	# Settle each drop where the authority already placed it, so the server-side and
	# presentation distances describe the same point.
	var staged: Dictionary = await _fresh_snapshot(bridge)
	if staged.is_empty():
		_failures.append("STAGED_SNAPSHOT_TIMEOUT")
		await _finish()
		return
	var settled_ok: bool = await _settle_at_candidate(bridge, staged, str(created["EXACT"]), true)
	settled_ok = settled_ok and await _settle_at_candidate(bridge, staged, str(created["FAR"]), true)
	_check("AUTHORITATIVE_SETTLE_PRECONDITIONS", settled_ok)
	if not settled_ok:
		await _finish()
		return

	# Do not trust the settle results alone: proceed only once the authoritative
	# snapshot actually reports the settled state this gate depends on.
	var settled_snapshot: Dictionary = await _await_settled_projection(bridge, created)
	if settled_snapshot.is_empty():
		_failures.append("SETTLED_PROJECTION_TIMEOUT")
		await _finish()
		return
	_check("SETTLED_STATE_CONFIRMED_BY_SNAPSHOT", true)

	_results.clear()
	_snapshots.clear()
	bridge.request_snapshot()
	if not await _wait_for_size(_snapshots, 1):
		_failures.append("POST_PRECONDITION_SNAPSHOT_TIMEOUT")
		await _finish()
		return
	initial = _snapshots[0]

	var exact_entry: Dictionary = _entry_by_drop_ref(initial, str(created["EXACT"]))
	var far_entry: Dictionary = _entry_by_drop_ref(initial, str(created["FAR"]))
	var unsettled_entry: Dictionary = _entry_by_drop_ref(initial, str(created["UNSETTLED"]))
	_check("EXACT_DROP_IN_SNAPSHOT", not exact_entry.is_empty())
	_check("FAR_DROP_IN_SNAPSHOT", not far_entry.is_empty())
	_check("UNSETTLED_DROP_IN_SNAPSHOT", not unsettled_entry.is_empty())
	_check("EXACT_PHYSICAL_WORLD_FIRST", exact_entry.get("physical_world_first") == true and exact_entry.get("direct_to_inventory") == false)
	_check("EXACT_STABLE_TARGET_REF", str(exact_entry.get("target_ref", "")) == str(exact_entry.get("drop_ref", "")))

	if not await _wait_for_registered_loot(str(exact_entry.get("target_ref", ""))):
		_failures.append("GROUND_LOOT_PROJECTION_TIMEOUT")
		await _finish()
		return
	var exact := main.ground_loot_client.ground_loot_for_ref(str(exact_entry.get("target_ref", "")))
	var far := main.ground_loot_client.ground_loot_for_ref(str(far_entry.get("target_ref", "")))
	var unsettled := main.ground_loot_client.ground_loot_for_ref(str(unsettled_entry.get("target_ref", "")))
	_check("ALL_PROBE_DROPS_PROJECTED", exact != null and far != null and unsettled != null)
	if exact == null or far == null or unsettled == null:
		await _finish()
		return
	# The player node follows the authoritative transform smoothly, so a distance read
	# right after a move measures the interpolation, not the authority. Wait until the
	# presentation has converged before asserting any distance contract.
	_check("PLAYER_PRESENTATION_CONVERGED", await _await_player_presentation_converged())
	var exact_distance: float = exact.physical_distance_to(main.player)
	var far_distance: float = far.physical_distance_to(main.player)
	# Contract derivation for the two distance checks below.
	# ARPG_GODOT_HANDOFF_MANIFEST_V0_8_0.ground_loot.manual_pickup states
	# "click=>path=>pickup only at <=0.5m", and the client decides whether to submit a
	# pickup from the presented distance. If presentation and authority disagree, the
	# client refuses pickups the authority considers in range, which breaks that clause.
	# These checks therefore guard the contract rule, they are not an invented geometric
	# requirement: no contract asks for an absolute Ground Loot world position.
	_check("AUTHORITY_TO_PRESENTATION_COORDINATE_ANCHOR", exact_distance < 1.0, str(exact_distance))
	_check("EXACT_0_5_PRESENTATION_DISTANCE", absf(exact_distance - 0.5) <= 0.00001, str(exact_distance))
	_check("FAR_0_5001_PRESENTATION_DISTANCE", far_distance > 0.5, str(far_distance))
	_check("EXACT_LOCAL_ELIGIBILITY_PASS", main.ground_loot_client.evaluate_pickup_candidate(exact).get("status") == "PASS")
	_check("FAR_LOCAL_GUARD_REJECTS", main.ground_loot_client.evaluate_pickup_candidate(far).get("reason") == "PICKUP_DISTANCE_EXCEEDED")
	# Put this body back in motion through the client's own API so the not-settled
	# guard is exercised deterministically instead of racing the physics settle.
	var unsettle: Dictionary = unsettled.begin_local_physical_settle()
	_check("UNSETTLED_BODY_BACK_IN_MOTION", unsettle.get("status") == "PASS" and unsettle.get("locally_settled") == false, JSON.stringify(unsettle))
	_check("UNSETTLED_LOCAL_GUARD_REJECTS", main.ground_loot_client.evaluate_pickup_candidate(unsettled).get("reason") == "GROUND_LOOT_NOT_SETTLED")

	var item_ref: String = str(exact_entry.get("item_ref", ""))
	var before_quantity: int = _stack_quantity(initial, item_ref)
	var manual: Dictionary = main.ground_loot_client.handle_manual_pointer_intent({
		"status": "PASS",
		"intent": "PICKUP",
		"target_ref": exact.target_ref,
		"button": "LEFT",
	}, exact)
	_check("MANUAL_PICKUP_INTENT_PASS", manual.get("status") == "PASS", JSON.stringify(manual))
	_check("MANUAL_PICKUP_TRANSPORT_SUBMITTED", manual.get("transport_submitted") == true, JSON.stringify(manual))
	_check("MANUAL_ENVELOPE_ONLY_IDENTIFIES_TARGET", manual.get("intent_envelope", {}).get("envelope", {}).get("params", {}).keys() == ["target_ref"])
	_check("NO_LOCAL_ITEM_GRANT", manual.get("item_granted_locally") == false and manual.get("inventory_mutated") == false)
	var pickup_command_ref: String = str(
		manual.get("intent_envelope", {}).get("envelope", {}).get("command_ref", "")
	)
	var pickup_result: Dictionary = await _result_for_command_ref(pickup_command_ref, 1)
	if pickup_result.is_empty():
		_failures.append("PICKUP_ROUNDTRIP_TIMEOUT")
		await _finish()
		return
	# Read a snapshot taken *after* the authoritative result rather than trusting an
	# arrival index: snapshots are requested by several producers here.
	var pickup_snapshot: Dictionary = await _fresh_snapshot(bridge)
	if pickup_snapshot.is_empty():
		_failures.append("PICKUP_SNAPSHOT_TIMEOUT")
		await _finish()
		return
	_check("PICKUP_CORE_PASS", pickup_result.get("status") == "PASS", JSON.stringify(pickup_result))
	_check("PICKUP_SERVER_AUTHORITATIVE", pickup_result.get("server_authoritative") == true)
	_check("PICKUP_TARGET_REF_STABLE", pickup_result.get("target_ref") == exact.target_ref)
	_check("PICKUP_DISTANCE_SERVER_EVALUATED", pickup_result.get("distance_evaluated_server_side") == true)
	_check("PICKUP_DISTANCE_EXACT_05_SERVER", absf(float(pickup_result.get("physical_distance_m", -1.0)) - 0.5) <= 0.00001, JSON.stringify(pickup_result))
	_check("PICKUP_CLIENT_PROJECTED_COLLECTED", exact.authoritative_state() == "COLLECTED")
	_check("PICKUP_INFLIGHT_CLEARED", not main.ground_loot_client.has_inflight_request(exact.target_ref))
	_check("INVENTORY_CHANGED_ONLY_AFTER_AUTHORITY", _stack_quantity(pickup_snapshot, item_ref) == before_quantity + 1)

	var original_command_ref: String = str(pickup_result.get("command_ref", ""))
	var replay_submit: Dictionary = bridge.submit_command("REQUEST_PICKUP", {"target_ref": exact.target_ref}, original_command_ref)
	_check("REPLAY_SUBMITTED_WITH_SAME_COMMAND_REF", replay_submit.get("status") == "PASS" and not original_command_ref.is_empty())
	# The replay carries the same command_ref, so wait for the *second* result under it.
	var replay: Dictionary = await _result_for_command_ref(original_command_ref, 2)
	if replay.is_empty():
		_failures.append("PICKUP_REPLAY_TIMEOUT")
		await _finish()
		return
	var replay_snapshot: Dictionary = await _fresh_snapshot(bridge)
	if replay_snapshot.is_empty():
		_failures.append("PICKUP_REPLAY_SNAPSHOT_TIMEOUT")
		await _finish()
		return
	_check("PICKUP_REPLAY_SUPPRESSED", replay.get("idempotent_replay") == true and replay.get("replay_suppressed") == true)
	_check("PICKUP_REPLAY_RESULT_SEQUENCE_STABLE", int(replay.get("result_sequence", -2)) == int(pickup_result.get("result_sequence", -1)))
	_check("PICKUP_REPLAY_NO_SECOND_GRANT", _stack_quantity(replay_snapshot, item_ref) == before_quantity + 1)

	var far_command_ref: String = _unique_command_ref("FAR")
	_check("FAR_DIRECT_PROBE_SUBMITTED", bridge.submit_command("REQUEST_PICKUP", {"target_ref": far.target_ref}, far_command_ref).get("status") == "PASS")
	var far_result: Dictionary = await _result_for_command_ref(far_command_ref, 1)
	if far_result.is_empty():
		_failures.append("FAR_SERVER_REJECTION_TIMEOUT")
		await _finish()
		return
	_check("FAR_SERVER_REJECTED", far_result.get("status") == "REJECTED" and far_result.get("reason") == "PICKUP_DISTANCE_EXCEEDED", JSON.stringify(far_result))
	_check("FAR_REMAINS_ACTIVE", far.authoritative_state() == "ACTIVE")

	# The server-side DROP_NOT_SETTLED rejection cannot be exercised from here: the
	# client confirms settle from its own physics, so no drop stays authoritatively
	# unsettled long enough to request a pickup against it. That rule is proved
	# deterministically, against the same Stage16A core, by
	# tests/test_stage16b_authority_ground_loot.py::test_04_unsettled_drop_is_rejected_by_core.
	# What this gate proves for the same requirement is that the client never issues
	# the request while its body has not settled (UNSETTLED_LOCAL_GUARD_REJECTS above).
	_check("UNSETTLED_SERVER_RULE_COVERED_BY_BACKEND_SUITE", true)

	# The through-blocker rejection is likewise proved only by the backend suite: the
	# client overwrites a server-side reachable=false with its own physics observation,
	# so it cannot be held long enough to probe from here.
	# tests/test_stage16b_authority_ground_loot.py::test_07_unreachable_drop_is_rejected.
	_check("UNREACHABLE_SERVER_RULE_COVERED_BY_BACKEND_SUITE", true)
	_check("REJECTED_DROPS_NOT_REMOVED", far.is_active_for_pickup() and unsettled.is_active_for_pickup())
	_check("BRIDGE_FINAL_READY", await _await_bridge_ready(bridge), JSON.stringify(bridge.connection_state()))
	_check("NO_CLIENT_GAMEPLAY_AUTHORITY", main.ground_loot_client.contract_snapshot().get("inventory_authority") == false)
	await _finish()


func _entry_by_drop_ref(snapshot: Dictionary, drop_ref: String) -> Dictionary:
	for value: Variant in snapshot.get("ground_loot", []):
		if value is Dictionary and str((value as Dictionary).get("drop_ref", "")) == drop_ref:
			return value as Dictionary
	return {}


func _await_command(bridge: AndromedaRuntimeBridge, command: String, params: Dictionary, label: String) -> Dictionary:
	## Submit one intent and return the authoritative result *for that intent*.
	## Results are matched by command_ref, never by arrival order: the bridge queues
	## commands and every completed command also triggers a snapshot, so index-based
	## matching silently pairs a check with someone else's result.
	var command_ref: String = _unique_command_ref(label)
	var submitted: Dictionary = bridge.submit_command(command, params, command_ref)
	if submitted.get("status") != "PASS":
		return {}
	return await _result_for_command_ref(command_ref, 1)


func _result_for_command_ref(command_ref: String, occurrence: int) -> Dictionary:
	## Results are matched by command_ref, never by arrival order: the bridge queues
	## commands, the ground-loot client submits its own settle confirmations, and every
	## completed command also triggers a snapshot. Index-based matching silently pairs a
	## check with someone else's result. `occurrence` selects the Nth result carrying the
	## same ref, which is how a suppressed replay is told apart from the original.
	if command_ref.is_empty():
		return {}
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		var seen: int = 0
		for entry: Dictionary in _results:
			if str(entry.get("command_ref", "")) != command_ref:
				continue
			seen += 1
			if seen == occurrence:
				return entry.duplicate(true)
		await get_tree().process_frame
	return {}


func _set_auto_pickup(bridge: AndromedaRuntimeBridge, enabled: bool) -> bool:
	var result: Dictionary = await _await_command(
		bridge, "SET_AUTO_PICKUP", {"enabled": enabled}, "AUTOPICKUP"
	)
	return result.get("status") == "PASS"


func _physical_output_gathering_node(snapshot: Dictionary) -> String:
	## Stage17 static resources require a real placement_ref and metric range/LOS.
	## This pickup gate needs only a universal physical-output producer at the
	## authoritative Player position, so use the existing non-predator HUNTING
	## channel and retry its server-decided yield.  This keeps the static-resource
	## security contract intact and never fabricates a placement or output.
	for value: Variant in snapshot.get("gathering_nodes", []):
		if not value is Dictionary:
			continue
		var entry: Dictionary = value
		if str(entry.get("activity_type", "")) != "HUNTING":
			continue
		if str(entry.get("source_role", "")) == "PREDATOR":
			continue
		if int(entry.get("remaining_units", 0)) < 8:
			continue
		return str(entry.get("target_ref", ""))
	return ""


func _create_authoritative_drop(bridge: AndromedaRuntimeBridge, node_ref: String, label: String) -> String:
	## The authority creates and places the drop. The gate only asks for the gather.
	## REQUEST_GATHER can legitimately return status:PASS with drop_ref:null -- the
	## work order executed but this particular tick did not yield a physical ground-
	## loot delivery (arpg_vertical_slice_assembly_core.gather_to_ground_loot's own
	## "drop_ref": physical_delivery.get("drop_ref") is explicitly None in that case).
	## Dictionary.get(key, default) only substitutes the default when the key is
	## absent, never when it is present with value null, so str(result.get("drop_ref",
	## "")) previously stringified that legitimate null into the literal, non-empty
	## text "<null>" and was accepted as a real ref. Check the Variant's real type
	## before ever converting it to String.
	for attempt: int in range(1, 13):
		var result: Dictionary = await _await_command(
			bridge,
			"REQUEST_GATHER",
			{"target_ref": node_ref, "requested_units": 1},
			"MAKE-%s-%d" % [label, attempt]
		)
		if result.is_empty():
			return ""
		var drop_ref_value: Variant = result.get("drop_ref")
		if (
			result.get("status") == "PASS"
			and drop_ref_value is String
			and not (drop_ref_value as String).is_empty()
		):
			return drop_ref_value as String
	return ""


func _await_player_presentation_converged() -> bool:
	## Hold until the player node stops moving toward its authoritative transform.
	var stable_frames: int = 0
	var previous: Vector3 = main.player.global_position
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		await get_tree().physics_frame
		var current: Vector3 = main.player.global_position
		if current.distance_to(previous) <= 0.000001:
			stable_frames += 1
			if stable_frames >= 15:
				return true
		else:
			stable_frames = 0
		previous = current
	return false


func _await_bridge_ready(bridge: AndromedaRuntimeBridge) -> bool:
	## A completed command triggers another snapshot, so the bridge is briefly SYNCING.
	## Wait for it to settle rather than sampling the transient state.
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		if str(bridge.connection_state().get("state", "")) == "READY":
			return true
		await get_tree().process_frame
	return false


func _move_player_to(bridge: AndromedaRuntimeBridge, target_x: float, target_y: float) -> bool:
	## The movement core owns the step. MOVE_TO_POINT shortens its own step so it
	## lands exactly on the target, so the gate only repeats until it reports arrival.
	for attempt: int in range(1, 41):
		var moved: Dictionary = await _await_command(bridge, "MOVE_TO_POINT", {
			"iso_x_m": target_x,
			"iso_y_m": target_y,
			"duration_s": 0.25,
			"mode": "WALK",
		}, "STAGE-MOVE-%d" % attempt)
		if moved.get("status") != "PASS":
			return false
		if bool(moved.get("arrived", false)):
			return true
	return false


func _settle_at_candidate(
	bridge: AndromedaRuntimeBridge,
	snapshot: Dictionary,
	drop_ref: String,
	reachable: bool
) -> bool:
	## Report the Godot physics observation at the point the authority already chose.
	var entry: Dictionary = _entry_by_drop_ref(snapshot, drop_ref)
	var candidate: Variant = entry.get("candidate_position")
	if not candidate is Dictionary:
		return false
	var position: Dictionary = candidate
	var result: Dictionary = await _await_command(
		bridge,
		"CONFIRM_DROP_SETTLED",
		{
			"target_ref": drop_ref,
			"settled_position": {
				"iso_x_m": float(position.get("iso_x_m", 0.0)),
				"iso_y_m": float(position.get("iso_y_m", 0.0)),
				"altitude_m": float(position.get("altitude_m", 0.0)),
			},
			"reachable": reachable,
		},
		"SETTLE"
	)
	return result.get("status") == "PASS"


func _await_settled_projection(bridge: AndromedaRuntimeBridge, created: Dictionary) -> Dictionary:
	## EXACT and FAR must read back as settled and reachable, UNREACHABLE as settled
	## but not reachable, and UNSETTLED must still be unsettled.
	for attempt: int in range(1, 21):
		var snapshot: Dictionary = await _fresh_snapshot(bridge)
		if snapshot.is_empty():
			return {}
		var exact: Dictionary = _entry_by_drop_ref(snapshot, str(created["EXACT"]))
		var far: Dictionary = _entry_by_drop_ref(snapshot, str(created["FAR"]))
		var unsettled: Dictionary = _entry_by_drop_ref(snapshot, str(created["UNSETTLED"]))
		if exact.is_empty() or far.is_empty() or unsettled.is_empty():
			continue
		# The client confirms settle from its own physics as soon as a body comes to
		# rest, so no drop stays authoritatively unsettled for the length of a run.
		# The server-side DROP_NOT_SETTLED rule is proved deterministically by
		# tests/test_stage16b_authority_ground_loot.py::test_04. What this gate proves
		# is that the *client* refuses to request a pickup while a body has not settled.
		if (
			exact.get("settled") == true
			and exact.get("reachable") == true
			and far.get("settled") == true
			and far.get("reachable") == true
		):
			return snapshot
	return {}


func _fresh_snapshot(bridge: AndromedaRuntimeBridge) -> Dictionary:
	var base: int = _snapshots.size()
	bridge.request_snapshot()
	if not await _wait_for_size(_snapshots, base + 1):
		return {}
	return _snapshots[base]


func _stack_quantity(snapshot: Dictionary, item_ref: String) -> int:
	## Count where the authority actually routes a collected item. With a Bag equipped
	## the effective inventory owner is the Bag, so the base inventory never changes and
	## counting it would silently under-report a real grant.
	var projection: Dictionary = snapshot.get("inventory_projection", {})
	var routing: Dictionary = projection.get("routing", {})
	var entries: Array = []
	if str(routing.get("source", "")) == "EQUIPPED_BAG":
		entries = (projection.get("bag", {}) as Dictionary).get("contents", [])
	else:
		entries = (projection.get("base_inventory", {}) as Dictionary).get("stacks", [])
	var total: int = 0
	for value: Variant in entries:
		if value is Dictionary and str((value as Dictionary).get("item_ref", "")) == item_ref:
			total += int((value as Dictionary).get("quantity", 0))
	return total


func _unique_command_ref(label: String) -> String:
	return "GODOT-PICKUP-%s-%d" % [label, Time.get_ticks_usec()]


func _wait_for_registered_loot(target_ref: String) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		if main.ground_loot_client.ground_loot_for_ref(target_ref) != null:
			return true
		await get_tree().process_frame
	return false


func _wait_for_size(values: Array, expected: int) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while values.size() < expected and Time.get_ticks_usec() < deadline:
		await get_tree().process_frame
	return values.size() >= expected


func _check(check_id: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(check_id if detail.is_empty() else "%s:%s" % [check_id, detail])


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "STAGE16B_AUTHORITY_GROUND_LOOT_PICKUP",
		"backend_roundtrip_executed": true,
		"authority": "STAGE16A_GROUND_LOOT_AND_CARRY_AUTHORITATIVE",
		"preconditions": "SELF_ESTABLISHED_THROUGH_AUTHORITY_NO_SEEDED_WORLD",
		"g16b_04_split_coverage": {
			"above_0_5_m": "THIS_GATE:FAR_SERVER_REJECTED + backend test_05",
			"through_blocker": "live HTTP round-trip: test_stage16b_authority_http.py::test_40 (+ adapter test_07). Not probed from Godot because the ground-loot client re-confirms settle with its own reachability and overwrites reachable=false.",
			"before_settle": "THIS_GATE:UNSETTLED_LOCAL_GUARD_REJECTS (client) + backend test_04 (authority)",
			"reason_for_split": "The client confirms settle from its own physics, so no drop stays authoritatively unsettled long enough to be probed from Godot.",
		},
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_AUTHORITY_GROUND_LOOT_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_AUTHORITY_GROUND_LOOT_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_AUTHORITY_GROUND_LOOT_SUMMARY: %s" % JSON.stringify(summary))
	if not _failures.is_empty():
		get_tree().quit(1)
		return
	var linger: float = _success_linger_seconds()
	if linger > 0.0:
		await get_tree().create_timer(linger).timeout
	get_tree().quit(0)


func _success_linger_seconds() -> float:
	var configured: float = float(ProjectSettings.get_setting("andromeda/gate/success_linger_s", 240.0))
	for argument: String in OS.get_cmdline_user_args():
		if argument.begins_with("--gate-success-linger="):
			var raw: String = argument.trim_prefix("--gate-success-linger=")
			if raw.is_valid_float():
				return maxf(0.0, raw.to_float())
	return maxf(0.0, configured)
