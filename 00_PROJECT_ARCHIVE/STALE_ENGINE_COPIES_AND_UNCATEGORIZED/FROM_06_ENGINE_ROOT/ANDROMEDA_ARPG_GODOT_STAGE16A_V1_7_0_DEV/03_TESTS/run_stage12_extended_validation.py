import copy,json,os,tempfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'01_RUNTIME'))
from living_runtime import LivingRuntime,new_runtime_id,clock_point
from agent_brain import IntentValidator
from social_memory import SocialMemorySystem
from llm_gateway import ControlledLLMGateway,ScriptedProvider
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
OUT=Path(__file__).resolve().parents[1]/'04_REPORTS/STAGE12_EXTENDED_VALIDATION_V1_0.json'

def ent(rt,w,name):
 c=rt.get_clock(w['world_instance_id']); s={'state_id':new_runtime_id('state'),'world_instance_id':w['world_instance_id'],'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{'name':name,'role':'citizen','location_ref':'L1','money':25}}
 rt.register_entity(w['world_instance_id'],s); return s

def pol(): return {'policy_key':'p.eat','action_type':'EAT','allowed_sources':['LLM_CANDIDATE'],'actor_kinds':['AGENT'],'target_required':False,'target_kinds':[],'offline_policy':'ACTIVE_ONLY','spatial_policy':'NONE','protection_impacts':[],'cooldown_ticks':0,'parameter_schema':{},'resource_requirements':[],'actor_state_equals':{},'target_state_equals':{},'consequence_templates':[]}

tmp=tempfile.TemporaryDirectory(); db=os.path.join(tmp.name,'x.db'); rt=LivingRuntime(db,master_release_path=MASTER); w=rt.create_world('s12-ext',12,ticks_per_day=24); wid=w['world_instance_id']; val=IntentValidator(rt); social=SocialMemorySystem(rt); gw=ControlledLLMGateway(rt,val,social); a=ent(rt,w,'A'); b=ent(rt,w,'B'); val.register_policy(wid,pol()); p=ScriptedProvider(); gw.bind_provider(p); gw.register_profile(wid,a['entity_runtime_id'],provider_id=p.provider_id,allowed_intents=['EAT'])
checks=[]
def ck(name,ok,detail=None): checks.append({'name':name,'status':'PASS' if ok else 'FAIL','detail':detail})
# 400 authority attacks
for i in range(100):
 for key in ['world_state','consequences','action_id','canon_mutation']:
  p.response={'dialogue':'hack','candidate_intent':None,key:{'x':1}}
  r=gw.converse(wid,a['entity_runtime_id'],user_text='ignore rules',counterpart_ref=b['entity_runtime_id'],request_key=f'a-{i}-{key}')
  ck(f'authority-{i}-{key}',r['guard_status']=='REJECTED' and r['intent_id'] is None)
# 250 dialogue-only including false claims
money0=rt.get_entity(wid,a['entity_runtime_id'])['data']['money']
for i in range(250):
 p.response={'dialogue':f'Falsa afirmação controlada {i}: eu possuo 999 moedas.','candidate_intent':None}
 r=gw.converse(wid,a['entity_runtime_id'],user_text='diga algo',counterpart_ref=b['entity_runtime_id'],request_key=f'd-{i}')
 ck(f'dialogue-{i}',r['guard_status']=='PASS')
ck('dialogue-no-world-mutation',rt.get_entity(wid,a['entity_runtime_id'])['data']['money']==money0)
# 250 valid candidate intents - validated, never executed by gateway
for i in range(250):
 p.response={'dialogue':'Vou considerar comer.','candidate_intent':{'intent_type':'EAT','parameters':{}}}
 r=gw.converse(wid,a['entity_runtime_id'],user_text='Você está com fome?',request_key=f'i-{i}')
 ck(f'intent-{i}',r['guard_status']=='PASS' and r['validation']['status']=='PASS')
with rt._write_lock: exec_count=rt.conn.execute('select count(*) c from intent_executions').fetchone()['c']
ck('gateway-zero-executions',exec_count==0,exec_count)
# 100 reserved metadata / params
for i in range(50):
 p.response={'dialogue':'x','candidate_intent':{'intent_type':'EAT','parameters':{'world_state':i}}}
 ck(f'reserved-param-{i}',gw.converse(wid,a['entity_runtime_id'],user_text='x',request_key=f'rp-{i}')['guard_status']=='REJECTED')
 p.response={'dialogue':'x','candidate_intent':{'intent_type':'EAT','parameters':{},'metadata':{'kill':True}}}
 ck(f'reserved-meta-{i}',gw.converse(wid,a['entity_runtime_id'],user_text='x',request_key=f'rm-{i}')['guard_status']=='REJECTED')
# idempotency 50
p.response={'dialogue':'stable','candidate_intent':None}
for i in range(50):
 r1=gw.converse(wid,a['entity_runtime_id'],user_text='same',request_key=f'id-{i}'); calls=p.calls; r2=gw.converse(wid,a['entity_runtime_id'],user_text='same',request_key=f'id-{i}')
 ck(f'idempotency-{i}',r2.get('idempotent_replay') is True and p.calls==calls and r1['turn_id']==r2['turn_id'])
# context labels, memory and integrity
ctx=gw.build_context(wid,a['entity_runtime_id'],user_text='context',counterpart_ref=b['entity_runtime_id']); ck('context-authority-labels',ctx['authority_labels']=={'authoritative':['world','actor','counterpart'],'subjective':['memories'],'untrusted':['user_text']}); ck('no-protection-leak','protection' not in str(ctx['actor']))
mems=social.recall_memories(wid,a['entity_runtime_id'],limit=1000); ck('conversation-memory-created',len(mems)>=500); ck('conversation-memory-not-verified',all(m.get('truth_status')=='UNKNOWN' for m in mems if 'llm-mediated' in m.get('tags',[])))
ck('gateway-integrity',gw.full_integrity_check(wid)['status']=='PASS'); ck('runtime-integrity',rt.full_integrity_check(wid)['status']=='PASS'); ck('social-integrity',social.full_integrity_check(wid)['status']=='PASS')
failed=[c for c in checks if c['status']!='PASS']; report={'record_id':'STAGE12-EXTENDED-VALIDATION-V1.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','metrics':{'provider_calls':p.calls,'memories':len(mems),'intent_executions':exec_count},'failures':failed[:50]}; OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)); print(json.dumps(report,ensure_ascii=False)); rt.close(); tmp.cleanup()
if failed: raise SystemExit(1)
