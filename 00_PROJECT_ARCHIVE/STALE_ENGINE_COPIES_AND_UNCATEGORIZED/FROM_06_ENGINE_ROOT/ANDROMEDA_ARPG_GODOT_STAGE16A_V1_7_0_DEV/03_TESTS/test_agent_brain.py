import copy
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '01_RUNTIME'))

from living_runtime import (
    LivingRuntime, ValidationError, IntegrityError, ConflictError, NotFoundError,
    OfflinePolicyError, new_runtime_id, clock_point
)
from agent_brain import AgentBrain, IntentValidator

MASTER = '/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'


def make_entity(rt, world, *, kind='AGENT', canonical_ref=None, lifecycle='ACTIVE', data=None, protection=None, origin=None):
    clock = rt.get_clock(world['world_instance_id'])
    if origin is None:
        origin = 'CANONICAL_BACKED' if canonical_ref else 'RUNTIME_BORN'
    state = {
        'state_id': new_runtime_id('state'),
        'world_instance_id': world['world_instance_id'],
        'timeline_id': world['timeline_id'],
        'entity_runtime_id': new_runtime_id(kind.lower()),
        'origin': origin,
        'entity_kind': kind,
        'lifecycle': lifecycle,
        'version': 0,
        'updated_at': clock_point(clock['day'], clock['tick']),
        'data': copy.deepcopy(data or {}),
    }
    if canonical_ref:
        state['canonical_ref'] = canonical_ref
    if protection:
        state['protection'] = copy.deepcopy(protection)
    rt.register_entity(world['world_instance_id'], state)
    return state


def agent_data(**overrides):
    d = {
        'needs': {'hunger': 80, 'safety': 30, 'social': 25},
        'goals': {'survive': 90, 'earn': 50},
        'risk_tolerance': 40,
        'location_ref': 'LOC-A',
        'money': 100,
        'energy': 75,
    }
    d.update(overrides)
    return d


def base_policy(action_type='EAT', **overrides):
    p = {
        'policy_key': f'policy.{action_type.lower()}',
        'action_type': action_type,
        'allowed_sources': ['AGENT_BRAIN', 'LLM_CANDIDATE', 'PLAYER_INPUT'],
        'actor_kinds': ['AGENT'],
        'target_required': False,
        'target_kinds': [],
        'offline_policy': 'ACTIVE_ONLY',
        'spatial_policy': 'NONE',
        'protection_impacts': [],
        'cooldown_ticks': 0,
        'parameter_schema': {},
        'resource_requirements': [],
        'actor_state_equals': {},
        'target_state_equals': {},
        'consequence_templates': [],
    }
    p.update(copy.deepcopy(overrides))
    return p


def behavior(key='eat', intent='EAT', **overrides):
    b = {
        'behavior_key': key,
        'intent_type': intent,
        'need_key': 'hunger',
        'threshold': 50,
        'target_strategy': 'NONE',
        'need_weight': 100,
        'base_priority': 0,
        'risk_cost': 0,
        'risk_penalty_weight': 1,
        'opportunity_bonus': 0,
        'goal_key': 'survive',
        'goal_weight': 10,
        'target_kinds': [],
        'target_fact_equals': {},
        'parameters': {},
    }
    b.update(copy.deepcopy(overrides))
    return b


class Stage5Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, 'world.db')
        self.rt = LivingRuntime(self.db, master_release_path=MASTER)
        self.world = self.rt.create_world('stage5-test', 505, ticks_per_day=24)
        self.val = IntentValidator(self.rt)
        self.brain = AgentBrain(self.rt, self.val)
        self.agent = make_entity(self.rt, self.world, data=agent_data())

    def tearDown(self):
        self.rt.close()
        self.tmp.cleanup()

    @property
    def wid(self):
        return self.world['world_instance_id']

    def policy(self, action='EAT', **kwargs):
        return self.val.register_policy(self.wid, base_policy(action, **kwargs))

    def submit(self, action='EAT', **kwargs):
        return self.val.submit_intent(self.wid, actor_ref=self.agent['entity_runtime_id'], intent_type=action, **kwargs)


class PolicyTests(Stage5Case):
    def test_register_valid_policy(self):
        p = self.policy()
        self.assertEqual(p['status'], 'ACTIVE')

    def test_duplicate_active_action_policy_rejected(self):
        self.policy()
        with self.assertRaises(ConflictError):
            self.val.register_policy(self.wid, base_policy('EAT', policy_key='policy.other'))

    def test_disabled_duplicate_allowed_then_enable_blocked(self):
        self.policy()
        p2 = self.val.register_policy(self.wid, base_policy('EAT', policy_key='policy.other', status='DISABLED'))
        with self.assertRaises(ConflictError):
            self.val.set_policy_status(p2['policy_id'], 'ACTIVE')

    def test_invalid_source_rejected(self):
        with self.assertRaises(ValidationError):
            self.val.register_policy(self.wid, base_policy(allowed_sources=['LLM_EXECUTOR']))

    def test_invalid_offline_policy_rejected(self):
        with self.assertRaises(ValidationError):
            self.val.register_policy(self.wid, base_policy(offline_policy='ALWAYS'))

    def test_invalid_spatial_policy_rejected(self):
        with self.assertRaises(ValidationError):
            self.val.register_policy(self.wid, base_policy(spatial_policy='TELEPORT'))

    def test_invalid_protection_impact_rejected(self):
        with self.assertRaises(ValidationError):
            self.val.register_policy(self.wid, base_policy(protection_impacts=['ERASE_CANON']))

    def test_negative_cooldown_rejected(self):
        with self.assertRaises(ValidationError):
            self.val.register_policy(self.wid, base_policy(cooldown_ticks=-1))

    def test_dynamic_mutation_path_rejected(self):
        with self.assertRaises(ValidationError):
            self.val.register_policy(self.wid, base_policy(consequence_templates=[{
                'target':'ACTOR','operation':'SET','field_path':'data.x','field_path_from_parameter':'path','value':1
            }]))

    def test_direct_target_ref_in_template_rejected(self):
        with self.assertRaises(ValidationError):
            self.val.register_policy(self.wid, base_policy(consequence_templates=[{
                'target':'ACTOR','target_ref':'rt:bad','operation':'SET','field_path':'data.x','value':1
            }]))

    def test_target_template_requires_target_policy(self):
        with self.assertRaises(ValidationError):
            self.val.register_policy(self.wid, base_policy(consequence_templates=[{
                'target':'TARGET','operation':'SET','field_path':'data.x','value':1
            }]))

    def test_resource_consume_cannot_exceed_minimum(self):
        with self.assertRaises(ValidationError):
            self.val.register_policy(self.wid, base_policy(resource_requirements=[{'field_path':'data.money','min_value':5,'consume_amount':10}]))

    def test_death_impact_is_inferred_from_target_lifecycle_template(self):
        p=self.val.register_policy(self.wid,base_policy('KILL',target_required=True,target_kinds=['AGENT'],consequence_templates=[
            {'target':'TARGET','operation':'SET','field_path':'lifecycle','value':'DEAD'}
        ]))
        self.assertIn('DEATH',p['protection_impacts'])

    def test_destroy_impact_is_inferred_from_target_lifecycle_template(self):
        p=self.val.register_policy(self.wid,base_policy('BREAK',target_required=True,target_kinds=['OBJECT'],consequence_templates=[
            {'target':'TARGET','operation':'SET','field_path':'lifecycle','value':'DESTROYED'}
        ]))
        self.assertIn('WORLD_MUTATION',p['protection_impacts'])

    def test_target_resource_requires_target_policy(self):
        with self.assertRaises(ValidationError):
            self.val.register_policy(self.wid,base_policy(target_resource_requirements=[{'field_path':'data.stock','min_value':1,'consume_amount':1}]))

    def test_target_resource_parameter_must_be_declared_numeric(self):
        with self.assertRaises(ValidationError):
            self.val.register_policy(self.wid,base_policy('BUY',target_required=True,target_kinds=['OBJECT'],parameter_schema={'amount':{'type':'string','required':True}},target_resource_requirements=[
                {'field_path':'data.stock','min_from_parameter':'amount','consume_from_parameter':'amount'}
            ]))

    def test_agent_state_filter_limits_behavior(self):
        self.policy('GUARD')
        self.brain.register_behavior(self.wid,behavior('guard','GUARD',agent_state_equals={'data.role':'guard'}))
        d=self.brain.decide(self.wid,self.agent['entity_runtime_id'])
        self.assertEqual(d['status'],'NO_ACTION')

    def test_policy_hash_corruption_detected(self):
        p = self.policy()
        self.rt.conn.execute("UPDATE action_policies SET policy_json='{}' WHERE policy_id=?", (p['policy_id'],))
        intent = self.submit()
        with self.assertRaises(IntegrityError):
            self.val.validate_intent(intent['intent_id'])


class IntentSubmissionTests(Stage5Case):
    def test_submit_valid_candidate(self):
        i = self.submit(parameters={})
        self.assertEqual(i['status'], 'CANDIDATE')
        self.assertEqual(self.val.get_intent(i['intent_id'])['source'], 'AGENT_BRAIN')

    def test_unknown_actor_rejected(self):
        with self.assertRaises(NotFoundError):
            self.val.submit_intent(self.wid, actor_ref=new_runtime_id('agent'), intent_type='EAT')

    def test_invalid_source_rejected(self):
        with self.assertRaises(ValidationError):
            self.submit(source='LLM_EXECUTOR')

    def test_candidate_is_immutable(self):
        i = self.submit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.rt.conn.execute("UPDATE intents SET candidate_json='{}' WHERE intent_id=?", (i['intent_id'],))

    def test_llm_authority_fields_rejected(self):
        with self.assertRaises(ValidationError):
            self.val.ingest_llm_candidate(self.wid, {
                'actor_ref': self.agent['entity_runtime_id'], 'intent_type':'EAT', 'consequences':[]
            })

    def test_llm_candidate_is_marked_untrusted(self):
        i = self.val.ingest_llm_candidate(self.wid, {'actor_ref':self.agent['entity_runtime_id'],'intent_type':'EAT'})
        self.assertEqual(i['source'], 'LLM_CANDIDATE')
        self.assertTrue(i['metadata']['llm_untrusted'])

    def test_candidate_hash_corruption_detected(self):
        i = self.submit()
        self.rt.conn.execute("DROP TRIGGER intent_candidate_immutable")
        self.rt.conn.execute("UPDATE intents SET candidate_hash='CORRUPTED_HASH' WHERE intent_id=?", (i['intent_id'],))
        with self.assertRaises(IntegrityError):
            self.val.get_intent(i['intent_id'])


class ValidationTests(Stage5Case):
    def test_missing_policy_rejects(self):
        i = self.submit()
        r = self.val.validate_intent(i['intent_id'])
        self.assertEqual(r['status'], 'REJECTED')
        self.assertIn('POLICY_NOT_AVAILABLE', r['reasons'])

    def test_valid_intent_passes(self):
        self.policy()
        i = self.submit()
        r = self.val.validate_intent(i['intent_id'])
        self.assertEqual(r['status'], 'PASS')
        self.assertEqual(r['action']['intent_id'], i['intent_id'])

    def test_validation_idempotent(self):
        self.policy()
        i = self.submit()
        a = self.val.validate_intent(i['intent_id'])
        b = self.val.validate_intent(i['intent_id'])
        self.assertEqual(a['action']['action_id'], b['action']['action_id'])
        self.assertTrue(b['idempotent_replay'])

    def test_actor_inactive_rejected(self):
        self.policy()
        a = make_entity(self.rt, self.world, lifecycle='INACTIVE', data=agent_data())
        i = self.val.submit_intent(self.wid, actor_ref=a['entity_runtime_id'], intent_type='EAT')
        r = self.val.validate_intent(i['intent_id'])
        self.assertIn('ACTOR_NOT_ACTIVE', r['reasons'])

    def test_actor_kind_rejected(self):
        self.policy()
        obj = make_entity(self.rt, self.world, kind='OBJECT', data={'location_ref':'LOC-A'})
        i = self.val.submit_intent(self.wid, actor_ref=obj['entity_runtime_id'], intent_type='EAT')
        r = self.val.validate_intent(i['intent_id'])
        self.assertIn('ACTOR_KIND_NOT_ALLOWED', r['reasons'])

    def test_source_not_allowed(self):
        self.val.register_policy(self.wid, base_policy(allowed_sources=['PLAYER_INPUT']))
        i = self.submit(source='AGENT_BRAIN')
        r = self.val.validate_intent(i['intent_id'])
        self.assertIn('SOURCE_NOT_ALLOWED', r['reasons'])

    def test_required_parameter_missing(self):
        self.val.register_policy(self.wid, base_policy(parameter_schema={'amount':{'type':'integer','required':True}}))
        i = self.submit()
        r = self.val.validate_intent(i['intent_id'])
        self.assertIn('MISSING_PARAMETER:amount', r['reasons'])

    def test_unknown_parameter_rejected(self):
        self.policy()
        i = self.submit(parameters={'hack':1})
        r = self.val.validate_intent(i['intent_id'])
        self.assertIn('UNKNOWN_PARAMETER:hack', r['reasons'])

    def test_reserved_parameter_rejected_even_for_llm(self):
        self.policy()
        i = self.val.ingest_llm_candidate(self.wid, {
            'actor_ref':self.agent['entity_runtime_id'],'intent_type':'EAT','parameters':{'execution_class':'ROUTINE_SAFE'}
        })
        r = self.val.validate_intent(i['intent_id'])
        self.assertTrue(any(x.startswith('RESERVED_PARAMETER') for x in r['reasons']))

    def test_parameter_type_and_bounds(self):
        self.val.register_policy(self.wid, base_policy(parameter_schema={'amount':{'type':'integer','required':True,'min':1,'max':3}}))
        i = self.submit(parameters={'amount':5})
        r = self.val.validate_intent(i['intent_id'])
        self.assertIn('PARAMETER_MAX:amount', r['reasons'])

    def test_target_required_missing(self):
        self.val.register_policy(self.wid, base_policy('ATTACK', target_required=True, target_kinds=['AGENT']))
        i = self.submit('ATTACK')
        r = self.val.validate_intent(i['intent_id'])
        self.assertIn('TARGET_REQUIRED', r['reasons'])

    def test_target_kind_rejected(self):
        self.val.register_policy(self.wid, base_policy('TALK', target_required=True, target_kinds=['AGENT']))
        obj = make_entity(self.rt, self.world, kind='OBJECT', data={})
        i = self.submit('TALK', target_ref=obj['entity_runtime_id'])
        r = self.val.validate_intent(i['intent_id'])
        self.assertIn('TARGET_KIND_NOT_ALLOWED', r['reasons'])

    def test_unmaterialized_canonical_target_rejected(self):
        self.val.register_policy(self.wid, base_policy('TALK', target_required=True, target_kinds=['AGENT']))
        i = self.submit('TALK', target_ref='PER-003')
        r = self.val.validate_intent(i['intent_id'])
        self.assertIn('TARGET_NOT_RESOLVED', r['reasons'])

    def test_materialized_canonical_target_passes(self):
        self.val.register_policy(self.wid, base_policy('TALK', target_required=True, target_kinds=['AGENT']))
        target = make_entity(self.rt, self.world, canonical_ref='PER-003', data=agent_data())
        i = self.submit('TALK', target_ref='PER-003')
        r = self.val.validate_intent(i['intent_id'])
        self.assertEqual(r['status'],'PASS')
        self.assertEqual(r['action']['parameters']['validated_target_ref'], target['entity_runtime_id'])

    def test_ambiguous_canonical_target_rejected(self):
        self.val.register_policy(self.wid, base_policy('TALK', target_required=True, target_kinds=['AGENT']))
        make_entity(self.rt, self.world, canonical_ref='PER-003', data=agent_data())
        make_entity(self.rt, self.world, canonical_ref='PER-003', data=agent_data())
        i = self.submit('TALK', target_ref='PER-003')
        r = self.val.validate_intent(i['intent_id'])
        self.assertIn('TARGET_NOT_RESOLVED', r['reasons'])

    def test_resource_insufficient(self):
        self.val.register_policy(self.wid, base_policy(resource_requirements=[{'field_path':'data.money','min_value':150,'consume_amount':10}]))
        i = self.submit()
        r = self.val.validate_intent(i['intent_id'])
        self.assertIn('RESOURCE_INSUFFICIENT:data.money', r['reasons'])

    def test_actor_state_precondition(self):
        self.val.register_policy(self.wid, base_policy(actor_state_equals={'data.energy':99}))
        i = self.submit()
        r = self.val.validate_intent(i['intent_id'])
        self.assertIn('ACTOR_PRECONDITION:data.energy', r['reasons'])

    def test_target_state_precondition(self):
        self.val.register_policy(self.wid, base_policy('TRADE', target_required=True, target_kinds=['AGENT'], target_state_equals={'data.shop_open':True}))
        target = make_entity(self.rt, self.world, data=agent_data(shop_open=False))
        i = self.submit('TRADE', target_ref=target['entity_runtime_id'])
        r = self.val.validate_intent(i['intent_id'])
        self.assertIn('TARGET_PRECONDITION:data.shop_open', r['reasons'])

    def test_spatial_same_location_passes(self):
        self.val.register_policy(self.wid, base_policy('TALK', target_required=True, target_kinds=['AGENT'], spatial_policy='SAME_LOCATION'))
        target = make_entity(self.rt, self.world, data=agent_data(location_ref='LOC-A'))
        i = self.submit('TALK', target_ref=target['entity_runtime_id'])
        self.assertEqual(self.val.validate_intent(i['intent_id'])['status'],'PASS')

    def test_spatial_different_location_rejected(self):
        self.val.register_policy(self.wid, base_policy('TALK', target_required=True, target_kinds=['AGENT'], spatial_policy='SAME_LOCATION'))
        target = make_entity(self.rt, self.world, data=agent_data(location_ref='LOC-B'))
        i = self.submit('TALK', target_ref=target['entity_runtime_id'])
        r = self.val.validate_intent(i['intent_id'])
        self.assertIn('SPATIAL_CONSTRAINT', r['reasons'])

    def test_narrative_death_protection(self):
        self.val.register_policy(self.wid, base_policy('KILL', target_required=True, target_kinds=['AGENT'], protection_impacts=['DEATH']))
        target = make_entity(self.rt, self.world, data=agent_data(), protection={'death':'BLOCKED'})
        i = self.submit('KILL', target_ref=target['entity_runtime_id'])
        r = self.val.validate_intent(i['intent_id'])
        self.assertIn('NARRATIVE_PROTECTION_DEATH', r['reasons'])

    def test_inferred_death_protection_blocks_even_without_declared_impact(self):
        self.val.register_policy(self.wid,base_policy('KILL',target_required=True,target_kinds=['AGENT'],consequence_templates=[
            {'target':'TARGET','operation':'SET','field_path':'lifecycle','value':'DEAD'}
        ]))
        target=make_entity(self.rt,self.world,data=agent_data(),protection={'death':'BLOCKED'})
        i=self.submit('KILL',target_ref=target['entity_runtime_id'])
        r=self.val.validate_intent(i['intent_id'])
        self.assertIn('NARRATIVE_PROTECTION_DEATH',r['reasons'])

    def test_target_resource_from_parameter_blocks_insufficient_stock(self):
        self.val.register_policy(self.wid,base_policy('BUY',target_required=True,target_kinds=['OBJECT'],parameter_schema={'amount':{'type':'integer','required':True,'min':1,'max':20}},target_resource_requirements=[
            {'field_path':'data.stock','min_from_parameter':'amount','consume_from_parameter':'amount'}
        ]))
        shop=make_entity(self.rt,self.world,kind='OBJECT',data={'stock':2})
        i=self.submit('BUY',target_ref=shop['entity_runtime_id'],parameters={'amount':3})
        r=self.val.validate_intent(i['intent_id'])
        self.assertIn('RESOURCE_INSUFFICIENT:data.stock',r['reasons'])

    def test_offline_agent_intent_blocked_even_routine_safe_policy(self):
        self.val.register_policy(self.wid, base_policy(offline_policy='ROUTINE_SAFE'))
        self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE')
        i = self.submit()
        r = self.val.validate_intent(i['intent_id'])
        self.assertIn('OFFLINE_POLICY_BLOCKED', r['reasons'])

    def test_offline_system_routine_can_validate(self):
        self.val.register_policy(self.wid, base_policy('SLEEP', allowed_sources=['SYSTEM_ROUTINE'], offline_policy='ROUTINE_SAFE'))
        self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE')
        i = self.submit('SLEEP', source='SYSTEM_ROUTINE')
        self.assertEqual(self.val.validate_intent(i['intent_id'])['status'],'PASS')

    def test_action_captures_actor_target_versions(self):
        self.val.register_policy(self.wid, base_policy('TALK', target_required=True, target_kinds=['AGENT']))
        target=make_entity(self.rt,self.world,data=agent_data())
        i=self.submit('TALK',target_ref=target['entity_runtime_id'])
        r=self.val.validate_intent(i['intent_id'])
        versions=r['action']['precondition_snapshot']['entity_versions']
        self.assertEqual(versions[self.agent['entity_runtime_id']],0)
        self.assertEqual(versions[target['entity_runtime_id']],0)


    def test_validation_bookkeeping_is_atomic_on_status_failure(self):
        self.policy()
        i=self.submit()
        self.rt.conn.execute("CREATE TRIGGER force_validated_fail BEFORE UPDATE OF status ON intents WHEN NEW.status='VALIDATED' BEGIN SELECT RAISE(ABORT,'forced'); END;")
        with self.assertRaises(sqlite3.IntegrityError):
            self.val.validate_intent(i['intent_id'])
        self.assertIsNone(self.rt.conn.execute("SELECT validation_id FROM intent_validations WHERE intent_id=?",(i['intent_id'],)).fetchone())
        self.assertEqual(self.val.get_intent(i['intent_id'])['status'],'CANDIDATE')


class ExecutionTests(Stage5Case):
    def test_execute_resource_cost_and_target_effect(self):
        self.val.register_policy(self.wid, base_policy('BUY', target_required=True, target_kinds=['OBJECT'],
            parameter_schema={'amount':{'type':'integer','required':True,'min':1,'max':5}},
            resource_requirements=[{'field_path':'data.money','min_value':10,'consume_amount':10}],
            target_resource_requirements=[{'field_path':'data.stock','min_from_parameter':'amount','consume_from_parameter':'amount'}],
            consequence_templates=[]))
        shop=make_entity(self.rt,self.world,kind='OBJECT',data={'stock':10,'location_ref':'LOC-A'})
        i=self.submit('BUY',target_ref=shop['entity_runtime_id'],parameters={'amount':2})
        self.assertEqual(self.val.validate_intent(i['intent_id'])['status'],'PASS')
        r=self.val.execute_validated_intent(i['intent_id'])
        self.assertEqual(r['status'],'SUCCEEDED')
        self.assertEqual(self.rt.get_entity(self.wid,self.agent['entity_runtime_id'])['data']['money'],90)
        self.assertEqual(self.rt.get_entity(self.wid,shop['entity_runtime_id'])['data']['stock'],8)

    def test_cooldown_is_atomic_state_mutation(self):
        self.val.register_policy(self.wid, base_policy(cooldown_ticks=4))
        i=self.submit();self.val.validate_intent(i['intent_id']);self.val.execute_validated_intent(i['intent_id'])
        state=self.rt.get_entity(self.wid,self.agent['entity_runtime_id'])
        cds=state['data']['agent_runtime']['cooldowns']
        self.assertEqual(len(cds),1)
        i2=self.submit();r=self.val.validate_intent(i2['intent_id'])
        self.assertIn('COOLDOWN_ACTIVE',r['reasons'])

    def test_cooldown_expires_with_clock(self):
        self.val.register_policy(self.wid, base_policy(cooldown_ticks=2))
        i=self.submit();self.val.validate_intent(i['intent_id']);self.val.execute_validated_intent(i['intent_id'])
        self.rt.advance_ticks(self.wid,2)
        i2=self.submit();self.assertEqual(self.val.validate_intent(i2['intent_id'])['status'],'PASS')

    def test_stale_precondition_blocks_execution(self):
        self.val.register_policy(self.wid, base_policy(consequence_templates=[{'target':'ACTOR','operation':'SET','field_path':'data.energy','value':100}]))
        i=self.submit();v=self.val.validate_intent(i['intent_id'])
        # mutate actor through a separate authoritative action after validation
        action={
            'action_id':new_runtime_id('action'),'intent_id':new_runtime_id('intent'),'world_instance_id':self.wid,'timeline_id':self.world['timeline_id'],
            'actor_ref':self.agent['entity_runtime_id'],'action_type':'EXTERNAL','parameters':{},'precondition_snapshot':{},'idempotency_key':new_runtime_id('idem'),
            'created_at':clock_point(0,0),'status':'SCHEDULED'
        }
        self.rt.apply_action(self.wid,action,[{'target_ref':self.agent['entity_runtime_id'],'operation':'SET','field_path':'data.energy','value':50}])
        with self.assertRaises(ConflictError): self.val.execute_validated_intent(i['intent_id'])

    def test_execution_idempotent(self):
        self.val.register_policy(self.wid, base_policy(consequence_templates=[{'target':'ACTOR','operation':'INCREMENT','field_path':'data.money','amount':1}]))
        i=self.submit();self.val.validate_intent(i['intent_id'])
        a=self.val.execute_validated_intent(i['intent_id']);b=self.val.execute_validated_intent(i['intent_id'])
        self.assertEqual(a['event_id'],b['event_id'])
        self.assertTrue(b['idempotent_replay'])
        self.assertEqual(self.rt.get_entity(self.wid,self.agent['entity_runtime_id'])['data']['money'],101)

    def test_consumed_status_after_execute(self):
        self.policy();i=self.submit();self.val.validate_intent(i['intent_id']);self.val.execute_validated_intent(i['intent_id'])
        self.assertEqual(self.val.get_intent(i['intent_id'])['status'],'CONSUMED')

    def test_rejected_intent_cannot_execute(self):
        self.policy();i=self.submit(parameters={'hack':1});self.val.validate_intent(i['intent_id'])
        with self.assertRaises(ConflictError):self.val.execute_validated_intent(i['intent_id'])

    def test_policy_disabled_after_validation_blocks_execution(self):
        p=self.policy();i=self.submit();self.val.validate_intent(i['intent_id']);self.val.set_policy_status(p['policy_id'],'DISABLED')
        with self.assertRaises(ValidationError):self.val.execute_validated_intent(i['intent_id'])

    def test_llm_must_pass_same_validator(self):
        self.val.register_policy(self.wid, base_policy(allowed_sources=['LLM_CANDIDATE'], parameter_schema={'tone':{'type':'string','required':True,'enum':['calm','angry']}}))
        i=self.val.ingest_llm_candidate(self.wid,{'actor_ref':self.agent['entity_runtime_id'],'intent_type':'EAT','parameters':{'tone':'calm'}})
        self.assertEqual(self.val.validate_intent(i['intent_id'])['status'],'PASS')
        self.assertEqual(self.val.execute_validated_intent(i['intent_id'])['status'],'SUCCEEDED')

    def test_validation_corruption_guard_blocks_world(self):
        self.policy();i=self.submit();self.val.validate_intent(i['intent_id'])
        self.rt.conn.execute("DROP TRIGGER validation_no_update")
        self.rt.conn.execute("UPDATE intent_validations SET validation_hash='bad' WHERE intent_id=?",(i['intent_id'],))
        g=self.val.integrity_guard(self.wid)
        self.assertEqual(g['status'],'FAIL')
        self.assertEqual(self.rt.get_world(self.wid)['status'],'CORRUPT_BLOCKED')


    def test_execution_bookkeeping_failure_reconciles_idempotently(self):
        self.val.register_policy(self.wid,base_policy(consequence_templates=[{'target':'ACTOR','operation':'INCREMENT','field_path':'data.money','amount':1}]))
        i=self.submit();self.val.validate_intent(i['intent_id'])
        self.rt.conn.execute("CREATE TRIGGER force_consumed_fail BEFORE UPDATE OF status ON intents WHEN NEW.status='CONSUMED' BEGIN SELECT RAISE(ABORT,'forced'); END;")
        with self.assertRaises(sqlite3.IntegrityError):
            self.val.execute_validated_intent(i['intent_id'])
        self.assertEqual(self.rt.get_entity(self.wid,self.agent['entity_runtime_id'])['data']['money'],101)
        self.assertIsNone(self.rt.conn.execute("SELECT execution_id FROM intent_executions WHERE intent_id=?",(i['intent_id'],)).fetchone())
        self.rt.conn.execute("DROP TRIGGER force_consumed_fail")
        r=self.val.execute_validated_intent(i['intent_id'])
        self.assertEqual(r['status'],'SUCCEEDED')
        self.assertEqual(self.rt.get_entity(self.wid,self.agent['entity_runtime_id'])['data']['money'],101)
        self.assertEqual(self.val.get_intent(i['intent_id'])['status'],'CONSUMED')


class AgentBrainTests(Stage5Case):
    def test_valid_agent_profile(self):
        self.assertEqual(self.brain.validate_agent_state(self.wid,self.agent['entity_runtime_id'])['status'],'PASS')

    def test_missing_needs_invalid(self):
        a=make_entity(self.rt,self.world,data={'risk_tolerance':20})
        self.assertEqual(self.brain.validate_agent_state(self.wid,a['entity_runtime_id'])['status'],'FAIL')

    def test_invalid_need_range(self):
        a=make_entity(self.rt,self.world,data=agent_data(needs={'hunger':101}))
        self.assertEqual(self.brain.validate_agent_state(self.wid,a['entity_runtime_id'])['status'],'FAIL')

    def test_non_agent_cannot_be_brain_controlled(self):
        o=make_entity(self.rt,self.world,kind='OBJECT',data={})
        with self.assertRaises(ValidationError):self.brain.validate_agent_state(self.wid,o['entity_runtime_id'])

    def test_behavior_registration(self):
        b=self.brain.register_behavior(self.wid,behavior())
        self.assertEqual(b['status'],'ACTIVE')

    def test_invalid_behavior_threshold(self):
        with self.assertRaises(ValidationError):self.brain.register_behavior(self.wid,behavior(threshold=101))

    def test_behavior_reserved_parameter_rejected(self):
        with self.assertRaises(ValidationError):self.brain.register_behavior(self.wid,behavior(parameters={'execution_class':'ROUTINE_SAFE'}))

    def test_no_candidate_below_threshold(self):
        a=make_entity(self.rt,self.world,data=agent_data(needs={'hunger':20}))
        self.brain.register_behavior(self.wid,behavior())
        d=self.brain.decide(self.wid,a['entity_runtime_id'])
        self.assertEqual(d['status'],'NO_ACTION')

    def test_decision_creates_only_candidate_not_mutation(self):
        self.policy();self.brain.register_behavior(self.wid,behavior())
        before=self.rt.get_entity(self.wid,self.agent['entity_runtime_id'])
        d=self.brain.decide(self.wid,self.agent['entity_runtime_id'])
        after=self.rt.get_entity(self.wid,self.agent['entity_runtime_id'])
        self.assertEqual(d['status'],'INTENT_PROPOSED')
        self.assertEqual(before['version'],after['version'])

    def test_highest_utility_selected(self):
        self.policy('EAT')
        self.val.register_policy(self.wid,base_policy('REST',policy_key='policy.rest'))
        self.brain.register_behavior(self.wid,behavior('eat','EAT',base_priority=1))
        self.brain.register_behavior(self.wid,behavior('rest','REST',base_priority=50))
        d=self.brain.decide(self.wid,self.agent['entity_runtime_id'])
        self.assertEqual(d['selected']['behavior_key'],'rest')

    def test_risk_penalty_changes_selection(self):
        self.policy('SAFE')
        self.val.register_policy(self.wid,base_policy('RISKY',policy_key='policy.risky'))
        self.brain.register_behavior(self.wid,behavior('safe','SAFE',base_priority=10,risk_cost=0))
        self.brain.register_behavior(self.wid,behavior('risky','RISKY',base_priority=40,risk_cost=100,risk_penalty_weight=2))
        d=self.brain.decide(self.wid,self.agent['entity_runtime_id'])
        self.assertEqual(d['selected']['behavior_key'],'safe')

    def test_tie_breaker_is_behavior_key(self):
        self.policy('A')
        self.val.register_policy(self.wid,base_policy('B',policy_key='policy.b'))
        self.brain.register_behavior(self.wid,behavior('z','A'))
        self.brain.register_behavior(self.wid,behavior('a','B'))
        d=self.brain.decide(self.wid,self.agent['entity_runtime_id'])
        self.assertEqual(d['selected']['behavior_key'],'a')

    def test_perception_target_selection_uses_confidence(self):
        self.val.register_policy(self.wid,base_policy('TALK',target_required=True,target_kinds=['AGENT'],policy_key='policy.talk'))
        self.brain.register_behavior(self.wid,behavior('talk','TALK',target_strategy='PERCEPTION',target_kinds=['AGENT']))
        t1=make_entity(self.rt,self.world,data=agent_data());t2=make_entity(self.rt,self.world,data=agent_data())
        self.brain.record_perception(self.wid,self.agent['entity_runtime_id'],[
            {'target_ref':t1['entity_runtime_id'],'perceived_kind':'AGENT','facts':{},'confidence':0.4},
            {'target_ref':t2['entity_runtime_id'],'perceived_kind':'AGENT','facts':{},'confidence':0.9},
        ])
        d=self.brain.decide(self.wid,self.agent['entity_runtime_id'])
        self.assertEqual(d['selected']['target_ref'],t2['entity_runtime_id'])

    def test_false_perception_does_not_override_truth_validator(self):
        self.val.register_policy(self.wid,base_policy('TRADE',target_required=True,target_kinds=['AGENT'],policy_key='policy.trade',target_state_equals={'data.shop_open':True}))
        self.brain.register_behavior(self.wid,behavior('trade','TRADE',target_strategy='PERCEPTION',target_kinds=['AGENT'],target_fact_equals={'shop_open':True}))
        t=make_entity(self.rt,self.world,data=agent_data(shop_open=False))
        self.brain.record_perception(self.wid,self.agent['entity_runtime_id'],[
            {'target_ref':t['entity_runtime_id'],'perceived_kind':'AGENT','facts':{'shop_open':True},'confidence':1.0}
        ])
        d=self.brain.decide(self.wid,self.agent['entity_runtime_id'])
        r=self.val.validate_intent(d['intent_id'])
        self.assertEqual(r['status'],'REJECTED')
        self.assertIn('TARGET_PRECONDITION:data.shop_open',r['reasons'])

    def test_no_perception_means_no_perception_target_action(self):
        self.brain.register_behavior(self.wid,behavior('talk','TALK',target_strategy='PERCEPTION',target_kinds=['AGENT']))
        d=self.brain.decide(self.wid,self.agent['entity_runtime_id'])
        self.assertEqual(d['status'],'NO_ACTION')

    def test_latest_perception_wins(self):
        self.brain.register_behavior(self.wid,behavior('talk','TALK',target_strategy='PERCEPTION',target_kinds=['AGENT']))
        t1=make_entity(self.rt,self.world,data=agent_data());t2=make_entity(self.rt,self.world,data=agent_data())
        self.brain.record_perception(self.wid,self.agent['entity_runtime_id'],[{'target_ref':t1['entity_runtime_id'],'perceived_kind':'AGENT','facts':{},'confidence':1}])
        self.brain.record_perception(self.wid,self.agent['entity_runtime_id'],[{'target_ref':t2['entity_runtime_id'],'perceived_kind':'AGENT','facts':{},'confidence':1}])
        d=self.brain.decide(self.wid,self.agent['entity_runtime_id'])
        self.assertEqual(d['selected']['target_ref'],t2['entity_runtime_id'])

    def test_unknown_perception_canonical_ref_rejected(self):
        with self.assertRaises(ValidationError):
            self.brain.record_perception(self.wid,self.agent['entity_runtime_id'],[{'target_ref':'NO-SUCH-CANON','facts':{}}])

    def test_invalid_confidence_rejected(self):
        with self.assertRaises(ValidationError):
            self.brain.record_perception(self.wid,self.agent['entity_runtime_id'],[{'target_ref':self.agent['entity_runtime_id'],'facts':{},'confidence':2}])

    def test_perception_immutable(self):
        p=self.brain.record_perception(self.wid,self.agent['entity_runtime_id'],[])
        with self.assertRaises(sqlite3.IntegrityError):self.rt.conn.execute("UPDATE agent_perceptions SET perception_json='{}' WHERE perception_id=?",(p['perception_id'],))

    def test_decision_immutable(self):
        self.brain.register_behavior(self.wid,behavior())
        d=self.brain.decide(self.wid,self.agent['entity_runtime_id'])
        with self.assertRaises(sqlite3.IntegrityError):self.rt.conn.execute("UPDATE agent_decisions SET decision_json='{}' WHERE decision_id=?",(d['decision_id'],))

    def test_decision_and_intent_are_atomic(self):
        self.brain.register_behavior(self.wid,behavior())
        self.rt.conn.execute("CREATE TRIGGER force_decision_fail BEFORE INSERT ON agent_decisions BEGIN SELECT RAISE(ABORT,'forced'); END;")
        before=self.rt.conn.execute("SELECT COUNT(*) c FROM intents").fetchone()['c']
        with self.assertRaises(sqlite3.IntegrityError):
            self.brain.decide(self.wid,self.agent['entity_runtime_id'])
        after=self.rt.conn.execute("SELECT COUNT(*) c FROM intents").fetchone()['c']
        self.assertEqual(before,after)

    def test_brain_offline_blocked(self):
        self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE')
        with self.assertRaises(OfflinePolicyError):self.brain.decide(self.wid,self.agent['entity_runtime_id'])

    def test_inactive_agent_cannot_decide(self):
        a=make_entity(self.rt,self.world,lifecycle='INACTIVE',data=agent_data())
        with self.assertRaises(ConflictError):self.brain.decide(self.wid,a['entity_runtime_id'])

    def test_behavior_hash_corruption_detected(self):
        b=self.brain.register_behavior(self.wid,behavior())
        self.rt.conn.execute("UPDATE agent_behaviors SET behavior_hash='bad' WHERE behavior_id=?",(b['behavior_id'],))
        with self.assertRaises(IntegrityError):self.brain.decide(self.wid,self.agent['entity_runtime_id'])

    def test_brain_integrity_guard_blocks_on_perception_corruption(self):
        p=self.brain.record_perception(self.wid,self.agent['entity_runtime_id'],[])
        self.rt.conn.execute("DROP TRIGGER perception_no_update")
        self.rt.conn.execute("UPDATE agent_perceptions SET perception_hash='bad' WHERE perception_id=?",(p['perception_id'],))
        g=self.brain.integrity_guard(self.wid)
        self.assertEqual(g['status'],'FAIL')
        self.assertEqual(self.rt.get_world(self.wid)['status'],'CORRUPT_BLOCKED')


class ConcurrencyAndDeterminismTests(Stage5Case):
    def test_concurrent_agents_decide_validate_execute(self):
        self.val.register_policy(self.wid,base_policy('WORK',policy_key='policy.work',resource_requirements=[{'field_path':'data.energy','min_value':1,'consume_amount':1}],consequence_templates=[{'target':'ACTOR','operation':'INCREMENT','field_path':'data.money','amount':1}]))
        self.brain.register_behavior(self.wid,behavior('work','WORK'))
        agents=[self.agent]+[make_entity(self.rt,self.world,data=agent_data()) for _ in range(15)]
        failures=[]
        def run(a):
            try:
                d=self.brain.decide(self.wid,a['entity_runtime_id'])
                v=self.val.validate_intent(d['intent_id'])
                if v['status']!='PASS': raise AssertionError(v)
                self.val.execute_validated_intent(d['intent_id'])
            except Exception as exc:
                failures.append(repr(exc))
        threads=[threading.Thread(target=run,args=(a,)) for a in agents]
        [t.start() for t in threads];[t.join() for t in threads]
        self.assertEqual(failures,[])
        for a in agents:
            state=self.rt.get_entity(self.wid,a['entity_runtime_id'])
            self.assertEqual(state['data']['money'],101)
            self.assertEqual(state['data']['energy'],74)
        self.assertEqual(self.brain.integrity_guard(self.wid)['status'],'PASS')

    def test_same_state_same_behavior_choice_across_worlds(self):
        self.brain.register_behavior(self.wid,behavior('a','A',base_priority=2))
        self.brain.register_behavior(self.wid,behavior('b','B',base_priority=1))
        d1=self.brain.decide(self.wid,self.agent['entity_runtime_id'])
        w2=self.rt.create_world('stage5-second',505,ticks_per_day=24)
        val2=IntentValidator(self.rt);brain2=AgentBrain(self.rt,val2)
        a2=make_entity(self.rt,w2,data=agent_data())
        # behaviors are world-local, reproduce identical rules
        brain2.register_behavior(w2['world_instance_id'],behavior('a','A',base_priority=2))
        brain2.register_behavior(w2['world_instance_id'],behavior('b','B',base_priority=1))
        d2=brain2.decide(w2['world_instance_id'],a2['entity_runtime_id'])
        self.assertEqual(d1['selected']['behavior_key'],d2['selected']['behavior_key'])
        self.assertEqual(d1['selected']['score'],d2['selected']['score'])


if __name__ == '__main__':
    unittest.main()
