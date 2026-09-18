extends Area3D
class_name AndromedaWaterVolume

## Stage16B B04 water detection/presentation only.
## Final stamina, exhaustion, defeat, TTL and inventory outcomes stay authoritative upstream.

const AUTHORITY := "GODOT_WATER_DETECTION_PRESENTATION_ONLY"
const SHALLOW_DEPTH_M_CANDIDATE := 0.65
const VEHICLE_MAX_WADE_DEPTH_M_CANDIDATE := 0.55
const LAYER_WATER_VOLUME := 2048
const WATER_ITEM_MASK := 16 | 4096

@export var volume_ref: String = "WATER-B04-PLACEHOLDER"
@export var volume_size: Vector3 = Vector3(6.0, 0.8, 4.0)
@export_range(0.0, 8.0, 0.01) var depth_m: float = 0.4
@export_range(0.0, 8.0, 0.01) var current_speed_mps: float = 0.0
@export var current_direction: Vector3 = Vector3.RIGHT
@export var swimmable: bool = true
@export var ordinary_vehicle_allowed: bool = true
@export var under_bridge: bool = false

@onready var water_visual: MeshInstance3D = $WaterVisual
@onready var volume_shape: CollisionShape3D = $CollisionShape3D

var _tracked_bodies: Dictionary = {}


func _ready() -> void:
	collision_layer = LAYER_WATER_VOLUME
	collision_mask = WATER_ITEM_MASK
	monitoring = true
	monitorable = true
	_configure_geometry()
	set_meta("volume_ref", volume_ref)
	set_meta("water_class", water_class())
	set_meta("gameplay_authority", false)
	if not body_entered.is_connected(_on_body_entered):
		body_entered.connect(_on_body_entered)
	if not body_exited.is_connected(_on_body_exited):
		body_exited.connect(_on_body_exited)


func _physics_process(_delta: float) -> void:
	# A body may be instantiated already overlapping the volume. Polling the overlap set
	# closes that deterministic initialization gap while signals handle ordinary entry/exit.
	var current_overlaps: Dictionary = {}
	for body: Node3D in get_overlapping_bodies():
		current_overlaps[body.get_instance_id()] = body
		if not _tracked_bodies.has(body.get_instance_id()):
			_notify_body_entered(body)
	for instance_id: Variant in _tracked_bodies.keys():
		if current_overlaps.has(instance_id):
			continue
		var previous_body := _tracked_bodies[instance_id] as Node3D
		if is_instance_valid(previous_body):
			_notify_body_exited(previous_body)
	_tracked_bodies = current_overlaps


func water_class() -> String:
	return "SHALLOW" if depth_m <= SHALLOW_DEPTH_M_CANDIDATE else "DEEP"


func current_class() -> String:
	if current_speed_mps < 0.45:
		return "CALM"
	if current_speed_mps < 1.15:
		return "CURRENT"
	return "STRONG_CURRENT"


func current_factor_candidate() -> float:
	match current_class():
		"CURRENT":
			return 1.35
		"STRONG_CURRENT":
			return 1.85
		_:
			return 1.0


func surface_world_y() -> float:
	return global_position.y + volume_size.y * 0.5


func contains_world_point(world_position: Vector3) -> bool:
	var local_point: Vector3 = to_local(world_position)
	var half: Vector3 = volume_size * 0.5
	return (
		absf(local_point.x) <= half.x
		and absf(local_point.y) <= half.y + maxf(depth_m, 0.5)
		and absf(local_point.z) <= half.z
	)


func sample_for_actor(actor_kind: String) -> Dictionary:
	var normalized_kind: String = actor_kind.to_upper().strip_edges()
	var shallow: bool = water_class() == "SHALLOW"
	var is_living: bool = normalized_kind in ["PLAYER", "NPC", "ANIMAL"]
	var allowed: bool = false
	var mode: String = "BLOCKED"
	var block_reason: String = "UNSUPPORTED_ACTOR_KIND"
	if is_living:
		allowed = shallow or swimmable
		mode = "WADE" if shallow else "SWIM"
		block_reason = "DEEP_WATER_NOT_SWIMMABLE" if not allowed else ""
	elif normalized_kind == "VEHICLE":
		allowed = shallow and ordinary_vehicle_allowed and depth_m <= VEHICLE_MAX_WADE_DEPTH_M_CANDIDATE
		mode = "WADE_VEHICLE" if allowed else "BLOCKED"
		block_reason = "VEHICLE_WATER_TOO_DEEP" if not allowed else ""
	var result := {
		"status": "PASS" if allowed else "BLOCKED",
		"reason": block_reason,
		"volume_ref": volume_ref,
		"actor_kind": normalized_kind,
		"water_class": water_class(),
		"mode": mode,
		"depth_m": depth_m,
		"current_speed_mps": current_speed_mps,
		"current_direction": normalized_current_direction(),
		"current_class": current_class(),
		"current_factor_candidate": current_factor_candidate(),
		"under_bridge": under_bridge,
		"swimmable": swimmable,
		"ordinary_vehicle_allowed": allowed if normalized_kind == "VEHICLE" else ordinary_vehicle_allowed,
		"living_stamina_input_detected": is_living and allowed,
		"vehicle_stamina_cost": null,
		"vehicle_traction_speed_penalty_input": normalized_kind == "VEHICLE" and allowed,
		"authoritative_stamina_applied": false,
		"authoritative_death_applied": false,
		"requires_authoritative_snapshot": is_living and allowed,
		"body_balance_mechanic": false,
		"authority": AUTHORITY,
	}
	if normalized_kind == "VEHICLE":
		result["vehicle_stamina_cost"] = 0.0
	return result


func normalized_current_direction() -> Vector3:
	var horizontal := Vector3(current_direction.x, 0.0, current_direction.z)
	if horizontal.length_squared() <= 0.000001:
		return Vector3.ZERO
	return horizontal.normalized()


func presentation_current_displacement(delta_s: float) -> Vector3:
	var safe_delta: float = clampf(delta_s, 0.0, 0.1)
	var displacement: Vector3 = normalized_current_direction() * current_speed_mps * safe_delta
	return displacement.limit_length(0.08)


func contract_snapshot() -> Dictionary:
	return {
		"volume_ref": volume_ref,
		"water_class": water_class(),
		"depth_m": depth_m,
		"current_class": current_class(),
		"current_direction": normalized_current_direction(),
		"swimmable": swimmable,
		"ordinary_vehicle_allowed": ordinary_vehicle_allowed,
		"under_bridge": under_bridge,
		"shallow_depth_m_candidate": SHALLOW_DEPTH_M_CANDIDATE,
		"vehicle_max_wade_depth_m_candidate": VEHICLE_MAX_WADE_DEPTH_M_CANDIDATE,
		"smooth_current_displacement_cap_m_per_tick": 0.08,
		"gameplay_authority_in_gdscript": false,
		"authority": AUTHORITY,
	}


func _configure_geometry() -> void:
	water_visual.mesh = water_visual.mesh.duplicate(true)
	volume_shape.shape = volume_shape.shape.duplicate(true)
	var box_mesh := water_visual.mesh as BoxMesh
	if box_mesh != null:
		box_mesh.size = volume_size
	var box_shape := volume_shape.shape as BoxShape3D
	if box_shape != null:
		box_shape.size = volume_size


func _on_body_entered(body: Node3D) -> void:
	_tracked_bodies[body.get_instance_id()] = body
	_notify_body_entered(body)


func _notify_body_entered(body: Node3D) -> void:
	var presenter: Node = body.get_node_or_null("WaterWorldItemPresenter")
	if presenter != null and presenter.has_method("enter_water"):
		presenter.call("enter_water", self)


func _on_body_exited(body: Node3D) -> void:
	_tracked_bodies.erase(body.get_instance_id())
	_notify_body_exited(body)


func _notify_body_exited(body: Node3D) -> void:
	var presenter: Node = body.get_node_or_null("WaterWorldItemPresenter")
	if presenter != null and presenter.has_method("exit_water"):
		presenter.call("exit_water", self)
