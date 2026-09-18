import unittest,sys,tempfile,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v14 import IntegratedLivingEngineV14
from streaming_system import ChunkStreamingSystem
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
class Invariants(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.e=IntegratedLivingEngineV14(os.path.join(self.t.name,'w.db'),master_release_path=MASTER);r=self.e.create_world('inv',1201,load_relationships=False);self.w=r['world']['world_instance_id'];self.c=self.e.country(self.w)
 def tearDown(self):self.e.close();self.t.cleanup()
 def test_every_active_owner_chunk_loaded(self):
  s=self.e.streaming(self.w);missing=sorted(set(s.owners.values())-s.loaded);self.assertEqual(missing,[])
 def test_streaming_state_rehydrates_without_duplicate_ownership(self):
  s=self.e.streaming(self.w);n=next(x for x in self.c._all_npc_records() if x['class']=='WARRIOR');dst=next(b for st in self.c.world['country']['states'] for b in st['blocks'] if b['state_id']!=n['state_id']);self.assertEqual(s.travel_npc(n['id'],dst['id'],speed_kmh=50)['status'],'PASS');owner=s.owners[n['id']]
  s2=ChunkStreamingSystem(self.e.runtime,self.w,self.c,self.e.spatial(self.w));self.assertEqual(s2.owners[n['id']],owner);self.assertEqual(s2.full_integrity_check()['status'],'PASS');self.assertEqual(len(s2.owners),len(set(s2.owners)))
 def test_lod_scene_entities_have_coordinates(self):
  p=self.e.atlas_lod(self.w).project(6,layers=[]);bad=[f['id'] for f in p['features'] if 'coordinate' not in f];self.assertEqual(bad,[])
 def test_dungeon_locked_edges_have_reachable_keys(self):
  dg=self.e.dungeon_graph(self.w)
  for st in self.c.world['country']['states']:
   for b in st['blocks']:
    for d in b.get('dungeons',[]):
     g=d['graph_v2']; room_index={r['id']:i for i,r in enumerate(g['rooms'])}
     for e in g['edges']:
      if e.get('locked'):
       key=e['key_item_ref']; key_rooms=[r['id'] for r in g['rooms'] if any(o.get('item_ref')==key and o.get('quantity',0)>0 for o in r['objects'])]
       self.assertTrue(key_rooms,(d['id'],e['id'],key));self.assertLess(min(room_index[x] for x in key_rooms),max(room_index[e['from']],room_index[e['to']]))
if __name__=='__main__':unittest.main()
