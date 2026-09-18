from __future__ import annotations
import hashlib,math
from typing import Any
class PlayerDiscoverySystem:
    VERSION='V1.5.0'; AUTHORITY='PLAYER_SCOPED_DISCOVERY_FOG_OF_WAR'
    def __init__(self,runtime:Any,world_instance_id:str,lod:Any,spatial:Any,movement:Any):
        self.runtime=runtime; self.world_instance_id=world_instance_id; self.lod=lod; self.spatial=spatial; self.movement=movement; self._init_db()
    def _init_db(self):
        with self.runtime._write_lock:
            self.runtime.conn.execute('CREATE TABLE IF NOT EXISTS v15_player_discovery(world_instance_id TEXT NOT NULL,player_ref TEXT NOT NULL,feature_ref TEXT NOT NULL,kind TEXT NOT NULL,discovered_day INTEGER NOT NULL,discovered_tick INTEGER NOT NULL,payload_hash TEXT NOT NULL,PRIMARY KEY(world_instance_id,player_ref,feature_ref))')
    def discover(self,player_ref,feature_ref,kind='FEATURE'):
        c=self.runtime.get_clock(self.world_instance_id); h=hashlib.sha256(f'{self.world_instance_id}|{player_ref}|{feature_ref}|{kind}|{c["day"]}|{c["tick"]}'.encode()).hexdigest()
        with self.runtime._write_lock:
            self.runtime.conn.execute('INSERT OR IGNORE INTO v15_player_discovery VALUES(?,?,?,?,?,?,?)',(self.world_instance_id,player_ref,feature_ref,kind,int(c['day']),int(c['tick']),h))
        return {'status':'PASS','player_ref':player_ref,'feature_ref':feature_ref,'kind':kind,'authority':self.AUTHORITY}
    def known(self,player_ref):
        return [dict(r) for r in self.runtime.conn.execute('SELECT player_ref,feature_ref,kind,discovered_day,discovered_tick FROM v15_player_discovery WHERE world_instance_id=? AND player_ref=? ORDER BY feature_ref',(self.world_instance_id,player_ref)).fetchall()]
    def _scene_discovery_allowed(self,player_ref,feature):
        npc=self.movement.country.npc(player_ref);kind=feature.get('kind');scene=npc.get('scene_id') or npc.get('dungeon_id');room=npc.get('dungeon_room_id')
        if kind=='DUNGEON_ROOM':return bool(scene and room and feature.get('id')==room)
        if kind=='DUNGEON_GRAPH_OBJECT':return bool(scene and room and feature.get('parent_id')==room)
        if kind=='SCENE_OBJECT' and scene:
            # In a dungeon, only physical objects assigned to the current room are discoverable.
            try:
                d=self.movement.country.scenes_dungeon(scene) if hasattr(self.movement.country,'scenes_dungeon') else None
            except Exception:d=None
            if d is None:
                for stc in self.movement.country.world['country']['states']:
                    for b in stc['blocks']:
                        for dd in b.get('dungeons',[]):
                            if dd['id']==scene:d=dd;break
            if d:
                rr=next((x for x in (d.get('graph_v2') or {}).get('rooms',[]) if x['id']==room),None)
                allowed={o.get('object_ref') for o in (rr or {}).get('objects',[]) if o.get('object_ref')}
                if feature.get('parent_id')==scene:return feature.get('id') in allowed
        return True
    def discover_nearby(self,player_ref,radius_m=250.0):
        st=self.movement.state(player_ref); refs=[]
        for lod_level in (2,3,4,5,6):
            for f in self.lod.project(lod_level,audience='PLAYER_RUNTIME')['features']:
                if not self._scene_discovery_allowed(player_ref,f):continue
                cc=f.get('coordinate')
                if not cc: continue
                iso=self.spatial.geodetic_to_isometric(cc['longitude'],cc['latitude'],cc.get('altitude_m',0)); d=math.hypot(st['iso_x_m']-iso['iso_x_m'],st['iso_y_m']-iso['iso_y_m'])
                if d<=radius_m: self.discover(player_ref,f['id'],f['kind']); refs.append(f['id'])
        return {'status':'PASS','discovered_or_known':len(refs),'feature_refs':sorted(set(refs)),'radius_m':float(radius_m),'authority':self.AUTHORITY}

    def verify(self):
        failures=[];rows=self.runtime.conn.execute('SELECT * FROM v15_player_discovery WHERE world_instance_id=? ORDER BY player_ref,feature_ref',(self.world_instance_id,)).fetchall();valid_players={n['id'] for n in self.movement.country._all_npc_records()}
        for r in rows:
            expected=hashlib.sha256(f"{self.world_instance_id}|{r['player_ref']}|{r['feature_ref']}|{r['kind']}|{r['discovered_day']}|{r['discovered_tick']}".encode()).hexdigest()
            if expected!=r['payload_hash']:failures.append('DISCOVERY_HASH:'+r['player_ref']+':'+r['feature_ref'])
            if r['player_ref'] not in valid_players:failures.append('DISCOVERY_ORPHAN_PLAYER:'+r['player_ref'])
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'records':len(rows),'authority':self.AUTHORITY}

    def player_projection(self,player_ref,lod_level):
        base=self.lod.project(lod_level,audience='PLAYER_RUNTIME'); known={r['feature_ref'] for r in self.known(player_ref)}
        features=[f for f in base['features'] if f['id'] in known or lod_level<=1]
        return {'status':'PASS','audience':'PLAYER_SCOPED','player_ref':player_ref,'lod':lod_level,'feature_count':len(features),'features':features,'authority':self.AUTHORITY}
