import os, tempfile, unittest
from integrated_arpg_engine_v08 import IntegratedARPGEngineV08
from living_runtime import ConflictError

MASTER = os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

class Stage08WorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine=IntegratedARPGEngineV08(':memory:',master_release_path=MASTER)
        created=cls.engine.create_world('stage08:test',80808)
        cls.wid=created['world']['world_instance_id']
        cls.profile=cls.engine.arpg(cls.wid).create_profile('stage08:test',origin_mode='CREATED',display_name='World Tester')['profile']
        cls.world=cls.engine.world_arpg(cls.wid)

    def test_01_health(self): self.assertEqual(self.engine.health_arpg_v08(self.wid)['status'],'PASS')
    def test_02_catalog_counts(self):
        c=self.world.canonical_catalog()['counts']; self.assertEqual(c,{'biomes':10,'climate_zones':8,'basins':6,'rivers':7,'water_bodies':8,'aquifers':4,'regions':8,'locations':18,'routes':25,'territories':13})
    def test_03_one_country(self): self.assertEqual(self.world.verify()['playable_country_count'],1)
    def test_04_zone_count_matches_blocks(self):
        blocks=sum(len(s['blocks']) for s in self.engine.country(self.wid).world['country']['states']); self.assertEqual(len(self.world.list_zones()),blocks)
    def test_05_canonical_biome_binding(self):
        for z in self.world.list_zones():
            self.assertEqual(z['biome']['primary_id'],'BIO-008'); self.assertEqual(z['biome']['major_system_id'],'BIO-002')
    def test_06_climate_binding_and_limits(self):
        for z in self.world.list_zones():
            self.assertEqual(z['environment']['canonical_climate_id'],'CLM-002')
            s=self.world.environment_sample(z['zone_ref'],step=11); self.assertGreaterEqual(s['temperature_c'],2); self.assertLessEqual(s['temperature_c'],33)
    def test_07_hydrology_binding(self):
        for z in self.world.list_zones(): self.assertEqual(z['hydrology_context']['ids'],['BAS-001','RIV-VARDEN'])
    def test_08_outbound_routes_locked(self):
        for rid in ('RTE-001','RTE-003','RTE-013'):
            r=self.world.boundary_route(rid); self.assertTrue(r['boundary_locked']); self.assertEqual(r['playability'],'BOUNDARY_GATE_ONLY')
    def test_09_start_waypoint_discovered(self): self.assertIn('WP-CANON-CIT-001',self.world.profile_state(self.profile['profile_ref'])['discovered_waypoints'])
    def test_10_undiscovered_runtime_waypoint_rejected(self):
        wp=next(w for z in self.world.list_zones() for w in z['waypoints'] if w['waypoint_ref'].startswith('WP-RUNTIME-'))
        out=self.world.fast_travel(self.profile['profile_ref'],wp['waypoint_ref'],event_ref='u:10'); self.assertEqual(out['status'],'REJECTED')
    def test_11_discover_and_fast_travel(self):
        wp=next(w for z in self.world.list_zones() for w in z['waypoints'] if w['waypoint_ref'].startswith('WP-RUNTIME-'))
        a=self.world.discover_waypoint(self.profile['profile_ref'],wp['waypoint_ref'],event_ref='u:11a'); self.assertEqual(a['status'],'PASS')
        b=self.world.fast_travel(self.profile['profile_ref'],wp['waypoint_ref'],event_ref='u:11b'); self.assertEqual(b['status'],'PASS'); self.assertEqual(b['zone_ref'],wp['zone_ref'])
    def test_12_dungeon_enter_exit(self):
        st=self.world.profile_state(self.profile['profile_ref']); current=self.world.zone(st['zone_ref'])
        if not current['dungeons']:
            target=next(z for z in self.world.list_zones() if z['dungeons']); wp=next((w for w in target['waypoints']),None)
            if wp:
                self.world.discover_waypoint(self.profile['profile_ref'],wp['waypoint_ref'],event_ref='u:12d'); self.world.fast_travel(self.profile['profile_ref'],wp['waypoint_ref'],event_ref='u:12t')
            else:
                state=self.world.ensure_profile(self.profile['profile_ref']); state['zone_ref']=target['zone_ref']; state['instance_context']={'kind':'OVERWORLD','ref':target['zone_ref']}; self.world._save_profile(state)
            current=target
        d=current['dungeons'][0]['dungeon_ref']; a=self.world.enter_dungeon(self.profile['profile_ref'],d,event_ref='u:12e'); self.assertEqual(a['status'],'PASS')
        b=self.world.exit_dungeon(self.profile['profile_ref'],event_ref='u:12x'); self.assertEqual(b['status'],'PASS')
    def test_13_wrong_dungeon_rejected(self):
        out=self.world.enter_dungeon(self.profile['profile_ref'],'DNG-NOT-HERE',event_ref='u:13'); self.assertEqual(out['status'],'REJECTED')
    def test_14_event_replay_idempotent(self):
        out1=self.world.discover_waypoint(self.profile['profile_ref'],'WP-CANON-CIT-001',event_ref='u:14'); out2=self.world.discover_waypoint(self.profile['profile_ref'],'WP-CANON-CIT-001',event_ref='u:14'); self.assertTrue(out2['idempotent_replay']); self.assertEqual(out1['world_server_sequence'],out2['world_server_sequence'])
    def test_15_event_ref_conflict(self):
        self.world.discover_waypoint(self.profile['profile_ref'],'WP-CANON-CIT-001',event_ref='u:15')
        wp=next(w for z in self.world.list_zones() for w in z['waypoints'] if w['waypoint_ref'].startswith('WP-RUNTIME-'))
        with self.assertRaises(ConflictError): self.world.discover_waypoint(self.profile['profile_ref'],wp['waypoint_ref'],event_ref='u:15')
    def test_16_environment_deterministic(self):
        z=self.world.list_zones()[0]['zone_ref']; self.assertEqual(self.world.environment_sample(z,step=77),self.world.environment_sample(z,step=77))
    def test_17_root_deep_overlay_preserved(self):
        roots=[z for z in self.world.list_zones() if (z['biome'].get('legacy_procedural_classification') or {}).get('class')=='ROOT_DEEP']
        self.assertTrue(roots)
        for z in roots:
            self.assertEqual(z['anomaly_overlay']['overlay_id'],'BIO-ROOT-DEEP'); self.assertTrue(z['anomaly_overlay']['predator_only']); self.assertFalse(z['anomaly_overlay']['normal_city_allowed']); self.assertFalse(z['anomaly_overlay']['normal_flora_allowed'])
    def test_18_climate_runtime_aliases_consumed(self):
        for z in self.world.list_zones():
            legacy=z['environment']['legacy_procedural_climate']; base=z['environment']['runtime_baseline']
            if 'humidity_pct' in legacy: self.assertEqual(base['humidity_pct'],round(max(10.0,min(98.0,float(legacy['humidity_pct']))),2))
            if 'rainfall_mm_y' in legacy: self.assertEqual(base['annual_precipitation_mm'],round(max(420.0,min(950.0,float(legacy['rainfall_mm_y']))),2))
    def test_19_placeholder_ready(self):
        self.assertTrue(all(z['art_dependency']=='NONE_PLACEHOLDER_READY' for z in self.world.list_zones()))

class Stage08PersistenceTests(unittest.TestCase):
    def test_persistence_resume(self):
        with tempfile.TemporaryDirectory() as td:
            db=os.path.join(td,'stage08.sqlite')
            e=IntegratedARPGEngineV08(db,master_release_path=MASTER); r=e.create_world('persist:test',81818); wid=r['world']['world_instance_id']
            p=e.arpg(wid).create_profile('persist:test',origin_mode='CREATED',display_name='Persist')['profile']; w=e.world_arpg(wid)
            wp=next(x for z in w.list_zones() for x in z['waypoints'] if x['waypoint_ref'].startswith('WP-RUNTIME-'))
            w.discover_waypoint(p['profile_ref'],wp['waypoint_ref'],event_ref='p:discover'); w.fast_travel(p['profile_ref'],wp['waypoint_ref'],event_ref='p:travel')
            before=w.profile_state(p['profile_ref']); e.runtime.close()
            e2=IntegratedARPGEngineV08(db,master_release_path=MASTER); e2.resume_world(wid); after=e2.world_arpg(wid).profile_state(p['profile_ref'])
            self.assertEqual(before,after); self.assertEqual(e2.world_arpg(wid).verify()['status'],'PASS'); e2.runtime.close()

if __name__=='__main__': unittest.main(verbosity=2)
