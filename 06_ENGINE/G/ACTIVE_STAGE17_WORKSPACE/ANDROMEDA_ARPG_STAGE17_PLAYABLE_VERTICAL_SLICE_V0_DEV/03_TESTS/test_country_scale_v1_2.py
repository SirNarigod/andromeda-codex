import os, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from country_scale import CountryScaleSystem, STATE_ARCHETYPES, SHOP_KINDS, NPC_CLASSES
from mar_balance import MARCanonBalance
from integrated_engine_v12 import IntegratedLivingEngineV12

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

class CountryScaleTests(unittest.TestCase):
    def setUp(self):
        self.s=CountryScaleSystem(master_release_path=MASTER,seed=1201)

    def test_hierarchy_and_scale(self):
        v=self.s.validate(); self.assertEqual(v['status'],'PASS',v)
        c=self.s.world['country']; self.assertGreater(c['area_km2_approx'],1_000_000)
        self.assertEqual({x['archetype'] for x in c['states']},{x[0] for x in STATE_ARCHETYPES})
        for st in c['states']:
            self.assertTrue(1<=len(st['blocks'])<=5)
            for b in st['blocks']:
                self.assertTrue(1<=len(b['subregions'])<=3)

    def test_root_deep_predator_only(self):
        roots=[b for s in self.s.world['country']['states'] for b in s['blocks'] if b['root_deep']]
        self.assertTrue(roots)
        for b in roots:
            self.assertTrue(b['biome']['predator_only']); self.assertFalse(b['flora']); self.assertFalse(b['cities']); self.assertFalse(b['industries'])
            self.assertTrue(all(x['role']=='PREDATOR' for x in b['fauna']))
            for a in b['fauna']:
                p=a['combat_profile']; self.assertTrue(all(0<=p[k]<=100 for k in ('size','damage','resistance','venom','corruption')))

    def test_inventory_reconciliation(self):
        c=self.s.world['country']
        for st in c['states']:
            for b in st['blocks']:
                for key in ('resources','flora','fauna'):
                    recon={}
                    for sub in b['subregions']:
                        for x,v in sub['inventory'][key].items(): recon[x]=recon.get(x,0)+v
                    self.assertEqual(recon,b['inventory'][key])
        # state sum -> country sum for resource/flora/fauna
        for key in ('resources','flora','fauna','shop_items','npc_items','industry_stock','bridge_resources'):
            recon={}
            for st in c['states']:
                for x,v in st['inventory'][key].items(): recon[x]=recon.get(x,0)+v
            self.assertEqual(recon,c['inventory'][key])

    def test_protected_classes(self):
        npcs=[n for s in self.s.world['country']['states'] for b in s['blocks'] for c in b['cities'] for n in c['npcs']]
        child=next(n for n in npcs if n['class']=='CHILD'); worker=next(n for n in npcs if n['class']=='WORKER')
        self.assertFalse(self.s.can_target(child['id'])['allowed'])
        self.assertEqual(self.s.assign_labor(child['id'],hazardous=True)['status'],'REJECTED')
        self.assertEqual(self.s.assign_labor(worker['id'],hazardous=True)['status'],'REJECTED')
        self.assertEqual(self.s.assign_labor(worker['id'],hazardous=False)['status'],'PASS')

    def test_local_actions_propagate_to_country(self):
        c=self.s.world['country']
        nonroot=next(b for s in c['states'] for b in s['blocks'] if not b['root_deep'] and b['cities'] and b['flora'] and b['industries'])
        actor=next(n for city in nonroot['cities'] for n in city['npcs'] if n['class']!='CHILD')
        res=nonroot['industries'][0]['resource_id']; before=c['inventory']['resources'][res]
        out=self.s.mine(nonroot['id'],res,17); self.assertEqual(out['status'],'PASS'); self.assertEqual(self.s.world['country']['inventory']['resources'][res],before-17)
        f=nonroot['flora'][0]; fref=f['species_ref']; beforef=self.s.world['country']['inventory']['flora'][fref]
        out=self.s.harvest_flora(nonroot['id'],f['id'],9,actor['id']); self.assertEqual(out['status'],'PASS'); self.assertEqual(self.s.world['country']['inventory']['flora'][fref],beforef-9)
        fauna=next(a for a in nonroot['fauna'] if a['count']>3); aref=fauna['species_ref']; beforea=self.s.world['country']['inventory']['fauna'][aref]
        out=self.s.hunt_fauna(nonroot['id'],fauna['id'],2,actor['id']); self.assertEqual(out['status'],'PASS'); self.assertEqual(self.s.world['country']['inventory']['fauna'][aref],beforea-2)
        self.assertEqual(self.s.validate()['status'],'PASS')

    def test_shop_purchase_propagates(self):
        c=self.s.world['country']; city=next(cy for s in c['states'] for b in s['blocks'] for cy in b['cities'] if cy['shops'])
        shop=city['shops'][0]; item=next(k for k,v in shop['inventory'].items() if v>0); actor=next(n for n in city['npcs'] if n['class']!='CHILD')
        before_shop=c['inventory']['shop_items'].get(item,0); before_npc=c['inventory']['npc_items'].get(item,0)
        out=self.s.purchase(shop['id'],actor['id'],item,1); self.assertEqual(out['status'],'PASS')
        self.assertEqual(self.s.world['country']['inventory']['shop_items'].get(item,0),before_shop-1)
        self.assertEqual(self.s.world['country']['inventory']['npc_items'].get(item,0),before_npc+1)

    def test_bridge_high_resource_and_durability(self):
        bridges=[(b,br) for s in self.s.world['country']['states'] for b in s['blocks'] for br in b['bridges']]
        self.assertTrue(bridges)
        b,br=bridges[0]; self.assertEqual(br['tier'],'ALTO'); self.assertGreaterEqual(br['durability_max'],7000)
        before=br['durability']; r=self.s.damage_bridge(b['id'],br['id'],1000); self.assertEqual(r['durability'],before-1000)
        mats_before=sum(br['inventory'].values()); r=self.s.repair_bridge(b['id'],br['id'],200); self.assertGreater(r['durability'],before-1000)
        self.assertEqual(sum(br['inventory'].values()),mats_before-r['material_units_consumed'])
        mats_after=sum(br['inventory'].values()); r2=self.s.repair_bridge(b['id'],br['id'],200)
        self.assertEqual(r2['restored'],0); self.assertEqual(r2['material_units_consumed'],0); self.assertEqual(sum(br['inventory'].values()),mats_after)

    def test_mar_balance_canon_layer(self):
        m=MARCanonBalance(MASTER); v=m.validate(); self.assertEqual(v['status'],'PASS',v); self.assertEqual(v['count'],30)
        self.assertGreater(v['class_counts']['BAIXO'],0); self.assertGreater(v['class_counts']['MÉDIO'],0); self.assertGreater(v['class_counts']['ALTO'],0)
        self.assertTrue(all(r['canonical_status']=='CÂNONE_AUTORIZADO' for r in m.records))

    def test_integrated_persistence(self):
        e=IntegratedLivingEngineV12(':memory:',master_release_path=MASTER)
        try:
            r=e.create_world('TEST',1201,load_relationships=False); wid=r['world']['world_instance_id']; cs=e.country(wid)
            city=next(cy for s in cs.world['country']['states'] for b in s['blocks'] for cy in b['cities'] if cy['shops'])
            shop=city['shops'][0]; actor=next(n for n in city['npcs'] if n['class']!='CHILD'); item=next(iter(shop['inventory']))
            cs.purchase(shop['id'],actor['id'],item,1)
            self.assertEqual(cs.persistence_integrity()['status'],'PASS'); self.assertGreaterEqual(cs.persistence_integrity()['events'],2)
            self.assertEqual(e.health_v12(wid)['status'],'PASS')
        finally:e.close()

if __name__=='__main__': unittest.main()
