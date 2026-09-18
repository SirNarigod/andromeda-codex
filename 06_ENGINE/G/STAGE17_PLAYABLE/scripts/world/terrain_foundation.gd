extends Node3D
class_name AndromedaTerrainFoundation

## Stage16B B04 terrain/collision/traversal presentation foundation.
## All coefficients are adjustable Stage16A candidates; no stamina/load outcome is authored here.

const AUTHORITY := "GODOT_TERRAIN_TRAVERSAL_DETECTION_ONLY"
const MAX_WALKABLE_SLOPE_DEG_CANDIDATE := 32.0
const MAX_STEP_HEIGHT_M_CANDIDATE := 0.35
const MICRO_RELIEF_COLLISION_FILTER_M_CANDIDATE := 0.12

const NAV_LAYER_LAND_SHALLOW := 1
const NAV_LAYER_DEEP_SWIM := 2
const NAV_LAYER_BRIDGE := 4
const LAYER_WORLD_STATIC := 1
const LAYER_WORLD_TRIGGER := 1024

const SURFACE_PROFILES := {
	"ROAD_GOOD": {"traversal_factor": 0.88, "speed_factor": 1.05, "road": true},
	"TRAIL": {"traversal_factor": 1.03, "speed_factor": 0.98, "trail": true},
	"FIRM_GROUND": {"traversal_factor": 1.0, "speed_factor": 1.0},
	"GRASS_FIELD": {"traversal_factor": 1.06, "speed_factor": 0.98, "field": true},
	"ROCKY_GROUND": {"traversal_factor": 1.18, "speed_factor": 0.92, "rock": true},
	"MUD": {"traversal_factor": 1.32, "speed_factor": 0.84, "mud": true},
}

@onready var visual_surface: Node3D = $VISUAL_SURFACE
@onready var collision_surface: Node3D = $COLLISION_SURFACE
@onready var traversal_surface: Node3D = $TRAVERSAL_SURFACE
@onready var navigation_regions: Node3D = $TRAVERSAL_SURFACE/NavigationRegions
@onready var surface_zones_root: Node3D = $TRAVERSAL_SURFACE/SurfaceZones
@onready var water_foundation: Node3D = $WATER_FOUNDATION
@onready var streaming_manager: AndromedaStreamingManager = $CELL_STREAMING

var _surface_zones: Array[Dictionary] = []
var _navigation_region_refs: Dictionary = {}
var _visual_min_height_m: float = INF
var _visual_max_height_m: float = -INF


func _ready() -> void:
	_build_visual_surface()
	_build_collision_surface()
	_build_surface_zones()
	_build_navigation_foundation()
	set_meta("gameplay_authority", false)
	set_meta("surface_separation", "VISUAL_COLLISION_TRAVERSAL")


func surface_sample(world_position: Vector3) -> Dictionary:
	for child: Node in water_foundation.get_children():
		var volume := child as AndromedaWaterVolume
		if volume != null and volume.contains_world_point(world_position):
			var water_sample: Dictionary = volume.sample_for_actor("PLAYER")
			water_sample["surface_kind"] = "WATER_%s" % volume.water_class()
			water_sample["slope_deg"] = 0.0
			water_sample["traversal_factor_candidate"] = volume.current_factor_candidate()
			water_sample["flags"] = _surface_flags("WATER")
			water_sample["requires_authoritative_traversal_resolution"] = true
			return water_sample
	var slope_deg: float = _slope_at(world_position)
	var surface_kind: String = _surface_kind_at(world_position)
	var profile: Dictionary = SURFACE_PROFILES.get(surface_kind, SURFACE_PROFILES["FIRM_GROUND"])
	var blocked: bool = slope_deg > MAX_WALKABLE_SLOPE_DEG_CANDIDATE
	return {
		"status": "BLOCKED" if blocked else "PASS",
		"reason": "SLOPE_EXCEEDS_WALKABLE_CANDIDATE" if blocked else "",
		"surface_kind": surface_kind,
		"slope_deg": slope_deg,
		"max_walkable_slope_deg_candidate": MAX_WALKABLE_SLOPE_DEG_CANDIDATE,
		"traversal_factor_candidate": float(profile.get("traversal_factor", 1.0)),
		"speed_factor_candidate": float(profile.get("speed_factor", 1.0)),
		"flags": _surface_flags(surface_kind),
		"load_input_forwarded": true,
		"authoritative_stamina_applied": false,
		"requires_authoritative_traversal_resolution": true,
		"body_balance_mechanic": false,
		"authority": AUTHORITY,
	}


func water_volume(volume_ref: String) -> AndromedaWaterVolume:
	for child: Node in water_foundation.get_children():
		var volume := child as AndromedaWaterVolume
		if volume != null and volume.volume_ref == volume_ref:
			return volume
	return null


func terrain_surface_height(world_position: Vector3) -> float:
	if _inside_xz(world_position, 12.0, 18.0, -2.0, 2.0):
		return remap(world_position.x, 12.0, 18.0, 0.0, 1.0)
	if _inside_xz(world_position, 18.0, 24.0, -2.0, 2.0):
		return remap(world_position.x, 18.0, 24.0, 1.0, 3.0)
	if _inside_xz(world_position, 24.0, 27.0, -2.0, 2.0):
		return remap(world_position.x, 24.0, 27.0, 3.0, 7.0)
	if _inside_xz(world_position, 12.0, 13.0, 6.0, 10.0):
		return remap(world_position.x, 12.0, 13.0, 0.0, 0.3)
	if _inside_xz(world_position, 13.0, 17.0, 6.0, 10.0):
		return 0.3
	return 0.0


func visual_micro_height(world_position: Vector3) -> float:
	return (
		0.045 * sin(world_position.x * 0.7) * cos(world_position.z * 0.6)
		+ 0.025 * sin((world_position.x + world_position.z) * 1.3)
	)


func navigation_path_for_capability(
	start_position: Vector3,
	target_position: Vector3,
	capability: String
) -> PackedVector3Array:
	var query := NavigationPathQueryParameters3D.new()
	query.map = get_world_3d().navigation_map
	query.start_position = start_position
	query.target_position = target_position
	query.navigation_layers = navigation_layers_for_capability(capability)
	query.pathfinding_algorithm = NavigationPathQueryParameters3D.PATHFINDING_ALGORITHM_ASTAR
	query.path_postprocessing = NavigationPathQueryParameters3D.PATH_POSTPROCESSING_CORRIDORFUNNEL
	var result := NavigationPathQueryResult3D.new()
	NavigationServer3D.query_path(query, result)
	return result.get_path()


func validate_navigation_for_capability(
	start_position: Vector3,
	target_position: Vector3,
	capability: String,
	maximum_projection_m: float = 0.75
) -> Dictionary:
	var path: PackedVector3Array = navigation_path_for_capability(start_position, target_position, capability)
	if path.is_empty():
		return {
			"status": "BLOCKED",
			"reason": "NO_NAVIGATION_PATH_FOR_CAPABILITY",
			"capability": capability,
			"authority": AUTHORITY,
		}
	var start_projection_m: float = Vector2(path[0].x, path[0].z).distance_to(Vector2(start_position.x, start_position.z))
	var final_point: Vector3 = path[path.size() - 1]
	var target_projection_m: float = Vector2(final_point.x, final_point.z).distance_to(Vector2(target_position.x, target_position.z))
	var passable: bool = start_projection_m <= maximum_projection_m and target_projection_m <= maximum_projection_m
	return {
		"status": "PASS" if passable else "BLOCKED",
		"reason": "" if passable else "CAPABILITY_SURFACE_PROJECTION_TOO_FAR",
		"capability": capability,
		"path": path,
		"path_point_count": path.size(),
		"start_projection_m": start_projection_m,
		"target_projection_m": target_projection_m,
		"maximum_projection_m": maximum_projection_m,
		"authority": AUTHORITY,
	}


func navigation_layers_for_capability(capability: String) -> int:
	match capability.to_upper().strip_edges():
		"LIVING_SWIMMER":
			return NAV_LAYER_LAND_SHALLOW | NAV_LAYER_DEEP_SWIM | NAV_LAYER_BRIDGE
		"SWIM_ONLY":
			return NAV_LAYER_DEEP_SWIM
		"BRIDGE_ONLY":
			return NAV_LAYER_BRIDGE
		"VEHICLE", "NON_SWIMMER":
			return NAV_LAYER_LAND_SHALLOW | NAV_LAYER_BRIDGE
		_:
			return NAV_LAYER_LAND_SHALLOW


func navigation_region_count() -> int:
	return _navigation_region_refs.size()


func navigation_region_polygon_count() -> int:
	var polygon_count: int = 0
	for value: Variant in _navigation_region_refs.values():
		var region := value as NavigationRegion3D
		if region != null and region.navigation_mesh != null:
			polygon_count += region.navigation_mesh.get_polygon_count()
	return polygon_count


func visual_height_range() -> Vector2:
	return Vector2(_visual_min_height_m, _visual_max_height_m)


func collision_filter_contract() -> Dictionary:
	return {
		"visual_micro_relief_max_abs_m": maxf(absf(_visual_min_height_m), absf(_visual_max_height_m)),
		"collision_micro_relief_m": 0.0,
		"micro_relief_collision_filter_m_candidate": MICRO_RELIEF_COLLISION_FILTER_M_CANDIDATE,
		"max_step_height_m_candidate": MAX_STEP_HEIGHT_M_CANDIDATE,
		"implemented_small_step_height_m": 0.3,
		"step_collision_transition": "FILTERED_RAMP",
		"body_balance_mechanic": false,
		"authority": AUTHORITY,
	}


func contract_snapshot() -> Dictionary:
	return {
		"status": "PASS",
		"nodes": {
			"visual_surface": visual_surface.name,
			"collision_surface": collision_surface.name,
			"traversal_surface": traversal_surface.name,
			"water_foundation": water_foundation.name,
			"cell_streaming": streaming_manager.name,
		},
		"surfaces_separated": (
			visual_surface != collision_surface
			and collision_surface != traversal_surface
			and visual_surface != traversal_surface
		),
		"max_walkable_slope_deg_candidate": MAX_WALKABLE_SLOPE_DEG_CANDIDATE,
		"max_step_height_m_candidate": MAX_STEP_HEIGHT_M_CANDIDATE,
		"micro_relief_collision_filter_m_candidate": MICRO_RELIEF_COLLISION_FILTER_M_CANDIDATE,
		"navigation_layers": {
			"LAND_SHALLOW": NAV_LAYER_LAND_SHALLOW,
			"DEEP_SWIM": NAV_LAYER_DEEP_SWIM,
			"BRIDGE": NAV_LAYER_BRIDGE,
		},
		"visual_final_art": false,
		"body_balance_mechanic": false,
		"gameplay_authority_in_gdscript": false,
		"backend_substitute": false,
		"authority": AUTHORITY,
	}


func _build_visual_surface() -> void:
	var macro_visual := MeshInstance3D.new()
	macro_visual.name = "MacroTerrainVisual"
	macro_visual.mesh = _build_micro_relief_mesh()
	macro_visual.material_override = _material(Color(0.54, 0.58, 0.51, 1.0), 1.0)
	visual_surface.add_child(macro_visual)
	_add_box_visual("RoadVisual", Vector3(-7.0, 0.015, -2.0), Vector3(8.0, 0.03, 2.0), Color(0.62, 0.61, 0.56, 1.0))
	_add_box_visual("RockyVisual", Vector3(-8.0, 0.018, 8.0), Vector3(6.0, 0.035, 4.0), Color(0.46, 0.48, 0.46, 1.0))
	_add_box_visual("MudVisual", Vector3(8.0, 0.016, 8.0), Vector3(6.0, 0.032, 4.0), Color(0.42, 0.34, 0.27, 1.0))
	_add_ramp_visual_x("GentleSlopeVisual", 12.0, 18.0, -2.0, 2.0, 0.0, 1.0, Color(0.57, 0.59, 0.50, 1.0))
	_add_ramp_visual_x("ModerateSlopeVisual", 18.0, 24.0, -2.0, 2.0, 1.0, 3.0, Color(0.54, 0.55, 0.47, 1.0))
	_add_ramp_visual_x("BlockedSlopeVisual", 24.0, 27.0, -2.0, 2.0, 3.0, 7.0, Color(0.43, 0.44, 0.43, 1.0))
	_add_ramp_visual_x("SmallStepFilteredVisual", 12.0, 13.0, 6.0, 10.0, 0.0, 0.3, Color(0.60, 0.59, 0.51, 1.0))
	_add_box_visual("SmallStepPlatformVisual", Vector3(15.0, 0.15, 8.0), Vector3(4.0, 0.3, 4.0), Color(0.60, 0.59, 0.51, 1.0))
	_build_bridge_visual()
	_build_micro_stone_placeholders()


func _build_collision_surface() -> void:
	_add_box_collision("StableMacroCollision", Vector3(0.0, -0.25, 0.0), Vector3(24.0, 0.5, 24.0))
	_add_ramp_collision_x("GentleSlopeCollision", 12.0, 18.0, -2.0, 2.0, 0.0, 1.0)
	_add_ramp_collision_x("ModerateSlopeCollision", 18.0, 24.0, -2.0, 2.0, 1.0, 3.0)
	_add_ramp_collision_x("BlockedSlopeCollision", 24.0, 27.0, -2.0, 2.0, 3.0, 7.0)
	_add_ramp_collision_x("SmallStepFilteredCollision", 12.0, 13.0, 6.0, 10.0, 0.0, 0.3)
	_add_box_collision("SmallStepPlatformCollision", Vector3(15.0, 0.15, 8.0), Vector3(4.0, 0.3, 4.0))
	for bed: Dictionary in [
		{"name": "ShallowCalmBed", "center": Vector3(32.0, -0.25, -10.0), "size": Vector3(6.0, 0.5, 4.0)},
		{"name": "ShallowWeakBed", "center": Vector3(40.0, -0.25, -10.0), "size": Vector3(6.0, 0.5, 4.0)},
		{"name": "ShallowStrongBed", "center": Vector3(48.0, -0.25, -10.0), "size": Vector3(6.0, 0.5, 4.0)},
		{"name": "DeepWaterBed", "center": Vector3(56.0, -1.85, -10.0), "size": Vector3(6.0, 0.5, 4.0)},
		{"name": "UnderBridgeBed", "center": Vector3(38.0, -0.25, 10.0), "size": Vector3(12.0, 0.5, 4.0)},
	]:
		_add_box_collision(str(bed["name"]), bed["center"], bed["size"])
	_build_bridge_collision()


func _build_surface_zones() -> void:
	_register_surface_zone("ROAD_GOOD", Rect2(-11.0, -3.0, 8.0, 2.0))
	_register_surface_zone("ROCKY_GROUND", Rect2(-11.0, 6.0, 6.0, 4.0))
	_register_surface_zone("MUD", Rect2(5.0, 6.0, 6.0, 4.0))
	_register_surface_zone("GRASS_FIELD", Rect2(-11.0, 1.0, 8.0, 3.0))


func _build_navigation_foundation() -> void:
	_add_navigation_slope_x("GentleSlopeNavigation", 12.0, 18.0, -2.0, 2.0, 0.0, 1.0, NAV_LAYER_LAND_SHALLOW)
	_add_navigation_slope_x("ModerateSlopeNavigation", 18.0, 24.0, -2.0, 2.0, 1.0, 3.0, NAV_LAYER_LAND_SHALLOW)
	_add_navigation_slope_x("SmallStepTransitionNavigation", 12.0, 13.0, 6.0, 10.0, 0.0, 0.3, NAV_LAYER_LAND_SHALLOW)
	_add_navigation_quad("SmallStepPlatformNavigation", 13.0, 17.0, 6.0, 10.0, 0.3, NAV_LAYER_LAND_SHALLOW)
	_add_navigation_quad("ShallowCalmNavigation", 29.0, 35.0, -12.0, -8.0, 0.0, NAV_LAYER_LAND_SHALLOW)
	_add_navigation_quad("ShallowWeakNavigation", 37.0, 43.0, -12.0, -8.0, 0.0, NAV_LAYER_LAND_SHALLOW)
	_add_navigation_quad("ShallowStrongNavigation", 45.0, 51.0, -12.0, -8.0, 0.0, NAV_LAYER_LAND_SHALLOW)
	_add_navigation_quad("DeepSwimNavigation", 53.0, 59.0, -12.0, -8.0, 1.55, NAV_LAYER_DEEP_SWIM)
	_add_navigation_quad("UnderBridgeShallowNavigation", 32.0, 44.0, 8.0, 12.0, 0.0, NAV_LAYER_LAND_SHALLOW)
	_add_navigation_slope_z("BridgeSouthNavigation", 37.0, 39.0, 4.0, 8.0, 0.0, 2.4, NAV_LAYER_BRIDGE)
	_add_navigation_quad("BridgeDeckNavigation", 37.0, 39.0, 8.0, 12.0, 2.4, NAV_LAYER_BRIDGE)
	_add_navigation_slope_z("BridgeNorthNavigation", 37.0, 39.0, 12.0, 16.0, 2.4, 0.0, NAV_LAYER_BRIDGE)


func _surface_kind_at(world_position: Vector3) -> String:
	for zone: Dictionary in _surface_zones:
		var bounds: Rect2 = zone["bounds"]
		if bounds.has_point(Vector2(world_position.x, world_position.z)):
			return str(zone["surface_kind"])
	return "FIRM_GROUND" if absf(world_position.x) <= 2.2 else "GRASS_FIELD"


func _slope_at(world_position: Vector3) -> float:
	if _inside_xz(world_position, 12.0, 18.0, -2.0, 2.0):
		return rad_to_deg(atan2(1.0, 6.0))
	if _inside_xz(world_position, 18.0, 24.0, -2.0, 2.0):
		return rad_to_deg(atan2(2.0, 6.0))
	if _inside_xz(world_position, 24.0, 27.0, -2.0, 2.0):
		return rad_to_deg(atan2(4.0, 3.0))
	if _inside_xz(world_position, 12.0, 13.0, 6.0, 10.0):
		return rad_to_deg(atan2(0.3, 1.0))
	return 0.0


func _surface_flags(surface_kind: String) -> Dictionary:
	var upper: String = surface_kind.to_upper()
	return {
		"road": upper.begins_with("ROAD"),
		"trail": upper == "TRAIL",
		"field": upper == "GRASS_FIELD",
		"rock": upper == "ROCKY_GROUND",
		"mud": upper == "MUD",
		"water": upper.begins_with("WATER"),
	}


func _register_surface_zone(surface_kind: String, bounds: Rect2) -> void:
	_surface_zones.append({"surface_kind": surface_kind, "bounds": bounds})
	var area := Area3D.new()
	area.name = "%sZone" % surface_kind.to_pascal_case()
	area.position = Vector3(bounds.position.x + bounds.size.x * 0.5, 0.0, bounds.position.y + bounds.size.y * 0.5)
	area.collision_layer = LAYER_WORLD_TRIGGER
	area.collision_mask = 0
	area.monitoring = false
	area.monitorable = false
	area.set_meta("surface_kind", surface_kind)
	area.set_meta("traversal_input_only", true)
	var shape_node := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = Vector3(bounds.size.x, 1.0, bounds.size.y)
	shape_node.shape = shape
	area.add_child(shape_node)
	surface_zones_root.add_child(area)


func _build_micro_relief_mesh() -> ArrayMesh:
	var surface_tool := SurfaceTool.new()
	surface_tool.begin(Mesh.PRIMITIVE_TRIANGLES)
	var divisions: int = 24
	var extent: float = 12.0
	for z_index: int in range(divisions):
		for x_index: int in range(divisions):
			var x0: float = remap(float(x_index), 0.0, float(divisions), -extent, extent)
			var x1: float = remap(float(x_index + 1), 0.0, float(divisions), -extent, extent)
			var z0: float = remap(float(z_index), 0.0, float(divisions), -extent, extent)
			var z1: float = remap(float(z_index + 1), 0.0, float(divisions), -extent, extent)
			var p00 := Vector3(x0, visual_micro_height(Vector3(x0, 0.0, z0)), z0)
			var p10 := Vector3(x1, visual_micro_height(Vector3(x1, 0.0, z0)), z0)
			var p01 := Vector3(x0, visual_micro_height(Vector3(x0, 0.0, z1)), z1)
			var p11 := Vector3(x1, visual_micro_height(Vector3(x1, 0.0, z1)), z1)
			for point: Vector3 in [p00, p01, p11, p00, p11, p10]:
				_visual_min_height_m = minf(_visual_min_height_m, point.y)
				_visual_max_height_m = maxf(_visual_max_height_m, point.y)
				surface_tool.add_vertex(point)
	surface_tool.generate_normals()
	return surface_tool.commit()


func _build_micro_stone_placeholders() -> void:
	var root := Node3D.new()
	root.name = "MicroReliefVisualOnly"
	visual_surface.add_child(root)
	for index: int in range(8):
		var stone := MeshInstance3D.new()
		stone.name = "VisualStone%02d" % index
		var mesh := SphereMesh.new()
		mesh.radius = 0.07 + float(index % 3) * 0.018
		mesh.height = mesh.radius * 1.3
		stone.mesh = mesh
		stone.material_override = _material(Color(0.43, 0.45, 0.43, 1.0), 1.0)
		stone.position = Vector3(-10.5 + index * 2.7, 0.045, 10.5 - float(index % 2) * 1.1)
		stone.scale = Vector3(1.4, 0.5, 1.0)
		root.add_child(stone)


func _build_bridge_visual() -> void:
	_add_ramp_visual_z("BridgeSouthRampVisual", 37.0, 39.0, 4.0, 8.0, 0.0, 2.4, Color(0.49, 0.42, 0.32, 1.0))
	_add_box_visual("BridgeDeckVisual", Vector3(38.0, 2.25, 10.0), Vector3(2.0, 0.3, 4.0), Color(0.49, 0.42, 0.32, 1.0))
	_add_ramp_visual_z("BridgeNorthRampVisual", 37.0, 39.0, 12.0, 16.0, 2.4, 0.0, Color(0.49, 0.42, 0.32, 1.0))


func _build_bridge_collision() -> void:
	_add_ramp_collision_z("BridgeSouthRampCollision", 37.0, 39.0, 4.0, 8.0, 0.0, 2.4)
	_add_box_collision("BridgeDeckCollision", Vector3(38.0, 2.25, 10.0), Vector3(2.0, 0.3, 4.0))
	_add_ramp_collision_z("BridgeNorthRampCollision", 37.0, 39.0, 12.0, 16.0, 2.4, 0.0)


func _add_box_visual(node_name: String, center: Vector3, size: Vector3, color: Color) -> void:
	var mesh_instance := MeshInstance3D.new()
	mesh_instance.name = node_name
	mesh_instance.position = center
	var mesh := BoxMesh.new()
	mesh.size = size
	mesh_instance.mesh = mesh
	mesh_instance.material_override = _material(color, 0.95)
	visual_surface.add_child(mesh_instance)


func _add_box_collision(node_name: String, center: Vector3, size: Vector3) -> void:
	var body := StaticBody3D.new()
	body.name = node_name
	body.position = center
	body.collision_layer = LAYER_WORLD_STATIC
	body.collision_mask = 0
	body.set_meta("pointer_kind", "GROUND")
	body.set_meta("collision_surface", "SIMPLIFIED_STABLE")
	var shape_node := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = size
	shape_node.shape = shape
	body.add_child(shape_node)
	collision_surface.add_child(body)


func _add_ramp_visual_x(node_name: String, x0: float, x1: float, z0: float, z1: float, y0: float, y1: float, color: Color) -> void:
	var placement: Dictionary = _ramp_placement_x(x0, x1, z0, z1, y0, y1)
	var mesh_instance := MeshInstance3D.new()
	mesh_instance.name = node_name
	mesh_instance.position = placement["center"]
	mesh_instance.rotation = Vector3(0.0, 0.0, float(placement["angle"]))
	var mesh := BoxMesh.new()
	mesh.size = placement["size"]
	mesh_instance.mesh = mesh
	mesh_instance.material_override = _material(color, 1.0)
	visual_surface.add_child(mesh_instance)


func _add_ramp_collision_x(node_name: String, x0: float, x1: float, z0: float, z1: float, y0: float, y1: float) -> void:
	var placement: Dictionary = _ramp_placement_x(x0, x1, z0, z1, y0, y1)
	var body := StaticBody3D.new()
	body.name = node_name
	body.position = placement["center"]
	body.rotation = Vector3(0.0, 0.0, float(placement["angle"]))
	body.collision_layer = LAYER_WORLD_STATIC
	body.collision_mask = 0
	body.set_meta("pointer_kind", "GROUND")
	body.set_meta("collision_surface", "SIMPLIFIED_STABLE")
	var shape_node := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = placement["size"]
	shape_node.shape = shape
	body.add_child(shape_node)
	collision_surface.add_child(body)


func _add_ramp_visual_z(node_name: String, x0: float, x1: float, z0: float, z1: float, y0: float, y1: float, color: Color) -> void:
	var placement: Dictionary = _ramp_placement_z(x0, x1, z0, z1, y0, y1)
	var mesh_instance := MeshInstance3D.new()
	mesh_instance.name = node_name
	mesh_instance.position = placement["center"]
	mesh_instance.rotation = Vector3(float(placement["angle"]), 0.0, 0.0)
	var mesh := BoxMesh.new()
	mesh.size = placement["size"]
	mesh_instance.mesh = mesh
	mesh_instance.material_override = _material(color, 1.0)
	visual_surface.add_child(mesh_instance)


func _add_ramp_collision_z(node_name: String, x0: float, x1: float, z0: float, z1: float, y0: float, y1: float) -> void:
	var placement: Dictionary = _ramp_placement_z(x0, x1, z0, z1, y0, y1)
	var body := StaticBody3D.new()
	body.name = node_name
	body.position = placement["center"]
	body.rotation = Vector3(float(placement["angle"]), 0.0, 0.0)
	body.collision_layer = LAYER_WORLD_STATIC
	body.collision_mask = 0
	body.set_meta("pointer_kind", "GROUND")
	body.set_meta("collision_surface", "SIMPLIFIED_STABLE")
	var shape_node := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = placement["size"]
	shape_node.shape = shape
	body.add_child(shape_node)
	collision_surface.add_child(body)


func _ramp_placement_x(x0: float, x1: float, z0: float, z1: float, y0: float, y1: float) -> Dictionary:
	var thickness: float = 0.35
	var run: float = x1 - x0
	var rise: float = y1 - y0
	var angle: float = atan2(rise, run)
	var length: float = Vector2(run, rise).length()
	var top_midpoint := Vector3((x0 + x1) * 0.5, (y0 + y1) * 0.5, (z0 + z1) * 0.5)
	var top_offset := Vector3(-sin(angle) * thickness * 0.5, cos(angle) * thickness * 0.5, 0.0)
	return {
		"center": top_midpoint - top_offset,
		"size": Vector3(length, thickness, z1 - z0),
		"angle": angle,
	}


func _ramp_placement_z(x0: float, x1: float, z0: float, z1: float, y0: float, y1: float) -> Dictionary:
	var thickness: float = 0.3
	var run: float = z1 - z0
	var rise: float = y1 - y0
	var angle: float = -atan2(rise, run)
	var length: float = Vector2(run, rise).length()
	var top_midpoint := Vector3((x0 + x1) * 0.5, (y0 + y1) * 0.5, (z0 + z1) * 0.5)
	var top_offset := Vector3(0.0, cos(angle) * thickness * 0.5, sin(angle) * thickness * 0.5)
	return {
		"center": top_midpoint - top_offset,
		"size": Vector3(x1 - x0, thickness, length),
		"angle": angle,
	}


func _add_navigation_quad(node_name: String, x0: float, x1: float, z0: float, z1: float, y: float, layers: int) -> void:
	var vertices := PackedVector3Array([
		Vector3(x0, y, z0),
		Vector3(x0, y, z1),
		Vector3(x1, y, z1),
		Vector3(x1, y, z0),
	])
	_add_navigation_polygon(node_name, vertices, layers)


func _add_navigation_slope_x(node_name: String, x0: float, x1: float, z0: float, z1: float, y0: float, y1: float, layers: int) -> void:
	var vertices := PackedVector3Array([
		Vector3(x0, y0, z0),
		Vector3(x0, y0, z1),
		Vector3(x1, y1, z1),
		Vector3(x1, y1, z0),
	])
	_add_navigation_polygon(node_name, vertices, layers)


func _add_navigation_slope_z(node_name: String, x0: float, x1: float, z0: float, z1: float, y0: float, y1: float, layers: int) -> void:
	var vertices := PackedVector3Array([
		Vector3(x0, y0, z0),
		Vector3(x0, y1, z1),
		Vector3(x1, y1, z1),
		Vector3(x1, y0, z0),
	])
	_add_navigation_polygon(node_name, vertices, layers)


func _add_navigation_polygon(node_name: String, vertices: PackedVector3Array, layers: int) -> void:
	var navigation_mesh := NavigationMesh.new()
	navigation_mesh.agent_radius = 0.35
	navigation_mesh.agent_height = 1.8
	navigation_mesh.agent_max_slope = MAX_WALKABLE_SLOPE_DEG_CANDIDATE
	navigation_mesh.agent_max_climb = MAX_STEP_HEIGHT_M_CANDIDATE
	navigation_mesh.set_vertices(vertices)
	navigation_mesh.add_polygon(PackedInt32Array([0, 1, 2, 3]))
	var region := NavigationRegion3D.new()
	region.name = node_name
	region.navigation_layers = layers
	region.use_edge_connections = true
	region.navigation_mesh = navigation_mesh
	navigation_regions.add_child(region)
	_navigation_region_refs[node_name] = region


func _material(color: Color, roughness: float) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = roughness
	return material


func _inside_xz(world_position: Vector3, x0: float, x1: float, z0: float, z1: float) -> bool:
	return world_position.x >= x0 and world_position.x <= x1 and world_position.z >= z0 and world_position.z <= z1
