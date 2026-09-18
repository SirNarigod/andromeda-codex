from __future__ import annotations
from typing import Any

from integrated_engine_v15 import IntegratedLivingEngineV15
from living_runtime import ValidationError
from arpg_game_core import ARPGGameCore


class IntegratedARPGEngineV01(IntegratedLivingEngineV15):
    VERSION = "ARPG-V0.2.0"
    AUTHORITY = "ANDROMEDA_ARPG_STAGE01_GAME_CORE"

    def __init__(self, db_path=':memory:', *, master_release_path):
        super().__init__(db_path, master_release_path=master_release_path)
        self._arpg_core: dict[str, ARPGGameCore] = {}

    def _attach_arpg(self, world_instance_id: str) -> ARPGGameCore:
        core = ARPGGameCore(self, world_instance_id)
        self._arpg_core[world_instance_id] = core
        return core

    def create_world(self, owner_scope: str, seed: int, **kwargs) -> dict[str, Any]:
        result = super().create_world(owner_scope, seed, **kwargs)
        wid = result['world']['world_instance_id']
        core = self._attach_arpg(wid)
        health = self.health_arpg_v01(wid)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage01 bootstrap failed:' + str(health['failures']))
        result.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'arpg_game_core': core.verify(), 'arpg_health': health})
        return result

    def resume_world(self, world_instance_id: str) -> dict[str, Any]:
        result = super().resume_world(world_instance_id)
        core = self._attach_arpg(world_instance_id)
        health = self.health_arpg_v01(world_instance_id)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage01 resume failed:' + str(health['failures']))
        result.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'arpg_game_core': core.verify(), 'arpg_health': health})
        return result

    def arpg(self, world_instance_id: str) -> ARPGGameCore:
        return self._arpg_core[world_instance_id]

    def health_arpg_v01(self, world_instance_id: str) -> dict[str, Any]:
        base = self.health_v15(world_instance_id)
        core = self.arpg(world_instance_id).verify()
        failures = []
        if base['status'] != 'PASS':
            failures.extend('V15:' + x for x in base.get('failures', []))
        if core['status'] != 'PASS':
            failures.extend('ARPG_CORE:' + x for x in core.get('failures', []))
        return {'status': 'PASS' if not failures else 'FAIL', 'failures': failures, 'v15': base, 'arpg_core': core, 'authority': self.AUTHORITY}
