extends Node

var _checks: int = 0
var _failures: Array[String] = []

@onready var main: AndromedaMainRuntime = $AndromedaARPG
@onready var player: AndromedaPlayerController = $AndromedaARPG/ActorRoot/Player
@onready var camera_rig: AndromedaIsometricCameraRig = $AndromedaARPG/IsometricCameraRig
@onready var hud: AndromedaHUDController = $AndromedaARPG/UILayer/MinimalHUD
@onready var npc_primary: AndromedaInteractionTarget = $AndromedaARPG/ActorRoot/NPCB03
@onready var npc_peer: AndromedaInteractionTarget = $AndromedaARPG/ActorRoot/NPCB05DialoguePeer
@onready var enemy: AndromedaInteractionTarget = $AndromedaARPG/ActorRoot/EnemyB03


func _ready() -> void:
	await _run_gate()


func _check(check_id: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(check_id if detail.is_empty() else "%s:%s" % [check_id, detail])


func _run_gate() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	var router := get_node_or_null("/root/InputRouter") as AndromedaInputRouter
	_check("AUTOLOAD_CLIENT_SESSION", session != null)
	_check("AUTOLOAD_ANDROMEDA_BRIDGE", bridge != null)
	_check("AUTOLOAD_INPUT_ROUTER", router != null)
	if session == null or bridge == null or router == null:
		await _finish()
		return
	var bind_result: Dictionary = session.bind_session("B05-GATE-SESSION")
	_check("SESSION_BOUND_FOR_ENVELOPES_ONLY", bind_result.get("status") == "PASS", JSON.stringify(bind_result))
	_check("EXISTING_BACKEND_URL_UNCHANGED", bridge.server_url() == "http://127.0.0.1:8000")
	var project_label: String = str(ProjectSettings.get_setting("application/config/name"))
	_check("PROJECT_LABEL_B05_THROUGH_B11", project_label in ["Andromeda ARPG Stage16B B05", "Andromeda ARPG Stage16B B06", "Andromeda ARPG Stage16B B07", "Andromeda ARPG Stage16B B08", "Andromeda ARPG Stage16B B09", "Andromeda ARPG Stage16B B10", "Andromeda ARPG Stage16B B11"], project_label)
	_check("MAIN_SCENE_UNCHANGED", str(ProjectSettings.get_setting("application/run/main_scene")) == "res://scenes/Main.tscn")
	_check("NO_BACKEND_SUBSTITUTE", main.contract_snapshot().get("backend_substitute") == false)
	_check("NO_GDSCRIPT_GAMEPLAY_AUTHORITY", main.contract_snapshot().get("gameplay_authority_in_gdscript") == false)
	_check("NO_HUD_GAMEPLAY_AUTHORITY", main.contract_snapshot().get("hud_gameplay_authority_in_gdscript") == false)
	_check("NO_WEAPON_TRANSPORT_SUBMISSION", main.contract_snapshot().get("weapon_command_transport_submitted_in_b05") == false)
	_check("NO_DIALOGUE_AUTHORING", main.contract_snapshot().get("dialogue_narrative_authored_in_gdscript") == false)
	_check("INPUT_ACTION_SLOT1", InputMap.has_action("weapon_slot_1"))
	_check("INPUT_ACTION_SLOT2", InputMap.has_action("weapon_slot_2"))
	_check("INPUT_ACTION_INVENTORY", InputMap.has_action("inventory_toggle"))
	await _wait_process_frames(4)
	_test_ui_architecture()
	await _test_stamina_ring()
	await _test_weapon_inputs(router)
	_test_hover_context_and_selection()
	await _test_dialogue_foundation()
	await _test_inventory_and_auto_pickup()
	_test_snapshot_projection()
	await _test_camera_and_click_to_move_stability()
	_restore_gate_state()
	await _finish()


func _test_ui_architecture() -> void:
	var contract: Dictionary = hud.contract_snapshot()
	_check("HUD_ROOT_PRESENT", main.hud == hud)
	_check("HUD_IS_CONTROL", hud is Control)
	_check("HUD_MOUSE_FILTER_IGNORE", hud.mouse_filter == Control.MOUSE_FILTER_IGNORE)
	_check("HUD_WORLD_FIRST_PHILOSOPHY", contract.get("philosophy") == "MINIMAL_CONTEXTUAL_WORLD_FIRST", JSON.stringify(contract))
	_check("HUD_NO_PERMANENT_LARGE_PANEL", contract.get("permanent_large_panels") == false)
	_check("HUD_NO_FINAL_ART", contract.get("final_art") == false)
	_check("HUD_BACKEND_SUBSTITUTE_FALSE", contract.get("backend_substitute") == false)
	_check("HUD_TRANSPORT_SUBMITTED_FALSE", contract.get("command_transport_submitted") == false)
	_check("HUD_THEME_PRESENT", hud.theme != null)
	var panel_style := hud.theme.get_stylebox("panel", "PanelContainer") as StyleBoxFlat
	_check("HUD_PANEL_STYLE_FLAT", panel_style != null)
	if panel_style != null:
		_check("HUD_PANEL_OFF_WHITE", panel_style.bg_color.r > 0.97 and panel_style.bg_color.g > 0.96, str(panel_style.bg_color))
		_check("HUD_PANEL_CORNER_14", panel_style.corner_radius_top_left == 14 and panel_style.corner_radius_bottom_right == 14)
		_check("HUD_SHADOW_SUBTLE", panel_style.shadow_size <= 6 and panel_style.shadow_color.a < 0.25)
	var default_font: Font = hud.theme.default_font
	_check("HUD_ROUNDED_SYSTEM_FONT_DIRECTION", default_font is SystemFont)
	if default_font is SystemFont:
		var system_font := default_font as SystemFont
		_check("HUD_FONT_HAS_ROUNDED_CANDIDATE", system_font.font_names.has("Nunito") or system_font.font_names.has("Segoe UI Rounded"), str(system_font.font_names))
	_check("HUD_PRIMARY_TEXT_HEX", contract.get("primary_text_hex") == "#6B6B6B")
	_check("HUD_SECONDARY_TEXT_HEX", contract.get("secondary_text_hex") == "#8A8A8A")
	_check("HUD_IMPORTANT_TEXT_HEX", contract.get("important_text_hex") == "#D9A15F")
	_check("STAMINA_RING_NODE_PRESENT", hud.has_node("WorldUIRoot/StaminaWorldRing"))
	_check("DIALOGUE_POOL_NODE_PRESENT", hud.has_node("WorldUIRoot/DialogueBubblePool"))
	_check("DIALOGUE_POOL_CAPACITY_THREE", hud.dialogue_pool_capacity() == 3)
	_check("INVENTORY_NODE_PRESENT", hud.has_node("InventoryPanel"))
	_check("CONTEXT_ACTION_NODE_PRESENT", hud.has_node("ContextAction"))
	_check("SELECTION_FEEDBACK_NODE_PRESENT", hud.has_node("SelectionFeedback"))
	_check("IMPORTANT_DIALOGUE_LINE_NODE_PRESENT", hud.has_node("ImportantDialogueLine"))
	_check("AUTO_PICKUP_STATUS_NODE_PRESENT", hud.has_node("AutoPickupStatus"))
	var slot_nodes: Array[Node] = get_tree().get_nodes_in_group("weapon_quick_slot")
	_check("EXACTLY_TWO_ACTIVE_QUICKSLOT_NODES", slot_nodes.size() == 2, str(slot_nodes.size()))
	_check("QUICKSLOT_CONTRACT_EXACTLY_TWO", hud.weapon_quick_slots.slot_count() == 2)
	_check("ONE_ACTIVE_SLOT_INITIAL", hud.weapon_quick_slots.active_slot() == 1)
	_check("INACTIVE_MODIFIERS_NOT_APPLIED_CLIENT", hud.weapon_quick_slots.contract_snapshot().get("inactive_modifiers_applied") == false)
	_check("NPC_PRIMARY_DIALOGUE_ANCHOR_REUSED", npc_primary.has_node("DialogueAnchor"))
	_check("NPC_PEER_DIALOGUE_ANCHOR_REUSED", npc_peer.has_node("DialogueAnchor"))
	_check("PLAYER_SCENE_NO_FIXED_STAMINA_BAR", not player.has_node("StaminaBar"))


func _test_stamina_ring() -> void:
	var ring: AndromedaStaminaWorldRing = hud.stamina_ring
	var full_inactive: Dictionary = hud.project_stamina(1.0, "INACTIVE", "LOCAL_GATE_PLACEHOLDER")
	await _wait_process_frames(2)
	_check("STAMINA_FULL_INACTIVE_PASS", full_inactive.get("status") == "PASS", JSON.stringify(full_inactive))
	_check("STAMINA_FULL_INACTIVE_HIDDEN", not ring.visible)
	_check("STAMINA_FULL_INACTIVE_PREDICATE", not ring.should_be_visible())
	var consuming: Dictionary = hud.project_stamina(0.68, "CONSUMING", "LOCAL_GATE_PLACEHOLDER")
	await _wait_process_frames(2)
	_check("STAMINA_CONSUMING_PASS", consuming.get("status") == "PASS", JSON.stringify(consuming))
	_check("STAMINA_CONSUMING_VISIBLE", ring.visible)
	_check("STAMINA_CONSUMING_FRACTION", is_equal_approx(ring.stamina_fraction(), 0.68))
	_check("STAMINA_CONSUMING_ACTIVITY", ring.activity_state() == "CONSUMING")
	_check("STAMINA_SOURCE_MARKED_PLACEHOLDER", ring.projection_source() == "LOCAL_GATE_PLACEHOLDER")
	var player_projection: Vector2 = camera_rig.camera.unproject_position(player.global_position + ring.player_offset_world)
	var ring_center: Vector2 = ring.position + ring.size * 0.5
	_check("STAMINA_PLAYER_ADJACENT_SCREEN_SPACE", ring_center.distance_to(player_projection + ring.screen_offset_px) < 1.0, "%s %s" % [ring_center, player_projection])
	var lower: Dictionary = hud.project_stamina(0.31, "CONSUMING", "LOCAL_GATE_PLACEHOLDER")
	_check("STAMINA_DEPLETION_PROJECTED", lower.get("status") == "PASS" and ring.stamina_fraction() < 0.68)
	var regenerating: Dictionary = hud.project_stamina(0.74, "REGENERATING", "LOCAL_GATE_PLACEHOLDER")
	_check("STAMINA_REGEN_PROJECTED", regenerating.get("status") == "PASS" and ring.stamina_fraction() > 0.31)
	_check("STAMINA_REGEN_VISIBLE", ring.visible)
	var full_regenerating: Dictionary = hud.project_stamina(1.0, "REGENERATING", "LOCAL_GATE_PLACEHOLDER")
	_check("STAMINA_FULL_REGEN_STILL_VISIBLE", full_regenerating.get("status") == "PASS" and ring.visible)
	hud.project_stamina(1.0, "INACTIVE", "LOCAL_GATE_PLACEHOLDER")
	_check("STAMINA_DISAPPEARS_AFTER_REGEN_IDLE", not ring.visible)
	hud.project_stamina(0.92, "CONSUMING", "LOCAL_GATE_PLACEHOLDER")
	_check("STAMINA_REAPPEARS_AFTER_NEW_CONSUMPTION", ring.visible)
	var ring_contract: Dictionary = ring.contract_snapshot()
	_check("STAMINA_SHAPE_CIRCLE_RADIAL", ring_contract.get("shape") == "CIRCLE_RADIAL")
	_check("STAMINA_COLOR_SOFT_YELLOW", ring_contract.get("color") == "SOFT_YELLOW")
	_check("STAMINA_NO_PERMANENT_NUMBERS", ring_contract.get("permanent_numbers") == false)
	_check("STAMINA_NO_HORIZONTAL_BAR", ring_contract.get("horizontal_bar") == false)
	_check("STAMINA_AUTHORITY_EXTERNAL", ring_contract.get("gameplay_authority_in_gdscript") == false)
	var bad_activity: Dictionary = hud.project_stamina(0.5, "AUTHORED_DRAIN", "LOCAL_GATE_PLACEHOLDER")
	_check("STAMINA_UNKNOWN_ACTIVITY_REJECTED", bad_activity.get("status") == "REJECTED")


func _test_weapon_inputs(router: AndromedaInputRouter) -> void:
	var key_one: Dictionary = main.handle_action_event(_key_event(KEY_1))
	_check("KEY1_INPUT_PASS", key_one.get("status") == "PASS", JSON.stringify(key_one))
	_check("KEY1_INTENT", key_one.get("intent") == "WEAPON_QUICK_SLOT_ACTIVATE")
	_check("KEY1_ACTIVE_SLOT", hud.active_weapon_slot() == 1)
	_check("KEY1_EXACT_SLOT", int(key_one.get("slot", 0)) == 1)
	var key_one_projection: Dictionary = key_one.get("ui_projection", {})
	_check("KEY1_UI_PROJECTION_PASS", key_one_projection.get("status") == "PASS", JSON.stringify(key_one_projection))
	_check("KEY1_ENVELOPE_BUILT", key_one_projection.get("intent_envelope", {}).get("status") == "PASS", JSON.stringify(key_one_projection))
	_check("KEY1_TRANSPORT_NOT_SUBMITTED", key_one_projection.get("transport_submitted") == false)
	_check("KEY1_MAIN_HAND_NOT_MUTATED", key_one_projection.get("authoritative_main_hand_changed") == false)
	var key_two: Dictionary = main.handle_action_event(_key_event(KEY_2))
	_check("KEY2_INPUT_PASS", key_two.get("status") == "PASS", JSON.stringify(key_two))
	_check("KEY2_ACTIVE_SLOT", hud.active_weapon_slot() == 2)
	_check("KEY2_EXACT_SLOT", int(key_two.get("slot", 0)) == 2)
	_check("KEY2_ENVELOPE_BUILT", key_two.get("ui_projection", {}).get("intent_envelope", {}).get("status") == "PASS", JSON.stringify(key_two))
	var invalid_slot: Dictionary = router.resolve_weapon_slot_key(3)
	_check("KEY3_SLOT_REJECTED", invalid_slot.get("status") == "REJECTED")
	var zoom_before_wheel: float = camera_rig.target_distance_m()
	var wheel_cycle: Dictionary = main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_DOWN, false))
	_check("WHEEL_UNMODIFIED_PASS", wheel_cycle.get("status") == "PASS", JSON.stringify(wheel_cycle))
	_check("WHEEL_UNMODIFIED_CYCLES", wheel_cycle.get("intent") == "WEAPON_QUICK_SLOT_CYCLE")
	_check("WHEEL_UNMODIFIED_TOGGLES_TO_SLOT1", hud.active_weapon_slot() == 1)
	_check("WHEEL_UNMODIFIED_NO_ZOOM", is_equal_approx(camera_rig.target_distance_m(), zoom_before_wheel))
	_check("WHEEL_UNMODIFIED_TRANSPORT_NOT_SUBMITTED", wheel_cycle.get("transport_submitted") == false)
	var wheel_reverse: Dictionary = main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_UP, false))
	_check("WHEEL_REVERSE_PASS", wheel_reverse.get("status") == "PASS")
	_check("WHEEL_REVERSE_TOGGLES_TO_SLOT2", hud.active_weapon_slot() == 2)
	var slot_before_zoom: int = hud.active_weapon_slot()
	var zoom_before: float = camera_rig.target_distance_m()
	var zoom_result: Dictionary = main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_DOWN, true))
	_check("MODIFIER_WHEEL_PASS", zoom_result.get("status") == "PASS", JSON.stringify(zoom_result))
	_check("MODIFIER_WHEEL_ZOOM_INTENT", zoom_result.get("intent") == "CAMERA_ZOOM")
	_check("MODIFIER_WHEEL_CHANGES_ZOOM", camera_rig.target_distance_m() > zoom_before)
	_check("MODIFIER_WHEEL_DOES_NOT_SWAP", hud.active_weapon_slot() == slot_before_zoom)
	_check("MODIFIER_WHEEL_CONSUMES_WEAPON", zoom_result.get("consumes_weapon_cycle") == true)
	var open_result: Dictionary = main.handle_action_event(_key_event(KEY_I))
	_check("I_OPENS_INVENTORY", open_result.get("status") == "PASS" and main.menu_open() and hud.is_inventory_open(), JSON.stringify(open_result))
	await _wait_process_frames(4)
	var slot_before_menu_scroll: int = hud.active_weapon_slot()
	var zoom_before_menu_scroll: float = camera_rig.target_distance_m()
	var scroll_before: int = hud.inventory_shell.scroll_value()
	var menu_wheel: Dictionary = main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_DOWN, false))
	_check("MENU_WHEEL_PASS", menu_wheel.get("status") == "PASS", JSON.stringify(menu_wheel))
	_check("MENU_WHEEL_SCROLL_ONLY", menu_wheel.get("intent") == "MENU_SCROLL")
	_check("MENU_WHEEL_DOES_NOT_SWAP", hud.active_weapon_slot() == slot_before_menu_scroll)
	_check("MENU_WHEEL_DOES_NOT_ZOOM", is_equal_approx(camera_rig.target_distance_m(), zoom_before_menu_scroll))
	_check("MENU_WHEEL_SCROLL_PROJECTION_PASS", menu_wheel.get("ui_projection", {}).get("status") == "PASS", JSON.stringify(menu_wheel))
	_check("MENU_WHEEL_SCROLLS", hud.inventory_shell.scroll_value() > scroll_before, "%d -> %d" % [scroll_before, hud.inventory_shell.scroll_value()])
	var close_result: Dictionary = main.handle_action_event(_key_event(KEY_I))
	_check("I_CLOSES_INVENTORY", close_result.get("status") == "PASS" and not main.menu_open() and not hud.is_inventory_open())
	_check("QUICKSLOTS_FADE_DISCREET_CONTRACT", hud.weapon_quick_slots.contract_snapshot().get("idle_behavior") == "FADE_TO_DISCREET_AFTER_SWAP")
	_check("QUICKSLOT_AUTHORITY_EXTERNAL", hud.weapon_quick_slots.contract_snapshot().get("gameplay_authority_in_gdscript") == false)


func _test_hover_context_and_selection() -> void:
	var hover_name := npc_primary.get_node("HoverFeedback/HoverName") as Label3D
	_check("NPC_NAME_INITIAL_HIDDEN", not hover_name.visible)
	npc_primary.set_hovered(true)
	_check("NPC_NAME_VISIBLE_ON_HOVER", hover_name.visible)
	_check("NPC_NAME_PLACEHOLDER_MATCH", hover_name.text == npc_primary.display_name)
	npc_primary.set_hovered(false)
	_check("NPC_NAME_HIDDEN_AFTER_HOVER", not hover_name.visible)
	main.hover_resolution_changed.emit({"status": "PASS", "intent": "HOVER_TARGET", "cursor": "TALK"})
	_check("CONTEXT_TALK_VISIBLE", hud.context_action_visible())
	_check("CONTEXT_TALK_LABEL", hud.context_action_text() == "Falar")
	main.hover_resolution_changed.emit({"status": "PASS", "intent": "HOVER_TARGET", "cursor": "ATTACK"})
	_check("CONTEXT_ATTACK_LABEL", hud.context_action_text() == "Atacar")
	main.hover_resolution_changed.emit({"status": "PASS", "intent": "HOVER_TARGET", "cursor": "HARVEST"})
	_check("CONTEXT_RESOURCE_LABEL", hud.context_action_text() == "Executar ação")
	main.hover_resolution_changed.emit({"status": "PASS", "intent": "HOVER_TARGET", "cursor": "PICKUP"})
	_check("CONTEXT_LOOT_LABEL", hud.context_action_text() == "Coletar")
	main.hover_resolution_changed.emit({"status": "PASS", "intent": "HOVER_CLEAR", "cursor": "DEFAULT"})
	_check("CONTEXT_CLEARS", not hud.context_action_visible())
	main.target_selection_changed.emit(enemy.target_ref, enemy.target_kind)
	_check("SELECTION_FEEDBACK_VISIBLE", hud.selection_feedback_visible())
	_check("SELECTION_INDICATOR_EXISTING_B03", enemy.has_node("HoverFeedback/SelectionIndicator"))


func _test_dialogue_foundation() -> void:
	var primary_original_position: Vector3 = npc_primary.global_position
	var peer_original_position: Vector3 = npc_peer.global_position
	npc_primary.global_position = Vector3(-3.0, 0.0, 2.0)
	npc_peer.global_position = Vector3(-1.0, 0.0, 3.0)
	await _wait_physics_frames(2)
	var normal_payload := {
		"line_ref": "B05-LINE-NORMAL-001",
		"speaker_ref": npc_primary.target_ref,
		"text": "O caminho continua aberto enquanto conversamos.",
		"conversation_ref": "B05-CONVERSATION-PAIR",
		"turn_index": 1,
		"important": false,
		"duration_seconds": 6.0,
	}
	var normal_result: Dictionary = hud.present_dialogue_line(npc_primary, normal_payload)
	_check("DIALOGUE_NORMAL_PASS", normal_result.get("status") == "PASS", JSON.stringify(normal_result))
	_check("DIALOGUE_REALTIME_AUTO_ADVANCE", normal_result.get("auto_advance") == true)
	_check("DIALOGUE_NO_NEXT", normal_result.get("next_button") == false)
	_check("DIALOGUE_NO_WORLD_PAUSE", normal_result.get("world_pause") == false and not get_tree().paused)
	_check("DIALOGUE_NO_MOVEMENT_LOCK", normal_result.get("movement_lock") == false)
	_check("DIALOGUE_ONE_BUBBLE_ACTIVE", hud.active_dialogue_count() == 1, str(hud.active_dialogue_count()))
	var normal_bubble: AndromedaDialogueBubble = _active_bubble_for_speaker(npc_primary.target_ref)
	_check("DIALOGUE_NORMAL_BUBBLE_FOUND", normal_bubble != null)
	if normal_bubble != null:
		_check("DIALOGUE_NORMAL_TEXT_GRAY", _color_near(normal_bubble.text_color(), Color("6b6b6b")))
		_check("DIALOGUE_WHITE_ROUNDED_CONTRACT", normal_bubble.contract_snapshot().get("bubble_shape") == "ROUNDED_WHITE")
		_check("DIALOGUE_WORLD_ANCHORED", normal_bubble.anchor_screen_position().distance_to(normal_bubble.position + Vector2(normal_bubble.size.x * 0.5, normal_bubble.size.y)) < 260.0)
	_check("NORMAL_DIALOGUE_NO_BOTTOM_DUPLICATE", not hud.important_dialogue_line_visible())
	var important_text: String = "A corrente está forte; atravesse com cuidado."
	var important_payload := {
		"line_ref": "B05-LINE-IMPORTANT-002",
		"speaker_ref": npc_peer.target_ref,
		"text": important_text,
		"conversation_ref": "B05-CONVERSATION-PAIR",
		"turn_index": 2,
		"important": true,
		"duration_seconds": 6.0,
	}
	var important_result: Dictionary = hud.present_dialogue_line(npc_peer, important_payload)
	_check("DIALOGUE_IMPORTANT_PASS", important_result.get("status") == "PASS", JSON.stringify(important_result))
	_check("SAME_CONVERSATION_ALTERNATES_ONE_BUBBLE", hud.active_dialogue_count() == 1, str(hud.active_dialogue_count()))
	_check("CONVERSATION_SPEAKER_ALTERNATED", hud.active_speaker_for_conversation("B05-CONVERSATION-PAIR") == npc_peer.target_ref)
	var important_bubble: AndromedaDialogueBubble = _active_bubble_for_speaker(npc_peer.target_ref)
	_check("IMPORTANT_BUBBLE_FOUND", important_bubble != null)
	if important_bubble != null:
		_check("IMPORTANT_WORLD_TEXT_ORANGE", _color_near(important_bubble.text_color(), Color("d9a15f")))
		_check("IMPORTANT_WORLD_TEXT_MATCH", important_bubble.displayed_text() == important_text)
	_check("IMPORTANT_BOTTOM_LINE_VISIBLE", hud.important_dialogue_line_visible())
	_check("IMPORTANT_BOTTOM_LINE_MATCH", hud.important_dialogue_line_text() == important_text)
	_check("IMPORTANT_BOTTOM_LINE_ORANGE", _color_near(hud.important_dialogue_line_color(), Color("d9a15f")))
	var choices: Array = [
		{"choice_ref": "CHOICE-ACCEPT", "label": "Atravessar depois"},
		{"choice_ref": "CHOICE-ASK", "label": "Perguntar sobre a ponte"},
	]
	var choice_result: Dictionary = hud.present_choices(npc_peer, choices, 1.5)
	_check("CHOICES_NEAR_NPC_PASS", choice_result.get("status") == "PASS", JSON.stringify(choice_result))
	_check("CHOICES_DISCREET_NOT_MODAL", choice_result.get("large_modal") == false)
	_check("CHOICES_NO_NEXT_BUTTON", choice_result.get("next_button") == false)
	_check("CHOICES_VISIBLE_NEAR_SPEAKER", hud.choices_visible_for_speaker(npc_peer.target_ref))
	var far_choices: Dictionary = hud.present_choices(npc_peer, choices, 2.5)
	_check("CHOICES_TOO_FAR_REJECTED", far_choices.get("status") == "REJECTED" and far_choices.get("reason") == "OUT_OF_CHOICE_RANGE")
	var choice_button: Button = _first_visible_choice_button(important_bubble)
	_check("CHOICE_BUTTON_FOUND", choice_button != null)
	if choice_button != null:
		choice_button.emit_signal("pressed")
		await _wait_process_frames(1)
		var choice_intent: Dictionary = hud.last_choice_intent()
		_check("CHOICE_INTENT_PROJECTED", choice_intent.get("status") == "PASS", JSON.stringify(choice_intent))
		_check("CHOICE_ENVELOPE_BUILT", choice_intent.get("intent_envelope", {}).get("status") == "PASS", JSON.stringify(choice_intent))
		_check("CHOICE_NOT_SUBMITTED", choice_intent.get("transport_submitted") == false)
		_check("CHOICE_NARRATIVE_AUTHORITY_UNCHANGED", choice_intent.get("narrative_authority_changed") == false)
	var button_nodes: Array[Node] = hud.find_children("*", "Button", true, false)
	var has_next: bool = false
	for button_node: Node in button_nodes:
		var button := button_node as Button
		if button == null:
			continue
		var normalized: String = "%s %s" % [button.name, button.text]
		normalized = normalized.to_lower()
		if normalized.contains("next") or normalized.contains("próximo") or normalized.contains("proximo"):
			has_next = true
	_check("DIALOGUE_STRUCTURALLY_HAS_NO_NEXT_BUTTON", not has_next)
	for conversation_index: int in range(2, 6):
		var speaker: AndromedaInteractionTarget = npc_primary if conversation_index % 2 == 0 else npc_peer
		var separate_result: Dictionary = hud.present_dialogue_line(speaker, {
			"line_ref": "B05-SEPARATE-%d" % conversation_index,
			"speaker_ref": speaker.target_ref,
			"text": "Conversa ambiente %d." % conversation_index,
			"conversation_ref": "B05-SEPARATE-CONV-%d" % conversation_index,
			"turn_index": 1,
			"important": false,
			"duration_seconds": 5.0,
		})
		_check("DIALOGUE_SEPARATE_%d_PASS" % conversation_index, separate_result.get("status") == "PASS", JSON.stringify(separate_result))
		_check("DIALOGUE_POOL_LIMIT_%d" % conversation_index, hud.active_dialogue_count() <= 3, str(hud.active_dialogue_count()))
	_check("DIALOGUE_POOL_MAX_THREE_NO_SPAM", hud.active_dialogue_count() == 3, str(hud.active_dialogue_count()))
	var stale_result: Dictionary = hud.present_dialogue_line(npc_primary, {
		"line_ref": "B05-STALE",
		"speaker_ref": npc_primary.target_ref,
		"text": "Turno antigo.",
		"conversation_ref": "B05-CONVERSATION-PAIR",
		"turn_index": 1,
	})
	_check("STALE_CONVERSATION_TURN_REJECTED", stale_result.get("status") == "REJECTED")
	var player_before: Vector3 = player.global_position
	var move_result: Dictionary = player.request_move(Vector3(-8.0, 0.0, 3.0))
	_check("PLAYER_CAN_REQUEST_MOVE_DURING_DIALOGUE", move_result.get("status") == "PASS", JSON.stringify(move_result))
	await _wait_physics_frames(18)
	_check("PLAYER_MOVES_DURING_DIALOGUE", _horizontal_distance(player_before, player.global_position) > 0.05, "%s -> %s" % [player_before, player.global_position])
	player.stop_local_prediction()
	npc_primary.global_position = primary_original_position
	npc_peer.global_position = peer_original_position


func _test_inventory_and_auto_pickup() -> void:
	main.set_menu_open(true)
	await _wait_process_frames(3)
	_check("INVENTORY_VISIBLE_WHEN_OPEN", hud.inventory_shell.visible)
	_check("INVENTORY_BLOCKS_WORLD_POINTER_WHEN_OPEN", hud.inventory_shell.mouse_filter == Control.MOUSE_FILTER_STOP)
	_check("INVENTORY_BASE_SLOT_COUNT_EIGHT", hud.inventory_shell.base_slot_count() == 8, str(hud.inventory_shell.base_slot_count()))
	var inventory_contract: Dictionary = hud.inventory_shell.contract_snapshot()
	_check("INVENTORY_REDUCED_BASE_POLICY_SHELL", inventory_contract.get("base_inventory_reduced") == true)
	_check("INVENTORY_BAG_SLOT_PRESENT", inventory_contract.get("bag_slot_present") == true)
	_check("INVENTORY_BAG_CONTAINER_PRESENT", inventory_contract.get("bag_container_present") == true)
	_check("INVENTORY_TWO_QUICKSLOT_REFERENCES", inventory_contract.get("weapon_quick_slot_references") == [1, 2])
	_check("INVENTORY_WHITE_ROUNDED_LANGUAGE", inventory_contract.get("white_rounded_language") == true)
	_check("INVENTORY_CONTENT_AUTHORITY_EXTERNAL", inventory_contract.get("authoritative_contents_in_gdscript") == false)
	_check("INVENTORY_WEIGHT_AUTHORITY_EXTERNAL", inventory_contract.get("authoritative_weight_in_gdscript") == false)
	_check("INVENTORY_DEATH_POLICY_EXTERNAL", inventory_contract.get("authoritative_death_policy_in_gdscript") == false)
	var auto_off: Dictionary = hud.set_auto_pickup_projection(false, true)
	_check("AUTO_PICKUP_OFF_VISUAL_PASS", auto_off.get("status") == "PASS" and auto_off.get("enabled") == false)
	_check("AUTO_PICKUP_OFF_NO_REMOTE_COLLECTION", auto_off.get("remote_collection_enabled_by_ui") == false)
	var auto_on: Dictionary = hud.set_auto_pickup_projection(true, true)
	_check("AUTO_PICKUP_ON_VISUAL_PASS", auto_on.get("status") == "PASS" and auto_on.get("enabled") == true)
	_check("AUTO_PICKUP_ON_NO_REMOTE_COLLECTION", auto_on.get("remote_collection_enabled_by_ui") == false)
	_check("AUTO_PICKUP_NOT_PERSISTED_CLIENT", auto_on.get("persisted_by_gdscript") == false)
	var auto_button := hud.inventory_shell.get_node("RoundedWhitePanel/Margin/Layout/MenuScroll/Content/AutoPickupSection/AutoPickupButton") as Button
	auto_button.emit_signal("pressed")
	await _wait_process_frames(1)
	var auto_intent: Dictionary = hud.last_auto_pickup_intent()
	_check("AUTO_PICKUP_INTENT_PROJECTED", auto_intent.get("status") == "PASS", JSON.stringify(auto_intent))
	_check("AUTO_PICKUP_ENVELOPE_BUILT", auto_intent.get("intent_envelope", {}).get("status") == "PASS", JSON.stringify(auto_intent))
	_check("AUTO_PICKUP_NOT_SUBMITTED", auto_intent.get("transport_submitted") == false)
	_check("AUTO_PICKUP_REMOTE_COLLECTION_STILL_FALSE", auto_intent.get("remote_collection_enabled") == false)
	main.set_menu_open(false)
	_check("INVENTORY_HIDDEN_WHEN_CLOSED", not hud.inventory_shell.visible)
	_check("INVENTORY_IGNORES_POINTER_WHEN_CLOSED", hud.inventory_shell.mouse_filter == Control.MOUSE_FILTER_IGNORE)


func _test_snapshot_projection() -> void:
	var snapshot := {
		"stamina": {"fraction": 0.42, "activity": "CONSUMING"},
		"weapon_loadout": {"active_slot": 2},
		"profile_preferences": {"auto_pickup": true},
	}
	var projected: Dictionary = hud.apply_presentation_snapshot(snapshot)
	_check("SNAPSHOT_PROJECTION_PASS", projected.get("status") == "PASS", JSON.stringify(projected))
	var channels: Array = projected.get("projected_channels", [])
	_check("SNAPSHOT_STAMINA_CHANNEL", channels.has("STAMINA"), str(channels))
	_check("SNAPSHOT_WEAPON_CHANNEL", channels.has("WEAPON_LOADOUT"), str(channels))
	_check("SNAPSHOT_AUTO_PICKUP_CHANNEL", channels.has("AUTO_PICKUP"), str(channels))
	_check("SNAPSHOT_STAMINA_VALUE", is_equal_approx(hud.stamina_ring.stamina_fraction(), 0.42))
	_check("SNAPSHOT_STAMINA_SOURCE", hud.stamina_ring.projection_source() == "AUTHORITATIVE_SNAPSHOT")
	_check("SNAPSHOT_ACTIVE_SLOT_TWO", hud.active_weapon_slot() == 2)
	_check("SNAPSHOT_ACTIVE_SLOT_SOURCE", hud.weapon_quick_slots.projection_source() == "AUTHORITATIVE_SNAPSHOT")
	_check("SNAPSHOT_AUTO_PICKUP_TRUE", hud.inventory_shell.auto_pickup_enabled())
	_check("SNAPSHOT_NOT_MUTATED", projected.get("snapshot_mutated") == false)
	_check("LOCAL_BAD_SLOT_REJECTED", hud.request_weapon_slot(3, "LOCAL_GATE_PLACEHOLDER").get("status") == "REJECTED")


func _test_camera_and_click_to_move_stability() -> void:
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	player.velocity = Vector3.ZERO
	camera_rig.set_follow_target(player, true)
	await _wait_physics_frames(5)
	var enemy_screen: Vector2 = main.target_to_screen(enemy)
	var select_event := InputEventMouseButton.new()
	select_event.button_index = MOUSE_BUTTON_LEFT
	select_event.pressed = true
	select_event.position = enemy_screen
	var select_result: Dictionary = main.handle_pointer_event(select_event)
	_check("TARGET_SELECTION_CLICK_PASS", select_result.get("status") == "PASS", JSON.stringify(select_result))
	_check("TARGET_SELECTION_INTENT", select_result.get("intent") == "SELECT_TARGET", JSON.stringify(select_result))
	_check("TARGET_SELECTION_ENEMY_STABLE_REF", main.selected_target_ref() == enemy.target_ref, main.selected_target_ref())
	var selected_before: String = main.selected_target_ref()
	var camera_y_before: float = camera_rig.global_position.y
	player.global_position.y += 0.05
	await _wait_physics_frames(8)
	_check("CAMERA_MICRO_HEIGHT_DEADBAND_STABLE", absf(camera_rig.global_position.y - camera_y_before) < 0.001, "%f -> %f" % [camera_y_before, camera_rig.global_position.y])
	_check("MICRO_HEIGHT_DOES_NOT_CHANGE_TARGET", main.selected_target_ref() == selected_before)
	var slot_before: int = hud.active_weapon_slot()
	main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_DOWN, true))
	await _wait_physics_frames(4)
	_check("CAMERA_ZOOM_DOES_NOT_CHANGE_TARGET", main.selected_target_ref() == selected_before)
	_check("CAMERA_ZOOM_DOES_NOT_CHANGE_SLOT", hud.active_weapon_slot() == slot_before)
	main.handle_action_event(_key_event(KEY_1))
	_check("WEAPON_KEY_DOES_NOT_CHANGE_TARGET", main.selected_target_ref() == selected_before)
	main.set_menu_open(true)
	main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_DOWN, false))
	main.set_menu_open(false)
	_check("MENU_UI_DOES_NOT_CHANGE_TARGET", main.selected_target_ref() == selected_before)
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	player.velocity = Vector3.ZERO
	camera_rig.set_follow_target(player, true)
	await _wait_physics_frames(5)
	var ground_screen: Vector2 = main.world_to_screen(Vector3(-8.0, 0.0, 4.0))
	var move_event := InputEventMouseButton.new()
	move_event.button_index = MOUSE_BUTTON_LEFT
	move_event.pressed = true
	move_event.position = ground_screen
	var move_result: Dictionary = main.handle_pointer_event(move_event)
	_check("UI_CLOSED_CLICK_TO_MOVE_PASS", move_result.get("status") == "PASS", JSON.stringify(move_result))
	_check("UI_CLOSED_CLICK_TO_MOVE_INTENT", move_result.get("intent") == "MOVE_TO_POINT", JSON.stringify(move_result))
	_check("UI_CLOSED_CLICK_TO_MOVE_REQUESTED", move_result.get("movement_result", {}).get("status") == "PASS", JSON.stringify(move_result))
	await _wait_physics_frames(12)
	_check("UI_CLOSED_PLAYER_MOVES", _horizontal_distance(Vector3(-7.0, 0.0, 0.0), player.global_position) > 0.05, str(player.global_position))
	_check("CLICK_TO_MOVE_DOES_NOT_REWRITE_SELECTED_TARGET", main.selected_target_ref() == selected_before)
	_check("HUD_ROOT_STILL_IGNORES_WORLD_POINTER", hud.mouse_filter == Control.MOUSE_FILTER_IGNORE)
	_check("CAMERA_FOLLOW_TARGET_PRESERVED", camera_rig.follow_target() == player)
	_check("CAMERA_FREE_ORBIT_FALSE", camera_rig.contract_snapshot().get("free_orbit") == false)
	_check("CAMERA_ZOOM_WITHIN_CLAMPS", camera_rig.target_distance_m() >= camera_rig.minimum_distance_m and camera_rig.target_distance_m() <= camera_rig.maximum_distance_m)


func _active_bubble_for_speaker(speaker_ref: String) -> AndromedaDialogueBubble:
	for index: int in range(1, 4):
		var bubble := hud.get_node("WorldUIRoot/DialogueBubblePool/Bubble%d" % index) as AndromedaDialogueBubble
		if bubble != null and bubble.is_line_active() and bubble.current_speaker_ref() == speaker_ref:
			return bubble
	return null


func _first_visible_choice_button(bubble: AndromedaDialogueBubble) -> Button:
	if bubble == null:
		return null
	var buttons: Array[Node] = bubble.find_children("Choice*", "Button", true, false)
	for button_node: Node in buttons:
		var button := button_node as Button
		if button != null and button.visible:
			return button
	return null


func _key_event(key_value: int) -> InputEventKey:
	var event := InputEventKey.new()
	event.keycode = key_value as Key
	event.pressed = true
	return event


func _wheel_event(button_value: int, shift: bool) -> InputEventMouseButton:
	var event := InputEventMouseButton.new()
	event.button_index = button_value as MouseButton
	event.pressed = true
	event.shift_pressed = shift
	return event


func _color_near(left: Color, right: Color) -> bool:
	return absf(left.r - right.r) < 0.01 and absf(left.g - right.g) < 0.01 and absf(left.b - right.b) < 0.01


func _horizontal_distance(first: Vector3, second: Vector3) -> float:
	return Vector2(first.x, first.z).distance_to(Vector2(second.x, second.z))


func _wait_process_frames(frame_count: int) -> void:
	for frame_index: int in range(frame_count):
		await get_tree().process_frame


func _wait_physics_frames(frame_count: int) -> void:
	for frame_index: int in range(frame_count):
		await get_tree().physics_frame


func _restore_gate_state() -> void:
	main.set_menu_open(false)
	player.stop_local_prediction()
	player.global_position = Vector3(-7.0, 0.0, 0.0)
	player.velocity = Vector3.ZERO
	camera_rig.set_follow_target(player, true)
	hud.project_stamina(1.0, "INACTIVE", "LOCAL_GATE_PLACEHOLDER")
	hud.request_weapon_slot(1, "LOCAL_GATE_PLACEHOLDER")


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "B05_HUD_WORLD_UI_DIALOGUE_STAMINA_WEAPON_SLOTS",
		"acceptance_scope_pass": ["G16B-10", "G16B-11", "G16B-12"],
		"partial_evidence_only": ["G16B-06", "G16B-08", "G16B-13", "G16B-14", "G16B-20", "G16B-21", "G16B-22", "G16B-23", "G16B-26"],
		"not_available_without_authoritative_backend": ["LIVE_STAMINA_ROUNDTRIP", "LIVE_MAIN_HAND_ROUNDTRIP", "AUTO_PICKUP_PERSISTENCE", "INVENTORY_BAG_CONTENTS"],
		"authority": "GODOT_HUD_WORLD_UI_PRESENTATION_ONLY",
		"backend_roundtrip_executed": false,
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_B05_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_B05_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_B05_SUMMARY: %s" % JSON.stringify(summary))
	if not _failures.is_empty():
		get_tree().quit(1)
		return
	var linger_s: float = _success_linger_seconds()
	if linger_s > 0.0:
		await get_tree().create_timer(linger_s).timeout
	get_tree().quit(0)


func _success_linger_seconds() -> float:
	var configured: float = float(ProjectSettings.get_setting("andromeda/gate/success_linger_s", 240.0))
	for argument: String in OS.get_cmdline_user_args():
		if not argument.begins_with("--gate-success-linger="):
			continue
		var raw_value: String = argument.trim_prefix("--gate-success-linger=")
		if raw_value.is_valid_float():
			return maxf(0.0, raw_value.to_float())
	return maxf(0.0, configured)
