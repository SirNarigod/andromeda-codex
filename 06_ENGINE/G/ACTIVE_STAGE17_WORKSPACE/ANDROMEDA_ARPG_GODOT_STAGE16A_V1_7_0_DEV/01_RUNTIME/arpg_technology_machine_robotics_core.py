from __future__ import annotations
import copy, hashlib, json, math, zipfile
from typing import Any
from living_runtime import ValidationError, IntegrityError, ConflictError, NotFoundError, canonical_json, sha256_text

class ARPGTechnologyMachineRoboticsCore:
    """Stage11 technology/machine/robotics authority for Terras Livres.

    Canonical identities are snapshotted read-only. Numeric machine capacities,
    recipes, energy budgets and robot profiles are gameplay-derived and rebalanceable.
    Robots are technological assets, not Country NPCs or legal workers.
    """
    VERSION='V1.2.0'
    AUTHORITY='ANDROMEDA_ARPG_STAGE11_TECHNOLOGY_MACHINES_ROBOTICS'
    GAMEPLAY_AUTHORITY='GAMEPLAY_DERIVED_STAGE11_REBALANCEABLE'
    COUNTRY_REF='TER-011'
    WORKSHOP_REF='POI-003'
    AUTOMOTIVE_REF='SYS-AUT-001'
    ROBOTICS_JOB_REF='JOB-LOG-ROBOTICA-001'
    LOCAL_PROFESSIONS=(
        'JOB-TEC-OFICINA-001','JOB-MAN-AGENTE-001','JOB-MFG-FAB-001','JOB-MFG-REPARO-001',
        'JOB-MNT-CAMPO-001','JOB-TEC-RESFRIAMENTO-001','JOB-TEC-OFI-RESP-001','JOB-TEC-OFI-AUX-001'
    )
    CAPABILITY_REFS=('PROP-OFI-001','PROP-OFI-002','PROP-MFG-001','PROP-MNT-001','PROP-MNT-002','PROP-LOG-002')
    MACHINE_PROFILES={
      'MACH-PROFILE-FABRICATOR':{'name':'Módulo de fabricação de oficina','machine_class':'FABRICATION','integrity_max':120.0,'energy_max':140.0,'cycle_energy':8.0,'wear_per_cycle':1.5,'capacity_kg':900.0},
      'MACH-PROFILE-MAINTENANCE':{'name':'Bancada modular de manutenção','machine_class':'MAINTENANCE','integrity_max':130.0,'energy_max':120.0,'cycle_energy':5.0,'wear_per_cycle':0.8,'capacity_kg':700.0},
      'MACH-PROFILE-AGRICULTURAL':{'name':'Máquina agrícola de serviço','machine_class':'AGRICULTURAL','integrity_max':150.0,'energy_max':160.0,'cycle_energy':10.0,'wear_per_cycle':1.8,'capacity_kg':1200.0},
      'MACH-PROFILE-POWER':{'name':'Unidade técnica de reserva energética','machine_class':'POWER_SERVICE','integrity_max':110.0,'energy_max':240.0,'cycle_energy':2.0,'wear_per_cycle':0.4,'capacity_kg':500.0},
    }
    ROBOT_PROFILES={
      'RBT-PROFILE-LOGISTICS':{'name':'Robô logístico supervisionado','robot_class':'LOGISTICS','integrity_max':100.0,'energy_max':100.0,'task_energy':5.0,'cargo_kg':240.0},
      'RBT-PROFILE-FIELD-SERVICE':{'name':'Robô de apoio técnico supervisionado','robot_class':'FIELD_SERVICE','integrity_max':110.0,'energy_max':110.0,'task_energy':6.0,'cargo_kg':120.0},
      'RBT-PROFILE-HAULER':{'name':'Robô cargueiro supervisionado','robot_class':'HAULER','integrity_max':130.0,'energy_max':130.0,'task_energy':8.0,'cargo_kg':600.0},
    }
    RECIPES={
      'RECIPE-CIRCUIT-STAGE11':{'machine_class':'FABRICATION','inputs':{'MIN-COPPER':2,'MIN-QUARTZ':1},'outputs':{'ITEM-CIRCUIT':1},'authority':'GAMEPLAY_DERIVED_RECIPE_NOT_CANON'},
      'RECIPE-SERVO-STAGE11':{'machine_class':'FABRICATION','inputs':{'MIN-IRON':2,'ITEM-CIRCUIT':1},'outputs':{'ITEM-SERVO':1},'authority':'GAMEPLAY_DERIVED_RECIPE_NOT_CANON'},
      'RECIPE-ACTUATOR-STAGE11':{'machine_class':'FABRICATION','inputs':{'MIN-IRON':2,'ITEM-SERVO':1},'outputs':{'ITEM-ACTUATOR':1},'authority':'GAMEPLAY_DERIVED_RECIPE_NOT_CANON'},
      'RECIPE-ENERGY-CELL-STAGE11':{'machine_class':'FABRICATION','inputs':{'MIN-COPPER':1,'MIN-QUARTZ':2},'outputs':{'ITEM-ENERGY-CELL':1},'authority':'GAMEPLAY_DERIVED_RECIPE_NOT_CANON'},
    }
    ENERGY_CONTRACT={
      'energy_contract_ref':'TECH-ENERGY-BUFFER-STAGE11','name':'Reserva energética técnica Stage11',
      'canonical_source_type':'UNSPECIFIED_BY_TER_011_CANON','carrier_item_ref':'ITEM-ENERGY-CELL',
      'authority':'GAMEPLAY_DERIVED_ENERGY_CARRIER; DOES_NOT_CANONIZE_FUEL_OR_POWER_SOURCE'
    }

    def __init__(self,engine:Any,world_instance_id:str)->None:
        self.engine=engine; self.runtime=engine.runtime; self.world_instance_id=str(world_instance_id)
        self.country=engine.country(world_instance_id); self.world=engine.world_arpg(world_instance_id); self.items=engine.items_arpg(world_instance_id)
        self.mobility=engine.mobility_arpg(world_instance_id); self.actors=engine.actors_arpg(world_instance_id); self.gathering=engine.gathering_arpg(world_instance_id)
        self._init_schema(); self._canon=self._load_canon(); self._bootstrap_profiles(); self._bootstrap_workshop_machines()

    @staticmethod
    def _payload(obj):
        t=canonical_json(obj); return t,sha256_text(t)
    def _world_seed(self): return int(getattr(self.country,'seed',0) or 0)
    def _stable_ref(self,prefix,*parts):
        raw='|'.join(str(x) for x in (self._world_seed(),)+parts); return prefix+hashlib.sha256(raw.encode()).hexdigest()[:18].upper()

    def _init_schema(self):
        with self.runtime._write_lock:
            self.runtime.conn.executescript('''
            CREATE TABLE IF NOT EXISTS arpg_technology_canon_snapshots(
              canonical_ref TEXT PRIMARY KEY,source_path TEXT NOT NULL,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS arpg_machine_profiles(
              profile_ref TEXT PRIMARY KEY,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS arpg_machine_instances(
              world_instance_id TEXT NOT NULL,machine_ref TEXT NOT NULL,profile_ref TEXT NOT NULL,owner_ref TEXT NOT NULL,
              payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL,PRIMARY KEY(world_instance_id,machine_ref));
            CREATE TABLE IF NOT EXISTS arpg_robot_profiles(
              profile_ref TEXT PRIMARY KEY,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS arpg_robot_instances(
              world_instance_id TEXT NOT NULL,robot_ref TEXT NOT NULL,profile_ref TEXT NOT NULL,owner_ref TEXT NOT NULL,
              payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL,PRIMARY KEY(world_instance_id,robot_ref));
            CREATE TABLE IF NOT EXISTS arpg_technology_events(
              world_instance_id TEXT NOT NULL,event_ref TEXT NOT NULL,event_type TEXT NOT NULL,payload_hash TEXT NOT NULL,
              result_json TEXT NOT NULL,result_hash TEXT NOT NULL,PRIMARY KEY(world_instance_id,event_ref));
            ''')

    def _load_canon(self):
        p=self.runtime.master_release_path
        if not p: raise IntegrityError('Master release required for Stage11')
        ep='ANDROMEDA_CODEX_MASTER/01_CANON/ANDROMEDA_CODEX_CANON_MASTER_V2_0_0.json'
        with zipfile.ZipFile(p) as z: master=json.loads(z.read(ep))
        ents={e.get('id'):e for e in master.get('entities',[]) if isinstance(e,dict) and e.get('id')}
        refs=(self.WORKSHOP_REF,self.AUTOMOTIVE_REF,self.ROBOTICS_JOB_REF)+self.LOCAL_PROFESSIONS+self.CAPABILITY_REFS
        out={}
        for ref in refs:
            obj=ents.get(ref)
            if not obj: raise IntegrityError('Stage11 missing canonical source:'+ref)
            t,h=self._payload(obj)
            row=self.runtime.conn.execute('SELECT payload_hash FROM arpg_technology_canon_snapshots WHERE canonical_ref=?',(ref,)).fetchone()
            if row and row['payload_hash']!=h: raise IntegrityError('Stage11 canonical snapshot drift:'+ref)
            if not row:
                with self.runtime._write_lock:self.runtime.conn.execute('INSERT INTO arpg_technology_canon_snapshots VALUES(?,?,?,?)',(ref,ep,t,h))
            out[ref]=obj
        return out

    def canonical_snapshot(self,ref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_technology_canon_snapshots WHERE canonical_ref=?',(str(ref),)).fetchone()
        if not row: raise NotFoundError('technology canonical snapshot not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('technology snapshot hash mismatch')
        return json.loads(row['payload_json'])

    def _bootstrap_profiles(self):
        for ref,b in self.MACHINE_PROFILES.items():
            p={'profile_ref':ref,**copy.deepcopy(b),'authority':self.GAMEPLAY_AUTHORITY,'canonical_identity':False,'workshop_support_ref':self.WORKSHOP_REF,'art_dependency':'NONE_PLACEHOLDER_READY'}
            t,h=self._payload(p)
            with self.runtime._write_lock:self.runtime.conn.execute('INSERT OR REPLACE INTO arpg_machine_profiles VALUES(?,?,?)',(ref,t,h))
        for ref,b in self.ROBOT_PROFILES.items():
            p={'profile_ref':ref,**copy.deepcopy(b),'authority':self.GAMEPLAY_AUTHORITY,'canonical_identity':False,
               'legal_status':'TECHNOLOGICAL_ASSET_NOT_NPC_NOT_LEGAL_WORKER','robotics_governance_ref':self.ROBOTICS_JOB_REF,
               'territory_guard':'JOB-LOG-ROBOTICA-001_NOT_DISTRIBUTED_IN_TER-011__DERIVED_SUPERVISION_REQUIRED','art_dependency':'NONE_PLACEHOLDER_READY'}
            t,h=self._payload(p)
            with self.runtime._write_lock:self.runtime.conn.execute('INSERT OR REPLACE INTO arpg_robot_profiles VALUES(?,?,?)',(ref,t,h))

    def machine_profile(self,ref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_machine_profiles WHERE profile_ref=?',(str(ref),)).fetchone()
        if not row: raise NotFoundError('machine profile not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('machine profile hash mismatch')
        return json.loads(row['payload_json'])
    def robot_profile(self,ref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_robot_profiles WHERE profile_ref=?',(str(ref),)).fetchone()
        if not row: raise NotFoundError('robot profile not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('robot profile hash mismatch')
        return json.loads(row['payload_json'])
    def list_machine_profiles(self): return [self.machine_profile(r['profile_ref']) for r in self.runtime.conn.execute('SELECT profile_ref FROM arpg_machine_profiles ORDER BY profile_ref')]
    def list_robot_profiles(self): return [self.robot_profile(r['profile_ref']) for r in self.runtime.conn.execute('SELECT profile_ref FROM arpg_robot_profiles ORDER BY profile_ref')]

    def _save_machine(self,m):
        t,h=self._payload(m)
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT OR REPLACE INTO arpg_machine_instances VALUES(?,?,?,?,?,?)',(self.world_instance_id,m['machine_ref'],m['profile_ref'],m['owner_ref'],t,h))
    def machine(self,ref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_machine_instances WHERE world_instance_id=? AND machine_ref=?',(self.world_instance_id,str(ref))).fetchone()
        if not row: raise NotFoundError('machine not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('machine hash mismatch')
        return json.loads(row['payload_json'])
    def list_machines(self): return [self.machine(r['machine_ref']) for r in self.runtime.conn.execute('SELECT machine_ref FROM arpg_machine_instances WHERE world_instance_id=? ORDER BY machine_ref',(self.world_instance_id,))]

    def _save_robot(self,r):
        t,h=self._payload(r)
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT OR REPLACE INTO arpg_robot_instances VALUES(?,?,?,?,?,?)',(self.world_instance_id,r['robot_ref'],r['profile_ref'],r['owner_ref'],t,h))
    def robot(self,ref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_robot_instances WHERE world_instance_id=? AND robot_ref=?',(self.world_instance_id,str(ref))).fetchone()
        if not row: raise NotFoundError('robot not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('robot hash mismatch')
        return json.loads(row['payload_json'])
    def list_robots(self): return [self.robot(r['robot_ref']) for r in self.runtime.conn.execute('SELECT robot_ref FROM arpg_robot_instances WHERE world_instance_id=? ORDER BY robot_ref',(self.world_instance_id,))]

    def _bootstrap_workshop_machines(self):
        # Workshop location is canonical. Machine identities/numbers are derived placeholders.
        for pref in ('MACH-PROFILE-FABRICATOR','MACH-PROFILE-MAINTENANCE','MACH-PROFILE-POWER'):
            ref=self._stable_ref('MACH-',self.WORKSHOP_REF,pref)
            if self.runtime.conn.execute('SELECT 1 FROM arpg_machine_instances WHERE world_instance_id=? AND machine_ref=?',(self.world_instance_id,ref)).fetchone(): continue
            p=self.machine_profile(pref)
            m={'machine_ref':ref,'profile_ref':pref,'owner_ref':self.WORKSHOP_REF,'location_ref':self.WORKSHOP_REF,'country_ref':self.COUNTRY_REF,
               'integrity':p['integrity_max'],'energy':p['energy_max'],'status':'OPERATIONAL','cycles':0,
               'canonical_location_ref':self.WORKSHOP_REF,'machine_identity_authority':self.GAMEPLAY_AUTHORITY,
               'energy_contract':copy.deepcopy(self.ENERGY_CONTRACT)}
            self._save_machine(m); self.items.ensure_inventory(ref,slot_capacity=96,weight_capacity=min(float(p['capacity_kg']),float(self.items.MAX_WEIGHT_CAPACITY)))

    def _event_existing(self,event_ref,event_type,payload):
        row=self.runtime.conn.execute('SELECT event_type,payload_hash,result_json,result_hash FROM arpg_technology_events WHERE world_instance_id=? AND event_ref=?',(self.world_instance_id,str(event_ref))).fetchone()
        if not row:return None
        _,ph=self._payload(payload)
        if row['event_type']!=event_type or row['payload_hash']!=ph: raise ConflictError('technology event_ref conflict')
        if sha256_text(row['result_json'])!=row['result_hash']: raise IntegrityError('technology event result hash mismatch')
        out=json.loads(row['result_json']); out['idempotent_replay']=True; return out
    def _record(self,event_ref,event_type,payload,result):
        pt,ph=self._payload(payload); rt,rh=self._payload(result)
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT INTO arpg_technology_events VALUES(?,?,?,?,?,?)',(self.world_instance_id,str(event_ref),event_type,ph,rt,rh))
        return result

    def _actor_exists(self,ref):
        try:self.engine.arpg(self.world_instance_id).profile(ref); return 'PLAYER_PROFILE'
        except Exception:pass
        try:self.country.npc(ref); return 'COUNTRY_NPC'
        except Exception:raise ValidationError('unknown technology operator_ref')
    def _operator_binding(self,ref):
        kind=self._actor_exists(ref)
        # Stage11 may use local workshop professions when an NPC already has/receives such a job through Living.
        # No canonical robotics operator is asserted in TER-011.
        return {'operator_ref':ref,'operator_kind':kind,'robotics_profession_ref':None,
                'authority':'GAMEPLAY_DERIVED_SUPERVISION_TER_011','canon_guard':'JOB-LOG-ROBOTICA-001_DISTRIBUTED_TER_001_NOT_TER_011'}

    def create_machine(self,owner_ref,profile_ref,location_ref,*,event_ref):
        payload={'owner_ref':owner_ref,'profile_ref':profile_ref,'location_ref':location_ref}; old=self._event_existing(event_ref,'CREATE_MACHINE',payload)
        if old:return old
        self._actor_exists(owner_ref); p=self.machine_profile(profile_ref)
        ref=self._stable_ref('MACH-',event_ref,owner_ref,profile_ref,location_ref)
        m={'machine_ref':ref,'profile_ref':profile_ref,'owner_ref':owner_ref,'location_ref':location_ref,'country_ref':self.COUNTRY_REF,
           'integrity':p['integrity_max'],'energy':p['energy_max'],'status':'OPERATIONAL','cycles':0,'machine_identity_authority':self.GAMEPLAY_AUTHORITY,'energy_contract':copy.deepcopy(self.ENERGY_CONTRACT)}
        self._save_machine(m); self.items.ensure_inventory(ref,slot_capacity=96,weight_capacity=min(float(p['capacity_kg']),float(self.items.MAX_WEIGHT_CAPACITY)))
        return self._record(event_ref,'CREATE_MACHINE',payload,{'status':'PASS','machine':m})

    def create_robot(self,owner_ref,profile_ref,*,event_ref):
        payload={'owner_ref':owner_ref,'profile_ref':profile_ref}; old=self._event_existing(event_ref,'CREATE_ROBOT',payload)
        if old:return old
        binding=self._operator_binding(owner_ref); p=self.robot_profile(profile_ref); ref=self._stable_ref('RBT-',event_ref,owner_ref,profile_ref)
        r={'robot_ref':ref,'profile_ref':profile_ref,'owner_ref':owner_ref,'operator_binding':binding,'integrity':p['integrity_max'],'energy':p['energy_max'],
           'status':'IDLE','task_count':0,'legal_status':'TECHNOLOGICAL_ASSET_NOT_NPC_NOT_LEGAL_WORKER','disposition':'NEUTRAL','authority':self.GAMEPLAY_AUTHORITY}
        self._save_robot(r); self.items.ensure_inventory(ref,slot_capacity=64,weight_capacity=min(float(p['cargo_kg']),float(self.items.MAX_WEIGHT_CAPACITY)))
        # Actor projection is allowed for perception/combat, but it remains a tech asset.
        try:self.actors.ensure_actor(ref)
        except Exception:pass
        return self._record(event_ref,'CREATE_ROBOT',payload,{'status':'PASS','robot':r})

    def recipe(self,ref):
        if ref not in self.RECIPES: raise NotFoundError('technology recipe not found')
        return {'recipe_ref':ref,**copy.deepcopy(self.RECIPES[ref]),'canon_guard':'NUMERIC_RECIPE_NOT_CANONICAL'}
    def list_recipes(self): return [self.recipe(r) for r in sorted(self.RECIPES)]

    def _inventory_count(self,owner_ref,item_ref):
        inv=self.items.inventory_snapshot(owner_ref); return int(inv.get('stacks',{}).get(item_ref,0))

    def run_recipe(self,operator_ref,machine_ref,recipe_ref,*,event_ref):
        payload={'operator_ref':operator_ref,'machine_ref':machine_ref,'recipe_ref':recipe_ref}; old=self._event_existing(event_ref,'RUN_RECIPE',payload)
        if old:return old
        self._actor_exists(operator_ref); m=self.machine(machine_ref); p=self.machine_profile(m['profile_ref']); r=self.recipe(recipe_ref)
        if p['machine_class']!=r['machine_class']: return self._record(event_ref,'RUN_RECIPE',payload,{'status':'REJECTED','reason':'MACHINE_CLASS_MISMATCH'})
        if m['status']!='OPERATIONAL' or m['integrity']<=10: return self._record(event_ref,'RUN_RECIPE',payload,{'status':'REJECTED','reason':'MACHINE_NOT_OPERATIONAL'})
        if float(m['energy'])<float(p['cycle_energy']): return self._record(event_ref,'RUN_RECIPE',payload,{'status':'REJECTED','reason':'INSUFFICIENT_MACHINE_ENERGY'})
        for item,qty in r['inputs'].items():
            if self._inventory_count(operator_ref,item)<int(qty): return self._record(event_ref,'RUN_RECIPE',payload,{'status':'REJECTED','reason':'MISSING_INPUT','item_ref':item})
        for item,qty in r['inputs'].items(): self.items.remove_item(operator_ref,item,int(qty),event_ref=f'{event_ref}:consume:{item}')
        for item,qty in r['outputs'].items(): self.items.grant_item(operator_ref,item,int(qty),event_ref=f'{event_ref}:produce:{item}')
        m['energy']=round(max(0.0,float(m['energy'])-float(p['cycle_energy'])),6); m['integrity']=round(max(0.0,float(m['integrity'])-float(p['wear_per_cycle'])),6); m['cycles']=int(m.get('cycles',0))+1
        if m['integrity']<=10:m['status']='MAINTENANCE_REQUIRED'
        self._save_machine(m)
        return self._record(event_ref,'RUN_RECIPE',payload,{'status':'PASS','recipe_ref':recipe_ref,'outputs':r['outputs'],'machine':m})

    def recharge_machine(self,operator_ref,machine_ref,cell_units:int,*,event_ref):
        payload={'operator_ref':operator_ref,'machine_ref':machine_ref,'cell_units':int(cell_units)}; old=self._event_existing(event_ref,'RECHARGE_MACHINE',payload)
        if old:return old
        self._actor_exists(operator_ref); n=int(cell_units)
        if n<=0: raise ValidationError('cell_units must be positive')
        if self._inventory_count(operator_ref,'ITEM-ENERGY-CELL')<n: return self._record(event_ref,'RECHARGE_MACHINE',payload,{'status':'REJECTED','reason':'MISSING_ENERGY_CELL'})
        m=self.machine(machine_ref); p=self.machine_profile(m['profile_ref']); self.items.remove_item(operator_ref,'ITEM-ENERGY-CELL',n,event_ref=f'{event_ref}:cells')
        m['energy']=round(min(float(p['energy_max']),float(m['energy'])+20.0*n),6); self._save_machine(m)
        return self._record(event_ref,'RECHARGE_MACHINE',payload,{'status':'PASS','machine':m,'energy_contract':copy.deepcopy(self.ENERGY_CONTRACT)})

    def repair_machine(self,operator_ref,machine_ref,repair_units:int,*,event_ref):
        payload={'operator_ref':operator_ref,'machine_ref':machine_ref,'repair_units':int(repair_units)}; old=self._event_existing(event_ref,'REPAIR_MACHINE',payload)
        if old:return old
        self._actor_exists(operator_ref); n=int(repair_units)
        if n<=0: raise ValidationError('repair_units must be positive')
        if self._inventory_count(operator_ref,'MIN-IRON')<n: return self._record(event_ref,'REPAIR_MACHINE',payload,{'status':'REJECTED','reason':'MISSING_REPAIR_MATERIAL'})
        m=self.machine(machine_ref); p=self.machine_profile(m['profile_ref']); self.items.remove_item(operator_ref,'MIN-IRON',n,event_ref=f'{event_ref}:repair-material')
        m['integrity']=round(min(float(p['integrity_max']),float(m['integrity'])+10.0*n),6); m['status']='OPERATIONAL' if m['integrity']>10 else 'MAINTENANCE_REQUIRED'; self._save_machine(m)
        return self._record(event_ref,'REPAIR_MACHINE',payload,{'status':'PASS','machine':m,'profession_support_refs':['JOB-TEC-OFICINA-001','JOB-MFG-REPARO-001','JOB-MNT-CAMPO-001']})

    def robot_task_transfer(self,operator_ref,robot_ref,source_owner_ref,dest_owner_ref,item_ref,quantity:int,*,event_ref):
        payload={'operator_ref':operator_ref,'robot_ref':robot_ref,'source_owner_ref':source_owner_ref,'dest_owner_ref':dest_owner_ref,'item_ref':item_ref,'quantity':int(quantity)}; old=self._event_existing(event_ref,'ROBOT_LOGISTICS_TRANSFER',payload)
        if old:return old
        self._actor_exists(operator_ref); r=self.robot(robot_ref); p=self.robot_profile(r['profile_ref'])
        if r['owner_ref']!=operator_ref: return self._record(event_ref,'ROBOT_LOGISTICS_TRANSFER',payload,{'status':'REJECTED','reason':'ROBOT_OPERATOR_MISMATCH'})
        if r['status']=='DISABLED' or r['integrity']<=10:return self._record(event_ref,'ROBOT_LOGISTICS_TRANSFER',payload,{'status':'REJECTED','reason':'ROBOT_DISABLED'})
        if float(r['energy'])<float(p['task_energy']):return self._record(event_ref,'ROBOT_LOGISTICS_TRANSFER',payload,{'status':'REJECTED','reason':'INSUFFICIENT_ROBOT_ENERGY'})
        q=int(quantity)
        if q<=0: raise ValidationError('quantity must be positive')
        self.items.transfer_item(source_owner_ref,dest_owner_ref,item_ref,q,event_ref=f'{event_ref}:transfer')
        r['energy']=round(float(r['energy'])-float(p['task_energy']),6); r['task_count']=int(r.get('task_count',0))+1; r['status']='IDLE'; self._save_robot(r)
        return self._record(event_ref,'ROBOT_LOGISTICS_TRANSFER',payload,{'status':'PASS','robot':r,'operator_binding':r['operator_binding'],'robot_legal_status':r['legal_status']})

    def recharge_robot(self,operator_ref,robot_ref,cell_units:int,*,event_ref):
        payload={'operator_ref':operator_ref,'robot_ref':robot_ref,'cell_units':int(cell_units)}; old=self._event_existing(event_ref,'RECHARGE_ROBOT',payload)
        if old:return old
        self._actor_exists(operator_ref); r=self.robot(robot_ref); p=self.robot_profile(r['profile_ref']); n=int(cell_units)
        if n<=0:raise ValidationError('cell_units must be positive')
        if r['owner_ref']!=operator_ref:return self._record(event_ref,'RECHARGE_ROBOT',payload,{'status':'REJECTED','reason':'ROBOT_OPERATOR_MISMATCH'})
        if self._inventory_count(operator_ref,'ITEM-ENERGY-CELL')<n:return self._record(event_ref,'RECHARGE_ROBOT',payload,{'status':'REJECTED','reason':'MISSING_ENERGY_CELL'})
        self.items.remove_item(operator_ref,'ITEM-ENERGY-CELL',n,event_ref=f'{event_ref}:cells'); r['energy']=round(min(float(p['energy_max']),float(r['energy'])+20*n),6); self._save_robot(r)
        return self._record(event_ref,'RECHARGE_ROBOT',payload,{'status':'PASS','robot':r})

    def bind_vehicle_energy(self,vehicle_ref,*,event_ref):
        payload={'vehicle_ref':vehicle_ref}; old=self._event_existing(event_ref,'BIND_VEHICLE_ENERGY',payload)
        if old:return old
        v=self.mobility.vehicle(vehicle_ref); v['stage11_energy_contract']=copy.deepcopy(self.ENERGY_CONTRACT); v['propulsion_authority']='STAGE11_TECH_ENERGY_BINDING_GAMEPLAY_DERIVED_SOURCE_UNSPECIFIED'; self.mobility._save_vehicle(v)
        return self._record(event_ref,'BIND_VEHICLE_ENERGY',payload,{'status':'PASS','vehicle':v,'energy_contract':copy.deepcopy(self.ENERGY_CONTRACT)})

    def verify(self):
        failures=[]
        try:
            if self.canonical_snapshot(self.WORKSHOP_REF).get('territory_refs')!=[self.COUNTRY_REF]: failures.append('WORKSHOP_TERRITORY')
            if self.canonical_snapshot(self.ROBOTICS_JOB_REF).get('territory_refs')==[self.COUNTRY_REF]: failures.append('ROBOTICS_JOB_GUARD_BROKEN')
            if len(self.list_machine_profiles())!=4: failures.append('MACHINE_PROFILE_COUNT')
            if len(self.list_robot_profiles())!=3: failures.append('ROBOT_PROFILE_COUNT')
            if len(self.list_machines())<3: failures.append('WORKSHOP_MACHINE_BOOTSTRAP')
            if self.ENERGY_CONTRACT['canonical_source_type']!='UNSPECIFIED_BY_TER_011_CANON': failures.append('ENERGY_CANON_GUARD')
            for m in self.list_machines():
                if m.get('canonical_location_ref')==self.WORKSHOP_REF and m.get('location_ref')!=self.WORKSHOP_REF: failures.append('MACHINE_LOCATION_DRIFT')
        except Exception as e: failures.append(type(e).__name__+':'+str(e))
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'machines':len(self.list_machines()),'robots':len(self.list_robots()),'machine_profiles':len(self.list_machine_profiles()),'robot_profiles':len(self.list_robot_profiles()),'recipes':len(self.RECIPES),'authority':self.AUTHORITY}
