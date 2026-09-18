from __future__ import annotations
import json, math, hashlib
from typing import Any

class ContinuousMovementSystem:
    VERSION='V1.5.0'; AUTHORITY='LIVING_CONTINUOUS_ISOMETRIC_MOVEMENT_RUNTIME'
    SPEEDS_MPS={'WALK':1.6,'RUN':4.8,'CROUCH':0.9}
    CITY_RUNTIME_RADIUS_M=750.0
    def __init__(self,runtime:Any,world_instance_id:str,country:Any,spatial:Any,streaming:Any,environment:Any|None=None,advance_ticks_callback=None):
        self.runtime=runtime; self.world_instance_id=world_instance_id; self.country=country; self.spatial=spatial; self.streaming=streaming; self.environment=environment; self.advance_ticks_callback=advance_ticks_callback
        self._init_db(); self.bootstrap()
    def _init_db(self):
        with self.runtime._write_lock:
            self.runtime.conn.execute("""CREATE TABLE IF NOT EXISTS v15_motion_state(
                world_instance_id TEXT NOT NULL, entity_ref TEXT NOT NULL, iso_x_m REAL NOT NULL, iso_y_m REAL NOT NULL,
                altitude_m REAL NOT NULL DEFAULT 0, stamina REAL NOT NULL DEFAULT 100, mode TEXT NOT NULL DEFAULT 'WALK',
                heading_deg REAL NOT NULL DEFAULT 0, elapsed_s REAL NOT NULL DEFAULT 0, payload_hash TEXT NOT NULL,
                PRIMARY KEY(world_instance_id,entity_ref))""")
    def _hash(self,d):
        return hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def _save(self,entity_ref,state):
        payload={k:state[k] for k in ('iso_x_m','iso_y_m','altitude_m','stamina','mode','heading_deg','elapsed_s')}; h=self._hash(payload)
        with self.runtime._write_lock:
            self.runtime.conn.execute('INSERT OR REPLACE INTO v15_motion_state VALUES(?,?,?,?,?,?,?,?,?,?)',(
                self.world_instance_id,entity_ref,payload['iso_x_m'],payload['iso_y_m'],payload['altitude_m'],payload['stamina'],
                payload['mode'],payload['heading_deg'],payload['elapsed_s'],h))
    def _row_state(self,r):
        d={'iso_x_m':float(r['iso_x_m']),'iso_y_m':float(r['iso_y_m']),'altitude_m':float(r['altitude_m']),
           'stamina':float(r['stamina']),'mode':r['mode'],'heading_deg':float(r['heading_deg']),'elapsed_s':float(r['elapsed_s'])}
        if self._hash(d)!=r['payload_hash']: raise ValueError('motion state hash mismatch')
        return d
    def bootstrap(self):
        created=0
        for n in self.country._all_npc_records():
            row=self.runtime.conn.execute('SELECT * FROM v15_motion_state WHERE world_instance_id=? AND entity_ref=?',(self.world_instance_id,n['id'])).fetchone()
            if row: continue
            p=self.spatial.point_for_npc(n); iso=self.spatial.geodetic_to_isometric(p['longitude'],p['latitude'],p.get('altitude_m',0))
            self._save(n['id'],{'iso_x_m':iso['iso_x_m'],'iso_y_m':iso['iso_y_m'],'altitude_m':p.get('altitude_m',0.0),
                                'stamina':100.0,'mode':'WALK','heading_deg':0.0,'elapsed_s':0.0}); created+=1
        return {'status':'PASS','created':created}
    def state(self,entity_ref):
        r=self.runtime.conn.execute('SELECT * FROM v15_motion_state WHERE world_instance_id=? AND entity_ref=?',(self.world_instance_id,entity_ref)).fetchone()
        if not r: raise KeyError(entity_ref)
        return {'entity_ref':entity_ref,**self._row_state(r),'authority':self.AUTHORITY}
    def _block_for_geodetic(self,lon,lat):
        for st in self.country.world['country']['states']:
            for b in st['blocks']:
                x0,y0,x1,y1=map(float,b['bounding_region'])
                if x0-1e-9<=lon<=x1+1e-9 and y0-1e-9<=lat<=y1+1e-9: return st,b
        return None,None
    def _advance_clock(self,state,seconds):
        state['elapsed_s']+=float(seconds); clock=self.runtime.get_clock(self.world_instance_id)
        seconds_per_tick=26.0*3600.0/float(clock['ticks_per_day']); ticks=int(state['elapsed_s']//seconds_per_tick)
        if ticks>0:
            state['elapsed_s']-=ticks*seconds_per_tick
            if self.advance_ticks_callback is not None: self.advance_ticks_callback(ticks)
            else: self.runtime.advance_ticks(self.world_instance_id,ticks,source='SYSTEM_RECONCILIATION')
        return ticks
    def step_vector(self,entity_ref:str,dx:float,dy:float,*,duration_s:float=.25,mode:str='WALK',environment_factor:float|None=None):
        if duration_s<=0 or duration_s>10: return {'status':'REJECTED','reason':'INVALID_STEP_DURATION'}
        mode=mode.upper()
        if mode not in self.SPEEDS_MPS: return {'status':'REJECTED','reason':'UNSUPPORTED_MOVE_MODE'}
        mag=math.hypot(float(dx),float(dy))
        if mag<=1e-12: return {'status':'PASS','moved_m':0.0,**self.state(entity_ref)}
        st=self.state(entity_ref); base=self.SPEEDS_MPS[mode]
        if mode=='RUN' and st['stamina']<5: return {'status':'REJECTED','reason':'INSUFFICIENT_STAMINA','stamina':st['stamina']}
        envf=max(.25,min(1.25,float(environment_factor) if environment_factor is not None else 1.0))
        maxdist=base*float(duration_s)*envf; ux,uy=float(dx)/mag,float(dy)/mag
        nx=st['iso_x_m']+ux*maxdist; ny=st['iso_y_m']+uy*maxdist
        geo=self.spatial.isometric_to_geodetic(nx,ny,st['altitude_m']); box=list(map(float,self.country.world['country']['bounding_region']))
        if not(box[0]<=geo['longitude']<=box[2] and box[1]<=geo['latitude']<=box[3]): return {'status':'REJECTED','reason':'COUNTRY_BOUNDARY_BLOCKED'}
        state={k:st[k] for k in ('iso_x_m','iso_y_m','altitude_m','stamina','mode','heading_deg','elapsed_s')}
        state.update({'iso_x_m':nx,'iso_y_m':ny,'mode':mode,'heading_deg':(math.degrees(math.atan2(uy,ux))+360)%360})
        state['stamina']=max(0.0,state['stamina']-duration_s*4.0) if mode=='RUN' else min(100.0,state['stamina']+duration_s*1.2)
        ticks=self._advance_clock(state,duration_s)
        npc=self.country.npc(entity_ref); old_block=npc['block_id']; old_city=npc.get('city_id'); strec,b=self._block_for_geodetic(geo['longitude'],geo['latitude'])
        location_changed=False
        if b and b['id']!=old_block:
            npc['state_id']=strec['id']; npc['block_id']=b['id']; npc['city_id']=None; location_changed=True
        if b and not npc.get('scene_id'):
            gx,gy=self.spatial._local_xy(geo['longitude'],geo['latitude']); nearest=None
            for city in b.get('cities',[]):
                cc=city.get('coordinate_center')
                if not cc: continue
                cx,cy=self.spatial._local_xy(cc['longitude'],cc['latitude']); dist=math.hypot(gx-cx,gy-cy)
                if dist<=self.CITY_RUNTIME_RADIUS_M and (nearest is None or dist<nearest[0]): nearest=(dist,city['id'])
            npc['city_id']=nearest[1] if nearest else None
            if npc.get('city_id')!=old_city: location_changed=True
        if location_changed: self.country.reconcile_country_inventory()
        ch=self.spatial.chunk_for_geodetic(geo['longitude'],geo['latitude'])['chunk_id']; oldch=self.streaming.owners.get(entity_ref); transfer=None
        if oldch!=ch:
            transfer=self.streaming.transfer(entity_ref,ch); self.streaming.prune_loaded_chunks(set(self.spatial.chunk_neighbors(ch,1)))
        self._save(entity_ref,state)
        return {'status':'PASS','entity_ref':entity_ref,'moved_m':round(maxdist,6),'mode':mode,'stamina':round(state['stamina'],4),
                'iso_x_m':round(nx,6),'iso_y_m':round(ny,6),'geodetic':geo,'chunk_id':ch,'chunk_changed':oldch!=ch,
                'block_changed':old_block!=npc['block_id'],'travel_ticks_advanced':ticks,'ownership':transfer,'authority':self.AUTHORITY}

    def apply_external_stamina_cost(self,entity_ref:str,cost:float,*,reason:str='STAGE16A_TRAVERSAL'):
        try: amount=float(cost)
        except Exception: return {'status':'REJECTED','reason':'INVALID_STAMINA_COST'}
        if not math.isfinite(amount) or amount<0: return {'status':'REJECTED','reason':'INVALID_STAMINA_COST'}
        st=self.state(entity_ref); before=float(st['stamina'])
        state={k:st[k] for k in ('iso_x_m','iso_y_m','altitude_m','stamina','mode','heading_deg','elapsed_s')}
        state['stamina']=max(0.0,before-amount); self._save(entity_ref,state)
        return {'status':'PASS','entity_ref':entity_ref,'stamina_before':round(before,6),'stamina_after':round(state['stamina'],6),
                'stamina_cost_applied':round(min(before,amount),6),'requested_cost':round(amount,6),'exhausted':state['stamina']<=1e-9,
                'reason':str(reason),'authority':self.AUTHORITY}

    def sync_to_geodetic(self,entity_ref:str,coordinate:dict,*,reason:str='SYSTEM_SPATIAL_SYNC'):
        st=self.state(entity_ref);iso=self.spatial.geodetic_to_isometric(coordinate['longitude'],coordinate['latitude'],coordinate.get('altitude_m',st['altitude_m']))
        state={k:st[k] for k in ('iso_x_m','iso_y_m','altitude_m','stamina','mode','heading_deg','elapsed_s')}
        state.update({'iso_x_m':iso['iso_x_m'],'iso_y_m':iso['iso_y_m'],'altitude_m':float(coordinate.get('altitude_m',st['altitude_m']))})
        self._save(entity_ref,state)
        return {'status':'PASS','entity_ref':entity_ref,'reason':reason,'iso_x_m':state['iso_x_m'],'iso_y_m':state['iso_y_m'],'authority':self.AUTHORITY}

    def move_toward_geodetic(self,entity_ref,lon,lat,*,duration_s=.25,mode='WALK',environment_factor=None):
        st=self.state(entity_ref); t=self.spatial.geodetic_to_isometric(lon,lat,st['altitude_m'])
        return self.step_vector(entity_ref,t['iso_x_m']-st['iso_x_m'],t['iso_y_m']-st['iso_y_m'],duration_s=duration_s,mode=mode,environment_factor=environment_factor)
    def verify(self):
        failures=[]
        for n in self.country._all_npc_records():
            try: s=self.state(n['id'])
            except Exception as e: failures.append('MOTION_STATE:'+n['id']+':'+str(e)); continue
            if not 0<=s['stamina']<=100: failures.append('STAMINA_RANGE:'+n['id'])
            geo=self.spatial.isometric_to_geodetic(s['iso_x_m'],s['iso_y_m'],s['altitude_m']); ch=self.spatial.chunk_for_geodetic(geo['longitude'],geo['latitude'])['chunk_id']
            if self.streaming.owners.get(n['id'])!=ch: failures.append('MOTION_OWNER_DIVERGENCE:'+n['id'])
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'states':sum(1 for _ in self.country._all_npc_records())}
