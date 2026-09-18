from __future__ import annotations
from pathlib import Path
from typing import Any
from integrated_engine import IntegratedLivingEngineV11
from country_scale import CountryScaleSystem
from mar_balance import MARCanonBalance
from scene_interaction import SceneInteractionSystem
from content_catalog import validate_catalog

class IntegratedLivingEngineV12(IntegratedLivingEngineV11):
    VERSION='V1.2.1-DEV'
    AUTHORITY='INTEGRATED_LIVING_V1_2_1_COUNTRY_SCENE_DEV'
    def __init__(self, db_path=':memory:', *, master_release_path):
        super().__init__(db_path,master_release_path=master_release_path)
        self.mar_balance=MARCanonBalance(master_release_path)
        self.country_systems:dict[str,CountryScaleSystem]={}
        self.scene_systems:dict[str,SceneInteractionSystem]={}
    def create_world(self,owner_scope:str,seed:int,*,mode='PRIVATE',ticks_per_day=24,population_reference_seed=1000,load_relationships=True,country_territory_id='TER-011')->dict[str,Any]:
        report=super().create_world(owner_scope,seed,mode=mode,ticks_per_day=ticks_per_day,population_reference_seed=population_reference_seed,load_relationships=load_relationships)
        wid=report['world']['world_instance_id']
        country=CountryScaleSystem(master_release_path=self.master_release_path,country_territory_id=country_territory_id,seed=seed)
        persistence=country.attach_runtime(self.runtime,wid)
        self.country_systems[wid]=country
        scene=SceneInteractionSystem(country); self.scene_systems[wid]=scene
        report['version']=self.VERSION; report['country_scale']={'validation':country.validate(),'persistence':persistence,'coordinate_scale':country.coordinate_scale_report()}; report['scene_interaction']=scene.validate(); report['content_catalog']=validate_catalog(); report['mar_balance']=self.mar_balance.validate(); report['authority']=self.AUTHORITY
        if report['country_scale']['validation']['status']!='PASS' or report['scene_interaction']['status']!='PASS' or report['content_catalog']['status']!='PASS' or report['mar_balance']['status']!='PASS': raise RuntimeError('V1.2.1 country/scene/catalog/MAR bootstrap validation failed')
        return report
    def country(self,world_instance_id:str)->CountryScaleSystem:
        return self.country_systems[world_instance_id]
    def scenes(self,world_instance_id:str)->SceneInteractionSystem:
        return self.scene_systems[world_instance_id]
    def health_v12(self,world_instance_id:str)->dict[str,Any]:
        base=self.health.snapshot(world_instance_id); country=self.country(world_instance_id)
        c=country.validate(); p=country.persistence_integrity(); m=self.mar_balance.validate(); s=self.scenes(world_instance_id).validate(); cat=validate_catalog()
        failures=[]
        if base['status']!='PASS':failures.append('BASE_HEALTH')
        if c['status']!='PASS':failures+=['COUNTRY:'+x for x in c['failures']]
        if p['status']!='PASS':failures+=['PERSISTENCE:'+x for x in p.get('failures',[])]
        if m['status']!='PASS':failures+=['MAR:'+x for x in m['failures']]
        if s['status']!='PASS':failures+=['SCENE:'+x for x in s['failures']]
        if cat['status']!='PASS':failures+=['CATALOG:'+x for x in cat['failures']]
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'base':base,'country':c,'persistence':p,'mar':m,'scene':s,'catalog':cat}
