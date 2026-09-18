import json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from country_scale import CountryScaleSystem
from scene_interaction import SceneInteractionSystem
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_1_0_RELEASE.zip'
OUT=ROOT/'04_REPORTS/V1_3_0/V1_3_CATALOG_DISTRIBUTION_STRESS.json'
with zipfile.ZipFile(MASTER) as z:
    mar=json.loads(z.read('ANDROMEDA_CODEX_MASTER/05_MAR/FUNCTIONAL/01_MAR/MAR_WEAPONS_FUNCTIONAL_V1_0.json'))
    country=json.loads(z.read('ANDROMEDA_CODEX_MASTER/03_DOMAINS/COUNTRY_SCALE/COUNTRY_ITEM_CATALOG_V2_1_0.json'))
known={x['id'] for x in mar['weapons']}|{x['id'] for x in country['items']}
stats={'seeds':0,'blocks':0,'shops':0,'dungeons':0,'scene_objects':0,'npcs':0}; failures=[]
for seed in range(1200,1500):
    c=CountryScaleSystem(master_release_path=MASTER,seed=seed); SceneInteractionSystem(c); stats['seeds']+=1
    for st in c.world['country']['states']:
        if not 1<=len(st['blocks'])<=5: failures.append([seed,'STATE_BLOCK_RANGE',st['id'],len(st['blocks'])])
        for b in st['blocks']:
            stats['blocks']+=1
            if b.get('root_deep'):
                if any(f.get('role')!='PREDATOR' for f in b.get('fauna',[])): failures.append([seed,'ROOT_NON_PREDATOR',b['id']])
                if b.get('cities'): failures.append([seed,'ROOT_CITY',b['id']])
            for cy in b.get('cities',[]):
                stats['npcs']+=len(cy.get('npcs',[])); stats['shops']+=len(cy.get('shops',[]))
                for sh in cy.get('shops',[]):
                    for ref,qty in sh.get('inventory',{}).items():
                        if ref not in known: failures.append([seed,'ORPHAN_SHOP_REF',sh['id'],ref])
                        if int(qty)<0: failures.append([seed,'NEGATIVE_SHOP_QTY',sh['id'],ref,qty])
            for d in b.get('dungeons',[]):
                stats['dungeons']+=1
                for o in d.get('objects',[]):
                    stats['scene_objects']+=1
                    ref=o.get('item_ref')
                    if ref and ref not in known: failures.append([seed,'ORPHAN_SCENE_ITEM',o['id'],ref])
rep={'record_id':'V1.3-CATALOG-DISTRIBUTION-STRESS','status':'PASS' if not failures else 'FAIL','stats':stats,'known_catalog_refs':len(known),'failure_count':len(failures),'failures':failures[:50]}
OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(rep,ensure_ascii=False));raise SystemExit(1 if failures else 0)
