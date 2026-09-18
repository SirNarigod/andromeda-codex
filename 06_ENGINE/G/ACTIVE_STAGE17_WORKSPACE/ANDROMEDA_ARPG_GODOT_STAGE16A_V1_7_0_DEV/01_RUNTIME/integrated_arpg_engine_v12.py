from __future__ import annotations
from typing import Any
from integrated_arpg_engine_v11 import IntegratedARPGEngineV11
from living_runtime import ValidationError
from arpg_narrative_culture_core import ARPGNarrativeCultureCore
class IntegratedARPGEngineV12(IntegratedARPGEngineV11):
    VERSION='ARPG-V1.3.0'; AUTHORITY='ANDROMEDA_ARPG_STAGE12_NARRATIVE_CULTURE_QUESTS'
    def __init__(self,db_path=':memory:',*,master_release_path): super().__init__(db_path,master_release_path=master_release_path); self._arpg_narrative_core={}
    def _attach_narrative_arpg(self,wid): c=ARPGNarrativeCultureCore(self,wid); self._arpg_narrative_core[wid]=c; return c
    def create_world(self,owner_scope:str,seed:int,**kwargs)->dict[str,Any]:
        r=super().create_world(owner_scope,seed,**kwargs); wid=r['world']['world_instance_id']; c=self._attach_narrative_arpg(wid); h=self.health_arpg_v12(wid)
        if h['status']!='PASS': raise ValidationError('ARPG Stage12 bootstrap failed:'+str(h['failures']))
        r.update({'version':self.VERSION,'authority':self.AUTHORITY,'narrative':c.verify(),'arpg_health':h}); return r
    def resume_world(self,wid:str)->dict[str,Any]:
        r=super().resume_world(wid); c=self._attach_narrative_arpg(wid); h=self.health_arpg_v12(wid)
        if h['status']!='PASS': raise ValidationError('ARPG Stage12 resume failed:'+str(h['failures']))
        r.update({'version':self.VERSION,'authority':self.AUTHORITY,'narrative':c.verify(),'arpg_health':h}); return r
    def narrative_arpg(self,wid): return self._arpg_narrative_core[wid]
    def health_arpg_v12(self,wid):
        b=self.health_arpg_v11(wid); n=self.narrative_arpg(wid).verify(); f=[]
        if b['status']!='PASS': f.extend('STAGE11:'+x for x in b.get('failures',[]))
        if n['status']!='PASS': f.extend('NARRATIVE:'+x for x in n.get('failures',[]))
        return {'status':'PASS' if not f else 'FAIL','failures':f,'stage11':b,'narrative':n,'authority':self.AUTHORITY}
