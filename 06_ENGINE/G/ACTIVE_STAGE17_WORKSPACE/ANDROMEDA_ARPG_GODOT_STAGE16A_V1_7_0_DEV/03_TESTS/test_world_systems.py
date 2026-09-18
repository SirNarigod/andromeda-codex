import os, sqlite3, tempfile, threading, unittest, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'01_RUNTIME'))
from living_runtime import LivingRuntime, ValidationError, ConflictError, IntegrityError
from consequence_engine import ConsequenceEngine
from agent_brain import AgentBrain, IntentValidator
from social_memory import SocialMemorySystem
from ecology_brain import EcologySystem
from object_environment import ObjectEnvironmentSystem
from world_orchestrator import WorldSimulationOrchestrator
from world_systems import WorldSystems

MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'

class WSCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=os.path.join(self.tmp.name,'w.db')
        self.rt=LivingRuntime(self.db,master_release_path=MASTER); self.w=self.rt.create_world('s10',1010,ticks_per_day=24); self.wid=self.w['world_instance_id']
        self.val=IntentValidator(self.rt);self.brain=AgentBrain(self.rt,self.val);self.social=SocialMemorySystem(self.rt);self.eco=EcologySystem(self.rt,self.val);self.obj=ObjectEnvironmentSystem(self.rt);self.cons=ConsequenceEngine(self.rt);self.orch=WorldSimulationOrchestrator(self.rt,self.cons,self.brain,self.val,self.social,self.eco,self.obj)
        self.orch.configure_world(self.wid,{'integrity_cadence_ticks':1,'extension_budget':4,'max_roots_per_run':256})
        self.ws=WorldSystems(self.rt);self.snap=self.ws.load_master_snapshots(MASTER);self.boot=self.ws.bootstrap_world(self.wid,population_seed=1000)
    def tearDown(self):
        try:self.rt.close()
        except:pass
        self.tmp.cleanup()

class MasterSnapshotTests(WSCase):
    def test_snapshot_total(self):self.assertEqual(self.snap['total'],58)
    def test_flow_count(self):self.assertEqual(self.snap['counts']['ECONOMIC_FLOW'],7)
    def test_faction_count(self):self.assertEqual(self.snap['counts']['FACTION_INFLUENCE'],3)
    def test_population_count(self):self.assertEqual(self.snap['counts']['POPULATION_DISTRIBUTION'],14)
    def test_route_count(self):self.assertEqual(self.snap['counts']['ROUTE'],25)
    def test_snapshot_reload_idempotent(self):self.assertEqual(self.ws.load_master_snapshots(MASTER)['inserted'],0)
    def test_snapshot_trigger_immutable(self):
        with self.assertRaises(sqlite3.DatabaseError):self.rt.conn.execute("UPDATE world_system_master_snapshots SET payload_json='{}' LIMIT 1")
    def test_snapshot_hash_guard(self):
        self.rt.conn.execute('DROP TRIGGER ws_snapshot_no_update');self.rt.conn.execute("UPDATE world_system_master_snapshots SET payload_json='{}' WHERE snapshot_key='ECONOMIC_FLOW:FLOW-001'")
        with self.assertRaises(IntegrityError):self.ws._snapshots('ECONOMIC_FLOW')

class BootstrapTests(WSCase):
    def test_bootstrap_total(self):self.assertEqual(self.boot['total'],58)
    def test_route_runtime_count(self):self.assertEqual(self.ws.summary(self.wid)['routes'],34)
    def test_flow_runtime_count(self):self.assertEqual(self.ws.summary(self.wid)['flows'],7)
    def test_pop_runtime_count(self):self.assertEqual(self.ws.summary(self.wid)['populations'],14)
    def test_faction_runtime_count(self):self.assertEqual(self.ws.summary(self.wid)['factions'],3)
    def test_population_runtime_not_canon(self):self.assertEqual(self.ws._entity_for(self.wid,'POPULATION_AGGREGATE','CIT-001')['data']['runtime_seed_policy'],'NUMERIC_POPULATION_RUNTIME_ONLY_NOT_CANON')
    def test_faction_influence_not_sovereignty(self):self.assertTrue(self.ws._entity_for(self.wid,'FACTION_RUNTIME','FAC-001')['data']['influence_not_sovereignty'])
    def test_duplicate_bootstrap_blocked(self):
        with self.assertRaises(ConflictError):self.ws.bootstrap_world(self.wid)
    def test_bad_population_seed(self):
        w2=self.rt.create_world('x',2,ticks_per_day=24)
        with self.assertRaises(ValidationError):self.ws.bootstrap_world(w2['world_instance_id'],population_seed=0)
    def test_unknown_binding(self):
        from living_runtime import NotFoundError
        with self.assertRaises(NotFoundError):self.ws._entity_for(self.wid,'ROUTE_RUNTIME','RTE-999')

class EconomyTests(WSCase):
    def test_economy_tick_pass(self):self.assertEqual(self.ws.economy_tick(self.wid,'t1','FULL')['status'],'PASS')
    def test_economy_emits_event(self):
        b=self.rt.event_count(self.wid);r=self.ws.economy_tick(self.wid,'t1','FULL');self.assertEqual(self.rt.event_count(self.wid),b+1);self.assertTrue(r['event_id'])
    def test_flow_stock_nonnegative(self):
        for i in range(20):self.ws.economy_tick(self.wid,f't{i}','FULL')
        self.assertTrue(all(e['data']['stock']>=0 for e in self.ws._entities(self.wid,'ECONOMIC_FLOW')))
    def test_price_bounded(self):
        for i in range(30):self.ws.economy_tick(self.wid,f't{i}','FULL')
        for e in self.ws._entities(self.wid,'ECONOMIC_FLOW'):
            self.assertGreaterEqual(e['data']['price'],e['data']['base_price']*.5);self.assertLessEqual(e['data']['price'],e['data']['base_price']*3)
    def test_route_block_reduces_production(self):
        f=self.ws._entity_for(self.wid,'ECONOMIC_FLOW','FLOW-001');route=f['data']['route_ids'][0];self.ws.set_route_operational(self.wid,route,False);self.ws.economy_tick(self.wid,'blocked','FULL');a=self.ws._entity_for(self.wid,'ECONOMIC_FLOW','FLOW-001');self.assertEqual(a['data']['last_throughput'],15.0) # old stock still serves demand
        # after depletion, blocked path produces shortage
        for i in range(8):self.ws.economy_tick(self.wid,f'b{i}','FULL')
        a=self.ws._entity_for(self.wid,'ECONOMIC_FLOW','FLOW-001');self.assertGreater(a['data']['shortage_pressure'],0)
    def test_route_restore(self):
        self.ws.set_route_operational(self.wid,'RTE-001',False);self.assertFalse(self.ws._entity_for(self.wid,'ROUTE_RUNTIME','RTE-001')['data']['operational']);self.ws.set_route_operational(self.wid,'RTE-001',True);self.assertTrue(self.ws._entity_for(self.wid,'ROUTE_RUNTIME','RTE-001')['data']['operational'])
    def test_invalid_capacity_rejected(self):
        with self.assertRaises(ValidationError):self.ws.set_route_operational(self.wid,'RTE-001',True,capacity_factor=2)
    def test_tick_idempotent(self):
        a=self.ws.economy_tick(self.wid,'same','FULL');state=self.ws._entity_for(self.wid,'ECONOMIC_FLOW','FLOW-001');b=self.ws.economy_tick(self.wid,'same','FULL');state2=self.ws._entity_for(self.wid,'ECONOMIC_FLOW','FLOW-001');self.assertTrue(b['idempotent_replay']);self.assertEqual(state['version'],state2['version'])
    def test_offline_economy_allowed_routine(self):
        self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE');self.assertEqual(self.ws.economy_tick(self.wid,'off','ROUTINE_OFFLINE')['status'],'PASS')

class PopulationTests(WSCase):
    def test_population_tick_pass(self):self.ws.economy_tick(self.wid,'a','FULL');self.assertEqual(self.ws.population_tick(self.wid,'a','FULL')['status'],'PASS')
    def test_population_nonnegative(self):
        for i in range(100):self.ws.economy_tick(self.wid,f'e{i}','FULL');self.ws.population_tick(self.wid,f'p{i}','FULL')
        self.assertTrue(all(e['data']['count']>=0 for e in self.ws._entities(self.wid,'POPULATION_AGGREGATE')))
    def test_labor_invariant(self):
        self.ws.economy_tick(self.wid,'e','FULL');self.ws.population_tick(self.wid,'p','FULL')
        for p in self.ws._entities(self.wid,'POPULATION_AGGREGATE'):
            d=p['data'];self.assertEqual(d['employed']+d['unemployed'],d['labor_force']);self.assertLessEqual(d['labor_force'],d['count'])
    def test_offline_no_migration(self):
        self.ws.economy_tick(self.wid,'e','ROUTINE_OFFLINE');r=self.ws.population_tick(self.wid,'p','ROUTINE_OFFLINE');self.assertEqual(r['metrics']['migration'],0)
    def test_food_security_bounded(self):
        self.ws.economy_tick(self.wid,'e','FULL');self.ws.population_tick(self.wid,'p','FULL');self.assertTrue(all(0<=x['data']['food_security']<=100 for x in self.ws._entities(self.wid,'POPULATION_AGGREGATE')))
    def test_population_tick_idempotent(self):
        self.ws.economy_tick(self.wid,'x','FULL');a=self.ws.population_tick(self.wid,'x','FULL');b=self.ws.population_tick(self.wid,'x','FULL');self.assertTrue(b['idempotent_replay'])

class FactionTests(WSCase):
    def test_faction_tick_pass(self):self.ws.economy_tick(self.wid,'e','FULL');self.ws.population_tick(self.wid,'p','FULL');self.assertEqual(self.ws.faction_tick(self.wid,'f','FULL')['status'],'PASS')
    def test_influence_bounds(self):
        for i in range(30):self.ws.economy_tick(self.wid,f'e{i}','FULL');self.ws.population_tick(self.wid,f'p{i}','FULL');self.ws.faction_tick(self.wid,f'f{i}','FULL')
        self.assertTrue(all(0<=f['data']['influence']<=100 for f in self.ws._entities(self.wid,'FACTION_RUNTIME')))
    def test_offline_influence_frozen(self):
        before=[f['data']['influence'] for f in self.ws._entities(self.wid,'FACTION_RUNTIME')];self.ws.economy_tick(self.wid,'e','ROUTINE_OFFLINE');self.ws.population_tick(self.wid,'p','ROUTINE_OFFLINE');self.ws.faction_tick(self.wid,'f','ROUTINE_OFFLINE');after=[f['data']['influence'] for f in self.ws._entities(self.wid,'FACTION_RUNTIME')];self.assertEqual(before,after)
    def test_relation_create(self):self.assertEqual(self.ws.set_faction_relation(self.wid,'FAC-001','FAC-002',-30)['stance'],-30)
    def test_relation_update_integrity(self):self.ws.set_faction_relation(self.wid,'FAC-001','FAC-002',-30);self.ws.set_faction_relation(self.wid,'FAC-001','FAC-002',10);self.assertEqual(self.ws.full_integrity_check(self.wid)['status'],'PASS')
    def test_relation_bounds(self):
        with self.assertRaises(ValidationError):self.ws.set_faction_relation(self.wid,'FAC-001','FAC-002',101)
    def test_unknown_faction_rejected(self):
        from living_runtime import NotFoundError
        with self.assertRaises(NotFoundError):self.ws.set_faction_relation(self.wid,'FAC-001','FAC-999',0)

class OrchestrationTests(WSCase):
    def test_attach_extension(self):self.assertEqual(self.ws.attach_to_orchestrator(self.orch,self.wid)['extension_key'],'world_systems')
    def test_tick_runs_all_systems(self):
        self.ws.attach_to_orchestrator(self.orch,self.wid);r=self.orch.run_tick(self.wid);d=[p for p in r['phases'] if p['phase']=='EXTENSIONS'][0]['detail'];self.assertEqual(d['executed'],1);self.assertEqual(self.ws.summary(self.wid)['ticks'],3)
    def test_offline_orchestrated_routine(self):
        self.ws.attach_to_orchestrator(self.orch,self.wid);self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE');self.orch.run_tick(self.wid);self.assertEqual(self.ws.summary(self.wid)['ticks'],3)
    def test_extension_restart_requires_rebind(self):
        self.ws.attach_to_orchestrator(self.orch,self.wid);self.rt.close();self.rt=LivingRuntime(self.db,master_release_path=MASTER);self.val=IntentValidator(self.rt);self.brain=AgentBrain(self.rt,self.val);self.social=SocialMemorySystem(self.rt);self.eco=EcologySystem(self.rt,self.val);self.obj=ObjectEnvironmentSystem(self.rt);self.cons=ConsequenceEngine(self.rt);self.orch=WorldSimulationOrchestrator(self.rt,self.cons,self.brain,self.val,self.social,self.eco,self.obj);self.ws=WorldSystems(self.rt)
        with self.assertRaises(ConflictError):self.orch.run_tick(self.wid)
        self.ws.bind_to_orchestrator(self.orch,self.wid);self.assertEqual(self.orch.run_tick(self.wid)['status'],'COMPLETED')
    def test_world_system_integrity_after_orchestrator(self):self.ws.attach_to_orchestrator(self.orch,self.wid);self.orch.run_tick(self.wid);self.assertEqual(self.ws.full_integrity_check(self.wid)['status'],'PASS')

class IntegrityConcurrencyTests(WSCase):
    def test_tick_log_immutable(self):
        self.ws.economy_tick(self.wid,'x','FULL')
        with self.assertRaises(sqlite3.DatabaseError):self.rt.conn.execute("UPDATE world_system_tick_log SET result_json='{}'")
    def test_integrity_pass(self):self.assertEqual(self.ws.full_integrity_check(self.wid)['status'],'PASS')
    def test_binding_corruption_detected(self):
        row=self.rt.conn.execute("SELECT binding_id FROM world_system_bindings LIMIT 1").fetchone();self.rt.conn.execute("UPDATE world_system_bindings SET binding_hash='bad' WHERE binding_id=?",(row['binding_id'],));self.assertEqual(self.ws.full_integrity_check(self.wid)['status'],'FAIL')
    def test_parallel_unique_economy_ticks(self):
        errs=[]
        def f(i):
            try:self.ws.economy_tick(self.wid,f't{i}','FULL')
            except Exception as e:errs.append(e)
        ts=[threading.Thread(target=f,args=(i,)) for i in range(16)];[t.start() for t in ts];[t.join() for t in ts];self.assertFalse(errs);self.assertEqual(self.rt.conn.execute("SELECT COUNT(*) c FROM world_system_tick_log WHERE system_name='ECONOMY'").fetchone()['c'],16)
    def test_sqlite_integrity(self):self.assertEqual(self.rt.conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
    def test_foreign_keys(self):self.assertEqual(len(self.rt.conn.execute('PRAGMA foreign_key_check').fetchall()),0)

if __name__=='__main__':unittest.main()
