extends Control
class_name AndromedaInventoryShell

## Visual inventory/Bag shell. Contents, weight and persistence are snapshot-owned.

signal auto_pickup_visual_changed(enabled: bool)

const AUTHORITY := "GODOT_INVENTORY_SHELL_PRESENTATION_ONLY"
const BASE_SLOT_COUNT := 8
const SCROLL_STEP_PX := 64

@onready var _menu_scroll: ScrollContainer = $RoundedWhitePanel/Margin/Layout/MenuScroll
@onready var _base_grid: GridContainer = $RoundedWhitePanel/Margin/Layout/MenuScroll/Content/BaseInventory/BaseInventoryGrid
@onready var _auto_pickup_button: Button = $RoundedWhitePanel/Margin/Layout/MenuScroll/Content/AutoPickupSection/AutoPickupButton
@onready var _bag_slot_label: Label = $RoundedWhitePanel/Margin/Layout/MenuScroll/Content/BagSection/BAG_SLOT/Label
@onready var _bag_container_label: Label = $RoundedWhitePanel/Margin/Layout/MenuScroll/Content/BagSection/BagContainer/Label
@onready var _equipment_label: Label = $RoundedWhitePanel/Margin/Layout/MenuScroll/Content/EquipmentArea/Label
@onready var _carry_label: Label = $RoundedWhitePanel/Margin/Layout/MenuScroll/Content/CarryProjection
@onready var _routing_label: Label = $RoundedWhitePanel/Margin/Layout/MenuScroll/Content/RoutingProjection
@onready var _slot_one_label: Label = $RoundedWhitePanel/Margin/Layout/MenuScroll/Content/WeaponQuickSlotReference/Slot1Reference/Label
@onready var _slot_two_label: Label = $RoundedWhitePanel/Margin/Layout/MenuScroll/Content/WeaponQuickSlotReference/Slot2Reference/Label

var _auto_pickup_enabled: bool = false
var _external_projection: Dictionary = {}


func _ready() -> void:
	_auto_pickup_button.pressed.connect(_on_auto_pickup_pressed)
	set_open(false)
	_apply_auto_pickup_label()


func set_open(value: bool) -> void:
	visible = value
	mouse_filter = Control.MOUSE_FILTER_STOP if value else Control.MOUSE_FILTER_IGNORE


func is_open() -> bool:
	return visible


func scroll_by(direction: int) -> Dictionary:
	if not visible:
		return _rejected("INVENTORY_MENU_CLOSED")
	if direction == 0:
		return _rejected("ZERO_SCROLL_DIRECTION")
	var before: int = _menu_scroll.scroll_vertical
	var scrollbar: VScrollBar = _menu_scroll.get_v_scroll_bar()
	var maximum: int = maxi(0, int(round(scrollbar.max_value - scrollbar.page)))
	_menu_scroll.scroll_vertical = clampi(before + direction * SCROLL_STEP_PX, 0, maximum)
	return {
		"status": "PASS",
		"before": before,
		"after": _menu_scroll.scroll_vertical,
		"direction": direction,
		"weapon_slot_changed": false,
		"camera_zoom_changed": false,
		"authority": AUTHORITY,
	}


func set_auto_pickup_visual(enabled: bool, emit_change: bool = false) -> Dictionary:
	_auto_pickup_enabled = enabled
	_apply_auto_pickup_label()
	if emit_change:
		auto_pickup_visual_changed.emit(_auto_pickup_enabled)
	return {
		"status": "PASS",
		"enabled": _auto_pickup_enabled,
		"label": "AUTO PICKUP ON" if _auto_pickup_enabled else "AUTO PICKUP OFF",
		"remote_collection_enabled_by_ui": false,
		"persisted_by_gdscript": false,
		"authority": AUTHORITY,
	}


func auto_pickup_enabled() -> bool:
	return _auto_pickup_enabled


func project_external_state(projection: Dictionary, externally_validated: bool) -> Dictionary:
	if not externally_validated:
		return _rejected("EXTERNAL_INVENTORY_VALIDATION_REQUIRED")
	for key: String in ["base_inventory", "bag", "equipment", "weapon_loadout", "carry", "routing"]:
		if not projection.get(key) is Dictionary:
			return _rejected("INVALID_INVENTORY_PROJECTION_%s" % key.to_upper())
	_external_projection = projection.duplicate(true)
	_render_external_projection()
	return {
		"status": "PASS",
		"snapshot_sequence": int(projection.get("snapshot_sequence", -1)),
		"contents_mutated_locally": false,
		"capacity_calculated_locally": false,
		"routing_selected_locally": false,
		"authority": AUTHORITY,
	}


func external_projection() -> Dictionary:
	return _external_projection.duplicate(true)


func bag_state_label() -> String:
	return _bag_slot_label.text


func carry_projection_label() -> String:
	return _carry_label.text


func base_slot_count() -> int:
	return _base_grid.get_child_count()


func scroll_value() -> int:
	return _menu_scroll.scroll_vertical


func contract_snapshot() -> Dictionary:
	return {
		"base_inventory_reduced": true,
		"base_slot_count_placeholder": BASE_SLOT_COUNT,
		"bag_slot_present": has_node("RoundedWhitePanel/Margin/Layout/MenuScroll/Content/BagSection/BAG_SLOT"),
		"bag_container_present": has_node("RoundedWhitePanel/Margin/Layout/MenuScroll/Content/BagSection/BagContainer"),
		"weapon_quick_slot_references": [1, 2],
		"white_rounded_language": true,
		"authoritative_contents_in_gdscript": false,
		"authoritative_weight_in_gdscript": false,
		"authoritative_capacity_in_gdscript": false,
		"authoritative_stack_in_gdscript": false,
		"authoritative_owner_routing_in_gdscript": false,
		"bag_states_projected": ["NO_BAG", "BAG_EQUIPPED"],
		"equipment_is_external_projection": true,
		"exact_weapon_quick_slot_count": 2,
		"simultaneously_active_weapons": 1,
		"authoritative_death_policy_in_gdscript": false,
		"save_reload_logic": false,
		"dropped_bag_logic": false,
		"authority": AUTHORITY,
	}


func _on_auto_pickup_pressed() -> void:
	set_auto_pickup_visual(not _auto_pickup_enabled, true)


func _apply_auto_pickup_label() -> void:
	_auto_pickup_button.text = "AUTO PICKUP  ON" if _auto_pickup_enabled else "AUTO PICKUP  OFF"
	_auto_pickup_button.add_theme_color_override(
		"font_color",
		Color("d9a15f") if _auto_pickup_enabled else Color("6b6b6b")
	)


func _render_external_projection() -> void:
	var base: Dictionary = _external_projection.get("base_inventory", {})
	var base_stacks: Array = base.get("stacks", [])
	for index: int in range(_base_grid.get_child_count()):
		var slot := _base_grid.get_child(index) as PanelContainer
		var label := slot.get_node_or_null("Label") as Label
		if label == null:
			continue
		if index >= base_stacks.size() or not base_stacks[index] is Dictionary:
			label.text = "—"
			continue
		var stack: Dictionary = base_stacks[index]
		label.text = "%s  ×%s" % [str(stack.get("item_ref", "Item")), str(stack.get("quantity", "?"))]
	var bag: Dictionary = _external_projection.get("bag", {})
	var bag_state: String = str(bag.get("state", "NO_BAG"))
	_bag_slot_label.text = "BAG_SLOT\n%s" % bag_state
	var contents: Array = bag.get("contents", [])
	_bag_container_label.text = "Container da Bolsa\n%s · %d projeções externas" % [
		str(bag.get("bag_ref", "sem Bolsa")),
		contents.size(),
	]
	var equipment: Dictionary = _external_projection.get("equipment", {})
	var equipment_slots: Dictionary = equipment.get("slots", {})
	_equipment_label.text = "Equipamento  ·  %d slots projetados externamente" % equipment_slots.size()
	var carry: Dictionary = _external_projection.get("carry", {})
	_carry_label.text = "Carga externa  ·  %s/%s peso  ·  %s/%s slots" % [
		str(carry.get("current_weight", "?")),
		str(carry.get("max_weight", "?")),
		str(carry.get("used_slots", "?")),
		str(carry.get("max_slots", "?")),
	]
	var routing: Dictionary = _external_projection.get("routing", {})
	_routing_label.text = "Destino efetivo externo  ·  %s  ·  %s" % [
		str(routing.get("source", "UNKNOWN")),
		str(routing.get("effective_inventory_owner_ref", "")),
	]
	var loadout: Dictionary = _external_projection.get("weapon_loadout", {})
	var quick_slots: Array = loadout.get("quick_slots", [])
	var active_slot: int = int(loadout.get("active_slot", 1))
	_slot_one_label.text = _quick_slot_text(quick_slots, 0, active_slot)
	_slot_two_label.text = _quick_slot_text(quick_slots, 1, active_slot)


func _quick_slot_text(quick_slots: Array, index: int, active_slot: int) -> String:
	var slot_number: int = index + 1
	var item_ref: String = "vazio"
	if index < quick_slots.size() and quick_slots[index] is Dictionary:
		item_ref = str(quick_slots[index].get("item_ref", "vazio"))
	var active_text: String = "  ·  ATIVA" if active_slot == slot_number else ""
	return "Arma rápida %d  ·  %s%s" % [slot_number, item_ref, active_text]


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
