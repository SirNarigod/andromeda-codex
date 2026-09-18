from __future__ import annotations
from typing import Any

from integrated_arpg_engine_v02 import IntegratedARPGEngineV02
from living_runtime import ValidationError
from arpg_combat_core import ARPGCombatCore


class IntegratedARPGEngineV03(IntegratedARPGEngineV02):
    VERSION = "ARPG-V0.4.0"
    AUTHORITY = "ANDROMEDA_ARPG_STAGE03_COMBAT_CORE"

    def __init__(self, db_path=':memory:', *, master_release_path):
        super().__init__(db_path, master_release_path=master_release_path)
        self._arpg_combat_core: dict[str, ARPGCombatCore] = {}

    def _attach_combat_arpg(self, world_instance_id: str) -> ARPGCombatCore:
        core = ARPGCombatCore(self, world_instance_id)
        self._arpg_combat_core[world_instance_id] = core
        return core

    def create_world(self, owner_scope: str, seed: int, **kwargs) -> dict[str, Any]:
        result = super().create_world(owner_scope, seed, **kwargs)
        wid = result['world']['world_instance_id']
        combat = self._attach_combat_arpg(wid)
        health = self.health_arpg_v03(wid)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage03 bootstrap failed:' + str(health['failures']))
        result.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'combat_core': combat.verify(), 'arpg_health': health})
        return result

    def resume_world(self, world_instance_id: str) -> dict[str, Any]:
        result = super().resume_world(world_instance_id)
        combat = self._attach_combat_arpg(world_instance_id)
        health = self.health_arpg_v03(world_instance_id)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage03 resume failed:' + str(health['failures']))
        result.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'combat_core': combat.verify(), 'arpg_health': health})
        return result

    def combat_arpg(self, world_instance_id: str) -> ARPGCombatCore:
        return self._arpg_combat_core[world_instance_id]

    def health_arpg_v03(self, world_instance_id: str) -> dict[str, Any]:
        base = self.health_arpg_v02(world_instance_id)
        combat = self.combat_arpg(world_instance_id).verify()
        failures = []
        if base['status'] != 'PASS':
            failures.extend('STAGE02:' + x for x in base.get('failures', []))
        if combat['status'] != 'PASS':
            failures.extend('COMBAT:' + x for x in combat.get('failures', []))
        return {'status': 'PASS' if not failures else 'FAIL', 'failures': failures, 'stage02': base, 'combat_core': combat, 'authority': self.AUTHORITY}
