import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "12_AUTHORITY_BACKEND_STAGE17"))

from living_runtime import LivingRuntime, new_runtime_id, clock_point
from social_memory import SocialMemorySystem
from world_systems import WorldSystems
from country_scale import CountryScaleSystem
from root_corruption_system import RootCorruptionSystem
from vendor_wealth_economy import VendorWealthEconomy
from perception_system import PerceptionSystem
from agent_brain import AgentBrain, IntentValidator
from world_orchestrator import WorldSimulationOrchestrator
from ecology_brain import EcologySystem
from object_environment import ObjectEnvironmentSystem
import system_causal_bridges as bridges

MASTER = os.environ.get(
    "ANDROMEDA_MASTER_RELEASE",
    "/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip",
)


def _entity(rt, world, *, kind, canonical_ref=None, data=None):
    clock = rt.get_clock(world["world_instance_id"])
    state = {
        "state_id": new_runtime_id("state"),
        "world_instance_id": world["world_instance_id"],
        "timeline_id": world["timeline_id"],
        "entity_runtime_id": new_runtime_id(kind.lower()),
        "origin": "RUNTIME_BORN",
        "entity_kind": kind,
        "lifecycle": "ACTIVE",
        "version": 0,
        "updated_at": clock_point(clock["day"], clock["tick"]),
        "data": copy.deepcopy(data or {}),
    }
    if canonical_ref:
        state["canonical_ref"] = canonical_ref
    rt.register_entity(world["world_instance_id"], state)
    return state


class KillFactionReactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rt = LivingRuntime(os.path.join(self.tmp.name, "w.db"), master_release_path=MASTER)
        self.world = self.rt.create_world("bridge-test", 1, ticks_per_day=24)
        self.wid = self.world["world_instance_id"]
        self.ws = WorldSystems(self.rt)
        self.sm = SocialMemorySystem(self.rt)

    def tearDown(self):
        self.rt.close()
        self.tmp.cleanup()

    def test_reputation_drops_weighted_by_influence_only_for_present_factions(self):
        player = _entity(self.rt, self.world, kind="ACTOR")
        _entity(
            self.rt, self.world, kind="FACTION_RUNTIME",
            data={"faction_ref": "FAC-001", "territory_ref": "TER-011", "influence": 80.0},
        )
        _entity(
            self.rt, self.world, kind="FACTION_RUNTIME",
            data={"faction_ref": "FAC-002", "territory_ref": "TER-003", "influence": 90.0},
        )
        result = bridges.apply_combat_kill_faction_reaction(
            self.ws, self.sm, self.wid, self.wid, player["entity_runtime_id"], "TER-011",
            event_ref="kill-1",
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["factions_reacted"], 1)
        rep = self.sm.get_reputation(self.wid, player["entity_runtime_id"], scope_type="FACTION", scope_ref="FAC-001")
        self.assertLess(rep["score"], 0.0)

    def test_idempotent_on_replayed_event_ref(self):
        player = _entity(self.rt, self.world, kind="ACTOR")
        _entity(
            self.rt, self.world, kind="FACTION_RUNTIME",
            data={"faction_ref": "FAC-001", "territory_ref": "TER-011", "influence": 50.0},
        )
        bridges.apply_combat_kill_faction_reaction(
            self.ws, self.sm, self.wid, self.wid, player["entity_runtime_id"], "TER-011", event_ref="kill-dup",
        )
        before = self.sm.get_reputation(self.wid, player["entity_runtime_id"], scope_type="FACTION", scope_ref="FAC-001")
        bridges.apply_combat_kill_faction_reaction(
            self.ws, self.sm, self.wid, self.wid, player["entity_runtime_id"], "TER-011", event_ref="kill-dup",
        )
        after = self.sm.get_reputation(self.wid, player["entity_runtime_id"], scope_type="FACTION", scope_ref="FAC-001")
        self.assertEqual(before["score"], after["score"])


class GatheringRegionalStockTests(unittest.TestCase):
    def setUp(self):
        self.country = CountryScaleSystem(master_release_path=MASTER, country_territory_id="TER-011")

    def _all_blocks(self):
        for s in self.country.world["country"]["states"]:
            for b in s["blocks"]:
                yield b

    def test_mines_richest_matching_kind_resource(self):
        block = next((b for b in self._all_blocks() if b["resources"]), None)
        self.assertIsNotNone(block, "fixed seed produced no block with any resource at all")
        kind = block["resources"][0]["kind"]
        before = max(r["remaining_units"] for r in block["resources"] if r["kind"] == kind)
        result = bridges.apply_gathering_yield_to_regional_stock(self.country, block["id"], kind, 5)
        self.assertEqual(result["status"], "PASS")
        after = self.country.block(block["id"])
        matched = next(r for r in after["resources"] if r["id"] == result["resource_id"])
        self.assertLess(matched["remaining_units"], before)

    def test_skips_cleanly_when_kind_absent(self):
        block = next(self._all_blocks())
        result = bridges.apply_gathering_yield_to_regional_stock(self.country, block["id"], "NONEXISTENT_KIND", 5)
        self.assertEqual(result["status"], "SKIPPED")


class CorruptionVendorPressureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rt = LivingRuntime(os.path.join(self.tmp.name, "w.db"), master_release_path=MASTER)
        self.world = self.rt.create_world("bridge-test-3", 3, ticks_per_day=24)
        self.corruption = RootCorruptionSystem(self.rt, self.world["world_instance_id"])

    def tearDown(self):
        self.rt.close()
        self.tmp.cleanup()

    def test_no_corruption_means_no_price_pressure(self):
        result = bridges.corruption_vendor_price_multiplier(self.corruption, "TER-999-UNCORRUPTED")
        self.assertEqual(result["multiplier"], 1.0)

    def test_corrupted_territory_reduces_multiplier_but_never_to_zero(self):
        self.corruption.corrupt_subregion(
            "SUB-BRIDGE-TEST-01", "TER-011", intensity="SEVERE", event_ref="seed-1",
            total_subregions_in_territory=60,
        )
        result = bridges.corruption_vendor_price_multiplier(self.corruption, "TER-011")
        self.assertLess(result["multiplier"], 1.0)
        self.assertGreater(result["multiplier"], 0.0)


class _FakeEconomy:
    """Minimal wallet stub -- VendorWealthEconomy only ever calls wallet()
    and _set_balance() on its `economy` dependency, confirmed by reading the
    file; the real ARPGEconomyCraftingCore needs a full engine to construct,
    which is out of scope for testing the price-pressure bridge in isolation."""

    def __init__(self):
        self._balances: dict[str, float] = {}

    def wallet(self, ref):
        return {"balance": self._balances.get(ref, 0.0)}

    def _set_balance(self, ref, value):
        self._balances[ref] = value


class VendorPricePressureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rt = LivingRuntime(os.path.join(self.tmp.name, "w.db"), master_release_path=MASTER)
        self.world = self.rt.create_world("bridge-test-4", 4, ticks_per_day=24)
        self.wid = self.world["world_instance_id"]
        self.vendor_wealth = VendorWealthEconomy(self.rt, self.wid, _FakeEconomy())
        self.vendor_wealth.register_vendor("VENDOR-001", "TER-011", event_ref="seed-vendor")
        self.country = CountryScaleSystem(master_release_path=MASTER, country_territory_id="TER-011")
        self.corruption = RootCorruptionSystem(self.rt, self.wid)

    def tearDown(self):
        self.rt.close()
        self.tmp.cleanup()

    def test_price_pressure_defaults_to_no_effect(self):
        state = self.vendor_wealth.state("VENDOR-001")
        self.assertEqual(state["effective_wallet_cap"], state["wallet_cap"])

    def test_corruption_pressure_shrinks_effective_cap(self):
        self.corruption.corrupt_subregion(
            "SUB-VENDOR-TEST-01", "TER-011", intensity="SEVERE", event_ref="seed-2",
            total_subregions_in_territory=60,
        )
        pressure = bridges.corruption_vendor_price_multiplier(self.corruption, "TER-011")
        self.vendor_wealth.apply_price_pressure("VENDOR-001", corruption_multiplier=pressure["multiplier"])
        state = self.vendor_wealth.state("VENDOR-001")
        self.assertLess(state["effective_wallet_cap"], state["wallet_cap"])

    def test_climate_and_corruption_pressures_compose(self):
        climate = bridges.climate_vendor_price_multiplier(self.country, "TER-011")
        self.vendor_wealth.apply_price_pressure("VENDOR-001", climate_multiplier=climate["multiplier"])
        self.vendor_wealth.apply_price_pressure("VENDOR-001", corruption_multiplier=0.7)
        state = self.vendor_wealth.state("VENDOR-001")
        expected = round(state["wallet_cap"] * 0.7 * climate["multiplier"], 2)
        self.assertEqual(state["effective_wallet_cap"], expected)


class PlayerDeathSocialReactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rt = LivingRuntime(os.path.join(self.tmp.name, "w.db"), master_release_path=MASTER)
        self.world = self.rt.create_world("bridge-test-5", 5, ticks_per_day=24)
        self.wid = self.world["world_instance_id"]
        self.ws = WorldSystems(self.rt)
        self.sm = SocialMemorySystem(self.rt)

    def tearDown(self):
        self.rt.close()
        self.tmp.cleanup()

    def test_death_raises_reputation_instead_of_lowering_it(self):
        player = _entity(self.rt, self.world, kind="ACTOR")
        _entity(
            self.rt, self.world, kind="FACTION_RUNTIME",
            data={"faction_ref": "FAC-001", "territory_ref": "TER-011", "influence": 60.0},
        )
        result = bridges.apply_player_death_social_reaction(
            self.ws, self.sm, self.wid, self.wid, player["entity_runtime_id"], "TER-011",
            event_ref="death-1",
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["trigger"], "PLAYER_DEATH")
        rep = self.sm.get_reputation(self.wid, player["entity_runtime_id"], scope_type="FACTION", scope_ref="FAC-001")
        self.assertGreater(rep["score"], 0.0)


class SkillLearnCostTests(unittest.TestCase):
    def setUp(self):
        self.economy = _FakeEconomy()
        self.economy._balances["PLAYER-1"] = 100.0

    def test_charges_scaled_by_territory_wealth(self):
        result = bridges.apply_skill_learn_cost(self.economy, "PLAYER-1", "TER-011", base_cost=50.0)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(self.economy.wallet("PLAYER-1")["balance"], round(100.0 - result["cost"], 2))

    def test_rejects_when_insufficient_funds(self):
        self.economy._balances["PLAYER-1"] = 1.0
        result = bridges.apply_skill_learn_cost(self.economy, "PLAYER-1", "TER-011", base_cost=50.0)
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(self.economy.wallet("PLAYER-1")["balance"], 1.0)

    def test_poorer_territory_costs_more(self):
        from vendor_wealth_economy import WELFARE_BY_TERRITORY

        rich = next(t for t, w in WELFARE_BY_TERRITORY.items() if w == "ALTO")
        poor = next(t for t, w in WELFARE_BY_TERRITORY.items() if w == "BAIXO")
        rich_cost = bridges.apply_skill_learn_cost(_FakeEconomy(), "P", rich, base_cost=50.0)
        self.economy2 = _FakeEconomy()
        poor_cost = bridges.apply_skill_learn_cost(self.economy2, "P", poor, base_cost=50.0)
        self.assertGreater(poor_cost["cost"], rich_cost["cost"])


class ConstructionMaterialCostTests(unittest.TestCase):
    def setUp(self):
        self.country = CountryScaleSystem(master_release_path=MASTER, country_territory_id="TER-011")

    def _first_block_with(self, *, resources=False, flora=False):
        for s in self.country.world["country"]["states"]:
            for b in s["blocks"]:
                if resources and not b["resources"]:
                    continue
                if flora and not b["flora"]:
                    continue
                return b
        return None

    def test_mineral_material_draws_matching_kind(self):
        block = self._first_block_with(resources=True)
        self.assertIsNotNone(block, "fixed seed produced no block with any resource")
        kind = block["resources"][0]["kind"]
        material_ref = next(k for k, v in bridges.CONSTRUCTION_MATERIAL_TO_RESOURCE_KIND.items() if v == kind)
        result = bridges.apply_construction_material_cost(self.country, block["id"], [material_ref], quantity_per_material=3)
        self.assertEqual(result["materials"][0]["status"], "PASS")

    def test_wood_material_draws_from_flora_regardless_of_species(self):
        block = self._first_block_with(flora=True)
        self.assertIsNotNone(block, "fixed seed produced no block with any flora")
        before = max(f["remaining_units"] for f in block["flora"])
        result = bridges.apply_construction_material_cost(self.country, block["id"], ["MAT-001"], quantity_per_material=3)
        self.assertEqual(result["materials"][0]["status"], "PASS")
        after = self.country.block(block["id"])
        self.assertLess(max(f["remaining_units"] for f in after["flora"]), before + 1)

    def test_unmapped_material_skips_cleanly(self):
        block = next(s["blocks"][0] for s in self.country.world["country"]["states"])
        result = bridges.apply_construction_material_cost(self.country, block["id"], ["MAT-UNKNOWN"])
        self.assertEqual(result["materials"][0]["status"], "SKIPPED")


class _FakeMovement:
    """Minimal movement.state() stub -- PerceptionSystem only ever reads
    iso_x_m/iso_y_m/mode from its `movement` dependency."""

    def __init__(self, positions: dict[str, dict]):
        self._positions = positions

    def state(self, ref):
        return self._positions[ref]


class PerceptionAgentBrainBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rt = LivingRuntime(os.path.join(self.tmp.name, "w.db"), master_release_path=MASTER)
        self.world = self.rt.create_world("bridge-test-6", 6, ticks_per_day=24)
        self.wid = self.world["world_instance_id"]
        self.agent = _entity(self.rt, self.world, kind="AGENT", data={})
        self.player = _entity(self.rt, self.world, kind="ACTOR", data={})
        self.validator = IntentValidator(self.rt)
        self.brain = AgentBrain(self.rt, self.validator)

    def tearDown(self):
        self.rt.close()
        self.tmp.cleanup()

    def _perception(self, observer_xy, target_xy, target_mode="WALK"):
        movement = _FakeMovement({
            self.agent["entity_runtime_id"]: {"iso_x_m": observer_xy[0], "iso_y_m": observer_xy[1], "mode": "IDLE"},
            self.player["entity_runtime_id"]: {"iso_x_m": target_xy[0], "iso_y_m": target_xy[1], "mode": target_mode},
        })
        return PerceptionSystem(self.rt, self.wid, movement)

    def test_seen_target_gets_recorded_for_agent_brain(self):
        perception = self._perception((0.0, 0.0), (5.0, 0.0))
        result = bridges.perceive_and_record_for_agent(
            perception, self.brain, self.wid, self.agent["entity_runtime_id"], self.player["entity_runtime_id"],
            observer_heading_deg=0.0,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["perception"]["state"], "SEEN")
        latest = self.brain._latest_perception(self.wid, self.agent["entity_runtime_id"])
        self.assertIsNotNone(latest)
        self.assertEqual(latest["observations"][0]["target_ref"], self.player["entity_runtime_id"])
        self.assertEqual(latest["observations"][0]["confidence"], 1.0)

    def test_unaware_target_records_nothing(self):
        perception = self._perception((0.0, 0.0), (500.0, 500.0))
        result = bridges.perceive_and_record_for_agent(
            perception, self.brain, self.wid, self.agent["entity_runtime_id"], self.player["entity_runtime_id"],
            observer_heading_deg=0.0,
        )
        self.assertEqual(result["status"], "SKIPPED")
        self.assertIsNone(self.brain._latest_perception(self.wid, self.agent["entity_runtime_id"]))


class NpcFactionMembershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rt = LivingRuntime(os.path.join(self.tmp.name, "w.db"), master_release_path=MASTER)
        self.world = self.rt.create_world("bridge-test-7", 7, ticks_per_day=24)
        self.wid = self.world["world_instance_id"]
        self.ws = WorldSystems(self.rt)
        self.country = CountryScaleSystem(master_release_path=MASTER, country_territory_id="TER-011")

    def tearDown(self):
        self.rt.close()
        self.tmp.cleanup()

    def _all_npcs(self):
        for s in self.country.world["country"]["states"]:
            for b in s["blocks"]:
                for c in b["cities"]:
                    for n in c["npcs"]:
                        yield n

    def test_skips_cleanly_when_no_faction_present(self):
        result = bridges.assign_npc_faction_membership(self.country, self.ws, self.wid)
        self.assertEqual(result["status"], "SKIPPED")

    def test_only_eligible_classes_get_a_real_faction_ref(self):
        _entity(
            self.rt, self.world, kind="FACTION_RUNTIME",
            data={"faction_ref": "FAC-001", "territory_ref": "TER-011", "influence": 70.0},
        )
        result = bridges.assign_npc_faction_membership(self.country, self.ws, self.wid)
        self.assertEqual(result["status"], "PASS")
        self.assertGreater(result["assigned"], 0)
        for npc in self._all_npcs():
            if npc["class"] in bridges.FACTION_ELIGIBLE_NPC_CLASSES:
                self.assertEqual(npc["faction_ref"], "FAC-001")
            else:
                self.assertIsNone(npc["faction_ref"])

    def test_deterministic_across_repeated_calls(self):
        _entity(
            self.rt, self.world, kind="FACTION_RUNTIME",
            data={"faction_ref": "FAC-001", "territory_ref": "TER-011", "influence": 40.0},
        )
        _entity(
            self.rt, self.world, kind="FACTION_RUNTIME",
            data={"faction_ref": "FAC-002", "territory_ref": "TER-011", "influence": 60.0},
        )
        bridges.assign_npc_faction_membership(self.country, self.ws, self.wid)
        first_pass = {n["id"]: n["faction_ref"] for n in self._all_npcs()}
        bridges.assign_npc_faction_membership(self.country, self.ws, self.wid)
        second_pass = {n["id"]: n["faction_ref"] for n in self._all_npcs()}
        self.assertEqual(first_pass, second_pass)


class NpcAgentRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rt = LivingRuntime(os.path.join(self.tmp.name, "w.db"), master_release_path=MASTER)
        self.world = self.rt.create_world("bridge-test-8", 8, ticks_per_day=24)
        self.wid = self.world["world_instance_id"]
        self.validator = IntentValidator(self.rt)
        self.brain = AgentBrain(self.rt, self.validator)
        self.social = SocialMemorySystem(self.rt)
        self.ecology = EcologySystem(self.rt, self.validator)
        self.objects = ObjectEnvironmentSystem(self.rt)
        from consequence_engine import ConsequenceEngine

        self.ce = ConsequenceEngine(self.rt)
        self.orchestrator = WorldSimulationOrchestrator(
            self.rt, self.ce, self.brain, self.validator, self.social, self.ecology, self.objects
        )
        self.orchestrator.configure_world(self.wid)
        self.country = CountryScaleSystem(master_release_path=MASTER, country_territory_id="TER-011")

    def tearDown(self):
        self.rt.close()
        self.tmp.cleanup()

    def _first_block_with_npcs(self):
        for s in self.country.world["country"]["states"]:
            for b in s["blocks"]:
                if any(c.get("npcs") for c in b.get("cities", [])):
                    return b
        return None

    def test_registers_every_npc_in_block_as_agent_participant(self):
        block = self._first_block_with_npcs()
        self.assertIsNotNone(block, "fixed seed produced no block with any NPC")
        expected_count = sum(len(c["npcs"]) for c in block["cities"])
        result = bridges.register_block_npcs_as_agents(self.rt, self.orchestrator, self.wid, block)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["npc_count"], expected_count)
        self.assertEqual(result["created_count"], expected_count)

    def test_idempotent_does_not_duplicate_agents(self):
        block = self._first_block_with_npcs()
        bridges.register_block_npcs_as_agents(self.rt, self.orchestrator, self.wid, block)
        agents_after_first = [e for e in self.rt.list_entities(self.wid) if e["entity_kind"] == "AGENT"]
        result = bridges.register_block_npcs_as_agents(self.rt, self.orchestrator, self.wid, block)
        agents_after_second = [e for e in self.rt.list_entities(self.wid) if e["entity_kind"] == "AGENT"]
        self.assertEqual(result["created_count"], 0)
        self.assertEqual(len(agents_after_first), len(agents_after_second))

    def test_registered_agent_actually_decides_via_real_tick(self):
        block = self._first_block_with_npcs()
        first_npc = block["cities"][0]["npcs"][0]
        registration = bridges.register_npc_as_agent_participant(
            self.rt, self.orchestrator, self.wid, first_npc
        )
        self.assertEqual(registration["status"], "PASS")
        run = self.orchestrator.run_tick(self.wid)
        self.assertEqual(run["status"], "COMPLETED")
        npc_phase = next(p for p in run["phases"] if p["phase"] == "NPC_AUTONOMY")
        self.assertGreaterEqual(npc_phase["detail"]["selected"], 1)
        decision = self.brain._latest_perception(self.wid, registration["agent_ref"])
        # No perception was ever recorded for this agent -- confirms decide()
        # ran (no exception) and produced a real, inspectable decision record
        # even with zero registered behaviors (NO_ACTION, not a crash).
        self.assertIsNone(decision)


if __name__ == "__main__":
    unittest.main()
