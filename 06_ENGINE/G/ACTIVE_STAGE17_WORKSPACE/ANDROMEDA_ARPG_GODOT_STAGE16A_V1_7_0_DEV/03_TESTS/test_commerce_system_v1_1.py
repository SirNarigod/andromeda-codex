import hashlib, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'01_RUNTIME'))
from living_runtime import LivingRuntime, ConflictError, new_runtime_id, clock_point
from world_systems import WorldSystems
from commerce_system import CommerceSystem

MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
MASTER_SHA='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2'

def make_agent(rt,wid):
    w=rt.get_world(wid); c=w['clock_state']
    s={'state_id':new_runtime_id('state'),'world_instance_id':wid,'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{'name':'Buyer','location_ref':'POI-003'},'protection':{}}
    return rt.register_entity(wid,s)

class CommerceV11Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=os.path.join(self.tmp.name,'c.db')
        self.rt=LivingRuntime(self.db,master_release_path=MASTER); self.w=self.rt.create_world('commerce',1201,ticks_per_day=24); self.wid=self.w['world_instance_id']
        self.ws=WorldSystems(self.rt); self.ws.load_master_snapshots(MASTER); self.ws.bootstrap_world(self.wid,population_seed=1000)
        self.cs=CommerceSystem(self.rt,self.ws); self.cat=self.cs.load_catalog(MASTER)
        self.agent=make_agent(self.rt,self.wid); self.cs.create_account(self.wid,self.agent['entity_runtime_id'],starting_balance=500)
        self.vendor=self.cs.create_vendor(self.wid,'POI-003',stock_seed=5,starting_cash=1000)['vendor']
    def tearDown(self):
        try:self.rt.close()
        except:pass
        self.tmp.cleanup()
    def _mutate_wallet(self,delta,key='mutate-wallet'):
        acct=self.cs.account_state(self.wid,self.agent['entity_runtime_id']); wallet=self.rt.get_entity(self.wid,acct['wallet_runtime_id']); w=self.rt.get_world(self.wid);c=w['clock_state']
        a={'action_id':new_runtime_id('action'),'intent_id':new_runtime_id('intent'),'world_instance_id':self.wid,'timeline_id':w['timeline_id'],'actor_ref':'SYSTEM_RECONCILIATION','action_type':'TEST_WALLET_CHANGE','parameters':{},'precondition_snapshot':{'entity_versions':{wallet['entity_runtime_id']:wallet['version']}},'idempotency_key':key,'created_at':clock_point(c['day'],c['tick']),'status':'SCHEDULED','source':'SYSTEM_RECONCILIATION','execution_class':'ROUTINE_SAFE'}
        self.rt.apply_action(self.wid,a,[{'target_ref':wallet['entity_runtime_id'],'operation':'INCREMENT','field_path':'data.balance','value':delta,'priority':0,'kind':'DIRECT'}])
    def test_catalog_has_30_weapons_and_master_unchanged(self):
        self.assertEqual(self.cat['count'],30)
        self.assertEqual(hashlib.sha256(Path(MASTER).read_bytes()).hexdigest(),MASTER_SHA)
    def test_wpn003_available_at_poi003(self):
        self.assertIn('WPN-003',[i['id'] for i in self.cs.items_available_at('POI-003')])
    def test_relative_cost_resolves_numeric_runtime_price(self):
        q=self.cs.quote(self.wid,self.agent['entity_runtime_id'],self.vendor['entity_runtime_id'],'WPN-003')
        self.assertEqual(q['relative_cost'],'BAIXO'); self.assertGreater(q['unit_price'],0); self.assertEqual(q['numeric_price_authority'],'RUNTIME_ONLY')
        self.assertEqual(q['factors']['relative_band_base'],30.0)
    def test_scarcity_changes_price(self):
        q1=self.cs.quote(self.wid,self.agent['entity_runtime_id'],self.vendor['entity_runtime_id'],'WPN-003')
        # Force material/technology runtime pressure through regular flow state actions.
        for ref in ('FLOW-002','FLOW-003'):
            e=self.ws._entity_for(self.wid,'ECONOMIC_FLOW',ref); w=self.rt.get_world(self.wid);c=w['clock_state']
            a={'action_id':new_runtime_id('action'),'intent_id':new_runtime_id('intent'),'world_instance_id':self.wid,'timeline_id':w['timeline_id'],'actor_ref':'SYSTEM_RECONCILIATION','action_type':'TEST_SCARCITY','parameters':{'flow':ref},'precondition_snapshot':{'entity_versions':{e['entity_runtime_id']:e['version']}},'idempotency_key':f'scarcity-{ref}','created_at':clock_point(c['day'],c['tick']),'status':'SCHEDULED','source':'SYSTEM_RECONCILIATION','execution_class':'ROUTINE_SAFE'}
            self.rt.apply_action(self.wid,a,[{'target_ref':e['entity_runtime_id'],'operation':'SET','field_path':'data.shortage_pressure','value':100.0,'priority':0,'kind':'DIRECT'}])
        q2=self.cs.quote(self.wid,self.agent['entity_runtime_id'],self.vendor['entity_runtime_id'],'WPN-003')
        self.assertGreater(q2['unit_price'],q1['unit_price'])
    def test_route_disruption_increases_price(self):
        q1=self.cs.quote(self.wid,self.agent['entity_runtime_id'],self.vendor['entity_runtime_id'],'WPN-003')
        for rr in self.ws.resolve_location('POI-003')['route_ids']: self.ws.set_route_operational(self.wid,rr,False)
        q2=self.cs.quote(self.wid,self.agent['entity_runtime_id'],self.vendor['entity_runtime_id'],'WPN-003')
        self.assertGreater(q2['unit_price'],q1['unit_price'])
    def test_purchase_is_atomic_and_idempotent(self):
        q=self.cs.quote(self.wid,self.agent['entity_runtime_id'],self.vendor['entity_runtime_id'],'WPN-003')
        before=self.cs.account_state(self.wid,self.agent['entity_runtime_id']); vb=self.rt.get_entity(self.wid,self.vendor['entity_runtime_id'])
        tx=self.cs.execute_quote(q['quote_id'],idempotency_key='buy-one')
        after=self.cs.account_state(self.wid,self.agent['entity_runtime_id']); va=self.rt.get_entity(self.wid,self.vendor['entity_runtime_id'])
        self.assertAlmostEqual(after['balance'],before['balance']-q['total_price'],places=4)
        self.assertEqual(after['items']['WPN-003'],1); self.assertEqual(va['data']['stock']['WPN-003'],vb['data']['stock']['WPN-003']-1); self.assertAlmostEqual(va['data']['cash_balance'],vb['data']['cash_balance']+q['total_price'],places=4)
        replay=self.cs.execute_quote(q['quote_id'],idempotency_key='buy-one'); self.assertTrue(replay['idempotent_replay'])
        self.assertEqual(self.cs.account_state(self.wid,self.agent['entity_runtime_id'])['items']['WPN-003'],1)
        self.assertEqual(tx['event_type'],'COMMERCE_PURCHASE')
    def test_insufficient_funds_does_not_mutate(self):
        poor=make_agent(self.rt,self.wid); self.cs.create_account(self.wid,poor['entity_runtime_id'],starting_balance=1)
        q=self.cs.quote(self.wid,poor['entity_runtime_id'],self.vendor['entity_runtime_id'],'WPN-003')
        vb=self.rt.get_entity(self.wid,self.vendor['entity_runtime_id']); before=self.cs.account_state(self.wid,poor['entity_runtime_id'])
        with self.assertRaises(ConflictError): self.cs.execute_quote(q['quote_id'],idempotency_key='poor-buy')
        va=self.rt.get_entity(self.wid,self.vendor['entity_runtime_id']); after=self.cs.account_state(self.wid,poor['entity_runtime_id'])
        self.assertEqual(before['balance'],after['balance']); self.assertEqual(vb['data']['stock'],va['data']['stock'])
    def test_remote_purchase_quote_blocked(self):
        w=self.rt.get_world(self.wid); c=w['clock_state']; agent=self.rt.get_entity(self.wid,self.agent['entity_runtime_id'])
        a={'action_id':new_runtime_id('action'),'intent_id':new_runtime_id('intent'),'world_instance_id':self.wid,'timeline_id':w['timeline_id'],'actor_ref':'SYSTEM_RECONCILIATION','action_type':'TEST_MOVE','parameters':{},'precondition_snapshot':{'entity_versions':{agent['entity_runtime_id']:agent['version']}},'idempotency_key':'move-away','created_at':clock_point(c['day'],c['tick']),'status':'SCHEDULED','source':'SYSTEM_RECONCILIATION','execution_class':'ROUTINE_SAFE'}
        self.rt.apply_action(self.wid,a,[{'target_ref':agent['entity_runtime_id'],'operation':'SET','field_path':'data.location_ref','value':'BIO-008','priority':0,'kind':'DIRECT'}])
        with self.assertRaises(ConflictError): self.cs.quote(self.wid,self.agent['entity_runtime_id'],self.vendor['entity_runtime_id'],'WPN-003')
    def test_stale_quote_rejected(self):
        q=self.cs.quote(self.wid,self.agent['entity_runtime_id'],self.vendor['entity_runtime_id'],'WPN-003'); self._mutate_wallet(1)
        with self.assertRaises(ConflictError): self.cs.execute_quote(q['quote_id'],idempotency_key='stale')
    def test_sell_round_trip_and_integrity(self):
        q=self.cs.quote(self.wid,self.agent['entity_runtime_id'],self.vendor['entity_runtime_id'],'WPN-003'); self.cs.execute_quote(q['quote_id'],idempotency_key='buy')
        sell=self.cs.quote(self.wid,self.agent['entity_runtime_id'],self.vendor['entity_runtime_id'],'WPN-003',direction='SELL'); tx=self.cs.execute_quote(sell['quote_id'],idempotency_key='sell')
        acct=self.cs.account_state(self.wid,self.agent['entity_runtime_id']); self.assertEqual(acct['items']['WPN-003'],0)
        self.assertGreater(acct['balance'],500-q['total_price']); self.assertEqual(tx['event_type'],'COMMERCE_SALE'); self.assertEqual(self.cs.full_integrity_check(self.wid)['status'],'PASS')

if __name__=='__main__':unittest.main()
