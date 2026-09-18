from __future__ import annotations
import math
from typing import Any
class CollisionInteractionSystem:
    VERSION='V1.5.0'; AUTHORITY='LIVING_LOCAL_COLLISION_INTERACTION_GATE'
    RADII={'DOOR':1.0,'TRAPDOOR':.8,'CHAIR':.7,'BOOK':.4,'TORCH':.4,'GROUND_WEAPON':.6,'CHEST':.8,'LEVER':.5,'RUNE_PEDESTAL':1.0,'CONSOLE':.8}
    DUNGEON_ROOM_RADIUS_M=14.0
    def __init__(self,country:Any,spatial:Any,movement:Any,scenes:Any): self.country=country; self.spatial=spatial; self.movement=movement; self.scenes=scenes
    def _dist(self,npc_id,obj):
        st=self.movement.state(npc_id); cc=obj.get('coordinate_center')
        if not cc: return math.inf
        iso=self.spatial.geodetic_to_isometric(cc['longitude'],cc['latitude'],cc.get('altitude_m',0)); return math.hypot(st['iso_x_m']-iso['iso_x_m'],st['iso_y_m']-iso['iso_y_m'])
    def can_interact(self,npc_id,object_id,max_distance_m=2.5):
        b,c,d,o=self.scenes.scene_object(object_id); npc=self.country.npc(npc_id); local,reason=self.scenes._locality(npc,b,c,d)
        if not local: return {'status':'REJECTED','reason':reason}
        dist=self._dist(npc_id,o)
        if dist>float(max_distance_m): return {'status':'REJECTED','reason':'OUT_OF_INTERACTION_RANGE','distance_m':round(dist,3),'max_distance_m':max_distance_m}
        return {'status':'PASS','distance_m':round(dist,3),'object_type':o['object_type'],'authority':self.AUTHORITY}
    def interact(self,npc_id,object_id,action,max_distance_m=2.5):
        gate=self.can_interact(npc_id,object_id,max_distance_m)
        if gate['status']!='PASS': return gate
        out=self.scenes.interact(npc_id,object_id,action); out['distance_m']=gate['distance_m']; out['authority']=self.AUTHORITY; return out
    def point_blocked(self,npc_id,iso_x_m,iso_y_m):
        npc=self.country.npc(npc_id)
        scene_id=npc.get('scene_id') or npc.get('dungeon_id'); room_id=npc.get('dungeon_room_id')
        if scene_id and room_id:
            try:
                d=self.scenes.dungeon(scene_id); room=next(r for r in (d.get('graph_v2') or {}).get('rooms',[]) if r['id']==room_id);cc=room.get('coordinate_center')
                if cc:
                    iso=self.spatial.geodetic_to_isometric(cc['longitude'],cc['latitude'],cc.get('altitude_m',0));dist=math.hypot(float(iso_x_m)-iso['iso_x_m'],float(iso_y_m)-iso['iso_y_m'])
                    if dist>self.DUNGEON_ROOM_RADIUS_M:return {'blocked':True,'reason':'ROOM_BOUNDARY_BLOCKED','room_id':room_id,'distance_from_room_center_m':round(dist,3)}
            except (KeyError,StopIteration):
                return {'blocked':True,'reason':'ROOM_SPATIAL_STATE_INVALID','room_id':room_id}
        for b,c,d,o in self.scenes._all_objects():
            local,_=self.scenes._locality(npc,b,c,d)
            if not local or o.get('object_type') not in ('DOOR','CHEST','CONSOLE','RUNE_PEDESTAL'): continue
            if o.get('object_type')=='DOOR' and o.get('is_open'): continue
            cc=o.get('coordinate_center')
            if not cc: continue
            iso=self.spatial.geodetic_to_isometric(cc['longitude'],cc['latitude'],cc.get('altitude_m',0)); rad=self.RADII.get(o['object_type'],.6)
            if math.hypot(float(iso_x_m)-iso['iso_x_m'],float(iso_y_m)-iso['iso_y_m'])<rad: return {'blocked':True,'object_id':o['id'],'object_type':o['object_type']}
        return {'blocked':False}
