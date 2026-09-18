extends Node3D
class_name AndromedaIsometricCameraRig

## Fixed-angle follow camera built on SpringArm3D so it can never end up
## behind geometry or "float away" from the player: the arm's own collision
## probe pulls it in automatically, and position tracking uses the physics
## frame so it never lags a frame behind the body it follows.

@export var yaw_degrees: float = 45.0
@export var pitch_degrees: float = -55.0
@export var spring_length_m: float = 14.0
@export var follow_smoothing: float = 10.0
## Height above the target's origin the rig tracks, in metres. The target's
## origin sits at ground level (a CharacterBody3D's feet), so without this
## offset the SpringArm3D's collision probe starts right at floor height and
## immediately collides with the ground itself, collapsing the arm to near
## zero length -- the camera clips into the floor, which reads as stutter
## and black flicker (near clip plane inside solid geometry) whenever the
## player moves.
@export var follow_height_m: float = 1.5
@export_flags_3d_physics var collision_mask: int = 1

@onready var _spring_arm: SpringArm3D = $SpringArm3D
@onready var _camera: Camera3D = $SpringArm3D/Camera3D

var _follow_target: Node3D


func _ready() -> void:
	rotation_degrees = Vector3(pitch_degrees, yaw_degrees, 0.0)
	_spring_arm.spring_length = spring_length_m
	_spring_arm.collision_mask = collision_mask
	_spring_arm.margin = 0.2
	_camera.current = true


func _physics_process(delta: float) -> void:
	if _follow_target == null or not is_instance_valid(_follow_target):
		return
	var alpha: float = clampf(follow_smoothing * delta, 0.0, 1.0)
	global_position = global_position.lerp(_target_position(), alpha)


func set_follow_target(target: Node3D, snap_immediately: bool = false) -> void:
	_follow_target = target
	if target != null and snap_immediately:
		global_position = _target_position()


func _target_position() -> Vector3:
	return _follow_target.global_position + Vector3(0.0, follow_height_m, 0.0)


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("camera_zoom_in"):
		request_zoom_steps(-1)
	elif event.is_action_pressed("camera_zoom_out"):
		request_zoom_steps(1)


func request_zoom_steps(step_count: int) -> float:
	spring_length_m = clampf(spring_length_m + float(step_count), 6.0, 24.0)
	_spring_arm.spring_length = spring_length_m
	return spring_length_m
