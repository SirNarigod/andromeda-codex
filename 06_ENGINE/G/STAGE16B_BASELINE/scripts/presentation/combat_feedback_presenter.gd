extends Control
class_name AndromedaCombatFeedbackPresenter

## B06 presentation-only feedback. Every combat outcome must already be externally confirmed.

signal local_visual_freeze_started(target_ref: String, duration_ms: int)
signal local_visual_freeze_ended(target_ref: String)
signal semantic_feedback_presented(result: Dictionary)

const AUTHORITY := "GODOT_COMBAT_FEEDBACK_PRESENTATION_ONLY"
const NORMAL_HIT_FREEZE_MS := 28
const STRONG_HIT_FREEZE_MS := 42
const CRITICAL_HIT_FREEZE_MS := 58
const MAX_CAMERA_IMPULSE_M := 0.18
const MAX_VISIBLE_FEEDBACK := 3
const DEFAULT_FEEDBACK_S := 0.72

const TOKEN_COMBAT_HIT := "COMBAT_HIT"
const TOKEN_COMBAT_CRITICAL_HIT := "COMBAT_CRITICAL_HIT"
const TOKEN_PLAYER_HURT := "PLAYER_HURT"
const TOKEN_PLAYER_SHIELD_HIT := "PLAYER_SHIELD_HIT"
const TOKEN_TARGET_DEFEATED := "TARGET_DEFEATED"
const TOKEN_INTERACTION_BLOCKED := "INTERACTION_BLOCKED"

const SUPPORTED_TOKENS: Array[String] = [
	TOKEN_COMBAT_HIT,
	TOKEN_COMBAT_CRITICAL_HIT,
	TOKEN_PLAYER_HURT,
	TOKEN_PLAYER_SHIELD_HIT,
	TOKEN_TARGET_DEFEATED,
	TOKEN_INTERACTION_BLOCKED,
]

const FORBIDDEN_GAMEPLAY_FIELDS: Array[String] = [
	"damage",
	"damage_amount",
	"hp_delta",
	"shield_delta",
	"critical_roll",
	"hit_roll",
	"cooldown_remaining",
	"xp_award",
	"loot_result",
]

const FEEDBACK_PRIORITY_CONTRACT := {
	"PLAYER_CRITICAL_DAMAGE": 100,
	"PLAYER_DAMAGE": 95,
	"BOSS_DANGER": 90,
	"CRITICAL_HIT_CONFIRM": 85,
	"HIT_CONFIRM": 80,
	"BLOCKED_INTERACTION": 72,
	"QUEST_UPDATE": 68,
	"INTERACTION_CONFIRM": 60,
	"PICKUP": 50,
	"MOVE_CLICK": 20,
	"AMBIENT": 10,
}

@onready var _edge_flash: ColorRect = $EdgeFlash
@onready var _feedback_panels: Array[PanelContainer] = [
	$FeedbackStack/Feedback1,
	$FeedbackStack/Feedback2,
	$FeedbackStack/Feedback3,
]

var _camera_rig: AndromedaIsometricCameraRig
var _reduced_motion: bool = false
var _visible_events: Array[Dictionary] = []
var _local_freezes: Dictionary = {}
var _edge_flash_remaining_s: float = 0.0
var _last_result: Dictionary = {}


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_edge_flash.visible = false
	for panel: PanelContainer in _feedback_panels:
		panel.visible = false


func _process(delta: float) -> void:
	_update_local_freezes(delta)
	_update_visible_events(delta)
	if _edge_flash_remaining_s > 0.0:
		_edge_flash_remaining_s = maxf(0.0, _edge_flash_remaining_s - delta)
		_edge_flash.modulate.a = minf(1.0, _edge_flash_remaining_s / 0.16)
		if _edge_flash_remaining_s <= 0.0:
			_edge_flash.visible = false


func bind_camera_rig(camera_rig: AndromedaIsometricCameraRig) -> Dictionary:
	if camera_rig == null:
		return _rejected("CAMERA_RIG_REQUIRED")
	_camera_rig = camera_rig
	_camera_rig.set_reduced_motion(_reduced_motion)
	return {
		"status": "PASS",
		"camera_impulse_cap_m": MAX_CAMERA_IMPULSE_M,
		"authority": AUTHORITY,
	}


func present_confirmed_event(event: Dictionary) -> Dictionary:
	var token: String = str(event.get("token", "")).strip_edges().to_upper()
	if token not in SUPPORTED_TOKENS:
		return _rejected("UNSUPPORTED_SEMANTIC_TOKEN")
	for field_name: String in FORBIDDEN_GAMEPLAY_FIELDS:
		if event.has(field_name):
			return _rejected("GAMEPLAY_MUTATION_FIELD_NOT_ACCEPTED:%s" % field_name)
	if token != TOKEN_INTERACTION_BLOCKED and not bool(event.get("confirmed_externally", false)):
		return _rejected("EXTERNAL_CONFIRMATION_REQUIRED")

	var target_ref: String = str(event.get("target_ref", "")).strip_edges()
	if token in [TOKEN_COMBAT_HIT, TOKEN_COMBAT_CRITICAL_HIT, TOKEN_TARGET_DEFEATED] and target_ref.is_empty():
		return _rejected("TARGET_REF_REQUIRED")
	var strength: String = str(event.get("strength", "NORMAL")).strip_edges().to_upper()
	if strength not in ["NORMAL", "STRONG"]:
		return _rejected("UNSUPPORTED_HIT_STRENGTH")
	var critical_received: bool = bool(event.get("critical_received", false))
	var freeze_ms: int = _freeze_duration_ms(token, strength)
	var impulse_m: float = _camera_impulse_m(token, strength, critical_received)
	if _reduced_motion:
		freeze_ms = 0
		impulse_m = 0.0

	var presentation_target: Node3D = event.get("presentation_target") as Node3D
	if freeze_ms > 0 and presentation_target != null:
		_start_local_visual_freeze(presentation_target, target_ref, freeze_ms)
	var camera_result: Dictionary = {
		"status": "NOT_BOUND",
		"applied_impulse_m": 0.0,
	}
	if _camera_rig != null:
		camera_result = _camera_rig.request_presentation_impulse(impulse_m)
		impulse_m = float(camera_result.get("applied_impulse_m", 0.0))

	var priority: int = _priority_for(token, critical_received)
	_queue_visible_event(token, priority)
	if token in [TOKEN_PLAYER_HURT, TOKEN_PLAYER_SHIELD_HIT]:
		_show_edge_flash(token)
	_last_result = {
		"status": "PASS",
		"token": token,
		"semantic_audio_token": token,
		"final_audio_asset": false,
		"target_ref": target_ref,
		"priority": priority,
		"local_visual_freeze_ms": freeze_ms,
		"local_animation_only": true,
		"global_world_pause": false,
		"scene_tree_paused": get_tree().paused,
		"camera_impulse_m": impulse_m,
		"camera_result": camera_result,
		"reduced_motion": _reduced_motion,
		"gameplay_result_changed": false,
		"hp_changed": false,
		"shield_changed": false,
		"critical_decided": false,
		"hit_decided": false,
		"death_decided": false,
		"cooldown_changed": false,
		"authority": AUTHORITY,
	}
	semantic_feedback_presented.emit(_last_result.duplicate(true))
	return _last_result.duplicate(true)


func set_reduced_motion(enabled: bool) -> Dictionary:
	_reduced_motion = enabled
	if _camera_rig != null:
		_camera_rig.set_reduced_motion(enabled)
	if enabled:
		_restore_all_local_freezes()
	return {
		"status": "PASS",
		"reduced_motion": _reduced_motion,
		"camera_impulse_m": 0.0 if enabled else MAX_CAMERA_IMPULSE_M,
		"local_visual_freeze_ms": 0 if enabled else CRITICAL_HIT_FREEZE_MS,
		"information_preserved_without_motion": true,
		"authority": AUTHORITY,
	}


func reduced_motion() -> bool:
	return _reduced_motion


func visible_tokens() -> Array[String]:
	var tokens: Array[String] = []
	for event: Dictionary in _visible_events:
		tokens.append(str(event.get("token", "")))
	return tokens


func visible_priorities() -> Array[int]:
	var priorities: Array[int] = []
	for event: Dictionary in _visible_events:
		priorities.append(int(event.get("priority", 0)))
	return priorities


func local_freeze_count() -> int:
	return _local_freezes.size()


func is_target_locally_frozen(target_ref: String) -> bool:
	for value: Variant in _local_freezes.values():
		var freeze: Dictionary = value
		if str(freeze.get("target_ref", "")) == target_ref:
			return true
	return false


func edge_flash_visible() -> bool:
	return _edge_flash.visible


func last_result() -> Dictionary:
	return _last_result.duplicate(true)


func priority_contract_snapshot() -> Dictionary:
	return FEEDBACK_PRIORITY_CONTRACT.duplicate(true)


func clear_presentation_feedback() -> void:
	_visible_events.clear()
	_restore_all_local_freezes()
	_edge_flash_remaining_s = 0.0
	_edge_flash.visible = false
	_refresh_feedback_stack()


func contract_snapshot() -> Dictionary:
	return {
		"normal_hit_stop_ms_candidate": NORMAL_HIT_FREEZE_MS,
		"strong_hit_stop_ms_candidate": STRONG_HIT_FREEZE_MS,
		"critical_hit_stop_ms_candidate": CRITICAL_HIT_FREEZE_MS,
		"camera_impulse_max_candidate_m": MAX_CAMERA_IMPULSE_M,
		"max_visible_feedback": MAX_VISIBLE_FEEDBACK,
		"feedback_priority": FEEDBACK_PRIORITY_CONTRACT.duplicate(true),
		"semantic_tokens": SUPPORTED_TOKENS.duplicate(),
		"global_hit_stop": false,
		"local_visual_root_only": true,
		"reduced_motion_supported": true,
		"final_audio_assets": false,
		"damage_authority": false,
		"critical_authority": false,
		"death_authority": false,
		"cooldown_authority": false,
		"gameplay_authority_in_gdscript": false,
		"authority": AUTHORITY,
	}


func _freeze_duration_ms(token: String, strength: String) -> int:
	if token == TOKEN_COMBAT_CRITICAL_HIT:
		return CRITICAL_HIT_FREEZE_MS
	if token != TOKEN_COMBAT_HIT:
		return 0
	return STRONG_HIT_FREEZE_MS if strength == "STRONG" else NORMAL_HIT_FREEZE_MS


func _camera_impulse_m(token: String, strength: String, critical_received: bool) -> float:
	match token:
		TOKEN_COMBAT_CRITICAL_HIT:
			return MAX_CAMERA_IMPULSE_M if strength == "STRONG" else 0.13
		TOKEN_COMBAT_HIT:
			return 0.13 if strength == "STRONG" else 0.08
		TOKEN_PLAYER_HURT:
			return 0.14 if critical_received else 0.08
		TOKEN_PLAYER_SHIELD_HIT:
			return 0.08
		TOKEN_TARGET_DEFEATED:
			return 0.13
		_:
			return 0.0


func _priority_for(token: String, critical_received: bool) -> int:
	match token:
		TOKEN_PLAYER_HURT:
			return 100 if critical_received else 95
		TOKEN_PLAYER_SHIELD_HIT:
			return 95
		TOKEN_COMBAT_CRITICAL_HIT:
			return 85
		TOKEN_TARGET_DEFEATED:
			return 85
		TOKEN_COMBAT_HIT:
			return 80
		TOKEN_INTERACTION_BLOCKED:
			return 72
		_:
			return 0


func _start_local_visual_freeze(target: Node3D, target_ref: String, duration_ms: int) -> void:
	var visual_root: Node = target.get_node_or_null("VisualRoot")
	if visual_root == null:
		return
	var instance_key: int = visual_root.get_instance_id()
	var duration_s: float = float(duration_ms) / 1000.0
	if _local_freezes.has(instance_key):
		var existing: Dictionary = _local_freezes[instance_key]
		existing["remaining_s"] = maxf(float(existing.get("remaining_s", 0.0)), duration_s)
		_local_freezes[instance_key] = existing
		return
	_local_freezes[instance_key] = {
		"node": visual_root,
		"target_ref": target_ref,
		"previous_process_mode": visual_root.process_mode,
		"remaining_s": duration_s,
	}
	visual_root.process_mode = Node.PROCESS_MODE_DISABLED
	local_visual_freeze_started.emit(target_ref, duration_ms)


func _update_local_freezes(delta: float) -> void:
	var completed_keys: Array[int] = []
	for key_value: Variant in _local_freezes.keys():
		var key: int = int(key_value)
		var freeze: Dictionary = _local_freezes[key]
		freeze["remaining_s"] = maxf(0.0, float(freeze.get("remaining_s", 0.0)) - delta)
		_local_freezes[key] = freeze
		if float(freeze.get("remaining_s", 0.0)) <= 0.0:
			completed_keys.append(key)
	for key: int in completed_keys:
		_restore_local_freeze(key)


func _restore_local_freeze(key: int) -> void:
	if not _local_freezes.has(key):
		return
	var freeze: Dictionary = _local_freezes[key]
	var visual_root: Node = freeze.get("node") as Node
	if visual_root != null and is_instance_valid(visual_root):
		visual_root.process_mode = int(freeze.get("previous_process_mode", Node.PROCESS_MODE_INHERIT)) as ProcessMode
	var target_ref: String = str(freeze.get("target_ref", ""))
	_local_freezes.erase(key)
	local_visual_freeze_ended.emit(target_ref)


func _restore_all_local_freezes() -> void:
	var keys: Array[int] = []
	for key_value: Variant in _local_freezes.keys():
		keys.append(int(key_value))
	for key: int in keys:
		_restore_local_freeze(key)


func _queue_visible_event(token: String, priority: int) -> void:
	_visible_events.append({
		"token": token,
		"priority": priority,
		"remaining_s": DEFAULT_FEEDBACK_S,
	})
	_visible_events.sort_custom(_sort_priority_desc)
	if _visible_events.size() > MAX_VISIBLE_FEEDBACK:
		_visible_events.resize(MAX_VISIBLE_FEEDBACK)
	_refresh_feedback_stack()


func _sort_priority_desc(left: Dictionary, right: Dictionary) -> bool:
	return int(left.get("priority", 0)) > int(right.get("priority", 0))


func _update_visible_events(delta: float) -> void:
	var changed: bool = false
	for index: int in range(_visible_events.size() - 1, -1, -1):
		var event: Dictionary = _visible_events[index]
		event["remaining_s"] = maxf(0.0, float(event.get("remaining_s", 0.0)) - delta)
		if float(event.get("remaining_s", 0.0)) <= 0.0:
			_visible_events.remove_at(index)
			changed = true
		else:
			_visible_events[index] = event
	if changed:
		_refresh_feedback_stack()


func _refresh_feedback_stack() -> void:
	for index: int in range(_feedback_panels.size()):
		var panel: PanelContainer = _feedback_panels[index]
		if index >= _visible_events.size():
			panel.visible = false
			continue
		var event: Dictionary = _visible_events[index]
		var token: String = str(event.get("token", ""))
		var label := panel.get_node("Label") as Label
		label.text = _label_for(token)
		label.add_theme_color_override("font_color", _color_for(token))
		panel.visible = true


func _label_for(token: String) -> String:
	return {
		TOKEN_COMBAT_HIT: "IMPACTO",
		TOKEN_COMBAT_CRITICAL_HIT: "CRÍTICO",
		TOKEN_PLAYER_HURT: "DANO RECEBIDO",
		TOKEN_PLAYER_SHIELD_HIT: "PROTEÇÃO",
		TOKEN_TARGET_DEFEATED: "ALVO DERROTADO",
		TOKEN_INTERACTION_BLOCKED: "AÇÃO BLOQUEADA",
	}.get(token, token)


func _color_for(token: String) -> Color:
	if token in [TOKEN_COMBAT_CRITICAL_HIT, TOKEN_TARGET_DEFEATED, TOKEN_PLAYER_SHIELD_HIT]:
		return Color("d9a15f")
	if token == TOKEN_PLAYER_HURT:
		return Color("b86f58")
	return Color("6b6b6b")


func _show_edge_flash(token: String) -> void:
	_edge_flash.color = Color(0.85, 0.63, 0.37, 0.16) if token == TOKEN_PLAYER_SHIELD_HIT else Color(0.72, 0.38, 0.3, 0.14)
	_edge_flash.modulate.a = 1.0
	_edge_flash.visible = true
	_edge_flash_remaining_s = 0.16


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
