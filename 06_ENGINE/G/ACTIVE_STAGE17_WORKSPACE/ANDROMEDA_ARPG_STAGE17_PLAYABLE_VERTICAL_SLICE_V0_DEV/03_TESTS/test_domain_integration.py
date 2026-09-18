import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '01_RUNTIME'))

from living_runtime import LivingRuntime, new_runtime_id, clock_point
from agent_brain import AgentBrain, IntentValidator
from consequence_engine import ConsequenceEngine
from social_memory import SocialMemorySystem
from ecology_brain import EcologySystem
from object_environment import ObjectEnvironmentSystem
from world_orchestrator import WorldSimulationOrchestrator

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE', '/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
HERB='CRI-001'
PRED='CRI-002'
HOME='TER-011'
HOME_BIOME='BIO-008'
ALT='TER-002'
ALT_BIOME='BIO-005'


def profile(species, diet='HERBIVORE', social='HERD', excursion=False):
    return {
        'species_ref':species,
        'diet':diet,
        'social_structure':social,
        'cognition_mode':'ADAPTIVE',
        'activity_mode':'DIURNAL',
        'range_excursion_allowed':excursion,
    }


def make_agent(rt, world, location_ref):
    c=rt.get_clock(world['world_instance_id'])
    state={
        'state_id':new_runtime_id('state'),
        'world_instance_id':world['world_instance_id'],
        'timeline_id':world['timeline_id'],
        'entity_runtime_id':new_runtime_id('agent'),
        'origin':'RUNTIME_BORN',
        'entity_kind':'AGENT',
        'lifecycle':'ACTIVE',
        'version':0,
        'updated_at':clock_point(c['day'],c['tick']),
        'data':{'location_ref':location_ref,'needs':{'hunger':10,'safety':20},'goals':{},'energy':80},
        'protection':{},
    }
    return rt.register_entity(world['world_instance_id'],state)


class DomainIntegrationCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=os.path.join(self.tmp.name,'w.db')
        self.rt=LivingRuntime(self.db,master_release_path=MASTER)
        self.w=self.rt.create_world('domain-integration',1100,ticks_per_day=24)
        self.wid=self.w['world_instance_id']
        self.val=IntentValidator(self.rt)
        self.brain=AgentBrain(self.rt,self.val)
        self.social=SocialMemorySystem(self.rt)
        self.eco=EcologySystem(self.rt,self.val)
        self.obj=ObjectEnvironmentSystem(self.rt)
        self.cons=ConsequenceEngine(self.rt)
        self.orch=WorldSimulationOrchestrator(self.rt,self.cons,self.brain,self.val,self.social,self.eco,self.obj)
        self.orch.configure_world(self.wid,{'environment_cadence_ticks':9999,'ecology_aggregate_cadence_ticks':9999,'integrity_cadence_ticks':9999})
        self.orch.register_scope(self.wid,HOME,'FULL')
        self.eco.load_master_fauna_snapshots(MASTER)
        self.eco.register_species_profile(self.wid,profile(HERB,'HERBIVORE','HERD'))
        self.eco.register_species_profile(self.wid,profile(PRED,'CARNIVORE','PACK',True))
        self.eco.install_default_action_policies(self.wid)
        self.hub=self.orch.domain_integration

    def tearDown(self):
        try:self.rt.close()
        except Exception:pass
        self.tmp.cleanup()

    def animal(self, species=HERB, territory=HOME, biome=HOME_BIOME, **kw):
        args={
            'species_ref':species,'territory_ref':territory,'biome_ref':biome,
            'age_days':60,'hunger':20,'thirst':20,'energy':80,'reproduction_drive':0,
        }
        args.update(kw)
        return self.eco.spawn_animal(self.wid,**args)

    def test_hunt_reconciles_death_population_and_scheduler(self):
        self.eco.register_population(self.wid,species_ref=HERB,territory_ref=HOME,count=12,carrying_capacity=100)
        predator=self.animal(PRED,hunger=90)
        prey=self.animal(HERB)
        self.orch.register_participant(self.wid,prey['entity_runtime_id'],'ECOLOGY',scope_ref=HOME)
        self.eco.record_observation(self.wid,predator['entity_runtime_id'],[{'kind':'PREY','target_ref':prey['entity_runtime_id'],'food_value':100,'confidence':1}])
        result=self.eco.execute_decision(self.eco.decide(self.wid,predator['entity_runtime_id']))
        self.assertEqual(result['status'],'PASS')
        drained=self.hub.drain_pending(self.wid)
        self.assertEqual(drained['status'],'PASS')
        self.assertEqual(self.eco.get_population(self.wid,HERB,HOME)['count'],11)
        row=self.rt.conn.execute("SELECT enabled FROM orchestration_participants WHERE entity_ref=?",(prey['entity_runtime_id'],)).fetchone()
        self.assertEqual(row['enabled'],0)
        self.hub.drain_pending(self.wid)
        self.assertEqual(self.eco.get_population(self.wid,HERB,HOME)['count'],11)

    def test_birth_increments_aggregate_once(self):
        self.eco.register_population(self.wid,species_ref=HERB,territory_ref=HOME,count=10,carrying_capacity=100)
        a=self.animal(HERB,reproduction_drive=95)
        b=self.animal(HERB,reproduction_drive=95)
        self.eco.record_observation(self.wid,a['entity_runtime_id'],[{'kind':'MATE','target_ref':b['entity_runtime_id'],'mate_quality':100,'confidence':1}])
        result=self.eco.execute_decision(self.eco.decide(self.wid,a['entity_runtime_id']))
        self.assertIsNotNone(result['birth'])
        self.hub.drain_pending(self.wid)
        self.assertEqual(self.eco.get_population(self.wid,HERB,HOME)['count'],11)
        self.hub.drain_pending(self.wid)
        self.assertEqual(self.eco.get_population(self.wid,HERB,HOME)['count'],11)

    def test_individual_migration_transfers_aggregate(self):
        self.eco.register_population(self.wid,species_ref=PRED,territory_ref=HOME,count=9,carrying_capacity=100)
        self.eco.register_population(self.wid,species_ref=PRED,territory_ref=ALT,count=1,carrying_capacity=100)
        animal=self.animal(PRED)
        intent=self.val.submit_intent(self.wid,actor_ref=animal['entity_runtime_id'],intent_type='ECO_MIGRATE',parameters={'destination_ref':ALT},source='AGENT_BRAIN')
        self.assertEqual(self.val.validate_intent(intent['intent_id'])['status'],'PASS')
        exe=self.val.execute_validated_intent(intent['intent_id'])
        self.assertEqual(exe['status'],'SUCCEEDED')
        self.hub.drain_pending(self.wid)
        self.assertEqual(self.eco.get_population(self.wid,PRED,HOME)['count'],8)
        self.assertEqual(self.eco.get_population(self.wid,PRED,ALT)['count'],2)

    def test_colocated_agent_automatically_witnesses_hunt(self):
        self.eco.register_population(self.wid,species_ref=HERB,territory_ref=HOME,count=12,carrying_capacity=100)
        witness=make_agent(self.rt,self.w,HOME_BIOME)
        predator=self.animal(PRED,hunger=90)
        prey=self.animal(HERB)
        self.eco.record_observation(self.wid,predator['entity_runtime_id'],[{'kind':'PREY','target_ref':prey['entity_runtime_id'],'food_value':100,'confidence':1}])
        result=self.eco.execute_decision(self.eco.decide(self.wid,predator['entity_runtime_id']))
        event_id=result['execution']['event_id']
        self.assertEqual(len(self.social.recall_memories(self.wid,witness['entity_runtime_id'])),0)
        self.hub.drain_pending(self.wid)
        memories=self.social.recall_memories(self.wid,witness['entity_runtime_id'])
        self.assertEqual(len(memories),1)
        self.assertEqual(memories[0]['linked_event_id'],event_id)
        self.hub.drain_pending(self.wid)
        self.assertEqual(len(self.social.recall_memories(self.wid,witness['entity_runtime_id'])),1)

    def test_missing_population_is_recorded_not_fabricated(self):
        predator=self.animal(PRED,hunger=90)
        prey=self.animal(HERB)
        self.eco.record_observation(self.wid,predator['entity_runtime_id'],[{'kind':'PREY','target_ref':prey['entity_runtime_id'],'food_value':100,'confidence':1}])
        result=self.eco.execute_decision(self.eco.decide(self.wid,predator['entity_runtime_id']))
        eid=result['execution']['event_id']
        drained=self.hub.drain_pending(self.wid)
        self.assertEqual(drained['status'],'PASS')
        effect=self.rt.conn.execute("SELECT effect_json FROM domain_integration_effects WHERE event_id=? AND effect_key LIKE 'ecology:death:%'",(eid,)).fetchone()
        self.assertIsNotNone(effect)
        self.assertIn('NO_AGGREGATE_POPULATION',effect['effect_json'])

    def test_orchestrator_integrity_includes_domain_hub(self):
        result=self.orch.full_integrity_check(self.wid)
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['domain_integration']['status'],'PASS')


if __name__=='__main__':
    unittest.main()
