from __future__ import annotations
import hashlib, json, math, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from country_scale import CountryScaleSystem, NPC_CLASSES, SHOP_KINDS, TIERS
from scene_interaction import SceneInteractionSystem, SCENE_TYPES
from content_catalog import ITEM_NAMES, RESOURCE_CATALOG, validate_catalog, name_status
from mar_balance import MARCanonBalance
MASTER=Path(os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'))
EXPECTED_MASTER='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2'
fail=[]; checks=0

def check(cond,label):
 global checks
 checks+=1
 if not cond: fail.append(label)

def eq(a,b):
 if isinstance(a,float) or isinstance(b,float): return math.isclose(float(a),float(b),rel_tol=1e-10,abs_tol=1e-6)
 return a==b

c=CountryScaleSystem(master_release_path=MASTER,seed=1201); s=SceneInteractionSystem(c); country=c.world['country']
check(c.validate()['status']=='PASS','COUNTRY_VALIDATE')
check(s.validate()['status']=='PASS','SCENE_VALIDATE')
check(validate_catalog()['status']=='PASS','CATALOG_VALIDATE')
check(MARCanonBalance(MASTER).validate()['status']=='PASS','MAR_VALIDATE')
check(hashlib.sha256(MASTER.read_bytes()).hexdigest()==EXPECTED_MASTER,'MASTER_SHA256')

ids=set(); names=[]; object_types=set(); root_count=0

def named(rec,label):
 if rec.get('id'):
  check(rec['id'] not in ids,'DUP_ID:'+rec['id']); ids.add(rec['id'])
  check(bool(rec.get('name')),'UNNAMED:'+label+':'+rec['id'])
  if rec.get('name'): names.append(rec['name'])

for st in country['states']:
 named(st,'STATE'); check(st['tier'] in TIERS,'STATE_TIER:'+st['id'])
 for b in st['blocks']:
  named(b,'BLOCK'); root_count+=int(b['root_deep'])
  resource_ids={r['id'] for r in b['resources']}
  check(('MIN-ROOT-SHARD' in resource_ids)==bool(b['root_deep']),'ROOT_SHARD_LOCALITY:'+b['id'])
  check(len(resource_ids)==len(b['resources']),'DUP_RESOURCE_TYPE_IN_BLOCK:'+b['id'])
  for r in b['resources']:
   check(bool(r.get('name')),'UNNAMED:RESOURCE:'+r['id']+':'+b['id']); check(r['tier'] in TIERS,'RESOURCE_TIER:'+r['id']+':'+b['id'])
  for sub in b['subregions']: named(sub,'SUBREGION')
  for ind in b['industries']: named(ind,'INDUSTRY')
  for f in b['flora']: named(f,'FLORA')
  for a in b['fauna']: named(a,'FAUNA')
  for br in b['bridges']:
   named(br,'BRIDGE'); check(br['durability']<=br['durability_max'],'BRIDGE_DURABILITY:'+br['id']); check(all(v>=0 for v in br['inventory'].values()),'BRIDGE_INV_NEG:'+br['id'])
  for realm in b.get('kingdoms',[]):
   named(realm,'REALM')
   for leg in realm.get('legendary_creatures',[]): named(leg,'LEGENDARY')
  for city in b['cities']:
   named(city,'CITY')
   for sh in city['shops']:
    named(sh,'SHOP'); check(float(sh['wallet']['balance'])>=0,'SHOP_CASH_NEG:'+sh['id'])
   for npc in city['npcs']:
    named(npc,'NPC'); check(float(npc['wallet']['balance'])>=0,'NPC_CASH_NEG:'+npc['id']); check(npc['class'] in NPC_CLASSES,'NPC_CLASS:'+npc['id'])
    if npc['class']=='CHILD': check(not npc['protection']['combat_targetable'] and not npc['protection']['hazardous_labor_allowed'],'CHILD_PROTECTION:'+npc['id'])
  for d in b.get('dungeons',[]):
   named(d,'DUNGEON')
   for obj in d['objects']:
    named(obj,'SCENE'); object_types.add(obj['object_type'])
    if obj.get('item_ref'): check(obj['item_ref'] in ITEM_NAMES,'UNNAMED_SCENE_ITEM:'+obj['item_ref'])
  for obj in b.get('scene_objects',[]):
   named(obj,'SCENE'); object_types.add(obj['object_type'])
   if obj.get('item_ref'): check(obj['item_ref'] in ITEM_NAMES,'UNNAMED_SCENE_ITEM:'+obj['item_ref'])
  for city in b['cities']:
   for obj in city.get('scene_objects',[]):
    named(obj,'SCENE'); object_types.add(obj['object_type'])
    if obj.get('item_ref'): check(obj['item_ref'] in ITEM_NAMES,'UNNAMED_SCENE_ITEM:'+obj['item_ref'])

check(root_count>=1,'ROOT_COVERAGE')
check(set(SCENE_TYPES).issubset(object_types),'SCENE_TYPE_COVERAGE:'+str(sorted(set(SCENE_TYPES)-object_types)))
check(set(NPC_CLASSES).issubset({n['class'] for n in c._all_npc_records()}),'NPC_CLASS_COVERAGE')
shops=[sh for st in country['states'] for b in st['blocks'] for cy in b['cities'] for sh in cy['shops']]
check(set(SHOP_KINDS).issubset({sh['kind'] for sh in shops}),'SHOP_KIND_COVERAGE')
# Every derived harvest/fauna item has a human-readable catalog name.
for ref in {f['species_ref'] for st in country['states'] for b in st['blocks'] for f in b['flora']}:
 check('ITEM-HARVEST-'+ref in ITEM_NAMES,'HARVEST_NAME:'+ref)
for ref in {a['species_ref'] for st in country['states'] for b in st['blocks'] for a in b['fauna']}:
 check('ITEM-FAUNA-'+ref in ITEM_NAMES,'FAUNA_RESOURCE_NAME:'+ref)

DICT_KEYS=('resources','flora','fauna','npcs','shop_items','npc_items','industry_stock','bridge_resources','mage_classes','scene_objects','scene_items','dungeon_weapons')
SCALAR_KEYS=('industries','cities','shops','bridges','kingdoms','legendary_creatures','dungeons','npc_currency','shop_currency')
def blank(): return {**{k:{} for k in DICT_KEYS},**{k:0 for k in SCALAR_KEYS}}
def merge(dst,src):
 for k in DICT_KEYS:
  for x,v in src.get(k,{}).items(): dst[k][x]=dst[k].get(x,0)+v
 for k in SCALAR_KEYS: dst[k]+=src.get(k,0)
agg=blank()
for st in country['states']:
 sa=blank()
 for b in st['blocks']:
  ba=blank()
  for sub in b['subregions']: merge(ba,sub['inventory'])
  for k in DICT_KEYS: check(ba[k]==b['inventory'][k],f'SUBREGION_RECON:{b["id"]}:{k}')
  for k in SCALAR_KEYS: check(eq(ba[k],b['inventory'][k]),f'SUBREGION_RECON:{b["id"]}:{k}')
  merge(sa,b['inventory'])
 for k in DICT_KEYS: check(sa[k]==st['inventory'][k],f'STATE_RECON:{st["id"]}:{k}')
 for k in SCALAR_KEYS: check(eq(sa[k],st['inventory'][k]),f'STATE_RECON:{st["id"]}:{k}')
 merge(agg,st['inventory'])
for k in DICT_KEYS: check(agg[k]==country['inventory'][k],'COUNTRY_RECON:'+k)
for k in SCALAR_KEYS: check(eq(agg[k],country['inventory'][k]),'COUNTRY_RECON:'+k)

out={'status':'PASS' if not fail else 'FAIL','checks':checks,'failures':fail,'coverage':{'ids':len(ids),'states':len(country['states']),'blocks':sum(len(st['blocks']) for st in country['states']),'subregions':sum(len(b['subregions']) for st in country['states'] for b in st['blocks']),'cities':country['inventory']['cities'],'shops':country['inventory']['shops'],'npcs':sum(country['inventory']['npcs'].values()),'dungeons':country['inventory']['dungeons'],'scene_objects':sum(country['inventory']['scene_objects'].values()),'resource_types_catalog':len(RESOURCE_CATALOG),'scene_types':sorted(object_types)},'master_sha256':hashlib.sha256(MASTER.read_bytes()).hexdigest()}
p=ROOT/'04_REPORTS/V1_2_1/COUNTRY_SCENE_DEEP_AUDIT_V1_2_1.json'; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print(json.dumps(out,ensure_ascii=False,indent=2)); raise SystemExit(0 if out['status']=='PASS' else 1)
