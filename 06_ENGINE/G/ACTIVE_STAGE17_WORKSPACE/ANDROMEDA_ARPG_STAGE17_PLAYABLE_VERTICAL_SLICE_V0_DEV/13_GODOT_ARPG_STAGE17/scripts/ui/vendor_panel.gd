extends Control
class_name AndromedaVendorPanel

## B09 vendor presentation. Every visible price, condition and result is an
## externally supplied projection. Buttons emit intents; they never mutate state.

signal quote_requested(vendor_ref: String, item_ref: String, operation: String, quantity: int)
signal execute_requested(
	quote_ref: String,
	vendor_ref: String,
	item_ref: String,
	operation: String,
	quantity: int,
	confirmation_ref: String
)
signal close_requested()

const AUTHORITY := "GODOT_VENDOR_UI_PRESENTATION_ONLY"
const SCROLL_STEP_PX := 64

@onready var _scroll: ScrollContainer = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll
@onready var _vendor_label: Label = $Backdrop/RoundedWhitePanel/Margin/Layout/VendorIdentity
@onready var _item_selector: OptionButton = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/QuoteBuilder/ItemSelector
@onready var _operation_selector: OptionButton = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/QuoteBuilder/OperationSelector
@onready var _quantity: SpinBox = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/QuoteBuilder/Quantity
@onready var _quote_button: Button = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/QuoteBuilder/RequestQuote
@onready var _quote_label: Label = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/QuoteProjection
@onready var _execute_button: Button = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/ExecuteTrade
@onready var _result_label: Label = $Backdrop/RoundedWhitePanel/Margin/Layout/BodyScroll/Content/TradeResult
@onready var _close_button: Button = $Backdrop/RoundedWhitePanel/Margin/Layout/Header/Close

var _vendor_ref: String = ""
var _target_ref: String = ""
var _stock_items: Array[Dictionary] = []
var _quote: Dictionary = {}
var _trade_result: Dictionary = {}
var _confirmation_serial: int = 0


func _ready() -> void:
	_operation_selector.add_item("BUY")
	_operation_selector.add_item("SELL")
	_quote_button.pressed.connect(_on_quote_pressed)
	_execute_button.pressed.connect(_on_execute_pressed)
	_close_button.pressed.connect(_on_close_pressed)
	set_open(false)
	_refresh_buttons()


func open_for_vendor(target_ref_value: String, vendor_ref_value: String) -> Dictionary:
	_target_ref = target_ref_value.strip_edges()
	_vendor_ref = vendor_ref_value.strip_edges()
	if _target_ref.is_empty() or _vendor_ref.is_empty():
		return _rejected("VENDOR_TARGET_AND_VENDOR_REF_REQUIRED")
	_vendor_label.text = "Serviço comercial  ·  %s" % _vendor_ref
	set_open(true)
	return {
		"status": "PASS",
		"target_ref": _target_ref,
		"vendor_ref": _vendor_ref,
		"auto_purchase": false,
		"authority": AUTHORITY,
	}


func set_open(value: bool) -> void:
	visible = value
	mouse_filter = Control.MOUSE_FILTER_STOP if value else Control.MOUSE_FILTER_IGNORE


func is_open() -> bool:
	return visible


func project_stock(items: Array[Dictionary], externally_validated: bool) -> Dictionary:
	if not externally_validated:
		return _rejected("EXTERNAL_STOCK_VALIDATION_REQUIRED")
	_stock_items = items.duplicate(true)
	_item_selector.clear()
	for item: Dictionary in _stock_items:
		var item_ref: String = str(item.get("item_ref", "")).strip_edges()
		var label: String = str(item.get("display_name", item_ref)).strip_edges()
		_item_selector.add_item(label)
		_item_selector.set_item_metadata(_item_selector.item_count - 1, item_ref)
	_quote.clear()
	_quote_label.text = "Solicite uma cotação explícita."
	_result_label.text = "Nenhuma operação executada."
	_refresh_buttons()
	return {
		"status": "PASS",
		"item_count": _stock_items.size(),
		"price_calculated_locally": false,
		"authority": AUTHORITY,
	}


func project_quote(quote: Dictionary, externally_validated: bool) -> Dictionary:
	if not externally_validated:
		return _rejected("EXTERNAL_QUOTE_VALIDATION_REQUIRED")
	_quote = quote.duplicate(true)
	var amount_text: String = str(_quote.get("total_price_display", "valor externo"))
	var currency_text: String = str(_quote.get("currency", ""))
	_quote_label.text = "Cotação recebida  ·  %s %s\nConfirme separadamente para executar." % [amount_text, currency_text]
	_result_label.text = "Aguardando confirmação do usuário."
	_refresh_buttons()
	return {
		"status": "PASS",
		"quote_ref": str(_quote.get("quote_ref", "")),
		"price_recalculated_locally": false,
		"trade_executed": false,
		"authority": AUTHORITY,
	}


func project_trade_result(result: Dictionary, externally_validated: bool) -> Dictionary:
	if not externally_validated:
		return _rejected("EXTERNAL_TRADE_RESULT_VALIDATION_REQUIRED")
	_trade_result = result.duplicate(true)
	var accepted: bool = str(_trade_result.get("result", "REJECTED")).to_upper() == "ACCEPTED"
	_result_label.text = "Operação confirmada externamente." if accepted else "Operação rejeitada externamente."
	_result_label.add_theme_color_override("font_color", Color("d9a15f") if accepted else Color("6b6b6b"))
	_refresh_buttons()
	return {
		"status": "PASS",
		"external_result": "ACCEPTED" if accepted else "REJECTED",
		"wallet_mutated_locally": false,
		"inventory_mutated_locally": false,
		"authority": AUTHORITY,
	}


func scroll_by(direction: int) -> Dictionary:
	if not visible:
		return _rejected("VENDOR_MENU_CLOSED")
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
		"authority": AUTHORITY,
	}


func selected_item_ref() -> String:
	if _item_selector.selected < 0 or _item_selector.selected >= _item_selector.item_count:
		return ""
	return str(_item_selector.get_item_metadata(_item_selector.selected)).strip_edges()


func active_vendor_ref() -> String:
	return _vendor_ref


func selected_operation() -> String:
	if _operation_selector.selected < 0:
		return ""
	return _operation_selector.get_item_text(_operation_selector.selected).strip_edges().to_upper()


func projected_quote() -> Dictionary:
	return _quote.duplicate(true)


func projected_trade_result() -> Dictionary:
	return _trade_result.duplicate(true)


func contract_snapshot() -> Dictionary:
	return {
		"flow": ["OPEN", "REQUEST_QUOTE", "PROJECT_QUOTE", "EXPLICIT_CONFIRM", "EXECUTE_TRADE", "PROJECT_RESULT"],
		"quote_and_execute_separate": true,
		"click_auto_purchase": false,
		"approach_auto_purchase": false,
		"open_auto_purchase": false,
		"quote_auto_execute": false,
		"price_authority": false,
		"wallet_authority": false,
		"inventory_authority": false,
		"ui_family": "WHITE_OFF_WHITE_ROUNDED_CLEAN_CONSOLE",
		"permanent_panel": false,
		"final_art": false,
		"authority": AUTHORITY,
	}


func _on_quote_pressed() -> void:
	var item_ref: String = selected_item_ref()
	var operation: String = selected_operation()
	if item_ref.is_empty() or operation.is_empty():
		return
	quote_requested.emit(_vendor_ref, item_ref, operation, int(_quantity.value))


func _on_execute_pressed() -> void:
	if _quote.is_empty():
		return
	_confirmation_serial += 1
	execute_requested.emit(
		str(_quote.get("quote_ref", "")),
		str(_quote.get("vendor_ref", "")),
		str(_quote.get("item_ref", "")),
		str(_quote.get("operation", "")),
		int(_quote.get("quantity", 0)),
		"B09-UI-CONFIRM-%06d" % _confirmation_serial
	)


func _on_close_pressed() -> void:
	close_requested.emit()


func _refresh_buttons() -> void:
	_quote_button.disabled = _stock_items.is_empty()
	_execute_button.disabled = _quote.is_empty() or not bool(_quote.get("active", true))


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
