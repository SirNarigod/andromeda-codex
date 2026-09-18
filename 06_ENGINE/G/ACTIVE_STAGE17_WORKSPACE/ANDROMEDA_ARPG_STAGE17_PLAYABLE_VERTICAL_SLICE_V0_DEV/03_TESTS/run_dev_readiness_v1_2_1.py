import json,hashlib,re
from pathlib import Path
R=Path(__file__).resolve().parents[1]; M=Path('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
checks=[]
def ck(name,ok,detail=None): checks.append({'name':name,'status':'PASS' if ok else 'FAIL','detail':detail})
ck('master-hash',sha(M)=='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2',sha(M))
# Syntax compile entirely in memory: audit must not mutate the tree it is auditing.
for p in sorted((R/'01_RUNTIME').glob('*.py')):
    try: compile(p.read_text(encoding='utf-8'),str(p),'exec'); ck('syntax:'+p.name,True)
    except Exception as e: ck('syntax:'+p.name,False,str(e))
requirements={
 'isolated-regression':R/'04_REPORTS/V1_2_1/ISOLATED_REGRESSION_V1_2_1.json','deep-audit':R/'04_REPORTS/V1_2_1/COUNTRY_SCENE_DEEP_AUDIT_V1_2_1.json',
 'generation-stress':R/'04_REPORTS/V1_2_1/COUNTRY_SCENE_FINAL_STRESS_V1_2_1.json','interaction-stress':R/'04_REPORTS/V1_2_1/COUNTRY_SCENE_INTERACTION_STRESS_V1_2_1.json',
 'static-v121':R/'04_REPORTS/V1_2_1/STAGE13_STATIC_AUDIT_V1_2_1.json','stage13-extended':R/'04_REPORTS/STAGE13_EXTENDED_VALIDATION_V1_0.json',
 'stage13-fuzz':R/'04_REPORTS/STAGE13_FUZZ_STRESS_V1_0.json','stage14-global':R/'04_REPORTS/STAGE14/STAGE14_GLOBAL_INTEGRATION_V1_0.json',
 'stage14-multiworld':R/'04_REPORTS/STAGE14/STAGE14_MULTIWORLD_SOAK_V1_0.json','stage14-corruption':R/'04_REPORTS/STAGE14/STAGE14_CORRUPTION_MATRIX_V1_0.json',
 'validation-summary':R/'04_REPORTS/V1_2_1/VALIDATION_SUMMARY_V1_2_1.json','checkpoint':R/'07_RELEASE_READINESS/V1_2_1_DEV/CHECKPOINT_COUNTRY_SCALE_V1_2_1_DEV.json'}
for name,p in requirements.items():
    ok=p.exists(); detail=None
    if ok:
        d=load(p); status=str(d.get('status','')); ok=status.startswith('PASS') or 'ZERO_KNOWN' in status; detail=status
    ck('report:'+name,ok,detail)
for f in ['AGENT_REGISTRY_V1_2_1.json','CONTENT_EXPANSION_V1_2_1.json','CODEX_COUNTRY_SCALE_CANON_RULES_V1_2_1.json','SCENE_DUNGEON_INTERACTION_CONTRACT_V1_2_1.json','TERRAS_LIVRES_COUNTRY_SCALE_SEED_1201_RUNTIME.json','NEXT_STAGE_PROPOSAL_MASTER_V2_1_COUNTRY_INTEGRATION.json']:
    ck('expansion:'+f,(R/'09_CODEX_EXPANSION/V1_2_1_DEV'/f).exists())
ck('no-db-artifacts',not any(p.suffix.lower() in {'.db','.sqlite','.sqlite3'} for p in R.rglob('*') if p.is_file()))
ck('no-pycache',not any(p.name=='__pycache__' for p in R.rglob('*') if p.is_dir()))
newsrc='\n'.join((R/'01_RUNTIME'/f).read_text(encoding='utf-8',errors='ignore') for f in ['content_catalog.py','country_scale.py','scene_interaction.py','integrated_engine_v12.py'])
ck('new-code-no-todo-fixme',not re.search(r'\b(TODO|FIXME)\b',newsrc))
bugs=load(R/'04_REPORTS/V1_2_1/BUG_CORRECTION_LEDGER_V1_2_1.json'); ck('known-active-bugs-zero',bugs.get('open_known_bugs')==0,bugs.get('open_known_bugs'))
base=load(R/'06_ATLAS_LIVING/UPSTREAM_BASELINE_HASHES_V1_1_SEALED.json')
for m,exp in base['runtime_modules'].items(): ck('v1.1-sealed:'+m,sha(R/'01_RUNTIME'/m)==exp)
failed=[x for x in checks if x['status']=='FAIL']
rep={'record_id':'DEV-READINESS-AUDIT-V1.2.1','status':'PASS' if not failed else 'FAIL','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'failures':failed,'release_class':'DEV_CONVERGED_NOT_PRODUCTION_RELEASE','production_backup_allowed':False,'audit_mutation_policy':'READ_ONLY_IN_MEMORY_SYNTAX_CHECK','reason':'Master V2.1 consolidation and post-consolidation restore/release cycle are next-stage gates.'}
out=R/'07_RELEASE_READINESS/V1_2_1_DEV/DEV_READINESS_AUDIT_V1_2_1.json'; out.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(rep,ensure_ascii=False)); raise SystemExit(0 if not failed else 1)
