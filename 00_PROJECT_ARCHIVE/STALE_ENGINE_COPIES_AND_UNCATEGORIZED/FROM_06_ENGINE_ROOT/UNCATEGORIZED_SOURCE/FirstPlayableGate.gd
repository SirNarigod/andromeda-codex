extends SceneTree

var failures: Array[String] = []

func check(label: String, condition: bool) -> void:
    if not condition:
        failures.append(label)

func _initialize() -> void:
    call_deferred("_run_gate")

func _run_gate() -> void:
    var packed = load("res://Main.tscn")
    check("MAIN_SCENE_LOAD", packed != null)
    if packed == null:
        _finish()
        return
    var scene = packed.instantiate()
    root.add_child(scene)
    await process_frame
    await process_frame
    await process_frame

    check("MAIN_INSTANCE", scene != null)
    var player = scene.get_node_or_null("Player")
    check("PLAYER_EXISTS", player != null)
    check("INTERACTABLES_CREATED", get_nodes_in_group("interactable").size() >= 10)
    check("WILDLIFE_CREATED", get_nodes_in_group("wildlife").size() >= 3)
    check("NAV_OBSTACLES_CREATED", get_nodes_in_group("navigation_obstacle").size() >= 10)
    check("LIVING_CLIENT_EXISTS", scene.get_node_or_null("LivingWorldClient") != null)
    check("WORLD_ENVIRONMENT_CREATED", scene.get_node_or_null("WorldEnvironment") != null)
    check("SUN_CREATED", scene.get_node_or_null("DirectionalLight3D") != null)
    check("GROUND_CREATED", scene.get_node_or_null("Ground") != null)
    check("BOOTSTRAP_VISUAL_READY", bool(scene.get("_bootstrap_visual_ready")) == true)
    check("ASTAR_PATHFINDER", scene.has_method("find_navigation_path"))

    if player != null:
        check("PLAYER_COLLISION", player.get_node_or_null("PlayerCollision") != null)
        check("PLAYER_VISUAL", player.get_node_or_null("PlayerMesh") != null)
        check("TORCH_LIGHT", player.get_node_or_null("TorchLight") != null)
        check("PLAYER_START_COINS", int(player.coins) == 100)
        check("PLAYER_START_HEALTH", int(player.health) == 100)
        check("PLAYER_MAX_HEALTH", int(player.max_health) == 100)
        check("PLAYER_START_STAMINA", int(player.stamina) == 100)
        check("PLAYER_START_PROTECTION", int(player.protection) == 60)
        check("PLAYER_MAX_PROTECTION", int(player.max_protection) == 60)
        check("PLAYER_GROUP", player.is_in_group("player"))
        check("LEFT_PRESS_HANDLER", player.has_method("_handle_left_press"))
        check("LEFT_MOVE_WORLD_POINT", player.has_method("_movement_point_at"))
        check("LEFT_SCENE_TRANSITION_EXCEPTION", player.has_method("_transition_target_at"))
        check("LEFT_GENERIC_SELECTION_API", player.has_method("_selectable_target_at"))
        check("SELECT_TARGET_API", player.has_method("_select_target"))
        check("SELECTED_TARGET_GETTER", player.has_method("get_selected_target"))
        check("SPACE_ATTACK_SELECTED_API", player.has_method("_attack_selected_target"))
        check("E_INTERACT_SELECTED_API", player.has_method("_interact_selected_target"))
        check("SELECTED_CONTEXT_KIND_API", player.has_method("_selected_target_context_kind"))
        check("SELECTED_SELECTABLE_API", player.has_method("_selected_target_is_selectable"))
        check("RIGHT_PRESS_HANDLER", player.has_method("_handle_right_press"))
        check("TARGET_ACTION", player.has_method("_begin_target_action"))
        check("INTERACTION_QUEUE", player.has_method("_queue_interaction"))
        check("INTERACTION_DEFERRED_DISPATCH", player.has_method("_dispatch_pending_interaction"))
        check("AUTO_ATTACK", player.has_method("_perform_attack_on"))
        check("PLAYER_HEALTH_BAR", player.get_node_or_null("HUD/ColorRect/ProgressBar") != null or player.get("_health_bar") != null)
        check("CLICK_MOVE_DESTINATION", player.has_method("_set_click_move_destination"))
        check("CLICK_HOLD_DETECTOR", player.has_method("_update_press_candidate"))
        check("POINTER_RELEASE_HANDLER", player.has_method("_handle_pointer_release"))
        check("HOLD_MOVE_START", player.has_method("_begin_hold_movement"))
        check("HOLD_MOVE_UPDATE", player.has_method("_update_hold_movement"))
        check("HOLD_MOVE_STOP", player.has_method("_stop_hold_movement"))
        check("INVENTORY_TOGGLE", player.has_method("toggle_inventory"))
        check("INVENTORY_REFRESH", player.has_method("_refresh_inventory_panel"))
        check("INVENTORY_CATEGORY_API", player.has_method("_inventory_category_for"))
        check("INVENTORY_WEAPON_SELECTION", player.has_method("select_weapon"))
        check("WEAPON_PROFILE_API", player.has_method("get_weapon_profile"))
        check("WEAPON_DURABILITY_API", player.has_method("get_weapon_durability"))
        check("RANGED_RETREAT_API", player.has_method("_request_ranged_retreat"))
        check("RANGED_CYCLE_STATE", player.get("_ranged_cycle_state") != null)
        check("RANGED_SETTLE_TIMER", player.get("_ranged_settle_timer") != null)
        check("RANGED_RETREAT_TIMER", player.get("_ranged_retreat_timer") != null)
        check("RANGED_DAMAGE_RETREAT_API", player.has_method("_trigger_ranged_retreat_from_damage"))
        check("RANGED_DAMAGE_REACTION_UPDATE", player.has_method("_update_ranged_damage_reaction"))
        check("RANGED_RETREAT_SOURCE_STATE", player.get("_ranged_retreat_source") == null)
        check("RANGED_PROJECTILE_API", player.has_method("_spawn_ranged_projectile"))
        var expanded_wildlife_nodes := get_nodes_in_group("wildlife")
        check("EXPANDED_WILDLIFE_COUNT", expanded_wildlife_nodes.size() >= 10)
        check("SWORD_VENDOR_EXISTS", scene.get_node_or_null("SwordVendor_NPC") != null)
        check("BOW_VENDOR_EXISTS", scene.get_node_or_null("BowVendor_NPC") != null)
        var inventory_panel = player.get_node_or_null("HUD/InventoryPanel")
        check("INVENTORY_PANEL_EXISTS", inventory_panel != null)
        check("INVENTORY_WEAPON_LIST_EXISTS", player.get_node_or_null("HUD/InventoryPanel/WeaponList") != null)
        if inventory_panel != null:
            check("INVENTORY_HIDDEN_BY_DEFAULT", inventory_panel.visible == false)
        var move_marker = player.get_parent().get_node_or_null("MoveTargetMarker")
        check("MOVE_TARGET_MARKER", move_marker != null)
        var selection_marker = player.get_parent().get_node_or_null("WorldSelectionMarker")
        check("ENEMY_SELECTION_MARKER", selection_marker != null)
        if selection_marker != null and selection_marker.mesh is CylinderMesh:
            check("ENEMY_SELECTION_MARKER_SIZE", (selection_marker.mesh as CylinderMesh).top_radius >= 0.65)
        if move_marker != null and move_marker.mesh is CylinderMesh:
            check("MOVE_TARGET_MARKER_SUBTLE_SIZE", (move_marker.mesh as CylinderMesh).top_radius <= 0.26)

    var entrance = scene.get_node_or_null("DungeonEntrance")
    var exit = scene.get_node_or_null("DungeonExit")
    check("DUNGEON_ENTRANCE", entrance != null)
    check("DUNGEON_EXIT", exit != null)
    check("SHOP_EXISTS", scene.get_node_or_null("Shop") != null)
    check("BRIDGE_EXISTS", scene.get_node_or_null("Bridge") != null)
    check("RIVER_EXISTS", scene.get_node_or_null("River") != null)
    check("RIVER_BANKS_EXIST", scene.get_node_or_null("RiverBankNorth") != null and scene.get_node_or_null("RiverBankSouth") != null)
    check("WALKABLE_SURFACES", get_nodes_in_group("walkable_surface").size() >= 3)
    if scene.has_method("is_water_point"):
        check("RIVER_SIDE_BLOCKED", bool(scene.is_water_point(Vector3(10, 0, -12))) == true)
        check("BRIDGE_CENTER_OPEN", bool(scene.is_water_point(Vector3(0, 0, -12))) == false)
        check("BRIDGE_SAFE_EDGE_OPEN", bool(scene.is_water_point(Vector3(3.4, 0, -12))) == false)

    if scene.has_method("find_navigation_path"):
        var bridge_path = scene.find_navigation_path(Vector3(0, 0.9, 8), Vector3(0, 0.9, -20), 0.0, null)
        check("PATH_ACROSS_BRIDGE", bridge_path.size() > 0)
        var obstacle_path = scene.find_navigation_path(Vector3(-10, 0.9, 6), Vector3(-18, 0.9, -6), 0.0, null)
        check("PATH_AROUND_OBSTACLE", obstacle_path.size() > 0)

    check("NAV_CACHE_API", scene.has_method("get_navigation_cache_build_count"))
    var wildlife_nodes = get_nodes_in_group("wildlife")
    if wildlife_nodes.size() > 0:
        var first_wildlife = wildlife_nodes[0]
        check("WILDLIFE_COLLISION", first_wildlife.get_node_or_null("WildlifeCollision") != null)
        check("WILDLIFE_COMBAT_BARS", first_wildlife.get_node_or_null("CombatBarLayer/CombatBars") != null)
        check("WILDLIFE_WEAPON_DAMAGE_API", first_wildlife.has_method("take_weapon_damage"))
    var alpha_node = scene.get_node_or_null("Velúrio_Alfa_Final")
    check("ALPHA_EXISTS", alpha_node != null)
    if alpha_node != null:
        check("ALPHA_HAS_SHIELD", int(alpha_node.get("max_shield")) > 0)
        check("ALPHA_SHIELD_LT_HP", int(alpha_node.get("max_shield")) < int(alpha_node.get("max_health")))
        check("ALPHA_SHIELD_BAR", alpha_node.get_node_or_null("CombatBarLayer/CombatBars/ShieldBarFill") != null)
    var door = scene.get_node_or_null("Door")
    check("DOOR_EXISTS", door != null)
    if door != null:
        check("DOOR_INTERACTION_HITBOX", door.get_node_or_null("InteractionHitbox") != null)
    var chair = scene.get_node_or_null("Chair")
    check("CHAIR_EXISTS", chair != null)
    if player != null:
        check("CHAIR_TOGGLE_PLAYER_API", player.has_method("toggle_seat_at"))
        check("STAND_PLAYER_API", player.has_method("stand_up"))

    _finish()

func _finish() -> void:
    if failures.is_empty():
        print("ANDROMEDA_FIRST_PLAYABLE_V0_1_25_FIX2_GATE: PASS")
        quit(0)
    else:
        print("ANDROMEDA_FIRST_PLAYABLE_V0_1_25_FIX2_GATE: FAIL ", failures)
        quit(1)
