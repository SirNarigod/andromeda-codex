extends Node
class_name AndromedaNpcDialogueClient

## G16B-19C2: minimal production dialogue transport client.
##
## Consumes the backend-authoritative dialogue_npc_projection (a top-level
## snapshot field -- see andromeda_authority_adapter.py's
## _dialogue_npc_projection(), G16B-19C1), submits REQUEST_NPC_DIALOGUE for
## exactly that server-selected npc_ref, validates the real result against
## the full contract REQUEST_NPC_DIALOGUE guarantees, and hands the real
## line to HUD for presentation. It never decides which NPC, never invents
## content, never falls back to local/fixture text, and never reuses a
## combat target as a dialogue target.
##
## Node3D anchors (e.g. NPCB03) remain pure presentation -- this client
## never treats a Node3D as proof of identity; the only identity source is
## dialogue_npc_projection.npc_ref. Client-side proximity (quest_client's
## own 1.5m gate, if used before calling this) is a presentation
## interaction gate only, never server-side spatial authority -- the
## backend has no per-NPC metric position (see G16B-19C1/C2 closure notes).
##
## PREFERENCE B (per G16B-19C2 Section 3): quest_client.gd's own dialogue-
## adjacent flow (begin_quest_interaction/_open_quest_for_npc) is tightly
## coupled to the pre-existing fake npc anchor system (_npcs_by_ref built
## from Godot-authored target_ref strings, quest_projection.offers[].npc_ref
## which is server-fabricated -- see _quest_npc_ref() in
## andromeda_authority_adapter.py). Reusing that machinery for the real
## dialogue_npc_projection identity would either weaken its existing
## contract or require rewiring it to a different identity source
## mid-flight. This dedicated client avoids both risks. quest_client.gd
## itself is UNCHANGED; ACCEPT_QUEST for the quest this dialogue returns
## still goes through the bridge the same way every other real command
## does -- no second quest state machine, no duplicated bridge.

signal dialogue_presented(result: Dictionary)

const AUTHORITY := "GODOT_NPC_DIALOGUE_CLIENT_PROJECTION_ONLY"
const EXPECTED_COPY_AUTHORITY := "GAMEPLAY_PLACEHOLDER_COPY_NOT_CANON_DIALOGUE"
const EXPECTED_PROJECTION_AUTHORITY := "STAGE16B_SERVER_SELECTED_DEVELOPMENT_DIALOGUE_TARGET"
const RESULT_TIMEOUT_S := 15.0

var _main_runtime: AndromedaMainRuntime
var _hud: AndromedaHUDController
var _bound: bool = false
var _dialogue_npc_projection: Dictionary = {}
var _projection_session_ref: String = ""
var _received_results: Dictionary = {}


func bind_runtime(main_runtime_value: AndromedaMainRuntime, hud_value: AndromedaHUDController) -> Dictionary:
	if main_runtime_value == null or hud_value == null:
		return _rejected("MAIN_AND_HUD_REQUIRED")
	_main_runtime = main_runtime_value
	_hud = hud_value
	if not _bound:
		var bridge: AndromedaRuntimeBridge = _bridge()
		if bridge != null:
			if not bridge.snapshot_applied.is_connected(_on_bridge_snapshot_applied):
				bridge.snapshot_applied.connect(_on_bridge_snapshot_applied)
			if not bridge.command_result_received.is_connected(_on_bridge_command_result_received):
				bridge.command_result_received.connect(_on_bridge_command_result_received)
		var session: AndromedaClientSession = _session()
		if session != null:
			if not session.session_bound.is_connected(_on_session_bound):
				session.session_bound.connect(_on_session_bound)
			if not session.session_revoked.is_connected(_on_session_revoked):
				session.session_revoked.connect(_on_session_revoked)
		_bound = true
	return {"status": "PASS", "authority": AUTHORITY}


func dialogue_target_available() -> bool:
	return not projected_npc_ref().is_empty()


## The ONLY identity source. Never a Node3D.target_ref, never combat_targets,
## never a locally chosen/derived npc_id.
func projected_npc_ref() -> String:
	if str(_dialogue_npc_projection.get("authority", "")) != EXPECTED_PROJECTION_AUTHORITY:
		return ""
	if not bool(_dialogue_npc_projection.get("available", false)):
		return ""
	if bool(_dialogue_npc_projection.get("canonical_identity", true)):
		return ""
	return str(_dialogue_npc_projection.get("npc_ref", "")).strip_edges()


## speaker_anchor is a presentation-only Node3D (e.g. NPCB03) used solely to
## anchor the HUD bubble in world space -- it never supplies identity.
func request_dialogue(speaker_anchor: Node3D = null) -> Dictionary:
	var npc_ref: String = projected_npc_ref()
	if npc_ref.is_empty():
		return _rejected("DIALOGUE_TARGET_NOT_PROJECTED")
	var bridge: AndromedaRuntimeBridge = _bridge()
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	var params := {"npc_target_ref": npc_ref}
	var built: Dictionary = bridge.build_command_envelope("REQUEST_NPC_DIALOGUE", params)
	if built.get("status") != "PASS":
		return built
	var envelope: Dictionary = built.get("envelope", {}) as Dictionary
	var command_ref: String = str(envelope.get("command_ref", ""))
	var submit: Dictionary = bridge.submit_command("REQUEST_NPC_DIALOGUE", params, command_ref)
	if submit.get("status") != "PASS":
		return submit
	var result: Dictionary = await _await_result(command_ref)
	if result.is_empty():
		return _rejected("DIALOGUE_RESULT_TIMEOUT", {"npc_ref": npc_ref, "command_ref": command_ref})
	var validation: Dictionary = _validate_result(result, npc_ref)
	if validation.get("status") != "PASS":
		return validation
	var presentation: Dictionary = {}
	if speaker_anchor != null and _hud != null:
		presentation = _hud.present_dialogue_line(speaker_anchor, {
			"line_ref": str(result.get("dialogue_ref", "")),
			"speaker_ref": npc_ref,
			"conversation_ref": "NPC-DIALOGUE:%s" % npc_ref,
			"turn_index": 0,
			"text": str(result.get("line", "")),
			"important": false,
		})
	var out := {
		"status": "PASS",
		"npc_ref": npc_ref,
		"dialogue_ref": str(result.get("dialogue_ref", "")),
		"line": str(result.get("line", "")),
		"copy_authority": str(result.get("copy_authority", "")),
		"speech_acts": (result.get("speech_acts", []) as Array).duplicate(true),
		"source_refs": (result.get("source_refs", []) as Array).duplicate(true),
		"related_quest_ref": str(result.get("related_quest_ref", "")),
		"choices": (result.get("choices", []) as Array).duplicate(true),
		"branching_required": bool(result.get("branching_required", false)),
		"presentation": presentation,
		"content_source": "BACKEND_AUTHORITATIVE",
		"authority": AUTHORITY,
	}
	dialogue_presented.emit(out.duplicate(true))
	return out


func _validate_result(result: Dictionary, requested_npc_ref: String) -> Dictionary:
	if result.get("status") != "PASS":
		return _rejected("DIALOGUE_COMMAND_REJECTED", {"detail": result})
	if result.get("server_authoritative") != true:
		return _rejected("DIALOGUE_RESULT_NOT_SERVER_AUTHORITATIVE")
	if str(result.get("npc_ref", "")) != requested_npc_ref:
		return _rejected("DIALOGUE_RESULT_NPC_REF_MISMATCH")
	if str(result.get("dialogue_ref", "")).strip_edges().is_empty():
		return _rejected("DIALOGUE_REF_EMPTY")
	if str(result.get("line", "")).strip_edges().is_empty():
		return _rejected("DIALOGUE_LINE_EMPTY")
	if str(result.get("copy_authority", "")) != EXPECTED_COPY_AUTHORITY:
		return _rejected("DIALOGUE_COPY_AUTHORITY_UNEXPECTED")
	if str(result.get("related_quest_ref", "")).strip_edges().is_empty():
		return _rejected("DIALOGUE_RELATED_QUEST_REF_EMPTY")
	var choices_value: Variant = result.get("choices", null)
	if not choices_value is Array or not (choices_value as Array).is_empty():
		return _rejected("DIALOGUE_CHOICES_NOT_EMPTY")
	if result.get("branching_required", true) != false:
		return _rejected("DIALOGUE_BRANCHING_UNEXPECTEDLY_REQUIRED")
	return {"status": "PASS", "authority": AUTHORITY}


func _await_result(command_ref: String) -> Dictionary:
	var deadline: int = Time.get_ticks_msec() + int(RESULT_TIMEOUT_S * 1000.0)
	while Time.get_ticks_msec() < deadline:
		if _received_results.has(command_ref):
			var result: Dictionary = _received_results[command_ref]
			_received_results.erase(command_ref)
			return result
		await get_tree().process_frame
	return {}


func _on_bridge_command_result_received(result: Dictionary) -> void:
	if str(result.get("command", "")).strip_edges().to_upper() != "REQUEST_NPC_DIALOGUE":
		return
	var command_ref: String = str(result.get("command_ref", ""))
	if command_ref.is_empty():
		return
	_received_results[command_ref] = result.duplicate(true)


func _on_bridge_snapshot_applied(snapshot: Dictionary) -> void:
	var projection_value: Variant = snapshot.get("dialogue_npc_projection")
	_dialogue_npc_projection = (projection_value as Dictionary) if projection_value is Dictionary else {}
	_projection_session_ref = str(snapshot.get("session_ref", ""))


func _on_session_bound(session_ref_value: String, _session_epoch: int) -> void:
	if not _projection_session_ref.is_empty() and _projection_session_ref != session_ref_value:
		_dialogue_npc_projection = {}
		_projection_session_ref = ""
	_received_results.clear()


func _on_session_revoked(_previous_session_ref: String, _session_epoch: int) -> void:
	_dialogue_npc_projection = {}
	_projection_session_ref = ""
	_received_results.clear()


func _bridge() -> AndromedaRuntimeBridge:
	return get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge


func _session() -> AndromedaClientSession:
	return get_node_or_null("/root/ClientSession") as AndromedaClientSession


func _rejected(reason: String, detail: Dictionary = {}) -> Dictionary:
	var result := {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
	result.merge(detail, true)
	return result
