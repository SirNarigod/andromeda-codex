from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import time
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
import sys

sys.path.insert(0, str(BACKEND_DIR))

from andromeda_authority_adapter import Stage16BAuthorityAdapter  # noqa: E402
from authority_config import AuthorityConfig, _resolve_master_path, verify_master  # noqa: E402


def build_config(root: pathlib.Path) -> AuthorityConfig:
    master = _resolve_master_path()
    return AuthorityConfig(
        master_release_path=master,
        master_release_sha256=verify_master(master),
        runtime_dir=PROJECT_ROOT / "01_RUNTIME",
        db_path=root / "world.sqlite",
        save_root=root / "saves",
        owner_scope="stage16b:combat-authority-test",
        world_seed=160800,
        player_class="WARRIOR",
        development_profile_bootstrap=True,
    )


class Stage16BAuthorityCombatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_combat_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session = "S16B-COMBAT"
        cls.adapter.bind_session(cls.session)
        cls.snapshot = cls.adapter.snapshot(cls.session)
        cls.common = next(row for row in cls.snapshot["combat_targets"] if row["slot"] == "COMMON")
        cls.alpha = next(row for row in cls.snapshot["combat_targets"] if row["slot"] == "ALPHA")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def attack(self, target_ref: str, command_ref: str, **extra: object) -> dict:
        return self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REQUEST_ATTACK",
                "command_ref": command_ref,
                "params": {"target_ref": target_ref, **extra},
            }
        )

    def test_01_snapshot_projects_real_stage07_hostile_encounter(self) -> None:
        targets = self.snapshot["combat_targets"]
        self.assertEqual(2, len(targets))
        self.assertEqual({"COMMON", "ALPHA"}, {row["slot"] for row in targets})
        self.assertTrue(all(row["hostile"] for row in targets))
        self.assertTrue(all(row["server_authoritative"] for row in targets))
        self.assertTrue(all(row["canonical_identity_mutation"] is False for row in targets))
        self.assertNotEqual(self.common["target_ref"], self.alpha["target_ref"])

    def test_02_development_encounter_uses_actor_and_combat_cores(self) -> None:
        encounter = self.adapter.development_profile_bootstrap["combat_encounter"]
        self.assertEqual("PASS", encounter["status"])
        self.assertFalse(encounter["canonical_identity_mutation"])
        self.assertTrue(encounter["runtime_gameplay_overlay_only"])
        self.assertTrue(all(row["actor_authority"] for row in encounter["targets"]))
        self.assertTrue(all(row["combat_authority"] for row in encounter["targets"]))

    def test_03_client_cannot_supply_combat_outcomes_or_actor_identity(self) -> None:
        for index, field in enumerate(
            ("damage", "critical", "hit", "cooldown_s", "player_ref", "xp")
        ):
            out = self.attack(
                self.common["target_ref"],
                f"S16B-COMBAT-FORGED-{index}",
                **{field: 999},
            )
            expected = (
                "CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN"
                if field in {"damage", "player_ref"}
                else "UNEXPECTED_COMMAND_PARAM"
            )
            self.assertEqual(expected, out["reason"], (field, out))

    def test_04_neutral_actor_is_not_reclassified_by_attack_request(self) -> None:
        actor_core = self.adapter._engine.actors_arpg(self.adapter.world_instance_id)
        encounter_refs = {self.common["target_ref"], self.alpha["target_ref"], self.adapter.avatar_ref}
        neutral_ref = None
        for npc in self.adapter._engine.country(self.adapter.world_instance_id)._all_npc_records():
            if npc["id"] in encounter_refs or npc.get("class") == "CHILD":
                continue
            actor = actor_core.ensure_actor(npc["id"])
            if actor["disposition"] == "NEUTRAL" and not actor["protected_identity"]:
                neutral_ref = npc["id"]
                break
        self.assertIsNotNone(neutral_ref)
        out = self.attack(str(neutral_ref), "S16B-COMBAT-NEUTRAL")
        self.assertEqual("TARGET_NOT_HOSTILE", out["reason"])
        self.assertEqual("NEUTRAL", actor_core.ensure_actor(str(neutral_ref))["disposition"])

    def test_05_valid_attack_is_fully_resolved_by_stage03(self) -> None:
        combat = self.adapter._engine.combat_arpg(self.adapter.world_instance_id)
        before = combat.ensure_enemy(self.common["target_ref"])
        out = self.attack(self.common["target_ref"], "S16B-COMBAT-VALID-1")
        after = combat.ensure_enemy(self.common["target_ref"])
        self.assertEqual("PASS", out["status"])
        self.assertTrue(out["server_authoritative"])
        self.assertTrue(out["hit_evaluated_server_side"])
        self.assertTrue(out["critical_evaluated_server_side"])
        self.assertTrue(out["damage_evaluated_server_side"])
        self.assertTrue(out["cooldown_evaluated_server_side"])
        self.assertEqual(out["health_after"], after["health"])
        self.assertLessEqual(after["health"], before["health"])

    def test_06_immediate_second_attack_is_rejected_by_core_cooldown(self) -> None:
        out = self.attack(self.common["target_ref"], "S16B-COMBAT-COOLDOWN-BLOCK")
        self.assertEqual("REJECTED", out["status"])
        self.assertEqual("ATTACK_COOLDOWN", out["reason"])
        self.assertGreater(float(out["remaining_s"]), 0.0)

    def test_07_server_elapsed_time_recovers_core_cooldown(self) -> None:
        time.sleep(1.05)
        out = self.attack(self.common["target_ref"], "S16B-COMBAT-AFTER-COOLDOWN")
        self.assertEqual("PASS", out["status"])
        self.assertFalse(out["runtime_pulse"]["client_delta_accepted"])
        self.assertGreaterEqual(float(out["runtime_pulse"]["server_elapsed_s"]), 1.0)

    def test_08_duplicate_command_does_not_apply_attack_twice(self) -> None:
        time.sleep(1.05)
        combat = self.adapter._engine.combat_arpg(self.adapter.world_instance_id)
        first = self.attack(self.alpha["target_ref"], "S16B-COMBAT-REPLAY")
        middle = combat.ensure_enemy(self.alpha["target_ref"])["health"]
        second = self.attack(self.alpha["target_ref"], "S16B-COMBAT-REPLAY")
        after = combat.ensure_enemy(self.alpha["target_ref"])["health"]
        self.assertEqual("PASS", first["status"])
        self.assertTrue(second["idempotent_replay"])
        self.assertTrue(second["replay_suppressed"])
        self.assertEqual(middle, after)

    def test_09_wrong_session_is_inert(self) -> None:
        combat = self.adapter._engine.combat_arpg(self.adapter.world_instance_id)
        before = combat.ensure_enemy(self.alpha["target_ref"])["health"]
        out = self.adapter.command(
            {
                "session_ref": "OTHER-SESSION",
                "command": "REQUEST_ATTACK",
                "command_ref": "S16B-COMBAT-WRONG-SESSION",
                "params": {"target_ref": self.alpha["target_ref"]},
            }
        )
        after = combat.ensure_enemy(self.alpha["target_ref"])["health"]
        self.assertEqual("UNKNOWN_OR_INACTIVE_SESSION", out["reason"])
        self.assertEqual(before, after)

    def test_10_non_lethal_attack_produces_no_physical_output(self) -> None:
        time.sleep(1.05)
        out = self.attack(self.alpha["target_ref"], "S16B-COMBAT-NO-DEFEAT")
        self.assertEqual("PASS", out["status"])
        self.assertFalse(out["enemy_defeated"])
        self.assertIsNone(out["enemy_physical_output"])
        self.assertEqual("NO_DEFEAT_THIS_ATTACK", out["enemy_loot_authority_status"])

    def test_11_development_enemy_carries_a_real_bag(self) -> None:
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        for row in self.snapshot["combat_targets"]:
            with self.subTest(slot=row["slot"]):
                carry = stage16a.water_bag.ensure_carry_profile(row["target_ref"])
                bag_ref = str(carry.get("equipped_bag_ref") or "")
                self.assertTrue(bag_ref, "development enemy must carry a real Bag")
                bag = stage16a.water_bag.bag(bag_ref)
                self.assertEqual(row["target_ref"], bag["property_owner_ref"])
                self.assertEqual("EQUIPPED", bag["state"])

    def test_12_defeat_drops_what_the_enemy_actually_carried(self) -> None:
        """No loot table is invented: the actor's carried contents become ENEMY loot."""
        target_ref = self.common["target_ref"]
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        bag_ref = str(
            stage16a.water_bag.ensure_carry_profile(target_ref).get("equipped_bag_ref") or ""
        )
        self.assertTrue(bag_ref)
        contents_before = self.adapter._bag_contents_summary(bag_ref)

        defeat: dict = {}
        for attempt in range(1, 61):
            time.sleep(1.05)
            out = self.attack(target_ref, f"S16B-COMBAT-DEFEAT-{attempt:03d}")
            if out.get("status") != "PASS":
                continue
            if out.get("enemy_defeated"):
                defeat = out
                break
        self.assertTrue(defeat, "authoritative defeat was never reached")
        type(self).lethal_command_ref = str(defeat["command_ref"])

        output = defeat["enemy_physical_output"]
        self.assertIsNotNone(output, defeat.get("enemy_loot_authority_status"))
        self.assertEqual(
            "STAGE16A_ENEMY_GROUND_LOOT_FROM_CARRIED_CONTENTS",
            defeat["enemy_loot_authority_status"],
        )
        self.assertEqual("ENEMY", output["source_kind"])
        self.assertEqual("GROUND_LOOT", output["output_form"])
        self.assertTrue(output["physical_world_first"])
        self.assertFalse(output["direct_to_inventory"])
        self.assertTrue(output["drop_refs"])

        # Every carried entry became a real ENEMY Ground Loot drop, none invented.
        carried_items = sorted(row["item_ref"] for row in contents_before)
        dropped_items = sorted(row["item_ref"] for row in output["drops"])
        self.assertEqual(carried_items, dropped_items)
        armor_row = next((row for row in output["drops"] if row["item_ref"] == "ITEM-ARMOR"), None)
        self.assertIsNotNone(armor_row, "DEV_ENEMY_ARMOR_OUTPUT_CREATED: ITEM-ARMOR must be part of the real ENEMY drop")
        type(self).armor_drop_ref = str(armor_row["drop_ref"])
        for row in output["drops"]:
            drop = stage16a.ground_loot.drop(row["drop_ref"])
            self.assertEqual("ENEMY", drop["source_kind"])
            self.assertEqual(target_ref, drop["source_ref"])
            self.assertTrue(drop["physical_world_first"])
            self.assertFalse(drop["direct_to_inventory"])
            self.assertEqual("ACTIVE", drop["state"])

        # The contents left the Bag exactly once: no duplication, no loss.
        self.assertEqual([], self.adapter._bag_contents_summary(bag_ref))

        # The Bag itself remains a recoverable world object still owned by the actor.
        bag = stage16a.water_bag.bag(bag_ref)
        self.assertEqual("DROPPED_LAND", bag["state"])
        self.assertIsNone(bag["carrier_ref"])
        self.assertEqual(target_ref, bag["property_owner_ref"])

        # Nothing reached the player's inventory as a result of the defeat.
        inventory = self.adapter._engine.items_arpg(
            self.adapter.world_instance_id
        ).inventory_snapshot(self.adapter.profile_ref)
        self.assertNotIn(bag_ref, set(inventory.get("instance_refs", [])))
        for row in output["drops"]:
            self.assertNotIn(row["item_ref"], set(inventory.get("stacks", {})))

    def test_12b_enemy_drops_reach_the_client_ground_loot_projection(self) -> None:
        snapshot = self.adapter.snapshot(self.session)
        enemy_drops = [
            row
            for row in snapshot.get("ground_loot", [])
            if str(row.get("source_kind", "")).upper() == "ENEMY"
        ]
        self.assertTrue(enemy_drops, "ENEMY Ground Loot must be projected to the client")
        for row in enemy_drops:
            self.assertTrue(str(row.get("target_ref", "")).startswith("DROP-S16A-"))
            self.assertFalse(row.get("direct_to_inventory"))

    def test_13_defeat_drop_is_replay_safe(self) -> None:
        """Re-issuing the lethal command_ref must not produce a second drop."""
        target_ref = self.common["target_ref"]
        lethal_ref = getattr(type(self), "lethal_command_ref", "")
        self.assertTrue(lethal_ref, "test_12 must record the lethal command_ref first")
        stage16a = self.adapter._engine.stage16a(self.adapter.world_instance_id)
        before = {row["drop_ref"] for row in stage16a.ground_loot.active_drops()}

        replay = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REQUEST_ATTACK",
                "command_ref": lethal_ref,
                "params": {"target_ref": target_ref},
            }
        )
        self.assertTrue(replay["idempotent_replay"])
        self.assertTrue(replay["replay_suppressed"])

        after = {row["drop_ref"] for row in stage16a.ground_loot.active_drops()}
        self.assertEqual(before, after, "replay must not spawn a second ENEMY drop")

    def test_14_armor_pickup_and_equip_is_fully_authoritative(self) -> None:
        """G16B-18/G16B-26: ITEM-ARMOR reaches the player only through the
        already-proven ENEMY -> Ground Loot -> pickup pipeline (test_12), then
        REQUEST_EQUIP_ITEM equips the resulting real instance_ref."""
        drop_ref = getattr(type(self), "armor_drop_ref", "")
        self.assertTrue(drop_ref, "test_12 must record the armor drop_ref first")
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        movement = self.adapter._engine.movement(self.adapter.world_instance_id)
        player_position = movement.state(self.adapter._player_ref)

        before_count = int(items.inventory_snapshot(self.adapter.profile_ref).get("instance_refs", []).__len__())
        armor_before_ref = items.inventory_snapshot(self.adapter.profile_ref)["equipped"].get("CHEST")
        self.assertIsNone(armor_before_ref, "setup requires CHEST to start empty for this proof")

        settle = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "CONFIRM_DROP_SETTLED",
                "command_ref": "S16B-ARMOR-SETTLE",
                "params": {
                    "target_ref": drop_ref,
                    "settled_position": {
                        "iso_x_m": float(player_position["iso_x_m"]),
                        "iso_y_m": float(player_position["iso_y_m"]),
                        "altitude_m": float(player_position.get("altitude_m", 0.0)),
                    },
                    "reachable": True,
                },
            }
        )
        self.assertEqual("PASS", settle["status"])

        pickup = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REQUEST_PICKUP",
                "command_ref": "S16B-ARMOR-PICKUP",
                "params": {"target_ref": drop_ref},
            }
        )
        self.assertEqual("PASS", pickup["status"], "DEV_ENEMY_ARMOR_PICKUP_AUTHORITATIVE")

        after_inventory = items.inventory_snapshot(self.adapter.profile_ref)
        new_armor_instances = [
            ref for ref in after_inventory.get("instance_refs", [])
            if items.instance(ref)["item_ref"] == "ITEM-ARMOR"
        ]
        self.assertEqual(1, len(new_armor_instances), "DEV_ENEMY_ARMOR_AVAILABLE_TO_PLAYER: exactly one real armor instance must now be owned by the player, no duplication")
        armor_instance_ref = new_armor_instances[0]

        equip = self.adapter.command(
            {
                "session_ref": self.session,
                "command": "REQUEST_EQUIP_ITEM",
                "command_ref": "S16B-ARMOR-EQUIP",
                "params": {"request_ref": "S16B-ARMOR-EQUIP:UI", "instance_ref": armor_instance_ref, "slot": "CHEST"},
            }
        )
        self.assertEqual("PASS", equip["status"])
        equipped_ref = items.inventory_snapshot(self.adapter.profile_ref)["equipped"].get("CHEST")
        self.assertEqual(armor_instance_ref, equipped_ref, "the item core must show the exact same real instance_ref equipped in CHEST")


class Stage16BDevelopmentCombatBindProvisioningTests(unittest.TestCase):
    """Proves the bind_session() development-target revalidation.

    Root cause this class guards against: _ensure_development_combat_encounter()
    used to run only once, inside _boot() (i.e. once per backend process). A backend
    process that binds more than one Godot session in a row -- exactly what the
    Combat gate does when it is run twice consecutively against the same running
    process -- never revalidated the COMMON/ALPHA development targets it had already
    handed out. A session bound after an earlier one had defeated its target then
    inherited that dead actor and every attack against it was rejected
    TARGET_ALREADY_DEFEATED.

    The fix reruns the same, unmodified _ensure_development_combat_encounter() on
    every successful bind_session() while development_profile_bootstrap is enabled.
    That function already reuses a pristine stored target untouched and only selects
    a different one when the stored target is missing, dead or partially damaged --
    never healing, never resurrecting. These tests exercise both branches directly
    against the real Stage07 cores, not a mock.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_bindprov_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root))
        cls.session_a = "S16B-BINDPROV-A"
        cls.adapter.bind_session(cls.session_a)
        snap_a = cls.adapter.snapshot(cls.session_a)
        cls.common_a = next(row for row in snap_a["combat_targets"] if row["slot"] == "COMMON")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def test_01_bind_reuses_pristine_target(self) -> None:
        """DEVELOPMENT_COMBAT_BIND_REUSES_PRISTINE_TARGET

        A second session bound while the previously-selected COMMON target is still
        untouched must not rotate to a different actor.
        """
        self.assertEqual("ALIVE", self.common_a["life_state"])
        self.assertEqual(self.common_a["health"], self.common_a["max_health"])

        session_b = "S16B-BINDPROV-B"
        self.adapter.bind_session(session_b)
        snap_b = self.adapter.snapshot(session_b)
        common_b = next(row for row in snap_b["combat_targets"] if row["slot"] == "COMMON")

        self.assertEqual(
            self.common_a["target_ref"],
            common_b["target_ref"],
            "an intact development target must not be rotated on a plain rebind",
        )
        self.assertEqual("ALIVE", common_b["life_state"])
        self.assertEqual(common_b["health"], common_b["max_health"])

    def test_02_bind_reselects_invalid_target(self) -> None:
        """DEVELOPMENT_COMBAT_BIND_RESELECTS_INVALID_TARGET

        Once the shared COMMON target has been defeated, the next bind on the same
        adapter/process must hand out a different, pristine COMMON target instead of
        the dead one -- and must never heal or resurrect the original.
        """
        target_ref = self.common_a["target_ref"]
        session_kill = "S16B-BINDPROV-KILL"
        self.adapter.bind_session(session_kill)

        life_state = "ALIVE"
        for attempt in range(40):
            result = self.adapter.command(
                {
                    "session_ref": session_kill,
                    "command": "REQUEST_ATTACK",
                    "command_ref": f"S16B-BINDPROV-KILL-{attempt}",
                    "params": {"target_ref": target_ref},
                }
            )
            life_state = result.get("target_state", {}).get("life_state", "ALIVE")
            if life_state == "DEFEATED":
                break
            time.sleep(1.2)  # real elapsed time, same as the gate, to clear the cooldown
        self.assertEqual("DEFEATED", life_state, "test setup failed to defeat the shared COMMON target")

        session_next = "S16B-BINDPROV-NEXT"
        self.adapter.bind_session(session_next)
        snap_next = self.adapter.snapshot(session_next)
        common_next = next(row for row in snap_next["combat_targets"] if row["slot"] == "COMMON")

        self.assertNotEqual(
            target_ref,
            common_next["target_ref"],
            "a defeated development target must never be reused by the next bind",
        )
        self.assertEqual("ALIVE", common_next["life_state"])
        self.assertEqual(
            common_next["health"],
            common_next["max_health"],
            "a reselected target must be pristine, never a partially damaged actor",
        )

        # The defeated original must not still be presented as a live combat target
        # under either slot -- proof this is a fresh selection, not a relabeled heal.
        stale_row = next(
            (row for row in snap_next["combat_targets"] if row["target_ref"] == target_ref),
            None,
        )
        self.assertIsNone(stale_row, "the defeated actor must not still be projected as a combat target")

    def test_03_reselection_never_heals_the_defeated_original(self) -> None:
        """The rejected original target's own authoritative state, read directly from
        the Stage03/07 combat core (not the snapshot projection), is untouched by the
        reselection performed in test_02: still DEFEATED, still at the HP it died at.
        """
        target_ref = self.common_a["target_ref"]
        combat = self.adapter._engine.combat_arpg(self.adapter.world_instance_id)
        state = combat.target_state(target_ref)
        self.assertEqual("DEFEATED", state["life_state"])
        self.assertEqual(0.0, float(state["health"]))


class Stage16BNonDevelopmentBindGuardTests(unittest.TestCase):
    """DEVELOPMENT_COMBAT_BIND_DISABLED_OUTSIDE_DEV_PROFILE

    The bind_session() revalidation added for the development combat encounter must
    have zero effect when development_profile_bootstrap is off, i.e. a normal,
    non-development profile. The only place combat_target_common_ref /
    combat_target_alpha_ref are ever written is inside
    _ensure_development_combat_encounter(); this class proves bind_session() never
    reaches it when the dev-profile flag is disabled, across repeated binds.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_nodevbind_")
        cls.root = pathlib.Path(cls._tmp.name)
        cfg = dataclasses.replace(build_config(cls.root), development_profile_bootstrap=False)
        cls.adapter = Stage16BAuthorityAdapter(cfg)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def test_01_bind_never_provisions_a_combat_encounter_outside_dev_profile(self) -> None:
        self.assertIsNone(self.adapter._bootstrap_get("combat_target_common_ref"))
        self.assertIsNone(self.adapter._bootstrap_get("combat_target_alpha_ref"))

        first = self.adapter.bind_session("S16B-NODEV-A")
        self.assertEqual("PASS", first.get("status"))
        self.assertIsNone(self.adapter._bootstrap_get("combat_target_common_ref"))
        self.assertIsNone(self.adapter._bootstrap_get("combat_target_alpha_ref"))

        # A second, later bind must equally leave the (still-absent) bootstrap alone.
        second = self.adapter.bind_session("S16B-NODEV-B")
        self.assertEqual("PASS", second.get("status"))
        self.assertIsNone(self.adapter._bootstrap_get("combat_target_common_ref"))
        self.assertIsNone(self.adapter._bootstrap_get("combat_target_alpha_ref"))

        # DEV_ACQUISITION_DISABLED_OUTSIDE_DEVELOPMENT_PROFILE: _ensure_enemy_carried_bag()
        # (the ITEM-ARMOR development acquisition route) has no other caller, so
        # with no encounter ever provisioned, the player owns no ITEM-ARMOR at all.
        items = self.adapter._engine.items_arpg(self.adapter.world_instance_id)
        items.ensure_inventory(self.adapter.profile_ref)
        inventory = items.inventory_snapshot(self.adapter.profile_ref)
        armor_owned = [ref for ref in inventory.get("instance_refs", []) if items.instance(ref)["item_ref"] == "ITEM-ARMOR"]
        self.assertEqual([], armor_owned)
        self.assertIsNone(inventory["equipped"].get("CHEST"))


def _fresh_bound_adapter(test: unittest.TestCase, prefix: str, session_ref: str) -> Stage16BAuthorityAdapter:
    """Build an isolated adapter with its own world, bind one session, and
    register cleanup on the given test. Used by the cross-slot tests below,
    each of which needs a scenario the shared class-level fixture cannot give
    them (partial damage on one slot only, both slots invalidated, etc.)."""
    tmp = tempfile.TemporaryDirectory(prefix=prefix)
    test.addCleanup(tmp.cleanup)
    adapter = Stage16BAuthorityAdapter(build_config(pathlib.Path(tmp.name)))
    test.addCleanup(adapter.close)
    adapter.bind_session(session_ref)
    return adapter


def _combat_row(adapter: Stage16BAuthorityAdapter, session_ref: str, slot: str) -> dict:
    snapshot = adapter.snapshot(session_ref)
    return next(row for row in snapshot["combat_targets"] if row["slot"] == slot)


def _attack_until(adapter: Stage16BAuthorityAdapter, session_ref: str, target_ref: str, stop_life_states, guard: int = 40) -> str:
    """Issue real REQUEST_ATTACK commands until target_state.life_state is one of
    stop_life_states (e.g. {"DEFEATED"}), or a single hit already left it partial
    (stop_life_states={"ALIVE"} with a health check done by the caller)."""
    life_state = "ALIVE"
    for attempt in range(guard):
        result = adapter.command(
            {
                "session_ref": session_ref,
                "command": "REQUEST_ATTACK",
                "command_ref": f"XSLOT-ATK-{prefix_ref(session_ref)}-{attempt}",
                "params": {"target_ref": target_ref},
            }
        )
        life_state = result.get("target_state", {}).get("life_state", "ALIVE")
        if life_state in stop_life_states:
            break
        time.sleep(1.2)
    return life_state


def prefix_ref(session_ref: str) -> str:
    return session_ref.replace(" ", "")


class Stage16BDevelopmentCombatCrossSlotTests(unittest.TestCase):
    """Proves the cross-slot reservation added to _ensure_development_combat_encounter().

    Root cause this class guards against: when a slot needs to reselect (its own
    stored target is dead or partially damaged), its candidate search and its reuse
    check could both land on the OTHER slot's own stored incumbent -- even while that
    incumbent was still pristine and untouched -- because the other slot's stored ref
    was never excluded. The slot processed first (COMMON) could "steal" the slot
    processed second (ALPHA)'s target, forcing an unnecessary rotation of a perfectly
    intact actor. The fix reserves each slot's stored incumbent from the other slot's
    search, symmetrically, before either slot is resolved.
    """

    def test_01_invalidating_common_does_not_rotate_pristine_alpha(self) -> None:
        """DEVELOPMENT_COMBAT_CROSS_SLOT_ALPHA_RESERVED_FROM_COMMON
        DEVELOPMENT_COMBAT_PRISTINE_ALPHA_NOT_ROTATED"""
        session = "S16B-XSLOT-A"
        adapter = _fresh_bound_adapter(self, "s16b_xslot_a_", session)
        common0 = _combat_row(adapter, session, "COMMON")
        alpha0 = _combat_row(adapter, session, "ALPHA")

        life_state = _attack_until(adapter, session, common0["target_ref"], {"DEFEATED"})
        self.assertEqual("DEFEATED", life_state, "setup failed to defeat COMMON")

        # ALPHA must still be exactly as it was, untouched, before the rebind.
        alpha_before_rebind = adapter._engine.combat_arpg(adapter.world_instance_id).target_state(alpha0["target_ref"])
        self.assertEqual("ALIVE", alpha_before_rebind["life_state"])
        self.assertEqual(alpha_before_rebind["health"], alpha_before_rebind["max_health"])

        adapter.bind_session(session)  # rebind on the same adapter -> re-provisions
        common1 = _combat_row(adapter, session, "COMMON")
        alpha1 = _combat_row(adapter, session, "ALPHA")

        self.assertNotEqual(common0["target_ref"], common1["target_ref"], "COMMON must reselect away from the dead actor")
        self.assertNotEqual(common1["target_ref"], alpha0["target_ref"], "COMMON reselection must never equal ALPHA's incumbent")
        self.assertEqual(alpha0["target_ref"], alpha1["target_ref"], "a pristine ALPHA must not be rotated by COMMON's reselection")
        self.assertEqual("ALIVE", alpha1["life_state"])
        self.assertEqual(alpha1["health"], alpha1["max_health"])

    def test_02_invalidating_alpha_does_not_rotate_pristine_common(self) -> None:
        """DEVELOPMENT_COMBAT_CROSS_SLOT_COMMON_RESERVED_FROM_ALPHA
        DEVELOPMENT_COMBAT_PRISTINE_COMMON_NOT_ROTATED (mirror of test_01)"""
        session = "S16B-XSLOT-B"
        adapter = _fresh_bound_adapter(self, "s16b_xslot_b_", session)
        common0 = _combat_row(adapter, session, "COMMON")
        alpha0 = _combat_row(adapter, session, "ALPHA")

        # Damage ALPHA without killing it: a single hit against a CHAMPION-scaled
        # target (armor + higher max HP) leaves it PARTIAL rather than DEFEATED,
        # proving the reservation also holds for a partially-damaged incumbent, not
        # only a fully dead one.
        result = adapter.command(
            {
                "session_ref": session,
                "command": "REQUEST_ATTACK",
                "command_ref": "XSLOT-B-HIT-0",
                "params": {"target_ref": alpha0["target_ref"]},
            }
        )
        ts = result.get("target_state", {})
        if ts.get("life_state") == "DEFEATED":
            # A single hit happened to be lethal on this seed; either way ALPHA is
            # now invalid and must be reselected -- the assertions below still hold.
            pass
        else:
            self.assertLess(float(ts.get("health", 0.0)), float(ts.get("max_health", 1.0)), "setup failed to leave ALPHA partially damaged")

        common_before_rebind = adapter._engine.combat_arpg(adapter.world_instance_id).target_state(common0["target_ref"])
        self.assertEqual("ALIVE", common_before_rebind["life_state"])
        self.assertEqual(common_before_rebind["health"], common_before_rebind["max_health"])

        adapter.bind_session(session)
        common1 = _combat_row(adapter, session, "COMMON")
        alpha1 = _combat_row(adapter, session, "ALPHA")

        self.assertNotEqual(alpha0["target_ref"], alpha1["target_ref"], "ALPHA must reselect away from the partially damaged actor")
        self.assertNotEqual(alpha1["target_ref"], common0["target_ref"], "ALPHA reselection must never equal COMMON's incumbent")
        self.assertEqual(common0["target_ref"], common1["target_ref"], "a pristine COMMON must not be rotated by ALPHA's reselection")
        self.assertEqual("ALIVE", common1["life_state"])
        self.assertEqual(common1["health"], common1["max_health"])

        # The old ALPHA actor's own state, read directly from the combat core, is
        # never healed by the reselection.
        old_alpha_state = adapter._engine.combat_arpg(adapter.world_instance_id).target_state(alpha0["target_ref"])
        if ts.get("life_state") == "DEFEATED":
            self.assertEqual("DEFEATED", old_alpha_state["life_state"])
        else:
            self.assertEqual(ts.get("health"), old_alpha_state["health"], "reselection must not heal the old ALPHA")

    def test_03_both_slots_invalid_selects_two_new_distinct_pristine_actors(self) -> None:
        """DEVELOPMENT_COMBAT_TARGETS_ALWAYS_DISTINCT (both-invalid branch of invariant 7)"""
        session = "S16B-XSLOT-C"
        adapter = _fresh_bound_adapter(self, "s16b_xslot_c_", session)
        common0 = _combat_row(adapter, session, "COMMON")
        alpha0 = _combat_row(adapter, session, "ALPHA")

        common_life = _attack_until(adapter, session, common0["target_ref"], {"DEFEATED"})
        self.assertEqual("DEFEATED", common_life)
        alpha_life = _attack_until(adapter, session, alpha0["target_ref"], {"DEFEATED"})
        self.assertEqual("DEFEATED", alpha_life)

        adapter.bind_session(session)
        common1 = _combat_row(adapter, session, "COMMON")
        alpha1 = _combat_row(adapter, session, "ALPHA")

        self.assertNotEqual(common0["target_ref"], common1["target_ref"])
        self.assertNotEqual(alpha0["target_ref"], alpha1["target_ref"])
        self.assertNotEqual(common1["target_ref"], alpha1["target_ref"], "COMMON and ALPHA must always be distinct")
        for row in (common1, alpha1):
            self.assertEqual("ALIVE", row["life_state"])
            self.assertEqual(row["health"], row["max_health"])

    def test_04_both_slots_pristine_repeated_binds_preserve_both_refs(self) -> None:
        """DEVELOPMENT_COMBAT_TARGETS_ALWAYS_DISTINCT held across repeated no-op binds,
        plus both DEVELOPMENT_COMBAT_PRISTINE_*_NOT_ROTATED invariants together."""
        session = "S16B-XSLOT-D"
        adapter = _fresh_bound_adapter(self, "s16b_xslot_d_", session)
        common0 = _combat_row(adapter, session, "COMMON")
        alpha0 = _combat_row(adapter, session, "ALPHA")
        self.assertNotEqual(common0["target_ref"], alpha0["target_ref"])

        for _ in range(3):
            adapter.bind_session(session)
            common_n = _combat_row(adapter, session, "COMMON")
            alpha_n = _combat_row(adapter, session, "ALPHA")
            self.assertEqual(common0["target_ref"], common_n["target_ref"])
            self.assertEqual(alpha0["target_ref"], alpha_n["target_ref"])
            self.assertNotEqual(common_n["target_ref"], alpha_n["target_ref"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
