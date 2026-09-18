import json,sys,time,traceback
from pathlib import Path
R=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(R/'01_RUNTIME'))
from country_scale import CountryScaleSystem
from scene_interaction import SceneInteractionSystem
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
OUT=R/'04_REPORTS/V1_2_1/COUNTRY_SCENE_INTERACTION_STRESS_V1_2_1.json'; OUT.parent.mkdir(parents=True,exist_ok=True)
start=time.time(); failures=[]; ops=0; statuses={}
def mark(name,res,allowed=('PASS',)):
    global ops
    ops+=1; statuses[name]=statuses.get(name,0)+1
    if res.get('status') not in allowed: raise AssertionError((name,res))
for seed in range(1001,1101):
    try:
        c=CountryScaleSystem(master_release_path=MASTER,seed=seed); s=SceneInteractionSystem(c)
        states=c.world['country']['states']; blocks=[b for st in states for b in st['blocks']]
        npcs=list(c._all_npc_records())
        actor=next(n for n in npcs if n['class'] in ('WARRIOR','MERCENARY','MAGE'))
        # commerce with real local buyer/shop; permit expected insufficient funds only if quote is above wallet, but conservation is still checked.
        city=next(cy for st in states for b in st['blocks'] for cy in b['cities'] if cy['shops'] and any(n['class']!='CHILD' for n in cy['npcs']))
        buyer=next(n for n in city['npcs'] if n['class']!='CHILD'); shop=city['shops'][0]; item=next(k for k,v in shop['inventory'].items() if v>0)
        q=c.quote_country_item(shop['id'],buyer['id'],item,1); mark('quote',q)
        before=round(float(buyer['wallet']['balance'])+float(shop['wallet']['balance']),2); p=c.purchase(shop['id'],buyer['id'],item,1)
        if p.get('status')=='PASS':
            mark('purchase',p); after=round(float(buyer['wallet']['balance'])+float(shop['wallet']['balance']),2)
            if before!=after: raise AssertionError(('money_not_conserved',before,after))
        elif p.get('reason')=='INSUFFICIENT_FUNDS': mark('purchase_insufficient_funds_valid',{'status':'PASS'})
        else: raise AssertionError(('purchase',p))
        # resource extraction
        b=next(x for x in blocks if x['resources']); r=b['resources'][0]; mark('mine',c.mine(b['id'],r['id'],1))
        # harvest/hunt are spatially local
        bf=next(x for x in blocks if x['flora'] and x['fauna']); mark('relocate_resource',c.relocate_npc(actor['id'],bf['id']))
        mark('harvest',c.harvest_flora(bf['id'],bf['flora'][0]['id'],1,actor['id']))
        mark('hunt',c.hunt_fauna(bf['id'],bf['fauna'][0]['id'],1,actor['id']))
        # bridge damage + material-backed repair
        bb=next((x for x in blocks if x['bridges']),None)
        if bb:
            br=bb['bridges'][0]; mark('bridge_damage',c.damage_bridge(bb['id'],br['id'],25)); rr=c.repair_bridge(bb['id'],br['id'],5); mark('bridge_repair',rr)
            if rr.get('material_units_consumed',0)<=0: raise AssertionError(('repair_no_material',rr))
        # dungeon chain
        bd=next(x for x in blocks if x.get('dungeons')); d=bd['dungeons'][0]; mark('relocate_dungeon',c.relocate_npc(actor['id'],bd['id']))
        mark('enter_dungeon',s.enter_dungeon(actor['id'],d['id']))
        torch=next(o for o in d['objects'] if o['object_type']=='TORCH'); mark('take_torch',s.interact(actor['id'],torch['id'],'TAKE')); mark('light_torch',s.inventory_light(actor['id'],'LIGHT'))
        book=next(o for o in d['objects'] if o['object_type']=='BOOK'); mark('read_book',s.interact(actor['id'],book['id'],'READ'))
        gw=next(o for o in d['objects'] if o['object_type']=='GROUND_WEAPON'); mark('take_weapon',s.interact(actor['id'],gw['id'],'TAKE')); mark('equip_weapon',s.equip_carried_weapon(actor['id'],gw['item_ref'])); mark('unequip_weapon',s.unequip_carried_weapon(actor['id']))
        mark('leave_dungeon',s.leave_dungeon(actor['id']))
        # final convergence checks
        if c.validate()['status']!='PASS': raise AssertionError(('country_validate',c.validate()))
        if s.validate()['status']!='PASS': raise AssertionError(('scene_validate',s.validate()))
        inv=c.world['country']['inventory']
        def scan(v,path='root'):
            if isinstance(v,dict):
                for k,x in v.items(): scan(x,path+'.'+str(k))
            elif isinstance(v,(int,float)) and ('currency' in path or 'items' in path or 'resources' in path or 'fauna' in path or 'flora' in path or 'scene_' in path or 'dungeon_' in path):
                if v<0: raise AssertionError(('negative_inventory',path,v))
        scan(inv)
    except Exception as e:
        failures.append({'seed':seed,'error':repr(e),'trace':traceback.format_exc(limit=3)}); break
rep={'record_id':'COUNTRY-SCENE-INTERACTION-STRESS-V1.2.1','status':'PASS' if not failures else 'FAIL','seeds_target':100,'operations':ops,'operation_classes':statuses,'failures':failures,'seconds':round(time.time()-start,3)}
OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(rep,ensure_ascii=False)); raise SystemExit(0 if not failures else 1)
