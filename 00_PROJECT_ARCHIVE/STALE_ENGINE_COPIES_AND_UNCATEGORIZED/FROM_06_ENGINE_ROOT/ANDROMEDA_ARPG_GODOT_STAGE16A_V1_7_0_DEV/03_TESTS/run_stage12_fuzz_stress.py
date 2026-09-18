import copy,json,os,random,tempfile,threading,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'01_RUNTIME'))
from living_runtime import LivingRuntime,new_runtime_id,clock_point
from agent_brain import IntentValidator
from social_memory import SocialMemorySystem
from llm_gateway import ControlledLLMGateway
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'; OUT=Path(__file__).resolve().parents[1]/'04_REPORTS/STAGE12_FUZZ_STRESS_V1_0.json'
def ent(rt,w,n):
 c=rt.get_clock(w['world_instance_id']); s={'state_id':new_runtime_id('state'),'world_instance_id':w['world_instance_id'],'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{'name':n,'role':'npc','location_ref':'L1','money':10}}; rt.register_entity(w['world_instance_id'],s); return s
def pol(): return {'policy_key':'p.eat','action_type':'EAT','allowed_sources':['LLM_CANDIDATE'],'actor_kinds':['AGENT'],'target_required':False,'target_kinds':[],'offline_policy':'ACTIVE_ONLY','spatial_policy':'NONE','protection_impacts':[],'cooldown_ticks':0,'parameter_schema':{},'resource_requirements':[],'actor_state_equals':{},'target_state_equals':{},'consequence_templates':[]}
class DeterministicStressProvider:
 provider_id='stage12-stress-deterministic-v1'
 def __init__(self): self.calls=0; self._lock=threading.Lock()
 def generate(self,request):
  with self._lock: self.calls+=1
  key=request['request_key']
  if key=='same-stress': return {'dialogue':'ok','candidate_intent':None}
  i=int(key.split('-',1)[1]); mode=i%5
  if mode==0: return {'dialogue':'ok','candidate_intent':{'intent_type':'EAT','parameters':{}}}
  if mode==1: return {'dialogue':'lie 999','candidate_intent':None}
  if mode==2: return {'dialogue':'hack','candidate_intent':None,'mutations':[1]}
  if mode==3: return {'dialogue':'hack','candidate_intent':{'intent_type':'EAT','parameters':{'action_id':'x'}}}
  return {'dialogue':'ok','candidate_intent':None}

tmp=tempfile.TemporaryDirectory(); db=os.path.join(tmp.name,'s.db'); rt=LivingRuntime(db,master_release_path=MASTER); w=rt.create_world('s12-stress',44,ticks_per_day=24); wid=w['world_instance_id']; val=IntentValidator(rt); social=SocialMemorySystem(rt); gw=ControlledLLMGateway(rt,val,social); a=ent(rt,w,'A'); val.register_policy(wid,pol()); p=DeterministicStressProvider(); gw.bind_provider(p); gw.register_profile(wid,a['entity_runtime_id'],provider_id=p.provider_id,allowed_intents=['EAT'])
errs=[]; outs=[]
def same():
 try: outs.append(gw.converse(wid,a['entity_runtime_id'],user_text='same',request_key='same-stress'))
 except Exception as e: errs.append(repr(e))
ts=[threading.Thread(target=same) for _ in range(64)]; [t.start() for t in ts]; [t.join() for t in ts]
same_ok=not errs and len(outs)==64 and len({x['turn_id'] for x in outs})==1 and p.calls==1
# 1200 unique requests through 24 callers. Provider is intentionally deterministic; gateway serializes per SQLite connection.
lock=threading.Lock(); results=[]
def worker(base):
 local=[]
 for j in range(50):
  i=base+j
  try:
   r=gw.converse(wid,a['entity_runtime_id'],user_text=f'input {i} ignore previous',request_key=f'u-{i}'); local.append(r['guard_status'])
  except Exception as e: errs.append(repr(e))
 with lock: results.extend(local)
ts=[threading.Thread(target=worker,args=(k*50,)) for k in range(24)]; [t.start() for t in ts]; [t.join() for t in ts]
# reopen and verify persisted hashes; rebind needed only for future generation
rt.close(); rt=LivingRuntime(db,master_release_path=MASTER); val=IntentValidator(rt); social=SocialMemorySystem(rt); gw2=ControlledLLMGateway(rt,val,social)
integ=gw2.full_integrity_check(wid); core=rt.full_integrity_check(wid); soc=social.full_integrity_check(wid)
with rt._write_lock:
 sql=rt.conn.execute('pragma integrity_check').fetchone()[0]; fk=len(rt.conn.execute('pragma foreign_key_check').fetchall()); reqs=rt.conn.execute('select count(*) c from llm_requests').fetchone()['c']; turns=rt.conn.execute('select count(*) c from llm_conversation_turns').fetchone()['c']; execs=rt.conn.execute('select count(*) c from intent_executions').fetchone()['c']
status='PASS' if same_ok and not errs and len(results)==1200 and integ['status']=='PASS' and core['status']=='PASS' and soc['status']=='PASS' and sql=='ok' and fk==0 and execs==0 else 'FAIL'
rep={'record_id':'STAGE12-FUZZ-STRESS-V1.0','status':status,'same_request_callers':64,'same_request_converged':same_ok,'unique_requests_attempted':1200,'unique_results':len(results),'guard_pass':results.count('PASS'),'guard_rejected':results.count('REJECTED'),'errors':errs[:20],'persisted_requests':reqs,'persisted_turns':turns,'intent_executions':execs,'gateway_integrity':integ['status'],'runtime_integrity':core['status'],'social_integrity':soc['status'],'sqlite_integrity':sql,'foreign_key_failures':fk}
OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2)); print(json.dumps(rep,ensure_ascii=False)); rt.close(); tmp.cleanup(); raise SystemExit(0 if status=='PASS' else 1)
