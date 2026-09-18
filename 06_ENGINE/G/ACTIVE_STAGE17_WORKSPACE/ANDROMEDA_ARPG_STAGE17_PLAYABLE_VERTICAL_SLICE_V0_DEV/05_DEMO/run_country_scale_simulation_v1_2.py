from pathlib import Path
import os,sys,json
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v12 import IntegratedLivingEngineV12
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
DB=os.environ.get('ANDROMEDA_COUNTRY_DB',str(ROOT/'04_REPORTS/V1_2_0/COUNTRY_SIM_V1_2.sqlite'))
Path(DB).parent.mkdir(parents=True,exist_ok=True)
try: Path(DB).unlink()
except FileNotFoundError: pass
engine=IntegratedLivingEngineV12(DB,master_release_path=MASTER)
boot=engine.create_world('RTE-00-COUNTRY-SIM',1201,load_relationships=False); wid=boot['world']['world_instance_id']; cs=engine.country(wid); c=cs.world['country']

# Representative inventories and entities
states=[{'id':st['id'],'archetype':st['archetype'],'tier':st['tier'],'blocks':st['block_count'],'inventory':st['inventory']} for st in c['states']]
root=next(b for st in c['states'] for b in st['blocks'] if b['root_deep'])
normal=next(b for st in c['states'] for b in st['blocks'] if (not b['root_deep']) and b['cities'] and b['flora'] and b['industries'])
city=normal['cities'][0]; local_actor=next(n for n in city['npcs'] if n['class'] not in ('CHILD',))
child=next(n for st in c['states'] for b in st['blocks'] for cy in b['cities'] for n in cy['npcs'] if n['class']=='CHILD')
worker=next(n for st in c['states'] for b in st['blocks'] for cy in b['cities'] for n in cy['npcs'] if n['class']=='WORKER')
warrior=next(n for st in c['states'] for b in st['blocks'] for cy in b['cities'] for n in cy['npcs'] if n['class'] in ('WARRIOR','MERCENARY'))
classes={cls:next(n for st in c['states'] for b in st['blocks'] for cy in b['cities'] for n in cy['npcs'] if n['class']==cls) for cls in ('MAGE','NATIVE','ROBOT','WARRIOR','MERCENARY','WORKER','CHILD')}

before={
 'country_resources':dict(c['inventory']['resources']),'country_flora':dict(c['inventory']['flora']),'country_fauna':dict(c['inventory']['fauna']),
 'country_shop_items':dict(c['inventory']['shop_items']),'country_npc_items':dict(c['inventory']['npc_items']),
 'normal_block_inventory':json.loads(json.dumps(normal['inventory'])),'normal_subregion_inventories':[json.loads(json.dumps(s['inventory'])) for s in normal['subregions']],
}

# Protection tests
protection={
 'child_target':cs.can_target(child['id']),
 'child_hazardous_labor':cs.assign_labor(child['id'],hazardous=True),
 'worker_hazardous_labor':cs.assign_labor(worker['id'],hazardous=True),
 'worker_safe_labor':cs.assign_labor(worker['id'],hazardous=False),
}

# Local inventory interactions
res=normal['industries'][0]['resource_id']; mining=cs.mine(normal['id'],res,23)
flora=normal['flora'][0]
# Ensure actor is physically local for harvest; normal city actor is local by construction.
harvest=cs.harvest_flora(normal['id'],flora['id'],11,local_actor['id'])
fauna=next(a for a in normal['fauna'] if a['count']>=3); hunt_local=cs.hunt_fauna(normal['id'],fauna['id'],1,local_actor['id'])
shop=city['shops'][0]; item=next(k for k,v in shop['inventory'].items() if v>0); purchase_local=cs.purchase(shop['id'],local_actor['id'],item,1)
# Remote purchase must fail after actor leaves city.
move_to_root=cs.relocate_npc(warrior['id'],root['id'])
remote_purchase=cs.purchase(shop['id'],warrior['id'],item,1)
root_pred=next(a for a in root['fauna'] if a['role']=='PREDATOR' and a['count']>0); root_hunt=cs.hunt_fauna(root['id'],root_pred['id'],1,warrior['id'])

# Bridge durability test
bridge_pair=next((b,br) for st in c['states'] for b in st['blocks'] for br in b['bridges'])
bridge_block,bridge=bridge_pair; bridge_before=bridge['durability']; bridge_damage=cs.damage_bridge(bridge_block['id'],bridge['id'],1250); bridge_repair=cs.repair_bridge(bridge_block['id'],bridge['id'],100)

# Reconcile and inspect hierarchy after mutations
cs.reconcile_country_inventory(); after={
 'country_resources':dict(c['inventory']['resources']),'country_flora':dict(c['inventory']['flora']),'country_fauna':dict(c['inventory']['fauna']),
 'country_shop_items':dict(c['inventory']['shop_items']),'country_npc_items':dict(c['inventory']['npc_items']),
 'normal_block_inventory':json.loads(json.dumps(normal['inventory'])),'normal_subregion_inventories':[json.loads(json.dumps(s['inventory'])) for s in normal['subregions']],
}
realms=[{'state_id':st['id'],'block_id':b['id'],'realm':k} for st in c['states'] for b in st['blocks'] for k in b.get('kingdoms',[])]
# Explicit inventory examples by requested NPC category
npc_inventory_examples={k:{'id':v['id'],'tier':v['tier'],'location':{'state_id':v['state_id'],'block_id':v['block_id'],'city_id':v['city_id']},'inventory':v['inventory'],'protection':v['protection']} for k,v in classes.items()}
report={
 'record_id':'RTE00-COUNTRY-SCALE-SIM-V1.2','status':'PASS','engine_version':engine.VERSION,'world_instance_id':wid,
 'country':{'name':c['name'],'source_territory_id':c['source_territory_id'],'area_km2_approx':c['area_km2_approx'],'story_binding_note':c['kenua_story_binding']},
 'coordinate_scale':cs.coordinate_scale_report(),'states':states,'country_inventory':c['inventory'],'root_deep':{'block_id':root['id'],'biome':root['biome'],'fauna':root['fauna'],'flora_count':len(root['flora']),'city_count':len(root['cities'])},
 'magic_realms':realms,'npc_inventory_examples':npc_inventory_examples,'protection_tests':protection,
 'interactions':{'mining':mining,'harvest':harvest,'local_hunt':hunt_local,'local_purchase':purchase_local,'move_to_root':move_to_root,'remote_purchase':remote_purchase,'root_hunt':root_hunt,'bridge_before':bridge_before,'bridge_damage':bridge_damage,'bridge_repair':bridge_repair},
 'before':before,'after':after,'mar':engine.mar_balance.export(),'country_validation':cs.validate(),'persistence':cs.persistence_integrity(),'health':engine.health_v12(wid),
}
# Result is FAIL if any expected policy failed to enforce.
assert protection['child_target']['allowed'] is False
assert protection['child_hazardous_labor']['status']=='REJECTED'
assert protection['worker_hazardous_labor']['status']=='REJECTED'
assert remote_purchase['status']=='REJECTED' and remote_purchase['reason']=='ACTOR_NOT_IN_SHOP_CITY'
assert root_hunt['status']=='PASS'
assert report['country_validation']['status']=='PASS'
assert report['health']['status']=='PASS'
path=ROOT/'04_REPORTS/V1_2_0'; path.mkdir(parents=True,exist_ok=True); (path/'COUNTRY_SCALE_SIMULATION_V1_2.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':'PASS','world':wid,'states':len(c['states']),'blocks':sum(len(s['blocks']) for s in c['states']),'subregions':sum(len(b['subregions']) for s in c['states'] for b in s['blocks']),'root_blocks':sum(1 for s in c['states'] for b in s['blocks'] if b['root_deep']),'country_inventory':c['inventory'],'protection_tests':protection,'interaction_statuses':{k:(v.get('status') if isinstance(v,dict) else None) for k,v in report['interactions'].items()},'health':report['health']['status'],'persistence_events':report['persistence']['events']},ensure_ascii=False,indent=2))
engine.close()
