import json,sys,time,traceback,random
from pathlib import Path
R=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(R/'01_RUNTIME'))
from country_scale import CountryScaleSystem
from scene_interaction import SceneInteractionSystem
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
OUT=R/'04_REPORTS/V1_2_1/COUNTRY_SCENE_FINAL_STRESS_V1_2_1.json'; OUT.parent.mkdir(parents=True,exist_ok=True)
start=time.time(); failures=[]; totals={'worlds':0,'blocks':0,'roots':0,'dungeons':0,'objects':0,'npcs':0,'shops':0}; mins={'blocks':10**9,'dungeons':10**9,'objects':10**9}; maxs={'blocks':0,'dungeons':0,'objects':0}
for seed in range(1,301):
    try:
        c=CountryScaleSystem(master_release_path=MASTER,seed=seed); s=SceneInteractionSystem(c)
        cv=c.validate(); sv=s.validate()
        if cv['status']!='PASS': raise AssertionError(('country',cv))
        if sv['status']!='PASS': raise AssertionError(('scene',sv))
        states=c.world['country']['states']; blocks=[b for st in states for b in st['blocks']]
        dungeons=[d for b in blocks for d in b.get('dungeons',[])]
        objects=list(s._all_objects())
        npcs=list(c._all_npc_records()); shops=[sh for st in states for b in st['blocks'] for cy in b['cities'] for sh in cy['shops']]
        roots=sum(1 for b in blocks if b['root_deep'])
        if roots<1: raise AssertionError('no root deep block')
        if any('MIN-ROOT-SHARD' not in {r['id'] for r in b['resources']} for b in blocks if b['root_deep']): raise AssertionError('root shard missing')
        if any('MIN-ROOT-SHARD' in {r['id'] for r in b['resources']} for b in blocks if not b['root_deep']): raise AssertionError('root shard leaked')
        if any(any(a['role']!='PREDATOR' for a in b['fauna']) for b in blocks if b['root_deep']): raise AssertionError('non predator in root')
        totals['worlds']+=1; totals['blocks']+=len(blocks); totals['roots']+=roots; totals['dungeons']+=len(dungeons); totals['objects']+=len(objects); totals['npcs']+=len(npcs); totals['shops']+=len(shops)
        for k,v in [('blocks',len(blocks)),('dungeons',len(dungeons)),('objects',len(objects))]: mins[k]=min(mins[k],v); maxs[k]=max(maxs[k],v)
    except Exception as e:
        failures.append({'seed':seed,'error':repr(e),'trace':traceback.format_exc(limit=2)})
        break
rep={'record_id':'COUNTRY-SCENE-FINAL-STRESS-V1.2.1','status':'PASS' if not failures else 'FAIL','seeds_target':300,'totals':totals,'mins':mins,'maxs':maxs,'failures':failures,'seconds':round(time.time()-start,3)}
OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(rep,ensure_ascii=False)); raise SystemExit(0 if not failures else 1)
