from __future__ import annotations
import collections, json, os, sys, tempfile
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,os.path.join(ROOT,'01_RUNTIME'))
from integrated_arpg_engine_v05 import IntegratedARPGEngineV05
from living_runtime import ValidationError, ConflictError, sha256_text, canonical_json
from arpg_item_core import RARITY_TIERS, AFFIX_POOL, CONSUMABLE_EFFECTS
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

def main():
    checks=[]
    def ck(name,cond,detail=None): checks.append({'name':name,'status':'PASS' if cond else 'FAIL','detail':detail})
    with tempfile.TemporaryDirectory() as td:
        db=os.path.join(td,'v.sqlite'); e=IntegratedARPGEngineV05(db,master_release_path=MASTER)
        wid=e.create_world('stage05:validation',56565)['world']['world_instance_id']; it=e.items_arpg(wid)
        ck('health_v05',e.health_arpg_v05(wid)['status']=='PASS')
        defs=it.list_definitions(); counts=collections.Counter(d['item_kind'] for d in defs)
        ck('definitions_84',len(defs)==84,len(defs)); ck('canon_30',sum(1 for d in defs if d['canonical_identity'])==30)
        ck('derived_54',sum(1 for d in defs if not d['canonical_identity'])==54)
        expected={'WEAPON':34,'MATERIAL':34,'COMPONENT':6,'CONSUMABLE':5,'ARMOR':1,'QUEST_UTILITY':1,'GENERIC':1,'TOOL':1,'UTILITY':1}
        for k,v in expected.items(): ck('kind:'+k,counts[k]==v,counts[k])
        ck('rarity_tiers_5',len(RARITY_TIERS)==5); ck('affix_pool_11',len(AFFIX_POOL)==11); ck('consumables_5',len(CONSUMABLE_EFFECTS)==5)
        w=it.definition('WPN-001'); ck('canon_weapon_name',w['name']=='Bastão de Vigília'); ck('canon_weapon_readonly',w['source_authority']=='MASTER_READ_ONLY')
        row=e.runtime.conn.execute("SELECT payload_json FROM commerce_catalog_snapshots WHERE item_ref='WPN-001'").fetchone(); ck('source_snapshot_hash',w['source_snapshot_hash']==sha256_text(row['payload_json']))
        mineral=it.definition('MIN-IRON'); ck('mineral_material',mineral['item_kind']=='MATERIAL'); ck('mineral_stack',mineral['stackable'] and mineral['stack_max']==999)
        ck('tool_universal',it.definition('ITEM-TOOL')['equip_slots']==['UTILITY']); ck('armor_slot',it.definition('ITEM-ARMOR')['equip_slots']==['CHEST'])
        ck('food_real_item',it.definition('ITEM-FOOD')['item_kind']=='CONSUMABLE'); ck('mana_crystal_primary_not_fixed_mana',it.definition('ITEM-MANA-CRYSTAL')['consumable_effect']['resource_restore']==60.0)
        p=e.arpg(wid).create_profile('local:validation',origin_mode='CREATED',display_name='Validation')['profile']; pref=p['profile_ref']; inv=it.ensure_inventory(pref)
        ck('player_owner_kind',inv['owner_kind']=='PLAYER_PROFILE'); ck('empty_slots',inv['metrics']['used_slots']==0); ck('empty_weight',inv['metrics']['current_weight']==0)
        g=it.grant_item(pref,'MIN-IRON',100,event_ref='v:iron'); ck('stack_grant',g['status']=='PASS' and g['after']==100)
        ck('stack_slots_one',it.inventory_snapshot(pref)['metrics']['used_slots']==1); ck('stack_weight_50',abs(it.inventory_snapshot(pref)['metrics']['current_weight']-50.0)<1e-9)
        gr=it.grant_item(pref,'MIN-IRON',100,event_ref='v:iron'); ck('stack_replay',gr.get('idempotent_replay') is True); ck('stack_no_duplicate',it.inventory_snapshot(pref)['stacks']['MIN-IRON']==100)
        weapon=it.grant_item(pref,'WPN-001',1,event_ref='v:weapon',rarity='EXCEPTIONAL',quality=82); ck('weapon_grant',weapon['status']=='PASS'); inst=weapon['instances'][0]; iref=inst['instance_ref']
        ck('instance_identity',iref.startswith('itm:')); ck('rarity_exceptional',inst['rarity']=='EXCEPTIONAL'); ck('quality_82',inst['quality']==82); ck('affix_count_2',len(inst['affixes'])==2)
        ck('socket_count_1',inst['socket_capacity']==1 and inst['sockets']==[None]); ck('durability_positive',inst['durability']>0); ck('instance_owner',inst['owner_ref']==pref)
        base=e.combat_arpg(wid).player_stats(pref); eq=it.equip(pref,iref,'MAIN_HAND',event_ref='v:equip'); ck('equip_pass',eq['status']=='PASS')
        armed=e.combat_arpg(wid).player_stats(pref); ck('combat_damage_increased',armed['base_damage']>base['base_damage']); ck('equipment_attached',isinstance(armed['equipment_modifiers'],dict))
        full=it.instance(iref)['max_durability']; br=it.apply_durability_loss(pref,iref,full+1,event_ref='v:break'); ck('broken',br['condition']=='BROKEN')
        broken=e.combat_arpg(wid).player_stats(pref); ck('broken_mod_suppressed',broken['base_damage']<armed['base_damage'])
        rp=it.repair_instance(pref,iref,event_ref='v:repair'); ck('repair_pass',rp['status']=='PASS' and rp['economic_cost']=='DEFERRED_STAGE11'); ck('repair_restores_mod',e.combat_arpg(wid).player_stats(pref)['base_damage']>broken['base_damage'])
        it.grant_item(pref,'ITEM-HERB',2,event_ref='v:herbgrant'); e.character(wid).apply_health_change(pref,-70,event_ref='v:hurt',source_type='VALIDATION')
        herb=it.use_consumable(pref,'ITEM-HERB',event_ref='v:herbuse'); ck('herb_use',herb['status']=='PASS' and herb['applied_health']>0 and herb['placeholder_only'] is False)
        it.grant_item(pref,'ITEM-MANA-CRYSTAL',1,event_ref='v:crystalgrant'); e.character(wid).apply_resource_change(pref,-70,event_ref='v:drain',source_type='VALIDATION')
        blocked=it.use_consumable(pref,'ITEM-MANA-CRYSTAL',event_ref='v:crystalblocked'); ck('shared_cooldown',blocked['status']=='REJECTED' and blocked['reason']=='ACTION_COOLDOWN')
        e.resources_arpg(wid).tick_profile(pref,1.0); crystal=it.use_consumable(pref,'ITEM-MANA-CRYSTAL',event_ref='v:crystal'); ck('adaptive_resource_restore',crystal['status']=='PASS' and crystal['applied_resource']>0)
        # Command stream path
        e.resources_arpg(wid).tick_profile(pref,1.0); e.character(wid).apply_health_change(pref,-30,event_ref='v:cmdhurt',source_type='VALIDATION')
        seq=e.arpg(wid)._input(pref)['last_client_sequence']+1; cmd=e.arpg(wid).submit_command('local:validation',pref,seq,'USE_ITEM',{'item_ref':'ITEM-HERB'})
        ck('command_item_route',cmd['status']=='PASS' and cmd['route']=='ITEM'); replay=e.arpg(wid).submit_command('local:validation',pref,seq,'USE_ITEM',{'item_ref':'ITEM-HERB'}); ck('command_replay',replay.get('idempotent_replay') is True)
        # Shared player/NPC contract
        npc=next(e.country(wid)._all_npc_records()); nref=npc['id']; ni=it.ensure_inventory(nref); ck('npc_owner_kind',ni['owner_kind']=='COUNTRY_NPC')
        tr=it.transfer_item(pref,nref,'MIN-IRON',20,event_ref='v:to_npc'); ck('transfer_to_npc',tr['status']=='PASS'); ck('npc_receives_same_item',it.inventory_snapshot(nref)['stacks']['MIN-IRON']==20)
        # Capacity gate on a fresh inventory
        tiny=e.arpg(wid).create_profile('local:tiny',origin_mode='CREATED',display_name='Tiny')['profile']['profile_ref']; it.ensure_inventory(tiny,slot_capacity=1,weight_capacity=1.0)
        cap=it.grant_item(tiny,'WPN-002',1,event_ref='v:cap'); ck('capacity_reject',cap['status']=='REJECTED' and cap['reason']=='INVENTORY_CAPACITY_EXCEEDED'); ck('capacity_no_partial',it.inventory_snapshot(tiny)['metrics']['used_slots']==0)
        singular_block=False
        try: it.grant_item(nref,'WPN-002',1,event_ref='v:singular',rarity='SINGULAR',quality=90)
        except ValidationError: singular_block=True
        ck('singular_requires_authoring',singular_block)
        conflict=False
        it.grant_item(nref,'MIN-GOLD',1,event_ref='v:conflict')
        try: it.grant_item(nref,'MIN-GOLD',2,event_ref='v:conflict')
        except ConflictError: conflict=True
        ck('event_conflict',conflict)
        snap=e.arpg(wid).client_snapshot(pref); ck('snapshot_items',snap['items'] is not None and snap['items']['definition_count']==84)
        ck('verify_items',it.verify()['status']=='PASS',it.verify().get('failures')); ck('health_final',e.health_arpg_v05(wid)['status']=='PASS',e.health_arpg_v05(wid).get('failures'))
        before=it.inventory_snapshot(pref); e.close()
        e2=IntegratedARPGEngineV05(db,master_release_path=MASTER); e2.resume_world(wid); after=e2.items_arpg(wid).inventory_snapshot(pref)
        ck('restore_health',e2.health_arpg_v05(wid)['status']=='PASS'); ck('restore_stack',after['stacks']['MIN-IRON']==80); ck('restore_equipped',after['equipped']['MAIN_HAND']==iref)
        ck('restore_instance',e2.items_arpg(wid).instance(iref)['quality']==82); ck('restore_verify',e2.items_arpg(wid).verify()['status']=='PASS'); e2.close()
    failed=[x for x in checks if x['status']!='PASS']
    out={'record_id':'ARPG-STAGE05-VALIDATION-V0.6.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','failures':failed}
    print(json.dumps(out,ensure_ascii=False,indent=2)); return 0 if not failed else 1
if __name__=='__main__': raise SystemExit(main())
