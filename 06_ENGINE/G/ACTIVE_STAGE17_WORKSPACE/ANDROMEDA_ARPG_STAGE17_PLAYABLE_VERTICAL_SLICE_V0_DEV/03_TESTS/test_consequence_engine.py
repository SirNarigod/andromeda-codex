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
    new_runtime_id, clock_point
)
from consequence_engine import ConsequenceEngine

import os
MASTER = os.environ.get('ANDROMEDA_MASTER_RELEASE', '/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')


def make_entity(rt, world, *, kind='OBJECT', origin='RUNTIME_BORN', canonical_ref=None, lifecycle='ACTIVE', data=None, protection=None):
    clock = rt.get_clock(world['world_instance_id'])
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


def root_action(rt, world, actor_ref, event_type, *, parameters=None, consequences=None, execution_class=None, source=None, causality=None):
    c = rt.get_clock(world['world_instance_id'])
    a = {
        'action_id': new_runtime_id('action'),
        'intent_id': new_runtime_id('intent'),
        'world_instance_id': world['world_instance_id'],
        'timeline_id': world['timeline_id'],
        'actor_ref': actor_ref,
        'action_type': event_type,
        'parameters': copy.deepcopy(parameters or {}),
        'precondition_snapshot': {},
        'idempotency_key': new_runtime_id('idem'),
        'created_at': clock_point(c['day'], c['tick']),
        'status': 'SCHEDULED',
    }
    if execution_class:
        a['execution_class'] = execution_class
    if source:
        a['source'] = source
    if causality:
        a['causality'] = causality
    return rt.apply_action(world['world_instance_id'], a, consequences or []), a


def rule(trigger, relation_type, derived, *, operation='INCREMENT', field_path='data.value', amount=1, value=None,
         direction='OUTGOING', max_depth=8, offline_policy='ACTIVE_ONLY', priority=0, kinds=None, condition=None, consequences=None):
    if consequences is None:
        c = {'operation': operation, 'field_path': field_path}
        if operation in {'INCREMENT', 'DECREMENT'}:
            c['amount'] = amount
        elif operation in {'SET', 'TRANSITION'}:
            c['value'] = value
        consequences = [c]
    return {
        'name': f'{trigger}->{derived}',
        'trigger_event_type': trigger,
        'relation_type': relation_type,
        'direction': direction,
        'derived_event_type': derived,
        'priority': priority,
        'max_depth': max_depth,
        'offline_policy': offline_policy,
        'target_entity_kinds': kinds or [],
        'event_payload_equals': condition or {},
        'consequences': consequences,
    }


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, 'world.db')
        self.rt = LivingRuntime(self.db, master_release_path=MASTER)
        self.world = self.rt.create_world('stage4-test', 444, ticks_per_day=24)
        self.eng = ConsequenceEngine(self.rt)

    def tearDown(self):
        self.eng.detach_auto_propagation()
        self.rt.close()
        self.tmp.cleanup()

    def entity(self, **kwargs):
        return make_entity(self.rt, self.world, **kwargs)

    def relation(self, a, b, rtype='CAUSES'):
        return self.eng.register_relation(self.world['world_instance_id'], a['entity_runtime_id'], b['entity_runtime_id'], rtype)

    def add_rule(self, *args, **kwargs):
        return self.eng.register_rule(self.world['world_instance_id'], rule(*args, **kwargs))

    def root(self, actor, etype='ROOT_EVENT', **kwargs):
        res, _ = root_action(self.rt, self.world, actor['entity_runtime_id'], etype, **kwargs)
        return res['event_id']


class CoreHardeningTests(EngineCase):
    def test_direct_destruction_auto_schedules_recovery(self):
        s = self.entity(kind='STRUCTURE', data={'functional': True})
        root_action(self.rt, self.world, s['entity_runtime_id'], 'DESTROYED', consequences=[
            {'target_ref': s['entity_runtime_id'], 'operation': 'SET', 'field_path': 'lifecycle', 'value': 'DESTROYED'},
            {'target_ref': s['entity_runtime_id'], 'operation': 'SET', 'field_path': 'data.functional', 'value': False},
        ])
        rows = self.rt.conn.execute("SELECT recovery_json FROM recoveries WHERE target_ref=?", (s['entity_runtime_id'],)).fetchall()
        self.assertEqual(len(rows), 1)
        rec = json.loads(rows[0]['recovery_json'])
        self.assertEqual(rec['due_at_day'], 7)
        self.assertEqual(rec['restore']['data.functional'], True)

    def test_explicit_recovery_is_not_duplicated(self):
        s = self.entity(kind='STRUCTURE', data={'functional': True})
        root_action(self.rt, self.world, s['entity_runtime_id'], 'DESTROYED', consequences=[
            {'target_ref': s['entity_runtime_id'], 'operation': 'SET', 'field_path': 'lifecycle', 'value': 'DESTROYED'},
            {'target_ref': s['entity_runtime_id'], 'operation': 'SCHEDULE_RECOVERY', 'restore': {'lifecycle': 'ACTIVE'}},
        ])
        n = self.rt.conn.execute("SELECT COUNT(*) c FROM recoveries WHERE target_ref=?", (s['entity_runtime_id'],)).fetchone()['c']
        self.assertEqual(n, 1)

    def test_auto_recovery_restores_after_seven_days(self):
        s = self.entity(kind='STRUCTURE', data={'functional': True})
        root_action(self.rt, self.world, s['entity_runtime_id'], 'DESTROYED', consequences=[
            {'target_ref': s['entity_runtime_id'], 'operation': 'SET', 'field_path': 'lifecycle', 'value': 'DESTROYED'},
            {'target_ref': s['entity_runtime_id'], 'operation': 'SET', 'field_path': 'data.functional', 'value': False},
        ])
        self.rt.advance_ticks(self.world['world_instance_id'], 7*24)
        self.rt.process_due_recoveries(self.world['world_instance_id'])
        got = self.rt.get_entity(self.world['world_instance_id'], s['entity_runtime_id'])
        self.assertEqual(got['lifecycle'], 'ACTIVE')
        self.assertTrue(got['data']['functional'])

    def test_forged_parent_missing_rejected(self):
        a = self.entity(data={'value': 0})
        fake = new_runtime_id('event')
        with self.assertRaises(ValidationError):
            root_action(self.rt, self.world, a['entity_runtime_id'], 'CHILD', causality={
                'root_event_id': fake, 'parent_event_id': fake, 'depth': 1, 'cascade_budget_remaining': 63
            })

    def test_forged_wrong_depth_rejected(self):
        a = self.entity(data={'value': 0})
        root_id = self.root(a)
        with self.assertRaises(ValidationError):
            root_action(self.rt, self.world, a['entity_runtime_id'], 'CHILD', causality={
                'root_event_id': root_id, 'parent_event_id': root_id, 'depth': 2, 'cascade_budget_remaining': 63
            })

    def test_forged_budget_not_decremented_rejected(self):
        a = self.entity(data={'value': 0})
        root_id = self.root(a)
        with self.assertRaises(ValidationError):
            root_action(self.rt, self.world, a['entity_runtime_id'], 'CHILD', causality={
                'root_event_id': root_id, 'parent_event_id': root_id, 'depth': 1, 'cascade_budget_remaining': 64
            })


class RelationTests(EngineCase):
    def test_register_runtime_relation(self):
        a,b = self.entity(),self.entity()
        r = self.relation(a,b,'DEPENDS_ON')
        self.assertEqual(r['relation_type'], 'DEPENDS_ON')
        self.assertEqual(self.eng.verify_relationship_integrity(self.world['world_instance_id'])['status'], 'PASS')

    def test_invalid_runtime_endpoint_rejected(self):
        a = self.entity()
        with self.assertRaises(NotFoundError):
            self.eng.register_relation(self.world['world_instance_id'], a['entity_runtime_id'], new_runtime_id('object'), 'X')

    def test_unknown_canonical_endpoint_rejected(self):
        a = self.entity()
        with self.assertRaises(ValidationError):
            self.eng.register_relation(self.world['world_instance_id'], a['entity_runtime_id'], 'NO-SUCH-CANON', 'X')

    def test_canonical_snapshot_requires_external_id(self):
        with self.assertRaises(ValidationError):
            self.eng.register_relation(self.world['world_instance_id'], 'BIO-001', 'RTE-014', 'conectado_por_rota', origin='CANONICAL_SNAPSHOT')

    def test_runtime_relation_can_be_deactivated(self):
        a,b=self.entity(),self.entity()
        r=self.relation(a,b)
        self.eng.deactivate_runtime_relation(r['relation_id'])
        row=self.rt.conn.execute('SELECT active FROM causal_relations WHERE relation_id=?',(r['relation_id'],)).fetchone()
        self.assertEqual(row['active'],0)

    def test_canonical_snapshot_is_immutable(self):
        report=self.eng.load_master_relationships(self.world['world_instance_id'], relation_types=['conectado_por_rota'], limit=1)
        self.assertEqual(report['inserted'],1)
        rid=self.rt.conn.execute("SELECT relation_id FROM causal_relations WHERE origin='CANONICAL_SNAPSHOT'").fetchone()['relation_id']
        with self.assertRaises(sqlite3.IntegrityError):
            self.rt.conn.execute('UPDATE causal_relations SET active=0 WHERE relation_id=?',(rid,))

    def test_master_relationship_import_is_idempotent(self):
        r1=self.eng.load_master_relationships(self.world['world_instance_id'], relation_types=['conectado_por_rota'], limit=10)
        r2=self.eng.load_master_relationships(self.world['world_instance_id'], relation_types=['conectado_por_rota'], limit=10)
        self.assertEqual(r1['inserted'],10)
        self.assertEqual(r2['inserted'],0)
        self.assertEqual(r2['skipped_existing'],10)

    def test_master_relationship_filter_empty(self):
        r=self.eng.load_master_relationships(self.world['world_instance_id'], relation_types=['TYPE_DOES_NOT_EXIST'])
        self.assertEqual(r['selected'],0)


class RuleValidationTests(EngineCase):
    def test_valid_rule(self):
        r=self.add_rule('A','REL','B')
        self.assertEqual(r['status'],'ACTIVE')
        self.assertEqual(self.eng.verify_rule_integrity(self.world['world_instance_id'])['status'],'PASS')

    def test_invalid_direction(self):
        with self.assertRaises(ValidationError): self.add_rule('A','REL','B',direction='SIDEWAYS')

    def test_invalid_max_depth(self):
        with self.assertRaises(ValidationError): self.add_rule('A','REL','B',max_depth=9)

    def test_hardcoded_target_rejected(self):
        bad=rule('A','REL','B',consequences=[{'operation':'SET','field_path':'data.x','value':1,'target_ref':'X'}])
        with self.assertRaises(ValidationError): self.eng.register_rule(self.world['world_instance_id'],bad)

    def test_unsupported_operation_rejected(self):
        bad=rule('A','REL','B',consequences=[{'operation':'TELEPORT'}])
        with self.assertRaises(ValidationError): self.eng.register_rule(self.world['world_instance_id'],bad)

    def test_disable_rule(self):
        r=self.add_rule('A','REL','B')
        self.eng.set_runtime_rule_status(r['rule_id'],'DISABLED')
        row=self.rt.conn.execute('SELECT status FROM causal_rules WHERE rule_id=?',(r['rule_id'],)).fetchone()
        self.assertEqual(row['status'],'DISABLED')


class PropagationTests(EngineCase):
    def test_one_hop_propagation(self):
        a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
        self.relation(a,b,'LINK')
        self.add_rule('ROOT','LINK','CHILD')
        summary=self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'ROOT'))
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],b['entity_runtime_id'])['data']['value'],1)
        self.assertEqual(summary['derived_event_types']['CHILD'],1)

    def test_three_hop_chain(self):
        a,b,c,d=[self.entity(data={'value':0}) for _ in range(4)]
        self.relation(a,b,'L1'); self.relation(b,c,'L2'); self.relation(c,d,'L3')
        self.add_rule('E0','L1','E1'); self.add_rule('E1','L2','E2'); self.add_rule('E2','L3','E3')
        root=self.root(a,'E0')
        s=self.eng.propagate_from_event(self.world['world_instance_id'],root)
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],d['entity_runtime_id'])['data']['value'],1)
        self.assertEqual(s['expansions']['APPLIED'],3)
        last=self.rt.conn.execute("SELECT child_event_id FROM causal_expansions WHERE root_event_id=? ORDER BY depth DESC LIMIT 1",(root,)).fetchone()['child_event_id']
        self.assertEqual(self.eng.explain_event(last)['depth'],3)

    def test_incoming_direction(self):
        a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
        self.relation(a,b,'LINK')
        self.add_rule('ROOT','LINK','BACK',direction='INCOMING')
        self.eng.propagate_from_event(self.world['world_instance_id'],self.root(b,'ROOT'))
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],a['entity_runtime_id'])['data']['value'],1)

    def test_both_direction_deduplicates_same_relation(self):
        a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
        self.relation(a,b,'LINK')
        self.add_rule('ROOT','LINK','BOTH',direction='BOTH')
        s=self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'ROOT'))
        self.assertEqual(s['expansions']['APPLIED'],1)

    def test_target_kind_filter(self):
        a=self.entity(); b=self.entity(kind='STRUCTURE',data={'value':0})
        self.relation(a,b,'LINK')
        self.add_rule('ROOT','LINK','CHILD',kinds=['AGENT'])
        s=self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'ROOT'))
        self.assertNotIn('APPLIED',s['expansions'])

    def test_event_payload_condition(self):
        a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
        self.relation(a,b,'LINK')
        self.add_rule('ROOT','LINK','CHILD',condition={'payload.parameters.severity':'HIGH'})
        r1=self.root(a,'ROOT',parameters={'severity':'LOW'})
        self.eng.propagate_from_event(self.world['world_instance_id'],r1)
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],b['entity_runtime_id'])['data']['value'],0)
        r2=self.root(a,'ROOT',parameters={'severity':'HIGH'})
        self.eng.propagate_from_event(self.world['world_instance_id'],r2)
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],b['entity_runtime_id'])['data']['value'],1)

    def test_value_from_event(self):
        a,b=self.entity(),self.entity(data={'status':'OLD'})
        self.relation(a,b,'LINK')
        self.eng.register_rule(self.world['world_instance_id'],rule('ROOT','LINK','CHILD',consequences=[
            {'operation':'SET','field_path':'data.status','value_from_event':'payload.parameters.new_status'}
        ]))
        self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'ROOT',parameters={'new_status':'NEW'}))
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],b['entity_runtime_id'])['data']['status'],'NEW')

    def test_amount_from_event_with_multiplier(self):
        a,b=self.entity(),self.entity(data={'value':0})
        self.relation(a,b,'LINK')
        self.eng.register_rule(self.world['world_instance_id'],rule('ROOT','LINK','CHILD',consequences=[
            {'operation':'INCREMENT','field_path':'data.value','amount_from_event':'payload.parameters.power','multiplier':2}
        ]))
        self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'ROOT',parameters={'power':3}))
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],b['entity_runtime_id'])['data']['value'],6)

    def test_target_not_materialized_stops(self):
        a=self.entity(origin='CANONICAL_BACKED',canonical_ref='BIO-001')
        self.eng.load_master_relationships(self.world['world_instance_id'],relation_types=['conectado_por_rota'],limit=1)
        self.add_rule('ROOT','conectado_por_rota','ROUTE_EFFECT')
        s=self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'ROOT'))
        self.assertEqual(s['stops'].get('TARGET_NOT_MATERIALIZED'),1)

    def test_canonical_alias_resolves_materialized_target(self):
        a=self.entity(origin='CANONICAL_BACKED',canonical_ref='BIO-001')
        b=self.entity(origin='CANONICAL_BACKED',canonical_ref='RTE-014',data={'value':0})
        self.eng.load_master_relationships(self.world['world_instance_id'],relation_types=['conectado_por_rota'],limit=1)
        self.add_rule('ROOT','conectado_por_rota','ROUTE_EFFECT')
        self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'ROOT'))
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],b['entity_runtime_id'])['data']['value'],1)

    def test_ambiguous_canonical_target_fails_closed(self):
        a=self.entity(origin='CANONICAL_BACKED',canonical_ref='BIO-001')
        self.entity(origin='CANONICAL_BACKED',canonical_ref='RTE-014',data={'value':0})
        self.entity(origin='CANONICAL_BACKED',canonical_ref='RTE-014',data={'value':0})
        self.eng.load_master_relationships(self.world['world_instance_id'],relation_types=['conectado_por_rota'],limit=1)
        self.add_rule('ROOT','conectado_por_rota','ROUTE_EFFECT')
        s=self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'ROOT'))
        self.assertEqual(s['stops'].get('AMBIGUOUS_CANONICAL_TARGET'),1)

    def test_protected_agent_death_blocked(self):
        a=self.entity(); b=self.entity(kind='AGENT',protection={'death':'BLOCKED'},data={'value':0})
        self.relation(a,b,'LINK')
        self.add_rule('ROOT','LINK','DIED',operation='SET',field_path='lifecycle',value='DEAD')
        s=self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'ROOT'))
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],b['entity_runtime_id'])['lifecycle'],'ACTIVE')
        self.assertEqual(s['stops'].get('NARRATIVE_PROTECTION_DEATH'),1)

    def test_protected_world_mutation_destroy_blocked(self):
        a=self.entity(); b=self.entity(kind='STRUCTURE',protection={'world_mutation_scope':'STORY_AUTHORITY_ONLY'},data={'functional':True})
        self.relation(a,b,'LINK')
        self.add_rule('ROOT','LINK','DESTROYED',operation='SET',field_path='lifecycle',value='DESTROYED')
        s=self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'ROOT'))
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],b['entity_runtime_id'])['lifecycle'],'ACTIVE')
        self.assertEqual(s['stops'].get('NARRATIVE_PROTECTION_WORLD_MUTATION'),1)

    def test_offline_active_only_rule_blocked(self):
        a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
        self.relation(a,b,'LINK'); self.add_rule('ROOT','LINK','CHILD')
        self.rt.set_simulation_mode(self.world['world_instance_id'],'ROUTINE_OFFLINE')
        root=self.root(a,'ROOT',execution_class='ROUTINE_SAFE')
        s=self.eng.propagate_from_event(self.world['world_instance_id'],root)
        self.assertEqual(s['stops'].get('OFFLINE_RULE_NOT_ROUTINE_SAFE'),1)

    def test_offline_routine_safe_benign_rule_runs(self):
        a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
        self.relation(a,b,'LINK'); self.add_rule('ROOT','LINK','CHILD',offline_policy='ROUTINE_SAFE')
        self.rt.set_simulation_mode(self.world['world_instance_id'],'ROUTINE_OFFLINE')
        root=self.root(a,'ROOT',execution_class='ROUTINE_SAFE')
        self.eng.propagate_from_event(self.world['world_instance_id'],root)
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],b['entity_runtime_id'])['data']['value'],1)

    def test_offline_destructive_lifecycle_blocked_even_if_safe(self):
        a=self.entity(); b=self.entity(kind='STRUCTURE',data={'functional':True})
        self.relation(a,b,'LINK'); self.add_rule('ROOT','LINK','DESTROYED',operation='SET',field_path='lifecycle',value='DESTROYED',offline_policy='ROUTINE_SAFE')
        self.rt.set_simulation_mode(self.world['world_instance_id'],'ROUTINE_OFFLINE')
        s=self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'ROOT',execution_class='ROUTINE_SAFE'))
        self.assertEqual(s['stops'].get('OFFLINE_MAJOR_LIFECYCLE_MUTATION_BLOCKED'),1)

    def test_offline_prohibited_event_type_blocked(self):
        a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
        self.relation(a,b,'LINK'); self.add_rule('ROOT','LINK','WAR_ESCALATION',offline_policy='ROUTINE_SAFE')
        self.rt.set_simulation_mode(self.world['world_instance_id'],'ROUTINE_OFFLINE')
        s=self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'ROOT',execution_class='ROUTINE_SAFE'))
        self.assertEqual(s['stops'].get('OFFLINE_MAJOR_EVENT_BLOCKED'),1)

    def test_budget_exhaustion_is_bounded(self):
        ents=[self.entity(data={'value':0}) for _ in range(4)]
        for i in range(3): self.relation(ents[i],ents[i+1],f'L{i}')
        self.add_rule('E0','L0','E1'); self.add_rule('E1','L1','E2'); self.add_rule('E2','L2','E3')
        s=self.eng.propagate_from_event(self.world['world_instance_id'],self.root(ents[0],'E0'),budget=1)
        self.assertEqual(s['status'],'BUDGET_EXHAUSTED')
        self.assertEqual(s['budget_used'],1)
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],ents[2]['entity_runtime_id'])['data']['value'],0)

    def test_rule_max_depth_blocks_next_hop(self):
        a,b,c=[self.entity(data={'value':0}) for _ in range(3)]
        self.relation(a,b,'L1');self.relation(b,c,'L2')
        self.add_rule('E0','L1','E1',max_depth=1);self.add_rule('E1','L2','E2',max_depth=1)
        s=self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'E0'))
        self.assertEqual(s['stops'].get('RULE_MAX_DEPTH'),1)
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],c['entity_runtime_id'])['data']['value'],0)

    def test_cycle_is_stopped_by_expansion_dedup(self):
        a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
        self.relation(a,b,'AB'); self.relation(b,a,'BA')
        self.add_rule('E0','AB','E1'); self.add_rule('E1','BA','E0')
        s=self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'E0'))
        self.assertEqual(s['expansions']['APPLIED'],2)
        self.assertGreaterEqual(s['stops'].get('DUPLICATE_EXPANSION',0),1)
        self.assertLessEqual(s['budget_used'],2)

    def test_propagation_replay_is_idempotent(self):
        a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
        self.relation(a,b); self.add_rule('ROOT','CAUSES','CHILD')
        root=self.root(a,'ROOT')
        s1=self.eng.propagate_from_event(self.world['world_instance_id'],root)
        s2=self.eng.propagate_from_event(self.world['world_instance_id'],root)
        self.assertFalse(s1['idempotent_replay']); self.assertTrue(s2['idempotent_replay'])
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],b['entity_runtime_id'])['data']['value'],1)

    def test_completed_run_does_not_retroactively_apply_new_rules(self):
        a,b,c=[self.entity(data={'value':0}) for _ in range(3)]
        self.relation(a,b,'L1'); self.relation(a,c,'L2')
        self.add_rule('ROOT','L1','C1')
        root=self.root(a,'ROOT'); self.eng.propagate_from_event(self.world['world_instance_id'],root)
        self.add_rule('ROOT','L2','C2')
        self.eng.propagate_from_event(self.world['world_instance_id'],root)
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],c['entity_runtime_id'])['data']['value'],0)

    def test_failed_derived_action_is_recorded_without_partial_mutation(self):
        a,b=self.entity(),self.entity(data={'value':'not-number'})
        self.relation(a,b); self.add_rule('ROOT','CAUSES','CHILD')
        s=self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'ROOT'))
        self.assertEqual(s['expansions'].get('FAILED'),1)
        self.assertEqual(s['stops'].get('DERIVED_ACTION_FAILED'),1)
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],b['entity_runtime_id'])['data']['value'],'not-number')

    def test_derived_destruction_gets_auto_recovery(self):
        a=self.entity(); b=self.entity(kind='STRUCTURE',data={'functional':True})
        self.relation(a,b); self.add_rule('ROOT','CAUSES','DESTROYED',operation='SET',field_path='lifecycle',value='DESTROYED')
        self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'ROOT'))
        n=self.rt.conn.execute('SELECT COUNT(*) c FROM recoveries WHERE target_ref=?',(b['entity_runtime_id'],)).fetchone()['c']
        self.assertEqual(n,1)

    def test_explain_event_returns_root_to_child_path(self):
        a,b,c=[self.entity(data={'value':0}) for _ in range(3)]
        self.relation(a,b,'L1');self.relation(b,c,'L2')
        self.add_rule('E0','L1','E1');self.add_rule('E1','L2','E2')
        root=self.root(a,'E0');self.eng.propagate_from_event(self.world['world_instance_id'],root)
        child=self.rt.conn.execute("SELECT child_event_id FROM causal_expansions WHERE root_event_id=? ORDER BY depth DESC LIMIT 1",(root,)).fetchone()['child_event_id']
        exp=self.eng.explain_event(child)
        self.assertEqual([x['event_type'] for x in exp['chain']],['E0','E1','E2'])

    def test_impact_summary_lists_affected_targets(self):
        a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
        self.relation(a,b);self.add_rule('ROOT','CAUSES','CHILD')
        root=self.root(a,'ROOT');self.eng.propagate_from_event(self.world['world_instance_id'],root)
        impact=self.eng.impact_summary(root)
        self.assertEqual(impact['affected_targets'][b['entity_runtime_id']],1)


class IntegrityAndAutomationTests(EngineCase):
    def test_full_integrity_after_cascade(self):
        a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
        self.relation(a,b);self.add_rule('ROOT','CAUSES','CHILD')
        self.eng.propagate_from_event(self.world['world_instance_id'],self.root(a,'ROOT'))
        self.assertEqual(self.eng.full_integrity_check(self.world['world_instance_id'])['status'],'PASS')

    def test_relation_hash_tamper_detected(self):
        a,b=self.entity(),self.entity();r=self.relation(a,b)
        self.rt.conn.execute('DROP TRIGGER IF EXISTS canonical_snapshot_relation_no_update')
        self.rt.conn.execute("UPDATE causal_relations SET metadata_json='{}' WHERE relation_id=?",(r['relation_id'],))
        # metadata was already {}, so change source instead to ensure mismatch
        self.rt.conn.execute("UPDATE causal_relations SET relation_type='TAMPER' WHERE relation_id=?",(r['relation_id'],))
        self.assertEqual(self.eng.verify_relationship_integrity(self.world['world_instance_id'])['status'],'FAIL')

    def test_rule_hash_tamper_detected(self):
        r=self.add_rule('A','REL','B')
        self.rt.conn.execute("UPDATE causal_rules SET derived_event_type='TAMPER' WHERE rule_id=?",(r['rule_id'],))
        # column tamper does not affect rule_json hash by design; tamper rule_json itself
        self.rt.conn.execute("UPDATE causal_rules SET rule_json='{}' WHERE rule_id=?",(r['rule_id'],))
        self.assertEqual(self.eng.verify_rule_integrity(self.world['world_instance_id'])['status'],'FAIL')

    def test_causal_graph_tamper_detected(self):
        a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
        self.relation(a,b);self.add_rule('ROOT','CAUSES','CHILD')
        root=self.root(a,'ROOT');self.eng.propagate_from_event(self.world['world_instance_id'],root)
        self.rt.conn.execute('UPDATE causal_expansions SET child_event_id=? WHERE root_event_id=?',(root,root))
        self.assertEqual(self.eng.verify_causal_graph(self.world['world_instance_id'])['status'],'FAIL')

    def test_auto_propagation_runs_on_root_event(self):
        a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
        self.relation(a,b);self.add_rule('ROOT','CAUSES','CHILD')
        self.eng.attach_auto_propagation()
        self.root(a,'ROOT')
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],b['entity_runtime_id'])['data']['value'],1)

    def test_detach_auto_propagation_stops_automatic_cascade(self):
        a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
        self.relation(a,b);self.add_rule('ROOT','CAUSES','CHILD')
        self.eng.attach_auto_propagation(); self.eng.detach_auto_propagation()
        self.root(a,'ROOT')
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],b['entity_runtime_id'])['data']['value'],0)

    def test_cross_world_relations_are_isolated(self):
        a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
        self.relation(a,b);self.add_rule('ROOT','CAUSES','CHILD')
        w2=self.rt.create_world('w2',2)
        a2=make_entity(self.rt,w2,data={'value':0}); b2=make_entity(self.rt,w2,data={'value':0})
        e2=ConsequenceEngine(self.rt)
        e2.register_relation(w2['world_instance_id'],a2['entity_runtime_id'],b2['entity_runtime_id'],'CAUSES')
        e2.register_rule(w2['world_instance_id'],rule('ROOT','CAUSES','CHILD'))
        r2,_=root_action(self.rt,w2,a2['entity_runtime_id'],'ROOT')
        e2.propagate_from_event(w2['world_instance_id'],r2['event_id'])
        self.assertEqual(self.rt.get_entity(w2['world_instance_id'],b2['entity_runtime_id'])['data']['value'],1)
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],b['entity_runtime_id'])['data']['value'],0)

    def test_wrong_world_root_rejected(self):
        a=self.entity(); root=self.root(a,'ROOT')
        w2=self.rt.create_world('w2',2)
        with self.assertRaises(ValidationError): self.eng.propagate_from_event(w2['world_instance_id'],root)

    def test_persistence_reopen_completed_run_is_idempotent(self):
        a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
        self.relation(a,b);self.add_rule('ROOT','CAUSES','CHILD')
        root=self.root(a,'ROOT');self.eng.propagate_from_event(self.world['world_instance_id'],root)
        wid=self.world['world_instance_id']
        self.rt.close()
        self.rt=LivingRuntime(self.db,master_release_path=MASTER)
        self.eng=ConsequenceEngine(self.rt)
        s=self.eng.propagate_from_event(wid,root)
        self.assertTrue(s['idempotent_replay'])
        self.assertEqual(self.eng.full_integrity_check(wid)['status'],'PASS')

    def test_concurrent_roots_no_duplicate_or_corruption(self):
        pairs=[]
        for i in range(8):
            a,b=self.entity(data={'value':0}),self.entity(data={'value':0})
            self.eng.register_relation(self.world['world_instance_id'],a['entity_runtime_id'],b['entity_runtime_id'],f'L{i}')
            self.eng.register_rule(self.world['world_instance_id'],rule(f'R{i}',f'L{i}',f'C{i}'))
            pairs.append((a,b,i))
        roots=[self.root(a,f'R{i}') for a,b,i in pairs]
        errors=[]
        threads=[]
        def work(root):
            try:self.eng.propagate_from_event(self.world['world_instance_id'],root)
            except Exception as e:errors.append(repr(e))
        for r in roots:
            t=threading.Thread(target=work,args=(r,));threads.append(t);t.start()
        for t in threads:t.join()
        self.assertEqual(errors,[])
        for a,b,i in pairs:
            self.assertEqual(self.rt.get_entity(self.world['world_instance_id'],b['entity_runtime_id'])['data']['value'],1)
        self.assertEqual(self.eng.full_integrity_check(self.world['world_instance_id'])['status'],'PASS')


if __name__ == '__main__':
    unittest.main(verbosity=2)
