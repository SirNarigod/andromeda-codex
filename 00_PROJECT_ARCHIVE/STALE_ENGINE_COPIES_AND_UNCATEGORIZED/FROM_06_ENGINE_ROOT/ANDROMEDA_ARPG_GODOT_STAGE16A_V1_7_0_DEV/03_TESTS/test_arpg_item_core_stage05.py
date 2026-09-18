from __future__ import annotations
import os, sys, tempfile, unittest

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT,'01_RUNTIME'))
from integrated_arpg_engine_v05 import IntegratedARPGEngineV05
from living_runtime import ValidationError, ConflictError

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')


class ItemStage05Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); cls.db=os.path.join(cls.tmp.name,'world.sqlite')
        cls.engine=IntegratedARPGEngineV05(cls.db, master_release_path=MASTER)
        out=cls.engine.create_world('stage05:test',50505); cls.wid=out['world']['world_instance_id']
        created=cls.engine.arpg(cls.wid).create_profile('local:test',origin_mode='CREATED',display_name='ItemTester')
        cls.pref=created['profile']['profile_ref']; cls.avatar=created['profile']['avatar_ref']
        cls.items=cls.engine.items_arpg(cls.wid); cls.items.ensure_inventory(cls.pref)

    @classmethod
    def tearDownClass(cls):
        cls.engine.close(); cls.tmp.cleanup()

    def test_01_health_and_catalog(self):
        self.assertEqual(self.engine.health_arpg_v05(self.wid)['status'],'PASS')
        defs=self.items.list_definitions(); self.assertEqual(len(defs),84)
        self.assertEqual(sum(1 for d in defs if d['canonical_identity']),30)
        self.assertEqual(sum(1 for d in defs if not d['canonical_identity']),54)

    def test_02_definition_preserves_identity_and_classifies(self):
        w=self.items.definition('WPN-001'); self.assertEqual(w['name'],'Bastão de Vigília')
        self.assertTrue(w['canonical_identity']); self.assertEqual(w['source_authority'],'MASTER_READ_ONLY'); self.assertEqual(w['item_kind'],'WEAPON')
        m=self.items.definition('MIN-IRON'); self.assertFalse(m['canonical_identity']); self.assertEqual(m['item_kind'],'MATERIAL'); self.assertTrue(m['stackable'])
        self.assertEqual(self.items.definition('ITEM-TOOL')['item_kind'],'TOOL')
        self.assertEqual(self.items.definition('ITEM-ARMOR')['equip_slots'],['CHEST'])

    def test_03_inventory_empty_and_capacity_contract(self):
        inv=self.items.inventory_snapshot(self.pref)
        self.assertEqual(inv['owner_kind'],'PLAYER_PROFILE'); self.assertEqual(inv['metrics']['used_slots'],0)
        self.assertEqual(inv['slot_capacity'],60); self.assertEqual(inv['weight_capacity'],100.0)
        self.assertEqual(inv['shared_owner_contract'],'PLAYER_AND_NPC_COMPATIBLE_STAGE09')

    def test_04_stack_grant_replay(self):
        out=self.items.grant_item(self.pref,'MIN-IRON',12,event_ref='u05:stack')
        self.assertEqual(out['status'],'PASS'); self.assertEqual(out['after'],12)
        replay=self.items.grant_item(self.pref,'MIN-IRON',12,event_ref='u05:stack')
        self.assertTrue(replay['idempotent_replay']); self.assertEqual(self.items.inventory_snapshot(self.pref)['stacks']['MIN-IRON'],12)

    def test_05_unique_instance_rarity_quality_affix_socket(self):
        out=self.items.grant_item(self.pref,'WPN-001',1,event_ref='u05:weapon',rarity='EXCEPTIONAL',quality=80)
        self.assertEqual(out['status'],'PASS'); inst=out['instances'][0]; self.__class__.weapon_ref=inst['instance_ref']
        self.assertEqual(inst['rarity'],'EXCEPTIONAL'); self.assertEqual(inst['quality'],80); self.assertEqual(len(inst['affixes']),2)
        self.assertEqual(inst['socket_capacity'],1); self.assertEqual(inst['sockets'],[None]); self.assertGreater(inst['max_durability'],0)

    def test_06_equip_modifies_combat(self):
        before_engine=IntegratedARPGEngineV05
        base=self.engine.combat_arpg(self.wid).player_stats(self.pref)['base_damage']
        eq=self.items.equip(self.pref,self.weapon_ref,'MAIN_HAND',event_ref='u05:equip')
        self.assertEqual(eq['status'],'PASS')
        after=self.engine.combat_arpg(self.wid).player_stats(self.pref)
        self.assertGreater(after['base_damage'],base); self.assertIsInstance(after['equipment_modifiers'],dict)
        self.assertEqual(after['equipment_modifiers']['equipped'][0]['item_ref'],'WPN-001')

    def test_07_durability_break_suppresses_and_repair_restores(self):
        inst=self.items.instance(self.weapon_ref); full=inst['max_durability']
        b=self.items.apply_durability_loss(self.pref,self.weapon_ref,full+1,event_ref='u05:break')
        self.assertEqual(b['condition'],'BROKEN')
        mods=self.items.equipment_modifiers(self.pref); self.assertFalse(mods['equipped'][0]['applied'])
        damaged_stats=self.engine.combat_arpg(self.wid).player_stats(self.pref)
        r=self.items.repair_instance(self.pref,self.weapon_ref,event_ref='u05:repair')
        self.assertEqual(r['status'],'PASS'); self.assertEqual(self.items.instance(self.weapon_ref)['condition'],'INTACT')
        repaired_stats=self.engine.combat_arpg(self.wid).player_stats(self.pref); self.assertGreater(repaired_stats['base_damage'],damaged_stats['base_damage'])

    def test_08_slot_compatibility_and_armor(self):
        out=self.items.grant_item(self.pref,'ITEM-ARMOR',1,event_ref='u05:armor',rarity='ATTUNED',quality=70); ar=out['instance_refs'][0]
        bad=self.items.equip(self.pref,ar,'MAIN_HAND',event_ref='u05:armorbad'); self.assertEqual(bad['reason'],'ITEM_SLOT_INCOMPATIBLE')
        ok=self.items.equip(self.pref,ar,'CHEST',event_ref='u05:armorok'); self.assertEqual(ok['status'],'PASS')
        self.assertGreater(self.engine.combat_arpg(self.wid).player_stats(self.pref)['armor'],0)

    def test_09_real_consumable_uses_item_stack_and_shared_cooldown(self):
        self.items.grant_item(self.pref,'ITEM-FOOD',2,event_ref='u05:foodgrant')
        self.engine.character(self.wid).apply_health_change(self.pref,-60,event_ref='u05:damage',source_type='TEST')
        out=self.items.use_consumable(self.pref,'ITEM-FOOD',event_ref='u05:fooduse')
        self.assertEqual(out['status'],'PASS'); self.assertFalse(out['placeholder_only']); self.assertGreater(out['applied_health'],0)
        self.assertEqual(out['remaining_quantity'],1)
        self.items.grant_item(self.pref,'ITEM-WATER',1,event_ref='u05:watergrant')
        self.engine.character(self.wid).apply_resource_change(self.pref,-20,event_ref='u05:drain',source_type='TEST')
        blocked=self.items.use_consumable(self.pref,'ITEM-WATER',event_ref='u05:waterblocked')
        self.assertEqual(blocked['status'],'REJECTED'); self.assertEqual(blocked['reason'],'ACTION_COOLDOWN')
        self.engine.resources_arpg(self.wid).tick_profile(self.pref,1.0)
        ok=self.items.use_consumable(self.pref,'ITEM-WATER',event_ref='u05:waterok'); self.assertEqual(ok['status'],'PASS'); self.assertGreater(ok['applied_resource'],0)

    def test_10_no_effect_does_not_consume(self):
        self.engine.resources_arpg(self.wid).tick_profile(self.pref,1.0)
        c=self.engine.character(self.wid); st=c.state(self.pref); missing=st['derived']['max_health']-st['vitals']['health']
        if missing>0: c.apply_health_change(self.pref,missing,event_ref='u05:topoff',source_type='TEST')
        before=self.items.inventory_snapshot(self.pref)['stacks']['ITEM-FOOD']
        out=self.items.use_consumable(self.pref,'ITEM-FOOD',event_ref='u05:noeffect')
        self.assertEqual(out['status'],'REJECTED'); self.assertEqual(out['reason'],'ITEM_USE_NO_EFFECT')
        self.assertEqual(self.items.inventory_snapshot(self.pref)['stacks']['ITEM-FOOD'],before)

    def test_11_game_core_use_item_command_and_replay(self):
        self.engine.resources_arpg(self.wid).tick_profile(self.pref,1.0)
        self.engine.character(self.wid).apply_health_change(self.pref,-30,event_ref='u05:cmddmg',source_type='TEST')
        seq=self.engine.arpg(self.wid)._input(self.pref)['last_client_sequence']+1
        out=self.engine.arpg(self.wid).submit_command('local:test',self.pref,seq,'USE_ITEM',{'item_ref':'ITEM-FOOD'})
        self.assertEqual(out['status'],'PASS'); self.assertEqual(out['route'],'ITEM')
        replay=self.engine.arpg(self.wid).submit_command('local:test',self.pref,seq,'USE_ITEM',{'item_ref':'ITEM-FOOD'})
        self.assertTrue(replay['idempotent_replay'])

    def test_12_transfer_stack_shared_contract(self):
        p2=self.engine.arpg(self.wid).create_profile('local:recv',origin_mode='CREATED',display_name='Receiver')['profile']; self.__class__.recv=p2['profile_ref']
        self.items.ensure_inventory(self.recv)
        before=self.items.inventory_snapshot(self.pref)['stacks']['MIN-IRON']
        out=self.items.transfer_item(self.pref,self.recv,'MIN-IRON',5,event_ref='u05:transferstack')
        self.assertEqual(out['status'],'PASS'); self.assertEqual(self.items.inventory_snapshot(self.recv)['stacks']['MIN-IRON'],5)
        self.assertEqual(self.items.inventory_snapshot(self.pref)['stacks']['MIN-IRON'],before-5)

    def test_13_transfer_unique_requires_unequip(self):
        blocked=self.items.transfer_item(self.pref,self.recv,'WPN-001',1,event_ref='u05:transferblocked',instance_ref=self.weapon_ref)
        self.assertEqual(blocked['reason'],'ITEM_INSTANCE_EQUIPPED')
        self.items.unequip(self.pref,'MAIN_HAND',event_ref='u05:uneq')
        ok=self.items.transfer_item(self.pref,self.recv,'WPN-001',1,event_ref='u05:transferunique',instance_ref=self.weapon_ref)
        self.assertEqual(ok['status'],'PASS'); self.assertEqual(self.items.instance(self.weapon_ref)['owner_ref'],self.recv)

    def test_14_country_npc_uses_same_inventory_contract(self):
        npc=next(self.engine.country(self.wid)._all_npc_records()); nref=npc['id']
        inv=self.items.ensure_inventory(nref); self.assertEqual(inv['owner_kind'],'COUNTRY_NPC')
        out=self.items.grant_item(nref,'MIN-COPPER',3,event_ref='u05:npcgrant'); self.assertEqual(out['status'],'PASS')
        self.assertEqual(self.items.inventory_snapshot(nref)['stacks']['MIN-COPPER'],3)

    def test_15_weight_capacity_rejects_without_partial_grant(self):
        p=self.engine.arpg(self.wid).create_profile('local:tinyw',origin_mode='CREATED',display_name='TinyWeight')['profile']; pref=p['profile_ref']
        self.items.ensure_inventory(pref,slot_capacity=10,weight_capacity=1.0)
        out=self.items.grant_item(pref,'WPN-002',1,event_ref='u05:weightfail')
        self.assertEqual(out['status'],'REJECTED'); self.assertEqual(out['reason'],'INVENTORY_CAPACITY_EXCEEDED')
        self.assertEqual(self.items.inventory_snapshot(pref)['metrics']['used_slots'],0)

    def test_16_stack_slot_capacity_uses_stack_max(self):
        p=self.engine.arpg(self.wid).create_profile('local:tinys',origin_mode='CREATED',display_name='TinySlots')['profile']; pref=p['profile_ref']
        self.items.ensure_inventory(pref,slot_capacity=1,weight_capacity=1000)
        ok=self.items.grant_item(pref,'MIN-STONE',999,event_ref='u05:stack999'); self.assertEqual(ok['status'],'PASS')
        bad=self.items.grant_item(pref,'MIN-STONE',1,event_ref='u05:stack1000'); self.assertEqual(bad['status'],'REJECTED')
        self.assertEqual(bad['reason'],'INVENTORY_CAPACITY_EXCEEDED')

    def test_17_singular_auto_generation_blocked(self):
        with self.assertRaises(ValidationError):
            self.items.grant_item(self.recv,'WPN-002',1,event_ref='u05:singular',rarity='SINGULAR',quality=90)

    def test_18_event_ref_conflict_detected(self):
        self.items.grant_item(self.recv,'MIN-GOLD',1,event_ref='u05:conflict')
        with self.assertRaises(ConflictError): self.items.grant_item(self.recv,'MIN-GOLD',2,event_ref='u05:conflict')

    def test_19_socket_framework_does_not_invent_rune_application(self):
        out=self.items.grant_item(self.recv,'WPN-003',1,event_ref='u05:socketitem',rarity='RELIC',quality=90)
        inst=out['instances'][0]; self.assertEqual(inst['socket_capacity'],2); self.assertEqual(inst['sockets'],[None,None])
        self.assertEqual(inst['socket_binding'],'EMPTY_SOCKET_FRAMEWORK_STAGE05')
        self.assertEqual(self.items.definition('WPN-003')['socket_support']['augmentation_binding'],'DEFERRED_TO_RUNE_SKILL_WORK_INTEGRATION')

    def test_20_client_snapshot_contains_itemization(self):
        snap=self.engine.arpg(self.wid).client_snapshot(self.recv)
        self.assertIsNotNone(snap['items']); self.assertEqual(snap['items']['definition_count'],84)
        self.assertEqual(snap['items']['authority'],'ARPG_ITEMIZATION_GAMEPLAY_DERIVATION')

    def test_21_verify(self):
        # Item integrity is the unit scope. Full Stage05/global health is already exercised
        # by validation, stress, bootstrap and persistence-resume gates; repeating it here
        # makes this unit suite pay the full country relationship-integrity scan again.
        self.assertEqual(self.items.verify()['status'],'PASS')


class ItemStage05PersistenceTests(unittest.TestCase):
    def test_22_persistence_resume(self):
        with tempfile.TemporaryDirectory() as td:
            db=os.path.join(td,'persist.sqlite'); e=IntegratedARPGEngineV05(db,master_release_path=MASTER)
            wid=e.create_world('stage05:persist',55055)['world']['world_instance_id']
            p=e.arpg(wid).create_profile('local:persist',origin_mode='CREATED',display_name='Persist')['profile']; pref=p['profile_ref']
            it=e.items_arpg(wid); it.ensure_inventory(pref)
            g=it.grant_item(pref,'WPN-004',1,event_ref='persist:weapon',rarity='EXCEPTIONAL',quality=88); iref=g['instance_refs'][0]
            it.equip(pref,iref,'MAIN_HAND',event_ref='persist:equip'); it.grant_item(pref,'MIN-TITAN',17,event_ref='persist:mineral')
            before=it.inventory_snapshot(pref); e.close()
            e2=IntegratedARPGEngineV05(db,master_release_path=MASTER); e2.resume_world(wid); after=e2.items_arpg(wid).inventory_snapshot(pref)
            self.assertEqual(after['stacks']['MIN-TITAN'],17); self.assertEqual(after['equipped']['MAIN_HAND'],iref)
            self.assertEqual(after['instances'][0]['rarity'],before['instances'][0]['rarity'])
            self.assertEqual(e2.health_arpg_v05(wid)['status'],'PASS'); e2.close()

if __name__=='__main__': unittest.main(verbosity=2)
