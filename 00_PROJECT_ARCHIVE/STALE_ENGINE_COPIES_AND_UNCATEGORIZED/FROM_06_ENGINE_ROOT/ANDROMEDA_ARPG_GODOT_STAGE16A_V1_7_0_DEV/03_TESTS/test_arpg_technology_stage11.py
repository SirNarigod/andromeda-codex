import os,tempfile,unittest
from integrated_arpg_engine_v11 import IntegratedARPGEngineV11
from living_runtime import ConflictError
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

class Stage11TechnologyTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.e=IntegratedARPGEngineV11(':memory:',master_release_path=MASTER);r=cls.e.create_world('s11:test',111111);cls.wid=r['world']['world_instance_id'];cls.t=cls.e.technology_arpg(cls.wid);cls.i=cls.e.items_arpg(cls.wid)
  cls.p=cls.e.arpg(cls.wid).create_profile('s11:test',origin_mode='CREATED',display_name='Technician')['profile'];cls.pref=cls.p['profile_ref']
  for ref,qty in [('MIN-COPPER',30),('MIN-QUARTZ',30),('MIN-IRON',30),('ITEM-ENERGY-CELL',10)]: cls.i.grant_item(cls.pref,ref,qty,event_ref='setup:'+ref)
 @classmethod
 def tearDownClass(cls): cls.e.close()
 def _fab(self): return next(m for m in self.t.list_machines() if self.t.machine_profile(m['profile_ref'])['machine_class']=='FABRICATION')
 def test_01_health(self): self.assertEqual(self.e.health_arpg_v11(self.wid)['status'],'PASS')
 def test_02_workshop_canon(self): self.assertEqual(self.t.canonical_snapshot('POI-003')['territory_refs'],['TER-011'])
 def test_03_robotics_job_guard(self): self.assertEqual(self.t.canonical_snapshot('JOB-LOG-ROBOTICA-001')['territory_refs'],['TER-001'])
 def test_04_local_professions(self): self.assertIn('TER-011',self.t.canonical_snapshot('JOB-TEC-OFICINA-001')['territory_refs'])
 def test_05_machine_profiles(self): self.assertEqual(len(self.t.list_machine_profiles()),4)
 def test_06_robot_profiles(self): self.assertEqual(len(self.t.list_robot_profiles()),3)
 def test_07_workshop_bootstrap(self): self.assertGreaterEqual(len(self.t.list_machines()),3)
 def test_08_machine_inventory(self):
  m=self._fab(); self.assertEqual(self.i.inventory_snapshot(m['machine_ref'])['owner_kind'],'MACHINE_STORAGE')
 def test_09_recipe_production(self):
  m=self._fab(); before=self.i.inventory_snapshot(self.pref)['stacks'].get('ITEM-CIRCUIT',0);o=self.t.run_recipe(self.pref,m['machine_ref'],'RECIPE-CIRCUIT-STAGE11',event_ref='u:recipe');self.assertEqual(o['status'],'PASS');self.assertEqual(self.i.inventory_snapshot(self.pref)['stacks'].get('ITEM-CIRCUIT',0),before+1)
 def test_10_recipe_replay(self):
  m=self._fab(); a=self.t.run_recipe(self.pref,m['machine_ref'],'RECIPE-CIRCUIT-STAGE11',event_ref='u:replay');b=self.t.run_recipe(self.pref,m['machine_ref'],'RECIPE-CIRCUIT-STAGE11',event_ref='u:replay');self.assertTrue(b['idempotent_replay']);self.assertEqual(a['outputs'],b['outputs'])
 def test_11_machine_wear(self):
  m=self._fab(); before=m['integrity']; self.t.run_recipe(self.pref,m['machine_ref'],'RECIPE-CIRCUIT-STAGE11',event_ref='u:wear');self.assertLess(self.t.machine(m['machine_ref'])['integrity'],before)
 def test_12_recharge_machine(self):
  m=self._fab(); mm=self.t.machine(m['machine_ref']);mm['energy']=1;self.t._save_machine(mm);o=self.t.recharge_machine(self.pref,m['machine_ref'],1,event_ref='u:mcharge');self.assertEqual(o['status'],'PASS');self.assertGreater(o['machine']['energy'],1)
 def test_13_repair_machine(self):
  m=self._fab();mm=self.t.machine(m['machine_ref']);mm['integrity']=20;self.t._save_machine(mm);o=self.t.repair_machine(self.pref,m['machine_ref'],1,event_ref='u:repair');self.assertEqual(o['status'],'PASS');self.assertGreater(o['machine']['integrity'],20)
 def test_14_create_robot(self):
  o=self.t.create_robot(self.pref,'RBT-PROFILE-LOGISTICS',event_ref='u:rbt');r=o['robot'];self.assertEqual(r['legal_status'],'TECHNOLOGICAL_ASSET_NOT_NPC_NOT_LEGAL_WORKER');self.assertEqual(self.i.inventory_snapshot(r['robot_ref'])['owner_kind'],'ROBOT_CARGO')
 def test_15_robot_actor_projection(self):
  r=self.t.create_robot(self.pref,'RBT-PROFILE-FIELD-SERVICE',event_ref='u:rbtactor')['robot'];a=self.e.actors_arpg(self.wid).ensure_actor(r['robot_ref']);self.assertEqual(a['actor_role'],'ROBOT');self.assertEqual(a['source_kind'],'TECH_ASSET')
 def test_16_robot_transfer(self):
  r=self.t.create_robot(self.pref,'RBT-PROFILE-HAULER',event_ref='u:rbtxfer')['robot'];before=self.i.inventory_snapshot(r['robot_ref'])['stacks'].get('MIN-IRON',0);o=self.t.robot_task_transfer(self.pref,r['robot_ref'],self.pref,r['robot_ref'],'MIN-IRON',2,event_ref='u:task');self.assertEqual(o['status'],'PASS');self.assertEqual(self.i.inventory_snapshot(r['robot_ref'])['stacks'].get('MIN-IRON',0),before+2)
 def test_17_robot_owner_guard(self):
  r=self.t.create_robot(self.pref,'RBT-PROFILE-LOGISTICS',event_ref='u:guardr')['robot'];p2=self.e.arpg(self.wid).create_profile('s11:other',origin_mode='CREATED',display_name='Other')['profile'];o=self.t.robot_task_transfer(p2['profile_ref'],r['robot_ref'],self.pref,r['robot_ref'],'MIN-IRON',1,event_ref='u:guard');self.assertEqual(o['reason'],'ROBOT_OPERATOR_MISMATCH')
 def test_18_vehicle_energy_binding(self):
  v=self.e.mobility_arpg(self.wid).create_vehicle(self.pref,'VEH-PROFILE-SERVICE-LIGHT',event_ref='u:veh')['vehicle'];o=self.t.bind_vehicle_energy(v['vehicle_ref'],event_ref='u:vebind');self.assertEqual(o['vehicle']['stage11_energy_contract']['canonical_source_type'],'UNSPECIFIED_BY_TER_011_CANON')
 def test_19_deterministic_machine_refs(self):
  a=self.t._stable_ref('MACH-',self.t.WORKSHOP_REF,'MACH-PROFILE-FABRICATOR');b=self.t._stable_ref('MACH-',self.t.WORKSHOP_REF,'MACH-PROFILE-FABRICATOR');self.assertEqual(a,b);self.assertNotIn(self.wid,a)
 def test_20_verify(self): self.assertEqual(self.t.verify()['status'],'PASS')

class Stage11PersistenceTests(unittest.TestCase):
 def test_persistence_resume(self):
  with tempfile.TemporaryDirectory() as td:
   db=os.path.join(td,'s11.sqlite');e=IntegratedARPGEngineV11(db,master_release_path=MASTER);r=e.create_world('persist:s11',111112);wid=r['world']['world_instance_id'];t=e.technology_arpg(wid);i=e.items_arpg(wid);p=e.arpg(wid).create_profile('persist:s11',origin_mode='CREATED',display_name='Persist Tech')['profile'];pref=p['profile_ref'];i.grant_item(pref,'MIN-COPPER',5,event_ref='p:c');i.grant_item(pref,'MIN-QUARTZ',5,event_ref='p:q');rb=t.create_robot(pref,'RBT-PROFILE-LOGISTICS',event_ref='p:r')['robot'];m=next(x for x in t.list_machines() if t.machine_profile(x['profile_ref'])['machine_class']=='FABRICATION');t.run_recipe(pref,m['machine_ref'],'RECIPE-CIRCUIT-STAGE11',event_ref='p:rec');before=(t.robot(rb['robot_ref']),t.machine(m['machine_ref']),i.inventory_snapshot(pref));e.runtime.close();e2=IntegratedARPGEngineV11(db,master_release_path=MASTER);e2.resume_world(wid);t2=e2.technology_arpg(wid);after=(t2.robot(rb['robot_ref']),t2.machine(m['machine_ref']),e2.items_arpg(wid).inventory_snapshot(pref));self.assertEqual(before,after);self.assertEqual(e2.health_arpg_v11(wid)['status'],'PASS');e2.runtime.close()
if __name__=='__main__':unittest.main(verbosity=2)
