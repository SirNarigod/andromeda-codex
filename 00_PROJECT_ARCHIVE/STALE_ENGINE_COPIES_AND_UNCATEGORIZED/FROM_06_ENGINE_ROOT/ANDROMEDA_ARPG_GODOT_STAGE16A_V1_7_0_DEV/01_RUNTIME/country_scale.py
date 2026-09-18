from __future__ import annotations

import copy, hashlib, json, math, random, zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from content_catalog import (
    RESOURCE_CATALOG, RESOURCE_NAMES, FLORA_NAMES, FAUNA_NAMES,
    state_name, city_name, npc_name, shop_name, block_name, subregion_name,
    realm_name, legendary_name, name_status,
)

COUNTRY_TERRITORY_PATH='ANDROMEDA_CODEX_MASTER/03_DOMAINS/GEOSPATIAL/02_GEOGRAFIA/STELLAR_TERRITORIES_V1_0.json'
BIOME_PATH='ANDROMEDA_CODEX_MASTER/03_DOMAINS/GEOSPATIAL/02_GEOGRAFIA/STELLAR_BIOME_MODEL_V1_0.json'
FAUNA_PATH='ANDROMEDA_CODEX_MASTER/03_DOMAINS/SPATIALIZATION/02_DISTRIBUICOES/STELLAR_FAUNA_DISTRIBUTION_V1_0.json'
FLORA_PATH='ANDROMEDA_CODEX_MASTER/03_DOMAINS/SPATIALIZATION/02_DISTRIBUICOES/STELLAR_FLORA_DISTRIBUTION_V1_0.json'

TIERS=('BAIXO','MÉDIO','ALTO')
STATE_ARCHETYPES=(
    ('TECHNOLOGY','Tecnologia'),('ROBOTICS','Robótica'),('MILITARY','Exército'),
    ('MAGIC','Magia'),('NATURE','Natureza'),
)
NPC_CLASSES=('MAGE','NATIVE','ROBOT','WARRIOR','MERCENARY','WORKER','CHILD')
SHOP_KINDS=('GENERAL','WEAPONS','MAGIC','TECH','ROBOTICS','MATERIALS','FOOD')
FLORA_POOL=('FLR-GRAIN','FLR-PASTURE','FLR-HARDWOOD','FLR-MEDICINAL','FLR-RUNIC_MOSS','FLR-FROST_REED','FLR-DESERT_SHRUB')
FAUNA_POOL=(
    ('FAU-GRAZER','HERBIVORE'),('FAU-BROWSER','HERBIVORE'),('FAU-SCAVENGER','OMNIVORE'),
    ('FAU-PREDATOR-L','PREDATOR'),('FAU-PREDATOR-M','PREDATOR'),('FAU-PREDATOR-H','PREDATOR'),
    ('FAU-INSECT-POLL','INSECT'),('FAU-INSECT-HIVE','INSECT'),
)


def _hash_seed(*parts: Any) -> int:
    raw='|'.join(str(p) for p in parts).encode('utf-8')
    return int(hashlib.sha256(raw).hexdigest()[:16],16)

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo,min(hi,v))

def _tier(v: float) -> str:
    return 'BAIXO' if v < 0.34 else ('MÉDIO' if v < 0.67 else 'ALTO')

def _haversine_km(a: tuple[float,float], b: tuple[float,float]) -> float:
    lon1,lat1=map(math.radians,a); lon2,lat2=map(math.radians,b)
    dlon=lon2-lon1; dlat=lat2-lat1
    h=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2*6178.1*math.asin(min(1.0,math.sqrt(h)))

@dataclass(frozen=True)
class ProtectionPolicy:
    protected: bool
    combat_targetable: bool
    hazardous_labor_allowed: bool
    exploitation_allowed: bool=False

class CountryScaleSystem:
    """Deterministic country-scale world model for the Living runtime.

    Canon input is read-only. Generated subdivisions, quantities and numeric balances are
    runtime/authorized-expansion data until consolidated into a future Master release.
    """
    VERSION='V1.4.0'
    AUTHORITY='USER_AUTHORIZED_COUNTRY_SCALE_RUNTIME_DERIVED_FROM_MASTER_V2_0_1'

    def __init__(self, *, master_release_path: str|Path, country_territory_id: str='TER-011', seed: int=1201) -> None:
        self.master_release_path=str(master_release_path)
        self.country_territory_id=country_territory_id
        self.seed=int(seed)
        self.country_source=self._load_country()
        self.world: dict[str,Any]={}
        self.runtime=None
        self.world_instance_id=None
        self.domain_bridge=None
        self._build()

    def attach_domain_bridge(self, bridge:Any) -> dict[str,Any]:
        self.domain_bridge=bridge
        return {'status':'PASS','authority':'LIVING_DOMAIN_BRIDGE_V1_3','parallel_purchase_path':'DISABLED_WHEN_BRIDGE_ATTACHED','parallel_hunt_path':'DISABLED_WHEN_BRIDGE_ATTACHED'}

    def attach_runtime(self, runtime:Any, world_instance_id:str) -> dict[str,Any]:
        self.runtime=runtime; self.world_instance_id=world_instance_id
        with runtime._write_lock:
            runtime.conn.executescript("""
            CREATE TABLE IF NOT EXISTS country_scale_state(
              world_instance_id TEXT PRIMARY KEY REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
              payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS country_scale_events(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
              event_type TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL
            );
            """)
        row=runtime.conn.execute('SELECT payload_json,payload_hash FROM country_scale_state WHERE world_instance_id=?',(world_instance_id,)).fetchone()
        if row:
            raw=row['payload_json']; h=hashlib.sha256(raw.encode('utf-8')).hexdigest()
            if h!=row['payload_hash']: raise ValueError('country scale snapshot hash mismatch')
            self.world=json.loads(raw); status='LOADED'
        else:
            self._persist_state(); self._record_event('COUNTRY_SCALE_BOOTSTRAPPED',{'seed':self.seed,'country_territory_id':self.country_territory_id},persist_first=False); status='CREATED'
        return {'status':'PASS','persistence':status,'world_instance_id':world_instance_id}

    def _persist_state(self)->None:
        if not self.runtime or not self.world_instance_id:return
        raw=json.dumps(self.world,ensure_ascii=False,sort_keys=True,separators=(',',':')); h=hashlib.sha256(raw.encode('utf-8')).hexdigest()
        with self.runtime._write_lock:
            self.runtime.conn.execute('INSERT OR REPLACE INTO country_scale_state(world_instance_id,payload_json,payload_hash) VALUES(?,?,?)',(self.world_instance_id,raw,h))

    def _record_event(self,event_type:str,payload:dict[str,Any],*,persist_first:bool=True)->None:
        if persist_first:self._persist_state()
        if not self.runtime or not self.world_instance_id:return
        body={'event_type':event_type,'payload':payload,'authority':'COUNTRY_SCALE_RUNTIME'}
        raw=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')); h=hashlib.sha256(raw.encode('utf-8')).hexdigest()
        with self.runtime._write_lock:
            self.runtime.conn.execute('INSERT INTO country_scale_events(world_instance_id,event_type,payload_json,payload_hash) VALUES(?,?,?,?)',(self.world_instance_id,event_type,raw,h))

    def persistence_integrity(self)->dict[str,Any]:
        if not self.runtime or not self.world_instance_id:return {'status':'SKIPPED','reason':'NOT_ATTACHED'}
        failures=[]
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM country_scale_state WHERE world_instance_id=?',(self.world_instance_id,)).fetchone()
        if not row:failures.append('STATE_MISSING')
        elif hashlib.sha256(row['payload_json'].encode('utf-8')).hexdigest()!=row['payload_hash']:failures.append('STATE_HASH')
        for r in self.runtime.conn.execute('SELECT sequence,payload_json,payload_hash FROM country_scale_events WHERE world_instance_id=?',(self.world_instance_id,)).fetchall():
            if hashlib.sha256(r['payload_json'].encode('utf-8')).hexdigest()!=r['payload_hash']:failures.append('EVENT_HASH:'+str(r['sequence']))
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'events':self.runtime.conn.execute('SELECT COUNT(*) c FROM country_scale_events WHERE world_instance_id=?',(self.world_instance_id,)).fetchone()['c']}

    def _load_country(self) -> dict[str,Any]:
        with zipfile.ZipFile(self.master_release_path) as z:
            data=json.loads(z.read(COUNTRY_TERRITORY_PATH).decode('utf-8'))
        for t in data.get('territories',[]):
            if t.get('id')==self.country_territory_id:
                return copy.deepcopy(t)
        raise KeyError(f'country territory not found: {self.country_territory_id}')

    def _rng(self,*parts:Any) -> random.Random:
        return random.Random(_hash_seed(self.seed,*parts))

    def _build(self) -> None:
        src=self.country_source
        bbox=list(map(float,src['bounding_region']))
        min_lon,min_lat,max_lon,max_lat=bbox
        width=max_lon-min_lon
        state_w=width/len(STATE_ARCHETYPES)
        states=[]
        for idx,(arch,label) in enumerate(STATE_ARCHETYPES,1):
            slon0=min_lon+(idx-1)*state_w; slon1=min_lon+idx*state_w
            sbbox=[round(slon0,6),min_lat,round(slon1,6),max_lat]
            state=self._make_state(idx,arch,label,sbbox)
            states.append(state)
        # Required feature guarantee: procedural chance may not erase an entire mandatory domain.
        # If no Root Deep block emerges naturally, convert the highest-magic block in the MAGIC state.
        if not any(b['root_deep'] for st in states for b in st['blocks']):
            magic_state=next(st for st in states if st['archetype']=='MAGIC')
            candidates=[b for b in magic_state['blocks'] if not b['root_deep']] or magic_state['blocks']
            target=max(candidates, key=lambda b:b['climate']['magic_intensity'])
            self._convert_to_root_deep(target)
        self._install_magic_realms(states)
        self.world={
            'schema_version':'1.4.0',
            'country':{
                'id':'CTR-PILOT-001','name':src['name'],'source_territory_id':src['id'],
                'scope_status':'DERIVED_COUNTRY_SCALE_FOR_SYSTEM_TESTING',
                'kenua_story_binding':'NOT_ASSIGNED_BY_MASTER',
                'area_km2_approx':src.get('area_km2_approx'),'bounding_region':bbox,
                'coordinate_center':copy.deepcopy(src.get('coordinate_center')),
                'states':states,'status':'ACTIVE','inventory_class':'COUNTRY',
            },
            'authority':self.AUTHORITY,
            'seed':self.seed,
        }
        self.reconcile_country_inventory()


    def _install_magic_realms(self,states:list[dict[str,Any]])->None:
        created=0
        for st in states:
            candidates=[b for b in st['blocks'] if not b['root_deep']]
            if not candidates: continue
            magic=float(st['stats']['magic']); rng=self._rng('realms',st['id'])
            count=1 if st['archetype']=='MAGIC' else (1 if rng.random()<magic*0.45 else 0)
            if st['archetype']=='MAGIC' and magic>0.72 and rng.random()<0.45: count=2
            for i in range(count):
                block=sorted(candidates,key=lambda b:b['climate']['magic_intensity'],reverse=True)[i%len(candidates)]
                realm=self._make_magic_realm(st,block,i+1); block['kingdoms'].append(realm); created+=1
        if created==0:
            candidates=[(st,b) for st in states for b in st['blocks'] if not b['root_deep']]
            st,b=max(candidates,key=lambda sb:sb[1]['climate']['magic_intensity']); b['kingdoms'].append(self._make_magic_realm(st,b,1))

    def _make_magic_realm(self,st:dict[str,Any],block:dict[str,Any],index:int)->dict[str,Any]:
        rng=self._rng('realm',st['id'],block['id'],index); mi=float(block['climate']['magic_intensity'])
        mage_score=_clamp(mi*0.72+rng.random()*0.28,0,1); mage_class=_tier(mage_score)
        n=1+rng.randint(0,2); creatures=[]
        for i in range(n):
            size=rng.randint(30,100); damage=rng.randint(25,95); resist=rng.randint(30,100); magic=rng.randint(55,100)
            threat=round(size*.15+damage*.30+resist*.25+magic*.30,2)
            leg_id=f"LEG-{st['id']}-{index:02d}-{i+1:02d}"
            creatures.append({'id':leg_id,'name':legendary_name(leg_id),'name_status':name_status(),'class':_tier(threat/100),'status':'ACTIVE','stats':{'size':size,'damage':damage,'resistance':resist,'magic':magic,'threat_score':threat},'safety':'FICTIONAL_GAMEPLAY_STATS'})
        realm_id=f"KDM-{st['id']}-{index:02d}"
        return {'id':realm_id,'name':realm_name(realm_id),'name_status':name_status(),'status':'ACTIVE','tier':mage_class,'mage_class':mage_class,'block_id':block['id'],'legendary_creatures':creatures,'inventory':{'ITEM-MANA-CRYSTAL':rng.randint(80,500),'ITEM-RUNE-DUST':rng.randint(100,700),'LEGENDARY_CREATURES':len(creatures)}}

    def _convert_to_root_deep(self, block:dict[str,Any]) -> None:
        sid=int(block['state_id'].split('-')[1]); bid=int(block['id'].split('-')[-1])
        block['root_deep']=True
        block['name']=block_name('MAGIC',block['id'],True)
        block['name_status']=name_status()
        block['biome']={'id':'BIO-ROOT-DEEP','name':'Bioma da Raiz Profunda','class':'ROOT_DEEP','status':'ACTIVE','predator_only':True,'tier':'ALTO'}
        block['industries']=[]
        block['cities']=[]
        block['kingdoms']=[]
        block['flora']=[]
        block['fauna']=self._fauna(sid,bid,block['biome'],0.2,True)
        for r in block['resources']:
            if r['kind'] in ('MAGIC_MINERAL','RARE_MINERAL','CORRUPTED_MINERAL'):
                r['density']=round(_clamp(float(r['density'])+0.18,0,1),4)
                r['tier']=_tier(r['density'])
                r['capacity_units']=max(r['capacity_units'],int(500+9500*r['density']))
                r['remaining_units']=r['capacity_units']
        if not any(r['id']=='MIN-ROOT-SHARD' for r in block['resources']):
            name,kind=next((name,kind) for rid,name,kind in RESOURCE_CATALOG if rid=='MIN-ROOT-SHARD')
            density=_clamp(0.59+float(block['climate']['magic_intensity'])*0.28,0.59,0.96)
            capacity=int(500+9500*density)
            block['resources'].append({'id':'MIN-ROOT-SHARD','name':name,'kind':kind,'tier':_tier(density),'density':round(density,4),'capacity_units':capacity,'remaining_units':capacity,'status':'AVAILABLE'})

    def _make_state(self, idx:int, arch:str, label:str, bbox:list[float]) -> dict[str,Any]:
        rng=self._rng('state',idx,arch)
        lon0,lat0,lon1,lat1=bbox
        center=[round((lon0+lon1)/2,6),round((lat0+lat1)/2,6)]
        altitude=max(20,round(200+rng.random()*1800))
        magic=_clamp(0.15+rng.random()*0.45+(0.35 if arch=='MAGIC' else 0)+(0.10 if arch=='NATURE' else 0),0,1)
        wealth=_clamp(0.25+rng.random()*0.55+(0.15 if arch in ('TECHNOLOGY','ROBOTICS') else 0),0,1)
        security=_clamp(0.30+rng.random()*0.45+(0.20 if arch=='MILITARY' else 0),0,1)
        tech=_clamp(0.20+rng.random()*0.45+(0.30 if arch in ('TECHNOLOGY','ROBOTICS') else 0),0,1)
        nature=_clamp(0.25+rng.random()*0.55+(0.20 if arch=='NATURE' else 0),0,1)
        blocks_n=rng.randint(1,5)
        blocks=[]
        bh=(lat1-lat0)/blocks_n
        for b in range(1,blocks_n+1):
            bb=[lon0,lat0+(b-1)*bh,lon1,lat0+b*bh]
            blk=self._make_block(idx,b,arch,bb,magic,wealth,tech,nature,security)
            blk['region_id']=f'REGION-{idx:02d}-{b:02d}'
            blk['subregion_count']=self._rng('subregion-count',idx,b).randint(1,3)
            blk['subregions']=[]
            blocks.append(blk)
        return {
            'id':f'STA-{idx:02d}','name':state_name(arch),'name_status':name_status(),
            'archetype':arch,'tier':_tier((wealth+tech+magic+nature+security)/5),'bounding_region':[round(x,6) for x in bbox],
            'coordinate_center':{'longitude':center[0],'latitude':center[1],'altitude_m':altitude,'crs_id':'ACRS-STELLAR-GEODETIC-V1'},
            'status':'ACTIVE','stats':{'technology':round(tech,4),'magic':round(magic,4),'nature':round(nature,4),'wealth':round(wealth,4),'security':round(security,4)},
            'blocks':blocks,'block_count':len(blocks),'inventory':{},
        }

    def _make_block(self, sidx:int, bidx:int, arch:str, bbox:list[float], magic:float, wealth:float, tech:float, nature:float, security:float) -> dict[str,Any]:
        rng=self._rng('block',sidx,bidx,arch)
        lon0,lat0,lon1,lat1=map(float,bbox)
        lon=(lon0+lon1)/2; lat=(lat0+lat1)/2
        altitude=max(0,round(80+rng.random()*2200))
        temperature=round(30-abs(lat)*0.38-altitude*0.0065+rng.uniform(-4,4),2)
        rainfall=round(_clamp(350+nature*1700+rng.uniform(-300,800),50,3600),2)
        humidity=round(_clamp(20+rainfall/45+rng.uniform(-10,12),10,98),2)
        magic_i=round(_clamp(magic+rng.uniform(-0.15,0.15),0,1),4)
        richness=round(_clamp((wealth+tech)*0.35+nature*0.15+rng.random()*0.3,0,1),4)
        root_chance=0.05+0.16*magic_i+0.08*(1-nature)
        root=rng.random()<root_chance
        biome=self._biome(temperature,rainfall,humidity,magic_i,root)
        resources=self._resources(sidx,bidx,arch,richness,magic_i,root)
        industries=self._industries(sidx,bidx,resources,tech,wealth,root)
        cities=self._cities(sidx,bidx,arch,wealth,tech,magic_i,resources,root)
        flora=self._flora(sidx,bidx,biome,nature,root)
        fauna=self._fauna(sidx,bidx,biome,nature,root)
        bridges=self._bridges(sidx,bidx,richness,tech,security)
        block_id=f'STA-{sidx:02d}-BLK-{bidx:02d}'
        return {
            'id':block_id,'name':block_name(arch,block_id,root),'name_status':name_status(),'state_id':f'STA-{sidx:02d}','status':'ACTIVE',
            'bounding_region':[round(x,6) for x in bbox],
            'coordinate_center':{'longitude':round(lon,6),'latitude':round(lat,6),'altitude_m':altitude,'crs_id':'ACRS-STELLAR-GEODETIC-V1'},
            'climate':{'temperature_c':temperature,'rainfall_mm_y':rainfall,'humidity_pct':humidity,'magic_intensity':magic_i,'resource_richness':richness},
            'biome':biome,'resources':resources,'industries':industries,'cities':cities,'flora':flora,'fauna':fauna,'bridges':bridges,'kingdoms':[],
            'root_deep':root,'inventory':{},
        }

    def _biome(self,temp:float,rain:float,hum:float,magic:float,root:bool)->dict[str,Any]:
        if root: return {'id':'BIO-ROOT-DEEP','name':'Bioma da Raiz Profunda','class':'ROOT_DEEP','status':'ACTIVE','predator_only':True,'tier':'ALTO'}
        if temp<-5: cls='GLACIAL'
        elif temp<5: cls='TUNDRA'
        elif rain<350: cls='ARID'
        elif temp>24 and hum>65: cls='TROPICAL_FOREST'
        elif rain>1800: cls='WET_FOREST'
        elif hum>70: cls='WETLAND'
        elif rain<750: cls='GRASSLAND'
        else: cls='TEMPERATE_FOREST'
        if magic>0.78: cls='MAGIC_SATURATED_'+cls
        return {'id':'BIO-DYN-'+cls,'name':cls.replace('_',' ').title(),'class':cls,'status':'ACTIVE','predator_only':False,'tier':_tier((magic+min(1,rain/2500))/2)}

    def _resources(self,sidx,bidx,arch,richness,magic,root):
        rng=self._rng('resources',sidx,bidx)
        out=[]
        for rid,name,kind in RESOURCE_CATALOG:
            if kind=='CORRUPTED_MINERAL' and not root:
                continue
            base_presence={
                'METAL':0.48,'STONE':0.52,'PRECIOUS_METAL':0.18,'MAGIC_MINERAL':0.12,
                'RARE_MINERAL':0.10,'TECH_MINERAL':0.13,'CORRUPTED_MINERAL':0.78,
            }.get(kind,0.20)
            presence=base_presence+richness*0.22
            if kind=='MAGIC_MINERAL': presence+=magic*0.50
            if kind=='TECH_MINERAL' and arch in ('TECHNOLOGY','ROBOTICS'): presence+=0.42
            if kind=='PRECIOUS_METAL': presence+=richness*0.20
            if kind=='RARE_MINERAL': presence+=richness*0.28
            if root and kind in ('MAGIC_MINERAL','RARE_MINERAL','CORRUPTED_MINERAL'): presence+=0.22
            if rng.random()>_clamp(presence,0.05,0.98):
                continue
            affinity=0.0
            if kind=='MAGIC_MINERAL': affinity+=magic*0.45
            if arch in ('TECHNOLOGY','ROBOTICS') and kind in ('METAL','RARE_MINERAL','TECH_MINERAL'): affinity+=0.18
            if arch=='MILITARY' and kind in ('METAL','STONE','PRECIOUS_METAL'): affinity+=0.12
            if root and kind in ('MAGIC_MINERAL','RARE_MINERAL','CORRUPTED_MINERAL'): affinity+=0.25
            density=_clamp(richness*0.55+rng.random()*0.35+affinity,0.05,1)
            capacity=int(500+9500*density)
            out.append({'id':rid,'name':name,'kind':kind,'tier':_tier(density),'density':round(density,4),'capacity_units':capacity,'remaining_units':capacity,'status':'AVAILABLE'})
        # Resource distribution is sparse, but a block must remain economically legible.
        by_id={r['id'] for r in out}
        mandatory=['MIN-IRON','MIN-STONE']
        if arch in ('TECHNOLOGY','ROBOTICS'): mandatory.append('MIN-MAGNETITE')
        if arch=='MAGIC': mandatory.append('MIN-CRYSTAL')
        if root: mandatory.append('MIN-ROOT-SHARD')
        catalog={rid:(name,kind) for rid,name,kind in RESOURCE_CATALOG}
        for rid in mandatory:
            if rid in by_id: continue
            name,kind=catalog[rid]; density=_clamp(0.24+richness*.35+(magic*.25 if kind=='MAGIC_MINERAL' else 0)+(0.35 if kind=='CORRUPTED_MINERAL' else 0),.08,1)
            capacity=int(500+9500*density)
            out.append({'id':rid,'name':name,'kind':kind,'tier':_tier(density),'density':round(density,4),'capacity_units':capacity,'remaining_units':capacity,'status':'AVAILABLE'})
        return out

    def _industries(self,sidx,bidx,resources,tech,wealth,root):
        if root: return []
        out=[]
        for i,r in enumerate(resources,1):
            if r['tier'] in ('MÉDIO','ALTO') and r['kind'] in ('METAL','MAGIC_MINERAL','RARE_MINERAL','STONE','PRECIOUS_METAL','TECH_MINERAL','CORRUPTED_MINERAL'):
                scale=_tier(_clamp((tech+wealth+r['density'])/3,0,1)); ind_id=f'IND-{sidx:02d}-{bidx:02d}-{i:02d}'
                out.append({'id':ind_id,'name':f"Complexo de Extração {r['name']} {i}",'name_status':name_status(),'focus':'MINING','resource_id':r['id'],'tier':scale,'status':'OPERATING','stock_units':0,'safety':round(_clamp(0.55+tech*0.25,0,1),4)})
        return out

    def _cities(self,sidx,bidx,arch,wealth,tech,magic,resources,root):
        if root: return []
        rng=self._rng('cities',sidx,bidx)
        n=max(1,min(4,1+int(wealth*2.4)+(1 if rng.random()<wealth else 0)))
        cities=[]
        shop_bias={'TECHNOLOGY':'TECH','ROBOTICS':'ROBOTICS','MILITARY':'WEAPONS','MAGIC':'MAGIC','NATURE':'FOOD'}[arch]
        for c in range(1,n+1):
            shops_n=max(1,min(8,1+int(wealth*5)+rng.randint(0,2)))
            shops=[]
            for sh in range(1,shops_n+1):
                kind=shop_bias if sh==1 else rng.choice(SHOP_KINDS)
                sh_id=f'SHP-{sidx:02d}-{bidx:02d}-{c:02d}-{sh:02d}'
                shops.append({'id':sh_id,'name':shop_name(kind,sh_id),'name_status':name_status(),'kind':kind,'tier':_tier(_clamp(wealth+rng.uniform(-.2,.2),0,1)),'status':'OPEN','state_id':f'STA-{sidx:02d}','block_id':f'STA-{sidx:02d}-BLK-{bidx:02d}','city_id':f'CITY-{sidx:02d}-{bidx:02d}-{c:02d}','inventory':self._shop_inventory(kind,rng),'wallet':{'currency':'CREDIT_RUNTIME','balance':round(1200+rng.random()*3800,2)},'price_policy':'COUNTRY_DYNAMIC_RUNTIME_V1_2_1_NOT_CANON'})
            npcs=self._npcs(sidx,bidx,c,arch,tech,magic,wealth,rng)
            city_id=f'CITY-{sidx:02d}-{bidx:02d}-{c:02d}'
            cities.append({'id':city_id,'name':city_name(arch,city_id),'name_status':name_status(),'status':'ACTIVE','tier':_tier(wealth),'shops':shops,'npcs':npcs,'inventory':{},'scene_objects':[]})
        return cities

    def _shop_inventory(self,kind,rng):
        pool={
            'GENERAL':['ITEM-FOOD','ITEM-WATER','ITEM-TOOL'], 'WEAPONS':['WPN-001','WPN-002','WPN-003'],
            'MAGIC':['ITEM-RUNE-DUST','ITEM-MANA-CRYSTAL','WPN-004'], 'TECH':['ITEM-CIRCUIT','ITEM-SENSOR','ITEM-TOOL'],
            'ROBOTICS':['ITEM-SERVO','ITEM-ACTUATOR','ITEM-CIRCUIT'], 'MATERIALS':['MIN-IRON','MIN-COPPER','MIN-STONE','MIN-TIN','MIN-QUARTZ','MIN-MAGNETITE'],
            'FOOD':['ITEM-GRAIN','ITEM-FRUIT','ITEM-WATER'],
        }[kind]
        return {x:rng.randint(5,80) for x in pool}

    def _npcs(self,sidx,bidx,cidx,arch,tech,magic,wealth,rng):
        out=[]
        preferred={'TECHNOLOGY':['WORKER','ROBOT'],'ROBOTICS':['ROBOT','WORKER'],'MILITARY':['WARRIOR','MERCENARY'],'MAGIC':['MAGE','NATIVE'],'NATURE':['NATIVE','WORKER']}[arch]
        classes=list(NPC_CLASSES)+preferred*2
        n=12+rng.randint(0,16)
        for nidx in range(1,n+1):
            cls=rng.choice(classes)
            age= rng.randint(6,17) if cls=='CHILD' else rng.randint(18,75)
            protection=self._protection(cls,age)
            tier=_tier(rng.random()*(0.55+wealth*0.45))
            inv=self._npc_inventory(cls,tier,rng)
            npc_id=f'NPC-{sidx:02d}-{bidx:02d}-{cidx:02d}-{nidx:03d}'
            mult={'BAIXO':1.0,'MÉDIO':1.65,'ALTO':2.4}[tier]
            out.append({'id':npc_id,'name':npc_name(cls,npc_id),'name_status':name_status(),'class':cls,'tier':tier,'age':age,'status':'ACTIVE','state_id':f'STA-{sidx:02d}','block_id':f'STA-{sidx:02d}-BLK-{bidx:02d}','city_id':f'CITY-{sidx:02d}-{bidx:02d}-{cidx:02d}','scene_id':None,'protection':protection.__dict__,'inventory':inv,'item_instances':[],'knowledge_tags':[],'active_light':None,'wallet':{'currency':'CREDIT_RUNTIME','balance':round((180+rng.random()*520)*mult,2)},'health':100,'reputation':0})
        # guarantee requested classes in every state through first city/block over generation reconciliation
        return out

    def _protection(self,cls,age):
        if cls=='CHILD' or age<18: return ProtectionPolicy(True,False,False,False)
        if cls=='WORKER': return ProtectionPolicy(True,True,False,False)
        return ProtectionPolicy(False,True,True,False)

    def _npc_inventory(self,cls,tier,rng):
        base={'MAGE':['ITEM-MANA-CRYSTAL','ITEM-RUNE-DUST'],'NATIVE':['ITEM-FOOD','ITEM-HERB'],
              'ROBOT':['ITEM-SERVO','ITEM-ENERGY-CELL'],'WARRIOR':['WPN-001','ITEM-ARMOR'],
              'MERCENARY':['WPN-003','ITEM-ARMOR'],'WORKER':['ITEM-TOOL','ITEM-FOOD'],'CHILD':['ITEM-FOOD','ITEM-PERSONAL']}[cls]
        mult={'BAIXO':1,'MÉDIO':2,'ALTO':3}[tier]
        return {x:rng.randint(1,3)*mult for x in base}

    def _base_biome_class(self,biome:dict[str,Any])->str:
        cls=str(biome.get('class','TEMPERATE_FOREST'))
        return cls.replace('MAGIC_SATURATED_','')

    def _flora_pool_for_biome(self,biome:dict[str,Any])->tuple[str,...]:
        cls=self._base_biome_class(biome)
        if cls in ('GLACIAL','TUNDRA'): return ('FLR-FROST_REED','FLR-RUNIC_MOSS','FLR-MEDICINAL')
        if cls=='ARID': return ('FLR-DESERT_SHRUB','FLR-MEDICINAL','FLR-RUNIC_MOSS')
        if cls in ('TROPICAL_FOREST','WET_FOREST','WETLAND'): return ('FLR-HARDWOOD','FLR-MEDICINAL','FLR-RUNIC_MOSS','FLR-GRAIN')
        if cls=='GRASSLAND': return ('FLR-GRAIN','FLR-PASTURE','FLR-MEDICINAL','FLR-RUNIC_MOSS')
        return ('FLR-HARDWOOD','FLR-MEDICINAL','FLR-RUNIC_MOSS','FLR-PASTURE')

    def _fauna_pool_for_biome(self,biome:dict[str,Any])->tuple[tuple[str,str],...]:
        cls=self._base_biome_class(biome)
        if cls in ('GLACIAL','TUNDRA'): return (('FAU-GRAZER','HERBIVORE'),('FAU-PREDATOR-M','PREDATOR'),('FAU-PREDATOR-H','PREDATOR'),('FAU-SCAVENGER','OMNIVORE'))
        if cls=='ARID': return (('FAU-SCAVENGER','OMNIVORE'),('FAU-PREDATOR-L','PREDATOR'),('FAU-PREDATOR-M','PREDATOR'),('FAU-INSECT-HIVE','INSECT'))
        if cls in ('TROPICAL_FOREST','WET_FOREST','WETLAND'): return (('FAU-BROWSER','HERBIVORE'),('FAU-GRAZER','HERBIVORE'),('FAU-PREDATOR-M','PREDATOR'),('FAU-INSECT-POLL','INSECT'),('FAU-INSECT-HIVE','INSECT'))
        if cls=='GRASSLAND': return (('FAU-GRAZER','HERBIVORE'),('FAU-SCAVENGER','OMNIVORE'),('FAU-PREDATOR-L','PREDATOR'),('FAU-PREDATOR-M','PREDATOR'),('FAU-INSECT-POLL','INSECT'))
        return (('FAU-BROWSER','HERBIVORE'),('FAU-GRAZER','HERBIVORE'),('FAU-PREDATOR-M','PREDATOR'),('FAU-PREDATOR-H','PREDATOR'),('FAU-INSECT-POLL','INSECT'))

    def _flora(self,sidx,bidx,biome,nature,root):
        if root: return []
        rng=self._rng('flora',sidx,bidx)
        n=3+rng.randint(0,4)
        pool=self._flora_pool_for_biome(biome)
        picks=rng.sample(pool,k=min(n,len(pool)))
        out=[]
        for i,p in enumerate(picks,1):
            abundance=_clamp(0.2+nature*0.55+rng.uniform(-.15,.2),.05,1)
            cap=int(200+4800*abundance)
            out.append({'id':f'{p}-{sidx:02d}-{bidx:02d}-{i:02d}','name':FLORA_NAMES.get(p,p),'name_status':name_status(),'species_ref':p,'tier':_tier(abundance),'abundance':round(abundance,4),'capacity_units':cap,'remaining_units':cap,'status':'THRIVING' if abundance>.67 else ('STABLE' if abundance>.34 else 'SCARCE'),'adapted_biome_class':self._base_biome_class(biome)})
        return out

    def _fauna(self,sidx,bidx,biome,nature,root):
        rng=self._rng('fauna',sidx,bidx)
        pool=[x for x in FAUNA_POOL if x[1]=='PREDATOR'] if root else list(self._fauna_pool_for_biome(biome))
        n=3+rng.randint(0,4)
        out=[]
        for i in range(n):
            ref,role=rng.choice(pool)
            if root: role='PREDATOR'
            abundance=_clamp(0.15+nature*0.45+rng.random()*0.35,0.05,1)
            climate_factor=1.0
            basecls=self._base_biome_class(biome)
            if role=='INSECT' and basecls in ('GLACIAL','TUNDRA'): climate_factor=0.20
            elif role=='PREDATOR': climate_factor=0.55
            count=max(2,int((8+abundance*160)*climate_factor))
            rec={'id':f'{ref}-{sidx:02d}-{bidx:02d}-{i+1:02d}','name':FAUNA_NAMES.get(ref,ref),'name_status':name_status(),'species_ref':ref,'role':role,'tier':_tier(abundance),'count':count,'status':'ACTIVE','adapted_biome_class':basecls}
            if role=='PREDATOR': rec['combat_profile']=self._predator_profile(sidx,bidx,i,root)
            out.append(rec)
        if root and not out:
            out=[{'id':f'FAU-ROOT-PRED-{sidx:02d}-{bidx:02d}-01','name':FAUNA_NAMES['FAU-ROOT-PREDATOR'],'name_status':name_status(),'species_ref':'FAU-ROOT-PREDATOR','role':'PREDATOR','tier':'ALTO','count':12,'status':'ACTIVE','combat_profile':self._predator_profile(sidx,bidx,1,True)}]
        return out

    def _predator_profile(self,sidx,bidx,i,root):
        rng=self._rng('pred',sidx,bidx,i)
        size=rng.randint(20,95); damage=rng.randint(20,90); resistance=rng.randint(20,90); venom=rng.randint(0,85)
        corruption=rng.randint(55,100) if root else rng.randint(0,25)
        score=round(size*.18+damage*.30+resistance*.24+venom*.12+corruption*.16,2)
        return {'size':size,'damage':damage,'resistance':resistance,'venom':venom,'corruption':corruption,'threat_score':score,'class':_tier(score/100),'units':'GAMEPLAY_NORMALIZED_0_100'}

    def _bridges(self,sidx,bidx,richness,tech,security):
        rng=self._rng('bridge',sidx,bidx)
        n=1 if rng.random()<(0.35+richness*.35) else 0
        out=[]
        for i in range(n):
            dura=int(7000+3000*_clamp((tech+security)/2,0,1))
            br_id=f'BRG-{sidx:02d}-{bidx:02d}-{i+1:02d}'
            out.append({'id':br_id,'name':f'Ponte de Alta Carga {1+i} — {sidx}.{bidx}','name_status':name_status(),'tier':'ALTO','resource_class':'ALTO','durability_max':dura,'durability':dura,'status':'ACTIVE','inventory':{'MIN-STONE':500,'MIN-IRON':300},'repairable':True})
        return out

    def _industries_inventory(self, block):
        return {i['resource_id']:i.get('stock_units',0) for i in block['industries']}

    def _empty_inventory(self):
        return {'resources':{},'flora':{},'fauna':{},'industries':0,'cities':0,'shops':0,'npcs':{},'bridges':0,'shop_items':{},'npc_items':{},'industry_stock':{},'bridge_resources':{},'kingdoms':0,'legendary_creatures':0,'mage_classes':{},'dungeons':0,'scene_objects':{},'scene_items':{},'dungeon_weapons':{},'npc_currency':0.0,'shop_currency':0.0}

    def _split_units(self,total:int,n:int,*parts:Any)->list[int]:
        if n<=1:return [int(total)]
        rng=self._rng('split',*parts); weights=[0.4+rng.random() for _ in range(n)]; sw=sum(weights)
        raw=[int(total*w/sw) for w in weights]; raw[0]+=int(total)-sum(raw); return raw

    def _reconcile_subregions(self,b:dict[str,Any],npcs_in_block:list[dict[str,Any]]|None=None)->None:
        n=int(b.get('subregion_count') or 1); lon0,lat0,lon1,lat1=map(float,b['bounding_region']); sh=(lat1-lat0)/n
        subs=[]
        for i in range(n):
            sub_id=f"{b['region_id']}-SUB-{i+1:02d}"
            inv=self._empty_inventory(); sbbox=[round(lon0,6),round(lat0+i*sh,6),round(lon1,6),round(lat0+(i+1)*sh,6)]; subs.append({'id':sub_id,'name':subregion_name(b.get('name',b['id']),sub_id),'name_status':name_status(),'region_id':b['region_id'],'status':'ACTIVE','bounding_region':sbbox,'coordinate_center':{'longitude':round((sbbox[0]+sbbox[2])/2,8),'latitude':round((sbbox[1]+sbbox[3])/2,8),'altitude_m':float(b.get('coordinate_center',{}).get('altitude_m',0)),'crs_id':'ACRS-STELLAR-GEODETIC-V1','precision_class':'DERIVED_CENTER'},'biome':copy.deepcopy(b['biome']),'climate':copy.deepcopy(b['climate']),'inventory':inv})
        for r in b['resources']:
            vals=self._split_units(r['remaining_units'],n,b['id'],r['id'],'resource')
            for i,v in enumerate(vals): subs[i]['inventory']['resources'][r['id']]=v
        for f in b['flora']:
            vals=self._split_units(f['remaining_units'],n,b['id'],f['id'],'flora')
            for i,v in enumerate(vals): subs[i]['inventory']['flora'][f['species_ref']]=subs[i]['inventory']['flora'].get(f['species_ref'],0)+v
        for a in b['fauna']:
            vals=self._split_units(a['count'],n,b['id'],a['id'],'fauna')
            for i,v in enumerate(vals): subs[i]['inventory']['fauna'][a['species_ref']]=subs[i]['inventory']['fauna'].get(a['species_ref'],0)+v
        def slot(ref): return _hash_seed(self.seed,b['id'],ref)%n
        def spatial_slot(entity, ref=None):
            cc=(entity or {}).get('coordinate_center') if isinstance(entity,dict) else None
            if cc:
                lon=float(cc.get('longitude')); lat=float(cc.get('latitude'))
                for idx,sr in enumerate(subs):
                    x0,y0,x1,y1=map(float,sr['bounding_region'])
                    if x0-1e-9<=lon<=x1+1e-9 and y0-1e-9<=lat<=y1+1e-9:
                        return idx
            return slot(ref or (entity or {}).get('id','fallback'))

        def npc_slot(npc):
            scene=npc.get('scene_id')
            if scene:
                d=next((x for x in b.get('dungeons',[]) if x['id']==scene),None)
                if d is not None:return spatial_slot(d,d['id'])
            city_id=npc.get('city_id')
            if city_id:
                city=next((x for x in b.get('cities',[]) if x['id']==city_id),None)
                if city is not None:return spatial_slot(city,city['id'])
            return spatial_slot({'coordinate_center':b.get('coordinate_center')},npc['id'])

        for ind in b['industries']:
            inv=subs[slot(ind['id'])]['inventory']; inv['industries']+=1; inv['industry_stock'][ind['resource_id']]=inv['industry_stock'].get(ind['resource_id'],0)+int(ind.get('stock_units',0))
        for br in b['bridges']:
            inv=subs[slot(br['id'])]['inventory']; inv['bridges']+=1
            for k,v in br.get('inventory',{}).items(): inv['bridge_resources'][k]=inv['bridge_resources'].get(k,0)+int(v)
        for realm in b.get('kingdoms',[]):
            inv=subs[slot(realm['id'])]['inventory']; inv['kingdoms']+=1; inv['legendary_creatures']+=len(realm.get('legendary_creatures',[])); mc=realm.get('mage_class','MÉDIO'); inv['mage_classes'][mc]=inv['mage_classes'].get(mc,0)+1
        for city in b['cities']:
            inv=subs[spatial_slot(city,city['id'])]['inventory']; inv['cities']+=1; inv['shops']+=len(city['shops'])
            for sh in city['shops']:
                for k,v in sh['inventory'].items(): inv['shop_items'][k]=inv['shop_items'].get(k,0)+int(v)
                inv['shop_currency']+=float((sh.get('wallet') or {}).get('balance',0.0))
            for obj in city.get('scene_objects',[]): self._accumulate_scene_object(inv,obj)
        # NPCs are stored under their origin city for stable identity, but inventory locality
        # follows their current block/city fields after travel.
        for npc in (npcs_in_block if npcs_in_block is not None else self._all_npc_records()):
            if npc.get('block_id')!=b['id']: continue
            ref=npc.get('city_id') or npc['id']; inv=subs[npc_slot(npc)]['inventory']
            inv['npcs'][npc['class']]=inv['npcs'].get(npc['class'],0)+1
            for k,v in npc['inventory'].items(): inv['npc_items'][k]=inv['npc_items'].get(k,0)+int(v)
            inv['npc_currency']+=float((npc.get('wallet') or {}).get('balance',0.0))
        for d in b.get('dungeons',[]):
            inv=subs[spatial_slot(d,d['id'])]['inventory']; inv['dungeons']+=1
            for obj in d.get('objects',[]): self._accumulate_scene_object(inv,obj)
            self._accumulate_dungeon_graph(inv,d)
        for obj in b.get('scene_objects',[]): self._accumulate_scene_object(subs[spatial_slot(obj,obj['id'])]['inventory'],obj)
        b['subregions']=subs

    def reconcile_country_inventory(self):
        country=self.world.get('country')
        if not country: return
        # Stage01 performance correction: materialize locality indexes once. The previous
        # implementation repeatedly rescanned every NPC for every city and block, creating
        # quadratic work during player-profile creation and other local updates.
        all_npcs=list(self._all_npc_records())
        npcs_by_block={}
        npcs_by_city_block={}
        for npc in all_npcs:
            bid=npc.get('block_id'); cid=npc.get('city_id')
            npcs_by_block.setdefault(bid,[]).append(npc)
            if cid is not None:
                npcs_by_city_block.setdefault((bid,cid),[]).append(npc)
        aggregate=self._empty_inventory()
        for st in country['states']:
            sinv=self._empty_inventory()
            for b in st['blocks']:
                binv=self._empty_inventory(); binv['industries']=len(b['industries']); binv['cities']=len(b['cities']); binv['bridges']=len(b['bridges'])
                for r in b['resources']: binv['resources'][r['id']]=binv['resources'].get(r['id'],0)+r['remaining_units']
                for f in b['flora']: binv['flora'][f['species_ref']]=binv['flora'].get(f['species_ref'],0)+f['remaining_units']
                for a in b['fauna']: binv['fauna'][a['species_ref']]=binv['fauna'].get(a['species_ref'],0)+a['count']
                for ind in b['industries']: binv['industry_stock'][ind['resource_id']]=binv['industry_stock'].get(ind['resource_id'],0)+int(ind.get('stock_units',0))
                for br in b['bridges']:
                    for k,v in br.get('inventory',{}).items(): binv['bridge_resources'][k]=binv['bridge_resources'].get(k,0)+int(v)
                for realm in b.get('kingdoms',[]):
                    binv['kingdoms']+=1; binv['legendary_creatures']+=len(realm.get('legendary_creatures',[])); mc=realm.get('mage_class','MÉDIO'); binv['mage_classes'][mc]=binv['mage_classes'].get(mc,0)+1
                for city in b['cities']:
                    current_npcs=npcs_by_city_block.get((b['id'],city['id']),[])
                    city['inventory']={'shops':len(city['shops']),'npcs':len(current_npcs),'shop_stock_units':sum(sum(sh['inventory'].values()) for sh in city['shops']),'npc_item_units':sum(sum(n['inventory'].values()) for n in current_npcs),'shop_currency':round(sum(float((sh.get('wallet') or {}).get('balance',0)) for sh in city['shops']),2),'npc_currency':round(sum(float((n.get('wallet') or {}).get('balance',0)) for n in current_npcs),2)}
                    binv['shops']+=len(city['shops'])
                    for sh in city['shops']:
                        for k,v in sh['inventory'].items(): binv['shop_items'][k]=binv['shop_items'].get(k,0)+int(v)
                        binv['shop_currency']+=float((sh.get('wallet') or {}).get('balance',0.0))
                    for obj in city.get('scene_objects',[]): self._accumulate_scene_object(binv,obj)
                block_npcs=npcs_by_block.get(b['id'],[])
                for npc in block_npcs:
                    binv['npcs'][npc['class']]=binv['npcs'].get(npc['class'],0)+1
                    for k,v in npc['inventory'].items(): binv['npc_items'][k]=binv['npc_items'].get(k,0)+int(v)
                    binv['npc_currency']+=float((npc.get('wallet') or {}).get('balance',0.0))
                for d in b.get('dungeons',[]):
                    binv['dungeons']+=1
                    for obj in d.get('objects',[]): self._accumulate_scene_object(binv,obj)
                    self._accumulate_dungeon_graph(binv,d)
                for obj in b.get('scene_objects',[]): self._accumulate_scene_object(binv,obj)
                b['inventory']=binv
                self._reconcile_subregions(b,block_npcs)
                self._merge_inventory(sinv,binv)
            st['inventory']=sinv
            self._merge_inventory(aggregate,sinv)
        country['inventory']=aggregate

    def _merge_inventory(self,dst,src):
        for k in ('resources','flora','fauna','npcs','shop_items','npc_items','industry_stock','bridge_resources','mage_classes','scene_objects','scene_items','dungeon_weapons'):
            for x,v in src.get(k,{}).items(): dst[k][x]=dst[k].get(x,0)+v
        for k in ('industries','cities','shops','bridges','kingdoms','legendary_creatures','dungeons','npc_currency','shop_currency'): dst[k]+=src.get(k,0)

    def _accumulate_scene_object(self,inv:dict[str,Any],obj:dict[str,Any])->None:
        typ=str(obj.get('object_type','UNKNOWN')); inv['scene_objects'][typ]=inv['scene_objects'].get(typ,0)+1
        item=obj.get('item_ref'); qty=int(obj.get('quantity',1) or 0)
        if item and obj.get('status') not in ('TAKEN','CONSUMED') and qty>0:
            inv['scene_items'][item]=inv['scene_items'].get(item,0)+qty
            if typ=='GROUND_WEAPON': inv['dungeon_weapons'][item]=inv['dungeon_weapons'].get(item,0)+qty

    def _accumulate_dungeon_graph(self,inv:dict[str,Any],dungeon:dict[str,Any])->None:
        graph=dungeon.get('graph_v2') or {}
        for room in graph.get('rooms',[]):
            for obj in room.get('objects',[]):
                if obj.get('object_ref'):
                    continue
                self._accumulate_scene_object(inv,obj)

    def _all_npc_records(self):
        country=self.world.get('country',{})
        for st in country.get('states',[]):
            for b in st.get('blocks',[]):
                for c in b.get('cities',[]):
                    for n in c.get('npcs',[]):
                        yield n

    def state(self,state_id):
        for s in self.world['country']['states']:
            if s['id']==state_id:return s
        raise KeyError(state_id)
    def block(self,block_id):
        for s in self.world['country']['states']:
            for b in s['blocks']:
                if b['id']==block_id:return b
        raise KeyError(block_id)
    def npc(self,npc_id):
        for s in self.world['country']['states']:
            for b in s['blocks']:
                for c in b['cities']:
                    for n in c['npcs']:
                        if n['id']==npc_id:return n
        raise KeyError(npc_id)
    def shop(self,shop_id):
        for s in self.world['country']['states']:
            for b in s['blocks']:
                for c in b['cities']:
                    for sh in c['shops']:
                        if sh['id']==shop_id:return sh
        raise KeyError(shop_id)

    def city(self,city_id:str)->dict[str,Any]:
        for s in self.world['country']['states']:
            for b in s['blocks']:
                for c in b['cities']:
                    if c['id']==city_id:return c
        raise KeyError(city_id)

    def relocate_npc(self,npc_id:str,destination_block_id:str,*,destination_city_id:str|None=None)->dict[str,Any]:
        npc=self.npc(npc_id); source=self.block(npc['block_id']); dest=self.block(destination_block_id)
        if destination_city_id is not None:
            city=self.city(destination_city_id)
            if not any(c['id']==destination_city_id for c in dest['cities']): return {'status':'REJECTED','reason':'CITY_NOT_IN_DESTINATION_BLOCK'}
        a=source['coordinate_center']; b=dest['coordinate_center']; dist=round(_haversine_km((a['longitude'],a['latitude']),(b['longitude'],b['latitude'])),2)
        npc['state_id']=dest['state_id']; npc['block_id']=dest['id']; npc['city_id']=destination_city_id
        self.reconcile_country_inventory()
        out={'status':'PASS','npc_id':npc_id,'source_block_id':source['id'],'destination_block_id':dest['id'],'destination_city_id':destination_city_id,'distance_km':dist}
        self._record_event('NPC_RELOCATED',out); return out

    def can_target(self,npc_id:str)->dict[str,Any]:
        n=self.npc(npc_id); p=n['protection']
        return {'npc_id':npc_id,'allowed':bool(p['combat_targetable']),'protected':bool(p['protected']),'reason':'PROTECTED_MINOR' if n['class']=='CHILD' else ('PROTECTED_WORKER_POLICY' if n['class']=='WORKER' else 'TARGETABLE_BY_GAMEPLAY_POLICY')}

    def assign_labor(self,npc_id:str, *, hazardous:bool)->dict[str,Any]:
        n=self.npc(npc_id); p=n['protection']
        if hazardous and not p['hazardous_labor_allowed']:
            return {'status':'REJECTED','npc_id':npc_id,'reason':'PROTECTED_FROM_HAZARDOUS_LABOR'}
        return {'status':'PASS','npc_id':npc_id,'hazardous':hazardous}

    def mine(self,block_id:str,resource_id:str,quantity:int)->dict[str,Any]:
        if quantity<=0: raise ValueError('quantity must be positive')
        b=self.block(block_id)
        r=next((x for x in b['resources'] if x['id']==resource_id),None)
        if not r: raise KeyError(resource_id)
        taken=min(quantity,r['remaining_units']); r['remaining_units']-=taken
        ind=next((x for x in b['industries'] if x['resource_id']==resource_id),None)
        if ind: ind['stock_units']+=taken
        r['status']='DEPLETED' if r['remaining_units']==0 else ('SCARCE' if r['remaining_units']<r['capacity_units']*.2 else 'AVAILABLE')
        self.reconcile_country_inventory()
        out={'status':'PASS','block_id':block_id,'resource_id':resource_id,'extracted':taken,'remaining':r['remaining_units'],'industry_stock':ind['stock_units'] if ind else None}
        self._record_event('RESOURCE_MINED',out); return out

    def harvest_flora(self,block_id:str,flora_id:str,quantity:int,npc_id:str)->dict[str,Any]:
        if quantity<=0: raise ValueError('quantity must be positive')
        b=self.block(block_id); f=next((x for x in b['flora'] if x['id']==flora_id),None)
        if not f: raise KeyError(flora_id)
        n=self.npc(npc_id)
        if n.get('block_id')!=block_id: return {'status':'REJECTED','reason':'ACTOR_NOT_IN_BLOCK'}
        if n['class']=='CHILD': return {'status':'REJECTED','reason':'PROTECTED_MINOR_RESOURCE_LABOR'}
        taken=min(quantity,f['remaining_units']); f['remaining_units']-=taken
        key='ITEM-HARVEST-'+f['species_ref']; n['inventory'][key]=n['inventory'].get(key,0)+taken
        f['status']='DEPLETED' if f['remaining_units']==0 else ('SCARCE' if f['remaining_units']<f['capacity_units']*.2 else f['status'])
        self.reconcile_country_inventory()
        out={'status':'PASS','harvested':taken,'flora_remaining':f['remaining_units'],'npc_item_total':n['inventory'][key],'npc_id':npc_id,'block_id':block_id}
        self._record_event('FLORA_HARVESTED',out); return out

    def hunt_fauna(self,block_id:str,fauna_id:str,quantity:int,npc_id:str)->dict[str,Any]:
        if self.domain_bridge is not None:
            return self.domain_bridge.hunt_fauna(npc_id=npc_id,block_id=block_id,fauna_id=fauna_id,quantity=quantity)
        return self._hunt_fauna_legacy(block_id,fauna_id,quantity,npc_id)

    def _hunt_fauna_legacy(self,block_id:str,fauna_id:str,quantity:int,npc_id:str)->dict[str,Any]:
        if quantity<=0: raise ValueError('quantity must be positive')
        b=self.block(block_id); a=next((x for x in b['fauna'] if x['id']==fauna_id),None)
        if not a: raise KeyError(fauna_id)
        actor=self.npc(npc_id)
        if actor.get('block_id')!=block_id: return {'status':'REJECTED','reason':'ACTOR_NOT_IN_BLOCK'}
        if actor['class']=='CHILD': return {'status':'REJECTED','reason':'PROTECTED_MINOR_COMBAT'}
        killed=min(quantity,a['count']); a['count']-=killed
        a['status']='EXTIRPATED_LOCAL' if a['count']==0 else 'ACTIVE'
        loot='ITEM-FAUNA-'+a['species_ref']; actor['inventory'][loot]=actor['inventory'].get(loot,0)+killed
        self.reconcile_country_inventory()
        out={'status':'PASS','killed':killed,'remaining':a['count'],'loot_units':actor['inventory'][loot],'root_predator':bool(b['root_deep'] and a['role']=='PREDATOR'),'npc_id':npc_id,'block_id':block_id}
        self._record_event('FAUNA_HUNTED',out); return out

    def purchase(self,shop_id:str,npc_id:str,item_ref:str,quantity:int)->dict[str,Any]:
        if self.domain_bridge is not None:
            return self.domain_bridge.purchase(shop_id=shop_id,npc_id=npc_id,item_ref=item_ref,quantity=quantity)
        return self._purchase_legacy(shop_id,npc_id,item_ref,quantity)

    def _purchase_legacy(self,shop_id:str,npc_id:str,item_ref:str,quantity:int)->dict[str,Any]:
        if quantity<=0: raise ValueError('quantity must be positive')
        sh=self.shop(shop_id); npc=self.npc(npc_id)
        if npc.get('city_id')!=sh.get('city_id'): return {'status':'REJECTED','reason':'ACTOR_NOT_IN_SHOP_CITY'}
        avail=int(sh['inventory'].get(item_ref,0)); qty=min(quantity,avail)
        if qty<=0:return {'status':'REJECTED','reason':'OUT_OF_STOCK'}
        quote=self.quote_country_item(shop_id,npc_id,item_ref,qty)
        if float(npc['wallet']['balance'])+1e-9<float(quote['total_price']):
            return {'status':'REJECTED','reason':'INSUFFICIENT_FUNDS','required':quote['total_price'],'balance':npc['wallet']['balance']}
        npc['wallet']['balance']=round(float(npc['wallet']['balance'])-float(quote['total_price']),2)
        sh['wallet']['balance']=round(float(sh['wallet']['balance'])+float(quote['total_price']),2)
        sh['inventory'][item_ref]-=qty; npc['inventory'][item_ref]=npc['inventory'].get(item_ref,0)+qty
        self.reconcile_country_inventory()
        out={'status':'PASS','quantity':qty,'shop_remaining':sh['inventory'][item_ref],'npc_total':npc['inventory'][item_ref],'shop_id':shop_id,'npc_id':npc_id,'item_ref':item_ref,'unit_price':quote['unit_price'],'total_price':quote['total_price'],'buyer_balance':npc['wallet']['balance'],'shop_balance':sh['wallet']['balance'],'price_factors':quote['factors'],'price_authority':'RUNTIME_ONLY_NOT_CANON'}
        self._record_event('SHOP_PURCHASED',out); return out

    def quote_country_item(self,shop_id:str,npc_id:str,item_ref:str,quantity:int=1)->dict[str,Any]:
        if quantity<=0: raise ValueError('quantity must be positive')
        sh=self.shop(shop_id); npc=self.npc(npc_id); b=self.block(sh['block_id']); st=self.state(sh['state_id'])
        if npc.get('city_id')!=sh.get('city_id'): return {'status':'REJECTED','reason':'ACTOR_NOT_IN_SHOP_CITY'}
        tier_base={'BAIXO':12.0,'MÉDIO':28.0,'ALTO':64.0}
        # Material tiers come from local geology; MAR/generic goods fall back to shop tier.
        local_res=next((r for r in b['resources'] if r['id']==item_ref),None)
        item_tier=local_res['tier'] if local_res else sh.get('tier','MÉDIO')
        base=tier_base.get(item_tier,28.0)
        stock=max(0,int(sh['inventory'].get(item_ref,0))); scarcity=1.0+max(0,20-stock)/80.0
        wealth=1.0+(float(st['stats']['wealth'])-0.5)*0.18
        logistics=1.0+(1.0-float(b['climate']['resource_richness']))*0.12
        reputation=max(-100.0,min(100.0,float(npc.get('reputation',0.0)))); relation=1.0-reputation*0.001
        unit=round(max(1.0,base*scarcity*wealth*logistics*relation),2)
        return {'status':'PASS','shop_id':shop_id,'npc_id':npc_id,'item_ref':item_ref,'quantity':int(quantity),'unit_price':unit,'total_price':round(unit*int(quantity),2),'currency':'CREDIT_RUNTIME','factors':{'relative_tier':item_tier,'base':base,'scarcity':round(scarcity,4),'wealth':round(wealth,4),'logistics':round(logistics,4),'relationship':round(relation,4)},'authority':'COUNTRY_RUNTIME_PRICE_V1_2_1_NOT_CANON'}

    def damage_bridge(self,block_id:str,bridge_id:str,damage:int)->dict[str,Any]:
        if damage<0: raise ValueError('damage negative')
        b=self.block(block_id); br=next((x for x in b['bridges'] if x['id']==bridge_id),None)
        if not br: raise KeyError(bridge_id)
        applied=min(int(damage),br['durability']); br['durability']-=applied
        br['status']='DESTROYED' if br['durability']==0 else ('DAMAGED' if br['durability']<br['durability_max'] else 'ACTIVE')
        out={'status':'PASS','applied_damage':applied,'durability':br['durability'],'bridge_status':br['status'],'block_id':block_id,'bridge_id':bridge_id}
        self._record_event('BRIDGE_DAMAGED',out); return out

    def repair_bridge(self,block_id:str,bridge_id:str,resource_units:int)->dict[str,Any]:
        b=self.block(block_id); br=next((x for x in b['bridges'] if x['id']==bridge_id),None)
        if not br: raise KeyError(bridge_id)
        if resource_units<=0: raise ValueError('resource_units positive')
        need=br['durability_max']-br['durability']
        if need<=0:
            return {'status':'PASS','restored':0,'durability':br['durability'],'bridge_status':br['status'],'block_id':block_id,'bridge_id':bridge_id,'material_units_consumed':0,'materials_used':{},'idempotent':True}
        available=sum(int(br.get('inventory',{}).get(k,0)) for k in ('MIN-STONE','MIN-IRON'))
        needed_units=int(math.ceil(need/5.0))
        consumed=min(int(resource_units),available,needed_units)
        if consumed<=0: return {'status':'REJECTED','reason':'NO_REPAIR_MATERIAL','block_id':block_id,'bridge_id':bridge_id}
        remaining_to_consume=consumed
        material_used={}
        for k in ('MIN-STONE','MIN-IRON'):
            have=int(br['inventory'].get(k,0)); use=min(have,remaining_to_consume)
            if use:
                br['inventory'][k]=have-use; material_used[k]=use; remaining_to_consume-=use
            if remaining_to_consume<=0: break
        restored=min(need,consumed*5)
        br['durability']+=restored; br['status']='ACTIVE' if br['durability']==br['durability_max'] else 'DAMAGED'
        self.reconcile_country_inventory()
        out={'status':'PASS','restored':restored,'durability':br['durability'],'bridge_status':br['status'],'block_id':block_id,'bridge_id':bridge_id,'material_units_consumed':consumed,'materials_used':material_used}
        self._record_event('BRIDGE_REPAIRED',out); return out

    def validate(self)->dict[str,Any]:
        failures=[]; warnings=[]; c=self.world['country']; cb=c['bounding_region']
        if len(c['states'])!=5: failures.append('STATE_COUNT_NOT_5')
        state_boxes=[]
        seen=set()
        for s in c['states']:
            if s['id'] in seen: failures.append('DUP_STATE_ID:'+s['id'])
            seen.add(s['id'])
            if not 1<=len(s['blocks'])<=5: failures.append('BLOCK_COUNT_RANGE:'+s['id'])
            sb=s['bounding_region']; state_boxes.append(sb)
            if sb[0]<cb[0] or sb[1]<cb[1] or sb[2]>cb[2] or sb[3]>cb[3]: failures.append('STATE_OUTSIDE_COUNTRY:'+s['id'])
            for b in s['blocks']:
                bb=b['bounding_region']
                if bb[0]<sb[0]-1e-9 or bb[1]<sb[1]-1e-9 or bb[2]>sb[2]+1e-9 or bb[3]>sb[3]+1e-9: failures.append('BLOCK_OUTSIDE_STATE:'+b['id'])
                cl=b['climate']; temp=cl['temperature_c']; rain=cl['rainfall_mm_y']; hum=cl['humidity_pct']
                if not (-50<=temp<=55 and 0<=rain<=5000 and 0<=hum<=100): failures.append('CLIMATE_RANGE:'+b['id'])
                if b['root_deep']:
                    if not b['biome']['predator_only']: failures.append('ROOT_BIOME_FLAG:'+b['id'])
                    if any(a['role']!='PREDATOR' for a in b['fauna']): failures.append('ROOT_NON_PREDATOR:'+b['id'])
                    if b['flora']: failures.append('ROOT_FLORA_PRESENT:'+b['id'])
                    if b['cities']: failures.append('ROOT_CITY_PRESENT:'+b['id'])
                    if b.get('kingdoms'): failures.append('ROOT_KINGDOM_PRESENT:'+b['id'])
                allowed_flora=set(self._flora_pool_for_biome(b['biome'])) if not b['root_deep'] else set()
                for f in b['flora']:
                    if f['species_ref'] not in allowed_flora: failures.append('FLORA_ADAPTATION:'+f['id'])
                allowed_fauna=set(self._fauna_pool_for_biome(b['biome'])) if not b['root_deep'] else None
                for a in b['fauna']:
                    if a['count']<0: failures.append('NEG_FAUNA:'+a['id'])
                    if allowed_fauna is not None and (a['species_ref'],a['role']) not in allowed_fauna: failures.append('FAUNA_ADAPTATION:'+a['id'])
                    if a['role']=='PREDATOR':
                        p=a['combat_profile']
                        if any(not 0<=p[x]<=100 for x in ('size','damage','resistance','venom','corruption')): failures.append('PRED_RANGE:'+a['id'])
                for r in b['resources']:
                    if not 0<=r['remaining_units']<=r['capacity_units']: failures.append('RESOURCE_RANGE:'+r['id']+':'+b['id'])
                for f in b['flora']:
                    if not 0<=f['remaining_units']<=f['capacity_units']: failures.append('FLORA_RANGE:'+f['id'])
                if not 1<=len(b.get('subregions',[]))<=3: failures.append('SUBREGION_COUNT:'+b['id'])
                # Subregion inventories must reconcile exactly to block inventory for scalar resource/fauna/flora quantities.
                for key in ('resources','flora','fauna'):
                    recon={}
                    for sub in b.get('subregions',[]):
                        for item,val in sub['inventory'][key].items(): recon[item]=recon.get(item,0)+val
                    if recon!=b['inventory'][key]: failures.append('SUBREGION_RECON:'+b['id']+':'+key)
                for realm in b.get('kingdoms',[]):
                    if realm['mage_class'] not in TIERS: failures.append('MAGE_CLASS:'+realm['id'])
                    for leg in realm.get('legendary_creatures',[]):
                        if leg['class'] not in TIERS or any(not 0<=v<=100 for k,v in leg['stats'].items() if k!='threat_score'): failures.append('LEGENDARY_STATS:'+leg['id'])
                for br in b['bridges']:
                    if br['tier']!='ALTO' or br['resource_class']!='ALTO' or br['durability_max']<7000: failures.append('BRIDGE_NOT_HIGH:'+br['id'])
                    if not 0<=br['durability']<=br['durability_max']: failures.append('BRIDGE_RANGE:'+br['id'])
                for city in b['cities']:
                    for npc in city['npcs']:
                        # NPC may have travelled out of its home city; block/state fields must still resolve.
                        try:
                            locb=self.block(npc['block_id'])
                            if npc['state_id']!=locb['state_id']: failures.append('NPC_STATE_LOCATION:'+npc['id'])
                        except Exception: failures.append('NPC_BLOCK_LOCATION:'+npc['id'])
                        if npc['class']=='CHILD' and (npc['protection']['combat_targetable'] or npc['protection']['hazardous_labor_allowed']): failures.append('CHILD_PROTECTION:'+npc['id'])
                        if npc['class']=='WORKER' and npc['protection']['hazardous_labor_allowed']: failures.append('WORKER_HAZARD:'+npc['id'])
                        if any(v<0 for v in npc['inventory'].values()): failures.append('NPC_INV_NEG:'+npc['id'])
                        if float((npc.get('wallet') or {}).get('balance',-1))<0: failures.append('NPC_WALLET_NEG:'+npc['id'])
                    for sh in city['shops']:
                        if any(v<0 for v in sh['inventory'].values()): failures.append('SHOP_INV_NEG:'+sh['id'])
                        if float((sh.get('wallet') or {}).get('balance',-1))<0: failures.append('SHOP_WALLET_NEG:'+sh['id'])
        # Country scale sanity: source is already country-scale by area.
        if float(c.get('area_km2_approx') or 0)<100000: warnings.append('COUNTRY_AREA_SMALL_FOR_TARGET_SCALE')
        # Root biome must exist in pilot world for feature test; if seed has none, this is an actionable generation gap.
        roots=sum(1 for s in c['states'] for b in s['blocks'] if b['root_deep'])
        if roots==0: failures.append('NO_ROOT_DEEP_BLOCK_GENERATED')
        if sum(len(b.get('kingdoms',[])) for st in c['states'] for b in st['blocks'])==0: failures.append('NO_MAGIC_REALM_GENERATED')
        # Each requested state archetype exactly once.
        if {s['archetype'] for s in c['states']}!={x[0] for x in STATE_ARCHETYPES}: failures.append('STATE_ARCHETYPES_MISMATCH')
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'warnings':warnings,'root_blocks':roots,'states':len(c['states']),'blocks':sum(len(s['blocks']) for s in c['states'])}

    def snapshot(self)->dict[str,Any]:
        return copy.deepcopy(self.world)

    def coordinate_scale_report(self)->dict[str,Any]:
        c=self.world['country']; cc=c['coordinate_center']; cpt=(float(cc['longitude']),float(cc['latitude']))
        distances=[]
        for s in c['states']:
            p=(float(s['coordinate_center']['longitude']),float(s['coordinate_center']['latitude']))
            distances.append({'state_id':s['id'],'center_distance_from_country_center_km':round(_haversine_km(cpt,p),2)})
        return {'country_area_km2_approx':c['area_km2_approx'],'crs':'ACRS-STELLAR-GEODETIC-V1','state_center_distances':distances,'unit_policy':{'distance':'km','area':'km2','temperature':'C','rainfall':'mm/year','humidity':'percent','gameplay_stats':'0-100','inventory':'abstract units'},'status':'PASS'}
