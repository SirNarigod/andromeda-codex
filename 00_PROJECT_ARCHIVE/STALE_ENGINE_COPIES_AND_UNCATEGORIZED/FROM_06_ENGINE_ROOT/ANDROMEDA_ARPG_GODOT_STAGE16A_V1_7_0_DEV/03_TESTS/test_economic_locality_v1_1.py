import os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'01_RUNTIME'))
from living_runtime import LivingRuntime, new_runtime_id, clock_point
from world_systems import WorldSystems

MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'

class EconomicLocalityV11Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=os.path.join(self.tmp.name,'e.db')
        self.rt=LivingRuntime(self.db,master_release_path=MASTER)
        self.w=self.rt.create_world('econ-locality',1101,ticks_per_day=24); self.wid=self.w['world_instance_id']
        self.ws=WorldSystems(self.rt); self.snap=self.ws.load_master_snapshots(MASTER); self.ws.bootstrap_world(self.wid,population_seed=1000)
    def tearDown(self):
        try:self.rt.close()
        except:pass
        self.tmp.cleanup()
    def _set(self, ent, path, value, key):
        w=self.rt.get_world(self.wid); c=w['clock_state']
        a={'action_id':new_runtime_id('action'),'intent_id':new_runtime_id('intent'),'world_instance_id':self.wid,'timeline_id':w['timeline_id'],'actor_ref':'SYSTEM_RECONCILIATION','action_type':'TEST_SET','parameters':{},'precondition_snapshot':{'entity_versions':{ent['entity_runtime_id']:ent['version']}},'idempotency_key':key,'created_at':clock_point(c['day'],c['tick']),'status':'SCHEDULED','source':'TEST','execution_class':'ROUTINE_SAFE'}
        return self.rt.apply_action(self.wid,a,[{'target_ref':ent['entity_runtime_id'],'operation':'SET','field_path':path,'value':value,'priority':0,'kind':'DIRECT'}])
    def test_original_snapshot_contract_preserved(self):
        self.assertEqual(self.snap['total'],58)
        self.assertGreater(self.snap['auxiliary_total'],0)
    def test_all_flow_destinations_resolve_population(self):
        results=[]
        for f in self.ws._entities(self.wid,'ECONOMIC_FLOW'):
            r=self.ws.resolve_destination_population(self.wid,f['data']['destination_id']); results.append(r)
        self.assertEqual(len(results),7)
        self.assertTrue(all(r['status']=='RESOLVED' for r in results),results)
        self.assertTrue(all(r['method'] in {'DIRECT_SETTLEMENT','DESTINATION_TERRITORY'} for r in results))
    def test_flow_003_is_technology(self):
        f=self.ws._entity_for(self.wid,'ECONOMIC_FLOW','FLOW-003')
        self.assertEqual(f['data']['product_category'],'TECHNOLOGY')
    def test_technology_shortage_does_not_reduce_food_security(self):
        flow=self.ws._entity_for(self.wid,'ECONOMIC_FLOW','FLOW-003')
        self._set(flow,'data.shortage_pressure',100.0,'set-tech-shortage')
        self.ws.population_tick(self.wid,'population-after-tech-shortage','FULL')
        foods={p['data']['settlement_ref']:p['data']['food_security'] for p in self.ws._entities(self.wid,'POPULATION_AGGREGATE')}
        self.assertTrue(all(v==100.0 for v in foods.values()),foods)
    def test_food_shortage_is_local_when_local_food_flow_exists(self):
        flow=self.ws._entity_for(self.wid,'ECONOMIC_FLOW','FLOW-001')
        self._set(flow,'data.shortage_pressure',100.0,'set-food-shortage')
        self.ws.population_tick(self.wid,'population-after-food-shortage','FULL')
        varga=self.ws._entity_for(self.wid,'POPULATION_AGGREGATE','CIT-001')
        self.assertEqual(varga['data']['territory_ref'],'TER-011')
        self.assertEqual(varga['data']['food_security'],0.0)
        # At least one settlement outside TER-011 should remain unaffected by the local food shortage.
        others=[p for p in self.ws._entities(self.wid,'POPULATION_AGGREGATE') if p['data'].get('territory_ref')!='TER-011']
        self.assertTrue(any(p['data']['food_security']==100.0 for p in others))
    def test_location_snapshot_integrity(self):
        self.assertEqual(self.ws.full_integrity_check(self.wid)['status'],'PASS')

if __name__=='__main__':unittest.main()
