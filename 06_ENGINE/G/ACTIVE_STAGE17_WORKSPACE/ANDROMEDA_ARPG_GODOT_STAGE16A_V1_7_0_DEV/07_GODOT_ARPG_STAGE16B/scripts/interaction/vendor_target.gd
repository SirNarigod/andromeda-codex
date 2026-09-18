extends AndromedaInteractionTarget
class_name AndromedaVendorTarget

## B09 vendor presentation target. Vendor identity and location come from the
## Stage13 contract; prices, stock, ownership and trade results never live here.

const AUTHORITY_B09 := "GODOT_VENDOR_TARGET_PRESENTATION_ONLY"

@export var vendor_ref: String = "SHOP-S13-91CDF9F934810A65B2"
@export var location_ref: String = "POI-002"
@export_range(0.5, 3.0, 0.05) var interaction_range_m: float = 1.35

@onready var interaction_anchor: Marker3D = $InteractionAnchor


func _ready() -> void:
	vendor_ref = vendor_ref.strip_edges()
	location_ref = location_ref.strip_edges()
	target_kind = AndromedaInputRouter.HIT_NPC
	hostile = false
	super._ready()
	set_meta("vendor_ref", vendor_ref)
	set_meta("location_ref", location_ref)
	set_meta("merchant_identity_claimed", false)


func interaction_anchor_world_position() -> Vector3:
	return interaction_anchor.global_position if interaction_anchor != null else global_position


func vendor_identity_snapshot() -> Dictionary:
	return {
		"target_ref": target_ref,
		"target_kind": target_kind,
		"vendor_ref": vendor_ref,
		"location_ref": location_ref,
		"interaction_range_m": interaction_range_m,
		"interaction_anchor": interaction_anchor_world_position(),
		"merchant_identity_claimed": false,
		"price_authority": false,
		"stock_authority": false,
		"trade_authority": false,
		"authority": AUTHORITY_B09,
	}


func contract_snapshot() -> Dictionary:
	return {
		"root_type": "CharacterBody3D",
		"target_kind": AndromedaInputRouter.HIT_NPC,
		"actor_collision_layer": 4,
		"interaction_sensor_layer": 8,
		"physical_approach_required": true,
		"click_or_approach_auto_purchases": false,
		"canonical_vendor_ref": "SHOP-S13-91CDF9F934810A65B2",
		"canonical_location_ref": "POI-002",
		"merchant_identity_claimed": false,
		"final_art": false,
		"gameplay_authority_in_gdscript": false,
		"authority": AUTHORITY_B09,
	}
