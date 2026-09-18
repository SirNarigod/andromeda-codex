from __future__ import annotations
from typing import Any
from integrated_engine_v14 import IntegratedLivingEngineV14
from living_runtime import ValidationError
from environment_simulation import EnvironmentSimulationSystem
from continuous_movement import ContinuousMovementSystem
from navigation_pathfinding import NavigationPathfindingSystem
from collision_interaction import CollisionInteractionSystem
from player_discovery import PlayerDiscoverySystem
from godot_adapter_v15 import GodotIsometricAdapterV15

class IntegratedLivingEngineV15(IntegratedLivingEngineV14):
    VERSION='V1.5.0'; AUTHORITY='INTEGRATED_LIVING_V1_5_ISOMETRIC_TRAVERSAL_ENVIRONMENT'
    def __init__(self,db_path=':memory:',*,master_release_path):
        super().__init__(db_path,master_release_path=master_release_path); self._env={}; self._move={}; self._nav={}; self._collision={}; self._discovery={}; self._godot={}
    def _attach_v15(self,wid):
        env=EnvironmentSimulationSystem(self.runtime,wid,self.country(wid)); move=ContinuousMovementSystem(self.runtime,wid,self.country(wid),self.spatial(wid),self.streaming(wid),env,advance_ticks_callback=lambda ticks:self.orchestrator.run_steps(wid,ticks))
        self.streaming(wid).position_resolver=lambda npc_id: self.spatial(wid).isometric_to_geodetic(self._move[wid].state(npc_id)['iso_x_m'],self._move[wid].state(npc_id)['iso_y_m'],self._move[wid].state(npc_id)['altitude_m']) if wid in self._move else self.spatial(wid).point_for_npc(self.country(wid).npc(npc_id))
        nav=NavigationPathfindingSystem(self.country(wid),self.spatial(wid),self.atlas_lod(wid),env); col=CollisionInteractionSystem(self.country(wid),self.spatial(wid),move,self.scenes(wid)); disc=PlayerDiscoverySystem(self.runtime,wid,self.atlas_lod(wid),self.spatial(wid),move)
        self._env[wid]=env; self._move[wid]=move; self._nav[wid]=nav; self._collision[wid]=col; self._discovery[wid]=disc; self._godot[wid]=GodotIsometricAdapterV15(self,wid)
        self.dungeon_graph(wid).position_sync_callback=lambda npc_id,cc,reason: self.movement(wid).sync_to_geodetic(npc_id,cc,reason=reason)
        self.dungeon_graph(wid).discovery_callback=lambda npc_id,feature_ref,kind: self.discovery(wid).discover(npc_id,feature_ref,kind)
    def create_world(self,owner_scope:str,seed:int,**kwargs)->dict[str,Any]:
        r=super().create_world(owner_scope,seed,**kwargs); wid=r['world']['world_instance_id']; self._attach_v15(wid); h=self.health_v15(wid)
        if h['status']!='PASS': raise ValidationError('V1.5 bootstrap failed:'+str(h['failures']))
        r.update({'version':self.VERSION,'authority':self.AUTHORITY,'v15_health':h}); return r
    def resume_world(self,world_instance_id:str)->dict[str,Any]:
        r=super().resume_world(world_instance_id); self._attach_v15(world_instance_id); h=self.health_v15(world_instance_id)
        if h['status']!='PASS': raise ValidationError('V1.5 resume failed:'+str(h['failures']))
        r.update({'version':self.VERSION,'authority':self.AUTHORITY,'v15_health':h}); return r
    def environment(self,wid): return self._env[wid]
    def movement(self,wid): return self._move[wid]
    def navigation(self,wid): return self._nav[wid]
    def collision(self,wid): return self._collision[wid]
    def discovery(self,wid): return self._discovery[wid]
    def godot(self,wid): return self._godot[wid]
    def health_v15(self,wid):
        base=self.health_v14(wid); parts={'environment':self.environment(wid).verify(),'movement':self.movement(wid).verify(),'navigation':self.navigation(wid).verify(),'discovery':self.discovery(wid).verify(),'godot':self.godot(wid).verify()}; failures=[]
        if base['status']!='PASS': failures.extend('V14:'+x for x in base.get('failures',[]))
        for k,v in parts.items():
            if v['status']!='PASS': failures.extend(k.upper()+':'+x for x in v.get('failures',[]))
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'v14':base,**parts,'authority':self.AUTHORITY}
