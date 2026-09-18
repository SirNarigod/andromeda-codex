from __future__ import annotations
import hashlib, json, os, sys, time
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v15 import IntegratedLivingEngineV15
from country_scale import CountryScaleSystem
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
fail=[]
stats={'integrated_worlds':0,'health_pass':0,'movement_checks':0,'vendor_checks':0,'determinism_pairs':0,'determinism_pass':0}
start=time.time()

def canonical_hash(obj):
    raw=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()

for seed in range(1201,1221):
    e=IntegratedLivingEngineV15(':memory:',master_release_path=MASTER)
    try:
        r=e.create_world(f'arpg-stress-{seed}',seed,load_relationships=False)
        wid=r['world']['world_instance_id']; stats['integrated_worlds']+=1
        h=e.health_v15(wid)
        if h.get('status')!='PASS': fail.append({'seed':seed,'check':'HEALTH','detail':h.get('failures')})
        else: stats['health_pass']+=1
        if r.get('commerce',{}).get('count')!=84: fail.append({'seed':seed,'check':'CATALOG_COUNT','detail':r.get('commerce')})
        c=e.country(wid)
        if c.validate().get('status')!='PASS': fail.append({'seed':seed,'check':'COUNTRY_VALIDATE','detail':c.validate().get('failures')})
        if seed<1206:
            n=next(x for x in c._all_npc_records() if x.get('class')=='WARRIOR')
            a=e.movement(wid).state(n['id'])
            m=e.godot(wid).command(n['id'],'MOVE_VECTOR',{'dx':1,'dy':0,'duration_s':0.1,'mode':'WALK'})
            b=e.movement(wid).state(n['id']); stats['movement_checks']+=1
            if m.get('status')!='PASS' or b['iso_x_m']<=a['iso_x_m']: fail.append({'seed':seed,'check':'MOVE_VECTOR','detail':m})
            sh=next(sh for st in c.world['country']['states'] for bl in st['blocks'] for cy in bl['cities'] for sh in cy['shops'])
            try:
                e.bridge(wid).ensure_vendor(sh['id']); stats['vendor_checks']+=1
            except Exception as exc: fail.append({'seed':seed,'check':'VENDOR','detail':repr(exc)})
    except Exception as exc:
        fail.append({'seed':seed,'check':'WORLD_EXCEPTION','detail':repr(exc)})
    finally:
        e.close()

for seed in range(2201,2211):
    a=CountryScaleSystem(master_release_path=MASTER,seed=seed)
    b=CountryScaleSystem(master_release_path=MASTER,seed=seed)
    stats['determinism_pairs']+=1
    ha,hb=canonical_hash(a.world),canonical_hash(b.world)
    if ha==hb: stats['determinism_pass']+=1
    else: fail.append({'seed':seed,'check':'COUNTRY_DETERMINISM','a':ha,'b':hb})

rep={
 'record_id':'ARPG-STAGE00-STRESS-V0.1.0','status':'PASS' if not fail else 'FAIL',
 'stats':stats,'failure_count':len(fail),'failures':fail[:50],
 'seconds':round(time.time()-start,3),'master':'V2.0.1','master_sha256':'6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2'
}
out=ROOT/'04_REPORTS/ARPG_STAGE00/ARPG_STAGE00_STRESS_V0_1_0.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(rep,ensure_ascii=False));raise SystemExit(1 if fail else 0)
