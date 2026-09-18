from __future__ import annotations
from typing import Any
from integrated_arpg_engine_v12 import IntegratedARPGEngineV12
from living_runtime import ValidationError
from arpg_economy_crafting_core import ARPGEconomyCraftingCore

class IntegratedARPGEngineV13(IntegratedARPGEngineV12):
    VERSION='ARPG-V1.4.0'; AUTHORITY='ANDROMEDA_ARPG_STAGE13_ECONOMY_CRAFTING'
    def __init__(self,db_path=':memory:',*,master_release_path):
        super().__init__(db_path,master_release_path=master_release_path); self._arpg_economy_core={}
    def _attach_economy_arpg(self,wid):
        c=ARPGEconomyCraftingCore(self,wid); self._arpg_economy_core[wid]=c; return c
    def create_world(self,owner_scope:str,seed:int,**kwargs)->dict[str,Any]:
        r=super().create_world(owner_scope,seed,**kwargs); wid=r['world']['world_instance_id']; c=self._attach_economy_arpg(wid); h=self.health_arpg_v13(wid)
        if h['status']!='PASS': raise ValidationError('ARPG Stage13 bootstrap failed:'+str(h['failures']))
        r.update({'version':self.VERSION,'authority':self.AUTHORITY,'economy':c.verify(),'arpg_health':h}); return r
    def resume_world(self,wid:str)->dict[str,Any]:
        r=super().resume_world(wid); c=self._attach_economy_arpg(wid); h=self.health_arpg_v13(wid)
        if h['status']!='PASS': raise ValidationError('ARPG Stage13 resume failed:'+str(h['failures']))
        r.update({'version':self.VERSION,'authority':self.AUTHORITY,'economy':c.verify(),'arpg_health':h}); return r
    def economy_arpg(self,wid): return self._arpg_economy_core[wid]
    def health_arpg_v13(self,wid):
        b=self.health_arpg_v12(wid); e=self.economy_arpg(wid).verify(); f=[]
        if b['status']!='PASS': f.extend('STAGE12:'+x for x in b.get('failures',[]))
        if e['status']!='PASS': f.extend('ECONOMY:'+x for x in e.get('failures',[]))
        return {'status':'PASS' if not f else 'FAIL','failures':f,'stage12':b,'economy':e,'authority':self.AUTHORITY}
