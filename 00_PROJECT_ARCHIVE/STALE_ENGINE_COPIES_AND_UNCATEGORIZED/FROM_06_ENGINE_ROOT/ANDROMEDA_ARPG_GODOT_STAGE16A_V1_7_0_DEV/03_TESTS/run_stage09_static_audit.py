import ast, hashlib, json, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SRC=ROOT/'01_RUNTIME'/'world_orchestrator.py'; REPORT=ROOT/'04_REPORTS'/'STAGE09_STATIC_AUDIT_V1_0.json'
MASTER=Path('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'); EXPECT='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2'
text=SRC.read_text();tree=ast.parse(text); checks=[]
def add(name,ok,detail=None):checks.append({'check':name,'status':'PASS' if ok else 'FAIL','detail':detail})
# Source/runtime boundaries
for token in ['eval(','exec(','requests.','urllib.','socket.','subprocess.','os.system(','pickle.loads(']:add('forbidden:'+token,token not in text)
for token in ['TODO','FIXME','LLM_EXECUTOR','CANON_WRITE','UNKNOWN_CANON_NAMESPACE']:add('absent:'+token,token not in text)
for token in ['FULL','ACTIVE','AGGREGATE','ROUTINE_OFFLINE']:add('lod:'+token,token in text)
for phase in ['PRE_GUARD','RECOVERY','ENVIRONMENT','ECOLOGY_AGGREGATE','ECOLOGY_INDIVIDUAL','SOCIAL_PROJECTION','NPC_AUTONOMY','EXTENSIONS','CONSEQUENCE_DRAIN','POST_GUARD','CLOCK_ADVANCE']:add('phase:'+phase,phase in text)
for token in ['RUNTIME_ORCHESTRATION_NOT_CANON','RUNTIME_EXTENSION_DESCRIPTOR_NOT_CANON','orchestration_config_snapshots','orch_config_no_update','orch_phase_no_update','max_roots_per_run','minimum_root_capacity','bind_extension_handler','handler identity does not match','idempotent_replay','verify_run_chain','CORRUPT_BLOCKED','ROUTINE_OFFLINE','policy_hash','config_snapshot_hash']:add('required:'+token,token in text)
add('no-direct-apply-action','runtime.apply_action(' not in text)
add('no-direct-llm-gateway','ingest_llm_candidate(' not in text)
add('agent-through-brain','self.brain.decide(' in text)
add('intent-through-validator','self.validator.validate_intent(' in text and 'self.validator.execute_validated_intent(' in text)
add('ecology-through-authority','self.ecology.decide(' in text and 'self.ecology.execute_decision(' in text)
add('environment-through-authority','self.objects.simulate_environment_tick(' in text)
add('recovery-through-runtime','self.runtime.process_due_recoveries(' in text)
add('causal-through-engine','self.consequence_engine.propagate_from_event(' in text)
add('clock-last',text.find('"CLOCK_ADVANCE"')>text.find('"POST_GUARD"'))
add('offline-block-npc','world_mode in {"AGGREGATE","ROUTINE_OFFLINE"}' in text)
add('extension-offline-safe','offline extension must be explicitly routine_safe' in text)
add('extension-missing-failclosed','extension handler missing at runtime' in text)
add('run-failed-conflict','orchestration tick already exists but is not completed' in text)
add('same-runtime-required','all orchestrated systems must share the same LivingRuntime' in text)
add('validator-consistency','brain/ecology validator mismatch' in text)
# AST checks
classes=[n for n in tree.body if isinstance(n,ast.ClassDef)];add('single-main-class',any(c.name=='WorldSimulationOrchestrator' for c in classes))
methods={n.name for c in classes if c.name=='WorldSimulationOrchestrator' for n in c.body if isinstance(n,ast.FunctionDef)}
for m in ['configure_world','get_policy','register_scope','set_scope_lod','register_participant','attach_extension','bind_extension_handler','run_tick','run_steps','verify_run_chain','full_integrity_check','integrity_guard']:add('method:'+m,m in methods)
# Byte identity upstream
mods=['living_runtime.py','consequence_engine.py','agent_brain.py','social_memory.py','ecology_brain.py','object_environment.py']
for m in mods:
    a=Path('/mnt/data/ANDROMEDA_LIVING_SIM_ETAPA_08/01_RUNTIME')/m;b=ROOT/'01_RUNTIME'/m
    add('upstream-identical:'+m,hashlib.sha256(a.read_bytes()).digest()==hashlib.sha256(b.read_bytes()).digest())
actual=hashlib.sha256(MASTER.read_bytes()).hexdigest();add('master-sha',actual==EXPECT,actual)
# Tests/reports presence
for f in ['03_TESTS/test_world_orchestrator.py','03_TESTS/run_stage09_extended_validation.py','03_TESTS/run_stage09_fuzz_stress.py','04_REPORTS/STAGE09_EXTENDED_VALIDATION_V1_0.json','04_REPORTS/STAGE09_FUZZ_STRESS_V1_0.json','04_REPORTS/UPSTREAM_MODULE_HASH_COMPARISON_V1_0.json']:add('exists:'+f,(ROOT/f).exists())
# Validate report statuses
for f in ['STAGE09_EXTENDED_VALIDATION_V1_0.json','STAGE09_FUZZ_STRESS_V1_0.json','UPSTREAM_MODULE_HASH_COMPARISON_V1_0.json']:
    d=json.loads((ROOT/'04_REPORTS'/f).read_text());add('report-pass:'+f,d.get('status')=='PASS')
failed=[c for c in checks if c['status']!='PASS'];report={'record_id':'STAGE09-STATIC-AUDIT-V1.0','status':'PASS' if not failed else 'FAIL','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'failures':failed}
REPORT.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));raise SystemExit(0 if not failed else 1)
