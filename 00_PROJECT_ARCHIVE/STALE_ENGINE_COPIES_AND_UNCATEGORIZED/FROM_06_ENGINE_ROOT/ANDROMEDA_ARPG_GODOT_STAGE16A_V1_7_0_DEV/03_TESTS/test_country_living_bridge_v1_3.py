import os, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v13 import IntegratedLivingEngineV13
from integrated_engine import IntegratedLivingEngineV11
from living_runtime import LivingRuntime, ValidationError
from atlas_living_bridge import AtlasLivingBridge

MASTER=os.environ.get('ANDROMEDA_MASTER_V201','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
MASTER20=MASTER
MASTER_SHA='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2'

class BridgeV13(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=os.path.join(self.tmp.name,'v13.db')
        self.e=IntegratedLivingEngineV13(self.db,master_release_path=MASTER)
        self.r=self.e.create_world('v13-test',1201,load_relationships=False); self.wid=self.r['world']['world_instance_id']; self.c=self.e.country(self.wid); self.brg=self.e.bridge(self.wid)
    def tearDown(self):
        try:self.e.close()
        except:pass
        self.tmp.cleanup()

    def _trade_hunt_context(self):
        for st in self.c.world['country']['states']:
            for b in st['blocks']:
                pred=next((f for f in b['fauna'] if f['role']=='PREDATOR' and f['count']>0),None)
                for city in b['cities']:
                    npc=next((n for n in city['npcs'] if n['class']!='CHILD' and n['protection']['combat_targetable']),None)
                    shop=next((sh for sh in city['shops'] if any(k.startswith('WPN-') and v>0 for k,v in sh['inventory'].items())),None)
                    if pred and npc and shop:
                        wpn=next(k for k,v in shop['inventory'].items() if k.startswith('WPN-') and v>0)
                        return b,city,npc,shop,pred,wpn
        self.fail('no trade+hunt context')

    def test_bootstrap_v201_and_catalog84(self):
        self.assertEqual(self.r['version'],'V1.3.0'); self.assertEqual(self.e.runtime.master_version,'V2.0.1'); self.assertEqual(self.e.runtime.master_release_sha256,MASTER_SHA)
        self.assertEqual(self.r['commerce']['count'],84); self.assertEqual(self.r['country_living_bridge']['status'],'PASS'); self.assertEqual(self.e.health_v13(self.wid)['status'],'PASS')
        self.assertFalse(self.e.runtime.canonical_ref_resolves('WPN-DNG-SWORD-001')); self.assertEqual(self.e.commerce.catalog_item('WPN-DNG-SWORD-001').get('canonical_status'),'DERIVED_GAMEPLAY_NOT_CANON')

    def test_country_purchase_delegates_and_conserves_money(self):
        b,city,n,sh,f,wpn=self._trade_hunt_context(); nb=float(n['wallet']['balance']); sb=float(sh['wallet']['balance']); stock=sh['inventory'][wpn]
        out=self.c.purchase(sh['id'],n['id'],wpn,1)
        self.assertEqual(out['status'],'PASS',out); self.assertEqual(out['engine'],'CommerceSystem'); self.assertEqual(out['money_conservation_delta'],0.0)
        self.assertAlmostEqual(nb+sb,float(n['wallet']['balance'])+float(sh['wallet']['balance']),places=2); self.assertEqual(sh['inventory'][wpn],stock-1); self.assertEqual(n['inventory'][wpn],1)
        events=[r['event_type'] for r in self.e.runtime.conn.execute('SELECT event_type FROM events WHERE world_instance_id=? ORDER BY sequence',(self.wid,)).fetchall()]
        self.assertIn('COMMERCE_PURCHASE',events); self.assertNotIn('SHOP_PURCHASED',events)
        self.assertEqual(self.brg.full_integrity_check()['status'],'PASS')

    def test_hunt_uses_combat_corpse_loot_and_witness_memory(self):
        b,city,n,sh,f,wpn=self._trade_hunt_context(); self.assertEqual(self.c.purchase(sh['id'],n['id'],wpn,1)['status'],'PASS')
        before=f['count']; out=self.c.hunt_fauna(b['id'],f['id'],1,n['id'])
        self.assertEqual(out['status'],'PASS',out); self.assertEqual(out['engine'],'CombatSystem'); self.assertEqual(out['killed'],1); self.assertEqual(f['count'],before-1); self.assertGreater(out['witness_memory_count'],0)
        kill=out['kills'][0]; self.assertTrue(kill['corpse_ref']); self.assertTrue(kill['loot']['item_ref'].startswith('ITEM-FAUNA-')); self.assertGreater(n['inventory'][kill['loot']['item_ref']],0)
        events=[r['event_type'] for r in self.e.runtime.conn.execute('SELECT event_type FROM events WHERE world_instance_id=? ORDER BY sequence',(self.wid,)).fetchall()]
        self.assertIn('COMBAT_RESOLVED',events); self.assertIn('CORPSE_HARVESTED',events); self.assertNotIn('FAUNA_HUNTED',events)
        self.assertEqual(self.brg.full_integrity_check()['status'],'PASS')

    def test_child_hunt_rejected_without_spawn(self):
        child=next(n for n in self.c._all_npc_records() if n['class']=='CHILD')
        b=self.c.block(child['block_id']); f=next(x for x in b['fauna'] if x['count']>0); before=f['count']; animals_before=sum(1 for x in self.e.runtime.list_entities(self.wid) if x['entity_kind']=='ANIMAL')
        out=self.c.hunt_fauna(b['id'],f['id'],1,child['id']); self.assertEqual(out['status'],'REJECTED'); self.assertEqual(out['reason'],'PROTECTED_MINOR_COMBAT'); self.assertEqual(f['count'],before)
        animals_after=sum(1 for x in self.e.runtime.list_entities(self.wid) if x['entity_kind']=='ANIMAL'); self.assertEqual(animals_before,animals_after)

    def test_scene_weapon_imports_then_equips_in_combat(self):
        scene=self.e.scenes(self.wid); chosen=None
        for st in self.c.world['country']['states']:
            for b in st['blocks']:
                if not b.get('dungeons'): continue
                actor=next((n for n in self.c._all_npc_records() if n['class'] in ('WARRIOR','MERCENARY','MAGE') and n['id']),None)
                if actor:
                    chosen=(b,b['dungeons'][0],actor); break
            if chosen:break
        b,d,n=chosen; self.c.relocate_npc(n['id'],b['id']); self.assertEqual(scene.enter_dungeon(n['id'],d['id'])['status'],'PASS')
        ground=next(o for o in d['objects'] if o['object_type']=='GROUND_WEAPON'); item=ground['item_ref']; self.assertEqual(scene.interact(n['id'],ground['id'],'TAKE')['status'],'PASS')
        eq=self.brg.equip_country_weapon(n['id'],item); self.assertEqual(eq['status'],'PASS',eq); self.assertEqual(self.e.combat.equipped_weapon(self.wid,self.brg.ensure_npc(n['id'])['entity_runtime_id'])['data']['item_ref'],item)
        self.assertEqual(self.brg.full_integrity_check()['status'],'PASS')

    def test_child_cannot_buy_equip_or_initiate_weapon_combat(self):
        ctx=None
        for st in self.c.world['country']['states']:
            for b in st['blocks']:
                for cy in b['cities']:
                    child=next((n for n in cy['npcs'] if n['class']=='CHILD'),None)
                    adult=next((n for n in cy['npcs'] if n['class'] not in ('CHILD','WORKER') and n['protection']['combat_targetable']),None)
                    shop=next((sh for sh in cy['shops'] if any(k.startswith('WPN-') and v>0 for k,v in sh['inventory'].items())),None)
                    if child and adult and shop:
                        item=next(k for k,v in shop['inventory'].items() if k.startswith('WPN-') and v>0); ctx=(child,adult,shop,item); break
                if ctx: break
            if ctx: break
        child,adult,shop,item=ctx
        before_tx=self.e.commerce.full_integrity_check(self.wid)['transactions']
        p=self.c.purchase(shop['id'],child['id'],item,1); self.assertEqual(p['status'],'REJECTED'); self.assertEqual(p['reason'],'PROTECTED_MINOR_WEAPON_PURCHASE')
        self.assertEqual(self.e.commerce.full_integrity_check(self.wid)['transactions'],before_tx)
        child['inventory'][item]=1
        q=self.brg.equip_country_weapon(child['id'],item); self.assertEqual(q['status'],'REJECTED'); self.assertEqual(q['reason'],'PROTECTED_MINOR_COMBAT')
        a=self.brg.attack_country_npc(child['id'],adult['id']); self.assertEqual(a['status'],'REJECTED'); self.assertEqual(a['reason'],'PROTECTED_MINOR_COMBAT')
        events=[r['event_type'] for r in self.e.runtime.conn.execute('SELECT event_type FROM events WHERE world_instance_id=? ORDER BY sequence',(self.wid,)).fetchall()]
        self.assertNotIn('COMBAT_RESOLVED',events)

    def test_remote_purchase_rejected_before_runtime_mutation(self):
        b,city,n,sh,f,wpn=self._trade_hunt_context(); other=next(x for st in self.c.world['country']['states'] for x in st['blocks'] if x['id']!=b['id'])
        self.c.relocate_npc(n['id'],other['id']); before_tx=self.e.commerce.full_integrity_check(self.wid)['transactions']; out=self.c.purchase(sh['id'],n['id'],wpn,1)
        self.assertEqual(out['status'],'REJECTED'); self.assertEqual(out['reason'],'ACTOR_NOT_IN_SHOP_CITY'); self.assertEqual(self.e.commerce.full_integrity_check(self.wid)['transactions'],before_tx)

    def test_relationship_loader_accepts_v201_verified_baseline(self):
        r=self.e.consequences.load_master_relationships(self.wid,limit=25); self.assertEqual(r['inserted'],25); self.assertEqual(self.e.consequences.full_integrity_check(self.wid)['status'],'PASS')

    def test_atlas_bridge_accepts_v201(self):
        self.e.runtime.conn.execute('PRAGMA wal_checkpoint(FULL)')
        a=AtlasLivingBridge(self.db,MASTER)
        try:self.assertEqual(a.master_release_sha256,MASTER_SHA)
        finally:a.close()

class Compatibility(unittest.TestCase):
    def test_runtime_v20_and_v13_supported(self):
        rt=LivingRuntime(':memory:',master_release_path=MASTER20)
        try:self.assertEqual(rt.master_version,'V2.0.1'); self.assertFalse(rt.canonical_ref_resolves('WPN-DNG-SWORD-001'))
        finally:rt.close()
        e=IntegratedLivingEngineV13(':memory:',master_release_path=MASTER20)
        try:
            r=e.create_world('v13-v201',1201,load_relationships=False); self.assertEqual(r['version'],'V1.3.0'); self.assertEqual(e.health_v13(r['world']['world_instance_id'])['status'],'PASS')
        finally:e.close()

    def test_v11_original_engine_still_boots_v20(self):
        e=IntegratedLivingEngineV11(':memory:',master_release_path=MASTER20)
        try:
            r=e.create_world('legacy',2201,load_relationships=False); self.assertEqual(r['status'],'PASS'); self.assertEqual(r['commerce']['count'],30)
        finally:e.close()

if __name__=='__main__':unittest.main()
