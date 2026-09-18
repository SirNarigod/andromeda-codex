from __future__ import annotations
from typing import Any

from integrated_arpg_engine_v07 import IntegratedARPGEngineV07
from living_runtime import ValidationError
from arpg_world_core import ARPGWorldCore


class IntegratedARPGEngineV08(IntegratedARPGEngineV07):
    VERSION = "ARPG-V0.9.0"
    AUTHORITY = "ANDROMEDA_ARPG_STAGE08_WORLD_BIOMES"

    def __init__(self, db_path=':memory:', *, master_release_path):
        super().__init__(db_path, master_release_path=master_release_path)
        self._arpg_world_core: dict[str, ARPGWorldCore] = {}

    def _attach_world_arpg(self, world_instance_id: str) -> ARPGWorldCore:
        core = ARPGWorldCore(self, world_instance_id)
        self._arpg_world_core[world_instance_id] = core
        return core

    def create_world(self, owner_scope: str, seed: int, **kwargs) -> dict[str, Any]:
        result = super().create_world(owner_scope, seed, **kwargs)
        wid = result['world']['world_instance_id']
        world_core = self._attach_world_arpg(wid)
        health = self.health_arpg_v08(wid)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage08 bootstrap failed:' + str(health['failures']))
        result.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'world_core': world_core.verify(), 'arpg_health': health})
        return result

    def resume_world(self, world_instance_id: str) -> dict[str, Any]:
        result = super().resume_world(world_instance_id)
        world_core = self._attach_world_arpg(world_instance_id)
        health = self.health_arpg_v08(world_instance_id)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage08 resume failed:' + str(health['failures']))
        result.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'world_core': world_core.verify(), 'arpg_health': health})
        return result

    def world_arpg(self, world_instance_id: str) -> ARPGWorldCore:
        return self._arpg_world_core[world_instance_id]

    def tick_arpg(self, profile_ref: str, *, delta_s: float = 1.0/60.0, max_ai_actors: int = 32) -> dict[str, Any]:
        result = super().tick_arpg(profile_ref, delta_s=delta_s, max_ai_actors=max_ai_actors)
        for wid, core in self._arpg_world_core.items():
            try:
                state = core.profile_state(profile_ref)
                result['world'] = {
                    'state': state,
                    'environment': core.environment_sample(state['zone_ref'], step=0),
                    'zone': core.zone(state['zone_ref']),
                }
                break
            except Exception:
                continue
        return result

    def health_arpg_v08(self, world_instance_id: str) -> dict[str, Any]:
        base = self.health_arpg_v07(world_instance_id)
        world = self.world_arpg(world_instance_id).verify()
        failures = []
        if base['status'] != 'PASS': failures.extend('STAGE07:' + x for x in base.get('failures', []))
        if world['status'] != 'PASS': failures.extend('WORLD:' + x for x in world.get('failures', []))
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'stage07':base,'world_core':world,'authority':self.AUTHORITY}
