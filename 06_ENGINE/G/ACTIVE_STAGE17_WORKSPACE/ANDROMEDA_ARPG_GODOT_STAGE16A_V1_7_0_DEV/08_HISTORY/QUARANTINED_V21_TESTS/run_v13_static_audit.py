import ast,hashlib,json,re,zipfile,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OLD=Path('/mnt/data/ANDROMEDA_LIVING_COUNTRY_SCALE_V1_2_1_DEV.zip')
M21=Path('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_1_0_RELEASE.zip')
M20=Path('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
OUT=ROOT/'04_REPORTS/V1_3_0/V1_3_STATIC_AUDIT.json'; OUT.parent.mkdir(parents=True,exist_ok=True)
H21='9677b10890c24dfc04916178a2b9fd40a9ea131f2a13c1ec8255186ab203a98b';H20='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2'
checks=[]
def ck(n,o,d=None):checks.append({'name':n,'status':'PASS' if o else 'FAIL','detail':d})
def sha_bytes(b):return hashlib.sha256(b).hexdigest()
def sha(p):return sha_bytes(Path(p).read_bytes())
ck('master-v21-sha',sha(M21)==H21,sha(M21));ck('master-v20-baseline-still-present',sha(M20)==H20,sha(M20))
# Exact runtime mutation scope against sealed V1.2.1 DEV package.
with zipfile.ZipFile(OLD) as z:
 prefix='ANDROMEDA_LIVING_COUNTRY_SCALE_V1_2_1_DEV/'
 old={n[len(prefix):]:sha_bytes(z.read(n)) for n in z.namelist() if n.startswith(prefix+'01_RUNTIME/') and not n.endswith('/')}
cur={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'01_RUNTIME').glob('*.py')}
changed=sorted(k for k in old if k in cur and old[k]!=cur[k]);new=sorted(k for k in cur if k not in old);missing=sorted(k for k in old if k not in cur)
allowed_changed=sorted(['01_RUNTIME/atlas_living_bridge.py','01_RUNTIME/combat_system.py','01_RUNTIME/commerce_system.py','01_RUNTIME/consequence_engine.py','01_RUNTIME/country_scale.py','01_RUNTIME/ecology_brain.py','01_RUNTIME/living_runtime.py'])
allowed_new=sorted(['01_RUNTIME/country_living_bridge.py','01_RUNTIME/integrated_engine_v13.py'])
ck('runtime-changed-allowlist',changed==allowed_changed,{'actual':changed,'expected':allowed_changed});ck('runtime-new-allowlist',new==allowed_new,{'actual':new,'expected':allowed_new});ck('runtime-no-missing',missing==[],missing)
# Syntax in memory; do not create pycache.
for p in sorted((ROOT/'01_RUNTIME').glob('*.py')):
 try:ast.parse(p.read_text(encoding='utf-8'));ok=True;detail=None
 except Exception as e:ok=False;detail=str(e)
 ck('syntax:'+p.name,ok,detail)
# Authority and anti-parallel-path checks.
bridge=(ROOT/'01_RUNTIME/country_living_bridge.py').read_text(encoding='utf-8'); country=(ROOT/'01_RUNTIME/country_scale.py').read_text(encoding='utf-8'); lr=(ROOT/'01_RUNTIME/living_runtime.py').read_text(encoding='utf-8'); eco=(ROOT/'01_RUNTIME/ecology_brain.py').read_text(encoding='utf-8'); cons=(ROOT/'01_RUNTIME/consequence_engine.py').read_text(encoding='utf-8'); atlas=(ROOT/'01_RUNTIME/atlas_living_bridge.py').read_text(encoding='utf-8'); v13=(ROOT/'01_RUNTIME/integrated_engine_v13.py').read_text(encoding='utf-8')
for n,o in [
 ('country-purchase-delegates','return self.domain_bridge.purchase' in country),('country-hunt-delegates','return self.domain_bridge.hunt_fauna' in country),
 ('bridge-no-legacy-purchase-call','_purchase_legacy' not in bridge),('bridge-no-legacy-hunt-call','_hunt_fauna_legacy' not in bridge),
 ('bridge-commerce-authority','self.commerce.execute_quote' in bridge),('bridge-combat-authority','self.combat.attack' in bridge),('bridge-social-memory','recall_memories' in bridge),
 ('bridge-child-purchase-protection','PROTECTED_MINOR_WEAPON_PURCHASE' in bridge),('bridge-child-combat-protection',bridge.count('PROTECTED_MINOR_COMBAT')>=3),
 ('v13-requires-master-v21',"requires Master V2.1.0" in v13),('v13-health-reads-baseline',"baseline.get('master_version')" in v13 and "baseline.get('release_sha256')" in v13),
 ('runtime-supports-v20',H20 in lr),('runtime-supports-v21',H21 in lr),('ecology-verifies-runtime-baseline','self.runtime.master_release_sha256' in eco),('consequence-verifies-runtime-baseline','self.runtime.master_release_sha256' in cons),
 ('atlas-uses-supported-baselines','SUPPORTED_MASTER_RELEASES' in atlas),('no-obsolete-hardcoded-compare','actual != MASTER_RELEASE_SHA256' not in eco+cons),
 ('no-eval-exec','eval(' not in bridge and 'exec(' not in bridge),('no-network-import',not re.search(r'^\s*(import|from)\s+(requests|httpx|urllib|socket|aiohttp)',bridge,re.M)),
 ]: ck(n,o)
# Master V2.1 canonical contracts.
with zipfile.ZipFile(M21) as z:
 items=json.loads(z.read('ANDROMEDA_CODEX_MASTER/03_DOMAINS/COUNTRY_SCALE/COUNTRY_ITEM_CATALOG_V2_1_0.json'))
 ext=json.loads(z.read('ANDROMEDA_CODEX_MASTER/01_CANON/COUNTRY_SCALE_CANON_EXTENSION_V2_1_0.json'))
 mar=json.loads(z.read('ANDROMEDA_CODEX_MASTER/05_MAR/FUNCTIONAL/01_MAR/MAR_GAMEPLAY_STATS_CANON_V2_1_0.json'))
 ids=[x['id'] for x in items['items']]
 ck('master-country-items-54',len(ids)==54,len(ids));ck('master-country-items-unique',len(ids)==len(set(ids)));ck('master-mar-30',mar.get('count')==30 and len(mar.get('weapons',[]))==30,{'count':mar.get('count'),'weapons':len(mar.get('weapons',[]))})
 ck('kenua-country-unresolved',ext.get('narrative_safety',{}).get('kenua_country_binding')=='UNRESOLVED',ext.get('narrative_safety'))
 ck('hierarchy-country-state-block',ext.get('hierarchy',[])[:4]==['PLANET','COUNTRY','STATE','REGION_BLOCK'],ext.get('hierarchy'))
# Artifact hygiene.
ck('no-db-artifacts',not any(p.suffix.lower() in {'.db','.sqlite','.sqlite3'} for p in ROOT.rglob('*') if p.is_file()))
ck('no-pycache',not any(p.name=='__pycache__' for p in ROOT.rglob('__pycache__')))
failed=[c for c in checks if c['status']=='FAIL']
rep={'record_id':'V1.3-STATIC-AUDIT','status':'PASS' if not failed else 'FAIL','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'changed_runtime':changed,'new_runtime':new,'failures':failed,'master_v21_sha256':sha(M21),'master_v20_sha256':sha(M20)}
OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'status':rep['status'],'checks':rep['checks'],'passed':rep['passed'],'failed':rep['failed'],'failures':failed[:5]},ensure_ascii=False));raise SystemExit(1 if failed else 0)
