import os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'01_RUNTIME'))
from living_runtime import LivingRuntime,new_runtime_id,clock_point,ConflictError
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
class DynamicSpawnV11Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.db=os.path.join(self.tmp.name,'s.db'); self.rt=LivingRuntime(self.db,master_release_path=MASTER); self.w=self.rt.create_world('spawn',1301,ticks_per_day=24); self.wid=self.w['world_instance_id']
 def tearDown(self):
  self.rt.close();self.tmp.cleanup()
 def test_spawn_is_event_atomic_and_replayable(self):
  w=self.rt.get_world(self.wid);c=w['clock_state']; eid=new_runtime_id('resource'); state={'state_id':new_runtime_id('state'),'world_instance_id':self.wid,'timeline_id':w['timeline_id'],'entity_runtime_id':eid,'origin':'RUNTIME_BORN','entity_kind':'RESOURCE_BUNDLE','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{'quantity':2}}
  a={'action_id':new_runtime_id('action'),'intent_id':new_runtime_id('intent'),'world_instance_id':self.wid,'timeline_id':w['timeline_id'],'actor_ref':'SYSTEM_RECONCILIATION','action_type':'TEST_DYNAMIC_SPAWN','parameters':{},'precondition_snapshot':{'entity_versions':{}},'idempotency_key':'spawn-1','created_at':clock_point(c['day'],c['tick']),'status':'SCHEDULED','source':'SYSTEM_RECONCILIATION','execution_class':'ROUTINE_SAFE'}
  r=self.rt.apply_action(self.wid,a,[{'target_ref':eid,'operation':'SPAWN','entity':state,'priority':0,'kind':'DIRECT'}]);self.assertEqual(r['status'],'SUCCEEDED');self.assertEqual(self.rt.get_entity(self.wid,eid)['data']['quantity'],2)
  self.assertFalse(self.rt.conn.execute('SELECT 1 FROM bootstrap_states WHERE entity_runtime_id=?',(eid,)).fetchone())
  self.assertEqual(self.rt.compare_replay_to_materialized(self.wid)['status'],'PASS')
 def test_duplicate_spawn_blocked(self):
  w=self.rt.get_world(self.wid);c=w['clock_state']; eid=new_runtime_id('resource'); state={'state_id':new_runtime_id('state'),'world_instance_id':self.wid,'timeline_id':w['timeline_id'],'entity_runtime_id':eid,'origin':'RUNTIME_BORN','entity_kind':'RESOURCE_BUNDLE','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{}}
  def act(key): return {'action_id':new_runtime_id('action'),'intent_id':new_runtime_id('intent'),'world_instance_id':self.wid,'timeline_id':w['timeline_id'],'actor_ref':'SYSTEM_RECONCILIATION','action_type':'TEST_DYNAMIC_SPAWN','parameters':{},'precondition_snapshot':{'entity_versions':{}},'idempotency_key':key,'created_at':clock_point(c['day'],c['tick']),'status':'SCHEDULED','source':'SYSTEM_RECONCILIATION','execution_class':'ROUTINE_SAFE'}
  self.rt.apply_action(self.wid,act('a'),[{'target_ref':eid,'operation':'SPAWN','entity':state,'priority':0,'kind':'DIRECT'}])
  with self.assertRaises(ConflictError): self.rt.apply_action(self.wid,act('b'),[{'target_ref':eid,'operation':'SPAWN','entity':state,'priority':0,'kind':'DIRECT'}])
if __name__=='__main__':unittest.main()
