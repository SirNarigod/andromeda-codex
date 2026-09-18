extends StaticBody3D
class_name AndromedaCameraOccluder

## Presentation-only material fade for geometry between the camera and Player.
## Original material overrides and collision settings are restored exactly.

const AUTHORITY := "GODOT_CAMERA_OCCLUSION_PRESENTATION_ONLY"

@export var occluder_ref: String = "CAMERA-OCCLUDER-PLACEHOLDER"
@export_enum("TREE", "WALL", "TALL_OBJECT") var occluder_kind: String = "TALL_OBJECT"
@export_range(0.05, 1.0, 0.01) var fade_target_alpha: float = 0.20
@export_range(0.01, 1.0, 0.01) var fade_duration_s: float = 0.16
@export_range(0.0, 0.5, 0.01) var release_hold_s: float = 0.06
@export var visual_root_path: NodePath = ^"VisualRoot"

var _meshes: Array[MeshInstance3D] = []
var _original_material_overrides: Dictionary = {}
var _fade_materials: Dictionary = {}
var _original_alphas: Dictionary = {}
var _occlusion_requested: bool = false
var _release_remaining_s: float = 0.0
var _fade_fraction: float = 0.0
var _fade_entry_count: int = 0
var _restore_count: int = 0
var _request_transition_count: int = 0
var _initial_collision_layer: int = 0
var _initial_collision_mask: int = 0


func _ready() -> void:
	_initial_collision_layer = collision_layer
	_initial_collision_mask = collision_mask
	_collect_meshes()
	set_physics_process(false)


func _physics_process(delta: float) -> void:
	if not _occlusion_requested and _release_remaining_s > 0.0:
		_release_remaining_s = maxf(0.0, _release_remaining_s - delta)
	var should_fade: bool = _occlusion_requested or _release_remaining_s > 0.0
	var target_fraction: float = 1.0 if should_fade else 0.0
	var speed: float = 1.0 / maxf(0.001, fade_duration_s)
	_fade_fraction = move_toward(_fade_fraction, target_fraction, speed * delta)
	_apply_fade_fraction()
	if not should_fade and is_zero_approx(_fade_fraction):
		_restore_original_materials()
		set_physics_process(false)


func request_camera_occlusion(occluded: bool, requested_alpha: float = -1.0) -> Dictionary:
	if requested_alpha >= 0.0:
		if is_nan(requested_alpha) or is_inf(requested_alpha):
			return _rejected("INVALID_FADE_ALPHA")
		fade_target_alpha = clampf(requested_alpha, 0.05, 1.0)
	if occluded and _fade_materials.is_empty():
		_prepare_fade_materials()
		if _fade_materials.is_empty():
			return _rejected("NO_SUPPORTED_VISUAL_MATERIAL")
	if occluded != _occlusion_requested:
		_request_transition_count += 1
		if occluded:
			_fade_entry_count += 1
	_occlusion_requested = occluded
	if occluded:
		_release_remaining_s = release_hold_s
	else:
		_release_remaining_s = maxf(_release_remaining_s, release_hold_s)
	set_physics_process(true)
	return {
		"status": "PASS",
		"occluder_ref": occluder_ref,
		"occluder_kind": occluder_kind,
		"occluded": occluded,
		"target_alpha": fade_target_alpha,
		"collision_changed": false,
		"targeting_changed": false,
		"authority": AUTHORITY,
	}


func force_restore_now() -> Dictionary:
	_occlusion_requested = false
	_release_remaining_s = 0.0
	_fade_fraction = 0.0
	_restore_original_materials()
	set_physics_process(false)
	return {
		"status": "PASS",
		"occluder_ref": occluder_ref,
		"material_state_restored": material_state_restored(),
		"collision_changed": false,
		"authority": AUTHORITY,
	}


func fade_fraction() -> float:
	return _fade_fraction


func current_visual_alpha() -> float:
	for material_value: Variant in _fade_materials.values():
		var material := material_value as StandardMaterial3D
		if material != null:
			return material.albedo_color.a
	for mesh: MeshInstance3D in _meshes:
		var source: Material = _source_material(mesh)
		if source is StandardMaterial3D:
			return (source as StandardMaterial3D).albedo_color.a
	return 1.0


func material_state_restored() -> bool:
	return _fade_materials.is_empty() and is_zero_approx(_fade_fraction)


func collision_state_unchanged() -> bool:
	return collision_layer == _initial_collision_layer and collision_mask == _initial_collision_mask


func contract_snapshot() -> Dictionary:
	return {
		"occluder_ref": occluder_ref,
		"occluder_kind": occluder_kind,
		"material_fade_execution": true,
		"fade_target_alpha": fade_target_alpha,
		"fade_duration_s": fade_duration_s,
		"release_hold_s": release_hold_s,
		"mesh_count": _meshes.size(),
		"fade_fraction": _fade_fraction,
		"current_visual_alpha": current_visual_alpha(),
		"occlusion_requested": _occlusion_requested,
		"material_state_restored": material_state_restored(),
		"fade_entry_count": _fade_entry_count,
		"restore_count": _restore_count,
		"request_transition_count": _request_transition_count,
		"collision_state_unchanged": collision_state_unchanged(),
		"collision_layer": collision_layer,
		"collision_mask": collision_mask,
		"collision_mutation": false,
		"targeting_mutation": false,
		"raycast_mutation": false,
		"navigation_mutation": false,
		"reduced_motion_affects_fade": false,
		"gameplay_authority": false,
		"authority": AUTHORITY,
	}


func _collect_meshes() -> void:
	_meshes.clear()
	var visual_root: Node = get_node_or_null(visual_root_path)
	if visual_root == null:
		visual_root = self
	if visual_root is MeshInstance3D:
		_meshes.append(visual_root as MeshInstance3D)
	for child: Node in visual_root.find_children("*", "MeshInstance3D", true, false):
		var mesh := child as MeshInstance3D
		if mesh != null and not _meshes.has(mesh):
			_meshes.append(mesh)


func _prepare_fade_materials() -> void:
	_original_material_overrides.clear()
	_fade_materials.clear()
	_original_alphas.clear()
	for mesh: MeshInstance3D in _meshes:
		var source: Material = _source_material(mesh)
		if not source is StandardMaterial3D:
			continue
		var duplicated := source.duplicate(true) as StandardMaterial3D
		if duplicated == null:
			continue
		var mesh_id: int = mesh.get_instance_id()
		_original_material_overrides[mesh_id] = mesh.material_override
		_original_alphas[mesh_id] = (source as StandardMaterial3D).albedo_color.a
		duplicated.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		mesh.material_override = duplicated
		_fade_materials[mesh_id] = duplicated
	_apply_fade_fraction()


func _apply_fade_fraction() -> void:
	for mesh_id_value: Variant in _fade_materials.keys():
		var mesh_id: int = int(mesh_id_value)
		var material := _fade_materials.get(mesh_id) as StandardMaterial3D
		if material == null:
			continue
		var color: Color = material.albedo_color
		var original_alpha: float = float(_original_alphas.get(mesh_id, 1.0))
		color.a = lerpf(original_alpha, minf(original_alpha, fade_target_alpha), _fade_fraction)
		material.albedo_color = color


func _restore_original_materials() -> void:
	if _original_material_overrides.is_empty() and _fade_materials.is_empty():
		return
	for mesh_id_value: Variant in _original_material_overrides.keys():
		var mesh_id: int = int(mesh_id_value)
		var mesh := instance_from_id(mesh_id) as MeshInstance3D
		if mesh == null:
			continue
		mesh.material_override = _original_material_overrides.get(mesh_id) as Material
	_original_material_overrides.clear()
	_fade_materials.clear()
	_original_alphas.clear()
	_restore_count += 1


func _source_material(mesh: MeshInstance3D) -> Material:
	if mesh.material_override != null:
		return mesh.material_override
	if mesh.mesh != null and mesh.mesh.get_surface_count() > 0:
		return mesh.get_active_material(0)
	return null


func _rejected(reason: String) -> Dictionary:
	return {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
