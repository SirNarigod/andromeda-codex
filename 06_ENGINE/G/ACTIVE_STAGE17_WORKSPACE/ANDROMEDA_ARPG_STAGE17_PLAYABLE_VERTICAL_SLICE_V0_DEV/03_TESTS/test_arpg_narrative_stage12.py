import os,tempfile,unittest
from integrated_arpg_engine_v12 import IntegratedARPGEngineV12
from living_runtime import ConflictError
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

class Stage12NarrativeTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.e=IntegratedARPGEngineV12(':memory:',master_release_path=MASTER);r=cls.e.create_world('s12:test',121212);cls.wid=r['world']['world_instance_id'];cls.n=cls.e.narrative_arpg(cls.wid);cls.i=cls.e.items_arpg(cls.wid);cls.m=cls.e.mobility_arpg(cls.wid);cls.t=cls.e.technology_arpg(cls.wid)
  cls.p=cls.e.arpg(cls.wid).create_profile('s12:test',origin_mode='CREATED',display_name='Narrative Tester')['profile'];cls.pref=cls.p['profile_ref']
 @classmethod
 def tearDownClass(cls): cls.e.close()
 def test_01_health(self): self.assertEqual(self.e.health_arpg_v12(self.wid)['status'],'PASS')
 def test_02_culture_identity(self): self.assertEqual(self.n.culture_profile()['culture_identity_name'],'Fronteiriços')
 def test_03_culture_count(self): self.assertEqual(len(self.n.culture_profile()['practice_refs']),26)
 def test_04_language_guard(self): self.assertIsNone(self.n.culture_profile()['official_language_ref'])
 def test_05_religion_guard(self): self.assertIsNone(self.n.culture_profile()['official_religion_ref'])
 def test_06_faction_guard(self): self.assertTrue(all(not x['territorial_control_claimed'] for x in self.n.faction_profile()))
 def test_07_spoiler_guard(self): self.assertNotIn('TIM-032',[x['canonical_ref'] for x in self.n.global_narrative_anchors(1)])
 def test_08_global_characters_not_spatialized(self): self.assertTrue(all(not x['auto_spatialize'] for x in self.n.global_narrative_anchors(1)))
 def test_09_quest_count(self): self.assertEqual(len(self.n.list_quest_templates()),5)
 def test_10_dialogue_briefs(self): self.assertEqual(len(self.n.list_dialogue_briefs()),3)
 def test_11_dialogue_not_canon_copy(self): self.assertFalse(self.n.dialogue_brief('DLG-S12-MEDIATION')['exact_dialogue_text_canonical'])
 def test_12_orientation_cycle(self):
  q='QST-S12-VARGA-ORIENTATION';self.n.accept_quest(self.pref,q,event_ref='u12:o:a');x=self.n.submit_objective(self.pref,q,'VISIT-VARGA',evidence={'canonical_ref':'CIT-001'},event_ref='u12:o:b');self.assertEqual(x['quest']['state'],'READY_TO_TURN_IN');y=self.n.turn_in_quest(self.pref,q,event_ref='u12:o:c');self.assertEqual(y['quest']['state'],'COMPLETED');self.assertEqual(y['reputation']['LOCAL_FAMILIARITY'],1)
 def test_13_bad_visit_rejected(self):
  q='QST-S12-VARGA-MEDIATION';self.n.accept_quest(self.pref,q,event_ref='u12:m:a');x=self.n.submit_objective(self.pref,q,'VISIT-MEDIATION',evidence={'canonical_ref':'POI-002'},event_ref='u12:m:bad');self.assertEqual(x['reason'],'OBJECTIVE_EVIDENCE_NOT_SATISFIED')
 def test_14_mediation_context_reputation(self):
  q='QST-S12-VARGA-MEDIATION';x=self.n.submit_objective(self.pref,q,'VISIT-MEDIATION',evidence={'canonical_ref':'POI-004'},event_ref='u12:m:ok');self.assertEqual(x['status'],'PASS');y=self.n.turn_in_quest(self.pref,q,event_ref='u12:m:turn');self.assertEqual(y['reputation']['FRONTIER_RELIABILITY'],2)
 def test_15_bridge_state_validates_objective(self):
  q='QST-S12-BRIDGE-CONTINUITY';self.n.accept_quest(self.pref,q,event_ref='u12:b:a');self.m.set_bridge_condition('POI-046',0);x=self.n.submit_objective(self.pref,q,'BRIDGE-OPERATIONAL',evidence={},event_ref='u12:b:fail');self.assertEqual(x['status'],'REJECTED');self.m.set_bridge_condition('POI-046',100);y=self.n.submit_objective(self.pref,q,'BRIDGE-OPERATIONAL',evidence={},event_ref='u12:b:ok');self.assertEqual(y['status'],'PASS')
 def test_16_inventory_objective_real_state(self):
  q='QST-S12-FRONTIER-SUPPLY';self.n.accept_quest(self.pref,q,event_ref='u12:s:a');self.i.grant_item(self.pref,'MIN-IRON',2,event_ref='u12:s:iron');x=self.n.submit_objective(self.pref,q,'HAVE-IRON',evidence={},event_ref='u12:s:obj');self.assertEqual(x['status'],'PASS')
 def test_17_technology_quest_uses_real_item(self):
  q='QST-S12-WORKSHOP-CIRCUIT';self.n.accept_quest(self.pref,q,event_ref='u12:t:a');self.i.grant_item(self.pref,'MIN-COPPER',2,event_ref='u12:t:c');self.i.grant_item(self.pref,'MIN-QUARTZ',1,event_ref='u12:t:q');m=next(x for x in self.t.list_machines() if self.t.machine_profile(x['profile_ref'])['machine_class']=='FABRICATION');self.t.run_recipe(self.pref,m['machine_ref'],'RECIPE-CIRCUIT-STAGE11',event_ref='u12:t:recipe');x=self.n.submit_objective(self.pref,q,'HAVE-CIRCUIT',evidence={},event_ref='u12:t:obj');self.assertEqual(x['status'],'PASS')
 def test_18_replay_idempotent(self):
  q='QST-S12-FRONTIER-SUPPLY';a=self.n.turn_in_quest(self.pref,q,event_ref='u12:s:turn');b=self.n.turn_in_quest(self.pref,q,event_ref='u12:s:turn');self.assertTrue(b['idempotent_replay']);self.assertEqual(a['reputation'],b['reputation'])
 def test_19_conflict_event_ref(self):
  with self.assertRaises(ConflictError): self.n.accept_quest(self.pref,'QST-S12-VARGA-ORIENTATION',event_ref='u12:s:turn')
 def test_20_verify(self): self.assertEqual(self.n.verify()['status'],'PASS')

class Stage12PersistenceTests(unittest.TestCase):
 def test_persistence_resume(self):
  with tempfile.TemporaryDirectory() as td:
   db=os.path.join(td,'s12.sqlite');e=IntegratedARPGEngineV12(db,master_release_path=MASTER);r=e.create_world('persist:s12',121213);wid=r['world']['world_instance_id'];n=e.narrative_arpg(wid);p=e.arpg(wid).create_profile('persist:s12',origin_mode='CREATED',display_name='Persist Narrative')['profile'];pref=p['profile_ref'];q='QST-S12-VARGA-ORIENTATION';n.accept_quest(pref,q,event_ref='p:a');n.submit_objective(pref,q,'VISIT-VARGA',evidence={'canonical_ref':'CIT-001'},event_ref='p:b');n.turn_in_quest(pref,q,event_ref='p:c');before=(n.quest_state(pref,q),n.reputation(pref));e.runtime.close();e2=IntegratedARPGEngineV12(db,master_release_path=MASTER);e2.resume_world(wid);n2=e2.narrative_arpg(wid);after=(n2.quest_state(pref,q),n2.reputation(pref));self.assertEqual(before,after);self.assertEqual(e2.health_arpg_v12(wid)['status'],'PASS');e2.runtime.close()
if __name__=='__main__': unittest.main(verbosity=2)
