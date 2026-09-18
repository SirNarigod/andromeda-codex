from __future__ import annotations
import hashlib, json, sqlite3, zipfile, os, threading
from pathlib import Path
from typing import Any

from living_runtime import SUPPORTED_MASTER_RELEASES
ATLAS_DATA='ANDROMEDA_CODEX_MASTER/02_ATLAS/runtime/data/atlas-data.json'
ROLES={'PUBLIC','PLAYER','ADMIN'}
_ATLAS_CACHE:dict[str,dict[str,Any]]={}
_ATLAS_CACHE_LOCK=threading.RLock()
DENY_KEYS={'protection','secret','secrets','password','token','credential','credentials','prompt','system_prompt','raw_prompt','raw_response','llm','internal','authority_override','canon_mutation','memory_write','knowledge_write'}
PLAYER_DATA_ALLOW={
 'name','role','location_ref','territory_ref','zone_ref','route_ref','operational','capacity_factor','functional','integrity','burning','fire_intensity','temperature','wetness','active','open','locked',
 'flow_ref','product','origin_id','processing_id','destination_id','route_ids','stock','production_rate','consumption_rate','base_price','price','shortage_pressure','last_throughput',
 'settlement_ref','count','labor_force','employed','unemployed','food_security','welfare_index',
 'faction_ref','influence','treasury','security','stability','influence_not_sovereignty',
 'species_ref','carrying_capacity','resource_index','water_index','climate_comfort',
 'humidity','water_level','smoke','contamination','atlas_exposure'
}

class AtlasBridgeError(Exception): pass
class AtlasBridgePermissionError(AtlasBridgeError): pass
class AtlasBridgeIntegrityError(AtlasBridgeError): pass

def _canon(v:Any)->str:return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def _sha_text(v:str)->str:return hashlib.sha256(v.encode()).hexdigest()
def _sha_file(p:str|Path)->str:
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def _scrub(value:Any, *, admin:bool=False)->Any:
 if isinstance(value,dict):
  out={}
  for k,v in value.items():
   lk=str(k).lower()
   if lk in DENY_KEYS or any(x in lk for x in ('password','credential','secret','raw_prompt','raw_response')):continue
   out[k]=_scrub(v,admin=admin)
  return out
 if isinstance(value,list):return [_scrub(x,admin=admin) for x in value]
 return value

class AtlasLivingBridge:
 """Read-only projection from a LivingRuntime SQLite database into Atlas-safe JSON."""
 SCHEMA_VERSION='1.0.0'
 def __init__(self, db_path:str|Path, master_release_path:str|Path):
  self.db_path=str(db_path); self.master_release_path=str(master_release_path)
  self.master_release_sha256=_sha_file(self.master_release_path)
  if self.master_release_sha256 not in SUPPORTED_MASTER_RELEASES: raise AtlasBridgeIntegrityError('master release hash mismatch/unsupported')
  cache_key=str(Path(self.master_release_path).resolve())
  with _ATLAS_CACHE_LOCK:
   cached=_ATLAS_CACHE.get(cache_key)
   if cached is None:
    with zipfile.ZipFile(self.master_release_path) as z:
     data=json.loads(z.read(ATLAS_DATA))
    cached={'atlas_meta':{k:data.get(k) for k in ('record_id','project','stage','version','projection_authority')},'entities':{e['id']:e for e in data.get('entities',[]) if isinstance(e,dict) and isinstance(e.get('id'),str)},'routes':{r.get('id'):r for r in data.get('routes',[]) if isinstance(r,dict) and r.get('id')}}
    _ATLAS_CACHE[cache_key]=cached
  self.atlas_meta=cached['atlas_meta']; self.entities=cached['entities']; self.routes=cached['routes']
  self._connect()
 def _connect(self):
  uri=f"file:{Path(self.db_path).resolve()}?mode=ro"
  self.conn=sqlite3.connect(uri,uri=True,check_same_thread=False); self.conn.row_factory=sqlite3.Row
  self.conn.execute('PRAGMA query_only=ON'); self.conn.execute('PRAGMA foreign_keys=ON')
 def close(self): self.conn.close()
 def _table(self,name:str)->bool:
  return self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None
 def _visible_canon(self,ref:str|None,spoiler_max:int)->bool:
  if not ref:return False
  e=self.entities.get(ref)
  if not e:return False
  level=int(e.get('spoiler_level') or 0)
  return level<=min(max(int(spoiler_max),0),3) and level<4 and e.get('atlas_visibility')!='HIDDEN'
 def _canon_brief(self,ref:str|None,spoiler_max:int)->dict[str,Any]|None:
  if not self._visible_canon(ref,spoiler_max):return None
  e=self.entities[ref]
  return {k:e.get(k) for k in ('id','name','domain','type','spoiler_level','atlas_visibility','location_refs','territory_refs','biome_refs','route_refs','layer_refs','geometry')}
 def _world(self,wid:str)->dict[str,Any]:
  r=self.conn.execute('SELECT * FROM worlds WHERE world_instance_id=?',(wid,)).fetchone()
  if not r: raise AtlasBridgePermissionError('world unavailable')
  c=self.conn.execute('SELECT * FROM clocks WHERE world_instance_id=?',(wid,)).fetchone()
  return {**dict(r),'clock':dict(c) if c else None}
 def _authorize(self,role:str,wid:str|None,request_scope:str|None)->dict[str,Any]|None:
  if role not in ROLES:raise AtlasBridgePermissionError('invalid role')
  if role=='PUBLIC':return None
  if not wid:raise AtlasBridgePermissionError('world required')
  w=self._world(wid)
  if role=='PLAYER' and (not request_scope or request_scope!=w['owner_scope']):raise AtlasBridgePermissionError('player scope mismatch')
  return w
 def _sanitize_value(self,value:Any,spoiler_max:int,visible_rt:set[str]|None=None)->Any:
  value=_scrub(value,admin=True); visible_rt=visible_rt or set()
  if isinstance(value,str):
   if value in self.entities and not self._visible_canon(value,spoiler_max): return '[REDACTED_CANONICAL_REF]'
   if value.startswith('rt:') and value not in visible_rt: return '[REDACTED_RUNTIME_REF]'
   return value
  if isinstance(value,list): return [self._sanitize_value(x,spoiler_max,visible_rt) for x in value]
  if isinstance(value,dict): return {k:self._sanitize_value(v,spoiler_max,visible_rt) for k,v in value.items()}
  return value
 def _safe_data(self,data:dict[str,Any],role:str,spoiler_max:int,visible_rt:set[str])->dict[str,Any]:
  data=_scrub(data,admin=role=='ADMIN')
  if role!='ADMIN': data={k:v for k,v in data.items() if k in PLAYER_DATA_ALLOW}
  return self._sanitize_value(data,spoiler_max,visible_rt)
 def _states(self,wid:str,role:str,spoiler_max:int)->tuple[list[dict[str,Any]],set[str]]:
  rows=self.conn.execute('SELECT * FROM entity_states WHERE world_instance_id=? ORDER BY entity_runtime_id',(wid,)).fetchall(); allowed=[];visible_rt=set()
  for r in rows:
   d=dict(r)
   if _sha_text(d['state_json'])!=d['state_hash']: raise AtlasBridgeIntegrityError('entity state hash mismatch')
   st=json.loads(d['state_json']); cref=d['canonical_ref']; cbrief=self._canon_brief(cref,spoiler_max) if cref else None
   if cref and not cbrief: continue
   if not cref:
    if role=='PLAYER' and st.get('data',{}).get('atlas_exposure')!='PLAYER_VISIBLE': continue
    if role not in {'ADMIN','PLAYER'}: continue
   allowed.append((d,st,cbrief)); visible_rt.add(d['entity_runtime_id'])
  out=[]
  for d,st,cbrief in allowed:
   out.append({'entity_runtime_id':d['entity_runtime_id'],'canonical_ref':d['canonical_ref'],'entity_kind':d['entity_kind'],'origin':d['origin'],'lifecycle':d['lifecycle'],'version':d['version'],'updated_at':{'day':d['updated_day'],'tick':d['updated_tick']},'data':self._safe_data(st.get('data',{}),role,spoiler_max,visible_rt),'canonical':cbrief,'authority':'TIMELINE_RUNTIME_STATE_NOT_CANON'})
  return out,visible_rt
 def _events(self,wid:str,role:str,visible_rt:set[str],spoiler_max:int,limit:int)->list[dict[str,Any]]:
  rows=self.conn.execute('SELECT * FROM events WHERE world_instance_id=? ORDER BY sequence DESC LIMIT ?',(wid,max(0,min(int(limit),1000)))).fetchall(); out=[]
  for r in rows:
   subjects=json.loads(r['subjects_json']); vis=[]
   for s in subjects:
    if s in visible_rt:vis.append(s)
    elif isinstance(s,str) and self._visible_canon(s,spoiler_max):vis.append(s)
   if role=='PLAYER' and not vis:continue
   safe_subjects=[]
   for sub in subjects:
    if sub in visible_rt: safe_subjects.append(sub)
    elif isinstance(sub,str) and sub in self.entities and self._visible_canon(sub,spoiler_max): safe_subjects.append(sub)
    elif role=='ADMIN' and isinstance(sub,str) and not sub.startswith('rt:') and sub not in self.entities: safe_subjects.append(sub)
   item={'sequence':r['sequence'],'event_id':r['event_id'],'event_type':r['event_type'],'occurred_at':{'day':r['occurred_day'],'tick':r['occurred_tick']},'subjects':safe_subjects,'source':r['source'],'authority':'IMMUTABLE_RUNTIME_EVENT'}
   if role=='ADMIN': item['payload']=self._sanitize_value(json.loads(r['payload_json']),spoiler_max,visible_rt); item['causality']=self._sanitize_value(json.loads(r['causality_json']),spoiler_max,visible_rt); item['event_hash']=r['event_hash']
   out.append(item)
  return out
 def _recoveries(self,wid:str,role:str,visible_rt:set[str])->list[dict[str,Any]]:
  rows=self.conn.execute('SELECT * FROM recoveries WHERE world_instance_id=? ORDER BY due_at_day',(wid,)).fetchall();out=[]
  for r in rows:
   if role=='PLAYER' and r['target_ref'] not in visible_rt:continue
   out.append({'recovery_id':r['recovery_id'],'target_ref':r['target_ref'],'destroyed_at_day':r['destroyed_at_day'],'due_at_day':r['due_at_day'],'status':r['status'],'policy':r['policy'],'authority':'RUNTIME_RECOVERY_POLICY'})
  return out
 def _ecology(self,wid:str,role:str,spoiler_max:int)->list[dict[str,Any]]:
  if not self._table('ecology_populations_current'):return []
  out=[]
  for r in self.conn.execute('SELECT * FROM ecology_populations_current WHERE world_instance_id=? ORDER BY species_ref,territory_ref',(wid,)):
   if _sha_text(r['population_json'])!=r['population_hash']: raise AtlasBridgeIntegrityError('ecology population hash mismatch')
   if not self._visible_canon(r['species_ref'],spoiler_max):continue
   out.append({'species_ref':r['species_ref'],'territory_ref':r['territory_ref'],'count':r['count'],'carrying_capacity':r['carrying_capacity'],'resource_index':r['resource_index'],'water_index':r['water_index'],'climate_comfort':r['climate_comfort'],'version':r['version'],'authority':'RUNTIME_ECOLOGY_AGGREGATE_NOT_CANON'})
  return out
 def _social(self,wid:str,role:str,viewer_ref:str|None,spoiler_max:int,visible_rt:set[str])->dict[str,list[dict[str,Any]]]:
  if role!='ADMIN' and not viewer_ref:return {'relationships':[],'reputation':[]}
  rel=[];rep=[]
  if self._table('relationships_current'):
   q='SELECT * FROM relationships_current WHERE world_instance_id=?';args=[wid]
   if role!='ADMIN':q+=' AND (holder_ref=? OR subject_ref=?)';args += [viewer_ref,viewer_ref]
   for r in self.conn.execute(q,args):
    if _sha_text(r['relationship_json'])!=r['relationship_hash']: raise AtlasBridgeIntegrityError('relationship hash mismatch')
    rel.append(self._sanitize_value(json.loads(r['relationship_json']),spoiler_max,visible_rt))
  if self._table('reputation_current'):
   q='SELECT * FROM reputation_current WHERE world_instance_id=?';args=[wid]
   if role!='ADMIN':q+=' AND subject_ref=?';args.append(viewer_ref)
   for r in self.conn.execute(q,args):
    if _sha_text(r['reputation_json'])!=r['reputation_hash']: raise AtlasBridgeIntegrityError('reputation hash mismatch')
    rep.append(self._sanitize_value(json.loads(r['reputation_json']),spoiler_max,visible_rt))
  return {'relationships':rel,'reputation':rep}
 def _causal(self,wid:str,role:str,visible_rt:set[str],limit:int=500)->list[dict[str,Any]]:
  if role!='ADMIN' or not self._table('causal_ledger'):return []
  out=[]
  for r in self.conn.execute('SELECT * FROM causal_ledger WHERE world_instance_id=? ORDER BY rowid DESC LIMIT ?',(wid,limit)):
   muts=self._sanitize_value(json.loads(r['mutations_json']),3,visible_rt)
   out.append({'ledger_entry_id':r['ledger_entry_id'],'event_id':r['event_id'],'root_event_id':r['root_event_id'],'recorded_at':{'day':r['recorded_day'],'tick':r['recorded_tick']},'mutations':muts,'ledger_hash':r['ledger_hash']})
  return out
 def _llm_metrics(self,wid:str,role:str)->dict[str,Any]:
  if role!='ADMIN' or not self._table('llm_requests'):return {'visible':False}
  requests=self.conn.execute('SELECT COUNT(*) c FROM llm_requests WHERE world_instance_id=?',(wid,)).fetchone()['c']
  turns=self.conn.execute('SELECT COUNT(*) c FROM llm_conversation_turns WHERE world_instance_id=?',(wid,)).fetchone()['c'] if self._table('llm_conversation_turns') else 0
  responses=self.conn.execute('SELECT COUNT(*) c FROM llm_responses r JOIN llm_requests q ON q.request_id=r.request_id WHERE q.world_instance_id=?',(wid,)).fetchone()['c'] if self._table('llm_responses') else 0
  return {'visible':True,'requests':requests,'responses':responses,'turns':turns,'raw_content_exposed':False}
 def export_projection(self, world_instance_id:str|None=None, *, role:str='PUBLIC', request_scope:str|None=None, viewer_ref:str|None=None, spoiler_max:int=0, recent_events:int=200)->dict[str,Any]:
  w=self._authorize(role,world_instance_id,request_scope); sm=min(max(int(spoiler_max),0),3)
  base={'schema_version':self.SCHEMA_VERSION,'projection_authority':'READ_ONLY_DERIVED_VIEW','master_release_sha256':self.master_release_sha256,'atlas':self.atlas_meta,'access':{'role':role,'spoiler_max':sm,'canonical_level_4_hidden':True,'runtime_write_authority':False}}
  if role=='PUBLIC':
   base.update({'world':None,'runtime_access':'NONE','layers':{},'security':{'runtime_hidden':True,'reason':'PUBLIC_ATLAS_CANON_ONLY'}});base['projection_hash']=_sha_text(_canon(base));return base
  wid=world_instance_id; states,visible_rt=self._states(wid,role,sm); events=self._events(wid,role,visible_rt,sm,recent_events); rec=self._recoveries(wid,role,visible_rt)
  by_kind=lambda *k:[x for x in states if x['entity_kind'] in k]
  layers={'LIVE_ENTITY_STATE':states,'LIVE_ROUTES':by_kind('ROUTE_RUNTIME'),'LIVE_ECONOMY':by_kind('ECONOMIC_FLOW'),'LIVE_POPULATION':by_kind('POPULATION_AGGREGATE'),'LIVE_FACTIONS':by_kind('FACTION_RUNTIME'),'LIVE_ENVIRONMENT':by_kind('OBJECT','STRUCTURE','FLORA_INSTANCE','ENVIRONMENT_ZONE','RESOURCE_NODE','MACHINE','VEHICLE','WEAPON'),'LIVE_EVENTS':events,'LIVE_RECOVERY':rec,'LIVE_ECOLOGY':self._ecology(wid,role,sm),'LIVE_SOCIAL':self._social(wid,role,viewer_ref,sm,visible_rt),'LIVE_CAUSAL':self._causal(wid,role,visible_rt),'LLM_METRICS':self._llm_metrics(wid,role)}
  world={'world_instance_id':w['world_instance_id'],'timeline_id':w['timeline_id'],'mode':w['mode'],'simulation_mode':w['simulation_mode'],'status':w['status'],'clock':{'day':w['clock']['day'],'tick':w['clock']['tick'],'ticks_per_day':w['clock']['ticks_per_day']}}
  base.update({'world':world,'runtime_access':'PLAYER_SAFE' if role=='PLAYER' else 'ADMIN_OPERATIONAL','layers':layers,'security':{'raw_llm_content_exposed':False,'private_memory_exposed':role=='ADMIN','hidden_canonical_overlays_removed':True,'runtime_born_default_hidden_for_player':True}})
  base['projection_hash']=_sha_text(_canon(base));return base
 def verify_projection(self,p:dict[str,Any])->dict[str,Any]:
  q=dict(p);h=q.pop('projection_hash',None);actual=_sha_text(_canon(q));return {'status':'PASS' if h==actual else 'FAIL','expected':h,'actual':actual}
 def write_attempt_probe(self)->str:
  try:self.conn.execute("UPDATE worlds SET status='PAUSED'");return 'FAIL_WRITE_SUCCEEDED'
  except sqlite3.DatabaseError:return 'PASS_READ_ONLY'


class AtlasSnapshotPublisher:
    """Publishes atomic SQLite read snapshots without mutating the authoritative runtime DB."""
    def __init__(self, runtime: Any, output_dir: str|Path):
        self.runtime=runtime; self.output_dir=Path(output_dir); self.output_dir.mkdir(parents=True,exist_ok=True); self._lock=threading.RLock()
    def publish(self, world_instance_id: str) -> dict[str,Any]:
        # Validate world before copying and serialize with the Runtime write authority.
        key=hashlib.sha256(world_instance_id.encode()).hexdigest()[:20]
        target=self.output_dir/f'living_atlas_{key}.sqlite'; tmp=self.output_dir/f'.living_atlas_{key}.tmp.sqlite'
        meta_path=self.output_dir/f'living_atlas_{key}.json'; meta_tmp=self.output_dir/f'.living_atlas_{key}.tmp.json'
        with self._lock, self.runtime._write_lock:
            core_integrity=self.runtime.full_integrity_check(world_instance_id)
            if core_integrity.get('status')!='PASS': raise AtlasBridgeIntegrityError('authoritative runtime integrity failed before snapshot')
            world=self.runtime.get_world(world_instance_id); clock=world['clock_state']
            if tmp.exists(): tmp.unlink()
            dst=sqlite3.connect(str(tmp))
            try:self.runtime.conn.backup(dst)
            finally:dst.close()
            # Prove the copy is internally valid before publication.
            chk=sqlite3.connect(f'file:{tmp.resolve()}?mode=ro',uri=True)
            try:
                integrity=chk.execute('PRAGMA integrity_check').fetchone()[0]
                fk=len(chk.execute('PRAGMA foreign_key_check').fetchall())
                seq=chk.execute('SELECT COALESCE(MAX(sequence),0) FROM events WHERE world_instance_id=?',(world_instance_id,)).fetchone()[0]
            finally:chk.close()
            if integrity!='ok' or fk!=0:
                if tmp.exists(): tmp.unlink()
                raise AtlasBridgeIntegrityError('snapshot integrity failure')
            os.replace(tmp,target); os.chmod(target,0o600)
            body={'schema_version':'1.0.0','authority':'READ_ONLY_ATOMIC_RUNTIME_SNAPSHOT','world_instance_id':world_instance_id,'timeline_id':world['timeline_id'],'clock':{'day':clock['day'],'tick':clock['tick'],'ticks_per_day':clock['ticks_per_day']},'max_event_sequence':seq,'snapshot_file':target.name,'snapshot_sha256':_sha_file(target),'source_runtime_mutated':False,'distribution':'BACKEND_ONLY_DO_NOT_SERVE_DB_FILE'}
            body['metadata_hash']=_sha_text(_canon(body)); meta_tmp.write_text(json.dumps(body,ensure_ascii=False,indent=2),encoding='utf-8'); os.replace(meta_tmp,meta_path)
        return body
