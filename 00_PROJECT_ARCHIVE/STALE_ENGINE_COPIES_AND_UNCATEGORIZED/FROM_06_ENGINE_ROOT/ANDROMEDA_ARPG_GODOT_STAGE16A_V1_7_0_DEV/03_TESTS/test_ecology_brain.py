import copy, json, os, sqlite3, tempfile, threading, unittest, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '01_RUNTIME'))

from living_runtime import LivingRuntime, ValidationError, IntegrityError, ConflictError, NotFoundError, OfflinePolicyError
from agent_brain import IntentValidator
from ecology_brain import EcologySystem

MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'

HERB='CRI-001'
PRED='CRI-002'
OTHER='CRI-003'
HOME='TER-011'
HOME_BIOME='BIO-008'
ALT='TER-002'
ALT_BIOME='BIO-005'


def profile(species, diet='HERBIVORE', social='HERD', excursion=False, **kw):
    p={'species_ref':species,'diet':diet,'social_structure':social,'cognition_mode':'ADAPTIVE','activity_mode':'DIURNAL','range_excursion_allowed':excursion}
    p.update(kw); return p

class EcoCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=os.path.join(self.tmp.name,'w.db')
        self.rt=LivingRuntime(self.db,master_release_path=MASTER); self.w=self.rt.create_world('eco-test',707,ticks_per_day=24); self.wid=self.w['world_instance_id']
        self.val=IntentValidator(self.rt); self.eco=EcologySystem(self.rt,self.val)
        self.assertEqual(self.eco.load_master_fauna_snapshots()['total'],64)
        self.eco.register_species_profile(self.wid,profile(HERB,'HERBIVORE','HERD'))
        self.eco.register_species_profile(self.wid,profile(PRED,'CARNIVORE','PACK',True))
        self.eco.register_species_profile(self.wid,profile(OTHER,'OMNIVORE','SOLITARY',True))
        self.eco.install_default_action_policies(self.wid)
    def tearDown(self):
        try:self.rt.close()
        except Exception:pass
        self.tmp.cleanup()
    def animal(self,species=HERB,**kw):
        base={'species_ref':species,'territory_ref':HOME,'biome_ref':HOME_BIOME,'age_days':60,'hunger':20,'thirst':20,'energy':80,'reproduction_drive':0}
        base.update(kw); return self.eco.spawn_animal(self.wid,**base)
    def obs(self,a,items):return self.eco.record_observation(self.wid,a['entity_runtime_id'],items)

class CanonBoundaryTests(EcoCase):
    def test_master_count_64(self):
        self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM fauna_snapshots').fetchone()['c'],64)
    def test_snapshot_name_from_master_index(self):
        self.assertEqual(self.eco.get_fauna_snapshot(HERB)['name'],'Cortassom')
    def test_snapshot_immutable_update(self):
        with self.assertRaises(sqlite3.DatabaseError): self.rt.conn.execute("UPDATE fauna_snapshots SET name='x' WHERE species_ref=?",(HERB,))
    def test_snapshot_immutable_delete(self):
        with self.assertRaises(sqlite3.DatabaseError): self.rt.conn.execute("DELETE FROM fauna_snapshots WHERE species_ref=?",(HERB,))
    def test_snapshot_idempotent_reload(self):
        r=self.eco.load_master_fauna_snapshots(); self.assertEqual(r['inserted'],0); self.assertEqual(r['total'],64)
    def test_habitat_primary_allowed(self): self.assertTrue(self.eco.habitat_allows(HERB,HOME,HOME_BIOME))
    def test_habitat_wrong_territory_blocked(self): self.assertFalse(self.eco.habitat_allows(HERB,ALT))
    def test_unknown_territory_rejected(self):
        with self.assertRaises(ValidationError): self.eco.habitat_allows(HERB,'TER-999')
    def test_unknown_biome_rejected(self):
        with self.assertRaises(ValidationError): self.eco.habitat_allows(HERB,HOME,'BIO-999')
    def test_unknown_species_snapshot(self):
        with self.assertRaises(NotFoundError): self.eco.get_fauna_snapshot('CRI-999')

class ProfileTests(EcoCase):
    def test_profile_marked_runtime_not_canon(self): self.assertEqual(self.eco.get_species_profile(self.wid,HERB)['authority'],'RUNTIME_SIMULATION_PROFILE_NOT_CANON')
    def test_invalid_diet(self):
        with self.assertRaises(ValidationError): self.eco.register_species_profile(self.wid,profile('CRI-004','PHOTOSYNTHETIC'))
    def test_invalid_social_structure(self):
        p=profile('CRI-004');p['social_structure']='KINGDOM'
        with self.assertRaises(ValidationError): self.eco.register_species_profile(self.wid,p)
    def test_invalid_cognition(self):
        p=profile('CRI-004');p['cognition_mode']='LLM_AUTONOMOUS'
        with self.assertRaises(ValidationError): self.eco.register_species_profile(self.wid,p)
    def test_invalid_growth_rate(self):
        with self.assertRaises(ValidationError): self.eco.register_species_profile(self.wid,profile('CRI-004',population_growth_rate=.9))
    def test_duplicate_species_profile_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError): self.eco.register_species_profile(self.wid,profile(HERB))
    def test_unknown_species_profile_rejected(self):
        with self.assertRaises(NotFoundError): self.eco.register_species_profile(self.wid,profile('CRI-999'))

class SpawnStateTests(EcoCase):
    def test_spawn_valid_animal(self):
        a=self.animal(); self.assertEqual(a['entity_kind'],'ANIMAL'); self.assertEqual(a['data']['species_ref'],HERB)
    def test_spawn_creature_kind(self): self.assertEqual(self.animal(entity_kind='CREATURE')['entity_kind'],'CREATURE')
    def test_spawn_outside_distribution_blocked_without_excursion(self):
        with self.assertRaises(ValidationError): self.eco.spawn_animal(self.wid,species_ref=HERB,territory_ref=ALT,biome_ref=ALT_BIOME)
    def test_spawn_excursion_allowed(self):
        a=self.eco.spawn_animal(self.wid,species_ref=PRED,territory_ref=ALT,biome_ref=ALT_BIOME); self.assertEqual(a['data']['ecology']['territory_ref'],ALT)
    def test_spawn_invalid_need_bounds(self):
        with self.assertRaises(ValidationError): self.animal(hunger=101)
    def test_maturity_derived_from_profile(self):
        a=self.animal(age_days=0); self.assertFalse(a['data']['mature'])
    def test_protection_preserved(self):
        a=self.animal(protection={'death':'BLOCKED'}); self.assertEqual(a['protection']['death'],'BLOCKED')
    def test_resource_creation(self):
        r=self.eco.create_resource(self.wid,resource_type='PLANT',quantity=50,territory_ref=HOME,biome_ref=HOME_BIOME); self.assertEqual(r['entity_kind'],'ECO_RESOURCE')
    def test_resource_unknown_territory_rejected(self):
        with self.assertRaises(ValidationError): self.eco.create_resource(self.wid,resource_type='PLANT',quantity=50,territory_ref='TER-999')

class ObservationMemoryTests(EcoCase):
    def test_record_observation(self):
        a=self.animal(); o=self.obs(a,[{'kind':'WATER','target_ref':'x','water_value':80,'confidence':.9}]); self.assertTrue(o['observation_id'].startswith('rt:ecoobs:'))
    def test_invalid_observation_kind(self):
        a=self.animal();
        with self.assertRaises(ValidationError): self.obs(a,[{'kind':'MONEY'}])
    def test_observation_immutable(self):
        a=self.animal();o=self.obs(a,[{'kind':'THREAT','danger':80}])
        with self.assertRaises(sqlite3.DatabaseError): self.rt.conn.execute("DELETE FROM ecology_observations WHERE observation_id=?",(o['observation_id'],))
    def test_territory_memory_preference(self):
        a=self.animal(species=PRED);self.eco.remember_territory(self.wid,a['entity_runtime_id'],ALT,food_score=90,water_score=80,danger_score=10,success_score=90)
        self.assertEqual(self.eco.territory_preferences(self.wid,a['entity_runtime_id'])[0]['territory_ref'],ALT)
    def test_territory_memory_immutable(self):
        a=self.animal();m=self.eco.remember_territory(self.wid,a['entity_runtime_id'],HOME,food_score=50,water_score=50,danger_score=10,success_score=60)
        with self.assertRaises(sqlite3.DatabaseError):self.rt.conn.execute("UPDATE territory_memories SET memory_json='{}' WHERE memory_id=?",(m['memory_id'],))

class DecisionTests(EcoCase):
    def test_threat_selects_flee(self):
        a=self.animal(energy=80);self.obs(a,[{'kind':'THREAT','danger':95,'confidence':1}]);d=self.eco.decide(self.wid,a['entity_runtime_id']);self.assertEqual(d['selected']['intent_type'],'ECO_FLEE')
    def test_thirst_selects_drink(self):
        a=self.animal(thirst=90);w=self.eco.create_resource(self.wid,resource_type='WATER',quantity=100,territory_ref=HOME);self.obs(a,[{'kind':'WATER','target_ref':w['entity_runtime_id'],'water_value':90,'confidence':1}]);d=self.eco.decide(self.wid,a['entity_runtime_id']);self.assertEqual(d['selected']['intent_type'],'ECO_DRINK')
    def test_herbivore_hunger_selects_forage(self):
        a=self.animal(hunger=90);f=self.eco.create_resource(self.wid,resource_type='PLANT',quantity=100,territory_ref=HOME);self.obs(a,[{'kind':'FOOD','target_ref':f['entity_runtime_id'],'food_value':90,'confidence':1}]);d=self.eco.decide(self.wid,a['entity_runtime_id']);self.assertEqual(d['selected']['intent_type'],'ECO_FORAGE')
    def test_carnivore_hunger_selects_hunt(self):
        p=self.animal(species=PRED,hunger=90);prey=self.animal();self.obs(p,[{'kind':'PREY','target_ref':prey['entity_runtime_id'],'food_value':90,'confidence':1}]);d=self.eco.decide(self.wid,p['entity_runtime_id']);self.assertEqual(d['selected']['intent_type'],'ECO_HUNT')
    def test_low_energy_selects_rest(self):
        a=self.animal(energy=10);d=self.eco.decide(self.wid,a['entity_runtime_id']);self.assertEqual(d['selected']['intent_type'],'ECO_REST')
    def test_reproduction_selects_mate(self):
        a=self.animal(reproduction_drive=95);b=self.animal(reproduction_drive=95);self.obs(a,[{'kind':'MATE','target_ref':b['entity_runtime_id'],'mate_quality':90,'confidence':1}]);d=self.eco.decide(self.wid,a['entity_runtime_id']);self.assertEqual(d['selected']['intent_type'],'ECO_REPRODUCE')
    def test_migration_selects_valid_destination(self):
        a=self.animal(species=PRED);self.obs(a,[{'kind':'HABITAT','territory_ref':ALT,'biome_ref':ALT_BIOME,'resource_pressure':95,'food_value':90,'water_value':80,'climate_comfort':80,'danger':10,'confidence':1}]);d=self.eco.decide(self.wid,a['entity_runtime_id']);self.assertEqual(d['selected']['intent_type'],'ECO_MIGRATE');self.assertEqual(d['selected']['parameters']['destination_ref'],ALT)
    def test_patrol_fallback(self):
        a=self.animal();d=self.eco.decide(self.wid,a['entity_runtime_id']);self.assertEqual(d['selected']['intent_type'],'ECO_PATROL')
    def test_offline_decision_blocked(self):
        a=self.animal();self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE')
        with self.assertRaises(OfflinePolicyError):self.eco.decide(self.wid,a['entity_runtime_id'])
    def test_decision_persists_hash(self):
        a=self.animal();d=self.eco.decide(self.wid,a['entity_runtime_id']);self.assertTrue(d['decision_hash'])

class ExecutionTests(EcoCase):
    def test_forage_executes_transactionally(self):
        a=self.animal(hunger=80);f=self.eco.create_resource(self.wid,resource_type='PLANT',quantity=100,territory_ref=HOME);self.obs(a,[{'kind':'FOOD','target_ref':f['entity_runtime_id'],'food_value':100}]);d=self.eco.decide(self.wid,a['entity_runtime_id']);r=self.eco.execute_decision(d);self.assertEqual(r['status'],'PASS');aa=self.rt.get_entity(self.wid,a['entity_runtime_id']);ff=self.rt.get_entity(self.wid,f['entity_runtime_id']);self.assertEqual(aa['data']['ecology']['hunger'],40);self.assertEqual(ff['data']['quantity'],60)
    def test_drink_executes(self):
        a=self.animal(thirst=80);w=self.eco.create_resource(self.wid,resource_type='WATER',quantity=100,territory_ref=HOME);self.obs(a,[{'kind':'WATER','target_ref':w['entity_runtime_id'],'water_value':100}]);r=self.eco.execute_decision(self.eco.decide(self.wid,a['entity_runtime_id']));self.assertEqual(r['status'],'PASS');self.assertEqual(self.rt.get_entity(self.wid,a['entity_runtime_id'])['data']['ecology']['thirst'],30)
    def test_hunt_kills_prey(self):
        p=self.animal(species=PRED,hunger=90);q=self.animal();self.obs(p,[{'kind':'PREY','target_ref':q['entity_runtime_id'],'food_value':100}]);r=self.eco.execute_decision(self.eco.decide(self.wid,p['entity_runtime_id']));self.assertEqual(r['status'],'PASS');self.assertEqual(self.rt.get_entity(self.wid,q['entity_runtime_id'])['lifecycle'],'DEAD')
    def test_hunt_protected_prey_rejected(self):
        p=self.animal(species=PRED,hunger=90);q=self.animal(protection={'death':'BLOCKED'});self.obs(p,[{'kind':'PREY','target_ref':q['entity_runtime_id'],'food_value':100}]);d=self.eco.decide(self.wid,p['entity_runtime_id']);r=self.eco.execute_decision(d);self.assertEqual(r['status'],'REJECTED');self.assertEqual(self.rt.get_entity(self.wid,q['entity_runtime_id'])['lifecycle'],'ACTIVE')
    def test_migration_updates_territory_and_memory(self):
        a=self.animal(species=PRED);self.obs(a,[{'kind':'HABITAT','territory_ref':ALT,'biome_ref':ALT_BIOME,'resource_pressure':95,'food_value':90,'water_value':90,'climate_comfort':90,'danger':0}]);r=self.eco.execute_decision(self.eco.decide(self.wid,a['entity_runtime_id']));self.assertEqual(r['status'],'PASS');self.assertEqual(self.rt.get_entity(self.wid,a['entity_runtime_id'])['data']['ecology']['territory_ref'],ALT);self.assertEqual(self.eco.territory_preferences(self.wid,a['entity_runtime_id'])[0]['territory_ref'],ALT)
    def test_reproduction_creates_runtime_child(self):
        a=self.animal(reproduction_drive=95);b=self.animal(reproduction_drive=95);self.obs(a,[{'kind':'MATE','target_ref':b['entity_runtime_id'],'mate_quality':100}]);r=self.eco.execute_decision(self.eco.decide(self.wid,a['entity_runtime_id']));self.assertEqual(r['status'],'PASS');child=self.rt.get_entity(self.wid,r['birth']['child_ref']);self.assertEqual(child['data']['parent_refs'],[a['entity_runtime_id'],b['entity_runtime_id']]);self.assertFalse(child['data']['mature'])
    def test_reproduction_birth_idempotent(self):
        a=self.animal(reproduction_drive=95);b=self.animal(reproduction_drive=95);self.obs(a,[{'kind':'MATE','target_ref':b['entity_runtime_id'],'mate_quality':100}]);d=self.eco.decide(self.wid,a['entity_runtime_id']);r=self.eco.execute_decision(d);again=self.eco._materialize_birth(self.wid,r['execution']['event_id'],a['entity_runtime_id'],b['entity_runtime_id']);self.assertTrue(again['idempotent_replay']);self.assertEqual(again['child_ref'],r['birth']['child_ref'])
    def test_reproduction_species_mismatch_blocked(self):
        a=self.animal(reproduction_drive=95);b=self.animal(species=PRED,reproduction_drive=95);self.obs(a,[{'kind':'MATE','target_ref':b['entity_runtime_id'],'mate_quality':100}])
        with self.assertRaises(ValidationError):self.eco.decide(self.wid,a['entity_runtime_id'])
    def test_reproduction_not_colocated_blocked(self):
        a=self.animal(species=PRED,reproduction_drive=95);b=self.eco.spawn_animal(self.wid,species_ref=PRED,territory_ref=ALT,biome_ref=ALT_BIOME,age_days=60,reproduction_drive=95);self.obs(a,[{'kind':'MATE','target_ref':b['entity_runtime_id'],'mate_quality':100}])
        with self.assertRaises(ValidationError):self.eco.decide(self.wid,a['entity_runtime_id'])
    def test_flee_energy_not_negative(self):
        a=self.animal(energy=5);self.obs(a,[{'kind':'THREAT','danger':100}]);d=self.eco.decide(self.wid,a['entity_runtime_id']);r=self.eco.execute_decision(d);self.assertEqual(r['status'],'REJECTED');self.assertEqual(self.rt.get_entity(self.wid,a['entity_runtime_id'])['data']['ecology']['energy'],5)

class GroupTests(EcoCase):
    def test_create_herd(self): self.assertTrue(self.eco.create_group(self.wid,species_ref=HERB,group_type='HERD',territory_ref=HOME)['group_id'])
    def test_solitary_profile_group_blocked(self):
        with self.assertRaises(ValidationError):self.eco.create_group(self.wid,species_ref=OTHER,group_type='PACK',territory_ref=HOME)
    def test_add_member(self):
        g=self.eco.create_group(self.wid,species_ref=HERB,group_type='HERD',territory_ref=HOME);a=self.animal();m=self.eco.add_group_member(g['group_id'],a['entity_runtime_id']);self.assertEqual(m['role'],'MEMBER')
    def test_species_mismatch_member_blocked(self):
        g=self.eco.create_group(self.wid,species_ref=HERB,group_type='HERD',territory_ref=HOME);a=self.animal(species=PRED)
        with self.assertRaises(ValidationError):self.eco.add_group_member(g['group_id'],a['entity_runtime_id'])
    def test_explicit_leader_wins_rank(self):
        g=self.eco.create_group(self.wid,species_ref=HERB,group_type='HERD',territory_ref=HOME);a=self.animal();b=self.animal();self.eco.add_group_member(g['group_id'],a['entity_runtime_id'],role='LEADER',rank_score=10);self.eco.add_group_member(g['group_id'],b['entity_runtime_id'],role='MEMBER',rank_score=99);self.assertEqual(self.eco.group_leader(g['group_id'])['animal_ref'],a['entity_runtime_id'])
    def test_highest_rank_when_no_leader(self):
        g=self.eco.create_group(self.wid,species_ref=HERB,group_type='HERD',territory_ref=HOME);a=self.animal();b=self.animal();self.eco.add_group_member(g['group_id'],a['entity_runtime_id'],rank_score=10);self.eco.add_group_member(g['group_id'],b['entity_runtime_id'],rank_score=90);self.assertEqual(self.eco.group_leader(g['group_id'])['animal_ref'],b['entity_runtime_id'])
    def test_duplicate_membership_blocked(self):
        g=self.eco.create_group(self.wid,species_ref=HERB,group_type='HERD',territory_ref=HOME);a=self.animal();self.eco.add_group_member(g['group_id'],a['entity_runtime_id'])
        with self.assertRaises(sqlite3.IntegrityError):self.eco.add_group_member(g['group_id'],a['entity_runtime_id'])

class PopulationTests(EcoCase):
    def test_register_population(self):
        p=self.eco.register_population(self.wid,species_ref=HERB,territory_ref=HOME,count=100,carrying_capacity=200);self.assertEqual(p['count'],100)
    def test_negative_population_blocked(self):
        self.eco.register_population(self.wid,species_ref=HERB,territory_ref=HOME,count=10,carrying_capacity=100)
        with self.assertRaises(ConflictError):self.eco.apply_population_delta(self.wid,HERB,HOME,-11,'test')
    def test_population_delta_replay(self):
        self.eco.register_population(self.wid,species_ref=HERB,territory_ref=HOME,count=10,carrying_capacity=100);self.eco.apply_population_delta(self.wid,HERB,HOME,5,'births');self.assertEqual(self.eco.get_population(self.wid,HERB,HOME)['count'],15);self.assertEqual(self.eco.full_integrity_check(self.wid)['status'],'PASS')
    def test_foodweb_predator_diet(self):
        l=self.eco.register_food_web_link(self.wid,predator_species_ref=PRED,prey_species_ref=HERB);self.assertEqual(l['authority'],'RUNTIME_SIMULATION_RELATION_NOT_CANON')
    def test_foodweb_herbivore_cannot_predate(self):
        with self.assertRaises(ValidationError):self.eco.register_food_web_link(self.wid,predator_species_ref=HERB,prey_species_ref=PRED)
    def test_routine_tick_idempotent(self):
        self.eco.register_population(self.wid,species_ref=HERB,territory_ref=HOME,count=50,carrying_capacity=100);r=self.eco.simulate_population_routine(self.wid,routine_key='x');r2=self.eco.simulate_population_routine(self.wid,routine_key='x');self.assertTrue(r2['idempotent_replay']);self.assertEqual(self.eco.get_population(self.wid,HERB,HOME)['version'],len(r['deltas']))
    def test_offline_routine_tick_allowed(self):
        self.eco.register_population(self.wid,species_ref=HERB,territory_ref=HOME,count=50,carrying_capacity=100);self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE');self.assertEqual(self.eco.simulate_population_routine(self.wid)['status'],'PASS')
    def test_extraordinary_migration_blocked_offline(self):
        self.eco.register_population(self.wid,species_ref=PRED,territory_ref=HOME,count=50,carrying_capacity=100);self.eco.register_population(self.wid,species_ref=PRED,territory_ref=ALT,count=0,carrying_capacity=100);self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE')
        with self.assertRaises(OfflinePolicyError):self.eco.migrate_population(self.wid,PRED,HOME,ALT,5,extraordinary=True)
    def test_bounded_offline_migration_allowed(self):
        self.eco.register_population(self.wid,species_ref=PRED,territory_ref=HOME,count=100,carrying_capacity=200);self.eco.register_population(self.wid,species_ref=PRED,territory_ref=ALT,count=0,carrying_capacity=200);self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE');r=self.eco.migrate_population(self.wid,PRED,HOME,ALT,5,extraordinary=False);self.assertEqual(r['status'],'PASS')
    def test_offline_migration_cap_enforced(self):
        self.eco.register_population(self.wid,species_ref=PRED,territory_ref=HOME,count=100,carrying_capacity=200);self.eco.register_population(self.wid,species_ref=PRED,territory_ref=ALT,count=0,carrying_capacity=200);self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE')
        with self.assertRaises(OfflinePolicyError):self.eco.migrate_population(self.wid,PRED,HOME,ALT,6,extraordinary=False)
    def test_predation_routine_never_negative(self):
        self.eco.register_population(self.wid,species_ref=PRED,territory_ref=HOME,count=1000,carrying_capacity=2000);self.eco.register_population(self.wid,species_ref=HERB,territory_ref=HOME,count=2,carrying_capacity=100);self.eco.register_food_web_link(self.wid,predator_species_ref=PRED,prey_species_ref=HERB,preference=1,efficiency=1);self.eco.simulate_population_routine(self.wid,routine_key='pred');self.assertGreaterEqual(self.eco.get_population(self.wid,HERB,HOME)['count'],0)

class ConcurrencyTests(EcoCase):
    def test_shared_resource_no_oversell(self):
        food=self.eco.create_resource(self.wid,resource_type='PLANT',quantity=40,territory_ref=HOME);animals=[self.animal(hunger=80) for _ in range(4)]
        for a in animals:self.obs(a,[{'kind':'FOOD','target_ref':food['entity_runtime_id'],'food_value':100}])
        results=[];lock=threading.Lock()
        def run(a):
            try:r=self.eco.execute_decision(self.eco.decide(self.wid,a['entity_runtime_id']));x=r['status']
            except Exception as e:x=type(e).__name__
            with lock:results.append(x)
        ts=[threading.Thread(target=run,args=(a,)) for a in animals]
        [t.start() for t in ts];[t.join(10) for t in ts]
        self.assertTrue(all(not t.is_alive() for t in ts));self.assertGreaterEqual(self.rt.get_entity(self.wid,food['entity_runtime_id'])['data']['quantity'],0);self.assertEqual(results.count('PASS'),1)
    def test_population_concurrent_deltas_no_lost_update(self):
        self.eco.register_population(self.wid,species_ref=HERB,territory_ref=HOME,count=100,carrying_capacity=1000);errs=[]
        def run():
            try:
                for _ in range(10):self.eco.apply_population_delta(self.wid,HERB,HOME,1,'thread')
            except Exception as e:errs.append(e)
        ts=[threading.Thread(target=run) for _ in range(8)];[t.start() for t in ts];[t.join(10) for t in ts]
        self.assertFalse(errs);self.assertEqual(self.eco.get_population(self.wid,HERB,HOME)['count'],180)
    def test_same_reproduction_event_concurrent_idempotency(self):
        a=self.animal(reproduction_drive=95);b=self.animal(reproduction_drive=95);self.obs(a,[{'kind':'MATE','target_ref':b['entity_runtime_id'],'mate_quality':100}]);d=self.eco.decide(self.wid,a['entity_runtime_id']);v=self.val.validate_intent(d['intent_id']);exe=self.val.execute_validated_intent(d['intent_id']);out=[];errs=[];lock=threading.Lock()
        def run():
            try:r=self.eco._materialize_birth(self.wid,exe['event_id'],a['entity_runtime_id'],b['entity_runtime_id'])
            except Exception as e:
                with lock:errs.append(e);return
            with lock:out.append(r['child_ref'])
        ts=[threading.Thread(target=run) for _ in range(12)];[t.start() for t in ts];[t.join(10) for t in ts]
        self.assertFalse(errs);self.assertEqual(len(set(out)),1);self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM ecology_births WHERE reproduction_event_id=?',(exe['event_id'],)).fetchone()['c'],1)

class IntegrityTests(EcoCase):
    def test_clean_integrity(self):
        a=self.animal();self.eco.remember_territory(self.wid,a['entity_runtime_id'],HOME,food_score=50,water_score=50,danger_score=10,success_score=60);self.assertEqual(self.eco.full_integrity_check(self.wid)['status'],'PASS')
    def test_corrupt_profile_detected(self):
        self.rt.conn.execute("UPDATE ecology_species_profiles SET profile_json='{}' WHERE world_instance_id=? AND species_ref=?",(self.wid,HERB));self.assertEqual(self.eco.full_integrity_check(self.wid)['status'],'FAIL')
    def test_corrupt_population_detected(self):
        self.eco.register_population(self.wid,species_ref=HERB,territory_ref=HOME,count=10,carrying_capacity=100);self.rt.conn.execute("UPDATE ecology_populations_current SET population_json='{}' WHERE world_instance_id=?",(self.wid,));self.assertEqual(self.eco.full_integrity_check(self.wid)['status'],'FAIL')
    def test_integrity_guard_blocks_world(self):
        self.rt.conn.execute("UPDATE ecology_species_profiles SET profile_json='{}' WHERE world_instance_id=? AND species_ref=?",(self.wid,HERB));r=self.eco.integrity_guard(self.wid);self.assertEqual(r['status'],'FAIL');self.assertEqual(self.rt.get_world(self.wid)['status'],'CORRUPT_BLOCKED')
    def test_reopen_persists_population_and_memory(self):
        a=self.animal();aid=a['entity_runtime_id'];self.eco.remember_territory(self.wid,aid,HOME,food_score=50,water_score=50,danger_score=10,success_score=60);self.eco.register_population(self.wid,species_ref=HERB,territory_ref=HOME,count=10,carrying_capacity=100);self.rt.close();self.rt=LivingRuntime(self.db,master_release_path=MASTER);self.val=IntentValidator(self.rt);self.eco=EcologySystem(self.rt,self.val);self.assertEqual(self.eco.get_population(self.wid,HERB,HOME)['count'],10);self.assertEqual(self.eco.territory_preferences(self.wid,aid)[0]['territory_ref'],HOME)

if __name__=='__main__':unittest.main()
