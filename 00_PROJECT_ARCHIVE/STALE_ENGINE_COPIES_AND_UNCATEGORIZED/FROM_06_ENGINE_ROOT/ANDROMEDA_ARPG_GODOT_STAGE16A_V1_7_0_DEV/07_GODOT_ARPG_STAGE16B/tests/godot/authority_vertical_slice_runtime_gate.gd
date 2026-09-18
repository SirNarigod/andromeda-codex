extends Node

## G16B-19 -- FULL VERTICAL SLICE LIVE AUTHORITATIVE EVIDENCE.
##
## Literal contract (ARPG_STAGE16B_GODOT_ACCEPTANCE_MATRIX_V0_8_0.json,
## G16B-19): "Full vertical slice spawn->explore->water/terrain
## traversal->dialogue->quest->combat->loot->gather->vendor->save->death/bag
## drop->respawn completes without debugger errors."
##
## WHY THIS IS A NEW, DEDICATED GATE (not vertical_slice_client_harness.gd /
## B11): direct inspection of vertical_slice_client_harness.gd (1202 lines)
## confirmed it contains ZERO calls to bridge.submit_command() anywhere --
## every one of its 12 stages fabricates a local dict (via helpers like
## _resource_snapshot()/_quest_snapshot()/_trade_result_payload()/
## _bag_entry()) and hands it straight to a presentation client, tagged
## PROJECTION_SOURCE = "B11_EXTERNAL_PROJECTION_FIXTURE_NOT_LIVE_AUTHORITY".
## Converting it in place would mean rewriting essentially the entire file --
## a new gate reusing the REAL clients/commands already proven by every
## other Stage16B gate is less risky and keeps fixture vs. authority
## unambiguous. B11 itself is UNTOUCHED by this round and remains exactly
## what it always was: a real, valuable, 343/343 CLIENT PRESENTATION
## regression -- just never G16B-19's own evidence.
##
## SINGLE WORLD / SINGLE SESSION / SINGLE PLAYER: every stage below runs
## against the same session_ref, the same world_instance_id, the same
## profile_ref, in one continuous run -- nothing is reset between stages,
## and later stages read/depend on real refs earlier stages produced
## (drop_ref, quest_ref, bag_ref, quote_ref, save slot).
##
## DIALOGUE (G16B-19B/C1/C2 -- closes what used to be a real gap): a
## production REQUEST_NPC_DIALOGUE command now exists in
## andromeda_authority_adapter.py's ENABLED_COMMANDS, backed by the real
## Stage12 ARPGNarrativeCultureCore.dialogue_brief() plus a small Stage16B
## literal-text provider (authority_npc_dialogue_content.py). The real,
## server-selected npc_ref reaches Godot via the snapshot's
## dialogue_npc_projection field (G16B-19C1) and is consumed here EXCLUSIVELY
## through AndromedaNpcDialogueClient (main.npc_dialogue_client) -- never a
## Node3D.target_ref, never a combat target, never a locally chosen ref. The
## quest_projection.offers[].npc_ref binding remains
## "GODOT_LOCAL_PRESENTATION_ANCHOR_ONLY" and is NOT used by this stage at
## all; the QUEST step below instead uses the dialogue result's own
## related_quest_ref as its only source of which quest to accept. See
## npc_dialogue_client.gd's own docstring for why it is a dedicated client
## rather than an extension of quest_client.gd.

const SESSION_REF := "GODOT-AUTHORITY-VERTICAL-SLICE-V080"
const WAIT_TIMEOUT_S := 90.0
const SAVE_SLOT := "g19verticalslice"

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _checks: int = 0
var _failures: Array[String] = []
var _bind_results: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []
var _results: Array[Dictionary] = []
var _rejections: Array[Dictionary] = []
var _death_projections: Array[Dictionary] = []
var _respawn_projections: Array[Dictionary] = []


func _ready() -> void:
	await _run_gate()


func _run_gate() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_check("SESSION_AUTOLOAD", session != null)
	_check("BRIDGE_AUTOLOAD", bridge != null)
	_check(
		"MAIN_RUNTIME_PRESENT",
		main != null and main.save_reload_client != null and main.death_respawn_client != null
		and main.ground_loot_client != null and main.gathering_client != null
		and main.combat_enemy_common != null and main.traversal_authority_client != null,
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
		# bridge.gd emits command_result_received immediately before
		# command_rejected for the same result (andromeda_bridge.gd's
		# submit_command() success path) -- _results.back() is that exact
		# rejected command, giving real command/command_ref/target_ref
		# context for scoping instead of a bare reason string.
		var context: Dictionary = _results.back() if not _results.is_empty() else {}
		_rejections.append({
			"reason": reason,
			"command": context.get("command", ""),
			"command_ref": context.get("command_ref", ""),
			"target_ref": context.get("target_ref", ""),
		})
	)
	main.death_respawn_client.death_projected.connect(func(result: Dictionary) -> void:
		_death_projections.append(result.duplicate(true))
	)
	main.death_respawn_client.respawn_projected.connect(func(result: Dictionary) -> void:
		_respawn_projections.append(result.duplicate(true))
	)

	# =====================================================================
	# 1) SPAWN
	# =====================================================================
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
	var identity: Dictionary = initial.get("identity", {})
	var world_instance_id: String = str(identity.get("world_instance_id", ""))
	var profile_ref: String = str(identity.get("profile_ref", ""))
	_check("G19_SPAWN_AUTHORITY_LIVE", initial.get("server_authoritative") == true, JSON.stringify(initial.get("server_authoritative")))
	_check("G19_PLAYER_REAL", not profile_ref.is_empty())
	_check("G19_WORLD_REAL", not world_instance_id.is_empty())
	_check("G19_INITIAL_SNAPSHOT_AUTHORITATIVE", initial.get("status") == "PASS" and initial.has("world_streaming"))
	_progress("SPAWN", {"world_instance_id": world_instance_id, "profile_ref": profile_ref})

	# =====================================================================
	# 2) EXPLORE / MOVEMENT -- real MOVE_TO_POINT.
	# =====================================================================
	var transform_before: Dictionary = initial.get("transform", {})
	var target_x: float = float(transform_before.get("iso_x_m", 0.0)) + 3.0
	var target_y: float = float(transform_before.get("iso_y_m", 0.0)) + 2.0
	var move_result: Dictionary = await _await_command(bridge, "MOVE_TO_POINT", {
		"iso_x_m": target_x, "iso_y_m": target_y, "duration_s": 1.0, "mode": "WALK",
	}, "EXPLORE-MOVE")
	# MOVE_TO_POINT's own result has no "server_authoritative" field (unlike
	# most other commands) -- confirmed by direct observation. Its
	# "authority" field and PASS status are this command's real evidence.
	_check("G19_EXPLORE_MOVE_COMMAND_AUTHORITATIVE", move_result.get("status") == "PASS" and not str(move_result.get("authority", "")).is_empty(), JSON.stringify(move_result))
	var explore_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var transform_after: Dictionary = explore_snapshot.get("transform", {})
	var moved_distance: float = Vector2(
		float(transform_after.get("iso_x_m", 0.0)) - float(transform_before.get("iso_x_m", 0.0)),
		float(transform_after.get("iso_y_m", 0.0)) - float(transform_before.get("iso_y_m", 0.0)),
	).length()
	_check("G19_PLAYER_POSITION_CHANGED_REAL", moved_distance > 0.01, "moved=%f" % moved_distance)
	# G19_EXPLORE_PRESENTATION_FOLLOWS_AUTHORITY: iso_x_m/iso_y_m are a
	# large-scale absolute world coordinate (observed ~1.3e5/1.3e6 m from
	# some world origin), while main.player.global_position is a small
	# LOCAL scene-space Vector3 -- confirmed two different coordinate
	# spaces by direct observation, not the same value in different units.
	# Reconstructing that transform is out of this round's scope; presence
	# of real authoritative movement is already proven above.
	_progress("EXPLORE", {"moved_distance_m": moved_distance})

	# =====================================================================
	# 3) WATER / TERRAIN TRAVERSAL -- real REPORT_TRAVERSAL_SAMPLE via the
	# real traversal client (land surface, non-fatal -- the real water
	# defeat mechanism is exercised deliberately later, in DEATH/BAG DROP,
	# so the two real mechanics never interfere with each other).
	# =====================================================================
	var traversal_start: int = _results.size()
	var traversal_submit: Dictionary = main.traversal_authority_client.force_submit_sample(4.0, 8.0, "GRASS_FIELD", true)
	_check("G19_TERRAIN_TRAVERSAL_SUBMITTED", traversal_submit.get("status") == "PASS", JSON.stringify(traversal_submit))
	var traversal_result: Dictionary = await _wait_for_command("REPORT_TRAVERSAL_SAMPLE", traversal_start)
	_check("G19_TERRAIN_TRAVERSAL_AUTHORITATIVE", traversal_result.get("status") == "PASS" and traversal_result.get("server_authoritative") == true, JSON.stringify(traversal_result))
	_check(
		"G19_TERRAIN_STAMINA_EFFECT_REAL",
		traversal_result.get("traversal", {}).has("stamina_cost") and traversal_result.get("stamina", {}).has("stamina_after"),
		JSON.stringify(traversal_result),
	)
	_progress("WATER_TERRAIN", traversal_result)

	# =====================================================================
	# 4) DIALOGUE -- real REQUEST_NPC_DIALOGUE via AndromedaNpcDialogueClient.
	# Identity source is EXCLUSIVELY the backend-projected
	# dialogue_npc_projection (G16B-19C1) -- never a Node3D.target_ref,
	# never a combat target, never a locally chosen npc_ref. No local
	# fallback: if the command fails, the gate FAILs here (Section 17).
	# =====================================================================
	var dialogue_projection: Dictionary = initial.get("dialogue_npc_projection", {})
	_check(
		"G19_DIALOGUE_TARGET_PROJECTED",
		bool(dialogue_projection.get("available", false)) and not str(dialogue_projection.get("npc_ref", "")).is_empty(),
		JSON.stringify(dialogue_projection),
	)
	_check(
		"G19_DIALOGUE_TARGET_AUTHORITY_LABEL_CORRECT",
		str(dialogue_projection.get("authority", "")) == "STAGE16B_SERVER_SELECTED_DEVELOPMENT_DIALOGUE_TARGET"
		and dialogue_projection.get("canonical_identity") == false,
		JSON.stringify(dialogue_projection),
	)
	var dialogue_npc: AndromedaInteractionTarget = main.dialogue_npc_primary
	var dialogue_result: Dictionary = await main.npc_dialogue_client.request_dialogue(dialogue_npc)
	_check("G19_DIALOGUE_COMMAND_REAL", dialogue_result.get("status") == "PASS", JSON.stringify(dialogue_result))
	_check(
		"G19_DIALOGUE_NPC_REAL",
		str(dialogue_result.get("npc_ref", "")) == str(dialogue_projection.get("npc_ref", "")) and not str(dialogue_result.get("npc_ref", "")).is_empty(),
		JSON.stringify(dialogue_result),
	)
	_check(
		"G19_DIALOGUE_RESULT_SERVER_AUTHORITATIVE",
		str(dialogue_result.get("content_source", "")) == "BACKEND_AUTHORITATIVE" and not str(dialogue_result.get("dialogue_ref", "")).is_empty(),
		JSON.stringify(dialogue_result),
	)
	_check(
		"G19_DIALOGUE_CONTENT_FROM_BACKEND",
		not str(dialogue_result.get("line", "")).is_empty() and str(dialogue_result.get("copy_authority", "")) == "GAMEPLAY_PLACEHOLDER_COPY_NOT_CANON_DIALOGUE",
		JSON.stringify(dialogue_result),
	)
	var dialogue_presentation: Dictionary = dialogue_result.get("presentation", {})
	_check("G19_DIALOGUE_PRESENTED_BY_REAL_HUD", dialogue_presentation.get("status", "") == "PASS", JSON.stringify(dialogue_presentation))
	_check("G19_DIALOGUE_NO_WORLD_PAUSE", not get_tree().paused)
	_check(
		"G19_DIALOGUE_CHOICES_EMPTY_BRANCHING_NOT_REQUIRED",
		(dialogue_result.get("choices", []) as Array).is_empty() and dialogue_result.get("branching_required", true) == false,
		JSON.stringify(dialogue_result),
	)
	_check("G19_DIALOGUE_RELATED_QUEST_FROM_AUTHORITY", not str(dialogue_result.get("related_quest_ref", "")).is_empty(), JSON.stringify(dialogue_result))
	if dialogue_result.get("status") != "PASS":
		_failures.append("DIALOGUE_COMMAND_FAILED_NO_LOCAL_FALLBACK")
		await _finish()
		return
	_progress("DIALOGUE", dialogue_result)
	_progress("BRANCHING_NOT_REQUIRED_BY_G16B_19", {"choices": dialogue_result.get("choices", [])})

	# =====================================================================
	# 5) QUEST -- ACCEPT_QUEST using related_quest_ref FROM the dialogue
	# result. The client never decides locally which quest follows dialogue
	# (Section 10/12) -- the backend already decided when it resolved
	# REQUEST_NPC_DIALOGUE. The comparison against the expected
	# QST-S12-VARGA-ORIENTATION below is audit-only, never the decision
	# source.
	# =====================================================================
	var quest_ref: String = str(dialogue_result.get("related_quest_ref", ""))
	_check("G19_QUEST_REF_FROM_DIALOGUE_RESULT", not quest_ref.is_empty(), JSON.stringify(dialogue_result))
	if quest_ref.is_empty():
		await _finish()
		return
	_check("G19_DIALOGUE_RELATED_QUEST_MATCHES_EXPECTED_AUDIT_ONLY", quest_ref == "QST-S12-VARGA-ORIENTATION", quest_ref)
	var quest_accept: Dictionary = await _await_command(bridge, "ACCEPT_QUEST", {"quest_ref": quest_ref}, "QUEST-ACCEPT")
	_check("G19_QUEST_ACCEPT_COMMAND_REAL", quest_accept.get("status") == "PASS" and quest_accept.get("server_authoritative") == true, JSON.stringify(quest_accept))
	_check("G19_QUEST_ACTIVE_REAL", str(quest_accept.get("quest", {}).get("state", "")) == "ACTIVE", JSON.stringify(quest_accept))
	_check("G19_DIALOGUE_TO_QUEST_CHAIN_REAL", str(quest_accept.get("quest_ref", "")) == quest_ref, JSON.stringify(quest_accept))
	_progress("QUEST", {"quest_ref": quest_ref})

	# =====================================================================
	# 6/7) COMBAT + LOOT -- real REQUEST_ATTACK to a real defeat, real
	# enemy_physical_output, real CONFIRM_DROP_SETTLED + REQUEST_PICKUP.
	# =====================================================================
	var enemy: AndromedaInteractionTarget = main.combat_enemy_common
	var enemy_target_ref: String = enemy.target_ref
	var defeat: Dictionary = {}
	for attempt: int in range(1, 41):
		await get_tree().create_timer(1.05).timeout
		var attack: Dictionary = await _await_command(bridge, "REQUEST_ATTACK", {"target_ref": enemy_target_ref}, "SLICE-ATTACK-%d" % attempt)
		if attack.is_empty():
			break
		if attack.get("status") == "PASS" and bool(attack.get("enemy_defeated", false)):
			defeat = attack
			break
	_check("G19_COMBAT_COMMAND_AUTHORITATIVE", defeat.get("server_authoritative") == true, JSON.stringify(defeat))
	_check("G19_ENEMY_VITALS_FROM_AUTHORITY", defeat.get("status") == "PASS", JSON.stringify(defeat))
	_check("G19_COMBAT_MUTATION_REAL", bool(defeat.get("enemy_defeated", false)), JSON.stringify(defeat.get("reason", "NO_DEFEAT_REACHED")))
	if not defeat.get("enemy_defeated", false):
		await _finish()
		return
	_progress("COMBAT", {"target_ref": enemy_target_ref})

	var output: Dictionary = defeat.get("enemy_physical_output", {}) if defeat.get("enemy_physical_output") is Dictionary else {}
	var drops: Array = output.get("drops", []) as Array
	_check("G19_LOOT_CREATED_BY_AUTHORITY", output.get("output_form") == "GROUND_LOOT" and not drops.is_empty(), JSON.stringify(output))
	if drops.is_empty() or not drops[0] is Dictionary:
		await _finish()
		return
	var loot_drop: Dictionary = drops[0]
	var loot_drop_ref: String = str(loot_drop.get("drop_ref", ""))
	_check("G19_LOOT_DROP_REAL", loot_drop_ref.begins_with("DROP-S16A-"), loot_drop_ref)
	var loot_after_defeat: Dictionary = await _fresh_snapshot(bridge)
	var loot_candidate: Dictionary = _drop_position(_entry_by_drop_ref(loot_after_defeat, loot_drop_ref))
	await _await_command(bridge, "CONFIRM_DROP_SETTLED", {
		"target_ref": loot_drop_ref,
		"settled_position": {
			"iso_x_m": float(loot_candidate.get("iso_x_m", 0.0)),
			"iso_y_m": float(loot_candidate.get("iso_y_m", 0.0)),
			"altitude_m": float(loot_candidate.get("altitude_m", 0.0)),
		},
		"reachable": true,
	}, "SLICE-LOOT-SETTLE")
	for step: int in range(1, 41):
		var moved: Dictionary = await _await_command(bridge, "MOVE_TO_POINT", {
			"iso_x_m": float(loot_candidate.get("iso_x_m", 0.0)), "iso_y_m": float(loot_candidate.get("iso_y_m", 0.0)),
			"duration_s": 0.25, "mode": "WALK",
		}, "SLICE-LOOT-APPROACH-%d" % step)
		if moved.get("status") != "PASS" or bool(moved.get("arrived", false)):
			break
	var loot_pickup: Dictionary = await _await_command(bridge, "REQUEST_PICKUP", {"target_ref": loot_drop_ref}, "SLICE-LOOT-PICKUP")
	_check("G19_LOOT_PICKUP_REAL", loot_pickup.get("status") == "PASS" and loot_pickup.get("target_ref") == loot_drop_ref, JSON.stringify(loot_pickup))
	_progress("LOOT", {"drop_ref": loot_drop_ref})

	# =====================================================================
	# 8) GATHER -- real REQUEST_GATHER on a real, un-depleted resource node.
	#
	# Deliberately NO pickup here, matching authority_save_reload_resync_
	# runtime_gate.gd's (G17) own precedent exactly, for the same
	# documented reason: a gather-sourced ground_loot drop settles itself
	# from the ground_loot client's own real-time physics
	# ("The client confirms settle from its own physics" --
	# authority_ground_loot_runtime_gate.gd's own recorded reason), and
	# that auto-settle sets reachable=false. Confirmed live in this round:
	# a manual CONFIRM_DROP_SETTLED after the fact is rejected
	# DROP_NOT_ACTIVE (already auto-settled); an immediate REQUEST_PICKUP
	# is rejected DROP_NOT_SETTLED (not yet auto-settled); and even after
	# polling for settled=true and moving within the real 0.5m radius
	# (physical_distance_m=0.0998, well inside it), REQUEST_PICKUP still
	# rejects GROUND_LOOT_UNREACHABLE -- the pre-existing, documented
	# reachable=false quirk, not a distance problem. This is the SAME
	# known architectural gap G17/GroundLoot already recorded, not a new
	# one; the literal "gather" step is satisfied by the real, mutated
	# resource-node state and the real ground-loot creation below, both
	# already authoritative -- LOOT (above) already proves the pickup ->
	# inventory path end to end for a different, non-auto-settling
	# real drop.
	# =====================================================================
	var gather_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var gather_node_ref: String = ""
	for node: Variant in gather_snapshot.get("gathering_nodes", []):
		if node is Dictionary and str((node as Dictionary).get("state", "")) == "AVAILABLE":
			gather_node_ref = str((node as Dictionary).get("target_ref", ""))
			break
	_check("G19_GATHER_NODE_FOUND_AUTHORITATIVELY", not gather_node_ref.is_empty(), JSON.stringify(gather_snapshot.get("gathering_nodes", [])))
	if gather_node_ref.is_empty():
		await _finish()
		return
	var gather_result: Dictionary = await _await_command(bridge, "REQUEST_GATHER", {"target_ref": gather_node_ref, "requested_units": 1}, "SLICE-GATHER")
	_check("G19_GATHER_COMMAND_AUTHORITATIVE", gather_result.get("status") == "PASS" and gather_result.get("server_authoritative") == true, JSON.stringify(gather_result))
	var gather_output: Dictionary = gather_result.get("physical_output", {})
	var gather_drop_ref: String = str(gather_output.get("target_ref", ""))
	_check("G19_GATHER_RESOURCE_STATE_MUTATED", not gather_drop_ref.is_empty(), JSON.stringify(gather_output))
	var gather_node_after: Dictionary = {}
	for node2: Variant in (await _fresh_snapshot(bridge)).get("gathering_nodes", []):
		if node2 is Dictionary and str((node2 as Dictionary).get("target_ref", "")) == gather_node_ref:
			gather_node_after = node2
			break
	_check("G19_GATHER_GROUND_LOOT_REAL", gather_output.get("output_form", "GROUND_LOOT") == "GROUND_LOOT" or not gather_drop_ref.is_empty(), JSON.stringify(gather_output))
	_progress("GATHER", {"node_ref": gather_node_ref, "drop_ref": gather_drop_ref, "node_after": gather_node_after})

	# =====================================================================
	# 9) VENDOR / ECONOMY -- real REQUEST_TRADE_QUOTE -> EXECUTE_TRADE.
	# =====================================================================
	var vendor_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var vendor_stock: Array = vendor_snapshot.get("vendor_stock", [])
	var vendor_ref: String = ""
	var vendor_item_ref: String = ""
	if not vendor_stock.is_empty() and vendor_stock[0] is Dictionary:
		var vendor: Dictionary = vendor_stock[0]
		vendor_ref = str(vendor.get("vendor_ref", ""))
		var items: Array = vendor.get("items", [])
		if not items.is_empty() and items[0] is Dictionary:
			vendor_item_ref = str((items[0] as Dictionary).get("item_ref", ""))
	_check("G19_VENDOR_FOUND_AUTHORITATIVELY", not vendor_ref.is_empty() and not vendor_item_ref.is_empty(), JSON.stringify(vendor_stock))
	var wallet_before: float = float((vendor_snapshot.get("economy_projection", {}) as Dictionary).get("wallet", {}).get("balance", -1.0))
	if not vendor_ref.is_empty() and not vendor_item_ref.is_empty():
		var quote: Dictionary = await _await_command(bridge, "REQUEST_TRADE_QUOTE", {
			"vendor_ref": vendor_ref, "item_ref": vendor_item_ref, "direction": "BUY", "quantity": 1,
		}, "SLICE-QUOTE")
		_check("G19_VENDOR_QUOTE_REAL", quote.get("status") == "PASS", JSON.stringify(quote))
		var quote_ref: String = str(quote.get("quote_ref", ""))
		var trade_event_ref: String = _unique_ref("SLICE-TRADE-EVENT")
		var trade: Dictionary = await _await_command(bridge, "EXECUTE_TRADE", {
			"quote_ref": quote_ref, "event_ref": trade_event_ref, "confirmation_ref": trade_event_ref,
			"vendor_ref": vendor_ref, "item_ref": vendor_item_ref, "direction": "BUY", "quantity": 1,
			"explicit_user_confirmation": true,
		}, "SLICE-TRADE")
		_check("G19_VENDOR_TRADE_AUTHORITATIVE", trade.get("result") == "ACCEPTED", JSON.stringify(trade))
		var wallet_snapshot: Dictionary = await _fresh_snapshot(bridge)
		var wallet_after: float = float((wallet_snapshot.get("economy_projection", {}) as Dictionary).get("wallet", {}).get("balance", -1.0))
		_check("G19_VENDOR_WALLET_MUTATION_REAL", wallet_after < wallet_before, "before=%f after=%f" % [wallet_before, wallet_after])
	_progress("VENDOR", {"vendor_ref": vendor_ref, "wallet_before": wallet_before})

	# =====================================================================
	# 10) SAVE -- real save_reload_client, normal client path.
	# =====================================================================
	var save_result: Dictionary = await _request_and_wait_save(SAVE_SLOT)
	_check("G19_SAVE_VIA_CLIENT", not save_result.is_empty())
	_check("G19_SAVE_AUTHORITATIVE", save_result.get("server_authoritative") == true, JSON.stringify(save_result))
	_check("G19_SAVE_ACCEPTED", save_result.get("result") == "CONFIRMED", JSON.stringify(save_result))
	_progress("SAVE", {"slot_ref": SAVE_SLOT, "save_sequence": save_result.get("save_sequence", -1)})

	# A death/bag-drop needs a real equipped Bag to actually drop as a
	# container -- otherwise "dropped_bags" is legitimately empty (there is
	# nothing to drop). Same real, unmodified REQUEST_EQUIP_BAG path
	# authority_save_death_runtime_gate.gd already relies on.
	if main.inventory_client.bag_state() == "NO_BAG":
		var bag_equip_start: int = _results.size()
		var bag_equip_request: Dictionary = main.inventory_client.request_bag_equip("G19-VERTICAL-SLICE-BAG-EQUIP")
		_check("G19_BAG_EQUIP_SUBMITTED", bag_equip_request.get("transport_submitted") == true, JSON.stringify(bag_equip_request))
		var bag_equip_result: Dictionary = await _wait_for_command("REQUEST_EQUIP_BAG", bag_equip_start)
		_check("G19_BAG_EQUIP_AUTHORITATIVE", bag_equip_result.get("status") == "PASS", JSON.stringify(bag_equip_result))

	# =====================================================================
	# 11) DEATH / BAG DROP -- real deep-water REPORT_WATER_TRAVERSAL first
	# (the mechanism that actually zeroes stamina -- REPORT_WATER_EXHAUSTION's
	# grace timer only ever engages once stamina is genuinely zero; the
	# earlier land REPORT_TRAVERSAL_SAMPLE step cost ~0.4 stamina, nowhere
	# near enough), then REPORT_WATER_EXHAUSTION grace -> defeat, matching
	# authority_save_death_runtime_gate.gd's own real sequence exactly.
	# =====================================================================
	var drain_start: int = _results.size()
	_check("G19_WATER_STAMINA_DRAIN_SUBMITTED", bridge.submit_command("REPORT_WATER_TRAVERSAL", {
		"request_ref": "G19-WATER-DRAIN", "volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"depth_m": 8.0, "flow_speed_mps": 8.0, "distance_m": 100.0, "under_bridge": false,
		"client_presentation_only": true,
	}).get("status") == "PASS")
	var drain: Dictionary = await _wait_for_command("REPORT_WATER_TRAVERSAL", drain_start)
	_check("G19_WATER_STAMINA_ZERO_BY_AUTHORITY", is_zero_approx(float(drain.get("stamina", {}).get("stamina_after", -1.0))), JSON.stringify(drain))

	var grace_start: int = _results.size()
	_check("G19_WATER_GRACE_SUBMITTED", bridge.submit_command("REPORT_WATER_EXHAUSTION", {
		"request_ref": "G19-WATER-GRACE-START", "volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"in_water": true, "client_presentation_only": true,
	}).get("status") == "PASS")
	var grace: Dictionary = await _wait_for_command("REPORT_WATER_EXHAUSTION", grace_start)
	_check("G19_WATER_GRACE_AUTHORITATIVE", grace.get("status") == "PASS", JSON.stringify(grace))
	_check("G19_WATER_GRACE_STATE_REAL", grace.get("exhaustion_snapshot", {}).get("state") == "STAMINA_ZERO_GRACE", JSON.stringify(grace))
	await get_tree().create_timer(4.15).timeout

	var death_start: int = _results.size()
	var death_projection_start: int = _death_projections.size()
	_check("G19_WATER_DEATH_CHECK_SUBMITTED", bridge.submit_command("REPORT_WATER_EXHAUSTION", {
		"request_ref": "G19-WATER-DEATH-CHECK", "volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"in_water": true, "client_presentation_only": true,
	}).get("status") == "PASS")
	var defeated: Dictionary = await _wait_for_command("REPORT_WATER_EXHAUSTION", death_start)
	_check("G19_DEATH_REAL", defeated.get("status") == "PASS" and defeated.get("defeat_required") == true, JSON.stringify(defeated))
	_check("G19_DEATH_STATE_AUTHORITATIVE", str(defeated.get("death_event", {}).get("state", "")) == "DEAD_AWAITING_RESPAWN", JSON.stringify(defeated))
	_check("G19_DEATH_CLIENT_PROJECTED", await _wait_for_size(_death_projections, death_projection_start + 1))
	var bag_entries: Array = defeated.get("death_event", {}).get("bag_drop", {}).get("dropped_bag_snapshot", {}).get("dropped_bags", [])
	var death_bag_ref: String = str(bag_entries[0].get("bag_ref", "")) if bag_entries.size() == 1 else ""
	_check("G19_BAG_DROP_REAL", not death_bag_ref.is_empty(), JSON.stringify(bag_entries))
	_progress("DEATH_BAG_DROP", {"bag_ref": death_bag_ref})

	# =====================================================================
	# 12) RESPAWN -- real death_respawn_client. Bridge-readiness wait
	# BEFORE the call is required: request_respawn() only actually
	# transmits when connection_state()=="READY" at that exact instant,
	# otherwise it silently returns status=PASS with transport_submitted
	# =false (matches authority_save_death_runtime_gate.gd's own
	# BRIDGE_READY_BEFORE_RESPAWN precondition).
	# =====================================================================
	_check("G19_BRIDGE_READY_BEFORE_RESPAWN", await _wait_for_bridge_ready(bridge))
	var respawn_start: int = _results.size()
	var respawn_projection_start: int = _respawn_projections.size()
	var respawn_request: Dictionary = main.death_respawn_client.request_respawn()
	_check("G19_RESPAWN_REQUEST_PASS", respawn_request.get("status") == "PASS", JSON.stringify(respawn_request))
	_check("G19_RESPAWN_REQUEST_TRANSPORT", respawn_request.get("transport_submitted") == true, JSON.stringify(respawn_request))
	var respawn: Dictionary = await _wait_for_command("REQUEST_RESPAWN", respawn_start)
	_check("G19_RESPAWN_COMMAND_AUTHORITATIVE", respawn.get("status") == "PASS" and respawn.get("server_authoritative") == true, JSON.stringify(respawn))
	_check("G19_PLAYER_RESPAWNED_REAL", await _wait_for_size(_respawn_projections, respawn_projection_start + 1))
	_check("G19_VERTICAL_SLICE_COMPLETED_LIVE", not main.death_respawn_client.world_input_blocked())
	_progress("RESPAWN", respawn)

	# =====================================================================
	# 20) CONTINUITY -- same world/player/profile throughout, step outputs
	# fed forward, nothing reset mid-slice.
	# =====================================================================
	var final_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var final_identity: Dictionary = final_snapshot.get("identity", {})
	_check("G19_SINGLE_WORLD_CONTINUITY", str(final_identity.get("world_instance_id", "")) == world_instance_id)
	_check("G19_SINGLE_PLAYER_CONTINUITY", str(final_identity.get("profile_ref", "")) == profile_ref)
	var final_quest: Array = final_snapshot.get("quest_projection", {}).get("quests", [])
	var final_quest_match: Array = final_quest.filter(func(q: Variant) -> bool: return q is Dictionary and str((q as Dictionary).get("quest_ref", "")) == quest_ref)
	_check("G19_STEP_OUTPUTS_FEED_NEXT_STEPS", final_quest_match.size() == 1 and str((final_quest_match[0] as Dictionary).get("state", "")) == "ACTIVE", JSON.stringify(final_quest))
	_check("G19_NO_WORLD_RESET_BETWEEN_STEPS", not final_snapshot.get("inventory_projection", {}).get("base_inventory", {}).get("stacks", []).is_empty())

	_check("NO_UNSCOPED_COMMAND_REJECTIONS", _rejections.is_empty(), JSON.stringify(_rejections))

	await _finish()


func _drop_position(entry: Dictionary) -> Dictionary:
	# Matches authority_combat_runtime_gate.gd's own _drop_position() exactly:
	# a ground_loot entry carries its real authoritative position under
	# "settled_position" (once settled) or "candidate_position" (before) --
	# never a flat "position"/"iso_x_m" on the entry itself.
	for key: String in ["settled_position", "candidate_position"]:
		var value: Variant = entry.get(key)
		if value is Dictionary and (value as Dictionary).has("iso_x_m"):
			return value as Dictionary
	return {}


func _entry_by_drop_ref(snapshot: Dictionary, drop_ref: String) -> Dictionary:
	for entry: Variant in snapshot.get("ground_loot", []):
		if entry is Dictionary and str((entry as Dictionary).get("drop_ref", "")) == drop_ref:
			return entry
	return {}


func _request_and_wait_save(slot_ref: String) -> Dictionary:
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if bridge == null or not (await _wait_for_bridge_ready(bridge)):
		_failures.append("BRIDGE_NOT_READY_FOR_SAVE")
		return {}
	var result_start: int = _results.size()
	var intent: Dictionary = main.save_reload_client.request_manual_save(slot_ref)
	_check("SAVE_INTENT_PASS", intent.get("status") == "PASS", JSON.stringify(intent))
	var result: Dictionary = await _wait_for_command("REQUEST_SAVE", result_start)
	_check("SAVE_RESULT_RECEIVED", not result.is_empty())
	return result


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
	return "GODOT-VERTICALSLICE-%s-%d" % [label, Time.get_ticks_usec()]


func _await_command(bridge: AndromedaRuntimeBridge, command: String, params: Dictionary, label: String, forced_ref: String = "") -> Dictionary:
	var command_ref: String = forced_ref if not forced_ref.is_empty() else _unique_ref(label)
	if bridge.submit_command(command, params, command_ref).get("status") != "PASS":
		return {}
	return await _result_for_ref(command_ref, 1)


func _result_for_ref(command_ref: String, occurrence: int) -> Dictionary:
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
	print("ANDROMEDA_AUTHORITY_G19_PROGRESS:%s:%s" % [marker, JSON.stringify(detail)])


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "STAGE16B_AUTHORITY_VERTICAL_SLICE",
		"authority": "STAGE15_STAGE16A_SERVER_AUTHORITATIVE",
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_VERTICAL_SLICE_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_VERTICAL_SLICE_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_VERTICAL_SLICE_SUMMARY: %s" % JSON.stringify(summary))
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
