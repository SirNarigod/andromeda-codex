from __future__ import annotations
import json, hashlib, math
from typing import Any

class ChunkStreamingSystem:
    VERSION='V1.4.0'; AUTHORITY='LIVING_ISOMETRIC_CHUNK_STREAMING_RUNTIME'
    def __init__(self,runtime:Any,world_instance_id:str,country_system:Any,spatial:Any,advance_ticks_callback=None):
        self.runtime=runtime; self.world_instance_id=world_instance_id; self.country=country_system; self.spatial=spatial; self.advance_ticks_callback=advance_ticks_callback
        self.loaded:set[str]=set(); self.owners:dict[str,str]={}; self.position_resolver=None; self._init_db(); self._load_state(); self.bootstrap_country_npcs()
    def _init_db(self):
        with self.runtime._write_lock:self.runtime.conn.executescript('''
        CREATE TABLE IF NOT EXISTS chunk_stream_state(world_instance_id TEXT NOT NULL,chunk_id TEXT NOT NULL,loaded INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(world_instance_id,chunk_id));
        CREATE TABLE IF NOT EXISTS chunk_entity_ownership(world_instance_id TEXT NOT NULL,entity_ref TEXT NOT NULL,chunk_id TEXT NOT NULL,payload_hash TEXT NOT NULL,PRIMARY KEY(world_instance_id,entity_ref));
        ''')
    def _load_state(self):
        for r in self.runtime.conn.execute('SELECT chunk_id FROM chunk_stream_state WHERE world_instance_id=? AND loaded=1',(self.world_instance_id,)).fetchall():self.loaded.add(r['chunk_id'])
        for r in self.runtime.conn.execute('SELECT entity_ref,chunk_id FROM chunk_entity_ownership WHERE world_instance_id=?',(self.world_instance_id,)).fetchall():self.owners[r['entity_ref']]=r['chunk_id']
    def _persist_owner(self,entity_ref,chunk_id):
        h=hashlib.sha256(f'{entity_ref}|{chunk_id}'.encode()).hexdigest()
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT OR REPLACE INTO chunk_entity_ownership(world_instance_id,entity_ref,chunk_id,payload_hash) VALUES(?,?,?,?)',(self.world_instance_id,entity_ref,chunk_id,h))
    def load_chunk(self,chunk_id:str,*,reason='REQUEST')->dict[str,Any]:
        self.loaded.add(chunk_id)
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT OR REPLACE INTO chunk_stream_state(world_instance_id,chunk_id,loaded) VALUES(?,?,1)',(self.world_instance_id,chunk_id))
        return {'status':'PASS','chunk_id':chunk_id,'loaded':True,'reason':reason}
    def unload_chunk(self,chunk_id:str,*,force=False)->dict[str,Any]:
        active=[e for e,c in self.owners.items() if c==chunk_id]
        if active and not force:return {'status':'REJECTED','reason':'ACTIVE_ENTITY_OWNERSHIP','chunk_id':chunk_id,'entities':active}
        self.loaded.discard(chunk_id)
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT OR REPLACE INTO chunk_stream_state(world_instance_id,chunk_id,loaded) VALUES(?,?,0)',(self.world_instance_id,chunk_id))
        return {'status':'PASS','chunk_id':chunk_id,'loaded':False,'serialized_entities':len(active)}
    def owner_chunk_for_npc(self,npc_id:str)->str:
        if self.position_resolver is not None:
            p=self.position_resolver(npc_id)
        else:
            n=self.country.npc(npc_id); p=self.spatial.point_for_npc(n)
        return self.spatial.chunk_for_geodetic(p['longitude'],p['latitude'])['chunk_id']
    def bootstrap_country_npcs(self)->dict[str,Any]:
        created=0
        for n in self.country._all_npc_records():
            ch=self.owner_chunk_for_npc(n['id'])
            if n['id'] not in self.owners: self.owners[n['id']]=ch;self._persist_owner(n['id'],ch);created+=1
            self.load_chunk(ch,reason='ACTIVE_ENTITY_BOOTSTRAP')
        return {'status':'PASS','owners':len(self.owners),'created':created,'active_chunks_loaded':len(set(self.owners.values()))}
    def prune_loaded_chunks(self,keep_chunks:set[str]|None=None)->dict[str,Any]:
        keep=set(keep_chunks or set()) | set(self.owners.values())
        removed=[]
        for cid in list(self.loaded):
            if cid in keep: continue
            out=self.unload_chunk(cid)
            if out.get('status')=='PASS': removed.append(cid)
        return {'status':'PASS','removed':len(removed),'loaded_chunks':len(self.loaded),'kept':len(keep)}

    def transfer(self,entity_ref:str,new_chunk_id:str)->dict[str,Any]:
        old=self.owners.get(entity_ref); self.load_chunk(new_chunk_id,reason='OWNERSHIP_TRANSFER'); self.owners[entity_ref]=new_chunk_id;self._persist_owner(entity_ref,new_chunk_id)
        return {'status':'PASS','entity_ref':entity_ref,'from_chunk':old,'to_chunk':new_chunk_id,'identity_preserved':True}
    def travel_npc(self,npc_id:str,destination_block_id:str,*,destination_city_id:str|None=None,speed_kmh:float=5.0,preload_radius:int=1)->dict[str,Any]:
        if speed_kmh<=0:raise ValueError('speed_kmh must be positive')
        n=self.country.npc(npc_id); srcp=self.spatial.point_for_npc(n); dstb=self.country.block(destination_block_id)
        if destination_city_id:
            city=self.country.city(destination_city_id)
            if city.get('block_id') not in (None,destination_block_id) and not any(c['id']==destination_city_id for c in dstb.get('cities',[])): return {'status':'REJECTED','reason':'CITY_NOT_IN_DESTINATION_BLOCK'}
            dstp=city['coordinate_center']
        else:dstp=dstb['coordinate_center']
        a=self.spatial.chunk_for_geodetic(srcp['longitude'],srcp['latitude']); z=self.spatial.chunk_for_geodetic(dstp['longitude'],dstp['latitude'])
        # Deterministic DDA through virtual chunk grid.
        x0,y0=a['chunk_x'],a['chunk_y']; x1,y1=z['chunk_x'],z['chunk_y']; steps=max(abs(x1-x0),abs(y1-y0),1); path=[]
        for i in range(steps+1):
            t=i/steps; cx=round(x0+(x1-x0)*t); cy=round(y0+(y1-y0)*t); cid=f'CHK-{cx:+07d}-{cy:+07d}'
            if not path or path[-1]!=cid:path.append(cid)
        for cid in self.spatial.chunk_neighbors(z['chunk_id'],preload_radius):self.load_chunk(cid,reason='DESTINATION_PRELOAD')
        move=self.country.relocate_npc(npc_id,destination_block_id,destination_city_id=destination_city_id)
        if move.get('status')!='PASS':return move
        trans=self.transfer(npc_id,z['chunk_id']); hours=round(float(move['distance_km'])/float(speed_kmh),4)
        clock=self.runtime.get_clock(self.world_instance_id); hours_per_tick=26.0/float(clock['ticks_per_day']); travel_ticks=max(1,int(math.ceil(hours/hours_per_tick)))
        if self.advance_ticks_callback is not None:self.advance_ticks_callback(travel_ticks)
        else:self.runtime.advance_ticks(self.world_instance_id,travel_ticks,source='SYSTEM_RECONCILIATION')
        keep=set(self.spatial.chunk_neighbors(z['chunk_id'],preload_radius));prune=self.prune_loaded_chunks(keep)
        return {'status':'PASS','npc_id':npc_id,'distance_km':move['distance_km'],'travel_hours':hours,'travel_ticks':travel_ticks,'stellar_day_hours':26.0,'speed_kmh':float(speed_kmh),'source_chunk':a['chunk_id'],'destination_chunk':z['chunk_id'],'chunk_path':path,'chunk_transitions':max(0,len(path)-1),'ownership':trans,'stream_prune':prune,'identity_preserved':self.country.npc(npc_id)['id']==npc_id}
    def full_integrity_check(self)->dict[str,Any]:
        failures=[]; npcs=self.country._all_npc_records(); ids={n['id'] for n in npcs}
        if len(self.owners)!=len(set(self.owners)):failures.append('DUP_OWNER_KEYS')
        for n in npcs:
            exp=self.owner_chunk_for_npc(n['id']); got=self.owners.get(n['id'])
            if got!=exp:failures.append('OWNER_LOCATION_DIVERGENCE:'+n['id']+':'+str(got)+':'+exp)
            if got not in self.loaded:failures.append('ACTIVE_OWNER_CHUNK_UNLOADED:'+n['id']+':'+str(got))
            row=self.runtime.conn.execute('SELECT payload_hash,chunk_id FROM chunk_entity_ownership WHERE world_instance_id=? AND entity_ref=?',(self.world_instance_id,n['id'])).fetchone()
            if not row:failures.append('OWNER_DB_MISSING:'+n['id'])
            elif hashlib.sha256(f"{n['id']}|{row['chunk_id']}".encode()).hexdigest()!=row['payload_hash']:failures.append('OWNER_HASH:'+n['id'])
        extras=set(self.owners)-ids
        if extras:failures.extend('ORPHAN_OWNER:'+x for x in sorted(extras))
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'owners':len(self.owners),'loaded_chunks':len(self.loaded)}
