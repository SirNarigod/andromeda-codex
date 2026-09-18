from __future__ import annotations
import copy,math,hashlib
from typing import Any
class GodotIsometricAdapterV15:
    VERSION='V1.5.0'; AUTHORITY='GODOT_CLIENT_ADAPTER_SERVER_AUTHORITATIVE'
    def __init__(self,engine:Any,world_instance_id:str):
        self.engine=engine; self.world_instance_id=world_instance_id
        with self.engine.runtime._write_lock:self.engine.runtime.conn.execute('CREATE TABLE IF NOT EXISTS v15_godot_sessions(world_instance_id TEXT NOT NULL,session_ref TEXT NOT NULL,player_ref TEXT NOT NULL,role TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,payload_hash TEXT NOT NULL,PRIMARY KEY(world_instance_id,session_ref))')

    def bind_session(self,session_ref:str,player_ref:str,role:str='PLAYER'):
        role=str(role).upper()
        if role not in ('PLAYER','ADMIN'):return {'status':'REJECTED','reason':'INVALID_SESSION_ROLE'}
        try:self.engine.country(self.world_instance_id).npc(player_ref)
        except KeyError:return {'status':'REJECTED','reason':'UNKNOWN_PLAYER_REF'}
        h=hashlib.sha256(f'{self.world_instance_id}|{session_ref}|{player_ref}|{role}|1'.encode()).hexdigest()
        with self.engine.runtime._write_lock:self.engine.runtime.conn.execute('INSERT OR REPLACE INTO v15_godot_sessions VALUES(?,?,?,?,1,?)',(self.world_instance_id,session_ref,player_ref,role,h))
        return {'status':'PASS','session_ref':session_ref,'player_ref':player_ref,'role':role,'authority':self.AUTHORITY}
    def _session(self,session_ref:str):
        r=self.engine.runtime.conn.execute('SELECT * FROM v15_godot_sessions WHERE world_instance_id=? AND session_ref=?',(self.world_instance_id,session_ref)).fetchone()
        if not r or not int(r['active']):return None
        h=hashlib.sha256(f"{self.world_instance_id}|{r['session_ref']}|{r['player_ref']}|{r['role']}|{r['active']}".encode()).hexdigest()
        if h!=r['payload_hash']:return None
        return dict(r)
    def revoke_session(self,session_ref:str):
        r=self._session(session_ref)
        if not r:return {'status':'REJECTED','reason':'UNKNOWN_OR_INACTIVE_SESSION'}
        h=hashlib.sha256(f"{self.world_instance_id}|{session_ref}|{r['player_ref']}|{r['role']}|0".encode()).hexdigest()
        with self.engine.runtime._write_lock:self.engine.runtime.conn.execute('UPDATE v15_godot_sessions SET active=0,payload_hash=? WHERE world_instance_id=? AND session_ref=?',(h,self.world_instance_id,session_ref))
        return {'status':'PASS','session_ref':session_ref,'revoked':True}
    def client_command(self,session_ref:str,command:str,params:dict|None=None):
        r=self._session(session_ref)
        if not r:return {'status':'REJECTED','reason':'UNKNOWN_OR_INACTIVE_SESSION','authority':self.AUTHORITY}
        return self.command(r['player_ref'],command,params)
    def client_snapshot(self,session_ref:str):
        r=self._session(session_ref)
        if not r:return {'status':'REJECTED','reason':'UNKNOWN_OR_INACTIVE_SESSION','authority':self.AUTHORITY}
        return self.snapshot(r['player_ref'])
    def verify(self):
        failures=[];rows=self.engine.runtime.conn.execute('SELECT * FROM v15_godot_sessions WHERE world_instance_id=?',(self.world_instance_id,)).fetchall();valid={n['id'] for n in self.engine.country(self.world_instance_id)._all_npc_records()}
        for r in rows:
            h=hashlib.sha256(f"{self.world_instance_id}|{r['session_ref']}|{r['player_ref']}|{r['role']}|{r['active']}".encode()).hexdigest()
            if h!=r['payload_hash']:failures.append('SESSION_HASH:'+r['session_ref'])
            if r['player_ref'] not in valid:failures.append('SESSION_ORPHAN_PLAYER:'+r['session_ref'])
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'sessions':len(rows),'authority':self.AUTHORITY}

    def snapshot(self,player_ref):
        st=self.engine.movement(self.world_instance_id).state(player_ref); ch=self.engine.streaming(self.world_instance_id).owners[player_ref]
        payload=self.engine.atlas_lod(self.world_instance_id).godot_chunk_payload(ch); env=self.engine.environment(self.world_instance_id).state_for_block(self.engine.country(self.world_instance_id).npc(player_ref)['block_id'])
        # V1.5 motion-state is the operational authority for NPC transforms and chunk membership.
        base_entities=[copy.deepcopy(e) for e in payload.get('entities',[]) if e.get('kind')!='NPC']
        for npc in self.engine.country(self.world_instance_id)._all_npc_records():
            if self.engine.streaming(self.world_instance_id).owners.get(npc['id'])!=ch:continue
            try:ms=self.engine.movement(self.world_instance_id).state(npc['id'])
            except KeyError:continue
            base_entities.append({'entity_ref':npc['id'],'kind':'NPC','chunk_id':ch,'isometric':{'x_m':round(ms['iso_x_m'],4),'y_m':round(ms['iso_y_m'],4),'z_m':float(ms['altitude_m'])},'data':{'class':npc.get('class'),'state_id':npc.get('state_id'),'block_id':npc.get('block_id'),'city_id':npc.get('city_id'),'scene_id':npc.get('scene_id'),'room_id':npc.get('dungeon_room_id')}})
        known={r['feature_ref'] for r in self.engine.discovery(self.world_instance_id).known(player_ref)}
        secret_kinds={'DUNGEON','DUNGEON_ROOM','DUNGEON_GRAPH_OBJECT'}
        filtered=[]
        for ent in base_entities:
            data=ent.get('data') or {}
            # NPC visibility inside a dungeon is governed by discovered/current room,
            # not by discovery of the NPC id itself. This keeps the player and
            # occupants of a known room visible while hiding occupants of unknown rooms.
            if ent.get('kind')=='NPC' and data.get('room_id'):
                if data.get('room_id') not in known: continue
                filtered.append(ent); continue
            dungeon_bound=ent.get('kind') in secret_kinds or bool(data.get('dungeon_id')) or bool(data.get('room_id'))
            if dungeon_bound and ent.get('entity_ref') not in known: continue
            filtered.append(ent)
        payload=copy.deepcopy(payload); payload['entities']=filtered; payload['entity_count']=len(filtered); payload['player_scoped']=True;payload['npc_positions_authority']='V1.5_MOTION_STATE'
        return {'status':'PASS','player_ref':player_ref,'transform':{'iso_x_m':st['iso_x_m'],'iso_y_m':st['iso_y_m'],'altitude_m':st['altitude_m'],'heading_deg':st['heading_deg']},'chunk':payload,'environment':env,'authority':self.AUTHORITY,'server_authoritative':True}
    def command(self,player_ref,command:str,params:dict|None=None):
        p=copy.deepcopy(params or {}); cmd=command.upper().strip()
        if cmd=='MOVE_VECTOR':
            env=self.engine.environment(self.world_instance_id).state_for_block(self.engine.country(self.world_instance_id).npc(player_ref)['block_id']); mv=self.engine.movement(self.world_instance_id); st=mv.state(player_ref)
            dx=float(p.get('dx',0)); dy=float(p.get('dy',0)); dur=float(p.get('duration_s',.25)); mode=p.get('mode','WALK'); mag=math.hypot(dx,dy)
            if mag>1e-12:
                speed=mv.SPEEDS_MPS.get(str(mode).upper())
                if speed is None: return {'status':'REJECTED','reason':'UNSUPPORTED_MOVE_MODE'}
                dist=speed*dur*env['movement_factor']; nx=st['iso_x_m']+dx/mag*dist; ny=st['iso_y_m']+dy/mag*dist; block=self.engine.collision(self.world_instance_id).point_blocked(player_ref,nx,ny)
                if block.get('blocked'): return {'status':'REJECTED','reason':'COLLISION_BLOCKED','collision_reason':block.get('reason') or block.get('object_type') or 'SPATIAL_BLOCK','collision':copy.deepcopy(block)}
            return mv.step_vector(player_ref,dx,dy,duration_s=dur,mode=mode,environment_factor=env['movement_factor'])
        if cmd=='INTERACT': return self.engine.collision(self.world_instance_id).interact(player_ref,p['object_id'],p['action'],float(p.get('max_distance_m',2.5)))
        if cmd=='DISCOVER': return self.engine.discovery(self.world_instance_id).discover_nearby(player_ref,float(p.get('radius_m',250)))
        if cmd=='DUNGEON_MOVE':
            npc=self.engine.country(self.world_instance_id).npc(player_ref);did=npc.get('scene_id') or npc.get('dungeon_id')
            if not did:return {'status':'REJECTED','reason':'PLAYER_NOT_IN_DUNGEON'}
            return self.engine.dungeon_graph(self.world_instance_id).move(player_ref,did,p['to_room_id'])
        if cmd=='PATH_PLAN':
            npc=self.engine.country(self.world_instance_id).npc(player_ref); return self.engine.navigation(self.world_instance_id).plan_blocks(npc['block_id'],p['destination_block_id'])
        return {'status':'REJECTED','reason':'UNSUPPORTED_GODOT_COMMAND','command':cmd,'authority':self.AUTHORITY}
