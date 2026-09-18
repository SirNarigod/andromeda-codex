import unittest,sys,math,tempfile,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v14 import IntegratedLivingEngineV14
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
class V14(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.e=IntegratedLivingEngineV14(os.path.join(self.t.name,'w.db'),master_release_path=MASTER);self.r=self.e.create_world('v14',1201,load_relationships=False);self.wid=self.r['world']['world_instance_id'];self.c=self.e.country(self.wid)
 def tearDown(self):self.e.close();self.t.cleanup()
 def test_bootstrap(self):self.assertEqual(self.e.health_v14(self.wid)['status'],'PASS')
 def test_all_lods_and_layers(self):
  lod=self.e.atlas_lod(self.wid)
  for i in range(7):self.assertGreater(lod.project(i)['feature_count'],0)
  p=lod.layer_projection();self.assertEqual(set(p),set(lod.LAYERS))
 def test_roundtrip_submeter(self):
  sp=self.e.spatial(self.wid)
  for st in self.c.world['country']['states']:
   for b in st['blocks']:
    cc=b['coordinate_center'];self.assertLess(sp.roundtrip_error_m(cc['longitude'],cc['latitude']),0.001)
 def test_subregions_have_centers(self):
  self.assertTrue(all('coordinate_center' in sr for st in self.c.world['country']['states'] for b in st['blocks'] for sr in b['subregions']))
 def test_cross_state_travel_ownership(self):
  n=next(x for x in self.c._all_npc_records() if x['class']=='WARRIOR');dst=next(b for st in self.c.world['country']['states'] for b in st['blocks'] if b['state_id']!=n['state_id']);before=n['id']
  x=self.e.streaming(self.wid).travel_npc(n['id'],dst['id'],speed_kmh=60);self.assertEqual(x['status'],'PASS');self.assertEqual(n['id'],before);self.assertGreater(x['chunk_transitions'],0);self.assertGreater(x['travel_hours'],0);self.assertEqual(self.e.streaming(self.wid).full_integrity_check()['status'],'PASS')
 def test_unload_owned_chunk_rejected(self):
  s=self.e.streaming(self.wid);n=next(iter(self.c._all_npc_records()));ch=s.owners[n['id']];self.assertEqual(s.unload_chunk(ch)['status'],'REJECTED')
 def test_dungeon_graph_connected_and_move(self):
  dg=self.e.dungeon_graph(self.wid);self.assertEqual(dg.validate()['status'],'PASS');d=next(d for st in self.c.world['country']['states'] for b in st['blocks'] for d in b.get('dungeons',[]));n=next(x for x in self.c._all_npc_records() if x['class']=='WARRIOR');self.c.relocate_npc(n['id'],d['block_id']);x=dg.enter(n['id'],d['id']);self.assertEqual(x['status'],'PASS');g=d['graph_v2'];cur=x['room_id'];edge=next(e for e in g['edges'] if e['from']==cur or e['to']==cur);dest=edge['to'] if edge['from']==cur else edge['from'];m=dg.move(n['id'],d['id'],dest);self.assertIn(m['status'],('PASS','REJECTED'))
if __name__=='__main__':unittest.main()
