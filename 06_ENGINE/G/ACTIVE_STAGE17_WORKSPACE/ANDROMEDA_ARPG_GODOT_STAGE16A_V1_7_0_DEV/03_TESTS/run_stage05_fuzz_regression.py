import copy, json, os, tempfile, threading, time, random, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from living_runtime import LivingRuntime, ValidationError, ConflictError, new_runtime_id, clock_point
from agent_brain import AgentBrain, IntentValidator
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'

def make(rt,w,kind='AGENT',data=None):
 c=rt.get_clock(w['world_instance_id']);s={'state_id':new_runtime_id('state'),'world_instance_id':w['world_instance_id'],'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id(kind.lower()),'origin':'RUNTIME_BORN','entity_kind':kind,'lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':copy.deepcopy(data or {})};rt.register_entity(w['world_instance_id'],s);return s

def ad():return {'needs':{'work':90},'goals':{'earn':80},'risk_tolerance':50,'location_ref':'L','money':0,'energy':100}
def pol(action,**kw):
 p={'policy_key':f'p.{action.lower()}','action_type':action,'allowed_sources':['AGENT_BRAIN','LLM_CANDIDATE'],'actor_kinds':['AGENT'],'target_required':False,'target_kinds':[],'offline_policy':'ACTIVE_ONLY','spatial_policy':'NONE','protection_impacts':[],'cooldown_ticks':0,'parameter_schema':{},'resource_requirements':[],'target_resource_requirements':[],'actor_state_equals':{},'target_state_equals':{},'consequence_templates':[]};p.update(copy.deepcopy(kw));return p
def beh():return {'behavior_key':'work','intent_type':'WORK','need_key':'work','threshold':1,'target_strategy':'NONE','need_weight':100,'base_priority':0,'risk_cost':0,'risk_penalty_weight':1,'opportunity_bonus':0,'goal_key':'earn','goal_weight':10,'target_kinds':[],'target_fact_equals':{},'agent_state_equals':{},'parameters':{}}

start=time.time();tmp=tempfile.TemporaryDirectory();db=os.path.join(tmp.name,'stress.db');rt=LivingRuntime(db,master_release_path=MASTER);w=rt.create_world('stress',7777,ticks_per_day=24);wid=w['world_instance_id'];val=IntentValidator(rt);brain=AgentBrain(rt,val)
val.register_policy(wid,pol('WORK',resource_requirements=[{'field_path':'data.energy','min_value':1,'consume_amount':1}],consequence_templates=[{'target':'ACTOR','operation':'INCREMENT','field_path':'data.money','amount':1}]))
brain.register_behavior(wid,beh())
agents=[make(rt,w,'AGENT',ad()) for _ in range(256)]
failures=[];ops=0;ops_lock=threading.Lock()
def worker(chunk):
 global ops
 for a in chunk:
  for _ in range(20):
   try:
    d=brain.decide(wid,a['entity_runtime_id']);v=val.validate_intent(d['intent_id'])
    if v['status']!='PASS':raise AssertionError(v)
    val.execute_validated_intent(d['intent_id'])
    with ops_lock: ops+=1
   except Exception as e:
    with ops_lock: failures.append(repr(e))
threads=[]
for i in range(32):
 chunk=agents[i::32];t=threading.Thread(target=worker,args=(chunk,));threads.append(t);t.start()
for t in threads:t.join()

# Adversarial LLM fuzz, deterministic seed.
rng=random.Random(505);llm_cases=3000;llm_expected_reject=0;llm_actual_reject=0
val.register_policy(wid,pol('SAY',allowed_sources=['LLM_CANDIDATE'],parameter_schema={'tone':{'type':'string','required':True,'enum':['calm','firm']},'urgency':{'type':'integer','required':False,'min':0,'max':10}}))
actor=agents[0]
for n in range(llm_cases):
 mode=rng.randrange(6)
 try:
  if mode==0:
   i=val.ingest_llm_candidate(wid,{'actor_ref':actor['entity_runtime_id'],'intent_type':'SAY','parameters':{'tone':'calm','urgency':rng.randrange(11)}});r=val.validate_intent(i['intent_id']);
   if r['status']!='PASS':failures.append('valid LLM unexpectedly rejected')
  elif mode==1:
   llm_expected_reject+=1
   try: val.ingest_llm_candidate(wid,{'actor_ref':actor['entity_runtime_id'],'intent_type':'SAY','mutations':[]})
   except ValidationError: llm_actual_reject+=1
  elif mode==2:
   llm_expected_reject+=1;i=val.ingest_llm_candidate(wid,{'actor_ref':actor['entity_runtime_id'],'intent_type':'SAY','parameters':{'tone':'evil'}});r=val.validate_intent(i['intent_id']);llm_actual_reject+=int(r['status']=='REJECTED')
  elif mode==3:
   llm_expected_reject+=1;i=val.ingest_llm_candidate(wid,{'actor_ref':actor['entity_runtime_id'],'intent_type':'SAY','parameters':{'tone':'calm','urgency':999}});r=val.validate_intent(i['intent_id']);llm_actual_reject+=int(r['status']=='REJECTED')
  elif mode==4:
   llm_expected_reject+=1;i=val.ingest_llm_candidate(wid,{'actor_ref':actor['entity_runtime_id'],'intent_type':'UNKNOWN','parameters':{}});r=val.validate_intent(i['intent_id']);llm_actual_reject+=int(r['status']=='REJECTED')
  else:
   llm_expected_reject+=1;i=val.ingest_llm_candidate(wid,{'actor_ref':actor['entity_runtime_id'],'intent_type':'SAY','parameters':{'tone':'calm','consequences':'x'}});r=val.validate_intent(i['intent_id']);llm_actual_reject+=int(r['status']=='REJECTED')
 except Exception as e: failures.append(f'llm:{e!r}')

# Shared resource race batches: 400 races, two prevalidated buyers for one stock unit.
val.register_policy(wid,pol('BUY',target_required=True,target_kinds=['OBJECT'],parameter_schema={'amount':{'type':'integer','required':True,'min':1,'max':1}},target_resource_requirements=[{'field_path':'data.stock','min_from_parameter':'amount','consume_from_parameter':'amount'}]))
races=400;race_ok=0;race_conflict=0
for _ in range(races):
 shop=make(rt,w,'OBJECT',{'stock':1});buyers=[make(rt,w,'AGENT',ad()) for _ in range(2)];ids=[]
 for b in buyers:
  i=val.submit_intent(wid,actor_ref=b['entity_runtime_id'],target_ref=shop['entity_runtime_id'],intent_type='BUY',parameters={'amount':1});v=val.validate_intent(i['intent_id']);
  if v['status']!='PASS':failures.append('race prevalidation failed')
  ids.append(i['intent_id'])
 out=[]
 def ex(x):
  try:val.execute_validated_intent(x);out.append('OK')
  except ConflictError:out.append('CONFLICT')
 ts=[threading.Thread(target=ex,args=(x,)) for x in ids];[t.start() for t in ts];[t.join() for t in ts]
 race_ok+=out.count('OK');race_conflict+=out.count('CONFLICT')
 if rt.get_entity(wid,shop['entity_runtime_id'])['data']['stock']!=0:failures.append('stock invariant')

# Verify results and persistence.
agent_ok=sum(1 for a in agents if rt.get_entity(wid,a['entity_runtime_id'])['data']['money']==20 and rt.get_entity(wid,a['entity_runtime_id'])['data']['energy']==80)
integ=brain.integrity_guard(wid);quick=rt.conn.execute('PRAGMA quick_check').fetchone()[0];fk=len(rt.conn.execute('PRAGMA foreign_key_check').fetchall())
rt.close();rt2=LivingRuntime(db,master_release_path=MASTER);val2=IntentValidator(rt2);brain2=AgentBrain(rt2,val2);reopen=brain2.integrity_guard(wid);native=rt2.conn.execute('PRAGMA integrity_check').fetchone()[0]
counts={t:rt2.conn.execute(f'SELECT COUNT(*) c FROM {t}').fetchone()['c'] for t in ['agent_decisions','intents','intent_validations','intent_executions','events','consequences']};rt2.close();tmp.cleanup()
status=(not failures and ops==5120 and agent_ok==256 and llm_actual_reject==llm_expected_reject and race_ok==races and race_conflict==races and integ['status']=='PASS' and reopen['status']=='PASS' and quick=='ok' and fk==0 and native=='ok')
report={'record_id':'LIVING-SIM-ETAPA-05-FUZZ-STRESS-V1.0','status':'PASS' if status else 'FAIL','elapsed_seconds':round(time.time()-start,3),'threads':32,'autonomous_operations':ops,'agents':256,'agent_final_invariant_pass':agent_ok,'llm_cases':llm_cases,'llm_expected_rejections':llm_expected_reject,'llm_actual_rejections':llm_actual_reject,'shared_stock_races':races,'race_successes':race_ok,'race_conflicts':race_conflict,'failures':failures[:50],'failure_count':len(failures),'integrity_before_reopen':integ['status'],'integrity_after_reopen':reopen['status'],'sqlite_quick_check':quick,'sqlite_foreign_key_failures':fk,'sqlite_integrity_after_reopen':native,'record_counts':counts}
(ROOT/'04_REPORTS'/'STAGE05_FUZZ_REGRESSION_V1_0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
if report['status']!='PASS':raise SystemExit(1)
