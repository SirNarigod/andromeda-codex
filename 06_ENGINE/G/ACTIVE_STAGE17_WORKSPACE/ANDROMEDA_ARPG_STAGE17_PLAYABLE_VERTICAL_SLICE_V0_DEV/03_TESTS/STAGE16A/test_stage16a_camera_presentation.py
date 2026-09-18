from __future__ import annotations
import pathlib, sys, unittest
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "01_RUNTIME"))
from arpg_camera_presentation_core import CameraPresentationCore, CAMERA_CANDIDATES

class Stage16ACameraPresentationTests(unittest.TestCase):
    def setUp(self): self.c=CameraPresentationCore()
    def test_01_stable_isometric_contract(self): self.assertEqual(self.c.contract()['camera_mode'],'STABLE_ISOMETRIC_OBLIQUE')
    def test_02_free_orbit_not_default(self): self.assertFalse(self.c.base_rig()['free_orbit'])
    def test_03_camera_never_pauses_world(self): self.assertFalse(self.c.contract()['world_pause'])
    def test_04_zoom_clamps_too_near(self): self.assertEqual(self.c.clamp_zoom_distance(1)['distance_m'],CAMERA_CANDIDATES['min_distance_m'])
    def test_05_zoom_clamps_too_far(self): self.assertEqual(self.c.clamp_zoom_distance(99)['distance_m'],CAMERA_CANDIDATES['max_distance_m'])
    def test_06_zoom_inside_range_preserved(self): self.assertEqual(self.c.clamp_zoom_distance(14)['distance_m'],14)
    def test_07_zoom_step_in(self): self.assertLess(self.c.zoom_step(14,'IN')['distance_m'],14)
    def test_08_zoom_step_out(self): self.assertGreater(self.c.zoom_step(14,'OUT')['distance_m'],14)
    def test_09_invalid_zoom_direction_rejected(self): self.assertEqual(self.c.zoom_step(14,'SIDE')['status'],'REJECTED')
    def test_10_micro_relief_does_not_bob_camera(self):
        x=self.c.height_follow(previous_smoothed_altitude_m=10,anchor_altitude_m=10.05,delta_seconds=1/60); self.assertTrue(x['micro_relief_filtered']); self.assertEqual(x['smoothed_altitude_m'],10)
    def test_11_real_height_change_smoothed_not_teleported(self):
        x=self.c.height_follow(previous_smoothed_altitude_m=10,anchor_altitude_m=12,delta_seconds=1/60); self.assertFalse(x['micro_relief_filtered']); self.assertGreater(x['smoothed_altitude_m'],10); self.assertLess(x['smoothed_altitude_m'],12); self.assertFalse(x['teleport'])
    def test_12_zero_dt_does_not_jump(self): self.assertEqual(self.c.height_follow(previous_smoothed_altitude_m=10,anchor_altitude_m=12,delta_seconds=0)['smoothed_altitude_m'],10)
    def test_13_occluder_fades_before_camera_jump(self):
        x=self.c.occlusion_policy(obstacle_ref='TREE',blocks_player_view=True,transparent_safe=True); self.assertEqual(x['action'],'FADE_OCCLUDER'); self.assertFalse(x['camera_reposition'])
    def test_14_unsafe_fade_uses_collision_shortening_without_abrupt_jump(self):
        x=self.c.occlusion_policy(obstacle_ref='WALL',blocks_player_view=True,transparent_safe=False); self.assertEqual(x['action'],'CAMERA_COLLISION_SHORTEN_DISTANCE'); self.assertFalse(x['abrupt_jump_allowed'])
    def test_15_clear_obstacle_restores_opacity(self): self.assertEqual(self.c.occlusion_policy(obstacle_ref='TREE',blocks_player_view=False)['action'],'RESTORE_OPACITY')
    def test_16_context_does_not_force_zoom_or_rotation(self):
        for ctx in ['OVERWORLD','COMBAT','INTERIOR','DUNGEON','VEHICLE','BOSS']:
            x=self.c.context_policy(ctx); self.assertFalse(x['forced_zoom']); self.assertFalse(x['forced_rotation'])
    def test_17_visual_impulse_cannot_rewrite_pointer_intent(self): self.assertFalse(self.c.pointer_stability_guard(feedback_impulse_active=True,pointer_action_pending=True)['re_resolve_world_target_due_to_visual_impulse'])
    def test_18_deterministic_signature(self): self.assertEqual(self.c.deterministic_signature(),CameraPresentationCore().deterministic_signature())

if __name__=='__main__': unittest.main(verbosity=2)
