import os,tempfile,unittest,copy
from integrated_arpg_engine_v14 import IntegratedARPGEngineV14
from living_runtime import ConflictError
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

class Stage14LivingIntegrationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.e=IntegratedARPGEngineV14(':memory:',master_release_path=MASTER);r=cls.e.create_world('s14:test',141414);cls.wid=r['world']['world_instance_id'];cls.l=cls.e.living_arpg(cls.wid);cls.m=cls.e.mobility_arpg(cls.wid);cls.ec=cls.e.economy_arpg(cls.wid);cls.t=cls.e.technology_arpg(cls.wid);cls.g=cls.e.gathering_arpg(cls.wid);cls.baseline_snapshot=copy.deepcopy(cls.l.snapshot())
 @classmethod
 def tearDownClass(cls): cls.e.close()
 def test_01_health(self): self.assertEqual(self.e.health_arpg_v14(self.wid)['status'],'PASS')
 def test_02_living_bridge_present(self):
  x=self.l.run_cycle('u14:bridge',apply_consequences=False)['living_runtime_bridge'];self.assertEqual(x['consequence_engine'],'ConsequenceEngine');self.assertEqual(x['world_orchestrator'],'WorldSimulationOrchestrator')
 def test_03_metric_bounds(self):
  s=self.l.snapshot();self.assertEqual(len(s['metrics']),10);self.assertTrue(all(0<=v<=1 for v in s['metrics'].values()))
 def test_04_resource_all_activities(self):
  d=self.l.snapshot()['detail']['resources'];self.assertEqual(set(d),{'MINING','LOGGING','FORAGING','AGRICULTURE','HUNTING','FISHING'})
 def test_05_labor_lazy_guard(self): self.assertTrue(self.l.snapshot()['detail']['labor']['lazy_materialization_guard'])
 def test_06_canon_guard(self): self.assertFalse(self.l.snapshot()['canonical_mutation'])
 def test_07_bridge_disruption_signal(self):
  self.m.set_bridge_condition('POI-046',0);x=self.l.run_cycle('u14:broken');types={s['signal_type'] for s in x['cycle']['signals']};self.assertIn('INFRASTRUCTURE_DISRUPTION',types);self.assertLess(x['cycle']['snapshot']['metrics']['infrastructure_resilience'],0.85)
 def test_08_bridge_creates_opportunity_not_canon(self):
  ops=self.l.list_opportunities('u14:broken');o=next(x for x in ops if x['opportunity_type']=='INFRASTRUCTURE_RESPONSE');self.assertFalse(o['canonical_event']);self.assertFalse(o['quest_template_auto_created'])
 def test_09_bridge_affects_market_over_time(self):
  row=self.ec._market_row('POI-002','ITEM-GRAIN');before=float(row['demand_index']);self.l.run_cycle('u14:broken2');after=float(self.ec._market_row('POI-002','ITEM-GRAIN')['demand_index']);self.assertGreater(after,before)
 def test_10_cycle_replay_idempotent(self):
  a=self.l.run_cycle('u14:replay');mid=float(self.ec._market_row('POI-002','ITEM-GRAIN')['demand_index']);b=self.l.run_cycle('u14:replay');after=float(self.ec._market_row('POI-002','ITEM-GRAIN')['demand_index']);self.assertTrue(b['idempotent_replay']);self.assertEqual(mid,after)
 def test_11_event_conflict(self):
  with self.assertRaises(ConflictError):self.l.run_cycle('u14:replay',apply_consequences=False)
 def test_12_machine_degradation_signal(self):
  mach=self.t.list_machines()[0];x=self.t.machine(mach['machine_ref']);x['integrity']=10;x['energy']=1;self.t._save_machine(x);c=self.l.run_cycle('u14:machine');self.assertIn('PRODUCTION_SLOWDOWN',{s['signal_type'] for s in c['cycle']['signals']})
 def test_13_ecology_depletion_signal(self):
  f=self.g.list_nodes(activity_type='FISHING')[0];
  with self.e.runtime._write_lock:self.e.runtime.conn.execute('UPDATE arpg_gathering_runtime_state SET remaining_units=0 WHERE world_instance_id=? AND node_ref=?',(self.wid,f['node_ref']))
  c=self.l.run_cycle('u14:eco');self.assertLess(c['cycle']['snapshot']['metrics']['ecological_resilience'],1.0)
 def test_14_recovery(self):
  self.m.set_bridge_condition('POI-046',100);mach=self.t.list_machines()[0];x=self.t.machine(mach['machine_ref']);p=self.t.machine_profile(x['profile_ref']);x['integrity']=p['integrity_max'];x['energy']=p['energy_max'];self.t._save_machine(x);c=self.l.run_cycle('u14:recover');self.assertGreater(c['cycle']['snapshot']['metrics']['infrastructure_resilience'],0.99)
 def test_15_causal_trace(self):
  tr=self.l.causal_trace('u14:broken');self.assertIn('causes',tr);self.assertIn('effects',tr);self.assertFalse(tr['canonical_mutation'])
 def test_16_orchestrator_advance(self):
  x=self.l.advance_and_reconcile('u14:advance',living_steps=1,apply_consequences=False);self.assertEqual(x['status'],'PASS');self.assertEqual(x['living_steps']['steps'],1)
 def test_17_determinism_same_seed(self):
  e2=IntegratedARPGEngineV14(':memory:',master_release_path=MASTER);w2=e2.create_world('s14:det',141414)['world']['world_instance_id'];a=copy.deepcopy(self.baseline_snapshot);b=copy.deepcopy(e2.living_arpg(w2).snapshot());a.pop('world_instance_id',None);b.pop('world_instance_id',None);self.assertEqual(a['metrics'],b['metrics']);self.assertEqual(a['detail'],b['detail']);e2.close()
 def test_18_population_faction_governance_guards(self):
  s=self.l.snapshot();self.assertIn('population_welfare',s['metrics']);self.assertIn('faction_stability',s['metrics']);self.assertIn('governance_stability',s['metrics']);self.assertFalse(s['detail']['factions']['sovereignty_claimed']);self.assertIn('guard',s['detail']['governance'])
 def test_19_verify(self): self.assertEqual(self.l.verify()['status'],'PASS')

class Stage14PersistenceTests(unittest.TestCase):
 def test_persistence_resume(self):
  with tempfile.TemporaryDirectory() as td:
   db=os.path.join(td,'s14.sqlite');e=IntegratedARPGEngineV14(db,master_release_path=MASTER);r=e.create_world('persist:s14',141415);wid=r['world']['world_instance_id'];l=e.living_arpg(wid);e.mobility_arpg(wid).set_bridge_condition('POI-046',0);before=l.run_cycle('p14:c');cycle=before['cycle'];signals=l.list_signals('p14:c');e.runtime.close();e2=IntegratedARPGEngineV14(db,master_release_path=MASTER);e2.resume_world(wid);l2=e2.living_arpg(wid);self.assertEqual(cycle,l2.cycle('p14:c'));self.assertEqual(signals,l2.list_signals('p14:c'));self.assertEqual(e2.health_arpg_v14(wid)['status'],'PASS');e2.runtime.close()
if __name__=='__main__':unittest.main(verbosity=2)
