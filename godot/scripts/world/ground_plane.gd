extends StaticBody3D
class_name AndromedaGroundPlane

## Simple, always-visible, always-collidable ground so the player can never
## fall into the void. Draws a checker grid purely for visual orientation.

@export var size_m: float = 400.0
@export var tile_m: float = 4.0


func _ready() -> void:
	collision_layer = 1
	collision_mask = 0
	var mesh_instance := MeshInstance3D.new()
	var plane_mesh := PlaneMesh.new()
	plane_mesh.size = Vector2(size_m, size_m)
	plane_mesh.subdivide_width = int(size_m / tile_m)
	plane_mesh.subdivide_depth = int(size_m / tile_m)
	mesh_instance.mesh = plane_mesh
	mesh_instance.material_override = _build_grid_material()
	add_child(mesh_instance)

	var collision_shape := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = Vector3(size_m, 0.2, size_m)
	collision_shape.shape = shape
	collision_shape.position = Vector3(0.0, -0.1, 0.0)
	add_child(collision_shape)


func _build_grid_material() -> ShaderMaterial:
	var shader := Shader.new()
	shader.code = """
shader_type spatial;
render_mode unshaded, cull_back;

uniform float tile_size = 4.0;
uniform vec3 color_a : source_color = vec3(0.16, 0.19, 0.16);
uniform vec3 color_b : source_color = vec3(0.20, 0.24, 0.20);
uniform vec3 line_color : source_color = vec3(0.32, 0.40, 0.30);

varying vec3 world_pos;

void vertex() {
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	vec2 cell = floor(world_pos.xz / tile_size);
	float checker = mod(cell.x + cell.y, 2.0);
	vec3 base = mix(color_a, color_b, checker);
	vec2 grid_uv = mod(world_pos.xz, tile_size);
	float line = step(grid_uv.x, 0.04) + step(grid_uv.y, 0.04);
	ALBEDO = mix(base, line_color, clamp(line, 0.0, 1.0));
	ROUGHNESS = 1.0;
}
"""
	var material := ShaderMaterial.new()
	material.shader = shader
	material.set_shader_parameter("tile_size", tile_m)
	return material
