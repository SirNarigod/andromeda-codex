import sys,tempfile,hashlib,json,os,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v14 import IntegratedLivingEngineV14
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
class ResumeTests(unittest.TestCase):
 def test_process_restart_rehydrates_same_world_and_streaming(self):
  fd,path=tempfile.mkstemp(suffix='.sqlite');os.close(fd)
  try:
   e=IntegratedLivingEngineV14(path,master_release_path=MASTER);r=e.create_world('resume',7301,load_relationships=False);wid=r['world']['world_instance_id'];c=e.country(wid);st=e.streaming(wid);dg=e.dungeon_graph(wid)
   actor=next(n for n in c._all_npc_records() if n['class'] in ('WARRIOR','MERCENARY','MAGE'))
   blocks=[b for s in c.world['country']['states'] for b in s['blocks']];d=next(d for b in blocks for d in b.get('dungeons',[]))
   self.assertEqual(st.travel_npc(actor['id'],d['block_id'],speed_kmh=1200)['status'],'PASS');self.assertEqual(dg.enter(actor['id'],d['id'])['status'],'PASS')
   g=d['graph_v2'];cur=c.npc(actor['id'])['dungeon_room_id'];edge=next((x for x in g['edges'] if x['from']==cur and not x['locked'] and not x['secret']),None)
   if edge:self.assertEqual(dg.move(actor['id'],d['id'],edge['to'])['status'],'PASS')
   before_country=digest(c.world);before_owner=st.owners[actor['id']];before_clock=e.runtime.get_clock(wid);before_room=c.npc(actor['id']).get('dungeon_room_id');before_events=e.runtime.event_count(wid);e.close()
   e2=IntegratedLivingEngineV14(path,master_release_path=MASTER);out=e2.resume_world(wid);c2=e2.country(wid);st2=e2.streaming(wid)
   self.assertEqual(out['status'],'PASS');self.assertTrue(out['identity_preserved']);self.assertFalse(out['new_world_created']);self.assertEqual(out['world_instance_id'],wid)
   self.assertEqual(digest(c2.world),before_country);self.assertEqual(st2.owners[actor['id']],before_owner);self.assertEqual(e2.runtime.get_clock(wid),before_clock);self.assertEqual(c2.npc(actor['id']).get('dungeon_room_id'),before_room);self.assertEqual(e2.runtime.event_count(wid),before_events)
   self.assertEqual(st2.full_integrity_check()['status'],'PASS');self.assertEqual(e2.health_v14(wid)['status'],'PASS')
   # prove resumed adapters are executable, not merely reconstructed metadata
   rr=e2.orchestrator.run_steps(wid,1);self.assertEqual(len(rr),1);self.assertEqual(e2.health_v14(wid)['status'],'PASS');e2.close()
  finally:
   try:os.unlink(path)
   except FileNotFoundError:pass
if __name__=='__main__':unittest.main()
