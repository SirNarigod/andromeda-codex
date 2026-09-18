import hashlib,json,re,zipfile,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1]
M=Path('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
OUT=R/'04_REPORTS/V1_2_1/STAGE13_STATIC_AUDIT_V1_2_1.json'
OUT.parent.mkdir(parents=True,exist_ok=True)
BASE=json.load(open(R/'06_ATLAS_LIVING/UPSTREAM_BASELINE_HASHES_V1_1_SEALED.json',encoding='utf-8'))
OLD=json.load(open(R/'06_ATLAS_LIVING/UPSTREAM_BASELINE_HASHES_V1_0.json',encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
mods=list(BASE['runtime_modules'])
module_rows=[]
for m in mods:
    actual=sha(R/'01_RUNTIME'/m); expected=BASE['runtime_modules'][m]
    module_rows.append({'module':m,'v1_2_1_sha256':actual,'v1_1_sealed_sha256':expected,'identical':actual==expected})
atlas_paths=list(OLD['canonical_atlas_runtime']);atlas_rows=[]
with zipfile.ZipFile(M) as z:
    names=z.namelist()
    prefix=next(n.split('02_ATLAS/runtime/')[0] for n in names if '02_ATLAS/runtime/atlas-core.mjs' in n)
    for pth in atlas_paths:
        actual=hashlib.sha256(z.read(prefix+pth)).hexdigest(); expected=OLD['canonical_atlas_runtime'][pth]
        atlas_rows.append({'path':pth,'actual_sha256':actual,'master_v2_0_1_sha256':expected,'match':actual==expected})
bridge=(R/'01_RUNTIME/atlas_living_bridge.py').read_text(encoding='utf-8')
js=(R/'06_ATLAS_LIVING/atlas-live-core.mjs').read_text(encoding='utf-8')
contract=json.load(open(R/'02_CONTRACTS/ATLAS_CODEX_LIVING_RUNTIME_INTEGRATION_CONTRACT_V1_0.json',encoding='utf-8'))
checks=[]
def ck(n,o,d=None):checks.append({'name':n,'status':'PASS' if o else 'FAIL','detail':d})
for x in module_rows: ck('v1.1-sealed-byte-identical:'+x['module'],x['identical'],x)
for x in atlas_rows: ck('canonical-atlas-master-hash:'+x['path'],x['match'],x)
for n,o in [
 ('bridge-mode-ro','?mode=ro' in bridge),('bridge-query-only','PRAGMA query_only=ON' in bridge),
 ('bridge-no-network-import',not re.search(r'^\s*(import|from)\s+(requests|httpx|urllib|socket|aiohttp)',bridge,re.M)),
 ('bridge-no-eval','eval(' not in bridge),('bridge-no-exec','exec(' not in bridge),('bridge-no-todo',not re.search(r'TODO|FIXME',bridge,re.I)),
 ('public-role',"role=='PUBLIC'" in bridge),('player-owner-scope','owner_scope' in bridge and 'player scope mismatch' in bridge),
 ('admin-role',"role=='ADMIN'" in bridge),('level4-hidden','level<4' in bridge),('hidden-atlas-filter',"atlas_visibility')!='HIDDEN'" in bridge),
 ('recursive-redaction','REDACTED_CANONICAL_REF' in bridge and 'REDACTED_RUNTIME_REF' in bridge),
 ('llm-raw-not-exposed',"'raw_content_exposed':False" in bridge),('snapshot-backup-api','.backup(dst)' in bridge),
 ('snapshot-backend-only','BACKEND_ONLY_DO_NOT_SERVE_DB_FILE' in bridge),('snapshot-0600','os.chmod(target,0o600)' in bridge),
 ('snapshot-core-integrity','full_integrity_check(world_instance_id)' in bridge),
 ('row-hash-checks','state_hash' in bridge and 'relationship_hash' in bridge and 'population_hash' in bridge),
 ('projection-hash','projection_hash' in bridge and 'verify_projection' in bridge),('js-readonly-assert','runtime_write_authority !== false' in js),
 ('js-no-fetch','fetch(' not in js),('js-no-storage-write',not re.search(r'localStorage\.(setItem|removeItem)|indexedDB|XMLHttpRequest',js)),
 ('contract-json-only',contract.get('transport',{}).get('client_delivery')=='JSON_PROJECTION_ONLY'),
 ('contract-backend-snapshot',contract.get('transport',{}).get('snapshot_file_distribution')=='BACKEND_ONLY_0600'),
 ('master-release-hash',hashlib.sha256(M.read_bytes()).hexdigest()==BASE['master_release_sha256'])]: ck(n,o)
failed=[c for c in checks if c['status']=='FAIL']
rep={'record_id':'STAGE13-STATIC-AUDIT-V1.2.1','basis':'V1.1 sealed runtime + Master V2.0.1 canonical Atlas','historical_auditor_note':'The V1.0 Stage13 baseline is retained as historical evidence and is not authoritative for V1.1 inherited runtime hashes.','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','upstream_modules':module_rows,'canonical_atlas_runtime':atlas_rows,'failures':failed}
OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':rep['status'],'checks':rep['checks'],'failed':rep['failed']}))
raise SystemExit(0 if not failed else 1)
