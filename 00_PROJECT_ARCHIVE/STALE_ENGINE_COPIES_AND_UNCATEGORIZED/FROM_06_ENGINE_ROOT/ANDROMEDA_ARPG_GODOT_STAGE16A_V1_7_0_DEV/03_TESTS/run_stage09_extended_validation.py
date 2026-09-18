import json, os, tempfile, sys, hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'01_RUNTIME'))
from living_runtime import LivingRuntime, new_runtime_id, clock_point
from consequence_engine import ConsequenceEngine
from agent_brain import AgentBrain, IntentValidator
from social_memory import SocialMemorySystem
from ecology_brain import EcologySystem
from object_environment import ObjectEnvironmentSystem
from world_orchestrator import WorldSimulationOrchestrator, PHASE_ORDER

MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'; HERB='CRI-001'; HOME='TER-011'; BIOME='BIO-008'
REPORT=Path(__file__).resolve().parents[1]/'04_REPORTS'/'STAGE09_EXTENDED_VALIDATION_V1_0.json'

def make_agent(rt,w,i):
    c=rt.get_clock(w['world_instance_id']);s={'state_id':new_runtime_id('state'),'world_instance_id':w['world_instance_id'],'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{'needs':{'hunger':80,'safety':20},'goals':{'survive':90},'risk_tolerance':50,'location_ref':f'LOC-{i%4}','money':10,'energy':80},'protection':{}}
    return rt.register_entity(w['world_instance_id'],s)

def policy():return {'policy_key':'policy.eat','action_type':'EAT','allowed_sources':['AGENT_BRAIN'],'actor_kinds':['AGENT'],'target_required':False,'target_kinds':[],'offline_policy':'ACTIVE_ONLY','spatial_policy':'NONE','protection_impacts':[],'cooldown_ticks':0,'parameter_schema':{},'resource_requirements':[],'actor_state_equals':{},'target_state_equals':{},'consequence_templates':[{'target':'ACTOR','operation':'DECREMENT','field_path':'data.needs.hunger','amount':10}]}
def behavior():return {'behavior_key':'eat','intent_type':'EAT','need_key':'hunger','threshold':50,'target_strategy':'NONE','need_weight':100,'base_priority':0,'risk_cost':0,'risk_penalty_weight':1,'opportunity_bonus':0,'goal_key':'survive','goal_weight':10,'target_kinds':[],'target_fact_equals':{},'parameters':{}}

def check(cond,name,failures):
    if not cond:failures.append(name)
    return 1

def main():
    checks=0; failures=[];tmp=tempfile.TemporaryDirectory();db=os.path.join(tmp.name,'stage09.db')
    rt=LivingRuntime(db,master_release_path=MASTER);w=rt.create_world('stage09-extended',90909,ticks_per_day=24);wid=w['world_instance_id']
    val=IntentValidator(rt);brain=AgentBrain(rt,val);social=SocialMemorySystem(rt);eco=EcologySystem(rt,val);obj=ObjectEnvironmentSystem(rt);cons=ConsequenceEngine(rt);orch=WorldSimulationOrchestrator(rt,cons,brain,val,social,eco,obj)
    orch.configure_world(wid,{'ticks_per_run':1,'full_npc_budget':16,'active_npc_budget':8,'full_ecology_budget':16,'active_ecology_budget':8,'environment_cadence_ticks':1,'ecology_aggregate_cadence_ticks':4,'integrity_cadence_ticks':12,'extension_budget':4,'max_roots_per_run':64})
    # policy min capacity 16+16+4+4=40
    scopes=[orch.register_scope(wid,HOME,'FULL'),orch.register_scope(wid,'TER-002','ACTIVE'),orch.register_scope(wid,'POI-001','AGGREGATE')]
    val.register_policy(wid,policy());brain.register_behavior(wid,behavior())
    agents=[]
    for i in range(64):
        a=make_agent(rt,w,i);agents.append(a);scope=[HOME,'TER-002','POI-001'][i%3];orch.register_participant(wid,a['entity_runtime_id'],'NPC',scope_ref=scope,priority=i%5,cadence_ticks=1,metadata={'social_targets':[]})
    eco.load_master_fauna_snapshots(MASTER);eco.register_species_profile(wid,{'species_ref':HERB,'diet':'HERBIVORE','social_structure':'HERD','cognition_mode':'ADAPTIVE','activity_mode':'DIURNAL','range_excursion_allowed':False});eco.install_default_action_policies(wid)
    animals=[]
    for i in range(64):
        a=eco.spawn_animal(wid,species_ref=HERB,territory_ref=HOME,biome_ref=BIOME,age_days=60,hunger=10,thirst=10,energy=80,reproduction_drive=0);animals.append(a);scope=[HOME,'TER-002','POI-001'][i%3];orch.register_participant(wid,a['entity_runtime_id'],'ECOLOGY',scope_ref=scope,priority=i%7,cadence_ticks=1)
    eco.register_population(wid,species_ref=HERB,territory_ref=HOME,count=1000,carrying_capacity=2000,resource_index=80,water_index=80,climate_comfort=80)
    for i in range(12):obj.create_environment_zone(wid,canonical_ref='POI-001' if i==0 else None,temperature=20+i%3,humidity=40)
    ext={'economy':0,'faction':0}
    orch.attach_extension(wid,'economy',lambda c:(ext.__setitem__('economy',ext['economy']+1) or {'status':'PASS','tick':c['tick_key']}),version='V0.TEST')
    orch.attach_extension(wid,'faction',lambda c:(ext.__setitem__('faction',ext['faction']+1) or {'status':'PASS'}),version='V0.TEST')
    modes=[('FULL',12),('ACTIVE',12),('AGGREGATE',12),('ROUTINE_OFFLINE',12)]
    counts_by_mode={}
    for mode,n in modes:
        rt.set_simulation_mode(wid,mode);d0=rt.conn.execute('SELECT COUNT(*) c FROM agent_decisions').fetchone()['c'];e0=rt.conn.execute('SELECT COUNT(*) c FROM ecology_decisions').fetchone()['c']
        for _ in range(n):
            before=rt.get_clock(wid);r=orch.run_tick(wid);after=rt.get_clock(wid)
            checks+=check(r['status']=='COMPLETED',f'{mode}:run_status',failures)
            checks+=check([p['phase'] for p in r['phases']]==PHASE_ORDER,f'{mode}:phase_order',failures)
            checks+=check(after['day']*24+after['tick']==before['day']*24+before['tick']+1,f'{mode}:clock',failures)
            checks+=check(r['phase_count']==len(PHASE_ORDER),f'{mode}:phase_count',failures)
            checks+=check(bool(r['config_snapshot_hash']),f'{mode}:config_hash',failures)
            cp=[p for p in r['phases'] if p['phase']=='CONSEQUENCE_DRAIN'][0]['detail']
            checks+=check(cp['pending_after']==0,f'{mode}:causal_backlog',failures)
            for p in r['phases']:
                checks+=check(p['status'] in {'PASS','SKIPPED'},f'{mode}:phase:{p["phase"]}',failures)
        d1=rt.conn.execute('SELECT COUNT(*) c FROM agent_decisions').fetchone()['c'];e1=rt.conn.execute('SELECT COUNT(*) c FROM ecology_decisions').fetchone()['c'];counts_by_mode[mode]={'npc_delta':d1-d0,'ecology_delta':e1-e0}
    checks+=check(counts_by_mode['FULL']['npc_delta']>0,'full npc activity',failures)
    checks+=check(counts_by_mode['FULL']['ecology_delta']>0,'full ecology activity',failures)
    checks+=check(counts_by_mode['ACTIVE']['npc_delta']>0,'active npc activity',failures)
    checks+=check(counts_by_mode['AGGREGATE']['npc_delta']==0,'aggregate npc blocked',failures)
    checks+=check(counts_by_mode['AGGREGATE']['ecology_delta']==0,'aggregate ecology individual blocked',failures)
    checks+=check(counts_by_mode['ROUTINE_OFFLINE']['npc_delta']==0,'offline npc blocked',failures)
    checks+=check(counts_by_mode['ROUTINE_OFFLINE']['ecology_delta']==0,'offline ecology individual blocked',failures)
    checks+=check(rt.conn.execute('SELECT COUNT(*) c FROM orchestration_runs WHERE status="COMPLETED"').fetchone()['c']==48,'48 completed runs',failures)
    checks+=check(rt.conn.execute('SELECT COUNT(*) c FROM orchestration_config_snapshots').fetchone()['c']==48,'48 config snapshots',failures)
    checks+=check(rt.conn.execute('SELECT COUNT(*) c FROM orchestration_phase_log').fetchone()['c']==48*len(PHASE_ORDER),'phase log count',failures)
    checks+=check(orch.verify_run_chain(wid)['status']=='PASS','run chain',failures)
    checks+=check(orch.integrity_guard(wid)['status']=='PASS','final integrity',failures)
    # idempotent historical replay does not move clock
    last=rt.conn.execute('SELECT tick_key FROM orchestration_runs WHERE world_instance_id=? ORDER BY sequence DESC LIMIT 1',(wid,)).fetchone()['tick_key'];clock_before=rt.get_clock(wid);rep=orch.run_tick(wid,tick_key=last);checks+=check(rep.get('idempotent_replay') is True,'idempotent replay flag',failures);checks+=check(rt.get_clock(wid)==clock_before,'idempotent replay clock stable',failures)
    sqlite_integrity=rt.conn.execute('PRAGMA integrity_check').fetchone()[0];fk=len(rt.conn.execute('PRAGMA foreign_key_check').fetchall());checks+=check(sqlite_integrity=='ok','sqlite integrity',failures);checks+=check(fk==0,'foreign keys',failures)
    report={'record_id':'STAGE09-EXTENDED-VALIDATION-V1.0','status':'PASS' if not failures else 'FAIL','checks':checks,'passed':checks-len(failures),'failed':len(failures),'failures':failures,'world':{'runs':48,'participants':128,'scopes':3,'environment_zones':12},'modes':counts_by_mode,'extensions':ext,'events':rt.event_count(wid),'propagation_runs':rt.conn.execute('SELECT COUNT(*) c FROM propagation_runs').fetchone()['c'],'config_snapshots':48,'sqlite_integrity':sqlite_integrity,'foreign_key_failures':fk}
    REPORT.write_text(json.dumps(report,indent=2));rt.close();tmp.cleanup();print(json.dumps(report,indent=2));return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
