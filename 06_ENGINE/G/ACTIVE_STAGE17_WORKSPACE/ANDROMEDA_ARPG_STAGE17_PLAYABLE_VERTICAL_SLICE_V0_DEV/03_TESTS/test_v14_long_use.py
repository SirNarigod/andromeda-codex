import unittest,sys,tempfile,os,copy,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v14 import IntegratedLivingEngineV14
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
class LongUse(unittest.TestCase):
 def make(self,seed=1201):
  td=tempfile.TemporaryDirectory();e=IntegratedLivingEngineV14(os.path.join(td.name,'w.db'),master_release_path=MASTER);r=e.create_world('long',seed,load_relationships=False);return td,e,r['world']['world_instance_id']
 def test_repeated_travel_does_not_leak_loaded_chunks(self):
  td,e,w=self.make();c=e.country(w);s=e.streaming(w)
  try:
   n=next(x for x in c._all_npc_records() if x['class']=='WARRIOR');blocks=[b for st in c.world['country']['states'] for b in st['blocks']];base_owner_chunks=len(set(s.owners.values()))
   for i in range(15):self.assertEqual(s.travel_npc(n['id'],blocks[(i+1)%len(blocks)]['id'],speed_kmh=1000)['status'],'PASS')
   self.assertLessEqual(len(s.loaded),base_owner_chunks+9)
  finally:e.close();td.cleanup()
 def test_dungeon_runtime_keys_are_visible_in_country_inventory(self):
  td,e,w=self.make();c=e.country(w)
  try:
   keys=[]
   for st in c.world['country']['states']:
    for b in st['blocks']:
     for d in b.get('dungeons',[]):
      for r in d['graph_v2']['rooms']:
       keys.extend(o['item_ref'] for o in r['objects'] if o.get('object_type')=='KEY' and o.get('quantity',0)>0)
   if not keys:self.skipTest('seed has no locked graph edges')
   inv=c.world['country']['inventory'];missing=[k for k in keys if inv.get('scene_items',{}).get(k,0)<=0];self.assertEqual(missing,[])
  finally:e.close();td.cleanup()
 def test_same_seed_same_spatial_graph_summary(self):
  def summary():
   td,e,w=self.make(2207);c=e.country(w);sp=e.spatial(w)
   try:
    return {'states':[(s['id'],s['coordinate_center']) for s in c.world['country']['states']], 'sub':[(sr['id'],sr['coordinate_center']) for st in c.world['country']['states'] for b in st['blocks'] for sr in b['subregions']], 'dungeons':[(d['id'],d['coordinate_center'],[(r['id'],r['room_type'],r['level']) for r in d['graph_v2']['rooms']],[(x['from'],x['to'],x['type'],x['locked'],x['secret']) for x in d['graph_v2']['edges']]) for st in c.world['country']['states'] for b in st['blocks'] for d in b.get('dungeons',[])]}
   finally:e.close();td.cleanup()
  self.assertEqual(summary(),summary())
if __name__=='__main__':unittest.main()
