from __future__ import annotations
import json, os, sys, tempfile
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,os.path.join(ROOT,'01_RUNTIME'))
from integrated_arpg_engine_v05 import IntegratedARPGEngineV05
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

def main():
    checks=[]
    def ck(name,cond,detail=None): checks.append({'name':name,'status':'PASS' if cond else 'FAIL','detail':detail})
    profiles=[]; total_events=0; total_replays=0
    with tempfile.TemporaryDirectory() as td:
        db=os.path.join(td,'stress.sqlite'); e=IntegratedARPGEngineV05(db,master_release_path=MASTER)
        wid=e.create_world('stage05:stress',57575)['world']['world_instance_id']; it=e.items_arpg(wid)
        for i in range(4):
            p=e.arpg(wid).create_profile(f'local:stress:{i}',origin_mode='CREATED',display_name=f'ItemStress{i}')['profile']; profiles.append(p['profile_ref']); it.ensure_inventory(p['profile_ref'])
        ck('profiles_4',len(profiles)==4)
        weapon_refs=[]
        for i,pref in enumerate(profiles):
            g=it.grant_item(pref,'MIN-IRON',100,event_ref=f's:{i}:iron'); total_events+=1; ck(f'material_{i}',g['status']=='PASS')
            gp=it.grant_item(pref,'ITEM-FOOD',5,event_ref=f's:{i}:food'); total_events+=1; ck(f'food_{i}',gp['status']=='PASS')
            w=it.grant_item(pref,f'WPN-{i+1:03d}',3,event_ref=f's:{i}:weapons'); total_events+=1; ck(f'weapons_{i}',w['status']=='PASS' and len(w['instance_refs'])==3); weapon_refs.append(w['instance_refs'][0])
            replay=it.grant_item(pref,f'WPN-{i+1:03d}',3,event_ref=f's:{i}:weapons'); total_replays+=1 if replay.get('idempotent_replay') else 0; ck(f'weapon_replay_{i}',replay.get('idempotent_replay') is True)
            eq=it.equip(pref,weapon_refs[-1],'MAIN_HAND',event_ref=f's:{i}:equip'); total_events+=1; ck(f'equip_{i}',eq['status']=='PASS')
            stats=e.combat_arpg(wid).player_stats(pref); ck(f'equipment_stats_{i}',isinstance(stats['equipment_modifiers'],dict) and stats['base_damage']>0)
            loss=it.apply_durability_loss(pref,weapon_refs[-1],5,event_ref=f's:{i}:wear'); total_events+=1; ck(f'durability_{i}',loss['status']=='PASS' and loss['after']<loss['before'])
            e.character(wid).apply_health_change(pref,-25,event_ref=f's:{i}:hurt',source_type='STRESS')
            use=it.use_consumable(pref,'ITEM-FOOD',event_ref=f's:{i}:fooduse'); total_events+=1; ck(f'consume_{i}',use['status']=='PASS' and use['remaining_quantity']==4)
            use_r=it.use_consumable(pref,'ITEM-FOOD',event_ref=f's:{i}:fooduse'); total_replays+=1 if use_r.get('idempotent_replay') else 0; ck(f'consume_replay_{i}',use_r.get('idempotent_replay') is True)
        # Ring transfer of materials preserves total quantity.
        for i,pref in enumerate(profiles):
            dest=profiles[(i+1)%len(profiles)]; o=it.transfer_item(pref,dest,'MIN-IRON',20,event_ref=f's:{i}:transfer'); total_events+=1; ck(f'transfer_{i}',o['status']=='PASS')
        total_iron=sum(it.inventory_snapshot(p)['stacks'].get('MIN-IRON',0) for p in profiles); ck('iron_conserved_400',total_iron==400,total_iron)
        # NPC owners use the same item contract.
        npcs=list(e.country(wid)._all_npc_records())[:4]
        for i,n in enumerate(npcs):
            ni=it.ensure_inventory(n['id']); ck(f'npc_inventory_{i}',ni['owner_kind']=='COUNTRY_NPC')
            g=it.grant_item(n['id'],'MIN-COPPER',25,event_ref=f's:npc:{i}:copper'); total_events+=1; ck(f'npc_material_{i}',g['status']=='PASS')
        ck('verify_before_restore',it.verify()['status']=='PASS',it.verify().get('failures')); ck('health_before_restore',e.health_arpg_v05(wid)['status']=='PASS')
        expected={p:it.inventory_snapshot(p) for p in profiles}; e.close()
        e2=IntegratedARPGEngineV05(db,master_release_path=MASTER); e2.resume_world(wid); it2=e2.items_arpg(wid)
        ck('restore_health',e2.health_arpg_v05(wid)['status']=='PASS'); ck('restore_verify',it2.verify()['status']=='PASS')
        for i,p in enumerate(profiles):
            snap=it2.inventory_snapshot(p); ck(f'restore_iron_{i}',snap['stacks']['MIN-IRON']==expected[p]['stacks']['MIN-IRON']); ck(f'restore_equipped_{i}',snap['equipped']['MAIN_HAND']==weapon_refs[i])
        e2.close()
    failed=[x for x in checks if x['status']!='PASS']
    out={'record_id':'ARPG-STAGE05-STRESS-V0.6.0','profiles':4,'npc_owners':4,'item_events':total_events,'idempotent_replays':total_replays,'checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','failures':failed}
    print(json.dumps(out,ensure_ascii=False,indent=2)); return 0 if not failed else 1
if __name__=='__main__': raise SystemExit(main())
