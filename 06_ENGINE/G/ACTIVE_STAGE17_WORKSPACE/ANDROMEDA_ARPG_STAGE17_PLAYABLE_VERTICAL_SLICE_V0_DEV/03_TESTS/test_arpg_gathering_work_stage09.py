import os, tempfile, unittest
from integrated_arpg_engine_v09 import IntegratedARPGEngineV09
from living_runtime import ConflictError

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

class Stage09GatheringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e=IntegratedARPGEngineV09(':memory:',master_release_path=MASTER)
        r=cls.e.create_world('stage09:test',90909); cls.wid=r['world']['world_instance_id']; cls.g=cls.e.gathering_arpg(cls.wid)
        cls.p=cls.e.arpg(cls.wid).create_profile('stage09:test',origin_mode='CREATED',display_name='Worker Tester')['profile']; cls.pref=cls.p['profile_ref']; cls.g.ensure_worker(cls.pref)
    @classmethod
    def tearDownClass(cls): cls.e.close()
    def _move(self,node):
        w=self.e.world_arpg(self.wid); st=w.ensure_profile(self.pref); st['zone_ref']=node['zone_ref']; st['instance_context']={'kind':'OVERWORLD','ref':node['zone_ref']}; w._save_profile(st)
    def _ensure_tool(self,kind='TOOL',event='tool'):
        inv=self.e.items_arpg(self.wid).inventory_snapshot(self.pref)
        if not any(self.e.items_arpg(self.wid).definition(i['item_ref'])['item_kind']==kind and i['condition']!='BROKEN' for i in inv['instances']):
            ref='ITEM-TOOL' if kind=='TOOL' else 'WPN-001'; self.e.items_arpg(self.wid).grant_item(self.pref,ref,1,event_ref='u:'+event)
    def test_01_health(self): self.assertEqual(self.e.health_arpg_v09(self.wid)['status'],'PASS')
    def test_02_activity_coverage(self):
        v=self.g.verify(); self.assertEqual(v['status'],'PASS'); self.assertEqual(set(v['activities']),set(self.g.ACTIVITIES)); self.assertTrue(all(v['activities'][a]>0 for a in self.g.ACTIVITIES))
    def test_03_profession_bridge_91(self): self.assertEqual(self.g.employment_bridge()['canonical_profession_snapshots'],91)
    def test_04_fishing_is_spatial(self):
        fish=self.g.list_nodes(activity_type='FISHING'); self.assertGreater(len(fish),0)
        for n in fish: self.assertTrue(self.g._zone_has_physical_fishing_water(self.e.world_arpg(self.wid).zone(n['zone_ref'])))
    def test_05_flora_guard(self):
        for n in self.g.list_nodes():
            if n['source_kind']=='FLORA': self.assertIn('MASTER_FLORA_SPATIALIZATION_BLOCKED',(n['source_meta']['flora_canon_guard']))
    def test_06_role_bindings(self):
        h=self.g.assign_role(self.pref,'HUNTING'); self.assertEqual(h['profession_ref'],'JOB-EXPL-CAC-001')
        a=self.g.assign_role(self.pref,'AGRICULTURE'); self.assertEqual(a['profession_ref'],'JOB-RUR-AGR-001')
        m=self.g.assign_role(self.pref,'MINING'); self.assertIsNone(m['profession_ref']); self.assertIn('OUTSIDE_TER_011',m['canonical_candidate_not_bound_reason'])
        f=self.g.assign_role(self.pref,'FISHING'); self.assertIsNone(f['profession_ref'])
    def test_07_explicit_out_of_territory_profession_rejected(self):
        with self.assertRaises(ConflictError): self.g.assign_role(self.pref,'MINING',profession_ref='JOB-MIN-OPER-001')
    def test_08_child_labor_forbidden(self):
        child=next(n for s in self.e.country(self.wid).world['country']['states'] for b in s['blocks'] for c in b['cities'] for n in c['npcs'] if n['class']=='CHILD')
        with self.assertRaises(ConflictError): self.g.assign_role(child['id'],'AGRICULTURE')
    def test_09_requires_tool(self):
        p2=self.e.arpg(self.wid).create_profile('stage09:test2',origin_mode='CREATED',display_name='No Tool')['profile']; ref=p2['profile_ref']; self.g.assign_role(ref,'MINING')
        n=self.g.list_nodes(activity_type='MINING')[0]; w=self.e.world_arpg(self.wid); st=w.ensure_profile(ref); st['zone_ref']=n['zone_ref'];st['instance_context']={'kind':'OVERWORLD','ref':n['zone_ref']};w._save_profile(st)
        out=self.g.create_work_order(ref,n['node_ref'],1,event_ref='u:no-tool'); self.assertEqual(out['status'],'REJECTED'); self.assertEqual(out['reason'],'REQUIRED_WORK_EQUIPMENT_MISSING')
    def test_10_player_mining_to_inventory(self):
        n=self.g.list_nodes(activity_type='MINING')[0]; self._move(n); self.g.assign_role(self.pref,'MINING'); self._ensure_tool('TOOL','mining-tool')
        before=n['remaining_units']; o=self.g.create_work_order(self.pref,n['node_ref'],4,event_ref='u:mining-create'); self.assertEqual(o['status'],'PASS')
        x=self.g.execute_work_order(o['order']['order_ref'],event_ref='u:mining-exec'); self.assertEqual(x['status'],'PASS'); self.assertGreater(x['produced_units'],0)
        self.assertEqual(self.g.node(n['node_ref'])['remaining_units'],before-x['resource_consumed']); self.assertGreaterEqual(self.e.items_arpg(self.wid).inventory_snapshot(self.pref)['stacks'].get(n['output_item_ref'],0),x['produced_units'])
    def test_11_create_replay_idempotent(self):
        n=self.g.list_nodes(activity_type='FORAGING')[0]; self._move(n); self.g.assign_role(self.pref,'FORAGING'); self._ensure_tool('TOOL','forage-tool')
        a=self.g.create_work_order(self.pref,n['node_ref'],1,event_ref='u:replay-create'); b=self.g.create_work_order(self.pref,n['node_ref'],1,event_ref='u:replay-create'); self.assertTrue(b['idempotent_replay']); self.assertEqual(a['order']['order_ref'],b['order']['order_ref'])
    def test_12_event_ref_conflict(self):
        nodes=self.g.list_nodes(activity_type='MINING')[:2]; self._move(nodes[0]); self.g.assign_role(self.pref,'MINING'); self._ensure_tool('TOOL','conf-tool')
        self.g.create_work_order(self.pref,nodes[0]['node_ref'],1,event_ref='u:conflict')
        with self.assertRaises(ConflictError): self.g.create_work_order(self.pref,nodes[0]['node_ref'],2,event_ref='u:conflict')
    def test_13_fishing_produces_generic_noncanon_item(self):
        n=self.g.list_nodes(activity_type='FISHING')[0]; self._move(n); self.g.assign_role(self.pref,'FISHING'); self._ensure_tool('TOOL','fish-tool')
        d=self.e.items_arpg(self.wid).definition(self.g.FISH_ITEM_REF); self.assertFalse(d['canonical_identity'])
        # deterministic retries with distinct refs until success, bounded.
        produced=0
        for i in range(6):
            o=self.g.create_work_order(self.pref,n['node_ref'],2,event_ref=f'u:fish-create:{i}'); x=self.g.execute_work_order(o['order']['order_ref'],event_ref=f'u:fish-exec:{i}'); produced+=x.get('produced_units',0)
            if produced: break
        self.assertGreater(produced,0)
    def test_14_hunting_nonpredator(self):
        n=next(x for x in self.g.list_nodes(activity_type='HUNTING') if x['source_meta'].get('role')!='PREDATOR'); self._move(n); self.g.assign_role(self.pref,'HUNTING'); self._ensure_tool('WEAPON','hunt-wpn')
        produced=0
        for i in range(6):
            o=self.g.create_work_order(self.pref,n['node_ref'],1,event_ref=f'u:hunt-create:{i}'); x=self.g.execute_work_order(o['order']['order_ref'],event_ref=f'u:hunt-exec:{i}'); produced+=x.get('produced_units',0)
            if produced: break
        self.assertGreater(produced,0)
    def test_15_predator_requires_clearance(self):
        n=next(x for x in self.g.list_nodes(activity_type='HUNTING') if x['source_meta'].get('role')=='PREDATOR'); self._move(n); self.g.assign_role(self.pref,'HUNTING'); self._ensure_tool('WEAPON','pred-wpn')
        o=self.g.create_work_order(self.pref,n['node_ref'],1,event_ref='u:pred-create'); x=self.g.execute_work_order(o['order']['order_ref'],event_ref='u:pred-exec'); self.assertEqual(x['status'],'REJECTED'); self.assertEqual(x['reason'],'PREDATOR_HUNT_REQUIRES_STAGE07_DANGER_CLEARANCE')
    def test_16_npc_shared_inventory_work(self):
        # Choose a safe agriculture node and a non-child NPC in the same block.
        pair=None
        for n in self.g.list_nodes(activity_type='AGRICULTURE'):
            b=self.e.country(self.wid).block(n['block_ref'])
            npc=next((x for c in b['cities'] for x in c['npcs'] if x['class']!='CHILD'),None)
            if npc: pair=(n,npc);break
        self.assertIsNotNone(pair); n,npc=pair; ref=npc['id']; role=self.g.assign_role(ref,'AGRICULTURE'); self.assertEqual(role['profession_ref'],'JOB-RUR-AGR-001')
        self.e.items_arpg(self.wid).grant_item(ref,'ITEM-TOOL',1,event_ref='u:npc-tool'); o=self.g.create_work_order(ref,n['node_ref'],2,event_ref='u:npc-create'); self.assertEqual(o['status'],'PASS')
        x=self.g.execute_work_order(o['order']['order_ref'],event_ref='u:npc-exec'); self.assertEqual(x['status'],'PASS'); self.assertGreater(self.e.items_arpg(self.wid).inventory_snapshot(ref)['stacks'].get(n['output_item_ref'],0),0)
    def test_17_mastery_progresses(self):
        w=self.g.worker(self.pref); self.assertGreater(w['completed_orders'],0); self.assertGreater(sum(v['xp'] for v in w['mastery'].values()),0)
    def test_18_verify_after_mutations(self): self.assertEqual(self.g.verify()['status'],'PASS')
    def test_19_same_seed_node_projection_deterministic(self):
        r=self.e.create_world('stage09:second',90909); g2=self.e.gathering_arpg(r['world']['world_instance_id']); self.assertEqual([n['node_ref'] for n in self.g.list_nodes()],[n['node_ref'] for n in g2.list_nodes()])

class Stage09PersistenceTests(unittest.TestCase):
    def test_persistence_resume(self):
        with tempfile.TemporaryDirectory() as td:
            db=os.path.join(td,'s09.sqlite'); e=IntegratedARPGEngineV09(db,master_release_path=MASTER); r=e.create_world('persist:s09',91919);wid=r['world']['world_instance_id'];g=e.gathering_arpg(wid)
            p=e.arpg(wid).create_profile('persist:s09',origin_mode='CREATED',display_name='Persist Worker')['profile'];pref=p['profile_ref'];g.assign_role(pref,'MINING');e.items_arpg(wid).grant_item(pref,'ITEM-TOOL',1,event_ref='p:tool')
            n=g.list_nodes(activity_type='MINING')[0];w=e.world_arpg(wid);st=w.ensure_profile(pref);st['zone_ref']=n['zone_ref'];st['instance_context']={'kind':'OVERWORLD','ref':n['zone_ref']};w._save_profile(st)
            o=g.create_work_order(pref,n['node_ref'],2,event_ref='p:create');x=g.execute_work_order(o['order']['order_ref'],event_ref='p:exec');before=(g.node(n['node_ref'])['remaining_units'],g.worker(pref),e.items_arpg(wid).inventory_snapshot(pref)['stacks'].get(n['output_item_ref'],0));e.runtime.close()
            e2=IntegratedARPGEngineV09(db,master_release_path=MASTER);e2.resume_world(wid);g2=e2.gathering_arpg(wid);after=(g2.node(n['node_ref'])['remaining_units'],g2.worker(pref),e2.items_arpg(wid).inventory_snapshot(pref)['stacks'].get(n['output_item_ref'],0));self.assertEqual(before,after);self.assertEqual(e2.health_arpg_v09(wid)['status'],'PASS');e2.runtime.close()

if __name__=='__main__':unittest.main(verbosity=2)
