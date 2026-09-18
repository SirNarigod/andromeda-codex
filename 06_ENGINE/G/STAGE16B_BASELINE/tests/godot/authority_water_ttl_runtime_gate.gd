extends Node

## G16B-27 WATER TTL / PERSISTENCE -- real Godot observation.
##
## Every scenario runs against its OWN clean-world backend boot, selected via
## the --scenario= cmdline arg (see run_stage16b_water_ttl_gates.* for the
## per-scenario launch/housekeeping sequence). This is deliberate isolation:
## ADVANCE_DEVELOPMENT_WATER_TIME advances every ACTIVE Ground Loot in WATER
## and every DROPPED_WATER_FLOATING Bag in the whole world at once, so two
## scenarios sharing one world could silently perturb each other's exposure
## math. One gate script, one scene, six mutually exclusive scenarios --
## never duplicated backend, never a second clock, never a fabricated Ground
## Loot/Bag (every one is created through the same real, already-proven
## transport the rest of this test suite already relies on: REQUEST_GATHER,
## REPORT_GROUND_LOOT_WATER_STATE, REPORT_WATER_EXHAUSTION, REQUEST_ATTACK).
##
## SCENARIO=A  Ground Loot WATER TTL threshold (899 not sunk, +1 -> 900 sunk)
## SCENARIO=B  Ground Loot WATER TTL persistence through save/reload
## SCENARIO=C  DroppedBag WATER TTL threshold (1799 floating, +1 -> 1800 sunk)
## SCENARIO=D  DroppedBag WATER TTL persistence through save/reload
## SCENARIO=E  DroppedBag on LAND has no TTL, survives an extreme advance + save/reload
## SCENARIO=F  ADVANCE_DEVELOPMENT_WATER_TIME rejected outside development_profile_bootstrap

const SESSION_REF := "GODOT-AUTHORITY-WATER-TTL-V080"
const WAIT_TIMEOUT_S := 90.0
const COMMAND := "ADVANCE_DEVELOPMENT_WATER_TIME"

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _checks: int = 0
var _failures: Array[String] = []
var _bind_results: Array[Dictionary] = []
var _snapshots: Array[Dictionary] = []
var _results: Array[Dictionary] = []
var _rejections: Array[String] = []
var _gate_name: String = "STAGE16B_AUTHORITY_WATER_TTL"


func _ready() -> void:
	await _run_gate()


func _scenario_from_cmdline() -> String:
	for argument: String in OS.get_cmdline_user_args():
		if argument.begins_with("--scenario="):
			return argument.trim_prefix("--scenario=").strip_edges().to_upper()
	return ""


func _run_gate() -> void:
	var scenario: String = _scenario_from_cmdline()
	_gate_name = "STAGE16B_AUTHORITY_WATER_TTL_%s" % (scenario if not scenario.is_empty() else "UNSPECIFIED")
	_check("SCENARIO_ARG_PRESENT", not scenario.is_empty(), "pass --scenario=A|B|C|D|E|F")
	if scenario.is_empty():
		await _finish()
		return

	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	_check("SESSION_AUTOLOAD", session != null)
	_check("BRIDGE_AUTOLOAD", bridge != null)
	_check("MAIN_RUNTIME_PRESENT", main != null)
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

	var enabled: Array = _bind_results[0].get("enabled_commands", [])
	_check("COMMAND_ADVERTISED", enabled.has(COMMAND), JSON.stringify(enabled))

	match scenario:
		"A":
			await _scenario_ground_loot_threshold(bridge)
		"B":
			await _scenario_ground_loot_persistence(bridge)
		"C":
			await _scenario_water_bag_threshold(bridge)
		"D":
			await _scenario_water_bag_persistence(bridge)
		"E":
			await _scenario_land_bag_no_ttl(bridge)
		"F":
			await _scenario_non_development_guard(bridge)
		_:
			_failures.append("UNKNOWN_SCENARIO:%s" % scenario)

	await _finish()


# ---------------------------------------------------------------------------
# Shared setup: a real Ground Loot drop, marked WATER via the real command.
# ---------------------------------------------------------------------------
func _spawn_and_mark_ground_loot_in_water(bridge: AndromedaRuntimeBridge, label: String) -> Dictionary:
	var snapshot: Dictionary = await _fresh_snapshot(bridge)
	var mining_nodes: Array[String] = []
	for node: Variant in snapshot.get("gathering_nodes", []):
		if not node is Dictionary:
			continue
		var n: Dictionary = node
		if str(n.get("activity_type", "")) == "MINING" and str(n.get("state", "")) == "AVAILABLE":
			mining_nodes.append(str(n.get("target_ref", "")))
	mining_nodes.sort()
	_check("%s_MINING_NODE_AVAILABLE" % label, not mining_nodes.is_empty())
	if mining_nodes.is_empty():
		return {}

	var gather: Dictionary = await _await_command(bridge, "REQUEST_GATHER", {
		"target_ref": mining_nodes[0], "requested_units": 1,
	}, "%s-GATHER" % label)
	_check("%s_GATHER_AUTHORITATIVE" % label, gather.get("status") == "PASS", JSON.stringify(gather))
	var drop_ref: String = str((gather.get("physical_output", {}) as Dictionary).get("target_ref", ""))
	_check("%s_DROP_REF_PRESENT" % label, not drop_ref.is_empty())
	if drop_ref.is_empty():
		return {}

	var after_gather: Dictionary = await _fresh_snapshot(bridge)
	var candidate: Dictionary = _drop_position(_entry_by_drop_ref(after_gather, drop_ref))
	if not candidate.is_empty():
		await _await_command(bridge, "CONFIRM_DROP_SETTLED", {
			"target_ref": drop_ref, "settled_position": candidate, "reachable": true,
		}, "%s-SETTLE" % label)

	var marked: Dictionary = await _await_command(bridge, "REPORT_GROUND_LOOT_WATER_STATE", {
		"request_ref": "%s:UI" % label, "target_ref": drop_ref, "drop_ref": drop_ref,
		"in_water": true, "flow_speed_mps": 0.3, "client_presentation_only": true,
	}, "%s-MARK" % label)
	_check("%s_WATER_MARK_AUTHORITATIVE" % label, marked.get("status") == "PASS", JSON.stringify(marked))
	_check("%s_WATER_MARK_ENVIRONMENT" % label, str(marked.get("environment", "")) == "WATER", JSON.stringify(marked))
	return {"drop_ref": drop_ref, "water_ttl_s": float(marked.get("water_ttl_s", -1.0))}


# ---------------------------------------------------------------------------
# Shared setup: a real DroppedBag in water, from a real player water death.
# ---------------------------------------------------------------------------
func _die_in_water_and_capture_bag(bridge: AndromedaRuntimeBridge, label: String) -> Dictionary:
	if main.inventory_client.bag_state() == "NO_BAG":
		var equip_start: int = _results.size()
		main.inventory_client.request_bag_equip("%s-BAG" % label)
		var equip_result: Dictionary = await _wait_for_command("REQUEST_EQUIP_BAG", equip_start)
		_check("%s_BAG_EQUIP_AUTHORITATIVE" % label, equip_result.get("status") == "PASS", JSON.stringify(equip_result))

	# Drain stamina to zero via the real deep-water traversal report first --
	# water_exhaustion_tick() only accumulates the grace timer once stamina is
	# actually at zero (same real transport as authority_save_death_runtime_
	# gate.gd's own REPORT_WATER_TRAVERSAL step, unmodified here).
	var traversal_start: int = _results.size()
	bridge.submit_command("REPORT_WATER_TRAVERSAL", {
		"request_ref": "%s-TRAVERSAL" % label, "volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"depth_m": 8.0, "flow_speed_mps": 8.0, "distance_m": 100.0,
		"under_bridge": false, "client_presentation_only": true,
	})
	var traversal: Dictionary = await _wait_for_command("REPORT_WATER_TRAVERSAL", traversal_start)
	_check("%s_TRAVERSAL_AUTHORITATIVE" % label, traversal.get("status") == "PASS", JSON.stringify(traversal))
	_check(
		"%s_STAMINA_ZERO_BY_AUTHORITY" % label,
		is_zero_approx(float((traversal.get("stamina", {}) as Dictionary).get("stamina_after", -1.0))),
		JSON.stringify(traversal),
	)

	var grace_start: int = _results.size()
	bridge.submit_command("REPORT_WATER_EXHAUSTION", {
		"request_ref": "%s-GRACE" % label, "volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"in_water": true, "client_presentation_only": true,
	})
	var grace: Dictionary = await _wait_for_command("REPORT_WATER_EXHAUSTION", grace_start)
	_check("%s_GRACE_AUTHORITATIVE" % label, grace.get("status") == "PASS", JSON.stringify(grace))
	await get_tree().create_timer(4.15).timeout

	var death_start: int = _results.size()
	bridge.submit_command("REPORT_WATER_EXHAUSTION", {
		"request_ref": "%s-DEFEAT" % label, "volume_ref": "WATER-B04-DEEP-SWIMMABLE",
		"in_water": true, "client_presentation_only": true,
	})
	var defeated: Dictionary = await _wait_for_command("REPORT_WATER_EXHAUSTION", death_start)
	_check("%s_DEATH_COMMAND_AUTHORITATIVE" % label, defeated.get("status") == "PASS", JSON.stringify(defeated))

	var bag_entries: Array = (((defeated.get("death_event", {}) as Dictionary).get("bag_drop", {}) as Dictionary).get("dropped_bag_snapshot", {}) as Dictionary).get("dropped_bags", [])
	_check("%s_BAG_DROPPED_IN_DEATH_EVENT" % label, bag_entries.size() == 1, JSON.stringify(bag_entries))
	var bag_ref: String = str((bag_entries[0] as Dictionary).get("bag_ref", "")) if bag_entries.size() == 1 else ""
	var water_ttl_s: float = float((bag_entries[0] as Dictionary).get("water_ttl_s", -1.0)) if bag_entries.size() == 1 else -1.0

	# Deliberately no respawn here: nothing downstream in these TTL scenarios
	# needs the player alive/moving again, and REQUEST_RESPAWN is real
	# wall-clock-timed transport that would only add unnecessary real seconds
	# to this same world's already-running water clock before the scenario's
	# own deterministic ADVANCE_DEVELOPMENT_WATER_TIME calls even begin.
	return {"bag_ref": bag_ref, "water_ttl_s": water_ttl_s}


func _dropped_bag_entry(snapshot: Dictionary, bag_ref: String) -> Dictionary:
	for value: Variant in snapshot.get("dropped_bags", []):
		if value is Dictionary and str((value as Dictionary).get("bag_ref", "")) == bag_ref:
			return value as Dictionary
	return {}


# ---------------------------------------------------------------------------
# A: Ground Loot WATER TTL threshold.
# ---------------------------------------------------------------------------
func _scenario_ground_loot_threshold(bridge: AndromedaRuntimeBridge) -> void:
	var setup: Dictionary = await _spawn_and_mark_ground_loot_in_water(bridge, "G27A")
	if setup.is_empty():
		return
	var drop_ref: String = str(setup["drop_ref"])
	var ttl_s: float = float(setup["water_ttl_s"])
	_check("G27_GROUND_LOOT_TTL_IS_900", is_equal_approx(ttl_s, 900.0), "ttl_s=%f" % ttl_s)

	var advance_899: Dictionary = await _await_command(bridge, COMMAND, {"delta_s": 899.0}, "G27A-ADVANCE-899")
	_check("G27_GROUND_LOOT_WATER_COMMAND_AUTHORITATIVE", advance_899.get("status") == "PASS", JSON.stringify(advance_899))
	var sunk_899: Array = (advance_899.get("ground_loot", {}) as Dictionary).get("sunk_drop_refs", [])
	_check("G27_GROUND_LOOT_899_NOT_SUNK", not sunk_899.has(drop_ref), JSON.stringify(sunk_899))

	var advance_1: Dictionary = await _await_command(bridge, COMMAND, {"delta_s": 1.0}, "G27A-ADVANCE-900")
	_check("G27_GROUND_LOOT_COMMAND_2_AUTHORITATIVE", advance_1.get("status") == "PASS", JSON.stringify(advance_1))
	var sunk_900: Array = (advance_1.get("ground_loot", {}) as Dictionary).get("sunk_drop_refs", [])
	_check("G27_GROUND_LOOT_900_THRESHOLD_CROSSED", sunk_900.has(drop_ref), JSON.stringify(sunk_900))
	_check("G27_GROUND_LOOT_SUNK_AFTER_THRESHOLD", sunk_900.has(drop_ref), JSON.stringify(sunk_900))

	_check("NO_COMMAND_REJECTIONS", _rejections.is_empty(), JSON.stringify(_rejections))


# ---------------------------------------------------------------------------
# B: Ground Loot WATER TTL persistence through save/reload.
# ---------------------------------------------------------------------------
func _scenario_ground_loot_persistence(bridge: AndromedaRuntimeBridge) -> void:
	var setup: Dictionary = await _spawn_and_mark_ground_loot_in_water(bridge, "G27B")
	if setup.is_empty():
		return
	var drop_ref: String = str(setup["drop_ref"])
	var ttl_s: float = float(setup["water_ttl_s"])

	# Safe margin below the real, confirmed threshold -- never 899.
	var margin_advance: Dictionary = await _await_command(bridge, COMMAND, {"delta_s": 600.0}, "G27B-ADVANCE-600")
	_check("G27_GROUND_LOOT_MARGIN_ADVANCE_AUTHORITATIVE", margin_advance.get("status") == "PASS", JSON.stringify(margin_advance))
	var sunk_at_margin: Array = (margin_advance.get("ground_loot", {}) as Dictionary).get("sunk_drop_refs", [])
	_check("G27_GROUND_LOOT_MARGIN_NOT_SUNK", not sunk_at_margin.has(drop_ref), JSON.stringify(sunk_at_margin))

	var before_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var before_entry: Dictionary = _entry_by_drop_ref(before_snapshot, drop_ref)
	var exposure_before_save: float = float(before_entry.get("water_exposure_s", -1.0))
	_check("G27_GROUND_LOOT_EXPOSURE_BEFORE_SAVE_PLAUSIBLE", exposure_before_save >= 600.0, "exposure_before_save=%f" % exposure_before_save)

	var saved: Dictionary = await _request_and_wait_save("g27blwater")
	_check("G27_GROUND_LOOT_SAVE_CONFIRMED", saved.get("result") == "CONFIRMED", JSON.stringify(saved))
	var restored: Dictionary = await _request_and_wait_reload("g27blwater")
	_check("G27_GROUND_LOOT_RELOAD_AUTHORITATIVE", restored.get("status") == "PASS", JSON.stringify(restored))

	var after_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var after_entry: Dictionary = _entry_by_drop_ref(after_snapshot, drop_ref)
	var exposure_after_reload: float = float(after_entry.get("water_exposure_s", -1.0))
	_check(
		"G27_GROUND_LOOT_EXPOSURE_PERSISTED",
		exposure_after_reload >= exposure_before_save and exposure_after_reload > 0.0,
		"before=%f after=%f" % [exposure_before_save, exposure_after_reload],
	)
	_check(
		"G27_GROUND_LOOT_EXPOSURE_NOT_RESET_BY_RELOAD",
		exposure_after_reload >= exposure_before_save,
		"before=%f after=%f" % [exposure_before_save, exposure_after_reload],
	)

	var crossing_delta: float = maxf(0.0, ttl_s - exposure_after_reload) + 5.0
	var crossing: Dictionary = await _await_command(bridge, COMMAND, {"delta_s": crossing_delta}, "G27B-ADVANCE-CROSS")
	_check("G27_GROUND_LOOT_CROSSING_COMMAND_AUTHORITATIVE", crossing.get("status") == "PASS", JSON.stringify(crossing))
	var sunk_after_cross: Array = (crossing.get("ground_loot", {}) as Dictionary).get("sunk_drop_refs", [])
	_check("G27_GROUND_LOOT_SINKS_AFTER_PERSISTED_EXPOSURE", sunk_after_cross.has(drop_ref), JSON.stringify(sunk_after_cross))

	_check("NO_COMMAND_REJECTIONS", _rejections.is_empty(), JSON.stringify(_rejections))


# ---------------------------------------------------------------------------
# C: DroppedBag WATER TTL threshold.
# ---------------------------------------------------------------------------
func _scenario_water_bag_threshold(bridge: AndromedaRuntimeBridge) -> void:
	var setup: Dictionary = await _die_in_water_and_capture_bag(bridge, "G27C")
	var bag_ref: String = str(setup.get("bag_ref", ""))
	var ttl_s: float = float(setup.get("water_ttl_s", -1.0))
	if bag_ref.is_empty():
		return
	_check("G27_WATER_BAG_TTL_IS_1800", is_equal_approx(ttl_s, 1800.0), "ttl_s=%f" % ttl_s)

	var advance_1799: Dictionary = await _await_command(bridge, COMMAND, {"delta_s": 1799.0}, "G27C-ADVANCE-1799")
	_check("G27_WATER_BAG_COMMAND_AUTHORITATIVE", advance_1799.get("status") == "PASS", JSON.stringify(advance_1799))
	var sunk_1799: Array = advance_1799.get("bags_sunk", [])
	_check("G27_BAG_1799_FLOATING", not sunk_1799.has(bag_ref), JSON.stringify(sunk_1799))

	var advance_1: Dictionary = await _await_command(bridge, COMMAND, {"delta_s": 1.0}, "G27C-ADVANCE-1800")
	_check("G27_BAG_COMMAND_2_AUTHORITATIVE", advance_1.get("status") == "PASS", JSON.stringify(advance_1))
	var sunk_1800: Array = advance_1.get("bags_sunk", [])
	_check("G27_BAG_1800_THRESHOLD_CROSSED", sunk_1800.has(bag_ref), JSON.stringify(sunk_1800))
	_check("G27_BAG_SUNK_AFTER_THRESHOLD", sunk_1800.has(bag_ref), JSON.stringify(sunk_1800))

	var after_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var after_entry: Dictionary = _dropped_bag_entry(after_snapshot, bag_ref)
	_check("G27_BAG_SAME_REF_AFTER_SINK", str(after_entry.get("bag_ref", "")) == bag_ref, JSON.stringify(after_entry))
	_check("G27_BAG_OWNER_PRESERVED_AFTER_SINK", str(after_entry.get("property_owner_ref", "")) == str(after_snapshot.get("identity", {}).get("profile_ref", "")), JSON.stringify(after_entry))

	_check("NO_COMMAND_REJECTIONS", _rejections.is_empty(), JSON.stringify(_rejections))


# ---------------------------------------------------------------------------
# D: DroppedBag WATER TTL persistence through save/reload.
# ---------------------------------------------------------------------------
func _scenario_water_bag_persistence(bridge: AndromedaRuntimeBridge) -> void:
	var setup: Dictionary = await _die_in_water_and_capture_bag(bridge, "G27D")
	var bag_ref: String = str(setup.get("bag_ref", ""))
	var ttl_s: float = float(setup.get("water_ttl_s", -1.0))
	if bag_ref.is_empty():
		return
	var owner_before: String = ""
	var initial_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var initial_entry: Dictionary = _dropped_bag_entry(initial_snapshot, bag_ref)
	owner_before = str(initial_entry.get("property_owner_ref", ""))

	var margin_advance: Dictionary = await _await_command(bridge, COMMAND, {"delta_s": 1200.0}, "G27D-ADVANCE-1200")
	_check("G27_BAG_MARGIN_ADVANCE_AUTHORITATIVE", margin_advance.get("status") == "PASS", JSON.stringify(margin_advance))
	var sunk_at_margin: Array = margin_advance.get("bags_sunk", [])
	_check("G27_BAG_MARGIN_NOT_SUNK", not sunk_at_margin.has(bag_ref), JSON.stringify(sunk_at_margin))

	var before_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var before_entry: Dictionary = _dropped_bag_entry(before_snapshot, bag_ref)
	var exposure_before_save: float = float(before_entry.get("water_exposure_s", -1.0))
	_check("G27_BAG_EXPOSURE_BEFORE_SAVE_PLAUSIBLE", exposure_before_save >= 1200.0, "exposure_before_save=%f" % exposure_before_save)
	_check("G27_BAG_STILL_FLOATING_BEFORE_SAVE", str(before_entry.get("state", "")) == "DROPPED_WATER_FLOATING", JSON.stringify(before_entry))

	var saved: Dictionary = await _request_and_wait_save("g27dbagwater")
	_check("G27_BAG_SAVE_CONFIRMED", saved.get("result") == "CONFIRMED", JSON.stringify(saved))
	var restored: Dictionary = await _request_and_wait_reload("g27dbagwater")
	_check("G27_BAG_RELOAD_AUTHORITATIVE", restored.get("status") == "PASS", JSON.stringify(restored))

	var after_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var after_entry: Dictionary = _dropped_bag_entry(after_snapshot, bag_ref)
	var exposure_after_reload: float = float(after_entry.get("water_exposure_s", -1.0))
	_check(
		"G27_BAG_EXPOSURE_PERSISTED",
		exposure_after_reload >= exposure_before_save and exposure_after_reload > 0.0,
		"before=%f after=%f" % [exposure_before_save, exposure_after_reload],
	)
	_check(
		"G27_BAG_EXPOSURE_NOT_RESET_BY_RELOAD",
		exposure_after_reload >= exposure_before_save,
		"before=%f after=%f" % [exposure_before_save, exposure_after_reload],
	)
	_check("G27_BAG_OWNER_PRESERVED_THROUGH_RELOAD_AND_SINK", str(after_entry.get("property_owner_ref", "")) == owner_before, JSON.stringify(after_entry))

	var crossing_delta: float = maxf(0.0, ttl_s - exposure_after_reload) + 5.0
	var crossing: Dictionary = await _await_command(bridge, COMMAND, {"delta_s": crossing_delta}, "G27D-ADVANCE-CROSS")
	_check("G27_BAG_CROSSING_COMMAND_AUTHORITATIVE", crossing.get("status") == "PASS", JSON.stringify(crossing))
	var sunk_after_cross: Array = crossing.get("bags_sunk", [])
	_check("G27_BAG_SINKS_AFTER_PERSISTED_EXPOSURE", sunk_after_cross.has(bag_ref), JSON.stringify(sunk_after_cross))

	var final_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var final_entry: Dictionary = _dropped_bag_entry(final_snapshot, bag_ref)
	_check("G27_BAG_OWNER_PRESERVED_FINAL", str(final_entry.get("property_owner_ref", "")) == owner_before, JSON.stringify(final_entry))

	_check("NO_COMMAND_REJECTIONS", _rejections.is_empty(), JSON.stringify(_rejections))


# ---------------------------------------------------------------------------
# E: DroppedBag on LAND has no TTL. Real via the already-proven G16B-05
# ENEMY -> Ground Loot pipeline: the development combat encounter's COMMON
# target already carries its own equipped Bag (andromeda_authority_adapter.py
# ::_ensure_enemy_carried_bag(), called from _ensure_development_combat_
# encounter()), and _enemy_death_physical_output() drops that Bag on LAND
# (in_water=False, hardcoded -- no actor water state exists for an NPC in
# this round) the moment the target is defeated via the real REQUEST_ATTACK
# loop -- the exact same defeat mechanism the main save/death gate already
# uses for XP/armor/common drops. bag_ref surfaces directly in the attack
# result's enemy_physical_output.bag_ref. Nothing here is fabricated.
# ---------------------------------------------------------------------------
func _scenario_land_bag_no_ttl(bridge: AndromedaRuntimeBridge) -> void:
	var initial: Dictionary = await _fresh_snapshot(bridge)
	var common_target_ref: String = ""
	for entry: Variant in initial.get("combat_targets", []):
		if entry is Dictionary and str((entry as Dictionary).get("slot", "")) == "COMMON":
			common_target_ref = str((entry as Dictionary).get("target_ref", ""))
			break
	_check("G27_LAND_BAG_COMMON_TARGET_FOUND", not common_target_ref.is_empty(), JSON.stringify(initial.get("combat_targets", [])))
	if common_target_ref.is_empty():
		return

	var lethal: Dictionary = {}
	for attempt: int in range(1, 41):
		await get_tree().create_timer(1.05).timeout
		var attack: Dictionary = await _await_command(bridge, "REQUEST_ATTACK", {"target_ref": common_target_ref}, "G27E-ATTACK-%d" % attempt)
		if attack.is_empty():
			break
		if attack.get("status") == "PASS" and bool(attack.get("enemy_defeated", false)):
			lethal = attack
			break
	_check("G27_LAND_BAG_ENEMY_DEFEAT_AUTHORITATIVE", lethal.get("status") == "PASS" and bool(lethal.get("enemy_defeated", false)), JSON.stringify(lethal.get("reason", "NO_DEFEAT_REACHED")))
	if lethal.is_empty():
		return

	var physical_output: Dictionary = lethal.get("enemy_physical_output", {})
	var bag_ref: String = str(physical_output.get("bag_ref", ""))
	_check("G27_LAND_BAG_AUTHORITATIVE", not bag_ref.is_empty(), JSON.stringify(physical_output))
	if bag_ref.is_empty():
		return

	var after_defeat: Dictionary = await _fresh_snapshot(bridge)
	var entry: Dictionary = _dropped_bag_entry(after_defeat, bag_ref)
	_check("G27_LAND_BAG_STATE_IS_DROPPED_LAND", str(entry.get("state", "")) == "DROPPED_LAND", JSON.stringify(entry))
	_check("G27_LAND_BAG_NO_WATER_TTL", entry.get("water_ttl_s") == null, JSON.stringify(entry))
	var owner_before: String = str(entry.get("property_owner_ref", ""))
	_check("G27_LAND_BAG_OWNER_KNOWN", owner_before == common_target_ref, "owner=%s target=%s" % [owner_before, common_target_ref])

	var advance: Dictionary = await _await_command(bridge, COMMAND, {"delta_s": 100000.0}, "G27E-ADVANCE-EXTREME")
	_check("G27_LAND_BAG_ADVANCE_COMMAND_AUTHORITATIVE", advance.get("status") == "PASS", JSON.stringify(advance))
	var sunk_bags: Array = advance.get("bags_sunk", [])
	_check("G27_LAND_BAG_SURVIVES_LONG_TIME", not sunk_bags.has(bag_ref), JSON.stringify(sunk_bags))

	var after_advance: Dictionary = await _fresh_snapshot(bridge)
	var entry_after_advance: Dictionary = _dropped_bag_entry(after_advance, bag_ref)
	_check("G27_LAND_BAG_SAME_REF", str(entry_after_advance.get("bag_ref", "")) == bag_ref, JSON.stringify(entry_after_advance))
	_check("G27_LAND_BAG_OWNER_PRESERVED", str(entry_after_advance.get("property_owner_ref", "")) == owner_before, JSON.stringify(entry_after_advance))
	_check("G27_LAND_BAG_STILL_DROPPED_LAND", str(entry_after_advance.get("state", "")) == "DROPPED_LAND", JSON.stringify(entry_after_advance))

	var saved: Dictionary = await _request_and_wait_save("g27elandbag")
	_check("G27_LAND_BAG_SAVE_CONFIRMED", saved.get("result") == "CONFIRMED", JSON.stringify(saved))
	var restored: Dictionary = await _request_and_wait_reload("g27elandbag")
	_check("G27_LAND_BAG_RELOAD_AUTHORITATIVE", restored.get("status") == "PASS", JSON.stringify(restored))

	var final_snapshot: Dictionary = await _fresh_snapshot(bridge)
	var final_entry: Dictionary = _dropped_bag_entry(final_snapshot, bag_ref)
	_check("G27_LAND_BAG_SURVIVES_SAVE_RELOAD", str(final_entry.get("state", "")) == "DROPPED_LAND", JSON.stringify(final_entry))
	_check("G27_LAND_BAG_NO_TTL_AFTER_RELOAD", final_entry.get("water_ttl_s") == null, JSON.stringify(final_entry))
	_check("G27_LAND_BAG_OWNER_PRESERVED_AFTER_RELOAD", str(final_entry.get("property_owner_ref", "")) == owner_before, JSON.stringify(final_entry))

	_check("NO_COMMAND_REJECTIONS", _rejections.is_empty(), JSON.stringify(_rejections))


# ---------------------------------------------------------------------------
# F: ADVANCE_DEVELOPMENT_WATER_TIME is REJECTED outside a development-profile
# world, with zero mutation -- the world this scenario runs against must be
# booted with ANDROMEDA_S16B_DEV_PROFILE_BOOTSTRAP=0 (housekeeping side, not
# a code change).
# ---------------------------------------------------------------------------
func _scenario_non_development_guard(bridge: AndromedaRuntimeBridge) -> void:
	var result: Dictionary = await _await_command(bridge, COMMAND, {"delta_s": 1.0}, "G27F-GUARD")
	_check("G27_NON_DEV_GUARD_REJECTED", result.get("status") == "REJECTED", JSON.stringify(result))
	_check(
		"G27_NON_DEV_GUARD_REASON",
		str(result.get("reason", "")) == "DEV_WATER_TIME_COMMAND_DISABLED_OUTSIDE_DEVELOPMENT_PROFILE",
		JSON.stringify(result),
	)
	# This REJECTED result is the deliberate, expected outcome of this
	# scenario -- andromeda_bridge.gd emits command_rejected for it like any
	# other non-PASS result. Remove exactly that one expected occurrence
	# before the final NO_COMMAND_REJECTIONS check, same discipline already
	# established for BASE_INVENTORY_SLOT_LIMIT_WITHOUT_BAG/VEHICLE_WATER_
	# TOO_DEEP in the other gates -- any other, truly unexpected rejection
	# still fails it.
	_rejections.erase("DEV_WATER_TIME_COMMAND_DISABLED_OUTSIDE_DEVELOPMENT_PROFILE")
	_check("NO_COMMAND_REJECTIONS", _rejections.is_empty(), JSON.stringify(_rejections))


# ---------------------------------------------------------------------------
# Shared save/reload helpers (same contract as authority_save_death_runtime_
# gate.gd's _request_and_wait_save(), parameterized by slot_ref since each
# scenario uses its own slot to avoid any cross-scenario/world save collision).
# ---------------------------------------------------------------------------
func _request_and_wait_save(slot_ref: String) -> Dictionary:
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if bridge == null or not (await _wait_for_bridge_ready(bridge)):
		_failures.append("BRIDGE_NOT_READY_FOR_SAVE")
		return {}
	var result_start: int = _results.size()
	var intent: Dictionary = main.save_reload_client.request_manual_save(slot_ref)
	_check("SAVE_INTENT_PASS_%s" % slot_ref, intent.get("status") == "PASS", JSON.stringify(intent))
	var result: Dictionary = await _wait_for_command("REQUEST_SAVE", result_start)
	_check("SAVE_RESULT_RECEIVED_%s" % slot_ref, not result.is_empty())
	return result


func _request_and_wait_reload(slot_ref: String) -> Dictionary:
	var bridge := get_node_or_null("/root/AndromedaBridge") as AndromedaRuntimeBridge
	if bridge == null or not (await _wait_for_bridge_ready(bridge)):
		_failures.append("BRIDGE_NOT_READY_FOR_RELOAD")
		return {}
	var result_start: int = _results.size()
	var intent: Dictionary = main.save_reload_client.request_reload_resync(slot_ref)
	_check("RELOAD_INTENT_PASS_%s" % slot_ref, intent.get("status") == "PASS", JSON.stringify(intent))
	var result: Dictionary = await _wait_for_command("REQUEST_RELOAD_RESYNC", result_start)
	_check("RELOAD_RESULT_RECEIVED_%s" % slot_ref, not result.is_empty())
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
	return "GODOT-WATERTTL-%s-%d" % [label, Time.get_ticks_usec()]


func _await_command(bridge: AndromedaRuntimeBridge, command: String, params: Dictionary, label: String) -> Dictionary:
	var command_ref: String = _unique_ref(label)
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


func _finish() -> void:
	var summary := {
		"status": "PASS" if _failures.is_empty() else "FAIL",
		"checks": _checks,
		"passed": _checks - _failures.size(),
		"failed": _failures.size(),
		"failures": _failures,
		"gate": _gate_name,
		"authority": "STAGE15_STAGE16A_SERVER_AUTHORITATIVE",
	}
	if _failures.is_empty():
		print("ANDROMEDA_STAGE16B_WATER_TTL_GATE: PASS")
	else:
		push_error("ANDROMEDA_STAGE16B_WATER_TTL_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_STAGE16B_WATER_TTL_SUMMARY: %s" % JSON.stringify(summary))
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
