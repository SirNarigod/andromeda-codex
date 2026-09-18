from __future__ import annotations
import hashlib, random, copy
from typing import Any

def _seed(*parts):return int(hashlib.sha256('|'.join(map(str,parts)).encode()).hexdigest()[:16],16)

class DungeonGraphV2:
    VERSION='V1.4.0';AUTHORITY='LIVING_DUNGEON_GRAPH_RUNTIME'
    ROOM_TYPES=('ENTRANCE','CORRIDOR','ARMORY','LIBRARY','PUZZLE','TREASURE','SANCTUM','PREDATOR_NEST')
    def __init__(self,country_system:Any,scene_system:Any,streaming=None,spatial=None):self.country=country_system;self.scene=scene_system;self.streaming=streaming;self.spatial=spatial;self.position_sync_callback=None;self.discovery_callback=None;self.bootstrap()
    def bootstrap(self):
        created=0
        for st in self.country.world['country']['states']:
            for b in st['blocks']:
                for d in b.get('dungeons',[]):
                    if not d.get('graph_v2'):d['graph_v2']=self._make_graph(d,b);created+=1
        self.country.reconcile_country_inventory()
        if created and self.country.runtime and self.country.world_instance_id:self.country._record_event('DUNGEON_GRAPH_V2_BOOTSTRAPPED',{'dungeons':created})
        return {'status':'PASS','created':created}
    def _make_graph(self,d,b):
        rng=random.Random(_seed(self.country.seed,d['id'],'graph-v2')); count=4+rng.randint(0,4); rooms=[]
        types=['ENTRANCE']+[rng.choice(self.ROOM_TYPES[1:]) for _ in range(count-2)]+[('PREDATOR_NEST' if b.get('root_deep') else 'SANCTUM')]
        for i,t in enumerate(types):
            level=0 if i<count-1 else (1 if rng.random()<.35 else 0);dx=(i%3)*36.0-36.0;dy=(i//3)*36.0 + level*12.0
            cc=self.spatial.offset_geodetic(d['coordinate_center'],dx,dy) if self.spatial is not None else dict(d['coordinate_center'])
            rooms.append({'id':f"{d['id']}-R{i+1:02d}",'name':self._room_name(t,i+1,d),'room_type':t,'level':level,'darkness':max(0,min(100,int(d['darkness_level']+rng.randint(-15,15)))),'coordinate_center':cc,'local_offset_m':{'x':dx,'y':dy,'z':level*4.0},'objects':[],'visited_by':[]})
        edges=[]
        for i in range(len(rooms)-1):
            et='TRAPDOOR' if rooms[i+1]['level']!=rooms[i]['level'] else 'DOOR'; locked=(i>0 and rng.random()<.25); key=f"KEY-{d['id']}-{i+1:02d}" if locked else None
            edges.append({'id':f"{d['id']}-E{i+1:02d}",'from':rooms[i]['id'],'to':rooms[i+1]['id'],'type':et,'locked':locked,'key_item_ref':key,'secret':False,'open':not locked})
            if locked:
                # Put a named runtime key in the preceding room and make it discoverable.
                rooms[max(0,i-1)]['objects'].append({'id':f'OBJ-{key}','object_type':'KEY','item_ref':key,'name':f'Chave de {d["name"]} {i+1}','quantity':1,'status':'ACTIVE'})
        if len(rooms)>=5:
            edges.append({'id':f"{d['id']}-E-SECRET",'from':rooms[1]['id'],'to':rooms[-1]['id'],'type':'SECRET_PASSAGE','locked':False,'key_item_ref':None,'secret':True,'open':False})
        # Assign existing objects deterministically to rooms without duplicating them.
        for idx,obj in enumerate(d.get('objects',[])):rooms[idx%len(rooms)]['objects'].append({'object_ref':obj['id'],'object_type':obj['object_type'],'name':obj.get('name',obj['id'])})
        if self.spatial is not None:
            by={r['id']:r for r in rooms}
            for e in edges:
                a=by[e['from']]['coordinate_center'];z=by[e['to']]['coordinate_center'];pa=self.spatial.geodetic_to_isometric(a['longitude'],a['latitude']);pz=self.spatial.geodetic_to_isometric(z['longitude'],z['latitude']);e['length_m']=round(((pa['local_x_m']-pz['local_x_m'])**2+(pa['local_y_m']-pz['local_y_m'])**2)**0.5,3)
        for r in rooms:
            for o in r['objects']:
                if not o.get('object_ref'):o['coordinate_center']=copy.deepcopy(r['coordinate_center'])
        return {'version':'2.0','rooms':rooms,'edges':edges,'entrance_room_id':rooms[0]['id'],'final_room_id':rooms[-1]['id'],'current_occupants':{},'authority':self.AUTHORITY}
    def _room_name(self,t,i,d):
        names={'ENTRANCE':'Átrio','CORRIDOR':'Galeria','ARMORY':'Arsenal','LIBRARY':'Arquivo','PUZZLE':'Câmara de Enigma','TREASURE':'Cofre','SANCTUM':'Santuário','PREDATOR_NEST':'Ninho Predatório'}
        return f"{names[t]} {i} — {d['name']}"
    def dungeon(self,did):return self.scene.dungeon(did)
    def enter(self,npc_id,dungeon_id):
        x=self.scene.enter_dungeon(npc_id,dungeon_id)
        if x.get('status')!='PASS':return x
        d=self.dungeon(dungeon_id);g=d['graph_v2'];n=self.country.npc(npc_id);rid=g['entrance_room_id'];n['dungeon_room_id']=rid;g['current_occupants'][npc_id]=rid;self._visit(g,rid,npc_id)
        if self.discovery_callback is not None:self.discovery_callback(npc_id,rid,'DUNGEON_ROOM')
        ownership=None
        if self.streaming is not None:
            room=next(r for r in g['rooms'] if r['id']==rid);cc=room['coordinate_center'];
            if self.position_sync_callback is not None:self.position_sync_callback(npc_id,cc,'DUNGEON_ENTER')
            ch=self.streaming.spatial.chunk_for_geodetic(cc['longitude'],cc['latitude'])['chunk_id']; ownership=self.streaming.transfer(npc_id,ch)
        self.country._record_event('DUNGEON_ROOM_ENTERED',{'npc_id':npc_id,'dungeon_id':dungeon_id,'room_id':rid,'ownership':ownership});return {'status':'PASS','npc_id':npc_id,'dungeon_id':dungeon_id,'room_id':rid,'ownership':ownership}
    def move(self,npc_id,dungeon_id,to_room_id):
        d=self.dungeon(dungeon_id);g=d['graph_v2'];n=self.country.npc(npc_id);cur=n.get('dungeon_room_id')
        if (n.get('scene_id') or n.get('dungeon_id'))!=dungeon_id:return {'status':'REJECTED','reason':'NPC_NOT_IN_DUNGEON'}
        e=next((x for x in g['edges'] if {x['from'],x['to']}=={cur,to_room_id}),None)
        if not e:return {'status':'REJECTED','reason':'ROOM_NOT_ADJACENT'}
        if e['secret'] and not e['open']:return {'status':'REJECTED','reason':'SECRET_PASSAGE_UNDISCOVERED','edge_id':e['id']}
        if e['locked']:
            key=e['key_item_ref']
            if int(n.get('inventory',{}).get(key,0))<=0:return {'status':'REJECTED','reason':'LOCKED_KEY_REQUIRED','key_item_ref':key,'edge_id':e['id']}
            e['locked']=False;e['open']=True
        n['dungeon_room_id']=to_room_id;g['current_occupants'][npc_id]=to_room_id;self._visit(g,to_room_id,npc_id)
        if self.discovery_callback is not None:self.discovery_callback(npc_id,to_room_id,'DUNGEON_ROOM')
        ownership=None
        if self.streaming is not None:
            room=next(r for r in g['rooms'] if r['id']==to_room_id);cc=room['coordinate_center'];
            if self.position_sync_callback is not None:self.position_sync_callback(npc_id,cc,'DUNGEON_ROOM_MOVE')
            ch=self.streaming.spatial.chunk_for_geodetic(cc['longitude'],cc['latitude'])['chunk_id'];ownership=self.streaming.transfer(npc_id,ch)
        self.country._record_event('DUNGEON_ROOM_MOVED',{'npc_id':npc_id,'dungeon_id':dungeon_id,'from_room_id':cur,'room_id':to_room_id,'edge_id':e['id'],'ownership':ownership});return {'status':'PASS','room_id':to_room_id,'edge_id':e['id'],'ownership':ownership}
    def take_room_key(self,npc_id,dungeon_id,room_id,key_ref):
        d=self.dungeon(dungeon_id);g=d['graph_v2'];n=self.country.npc(npc_id)
        if n.get('dungeon_room_id')!=room_id:return {'status':'REJECTED','reason':'NPC_NOT_IN_ROOM'}
        room=next(r for r in g['rooms'] if r['id']==room_id);o=next((o for o in room['objects'] if o.get('item_ref')==key_ref and o.get('quantity',0)>0),None)
        if not o:return {'status':'REJECTED','reason':'KEY_NOT_AVAILABLE'}
        n['inventory'][key_ref]=n['inventory'].get(key_ref,0)+1;o['quantity']=0;o['status']='TAKEN';self.country.reconcile_country_inventory();self.country._record_event('DUNGEON_KEY_TAKEN',{'npc_id':npc_id,'dungeon_id':dungeon_id,'room_id':room_id,'item_ref':key_ref});return {'status':'PASS','item_ref':key_ref}
    def discover_secret(self,npc_id,dungeon_id,edge_id):
        d=self.dungeon(dungeon_id);g=d['graph_v2'];e=next((x for x in g['edges'] if x['id']==edge_id),None)
        if not e or not e['secret']:return {'status':'REJECTED','reason':'NOT_SECRET_EDGE'}
        e['open']=True;self.country._record_event('DUNGEON_SECRET_DISCOVERED',{'npc_id':npc_id,'dungeon_id':dungeon_id,'edge_id':edge_id});return {'status':'PASS','edge_id':edge_id}
    def leave(self,npc_id):
        n=self.country.npc(npc_id);did=n.get('scene_id') or n.get('dungeon_id');d=self.dungeon(did) if did else None
        if d:d['graph_v2']['current_occupants'].pop(npc_id,None)
        n['dungeon_room_id']=None;out=self.scene.leave_dungeon(npc_id)
        if out.get('status')=='PASS' and self.streaming is not None:
            outside=self.country.block(n['block_id'])['coordinate_center']
            if self.position_sync_callback is not None:self.position_sync_callback(npc_id,outside,'DUNGEON_LEAVE')
            ch=self.streaming.owner_chunk_for_npc(npc_id);out['ownership']=self.streaming.transfer(npc_id,ch)
        return out
    def _visit(self,g,rid,nid):
        r=next(x for x in g['rooms'] if x['id']==rid)
        if nid not in r['visited_by']:r['visited_by'].append(nid)
    def validate(self):
        fail=[];count=0
        for st in self.country.world['country']['states']:
            for b in st['blocks']:
                for d in b.get('dungeons',[]):
                    count+=1;g=d.get('graph_v2');
                    if not g:fail.append('NO_GRAPH:'+d['id']);continue
                    ids={r['id'] for r in g['rooms']}
                    if g['entrance_room_id'] not in ids or g['final_room_id'] not in ids:fail.append('GRAPH_ENDPOINT:'+d['id'])
                    seen={g['entrance_room_id']};changed=True
                    while changed:
                        changed=False
                        for e in g['edges']:
                            if e['from'] in seen and e['to'] not in seen:seen.add(e['to']);changed=True
                            if e['to'] in seen and e['from'] not in seen:seen.add(e['from']);changed=True
                    if ids-seen:fail.append('DISCONNECTED:'+d['id'])
        return {'status':'PASS' if not fail else 'FAIL','failures':fail,'dungeons':count}
