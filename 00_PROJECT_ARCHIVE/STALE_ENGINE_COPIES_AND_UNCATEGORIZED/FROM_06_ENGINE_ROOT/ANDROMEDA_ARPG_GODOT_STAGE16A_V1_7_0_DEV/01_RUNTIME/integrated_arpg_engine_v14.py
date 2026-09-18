from __future__ import annotations
from typing import Any
from integrated_arpg_engine_v13 import IntegratedARPGEngineV13
from living_runtime import ValidationError
from arpg_living_integration_core import ARPGLivingIntegrationCore


class IntegratedARPGEngineV14(IntegratedARPGEngineV13):
    VERSION='ARPG-V1.5.0'
    AUTHORITY='ANDROMEDA_ARPG_STAGE14_LIVING_INTEGRATION'

    def __init__(self,db_path=':memory:',*,master_release_path):
        super().__init__(db_path,master_release_path=master_release_path)
        self._arpg_living_core={}

    def _attach_living_arpg(self,wid):
        c=ARPGLivingIntegrationCore(self,wid);self._arpg_living_core[wid]=c;return c

    def create_world(self,owner_scope:str,seed:int,**kwargs)->dict[str,Any]:
        r=super().create_world(owner_scope,seed,**kwargs);wid=r['world']['world_instance_id'];c=self._attach_living_arpg(wid);h=self.health_arpg_v14(wid)
        if h['status']!='PASS':raise ValidationError('ARPG Stage14 bootstrap failed:'+str(h['failures']))
        r.update({'version':self.VERSION,'authority':self.AUTHORITY,'living_integration':c.verify(),'arpg_health':h});return r

    def resume_world(self,wid:str)->dict[str,Any]:
        r=super().resume_world(wid);c=self._attach_living_arpg(wid);h=self.health_arpg_v14(wid)
        if h['status']!='PASS':raise ValidationError('ARPG Stage14 resume failed:'+str(h['failures']))
        r.update({'version':self.VERSION,'authority':self.AUTHORITY,'living_integration':c.verify(),'arpg_health':h});return r

    def living_arpg(self,wid):return self._arpg_living_core[wid]

    def health_arpg_v14(self,wid):
        b=self.health_arpg_v13(wid);l=self.living_arpg(wid).verify();f=[]
        if b['status']!='PASS':f.extend('STAGE13:'+x for x in b.get('failures',[]))
        if l['status']!='PASS':f.extend('LIVING:'+x for x in l.get('failures',[]))
        return {'status':'PASS' if not f else 'FAIL','failures':f,'stage13':b,'living':l,'authority':self.AUTHORITY}
