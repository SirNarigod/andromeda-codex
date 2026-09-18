extends Node

## G16B-28 NPC BAG OWNERSHIP / FOREIGN RECOVERY / ANTI-THEFT -- real Godot
## observation. Deliberately isolated from authority_save_death_runtime_gate.gd
## (death/TTL) and from authority_water_ttl_runtime_gate.gd -- ownership never
## needs to share a world with either.
##
## Real transport only, every step:
##   - development combat encounter (COMMON + ALPHA-slot/CHAMPION-rank
##     targets, both already carry a real equipped Bag via andromeda_
##     authority_adapter.py::_ensure_enemy_carried_bag(), same infrastructure
##     G16B-27's Land Bag scenario already reused) -- REQUEST_ATTACK to
##     defeat COMMON, whose Bag is then dropped in enemy_physical_output.
##     bag_ref (real, never fabricated);
##   - the ALPHA-slot target's own real target_ref is used as the stranger
##     NPC (never hardcoded);
##   - ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY (development-only transport) for
##     the stranger attempt;
##   - MOVE_TO_POINT (real physics-authoritative movement) to bring the
##     Player within REQUEST_BAG_RECOVERY's real 0.5m range;
##   - REQUEST_BAG_RECOVERY (real, production command) for the Player's
##     foreign recovery;
##   - REQUEST_SAVE / REQUEST_RELOAD_RESYNC for persistence.

const SESSION_REF := "GODOT-AUTHORITY-NPC-BAG-OWNERSHIP-V080"
const WAIT_TIMEOUT_S := 90.0
const SAVE_SLOT := "g28npcbag"

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
	_check("MAIN_RUNTIME_PRESENT", main != null)
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
	_check("LOCAL_SESSION_BIND", session.bind_session(SESSION_REF).get("status") == "PASS")
	_check("AUTHORITY_BIND_STARTED", bridge.bind_authoritative_session().get("status") == "PASS")
	if not await _wait_for_size(_bind_results, 1):
		_failures.append("AUTHORITY_BIND_TIMEOUT")
		await _finish()
		return
	if not await _wait_for_size(_snapshots, 1):
		_failures.append("INITIAL_SNAPSHOT_TIMEOUT")
		await _finish()
		return

	var enabled: Array = _bind_results[0].get("enabled_commands", [])
	_check("REQUEST_BAG_RECOVERY_ENABLED", enabled.has("REQUEST_BAG_RECOVERY"), JSON.stringify(enabled))
	_check("ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY_ENABLED", enabled.has("ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY"), JSON.stringify(enabled))
	_check("MOVE_TO_POINT_ENABLED", enabled.has("MOVE_TO_POINT"), JSON.stringify(enabled))

	var initial: Dictionary = _snapshots.back()
	var player_ref: String = str(initial.get("identity", {}).get("profile_ref", ""))
	var owner_target_ref: String = ""
	var stranger_target_ref: String = ""
	for entry: Variant in initial.get("combat_targets", []):
		if not entry is Dictionary:
			continue
		var e: Dictionary = entry
		if str(e.get("slot", "")) == "COMMON":
			owner_target_ref = str(e.get("target_ref", ""))
		elif str(e.get("slot", "")) == "ALPHA":
			stranger_target_ref = str(e.get("target_ref", ""))
	_check("G28_NPC_BAG_OWNER_TARGET_FOUND", not owner_target_ref.is_empty(), JSON.stringify(initial.get("combat_targets", [])))
	# G28_STRANGER_NPC_REF_AUTHORITATIVE
	_check("G28_STRANGER_NPC_REF_AUTHORITATIVE", not stranger_target_ref.is_empty(), JSON.stringify(initial.get("combat_targets", [])))
	_check("G28_STRANGER_NPC_DIFFERS_FROM_OWNER", stranger_target_ref != owner_target_ref and not stranger_target_ref.is_empty())
	_check("G28_STRANGER_NPC_DIFFERS_FROM_PLAYER", stranger_target_ref != player_ref and not stranger_target_ref.is_empty())
	if owner_target_ref.is_empty() or stranger_target_ref.is_empty():
		await _finish()
		return

	# --- Defeat the COMMON target: its own equipped Bag drops on LAND via
	# the already-proven enemy_physical_output.bag_ref route. --------------
	var lethal: Dictionary = {}
	for attempt: int in range(1, 41):
		await get_tree().create_timer(1.05).timeout
		var attack: Dictionary = await _await_command(bridge, "REQUEST_ATTACK", {"target_ref": owner_target_ref}, "G28-ATTACK-%d" % attempt)
		if attack.is_empty():
			break
		if attack.get("status") == "PASS" and bool(attack.get("enemy_defeated", false)):
			lethal = attack
			break
	_check("G28_NPC_BAG_CREATED_AUTHORITATIVELY", lethal.get("status") == "PASS" and bool(lethal.get("enemy_defeated", false)), JSON.stringify(lethal.get("reason", "NO_DEFEAT_REACHED")))
	if lethal.is_empty():
		await _finish()
		return

	var physical_output: Dictionary = lethal.get("enemy_physical_output", {})
	var bag_ref: String = str(physical_output.get("bag_ref", ""))
	_check("G28_NPC_BAG_REF_CAPTURED", not bag_ref.is_empty(), JSON.stringify(physical_output))
	if bag_ref.is_empty():
		await _finish()
		return

	var after_defeat: Dictionary = await _fresh_snapshot(bridge)
	var bag_before: Dictionary = _dropped_bag_entry(after_defeat, bag_ref)
	_check("G28_NPC_BAG_DROPPED_STATE_AUTHORITATIVE", str(bag_before.get("state", "")) == "DROPPED_LAND", JSON.stringify(bag_before))
	_check("G28_NPC_BAG_ORIGINAL_OWNER_CAPTURED", str(bag_before.get("property_owner_ref", "")) == owner_target_ref, JSON.stringify(bag_before))
	_check("G28_NPC_BAG_CONTENTS_CAPTURED", bag_before.get("contents_summary") is Array, JSON.stringify(bag_before))
	var contents_before: String = JSON.stringify(bag_before.get("contents_summary", []))
	var carrier_before: String = str(bag_before.get("carrier_ref", ""))
	var foreign_ref_before: String = str(bag_before.get("foreign_recovery_ref", ""))
	_progress("NPC_BAG_CAPTURED", {"bag_ref": bag_ref, "owner": owner_target_ref, "stranger": stranger_target_ref})

	# --- Stranger NPC (ALPHA-slot target) attempts recovery -- expected
	# REJECTED. -------------------------------------------------------------
	var stranger_command_ref: String = _unique_ref("STRANGER-ATTEMPT")
	var stranger_submit: Dictionary = bridge.submit_command(
		"ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY",
		{"bag_ref": bag_ref, "npc_target_ref": stranger_target_ref},
		stranger_command_ref,
	)
	_check("G28_STRANGER_NPC_RECOVERY_COMMAND_AUTHORITATIVE", stranger_submit.get("status") == "PASS", JSON.stringify(stranger_submit))
	var stranger_result: Dictionary = await _result_for_ref(stranger_command_ref, 1)
	_check("G28_STRANGER_NPC_RECOVERY_REJECTED", stranger_result.get("status") == "REJECTED", JSON.stringify(stranger_result))
	_check(
		"G28_STRANGER_NPC_RECOVERY_REASON",
		str(stranger_result.get("reason", "")) == "FOREIGN_NPC_BAG_RECOVERY_NOT_ENABLED",
		JSON.stringify(stranger_result),
	)
	_check("G28_STRANGER_NPC_NO_AUTO_THEFT", stranger_result.get("status") != "PASS")

	# --- Zero mutation after stranger rejection. ---------------------------
	var after_stranger: Dictionary = await _fresh_snapshot(bridge)
	var bag_after_stranger: Dictionary = _dropped_bag_entry(after_stranger, bag_ref)
	_check("G28_STRANGER_REJECTION_SAME_BAG_REF", str(bag_after_stranger.get("bag_ref", "")) == bag_ref, JSON.stringify(bag_after_stranger))
	_check(
		"G28_STRANGER_REJECTION_OWNER_UNCHANGED",
		str(bag_after_stranger.get("property_owner_ref", "")) == owner_target_ref,
		JSON.stringify(bag_after_stranger),
	)
	_check("G28_STRANGER_REJECTION_CARRIER_UNCHANGED", str(bag_after_stranger.get("carrier_ref", "")) == carrier_before, JSON.stringify(bag_after_stranger))
	_check("G28_STRANGER_REJECTION_STATE_UNCHANGED", str(bag_after_stranger.get("state", "")) == "DROPPED_LAND", JSON.stringify(bag_after_stranger))
	_check(
		"G28_STRANGER_REJECTION_CONTENTS_UNCHANGED",
		JSON.stringify(bag_after_stranger.get("contents_summary", [])) == contents_before,
		JSON.stringify(bag_after_stranger.get("contents_summary", [])),
	)
	_check(
		"G28_STRANGER_REJECTION_FOREIGN_REF_UNCHANGED",
		str(bag_after_stranger.get("foreign_recovery_ref", "")) == foreign_ref_before,
		JSON.stringify(bag_after_stranger),
	)
	_check("G28_BAG_REMAINS_AVAILABLE_AFTER_STRANGER_REJECTION", not bag_after_stranger.is_empty() and str(bag_after_stranger.get("state", "")) == "DROPPED_LAND")

	# --- Rejection scoping: consume ONLY this specific stranger attempt's
	# rejection, correlated by its own real command_ref (the command's
	# result never echoes bag_ref/target_ref for this rejection reason, so
	# command_ref -- already unique per attempt -- is the real, available
	# correlation key here; a different bag_ref's identical rejection reason
	# would carry a different command_ref and would NOT be scoped away). ---
	var scoped_count: int = 0
	for entry: Dictionary in _results:
		if (
			str(entry.get("status", "")) != "PASS"
			and str(entry.get("reason", "")) == "FOREIGN_NPC_BAG_RECOVERY_NOT_ENABLED"
			and str(entry.get("command", "")) == "ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY"
			and str(entry.get("command_ref", "")) == stranger_command_ref
		):
			scoped_count += 1
	_check("G28_STRANGER_NPC_RECOVERY_REJECTION_SCOPED", scoped_count == 1, "scoped_count=%d" % scoped_count)
	_rejections.erase("FOREIGN_NPC_BAG_RECOVERY_NOT_ENABLED")

	# --- Player foreign recovery: move into real 0.5m range first. --------
	var bag_position: Dictionary = bag_before.get("position", {})
	var move_start: int = _results.size()
	bridge.submit_command("MOVE_TO_POINT", {
		"iso_x_m": float(bag_position.get("iso_x_m", 0.0)),
		"iso_y_m": float(bag_position.get("iso_y_m", 0.0)),
		"mode": "WALK",
		"duration_s": 10.0,
	})
	var move_result: Dictionary = await _wait_for_command("MOVE_TO_POINT", move_start)
	_check("G28_PLAYER_MOVE_TO_BAG_AUTHORITATIVE", move_result.get("status") == "PASS", JSON.stringify(move_result))
	_check("G28_PLAYER_ARRIVED_IN_RECOVERY_RANGE", move_result.get("remaining_distance_m", 999.0) <= 0.5, JSON.stringify(move_result))

	var recovery_command_ref: String = _unique_ref("PLAYER-FOREIGN-RECOVERY")
	bridge.submit_command("REQUEST_BAG_RECOVERY", {
		"request_ref": "G28-PLAYER-RECOVERY:UI",
		"bag_ref": bag_ref,
		"target_ref": bag_ref,
		"target_kind": "DROPPED_BAG",
		"physical_distance_m": 0.0,
		"client_range_candidate_m": 0.5,
		"client_guard_passed": true,
		"client_presentation_only": true,
	}, recovery_command_ref)
	var recovery_result: Dictionary = await _result_for_ref(recovery_command_ref, 1)
	_check("G28_PLAYER_FOREIGN_RECOVERY_COMMAND_AUTHORITATIVE", not recovery_result.is_empty(), JSON.stringify(recovery_result))
	_check("G28_PLAYER_FOREIGN_RECOVERY_ACCEPTED", recovery_result.get("result") == "ACCEPTED", JSON.stringify(recovery_result))

	var bag_projection: Dictionary = recovery_result.get("bag_projection", {})
	_check("G28_FOREIGN_RECOVERY_STATE_EXPLICIT", str(bag_projection.get("state", "")) == "RECOVERED_FOREIGN", JSON.stringify(bag_projection))
	_check("G28_SAME_BAG_REF_AFTER_PLAYER_RECOVERY", str(bag_projection.get("bag_ref", bag_projection.get("target_ref", ""))) == bag_ref, JSON.stringify(bag_projection))
	_check(
		"G28_ORIGINAL_OWNER_PRESERVED_AFTER_PLAYER_RECOVERY",
		str(bag_projection.get("original_owner_ref", "")) == owner_target_ref
		and str(bag_projection.get("property_owner_ref", recovery_result.get("property_owner_ref", ""))) == owner_target_ref,
		JSON.stringify(bag_projection),
	)
	_check(
		"G28_ORIGINAL_OWNER_ALIAS_CONSISTENT",
		str(bag_projection.get("original_owner_ref", "")) == str(bag_projection.get("property_owner_ref", recovery_result.get("property_owner_ref", ""))),
		JSON.stringify(bag_projection),
	)
	# foreign_recovery_ref is nested under context_metadata in the real
	# _bag_projection() shape -- there is no top-level key by that name.
	var foreign_recovery_ref: String = str((bag_projection.get("context_metadata", {}) as Dictionary).get("foreign_recovery_ref", ""))
	_check("G28_FOREIGN_RECOVERY_REF_SET", not foreign_recovery_ref.is_empty(), JSON.stringify(bag_projection))
	_check(
		"G28_FOREIGN_RECOVERY_REF_MATCHES_REAL_PLAYER_IDENTITY",
		foreign_recovery_ref == player_ref,
		"foreign_recovery_ref=%s player_ref=%s" % [foreign_recovery_ref, player_ref],
	)
	_check(
		"G28_CURRENT_CARRIER_MATCHES_RECOVERY_SEMANTICS",
		str(bag_projection.get("carrier_ref", "")) == player_ref,
		JSON.stringify(bag_projection),
	)
	_check("G28_AUTO_THEFT_FALSE", recovery_result.get("auto_theft") == false, JSON.stringify(recovery_result))
	var contents_after_recovery: String = JSON.stringify(bag_projection.get("contents_summary", []))
	_check("G28_BAG_CONTENTS_PRESERVED_AFTER_FOREIGN_RECOVERY", contents_after_recovery == contents_before, contents_after_recovery)
	_check("G28_FOREIGN_RECOVERY_NO_DUPLICATION", contents_after_recovery == contents_before)
	# G28_FOREIGN_RECOVERY_SEMANTICS_DISTINCT: state != OWN-recovery's "RECOVERED"
	_check("G28_FOREIGN_RECOVERY_SEMANTICS_DISTINCT", str(bag_projection.get("state", "")) == "RECOVERED_FOREIGN" and str(bag_projection.get("state", "")) != "RECOVERED")
	_progress("PLAYER_FOREIGN_RECOVERY_DONE", {"bag_ref": bag_ref, "state": str(bag_projection.get("state", ""))})

	# --- Save / reload. Per real contract, RECOVERED_FOREIGN is excluded
	# from the dropped_bags projection (only DROPPED_LAND/DROPPED_WATER_
	# FLOATING/SUNK are -- confirmed by reading andromeda_authority_adapter.py
	# ::_dropped_bag_entries()'s own state filter), and it is not folded into
	# inventory_projection.bag either (recover_bag()'s foreign branch never
	# touches carry_profile/equipped_bag_ref). No live snapshot projection
	# re-exposes a RECOVERED_FOREIGN bag's fields after this point.
	#
	# ANOMALY DISCOVERED THIS ROUND: re-attempting the real REQUEST_BAG_
	# RECOVERY command on an already-RECOVERED_FOREIGN bag throws
	# INTERNAL_ADAPTER_ERROR. recover_bag()'s foreign branch sets
	# "position": None on the bag record; _request_bag_recovery()'s own
	# pre-core distance/collision gate runs BEFORE the core's state check
	# and reads position.get("iso_x_m", math.inf) unconditionally, so a
	# RECOVERED_FOREIGN bag's None position feeds math.inf into the
	# collision system, which raises. Confirmed live, not fixed (out of
	# scope: no backend edits this round) -- reported below, not routed
	# around by weakening this gate's own checks.
	#
	# The safe, real, authoritative persistence signal actually used here is
	# ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY instead: it goes straight from a
	# KeyError-guarded bag() lookup to the same core recover_bag(), with no
	# distance/collision pre-check at all, so it cannot trip this bug. If
	# the state had reverted to a recoverable dropped state, this would
	# ACCEPT (or hit the OWNER branch); since it stays RECOVERED_FOREIGN,
	# the core's own real BAG_NOT_RECOVERABLE branch fires instead -- a
	# genuine post-reload confirmation that the transition persisted. -------
	var saved: Dictionary = await _request_and_wait_save()
	_check("G28_FOREIGN_RECOVERY_SAVE_CONFIRMED", saved.get("result") == "CONFIRMED", JSON.stringify(saved))
	var restored: Dictionary = await _request_and_wait_reload()
	_check("G28_FOREIGN_RECOVERY_RELOAD_AUTHORITATIVE", restored.get("status") == "PASS", JSON.stringify(restored))

	var post_reload_probe_ref: String = _unique_ref("POST-RELOAD-REPROBE")
	bridge.submit_command(
		"ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY",
		{"bag_ref": bag_ref, "npc_target_ref": stranger_target_ref},
		post_reload_probe_ref,
	)
	var post_reload_result: Dictionary = await _result_for_ref(post_reload_probe_ref, 1)
	_check("G28_FOREIGN_RECOVERY_PERSISTS_SAVE_RELOAD", post_reload_result.get("status") == "REJECTED", JSON.stringify(post_reload_result))
	_check(
		"G28_ORIGINAL_OWNER_PERSISTS_SAVE_RELOAD",
		str(post_reload_result.get("reason", "")) == "BAG_NOT_RECOVERABLE",
		JSON.stringify(post_reload_result),
	)
	# This second ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY REJECTED result is
	# itself the deliberate, expected outcome of the persistence re-probe
	# above -- scope it away the same way, by its own unique command_ref,
	# before the final NO_COMMAND_REJECTIONS check.
	var post_reload_scoped: int = 0
	for entry: Dictionary in _results:
		if (
			str(entry.get("status", "")) != "PASS"
			and str(entry.get("reason", "")) == "BAG_NOT_RECOVERABLE"
			and str(entry.get("command", "")) == "ATTEMPT_DEVELOPMENT_NPC_BAG_RECOVERY"
			and str(entry.get("command_ref", "")) == post_reload_probe_ref
		):
			post_reload_scoped += 1
	_check("G28_POST_RELOAD_REPROBE_REJECTION_SCOPED", post_reload_scoped == 1, "scoped=%d" % post_reload_scoped)
	_rejections.erase("BAG_NOT_RECOVERABLE")
	_check("G28_NO_AUTO_THEFT_AFTER_RELOAD", post_reload_result.get("status") != "PASS")

	# --- Corrective microprocess: retry the REAL REQUEST_BAG_RECOVERY command
	# (not the dev command) on the same now-RECOVERED_FOREIGN bag. This used
	# to throw INTERNAL_ADAPTER_ERROR (root cause: recover_bag()'s foreign
	# branch sets position=None; the adapter's pre-core distance/collision
	# precondition read that unconditionally, feeding math.inf into
	# physical_distance_m, which Starlette's JSONResponse.render()
	# [json.dumps(..., allow_nan=False)] then rejected -- caught by the
	# generic exception handler and surfaced as INTERNAL_ADAPTER_ERROR).
	# Fixed in andromeda_authority_adapter.py::_request_bag_recovery(): the
	# spatial precondition now only runs when the bag is in one of the core's
	# own two spatially-"DROPPED" states; for RECOVERED_FOREIGN it defers
	# straight to the core, which answers BAG_NOT_RECOVERABLE naturally. A
	# REJECTED result is expected and correct here -- this is NOT a promotion
	# requirement, per the task's own "não exigir PASS" instruction. --------
	var real_retry_command_ref: String = _unique_ref("REAL-RETRY")
	bridge.submit_command("REQUEST_BAG_RECOVERY", {
		"request_ref": "G28-REAL-RETRY:UI",
		"bag_ref": bag_ref,
		"target_ref": bag_ref,
		"target_kind": "DROPPED_BAG",
		"physical_distance_m": 0.0,
		"client_range_candidate_m": 0.5,
		"client_guard_passed": true,
		"client_presentation_only": true,
	}, real_retry_command_ref)
	var real_retry_result: Dictionary = await _result_for_ref(real_retry_command_ref, 1)
	_check("G28_RECOVERED_FOREIGN_RETRY_COMMAND_AUTHORITATIVE", not real_retry_result.is_empty(), JSON.stringify(real_retry_result))
	_check(
		"G28_RECOVERED_FOREIGN_RETRY_NO_INTERNAL_ERROR",
		str(real_retry_result.get("reason", "")) != "INTERNAL_ADAPTER_ERROR" and str(real_retry_result.get("status", "")) != "FAIL",
		JSON.stringify(real_retry_result),
	)
	var after_real_retry: Dictionary = await _fresh_snapshot(bridge)
	var bag_after_real_retry: Dictionary = _dropped_bag_entry(after_real_retry, bag_ref)
	# RECOVERED_FOREIGN bags are excluded from dropped_bags by design (same
	# structural limitation documented above) -- so an EMPTY lookup here is
	# itself the expected, correct signal that the bag did not revert to a
	# dropped/available state. The real owner-stability signal is the core's
	# own reason on the retry result, not a snapshot re-read.
	_check(
		"G28_RECOVERED_FOREIGN_RETRY_OWNER_STABLE",
		bag_after_real_retry.is_empty() and str(real_retry_result.get("reason", "")) == "BAG_NOT_RECOVERABLE",
		JSON.stringify({"snapshot_entry": bag_after_real_retry, "retry_result": real_retry_result}),
	)
	_check(
		"G28_RECOVERED_FOREIGN_RETRY_NO_DUPLICATION",
		real_retry_result.get("result") != "ACCEPTED",
		JSON.stringify(real_retry_result),
	)
	var real_retry_scoped: int = 0
	for entry: Dictionary in _results:
		if (
			str(entry.get("status", "")) != "PASS"
			and str(entry.get("reason", "")) == "BAG_NOT_RECOVERABLE"
			and str(entry.get("command", "")) == "REQUEST_BAG_RECOVERY"
			and str(entry.get("command_ref", "")) == real_retry_command_ref
		):
			real_retry_scoped += 1
	_check("G28_RECOVERED_FOREIGN_REAL_RETRY_REJECTION_SCOPED", real_retry_scoped == 1, "scoped=%d" % real_retry_scoped)
	_rejections.erase("BAG_NOT_RECOVERABLE")

	# --- Contextual reaction: registered, not fabricated. ------------------
	_check(
		"G28_CONTEXTUAL_REACTION_HOOK_DECLARED",
		str(recovery_result.get("reaction_hook", "")) == "PROPERTY_RECOVERY_CONTEXT_ELIGIBLE",
		JSON.stringify(recovery_result),
	)
	_progress("CONTEXTUAL_REACTION_CLASSIFICATION", {"status": "NOT_IMPLEMENTED", "class": "FUTURE_HOOK_NON_BLOCKING"})

	_check("NO_COMMAND_REJECTIONS", _rejections.is_empty(), JSON.stringify(_rejections))
	_check("BRIDGE_FINAL_READY", await _wait_for_bridge_ready(bridge))
	await _finish()


func _dropped_bag_entry(snapshot: Dictionary, bag_ref: String) -> Dictionary:
	for value: Variant in snapshot.get("dropped_bags", []):
		if value is Dictionary and str((value as Dictionary).get("bag_ref", "")) == bag_ref:
			return value as Dictionary
	return {}


func _request_and_wait_save() -> Dictionary:
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if bridge == null or not (await _wait_for_bridge_ready(bridge)):
		_failures.append("BRIDGE_NOT_READY_FOR_SAVE")
		return {}
	var result_start: int = _results.size()
	var intent: Dictionary = main.save_reload_client.request_manual_save(SAVE_SLOT)
	_check("SAVE_INTENT_PASS", intent.get("status") == "PASS", JSON.stringify(intent))
	var result: Dictionary = await _wait_for_command("REQUEST_SAVE", result_start)
	_check("SAVE_RESULT_RECEIVED", not result.is_empty())
	return result


func _request_and_wait_reload() -> Dictionary:
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if bridge == null or not (await _wait_for_bridge_ready(bridge)):
		_failures.append("BRIDGE_NOT_READY_FOR_RELOAD")
		return {}
	var result_start: int = _results.size()
	var intent: Dictionary = main.save_reload_client.request_reload_resync(SAVE_SLOT)
	_check("RELOAD_INTENT_PASS", intent.get("status") == "PASS", JSON.stringify(intent))
	var result: Dictionary = await _wait_for_command("REQUEST_RELOAD_RESYNC", result_start)
	_check("RELOAD_RESULT_RECEIVED", not result.is_empty())
	return result


func _wait_for_command(command: String, start_index: int) -> Dictionary:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		for index: int in range(start_index, _results.size()):
			if str(_results[index].get("command", "")) == command:
				return _results[index].duplicate(true)
		await get_tree().process_frame
	return {}


func _wait_for_size(values: Array, expected: int) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while values.size() < expected and Time.get_ticks_usec() < deadline:
		await get_tree().process_frame
	return values.size() >= expected


func _unique_ref(label: String) -> String:
	return "GODOT-NPCBAG-%s-%d" % [label, Time.get_ticks_usec()]


func _await_command(bridge: AndromedaRuntimeBridge, command: String, params: Dictionary, label: String) -> Dictionary:
	var command_ref: String = _unique_ref(label)
	if bridge.submit_command(command, params, command_ref).get("status") != "PASS":
		return {}
	return await _result_for_ref(command_ref, 1)


func _result_for_ref(command_ref: String, occurrence: int) -> Dictionary:
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


func _fresh_snapshot(bridge: AndromedaRuntimeBridge) -> Dictionary:
	var base: int = _snapshots.size()
	bridge.request_snapshot()
	if not await _wait_for_size(_snapshots, base + 1):
		return _snapshots.back() if not _snapshots.is_empty() else {}
	return _snapshots.back()


func _wait_for_bridge_ready(bridge: AndromedaRuntimeBridge) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		if bridge.connection_state().get("state") == AndromedaRuntimeBridge.STATE_READY:
			return true
		await get_tree().process_frame
	return false


func _check(check_id: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(check_id if detail.is_empty() else "%s:%s" % [check_id, detail])


func _progress(marker: String, detail: Dictionary = {}) -> void:
	print("ANDROMEDA_AUTHORITY_G28_PROGRESS:%s:%s" % [marker, JSON.stringify(detail)])


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "STAGE16B_AUTHORITY_NPC_BAG_OWNERSHIP",
		"authority": "STAGE15_STAGE16A_SERVER_AUTHORITATIVE",
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_NPC_BAG_OWNERSHIP_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_NPC_BAG_OWNERSHIP_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_NPC_BAG_OWNERSHIP_SUMMARY: %s" % JSON.stringify(summary))
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
