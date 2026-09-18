"""G16B-09B: authoritative ACTIVE/SYSTEMIC zone streaming + Living state.

Backend-only round (G16B-09B). Implements and proves:

  - Stage16BAuthorityAdapter._streaming_projection(): authoritative,
    DERIVED (never persisted) zone classification. The player's real
    current zone_ref (world_arpg.profile_state()["zone_ref"]) is ACTIVE;
    every other real zone in the world (world_arpg.list_zones()) is
    SYSTEMIC. No client-supplied phase is ever accepted -- the function
    takes no external input at all besides the world's own state.

  - _zone_living_state(): a compact, real, mutable summary read straight
    from CountryScaleSystem.block(block_ref) -- the same structure
    CountryLivingDomainBridge.hunt_fauna() persists back to
    (fauna[].count/status). Proven genuinely evolvable below by calling
    hunt_fauna() directly through the engine (test-only direct access,
    no new transport -- see test_04_*), never through a fabricated
    fixture.

  - ADVANCE_DEVELOPMENT_LIVING_SYSTEMIC: a narrow, development-only
    command that triggers exactly one real
    ARPGLivingIntegrationCore.advance_and_reconcile() cycle (the
    "sealed Living orchestration" tick that already exists and is
    already bootstrapped on every Stage16B world) -- proving
    living_macro_context evolves through the real production tick, not
    a second, adapter-local simulation.

Both projection paths (REQUEST_SNAPSHOT via snapshot()["world_streaming"],
and REQUEST_RELOAD_RESYNC via _restore_snapshot_payload()["world"]
["streaming"]) reuse the exact same _streaming_projection() call -- no
duplicated logic, no persisted phase to go stale or roll back on save/
reload.

Scope note carried over from G16B-09B Section 3/33: cell-level PRELOAD
subdivision *within* the current zone is NOT implemented here -- no
existing code binds a MAP_SCALE_POLICIES area_scale to a real zone_ref,
and inventing one would be an arbitrary new zone policy this round's
authorization explicitly forbids. Only the zone-level ACTIVE (current)
vs SYSTEMIC (every other real zone) split is proven. This is reported,
not hidden -- see the closure report for this round.

G16B-09B2 adds ATTEMPT_DEVELOPMENT_SYSTEMIC_ZONE_HUNT: a narrow,
development-only command giving Godot/tests the SAME real per-zone Living
mutation the G16B-09B closure report proved only through direct test-only
engine access (CountryLivingDomainBridge.hunt_fauna()). The client
supplies only zone_ref; block_ref/npc_id/fauna_id/quantity are all
resolved server-side from real data, and the zone must already be
authoritatively SYSTEMIC per _streaming_projection() itself -- never a
client-supplied phase. This is a genuinely different granularity from
ADVANCE_DEVELOPMENT_LIVING_SYSTEMIC's country-wide aggregate tick: one
mutates a specific zone's zone_living_state, the other mutates
living_macro_context, and neither substitutes for the other.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import sys
import tempfile
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "01_RUNTIME"))

from andromeda_authority_adapter import Stage16BAuthorityAdapter  # noqa: E402
from authority_config import AuthorityConfig, _resolve_master_path, verify_master  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

COMMAND = "ADVANCE_DEVELOPMENT_LIVING_SYSTEMIC"


def build_config(root: pathlib.Path, owner_scope: str, *, seed: int = 990111) -> AuthorityConfig:
    master = _resolve_master_path()
    return AuthorityConfig(
        master_release_path=master,
        master_release_sha256=verify_master(master),
        runtime_dir=PROJECT_ROOT / "01_RUNTIME",
        db_path=root / "world.sqlite",
        save_root=root / "saves",
        owner_scope=owner_scope,
        world_seed=seed,
        player_class="WARRIOR",
        development_profile_bootstrap=True,
    )


class Stage16BLivingSystemicGuardTests(unittest.TestCase):
    """Development profile OFF -> REJECTED, zero Living mutation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_livingsys_guard_")
        cls.root = pathlib.Path(cls._tmp.name)
        cfg = dataclasses.replace(
            build_config(cls.root, "stage16b:living-systemic-guard"),
            development_profile_bootstrap=False,
        )
        cls.adapter = Stage16BAuthorityAdapter(cfg)
        cls.session = "S16B-LIVINGSYS-GUARD"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {"session_ref": self.session, "command": COMMAND, "command_ref": ref, "params": params}
        )

    def test_01_disabled_outside_development_profile_zero_mutation(self) -> None:
        living_core = self.adapter._engine.living_arpg(self.adapter.world_instance_id)
        before = living_core.snapshot()["metrics"]

        result = self.command("G09B-GUARD-ADVANCE", {"request_ref": "G09B-GUARD-ADVANCE:UI"})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual(
            "DEV_LIVING_SYSTEMIC_COMMAND_DISABLED_OUTSIDE_DEVELOPMENT_PROFILE", result["reason"]
        )
        after = living_core.snapshot()["metrics"]
        self.assertEqual(before, after, "zero Living mutation on rejection")

    def test_02_projection_still_production_available_without_dev_profile(self) -> None:
        # Section 20: the projection itself is PRODUCTION, must not depend
        # on development_profile_bootstrap.
        proj = self.adapter._streaming_projection()
        self.assertIn("current_zone_ref", proj)
        self.assertGreater(len(proj["zones"]), 0)
        active = [z for z in proj["zones"] if z["stream_phase"] == "ACTIVE"]
        self.assertEqual(1, len(active))
        self.assertEqual(proj["current_zone_ref"], active[0]["zone_ref"])


class Stage16BLivingSystemicTransportTests(unittest.TestCase):
    """Transport-shape validation, enablement, replay/idempotency."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_livingsys_transport_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root, "stage16b:living-systemic-transport"))
        cls.session = "S16B-LIVINGSYS-TRANSPORT"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {"session_ref": self.session, "command": COMMAND, "command_ref": ref, "params": params}
        )

    def test_01_advertised_in_enabled_commands(self) -> None:
        bind = self.adapter.bind_session("S16B-LIVINGSYS-TRANSPORT-BIND-PROBE")
        self.assertIn(COMMAND, bind["enabled_commands"])

    def test_02_unexpected_param_is_rejected(self) -> None:
        result = self.command("G09B-UNEXPECTED", {"request_ref": "G09B-UNEXPECTED:UI", "bogus": True})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("UNEXPECTED_COMMAND_PARAM", result["reason"])

    def test_03_client_cannot_supply_zone_ref_or_phase_or_metrics(self) -> None:
        # G09_NO_CLIENT_SUPPLIED_STREAM_PHASE: none of these gameplay
        # fields are in the allowlist -- every one is rejected as an
        # unexpected param, never silently accepted/ignored.
        for forbidden_field, value in (
            ("zone_ref", "ZONE-STA-01-BLK-01"),
            ("stream_phase", "SYSTEMIC"),
            ("fauna_total_population", 0),
            ("living_steps", 5),
        ):
            with self.subTest(field=forbidden_field):
                result = self.command(
                    f"G09B-FORBIDDEN-{forbidden_field}",
                    {"request_ref": f"G09B-FORBIDDEN-{forbidden_field}:UI", forbidden_field: value},
                )
                self.assertEqual("REJECTED", result["status"])
                self.assertEqual("UNEXPECTED_COMMAND_PARAM", result["reason"])

    def test_04_accepted_call_is_server_authoritative_single_cycle(self) -> None:
        result = self.command("G09B-BASIC-TICK", {"request_ref": "G09B-BASIC-TICK:UI"})
        self.assertEqual("PASS", result["status"])
        self.assertTrue(result["server_authoritative"])
        self.assertTrue(result["development_only"])
        self.assertTrue(result["grants_nothing"])
        self.assertFalse(result["zone_or_phase_client_supplied"])
        self.assertEqual("ADVANCE_DEVELOPMENT_LIVING_SYSTEMIC", result["command"])
        self.assertEqual(1, result["living_steps"]["steps"])

    def test_05_replay_same_command_ref_no_double_evolution(self) -> None:
        living_core = self.adapter._engine.living_arpg(self.adapter.world_instance_id)
        first = self.command("G09B-REPLAY-REF", {"request_ref": "G09B-REPLAY-REF:UI"})
        self.assertEqual("PASS", first["status"])
        self.assertFalse(first["idempotent_replay"])
        metrics_after_first = living_core.snapshot()["metrics"]

        second = self.command("G09B-REPLAY-REF", {"request_ref": "G09B-REPLAY-REF:UI"})
        self.assertTrue(second["idempotent_replay"], "G09_DEV_LIVING_TICK_REPLAY_SUPPRESSED")
        metrics_after_second = living_core.snapshot()["metrics"]
        self.assertEqual(
            metrics_after_first, metrics_after_second, "G09_DEV_LIVING_TICK_NO_DOUBLE_EVOLUTION"
        )


class Stage16BLivingSystemicZoneIdentityTests(unittest.TestCase):
    """Real zone_ref/block_ref identity, ACTIVE=current only, SYSTEMIC=rest."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_livingsys_zoneid_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root, "stage16b:living-systemic-zoneid"))
        cls.session = "S16B-LIVINGSYS-ZONEID"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def test_01_zone_ref_real_and_block_link_real(self) -> None:
        # G09_ZONE_REF_REAL / G09_ZONE_BLOCK_LINK_REAL
        world_arpg = self.adapter._engine.world_arpg(self.adapter.world_instance_id)
        current_zone_ref = str(world_arpg.profile_state(self.adapter.profile_ref)["zone_ref"])
        zone = world_arpg.zone(current_zone_ref)
        self.assertEqual(current_zone_ref, zone["zone_ref"])
        block_ref = zone["block_ref"]
        self.assertTrue(block_ref)

        country = self.adapter._engine.country(self.adapter.world_instance_id)
        block = country.block(block_ref)  # raises KeyError if not real -- must not raise
        self.assertEqual(block_ref, block["id"])

    def test_02_zone_living_domain_real(self) -> None:
        # G09_ZONE_LIVING_DOMAIN_REAL: the domain bridge genuinely exists
        # and is attached to this exact CountryScaleSystem.
        bridge = self.adapter._engine.bridge(self.adapter.world_instance_id)
        country = self.adapter._engine.country(self.adapter.world_instance_id)
        self.assertIs(country.domain_bridge, bridge)
        integrity = bridge.full_integrity_check()
        self.assertEqual("PASS", integrity["status"], integrity.get("failures"))

    def test_03_current_zone_active_all_others_systemic_no_invented_tier(self) -> None:
        proj = self.adapter._streaming_projection()
        world_arpg = self.adapter._engine.world_arpg(self.adapter.world_instance_id)
        real_zone_refs = {str(z["zone_ref"]) for z in world_arpg.list_zones()}
        projected_refs = {z["zone_ref"] for z in proj["zones"]}
        self.assertEqual(real_zone_refs, projected_refs, "every projected zone is a real zone, no fixture")

        phases = {z["zone_ref"]: z["stream_phase"] for z in proj["zones"]}
        self.assertEqual({"ACTIVE", "SYSTEMIC"}, set(phases.values()), "no invented third zone tier")
        active_refs = [ref for ref, phase in phases.items() if phase == "ACTIVE"]
        self.assertEqual([proj["current_zone_ref"]], active_refs)

    def test_04_distant_zone_real_and_systemic_with_real_living_state(self) -> None:
        # G09_DISTANT_ZONE_REAL / G09_DISTANT_ZONE_SYSTEMIC_AUTHORITATIVE /
        # G09_SYSTEMIC_ZONE_HAS_REAL_LIVING_STATE
        proj = self.adapter._streaming_projection()
        systemic = [z for z in proj["zones"] if z["stream_phase"] == "SYSTEMIC"]
        self.assertGreater(len(systemic), 0, "world must have at least one real distant zone")
        distant = systemic[0]
        self.assertNotEqual(proj["current_zone_ref"], distant["zone_ref"])
        living_state = distant["zone_living_state"]
        self.assertEqual(distant["block_ref"], living_state["block_ref"])
        self.assertIn("fauna_total_population", living_state)
        self.assertIn("fauna_species_count", living_state)
        self.assertGreaterEqual(living_state["fauna_species_count"], 0)

    def test_05_phase_is_derived_not_persisted(self) -> None:
        # G09_SYSTEMIC_PHASE_DERIVED_NOT_PERSISTED: no phase-storing table
        # exists at all -- confirm by checking the schema has no such table.
        tables = {
            row["name"]
            for row in self.adapter._engine.runtime.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        phase_tables = {t for t in tables if "stream" in t.lower() and "phase" in t.lower()}
        self.assertEqual(set(), phase_tables, "no persisted stream_phase table exists")


class Stage16BLivingSystemicEvolutionTests(unittest.TestCase):
    """T0 -> production tick -> T1, remaining SYSTEMIC throughout."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_livingsys_evolution_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root, "stage16b:living-systemic-evolution"))
        cls.session = "S16B-LIVINGSYS-EVOLUTION"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {"session_ref": self.session, "command": COMMAND, "command_ref": ref, "params": params}
        )

    def test_01_production_tick_evolves_living_macro_context_zone_stays_systemic(self) -> None:
        # T0
        proj_t0 = self.adapter._streaming_projection()
        systemic_before = {z["zone_ref"]: z["stream_phase"] for z in proj_t0["zones"] if z["stream_phase"] == "SYSTEMIC"}
        self.assertGreater(len(systemic_before), 0)
        macro_t0 = proj_t0["living_macro_context"]

        # Production tick, via the real core -- not a second simulation.
        result = self.command("G09B-EVOLVE-TICK", {"request_ref": "G09B-EVOLVE-TICK:UI"})
        self.assertEqual("PASS", result["status"])

        # T1
        proj_t1 = self.adapter._streaming_projection()
        macro_t1 = proj_t1["living_macro_context"]

        # G09_SYSTEMIC_STATE_T1_REAL / G09_SYSTEMIC_LIVING_STATE_CHANGED
        self.assertNotEqual(macro_t0["metrics"], macro_t1["metrics"], "living_macro_context genuinely changed")
        self.assertNotEqual(macro_t0["resilience_index"], macro_t1["resilience_index"])

        # G09_SYSTEMIC_REMAINED_SYSTEMIC: the same zones checked at T0 are
        # still SYSTEMIC at T1 -- the tick never promotes anything, because
        # it never touches player position at all.
        systemic_after = {z["zone_ref"]: z["stream_phase"] for z in proj_t1["zones"] if z["stream_phase"] == "SYSTEMIC"}
        for zone_ref in systemic_before:
            self.assertEqual("SYSTEMIC", systemic_after.get(zone_ref), f"{zone_ref} must remain SYSTEMIC")
        self.assertEqual(proj_t0["current_zone_ref"], proj_t1["current_zone_ref"], "player position untouched by the tick")

        # G09_SYSTEMIC_EVOLUTION_SERVER_AUTHORITATIVE: the projection call
        # itself takes no external input -- see _streaming_projection()'s
        # signature (self only). Nothing about T1 could have been supplied
        # by a caller.

    def test_02_per_zone_living_state_genuinely_mutable_via_real_domain_action(self) -> None:
        # G09_SYSTEMIC_EVOLUTION_NOT_GODOT_FIXTURE, and honest per Section 21:
        # advance_and_reconcile() (test_01 above) changes living_macro_context
        # (country-aggregate), NOT any single zone's zone_living_state --
        # confirmed by direct inspection of run_cycle()'s effects (fixed
        # anchor refs: BRIDGE_REF/WAREHOUSE_REF/WORKSHOP_REF/MARKET_REF, no
        # per-block attribution). Per-zone Living evolution (fauna decline)
        # is proven here instead via the REAL, already-existing
        # CountryLivingDomainBridge.hunt_fauna() -- called directly through
        # the engine the adapter already holds, exactly as this test module
        # (like every other Stage16B test) directly drives protected cores
        # for setup. This is NOT new transport: no command/params were
        # added for it, and Godot still has zero route to invoke it. It
        # exists to prove the zone_living_state FIELD reflects genuinely
        # mutable data, not to claim it is production-reachable yet -- that
        # gap is reported, not hidden (see closure report Section 22).
        proj = self.adapter._streaming_projection()
        country = self.adapter._engine.country(self.adapter.world_instance_id)
        bridge = self.adapter._engine.bridge(self.adapter.world_instance_id)

        armed_npc = None
        target_block_ref = None
        for n in country._all_npc_records():
            if n["id"] == self.adapter._player_ref or n.get("class") == "CHILD":
                continue
            inv = n.get("inventory", {})
            if not any(str(k).startswith("WPN-") and int(v) > 0 for k, v in inv.items()):
                continue
            block_id = n.get("block_id")
            zone_entry = next((z for z in proj["zones"] if z["block_ref"] == block_id), None)
            if zone_entry and zone_entry["stream_phase"] == "SYSTEMIC" and zone_entry["zone_living_state"]["fauna_species_count"] > 0:
                armed_npc = n
                target_block_ref = block_id
                break
        self.assertIsNotNone(armed_npc, "world must contain a real armed NPC in a real SYSTEMIC block with fauna")

        target_zone_ref = next(z["zone_ref"] for z in proj["zones"] if z["block_ref"] == target_block_ref)
        block_before = country.block(target_block_ref)
        fauna_id = block_before["fauna"][0]["id"]
        population_before = self.adapter._zone_living_state(block_before)["fauna_total_population"]

        hunt_result = bridge.hunt_fauna(
            npc_id=armed_npc["id"], block_id=target_block_ref, fauna_id=fauna_id, quantity=1
        )
        self.assertEqual("PASS", hunt_result["status"])
        self.assertEqual(1, hunt_result["killed"])

        proj_after = self.adapter._streaming_projection()
        after_entry = next(z for z in proj_after["zones"] if z["zone_ref"] == target_zone_ref)
        self.assertEqual("SYSTEMIC", after_entry["stream_phase"], "hunting a distant block never materializes it")
        population_after = after_entry["zone_living_state"]["fauna_total_population"]
        self.assertEqual(population_before - 1, population_after, "zone_living_state reflects the real mutation")

    def test_03_snapshot_and_restore_projections_are_json_serializable(self) -> None:
        snapshot = self.adapter.snapshot(self.session)
        self.assertEqual("PASS", snapshot["status"])
        self.assertIn("world_streaming", snapshot)
        response = JSONResponse(snapshot)
        rendered = response.render(snapshot)  # raises ValueError on NaN/inf (allow_nan=False)
        self.assertGreater(len(rendered), 0)


class Stage16BLivingSystemicSaveReloadTests(unittest.TestCase):
    """SYSTEMIC zone identity and Living state survive save/reload."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_livingsys_savereload_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root, "stage16b:living-systemic-savereload"))
        cls.session = "S16B-LIVINGSYS-SAVERELOAD"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, name: str, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {"session_ref": self.session, "command": name, "command_ref": ref, "params": params}
        )

    def test_01_systemic_living_state_and_macro_context_persist_across_reload(self) -> None:
        proj_before = self.adapter._streaming_projection()
        target_zone_ref = next(z["zone_ref"] for z in proj_before["zones"] if z["stream_phase"] == "SYSTEMIC")

        # Real production tick BEFORE save, so living_macro_context has
        # genuinely moved away from its boot-time value.
        tick = self.command(COMMAND, "G09B-SR-TICK", {"request_ref": "G09B-SR-TICK:UI"})
        self.assertEqual("PASS", tick["status"])
        proj_pre_save = self.adapter._streaming_projection()
        macro_pre_save = proj_pre_save["living_macro_context"]
        target_entry_pre_save = next(z for z in proj_pre_save["zones"] if z["zone_ref"] == target_zone_ref)
        self.assertEqual("SYSTEMIC", target_entry_pre_save["stream_phase"])
        living_state_pre_save = target_entry_pre_save["zone_living_state"]

        saved = self.command(
            "REQUEST_SAVE", "G09B-SR-SAVE",
            {
                "request_ref": "G09B-SR-SAVE:UI", "slot_ref": "g09bliving", "save_kind": "MANUAL",
                "reason": "G16B09B_LIVING_SYSTEMIC_CONTINUITY", "client_presentation_only": True,
            },
        )
        self.assertEqual("CONFIRMED", saved["result"])

        restored = self.command(
            "REQUEST_RELOAD_RESYNC", "G09B-SR-RELOAD",
            {
                "request_ref": "G09B-SR-RELOAD:UI", "slot_ref": "g09bliving",
                "require_resync_before_ready": True, "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", restored["status"])

        # G09_SYSTEMIC_ZONE_IDENTITY_PERSISTS / G09_SYSTEMIC_STATE_PERSISTS_SAVE_RELOAD
        restore_streaming = restored["restore_snapshot"]["world"]["streaming"]
        restored_entry = next(z for z in restore_streaming["zones"] if z["zone_ref"] == target_zone_ref)
        self.assertEqual("SYSTEMIC", restored_entry["stream_phase"], "phase recalculated fresh, still SYSTEMIC")
        self.assertEqual(living_state_pre_save, restored_entry["zone_living_state"], "G09_SYSTEMIC_NO_STATE_ROLLBACK")
        self.assertEqual(macro_pre_save["metrics"], restore_streaming["living_macro_context"]["metrics"])

        # Confirm via a fresh, independent snapshot() call too (self._engine
        # was replaced in place by the reload; the adapter's own methods
        # re-resolve it, so no stale reference risk here).
        proj_after = self.adapter._streaming_projection()
        after_entry = next(z for z in proj_after["zones"] if z["zone_ref"] == target_zone_ref)
        self.assertEqual("SYSTEMIC", after_entry["stream_phase"])
        self.assertEqual(living_state_pre_save, after_entry["zone_living_state"])


class Stage16BLivingSystemicZoneHuntTests(unittest.TestCase):
    """ATTEMPT_DEVELOPMENT_SYSTEMIC_ZONE_HUNT: real per-zone Living mutation.

    world_seed=990111 (this file's default, see build_config()) is fully
    deterministic: ZONE-STA-01-BLK-05 always has a real armed NPC and real
    fauna, so hunt_fauna() genuinely succeeds there. Other SYSTEMIC zones
    at this seed legitimately reject with NO_OWNED_WEAPON (the domain's
    own decision, not a bug) -- proven explicitly in test_02 below rather
    than hidden.
    """

    WORKING_ZONE_REF = "ZONE-STA-01-BLK-05"
    COMMAND = "ATTEMPT_DEVELOPMENT_SYSTEMIC_ZONE_HUNT"

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_livingsys_zonehunt_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root, "stage16b:living-systemic-zonehunt"))
        cls.session = "S16B-LIVINGSYS-ZONEHUNT"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {"session_ref": self.session, "command": self.COMMAND, "command_ref": ref, "params": params}
        )

    def test_01_advertised_and_disabled_outside_development_profile(self) -> None:
        bind = self.adapter.bind_session("S16B-ZONEHUNT-BIND-PROBE")
        self.assertIn(self.COMMAND, bind["enabled_commands"])

        guard_root = pathlib.Path(tempfile.mkdtemp(prefix="s16b_zonehunt_guard_"))
        cfg = dataclasses.replace(
            build_config(guard_root, "stage16b:living-systemic-zonehunt-guard"),
            development_profile_bootstrap=False,
        )
        guard_adapter = Stage16BAuthorityAdapter(cfg)
        try:
            guard_session = "S16B-ZONEHUNT-GUARD"
            guard_adapter.bind_session(guard_session)
            country = guard_adapter._engine.country(guard_adapter.world_instance_id)
            block_before = country.block(
                guard_adapter._engine.world_arpg(guard_adapter.world_instance_id)
                .zone(self.WORKING_ZONE_REF)["block_ref"]
            )
            fauna_before = json.loads(json.dumps(block_before["fauna"]))

            result = guard_adapter.command(
                {
                    "session_ref": guard_session, "command": self.COMMAND, "command_ref": "GUARD-HUNT",
                    "params": {"request_ref": "GUARD-HUNT:UI", "zone_ref": self.WORKING_ZONE_REF},
                }
            )
            self.assertEqual("REJECTED", result["status"])
            self.assertEqual("DEV_SYSTEMIC_HUNT_DISABLED_OUTSIDE_DEVELOPMENT_PROFILE", result["reason"])

            block_after = country.block(
                guard_adapter._engine.world_arpg(guard_adapter.world_instance_id)
                .zone(self.WORKING_ZONE_REF)["block_ref"]
            )
            self.assertEqual(fauna_before, block_after["fauna"], "zero Living mutation on rejection")

            # G20: production projection itself is NOT gated by dev profile.
            proj = guard_adapter._streaming_projection()
            self.assertGreater(len(proj["zones"]), 0)
        finally:
            guard_adapter.close()

    def test_02_unexpected_and_forbidden_client_params_rejected(self) -> None:
        result = self.command("ZONEHUNT-UNEXPECTED", {"request_ref": "x", "zone_ref": self.WORKING_ZONE_REF, "bogus": True})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("UNEXPECTED_COMMAND_PARAM", result["reason"])

        # These are all rejected before ever reaching hunt_fauna(), but by
        # two DIFFERENT, layered guards: npc_ref is caught by the adapter's
        # general FORBIDDEN_AUTHORITY_KEYS scan (find_forbidden_field(),
        # shared by every command in this file, not something this round
        # added) BEFORE this command's own params allowlist even runs;
        # everything else falls through to this command's own allowlist.
        # Both are real, both prove the client cannot supply an
        # authoritative identity/result field -- documented here rather
        # than silently expecting one uniform reason.
        for forbidden_field, value, expected_reason in (
            ("block_ref", "STA-01-BLK-05", "UNEXPECTED_COMMAND_PARAM"),
            ("npc_ref", "NPC-01-05-01-002", "CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN"),
            ("fauna_ref", "FAU-BROWSER-01-05-01", "UNEXPECTED_COMMAND_PARAM"),
            ("quantity", 5, "UNEXPECTED_COMMAND_PARAM"),
            ("stream_phase", "SYSTEMIC", "UNEXPECTED_COMMAND_PARAM"),
            ("population_delta", -1, "UNEXPECTED_COMMAND_PARAM"),
        ):
            with self.subTest(field=forbidden_field):
                result = self.command(
                    f"ZONEHUNT-FORBIDDEN-{forbidden_field}",
                    {"request_ref": "x", "zone_ref": self.WORKING_ZONE_REF, forbidden_field: value},
                )
                self.assertEqual("REJECTED", result["status"])
                self.assertEqual(expected_reason, result["reason"])

    def test_03_zone_ref_required(self) -> None:
        result = self.command("ZONEHUNT-NO-ZONE", {"request_ref": "x"})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("DEV_SYSTEMIC_HUNT_ZONE_REF_REQUIRED", result["reason"])

    def test_04_unknown_zone_ref_rejected(self) -> None:
        # G09_DISTANT... no fabricated ref accepted as real.
        result = self.command("ZONEHUNT-UNKNOWN", {"request_ref": "x", "zone_ref": "ZONE-BOGUS-DOES-NOT-EXIST"})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("DEV_SYSTEMIC_HUNT_UNKNOWN_ZONE_REF", result["reason"])

    def test_05_active_zone_rejected_no_client_supplied_phase_bypass(self) -> None:
        proj = self.adapter._streaming_projection()
        current_zone_ref = proj["current_zone_ref"]
        result = self.command("ZONEHUNT-ACTIVE", {"request_ref": "x", "zone_ref": current_zone_ref})
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("DEV_SYSTEMIC_HUNT_REQUIRES_AUTHORITATIVE_SYSTEMIC_PHASE", result["reason"])

    def test_06_legitimate_domain_rejection_returned_verbatim_no_retry(self) -> None:
        # A SYSTEMIC zone at this seed whose deterministically-first
        # eligible NPC genuinely has no owned weapon -- the domain's own
        # decision, returned as-is, never silently retried against a
        # different NPC in the same block.
        result = self.command(
            "ZONEHUNT-NO-WEAPON", {"request_ref": "x", "zone_ref": "ZONE-STA-01-BLK-01"}
        )
        self.assertEqual("REJECTED", result["status"])
        self.assertEqual("NO_OWNED_WEAPON", result["reason"])

    def test_07_t0_action_t1_zone_remains_systemic_player_zone_unchanged(self) -> None:
        proj_t0 = self.adapter._streaming_projection()
        current_zone_before = proj_t0["current_zone_ref"]
        entry_t0 = next(z for z in proj_t0["zones"] if z["zone_ref"] == self.WORKING_ZONE_REF)
        self.assertEqual("SYSTEMIC", entry_t0["stream_phase"])
        living_t0 = entry_t0["zone_living_state"]

        result = self.command("ZONEHUNT-T0T1", {"request_ref": "x", "zone_ref": self.WORKING_ZONE_REF})
        self.assertEqual("PASS", result["status"])
        self.assertEqual("CombatSystem", result["engine"])
        self.assertEqual("CountryLivingDomainBridge", result["bridge"])
        self.assertEqual(1, result["killed"])
        self.assertTrue(result["server_authoritative"])
        self.assertTrue(result["development_only"])
        self.assertFalse(result["zone_promoted_to_active"])
        self.assertEqual(self.WORKING_ZONE_REF, result["zone_ref"])
        self.assertEqual(entry_t0["block_ref"], result["block_ref"])

        proj_t1 = self.adapter._streaming_projection()
        entry_t1 = next(z for z in proj_t1["zones"] if z["zone_ref"] == self.WORKING_ZONE_REF)
        # G09_SYSTEMIC_ZONE_REMAINED_SYSTEMIC / G09_SYSTEMIC_ACTION_DID_NOT_PROMOTE_ZONE
        self.assertEqual("SYSTEMIC", entry_t1["stream_phase"])
        living_t1 = entry_t1["zone_living_state"]

        # G09_SYSTEMIC_ZONE_LIVING_CHANGED
        self.assertNotEqual(living_t0, living_t1)
        self.assertEqual(
            living_t0["fauna_total_population"] - 1, living_t1["fauna_total_population"]
        )

        # G09_PLAYER_ZONE_UNCHANGED
        self.assertEqual(current_zone_before, proj_t1["current_zone_ref"])

    def test_08_replay_same_command_ref_no_double_mutation(self) -> None:
        proj_before = self.adapter._streaming_projection()
        entry_before = next(z for z in proj_before["zones"] if z["zone_ref"] == self.WORKING_ZONE_REF)
        population_before = entry_before["zone_living_state"]["fauna_total_population"]

        first = self.command("ZONEHUNT-REPLAY", {"request_ref": "x", "zone_ref": self.WORKING_ZONE_REF})
        self.assertEqual("PASS", first["status"])
        self.assertFalse(first["idempotent_replay"])

        second = self.command("ZONEHUNT-REPLAY", {"request_ref": "x", "zone_ref": self.WORKING_ZONE_REF})
        self.assertTrue(second["idempotent_replay"], "G09_SYSTEMIC_ZONE_HUNT_REPLAY_SUPPRESSED")

        proj_after = self.adapter._streaming_projection()
        entry_after = next(z for z in proj_after["zones"] if z["zone_ref"] == self.WORKING_ZONE_REF)
        population_after = entry_after["zone_living_state"]["fauna_total_population"]
        self.assertEqual(
            population_before - 1, population_after, "G09_SYSTEMIC_ZONE_HUNT_NO_DOUBLE_MUTATION"
        )

    def test_09_response_json_serializable(self) -> None:
        result = self.command("ZONEHUNT-JSON", {"request_ref": "x", "zone_ref": self.WORKING_ZONE_REF})
        response = JSONResponse(result)
        rendered = response.render(result)
        self.assertGreater(len(rendered), 0)
        snapshot = self.adapter.snapshot(self.session)
        response2 = JSONResponse(snapshot)
        self.assertGreater(len(response2.render(snapshot)), 0)


class Stage16BLivingSystemicZoneHuntSaveReloadTests(unittest.TestCase):
    """Zone hunt result persists across save/reload; phase re-derived fresh."""

    WORKING_ZONE_REF = "ZONE-STA-01-BLK-05"
    COMMAND = "ATTEMPT_DEVELOPMENT_SYSTEMIC_ZONE_HUNT"

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="s16b_livingsys_zonehunt_sr_")
        cls.root = pathlib.Path(cls._tmp.name)
        cls.adapter = Stage16BAuthorityAdapter(build_config(cls.root, "stage16b:living-systemic-zonehunt-sr"))
        cls.session = "S16B-LIVINGSYS-ZONEHUNT-SR"
        cls.adapter.bind_session(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.adapter.close()
        cls._tmp.cleanup()

    def command(self, name: str, ref: str, params: dict) -> dict:
        return self.adapter.command(
            {"session_ref": self.session, "command": name, "command_ref": ref, "params": params}
        )

    def test_01_zone_hunt_result_persists_save_reload_no_rollback(self) -> None:
        hunt = self.command(
            self.COMMAND, "ZONEHUNT-SR-HUNT",
            {"request_ref": "ZONEHUNT-SR-HUNT:UI", "zone_ref": self.WORKING_ZONE_REF},
        )
        self.assertEqual("PASS", hunt["status"])

        proj_pre_save = self.adapter._streaming_projection()
        entry_pre_save = next(z for z in proj_pre_save["zones"] if z["zone_ref"] == self.WORKING_ZONE_REF)
        self.assertEqual("SYSTEMIC", entry_pre_save["stream_phase"])
        living_pre_save = entry_pre_save["zone_living_state"]

        saved = self.command(
            "REQUEST_SAVE", "ZONEHUNT-SR-SAVE",
            {
                "request_ref": "ZONEHUNT-SR-SAVE:UI", "slot_ref": "g09b2zonehunt", "save_kind": "MANUAL",
                "reason": "G16B09B2_SYSTEMIC_ZONE_HUNT_CONTINUITY", "client_presentation_only": True,
            },
        )
        self.assertEqual("CONFIRMED", saved["result"])

        restored = self.command(
            "REQUEST_RELOAD_RESYNC", "ZONEHUNT-SR-RELOAD",
            {
                "request_ref": "ZONEHUNT-SR-RELOAD:UI", "slot_ref": "g09b2zonehunt",
                "require_resync_before_ready": True, "client_presentation_only": True,
            },
        )
        self.assertEqual("PASS", restored["status"])

        # G09_SYSTEMIC_ZONE_DOMAIN_STATE_PERSISTS_SAVE_RELOAD /
        # G09_SYSTEMIC_ZONE_PHASE_REDERIVED_AFTER_RELOAD
        restore_streaming = restored["restore_snapshot"]["world"]["streaming"]
        restored_entry = next(z for z in restore_streaming["zones"] if z["zone_ref"] == self.WORKING_ZONE_REF)
        self.assertEqual("SYSTEMIC", restored_entry["stream_phase"])
        # G09_SYSTEMIC_ZONE_DOMAIN_STATE_NO_ROLLBACK
        self.assertEqual(living_pre_save, restored_entry["zone_living_state"])

        proj_after = self.adapter._streaming_projection()
        after_entry = next(z for z in proj_after["zones"] if z["zone_ref"] == self.WORKING_ZONE_REF)
        self.assertEqual("SYSTEMIC", after_entry["stream_phase"])
        self.assertEqual(living_pre_save, after_entry["zone_living_state"])


if __name__ == "__main__":
    unittest.main()
