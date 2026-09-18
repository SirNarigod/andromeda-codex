extends Control
class_name AndromedaCraftingPanel

## Runtime crafting presentation for G16B-23. Recipe data and availability are
## external projections. The explicit action only emits a client intent.

signal craft_intent_requested(workstation_ref: String, recipe_ref: String, quantity: int)
signal close_requested()

const AUTHORITY := "GODOT_CRAFTING_UI_PRESENTATION_ONLY"
const SCROLL_STEP_PX := 64

@onready var _scroll: ScrollContainer = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll
@onready var _workstation_label: Label = $Backdrop/RoundedWhitePanel/Margin/Layout/Workstation
@onready var _recipe_label: Label = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/RecipeName
@onready var _ingredients: VBoxContainer = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/Ingredients
@onready var _quantity: SpinBox = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/QuantityRow/Quantity
@onready var _output_label: Label = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/OutputProjection
@onready var _availability_label: Label = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/Availability
@onready var _craft_button: Button = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/CraftAction
@onready var _close_button: Button = $Backdrop/RoundedWhitePanel/Margin/Layout/Header/Close

var _workstation_ref: String = ""
var _expected_session_ref: String = ""
var _recipe_projection: Dictionary = {}
var _projection_source: String = ""
var _last_sequence: int = -1
var _last_intent: Dictionary = {}
var _externally_available: bool = false


func _ready() -> void:
	_craft_button.pressed.connect(_on_craft_pressed)
	_close_button.pressed.connect(_on_close_pressed)
	set_open(false)
	_refresh_action_state()


func bind_expected_session(session_ref: String) -> Dictionary:
	_expected_session_ref = session_ref.strip_edges()
	return {
		"status": "PASS",
		"session_ref_bound": not _expected_session_ref.is_empty(),
		"session_identity_decided_locally": false,
		"authority": AUTHORITY,
	}


func open_for_workstation(workstation_ref: String) -> Dictionary:
	_workstation_ref = workstation_ref.strip_edges()
	if _workstation_ref.is_empty():
		return _rejected("WORKSTATION_REF_REQUIRED")
	_workstation_label.text = "Estação de produção  ·  %s" % _workstation_ref
	set_open(true)
	return {
		"status": "PASS",
		"workstation_ref": _workstation_ref,
		"craft_executed": false,
		"authority": AUTHORITY,
	}


func set_open(value: bool) -> void:
	visible = value
	mouse_filter = Control.MOUSE_FILTER_STOP if value else Control.MOUSE_FILTER_IGNORE


func is_open() -> bool:
	return visible


func project_recipe(projection: Dictionary, externally_validated: bool) -> Dictionary:
	if not externally_validated:
		return _rejected("EXTERNAL_RECIPE_VALIDATION_REQUIRED")
	var recipe_ref: String = str(projection.get("recipe_ref", "")).strip_edges()
	var projection_source: String = str(projection.get("projection_source", "")).strip_edges()
	if recipe_ref.is_empty() or projection_source.is_empty():
		return _rejected("RECIPE_REF_AND_PROJECTION_SOURCE_REQUIRED")
	var incoming_session: String = str(projection.get("session_ref", "")).strip_edges()
	if not _expected_session_ref.is_empty() and incoming_session != _expected_session_ref:
		return _rejected("WRONG_SESSION_RECIPE_PROJECTION")
	var incoming_sequence: int = int(projection.get("sequence", 0))
	if incoming_sequence > 0 and incoming_sequence <= _last_sequence:
		return _rejected("STALE_OR_DUPLICATE_RECIPE_PROJECTION")
	var output_value: Variant = projection.get("output", {})
	if not output_value is Dictionary:
		return _rejected("MALFORMED_OUTPUT_PROJECTION")
	var projected_ingredients: Array[Dictionary] = []
	for ingredient_value: Variant in projection.get("ingredients", []):
		if ingredient_value is Dictionary:
			projected_ingredients.append((ingredient_value as Dictionary).duplicate(true))
	_recipe_projection = projection.duplicate(true)
	_recipe_projection["ingredients"] = projected_ingredients
	_projection_source = projection_source
	_externally_available = bool(projection.get("available", false))
	if incoming_sequence > 0:
		_last_sequence = incoming_sequence
	_render_projection()
	_refresh_action_state()
	return {
		"status": "PASS",
		"recipe_ref": recipe_ref,
		"ingredient_count": projected_ingredients.size(),
		"output_projected": true,
		"availability_projected_externally": true,
		"projection_source": _projection_source,
		"fixture_is_authoritative_roundtrip": false,
		"yield_calculated_locally": false,
		"inventory_mutated_locally": false,
		"craft_executed": false,
		"authority": AUTHORITY,
	}


func request_craft_intent() -> Dictionary:
	if not visible:
		return _rejected("CRAFTING_MENU_CLOSED")
	if _recipe_projection.is_empty():
		return _rejected("RECIPE_PROJECTION_REQUIRED")
	if not _externally_available:
		return _rejected("EXTERNAL_RECIPE_UNAVAILABLE")
	var quantity: int = int(_quantity.value)
	if quantity <= 0:
		return _rejected("INVALID_REQUEST_QUANTITY")
	_last_intent = {
		"status": "PASS",
		"intent": "REQUEST_CRAFT",
		"workstation_ref": _workstation_ref,
		"recipe_ref": str(_recipe_projection.get("recipe_ref", "")),
		"quantity": quantity,
		"projection_source": _projection_source,
		"transport_submitted": false,
		"craft_result_decided_locally": false,
		"ingredients_consumed_locally": false,
		"output_granted_locally": false,
		"inventory_mutated_locally": false,
		"authority": AUTHORITY,
	}
	craft_intent_requested.emit(
		_workstation_ref,
		str(_recipe_projection.get("recipe_ref", "")),
		quantity
	)
	return _last_intent.duplicate(true)


func set_request_quantity(quantity: int) -> Dictionary:
	if quantity < int(_quantity.min_value) or quantity > int(_quantity.max_value):
		return _rejected("REQUEST_QUANTITY_OUT_OF_UI_RANGE")
	_quantity.value = quantity
	return {
		"status": "PASS",
		"quantity": quantity,
		"output_quantity_recalculated": false,
		"authority": AUTHORITY,
	}


func scroll_by(direction: int) -> Dictionary:
	if not visible:
		return _rejected("CRAFTING_MENU_CLOSED")
	if direction == 0:
		return _rejected("ZERO_SCROLL_DIRECTION")
	var before: int = _scroll.scroll_vertical
	var scrollbar: VScrollBar = _scroll.get_v_scroll_bar()
	var maximum: int = maxi(0, int(round(scrollbar.max_value - scrollbar.page)))
	_scroll.scroll_vertical = clampi(before + direction * SCROLL_STEP_PX, 0, maximum)
	return {
		"status": "PASS",
		"before": before,
		"after": _scroll.scroll_vertical,
		"weapon_slot_changed": false,
		"camera_zoom_changed": false,
		"world_action_emitted": false,
		"authority": AUTHORITY,
	}


func projected_recipe() -> Dictionary:
	return _recipe_projection.duplicate(true)


func last_intent() -> Dictionary:
	return _last_intent.duplicate(true)


func ingredient_row_count() -> int:
	return _ingredients.get_child_count()


func craft_button_enabled() -> bool:
	return not _craft_button.disabled


func availability_color() -> Color:
	return _availability_label.get_theme_color("font_color")


func contract_snapshot() -> Dictionary:
	return {
		"ui_family": "WHITE_OFF_WHITE_ROUNDED_CLEAN_CONSOLE",
		"panel_color": "OFF_WHITE",
		"rounded_corners": true,
		"rounded_legible_typography": true,
		"primary_text_hex": "#6B6B6B",
		"secondary_text_hex": "#8A8A8A",
		"important_text_hex": "#D9A15F",
		"ingredients_presented": true,
		"request_quantity_presented": true,
		"output_presented": true,
		"availability_external_projection": true,
		"craft_action_separate": true,
		"recipe_authority": false,
		"yield_authority": false,
		"ingredient_consumption_authority": false,
		"inventory_authority": false,
		"stamina_authority": false,
		"craft_result_authority": false,
		"command_transport_submitted": false,
		"permanent_panel": false,
		"final_art": false,
		"copied_nintendo_or_zelda_assets": false,
		"authority": AUTHORITY,
	}


func _render_projection() -> void:
	_recipe_label.text = str(_recipe_projection.get("display_name", _recipe_projection.get("recipe_ref", "Receita externa")))
	for child: Node in _ingredients.get_children():
		_ingredients.remove_child(child)
		child.queue_free()
	for ingredient: Dictionary in _recipe_projection.get("ingredients", []):
		var row := Label.new()
		var display_name: String = str(ingredient.get("display_name", ingredient.get("item_ref", "Ingrediente externo")))
		var required_text: String = str(ingredient.get("required_display", ingredient.get("required_quantity", "?")))
		var available_text: String = str(ingredient.get("available_display", ingredient.get("available_quantity", "?")))
		row.text = "%s  ·  %s / %s" % [display_name, available_text, required_text]
		row.add_theme_color_override("font_color", Color("6b6b6b"))
		_ingredients.add_child(row)
	var output: Dictionary = _recipe_projection.get("output", {})
	var output_name: String = str(output.get("display_name", output.get("item_ref", "Output externo")))
	var output_quantity: String = str(output.get("quantity_display", output.get("quantity", "?")))
	_output_label.text = "%s  ·  quantidade projetada: %s" % [output_name, output_quantity]
	_availability_label.text = "Disponível segundo autoridade externa" if _externally_available else "Indisponível segundo autoridade externa"
	_availability_label.add_theme_color_override(
		"font_color",
		Color("d9a15f") if _externally_available else Color("8a8a8a")
	)


func _refresh_action_state() -> void:
	_craft_button.disabled = _recipe_projection.is_empty() or not _externally_available


func _on_craft_pressed() -> void:
	request_craft_intent()


func _on_close_pressed() -> void:
	close_requested.emit()


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
