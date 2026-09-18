from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "01_RUNTIME"
sys.path.insert(0, str(RUNTIME))

from integrated_arpg_engine_v02 import IntegratedARPGEngineV02
from living_runtime import ValidationError, ConflictError
from character_core import CORE_ATTRIBUTES, CharacterCore

MASTER = os.environ.get("ANDROMEDA_MASTER_RELEASE", str(Path("/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip")))


class CharacterCoreStage02Tests(unittest.TestCase):
    def setUp(self):
        self.engine = IntegratedARPGEngineV02(':memory:', master_release_path=MASTER)
        report = self.engine.create_world('stage02-tests', 2202, load_relationships=False)
        self.wid = report['world']['world_instance_id']
        self.arpg = self.engine.arpg(self.wid)
        self.character = self.engine.character(self.wid)

    def tearDown(self):
        self.engine.close()

    def create(self, name='Stage02 Hero', scope='local:stage02'):
        return self.arpg.create_profile(scope, origin_mode='CREATED', display_name=name)['profile']

    def test_created_profile_bootstraps_character_sheet(self):
        p = self.create()
        s = self.character.state(p['profile_ref'])
        self.assertEqual(s['level'], 1)
        self.assertEqual(s['experience'], 0)
        self.assertEqual(set(s['attributes']), set(CORE_ATTRIBUTES))
        self.assertTrue(all(v == CharacterCore.BASE_ATTRIBUTE for v in s['attributes'].values()))
        self.assertEqual(s['vitals']['life_state'], 'ALIVE')
        self.assertEqual(s['vitals']['health'], s['derived']['max_health'])
        self.assertEqual(s['vitals']['resource'], s['derived']['max_resource'])
        self.assertEqual(s['numeric_authority'], 'GAMEPLAY_DERIVED_NOT_CANON')

    def test_canonical_profile_uses_same_noncanonical_numeric_baseline(self):
        p = self.arpg.create_profile('local:canon02', origin_mode='CANONICAL', canonical_ref='PER-002')['profile']
        s = self.character.state(p['profile_ref'])
        self.assertEqual(s['canonical_ref'], 'PER-002')
        self.assertEqual(s['attributes'], {k: CharacterCore.BASE_ATTRIBUTE for k in CORE_ATTRIBUTES})
        self.assertEqual(s['numeric_authority'], 'GAMEPLAY_DERIVED_NOT_CANON')

    def test_xp_curve_level_up_and_points(self):
        p = self.create()
        need = self.character.xp_to_next(1)
        out = self.character.award_experience(p['profile_ref'], need, event_ref='xp:level2')
        s = self.character.state(p['profile_ref'])
        self.assertEqual(out['level_after'], 2)
        self.assertEqual(out['levels_gained'], 1)
        self.assertEqual(s['unspent_attribute_points'], CharacterCore.ATTRIBUTE_POINTS_PER_LEVEL)
        self.assertEqual(s['experience_into_level'], 0)

    def test_xp_event_is_idempotent_and_conflict_safe(self):
        p = self.create()
        a = self.character.award_experience(p['profile_ref'], 50, event_ref='xp:once')
        b = self.character.award_experience(p['profile_ref'], 50, event_ref='xp:once')
        self.assertFalse(a['idempotent_replay'])
        self.assertTrue(b['idempotent_replay'])
        self.assertEqual(self.character.state(p['profile_ref'])['experience'], 50)
        with self.assertRaises(ConflictError):
            self.character.award_experience(p['profile_ref'], 51, event_ref='xp:once')

    def test_allocate_attributes_updates_derived_and_build_evidence(self):
        p = self.create()
        need = self.character.xp_to_next(1)
        self.character.award_experience(p['profile_ref'], need, event_ref='xp:alloc')
        before = self.character.state(p['profile_ref'])
        out = self.character.allocate_attributes(p['profile_ref'], {'vitality': 3, 'power': 2}, event_ref='attr:1')
        after = self.character.state(p['profile_ref'])
        self.assertEqual(out['unspent_attribute_points'], 0)
        self.assertEqual(after['attributes']['VITALITY'], 13)
        self.assertEqual(after['attributes']['POWER'], 12)
        self.assertGreater(after['derived']['max_health'], before['derived']['max_health'])
        self.assertEqual(after['build_evidence']['attribute_investment']['VITALITY'], 3)
        self.assertIsNone(after['build_evidence']['emergent_class'])

    def test_allocation_rejects_overspend_and_unknown_attribute(self):
        p = self.create()
        with self.assertRaises(ConflictError):
            self.character.allocate_attributes(p['profile_ref'], {'POWER': 1}, event_ref='attr:no-points')
        with self.assertRaises(ValidationError):
            self.character.allocate_attributes(p['profile_ref'], {'LUCK': 1}, event_ref='attr:bad')

    def test_health_damage_death_and_dead_action_gate(self):
        p = self.create()
        s = self.character.state(p['profile_ref'])
        dead = self.character.apply_health_change(p['profile_ref'], -float(s['derived']['max_health']), event_ref='hp:dead', source_type='TEST')
        self.assertEqual(dead['life_state'], 'DEAD')
        command = self.arpg.submit_command(p['controller_scope'], p['profile_ref'], 1, 'MOVE_POINTER', {'iso_x_m': 1, 'iso_y_m': 1})
        self.assertEqual(command['status'], 'REJECTED')
        self.assertEqual(command['reason'], 'CHARACTER_DEAD')
        tick = self.arpg.tick(p['profile_ref'], delta_s=0.1)
        self.assertEqual(tick['frame_state'], 'DEAD')
        with self.assertRaises(ConflictError):
            self.character.apply_health_change(p['profile_ref'], 10, event_ref='hp:no-revive')

    def test_regeneration_is_bounded_and_persistent(self):
        p = self.create()
        self.character.apply_health_change(p['profile_ref'], -20, event_ref='hp:damage')
        self.character.apply_resource_change(p['profile_ref'], -15, event_ref='res:spend')
        before = self.character.state(p['profile_ref'])
        tick = self.character.tick_profile(p['profile_ref'], 1.0)
        after = self.character.state(p['profile_ref'])
        self.assertTrue(tick['changed'])
        self.assertGreater(after['vitals']['health'], before['vitals']['health'])
        self.assertGreater(after['vitals']['resource'], before['vitals']['resource'])
        self.assertLessEqual(after['vitals']['health'], after['derived']['max_health'])
        self.assertLessEqual(after['vitals']['resource'], after['derived']['max_resource'])

    def test_snapshot_exposes_character_without_art_dependency(self):
        p = self.create()
        snap = self.arpg.client_snapshot(p['profile_ref'])
        self.assertIsNotNone(snap['character'])
        self.assertEqual(snap['character']['profile_ref'], p['profile_ref'])
        self.assertEqual(snap['character']['art_dependency'], 'NONE_PLACEHOLDER_READY')

    def test_verify_passes_with_multiple_controllers(self):
        self.create('One', 'controller:1')
        self.create('Two', 'controller:2')
        self.assertEqual(self.character.verify()['status'], 'PASS')
        self.assertEqual(self.engine.health_arpg_v02(self.wid)['status'], 'PASS')


class CharacterCoreStage02PersistenceTests(unittest.TestCase):
    def test_upgrade_resume_and_character_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, 'stage02.sqlite')
            engine = IntegratedARPGEngineV02(db, master_release_path=MASTER)
            report = engine.create_world('stage02-persist', 2203, load_relationships=False)
            wid = report['world']['world_instance_id']
            p = engine.arpg(wid).create_profile('local:persist02', origin_mode='CREATED', display_name='Persistent')['profile']
            core = engine.character(wid)
            core.award_experience(p['profile_ref'], core.xp_to_next(1), event_ref='xp:persist')
            core.allocate_attributes(p['profile_ref'], {'VITALITY': 5}, event_ref='attr:persist')
            before = core.state(p['profile_ref'])
            engine.close()
            engine = IntegratedARPGEngineV02(db, master_release_path=MASTER)
            try:
                resumed = engine.resume_world(wid)
                after = engine.character(wid).state(p['profile_ref'])
                self.assertEqual(resumed['status'], 'PASS')
                self.assertEqual(after, before)
                self.assertEqual(engine.character(wid).verify()['status'], 'PASS')
            finally:
                engine.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
