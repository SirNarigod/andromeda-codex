from __future__ import annotations
import os, pathlib, tempfile, unittest, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'01_RUNTIME'))
from integrated_arpg_engine_v16a import IntegratedARPGEngineV16A

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

class Stage16AWaterBagSurvivalV08Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); td=pathlib.Path(cls.tmp.name)
        cls.e=IntegratedARPGEngineV16A(str(td/'world.sqlite'),master_release_path=MASTER,save_root=td/'saves')
        out=cls.e.create_world('stage16a:v08',160800); cls.wid=out['world']['world_instance_id']
        cls.pr=cls.e.arpg(cls.wid).create_profile('stage16a:v08',display_name='Water Bag Tester')['profile']['profile_ref']
        cls.s=cls.e.stage16a(cls.wid); cls.wb=cls.s.water_bag; cls.items=cls.e.items_arpg(cls.wid)
        cls.items.ensure_inventory(cls.pr)
        defs=cls.items.list_definitions()
        cls.weapons=[d for d in defs if d.get('item_kind')=='WEAPON'][:2]
        cls.armor=next(d for d in defs if d.get('item_kind')=='ARMOR' and d.get('equip_slots'))
        cls.weapon_refs=[]
        for i,d in enumerate(cls.weapons,1):
            cls.weapon_refs.append(cls.items.grant_item(cls.pr,d['item_ref'],1,event_ref=f'v08:weapon:{i}')['instance_refs'][0])
        ar=cls.items.grant_item(cls.pr,cls.armor['item_ref'],1,event_ref='v08:armor')['instance_refs'][0]
        cls.armor_ref=ar
        cls.items.equip(cls.pr,ar,cls.armor['equip_slots'][0],event_ref='v08:armor:equip')
        cls.s.assign_weapon_slot(cls.pr,1,cls.weapon_refs[0],event_ref='v08:wslot:1')
        cls.s.assign_weapon_slot(cls.pr,2,cls.weapon_refs[1],event_ref='v08:wslot:2')
        cls.s.activate_weapon_slot(cls.pr,1,event_ref='v08:wslot:active')
    @classmethod
    def tearDownClass(cls):
        cls.e.runtime.close(); cls.tmp.cleanup()

    def test_01_contract_water_and_bag_rules(self):
        c=self.wb.contract()
        self.assertEqual(900.0,c['water_loot']['individual_item_ttl_s'])
        self.assertEqual(1800.0,c['water_loot']['bag_ttl_s'])
        self.assertIsNone(c['water_loot']['land_bag_ttl'])
        self.assertFalse(c['water']['balance_body_system'])
        self.assertTrue(c['ownership']['player_can_recover_npc_bag'])

    def test_02_shallow_water_player_crossing(self):
        x=self.wb.water_traversal_sample(actor_kind='PLAYER',depth_m=.35,flow_speed_mps=.2,distance_m=10,load_fraction=.2)
        self.assertEqual('PASS',x['status']); self.assertEqual('WADE',x['mode']); self.assertGreater(x['stamina_cost'],0)

    def test_03_strong_current_costs_more(self):
        calm=self.wb.water_traversal_sample(actor_kind='PLAYER',depth_m=.4,flow_speed_mps=.2,distance_m=10,load_fraction=.2)
        strong=self.wb.water_traversal_sample(actor_kind='PLAYER',depth_m=.4,flow_speed_mps=1.6,distance_m=10,load_fraction=.2)
        self.assertGreater(strong['stamina_cost'],calm['stamina_cost']); self.assertEqual('STRONG_CURRENT',strong['flow_class'])

    def test_04_under_bridge_shallow_is_traversable(self):
        x=self.wb.water_traversal_sample(actor_kind='NPC',depth_m=.4,flow_speed_mps=.7,distance_m=8,load_fraction=.1,under_bridge=True)
        self.assertEqual('PASS',x['status']); self.assertTrue(x['under_bridge']); self.assertEqual('WADE',x['mode'])

    def test_05_deep_water_swim_costs_more_than_shallow(self):
        a=self.wb.water_traversal_sample(actor_kind='ANIMAL',depth_m=.4,flow_speed_mps=.3,distance_m=10,load_fraction=0)
        b=self.wb.water_traversal_sample(actor_kind='ANIMAL',depth_m=1.4,flow_speed_mps=.3,distance_m=10,load_fraction=0)
        self.assertEqual('SWIM',b['mode']); self.assertGreater(b['stamina_cost'],a['stamina_cost'])

    def test_06_vehicle_shallow_passes_without_stamina(self):
        x=self.wb.water_traversal_sample(actor_kind='VEHICLE',depth_m=.3,flow_speed_mps=.5,distance_m=12,load_fraction=0)
        self.assertEqual('PASS',x['status']); self.assertEqual(0.0,x['stamina_cost']); self.assertLess(x['speed_factor'],1.0)

    def test_07_vehicle_deep_water_blocked(self):
        x=self.wb.water_traversal_sample(actor_kind='VEHICLE',depth_m=1.0,flow_speed_mps=.2,distance_m=12,load_fraction=0)
        self.assertEqual('BLOCKED',x['status']); self.assertEqual('VEHICLE_WATER_TOO_DEEP',x['reason'])

    def test_08_player_water_traversal_spends_real_stamina(self):
        avatar=self.e.arpg(self.wid).profile(self.pr)['avatar_ref']
        before=self.e.movement(self.wid).state(avatar)['stamina']
        out=self.s.water_traversal_effect(self.pr,depth_m=.35,flow_speed_mps=.5,distance_m=5,under_bridge=True,event_ref='v08:water:spend')
        after=self.e.movement(self.wid).state(avatar)['stamina']
        self.assertEqual('PASS',out['status']); self.assertLess(after,before)

    def test_09_bag_is_real_container_and_retains_equipped_gear(self):
        out=self.s.equip_bag(self.pr,event_ref='v08:bag:equip')
        self.assertEqual('PASS',out['status']); self.__class__.bag_ref=out['bag_ref']
        bag_inv=self.items.inventory_snapshot(self.bag_ref)
        player_inv=self.items.inventory_snapshot(self.pr)
        self.assertEqual('STAGE16A_BAG_CONTAINER',bag_inv['owner_kind'])
        self.assertIn(self.weapon_refs[0],player_inv['instance_refs']); self.assertIn(self.weapon_refs[1],player_inv['instance_refs'])
        self.assertIn(self.armor_ref,player_inv['instance_refs'])

    def test_10_pickup_routes_into_equipped_bag(self):
        player_before=self.items.inventory_snapshot(self.pr)['metrics']['current_weight']
        out=self.wb.grant_carried_item(self.pr,'ITEM-GRAIN',3,event_ref='v08:bag:grain')
        self.assertEqual('PASS',out['status']); self.assertEqual(self.bag_ref,out['effective_inventory_owner_ref'])
        self.assertEqual(3,self.items.inventory_snapshot(self.bag_ref)['stacks'].get('ITEM-GRAIN'))
        metrics=self.wb.carry_metrics(self.pr)
        self.assertEqual(self.bag_ref,metrics['bag_ref'])
        self.assertGreater(metrics['current_weight'],player_before)
        self.assertEqual(metrics['current_weight'],self.s._inventory_metrics(self.pr)['current_weight'])

    def test_11_quest_item_can_be_in_bag(self):
        out=self.wb.grant_carried_item(self.pr,'ITEM-OLD-KEY',1,event_ref='v08:bag:quest')
        self.assertEqual('PASS',out['status']); self.assertEqual(1,self.items.inventory_snapshot(self.bag_ref)['stacks'].get('ITEM-OLD-KEY'))
        economy=self.e.economy_arpg(self.wid)
        economy.ensure_wallet(self.pr,1000.0)
        vendor=next(v for v in economy.list_vendors() if v['location_ref']=='POI-002')
        profile_before=int(self.items.inventory_snapshot(self.pr).get('stacks',{}).get('ITEM-GRAIN',0))
        bag_before=int(self.items.inventory_snapshot(self.bag_ref).get('stacks',{}).get('ITEM-GRAIN',0))
        q=economy.price_quote(self.pr,vendor['vendor_ref'],'ITEM-GRAIN',1,direction='BUY',event_ref='v08:bag:trade:quote')['quote']['quote_ref']
        trade=self.s.execute_trade_carried(self.pr,q,event_ref='v08:bag:trade:buy')
        self.assertEqual('PASS',trade['status']); self.assertEqual(self.bag_ref,trade['inventory_owner_ref'])
        self.assertEqual(profile_before,int(self.items.inventory_snapshot(self.pr).get('stacks',{}).get('ITEM-GRAIN',0)))
        self.assertEqual(bag_before+1,int(self.items.inventory_snapshot(self.bag_ref).get('stacks',{}).get('ITEM-GRAIN',0)))

    def test_12_water_death_drops_floating_bag_and_protects_quest_item(self):
        out=self.s.drop_bag_for_death(self.pr,in_water=True,position={'iso_x_m':4,'iso_y_m':5,'altitude_m':0},event_ref='v08:death:bag')
        self.assertTrue(out['bag_dropped']); b=out['bag']; self.assertEqual('DROPPED_WATER_FLOATING',b['state']); self.assertEqual('FLOATING',b['float_state'])
        self.assertEqual(1800.0,b['water_ttl_s']); self.assertEqual(1,self.items.inventory_snapshot(self.pr)['stacks'].get('ITEM-OLD-KEY'))
        inv=self.items.inventory_snapshot(self.pr); self.assertIn(self.weapon_refs[0],inv['instance_refs']); self.assertIn(self.weapon_refs[1],inv['instance_refs']); self.assertIn(self.armor_ref,inv['instance_refs'])

    def test_13_water_bag_survives_before_30_min(self):
        self.s.advance_water_time(1799,event_ref='v08:time:1799')
        self.assertEqual('DROPPED_WATER_FLOATING',self.wb.bag(self.bag_ref)['state'])

    def test_14_water_bag_sinks_at_30_min(self):
        self.s.advance_water_time(1,event_ref='v08:time:1')
        self.assertEqual('SUNK',self.wb.bag(self.bag_ref)['state'])

    def test_15_individual_ground_item_water_ttl_15_min(self):
        d=self.s.ground_loot.spawn_drop(source_ref='SRC',source_kind='ROCK',item_ref='ITEM-GRAIN',item_kind='MATERIAL',quantity=1,candidate_position={'iso_x_m':0,'iso_y_m':0,'altitude_m':0},event_ref='v08:waterdrop:spawn')['drop_ref']
        self.s.confirm_drop_settled(d,settled_position={'iso_x_m':0,'iso_y_m':0,'altitude_m':0},reachable=True,event_ref='v08:waterdrop:settle')
        self.s.mark_drop_in_water(d,in_water=True,flow_speed_mps=.8,event_ref='v08:waterdrop:mark')
        self.s.advance_water_time(899,event_ref='v08:waterdrop:t899'); self.assertEqual('ACTIVE',self.s.ground_loot.drop(d)['state'])
        self.s.advance_water_time(1,event_ref='v08:waterdrop:t1'); self.assertEqual('SUNK',self.s.ground_loot.drop(d)['state'])

    def test_16_land_bag_has_no_expiry(self):
        p=self.e.arpg(self.wid).create_profile('stage16a:v08:land',display_name='Land Bag')['profile']['profile_ref']
        self.items.ensure_inventory(p); b=self.s.equip_bag(p,event_ref='v08:landbag:equip')['bag_ref']
        self.wb.grant_carried_item(p,'ITEM-GRAIN',2,event_ref='v08:landbag:item')
        self.s.drop_bag_for_death(p,in_water=False,position={'iso_x_m':1,'iso_y_m':2,'altitude_m':0},event_ref='v08:landbag:drop')
        self.s.advance_water_time(100000,event_ref='v08:landbag:time')
        st=self.wb.bag(b); self.assertEqual('DROPPED_LAND',st['state']); self.assertIsNone(st['water_ttl_s'])

    def test_17_player_can_recover_npc_bag_and_property_is_preserved(self):
        npc=next(n['id'] for n in self.e.country(self.wid)._all_npc_records())
        self.items.ensure_inventory(npc); nb=self.s.equip_bag(npc,event_ref='v08:npcbag:equip')['bag_ref']
        self.wb.grant_carried_item(npc,'ITEM-GRAIN',1,event_ref='v08:npcbag:item')
        self.s.drop_bag_for_death(npc,in_water=False,position={'iso_x_m':3,'iso_y_m':3,'altitude_m':0},event_ref='v08:npcbag:drop')
        out=self.s.recover_bag(nb,self.pr,claimant_kind='PLAYER',event_ref='v08:npcbag:recover')
        self.assertEqual('PASS',out['status']); self.assertEqual('FOREIGN_PROPERTY',out['ownership']); self.assertEqual(npc,out['property_owner_ref']); self.assertFalse(out['auto_theft'])

    def test_18_foreign_npc_cannot_auto_take_other_npc_bag(self):
        npc1,npc2=[n['id'] for n in list(self.e.country(self.wid)._all_npc_records())[:2]]
        self.items.ensure_inventory(npc1); b=self.s.equip_bag(npc1,event_ref='v08:npc2:equip')['bag_ref']
        self.s.drop_bag_for_death(npc1,in_water=False,position={'iso_x_m':0,'iso_y_m':0,'altitude_m':0},event_ref='v08:npc2:drop')
        out=self.s.recover_bag(b,npc2,claimant_kind='NPC',event_ref='v08:npc2:recover')
        self.assertEqual('REJECTED',out['status']); self.assertEqual('FOREIGN_NPC_BAG_RECOVERY_NOT_ENABLED',out['reason'])

    def test_19_zero_stamina_water_has_grace_before_defeat(self):
        p=self.e.arpg(self.wid).create_profile('stage16a:v08:exhaust',display_name='Exhaust Tester')['profile']['profile_ref']
        self.items.ensure_inventory(p); b=self.s.equip_bag(p,event_ref='v08:exhaust:bag')['bag_ref']; self.__class__.exhaust_pr=p; self.__class__.exhaust_bag=b
        a=self.s.water_exhaustion_tick(p,actor_kind='PLAYER',stamina=0,in_water=True,delta_s=2,event_ref='v08:exhaust:2',position={'iso_x_m':8,'iso_y_m':8,'altitude_m':0})
        self.assertEqual('ALIVE',a['life_state']); self.assertFalse(a['defeat_required'])

    def test_20_zero_stamina_water_can_defeat_and_drop_bag(self):
        a=self.s.water_exhaustion_tick(self.exhaust_pr,actor_kind='PLAYER',stamina=0,in_water=True,delta_s=2.1,event_ref='v08:exhaust:2.1',position={'iso_x_m':8,'iso_y_m':8,'altitude_m':0})
        self.assertEqual('DEFEATED',a['life_state']); self.assertTrue(a['defeat_required']); self.assertTrue(a['bag_drop']['bag_dropped'])
        self.assertEqual('DEAD',self.e.character(self.wid).ensure_profile(self.exhaust_pr)['vitals']['life_state'])

    def test_21_stamina_recovery_resets_water_exhaustion_counter(self):
        npc=next(n['id'] for n in list(self.e.country(self.wid)._all_npc_records())[3:])
        self.s.water_exhaustion_tick(npc,actor_kind='NPC',stamina=0,in_water=True,delta_s=2,event_ref='v08:npcx:1')
        b=self.s.water_exhaustion_tick(npc,actor_kind='NPC',stamina=5,in_water=True,delta_s=.1,event_ref='v08:npcx:2')
        self.assertEqual(0.0,b['zero_stamina_water_s']); self.assertEqual('ALIVE',b['life_state'])

    def test_22_health_includes_water_bag_core(self):
        h=self.e.health_arpg_v16a(self.wid); self.assertEqual('PASS',h['status']); self.assertEqual('PASS',h['stage16a']['water_bag']['status'])

class Stage16AWaterBagPersistenceV08Tests(unittest.TestCase):
    def test_23_bag_and_water_timer_persist_across_resume(self):
        with tempfile.TemporaryDirectory() as td_raw:
            td=pathlib.Path(td_raw); db=td/'w.sqlite'; save=td/'saves'
            e=IntegratedARPGEngineV16A(str(db),master_release_path=MASTER,save_root=save)
            wid=e.create_world('stage16a:v08:persist',160823)['world']['world_instance_id']
            p=e.arpg(wid).create_profile('stage16a:v08:persist',display_name='Persist Bag')['profile']['profile_ref']
            s=e.stage16a(wid); e.items_arpg(wid).ensure_inventory(p); b=s.equip_bag(p,event_ref='v08:persist:equip')['bag_ref']
            s.water_bag.grant_carried_item(p,'ITEM-GRAIN',2,event_ref='v08:persist:item')
            s.drop_bag_for_death(p,in_water=True,position={'iso_x_m':2,'iso_y_m':2,'altitude_m':0},event_ref='v08:persist:drop')
            s.advance_water_time(600,event_ref='v08:persist:t600'); before=s.water_bag.bag(b); e.runtime.close()
            e2=IntegratedARPGEngineV16A(str(db),master_release_path=MASTER,save_root=save); e2.resume_world(wid)
            after=e2.stage16a(wid).water_bag.bag(b)
            self.assertEqual(before,after); self.assertEqual(600.0,after['water_exposure_s']); self.assertEqual('DROPPED_WATER_FLOATING',after['state']); self.assertEqual('PASS',e2.health_arpg_v16a(wid)['status'])
            e2.runtime.close()

    def test_24_contract_version_v08(self):
        with tempfile.TemporaryDirectory() as td_raw:
            td=pathlib.Path(td_raw); e=IntegratedARPGEngineV16A(str(td/'w.sqlite'),master_release_path=MASTER,save_root=td/'s')
            wid=e.create_world('stage16a:v08:contract',160824)['world']['world_instance_id']
            c=e.stage16a(wid).contract(); self.assertEqual('V0.8.0-PRE-GODOT',c['version']); self.assertIn('water_bag_survival',c)
            e.runtime.close()

if __name__=='__main__': unittest.main(verbosity=2)
