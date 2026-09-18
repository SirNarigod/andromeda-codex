from __future__ import annotations
from typing import Any

from integrated_arpg_engine_v05 import IntegratedARPGEngineV05
from living_runtime import ValidationError
from arpg_skill_core import ARPGSkillCore


class IntegratedARPGEngineV06(IntegratedARPGEngineV05):
    VERSION = "ARPG-V0.7.0"
    AUTHORITY = "ANDROMEDA_ARPG_STAGE06_SKILLS_BUILD_PROGRESSION"

    def __init__(self, db_path=':memory:', *, master_release_path):
        super().__init__(db_path, master_release_path=master_release_path)
        self._arpg_skill_core: dict[str, ARPGSkillCore] = {}

    def _attach_skills_arpg(self, world_instance_id: str) -> ARPGSkillCore:
        core = ARPGSkillCore(self, world_instance_id)
        self._arpg_skill_core[world_instance_id] = core
        return core

    def create_world(self, owner_scope: str, seed: int, **kwargs) -> dict[str, Any]:
        result = super().create_world(owner_scope, seed, **kwargs)
        wid = result['world']['world_instance_id']
        skills = self._attach_skills_arpg(wid)
        health = self.health_arpg_v06(wid)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage06 bootstrap failed:' + str(health['failures']))
        result.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'skill_core': skills.verify(), 'arpg_health': health})
        return result

    def resume_world(self, world_instance_id: str) -> dict[str, Any]:
        result = super().resume_world(world_instance_id)
        skills = self._attach_skills_arpg(world_instance_id)
        health = self.health_arpg_v06(world_instance_id)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage06 resume failed:' + str(health['failures']))
        result.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'skill_core': skills.verify(), 'arpg_health': health})
        return result

    def skills_arpg(self, world_instance_id: str) -> ARPGSkillCore:
        return self._arpg_skill_core[world_instance_id]

    def health_arpg_v06(self, world_instance_id: str) -> dict[str, Any]:
        base = self.health_arpg_v05(world_instance_id)
        skills = self.skills_arpg(world_instance_id).verify()
        failures = []
        if base['status'] != 'PASS': failures.extend('STAGE05:' + x for x in base.get('failures', []))
        if skills['status'] != 'PASS': failures.extend('SKILLS:' + x for x in skills.get('failures', []))
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'stage05':base,'skill_core':skills,'authority':self.AUTHORITY}
