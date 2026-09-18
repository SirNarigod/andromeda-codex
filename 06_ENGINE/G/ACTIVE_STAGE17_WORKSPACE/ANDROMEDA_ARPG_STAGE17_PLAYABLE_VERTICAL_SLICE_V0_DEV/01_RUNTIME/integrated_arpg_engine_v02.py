from __future__ import annotations
from typing import Any

from integrated_arpg_engine_v01 import IntegratedARPGEngineV01
from living_runtime import ValidationError
from character_core import CharacterCore


class IntegratedARPGEngineV02(IntegratedARPGEngineV01):
    VERSION = "ARPG-V0.3.0"
    AUTHORITY = "ANDROMEDA_ARPG_STAGE02_CHARACTER_CORE"

    def __init__(self, db_path=':memory:', *, master_release_path):
        super().__init__(db_path, master_release_path=master_release_path)
        self._character_core: dict[str, CharacterCore] = {}

    def _attach_character(self, world_instance_id: str) -> CharacterCore:
        core = CharacterCore(self, world_instance_id)
        self._character_core[world_instance_id] = core
        return core

    def create_world(self, owner_scope: str, seed: int, **kwargs) -> dict[str, Any]:
        result = super().create_world(owner_scope, seed, **kwargs)
        wid = result['world']['world_instance_id']
        character = self._attach_character(wid)
        health = self.health_arpg_v02(wid)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage02 bootstrap failed:' + str(health['failures']))
        result.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'character_core': character.verify(), 'arpg_health': health})
        return result

    def resume_world(self, world_instance_id: str) -> dict[str, Any]:
        result = super().resume_world(world_instance_id)
        character = self._attach_character(world_instance_id)
        health = self.health_arpg_v02(world_instance_id)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage02 resume failed:' + str(health['failures']))
        result.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'character_core': character.verify(), 'arpg_health': health})
        return result

    def character(self, world_instance_id: str) -> CharacterCore:
        return self._character_core[world_instance_id]

    def health_arpg_v02(self, world_instance_id: str) -> dict[str, Any]:
        base = self.health_arpg_v01(world_instance_id)
        character = self.character(world_instance_id).verify()
        failures = []
        if base['status'] != 'PASS':
            failures.extend('STAGE01:' + x for x in base.get('failures', []))
        if character['status'] != 'PASS':
            failures.extend('CHARACTER:' + x for x in character.get('failures', []))
        return {'status': 'PASS' if not failures else 'FAIL', 'failures': failures, 'stage01': base, 'character_core': character, 'authority': self.AUTHORITY}
