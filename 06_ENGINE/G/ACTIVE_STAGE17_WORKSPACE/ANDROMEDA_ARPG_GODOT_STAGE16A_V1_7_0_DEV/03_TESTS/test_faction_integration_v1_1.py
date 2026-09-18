import os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'01_RUNTIME'))
from living_runtime import LivingRuntime
from world_systems import WorldSystems

MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'

class FactionIntegrationV11Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=os.path.join(self.tmp.name,'f.db')
        self.rt=LivingRuntime(self.db,master_release_path=MASTER); self.ws=WorldSystems(self.rt); self.ws.load_master_snapshots(MASTER)
    def tearDown(self):
        try:self.rt.close()
        except:pass
        self.tmp.cleanup()

    def _world(self, owner):
        w=self.rt.create_world(owner,6100+len(owner),ticks_per_day=24); wid=w['world_instance_id']
        self.ws.bootstrap_world(wid,population_seed=1000)
        self.ws.economy_tick(wid,'e','FULL'); self.ws.population_tick(wid,'p','FULL')
        return wid

    def test_faction_context_uses_canonical_local_scope(self):
        wid=self._world('locality')
        ctx=self.ws.faction_runtime_context(wid,'FAC-002')
        self.assertEqual(ctx['territory_ref'],'TER-003')
        self.assertGreater(ctx['economic_activity'],0)
        self.assertTrue(ctx['economic_flow_refs'])
        for pref in ctx['population_refs']:
            self.assertEqual(self.ws._entity_for(wid,'POPULATION_AGGREGATE',pref)['data']['territory_ref'],'TER-003')
        self.assertEqual(ctx['authority'],'RUNTIME_CONTEXT_FROM_CANON_SCOPE_NOT_SOVEREIGNTY')

    def test_hostile_relation_reduces_runtime_outcome_vs_identical_neutral_world(self):
        neutral=self._world('neutral'); hostile=self._world('hostile')
        self.ws.set_faction_relation(hostile,'FAC-001','FAC-002',-100)
        self.ws.faction_tick(neutral,'f','FULL'); self.ws.faction_tick(hostile,'f','FULL')
        n=self.ws._entity_for(neutral,'FACTION_RUNTIME','FAC-001')['data']; h=self.ws._entity_for(hostile,'FACTION_RUNTIME','FAC-001')['data']
        self.assertEqual(n['last_faction_context']['diplomatic_stance'],0.0)
        self.assertEqual(h['last_faction_context']['diplomatic_stance'],-100.0)
        self.assertLess(h['last_faction_context']['trade_factor'],n['last_faction_context']['trade_factor'])
        self.assertLess(h['treasury'],n['treasury']); self.assertLess(h['security'],n['security']); self.assertLess(h['stability'],n['stability'])

    def test_friendly_relation_improves_runtime_outcome_vs_identical_neutral_world(self):
        neutral=self._world('neutral2'); friendly=self._world('friendly')
        self.ws.set_faction_relation(friendly,'FAC-001','FAC-002',100)
        self.ws.faction_tick(neutral,'f','FULL'); self.ws.faction_tick(friendly,'f','FULL')
        n=self.ws._entity_for(neutral,'FACTION_RUNTIME','FAC-001')['data']; f=self.ws._entity_for(friendly,'FACTION_RUNTIME','FAC-001')['data']
        self.assertGreater(f['last_faction_context']['trade_factor'],n['last_faction_context']['trade_factor'])
        self.assertGreater(f['treasury'],n['treasury']); self.assertGreater(f['security'],n['security']); self.assertGreater(f['stability'],n['stability'])
        self.assertTrue(f['influence_not_sovereignty'])

if __name__=='__main__': unittest.main()
