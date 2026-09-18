from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '01_RUNTIME'))

from integrated_arpg_engine_v01 import IntegratedARPGEngineV01
from living_runtime import ValidationError

MASTER = os.environ.get('ANDROMEDA_MASTER_RELEASE', '/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')


class ARPGGameCoreStage01Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, 'stage01-shared.sqlite')
        cls.engine = IntegratedARPGEngineV01(cls.db, master_release_path=MASTER)
        report = cls.engine.create_world('stage01-tests', 1201, load_relationships=False)
        cls.wid = report['world']['world_instance_id']
        cls.core = cls.engine.arpg(cls.wid)
        cls.profile_counter = 0

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()
        cls.tmp.cleanup()

    def created(self, name='Stage01 Hero', scope=None):
        type(self).profile_counter += 1
        scope = scope or f'local:test:{type(self).profile_counter}'
        return self.core.create_profile(scope, origin_mode='CREATED', display_name=f'{name} {type(self).profile_counter}')['profile']

    def test_created_profile_is_runtime_derived_and_classless(self):
        p = self.created()
        npc = self.engine.country(self.wid).npc(p['avatar_ref'])
        self.assertEqual(p['origin_mode'], 'CREATED')
        self.assertIsNone(p['canonical_ref'])
        self.assertEqual(p['progression']['class_model'], 'EMERGENT_FROM_PLAYER_CHOICES')
        self.assertIsNone(p['progression']['emergent_class'])
        self.assertEqual(npc['class'], 'PLAYER_AVATAR')
        self.assertIsNone(npc['emergent_class'])
        self.assertEqual(self.engine.health_arpg_v01(self.wid)['status'], 'PASS')
        snap = self.core.client_snapshot(p['profile_ref'])
        self.assertTrue(snap['server_authoritative'])
        self.assertEqual(snap['control_scheme'], 'MOUSE_POINTER_DIABLO_LIKE')
        self.assertEqual(snap['network_model'], 'SINGLE_PLAYER_FIRST_MULTIPLAYER_READY')
        self.assertEqual(snap['art_dependency'], 'NONE_PLACEHOLDER_READY')

    def test_canonical_profile_resolves_master_character_and_locks_name(self):
        p = self.core.create_profile('local:canon', origin_mode='CANONICAL', canonical_ref='PER-002')['profile']
        self.assertEqual(p['display_name'], 'Kenua Vaarn')
        self.assertEqual(p['canonical_ref'], 'PER-002')
        self.assertEqual(p['canonical_character_metadata']['domain'], 'narrativa/personagens')
        with self.assertRaises(ValidationError):
            self.core.create_profile('local:badname', origin_mode='CANONICAL', canonical_ref='PER-003', display_name='Override')

    def test_non_character_canonical_ref_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.core.create_profile('local:invalid', origin_mode='CANONICAL', canonical_ref='TIM-027')

    def test_profile_activation_is_single_and_owner_checked(self):
        p1 = self.created('Hero One', 'local:switch')
        p2 = self.core.create_profile('local:switch', origin_mode='CREATED', display_name='Hero Two', activate=False)['profile']
        self.assertTrue(self.core.profile(p1['profile_ref'])['active'])
        denied = self.core.activate_profile(p2['profile_ref'], controller_scope='local:wrong')
        self.assertEqual(denied['reason'], 'PROFILE_OWNERSHIP_MISMATCH')
        ok = self.core.activate_profile(p2['profile_ref'], controller_scope='local:switch')
        self.assertEqual(ok['status'], 'PASS')
        self.assertFalse(self.core.profile(p1['profile_ref'])['active'])
        self.assertTrue(self.core.profile(p2['profile_ref'])['active'])
        self.assertEqual(sum(1 for x in self.core.list_profiles() if x['controller_scope']=='local:switch' and x['active']), 1)

    def test_pointer_ground_click_starts_and_finishes_movement(self):
        p = self.created()
        m = self.engine.movement(self.wid)
        before = m.state(p['avatar_ref'])
        result = self.core.submit_command(p['controller_scope'], p['profile_ref'], 1, 'POINTER_PRIMARY', {
            'iso_x_m': before['iso_x_m'] + 1.5,
            'iso_y_m': before['iso_y_m'],
            'mode': 'WALK',
        })
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['movement_intent'], 'STARTED')
        frames = []
        for _ in range(20):
            frame = self.core.tick(p['profile_ref'], delta_s=0.1)
            frames.append(frame['frame_state'])
            if frame['frame_state'] == 'ARRIVED':
                break
        after = m.state(p['avatar_ref'])
        self.assertGreater(after['iso_x_m'], before['iso_x_m'])
        self.assertIn('ARRIVED', frames)
        self.assertIsNone(self.core.client_snapshot(p['profile_ref'])['input_state']['move_target'])

    def test_local_pointer_range_guard(self):
        p = self.created()
        st = self.engine.movement(self.wid).state(p['avatar_ref'])
        out = self.core.submit_command(p['controller_scope'], p['profile_ref'], 1, 'MOVE_POINTER', {
            'iso_x_m': st['iso_x_m'] + self.core.MAX_POINTER_DISTANCE_M + 10,
            'iso_y_m': st['iso_y_m'],
        })
        self.assertEqual(out['status'], 'REJECTED')
        self.assertEqual(out['reason'], 'POINTER_DESTINATION_OUT_OF_LOCAL_RANGE')

    def test_command_sequence_replay_conflict_and_out_of_order(self):
        p = self.created()
        first = self.core.submit_command(p['controller_scope'], p['profile_ref'], 1, 'SELECT_TARGET', {'target_ref': None})
        replay = self.core.submit_command(p['controller_scope'], p['profile_ref'], 1, 'SELECT_TARGET', {'target_ref': None})
        conflict = self.core.submit_command(p['controller_scope'], p['profile_ref'], 1, 'CANCEL_ACTION', {})
        gap = self.core.submit_command(p['controller_scope'], p['profile_ref'], 3, 'CANCEL_ACTION', {})
        second = self.core.submit_command(p['controller_scope'], p['profile_ref'], 2, 'CANCEL_ACTION', {})
        self.assertEqual(first['status'], 'PASS')
        self.assertTrue(replay['idempotent_replay'])
        self.assertEqual(replay['command_ref'], first['command_ref'])
        self.assertEqual(conflict['reason'], 'CLIENT_SEQUENCE_CONFLICT')
        self.assertEqual(gap['reason'], 'OUT_OF_ORDER_CLIENT_SEQUENCE')
        self.assertEqual(second['status'], 'PASS')
        self.assertEqual([x['client_sequence'] for x in self.core.command_history(p['profile_ref'])], [1, 2])

    def test_profile_ownership_is_enforced_on_commands(self):
        p = self.created()
        out = self.core.submit_command('other:user', p['profile_ref'], 1, 'CANCEL_ACTION', {})
        self.assertEqual(out['status'], 'REJECTED')
        self.assertEqual(out['reason'], 'PROFILE_OWNERSHIP_MISMATCH')
        self.assertEqual(len(self.core.command_history(p['profile_ref'])), 0)

    def test_target_selection_and_scene_interaction_route(self):
        p = self.created()
        country = self.engine.country(self.wid)
        obj = None
        for st in country.world['country']['states']:
            for block in st['blocks']:
                for city in block.get('cities', []):
                    candidate = next((o for o in city.get('scene_objects', []) if o.get('object_type') == 'DOOR' and not o.get('locked')), None)
                    if candidate:
                        obj = candidate
                        target_city = city
                        target_block = block
                        break
                if obj:
                    break
            if obj:
                break
        self.assertIsNotNone(obj)
        country.relocate_npc(p['avatar_ref'], target_block['id'], destination_city_id=target_city['id'])
        cc = obj['coordinate_center']
        sp = self.engine.spatial(self.wid)
        oi = sp.geodetic_to_isometric(cc['longitude'], cc['latitude'], cc.get('altitude_m', 0))
        near = sp.isometric_to_geodetic(oi['iso_x_m'] - 1.5, oi['iso_y_m'], oi['altitude_m'])
        self.engine.movement(self.wid).sync_to_geodetic(p['avatar_ref'], near, reason='STAGE01_TEST')
        self.engine.streaming(self.wid).transfer(p['avatar_ref'], sp.chunk_for_geodetic(near['longitude'], near['latitude'])['chunk_id'])
        out = self.core.submit_command(p['controller_scope'], p['profile_ref'], 1, 'POINTER_PRIMARY', {'target_ref': obj['id'], 'interaction_action': 'OPEN'})
        self.assertEqual(out['status'], 'PASS')
        self.assertEqual(out['route'], 'INTERACTION')
        self.assertEqual(out['resolved_action'], 'OPEN')

    def test_npc_primary_action_routes_without_premature_combat_implementation(self):
        p = self.created()
        npc = next(n for n in self.engine.country(self.wid)._all_npc_records() if n['id'] != p['avatar_ref'])
        out = self.core.submit_command(p['controller_scope'], p['profile_ref'], 1, 'POINTER_PRIMARY', {'target_ref': npc['id']})
        self.assertEqual(out['status'], 'PASS')
        self.assertEqual(out['route'], 'NPC_CONTEXT')
        self.assertEqual(out['implementation_stage'], 'COMBAT_STAGE03_DIALOGUE_STAGE11')

    def test_pause_freezes_pointer_tick_and_resume_continues(self):
        p = self.created()
        st = self.engine.movement(self.wid).state(p['avatar_ref'])
        self.core.submit_command(p['controller_scope'], p['profile_ref'], 1, 'MOVE_POINTER', {'iso_x_m': st['iso_x_m'] + 2, 'iso_y_m': st['iso_y_m'], 'mode': 'WALK'})
        paused = self.core.submit_command(p['controller_scope'], p['profile_ref'], 2, 'PAUSE', {})
        before = self.engine.movement(self.wid).state(p['avatar_ref'])
        frame = self.core.tick(p['profile_ref'], delta_s=0.2)
        after = self.engine.movement(self.wid).state(p['avatar_ref'])
        self.assertEqual(paused['clock_state'], 'PAUSED')
        self.assertEqual(frame['frame_state'], 'PAUSED')
        self.assertEqual((before['iso_x_m'], before['iso_y_m']), (after['iso_x_m'], after['iso_y_m']))
        resumed = self.core.submit_command(p['controller_scope'], p['profile_ref'], 3, 'RESUME', {})
        moved = self.core.tick(p['profile_ref'], delta_s=0.2)
        self.assertEqual(resumed['clock_state'], 'RUNNING')
        self.assertIn(moved['frame_state'], {'MOVING', 'ARRIVED'})



class ARPGGameCoreStage01PersistenceTests(unittest.TestCase):
    def test_persistence_resume_preserves_profile_command_and_pointer_state(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, 'resume.sqlite')
            engine = IntegratedARPGEngineV01(db, master_release_path=MASTER)
            report = engine.create_world('stage01-persistence', 1201, load_relationships=False)
            wid = report['world']['world_instance_id']
            core = engine.arpg(wid)
            p = core.create_profile('local:persist', origin_mode='CREATED', display_name='Persistent Hero')['profile']
            st = engine.movement(wid).state(p['avatar_ref'])
            core.submit_command('local:persist', p['profile_ref'], 1, 'MOVE_POINTER', {'iso_x_m': st['iso_x_m'] + 4, 'iso_y_m': st['iso_y_m'], 'mode': 'WALK'})
            core.tick(p['profile_ref'], delta_s=0.1)
            before = core.client_snapshot(p['profile_ref'])
            engine.close()
            engine = IntegratedARPGEngineV01(db, master_release_path=MASTER)
            try:
                resumed = engine.resume_world(wid)
                core = engine.arpg(wid)
                after = core.client_snapshot(p['profile_ref'])
                self.assertEqual(resumed['status'], 'PASS')
                self.assertEqual(after['profile']['profile_ref'], before['profile']['profile_ref'])
                self.assertEqual(after['input_state']['last_client_sequence'], 1)
                self.assertIsNotNone(after['input_state']['move_target'])
                self.assertEqual(core.verify()['status'], 'PASS')
                next_cmd = core.submit_command('local:persist', p['profile_ref'], 2, 'CANCEL_ACTION', {})
                self.assertEqual(next_cmd['status'], 'PASS')
            finally:
                engine.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
