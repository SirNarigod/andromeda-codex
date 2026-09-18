import os,tempfile,unittest
from integrated_arpg_engine_v10 import IntegratedARPGEngineV10
from living_runtime import ConflictError
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

class Stage10MobilityTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.e=IntegratedARPGEngineV10(':memory:',master_release_path=MASTER);r=cls.e.create_world('s10:test',101010);cls.wid=r['world']['world_instance_id'];cls.m=cls.e.mobility_arpg(cls.wid)
  cls.p=cls.e.arpg(cls.wid).create_profile('s10:test',origin_mode='CREATED',display_name='Driver')['profile'];cls.pref=cls.p['profile_ref']
 @classmethod
 def tearDownClass(cls): cls.e.close()
 def _vehicle(self,ev='v',profile='VEH-PROFILE-SERVICE-LIGHT'):
  return self.m.create_vehicle(self.pref,profile,event_ref='u:'+ev)['vehicle']
 def _place(self,pref,veh,seg,origin=True):
  z=seg['origin_ref'] if origin else seg['destination_ref'];w=self.e.world_arpg(self.wid);st=w.ensure_profile(pref);st['zone_ref']=z;st['instance_context']={'kind':'OVERWORLD','ref':z};w._save_profile(st);v=self.m.vehicle(veh);v['zone_ref']=z;self.m._save_vehicle(v)
 def test_01_health(self): self.assertEqual(self.e.health_arpg_v10(self.wid)['status'],'PASS')
 def test_02_canon_sources(self):
  self.assertEqual(self.m.canonical_snapshot('SYS-AUT-001')['territory_refs'],['TER-011']);self.assertEqual(self.m.canonical_snapshot('POI-046')['name'],'Ponte Varden')
 def test_03_local_road(self): self.assertFalse(self.m.segment('SRTE-001')['boundary_locked'])
 def test_04_boundary_locked(self): self.assertTrue(all(self.m.segment(x)['boundary_locked'] for x in self.m.BOUNDARY_ROUTES))
 def test_05_derived_connectors(self): self.assertGreater(sum(s['segment_kind']=='DERIVED_LOCAL_CONNECTOR' for s in self.m.list_segments()),0)
 def test_06_vehicle_profiles(self): self.assertEqual(len(self.m.list_vehicle_profiles()),3)
 def test_07_create_vehicle(self):
  x=self._vehicle('create');self.assertEqual(x['owner_ref'],self.pref);self.assertEqual(self.e.items_arpg(self.wid).inventory_snapshot(x['vehicle_ref'])['owner_kind'],'VEHICLE_CARGO')
 def test_08_create_replay(self):
  a=self.m.create_vehicle(self.pref,'VEH-PROFILE-SCOUT',event_ref='u:replay');b=self.m.create_vehicle(self.pref,'VEH-PROFILE-SCOUT',event_ref='u:replay');self.assertEqual(a['vehicle']['vehicle_ref'],b['vehicle']['vehicle_ref']);self.assertTrue(b['idempotent_replay'])
 def test_09_board_driver(self):
  v=self._vehicle('board');o=self.m.board(self.pref,v['vehicle_ref'],event_ref='u:board:ev',as_driver=True);self.assertEqual(o['vehicle']['driver_ref'],self.pref)
 def test_10_travel_connector(self):
  v=self._vehicle('travel');vr=v['vehicle_ref'];self.m.board(self.pref,vr,event_ref='u:travel:board',as_driver=True);s=next(x for x in self.m.list_segments() if x['segment_kind']=='DERIVED_LOCAL_CONNECTOR');self._place(self.pref,vr,s);o=self.m.travel(self.pref,vr,s['segment_ref'],event_ref='u:travel:go');self.assertEqual(o['status'],'PASS');self.assertEqual(self.e.world_arpg(self.wid).ensure_profile(self.pref)['zone_ref'],o['destination_zone'])
 def test_11_boundary_rejected(self):
  v=self._vehicle('bound');vr=v['vehicle_ref'];self.m.board(self.pref,vr,event_ref='u:bound:board',as_driver=True);o=self.m.travel(self.pref,vr,'RTE-001',event_ref='u:bound:go');self.assertEqual(o['reason'],'BOUNDARY_ROUTE_LOCKED')
 def test_12_cargo_universal_inventory(self):
  v=self._vehicle('cargo');vr=v['vehicle_ref'];it=self.e.items_arpg(self.wid);it.grant_item(self.pref,'MIN-IRON',5,event_ref='u:cargo:grant');self.m.load_cargo(self.pref,vr,'MIN-IRON',3,event_ref='u:cargo:load');self.assertEqual(it.inventory_snapshot(vr)['stacks'].get('MIN-IRON'),3);self.m.unload_cargo(vr,self.pref,'MIN-IRON',2,event_ref='u:cargo:unload');self.assertEqual(it.inventory_snapshot(vr)['stacks'].get('MIN-IRON'),1)
 def test_13_bridge_condition(self):
  b=self.m.set_bridge_condition('POI-046',5);self.assertFalse(b['operational']);self.m.set_bridge_condition('POI-046',100)
 def test_14_refuel_abstract(self):
  v=self._vehicle('fuel');vr=v['vehicle_ref'];x=self.m.refuel(vr,10,event_ref='u:fuel:1');self.assertEqual(x['propulsion_type'],'ABSTRACT_PROPULSION_RESOURCE_STAGE10')
 def test_15_npc_vehicle_driver(self):
  npc=next(n for st in self.e.country(self.wid).world['country']['states'] for b in st['blocks'] for c in b['cities'] for n in c['npcs'] if n['class']!='CHILD');v=self.m.create_vehicle(npc['id'],'VEH-PROFILE-UTILITY-CARGO',event_ref='u:npc:create')['vehicle'];o=self.m.board(npc['id'],v['vehicle_ref'],event_ref='u:npc:board',as_driver=True);self.assertEqual(o['status'],'PASS');self.assertIsNotNone(v['zone_ref'])
 def test_16_deterministic_vehicle_ref(self):
  r=self.e.create_world('s10:other',101010);m2=self.e.mobility_arpg(r['world']['world_instance_id']);p2=self.e.arpg(r['world']['world_instance_id']).create_profile('s10:other',origin_mode='CREATED',display_name='Driver')['profile'];a=self.m.create_vehicle(self.pref,'VEH-PROFILE-SCOUT',event_ref='u:det')['vehicle']['vehicle_ref'];b=m2.create_vehicle(p2['profile_ref'],'VEH-PROFILE-SCOUT',event_ref='u:det')['vehicle']['vehicle_ref'];self.assertNotEqual(a,b) # owner identity is intentionally part of vehicle identity
  self.assertEqual([s['segment_ref'] for s in self.m.list_segments() if s['segment_kind']=='DERIVED_LOCAL_CONNECTOR'],[s['segment_ref'] for s in m2.list_segments() if s['segment_kind']=='DERIVED_LOCAL_CONNECTOR'])
 def test_17_bridge_projection(self): self.assertGreaterEqual(len(self.m.list_bridges()),1)
 def test_18_verify(self): self.assertEqual(self.m.verify()['status'],'PASS')

class Stage10PersistenceTests(unittest.TestCase):
 def test_persistence_resume(self):
  with tempfile.TemporaryDirectory() as td:
   db=os.path.join(td,'s10.sqlite');e=IntegratedARPGEngineV10(db,master_release_path=MASTER);r=e.create_world('persist:s10',101011);wid=r['world']['world_instance_id'];m=e.mobility_arpg(wid);p=e.arpg(wid).create_profile('persist:s10',origin_mode='CREATED',display_name='Persist Driver')['profile'];pref=p['profile_ref'];v=m.create_vehicle(pref,'VEH-PROFILE-SERVICE-LIGHT',event_ref='p:create')['vehicle'];vr=v['vehicle_ref'];m.board(pref,vr,event_ref='p:board',as_driver=True);s=next(x for x in m.list_segments() if x['segment_kind']=='DERIVED_LOCAL_CONNECTOR');w=e.world_arpg(wid);st=w.ensure_profile(pref);st['zone_ref']=s['origin_ref'];st['instance_context']={'kind':'OVERWORLD','ref':s['origin_ref']};w._save_profile(st);vv=m.vehicle(vr);vv['zone_ref']=s['origin_ref'];m._save_vehicle(vv);m.travel(pref,vr,s['segment_ref'],event_ref='p:travel');before=m.vehicle(vr);e.runtime.close();e2=IntegratedARPGEngineV10(db,master_release_path=MASTER);e2.resume_world(wid);after=e2.mobility_arpg(wid).vehicle(vr);self.assertEqual(before,after);self.assertEqual(e2.health_arpg_v10(wid)['status'],'PASS');e2.runtime.close()
if __name__=='__main__':unittest.main(verbosity=2)
