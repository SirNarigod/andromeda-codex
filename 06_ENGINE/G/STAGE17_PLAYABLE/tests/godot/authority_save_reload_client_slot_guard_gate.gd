extends Node

## Permanent regression for the save_reload_client.gd cross-slot replay-guard
## fix. No live backend needed: this drives AndromedaSaveReloadClient
## directly with fabricated (but structurally real) restore_snapshot
## payloads, exactly like the pre-existing b10_runtime_gate.gd fixture
## pattern, and checks project_restore_snapshot()'s accept/reject decisions
## and main.save_reload_client.state() transitions.
##
## Root cause (confirmed by direct read, fixed in save_reload_client.gd):
## the backend tracks save_sequence PER SAVE SLOT
## (andromeda_authority_adapter.py::_request_save():
## self._next_result_sequence("SAVE_SEQUENCE:" + slot_ref) -- confirmed via
## _next_result_sequence()'s scope_ref-keyed SQLite cursor, i.e. genuinely
## per-slot, not global). The client's own project_restore_snapshot() used a
## single GLOBAL _last_restored_save_sequence int compared against that
## per-slot value -- restoring "autosave" after "manual" (or vice versa)
## could spuriously reject a fully valid, newer restore as
## OLDER_OR_DUPLICATE_SAVE_SEQUENCE purely because the two slots' own
## independent counters happened to collide numerically, leaving the client
## stuck at RELOAD_PENDING and blocking every subsequent save. Fixed by
## keying the guard per slot_ref (_last_restored_save_sequence_by_slot), the
## same real slot_ref the backend already returns on every REQUEST_RELOAD_
## RESYNC result. restore_sequence's own guard is untouched: it comes from
## _next_transport_sequence(), which IS globally monotonic by contract, so
## a single global int for it is correct.

const SESSION_REF := "GODOT-SAVE-RELOAD-CLIENT-SLOT-GUARD-V080"
const MANUAL_SLOT := "manual"
const AUTOSAVE_SLOT := "autosave"

@onready var main: AndromedaMainRuntime = $AndromedaARPG

var _checks: int = 0
var _failures: Array[String] = []


func _ready() -> void:
	await _run_gate()


func _run_gate() -> void:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	_check("SESSION_AUTOLOAD", session != null)
	_check("MAIN_RUNTIME_PRESENT", main != null and main.save_reload_client != null)
	if session == null or main == null:
		await _finish()
		return

	if session.has_active_session():
		session.revoke_session()
	_check("LOCAL_SESSION_BIND", session.bind_session(SESSION_REF).get("status") == "PASS")
	var client: AndromedaSaveReloadClient = main.save_reload_client

	# =====================================================================
	# GROUP 1 -- guard correctness, direct fixture calls.
	# =====================================================================

	# A1: first restore for "manual" -- must be accepted.
	var manual_1: Dictionary = client.project_restore_snapshot(_fixture(1, 1), MANUAL_SLOT)
	_check("SAVE_RELOAD_MANUAL_FIRST_ACCEPTED", manual_1.get("status") == "PASS", JSON.stringify(manual_1))

	# A2: same slot, same save_sequence (higher restore_sequence so the
	# GLOBAL restore guard doesn't mask this) -- must still be rejected.
	# This is the anti-replay protection this fix must NOT weaken.
	var manual_2_stale: Dictionary = client.project_restore_snapshot(_fixture(2, 1), MANUAL_SLOT)
	_check("SAVE_RELOAD_SAME_SLOT_DUPLICATE_REJECTED", manual_2_stale.get("status") != "PASS", JSON.stringify(manual_2_stale))
	_check(
		"SAVE_RELOAD_SAME_SLOT_STALE_REASON",
		manual_2_stale.get("reason") == "OLDER_OR_DUPLICATE_SAVE_SEQUENCE",
		JSON.stringify(manual_2_stale),
	)
	_check("SAVE_RELOAD_REPLAY_GUARD_PRESERVED", manual_2_stale.get("reason") == "OLDER_OR_DUPLICATE_SAVE_SEQUENCE")

	# B1: THE core fix -- "autosave" slot's OWN save_sequence=1 is numerically
	# EQUAL to "manual"'s already-restored save_sequence=1, but a DIFFERENT
	# slot/namespace. Must be accepted, not rejected as a duplicate.
	var autosave_1_equal_seq: Dictionary = client.project_restore_snapshot(_fixture(3, 1), AUTOSAVE_SLOT)
	_check(
		"SAVE_RELOAD_EQUAL_SEQUENCE_DIFFERENT_SLOT_ACCEPTED",
		autosave_1_equal_seq.get("status") == "PASS",
		JSON.stringify(autosave_1_equal_seq),
	)
	_check("SAVE_RELOAD_MANUAL_TO_AUTOSAVE_ACCEPTED", autosave_1_equal_seq.get("status") == "PASS")

	# C1: "manual" again, with a genuinely newer save_sequence -- must still
	# work after autosave was touched in between (namespaces independent).
	var manual_3: Dictionary = client.project_restore_snapshot(_fixture(4, 2), MANUAL_SLOT)
	_check("SAVE_RELOAD_MANUAL_STILL_WORKS_AFTER_AUTOSAVE", manual_3.get("status") == "PASS", JSON.stringify(manual_3))

	# C2: "autosave" again, newer save_sequence -- reverse direction
	# (autosave -> manual -> autosave), same guarantee.
	var autosave_2: Dictionary = client.project_restore_snapshot(_fixture(5, 2), AUTOSAVE_SLOT)
	_check("SAVE_RELOAD_AUTOSAVE_TO_MANUAL_ACCEPTED", autosave_2.get("status") == "PASS", JSON.stringify(autosave_2))

	# D1: the GLOBAL restore_sequence guard must be untouched -- reusing the
	# same restore_sequence (5) already consumed by autosave_2 above, even
	# for a fresh, higher save_sequence, must still be rejected as stale.
	var manual_stale_restore: Dictionary = client.project_restore_snapshot(_fixture(5, 3), MANUAL_SLOT)
	_check(
		"SAVE_RELOAD_GLOBAL_RESTORE_SEQUENCE_GUARD_INTACT",
		manual_stale_restore.get("reason") == "STALE_OR_DUPLICATE_RESTORE_SNAPSHOT",
		JSON.stringify(manual_stale_restore),
	)

	# =====================================================================
	# GROUP 2 -- client never gets stuck at RELOAD_PENDING across a real
	# request_reload_resync() -> project_restore_snapshot() cycle, for both
	# directions (manual -> autosave and autosave -> manual). No live
	# backend/bridge connection needed: request_reload_resync() sets
	# _state=RELOAD_PENDING synchronously regardless of transport
	# availability, which is exactly the state this test needs to prove
	# recovers correctly on a legitimate cross-slot restore.
	# =====================================================================
	client.request_reload_resync(MANUAL_SLOT)
	_check("SAVE_RELOAD_STATE_PENDING_BEFORE_RESTORE_1", client.state() == AndromedaSaveReloadClient.STATE_RELOAD_PENDING)
	_check("VALID_RELOAD_REMAINS_PENDING_UNTIL_PROJECTION", client.state() == AndromedaSaveReloadClient.STATE_RELOAD_PENDING)
	var manual_4: Dictionary = client.project_restore_snapshot(_fixture(6, 4), MANUAL_SLOT)
	_check("SAVE_RELOAD_MANUAL_CYCLE_ACCEPTED", manual_4.get("status") == "PASS", JSON.stringify(manual_4))
	_check(
		"SAVE_RELOAD_CLIENT_NOT_STUCK_PENDING_MANUAL",
		client.state() == AndromedaSaveReloadClient.STATE_READY,
		"state=%s" % client.state(),
	)
	_check("VALID_RELOAD_PROJECTION_RETURNS_READY", client.state() == AndromedaSaveReloadClient.STATE_READY)

	client.request_reload_resync(AUTOSAVE_SLOT)
	_check("SAVE_RELOAD_STATE_PENDING_BEFORE_RESTORE_2", client.state() == AndromedaSaveReloadClient.STATE_RELOAD_PENDING)
	var autosave_3: Dictionary = client.project_restore_snapshot(_fixture(7, 3), AUTOSAVE_SLOT)
	_check("SAVE_RELOAD_AUTOSAVE_CYCLE_ACCEPTED", autosave_3.get("status") == "PASS", JSON.stringify(autosave_3))
	_check(
		"SAVE_RELOAD_CLIENT_NOT_STUCK_PENDING_AUTOSAVE",
		client.state() == AndromedaSaveReloadClient.STATE_READY,
		"state=%s" % client.state(),
	)

	# =====================================================================
	# GROUP 3 -- this round's fix: a LEGITIMATE rejection inside
	# project_restore_snapshot() (OLDER_OR_DUPLICATE_SAVE_SEQUENCE /
	# STALE_OR_DUPLICATE_RESTORE_SNAPSHOT / malformed payload) must release
	# RELOAD_PENDING back to the prior operational state, correlated
	# strictly by the real request_ref request_reload_resync() itself
	# returned -- never by guessing or by any rejection regardless of which
	# command it belongs to.
	# =====================================================================

	# Matching rejection: the pending request_ref is echoed back exactly as
	# the real bridge would echo it on the command result -> must clear
	# RELOAD_PENDING.
	var reload_intent_x: Dictionary = client.request_reload_resync(MANUAL_SLOT)
	_check("SAVE_RELOAD_PENDING_BEFORE_REJECTION_X", client.state() == AndromedaSaveReloadClient.STATE_RELOAD_PENDING)
	var pending_ref_x: String = str(reload_intent_x.get("request_ref", ""))
	_check("SAVE_RELOAD_PENDING_REQUEST_REF_CAPTURED_X", not pending_ref_x.is_empty())
	# save_sequence=4 duplicates _last_restored_save_sequence_by_slot[manual]
	# (set to 4 by manual_4 above) -- a genuine, still-enforced duplicate.
	var rejected_x: Dictionary = client.project_restore_snapshot(_fixture(8, 4), MANUAL_SLOT, pending_ref_x)
	_check(
		"SAVE_RELOAD_DUPLICATE_STILL_REJECTED",
		rejected_x.get("status") != "PASS" and rejected_x.get("reason") == "OLDER_OR_DUPLICATE_SAVE_SEQUENCE",
		JSON.stringify(rejected_x),
	)
	_check("SAVE_RELOAD_DUPLICATE_REASON_PRESERVED", rejected_x.get("reason") == "OLDER_OR_DUPLICATE_SAVE_SEQUENCE")
	_check(
		"SAVE_RELOAD_REJECTION_MATCHING_COMMAND_CLEARS_PENDING",
		client.state() == AndromedaSaveReloadClient.STATE_READY,
		"state=%s" % client.state(),
	)
	_check("SAVE_RELOAD_REJECTION_RETURNS_CLIENT_TO_OPERATIONAL_STATE", client.state() == AndromedaSaveReloadClient.STATE_READY)
	_check("SAVE_RELOAD_AFTER_REJECTION_NOT_STUCK_PENDING", client.state() != AndromedaSaveReloadClient.STATE_RELOAD_PENDING)

	# Immediately after the rejection: a real, unrelated valid command via
	# the client must be accepted, not just an internal state variable check.
	var save_after_rejection: Dictionary = client.request_manual_save(MANUAL_SLOT)
	_check("SAVE_AFTER_RELOAD_REJECTION_ACCEPTED", save_after_rejection.get("status") == "PASS", JSON.stringify(save_after_rejection))
	# request_manual_save() success moves the client to SAVE_PENDING; settle
	# it back to READY before the next sub-case so pending-state assertions
	# below are not confused by an unrelated save intent.
	client.project_save_result({
		"server_authoritative": true,
		"session_ref": (get_node_or_null("/root/ClientSession") as AndromedaClientSession).session_ref(),
		"request_ref": str(save_after_rejection.get("request_ref", "")),
		"result": "CONFIRMED",
		"result_sequence": 1,
		"save_ref": "SAVE-SLOTGUARD-POSTREJECTION",
		"save_sequence": 5,
		"reason": "OK",
	})

	# Unrelated rejection: a DIFFERENT (unrelated) request_ref must NOT clear
	# this client's current RELOAD_PENDING.
	var reload_intent_y: Dictionary = client.request_reload_resync(MANUAL_SLOT)
	_check("SAVE_RELOAD_PENDING_BEFORE_REJECTION_Y", client.state() == AndromedaSaveReloadClient.STATE_RELOAD_PENDING)
	var pending_ref_y: String = str(reload_intent_y.get("request_ref", ""))
	# save_sequence=4 still duplicates _last_restored_save_sequence_by_slot[manual]
	# (unchanged at 4 -- project_save_result() above never touches this
	# per-slot restore guard, only a successful restore projection does).
	var rejected_y: Dictionary = client.project_restore_snapshot(_fixture(10, 4), MANUAL_SLOT, "UNRELATED-REQUEST-REF-DOES-NOT-MATCH")
	_check("SAVE_RELOAD_UNRELATED_REJECTION_STILL_REJECTS_PAYLOAD", rejected_y.get("status") != "PASS", JSON.stringify(rejected_y))
	_check(
		"UNRELATED_REJECTION_DOES_NOT_CLEAR_RELOAD_PENDING",
		client.state() == AndromedaSaveReloadClient.STATE_RELOAD_PENDING,
		"state=%s" % client.state(),
	)
	# Now release it correctly, with the real matching request_ref, proving
	# correlation works both ways and leaving the client clean.
	var rejected_y2: Dictionary = client.project_restore_snapshot(_fixture(10, 4), MANUAL_SLOT, pending_ref_y)
	_check(
		"RELOAD_REJECTION_MATCHING_COMMAND_CLEARS_PENDING",
		rejected_y2.get("status") != "PASS" and client.state() == AndromedaSaveReloadClient.STATE_READY,
		"state=%s result=%s" % [client.state(), JSON.stringify(rejected_y2)],
	)

	_finish()


func _fixture(restore_sequence: int, save_sequence: int) -> Dictionary:
	var session := get_node_or_null("/root/ClientSession") as AndromedaClientSession
	var session_ref: String = session.session_ref() if session != null else SESSION_REF
	return {
		"server_authoritative": true,
		"session_ref": session_ref,
		"restore_ref": "RESTORE-SLOTGUARD-%06d" % restore_sequence,
		"restore_sequence": restore_sequence,
		"save_sequence": save_sequence,
		"player": {
			"position": {"iso_x_m": 0.0, "iso_y_m": 0.0, "altitude_m": 0.0},
			"presentation": {
				"stamina": {"fraction": 1.0, "activity": "INACTIVE"},
				"weapon_loadout": {"active_slot": 1},
				"profile_preferences": {"auto_pickup": true},
				"combat_presentation": {"player": {}, "targets": []},
			},
		},
		"world": {
			"active_cell": {"x": 0, "y": 0},
			"resource_snapshot": {
				"server_authoritative": true,
				"session_ref": session_ref,
				"snapshot_sequence": restore_sequence,
				"resources": [],
			},
		},
		"ground_loot_snapshot": {
			"server_authoritative": true,
			"session_ref": session_ref,
			"snapshot_sequence": restore_sequence,
			"ground_loot": [],
		},
		"profile_preference": {
			"auto_pickup": true,
			"preference_sequence": restore_sequence,
		},
		"inventory_snapshot": {
			"server_authoritative": true,
			"session_ref": session_ref,
			"snapshot_sequence": restore_sequence,
			"base_inventory": {"owner_ref": "PROFILE-SLOTGUARD", "slot_limit": 8, "weight_limit": 20.0, "stacks": []},
			"bag": {"state": "NO_BAG", "bag_ref": "", "capacity_slots": 0, "capacity_weight": 0.0, "contents": []},
			"equipment": {"slots": {}, "protected_critical_refs": []},
			"weapon_loadout": {
				"quick_slots": [
					{"slot": 1, "item_ref": "WEAPON-SLOTGUARD-ONE"},
					{"slot": 2, "item_ref": "WEAPON-SLOTGUARD-TWO"},
				],
				"active_slot": 1,
			},
			"carry": {"current_weight": 0.0, "max_weight": 20.0, "used_slots": 0, "max_slots": 8},
			"routing": {"source": "BASE_INVENTORY", "effective_inventory_owner_ref": "PROFILE-SLOTGUARD", "currency_wallet_owner_ref": "PROFILE-SLOTGUARD"},
		},
		"economy_projection": {
			"wallet": {"owner_ref": "PROFILE-SLOTGUARD", "balance": 100.0, "revision": save_sequence},
			"vendor_state_refs": [],
			"calculated_locally": false,
		},
		"quest_projection": {
			"offer_snapshot": {
				"server_authoritative": true, "session_ref": session_ref,
				"snapshot_sequence": restore_sequence, "offers": [],
			},
			"state_snapshot": {
				"server_authoritative": true, "session_ref": session_ref,
				"snapshot_sequence": restore_sequence, "quests": [],
			},
		},
		"dropped_bag_snapshot": {
			"server_authoritative": true, "session_ref": session_ref,
			"snapshot_sequence": restore_sequence, "dropped_bags": [], "complete_projection": false,
		},
		"death_recovery_snapshot": {
			"server_authoritative": true, "session_ref": session_ref,
			"restore_sequence": restore_sequence, "state": "ALIVE",
			"retention_projection": {}, "recovery_state_ref": "RECOVERY-SLOTGUARD-%06d" % restore_sequence,
		},
	}


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
		"gate": "SAVE_RELOAD_CLIENT_SLOT_GUARD",
	}
	if _failures.is_empty():
		print("ANDROMEDA_SAVE_RELOAD_CLIENT_SLOT_GUARD_GATE: PASS")
	else:
		push_error("ANDROMEDA_SAVE_RELOAD_CLIENT_SLOT_GUARD_GATE: FAIL %s" % JSON.stringify(_failures))
	print("ANDROMEDA_SAVE_RELOAD_CLIENT_SLOT_GUARD_SUMMARY: %s" % JSON.stringify(summary))
	get_tree().quit(0 if _failures.is_empty() else 1)
