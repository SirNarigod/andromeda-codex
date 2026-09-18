from __future__ import annotations
from typing import Any

from integrated_arpg_engine_v14 import IntegratedARPGEngineV14
from integrated_engine_v15 import IntegratedLivingEngineV15
from living_runtime import ValidationError
from arpg_save_recovery_core import ARPGSaveRecoveryCore


class IntegratedARPGEngineV15(IntegratedARPGEngineV14):
    VERSION = "ARPG-V1.6.0"
    AUTHORITY = "ANDROMEDA_ARPG_STAGE15_SAVE_PERSISTENCE_DEATH_RECOVERY"

    def __init__(self, db_path=':memory:', *, master_release_path, save_root=None):
        super().__init__(db_path, master_release_path=master_release_path)
        self._arpg_save_core = {}
        self._stage15_save_root = save_root

    def _attach_save_recovery(self, wid):
        c = ARPGSaveRecoveryCore(self, wid, save_root=self._stage15_save_root)
        self._arpg_save_core[wid] = c
        return c

    def create_world(self, owner_scope: str, seed: int, **kwargs) -> dict[str, Any]:
        r = super().create_world(owner_scope, seed, **kwargs)
        wid = r['world']['world_instance_id']
        c = self._attach_save_recovery(wid)
        h = self.health_arpg_v15(wid)
        if h['status'] != 'PASS': raise ValidationError('ARPG Stage15 bootstrap failed:'+str(h['failures']))
        r.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'save_recovery': c.verify(), 'arpg_health': h})
        return r

    def resume_world(self, wid: str) -> dict[str, Any]:
        # Deliberately bypass Stage01-14 resume recursion. Rehydrate Living once, then attach
        # every ARPG core linearly and execute one global health tree at the end.
        r = IntegratedLivingEngineV15.resume_world(self, wid)
        self._attach_arpg(wid)
        self._attach_character(wid)
        self._attach_combat_arpg(wid)
        self._attach_resources_arpg(wid)
        self._attach_items_arpg(wid)
        self._attach_skills_arpg(wid)
        self._attach_actors_arpg(wid)
        self._attach_world_arpg(wid)
        self._attach_gathering_arpg(wid)
        self._attach_mobility_arpg(wid)
        self._attach_technology_arpg(wid)
        self._attach_narrative_arpg(wid)
        self._attach_economy_arpg(wid)
        self._attach_living_arpg(wid)
        c = self._attach_save_recovery(wid)
        h = self.health_arpg_v15(wid)
        if h['status'] != 'PASS': raise ValidationError('ARPG Stage15 resume failed:'+str(h['failures']))
        r.update({'version': self.VERSION, 'authority': self.AUTHORITY, 'save_recovery': c.verify(), 'arpg_health': h, 'resume_strategy': 'LINEAR_REHYDRATION_SINGLE_GLOBAL_HEALTH'})
        return r

    def save_recovery(self, wid): return self._arpg_save_core[wid]

    def health_arpg_v15(self, wid):
        b = self.health_arpg_v14(wid); s = self.save_recovery(wid).verify(); f = []
        if b['status'] != 'PASS': f.extend('STAGE14:'+x for x in b.get('failures', []))
        if s['status'] != 'PASS': f.extend('SAVE:'+x for x in s.get('failures', []))
        return {'status':'PASS' if not f else 'FAIL','failures':f,'stage14':b,'save_recovery':s,'authority':self.AUTHORITY}
