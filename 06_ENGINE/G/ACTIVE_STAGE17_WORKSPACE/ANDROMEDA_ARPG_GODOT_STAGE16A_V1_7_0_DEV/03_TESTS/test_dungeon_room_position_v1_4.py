import unittest,sys,tempfile,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v14 import IntegratedLivingEngineV14
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
class RoomPosition(unittest.TestCase):
 def test_npc_position_tracks_current_room(self):
  with tempfile.TemporaryDirectory() as td:
   e=IntegratedLivingEngineV14(os.path.join(td,'w.db'),master_release_path=MASTER)
   try:
    r=e.create_world('room',1201,load_relationships=False);w=r['world']['world_instance_id'];c=e.country(w);dg=e.dungeon_graph(w);sp=e.spatial(w);stream=e.streaming(w);d=next(d for st in c.world['country']['states'] for b in st['blocks'] for d in b.get('dungeons',[]));n=next(x for x in c._all_npc_records() if x['class']=='WARRIOR');stream.travel_npc(n['id'],d['block_id'],speed_kmh=1200);x=dg.enter(n['id'],d['id']);g=d['graph_v2'];cur=x['room_id'];edge=next(e for e in g['edges'] if not e.get('locked') and not e.get('secret') and (e['from']==cur or e['to']==cur));dest=edge['to'] if edge['from']==cur else edge['from'];m=dg.move(n['id'],d['id'],dest);self.assertEqual(m['status'],'PASS');room=next(r for r in g['rooms'] if r['id']==dest);p=sp.point_for_npc(n);self.assertAlmostEqual(p['longitude'],room['coordinate_center']['longitude'],places=8);self.assertAlmostEqual(p['latitude'],room['coordinate_center']['latitude'],places=8);expected=sp.chunk_for_geodetic(p['longitude'],p['latitude'])['chunk_id'];self.assertEqual(stream.owners[n['id']],expected)
   finally:e.close()
if __name__=='__main__':unittest.main()
