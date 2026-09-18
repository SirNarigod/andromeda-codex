import unittest,sys,tempfile,os,math,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v14 import IntegratedLivingEngineV14
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
class GodotDungeon(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.e=IntegratedLivingEngineV14(os.path.join(self.t.name,'w.db'),master_release_path=MASTER);r=self.e.create_world('godot',1201,load_relationships=False);self.w=r['world']['world_instance_id'];self.c=self.e.country(self.w);self.sp=self.e.spatial(self.w);self.lod=self.e.atlas_lod(self.w)
 def tearDown(self):self.e.close();self.t.cleanup()
 def test_room_coordinates_local_and_edges_have_lengths(self):
  for st in self.c.world['country']['states']:
   for b in st['blocks']:
    for d in b.get('dungeons',[]):
     a=self.sp.geodetic_to_isometric(d['coordinate_center']['longitude'],d['coordinate_center']['latitude'])
     for r in d['graph_v2']['rooms']:
      z=self.sp.geodetic_to_isometric(r['coordinate_center']['longitude'],r['coordinate_center']['latitude']);self.assertLessEqual(math.hypot(a['local_x_m']-z['local_x_m'],a['local_y_m']-z['local_y_m']),150)
     self.assertTrue(all(e.get('length_m',0)>0 for e in d['graph_v2']['edges']))
 def test_chunk_payload_unique_and_chunk_consistent(self):
  n=next(x for x in self.c._all_npc_records() if x['class']=='WARRIOR');ch=self.e.streaming(self.w).owners[n['id']];p=self.lod.godot_chunk_payload(ch);self.assertEqual(p['status'],'PASS');refs=[x['entity_ref'] for x in p['entities']];self.assertEqual(len(refs),len(set(refs)));self.assertTrue(all(x['chunk_id']==ch for x in p['entities']));self.assertIn(n['id'],refs)
 def test_payload_is_deep_read_only(self):
  n=next(x for x in self.c._all_npc_records() if x['class']=='WARRIOR');ch=self.e.streaming(self.w).owners[n['id']];p=self.lod.godot_chunk_payload(ch);row=next(x for x in p['entities'] if x['entity_ref']==n['id']);orig=self.c.npc(n['id'])['class'];row['data']['class']='MUTATED';self.assertEqual(self.c.npc(n['id'])['class'],orig)
 def test_npc_moves_to_dungeon_payload_chunk(self):
  d=next(d for st in self.c.world['country']['states'] for b in st['blocks'] for d in b.get('dungeons',[]));n=next(x for x in self.c._all_npc_records() if x['class']=='WARRIOR');stream=self.e.streaming(self.w);stream.travel_npc(n['id'],d['block_id'],speed_kmh=1000);old=stream.owners[n['id']];self.assertEqual(self.e.dungeon_graph(self.w).enter(n['id'],d['id'])['status'],'PASS');new=stream.owners[n['id']];self.assertNotEqual(old,new);self.assertIn(n['id'],[x['entity_ref'] for x in self.lod.godot_chunk_payload(new)['entities']]);self.assertNotIn(n['id'],[x['entity_ref'] for x in self.lod.godot_chunk_payload(old)['entities']])
if __name__=='__main__':unittest.main()
