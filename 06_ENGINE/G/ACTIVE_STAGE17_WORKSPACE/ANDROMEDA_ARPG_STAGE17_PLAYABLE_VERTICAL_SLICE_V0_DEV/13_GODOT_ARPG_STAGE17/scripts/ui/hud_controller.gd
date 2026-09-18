extends Control
class_name AndromedaHUDController

## B05/B06 presentation coordinator. It projects snapshots without gameplay authority.

signal weapon_intent_projected(result: Dictionary)
signal inventory_state_changed(open: bool)
signal dialogue_line_projected(result: Dictionary)
signal dialogue_choice_projected(result: Dictionary)
signal modal_state_changed(layer: String, open: bool)
signal crafting_intent_projected(result: Dictionary)

const AUTHORITY := "GODOT_HUD_WORLD_UI_PRESENTATION_ONLY"
const DIALOGUE_POOL_CAPACITY := 3
const CHOICE_RANGE_M_CANDIDATE := 2.0
const TEMPORARY_FEEDBACK_S := 1.8
const ENEMY_COMBAT_BAR_SCENE := preload("res://scenes/ui/EnemyCombatBar.tscn")

@onready var stamina_ring: AndromedaStaminaWorldRing = $WorldUIRoot/StaminaWorldRing
@onready var weapon_quick_slots: AndromedaWeaponQuickSlots = $WeaponQuickSlots
@onready var inventory_shell: AndromedaInventoryShell = $InventoryPanel
@onready var vendor_panel: AndromedaVendorPanel = $VendorPanel
@onready var quest_panel: AndromedaQuestPanel = $QuestPanel
@onready var crafting_panel: AndromedaCraftingPanel = $CraftingPanel
@onready var death_recovery_overlay: AndromedaDeathRecoveryOverlay = $DeathRecoveryOverlay
@onready var player_combat_vitals: AndromedaPlayerCombatVitals = $PlayerCombatVitals
@onready var combat_feedback: AndromedaCombatFeedbackPresenter = $CombatFeedbackPresenter
@onready var _enemy_combat_bar_layer: Control = $WorldUIRoot/EnemyCombatBarLayer
@onready var _context_action: PanelContainer = $ContextAction
@onready var _context_action_label: Label = $ContextAction/Label
@onready var _selection_feedback: PanelContainer = $SelectionFeedback
@onready var _selection_feedback_label: Label = $SelectionFeedback/Label
@onready var _important_dialogue_line: PanelContainer = $ImportantDialogueLine
@onready var _important_dialogue_label: Label = $ImportantDialogueLine/Label
@onready var _auto_pickup_status: PanelContainer = $AutoPickupStatus
@onready var _auto_pickup_label: Label = $AutoPickupStatus/Label
@onready var _quest_feedback_stack: VBoxContainer = $QuestFeedbackStack
@onready var _dialogue_bubbles: Array[AndromedaDialogueBubble] = [
	$WorldUIRoot/DialogueBubblePool/Bubble1,
	$WorldUIRoot/DialogueBubblePool/Bubble2,
	$WorldUIRoot/DialogueBubblePool/Bubble3,
]

var _main_runtime: Node
var _player: Node3D
var _camera: Camera3D
var _camera_rig: AndromedaIsometricCameraRig
var _dialogue_actors_by_ref: Dictionary = {}
var _combat_actors_by_ref: Dictionary = {}
var _enemy_bars_by_ref: Dictionary = {}
var _conversation_bubble_index: Dictionary = {}
var _conversation_last_turn: Dictionary = {}
var _bubble_last_used_serial: Array[int] = [0, 0, 0]
var _dialogue_serial: int = 0
var _selection_feedback_remaining_s: float = 0.0
var _important_line_remaining_s: float = 0.0
var _auto_pickup_remaining_s: float = 0.0
var _last_weapon_intent: Dictionary = {}
var _last_choice_intent: Dictionary = {}
var _last_auto_pickup_intent: Dictionary = {}
var _last_crafting_intent: Dictionary = {}
var _active_modal: String = ""
var _quest_feedbacks: Array[Dictionary] = []
var _bound: bool = false


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_context_action.visible = false
	_selection_feedback.visible = false
	_important_dialogue_line.visible = false
	_auto_pickup_status.visible = false
	vendor_panel.set_open(false)
	quest_panel.set_open(false)
	crafting_panel.set_open(false)
	crafting_panel.craft_intent_requested.connect(_on_crafting_intent_requested)
	crafting_panel.close_requested.connect(_on_crafting_close_requested)
	for bubble: AndromedaDialogueBubble in _dialogue_bubbles:
		bubble.choice_intent_requested.connect(_on_choice_intent_requested)
	inventory_shell.auto_pickup_visual_changed.connect(_on_auto_pickup_visual_changed)


func _process(delta: float) -> void:
	_selection_feedback_remaining_s = maxf(0.0, _selection_feedback_remaining_s - delta)
	_important_line_remaining_s = maxf(0.0, _important_line_remaining_s - delta)
	_auto_pickup_remaining_s = maxf(0.0, _auto_pickup_remaining_s - delta)
	if _selection_feedback_remaining_s <= 0.0:
		_selection_feedback.visible = false
	if _important_line_remaining_s <= 0.0:
		_important_dialogue_line.visible = false
	if _auto_pickup_remaining_s <= 0.0:
		_auto_pickup_status.visible = false


func bind_runtime(
	main_runtime: Node,
	player_node: Node3D,
	camera_node: Camera3D,
	dialogue_actors: Array[Node3D],
	combat_actors: Array[Node3D] = [],
	camera_rig_node: AndromedaIsometricCameraRig = null
) -> Dictionary:
	if main_runtime == null or player_node == null or camera_node == null:
		return _rejected("MAIN_PLAYER_CAMERA_REQUIRED")
	_main_runtime = main_runtime
	_player = player_node
	_camera = camera_node
	_camera_rig = camera_rig_node
	if _camera_rig == null:
		_camera_rig = camera_node.get_parent() as AndromedaIsometricCameraRig
	stamina_ring.bind_projection(_player, _camera)
	if _camera_rig != null:
		combat_feedback.bind_camera_rig(_camera_rig)
	_dialogue_actors_by_ref.clear()
	for actor: Node3D in dialogue_actors:
		if actor == null:
			continue
		var target_ref: String = str(actor.get("target_ref")).strip_edges()
		if not target_ref.is_empty():
			_dialogue_actors_by_ref[target_ref] = actor
	_register_combat_actors(combat_actors)
	if not _bound:
		if _main_runtime.has_signal("hover_resolution_changed"):
			_main_runtime.connect("hover_resolution_changed", Callable(self, "_on_hover_resolution_changed"))
		if _main_runtime.has_signal("target_selection_changed"):
			_main_runtime.connect("target_selection_changed", Callable(self, "_on_target_selection_changed"))
		var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
		if bridge != null:
			bridge.snapshot_applied.connect(_on_snapshot_applied)
		_bound = true
	return {
		"status": "PASS",
		"dialogue_actor_count": _dialogue_actors_by_ref.size(),
		"dialogue_pool_capacity": DIALOGUE_POOL_CAPACITY,
		"combat_actor_count": _combat_actors_by_ref.size(),
		"enemy_bar_count": _enemy_bars_by_ref.size(),
		"gameplay_authority_in_gdscript": false,
		"authority": AUTHORITY,
	}


func project_stamina(fraction_value: float, activity: String, source: String) -> Dictionary:
	return stamina_ring.project_stamina(fraction_value, activity, source)


func project_player_combat_vitals(
	hp_fraction: float,
	protection_fraction: float,
	relevant: bool,
	source: String
) -> Dictionary:
	return player_combat_vitals.project_vitals(
		hp_fraction,
		protection_fraction,
		relevant,
		source
	)


func project_enemy_combat_vitals(
	target_ref: String,
	hp_fraction: float,
	shield_fraction: float,
	engaged: bool,
	source: String
) -> Dictionary:
	var bar: AndromedaEnemyCombatBar = enemy_bar_for_ref(target_ref)
	if bar == null:
		return _rejected("ENEMY_BAR_NOT_FOUND")
	return bar.project_vitals(hp_fraction, shield_fraction, engaged, source)


func present_combat_event(event: Dictionary) -> Dictionary:
	var prepared: Dictionary = event.duplicate(true)
	var token: String = str(prepared.get("token", "")).strip_edges().to_upper()
	var target_ref: String = str(prepared.get("target_ref", "")).strip_edges()
	if token in ["PLAYER_HURT", "PLAYER_SHIELD_HIT"]:
		prepared["presentation_target"] = _player
	elif _combat_actors_by_ref.has(target_ref):
		prepared["presentation_target"] = _combat_actors_by_ref[target_ref]
	var result: Dictionary = combat_feedback.present_confirmed_event(prepared)
	if result.get("status") != "PASS":
		return result
	if token in ["PLAYER_HURT", "PLAYER_SHIELD_HIT"]:
		player_combat_vitals.present_semantic_feedback(token)
	elif _enemy_bars_by_ref.has(target_ref):
		var bar: AndromedaEnemyCombatBar = _enemy_bars_by_ref[target_ref]
		bar.present_semantic_feedback(token)
	result["snapshot_projection_changed"] = false
	result["target_selection_changed"] = false
	return result


func set_reduced_motion(enabled: bool) -> Dictionary:
	return combat_feedback.set_reduced_motion(enabled)


func enemy_bar_for_ref(target_ref: String) -> AndromedaEnemyCombatBar:
	var value: Variant = _enemy_bars_by_ref.get(target_ref)
	return value as AndromedaEnemyCombatBar


func registered_combat_actor_count() -> int:
	return _combat_actors_by_ref.size()


func enemy_bar_count() -> int:
	return _enemy_bars_by_ref.size()


func rebind_external_combat_actors(combat_actors: Array[Node3D]) -> Dictionary:
	if _camera == null:
		return _rejected("COMBAT_CAMERA_NOT_BOUND")
	_register_combat_actors(combat_actors)
	return {
		"status": "PASS",
		"combat_actor_count": _combat_actors_by_ref.size(),
		"enemy_bar_count": _enemy_bars_by_ref.size(),
		"combat_identity_decided_locally": false,
		"authority": AUTHORITY,
	}


func request_weapon_slot(slot: int, source: String, submit_authority: bool = true) -> Dictionary:
	var projection: Dictionary = weapon_quick_slots.project_active_slot(slot, source)
	if projection.get("status") != "PASS":
		return projection
	var envelope_result: Dictionary = _build_presentation_intent("ACTIVATE_WEAPON_SLOT", {
		"slot": slot,
	})
	var transport_result: Dictionary = {}
	if submit_authority:
		transport_result = _submit_built_intent_if_authority_ready(envelope_result)
	_last_weapon_intent = {
		"status": "PASS",
		"intent": "WEAPON_QUICK_SLOT_ACTIVATE",
		"slot": slot,
		"projection": projection,
		"intent_envelope": envelope_result,
		"transport_submitted": transport_result.get("status") == "PASS",
		"transport_result": transport_result,
		"authoritative_main_hand_changed": false,
		"authority": AUTHORITY,
	}
	weapon_intent_projected.emit(_last_weapon_intent.duplicate(true))
	return _last_weapon_intent.duplicate(true)


func request_weapon_cycle(delta: int, source: String) -> Dictionary:
	if delta == 0:
		return _rejected("ZERO_WEAPON_CYCLE_DELTA")
	var target_slot: int = 2 if weapon_quick_slots.active_slot() == 1 else 1
	var result: Dictionary = request_weapon_slot(target_slot, source, false)
	var cycle_envelope: Dictionary = _build_presentation_intent("CYCLE_WEAPON_SLOT", {
		"direction": delta,
	})
	var transport_result: Dictionary = _submit_built_intent_if_authority_ready(cycle_envelope)
	result["intent"] = "WEAPON_QUICK_SLOT_CYCLE"
	result["slot_delta"] = delta
	result["intent_envelope"] = cycle_envelope
	result["transport_submitted"] = transport_result.get("status") == "PASS"
	result["transport_result"] = transport_result
	_last_weapon_intent = result.duplicate(true)
	return result


func active_weapon_slot() -> int:
	return weapon_quick_slots.active_slot()


func last_weapon_intent() -> Dictionary:
	return _last_weapon_intent.duplicate(true)


func set_inventory_open(value: bool) -> Dictionary:
	if value:
		_close_modal_views()
		_active_modal = "INVENTORY"
		inventory_shell.set_open(true)
	else:
		inventory_shell.set_open(false)
		if _active_modal == "INVENTORY":
			_active_modal = ""
	if value:
		_context_action.visible = false
	inventory_state_changed.emit(value)
	modal_state_changed.emit("INVENTORY", value)
	return {
		"status": "PASS",
		"open": value,
		"permanent_panel": false,
		"authority": AUTHORITY,
	}


func is_inventory_open() -> bool:
	return inventory_shell.is_open()


func consume_menu_scroll(direction: int) -> Dictionary:
	match _active_modal:
		"INVENTORY":
			return inventory_shell.scroll_by(direction)
		"VENDOR":
			return vendor_panel.scroll_by(direction)
		"QUEST":
			return quest_panel.scroll_by(direction)
		"CRAFTING":
			return crafting_panel.scroll_by(direction)
	return _rejected("NO_ACTIVE_MODAL_FOR_SCROLL")


func open_vendor(target_ref: String, vendor_ref: String) -> Dictionary:
	_close_modal_views()
	_active_modal = "VENDOR"
	_context_action.visible = false
	var result: Dictionary = vendor_panel.open_for_vendor(target_ref, vendor_ref)
	if result.get("status") != "PASS":
		_active_modal = ""
		return result
	modal_state_changed.emit("VENDOR", true)
	return result


func project_vendor_stock(vendor_ref: String, items: Array[Dictionary]) -> Dictionary:
	if not vendor_panel.is_open() or vendor_ref != vendor_panel.active_vendor_ref():
		return {
			"status": "PASS",
			"deferred_until_vendor_open": true,
			"item_count": items.size(),
			"authority": AUTHORITY,
		}
	return vendor_panel.project_stock(items, true)


func project_vendor_quote(quote: Dictionary) -> Dictionary:
	return vendor_panel.project_quote(quote, true)


func project_vendor_trade_result(result: Dictionary) -> Dictionary:
	return vendor_panel.project_trade_result(result, true)


func open_quest_offer(offer: Dictionary) -> Dictionary:
	_close_modal_views()
	_active_modal = "QUEST"
	_context_action.visible = false
	var result: Dictionary = quest_panel.project_offer(offer, true)
	if result.get("status") != "PASS":
		_active_modal = ""
		return result
	modal_state_changed.emit("QUEST", true)
	return result


func open_quest_state(projection: Dictionary) -> Dictionary:
	_close_modal_views()
	_active_modal = "QUEST"
	_context_action.visible = false
	var result: Dictionary = quest_panel.project_quest_state(projection, true)
	if result.get("status") != "PASS":
		_active_modal = ""
		return result
	modal_state_changed.emit("QUEST", true)
	return result


func project_quest_state(projection: Dictionary) -> Dictionary:
	return quest_panel.project_quest_state(projection, true)


func open_crafting(workstation_ref: String) -> Dictionary:
	_close_modal_views()
	_active_modal = "CRAFTING"
	_context_action.visible = false
	var result: Dictionary = crafting_panel.open_for_workstation(workstation_ref)
	if result.get("status") != "PASS":
		_active_modal = ""
		return result
	modal_state_changed.emit("CRAFTING", true)
	return result


func project_crafting_recipe(projection: Dictionary) -> Dictionary:
	return crafting_panel.project_recipe(projection, true)


func present_quest_event(event: Dictionary) -> Dictionary:
	var ui_result: Dictionary = quest_panel.present_external_event(event, true)
	if ui_result.get("status") != "PASS":
		return ui_result
	_quest_feedbacks.append({
		"event_ref": str(event.get("event_ref", "")),
		"text": str(event.get("feedback_text", "Atualização de quest")),
	})
	while _quest_feedbacks.size() > 3:
		_quest_feedbacks.pop_front()
	_render_quest_feedbacks()
	ui_result["feedback_priority"] = 60
	ui_result["simultaneous_feedback_count"] = _quest_feedbacks.size()
	ui_result["max_simultaneous_feedback"] = 3
	return ui_result


func project_inventory_state(projection: Dictionary) -> Dictionary:
	var result: Dictionary = inventory_shell.project_external_state(projection, true)
	var loadout: Dictionary = projection.get("weapon_loadout", {})
	var active_slot: int = int(loadout.get("active_slot", 0))
	if result.get("status") == "PASS" and active_slot in [1, 2]:
		result["weapon_projection"] = weapon_quick_slots.project_active_slot(
			active_slot,
			"EXTERNAL_B09_INVENTORY_SNAPSHOT"
		)
	return result


func active_modal() -> String:
	return _active_modal


func is_vendor_open() -> bool:
	return vendor_panel.is_open()


func is_quest_open() -> bool:
	return quest_panel.is_open()


func is_crafting_open() -> bool:
	return crafting_panel.is_open()


func last_crafting_intent() -> Dictionary:
	return _last_crafting_intent.duplicate(true)


func is_any_modal_open() -> bool:
	return not _active_modal.is_empty()


func close_active_modal() -> Dictionary:
	var previous: String = _active_modal
	_close_modal_views()
	_active_modal = ""
	if previous == "INVENTORY":
		inventory_state_changed.emit(false)
	if not previous.is_empty():
		modal_state_changed.emit(previous, false)
	return {
		"status": "PASS",
		"closed_layer": previous,
		"gameplay_state_changed": false,
		"authority": AUTHORITY,
	}


func quest_feedback_count() -> int:
	return _quest_feedbacks.size()


func set_auto_pickup_projection(enabled: bool, changed: bool = false) -> Dictionary:
	var projection: Dictionary = inventory_shell.set_auto_pickup_visual(enabled, false)
	if changed:
		_show_auto_pickup_status(enabled)
	return projection


func present_b10_client_pending(state: String, detail: String) -> Dictionary:
	return death_recovery_overlay.present_client_pending(state, detail)


func project_b10_external_state(state: String, detail: String, important: bool = false) -> Dictionary:
	return death_recovery_overlay.project_external_state(state, detail, important)


func hide_b10_presentation() -> Dictionary:
	return death_recovery_overlay.hide_presentation()


func present_dialogue_line(speaker: Node3D, payload: Dictionary) -> Dictionary:
	if speaker == null or _camera == null:
		return _rejected("SPEAKER_AND_CAMERA_REQUIRED")
	var line_ref: String = str(payload.get("line_ref", "")).strip_edges()
	var speaker_ref: String = str(payload.get("speaker_ref", speaker.get("target_ref"))).strip_edges()
	var conversation_ref: String = str(payload.get("conversation_ref", "")).strip_edges()
	if conversation_ref.is_empty():
		conversation_ref = "STANDALONE:%s" % line_ref
	var turn_index: int = int(payload.get("turn_index", 0))
	if _conversation_last_turn.has(conversation_ref):
		var last_turn: int = int(_conversation_last_turn[conversation_ref])
		if turn_index < last_turn:
			return _rejected("STALE_DIALOGUE_TURN")
	var bubble_index: int = _bubble_index_for_conversation(conversation_ref)
	var bubble: AndromedaDialogueBubble = _dialogue_bubbles[bubble_index]
	var anchor: Node3D = speaker.get_node_or_null("DialogueAnchor") as Node3D
	if anchor == null:
		anchor = speaker
	var normalized_payload: Dictionary = payload.duplicate(true)
	normalized_payload["speaker_ref"] = speaker_ref
	normalized_payload["npc_ref"] = str(speaker.get("target_ref"))
	normalized_payload["conversation_ref"] = conversation_ref
	normalized_payload["turn_index"] = turn_index
	var projected: Dictionary = bubble.project_line(anchor, _camera, normalized_payload)
	if projected.get("status") != "PASS":
		return projected
	_conversation_last_turn[conversation_ref] = turn_index
	_dialogue_serial += 1
	_bubble_last_used_serial[bubble_index] = _dialogue_serial
	if bool(normalized_payload.get("important", false)):
		_show_important_dialogue_line(
			str(normalized_payload.get("text", "")),
			float(projected.get("duration_seconds", TEMPORARY_FEEDBACK_S))
		)
	dialogue_line_projected.emit(projected.duplicate(true))
	return projected


func present_dialogue_line_for_ref(speaker_ref: String, payload: Dictionary) -> Dictionary:
	var actor_value: Variant = _dialogue_actors_by_ref.get(speaker_ref)
	if not actor_value is Node3D:
		return _rejected("DIALOGUE_SPEAKER_NOT_FOUND")
	return present_dialogue_line(actor_value as Node3D, payload)


func present_choices(speaker: Node3D, choices: Array, distance_m: float) -> Dictionary:
	if distance_m > CHOICE_RANGE_M_CANDIDATE:
		return {
			"status": "REJECTED",
			"reason": "OUT_OF_CHOICE_RANGE",
			"distance_m": distance_m,
			"authority": AUTHORITY,
		}
	var speaker_ref: String = str(speaker.get("target_ref")).strip_edges()
	for bubble: AndromedaDialogueBubble in _dialogue_bubbles:
		if bubble.is_line_active() and bubble.current_speaker_ref() == speaker_ref:
			return bubble.project_choices(choices)
	return _rejected("ACTIVE_SPEAKER_BUBBLE_NOT_FOUND")


func active_dialogue_count() -> int:
	var count: int = 0
	for bubble: AndromedaDialogueBubble in _dialogue_bubbles:
		if bubble.is_line_active():
			count += 1
	return count


func dialogue_pool_capacity() -> int:
	return _dialogue_bubbles.size()


func active_speaker_for_conversation(conversation_ref: String) -> String:
	if not _conversation_bubble_index.has(conversation_ref):
		return ""
	var index: int = int(_conversation_bubble_index[conversation_ref])
	return _dialogue_bubbles[index].current_speaker_ref()


func choices_visible_for_speaker(speaker_ref: String) -> bool:
	for bubble: AndromedaDialogueBubble in _dialogue_bubbles:
		if bubble.current_speaker_ref() == speaker_ref and bubble.choices_visible():
			return true
	return false


func important_dialogue_line_visible() -> bool:
	return _important_dialogue_line.visible


func important_dialogue_line_text() -> String:
	return _important_dialogue_label.text


func important_dialogue_line_color() -> Color:
	return _important_dialogue_label.get_theme_color("font_color")


func context_action_visible() -> bool:
	return _context_action.visible


func context_action_text() -> String:
	return _context_action_label.text


func selection_feedback_visible() -> bool:
	return _selection_feedback.visible


func last_choice_intent() -> Dictionary:
	return _last_choice_intent.duplicate(true)


func last_auto_pickup_intent() -> Dictionary:
	return _last_auto_pickup_intent.duplicate(true)


func apply_presentation_snapshot(snapshot: Dictionary) -> Dictionary:
	var channels: Array[String] = []
	var stamina_value: Variant = snapshot.get("stamina", {})
	if stamina_value is Dictionary:
		var stamina: Dictionary = stamina_value
		if stamina.has("fraction"):
			project_stamina(
				float(stamina.get("fraction", 1.0)),
				str(stamina.get("activity", AndromedaStaminaWorldRing.ACTIVITY_INACTIVE)),
				"AUTHORITATIVE_SNAPSHOT"
			)
			channels.append("STAMINA")
	var loadout_value: Variant = snapshot.get("weapon_loadout", {})
	if loadout_value is Dictionary:
		var loadout: Dictionary = loadout_value
		var active_slot: int = int(loadout.get("active_slot", 0))
		if active_slot in [1, 2]:
			weapon_quick_slots.project_active_slot(active_slot, "AUTHORITATIVE_SNAPSHOT")
			channels.append("WEAPON_LOADOUT")
	var preferences_value: Variant = snapshot.get("profile_preferences", {})
	if preferences_value is Dictionary:
		var preferences: Dictionary = preferences_value
		if preferences.has("auto_pickup"):
			set_auto_pickup_projection(bool(preferences.get("auto_pickup", false)), false)
			channels.append("AUTO_PICKUP")
	var combat_value: Variant = snapshot.get("combat_presentation", {})
	if combat_value is Dictionary:
		var combat: Dictionary = combat_value
		var player_value: Variant = combat.get("player", {})
		if player_value is Dictionary:
			var player_snapshot: Dictionary = player_value
			if player_snapshot.has("hp_fraction") and player_snapshot.has("protection_fraction"):
				var player_result: Dictionary = project_player_combat_vitals(
					float(player_snapshot.get("hp_fraction", 1.0)),
					float(player_snapshot.get("protection_fraction", 0.0)),
					bool(player_snapshot.get("relevant", false)),
					"AUTHORITATIVE_SNAPSHOT"
				)
				if player_result.get("status") == "PASS":
					channels.append("PLAYER_COMBAT_VITALS")
		var targets_value: Variant = combat.get("targets", [])
		if targets_value is Array:
			for target_value: Variant in targets_value:
				if not target_value is Dictionary:
					continue
				var target_snapshot: Dictionary = target_value
				var target_result: Dictionary = project_enemy_combat_vitals(
					str(target_snapshot.get("target_ref", "")),
					float(target_snapshot.get("hp_fraction", 1.0)),
					float(target_snapshot.get("shield_fraction", 0.0)),
					bool(target_snapshot.get("engaged", false)),
					"AUTHORITATIVE_SNAPSHOT"
				)
				if target_result.get("status") == "PASS":
					channels.append("ENEMY_COMBAT_VITALS:%s" % str(target_snapshot.get("target_ref", "")))
	return {
		"status": "PASS",
		"projected_channels": channels,
		"snapshot_mutated": false,
		"authority": AUTHORITY,
	}


func contract_snapshot() -> Dictionary:
	return {
		"philosophy": "MINIMAL_CONTEXTUAL_WORLD_FIRST",
		"ui_family": "WHITE_OFF_WHITE_ROUNDED_CLEAN_CONSOLE",
		"primary_text_hex": "#6B6B6B",
		"secondary_text_hex": "#8A8A8A",
		"important_text_hex": "#D9A15F",
		"dialogue_pool_capacity": DIALOGUE_POOL_CAPACITY,
		"permanent_large_panels": false,
		"inventory_toggled": true,
		"stamina": stamina_ring.contract_snapshot(),
		"weapon_quickslots": weapon_quick_slots.contract_snapshot(),
		"inventory": inventory_shell.contract_snapshot(),
		"vendor": vendor_panel.contract_snapshot(),
		"quest": quest_panel.contract_snapshot(),
		"crafting": crafting_panel.contract_snapshot(),
		"death_recovery_overlay": death_recovery_overlay.contract_snapshot(),
		"modal_layers": ["INVENTORY", "VENDOR", "QUEST", "CRAFTING"],
		"modal_world_input_consumed": true,
		"modal_scene_tree_paused": false,
		"quest_feedback_priority": 60,
		"max_simultaneous_quest_feedback": 3,
		"player_combat_vitals": player_combat_vitals.contract_snapshot(),
		"enemy_combat_bar_count": _enemy_bars_by_ref.size(),
		"combat_feedback": combat_feedback.contract_snapshot(),
		"next_button": false,
		"final_art": false,
		"backend_substitute": false,
		"command_transport_submitted": false,
		"combat_outcome_calculated": false,
		"combat_snapshot_mutated": false,
		"crafting_result_calculated": false,
		"crafting_inventory_mutated": false,
		"gameplay_authority_in_gdscript": false,
		"authority": AUTHORITY,
	}


func _register_combat_actors(combat_actors: Array[Node3D]) -> void:
	_combat_actors_by_ref.clear()
	_enemy_bars_by_ref.clear()
	for child: Node in _enemy_combat_bar_layer.get_children():
		child.queue_free()
	for actor: Node3D in combat_actors:
		if actor == null:
			continue
		var target_ref: String = str(actor.get("target_ref")).strip_edges()
		if target_ref.is_empty() or _combat_actors_by_ref.has(target_ref):
			continue
		_combat_actors_by_ref[target_ref] = actor
		var bar := ENEMY_COMBAT_BAR_SCENE.instantiate() as AndromedaEnemyCombatBar
		if bar == null:
			continue
		bar.name = "EnemyBar_%s" % target_ref.replace("-", "_")
		_enemy_combat_bar_layer.add_child(bar)
		var alpha_rank: bool = str(actor.get_meta("combat_rank", "COMMON")).to_upper() == "ALPHA"
		var bind_result: Dictionary = bar.bind_projection(actor, _camera, target_ref, alpha_rank)
		if bind_result.get("status") == "PASS":
			_enemy_bars_by_ref[target_ref] = bar


func _bubble_index_for_conversation(conversation_ref: String) -> int:
	if _conversation_bubble_index.has(conversation_ref):
		return int(_conversation_bubble_index[conversation_ref])
	for index: int in range(_dialogue_bubbles.size()):
		if not _dialogue_bubbles[index].is_line_active():
			_conversation_bubble_index[conversation_ref] = index
			return index
	var oldest_index: int = 0
	var oldest_serial: int = _bubble_last_used_serial[0]
	for index: int in range(1, _bubble_last_used_serial.size()):
		if _bubble_last_used_serial[index] < oldest_serial:
			oldest_index = index
			oldest_serial = _bubble_last_used_serial[index]
	var displaced_conversation: String = _dialogue_bubbles[oldest_index].current_conversation_ref()
	if not displaced_conversation.is_empty():
		_conversation_bubble_index.erase(displaced_conversation)
	_dialogue_bubbles[oldest_index].hide_presentation()
	_conversation_bubble_index[conversation_ref] = oldest_index
	return oldest_index


func _on_hover_resolution_changed(result: Dictionary) -> void:
	if str(result.get("intent", "")) != "HOVER_TARGET":
		_context_action.visible = false
		return
	var cursor: String = str(result.get("cursor", "DEFAULT")).to_upper()
	var action_text: String = {
		"TALK": "Falar",
		"ATTACK": "Atacar",
		"PICKUP": "Coletar",
		"HARVEST": "Executar ação",
		"RECOVER": "Recuperar bolsa",
		"INTERACT": "Interagir",
		"BLOCKED": "Ação bloqueada",
	}.get(cursor, "Interagir")
	_context_action_label.text = action_text
	_context_action.visible = not is_any_modal_open()


func _on_target_selection_changed(target_ref: String, target_kind: String) -> void:
	if target_ref.is_empty():
		_selection_feedback.visible = false
		return
	_selection_feedback_label.text = "Alvo selecionado  ·  %s" % target_kind.capitalize()
	_selection_feedback.visible = true
	_selection_feedback_remaining_s = TEMPORARY_FEEDBACK_S


func _on_choice_intent_requested(npc_ref: String, choice_ref: String) -> void:
	var envelope_result: Dictionary = _build_presentation_intent("DIALOGUE_CHOICE", {
		"npc_ref": npc_ref,
		"choice_ref": choice_ref,
		"client_presentation_only": true,
	})
	_last_choice_intent = {
		"status": "PASS",
		"intent": "DIALOGUE_CHOICE",
		"npc_ref": npc_ref,
		"choice_ref": choice_ref,
		"intent_envelope": envelope_result,
		"transport_submitted": false,
		"narrative_authority_changed": false,
		"authority": AUTHORITY,
	}
	dialogue_choice_projected.emit(_last_choice_intent.duplicate(true))


func _on_auto_pickup_visual_changed(enabled: bool) -> void:
	_show_auto_pickup_status(enabled)
	var envelope_result: Dictionary = _build_presentation_intent("SET_AUTO_PICKUP", {
		"enabled": enabled,
	})
	var transport_result: Dictionary = _submit_built_intent_if_authority_ready(envelope_result)
	_last_auto_pickup_intent = {
		"status": "PASS",
		"enabled": enabled,
		"intent_envelope": envelope_result,
		"transport_submitted": transport_result.get("status") == "PASS",
		"transport_result": transport_result,
		"remote_collection_enabled": false,
		"persisted_by_gdscript": false,
		"authority": AUTHORITY,
	}


func _on_snapshot_applied(snapshot: Dictionary) -> void:
	apply_presentation_snapshot(snapshot)


func _show_important_dialogue_line(text_value: String, duration_s: float) -> void:
	_important_dialogue_label.text = text_value
	_important_dialogue_label.add_theme_color_override("font_color", Color("d9a15f"))
	_important_dialogue_line.visible = true
	_important_line_remaining_s = clampf(duration_s, 1.8, 8.0)


func _show_auto_pickup_status(enabled: bool) -> void:
	_auto_pickup_label.text = "AUTO PICKUP  ON" if enabled else "AUTO PICKUP  OFF"
	_auto_pickup_label.add_theme_color_override(
		"font_color",
		Color("d9a15f") if enabled else Color("6b6b6b")
	)
	_auto_pickup_status.visible = true
	_auto_pickup_remaining_s = 2.0


func _build_presentation_intent(command: String, params: Dictionary) -> Dictionary:
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	return bridge.build_command_envelope(command, params)


func _submit_built_intent_if_authority_ready(built: Dictionary) -> Dictionary:
	if built.get("status") != "PASS":
		return _rejected(str(built.get("reason", "INTENT_ENVELOPE_REJECTED")))
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	if bridge.connection_state().get("authority_session_bound") != true:
		return _rejected("AUTHORITY_SESSION_NOT_BOUND")
	var envelope: Dictionary = built.get("envelope", {})
	return bridge.submit_command(
		str(envelope.get("command", "")),
		envelope.get("params", {}),
		str(envelope.get("command_ref", ""))
	)


func _on_crafting_intent_requested(
	workstation_ref: String,
	recipe_ref: String,
	quantity: int
) -> void:
	var envelope_result: Dictionary = _build_presentation_intent("REQUEST_CRAFT", {
		"workstation_ref": workstation_ref,
		"recipe_ref": recipe_ref,
		"quantity": quantity,
		"client_presentation_only": true,
	})
	_last_crafting_intent = {
		"status": "PASS" if envelope_result.get("status") == "PASS" else "REJECTED",
		"intent": "REQUEST_CRAFT",
		"workstation_ref": workstation_ref,
		"recipe_ref": recipe_ref,
		"quantity": quantity,
		"intent_envelope": envelope_result,
		"transport_submitted": false,
		"craft_result_decided_locally": false,
		"inventory_mutated_locally": false,
		"authority": AUTHORITY,
	}
	crafting_intent_projected.emit(_last_crafting_intent.duplicate(true))


func _on_crafting_close_requested() -> void:
	close_active_modal()


func _close_modal_views() -> void:
	inventory_shell.set_open(false)
	vendor_panel.set_open(false)
	quest_panel.set_open(false)
	crafting_panel.set_open(false)


func _render_quest_feedbacks() -> void:
	for child: Node in _quest_feedback_stack.get_children():
		child.queue_free()
	for feedback: Dictionary in _quest_feedbacks:
		var label := Label.new()
		label.text = str(feedback.get("text", "Atualização de quest"))
		label.add_theme_color_override("font_color", Color("d9a15f"))
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
		_quest_feedback_stack.add_child(label)


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
