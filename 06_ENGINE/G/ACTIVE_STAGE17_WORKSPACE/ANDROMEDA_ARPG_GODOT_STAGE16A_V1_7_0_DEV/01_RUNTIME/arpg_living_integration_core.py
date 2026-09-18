from __future__ import annotations
import copy, hashlib, json
from typing import Any
from living_runtime import ValidationError, IntegrityError, ConflictError, canonical_json, sha256_text


class ARPGLivingIntegrationCore:
    """Stage14 causal bridge between ARPG systems and the Living Simulation Engine.

    Canon remains read-only. All numeric thresholds, pressure formulas, interventions,
    runtime opportunities and recovery rules are gameplay/runtime policy and may be rebalanced.
    """

    VERSION = 'V1.5.0'
    AUTHORITY = 'ANDROMEDA_ARPG_STAGE14_LIVING_INTEGRATION'
    GAMEPLAY_AUTHORITY = 'GAMEPLAY_DERIVED_STAGE14_REBALANCEABLE'
    COUNTRY_REF = 'TER-011'
    MARKET_REF = 'POI-002'
    WORKSHOP_REF = 'POI-003'
    WAREHOUSE_REF = 'POI-006'
    BRIDGE_REF = 'POI-046'
    REPRESENTATIVE_ITEMS = ('ITEM-GRAIN', 'MIN-IRON', 'ITEM-CIRCUIT', 'ITEM-ENERGY-CELL')

    def __init__(self, engine: Any, world_instance_id: str) -> None:
        self.engine = engine
        self.runtime = engine.runtime
        self.world_instance_id = str(world_instance_id)
        self.world = engine.world_arpg(world_instance_id)
        self.actors = engine.actors_arpg(world_instance_id)
        self.gathering = engine.gathering_arpg(world_instance_id)
        self.mobility = engine.mobility_arpg(world_instance_id)
        self.technology = engine.technology_arpg(world_instance_id)
        self.narrative = engine.narrative_arpg(world_instance_id)
        self.economy = engine.economy_arpg(world_instance_id)
        self._init_schema()
        self._bootstrap_market_rows()

    @staticmethod
    def _pack(obj: Any) -> tuple[str, str]:
        text = canonical_json(obj)
        return text, sha256_text(text)

    @staticmethod
    def _clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, float(v)))

    def _stable_ref(self, prefix: str, *parts: Any) -> str:
        seed = int(getattr(self.engine.country(self.world_instance_id), 'seed', 0) or 0)
        raw = '|'.join(str(x) for x in (seed,) + parts)
        return prefix + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:18].upper()

    def _init_schema(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.executescript('''
            CREATE TABLE IF NOT EXISTS arpg_living_cycles(
              world_instance_id TEXT NOT NULL,
              cycle_ref TEXT NOT NULL,
              cycle_index INTEGER NOT NULL,
              payload_json TEXT NOT NULL,
              payload_hash TEXT NOT NULL,
              PRIMARY KEY(world_instance_id,cycle_ref),
              UNIQUE(world_instance_id,cycle_index)
            );
            CREATE TABLE IF NOT EXISTS arpg_living_metrics(
              world_instance_id TEXT NOT NULL,
              metric_ref TEXT NOT NULL,
              value REAL NOT NULL,
              payload_json TEXT NOT NULL,
              payload_hash TEXT NOT NULL,
              PRIMARY KEY(world_instance_id,metric_ref)
            );
            CREATE TABLE IF NOT EXISTS arpg_living_signals(
              world_instance_id TEXT NOT NULL,
              signal_ref TEXT NOT NULL,
              cycle_ref TEXT NOT NULL,
              signal_type TEXT NOT NULL,
              severity REAL NOT NULL,
              payload_json TEXT NOT NULL,
              payload_hash TEXT NOT NULL,
              PRIMARY KEY(world_instance_id,signal_ref)
            );
            CREATE TABLE IF NOT EXISTS arpg_living_opportunities(
              world_instance_id TEXT NOT NULL,
              opportunity_ref TEXT NOT NULL,
              cycle_ref TEXT NOT NULL,
              opportunity_type TEXT NOT NULL,
              anchor_ref TEXT,
              payload_json TEXT NOT NULL,
              payload_hash TEXT NOT NULL,
              PRIMARY KEY(world_instance_id,opportunity_ref)
            );
            CREATE TABLE IF NOT EXISTS arpg_living_events(
              world_instance_id TEXT NOT NULL,
              event_ref TEXT NOT NULL,
              event_type TEXT NOT NULL,
              payload_hash TEXT NOT NULL,
              result_json TEXT NOT NULL,
              result_hash TEXT NOT NULL,
              PRIMARY KEY(world_instance_id,event_ref)
            );
            ''')

    def _bootstrap_market_rows(self) -> None:
        # Create representative market rows through the Stage13 authority instead of direct schema invention.
        for item_ref in self.REPRESENTATIVE_ITEMS:
            try:
                self.economy._market_row(self.MARKET_REF, item_ref)
            except Exception:
                # Some late-game items may not exist in a future content profile; Stage14 remains resilient.
                pass

    def _event_existing(self, event_ref: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = self.runtime.conn.execute(
            'SELECT event_type,payload_hash,result_json,result_hash FROM arpg_living_events WHERE world_instance_id=? AND event_ref=?',
            (self.world_instance_id, str(event_ref)),
        ).fetchone()
        if not row:
            return None
        _, ph = self._pack(payload)
        if row['event_type'] != event_type or row['payload_hash'] != ph:
            raise ConflictError('STAGE14_EVENT_REF_CONFLICT')
        if sha256_text(row['result_json']) != row['result_hash']:
            raise IntegrityError('Stage14 event result hash mismatch')
        out = json.loads(row['result_json'])
        out['idempotent_replay'] = True
        return out

    def _record_event(self, event_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        pt, ph = self._pack(payload)
        rt, rh = self._pack(result)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                'INSERT INTO arpg_living_events VALUES(?,?,?,?,?,?)',
                (self.world_instance_id, str(event_ref), event_type, ph, rt, rh),
            )
        return result

    def _resource_metric(self) -> tuple[float, dict[str, float]]:
        # Stage09 keeps most source state in Country records and materializes fishing state separately.
        # Use the public node projection so all activities are measured consistently.
        by: dict[str, list[float]] = {}
        for n in self.gathering.list_nodes():
            cap=max(1.0,float(n.get('capacity_units',1.0)))
            rem=self._clamp(float(n.get('remaining_units',cap))/cap,0.0,1.0)
            by.setdefault(str(n.get('activity_type')),[]).append(rem)
        per={k:round(sum(v)/len(v),6) for k,v in by.items() if v}
        important=[per.get(k,1.0) for k in ('MINING','LOGGING','FORAGING','AGRICULTURE','HUNTING','FISHING')]
        return round(sum(important)/len(important),6),per

    def _production_metric(self) -> tuple[float, dict[str, Any]]:
        machines = self.technology.list_machines()
        vals = []
        detail = []
        for m in machines:
            p = self.technology.machine_profile(m['profile_ref'])
            integ = self._clamp(float(m.get('integrity',0.0)) / max(1.0,float(p.get('integrity_max',1.0))), 0.0, 1.0)
            energy = self._clamp(float(m.get('energy',0.0)) / max(1.0,float(p.get('energy_max',1.0))), 0.0, 1.0)
            operational = 1.0 if m.get('status') == 'OPERATIONAL' else 0.25
            score = (integ * 0.45) + (energy * 0.35) + (operational * 0.20)
            vals.append(score)
            detail.append({'machine_ref':m['machine_ref'],'score':round(score,6),'integrity_ratio':round(integ,6),'energy_ratio':round(energy,6)})
        score = sum(vals)/len(vals) if vals else 1.0
        return round(self._clamp(score,0.0,1.0),6), {'machines':detail}

    def _infrastructure_metric(self) -> tuple[float, dict[str, Any]]:
        b = self.mobility.bridge(self.BRIDGE_REF)
        integrity = self._clamp(float(b.get('integrity',0.0))/max(1.0,float(b.get('integrity_max',100.0))),0.0,1.0)
        cap = self._clamp(float(b.get('capacity_factor',1.0)),0.0,1.0)
        operational = 1.0 if b.get('operational') else 0.0
        score = (integrity*0.35)+(cap*0.35)+(operational*0.30)
        return round(self._clamp(score,0.0,1.0),6), {'bridge_ref':self.BRIDGE_REF,'operational':bool(b.get('operational')),'integrity_ratio':round(integrity,6),'capacity_factor':round(cap,6)}

    def _market_metric(self) -> tuple[float, dict[str, Any]]:
        rows=[]; stability=[]
        vendors=self.economy.list_vendors()
        for item_ref in self.REPRESENTATIVE_ITEMS:
            try:
                # Use the vendor with the strongest current stock for this category; the Stage13 market is multi-node.
                choices=[]
                for v in vendors:
                    try: choices.append((self.economy._vendor_qty(v['vendor_ref'],item_ref),v))
                    except Exception: pass
                stock,vendor=max(choices,key=lambda x:x[0]) if choices else (0,{'location_ref':self.MARKET_REF,'vendor_ref':'NONE'})
                m=self.economy._market_row(vendor['location_ref'],item_ref)
                target=max(1.0,float(m['target_stock']))
                stock_ratio=self._clamp(float(stock)/target,0.0,1.0)
                demand_penalty=self._clamp(abs(float(m['demand_index'])-1.0)/0.75,0.0,1.0)
                item_stability=(stock_ratio*0.70)+((1.0-demand_penalty)*0.30)
                stability.append(item_stability)
                rows.append({'item_ref':item_ref,'vendor_ref':vendor['vendor_ref'],'location_ref':vendor['location_ref'],'stock':stock,'target_stock':target,'demand_index':round(float(m['demand_index']),6),'stability':round(item_stability,6)})
            except Exception:
                continue
        score=sum(stability)/len(stability) if stability else 1.0
        return round(self._clamp(score,0.0,1.0),6),{'items':rows}

    def _labor_metric(self) -> tuple[float, dict[str, Any]]:
        eligible = 0
        protected = 0
        for n in self.engine.country(self.world_instance_id)._all_npc_records():
            tags=set(n.get('tags') or [])
            if 'CHILD' in tags or bool(n.get('protected')):
                protected += 1
            else:
                eligible += 1
        workers = int(self.runtime.conn.execute('SELECT COUNT(*) n FROM arpg_worker_profiles WHERE world_instance_id=?',(self.world_instance_id,)).fetchone()['n'])
        contracts = int(self.runtime.conn.execute("SELECT COUNT(*) n FROM employment_contracts WHERE world_instance_id=? AND status='ACTIVE'",(self.world_instance_id,)).fetchone()['n'])
        # Potential workforce is capacity; active worker overlays are lazy by design and must not be interpreted as unemployment.
        utilization = self._clamp((contracts + min(workers,eligible))*1.0/max(1.0,eligible*0.20),0.0,1.0)
        capacity = self._clamp(0.65 + (0.35*(eligible/max(1.0,eligible+protected))),0.0,1.0)
        score=(capacity*0.75)+(utilization*0.25)
        return round(score,6), {'eligible_npcs':eligible,'protected_npcs':protected,'materialized_workers':workers,'active_contracts':contracts,'lazy_materialization_guard':True}

    def _ecology_metric(self) -> tuple[float, dict[str, Any]]:
        per={}; vals=[]
        for activity in ('HUNTING','FISHING'):
            nodes=self.gathering.list_nodes(activity_type=activity)
            if not nodes: continue
            ratios=[]
            for n in nodes:
                cap=max(1.0,float(n.get('capacity_units',1.0)))
                ratios.append(self._clamp(float(n.get('remaining_units',cap))/cap,0.0,1.0))
            ratio=sum(ratios)/len(ratios)
            per[activity]={'remaining_ratio':round(ratio,6),'nodes':len(nodes)}
            vals.append(ratio)
        pop_count=int(self.runtime.conn.execute('SELECT COUNT(*) n FROM ecology_populations_current WHERE world_instance_id=?',(self.world_instance_id,)).fetchone()['n'])
        score=sum(vals)/len(vals) if vals else 1.0
        return round(self._clamp(score,0.0,1.0),6),{'extraction_surfaces':per,'living_population_records':pop_count,'population_absence_guard':'NO_RECORD_IS_NOT_EXTINCTION'}

    def _population_metric(self) -> tuple[float, dict[str, Any]]:
        rows=self.engine.world_systems._entities(self.world_instance_id,'POPULATION_AGGREGATE')
        local=[x for x in rows if (x.get('data') or {}).get('territory_ref')==self.COUNTRY_REF]
        if not local:
            return 1.0,{'local_population_records':0,'guard':'NO_LOCAL_RUNTIME_RECORD_IS_NOT_ZERO_POPULATION'}
        vals=[];detail=[]
        for x in local:
            d=x.get('data') or {}; welfare=self._clamp(float(d.get('welfare_index',70.0))/100.0,0.0,1.0); food=self._clamp(float(d.get('food_security',75.0))/100.0,0.0,1.0); employment=self._clamp(float(d.get('employed',0))/max(1.0,float(d.get('labor_force',1))),0.0,1.0); score=(welfare*0.4)+(food*0.35)+(employment*0.25);vals.append(score);detail.append({'settlement_ref':d.get('settlement_ref'),'count':int(d.get('count',0)),'welfare':round(welfare,6),'food_security':round(food,6),'employment_ratio':round(employment,6),'score':round(score,6)})
        return round(sum(vals)/len(vals),6),{'local_population_records':len(local),'settlements':detail,'numeric_authority':'LIVING_RUNTIME_ONLY_NOT_CANON'}

    def _faction_metric(self) -> tuple[float, dict[str, Any]]:
        rows=self.engine.world_systems._entities(self.world_instance_id,'FACTION_RUNTIME')
        local=[x for x in rows if (x.get('data') or {}).get('territory_ref')==self.COUNTRY_REF]
        if not local:
            return 1.0,{'local_faction_records':0,'guard':'NO_TER011_RUNTIME_FACTION_PRESENCE_DOES_NOT_MEAN_NO_FACTIONS','sovereignty_claimed':False}
        vals=[];detail=[]
        for x in local:
            d=x.get('data') or {}; sec=self._clamp(float(d.get('security',50))/100.0,0.0,1.0);stab=self._clamp(float(d.get('stability',50))/100.0,0.0,1.0);score=(sec+stab)/2;vals.append(score);detail.append({'faction_ref':d.get('faction_ref'),'security':round(sec,6),'stability':round(stab,6),'score':round(score,6),'influence_not_sovereignty':bool(d.get('influence_not_sovereignty',True))})
        return round(sum(vals)/len(vals),6),{'local_faction_records':len(local),'factions':detail,'sovereignty_claimed':False}

    def _governance_metric(self) -> tuple[float, dict[str, Any]]:
        law=self.runtime.conn.execute('SELECT law_profile_id,authority_faction_ref,profile_json,profile_hash FROM law_profiles WHERE world_instance_id=? AND territory_ref=?',(self.world_instance_id,self.COUNTRY_REF)).fetchone()
        incidents=int(self.runtime.conn.execute('SELECT COUNT(*) n FROM legal_incidents WHERE world_instance_id=? AND territory_ref=?',(self.world_instance_id,self.COUNTRY_REF)).fetchone()['n'])
        open_incidents=int(self.runtime.conn.execute("SELECT COUNT(*) n FROM legal_incidents i JOIN legal_incident_status s ON i.incident_id=s.incident_id WHERE i.world_instance_id=? AND i.territory_ref=? AND s.status='OPEN'",(self.world_instance_id,self.COUNTRY_REF)).fetchone()['n'])
        if not law:
            return 1.0,{'law_profile_present':False,'legal_incidents':incidents,'open_incidents':open_incidents,'guard':'NO_RUNTIME_LAW_PROFILE_IS_UNRESOLVED_POLICY_NOT_LAWLESSNESS','authority_faction_claimed':False}
        pressure=self._clamp(open_incidents/10.0,0.0,1.0);return round(1.0-pressure,6),{'law_profile_present':True,'law_profile_id':law['law_profile_id'],'authority_faction_ref':law['authority_faction_ref'],'legal_incidents':incidents,'open_incidents':open_incidents,'policy_authority':'RUNTIME_POLICY_NOT_CANON'}

    def _security_metric(self) -> tuple[float, dict[str, Any]]:
        rows=self.runtime.conn.execute('SELECT payload_json FROM arpg_actor_profiles WHERE world_instance_id=?',(self.world_instance_id,)).fetchall()
        total=len(rows); hostile=0
        for r in rows:
            try:
                p=json.loads(r['payload_json'])
                if p.get('disposition')=='HOSTILE': hostile+=1
            except Exception: pass
        pressure = self._clamp(hostile/max(1.0,total*0.25),0.0,1.0) if total else 0.0
        return round(1.0-pressure,6), {'materialized_actors':total,'hostile_materialized':hostile,'lazy_actor_guard':True}

    def snapshot(self) -> dict[str, Any]:
        infrastructure, infra_detail=self._infrastructure_metric()
        resources, resource_detail=self._resource_metric()
        production, production_detail=self._production_metric()
        market, market_detail=self._market_metric()
        labor, labor_detail=self._labor_metric()
        ecology, ecology_detail=self._ecology_metric()
        security, security_detail=self._security_metric()
        population, population_detail=self._population_metric()
        faction, faction_detail=self._faction_metric()
        governance, governance_detail=self._governance_metric()
        metrics={
            'infrastructure_resilience':infrastructure,
            'resource_availability':resources,
            'production_capacity':production,
            'market_stability':market,
            'labor_capacity':labor,
            'ecological_resilience':ecology,
            'security_stability':security,
            'population_welfare':population,
            'faction_stability':faction,
            'governance_stability':governance,
        }
        resilience=round(sum(metrics.values())/len(metrics),6)
        pressure=round(1.0-resilience,6)
        return {
            'world_instance_id':self.world_instance_id,'country_ref':self.COUNTRY_REF,
            'metrics':metrics,'resilience_index':resilience,'systemic_pressure':pressure,
            'detail':{'infrastructure':infra_detail,'resources':resource_detail,'production':production_detail,'market':market_detail,'labor':labor_detail,'ecology':ecology_detail,'security':security_detail,'population':population_detail,'factions':faction_detail,'governance':governance_detail},
            'authority':self.AUTHORITY,'numeric_authority':self.GAMEPLAY_AUTHORITY,'canonical_mutation':False,
        }

    def _signals_for(self, snap: dict[str,Any], cycle_ref: str) -> list[dict[str,Any]]:
        m=snap['metrics']; specs=[]
        def add(t,severity,anchor,reason):
            severity=round(self._clamp(severity,0.0,1.0),6)
            if severity<=0.0:return
            specs.append({'signal_ref':self._stable_ref('SIG-S14-',cycle_ref,t,anchor or ''),'cycle_ref':cycle_ref,'signal_type':t,'severity':severity,'anchor_ref':anchor,'reason':reason,'authority':self.GAMEPLAY_AUTHORITY,'canonical_event':False})
        if m['infrastructure_resilience']<0.85:add('INFRASTRUCTURE_DISRUPTION',1-m['infrastructure_resilience'],self.BRIDGE_REF,'Bridge/network capacity below healthy threshold')
        if m['resource_availability']<0.75:add('RESOURCE_SCARCITY',1-m['resource_availability'],self.WAREHOUSE_REF,'Gathering availability below healthy threshold')
        if m['production_capacity']<0.80:add('PRODUCTION_SLOWDOWN',1-m['production_capacity'],self.WORKSHOP_REF,'Machine energy/integrity reduces production capacity')
        if m['market_stability']<0.75:add('MARKET_PRESSURE',1-m['market_stability'],self.MARKET_REF,'Stock/demand pressure is elevated')
        if m['ecological_resilience']<0.75:add('ECOLOGICAL_STRESS',1-m['ecological_resilience'],None,'Hunting/fishing extraction surface is depleted')
        if m['security_stability']<0.75:add('SECURITY_PRESSURE',1-m['security_stability'],'CIT-001','Materialized hostile actor pressure is elevated')
        if m['population_welfare']<0.75:add('POPULATION_STRESS',1-m['population_welfare'],'CIT-001','Runtime welfare/food/employment pressure is elevated')
        if m['faction_stability']<0.75:add('FACTION_INSTABILITY',1-m['faction_stability'],None,'Runtime faction security/stability is reduced')
        if m['governance_stability']<0.75:add('GOVERNANCE_PRESSURE',1-m['governance_stability'],None,'Open legal incident pressure is elevated')
        if snap['resilience_index']>=0.90:add('SYSTEM_RECOVERY',snap['resilience_index']-0.89,self.MARKET_REF,'Integrated system is in a healthy recovery band')
        return specs

    def _persist_signal(self, s: dict[str,Any]) -> None:
        t,h=self._pack(s)
        with self.runtime._write_lock:
            self.runtime.conn.execute('INSERT OR REPLACE INTO arpg_living_signals VALUES(?,?,?,?,?,?,?)',(self.world_instance_id,s['signal_ref'],s['cycle_ref'],s['signal_type'],float(s['severity']),t,h))

    def _opportunity_for_signal(self, s: dict[str,Any]) -> dict[str,Any] | None:
        mapping={
            'INFRASTRUCTURE_DISRUPTION':('INFRASTRUCTURE_RESPONSE',self.BRIDGE_REF),
            'RESOURCE_SCARCITY':('SUPPLY_RESPONSE',self.WAREHOUSE_REF),
            'PRODUCTION_SLOWDOWN':('WORKSHOP_SUPPORT',self.WORKSHOP_REF),
            'MARKET_PRESSURE':('MARKET_STABILIZATION',self.MARKET_REF),
            'ECOLOGICAL_STRESS':('ECOLOGICAL_RECOVERY',None),
            'SECURITY_PRESSURE':('SECURITY_RESPONSE','CIT-001'),
            'POPULATION_STRESS':('WELFARE_RESPONSE','CIT-001'),
            'FACTION_INSTABILITY':('FACTION_MEDIATION',None),
            'GOVERNANCE_PRESSURE':('LEGAL_MEDIATION','POI-004'),
        }
        if s['signal_type'] not in mapping:return None
        typ,anchor=mapping[s['signal_type']]
        return {
            'opportunity_ref':self._stable_ref('OPP-S14-',s['cycle_ref'],typ,anchor or ''),
            'cycle_ref':s['cycle_ref'],'opportunity_type':typ,'anchor_ref':anchor,
            'source_signal_ref':s['signal_ref'],'severity':s['severity'],
            'quest_template_auto_created':False,'canonical_event':False,
            'authority':'GAMEPLAY_DERIVED_DYNAMIC_OPPORTUNITY_NOT_CANON',
            'guard':'May seed runtime quest content but never mutates Master or canonizes emergent events.',
        }

    def _persist_opportunity(self,o:dict[str,Any]) -> None:
        t,h=self._pack(o)
        with self.runtime._write_lock:
            self.runtime.conn.execute('INSERT OR REPLACE INTO arpg_living_opportunities VALUES(?,?,?,?,?,?,?)',(self.world_instance_id,o['opportunity_ref'],o['cycle_ref'],o['opportunity_type'],o.get('anchor_ref'),t,h))

    def _apply_market_intervention(self, snap: dict[str,Any]) -> list[dict[str,Any]]:
        m=snap['metrics']; effects=[]
        resource_pressure=1.0-m['resource_availability']; infra_pressure=1.0-m['infrastructure_resilience']; prod_pressure=1.0-m['production_capacity']; eco_pressure=1.0-m['ecological_resilience']
        pressure_by_item={
            'ITEM-GRAIN':max(resource_pressure*0.55,eco_pressure*0.35,infra_pressure*0.30),
            'MIN-IRON':max(resource_pressure*0.75,infra_pressure*0.30),
            'ITEM-CIRCUIT':max(prod_pressure*0.80,infra_pressure*0.25),
            'ITEM-ENERGY-CELL':max(prod_pressure*0.65,infra_pressure*0.20),
        }
        for item_ref,p in pressure_by_item.items():
            try:
                row=self.economy._market_row(self.MARKET_REF,item_ref); old=float(row['demand_index'])
                # Pressure raises demand; healthy systems recover slowly toward neutral 1.0.
                if p>0.10:new=old+(p*0.08)
                else:new=old+((1.0-old)*0.08)
                new=round(self._clamp(new,0.75,1.75),6)
                with self.runtime._write_lock:
                    self.runtime.conn.execute('UPDATE arpg_economy_market SET demand_index=? WHERE world_instance_id=? AND location_ref=? AND item_ref=?',(new,self.world_instance_id,self.MARKET_REF,item_ref))
                effects.append({'item_ref':item_ref,'old_demand_index':round(old,6),'new_demand_index':new,'pressure':round(p,6)})
            except Exception as e:
                effects.append({'item_ref':item_ref,'status':'SKIPPED','reason':type(e).__name__})
        return effects

    def run_cycle(self, cycle_ref: str, *, apply_consequences: bool=True) -> dict[str,Any]:
        cycle_ref=str(cycle_ref)
        if not cycle_ref: raise ValidationError('cycle_ref required')
        payload={'cycle_ref':cycle_ref,'apply_consequences':bool(apply_consequences)}
        old=self._event_existing(cycle_ref,'LIVING_CYCLE',payload)
        if old:return old
        prior=self.runtime.conn.execute('SELECT COALESCE(MAX(cycle_index),0) n FROM arpg_living_cycles WHERE world_instance_id=?',(self.world_instance_id,)).fetchone()
        cycle_index=int(prior['n'])+1
        snap=self.snapshot(); signals=self._signals_for(snap,cycle_ref)
        for s in signals:self._persist_signal(s)
        opportunities=[]
        for s in signals:
            o=self._opportunity_for_signal(s)
            if o:self._persist_opportunity(o);opportunities.append(o)
        effects=self._apply_market_intervention(snap) if apply_consequences else []
        cycle={'cycle_ref':cycle_ref,'cycle_index':cycle_index,'snapshot':snap,'signals':signals,'opportunities':opportunities,'effects':effects,'apply_consequences':bool(apply_consequences),'canonical_mutation':False,'authority':self.AUTHORITY}
        ct,ch=self._pack(cycle)
        with self.runtime._write_lock:
            self.runtime.conn.execute('INSERT INTO arpg_living_cycles VALUES(?,?,?,?,?)',(self.world_instance_id,cycle_ref,cycle_index,ct,ch))
            for k,v in snap['metrics'].items():
                mp={'metric_ref':k,'value':float(v),'cycle_ref':cycle_ref,'authority':self.GAMEPLAY_AUTHORITY};mt,mh=self._pack(mp)
                self.runtime.conn.execute('INSERT OR REPLACE INTO arpg_living_metrics VALUES(?,?,?,?,?)',(self.world_instance_id,k,float(v),mt,mh))
        result={'status':'PASS','cycle':cycle,'living_runtime_bridge':{'consequence_engine':type(self.engine.consequences).__name__,'world_orchestrator':type(self.engine.orchestrator).__name__,'society':type(self.engine.society).__name__,'ecology':type(self.engine.ecology).__name__},'authority':self.AUTHORITY}
        return self._record_event(cycle_ref,'LIVING_CYCLE',payload,result)


    def advance_and_reconcile(self, event_ref: str, *, living_steps: int=1, apply_consequences: bool=True) -> dict[str,Any]:
        if not isinstance(living_steps,int) or isinstance(living_steps,bool) or living_steps<=0:
            raise ValidationError('living_steps must be positive integer')
        event_ref=str(event_ref)
        payload={'living_steps':living_steps,'apply_consequences':bool(apply_consequences)}
        old=self._event_existing(event_ref,'ADVANCE_AND_RECONCILE',payload)
        if old:return old
        # The sealed Living orchestration remains the authority for simulation ticks. Stage14 only reconciles ARPG consequences afterwards.
        steps=self.engine.active_steps(self.world_instance_id,living_steps)
        cycle=self.run_cycle(event_ref+':CYCLE',apply_consequences=apply_consequences)
        result={'status':'PASS' if steps.get('status')=='PASS' and cycle.get('status')=='PASS' else 'FAIL','living_steps':steps,'reconciliation':cycle,'authority':self.AUTHORITY,'canonical_mutation':False}
        return self._record_event(event_ref,'ADVANCE_AND_RECONCILE',payload,result)

    def cycle(self, cycle_ref: str) -> dict[str,Any]:
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_living_cycles WHERE world_instance_id=? AND cycle_ref=?',(self.world_instance_id,str(cycle_ref))).fetchone()
        if not row: raise ValidationError('living cycle not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('living cycle hash mismatch')
        return json.loads(row['payload_json'])

    def list_signals(self, cycle_ref: str|None=None) -> list[dict[str,Any]]:
        if cycle_ref:
            rows=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_living_signals WHERE world_instance_id=? AND cycle_ref=? ORDER BY signal_ref',(self.world_instance_id,str(cycle_ref))).fetchall()
        else:
            rows=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_living_signals WHERE world_instance_id=? ORDER BY cycle_ref,signal_ref',(self.world_instance_id,)).fetchall()
        out=[]
        for r in rows:
            if sha256_text(r['payload_json'])!=r['payload_hash']:raise IntegrityError('living signal hash mismatch')
            out.append(json.loads(r['payload_json']))
        return out

    def list_opportunities(self, cycle_ref: str|None=None) -> list[dict[str,Any]]:
        if cycle_ref:
            rows=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_living_opportunities WHERE world_instance_id=? AND cycle_ref=? ORDER BY opportunity_ref',(self.world_instance_id,str(cycle_ref))).fetchall()
        else:
            rows=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_living_opportunities WHERE world_instance_id=? ORDER BY cycle_ref,opportunity_ref',(self.world_instance_id,)).fetchall()
        out=[]
        for r in rows:
            if sha256_text(r['payload_json'])!=r['payload_hash']:raise IntegrityError('living opportunity hash mismatch')
            out.append(json.loads(r['payload_json']))
        return out

    def causal_trace(self, cycle_ref: str) -> dict[str,Any]:
        c=self.cycle(cycle_ref)
        return {
            'cycle_ref':cycle_ref,
            'causes':c['snapshot']['metrics'],
            'signals':[{'signal_ref':s['signal_ref'],'type':s['signal_type'],'severity':s['severity']} for s in c['signals']],
            'effects':copy.deepcopy(c['effects']),
            'opportunities':[o['opportunity_ref'] for o in c['opportunities']],
            'authority':self.AUTHORITY,'canonical_mutation':False,
        }

    def verify(self) -> dict[str,Any]:
        failures=[]
        try:
            s=self.snapshot()
            for k,v in s['metrics'].items():
                if not (0.0<=float(v)<=1.0):failures.append('METRIC_RANGE:'+k)
            if s['country_ref']!=self.COUNTRY_REF:failures.append('COUNTRY_SCOPE')
            if s['canonical_mutation']:failures.append('CANON_MUTATION_GUARD')
            if type(self.engine.consequences).__name__!='ConsequenceEngine':failures.append('CONSEQUENCE_ENGINE_BRIDGE')
            if type(self.engine.orchestrator).__name__!='WorldSimulationOrchestrator':failures.append('ORCHESTRATOR_BRIDGE')
        except Exception as e:
            failures.append(type(e).__name__+':'+str(e))
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'country_ref':self.COUNTRY_REF,'metrics':10,'authority':self.AUTHORITY,'canonical_mutation':False}
