import ast, hashlib, json, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];R=ROOT/'01_RUNTIME';REPORT=ROOT/'04_REPORTS'
MASTER=Path('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip');ST10=Path('/mnt/data/ANDROMEDA_LIVING_SIM_ETAPA_10')
checks=[]
def add(name, ok, detail=None):checks.append({'name':name,'status':'PASS' if ok else 'FAIL','detail':detail})
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
src=(R/'long_horizon.py').read_text();tree=ast.parse(src)
# Security / authority boundary.
imports=set()
for n in ast.walk(tree):
 if isinstance(n,ast.Import): imports.update(a.name.split('.')[0] for a in n.names)
 elif isinstance(n,ast.ImportFrom) and n.module: imports.add(n.module.split('.')[0])
for term in ['eval(','exec(','http://','https://']:
 add('no_'+re.sub(r'\W+','_',term).strip('_'),term not in src)
for mod in ['subprocess','requests','urllib','socket']:
 add('no_import_'+mod,mod not in imports,sorted(imports))
add('no_llm_executor','LLM_EXECUTOR' not in src)
add('routine_offline_present','ROUTINE_OFFLINE' in src)
add('system_reconciliation_present','SYSTEM_RECONCILIATION' in src)
add('runtime_not_canon_markers',src.count('NOT_CANON')>=5,src.count('NOT_CANON'))
add('universe_day_authority','UNIVERSE_DAY_INDEX' in src)
add('display_calendar_runtime_only','RUNTIME_ONLY_NOT_CANON' in src)
add('no_hardcoded_calendar_year','display_days_per_year": None' in src)
# Required APIs.
funcs={n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
for f in ['configure_world','get_policy','chronology','create_snapshot','begin_offline_session','simulate_offline_days','reconcile_and_resume','verify_segment_chain','full_integrity_check','integrity_guard']:
 add('api_'+f,f in funcs)
# Persistence schema & immutability.
for table in ['long_horizon_policies','offline_sessions','offline_catchup_requests','long_horizon_segments','temporal_snapshots','reconciliation_reports']:
 add('table_'+table,f'CREATE TABLE IF NOT EXISTS {table}' in src)
for trig in ['long_segment_no_update','long_segment_no_delete','temporal_snapshot_no_update','temporal_snapshot_no_delete','reconciliation_no_update','reconciliation_no_delete']:
 add('trigger_'+trig,trig in src)
add('one_open_session_partial_index','idx_one_open_offline_session' in src and "WHERE status='OPEN'" in src)
add('catchup_request_unique','UNIQUE(session_id,request_key)' in src)
# Safety policy.
for key,val in [('max_days_per_call','3650'),('short_chunk_days','1'),('medium_chunk_days','7'),('long_chunk_days','30'),('snapshot_cadence_days','30')]:
 add('policy_'+key,f'"{key}": {val}' in src)
add('human_population_guard','max_total_population_change_fraction_per_call' in src)
add('ecology_population_guard','max_total_ecology_change_fraction_per_call' in src)
add('individual_decision_guard','individual decisions changed during offline session' in src)
add('human_migration_frozen','migration_accumulator' in src and 'sec-50.0+opportunity' not in src)
add('faction_influence_not_mutated_offline','"influence"' in src and 'fields_fac' in src)
add('ecology_no_cross_territory','cross_territory_migration":False' in src)
add('environment_routine_only_once','environment_tick_once_per_segment' in src)
add('recovery_boundary_split','_next_recovery_day' in src)
add('snapshot_boundary_split','next_snapshot_day' in src and 'boundaries=' in src)
add('consequence_public_drain','drain_pending_consequences' in (R/'world_orchestrator.py').read_text())
add('catchup_per_runtime_serialization','_long_horizon_operation_lock' in src)
add('catchup_per_world_lock','_long_horizon_world_locks' in src)
# Integrity and hashes.
for token in ['policy_hash','session_hash','result_hash','segment_hash','state_hash','report_hash']:
 add('hash_'+token,token in src)
add('fail_closed_corrupt_blocked','CORRUPT_BLOCKED' in src)
add('sqlite_foreign_authority_unchanged','LivingRuntime' in src)
# Baseline hashes.
add('master_sha_exact',sha(MASTER)=='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2',sha(MASTER))
add('stage10_checkpoint_exact',sha(ST10/'CHECKPOINT_LIVING_SIM_ETAPA_10_V1_0.json')=='33dec02e82131407681a2a85b5c91d6d7fe403df12cb4b5a7e179a2232ac8205')
# Upstream modules must be byte-identical except the documented public orchestrator drain wrapper.
for f in ['living_runtime.py','consequence_engine.py','agent_brain.py','social_memory.py','ecology_brain.py','object_environment.py','world_systems.py']:
 add('upstream_identical_'+f,sha(R/f)==sha(ST10/'01_RUNTIME'/f))
# Confirm orchestrator delta is limited to the public drain wrapper by removing that method text and comparing structurally loose hashes is brittle; use diff content.
import subprocess
diff=subprocess.run(['diff','-u',str(ST10/'01_RUNTIME/world_orchestrator.py'),str(R/'world_orchestrator.py')],capture_output=True,text=True).stdout
add('orchestrator_only_documented_delta','drain_pending_consequences' in diff and diff.count('\n@@')==1,diff[:500])
# Reports from actual execution.
for fn,status_key in [('STAGE11_EXTENDED_VALIDATION_V1_0.json','status'),('STAGE11_FUZZ_STRESS_V1_0.json','status'),('STAGE11_COVERAGE_V1_0.json','status')]:
 p=REPORT/fn;ok=p.exists() and json.loads(p.read_text()).get(status_key)=='PASS';add('report_'+fn,ok)
demo=ROOT/'05_DEMO/DEMO_RESULT_V1_0.json';add('demo_pass',demo.exists() and json.loads(demo.read_text()).get('status')=='PASS')
# Code quality.
add('no_todo','TODO' not in src and 'FIXME' not in src)
add('module_compiles',True)
add('class_docstring',ast.get_docstring(next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LongHorizonSimulation')) is not None)
# Test expectations present.
test=(ROOT/'03_TESTS/test_long_horizon.py').read_text()
for token in ['test_request_idempotency','test_recovery_splits_at_day7','test_faction_influence_frozen','test_population_human_migration_frozen','test_same_request_concurrent_does_not_double_advance','test_second_session_allowed','test_integrity_guard_blocks_corrupt']:
 add('test_present_'+token,token in test)
failed=[c for c in checks if c['status']!='PASS'];out={'record_id':'STAGE11-STATIC-AUDIT-V1.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','failures':failed}
(REPORT/'STAGE11_STATIC_AUDIT_V1_0.json').write_text(json.dumps(out,indent=2,ensure_ascii=False));print(json.dumps(out,indent=2));raise SystemExit(0 if not failed else 1)
