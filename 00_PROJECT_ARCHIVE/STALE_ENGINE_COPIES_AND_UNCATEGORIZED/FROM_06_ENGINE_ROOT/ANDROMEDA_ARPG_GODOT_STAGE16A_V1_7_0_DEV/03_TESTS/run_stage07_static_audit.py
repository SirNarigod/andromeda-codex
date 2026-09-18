import ast,hashlib,json,re,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; R=ROOT/'01_RUNTIME'
files=[R/'living_runtime.py',R/'consequence_engine.py',R/'agent_brain.py',R/'social_memory.py',R/'ecology_brain.py']
checks=[]
def chk(name,cond,detail=None): checks.append({'check':name,'status':'PASS' if cond else 'FAIL','detail':detail})
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
start=time.time()
for f in files:
    src=f.read_text(encoding='utf-8');tree=ast.parse(src);chk(f'{f.name}:parse',True)
    calls=[n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
    for bad in ['eval','exec','compile']:chk(f'{f.name}:no_{bad}',bad not in calls)
    chk(f'{f.name}:no_network_import',not re.search(r'^\s*(import|from)\s+(socket|requests|urllib|httpx|aiohttp)\b',src,re.M))
    chk(f'{f.name}:no_todo_fixme',not re.search(r'\b(TODO|FIXME)\b',src,re.I))
chk('master_sha256_unchanged',sha('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')=='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2')
chk('parent_checkpoint_stage06',sha('/mnt/data/ANDROMEDA_LIVING_SIM_ETAPA_06/CHECKPOINT_LIVING_SIM_ETAPA_06_V1_0.json')=='81ef5a1cd28f7e6e7938400f7e25495dab1f7bdb4dd5bcdcb6d47727ccb79f76')
s=(R/'ecology_brain.py').read_text(encoding='utf-8')
# Canon/read-only boundary and provenance.
for token in ['MASTER_FAUNA_PATH','MASTER_ENTITY_INDEX_PATH','RUNTIME_SIMULATION_PROFILE_NOT_CANON','RUNTIME_SIMULATION_RELATION_NOT_CANON','fauna snapshots are immutable']:
    chk(f'canon_boundary:{token}',token in s)
chk('sealed_master_hash_rechecked','actual != MASTER_RELEASE_SHA256' in s)
chk('master_fauna_count_validated',"dist.get('count') != len(distributions)" in s)
chk('canonical_distribution_resolves',"fauna distribution unresolved" in s)
chk('habitat_territory_validation','_validate_territory_ref' in s and 'canonical_ref_resolves' in s)
chk('habitat_biome_validation','_validate_biome_ref' in s)
# Specialized cognition/decision boundary.
for action in ['ECO_FORAGE','ECO_DRINK','ECO_REST','ECO_FLEE','ECO_MIGRATE','ECO_HUNT','ECO_REPRODUCE','ECO_PATROL']:
    chk(f'action_policy:{action}',action in s)
chk('animal_decisions_offline_blocked','animal autonomous decisions are disabled offline' in s)
chk('aggregate_routine_offline_allowed','routine_safe' in s and 'cross_territory_migration' in s)
chk('extraordinary_migration_offline_block','extraordinary population migration blocked offline' in s)
chk('bounded_offline_migration_cap','offline routine migration exceeds bounded cap' in s)
chk('death_protection_hunt','protection_impacts' in s and "'DEATH'" in s)
chk('reproduction_pair_same_species','reproduction species mismatch' in s)
chk('reproduction_pair_colocated','reproduction pair not co-located' in s)
chk('birth_idempotency_unique_event','reproduction_event_id TEXT NOT NULL UNIQUE' in s)
chk('birth_lock_hardening','Hold Runtime\'s authoritative DB lock' in s)
# Biological bounds/transacted resource guards.
for field in ['data.ecology.hunger','data.ecology.thirst','data.ecology.energy','data.quantity']:
    chk(f'biological_guard:{field}',field in s)
chk('needs_bounds_validation',all(k in s for k in ["_num(eco.get(k),k,0,100)","reproduction_drive","threat_pressure"]))
chk('population_nonnegative_schema','count INTEGER NOT NULL CHECK(count>=0)' in s)
chk('population_negative_runtime_guard','population cannot become negative' in s)
chk('population_replay_integrity','POP_REPLAY_MISMATCH' in s and 'POP_REPLAY_CHAIN' in s)
# Territorial memory and groups.
for token in ['territory_memories_no_update','territory_memories_no_delete','ecology_observations_no_update','ecology_observations_no_delete']:
    chk(f'append_only:{token}',token in s)
for token in ['animal_groups','animal_group_members','group_leader','max_group_size','group species mismatch']:
    chk(f'groups:{token}',token in s)
# Food web/population routines.
for token in ['food_web_links','predator diet incompatible','predation_rate','ROUTINE_ECOLOGY_TICK','ecology_routine_ticks']:
    chk(f'population:{token}',token in s)
chk('routine_idempotency_unique','UNIQUE(world_instance_id,tick_key)' in s)
chk('routine_change_cap','routine_population_change_cap_fraction' in s)
chk('routine_no_cross_territory','cross_territory_migration' in s)
# Fail-closed integrity.
chk('integrity_guard_corrupt_blocked',"UPDATE worlds SET status='CORRUPT_BLOCKED'" in s)
for table in ['ecology_species_profiles','ecology_observations','territory_memories','animal_groups','animal_group_members','ecology_decisions','ecology_births','ecology_populations_current','ecology_population_deltas','food_web_links','ecology_routine_ticks']:
    chk(f'integrity_table:{table}',f"'{table}'" in s)
# No direct canon mutation APIs/namespace fabrication markers.
for bad in ['CANON_WRITE','MASTER_WRITE','PER-NEW','FAD-NEW','CRI-NEW','FPN-NEW']:
    chk(f'no_{bad.lower()}',bad not in s)
# Reports already generated must pass.
for name in ['UNIT_TEST_REPORT_V1_0.json','STAGE06_EXTENDED_REGRESSION_V1_0.json','STAGE06_SOCIAL_FUZZ_REGRESSION_V1_0.json','EXTENDED_VALIDATION_V1_0.json','FUZZ_STRESS_V1_0.json']:
    p=ROOT/'04_REPORTS'/name;ok=p.exists();detail=None
    if ok:
        try:d=json.loads(p.read_text());ok=d.get('status')=='PASS';detail=d.get('status')
        except Exception as e:ok=False;detail=str(e)
    chk(f'report:{name}',ok,detail)
report={'record_id':'LIVING-SIM-ETAPA-07-STATIC-AUDIT-V1.0','checks':len(checks),'passed':sum(x['status']=='PASS' for x in checks),'failed':sum(x['status']=='FAIL' for x in checks),'elapsed_seconds':round(time.time()-start,3),'details':checks};report['status']='PASS' if report['failed']==0 else 'FAIL'
(ROOT/'04_REPORTS'/'STATIC_AUDIT_V1_0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='details'},ensure_ascii=False,indent=2));sys.exit(0 if report['status']=='PASS' else 1)
