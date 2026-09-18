import unittest,sys,tempfile,os,math,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v15 import IntegratedLivingEngineV15
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'

class V15SecurityPersistence(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(); self.db=os.path.join(self.t.name,'w.db')
        self.e=IntegratedLivingEngineV15(self.db,master_release_path=MASTER)
        r=self.e.create_world('v15sec',1201,load_relationships=False); self.wid=r['world']['world_instance_id']; self.c=self.e.country(self.wid)
        self.n=next(x for x in self.c._all_npc_records() if x['class']=='WARRIOR')
    def tearDown(self):
        try:self.e.close()
        except Exception:pass
        self.t.cleanup()
    def test_godot_payload_npc_uses_exact_motion_transform(self):
        g=self.e.godot(self.wid); self.assertEqual(g.bind_session('S1',self.n['id'])['status'],'PASS')
        for _ in range(10):
            self.assertEqual(g.client_command('S1','MOVE_VECTOR',{'dx':1,'dy':0,'duration_s':2,'mode':'RUN'})['status'],'PASS')
        s=g.client_snapshot('S1'); self.assertEqual(s['status'],'PASS')
        ents=[x for x in s['chunk']['entities'] if x.get('entity_ref')==self.n['id']]; self.assertEqual(len(ents),1)
        self.assertLess(abs(ents[0]['isometric']['x_m']-s['transform']['iso_x_m']),0.001)
        self.assertLess(abs(ents[0]['isometric']['y_m']-s['transform']['iso_y_m']),0.001)
    def test_undiscovered_dungeon_is_redacted_even_in_same_chunk(self):
        d=next(d for st in self.c.world['country']['states'] for b in st['blocks'] for d in b.get('dungeons',[]))
        sp=self.e.spatial(self.wid); m=self.e.movement(self.wid)
        m.sync_to_geodetic(self.n['id'],d['coordinate_center'],reason='SECURITY_FIXTURE')
        ch=sp.chunk_for_geodetic(d['coordinate_center']['longitude'],d['coordinate_center']['latitude'])['chunk_id']; self.e.streaming(self.wid).transfer(self.n['id'],ch)
        snap=self.e.godot(self.wid).snapshot(self.n['id']); refs={x.get('entity_ref') for x in snap['chunk']['entities']}
        self.assertNotIn(d['id'],refs)
        for r in d['graph_v2']['rooms']: self.assertNotIn(r['id'],refs)
    def test_player_remains_visible_in_own_discovered_dungeon_room(self):
        d=next(d for st in self.c.world['country']['states'] for b in st['blocks'] for d in b.get('dungeons',[]))
        self.c.relocate_npc(self.n['id'],d['block_id']); en=self.e.dungeon_graph(self.wid).enter(self.n['id'],d['id']); self.assertEqual(en['status'],'PASS')
        snap=self.e.godot(self.wid).snapshot(self.n['id']); refs=[x.get('entity_ref') for x in snap['chunk']['entities']]
        self.assertIn(self.n['id'],refs); self.assertIn(en['room_id'],{x['feature_ref'] for x in self.e.discovery(self.wid).known(self.n['id'])})
    def test_discovery_hash_corruption_is_detected(self):
        d=next(d for st in self.c.world['country']['states'] for b in st['blocks'] for d in b.get('dungeons',[]))
        self.e.discovery(self.wid).discover(self.n['id'],d['id'],'DUNGEON')
        self.e.runtime.conn.execute("UPDATE v15_player_discovery SET payload_hash='BAD' WHERE world_instance_id=? AND player_ref=? AND feature_ref=?",(self.wid,self.n['id'],d['id']))
        h=self.e.health_v15(self.wid); self.assertEqual(h['status'],'FAIL'); self.assertTrue(any('DISCOVERY_HASH' in x for x in h['failures']))
    def test_session_survives_process_resume_and_revoke_fails_closed(self):
        g=self.e.godot(self.wid); self.assertEqual(g.bind_session('SRES',self.n['id'])['status'],'PASS')
        before=self.e.movement(self.wid).state(self.n['id']); self.assertEqual(g.client_command('SRES','MOVE_VECTOR',{'dx':1,'dy':0,'duration_s':2,'mode':'WALK'})['status'],'PASS'); moved=self.e.movement(self.wid).state(self.n['id'])
        self.e.close(); self.e=IntegratedLivingEngineV15(self.db,master_release_path=MASTER); r=self.e.resume_world(self.wid); self.assertEqual(r['status'],'PASS')
        resumed=self.e.movement(self.wid).state(self.n['id']); self.assertAlmostEqual(resumed['iso_x_m'],moved['iso_x_m'],places=6); self.assertEqual(self.e.godot(self.wid).client_snapshot('SRES')['status'],'PASS')
        self.assertEqual(self.e.godot(self.wid).revoke_session('SRES')['status'],'PASS'); self.assertEqual(self.e.godot(self.wid).client_command('SRES','MOVE_VECTOR',{'dx':1,'dy':0,'duration_s':1})['status'],'REJECTED')
    def test_environment_changes_with_world_clock(self):
        b=self.n['block_id']; a=self.e.environment(self.wid).state_for_block(b); self.e.orchestrator.run_steps(self.wid,1); z=self.e.environment(self.wid).state_for_block(b)
        self.assertNotEqual(a['clock'],z['clock']); self.assertNotEqual((a['temperature_c'],a['wind_mps'],a['daylight']),(z['temperature_c'],z['wind_mps'],z['daylight']))

if __name__=='__main__': unittest.main()
