extends Node

## G16B-19C2 -- AUTHORITATIVE NPC DIALOGUE -- dedicated Godot gate.
##
## Proves, independently of the full G19 vertical slice, that the
## REQUEST_NPC_DIALOGUE integration is real end to end: snapshot ->
## dialogue_npc_projection (G16B-19C1) -> AndromedaNpcDialogueClient
## (main.npc_dialogue_client, G16B-19C2) -> real backend result -> real HUD
## presentation -> related_quest_ref -> real ACCEPT_QUEST -> ACTIVE. Does
## NOT duplicate the 36 Python backend tests -- this is the Godot-side
## wiring proof only.

const SESSION_REF := "GODOT-AUTHORITY-NPC-DIALOGUE-V080"
const WAIT_TIMEOUT_S := 60.0
const EXPECTED_PROJECTION_AUTHORITY := "STAGE16B_SERVER_SELECTED_DEVELOPMENT_DIALOGUE_TARGET"
const EXPECTED_COPY_AUTHORITY := "GAMEPLAY_PLACEHOLDER_COPY_NOT_CANON_DIALOGUE"
const EXPECTED_RELATED_QUEST_REF := "QST-S12-VARGA-ORIENTATION"

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
		main != null and main.hud != null and main.npc_dialogue_client != null and main.dialogue_npc_primary != null,
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

	# =====================================================================
	# 1) REQUEST_SNAPSHOT real.
	# =====================================================================
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
	var initial: Dictionary = _snapshots.back()
	_check("G19D_SNAPSHOT_REAL", initial.get("status") == "PASS" and initial.get("server_authoritative") == true, JSON.stringify(initial.get("status")))

	# =====================================================================
	# 2-6) dialogue_npc_projection exists / available / npc_ref real /
	# canonical_identity=false / authority label correct.
	# =====================================================================
	var projection_value: Variant = initial.get("dialogue_npc_projection")
	_check("G19D_PROJECTION_EXISTS", projection_value is Dictionary)
	var projection: Dictionary = projection_value if projection_value is Dictionary else {}
	_check("G19D_PROJECTION_AVAILABLE", bool(projection.get("available", false)), JSON.stringify(projection))
	var npc_ref: String = str(projection.get("npc_ref", "")).strip_edges()
	_check("G19D_PROJECTION_NPC_REF_FROM_BACKEND", not npc_ref.is_empty(), JSON.stringify(projection))
	_check("G19D_PROJECTION_CANONICAL_IDENTITY_FALSE", projection.get("canonical_identity") == false, JSON.stringify(projection))
	_check("G19D_PROJECTION_AUTHORITY_LABEL_CORRECT", str(projection.get("authority", "")) == EXPECTED_PROJECTION_AUTHORITY, JSON.stringify(projection))
	if npc_ref.is_empty():
		await _finish()
		return

	# =====================================================================
	# 7-18) REQUEST_NPC_DIALOGUE via AndromedaNpcDialogueClient, using
	# exactly the projected ref. Real HUD presentation.
	# =====================================================================
	var dialogue_result: Dictionary = await main.npc_dialogue_client.request_dialogue(main.dialogue_npc_primary)
	_check("G19D_DIALOGUE_COMMAND_SENT_WITH_PROJECTED_REF", dialogue_result.get("npc_ref", "") == npc_ref, JSON.stringify(dialogue_result))
	_check("G19D_DIALOGUE_RESULT_PASS", dialogue_result.get("status") == "PASS", JSON.stringify(dialogue_result))
	_check("G19D_DIALOGUE_RESULT_NPC_REF_MATCHES", str(dialogue_result.get("npc_ref", "")) == npc_ref, JSON.stringify(dialogue_result))
	_check("G19D_DIALOGUE_REF_REAL", not str(dialogue_result.get("dialogue_ref", "")).is_empty(), JSON.stringify(dialogue_result))
	_check("G19D_LINE_NOT_EMPTY", not str(dialogue_result.get("line", "")).strip_edges().is_empty(), JSON.stringify(dialogue_result))
	_check("G19D_COPY_AUTHORITY_CORRECT", str(dialogue_result.get("copy_authority", "")) == EXPECTED_COPY_AUTHORITY, JSON.stringify(dialogue_result))
	var speech_acts: Array = dialogue_result.get("speech_acts", [])
	_check("G19D_SPEECH_ACTS_PRESENT", not speech_acts.is_empty(), JSON.stringify(speech_acts))
	var source_refs: Array = dialogue_result.get("source_refs", [])
	_check("G19D_SOURCE_REFS_PRESENT", not source_refs.is_empty(), JSON.stringify(source_refs))
	var choices: Array = dialogue_result.get("choices", [])
	_check("G19D_CHOICES_EMPTY", choices.is_empty(), JSON.stringify(choices))
	_check("G19D_BRANCHING_NOT_REQUIRED", dialogue_result.get("branching_required", true) == false)
	var presentation: Dictionary = dialogue_result.get("presentation", {})
	_check("G19D_HUD_RECEIVED_REAL_LINE", presentation.get("status", "") == "PASS", JSON.stringify(presentation))
	_check("G19D_CONTENT_SOURCE_BACKEND_AUTHORITATIVE", str(dialogue_result.get("content_source", "")) == "BACKEND_AUTHORITATIVE", JSON.stringify(dialogue_result))
	var related_quest_ref: String = str(dialogue_result.get("related_quest_ref", ""))
	_check("G19D_RELATED_QUEST_REF_FROM_BACKEND", not related_quest_ref.is_empty(), JSON.stringify(dialogue_result))
	_progress("DIALOGUE", dialogue_result)

	# =====================================================================
	# 19-21) ACCEPT_QUEST using the dialogue result's own related_quest_ref
	# -> ACTIVE.
	# =====================================================================
	if related_quest_ref.is_empty():
		await _finish()
		return
	_check("G19D_RELATED_QUEST_MATCHES_EXPECTED_AUDIT_ONLY", related_quest_ref == EXPECTED_RELATED_QUEST_REF, related_quest_ref)
	var accept_ref: String = "GODOT-DIALOGUE-QUEST-ACCEPT-%d" % Time.get_ticks_usec()
	if bridge.submit_command("ACCEPT_QUEST", {"quest_ref": related_quest_ref}, accept_ref).get("status") != "PASS":
		_failures.append("ACCEPT_QUEST_SUBMIT_FAILED")
		await _finish()
		return
	var quest_accept: Dictionary = await _result_for_ref(accept_ref, 1)
	_check("G19D_ACCEPT_QUEST_COMMAND_REAL", quest_accept.get("status") == "PASS" and quest_accept.get("server_authoritative") == true, JSON.stringify(quest_accept))
	_check("G19D_QUEST_ACTIVE_REAL", str(quest_accept.get("quest", {}).get("state", "")) == "ACTIVE", JSON.stringify(quest_accept))
	_progress("QUEST", {"quest_ref": related_quest_ref})

	# =====================================================================
	# 22) No local content was used -- content_source is stamped
	# BACKEND_AUTHORITATIVE by npc_dialogue_client.gd only after its own
	# _validate_result() accepted a real command result (checks 8-16
	# above); this gate never authors a line/dialogue_ref/npc_ref itself
	# anywhere in this file, and the presented text does not match either
	# of the old presentation-only fixture strings this gate replaced.
	# =====================================================================
	_check(
		"G19D_NO_LOCAL_CONTENT_USED",
		str(dialogue_result.get("content_source", "")) == "BACKEND_AUTHORITATIVE"
		and not str(dialogue_result.get("line", "")).begins_with("[G19"),
		JSON.stringify(dialogue_result),
	)

	# =====================================================================
	# 23) Replay: same command_ref -> same result, no duplicate mutation.
	# Cheap direct bridge submission (bypasses the client's own auto-ref
	# generation on purpose, to force an identical command_ref twice).
	# =====================================================================
	var replay_ref: String = "GODOT-DIALOGUE-REPLAY-%d" % Time.get_ticks_usec()
	bridge.submit_command("REQUEST_NPC_DIALOGUE", {"npc_target_ref": npc_ref}, replay_ref)
	var first_replay: Dictionary = await _result_for_ref(replay_ref, 1)
	bridge.submit_command("REQUEST_NPC_DIALOGUE", {"npc_target_ref": npc_ref}, replay_ref)
	var second_replay: Dictionary = await _result_for_ref(replay_ref, 2)
	_check(
		"G19D_REPLAY_SAME_COMMAND_REF_SAME_RESULT",
		first_replay.get("status") == "PASS" and second_replay.get("status") == "PASS"
		and str(first_replay.get("line", "")) == str(second_replay.get("line", ""))
		and str(first_replay.get("dialogue_ref", "")) == str(second_replay.get("dialogue_ref", "")),
		JSON.stringify({"first": first_replay, "second": second_replay}),
	)

	# =====================================================================
	# NO_COMMAND_REJECTIONS -- no rejection expected anywhere in this run.
	# =====================================================================
	_check("NO_COMMAND_REJECTIONS", _rejections.is_empty(), JSON.stringify(_rejections))

	await _finish()


func _wait_for_size(values: Array, expected: int) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while values.size() < expected and Time.get_ticks_usec() < deadline:
		await get_tree().process_frame
	return values.size() >= expected


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


func _check(check_id: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(check_id if detail.is_empty() else "%s:%s" % [check_id, detail])


func _progress(marker: String, detail: Dictionary = {}) -> void:
	print("ANDROMEDA_AUTHORITY_G19D_PROGRESS:%s:%s" % [marker, JSON.stringify(detail)])


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "STAGE16B_AUTHORITY_NPC_DIALOGUE",
		"authority": "STAGE15_STAGE16A_SERVER_AUTHORITATIVE",
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_NPC_DIALOGUE_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_NPC_DIALOGUE_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_NPC_DIALOGUE_SUMMARY: %s" % JSON.stringify(summary))
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
