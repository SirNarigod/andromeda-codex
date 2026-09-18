import ast,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
files={p.name:p for p in (ROOT/'01_RUNTIME').glob('*.py')}
checks=[]
def add(name,ok,detail=None): checks.append({'check':name,'status':'PASS' if ok else 'FAIL','detail':detail})
texts={n:p.read_text() for n,p in files.items()}
trees={n:ast.parse(t) for n,t in texts.items()}
# Syntax / module inventory
for n in ['living_runtime.py','consequence_engine.py','agent_brain.py']:
 add(f'parse_{n}',n in trees)
# Dangerous builtins / imports
for n,tree in trees.items():
 calls=[x.func.id for x in ast.walk(tree) if isinstance(x,ast.Call) and isinstance(x.func,ast.Name)]
 add(f'no_eval_{n}','eval' not in calls)
 add(f'no_exec_{n}','exec' not in calls)
 imports=[]
 for x in ast.walk(tree):
  if isinstance(x,ast.Import): imports += [a.name.split('.')[0] for a in x.names]
  elif isinstance(x,ast.ImportFrom) and x.module: imports.append(x.module.split('.')[0])
 add(f'no_network_imports_{n}',not any(x in {'requests','urllib','http','socket','aiohttp'} for x in imports),sorted(set(imports)))
 add(f'no_subprocess_{n}','subprocess' not in imports)
# AgentBrain authority boundary: no apply_action call inside class AgentBrain.
tree=trees['agent_brain.py']
classes={x.name:x for x in tree.body if isinstance(x,ast.ClassDef)}
brain=classes['AgentBrain'];validator=classes['IntentValidator']
def method_calls(node,attr):
 return [x for x in ast.walk(node) if isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and x.func.attr==attr]
add('agent_brain_never_calls_apply_action',len(method_calls(brain,'apply_action'))==0,len(method_calls(brain,'apply_action')))
add('intent_validator_is_only_stage5_apply_action_caller',len(method_calls(validator,'apply_action'))==1,len(method_calls(validator,'apply_action')))
# LLM gateway must only call submit_intent and never action execution.
llm=[x for x in validator.body if isinstance(x,ast.FunctionDef) and x.name=='ingest_llm_candidate'][0]
add('llm_gateway_no_apply_action',len(method_calls(llm,'apply_action'))==0)
add('llm_gateway_no_execute_validated_intent',len(method_calls(llm,'execute_validated_intent'))==0)
# Required textual invariants.
t=texts['agent_brain.py']
for name,pat in [
 ('reserved_parameter_guard','RESERVED_PARAMETER_KEYS'),('offline_brain_guard','AgentBrain does not make autonomous decisions offline'),
 ('policy_hash_guard','action policy hash mismatch'),('perception_hash_guard','perception hash mismatch'),
 ('candidate_immutable_trigger','intent_candidate_immutable'),('validation_immutable_trigger','validation_no_update'),
 ('decision_immutable_trigger','decision_no_update'),('perception_immutable_trigger','perception_no_update'),
 ('cooldown_authoritative_state','data.agent_runtime.cooldowns'),('version_precondition_capture','entity_versions'),
 ('death_impact_inference','inferred_impacts.add("DEATH")'),('destroy_impact_inference','inferred_impacts.add("WORLD_MUTATION")'),
 ('target_resource_guard','target_resource_requirements'),('same_location_constraint','SAME_LOCATION'),
 ('corrupt_blocked_fail_closed','CORRUPT_BLOCKED'),('deterministic_tie_break','candidates.sort(key=lambda c: (-c["score"], c["behavior_key"]))'),
 ('decision_transaction','self.runtime._begin()'),('intent_idempotency_key','intent:{intent_id}')]:
 add(name,pat in t)
# Runtime/causal regressions still contain their safety invariants.
lt=texts['living_runtime.py'];ct=texts['consequence_engine.py']
for name,pat,src in [
 ('master_hash_pinned','6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2',lt),
 ('event_append_only_trigger','events_no_update',lt),('ledger_append_only_trigger','ledger_no_update',lt),
 ('seven_day_recovery','destroyed_day + 7',lt),('offline_runtime_guard','only ROUTINE_SAFE actions execute offline',lt),
 ('causal_budget_limit','budget_total INTEGER NOT NULL CHECK(budget_total BETWEEN 1 AND 64)',ct),('causal_depth_limit','MAX_DEPTH = 8',ct),
 ('canonical_relation_immutable','canonical_snapshot_relation_no_update',ct)]:
 add(name,pat in src)
# Schema DB access must be lock-guarded: basic heuristic for shared connection references in public mutating methods.
mutators=['register_policy','set_policy_status','submit_intent','validate_intent','execute_validated_intent','register_behavior','set_behavior_status','record_perception','decide']
for cname in ['IntentValidator','AgentBrain']:
 cls=classes[cname]
 for fn in [x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name in mutators]:
  src=ast.get_source_segment(t,fn) or ''
  add(f'lock_present_{cname}_{fn.name}','_lock' in src and '_write_lock' in src,fn.name)
# No TODO/FIXME in production runtime.
add('no_todo_fixme_runtime',not any(re.search(r'\b(TODO|FIXME)\b',x,re.I) for x in texts.values()))
report={'record_id':'LIVING-SIM-ETAPA-05-STATIC-AUDIT-V1.0','checks':len(checks),'passed':sum(c['status']=='PASS' for c in checks),'failed':sum(c['status']=='FAIL' for c in checks),'details':checks}
report['status']='PASS' if report['failed']==0 else 'FAIL'
(ROOT/'04_REPORTS'/'STATIC_AUDIT_V1_0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='details'},ensure_ascii=False,indent=2))
if report['status']!='PASS':
 for c in checks:
  if c['status']=='FAIL':print('FAIL',c)
 raise SystemExit(1)
