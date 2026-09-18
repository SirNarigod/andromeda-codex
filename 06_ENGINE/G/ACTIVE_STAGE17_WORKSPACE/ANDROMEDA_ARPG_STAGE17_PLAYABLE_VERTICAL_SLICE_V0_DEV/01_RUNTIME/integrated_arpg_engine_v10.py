from __future__ import annotations
from typing import Any
from integrated_arpg_engine_v09 import IntegratedARPGEngineV09
from living_runtime import ValidationError
from arpg_mobility_infrastructure_core import ARPGMobilityInfrastructureCore

class IntegratedARPGEngineV10(IntegratedARPGEngineV09):
    VERSION='ARPG-V1.1.0'
    AUTHORITY='ANDROMEDA_ARPG_STAGE10_MOBILITY_INFRASTRUCTURE'
    def __init__(self,db_path=':memory:',*,master_release_path):
        super().__init__(db_path,master_release_path=master_release_path); self._arpg_mobility_core={}
    def _attach_mobility_arpg(self,wid):
        c=ARPGMobilityInfrastructureCore(self,wid); self._arpg_mobility_core[wid]=c; return c
    def create_world(self,owner_scope:str,seed:int,**kwargs)->dict[str,Any]:
        r=super().create_world(owner_scope,seed,**kwargs); wid=r['world']['world_instance_id']; c=self._attach_mobility_arpg(wid); h=self.health_arpg_v10(wid)
        if h['status']!='PASS': raise ValidationError('ARPG Stage10 bootstrap failed:'+str(h['failures']))
        r.update({'version':self.VERSION,'authority':self.AUTHORITY,'mobility':c.verify(),'arpg_health':h}); return r
    def resume_world(self,wid:str)->dict[str,Any]:
        r=super().resume_world(wid); c=self._attach_mobility_arpg(wid); h=self.health_arpg_v10(wid)
        if h['status']!='PASS': raise ValidationError('ARPG Stage10 resume failed:'+str(h['failures']))
        r.update({'version':self.VERSION,'authority':self.AUTHORITY,'mobility':c.verify(),'arpg_health':h}); return r
    def mobility_arpg(self,wid): return self._arpg_mobility_core[wid]
    def health_arpg_v10(self,wid):
        b=self.health_arpg_v09(wid); m=self.mobility_arpg(wid).verify(); f=[]
        if b['status']!='PASS': f.extend('STAGE09:'+x for x in b.get('failures',[]))
        if m['status']!='PASS': f.extend('MOBILITY:'+x for x in m.get('failures',[]))
        return {'status':'PASS' if not f else 'FAIL','failures':f,'stage09':b,'mobility':m,'authority':self.AUTHORITY}
