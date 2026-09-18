from __future__ import annotations
from typing import Any
import copy
import json, zipfile

class AtlasCountryLOD:
    VERSION='V1.4.0'; AUTHORITY='READ_ONLY_COUNTRY_LOD_PROJECTION'
    LOD_LEVELS={0:'COUNTRY',1:'STATE',2:'BLOCK',3:'SUBREGION',4:'CITY_BIOME_POI',5:'DUNGEON',6:'SCENE_ENTITY'}
    LAYERS=('climate','resources','industry','magic','root','threat','population','commerce','fauna','flora','routes')
    ACCESS_POLICIES={
        'PUBLIC':{'max_lod':4,'blocked_layers':frozenset({'resources','commerce','population','root','threat'})},
        'PLAYER_RUNTIME':{'max_lod':6,'blocked_layers':frozenset()},
        'ADMIN':{'max_lod':6,'blocked_layers':frozenset()},
    }
    def __init__(self,country_system:Any,spatial:Any): self.country=country_system; self.spatial=spatial; self.canonical_routes=self._load_canonical_routes()
    def _load_canonical_routes(self):
        with zipfile.ZipFile(self.country.master_release_path) as z:
            name=next((n for n in z.namelist() if n.endswith('STELLAR_ROUTE_SKELETON_V1_0.json')),None)
            if not name:return []
            data=json.loads(z.read(name).decode('utf-8'))
        cb=list(map(float,self.country.world['country']['bounding_region'])); out=[]
        for r in data.get('routes',[]):
            pts=(r.get('geometry') or {}).get('coordinates') or []
            if not pts:continue
            xs=[float(p[0]) for p in pts];ys=[float(p[1]) for p in pts];rb=[min(xs),min(ys),max(xs),max(ys)]
            intersects=not (rb[2]<cb[0] or rb[0]>cb[2] or rb[3]<cb[1] or rb[1]>cb[3])
            if intersects:out.append(copy.deepcopy(r))
        return out
    def _feature(self,obj,kind,parent=None):
        cc=obj.get('coordinate_center'); f={'id':obj['id'],'name':obj.get('name',obj['id']),'kind':kind,'parent_id':parent,'status':obj.get('status','ACTIVE')}
        if cc:f['coordinate']=copy.deepcopy(cc)
        if obj.get('bounding_region'):f['bounding_region']=copy.deepcopy(obj['bounding_region'])
        return f
    def project(self,lod:int,*,layers:list[str]|None=None,audience:str='PLAYER_RUNTIME')->dict[str,Any]:
        if lod not in self.LOD_LEVELS: raise ValueError('unsupported LOD')
        if audience not in self.ACCESS_POLICIES: raise ValueError('unsupported audience')
        policy=self.ACCESS_POLICIES[audience]
        if lod>policy['max_lod']:
            return {'status':'REJECTED','reason':'AUDIENCE_LOD_RESTRICTED','audience':audience,'lod':lod,'lod_name':self.LOD_LEVELS[lod],'feature_count':0,'features':[],'layers':{},'redacted_layers':[],'authority':self.AUTHORITY}
        c=self.country.world['country']; feats=[]
        if lod==0: feats=[self._feature(c,'COUNTRY')]
        elif lod==1: feats=[self._feature(s,'STATE',c['id']) for s in c['states']]
        elif lod==2: feats=[self._feature(b,'BLOCK',s['id']) for s in c['states'] for b in s['blocks']]
        elif lod==3: feats=[self._feature(sr,'SUBREGION',b['id']) for s in c['states'] for b in s['blocks'] for sr in b.get('subregions',[])]
        elif lod==4:
            for s in c['states']:
                for b in s['blocks']:
                    feats.append({'id':'BIOME@'+b['id'],'name':b['biome']['name'],'kind':'BIOME','parent_id':b['id'],'coordinate':b['coordinate_center'],'biome':copy.deepcopy(b['biome'])})
                    feats.extend(self._feature(x,'CITY',b['id']) for x in b.get('cities',[]))
        elif lod==5: feats=[self._feature(d,'DUNGEON',b['id']) for s in c['states'] for b in s['blocks'] for d in b.get('dungeons',[])]
        else:
            for s in c['states']:
                for b in s['blocks']:
                    feats.extend(self._feature(x,'SCENE_OBJECT',b['id']) for x in b.get('scene_objects',[]))
                    for city in b.get('cities',[]): feats.extend(self._feature(x,'SCENE_OBJECT',city['id']) for x in city.get('scene_objects',[]))
                    for d in b.get('dungeons',[]):
                        feats.extend(self._feature(x,'SCENE_OBJECT',d['id']) for x in d.get('objects',[]))
                        graph=d.get('graph_v2') or {}
                        for room in graph.get('rooms',[]):
                            feats.append(self._feature(room,'DUNGEON_ROOM',d['id']))
                            for obj in room.get('objects',[]):
                                if obj.get('object_ref'): continue
                                feats.append(self._feature(obj,'DUNGEON_GRAPH_OBJECT',room['id']))
        requested=self.LAYERS if layers is None else tuple(layers)
        invalid=[x for x in requested if x not in self.LAYERS]
        if invalid: raise ValueError('unknown layers:'+','.join(invalid))
        redacted=[x for x in requested if x in policy['blocked_layers']]
        use=tuple(x for x in requested if x not in policy['blocked_layers'])
        return {'status':'PASS','audience':audience,'lod':lod,'lod_name':self.LOD_LEVELS[lod],'feature_count':len(feats),'features':copy.deepcopy(feats),'layers':copy.deepcopy(self.layer_projection(use)),'redacted_layers':redacted,'authority':self.AUTHORITY}
    def layer_projection(self,layers=None)->dict[str,Any]:
        use=self.LAYERS if layers is None else tuple(layers); c=self.country.world['country']; out={}
        blocks=[b for s in c['states'] for b in s['blocks']]
        for layer in use:
            rows=[]
            if layer=='climate': rows=[{'block_id':b['id'],**b['climate']} for b in blocks]
            elif layer=='resources': rows=[{'block_id':b['id'],'resource_id':r['id'],'tier':r['tier'],'remaining_units':r['remaining_units'],'status':r['status']} for b in blocks for r in b.get('resources',[])]
            elif layer=='industry': rows=[{'block_id':b['id'],**{k:v for k,v in i.items() if k!='inventory'}} for b in blocks for i in b.get('industries',[])]
            elif layer=='magic': rows=[{'block_id':b['id'],'magic_intensity':b['climate']['magic_intensity'],'kingdoms':len(b.get('kingdoms',[]))} for b in blocks]
            elif layer=='root': rows=[{'block_id':b['id'],'root_deep':True,'biome':copy.deepcopy(b['biome'])['id']} for b in blocks if b.get('root_deep')]
            elif layer=='threat': rows=[{'block_id':b['id'],'predators':sum(f['count'] for f in b.get('fauna',[]) if f.get('role')=='PREDATOR'),'max_threat':max([float(f.get('predator_profile',{}).get('threat_score',0)) for f in b.get('fauna',[])]+[0])} for b in blocks]
            elif layer=='population': rows=[{'block_id':b['id'],'city_id':city['id'],'npcs':len(city.get('npcs',[]))} for b in blocks for city in b.get('cities',[])]
            elif layer=='commerce': rows=[{'block_id':b['id'],'city_id':city['id'],'shops':len(city.get('shops',[])),'stock_units':sum(sum(max(0,int(q)) for q in sh.get('inventory',{}).values()) for sh in city.get('shops',[]))} for b in blocks for city in b.get('cities',[])]
            elif layer=='fauna': rows=[{'block_id':b['id'],'species_ref':f['species_ref'],'count':f['count'],'role':f['role']} for b in blocks for f in b.get('fauna',[])]
            elif layer=='flora': rows=[{'block_id':b['id'],'species_ref':f['species_ref'],'remaining_units':f['remaining_units'],'status':f['status']} for b in blocks for f in b.get('flora',[])]
            elif layer=='routes':
                rows=[{'route_id':r['id'],'name':r.get('name'),'type':r.get('type'),'origin_id':r.get('origin_id'),'destination_id':r.get('destination_id'),'distance_km':r.get('distance_km'),'risk':r.get('risk'),'access_level':r.get('access_level'),'geometry':copy.deepcopy(r.get('geometry')),'authority':'CÂNONE_ESPACIAL'} for r in self.canonical_routes]
            out[layer]={'count':len(rows),'rows':rows}
        return out
    def godot_chunk_payload(self,chunk_id:str)->dict[str,Any]:
        c=self.country.world['country'];entities=[];seen=set()
        def add(ref,kind,cc,data=None):
            if not cc or ref in seen:return
            ch=self.spatial.chunk_for_geodetic(cc['longitude'],cc['latitude'])['chunk_id']
            if ch!=chunk_id:return
            iso=self.spatial.geodetic_to_isometric(cc['longitude'],cc['latitude'],cc.get('altitude_m',0.0));seen.add(ref);entities.append({'entity_ref':ref,'kind':kind,'chunk_id':chunk_id,'isometric':{'x_m':round(iso['iso_x_m'],4),'y_m':round(iso['iso_y_m'],4),'z_m':float(cc.get('altitude_m',0.0))},'data':copy.deepcopy(data or {})})
        for st in c['states']:
            for b in st['blocks']:
                add(b['id'],'BLOCK_ANCHOR',b.get('coordinate_center'),{'state_id':st['id']})
                for city in b.get('cities',[]):
                    add(city['id'],'CITY',city.get('coordinate_center'),{'block_id':b['id']})
                    for o in city.get('scene_objects',[]):add(o['id'],'SCENE_OBJECT',o.get('coordinate_center'),{'object_type':o.get('object_type'),'city_id':city['id']})
                for o in b.get('scene_objects',[]):add(o['id'],'SCENE_OBJECT',o.get('coordinate_center'),{'object_type':o.get('object_type'),'block_id':b['id']})
                for d in b.get('dungeons',[]):
                    add(d['id'],'DUNGEON',d.get('coordinate_center'),{'block_id':b['id']})
                    for o in d.get('objects',[]):add(o['id'],'SCENE_OBJECT',o.get('coordinate_center'),{'object_type':o.get('object_type'),'dungeon_id':d['id']})
                    for room in (d.get('graph_v2') or {}).get('rooms',[]):
                        add(room['id'],'DUNGEON_ROOM',room.get('coordinate_center'),{'dungeon_id':d['id'],'room_type':room.get('room_type'),'level':room.get('level')})
                        for o in room.get('objects',[]):
                            if not o.get('object_ref'):add(o['id'],'DUNGEON_GRAPH_OBJECT',o.get('coordinate_center'),{'room_id':room['id'],'object_type':o.get('object_type'),'item_ref':o.get('item_ref')})
                for npc in self.country._all_npc_records():
                    if npc.get('block_id')==b['id']:
                        add(npc['id'],'NPC',self.spatial.point_for_npc(npc),{'class':npc.get('class'),'state_id':npc.get('state_id'),'block_id':npc.get('block_id'),'city_id':npc.get('city_id'),'scene_id':npc.get('scene_id')})
        return {'status':'PASS','chunk_id':chunk_id,'entity_count':len(entities),'entities':entities,'authority':'READ_ONLY_GODOT_CHUNK_PAYLOAD','world_units':'meters','tile_size_m':self.spatial.tile_size_m}

    def verify(self)->dict[str,Any]:
        failures=[]
        for lod in self.LOD_LEVELS:
            p=self.project(lod,layers=[])
            if p['feature_count']<=0: failures.append('EMPTY_LOD:'+str(lod))
        lp=self.layer_projection()
        for name in self.LAYERS:
            if name not in lp: failures.append('MISSING_LAYER:'+name)
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'lod_levels':len(self.LOD_LEVELS),'layers':len(self.LAYERS)}
