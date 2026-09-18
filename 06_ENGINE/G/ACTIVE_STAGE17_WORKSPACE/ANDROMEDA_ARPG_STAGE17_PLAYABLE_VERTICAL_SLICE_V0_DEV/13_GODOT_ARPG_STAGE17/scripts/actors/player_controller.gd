extends CharacterBody3D
class_name AndromedaPlayerController

## Local movement prediction and Godot physics/navigation presentation only.
## The bridge envelope carries intent; this script never decides gameplay outcomes.

signal movement_intent_created(result: Dictionary)
signal destination_rejected(result: Dictionary)
signal destination_reached(world_position: Vector3)

const AUTHORITY := "GODOT_NAVIGATION_PRESENTATION_ONLY"
const MAX_DESTINATION_PROJECTION_M := 0.75

@export var movement_speed_mps: float = 5.0
@export var acceleration_mps2: float = 28.0
@export var deceleration_mps2: float = 36.0
@export var arrival_distance_m: float = 0.16
## WASD (14/09): mesmo pipeline de request_move()/submit_local_destination()
## do clique-pra-mover, so que reenviado periodicamente enquanto uma tecla
## de direcao esta segurada, em vez de 1x por clique. Nao toca em nenhum
## arquivo protegido/backend - e so uma forma diferente de alimentar o
## mesmo MOVE_TO_POINT que ja existia. yaw_degrees precisa bater com o
## AndromedaIsometricCameraRig (default 45.0) pra frente/W apontar pra cima
## da tela - ajustavel aqui no Inspector sem mexer em codigo se a direcao
## sair errada visualmente (nao pude confirmar visualmente sem acesso ao PC
## nesta sessao, so confirmei que roda sem erro).
@export var wasd_camera_yaw_degrees: float = 45.0
@export var wasd_authority_resubmit_interval_s: float = 0.25

@onready var navigation_agent: NavigationAgent3D = $NavigationAgent3D

var _has_destination: bool = false
var _destination: Vector3 = Vector3.ZERO
var _last_request: Dictionary = {}
var _movement_authority_client: AndromedaMovementAuthorityClient
var _reconciliation_active: bool = false
var _wasd_resubmit_timer_s: float = 0.0


func _ready() -> void:
	navigation_agent.path_desired_distance = 0.12
	navigation_agent.target_desired_distance = arrival_distance_m
	navigation_agent.avoidance_enabled = false
	floor_stop_on_slope = true
	floor_snap_length = 0.2


func _physics_process(delta: float) -> void:
	_apply_vertical_velocity(delta)
	var wasd_input: Vector2 = Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	if wasd_input.length_squared() > 0.0001:
		_process_wasd_movement(wasd_input, delta)
		return
	if not _has_destination:
		velocity.x = move_toward(velocity.x, 0.0, deceleration_mps2 * delta)
		velocity.z = move_toward(velocity.z, 0.0, deceleration_mps2 * delta)
		move_and_slide()
		return
	var horizontal_to_destination := Vector2(
		_destination.x - global_position.x,
		_destination.z - global_position.z
	)
	if horizontal_to_destination.length() <= arrival_distance_m:
		_complete_destination()
		move_and_slide()
		return
	var next_path_position: Vector3 = navigation_agent.get_next_path_position()
	var horizontal_direction := Vector2(
		next_path_position.x - global_position.x,
		next_path_position.z - global_position.z
	)
	if horizontal_direction.length_squared() <= 0.000001:
		horizontal_direction = horizontal_to_destination
	if horizontal_direction.length_squared() > 0.000001:
		horizontal_direction = horizontal_direction.normalized()
	var desired_x: float = horizontal_direction.x * movement_speed_mps
	var desired_z: float = horizontal_direction.y * movement_speed_mps
	velocity.x = move_toward(velocity.x, desired_x, acceleration_mps2 * delta)
	velocity.z = move_toward(velocity.z, desired_z, acceleration_mps2 * delta)
	move_and_slide()


func _process_wasd_movement(wasd_input: Vector2, delta: float) -> void:
	## Cancela qualquer destino de clique pendente - WASD assume o controle
	## direto assim que uma tecla e pressionada, mesma logica de velocidade/
	## aceleracao ja usada pro clique-pra-mover, so que a direcao vem do
	## teclado (relativa a camera isometrica fixa) em vez de um ponto no
	## chao vindo do NavigationAgent3D.
	_has_destination = false
	var yaw_rad: float = deg_to_rad(wasd_camera_yaw_degrees)
	var camera_forward := Vector3(sin(yaw_rad), 0.0, cos(yaw_rad))
	var camera_right := Vector3(cos(yaw_rad), 0.0, -sin(yaw_rad))
	var move_direction: Vector3 = (camera_forward * -wasd_input.y) + (camera_right * wasd_input.x)
	if move_direction.length_squared() > 0.000001:
		move_direction = move_direction.normalized()
	var desired_x: float = move_direction.x * movement_speed_mps
	var desired_z: float = move_direction.z * movement_speed_mps
	velocity.x = move_toward(velocity.x, desired_x, acceleration_mps2 * delta)
	velocity.z = move_toward(velocity.z, desired_z, acceleration_mps2 * delta)
	move_and_slide()
	# Reenvia a posicao pro servidor periodicamente (nao todo frame - evita
	# spam de MOVE_TO_POINT) enquanto a tecla continua segurada. O servidor
	# so ve "va ate este ponto" de tempos em tempos, exatamente como ja
	# fazia pro clique - so que o ponto agora e recalculado a frente do
	# jogador em vez de vir de 1 clique so.
	_wasd_resubmit_timer_s -= delta
	if _wasd_resubmit_timer_s > 0.0 or _movement_authority_client == null:
		return
	if move_direction.length_squared() <= 0.000001:
		return
	_wasd_resubmit_timer_s = wasd_authority_resubmit_interval_s
	var ahead_point: Vector3 = global_position + move_direction * MAX_DESTINATION_PROJECTION_M
	_movement_authority_client.submit_local_destination(ahead_point, "WALK")


func bind_movement_authority_client(client: AndromedaMovementAuthorityClient) -> void:
	_movement_authority_client = client


func movement_authority_client() -> AndromedaMovementAuthorityClient:
	## Read-only orchestration access for interaction clients.  The movement
	## backend remains the source of positional truth; callers may observe the
	## command lifecycle but cannot manufacture an authoritative position here.
	return _movement_authority_client


func movement_authority_metrics_snapshot() -> Dictionary:
	if _movement_authority_client == null:
		return {
			"status": "NOT_AVAILABLE",
			"pending_count": 0,
			"last_authority_position": {},
			"authority": AUTHORITY,
		}
	return _movement_authority_client.metrics_snapshot()


func request_move(world_destination: Vector3, mode: String = "WALK") -> Dictionary:
	var validation: Dictionary = validate_destination(world_destination)
	if validation.get("status") != "PASS":
		_last_request = validation.duplicate(true)
		destination_rejected.emit(validation.duplicate(true))
		return validation
	var navigation_destination: Vector3 = validation["navigation_destination"]
	var authority_submission: Dictionary = {}
	if _movement_authority_client != null:
		authority_submission = _movement_authority_client.submit_local_destination(
			navigation_destination,
			mode
		)
		if authority_submission.get("status") != "PASS":
			_last_request = authority_submission.duplicate(true)
			destination_rejected.emit(_last_request.duplicate(true))
			return _last_request.duplicate(true)
	_destination = navigation_destination
	navigation_agent.target_position = _destination
	_has_destination = true
	_reconciliation_active = false
	_last_request = {
		"status": "PASS",
		"intent": "MOVE_TO_POINT",
		"navigation_destination": _destination,
		"path_point_count": int(validation.get("path_point_count", 0)),
		"authority_submission": authority_submission,
		"transport_submitted": bool(authority_submission.get("submitted", false)),
		"local_prediction": true,
		"authority": AUTHORITY,
	}
	movement_intent_created.emit(_last_request.duplicate(true))
	return _last_request.duplicate(true)


func request_presentation_approach(world_destination: Vector3) -> Dictionary:
	## Stage17 B2 intentionally does not map local placeholder target positions to
	## territorial authority space. NPC/resource/loot spatial bindings are not yet
	## authoritative, so interaction callers retain the validated Stage16B local
	## approach until a later block supplies real target-position metadata.
	var validation: Dictionary = validate_destination(world_destination)
	if validation.get("status") != "PASS":
		_last_request = validation.duplicate(true)
		destination_rejected.emit(_last_request.duplicate(true))
		return _last_request.duplicate(true)
	_destination = validation.get("navigation_destination", world_destination)
	navigation_agent.target_position = _destination
	_has_destination = true
	_reconciliation_active = false
	_last_request = {
		"status": "PASS",
		"intent": "PRESENTATION_APPROACH_PENDING_AUTHORITY_SPATIAL_BINDING",
		"navigation_destination": _destination,
		"path_point_count": int(validation.get("path_point_count", 0)),
		"transport_submitted": false,
		"local_prediction": true,
		"authority_migration_pending": true,
		"authority": AUTHORITY,
	}
	movement_intent_created.emit(_last_request.duplicate(true))
	return _last_request.duplicate(true)


func validate_destination(world_destination: Vector3) -> Dictionary:
	var navigation_map: RID = navigation_agent.get_navigation_map()
	if not navigation_map.is_valid() or NavigationServer3D.map_get_iteration_id(navigation_map) <= 0:
		return _rejected("NAVIGATION_MAP_NOT_READY")
	var closest: Vector3 = NavigationServer3D.map_get_closest_point(navigation_map, world_destination)
	var projection_distance: float = Vector2(world_destination.x, world_destination.z).distance_to(
		Vector2(closest.x, closest.z)
	)
	if projection_distance > MAX_DESTINATION_PROJECTION_M:
		return _rejected("UNREACHABLE_DESTINATION", {
			"requested_destination": world_destination,
			"closest_navigation_point": closest,
			"projection_distance_m": projection_distance,
		})
	var path: PackedVector3Array = NavigationServer3D.map_get_path(
		navigation_map,
		global_position,
		closest,
		true
	)
	if path.is_empty():
		return _rejected("UNREACHABLE_DESTINATION", {"path_point_count": 0})
	var final_point: Vector3 = path[path.size() - 1]
	var final_distance: float = Vector2(final_point.x, final_point.z).distance_to(Vector2(closest.x, closest.z))
	if final_distance > arrival_distance_m:
		return _rejected("UNREACHABLE_DESTINATION", {"path_end_distance_m": final_distance})
	return {
		"status": "PASS",
		"navigation_destination": closest,
		"path": path,
		"path_point_count": path.size(),
		"authority": AUTHORITY,
	}


func preview_path(world_destination: Vector3) -> PackedVector3Array:
	var validation: Dictionary = validate_destination(world_destination)
	if validation.get("status") != "PASS":
		return PackedVector3Array()
	return validation.get("path", PackedVector3Array()) as PackedVector3Array


func has_destination() -> bool:
	return _has_destination


func requested_destination() -> Vector3:
	return _destination


func last_request() -> Dictionary:
	return _last_request.duplicate(true)


func stop_local_prediction() -> void:
	_has_destination = false
	_reconciliation_active = false
	velocity.x = 0.0
	velocity.z = 0.0
	navigation_agent.target_position = global_position


func reconcile_authoritative_position(
	authoritative_local_position: Vector3,
	source: String,
	command_ref: String
) -> Dictionary:
	if not is_finite(authoritative_local_position.x) or not is_finite(authoritative_local_position.z):
		return _rejected("INVALID_RECONCILIATION_POSITION")
	var error_distance: float = Vector2(global_position.x, global_position.z).distance_to(
		Vector2(authoritative_local_position.x, authoritative_local_position.z)
	)
	var tolerance: float = arrival_distance_m
	if error_distance <= tolerance:
		return {
			"status": "PASS",
			"action": "WITHIN_PRESENTATION_TOLERANCE",
			"error_distance_m": error_distance,
			"tolerance_m": tolerance,
			"source": source,
			"command_ref": command_ref,
			"authority": AUTHORITY,
		}
	var destination := Vector3(
		authoritative_local_position.x,
		global_position.y,
		authoritative_local_position.z
	)
	var validation: Dictionary = validate_destination(destination)
	if validation.get("status") != "PASS":
		stop_local_prediction()
		return _rejected("AUTHORITATIVE_RECONCILIATION_PATH_INVALID", {
			"error_distance_m": error_distance,
			"path_result": validation,
			"source": source,
			"command_ref": command_ref,
		})
	_destination = validation.get("navigation_destination", destination)
	navigation_agent.target_position = _destination
	_has_destination = true
	_reconciliation_active = true
	return {
		"status": "PASS",
		"action": "SMOOTH_NAVIGATION_RECONCILIATION",
		"error_distance_m": error_distance,
		"tolerance_m": tolerance,
		"reconciliation_destination": _destination,
		"source": source,
		"command_ref": command_ref,
		"authority": AUTHORITY,
	}


func presentation_reconciliation_tolerance_m() -> float:
	return arrival_distance_m


func reconciliation_active() -> bool:
	return _reconciliation_active


func _complete_destination() -> void:
	_has_destination = false
	velocity.x = 0.0
	velocity.z = 0.0
	global_position.x = _destination.x
	global_position.z = _destination.z
	_reconciliation_active = false
	destination_reached.emit(global_position)


func _apply_vertical_velocity(delta: float) -> void:
	if is_on_floor():
		velocity.y = 0.0
	else:
		velocity.y -= float(ProjectSettings.get_setting("physics/3d/default_gravity", 9.8)) * delta


func _rejected(reason: String, detail: Dictionary = {}) -> Dictionary:
	var result: Dictionary = {
		"status": "REJECTED",
		"reason": reason,
		"authority": AUTHORITY,
	}
	result.merge(detail, true)
	return result
