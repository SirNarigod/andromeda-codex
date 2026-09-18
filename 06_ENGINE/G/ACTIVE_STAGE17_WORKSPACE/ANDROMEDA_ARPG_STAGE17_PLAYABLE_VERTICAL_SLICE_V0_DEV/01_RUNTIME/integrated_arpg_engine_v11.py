from __future__ import annotations
from typing import Any
from integrated_arpg_engine_v10 import IntegratedARPGEngineV10
from living_runtime import ValidationError
from arpg_technology_machine_robotics_core import ARPGTechnologyMachineRoboticsCore

class IntegratedARPGEngineV11(IntegratedARPGEngineV10):
    VERSION='ARPG-V1.2.0'
    AUTHORITY='ANDROMEDA_ARPG_STAGE11_TECHNOLOGY_MACHINES_ROBOTICS'
    def __init__(self,db_path=':memory:',*,master_release_path):
        super().__init__(db_path,master_release_path=master_release_path); self._arpg_technology_core={}
    def _attach_technology_arpg(self,wid):
        c=ARPGTechnologyMachineRoboticsCore(self,wid); self._arpg_technology_core[wid]=c; return c
    def create_world(self,owner_scope:str,seed:int,**kwargs)->dict[str,Any]:
        r=super().create_world(owner_scope,seed,**kwargs); wid=r['world']['world_instance_id']; c=self._attach_technology_arpg(wid); h=self.health_arpg_v11(wid)
        if h['status']!='PASS': raise ValidationError('ARPG Stage11 bootstrap failed:'+str(h['failures']))
        r.update({'version':self.VERSION,'authority':self.AUTHORITY,'technology':c.verify(),'arpg_health':h}); return r
    def resume_world(self,wid:str)->dict[str,Any]:
        r=super().resume_world(wid); c=self._attach_technology_arpg(wid); h=self.health_arpg_v11(wid)
        if h['status']!='PASS': raise ValidationError('ARPG Stage11 resume failed:'+str(h['failures']))
        r.update({'version':self.VERSION,'authority':self.AUTHORITY,'technology':c.verify(),'arpg_health':h}); return r
    def technology_arpg(self,wid): return self._arpg_technology_core[wid]
    def health_arpg_v11(self,wid):
        b=self.health_arpg_v10(wid); t=self.technology_arpg(wid).verify(); f=[]
        if b['status']!='PASS': f.extend('STAGE10:'+x for x in b.get('failures',[]))
        if t['status']!='PASS': f.extend('TECH:'+x for x in t.get('failures',[]))
        return {'status':'PASS' if not f else 'FAIL','failures':f,'stage10':b,'technology':t,'authority':self.AUTHORITY}
