import json, os, shutil, tempfile, unittest, zipfile, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from living_runtime import LivingRuntime,new_runtime_id,clock_point
from agent_brain import IntentValidator
from social_memory import SocialMemorySystem
from ecology_brain import EcologySystem
from object_environment import ObjectEnvironmentSystem
from world_systems import WorldSystems
from llm_gateway import ControlledLLMGateway, ScriptedProvider
from atlas_living_bridge import AtlasLivingBridge,AtlasSnapshotPublisher,AtlasBridgePermissionError,AtlasBridgeIntegrityError
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

def mkstate(rt,w,kind='AGENT',canon=None,data=None,lifecycle='ACTIVE'):
 c=rt.get_clock(w['world_instance_id']);s={'state_id':new_runtime_id('state'),'world_instance_id':w['world_instance_id'],'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id(kind.lower()),'origin':'CANONICAL_BACKED' if canon else 'RUNTIME_BORN','entity_kind':kind,'lifecycle':lifecycle,'version':0,'updated_at':clock_point(c['day'],c['tick']),'data':dict(data or {}),'protection':{'death':'BLOCKED'}}
 if canon:s['canonical_ref']=canon
 return rt.register_entity(w['world_instance_id'],s)

def policy():return {'policy_key':'atlas.refuse','action_type':'REFUSE_TRADE','allowed_sources':['LLM_CANDIDATE'],'actor_kinds':['AGENT'],'target_required':True,'target_kinds':['AGENT'],'offline_policy':'ACTIVE_ONLY','spatial_policy':'NONE','protection_impacts':[],'cooldown_ticks':0,'parameter_schema':{},'resource_requirements':[],'actor_state_equals':{},'target_state_equals':{},'consequence_templates':[]}

class BridgeCase(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.seedtmp=tempfile.TemporaryDirectory(); cls.seed=os.path.join(cls.seedtmp.name,'seed.db')
  rt=LivingRuntime(cls.seed,master_release_path=MASTER); w=rt.create_world('player-001',1313,ticks_per_day=24); cls.wid=w['world_instance_id']; cls.tid=w['timeline_id']
  w2=rt.create_world('player-002',1314,ticks_per_day=24); cls.wid2=w2['world_instance_id']
  ws=WorldSystems(rt);ws.load_master_snapshots(MASTER);ws.bootstrap_world(cls.wid,population_seed=1000);ws.bootstrap_world(cls.wid2,population_seed=2000);ws.economy_tick(cls.wid,'e1','FULL');ws.population_tick(cls.wid,'p1','FULL');ws.faction_tick(cls.wid,'f1','FULL');ws.set_route_operational(cls.wid,'RTE-001',False)
  cls.serlis=mkstate(rt,w,canon='PER-003',data={'name':'Serlis','role':'NPC','location_ref':'CIT-001','money':20,'token':'SHOULD_HIDE'})
  cls.visible=mkstate(rt,w,data={'name':'Runtime Visible','atlas_exposure':'PLAYER_VISIBLE','location_ref':'CIT-001','money':7,'secret':'hide-me'})
  cls.hidden=mkstate(rt,w,data={'name':'Runtime Hidden','location_ref':'CIT-001','money':9})
  with zipfile.ZipFile(MASTER) as z:
   ad=json.loads(z.read('ANDROMEDA_CODEX_MASTER/02_ATLAS/runtime/data/atlas-data.json'))
  lvl4=next(e['id'] for e in ad['entities'] if int(e.get('spoiler_level',0))==4)
  hid=next(e['id'] for e in ad['entities'] if e.get('atlas_visibility')=='HIDDEN')
  cls.level4=mkstate(rt,w,canon=lvl4,data={'name':'Restricted'})
  cls.canonhidden=mkstate(rt,w,canon=hid,data={'name':'Hidden Canon'})
  val=IntentValidator(rt); val.register_policy(cls.wid,policy()); social=SocialMemorySystem(rt)
  social.apply_relationship_delta(cls.wid,cls.serlis['entity_runtime_id'],cls.visible['entity_runtime_id'],{'trust':-25},reason='ATLAS_TEST',idempotency_key='atlas-rel')
  social.apply_reputation_delta(cls.wid,cls.visible['entity_runtime_id'],-12,reason='ATLAS_TEST',idempotency_key='atlas-rep')
  eco=EcologySystem(rt,val);eco.load_master_fauna_snapshots(MASTER);eco.register_species_profile(cls.wid,{'species_ref':'CRI-002','diet':'CARNIVORE','social_structure':'SOLITARY','cognition_mode':'ADAPTIVE','activity_mode':'CATHEMERAL'});eco.register_population(cls.wid,species_ref='CRI-002',territory_ref='TER-002',count=50,carrying_capacity=100,resource_index=70,water_index=80,climate_comfort=90)
  obj=ObjectEnvironmentSystem(rt);prof=obj.register_profile(cls.wid,{'object_class':'BRIDGE','material_class':'STONE','base_integrity':100}); cls.bridgeobj=obj.spawn_object(cls.wid,profile_id=prof['profile_id'],data={'atlas_exposure':'PLAYER_VISIBLE','name':'Ponte Runtime'}); actor=cls.visible;obj.interact(cls.wid,actor_ref=actor['entity_runtime_id'],target_ref=cls.bridgeobj['entity_runtime_id'],interaction_type='DAMAGE',amount=100)
  gw=ControlledLLMGateway(rt,val,social);provider=ScriptedProvider({'dialogue':'Não.','candidate_intent':{'intent_type':'REFUSE_TRADE','target_ref':cls.visible['entity_runtime_id'],'parameters':{}}});gw.bind_provider(provider);gw.register_profile(cls.wid,cls.serlis['entity_runtime_id'],provider_id=provider.provider_id,personality='x',allowed_intents=['REFUSE_TRADE']);gw.converse(cls.wid,cls.serlis['entity_runtime_id'],user_text='Negocia?',counterpart_ref=cls.visible['entity_runtime_id'],request_key='atlas-llm')
  rt.close()
 @classmethod
 def tearDownClass(cls):cls.seedtmp.cleanup()
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=os.path.join(self.tmp.name,'w.db');shutil.copy2(self.seed,self.db);self.b=AtlasLivingBridge(self.db,MASTER)
 def tearDown(self):self.b.close();self.tmp.cleanup()
 def player(self,spoiler=0,viewer=None):return self.b.export_projection(self.wid,role='PLAYER',request_scope='player-001',viewer_ref=viewer,spoiler_max=spoiler,recent_events=500)
 def admin(self,spoiler=3):return self.b.export_projection(self.wid,role='ADMIN',spoiler_max=spoiler,recent_events=500)

class AccessTests(BridgeCase):
 def test_public_no_runtime(self):p=self.b.export_projection(role='PUBLIC');self.assertEqual(p['runtime_access'],'NONE');self.assertEqual(p['layers'],{})
 def test_public_ignores_fake_world(self):self.assertEqual(self.b.export_projection('fake',role='PUBLIC')['runtime_access'],'NONE')
 def test_player_requires_scope(self):
  with self.assertRaises(AtlasBridgePermissionError):self.b.export_projection(self.wid,role='PLAYER')
 def test_player_wrong_scope(self):
  with self.assertRaises(AtlasBridgePermissionError):self.b.export_projection(self.wid,role='PLAYER',request_scope='player-002')
 def test_admin_any_world(self):self.assertEqual(self.b.export_projection(self.wid2,role='ADMIN')['world']['world_instance_id'],self.wid2)
 def test_invalid_role(self):
  with self.assertRaises(AtlasBridgePermissionError):self.b.export_projection(self.wid,role='AUTHOR')
 def test_level4_always_hidden(self):self.assertFalse(any(x.get('canonical_ref')==self.level4['canonical_ref'] for x in self.admin(3)['layers']['LIVE_ENTITY_STATE']))
 def test_hidden_canon_always_hidden(self):self.assertFalse(any(x.get('canonical_ref')==self.canonhidden['canonical_ref'] for x in self.admin()['layers']['LIVE_ENTITY_STATE']))
 def test_spoiler0_hides_serlis(self):self.assertFalse(any(x.get('canonical_ref')=='PER-003' for x in self.player(0)['layers']['LIVE_ENTITY_STATE']))
 def test_spoiler1_shows_serlis(self):self.assertTrue(any(x.get('canonical_ref')=='PER-003' for x in self.player(1)['layers']['LIVE_ENTITY_STATE']))

class StateProjectionTests(BridgeCase):
 def test_runtime_hidden_by_default(self):self.assertFalse(any(x['entity_runtime_id']==self.hidden['entity_runtime_id'] for x in self.player(1)['layers']['LIVE_ENTITY_STATE']))
 def test_runtime_visible_optin(self):self.assertTrue(any(x['entity_runtime_id']==self.visible['entity_runtime_id'] for x in self.player(1)['layers']['LIVE_ENTITY_STATE']))
 def test_admin_sees_runtime_hidden(self):self.assertTrue(any(x['entity_runtime_id']==self.hidden['entity_runtime_id'] for x in self.admin()['layers']['LIVE_ENTITY_STATE']))
 def test_protection_not_exposed(self):self.assertTrue(all('protection' not in x for x in self.admin()['layers']['LIVE_ENTITY_STATE']))
 def test_secret_not_exposed_player(self):x=next(x for x in self.player(1)['layers']['LIVE_ENTITY_STATE'] if x['entity_runtime_id']==self.visible['entity_runtime_id']);self.assertNotIn('secret',x['data'])
 def test_token_not_exposed_admin(self):x=next(x for x in self.admin()['layers']['LIVE_ENTITY_STATE'] if x.get('canonical_ref')=='PER-003');self.assertNotIn('token',x['data'])
 def test_world_clock_present(self):self.assertEqual(self.admin()['world']['clock']['ticks_per_day'],24)
 def test_runtime_authority_label(self):self.assertTrue(all(x['authority']=='TIMELINE_RUNTIME_STATE_NOT_CANON' for x in self.admin()['layers']['LIVE_ENTITY_STATE']))
 def test_routes_layer(self):self.assertGreaterEqual(len(self.player()['layers']['LIVE_ROUTES']),1)
 def test_economy_layer(self):self.assertEqual(len(self.admin()['layers']['LIVE_ECONOMY']),7)
 def test_population_layer(self):self.assertEqual(len(self.admin()['layers']['LIVE_POPULATION']),14)
 def test_faction_layer(self):self.assertEqual(len(self.admin()['layers']['LIVE_FACTIONS']),3)
 def test_environment_layer_contains_destroyed(self):self.assertTrue(any(x['lifecycle']=='DESTROYED' for x in self.player(1)['layers']['LIVE_ENVIRONMENT']))
 def test_route_block_visible(self):self.assertTrue(any(x.get('canonical_ref')=='RTE-001' and x['data'].get('operational') is False for x in self.player()['layers']['LIVE_ROUTES']))

class EventRecoveryTests(BridgeCase):
 def test_events_present_admin(self):self.assertGreater(len(self.admin()['layers']['LIVE_EVENTS']),0)
 def test_player_events_sanitized(self):self.assertTrue(all('payload' not in x for x in self.player(1)['layers']['LIVE_EVENTS']))
 def test_admin_events_payload(self):self.assertTrue(any('payload' in x for x in self.admin()['layers']['LIVE_EVENTS']))
 def test_event_limit(self):self.assertLessEqual(len(self.b.export_projection(self.wid,role='ADMIN',recent_events=2)['layers']['LIVE_EVENTS']),2)
 def test_recovery_present(self):self.assertTrue(any(x['target_ref']==self.bridgeobj['entity_runtime_id'] for x in self.player(1)['layers']['LIVE_RECOVERY']))
 def test_recovery_policy(self):x=next(x for x in self.admin()['layers']['LIVE_RECOVERY'] if x['target_ref']==self.bridgeobj['entity_runtime_id']);self.assertEqual(x['due_at_day']-x['destroyed_at_day'],7)
 def test_causal_hidden_player(self):self.assertEqual(self.player(1)['layers']['LIVE_CAUSAL'],[])
 def test_causal_visible_admin(self):self.assertGreater(len(self.admin()['layers']['LIVE_CAUSAL']),0)

class EcologySocialLLMTests(BridgeCase):
 def test_ecology_visible(self):self.assertTrue(any(x['species_ref']=='CRI-002' for x in self.admin()['layers']['LIVE_ECOLOGY']))
 def test_social_hidden_without_viewer(self):self.assertEqual(self.player(1)['layers']['LIVE_SOCIAL'],{'relationships':[],'reputation':[]})
 def test_social_viewer_scoped(self):p=self.player(1,viewer=self.visible['entity_runtime_id']);self.assertGreaterEqual(len(p['layers']['LIVE_SOCIAL']['relationships']),1);self.assertGreaterEqual(len(p['layers']['LIVE_SOCIAL']['reputation']),1)
 def test_admin_social_visible(self):p=self.admin();self.assertGreaterEqual(len(p['layers']['LIVE_SOCIAL']['relationships']),1)
 def test_player_llm_metrics_hidden(self):self.assertFalse(self.player(1)['layers']['LLM_METRICS']['visible'])
 def test_admin_llm_metrics(self):x=self.admin()['layers']['LLM_METRICS'];self.assertTrue(x['visible']);self.assertGreaterEqual(x['requests'],1);self.assertFalse(x['raw_content_exposed'])
 def test_no_raw_llm_keys_anywhere(self):s=json.dumps(self.admin()).lower();self.assertNotIn('raw_prompt',s);self.assertNotIn('raw_response',s)

class IntegrityIsolationTests(BridgeCase):
 def test_projection_hash_pass(self):p=self.admin();self.assertEqual(self.b.verify_projection(p)['status'],'PASS')
 def test_projection_tamper_fails(self):p=self.admin();p['world']['clock']['day']+=1;self.assertEqual(self.b.verify_projection(p)['status'],'FAIL')
 def test_sqlite_is_readonly(self):self.assertEqual(self.b.write_attempt_probe(),'PASS_READ_ONLY')
 def test_query_only_pragma(self):self.assertEqual(self.b.conn.execute('PRAGMA query_only').fetchone()[0],1)
 def test_world_isolation(self):p=self.b.export_projection(self.wid2,role='ADMIN');self.assertFalse(any(x.get('canonical_ref')=='PER-003' for x in p['layers']['LIVE_ENTITY_STATE']))
 def test_projection_timeline_matches(self):self.assertEqual(self.admin()['world']['timeline_id'],self.tid)
 def test_master_hash_declared(self):self.assertEqual(self.admin()['master_release_sha256'],'6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2')
 def test_bad_master_rejected(self):
  p=os.path.join(self.tmp.name,'bad.zip');
  with open(p,'wb') as f:f.write(b'bad')
  with self.assertRaises(AtlasBridgeIntegrityError):AtlasLivingBridge(self.db,p)
 def test_projection_authority(self):self.assertEqual(self.admin()['projection_authority'],'READ_ONLY_DERIVED_VIEW')
 def test_write_authority_false(self):self.assertFalse(self.admin()['access']['runtime_write_authority'])


class SnapshotPublisherTests(BridgeCase):
 def test_publish_snapshot(self):
  rt=LivingRuntime(self.db,master_release_path=MASTER);pub=AtlasSnapshotPublisher(rt,self.tmp.name);m=pub.publish(self.wid);rt.close();self.assertEqual(m['authority'],'READ_ONLY_ATOMIC_RUNTIME_SNAPSHOT');self.assertFalse(m['source_runtime_mutated']);self.assertTrue(os.path.exists(os.path.join(self.tmp.name,m['snapshot_file'])))
 def test_snapshot_bridge_readonly(self):
  rt=LivingRuntime(self.db,master_release_path=MASTER);pub=AtlasSnapshotPublisher(rt,self.tmp.name);m=pub.publish(self.wid);rt.close();b=AtlasLivingBridge(os.path.join(self.tmp.name,m['snapshot_file']),MASTER);self.assertEqual(b.write_attempt_probe(),'PASS_READ_ONLY');b.close()
 def test_snapshot_hash_matches(self):
  import hashlib
  rt=LivingRuntime(self.db,master_release_path=MASTER);m=AtlasSnapshotPublisher(rt,self.tmp.name).publish(self.wid);rt.close();
  with open(os.path.join(self.tmp.name,m['snapshot_file']),'rb') as f:h=hashlib.sha256(f.read()).hexdigest()
  self.assertEqual(h,m['snapshot_sha256'])
 def test_publish_replaces_atomically(self):
  rt=LivingRuntime(self.db,master_release_path=MASTER);pub=AtlasSnapshotPublisher(rt,self.tmp.name);a=pub.publish(self.wid);rt.advance_ticks(self.wid,1);b=pub.publish(self.wid);rt.close();self.assertEqual(a['snapshot_file'],b['snapshot_file']);self.assertNotEqual(a['snapshot_sha256'],b['snapshot_sha256'])
 def test_snapshot_metadata_hash(self):
  from atlas_living_bridge import _sha_text,_canon
  rt=LivingRuntime(self.db,master_release_path=MASTER);m=AtlasSnapshotPublisher(rt,self.tmp.name).publish(self.wid);rt.close();x=dict(m);h=x.pop('metadata_hash');self.assertEqual(h,_sha_text(_canon(x)))


class HardeningTests(BridgeCase):
 def _rw(self,sql,args=()):
  self.b.close();import sqlite3;c=sqlite3.connect(self.db);c.execute(sql,args);c.commit();c.close();self.b=AtlasLivingBridge(self.db,MASTER)
 def test_state_hash_corruption_detected(self):
  self._rw("UPDATE entity_states SET state_hash='bad' WHERE world_instance_id=? LIMIT 1",(self.wid,))
  with self.assertRaises(AtlasBridgeIntegrityError):self.admin()
 def test_relationship_hash_corruption_detected(self):
  self._rw("UPDATE relationships_current SET relationship_hash='bad' WHERE world_instance_id=? LIMIT 1",(self.wid,))
  with self.assertRaises(AtlasBridgeIntegrityError):self.admin()
 def test_ecology_hash_corruption_detected(self):
  self._rw("UPDATE ecology_populations_current SET population_hash='bad' WHERE world_instance_id=? LIMIT 1",(self.wid,))
  with self.assertRaises(AtlasBridgeIntegrityError):self.admin()
 def test_snapshot_publisher_blocks_corrupt_runtime(self):
  self.b.close();import sqlite3;c=sqlite3.connect(self.db);c.execute("UPDATE entity_states SET state_hash='bad' WHERE world_instance_id=? LIMIT 1",(self.wid,));c.commit();c.close();rt=LivingRuntime(self.db,master_release_path=MASTER)
  try:
   with self.assertRaises(AtlasBridgeIntegrityError):AtlasSnapshotPublisher(rt,self.tmp.name).publish(self.wid)
  finally:rt.close();self.b=AtlasLivingBridge(self.db,MASTER)
 def test_snapshot_permissions_backend_only(self):
  rt=LivingRuntime(self.db,master_release_path=MASTER);m=AtlasSnapshotPublisher(rt,self.tmp.name).publish(self.wid);rt.close();mode=os.stat(os.path.join(self.tmp.name,m['snapshot_file'])).st_mode & 0o777;self.assertEqual(mode,0o600);self.assertEqual(m['distribution'],'BACKEND_ONLY_DO_NOT_SERVE_DB_FILE')
 def test_nested_restricted_canon_ref_redacted(self):
  x=self.b._sanitize_value({'nested':[self.level4['canonical_ref']]},3,set());self.assertEqual(x['nested'][0],'[REDACTED_CANONICAL_REF]')
 def test_hidden_runtime_ref_redacted(self):
  x=self.b._sanitize_value({'target':self.hidden['entity_runtime_id']},3,{self.visible['entity_runtime_id']});self.assertEqual(x['target'],'[REDACTED_RUNTIME_REF]')

if __name__=='__main__':unittest.main()
