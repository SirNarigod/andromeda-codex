from pathlib import Path
import os, sys, json
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from country_scale import CountryScaleSystem, NPC_CLASSES, SHOP_KINDS
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
failures=[]; summaries=[]
for seed in range(1000,1200):
    s=CountryScaleSystem(master_release_path=MASTER,seed=seed); v=s.validate()
    c=s.world['country']; npcs=[n for st in c['states'] for b in st['blocks'] for cy in b['cities'] for n in cy['npcs']]
    shops=[sh for st in c['states'] for b in st['blocks'] for cy in b['cities'] for sh in cy['shops']]
    if v['status']!='PASS': failures.append({'seed':seed,'type':'VALIDATE','details':v})
    missing_npcs=sorted(set(NPC_CLASSES)-{n['class'] for n in npcs})
    if missing_npcs: failures.append({'seed':seed,'type':'NPC_CLASS_MISSING','details':missing_npcs})
    missing_shops=sorted(set(SHOP_KINDS)-{sh['kind'] for sh in shops})
    if missing_shops: failures.append({'seed':seed,'type':'SHOP_KIND_MISSING','details':missing_shops})
    if c['inventory']['kingdoms']<1 or c['inventory']['legendary_creatures']<1: failures.append({'seed':seed,'type':'MAGIC_REALM_COVERAGE'})
    # No negative quantity anywhere in hierarchy
    def neg(inv):
        for k in ('resources','flora','fauna','shop_items','npc_items','industry_stock','bridge_resources'):
            if any(v<0 for v in inv.get(k,{}).values()): return k
    if neg(c['inventory']): failures.append({'seed':seed,'type':'NEG_COUNTRY_INVENTORY'})
    summaries.append({'seed':seed,'states':len(c['states']),'blocks':sum(len(st['blocks']) for st in c['states']),'subregions':sum(len(b['subregions']) for st in c['states'] for b in st['blocks']),'root_blocks':v['root_blocks'],'cities':c['inventory']['cities'],'shops':c['inventory']['shops'],'npcs':sum(c['inventory']['npcs'].values())})
out={'status':'PASS' if not failures else 'FAIL','seeds_tested':200,'failures':failures,'summary_minmax':{k:[min(x[k] for x in summaries),max(x[k] for x in summaries)] for k in ('states','blocks','subregions','root_blocks','cities','shops','npcs')}}
path=ROOT/'04_REPORTS/V1_2_0'; path.mkdir(parents=True,exist_ok=True); (path/'COUNTRY_SCALE_STRESS_V1_2.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
raise SystemExit(0 if out['status']=='PASS' else 1)
