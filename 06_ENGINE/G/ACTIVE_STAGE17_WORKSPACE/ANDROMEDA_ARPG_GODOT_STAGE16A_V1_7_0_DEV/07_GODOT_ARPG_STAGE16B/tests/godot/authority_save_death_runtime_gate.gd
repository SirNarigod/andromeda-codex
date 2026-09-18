extends Node

const SESSION_REF := "GODOT-AUTHORITY-SAVE-DEATH-V080"
const SAVE_SLOT := "godotb10"
const WAIT_TIMEOUT_S := 90.0

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _checks: int = 0
var _failures: Array[String] = []
var _bind_results: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []
var _results: Array[Dictionary] = []
var _rejections: Array[String] = []
var _save_projections: Array[Dictionary] = []
var _restore_projections: Array[Dictionary] = []
var _death_projections: Array[Dictionary] = []
var _respawn_projections: Array[Dictionary] = []
var _bag_snapshots: Array[Dictionary] = []


func _ready() -> void:
	await _run_gate()


func _run_gate() -> void:
	# Isolated, fabricated-data proof of the DROP_NOT_ACTIVE correlation
	# helper -- deliberately run before any bridge/session interaction so it
	# cannot contaminate the real flow below.
	_prove_drop_not_active_scoping()

	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_check("SESSION_AUTOLOAD", session != null)
	_check("BRIDGE_AUTOLOAD", bridge != null)
	_check(
		"MAIN_B10_CLIENTS",
		main != null
		and main.save_reload_client != null
		and main.death_respawn_client != null
		and main.dropped_bag_client != null
	)
	if session == null or bridge == null or main == null:
		await _finish()
		return

	bridge.authority_session_bound.connect(func(result: Dictionary) -> void:
		_bind_results.append(result.duplicate(true))
	)
	bridge.snapshot_applied.connect(func(snapshot: Dictionary) -> void:
		_snapshots.append(snapshot.duplicate(true))
	)
	bridge.command_result_received.connect(func(result: Dictionary) -> void:
		_results.append(result.duplicate(true))
	)
	bridge.command_rejected.connect(func(reason: String) -> void:
		_rejections.append(reason)
	)
	main.save_reload_client.save_result_projected.connect(func(result: Dictionary) -> void:
		_save_projections.append(result.duplicate(true))
	)
	main.save_reload_client.restore_projected.connect(func(result: Dictionary) -> void:
		_restore_projections.append(result.duplicate(true))
	)
	main.death_respawn_client.death_projected.connect(func(result: Dictionary) -> void:
		_death_projections.append(result.duplicate(true))
	)
	main.death_respawn_client.respawn_projected.connect(func(result: Dictionary) -> void:
		_respawn_projections.append(result.duplicate(true))
	)
	main.dropped_bag_client.dropped_bag_snapshot_projected.connect(func(result: Dictionary) -> void:
		_bag_snapshots.append(result.duplicate(true))
	)

	if session.has_active_session():
		session.revoke_session()
	_check("LOCAL_SESSION_BIND", session.bind_session(SESSION_REF).get("status") == "PASS")
	_check("AUTHORITY_BIND_STARTED", bridge.bind_authoritative_session().get("status") == "PASS")
	if not await _wait_for_size(_bind_results, 1):
		_failures.append("AUTHORITY_BIND_TIMEOUT")
		await _finish()
		return
	if not await _wait_for_size(_snapshots, 1):
		_failures.append("INITIAL_SNAPSHOT_TIMEOUT")
		await _finish()
		return

	var initial: Dictionary = _snapshots.back()
	_progress("INITIAL_SNAPSHOT_APPLIED")
	var enabled: Array = _bind_results[0].get("enabled_commands", [])
	for command: String in [
		"REQUEST_SAVE", "REQUEST_AUTOSAVE", "REQUEST_RELOAD_RESYNC",
		"REPORT_WATER_TRAVERSAL", "REPORT_WATER_EXHAUSTION",
		"REQUEST_BAG_RECOVERY", "REQUEST_RESPAWN",
	]:
		_check("COMMAND_ENABLED_%s" % command, enabled.has(command), JSON.stringify(enabled))
	_check("INITIAL_SERVER_AUTHORITATIVE", initial.get("server_authoritative") == true)
	_check("INITIAL_PRESENTATION_SEQUENCE_INT", typeof(initial.get("presentation_sequence")) == TYPE_INT)
	_check("INITIAL_DEATH_RECOVERY_PRESENT", initial.get("death_recovery") is Dictionary)
	_check("INITIAL_DROPPED_BAGS_PRESENT", initial.get("dropped_bags") is Array)
	_check("INITIAL_SAVE_CLIENT_READY", main.save_reload_client.state() == AndromedaSaveReloadClient.STATE_READY)

	# --- G16B-18/G16B-26 death retention, part 1: acquire ITEM-ARMOR and equip
	# it BEFORE any Bag exists. Proven read-only against the real engine first:
	# once a Bag is equipped, REQUEST_PICKUP routes any newly picked-up item
	# (including ITEM-ARMOR) straight into the Bag's own inventory record, not
	# the player's -- and items.equip() only accepts an instance_ref already in
	# the player's OWN inventory, so it would reject it as not owned. Doing the
	# armor pickup+equip here, before the untouched Bag-equip block just below,
	# avoids that: equip_new_bag() only sweeps un-equipped inventory, so the
	# now-equipped armor is correctly left alone while ITEM-OLD-KEY (already
	# provisioned at boot) and the picked-up common item are swept in exactly
	# as that existing code already does for everything else. ------------------
	var xp_before: float = float(initial.get("death_recovery", {}).get("retention_projection", {}).get("experience", -1.0))
	var common_target_ref: String = ""
	for entry: Variant in initial.get("combat_targets", []):
		if entry is Dictionary and str((entry as Dictionary).get("slot", "")) == "COMMON":
			common_target_ref = str((entry as Dictionary).get("target_ref", ""))
			break
	_check("DEATH_RETENTION_COMMON_TARGET_FOUND", not common_target_ref.is_empty(), JSON.stringify(initial.get("combat_targets", [])))

	var lethal: Dictionary = {}
	if not common_target_ref.is_empty():
		for attempt: int in range(1, 41):
			await get_tree().create_timer(1.05).timeout
			var attack: Dictionary = await _await_command(bridge, "REQUEST_ATTACK", {"target_ref": common_target_ref}, "DR-ATTACK-%d" % attempt)
			if attack.is_empty():
				break
			if attack.get("status") == "PASS" and bool(attack.get("enemy_defeated", false)):
				lethal = attack
				break
	_check("DEATH_RETENTION_ENEMY_DEFEAT_AUTHORITATIVE", lethal.get("status") == "PASS" and bool(lethal.get("enemy_defeated", false)), JSON.stringify(lethal.get("reason", "NO_DEFEAT_REACHED")))

	var lethal_xp: Dictionary = lethal.get("xp", {}) if lethal.get("xp") is Dictionary else {}
	var lethal_target_state: Dictionary = lethal.get("target_state", {}) if lethal.get("target_state") is Dictionary else {}
	_check(
		"DEATH_XP_SOURCE_COMBAT_AUTHORITATIVE",
		lethal_xp.get("status") == "PASS" and is_equal_approx(float(lethal_xp.get("xp_applied", -1.0)), float(lethal_target_state.get("xp_reward", -2.0))),
		JSON.stringify(lethal_xp),
	)
	var xp_after_lethal: float = float(lethal_xp.get("experience", -1.0))
	_check("DEATH_XP_PRESENT_BEFORE_PLAYER_DEATH", xp_after_lethal > xp_before, "before=%f after_lethal=%f" % [xp_before, xp_after_lethal])

	var drops: Array = (lethal.get("enemy_physical_output", {}) as Dictionary).get("drops", []) if lethal.get("enemy_physical_output") is Dictionary else []
	var armor_row: Dictionary = {}
	var common_row: Dictionary = {}
	for row: Variant in drops:
		if not row is Dictionary:
			continue
		if str((row as Dictionary).get("item_ref", "")) == "ITEM-ARMOR":
			armor_row = row
		elif common_row.is_empty():
			common_row = row
	_check("DEATH_ARMOR_ACQUIRED_AUTHORITATIVELY", not armor_row.is_empty(), JSON.stringify(drops))
	_check("DEATH_RETENTION_COMMON_DROP_FOUND", not common_row.is_empty(), JSON.stringify(drops))

	var armor_instance_ref: String = ""
	var chest_before: String = ""
	var common_item_ref: String = str(common_row.get("item_ref", ""))
	var common_quantity_granted: int = int(common_row.get("quantity", 1))
	# G16B-26 BASE_SLOT_LIMIT probe drop -- hoisted for the same reason as
	# armor_drop_ref/common_drop_ref below.
	var base_slot_nine_drop_ref: String = ""
	# Kept for the same DROP_NOT_ACTIVE scoping discipline as armor_drop_ref/
	# common_drop_ref below -- always empty now that the BASE_SLOT_LIMIT probe
	# no longer fills to 8 via real gathering (the development boot baseline
	# is already at capacity), but the scoping loop further below still reads
	# it unconditionally, so it stays declared and harmless.
	var gathering_fill_drop_refs: Array[String] = []
	# Hoisted out of the `if` below (was local there) so the final
	# NO_COMMAND_REJECTIONS scoping block can correlate DROP_NOT_ACTIVE
	# rejections against the exact two drop_refs this flow itself pickup()'d.
	var armor_drop_ref: String = str(armor_row.get("drop_ref", ""))
	var common_drop_ref: String = str(common_row.get("drop_ref", ""))
	if not armor_row.is_empty() and not common_row.is_empty():

		var after_defeat_snapshot: Dictionary = await _fresh_snapshot(bridge)
		var armor_candidate: Dictionary = _drop_position(_entry_by_drop_ref(after_defeat_snapshot, armor_drop_ref))
		var common_candidate: Dictionary = _drop_position(_entry_by_drop_ref(after_defeat_snapshot, common_drop_ref))
		_check("DEATH_RETENTION_ARMOR_SETTLE_POSITION_FOUND", not armor_candidate.is_empty(), armor_drop_ref)
		_check("DEATH_RETENTION_COMMON_SETTLE_POSITION_FOUND", not common_candidate.is_empty(), common_drop_ref)

		if not armor_candidate.is_empty():
			await _await_command(bridge, "CONFIRM_DROP_SETTLED", {
				"target_ref": armor_drop_ref, "settled_position": armor_candidate, "reachable": true,
			}, "DR-ARMOR-SETTLE")
		if not common_candidate.is_empty():
			await _await_command(bridge, "CONFIRM_DROP_SETTLED", {
				"target_ref": common_drop_ref, "settled_position": common_candidate, "reachable": true,
			}, "DR-COMMON-SETTLE")

		var armor_pickup: Dictionary = await _await_command(bridge, "REQUEST_PICKUP", {"target_ref": armor_drop_ref}, "DR-ARMOR-PICKUP")
		_check("DEATH_ARMOR_PICKUP_AUTHORITATIVE", armor_pickup.get("status") == "PASS", JSON.stringify(armor_pickup))
		var common_pickup: Dictionary = await _await_command(bridge, "REQUEST_PICKUP", {"target_ref": common_drop_ref}, "DR-COMMON-PICKUP")
		_check("DEATH_RETENTION_COMMON_PICKUP_AUTHORITATIVE", common_pickup.get("status") == "PASS", JSON.stringify(common_pickup))
		# ground_loot_client independently observes every active drop in the
		# world (it already reads main.ground_loot_client.auto_pickup_enabled()
		# elsewhere in this file) and can keep reacting to either of these two
		# drops with its own settle/pickup attempts for a while after this
		# test's explicit, already-successful pickups above -- each one
		# correctly rejected DROP_NOT_ACTIVE, since the drop is already gone.
		# That is the deliberate, expected result of the two real pickups just
		# above, not an unexpected rejection. Every DROP_NOT_ACTIVE occurrence,
		# however many arrive over the rest of the gate, is filtered out right
		# before the final NO_COMMAND_REJECTIONS check (unmodified) instead of
		# here, since this client can keep observing these two already-handled
		# drops well after this point.

		var after_pickup_snapshot: Dictionary = await _fresh_snapshot(bridge)
		var armor_entry: Dictionary = _inventory_entry(after_pickup_snapshot, "base", "ITEM-ARMOR")
		armor_instance_ref = str(armor_entry.get("instance_ref", ""))
		_check("DEATH_RETENTION_ARMOR_OWNED_BEFORE_EQUIP", not armor_instance_ref.is_empty(), JSON.stringify(armor_entry))

		# DEATH_PROTECTED_CRITICAL_PROJECTED: equipment.protected_critical_refs
		# (andromeda_authority_adapter.py::_inventory_projection()) is derived
		# only from the player's OWN base inventory, not wherever the effective
		# owner currently is -- so this must be observed here, while
		# ITEM-OLD-KEY is still in base (picked up, not yet swept into the Bag
		# by the equip step further below), not after. The per-entry
		# protected_or_critical flag itself (checked again once the item is
		# inside the Bag, in the next block) is not scoped that way.
		var protected_entry_in_base: Dictionary = _inventory_entry(after_pickup_snapshot, "base", "ITEM-OLD-KEY")
		_check(
			"DEATH_PROTECTED_CRITICAL_PROJECTED",
			protected_entry_in_base.get("protected_or_critical") == true
			and "ITEM-OLD-KEY" in (after_pickup_snapshot.get("inventory_projection", {}) as Dictionary).get("equipment", {}).get("protected_critical_refs", []),
			JSON.stringify(protected_entry_in_base),
		)

		if not armor_instance_ref.is_empty():
			var equip_armor: Dictionary = await _await_command(bridge, "REQUEST_EQUIP_ITEM", {
				"request_ref": "DR-ARMOR-EQUIP:UI", "instance_ref": armor_instance_ref, "slot": "CHEST",
			}, "DR-ARMOR-EQUIP")
			_check("DEATH_ARMOR_EQUIPPED_AUTHORITATIVELY", equip_armor.get("status") == "PASS", JSON.stringify(equip_armor))

		var after_equip_snapshot: Dictionary = await _fresh_snapshot(bridge)
		chest_before = str((after_equip_snapshot.get("inventory_projection", {}) as Dictionary).get("equipment", {}).get("slots", {}).get("CHEST", ""))
		_check("DEATH_ARMOR_PRESENT_BEFORE_DEATH", not chest_before.is_empty() and chest_before == armor_instance_ref, "chest=%s armor=%s" % [chest_before, armor_instance_ref])
	_progress("ARMOR_RETENTION_SETUP_DONE", {"armor_instance_ref": armor_instance_ref, "common_item_ref": common_item_ref})

	# --- G16B-26: BASE_SLOT_LIMIT=8 without a Bag, proved end to end with real
	# transport, strictly BEFORE REQUEST_EQUIP_BAG below. Real slot semantics
	# (arpg_water_bag_survival_core.py::can_accept_carried(), 01_RUNTIME/
	# arpg_item_core.py::_inventory_metrics()): used_slots counts, per
	# distinct item_ref, ceil(qty/stack_max) for a stack or 1 per unit for a
	# non-stackable instance -- never "1 slot per unit" in a stack. Reachable
	# real transport for filling distinct slots without inventing anything:
	# REQUEST_GATHER (arpg_vertical_slice_assembly_core.py::gather_to_ground_
	# loot(), delivery_mode="GROUND_LOOT") always spawns its drop at the
	# worker's OWN current position and never consults inventory capacity at
	# gather time (only CONFIRM_DROP_SETTLED + REQUEST_PICKUP does, via the
	# same can_accept_carried() the armor/common pickups above already went
	# through) -- the same settle/pickup pattern used for armor/common above
	# applies unchanged. The player's own current zone always has multiple
	# distinct, immediately-reachable MINING nodes (dev-profile boot already
	# grants the required TOOL and MINING role), discovered here from the
	# real snapshot's gathering_nodes projection -- never hardcoded, since
	# node_ref is derived from the world's own seed and differs per world.
	var capacity_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var inv_projection_before: Dictionary = capacity_snapshot.get("inventory_projection", {})
	var routing_before: Dictionary = inv_projection_before.get("routing", {})
	_check(
		"NO_BAG_EFFECTIVE_OWNER_IS_PLAYER",
		str(routing_before.get("source", "")) == "BASE_INVENTORY"
		and str(routing_before.get("effective_inventory_owner_ref", "")) != "",
		JSON.stringify(routing_before),
	)
	var carry_before: Dictionary = inv_projection_before.get("carry", {})
	var used_slots_before: int = int(carry_before.get("used_slots", -1))
	var base_slot_limit_reported: int = int(inv_projection_before.get("base_inventory", {}).get("slot_limit", -1))
	_check("BASE_SLOT_LIMIT_EXACTLY_EIGHT", base_slot_limit_reported == 8, "reported=%d" % base_slot_limit_reported)
	_progress("BASE_SLOT_COUNT_AT_CAPACITY", {"used_slots_before": used_slots_before})
	# Development-profile boot baseline: CLOTHES (S16B-DEV-CLOTHES-LEGS-001,
	# granted at boot into the base inventory, see andromeda_authority_adapter.py
	# ::_ensure_development_profile_loadout()) now occupies the base inventory's
	# 8th slot before this probe even starts -- the precondition is genuinely
	# AT capacity, not merely below it. Fill-to-8 gathering is therefore no
	# longer necessary or reachable via a real, non-rejected transport route:
	# only the real 9th-slot attempt below still has anything to prove.
	_check(
		"BASE_SLOT_COUNT_AT_CAPACITY",
		used_slots_before == 8,
		"used_slots_before=%d (development boot baseline; re-measure this probe if the boot loadout changes again)" % used_slots_before,
	)

	var mining_nodes: Array[String] = []
	for node: Variant in capacity_snapshot.get("gathering_nodes", []):
		if not node is Dictionary:
			continue
		var n: Dictionary = node
		if str(n.get("activity_type", "")) == "MINING" and str(n.get("state", "")) == "AVAILABLE":
			mining_nodes.append(str(n.get("target_ref", "")))
	mining_nodes.sort()
	var needed_nodes: int = 1  # only the real 9th-slot probe remains reachable
	_check(
		"G16B26_MINING_NODES_SUFFICIENT_FOR_REACHABILITY",
		mining_nodes.size() >= needed_nodes,
		"available=%d needed=%d (this must PASS via real transport, never a fabricated shortfall)" % [mining_nodes.size(), needed_nodes],
	)

	if mining_nodes.size() >= needed_nodes:
		# The real 9th-slot attempt: REQUEST_GATHER itself is authoritative
		# and PASSes (gather never consults capacity -- the resource exists
		# in the world before pickup), then REQUEST_PICKUP is the command
		# that must be REJECTED with BASE_INVENTORY_SLOT_LIMIT_WITHOUT_BAG.
		var ninth_node_ref: String = mining_nodes[0]
		var ninth_gather: Dictionary = await _await_command(bridge, "REQUEST_GATHER", {
			"target_ref": ninth_node_ref, "requested_units": 1,
		}, "BSL-NINTH-GATHER")
		_check("BASE_SLOT_NINE_COMMAND_AUTHORITATIVE", ninth_gather.get("status") == "PASS", JSON.stringify(ninth_gather))
		base_slot_nine_drop_ref = str((ninth_gather.get("physical_output", {}) as Dictionary).get("target_ref", ""))
		var ninth_item_ref: String = str((ninth_gather.get("physical_output", {}) as Dictionary).get("item_ref", ""))
		if not base_slot_nine_drop_ref.is_empty():
			var ninth_snapshot: Dictionary = await _fresh_snapshot(bridge)
			var ninth_candidate: Dictionary = _drop_position(_entry_by_drop_ref(ninth_snapshot, base_slot_nine_drop_ref))
			if not ninth_candidate.is_empty():
				await _await_command(bridge, "CONFIRM_DROP_SETTLED", {
					"target_ref": base_slot_nine_drop_ref, "settled_position": ninth_candidate, "reachable": true,
				}, "BSL-NINTH-SETTLE")
			var ninth_pickup: Dictionary = await _await_command(bridge, "REQUEST_PICKUP", {"target_ref": base_slot_nine_drop_ref}, "BSL-NINTH-PICKUP")
			_check("BASE_SLOT_NINE_REJECTED", ninth_pickup.get("status") == "REJECTED", JSON.stringify(ninth_pickup))
			_check(
				"BASE_SLOT_NINE_REASON_WITHOUT_BAG",
				str(ninth_pickup.get("reason", "")) == "BASE_INVENTORY_SLOT_LIMIT_WITHOUT_BAG",
				JSON.stringify(ninth_pickup),
			)

		var after_ninth_snapshot: Dictionary = await _fresh_snapshot(bridge)
		var inv_projection_after_ninth: Dictionary = after_ninth_snapshot.get("inventory_projection", {})
		var used_slots_after_ninth: int = int(inv_projection_after_ninth.get("carry", {}).get("used_slots", -1))
		_check(
			"BASE_SLOT_NINE_NO_PARTIAL_MUTATION",
			used_slots_after_ninth == 8,
			"used_slots_after_ninth=%d (must still be exactly 8, not 9 and not <8)" % used_slots_after_ninth,
		)
		# base_inventory.stacks is the same list-of-entries shape _inventory_entry() reads.
		var ninth_entry: Dictionary = _inventory_entry(after_ninth_snapshot, "base", ninth_item_ref)
		_check(
			"BASE_SLOT_NINE_NOT_PRESENT_AFTER_REJECTION",
			ninth_entry.is_empty() or int(ninth_entry.get("quantity", 0)) <= 0,
			JSON.stringify(ninth_entry),
		)
		_check(
			"NO_BAG_IMPLICITLY_CREATED",
			str((inv_projection_after_ninth.get("routing", {}) as Dictionary).get("source", "")) == "BASE_INVENTORY",
			JSON.stringify(inv_projection_after_ninth.get("routing", {})),
		)
	_progress("BASE_SLOT_LIMIT_PROBE_DONE", {"used_slots_before": used_slots_before, "base_slot_nine_drop_ref": base_slot_nine_drop_ref})

	# --- G16B-18: locate the real S16B-DEV-CLOTHES-LEGS-001 instance
	# authoritatively (never fabricated -- read from the same base inventory
	# projection every other entry in this file is read from) and equip it to
	# LEGS via the existing, unmodified REQUEST_EQUIP_ITEM command, strictly
	# BEFORE REQUEST_EQUIP_BAG below -- same discipline as the ITEM-ARMOR
	# equip earlier in this file. CLOTHES was granted at boot (development
	# profile bootstrap, andromeda_authority_adapter.py::_ensure_development_
	# profile_loadout()) and already counted toward used_slots_before above;
	# equipping it here does not free that slot (equip() never removes an
	# instance from the base inventory's instance_refs). ----------------------
	var clothes_before_bag_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var clothes_entry: Dictionary = _inventory_entry(clothes_before_bag_snapshot, "base", "S16B-DEV-CLOTHES-LEGS-001")
	var clothes_instance_ref: String = str(clothes_entry.get("instance_ref", ""))
	_check("CLOTHES_INSTANCE_FOUND_AUTHORITATIVELY", not clothes_instance_ref.is_empty(), JSON.stringify(clothes_entry))
	_check("CLOTHES_SINGLE_INSTANCE_PRESENT", int(clothes_entry.get("quantity", 0)) == 1, JSON.stringify(clothes_entry))

	var legs_before_equip: String = _string_or_empty((clothes_before_bag_snapshot.get("inventory_projection", {}) as Dictionary).get("equipment", {}).get("slots", {}).get("LEGS"))
	_check("CLOTHES_LEGS_EMPTY_BEFORE_EQUIP", legs_before_equip.is_empty(), legs_before_equip)

	if not clothes_instance_ref.is_empty():
		var clothes_equip: Dictionary = await _await_command(bridge, "REQUEST_EQUIP_ITEM", {
			"instance_ref": clothes_instance_ref, "slot": "LEGS",
		}, "CLOTHES-EQUIP")
		_check("CLOTHES_EQUIP_COMMAND_AUTHORITATIVE", not clothes_equip.is_empty(), JSON.stringify(clothes_equip))
		_check("CLOTHES_EQUIP_PASS", clothes_equip.get("status") == "PASS", JSON.stringify(clothes_equip))

		var after_clothes_equip_snapshot: Dictionary = await _fresh_snapshot(bridge)
		var legs_after_equip: String = _string_or_empty((after_clothes_equip_snapshot.get("inventory_projection", {}) as Dictionary).get("equipment", {}).get("slots", {}).get("LEGS"))
		_check("CLOTHES_LEGS_SLOT_ACTIVE", legs_after_equip == clothes_instance_ref, "legs=%s expected=%s" % [legs_after_equip, clothes_instance_ref])
		_check("CLOTHES_SAME_INSTANCE_EQUIPPED", legs_after_equip == clothes_instance_ref)

		var clothes_retention_after_equip: Dictionary = (after_clothes_equip_snapshot.get("death_recovery", {}) as Dictionary).get("retention_projection", {})
		_check(
			"CLOTHES_PROJECTED_AS_CLOTHES",
			clothes_instance_ref in (clothes_retention_after_equip.get("equipped_clothes_refs", []) as Array),
			JSON.stringify(clothes_retention_after_equip.get("equipped_clothes_refs", [])),
		)
		_check(
			"CLOTHES_NOT_PROJECTED_AS_ARMOR",
			not (clothes_instance_ref in (clothes_retention_after_equip.get("equipped_armor_refs", []) as Array)),
			JSON.stringify(clothes_retention_after_equip.get("equipped_armor_refs", [])),
		)
	_progress("CLOTHES_EQUIP_DONE", {"clothes_instance_ref": clothes_instance_ref})

	# --- G16B-18/G16B-26 death retention, part 2: ITEM-OLD-KEY (provisioned at
	# boot, base inventory) and the picked-up common item are still un-equipped
	# at this point, so the existing, unmodified Bag-equip logic right below
	# sweeps both of them into the Bag exactly as it already does for anything
	# else -- nothing here changes that behavior, only observes it. -----------
	if main.inventory_client.bag_state() == "NO_BAG":
		var equip_start: int = _results.size()
		var equip_request: Dictionary = main.inventory_client.request_bag_equip("B10-GATE-BAG-CORRELATION")
		_check("REAL_BAG_SETUP_REQUEST", equip_request.get("transport_submitted") == true, JSON.stringify(equip_request))
		var equip_result: Dictionary = await _wait_for_command("REQUEST_EQUIP_BAG", equip_start)
		_check("REAL_BAG_SETUP_AUTHORITY", equip_result.get("status") == "PASS", JSON.stringify(equip_result))
		_check("REAL_BAG_SETUP_SNAPSHOT", await _wait_for_inventory_bag("BAG_EQUIPPED"))
	else:
		_check("REAL_BAG_ALREADY_EQUIPPED", main.inventory_client.bag_state() == "BAG_EQUIPPED")
	_progress("BAG_PRECONDITION_READY")

	var bag_ref_before: String = ""
	var common_quantity_in_bag_before: int = 0
	var bag_precondition_snapshot: Dictionary = await _fresh_snapshot(bridge)
	bag_ref_before = str((bag_precondition_snapshot.get("inventory_projection", {}) as Dictionary).get("bag", {}).get("bag_ref", ""))
	# G16B-26: now that a real Bag is equipped, effective routing must have
	# moved off the player's own base inventory -- the no-Bag policy above
	# was specifically the no-Bag path, not a permanent ceiling.
	var routing_after_bag: Dictionary = (bag_precondition_snapshot.get("inventory_projection", {}) as Dictionary).get("routing", {})
	_check(
		"EQUIPPED_BAG_CHANGES_EFFECTIVE_OWNER",
		str(routing_after_bag.get("source", "")) == "EQUIPPED_BAG"
		and str(routing_after_bag.get("effective_inventory_owner_ref", "")) == bag_ref_before
		and not bag_ref_before.is_empty(),
		JSON.stringify(routing_after_bag),
	)
	# G16B-18: equipping a Bag only sweeps un-equipped inventory (same rule
	# already relied on for ITEM-ARMOR above) -- CLOTHES, already equipped to
	# LEGS, must stay there and must not be swept into the Bag as a loose item.
	if not clothes_instance_ref.is_empty():
		var legs_after_bag_equip: String = _string_or_empty((bag_precondition_snapshot.get("inventory_projection", {}) as Dictionary).get("equipment", {}).get("slots", {}).get("LEGS"))
		_check(
			"CLOTHES_REMAINS_EQUIPPED_AFTER_BAG_EQUIP",
			legs_after_bag_equip == clothes_instance_ref,
			"legs=%s expected=%s" % [legs_after_bag_equip, clothes_instance_ref],
		)
	var protected_entry_in_bag: Dictionary = _inventory_entry(bag_precondition_snapshot, "bag", "ITEM-OLD-KEY")
	_check(
		"DEATH_PROTECTED_CRITICAL_PRESENT_BEFORE_DEATH",
		int(protected_entry_in_bag.get("quantity", 0)) == 1,
		JSON.stringify(protected_entry_in_bag),
	)
	_check(
		"DEATH_RETENTION_PROTECTED_STILL_CLASSIFIED_INSIDE_BAG",
		protected_entry_in_bag.get("protected_or_critical") == true,
		JSON.stringify(protected_entry_in_bag),
	)
	var common_entry_in_bag_before: Dictionary = _inventory_entry(bag_precondition_snapshot, "bag", common_item_ref)
	common_quantity_in_bag_before = int(common_entry_in_bag_before.get("quantity", 0))
	_check(
		"DEATH_COMMON_BAG_CONTENT_PRESERVED",
		not common_item_ref.is_empty() and common_quantity_in_bag_before == common_quantity_granted,
		"item_ref=%s expected=%d actual=%d" % [common_item_ref, common_quantity_granted, common_quantity_in_bag_before],
	)

	var preference_before: bool = main.ground_loot_client.auto_pickup_enabled()
	var first_save: Dictionary = await _request_and_wait_save()
	_progress("FIRST_SAVE_RESULT", {"result": first_save, "projection_count": _save_projections.size()})
	if first_save.is_empty() or _save_projections.is_empty():
		_failures.append("FIRST_SAVE_OBSERVATION_INCOMPLETE")
		await _finish()
		return
	_check("FIRST_SAVE_CONFIRMED", first_save.get("result") == "CONFIRMED", JSON.stringify(first_save))
	_check("FIRST_SAVE_SERVER_AUTHORITATIVE", first_save.get("server_authoritative") == true)
	_check("FIRST_SAVE_REAL_INTEGRITY", first_save.get("snapshot_integrity", {}).get("status") == "PASS")
	_check("FIRST_SAVE_CLIENT_PROJECTED", not _save_projections.is_empty() and _save_projections.back().get("success_confirmed_externally") == true)
	_check("FIRST_SAVE_NO_LOCAL_WRITE", _save_projections.back().get("save_written_locally") == false)

	var desired_changed_preference: bool = not preference_before
	_check("BRIDGE_READY_BEFORE_PREFERENCE", await _wait_for_bridge_ready(bridge))
	var preference_result_start: int = _results.size()
	var preference_snapshot_start: int = _snapshots.size()
	main.hud.inventory_shell.set_auto_pickup_visual(desired_changed_preference, true)
	var preference_result: Dictionary = await _wait_for_command("SET_AUTO_PICKUP", preference_result_start)
	_check("MUTATION_AFTER_SAVE_AUTHORITY_PASS", preference_result.get("status") == "PASS", JSON.stringify(preference_result))
	var preference_projected: bool = await _wait_for_auto_pickup(
		desired_changed_preference, preference_snapshot_start, bridge
	)
	_check("MUTATION_AFTER_SAVE_SNAPSHOT", preference_projected)
	_progress("PREFERENCE_MUTATION_OBSERVED", {
		"expected": desired_changed_preference,
		"actual": main.ground_loot_client.auto_pickup_enabled(),
		"raw_snapshot_preference": _snapshots.back().get("profile_preferences", {}),
	})
	if preference_result.is_empty() or not preference_projected:
		await _finish()
		return

	_check("BRIDGE_READY_BEFORE_FIRST_RELOAD", await _wait_for_bridge_ready(bridge))
	var restore_start: int = _results.size()
	var restore_projection_start: int = _restore_projections.size()
	var reload_intent: Dictionary = main.save_reload_client.request_reload_resync(SAVE_SLOT)
	_progress("FIRST_RELOAD_SUBMITTED", reload_intent)
	_check("FIRST_RELOAD_INTENT_PASS", reload_intent.get("status") == "PASS", JSON.stringify(reload_intent))
	_check("FIRST_RELOAD_TRANSPORT", reload_intent.get("transport_submitted") == true)
	_check("FIRST_RELOAD_BLOCKS_INPUT_PENDING", main.death_respawn_client.world_input_blocked())
	var restored: Dictionary = await _wait_for_command("REQUEST_RELOAD_RESYNC", restore_start)
	_progress("FIRST_RELOAD_RESULT", {"result_received": not restored.is_empty()})
	if restored.is_empty():
		_failures.append("FIRST_RELOAD_RESULT_TIMEOUT")
		await _finish()
		return
	_check("FIRST_RELOAD_AUTHORITY_PASS", restored.get("status") == "PASS", JSON.stringify(restored))
	_check("FIRST_RELOAD_REAL_RESYNC", restored.get("resync_before_ready") == true)
	_check("FIRST_RELOAD_NOT_GODOT_FABRICATED", restored.get("restore_fabricated_by_godot") == false)
	_check("FIRST_RESTORE_CLIENT_PROJECTED", await _wait_for_size(_restore_projections, restore_projection_start + 1))
	_check("FIRST_RESTORE_CLIENT_READY", main.save_reload_client.state() == AndromedaSaveReloadClient.STATE_READY and not main.save_reload_client.needs_resync())
	_check("FIRST_RESTORE_INPUT_RELEASED", not main.death_respawn_client.world_input_blocked())
	_check("FIRST_RESTORE_PREFERENCE_CONTINUITY", main.ground_loot_client.auto_pickup_enabled() == preference_before)
	_check("FIRST_RESTORE_BAG_CONTINUITY", main.inventory_client.bag_state() == "BAG_EQUIPPED")
	_check("FIRST_RESTORE_ECONOMY_PRESENT", not main.save_reload_client.economy_projection().is_empty())
	_check("FIRST_RESTORE_WORLD_PRESENT", not main.save_reload_client.world_projection().is_empty())
	_check("FIRST_RESTORE_NESTED_SEQUENCE_NORMALIZED", _restore_nested_sequences_are_int(restored.get("restore_snapshot", {})))

	# G16B-18: same real save/reload round trip as everything else above --
	# no second save flow. CLOTHES must still be the SAME instance, still
	# equipped to LEGS, still exactly one instance, no re-grant.
	if not clothes_instance_ref.is_empty():
		var post_reload_snapshot: Dictionary = await _fresh_snapshot(bridge)
		var legs_after_reload: String = _string_or_empty((post_reload_snapshot.get("inventory_projection", {}) as Dictionary).get("equipment", {}).get("slots", {}).get("LEGS"))
		_check(
			"CLOTHES_SAVE_RELOAD_PRESERVED",
			legs_after_reload == clothes_instance_ref,
			"legs=%s expected=%s" % [legs_after_reload, clothes_instance_ref],
		)
		_check("CLOTHES_SAVE_RELOAD_SAME_INSTANCE", legs_after_reload == clothes_instance_ref)
		var clothes_retention_after_reload: Dictionary = (post_reload_snapshot.get("death_recovery", {}) as Dictionary).get("retention_projection", {})
		_check(
			"CLOTHES_SAVE_RELOAD_NO_DUPLICATION",
			(clothes_retention_after_reload.get("equipped_clothes_refs", []) as Array).count(clothes_instance_ref) == 1,
			JSON.stringify(clothes_retention_after_reload.get("equipped_clothes_refs", [])),
		)

	_check("BRIDGE_READY_BEFORE_WATER_RESET", await _wait_for_bridge_ready(bridge))
	var reset_start: int = _results.size()
	_check("WATER_EXPOSURE_RESET_SUBMITTED", bridge.submit_command("REPORT_WATER_EXHAUSTION", {
		"request_ref": "B10-GODOT-WATER-RESET",
		"volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"in_water": false,
		"client_presentation_only": true,
	}).get("status") == "PASS")
	var water_reset: Dictionary = await _wait_for_command("REPORT_WATER_EXHAUSTION", reset_start)
	_check("WATER_EXPOSURE_RESET_AUTHORITY_PASS", water_reset.get("status") == "PASS", JSON.stringify(water_reset))
	_check("WATER_EXPOSURE_RESET_RECOVERED", water_reset.get("exhaustion_snapshot", {}).get("state") == "RECOVERED", JSON.stringify(water_reset))
	_check("WATER_EXPOSURE_RESET_NO_CLIENT_TIMER", water_reset.get("client_supplied_elapsed_time") == false)
	_check("BRIDGE_READY_BEFORE_CLEANUP_SAVE", await _wait_for_bridge_ready(bridge))
	var cleanup_save: Dictionary = await _request_and_wait_save()
	_progress("CLEANUP_SAVE_RESULT", {"result": cleanup_save, "projection_count": _save_projections.size()})
	if cleanup_save.is_empty():
		_failures.append("CLEANUP_SAVE_RESULT_TIMEOUT")
		await _finish()
		return
	_check("CLEANUP_SAVE_CONFIRMED", cleanup_save.get("result") == "CONFIRMED", JSON.stringify(cleanup_save))
	_check("CLEANUP_SAVE_SEQUENCE_ADVANCED", int(cleanup_save.get("save_sequence", -1)) > int(first_save.get("save_sequence", -1)))

	_check("BRIDGE_READY_BEFORE_WATER_TRAVERSAL", await _wait_for_bridge_ready(bridge))
	var traversal_start: int = _results.size()
	var traversal_submit: Dictionary = bridge.submit_command("REPORT_WATER_TRAVERSAL", {
		"request_ref": "B10-GODOT-WATER-TRAVERSAL",
		"volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"depth_m": 8.0,
		"flow_speed_mps": 8.0,
		"distance_m": 100.0,
		"under_bridge": false,
		"client_presentation_only": true,
	})
	_check("WATER_TRAVERSAL_SUBMITTED", traversal_submit.get("status") == "PASS", JSON.stringify(traversal_submit))
	var traversal: Dictionary = await _wait_for_command("REPORT_WATER_TRAVERSAL", traversal_start)
	_progress("WATER_TRAVERSAL_RESULT", {"received": not traversal.is_empty()})
	if traversal.is_empty():
		_failures.append("WATER_TRAVERSAL_RESULT_TIMEOUT")
		await _finish()
		return
	_check("WATER_TRAVERSAL_STAGE16A_PASS", traversal.get("status") == "PASS", JSON.stringify(traversal))
	_check("WATER_STAMINA_ZERO_BY_AUTHORITY", is_zero_approx(float(traversal.get("stamina", {}).get("stamina_after", -1.0))))
	_check("WATER_LOAD_READ_BY_STAGE16A", traversal.get("load_read_by_stage16a") == true)
	_check("WATER_NO_GODOT_STAMINA_AUTHORITY", traversal.get("stamina_decided_by_godot") == false)

	# --- G16B-25: ordinary non-water-capable vehicles are blocked from deep water,
	# and never touch the player's own stamina rule (real REPORT_WATER_TRAVERSAL
	# round-trip with actor_kind=VEHICLE; no vehicle node/controller is created --
	# the authoritative report itself is the unit of proof). --------------------
	var stamina_before_vehicle: float = float(traversal.get("stamina", {}).get("stamina_after", -1.0))
	_check("BRIDGE_READY_BEFORE_VEHICLE_DEEP_WATER", await _wait_for_bridge_ready(bridge))
	var vehicle_start: int = _results.size()
	var vehicle_submit: Dictionary = bridge.submit_command("REPORT_WATER_TRAVERSAL", {
		"request_ref": "G25-VEHICLE-DEEP-WATER",
		"volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"depth_m": 1.0,
		"flow_speed_mps": 0.2,
		"distance_m": 1.0,
		"actor_kind": "VEHICLE",
		"client_presentation_only": true,
	})
	_check("VEHICLE_DEEP_WATER_COMMAND_AUTHORITATIVE", vehicle_submit.get("status") == "PASS", JSON.stringify(vehicle_submit))
	var vehicle_result: Dictionary = await _wait_for_command("REPORT_WATER_TRAVERSAL", vehicle_start)
	_check(
		"VEHICLE_DEEP_WATER_BLOCKED",
		vehicle_result.get("status") == "BLOCKED" and vehicle_result.get("reason") == "VEHICLE_WATER_TOO_DEEP",
		JSON.stringify(vehicle_result),
	)
	# This BLOCKED outcome is the deliberate, expected result of this very step,
	# not an unexpected rejection -- the bridge's command_rejected signal fires
	# for any non-PASS status (see andromeda_bridge.gd), so it lands in the same
	# _rejections list the pre-existing NO_COMMAND_REJECTIONS check (further
	# below, unmodified) asserts is empty. Removing exactly the one occurrence
	# this step causes keeps that check meaningful for everything else in the
	# gate: any other, truly unexpected rejection still fails it.
	_rejections.erase("VEHICLE_WATER_TOO_DEEP")
	_check(
		"VEHICLE_WATER_TOO_DEEP_STAGE16B_PASS",
		(
			vehicle_result.get("actor_kind") == "VEHICLE"
			and vehicle_result.get("server_authoritative") == true
			and not vehicle_result.has("profile_ref")
			and not vehicle_result.has("stamina")
		),
		JSON.stringify(vehicle_result),
	)

	_check("BRIDGE_READY_BEFORE_VEHICLE_STAMINA_PROBE", await _wait_for_bridge_ready(bridge))
	var stamina_probe_start: int = _results.size()
	bridge.submit_command("REPORT_WATER_TRAVERSAL", {
		"request_ref": "G25-VEHICLE-STAMINA-PROBE",
		"volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"depth_m": 0.0,
		"flow_speed_mps": 0.0,
		"distance_m": 0.0,
		"client_presentation_only": true,
	})
	var stamina_probe: Dictionary = await _wait_for_command("REPORT_WATER_TRAVERSAL", stamina_probe_start)
	var stamina_after_vehicle: float = float(stamina_probe.get("stamina", {}).get("stamina_after", -2.0))
	_check(
		"VEHICLE_DEEP_WATER_NO_PLAYER_STAMINA_RULE",
		is_equal_approx(stamina_after_vehicle, stamina_before_vehicle),
		"before=%f after=%f" % [stamina_before_vehicle, stamina_after_vehicle],
	)

	# --- G16B-24: shallow rivers traversable, under-bridge shallow traversable,
	# stronger current increases stamina cost, vehicles use traction/speed penalty
	# instead of stamina. Same REPORT_WATER_TRAVERSAL route opened for G16B-25;
	# no new transport, no vehicle node/controller. Each sample is submitted and
	# awaited individually (command_ref-distinct) so none contaminates the next. -
	_check("BRIDGE_READY_BEFORE_SHALLOW_WATER", await _wait_for_bridge_ready(bridge))
	var shallow_start: int = _results.size()
	var shallow_submit: Dictionary = bridge.submit_command("REPORT_WATER_TRAVERSAL", {
		"request_ref": "G24-SHALLOW-A",
		"volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"depth_m": 0.3,
		"flow_speed_mps": 0.2,
		"distance_m": 1.0,
		"client_presentation_only": true,
	})
	_check("SHALLOW_WATER_COMMAND_AUTHORITATIVE", shallow_submit.get("status") == "PASS", JSON.stringify(shallow_submit))
	var shallow_result: Dictionary = await _wait_for_command("REPORT_WATER_TRAVERSAL", shallow_start)
	var shallow_traversal: Dictionary = shallow_result.get("traversal", {})
	_check("SHALLOW_WATER_TRAVERSABLE", shallow_result.get("status") == "PASS", JSON.stringify(shallow_result))
	_check(
		"SHALLOW_WATER_WADE_MODE",
		shallow_traversal.get("mode") == "WADE" and shallow_traversal.get("mode") != "SWIM" and shallow_traversal.get("shallow") == true,
		JSON.stringify(shallow_traversal),
	)

	_check("BRIDGE_READY_BEFORE_UNDER_BRIDGE", await _wait_for_bridge_ready(bridge))
	var under_bridge_start: int = _results.size()
	var under_bridge_submit: Dictionary = bridge.submit_command("REPORT_WATER_TRAVERSAL", {
		"request_ref": "G24-UNDER-BRIDGE-B",
		"volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"depth_m": 0.3,
		"flow_speed_mps": 0.2,
		"distance_m": 1.0,
		"under_bridge": true,
		"client_presentation_only": true,
	})
	_check("UNDER_BRIDGE_SHALLOW_AUTHORITATIVE", under_bridge_submit.get("status") == "PASS", JSON.stringify(under_bridge_submit))
	var under_bridge_result: Dictionary = await _wait_for_command("REPORT_WATER_TRAVERSAL", under_bridge_start)
	var under_bridge_traversal: Dictionary = under_bridge_result.get("traversal", {})
	_check(
		"UNDER_BRIDGE_SHALLOW_TRAVERSABLE",
		under_bridge_result.get("status") == "PASS" and under_bridge_traversal.get("mode") == "WADE" and under_bridge_traversal.get("under_bridge") == true,
		JSON.stringify(under_bridge_result),
	)

	_check("BRIDGE_READY_BEFORE_CURRENT_LOW", await _wait_for_bridge_ready(bridge))
	var current_low_start: int = _results.size()
	bridge.submit_command("REPORT_WATER_TRAVERSAL", {
		"request_ref": "G24-CURRENT-LOW",
		"volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"depth_m": 0.3,
		"flow_speed_mps": 0.2,
		"distance_m": 1.0,
		"client_presentation_only": true,
	})
	var current_low: Dictionary = await _wait_for_command("REPORT_WATER_TRAVERSAL", current_low_start)
	var current_low_traversal: Dictionary = current_low.get("traversal", {})
	_check("WATER_CURRENT_LOW_AUTHORITATIVE", current_low.get("status") == "PASS" and current_low_traversal.get("flow_class") == "CALM", JSON.stringify(current_low))

	_check("BRIDGE_READY_BEFORE_CURRENT_HIGH", await _wait_for_bridge_ready(bridge))
	var current_high_start: int = _results.size()
	bridge.submit_command("REPORT_WATER_TRAVERSAL", {
		"request_ref": "G24-CURRENT-HIGH",
		"volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"depth_m": 0.3,
		"flow_speed_mps": 1.2,
		"distance_m": 1.0,
		"client_presentation_only": true,
	})
	var current_high: Dictionary = await _wait_for_command("REPORT_WATER_TRAVERSAL", current_high_start)
	var current_high_traversal: Dictionary = current_high.get("traversal", {})
	_check("WATER_CURRENT_HIGH_AUTHORITATIVE", current_high.get("status") == "PASS" and current_high_traversal.get("flow_class") == "STRONG_CURRENT", JSON.stringify(current_high))
	_check(
		"STRONGER_CURRENT_INCREASES_STAMINA_COST",
		float(current_high_traversal.get("stamina_cost", -1.0)) > float(current_low_traversal.get("stamina_cost", -1.0)),
		"low=%f high=%f" % [float(current_low_traversal.get("stamina_cost", -1.0)), float(current_high_traversal.get("stamina_cost", -1.0))],
	)

	_check("BRIDGE_READY_BEFORE_VEHICLE_SHALLOW", await _wait_for_bridge_ready(bridge))
	var stamina_before_vehicle_shallow: float = stamina_after_vehicle
	var vehicle_shallow_start: int = _results.size()
	var vehicle_shallow_submit: Dictionary = bridge.submit_command("REPORT_WATER_TRAVERSAL", {
		"request_ref": "G24-VEHICLE-SHALLOW",
		"volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"depth_m": 0.3,
		"flow_speed_mps": 0.2,
		"distance_m": 1.0,
		"actor_kind": "VEHICLE",
		"client_presentation_only": true,
	})
	_check("VEHICLE_SHALLOW_COMMAND_AUTHORITATIVE", vehicle_shallow_submit.get("status") == "PASS", JSON.stringify(vehicle_shallow_submit))
	var vehicle_shallow_result: Dictionary = await _wait_for_command("REPORT_WATER_TRAVERSAL", vehicle_shallow_start)
	_check(
		"VEHICLE_SHALLOW_TRAVERSABLE",
		vehicle_shallow_result.get("status") == "PASS" and vehicle_shallow_result.get("mode") == "WADE_VEHICLE",
		JSON.stringify(vehicle_shallow_result),
	)
	_check("VEHICLE_SHALLOW_SPEED_PENALTY", float(vehicle_shallow_result.get("speed_factor", 1.0)) < 1.0, JSON.stringify(vehicle_shallow_result))
	_check("VEHICLE_SHALLOW_TRACTION_PENALTY", float(vehicle_shallow_result.get("traction_penalty", 0.0)) > 0.0, JSON.stringify(vehicle_shallow_result))

	_check("BRIDGE_READY_BEFORE_VEHICLE_SHALLOW_STAMINA_PROBE", await _wait_for_bridge_ready(bridge))
	var shallow_stamina_probe_start: int = _results.size()
	bridge.submit_command("REPORT_WATER_TRAVERSAL", {
		"request_ref": "G24-VEHICLE-SHALLOW-STAMINA-PROBE",
		"volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"depth_m": 0.0,
		"flow_speed_mps": 0.0,
		"distance_m": 0.0,
		"client_presentation_only": true,
	})
	var shallow_stamina_probe: Dictionary = await _wait_for_command("REPORT_WATER_TRAVERSAL", shallow_stamina_probe_start)
	var stamina_after_vehicle_shallow: float = float(shallow_stamina_probe.get("stamina", {}).get("stamina_after", -2.0))
	_check(
		"VEHICLE_SHALLOW_NO_PLAYER_STAMINA_RULE",
		is_equal_approx(stamina_after_vehicle_shallow, stamina_before_vehicle_shallow),
		"before=%f after=%f" % [stamina_before_vehicle_shallow, stamina_after_vehicle_shallow],
	)

	# G16B-18: capture CLOTHES' state immediately before the same real death
	# sequence (water exhaustion) proven below -- no separate/second death.
	var legs_before_death: String = ""
	if not clothes_instance_ref.is_empty():
		var before_death_snapshot: Dictionary = await _fresh_snapshot(bridge)
		legs_before_death = _string_or_empty((before_death_snapshot.get("inventory_projection", {}) as Dictionary).get("equipment", {}).get("slots", {}).get("LEGS"))
		var clothes_retention_before_death: Dictionary = (before_death_snapshot.get("death_recovery", {}) as Dictionary).get("retention_projection", {})
		_check("DEATH_CLOTHES_PRESENT_BEFORE_DEATH", legs_before_death == clothes_instance_ref, "legs=%s expected=%s" % [legs_before_death, clothes_instance_ref])
		_check(
			"DEATH_CLOTHES_PROJECTED_AS_CLOTHES",
			clothes_instance_ref in (clothes_retention_before_death.get("equipped_clothes_refs", []) as Array),
			JSON.stringify(clothes_retention_before_death.get("equipped_clothes_refs", [])),
		)

	_check("BRIDGE_READY_BEFORE_WATER_GRACE", await _wait_for_bridge_ready(bridge))
	var grace_start: int = _results.size()
	_check("WATER_GRACE_START_SUBMITTED", bridge.submit_command("REPORT_WATER_EXHAUSTION", {
		"request_ref": "B10-GODOT-WATER-GRACE-START",
		"volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"in_water": true,
		"client_presentation_only": true,
	}).get("status") == "PASS")
	var grace: Dictionary = await _wait_for_command("REPORT_WATER_EXHAUSTION", grace_start)
	_progress("WATER_GRACE_RESULT", {"received": not grace.is_empty()})
	if grace.is_empty():
		_failures.append("WATER_GRACE_RESULT_TIMEOUT")
		await _finish()
		return
	_check("WATER_GRACE_AUTHORITY_PASS", grace.get("status") == "PASS", JSON.stringify(grace))
	_check("WATER_GRACE_STARTED_EXTERNALLY", grace.get("exhaustion_snapshot", {}).get("state") == "STAMINA_ZERO_GRACE")
	_check("WATER_CLIENT_PROJECTED_GRACE", main.death_respawn_client.exhaustion_projection().get("state") == "STAMINA_ZERO_GRACE")
	_check("WATER_CLIENT_NO_ELAPSED_AUTHORITY", grace.get("client_supplied_elapsed_time") == false)
	await get_tree().create_timer(4.15).timeout

	_check("BRIDGE_READY_BEFORE_WATER_DEATH", await _wait_for_bridge_ready(bridge))
	var death_result_start: int = _results.size()
	var death_projection_start: int = _death_projections.size()
	_check("WATER_DEATH_CHECK_SUBMITTED", bridge.submit_command("REPORT_WATER_EXHAUSTION", {
		"request_ref": "B10-GODOT-WATER-GRACE-DEFEAT",
		"volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"in_water": true,
		"client_presentation_only": true,
	}).get("status") == "PASS")
	var defeated: Dictionary = await _wait_for_command("REPORT_WATER_EXHAUSTION", death_result_start)
	_progress("WATER_DEATH_RESULT", {"received": not defeated.is_empty()})
	if defeated.is_empty():
		_failures.append("WATER_DEATH_RESULT_TIMEOUT")
		await _finish()
		return
	_check("WATER_DEATH_AUTHORITY_PASS", defeated.get("status") == "PASS", JSON.stringify(defeated))
	_check("WATER_DEFEAT_REQUIRED_EXTERNALLY", defeated.get("defeat_required") == true)
	_check("WATER_DEATH_EVENT_EXTERNAL", defeated.get("death_event", {}).get("state") == "DEAD_AWAITING_RESPAWN")
	_check("WATER_DEATH_CLIENT_PROJECTED", await _wait_for_size(_death_projections, death_projection_start + 1))
	_check("WATER_DEATH_INPUT_BLOCKED", main.death_respawn_client.world_input_blocked())
	_check("WATER_DEATH_CLIENT_STATE", main.death_respawn_client.state() == AndromedaDeathRespawnClient.STATE_DEAD_AWAITING_RESPAWN)
	var bag_drop: Dictionary = defeated.get("death_event", {}).get("bag_drop", {})
	var bag_entries: Array = bag_drop.get("dropped_bag_snapshot", {}).get("dropped_bags", [])
	_check("DEATH_SINGLE_BAG_CONTAINER", bag_drop.get("single_container") == true and bag_entries.size() == 1, JSON.stringify(bag_drop))
	var death_bag_ref: String = str(bag_entries[0].get("bag_ref", "")) if bag_entries.size() == 1 else ""
	var death_bag: AndromedaDroppedBag = main.dropped_bag_client.dropped_bag_for_ref(death_bag_ref)
	_check("DROPPED_BAG_CLIENT_PRESENT", death_bag != null, death_bag_ref)
	if death_bag != null:
		_check("DROPPED_BAG_WATER_FLOATING", death_bag.projected_state() == AndromedaDroppedBag.STATE_DROPPED_WATER_FLOATING)
		_check("DROPPED_BAG_OWNER_PRESERVED", death_bag.original_owner_ref == str(initial.get("identity", {}).get("profile_ref", "")))
	_check("DEATH_RETENTION_TWO_SLOTS", (defeated.get("death_event", {}).get("retention", {}).get("quick_slots", []) as Array).size() == 2)
	_check("DEATH_NO_LOCAL_AUTHORITY", main.death_respawn_client.contract_snapshot().get("death_authority") == false)

	# --- G16B-18/G16B-26 death retention, part 3: verify retention against the
	# SAME real death event above -- no second death, no manual restoration
	# afterward, nothing re-equipped or re-granted here. -----------------------
	var retention: Dictionary = defeated.get("death_event", {}).get("retention", {})
	_check(
		"DEATH_XP_RETAINED",
		retention.get("xp_retained") == true and is_equal_approx(float(retention.get("experience", -1.0)), xp_after_lethal),
		"retained=%f expected=%f" % [float(retention.get("experience", -1.0)), xp_after_lethal],
	)
	_check("DEATH_ARMOR_RETAINED", armor_instance_ref in (retention.get("equipped_armor_refs", []) as Array), JSON.stringify(retention.get("equipped_armor_refs", [])))
	_check("DEATH_PROTECTED_CRITICAL_RETAINED", "ITEM-OLD-KEY" in (retention.get("protected_critical_refs", []) as Array), JSON.stringify(retention.get("protected_critical_refs", [])))
	_check("DEATH_BAG_CONTAINER_IDENTITY_PRESERVED", not bag_ref_before.is_empty() and death_bag_ref == bag_ref_before, "before=%s after=%s" % [bag_ref_before, death_bag_ref])

	var after_death_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var chest_after: String = str((after_death_snapshot.get("inventory_projection", {}) as Dictionary).get("equipment", {}).get("slots", {}).get("CHEST", ""))
	_check("DEATH_ARMOR_SAME_INSTANCE_RETAINED", not chest_after.is_empty() and chest_after == chest_before, "before=%s after=%s" % [chest_before, chest_after])

	# G16B-18: same real death event verified above -- no second death, no
	# manual restoration. CLOTHES stays equipped through death exactly like
	# ITEM-ARMOR does (equipped items are retained, not dropped into the Bag).
	if not clothes_instance_ref.is_empty():
		var legs_after_death: String = _string_or_empty((after_death_snapshot.get("inventory_projection", {}) as Dictionary).get("equipment", {}).get("slots", {}).get("LEGS"))
		_check(
			"DEATH_CLOTHES_RETAINED",
			clothes_instance_ref in (retention.get("equipped_clothes_refs", []) as Array),
			JSON.stringify(retention.get("equipped_clothes_refs", [])),
		)
		_check(
			"DEATH_CLOTHES_SAME_INSTANCE_RETAINED",
			not legs_after_death.is_empty() and legs_after_death == legs_before_death and legs_after_death == clothes_instance_ref,
			"before=%s after=%s" % [legs_before_death, legs_after_death],
		)
		# Still equipped (LEGS slot unchanged through death) is itself the
		# proof it was never dropped into the death Bag -- the same rule
		# already relied on for ITEM-ARMOR/CHEST above and for ITEM-OLD-KEY's
		# protected/critical retention: equip is atomic and exclusive, so an
		# instance still shown equipped here cannot also be inside the Bag.
		_check(
			"DEATH_CLOTHES_NOT_DROPPED",
			not legs_after_death.is_empty() and legs_after_death == clothes_instance_ref,
			"legs_after_death=%s" % legs_after_death,
		)
		_check(
			"DEATH_CLOTHES_NO_DUPLICATION",
			(retention.get("equipped_clothes_refs", []) as Array).count(clothes_instance_ref) == 1,
			JSON.stringify(retention.get("equipped_clothes_refs", [])),
		)

	var protected_entry_after_death: Dictionary = _inventory_entry(after_death_snapshot, "base", "ITEM-OLD-KEY")
	var protected_quantity_after_death: int = int(protected_entry_after_death.get("quantity", 0))
	# The dropped Bag never exposes its contents to the client (see
	# andromeda_authority_adapter.py::_bag_projection() -- no "contents" field
	# for a dropped bag), so there is no transport route to read it directly.
	# A live quantity of exactly 1 in the player's OWN base inventory, read
	# straight after this real death and before any respawn or manual action,
	# is still full authoritative proof: the item is stackable/singular and
	# grant/removal are atomic (already unit-tested directly against the Bag's
	# own contents in 12_AUTHORITY_BACKEND/tests/test_stage16b_authority_save_death_water.py),
	# so it can only ever exist in exactly one place -- if it were still in the
	# Bag, the player could not also show it here.
	_check("DEATH_PROTECTED_CRITICAL_RETURNED_TO_OWNER", protected_quantity_after_death == 1, JSON.stringify(protected_entry_after_death))
	_check("DEATH_PROTECTED_CRITICAL_NOT_DROPPED", protected_quantity_after_death == 1, JSON.stringify(protected_entry_after_death))
	_check("DEATH_PROTECTED_CRITICAL_NO_DUPLICATION", protected_quantity_after_death == 1, JSON.stringify(protected_entry_after_death))

	_check("BRIDGE_READY_BEFORE_RESPAWN", await _wait_for_bridge_ready(bridge))
	var respawn_result_start: int = _results.size()
	var respawn_projection_start: int = _respawn_projections.size()
	var respawn_request: Dictionary = main.death_respawn_client.request_respawn()
	_check("RESPAWN_REQUEST_PASS", respawn_request.get("status") == "PASS", JSON.stringify(respawn_request))
	_check("RESPAWN_REQUEST_TRANSPORT", respawn_request.get("transport_submitted") == true)
	_check("RESPAWN_POINT_NOT_CLIENT_SELECTED", respawn_request.get("respawn_point_selected_locally") == false)
	var respawn: Dictionary = await _wait_for_command("REQUEST_RESPAWN", respawn_result_start)
	_progress("RESPAWN_RESULT", {"received": not respawn.is_empty()})
	if respawn.is_empty():
		_failures.append("RESPAWN_RESULT_TIMEOUT")
		await _finish()
		return
	_check("RESPAWN_STAGE15_PASS", respawn.get("status") == "PASS", JSON.stringify(respawn))
	_check("RESPAWN_HAS_SAFE_WAYPOINT", not str(respawn.get("respawn_snapshot", {}).get("safe_waypoint_ref", "")).is_empty())
	_check("RESPAWN_POST_SAVE_REAL", respawn.get("post_respawn_save", {}).get("status") == "PASS")
	_check("RESPAWN_CLIENT_PROJECTED", await _wait_for_size(_respawn_projections, respawn_projection_start + 1))
	_check("RESPAWN_INPUT_RELEASED", not main.death_respawn_client.world_input_blocked())
	_check("RESPAWN_CAMERA_STABLE", main.camera_rig.follow_target() == main.player)

	_check("BRIDGE_READY_BEFORE_CLEANUP_RESTORE", await _wait_for_bridge_ready(bridge))
	var cleanup_restore_start: int = _results.size()
	var cleanup_projection_start: int = _restore_projections.size()
	var cleanup_reload: Dictionary = main.save_reload_client.request_reload_resync(SAVE_SLOT)
	_check("CLEANUP_RELOAD_SUBMITTED", cleanup_reload.get("transport_submitted") == true, JSON.stringify(cleanup_reload))
	var cleanup_restored: Dictionary = await _wait_for_command("REQUEST_RELOAD_RESYNC", cleanup_restore_start)
	_progress("CLEANUP_RESTORE_RESULT", {"received": not cleanup_restored.is_empty()})
	if cleanup_restored.is_empty():
		_failures.append("CLEANUP_RESTORE_RESULT_TIMEOUT")
		await _finish()
		return
	_check("CLEANUP_RELOAD_AUTHORITY_PASS", cleanup_restored.get("status") == "PASS", JSON.stringify(cleanup_restored))
	_check("CLEANUP_RESTORE_CLIENT_PROJECTED", await _wait_for_size(_restore_projections, cleanup_projection_start + 1))
	_check("CLEANUP_ALIVE_READY", main.death_respawn_client.state() in [AndromedaDeathRespawnClient.STATE_ALIVE, AndromedaDeathRespawnClient.STATE_READY])
	_check("CLEANUP_INPUT_RELEASED", not main.death_respawn_client.world_input_blocked())
	_check("CLEANUP_BAG_RESTORED", main.inventory_client.bag_state() == "BAG_EQUIPPED")
	_check("CLEANUP_DEATH_BAG_REMOVED", main.dropped_bag_client.dropped_bag_for_ref(death_bag_ref) == null)

	var save_contract: Dictionary = main.save_reload_client.contract_snapshot()
	var death_contract: Dictionary = main.death_respawn_client.contract_snapshot()
	var bag_contract: Dictionary = main.dropped_bag_client.contract_snapshot()
	_check("NO_GDSCRIPT_SAVE_AUTHORITY", save_contract.get("save_success_authority") == false and save_contract.get("restore_authority") == false)
	_check("NO_GDSCRIPT_TTL_AUTHORITY", save_contract.get("ttl_authority") == false and bag_contract.get("ttl_authority") == false)
	_check("NO_GDSCRIPT_DEATH_BAG_OWNERSHIP", death_contract.get("death_authority") == false and bag_contract.get("ownership_authority") == false)
	# DROP_NOT_ACTIVE: ground_loot_client's own, independent observation of the
	# two real drops this gate's death-retention proof already picked up
	# explicitly (see the comment where those pickups happen) can keep
	# producing this exact, already-explained rejection for a while after.
	#
	# _rejections (bridge.command_rejected) only carries the bare `reason`
	# string -- it cannot itself be correlated to a drop_ref. _results
	# (bridge.command_result_received, connected above) stores the FULL
	# backend response for every command instead, and andromeda_bridge.gd's
	# _on_command_request_completed() always emits command_result_received
	# for a result before emitting command_rejected for the same result, so
	# every DROP_NOT_ACTIVE entry in _rejections has exactly one matching
	# entry in _results. That entry carries command_ref, command and --
	# for REQUEST_PICKUP/CONFIRM_DROP_SETTLED specifically -- target_ref
	# echoing the drop_ref unconditionally, including on rejection
	# (andromeda_authority_adapter.py::_request_pickup /
	# ::_confirm_drop_settled both set "target_ref": drop_ref after
	# building the result). That is real, available identity -- used below
	# instead of a global reason-string filter.
	var expected_manual_drop_refs: Array[String] = []
	if not armor_drop_ref.is_empty():
		expected_manual_drop_refs.append(armor_drop_ref)
	if not common_drop_ref.is_empty():
		expected_manual_drop_refs.append(common_drop_ref)
	for gathering_drop_ref: String in gathering_fill_drop_refs:
		if not gathering_drop_ref.is_empty():
			expected_manual_drop_refs.append(gathering_drop_ref)
	var scoped_drop_not_active_refs: Array[String] = _scope_rejection_allowance(
		_results, "DROP_NOT_ACTIVE", ["REQUEST_PICKUP", "CONFIRM_DROP_SETTLED"], expected_manual_drop_refs
	)
	_check(
		"EXPECTED_MANUAL_DROP_REJECTIONS_SCOPED",
		not expected_manual_drop_refs.is_empty(),
		JSON.stringify({
			"expected_manual_drop_refs": expected_manual_drop_refs,
			"scoped_command_refs": scoped_drop_not_active_refs,
		}),
	)

	# G16B-26: the same discipline, for the real 9th-slot rejection --
	# correlated to the one drop_ref that specific probe pickup used.
	var expected_ninth_drop_refs: Array[String] = []
	if not base_slot_nine_drop_ref.is_empty():
		expected_ninth_drop_refs.append(base_slot_nine_drop_ref)
	var scoped_base_slot_limit_refs: Array[String] = _scope_rejection_allowance(
		_results, "BASE_INVENTORY_SLOT_LIMIT_WITHOUT_BAG", ["REQUEST_PICKUP"], expected_ninth_drop_refs
	)
	_check(
		"BASE_SLOT_NINE_REJECTION_SCOPED",
		not expected_ninth_drop_refs.is_empty() and not scoped_base_slot_limit_refs.is_empty(),
		JSON.stringify({
			"expected_ninth_drop_refs": expected_ninth_drop_refs,
			"scoped_command_refs": scoped_base_slot_limit_refs,
		}),
	)

	# Only as many DROP_NOT_ACTIVE / BASE_INVENTORY_SLOT_LIMIT_WITHOUT_BAG
	# occurrences as were just proven, above, to belong to this flow's own
	# manual drops are consumed here -- any further occurrence of either
	# reason (an unrelated drop), or any other reason entirely, is left in
	# _unexpected_rejections and still fails NO_COMMAND_REJECTIONS.
	var scoped_allowance: int = scoped_drop_not_active_refs.size()
	var base_slot_limit_allowance: int = scoped_base_slot_limit_refs.size()
	var _unexpected_rejections: Array[String] = []
	for reason: String in _rejections:
		if reason == "DROP_NOT_ACTIVE" and scoped_allowance > 0:
			scoped_allowance -= 1
			continue
		if reason == "BASE_INVENTORY_SLOT_LIMIT_WITHOUT_BAG" and base_slot_limit_allowance > 0:
			base_slot_limit_allowance -= 1
			continue
		_unexpected_rejections.append(reason)
	var unrelated_drop_not_active_in_output: int = 0
	var unrelated_base_slot_limit_in_output: int = 0
	for reason: String in _unexpected_rejections:
		if reason == "DROP_NOT_ACTIVE":
			unrelated_drop_not_active_in_output += 1
		if reason == "BASE_INVENTORY_SLOT_LIMIT_WITHOUT_BAG":
			unrelated_base_slot_limit_in_output += 1
	var total_drop_not_active_seen: int = 0
	var total_base_slot_limit_seen: int = 0
	for reason: String in _rejections:
		if reason == "DROP_NOT_ACTIVE":
			total_drop_not_active_seen += 1
		if reason == "BASE_INVENTORY_SLOT_LIMIT_WITHOUT_BAG":
			total_base_slot_limit_seen += 1
	_check(
		"UNRELATED_DROP_NOT_ACTIVE_NOT_SUPPRESSED",
		unrelated_drop_not_active_in_output == max(0, total_drop_not_active_seen - scoped_drop_not_active_refs.size()),
		"total=%d scoped=%d left_unexpected=%d" % [total_drop_not_active_seen, scoped_drop_not_active_refs.size(), unrelated_drop_not_active_in_output],
	)
	_check(
		"UNRELATED_BASE_SLOT_LIMIT_REJECTION_NOT_SUPPRESSED",
		unrelated_base_slot_limit_in_output == max(0, total_base_slot_limit_seen - scoped_base_slot_limit_refs.size()),
		"total=%d scoped=%d left_unexpected=%d" % [total_base_slot_limit_seen, scoped_base_slot_limit_refs.size(), unrelated_base_slot_limit_in_output],
	)
	_check("NO_COMMAND_REJECTIONS", _unexpected_rejections.is_empty(), JSON.stringify(_unexpected_rejections))
	_check("BRIDGE_FINAL_READY", await _wait_for_bridge_ready(bridge))
	await _finish()


func _request_and_wait_save() -> Dictionary:
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if bridge == null or not (await _wait_for_bridge_ready(bridge)):
		_failures.append("BRIDGE_NOT_READY_FOR_SAVE")
		return {}
	var result_start: int = _results.size()
	var projection_start: int = _save_projections.size()
	var intent: Dictionary = main.save_reload_client.request_manual_save(SAVE_SLOT)
	_check("SAVE_INTENT_PASS_%d" % result_start, intent.get("status") == "PASS", JSON.stringify(intent))
	_check("SAVE_TRANSPORT_SUBMITTED_%d" % result_start, intent.get("transport_submitted") == true)
	var result: Dictionary = await _wait_for_command("REQUEST_SAVE", result_start)
	_check("SAVE_RESULT_RECEIVED_%d" % result_start, not result.is_empty())
	_check("SAVE_PROJECTION_RECEIVED_%d" % result_start, await _wait_for_size(_save_projections, projection_start + 1))
	return result


func _restore_nested_sequences_are_int(snapshot: Variant) -> bool:
	if not snapshot is Dictionary:
		return false
	var value: Dictionary = snapshot
	for key: String in ["restore_sequence", "save_sequence"]:
		if typeof(value.get(key)) != TYPE_INT:
			return false
	var preference: Dictionary = value.get("profile_preference", {})
	var inventory: Dictionary = value.get("inventory_snapshot", {})
	var death: Dictionary = value.get("death_recovery_snapshot", {})
	return (
		typeof(preference.get("preference_sequence")) == TYPE_INT
		and typeof(inventory.get("snapshot_sequence")) == TYPE_INT
		and typeof(death.get("restore_sequence")) == TYPE_INT
	)


func _wait_for_auto_pickup(
	expected: bool,
	snapshot_start: int,
	bridge: AndromedaRuntimeBridge
) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		var raw_confirmed: bool = false
		for index: int in range(snapshot_start, _snapshots.size()):
			var preferences: Dictionary = _snapshots[index].get("profile_preferences", {})
			if preferences.has("auto_pickup") and bool(preferences.get("auto_pickup")) == expected:
				raw_confirmed = true
				break
		if (
			raw_confirmed
			and main.ground_loot_client.auto_pickup_enabled() == expected
			and bridge.connection_state().get("state") == AndromedaRuntimeBridge.STATE_READY
		):
			return true
		await get_tree().process_frame
	return false


func _wait_for_inventory_bag(expected: String) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		if main.inventory_client.bag_state() == expected:
			return true
		await get_tree().process_frame
	return false


func _wait_for_command(command: String, start_index: int) -> Dictionary:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		for index: int in range(start_index, _results.size()):
			if str(_results[index].get("command", "")) == command:
				return _results[index].duplicate(true)
		await get_tree().process_frame
	return {}


func _wait_for_size(values: Array, expected: int) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while values.size() < expected and Time.get_ticks_usec() < deadline:
		await get_tree().process_frame
	return values.size() >= expected


func _unique_ref(label: String) -> String:
	return "GODOT-DEATHRET-%s-%d" % [label, Time.get_ticks_usec()]


## G16B-18: equipment.slots pre-populates every slot key with GDScript null
## when unequipped (arpg_item_core.py::"equipped": {slot: None for slot in
## self.EQUIPMENT_SLOTS} -- serialized as JSON null, never an absent key or
## empty string). Dictionary.get(key, default) only falls back to default
## when the key is ABSENT, not when it is present with a null value, so a
## plain str(dict.get("LEGS", "")) call on an unequipped slot stringifies the
## literal null into the text "<null>" instead of "". This helper is the
## correct null-safe coercion (GDScript's "or" operator coerces both sides to
## bool and returns a bool, not either operand, so "x or \"\"" is NOT a valid
## Python-style fallback here).
func _string_or_empty(value: Variant) -> String:
	return str(value) if value != null else ""


## Pure correlation helper (no bridge/session dependency): given the list of
## command results this gate collected via bridge.command_result_received
## (same dictionary shape the bridge delivers -- status/reason/command/
## command_ref/target_ref) and the drop_refs this flow itself pickup()'d,
## returns the command_refs of rejections, for the given `reason` and
## `allowed_commands`, that are provably caused by those specific drops. The
## same reason for any other drop_ref, or from any other command, is never
## returned. Generalized (originally DROP_NOT_ACTIVE-only) so the same,
## already-proven correlation discipline covers BASE_INVENTORY_SLOT_LIMIT_
## WITHOUT_BAG (G16B-26) without a second, parallel filtering mechanism.
static func _scope_rejection_allowance(
	results: Array[Dictionary], reason: String, allowed_commands: Array[String], expected_target_refs: Array[String]
) -> Array[String]:
	var scoped: Array[String] = []
	for entry: Dictionary in results:
		if str(entry.get("status", "")) == "PASS":
			continue
		if str(entry.get("reason", "")) != reason:
			continue
		if not allowed_commands.has(str(entry.get("command", ""))):
			continue
		if not expected_target_refs.has(str(entry.get("target_ref", ""))):
			continue
		scoped.append(str(entry.get("command_ref", "")))
	return scoped


func _prove_drop_not_active_scoping() -> void:
	## Isolated correlation proof -- no live bridge/session involved, and
	## nothing here touches the real death-retention flow below. Fabricated
	## result entries, in the exact shape andromeda_bridge.gd's
	## command_result_received delivers, prove the scoping helper above
	## consumes only the two expected drops' rejections and leaves an
	## unrelated drop's identical reason string untouched.
	var fake_results: Array[Dictionary] = [
		{
			"status": "REJECTED", "reason": "DROP_NOT_ACTIVE", "command": "REQUEST_PICKUP",
			"command_ref": "FAKE-EXPECTED-ARMOR", "target_ref": "DROP-EXPECTED-ARMOR",
		},
		{
			"status": "REJECTED", "reason": "DROP_NOT_ACTIVE", "command": "CONFIRM_DROP_SETTLED",
			"command_ref": "FAKE-EXPECTED-COMMON", "target_ref": "DROP-EXPECTED-COMMON",
		},
		{
			"status": "REJECTED", "reason": "DROP_NOT_ACTIVE", "command": "REQUEST_PICKUP",
			"command_ref": "FAKE-UNRELATED", "target_ref": "DROP-UNRELATED-Z",
		},
		{
			"status": "PASS", "reason": "", "command": "REQUEST_PICKUP",
			"command_ref": "FAKE-PASS-NOISE", "target_ref": "DROP-EXPECTED-ARMOR",
		},
	]
	var expected: Array[String] = ["DROP-EXPECTED-ARMOR", "DROP-EXPECTED-COMMON"]
	var scoped: Array[String] = _scope_rejection_allowance(fake_results, "DROP_NOT_ACTIVE", ["REQUEST_PICKUP", "CONFIRM_DROP_SETTLED"], expected)
	_check(
		"EXPECTED_MANUAL_DROP_REJECTIONS_SCOPED_UNIT",
		scoped.has("FAKE-EXPECTED-ARMOR") and scoped.has("FAKE-EXPECTED-COMMON") and scoped.size() == 2,
		JSON.stringify(scoped),
	)
	_check(
		"UNRELATED_DROP_NOT_ACTIVE_NOT_SUPPRESSED_UNIT",
		not scoped.has("FAKE-UNRELATED"),
		JSON.stringify(scoped),
	)


func _await_command(bridge: AndromedaRuntimeBridge, command: String, params: Dictionary, label: String) -> Dictionary:
	var command_ref: String = _unique_ref(label)
	if bridge.submit_command(command, params, command_ref).get("status") != "PASS":
		return {}
	return await _result_for_ref(command_ref, 1)


func _result_for_ref(command_ref: String, occurrence: int) -> Dictionary:
	## Match by command_ref, never by arrival order -- other clients (auto-pickup,
	## settle confirmations) can interleave results in the same stream.
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		var seen: int = 0
		for entry: Dictionary in _results:
			if str(entry.get("command_ref", "")) != command_ref:
				continue
			seen += 1
			if seen == occurrence:
				return entry.duplicate(true)
		await get_tree().process_frame
	return {}


func _fresh_snapshot(bridge: AndromedaRuntimeBridge) -> Dictionary:
	var base: int = _snapshots.size()
	bridge.request_snapshot()
	if not await _wait_for_size(_snapshots, base + 1):
		return _snapshots.back() if not _snapshots.is_empty() else {}
	return _snapshots.back()


func _entry_by_drop_ref(snapshot: Dictionary, drop_ref: String) -> Dictionary:
	for value: Variant in snapshot.get("ground_loot", []):
		if value is Dictionary and str((value as Dictionary).get("drop_ref", "")) == drop_ref:
			return value as Dictionary
	return {}


func _drop_position(entry: Dictionary) -> Dictionary:
	for key: String in ["settled_position", "candidate_position"]:
		var value: Variant = entry.get(key)
		if value is Dictionary and (value as Dictionary).has("iso_x_m"):
			return {
				"iso_x_m": float((value as Dictionary).get("iso_x_m", 0.0)),
				"iso_y_m": float((value as Dictionary).get("iso_y_m", 0.0)),
				"altitude_m": float((value as Dictionary).get("altitude_m", 0.0)),
			}
	return {}


func _inventory_entry(snapshot: Dictionary, container: String, item_ref: String) -> Dictionary:
	## container is "base" or "bag" -- both use the same entry shape
	## (item_ref/quantity/instance_ref/protected_or_critical) from
	## andromeda_authority_adapter.py::_inventory_entries().
	var projection: Dictionary = snapshot.get("inventory_projection", {})
	var entries: Array = []
	if container == "bag":
		entries = (projection.get("bag", {}) as Dictionary).get("contents", [])
	else:
		entries = (projection.get("base_inventory", {}) as Dictionary).get("stacks", [])
	for value: Variant in entries:
		if value is Dictionary and str((value as Dictionary).get("item_ref", "")) == item_ref:
			return value as Dictionary
	return {}


func _wait_for_bridge_ready(bridge: AndromedaRuntimeBridge) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		if bridge.connection_state().get("state") == AndromedaRuntimeBridge.STATE_READY:
			return true
		await get_tree().process_frame
	return false


func _check(check_id: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(check_id if detail.is_empty() else "%s:%s" % [check_id, detail])


func _progress(marker: String, detail: Dictionary = {}) -> void:
	print("ANDROMEDA_AUTHORITY_B10_PROGRESS:%s:%s" % [marker, JSON.stringify(detail)])


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "STAGE16B_AUTHORITY_SAVE_DEATH_WATER_RELOAD",
		"backend_roundtrip_executed": true,
		"save_restore_roundtrip": true,
		"death_respawn_roundtrip": true,
		"cleanup_restore_executed": true,
		"authority": "STAGE15_STAGE16A_SERVER_AUTHORITATIVE",
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_AUTHORITY_SAVE_DEATH_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_AUTHORITY_SAVE_DEATH_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_AUTHORITY_SAVE_DEATH_SUMMARY: %s" % JSON.stringify(summary))
	if not _failures.is_empty():
		get_tree().quit(1)
		return
	var linger: float = _success_linger_seconds()
	if linger > 0.0:
		await get_tree().create_timer(linger).timeout
	get_tree().quit(0)


func _success_linger_seconds() -> float:
	var configured: float = float(ProjectSettings.get_setting("andromeda/gate/success_linger_s", 240.0))
	for argument: String in OS.get_cmdline_user_args():
		if argument.begins_with("--gate-success-linger="):
			var raw: String = argument.trim_prefix("--gate-success-linger=")
			if raw.is_valid_float():
				return maxf(0.0, raw.to_float())
	return maxf(0.0, configured)
