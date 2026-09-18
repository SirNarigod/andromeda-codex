import os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'01_RUNTIME'))
from living_runtime import LivingRuntime,new_runtime_id,clock_point,ConflictError
from world_systems import WorldSystems
from commerce_system import CommerceSystem
from combat_system import CombatSystem
from agent_brain import IntentValidator
from ecology_brain import EcologySystem
from social_memory import SocialMemorySystem
from domain_integration import DomainIntegrationHub

MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
PRED='CRI-002'; HOME='TER-011'; BIOME='BIO-008'

def make_agent(rt,wid,location='POI-003',name='Player'):
 w=rt.get_world(wid);c=w['clock_state'];s={'state_id':new_runtime_id('state'),'world_instance_id':wid,'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{'name':name,'location_ref':location,'energy':100},'protection':{}}
 return rt.register_entity(wid,s)

def profile(species):
 return {'species_ref':species,'diet':'CARNIVORE','social_structure':'PACK','cognition_mode':'ADAPTIVE','activity_mode':'DIURNAL','range_excursion_allowed':True}

class CombatV11Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=os.path.join(self.tmp.name,'c.db');self.rt=LivingRuntime(self.db,master_release_path=MASTER);self.w=self.rt.create_world('combat',1401,ticks_per_day=24);self.wid=self.w['world_instance_id']
  self.ws=WorldSystems(self.rt);self.ws.load_master_snapshots(MASTER);self.ws.bootstrap_world(self.wid,population_seed=1000)
  self.cs=CommerceSystem(self.rt,self.ws);self.cs.load_catalog(MASTER)
  self.player=make_agent(self.rt,self.wid);self.observer=make_agent(self.rt,self.wid,BIOME,'Observer')
  self.cs.create_account(self.wid,self.player['entity_runtime_id'],starting_balance=500);self.vendor=self.cs.create_vendor(self.wid,'POI-003',stock_seed=5)['vendor']
  q=self.cs.quote(self.wid,self.player['entity_runtime_id'],self.vendor['entity_runtime_id'],'WPN-003');self.cs.execute_quote(q['quote_id'],idempotency_key='initial-buy')
  self.val=IntentValidator(self.rt);self.eco=EcologySystem(self.rt,self.val);self.eco.load_master_fauna_snapshots(MASTER);self.eco.register_species_profile(self.wid,profile(PRED));self.eco.register_population(self.wid,species_ref=PRED,territory_ref=HOME,count=12,carrying_capacity=100)
  self.social=SocialMemorySystem(self.rt);self.hub=DomainIntegrationHub(self.rt,self.eco,self.social);self.combat=CombatSystem(self.rt,self.cs,domain_hub=self.hub)
  self.move(self.player['entity_runtime_id'],BIOME,'player-to-biome')
 def tearDown(self):
  try:self.hub.detach()
  except:pass
  try:self.rt.close()
  except:pass
  self.tmp.cleanup()
 def move(self,ref,loc,key):
  e=self.rt.get_entity(self.wid,ref);w=self.rt.get_world(self.wid);c=w['clock_state'];a={'action_id':new_runtime_id('action'),'intent_id':new_runtime_id('intent'),'world_instance_id':self.wid,'timeline_id':w['timeline_id'],'actor_ref':'SYSTEM_RECONCILIATION','action_type':'TEST_MOVE','parameters':{'location_ref':loc},'precondition_snapshot':{'entity_versions':{ref:e['version']}},'idempotency_key':key,'created_at':clock_point(c['day'],c['tick']),'status':'SCHEDULED','source':'SYSTEM_RECONCILIATION','execution_class':'ROUTINE_SAFE'}
  self.rt.apply_action(self.wid,a,[{'target_ref':ref,'operation':'SET','field_path':'data.location_ref','value':loc,'priority':0,'kind':'DIRECT'}])
 def predator(self,protection=None):
  return self.eco.spawn_animal(self.wid,species_ref=PRED,territory_ref=HOME,biome_ref=BIOME,age_days=60,hunger=20,thirst=20,energy=80,reproduction_drive=0,protection=protection)
 def equip(self): return self.combat.equip_weapon(self.wid,self.player['entity_runtime_id'],'WPN-003')['equipment']
 def kill(self,target,max_attacks=12):
  out=[]
  for _ in range(max_attacks):
   if self.rt.get_entity(self.wid,target['entity_runtime_id'])['lifecycle']!='ACTIVE': break
   out.append(self.combat.attack(self.wid,self.player['entity_runtime_id'],target['entity_runtime_id']))
  return out
 def test_equip_consumes_inventory_and_spawns_replayable_equipment(self):
  self.assertEqual(self.cs.account_state(self.wid,self.player['entity_runtime_id'])['items']['WPN-003'],1);eq=self.equip();self.assertEqual(self.cs.account_state(self.wid,self.player['entity_runtime_id'])['items']['WPN-003'],0);self.assertEqual(eq['data']['condition'],100.0);self.assertEqual(self.rt.compare_replay_to_materialized(self.wid)['status'],'PASS')
 def test_attack_uses_mar_and_wears_equipment(self):
  eq=self.equip();t=self.predator();r=self.combat.attack(self.wid,self.player['entity_runtime_id'],t['entity_runtime_id']);eq2=self.rt.get_entity(self.wid,eq['entity_runtime_id']);self.assertEqual(r['weapon_ref'],'WPN-003');self.assertLess(eq2['data']['condition'],100.0);self.assertEqual(r['balance_authority'],'RUNTIME_ONLY_NOT_CANON')
 def test_lethal_combat_creates_corpse_and_updates_population(self):
  self.equip();t=self.predator();results=self.kill(t);dead=self.rt.get_entity(self.wid,t['entity_runtime_id']);self.assertEqual(dead['lifecycle'],'DEAD');self.assertTrue(any(r['lethal'] for r in results));self.assertEqual(self.eco.get_population(self.wid,PRED,HOME)['count'],11)
  lethal=[r for r in results if r['lethal']][-1];corpse=self.rt.get_entity(self.wid,lethal['corpse_ref']);self.assertEqual(corpse['entity_kind'],'CORPSE');self.assertTrue(corpse['data']['harvestable'])
 def test_witness_memory_is_automatic_for_combat(self):
  self.equip();t=self.predator();self.kill(t);mem=self.social.recall_memories(self.wid,self.observer['entity_runtime_id'],limit=100);self.assertGreaterEqual(len(mem),1);self.assertTrue(any(m.get('content',{}).get('event_type')=='COMBAT_RESOLVED' for m in mem))
 def test_death_protection_prevents_kill_and_corpse(self):
  self.equip();t=self.predator(protection={'death':'BLOCKED'});results=self.kill(t,8);state=self.rt.get_entity(self.wid,t['entity_runtime_id']);self.assertEqual(state['lifecycle'],'ACTIVE');self.assertGreaterEqual(state['data']['combat']['health'],1.0);self.assertTrue(any(r['death_blocked_by_protection'] for r in results if r['hit']));self.assertFalse(any(r['corpse_ref'] for r in results))
 def test_harvest_creates_resource_bundle_once(self):
  self.equip();t=self.predator();results=self.kill(t);corpse=[r['corpse_ref'] for r in results if r['lethal']][-1];h=self.combat.harvest_corpse(self.wid,self.player['entity_runtime_id'],corpse);res=h['resource'];self.assertEqual(res['entity_kind'],'RESOURCE_BUNDLE');self.assertEqual(res['data']['resource_type'],'BIOLOGICAL_MATERIAL');self.assertEqual(res['data']['quantity'],2.0);self.assertEqual(self.rt.get_entity(self.wid,corpse)['lifecycle'],'HARVESTED')
  with self.assertRaises(ConflictError): self.combat.harvest_corpse(self.wid,self.player['entity_runtime_id'],corpse)
 def test_spatial_constraint_blocks_remote_attack(self):
  self.equip();t=self.predator();self.move(self.player['entity_runtime_id'],'POI-003','back-to-shop')
  with self.assertRaises(ConflictError): self.combat.attack(self.wid,self.player['entity_runtime_id'],t['entity_runtime_id'])
 def test_cannot_equip_unowned_weapon(self):
  with self.assertRaises(ConflictError): self.combat.equip_weapon(self.wid,self.player['entity_runtime_id'],'WPN-002')
 def test_full_integrity_and_replay_after_combat_harvest(self):
  self.equip();t=self.predator();results=self.kill(t);corpse=[r['corpse_ref'] for r in results if r['lethal']][-1];self.combat.harvest_corpse(self.wid,self.player['entity_runtime_id'],corpse);rep=self.combat.full_integrity_check(self.wid);self.assertEqual(rep['status'],'PASS',rep);self.assertEqual(rep['replay']['status'],'PASS')
 def test_repair_requires_master_maintenance_location(self):
  eq=self.equip();t=self.predator();self.combat.attack(self.wid,self.player['entity_runtime_id'],t['entity_runtime_id'])
  with self.assertRaises(ConflictError): self.combat.repair_equipment(self.wid,self.player['entity_runtime_id'],eq['entity_runtime_id'])
 def test_repair_transfers_full_runtime_cost_and_restores_condition(self):
  eq=self.equip();t=self.predator();self.combat.attack(self.wid,self.player['entity_runtime_id'],t['entity_runtime_id']);before_eq=self.rt.get_entity(self.wid,eq['entity_runtime_id']);self.assertLess(before_eq['data']['condition'],100)
  self.move(self.player['entity_runtime_id'],'POI-003','repair-return');before_wallet=self.cs.account_state(self.wid,self.player['entity_runtime_id'])['balance'];before_vendor=self.rt.get_entity(self.wid,self.vendor['entity_runtime_id'])['data']['cash_balance'];r=self.combat.repair_equipment(self.wid,self.player['entity_runtime_id'],eq['entity_runtime_id']);after_wallet=self.cs.account_state(self.wid,self.player['entity_runtime_id'])['balance'];after_vendor=self.rt.get_entity(self.wid,self.vendor['entity_runtime_id'])['data']['cash_balance']
  self.assertGreater(r['cost'],0);self.assertAlmostEqual(before_wallet-after_wallet,r['cost']);self.assertAlmostEqual(after_vendor-before_vendor,r['cost']);self.assertEqual(r['equipment']['data']['condition'],100.0);self.assertEqual(r['quote_basis']['maintenance_location_ref'],'POI-003');self.assertEqual(r['quote_basis']['maintenance_source_authority'],'MASTER_READ_ONLY')
 def test_repair_reactivates_broken_equipment(self):
  eq=self.equip();e=self.rt.get_entity(self.wid,eq['entity_runtime_id']);self.combat._world_action(self.wid,self.player['entity_runtime_id'],'TEST_BREAK_EQUIPMENT',{'test':True},{e['entity_runtime_id']:e['version']},[{'target_ref':e['entity_runtime_id'],'operation':'SET','field_path':'data.condition','value':0.0,'priority':0,'kind':'DIRECT'},{'target_ref':e['entity_runtime_id'],'operation':'SET','field_path':'data.functional','value':False,'priority':1,'kind':'DIRECT'}],'test-break-equipment')
  self.move(self.player['entity_runtime_id'],'POI-003','repair-broken-return');r=self.combat.repair_equipment(self.wid,self.player['entity_runtime_id'],eq['entity_runtime_id']);self.assertTrue(r['equipment']['data']['functional']);self.assertEqual(r['equipment']['data']['condition'],100.0);self.assertEqual(self.combat.full_integrity_check(self.wid)['status'],'PASS')

if __name__=='__main__':unittest.main()
