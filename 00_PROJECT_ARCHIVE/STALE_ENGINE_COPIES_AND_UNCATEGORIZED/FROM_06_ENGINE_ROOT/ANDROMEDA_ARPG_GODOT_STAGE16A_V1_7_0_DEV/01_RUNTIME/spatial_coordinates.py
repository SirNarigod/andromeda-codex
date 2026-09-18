from __future__ import annotations
import math, hashlib, re
from typing import Any

STELLAR_MEAN_RADIUS_M = 6_172_666.667
DEFAULT_CHUNK_SIZE_M = 4096.0
DEFAULT_TILE_SIZE_M = 2.0


def _center(bbox):
    return {'longitude':(float(bbox[0])+float(bbox[2]))/2.0,'latitude':(float(bbox[1])+float(bbox[3]))/2.0}

def _seed_fraction(*parts:str)->float:
    h=hashlib.sha256('|'.join(map(str,parts)).encode()).hexdigest()
    return int(h[:12],16)/float(16**12-1)

class SpatialCoordinateSystem:
    VERSION='V1.4.0'
    AUTHORITY='LIVING_SPATIAL_COORDINATE_PROJECTION_RUNTIME'
    CRS='ACRS-STELLAR-GEODETIC-V1'
    def __init__(self,country_system:Any,*,chunk_size_m:float=DEFAULT_CHUNK_SIZE_M,tile_size_m:float=DEFAULT_TILE_SIZE_M):
        self.country=country_system; self.chunk_size_m=float(chunk_size_m); self.tile_size_m=float(tile_size_m)
        c=self.country.world['country']; cc=c['coordinate_center']; self.origin_lon=float(cc['longitude']); self.origin_lat=float(cc['latitude'])
        self.enrich_country_coordinates()
    def _local_xy(self,lon:float,lat:float)->tuple[float,float]:
        lon0=math.radians(self.origin_lon); lat0=math.radians(self.origin_lat); lonr=math.radians(float(lon)); latr=math.radians(float(lat))
        x=(lonr-lon0)*math.cos(lat0)*STELLAR_MEAN_RADIUS_M; y=(latr-lat0)*STELLAR_MEAN_RADIUS_M
        return x,y
    def _lonlat(self,x:float,y:float)->tuple[float,float]:
        lat0=math.radians(self.origin_lat); lon0=math.radians(self.origin_lon)
        lat=lat0+float(y)/STELLAR_MEAN_RADIUS_M; lon=lon0+float(x)/(STELLAR_MEAN_RADIUS_M*math.cos(lat0))
        return math.degrees(lon),math.degrees(lat)
    def geodetic_to_isometric(self,lon:float,lat:float,altitude_m:float=0.0)->dict[str,Any]:
        x,y=self._local_xy(lon,lat); s=math.sqrt(2.0)
        ix=(x-y)/s; iy=(x+y)/s
        return {'iso_x_m':ix,'iso_y_m':iy,'altitude_m':float(altitude_m),'local_x_m':x,'local_y_m':y,'crs':self.CRS,'authority':self.AUTHORITY}
    def isometric_to_geodetic(self,iso_x_m:float,iso_y_m:float,altitude_m:float=0.0)->dict[str,Any]:
        s=math.sqrt(2.0); x=(float(iso_x_m)+float(iso_y_m))/s; y=(float(iso_y_m)-float(iso_x_m))/s; lon,lat=self._lonlat(x,y)
        return {'longitude':lon,'latitude':lat,'altitude_m':float(altitude_m),'crs':self.CRS,'authority':self.AUTHORITY}
    def chunk_for_geodetic(self,lon:float,lat:float)->dict[str,Any]:
        x,y=self._local_xy(lon,lat); cx=math.floor(x/self.chunk_size_m); cy=math.floor(y/self.chunk_size_m)
        return {'chunk_id':f'CHK-{cx:+07d}-{cy:+07d}','chunk_x':cx,'chunk_y':cy,'chunk_size_m':self.chunk_size_m,'local_x_m':x,'local_y_m':y}
    def chunk_neighbors(self,chunk_id:str,radius:int=1)->list[str]:
        m=re.fullmatch(r'CHK-([+-]\d+)-([+-]\d+)',chunk_id)
        if not m: raise ValueError('invalid chunk_id:'+str(chunk_id))
        cx=int(m.group(1)); cy=int(m.group(2)); out=[]
        for dx in range(-radius,radius+1):
            for dy in range(-radius,radius+1): out.append(f'CHK-{cx+dx:+07d}-{cy+dy:+07d}')
        return sorted(out)
    def _point_for_bbox(self,bbox,tag:str)->dict[str,Any]:
        lon0,lat0,lon1,lat1=map(float,bbox); fx=.2+.6*_seed_fraction(self.country.seed,tag,'lon'); fy=.2+.6*_seed_fraction(self.country.seed,tag,'lat')
        lon=lon0+(lon1-lon0)*fx; lat=lat0+(lat1-lat0)*fy
        return {'longitude':round(lon,8),'latitude':round(lat,8),'altitude_m':0.0,'crs_id':self.CRS,'precision_class':'RUNTIME_ANCHOR'}
    def offset_geodetic(self,parent:dict[str,Any],dx_m:float,dy_m:float)->dict[str,Any]:
        x,y=self._local_xy(float(parent['longitude']),float(parent['latitude']));lon,lat=self._lonlat(x+float(dx_m),y+float(dy_m))
        return {'longitude':round(lon,8),'latitude':round(lat,8),'altitude_m':float(parent.get('altitude_m',0.0)),'crs_id':self.CRS,'precision_class':'RUNTIME_LOCAL_OFFSET'}

    def _point_near(self,parent:dict[str,Any],tag:str,radius_m:float)->dict[str,Any]:
        x,y=self._local_xy(float(parent['longitude']),float(parent['latitude']))
        angle=2.0*math.pi*_seed_fraction(self.country.seed,tag,'angle'); r=float(radius_m)*(.15+.85*_seed_fraction(self.country.seed,tag,'radius'))
        lon,lat=self._lonlat(x+math.cos(angle)*r,y+math.sin(angle)*r)
        return {'longitude':round(lon,8),'latitude':round(lat,8),'altitude_m':float(parent.get('altitude_m',0.0)),'crs_id':self.CRS,'precision_class':'RUNTIME_LOCAL_ANCHOR'}
    def enrich_country_coordinates(self)->dict[str,Any]:
        added=0; c=self.country.world['country']
        for st in c['states']:
            for b in st['blocks']:
                for sr in b.get('subregions',[]):
                    if 'coordinate_center' not in sr:
                        cc=_center(sr['bounding_region']); sr['coordinate_center']={'longitude':round(cc['longitude'],8),'latitude':round(cc['latitude'],8),'altitude_m':float(b['coordinate_center'].get('altitude_m',0)),'crs_id':self.CRS,'precision_class':'DERIVED_CENTER'}; added+=1
                for city in b.get('cities',[]):
                    if 'coordinate_center' not in city:
                        city['coordinate_center']=self._point_for_bbox(b['bounding_region'],city['id']); added+=1
                for obj in b.get('scene_objects',[]):
                    if 'coordinate_center' not in obj:
                        obj['coordinate_center']=self._point_for_bbox(b['bounding_region'],obj['id']); added+=1
                for city in b.get('cities',[]):
                    for obj in city.get('scene_objects',[]):
                        if 'coordinate_center' not in obj:
                            obj['coordinate_center']=self._point_near(city['coordinate_center'],obj['id'],150.0); added+=1
                for d in b.get('dungeons',[]):
                    if 'coordinate_center' not in d:
                        d['coordinate_center']=self._point_for_bbox(b['bounding_region'],d['id']); added+=1
                    for obj in d.get('objects',[]):
                        if 'coordinate_center' not in obj:
                            obj['coordinate_center']=self._point_near(d['coordinate_center'],obj['id'],120.0); added+=1
        membership=self.refresh_membership()
        if added and self.country.runtime and self.country.world_instance_id: self.country._record_event('SPATIAL_COORDINATES_ENRICHED',{'added':added,'authority':self.AUTHORITY})
        return {'status':'PASS','added':added,'membership':membership}
    def _subregion_for_point(self,block:dict[str,Any],cc:dict[str,Any])->str|None:
        lon=float(cc['longitude']);lat=float(cc['latitude'])
        for sr in block.get('subregions',[]):
            x0,y0,x1,y1=map(float,sr['bounding_region'])
            if x0-1e-9<=lon<=x1+1e-9 and y0-1e-9<=lat<=y1+1e-9:return sr['id']
        return None
    def refresh_membership(self)->dict[str,Any]:
        assigned=0
        for st in self.country.world['country']['states']:
            for b in st['blocks']:
                for city in b.get('cities',[]):
                    city['subregion_id']=self._subregion_for_point(b,city['coordinate_center']);assigned+=1
                    for obj in city.get('scene_objects',[]):obj['subregion_id']=self._subregion_for_point(b,obj['coordinate_center']);assigned+=1
                for obj in b.get('scene_objects',[]):obj['subregion_id']=self._subregion_for_point(b,obj['coordinate_center']);assigned+=1
                for d in b.get('dungeons',[]):
                    d['subregion_id']=self._subregion_for_point(b,d['coordinate_center']);assigned+=1
                    for obj in d.get('objects',[]):obj['subregion_id']=d['subregion_id'];assigned+=1
        return {'status':'PASS','assigned':assigned}

    def point_for_npc(self,npc:dict[str,Any])->dict[str,Any]:
        scene_ref=npc.get('scene_id') or npc.get('dungeon_id')
        if scene_ref:
            try:
                d=self._find_dungeon(scene_ref); room_ref=npc.get('dungeon_room_id')
                if room_ref:
                    room=next((r for r in (d.get('graph_v2') or {}).get('rooms',[]) if r['id']==room_ref),None)
                    if room and room.get('coordinate_center'):return dict(room['coordinate_center'])
                return dict(d['coordinate_center'])
            except KeyError:pass
        if npc.get('city_id'):
            try:return dict(self.country.city(npc['city_id'])['coordinate_center'])
            except KeyError:pass
        return dict(self.country.block(npc['block_id'])['coordinate_center'])
    def _find_dungeon(self,did):
        for st in self.country.world['country']['states']:
            for b in st['blocks']:
                for d in b.get('dungeons',[]):
                    if d['id']==did:return d
        raise KeyError(did)
    def roundtrip_error_m(self,lon:float,lat:float)->float:
        a=self.geodetic_to_isometric(lon,lat); b=self.isometric_to_geodetic(a['iso_x_m'],a['iso_y_m']); x1,y1=self._local_xy(lon,lat); x2,y2=self._local_xy(b['longitude'],b['latitude']); return math.hypot(x1-x2,y1-y2)
