from pathlib import Path
import os,sys,json
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from country_scale import CountryScaleSystem,TIERS,NPC_CLASSES,SHOP_KINDS
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
s=CountryScaleSystem(master_release_path=MASTER,seed=1201); c=s.world['country']; failures=[]; checks=0

def check(cond,label):
    global checks
    checks+=1
    if not cond: failures.append(label)

ids=set()
for st in c['states']:
    check(st['status']=='ACTIVE','STATE_STATUS:'+st['id']); check(st['tier'] in TIERS,'STATE_TIER:'+st['id'])
    check(st['id'] not in ids,'DUP:'+st['id']); ids.add(st['id'])
    for b in st['blocks']:
        check(b['status']=='ACTIVE','BLOCK_STATUS:'+b['id']); check(b['id'] not in ids,'DUP:'+b['id']); ids.add(b['id'])
        for sub in b['subregions']:
            check(sub['status']=='ACTIVE','SUB_STATUS:'+sub['id']); check(sub['id'] not in ids,'DUP:'+sub['id']); ids.add(sub['id'])
            bb=b['bounding_region']; sb=sub['bounding_region']; check(sb[0]>=bb[0]-1e-8 and sb[1]>=bb[1]-1e-8 and sb[2]<=bb[2]+1e-8 and sb[3]<=bb[3]+1e-8,'SUB_OUT:'+sub['id'])
        for r in b['resources']:
            check(r['status'] in ('AVAILABLE','SCARCE','DEPLETED'),'RESOURCE_STATUS:'+r['id']); check(r['tier'] in TIERS,'RESOURCE_TIER:'+r['id'])
        for ind in b['industries']:
            check(ind['status']=='OPERATING','IND_STATUS:'+ind['id']); check(ind['focus']=='MINING','IND_FOCUS:'+ind['id']); check(ind['tier'] in TIERS,'IND_TIER:'+ind['id'])
        for realm in b.get('kingdoms',[]):
            check(realm['status']=='ACTIVE','KDM_STATUS:'+realm['id']); check(realm['tier'] in TIERS,'KDM_TIER:'+realm['id']); check(realm['mage_class'] in TIERS,'MAGE_CLASS:'+realm['id'])
            for leg in realm['legendary_creatures']:
                check(leg['status']=='ACTIVE','LEG_STATUS:'+leg['id']); check(leg['class'] in TIERS,'LEG_CLASS:'+leg['id'])
        for city in b['cities']:
            check(city['status']=='ACTIVE','CITY_STATUS:'+city['id']); check(city['tier'] in TIERS,'CITY_TIER:'+city['id'])
            for sh in city['shops']:
                check(sh['status']=='OPEN','SHOP_STATUS:'+sh['id']); check(sh['tier'] in TIERS,'SHOP_TIER:'+sh['id']); check(sh['kind'] in SHOP_KINDS,'SHOP_KIND:'+sh['id'])
            for npc in city['npcs']:
                check(npc['status']=='ACTIVE','NPC_STATUS:'+npc['id']); check(npc['tier'] in TIERS,'NPC_TIER:'+npc['id']); check(npc['class'] in NPC_CLASSES,'NPC_CLASS:'+npc['id']); check(npc['block_id'] in {x['id'] for ss in c['states'] for x in ss['blocks']},'NPC_BLOCK:'+npc['id'])
        for f in b['flora']:
            check(f['status'] in ('THRIVING','STABLE','SCARCE','DEPLETED'),'FLORA_STATUS:'+f['id']); check(f['tier'] in TIERS,'FLORA_TIER:'+f['id'])
        for a in b['fauna']:
            check(a['status'] in ('ACTIVE','EXTIRPATED_LOCAL'),'FAUNA_STATUS:'+a['id']); check(a['tier'] in TIERS,'FAUNA_TIER:'+a['id'])
        for br in b['bridges']:
            check(br['status'] in ('ACTIVE','DAMAGED','DESTROYED'),'BRIDGE_STATUS:'+br['id']); check(br['tier']=='ALTO','BRIDGE_TIER:'+br['id'])
# Global class coverage
npcs=[n for st in c['states'] for b in st['blocks'] for city in b['cities'] for n in city['npcs']]
check(set(NPC_CLASSES).issubset({n['class'] for n in npcs}),'NPC_CLASS_COVERAGE')
shops=[sh for st in c['states'] for b in st['blocks'] for city in b['cities'] for sh in city['shops']]
check(set(SHOP_KINDS).issubset({sh['kind'] for sh in shops}),'SHOP_KIND_COVERAGE')
check(c['inventory']['kingdoms']>=1,'KINGDOM_COVERAGE'); check(c['inventory']['legendary_creatures']>=1,'LEGENDARY_COVERAGE')
# Inventory consistency from built-in validator
v=s.validate(); check(v['status']=='PASS','BUILTIN_VALIDATE')
out={'status':'PASS' if not failures else 'FAIL','checks':checks,'failures':failures,'coverage':{'npc_classes':sorted({n['class'] for n in npcs}),'shop_kinds':sorted({sh['kind'] for sh in shops}),'kingdoms':c['inventory']['kingdoms'],'legendary_creatures':c['inventory']['legendary_creatures']}}
path=ROOT/'04_REPORTS/V1_2_0'; path.mkdir(parents=True,exist_ok=True); (path/'COUNTRY_SCALE_DEEP_AUDIT_V1_2.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2)); raise SystemExit(0 if out['status']=='PASS' else 1)
