import copy, json, os, tempfile, time, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from living_runtime import LivingRuntime, ValidationError, ConflictError, OfflinePolicyError, new_runtime_id, clock_point
from agent_brain import AgentBrain, IntentValidator
from social_memory import SocialMemorySystem
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
checks=[]
def check(name,cond,detail=None):
    checks.append({'check':name,'status':'PASS' if cond else 'FAIL','detail':detail})
    if not cond: raise AssertionError(f'{name}:{detail}')
def ent(rt,w,kind='AGENT',data=None,protection=None):
    c=rt.get_clock(w['world_instance_id']); s={'state_id':new_runtime_id('state'),'world_instance_id':w['world_instance_id'],'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id(kind.lower()),'origin':'RUNTIME_BORN','entity_kind':kind,'lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':copy.deepcopy(data or {})}
    if protection:s['protection']=copy.deepcopy(protection)
    rt.register_entity(w['world_instance_id'],s); return s
def act(rt,w,actor,t='SOCIAL'):
    c=rt.get_clock(w['world_instance_id']); return {'action_id':new_runtime_id('action'),'intent_id':new_runtime_id('intent'),'world_instance_id':w['world_instance_id'],'timeline_id':w['timeline_id'],'actor_ref':actor,'action_type':t,'parameters':{},'precondition_snapshot':{},'idempotency_key':new_runtime_id('idem'),'created_at':clock_point(c['day'],c['tick']),'status':'SCHEDULED'}
start=time.time(); td=tempfile.TemporaryDirectory(); db=os.path.join(td.name,'social.db')
rt=LivingRuntime(db,master_release_path=MASTER); w=rt.create_world('stage6-extended',60606,ticks_per_day=24); wid=w['world_instance_id']; val=IntentValidator(rt); brain=AgentBrain(rt,val); sm=SocialMemorySystem(rt)
agents=[ent(rt,w,'AGENT',{'needs':{'social':80},'goals':{},'risk_tolerance':50,'marker':0}) for _ in range(220)]
# 1) 1100 persistent memories and recall ranking.
for i,a in enumerate(agents[:110]):
    for j in range(10):
        sm.record_memory(wid,a['entity_runtime_id'],memory_type='OBSERVATION',content={'seq':j},source='SENSORY',subject_ref=agents[(i+1)%110]['entity_runtime_id'],confidence=.5+j*.04,salience=10+j*8,emotional_weight=(-1)**j*j)
    rs=sm.recall_memories(wid,a['entity_runtime_id'],limit=10)
    check(f'memory_rank_{i}',len(rs)==10 and rs[0]['salience']>=rs[-1]['salience'])
check('memory_total_1100',rt.conn.execute('SELECT COUNT(*) c FROM social_memories').fetchone()['c']==1100)
# 2) Knowledge conflicts, independent evidence, verified truth authority.
for i,a in enumerate(agents[:100]):
    target=agents[100+(i%100)]['entity_runtime_id']; key=f'claim.{i}'
    sm.add_claim(wid,a['entity_runtime_id'],claim_key=key,predicate='status',value='A',confidence=.55,source='SENSORY',subject_ref=target)
    sm.add_claim(wid,a['entity_runtime_id'],claim_key=key,predicate='status',value='B',confidence=.50,source='INFERENCE',subject_ref=target)
    check(f'knowledge_contested_{i}',sm.get_knowledge(wid,a['entity_runtime_id'],key)['truth_status']=='CONTESTED')
    sm.verify_claim(wid,a['entity_runtime_id'],claim_key=key,predicate='status',value='A',is_true=True,subject_ref=target)
    k=sm.get_knowledge(wid,a['entity_runtime_id'],key); check(f'knowledge_verified_{i}',k['truth_status']=='VERIFIED_TRUE' and k['current_value']=='A')
# 3) Witness events -> social effects, idempotent replay.
sm.register_effect_policy(wid,{'policy_key':'social.attack','event_type':'ATTACKED','subject_index':1,'relationship_deltas':{'trust':-30,'affinity':-15,'fear':25},'reputation_delta':-20,'reputation_scope_type':'GLOBAL','rumor_effect_factor':.5})
for i in range(80):
    observer=agents[i]['entity_runtime_id']; subject=agents[120+(i%80)]['entity_runtime_id']; rr=rt.apply_action(wid,act(rt,w,agents[219]['entity_runtime_id'],'ATTACKED'),[{'target_ref':subject,'operation':'INCREMENT','field_path':'data.marker','amount':1}]); eid=rr['event_id']
    x=sm.witness_event(wid,observer,eid); check(f'witness_rel_{i}',x['effects']['relationship']['trust']==-30); check(f'witness_rep_{i}',sm.get_reputation(wid,subject)['score']==-20)
    y=sm.witness_event(wid,observer,eid); check(f'witness_idem_{i}',y['idempotent'] is True and sm.get_relationship(wid,observer,subject)['trust']==-30)
# 4) Rumor chains 4 hops; truth never upgraded by hearsay; loop blocked.
for i in range(40):
    chain=agents[i*5:i*5+5]; subject=agents[215]['entity_runtime_id']; c=sm.add_claim(wid,chain[0]['entity_runtime_id'],claim_key=f'rumor.{i}',predicate='dangerous',value=True,confidence=.95,source='SENSORY',subject_ref=subject,metadata={'effect_policy_key':'social.attack','event_type':'ATTACKED'})
    current=c
    confidences=[]
    for h in range(1,5):
        t=sm.transmit_claim(wid,chain[h-1]['entity_runtime_id'],chain[h]['entity_runtime_id'],current['claim_id']); confidences.append(t['resulting_confidence']); current_row=rt.conn.execute('SELECT claim_json FROM knowledge_claims WHERE claim_id=?',(t['listener_claim_id'],)).fetchone(); current=json.loads(current_row['claim_json'])
        check(f'rumor_unknown_{i}_{h}',sm.get_knowledge(wid,chain[h]['entity_runtime_id'],f'rumor.{i}')['truth_status']!='VERIFIED_TRUE')
    check(f'rumor_decay_{i}',all(confidences[j]>confidences[j+1] for j in range(3)),confidences)
    blocked=False
    try: sm.transmit_claim(wid,chain[4]['entity_runtime_id'],chain[0]['entity_runtime_id'],current['claim_id'])
    except ConflictError: blocked=True
    check(f'rumor_loop_block_{i}',blocked)
# 5) Relationship/reputation affect brain via MEMORY projection.
brain.register_behavior(wid,{'behavior_key':'social.approach','intent_type':'SOCIAL','need_key':'social','threshold':1,'target_strategy':'PERCEPTION','need_weight':1,'base_priority':20,'risk_cost':0,'risk_penalty_weight':1,'opportunity_bonus':0,'goal_key':None,'goal_weight':0,'target_kinds':['AGENT'],'target_fact_equals':{'flags.trusted':True},'agent_state_equals':{},'parameters':{}})
brain.register_behavior(wid,{'behavior_key':'social.avoid','intent_type':'SOCIAL','need_key':'social','threshold':1,'target_strategy':'PERCEPTION','need_weight':1,'base_priority':30,'risk_cost':0,'risk_penalty_weight':1,'opportunity_bonus':0,'goal_key':None,'goal_weight':0,'target_kinds':['AGENT'],'target_fact_equals':{'flags.untrusted':True},'agent_state_equals':{},'parameters':{}})
for i in range(50):
    a=agents[i]; target=agents[150+i]
    sm.apply_relationship_delta(wid,a['entity_runtime_id'],target['entity_runtime_id'],{'trust':40},reason='help'); sm.project_social_perception(brain,wid,a['entity_runtime_id'],[target['entity_runtime_id']]); d1=brain.decide(wid,a['entity_runtime_id']); check(f'brain_trusted_{i}',d1['selected']['behavior_key']=='social.approach')
    sm.apply_relationship_delta(wid,a['entity_runtime_id'],target['entity_runtime_id'],{'trust':-100},reason='betrayal'); sm.project_social_perception(brain,wid,a['entity_runtime_id'],[target['entity_runtime_id']]); d2=brain.decide(wid,a['entity_runtime_id']); check(f'brain_untrusted_{i}',d2['selected']['behavior_key']=='social.avoid')
# 6) Protected relationship holder blocks social mutation.
for i in range(30):
    p=ent(rt,w,'AGENT',{'needs':{'social':1},'goals':{},'risk_tolerance':50},protection={'relationship_change':'BLOCKED'})
    blocked=False
    try: sm.apply_relationship_delta(wid,p['entity_runtime_id'],agents[0]['entity_runtime_id'],{'trust':1},reason='x')
    except ValidationError: blocked=True
    check(f'protected_relationship_{i}',blocked)
# 7) Offline rumor boundary.
source=sm.add_claim(wid,agents[0]['entity_runtime_id'],claim_key='offline.rumor',predicate='x',value=True,confidence=.8,source='SENSORY',subject_ref=agents[2]['entity_runtime_id'])
rt.set_simulation_mode(wid,'ROUTINE_OFFLINE'); blocked=False
try: sm.transmit_claim(wid,agents[0]['entity_runtime_id'],agents[1]['entity_runtime_id'],source['claim_id'])
except OfflinePolicyError: blocked=True
check('offline_rumor_blocked',blocked)
check('offline_routine_safe_rumor',sm.transmit_claim(wid,agents[0]['entity_runtime_id'],agents[1]['entity_runtime_id'],source['claim_id'],routine_safe=True)['status']=='ACCEPTED'); rt.set_simulation_mode(wid,'FULL')
# 8) Timeline isolation.
for n in range(6):
    w2=rt.create_world(f'social-iso-{n}',700+n,ticks_per_day=24); s2=SocialMemorySystem(rt); a2=ent(rt,w2,'AGENT',{}); b2=ent(rt,w2,'AGENT',{}); s2.apply_relationship_delta(w2['world_instance_id'],a2['entity_runtime_id'],b2['entity_runtime_id'],{'trust':n+1},reason='iso'); check(f'timeline_isolation_{n}',s2.get_relationship(w2['world_instance_id'],a2['entity_runtime_id'],b2['entity_runtime_id'])['trust']==n+1)
# 9) Component + SQLite integrity before reopen.
check('social_integrity',sm.full_integrity_check(wid)['status']=='PASS',sm.full_integrity_check(wid))
check('runtime_integrity',rt.full_integrity_check(wid)['status']=='PASS')
check('validator_integrity',val.full_integrity_check(wid)['status']=='PASS')
check('brain_integrity',brain.full_integrity_check(wid)['status']=='PASS')
check('sqlite_quick',rt.conn.execute('PRAGMA quick_check').fetchone()[0]=='ok'); check('sqlite_fk',len(rt.conn.execute('PRAGMA foreign_key_check').fetchall())==0)
counts={t:rt.conn.execute(f'SELECT COUNT(*) c FROM {t} WHERE world_instance_id=?',(wid,)).fetchone()['c'] for t in ['social_memories','knowledge_claims','knowledge_current','relationship_events','relationships_current','reputation_events','reputation_current','rumor_transmissions']}
rt.close()
# 10) Reopen/replay.
rt2=LivingRuntime(db,master_release_path=MASTER); sm2=SocialMemorySystem(rt2); check('reopen_social_integrity',sm2.full_integrity_check(wid)['status']=='PASS',sm2.full_integrity_check(wid)); check('reopen_sqlite_integrity',rt2.conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'); rt2.close(); td.cleanup()
report={'record_id':'LIVING-SIM-ETAPA-06-EXTENDED-VALIDATION-V1.0','checks':len(checks),'passed':sum(x['status']=='PASS' for x in checks),'failed':sum(x['status']=='FAIL' for x in checks),'elapsed_seconds':round(time.time()-start,3),'scale':{'agents':220,'memories_seeded':1100,'knowledge_conflict_sets':100,'witness_events':80,'rumor_chains':40,'rumor_hops_each':4,'brain_social_flips':50,'protected_holders':30,'timelines_total':7},'record_counts':counts,'details':checks}; report['status']='PASS' if report['failed']==0 else 'FAIL'; (ROOT/'04_REPORTS'/'EXTENDED_VALIDATION_V1_0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)); print(json.dumps({k:v for k,v in report.items() if k!='details'},ensure_ascii=False,indent=2)); raise SystemExit(0 if report['status']=='PASS' else 1)
