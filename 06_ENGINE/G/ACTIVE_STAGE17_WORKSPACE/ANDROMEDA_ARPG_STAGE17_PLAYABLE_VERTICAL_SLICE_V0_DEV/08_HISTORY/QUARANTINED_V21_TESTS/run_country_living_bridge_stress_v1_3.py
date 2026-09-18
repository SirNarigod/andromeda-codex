import json,time,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v13 import IntegratedLivingEngineV13
M='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_1_0_RELEASE.zip'; OUT=ROOT/'04_REPORTS/V1_3_0/COUNTRY_LIVING_BRIDGE_STRESS_V1_3.json'
fail=[]; stats={'worlds':0,'purchases':0,'hunts':0,'kills':0,'memories':0,'scene_weapon_equips':0,'child_weapon_rejections':0,'health_pass':0};t0=time.time()
for seed in range(3100,3150):
 e=IntegratedLivingEngineV13(':memory:',master_release_path=M)
 try:
  r=e.create_world(f'v13-stress-{seed}',seed,load_relationships=False);wid=r['world']['world_instance_id'];c=e.country(wid);br=e.bridge(wid);scene=e.scenes(wid);stats['worlds']+=1
  ctx=None
  for st in c.world['country']['states']:
   for b in st['blocks']:
    pred=next((f for f in b['fauna'] if f['role']=='PREDATOR' and f['count']>0),None)
    for cy in b['cities']:
     npc=next((n for n in cy['npcs'] if n['class']!='CHILD' and n['protection']['combat_targetable']),None)
     sh=next((s for s in cy['shops'] if any(k.startswith('WPN-') and v>0 for k,v in s['inventory'].items())),None)
     if pred and npc and sh:
      w=next(k for k,v in sh['inventory'].items() if k.startswith('WPN-') and v>0);ctx=(b,cy,npc,sh,pred,w);break
    if ctx:break
   if ctx:break
  if not ctx:fail.append([seed,'NO_TRADE_HUNT_CONTEXT']);continue
  b,cy,n,sh,f,w=ctx
  p=c.purchase(sh['id'],n['id'],w,1)
  if p.get('status')!='PASS' or p.get('money_conservation_delta')!=0.0:fail.append([seed,'PURCHASE',p]);continue
  stats['purchases']+=1
  h=c.hunt_fauna(b['id'],f['id'],1,n['id'])
  if h.get('status')!='PASS' or h.get('killed')!=1:fail.append([seed,'HUNT',h]);continue
  stats['hunts']+=1;stats['kills']+=h['killed'];stats['memories']+=h.get('witness_memory_count',0)
  # Protected-minor policy across procedural seeds.
  child_ctx=None
  for st in c.world['country']['states']:
   for bb in st['blocks']:
    for cc in bb['cities']:
     child=next((x for x in cc['npcs'] if x['class']=='CHILD'),None)
     adult=next((x for x in cc['npcs'] if x['class'] not in ('CHILD','WORKER') and x['protection']['combat_targetable']),None)
     shop=next((x for x in cc['shops'] if any(k.startswith('WPN-') and v>0 for k,v in x['inventory'].items())),None)
     if child and adult and shop:
      item=next(k for k,v in shop['inventory'].items() if k.startswith('WPN-') and v>0);child_ctx=(child,adult,shop,item);break
    if child_ctx:break
   if child_ctx:break
  if child_ctx:
   child,adult,shop,item=child_ctx; before=e.commerce.full_integrity_check(wid)['transactions']; q=c.purchase(shop['id'],child['id'],item,1);a=br.attack_country_npc(child['id'],adult['id'])
   if q.get('reason')!='PROTECTED_MINOR_WEAPON_PURCHASE' or a.get('reason')!='PROTECTED_MINOR_COMBAT' or e.commerce.full_integrity_check(wid)['transactions']!=before:fail.append([seed,'CHILD_POLICY',q,a])
   else:stats['child_weapon_rejections']+=1
  if seed<3120:
   picked=None
   for st in c.world['country']['states']:
    for bb in st['blocks']:
     if bb.get('dungeons'):
      actor=next((x for x in c._all_npc_records() if x['class'] in ('WARRIOR','MERCENARY','MAGE')),None)
      if actor:picked=(bb,bb['dungeons'][0],actor);break
    if picked:break
   if picked:
    bb,d,a=picked;c.relocate_npc(a['id'],bb['id']);en=scene.enter_dungeon(a['id'],d['id'])
    if en.get('status')=='PASS':
     g=next(o for o in d['objects'] if o['object_type']=='GROUND_WEAPON');tk=scene.interact(a['id'],g['id'],'TAKE');eq=br.equip_country_weapon(a['id'],g['item_ref'])
     if tk.get('status')!='PASS' or eq.get('status')!='PASS':fail.append([seed,'SCENE_EQUIP',tk,eq])
     else:stats['scene_weapon_equips']+=1
  integ=br.full_integrity_check();health=e.health_v13(wid)
  if integ['status']!='PASS' or health['status']!='PASS':fail.append([seed,'INTEGRITY',integ.get('failures'),health.get('failures')])
  else:stats['health_pass']+=1
 finally:e.close()
rep={'record_id':'COUNTRY-LIVING-BRIDGE-STRESS-V1.3','status':'PASS' if not fail else 'FAIL','stats':stats,'failure_count':len(fail),'failures':fail[:25],'seconds':round(time.time()-t0,3),'master':'V2.1.0'}
OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(rep,ensure_ascii=False));raise SystemExit(1 if fail else 0)
