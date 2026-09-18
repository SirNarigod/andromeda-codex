import copy,json,os,tempfile,threading,time,sys,random
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from living_runtime import LivingRuntime,new_runtime_id,clock_point
from social_memory import SocialMemorySystem
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
def ent(rt,w):
 c=rt.get_clock(w['world_instance_id']);s={'state_id':new_runtime_id('state'),'world_instance_id':w['world_instance_id'],'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{}};rt.register_entity(w['world_instance_id'],s);return s
start=time.time();td=tempfile.TemporaryDirectory();db=os.path.join(td.name,'stress.db');rt=LivingRuntime(db,master_release_path=MASTER);w=rt.create_world('stage6-stress',606060,ticks_per_day=24);wid=w['world_instance_id'];sm=SocialMemorySystem(rt);agents=[ent(rt,w) for _ in range(128)];holder=agents[0]['entity_runtime_id'];subject=agents[1]['entity_runtime_id'];fail=[];lock=threading.Lock();threads=16;loops=200

def worker(tid):
 try:
  for i in range(loops):
   sm.apply_relationship_delta(wid,holder,subject,{'trust':0.01},reason='stress')
   sm.apply_reputation_delta(wid,subject,0.01,reason='stress')
   listener=agents[2+((tid*loops+i)%126)]['entity_runtime_id']
   sm.record_memory(wid,listener,memory_type='OBSERVATION',content={'tid':tid,'i':i},source='SENSORY',subject_ref=subject,confidence=.5,salience=25)
   sm.add_claim(wid,listener,claim_key=f'stress.{tid}.{i}',predicate='seen',value=True,confidence=.5,source='SENSORY',subject_ref=subject)
 except Exception as e:
  with lock:fail.append({'thread':tid,'error':type(e).__name__+':'+str(e)})
ts=[threading.Thread(target=worker,args=(t,)) for t in range(threads)];[t.start() for t in ts];[t.join() for t in ts]
# Rumor fuzz: 800 independent claims/transmissions, including varying trust.
rumor_fail=0;rumor_ok=0
speaker=agents[2]['entity_runtime_id']
for i in range(800):
 listener=agents[3+(i%125)]['entity_runtime_id']
 try:
  c=sm.add_claim(wid,speaker,claim_key=f'rumor.stress.{i}',predicate='claim',value={'n':i%7},confidence=.3+(i%7)*.1,source='SENSORY',subject_ref=subject)
  if i%10==0: sm.apply_relationship_delta(wid,listener,speaker,{'trust':5},reason='rumor-trust')
  r=sm.transmit_claim(wid,speaker,listener,c['claim_id']); rumor_ok+=int(r['status'] in {'ACCEPTED','DISMISSED_LOW_CONFIDENCE'})
 except Exception: rumor_fail+=1
rel=sm.get_relationship(wid,holder,subject);rep=sm.get_reputation(wid,subject);social=sm.full_integrity_check(wid);quick=rt.conn.execute('PRAGMA quick_check').fetchone()[0];fk=len(rt.conn.execute('PRAGMA foreign_key_check').fetchall())
counts={t:rt.conn.execute(f'SELECT COUNT(*) c FROM {t} WHERE world_instance_id=?',(wid,)).fetchone()['c'] for t in ['social_memories','knowledge_claims','knowledge_current','relationship_events','reputation_events','rumor_transmissions']}
pre={'relationship_trust':rel['trust'],'reputation_score':rep['score'],'social_integrity':social['status'],'sqlite_quick':quick,'foreign_key_failures':fk,'counts':counts}
rt.close();rt2=LivingRuntime(db,master_release_path=MASTER);sm2=SocialMemorySystem(rt2);post=sm2.full_integrity_check(wid);integrity=rt2.conn.execute('PRAGMA integrity_check').fetchone()[0];rt2.close();td.cleanup()
expected=round(threads*loops*.01,6)
report={'record_id':'LIVING-SIM-ETAPA-06-SOCIAL-FUZZ-STRESS-V1.0','threads':threads,'loops_per_thread':loops,'concurrent_iterations':threads*loops,'concurrent_social_operations':threads*loops*4,'rumor_cases':800,'rumor_ok':rumor_ok,'rumor_failures':rumor_fail,'thread_failures':fail,'expected_shared_delta':expected,'pre_reopen':pre,'post_reopen_social_integrity':post['status'],'post_reopen_sqlite_integrity':integrity,'elapsed_seconds':round(time.time()-start,3)}
report['status']='PASS' if not fail and rumor_fail==0 and abs(rel['trust']-expected)<1e-6 and abs(rep['score']-expected)<1e-6 and social['status']=='PASS' and quick=='ok' and fk==0 and post['status']=='PASS' and integrity=='ok' else 'FAIL';(ROOT/'04_REPORTS'/'SOCIAL_FUZZ_STRESS_V1_0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(0 if report['status']=='PASS' else 1)
