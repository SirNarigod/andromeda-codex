import json, os, tempfile, threading, random, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'01_RUNTIME'))
from living_runtime import LivingRuntime, new_runtime_id, clock_point, IntegrityError
from consequence_engine import ConsequenceEngine
from agent_brain import AgentBrain, IntentValidator
from social_memory import SocialMemorySystem
from ecology_brain import EcologySystem
from object_environment import ObjectEnvironmentSystem
from world_orchestrator import WorldSimulationOrchestrator

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'); REPORT=Path(__file__).resolve().parents[1]/'04_REPORTS'/'STAGE09_FUZZ_STRESS_V1_0.json'

def stable_extension(ctx):return {'status':'PASS','mode':ctx['simulation_mode']}

def stack(rt):
    v=IntentValidator(rt);b=AgentBrain(rt,v);s=SocialMemorySystem(rt);e=EcologySystem(rt,v);o=ObjectEnvironmentSystem(rt);c=ConsequenceEngine(rt);orch=WorldSimulationOrchestrator(rt,c,b,v,s,e,o);return v,b,s,e,o,c,orch

def main():
    t0=time.time();tmp=tempfile.TemporaryDirectory();db=os.path.join(tmp.name,'stress.db');fail=[];stats={}
    rt=LivingRuntime(db,master_release_path=MASTER);v,b,s,e,o,c,orch=stack(rt)
    # World A: concurrent same-key idempotency and sequential pressure.
    w=rt.create_world('stress-a',9001,ticks_per_day=24);wid=w['world_instance_id'];orch.configure_world(wid,{'environment_cadence_ticks':10000,'ecology_aggregate_cadence_ticks':10000,'integrity_cadence_ticks':10000,'full_npc_budget':4,'active_npc_budget':2,'full_ecology_budget':4,'active_ecology_budget':2,'extension_budget':2,'max_roots_per_run':32})
    orch.attach_extension(wid,'stable',stable_extension,version='V1.TEST')
    out=[];errs=[]
    def same_worker():
        try:out.append(orch.run_tick(wid,tick_key='shared-key'))
        except Exception as ex:errs.append(repr(ex))
    ts=[threading.Thread(target=same_worker) for _ in range(64)];[x.start() for x in ts];[x.join() for x in ts]
    if errs:fail.append('same_key_errors')
    if len({x['run_id'] for x in out})!=1:fail.append('same_key_duplicate_run')
    if rt.get_clock(wid)['tick']!=1:fail.append('same_key_clock')
    stats['same_key_callers']=64
    # Concurrent unique keys on same world serialize safely.
    errs=[]
    def unique_worker(i):
        try:orch.run_tick(wid,tick_key=f'u-{i:04d}')
        except Exception as ex:errs.append((i,repr(ex)))
    ts=[threading.Thread(target=unique_worker,args=(i,)) for i in range(192)];[x.start() for x in ts];[x.join() for x in ts]
    if errs:fail.append(f'unique_key_errors:{len(errs)}')
    if orch.verify_run_chain(wid)['status']!='PASS':fail.append('world_a_chain')
    stats['unique_concurrent_ticks']=192
    # Multiworld pressure: 8 private/shared-compatible worlds, 64 ticks each.
    worlds=[]
    for i in range(8):
        ww=rt.create_world(f'stress-{i}',9100+i,ticks_per_day=24,mode='SHARED' if i==7 else 'PRIVATE');ow=WorldSimulationOrchestrator(rt,c,b,v,s,e,o);ow.configure_world(ww['world_instance_id'],{'environment_cadence_ticks':10000,'ecology_aggregate_cadence_ticks':10000,'integrity_cadence_ticks':10000,'full_npc_budget':2,'active_npc_budget':1,'full_ecology_budget':2,'active_ecology_budget':1,'extension_budget':1,'max_roots_per_run':16});worlds.append((ww,ow))
    errs=[]
    def world_worker(pair):
        ww,ow=pair
        try:
            for _ in range(64):ow.run_tick(ww['world_instance_id'])
        except Exception as ex:errs.append((ww['world_instance_id'],repr(ex)))
    ts=[threading.Thread(target=world_worker,args=(p,)) for p in worlds];[x.start() for x in ts];[x.join() for x in ts]
    if errs:fail.append(f'multiworld_errors:{len(errs)}')
    for ww,ow in worlds:
        if ow.verify_run_chain(ww['world_instance_id'])['status']!='PASS':fail.append('multiworld_chain')
        if rt.get_clock(ww['world_instance_id'])['day']*24+rt.get_clock(ww['world_instance_id'])['tick']!=64:fail.append('multiworld_clock')
    stats['multiworld_worlds']=8;stats['multiworld_ticks']=512
    # LOD transition fuzz on a fresh empty world.
    wf=rt.create_world('lod-fuzz',9999,ticks_per_day=24);of=WorldSimulationOrchestrator(rt,c,b,v,s,e,o);of.configure_world(wf['world_instance_id'],{'environment_cadence_ticks':10000,'ecology_aggregate_cadence_ticks':10000,'integrity_cadence_ticks':10000,'full_npc_budget':2,'active_npc_budget':1,'full_ecology_budget':2,'active_ecology_budget':1,'extension_budget':1,'max_roots_per_run':16})
    rng=random.Random(909);modes=['FULL','ACTIVE','AGGREGATE','ROUTINE_OFFLINE'];seq=[]
    for i in range(240):
        m=rng.choice(modes);seq.append(m);rt.set_simulation_mode(wf['world_instance_id'],m);of.run_tick(wf['world_instance_id'],tick_key=f'lod-{i}')
    if of.verify_run_chain(wf['world_instance_id'])['status']!='PASS':fail.append('lod_chain')
    stats['lod_fuzz_ticks']=240
    # Restart proof for world A, including extension descriptor rebind.
    pre_clock=rt.get_clock(wid);pre_runs=rt.conn.execute('SELECT COUNT(*) c FROM orchestration_runs WHERE world_instance_id=? AND status="COMPLETED"',(wid,)).fetchone()['c'];rt.close()
    rt2=LivingRuntime(db,master_release_path=MASTER);v2,b2,s2,e2,o2,c2,orch2=stack(rt2)
    if orch2.verify_run_chain(wid)['status']!='PASS':fail.append('restart_chain')
    preflight_runs=rt2.conn.execute('SELECT COUNT(*) c FROM orchestration_runs WHERE world_instance_id=?',(wid,)).fetchone()['c']
    try:
        orch2.run_tick(wid,tick_key='should-not-create-run');fail.append('missing_handler_not_blocked')
    except Exception as ex:
        if ex.__class__.__name__!='ConflictError':fail.append('missing_handler_wrong_exception')
    if rt2.conn.execute('SELECT COUNT(*) c FROM orchestration_runs WHERE world_instance_id=?',(wid,)).fetchone()['c']!=preflight_runs:fail.append('missing_handler_created_run')
    if rt2.get_world(wid)['status']!='ACTIVE':fail.append('missing_handler_changed_world_status')
    orch2.bind_extension_handler(wid,'stable',stable_extension)
    orch2.run_tick(wid,tick_key='after-rebind')
    if orch2.verify_run_chain(wid)['status']!='PASS':fail.append('rebind_chain')
    if rt2.get_clock(wid)['day']*24+rt2.get_clock(wid)['tick'] != pre_clock['day']*24+pre_clock['tick']+1:fail.append('restart_clock')
    # Native DB integrity.
    sqlite_integrity=rt2.conn.execute('PRAGMA integrity_check').fetchone()[0];fk=len(rt2.conn.execute('PRAGMA foreign_key_check').fetchall())
    if sqlite_integrity!='ok':fail.append('sqlite_integrity')
    if fk:fail.append('foreign_keys')
    guard=orch2.integrity_guard(wid)
    if guard['status']!='PASS':fail.append('final_guard')
    stats['world_a_completed_runs']=rt2.conn.execute('SELECT COUNT(*) c FROM orchestration_runs WHERE world_instance_id=? AND status="COMPLETED"',(wid,)).fetchone()['c'];stats['world_a_failed_runs']=rt2.conn.execute('SELECT COUNT(*) c FROM orchestration_runs WHERE world_instance_id=? AND status="FAILED"',(wid,)).fetchone()['c'];stats['total_completed_runs']=rt2.conn.execute('SELECT COUNT(*) c FROM orchestration_runs WHERE status="COMPLETED"').fetchone()['c'];stats['total_phase_logs']=rt2.conn.execute('SELECT COUNT(*) c FROM orchestration_phase_log').fetchone()['c'];stats['seconds']=round(time.time()-t0,2)
    report={'record_id':'STAGE09-FUZZ-STRESS-V1.0','status':'PASS' if not fail else 'FAIL','failures':fail,'stats':stats,'sqlite_integrity':sqlite_integrity,'foreign_key_failures':fk,'restart_guard':guard['status']}
    REPORT.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));rt2.close();tmp.cleanup();return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
