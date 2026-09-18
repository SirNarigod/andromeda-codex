import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v14 import IntegratedLivingEngineV14
from country_scale import CountryScaleSystem
MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'
class VersionMetadata(unittest.TestCase):
 def test_v14_country_schema_identity(self):
  e=IntegratedLivingEngineV14(':memory:',master_release_path=MASTER)
  try:
   r=e.create_world('version',8001,load_relationships=False);w=r['world']['world_instance_id'];c=e.country(w)
   self.assertEqual(CountryScaleSystem.VERSION,'V1.4.0');self.assertEqual(c.world['schema_version'],'1.4.0');self.assertEqual(r['version'],'V1.4.0')
  finally:e.close()
if __name__=='__main__':unittest.main()
