from __future__ import annotations

import copy
import json
import math
import sqlite3
import threading
import zipfile
from pathlib import Path
from typing import Any

from living_runtime import (
    LivingRuntime, ValidationError, IntegrityError, ConflictError, NotFoundError,
    OfflinePolicyError, canonical_json, sha256_text, new_runtime_id, validate_runtime_id,
    clock_point, MASTER_RELEASE_SHA256,
)
from agent_brain import IntentValidator

MASTER_FAUNA_PATH = "ANDROMEDA_CODEX_MASTER/03_DOMAINS/SPATIALIZATION/02_DISTRIBUICOES/STELLAR_FAUNA_DISTRIBUTION_V1_0.json"
MASTER_ENTITY_INDEX_PATH = "ANDROMEDA_CODEX_MASTER/02_ATLAS/STAGE_08_REFERENCE/01_DATA/ATLAS_ENTITY_INDEX_V1_0.json"

DIETS = {"HERBIVORE", "CARNIVORE", "OMNIVORE", "DETRITIVORE", "NECTARIVORE", "INSECTIVORE"}
SOCIAL_STRUCTURES = {"SOLITARY", "PAIR", "HERD", "PACK", "FLOCK", "SCHOOL", "SWARM", "COLONY"}
COGNITION_MODES = {"INSTINCTIVE", "ADAPTIVE", "COGNITIVE"}
ACTIVITY_MODES = {"DIURNAL", "NOCTURNAL", "CREPUSCULAR", "CATHEMERAL"}
GROUP_ROLES = {"LEADER", "MEMBER", "JUVENILE", "SCOUT", "GUARD"}
OBS_KINDS = {"FOOD", "WATER", "PREY", "PREDATOR", "THREAT", "MATE", "SHELTER", "HABITAT", "GROUP", "SETTLEMENT"}


def _num(v: Any, name: str, lo: float | None = None, hi: float | None = None) -> float:
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(float(v)):
        raise ValidationError(f"{name} must be finite number")
    f = float(v)
    if lo is not None and f < lo:
        raise ValidationError(f"{name} below minimum {lo}")
    if hi is not None and f > hi:
        raise ValidationError(f"{name} above maximum {hi}")
    return f


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _path_get(obj: Any, path: str, default: Any = None) -> Any:
    cur = obj
    for p in path.split('.'):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


class EcologySystem:
    """Specialized animal/creature cognition and bounded ecological simulation.

    Canon fauna data is snapshotted read-only from the sealed Master. Behavioural traits
    are runtime simulation profiles and are never promoted to canon by this component.
    """

    SCHEMA_VERSION = 1

    def __init__(self, runtime: LivingRuntime, validator: IntentValidator) -> None:
        self.runtime = runtime
        self.validator = validator
        self.conn = runtime.conn
        self._lock = threading.RLock()
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self.runtime._write_lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS fauna_snapshots(
                    species_ref TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    distribution_json TEXT NOT NULL,
                    distribution_hash TEXT NOT NULL,
                    source_release_sha256 TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS fauna_snapshots_no_update BEFORE UPDATE ON fauna_snapshots BEGIN SELECT RAISE(ABORT,'fauna snapshots are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS fauna_snapshots_no_delete BEFORE DELETE ON fauna_snapshots BEGIN SELECT RAISE(ABORT,'fauna snapshots are immutable'); END;

                CREATE TABLE IF NOT EXISTS ecology_species_profiles(
                    profile_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    species_ref TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('ACTIVE','DISABLED')),
                    profile_json TEXT NOT NULL,
                    profile_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id,species_ref)
                );
                CREATE TABLE IF NOT EXISTS ecology_observations(
                    observation_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    animal_ref TEXT NOT NULL,
                    observed_day INTEGER NOT NULL,
                    observed_tick INTEGER NOT NULL,
                    observation_json TEXT NOT NULL,
                    observation_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_eco_obs_animal ON ecology_observations(world_instance_id,animal_ref,observed_day DESC,observed_tick DESC);
                CREATE TRIGGER IF NOT EXISTS ecology_observations_no_update BEFORE UPDATE ON ecology_observations BEGIN SELECT RAISE(ABORT,'ecology observations are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS ecology_observations_no_delete BEFORE DELETE ON ecology_observations BEGIN SELECT RAISE(ABORT,'ecology observations are immutable'); END;

                CREATE TABLE IF NOT EXISTS territory_memories(
                    memory_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    animal_ref TEXT NOT NULL,
                    territory_ref TEXT NOT NULL,
                    recorded_day INTEGER NOT NULL,
                    memory_json TEXT NOT NULL,
                    memory_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_territory_memories ON territory_memories(world_instance_id,animal_ref,territory_ref,recorded_day DESC);
                CREATE TRIGGER IF NOT EXISTS territory_memories_no_update BEFORE UPDATE ON territory_memories BEGIN SELECT RAISE(ABORT,'territory memories are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS territory_memories_no_delete BEFORE DELETE ON territory_memories BEGIN SELECT RAISE(ABORT,'territory memories are immutable'); END;

                CREATE TABLE IF NOT EXISTS animal_groups(
                    group_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    species_ref TEXT NOT NULL,
                    group_type TEXT NOT NULL,
                    territory_ref TEXT,
                    group_json TEXT NOT NULL,
                    group_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS animal_group_members(
                    membership_id TEXT PRIMARY KEY,
                    group_id TEXT NOT NULL REFERENCES animal_groups(group_id) ON DELETE CASCADE,
                    world_instance_id TEXT NOT NULL,
                    animal_ref TEXT NOT NULL,
                    role TEXT NOT NULL,
                    rank_score REAL NOT NULL,
                    member_json TEXT NOT NULL,
                    member_hash TEXT NOT NULL,
                    UNIQUE(group_id,animal_ref)
                );

                CREATE TABLE IF NOT EXISTS ecology_decisions(
                    decision_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    animal_ref TEXT NOT NULL,
                    intent_id TEXT,
                    decision_json TEXT NOT NULL,
                    decision_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_eco_decisions ON ecology_decisions(world_instance_id,animal_ref);

                CREATE TABLE IF NOT EXISTS ecology_births(
                    birth_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    reproduction_event_id TEXT NOT NULL UNIQUE,
                    parent_a_ref TEXT NOT NULL,
                    parent_b_ref TEXT NOT NULL,
                    child_ref TEXT NOT NULL UNIQUE,
                    birth_json TEXT NOT NULL,
                    birth_hash TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ecology_populations_current(
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    species_ref TEXT NOT NULL,
                    territory_ref TEXT NOT NULL,
                    count INTEGER NOT NULL CHECK(count>=0),
                    carrying_capacity INTEGER NOT NULL CHECK(carrying_capacity>0),
                    resource_index REAL NOT NULL,
                    water_index REAL NOT NULL,
                    climate_comfort REAL NOT NULL,
                    version INTEGER NOT NULL CHECK(version>=0),
                    population_json TEXT NOT NULL,
                    population_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id,species_ref,territory_ref)
                );
                CREATE TABLE IF NOT EXISTS ecology_population_deltas(
                    delta_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL,
                    species_ref TEXT NOT NULL,
                    territory_ref TEXT NOT NULL,
                    delta_count INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    occurred_day INTEGER NOT NULL,
                    occurred_tick INTEGER NOT NULL,
                    delta_json TEXT NOT NULL,
                    delta_hash TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS ecology_population_deltas_no_update BEFORE UPDATE ON ecology_population_deltas BEGIN SELECT RAISE(ABORT,'population deltas are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS ecology_population_deltas_no_delete BEFORE DELETE ON ecology_population_deltas BEGIN SELECT RAISE(ABORT,'population deltas are immutable'); END;

                CREATE TABLE IF NOT EXISTS food_web_links(
                    link_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    predator_species_ref TEXT NOT NULL,
                    prey_species_ref TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('ACTIVE','DISABLED')),
                    link_json TEXT NOT NULL,
                    link_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id,predator_species_ref,prey_species_ref)
                );
                CREATE TABLE IF NOT EXISTS ecology_routine_ticks(
                    tick_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL,
                    tick_key TEXT NOT NULL,
                    tick_json TEXT NOT NULL,
                    tick_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id,tick_key)
                );
                """
            )

    # ---------- Canon snapshot boundary ----------
    def load_master_fauna_snapshots(self, master_release_path: str | Path | None = None) -> dict[str, Any]:
        path = str(master_release_path or self.runtime.master_release_path or "")
        if not path:
            raise IntegrityError("master release path required")
        actual = self.runtime._file_sha256(path)
        # Runtime constructor owns the supported-baseline decision; modules re-check the verified baseline.
        if actual != self.runtime.master_release_sha256:
            raise IntegrityError("master release hash changed after runtime initialization")
        with zipfile.ZipFile(path, 'r') as zf:
            dist = json.loads(zf.read(MASTER_FAUNA_PATH))
            idx = json.loads(zf.read(MASTER_ENTITY_INDEX_PATH))
        entries = {e.get('id'): e for e in idx.get('entries', []) if isinstance(e, dict)}
        distributions = dist.get('distributions')
        if not isinstance(distributions, list) or dist.get('count') != len(distributions):
            raise IntegrityError("master fauna distribution count mismatch")
        inserted = 0
        with self._lock, self.runtime._write_lock:
            self.runtime._begin()
            try:
                for d in distributions:
                    species_ref = d.get('entity_id')
                    if not isinstance(species_ref, str) or species_ref not in entries:
                        raise IntegrityError(f"fauna distribution unresolved: {species_ref}")
                    if entries[species_ref].get('domain') != 'Fauna':
                        raise IntegrityError(f"fauna distribution points to non-fauna entity: {species_ref}")
                    body = copy.deepcopy(d)
                    text = canonical_json(body)
                    h = sha256_text(text)
                    existing = self.conn.execute("SELECT distribution_hash FROM fauna_snapshots WHERE species_ref=?", (species_ref,)).fetchone()
                    if existing:
                        if existing['distribution_hash'] != h:
                            raise IntegrityError(f"fauna snapshot drift detected: {species_ref}")
                        continue
                    self.conn.execute(
                        "INSERT INTO fauna_snapshots VALUES(?,?,?,?,?)",
                        (species_ref, entries[species_ref].get('name') or species_ref, text, h, actual),
                    )
                    inserted += 1
                self.runtime._commit()
            except Exception:
                self.runtime._rollback(); raise
        return {"status":"PASS","master_count":len(distributions),"inserted":inserted,"total":self.conn.execute("SELECT COUNT(*) c FROM fauna_snapshots").fetchone()['c']}

    def get_fauna_snapshot(self, species_ref: str) -> dict[str, Any]:
        with self.runtime._write_lock:
            row = self.conn.execute("SELECT * FROM fauna_snapshots WHERE species_ref=?", (species_ref,)).fetchone()
        if not row:
            raise NotFoundError(f"fauna species snapshot not loaded: {species_ref}")
        if sha256_text(row['distribution_json']) != row['distribution_hash']:
            raise IntegrityError("fauna snapshot hash mismatch")
        body = json.loads(row['distribution_json'])
        body['name'] = row['name']
        return body

    def habitat_allows(self, species_ref: str, territory_ref: str, biome_ref: str | None = None) -> bool:
        self._validate_territory_ref(territory_ref)
        self._validate_biome_ref(biome_ref)
        d = self.get_fauna_snapshot(species_ref)
        p = d.get('distribution_primary') or {}
        territories = {p.get('territory_id')} | set(d.get('distribution_secondary_territory_ids') or [])
        if territory_ref not in territories:
            return False
        if biome_ref is None:
            return True
        biomes = set(d.get('biome_ids') or []) | set(p.get('biome_ids') or [])
        return biome_ref in biomes

    def _validate_territory_ref(self, territory_ref: str) -> None:
        if not isinstance(territory_ref, str) or not territory_ref.startswith('TER-'):
            raise ValidationError('invalid territory_ref')
        if self.runtime.canonical_ids is not None and not self.runtime.canonical_ref_resolves(territory_ref):
            raise ValidationError(f'unknown canonical territory_ref: {territory_ref}')

    def _validate_biome_ref(self, biome_ref: str | None) -> None:
        if biome_ref is None:
            return
        if not isinstance(biome_ref, str) or not biome_ref.startswith('BIO-'):
            raise ValidationError('invalid biome_ref')
        if self.runtime.canonical_ids is not None and not self.runtime.canonical_ref_resolves(biome_ref):
            raise ValidationError(f'unknown canonical biome_ref: {biome_ref}')

    # ---------- Runtime species profiles ----------
    def register_species_profile(self, world_instance_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        world = self.runtime.get_world(world_instance_id)
        p = copy.deepcopy(profile)
        required = ['species_ref','diet','social_structure','cognition_mode','activity_mode']
        missing = [k for k in required if k not in p]
        if missing: raise ValidationError(f"missing species profile fields: {missing}")
        self.get_fauna_snapshot(p['species_ref'])
        if p['diet'] not in DIETS: raise ValidationError('invalid diet')
        if p['social_structure'] not in SOCIAL_STRUCTURES: raise ValidationError('invalid social_structure')
        if p['cognition_mode'] not in COGNITION_MODES: raise ValidationError('invalid cognition_mode')
        if p['activity_mode'] not in ACTIVITY_MODES: raise ValidationError('invalid activity_mode')
        defaults = {
            'hunger_threshold':60,'thirst_threshold':60,'rest_threshold':30,'flee_threshold':70,
            'migration_pressure_threshold':70,'reproduction_threshold':75,'maturity_days':30,
            'population_growth_rate':0.03,'predation_rate':0.02,'territoriality':50,'sociality':50,
            'risk_tolerance':50,'max_group_size':20,'range_excursion_allowed':False,
            'routine_population_change_cap_fraction':0.05,'status':'ACTIVE',
        }
        for k,v in defaults.items(): p.setdefault(k,v)
        for k in ['hunger_threshold','thirst_threshold','rest_threshold','flee_threshold','migration_pressure_threshold','reproduction_threshold','territoriality','sociality','risk_tolerance']:
            p[k] = _num(p[k],k,0,100)
        p['population_growth_rate']=_num(p['population_growth_rate'],'population_growth_rate',0,0.25)
        p['predation_rate']=_num(p['predation_rate'],'predation_rate',0,0.25)
        p['routine_population_change_cap_fraction']=_num(p['routine_population_change_cap_fraction'],'routine cap',0,0.10)
        if not isinstance(p['maturity_days'], int) or p['maturity_days'] < 0: raise ValidationError('maturity_days invalid')
        if not isinstance(p['max_group_size'], int) or p['max_group_size'] < 1: raise ValidationError('max_group_size invalid')
        if not isinstance(p['range_excursion_allowed'], bool): raise ValidationError('range_excursion_allowed invalid')
        if p['status'] not in {'ACTIVE','DISABLED'}: raise ValidationError('profile status invalid')
        p['authority']='RUNTIME_SIMULATION_PROFILE_NOT_CANON'
        p['profile_id']=p.get('profile_id') or new_runtime_id('ecoprofile')
        validate_runtime_id(p['profile_id'],'ecoprofile')
        body={'profile_id':p['profile_id'],'world_instance_id':world_instance_id,'timeline_id':world['timeline_id'],**p}
        text=canonical_json(body); h=sha256_text(text)
        with self._lock, self.runtime._write_lock:
            self.conn.execute("INSERT INTO ecology_species_profiles VALUES(?,?,?,?,?,?)",
                              (body['profile_id'],world_instance_id,body['species_ref'],body['status'],text,h))
        body['profile_hash']=h; return body

    def get_species_profile(self, world_instance_id: str, species_ref: str) -> dict[str, Any]:
        with self.runtime._write_lock:
            row=self.conn.execute("SELECT * FROM ecology_species_profiles WHERE world_instance_id=? AND species_ref=?",(world_instance_id,species_ref)).fetchone()
        if not row: raise NotFoundError(f"species runtime profile missing: {species_ref}")
        if sha256_text(row['profile_json']) != row['profile_hash']: raise IntegrityError('species profile hash mismatch')
        return json.loads(row['profile_json'])

    # ---------- Policy installation ----------
    def install_default_action_policies(self, world_instance_id: str) -> dict[str, Any]:
        policies = [
            {'policy_key':'eco.forage','action_type':'ECO_FORAGE','allowed_sources':['AGENT_BRAIN'],'actor_kinds':['ANIMAL','CREATURE'],'target_required':True,'target_kinds':['ECO_RESOURCE'],'offline_policy':'ACTIVE_ONLY','target_state_equals':{'lifecycle':'ACTIVE'},'parameter_schema':{'amount':{'type':'number','required':True,'min':0.1,'max':100}},'resource_requirements':[{'field_path':'data.ecology.hunger','min_from_parameter':'amount','consume_amount':0}],'target_resource_requirements':[{'field_path':'data.quantity','min_from_parameter':'amount','consume_from_parameter':'amount'}],'consequence_templates':[{'target':'ACTOR','operation':'DECREMENT','field_path':'data.ecology.hunger','amount_from_parameter':'amount'}]},
            {'policy_key':'eco.drink','action_type':'ECO_DRINK','allowed_sources':['AGENT_BRAIN'],'actor_kinds':['ANIMAL','CREATURE'],'target_required':True,'target_kinds':['ECO_RESOURCE'],'offline_policy':'ACTIVE_ONLY','target_state_equals':{'lifecycle':'ACTIVE'},'parameter_schema':{'amount':{'type':'number','required':True,'min':0.1,'max':100}},'resource_requirements':[{'field_path':'data.ecology.thirst','min_from_parameter':'amount','consume_amount':0}],'target_resource_requirements':[{'field_path':'data.quantity','min_from_parameter':'amount','consume_from_parameter':'amount'}],'consequence_templates':[{'target':'ACTOR','operation':'DECREMENT','field_path':'data.ecology.thirst','amount_from_parameter':'amount'}]},
            {'policy_key':'eco.rest','action_type':'ECO_REST','allowed_sources':['AGENT_BRAIN'],'actor_kinds':['ANIMAL','CREATURE'],'target_required':False,'offline_policy':'ACTIVE_ONLY','parameter_schema':{},'consequence_templates':[{'target':'ACTOR','operation':'INCREMENT','field_path':'data.ecology.energy','amount':30}]},
            {'policy_key':'eco.flee','action_type':'ECO_FLEE','allowed_sources':['AGENT_BRAIN'],'actor_kinds':['ANIMAL','CREATURE'],'target_required':False,'offline_policy':'ACTIVE_ONLY','parameter_schema':{},'resource_requirements':[{'field_path':'data.ecology.energy','min_value':10,'consume_amount':0}],'consequence_templates':[{'target':'ACTOR','operation':'SET','field_path':'data.ecology.threat_pressure','value':0},{'target':'ACTOR','operation':'DECREMENT','field_path':'data.ecology.energy','amount':10}]},
            {'policy_key':'eco.migrate','action_type':'ECO_MIGRATE','allowed_sources':['AGENT_BRAIN'],'actor_kinds':['ANIMAL','CREATURE'],'target_required':False,'offline_policy':'ACTIVE_ONLY','parameter_schema':{'destination_ref':{'type':'string','required':True}},'resource_requirements':[{'field_path':'data.ecology.energy','min_value':15,'consume_amount':0}],'consequence_templates':[{'target':'ACTOR','operation':'SET','field_path':'data.ecology.territory_ref','value_from_parameter':'destination_ref'},{'target':'ACTOR','operation':'DECREMENT','field_path':'data.ecology.energy','amount':15}]},
            {'policy_key':'eco.hunt','action_type':'ECO_HUNT','allowed_sources':['AGENT_BRAIN'],'actor_kinds':['ANIMAL','CREATURE'],'target_required':True,'target_kinds':['ANIMAL','CREATURE'],'offline_policy':'ACTIVE_ONLY','target_state_equals':{'lifecycle':'ACTIVE'},'parameter_schema':{},'resource_requirements':[{'field_path':'data.ecology.energy','min_value':20,'consume_amount':0}],'protection_impacts':['DEATH'],'consequence_templates':[{'target':'TARGET','operation':'TRANSITION','field_path':'lifecycle','from':'ACTIVE','value':'DEAD'},{'target':'ACTOR','operation':'DECREMENT','field_path':'data.ecology.hunger','amount':50},{'target':'ACTOR','operation':'DECREMENT','field_path':'data.ecology.energy','amount':20}]},
            {'policy_key':'eco.reproduce','action_type':'ECO_REPRODUCE','allowed_sources':['AGENT_BRAIN'],'actor_kinds':['ANIMAL','CREATURE'],'target_required':True,'target_kinds':['ANIMAL','CREATURE'],'offline_policy':'ACTIVE_ONLY','target_state_equals':{'lifecycle':'ACTIVE'},'parameter_schema':{},'resource_requirements':[{'field_path':'data.ecology.energy','min_value':20,'consume_amount':0}],'target_resource_requirements':[{'field_path':'data.ecology.energy','min_value':20,'consume_amount':0}],'consequence_templates':[{'target':'ACTOR','operation':'SET','field_path':'data.ecology.reproduction_drive','value':0},{'target':'TARGET','operation':'SET','field_path':'data.ecology.reproduction_drive','value':0},{'target':'ACTOR','operation':'DECREMENT','field_path':'data.ecology.energy','amount':20},{'target':'TARGET','operation':'DECREMENT','field_path':'data.ecology.energy','amount':20}]},
            {'policy_key':'eco.patrol','action_type':'ECO_PATROL','allowed_sources':['AGENT_BRAIN'],'actor_kinds':['ANIMAL','CREATURE'],'target_required':False,'offline_policy':'ACTIVE_ONLY','parameter_schema':{},'resource_requirements':[{'field_path':'data.ecology.energy','min_value':5,'consume_amount':0}],'consequence_templates':[{'target':'ACTOR','operation':'DECREMENT','field_path':'data.ecology.energy','amount':5}]},
        ]
        installed=[]; existing=[]
        for p in policies:
            try:
                installed.append(self.validator.register_policy(world_instance_id,p)['action_type'])
            except ConflictError:
                existing.append(p['action_type'])
        return {'status':'PASS','installed':installed,'existing':existing}

    # ---------- Entity/resource materialization ----------
    def create_resource(self, world_instance_id: str, *, resource_type: str, quantity: float, territory_ref: str, biome_ref: str | None = None) -> dict[str, Any]:
        world=self.runtime.get_world(world_instance_id); self._validate_territory_ref(territory_ref); self._validate_biome_ref(biome_ref); c=world['clock_state']; q=_num(quantity,'quantity',0)
        state={'state_id':new_runtime_id('state'),'world_instance_id':world_instance_id,'timeline_id':world['timeline_id'],'entity_runtime_id':new_runtime_id('eco_resource'),'origin':'RUNTIME_BORN','entity_kind':'ECO_RESOURCE','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{'resource_type':resource_type,'quantity':q,'territory_ref':territory_ref,'biome_ref':biome_ref}}
        return self.runtime.register_entity(world_instance_id,state)

    def spawn_animal(self, world_instance_id: str, *, species_ref: str, territory_ref: str, biome_ref: str | None = None,
                     entity_kind: str='ANIMAL', age_days: int=30, sex: str='UNSPECIFIED',
                     hunger: float=20, thirst: float=20, energy: float=80, reproduction_drive: float=0,
                     protection: dict[str,Any] | None=None, parent_refs: list[str] | None=None) -> dict[str, Any]:
        if entity_kind not in {'ANIMAL','CREATURE'}: raise ValidationError('invalid ecological entity kind')
        self._validate_territory_ref(territory_ref); self._validate_biome_ref(biome_ref)
        profile=self.get_species_profile(world_instance_id,species_ref)
        if profile['status']!='ACTIVE': raise ValidationError('species profile disabled')
        if not self.habitat_allows(species_ref,territory_ref,biome_ref) and not profile['range_excursion_allowed']:
            raise ValidationError('spawn habitat outside canonical distribution')
        if not isinstance(age_days,int) or age_days<0: raise ValidationError('age_days invalid')
        world=self.runtime.get_world(world_instance_id); c=world['clock_state']
        data={'species_ref':species_ref,'age_days':age_days,'sex':sex,'mature':age_days>=profile['maturity_days'],'parent_refs':copy.deepcopy(parent_refs or []),'ecology':{'hunger':_num(hunger,'hunger',0,100),'thirst':_num(thirst,'thirst',0,100),'energy':_num(energy,'energy',0,100),'reproduction_drive':_num(reproduction_drive,'reproduction_drive',0,100),'threat_pressure':0.0,'territory_ref':territory_ref,'biome_ref':biome_ref,'home_territory_ref':territory_ref},'simulation_profile_ref':profile['profile_id']}
        state={'state_id':new_runtime_id('state'),'world_instance_id':world_instance_id,'timeline_id':world['timeline_id'],'entity_runtime_id':new_runtime_id(entity_kind.lower()),'origin':'RUNTIME_BORN','entity_kind':entity_kind,'lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':data}
        if protection: state['protection']=copy.deepcopy(protection)
        return self.runtime.register_entity(world_instance_id,state)

    def _animal(self, world_instance_id: str, animal_ref: str, *, active: bool=True) -> dict[str,Any]:
        a=self.runtime.get_entity(world_instance_id,animal_ref)
        if a['entity_kind'] not in {'ANIMAL','CREATURE'}: raise ValidationError('entity is not animal/creature')
        if active and a['lifecycle']!='ACTIVE': raise ValidationError('animal is not active')
        species=_path_get(a,'data.species_ref')
        if not isinstance(species,str): raise ValidationError('animal species_ref missing')
        self.get_species_profile(world_instance_id,species)
        return a

    # ---------- Perception & territorial memory ----------
    def record_observation(self, world_instance_id: str, animal_ref: str, observations: list[dict[str,Any]], *, source: str='SENSORY') -> dict[str,Any]:
        world=self.runtime.get_world(world_instance_id); self._animal(world_instance_id,animal_ref)
        if source not in {'SENSORY','GROUP_SIGNAL','TERRITORIAL_MEMORY','SYSTEM_OBSERVATION'}: raise ValidationError('invalid ecology observation source')
        if not isinstance(observations,list): raise ValidationError('observations must be list')
        cleaned=[]
        for o in observations:
            if not isinstance(o,dict) or o.get('kind') not in OBS_KINDS: raise ValidationError('invalid ecological observation')
            x=copy.deepcopy(o); x['confidence']=_num(x.get('confidence',1),'confidence',0,1)
            if 'target_ref' in x and x['target_ref'] is not None and not isinstance(x['target_ref'],str): raise ValidationError('invalid target_ref')
            for k in ['danger','food_value','water_value','mate_quality','climate_comfort','resource_pressure']:
                if k in x: x[k]=_num(x[k],k,0,100)
            cleaned.append(x)
        c=world['clock_state']; oid=new_runtime_id('ecoobs')
        body={'observation_id':oid,'world_instance_id':world_instance_id,'timeline_id':world['timeline_id'],'animal_ref':animal_ref,'source':source,'observed_at':clock_point(c['day'],c['tick']),'observations':cleaned}
        text=canonical_json(body); h=sha256_text(text)
        with self._lock,self.runtime._write_lock:
            self.conn.execute("INSERT INTO ecology_observations VALUES(?,?,?,?,?,?,?,?)",(oid,world_instance_id,world['timeline_id'],animal_ref,c['day'],c['tick'],text,h))
        body['observation_hash']=h; return body

    def _latest_observation(self, world_instance_id: str, animal_ref: str) -> dict[str,Any] | None:
        with self.runtime._write_lock:
            row=self.conn.execute("SELECT * FROM ecology_observations WHERE world_instance_id=? AND animal_ref=? ORDER BY observed_day DESC,observed_tick DESC,rowid DESC LIMIT 1",(world_instance_id,animal_ref)).fetchone()
        if not row:return None
        if sha256_text(row['observation_json'])!=row['observation_hash']:raise IntegrityError('ecology observation hash mismatch')
        return json.loads(row['observation_json'])

    def remember_territory(self, world_instance_id: str, animal_ref: str, territory_ref: str, *, food_score: float, water_score: float, danger_score: float, success_score: float, notes: dict[str,Any] | None=None) -> dict[str,Any]:
        world=self.runtime.get_world(world_instance_id); self._animal(world_instance_id,animal_ref)
        mid=new_runtime_id('territory_memory'); c=world['clock_state']
        body={'memory_id':mid,'world_instance_id':world_instance_id,'timeline_id':world['timeline_id'],'animal_ref':animal_ref,'territory_ref':territory_ref,'recorded_at':clock_point(c['day'],c['tick']),'food_score':_num(food_score,'food_score',0,100),'water_score':_num(water_score,'water_score',0,100),'danger_score':_num(danger_score,'danger_score',0,100),'success_score':_num(success_score,'success_score',0,100),'notes':copy.deepcopy(notes or {})}
        text=canonical_json(body);h=sha256_text(text)
        with self._lock,self.runtime._write_lock:
            self.conn.execute("INSERT INTO territory_memories VALUES(?,?,?,?,?,?,?,?)",(mid,world_instance_id,world['timeline_id'],animal_ref,territory_ref,c['day'],text,h))
        body['memory_hash']=h;return body

    def territory_preferences(self, world_instance_id: str, animal_ref: str) -> list[dict[str,Any]]:
        self._animal(world_instance_id,animal_ref)
        with self.runtime._write_lock:
            rows=self.conn.execute("SELECT * FROM territory_memories WHERE world_instance_id=? AND animal_ref=? ORDER BY recorded_day DESC,rowid DESC",(world_instance_id,animal_ref)).fetchall()
        by={}
        for r in rows:
            if sha256_text(r['memory_json'])!=r['memory_hash']:raise IntegrityError('territory memory hash mismatch')
            b=json.loads(r['memory_json']); t=b['territory_ref']
            if t in by: continue
            b['preference_score']=round((b['food_score']+b['water_score']+b['success_score']-b['danger_score'])/3,6);by[t]=b
        return sorted(by.values(),key=lambda x:(-x['preference_score'],x['territory_ref']))

    # ---------- Groups & hierarchy ----------
    def create_group(self, world_instance_id: str, *, species_ref: str, group_type: str, territory_ref: str | None=None) -> dict[str,Any]:
        world=self.runtime.get_world(world_instance_id); self._validate_territory_ref(territory_ref) if territory_ref is not None else None; p=self.get_species_profile(world_instance_id,species_ref)
        if group_type not in SOCIAL_STRUCTURES-{'SOLITARY'}: raise ValidationError('invalid group type')
        if p['social_structure']=='SOLITARY': raise ValidationError('solitary species cannot create persistent group')
        gid=new_runtime_id('ecogroup');body={'group_id':gid,'world_instance_id':world_instance_id,'timeline_id':world['timeline_id'],'species_ref':species_ref,'group_type':group_type,'territory_ref':territory_ref,'max_group_size':p['max_group_size']}
        text=canonical_json(body);h=sha256_text(text)
        with self._lock,self.runtime._write_lock:self.conn.execute("INSERT INTO animal_groups VALUES(?,?,?,?,?,?,?,?)",(gid,world_instance_id,world['timeline_id'],species_ref,group_type,territory_ref,text,h))
        body['group_hash']=h;return body

    def add_group_member(self, group_id: str, animal_ref: str, *, role: str='MEMBER', rank_score: float=50) -> dict[str,Any]:
        validate_runtime_id(group_id,'ecogroup')
        if role not in GROUP_ROLES: raise ValidationError('invalid group role')
        rank=_num(rank_score,'rank_score',0,100)
        with self._lock,self.runtime._write_lock:
            g=self.conn.execute("SELECT * FROM animal_groups WHERE group_id=?",(group_id,)).fetchone()
            if not g:raise NotFoundError('group not found')
            if sha256_text(g['group_json'])!=g['group_hash']:raise IntegrityError('group hash mismatch')
            gb=json.loads(g['group_json']); a=self._animal(g['world_instance_id'],animal_ref)
            if _path_get(a,'data.species_ref')!=g['species_ref']:raise ValidationError('group species mismatch')
            count=self.conn.execute("SELECT COUNT(*) c FROM animal_group_members WHERE group_id=?",(group_id,)).fetchone()['c']
            if count>=gb['max_group_size']:raise ConflictError('group capacity reached')
            mid=new_runtime_id('membership');body={'membership_id':mid,'group_id':group_id,'world_instance_id':g['world_instance_id'],'animal_ref':animal_ref,'role':role,'rank_score':rank}
            text=canonical_json(body);h=sha256_text(text)
            self.conn.execute("INSERT INTO animal_group_members VALUES(?,?,?,?,?,?,?,?)",(mid,group_id,g['world_instance_id'],animal_ref,role,rank,text,h))
        body['member_hash']=h;return body

    def group_leader(self, group_id: str) -> dict[str,Any]:
        validate_runtime_id(group_id,'ecogroup')
        with self.runtime._write_lock:
            rows=self.conn.execute("SELECT * FROM animal_group_members WHERE group_id=?",(group_id,)).fetchall()
        if not rows:raise NotFoundError('group has no members')
        members=[]
        for r in rows:
            if sha256_text(r['member_json'])!=r['member_hash']:raise IntegrityError('group member hash mismatch')
            b=json.loads(r['member_json']); b['_role_bias']=1 if b['role']=='LEADER' else 0;members.append(b)
        members.sort(key=lambda x:(-x['_role_bias'],-x['rank_score'],x['animal_ref']))
        members[0].pop('_role_bias',None);return members[0]

    # ---------- Decision system ----------
    def _validate_ecological_state(self, animal: dict[str,Any]) -> dict[str,float]:
        eco=_path_get(animal,'data.ecology')
        if not isinstance(eco,dict):raise ValidationError('animal ecology state missing')
        vals={}
        for k in ['hunger','thirst','energy','reproduction_drive','threat_pressure']:
            vals[k]=_num(eco.get(k),k,0,100)
        if not isinstance(eco.get('territory_ref'),str):raise ValidationError('territory_ref missing')
        return vals

    def _select_destination(self, world_instance_id: str, animal: dict[str,Any], observations: list[dict[str,Any]], profile: dict[str,Any]) -> str | None:
        current=_path_get(animal,'data.ecology.territory_ref')
        candidates=[]
        for o in observations:
            if o['kind']!='HABITAT':continue
            dest=o.get('territory_ref') or o.get('target_ref')
            if not isinstance(dest,str) or dest==current:continue
            biome=o.get('biome_ref')
            if not self.habitat_allows(profile['species_ref'],dest,biome) and not profile['range_excursion_allowed']:continue
            score=float(o.get('food_value',0))+float(o.get('water_value',0))+float(o.get('climate_comfort',50))-float(o.get('danger',0))
            candidates.append((score,dest))
        for m in self.territory_preferences(world_instance_id,animal['entity_runtime_id']):
            if m['territory_ref']!=current and (self.habitat_allows(profile['species_ref'],m['territory_ref']) or profile['range_excursion_allowed']):
                candidates.append((m['preference_score'],m['territory_ref']))
        if not candidates:return None
        candidates.sort(key=lambda x:(-x[0],x[1]));return candidates[0][1]

    def decide(self, world_instance_id: str, animal_ref: str) -> dict[str,Any]:
        world=self.runtime.get_world(world_instance_id)
        if world['simulation_mode']=='ROUTINE_OFFLINE': raise OfflinePolicyError('animal autonomous decisions are disabled offline; aggregate routines only')
        animal=self._animal(world_instance_id,animal_ref); eco=self._validate_ecological_state(animal)
        profile=self.get_species_profile(world_instance_id,_path_get(animal,'data.species_ref'))
        obsrec=self._latest_observation(world_instance_id,animal_ref); observations=obsrec['observations'] if obsrec else []
        candidates=[]
        def add(action,score,target=None,params=None,reason=''):
            candidates.append({'intent_type':action,'score':round(float(score),6),'target_ref':target,'parameters':copy.deepcopy(params or {}),'reason':reason})
        # Threat takes precedence through score, not hard-coded immediate mutation.
        threat_obs=sorted([o for o in observations if o['kind'] in {'THREAT','PREDATOR'}],key=lambda o:(-float(o.get('danger',0)),-o['confidence'],str(o.get('target_ref'))))
        max_danger=max([eco['threat_pressure']]+[float(o.get('danger',0))*float(o['confidence']) for o in threat_obs])
        if max_danger>=profile['flee_threshold']:
            add('ECO_FLEE',200+max_danger,reason='THREAT_ABOVE_FLEE_THRESHOLD')
        water=[o for o in observations if o['kind']=='WATER' and o.get('target_ref')]
        if eco['thirst']>=profile['thirst_threshold'] and water:
            water.sort(key=lambda o:(-float(o.get('water_value',50))*o['confidence'],str(o['target_ref'])))
            amount=min(50.0,eco['thirst']);add('ECO_DRINK',130+eco['thirst'],water[0]['target_ref'],{'amount':amount},'THIRST')
        if eco['hunger']>=profile['hunger_threshold']:
            prey=[o for o in observations if o['kind']=='PREY' and o.get('target_ref')]
            food=[o for o in observations if o['kind']=='FOOD' and o.get('target_ref')]
            if profile['diet'] in {'CARNIVORE','OMNIVORE','INSECTIVORE'} and prey:
                prey.sort(key=lambda o:(-float(o.get('food_value',50))*o['confidence'],str(o['target_ref'])))
                add('ECO_HUNT',120+eco['hunger'],prey[0]['target_ref'],{},'HUNGER_PREDATION')
            elif food:
                food.sort(key=lambda o:(-float(o.get('food_value',50))*o['confidence'],str(o['target_ref'])))
                amount=min(40.0,eco['hunger']);add('ECO_FORAGE',115+eco['hunger'],food[0]['target_ref'],{'amount':amount},'HUNGER_FORAGE')
        if eco['energy']<=profile['rest_threshold']:
            add('ECO_REST',150+(100-eco['energy']),reason='LOW_ENERGY')
        mates=[o for o in observations if o['kind']=='MATE' and o.get('target_ref')]
        if eco['reproduction_drive']>=profile['reproduction_threshold'] and _path_get(animal,'data.mature',False) and mates:
            mates.sort(key=lambda o:(-float(o.get('mate_quality',50))*o['confidence'],str(o['target_ref'])))
            add('ECO_REPRODUCE',90+eco['reproduction_drive'],mates[0]['target_ref'],{},'REPRODUCTION_DRIVE')
        habitat_pressure=max([float(o.get('resource_pressure',0)) for o in observations if o['kind']=='HABITAT'] or [0])
        if habitat_pressure>=profile['migration_pressure_threshold']:
            dest=self._select_destination(world_instance_id,animal,observations,profile)
            if dest:add('ECO_MIGRATE',100+habitat_pressure,params={'destination_ref':dest},reason='HABITAT_PRESSURE')
        add('ECO_PATROL',10+profile['territoriality']/10,reason='BASELINE_TERRITORIAL_ROUTINE')
        candidates.sort(key=lambda c:(-c['score'],c['intent_type'],str(c.get('target_ref'))))
        selected=candidates[0] if candidates else None; did=new_runtime_id('ecodecision'); intent=None; c=world['clock_state']
        with self._lock,self.validator._lock,self.runtime._write_lock:
            self.runtime._begin()
            try:
                if selected:
                    # Specialized checks that generic IntentValidator intentionally does not know.
                    if selected['intent_type']=='ECO_REPRODUCE': self._check_reproduction_pair(world_instance_id,animal_ref,selected['target_ref'])
                    if selected['intent_type']=='ECO_MIGRATE':
                        dest=selected['parameters']['destination_ref']; biome=None
                        if not self.habitat_allows(profile['species_ref'],dest,biome) and not profile['range_excursion_allowed']:
                            raise ValidationError('migration destination outside canonical distribution')
                    intent=self.validator.submit_intent(world_instance_id,actor_ref=animal_ref,target_ref=selected.get('target_ref'),intent_type=selected['intent_type'],parameters=selected['parameters'],source='AGENT_BRAIN',metadata={'ecology_decision_id':did,'reason':selected['reason'],'score':selected['score'],'observation_id':obsrec['observation_id'] if obsrec else None})
                body={'decision_id':did,'world_instance_id':world_instance_id,'timeline_id':world['timeline_id'],'animal_ref':animal_ref,'decided_at':clock_point(c['day'],c['tick']),'animal_state_version':animal['version'],'profile_id':profile['profile_id'],'observation_id':obsrec['observation_id'] if obsrec else None,'candidates':candidates,'selected':selected,'intent_id':intent['intent_id'] if intent else None,'status':'INTENT_PROPOSED' if intent else 'NO_ACTION'}
                text=canonical_json(body);h=sha256_text(text)
                self.conn.execute("INSERT INTO ecology_decisions VALUES(?,?,?,?,?,?,?)",(did,world_instance_id,world['timeline_id'],animal_ref,body['intent_id'],text,h));self.runtime._commit()
            except Exception:self.runtime._rollback();raise
        body['decision_hash']=h;return body

    def _check_reproduction_pair(self, world_instance_id: str, a_ref: str, b_ref: str | None) -> tuple[dict[str,Any],dict[str,Any]]:
        if not b_ref or b_ref==a_ref:raise ValidationError('reproduction requires distinct mate')
        a=self._animal(world_instance_id,a_ref);b=self._animal(world_instance_id,b_ref)
        if _path_get(a,'data.species_ref')!=_path_get(b,'data.species_ref'):raise ValidationError('reproduction species mismatch')
        if not _path_get(a,'data.mature',False) or not _path_get(b,'data.mature',False):raise ValidationError('reproduction requires mature pair')
        if _path_get(a,'data.ecology.territory_ref')!=_path_get(b,'data.ecology.territory_ref'):raise ValidationError('reproduction pair not co-located')
        profile=self.get_species_profile(world_instance_id,_path_get(a,'data.species_ref'))
        if _num(_path_get(a,'data.ecology.reproduction_drive'),'drive',0,100)<profile['reproduction_threshold'] or _num(_path_get(b,'data.ecology.reproduction_drive'),'drive',0,100)<profile['reproduction_threshold']:
            raise ValidationError('reproduction drive below threshold')
        return a,b

    def execute_decision(self, decision: dict[str,Any]) -> dict[str,Any]:
        if not isinstance(decision,dict) or not decision.get('intent_id'):raise ValidationError('decision has no intent')
        v=self.validator.validate_intent(decision['intent_id'])
        if v['status']!='PASS':return {'status':'REJECTED','validation':v,'execution':None}
        exe=self.validator.execute_validated_intent(decision['intent_id'])
        out={'status':'PASS','validation':v,'execution':exe,'birth':None}
        selected=decision.get('selected') or {}
        if selected.get('intent_type')=='ECO_REPRODUCE':
            out['birth']=self._materialize_birth(decision['world_instance_id'],exe['event_id'],decision['animal_ref'],selected.get('target_ref'))
        if selected.get('intent_type')=='ECO_MIGRATE':
            self.remember_territory(decision['world_instance_id'],decision['animal_ref'],selected['parameters']['destination_ref'],food_score=50,water_score=50,danger_score=20,success_score=60,notes={'source_event_id':exe['event_id'],'migration':True})
        return out

    def _materialize_birth(self, world_instance_id: str, reproduction_event_id: str, parent_a_ref: str, parent_b_ref: str) -> dict[str,Any]:
        # Hold Runtime's authoritative DB lock across idempotency check, child materialization and birth record.
        # This closes the check-then-spawn race even across multiple EcologySystem instances sharing one Runtime.
        with self._lock, self.runtime._write_lock:
            existing=self.conn.execute("SELECT birth_json,birth_hash FROM ecology_births WHERE reproduction_event_id=?",(reproduction_event_id,)).fetchone()
            if existing:
                if sha256_text(existing['birth_json'])!=existing['birth_hash']:raise IntegrityError('birth hash mismatch')
                b=json.loads(existing['birth_json']);b['idempotent_replay']=True;return b
            a,b=self._check_reproduction_pair_after_event(world_instance_id,parent_a_ref,parent_b_ref)
            species=_path_get(a,'data.species_ref'); territory=_path_get(a,'data.ecology.territory_ref'); biome=_path_get(a,'data.ecology.biome_ref')
            child=self.spawn_animal(world_instance_id,species_ref=species,territory_ref=territory,biome_ref=biome,entity_kind=a['entity_kind'],age_days=0,hunger=10,thirst=10,energy=70,reproduction_drive=0,parent_refs=[parent_a_ref,parent_b_ref])
            bid=new_runtime_id('birth'); body={'birth_id':bid,'world_instance_id':world_instance_id,'reproduction_event_id':reproduction_event_id,'parent_a_ref':parent_a_ref,'parent_b_ref':parent_b_ref,'child_ref':child['entity_runtime_id'],'species_ref':species,'territory_ref':territory,'status':'BORN'}
            text=canonical_json(body);h=sha256_text(text)
            self.conn.execute("INSERT INTO ecology_births VALUES(?,?,?,?,?,?,?,?)",(bid,world_instance_id,reproduction_event_id,parent_a_ref,parent_b_ref,child['entity_runtime_id'],text,h))
            body['birth_hash']=h;return body

    def _check_reproduction_pair_after_event(self, world_instance_id: str, a_ref: str, b_ref: str) -> tuple[dict[str,Any],dict[str,Any]]:
        # After successful reproduction action drives are intentionally reset, so only stable pairing constraints remain.
        a=self._animal(world_instance_id,a_ref);b=self._animal(world_instance_id,b_ref)
        if _path_get(a,'data.species_ref')!=_path_get(b,'data.species_ref'):raise IntegrityError('post-event reproduction species mismatch')
        if _path_get(a,'data.ecology.territory_ref')!=_path_get(b,'data.ecology.territory_ref'):raise IntegrityError('post-event reproduction co-location changed')
        return a,b

    # ---------- Aggregated ecology ----------
    def register_population(self, world_instance_id: str, *, species_ref: str, territory_ref: str, count: int, carrying_capacity: int,
                            resource_index: float=100, water_index: float=100, climate_comfort: float=100) -> dict[str,Any]:
        self.get_species_profile(world_instance_id,species_ref); self._validate_territory_ref(territory_ref)
        if not isinstance(count,int) or count<0:raise ValidationError('population count invalid')
        if not isinstance(carrying_capacity,int) or carrying_capacity<=0 or count>carrying_capacity*10:raise ValidationError('carrying capacity invalid')
        for v,n in [(resource_index,'resource_index'),(water_index,'water_index'),(climate_comfort,'climate_comfort')]:_num(v,n,0,100)
        body={'world_instance_id':world_instance_id,'species_ref':species_ref,'territory_ref':territory_ref,'count':count,'carrying_capacity':carrying_capacity,'resource_index':float(resource_index),'water_index':float(water_index),'climate_comfort':float(climate_comfort),'version':0}
        text=canonical_json(body);h=sha256_text(text)
        with self._lock,self.runtime._write_lock:self.conn.execute("INSERT INTO ecology_populations_current VALUES(?,?,?,?,?,?,?,?,?,?,?)",(world_instance_id,species_ref,territory_ref,count,carrying_capacity,float(resource_index),float(water_index),float(climate_comfort),0,text,h))
        body['population_hash']=h;return body

    def get_population(self, world_instance_id: str, species_ref: str, territory_ref: str) -> dict[str,Any]:
        with self.runtime._write_lock:row=self.conn.execute("SELECT * FROM ecology_populations_current WHERE world_instance_id=? AND species_ref=? AND territory_ref=?",(world_instance_id,species_ref,territory_ref)).fetchone()
        if not row:raise NotFoundError('population not found')
        if sha256_text(row['population_json'])!=row['population_hash']:raise IntegrityError('population hash mismatch')
        return json.loads(row['population_json'])

    def _apply_population_delta_tx(self, world_instance_id: str, species_ref: str, territory_ref: str, delta: int, reason: str) -> dict[str,Any]:
        row=self.conn.execute("SELECT * FROM ecology_populations_current WHERE world_instance_id=? AND species_ref=? AND territory_ref=?",(world_instance_id,species_ref,territory_ref)).fetchone()
        if not row:raise NotFoundError('population not found')
        if sha256_text(row['population_json'])!=row['population_hash']:raise IntegrityError('population hash mismatch')
        old=json.loads(row['population_json']); new_count=old['count']+int(delta)
        if new_count<0:raise ConflictError('population cannot become negative')
        new=copy.deepcopy(old);new['count']=new_count;new['version']=old['version']+1
        text=canonical_json(new);h=sha256_text(text);c=self.runtime.get_clock(world_instance_id);did=new_runtime_id('popdelta')
        d={'delta_id':did,'world_instance_id':world_instance_id,'species_ref':species_ref,'territory_ref':territory_ref,'delta_count':int(delta),'reason':reason,'occurred_at':clock_point(c['day'],c['tick']),'from_count':old['count'],'to_count':new_count,'from_version':old['version'],'to_version':new['version']}
        dt=canonical_json(d);dh=sha256_text(dt)
        self.conn.execute("UPDATE ecology_populations_current SET count=?,version=?,population_json=?,population_hash=? WHERE world_instance_id=? AND species_ref=? AND territory_ref=? AND version=?",(new_count,new['version'],text,h,world_instance_id,species_ref,territory_ref,old['version']))
        if self.conn.total_changes is None: pass
        self.conn.execute("INSERT INTO ecology_population_deltas VALUES(?,?,?,?,?,?,?,?,?,?)",(did,world_instance_id,species_ref,territory_ref,int(delta),reason,c['day'],c['tick'],dt,dh))
        return d

    def apply_population_delta(self, world_instance_id: str, species_ref: str, territory_ref: str, delta: int, reason: str) -> dict[str,Any]:
        if not isinstance(delta,int):raise ValidationError('population delta must be integer')
        with self._lock,self.runtime._write_lock:
            self.runtime._begin()
            try:r=self._apply_population_delta_tx(world_instance_id,species_ref,territory_ref,delta,reason);self.runtime._commit();return r
            except Exception:self.runtime._rollback();raise

    def register_food_web_link(self, world_instance_id: str, *, predator_species_ref: str, prey_species_ref: str, preference: float=1.0, efficiency: float=0.5) -> dict[str,Any]:
        pp=self.get_species_profile(world_instance_id,predator_species_ref);self.get_species_profile(world_instance_id,prey_species_ref)
        if pp['diet'] not in {'CARNIVORE','OMNIVORE','INSECTIVORE'}:raise ValidationError('predator diet incompatible')
        pref=_num(preference,'preference',0,1);eff=_num(efficiency,'efficiency',0,1);lid=new_runtime_id('foodweb')
        body={'link_id':lid,'world_instance_id':world_instance_id,'predator_species_ref':predator_species_ref,'prey_species_ref':prey_species_ref,'preference':pref,'efficiency':eff,'status':'ACTIVE','authority':'RUNTIME_SIMULATION_RELATION_NOT_CANON'}
        text=canonical_json(body);h=sha256_text(text)
        with self._lock,self.runtime._write_lock:self.conn.execute("INSERT INTO food_web_links VALUES(?,?,?,?,?,?,?)",(lid,world_instance_id,predator_species_ref,prey_species_ref,'ACTIVE',text,h))
        body['link_hash']=h;return body

    def simulate_population_routine(self, world_instance_id: str, *, routine_key: str | None=None) -> dict[str,Any]:
        world=self.runtime.get_world(world_instance_id)
        if world['simulation_mode']=='ROUTINE_OFFLINE':
            # This routine is explicitly bounded and cannot create cross-territory migration or settlement events.
            pass
        c=world['clock_state']; key=routine_key or f"eco:{c['day']}:{c['tick']}"
        with self._lock,self.runtime._write_lock:
            ex=self.conn.execute("SELECT tick_json,tick_hash FROM ecology_routine_ticks WHERE world_instance_id=? AND tick_key=?",(world_instance_id,key)).fetchone()
            if ex:
                if sha256_text(ex['tick_json'])!=ex['tick_hash']:raise IntegrityError('ecology routine tick hash mismatch')
                b=json.loads(ex['tick_json']);b['idempotent_replay']=True;return b
            pops=self.conn.execute("SELECT * FROM ecology_populations_current WHERE world_instance_id=? ORDER BY species_ref,territory_ref",(world_instance_id,)).fetchall()
            links=self.conn.execute("SELECT * FROM food_web_links WHERE world_instance_id=? AND status='ACTIVE'",(world_instance_id,)).fetchall()
            planned={}
            for r in pops:
                if sha256_text(r['population_json'])!=r['population_hash']:raise IntegrityError('population hash mismatch')
                p=json.loads(r['population_json']);prof=self.get_species_profile(world_instance_id,p['species_ref'])
                pressure=min(p['resource_index'],p['water_index'],p['climate_comfort'])/100.0
                density=(p['count']/p['carrying_capacity']) if p['carrying_capacity'] else 1.0
                raw=p['count']*prof['population_growth_rate']*pressure*(1-density)
                cap=max(1,int(math.ceil(p['count']*prof['routine_population_change_cap_fraction']))) if p['count'] else 0
                delta=max(-cap,min(cap,int(round(raw)))) if cap else 0
                planned[(p['species_ref'],p['territory_ref'])]=delta
            # Bounded predation within same territory.
            popmap={(json.loads(r['population_json'])['species_ref'],json.loads(r['population_json'])['territory_ref']):json.loads(r['population_json']) for r in pops}
            for lr in links:
                if sha256_text(lr['link_json'])!=lr['link_hash']:raise IntegrityError('food web hash mismatch')
                link=json.loads(lr['link_json'])
                territories={t for s,t in popmap if s==link['predator_species_ref']} & {t for s,t in popmap if s==link['prey_species_ref']}
                for t in territories:
                    pred=popmap[(link['predator_species_ref'],t)];prey=popmap[(link['prey_species_ref'],t)]
                    prof=self.get_species_profile(world_instance_id,link['predator_species_ref'])
                    kills=int(min(prey['count'], math.floor(pred['count']*prof['predation_rate']*link['preference'])))
                    prey_cap=max(1,int(math.ceil(prey['count']*0.05))) if prey['count'] else 0;kills=min(kills,prey_cap)
                    planned[(prey['species_ref'],t)]=planned.get((prey['species_ref'],t),0)-kills
                    planned[(pred['species_ref'],t)]=planned.get((pred['species_ref'],t),0)+int(math.floor(kills*link['efficiency']*0.1))
            self.runtime._begin()
            try:
                deltas=[]
                for (s,t),d in sorted(planned.items()):
                    current=self.get_population(world_instance_id,s,t)['count']
                    d=max(-current,d)
                    if d:deltas.append(self._apply_population_delta_tx(world_instance_id,s,t,d,'ROUTINE_ECOLOGY_TICK'))
                tid=new_runtime_id('ecotick');body={'tick_id':tid,'world_instance_id':world_instance_id,'timeline_id':world['timeline_id'],'tick_key':key,'occurred_at':clock_point(c['day'],c['tick']),'routine_safe':True,'cross_territory_migration':False,'deltas':deltas,'status':'PASS'}
                text=canonical_json(body);h=sha256_text(text);self.conn.execute("INSERT INTO ecology_routine_ticks VALUES(?,?,?,?,?)",(tid,world_instance_id,key,text,h));self.runtime._commit()
            except Exception:self.runtime._rollback();raise
        body['tick_hash']=h;return body

    def migrate_population(self, world_instance_id: str, species_ref: str, source_territory: str, destination_territory: str, count: int, *, extraordinary: bool=True) -> dict[str,Any]:
        if not isinstance(count,int) or count<=0:raise ValidationError('migration count invalid')
        self._validate_territory_ref(source_territory); self._validate_territory_ref(destination_territory)
        world=self.runtime.get_world(world_instance_id);prof=self.get_species_profile(world_instance_id,species_ref)
        if world['simulation_mode']=='ROUTINE_OFFLINE' and extraordinary:raise OfflinePolicyError('extraordinary population migration blocked offline')
        if not self.habitat_allows(species_ref,destination_territory) and not prof['range_excursion_allowed']:raise ValidationError('population migration outside canonical distribution')
        with self._lock,self.runtime._write_lock:
            self.runtime._begin()
            try:
                src=self.get_population(world_instance_id,species_ref,source_territory);dst=self.get_population(world_instance_id,species_ref,destination_territory)
                max_allowed=count
                if world['simulation_mode']=='ROUTINE_OFFLINE': max_allowed=max(1,int(math.floor(src['count']*prof['routine_population_change_cap_fraction'])))
                if count>max_allowed:raise OfflinePolicyError('offline routine migration exceeds bounded cap')
                a=self._apply_population_delta_tx(world_instance_id,species_ref,source_territory,-count,'MIGRATION_OUT')
                b=self._apply_population_delta_tx(world_instance_id,species_ref,destination_territory,count,'MIGRATION_IN')
                self.runtime._commit()
            except Exception:self.runtime._rollback();raise
        return {'status':'PASS','species_ref':species_ref,'count':count,'source':source_territory,'destination':destination_territory,'deltas':[a,b]}

    # ---------- Integrity ----------
    def full_integrity_check(self, world_instance_id: str) -> dict[str,Any]:
        failures=[]
        with self._lock,self.runtime._write_lock:
            checks=[
                ('ecology_species_profiles','profile_json','profile_hash'),('ecology_observations','observation_json','observation_hash'),
                ('territory_memories','memory_json','memory_hash'),('animal_groups','group_json','group_hash'),
                ('animal_group_members','member_json','member_hash'),('ecology_decisions','decision_json','decision_hash'),
                ('ecology_births','birth_json','birth_hash'),('ecology_populations_current','population_json','population_hash'),
                ('ecology_population_deltas','delta_json','delta_hash'),('food_web_links','link_json','link_hash'),('ecology_routine_ticks','tick_json','tick_hash')]
            for table,j,h in checks:
                rows=self.conn.execute(f"SELECT rowid,* FROM {table} WHERE world_instance_id=?",(world_instance_id,)).fetchall()
                for r in rows:
                    if sha256_text(r[j])!=r[h]:failures.append(f"{table}:HASH_MISMATCH:{r['rowid']}")
            # Global immutable canon snapshots are also verified.
            for r in self.conn.execute("SELECT rowid,* FROM fauna_snapshots").fetchall():
                if sha256_text(r['distribution_json'])!=r['distribution_hash']:failures.append(f"fauna_snapshots:HASH_MISMATCH:{r['rowid']}")
            # Population replay.
            rows=self.conn.execute("SELECT * FROM ecology_populations_current WHERE world_instance_id=?",(world_instance_id,)).fetchall()
            for r in rows:
                current=json.loads(r['population_json']); deltas=self.conn.execute("SELECT delta_json,delta_hash FROM ecology_population_deltas WHERE world_instance_id=? AND species_ref=? AND territory_ref=? ORDER BY rowid",(world_instance_id,r['species_ref'],r['territory_ref'])).fetchall()
                if deltas:
                    # Recover initial count from first delta's from_count, then replay all.
                    first=json.loads(deltas[0]['delta_json']); replay=first['from_count'];ver=first['from_version']
                    for drow in deltas:
                        if sha256_text(drow['delta_json'])!=drow['delta_hash']:continue
                        d=json.loads(drow['delta_json'])
                        if d['from_count']!=replay or d['from_version']!=ver:failures.append(f"POP_REPLAY_CHAIN:{r['species_ref']}:{r['territory_ref']}");break
                        replay=d['to_count'];ver=d['to_version']
                    if replay!=current['count'] or ver!=current['version']:failures.append(f"POP_REPLAY_MISMATCH:{r['species_ref']}:{r['territory_ref']}")
        return {'status':'PASS' if not failures else 'FAIL','failures':failures}

    def integrity_guard(self, world_instance_id: str) -> dict[str,Any]:
        upstream=self.validator.integrity_guard(world_instance_id);eco=self.full_integrity_check(world_instance_id)
        ok=upstream['status']=='PASS' and eco['status']=='PASS'
        if not ok:
            with self.runtime._write_lock:self.conn.execute("UPDATE worlds SET status='CORRUPT_BLOCKED' WHERE world_instance_id=?",(world_instance_id,))
        return {'status':'PASS' if ok else 'FAIL','upstream':upstream,'ecology':eco}
