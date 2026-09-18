from __future__ import annotations

from pathlib import Path
from typing import Any

from living_runtime import LivingRuntime, ValidationError
from consequence_engine import ConsequenceEngine
from agent_brain import AgentBrain, IntentValidator
from social_memory import SocialMemorySystem
from ecology_brain import EcologySystem
from object_environment import ObjectEnvironmentSystem
from world_orchestrator import WorldSimulationOrchestrator
from world_systems import WorldSystems
from commerce_system import CommerceSystem
from combat_system import CombatSystem
from mobility_biology import MobilityBiologySystem
from society_labor import SocietyLaborSystem
from long_horizon import LongHorizonSimulation
from system_health import SystemHealthMonitor


class IntegratedLivingEngineV11:
    """Official V1.1 composition root for the Living Simulation Engine.

    It removes manual wiring between subsystems while preserving the sealed Master as
    read-only input. All numeric seeds introduced by V1.1 are runtime policy.
    """

    VERSION="V1.1.0"
    AUTHORITY="INTEGRATED_LIVING_V1_1_RUNTIME_NOT_CANON"

    def __init__(self, db_path: str|Path=":memory:", *, master_release_path: str|Path) -> None:
        if not master_release_path: raise ValidationError("master_release_path required")
        self.master_release_path=str(master_release_path)
        self.runtime=LivingRuntime(db_path,master_release_path=self.master_release_path)
        self.validator=IntentValidator(self.runtime)
        self.brain=AgentBrain(self.runtime,self.validator)
        self.social=SocialMemorySystem(self.runtime)
        self.ecology=EcologySystem(self.runtime,self.validator)
        self.objects=ObjectEnvironmentSystem(self.runtime)
        self.consequences=ConsequenceEngine(self.runtime)
        self.orchestrator=WorldSimulationOrchestrator(self.runtime,self.consequences,self.brain,self.validator,self.social,self.ecology,self.objects)
        self.domain_hub=self.orchestrator.domain_integration
        self.world_systems=WorldSystems(self.runtime)
        self.commerce=CommerceSystem(self.runtime,self.world_systems)
        self.combat=CombatSystem(self.runtime,self.commerce,domain_hub=self.domain_hub)
        self.mobility=MobilityBiologySystem(self.runtime,self.world_systems,self.ecology,domain_hub=self.domain_hub)
        self.society=SocietyLaborSystem(self.runtime,self.world_systems,self.social,self.commerce,domain_hub=self.domain_hub)
        self.long_horizon=LongHorizonSimulation(self.runtime,self.orchestrator,self.world_systems,self.ecology,self.objects)
        self.health=SystemHealthMonitor(self.runtime,world_systems=self.world_systems,orchestrator=self.orchestrator,ecology=self.ecology,social=self.social,objects=self.objects,consequence_engine=self.consequences,domain_hub=self.domain_hub,commerce=self.commerce,combat=self.combat,mobility=self.mobility,society=self.society)

    def create_world(self, owner_scope: str, seed: int, *, mode: str="PRIVATE", ticks_per_day: int=24,
                     population_reference_seed: int=1000, load_relationships: bool=True) -> dict[str,Any]:
        world=self.runtime.create_world(owner_scope,seed,mode=mode,ticks_per_day=ticks_per_day)
        wid=world["world_instance_id"]
        # Extension budget > currently attached extension count and root budget sized accordingly.
        orchestration=self.orchestrator.configure_world(wid,{"extension_budget":8,"max_roots_per_run":256,"integrity_cadence_ticks":24})
        master_snapshots=self.world_systems.load_master_snapshots(self.master_release_path)
        systems=self.world_systems.bootstrap_world_contextual(wid,population_seed=population_reference_seed)
        commerce=self.commerce.load_catalog(self.master_release_path)
        fauna=self.ecology.load_master_fauna_snapshots(self.master_release_path)
        eco_policies=self.ecology.install_default_action_policies(wid)
        professions=self.society.load_professions(self.master_release_path)
        relationships=self.consequences.load_master_relationships(wid) if load_relationships else {"status":"SKIPPED_BY_CALLER","selected":0,"inserted":0}
        extensions={
            "world_systems":self.world_systems.attach_to_orchestrator(self.orchestrator,wid),
            "mobility_biology":self.mobility.attach_to_orchestrator(self.orchestrator,wid),
            "society_labor":self.society.attach_to_orchestrator(self.orchestrator,wid),
        }
        long_horizon=self.long_horizon.configure_world(wid)
        report={
            "status":"PASS","version":self.VERSION,"world":self.runtime.get_world(wid),
            "bootstrap_policy":"CONTEXTUAL_V1_1_RUNTIME_ONLY_NOT_CANON",
            "master_snapshots":master_snapshots,"world_systems":systems,"commerce":commerce,
            "fauna":fauna,"ecology_policies":eco_policies,"professions":professions,
            "relationships":relationships,"extensions":extensions,"orchestration":orchestration,
            "long_horizon":long_horizon,"authority":self.AUTHORITY,
        }
        # Creation is not complete if the integrated state is already unhealthy.
        health=self.health.snapshot(wid); report["health"]=health
        if health["status"]!="PASS":
            raise ValidationError(f"integrated world bootstrap failed health gate: {health['failures']}")
        return report

    def active_steps(self, world_instance_id: str, count: int) -> dict[str,Any]:
        if not isinstance(count,int) or isinstance(count,bool) or count<=0: raise ValidationError("count must be positive integer")
        runs=self.orchestrator.run_steps(world_instance_id,count)
        health=self.health.snapshot(world_instance_id)
        return {"status":"PASS" if health["status"]=="PASS" else "FAIL","steps":len(runs),"clock":self.runtime.get_clock(world_instance_id),"health":health,"authority":self.AUTHORITY}

    def offline_days(self, world_instance_id: str, days: int, *, request_key: str="integrated-v1-1") -> dict[str,Any]:
        session=self.long_horizon.begin_offline_session(world_instance_id)
        simulation=self.long_horizon.simulate_offline_days(world_instance_id,days,request_key=request_key)
        reconciliation=self.long_horizon.reconcile_and_resume(world_instance_id)
        if isinstance(reconciliation,dict) and "status" not in reconciliation:
            reconciliation={"status":"PASS",**reconciliation}
        health=self.health.snapshot(world_instance_id)
        return {"status":"PASS" if health["status"]=="PASS" else "FAIL","session":session,"simulation":simulation,"reconciliation":reconciliation,"health":health,"authority":self.AUTHORITY}

    def close(self)->None:
        self.runtime.close()
