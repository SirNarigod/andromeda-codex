import json, sys, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v13 import IntegratedLivingEngineV13

MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')

class CombatDeterminismV13Tests(unittest.TestCase):
    def run_logical_scenario(self, seed: int):
        e=IntegratedLivingEngineV13(':memory:',master_release_path=MASTER)
        try:
            r=e.create_world(f'determinism-{seed}',seed,load_relationships=False)
            wid=r['world']['world_instance_id']; c=e.country(wid)
            ctx=None
            for st in c.world['country']['states']:
                for b in st['blocks']:
                    pred=next((f for f in b['fauna'] if f['role']=='PREDATOR' and f['count']>0),None)
                    for cy in b['cities']:
                        npc=next((n for n in cy['npcs'] if n['class']!='CHILD' and n['protection']['combat_targetable']),None)
                        sh=next((s for s in cy['shops'] if any(k.startswith('WPN-') and v>0 for k,v in s['inventory'].items())),None)
                        if pred and npc and sh:
                            weapon=next(k for k,v in sorted(sh['inventory'].items()) if k.startswith('WPN-') and v>0)
                            ctx=(b,npc,sh,pred,weapon);break
                    if ctx:break
                if ctx:break
            self.assertIsNotNone(ctx)
            b,npc,sh,pred,weapon=ctx
            p=c.purchase(sh['id'],npc['id'],weapon,1); self.assertEqual(p['status'],'PASS',p)
            h=c.hunt_fauna(b['id'],pred['id'],1,npc['id']); self.assertEqual(h['status'],'PASS',h); self.assertEqual(h['killed'],1,h)
            rows=e.runtime.conn.execute("SELECT payload_json FROM events WHERE world_instance_id=? AND event_type='COMBAT_RESOLVED' ORDER BY sequence",(wid,)).fetchall()
            combat=[]
            for row in rows:
                params=json.loads(row['payload_json'])['parameters']
                combat.append({k:params[k] for k in ('roll','hit','damage','health_before','health_after','lethal','weapon_ref')})
            return {
                'combat':combat,
                'witness_memory_count':h['witness_memory_count'],
                'killed':h['killed'],
                'remaining':h['remaining'],
                'catalog_refs':e.commerce.full_integrity_check(wid)['catalog'],
            }
        finally:
            e.close()

    def test_same_seed_same_logical_combat_across_fresh_uuid_allocations(self):
        first=self.run_logical_scenario(4317)
        second=self.run_logical_scenario(4317)
        self.assertEqual(first,second)
        self.assertGreater(len(first['combat']),0)
        self.assertGreater(first['witness_memory_count'],0)

if __name__=='__main__':
    unittest.main()
