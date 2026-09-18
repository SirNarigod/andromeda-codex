import os,tempfile,unittest
from integrated_arpg_engine_v13 import IntegratedARPGEngineV13
from living_runtime import ConflictError, ValidationError
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

class Stage13EconomyTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.e=IntegratedARPGEngineV13(':memory:',master_release_path=MASTER); r=cls.e.create_world('s13:test',131313); cls.wid=r['world']['world_instance_id']; cls.ec=cls.e.economy_arpg(cls.wid); cls.i=cls.e.items_arpg(cls.wid); cls.m=cls.e.mobility_arpg(cls.wid); cls.t=cls.e.technology_arpg(cls.wid)
  cls.p=cls.e.arpg(cls.wid).create_profile('s13:test',origin_mode='CREATED',display_name='Economy Tester')['profile']; cls.pref=cls.p['profile_ref']; cls.ec.ensure_wallet(cls.pref,1000)
  cls.market=next(v for v in cls.ec.list_vendors() if v['location_ref']=='POI-002'); cls.workshop=next(v for v in cls.ec.list_vendors() if v['location_ref']=='POI-003')
 @classmethod
 def tearDownClass(cls): cls.e.close()
 def test_01_health(self): self.assertEqual(self.e.health_arpg_v13(self.wid)['status'],'PASS')
 def test_02_canon_market(self): self.assertEqual(self.ec.canonical_snapshot('POI-002').get('name'),'Mercado Fronteiriço de Varga')
 def test_03_culinary_count(self): self.assertEqual(len(self.ec.CULINARY_REFS),4)
 def test_04_vendor_count(self): self.assertEqual(len(self.ec.list_vendors()),3)
 def test_05_no_canonical_merchant_invented(self): self.assertTrue(all(not v['merchant_identity_claimed'] for v in self.ec.list_vendors()))
 def test_06_currency_guard(self): self.assertEqual(self.ec.wallet(self.pref)['currency'],'CREDIT_RUNTIME_NOT_CANON')
 def test_07_quote_requires_execution(self):
  before=self.ec.wallet(self.pref)['balance']; q=self.ec.price_quote(self.pref,self.market['vendor_ref'],'ITEM-GRAIN',2,event_ref='u13:q1'); self.assertEqual(self.ec.wallet(self.pref)['balance'],before); self.assertGreater(q['quote']['total_price'],0)
 def test_08_buy(self):
  q=self.ec.price_quote(self.pref,self.market['vendor_ref'],'ITEM-GRAIN',2,event_ref='u13:q2'); b=self.ec.execute_trade(q['quote']['quote_ref'],event_ref='u13:buy'); self.assertEqual(b['status'],'PASS'); self.assertGreaterEqual(self.i.inventory_snapshot(self.pref)['stacks'].get('ITEM-GRAIN',0),2)
 def test_09_trade_replay(self):
  before=self.i.inventory_snapshot(self.pref)['stacks'].get('ITEM-GRAIN',0); q=self.ec.price_quote(self.pref,self.market['vendor_ref'],'ITEM-GRAIN',1,event_ref='u13:q3'); a=self.ec.execute_trade(q['quote']['quote_ref'],event_ref='u13:buy2'); b=self.ec.execute_trade(q['quote']['quote_ref'],event_ref='u13:buy2'); self.assertTrue(b['idempotent_replay']); self.assertEqual(self.i.inventory_snapshot(self.pref)['stacks'].get('ITEM-GRAIN',0),before+1)
 def test_10_sell(self):
  before=self.ec.wallet(self.pref)['balance']; q=self.ec.price_quote(self.pref,self.market['vendor_ref'],'ITEM-GRAIN',1,direction='SELL',event_ref='u13:sq'); x=self.ec.execute_trade(q['quote']['quote_ref'],event_ref='u13:sell'); self.assertEqual(x['status'],'PASS'); self.assertGreater(self.ec.wallet(self.pref)['balance'],before)
 def test_11_market_demand_changes(self):
  row=self.e.runtime.conn.execute('SELECT demand_index FROM arpg_economy_market WHERE world_instance_id=? AND location_ref=? AND item_ref=?',(self.wid,'POI-002','ITEM-GRAIN')).fetchone(); self.assertNotEqual(round(float(row['demand_index']),6),1.0)
 def test_12_bridge_logistics_factor(self):
  self.m.set_bridge_condition('POI-046',0); q=self.ec.price_quote(self.pref,self.market['vendor_ref'],'ITEM-FRUIT',1,event_ref='u13:bridgeq'); self.assertEqual(q['quote']['factors']['logistics'],1.25); self.m.set_bridge_condition('POI-046',100)
 def test_13_stash(self):
  if self.i.inventory_snapshot(self.pref)['stacks'].get('ITEM-GRAIN',0)<1:self.i.grant_item(self.pref,'ITEM-GRAIN',1,event_ref='u13:stashgrant')
  st=self.ec.ensure_stash(self.pref); self.ec.stash_deposit(self.pref,'ITEM-GRAIN',1,event_ref='u13:stashdep'); self.assertGreaterEqual(self.i.inventory_snapshot(st)['stacks'].get('ITEM-GRAIN',0),1); self.ec.stash_withdraw(self.pref,'ITEM-GRAIN',1,event_ref='u13:stashout')
 def test_14_craft_missing_rejected(self):
  # Fresh canonical ingredient not guaranteed in this quantity.
  x=self.ec.craft(self.pref,'CRFT-S13-BARRA-VIAGEM',event_ref='u13:craftmissing'); self.assertEqual(x['status'],'REJECTED')
 def test_15_culinary_craft(self):
  self.i.grant_item(self.pref,'ECO-GOOD-000006',1,event_ref='u13:grilo'); x=self.ec.craft(self.pref,'CRFT-S13-GRILO-TOSTADO',event_ref='u13:craft'); self.assertEqual(x['status'],'PASS'); self.assertEqual(self.i.definition('CUL-PREP-NORM-TER011-001')['canonical_identity'],True)
 def test_16_unified_crafting_catalog(self):
  c=self.ec.list_crafting_catalog(); self.assertEqual(len(c['stage13_culinary']),4); self.assertGreaterEqual(len(c['stage11_technology']),4)
 def test_17_technology_dispatch(self):
  self.i.grant_item(self.pref,'MIN-COPPER',2,event_ref='u13:tc'); self.i.grant_item(self.pref,'MIN-QUARTZ',1,event_ref='u13:tq'); mach=next(x for x in self.t.list_machines() if self.t.machine_profile(x['profile_ref'])['machine_class']=='FABRICATION'); x=self.ec.craft_dispatch(self.pref,'RECIPE-CIRCUIT-STAGE11',machine_ref=mach['machine_ref'],event_ref='u13:techcraft'); self.assertEqual(x['status'],'PASS')
 def test_18_repair_service(self):
  g=self.i.grant_item(self.pref,'WPN-001',1,event_ref='u13:wg'); ir=g['instance_refs'][0]; self.i.apply_durability_loss(self.pref,ir,10,event_ref='u13:wear'); before=self.i.instance(ir)['durability']; x=self.ec.repair_service(self.pref,self.workshop['vendor_ref'],ir,event_ref='u13:repair'); self.assertEqual(x['status'],'PASS'); self.assertGreater(self.i.instance(ir)['durability'],before)
 def test_19_npc_shared_economy(self):
  npc=next(self.e.country(self.wid)._all_npc_records())['id']; self.ec.ensure_wallet(npc,100); self.i.grant_item(npc,'ITEM-GRAIN',1,event_ref='u13:npcgrain'); q=self.ec.price_quote(npc,self.market['vendor_ref'],'ITEM-GRAIN',1,direction='SELL',event_ref='u13:npcq'); x=self.ec.execute_trade(q['quote']['quote_ref'],event_ref='u13:npcsell'); self.assertEqual(x['status'],'PASS')
 def test_20_event_conflict(self):
  with self.assertRaises(ConflictError): self.ec.price_quote(self.pref,self.market['vendor_ref'],'ITEM-FRUIT',2,event_ref='u13:q1')
 def test_21_verify(self): self.assertEqual(self.ec.verify()['status'],'PASS')

class Stage13PersistenceTests(unittest.TestCase):
 def test_persistence_resume(self):
  with tempfile.TemporaryDirectory() as td:
   db=os.path.join(td,'s13.sqlite'); e=IntegratedARPGEngineV13(db,master_release_path=MASTER); r=e.create_world('persist:s13',131314); wid=r['world']['world_instance_id']; ec=e.economy_arpg(wid); p=e.arpg(wid).create_profile('persist:s13',origin_mode='CREATED',display_name='Persist Economy')['profile']['profile_ref']; ec.ensure_wallet(p,600); market=next(v for v in ec.list_vendors() if v['location_ref']=='POI-002'); q=ec.price_quote(p,market['vendor_ref'],'ITEM-GRAIN',1,event_ref='p:q'); ec.execute_trade(q['quote']['quote_ref'],event_ref='p:t'); st=ec.ensure_stash(p); ec.stash_deposit(p,'ITEM-GRAIN',1,event_ref='p:s'); before=(ec.wallet(p),e.items_arpg(wid).inventory_snapshot(st)); e.runtime.close(); e2=IntegratedARPGEngineV13(db,master_release_path=MASTER); e2.resume_world(wid); ec2=e2.economy_arpg(wid); after=(ec2.wallet(p),e2.items_arpg(wid).inventory_snapshot(st)); self.assertEqual(before,after); self.assertEqual(e2.health_arpg_v13(wid)['status'],'PASS'); e2.runtime.close()
if __name__=='__main__':unittest.main(verbosity=2)
