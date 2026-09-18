import ast, hashlib, json, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'01_RUNTIME';REPORT=ROOT/'04_REPORTS'/'STAGE10_STATIC_AUDIT_V1_0.json';MASTER=Path('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip');STAGE9=Path('/mnt/data/ANDROMEDA_LIVING_SIM_ETAPA_09/01_RUNTIME')
checks=[]
def ck(name,ok,detail=None):checks.append({'name':name,'status':'PASS' if ok else 'FAIL','detail':detail})
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
code=(RUNTIME/'world_systems.py').read_text();tree=ast.parse(code)
imports=[]
for n in ast.walk(tree):
 if isinstance(n,(ast.Import,ast.ImportFrom)):
  if isinstance(n,ast.Import):imports += [a.name for a in n.names]
  else:imports.append(n.module or '')
ck('world_systems_compiles',True)
for bad in ['requests','urllib.request','http.client','socket'] : ck(f'no_network_import_{bad}',not any(x==bad or x.startswith(bad+'.') for x in imports))
ck('no_eval_call',not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='eval' for n in ast.walk(tree)))
ck('no_exec_call',not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='exec' for n in ast.walk(tree)))
ck('no_llm_dependency','LLM' not in code and 'openai' not in code.lower())
ck('master_read_only_snapshot_marker','MASTER_READ_ONLY_SNAPSHOT' in code)
ck('population_runtime_only_marker','NUMERIC_POPULATION_RUNTIME_ONLY_NOT_CANON' in code)
ck('non_sovereignty_marker','influence_not_sovereignty' in code)
ck('offline_migration_frozen','if mode!="ROUTINE_OFFLINE"' in code)
ck('route_capacity_bounded','capacity_factor must be 0..1' in code)
ck('price_clamped','_clamp(float(d["base_price"])' in code)
ck('stock_nonnegative','stock=max(0.0' in code)
ck('population_nonnegative','new_count=max(0' in code)
ck('faction_influence_bounded','influence=_clamp' in code)
ck('master_snapshot_trigger','ws_snapshot_no_update' in code and 'ws_snapshot_no_delete' in code)
ck('tick_log_trigger','ws_tick_no_update' in code and 'ws_tick_no_delete' in code)
ck('extension_rebind_api','bind_to_orchestrator' in code)
ck('extension_routine_safe','routine_safe=True' in code)
ck('primary_route_source','STELLAR_ROUTE_SKELETON_V1_0.json' in code)
ck('secondary_route_source','STELLAR_SECONDARY_ROUTE_REGISTRY_V1_0.json' in code)
ck('economic_flow_source','STELLAR_ECONOMIC_FLOWS_V1_0.json' in code)
ck('population_source','STELLAR_POPULATION_DISTRIBUTION_V1_0.json' in code)
ck('faction_source','STELLAR_FACTION_INFLUENCE_V1_0.json' in code)
ck('master_exists',MASTER.exists())
ck('master_sha256',sha(MASTER)=='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2',sha(MASTER))
# Prove upstream modules unchanged byte-for-byte.
for name in ['living_runtime.py','consequence_engine.py','agent_brain.py','social_memory.py','ecology_brain.py','object_environment.py','world_orchestrator.py']:
 ck(f'upstream_identical_{name}',sha(RUNTIME/name)==sha(STAGE9/name),{'stage10':sha(RUNTIME/name),'stage9':sha(STAGE9/name)})
# Schema/contract checks.
contract=json.loads((ROOT/'02_CONTRACTS'/'SYSTEMIC_ECONOMY_FACTIONS_POPULATION_CONTRACT_V1_0.json').read_text())
ck('contract_runtime_status',contract['status']=='RUNTIME_CONTRACT')
ck('contract_master_readonly',contract['authority']['master']=='READ_ONLY')
ck('contract_population_not_canon',contract['authority']['numeric_population']=='RUNTIME_ONLY_NOT_CANON')
ck('contract_sovereignty_guard',contract['authority']['faction_influence']=='NEVER_IMPLIES_SOVEREIGNTY')
ck('contract_route_counts',contract['master_inputs']['primary_routes']==25 and contract['master_inputs']['secondary_routes']==9)
# No unresolved development markers in new source.
for marker in ['TODO','FIXME','HACK','pass #','NotImplementedError'] : ck(f'no_marker_{marker}',marker not in code)
failed=[x for x in checks if x['status']=='FAIL'];report={'record_id':'STAGE10-STATIC-AUDIT-V1.0','status':'PASS' if not failed else 'FAIL','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'failures':failed}
REPORT.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));raise SystemExit(0 if not failed else 1)
