from __future__ import annotations
from typing import Any

from integrated_arpg_engine_v15 import IntegratedARPGEngineV15
from living_runtime import ValidationError
from arpg_vertical_slice_assembly_core import VerticalSliceAssemblyCore


class IntegratedARPGEngineV16A(IntegratedARPGEngineV15):
    VERSION = "ARPG-V1.8.0-DEV-PRE-GODOT"
    AUTHORITY = "ANDROMEDA_ARPG_STAGE16A_VERTICAL_SLICE_PRE_GODOT"

    def __init__(self, db_path=':memory:', *, master_release_path, save_root=None):
        super().__init__(db_path, master_release_path=master_release_path, save_root=save_root)
        self._stage16a_assembly: dict[str, VerticalSliceAssemblyCore] = {}

    def _attach_stage16a(self, world_instance_id: str) -> VerticalSliceAssemblyCore:
        core = VerticalSliceAssemblyCore(self, world_instance_id)
        self._stage16a_assembly[world_instance_id] = core
        return core

    def create_world(self, owner_scope: str, seed: int, **kwargs) -> dict[str, Any]:
        result = super().create_world(owner_scope, seed, **kwargs)
        wid = result['world']['world_instance_id']
        core = self._attach_stage16a(wid)
        health = self.health_arpg_v16a(wid)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage16A bootstrap failed:' + str(health['failures']))
        result.update({
            'version': self.VERSION,
            'authority': self.AUTHORITY,
            'stage16a': core.verify(),
            'arpg_health': health,
            'godot_gate': 'PENDING_PC_AND_EDITOR_BRIDGE',
        })
        return result

    def resume_world(self, world_instance_id: str) -> dict[str, Any]:
        result = super().resume_world(world_instance_id)
        core = self._attach_stage16a(world_instance_id)
        health = self.health_arpg_v16a(world_instance_id)
        if health['status'] != 'PASS':
            raise ValidationError('ARPG Stage16A resume failed:' + str(health['failures']))
        result.update({
            'version': self.VERSION,
            'authority': self.AUTHORITY,
            'stage16a': core.verify(),
            'arpg_health': health,
            'godot_gate': 'PENDING_PC_AND_EDITOR_BRIDGE',
        })
        return result

    def stage16a(self, world_instance_id: str) -> VerticalSliceAssemblyCore:
        return self._stage16a_assembly[world_instance_id]

    def health_arpg_v16a(self, world_instance_id: str) -> dict[str, Any]:
        base = self.health_arpg_v15(world_instance_id)
        stage16a = self.stage16a(world_instance_id).verify()
        failures: list[str] = []
        if base['status'] != 'PASS':
            failures.extend('STAGE15:' + x for x in base.get('failures', []))
        if stage16a['status'] != 'PASS':
            failures.extend('STAGE16A:' + x for x in stage16a.get('failures', []))
        return {
            'status': 'PASS' if not failures else 'FAIL',
            'failures': failures,
            'stage15': base,
            'stage16a': stage16a,
            'godot_gate': 'PENDING_PC_AND_EDITOR_BRIDGE',
            'authority': self.AUTHORITY,
        }
