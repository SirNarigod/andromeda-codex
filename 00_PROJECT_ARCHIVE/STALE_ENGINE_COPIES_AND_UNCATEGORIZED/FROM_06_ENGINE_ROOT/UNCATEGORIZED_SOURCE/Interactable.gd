extends StaticBody3D
class_name AndromedaInteractable

var interaction_kind: String = "GENERIC"
var display_name: String = "Objeto"
var item_name: String = ""
var price: int = 0
var target_position: Vector3 = Vector3.ZERO
var lore_title: String = ""
var used: bool = false
var is_open: bool = false
var _collision: CollisionShape3D
var _mesh: MeshInstance3D
var _nav_size: Vector3 = Vector3.ONE
var _interaction_area: Area3D

func setup(kind: String, label: String, size: Vector3, color: Color, p_item: String = "", p_price: int = 0) -> void:
	collision_layer = 1
	collision_mask = 1
	interaction_kind = kind
	display_name = label
	item_name = p_item
	price = p_price
	_nav_size = size
	add_to_group("interactable")
	add_to_group("navigation_obstacle")
	set_meta("nav_size", size)

	_mesh = MeshInstance3D.new()
	var box := BoxMesh.new()
	box.size = size
	_mesh.mesh = box
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = 0.7
	if kind == "TORCH":
		material.emission_enabled = true
		material.emission = Color(1.0, 0.34, 0.06)
		material.emission_energy_multiplier = 1.6
	_mesh.material_override = material
	add_child(_mesh)

	if kind == "TORCH":
		var torch_glow := OmniLight3D.new()
		torch_glow.name = "TorchGlow"
		torch_glow.light_color = Color(1.0, 0.55, 0.22)
		torch_glow.light_energy = 1.4
		torch_glow.omni_range = 4.5
		torch_glow.position = Vector3(0.0, maxf(0.35, size.y * 0.35), 0.0)
		add_child(torch_glow)

	_collision = CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = size
	_collision.shape = shape
	add_child(_collision)

	# Hitbox separada para o clique direito. Ela continua ativa quando uma porta
	# abre e sua colisão física é desabilitada, permitindo fechá-la no segundo clique.
	_interaction_area = Area3D.new()
	_interaction_area.name = "InteractionHitbox"
	_interaction_area.add_to_group("interaction_hitbox")
	_interaction_area.collision_layer = 2
	_interaction_area.collision_mask = 0
	var hitbox_collision := CollisionShape3D.new()
	var hitbox_shape := BoxShape3D.new()
	hitbox_shape.size = size + Vector3(0.18, 0.18, 0.18)
	hitbox_collision.shape = hitbox_shape
	_interaction_area.add_child(hitbox_collision)
	add_child(_interaction_area)

func get_display_name() -> String:
	return display_name

func get_hover_info() -> Dictionary:
	var type_text := "Objeto"
	var detail := "Interação disponível"
	match interaction_kind:
		"NPC":
			type_text = "NPC"
			detail = "Vigiante local • Clique direito para conversar"
		"SHOP":
			type_text = "Loja"
			detail = "Catálogo %s • E/Direito para abrir" % item_name
		"SHOP_NPC":
			type_text = "NPC comerciante"
			detail = "Catálogo %s • E/Direito para abrir" % item_name
		"DOOR":
			type_text = "Porta"
			detail = ("Aberta" if is_open else "Fechada") + " • Clique direito para alternar"
		"CHAIR":
			type_text = "Objeto"
			detail = "Assento • Clique direito para sentar/levantar"
		"BOOK":
			type_text = "Livro"
			detail = "Registro legível"
		"TORCH":
			type_text = "Equipamento"
			detail = "Fonte de luz" if not used else "Já coletada"
		"DUNGEON_ENTER":
			type_text = "Local"
			detail = "Entrada de masmorra"
		"DUNGEON_EXIT":
			type_text = "Local"
			detail = "Saída da masmorra"
		"WEAPON_PICKUP":
			type_text = "Arma"
			detail = "Equipamento antigo" if not used else "Já coletada"
		"CHEST":
			type_text = "Baú"
			detail = "Aberto" if used else "Pode conter recursos"
		"LEVER":
			type_text = "Mecanismo"
			detail = "Ativada" if used else "Desativada"
		_:
			pass
	return {"title": display_name, "detail": "%s • %s" % [type_text, detail]}

func _set_interaction_enabled(enabled: bool) -> void:
	if not is_instance_valid(_interaction_area):
		return
	for child in _interaction_area.get_children():
		if child is CollisionShape3D:
			var hitbox_shape: CollisionShape3D = child as CollisionShape3D
			hitbox_shape.set_deferred("disabled", not enabled)

func is_navigation_blocking() -> bool:
	if interaction_kind == "DOOR" and is_open:
		return false
	if interaction_kind in ["BOOK", "TORCH", "WEAPON_PICKUP", "LEVER"]:
		return false
	return maxf(_nav_size.x, _nav_size.z) >= 0.7

func _player_message(player: Node, text: String) -> void:
	if is_instance_valid(player) and player.has_method("show_message"):
		player.call("show_message", text)

func interact(player: Node) -> void:
	if not is_instance_valid(player):
		return
	match interaction_kind:
		"DOOR":
			is_open = not is_open
			if is_instance_valid(_collision):
				_collision.set_deferred("disabled", is_open)
			if is_instance_valid(_mesh):
				var rot := _mesh.rotation_degrees
				rot.y = 90.0 if is_open else 0.0
				_mesh.rotation_degrees = rot
			var world_root := get_parent()
			if world_root != null and world_root.has_method("invalidate_navigation_cache"):
				world_root.call("invalidate_navigation_cache")
			_player_message(player, "%s %s." % [display_name, "aberta" if is_open else "fechada"])
		"CHAIR":
			if player.has_method("toggle_seat_at"):
				player.call("toggle_seat_at", self, global_position + Vector3(0, 0.9, 0.9))
			elif player.has_method("sit_at"):
				player.call("sit_at", global_position + Vector3(0, 0.9, 0.9))
		"BOOK":
			if player.has_method("add_lore"):
				player.call("add_lore", lore_title if not lore_title.is_empty() else display_name)
		"TORCH":
			if not used:
				used = true
				if player.has_method("add_item"):
					player.call("add_item", item_name if not item_name.is_empty() else display_name)
				visible = false
				if is_instance_valid(_collision):
					_collision.set_deferred("disabled", true)
				_set_interaction_enabled(false)
				if player.has_method("ensure_torch_on"):
					player.call("ensure_torch_on")
			else:
				_player_message(player, "A tocha já foi coletada.")
		"SHOP":
			if player.has_method("open_shop"):
				player.call("open_shop", item_name, display_name)
		"SHOP_NPC":
			_player_message(player, "%s abriu o catálogo. Selecione um item e confirme em COMPRAR." % display_name)
			if player.has_method("open_shop"):
				player.call("open_shop", item_name, display_name)
		"DUNGEON_ENTER":
			if player.has_method("teleport_to"):
				player.call("teleport_to", target_position, true)
		"DUNGEON_EXIT":
			if player.has_method("teleport_to"):
				player.call("teleport_to", target_position, false)
		"WEAPON_PICKUP":
			if not used:
				used = true
				if player.has_method("equip_weapon"):
					player.call("equip_weapon", item_name if not item_name.is_empty() else display_name)
				visible = false
				if is_instance_valid(_collision):
					_collision.set_deferred("disabled", true)
				_set_interaction_enabled(false)
			else:
				_player_message(player, "O item já foi coletado.")
		"CHEST":
			if not used:
				used = true
				var current_coins: int = int(player.get("coins"))
				player.set("coins", current_coins + 20)
				if player.has_method("add_item"):
					player.call("add_item", item_name if not item_name.is_empty() else "Fragmento Rúnico")
				_player_message(player, "Baú aberto: +20 moedas e recurso encontrado.")
			else:
				_player_message(player, "O baú está vazio.")
		"NPC":
			_player_message(player, "%s: 'As rotas de Varga estão tranquilas hoje.'" % display_name)
		"LEVER":
			used = not used
			_player_message(player, "%s %s." % [display_name, "ativada" if used else "desativada"])
		_:
			_player_message(player, "Você interagiu com %s." % display_name)
