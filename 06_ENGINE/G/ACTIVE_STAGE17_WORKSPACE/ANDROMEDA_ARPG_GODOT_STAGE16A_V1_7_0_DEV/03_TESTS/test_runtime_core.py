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
    OfflinePolicyError, new_runtime_id, clock_point, MASTER_RELEASE_SHA256
)

MASTER = '/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'


def make_entity(rt, world, *, kind='OBJECT', origin='RUNTIME_BORN', canonical_ref=None, lifecycle='ACTIVE', data=None):
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
    return state


def make_action(rt, world, actor_ref, action_type='TEST_ACTION', *, pre=None, key=None, execution_class=None, source=None):
    c = rt.get_clock(world['world_instance_id'])
    a = {
        'action_id': new_runtime_id('action'),
        'intent_id': new_runtime_id('intent'),
        'world_instance_id': world['world_instance_id'],
        'timeline_id': world['timeline_id'],
        'actor_ref': actor_ref,
        'action_type': action_type,
        'parameters': {},
        'precondition_snapshot': pre or {},
        'idempotency_key': key or new_runtime_id('idem'),
        'created_at': clock_point(c['day'], c['tick']),
        'status': 'SCHEDULED',
    }
    if execution_class:
        a['execution_class'] = execution_class
    if source:
        a['source'] = source
    return a


class RuntimeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, 'world.db')
        self.rt = LivingRuntime(self.db, master_release_path=MASTER)
        self.world = self.rt.create_world('test-player', 12345, ticks_per_day=24)

    def tearDown(self):
        self.rt.close()
        self.tmp.cleanup()

    def register(self, **kwargs):
        state = make_entity(self.rt, self.world, **kwargs)
        self.rt.register_entity(self.world['world_instance_id'], state)
        return state

    def mutate(self, entity, operation, field_path, *, value=None, amount=None, expected_version=None, pre=None, key=None, execution_class=None):
        c = {'target_ref': entity['entity_runtime_id'], 'operation': operation, 'field_path': field_path, 'priority': 0}
        if value is not None: c['value'] = value
        if amount is not None: c['amount'] = amount
        if expected_version is not None: c['expected_version'] = expected_version
        a = make_action(self.rt, self.world, entity['entity_runtime_id'], pre=pre, key=key, execution_class=execution_class)
        return self.rt.apply_action(self.world['world_instance_id'], a, [c]), a


class BaselineTests(RuntimeCase):
    def test_baseline_loaded_and_exact_hash(self):
        self.assertEqual(len(self.rt.canonical_ids), 1660)
        self.assertTrue(self.rt.canonical_ref_resolves('PER-003'))
        self.assertTrue(self.rt.canonical_ref_resolves('FAD-001'))
        self.assertTrue(self.rt.canonical_ref_resolves('POI-001'))
        self.assertFalse(self.rt.canonical_ref_resolves('PER-999999'))
        self.assertEqual(self.world['baseline']['release_sha256'], MASTER_RELEASE_SHA256)

    def test_bad_master_hash_fails_closed(self):
        bad = os.path.join(self.tmp.name, 'bad.zip')
        Path(bad).write_bytes(b'not master')
        with self.assertRaises(IntegrityError):
            LivingRuntime(':memory:', master_release_path=bad)

    def test_canonical_backed_known_ref_allowed(self):
        e = self.register(kind='AGENT', origin='CANONICAL_BACKED', canonical_ref='PER-003')
        got = self.rt.get_entity(self.world['world_instance_id'], e['entity_runtime_id'])
        self.assertEqual(got['canonical_ref'], 'PER-003')

    def test_unknown_canonical_ref_rejected(self):
        e = make_entity(self.rt, self.world, kind='AGENT', origin='CANONICAL_BACKED', canonical_ref='PER-999999')
        with self.assertRaises(ValidationError):
            self.rt.register_entity(self.world['world_instance_id'], e)

    def test_missing_master_resolver_fails_for_canonical_backed(self):
        other = LivingRuntime(':memory:')
        w = other.create_world('x', 1)
        e = make_entity(other, w, kind='AGENT', origin='CANONICAL_BACKED', canonical_ref='PER-003')
        try:
            with self.assertRaises(IntegrityError):
                other.register_entity(w['world_instance_id'], e)
        finally:
            other.close()


class WorldClockTests(RuntimeCase):
    def test_world_defaults(self):
        self.assertEqual(self.world['mode'], 'PRIVATE')
        self.assertEqual(self.world['simulation_mode'], 'FULL')
        self.assertEqual(self.world['status'], 'ACTIVE')
        self.assertEqual(self.world['clock_state']['day'], 0)
        self.assertEqual(self.world['clock_state']['tick'], 0)

    def test_shared_mode_schema_compatible(self):
        w = self.rt.create_world('shared-scope', 9, mode='SHARED')
        self.assertEqual(w['mode'], 'SHARED')

    def test_invalid_world_parameters(self):
        with self.assertRaises(ValidationError): self.rt.create_world('', 1)
        with self.assertRaises(ValidationError): self.rt.create_world('x', -1)
        with self.assertRaises(ValidationError): self.rt.create_world('x', 1, mode='BAD')
        with self.assertRaises(ValidationError): self.rt.create_world('x', 1, ticks_per_day=0)

    def test_clock_tick_rollover(self):
        e = self.rt.advance_ticks(self.world['world_instance_id'], 25)
        c = self.rt.get_clock(self.world['world_instance_id'])
        self.assertEqual((c['day'], c['tick']), (1, 1))
        self.assertEqual(e.event_type, 'CLOCK_ADVANCED')
        self.assertEqual(e.payload['from'], {'day': 0, 'tick': 0})
        self.assertEqual(e.payload['to'], {'day': 1, 'tick': 1})

    def test_clock_multiple_days(self):
        self.rt.advance_ticks(self.world['world_instance_id'], 24 * 7 + 5)
        c = self.rt.get_clock(self.world['world_instance_id'])
        self.assertEqual((c['day'], c['tick']), (7, 5))

    def test_clock_paused_rejects_advance(self):
        self.rt.set_clock_state(self.world['world_instance_id'], 'PAUSED')
        with self.assertRaises(ConflictError):
            self.rt.advance_ticks(self.world['world_instance_id'], 1)
        self.assertEqual(self.rt.event_count(self.world['world_instance_id']), 0)

    def test_clock_invalid_inputs(self):
        for n in [0, -1, 1.5, '1']:
            with self.assertRaises(ValidationError):
                self.rt.advance_ticks(self.world['world_instance_id'], n)
        with self.assertRaises(ValidationError):
            self.rt.advance_ticks(self.world['world_instance_id'], 1, source='LLM')

    def test_clock_event_ledger_integrity(self):
        for _ in range(20): self.rt.advance_ticks(self.world['world_instance_id'], 1)
        self.assertEqual(self.rt.verify_event_chain(self.world['world_instance_id'])['status'], 'PASS')
        self.assertEqual(self.rt.verify_ledger(self.world['world_instance_id'])['status'], 'PASS')
        self.assertEqual(self.rt.replay_clock(self.world['world_instance_id'])['status'], 'PASS')

    def test_persistence_reopen(self):
        wid = self.world['world_instance_id']
        self.rt.advance_ticks(wid, 30)
        self.rt.close()
        self.rt = LivingRuntime(self.db, master_release_path=MASTER)
        c = self.rt.get_clock(wid)
        self.assertEqual((c['day'], c['tick']), (1, 6))
        self.assertEqual(self.rt.event_count(wid), 1)


class StateStoreTests(RuntimeCase):
    def test_register_and_get_runtime_entity(self):
        e = self.register(data={'stock': 10})
        got = self.rt.get_entity(self.world['world_instance_id'], e['entity_runtime_id'])
        self.assertEqual(got, e)

    def test_bootstrap_must_be_version_zero(self):
        e = make_entity(self.rt, self.world)
        e['version'] = 1
        with self.assertRaises(ValidationError): self.rt.register_entity(self.world['world_instance_id'], e)

    def test_bootstrap_time_must_match_clock(self):
        e = make_entity(self.rt, self.world)
        e['updated_at'] = {'day': 99, 'tick': 0}
        with self.assertRaises(ValidationError): self.rt.register_entity(self.world['world_instance_id'], e)

    def test_world_timeline_mismatch_rejected(self):
        e = make_entity(self.rt, self.world)
        e['timeline_id'] = new_runtime_id('timeline')
        with self.assertRaises(ValidationError): self.rt.register_entity(self.world['world_instance_id'], e)

    def test_duplicate_entity_rejected(self):
        e = self.register()
        with self.assertRaises(sqlite3.IntegrityError):
            self.rt.register_entity(self.world['world_instance_id'], e)

    def test_get_missing_entity(self):
        with self.assertRaises(NotFoundError): self.rt.get_entity(self.world['world_instance_id'], new_runtime_id('object'))

    def test_state_hash_detects_corruption(self):
        e = self.register(data={'x': 1})
        self.rt.conn.execute("UPDATE entity_states SET state_json=? WHERE entity_runtime_id=?", ('{}', e['entity_runtime_id']))
        with self.assertRaises(IntegrityError): self.rt.get_entity(self.world['world_instance_id'], e['entity_runtime_id'])
        self.assertEqual(self.rt.verify_materialized_states(self.world['world_instance_id'])['status'], 'FAIL')


class ActionTransactionTests(RuntimeCase):
    def test_set_mutation(self):
        e = self.register(data={'stock': 10})
        result, _ = self.mutate(e, 'SET', 'data.stock', value=7)
        got = self.rt.get_entity(self.world['world_instance_id'], e['entity_runtime_id'])
        self.assertEqual(got['data']['stock'], 7)
        self.assertEqual(got['version'], 1)
        self.assertEqual(result['mutation_count'], 1)

    def test_increment_and_decrement(self):
        e = self.register(data={'stock': 10})
        self.mutate(e, 'INCREMENT', 'data.stock', amount=5)
        self.mutate(e, 'DECREMENT', 'data.stock', amount=2)
        got = self.rt.get_entity(self.world['world_instance_id'], e['entity_runtime_id'])
        self.assertEqual(got['data']['stock'], 13)
        self.assertEqual(got['version'], 2)

    def test_transition_from_guard(self):
        e = self.register(lifecycle='ACTIVE')
        c = {'target_ref': e['entity_runtime_id'], 'operation': 'TRANSITION', 'field_path': 'lifecycle', 'from': 'ACTIVE', 'value': 'DESTROYED'}
        a = make_action(self.rt, self.world, e['entity_runtime_id'])
        self.rt.apply_action(self.world['world_instance_id'], a, [c])
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'], e['entity_runtime_id'])['lifecycle'], 'DESTROYED')
        a2 = make_action(self.rt, self.world, e['entity_runtime_id'])
        with self.assertRaises(ConflictError): self.rt.apply_action(self.world['world_instance_id'], a2, [c])

    def test_precondition_version_guard(self):
        e = self.register(data={'x': 0})
        self.mutate(e, 'INCREMENT', 'data.x', amount=1)
        stale = {'entity_versions': {e['entity_runtime_id']: 0}}
        with self.assertRaises(ConflictError): self.mutate(e, 'INCREMENT', 'data.x', amount=1, pre=stale)
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'], e['entity_runtime_id'])['data']['x'], 1)

    def test_consequence_expected_version_guard(self):
        e = self.register(data={'x': 0})
        self.mutate(e, 'INCREMENT', 'data.x', amount=1)
        with self.assertRaises(ConflictError): self.mutate(e, 'INCREMENT', 'data.x', amount=1, expected_version=0)

    def test_idempotency_same_action_returns_same_event(self):
        e = self.register(data={'x': 0})
        key = 'stable-key-1'
        a = make_action(self.rt, self.world, e['entity_runtime_id'], key=key)
        c = [{'target_ref': e['entity_runtime_id'], 'operation': 'INCREMENT', 'field_path': 'data.x', 'amount': 1}]
        r1 = self.rt.apply_action(self.world['world_instance_id'], a, c)
        r2 = self.rt.apply_action(self.world['world_instance_id'], a, c)
        self.assertEqual(r1['event_id'], r2['event_id'])
        self.assertFalse(r1['idempotent_replay'])
        self.assertTrue(r2['idempotent_replay'])
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'], e['entity_runtime_id'])['data']['x'], 1)
        self.assertEqual(self.rt.event_count(self.world['world_instance_id']), 1)

    def test_idempotency_key_collision_rejected(self):
        e = self.register(data={'x': 0})
        a1 = make_action(self.rt, self.world, e['entity_runtime_id'], key='same')
        a2 = make_action(self.rt, self.world, e['entity_runtime_id'], key='same')
        c = [{'target_ref': e['entity_runtime_id'], 'operation': 'INCREMENT', 'field_path': 'data.x', 'amount': 1}]
        self.rt.apply_action(self.world['world_instance_id'], a1, c)
        with self.assertRaises(ConflictError): self.rt.apply_action(self.world['world_instance_id'], a2, c)

    def test_transaction_rolls_back_all_on_second_failure(self):
        e1 = self.register(data={'x': 0})
        e2 = self.register(data={'name': 'not-number'})
        a = make_action(self.rt, self.world, e1['entity_runtime_id'])
        cs = [
            {'target_ref': e1['entity_runtime_id'], 'operation': 'INCREMENT', 'field_path': 'data.x', 'amount': 10, 'priority': 0},
            {'target_ref': e2['entity_runtime_id'], 'operation': 'INCREMENT', 'field_path': 'data.name', 'amount': 1, 'priority': 1},
        ]
        with self.assertRaises(ValidationError): self.rt.apply_action(self.world['world_instance_id'], a, cs)
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'], e1['entity_runtime_id'])['data']['x'], 0)
        self.assertEqual(self.rt.event_count(self.world['world_instance_id']), 0)
        self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM consequences').fetchone()['c'], 0)

    def test_multi_entity_atomic_success(self):
        a1 = self.register(data={'money': 100})
        a2 = self.register(data={'money': 10})
        action = make_action(self.rt, self.world, a1['entity_runtime_id'])
        cs = [
            {'target_ref': a1['entity_runtime_id'], 'operation': 'DECREMENT', 'field_path': 'data.money', 'amount': 25},
            {'target_ref': a2['entity_runtime_id'], 'operation': 'INCREMENT', 'field_path': 'data.money', 'amount': 25},
        ]
        r = self.rt.apply_action(self.world['world_instance_id'], action, cs)
        self.assertEqual(r['mutation_count'], 2)
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'], a1['entity_runtime_id'])['data']['money'], 75)
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'], a2['entity_runtime_id'])['data']['money'], 35)

    def test_unsupported_operation_rolls_back(self):
        e = self.register(data={'x': 0})
        a = make_action(self.rt, self.world, e['entity_runtime_id'])
        with self.assertRaises(ValidationError):
            self.rt.apply_action(self.world['world_instance_id'], a, [{'target_ref': e['entity_runtime_id'], 'operation': 'TELEPORT'}])
        self.assertEqual(self.rt.event_count(self.world['world_instance_id']), 0)

    def test_negative_increment_amount_rejected(self):
        e = self.register(data={'x': 0})
        with self.assertRaises(ValidationError): self.mutate(e, 'INCREMENT', 'data.x', amount=-1)

    def test_non_numeric_increment_rejected(self):
        e = self.register(data={'x': 'a'})
        with self.assertRaises(ValidationError): self.mutate(e, 'INCREMENT', 'data.x', amount=1)

    def test_noop_blocked_records_no_state_mutation(self):
        e = self.register(data={'x': 1})
        a = make_action(self.rt, self.world, e['entity_runtime_id'])
        r = self.rt.apply_action(self.world['world_instance_id'], a, [{'target_ref': e['entity_runtime_id'], 'operation': 'NOOP_BLOCKED', 'reason': 'NARRATIVE_PROTECTION'}])
        self.assertEqual(r['mutation_count'], 1)
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'], e['entity_runtime_id'])['version'], 0)
        row = self.rt.conn.execute('SELECT status FROM consequences WHERE event_id=?', (r['event_id'],)).fetchone()
        self.assertEqual(row['status'], 'BLOCKED')

    def test_unknown_actor_rejected(self):
        e = self.register(data={'x': 0})
        a = make_action(self.rt, self.world, 'UNKNOWN_ACTOR')
        with self.assertRaises(ValidationError):
            self.rt.apply_action(self.world['world_instance_id'], a, [{'target_ref': e['entity_runtime_id'], 'operation': 'INCREMENT', 'field_path': 'data.x', 'amount': 1}])
        self.assertEqual(self.rt.event_count(self.world['world_instance_id']), 0)

    def test_missing_runtime_actor_rejected(self):
        e = self.register(data={'x': 0})
        a = make_action(self.rt, self.world, new_runtime_id('agent'))
        with self.assertRaises(NotFoundError):
            self.rt.apply_action(self.world['world_instance_id'], a, [{'target_ref': e['entity_runtime_id'], 'operation': 'INCREMENT', 'field_path': 'data.x', 'amount': 1}])



class OfflineAndRecoveryTests(RuntimeCase):
    def test_offline_rejects_non_routine_safe(self):
        e = self.register(data={'x': 0})
        self.rt.set_simulation_mode(self.world['world_instance_id'], 'ROUTINE_OFFLINE')
        with self.assertRaises(OfflinePolicyError): self.mutate(e, 'INCREMENT', 'data.x', amount=1)
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'], e['entity_runtime_id'])['data']['x'], 0)

    def test_offline_allows_routine_safe(self):
        e = self.register(data={'x': 0})
        self.rt.set_simulation_mode(self.world['world_instance_id'], 'ROUTINE_OFFLINE')
        self.mutate(e, 'INCREMENT', 'data.x', amount=1, execution_class='ROUTINE_SAFE')
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'], e['entity_runtime_id'])['data']['x'], 1)

    def test_recovery_exactly_seven_universe_days(self):
        e = self.register(kind='STRUCTURE', lifecycle='ACTIVE', data={'functional': True})
        a = make_action(self.rt, self.world, e['entity_runtime_id'])
        cs = [
            {'target_ref': e['entity_runtime_id'], 'operation': 'SET', 'field_path': 'lifecycle', 'value': 'DESTROYED', 'priority': 0},
            {'target_ref': e['entity_runtime_id'], 'operation': 'SET', 'field_path': 'data.functional', 'value': False, 'priority': 1},
            {'target_ref': e['entity_runtime_id'], 'operation': 'SCHEDULE_RECOVERY', 'restore': {'lifecycle': 'ACTIVE', 'data.functional': True}, 'priority': 2},
        ]
        self.rt.apply_action(self.world['world_instance_id'], a, cs)
        rec = self.rt.conn.execute('SELECT * FROM recoveries').fetchone()
        self.assertEqual(rec['destroyed_at_day'], 0)
        self.assertEqual(rec['due_at_day'], 7)
        self.rt.advance_ticks(self.world['world_instance_id'], 24 * 7 - 1)
        self.assertEqual(self.rt.process_due_recoveries(self.world['world_instance_id']), [])
        self.rt.advance_ticks(self.world['world_instance_id'], 1)
        out = self.rt.process_due_recoveries(self.world['world_instance_id'])
        self.assertEqual(len(out), 1)
        got = self.rt.get_entity(self.world['world_instance_id'], e['entity_runtime_id'])
        self.assertEqual(got['lifecycle'], 'ACTIVE')
        self.assertTrue(got['data']['functional'])

    def test_recovery_runs_offline_as_safe_system_work(self):
        e = self.register(kind='STRUCTURE', lifecycle='ACTIVE')
        a = make_action(self.rt, self.world, e['entity_runtime_id'])
        self.rt.apply_action(self.world['world_instance_id'], a, [
            {'target_ref': e['entity_runtime_id'], 'operation': 'SET', 'field_path': 'lifecycle', 'value': 'DESTROYED'},
            {'target_ref': e['entity_runtime_id'], 'operation': 'SCHEDULE_RECOVERY', 'restore': {'lifecycle': 'ACTIVE'}},
        ])
        self.rt.set_simulation_mode(self.world['world_instance_id'], 'ROUTINE_OFFLINE')
        self.rt.advance_ticks(self.world['world_instance_id'], 24 * 7)
        out = self.rt.process_due_recoveries(self.world['world_instance_id'])
        self.assertEqual(len(out), 1)
        self.assertEqual(self.rt.get_entity(self.world['world_instance_id'], e['entity_runtime_id'])['lifecycle'], 'ACTIVE')

    def test_recovery_does_not_delete_destroy_event_history(self):
        e = self.register(kind='STRUCTURE')
        a = make_action(self.rt, self.world, e['entity_runtime_id'], action_type='STRUCTURE_DESTROYED')
        destroy = self.rt.apply_action(self.world['world_instance_id'], a, [
            {'target_ref': e['entity_runtime_id'], 'operation': 'SET', 'field_path': 'lifecycle', 'value': 'DESTROYED'},
            {'target_ref': e['entity_runtime_id'], 'operation': 'SCHEDULE_RECOVERY', 'restore': {'lifecycle': 'ACTIVE'}},
        ])
        self.rt.advance_ticks(self.world['world_instance_id'], 24 * 7)
        self.rt.process_due_recoveries(self.world['world_instance_id'])
        self.assertEqual(self.rt.get_event(destroy['event_id']).event_type, 'STRUCTURE_DESTROYED')
        self.assertGreaterEqual(self.rt.event_count(self.world['world_instance_id']), 3)
        self.assertEqual(self.rt.verify_event_chain(self.world['world_instance_id'])['status'], 'PASS')

    def test_recovery_non_regenerable_agent_rejected_atomically(self):
        e = self.register(kind='AGENT')
        a = make_action(self.rt, self.world, e['entity_runtime_id'])
        with self.assertRaises(ValidationError):
            self.rt.apply_action(self.world['world_instance_id'], a, [{'target_ref': e['entity_runtime_id'], 'operation': 'SCHEDULE_RECOVERY'}])
        self.assertEqual(self.rt.conn.execute('SELECT COUNT(*) c FROM recoveries').fetchone()['c'], 0)
        self.assertEqual(self.rt.event_count(self.world['world_instance_id']), 0)


class EventBusIntegrityTests(RuntimeCase):
    def test_bus_delivers_post_commit_event(self):
        seen = []
        self.rt.event_bus.subscribe(lambda e: seen.append((e.event_id, self.rt.event_count(e.world_instance_id))))
        self.rt.advance_ticks(self.world['world_instance_id'], 1)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][1], 1)

    def test_bus_handler_failure_does_not_rollback_truth(self):
        def boom(_): raise RuntimeError('subscriber failed')
        self.rt.event_bus.subscribe(boom)
        e = self.rt.advance_ticks(self.world['world_instance_id'], 1)
        self.assertEqual(self.rt.get_event(e.event_id).event_id, e.event_id)
        self.assertEqual(self.rt.event_count(self.world['world_instance_id']), 1)

    def test_bus_unsubscribe(self):
        seen = []
        unsub = self.rt.event_bus.subscribe(lambda e: seen.append(e.event_id))
        self.rt.advance_ticks(self.world['world_instance_id'], 1)
        unsub()
        self.rt.advance_ticks(self.world['world_instance_id'], 1)
        self.assertEqual(len(seen), 1)

    def test_event_table_update_delete_blocked(self):
        e = self.rt.advance_ticks(self.world['world_instance_id'], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.rt.conn.execute('UPDATE events SET event_type=? WHERE event_id=?', ('HACK', e.event_id))
        with self.assertRaises(sqlite3.IntegrityError):
            self.rt.conn.execute('DELETE FROM events WHERE event_id=?', (e.event_id,))

    def test_ledger_update_delete_blocked(self):
        e = self.rt.advance_ticks(self.world['world_instance_id'], 1)
        lid = self.rt.conn.execute('SELECT ledger_entry_id FROM causal_ledger WHERE event_id=?', (e.event_id,)).fetchone()['ledger_entry_id']
        with self.assertRaises(sqlite3.IntegrityError):
            self.rt.conn.execute('UPDATE causal_ledger SET root_event_id=? WHERE ledger_entry_id=?', ('x', lid))
        with self.assertRaises(sqlite3.IntegrityError):
            self.rt.conn.execute('DELETE FROM causal_ledger WHERE ledger_entry_id=?', (lid,))

    def test_chain_multi_world_isolated(self):
        w2 = self.rt.create_world('other', 2)
        for _ in range(10):
            self.rt.advance_ticks(self.world['world_instance_id'], 1)
            self.rt.advance_ticks(w2['world_instance_id'], 2)
        self.assertEqual(self.rt.verify_event_chain(self.world['world_instance_id'])['status'], 'PASS')
        self.assertEqual(self.rt.verify_event_chain(w2['world_instance_id'])['status'], 'PASS')

    def test_manual_event_corruption_detected(self):
        self.rt.advance_ticks(self.world['world_instance_id'], 1)
        self.rt.conn.execute('DROP TRIGGER events_no_update')
        self.rt.conn.execute("UPDATE events SET payload_json='{}' WHERE world_instance_id=?", (self.world['world_instance_id'],))
        report = self.rt.verify_event_chain(self.world['world_instance_id'])
        self.assertEqual(report['status'], 'FAIL')
        self.assertTrue(any(x['error'] == 'EVENT_HASH_MISMATCH' for x in report['failures']))

    def test_manual_ledger_corruption_detected(self):
        self.rt.advance_ticks(self.world['world_instance_id'], 1)
        self.rt.conn.execute('DROP TRIGGER ledger_no_update')
        self.rt.conn.execute("UPDATE causal_ledger SET mutations_json='[]'")
        self.assertEqual(self.rt.verify_ledger(self.world['world_instance_id'])['status'], 'FAIL')


class ReplayTests(RuntimeCase):
    def test_replay_matches_materialized_after_mixed_operations(self):
        entities = [self.register(data={'n': i}) for i in range(10)]
        for i in range(100):
            e = entities[i % len(entities)]
            if i % 3 == 0:
                self.mutate(e, 'INCREMENT', 'data.n', amount=2)
            elif i % 3 == 1:
                self.mutate(e, 'DECREMENT', 'data.n', amount=1)
            else:
                current = self.rt.get_entity(self.world['world_instance_id'], e['entity_runtime_id'])['data']['n']
                self.mutate(e, 'SET', 'data.n', value=current + 3)
        report = self.rt.compare_replay_to_materialized(self.world['world_instance_id'])
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['entities'], 10)

    def test_full_integrity_check(self):
        e = self.register(data={'x': 0})
        for _ in range(20): self.mutate(e, 'INCREMENT', 'data.x', amount=1)
        self.rt.advance_ticks(self.world['world_instance_id'], 50)
        r = self.rt.full_integrity_check(self.world['world_instance_id'])
        self.assertEqual(r['status'], 'PASS')
        self.assertTrue(all(v['status'] == 'PASS' for v in r['checks'].values()))

    def test_materialized_tamper_replay_detects_difference(self):
        e = self.register(data={'x': 0})
        self.mutate(e, 'INCREMENT', 'data.x', amount=5)
        state = self.rt.get_entity(self.world['world_instance_id'], e['entity_runtime_id'])
        state['data']['x'] = 999
        from living_runtime import canonical_json, sha256_text
        sj = canonical_json(state)
        self.rt.conn.execute('UPDATE entity_states SET state_json=?,state_hash=? WHERE entity_runtime_id=?', (sj, sha256_text(sj), e['entity_runtime_id']))
        self.assertEqual(self.rt.verify_materialized_states(self.world['world_instance_id'])['status'], 'PASS')
        self.assertEqual(self.rt.compare_replay_to_materialized(self.world['world_instance_id'])['status'], 'FAIL')

    def test_bootstrap_immutable_trigger(self):
        e = self.register()
        with self.assertRaises(sqlite3.IntegrityError):
            self.rt.conn.execute('UPDATE bootstrap_states SET state_json=? WHERE entity_runtime_id=?', ('{}', e['entity_runtime_id']))
        with self.assertRaises(sqlite3.IntegrityError):
            self.rt.conn.execute('DELETE FROM bootstrap_states WHERE entity_runtime_id=?', (e['entity_runtime_id'],))

    def test_clock_replay_detects_materialized_clock_tamper(self):
        self.rt.advance_ticks(self.world['world_instance_id'], 10)
        self.rt.conn.execute('UPDATE clocks SET tick=11 WHERE world_instance_id=?', (self.world['world_instance_id'],))
        self.assertEqual(self.rt.replay_clock(self.world['world_instance_id'])['status'], 'FAIL')

    def test_integrity_guard_blocks_corrupt_world(self):
        e = self.register(data={'x': 0})
        self.mutate(e, 'INCREMENT', 'data.x', amount=1)
        self.rt.conn.execute("UPDATE entity_states SET state_json='{}' WHERE entity_runtime_id=?", (e['entity_runtime_id'],))
        report = self.rt.integrity_guard(self.world['world_instance_id'])
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(self.rt.get_world(self.world['world_instance_id'])['status'], 'CORRUPT_BLOCKED')

    def test_crash_style_reopen_replay_is_consistent(self):
        e = self.register(data={'x': 0})
        wid = self.world['world_instance_id']
        for i in range(250):
            self.mutate(e, 'INCREMENT', 'data.x', amount=(i % 3) + 1)
        self.rt.advance_ticks(wid, 123)
        self.rt.close()
        self.rt = LivingRuntime(self.db, master_release_path=MASTER)
        self.assertEqual(self.rt.full_integrity_check(wid)['status'], 'PASS')
        self.assertEqual(self.rt.get_entity(wid, e['entity_runtime_id'])['data']['x'], sum((i % 3) + 1 for i in range(250)))



class StressConcurrencyTests(RuntimeCase):
    def test_stress_100_entities_3000_actions_and_replay(self):
        entities = [self.register(data={'v': 0}) for _ in range(100)]
        for i in range(3000):
            e = entities[(i * 37) % 100]
            self.mutate(e, 'INCREMENT', 'data.v', amount=(i % 5) + 1)
        self.assertEqual(self.rt.event_count(self.world['world_instance_id']), 3000)
        self.assertEqual(self.rt.verify_event_chain(self.world['world_instance_id'])['status'], 'PASS')
        self.assertEqual(self.rt.verify_ledger(self.world['world_instance_id'])['status'], 'PASS')
        self.assertEqual(self.rt.compare_replay_to_materialized(self.world['world_instance_id'])['status'], 'PASS')
        total = sum(e['data']['v'] for e in self.rt.list_entities(self.world['world_instance_id']))
        self.assertEqual(total, sum((i % 5) + 1 for i in range(3000)))

    def test_concurrent_8_threads_400_atomic_increments(self):
        e = self.register(data={'v': 0})
        errors = []
        def worker(worker_id):
            try:
                for i in range(50):
                    a = make_action(self.rt, self.world, e['entity_runtime_id'], key=f'w{worker_id}:{i}')
                    self.rt.apply_action(self.world['world_instance_id'], a, [{
                        'target_ref': e['entity_runtime_id'], 'operation': 'INCREMENT', 'field_path': 'data.v', 'amount': 1
                    }])
            except Exception as exc:
                errors.append(repr(exc))
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(errors, [])
        got = self.rt.get_entity(self.world['world_instance_id'], e['entity_runtime_id'])
        self.assertEqual(got['data']['v'], 400)
        self.assertEqual(got['version'], 400)
        self.assertEqual(self.rt.event_count(self.world['world_instance_id']), 400)
        self.assertEqual(self.rt.full_integrity_check(self.world['world_instance_id'])['status'], 'PASS')


if __name__ == '__main__':
    unittest.main(verbosity=2)
