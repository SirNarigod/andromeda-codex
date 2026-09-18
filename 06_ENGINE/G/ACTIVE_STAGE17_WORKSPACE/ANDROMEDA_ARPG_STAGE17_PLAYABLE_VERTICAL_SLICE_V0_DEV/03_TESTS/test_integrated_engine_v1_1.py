import hashlib, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'01_RUNTIME'))

from integrated_engine import IntegratedLivingEngineV11

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
MASTER_SHA='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2'

class IntegratedV11(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=os.path.join(self.tmp.name,'integrated.db')
        self.engine=IntegratedLivingEngineV11(self.db,master_release_path=MASTER)
        self.report=self.engine.create_world('integrated-test',2201,population_reference_seed=1000,load_relationships=False)
        self.wid=self.report['world']['world_instance_id']
    def tearDown(self):
        try:self.engine.close()
        except:pass
        self.tmp.cleanup()
    def test_composition_shares_runtime_and_domain_hub(self):
        e=self.engine
        self.assertIs(e.combat.domain_hub,e.domain_hub);self.assertIs(e.mobility.domain_hub,e.domain_hub);self.assertIs(e.society.domain_hub,e.domain_hub)
        self.assertTrue(all(x.runtime is e.runtime for x in [e.world_systems,e.commerce,e.combat,e.mobility,e.society,e.ecology,e.social,e.orchestrator,e.long_horizon]))
    def test_contextual_bootstrap_replaces_uniform_runtime_seeds(self):
        flows=self.engine.world_systems._entities(self.wid,'ECONOMIC_FLOW');pops=self.engine.world_systems._entities(self.wid,'POPULATION_AGGREGATE');facs=self.engine.world_systems._entities(self.wid,'FACTION_RUNTIME')
        self.assertGreater(len({f['data']['base_price'] for f in flows}),1);self.assertGreater(len({p['data']['count'] for p in pops}),1);self.assertGreater(len({f['data']['treasury'] for f in facs}),1)
        self.assertTrue(all('CONTEXTUAL_V1_1' in x['data']['runtime_seed_policy'] for x in flows+pops+facs))
    def test_catalogs_and_master_snapshots_load(self):
        self.assertEqual(self.report['commerce']['count'],30);self.assertEqual(self.report['professions']['count'],91);self.assertEqual(self.report['master_snapshots']['counts']['ECONOMIC_FLOW'],7);self.assertEqual(self.report['master_snapshots']['counts']['POPULATION_DISTRIBUTION'],14)
    def test_expected_extensions_are_registered(self):
        rows=self.engine.runtime.conn.execute("SELECT extension_key FROM orchestration_extension_descriptors WHERE world_instance_id=? ORDER BY extension_key",(self.wid,)).fetchall();self.assertEqual([r['extension_key'] for r in rows],['mobility_biology','society_labor','world_systems'])
    def test_bootstrap_health_gate_passes(self):
        self.assertEqual(self.report['health']['status'],'PASS',self.report['health']['failures']);self.assertEqual(self.engine.health.snapshot(self.wid)['status'],'PASS')
    def test_one_active_day_remains_healthy(self):
        r=self.engine.active_steps(self.wid,24);self.assertEqual(r['status'],'PASS',r['health']['failures']);self.assertEqual((r['clock']['day'],r['clock']['tick']),(1,0))
    def test_thirty_offline_days_reconcile_healthy(self):
        r=self.engine.offline_days(self.wid,30,request_key='integrated-30');self.assertEqual(r['status'],'PASS',r['health']['failures']);c=self.engine.runtime.get_clock(self.wid);self.assertEqual((c['day'],c['tick']),(30,0));self.assertEqual(r['reconciliation']['status'],'PASS')
    def test_master_is_unchanged(self):
        self.assertEqual(hashlib.sha256(Path(MASTER).read_bytes()).hexdigest(),MASTER_SHA)

class IntegratedV11Relationships(unittest.TestCase):
    def test_full_relationship_registry_loads_read_only(self):
        tmp=tempfile.TemporaryDirectory();e=IntegratedLivingEngineV11(os.path.join(tmp.name,'rels.db'),master_release_path=MASTER)
        try:
            r=e.create_world('integrated-relations',2202,load_relationships=True);self.assertEqual(r['relationships']['source_count'],9429);self.assertEqual(r['relationships']['inserted'],9429);self.assertEqual(r['health']['status'],'PASS')
        finally:e.close();tmp.cleanup()

if __name__=='__main__':unittest.main()
