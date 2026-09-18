import os, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from country_scale import CountryScaleSystem
from scene_interaction import SceneInteractionSystem
from content_catalog import validate_catalog, DUNGEON_WEAPONS, RESOURCE_CATALOG, name_status
from integrated_engine_v12 import IntegratedLivingEngineV12

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

class SceneInteractionTests(unittest.TestCase):
    def setUp(self):
        self.c=CountryScaleSystem(master_release_path=MASTER,seed=1201)
        self.s=SceneInteractionSystem(self.c)

    def _all_npcs(self):
        return list(self.c._all_npc_records())

    def _root_dungeon(self):
        for st in self.c.world['country']['states']:
            for b in st['blocks']:
                if b['root_deep'] and b.get('dungeons'):
                    return b,b['dungeons'][0]
        self.fail('root dungeon missing')

    def test_catalog_and_names(self):
        self.assertEqual(validate_catalog()['status'],'PASS')
        self.assertGreaterEqual(len(RESOURCE_CATALOG),16)
        unnamed=[]
        for st in self.c.world['country']['states']:
            for rec in [st]:
                if not rec.get('name'): unnamed.append(rec['id'])
            for b in st['blocks']:
                for rec in [b,*b['resources'],*b['industries'],*b['flora'],*b['fauna'],*b['bridges'],*b.get('kingdoms',[])]:
                    if rec.get('id') and not rec.get('name'): unnamed.append(rec['id'])
                for sub in b['subregions']:
                    if not sub.get('name'): unnamed.append(sub['id'])
                for c in b['cities']:
                    if not c.get('name'): unnamed.append(c['id'])
                    for sh in c['shops']:
                        if not sh.get('name'): unnamed.append(sh['id'])
                    for n in c['npcs']:
                        if not n.get('name'): unnamed.append(n['id'])
                for realm in b.get('kingdoms',[]):
                    for leg in realm.get('legendary_creatures',[]):
                        if not leg.get('name'): unnamed.append(leg['id'])
        self.assertEqual(unnamed,[])

    def test_sparse_purposeful_resource_distribution(self):
        blocks=[b for st in self.c.world['country']['states'] for b in st['blocks']]
        sets=[frozenset(r['id'] for r in b['resources']) for b in blocks]
        self.assertGreater(len(set(sets)),1)
        self.assertTrue(all(len(s)<len(RESOURCE_CATALOG) for s,b in zip(sets,blocks) if not b['root_deep']))
        for b in blocks:
            ids={r['id'] for r in b['resources']}
            self.assertEqual('MIN-ROOT-SHARD' in ids,bool(b['root_deep']))
        tech=next(st for st in self.c.world['country']['states'] if st['archetype']=='TECHNOLOGY')
        self.assertTrue(all('MIN-MAGNETITE' in {r['id'] for r in b['resources']} for b in tech['blocks']))

    def test_scene_validation_and_required_dungeon_weapons(self):
        v=self.s.validate(); self.assertEqual(v['status'],'PASS',v)
        self.assertGreater(v['dungeons'],0)
        self.assertGreater(v['objects'],0)
        self.assertTrue(all(v['weapon_family_hits'][x]>0 for x in ('SWORD','CROSSBOW','BOW','WHIP')))

    def test_dark_dungeon_interactions_and_inventory_propagation(self):
        block,d=self._root_dungeon()
        actor=next(n for n in self._all_npcs() if n['class'] in ('WARRIOR','MERCENARY','MAGE'))
        self.assertEqual(self.c.relocate_npc(actor['id'],block['id'])['status'],'PASS')
        self.assertEqual(self.s.enter_dungeon(actor['id'],d['id'])['status'],'PASS')
        book=next(o for o in d['objects'] if o['object_type']=='BOOK')
        if d['darkness_level']>=70:
            self.assertEqual(self.s.interact(actor['id'],book['id'],'READ')['reason'],'INSUFFICIENT_LIGHT')
        torch=next(o for o in d['objects'] if o['object_type']=='TORCH')
        before_torch=self.c.world['country']['inventory']['scene_items'].get('ITEM-TORCH',0)
        self.assertEqual(self.s.interact(actor['id'],torch['id'],'TAKE')['status'],'PASS')
        self.assertEqual(self.c.world['country']['inventory']['scene_items'].get('ITEM-TORCH',0),before_torch-1)
        self.assertEqual(self.s.interact(actor['id'],torch['id'],'LIGHT')['status'],'PASS')
        self.assertEqual(self.s.interact(actor['id'],book['id'],'READ')['status'],'PASS')
        self.assertIn(book['knowledge_tag'],actor['knowledge_tags'])

        chest=next(o for o in d['objects'] if o['object_type']=='CHEST')
        self.assertEqual(self.s.interact(actor['id'],chest['id'],'OPEN')['status'],'PASS')
        self.assertEqual(self.s.interact(actor['id'],chest['id'],'LOOT')['status'],'PASS')
        trap=next(o for o in d['objects'] if o['object_type']=='TRAPDOOR')
        self.assertEqual(self.s.interact(actor['id'],trap['id'],'OPEN')['status'],'PASS')

        chair=next(o for o in d['objects'] if o['object_type']=='CHAIR')
        self.assertEqual(self.s.interact(actor['id'],chair['id'],'SIT')['status'],'PASS')
        self.assertEqual(chair['occupied_by'],actor['id'])
        self.assertEqual(self.s.interact(actor['id'],chair['id'],'STAND')['status'],'PASS')

        ground=next(o for o in d['objects'] if o['object_type']=='GROUND_WEAPON')
        item=ground['item_ref']; before=self.c.world['country']['inventory']['dungeon_weapons'].get(item,0)
        self.assertGreater(before,0)
        out=self.s.interact(actor['id'],ground['id'],'TAKE'); self.assertEqual(out['status'],'PASS')
        self.assertEqual(self.c.world['country']['inventory']['dungeon_weapons'].get(item,0),before-1)
        self.assertGreaterEqual(actor['inventory'][item],1)
        self.assertTrue(any(x['source_object_id']==ground['id'] for x in actor['item_instances']))
        eq=self.s.equip_carried_weapon(actor['id'],item); self.assertEqual(eq['status'],'PASS',eq)
        self.assertEqual(actor['equipped_weapon']['item_ref'],item)
        self.assertTrue(all(0<=v<=100 for v in actor['equipped_weapon']['stats'].values()))
        self.assertEqual(self.s.unequip_carried_weapon(actor['id'])['status'],'PASS')
        self.assertIsNone(actor['equipped_weapon'])

    def test_protected_npcs_cannot_enter_hazardous_dungeon(self):
        block,d=self._root_dungeon()
        child=next(n for n in self._all_npcs() if n['class']=='CHILD')
        worker=next(n for n in self._all_npcs() if n['class']=='WORKER')
        self.c.relocate_npc(child['id'],block['id']); self.c.relocate_npc(worker['id'],block['id'])
        self.assertEqual(self.s.enter_dungeon(child['id'],d['id'])['reason'],'PROTECTED_MINOR_DUNGEON')
        self.assertEqual(self.s.enter_dungeon(worker['id'],d['id'])['reason'],'PROTECTED_WORKER_HAZARDOUS_DUNGEON')

    def test_locality_rejects_remote_scene_interaction(self):
        block,d=self._root_dungeon(); book=next(o for o in d['objects'] if o['object_type']=='BOOK')
        actor=next(n for n in self._all_npcs() if n['block_id']!=block['id'] and n['class']!='CHILD')
        out=self.s.interact(actor['id'],book['id'],'READ')
        self.assertEqual(out['status'],'REJECTED'); self.assertEqual(out['reason'],'ACTOR_NOT_IN_BLOCK')

    def test_carried_torch_remains_usable_after_leaving_source_scene(self):
        block,d=self._root_dungeon(); actor=next(n for n in self._all_npcs() if n['class'] in ('WARRIOR','MERCENARY','MAGE'))
        self.c.relocate_npc(actor['id'],block['id']); self.s.enter_dungeon(actor['id'],d['id'])
        torch=next(o for o in d['objects'] if o['object_type']=='TORCH')
        self.assertEqual(self.s.interact(actor['id'],torch['id'],'TAKE')['status'],'PASS')
        self.s.leave_dungeon(actor['id'])
        other=next(b for st in self.c.world['country']['states'] for b in st['blocks'] if b['id']!=block['id'])
        self.c.relocate_npc(actor['id'],other['id'])
        self.assertEqual(self.s.inventory_light(actor['id'],'LIGHT')['status'],'PASS')
        self.assertEqual(actor['active_light'],'ITEM-TORCH')
        self.assertEqual(self.s.inventory_light(actor['id'],'EXTINGUISH')['status'],'PASS')
        self.assertIsNone(actor['active_light'])

    def test_npc_inventory_moves_with_current_location(self):
        actor=next(n for n in self._all_npcs() if n['class'] not in ('CHILD','WORKER'))
        source=actor['block_id']; source_state=actor['state_id']; unit=sum(actor['inventory'].values())
        dest=next(b for st in self.c.world['country']['states'] for b in st['blocks'] if b['id']!=source and b['state_id']!=source_state)
        before_src=sum(self.c.block(source)['inventory']['npc_items'].values())
        before_dst=sum(dest['inventory']['npc_items'].values())
        self.c.relocate_npc(actor['id'],dest['id'])
        self.assertEqual(sum(self.c.block(source)['inventory']['npc_items'].values()),before_src-unit)
        self.assertEqual(sum(dest['inventory']['npc_items'].values()),before_dst+unit)

    def test_country_purchase_charges_currency_and_conserves_local_money(self):
        city=next(cy for st in self.c.world['country']['states'] for b in st['blocks'] for cy in b['cities'] if cy['shops'] and any(n['class']!='CHILD' for n in cy['npcs']))
        buyer=next(n for n in city['npcs'] if n['class']!='CHILD'); shop=city['shops'][0]
        item=next(k for k,v in shop['inventory'].items() if v>0)
        quote=self.c.quote_country_item(shop['id'],buyer['id'],item,1); self.assertEqual(quote['status'],'PASS'); self.assertGreater(quote['unit_price'],0)
        before_b=float(buyer['wallet']['balance']); before_s=float(shop['wallet']['balance']); before_total=round(before_b+before_s,2)
        out=self.c.purchase(shop['id'],buyer['id'],item,1); self.assertEqual(out['status'],'PASS',out)
        self.assertEqual(round(before_b-out['total_price'],2),buyer['wallet']['balance'])
        self.assertEqual(round(before_s+out['total_price'],2),shop['wallet']['balance'])
        self.assertEqual(round(buyer['wallet']['balance']+shop['wallet']['balance'],2),before_total)

    def test_integrated_scene_persistence_and_health(self):
        e=IntegratedLivingEngineV12(':memory:',master_release_path=MASTER)
        try:
            r=e.create_world('SCENE_TEST',1201,load_relationships=False); wid=r['world']['world_instance_id']
            self.assertEqual(r['scene_interaction']['status'],'PASS')
            self.assertEqual(e.health_v12(wid)['status'],'PASS')
            self.assertEqual(e.country(wid).persistence_integrity()['status'],'PASS')
        finally:
            e.close()

if __name__=='__main__': unittest.main()
