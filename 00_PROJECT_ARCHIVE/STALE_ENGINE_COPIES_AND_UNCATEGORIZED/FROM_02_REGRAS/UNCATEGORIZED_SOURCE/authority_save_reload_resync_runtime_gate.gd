extends Node

## G16B-17 -- AUTHORITATIVE SAVE / AUTOSAVE / RELOAD / RESYNC -- real Godot
## observation. Dedicated, isolated from authority_save_death_runtime_gate.gd
## (194/194, death/bag/CLOTHES/water-TTL-reset focus) and from
## authority_npc_bag_ownership_runtime_gate.gd (G16B-28).
##
## Literal contract (ARPG_STAGE16B_GODOT_ACCEPTANCE_MATRIX_V0_8_0.json, G16B-17):
## "Save/reload preserves player, world, Ground Loot, Auto Pickup,
##  quest/economy, water exposure, bag ownership/state and death recovery
##  state."
##
## player / world / Auto Pickup / bag ownership+state / death recovery are
## PASS_ALREADY via existing evidence (authority_save_death_runtime_gate
## 194/194, authority_npc_bag_ownership_runtime_gate 62/62x2,
## authority_water_ttl_runtime_gate A-E) and are only lightly re-touched here
## (Auto Pickup is reused AS the mutation-after-save probe; player/world get
## a cheap coherence check). This gate closes what those never exercised:
## quest, economy, water exposure and REQUEST_AUTOSAVE, using only real,
## already-transported commands:
##   ACCEPT_QUEST, REQUEST_GATHER, CONFIRM_DROP_SETTLED, REQUEST_TRADE_QUOTE,
##   EXECUTE_TRADE, REPORT_WATER_TRAVERSAL, REPORT_WATER_EXHAUSTION,
##   SET_AUTO_PICKUP, REQUEST_SAVE, REQUEST_AUTOSAVE, REQUEST_RELOAD_RESYNC.
##
## QUEST PROGRESSION TRANSPORT GAP (explicit, authorized, non-blocking):
## arpg_narrative_culture_core.py::submit_objective()/turn_in_quest() are
## real core functions with zero callers anywhere in the backend -- no
## Godot-reachable command exists for quest progress/turn-in. Per explicit
## authorization this round, "quest" is proven at the real, non-default
## ACCEPT_QUEST/ACTIVE level (state=ACTIVE, real objective_states, never a
## fixture, never fabricated progress). This gate does NOT create
## SUBMIT_OBJECTIVE/TURN_IN_QUEST. Registered as:
##   QUEST_PROGRESSION_TRANSPORT_GAP_NON_BLOCKING_FOR_G16B_17
##
## WATER EXPOSURE ORDERING (deliberate, found the hard way): the persisted
## field is arpg_stage16a_water_exhaustion.zero_stamina_water_s, which is
## ONLY ever advanced by a live REPORT_WATER_EXHAUSTION(in_water=true) call
## -- it is not a passive background timer. That call always computes delta
## against REAL wall-clock time since the previous tick, with NO way to
## "pause" it (in_water=false or stamina>0 immediately zero it -- there is
## no non-destructive read). EXHAUSTION_GRACE_S is a fixed 4.0s; an
## authoritative REQUEST_RELOAD_RESYNC (full SQLite file swap + engine
## reboot) was observed taking >5s in this environment. Sandwiching the
## exhaustion probe around the FULL quest/ground-loot/economy/auto-pickup
## bundle's save+reload (as first attempted) reliably pushed real elapsed
## time past the grace window and triggered a genuine, unintended death,
## which then cascaded into the save_reload_client's own state machine
## being left mid-transition for the following commands. The water-exposure
## probe therefore runs LAST, in its own minimal, isolated save/reload pair
## (immediately after capturing the pre-save value: SAVE -> RELOAD -> tick),
## after every other clause has already been verified -- so even an
## occasional slow reload crossing into a real, correctly-triggered defeat
## cannot contaminate anything checked earlier, and is not treated as a
## required "still not destructive" outcome (that requirement is the
## pre-save capture's alone, per the task's own literal wording).

const SESSION_REF := "GODOT-AUTHORITY-SAVE-RELOAD-RESYNC-V080"
const WAIT_TIMEOUT_S := 90.0
const SAVE_SLOT := "g17manual"
const AUTOSAVE_SLOT := "autosave"  # andromeda_authority_adapter.py::AndromedaSaveReloadClient
                                     # .request_autosave() hardcodes this slot -- distinct from
                                     # manual save's caller-chosen slot_ref, confirmed by direct read.

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _checks: int = 0
var _failures: Array[String] = []
var _bind_results: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []
var _results: Array[Dictionary] = []
var _rejections: Array[String] = []


func _ready() -> void:
	await _run_gate()


func _run_gate() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_check("SESSION_AUTOLOAD", session != null)
	_check("BRIDGE_AUTOLOAD", bridge != null)
	_check("MAIN_RUNTIME_PRESENT", main != null and main.save_reload_client != null and main.ground_loot_client != null)
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
	var player_ref: String = str(initial.get("identity", {}).get("profile_ref", ""))
	var enabled: Array = _bind_results[0].get("enabled_commands", [])
	for command: String in [
		"ACCEPT_QUEST", "REQUEST_GATHER", "CONFIRM_DROP_SETTLED",
		"REQUEST_TRADE_QUOTE", "EXECUTE_TRADE",
		"REPORT_WATER_TRAVERSAL", "REPORT_WATER_EXHAUSTION",
		"SET_AUTO_PICKUP", "REQUEST_SAVE", "REQUEST_AUTOSAVE", "REQUEST_RELOAD_RESYNC",
	]:
		_check("COMMAND_ENABLED_%s" % command, enabled.has(command), JSON.stringify(enabled))

	# =====================================================================
	# 1) QUEST -- ACCEPT_QUEST only. Real seeded Stage12 template, never
	#    hardcoded: taken from the live quest_projection.offers (an
	#    un-accepted template real to THIS world).
	# =====================================================================
	var offers: Array = (initial.get("quest_projection", {}) as Dictionary).get("offers", [])
	var quest_ref: String = ""
	if not offers.is_empty() and offers[0] is Dictionary:
		quest_ref = str((offers[0] as Dictionary).get("quest_ref", ""))
	_check("G17_QUEST_OFFER_FOUND_AUTHORITATIVELY", not quest_ref.is_empty(), JSON.stringify(offers))
	if quest_ref.is_empty():
		await _finish()
		return

	var accept_ref: String = _unique_ref("ACCEPT-QUEST")
	var accept_result: Dictionary = await _await_command(bridge, "ACCEPT_QUEST", {"quest_ref": quest_ref}, "ACCEPT-QUEST", accept_ref)
	_check("G17_QUEST_ACCEPT_COMMAND_AUTHORITATIVE", accept_result.get("server_authoritative") == true, JSON.stringify(accept_result))
	_check("G17_QUEST_ACCEPT_PASS", accept_result.get("status") == "PASS", JSON.stringify(accept_result))
	var accepted_quest: Dictionary = accept_result.get("quest", {})
	_check("G17_QUEST_ACTIVE_BEFORE_SAVE", str(accepted_quest.get("state", "")) == "ACTIVE", JSON.stringify(accepted_quest))
	var objective_states_before: Dictionary = accepted_quest.get("objective_states", {})
	_check("G17_QUEST_OBJECTIVES_REAL_BEFORE_SAVE", not objective_states_before.is_empty(), JSON.stringify(objective_states_before))
	_check(
		"G17_QUEST_STATE_NON_DEFAULT",
		str(accepted_quest.get("state", "")) == "ACTIVE" and not objective_states_before.is_empty(),
		JSON.stringify(accepted_quest),
	)
	_progress("QUEST_ACCEPTED", {"quest_ref": quest_ref, "state": accepted_quest.get("state", ""), "objectives": objective_states_before})

	# =====================================================================
	# 2) GROUND LOOT -- REQUEST_GATHER + CONFIRM_DROP_SETTLED. Deliberately
	#    NO pickup: must stay ACTIVE across the save/reload below.
	# =====================================================================
	var mining_node_ref: String = ""
	var node_zone_ref: String = ""
	for node: Variant in initial.get("gathering_nodes", []):
		if not node is Dictionary:
			continue
		var n: Dictionary = node
		if str(n.get("state", "")) == "AVAILABLE":
			mining_node_ref = str(n.get("target_ref", ""))
			node_zone_ref = str(n.get("zone_ref", ""))
			break
	_check("G17_GATHERING_NODE_FOUND_AUTHORITATIVELY", not mining_node_ref.is_empty(), JSON.stringify(initial.get("gathering_nodes", [])))
	if mining_node_ref.is_empty():
		await _finish()
		return

	var gather_result: Dictionary = await _await_command(bridge, "REQUEST_GATHER", {
		"target_ref": mining_node_ref, "requested_units": 1,
	}, "GATHER")
	_check("G17_GROUND_LOOT_CREATED_AUTHORITATIVELY", gather_result.get("status") == "PASS", JSON.stringify(gather_result))
	var physical_output: Dictionary = gather_result.get("physical_output", {})
	var drop_ref: String = str(physical_output.get("target_ref", ""))
	var drop_item_ref: String = str(physical_output.get("item_ref", ""))
	var drop_quantity: int = int(physical_output.get("quantity", -1))
	var candidate_position: Dictionary = physical_output.get("candidate_position", {})
	_check("G17_GROUND_LOOT_REF_CAPTURED", not drop_ref.is_empty(), JSON.stringify(physical_output))
	if drop_ref.is_empty():
		await _finish()
		return

	var settle_result: Dictionary = await _await_command(bridge, "CONFIRM_DROP_SETTLED", {
		"target_ref": drop_ref, "settled_position": candidate_position, "reachable": true,
	}, "SETTLE")
	_check("G17_GROUND_LOOT_SETTLED_AUTHORITATIVE", settle_result.get("status") == "PASS", JSON.stringify(settle_result))

	var ground_loot_snapshot_before: Dictionary = await _fresh_snapshot(bridge)
	var drop_before: Dictionary = _ground_loot_entry(ground_loot_snapshot_before, drop_ref)
	_check("G17_GROUND_LOOT_ACTIVE_BEFORE_SAVE", str(drop_before.get("state", "")) == "ACTIVE", JSON.stringify(drop_before))
	_progress("GROUND_LOOT_CREATED", {"drop_ref": drop_ref, "item_ref": drop_item_ref, "quantity": drop_quantity})

	# =====================================================================
	# 3) ECONOMY -- REQUEST_TRADE_QUOTE -> EXECUTE_TRADE (real BUY). Balance
	#    mutation is unambiguous and server-priced end to end.
	# =====================================================================
	var vendor_stock: Array = ground_loot_snapshot_before.get("vendor_stock", [])
	var vendor_ref: String = ""
	var vendor_item_ref: String = ""
	if not vendor_stock.is_empty() and vendor_stock[0] is Dictionary:
		var vendor: Dictionary = vendor_stock[0]
		vendor_ref = str(vendor.get("vendor_ref", ""))
		var items: Array = vendor.get("items", [])
		if not items.is_empty() and items[0] is Dictionary:
			vendor_item_ref = str((items[0] as Dictionary).get("item_ref", ""))
	_check("G17_VENDOR_AND_ITEM_FOUND_AUTHORITATIVELY", not vendor_ref.is_empty() and not vendor_item_ref.is_empty(), JSON.stringify(vendor_stock))
	if vendor_ref.is_empty() or vendor_item_ref.is_empty():
		await _finish()
		return

	var balance_before: float = float((ground_loot_snapshot_before.get("economy_projection", {}) as Dictionary).get("wallet", {}).get("balance", -1.0))
	var quote_result: Dictionary = await _await_command(bridge, "REQUEST_TRADE_QUOTE", {
		"vendor_ref": vendor_ref, "item_ref": vendor_item_ref, "direction": "BUY", "quantity": 1,
	}, "QUOTE")
	_check("G17_ECONOMY_QUOTE_AUTHORITATIVE", quote_result.get("status") == "PASS", JSON.stringify(quote_result))
	var quote_ref: String = str(quote_result.get("quote_ref", ""))
	var total_price: float = float(quote_result.get("total_price", -1.0))
	_check("G17_ECONOMY_QUOTE_AFFORDABLE", quote_ref != "" and total_price >= 0.0 and total_price <= balance_before, "total=%f balance=%f" % [total_price, balance_before])

	var trade_ref: String = _unique_ref("TRADE")
	var trade_result: Dictionary = await _await_command(bridge, "EXECUTE_TRADE", {
		"quote_ref": quote_ref,
		"event_ref": trade_ref,
		"confirmation_ref": trade_ref,
		"vendor_ref": vendor_ref,
		"item_ref": vendor_item_ref,
		"direction": "BUY",
		"quantity": 1,
		"explicit_user_confirmation": true,
	}, "EXECUTE-TRADE")
	_check("G17_ECONOMY_TRANSACTION_AUTHORITATIVE", trade_result.get("result") == "ACCEPTED", JSON.stringify(trade_result))

	var economy_snapshot_before_save: Dictionary = await _fresh_snapshot(bridge)
	var balance_after_trade: float = float((economy_snapshot_before_save.get("economy_projection", {}) as Dictionary).get("wallet", {}).get("balance", -1.0))
	_check("G17_ECONOMY_NON_DEFAULT_BEFORE_SAVE", balance_after_trade != balance_before, "before=%f after=%f" % [balance_before, balance_after_trade])
	_progress("ECONOMY_TRANSACTION_DONE", {"balance_before": balance_before, "balance_after_trade": balance_after_trade, "total_price": total_price})

	# World identity (light touch only -- Living SYSTEMIC depth belongs to
	# G16B-09, not here): the player's own current zone_ref, real and
	# authoritative, taken from the gathering node discovered above.
	var world_zone_before: String = node_zone_ref
	_check("G17_WORLD_PRESENT_BEFORE_SAVE", not world_zone_before.is_empty())

	# =====================================================================
	# 4) MANUAL SAVE (real) -- bundle so far: quest ACTIVE, Ground Loot
	#    ACTIVE, wallet mutated. Water exposure is deliberately NOT part of
	#    this bundle -- see the file-level comment on ordering.
	# =====================================================================
	var first_save: Dictionary = await _request_and_wait_save(SAVE_SLOT)
	_check("G17_MANUAL_SAVE_COMMAND_AUTHORITATIVE", first_save.get("server_authoritative") == true, JSON.stringify(first_save))
	_check("G17_MANUAL_SAVE_ACCEPTED", first_save.get("result") == "CONFIRMED", JSON.stringify(first_save))
	_check("G17_MANUAL_SAVE_REFERENCE_VALID", not str(first_save.get("save_ref", "")).is_empty() and int(first_save.get("save_sequence", -1)) >= 0, JSON.stringify(first_save))

	# =====================================================================
	# 5) MUTATION AFTER SAVE -- Auto Pickup, the same proven pattern already
	#    used by authority_save_death_runtime_gate.gd. Real, authoritative,
	#    reversible by a real reload.
	# =====================================================================
	var auto_pickup_before_save: bool = main.ground_loot_client.auto_pickup_enabled()
	var desired_flip: bool = not auto_pickup_before_save
	var mutation_start: int = _results.size()
	main.hud.inventory_shell.set_auto_pickup_visual(desired_flip, true)
	var mutation_result: Dictionary = await _wait_for_command("SET_AUTO_PICKUP", mutation_start)
	_check("G17_AUTO_PICKUP_POST_SAVE_MUTATION_REAL", mutation_result.get("status") == "PASS", JSON.stringify(mutation_result))
	if not await _wait_for_auto_pickup(desired_flip):
		_failures.append("AUTO_PICKUP_MUTATION_NOT_PROJECTED")

	# =====================================================================
	# 6) REQUEST_RELOAD_RESYNC (real).
	# =====================================================================
	var restored: Dictionary = await _request_and_wait_reload(SAVE_SLOT)
	_check("G17_RELOAD_RESYNC_COMMAND_AUTHORITATIVE", not restored.is_empty(), JSON.stringify(restored))
	_check("G17_RELOAD_RESYNC_ACCEPTED", restored.get("status") == "PASS", JSON.stringify(restored))
	_check(
		"G17_RESYNC_SIGNAL_REAL",
		restored.get("resync_before_ready") == true and restored.get("restore_fabricated_by_godot") == false,
		JSON.stringify(restored),
	)
	if restored.get("status") != "PASS":
		await _finish()
		return

	var after_reload_snapshot: Dictionary = await _fresh_snapshot(bridge)

	# --- Quest after reload. ----------------------------------------------
	var quests_after: Array = (after_reload_snapshot.get("quest_projection", {}) as Dictionary).get("quests", [])
	var quest_matches: Array = quests_after.filter(func(q: Variant) -> bool: return q is Dictionary and str((q as Dictionary).get("quest_ref", "")) == quest_ref)
	_check("G17_QUEST_PRESERVED_AFTER_RELOAD", quest_matches.size() >= 1, JSON.stringify(quests_after))
	_check("G17_QUEST_NO_DUPLICATION", quest_matches.size() == 1, JSON.stringify(quests_after))
	if quest_matches.size() >= 1:
		var quest_after: Dictionary = quest_matches[0]
		_check("G17_QUEST_SAME_REF_AFTER_RELOAD", str(quest_after.get("quest_ref", "")) == quest_ref)
		var objectives_after: Dictionary = {}
		for objective: Variant in quest_after.get("objectives", []):
			if objective is Dictionary:
				objectives_after[str((objective as Dictionary).get("objective_ref", ""))] = str((objective as Dictionary).get("state", ""))
		var objectives_match: bool = objectives_after.size() == objective_states_before.size()
		if objectives_match:
			for key: String in objective_states_before.keys():
				if str(objectives_after.get(key, "")) != str(objective_states_before[key]):
					objectives_match = false
					break
		_check("G17_QUEST_OBJECTIVES_PRESERVED_AFTER_RELOAD", objectives_match, "before=%s after=%s" % [JSON.stringify(objective_states_before), JSON.stringify(objectives_after)])
		_check("G17_QUEST_STATE_STILL_ACTIVE_AFTER_RELOAD", str(quest_after.get("state", "")) == "ACTIVE", JSON.stringify(quest_after))

	# --- Ground Loot after reload. -----------------------------------------
	var all_ground_loot_after: Array = after_reload_snapshot.get("ground_loot", [])
	var drop_matches: Array = all_ground_loot_after.filter(func(d: Variant) -> bool: return d is Dictionary and str((d as Dictionary).get("drop_ref", "")) == drop_ref)
	_check("G17_GROUND_LOOT_PRESERVED_AFTER_RELOAD", drop_matches.size() >= 1, JSON.stringify(all_ground_loot_after))
	_check("G17_GROUND_LOOT_NO_DUPLICATION", drop_matches.size() == 1, JSON.stringify(all_ground_loot_after))
	if drop_matches.size() >= 1:
		var drop_after: Dictionary = drop_matches[0]
		_check("G17_GROUND_LOOT_SAME_REF_AFTER_RELOAD", str(drop_after.get("drop_ref", "")) == drop_ref)
		_check("G17_GROUND_LOOT_STATE_PRESERVED", str(drop_after.get("state", "")) == "ACTIVE", JSON.stringify(drop_after))
		_check(
			"G17_GROUND_LOOT_IDENTITY_PRESERVED",
			str(drop_after.get("item_ref", "")) == drop_item_ref and int(drop_after.get("quantity", -1)) == drop_quantity,
			JSON.stringify(drop_after),
		)

	# --- Economy after reload. ---------------------------------------------
	var balance_after_reload: float = float((after_reload_snapshot.get("economy_projection", {}) as Dictionary).get("wallet", {}).get("balance", -1.0))
	_check("G17_ECONOMY_PRESERVED_AFTER_RELOAD", balance_after_reload >= 0.0)
	_check("G17_ECONOMY_SAVED_BALANCE_RESTORED", is_equal_approx(balance_after_reload, balance_after_trade), "saved=%f restored=%f" % [balance_after_trade, balance_after_reload])

	# --- Auto Pickup restored to the value at save time (not the post-save
	# mutation). Read from the RELOAD result's own authoritative
	# restore_snapshot.profile_preference.auto_pickup, not the client's
	# locally-cached ground_loot_client.auto_pickup_enabled() -- that cache
	# is only refreshed by the bridge's own periodic background snapshot
	# polling, which is a real, independent, eventually-consistent
	# presentation channel, not the server's authoritative signal, and
	# racing it against a real ~multi-second reload duration is exactly the
	# kind of frágil timing dependency this round already ruled out once
	# for the water-exposure probe. -----------------------------------------
	var restored_auto_pickup: Variant = restored.get("restore_snapshot", {}).get("profile_preference", {}).get("auto_pickup", null)
	_check("G17_AUTO_PICKUP_RESTORED_FROM_SAVE", restored_auto_pickup == auto_pickup_before_save, "expected=%s actual=%s" % [auto_pickup_before_save, restored_auto_pickup])

	# --- World coherence (light touch, G16B-09 territory left alone). ------
	var world_zone_after: String = str(restored.get("restore_snapshot", {}).get("world", {}).get("zone_ref", ""))
	_check("G17_WORLD_PRESENT_AFTER_RELOAD", not world_zone_after.is_empty(), JSON.stringify(restored.get("restore_snapshot", {}).get("world", {})))
	_check("G17_WORLD_IDENTITY_OR_REVISION_COHERENT", world_zone_after == world_zone_before, "before=%s after=%s" % [world_zone_before, world_zone_after])

	# --- Player (cheap reuse -- deep proof already lives in the 194-check
	# save/death gate). -------------------------------------------------------
	var player_ref_after: String = str(after_reload_snapshot.get("identity", {}).get("profile_ref", ""))
	_check("G17_PLAYER_REF_STABLE_AFTER_RELOAD", player_ref_after == player_ref, "before=%s after=%s" % [player_ref, player_ref_after])

	# =====================================================================
	# 7) REPEATED RELOAD -- section 11 draws a real distinction this gate
	#    honors explicitly:
	#
	#    A. Repeating the EXACT SAME restore (same slot, no new
	#       REQUEST_SAVE in between -> backend's own save_sequence for this
	#       slot is unchanged) IS a literal replay.
	#       andromeda_authority_adapter.py::_request_reload_resync() has no
	#       replay check of its own -- it performs the DB swap and returns
	#       PASS with a fresh restore_snapshot every time the slot verifies
	#       -- so the rejection is entirely save_reload_client.gd's OWN
	#       anti-replay guard inside project_restore_snapshot()
	#       (OLDER_OR_DUPLICATE_SAVE_SEQUENCE, since the slot's save_sequence
	#       did not advance). That guard must NOT be weakened. Now that
	#       save_reload_client.gd releases RELOAD_PENDING on a correlated
	#       rejection instead of staying stuck (this round's fix), this case
	#       goes through the NORMAL client -> bridge -> backend ->
	#       restore_snapshot -> client rejection path end to end, exactly
	#       like every other reload in this gate -- no bridge bypass
	#       remains anywhere in G17.
	#
	#    B. A genuinely NEW REQUEST_RELOAD_RESYNC for the SAME slot (this
	#       gate manufactures one cheaply via another real, unmutated
	#       REQUEST_SAVE first, so the slot's own save_sequence legitimately
	#       advances) is not a replay at all -- the exact per-slot-guard
	#       scenario the prior round's fix targets -- and goes through the
	#       normal client -> bridge -> backend -> restore_snapshot -> client
	#       projection path end to end.
	# =====================================================================
	var replay_projected_count: Array = [0]
	var replay_listener := func(_r: Dictionary) -> void: replay_projected_count[0] += 1
	main.save_reload_client.restore_projected.connect(replay_listener)
	var replay_restored: Dictionary = await _request_and_wait_reload(SAVE_SLOT)
	main.save_reload_client.restore_projected.disconnect(replay_listener)
	_check("G17_EXACT_REPLAY_ACCEPTED_BY_BACKEND", replay_restored.get("status") == "PASS", JSON.stringify(replay_restored))
	# The backend itself has no replay guard (see comment above), so its own
	# command result is PASS -- the client's internal projection is what
	# refuses to re-apply it. restore_projected only fires on a genuinely
	# accepted projection, so zero fires here proves the client-side guard
	# fired instead of silently re-applying.
	_check(
		"G17_DUPLICATE_RELOAD_VIA_CLIENT_REJECTED",
		replay_projected_count[0] == 0,
		"restore_projected_fired=%d" % replay_projected_count[0],
	)
	_check(
		"G17_DUPLICATE_RELOAD_CLIENT_RECOVERS_FROM_PENDING",
		main.save_reload_client.state() == AndromedaSaveReloadClient.STATE_READY,
		"state=%s" % main.save_reload_client.state(),
	)
	var replay_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var replay_quest_matches: Array = (replay_snapshot.get("quest_projection", {}) as Dictionary).get("quests", []).filter(
		func(q: Variant) -> bool: return q is Dictionary and str((q as Dictionary).get("quest_ref", "")) == quest_ref
	)
	var replay_drop_matches: Array = (replay_snapshot.get("ground_loot", []) as Array).filter(
		func(d: Variant) -> bool: return d is Dictionary and str((d as Dictionary).get("drop_ref", "")) == drop_ref
	)
	_check("G17_EXACT_REPLAY_NO_DUPLICATION", replay_quest_matches.size() == 1 and replay_drop_matches.size() == 1, "quests=%d drops=%d" % [replay_quest_matches.size(), replay_drop_matches.size()])

	# Section 7 of this round's authorization: the very next real command via
	# the client immediately after a legitimate rejection must be accepted,
	# not just "state looks READY". This save also legitimately advances the
	# slot's save_sequence, which doubles as the setup Case B needs below.
	var repeat_save: Dictionary = await _request_and_wait_save(SAVE_SLOT)
	_check("G17_REPEAT_SAVE_CONFIRMED", repeat_save.get("result") == "CONFIRMED", JSON.stringify(repeat_save))
	_check("G17_POST_REJECTION_SAVE_VIA_CLIENT_ACCEPTED", repeat_save.get("result") == "CONFIRMED", JSON.stringify(repeat_save))
	var repeat_restored: Dictionary = await _request_and_wait_reload(SAVE_SLOT)
	_check("G17_REPEAT_RELOAD_ACCEPTED", repeat_restored.get("status") == "PASS", JSON.stringify(repeat_restored))
	_check(
		"G17_REPEAT_RELOAD_CLIENT_NOT_STUCK_PENDING",
		main.save_reload_client.state() == AndromedaSaveReloadClient.STATE_READY,
		"state=%s" % main.save_reload_client.state(),
	)
	var repeat_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var repeat_quest_matches: Array = (repeat_snapshot.get("quest_projection", {}) as Dictionary).get("quests", []).filter(
		func(q: Variant) -> bool: return q is Dictionary and str((q as Dictionary).get("quest_ref", "")) == quest_ref
	)
	var repeat_drop_matches: Array = (repeat_snapshot.get("ground_loot", []) as Array).filter(
		func(d: Variant) -> bool: return d is Dictionary and str((d as Dictionary).get("drop_ref", "")) == drop_ref
	)
	_check("G17_REPEAT_RELOAD_NO_DUPLICATION", repeat_quest_matches.size() == 1 and repeat_drop_matches.size() == 1, "quests=%d drops=%d" % [repeat_quest_matches.size(), repeat_drop_matches.size()])
	_check(
		"G17_REPEAT_RELOAD_STABLE_REFS",
		repeat_quest_matches.size() == 1 and str((repeat_quest_matches[0] as Dictionary).get("quest_ref", "")) == quest_ref
		and repeat_drop_matches.size() == 1 and str((repeat_drop_matches[0] as Dictionary).get("drop_ref", "")) == drop_ref,
	)
	_check(
		"G17_REPEAT_RELOAD_QUEST_STABLE",
		repeat_quest_matches.size() == 1 and str((repeat_quest_matches[0] as Dictionary).get("state", "")) == "ACTIVE",
		JSON.stringify(repeat_quest_matches),
	)

	# =====================================================================
	# 8) AUTOSAVE -- distinct fixed slot ("autosave"), confirmed by direct
	#    source read (AndromedaSaveReloadClient.request_autosave()). A
	#    separate mutate -> autosave -> mutate -> reload("autosave") cycle
	#    proves it round-trips on its own slot, independent of SAVE_SLOT,
	#    through the NORMAL client path end to end -- this cross-slot
	#    switch (manual slot just above -> autosave slot here) is exactly
	#    the scenario save_reload_client.gd's per-slot guard fix targets.
	#    Runs BEFORE the water-exposure probe below, deliberately, so an
	#    occasional slow reload there can never leave this block starved of
	#    a READY save_reload_client state.
	# =====================================================================
	var auto_pickup_at_autosave: bool = main.ground_loot_client.auto_pickup_enabled()
	_check("BRIDGE_READY_BEFORE_AUTOSAVE", await _wait_for_bridge_ready(bridge))
	var autosave_start: int = _results.size()
	var autosave_intent: Dictionary = main.save_reload_client.request_autosave("G17-AUTOSAVE-TEST")
	_check("G17_AUTOSAVE_INTENT_TRANSPORT", autosave_intent.get("transport_submitted") == true, JSON.stringify(autosave_intent))
	var autosave_result: Dictionary = await _wait_for_command("REQUEST_AUTOSAVE", autosave_start)
	_check("G17_AUTOSAVE_COMMAND_AUTHORITATIVE", autosave_result.get("server_authoritative") == true, JSON.stringify(autosave_result))
	_check("G17_AUTOSAVE_ACCEPTED", autosave_result.get("result") == "CONFIRMED", JSON.stringify(autosave_result))
	_check("G17_AUTOSAVE_KIND_CORRECT", str(autosave_result.get("command", "")) == "REQUEST_AUTOSAVE", JSON.stringify(autosave_result))
	_check("G17_AUTOSAVE_DISTINCT_SLOT", str(autosave_intent.get("slot_ref", "")) == AUTOSAVE_SLOT, JSON.stringify(autosave_intent))

	# Mutate again after the autosave, then reload from the autosave slot --
	# must restore to the value AT autosave time, not this later mutation.
	var post_autosave_mutation_start: int = _results.size()
	main.hud.inventory_shell.set_auto_pickup_visual(not auto_pickup_at_autosave, true)
	await _wait_for_command("SET_AUTO_PICKUP", post_autosave_mutation_start)
	await _wait_for_auto_pickup(not auto_pickup_at_autosave)

	var autosave_restored: Dictionary = await _request_and_wait_reload(AUTOSAVE_SLOT)
	_check("G17_AUTOSAVE_RESTORABLE_VIA_CLIENT", autosave_restored.get("status") == "PASS", JSON.stringify(autosave_restored))
	_check(
		"G17_AUTOSAVE_CLIENT_REPLAY_NAMESPACE_CORRECT",
		main.save_reload_client.state() == AndromedaSaveReloadClient.STATE_READY,
		"state=%s" % main.save_reload_client.state(),
	)
	# Authoritative signal, not the client's locally-cached getter -- see the
	# comment on G17_AUTO_PICKUP_RESTORED_FROM_SAVE above for why.
	var autosave_restored_auto_pickup: Variant = autosave_restored.get("restore_snapshot", {}).get("profile_preference", {}).get("auto_pickup", null)
	_check(
		"G17_AUTOSAVE_RESTORED_AUTO_PICKUP",
		autosave_restored_auto_pickup == auto_pickup_at_autosave,
		"expected=%s actual=%s" % [auto_pickup_at_autosave, autosave_restored_auto_pickup],
	)

	# =====================================================================
	# 9) WATER EXPOSURE -- deliberately LAST, in its own minimal, isolated
	#    save/reload pair, immediately after capturing the pre-save value.
	#    See the file-level comment for why this cannot safely share the
	#    main bundle's save/reload: the persisted zero_stamina_water_s only
	#    advances on a live tick, real reload latency can exceed the fixed
	#    4.0s EXHAUSTION_GRACE_S, and there is no non-destructive way to
	#    re-read it. Everything else in this gate has already been verified
	#    by this point, so an occasional real defeat here cannot contaminate
	#    any other clause's evidence.
	# =====================================================================
	var drain_result: Dictionary = await _await_command(bridge, "REPORT_WATER_TRAVERSAL", {
		"depth_m": 8.0, "flow_speed_mps": 8.0, "distance_m": 100.0,
	}, "DRAIN-STAMINA")
	_check("G17_WATER_TRAVERSAL_DRAINED_STAMINA", is_equal_approx(float(drain_result.get("stamina", {}).get("stamina_after", -1.0)), 0.0), JSON.stringify(drain_result))

	var first_tick: Dictionary = await _await_command(bridge, "REPORT_WATER_EXHAUSTION", {
		"volume_ref": "WATER-G17-EXPOSURE", "in_water": true,
	}, "EXPOSURE-TICK-1")
	_check("G17_WATER_EXPOSURE_AUTHORITATIVE", first_tick.get("status") == "PASS", JSON.stringify(first_tick))
	_check(
		"G17_WATER_EXPOSURE_NOT_DESTRUCTIVE_AT_FIRST_TICK",
		str(first_tick.get("exhaustion_snapshot", {}).get("state", "")) == "STAMINA_ZERO_GRACE",
		JSON.stringify(first_tick),
	)
	await get_tree().create_timer(0.3).timeout
	var second_tick: Dictionary = await _await_command(bridge, "REPORT_WATER_EXHAUSTION", {
		"volume_ref": "WATER-G17-EXPOSURE", "in_water": true,
	}, "EXPOSURE-TICK-2")
	var exposure_before_save: float = float(second_tick.get("zero_stamina_water_s", -1.0))
	_check("G17_WATER_EXPOSURE_NONZERO_BEFORE_SAVE", exposure_before_save > 0.0, "exposure=%f" % exposure_before_save)
	_check(
		"G17_WATER_EXPOSURE_NOT_DESTRUCTIVE_BEFORE_SAVE",
		str(second_tick.get("exhaustion_snapshot", {}).get("state", "")) == "STAMINA_ZERO_GRACE"
		and second_tick.get("defeat_required", true) == false,
		JSON.stringify(second_tick),
	)
	_progress("WATER_EXPOSURE_CAPTURED", {"exposure_before_save": exposure_before_save})

	var water_save: Dictionary = await _request_and_wait_save(SAVE_SLOT)
	_check("G17_WATER_EXPOSURE_SAVE_CONFIRMED", water_save.get("result") == "CONFIRMED", JSON.stringify(water_save))
	var water_restored: Dictionary = await _request_and_wait_reload(SAVE_SLOT)
	_check("G17_WATER_EXPOSURE_RELOAD_ACCEPTED", water_restored.get("status") == "PASS", JSON.stringify(water_restored))

	# First action after this reload, before anything else can add real
	# elapsed time on top of it.
	var third_tick: Dictionary = await _await_command(bridge, "REPORT_WATER_EXHAUSTION", {
		"volume_ref": "WATER-G17-EXPOSURE", "in_water": true,
	}, "EXPOSURE-TICK-3")
	var exposure_after_reload: float = float(third_tick.get("zero_stamina_water_s", -1.0))
	_check(
		"G17_WATER_EXPOSURE_PRESERVED_AFTER_RELOAD",
		exposure_after_reload >= exposure_before_save,
		"before=%f after=%f" % [exposure_before_save, exposure_after_reload],
	)
	_check("G17_WATER_EXPOSURE_NOT_RESET", exposure_after_reload > 0.0, "after=%f" % exposure_after_reload)
	_progress("WATER_EXPOSURE_POST_RELOAD", {
		"exposure_before_save": exposure_before_save,
		"exposure_after_reload": exposure_after_reload,
		"real_elapsed_s": float(third_tick.get("exhaustion_snapshot", {}).get("server_elapsed_s", -1.0)),
		"defeat_required": third_tick.get("defeat_required", null),
		"note": "A real defeat here (if the save/reload round trip exceeded EXHAUSTION_GRACE_S=4.0s) is expected mechanism behavior given real elapsed time, not a persistence failure -- see file header comment. It is not required to stay non-destructive, only the pre-save capture is.",
	})

	# --- Contextual note: quest progression transport gap, declared, never
	# fabricated as executed. -------------------------------------------------
	_progress("QUEST_PROGRESSION_TRANSPORT_GAP", {
		"status": "QUEST_PROGRESSION_TRANSPORT_GAP_NON_BLOCKING_FOR_G16B_17",
		"missing_commands": ["SUBMIT_OBJECTIVE", "TURN_IN_QUEST"],
		"core_functions_exist": ["submit_objective", "turn_in_quest"],
		"callers_found": 0,
	})

	_check("NO_COMMAND_REJECTIONS", _rejections.is_empty(), JSON.stringify(_rejections))
	_check("BRIDGE_FINAL_READY", await _wait_for_bridge_ready(bridge))
	await _finish()


func _ground_loot_entry(snapshot: Dictionary, drop_ref: String) -> Dictionary:
	for value: Variant in snapshot.get("ground_loot", []):
		if value is Dictionary and str((value as Dictionary).get("drop_ref", "")) == drop_ref:
			return value as Dictionary
	return {}


func _wait_for_auto_pickup(expected: bool) -> bool:
	var deadline: int = Time.get_ticks_usec() + int(WAIT_TIMEOUT_S * 1000000.0)
	while Time.get_ticks_usec() < deadline:
		if main.ground_loot_client.auto_pickup_enabled() == expected:
			return true
		await get_tree().process_frame
	return false


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


func _request_and_wait_reload(slot_ref: String) -> Dictionary:
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if bridge == null or not (await _wait_for_bridge_ready(bridge)):
		_failures.append("BRIDGE_NOT_READY_FOR_RELOAD")
		return {}
	var result_start: int = _results.size()
	var intent: Dictionary = main.save_reload_client.request_reload_resync(slot_ref)
	_check("RELOAD_INTENT_PASS", intent.get("status") == "PASS", JSON.stringify(intent))
	var result: Dictionary = await _wait_for_command("REQUEST_RELOAD_RESYNC", result_start)
	_check("RELOAD_RESULT_RECEIVED", not result.is_empty())
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
	return "GODOT-SAVERELOAD-%s-%d" % [label, Time.get_ticks_usec()]


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
	print("ANDROMEDA_AUTHORITY_G17_PROGRESS:%s:%s" % [marker, JSON.stringify(detail)])


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": "STAGE16B_AUTHORITY_SAVE_RELOAD_RESYNC",
		"authority": "STAGE15_STAGE16A_SERVER_AUTHORITATIVE",
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_SAVE_RELOAD_RESYNC_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_SAVE_RELOAD_RESYNC_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_SAVE_RELOAD_RESYNC_SUMMARY: %s" % JSON.stringify(summary))
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
