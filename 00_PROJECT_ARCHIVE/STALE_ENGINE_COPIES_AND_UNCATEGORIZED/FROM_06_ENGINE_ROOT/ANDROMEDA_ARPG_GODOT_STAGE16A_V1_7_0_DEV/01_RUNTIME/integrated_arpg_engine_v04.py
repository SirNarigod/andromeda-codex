from __future__ import annotations
from typing import Any

from integrated_arpg_engine_v03 import IntegratedARPGEngineV03
from living_runtime import ValidationError
from arpg_resource_core import ARPGResourceCore


class IntegratedARPGEngineV04(IntegratedARPGEngineV03):
    VERSION = "ARPG-V0.5.0"
    AUTHORITY = "ANDROMEDA_ARPG_STAGE04_RESOURCES_COOLDOWNS_CONSUMABLES"

    def __init__(self, db_path=':memory:', *, master_release_path):
        super().__init__(db_path, master_release_path=master_release_path)
        self._arpg_resource_core: dict[str, ARPGResourceCore] = {}

    def _attach_resources_arpg(self, world_instance_id: str) -> ARPGResourceCore:
        core = ARPGResourceCore(self, world_instance_id)
        self._arpg_resource_core[world_instance_id] = core
        return core

    def create_world(self, owner_scope: str, seed: int, **kwargs) -> dict[str, Any]:
        result = super().create_world(owner_scope, seed, **kwargs)
        wid = result['world']['world_instance_id']
        resources = self._attach_resources_arpg(wid)
        health = self.health_arpg_v04(wid)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage04 bootstrap failed:' + str(health['failures']))
        result.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'resource_core': resources.verify(), 'arpg_health': health})
        return result

    def resume_world(self, world_instance_id: str) -> dict[str, Any]:
        result = super().resume_world(world_instance_id)
        resources = self._attach_resources_arpg(world_instance_id)
        health = self.health_arpg_v04(world_instance_id)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage04 resume failed:' + str(health['failures']))
        result.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'resource_core': resources.verify(), 'arpg_health': health})
        return result

    def resources_arpg(self, world_instance_id: str) -> ARPGResourceCore:
        return self._arpg_resource_core[world_instance_id]

    def health_arpg_v04(self, world_instance_id: str) -> dict[str, Any]:
        base = self.health_arpg_v03(world_instance_id)
        resources = self.resources_arpg(world_instance_id).verify()
        failures = []
        if base['status'] != 'PASS':
            failures.extend('STAGE03:' + x for x in base.get('failures', []))
        if resources['status'] != 'PASS':
            failures.extend('RESOURCES:' + x for x in resources.get('failures', []))
        return {'status': 'PASS' if not failures else 'FAIL', 'failures': failures, 'stage03': base, 'resource_core': resources, 'authority': self.AUTHORITY}
