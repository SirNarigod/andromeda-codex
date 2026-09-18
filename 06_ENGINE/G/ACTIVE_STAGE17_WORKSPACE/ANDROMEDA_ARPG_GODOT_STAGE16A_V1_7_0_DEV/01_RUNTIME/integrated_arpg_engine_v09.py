from __future__ import annotations
from typing import Any

from integrated_arpg_engine_v08 import IntegratedARPGEngineV08
from living_runtime import ValidationError
from arpg_gathering_work_core import ARPGGatheringWorkCore


class IntegratedARPGEngineV09(IntegratedARPGEngineV08):
    VERSION = "ARPG-V1.0.0"
    AUTHORITY = "ANDROMEDA_ARPG_STAGE09_GATHERING_WORK"

    def __init__(self, db_path=':memory:', *, master_release_path):
        super().__init__(db_path, master_release_path=master_release_path)
        self._arpg_gathering_core: dict[str, ARPGGatheringWorkCore] = {}

    def _attach_gathering_arpg(self, world_instance_id: str) -> ARPGGatheringWorkCore:
        core=ARPGGatheringWorkCore(self,world_instance_id); self._arpg_gathering_core[world_instance_id]=core; return core

    def create_world(self, owner_scope: str, seed: int, **kwargs) -> dict[str, Any]:
        result=super().create_world(owner_scope,seed,**kwargs); wid=result['world']['world_instance_id']; core=self._attach_gathering_arpg(wid); health=self.health_arpg_v09(wid)
        if health['status']!='PASS': raise ValidationError('ARPG Stage09 bootstrap failed:'+str(health['failures']))
        result.update({'version':self.VERSION,'authority':self.AUTHORITY,'gathering_work':core.verify(),'arpg_health':health}); return result

    def resume_world(self, world_instance_id: str) -> dict[str, Any]:
        result=super().resume_world(world_instance_id); core=self._attach_gathering_arpg(world_instance_id); health=self.health_arpg_v09(world_instance_id)
        if health['status']!='PASS': raise ValidationError('ARPG Stage09 resume failed:'+str(health['failures']))
        result.update({'version':self.VERSION,'authority':self.AUTHORITY,'gathering_work':core.verify(),'arpg_health':health}); return result

    def gathering_arpg(self, world_instance_id: str) -> ARPGGatheringWorkCore: return self._arpg_gathering_core[world_instance_id]

    def health_arpg_v09(self, world_instance_id: str) -> dict[str, Any]:
        base=self.health_arpg_v08(world_instance_id); g=self.gathering_arpg(world_instance_id).verify(); failures=[]
        if base['status']!='PASS': failures.extend('STAGE08:'+x for x in base.get('failures',[]))
        if g['status']!='PASS': failures.extend('GATHERING:'+x for x in g.get('failures',[]))
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'stage08':base,'gathering_work':g,'authority':self.AUTHORITY}
