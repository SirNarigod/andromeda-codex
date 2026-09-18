from __future__ import annotations
import hashlib, math
from typing import Any

class EnvironmentSimulationSystem:
    VERSION='V1.5.0'; AUTHORITY='LIVING_DYNAMIC_ENVIRONMENT_RUNTIME'
    def __init__(self,runtime:Any,world_instance_id:str,country:Any):
        self.runtime=runtime; self.world_instance_id=world_instance_id; self.country=country
    def _noise(self,*parts):
        return int(hashlib.sha256('|'.join(map(str,parts)).encode()).hexdigest()[:12],16)/float(16**12-1)
    def state_for_block(self,block_id:str):
        b=self.country.block(block_id); c=b['climate']; clock=self.runtime.get_clock(self.world_instance_id)
        tpd=float(clock['ticks_per_day']); phase=(float(clock['tick'])/tpd)*2*math.pi
        base=float(c['temperature_c']); amp=4.0+3.0*(1.0-float(c['humidity_pct'])/100.0)
        temp=base+math.sin(phase-math.pi/2)*amp
        chance=max(0,min(1,float(c['rainfall_mm_y'])/2200.0*0.65+float(c['humidity_pct'])/100.0*0.35))
        precip=self._noise(self.country.seed,block_id,clock['day'],clock['tick'],'rain')<chance
        wind=2.0+12.0*self._noise(self.country.seed,block_id,clock['day'],clock['tick'],'wind')
        daylight=max(0.0,math.sin(phase-math.pi/2)*0.5+0.5)
        visibility=max(0.15,min(1.0,0.25+0.75*daylight-(0.2 if precip else 0.0)))
        move=max(.55,min(1.05,1.0-(0.12 if precip else 0)-max(0,abs(temp-22)-18)*0.008))
        return {'status':'PASS','block_id':block_id,'temperature_c':round(temp,2),'precipitating':precip,
                'precipitation_probability':round(chance,4),'humidity':float(c['humidity_pct'])/100.0,'wind_mps':round(wind,2),
                'daylight':round(daylight,4),'visibility':round(visibility,4),'movement_factor':round(move,4),
                'clock':{'day':clock['day'],'tick':clock['tick']},'authority':self.AUTHORITY}
    def verify(self):
        failures=[]
        for st in self.country.world['country']['states']:
            for b in st['blocks']:
                x=self.state_for_block(b['id'])
                if not .15<=x['visibility']<=1: failures.append('VISIBILITY:'+b['id'])
                if not .55<=x['movement_factor']<=1.05: failures.append('MOVE_FACTOR:'+b['id'])
        return {'status':'PASS' if not failures else 'FAIL','failures':failures}
