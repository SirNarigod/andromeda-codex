import unittest,sys,tempfile,os,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v15 import IntegratedLivingEngineV15
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
class V15Integration(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.db=os.path.join(self.t.name,'w.db');self.e=IntegratedLivingEngineV15(self.db,master_release_path=MASTER);self.r=self.e.create_world('v15i',1201,load_relationships=False);self.wid=self.r['world']['world_instance_id'];self.c=self.e.country(self.wid);self.n=next(x for x in self.c._all_npc_records() if x['class']=='WARRIOR')
 def tearDown(self):
  try:self.e.close()
  except:pass
  self.t.cleanup()
 def test_cross_chunk_owner_uses_exact_motion(self):
  m=self.e.movement(self.wid);s=self.e.streaming(self.wid);sp=self.e.spatial(self.wid);a=m.state(self.n['id']);g=sp.isometric_to_geodetic(a['iso_x_m'],a['iso_y_m']);ch=sp.chunk_for_geodetic(g['longitude'],g['latitude']);lon,lat=sp._lonlat((ch['chunk_x']+1)*sp.chunk_size_m+5,ch['local_y_m']);changed=False
  for _ in range(120):
   x=m.move_toward_geodetic(self.n['id'],lon,lat,duration_s=10,mode='WALK',environment_factor=1)
   if x.get('chunk_changed'):changed=True;break
  self.assertTrue(changed);self.assertEqual(s.owners[self.n['id']],s.owner_chunk_for_npc(self.n['id']));self.assertEqual(s.full_integrity_check()['status'],'PASS')
 def test_discovery_hides_dungeon_until_known(self):
  d=next(d for st in self.c.world['country']['states'] for b in st['blocks'] for d in b.get('dungeons',[]));disc=self.e.discovery(self.wid);p=disc.player_projection(self.n['id'],5);self.assertNotIn(d['id'],{f['id'] for f in p['features']});disc.discover(self.n['id'],d['id'],'DUNGEON');p2=disc.player_projection(self.n['id'],5);self.assertIn(d['id'],{f['id'] for f in p2['features']})
 def test_godot_chunk_does_not_leak_undiscovered_dungeon(self):
  snap=self.e.godot(self.wid).snapshot(self.n['id']);known={r['feature_ref'] for r in self.e.discovery(self.wid).known(self.n['id'])};secret=[x for x in snap['chunk']['entities'] if x['kind'] in ('DUNGEON','DUNGEON_ROOM') and x['entity_ref'] not in known];self.assertEqual(secret,[])
 def test_resume_preserves_motion_and_discovery(self):
  pid=self.n['id'];self.e.godot(self.wid).command(pid,'MOVE_VECTOR',{'dx':1,'dy':1,'duration_s':2,'mode':'WALK'});self.e.discovery(self.wid).discover(pid,'TEST-FEATURE','TEST');before=self.e.movement(self.wid).state(pid);wid=self.wid;self.e.close();self.e=IntegratedLivingEngineV15(self.db,master_release_path=MASTER);rr=self.e.resume_world(wid);after=self.e.movement(wid).state(pid);self.assertEqual(rr['status'],'PASS');self.assertAlmostEqual(before['iso_x_m'],after['iso_x_m']);self.assertEqual(len(self.e.discovery(wid).known(pid)),1)
 def test_all_blocks_path_resolvable_or_explicitly_isolated(self):
  blocks=[b for st in self.c.world['country']['states'] for b in st['blocks']];origin=blocks[0]['id'];fails=[]
  for b in blocks[1:]:
   p=self.e.navigation(self.wid).plan_blocks(origin,b['id'])
   if p['status']!='PASS':fails.append(b['id'])
  self.assertEqual(fails,[])
if __name__=='__main__':unittest.main()
