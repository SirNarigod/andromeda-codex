import json, os, sys, tempfile, threading, time, random
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from living_runtime import LivingRuntime, ConflictError, ValidationError
from agent_brain import IntentValidator
from ecology_brain import EcologySystem

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
start=time.time(); failures=[]; lock=threading.Lock()
def fail(x):
    with lock: failures.append(x)

def prof(s,diet,social='HERD',exc=True):return {'species_ref':s,'diet':diet,'social_structure':social,'cognition_mode':'ADAPTIVE','activity_mode':'CATHEMERAL','range_excursion_allowed':exc,'population_growth_rate':.02,'predation_rate':.02}

with tempfile.TemporaryDirectory() as td:
    db=os.path.join(td,'stress.db');rt=LivingRuntime(db,master_release_path=MASTER);w=rt.create_world('eco-stress',70707,ticks_per_day=24);wid=w['world_instance_id'];val=IntentValidator(rt);eco=EcologySystem(rt,val);eco.load_master_fauna_snapshots()
    eco.register_species_profile(wid,prof('CRI-001','HERBIVORE','HERD',False));eco.register_species_profile(wid,prof('CRI-002','CARNIVORE','PACK',True));eco.install_default_action_policies(wid)
    # Shared forage resource: 960 successful 40-unit meals max, with 1,920 contenders.
    resource=eco.create_resource(wid,resource_type='PLANT',quantity=38400,territory_ref='TER-011',biome_ref='BIO-008')
    threads=24;loops=80;successes=rejects=conflicts=errors=0;counter_lock=threading.Lock()
    def forage_worker(seed):
        global successes,rejects,conflicts,errors
        rnd=random.Random(seed)
        for i in range(loops):
            try:
                a=eco.spawn_animal(wid,species_ref='CRI-001',territory_ref='TER-011',biome_ref='BIO-008',age_days=60,hunger=80,energy=80)
                eco.record_observation(wid,a['entity_runtime_id'],[{'kind':'FOOD','target_ref':resource['entity_runtime_id'],'food_value':80+rnd.randint(0,20),'confidence':1}])
                r=eco.execute_decision(eco.decide(wid,a['entity_runtime_id']))
                with counter_lock:
                    if r['status']=='PASS':successes+=1
                    else:rejects+=1
            except ConflictError:
                with counter_lock:conflicts+=1
            except Exception as e:
                with counter_lock:errors+=1
                fail(f'forage:{type(e).__name__}:{e}')
    ts=[threading.Thread(target=forage_worker,args=(i,)) for i in range(threads)];[t.start() for t in ts];[t.join(45) for t in ts]
    alive=sum(t.is_alive() for t in ts)
    if alive:fail(f'forage_threads_alive:{alive}')
    qty=rt.get_entity(wid,resource['entity_runtime_id'])['data']['quantity']
    if qty<0:fail(f'negative_resource:{qty}')
    if successes*40+qty!=38400:fail(f'resource_conservation:successes={successes}:qty={qty}')

    # High-contention population ledger: exactly 6,000 increments expected.
    eco.register_population(wid,species_ref='CRI-001',territory_ref='TER-011',count=100,carrying_capacity=20000)
    pop_threads=24;pop_loops=250;pop_errors=[]
    def pop_worker():
        try:
            for _ in range(pop_loops): eco.apply_population_delta(wid,'CRI-001','TER-011',1,'STRESS_INCREMENT')
        except Exception as e:
            with lock:pop_errors.append(f'{type(e).__name__}:{e}')
    pts=[threading.Thread(target=pop_worker) for _ in range(pop_threads)];[t.start() for t in pts];[t.join(45) for t in pts]
    pop_alive=sum(t.is_alive() for t in pts)
    if pop_alive:fail(f'population_threads_alive:{pop_alive}')
    failures.extend(pop_errors)
    pop=eco.get_population(wid,'CRI-001','TER-011')
    if pop['count']!=100+pop_threads*pop_loops:fail(f'population_lost_update:{pop["count"]}')

    # Predation race: 48 predators observe the same prey; prey can die once only.
    prey=eco.spawn_animal(wid,species_ref='CRI-001',territory_ref='TER-011',biome_ref='BIO-008',age_days=60)
    predators=[];decisions=[]
    for i in range(48):
        p=eco.spawn_animal(wid,species_ref='CRI-002',territory_ref='TER-011',biome_ref='BIO-008',age_days=60,hunger=90,energy=90);predators.append(p)
        eco.record_observation(wid,p['entity_runtime_id'],[{'kind':'PREY','target_ref':prey['entity_runtime_id'],'food_value':100,'confidence':1}]);decisions.append(eco.decide(wid,p['entity_runtime_id']))
    hunt_pass=hunt_reject=hunt_conflicts=hunt_errors=0
    def hunt_worker(d):
        global hunt_pass,hunt_reject,hunt_conflicts,hunt_errors
        try:
            r=eco.execute_decision(d)
            with counter_lock:
                if r['status']=='PASS':hunt_pass+=1
                else:hunt_reject+=1
        except (ConflictError,ValidationError):
            with counter_lock:hunt_conflicts+=1
        except Exception as e:
            with counter_lock:hunt_errors+=1
            fail(f'hunt:{type(e).__name__}:{e}')
    hts=[threading.Thread(target=hunt_worker,args=(d,)) for d in decisions];[t.start() for t in hts];[t.join(30) for t in hts]
    if any(t.is_alive() for t in hts):fail('hunt_threads_alive')
    if rt.get_entity(wid,prey['entity_runtime_id'])['lifecycle']!='DEAD':fail('prey_not_dead')
    if hunt_pass!=1:fail(f'hunt_success_count:{hunt_pass}')

    # Reproduction event idempotency under 64 concurrent materializers.
    pa=eco.spawn_animal(wid,species_ref='CRI-001',territory_ref='TER-011',biome_ref='BIO-008',age_days=60,reproduction_drive=95,energy=90)
    pb=eco.spawn_animal(wid,species_ref='CRI-001',territory_ref='TER-011',biome_ref='BIO-008',age_days=60,reproduction_drive=95,energy=90)
    eco.record_observation(wid,pa['entity_runtime_id'],[{'kind':'MATE','target_ref':pb['entity_runtime_id'],'mate_quality':100,'confidence':1}]);dec=eco.decide(wid,pa['entity_runtime_id']);val.validate_intent(dec['intent_id']);ex=val.execute_validated_intent(dec['intent_id'])
    children=[];birth_errors=[]
    def birth_worker():
        try:
            b=eco._materialize_birth(wid,ex['event_id'],pa['entity_runtime_id'],pb['entity_runtime_id'])
            with lock:children.append(b['child_ref'])
        except Exception as e:
            with lock:birth_errors.append(f'{type(e).__name__}:{e}')
    bts=[threading.Thread(target=birth_worker) for _ in range(64)];[t.start() for t in bts];[t.join(30) for t in bts]
    if any(t.is_alive() for t in bts):fail('birth_threads_alive')
    failures.extend(birth_errors)
    if len(set(children))!=1:fail(f'birth_child_count:{len(set(children))}')
    if rt.conn.execute('SELECT COUNT(*) c FROM ecology_births WHERE reproduction_event_id=?',(ex['event_id'],)).fetchone()['c']!=1:fail('birth_rows_not_one')

    # Fuzz 2,000 ecological observations; invalid ones must reject without corrupting state.
    fuzz_cases=2000;fuzz_rejected=0;fuzz_accepted=0
    observer=eco.spawn_animal(wid,species_ref='CRI-001',territory_ref='TER-011',biome_ref='BIO-008',age_days=60)
    kinds=['FOOD','WATER','PREY','PREDATOR','THREAT','MATE','SHELTER','HABITAT','GROUP','SETTLEMENT','INVALID','LLM_TRUTH']
    rnd=random.Random(707)
    for i in range(fuzz_cases):
        o={'kind':rnd.choice(kinds),'confidence':rnd.uniform(-.5,1.5),'danger':rnd.uniform(-50,150)}
        try:eco.record_observation(wid,observer['entity_runtime_id'],[o]);fuzz_accepted+=1
        except Exception:fuzz_rejected+=1
    # Both paths should be exercised.
    if not fuzz_rejected or not fuzz_accepted:fail(f'fuzz_distribution:{fuzz_accepted}:{fuzz_rejected}')

    integrity_before=eco.full_integrity_check(wid);core_before=rt.full_integrity_check(wid);quick=rt.conn.execute('PRAGMA quick_check').fetchone()[0];fk=len(rt.conn.execute('PRAGMA foreign_key_check').fetchall())
    counts={t:rt.conn.execute(f'SELECT COUNT(*) c FROM {t}').fetchone()['c'] for t in ['ecology_decisions','ecology_births','ecology_population_deltas','ecology_observations','entity_states','events']}
    rt.close()
    rt=LivingRuntime(db,master_release_path=MASTER);val=IntentValidator(rt);eco=EcologySystem(rt,val);integrity_after=eco.full_integrity_check(wid);core_after=rt.full_integrity_check(wid);quick_after=rt.conn.execute('PRAGMA integrity_check').fetchone()[0];fk_after=len(rt.conn.execute('PRAGMA foreign_key_check').fetchall());rt.close()

report={
 'record_id':'LIVING-SIM-ETAPA-07-FUZZ-STRESS-V1.0','status':'PASS' if not failures else 'FAIL','elapsed_seconds':round(time.time()-start,3),
 'threads':threads,'forage_attempts':threads*loops,'forage_successes':successes,'forage_rejections':rejects,'forage_version_conflicts':conflicts,'forage_errors':errors,'remaining_resource':qty,
 'population_threads':pop_threads,'population_delta_ops':pop_threads*pop_loops,'population_final':pop['count'],
 'predation_contenders':48,'predation_successes':hunt_pass,'predation_rejections':hunt_reject,'predation_version_conflicts':hunt_conflicts,'predation_errors':hunt_errors,
 'birth_contenders':64,'unique_children':len(set(children)),'birth_errors':len(birth_errors),
 'observation_fuzz_cases':fuzz_cases,'fuzz_accepted':fuzz_accepted,'fuzz_rejected':fuzz_rejected,
 'integrity_before_reopen':integrity_before['status'],'core_before_reopen':core_before['status'],'sqlite_quick_check':quick,'foreign_key_failures':fk,
 'integrity_after_reopen':integrity_after['status'],'core_after_reopen':core_after['status'],'sqlite_integrity_check_after':quick_after,'foreign_key_failures_after':fk_after,
 'record_counts':counts,'failures':failures[:100]
}
if any(x!='PASS' for x in [report['integrity_before_reopen'],report['core_before_reopen'],report['integrity_after_reopen'],report['core_after_reopen']]) or quick!='ok' or quick_after!='ok' or fk or fk_after:
 report['status']='FAIL'
(ROOT/'04_REPORTS'/'FUZZ_STRESS_V1_0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
if report['status']!='PASS':raise SystemExit(1)
