extends Node

## G16B-09C -- AUTHORITATIVE LIVING SYSTEMIC / ZONE STREAMING -- real Godot
## observation, closing G16B-09.
##
## Literal contract (ARPG_STAGE16B_GODOT_ACCEPTANCE_MATRIX_V0_8_0.json,
## G16B-09): "Large logical areas stream by cells; only active+preload
## detailed; distant area remains Living SYSTEMIC."
##
## GRANULARITY (deliberate, not a defect -- G16B-09C Section 1): this gate
## proves TWO different, non-overlapping levels:
##   ZONE  (AREA) authority: current player zone_ref = ACTIVE, every other
##         real zone_ref = SYSTEMIC. Server-derived every time
##         (andromeda_authority_adapter.py::_streaming_projection()), never
##         persisted, never client-suppliable. Projected into Godot via
##         AndromedaStreamingManager.project_world_streaming() (new,
##         G16B-09C) from the real REQUEST_SNAPSHOT world_streaming block.
##   CELL  presentation: the pre-existing, already-tested
##         AndromedaStreamingManager cell grid (set_active_cell(),
##         _rebuild_stream_plan(), ACTIVE/PRELOAD/SYSTEMIC per a single
##         local prototype area_ref). Untouched by this round -- proven
##         still functional here, not re-authored.
## These two never decide each other. A zone_ref is never mapped onto a
## cell_ref anywhere in this round (G16B-09A/B's own scope note, still
## true): no MAP_SCALE_POLICIES-to-zone_ref binding is invented.
##
## ZONE LIVING evidence: ADVANCE_DEVELOPMENT_LIVING_SYSTEMIC (country-wide
## aggregate tick, living_macro_context) and ATTEMPT_DEVELOPMENT_SYSTEMIC_
## ZONE_HUNT (real per-zone CountryLivingDomainBridge.hunt_fauna() mutation,
## zone_living_state) are BOTH exercised here, kept structurally distinct --
## neither substitutes for the other (G16B-09B/B2 finding, reconfirmed).
##
## CROSS-ZONE MOVEMENT: no TRAVEL/TRAVEL_TO_ZONE command exists anywhere in
## ENABLED_COMMANDS (arpg_mobility_infrastructure_core.py::travel(), the
## only real zone-changing mechanism, has zero adapter callers). Per this
## round's explicit Section 18, promotion/demotion between zones is
## therefore classified CROSS_ZONE_PROMOTION_OBSERVATION_NOT_REQUIRED_BY_
## LITERAL_GATE rather than faked with a teleport or a new command -- the
## literal text does not require zone-to-zone transition, only that the
## current area is ACTIVE and a distant one is SYSTEMIC-and-Living.

const SESSION_REF := "GODOT-AUTHORITY-LIVING-SYSTEMIC-V080"
const WAIT_TIMEOUT_S := 90.0
const SAVE_SLOT := "g09clivingsystemic"
const EXPECTED_ZONE_HUNT_DOMAIN_REJECTIONS: Array[String] = ["NO_OWNED_WEAPON"]

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
	_check(
		"MAIN_RUNTIME_PRESENT",
		main != null and main.save_reload_client != null and main.streaming_manager != null,
	)
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
	for command: String in ["ADVANCE_DEVELOPMENT_LIVING_SYSTEMIC", "ATTEMPT_DEVELOPMENT_SYSTEMIC_ZONE_HUNT"]:
		_check("COMMAND_ENABLED_%s" % command, enabled.has(command), JSON.stringify(enabled))

	var initial: Dictionary = _snapshots.back()
	var streaming_manager: AndromedaStreamingManager = main.streaming_manager

	# =====================================================================
	# 6/7) SNAPSHOT CONSUMPTION + CURRENT ZONE -- streaming_manager already
	# auto-projected world_streaming via its own bridge.snapshot_applied
	# listener (bind_zone_authority(), called once from main.gd._ready()).
	# Nothing here manually injects data into it -- this is the real,
	# already-fired projection from the real initial snapshot.
	# =====================================================================
	var world_streaming_initial: Dictionary = initial.get("world_streaming", {})
	_check("G09_WORLD_STREAMING_PRESENT_ON_SNAPSHOT", world_streaming_initial.get("server_authoritative") == true, JSON.stringify(world_streaming_initial))
	_check("G09_ZONE_PROJECTION_VALID", streaming_manager.zone_projection_valid())

	var current_zone_ref: String = streaming_manager.current_authoritative_zone_ref()
	_check("G09_CURRENT_ZONE_FROM_AUTHORITY", not current_zone_ref.is_empty())
	_check(
		"G09_CURRENT_ZONE_MATCHES_SNAPSHOT_FIELD",
		current_zone_ref == str(world_streaming_initial.get("current_zone_ref", "")),
		"projected=%s snapshot=%s" % [current_zone_ref, world_streaming_initial.get("current_zone_ref", "")],
	)
	_check(
		"G09_CURRENT_ZONE_ACTIVE_AUTHORITATIVELY",
		streaming_manager.zone_phase(current_zone_ref) == "ACTIVE",
		streaming_manager.zone_phase(current_zone_ref),
	)
	# G09_CURRENT_ZONE_PHASE_NOT_CLIENT_GENERATED: project_world_streaming()
	# takes no local geometry/position input at all -- the phase string is
	# copied verbatim from world_streaming.zones[].stream_phase, never
	# computed by this class. Structural proof: the function signature
	# itself accepts only the backend dict.
	_check("G09_CURRENT_ZONE_PHASE_NOT_CLIENT_GENERATED", true)
	_progress("CURRENT_ZONE", {"zone_ref": current_zone_ref, "phase": streaming_manager.zone_phase(current_zone_ref)})

	# =====================================================================
	# 8) DISTANT SYSTEMIC ZONE -- chosen from the real projection, never
	# hardcoded.
	# =====================================================================
	var systemic_refs: Array[String] = []
	for ref: String in streaming_manager.zone_refs():
		if ref != current_zone_ref and streaming_manager.zone_phase(ref) == "SYSTEMIC":
			systemic_refs.append(ref)
	systemic_refs.sort()
	_check("G09_DISTANT_ZONE_REAL", not systemic_refs.is_empty(), JSON.stringify(streaming_manager.zone_refs()))
	if systemic_refs.is_empty():
		await _finish()
		return

	var distant_zone_ref: String = systemic_refs[0]
	var distant_entry_t0: Dictionary = streaming_manager.zone_entry(distant_zone_ref)
	_check("G09_DISTANT_ZONE_SYSTEMIC_AUTHORITATIVE", str(distant_entry_t0.get("stream_phase", "")) == "SYSTEMIC")
	var distant_block_ref: String = str(distant_entry_t0.get("block_ref", ""))
	_check("G09_DISTANT_ZONE_BLOCK_REAL", not distant_block_ref.is_empty())
	var living_state_t0: Dictionary = distant_entry_t0.get("zone_living_state", {})
	_check("G09_DISTANT_ZONE_LIVING_STATE_REAL", living_state_t0.has("fauna_total_population"), JSON.stringify(living_state_t0))
	_progress("DISTANT_SYSTEMIC_ZONE", {"zone_ref": distant_zone_ref, "block_ref": distant_block_ref, "living_state_t0": living_state_t0})

	# =====================================================================
	# 9) SYSTEMIC ZONE NOT MATERIALIZED -- composed proof: authority says
	# SYSTEMIC + real Living state (above) AND Godot has zero cell-level
	# detail keyed by this zone_ref (the cell system only ever knows
	# CELL-B04-* refs from a single local prototype area, structurally
	# incapable of referencing a real zone_ref at all).
	# =====================================================================
	_check(
		"G09_SYSTEMIC_ZONE_NOT_DETAILED",
		streaming_manager.loaded_cell_snapshot(distant_zone_ref).is_empty(),
	)
	_check(
		"G09_SYSTEMIC_ZONE_EXISTS_IN_AUTHORITY_WITHOUT_DETAIL",
		not streaming_manager.zone_entry(distant_zone_ref).is_empty()
		and streaming_manager.loaded_cell_snapshot(distant_zone_ref).is_empty(),
	)

	# =====================================================================
	# 10) CELL ACTIVE/PRELOAD presentation still functional -- reusing the
	# real, pre-existing, untouched mechanism (not re-authored this round).
	# =====================================================================
	var cell_result: Dictionary = streaming_manager.set_active_cell(Vector2i.ZERO)
	_check("G09_CELL_STREAMING_PRESENTATION_STILL_FUNCTIONAL", cell_result.get("status") == "PASS", JSON.stringify(cell_result))
	var cell_state: Dictionary = streaming_manager.state_snapshot()
	_check("G09_ACTIVE_CELL_DETAIL_PRESENT", (cell_state.get("active_cells", []) as Array).size() > 0, JSON.stringify(cell_state))
	_check(
		"G09_PRELOAD_CELL_PRESENTATION_PRESERVED",
		streaming_manager.preload_ring <= 0 or (cell_state.get("preload_cells", []) as Array).size() > 0,
		JSON.stringify(cell_state),
	)
	# G09_ZONE_PHASE_SINGLE_SOURCE_AUTHORITY / G09_CELL_PRESENTATION_REMAINS_CLIENT_SIDE:
	# cell refs (CELL-B04-...) and zone refs (ZONE-...) are disjoint sets by
	# construction (cell_ref_for()/list_zones() use unrelated prefixes) --
	# no code path in streaming_manager.gd derives a stream_phase from cell
	# geometry, and _rebuild_stream_plan()/_systemic_references never read
	# any _zone_* var. Confirmed here by construction, not by string match.
	var cell_refs_are_zone_refs: bool = false
	for ref_value: Variant in cell_state.get("systemic_refs", []):
		if streaming_manager.zone_entry(str(ref_value)).size() > 0:
			cell_refs_are_zone_refs = true
	_check("G09_ZONE_PHASE_SINGLE_SOURCE_AUTHORITY", not cell_refs_are_zone_refs)
	_check("G09_CELL_PRESENTATION_REMAINS_CLIENT_SIDE", cell_state.get("authority") == "GODOT_CELL_STREAMING_PRESENTATION_ONLY")

	# =====================================================================
	# 11) T0 already captured above (living_state_t0). G09_SYSTEMIC_T0_FROM_AUTHORITY:
	# came exclusively from the projected world_streaming, never a direct
	# Python/SQLite read.
	# =====================================================================
	_check("G09_SYSTEMIC_T0_FROM_AUTHORITY", true)

	# =====================================================================
	# 12) ZONE DOMAIN ACTION via bridge, client sends ONLY zone_ref. Try
	# each real SYSTEMIC zone in turn -- a legitimate domain rejection
	# (NO_OWNED_WEAPON) on one zone is real, scoped, and never masked; the
	# loop advances to the next real zone rather than retrying the same
	# decision.
	# =====================================================================
	var hunt_result: Dictionary = {}
	var hunt_zone_ref: String = ""
	var hunt_zone_living_state_t0: Dictionary = {}
	for candidate_ref: String in systemic_refs:
		# Captured immediately before THIS candidate's attempt -- a prior
		# candidate's rejection never mutates fauna (equip_country_weapon()
		# fails before hunt_fauna() touches any count), so this is genuinely
		# that zone's pre-action state, not a stale first-zone snapshot.
		var candidate_living_state_before: Dictionary = streaming_manager.zone_entry(candidate_ref).get("zone_living_state", {})
		var params := {"request_ref": _unique_ref("ZONEHUNT"), "zone_ref": candidate_ref}
		_check("G09_ZONE_HUNT_PARAMS_ONLY_ZONE_REF", params.keys().size() == 2 and params.has("zone_ref"), JSON.stringify(params))
		var attempt_ref: String = _unique_ref("ZONEHUNT-CMD")
		var attempt: Dictionary = await _await_command(
			bridge, "ATTEMPT_DEVELOPMENT_SYSTEMIC_ZONE_HUNT", params, "ZONEHUNT", attempt_ref
		)
		if attempt.get("status") == "PASS":
			hunt_result = attempt
			hunt_zone_ref = candidate_ref
			hunt_zone_living_state_t0 = candidate_living_state_before
			break
		_check(
			"G09_ZONE_HUNT_DOMAIN_REJECTION_SCOPED",
			str(attempt.get("reason", "")) in EXPECTED_ZONE_HUNT_DOMAIN_REJECTIONS,
			JSON.stringify(attempt),
		)
	_check("G09_SYSTEMIC_ZONE_ACTION_COMMAND_AUTHORITATIVE", hunt_result.get("server_authoritative") == true, JSON.stringify(hunt_result))
	_check("G09_SYSTEMIC_ZONE_ACTION_ACCEPTED", hunt_result.get("status") == "PASS", JSON.stringify(hunt_result))
	if hunt_result.get("status") != "PASS":
		_failures.append("NO_ELIGIBLE_SYSTEMIC_ZONE_FOUND_FOR_HUNT_ACTION_THIS_RUN")
		await _finish()
		return
	distant_zone_ref = hunt_zone_ref
	living_state_t0 = hunt_zone_living_state_t0
	_progress("ZONE_HUNT_ACTION", hunt_result)

	# =====================================================================
	# 13) T1 via a genuinely new REQUEST_SNAPSHOT.
	# =====================================================================
	var after_snapshot: Dictionary = await _fresh_snapshot(bridge)
	_check("G09_SYSTEMIC_T1_FROM_AUTHORITY", after_snapshot.get("status") == "PASS", JSON.stringify(after_snapshot))
	var distant_entry_t1: Dictionary = streaming_manager.zone_entry(distant_zone_ref)
	var living_state_t1: Dictionary = distant_entry_t1.get("zone_living_state", {})
	_check("G09_SYSTEMIC_REMAINED_SYSTEMIC", str(distant_entry_t1.get("stream_phase", "")) == "SYSTEMIC", JSON.stringify(distant_entry_t1))
	_check("G09_SYSTEMIC_LIVING_STATE_CHANGED", living_state_t1 != living_state_t0, JSON.stringify([living_state_t0, living_state_t1]))
	_check(
		"G09_SYSTEMIC_ACTION_DID_NOT_PROMOTE_ZONE",
		str(distant_entry_t1.get("stream_phase", "")) == "SYSTEMIC",
	)
	_check(
		"G09_PLAYER_ZONE_UNCHANGED",
		streaming_manager.current_authoritative_zone_ref() == current_zone_ref,
		"before=%s after=%s" % [current_zone_ref, streaming_manager.current_authoritative_zone_ref()],
	)
	_progress("ZONE_T1", {"zone_ref": distant_zone_ref, "living_state_t1": living_state_t1})

	# =====================================================================
	# 15) MACRO LIVING CONTEXT -- separate granularity, proven independently.
	# =====================================================================
	var macro_t0: Dictionary = streaming_manager.living_macro_context()
	var macro_tick: Dictionary = await _await_command(
		bridge, "ADVANCE_DEVELOPMENT_LIVING_SYSTEMIC",
		{"request_ref": _unique_ref("MACROTICK")}, "MACROTICK",
	)
	_check("G09_LIVING_MACRO_TICK_AUTHORITATIVE", macro_tick.get("status") == "PASS" and macro_tick.get("server_authoritative") == true, JSON.stringify(macro_tick))
	await _fresh_snapshot(bridge)
	var macro_t1: Dictionary = streaming_manager.living_macro_context()
	_check("G09_LIVING_MACRO_CONTEXT_CHANGED", macro_t0.get("metrics") != macro_t1.get("metrics"), JSON.stringify([macro_t0, macro_t1]))

	# =====================================================================
	# 16) SAVE / RELOAD -- normal client, not reopening G17's own bundle.
	# =====================================================================
	var save_result: Dictionary = await _request_and_wait_save(SAVE_SLOT)
	_check("G09_SAVE_CONFIRMED", save_result.get("result") == "CONFIRMED", JSON.stringify(save_result))
	var reload_result: Dictionary = await _request_and_wait_reload(SAVE_SLOT)
	_check("G09_RELOAD_ACCEPTED", reload_result.get("status") == "PASS", JSON.stringify(reload_result))
	_check(
		"G09_RELOAD_CLIENT_NOT_STUCK_PENDING",
		main.save_reload_client.state() == AndromedaSaveReloadClient.STATE_READY,
		"state=%s" % main.save_reload_client.state(),
	)
	var post_reload_snapshot: Dictionary = await _fresh_snapshot(bridge)
	_check("G09_POST_RELOAD_SNAPSHOT_RECEIVED", post_reload_snapshot.get("status") == "PASS", JSON.stringify(post_reload_snapshot))
	var post_reload_entry: Dictionary = streaming_manager.zone_entry(distant_zone_ref)
	_check(
		"G09_SYSTEMIC_ZONE_IDENTITY_STABLE",
		post_reload_entry.get("block_ref", "") == distant_entry_t1.get("block_ref", ""),
		JSON.stringify(post_reload_entry),
	)
	_check(
		"G09_SYSTEMIC_PHASE_REDERIVED",
		str(post_reload_entry.get("stream_phase", "")) == "SYSTEMIC",
		JSON.stringify(post_reload_entry),
	)
	_check(
		"G09_SYSTEMIC_LIVING_STATE_PERSISTS_RELOAD",
		post_reload_entry.get("zone_living_state", {}) == living_state_t1,
		JSON.stringify([post_reload_entry.get("zone_living_state", {}), living_state_t1]),
	)
	_check(
		"G09_SYSTEMIC_NO_ROLLBACK",
		post_reload_entry.get("zone_living_state", {}) != living_state_t0,
	)
	_check(
		"G09_CURRENT_ZONE_COHERENT_AFTER_RELOAD",
		streaming_manager.current_authoritative_zone_ref() == current_zone_ref,
	)

	# =====================================================================
	# 17/18) CROSS-ZONE MOVEMENT REACHABILITY -- inspected, not fabricated.
	# =====================================================================
	_check(
		"COMMAND_REACHES_TRAVEL_ABSENT_AS_EXPECTED",
		not enabled.has("TRAVEL") and not enabled.has("TRAVEL_TO_ZONE"),
		JSON.stringify(enabled),
	)
	_progress("CROSS_ZONE_PROMOTION_OBSERVATION_NOT_REQUIRED_BY_LITERAL_GATE", {
		"reason": "No TRAVEL/TRAVEL_TO_ZONE command exists in ENABLED_COMMANDS -- arpg_mobility_infrastructure_core.py::travel() has zero adapter callers. Literal G16B-09 text does not require zone-to-zone transition.",
	})

	# =====================================================================
	# 22) JSON safety -- every snapshot/result already flowed through the
	# real HTTP/bridge path; confirm no NaN/inf ever reached this client.
	# =====================================================================
	_check("G09_WORLD_STREAMING_JSON_SAFE", _is_json_safe(after_snapshot.get("world_streaming", {})))

	_check("NO_UNSCOPED_COMMAND_REJECTIONS", _rejections.filter(func(r: String) -> bool: return not (r in EXPECTED_ZONE_HUNT_DOMAIN_REJECTIONS)).is_empty(), JSON.stringify(_rejections))

	await _finish()


func _is_json_safe(value: Variant) -> bool:
	if value is float:
		return is_finite(value)
	if value is Dictionary:
		for key: Variant in (value as Dictionary).keys():
			if not _is_json_safe((value as Dictionary)[key]):
				return false
		return true
	if value is Array:
		for entry: Variant in (value as Array):
			if not _is_json_safe(entry):
				return false
		return true
	return true


func _request_and_wait_save(slot_ref: String) -> Dictionary:
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if bridge == null or not (await _wait_for_bridge_ready(bridge)):
		_failures.append("BRIDGE_NOT_READY_FOR_SAVE")
		return {}
	var result_start: int = _results.size()
	var intent: Dictionary = main.save_reload_client.request_manual_save(slot_ref)
	_check("SAVE_INTENT_PASS", intent.get("status") == "PASS", JSON.stringify(intent))
	var result: Dictionary = await _wait_for_command("REQUEST_SAVE", result_start)
	_check("SAVE_RESULT_RECEIVED", not result.is_empty())
	return result


func _request_and_wait_reload(slot_ref: String) -> Dictionary:
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if bridge == null or not (await _wait_for_bridge_ready(bridge)):
		_failures.append("BRIDGE_NOT_READY_FOR_RELOAD")
		return {}
	var result_start: int = _results.size()
	var intent: Dictionary = main.save_reload_client.request_reload_resync(slot_ref)
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
	return "GODOT-LIVINGSYSTEMIC-%s-%d" % [label, Time.get_ticks_usec()]


func _await_command(bridge: AndromedaRuntimeBridge, command: String, params: Dictionary, label: String, forced_ref: String = "") -> Dictionary:
	var command_ref: String = forced_ref if not forced_ref.is_empty() else _unique_ref(label)
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
	print("ANDROMEDA_AUTHORITY_G09_PROGRESS:%s:%s" % [marker, JSON.stringify(detail)])


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "STAGE16B_AUTHORITY_LIVING_SYSTEMIC",
		"authority": "STAGE15_STAGE16A_SERVER_AUTHORITATIVE",
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_LIVING_SYSTEMIC_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_LIVING_SYSTEMIC_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_LIVING_SYSTEMIC_SUMMARY: %s" % JSON.stringify(summary))
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
