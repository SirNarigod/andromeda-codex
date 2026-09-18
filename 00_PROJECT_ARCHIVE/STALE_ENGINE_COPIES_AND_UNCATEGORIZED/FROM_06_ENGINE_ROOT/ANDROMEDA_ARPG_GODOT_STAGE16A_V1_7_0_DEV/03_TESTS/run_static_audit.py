import ast,hashlib,json,re,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
R=ROOT/'01_RUNTIME'; files=[R/'living_runtime.py',R/'consequence_engine.py',R/'agent_brain.py',R/'social_memory.py']
checks=[]
def chk(name,cond,detail=None): checks.append({'check':name,'status':'PASS' if cond else 'FAIL','detail':detail})
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
start=time.time()
# Syntax/AST and dangerous calls.
for f in files:
    src=f.read_text(encoding='utf-8'); tree=ast.parse(src)
    chk(f'{f.name}:parse',True)
    calls=[n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
    chk(f'{f.name}:no_eval','eval' not in calls)
    chk(f'{f.name}:no_exec','exec' not in calls)
    chk(f'{f.name}:no_compile_dynamic','compile' not in calls)
    chk(f'{f.name}:no_socket_import',not re.search(r'^\s*(import|from)\s+(socket|requests|urllib|httpx|aiohttp)\b',src,re.M))
    chk(f'{f.name}:no_todo_fixme',not re.search(r'\b(TODO|FIXME)\b',src,re.I))
# Baseline and parent chain.
chk('master_sha256_unchanged',sha('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')=='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2')
chk('parent_checkpoint_sha256',sha('/mnt/data/ANDROMEDA_LIVING_SIM_ETAPA_05/CHECKPOINT_LIVING_SIM_ETAPA_05_V1_0.json')=='6c162e1414ea05a3018d52c7e20016204b2b00d1ed61442fe814930a8de84790')
s=(R/'social_memory.py').read_text(encoding='utf-8')
# Authority boundary.
chk('rumor_never_verified_by_communication','non-authoritative source cannot verify world truth' in s)
chk('verified_sources_restricted','{"DIRECT_EVENT", "SYSTEM_VERIFICATION"}' in s)
chk('world_truth_runtime_owned','World truth remains owned by LivingRuntime' in s)
chk('offline_rumor_default_block','rumor transmission is blocked offline' in s)
chk('rumor_hop_limit','MAX_RUMOR_HOPS = 4' in s)
chk('rumor_cycle_guard','rumor provenance cycle blocked' in s)
chk('rumor_per_hop_decay','*trust_factor*0.85' in s)
chk('direct_event_memory_idempotent','idx_social_memory_event_once' in s and 'event memory claim missing or corrupt' in s)
# Append-only evidence triggers.
for token in ['memories_no_update','memories_no_delete','claims_no_update','claims_no_delete','rel_events_no_update','rel_events_no_delete','rep_events_no_update','rep_events_no_delete','rumor_no_update','rumor_no_delete']:
    chk(f'trigger:{token}',token in s)
# Materialized views and replay.
for token in ['knowledge_current','relationships_current','reputation_current','_replay_relationship_pair','_replay_reputation','KNOWLEDGE_REPLAY_MISMATCH','REL_REPLAY_MISMATCH','REP_REPLAY_MISMATCH']:
    chk(f'materialized:{token}',token in s)
# Relationship/reputation constraints.
for dim in ['trust','affinity','fear','respect','obligation']: chk(f'rel_dimension:{dim}',f'"{dim}"' in s)
for scope in ['GLOBAL','FACTION','SETTLEMENT','PROFESSION','REGION','INSTITUTION']: chk(f'reputation_scope:{scope}',f'"{scope}"' in s)
chk('fear_floor_zero','0 if k=="fear" else -100' in s)
chk('relationship_protection','relationship change blocked by narrative protection' in s)
chk('relationship_idempotency','witness-rel:' in s and 'idempotency_key' in s)
chk('reputation_idempotency','witness-rep:' in s and 'idempotency_key' in s)
# Brain integration must go through MEMORY perception, not direct state mutation.
chk('brain_projection_memory_source','source="MEMORY"' in s)
chk('brain_projection_no_apply_action','apply_action(' not in s[s.find('def project_social_perception'):s.find('# ---------- replay / integrity ----------')])
# No canonical namespace creation strings.
for bad in ['PER-NEW','FAC-NEW','CANON_WRITE','MASTER_WRITE']:
    chk(f'no_{bad.lower()}',bad not in s)
# Unit/extended/stress reports already PASS.
for name in ['UNIT_TEST_REPORT_V1_0.json','EXTENDED_VALIDATION_V1_0.json','SOCIAL_FUZZ_STRESS_V1_0.json','STAGE05_EXTENDED_REGRESSION_V1_0.json']:
    p=ROOT/'04_REPORTS'/name; ok=p.exists()
    detail=None
    if ok:
        try: d=json.loads(p.read_text()); ok=d.get('status')=='PASS'; detail=d.get('status')
        except Exception as e: ok=False; detail=str(e)
    chk(f'report:{name}',ok,detail)
# Source code compiles and schema markers exist.
chk('schema_version', 'SCHEMA_VERSION = 1' in s)
chk('social_schema_meta', 'social_memory_schema_version' in s)
chk('integrity_guard_fail_closed', "UPDATE worlds SET status='CORRUPT_BLOCKED'" in s)
report={'record_id':'LIVING-SIM-ETAPA-06-STATIC-AUDIT-V1.0','checks':len(checks),'passed':sum(c['status']=='PASS' for c in checks),'failed':sum(c['status']=='FAIL' for c in checks),'elapsed_seconds':round(time.time()-start,3),'details':checks};report['status']='PASS' if report['failed']==0 else 'FAIL';(ROOT/'04_REPORTS'/'STATIC_AUDIT_V1_0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='details'},ensure_ascii=False,indent=2));sys.exit(0 if report['status']=='PASS' else 1)
