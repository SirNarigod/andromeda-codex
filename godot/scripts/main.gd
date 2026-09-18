extends Node3D

## Wires the player, camera, ground and backend connection together and
## kicks off the authoritative session bind on startup.

@onready var _player: AndromedaPlayerController = $Player
@onready var _camera_rig: AndromedaIsometricCameraRig = $CameraRig
@onready var _movement_authority_client: AndromedaMovementAuthorityClient = $MovementAuthorityClient
@onready var _authority_space_mapper: AndromedaAuthoritySpaceMapper = $AuthoritySpaceMapper


func _ready() -> void:
	_camera_rig.set_follow_target(_player, true)
	_movement_authority_client.bind_runtime(_player, _authority_space_mapper)
	_player.bind_movement_authority_client(_movement_authority_client)

	var session: AndromedaClientSession = get_node_or_null("/root/ClientSession")
	var bridge: AndromedaRuntimeBridge = get_node_or_null("/root/AndromedaBridge")
	if session != null:
		var default_session_ref: String = str(
			ProjectSettings.get_setting("andromeda/bridge/default_session_ref", "")
		)
		if not default_session_ref.is_empty() and not session.has_active_session():
			session.bind_session(default_session_ref)
	if bridge != null:
		bridge.bind_authoritative_session()
