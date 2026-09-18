import unittest,sys,tempfile,os,math,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v14 import IntegratedLivingEngineV14
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
class SimulationAnomalies(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.e=IntegratedLivingEngineV14(os.path.join(self.t.name,'w.db'),master_release_path=MASTER);r=self.e.create_world('sim',1201,load_relationships=False);self.w=r['world']['world_instance_id'];self.c=self.e.country(self.w);self.sp=self.e.spatial(self.w)
 def tearDown(self):self.e.close();self.t.cleanup()
 def test_travel_advances_world_clock(self):
  n=next(x for x in self.c._all_npc_records() if x['class']=='WARRIOR');dst=next(b for st in self.c.world['country']['states'] for b in st['blocks'] if b['state_id']!=n['state_id']);before=self.e.runtime.get_clock(self.w);x=self.e.streaming(self.w).travel_npc(n['id'],dst['id'],speed_kmh=60);after=self.e.runtime.get_clock(self.w);self.assertGreater(x['travel_hours'],0);self.assertNotEqual((before['day'],before['tick']),(after['day'],after['tick']))
 def test_dungeon_entry_exit_keeps_stream_ownership_consistent(self):
  dg=self.e.dungeon_graph(self.w);d=next(d for st in self.c.world['country']['states'] for b in st['blocks'] for d in b.get('dungeons',[]));n=next(x for x in self.c._all_npc_records() if x['class']=='WARRIOR');self.e.streaming(self.w).travel_npc(n['id'],d['block_id'],speed_kmh=60);self.assertEqual(dg.enter(n['id'],d['id'])['status'],'PASS');self.assertEqual(self.e.streaming(self.w).full_integrity_check()['status'],'PASS');self.assertEqual(dg.leave(n['id'])['status'],'PASS');self.assertEqual(self.e.streaming(self.w).full_integrity_check()['status'],'PASS')
 def test_dungeon_scene_objects_are_local_to_dungeon(self):
  # 250 m radius is generous for a single isometric dungeon entrance/scene anchor.
  for st in self.c.world['country']['states']:
   for b in st['blocks']:
    for d in b.get('dungeons',[]):
     a=self.sp.geodetic_to_isometric(d['coordinate_center']['longitude'],d['coordinate_center']['latitude'])
     for o in d['objects']:
      z=self.sp.geodetic_to_isometric(o['coordinate_center']['longitude'],o['coordinate_center']['latitude']);dist=math.hypot(a['local_x_m']-z['local_x_m'],a['local_y_m']-z['local_y_m']);self.assertLessEqual(dist,250,(d['id'],o['id'],dist))
 def test_atlas_projection_is_deep_read_only_copy(self):
  lod=self.e.atlas_lod(self.w);before=copy.deepcopy(self.c.world['country']['coordinate_center']);p=lod.project(0,layers=[]);p['features'][0]['coordinate']['longitude']+=999;self.assertEqual(self.c.world['country']['coordinate_center'],before)
  # biome nested object also must be detached
  p=lod.project(4,layers=[]);bf=copy.deepcopy(self.c.world['country']['states'][0]['blocks'][0]['biome']);bio=next(x for x in p['features'] if x['kind']=='BIOME');bio['biome']['name']='MUTATED';self.assertEqual(self.c.world['country']['states'][0]['blocks'][0]['biome'],bf)
 def test_dungeon_entry_changes_owner_to_dungeon_chunk_and_exit_restores_block_chunk(self):
  dg=self.e.dungeon_graph(self.w);stream=self.e.streaming(self.w);d=next(d for st in self.c.world['country']['states'] for b in st['blocks'] for d in b.get('dungeons',[]));n=next(x for x in self.c._all_npc_records() if x['class']=='WARRIOR');stream.travel_npc(n['id'],d['block_id'],speed_kmh=60)
  block_chunk=self.sp.chunk_for_geodetic(self.c.block(d['block_id'])['coordinate_center']['longitude'],self.c.block(d['block_id'])['coordinate_center']['latitude'])['chunk_id'];dchunk=self.sp.chunk_for_geodetic(d['coordinate_center']['longitude'],d['coordinate_center']['latitude'])['chunk_id'];self.assertNotEqual(block_chunk,dchunk)
  self.assertEqual(dg.enter(n['id'],d['id'])['status'],'PASS');self.assertEqual(stream.owners[n['id']],dchunk)
  self.assertEqual(dg.leave(n['id'])['status'],'PASS');self.assertEqual(stream.owners[n['id']],block_chunk)
if __name__=='__main__':unittest.main()
