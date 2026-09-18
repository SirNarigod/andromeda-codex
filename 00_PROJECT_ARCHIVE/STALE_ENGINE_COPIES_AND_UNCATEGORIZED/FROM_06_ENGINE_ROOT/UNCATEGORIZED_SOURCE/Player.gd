extends CharacterBody3D
class_name AndromedaPrototypePlayer

signal prototype_command(command: String, params: Dictionary)
signal world_message(text: String)

const WALK_SPEED := 5.0
const RUN_SPEED := 8.0
const ACCELERATION := 22.0
const INTERACTION_DISTANCE := 2.7
const ATTACK_DISTANCE := 2.8
const PATH_POINT_DISTANCE := 0.28
const CLICK_RAY_DISTANCE := 2000.0
const ATTACK_INTERVAL_S := 2.0
const RANGED_SETTLE_TIME_S := 0.18
const RANGED_RETREAT_TIME_S := 0.32
const RANGED_RETREAT_STEP_M := 2.20
const STAMINA_REGEN_RATE := 8.0
const STAMINA_REGEN_DELAY_AFTER_ATTACK_S := 1.40

const SHOP_CATALOGS := {
    "WEAPONS": [
        {"name": "Espada de Oficina", "price": 30, "type": "WEAPON"},
        {"name": "Espada do Vigia Caído", "price": 55, "type": "WEAPON"},
        {"name": "Arco de Galho Negro", "price": 45, "type": "WEAPON"},
        {"name": "Besta de Ferrolho Antiga", "price": 70, "type": "WEAPON"},
        {"name": "Chicote de Corrente Velária", "price": 60, "type": "WEAPON"}
    ],
    "ARMOR": [
        {"name": "Colete de Couro Reforçado", "price": 45, "type": "ARMOR", "protection_bonus": 12},
        {"name": "Armadura de Vigília", "price": 80, "type": "ARMOR", "protection_bonus": 25},
        {"name": "Couraça de Teste", "price": 120, "type": "ARMOR", "protection_bonus": 40}
    ],
    "COSMETICS": [
        {"name": "Broche Vital", "price": 55, "type": "COSMETIC", "hp_bonus": 20},
        {"name": "Pulseira Guardiã", "price": 50, "type": "COSMETIC", "protection_bonus": 15},
        {"name": "Faixa do Corredor", "price": 50, "type": "COSMETIC", "stamina_bonus": 20},
        {"name": "Pingente Trino", "price": 100, "type": "COSMETIC", "hp_bonus": 10, "protection_bonus": 10, "stamina_bonus": 10}
    ]
}
const TARGET_REPATH_INTERVAL_S := 0.60
const TARGET_REPATH_DISTANCE_M := 1.20
const HOVER_REFRESH_S := 0.08
const INTERACTION_DEBOUNCE_S := 0.18
const HOLD_MOVE_REFRESH_S := 0.12
const HOLD_MOVE_MIN_WORLD_DELTA_M := 0.65
const CLICK_HOLD_THRESHOLD_S := 0.18

const WEAPON_PROFILES := {
    "Espada de Oficina": {
        "combat_class": "MELEE",
        "damage": 24,
        "stamina_cost": 12,
        "shield_damage_factor": 0.80,
        "hp_through_shield_factor": 0.00,
        "attack_range_m": 2.80,
        "min_range_m": 0.00,
        "durability_max": 70,
        "power": 64,
        "defense": 70,
        "utility": 66,
        "handling": 64,
        "durability_stat": 70,
        "reach_stat": 35,
        "magic_affinity": 68,
        "tech_affinity": 75,
        "overall": 68,
        "rarity": "COMUM",
        "projectile": "",
        "authority": "DERIVAÇÃO_DEV_DE_WPN-003_LÂMINA_DE_OFICINA",
    },
    "Espada do Vigia Caído": {
        "combat_class": "MELEE",
        "damage": 32,
        "stamina_cost": 16,
        "shield_damage_factor": 0.70,
        "hp_through_shield_factor": 0.18,
        "attack_range_m": 2.90,
        "min_range_m": 0.00,
        "durability_max": 48,
        "power": 68,
        "defense": 56,
        "utility": 50,
        "handling": 58,
        "durability_stat": 48,
        "reach_stat": 40,
        "magic_affinity": 42,
        "tech_affinity": 45,
        "overall": 55,
        "rarity": "INCOMUM_DESGASTADA",
        "projectile": "",
        "authority": "PROPOSTA_DEV_FIRST_PLAYABLE",
    },
    "Arco de Galho Negro": {
        "combat_class": "RANGED",
        "damage": 20,
        "stamina_cost": 9,
        "shield_damage_factor": 0.42,
        "hp_through_shield_factor": 0.28,
        "attack_range_m": 9.00,
        "min_range_m": 4.50,
        "durability_max": 40,
        "power": 54,
        "defense": 59,
        "utility": 52,
        "handling": 60,
        "durability_stat": 40,
        "reach_stat": 35,
        "magic_affinity": 65,
        "tech_affinity": 73,
        "overall": 60,
        "rarity": "INCOMUM",
        "projectile": "FLECHA",
        "authority": "DERIVAÇÃO_DEV_DE_WPN-024_ARCO_DE_LUZ",
    },
    "Besta de Ferrolho Antiga": {
        "combat_class": "RANGED",
        "damage": 32,
        "stamina_cost": 18,
        "shield_damage_factor": 0.85,
        "hp_through_shield_factor": 0.14,
        "attack_range_m": 10.50,
        "min_range_m": 5.30,
        "durability_max": 55,
        "power": 72,
        "defense": 48,
        "utility": 58,
        "handling": 52,
        "durability_stat": 55,
        "reach_stat": 75,
        "magic_affinity": 38,
        "tech_affinity": 62,
        "overall": 61,
        "rarity": "INCOMUM_ANTIGA",
        "projectile": "VIROTE",
        "authority": "PROPOSTA_DEV_FIRST_PLAYABLE",
    },
    "Chicote de Corrente Velária": {
        "combat_class": "MID_MELEE",
        "damage": 22,
        "stamina_cost": 11,
        "shield_damage_factor": 0.60,
        "hp_through_shield_factor": 0.00,
        "attack_range_m": 4.50,
        "min_range_m": 0.00,
        "durability_max": 60,
        "power": 58,
        "defense": 45,
        "utility": 70,
        "handling": 68,
        "durability_stat": 60,
        "reach_stat": 65,
        "magic_affinity": 55,
        "tech_affinity": 50,
        "overall": 59,
        "rarity": "INCOMUM",
        "projectile": "",
        "authority": "PROPOSTA_DEV_FIRST_PLAYABLE",
    },
}

var gravity: float = 9.8
var max_health: int = 100
var health: int = 100
var max_stamina: float = 100.0
var stamina: float = 100.0
var max_protection: int = 60
var protection: int = 60
var coins: int = 600
var inventory: Array[String] = []
var _inventory_categories: Dictionary = {}
var lore: Array[String] = []
var equipped_weapon: String = ""
var torch_on: bool = false
var in_dungeon: bool = false
var sitting: bool = false
var _seated_target: Node3D

var _message_time: float = 0.0
var _status_label: Label
var _message_label: Label
var _health_bar: ProgressBar
var _stamina_bar: ProgressBar
var _protection_bar: ProgressBar
var _inventory_panel: ColorRect
var _shop_panel: ColorRect
var _shop_title: Label
var _shop_item_list: VBoxContainer
var _shop_detail: Label
var _shop_buy_button: Button
var _shop_catalog_id: String = ""
var _shop_name: String = ""
var _shop_selected_index: int = -1
var _purchased_shop_items: Dictionary = {}
var _inventory_label: Label
var _inventory_weapon_list: VBoxContainer
var _inventory_open: bool = false
var _inventory_ui_dirty: bool = true
var _weapon_durability: Dictionary = {}
var _torch_light: OmniLight3D
var _camera: Camera3D
var _command_accumulator: float = 0.0
var _target_marker: MeshInstance3D
var _marker_pending_position: Vector3 = Vector3.ZERO
var _marker_pending_mode: String = "MOVE"
var _marker_pending_update: bool = false
var _selected_target: Node3D
var _selection_marker: MeshInstance3D
var _pending_left_click: bool = false
var _pending_right_click: bool = false
var _pending_left_release: bool = false
var _pending_left_position: Vector2 = Vector2.ZERO
var _pending_right_position: Vector2 = Vector2.ZERO
var _left_mouse_held: bool = false
var _press_candidate_button: int = 0
var _press_candidate_elapsed: float = 0.0
var _press_candidate_position: Vector2 = Vector2.ZERO
var _press_candidate_ground: bool = false
var _hold_move_active: bool = false
var _hold_move_button: int = 0
var _hold_move_refresh: float = 0.0
var _hold_last_world_point: Vector3 = Vector3.ZERO
var _hold_has_world_point: bool = false

var _path_points: Array[Vector3] = []
var _path_index: int = 0
var _click_run: bool = false

var _action_kind: String = ""
var _action_target: Node3D
var _attack_cooldown: float = 0.0
var _stamina_regen_delay: float = 0.0
var _ranged_cycle_state: String = "READY"
var _ranged_retreat_source: Node3D
var _ranged_retreat_timer: float = 0.0
var _ranged_settle_timer: float = 0.0
var _target_repath_timer: float = 0.0
var _last_target_position: Vector3 = Vector3.ZERO
var _hover_panel: ColorRect
var _hover_label: Label
var _hover_timer: float = 0.0
var _last_hover_target: Node3D
var _pending_interaction_target: Node3D
var _pending_interaction_distance: float = 0.0
var _interaction_dispatch_scheduled: bool = false
var _interaction_cooldown: float = 0.0

func _ready() -> void:
    add_to_group("player")
    collision_layer = 1
    collision_mask = 1
    gravity = float(ProjectSettings.get_setting("physics/3d/default_gravity", 9.8))
    _build_body()
    _build_camera()
    _build_move_marker()
    _build_selection_marker()
    _build_hud()
    _update_hud()
    show_message("Esquerdo no chão move; em alvo apenas seleciona e preserva o movimento atual. E interage; Espaço ataca inimigo selecionado.")

func _build_body() -> void:
    var collision := CollisionShape3D.new()
    collision.name = "PlayerCollision"
    var capsule := CapsuleShape3D.new()
    capsule.radius = 0.45
    capsule.height = 1.8
    collision.shape = capsule
    add_child(collision)

    var visual := MeshInstance3D.new()
    visual.name = "PlayerMesh"
    var mesh := CapsuleMesh.new()
    mesh.radius = 0.45
    mesh.height = 1.8
    visual.mesh = mesh
    var material := StandardMaterial3D.new()
    material.albedo_color = Color(0.78, 0.88, 1.0)
    material.roughness = 0.65
    visual.material_override = material
    add_child(visual)

    _torch_light = OmniLight3D.new()
    _torch_light.name = "TorchLight"
    _torch_light.light_color = Color(1.0, 0.68, 0.30)
    _torch_light.light_energy = 0.0
    _torch_light.omni_range = 10.0
    _torch_light.position = Vector3(0.45, 0.8, 0.0)
    add_child(_torch_light)

func _build_camera() -> void:
    _camera = Camera3D.new()
    _camera.name = "IsometricCamera"
    _camera.projection = Camera3D.PROJECTION_ORTHOGONAL
    _camera.size = 18.0
    _camera.current = true
    add_child(_camera)

func _build_move_marker() -> void:
    _target_marker = MeshInstance3D.new()
    _target_marker.name = "MoveTargetMarker"
    var mesh := CylinderMesh.new()
    mesh.top_radius = 0.24
    mesh.bottom_radius = 0.24
    mesh.height = 0.018
    _target_marker.mesh = mesh
    var material := StandardMaterial3D.new()
    material.albedo_color = Color(0.35, 0.95, 0.55, 0.42)
    material.emission_enabled = true
    material.emission = Color(0.08, 0.34, 0.14)
    material.emission_energy_multiplier = 0.45
    material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
    _target_marker.material_override = material
    _target_marker.visible = false
    _target_marker.tree_entered.connect(_on_target_marker_tree_entered)
    var parent_node := get_parent()
    if parent_node != null:
        parent_node.add_child.call_deferred(_target_marker)

func _build_selection_marker() -> void:
    _selection_marker = MeshInstance3D.new()
    _selection_marker.name = "WorldSelectionMarker"

    var mesh := CylinderMesh.new()
    mesh.top_radius = 0.72
    mesh.bottom_radius = 0.72
    mesh.height = 0.016
    _selection_marker.mesh = mesh

    var material := StandardMaterial3D.new()
    material.albedo_color = Color(1.0, 0.72, 0.16, 0.28)
    material.emission_enabled = true
    material.emission = Color(0.48, 0.22, 0.03)
    material.emission_energy_multiplier = 0.32
    material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
    material.roughness = 0.72
    _selection_marker.material_override = material
    _selection_marker.visible = false

    # Mesmo padrão seguro usado pelo marcador de movimento: o world pode
    # ainda estar montando filhos durante o _ready do Player.
    var parent_node := get_parent()
    if parent_node != null:
        parent_node.add_child.call_deferred(_selection_marker)

func _make_player_resource_bar(parent: Control, label_text: String, y: float, max_value: float, current_value: float) -> ProgressBar:
    var label := Label.new()
    label.position = Vector2(10, y - 2.0)
    label.size = Vector2(54, 16)
    label.text = label_text
    label.add_theme_font_size_override("font_size", 10)
    label.mouse_filter = Control.MOUSE_FILTER_IGNORE
    parent.add_child(label)

    var bar := ProgressBar.new()
    bar.position = Vector2(64, y)
    bar.size = Vector2(210, 12)
    bar.min_value = 0.0
    bar.max_value = max_value
    bar.value = current_value
    bar.show_percentage = false
    bar.mouse_filter = Control.MOUSE_FILTER_IGNORE
    parent.add_child(bar)
    return bar

func _build_hud() -> void:
    var canvas := CanvasLayer.new()
    canvas.name = "HUD"
    add_child(canvas)

    var panel := ColorRect.new()
    panel.name = "PlayerStatusPanel"
    panel.color = Color(0.025, 0.035, 0.055, 0.72)
    panel.position = Vector2(12, 12)
    panel.size = Vector2(300, 128)
    canvas.add_child(panel)

    _health_bar = _make_player_resource_bar(panel, "HP", 10.0, float(max_health), float(health))
    _stamina_bar = _make_player_resource_bar(panel, "STA", 30.0, max_stamina, stamina)
    _protection_bar = _make_player_resource_bar(panel, "PROT", 50.0, float(max_protection), float(protection))

    _status_label = Label.new()
    _status_label.position = Vector2(10, 72)
    _status_label.size = Vector2(280, 48)
    _status_label.add_theme_font_size_override("font_size", 10)
    _status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    panel.add_child(_status_label)

    var controls := Label.new()
    controls.text = "LMB chão:mover | LMB alvo:selecionar | E:interagir | Espaço:atacar | RMB:contextual | I:inventário"
    controls.position = Vector2(12, 686)
    controls.size = Vector2(1000, 20)
    controls.add_theme_font_size_override("font_size", 10)
    canvas.add_child(controls)

    _inventory_panel = ColorRect.new()
    _inventory_panel.name = "InventoryPanel"
    _inventory_panel.color = Color(0.025, 0.035, 0.055, 0.96)
    _inventory_panel.position = Vector2(790, 52)
    _inventory_panel.size = Vector2(470, 610)
    _inventory_panel.visible = false
    _inventory_panel.mouse_filter = Control.MOUSE_FILTER_STOP
    _inventory_panel.z_index = 35
    canvas.add_child(_inventory_panel)

    var inventory_title := Label.new()
    inventory_title.name = "InventoryTitle"
    inventory_title.position = Vector2(18, 14)
    inventory_title.size = Vector2(434, 30)
    inventory_title.text = "INVENTÁRIO — clique em uma arma para equipar"
    inventory_title.mouse_filter = Control.MOUSE_FILTER_IGNORE
    _inventory_panel.add_child(inventory_title)

    _inventory_weapon_list = VBoxContainer.new()
    _inventory_weapon_list.name = "WeaponList"
    _inventory_weapon_list.position = Vector2(18, 50)
    _inventory_weapon_list.size = Vector2(434, 240)
    _inventory_weapon_list.mouse_filter = Control.MOUSE_FILTER_STOP
    _inventory_panel.add_child(_inventory_weapon_list)

    _inventory_label = Label.new()
    _inventory_label.position = Vector2(18, 300)
    _inventory_label.size = Vector2(434, 292)
    _inventory_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    _inventory_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
    _inventory_panel.add_child(_inventory_label)

    _shop_panel = ColorRect.new()
    _shop_panel.name = "ShopPanel"
    _shop_panel.color = Color(0.025, 0.035, 0.055, 0.97)
    _shop_panel.position = Vector2(350, 70)
    _shop_panel.size = Vector2(580, 500)
    _shop_panel.visible = false
    _shop_panel.mouse_filter = Control.MOUSE_FILTER_STOP
    _shop_panel.z_index = 50
    canvas.add_child(_shop_panel)

    _shop_title = Label.new()
    _shop_title.position = Vector2(18, 14)
    _shop_title.size = Vector2(450, 28)
    _shop_title.text = "LOJA"
    _shop_panel.add_child(_shop_title)

    var close_button := Button.new()
    close_button.position = Vector2(500, 10)
    close_button.size = Vector2(62, 30)
    close_button.text = "FECHAR"
    close_button.pressed.connect(_close_shop)
    _shop_panel.add_child(close_button)

    _shop_item_list = VBoxContainer.new()
    _shop_item_list.position = Vector2(18, 54)
    _shop_item_list.size = Vector2(250, 380)
    _shop_panel.add_child(_shop_item_list)

    _shop_detail = Label.new()
    _shop_detail.position = Vector2(290, 60)
    _shop_detail.size = Vector2(270, 300)
    _shop_detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    _shop_panel.add_child(_shop_detail)

    _shop_buy_button = Button.new()
    _shop_buy_button.position = Vector2(320, 390)
    _shop_buy_button.size = Vector2(210, 46)
    _shop_buy_button.text = "COMPRAR"
    _shop_buy_button.disabled = true
    _shop_buy_button.pressed.connect(_on_shop_buy_pressed)
    _shop_panel.add_child(_shop_buy_button)

    var shop_hint := Label.new()
    shop_hint.position = Vector2(18, 450)
    shop_hint.size = Vector2(540, 30)
    shop_hint.text = "Selecione um item, confira atributos e preço, depois use COMPRAR."
    shop_hint.add_theme_font_size_override("font_size", 11)
    _shop_panel.add_child(shop_hint)

    _hover_panel = ColorRect.new()
    _hover_panel.name = "HoverInfo"
    _hover_panel.color = Color(0.02, 0.03, 0.05, 0.92)
    _hover_panel.size = Vector2(285, 68)
    _hover_panel.visible = false
    _hover_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
    _hover_panel.z_index = 40
    canvas.add_child(_hover_panel)

    _hover_label = Label.new()
    _hover_label.position = Vector2(10, 7)
    _hover_label.size = Vector2(265, 54)
    _hover_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    _hover_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
    _hover_panel.add_child(_hover_label)

    _message_label = Label.new()
    _message_label.position = Vector2(365, 610)
    _message_label.size = Vector2(560, 52)
    _message_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    _message_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    canvas.add_child(_message_label)


func _physics_process(delta: float) -> void:
    if _pending_left_click:
        _pending_left_click = false
        _handle_left_press(_pending_left_position)
    if _pending_right_click:
        _pending_right_click = false
        _handle_right_press(_pending_right_position)
    if _pending_left_release:
        _pending_left_release = false
        _handle_pointer_release(MOUSE_BUTTON_LEFT)
    _attack_cooldown = maxf(0.0, _attack_cooldown - delta)
    _stamina_regen_delay = maxf(0.0, _stamina_regen_delay - delta)
    _ranged_retreat_timer = maxf(0.0, _ranged_retreat_timer - delta)
    _ranged_settle_timer = maxf(0.0, _ranged_settle_timer - delta)
    _update_press_candidate(delta)
    _update_hold_movement(delta)
    _target_repath_timer = maxf(0.0, _target_repath_timer - delta)
    _interaction_cooldown = maxf(0.0, _interaction_cooldown - delta)
    _update_ranged_damage_reaction()
    _update_target_action()
    _update_selected_target()

    _hover_timer = maxf(0.0, _hover_timer - delta)
    if _hover_timer <= 0.0:
        _hover_timer = HOVER_REFRESH_S
        _update_hover_tooltip(get_viewport().get_mouse_position())

    var input_vec := Vector2.ZERO

    # WASD permanece apenas como fallback de debug.
    if Input.is_key_pressed(KEY_A): input_vec.x -= 1.0
    if Input.is_key_pressed(KEY_D): input_vec.x += 1.0
    if Input.is_key_pressed(KEY_W): input_vec.y -= 1.0
    if Input.is_key_pressed(KEY_S): input_vec.y += 1.0
    input_vec = input_vec.normalized()
    if input_vec.length() > 0.0:
        _cancel_all_actions(false)
        if sitting:
            sitting = false
            show_message("Você se levantou.")

    if sitting:
        velocity.x = move_toward(velocity.x, 0.0, ACCELERATION * delta)
        velocity.z = move_toward(velocity.z, 0.0, ACCELERATION * delta)
    else:
        if input_vec.length() <= 0.0:
            input_vec = _path_direction()

        var running := (_click_run or Input.is_key_pressed(KEY_SHIFT)) and stamina > 0.5 and input_vec.length() > 0.0
        var target_speed := RUN_SPEED if running else WALK_SPEED
        if running:
            stamina = maxf(0.0, stamina - 22.0 * delta)
        elif _stamina_regen_delay <= 0.0:
            stamina = minf(max_stamina, stamina + STAMINA_REGEN_RATE * delta)

        var world_dir := Vector3(input_vec.x, 0.0, input_vec.y)
        velocity.x = move_toward(velocity.x, world_dir.x * target_speed, ACCELERATION * delta)
        velocity.z = move_toward(velocity.z, world_dir.z * target_speed, ACCELERATION * delta)
        if not is_on_floor():
            velocity.y -= gravity * delta
        else:
            velocity.y = -0.5
        move_and_slide()

        if world_dir.length_squared() > 0.0001:
            var desired_yaw := atan2(world_dir.x, world_dir.z)
            rotation.y = lerp_angle(rotation.y, desired_yaw, clampf(10.0 * delta, 0.0, 1.0))

        _command_accumulator += delta
        if input_vec.length() > 0.0 and _command_accumulator >= 0.5:
            _command_accumulator = 0.0
            prototype_command.emit("MOVE_VECTOR", {"dx": input_vec.x, "dy": input_vec.y, "duration_s": 0.5, "mode": "RUN" if running else "WALK"})

    if is_instance_valid(_camera):
        _camera.global_position = global_position + Vector3(10.0, 14.0, 10.0)
        _camera.look_at(global_position + Vector3(0.0, 0.7, 0.0), Vector3.UP)

    if _message_time > 0.0:
        _message_time -= delta
        if _message_time <= 0.0:
            _message_label.text = ""
    _update_hud()

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventMouseButton:
        var mouse_event := event as InputEventMouseButton
        if mouse_event.button_index == MOUSE_BUTTON_LEFT:
            _left_mouse_held = mouse_event.pressed
            if mouse_event.pressed:
                _pending_left_position = mouse_event.position
                _pending_left_click = true
            else:
                _pending_left_release = true
            return
        if mouse_event.button_index == MOUSE_BUTTON_RIGHT:
            # V0.1.13: botão direito é somente clique. Não entra em modo hold.
            if mouse_event.pressed:
                _pending_right_position = mouse_event.position
                _pending_right_click = true
            return

    if not (event is InputEventKey):
        return
    var key := event as InputEventKey
    if not key.pressed or key.echo:
        return
    match key.keycode:
        KEY_E:
            _interact_selected_target()
        KEY_F:
            _attack()
        KEY_SPACE:
            _attack_selected_target()
        KEY_T:
            toggle_torch()
        KEY_I:
            toggle_inventory()
        KEY_ESCAPE:
            _cancel_all_actions(true)

func _handle_left_press(screen_position: Vector2) -> void:
    if sitting:
        stand_up(true)

    # Transições de cenário continuam sendo a exceção aprovada:
    # o esquerdo aproxima e atravessa em vez de apenas selecionar.
    var transition_target := _transition_target_at(screen_position)
    if transition_target != null:
        _clear_press_candidate()
        _stop_hold_movement(false)
        _begin_target_action(transition_target, "INTERACT")
        return

    # V0.1.23:
    # clicar em qualquer alvo selecionável APENAS troca a seleção.
    # Se já existe um movimento em andamento, o caminho/destino é preservado.
    # Se o jogador está parado, ele permanece parado.
    var selectable_target := _selectable_target_at(screen_position)
    if selectable_target != null:
        _select_target(selectable_target)
        return

    # Somente chão vazio cria ou troca o destino de movimento.
    _begin_pointer_move_press(MOUSE_BUTTON_LEFT, screen_position)

func _handle_right_press(screen_position: Vector2) -> void:
    if sitting:
        stand_up(true)

    var target := _context_target_at(screen_position)
    if target != null:
        # Ação contextual é um comando completo por clique: o jogador pode soltar
        # imediatamente e o personagem seguirá até o alvo para concluir a ação.
        _clear_press_candidate()
        _stop_hold_movement(false)
        if target.is_in_group("interactable"):
            _begin_target_action(target, "INTERACT")
            return
        if target.is_in_group("wildlife"):
            if target.has_method("is_enemy") and bool(target.call("is_enemy")):
                _begin_target_action(target, "ATTACK")
            else:
                _begin_target_action(target, "INSPECT")
            return
        if target.is_in_group("hoverable"):
            _begin_target_action(target, "INSPECT")
            return

    # V0.1.13: direito em chão vazio é somente clique de movimento.
    # Não entra no detector de hold; o caminho continua sozinho até o destino.
    _cancel_target_action(false)
    _stop_hold_movement(false)
    _clear_press_candidate()
    _set_click_move_destination(screen_position, MOUSE_BUTTON_RIGHT)

func _begin_pointer_move_press(button: int, screen_position: Vector2) -> void:
    if sitting:
        stand_up(true)
    _cancel_target_action(false)
    _stop_hold_movement(false)
    _clear_path(false)
    _press_candidate_button = button
    _press_candidate_elapsed = 0.0
    _press_candidate_position = screen_position
    _press_candidate_ground = _set_click_move_destination(screen_position, button)

func _set_click_move_destination(screen_position: Vector2, button: int) -> bool:
    var point_result := _movement_point_at(screen_position) if button == MOUSE_BUTTON_LEFT else _raycast_walkable_point(screen_position)
    if point_result.is_empty():
        _clear_path(false)
        return false
    var point: Vector3 = point_result.get("position", global_position)
    var main_node := get_parent()
    if main_node != null and main_node.has_method("is_water_point") and bool(main_node.call("is_water_point", point)):
        _clear_path(false)
        show_message("Água profunda: atravesse pela ponte.")
        return false
    var path_ready := _request_path(point, 0.0, null)
    if not path_ready and button == MOUSE_BUTTON_LEFT:
        # Clique sobre área ocupada: caminhe até o ponto navegável mais próximo,
        # sem converter o comando em interação ou perseguição.
        path_ready = _request_path(point, INTERACTION_DISTANCE * 0.82, null)
    if not path_ready:
        _clear_path(false)
        return false
    _click_run = Input.is_key_pressed(KEY_SHIFT)
    _set_marker(point, "MOVE")
    prototype_command.emit("MOVE_CLICK", {"target_x": point.x, "target_z": point.z, "button": button})
    return true

func _update_press_candidate(delta: float) -> void:
    if _press_candidate_button == 0 or not _press_candidate_ground:
        return
    var still_held := _press_candidate_button == MOUSE_BUTTON_LEFT and _left_mouse_held
    if not still_held:
        return
    _press_candidate_elapsed += delta
    if _press_candidate_elapsed < CLICK_HOLD_THRESHOLD_S:
        return

    var button := _press_candidate_button
    _clear_press_candidate()
    # Promove o clique candidato para hold sem reconstruir a rota duas vezes.
    # O primeiro clique já iniciou movimento imediatamente; daqui em diante o
    # destino acompanha a posição ATUAL do cursor até o botão ser solto.
    _hold_move_active = true
    _hold_move_button = button
    _hold_move_refresh = HOLD_MOVE_REFRESH_S
    _hold_has_world_point = false
    _click_run = false
    _update_hold_destination(get_viewport().get_mouse_position(), true)

func _handle_pointer_release(button: int) -> void:
    if _hold_move_active and _hold_move_button == button:
        # Hold confirmado: soltar significa parar imediatamente.
        _clear_press_candidate()
        _stop_hold_movement()
        return
    if _press_candidate_button == button:
        # Clique curto: o caminho criado no press continua até o destino.
        _clear_press_candidate()

func _clear_press_candidate() -> void:
    _press_candidate_button = 0
    _press_candidate_elapsed = 0.0
    _press_candidate_position = Vector2.ZERO
    _press_candidate_ground = false

func _begin_hold_movement(button: int, screen_position: Vector2) -> void:
    if sitting:
        stand_up(true)
    _cancel_target_action(false)
    _clear_path(false)
    _hold_move_active = true
    _hold_move_button = button
    _hold_move_refresh = 0.0
    _hold_has_world_point = false
    _click_run = false
    _update_hold_destination(screen_position, true)

func _update_hold_movement(delta: float) -> void:
    if not _hold_move_active:
        return
    # Hold-to-move é exclusivo do botão esquerdo.
    var still_held := _hold_move_button == MOUSE_BUTTON_LEFT and _left_mouse_held
    if not still_held:
        _stop_hold_movement()
        return
    _hold_move_refresh = maxf(0.0, _hold_move_refresh - delta)
    if _hold_move_refresh <= 0.0:
        _hold_move_refresh = HOLD_MOVE_REFRESH_S
        _update_hold_destination(get_viewport().get_mouse_position(), false)

func _update_hold_destination(screen_position: Vector2, force: bool = false) -> void:
    var point_result := _movement_point_at(screen_position)
    if point_result.is_empty():
        _clear_path(false)
        velocity.x = 0.0
        velocity.z = 0.0
        return
    var point: Vector3 = point_result.get("position", global_position)
    var main_node := get_parent()
    if main_node != null and main_node.has_method("is_water_point") and bool(main_node.call("is_water_point", point)):
        _clear_path(false)
        velocity.x = 0.0
        velocity.z = 0.0
        return

    var cursor_moved_enough := not _hold_has_world_point or _hold_last_world_point.distance_to(point) >= HOLD_MOVE_MIN_WORLD_DELTA_M
    if not force and not cursor_moved_enough and not _path_points.is_empty():
        return
    var path_ready := _request_path(point, 0.0, null)
    if not path_ready:
        path_ready = _request_path(point, INTERACTION_DISTANCE * 0.82, null)
    if path_ready:
        _hold_last_world_point = point
        _hold_has_world_point = true
        _set_marker(point, "MOVE")
        prototype_command.emit("MOVE_HOLD", {"target_x": point.x, "target_z": point.z, "button": _hold_move_button})
    else:
        _clear_path(false)
        velocity.x = 0.0
        velocity.z = 0.0

func _stop_hold_movement(hide_marker: bool = true) -> void:
    if not _hold_move_active and _hold_move_button == 0:
        return
    _hold_move_active = false
    _hold_move_button = 0
    _hold_move_refresh = 0.0
    _hold_has_world_point = false
    _clear_path(hide_marker)
    velocity.x = 0.0
    velocity.z = 0.0
    _click_run = false
    prototype_command.emit("MOVE_STOP", {})

func _transition_target_at(screen_position: Vector2) -> Node3D:
    if not is_instance_valid(_camera) or not is_inside_tree():
        return null
    var origin: Vector3 = _camera.project_ray_origin(screen_position)
    var direction: Vector3 = _camera.project_ray_normal(screen_position)
    var query := PhysicsRayQueryParameters3D.create(origin, origin + direction * CLICK_RAY_DISTANCE)
    query.exclude = [get_rid()]
    query.collide_with_areas = true
    query.collide_with_bodies = true
    var hit: Dictionary = get_world_3d().direct_space_state.intersect_ray(query)
    if hit.is_empty():
        return null
    var collider := hit.get("collider") as Node
    if collider == null:
        return null
    var resolved := _resolve_click_target(collider)
    if resolved == null or not resolved.is_in_group("interactable"):
        return null
    var kind := str(resolved.get("interaction_kind"))
    if kind in ["DUNGEON_ENTER", "DUNGEON_EXIT"]:
        return resolved
    return null

func _context_target_at(screen_position: Vector2) -> Node3D:
    if not is_instance_valid(_camera) or not is_inside_tree():
        return null
    var origin: Vector3 = _camera.project_ray_origin(screen_position)
    var direction: Vector3 = _camera.project_ray_normal(screen_position)
    var query := PhysicsRayQueryParameters3D.create(origin, origin + direction * CLICK_RAY_DISTANCE)
    query.exclude = [get_rid()]
    query.collide_with_areas = true
    query.collide_with_bodies = true
    var hit: Dictionary = get_world_3d().direct_space_state.intersect_ray(query)
    if hit.is_empty():
        return null
    var collider := hit.get("collider") as Node
    if collider == null:
        return null
    return _resolve_click_target(collider)

func _selectable_target_at(screen_position: Vector2) -> Node3D:
    # _context_target_at resolve interactable, wildlife e hoverable.
    return _context_target_at(screen_position)

func _select_target(target: Node3D) -> bool:
    if not is_instance_valid(target) or not target.is_inside_tree():
        return false
    if not (
        target.is_in_group("interactable")
        or target.is_in_group("wildlife")
        or target.is_in_group("hoverable")
    ):
        return false
    if target.has_method("is_alive") and not bool(target.call("is_alive")):
        return false

    _selected_target = target
    _update_selected_target()

    var hint := _selected_target_action_hint(target)
    show_message("Selecionado: %s • %s" % [_target_display_name(target), hint])
    prototype_command.emit("TARGET_SELECT", {
        "target": str(target.name),
        "group_interactable": target.is_in_group("interactable"),
        "group_wildlife": target.is_in_group("wildlife"),
        "group_hoverable": target.is_in_group("hoverable")
    })
    return true

func _selected_target_is_selectable(target) -> bool:
    # FIX1: `target` may be a previously-freed Object reference.
    # It must be validated before any typed dispatch or method access.
    if target == null:
        return false
    if not is_instance_valid(target):
        return false
    if not target.is_inside_tree():
        return false
    return (
        target.is_in_group("interactable")
        or target.is_in_group("wildlife")
        or target.is_in_group("hoverable")
    )

func _selected_target_is_attackable_enemy(target) -> bool:
    if not _selected_target_is_selectable(target):
        return false
    if not target.is_in_group("wildlife"):
        return false
    if target.has_method("is_enemy"):
        return bool(target.call("is_enemy"))
    return false

func _selected_target_action_hint(target) -> String:
    if _selected_target_is_attackable_enemy(target):
        return "Espaço: atacar"
    if target.is_in_group("interactable"):
        return "E: ir/interagir"
    if target.is_in_group("wildlife"):
        return "E: ir/observar"
    if target.is_in_group("hoverable"):
        return "E: ir/observar"
    return "Selecionado"

func _clear_selected_target(show_feedback: bool = false) -> void:
    var previous_name := ""
    if is_instance_valid(_selected_target):
        previous_name = _target_display_name(_selected_target)
    _selected_target = null
    if is_instance_valid(_selection_marker):
        _selection_marker.visible = false
    if show_feedback and not previous_name.is_empty():
        show_message("Seleção removida: %s." % previous_name)

func _update_selected_target() -> void:
    # FIX1: nunca passe uma referência liberada para helpers tipados/dinâmicos.
    if _selected_target == null or not is_instance_valid(_selected_target):
        _clear_selected_target(false)
        return
    if not _selected_target_is_selectable(_selected_target):
        _clear_selected_target(false)
        return
    if _selected_target.has_method("is_alive") and not bool(_selected_target.call("is_alive")):
        _clear_selected_target(false)
        return

    if is_instance_valid(_selection_marker) and _selection_marker.is_inside_tree():
        _selection_marker.global_position = _selected_target.global_position + Vector3(0.0, 0.045, 0.0)
        _selection_marker.visible = true

func get_selected_target() -> Node3D:
    _update_selected_target()
    return _selected_target

# Compatibilidade com a API anterior.
func get_selected_enemy() -> Node3D:
    _update_selected_target()
    if is_instance_valid(_selected_target) and _selected_target_is_attackable_enemy(_selected_target):
        return _selected_target
    return null

func _selected_target_context_kind(target) -> String:
    if not _selected_target_is_selectable(target):
        return ""
    if _selected_target_is_attackable_enemy(target):
        return "ATTACK"
    if target.is_in_group("interactable"):
        return "INTERACT"
    if target.is_in_group("wildlife"):
        return "INSPECT"
    if target.is_in_group("hoverable"):
        return "INSPECT"
    return ""

func _interact_selected_target() -> void:
    _update_selected_target()
    if not is_instance_valid(_selected_target):
        show_message("Nenhum alvo selecionado. Selecione um NPC, animal, árvore, pedra ou objeto com o botão esquerdo.")
        return

    if _selected_target_is_attackable_enemy(_selected_target):
        show_message("%s é um inimigo. Use Espaço ou botão direito para atacar." % _target_display_name(_selected_target))
        return

    var action_kind := _selected_target_context_kind(_selected_target)
    if action_kind.is_empty() or action_kind == "ATTACK":
        show_message("%s não possui interação disponível pelo E." % _target_display_name(_selected_target))
        return

    if sitting:
        stand_up(true)

    # E transforma a seleção em um comando completo:
    # cancela o movimento atual, aproxima até a distância correta e
    # conclui automaticamente a mesma ação contextual do botão direito.
    _clear_press_candidate()
    _stop_hold_movement(false)
    _begin_target_action(_selected_target, action_kind)
    prototype_command.emit("INTERACT_SELECTED", {
        "target": str(_selected_target.name),
        "kind": action_kind
    })

func _attack_selected_target() -> void:
    _update_selected_target()
    if not is_instance_valid(_selected_target):
        show_message("Nenhum alvo selecionado.")
        return

    if not _selected_target_is_attackable_enemy(_selected_target):
        show_message("%s não é um inimigo atacável. Use E para ir/interagir." % _target_display_name(_selected_target))
        return

    if _selected_target.has_method("is_alive") and not bool(_selected_target.call("is_alive")):
        _clear_selected_target(false)
        show_message("O inimigo selecionado não está mais disponível.")
        return

    if sitting:
        stand_up(true)

    _clear_press_candidate()
    _stop_hold_movement(false)
    _begin_target_action(_selected_target, "ATTACK")
    prototype_command.emit("ATTACK_SELECTED", {"target": str(_selected_target.name)})

# Alias mantido para compatibilidade interna da V0.1.20.
func _attack_selected_enemy() -> void:
    _attack_selected_target()

func _resolve_click_target(collider: Node) -> Node3D:
    if collider is Node3D and (collider.is_in_group("interactable") or collider.is_in_group("wildlife") or collider.is_in_group("hoverable")):
        return collider as Node3D
    if collider.is_in_group("interaction_hitbox"):
        var parent_node := collider.get_parent()
        if parent_node is Node3D and parent_node.is_in_group("interactable"):
            return parent_node as Node3D
    return null

func _weapon_profile_for(item_name: String) -> Dictionary:
    if item_name.is_empty():
        return {
            "combat_class": "UNARMED",
            "damage": 12,
            "stamina_cost": 6,
            "shield_damage_factor": 0.55,
            "hp_through_shield_factor": 0.00,
            "attack_range_m": ATTACK_DISTANCE,
            "min_range_m": 0.0,
            "durability_max": 0,
            "power": 30,
            "defense": 20,
            "utility": 20,
            "handling": 55,
            "durability_stat": 0,
            "reach_stat": 20,
            "magic_affinity": 0,
            "tech_affinity": 0,
            "overall": 25,
            "rarity": "N/A",
            "projectile": "",
            "authority": "FIRST_PLAYABLE_UNARMED"
        }
    if WEAPON_PROFILES.has(item_name):
        return WEAPON_PROFILES[item_name]
    return {
        "combat_class": "MELEE",
        "damage": 20,
        "stamina_cost": 10,
        "shield_damage_factor": 0.65,
        "hp_through_shield_factor": 0.10,
        "attack_range_m": ATTACK_DISTANCE,
        "min_range_m": 0.0,
        "durability_max": 50,
        "power": 50,
        "defense": 45,
        "utility": 45,
        "handling": 50,
        "durability_stat": 50,
        "reach_stat": 35,
        "magic_affinity": 0,
        "tech_affinity": 0,
        "overall": 45,
        "rarity": "DEV_GENÉRICA",
        "projectile": "",
        "authority": "FALLBACK_DEV_NOT_CANON"
    }

func get_weapon_profile(item_name: String) -> Dictionary:
    return _weapon_profile_for(item_name).duplicate(true)

func _ensure_weapon_state(item_name: String) -> void:
    if item_name.is_empty():
        return
    if _weapon_durability.has(item_name):
        return
    var profile := _weapon_profile_for(item_name)
    _weapon_durability[item_name] = int(profile.get("durability_max", 50))

func get_weapon_durability(item_name: String) -> int:
    if item_name.is_empty():
        return 0
    _ensure_weapon_state(item_name)
    return int(_weapon_durability.get(item_name, 0))

func _current_weapon_profile() -> Dictionary:
    return _weapon_profile_for(equipped_weapon)

func _current_attack_range() -> float:
    return float(_current_weapon_profile().get("attack_range_m", ATTACK_DISTANCE))

func _current_min_range() -> float:
    return float(_current_weapon_profile().get("min_range_m", 0.0))

func _current_attack_stop_distance() -> float:
    var attack_range := _current_attack_range()
    var min_range := _current_min_range()
    if min_range > 0.0:
        return clampf(maxf(min_range + 0.8, attack_range * 0.72), min_range, attack_range - 0.35)
    return maxf(0.6, attack_range * 0.86)

func _current_weapon_is_ranged() -> bool:
    return str(_current_weapon_profile().get("combat_class", "MELEE")) == "RANGED"

func _request_ranged_retreat(target: Node3D, distance: float) -> bool:
    if not is_instance_valid(target):
        return false
    var away := global_position - target.global_position
    away.y = 0.0
    if away.length() < 0.05:
        away = Vector3(1.0, 0.0, 0.0)
    away = away.normalized()

    var retreat_amount := maxf(RANGED_RETREAT_STEP_M, _current_min_range() - distance + 1.2)
    var main_node := get_parent()
    var angles := [0.0, 0.70, -0.70, 1.25, -1.25]
    _clear_path(false)
    for angle in angles:
        var candidate_direction := away.rotated(Vector3.UP, float(angle))
        var candidate := global_position + candidate_direction * retreat_amount
        if main_node != null and main_node.has_method("is_water_point") and bool(main_node.call("is_water_point", candidate)):
            continue
        if _request_path(candidate, 0.0, null):
            return true
    return false

func _begin_target_action(target: Node3D, kind: String) -> void:
    # Segundo clique na mesma cadeira deve levantar. A interação é despachada
    # fora do _physics_process para não alterar estado físico durante a etapa de física.
    if kind == "INTERACT" and sitting and target == _seated_target:
        var seat_distance := global_position.distance_to(target.global_position)
        _cancel_target_action(true)
        _clear_path(true)
        _queue_interaction(target, seat_distance)
        return
    if sitting:
        stand_up(true)

    _cancel_target_action(false)
    _clear_path()
    _action_target = target
    _action_kind = kind
    _last_target_position = target.global_position
    _target_repath_timer = 0.0
    _click_run = false
    var initial_distance := global_position.distance_to(target.global_position)

    if kind == "ATTACK":
        _ranged_cycle_state = "READY"
        _ranged_retreat_source = null
        _ranged_retreat_timer = 0.0
        _ranged_settle_timer = 0.0
        var attack_range := _current_attack_range()
        var stop_distance := _current_attack_stop_distance()
        _set_marker(target.global_position, "ATTACK")
        show_message("Alvo: %s • %s • alcance %.1fm." % [_target_display_name(target), equipped_weapon if not equipped_weapon.is_empty() else "desarmado", attack_range])
        if initial_distance > attack_range and not _request_path(target.global_position, stop_distance, target):
            show_message("Não existe caminho até %s." % _target_display_name(target))
            _cancel_target_action(true)
    else:
        _set_marker(target.global_position, "INTERACT")
        if kind == "INSPECT":
            show_message("Indo observar %s." % _target_display_name(target))
        else:
            show_message("Indo interagir com %s." % _target_display_name(target))
        if initial_distance > INTERACTION_DISTANCE and not _request_path(target.global_position, INTERACTION_DISTANCE * 0.82, target):
            show_message("Não existe caminho até %s." % _target_display_name(target))
            _cancel_target_action(true)

func _trigger_ranged_retreat_from_damage(source: Node3D) -> void:
    if not _current_weapon_is_ranged():
        return
    if not is_instance_valid(source) or not source.is_inside_tree():
        return

    _ranged_retreat_source = source
    _ranged_cycle_state = "DAMAGE_RETREAT_PENDING"
    _ranged_retreat_timer = 0.0
    _ranged_settle_timer = 0.0
    _clear_path(false)

func _update_ranged_damage_reaction() -> void:
    if not _current_weapon_is_ranged():
        if _ranged_cycle_state != "READY":
            _ranged_cycle_state = "READY"
            _ranged_retreat_source = null
            _ranged_retreat_timer = 0.0
            _ranged_settle_timer = 0.0
        return

    match _ranged_cycle_state:
        "DAMAGE_RETREAT_PENDING":
            var retreat_source := _ranged_retreat_source
            if not is_instance_valid(retreat_source) or not retreat_source.is_inside_tree():
                _ranged_cycle_state = "READY"
                _ranged_retreat_source = null
                return

            var source_distance := global_position.distance_to(retreat_source.global_position)
            if _request_ranged_retreat(retreat_source, source_distance):
                _ranged_retreat_timer = RANGED_RETREAT_TIME_S
                _ranged_cycle_state = "RETREATING"
            else:
                _clear_path(false)
                _ranged_cycle_state = "SETTLING"
                _ranged_settle_timer = RANGED_SETTLE_TIME_S

        "RETREATING":
            if _ranged_retreat_timer > 0.0 and not _path_points.is_empty():
                return
            # Recuo curto: interrompe a rota assim que o tempo acaba.
            _clear_path(false)
            _ranged_retreat_timer = 0.0
            _ranged_cycle_state = "SETTLING"
            _ranged_settle_timer = RANGED_SETTLE_TIME_S

        "SETTLING":
            _clear_path(false)
            if _ranged_settle_timer > 0.0:
                return
            _ranged_cycle_state = "READY"
            _ranged_retreat_source = null

        _:
            pass

func _update_target_action() -> void:
    if _action_kind.is_empty():
        return
    if not is_instance_valid(_action_target) or not _action_target.is_inside_tree():
        _cancel_target_action(true)
        _clear_path()
        show_message("O alvo não está mais disponível.")
        return

    if is_instance_valid(_target_marker) and _target_marker.is_inside_tree():
        _target_marker.global_position = _action_target.global_position + Vector3(0.0, 0.05, 0.0)

    var distance := global_position.distance_to(_action_target.global_position)
    if _action_kind in ["INTERACT", "INSPECT"]:
        if distance <= INTERACTION_DISTANCE:
            var completed_target: Node3D = _action_target
            var completed_kind: String = _action_kind
            _cancel_target_action(true)
            _clear_path(true)
            if completed_kind == "INSPECT":
                _perform_inspect(completed_target)
            else:
                _queue_interaction(completed_target, distance)
        elif _path_points.is_empty() and _target_repath_timer <= 0.0:
            _request_path(_action_target.global_position, INTERACTION_DISTANCE * 0.82, _action_target)
            _target_repath_timer = TARGET_REPATH_INTERVAL_S
        return

    if _action_kind == "ATTACK":
        if _action_target.has_method("is_alive") and not bool(_action_target.call("is_alive")):
            _cancel_target_action(true)
            _clear_path()
            return

        var attack_range := _current_attack_range()
        var ranged := _current_weapon_is_ranged()

        if ranged:
            # V0.1.19 FINAL:
            # Proximidade nunca inicia recuo.
            # O único gatilho é receber dano enquanto uma arma RANGED está equipada.
            # Enquanto o recuo/estabilização por dano está ativo, não há disparo.
            if _ranged_cycle_state != "READY":
                return

            if distance <= attack_range:
                _clear_path()
                if _attack_cooldown <= 0.0:
                    _perform_attack_on(_action_target)
            else:
                var target_moved_ranged := _action_target.global_position.distance_to(_last_target_position) >= TARGET_REPATH_DISTANCE_M
                if (_path_points.is_empty() or target_moved_ranged) and _target_repath_timer <= 0.0:
                    _request_path(_action_target.global_position, _current_attack_stop_distance(), _action_target)
                    _last_target_position = _action_target.global_position
                    _target_repath_timer = TARGET_REPATH_INTERVAL_S
            return

        if distance <= attack_range:
            _clear_path()
            if _attack_cooldown <= 0.0:
                _perform_attack_on(_action_target)
        else:
            var target_moved := _action_target.global_position.distance_to(_last_target_position) >= TARGET_REPATH_DISTANCE_M
            if (_path_points.is_empty() or target_moved) and _target_repath_timer <= 0.0:
                _request_path(_action_target.global_position, _current_attack_stop_distance(), _action_target)
                _last_target_position = _action_target.global_position
                _target_repath_timer = TARGET_REPATH_INTERVAL_S

func _request_path(destination: Vector3, stop_distance: float, target: Node3D) -> bool:
    var main_node := get_parent()
    if main_node == null or not main_node.has_method("find_navigation_path"):
        return false
    var result: Variant = main_node.call("find_navigation_path", global_position, destination, stop_distance, target)
    if not (result is Array):
        return false
    _path_points.clear()
    for entry in result:
        if entry is Vector3:
            _path_points.append(entry)
    _path_index = 0
    return not _path_points.is_empty()

func _path_direction() -> Vector2:
    while _path_index < _path_points.size():
        var waypoint := _path_points[_path_index]
        var offset := waypoint - global_position
        offset.y = 0.0
        if offset.length() <= PATH_POINT_DISTANCE:
            _path_index += 1
            continue
        var direction := offset.normalized()
        return Vector2(direction.x, direction.z)
    _clear_path(not _hold_move_active and _action_kind.is_empty())
    return Vector2.ZERO

func _clear_path(hide_marker: bool = false) -> void:
    _path_points.clear()
    _path_index = 0
    if hide_marker:
        _marker_pending_update = false
        if is_instance_valid(_target_marker):
            _target_marker.visible = false

func _movement_point_at(screen_position: Vector2) -> Dictionary:
    var walkable_hit := _raycast_walkable_point(screen_position)
    if not walkable_hit.is_empty():
        return walkable_hit

    if not is_instance_valid(_camera) or not is_inside_tree():
        return {}

    # Projeta o cursor no plano do terreno quando um volume do mundo impede
    # um hit walkable direto. O objeto não se torna alvo de ação.
    var origin: Vector3 = _camera.project_ray_origin(screen_position)
    var direction: Vector3 = _camera.project_ray_normal(screen_position)
    if absf(direction.y) <= 0.0001:
        return {}
    var distance_to_plane := (0.0 - origin.y) / direction.y
    if distance_to_plane <= 0.0:
        return {}
    var point := origin + direction * distance_to_plane
    return {"position": point, "fallback": true}

func _raycast_walkable_point(screen_position: Vector2) -> Dictionary:
    if not is_instance_valid(_camera) or not is_inside_tree():
        return {}
    var origin := _camera.project_ray_origin(screen_position)
    var direction := _camera.project_ray_normal(screen_position)
    var excluded: Array[RID] = [get_rid()]
    var space_state := get_world_3d().direct_space_state
    for _attempt in range(12):
        var query := PhysicsRayQueryParameters3D.create(origin, origin + direction * CLICK_RAY_DISTANCE)
        query.exclude = excluded
        query.collide_with_areas = false
        query.collide_with_bodies = true
        var hit: Dictionary = space_state.intersect_ray(query)
        if hit.is_empty():
            break
        var collider := hit.get("collider") as Node
        if collider != null and collider.is_in_group("walkable_surface"):
            return hit
        var collider_rid: RID = hit.get("rid", RID())
        if collider_rid.is_valid():
            excluded.append(collider_rid)
        else:
            break
    return {}

func _set_marker(world_position: Vector3, mode: String) -> void:
    if not is_instance_valid(_target_marker):
        return
    if not _target_marker.is_inside_tree():
        _marker_pending_position = world_position
        _marker_pending_mode = mode
        _marker_pending_update = true
        return
    _target_marker.global_position = world_position + Vector3(0.0, 0.05, 0.0)
    _target_marker.visible = true
    var material := _target_marker.material_override as StandardMaterial3D
    if material == null:
        return
    if mode == "ATTACK":
        material.albedo_color = Color(0.95, 0.18, 0.16, 0.50)
        material.emission = Color(0.34, 0.03, 0.02)
    elif mode == "INTERACT":
        material.albedo_color = Color(0.95, 0.76, 0.20, 0.48)
        material.emission = Color(0.30, 0.17, 0.02)
    else:
        material.albedo_color = Color(0.35, 0.95, 0.55, 0.42)
        material.emission = Color(0.08, 0.34, 0.14)

func _on_target_marker_tree_entered() -> void:
    if not _marker_pending_update:
        return
    var pending_position := _marker_pending_position
    var pending_mode := _marker_pending_mode
    _marker_pending_update = false
    _set_marker(pending_position, pending_mode)

func _cancel_target_action(hide_marker: bool = true) -> void:
    _action_kind = ""
    _action_target = null
    _ranged_cycle_state = "READY"
    _ranged_retreat_source = null
    _ranged_retreat_timer = 0.0
    _ranged_settle_timer = 0.0
    _target_repath_timer = 0.0
    # O cooldown de ataque NÃO é zerado ao trocar/cancelar alvo. Isso garante
    # intervalo real de 2 s mesmo sob cliques repetidos.
    # Um novo movimento/novo alvo invalida uma interação ainda aguardando o
    # despacho diferido. O callback pode continuar enfileirado, mas encontrará
    # alvo nulo e encerrará sem mutação.
    _pending_interaction_target = null
    _pending_interaction_distance = 0.0
    if hide_marker:
        _marker_pending_update = false
        if is_instance_valid(_target_marker):
            _target_marker.visible = false

func _cancel_all_actions(show_feedback: bool = false) -> void:
    _clear_press_candidate()
    _cancel_target_action(true)
    _stop_hold_movement(true)
    _clear_path(true)
    _click_run = false
    if show_feedback:
        show_message("Ação cancelada.")

func _update_hover_tooltip(screen_position: Vector2) -> void:
    if not is_instance_valid(_hover_panel) or not is_instance_valid(_hover_label):
        return
    var target: Node3D = _hover_target_at(screen_position)
    if target == null:
        _last_hover_target = null
        _hover_panel.visible = false
        return
    var info: Dictionary = _hover_info_for(target)
    if info.is_empty():
        _last_hover_target = null
        _hover_panel.visible = false
        return
    _last_hover_target = target
    var title: String = str(info.get("title", _target_display_name(target)))
    var detail: String = str(info.get("detail", ""))
    _hover_label.text = title if detail.is_empty() else "%s\n%s" % [title, detail]
    var viewport_size: Vector2 = get_viewport().get_visible_rect().size
    var desired := screen_position + Vector2(18, 18)
    desired.x = clampf(desired.x, 8.0, maxf(8.0, viewport_size.x - _hover_panel.size.x - 8.0))
    desired.y = clampf(desired.y, 8.0, maxf(8.0, viewport_size.y - _hover_panel.size.y - 8.0))
    _hover_panel.position = desired
    _hover_panel.visible = true

func _hover_target_at(screen_position: Vector2) -> Node3D:
    if not is_instance_valid(_camera) or not is_inside_tree():
        return null
    var origin: Vector3 = _camera.project_ray_origin(screen_position)
    var direction: Vector3 = _camera.project_ray_normal(screen_position)
    var query := PhysicsRayQueryParameters3D.create(origin, origin + direction * CLICK_RAY_DISTANCE)
    query.exclude = [get_rid()]
    query.collide_with_areas = true
    query.collide_with_bodies = true
    var hit: Dictionary = get_world_3d().direct_space_state.intersect_ray(query)
    if hit.is_empty():
        return null
    var collider := hit.get("collider") as Node
    if collider == null:
        return null
    return _resolve_click_target(collider)

func _hover_info_for(target: Node3D) -> Dictionary:
    if target.has_method("get_hover_info"):
        var result: Variant = target.call("get_hover_info")
        if result is Dictionary:
            return result
    if target.is_in_group("hoverable"):
        return {
            "title": str(target.get_meta("hover_name", target.name)),
            "detail": str(target.get_meta("hover_detail", "Objeto do mundo"))
        }
    return {}

func _perform_inspect(target: Node3D) -> void:
    var info: Dictionary = _hover_info_for(target)
    if info.is_empty():
        show_message("Você observa %s." % _target_display_name(target))
        return
    var title: String = str(info.get("title", _target_display_name(target)))
    var detail: String = str(info.get("detail", ""))
    show_message(title if detail.is_empty() else "%s — %s" % [title, detail])

func _queue_interaction(target: Node3D, distance: float) -> void:
    if not is_instance_valid(target) or not target.is_inside_tree():
        show_message("O alvo não está mais disponível.")
        return
    if not target.has_method("interact"):
        show_message("Esse alvo não possui interação disponível.")
        return
    # Debounce evita dois cliques/frames despacharem a mesma mutação física.
    if _interaction_cooldown > 0.0:
        return
    _pending_interaction_target = target
    _pending_interaction_distance = distance
    if _interaction_dispatch_scheduled:
        return
    _interaction_dispatch_scheduled = true
    call_deferred("_dispatch_pending_interaction")

func _dispatch_pending_interaction() -> void:
    _interaction_dispatch_scheduled = false
    var target: Node3D = _pending_interaction_target
    var distance: float = _pending_interaction_distance
    _pending_interaction_target = null
    _pending_interaction_distance = 0.0
    if not is_instance_valid(target) or not target.is_inside_tree():
        return
    if not target.has_method("interact"):
        return

    # O ID é capturado antes da interação porque a ação pode ocultar, desabilitar
    # colisores ou futuramente remover o objeto da árvore.
    var object_id: String = str(target.name)
    _interaction_cooldown = INTERACTION_DEBOUNCE_S
    target.call("interact", self)
    prototype_command.emit("INTERACT", {"object_id": object_id, "action": "USE", "distance_m": distance})

# Compatibilidade interna/teclado: nunca executa mutações diretamente no frame de física.
func _perform_interaction(target: Node3D, distance: float) -> void:
    _queue_interaction(target, distance)

func _perform_attack_on(target: Node3D) -> bool:
    if _attack_cooldown > 0.0:
        return false
    if not is_instance_valid(target) or not target.has_method("take_damage"):
        return false

    var profile := _current_weapon_profile()
    var attack_range := float(profile.get("attack_range_m", ATTACK_DISTANCE))
    var distance := global_position.distance_to(target.global_position)
    if distance > attack_range + 0.25:
        return false

    if not equipped_weapon.is_empty():
        _ensure_weapon_state(equipped_weapon)
        var durability := int(_weapon_durability.get(equipped_weapon, 0))
        if durability <= 0:
            show_message("%s está sem durabilidade. Selecione outra arma." % equipped_weapon)
            _cancel_target_action(true)
            _clear_path(true)
            _inventory_ui_dirty = true
            return false

    var stamina_cost := float(profile.get("stamina_cost", 10.0))
    if stamina < stamina_cost:
        show_message("Stamina insuficiente: %.0f necessária, %.0f disponível." % [stamina_cost, stamina])
        return false

    stamina = maxf(0.0, stamina - stamina_cost)
    _stamina_regen_delay = STAMINA_REGEN_DELAY_AFTER_ATTACK_S

    # Cooldown global preservado: sempre 2 segundos para ataques válidos.
    _attack_cooldown = ATTACK_INTERVAL_S
    var damage := int(profile.get("damage", 12))
    var projectile_kind := str(profile.get("projectile", ""))

    var weapon_damage_profile := profile.duplicate(true)
    if not projectile_kind.is_empty():
        var start_pos := global_position + Vector3(0.0, 0.85, 0.0)
        var end_pos := target.global_position + Vector3(0.0, 0.65, 0.0)
        call_deferred("_spawn_ranged_projectile", start_pos, end_pos, projectile_kind, target, damage, weapon_damage_profile)
    else:
        if target.has_method("take_weapon_damage"):
            target.call("take_weapon_damage", damage, weapon_damage_profile, self)
        else:
            target.call("take_damage", damage, self)

    if not equipped_weapon.is_empty():
        var remaining := maxi(0, int(_weapon_durability.get(equipped_weapon, 0)) - 1)
        _weapon_durability[equipped_weapon] = remaining
        _inventory_ui_dirty = true
        if remaining == 0:
            show_message("%s chegou a 0 de durabilidade." % equipped_weapon)

    prototype_command.emit("ATTACK", {
        "target": str(target.name),
        "weapon": equipped_weapon if not equipped_weapon.is_empty() else "UNARMED",
        "damage": damage,
        "stamina_cost": stamina_cost,
        "stamina_after": stamina,
        "shield_damage_factor": float(profile.get("shield_damage_factor", 0.0)),
        "hp_through_shield_factor": float(profile.get("hp_through_shield_factor", 0.0)),
        "range_m": attack_range,
        "durability": get_weapon_durability(equipped_weapon) if not equipped_weapon.is_empty() else 0,
        "interval_s": ATTACK_INTERVAL_S
    })
    return true

func _spawn_ranged_projectile(start_pos: Vector3, end_pos: Vector3, projectile_kind: String, target, damage: int, weapon_damage_profile: Dictionary) -> void:
    var world_parent := get_parent()
    if world_parent == null or not world_parent.is_inside_tree():
        return

    var projectile := MeshInstance3D.new()
    projectile.name = "ArrowProjectile" if projectile_kind == "FLECHA" else "BoltProjectile"

    var mesh := BoxMesh.new()
    mesh.size = Vector3(0.07, 0.07, 0.72 if projectile_kind == "FLECHA" else 0.55)
    projectile.mesh = mesh

    var material := StandardMaterial3D.new()
    material.albedo_color = Color(0.46, 0.30, 0.15) if projectile_kind == "FLECHA" else Color(0.55, 0.50, 0.42)
    material.roughness = 0.75
    projectile.material_override = material

    world_parent.add_child(projectile)
    projectile.global_position = start_pos
    if start_pos.distance_to(end_pos) > 0.05:
        projectile.look_at(end_pos, Vector3.UP)

    var travel_time := clampf(start_pos.distance_to(end_pos) / 28.0, 0.12, 0.34)
    var tween := projectile.create_tween()
    tween.tween_property(projectile, "global_position", end_pos, travel_time)
    tween.tween_callback(_resolve_ranged_impact.bind(projectile, target, damage, weapon_damage_profile))

func _resolve_ranged_impact(projectile, target, damage: int, weapon_damage_profile: Dictionary) -> void:
    # O alvo pode ter sido destruído antes do projétil chegar.
    if target != null and is_instance_valid(target) and target.is_inside_tree():
        if target.has_method("take_weapon_damage"):
            target.call("take_weapon_damage", damage, weapon_damage_profile, self)
        elif target.has_method("take_damage"):
            target.call("take_damage", damage, self)
    if projectile != null and is_instance_valid(projectile):
        projectile.queue_free()

func _target_display_name(target: Node3D) -> String:
    if target.has_method("get_display_name"):
        return str(target.call("get_display_name"))
    if target.has_method("get_species_name"):
        return str(target.call("get_species_name"))
    return str(target.name)

# Fallbacks de teclado para debug.
func _interact() -> void:
    var nearest: Node3D = null
    var nearest_distance := INTERACTION_DISTANCE + 0.001
    for node in get_tree().get_nodes_in_group("interactable"):
        if node is Node3D and is_instance_valid(node):
            var distance := global_position.distance_to((node as Node3D).global_position)
            if distance < nearest_distance:
                nearest = node as Node3D
                nearest_distance = distance
    if nearest == null:
        show_message("Nada para interagir por perto.")
        return
    _perform_interaction(nearest, nearest_distance)

func _attack() -> void:
    var nearest: Node3D = null
    var nearest_distance := _current_attack_range() + 0.001
    for node in get_tree().get_nodes_in_group("wildlife"):
        if node is Node3D and is_instance_valid(node):
            if node.has_method("is_enemy") and not bool(node.call("is_enemy")):
                continue
            var distance := global_position.distance_to((node as Node3D).global_position)
            if distance < nearest_distance:
                nearest = node as Node3D
                nearest_distance = distance
    if nearest == null:
        show_message("Nenhum inimigo ao alcance.")
        return
    _perform_attack_on(nearest)

func _inventory_category_for(item_name: String) -> String:
    if _inventory_categories.has(item_name):
        return str(_inventory_categories[item_name])

    var normalized := item_name.to_lower()
    var weapon_terms := ["espada", "machado", "arco", "lança", "lanca", "adaga", "cajado", "martelo", "arma"]
    for term in weapon_terms:
        if normalized.contains(term):
            return "ARMAS"

    var material_terms := ["couro", "tecido", "pele", "carne", "fibra", "osso", "chifre", "escama", "fragmento", "minério", "minerio", "madeira", "erva"]
    for term in material_terms:
        if normalized.contains(term):
            return "MATERIAIS"

    return "OBJETOS"

func _register_inventory_category(item_name: String, requested_category: String = "") -> void:
    var category := requested_category.strip_edges().to_upper()
    if category not in ["ARMAS", "MATERIAIS", "OBJETOS"]:
        category = _inventory_category_for(item_name)
    _inventory_categories[item_name] = category

func add_item(item_name: String, category: String = "") -> void:
    if not inventory.has(item_name):
        inventory.append(item_name)
    _register_inventory_category(item_name, category)
    if _inventory_category_for(item_name) == "ARMAS":
        _ensure_weapon_state(item_name)
    _inventory_ui_dirty = true
    show_message("Adquirido: %s" % item_name)
    _update_hud()

func has_item(item_name: String) -> bool:
    return inventory.has(item_name)

func equip_weapon(item_name: String) -> void:
    if not inventory.has(item_name):
        inventory.append(item_name)
    _register_inventory_category(item_name, "ARMAS")
    _ensure_weapon_state(item_name)
    equipped_weapon = item_name
    _inventory_ui_dirty = true
    show_message("Arma equipada: %s" % item_name)
    _update_hud()

func select_weapon(item_name: String) -> bool:
    if not inventory.has(item_name):
        show_message("Essa arma não está no inventário.")
        return false
    if _inventory_category_for(item_name) != "ARMAS":
        show_message("%s não é uma arma selecionável." % item_name)
        return false
    _ensure_weapon_state(item_name)
    equipped_weapon = item_name
    _inventory_ui_dirty = true
    var profile := _weapon_profile_for(item_name)
    show_message("Selecionada: %s • dano %d • alcance %.1fm." % [item_name, int(profile.get("damage", 0)), float(profile.get("attack_range_m", 0.0))])
    _update_hud()
    return true

func _on_inventory_weapon_pressed(item_name: String) -> void:
    select_weapon(item_name)

func open_shop(catalog_id: String, shop_name: String = "Loja") -> bool:
    var normalized := catalog_id.strip_edges().to_upper()
    if not SHOP_CATALOGS.has(normalized):
        show_message("Catálogo indisponível: %s." % normalized)
        return false

    _shop_catalog_id = normalized
    _shop_name = shop_name
    _shop_selected_index = -1
    if is_instance_valid(_shop_panel):
        _shop_panel.visible = true
    if is_instance_valid(_inventory_panel):
        _inventory_panel.visible = false
    _inventory_open = false
    _refresh_shop()
    return true

func _close_shop() -> void:
    if is_instance_valid(_shop_panel):
        _shop_panel.visible = false
    _shop_catalog_id = ""
    _shop_selected_index = -1

func _refresh_shop() -> void:
    if not is_instance_valid(_shop_panel) or not _shop_panel.visible:
        return
    if not SHOP_CATALOGS.has(_shop_catalog_id):
        return

    _shop_title.text = "%s • Moedas: %d" % [_shop_name, coins]

    for child in _shop_item_list.get_children():
        child.queue_free()

    var items: Array = SHOP_CATALOGS[_shop_catalog_id]
    for index in range(items.size()):
        var item: Dictionary = items[index]
        var button := Button.new()
        button.text = "%s — %d moedas" % [str(item.get("name", "Item")), int(item.get("price", 0))]
        button.custom_minimum_size = Vector2(240, 38)
        button.pressed.connect(_on_shop_item_pressed.bind(index))
        _shop_item_list.add_child(button)

    if _shop_selected_index < 0 or _shop_selected_index >= items.size():
        _shop_detail.text = "Selecione um item para ver informações completas."
        _shop_buy_button.disabled = true
        _shop_buy_button.text = "COMPRAR"
    else:
        var selected: Dictionary = items[_shop_selected_index]
        _shop_detail.text = _shop_item_description(selected)
        var item_name := str(selected.get("name", ""))
        _shop_buy_button.disabled = _purchased_shop_items.has(item_name)
        _shop_buy_button.text = "ADQUIRIDO" if _purchased_shop_items.has(item_name) else "COMPRAR"

func _on_shop_item_pressed(index: int) -> void:
    _shop_selected_index = index
    _refresh_shop()

func _shop_item_description(item: Dictionary) -> String:
    var item_name := str(item.get("name", "Item"))
    var item_type := str(item.get("type", "ITEM"))
    var price := int(item.get("price", 0))
    var lines: Array[String] = [
        item_name,
        "Tipo: %s" % item_type,
        "Preço: %d moedas" % price
    ]

    if item_type == "WEAPON":
        var profile := _weapon_profile_for(item_name)
        lines.append("Dano: %d" % int(profile.get("damage", 0)))
        lines.append("Alcance: %.1f m" % float(profile.get("attack_range_m", 0.0)))
        lines.append("Stamina/ataque: %.0f" % float(profile.get("stamina_cost", 10.0)))
        lines.append("Durabilidade: %d" % int(profile.get("durability_max", 0)))
        lines.append("Vs Escudo: x%.2f" % float(profile.get("shield_damage_factor", 0.0)))
        lines.append("Penetração HP: x%.2f" % float(profile.get("hp_through_shield_factor", 0.0)))
    else:
        if int(item.get("hp_bonus", 0)) > 0:
            lines.append("HP máximo: +%d" % int(item.get("hp_bonus", 0)))
        if int(item.get("protection_bonus", 0)) > 0:
            lines.append("Proteção máxima: +%d" % int(item.get("protection_bonus", 0)))
        if int(item.get("stamina_bonus", 0)) > 0:
            lines.append("Stamina máxima: +%d" % int(item.get("stamina_bonus", 0)))

    if _purchased_shop_items.has(item_name):
        lines.append("")
        lines.append("STATUS: JÁ ADQUIRIDO")
    return "\n".join(lines)

func _on_shop_buy_pressed() -> void:
    if not SHOP_CATALOGS.has(_shop_catalog_id):
        return
    var items: Array = SHOP_CATALOGS[_shop_catalog_id]
    if _shop_selected_index < 0 or _shop_selected_index >= items.size():
        return

    var item: Dictionary = items[_shop_selected_index]
    var item_name := str(item.get("name", "Item"))
    var price := int(item.get("price", 0))

    if _purchased_shop_items.has(item_name):
        show_message("%s já foi adquirido." % item_name)
        _refresh_shop()
        return
    if coins < price:
        show_message("Moedas insuficientes: %d necessárias." % price)
        return

    coins -= price
    _purchased_shop_items[item_name] = true
    _apply_shop_purchase(item)
    show_message("Compra concluída: %s por %d moedas." % [item_name, price])
    _inventory_ui_dirty = true
    _update_hud()
    _refresh_shop()

func _apply_shop_purchase(item: Dictionary) -> void:
    var item_name := str(item.get("name", "Item"))
    var item_type := str(item.get("type", "ITEM"))

    if item_type == "WEAPON":
        add_item(item_name, "ARMAS")
        return

    if not inventory.has(item_name):
        inventory.append(item_name)
    _register_inventory_category(item_name, "OBJETOS")

    var hp_bonus := int(item.get("hp_bonus", 0))
    var protection_bonus := int(item.get("protection_bonus", 0))
    var stamina_bonus := float(item.get("stamina_bonus", 0))

    if hp_bonus > 0:
        max_health += hp_bonus
        health += hp_bonus
    if protection_bonus > 0:
        max_protection += protection_bonus
        protection += protection_bonus
    if stamina_bonus > 0.0:
        max_stamina += stamina_bonus
        stamina += stamina_bonus

func buy_item(item_name: String, price: int) -> bool:
    if coins < price:
        show_message("Moedas insuficientes: %d necessárias." % price)
        return false
    coins -= price
    if not inventory.has(item_name):
        inventory.append(item_name)
    _register_inventory_category(item_name)
    if _inventory_category_for(item_name) == "ARMAS":
        _ensure_weapon_state(item_name)
    if equipped_weapon.is_empty() and _inventory_category_for(item_name) == "ARMAS":
        equipped_weapon = item_name
    _inventory_ui_dirty = true
    show_message("Comprado: %s por %d moedas." % [item_name, price])
    _update_hud()
    return true

func add_lore(title: String) -> void:
    if not lore.has(title):
        lore.append(title)
    show_message("Livro lido: %s" % title)

func toggle_seat_at(seat_target: Node3D, world_pos: Vector3) -> void:
    if sitting and seat_target == _seated_target:
        stand_up(true)
        return
    if sitting:
        stand_up(false)
    _cancel_all_actions(false)
    global_position = world_pos
    velocity = Vector3.ZERO
    sitting = true
    _seated_target = seat_target
    show_message("Você se sentou. Clique novamente na cadeira ou no chão para levantar.")

func sit_at(world_pos: Vector3) -> void:
    # Compatibilidade com chamadas antigas.
    toggle_seat_at(null, world_pos)

func stand_up(show_feedback: bool = true) -> void:
    if not sitting:
        return
    sitting = false
    _seated_target = null
    velocity = Vector3.ZERO
    if show_feedback:
        show_message("Você se levantou.")

func teleport_to(world_pos: Vector3, dungeon_state: bool) -> void:
    _cancel_all_actions(false)
    global_position = world_pos
    velocity = Vector3.ZERO
    in_dungeon = dungeon_state
    show_message("Entrando na masmorra..." if dungeon_state else "Retornando à superfície...")

func _has_torch_item() -> bool:
    for entry in inventory:
        if entry.to_lower().contains("tocha"):
            return true
    return false

func ensure_torch_on() -> void:
    if not _has_torch_item():
        return
    if not torch_on:
        torch_on = true
        _torch_light.light_energy = 3.2
        show_message("Tocha equipada e acesa.")

func toggle_inventory() -> void:
    _inventory_open = not _inventory_open
    if is_instance_valid(_inventory_panel):
        _inventory_panel.visible = _inventory_open
    if _inventory_open:
        _inventory_ui_dirty = true
    _refresh_inventory_panel()

func _weapon_button_text(item_name: String) -> String:
    var profile := _weapon_profile_for(item_name)
    var selected := "▶ " if item_name == equipped_weapon else "   "
    var current_durability := get_weapon_durability(item_name)
    var max_durability := int(profile.get("durability_max", 0))
    var class_label := "DIST" if str(profile.get("combat_class", "MELEE")) == "RANGED" else "CORPO"
    if str(profile.get("combat_class", "")) == "MID_MELEE":
        class_label = "MÉDIO"
    return "%s%s | %s | D%d | %.1fm | Dur %d/%d" % [
        selected,
        item_name,
        class_label,
        int(profile.get("damage", 0)),
        float(profile.get("attack_range_m", 0.0)),
        current_durability,
        max_durability
    ]

func _selected_weapon_detail() -> String:
    if equipped_weapon.is_empty():
        return "SELECIONADA\n— nenhuma —"
    var p := _weapon_profile_for(equipped_weapon)
    var current_durability := get_weapon_durability(equipped_weapon)
    return "SELECIONADA\n%s\nClasse %s | Dano %d | Alcance %.1fm\nDurabilidade %d/%d | Dist. mínima %.1fm\nStamina/ataque %.0f | Vs Escudo x%.2f | Pen. HP x%.2f\nPWR %d | DEF %d | UTI %d | MAN %d\nDUR %d | REACH %d | MAG %d | TEC %d | OVR %d\n%s" % [
        equipped_weapon,
        str(p.get("combat_class", "MELEE")),
        int(p.get("damage", 0)),
        float(p.get("attack_range_m", 0.0)),
        current_durability,
        int(p.get("durability_max", 0)),
        float(p.get("min_range_m", 0.0)),
        float(p.get("stamina_cost", 10.0)),
        float(p.get("shield_damage_factor", 0.0)),
        float(p.get("hp_through_shield_factor", 0.0)),
        int(p.get("power", 0)),
        int(p.get("defense", 0)),
        int(p.get("utility", 0)),
        int(p.get("handling", 0)),
        int(p.get("durability_stat", 0)),
        int(p.get("reach_stat", 0)),
        int(p.get("magic_affinity", 0)),
        int(p.get("tech_affinity", 0)),
        int(p.get("overall", 0)),
        str(p.get("authority", "DEV"))
    ]

func _refresh_inventory_panel() -> void:
    if not _inventory_open or not _inventory_ui_dirty:
        return
    if not is_instance_valid(_inventory_label) or not is_instance_valid(_inventory_weapon_list):
        return

    _inventory_ui_dirty = false
    var weapons: Array[String] = []
    var materials: Array[String] = []
    var objects: Array[String] = []

    for entry in inventory:
        match _inventory_category_for(entry):
            "ARMAS":
                weapons.append(entry)
            "MATERIAIS":
                materials.append(entry)
            _:
                objects.append(entry)

    for child in _inventory_weapon_list.get_children():
        child.queue_free()

    if weapons.is_empty():
        var empty_label := Label.new()
        empty_label.text = "ARMAS\n— nenhuma —"
        empty_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
        _inventory_weapon_list.add_child(empty_label)
    else:
        var weapons_header := Label.new()
        weapons_header.text = "ARMAS"
        weapons_header.mouse_filter = Control.MOUSE_FILTER_IGNORE
        _inventory_weapon_list.add_child(weapons_header)
        for weapon_name in weapons:
            var button := Button.new()
            button.text = _weapon_button_text(weapon_name)
            button.tooltip_text = "Clique esquerdo para equipar %s" % weapon_name
            button.custom_minimum_size = Vector2(420, 34)
            button.mouse_filter = Control.MOUSE_FILTER_STOP
            button.pressed.connect(_on_inventory_weapon_pressed.bind(weapon_name))
            _inventory_weapon_list.add_child(button)

    var materials_text := "—" if materials.is_empty() else "• " + "\n• ".join(materials)
    var objects_text := "—" if objects.is_empty() else "• " + "\n• ".join(objects)
    _inventory_label.text = "%s\n\nMATERIAIS\n%s\n\nOBJETOS\n%s\n\n[I] fechar" % [
        _selected_weapon_detail(),
        materials_text,
        objects_text
    ]

func toggle_torch() -> void:
    if not _has_torch_item():
        show_message("Você ainda não possui uma tocha.")
        return
    torch_on = not torch_on
    _torch_light.light_energy = 3.2 if torch_on else 0.0
    show_message("Tocha acesa." if torch_on else "Tocha apagada.")

func take_damage(amount: int, source_name: String = "ameaça", source_node: Node3D = null) -> void:
    var incoming := maxi(0, amount)
    var protection_damage := 0
    var health_damage := incoming

    if protection > 0 and incoming > 0:
        # Proteção DEV: absorve ~65% do golpe enquanto houver reserva.
        var desired_protection_damage := maxi(1, int(ceil(float(incoming) * 0.65)))
        protection_damage = mini(protection, desired_protection_damage)
        protection = maxi(0, protection - protection_damage)
        health_damage = maxi(0, incoming - protection_damage)

    health = maxi(0, health - health_damage)
    show_message("%s • HP -%d | Proteção -%d." % [source_name, health_damage, protection_damage])

    # Regra ranged final preservada: receber o golpe é o gatilho de recuo,
    # mesmo quando parte importante foi absorvida pela Proteção.
    if health > 0 and incoming > 0 and _current_weapon_is_ranged() and is_instance_valid(source_node):
        _trigger_ranged_retreat_from_damage(source_node)

    if health <= 0:
        health = max_health
        stamina = max_stamina
        protection = max_protection
        _cancel_all_actions(false)
        global_position = Vector3(0, 0.9, 8)
        show_message("Você caiu e retornou ao ponto de teste com recursos restaurados.")

func show_message(text: String) -> void:
    if is_instance_valid(_message_label):
        _message_label.text = text
    _message_time = 4.0
    world_message.emit(text)

func _update_hud() -> void:
    if not is_instance_valid(_status_label):
        return
    if is_instance_valid(_health_bar):
        _health_bar.max_value = float(max_health)
        _health_bar.value = float(health)
        _health_bar.tooltip_text = "HP %d/%d" % [health, max_health]
    if is_instance_valid(_stamina_bar):
        _stamina_bar.max_value = max_stamina
        _stamina_bar.value = stamina
        _stamina_bar.tooltip_text = "Stamina %d/%d" % [int(stamina), int(max_stamina)]
    if is_instance_valid(_protection_bar):
        _protection_bar.max_value = float(max_protection)
        _protection_bar.value = float(protection)
        _protection_bar.tooltip_text = "Proteção %d/%d" % [protection, max_protection]

    var zone := "Masmorra de Vigília" if in_dungeon else "Campo de Testes — Terras Livres"
    var weapon := equipped_weapon if not equipped_weapon.is_empty() else "nenhuma"
    if not equipped_weapon.is_empty():
        var weapon_profile := _current_weapon_profile()
        weapon = "%s [D%d | %.1fm | Dur %d/%d]" % [
            equipped_weapon,
            int(weapon_profile.get("damage", 0)),
            float(weapon_profile.get("attack_range_m", 0.0)),
            get_weapon_durability(equipped_weapon),
            int(weapon_profile.get("durability_max", 0))
        ]
    var selected_target_text := "nenhum"
    if _selected_target != null and is_instance_valid(_selected_target) and _selected_target.is_inside_tree():
        selected_target_text = "%s [%s]" % [
            _target_display_name(_selected_target),
            _selected_target_action_hint(_selected_target)
        ]
    _status_label.text = "V0.1.25 FIX2 • %s • $%d\n%s\nAlvo: %s" % [zone, coins, weapon, selected_target_text]
    if _inventory_open:
        _refresh_inventory_panel()
