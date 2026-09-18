from __future__ import annotations
from typing import Any

from integrated_arpg_engine_v06 import IntegratedARPGEngineV06
from living_runtime import ValidationError
from arpg_actor_core import ARPGActorCore


class IntegratedARPGEngineV07(IntegratedARPGEngineV06):
    VERSION = "ARPG-V0.8.0"
    AUTHORITY = "ANDROMEDA_ARPG_STAGE07_ACTORS_HOSTILITY_AI"

    def __init__(self, db_path=':memory:', *, master_release_path):
        super().__init__(db_path, master_release_path=master_release_path)
        self._arpg_actor_core: dict[str, ARPGActorCore] = {}

    def _attach_actors_arpg(self, world_instance_id: str) -> ARPGActorCore:
        core = ARPGActorCore(self, world_instance_id)
        self._arpg_actor_core[world_instance_id] = core
        return core

    def create_world(self, owner_scope: str, seed: int, **kwargs) -> dict[str, Any]:
        result = super().create_world(owner_scope, seed, **kwargs)
        wid = result['world']['world_instance_id']
        actors = self._attach_actors_arpg(wid)
        health = self.health_arpg_v07(wid)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage07 bootstrap failed:' + str(health['failures']))
        result.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'actor_core': actors.verify(), 'arpg_health': health})
        return result

    def resume_world(self, world_instance_id: str) -> dict[str, Any]:
        result = super().resume_world(world_instance_id)
        actors = self._attach_actors_arpg(world_instance_id)
        health = self.health_arpg_v07(world_instance_id)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage07 resume failed:' + str(health['failures']))
        result.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'actor_core': actors.verify(), 'arpg_health': health})
        return result

    def actors_arpg(self, world_instance_id: str) -> ARPGActorCore:
        return self._arpg_actor_core[world_instance_id]

    def tick_arpg(self, profile_ref: str, *, delta_s: float = 1.0/60.0, max_ai_actors: int = 32) -> dict[str, Any]:
        profile = None
        for wid, core in self._arpg_actor_core.items():
            try:
                profile = self.arpg(wid).profile(profile_ref)
                world_instance_id = wid
                break
            except Exception:
                continue
        if profile is None:
            raise ValidationError('profile_ref not found in attached Stage07 worlds')
        player = self.arpg(world_instance_id).tick(profile_ref, delta_s=delta_s)
        ai = self.actors_arpg(world_instance_id).tick_nearby(profile_ref, delta_s, max_actors=max_ai_actors)
        return {'status':'PASS','profile_ref':profile_ref,'player':player,'actors':ai,'authority':self.AUTHORITY}

    def health_arpg_v07(self, world_instance_id: str) -> dict[str, Any]:
        base = self.health_arpg_v06(world_instance_id)
        actors = self.actors_arpg(world_instance_id).verify()
        failures = []
        if base['status'] != 'PASS': failures.extend('STAGE06:' + x for x in base.get('failures', []))
        if actors['status'] != 'PASS': failures.extend('ACTORS:' + x for x in actors.get('failures', []))
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'stage06':base,'actor_core':actors,'authority':self.AUTHORITY}
