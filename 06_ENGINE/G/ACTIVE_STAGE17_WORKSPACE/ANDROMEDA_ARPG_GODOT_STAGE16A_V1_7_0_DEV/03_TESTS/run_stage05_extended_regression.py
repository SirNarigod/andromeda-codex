import copy, json, os, tempfile, threading, time, sqlite3, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from living_runtime import LivingRuntime, ValidationError, ConflictError, NotFoundError, OfflinePolicyError, new_runtime_id, clock_point
from agent_brain import AgentBrain, IntentValidator
from consequence_engine import ConsequenceEngine

MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
checks=[]
def check(name, cond, detail=None):
    checks.append({'check':name,'status':'PASS' if cond else 'FAIL','detail':detail})
    if not cond: raise AssertionError(f'{name}: {detail}')

def agent_data(**kw):
    d={'needs':{'hunger':80,'work':90},'goals':{'survive':90,'earn':80},'risk_tolerance':45,'location_ref':'LOC-A','money':1000,'energy':100}
    d.update(kw); return d

def make_entity(rt,w,kind='AGENT',data=None,canonical_ref=None,protection=None):
    c=rt.get_clock(w['world_instance_id'])
    s={'state_id':new_runtime_id('state'),'world_instance_id':w['world_instance_id'],'timeline_id':w['timeline_id'],
       'entity_runtime_id':new_runtime_id(kind.lower()),'origin':'CANONICAL_BACKED' if canonical_ref else 'RUNTIME_BORN',
       'entity_kind':kind,'lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':copy.deepcopy(data or {})}
    if canonical_ref:s['canonical_ref']=canonical_ref
    if protection:s['protection']=copy.deepcopy(protection)
    rt.register_entity(w['world_instance_id'],s);return s

def policy(action,**kw):
    p={'policy_key':f'policy.{action.lower()}','action_type':action,'allowed_sources':['AGENT_BRAIN','LLM_CANDIDATE','PLAYER_INPUT'],
       'actor_kinds':['AGENT'],'target_required':False,'target_kinds':[],'offline_policy':'ACTIVE_ONLY','spatial_policy':'NONE',
       'protection_impacts':[],'cooldown_ticks':0,'parameter_schema':{},'resource_requirements':[],'target_resource_requirements':[],
       'actor_state_equals':{},'target_state_equals':{},'consequence_templates':[]}
    p.update(copy.deepcopy(kw));return p

def behavior(key,action,**kw):
    b={'behavior_key':key,'intent_type':action,'need_key':'work','threshold':1,'target_strategy':'NONE','need_weight':100,'base_priority':0,
       'risk_cost':0,'risk_penalty_weight':1,'opportunity_bonus':0,'goal_key':'earn','goal_weight':10,'target_kinds':[],
       'target_fact_equals':{},'agent_state_equals':{},'parameters':{}}
    b.update(copy.deepcopy(kw));return b

start=time.time();tmp=tempfile.TemporaryDirectory();db=os.path.join(tmp.name,'stage5.db')
rt=LivingRuntime(db,master_release_path=MASTER);w=rt.create_world('stage5-extended',50505,ticks_per_day=24);wid=w['world_instance_id']
val=IntentValidator(rt);brain=AgentBrain(rt,val);eng=ConsequenceEngine(rt)

# 1. Canonical-backed agent resolves against sealed Master.
canon_agent=make_entity(rt,w,'AGENT',agent_data(role='guard'),canonical_ref='PER-003')
check('canonical_agent_PER_003_materialized',rt.get_entity(wid,canon_agent['entity_runtime_id'])['canonical_ref']=='PER-003')

# 2. Deterministic autonomous work pipeline at scale.
val.register_policy(wid,policy('WORK',resource_requirements=[{'field_path':'data.energy','min_value':1,'consume_amount':1}],
    consequence_templates=[{'target':'ACTOR','operation':'INCREMENT','field_path':'data.money','amount':2}]))
brain.register_behavior(wid,behavior('work.primary','WORK',agent_state_equals={'data.role':'worker'}))
agents=[make_entity(rt,w,'AGENT',agent_data(role='worker')) for _ in range(200)]
for _ in range(5):
    for a in agents:
        d=brain.decide(wid,a['entity_runtime_id']);v=val.validate_intent(d['intent_id']);
        if v['status']!='PASS': raise AssertionError(v)
        val.execute_validated_intent(d['intent_id'])
check('1000_agent_decision_validation_execution_cycles',all(rt.get_entity(wid,a['entity_runtime_id'])['data']['money']==1010 for a in agents),{'agents':200,'cycles':5})
check('agent_energy_costs_transactional',all(rt.get_entity(wid,a['entity_runtime_id'])['data']['energy']==95 for a in agents))

# 3. Shared-stock race: exactly one of two stale validated intents may consume final unit.
val.register_policy(wid,policy('BUY_ONE',target_required=True,target_kinds=['OBJECT'],parameter_schema={'amount':{'type':'integer','required':True,'min':1,'max':1}},
    resource_requirements=[{'field_path':'data.money','min_value':1,'consume_amount':1}],
    target_resource_requirements=[{'field_path':'data.stock','min_from_parameter':'amount','consume_from_parameter':'amount'}]))
race_success=0;race_conflict=0
for _ in range(100):
    shop=make_entity(rt,w,'OBJECT',{'stock':1,'location_ref':'LOC-A'})
    buyers=[make_entity(rt,w,'AGENT',agent_data()) for _ in range(2)]
    intents=[]
    for b in buyers:
        i=val.submit_intent(wid,actor_ref=b['entity_runtime_id'],target_ref=shop['entity_runtime_id'],intent_type='BUY_ONE',parameters={'amount':1})
        v=val.validate_intent(i['intent_id']); check('race_prevalidation_pass',v['status']=='PASS')
        intents.append(i['intent_id'])
    outcomes=[]
    def ex(iid):
        try: val.execute_validated_intent(iid); outcomes.append('OK')
        except ConflictError: outcomes.append('CONFLICT')
    ts=[threading.Thread(target=ex,args=(iid,)) for iid in intents];[t.start() for t in ts];[t.join() for t in ts]
    race_success+=outcomes.count('OK');race_conflict+=outcomes.count('CONFLICT')
    check('race_stock_never_negative',rt.get_entity(wid,shop['entity_runtime_id'])['data']['stock']==0,outcomes)
check('100_shared_stock_races_serialized',race_success==100 and race_conflict==100,{'success':race_success,'conflict':race_conflict})

# 4. Protection inference: target lifecycle DEAD automatically requires DEATH authority.
val.register_policy(wid,policy('KILL_PROTECTED',target_required=True,target_kinds=['AGENT'],consequence_templates=[{'target':'TARGET','operation':'SET','field_path':'lifecycle','value':'DEAD'}]))
blocked=0
for _ in range(100):
    target=make_entity(rt,w,'AGENT',agent_data(),protection={'death':'BLOCKED'})
    actor=make_entity(rt,w,'AGENT',agent_data())
    i=val.submit_intent(wid,actor_ref=actor['entity_runtime_id'],target_ref=target['entity_runtime_id'],intent_type='KILL_PROTECTED')
    v=val.validate_intent(i['intent_id']); blocked += int('NARRATIVE_PROTECTION_DEATH' in v['reasons'])
check('100_protected_deaths_blocked_by_inferred_impact',blocked==100,blocked)

# 5. Perception may be false; validator truth wins.
val.register_policy(wid,policy('TRADE_TRUTH',target_required=True,target_kinds=['AGENT'],target_state_equals={'data.shop_open':True}))
brain.register_behavior(wid,behavior('trade.false-belief','TRADE_TRUTH',need_key='hunger',target_strategy='PERCEPTION',target_kinds=['AGENT'],target_fact_equals={'shop_open':True}))
false_rejected=0
for _ in range(100):
    actor=make_entity(rt,w,'AGENT',agent_data(role='trader'))
    target=make_entity(rt,w,'AGENT',agent_data(shop_open=False))
    brain.record_perception(wid,actor['entity_runtime_id'],[{'target_ref':target['entity_runtime_id'],'perceived_kind':'AGENT','facts':{'shop_open':True},'confidence':1.0}])
    d=brain.decide(wid,actor['entity_runtime_id']);v=val.validate_intent(d['intent_id']);false_rejected += int(v['status']=='REJECTED')
check('100_false_perceptions_cannot_override_world_truth',false_rejected==100,false_rejected)

# 6. LLM adversarial boundary.
val.register_policy(wid,policy('SAY',allowed_sources=['LLM_CANDIDATE'],parameter_schema={'tone':{'type':'string','required':True,'enum':['calm','firm']}}))
llm_rejected=0;llm_valid=0
actor=make_entity(rt,w,'AGENT',agent_data())
for n in range(500):
    if n%5==0:
        cand={'actor_ref':actor['entity_runtime_id'],'intent_type':'SAY','parameters':{'tone':'calm'}}
        i=val.ingest_llm_candidate(wid,cand);v=val.validate_intent(i['intent_id']);llm_valid+=int(v['status']=='PASS')
    elif n%5==1:
        try: val.ingest_llm_candidate(wid,{'actor_ref':actor['entity_runtime_id'],'intent_type':'SAY','consequences':[]})
        except ValidationError: llm_rejected+=1
    elif n%5==2:
        i=val.ingest_llm_candidate(wid,{'actor_ref':actor['entity_runtime_id'],'intent_type':'SAY','parameters':{'execution_class':'ROUTINE_SAFE'}});v=val.validate_intent(i['intent_id']);llm_rejected+=int(v['status']=='REJECTED')
    elif n%5==3:
        i=val.ingest_llm_candidate(wid,{'actor_ref':actor['entity_runtime_id'],'intent_type':'SAY','parameters':{'tone':'invented'}});v=val.validate_intent(i['intent_id']);llm_rejected+=int(v['status']=='REJECTED')
    else:
        i=val.ingest_llm_candidate(wid,{'actor_ref':actor['entity_runtime_id'],'intent_type':'UNKNOWN','parameters':{}});v=val.validate_intent(i['intent_id']);llm_rejected+=int(v['status']=='REJECTED')
check('500_llm_boundary_cases',llm_valid==100 and llm_rejected==400,{'valid':llm_valid,'rejected':llm_rejected})

# 7. Offline: brain is blocked; routine system can continue.
rt.set_simulation_mode(wid,'ROUTINE_OFFLINE')
offline_block=False
try: brain.decide(wid,agents[0]['entity_runtime_id'])
except OfflinePolicyError: offline_block=True
check('agent_brain_offline_blocked',offline_block)
val.register_policy(wid,policy('SLEEP_ROUTINE',allowed_sources=['SYSTEM_ROUTINE'],offline_policy='ROUTINE_SAFE',consequence_templates=[{'target':'ACTOR','operation':'SET','field_path':'data.energy','value':100}]))
i=val.submit_intent(wid,actor_ref=agents[0]['entity_runtime_id'],intent_type='SLEEP_ROUTINE',source='SYSTEM_ROUTINE')
v=val.validate_intent(i['intent_id']);check('system_routine_offline_validates',v['status']=='PASS');val.execute_validated_intent(i['intent_id'])
check('system_routine_offline_executes',rt.get_entity(wid,agents[0]['entity_runtime_id'])['data']['energy']==100)
rt.set_simulation_mode(wid,'FULL')

# 8. Integration with Consequence Engine: validated agent event fans out causally.
group=make_entity(rt,w,'GROUP',{'activity':0})
eng.register_relation(wid,canon_agent['entity_runtime_id'],group['entity_runtime_id'],'MEMBER_OF')
eng.register_rule(wid,{
 'name':'work raises group activity','trigger_event_type':'GUARD_WORK','relation_type':'MEMBER_OF','direction':'OUTGOING','derived_event_type':'GROUP_ACTIVITY',
 'priority':0,'max_depth':2,'offline_policy':'ACTIVE_ONLY','target_entity_kinds':['GROUP'],'event_payload_equals':{},
 'consequences':[{'operation':'INCREMENT','field_path':'data.activity','amount':1}]
})
val.register_policy(wid,policy('GUARD_WORK',consequence_templates=[{'target':'ACTOR','operation':'DECREMENT','field_path':'data.energy','amount':1}]))
eng.attach_auto_propagation()
i=val.submit_intent(wid,actor_ref=canon_agent['entity_runtime_id'],intent_type='GUARD_WORK');v=val.validate_intent(i['intent_id']);check('brain_to_causal_integration_validates',v['status']=='PASS');val.execute_validated_intent(i['intent_id'])
eng.detach_auto_propagation()
check('validated_agent_event_propagates_to_group',rt.get_entity(wid,group['entity_runtime_id'])['data']['activity']==1)

# 9. Multi-timeline isolation and deterministic choice.
selections=[]
for n in range(8):
    w2=rt.create_world(f'iso-{n}',900+n,ticks_per_day=24);wid2=w2['world_instance_id'];v2=IntentValidator(rt);b2=AgentBrain(rt,v2)
    a2=make_entity(rt,w2,'AGENT',agent_data(role='worker'))
    b2.register_behavior(wid2,behavior('a','A',base_priority=10));b2.register_behavior(wid2,behavior('b','B',base_priority=5))
    d=b2.decide(wid2,a2['entity_runtime_id']);selections.append((d['selected']['behavior_key'],d['selected']['score']))
check('8_timelines_same_state_deterministic_choice',len(set(selections))==1,selections)

# 10. Native SQLite + component integrity before reopen.
check('runtime_integrity_before_reopen',rt.full_integrity_check(wid)['status']=='PASS')
check('validator_integrity_before_reopen',val.full_integrity_check(wid)['status']=='PASS')
check('brain_integrity_before_reopen',brain.full_integrity_check(wid)['status']=='PASS')
check('consequence_integrity_before_reopen',eng.full_integrity_check(wid)['status']=='PASS')
quick=rt.conn.execute('PRAGMA quick_check').fetchone()[0];fk=rt.conn.execute('PRAGMA foreign_key_check').fetchall()
check('sqlite_quick_check',quick=='ok',quick);check('sqlite_foreign_key_check',len(fk)==0,len(fk))
rt.close()

# 11. Reopen persistence and integrity.
rt2=LivingRuntime(db,master_release_path=MASTER);val2=IntentValidator(rt2);brain2=AgentBrain(rt2,val2);eng2=ConsequenceEngine(rt2)
check('reopen_world_persisted',rt2.get_world(wid)['status']=='ACTIVE')
check('reopen_integrity_runtime',rt2.full_integrity_check(wid)['status']=='PASS')
check('reopen_integrity_validator',val2.full_integrity_check(wid)['status']=='PASS')
check('reopen_integrity_brain',brain2.full_integrity_check(wid)['status']=='PASS')
check('reopen_integrity_consequence',eng2.full_integrity_check(wid)['status']=='PASS')
check('sqlite_integrity_check_after_reopen',rt2.conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok')

counts={t:rt2.conn.execute(f'SELECT COUNT(*) c FROM {t}').fetchone()['c'] for t in ['entity_states','agent_decisions','intents','intent_validations','intent_executions','events','consequences']}
rt2.close();tmp.cleanup()
report={'record_id':'LIVING-SIM-ETAPA-05-EXTENDED-VALIDATION-V1.0','checks':len(checks),'passed':sum(x['status']=='PASS' for x in checks),'failed':sum(x['status']=='FAIL' for x in checks),
        'elapsed_seconds':round(time.time()-start,3),'scale':{'autonomous_cycles':1000,'shared_stock_races':100,'protected_targets':100,'false_perception_cases':100,'llm_boundary_cases':500,'timelines':9},
        'record_counts':counts,'details':checks}
report['status']='PASS' if report['failed']==0 else 'FAIL'
(ROOT/'04_REPORTS'/'STAGE05_EXTENDED_REGRESSION_V1_0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='details'},ensure_ascii=False,indent=2))
if report['status']!='PASS':raise SystemExit(1)
