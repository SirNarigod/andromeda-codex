extends CharacterBody3D
class_name AndromedaPlayerController

## Presentation-only player controller. Movement is predicted locally for
## responsiveness, but the backend (AndromedaMovementAuthorityClient) remains
## the single source of truth: every step also resubmits our position as an
## authoritative WALK destination so the server can accept/correct it.
## AUTHORITY := "GODOT_CLIENT_TRANSPORT_PRESENTATION_ONLY"

@export var movement_speed_mps: float = 5.0
@export var run_speed_threshold_mps: float = 3.2
@export var acceleration_mps2: float = 28.0
@export var rotation_speed_rad_s: float = 12.0
@export var camera_yaw_degrees: float = 45.0
@export var authority_resubmit_interval_s: float = 0.2
@export var animation_crossfade_s: float = 0.2
@export var dodge_duration_s: float = 0.5
@export var dodge_speed_mps: float = 8.0
@export var jump_velocity_mps: float = 7.5

# Locomotion clips loop; jump/dodge clips play once. This list is also what
# forces loop_mode at _ready(), since the glTF importer leaves everything as
# LOOP_NONE by default -- without this, walking/running plays once and then
# freezes on the last frame while the body keeps moving (looked like the
# animation "travava"/froze while movement stayed continuous).
const LOOPING_ANIMATIONS: Array[String] = [
	"idle", "walk", "run", "strafe_left", "strafe_right", "turn_left", "turn_right",
	"swim", "tread_water",
]

const ANIM_IDLE := "idle"
const ANIM_WALK := "walk"
const ANIM_RUN := "run"
const ANIM_JUMP_IDLE := "jump_idle"
const ANIM_JUMP_WALK := "jump_walk"
const ANIM_JUMP_RUN := "jump_run"
const ANIM_DODGE_FORWARD := "dodge_forward"
const ANIM_DODGE_BACK := "dodge_back"
const ANIM_DODGE_LEFT := "dodge_left"
const ANIM_DODGE_RIGHT := "dodge_right"
const ANIM_CLIMB_UP := "climb_up"
const ANIM_SWIM := "swim"

var _movement_authority_client: AndromedaMovementAuthorityClient
var _resubmit_timer_s: float = 0.0
var _current_animation: String = ""
var _dodge_remaining_s: float = 0.0
var _dodge_direction: Vector3 = Vector3.ZERO
var _swim_mode_active: bool = false

@onready var _mesh_pivot: Node3D = $MeshPivot
@onready var _anim_player: AnimationPlayer = _find_animation_player(_mesh_pivot)


func _ready() -> void:
	if _anim_player == null:
		return
	for anim_name: String in LOOPING_ANIMATIONS:
		if _anim_player.has_animation(anim_name):
			_anim_player.get_animation(anim_name).loop_mode = Animation.LOOP_LINEAR


func _find_animation_player(root: Node) -> AnimationPlayer:
	if root == null:
		return null
	return root.find_child("AnimationPlayer", true, false) as AnimationPlayer


func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y -= 24.0 * delta
	else:
		velocity.y = -0.2

	var input_vector: Vector2 = Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	var yaw_rad: float = deg_to_rad(camera_yaw_degrees)
	# Camera looks toward -Z rotated by yaw; forward/right are derived from
	# that same yaw so "W" always walks toward the top of the screen.
	var forward := Vector3(-sin(yaw_rad), 0.0, -cos(yaw_rad))
	var right := Vector3(cos(yaw_rad), 0.0, -sin(yaw_rad))

	if _dodge_remaining_s > 0.0:
		_dodge_remaining_s -= delta
		velocity.x = _dodge_direction.x * dodge_speed_mps
		velocity.z = _dodge_direction.z * dodge_speed_mps
		move_and_slide()
		return

	if is_on_floor() and Input.is_action_just_pressed("dodge") and input_vector.length_squared() > 0.0001:
		var dodge_dir: Vector3 = (forward * -input_vector.y + right * input_vector.x).normalized()
		_start_dodge(dodge_dir)
		return

	if is_on_floor() and Input.is_action_just_pressed("jump"):
		velocity.y = jump_velocity_mps
		var ground_speed_for_jump: float = Vector2(velocity.x, velocity.z).length()
		if ground_speed_for_jump < 0.2:
			_play_animation(ANIM_JUMP_IDLE)
		elif ground_speed_for_jump < run_speed_threshold_mps:
			_play_animation(ANIM_JUMP_WALK)
		else:
			_play_animation(ANIM_JUMP_RUN)

	if input_vector.length_squared() > 0.0001:
		var move_direction: Vector3 = (forward * -input_vector.y + right * input_vector.x).normalized()

		velocity.x = move_toward(velocity.x, move_direction.x * movement_speed_mps, acceleration_mps2 * delta)
		velocity.z = move_toward(velocity.z, move_direction.z * movement_speed_mps, acceleration_mps2 * delta)

		if _mesh_pivot != null:
			var target_angle: float = atan2(move_direction.x, move_direction.z)
			_mesh_pivot.rotation.y = lerp_angle(_mesh_pivot.rotation.y, target_angle, rotation_speed_rad_s * delta)

		_resubmit_timer_s -= delta
		if _resubmit_timer_s <= 0.0 and _movement_authority_client != null:
			_resubmit_timer_s = authority_resubmit_interval_s
			var ahead_point: Vector3 = global_position + move_direction * 2.0
			_movement_authority_client.submit_local_destination(ahead_point, "WALK")
	else:
		velocity.x = move_toward(velocity.x, 0.0, acceleration_mps2 * delta)
		velocity.z = move_toward(velocity.z, 0.0, acceleration_mps2 * delta)

	move_and_slide()

	# Compute airborne state AFTER move_and_slide() so a jump impulse applied
	# this same frame is reflected immediately -- reading is_on_floor() before
	# moving made the ground-animation branch below stomp the jump animation
	# in the very frame it started playing ("pulo não tem animação").
	var is_airborne: bool = not is_on_floor()
	if is_airborne:
		return

	if _swim_mode_active:
		_play_animation(ANIM_SWIM if input_vector.length_squared() > 0.0001 else "tread_water")
		return

	var ground_speed_mps: float = Vector2(velocity.x, velocity.z).length()
	if ground_speed_mps < 0.2:
		_play_animation(ANIM_IDLE)
	elif ground_speed_mps < run_speed_threshold_mps:
		_play_animation(ANIM_WALK)
	else:
		_play_animation(ANIM_RUN)


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("climb_toggle"):
		_play_animation(ANIM_CLIMB_UP)
	elif event.is_action_pressed("swim_toggle"):
		_swim_mode_active = not _swim_mode_active


func _start_dodge(direction: Vector3) -> void:
	_dodge_direction = direction
	_dodge_remaining_s = dodge_duration_s
	var yaw_rad: float = deg_to_rad(camera_yaw_degrees)
	var forward := Vector3(-sin(yaw_rad), 0.0, -cos(yaw_rad))
	var right := Vector3(cos(yaw_rad), 0.0, -sin(yaw_rad))
	var forward_dot: float = direction.dot(forward)
	var right_dot: float = direction.dot(right)
	if absf(forward_dot) >= absf(right_dot):
		_play_animation(ANIM_DODGE_FORWARD if forward_dot >= 0.0 else ANIM_DODGE_BACK)
	else:
		_play_animation(ANIM_DODGE_RIGHT if right_dot >= 0.0 else ANIM_DODGE_LEFT)
	if _mesh_pivot != null:
		_mesh_pivot.rotation.y = atan2(direction.x, direction.z)


func _play_animation(anim_name: String) -> void:
	if _anim_player == null or _current_animation == anim_name:
		return
	if not _anim_player.has_animation(anim_name):
		return
	_current_animation = anim_name
	_anim_player.play(anim_name, animation_crossfade_s)


func bind_movement_authority_client(client: AndromedaMovementAuthorityClient) -> void:
	_movement_authority_client = client


## Called by AndromedaMovementAuthorityClient when the connection drops
## (reconnect-wait/disconnected): halt local horizontal prediction so the
## player doesn't keep sliding on stale input while waiting for a fresh
## authoritative snapshot. Vertical (gravity) is left alone.
func stop_local_prediction() -> void:
	velocity.x = 0.0
	velocity.z = 0.0
	_resubmit_timer_s = 0.0


## Called by AndromedaMovementAuthorityClient whenever the server's own
## position (snapshot, command result, or a rejection's rollback) disagrees
## with our client-side prediction. Small drift is corrected smoothly so it's
## invisible; large drift (reconnect, rejection) snaps immediately since the
## server is always right. Returns reconciliation evidence for metrics.
func reconcile_authoritative_position(local_position: Vector3, reason: String, command_ref: String) -> Dictionary:
	var error_distance_m: float = Vector3(global_position.x, 0.0, global_position.z).distance_to(
		Vector3(local_position.x, 0.0, local_position.z)
	)
	if reason == "RECONNECT_SNAPSHOT" or reason == "AUTHORITY_REJECTION":
		# The server is unconditionally right here (we just reconnected, or our
		# last move was rejected outright) -- snap immediately.
		global_position.x = local_position.x
		global_position.z = local_position.z
	elif reason == "AUTHORITY_COMMAND_RESULT":
		# WASD resubmits a WALK request every ~0.2s targeting a point ahead of
		# the player, and the server acks the REQUESTED DESTINATION, not the
		# entity's true current position mid-travel. Snapping to that ack (as
		# we did before) made the player visibly hop forward on every
		# resubmit. Only correct hard drift here (e.g. actually stuck/blocked
		# server-side); small differences are expected and are left to local
		# prediction plus the periodic full-snapshot reconciliation below.
		if error_distance_m > 6.0:
			global_position.x = local_position.x
			global_position.z = local_position.z
		elif error_distance_m > 0.05:
			global_position.x = lerp(global_position.x, local_position.x, 0.05)
			global_position.z = lerp(global_position.z, local_position.z, 0.05)
	else:
		# Periodic authoritative snapshot: bigger drift snaps, small drift eases in.
		if error_distance_m > 2.0:
			global_position.x = local_position.x
			global_position.z = local_position.z
		elif error_distance_m > 0.05:
			global_position.x = lerp(global_position.x, local_position.x, 0.35)
			global_position.z = lerp(global_position.z, local_position.z, 0.35)
	return {
		"status": "PASS",
		"reason": reason,
		"command_ref": command_ref,
		"error_distance_m": error_distance_m,
		"corrected_position": global_position,
		"authority": "GODOT_CLIENT_TRANSPORT_PRESENTATION_ONLY",
	}
