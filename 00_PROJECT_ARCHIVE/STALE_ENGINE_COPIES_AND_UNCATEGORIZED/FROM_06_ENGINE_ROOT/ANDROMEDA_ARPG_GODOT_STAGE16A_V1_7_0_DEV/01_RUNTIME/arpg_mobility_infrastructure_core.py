from __future__ import annotations
import copy, hashlib, json, math, zipfile
from typing import Any
from living_runtime import ValidationError, IntegrityError, ConflictError, NotFoundError, canonical_json, sha256_text

class ARPGMobilityInfrastructureCore:
    """Stage10 mobility/infrastructure authority for the one-country ARPG pilot.

    Canonical transport identities, routes and bridge anchors are snapshotted read-only
    from Master V2.0.1. Vehicle numeric profiles, local connector roads, propulsion
    budgets and wear are explicit gameplay-derived policies and can be rebalanced.
    """
    VERSION='V1.1.0'
    AUTHORITY='ANDROMEDA_ARPG_STAGE10_MOBILITY_INFRASTRUCTURE'
    GAMEPLAY_AUTHORITY='GAMEPLAY_DERIVED_STAGE10_REBALANCEABLE'
    COUNTRY_REF='TER-011'
    CANON_AUTOMOTIVE_REF='SYS-AUT-001'
    CANON_LOCAL_ROAD_REF='SRTE-001'
    CANON_BRIDGE_REF='POI-046'
    BOUNDARY_ROUTES=('RTE-001','RTE-003','RTE-013')
    VEHICLE_PROFILES={
        'VEH-PROFILE-SERVICE-LIGHT':{'name':'Veículo leve de serviço','vehicle_class':'ROAD_SERVICE','speed_kmh':42.0,'cargo_kg':180.0,'passengers':4,'propulsion_max':100.0,'propulsion_per_km':0.08,'integrity_max':100.0,'offroad':False},
        'VEH-PROFILE-UTILITY-CARGO':{'name':'Veículo utilitário de carga','vehicle_class':'ROAD_CARGO','speed_kmh':32.0,'cargo_kg':900.0,'passengers':2,'propulsion_max':140.0,'propulsion_per_km':0.07,'integrity_max':130.0,'offroad':False},
        'VEH-PROFILE-SCOUT':{'name':'Veículo de reconhecimento','vehicle_class':'SCOUT','speed_kmh':38.0,'cargo_kg':250.0,'passengers':3,'propulsion_max':110.0,'propulsion_per_km':0.08,'integrity_max':110.0,'offroad':True},
    }

    def __init__(self, engine: Any, world_instance_id: str) -> None:
        self.engine=engine; self.runtime=engine.runtime; self.world_instance_id=str(world_instance_id)
        self.country=engine.country(world_instance_id); self.world=engine.world_arpg(world_instance_id); self.items=engine.items_arpg(world_instance_id)
        self._init_schema(); self._canon=self._load_canon(); self._bootstrap_profiles(); self._bootstrap_segments(); self._bootstrap_bridge(); self._bootstrap_existing_players()

    @staticmethod
    def _payload(obj):
        t=canonical_json(obj); return t,sha256_text(t)
    def _world_seed(self): return int(getattr(self.country,'seed',0) or 0)
    def _stable_ref(self,prefix,*parts):
        raw='|'.join(str(x) for x in (self._world_seed(),)+parts); return prefix+hashlib.sha256(raw.encode()).hexdigest()[:18].upper()

    def _init_schema(self):
        with self.runtime._write_lock:
            self.runtime.conn.executescript('''
            CREATE TABLE IF NOT EXISTS arpg_mobility_canon_snapshots(
              canonical_ref TEXT PRIMARY KEY, source_path TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS arpg_transport_segments(
              world_instance_id TEXT NOT NULL, segment_ref TEXT NOT NULL, source_ref TEXT, segment_kind TEXT NOT NULL,
              origin_ref TEXT NOT NULL, destination_ref TEXT NOT NULL, distance_km REAL NOT NULL,
              payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, PRIMARY KEY(world_instance_id,segment_ref));
            CREATE TABLE IF NOT EXISTS arpg_bridge_states(
              world_instance_id TEXT NOT NULL, bridge_ref TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
              PRIMARY KEY(world_instance_id,bridge_ref));
            CREATE TABLE IF NOT EXISTS arpg_vehicle_profiles(
              profile_ref TEXT PRIMARY KEY, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS arpg_vehicle_instances(
              world_instance_id TEXT NOT NULL, vehicle_ref TEXT NOT NULL, owner_ref TEXT NOT NULL, profile_ref TEXT NOT NULL,
              payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, PRIMARY KEY(world_instance_id,vehicle_ref));
            CREATE TABLE IF NOT EXISTS arpg_mobility_events(
              world_instance_id TEXT NOT NULL, event_ref TEXT NOT NULL, event_type TEXT NOT NULL, payload_hash TEXT NOT NULL,
              result_json TEXT NOT NULL, result_hash TEXT NOT NULL, PRIMARY KEY(world_instance_id,event_ref));
            ''')

    def _load_canon(self):
        p=self.runtime.master_release_path
        if not p: raise IntegrityError('Master release required for Stage10')
        entity_path='ANDROMEDA_CODEX_MASTER/01_CANON/ANDROMEDA_CODEX_CANON_MASTER_V2_0_0.json'
        route_path='ANDROMEDA_CODEX_MASTER/03_DOMAINS/GEOSPATIAL/02_GEOGRAFIA/STELLAR_ROUTE_SKELETON_V1_0.json'
        route_idx_path='ANDROMEDA_CODEX_MASTER/02_ATLAS/STAGE_08_REFERENCE/01_DATA/ATLAS_ROUTE_INDEX_V1_0.json'
        with zipfile.ZipFile(p) as z:
            master=json.loads(z.read(entity_path)); skeleton=json.loads(z.read(route_path)); routeidx=json.loads(z.read(route_idx_path))
        ents={e.get('id'):e for e in master.get('entities',[]) if isinstance(e,dict) and e.get('id')}
        routes={r.get('id'):r for r in skeleton.get('routes',[]) if isinstance(r,dict) and r.get('id')}
        sroutes={r.get('id'):r for r in routeidx.get('routes',[]) if isinstance(r,dict) and r.get('id')}
        needed={self.CANON_AUTOMOTIVE_REF:ents.get(self.CANON_AUTOMOTIVE_REF),self.CANON_BRIDGE_REF:ents.get(self.CANON_BRIDGE_REF),self.CANON_LOCAL_ROAD_REF:ents.get(self.CANON_LOCAL_ROAD_REF)}
        for r in self.BOUNDARY_ROUTES: needed[r]=routes.get(r)
        for ref,obj in needed.items():
            if not obj: raise IntegrityError('Stage10 missing canonical source:'+ref)
            src=route_path if ref in self.BOUNDARY_ROUTES else entity_path
            if ref==self.CANON_LOCAL_ROAD_REF and ref in sroutes: obj=copy.deepcopy(sroutes[ref]); src=route_idx_path
            t,h=self._payload(obj); row=self.runtime.conn.execute('SELECT payload_hash FROM arpg_mobility_canon_snapshots WHERE canonical_ref=?',(ref,)).fetchone()
            if row and row['payload_hash']!=h: raise IntegrityError('Stage10 canonical snapshot drift:'+ref)
            if not row:
                with self.runtime._write_lock:self.runtime.conn.execute('INSERT INTO arpg_mobility_canon_snapshots VALUES(?,?,?,?)',(ref,src,t,h))
            needed[ref]=obj
        return needed

    def canonical_snapshot(self,ref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_mobility_canon_snapshots WHERE canonical_ref=?',(ref,)).fetchone()
        if not row: raise NotFoundError('mobility canonical snapshot not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('mobility snapshot hash mismatch')
        return json.loads(row['payload_json'])

    def _bootstrap_profiles(self):
        for ref,b in self.VEHICLE_PROFILES.items():
            p={'profile_ref':ref,**copy.deepcopy(b),'canonical_identity':False,'canonical_support_ref':self.CANON_AUTOMOTIVE_REF,
               'propulsion_type':'ABSTRACT_PROPULSION_RESOURCE_STAGE10','authority':self.GAMEPLAY_AUTHORITY,'art_dependency':'NONE_PLACEHOLDER_READY'}
            t,h=self._payload(p)
            with self.runtime._write_lock:self.runtime.conn.execute('INSERT OR REPLACE INTO arpg_vehicle_profiles VALUES(?,?,?)',(ref,t,h))

    def vehicle_profile(self,ref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_vehicle_profiles WHERE profile_ref=?',(ref,)).fetchone()
        if not row: raise NotFoundError('vehicle profile not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('vehicle profile hash mismatch')
        return json.loads(row['payload_json'])
    def list_vehicle_profiles(self): return [self.vehicle_profile(r['profile_ref']) for r in self.runtime.conn.execute('SELECT profile_ref FROM arpg_vehicle_profiles ORDER BY profile_ref')]

    def _zone_center(self,z):
        b=z['bounding_region']; return ((float(b[0])+float(b[2]))/2,(float(b[1])+float(b[3]))/2)
    @staticmethod
    def _dist(a,b):
        # local geodesic approximation, sufficient only for derived connector costing
        lon1,lat1=a; lon2,lat2=b; y=(lat2-lat1)*111.32; x=(lon2-lon1)*111.32*math.cos(math.radians((lat1+lat2)/2)); return math.hypot(x,y)
    def _save_segment(self,s):
        t,h=self._payload(s)
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT OR REPLACE INTO arpg_transport_segments VALUES(?,?,?,?,?,?,?,?,?)',(self.world_instance_id,s['segment_ref'],s.get('source_ref'),s['segment_kind'],s['origin_ref'],s['destination_ref'],float(s['distance_km']),t,h))

    def _bootstrap_segments(self):
        # Canonical local Varga road.
        r=self._canon[self.CANON_LOCAL_ROAD_REF]
        rz={'segment_ref':self.CANON_LOCAL_ROAD_REF,'source_ref':self.CANON_LOCAL_ROAD_REF,'segment_kind':'CANONICAL_LOCAL_ROAD',
            'origin_ref':r['origin_id'],'destination_ref':r['destination_id'],'distance_km':float(r['distance_km']),
            'transport_modes':list(r.get('transport_modes') or []),'risk':r.get('risk'),'boundary_locked':False,
            'terrain':list(r.get('terrain') or []),'authority':'MASTER_V2_0_1_READ_ONLY','country_ref':self.COUNTRY_REF}
        self._save_segment(rz)
        # Boundary corridors are indexed but never traversable in the one-country pilot.
        for ref in self.BOUNDARY_ROUTES:
            x=self._canon[ref]; self._save_segment({'segment_ref':ref,'source_ref':ref,'segment_kind':'CANONICAL_BOUNDARY_GATE',
              'origin_ref':x['origin_id'],'destination_ref':x['destination_id'],'distance_km':float(x['distance_km']),
              'transport_modes':list(x.get('transport_modes') or []),'speed_bands_kmh':copy.deepcopy(x.get('speed_bands_kmh') or {}),
              'risk':x.get('risk'),'terrain':list(x.get('terrain') or []),'boundary_locked':True,'lock_reason':'ONE_COUNTRY_SCOPE_OTHER_COUNTRY_DEFERRED',
              'authority':'MASTER_V2_0_1_READ_ONLY','country_ref':self.COUNTRY_REF})
        # Gameplay-derived local connectors join Stage08 zones only; they are not canonical roads.
        zones=self.world.list_zones(); centers={z['zone_ref']:self._zone_center(z) for z in zones}
        zs=sorted(centers)
        edges=set()
        for a in zs:
            others=sorted((self._dist(centers[a],centers[b]),b) for b in zs if b!=a)[:2]
            for d,b in others:
                key=tuple(sorted((a,b)))
                if key in edges: continue
                edges.add(key); ref=self._stable_ref('DRV-ROAD-',key[0],key[1])
                za=self.world.zone(a); zb=self.world.zone(b); root=bool(za.get('anomaly_overlay') or zb.get('anomaly_overlay'))
                self._save_segment({'segment_ref':ref,'source_ref':None,'segment_kind':'DERIVED_LOCAL_CONNECTOR','origin_ref':a,'destination_ref':b,
                  'distance_km':round(max(0.1,d),3),'transport_modes':['a pé','veículo compatível'],'risk':'ALTO' if root else 'BAIXO',
                  'terrain':['country_runtime_connector'],'boundary_locked':False,'root_overlay':root,
                  'authority':self.GAMEPLAY_AUTHORITY,'canonical_claim':False,'country_ref':self.COUNTRY_REF})

    def list_segments(self):
        rows=self.runtime.conn.execute('SELECT segment_ref,payload_json,payload_hash FROM arpg_transport_segments WHERE world_instance_id=? ORDER BY segment_ref',(self.world_instance_id,)).fetchall(); out=[]
        for r in rows:
            if sha256_text(r['payload_json'])!=r['payload_hash']: raise IntegrityError('transport segment hash mismatch')
            out.append(json.loads(r['payload_json']))
        return out
    def segment(self,ref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_transport_segments WHERE world_instance_id=? AND segment_ref=?',(self.world_instance_id,ref)).fetchone()
        if not row: raise NotFoundError('transport segment not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('transport segment hash mismatch')
        return json.loads(row['payload_json'])

    def _bootstrap_bridge(self):
        canon=self._canon[self.CANON_BRIDGE_REF]
        # Canonical identity + gameplay runtime condition. Exact road attachment is proximity-derived, not promoted to canon.
        b={'bridge_ref':self.CANON_BRIDGE_REF,'canonical_ref':self.CANON_BRIDGE_REF,'name':canon.get('name'),'country_ref':self.COUNTRY_REF,
           'integrity':100.0,'integrity_max':100.0,'capacity_factor':1.0,'operational':True,
           'route_attachment':'VARGA_LOCAL_NETWORK','attachment_authority':'GAMEPLAY_DERIVED_PROXIMITY_NOT_CANON',
           'canonical_authority':'MASTER_V2_0_1_READ_ONLY','runtime_authority':self.GAMEPLAY_AUTHORITY}
        self._save_bridge(b)
        # Existing Country Scale bridges remain runtime-derived structures, exposed to the same condition API.
        for s in self.country.world['country']['states']:
            for block in s['blocks']:
                for br in block.get('bridges',[]):
                    x={'bridge_ref':br['id'],'canonical_ref':None,'name':br.get('name'),'country_ref':self.COUNTRY_REF,'block_ref':block['id'],
                       'integrity':round(100.0*float(br.get('durability',1))/max(1,float(br.get('durability_max',1))),6),'integrity_max':100.0,
                       'capacity_factor':1.0,'operational':str(br.get('status','ACTIVE')).upper()=='ACTIVE','source_durability':br.get('durability'),
                       'source_durability_max':br.get('durability_max'),'canonical_authority':None,'runtime_authority':'COUNTRY_RUNTIME_DERIVED_STAGE10'}
                    self._save_bridge(x)
    def _save_bridge(self,b):
        t,h=self._payload(b)
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT OR REPLACE INTO arpg_bridge_states VALUES(?,?,?,?)',(self.world_instance_id,b['bridge_ref'],t,h))
    def bridge(self,ref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_bridge_states WHERE world_instance_id=? AND bridge_ref=?',(self.world_instance_id,ref)).fetchone()
        if not row: raise NotFoundError('bridge not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('bridge hash mismatch')
        return json.loads(row['payload_json'])
    def list_bridges(self): return [self.bridge(r['bridge_ref']) for r in self.runtime.conn.execute('SELECT bridge_ref FROM arpg_bridge_states WHERE world_instance_id=? ORDER BY bridge_ref',(self.world_instance_id,))]
    def set_bridge_condition(self,ref,integrity,*,authority='STAGE10_TEST_RUNTIME'):
        b=self.bridge(ref); val=max(0.0,min(100.0,float(integrity))); b['integrity']=round(val,6); b['operational']=val>10.0; b['capacity_factor']=round(max(0.0,min(1.0,val/50.0)),6); b['last_condition_authority']=authority; self._save_bridge(b); return b

    def _bootstrap_existing_players(self):
        for p in self.engine.arpg(self.world_instance_id).list_profiles(): pass

    def _event_existing(self,event_ref,event_type,payload):
        row=self.runtime.conn.execute('SELECT event_type,payload_hash,result_json,result_hash FROM arpg_mobility_events WHERE world_instance_id=? AND event_ref=?',(self.world_instance_id,event_ref)).fetchone()
        if not row:return None
        _,ph=self._payload(payload)
        if row['event_type']!=event_type or row['payload_hash']!=ph: raise ConflictError('mobility event_ref conflict')
        if sha256_text(row['result_json'])!=row['result_hash']: raise IntegrityError('mobility event result hash mismatch')
        out=json.loads(row['result_json']); out['idempotent_replay']=True; return out
    def _record(self,event_ref,event_type,payload,result):
        pt,ph=self._payload(payload); rt,rh=self._payload(result)
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT INTO arpg_mobility_events VALUES(?,?,?,?,?,?)',(self.world_instance_id,event_ref,event_type,ph,rt,rh))
        return result

    def _country_npc_zone(self,npc_ref):
        for st in self.country.world['country']['states']:
            for b in st['blocks']:
                for c in b.get('cities',[]):
                    for n in c.get('npcs',[]):
                        if n.get('id')==npc_ref:
                            z=next((x for x in self.world.list_zones() if x.get('block_ref')==b.get('id')),None)
                            return z.get('zone_ref') if z else None
        return None

    def _actor_exists(self,actor_ref):
        try:
            self.engine.arpg(self.world_instance_id).profile(actor_ref); return 'PLAYER_PROFILE'
        except Exception: pass
        try:
            self.country.npc(actor_ref); return 'COUNTRY_NPC'
        except Exception: pass
        raise ValidationError('unknown mobility actor_ref')

    def create_vehicle(self,owner_ref,profile_ref,*,event_ref):
        payload={'owner_ref':owner_ref,'profile_ref':profile_ref}; old=self._event_existing(event_ref,'CREATE_VEHICLE',payload)
        if old:return old
        p=self.vehicle_profile(profile_ref)
        # Player or Country NPC must exist; ItemCore already provides this validation contract.
        self.items.ensure_inventory(owner_ref)
        ref=self._stable_ref('VEH-',event_ref,owner_ref,profile_ref)
        zone=None
        try: zone=self.world.ensure_profile(owner_ref).get('zone_ref')
        except Exception: zone=self._country_npc_zone(owner_ref)
        v={'vehicle_ref':ref,'owner_ref':owner_ref,'profile_ref':profile_ref,'zone_ref':zone,'integrity':p['integrity_max'],'propulsion':p['propulsion_max'],
           'passenger_refs':[],'driver_ref':None,'odometer_km':0.0,'status':'PARKED','authority':self.GAMEPLAY_AUTHORITY}
        self._save_vehicle(v)
        # Vehicle cargo uses Stage05 universal inventory; owner recognition is Stage10 extension.
        self.items.ensure_inventory(ref,slot_capacity=96,weight_capacity=min(float(p['cargo_kg']),float(self.items.MAX_WEIGHT_CAPACITY)))
        return self._record(event_ref,'CREATE_VEHICLE',payload,{'status':'PASS','vehicle':copy.deepcopy(v)})
    def _save_vehicle(self,v):
        t,h=self._payload(v)
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT OR REPLACE INTO arpg_vehicle_instances VALUES(?,?,?,?,?,?)',(self.world_instance_id,v['vehicle_ref'],v['owner_ref'],v['profile_ref'],t,h))
    def vehicle(self,ref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_vehicle_instances WHERE world_instance_id=? AND vehicle_ref=?',(self.world_instance_id,ref)).fetchone()
        if not row: raise NotFoundError('vehicle not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('vehicle hash mismatch')
        return json.loads(row['payload_json'])
    def list_vehicles(self): return [self.vehicle(r['vehicle_ref']) for r in self.runtime.conn.execute('SELECT vehicle_ref FROM arpg_vehicle_instances WHERE world_instance_id=? ORDER BY vehicle_ref',(self.world_instance_id,))]

    def board(self,profile_ref,vehicle_ref,*,event_ref,as_driver=False):
        payload={'profile_ref':profile_ref,'vehicle_ref':vehicle_ref,'as_driver':bool(as_driver)}; old=self._event_existing(event_ref,'BOARD',payload)
        if old:return old
        self._actor_exists(profile_ref); v=self.vehicle(vehicle_ref); p=self.vehicle_profile(v['profile_ref'])
        refs=list(v.get('passenger_refs') or [])
        if profile_ref not in refs:
            if len(refs)>=int(p['passengers']): return self._record(event_ref,'BOARD',payload,{'status':'REJECTED','reason':'PASSENGER_CAPACITY'})
            refs.append(profile_ref)
        v['passenger_refs']=refs
        if as_driver:
            if v.get('driver_ref') not in (None,profile_ref): return self._record(event_ref,'BOARD',payload,{'status':'REJECTED','reason':'DRIVER_OCCUPIED'})
            v['driver_ref']=profile_ref
        self._save_vehicle(v); return self._record(event_ref,'BOARD',payload,{'status':'PASS','vehicle':v})

    def load_cargo(self,source_owner_ref,vehicle_ref,item_ref,quantity,*,event_ref):
        payload={'source_owner_ref':source_owner_ref,'vehicle_ref':vehicle_ref,'item_ref':item_ref,'quantity':int(quantity)}; old=self._event_existing(event_ref,'LOAD_CARGO',payload)
        if old:return old
        self.vehicle(vehicle_ref)
        res=self.items.transfer_item(source_owner_ref,vehicle_ref,item_ref,int(quantity),event_ref='mobility:'+event_ref)
        out={'status':res.get('status','PASS'),'transfer':res,'cargo':self.items.inventory_snapshot(vehicle_ref)}
        return self._record(event_ref,'LOAD_CARGO',payload,out)
    def unload_cargo(self,vehicle_ref,dest_owner_ref,item_ref,quantity,*,event_ref):
        payload={'vehicle_ref':vehicle_ref,'dest_owner_ref':dest_owner_ref,'item_ref':item_ref,'quantity':int(quantity)}; old=self._event_existing(event_ref,'UNLOAD_CARGO',payload)
        if old:return old
        self.vehicle(vehicle_ref); res=self.items.transfer_item(vehicle_ref,dest_owner_ref,item_ref,int(quantity),event_ref='mobility:'+event_ref)
        return self._record(event_ref,'UNLOAD_CARGO',payload,{'status':res.get('status','PASS'),'transfer':res})

    def _segment_zone_pair(self,s):
        if s['segment_kind']=='DERIVED_LOCAL_CONNECTOR': return s['origin_ref'],s['destination_ref']
        # Map canonical local road endpoints to Stage08 zones from exact entity geometry when possible.
        zones=self.world.list_zones(); master=self._canon
        if s['segment_ref']==self.CANON_LOCAL_ROAD_REF:
            r=self.canonical_snapshot(self.CANON_LOCAL_ROAD_REF); oc=r.get('origin_coordinate') or {}; dc=r.get('destination_coordinate') or {}
            a=self.world._location_zone(float(oc.get('longitude',-3.62125)),float(oc.get('latitude',11.995)),zones)
            b=self.world._location_zone(float(dc.get('longitude',-3.67)),float(dc.get('latitude',12.03)),zones)
            return a,b
        return None,None

    def travel(self,profile_ref,vehicle_ref,segment_ref,*,event_ref):
        payload={'profile_ref':profile_ref,'vehicle_ref':vehicle_ref,'segment_ref':segment_ref}; old=self._event_existing(event_ref,'TRAVEL',payload)
        if old:return old
        s=self.segment(segment_ref); v=self.vehicle(vehicle_ref); p=self.vehicle_profile(v['profile_ref'])
        if s.get('boundary_locked'): return self._record(event_ref,'TRAVEL',payload,{'status':'REJECTED','reason':'BOUNDARY_ROUTE_LOCKED','segment_ref':segment_ref})
        if v.get('driver_ref')!=profile_ref: return self._record(event_ref,'TRAVEL',payload,{'status':'REJECTED','reason':'DRIVER_REQUIRED'})
        if float(v.get('integrity',0))<=10: return self._record(event_ref,'TRAVEL',payload,{'status':'REJECTED','reason':'VEHICLE_INOPERABLE'})
        a,b=self._segment_zone_pair(s)
        current=v.get('zone_ref')
        # First trip may start from player's current world zone.
        try: player_zone=self.world.ensure_profile(profile_ref).get('zone_ref')
        except Exception: player_zone=None
        if current is None: current=player_zone
        if a and b:
            if current==a: dest=b
            elif current==b: dest=a
            elif s['segment_kind']=='CANONICAL_LOCAL_ROAD' and player_zone in (a,b): current=player_zone; dest=b if player_zone==a else a
            else: return self._record(event_ref,'TRAVEL',payload,{'status':'REJECTED','reason':'VEHICLE_NOT_AT_SEGMENT_ENDPOINT','current_zone':current,'endpoints':[a,b]})
        else: return self._record(event_ref,'TRAVEL',payload,{'status':'REJECTED','reason':'SEGMENT_NOT_ZONE_RESOLVED'})
        dist=float(s['distance_km']); cost=dist*float(p['propulsion_per_km'])
        if float(v['propulsion'])+1e-9<cost: return self._record(event_ref,'TRAVEL',payload,{'status':'REJECTED','reason':'INSUFFICIENT_PROPULSION','required':round(cost,6)})
        root=bool(s.get('root_overlay')); terrain_factor=(0.82 if p.get('offroad') else 0.68) if root else 1.0
        bridge_factor=1.0
        if s['segment_ref']==self.CANON_LOCAL_ROAD_REF:
            br=self.bridge(self.CANON_BRIDGE_REF)
            if not br.get('operational',True):
                return self._record(event_ref,'TRAVEL',payload,{'status':'REJECTED','reason':'BRIDGE_INOPERABLE','bridge_ref':self.CANON_BRIDGE_REF})
            bridge_factor=max(0.25,float(br.get('capacity_factor',1.0)))
        speed=float(p['speed_kmh'])*terrain_factor*bridge_factor; hours=dist/max(1.0,speed); wear=dist*(0.025 if root else 0.008)
        v['zone_ref']=dest; v['propulsion']=round(max(0,float(v['propulsion'])-cost),6); v['integrity']=round(max(0,float(v['integrity'])-wear),6); v['odometer_km']=round(float(v.get('odometer_km',0))+dist,6); v['status']='PARKED'
        self._save_vehicle(v)
        # Move all Stage01 player passengers in the vehicle to the same zone.
        for pref in list(v.get('passenger_refs') or []):
            try:
                st=self.world.ensure_profile(pref); st['zone_ref']=dest; st['instance_context']={'kind':'OVERWORLD','ref':dest}; self.world._save_profile(st)
            except Exception: pass
        out={'status':'PASS','vehicle_ref':vehicle_ref,'segment_ref':segment_ref,'origin_zone':current,'destination_zone':dest,'distance_km':dist,
             'travel_hours':round(hours,6),'speed_kmh_effective':round(speed,6),'propulsion_used':round(cost,6),'integrity_loss':round(wear,6),'vehicle':copy.deepcopy(v)}
        return self._record(event_ref,'TRAVEL',payload,out)

    def refuel(self,vehicle_ref,amount,*,event_ref,authority='GAMEPLAY_STAGE10_TEST'):
        payload={'vehicle_ref':vehicle_ref,'amount':float(amount),'authority':authority}; old=self._event_existing(event_ref,'REFUEL',payload)
        if old:return old
        v=self.vehicle(vehicle_ref); p=self.vehicle_profile(v['profile_ref']); v['propulsion']=round(min(float(p['propulsion_max']),float(v['propulsion'])+max(0,float(amount))),6); self._save_vehicle(v)
        return self._record(event_ref,'REFUEL',payload,{'status':'PASS','vehicle':v,'propulsion_type':'ABSTRACT_PROPULSION_RESOURCE_STAGE10'})

    def verify(self):
        failures=[]; segs=self.list_segments(); bridges=self.list_bridges(); profs=self.list_vehicle_profiles()
        if self.canonical_snapshot(self.CANON_AUTOMOTIVE_REF).get('territory_refs')!=[self.COUNTRY_REF]: failures.append('AUTOMOTIVE_CANON_SCOPE')
        if not any(s['segment_ref']==self.CANON_LOCAL_ROAD_REF and not s['boundary_locked'] for s in segs): failures.append('LOCAL_ROAD')
        for r in self.BOUNDARY_ROUTES:
            try:
                if not self.segment(r).get('boundary_locked'): failures.append('BOUNDARY_UNLOCKED:'+r)
            except Exception: failures.append('BOUNDARY_MISSING:'+r)
        if not any(b['bridge_ref']==self.CANON_BRIDGE_REF for b in bridges): failures.append('CANON_BRIDGE')
        if len(profs)!=3: failures.append('VEHICLE_PROFILES')
        for v in self.list_vehicles():
            t,_=self._payload(v)
            if not math.isfinite(float(v.get('integrity',-1))) or not math.isfinite(float(v.get('propulsion',-1))): failures.append('VEHICLE_NUMERIC:'+v['vehicle_ref'])
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'segments':len(segs),'derived_local_connectors':sum(s['segment_kind']=='DERIVED_LOCAL_CONNECTOR' for s in segs),
                'boundary_routes':sum(s.get('boundary_locked',False) for s in segs),'bridges':len(bridges),'canonical_bridge':self.CANON_BRIDGE_REF,
                'vehicle_profiles':len(profs),'vehicles':len(self.list_vehicles()),'authority':self.AUTHORITY,'art_dependency':'NONE_PLACEHOLDER_READY'}
