extends Node3D
class_name AndromedaIsometricCameraRig

## Fixed isometric/oblique camera contract plus B06 bounded presentation impulse.

const AUTHORITY := "GODOT_CAMERA_PRESENTATION_ONLY"

@export var yaw_degrees: float = 45.0
@export var pitch_degrees: float = 55.0
@export var default_distance_m: float = 14.0
@export var minimum_distance_m: float = 11.0
@export var maximum_distance_m: float = 18.0
@export var zoom_step_m: float = 1.0
@export var follow_half_life_s: float = 0.18
@export var micro_height_deadband_m: float = 0.12
@export var occluder_fade_alpha: float = 0.2
@export_flags_3d_physics var occluder_collision_mask: int = 256
@export_range(1, 32, 1) var maximum_occluder_hits: int = 16
@export var occlusion_target_height_m: float = 1.0
@export var maximum_presentation_impulse_m: float = 0.18
@export var presentation_impulse_duration_s: float = 0.12

@onready var camera: Camera3D = $Camera3D
@onready var occlusion_probe: RayCast3D = $OcclusionProbe

var _follow_target: Node3D
var _target_distance_m: float = 14.0
var _current_distance_m: float = 14.0
var _initialized: bool = false
var _reduced_motion: bool = false
var _impulse_strength_m: float = 0.0
var _impulse_remaining_s: float = 0.0
var _impulse_total_s: float = 0.0
var _presentation_offset_m: Vector3 = Vector3.ZERO
var _active_material_occluders: Dictionary = {}
var _last_occlusion_refs: Array[String] = []
var _occlusion_scan_count: int = 0


func _ready() -> void:
	_target_distance_m = clampf(default_distance_m, minimum_distance_m, maximum_distance_m)
	_current_distance_m = _target_distance_m
	_apply_camera_transform()


func _physics_process(delta: float) -> void:
	if _follow_target != null and is_instance_valid(_follow_target):
		_follow_position(_follow_target.global_position, delta)
	var alpha: float = _smoothing_alpha(delta)
	_current_distance_m = lerpf(_current_distance_m, _target_distance_m, alpha)
	_advance_presentation_impulse(delta)
	_apply_camera_transform()
	_update_material_occlusion()


func _exit_tree() -> void:
	_clear_material_occluders()


func set_follow_target(target: Node3D, snap_immediately: bool = false) -> void:
	_follow_target = target
	if target == null:
		return
	if snap_immediately or not _initialized:
		global_position = target.global_position
		_initialized = true


func request_zoom_steps(step_count: int) -> float:
	_target_distance_m = clampf(
		_target_distance_m + float(step_count) * zoom_step_m,
		minimum_distance_m,
		maximum_distance_m
	)
	return _target_distance_m


func camera_distance_m() -> float:
	return _current_distance_m


func target_distance_m() -> float:
	return _target_distance_m


func follow_target() -> Node3D:
	return _follow_target


func request_presentation_impulse(magnitude_m: float) -> Dictionary:
	if is_nan(magnitude_m) or is_inf(magnitude_m) or magnitude_m < 0.0:
		return {
			"status": "REJECTED",
			"reason": "INVALID_PRESENTATION_IMPULSE",
			"applied_impulse_m": 0.0,
			"authority": AUTHORITY,
		}
	if _reduced_motion or magnitude_m <= 0.0:
		_clear_presentation_impulse()
		return {
			"status": "PASS",
			"applied_impulse_m": 0.0,
			"reduced_motion": _reduced_motion,
			"gameplay_camera_changed": false,
			"authority": AUTHORITY,
		}
	_impulse_strength_m = clampf(magnitude_m, 0.0, maximum_presentation_impulse_m)
	_impulse_total_s = maxf(0.001, presentation_impulse_duration_s)
	_impulse_remaining_s = _impulse_total_s
	return {
		"status": "PASS",
		"requested_impulse_m": magnitude_m,
		"applied_impulse_m": _impulse_strength_m,
		"maximum_impulse_m": maximum_presentation_impulse_m,
		"reduced_motion": false,
		"gameplay_camera_changed": false,
		"selection_reresolved": false,
		"authority": AUTHORITY,
	}


func set_reduced_motion(enabled: bool) -> void:
	_reduced_motion = enabled
	if enabled:
		_clear_presentation_impulse()


func reduced_motion() -> bool:
	return _reduced_motion


func presentation_impulse_active() -> bool:
	return _impulse_remaining_s > 0.0 and _presentation_offset_m.length() > 0.0


func current_presentation_offset_m() -> Vector3:
	return _presentation_offset_m


func update_material_occlusion_now() -> Dictionary:
	_update_material_occlusion()
	return occlusion_runtime_snapshot()


func active_occluder_refs() -> Array[String]:
	return _last_occlusion_refs.duplicate()


func occlusion_runtime_snapshot() -> Dictionary:
	return {
		"active_occluder_count": _active_material_occluders.size(),
		"active_occluder_refs": active_occluder_refs(),
		"scan_count": _occlusion_scan_count,
		"material_fade_execution": true,
		"multiple_occluders_supported": true,
		"collision_mutation": false,
		"targeting_mutation": false,
		"selection_reresolved": false,
		"camera_impulse_changes_targeting": false,
		"reduced_motion_affects_occluder_fade": false,
		"authority": AUTHORITY,
	}


func contract_snapshot() -> Dictionary:
	return {
		"yaw_degrees": yaw_degrees,
		"pitch_degrees": pitch_degrees,
		"minimum_distance_m": minimum_distance_m,
		"maximum_distance_m": maximum_distance_m,
		"follow_half_life_s": follow_half_life_s,
		"micro_height_deadband_m": micro_height_deadband_m,
		"occluder_fade_alpha": occluder_fade_alpha,
		"occluder_collision_mask": occluder_collision_mask,
		"maximum_occluder_hits": maximum_occluder_hits,
		"maximum_presentation_impulse_m": maximum_presentation_impulse_m,
		"presentation_impulse_local_only": true,
		"presentation_impulse_rewrites_selection": false,
		"reduced_motion_supported": true,
		"free_orbit": false,
		"occlusion_probe_prepared": occlusion_probe != null and occlusion_probe.enabled,
		"material_fade_execution": true,
		"multiple_occluders_supported": true,
		"occluder_fade_changes_collision": false,
		"occluder_fade_changes_targeting": false,
		"occluder_fade_reduced_motion_dependent": false,
		"authority": AUTHORITY,
	}


func _follow_position(target_position: Vector3, delta: float) -> void:
	var alpha: float = _smoothing_alpha(delta)
	global_position.x = lerpf(global_position.x, target_position.x, alpha)
	global_position.z = lerpf(global_position.z, target_position.z, alpha)
	var height_delta: float = target_position.y - global_position.y
	if absf(height_delta) > micro_height_deadband_m:
		global_position.y = lerpf(global_position.y, target_position.y, alpha)


func _smoothing_alpha(delta: float) -> float:
	if follow_half_life_s <= 0.0:
		return 1.0
	return 1.0 - pow(0.5, delta / follow_half_life_s)


func _advance_presentation_impulse(delta: float) -> void:
	if _reduced_motion or _impulse_remaining_s <= 0.0 or _impulse_total_s <= 0.0:
		_presentation_offset_m = Vector3.ZERO
		_impulse_remaining_s = 0.0
		return
	_impulse_remaining_s = maxf(0.0, _impulse_remaining_s - delta)
	var envelope: float = _impulse_remaining_s / _impulse_total_s
	var elapsed_ratio: float = 1.0 - envelope
	var phase: float = elapsed_ratio * TAU * 3.0
	var direction := Vector3(sin(phase), sin(phase * 1.7) * 0.35, cos(phase) * 0.45).normalized()
	_presentation_offset_m = direction * _impulse_strength_m * envelope
	if _impulse_remaining_s <= 0.0:
		_clear_presentation_impulse()


func _clear_presentation_impulse() -> void:
	_impulse_strength_m = 0.0
	_impulse_remaining_s = 0.0
	_impulse_total_s = 0.0
	_presentation_offset_m = Vector3.ZERO


func _apply_camera_transform() -> void:
	if camera == null:
		return
	var yaw_radians: float = deg_to_rad(yaw_degrees)
	var pitch_radians: float = deg_to_rad(pitch_degrees)
	var horizontal_distance: float = cos(pitch_radians) * _current_distance_m
	var camera_offset := Vector3(
		sin(yaw_radians) * horizontal_distance,
		sin(pitch_radians) * _current_distance_m,
		cos(yaw_radians) * horizontal_distance
	)
	camera.position = camera_offset + _presentation_offset_m
	camera.look_at(Vector3.ZERO, Vector3.UP)
	if occlusion_probe != null:
		occlusion_probe.position = camera_offset
		occlusion_probe.target_position = -camera_offset


func _update_material_occlusion() -> void:
	if camera == null or _follow_target == null or not is_instance_valid(_follow_target):
		_clear_material_occluders()
		return
	var world: World3D = get_world_3d()
	if world == null:
		return
	_occlusion_scan_count += 1
	var from_position: Vector3 = camera.global_position
	var to_position: Vector3 = _follow_target.global_position + Vector3.UP * occlusion_target_height_m
	if from_position.distance_squared_to(to_position) <= 0.0001:
		_clear_material_occluders()
		return
	var current_occluders: Dictionary = {}
	var excluded_rids: Array[RID] = []
	var direct_space: PhysicsDirectSpaceState3D = world.direct_space_state
	for _hit_index: int in range(maximum_occluder_hits):
		var query := PhysicsRayQueryParameters3D.create(
			from_position,
			to_position,
			occluder_collision_mask,
			excluded_rids
		)
		query.collide_with_areas = false
		query.collide_with_bodies = true
		query.hit_from_inside = true
		var hit: Dictionary = direct_space.intersect_ray(query)
		if hit.is_empty():
			break
		var hit_rid: RID = hit.get("rid", RID())
		if hit_rid.is_valid():
			excluded_rids.append(hit_rid)
		var collider := hit.get("collider") as Node
		var occluder: AndromedaCameraOccluder = _resolve_material_occluder(collider)
		if occluder != null and not current_occluders.has(occluder):
			current_occluders[occluder] = true
			occluder.request_camera_occlusion(true, occluder_fade_alpha)
		if not hit_rid.is_valid():
			break
	for previous_value: Variant in _active_material_occluders.keys():
		var previous := previous_value as AndromedaCameraOccluder
		if previous != null and is_instance_valid(previous) and not current_occluders.has(previous):
			previous.request_camera_occlusion(false, occluder_fade_alpha)
	_active_material_occluders = current_occluders
	_last_occlusion_refs.clear()
	for occluder_value: Variant in _active_material_occluders.keys():
		var active := occluder_value as AndromedaCameraOccluder
		if active != null:
			_last_occlusion_refs.append(active.occluder_ref)
	_last_occlusion_refs.sort()


func _resolve_material_occluder(collider: Node) -> AndromedaCameraOccluder:
	var current: Node = collider
	while current != null:
		if current is AndromedaCameraOccluder:
			return current as AndromedaCameraOccluder
		current = current.get_parent()
	return null


func _clear_material_occluders() -> void:
	for occluder_value: Variant in _active_material_occluders.keys():
		var occluder := occluder_value as AndromedaCameraOccluder
		if occluder != null and is_instance_valid(occluder):
			occluder.request_camera_occlusion(false, occluder_fade_alpha)
	_active_material_occluders.clear()
	_last_occlusion_refs.clear()
