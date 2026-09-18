import unittest,sys,tempfile,os,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v15 import IntegratedLivingEngineV15
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
class V15Core(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.e=IntegratedLivingEngineV15(os.path.join(self.t.name,'w.db'),master_release_path=MASTER);self.r=self.e.create_world('v15',1201,load_relationships=False);self.wid=self.r['world']['world_instance_id'];self.c=self.e.country(self.wid);self.n=next(x for x in self.c._all_npc_records() if x['class']=='WARRIOR')
 def tearDown(self):self.e.close();self.t.cleanup()
 def test_bootstrap(self):self.assertEqual(self.e.health_v15(self.wid)['status'],'PASS')
 def test_continuous_step_and_stamina(self):
  a=self.e.movement(self.wid).state(self.n['id']);x=self.e.godot(self.wid).command(self.n['id'],'MOVE_VECTOR',{'dx':1,'dy':0,'duration_s':1,'mode':'RUN'});b=self.e.movement(self.wid).state(self.n['id']);self.assertEqual(x['status'],'PASS');self.assertGreater(b['iso_x_m'],a['iso_x_m']);self.assertLess(b['stamina'],a['stamina']);self.assertEqual(self.e.streaming(self.wid).full_integrity_check()['status'],'PASS')
 def test_invalid_long_step_rejected(self):self.assertEqual(self.e.movement(self.wid).step_vector(self.n['id'],1,0,duration_s=60)['status'],'REJECTED')
 def test_environment_deterministic_same_clock(self):
  b=self.c.block(self.n['block_id']);a=self.e.environment(self.wid).state_for_block(b['id']);z=self.e.environment(self.wid).state_for_block(b['id']);self.assertEqual(a,z)
 def test_discovery_player_scoped(self):
  p1=self.n['id'];p2=next(x['id'] for x in self.c._all_npc_records() if x['id']!=p1);self.e.discovery(self.wid).discover_nearby(p1,500);self.assertGreaterEqual(len(self.e.discovery(self.wid).known(p1)),1);self.assertEqual(len(self.e.discovery(self.wid).known(p2)),0)
 def test_path_plan(self):
  blocks=[b for st in self.c.world['country']['states'] for b in st['blocks']];dest=next(b for b in blocks if b['id']!=self.n['block_id']);p=self.e.navigation(self.wid).plan_blocks(self.n['block_id'],dest['id']);self.assertIn(p['status'],('PASS','REJECTED'))
 def test_godot_snapshot_server_authoritative(self):self.assertTrue(self.e.godot(self.wid).snapshot(self.n['id'])['server_authoritative'])
if __name__=='__main__':unittest.main()
