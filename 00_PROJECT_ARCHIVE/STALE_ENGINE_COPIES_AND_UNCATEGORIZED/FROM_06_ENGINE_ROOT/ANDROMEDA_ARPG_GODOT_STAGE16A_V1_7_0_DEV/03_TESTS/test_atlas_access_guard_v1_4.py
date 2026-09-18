import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v14 import IntegratedLivingEngineV14
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
class AccessGuardTests(unittest.TestCase):
 def setUp(self):
  self.e=IntegratedLivingEngineV14(':memory:',master_release_path=MASTER);r=self.e.create_world('access',9101,load_relationships=False);self.w=r['world']['world_instance_id'];self.l=self.e.atlas_lod(self.w)
 def tearDown(self):self.e.close()
 def test_public_cannot_request_dungeon_or_scene_lod(self):
  for lod in (5,6):
   p=self.l.project(lod,audience='PUBLIC');self.assertEqual(p['status'],'REJECTED');self.assertEqual(p['feature_count'],0)
 def test_public_sensitive_layers_are_redacted(self):
  p=self.l.project(2,layers=['climate','resources','commerce','population','root','threat','routes'],audience='PUBLIC')
  self.assertEqual(p['status'],'PASS');self.assertEqual(set(p['layers']),{'climate','routes'});self.assertEqual(set(p['redacted_layers']),{'resources','commerce','population','root','threat'})
 def test_admin_retains_full_projection(self):
  p=self.l.project(6,layers=list(self.l.LAYERS),audience='ADMIN');self.assertEqual(p['status'],'PASS');self.assertGreater(p['feature_count'],0);self.assertEqual(set(p['layers']),set(self.l.LAYERS));self.assertEqual(p['redacted_layers'],[])
 def test_unknown_audience_fails_closed(self):
  with self.assertRaises(ValueError):self.l.project(1,audience='UNKNOWN')
if __name__=='__main__':unittest.main()
