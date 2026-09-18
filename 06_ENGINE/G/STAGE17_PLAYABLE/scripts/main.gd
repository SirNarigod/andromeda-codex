extends Node
class_name AndromedaMainRuntime

## Stage17 fork of the validated Stage16B scene/input/UI client adapter.
## Godot detects and presents targets; authoritative gameplay remains behind the B01 bridge.

signal pointer_resolution_committed(result: Dictionary)
signal hover_resolution_changed(result: Dictionary)
signal target_selection_changed(target_ref: String, target_kind: String)
signal menu_state_changed(open: bool)

const AUTHORITY := "GODOT_SCENE_INPUT_PHYSICS_PRESENTATION_ONLY"

const LAYER_WORLD_STATIC := 1
const LAYER_PLAYER := 2
const LAYER_ACTOR_BODY := 4
const LAYER_INTERACTABLE := 8
const LAYER_GROUND_LOOT := 16
const LAYER_RESOURCE_NODE := 32
const LAYER_VEHICLE := 64
const LAYER_NAV_BLOCKER := 128
const LAYER_CAMERA_OCCLUDER := 256
const LAYER_HIT_HURT_SENSOR := 512
const LAYER_WORLD_TRIGGER := 1024
const LAYER_WATER_VOLUME := 2048
const LAYER_DROPPED_BAG := 4096

const POINTER_COLLISION_MASK := (
	LAYER_WORLD_STATIC
	| LAYER_ACTOR_BODY
	| LAYER_INTERACTABLE
	| LAYER_GROUND_LOOT
	| LAYER_RESOURCE_NODE
	| LAYER_VEHICLE
	| LAYER_NAV_BLOCKER
	| LAYER_DROPPED_BAG
)
const POINTER_MAX_HITS := 32
const RAY_LENGTH_M := 500.0
const NAVIGATION_READY_PROBE := Vector3(-7.0, 0.0, 0.0)

@onready var navigation_region: NavigationRegion3D = $WorldStreamRoot/TraversalSurface/NavigationRegion3D
@onready var terrain_foundation: AndromedaTerrainFoundation = $WorldStreamRoot/TerrainFoundation
@onready var player: AndromedaPlayerController = $ActorRoot/Player
@onready var authority_space_mapper: AndromedaAuthoritySpaceMapper = $AuthoritySpaceMapper
@onready var movement_authority_client: AndromedaMovementAuthorityClient = $MovementAuthorityClient
@onready var interaction_spatial_binding_registry: AndromedaInteractionSpatialBindingRegistry = $InteractionSpatialBindingRegistry
@onready var camera_rig: AndromedaIsometricCameraRig = $IsometricCameraRig
@onready var hud: AndromedaHUDController = $UILayer/MinimalHUD
@onready var ground_loot_client: AndromedaGroundLootPickupClient = $GroundLootPickupClient
@onready var gathering_client: AndromedaGatheringClient = $GatheringClient
@onready var combat_authority_client: AndromedaCombatAuthorityClient = $CombatAuthorityClient
@onready var traversal_authority_client: Node = $TraversalAuthorityClient
@onready var vendor_client: AndromedaVendorClient = $VendorClient
@onready var inventory_client: AndromedaInventoryClient = $InventoryClient
@onready var quest_client: AndromedaQuestClient = $QuestClient
@onready var npc_dialogue_client: AndromedaNpcDialogueClient = $NpcDialogueClient
@onready var dropped_bag_client: AndromedaDroppedBagClient = $DroppedBagClient
@onready var death_respawn_client: AndromedaDeathRespawnClient = $DeathRespawnClient
@onready var save_reload_client: AndromedaSaveReloadClient = $SaveReloadClient
@onready var b11_performance_probe: AndromedaB11PerformanceProbe = $B11PerformanceProbe
@onready var b11_vertical_slice_client: AndromedaB11VerticalSliceClient = $B11VerticalSliceClient
@onready var ground_loot_root: Node3D = $GroundLootRoot
@onready var dropped_bag_root: Node3D = $DroppedBagRoot
@onready var resource_root: Node3D = $WorldStreamRoot/B03InteractionTargets
@onready var streaming_manager: AndromedaStreamingManager = $WorldStreamRoot/TerrainFoundation/CELL_STREAMING
@onready var dialogue_npc_primary: AndromedaInteractionTarget = $ActorRoot/NPCB03
@onready var dialogue_npc_peer: AndromedaInteractionTarget = $ActorRoot/NPCB05DialoguePeer
@onready var vendor_npc: AndromedaVendorTarget = $ActorRoot/VendorNPCB09
@onready var combat_enemy_common: AndromedaInteractionTarget = $ActorRoot/EnemyB03
@onready var combat_enemy_alpha: AndromedaInteractionTarget = $ActorRoot/EnemyB06Alpha

var _menu_open: bool = false
var _pointer_resolution_serial: int = 0
var _last_pointer_resolution: Dictionary = {}
var _last_pointer_target_ref: String = ""
var _selected_target_ref: String = ""
var _selected_target_kind: String = ""
var _selected_target: AndromedaInteractionTarget
var _hovered_target_ref: String = ""
var _hovered_target: AndromedaInteractionTarget


func _ready() -> void:
	_build_b02_navigation_mesh()
	movement_authority_client.bind_runtime(player, authority_space_mapper)
	interaction_spatial_binding_registry.bind_runtime(authority_space_mapper)
	player.bind_movement_authority_client(movement_authority_client)
	camera_rig.set_follow_target(player, true)
	streaming_manager.bind_zone_authority()
	var dialogue_actors: Array[Node3D] = [dialogue_npc_primary, dialogue_npc_peer, vendor_npc]
	var combat_actors: Array[Node3D] = [combat_enemy_common, combat_enemy_alpha]
	hud.bind_runtime(self, player, camera_rig.camera, dialogue_actors, combat_actors, camera_rig)
	ground_loot_client.bind_runtime(self, player, hud, ground_loot_root)
	combat_authority_client.bind_runtime(
		self,
		player,
		hud,
		ground_loot_client,
		combat_enemy_common,
		combat_enemy_alpha,
		interaction_spatial_binding_registry
	)
	traversal_authority_client.bind_runtime(player, terrain_foundation)
	gathering_client.bind_runtime(
		self,
		player,
		hud,
		resource_root,
		ground_loot_client,
		streaming_manager,
		interaction_spatial_binding_registry
	)
	var vendors: Array[AndromedaVendorTarget] = [vendor_npc]
	vendor_client.bind_runtime(self, player, hud, vendors)
	inventory_client.bind_runtime(hud)
	var quest_npcs: Array[AndromedaInteractionTarget] = [dialogue_npc_primary, dialogue_npc_peer]
	quest_client.bind_runtime(self, player, hud, quest_npcs)
	npc_dialogue_client.bind_runtime(self, hud)
	dropped_bag_client.bind_runtime(self, player, hud, dropped_bag_root)
	death_respawn_client.bind_runtime(
		self,
		player,
		camera_rig,
		hud,
		dropped_bag_client,
		inventory_client
	)
	save_reload_client.bind_runtime(
		self,
		player,
		hud,
		ground_loot_client,
		gathering_client,
		inventory_client,
		vendor_client,
		quest_client,
		dropped_bag_client,
		death_respawn_client,
		streaming_manager
	)
	b11_vertical_slice_client.bind_runtime(self, b11_performance_probe)
	if not hud.modal_state_changed.is_connected(_on_hud_modal_state_changed):
		hud.modal_state_changed.connect(_on_hud_modal_state_changed)
	call_deferred("_start_authority_connection_if_main_scene")


func _start_authority_connection_if_main_scene() -> void:
	if get_tree().current_scene != self:
		return
	if not bool(ProjectSettings.get_setting("andromeda/bridge/auto_connect_main", true)):
		return
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if session == null or bridge == null:
		return
	if not session.has_active_session():
		var configured_ref: String = str(ProjectSettings.get_setting(
			"andromeda/bridge/default_session_ref",
			"GODOT-STAGE16B-MAIN-001"
		)).strip_edges()
		if session.bind_session(configured_ref).get("status") != "PASS":
			return
	bridge.bind_authoritative_session()


func _process(_delta: float) -> void:
	if _menu_open or world_input_blocked() or camera_rig == null or camera_rig.camera == null:
		return
	handle_pointer_hover(get_viewport().get_mouse_position())


func _unhandled_input(event: InputEvent) -> void:
	var action_result: Dictionary = handle_action_event(event)
	if action_result.get("status") == "PASS":
		get_viewport().set_input_as_handled()
		return
	var result: Dictionary = handle_pointer_event(event)
	if result.get("status") == "PASS":
		get_viewport().set_input_as_handled()


func handle_action_event(event: InputEvent) -> Dictionary:
	if not event is InputEventKey:
		return _rejected("UNSUPPORTED_ACTION_EVENT")
	var key_event: InputEventKey = event
	if not key_event.pressed or key_event.echo:
		return _rejected("ACTION_RELEASE_OR_ECHO_IGNORED")
	if key_event.is_action_pressed("inventory_toggle") or key_event.keycode == KEY_I:
		if hud.active_modal() == "INVENTORY":
			hud.close_active_modal()
		else:
			hud.set_inventory_open(true)
		_menu_open = hud.is_any_modal_open()
		return _commit_pointer_resolution({
			"status": "PASS",
			"intent": "INVENTORY_TOGGLE",
			"menu_open": _menu_open,
			"gameplay_authority_changed": false,
			"authority": AUTHORITY,
		})
	if key_event.keycode == KEY_ESCAPE and _menu_open:
		var close_result: Dictionary = hud.close_active_modal()
		_menu_open = hud.is_any_modal_open()
		return _commit_pointer_resolution({
			"status": "PASS",
			"intent": "CLOSE_ACTIVE_MODAL",
			"close_result": close_result,
			"gameplay_state_changed": false,
			"authority": AUTHORITY,
		})
	# S17-C3R5: minimal normal-input connection for respawn -- placed before the
	# world_input_blocked() gate below because respawn is precisely the action
	# that must work WHILE the world is blocked (death). request_respawn()
	# already self-validates against death_respawn_client's own state (only
	# proceeds from DEAD_AWAITING_RESPAWN), so no state is duplicated here.
	if key_event.keycode == KEY_R and not _menu_open:
		var respawn_result: Dictionary = death_respawn_client.request_respawn()
		return _commit_pointer_resolution({
			"status": respawn_result.get("status", "REJECTED"),
			"reason": respawn_result.get("reason", ""),
			"intent": "RESPAWN_REQUESTED",
			"respawn_client_result": respawn_result,
			"gameplay_authority_preserved": true,
			"authority": AUTHORITY,
		})
	if world_input_blocked():
		return _commit_pointer_resolution({
			"status": "PASS",
			"intent": "WORLD_INPUT_BLOCKED",
			"reason": "DEATH_RELOAD_RESYNC_STATE",
			"world_action_dispatched": false,
			"target_changed": false,
			"authority": AUTHORITY,
		})
	if key_event.is_action_pressed("context_interact") or key_event.keycode == KEY_E:
		if _menu_open:
			return _commit_pointer_resolution({
				"status": "PASS",
				"intent": "UI_INPUT_CONSUMED",
				"world_action_dispatched": false,
				"authority": AUTHORITY,
			})
		if _selected_target == null or not is_instance_valid(_selected_target):
			return _commit_pointer_resolution(_rejected("NO_SELECTED_CONTEXT_TARGET"))
		var interaction_result: Dictionary
		if _selected_target is AndromedaDroppedBag:
			interaction_result = dropped_bag_client.handle_selected_interaction(_selected_target)
		elif _selected_target is AndromedaVendorTarget:
			interaction_result = vendor_client.handle_selected_interaction(_selected_target)
		elif _selected_target.target_kind == AndromedaInputRouter.HIT_NPC:
			interaction_result = quest_client.handle_selected_interaction(_selected_target)
			# S17-C3R5: minimal normal-input connection for dialogue. quest_client
			# only ever handles NPCs that already carry a projected quest/offer --
			# by design (npc_dialogue_client.gd's own contract) dialogue identity
			# comes exclusively from the server's dialogue_npc_projection, never
			# from whatever the player happens to have selected. So the selected
			# NPC here is used only as a presentation anchor for the HUD bubble,
			# never as the dialogue identity itself, exactly as that client
			# requires. Fired only when quest_client had nothing to offer this
			# NPC and the server currently has a real dialogue target ready.
			if (
				interaction_result.get("status") != "PASS"
				and interaction_result.get("reason", "") in ["QUEST_STATE_NOT_PROJECTED_FOR_NPC", "NO_PROJECTED_QUEST_FOR_NPC"]
				and npc_dialogue_client != null
				and npc_dialogue_client.dialogue_target_available()
			):
				npc_dialogue_client.request_dialogue(_selected_target)
				interaction_result = {
					"status": "PASS",
					"intent": "DIALOGUE_REQUESTED",
					"dialogue_dispatched": true,
					"authority": npc_dialogue_client.AUTHORITY,
				}
		else:
			interaction_result = gathering_client.handle_selected_interaction(_selected_target)
		return _commit_pointer_resolution({
			"status": interaction_result.get("status", "REJECTED"),
			"reason": interaction_result.get("reason", ""),
			"intent": "CONTEXT_INTERACT_SELECTED",
			"target_ref": _selected_target_ref,
			"target_kind": _selected_target_kind,
			"interaction_client_result": interaction_result,
			"gathering_client_result": interaction_result if _selected_target.target_kind == AndromedaInputRouter.HIT_GATHER_NODE else {},
			"vendor_client_result": interaction_result if _selected_target is AndromedaVendorTarget else {},
			"quest_client_result": interaction_result if _selected_target.target_kind == AndromedaInputRouter.HIT_NPC and not _selected_target is AndromedaVendorTarget else {},
			"dropped_bag_client_result": interaction_result if _selected_target is AndromedaDroppedBag else {},
			"gameplay_authority_preserved": true,
			"authority": AUTHORITY,
		})
	if _menu_open:
		return _commit_pointer_resolution({
			"status": "PASS",
			"intent": "UI_INPUT_CONSUMED",
			"weapon_slot_changed": false,
			"world_action_dispatched": false,
			"authority": AUTHORITY,
		})
	if key_event.keycode == KEY_SPACE:
		if (
			_selected_target == null
			or not is_instance_valid(_selected_target)
			or _selected_target.target_kind != AndromedaInputRouter.HIT_ACTOR
			or not _selected_target.hostile
		):
			return _commit_pointer_resolution(_rejected("NO_SELECTED_HOSTILE_TARGET"))
		var attack_result: Dictionary = combat_authority_client.handle_selected_attack(
			_selected_target
		)
		return _commit_pointer_resolution({
			"status": attack_result.get("status", "REJECTED"),
			"reason": attack_result.get("reason", ""),
			"intent": "ATTACK_SELECTED_TARGET",
			"target_ref": _selected_target_ref,
			"combat_client_result": attack_result,
			"transport_submitted": bool(attack_result.get("transport_submitted", false)),
			"gameplay_authority_preserved": true,
			"authority": AUTHORITY,
		})
	# S17-C3R5: minimal normal-input connection for manual save -- reuses the
	# existing save_reload_client authority path (previously only reachable
	# from test harnesses); backend REQUEST_SAVE remains the sole authority
	# over what is persisted.
	if key_event.keycode == KEY_F5:
		var save_result: Dictionary = save_reload_client.request_manual_save()
		return _commit_pointer_resolution({
			"status": save_result.get("status", "REJECTED"),
			"reason": save_result.get("reason", ""),
			"intent": "MANUAL_SAVE_REQUESTED",
			"save_client_result": save_result,
			"gameplay_authority_preserved": true,
			"authority": AUTHORITY,
		})
	var slot_index: int = 0
	if key_event.is_action_pressed("weapon_slot_1") or key_event.keycode == KEY_1:
		slot_index = 1
	elif key_event.is_action_pressed("weapon_slot_2") or key_event.keycode == KEY_2:
		slot_index = 2
	if slot_index == 0:
		return _rejected("UNMAPPED_ACTION_KEY")
	var router := get_node_or_null("/root/InputRouter") as AndromedaInputRouter
	if router == null:
		return _rejected("INPUT_ROUTER_AUTOLOAD_NOT_FOUND")
	var resolved: Dictionary = router.resolve_weapon_slot_key(slot_index)
	if resolved.get("status") == "PASS":
		resolved["ui_projection"] = hud.request_weapon_slot(slot_index, "KEY_%d" % slot_index)
		resolved["transport_submitted"] = bool(resolved["ui_projection"].get("transport_submitted", false))
	return _commit_pointer_resolution(resolved)


func handle_pointer_event(event: InputEvent) -> Dictionary:
	if not event is InputEventMouseButton:
		return _rejected("UNSUPPORTED_INPUT_EVENT")
	var mouse_event: InputEventMouseButton = event
	if not mouse_event.pressed:
		return _rejected("POINTER_RELEASE_IGNORED")
	var router := get_node_or_null("/root/InputRouter") as AndromedaInputRouter
	if router == null:
		return _rejected("INPUT_ROUTER_AUTOLOAD_NOT_FOUND")
	if mouse_event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN]:
		if world_input_blocked() and not _menu_open:
			return _commit_pointer_resolution({
				"status": "PASS",
				"intent": "WORLD_INPUT_BLOCKED",
				"weapon_slot_changed": false,
				"camera_zoom_changed": false,
				"authority": AUTHORITY,
			})
		var zoom_modifier: bool = mouse_event.shift_pressed or Input.is_action_pressed("camera_zoom_modifier")
		var wheel_result: Dictionary = router.resolve_wheel(
			mouse_event.button_index,
			zoom_modifier,
			_menu_open
		)
		if wheel_result.get("intent") == "CAMERA_ZOOM":
			camera_rig.request_zoom_steps(int(wheel_result.get("zoom_steps", 0)))
		elif wheel_result.get("intent") == "WEAPON_QUICK_SLOT_CYCLE":
			wheel_result["ui_projection"] = hud.request_weapon_cycle(
				int(wheel_result.get("slot_delta", 0)),
				"MOUSE_WHEEL"
			)
			wheel_result["transport_submitted"] = bool(
				wheel_result["ui_projection"].get("transport_submitted", false)
			)
		elif wheel_result.get("intent") == "MENU_SCROLL":
			wheel_result["ui_projection"] = hud.consume_menu_scroll(
				int(wheel_result.get("scroll_direction", 0))
			)
		return _commit_pointer_resolution(wheel_result)
	if _menu_open:
		return _commit_pointer_resolution({
			"status": "PASS",
			"intent": "UI_POINTER_CONSUMED",
			"world_action_dispatched": false,
			"selection_changed": false,
			"movement_changed": false,
			"authority": AUTHORITY,
		})
	if world_input_blocked():
		return _commit_pointer_resolution({
			"status": "PASS",
			"intent": "WORLD_INPUT_BLOCKED",
			"world_action_dispatched": false,
			"selection_changed": false,
			"movement_changed": false,
			"authority": AUTHORITY,
		})
	if mouse_event.button_index != MOUSE_BUTTON_LEFT and mouse_event.button_index != MOUSE_BUTTON_RIGHT:
		return _rejected("UNSUPPORTED_POINTER_BUTTON")

	var pointer_context: Dictionary = _resolve_screen_pointer(mouse_event.position)
	var candidate: Dictionary = pointer_context.get("target", {})
	var hit_kind: String = AndromedaInputRouter.HIT_GROUND
	var target_ref: String = ""
	var hostile: bool = false
	var ground_loot_settled: bool = true
	var pointer_world_position: Vector3 = Vector3.ZERO
	if not candidate.is_empty():
		hit_kind = str(candidate.get("target_kind", "")).to_upper()
		target_ref = str(candidate.get("target_ref", ""))
		hostile = bool(candidate.get("hostile", false))
		ground_loot_settled = bool(candidate.get("ground_loot_settled", true))
		pointer_world_position = candidate.get("target_world_position", Vector3.ZERO)
	elif pointer_context.has("ground_position"):
		pointer_world_position = pointer_context.get("ground_position", Vector3.ZERO)
	elif bool(pointer_context.get("blocked", false)):
		return _commit_pointer_resolution(_rejected("POINTER_BLOCKED", {
			"blocker": str(pointer_context.get("blocker", "")),
		}))
	else:
		return _commit_pointer_resolution(_rejected("NO_POINTER_HIT"))

	var distance_m: float = player.global_position.distance_to(pointer_world_position)
	var reachable: bool = true
	if hit_kind == AndromedaInputRouter.HIT_GROUND_LOOT:
		reachable = player.validate_destination(pointer_world_position).get("status") == "PASS"
	var resolved: Dictionary = router.resolve_pointer_click(
		mouse_event.button_index,
		hit_kind,
		pointer_world_position,
		target_ref,
		hostile,
		distance_m,
		reachable,
		ground_loot_settled
	)
	if not candidate.is_empty():
		resolved["resolved_depth_m"] = float(candidate.get("depth_m", INF))
		resolved["resolved_screen_distance_px"] = float(candidate.get("screen_distance_px", INF))
		resolved["direct_cursor_hit"] = bool(candidate.get("direct_hit", false))

	var intent: String = str(resolved.get("intent", ""))
	if intent == "MOVE_TO_POINT" or intent == "APPROACH_PICKUP":
		var movement: Dictionary = (
			player.request_move(pointer_world_position)
			if intent == "MOVE_TO_POINT"
			else player.request_presentation_approach(pointer_world_position)
		)
		resolved["movement_result"] = movement
		if movement.get("status") != "PASS":
			resolved["status"] = "REJECTED"
			resolved["reason"] = movement.get("reason", "MOVEMENT_REJECTED")
	if intent == "SELECT_TARGET" and resolved.get("status") == "PASS":
		_select_candidate(candidate)
		resolved["selection_stable_until_next_selection"] = true
	if (
		hit_kind == AndromedaInputRouter.HIT_GROUND_LOOT
		and intent in ["PICKUP", "APPROACH_PICKUP"]
		and resolved.get("status") == "PASS"
	):
		resolved["pickup_client_result"] = ground_loot_client.handle_manual_pointer_intent(
			resolved,
			_candidate_owner(candidate)
		)
	if (
		hit_kind == AndromedaInputRouter.HIT_GATHER_NODE
		and intent == "APPROACH_HARVEST"
		and resolved.get("status") == "PASS"
	):
		var gathering_result: Dictionary = gathering_client.handle_manual_resource_intent(
			resolved,
			_candidate_owner(candidate)
		)
		resolved["gathering_client_result"] = gathering_result
		resolved["gathering_request_prepared"] = gathering_result.get("status") == "PASS"
	if (
		hit_kind == AndromedaInputRouter.HIT_ACTOR
		and hostile
		and intent == "CHASE_ATTACK"
		and resolved.get("status") == "PASS"
	):
		var combat_result: Dictionary = combat_authority_client.handle_manual_hostile_intent(
			resolved,
			_candidate_owner(candidate)
		)
		resolved["combat_client_result"] = combat_result
		resolved["combat_request_prepared"] = combat_result.get("status") == "PASS"
		resolved["transport_submitted"] = bool(combat_result.get("transport_submitted", false))
	if (
		hit_kind == AndromedaInputRouter.HIT_DROPPED_BAG
		and intent == "APPROACH_RECOVER_BAG"
		and resolved.get("status") == "PASS"
	):
		resolved["dropped_bag_client_result"] = dropped_bag_client.handle_manual_bag_intent(
			resolved,
			_candidate_owner(candidate)
		)
	if (
		hit_kind == AndromedaInputRouter.HIT_NPC
		and intent == "APPROACH_INTERACT"
		and resolved.get("status") == "PASS"
	):
		var interaction_target: AndromedaInteractionTarget = _candidate_owner(candidate)
		if interaction_target is AndromedaVendorTarget:
			resolved["vendor_client_result"] = vendor_client.handle_manual_vendor_intent(resolved, interaction_target)
		else:
			resolved["quest_client_result"] = quest_client.handle_manual_npc_intent(resolved, interaction_target)
	if intent in [
		"SELECT_TARGET",
		"PICKUP",
		"APPROACH_PICKUP",
		"CHASE_ATTACK",
		"APPROACH_INTERACT",
		"APPROACH_HARVEST",
		"APPROACH_RECOVER_BAG",
	]:
		resolved["intent_envelope"] = _build_interaction_envelope(resolved, pointer_world_position)
		if not resolved.has("transport_submitted"):
			resolved["transport_submitted"] = false
		resolved["dispatched_to_gameplay"] = bool(resolved.get("transport_submitted", false))
		resolved["gameplay_authority_preserved"] = true
	return _commit_pointer_resolution(resolved)


func handle_pointer_hover(screen_position: Vector2) -> Dictionary:
	var router := get_node_or_null("/root/InputRouter") as AndromedaInputRouter
	if router == null:
		return _rejected("INPUT_ROUTER_AUTOLOAD_NOT_FOUND")
	var pointer_context: Dictionary = _resolve_screen_pointer(screen_position)
	var candidate: Dictionary = pointer_context.get("target", {})
	_set_hover_candidate(candidate)
	var result: Dictionary = router.resolve_hover_candidate(candidate)
	hover_resolution_changed.emit(result.duplicate(true))
	return result


func raycast_target_from_world_ray(ray_origin: Vector3, ray_end: Vector3) -> Dictionary:
	var pointer_context: Dictionary = _resolve_pointer_ray(ray_origin, ray_end, Vector2.ZERO, false)
	var result: Dictionary = {
		"status": "PASS",
		"blocked": bool(pointer_context.get("blocked", false)),
		"blocker": str(pointer_context.get("blocker", "")),
		"authority": AUTHORITY,
	}
	var candidate: Dictionary = pointer_context.get("target", {})
	if not candidate.is_empty():
		result["target_ref"] = str(candidate.get("target_ref", ""))
		result["target_kind"] = str(candidate.get("target_kind", ""))
		result["depth_m"] = float(candidate.get("depth_m", INF))
	if pointer_context.has("ground_position"):
		result["ground_position"] = pointer_context.get("ground_position", Vector3.ZERO)
	return result


func pointer_target_at_screen(screen_position: Vector2) -> Dictionary:
	var pointer_context: Dictionary = _resolve_screen_pointer(screen_position)
	var candidate: Dictionary = pointer_context.get("target", {})
	if candidate.is_empty():
		return {
			"status": "REJECTED",
			"reason": "NO_TARGET_AT_CURSOR",
			"blocked": bool(pointer_context.get("blocked", false)),
			"authority": AUTHORITY,
		}
	return {
		"status": "PASS",
		"target_ref": str(candidate.get("target_ref", "")),
		"target_kind": str(candidate.get("target_kind", "")),
		"depth_m": float(candidate.get("depth_m", INF)),
		"screen_distance_px": float(candidate.get("screen_distance_px", INF)),
		"direct_hit": bool(candidate.get("direct_hit", false)),
		"authority": AUTHORITY,
	}


func world_to_screen(world_position: Vector3) -> Vector2:
	return camera_rig.camera.unproject_position(world_position)


func target_to_screen(target: AndromedaInteractionTarget) -> Vector2:
	if target == null:
		return Vector2.ZERO
	return world_to_screen(target.pointer_world_position())


func set_menu_open(value: bool) -> void:
	if hud != null:
		if value:
			hud.set_inventory_open(true)
		else:
			hud.close_active_modal()
	_menu_open = hud.is_any_modal_open() if hud != null else value
	if _menu_open:
		_set_hover_candidate({})
	menu_state_changed.emit(_menu_open)


func menu_open() -> bool:
	return _menu_open


func pointer_resolution_serial() -> int:
	return _pointer_resolution_serial


func last_pointer_resolution() -> Dictionary:
	return _last_pointer_resolution.duplicate(true)


func last_pointer_target_ref() -> String:
	return _last_pointer_target_ref


func selected_target_ref() -> String:
	return _selected_target_ref


func selected_target_kind() -> String:
	return _selected_target_kind


func selected_target() -> AndromedaInteractionTarget:
	if _selected_target != null and is_instance_valid(_selected_target):
		return _selected_target
	return null


func clear_selection_if_target_ref(target_ref_value: String) -> Dictionary:
	if _selected_target_ref != target_ref_value.strip_edges():
		return {
			"status": "PASS",
			"cleared": false,
			"authority": AUTHORITY,
		}
	if _selected_target != null and is_instance_valid(_selected_target):
		_selected_target.set_selected(false)
	_selected_target = null
	_selected_target_ref = ""
	_selected_target_kind = ""
	target_selection_changed.emit("", "")
	return {
		"status": "PASS",
		"cleared": true,
		"authority": AUTHORITY,
	}


func clear_current_target_projection(reason: String) -> Dictionary:
	if _selected_target != null and is_instance_valid(_selected_target):
		_selected_target.set_selected(false)
	if _hovered_target != null and is_instance_valid(_hovered_target):
		_hovered_target.set_hovered(false)
	_selected_target = null
	_selected_target_ref = ""
	_selected_target_kind = ""
	_hovered_target = null
	_hovered_target_ref = ""
	ground_loot_client.clear_client_request_tracking()
	gathering_client.clear_client_request_tracking()
	combat_authority_client.clear_client_request_tracking()
	dropped_bag_client.clear_client_request_tracking()
	target_selection_changed.emit("", "")
	return {
		"status": "PASS",
		"reason": reason,
		"target_cleared": true,
		"gameplay_state_mutated": false,
		"authority": AUTHORITY,
	}


func world_input_blocked() -> bool:
	return death_respawn_client != null and death_respawn_client.world_input_blocked()


func hovered_target_ref() -> String:
	return _hovered_target_ref


func navigation_ready() -> bool:
	var navigation_map: RID = player.get_world_3d().navigation_map
	if not navigation_map.is_valid() or NavigationServer3D.map_get_iteration_id(navigation_map) <= 0:
		return false
	var closest_probe: Vector3 = NavigationServer3D.map_get_closest_point(
		navigation_map,
		NAVIGATION_READY_PROBE
	)
	return Vector2(closest_probe.x, closest_probe.z).distance_to(
		Vector2(NAVIGATION_READY_PROBE.x, NAVIGATION_READY_PROBE.z)
	) < 0.05


func navigation_mesh_polygon_count() -> int:
	if navigation_region.navigation_mesh == null:
		return 0
	return navigation_region.navigation_mesh.get_polygon_count()


func closest_navigation_point(world_position: Vector3) -> Vector3:
	return NavigationServer3D.map_get_closest_point(player.get_world_3d().navigation_map, world_position)


func collision_layer_contract() -> Dictionary:
	return {
		"WORLD_STATIC": LAYER_WORLD_STATIC,
		"PLAYER": LAYER_PLAYER,
		"ACTOR_BODY": LAYER_ACTOR_BODY,
		"INTERACTABLE": LAYER_INTERACTABLE,
		"GROUND_LOOT": LAYER_GROUND_LOOT,
		"RESOURCE_NODE": LAYER_RESOURCE_NODE,
		"VEHICLE": LAYER_VEHICLE,
		"NAV_BLOCKER": LAYER_NAV_BLOCKER,
		"CAMERA_OCCLUDER": LAYER_CAMERA_OCCLUDER,
		"HIT_HURT_SENSOR": LAYER_HIT_HURT_SENSOR,
		"WORLD_TRIGGER": LAYER_WORLD_TRIGGER,
		"WATER_VOLUME": LAYER_WATER_VOLUME,
		"DROPPED_BAG": LAYER_DROPPED_BAG,
	}


func terrain_contract_snapshot() -> Dictionary:
	return terrain_foundation.contract_snapshot()


func terrain_surface_sample(world_position: Vector3) -> Dictionary:
	return terrain_foundation.surface_sample(world_position)


func navigation_path_for_capability(
	start_position: Vector3,
	target_position: Vector3,
	capability: String
) -> PackedVector3Array:
	return terrain_foundation.navigation_path_for_capability(start_position, target_position, capability)


func set_b04_base_route_closure(close_north_route: bool, close_south_route: bool = false) -> Dictionary:
	if close_north_route and close_south_route:
		return _rejected("CANNOT_CLOSE_ALL_BASE_ROUTES")
	_build_b02_navigation_mesh(close_north_route, close_south_route)
	return {
		"status": "PASS",
		"north_route_closed": close_north_route,
		"south_route_closed": close_south_route,
		"navigation_polygon_count": navigation_mesh_polygon_count(),
		"movement_prediction_preserved": player.has_destination(),
		"gameplay_authority_changed": false,
		"authority": AUTHORITY,
	}


func contract_snapshot() -> Dictionary:
	return {
		"main_root": name,
		"left_ground": "MOVE_TO_POINT",
		"right_ground": "MOVE_TO_POINT",
		"left_target": "SELECT_TARGET_WITHOUT_MOVEMENT_CHANGE",
		"right_hostile": "CHASE_ATTACK_FUTURE",
		"right_context": "APPROACH_INTERACT_FUTURE",
		"ground_loot_exception": true,
		"ground_loot_pickup_radius_m": AndromedaInputRouter.PICKUP_RADIUS_M,
		"target_resolution_order": ["SCREEN_DISTANCE", "DEPTH", "SEMANTIC_TIEBREAK", "TARGET_REF"],
		"semantic_priority_is_tiebreak_only": true,
		"camera_feedback_cannot_rewrite_selection": true,
		"gameplay_authority_in_gdscript": false,
		"backend_substitute": false,
		"backend_command_submission_in_b03": false,
		"terrain_foundation_present": terrain_foundation != null,
		"terrain_traversal_authority_in_gdscript": false,
		"hud_foundation_present": hud != null,
		"hud_gameplay_authority_in_gdscript": false,
		"weapon_command_transport_submitted_in_b05": false,
		"dialogue_narrative_authored_in_gdscript": false,
		"combat_presentation_present": hud != null and hud.enemy_bar_count() == 2,
		"combat_outcome_calculated_in_gdscript": false,
		"combat_snapshot_mutated_in_gdscript": false,
		"global_hit_stop": false,
		"ground_loot_client_present": ground_loot_client != null,
		"ground_loot_request_authority_in_gdscript": false,
		"ground_loot_inventory_authority_in_gdscript": false,
		"ground_loot_ttl_authority_in_gdscript": false,
		"gathering_client_present": gathering_client != null,
		"gathering_yield_authority_in_gdscript": false,
		"gathering_quantity_authority_in_gdscript": false,
		"gathering_tool_authority_in_gdscript": false,
		"gathering_stamina_authority_in_gdscript": false,
		"gathering_depletion_authority_in_gdscript": false,
		"gathering_respawn_authority_in_gdscript": false,
		"gathering_inventory_authority_in_gdscript": false,
		"vendor_client_present": vendor_client != null,
		"inventory_client_present": inventory_client != null,
		"quest_client_present": quest_client != null,
		"vendor_click_auto_purchase": false,
		"vendor_approach_auto_purchase": false,
		"vendor_quote_auto_execute": false,
		"vendor_price_authority_in_gdscript": false,
		"vendor_wallet_authority_in_gdscript": false,
		"inventory_authority_in_gdscript": false,
		"bag_authority_in_gdscript": false,
		"quest_completion_authority_in_gdscript": false,
		"quest_reward_authority_in_gdscript": false,
		"save_reload_client_present": save_reload_client != null,
		"death_respawn_client_present": death_respawn_client != null,
		"dropped_bag_client_present": dropped_bag_client != null,
		"save_authority_in_gdscript": false,
		"death_authority_in_gdscript": false,
		"dropped_bag_authority_in_gdscript": false,
		"ownership_authority_in_gdscript": false,
		"water_ttl_authority_in_gdscript": false,
		"respawn_point_authority_in_gdscript": false,
		"b11_vertical_slice_client_present": b11_vertical_slice_client != null,
		"b11_performance_probe_present": b11_performance_probe != null,
		"b11_harness_runs_automatically": false,
		"b11_fixture_is_authoritative_roundtrip": false,
		"authority": AUTHORITY,
	}


func run_b11_integrated_vertical_slice(session_ref: String = "B11-INTEGRATED-SESSION") -> Dictionary:
	if b11_vertical_slice_client == null:
		return _rejected("B11_VERTICAL_SLICE_CLIENT_NOT_FOUND")
	return await b11_vertical_slice_client.run_integrated_vertical_slice(session_ref)


func _on_hud_modal_state_changed(_layer: String, _open: bool) -> void:
	_menu_open = hud.is_any_modal_open()
	if _menu_open:
		_set_hover_candidate({})


func _resolve_screen_pointer(screen_position: Vector2) -> Dictionary:
	var camera: Camera3D = camera_rig.camera
	var ray_origin: Vector3 = camera.project_ray_origin(screen_position)
	var ray_end: Vector3 = ray_origin + camera.project_ray_normal(screen_position) * RAY_LENGTH_M
	return _resolve_pointer_ray(ray_origin, ray_end, screen_position, true)


func _resolve_pointer_ray(
	ray_origin: Vector3,
	ray_end: Vector3,
	screen_position: Vector2,
	measure_screen_distance: bool
) -> Dictionary:
	var router := get_node_or_null("/root/InputRouter") as AndromedaInputRouter
	if router == null:
		return {}
	var excluded_rids: Array[RID] = [player.get_rid()]
	var candidates_by_ref: Dictionary = {}
	var ground_position: Variant = null
	var blocked: bool = false
	var blocker_name: String = ""
	var ray_length: float = ray_origin.distance_to(ray_end)
	for _hit_index: int in range(POINTER_MAX_HITS):
		var query: PhysicsRayQueryParameters3D = PhysicsRayQueryParameters3D.create(
			ray_origin,
			ray_end,
			POINTER_COLLISION_MASK,
			excluded_rids
		)
		query.collide_with_areas = true
		query.collide_with_bodies = true
		var hit: Dictionary = get_viewport().world_3d.direct_space_state.intersect_ray(query)
		if hit.is_empty():
			break
		var collider_value: Variant = hit.get("collider")
		if not collider_value is CollisionObject3D:
			break
		var collider: CollisionObject3D = collider_value
		excluded_rids.append(collider.get_rid())
		var target_ref: String = str(collider.get_meta("target_ref", "")).strip_edges()
		if not target_ref.is_empty():
			var candidate: Dictionary = _candidate_from_hit(
				hit,
				collider,
				ray_origin,
				screen_position,
				measure_screen_distance
			)
			var existing: Dictionary = candidates_by_ref.get(target_ref, {})
			if existing.is_empty() or float(candidate.get("depth_m", ray_length)) < float(existing.get("depth_m", ray_length)):
				candidates_by_ref[target_ref] = candidate
			continue
		var pointer_kind: String = str(collider.get_meta("pointer_kind", "")).to_upper()
		if pointer_kind == AndromedaInputRouter.HIT_GROUND:
			ground_position = hit.get("position", Vector3.ZERO)
			break
		if bool(collider.get_meta("pointer_blocker", false)) or (
			collider.collision_layer & (LAYER_WORLD_STATIC | LAYER_NAV_BLOCKER)
		) != 0:
			blocked = true
			blocker_name = collider.name
			break
	var candidates: Array[Dictionary] = []
	for candidate_value: Variant in candidates_by_ref.values():
		if candidate_value is Dictionary:
			candidates.append(candidate_value)
	var chosen: Dictionary = router.choose_pointer_target(candidates)
	var result: Dictionary = {
		"target": chosen,
		"candidate_count": candidates.size(),
		"blocked": blocked,
		"blocker": blocker_name,
	}
	if ground_position is Vector3:
		result["ground_position"] = ground_position
	return result


func _candidate_from_hit(
	hit: Dictionary,
	collider: CollisionObject3D,
	ray_origin: Vector3,
	screen_position: Vector2,
	measure_screen_distance: bool
) -> Dictionary:
	var hit_position: Vector3 = hit.get("position", collider.global_position)
	var target_world_position: Vector3 = collider.global_position
	var owner_instance_id: int = int(collider.get_meta("target_owner_instance_id", 0))
	if owner_instance_id > 0:
		var owner_value: Object = instance_from_id(owner_instance_id)
		if owner_value is AndromedaInteractionTarget:
			var interaction_target := owner_value as AndromedaInteractionTarget
			target_world_position = interaction_target.pointer_world_position()
	var screen_distance_px: float = 0.0
	if measure_screen_distance:
		screen_distance_px = screen_position.distance_to(world_to_screen(target_world_position))
	return {
		"target_ref": str(collider.get_meta("target_ref", "")),
		"target_kind": str(collider.get_meta("pointer_kind", "")).to_upper(),
		"hostile": bool(collider.get_meta("hostile", false)),
		"resource_kind": str(collider.get_meta("resource_kind", "")),
		"ground_loot_settled": bool(collider.get_meta("ground_loot_settled", true)),
		"selectable": bool(collider.get_meta("selectable", true)),
		"owner_instance_id": owner_instance_id,
		"target_world_position": target_world_position,
		"hit_position": hit_position,
		"screen_distance_px": screen_distance_px,
		"depth_m": ray_origin.distance_to(hit_position),
		"direct_hit": true,
	}


func _set_hover_candidate(candidate: Dictionary) -> void:
	var next_ref: String = str(candidate.get("target_ref", ""))
	var next_target: AndromedaInteractionTarget = _candidate_owner(candidate)
	if _hovered_target == next_target and _hovered_target_ref == next_ref:
		return
	if _hovered_target != null and is_instance_valid(_hovered_target):
		_hovered_target.set_hovered(false)
	_hovered_target = next_target
	_hovered_target_ref = next_ref
	if _hovered_target != null and is_instance_valid(_hovered_target):
		_hovered_target.set_hovered(true)


func _select_candidate(candidate: Dictionary) -> void:
	var next_ref: String = str(candidate.get("target_ref", ""))
	var next_kind: String = str(candidate.get("target_kind", ""))
	var next_target: AndromedaInteractionTarget = _candidate_owner(candidate)
	if _selected_target != null and is_instance_valid(_selected_target) and _selected_target != next_target:
		_selected_target.set_selected(false)
	_selected_target = next_target
	_selected_target_ref = next_ref
	_selected_target_kind = next_kind
	if _selected_target != null and is_instance_valid(_selected_target):
		_selected_target.set_selected(true)
	target_selection_changed.emit(_selected_target_ref, _selected_target_kind)


func _candidate_owner(candidate: Dictionary) -> AndromedaInteractionTarget:
	var owner_instance_id: int = int(candidate.get("owner_instance_id", 0))
	if owner_instance_id <= 0:
		return null
	var owner_value: Object = instance_from_id(owner_instance_id)
	return owner_value as AndromedaInteractionTarget


func _build_interaction_envelope(resolved: Dictionary, world_position: Vector3) -> Dictionary:
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if bridge == null:
		return _rejected("BRIDGE_AUTOLOAD_NOT_FOUND")
	var intent: String = str(resolved.get("intent", "")).to_upper()
	if intent.is_empty():
		return _rejected("EMPTY_INTERACTION_INTENT")
	return bridge.build_command_envelope(intent, {
		"target_ref": str(resolved.get("target_ref", "")),
		"target_kind": str(resolved.get("target_kind", "")),
		"button": str(resolved.get("button", "")),
		"world_point": {
			"iso_x_m": world_position.x,
			"iso_y_m": world_position.z,
			"altitude_m": world_position.y,
		},
		"client_presentation_only": true,
	})


func _commit_pointer_resolution(result: Dictionary) -> Dictionary:
	_pointer_resolution_serial += 1
	_last_pointer_resolution = result.duplicate(true)
	if result.has("target_ref"):
		_last_pointer_target_ref = str(result.get("target_ref", ""))
	pointer_resolution_committed.emit(_last_pointer_resolution.duplicate(true))
	return result


func _build_b02_navigation_mesh(close_north_route: bool = false, close_south_route: bool = false) -> void:
	var navigation_mesh := NavigationMesh.new()
	navigation_mesh.agent_radius = 0.35
	navigation_mesh.agent_height = 1.8
	navigation_mesh.agent_max_slope = 32.0
	navigation_mesh.agent_max_climb = 0.35
	var x_coordinates := PackedFloat32Array([-12.0, -1.75, 1.75, 12.0])
	var z_coordinates := PackedFloat32Array([-12.0, -4.75, 4.75, 12.0])
	var vertices := PackedVector3Array()
	for z_value: float in z_coordinates:
		for x_value: float in x_coordinates:
			vertices.append(Vector3(x_value, 0.0, z_value))
	navigation_mesh.set_vertices(vertices)
	for z_index: int in range(3):
		for x_index: int in range(3):
			if x_index == 1 and z_index == 1:
				continue
			if close_north_route and x_index == 1 and z_index == 2:
				continue
			if close_south_route and x_index == 1 and z_index == 0:
				continue
			var top_left: int = z_index * 4 + x_index
			var bottom_left: int = (z_index + 1) * 4 + x_index
			var bottom_right: int = (z_index + 1) * 4 + x_index + 1
			var top_right: int = z_index * 4 + x_index + 1
			navigation_mesh.add_polygon(PackedInt32Array([
				top_left,
				bottom_left,
				bottom_right,
				top_right,
			]))
	navigation_region.navigation_mesh = navigation_mesh


func _rejected(reason: String, detail: Dictionary = {}) -> Dictionary:
	var result: Dictionary = {"status": "REJECTED", "reason": reason, "authority": AUTHORITY}
	result.merge(detail, true)
	return result
