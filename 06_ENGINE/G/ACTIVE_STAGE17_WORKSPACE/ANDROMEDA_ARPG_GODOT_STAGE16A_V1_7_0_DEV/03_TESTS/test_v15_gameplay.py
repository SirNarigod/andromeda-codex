import unittest,sys,tempfile,os,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v15 import IntegratedLivingEngineV15
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
class V15Gameplay(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.e=IntegratedLivingEngineV15(os.path.join(self.t.name,'w.db'),master_release_path=MASTER);r=self.e.create_world('v15g',1201,load_relationships=False);self.wid=r['world']['world_instance_id'];self.c=self.e.country(self.wid);self.n=next(x for x in self.c._all_npc_records() if x['class']=='WARRIOR')
 def tearDown(self):self.e.close();self.t.cleanup()
 def test_clock_tick_runs_orchestrator(self):
  m=self.e.movement(self.wid);st=m.state(self.n['id']);clock=self.e.runtime.get_clock(self.wid);sec=26*3600/clock['ticks_per_day'];m._save(self.n['id'],{'iso_x_m':st['iso_x_m'],'iso_y_m':st['iso_y_m'],'altitude_m':st['altitude_m'],'stamina':st['stamina'],'mode':st['mode'],'heading_deg':st['heading_deg'],'elapsed_s':sec-1});before=self.e.orchestrator.verify_run_chain(self.wid)['runs'];x=m.step_vector(self.n['id'],1,0,duration_s=2,mode='WALK',environment_factor=1);after=self.e.orchestrator.verify_run_chain(self.wid);self.assertEqual(x['status'],'PASS');self.assertGreater(after['runs'],before);self.assertEqual(after['status'],'PASS')
 def test_city_locality_clears_after_exit(self):
  n=next(x for x in self.c._all_npc_records() if x.get('city_id'));m=self.e.movement(self.wid)
  for _ in range(55):m.step_vector(n['id'],1,1,duration_s=10,mode='WALK',environment_factor=1)
  self.assertIsNone(n.get('city_id'))
 def test_bridge_changes_path(self):
  nav=self.e.navigation(self.wid);before=nav.plan_blocks('STA-05-BLK-02','STA-05-BLK-01');self.assertIn('RTE-013',before.get('canonical_route_refs',[]));b=self.c.block('STA-05-BLK-01');br=b['bridges'][0];self.c.damage_bridge(b['id'],br['id'],br['durability_max']);after=nav.plan_blocks('STA-05-BLK-02','STA-05-BLK-01');self.assertNotEqual((after.get('canonical_route_refs') or []),before.get('canonical_route_refs'))
 def test_closed_door_blocks_and_open_door_allows(self):
  pick=None
  for st in self.c.world['country']['states']:
   for b in st['blocks']:
    for city in b['cities']:
     door=next((o for o in city.get('scene_objects',[]) if o['object_type']=='DOOR' and not o.get('locked')),None);war=next((n for n in city.get('npcs',[]) if n['class']=='WARRIOR'),None)
     if door and war:pick=(door,war);break
    if pick:break
   if pick:break
  door,n=pick;sp=self.e.spatial(self.wid);m=self.e.movement(self.wid);di=sp.geodetic_to_isometric(door['coordinate_center']['longitude'],door['coordinate_center']['latitude']);g=sp.isometric_to_geodetic(di['iso_x_m']-2,di['iso_y_m']);m.sync_to_geodetic(n['id'],g,reason='TEST');self.e.streaming(self.wid).transfer(n['id'],sp.chunk_for_geodetic(g['longitude'],g['latitude'])['chunk_id']);blocked=self.e.godot(self.wid).command(n['id'],'MOVE_VECTOR',{'dx':1,'dy':0,'duration_s':1,'mode':'WALK'});self.assertEqual(blocked.get('reason'),'COLLISION_BLOCKED');op=self.e.godot(self.wid).command(n['id'],'INTERACT',{'object_id':door['id'],'action':'OPEN'});self.assertEqual(op['status'],'PASS');moved=self.e.godot(self.wid).command(n['id'],'MOVE_VECTOR',{'dx':1,'dy':0,'duration_s':1,'mode':'WALK'});self.assertEqual(moved['status'],'PASS')
 def test_dungeon_room_boundary_and_graph_move(self):
  d=next(d for st in self.c.world['country']['states'] for b in st['blocks'] for d in b.get('dungeons',[]));self.c.relocate_npc(self.n['id'],d['block_id']);en=self.e.dungeon_graph(self.wid).enter(self.n['id'],d['id']);blocked=self.e.godot(self.wid).command(self.n['id'],'MOVE_VECTOR',{'dx':1,'dy':0,'duration_s':10,'mode':'WALK'});self.assertEqual(blocked.get('reason'),'COLLISION_BLOCKED');cur=en['room_id'];edge=next(e for e in d['graph_v2']['edges'] if (e['from']==cur or e['to']==cur) and not e.get('secret'));dest=edge['to'] if edge['from']==cur else edge['from'];out=self.e.godot(self.wid).command(self.n['id'],'DUNGEON_MOVE',{'to_room_id':dest});self.assertIn(out['status'],('PASS','REJECTED'));self.assertEqual(self.e.health_v15(self.wid)['status'],'PASS')
 def test_discovery_only_current_room(self):
  d=next(d for st in self.c.world['country']['states'] for b in st['blocks'] for d in b.get('dungeons',[]));self.c.relocate_npc(self.n['id'],d['block_id']);en=self.e.dungeon_graph(self.wid).enter(self.n['id'],d['id']);self.e.discovery(self.wid).discover_nearby(self.n['id'],250);rooms=[x['feature_ref'] for x in self.e.discovery(self.wid).known(self.n['id']) if x['kind']=='DUNGEON_ROOM'];self.assertEqual(rooms,[en['room_id']])
if __name__=='__main__':unittest.main()
