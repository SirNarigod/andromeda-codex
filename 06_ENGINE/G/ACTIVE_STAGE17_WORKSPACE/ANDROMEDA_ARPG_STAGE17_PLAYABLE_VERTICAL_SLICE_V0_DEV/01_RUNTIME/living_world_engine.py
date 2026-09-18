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
from tick_background_service import TickBackgroundService


class LivingWorldEngine:
    """Composition root for a live world: runtime, systems, orchestrator and clock."""

    def __init__(self, db_path: str | Path = ":memory:", *, master_release_path: str | Path,
                 tick_interval_s: float = 0.05, auto_start: bool = True) -> None:
        self.runtime = LivingRuntime(db_path, master_release_path=master_release_path)
        self.master_release_path = str(master_release_path)
        self.validator = IntentValidator(self.runtime)
        self.brain = AgentBrain(self.runtime, self.validator)
        self.social = SocialMemorySystem(self.runtime)
        self.ecology = EcologySystem(self.runtime, self.validator)
        self.objects = ObjectEnvironmentSystem(self.runtime)
        self.consequences = ConsequenceEngine(self.runtime)
        self.consequences.attach_auto_propagation()
        self.orchestrator = WorldSimulationOrchestrator(
            self.runtime, self.consequences, self.brain, self.validator,
            self.social, self.ecology, self.objects,
        )
        self.world_systems = WorldSystems(self.runtime)
        self.tick_service = self.orchestrator.start_background_ticks(interval_s=tick_interval_s)
        self.auto_start = bool(auto_start)
        if not self.auto_start:
            self.tick_service.stop()

    def create_world(self, owner_scope: str, seed: int, **kwargs: Any) -> dict[str, Any]:
        world = self.runtime.create_world(owner_scope, seed, **kwargs)
        wid = world["world_instance_id"]
        self.ecology.load_master_fauna_snapshots(self.master_release_path)
        self.world_systems.load_master_snapshots(self.master_release_path)
        self.consequences.load_master_relationships(wid)
        self.world_systems.bootstrap_world(wid, population_seed=kwargs.pop("population_seed", 1000))
        self.orchestrator.configure_world(wid)
        self.world_systems.attach_to_orchestrator(self.orchestrator, wid)
        if self.auto_start:
            self.orchestrator.register_background_world(wid)
        return {
            "world": world,
            "world_instance_id": wid,
            "background_tick": self.auto_start,
            "orchestrator": self.orchestrator.full_integrity_check(wid),
            "world_systems": self.world_systems.summary(wid),
        }

    def pause_world(self, world_instance_id: str) -> dict[str, Any]:
        self.orchestrator.unregister_background_world(world_instance_id)
        return self.runtime.pause_world(world_instance_id)

    def resume_world(self, world_instance_id: str) -> dict[str, Any]:
        result = self.runtime.resume_world(world_instance_id)
        if self.auto_start:
            self.orchestrator.register_background_world(world_instance_id)
        return result

    def close(self) -> None:
        self.runtime.close()

    def __enter__(self) -> "LivingWorldEngine":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()