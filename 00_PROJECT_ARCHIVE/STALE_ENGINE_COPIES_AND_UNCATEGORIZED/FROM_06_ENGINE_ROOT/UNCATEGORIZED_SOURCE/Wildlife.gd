extends CharacterBody3D
class_name AndromedaWildlife

const PATH_POINT_DISTANCE := 0.28
const REPATH_INTERVAL_S := 1.20
const CHASE_STOP_DISTANCE := 1.20
const PLAYER_REPATH_DISTANCE_M := 1.60
const WANDER_INTERVAL_S := 3.2
const STALL_REPATH_DELAY_S := 0.55
const MIN_PROGRESS_DISTANCE_M := 0.06
const PROXIMITY_AGGRO_DISTANCE_M := 7.0

const ENEMY_TIER_PROFILES := {
    "FRACO": {
        "display": "FRACO",
        "speed": 2.0,
        "attack_damage": 8,
        "health_multiplier": 0.85,
        "attack_interval_s": 1.90,
        "visual_scale": 0.92
    },
    "MEDIO": {
        "display": "MÉDIO",
        "speed": 2.3,
        "attack_damage": 11,
        "health_multiplier": 1.00,
        "attack_interval_s": 1.70,
        "visual_scale": 1.00
    },
    "FORTE": {
        "display": "FORTE",
        "speed": 2.6,
        "attack_damage": 16,
        "health_multiplier": 1.35,
        "attack_interval_s": 1.55,
        "visual_scale": 1.10
    },
    "ALFA": {
        "display": "ALFA",
        "speed": 2.9,
        "attack_damage": 23,
        "health_multiplier": 1.85,
        "attack_interval_s": 1.35,
        "visual_scale": 1.25
    }
}

var species_name: String = "Criatura"
var health: int = 60
var max_health: int = 60
var shield: int = 0
var max_shield: int = 0
var hostile: bool = false
var enemy_tier: String = "FRACO"
var move_speed: float = 1.4
var attack_damage: int = 8
var attack_interval_s: float = 1.90
var _tier_move_speed: float = 2.0
var _player: Node3D
var _attack_cooldown: float = 0.0
var _home: Vector3
var _phase: float = 0.0
var _repath_timer: float = 0.0
var _wander_timer: float = 0.0
var _last_player_position: Vector3 = Vector3.ZERO
var _path_points: Array[Vector3] = []
var _path_index: int = 0
var _stall_time: float = 0.0
var _aggro_active: bool = false
var _aggro_target: Node3D
var _visual_scale: float = 1.0
var _combat_bar_layer: CanvasLayer
var _combat_bar_root: Control
var _health_bar_fill: ProgressBar
var _shield_bar_fill: ProgressBar
var combat_style: String = "MELEE"
var ranged_attack_range: float = 9.0
var ranged_attack_damage: int = 12
var one_shot: bool = false

func setup(label: String, color: Color, p_hostile: bool = false, p_health: int = 60, p_tier: String = "FRACO", p_combat_style: String = "MELEE", p_ranged_damage: int = -1, p_ranged_range: float = 9.0, p_one_shot: bool = false) -> void:
    species_name = label
    name = label.replace(" ", "_")
    hostile = p_hostile
    combat_style = p_combat_style.to_upper()
    ranged_attack_range = p_ranged_range
    one_shot = p_one_shot
    enemy_tier = p_tier.to_upper()
    if not ENEMY_TIER_PROFILES.has(enemy_tier):
        enemy_tier = "FRACO"

    var tier_profile: Dictionary = ENEMY_TIER_PROFILES[enemy_tier]
    _tier_move_speed = float(tier_profile.get("speed", 2.0))
    attack_damage = int(tier_profile.get("attack_damage", 8))
    ranged_attack_damage = p_ranged_damage if p_ranged_damage >= 0 else attack_damage
    attack_interval_s = float(tier_profile.get("attack_interval_s", 1.90))
    move_speed = _tier_move_speed if hostile else 1.4

    var health_multiplier := float(tier_profile.get("health_multiplier", 1.0)) if hostile else 1.0
    health = maxi(1, int(round(float(p_health) * health_multiplier)))
    max_health = health

    # Apenas ALFA possui Escudo nesta etapa.
    if hostile and enemy_tier == "ALFA":
        max_shield = mini(max_health - 1, maxi(1, int(round(float(max_health) * 0.48))))
        shield = max_shield
    else:
        max_shield = 0
        shield = 0

    collision_layer = 1
    collision_mask = 1
    floor_snap_length = 0.25
    add_to_group("wildlife")
    add_to_group("hoverable")
    _home = global_position
    _phase = float(abs(hash(label)) % 1000) / 100.0

    var visual := MeshInstance3D.new()
    var mesh := CapsuleMesh.new()
    _visual_scale = float(tier_profile.get("visual_scale", 1.0)) if hostile else 1.0
    mesh.radius = (0.5 * _visual_scale) if hostile else 0.38
    mesh.height = (1.2 * _visual_scale) if hostile else 0.9
    visual.mesh = mesh
    var material := StandardMaterial3D.new()
    material.albedo_color = color
    material.roughness = 0.85
    visual.material_override = material
    add_child(visual)

    if hostile and combat_style == "RANGED":
        var weapon_visual := MeshInstance3D.new()
        weapon_visual.name = "RangedWeapon"
        var weapon_mesh := BoxMesh.new()
        weapon_mesh.size = Vector3(0.16, 0.16, 0.95)
        weapon_visual.mesh = weapon_mesh
        weapon_visual.position = Vector3(0.38, 0.15, 0.20)
        var weapon_material := StandardMaterial3D.new()
        weapon_material.albedo_color = Color(0.16, 0.16, 0.18)
        weapon_visual.material_override = weapon_material
        add_child(weapon_visual)

    var collision := CollisionShape3D.new()
    collision.name = "WildlifeCollision"
    var shape := CapsuleShape3D.new()
    shape.radius = mesh.radius
    shape.height = mesh.height
    collision.shape = shape
    add_child(collision)

    _build_combat_bars()

func _make_bar_style(color: Color) -> StyleBoxFlat:
    var style := StyleBoxFlat.new()
    style.bg_color = color
    style.corner_radius_top_left = 2
    style.corner_radius_top_right = 2
    style.corner_radius_bottom_left = 2
    style.corner_radius_bottom_right = 2
    return style

func _make_screen_bar(parent: Control, y: float, height: float, fill_color: Color) -> ProgressBar:
    var bar := ProgressBar.new()
    bar.position = Vector2(0, y)
    bar.size = Vector2(86, height)
    bar.min_value = 0.0
    bar.max_value = 100.0
    bar.value = 100.0
    bar.show_percentage = false
    bar.mouse_filter = Control.MOUSE_FILTER_IGNORE
    bar.add_theme_stylebox_override("background", _make_bar_style(Color(0.06, 0.06, 0.07, 0.92)))
    bar.add_theme_stylebox_override("fill", _make_bar_style(fill_color))
    parent.add_child(bar)
    return bar

func _build_combat_bars() -> void:
    # UI 2D projetada: horizontal e sem rotação 3D.
    _combat_bar_layer = CanvasLayer.new()
    _combat_bar_layer.name = "CombatBarLayer"
    _combat_bar_layer.layer = 20
    add_child(_combat_bar_layer)

    _combat_bar_root = Control.new()
    _combat_bar_root.name = "CombatBars"
    _combat_bar_root.size = Vector2(86, 32 if enemy_tier == "ALFA" else 20)
    _combat_bar_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
    _combat_bar_root.visible = hostile
    _combat_bar_layer.add_child(_combat_bar_root)

    _health_bar_fill = _make_screen_bar(_combat_bar_root, 0.0, 8.0, Color(0.88, 0.10, 0.10, 1.0))
    _health_bar_fill.name = "HealthBarFill"

    if enemy_tier == "ALFA" and max_shield > 0:
        _shield_bar_fill = _make_screen_bar(_combat_bar_root, 12.0, 6.0, Color(0.14, 0.50, 0.95, 1.0))
        _shield_bar_fill.name = "ShieldBarFill"

    _update_combat_bars()

func _update_combat_bars() -> void:
    if not is_instance_valid(_combat_bar_root):
        return

    if not hostile or health <= 0:
        _combat_bar_root.visible = false
        return

    var camera := get_viewport().get_camera_3d()
    if camera == null or not is_instance_valid(camera):
        _combat_bar_root.visible = false
        return
    if camera.is_position_behind(global_position):
        _combat_bar_root.visible = false
        return

    var screen_position := camera.unproject_position(global_position + Vector3(0.0, 1.65 * _visual_scale, 0.0))
    if not get_viewport().get_visible_rect().has_point(screen_position):
        _combat_bar_root.visible = false
        return

    _combat_bar_root.visible = true
    _combat_bar_root.position = screen_position - Vector2(_combat_bar_root.size.x * 0.5, 24.0)

    if is_instance_valid(_health_bar_fill):
        _health_bar_fill.max_value = float(maxi(1, max_health))
        _health_bar_fill.value = float(health)
        _health_bar_fill.tooltip_text = "HP %d/%d" % [health, max_health]

    if is_instance_valid(_shield_bar_fill):
        _shield_bar_fill.max_value = float(maxi(1, max_shield))
        _shield_bar_fill.value = float(shield)
        _shield_bar_fill.tooltip_text = "Escudo %d/%d" % [shield, max_shield]

func _ready() -> void:
    _player = get_tree().get_first_node_in_group("player") as Node3D
    if is_instance_valid(_player):
        _last_player_position = _player.global_position

func _fire_enemy_projectile(target: Node3D) -> void:
    if target == null or not is_instance_valid(target):
        return

    _attack_cooldown = 2.6 if one_shot else 2.0
    var world_parent := get_parent()
    if world_parent == null:
        return

    var projectile := MeshInstance3D.new()
    projectile.name = "EnemyOneShotProjectile" if one_shot else "EnemyProjectile"
    var mesh := BoxMesh.new()
    mesh.size = Vector3(0.08, 0.08, 0.55)
    projectile.mesh = mesh
    var material := StandardMaterial3D.new()
    material.albedo_color = Color(0.95, 0.30, 0.10) if one_shot else Color(0.78, 0.70, 0.32)
    projectile.material_override = material
    world_parent.add_child(projectile)

    var start_pos: Vector3 = global_position + Vector3(0.0, 0.85, 0.0)
    var end_pos: Vector3 = target.global_position + Vector3(0.0, 0.75, 0.0)
    projectile.global_position = start_pos
    if start_pos.distance_to(end_pos) > 0.05:
        projectile.look_at(end_pos, Vector3.UP)

    var travel_time: float = clampf(start_pos.distance_to(end_pos) / 24.0, 0.14, 0.45)
    var tween: Tween = projectile.create_tween()
    tween.tween_property(projectile, "global_position", end_pos, travel_time)
    tween.tween_callback(_resolve_enemy_projectile.bind(projectile, target))

func _resolve_enemy_projectile(projectile, target) -> void:
    if target != null and is_instance_valid(target) and target.has_method("take_damage"):
        var damage := 999 if one_shot else ranged_attack_damage
        target.call("take_damage", damage, "%s [RANGED%s]" % [species_name, " ONE-SHOT" if one_shot else ""], self)
    if projectile != null and is_instance_valid(projectile):
        projectile.queue_free()

func _physics_process(delta: float) -> void:
    if health <= 0:
        return

    _update_combat_bars()
    _attack_cooldown = maxf(0.0, _attack_cooldown - delta)
    _repath_timer = maxf(0.0, _repath_timer - delta)
    _wander_timer = maxf(0.0, _wander_timer - delta)

    if _aggro_active and is_instance_valid(_aggro_target):
        _player = _aggro_target
    elif not is_instance_valid(_player):
        _player = get_tree().get_first_node_in_group("player") as Node3D
        return

    if not is_instance_valid(_player):
        return

    var distance := global_position.distance_to(_player.global_position)
    var direction := Vector3.ZERO

    if hostile and combat_style == "DUMMY":
        _clear_path()
        velocity.x = 0.0
        velocity.z = 0.0

    else:
        var perception_distance := PROXIMITY_AGGRO_DISTANCE_M
        if combat_style == "RANGED":
            perception_distance = ranged_attack_range + 3.0

        if hostile and (_aggro_active or distance < perception_distance):
            if combat_style == "RANGED":
                if distance <= ranged_attack_range:
                    _clear_path()
                    if _attack_cooldown <= 0.0:
                        _fire_enemy_projectile(_player)
                else:
                    var moved_ranged := _player.global_position.distance_to(_last_player_position) >= PLAYER_REPATH_DISTANCE_M
                    if _repath_timer <= 0.0 and (_path_points.is_empty() or moved_ranged):
                        _request_path(_player.global_position, maxf(2.0, ranged_attack_range * 0.78))
                        _last_player_position = _player.global_position
                        _repath_timer = REPATH_INTERVAL_S
                    direction = _path_direction()
            else:
                if distance < 1.5 and _attack_cooldown <= 0.0:
                    if _player.has_method("take_damage"):
                        _player.take_damage(attack_damage, "%s [%s]" % [species_name, _tier_display_name()], self)
                    _attack_cooldown = attack_interval_s

                var player_moved := _player.global_position.distance_to(_last_player_position) >= PLAYER_REPATH_DISTANCE_M
                if distance > CHASE_STOP_DISTANCE and _repath_timer <= 0.0 and (_path_points.is_empty() or player_moved):
                    _request_path(_player.global_position, CHASE_STOP_DISTANCE)
                    _last_player_position = _player.global_position
                    _repath_timer = REPATH_INTERVAL_S
                direction = _path_direction()

        elif not hostile:
            if _path_points.is_empty() and _wander_timer <= 0.0:
                _phase += 1.37
                var target := _home + Vector3(cos(_phase) * 2.0, 0.0, sin(_phase) * 2.0)
                _request_path(target, 0.0)
                _wander_timer = WANDER_INTERVAL_S
            direction = _path_direction()
        else:
            _clear_path()

    if direction.length() > 0.2:
        direction = direction.normalized()
        var main_node := get_parent()
        var next_point := global_position + direction * move_speed * delta
        if main_node != null and main_node.has_method("is_water_point") and bool(main_node.call("is_water_point", next_point)):
            direction = Vector3.ZERO
            velocity.x = 0.0
            velocity.z = 0.0
            _clear_path()
            _repath_timer = 0.0
        else:
            velocity.x = direction.x * move_speed
            velocity.z = direction.z * move_speed
            var desired_yaw := atan2(direction.x, direction.z)
            rotation.y = lerp_angle(rotation.y, desired_yaw, clampf(7.0 * delta, 0.0, 1.0))
    else:
        velocity.x = move_toward(velocity.x, 0.0, 4.0 * delta)
        velocity.z = move_toward(velocity.z, 0.0, 4.0 * delta)

    if not is_on_floor():
        velocity.y -= 9.8 * delta
    else:
        velocity.y = -0.3

    var before_move := global_position
    move_and_slide()

    if direction.length() > 0.2:
        var planar_progress := Vector2(global_position.x - before_move.x, global_position.z - before_move.z).length()
        if planar_progress < MIN_PROGRESS_DISTANCE_M * delta:
            _stall_time += delta
        else:
            _stall_time = 0.0
        if _stall_time >= STALL_REPATH_DELAY_S and _repath_timer <= 0.0:
            _clear_path()
            _stall_time = 0.0
    else:
        _stall_time = 0.0

func _request_path(destination: Vector3, stop_distance: float) -> bool:
    var main_node := get_parent()
    if main_node == null or not main_node.has_method("find_navigation_path"):
        _clear_path()
        return false
    var result: Variant = main_node.call("find_navigation_path", global_position, destination, stop_distance, self)
    if not (result is Array):
        _clear_path()
        return false
    _path_points.clear()
    for entry in result:
        if entry is Vector3:
            _path_points.append(entry)
    _path_index = 0
    return not _path_points.is_empty()

func _path_direction() -> Vector3:
    while _path_index < _path_points.size():
        var waypoint := _path_points[_path_index]
        var offset := waypoint - global_position
        offset.y = 0.0
        if offset.length() <= PATH_POINT_DISTANCE:
            _path_index += 1
            continue
        return offset.normalized()
    _clear_path()
    return Vector3.ZERO

func _clear_path() -> void:
    _path_points.clear()
    _path_index = 0

func get_species_name() -> String:
    return species_name

func get_display_name() -> String:
    return species_name

func _tier_display_name() -> String:
    if ENEMY_TIER_PROFILES.has(enemy_tier):
        return str(ENEMY_TIER_PROFILES[enemy_tier].get("display", enemy_tier))
    return enemy_tier

func get_hover_info() -> Dictionary:
    var behavior := "Em perseguição" if _aggro_active else ("Predador hostil" if hostile else "Fauna local")
    var tier_text := _tier_display_name() if hostile else "FAUNA"
    var defense_text := "HP %d/%d" % [health, max_health]
    if enemy_tier == "ALFA" and max_shield > 0:
        defense_text += " • Escudo %d/%d" % [shield, max_shield]
    return {
        "title": "%s • %s" % [species_name, tier_text],
        "detail": "Animal • %s • %s • %s • Dano %d • Vel %.1f" % [behavior, defense_text, combat_style, 999 if one_shot else (ranged_attack_damage if combat_style == "RANGED" else attack_damage), move_speed]
    }

func is_enemy() -> bool:
    return hostile and health > 0

func is_alive() -> bool:
    return health > 0 and not is_queued_for_deletion()

func trigger_aggro(attacker: Node) -> void:
    # V0.1.16: receber dano é um gatilho de hostilidade independente
    # do raio de percepção. Isso permite resposta imediata a arco/besta.
    if attacker is Node3D and is_instance_valid(attacker):
        _aggro_target = attacker as Node3D
        _player = _aggro_target
    elif not is_instance_valid(_player):
        _player = get_tree().get_first_node_in_group("player") as Node3D

    hostile = true
    move_speed = _tier_move_speed
    if is_instance_valid(_combat_bar_root):
        _combat_bar_root.visible = true
    _aggro_active = true
    _clear_path()
    _repath_timer = 0.0
    _stall_time = 0.0

func is_aggro_active() -> bool:
    return _aggro_active

func _finalize_received_damage(attacker: Node, hp_damage: int, shield_damage: int) -> void:
    _update_combat_bars()

    if health > 0:
        trigger_aggro(attacker)

    if is_instance_valid(attacker) and attacker.has_method("show_message"):
        if enemy_tier == "ALFA" and max_shield > 0:
            attacker.show_message(
                "%s • HP -%d | Escudo -%d • Restante: HP %d/%d | Escudo %d/%d"
                % [species_name, hp_damage, shield_damage, health, max_health, shield, max_shield]
            )
        else:
            attacker.show_message("%s sofreu %d de dano. HP: %d/%d • AGGRO" % [species_name, hp_damage, health, max_health])

    if health <= 0:
        if is_instance_valid(attacker) and attacker.has_method("add_item"):
            attacker.add_item("Couro de %s" % species_name, "MATERIAIS")
        remove_from_group("wildlife")
        remove_from_group("hoverable")
        queue_free()

func take_weapon_damage(amount: int, weapon_profile: Dictionary, attacker: Node) -> void:
    var incoming := maxi(0, amount)
    var hp_damage := incoming
    var shield_damage := 0

    if enemy_tier == "ALFA" and shield > 0 and incoming > 0:
        var shield_factor := clampf(float(weapon_profile.get("shield_damage_factor", 0.65)), 0.05, 1.50)
        var hp_factor := clampf(float(weapon_profile.get("hp_through_shield_factor", 0.00)), 0.00, 0.95)

        var requested_shield_damage := maxi(1, int(round(float(incoming) * shield_factor)))
        shield_damage = mini(shield, requested_shield_damage)
        var overflow := maxi(0, requested_shield_damage - shield_damage)

        hp_damage = 0
        if hp_factor > 0.0:
            hp_damage = maxi(1, int(round(float(incoming) * hp_factor)))
        hp_damage += overflow

        # Contrato autoral: quando HP e Escudo caem no mesmo golpe,
        # os valores de redução nunca podem ser iguais.
        if hp_damage > 0 and shield_damage > 0 and hp_damage == shield_damage:
            if hp_damage > 1:
                hp_damage -= 1
            else:
                hp_damage += 1

        shield = maxi(0, shield - shield_damage)
        health = maxi(0, health - hp_damage)
    else:
        health = maxi(0, health - hp_damage)

    _finalize_received_damage(attacker, hp_damage, shield_damage)

func take_damage(amount: int, attacker: Node) -> void:
    # Compatibilidade com sistemas que ainda não enviam perfil de arma.
    take_weapon_damage(amount, {}, attacker)
