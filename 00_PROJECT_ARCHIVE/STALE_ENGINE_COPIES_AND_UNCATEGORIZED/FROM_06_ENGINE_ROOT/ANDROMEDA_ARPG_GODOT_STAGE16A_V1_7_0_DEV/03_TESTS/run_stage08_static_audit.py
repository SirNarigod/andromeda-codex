import ast,json,re,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];src=ROOT/'01_RUNTIME'/'object_environment.py';text=src.read_text();tree=ast.parse(text)
checks=[]
def add(label,ok,detail=None):checks.append({'check':label,'status':'PASS' if ok else 'FAIL',**({'detail':detail} if detail else {})})
# Structural/class/method checks
classes={n.name:n for n in tree.body if isinstance(n,ast.ClassDef)};add('ObjectEnvironmentSystem exists','ObjectEnvironmentSystem' in classes)
methods={n.name for n in classes['ObjectEnvironmentSystem'].body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
for m in ['register_profile','spawn_object','create_environment_zone','link','interact','update_environment','simulate_environment_tick','propagate_fire','full_integrity_check','get_profile']:
 add(f'method:{m}',m in methods)
# Forbidden capabilities and boundaries
for token in ['eval(','exec(','requests.','urllib','socket.','subprocess','AgentBrain','SocialMemorySystem']:
 add(f'forbidden_absent:{token}',token not in text)
executable_names={getattr(n,'id','') for n in ast.walk(tree) if isinstance(n,ast.Name)} | {getattr(n,'attr','') for n in ast.walk(tree) if isinstance(n,ast.Attribute)}
add('forbidden_executable_absent:LLM',not any('LLM' in x.upper() for x in executable_names))
for required in ['RUNTIME_REACTIVE_PROFILE_NOT_CANON','RUNTIME_SPATIAL_REACTION_LINK_NOT_CANON','REGENERATE_7_UNIVERSE_DAYS','ROUTINE_OFFLINE','MAX_PROPAGATION_DEPTH = 4','DEFAULT_PROPAGATION_BUDGET = 32']:
 add(f'required:{required}',required in text)
# Interaction whitelist exactly contains expected categories
for x in ['OPEN','CLOSE','LOCK','UNLOCK','ACTIVATE','DEACTIVATE','DAMAGE','REPAIR','IGNITE','EXTINGUISH','HEAT','COOL','SOAK','DRY','HARVEST','CUT']:
 add(f'interaction:{x}',f'"{x}"' in text)
# Schemas/triggers/hash guarding
for x in ['reactive_profiles','environment_links','reaction_logs','environment_ticks','propagation_runs_env','reaction_logs_no_update','reaction_logs_no_delete','profile_hash','link_hash','record_hash','result_hash']:
 add(f'schema:{x}',x in text)
# No direct writes to canon/master, no network imports
imports=set()
for n in ast.walk(tree):
 if isinstance(n,ast.Import):imports.update(a.name.split('.')[0] for a in n.names)
 if isinstance(n,ast.ImportFrom) and n.module:imports.add(n.module.split('.')[0])
for mod in ['requests','urllib','socket','http','subprocess']:
 add(f'import_absent:{mod}',mod not in imports)
# Runtime is the sole state authority: object module must call apply_action, not UPDATE entity_states.
add('uses_runtime_apply_action','.apply_action(' in text)
add('no_direct_entity_state_update','UPDATE entity_states' not in text and 'INSERT INTO entity_states' not in text)
add('canonical_resolver_used','canonical_ref_resolves' in text)
add('offline_fire_explicit_block','extraordinary fire propagation is blocked offline' in text)
add('offline_fire_tick_frozen','and not offline' in text)
add('recovery_restores_integrity','"data.integrity": float(profile["base_integrity"])' in text)
add('destroy_sets_functional_false','"data.functional", False' in text)
add('fire_budget_guard','heated<budget' in text)
add('fire_cycle_guard','visited={root_ref}' in text)
add('idempotent_environment_tick','environment_ticks' in text and 'idempotent_replay' in text)
add('idempotent_fire_propagation','propagation_runs_env' in text and 'idempotent_replay' in text)
# Compile every runtime module.
for p in sorted((ROOT/'01_RUNTIME').glob('*.py')):
 try:compile(p.read_text(),str(p),'exec');ok=True
 except Exception as e:ok=False
 add(f'compile:{p.name}',ok)
failed=[c for c in checks if c['status']=='FAIL'];report={'record_id':'LIVING-SIM-ETAPA-08-STATIC-AUDIT-V1.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','failures':failed}
(ROOT/'04_REPORTS'/'STATIC_AUDIT_V1_0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
if failed:raise SystemExit(1)
