from __future__ import annotations
from typing import Any

from integrated_arpg_engine_v04 import IntegratedARPGEngineV04
from living_runtime import ValidationError
from arpg_item_core import ARPGItemCore


class IntegratedARPGEngineV05(IntegratedARPGEngineV04):
    VERSION = "ARPG-V0.6.0"
    AUTHORITY = "ANDROMEDA_ARPG_STAGE05_ITEMIZATION"

    def __init__(self, db_path=':memory:', *, master_release_path):
        super().__init__(db_path, master_release_path=master_release_path)
        self._arpg_item_core: dict[str, ARPGItemCore] = {}

    def _attach_items_arpg(self, world_instance_id: str) -> ARPGItemCore:
        core = ARPGItemCore(self, world_instance_id)
        self._arpg_item_core[world_instance_id] = core
        return core

    def create_world(self, owner_scope: str, seed: int, **kwargs) -> dict[str, Any]:
        result = super().create_world(owner_scope, seed, **kwargs)
        wid = result['world']['world_instance_id']
        items = self._attach_items_arpg(wid)
        health = self.health_arpg_v05(wid)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage05 bootstrap failed:' + str(health['failures']))
        result.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'item_core': items.verify(), 'arpg_health': health})
        return result

    def resume_world(self, world_instance_id: str) -> dict[str, Any]:
        result = super().resume_world(world_instance_id)
        items = self._attach_items_arpg(world_instance_id)
        health = self.health_arpg_v05(world_instance_id)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage05 resume failed:' + str(health['failures']))
        result.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'item_core': items.verify(), 'arpg_health': health})
        return result

    def items_arpg(self, world_instance_id: str) -> ARPGItemCore:
        return self._arpg_item_core[world_instance_id]

    def health_arpg_v05(self, world_instance_id: str) -> dict[str, Any]:
        base = self.health_arpg_v04(world_instance_id)
        items = self.items_arpg(world_instance_id).verify()
        failures = []
        if base['status'] != 'PASS':
            failures.extend('STAGE04:' + x for x in base.get('failures', []))
        if items['status'] != 'PASS':
            failures.extend('ITEMS:' + x for x in items.get('failures', []))
        return {'status': 'PASS' if not failures else 'FAIL', 'failures': failures, 'stage04': base, 'item_core': items, 'authority': self.AUTHORITY}
