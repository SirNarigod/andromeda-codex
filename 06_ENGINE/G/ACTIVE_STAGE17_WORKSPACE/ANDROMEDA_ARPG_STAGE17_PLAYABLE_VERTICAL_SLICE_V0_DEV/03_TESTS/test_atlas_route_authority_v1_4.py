import unittest,sys,tempfile,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v14 import IntegratedLivingEngineV14
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
class RouteAuthority(unittest.TestCase):
 def test_route_layer_uses_canonical_master_geometry(self):
  with tempfile.TemporaryDirectory() as td:
   e=IntegratedLivingEngineV14(os.path.join(td,'w.db'),master_release_path=MASTER)
   try:
    r=e.create_world('route',1201,load_relationships=False);w=r['world']['world_instance_id'];rows=e.atlas_lod(w).layer_projection(['routes'])['routes']['rows'];self.assertTrue(rows);self.assertTrue(all(x['route_id'].startswith('RTE-') for x in rows));self.assertTrue(all(x.get('authority')=='CÂNONE_ESPACIAL' for x in rows));self.assertTrue(all(x.get('geometry',{}).get('type')=='LineString' for x in rows))
   finally:e.close()
if __name__=='__main__':unittest.main()
