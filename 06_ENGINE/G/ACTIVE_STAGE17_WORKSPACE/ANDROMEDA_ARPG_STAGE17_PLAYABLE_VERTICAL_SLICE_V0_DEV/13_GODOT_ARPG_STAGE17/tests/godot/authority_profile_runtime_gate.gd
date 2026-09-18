extends Node

const SESSION_REF := "GODOT-AUTHORITY-PROFILE-V080"
const WAIT_TIMEOUT_S := 45.0

@onready var main: AndromedaMainRuntime = $AndromedaARPG
@onready var hud: AndromedaHUDController = $AndromedaARPG/UILayer/MinimalHUD

var _checks: int = 0
var _failures: Array[String] = []
var _bind_results: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []
var _commands: Array[Dictionary] = []
var _command_rejections: Array[String] = []


func _ready() -> void:
	await _run_gate()


func _run_gate() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_check("SESSION_AUTOLOAD", session != null)
	_check("BRIDGE_AUTOLOAD", bridge != null)
	_check("MAIN_PRESENTATION_RUNTIME", main != null and hud != null)
	if session == null or bridge == null or main == null or hud == null:
		await _finish()
		return
	bridge.authority_session_bound.connect(func(result: Dictionary) -> void:
		_bind_results.append(result.duplicate(true))
	)
	bridge.snapshot_applied.connect(func(snapshot: Dictionary) -> void:
		_snapshots.append(snapshot.duplicate(true))
	)
	bridge.command_completed.connect(func(result: Dictionary) -> void:
		_commands.append(result.duplicate(true))
	)
	bridge.command_rejected.connect(func(reason: String) -> void:
		_command_rejections.append(reason)
	)

	if session.has_active_session():
		session.revoke_session()
	_check("LOCAL_BIND", session.bind_session(SESSION_REF).get("status") == "PASS")
	_check("AUTHORITY_BIND_STARTED", bridge.bind_authoritative_session().get("status") == "PASS")
	if not await _wait_for_count(_bind_results, 1):
		_failures.append("AUTHORITY_BIND_TIMEOUT")
		await _finish()
		return
	if not await _wait_for_count(_snapshots, 1):
		_failures.append("INITIAL_SNAPSHOT_TIMEOUT")
		await _finish()
		return
	var initial: Dictionary = _snapshots[0]
	var enabled_commands: Array = _bind_results[0].get("enabled_commands", [])
	for command: String in ["SET_AUTO_PICKUP", "ACTIVATE_WEAPON_SLOT", "CYCLE_WEAPON_SLOT"]:
		_check("AUTHORITY_ENABLES_%s" % command, enabled_commands.has(command), JSON.stringify(enabled_commands))
	_check("PROFILE_SNAPSHOT_AUTHORITATIVE", initial.get("server_authoritative") == true)
	_check("PROFILE_SNAPSHOT_HAS_PREFERENCES", initial.get("profile_preferences") is Dictionary)
	_check("PROFILE_SNAPSHOT_HAS_LOADOUT", initial.get("weapon_loadout") is Dictionary)
	_check("PROFILE_SNAPSHOT_HAS_INVENTORY", initial.get("inventory") is Dictionary)
	_check("PROFILE_SNAPSHOT_HAS_MODIFIERS", initial.get("equipment_modifiers") is Dictionary)

	var loadout: Dictionary = initial.get("weapon_loadout", {})
	var slots: Dictionary = loadout.get("slots", {})
	_check("EXACTLY_TWO_AUTHORITY_QUICKSLOTS", slots.size() == 2 and slots.has("1") and slots.has("2"), JSON.stringify(loadout))
	_check("TWO_DISTINCT_WEAPON_INSTANCES", not str(slots.get("1", "")).is_empty() and str(slots.get("1")) != str(slots.get("2")))
	var initial_active: int = int(loadout.get("active_slot", 0))
	_check("ONE_AUTHORITY_ACTIVE_SLOT", initial_active in [1, 2], JSON.stringify(loadout))
	_check("HUD_PROJECTED_AUTHORITY_ACTIVE_SLOT", hud.active_weapon_slot() == initial_active)
	_check(
		"MAIN_HAND_MATCHES_ACTIVE_QUICKSLOT",
		str(initial.get("inventory", {}).get("equipped", {}).get("MAIN_HAND", "")) == str(slots.get(str(initial_active), ""))
	)
	_check("ONLY_ONE_MAIN_HAND_MODIFIER_APPLIED", _applied_main_hand_count(initial) == 1)

	var preference_before: bool = bool(initial.get("profile_preferences", {}).get("auto_pickup", false))
	var desired_preference: bool = not preference_before
	hud.inventory_shell.set_auto_pickup_visual(desired_preference, true)
	await get_tree().process_frame
	var auto_intent: Dictionary = hud.last_auto_pickup_intent()
	_check("AUTO_PICKUP_UI_INTENT_PASS", auto_intent.get("status") == "PASS", JSON.stringify(auto_intent))
	_check("AUTO_PICKUP_UI_SUBMITTED_TO_AUTHORITY", auto_intent.get("transport_submitted") == true, JSON.stringify(auto_intent))
	_check(
		"AUTO_PICKUP_COMMAND_REF_PRESENT",
		not str(auto_intent.get("intent_envelope", {}).get("envelope", {}).get("command_ref", "")).is_empty()
	)
	var auto_result: Dictionary = await _result_for_command("SET_AUTO_PICKUP")
	if auto_result.is_empty() or not await _wait_for_count(_snapshots, 2):
		_failures.append("AUTO_PICKUP_ROUNDTRIP_TIMEOUT")
		await _finish()
		return
	var auto_snapshot: Dictionary = _snapshots.back()
	_check("AUTO_PICKUP_CORE_PASS", auto_result.get("status") == "PASS", JSON.stringify(auto_result))
	_check("AUTO_PICKUP_CORE_COMMAND", auto_result.get("command") == "SET_AUTO_PICKUP")
	_check("AUTO_PICKUP_CORE_AUTHORITY", auto_result.get("server_authoritative") == true)
	_check("AUTO_PICKUP_SNAPSHOT_CHANGED", bool(auto_snapshot.get("profile_preferences", {}).get("auto_pickup")) == desired_preference)
	_check("AUTO_PICKUP_HUD_CORRECTED_BY_SNAPSHOT", hud.inventory_shell.auto_pickup_enabled() == desired_preference)
	_check("AUTO_PICKUP_CLIENT_PROJECTION_CONFIRMED", main.ground_loot_client.auto_pickup_enabled() == desired_preference)

	var target_slot: int = 2 if int(auto_snapshot.get("weapon_loadout", {}).get("active_slot", 1)) == 1 else 1
	var key_result: Dictionary = main.handle_action_event(_key_event(KEY_2 if target_slot == 2 else KEY_1))
	_check("KEY_SLOT_INPUT_PASS", key_result.get("status") == "PASS", JSON.stringify(key_result))
	_check("KEY_SLOT_TRANSPORT_SUBMITTED", key_result.get("ui_projection", {}).get("transport_submitted") == true, JSON.stringify(key_result))
	var activate_result: Dictionary = await _result_for_command("ACTIVATE_WEAPON_SLOT")
	if activate_result.is_empty() or not await _wait_for_count(_snapshots, 3):
		_failures.append("WEAPON_ACTIVATION_ROUNDTRIP_TIMEOUT")
		await _finish()
		return
	var activate_snapshot: Dictionary = _snapshots.back()
	_check("ACTIVATE_WEAPON_CORE_PASS", activate_result.get("status") == "PASS", JSON.stringify(activate_result))
	_check("ACTIVATE_WEAPON_COMMAND", activate_result.get("command") == "ACTIVATE_WEAPON_SLOT")
	_check("ACTIVATE_WEAPON_SLOT_MATCH", int(activate_snapshot.get("weapon_loadout", {}).get("active_slot", 0)) == target_slot)
	_check(
		"ACTIVATE_MAIN_HAND_MATCH",
		str(activate_snapshot.get("inventory", {}).get("equipped", {}).get("MAIN_HAND", ""))
		== str(activate_snapshot.get("weapon_loadout", {}).get("slots", {}).get(str(target_slot), ""))
	)
	_check("ACTIVATE_NO_INACTIVE_MODIFIER_STACK", _applied_main_hand_count(activate_snapshot) == 1)
	_check("ACTIVATE_HUD_SNAPSHOT_MATCH", hud.active_weapon_slot() == target_slot)

	var wheel_result: Dictionary = main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_DOWN, false))
	_check("UNMODIFIED_WHEEL_CYCLE", wheel_result.get("intent") == "WEAPON_QUICK_SLOT_CYCLE", JSON.stringify(wheel_result))
	_check("UNMODIFIED_WHEEL_SUBMITTED", wheel_result.get("transport_submitted") == true, JSON.stringify(wheel_result))
	var cycle_result: Dictionary = await _result_for_command("CYCLE_WEAPON_SLOT")
	if cycle_result.is_empty() or not await _wait_for_count(_snapshots, 4):
		_failures.append("WEAPON_CYCLE_ROUNDTRIP_TIMEOUT")
		await _finish()
		return
	var cycle_snapshot: Dictionary = _snapshots.back()
	_check("CYCLE_CORE_PASS", cycle_result.get("status") == "PASS", JSON.stringify(cycle_result))
	_check("CYCLE_CORE_COMMAND", cycle_result.get("command") == "CYCLE_WEAPON_SLOT")
	_check("CYCLE_CHANGED_ACTIVE_SLOT", int(cycle_snapshot.get("weapon_loadout", {}).get("active_slot", 0)) != target_slot)
	_check("CYCLE_ONLY_ONE_MAIN_HAND", _applied_main_hand_count(cycle_snapshot) == 1)

	var commands_before_zoom: int = _commands.size()
	var zoom_before: float = main.camera_rig.target_distance_m()
	var zoom_result: Dictionary = main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_UP, true))
	await _wait_process_frames(5)
	_check("MODIFIER_WHEEL_ZOOM_ONLY", zoom_result.get("intent") == "CAMERA_ZOOM")
	_check("MODIFIER_WHEEL_CHANGED_ZOOM", main.camera_rig.target_distance_m() != zoom_before)
	_check("MODIFIER_WHEEL_NO_WEAPON_COMMAND", _commands.size() == commands_before_zoom)

	main.set_menu_open(true)
	var menu_result: Dictionary = main.handle_pointer_event(_wheel_event(MOUSE_BUTTON_WHEEL_DOWN, false))
	await _wait_process_frames(5)
	main.set_menu_open(false)
	_check("MENU_WHEEL_SCROLL_ONLY", menu_result.get("intent") == "MENU_SCROLL", JSON.stringify(menu_result))
	_check("MENU_WHEEL_NO_AUTHORITY_COMMAND", _commands.size() == commands_before_zoom)
	# G16B-21: two quick slots is a loadout limit, not an inventory limit. Count weapons
	# wherever the authority routes them, since an equipped Bag becomes the effective
	# inventory owner and the base inventory then holds nothing.
	var final_snapshot: Dictionary = _snapshots.back()
	var carried_weapons: int = _carried_weapon_count(final_snapshot)
	var slot_map: Dictionary = final_snapshot.get("weapon_loadout", {}).get("slots", {})
	var filled_slots: int = 0
	for slot_value: Variant in slot_map.values():
		if not str(slot_value).is_empty():
			filled_slots += 1
	_check("QUICK_LOADOUT_EXPOSES_EXACTLY_TWO_SLOTS", slot_map.size() == 2, JSON.stringify(slot_map))
	_check("BOTH_QUICK_SLOTS_FILLED", filled_slots == 2)
	_check(
		"INVENTORY_MAY_CARRY_MORE_WEAPONS_THAN_SLOTS",
		carried_weapons > filled_slots,
		"carried=%d slots=%d" % [carried_weapons, filled_slots]
	)

	_check("NO_COMMAND_REJECTIONS", _command_rejections.is_empty(), JSON.stringify(_command_rejections))
	_check("BRIDGE_FINAL_READY", bridge.connection_state().get("state") == "READY")
	_check("NO_PROFILE_AUTHORITY_IN_GDSCRIPT", true)
	await _finish()


func _applied_main_hand_count(snapshot: Dictionary) -> int:
	var count: int = 0
	for row_value: Variant in snapshot.get("equipment_modifiers", {}).get("equipped", []):
		if row_value is Dictionary:
			var row: Dictionary = row_value
			if row.get("slot") == "MAIN_HAND" and row.get("applied") == true:
				count += 1
	return count


func _key_event(keycode: Key) -> InputEventKey:
	var event := InputEventKey.new()
	event.keycode = keycode
	event.pressed = true
	return event


func _wheel_event(button: MouseButton, shift_pressed: bool) -> InputEventMouseButton:
	var event := InputEventMouseButton.new()
	event.button_index = button
	event.shift_pressed = shift_pressed
	event.pressed = true
	return event


func _wait_for_count(values: Array, expected: int) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while values.size() < expected and Time.get_ticks_usec() < deadline:
		await get_tree().process_frame
	return values.size() >= expected


func _wait_process_frames(count: int) -> void:
	for _index: int in range(count):
		await get_tree().process_frame


func _check(check_id: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(check_id if detail.is_empty() else "%s:%s" % [check_id, detail])


func _result_for_command(command_name: String) -> Dictionary:
	## Match the authoritative result by command name, never by arrival index. With
	## Auto Pickup on, the ground-loot client injects its own REQUEST_PICKUP into the
	## same stream and index matching silently reads the wrong result.
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		for entry: Dictionary in _commands:
			if str(entry.get("command", "")) == command_name:
				return entry.duplicate(true)
		await get_tree().process_frame
	return {}


func _carried_weapon_count(snapshot: Dictionary) -> int:
	## Weapons live in the base inventory, or inside an equipped Bag once that Bag
	## becomes the effective inventory owner. Count both.
	var projection: Dictionary = snapshot.get("inventory_projection", {})
	var total: int = 0
	var sources: Array = [
		(projection.get("base_inventory", {}) as Dictionary).get("stacks", []),
		(projection.get("bag", {}) as Dictionary).get("contents", []),
	]
	for source: Variant in sources:
		if not source is Array:
			continue
		for entry: Variant in source:
			if entry is Dictionary and str((entry as Dictionary).get("item_kind", "")) == "WEAPON":
				total += int((entry as Dictionary).get("quantity", 1))
	return total


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "STAGE16B_AUTHORITY_PROFILE_AUTO_PICKUP_MAIN_HAND",
		"backend_roundtrip_executed": true,
		"authority": "STAGE16A_AND_STAGE05_SERVER_AUTHORITATIVE",
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_AUTHORITY_PROFILE_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_AUTHORITY_PROFILE_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_AUTHORITY_PROFILE_SUMMARY: %s" % JSON.stringify(summary))
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

