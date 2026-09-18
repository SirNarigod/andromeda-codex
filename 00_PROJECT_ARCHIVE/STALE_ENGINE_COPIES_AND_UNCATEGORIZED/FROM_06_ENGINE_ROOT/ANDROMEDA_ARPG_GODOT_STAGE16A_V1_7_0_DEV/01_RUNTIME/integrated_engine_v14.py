from __future__ import annotations
from typing import Any
from integrated_engine_v13 import IntegratedLivingEngineV13
from living_runtime import ValidationError
from spatial_coordinates import SpatialCoordinateSystem
from atlas_country_lod import AtlasCountryLOD
from streaming_system import ChunkStreamingSystem
from dungeon_graph_v2 import DungeonGraphV2
from country_scale import CountryScaleSystem
from scene_interaction import SceneInteractionSystem
from country_living_bridge import CountryLivingDomainBridge

class IntegratedLivingEngineV14(IntegratedLivingEngineV13):
    VERSION='V1.4.0';AUTHORITY='INTEGRATED_LIVING_V1_4_ATLAS_LOD_STREAMING'
    def __init__(self,db_path=':memory:',*,master_release_path):
        super().__init__(db_path,master_release_path=master_release_path);self._spatial={};self._lod={};self._stream={};self._dgraph={}
    def create_world(self,owner_scope:str,seed:int,**kwargs)->dict[str,Any]:
        r=super().create_world(owner_scope,seed,**kwargs);wid=r['world']['world_instance_id'];c=self.country(wid);s=self.scenes(wid)
        sp=SpatialCoordinateSystem(c);sp.enrich_country_coordinates();lod=AtlasCountryLOD(c,sp);stream=ChunkStreamingSystem(self.runtime,wid,c,sp,advance_ticks_callback=lambda ticks:self.orchestrator.run_steps(wid,ticks));dg=DungeonGraphV2(c,s,streaming=stream,spatial=sp)
        self._spatial[wid]=sp;self._lod[wid]=lod;self._stream[wid]=stream;self._dgraph[wid]=dg;c._persist_state()
        health=self.health_v14(wid)
        if health['status']!='PASS':raise ValidationError('V1.4 bootstrap failed:'+str(health['failures']))
        r.update({'version':self.VERSION,'authority':self.AUTHORITY,'spatial':{'status':'PASS','crs':sp.CRS,'chunk_size_m':sp.chunk_size_m},'atlas_lod':lod.verify(),'streaming':stream.full_integrity_check(),'dungeon_graph':dg.validate()})
        return r

    def resume_world(self, world_instance_id:str)->dict[str,Any]:
        """Rehydrate an existing V1.4 world after process restart without creating a new world.

        Persisted Living truth remains authoritative. In-memory adapters/projections are rebuilt
        from the existing world, Country snapshot and streaming ownership tables.
        """
        world=self.runtime.get_world(world_instance_id)
        baseline=world.get('baseline') or {}
        if baseline.get('master_version')!=self.runtime.master_version or baseline.get('release_sha256')!=self.runtime.master_release_sha256:
            raise ValidationError('resume baseline mismatch')
        # Rebind persisted orchestrator descriptors to this process' handlers.
        for key,handler in ((self.world_systems.EXTENSION_KEY,self.world_systems.extension_handler),(self.mobility.EXTENSION_KEY,self.mobility.extension_handler),(self.society.EXTENSION_KEY,self.society.extension_handler)):
            self.orchestrator.bind_extension_handler(world_instance_id,key,handler)
        # Country is reconstructed from canonical seed then replaced by its hash-verified persisted snapshot.
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM country_scale_state WHERE world_instance_id=?',(world_instance_id,)).fetchone()
        if not row: raise ValidationError('country snapshot missing for resume')
        import json,hashlib
        if hashlib.sha256(row['payload_json'].encode('utf-8')).hexdigest()!=row['payload_hash']:
            raise ValidationError('country snapshot hash mismatch during resume')
        snap=json.loads(row['payload_json']); territory=(snap.get('country') or {}).get('source_territory_id') or 'TER-011'
        country=CountryScaleSystem(master_release_path=self.master_release_path,country_territory_id=territory,seed=int(world['seed']))
        persistence=country.attach_runtime(self.runtime,world_instance_id)
        self.country_systems[world_instance_id]=country
        scene=SceneInteractionSystem(country); self.scene_systems[world_instance_id]=scene
        bridge=CountryLivingDomainBridge(self,world_instance_id,country); self.country_bridges[world_instance_id]=bridge
        sp=SpatialCoordinateSystem(country);sp.enrich_country_coordinates()
        lod=AtlasCountryLOD(country,sp)
        stream=ChunkStreamingSystem(self.runtime,world_instance_id,country,sp,advance_ticks_callback=lambda ticks:self.orchestrator.run_steps(world_instance_id,ticks))
        dg=DungeonGraphV2(country,scene,streaming=stream,spatial=sp)
        self._spatial[world_instance_id]=sp;self._lod[world_instance_id]=lod;self._stream[world_instance_id]=stream;self._dgraph[world_instance_id]=dg
        health=self.health_v14(world_instance_id)
        if health['status']!='PASS': raise ValidationError('V1.4 resume failed:'+str(health['failures']))
        return {'status':'PASS','version':self.VERSION,'authority':self.AUTHORITY,'world_instance_id':world_instance_id,'seed':world['seed'],'country_persistence':persistence,'streaming':stream.full_integrity_check(),'health':health,'identity_preserved':True,'new_world_created':False}

    def spatial(self,wid):return self._spatial[wid]
    def atlas_lod(self,wid):return self._lod[wid]
    def streaming(self,wid):return self._stream[wid]
    def dungeon_graph(self,wid):return self._dgraph[wid]
    def health_v14(self,wid):
        base=self.health_v13(wid);parts={'lod':self._lod[wid].verify(),'streaming':self._stream[wid].full_integrity_check(),'dungeon_graph':self._dgraph[wid].validate()};fail=[]
        if base['status']!='PASS':fail.extend('V13:'+x for x in base.get('failures',[]))
        for k,v in parts.items():
            if v['status']!='PASS':fail.extend(k.upper()+':'+x for x in v.get('failures',[]))
        return {'status':'PASS' if not fail else 'FAIL','failures':fail,'v13':base,**parts,'authority':self.AUTHORITY}
