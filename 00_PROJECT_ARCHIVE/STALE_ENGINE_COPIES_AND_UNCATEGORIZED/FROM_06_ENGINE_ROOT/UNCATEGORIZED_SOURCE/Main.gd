extends Node3D

const InteractableScript = preload("res://Interactable.gd")
const WildlifeScript = preload("res://Wildlife.gd")
const LivingClientScript = preload("res://LivingWorldClient.gd")
const LivingTransportScript = preload("res://LivingWorldTransport.gd")

var player: AndromedaPrototypePlayer
var sun: DirectionalLight3D
var environment_resource: Environment
var living_client: LivingWorldClient
var living_transport: LivingWorldTransport
var _last_dungeon_state: bool = false
var _bootstrap_visual_ready: bool = false
var _bootstrap_phase: String = "INIT"

const NAV_MIN_X := -60.0
const NAV_MAX_X := 60.0
const NAV_MIN_Z := -55.0
const NAV_MAX_Z := 95.0
const NAV_CELL_SIZE := 1.0
const NAV_PADDING := 0.58

# Geometria compartilhada entre visual e navegação.
# O rio precisa estar visível; a ponte define a única faixa atravessável neste protótipo.
const RIVER_CENTER_Z := -12.0
const RIVER_WIDTH_Z := 5.0
const RIVER_Z_MIN := RIVER_CENTER_Z - RIVER_WIDTH_Z * 0.5
const RIVER_Z_MAX := RIVER_CENTER_Z + RIVER_WIDTH_Z * 0.5
const BRIDGE_WIDTH_X := 8.0
const PLAYER_NAV_RADIUS := 0.45
const BRIDGE_NAV_HALF_WIDTH := BRIDGE_WIDTH_X * 0.5 - PLAYER_NAV_RADIUS

var _navigation_grid_cache: AStarGrid2D
var _navigation_grid_dirty: bool = true
var _navigation_grid_builds: int = 0


func _ready() -> void:
	# O processamento só começa depois que o mundo visual mínimo existe.
	# Isso impede loops de erro por componentes ainda não inicializados.
	set_process(false)
	_bootstrap_phase = "PLAYER_BIND"
	player = $Player as AndromedaPrototypePlayer
	if not is_instance_valid(player):
		push_error("ANDROMEDA_BOOTSTRAP_FATAL: PLAYER_NOT_FOUND")
		return
	player.add_to_group("player")
	if not player.prototype_command.is_connected(_on_prototype_command):
		player.prototype_command.connect(_on_prototype_command)

	_bootstrap_phase = "ENVIRONMENT"
	_build_environment()
	_bootstrap_phase = "SURFACE"
	_build_surface()
	_bootstrap_phase = "DUNGEON"
	_build_dungeon()
	_bootstrap_phase = "NAVIGATION_CACHE"
	invalidate_navigation_cache()
	_warm_navigation_cache()

	_bootstrap_visual_ready = true
	_bootstrap_phase = "VISUAL_READY"
	set_process(true)
	print("ANDROMEDA_BOOTSTRAP_VISUAL: PASS")

	# A ponte Living é inicializada depois do cenário. Uma falha de integração
	# não pode apagar o first playable visual.
	_bootstrap_phase = "LIVING_CLIENT"
	_build_living_client()

	if is_instance_valid(living_client) and is_instance_valid(living_transport):
		print("ANDROMEDA_BOOTSTRAP_LIVING: CONNECTING")
	else:
		push_warning("ANDROMEDA_BOOTSTRAP_LIVING: DEGRADED")

	_bootstrap_phase = "READY"


func _build_living_client() -> void:
	living_client = LivingClientScript.new()
	living_client.name = "LivingWorldClient"
	add_child(living_client)
	living_client.bind_session("FIRST-PLAYABLE-V0-1-LOCAL")

	living_transport = LivingTransportScript.new()
	living_transport.name = "LivingWorldTransport"
	add_child(living_transport)

	living_transport.transport_ready.connect(_on_living_transport_ready)
	living_transport.transport_error.connect(_on_living_transport_error)
	living_transport.connect_client(living_client)


func _on_living_transport_ready() -> void:
	print("ANDROMEDA_LIVING_TRANSPORT: PASS")


func _on_living_transport_error(reason: String) -> void:
	push_warning("ANDROMEDA_LIVING_TRANSPORT: %s" % reason)

func _apply_initial_snapshot() -> void:
	var snapshot := {
		"status": "PASS",
		"server_authoritative": true,
		"transform": {"iso_x_m": player.position.x, "iso_y_m": player.position.z, "altitude_m": player.position.y, "heading_deg": 0.0},
		"chunk": {"chunk_id": "FP-V0-1-SURFACE", "entities": []},
		"environment": {"temperature_c": 23.0, "daylight": 0.9, "prototype": true}
	}
	living_client.apply_snapshot(snapshot)

func _build_environment() -> void:
	var world_environment := WorldEnvironment.new()
	environment_resource = Environment.new()
	environment_resource.background_mode = Environment.BG_COLOR
	environment_resource.background_color = Color(0.34, 0.49, 0.62)
	environment_resource.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment_resource.ambient_light_color = Color(0.62, 0.68, 0.74)
	environment_resource.ambient_light_energy = 0.75
	world_environment.environment = environment_resource
	add_child(world_environment)

	sun = DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-52, -35, 0)
	sun.light_energy = 1.15
	sun.shadow_enabled = true
	add_child(sun)

func _build_surface() -> void:
	_make_box("Ground", Vector3(0, -0.25, -4), Vector3(120, 0.5, 104), Color(0.24, 0.38, 0.20), true)
	_make_box("CentralRoad", Vector3(0, 0.02, -2), Vector3(8, 0.06, 92), Color(0.32, 0.29, 0.24), false)

	_make_box("River", Vector3(0, 0.035, RIVER_CENTER_Z), Vector3(120, 0.05, RIVER_WIDTH_Z), Color(0.08, 0.36, 0.68), false)
	_make_box("RiverBankNorth", Vector3(0, 0.045, RIVER_Z_MAX + 0.18), Vector3(120, 0.07, 0.36), Color(0.24, 0.20, 0.13), false)
	_make_box("RiverBankSouth", Vector3(0, 0.045, RIVER_Z_MIN - 0.18), Vector3(120, 0.07, 0.36), Color(0.24, 0.20, 0.13), false)
	_make_box("Bridge", Vector3(0, 0.09, RIVER_CENTER_Z), Vector3(BRIDGE_WIDTH_X, 0.10, 6), Color(0.48, 0.29, 0.12), false)

	_make_zone_pad("ZoneCommercial", Vector3(-36, 0.04, 16), Vector3(30, 0.05, 20), Color(0.34, 0.31, 0.22), "ÁREA COMERCIAL")
	_make_zone_pad("ZoneShooting", Vector3(35, 0.04, 16), Vector3(38, 0.05, 20), Color(0.24, 0.31, 0.29), "ESTANDE DE TIRO")
	_make_zone_pad("ZoneInteraction", Vector3(0, 0.04, 16), Vector3(20, 0.05, 20), Color(0.29, 0.28, 0.35), "INTERAÇÕES")
	_make_zone_pad("ZonePredators", Vector3(-36, 0.04, -30), Vector3(30, 0.05, 22), Color(0.28, 0.22, 0.18), "FAUNA / PREDADORES")
	_make_zone_pad("ZoneArmed", Vector3(35, 0.04, -30), Vector3(34, 0.05, 22), Color(0.25, 0.23, 0.20), "INIMIGOS ARMADOS")
	_make_zone_pad("ZoneAlpha", Vector3(0, 0.04, -42), Vector3(22, 0.05, 14), Color(0.30, 0.18, 0.18), "FINAL — ALFA")
	_make_zone_pad("ZoneOneShot", Vector3(49, 0.055, -40), Vector3(16, 0.04, 10), Color(0.36, 0.12, 0.12), "PERIGO — ONE-SHOT")

	_make_interactable("WeaponVendor_NPC", "SHOP_NPC", "Armeiro Orven", Vector3(-45, 0.9, 16), Vector3(0.9, 1.8, 0.9), Color(0.62, 0.29, 0.18), "WEAPONS", 0)
	_make_interactable("ArmorVendor_NPC", "SHOP_NPC", "Armadureira Kaela", Vector3(-36, 0.9, 16), Vector3(0.9, 1.8, 0.9), Color(0.34, 0.42, 0.58), "ARMOR", 0)
	_make_interactable("CosmeticVendor_NPC", "SHOP_NPC", "Estilista Nym", Vector3(-27, 0.9, 16), Vector3(0.9, 1.8, 0.9), Color(0.58, 0.34, 0.54), "COSMETICS", 0)

	_make_interactable("InteractionNPC", "NPC", "Instrutor do Laboratório", Vector3(-5, 0.9, 16), Vector3(0.9, 1.8, 0.9), Color(0.30, 0.46, 0.75))
	_make_interactable("Door", "DOOR", "Porta de Teste", Vector3(3, 1.0, 16), Vector3(1.3, 2.0, 0.25), Color(0.38, 0.18, 0.08))
	_make_interactable("Chair", "CHAIR", "Cadeira de Teste", Vector3(6, 0.5, 18), Vector3(0.8, 1.0, 0.8), Color(0.42, 0.25, 0.13))
	var book = _make_interactable("Book", "BOOK", "Manual do Laboratório", Vector3(5, 0.55, 13), Vector3(0.9, 0.18, 0.65), Color(0.18, 0.10, 0.05))
	book.lore_title = "Manual do Laboratório de Combate"
	_make_interactable("TestChest", "CHEST", "Baú de Recursos", Vector3(-1, 0.6, 20), Vector3(1.1, 1.0, 1.0), Color(0.44, 0.28, 0.12), "Fragmento Rúnico")

	_make_wildlife("Alvo Curto 8m", Vector3(23, 0.8, 16), Color(0.58, 0.45, 0.24), true, 90, "FRACO", "DUMMY")
	_make_wildlife("Alvo Médio 16m", Vector3(35, 0.8, 16), Color(0.58, 0.45, 0.24), true, 140, "MEDIO", "DUMMY")
	_make_wildlife("Alvo Longo 24m", Vector3(49, 0.8, 16), Color(0.58, 0.45, 0.24), true, 190, "FORTE", "DUMMY")

	var rng := RandomNumberGenerator.new()
	rng.seed = 12425
	for predator_index in range(7):
		var px := rng.randf_range(-48.0, -24.0)
		var pz := rng.randf_range(-38.0, -22.0)
		var tier := "FRACO" if predator_index < 3 else ("MEDIO" if predator_index < 6 else "FORTE")
		_make_wildlife("Predador Teste %02d" % [predator_index + 1], Vector3(px, 0.8, pz), Color(0.42, 0.12 + 0.02 * predator_index, 0.16), true, 82 + predator_index * 5, tier)

	_make_wildlife("Cortassom Passivo A", Vector3(-44, 0.6, -24), Color(0.60, 0.78, 0.42), false, 55, "FRACO")
	_make_wildlife("Cortassom Passivo B", Vector3(-27, 0.6, -35), Color(0.56, 0.72, 0.38), false, 55, "FRACO")

	_make_wildlife("Atirador de Teste A", Vector3(28, 0.8, -27), Color(0.25, 0.26, 0.31), true, 100, "MEDIO", "RANGED", 14, 10.0, false)
	_make_wildlife("Atirador de Teste B", Vector3(39, 0.8, -32), Color(0.22, 0.24, 0.30), true, 120, "FORTE", "RANGED", 20, 11.5, false)
	_make_wildlife("Atirador de Teste C", Vector3(31, 0.8, -37), Color(0.28, 0.23, 0.25), true, 95, "MEDIO", "RANGED", 12, 9.0, false)
	_make_wildlife("Sentinela One-Shot", Vector3(49, 0.8, -40), Color(0.48, 0.06, 0.06), true, 125, "FORTE", "RANGED", 999, 13.0, true)

	_make_wildlife("Velúrio Alfa Final", Vector3(0, 0.9, -42), Color(0.24, 0.035, 0.06), true, 135, "ALFA")

	for pos in [Vector3(-14,1,8), Vector3(14,1,8), Vector3(-18,1,-4), Vector3(18,1,-4)]:
		_make_tree(pos)
	for pos in [Vector3(-9,0.45,23), Vector3(10,0.45,23), Vector3(-17,0.45,-18), Vector3(17,0.45,-18)]:
		_make_rock(pos)

	var entrance = _make_interactable("DungeonEntrance", "DUNGEON_ENTER", "Entrada da Masmorra de Vigília", Vector3(0, 0.7, -51), Vector3(4.0, 1.4, 1.0), Color(0.11, 0.12, 0.15))
	entrance.target_position = Vector3(0, 0.9, 70)

func _build_dungeon() -> void:
	_make_box("DungeonFloor", Vector3(0, -0.25, 78), Vector3(24, 0.5, 30), Color(0.10, 0.105, 0.12), true)
	_make_box("DungeonNorth", Vector3(0, 1.5, 93), Vector3(24, 3, 0.6), Color(0.12, 0.12, 0.13), true)
	_make_box("DungeonWest", Vector3(-12, 1.5, 78), Vector3(0.6, 3, 30), Color(0.12, 0.12, 0.13), true)
	_make_box("DungeonEast", Vector3(12, 1.5, 78), Vector3(0.6, 3, 30), Color(0.12, 0.12, 0.13), true)
	# Parede dividida em dois segmentos para que a Porta Antiga abra uma passagem real.
	_make_box("DungeonDividerA1", Vector3(-5, 1.5, 70.5), Vector3(0.6, 3, 7.0), Color(0.14, 0.14, 0.15), true)
	_make_box("DungeonDividerA2", Vector3(-5, 1.5, 84.5), Vector3(0.6, 3, 17.0), Color(0.14, 0.14, 0.15), true)
	_make_box("DungeonDividerB", Vector3(5, 1.5, 84), Vector3(0.6, 3, 12), Color(0.14, 0.14, 0.15), true)

	var exit = _make_interactable("DungeonExit", "DUNGEON_EXIT", "Saída da Masmorra", Vector3(0, 0.7, 67), Vector3(3.0, 1.4, 0.7), Color(0.22, 0.25, 0.30))
	exit.target_position = Vector3(0, 0.9, -22)

	_make_interactable("DungeonDoor", "DOOR", "Porta Antiga", Vector3(-5, 1.0, 75), Vector3(0.25, 2.0, 2.4), Color(0.25, 0.16, 0.09))
	_make_interactable("DungeonTrapdoor", "DOOR", "Alçapão Antigo", Vector3(7, 0.18, 88), Vector3(2.0, 0.35, 2.0), Color(0.20, 0.12, 0.06))
	var dungeon_book = _make_interactable("DungeonBook", "BOOK", "Códice Envelhecido", Vector3(-8, 0.55, 86), Vector3(0.9, 0.18, 0.65), Color(0.18, 0.08, 0.05))
	dungeon_book.lore_title = "Notas da Masmorra de Vigília"
	_make_interactable("DungeonChest", "CHEST", "Baú Rúnico", Vector3(8, 0.65, 89), Vector3(1.4, 1.3, 1.0), Color(0.32, 0.18, 0.07), "Cristal Rúnico")
	_make_interactable("DungeonLever", "LEVER", "Alavanca de Ferro", Vector3(9.5, 0.7, 80), Vector3(0.35, 1.4, 0.35), Color(0.34, 0.35, 0.38))

	_make_interactable("OldSword", "WEAPON_PICKUP", "Espada do Vigia Caído", Vector3(-8, 0.18, 74), Vector3(0.18, 0.18, 1.5), Color(0.55, 0.58, 0.62), "Espada do Vigia Caído")
	_make_interactable("OldBow", "WEAPON_PICKUP", "Arco de Galho Negro", Vector3(-8, 0.18, 78), Vector3(0.18, 0.18, 1.6), Color(0.29, 0.16, 0.08), "Arco de Galho Negro")
	_make_interactable("OldCrossbow", "WEAPON_PICKUP", "Besta de Ferrolho Antiga", Vector3(8, 0.18, 74), Vector3(0.35, 0.18, 1.3), Color(0.33, 0.24, 0.16), "Besta de Ferrolho Antiga")
	_make_interactable("OldWhip", "WEAPON_PICKUP", "Chicote de Corrente Velária", Vector3(8, 0.18, 78), Vector3(0.15, 0.15, 1.7), Color(0.31, 0.31, 0.34), "Chicote de Corrente Velária")

	_make_wildlife("Velúrio Corrompido", Vector3(0, 0.8, 86), Color(0.30, 0.04, 0.08), true, 120, "FORTE")
	_make_wildlife("Velúrio Corrompido Leste", Vector3(7, 0.8, 82), Color(0.26, 0.03, 0.07), true, 105, "MEDIO")
	_make_wildlife("Velúrio Corrompido Oeste", Vector3(-8, 0.8, 89), Color(0.34, 0.05, 0.09), true, 110, "FORTE")

func _process(_delta: float) -> void:
	if not _bootstrap_visual_ready:
		return
	if not is_instance_valid(player):
		return
	if not is_instance_valid(sun) or environment_resource == null:
		return
	var dungeon_now: bool = player.global_position.z > 50.0
	if dungeon_now != _last_dungeon_state:
		_last_dungeon_state = dungeon_now
		player.in_dungeon = dungeon_now
	if dungeon_now:
		sun.light_energy = 0.05
		environment_resource.ambient_light_energy = 0.10
		environment_resource.background_color = Color(0.025, 0.03, 0.045)
	else:
		sun.light_energy = 1.15
		environment_resource.ambient_light_energy = 0.75
		environment_resource.background_color = Color(0.34, 0.49, 0.62)

func _on_prototype_command(command: String, params: Dictionary) -> void:
	if not is_instance_valid(living_client):
		return
	match command:
		"MOVE_VECTOR":
			living_client.build_move_vector(Vector2(float(params.get("dx", 0.0)), float(params.get("dy", 0.0))), float(params.get("duration_s", 0.5)), str(params.get("mode", "WALK")))
		"INTERACT":
			living_client.build_interaction(str(params.get("object_id", "")), str(params.get("action", "USE")), float(params.get("distance_m", 2.5)))
		"MOVE_CLICK":
			# O protótipo continua enviando MOVE_VECTOR durante a caminhada.
			# MOVE_CLICK registra a intenção visual sem inventar autoridade de destino no Living.
			pass
		"ATTACK":
			living_client.build_interaction(str(params.get("target", "")), "ATTACK", 2.8)
		_:
			pass

func _make_box(label: String, pos: Vector3, size: Vector3, color: Color, collision_enabled: bool) -> Node3D:
	var parent_node: Node3D
	if collision_enabled:
		var body := StaticBody3D.new()
		parent_node = body
		var collision := CollisionShape3D.new()
		var shape := BoxShape3D.new()
		shape.size = size
		collision.shape = shape
		body.add_child(collision)
	else:
		parent_node = Node3D.new()
	parent_node.name = label
	parent_node.position = pos
	if label in ["Ground", "Bridge", "DungeonFloor"]:
		parent_node.add_to_group("walkable_surface")
	elif collision_enabled:
		parent_node.add_to_group("navigation_obstacle")
		parent_node.set_meta("nav_size", size)
	if label == "TreeTrunk":
		parent_node.add_to_group("hoverable")
		parent_node.set_meta("hover_name", "Árvore")
		parent_node.set_meta("hover_detail", "Flora • Obstáculo natural")
	elif label == "Rock":
		parent_node.add_to_group("hoverable")
		parent_node.set_meta("hover_name", "Rocha")
		parent_node.set_meta("hover_detail", "Recurso mineral • Obstáculo natural")
	var visual := MeshInstance3D.new()
	var mesh := BoxMesh.new()
	mesh.size = size
	visual.mesh = mesh
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = 0.82
	visual.material_override = material
	parent_node.add_child(visual)
	add_child(parent_node)
	return parent_node

func _make_zone_pad(node_name: String, pos: Vector3, size: Vector3, color: Color, label_text: String) -> void:
	_make_box(node_name, pos, size, color, false)
	var label := Label3D.new()
	label.name = node_name + "_Label"
	label.text = label_text
	label.position = pos + Vector3(0.0, 0.35, -size.z * 0.42)
	label.font_size = 48
	label.pixel_size = 0.006
	label.modulate = Color(0.95, 0.95, 0.92)
	label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	add_child(label)

func _make_tree(pos: Vector3) -> void:
	var trunk := _make_box("TreeTrunk", pos, Vector3(0.65, 2.0, 0.65), Color(0.25, 0.14, 0.07), true)
	var crown := MeshInstance3D.new()
	var sphere := SphereMesh.new()
	sphere.radius = 1.55
	sphere.height = 3.1
	crown.mesh = sphere
	crown.position = Vector3(0, 1.8, 0)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.13, 0.37, 0.16)
	crown.material_override = mat
	trunk.add_child(crown)

func _make_rock(pos: Vector3) -> void:
	_make_box("Rock", pos, Vector3(1.1, 0.8, 1.0), Color(0.32, 0.34, 0.35), true)

func _make_interactable(node_name: String, kind: String, label: String, pos: Vector3, size: Vector3, color: Color, item: String = "", p_price: int = 0) -> AndromedaInteractable:
	var obj: AndromedaInteractable = InteractableScript.new()
	obj.name = node_name
	obj.position = pos
	add_child(obj)
	obj.setup(kind, label, size, color, item, p_price)
	return obj

func find_navigation_path(start: Vector3, destination: Vector3, stop_distance: float = 0.0, target: Node3D = null) -> Array[Vector3]:
	var grid := _get_navigation_grid()
	var start_id := _world_to_nav_id(start)
	if not _nav_id_valid(start_id) or grid.is_point_solid(start_id):
		start_id = _nearest_open_id(grid, start_id, 4)
	if not _nav_id_valid(start_id):
		return []

	var candidates: Array[Vector3] = []
	if stop_distance <= 0.05:
		candidates.append(destination)
	else:
		var radius := maxf(0.85, stop_distance)
		# V0.1.8: alvos de fauna usam uma amostragem de aproximação mais leve.
		# A V0.1.7 testava 72 destinos A* por repath; 24 candidatos bem distribuídos
		# são suficientes neste protótipo e reduzem muito picos de CPU. Objetos
		# estáticos mantêm a busca mais densa para preservar a qualidade existente.
		var wildlife_target := target != null and target.is_in_group("wildlife")
		var approach_samples := 12 if wildlife_target else 24
		# V0.1.10: não usar expressão condicional para inicializar Array[float].
		# No Godot 4.7.1, o resultado do ternário é um Array genérico e gera
		# erro em runtime ao ser atribuído diretamente a Array[float].
		var ring_scales: Array[float] = []
		if wildlife_target:
			ring_scales.append(1.0)
			ring_scales.append(1.10)
		else:
			ring_scales.append(1.0)
			ring_scales.append(0.88)
			ring_scales.append(1.12)
		var start_angle := atan2(start.z - destination.z, start.x - destination.x)
		for ring_scale in ring_scales:
			for i in range(approach_samples):
				var angle := start_angle + TAU * float(i) / float(approach_samples)
				var ring_radius := radius * float(ring_scale)
				candidates.append(destination + Vector3(cos(angle) * ring_radius, 0.0, sin(angle) * ring_radius))

	var best_ids: Array[Vector2i] = []
	var best_goal := destination
	var best_cost: float = INF
	for candidate in candidates:
		var goal_id := _world_to_nav_id(candidate)
		if not _nav_id_valid(goal_id) or grid.is_point_solid(goal_id):
			continue
		var ids: Array[Vector2i] = grid.get_id_path(start_id, goal_id, false)
		if ids.is_empty():
			continue
		# Custo em metros, não apenas quantidade de células. Em empates favorece
		# o ponto de aproximação mais perto do jogador e do alvo real.
		var cost := 0.0
		var previous := start
		for nav_id in ids:
			var nav_point := _nav_id_to_world(nav_id, start.y)
			cost += Vector2(previous.x, previous.z).distance_to(Vector2(nav_point.x, nav_point.z))
			previous = nav_point
		cost += Vector2(candidate.x, candidate.z).distance_to(Vector2(destination.x, destination.z)) * 0.05
		if target != null and target.is_in_group("wildlife"):
			# Evita terminar atrás de um obstáculo sem linha local até a criatura.
			if not _navigation_segment_clear(candidate, destination):
				cost += 25.0
		if cost < best_cost:
			best_cost = cost
			best_ids = ids
			best_goal = candidate

	if best_ids.is_empty():
		return []

	var result: Array[Vector3] = []
	for i in range(1, best_ids.size()):
		result.append(_nav_id_to_world(best_ids[i], start.y))
	if result.is_empty() or result[result.size() - 1].distance_to(best_goal) > 0.35:
		result.append(Vector3(best_goal.x, start.y, best_goal.z))
	return _simplify_navigation_path(result, start)

func invalidate_navigation_cache() -> void:
	_navigation_grid_dirty = true

func _warm_navigation_cache() -> void:
	_get_navigation_grid()

func _get_navigation_grid() -> AStarGrid2D:
	if _navigation_grid_cache == null or _navigation_grid_dirty:
		_navigation_grid_cache = _build_navigation_grid()
		_navigation_grid_dirty = false
		_navigation_grid_builds += 1
	return _navigation_grid_cache

func get_navigation_cache_build_count() -> int:
	return _navigation_grid_builds

func _build_navigation_grid() -> AStarGrid2D:
	var width := int(floor((NAV_MAX_X - NAV_MIN_X) / NAV_CELL_SIZE)) + 1
	var height := int(floor((NAV_MAX_Z - NAV_MIN_Z) / NAV_CELL_SIZE)) + 1
	var grid := AStarGrid2D.new()
	grid.region = Rect2i(0, 0, width, height)
	grid.cell_size = Vector2(NAV_CELL_SIZE, NAV_CELL_SIZE)
	grid.diagonal_mode = AStarGrid2D.DIAGONAL_MODE_ONLY_IF_NO_OBSTACLES
	grid.update()
	for x in range(width):
		for z in range(height):
			var id := Vector2i(x, z)
			var point := _nav_id_to_world(id, 0.0)
			if _navigation_point_blocked(point):
				grid.set_point_solid(id, true)
	return grid

func _navigation_point_blocked(point: Vector3) -> bool:
	# Superfície e dungeon são ilhas navegáveis separadas.
	if point.z > 30.0 and point.z < 63.0:
		return true
	if point.z >= 63.0 and absf(point.x) > 11.15:
		return true
	# Rio: somente a faixa fisicamente segura da ponte é atravessável.
	# A largura considera o raio da cápsula do jogador, evitando bloquear
	# células que ainda pertencem visualmente à ponte.
	if is_water_point(point):
		return true

	for entry in get_tree().get_nodes_in_group("navigation_obstacle"):
		if not (entry is Node3D) or not is_instance_valid(entry):
			continue
		var obstacle := entry as Node3D
		if obstacle.has_method("is_navigation_blocking") and not bool(obstacle.call("is_navigation_blocking")):
			continue
		var size_variant: Variant = obstacle.get_meta("nav_size", Vector3.ZERO)
		if not (size_variant is Vector3):
			continue
		var size: Vector3 = size_variant
		if size == Vector3.ZERO:
			continue
		var center := obstacle.global_position
		if absf(point.x - center.x) <= size.x * 0.5 + NAV_PADDING and absf(point.z - center.z) <= size.z * 0.5 + NAV_PADDING:
			return true
	return false

func is_water_point(point: Vector3) -> bool:
	return point.z >= RIVER_Z_MIN and point.z <= RIVER_Z_MAX and absf(point.x) > BRIDGE_NAV_HALF_WIDTH

func _world_to_nav_id(point: Vector3) -> Vector2i:
	return Vector2i(
		int(round((point.x - NAV_MIN_X) / NAV_CELL_SIZE)),
		int(round((point.z - NAV_MIN_Z) / NAV_CELL_SIZE))
	)

func _nav_id_to_world(id: Vector2i, y_value: float) -> Vector3:
	return Vector3(NAV_MIN_X + float(id.x) * NAV_CELL_SIZE, y_value, NAV_MIN_Z + float(id.y) * NAV_CELL_SIZE)

func _nav_id_valid(id: Vector2i) -> bool:
	var width := int(floor((NAV_MAX_X - NAV_MIN_X) / NAV_CELL_SIZE)) + 1
	var height := int(floor((NAV_MAX_Z - NAV_MIN_Z) / NAV_CELL_SIZE)) + 1
	return id.x >= 0 and id.y >= 0 and id.x < width and id.y < height

func _nearest_open_id(grid: AStarGrid2D, center: Vector2i, max_radius: int) -> Vector2i:
	for radius in range(max_radius + 1):
		for x in range(center.x - radius, center.x + radius + 1):
			for y in range(center.y - radius, center.y + radius + 1):
				var id := Vector2i(x, y)
				if _nav_id_valid(id) and not grid.is_point_solid(id):
					return id
	return Vector2i(-9999, -9999)

func _simplify_navigation_path(points: Array[Vector3], start: Vector3) -> Array[Vector3]:
	if points.size() <= 2:
		return points
	var simplified: Array[Vector3] = []
	var anchor := start
	var index := 0
	while index < points.size():
		var furthest := index
		for candidate in range(index, points.size()):
			if _navigation_segment_clear(anchor, points[candidate]):
				furthest = candidate
			else:
				break
		simplified.append(points[furthest])
		anchor = points[furthest]
		index = furthest + 1
	return simplified

func _navigation_segment_clear(from_point: Vector3, to_point: Vector3) -> bool:
	var distance := Vector2(from_point.x, from_point.z).distance_to(Vector2(to_point.x, to_point.z))
	var samples := maxi(1, int(ceil(distance / 0.35)))
	for i in range(1, samples + 1):
		var t := float(i) / float(samples)
		var point := from_point.lerp(to_point, t)
		if _navigation_point_blocked(point):
			return false
	return true

func _make_wildlife(label: String, pos: Vector3, color: Color, hostile: bool, hp: int, tier: String = "FRACO", combat_style: String = "MELEE", ranged_damage: int = -1, ranged_range: float = 9.0, one_shot: bool = false) -> void:
	var animal: AndromedaWildlife = WildlifeScript.new()
	animal.position = pos
	add_child(animal)
	animal.setup(label, color, hostile, hp, tier, combat_style, ranged_damage, ranged_range, one_shot)
