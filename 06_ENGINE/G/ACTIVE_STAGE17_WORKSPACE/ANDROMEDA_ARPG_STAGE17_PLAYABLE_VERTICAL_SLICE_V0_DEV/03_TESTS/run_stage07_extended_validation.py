import json, os, sys, tempfile, time, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from living_runtime import LivingRuntime
from agent_brain import IntentValidator
from ecology_brain import EcologySystem, MASTER_FAUNA_PATH

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
start=time.time(); checks=passed=0; failures=[]
def ck(cond,label):
    global checks,passed
    checks+=1
    if cond: passed+=1
    else: failures.append(label)
def run():
    global checks,passed
    with tempfile.TemporaryDirectory() as td:
        db=os.path.join(td,'eco_extended.db')
        rt=LivingRuntime(db,master_release_path=MASTER); w=rt.create_world('eco-extended',7007,ticks_per_day=24); wid=w['world_instance_id']
        val=IntentValidator(rt); eco=EcologySystem(rt,val); load=eco.load_master_fauna_snapshots(); ck(load['total']==64,'fauna_count_64')
        with zipfile.ZipFile(MASTER) as zf: dist=json.loads(zf.read(MASTER_FAUNA_PATH))['distributions']
        species=[]
        for i,d in enumerate(dist):
            s=d['entity_id']; species.append(s)
            diet='CARNIVORE' if i%4==0 else ('OMNIVORE' if i%4==1 else 'HERBIVORE')
            social='PACK' if i%3==0 else ('HERD' if i%3==1 else 'SOLITARY')
            p=eco.register_species_profile(wid,{'species_ref':s,'diet':diet,'social_structure':social,'cognition_mode':'ADAPTIVE','activity_mode':'CATHEMERAL','range_excursion_allowed':True,'population_growth_rate':0.02+(i%3)*0.005,'predation_rate':0.01+(i%2)*0.01})
            ck(p['authority']=='RUNTIME_SIMULATION_PROFILE_NOT_CANON',f'profile_authority:{s}')
            terr=d['distribution_primary']['territory_id']; bios=d['distribution_primary'].get('biome_ids') or d.get('biome_ids') or []
            biome=bios[0] if bios else None
            ck(eco.habitat_allows(s,terr,biome),f'habitat:{s}')
        pol=eco.install_default_action_policies(wid); ck(len(pol['installed'])==8,'policies_8')
        # Four individuals per canonical species.
        animals=[]
        for i,d in enumerate(dist):
            terr=d['distribution_primary']['territory_id']; bios=d['distribution_primary'].get('biome_ids') or d.get('biome_ids') or []; biome=bios[0] if bios else None
            for j in range(4):
                a=eco.spawn_animal(wid,species_ref=d['entity_id'],territory_ref=terr,biome_ref=biome,age_days=60,hunger=20+j*10,thirst=20,energy=80,reproduction_drive=0)
                animals.append(a); ck(a['lifecycle']=='ACTIVE',f'spawn:{d["entity_id"]}:{j}')
                m=eco.remember_territory(wid,a['entity_runtime_id'],terr,food_score=60+j,water_score=70,danger_score=10,success_score=75)
                ck(m['territory_ref']==terr,f'memory:{d["entity_id"]}:{j}')
        # Group hierarchy for social species.
        group_count=0
        for i,d in enumerate(dist):
            prof=eco.get_species_profile(wid,d['entity_id'])
            if prof['social_structure']=='SOLITARY': continue
            terr=d['distribution_primary']['territory_id']; g=eco.create_group(wid,species_ref=d['entity_id'],group_type=prof['social_structure'],territory_ref=terr); group_count+=1
            members=[a for a in animals if a['data']['species_ref']==d['entity_id']][:3]
            for j,a in enumerate(members): eco.add_group_member(g['group_id'],a['entity_runtime_id'],role='LEADER' if j==0 else 'MEMBER',rank_score=20+j*30)
            leader=eco.group_leader(g['group_id']); ck(leader['animal_ref']==members[0]['entity_runtime_id'],f'leader:{d["entity_id"]}')
        # Aggregate populations for all 64 canonical fauna distributions.
        for i,d in enumerate(dist):
            terr=d['distribution_primary']['territory_id']; p=eco.register_population(wid,species_ref=d['entity_id'],territory_ref=terr,count=80+(i%20),carrying_capacity=200)
            ck(p['count']>=80,f'population:{d["entity_id"]}')
        # Food web links where test runtime profiles designate predators, choosing prey in same territory when possible.
        byterr={}
        for d in dist: byterr.setdefault(d['distribution_primary']['territory_id'],[]).append(d['entity_id'])
        food_links=0
        for terr,ss in byterr.items():
            preds=[s for s in ss if eco.get_species_profile(wid,s)['diet'] in {'CARNIVORE','OMNIVORE','INSECTIVORE'}]
            preys=[s for s in ss if eco.get_species_profile(wid,s)['diet']=='HERBIVORE']
            if preds and preys:
                try:
                    eco.register_food_web_link(wid,predator_species_ref=preds[0],prey_species_ref=preys[0],preference=.8,efficiency=.6);food_links+=1;ck(True,f'foodweb:{terr}')
                except Exception as e: ck(False,f'foodweb:{terr}:{e}')
        # 20 aggregate routine ticks, checking all populations remain non-negative/bounded structurally.
        for tick in range(20):
            r=eco.simulate_population_routine(wid,routine_key=f'ext-{tick}'); ck(r['status']=='PASS',f'routine:{tick}')
            for d in dist:
                p=eco.get_population(wid,d['entity_id'],d['distribution_primary']['territory_id']); ck(p['count']>=0,f'nonnegative:{tick}:{d["entity_id"]}')
        # Individual foraging cycles.
        for i in range(120):
            a=eco.spawn_animal(wid,species_ref='CRI-001',territory_ref='TER-011',biome_ref='BIO-008',age_days=60,hunger=80,energy=80)
            food=eco.create_resource(wid,resource_type='PLANT',quantity=40,territory_ref='TER-011',biome_ref='BIO-008')
            eco.record_observation(wid,a['entity_runtime_id'],[{'kind':'FOOD','target_ref':food['entity_runtime_id'],'food_value':100,'confidence':1}])
            d=eco.decide(wid,a['entity_runtime_id']); x=eco.execute_decision(d); ck(x['status']=='PASS',f'forage:{i}'); ck(rt.get_entity(wid,food['entity_runtime_id'])['data']['quantity']==0,f'forage_resource:{i}')
        # Predation cycles.
        for i in range(60):
            pred=eco.spawn_animal(wid,species_ref='CRI-002',territory_ref='TER-011',biome_ref='BIO-008',age_days=60,hunger=90,energy=90)
            prey=eco.spawn_animal(wid,species_ref='CRI-001',territory_ref='TER-011',biome_ref='BIO-008',age_days=60)
            eco.record_observation(wid,pred['entity_runtime_id'],[{'kind':'PREY','target_ref':prey['entity_runtime_id'],'food_value':100,'confidence':1}])
            x=eco.execute_decision(eco.decide(wid,pred['entity_runtime_id'])); ck(x['status']=='PASS',f'hunt:{i}'); ck(rt.get_entity(wid,prey['entity_runtime_id'])['lifecycle']=='DEAD',f'prey_dead:{i}')
        # Reproduction cycles, verifying runtime-born descendants.
        for i in range(50):
            a=eco.spawn_animal(wid,species_ref='CRI-001',territory_ref='TER-011',biome_ref='BIO-008',age_days=60,reproduction_drive=95,energy=90)
            b=eco.spawn_animal(wid,species_ref='CRI-001',territory_ref='TER-011',biome_ref='BIO-008',age_days=60,reproduction_drive=95,energy=90)
            eco.record_observation(wid,a['entity_runtime_id'],[{'kind':'MATE','target_ref':b['entity_runtime_id'],'mate_quality':100,'confidence':1}])
            x=eco.execute_decision(eco.decide(wid,a['entity_runtime_id'])); child=rt.get_entity(wid,x['birth']['child_ref']); ck(child['origin']=='RUNTIME_BORN',f'birth_origin:{i}'); ck(len(child['data']['parent_refs'])==2,f'birth_parents:{i}')
        # Migration for range-excursion runtime profile. Destination is still a valid canonical territory.
        for i in range(50):
            a=eco.spawn_animal(wid,species_ref='CRI-002',territory_ref='TER-011',biome_ref='BIO-008',age_days=60,energy=90)
            eco.record_observation(wid,a['entity_runtime_id'],[{'kind':'HABITAT','territory_ref':'TER-002','biome_ref':'BIO-005','resource_pressure':95,'food_value':95,'water_value':90,'climate_comfort':90,'danger':0,'confidence':1}])
            x=eco.execute_decision(eco.decide(wid,a['entity_runtime_id'])); ck(x['status']=='PASS',f'migrate:{i}'); ck(rt.get_entity(wid,a['entity_runtime_id'])['data']['ecology']['territory_ref']=='TER-002',f'migrate_state:{i}')
        # Protected prey always survives.
        for i in range(30):
            pred=eco.spawn_animal(wid,species_ref='CRI-002',territory_ref='TER-011',biome_ref='BIO-008',age_days=60,hunger=90,energy=90)
            prey=eco.spawn_animal(wid,species_ref='CRI-001',territory_ref='TER-011',biome_ref='BIO-008',age_days=60,protection={'death':'BLOCKED'})
            eco.record_observation(wid,pred['entity_runtime_id'],[{'kind':'PREY','target_ref':prey['entity_runtime_id'],'food_value':100,'confidence':1}])
            x=eco.execute_decision(eco.decide(wid,pred['entity_runtime_id'])); ck(x['status']=='REJECTED',f'protected_reject:{i}'); ck(rt.get_entity(wid,prey['entity_runtime_id'])['lifecycle']=='ACTIVE',f'protected_alive:{i}')
        # Offline: autonomous decisions blocked, bounded aggregate routine allowed.
        test_animal=animals[0]; rt.set_simulation_mode(wid,'ROUTINE_OFFLINE')
        try: eco.decide(wid,test_animal['entity_runtime_id']); ck(False,'offline_decision_should_block')
        except Exception as e: ck(type(e).__name__=='OfflinePolicyError','offline_decision_block')
        off=eco.simulate_population_routine(wid,routine_key='offline-bounded'); ck(off['routine_safe'] is True and off['cross_territory_migration'] is False,'offline_bounded_routine')
        rt.set_simulation_mode(wid,'FULL')
        integ=eco.full_integrity_check(wid); ck(integ['status']=='PASS','ecology_integrity')
        core=rt.full_integrity_check(wid); ck(core['status']=='PASS','core_integrity')
        q=rt.conn.execute('PRAGMA quick_check').fetchone()[0]; ck(q=='ok','sqlite_quick_check')
        fk=rt.conn.execute('PRAGMA foreign_key_check').fetchall(); ck(len(fk)==0,'sqlite_foreign_key_check')
        counts={t:rt.conn.execute(f'SELECT COUNT(*) c FROM {t}').fetchone()['c'] for t in ['fauna_snapshots','ecology_species_profiles','ecology_observations','territory_memories','animal_groups','animal_group_members','ecology_decisions','ecology_births','ecology_populations_current','ecology_population_deltas','food_web_links','ecology_routine_ticks']}
        rt.close()
        # Reopen and prove persistence/integrity.
        rt=LivingRuntime(db,master_release_path=MASTER); val=IntentValidator(rt); eco=EcologySystem(rt,val); ck(eco.full_integrity_check(wid)['status']=='PASS','reopen_ecology_integrity'); ck(rt.full_integrity_check(wid)['status']=='PASS','reopen_core_integrity'); rt.close()
        return {'species_profiles':64,'individuals_seeded':len(animals),'groups':group_count,'food_web_links':food_links,'routine_ticks':21,'forage_cycles':120,'predation_cycles':60,'reproduction_cycles':50,'migration_cycles':50,'protected_predation_cases':30,'record_counts':counts}
scale=run()
report={'record_id':'LIVING-SIM-ETAPA-07-EXTENDED-VALIDATION-V1.0','checks':checks,'passed':passed,'failed':checks-passed,'elapsed_seconds':round(time.time()-start,3),'scale':scale,'failures':failures[:100]}
report['status']='PASS' if not failures else 'FAIL'
(ROOT/'04_REPORTS'/'EXTENDED_VALIDATION_V1_0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
if report['status']!='PASS': raise SystemExit(1)
