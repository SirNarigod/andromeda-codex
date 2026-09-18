extends Node

const SESSION_REF := "GODOT-AUTHORITY-COMBAT-V080"
const WAIT_TIMEOUT_S := 15.0

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _checks: int = 0
var _failures: Array[String] = []
var _bind_results: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []
var _results: Array[Dictionary] = []
var _client_projections: Array[Dictionary] = []
var _rejections: Array[String] = []


func _ready() -> void:
	await _run_gate()


func _run_gate() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_check("SESSION_AUTOLOAD", session != null)
	_check("BRIDGE_AUTOLOAD", bridge != null)
	_check("MAIN_COMBAT_CLIENT", main != null and main.combat_authority_client != null)
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
	main.combat_authority_client.attack_result_projected.connect(func(result: Dictionary) -> void:
		_client_projections.append(result.duplicate(true))
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
	var enabled: Array = _bind_results[0].get("enabled_commands", [])
	_check("REQUEST_ATTACK_ENABLED", enabled.has("REQUEST_ATTACK"), JSON.stringify(enabled))
	_check("SNAPSHOT_SERVER_AUTHORITATIVE", initial.get("server_authoritative") == true)
	_check("COMBAT_TARGETS_PRESENT", initial.get("combat_targets") is Array)
	_check("COMBAT_PRESENTATION_PRESENT", initial.get("combat_presentation") is Dictionary)
	_check("TWO_REAL_COMBAT_TARGETS", (initial.get("combat_targets", []) as Array).size() == 2)
	var initial_common_entry: Dictionary = _target_entry(initial, "COMMON")
	var initial_alpha_entry: Dictionary = _target_entry(initial, "ALPHA")
	if not await _wait_for_projected_targets(
		str(initial_common_entry.get("target_ref", "")),
		str(initial_alpha_entry.get("target_ref", ""))
	):
		_failures.append("COMBAT_TARGET_PROJECTION_TIMEOUT")
		await _finish()
		return

	var common: AndromedaInteractionTarget = main.combat_enemy_common
	var alpha: AndromedaInteractionTarget = main.combat_enemy_alpha
	var common_entry: Dictionary = initial_common_entry
	var alpha_entry: Dictionary = initial_alpha_entry
	_check("COMMON_REF_FROM_AUTHORITY", common.target_ref == common_entry.get("target_ref"))
	_check("ALPHA_REF_FROM_AUTHORITY", alpha.target_ref == alpha_entry.get("target_ref"))
	_check("TARGET_REFS_UNIQUE", common.target_ref != alpha.target_ref)
	_check("COMMON_HOSTILE_EXTERNAL", common.hostile and common_entry.get("hostile") == true)
	_check("ALPHA_HOSTILE_EXTERNAL", alpha.hostile and alpha_entry.get("hostile") == true)
	_check("COMMON_REAL_STAGE07_IDENTITY", common.target_ref.begins_with("NPC-"))
	_check("ALPHA_REAL_STAGE07_IDENTITY", alpha.target_ref.begins_with("NPC-"))
	_check("COMMON_ATTACK_RANGE_PROJECTED", float(common.get_meta("authority_attack_range_m", 0.0)) > 0.0)
	_check("ALPHA_ATTACK_RANGE_PROJECTED", float(alpha.get_meta("authority_attack_range_m", 0.0)) > 0.0)
	_check("HUD_REBOUND_TO_REAL_TARGETS", main.hud.enemy_bar_for_ref(common.target_ref) != null and main.hud.enemy_bar_for_ref(alpha.target_ref) != null)
	_check("ALPHA_SHIELD_NOT_FABRICATED", alpha_entry.get("shield_fraction") == 0.0 and alpha_entry.get("shield_authority") == "NOT_AVAILABLE_IN_STAGE16A_COMBAT_CORE")
	_check("PLAYER_PROTECTION_NOT_FABRICATED", initial.get("combat_presentation", {}).get("player", {}).get("protection_authority") == "NOT_AVAILABLE_IN_STAGE16A_COMBAT_CORE")

	# The historical Stage16B scene placed its placeholder Common target inside the
	# Player's initial range. Real Stage17 target positions are territorial and may
	# legitimately be farther away after earlier sessions. Put the Player in range via
	# the real movement authority before testing the direct-attack branch; never move
	# the target Node or derive territorial truth from its transform.
	var common_candidate: Dictionary = main.combat_authority_client.evaluate_attack_candidate(common)
	if common_candidate.get("status") != "PASS":
		var common_range: float = float(common.get_meta("authority_attack_range_m", 0.0))
		var common_approach: Vector3 = main.combat_authority_client.approach_destination_for(common, common_range)
		if common_approach != Vector3.INF:
			var common_move_start: int = _results.size()
			var common_move: Dictionary = main.player.request_move(common_approach)
			if common_move.get("status") == "PASS" and common_move.get("transport_submitted") == true:
				var common_move_result: Dictionary = await _wait_for_command_result("MOVE_TO_POINT", "", common_move_start)
				if common_move_result.get("status") == "PASS":
					await _wait_for_visual_position(common_approach)

	await _wait_physics_frames(4)
	var left: Dictionary = main.handle_pointer_event(_mouse_button(MOUSE_BUTTON_LEFT, main.target_to_screen(common)))
	_check("LEFT_SELECT_COMMON_PASS", left.get("status") == "PASS", JSON.stringify(left))
	# COMMON and ALPHA currently share one real movement-state position. The pointer
	# resolver therefore chooses the actual front-most collider; continue with that
	# stable authoritative identity instead of imposing the historical scene slot.
	var attack_target: AndromedaInteractionTarget = main.combat_authority_client.actor_for_ref(
		main.selected_target_ref()
	)
	_check(
		"LEFT_SELECT_COMMON_STABLE_REF",
		attack_target != null
		and main.selected_target_ref() == str(left.get("target_ref", main.selected_target_ref()))
		and main.selected_target_ref().begins_with("NPC-")
	)
	var selected_before: String = main.selected_target_ref()
	var attack_slot: String = str(attack_target.get_meta("combat_rank", "COMMON")) if attack_target != null else "COMMON"
	var result_start: int = _results.size()
	var projection_start: int = _client_projections.size()
	var right: Dictionary = main.handle_pointer_event(_mouse_button(MOUSE_BUTTON_RIGHT, main.target_to_screen(common)))
	var right_client: Dictionary = right.get("combat_client_result", {})
	_check("RIGHT_HOSTILE_CHASE_ATTACK", right.get("intent") == "CHASE_ATTACK", JSON.stringify(right))
	_check("RIGHT_HOSTILE_CLICK_ONLY", right.get("input_mode") == "CLICK_ONLY")
	_check("RIGHT_COMBAT_CLIENT_PASS", right_client.get("status") == "PASS", JSON.stringify(right_client))
	_check("RIGHT_ATTACK_TRANSPORT_SUBMITTED", right_client.get("transport_submitted") == true, JSON.stringify(right_client))
	_check("RIGHT_DOES_NOT_CHANGE_SELECTED_TARGET", main.selected_target_ref() == selected_before)
	var first_params: Dictionary = right_client.get("intent_envelope", {}).get("envelope", {}).get("params", {})
	_check("ATTACK_ENVELOPE_TARGET_ONLY", first_params.keys() == ["target_ref"] and first_params.get("target_ref") == selected_before, JSON.stringify(first_params))
	_check("ATTACK_ENVELOPE_NO_PLAYER_OR_OUTCOME", not first_params.has("player_ref") and not first_params.has("damage") and not first_params.has("hit") and not first_params.has("critical") and not first_params.has("cooldown_s"))
	var first: Dictionary = await _wait_for_command_result("REQUEST_ATTACK", selected_before, result_start)
	_check("FIRST_ATTACK_RESULT_RECEIVED", not first.is_empty())
	_check("FIRST_ATTACK_STAGE03_PASS", first.get("status") == "PASS", JSON.stringify(first))
	_check("FIRST_ATTACK_SERVER_AUTHORITATIVE", first.get("server_authoritative") == true)
	_check("FIRST_ATTACK_HIT_SERVER_SIDE", first.get("hit_evaluated_server_side") == true)
	_check("FIRST_ATTACK_CRITICAL_SERVER_SIDE", first.get("critical_evaluated_server_side") == true)
	_check("FIRST_ATTACK_DAMAGE_SERVER_SIDE", first.get("damage_evaluated_server_side") == true)
	_check("FIRST_ATTACK_RANGE_SERVER_SIDE", first.get("range_evaluated_server_side") == true)
	_check("FIRST_ATTACK_COOLDOWN_SERVER_SIDE", first.get("cooldown_evaluated_server_side") == true)
	_check("FIRST_ATTACK_DEATH_SERVER_SIDE", first.get("death_evaluated_server_side") == true)
	_check("FIRST_ATTACK_CORE_AUTHORITY", str(first.get("authority", "")).contains("ARPG_COMBAT_CORE"))
	_check("CLIENT_RESULT_PROJECTION_RECEIVED", await _wait_for_size(_client_projections, projection_start + 1))
	var first_projection: Dictionary = _client_projections[projection_start] if _client_projections.size() > projection_start else {}
	_check("CLIENT_PROJECTS_WITHOUT_DAMAGE_AUTHORITY", first_projection.get("damage_decided_locally") == false and first_projection.get("hit_decided_locally") == false)
	_check("FEEDBACK_PRESERVES_SELECTION", main.selected_target_ref() == selected_before)
	var first_bar := main.hud.enemy_bar_for_ref(selected_before)
	var target_state: Dictionary = first.get("target_state", {})
	var expected_fraction: float = float(target_state.get("health", 0.0)) / maxf(0.000001, float(target_state.get("max_health", 1.0)))
	_check("HP_BAR_FROM_EXTERNAL_RESULT", first_bar != null and is_equal_approx(first_bar.hp_fraction(), expected_fraction))

	var cooldown_start: int = _results.size()
	var space_cooldown: Dictionary = main.handle_action_event(_key_event(KEY_SPACE))
	_check("SPACE_SELECTED_ATTACK_DISPATCHED", space_cooldown.get("intent") == "ATTACK_SELECTED_TARGET", JSON.stringify(space_cooldown))
	_check("SPACE_COOLDOWN_REQUEST_SUBMITTED", space_cooldown.get("combat_client_result", {}).get("transport_submitted") == true, JSON.stringify(space_cooldown))
	var cooldown: Dictionary = await _wait_for_command_result("REQUEST_ATTACK", selected_before, cooldown_start)
	_check("CORE_COOLDOWN_REJECTS_SPAM", cooldown.get("status") == "REJECTED" and cooldown.get("reason") == "ATTACK_COOLDOWN", JSON.stringify(cooldown))
	_check("CORE_COOLDOWN_REMAINING_EXTERNAL", float(cooldown.get("remaining_s", 0.0)) > 0.0)
	_check("COOLDOWN_REJECTION_TARGET_STABLE", main.selected_target_ref() == selected_before)

	await get_tree().create_timer(1.1).timeout
	var recovered_start: int = _results.size()
	var recovered_request: Dictionary = main.handle_action_event(_key_event(KEY_SPACE))
	_check("SPACE_AFTER_RECOVERY_SUBMITTED", recovered_request.get("combat_client_result", {}).get("transport_submitted") == true, JSON.stringify(recovered_request))
	var recovered: Dictionary = await _wait_for_command_result("REQUEST_ATTACK", selected_before, recovered_start)
	_check("SERVER_ELAPSED_RECOVERS_COOLDOWN", recovered.get("status") == "PASS", JSON.stringify(recovered))
	_check("CLIENT_DELTA_NOT_ACCEPTED", recovered.get("runtime_pulse", {}).get("client_delta_accepted") == false)

	# Sample the authoritative HP from a snapshot taken immediately before the replay.
	# The earlier form compared an attack-result payload against _snapshots.back() after
	# waiting for an absolute snapshot count, so on a world where other clients had
	# already produced snapshots it could read a projection from before the replay, or
	# one separated from the sample by intervening world ticks. A suppressed replay
	# advances no tick, so two snapshots bracketing it must report identical HP.
	var pre_replay: Dictionary = await _fresh_snapshot(bridge)
	var hp_before_replay: float = float(_target_entry(pre_replay, attack_slot).get("health", -1.0))
	var replay_start: int = _results.size()
	var first_ref: String = str(first.get("command_ref", ""))
	_check("ATTACK_REPLAY_SUBMITTED", bridge.submit_command("REQUEST_ATTACK", {"target_ref": selected_before}, first_ref).get("status") == "PASS")
	var replay: Dictionary = await _wait_for_command_result("REQUEST_ATTACK", selected_before, replay_start)
	_check("ATTACK_REPLAY_SUPPRESSED", replay.get("idempotent_replay") == true and replay.get("replay_suppressed") == true, JSON.stringify(replay))
	_check("REPLAY_RETURNS_ORIGINAL_EVENT", replay.get("event_ref") == first.get("event_ref"))
	_check("STALE_RESULT_NOT_REPROJECTED", main.combat_authority_client.project_attack_result(replay).get("reason") == "STALE_OR_DUPLICATE_COMBAT_RESULT")
	_check("REPLAY_DOES_NOT_REWRITE_SELECTION", main.selected_target_ref() == selected_before)
	var post_replay: Dictionary = await _fresh_snapshot(bridge)
	if post_replay.is_empty():
		_failures.append("POST_REPLAY_SNAPSHOT_TIMEOUT")
	var current_common: Dictionary = _target_entry(post_replay, attack_slot)
	var hp_after_replay: float = float(current_common.get("health", -2.0))
	_check("REPLAY_WORLD_HP_NOT_REAPPLIED", is_equal_approx(hp_after_replay, hp_before_replay), "before=%f after=%f" % [hp_before_replay, hp_after_replay])

	var stale: Dictionary = main.combat_authority_client.project_combat_snapshot(initial)
	_check("STALE_COMBAT_SNAPSHOT_REJECTED", stale.get("reason") == "STALE_OR_DUPLICATE_COMBAT_SNAPSHOT")
	var wrong_session: Dictionary = post_replay.duplicate(true)
	wrong_session["session_ref"] = "OTHER-COMBAT-SESSION"
	wrong_session["snapshot_sequence"] = int(post_replay.get("snapshot_sequence", 0)) + 100
	_check("WRONG_SESSION_COMBAT_SNAPSHOT_REJECTED", main.combat_authority_client.project_combat_snapshot(wrong_session).get("reason") == "COMBAT_SNAPSHOT_SESSION_MISMATCH")
	var forged_local: Dictionary = bridge.build_command_envelope("REQUEST_ATTACK", {"target_ref": selected_before, "damage": 999})
	_check("CLIENT_FORGED_DAMAGE_REJECTED", forged_local.get("reason") == "CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN")
	var forged_start: int = _results.size()
	_check("FORGED_CRITICAL_SENT_FOR_SERVER_REJECTION", bridge.submit_command("REQUEST_ATTACK", {"target_ref": selected_before, "critical": true}, _unique_ref("FORGED_CRIT")).get("status") == "PASS")
	var forged_result: Dictionary = await _wait_for_command_result("REQUEST_ATTACK", "", forged_start)
	_check("SERVER_REJECTS_CLIENT_CRITICAL", forged_result.get("reason") == "UNEXPECTED_COMMAND_PARAM", JSON.stringify(forged_result))

	var contract: Dictionary = main.combat_authority_client.contract_snapshot()
	_check("NO_GDSCRIPT_DAMAGE_AUTHORITY", contract.get("damage_authority") == false)
	_check("NO_GDSCRIPT_HIT_CRIT_AUTHORITY", contract.get("hit_authority") == false and contract.get("critical_authority") == false)
	_check("NO_GDSCRIPT_COOLDOWN_DEATH_XP", contract.get("cooldown_authority") == false and contract.get("death_authority") == false and contract.get("xp_authority") == false)
	# A non-lethal attack must produce no physical output at all. Enemy physical output
	# is the defeated actor's own Bag, dropped by the Stage16A authority on defeat.
	_check("NON_LETHAL_NO_PHYSICAL_OUTPUT", first.get("enemy_physical_output") == null and first.get("enemy_loot_authority_status") == "NO_DEFEAT_THIS_ATTACK")
	_check("NO_GDSCRIPT_ENEMY_LOOT_AUTHORITY", first.get("enemy_defeated") == false and contract.get("loot_authority") != true)

	# Stage17 C0 forbids moving a target Node and treating that local transform as
	# territorial truth. Establish the far scenario by moving the PLAYER through the
	# real authority instead; ALPHA remains bound to movement.state throughout.
	var alpha_binding: Dictionary = main.interaction_spatial_binding_registry.authoritative_target_local_position(alpha.target_ref)
	var alpha_local_position: Vector3 = alpha_binding.get("local_position", Vector3.INF)
	var attack_range_before_chase: float = float(alpha.get_meta("authority_attack_range_m", 0.0))
	var far_player_position: Vector3 = Vector3.INF
	var far_move: Dictionary = {}
	var far_authority_result: Dictionary = {}
	var visual_far_position_reached := false
	# Navmesh validity alone cannot predict which direction is blocked by another
	# projected actor's collision. Try a bounded set of explicit authority destinations
	# and retain the first whose local presentation also arrives; this is setup for the
	# historical chase branch, never a per-frame chase loop.
	for candidate: Vector3 in _valid_far_player_destinations(alpha_local_position, attack_range_before_chase):
		var far_move_start: int = _results.size()
		var candidate_move: Dictionary = main.player.request_move(candidate)
		var candidate_result: Dictionary = await _wait_for_command_result("MOVE_TO_POINT", "", far_move_start)
		if (
			candidate_move.get("status") == "PASS"
			and candidate_move.get("transport_submitted") == true
			and candidate_result.get("status") == "PASS"
			and await _wait_for_visual_position(candidate)
		):
			far_player_position = candidate
			far_move = candidate_move
			far_authority_result = candidate_result
			visual_far_position_reached = true
			break
		main.player.stop_local_prediction()
	var scenario_stable: bool = (
		far_move.get("status") == "PASS"
		and far_move.get("transport_submitted") == true
		and far_authority_result.get("status") == "PASS"
		and visual_far_position_reached
	)
	_check(
		"FAR_TARGET_SCENARIO_STABLE_BEFORE_CHASE",
		scenario_stable,
		JSON.stringify({"move": far_move, "authority_result": far_authority_result}),
	)
	main.combat_authority_client.clear_client_request_tracking()
	var current_alpha_binding: Dictionary = main.interaction_spatial_binding_registry.authoritative_target_local_position(alpha.target_ref)
	var current_alpha_position: Vector3 = current_alpha_binding.get("local_position", Vector3.INF)
	var distance_before_chase: float = main.player.global_position.distance_to(current_alpha_position)
	_check(
		"FAR_TARGET_DISTANCE_CONFIRMED_BEFORE_CHASE",
		current_alpha_position != Vector3.INF and distance_before_chase > attack_range_before_chase,
		"distance=%f attack_range=%f position=%s" % [distance_before_chase, attack_range_before_chase, current_alpha_position],
	)
	var chase_result_start: int = _results.size()
	var chase: Dictionary = main.combat_authority_client.begin_attack(alpha, "AUTHORITY_GATE_FAR_CHASE")
	_check("FAR_TARGET_STARTS_LOCAL_CHASE", chase.get("status") == "PASS" and chase.get("intent") == "CHASE_ATTACK_PENDING", JSON.stringify(chase))
	_check("FAR_TARGET_NOT_REMOTE_ATTACKED", chase.get("attack_requested") == false and chase.get("remote_attack") == false)
	_check("CHASE_USES_NAVIGATION", chase.get("movement_result", {}).get("status") == "PASS")
	_check("CHASE_PRESERVES_TARGET_REF", main.selected_target_ref() == selected_before)
	main.combat_authority_client.clear_client_request_tracking()
	# The combat intent is cancelled for this regression probe, but its single
	# authoritative approach command must still be drained before the next scenario.
	# This prevents a later snapshot/result from crossing into the Ground Loot proof.
	if chase.get("movement_result", {}).get("transport_submitted") == true:
		await _wait_for_command_result("MOVE_TO_POINT", "", chase_result_start)
	main.player.stop_local_prediction()
	await _wait_physics_frames(2)
	# --- G16B-05: ENEMY physical output as Ground Loot -----------------------
	# The non-lethal case above proves an attack that does not defeat creates no drop.
	# This proves the other side of the same rule: an authoritative defeat produces a
	# real ENEMY Ground Loot entry that reaches inventory only through a pickup.
	await _prove_enemy_ground_loot(bridge, attack_target)

	_check("BRIDGE_FINAL_READY", await _wait_for_bridge_ready(bridge))
	_check("EXPECTED_SERVER_REJECTION_RECORDED", _rejections.has("ATTACK_COOLDOWN") and _rejections.has("UNEXPECTED_COMMAND_PARAM"))
	await _finish()


func _prove_enemy_ground_loot(bridge: AndromedaRuntimeBridge, target: AndromedaInteractionTarget) -> void:
	var target_ref: String = target.target_ref
	var baseline: Dictionary = await _fresh_snapshot(bridge)

	# 1. Real attacks through the authority until it reports the defeat.
	var defeat: Dictionary = {}
	for attempt: int in range(1, 41):
		await get_tree().create_timer(1.05).timeout
		var attack: Dictionary = await _await_command(
			bridge, "REQUEST_ATTACK", {"target_ref": target_ref}, "LETHAL-%d" % attempt
		)
		if attack.is_empty():
			break
		if attack.get("status") == "PASS" and bool(attack.get("enemy_defeated", false)):
			defeat = attack
			break
	_check("ENEMY_DEFEAT_AUTHORITATIVE_PASS", defeat.get("status") == "PASS" and bool(defeat.get("enemy_defeated", false)), JSON.stringify(defeat.get("reason", "NO_DEFEAT_REACHED")))
	if defeat.is_empty():
		return

	# 2. The authority produced the physical output, and it is Ground Loot.
	var output: Dictionary = defeat.get("enemy_physical_output", {}) if defeat.get("enemy_physical_output") is Dictionary else {}
	_check("ENEMY_PHYSICAL_OUTPUT_CREATED", output.get("source_kind") == "ENEMY" and output.get("output_form") == "GROUND_LOOT", JSON.stringify(output))
	var drops: Array = output.get("drops", []) as Array
	if drops.is_empty() or not drops[0] is Dictionary:
		_check("ENEMY_DROP_STABLE_TARGET_REF", false, "no drop in enemy physical output")
		return
	var first_drop: Dictionary = drops[0]
	var drop_ref: String = str(first_drop.get("drop_ref", ""))
	var item_ref: String = str(first_drop.get("item_ref", ""))
	var drop_payload: Dictionary = first_drop.get("drop", {}) if first_drop.get("drop") is Dictionary else {}
	_check("ENEMY_DROP_STABLE_TARGET_REF", drop_ref.begins_with("DROP-S16A-") and str(drop_payload.get("drop_ref", "")) == drop_ref, drop_ref)
	_check("ENEMY_DROP_INITIAL_UNSETTLED", drop_payload.get("settled") == false, JSON.stringify(drop_payload.get("settled")))
	_check("ENEMY_OUTPUT_PHYSICAL_WORLD_FIRST", output.get("physical_world_first") == true and output.get("direct_to_inventory") == false)

	# 3. Nothing reached the inventory just because the enemy died.
	var before_quantity: int = _stack_quantity(baseline, item_ref)
	var after_defeat: Dictionary = await _fresh_snapshot(bridge)
	_check("ENEMY_NO_INVENTORY_GRANT_BEFORE_PICKUP", _stack_quantity(after_defeat, item_ref) == before_quantity, "before=%d after_defeat=%d" % [before_quantity, _stack_quantity(after_defeat, item_ref)])

	# 4. The client projects it as Ground Loot.
	var loot: AndromedaGroundLoot = null
	var project_deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < project_deadline:
		loot = main.ground_loot_client.ground_loot_for_ref(drop_ref)
		if loot != null:
			break
		await get_tree().process_frame
	_check("ENEMY_GROUND_LOOT_CLIENT_PROJECTED", loot != null, drop_ref)
	if loot == null:
		return

	# 5. Report the settle observation, then require the authority to confirm it.
	var candidate: Dictionary = _drop_position(_entry_by_drop_ref(after_defeat, drop_ref))
	if candidate.is_empty():
		_check("ENEMY_DROP_AUTHORITATIVE_SETTLED", false, "no authoritative position for the enemy drop")
		return
	await _await_command(bridge, "CONFIRM_DROP_SETTLED", {
		"target_ref": drop_ref,
		"settled_position": {
			"iso_x_m": float(candidate.get("iso_x_m", 0.0)),
			"iso_y_m": float(candidate.get("iso_y_m", 0.0)),
			"altitude_m": float(candidate.get("altitude_m", 0.0)),
		},
		"reachable": true,
	}, "ENEMY-SETTLE")
	var settled_snapshot: Dictionary = {}
	var settle_deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < settle_deadline:
		settled_snapshot = await _fresh_snapshot(bridge)
		var entry: Dictionary = _entry_by_drop_ref(settled_snapshot, drop_ref)
		if entry.get("settled") == true and entry.get("reachable") == true:
			break
	var settled_entry: Dictionary = _entry_by_drop_ref(settled_snapshot, drop_ref)
	_check("ENEMY_DROP_AUTHORITATIVE_SETTLED", settled_entry.get("settled") == true, JSON.stringify(settled_entry.get("settled")))

	# 6. Stand on the drop so the authority measures a distance inside the 0.5 m rule.
	for step: int in range(1, 41):
		var moved: Dictionary = await _await_command(bridge, "MOVE_TO_POINT", {
			"iso_x_m": float(candidate.get("iso_x_m", 0.0)),
			"iso_y_m": float(candidate.get("iso_y_m", 0.0)),
			# Match the accepted Stage17 explicit-destination request budget. The
			# historical 0.25 s probe could stop short after a long real approach and
			# then incorrectly exercise pickup from its old authority position.
			"duration_s": 10.0,
			"mode": "WALK",
		}, "ENEMY-APPROACH-%d" % step)
		if moved.get("status") != "PASS" or bool(moved.get("arrived", false)):
			break

	# 7. Authoritative pickup of the same target_ref.
	var pickup_ref: String = _unique_ref("ENEMY-PICKUP")
	if bridge.submit_command("REQUEST_PICKUP", {"target_ref": drop_ref}, pickup_ref).get("status") != "PASS":
		_check("ENEMY_PICKUP_CORE_PASS", false, "pickup was not queued")
		return
	var pickup: Dictionary = await _result_for_ref(pickup_ref, 1)
	_check("ENEMY_PICKUP_CORE_PASS", pickup.get("status") == "PASS" and pickup.get("target_ref") == drop_ref, JSON.stringify(pickup))

	# 8. Inventory changed only now, and by the authoritative amount.
	var after_pickup: Dictionary = await _fresh_snapshot(bridge)
	var granted: int = int(first_drop.get("quantity", 1))
	_check("ENEMY_INVENTORY_CHANGED_ONLY_AFTER_AUTHORITY", _stack_quantity(after_pickup, item_ref) == before_quantity + granted, "before=%d after=%d granted=%d" % [before_quantity, _stack_quantity(after_pickup, item_ref), granted])
	_check("ENEMY_PICKUP_CLIENT_PROJECTED_COLLECTED", loot.authoritative_state() == "COLLECTED", loot.authoritative_state())
	_check("ENEMY_GROUND_LOOT_REMOVED_FROM_ACTIVE", _entry_by_drop_ref(after_pickup, drop_ref).is_empty() or str(_entry_by_drop_ref(after_pickup, drop_ref).get("state", "")) != "ACTIVE")

	# 9. Replay the same command_ref: suppressed, and no second grant.
	bridge.submit_command("REQUEST_PICKUP", {"target_ref": drop_ref}, pickup_ref)
	var replay: Dictionary = await _result_for_ref(pickup_ref, 2)
	_check("ENEMY_PICKUP_REPLAY_SUPPRESSED", replay.get("idempotent_replay") == true and replay.get("replay_suppressed") == true, JSON.stringify(replay))
	var after_replay: Dictionary = await _fresh_snapshot(bridge)
	_check("ENEMY_PICKUP_REPLAY_NO_SECOND_GRANT", _stack_quantity(after_replay, item_ref) == before_quantity + granted)


func _await_command(bridge: AndromedaRuntimeBridge, command: String, params: Dictionary, label: String) -> Dictionary:
	var command_ref: String = _unique_ref(label)
	if bridge.submit_command(command, params, command_ref).get("status") != "PASS":
		return {}
	return await _result_for_ref(command_ref, 1)


func _result_for_ref(command_ref: String, occurrence: int) -> Dictionary:
	## Match by command_ref, never by arrival order: the ground-loot client submits its
	## own settle confirmations into the same stream. `occurrence` separates a
	## suppressed replay from the original result.
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
			return value as Dictionary
	return {}


func _stack_quantity(snapshot: Dictionary, item_ref: String) -> int:
	## Count where the authority routes the item: with a Bag equipped the effective
	## inventory owner is the Bag and the base inventory never changes.
	var projection: Dictionary = snapshot.get("inventory_projection", {})
	var routing: Dictionary = projection.get("routing", {})
	var entries: Array = []
	if str(routing.get("source", "")) == "EQUIPPED_BAG":
		entries = (projection.get("bag", {}) as Dictionary).get("contents", [])
	else:
		entries = (projection.get("base_inventory", {}) as Dictionary).get("stacks", [])
	var total: int = 0
	for value: Variant in entries:
		if value is Dictionary and str((value as Dictionary).get("item_ref", "")) == item_ref:
			total += int((value as Dictionary).get("quantity", 0))
	return total


func _target_entry(snapshot: Dictionary, slot: String) -> Dictionary:
	for value: Variant in snapshot.get("combat_targets", []):
		if value is Dictionary and str((value as Dictionary).get("slot", "")) == slot:
			return (value as Dictionary).duplicate(true)
	return {}


func _wait_for_projected_targets(expected_common_ref: String, expected_alpha_ref: String) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		if (
			not expected_common_ref.is_empty()
			and not expected_alpha_ref.is_empty()
			and main.combat_enemy_common.target_ref == expected_common_ref
			and main.combat_enemy_alpha.target_ref == expected_alpha_ref
			and main.hud.enemy_bar_for_ref(main.combat_enemy_common.target_ref) != null
			and main.hud.enemy_bar_for_ref(main.combat_enemy_alpha.target_ref) != null
		):
			return true
		await get_tree().process_frame
	return false


func _wait_for_command_result(command: String, target_ref: String, start_index: int) -> Dictionary:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		for index: int in range(start_index, _results.size()):
			var result: Dictionary = _results[index]
			if str(result.get("command", "")) != command:
				continue
			if not target_ref.is_empty() and str(result.get("target_ref", "")) != target_ref:
				continue
			return result.duplicate(true)
		await get_tree().process_frame
	return {}


func _wait_for_bridge_ready(bridge: AndromedaRuntimeBridge) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		if bridge.connection_state().get("state") == AndromedaRuntimeBridge.STATE_READY:
			return true
		await get_tree().process_frame
	return false


func _valid_far_player_destinations(target_local: Vector3, attack_range_m: float) -> Array[Vector3]:
	var valid: Array[Vector3] = []
	if target_local == Vector3.INF or attack_range_m <= 0.0:
		return valid
	var radius: float = attack_range_m + 1.25
	var away_from_target := Vector2(
		main.player.global_position.x - target_local.x,
		main.player.global_position.z - target_local.z
	)
	if away_from_target.length_squared() <= 0.000001:
		away_from_target = Vector2.RIGHT
	away_from_target = away_from_target.normalized()
	for direction: Vector2 in [away_from_target, Vector2.RIGHT, Vector2.LEFT, Vector2.UP, Vector2.DOWN]:
		var candidate := Vector3(
			target_local.x + direction.x * radius,
			target_local.y,
			target_local.z + direction.y * radius
		)
		if main.player.validate_destination(candidate).get("status") == "PASS":
			if not valid.has(candidate):
				valid.append(candidate)
	return valid


func _wait_for_visual_position(destination: Vector3) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		var error := Vector2(
			main.player.global_position.x,
			main.player.global_position.z
		).distance_to(Vector2(destination.x, destination.z))
		if error <= main.player.presentation_reconciliation_tolerance_m():
			return true
		await get_tree().physics_frame
	return false


func _wait_for_size(values: Array, expected: int) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while values.size() < expected and Time.get_ticks_usec() < deadline:
		await get_tree().process_frame
	return values.size() >= expected


func _wait_physics_frames(count: int) -> void:
	for _index: int in range(count):
		await get_tree().physics_frame


func _mouse_button(button: MouseButton, position: Vector2) -> InputEventMouseButton:
	var event := InputEventMouseButton.new()
	event.button_index = button
	event.pressed = true
	event.position = position
	return event


func _key_event(keycode: Key) -> InputEventKey:
	var event := InputEventKey.new()
	event.keycode = keycode
	event.pressed = true
	return event


func _unique_ref(label: String) -> String:
	return "GODOT-COMBAT-%s-%d" % [label, Time.get_ticks_usec()]


func _check(label: String, condition: bool, detail: String = "") -> void:
	_checks += 1
	if not condition:
		_failures.append(label if detail.is_empty() else "%s:%s" % [label, detail])


func _finish() -> void:
	await _wait_physics_frames(2)
	var passed: int = _checks - _failures.size()
	var status: String = "PASS" if _failures.is_empty() else "FAIL"
	var summary := {
		"gate": "AUTHORITY_COMBAT_ROUNDTRIP",
		"status": status,
		"checks": _checks,
		"passed": passed,
		"failed": _failures.size(),
		"failures": _failures,
		"backend": "REAL_STAGE16A_AUTHORITY",
		"fixture_authority": false,
		"enemy_physical_output_authority": "STAGE16A_BAG_DEATH_DROP_OF_CARRIED_CONTENTS",
		"enemy_loot_table_invented": false,
	}
	print("ANDROMEDA_STAGE16B_AUTHORITY_COMBAT_SUMMARY: ", JSON.stringify(summary))
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_AUTHORITY_COMBAT_GATE: PASS")
		await get_tree().create_timer(8.0).timeout
		get_tree().quit(0)
	else:
		push_error("ANDROMEDA_STAGE16B_AUTHORITY_COMBAT_GATE: FAIL %s" % JSON.stringify(_failures))
		await get_tree().create_timer(8.0).timeout
		get_tree().quit(1)
