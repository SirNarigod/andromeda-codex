extends Control
class_name AndromedaInventoryPanel

## Minimal functional inventory panel: toggled with the "inventory_toggle"
## action, reads directly from the bridge's current snapshot. This is
## deliberately simpler than the full AndromedaInventoryClient projection
## pipeline (which expects an AndromedaHUDController that doesn't exist yet
## in this project) -- it exists so "I opens the inventory" actually works
## today. Wiring the real equip/unequip intents through inventory_client.gd
## is follow-up work, not done here.

@onready var _list_label: Label = $Panel/VBoxContainer/ItemList


func _ready() -> void:
	visible = false


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("inventory_toggle"):
		visible = not visible
		if visible:
			_refresh()


func _refresh() -> void:
	var bridge: AndromedaRuntimeBridge = get_node_or_null("/root/AndromedaBridge")
	if bridge == null:
		_list_label.text = "Backend indisponível."
		return
	var snapshot: Dictionary = bridge.current_snapshot()
	if snapshot.is_empty():
		_list_label.text = "Sem dados de inventário ainda (aguardando snapshot)."
		return
	var inventory: Dictionary = snapshot.get("inventory_projection", {}) as Dictionary
	if inventory.is_empty():
		_list_label.text = "Inventário vazio ou não projetado neste snapshot."
		return
	var lines: Array[String] = []
	var base_inventory: Dictionary = inventory.get("base_inventory", {}) as Dictionary
	var stacks: Array = base_inventory.get("stacks", []) as Array
	lines.append("Itens (%d/%s slots):" % [stacks.size(), str(base_inventory.get("slot_limit", "?"))])
	if stacks.is_empty():
		lines.append("  (sem itens)")
	for stack_value: Variant in stacks:
		var stack: Dictionary = stack_value as Dictionary
		lines.append("  %s  x%s" % [str(stack.get("display_name", stack.get("item_ref", "?"))), str(stack.get("quantity", "?"))])
	var bag: Dictionary = inventory.get("bag", {}) as Dictionary
	lines.append("")
	lines.append("Mochila: %s" % str(bag.get("state", "NO_BAG")))
	var economy: Dictionary = snapshot.get("economy_projection", {}) as Dictionary
	var wallet: Dictionary = economy.get("wallet", {}) as Dictionary
	if not wallet.is_empty():
		lines.append("")
		lines.append("Carteira: %s" % str(wallet))
	_list_label.text = "\n".join(lines)
