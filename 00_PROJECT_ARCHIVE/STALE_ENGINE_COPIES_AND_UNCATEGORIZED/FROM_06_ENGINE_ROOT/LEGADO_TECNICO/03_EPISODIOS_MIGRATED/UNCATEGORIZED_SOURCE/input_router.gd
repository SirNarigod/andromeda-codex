extends Node
class_name AndromedaInputRouter

## Stage16B pointer semantics adapter. It resolves presentation intents only.
## Authoritative interaction, combat, pickup, inventory, and weapon state stay outside Godot.

signal pointer_intent_resolved(result: Dictionary)

const AUTHORITY := "GODOT_INPUT_INTENT_PRESENTATION_ONLY"
const PICKUP_RADIUS_M := 0.5
const SCREEN_DISTANCE_DEPTH_TIE_EPSILON_PX := 0.25

const HIT_GROUND := "GROUND"
const HIT_GROUND_LOOT := "GROUND_LOOT"
const HIT_DROPPED_BAG := "DROPPED_BAG"
const HIT_ACTOR := "ACTOR"
const HIT_NPC := "NPC"
const HIT_ANIMAL := "ANIMAL"
const HIT_GATHER_NODE := "GATHER_NODE"
const HIT_SCENE_OBJECT := "SCENE_OBJECT"
const HIT_VEHICLE := "VEHICLE"


func resolve_pointer_click(
	button_index: int,
	hit_kind_value: String,
	world_position: Vector3,
	target_ref_value: String = "",
	hostile: bool = false,
	physical_distance_m: float = INF,
	reachable: bool = true,
	ground_loot_settled: bool = true
) -> Dictionary:
	var button: String = _button_name(button_index)
	if button.is_empty():
		return _emit_result(_rejected("UNSUPPORTED_POINTER_BUTTON"))
	var hit_kind: String = hit_kind_value.strip_edges().to_upper()
	var target_ref: String = target_ref_value.strip_edges()
	if hit_kind == HIT_GROUND:
		return _emit_result({
			"status": "PASS",
			"intent": "MOVE_TO_POINT",
			"ground_point": _ground_point(world_position),
			"world_position": world_position,
			"cursor": "MOVE",
			"button": button,
			"authority": AUTHORITY,
		})
	if hit_kind == HIT_GROUND_LOOT:
		return _emit_result(_resolve_ground_loot(
			button,
			target_ref,
			world_position,
			physical_distance_m,
			reachable,
			ground_loot_settled
		))
	if target_ref.is_empty():
		return _emit_result(_rejected("EMPTY_TARGET_REF"))
	if button == "LEFT":
		return _emit_result({
			"status": "PASS",
			"intent": "SELECT_TARGET",
			"target_ref": target_ref,
			"target_kind": hit_kind,
			"cursor": "SELECT",
			"movement_change": "NONE",
			"button": button,
			"authority": AUTHORITY,
		})
	if hit_kind == HIT_ACTOR and hostile:
		return _emit_result({
			"status": "PASS",
			"intent": "CHASE_ATTACK",
			"target_ref": target_ref,
			"target_kind": hit_kind,
			"requires_path": true,
			"input_mode": "CLICK_ONLY",
			"implementation_stage": "FUTURE",
			"authoritative_result_required": true,
			"cursor": "ATTACK",
			"button": button,
			"authority": AUTHORITY,
		})
	if hit_kind in [HIT_ACTOR, HIT_NPC, HIT_ANIMAL]:
		return _emit_result({
			"status": "PASS",
			"intent": "APPROACH_INTERACT",
			"target_ref": target_ref,
			"target_kind": hit_kind,
			"requires_path": true,
			"input_mode": "CLICK_ONLY",
			"implementation_stage": "FUTURE",
			"authoritative_result_required": true,
			"cursor": "TALK" if hit_kind == HIT_NPC else "INTERACT",
			"button": button,
			"authority": AUTHORITY,
		})
	if hit_kind == HIT_GATHER_NODE:
		return _emit_result({
			"status": "PASS",
			"intent": "APPROACH_HARVEST",
			"target_ref": target_ref,
			"target_kind": hit_kind,
			"requires_path": true,
			"input_mode": "CLICK_ONLY",
			"implementation_stage": "FUTURE",
			"authoritative_result_required": true,
			"cursor": "HARVEST",
			"button": button,
			"authority": AUTHORITY,
		})
	if hit_kind == HIT_DROPPED_BAG:
		return _emit_result({
			"status": "PASS",
			"intent": "APPROACH_RECOVER_BAG",
			"target_ref": target_ref,
			"target_kind": hit_kind,
			"requires_path": true,
			"input_mode": "CLICK_ONLY",
			"authoritative_result_required": true,
			"cursor": "RECOVER",
			"button": button,
			"authority": AUTHORITY,
		})
	if hit_kind in [HIT_SCENE_OBJECT, HIT_VEHICLE]:
		return _emit_result({
			"status": "PASS",
			"intent": "APPROACH_INTERACT",
			"target_ref": target_ref,
			"target_kind": hit_kind,
			"requires_path": true,
			"implementation_stage": "FUTURE",
			"authoritative_result_required": true,
			"cursor": "INTERACT",
			"button": button,
			"authority": AUTHORITY,
		})
	return _emit_result(_rejected("UNRESOLVED_CONTEXT"))


func choose_pointer_target(candidates: Array[Dictionary]) -> Dictionary:
	var eligible: Array[Dictionary] = []
	for candidate: Dictionary in candidates:
		if not bool(candidate.get("direct_hit", true)):
			continue
		if str(candidate.get("target_ref", "")).strip_edges().is_empty():
			continue
		eligible.append(candidate.duplicate(true))
	if eligible.is_empty():
		return {}
	eligible.sort_custom(_candidate_less)
	return eligible[0].duplicate(true)


func resolve_hover_candidate(candidate: Dictionary) -> Dictionary:
	if candidate.is_empty():
		return {
			"status": "PASS",
			"intent": "HOVER_CLEAR",
			"cursor": "DEFAULT",
			"authority": AUTHORITY,
		}
	var hit_kind: String = str(candidate.get("target_kind", "")).to_upper()
	var cursor: String = "INTERACT"
	if hit_kind == HIT_GROUND_LOOT:
		cursor = "PICKUP" if bool(candidate.get("ground_loot_settled", true)) else "BLOCKED"
	elif hit_kind == HIT_DROPPED_BAG:
		cursor = "RECOVER" if bool(candidate.get("selectable", true)) else "BLOCKED"
	elif hit_kind == HIT_ACTOR and bool(candidate.get("hostile", false)):
		cursor = "ATTACK"
	elif hit_kind == HIT_NPC:
		cursor = "TALK"
	elif hit_kind == HIT_GATHER_NODE:
		cursor = "HARVEST"
	return {
		"status": "PASS",
		"intent": "HOVER_TARGET",
		"target_ref": str(candidate.get("target_ref", "")),
		"target_kind": hit_kind,
		"cursor": cursor,
		"authority": AUTHORITY,
	}


func semantic_priority(hit_kind_value: String) -> int:
	var hit_kind: String = hit_kind_value.strip_edges().to_upper()
	if hit_kind == HIT_GROUND_LOOT:
		return 0
	if hit_kind == HIT_DROPPED_BAG:
		return 1
	if hit_kind in [HIT_ACTOR, HIT_NPC, HIT_ANIMAL]:
		return 2
	if hit_kind == HIT_GATHER_NODE:
		return 3
	if hit_kind == HIT_SCENE_OBJECT:
		return 4
	if hit_kind == HIT_VEHICLE:
		return 5
	return 99


func resolve_wheel(wheel_button_index: int, zoom_modifier: bool, menu_open: bool) -> Dictionary:
	if wheel_button_index != MOUSE_BUTTON_WHEEL_UP and wheel_button_index != MOUSE_BUTTON_WHEEL_DOWN:
		return _emit_result(_rejected("UNSUPPORTED_WHEEL_BUTTON"))
	var direction: int = -1 if wheel_button_index == MOUSE_BUTTON_WHEEL_UP else 1
	if menu_open:
		return _emit_result({
			"status": "PASS",
			"intent": "MENU_SCROLL",
			"scroll_direction": direction,
			"consumes_world_input": true,
			"authority": AUTHORITY,
		})
	if zoom_modifier:
		return _emit_result({
			"status": "PASS",
			"intent": "CAMERA_ZOOM",
			"zoom_steps": direction,
			"consumes_weapon_cycle": true,
			"authority": AUTHORITY,
		})
	return _emit_result({
		"status": "PASS",
		"intent": "WEAPON_QUICK_SLOT_CYCLE",
		"slot_delta": direction,
		"quick_slot_count": 2,
		"implementation_stage": "AUTHORITATIVE_SYSTEM_PRESERVED",
		"consumes_camera_zoom": true,
		"authority": AUTHORITY,
	})


func resolve_weapon_slot_key(slot_index: int) -> Dictionary:
	if slot_index not in [1, 2]:
		return _emit_result(_rejected("WEAPON_SLOT_KEY_MUST_BE_1_OR_2"))
	return _emit_result({
		"status": "PASS",
		"intent": "WEAPON_QUICK_SLOT_ACTIVATE",
		"slot": slot_index,
		"quick_slot_count": 2,
		"simultaneously_active_weapons": 1,
		"authoritative_result_required": true,
		"implementation_stage": "AUTHORITATIVE_SYSTEM_PRESERVED",
		"authority": AUTHORITY,
	})


func _resolve_ground_loot(
	button: String,
	target_ref: String,
	world_position: Vector3,
	physical_distance_m: float,
	reachable: bool,
	ground_loot_settled: bool
) -> Dictionary:
	if target_ref.is_empty():
		return _rejected("EMPTY_TARGET_REF")
	if not ground_loot_settled:
		return {
			"status": "REJECTED",
			"reason": "GROUND_LOOT_NOT_SETTLED",
			"target_ref": target_ref,
			"target_kind": HIT_GROUND_LOOT,
			"cursor": "BLOCKED",
			"button": button,
			"authority": AUTHORITY,
		}
	if not reachable:
		return {
			"status": "REJECTED",
			"reason": "GROUND_LOOT_UNREACHABLE",
			"target_ref": target_ref,
			"target_kind": HIT_GROUND_LOOT,
			"cursor": "BLOCKED",
			"button": button,
			"authority": AUTHORITY,
		}
	if physical_distance_m <= PICKUP_RADIUS_M:
		return {
			"status": "PASS",
			"intent": "PICKUP",
			"target_ref": target_ref,
			"target_kind": HIT_GROUND_LOOT,
			"physical_distance_m": physical_distance_m,
			"max_pickup_distance_m": PICKUP_RADIUS_M,
			"cursor": "PICKUP",
			"interrupts_action": false,
			"button": button,
			"authority": AUTHORITY,
		}
	return {
		"status": "PASS",
		"intent": "APPROACH_PICKUP",
		"target_ref": target_ref,
		"target_kind": HIT_GROUND_LOOT,
		"world_position": world_position,
		"physical_distance_m": physical_distance_m,
		"arrival_distance_m": PICKUP_RADIUS_M,
		"requires_path": true,
		"cursor": "PICKUP",
		"button": button,
		"authority": AUTHORITY,
	}


func _candidate_less(left: Dictionary, right: Dictionary) -> bool:
	var left_screen_distance: float = float(left.get("screen_distance_px", INF))
	var right_screen_distance: float = float(right.get("screen_distance_px", INF))
	if absf(left_screen_distance - right_screen_distance) > SCREEN_DISTANCE_DEPTH_TIE_EPSILON_PX:
		return left_screen_distance < right_screen_distance
	var left_depth: float = float(left.get("depth_m", INF))
	var right_depth: float = float(right.get("depth_m", INF))
	if not is_equal_approx(left_depth, right_depth):
		return left_depth < right_depth
	var left_priority: int = semantic_priority(str(left.get("target_kind", "")))
	var right_priority: int = semantic_priority(str(right.get("target_kind", "")))
	if left_priority != right_priority:
		return left_priority < right_priority
	return str(left.get("target_ref", "")) < str(right.get("target_ref", ""))


func _ground_point(world_position: Vector3) -> Dictionary:
	return {
		"iso_x_m": world_position.x,
		"iso_y_m": world_position.z,
		"altitude_m": world_position.y,
	}


func _button_name(button_index: int) -> String:
	if button_index == MOUSE_BUTTON_LEFT:
		return "LEFT"
	if button_index == MOUSE_BUTTON_RIGHT:
		return "RIGHT"
	return ""


func _emit_result(result: Dictionary) -> Dictionary:
	pointer_intent_resolved.emit(result.duplicate(true))
	return result


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
