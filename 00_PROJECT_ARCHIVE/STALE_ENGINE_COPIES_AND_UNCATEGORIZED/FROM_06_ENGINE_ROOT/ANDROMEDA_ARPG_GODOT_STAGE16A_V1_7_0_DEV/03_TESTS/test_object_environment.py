import os, sqlite3, tempfile, threading, unittest, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '01_RUNTIME'))
from living_runtime import LivingRuntime, ValidationError, IntegrityError, ConflictError, OfflinePolicyError, new_runtime_id, clock_point
from object_environment import ObjectEnvironmentSystem

MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'

class ObjCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=os.path.join(self.tmp.name,'w.db')
        self.rt=LivingRuntime(self.db,master_release_path=MASTER); self.w=self.rt.create_world('obj-test',808,ticks_per_day=24); self.wid=self.w['world_instance_id']
        self.sys=ObjectEnvironmentSystem(self.rt)
        self.actor=self._actor()
        self.doorp=self.sys.register_profile(self.wid,{'object_class':'DOOR','material_class':'WOOD','flammable':True,'supports_open':True,'supports_lock':True,'base_integrity':100,'ignition_temperature':100,'water_absorption':1})
        self.metp=self.sys.register_profile(self.wid,{'object_class':'MACHINE','material_class':'METAL','flammable':False,'supports_activation':True,'base_integrity':100,'heat_resistance':.8})
        self.flrp=self.sys.register_profile(self.wid,{'object_class':'FLORA','material_class':'ORGANIC','flammable':True,'harvestable':True,'base_integrity':50,'ignition_temperature':80,'water_absorption':1})
        self.bridgep=self.sys.register_profile(self.wid,{'object_class':'BRIDGE','material_class':'STONE','flammable':False,'base_integrity':100})
    def tearDown(self):
        try:self.rt.close()
        except:pass
        self.tmp.cleanup()
    def _actor(self):
        w=self.rt.get_world(self.wid);c=w['clock_state']
        s={'state_id':new_runtime_id('state'),'world_instance_id':self.wid,'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{},'protection':{}}
        return self.rt.register_entity(self.wid,s)
    def obj(self,p=None,**kw): return self.sys.spawn_object(self.wid,profile_id=(p or self.doorp)['profile_id'],**kw)
    def interact(self,o,t,**kw):return self.sys.interact(self.wid,actor_ref=self.actor['entity_runtime_id'],target_ref=o['entity_runtime_id'],interaction_type=t,**kw)

class ProfileTests(ObjCase):
    def test_runtime_authority(self): self.assertEqual(self.doorp['authority'],'RUNTIME_REACTIVE_PROFILE_NOT_CANON')
    def test_unknown_class(self):
        with self.assertRaises(ValidationError):self.sys.register_profile(self.wid,{'object_class':'SENTIENT_CHAIR'})
    def test_unknown_material(self):
        with self.assertRaises(ValidationError):self.sys.register_profile(self.wid,{'object_class':'DOOR','material_class':'MAGIC'})
    def test_invalid_integrity(self):
        with self.assertRaises(ValidationError):self.sys.register_profile(self.wid,{'object_class':'DOOR','base_integrity':101})
    def test_invalid_recovery_policy(self):
        with self.assertRaises(ValidationError):self.sys.register_profile(self.wid,{'object_class':'DOOR','recovery_policy':'NEVER'})
    def test_noncanon_authority_rejected(self):
        with self.assertRaises(ValidationError):self.sys.register_profile(self.wid,{'object_class':'DOOR','authority':'CANON'})
    def test_profile_hash_corruption_detected(self):
        pid=self.doorp['profile_id'];self.rt.conn.execute("UPDATE reactive_profiles SET profile_json='{}' WHERE profile_id=?",(pid,))
        with self.assertRaises(IntegrityError):self.sys.get_profile(self.wid,pid)

class SpawnTests(ObjCase):
    def test_spawn_door(self):
        o=self.obj();self.assertEqual(o['entity_kind'],'OBJECT');self.assertTrue(o['data']['functional'])
    def test_spawn_canonical_weapon(self):
        o=self.obj(self.metp,canonical_ref='WPN-024');self.assertEqual(o['canonical_ref'],'WPN-024')
    def test_unknown_canonical_ref(self):
        with self.assertRaises(ValidationError):self.obj(canonical_ref='WPN-999')
    def test_bridge_kind_structure(self): self.assertEqual(self.obj(self.bridgep)['entity_kind'],'STRUCTURE')
    def test_flora_kind(self): self.assertEqual(self.obj(self.flrp)['entity_kind'],'FLORA_INSTANCE')
    def test_invalid_open_locked_bootstrap(self):
        with self.assertRaises(ValidationError):self.obj(data={'open':True,'locked':True})
    def test_nonflammable_bootstrap_burning_blocked(self):
        with self.assertRaises(ValidationError):self.obj(self.metp,data={'burning':True})
    def test_zone_membership_validated(self):
        z=self.sys.create_environment_zone(self.wid,canonical_ref='POI-006');o=self.obj(zone_ref=z['entity_runtime_id']);self.assertEqual(o['data']['zone_ref'],z['entity_runtime_id'])
    def test_non_zone_ref_blocked(self):
        other=self.obj()
        with self.assertRaises(ValidationError):self.obj(zone_ref=other['entity_runtime_id'])

class DoorStateTests(ObjCase):
    def test_open(self):o=self.obj();self.interact(o,'OPEN');self.assertTrue(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['open'])
    def test_close(self):o=self.obj(data={'open':True});self.interact(o,'CLOSE');self.assertFalse(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['open'])
    def test_lock(self):o=self.obj();self.interact(o,'LOCK');self.assertTrue(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['locked'])
    def test_open_locked_blocked(self):o=self.obj(data={'locked':True});
    def test_unlock(self):o=self.obj(data={'locked':True});self.interact(o,'UNLOCK');self.assertFalse(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['locked'])
    def test_lock_open_blocked(self):
        o=self.obj(data={'open':True})
        with self.assertRaises(ConflictError):self.interact(o,'LOCK')
    def test_unsupported_open(self):
        o=self.obj(self.metp)
        with self.assertRaises(ValidationError):self.interact(o,'OPEN')
    def test_machine_activation(self):o=self.obj(self.metp);self.interact(o,'ACTIVATE');self.assertTrue(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['active'])
    def test_machine_deactivation(self):o=self.obj(self.metp,data={'active':True});self.interact(o,'DEACTIVATE');self.assertFalse(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['active'])

# fix isolated test method body intentionally below
DoorStateTests.test_open_locked_blocked=lambda self: (lambda o: self.assertRaises(ConflictError, self.interact, o, 'OPEN'))(self.obj(data={'locked':True}))

class DamageRecoveryTests(ObjCase):
    def test_damage_reduces_integrity(self):o=self.obj();self.interact(o,'DAMAGE',amount=25);self.assertEqual(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['integrity'],75)
    def test_damage_destroy_sets_state(self):
        o=self.obj();self.interact(o,'DAMAGE',amount=100);s=self.rt.get_entity(self.wid,o['entity_runtime_id']);self.assertEqual(s['lifecycle'],'DESTROYED');self.assertFalse(s['data']['functional'])
    def test_destroy_schedules_recovery_day7(self):
        o=self.obj();self.interact(o,'DAMAGE',amount=100);r=self.rt.conn.execute('SELECT destroyed_at_day,due_at_day FROM recoveries WHERE target_ref=?',(o['entity_runtime_id'],)).fetchone();self.assertEqual(r['due_at_day']-r['destroyed_at_day'],7)
    def test_recovery_restores_integrity(self):
        o=self.obj();self.interact(o,'DAMAGE',amount=100);self.rt.advance_ticks(self.wid,7*24);self.rt.process_due_recoveries(self.wid);s=self.rt.get_entity(self.wid,o['entity_runtime_id']);self.assertEqual(s['lifecycle'],'ACTIVE');self.assertEqual(s['data']['integrity'],100);self.assertTrue(s['data']['functional'])
    def test_history_preserved_after_recovery(self):
        o=self.obj();self.interact(o,'DAMAGE',amount=100);before=self.rt.event_count(self.wid);self.rt.advance_ticks(self.wid,7*24);self.rt.process_due_recoveries(self.wid);self.assertGreater(self.rt.event_count(self.wid),before)
    def test_manual_repair_caps_at_base(self):o=self.obj(data={'integrity':80});self.interact(o,'REPAIR',amount=50);self.assertEqual(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['integrity'],100)
    def test_destroyed_rejects_open(self):
        o=self.obj();self.interact(o,'DAMAGE',amount=100)
        with self.assertRaises(ConflictError):self.interact(o,'OPEN')

class FireWaterTests(ObjCase):
    def test_ignite_flammable(self):o=self.obj();self.interact(o,'IGNITE');self.assertTrue(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['burning'])
    def test_nonflammable_ignite_blocked(self):
        o=self.obj(self.metp)
        with self.assertRaises(ConflictError):self.interact(o,'IGNITE')
    def test_wet_object_ignite_blocked(self):
        o=self.obj(data={'wetness':80})
        with self.assertRaises(ConflictError):self.interact(o,'IGNITE')
    def test_extinguish(self):o=self.obj(data={'burning':True,'fire_intensity':50,'temperature':120});self.interact(o,'EXTINGUISH');s=self.rt.get_entity(self.wid,o['entity_runtime_id']);self.assertFalse(s['data']['burning']);self.assertEqual(s['data']['fire_intensity'],0)
    def test_heat_auto_ignites(self):o=self.obj();self.interact(o,'HEAT',amount=100);self.assertTrue(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['burning'])
    def test_heat_resistance(self):o=self.obj(self.metp);self.interact(o,'HEAT',amount=100);self.assertAlmostEqual(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['temperature'],40)
    def test_soak_extinguishes_at_threshold(self):o=self.obj(data={'burning':True,'fire_intensity':50,'wetness':55,'temperature':120});self.interact(o,'SOAK',amount=10);self.assertFalse(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['burning'])
    def test_dry_floor_zero(self):o=self.obj(data={'wetness':5});self.interact(o,'DRY',amount=50);self.assertEqual(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['wetness'],0)
    def test_cool_floor(self):o=self.obj(data={'temperature':-190});self.interact(o,'COOL',amount=100);self.assertEqual(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['temperature'],-200)

class ResourceTests(ObjCase):
    def test_harvest(self):o=self.obj(self.flrp,data={'resource_quantity':10});self.interact(o,'HARVEST',amount=3);self.assertEqual(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['resource_quantity'],7)
    def test_harvest_insufficient(self):
        o=self.obj(self.flrp,data={'resource_quantity':2})
        with self.assertRaises(ConflictError):self.interact(o,'HARVEST',amount=3)
    def test_nonharvestable_blocked(self):
        o=self.obj()
        with self.assertRaises(ValidationError):self.interact(o,'HARVEST',amount=1)
    def test_concurrent_harvest_never_negative(self):
        o=self.obj(self.flrp,data={'resource_quantity':10});res=[];lock=threading.Lock()
        def f():
            try:self.interact(o,'HARVEST',amount=1);x='PASS'
            except Exception as e:x=type(e).__name__
            with lock:res.append(x)
        ts=[threading.Thread(target=f) for _ in range(20)];[t.start() for t in ts];[t.join(10) for t in ts]
        self.assertTrue(all(not t.is_alive() for t in ts));s=self.rt.get_entity(self.wid,o['entity_runtime_id']);self.assertEqual(s['data']['resource_quantity'],0);self.assertEqual(res.count('PASS'),10)

class EnvironmentTests(ObjCase):
    def test_create_zone(self):z=self.sys.create_environment_zone(self.wid,canonical_ref='POI-006');self.assertEqual(z['entity_kind'],'ENVIRONMENT_ZONE')
    def test_invalid_zone_value(self):
        with self.assertRaises(ValidationError):self.sys.create_environment_zone(self.wid,humidity=101)
    def test_zone_update_bounded(self):z=self.sys.create_environment_zone(self.wid,fire_intensity=95);self.sys.update_environment(self.wid,z['entity_runtime_id'],deltas={'fire_intensity':20});self.assertEqual(self.rt.get_entity(self.wid,z['entity_runtime_id'])['data']['fire_intensity'],100)
    def test_bad_zone_field(self):
        z=self.sys.create_environment_zone(self.wid)
        with self.assertRaises(ValidationError):self.sys.update_environment(self.wid,z['entity_runtime_id'],deltas={'gravity':1})
    def test_environment_link(self):z=self.sys.create_environment_zone(self.wid);o=self.obj();r=self.sys.link(self.wid,z['entity_runtime_id'],o['entity_runtime_id'],link_type='ENVIRONMENT_MEMBER');self.assertEqual(r['authority'],'RUNTIME_SPATIAL_REACTION_LINK_NOT_CANON')
    def test_self_link_blocked(self):
        o=self.obj()
        with self.assertRaises(ValidationError):self.sys.link(self.wid,o['entity_runtime_id'],o['entity_runtime_id'])
    def test_invalid_link_type(self):
        a=self.obj();b=self.obj()
        with self.assertRaises(ValidationError):self.sys.link(self.wid,a['entity_runtime_id'],b['entity_runtime_id'],link_type='TELEPATHIC')
    def test_fire_zone_heats_member(self):
        z=self.sys.create_environment_zone(self.wid,fire_intensity=100);o=self.obj();self.sys.link(self.wid,z['entity_runtime_id'],o['entity_runtime_id'],link_type='ENVIRONMENT_MEMBER');self.sys.simulate_environment_tick(self.wid,tick_key='t1');self.assertGreater(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['temperature'],20)
    def test_water_zone_soaks_member(self):
        z=self.sys.create_environment_zone(self.wid,water_level=100);o=self.obj();self.sys.link(self.wid,z['entity_runtime_id'],o['entity_runtime_id'],link_type='ENVIRONMENT_MEMBER');self.sys.simulate_environment_tick(self.wid,tick_key='t1');self.assertGreater(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['wetness'],0)
    def test_burning_member_increases_zone(self):
        z=self.sys.create_environment_zone(self.wid);o=self.obj(data={'burning':True,'fire_intensity':50,'temperature':120});self.sys.link(self.wid,z['entity_runtime_id'],o['entity_runtime_id'],link_type='ENVIRONMENT_MEMBER');self.sys.simulate_environment_tick(self.wid,tick_key='t1');self.assertGreater(self.rt.get_entity(self.wid,z['entity_runtime_id'])['data']['smoke'],0)
    def test_tick_idempotent(self):
        z=self.sys.create_environment_zone(self.wid,fire_intensity=30);o=self.obj();self.sys.link(self.wid,z['entity_runtime_id'],o['entity_runtime_id'],link_type='ENVIRONMENT_MEMBER');a=self.sys.simulate_environment_tick(self.wid,tick_key='same');state=self.rt.get_entity(self.wid,o['entity_runtime_id']);b=self.sys.simulate_environment_tick(self.wid,tick_key='same');self.assertTrue(b['idempotent_replay']);self.assertEqual(self.rt.get_entity(self.wid,o['entity_runtime_id'])['version'],state['version'])
    def test_offline_environment_tick_allowed(self):
        z=self.sys.create_environment_zone(self.wid,humidity=95);o=self.obj();self.sys.link(self.wid,z['entity_runtime_id'],o['entity_runtime_id'],link_type='ENVIRONMENT_MEMBER');self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE');self.assertEqual(self.sys.simulate_environment_tick(self.wid,tick_key='off')['status'],'PASS')

    def test_offline_fire_zone_does_not_heat(self):
        z=self.sys.create_environment_zone(self.wid,fire_intensity=100);o=self.obj();self.sys.link(self.wid,z['entity_runtime_id'],o['entity_runtime_id'],link_type='ENVIRONMENT_MEMBER');self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE');r=self.sys.simulate_environment_tick(self.wid,tick_key='off-fire');self.assertEqual(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['temperature'],20);self.assertGreaterEqual(r['blocked'],1)

    def test_manual_interaction_blocked_offline(self):
        o=self.obj();self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE')
        with self.assertRaises(OfflinePolicyError):self.interact(o,'OPEN')

class FirePropagationTests(ObjCase):
    def chain(self,n,conductance=1):
        arr=[self.obj(data={'temperature':20}) for _ in range(n)]
        for a,b in zip(arr,arr[1:]):self.sys.link(self.wid,a['entity_runtime_id'],b['entity_runtime_id'],link_type='ADJACENT',conductance=conductance)
        self.interact(arr[0],'IGNITE');return arr
    def test_fire_propagates(self):
        a=self.chain(3);r=self.sys.propagate_fire(self.wid,a[0]['entity_runtime_id'],propagation_key='p');self.assertGreaterEqual(r['ignited'],1)
    def test_nonburning_root_blocked(self):
        o=self.obj()
        with self.assertRaises(ConflictError):self.sys.propagate_fire(self.wid,o['entity_runtime_id'],propagation_key='p')
    def test_budget_enforced(self):
        a=self.chain(10);r=self.sys.propagate_fire(self.wid,a[0]['entity_runtime_id'],propagation_key='p',budget=2);self.assertLessEqual(r['heated'],2);self.assertTrue(r['budget_exhausted'])
    def test_invalid_budget(self):
        a=self.chain(2)
        with self.assertRaises(ValidationError):self.sys.propagate_fire(self.wid,a[0]['entity_runtime_id'],propagation_key='p',budget=33)
    def test_cycle_no_infinite_loop(self):
        a=self.chain(3);self.sys.link(self.wid,a[2]['entity_runtime_id'],a[0]['entity_runtime_id'],link_type='ADJACENT');r=self.sys.propagate_fire(self.wid,a[0]['entity_runtime_id'],propagation_key='p');self.assertLessEqual(r['visited'],3)

    def test_fire_propagation_blocked_offline(self):
        a=self.chain(2);self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE')
        with self.assertRaises(OfflinePolicyError):self.sys.propagate_fire(self.wid,a[0]['entity_runtime_id'],propagation_key='off')

    def test_idempotent_propagation(self):
        a=self.chain(3);self.sys.propagate_fire(self.wid,a[0]['entity_runtime_id'],propagation_key='p');versions=[self.rt.get_entity(self.wid,x['entity_runtime_id'])['version'] for x in a];r=self.sys.propagate_fire(self.wid,a[0]['entity_runtime_id'],propagation_key='p');self.assertTrue(r['idempotent_replay']);self.assertEqual(versions,[self.rt.get_entity(self.wid,x['entity_runtime_id'])['version'] for x in a])

class IntegrityTests(ObjCase):
    def test_reaction_log_immutable(self):
        o=self.obj();r=self.interact(o,'OPEN');row=self.rt.conn.execute('SELECT reaction_id FROM reaction_logs WHERE event_id=?',(r['event_id'],)).fetchone()
        with self.assertRaises(sqlite3.DatabaseError):self.rt.conn.execute("DELETE FROM reaction_logs WHERE reaction_id=?",(row['reaction_id'],))
    def test_integrity_pass(self):o=self.obj();self.interact(o,'DAMAGE',amount=10);self.assertEqual(self.sys.full_integrity_check(self.wid)['status'],'PASS')
    def test_link_hash_corruption_detected(self):
        a=self.obj();b=self.obj();l=self.sys.link(self.wid,a['entity_runtime_id'],b['entity_runtime_id']);self.rt.conn.execute("UPDATE environment_links SET link_json='{}' WHERE link_id=?",(l['link_id'],));self.assertEqual(self.sys.full_integrity_check(self.wid)['status'],'FAIL')
    def test_reaction_hash_corruption_detected(self):
        o=self.obj();r=self.interact(o,'OPEN');self.rt.conn.execute("DROP TRIGGER reaction_logs_no_update");self.rt.conn.execute("UPDATE reaction_logs SET record_hash='0' WHERE event_id=?",(r['event_id'],));self.assertEqual(self.sys.full_integrity_check(self.wid)['status'],'FAIL')
    def test_runtime_integrity_composed(self):self.assertEqual(self.sys.full_integrity_check(self.wid)['status'],'PASS')

class ConcurrencyTests(ObjCase):
    def test_damage_concurrent_no_negative(self):
        o=self.obj();results=[];lock=threading.Lock()
        def f():
            try:self.interact(o,'DAMAGE',amount=10);x='PASS'
            except Exception as e:x=type(e).__name__
            with lock:results.append(x)
        ts=[threading.Thread(target=f) for _ in range(20)];[t.start() for t in ts];[t.join(10) for t in ts]
        self.assertTrue(all(not t.is_alive() for t in ts));s=self.rt.get_entity(self.wid,o['entity_runtime_id']);self.assertGreaterEqual(s['data']['integrity'],0)
    def test_parallel_distinct_objects(self):
        objs=[self.obj() for _ in range(32)];errs=[]
        def f(o):
            try:self.interact(o,'DAMAGE',amount=1)
            except Exception as e:errs.append(repr(e))
        ts=[threading.Thread(target=f,args=(o,)) for o in objs];[t.start() for t in ts];[t.join(10) for t in ts]
        self.assertFalse(errs);self.assertTrue(all(not t.is_alive() for t in ts));self.assertTrue(all(self.rt.get_entity(self.wid,o['entity_runtime_id'])['data']['integrity']==99 for o in objs))

if __name__=='__main__':unittest.main()
