from __future__ import annotations
import copy, json, hashlib, zipfile
from typing import Any
from living_runtime import ValidationError, IntegrityError, ConflictError, NotFoundError, canonical_json, sha256_text

class ARPGNarrativeCultureCore:
    VERSION='V1.3.0'
    AUTHORITY='ANDROMEDA_ARPG_STAGE12_NARRATIVE_CULTURE_QUESTS'
    GAMEPLAY_AUTHORITY='GAMEPLAY_DERIVED_STAGE12_REBALANCEABLE'
    COUNTRY_REF='TER-011'
    START_LOCATION='CIT-001'
    CANON_PATH='ANDROMEDA_CODEX_MASTER/01_CANON/ANDROMEDA_CODEX_CANON_MASTER_V2_0_0.json'
    CULTURE_REFS=(
      'SOC-PROP-FND-011','SOC-PROP-ETQ-011','SOC-PROP-REP-011','SOC-PROP-TRB-011','SOC-PROP-CFL-011',
      'SOC-PROP-HOS-011','SOC-PROP-EDU-011','SOC-PROP-ORA-011','SOC-PROP-CIV-011','SOC-PROP-RIT-011',
      'SOC-PROP-ESP-011','SOC-PROP-FUN-011','SOC-PROP-LUT-011','SOC-PROP-UNI-011','SOC-PROP-JOG-011',
      'SOC-PROP-LAZ-011','SOC-PROP-CEL-011','SOC-PROP-SIM-011','SOC-PROP-ALI-011','SOC-PROP-REF-011',
      'SOC-PROP-VES-011','SOC-PROP-MUS-011','SOC-PROP-ART-011','SOC-PROP-COM-031','SOC-PROP-COM-033','SOC-PROP-FAM-011'
    )
    LOCAL_ANCHORS=('CIT-001','POI-001','POI-002','POI-003','POI-004','POI-005','POI-006','POI-007','POI-046','SRTE-001')
    FACTION_REFS=('FAC-009','FAC-010')
    GLOBAL_NARRATIVE_REFS=('PER-002','PER-003','TIM-029','TIM-032')
    BELIEF_REFS=('SYS-REL-001',)
    QUEST_TEMPLATES={
      'QST-S12-VARGA-MEDIATION':{
        'name':'Mediação na Fronteira','kind':'SOCIAL','anchor_ref':'POI-004','source_refs':['POI-004','SOC-PROP-CFL-011','SOC-PROP-REP-011','SOC-PROP-ETQ-011'],
        'objectives':[{'objective_ref':'VISIT-MEDIATION','type':'VISIT_CANONICAL_REF','canonical_ref':'POI-004'}],
        'reputation_awards':{'FRONTIER_RELIABILITY':2},'authority':'GAMEPLAY_DERIVED_QUEST_FROM_CANON_ANCHORS'
      },
      'QST-S12-BRIDGE-CONTINUITY':{
        'name':'Continuidade da Ponte Varden','kind':'INFRASTRUCTURE','anchor_ref':'POI-046','source_refs':['POI-046','SOC-PROP-TRB-011','SOC-PROP-COM-033'],
        'objectives':[{'objective_ref':'BRIDGE-OPERATIONAL','type':'BRIDGE_OPERATIONAL','bridge_ref':'POI-046'}],
        'reputation_awards':{'FRONTIER_RELIABILITY':3},'authority':'GAMEPLAY_DERIVED_QUEST_FROM_CANON_ANCHORS'
      },
      'QST-S12-WORKSHOP-CIRCUIT':{
        'name':'Entrega para a Oficina Arco Morto','kind':'TECHNOLOGY','anchor_ref':'POI-003','source_refs':['POI-003','FAC-009','FAC-010','SOC-PROP-TRB-011'],
        'objectives':[{'objective_ref':'HAVE-CIRCUIT','type':'INVENTORY_AT_LEAST','item_ref':'ITEM-CIRCUIT','quantity':1}],
        'reputation_awards':{'WORKSHOP_RELIABILITY':3},'authority':'GAMEPLAY_DERIVED_QUEST_FROM_CANON_ANCHORS'
      },
      'QST-S12-FRONTIER-SUPPLY':{
        'name':'Suprimentos da Fronteira','kind':'GATHERING','anchor_ref':'POI-006','source_refs':['POI-006','INDN-008','SOC-PROP-HOS-011','SOC-PROP-COM-033'],
        'objectives':[{'objective_ref':'HAVE-IRON','type':'INVENTORY_AT_LEAST','item_ref':'MIN-IRON','quantity':2}],
        'reputation_awards':{'FRONTIER_RELIABILITY':2},'authority':'GAMEPLAY_DERIVED_QUEST_FROM_CANON_ANCHORS'
      },
      'QST-S12-VARGA-ORIENTATION':{
        'name':'Orientação de Varga','kind':'EXPLORATION','anchor_ref':'CIT-001','source_refs':['CIT-001','SOC-PROP-ORA-011','SOC-PROP-EDU-011','SOC-PROP-CIV-011'],
        'objectives':[{'objective_ref':'VISIT-VARGA','type':'VISIT_CANONICAL_REF','canonical_ref':'CIT-001'}],
        'reputation_awards':{'LOCAL_FAMILIARITY':1},'authority':'GAMEPLAY_DERIVED_QUEST_FROM_CANON_ANCHORS'
      }
    }
    DIALOGUE_BRIEFS={
      'DLG-S12-MEDIATION':{'anchor_ref':'POI-004','speech_acts':['INFORM','CLARIFY','REQUEST_EVIDENCE','PROPOSE_MEDIATION'],'source_refs':['SOC-PROP-CFL-011','SOC-PROP-REP-011'],'copy_authority':'GAMEPLAY_PLACEHOLDER_COPY_NOT_CANON_DIALOGUE'},
      'DLG-S12-WORKSHOP':{'anchor_ref':'POI-003','speech_acts':['REQUEST_WORK','REPORT_CONDITION','DELIVER_COMPONENT'],'source_refs':['FAC-009','FAC-010','SOC-PROP-TRB-011'],'copy_authority':'GAMEPLAY_PLACEHOLDER_COPY_NOT_CANON_DIALOGUE'},
      'DLG-S12-FRONTIER':{'anchor_ref':'CIT-001','speech_acts':['GREET','GIVE_DIRECTIONS','SHARE_SOURCE_WITH_ATTRIBUTION'],'source_refs':['SOC-PROP-CMP-011','SOC-PROP-ORA-011'],'copy_authority':'GAMEPLAY_PLACEHOLDER_COPY_NOT_CANON_DIALOGUE'},
    }

    def __init__(self,engine:Any,world_instance_id:str)->None:
        self.engine=engine; self.runtime=engine.runtime; self.world_instance_id=str(world_instance_id)
        self.country=engine.country(world_instance_id); self.items=engine.items_arpg(world_instance_id); self.mobility=engine.mobility_arpg(world_instance_id)
        self._init_schema(); self._master,self._entities=self._load_master(); self._bootstrap_canon(); self._bootstrap_templates()

    @staticmethod
    def _payload(obj):
        t=canonical_json(obj); return t,sha256_text(t)
    def _init_schema(self):
        with self.runtime._write_lock:
            self.runtime.conn.executescript('''
            CREATE TABLE IF NOT EXISTS arpg_narrative_canon_snapshots(canonical_ref TEXT PRIMARY KEY,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS arpg_quest_templates(quest_ref TEXT PRIMARY KEY,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS arpg_quest_instances(world_instance_id TEXT NOT NULL,profile_ref TEXT NOT NULL,quest_ref TEXT NOT NULL,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL,PRIMARY KEY(world_instance_id,profile_ref,quest_ref));
            CREATE TABLE IF NOT EXISTS arpg_context_reputation(world_instance_id TEXT NOT NULL,profile_ref TEXT NOT NULL,context_ref TEXT NOT NULL,value INTEGER NOT NULL,payload_hash TEXT NOT NULL,PRIMARY KEY(world_instance_id,profile_ref,context_ref));
            CREATE TABLE IF NOT EXISTS arpg_narrative_events(world_instance_id TEXT NOT NULL,event_ref TEXT NOT NULL,event_type TEXT NOT NULL,payload_hash TEXT NOT NULL,result_json TEXT NOT NULL,result_hash TEXT NOT NULL,PRIMARY KEY(world_instance_id,event_ref));
            ''')
    def _load_master(self):
        p=self.runtime.master_release_path
        if not p: raise IntegrityError('Master release required for Stage12')
        with zipfile.ZipFile(p) as z: master=json.loads(z.read(self.CANON_PATH))
        entities={e.get('id'):e for e in master.get('entities',[]) if isinstance(e,dict) and e.get('id')}
        return master,entities
    def _snapshot(self,ref):
        obj=self._entities.get(ref)
        if not obj: raise IntegrityError('Stage12 missing canonical source:'+ref)
        t,h=self._payload(obj); row=self.runtime.conn.execute('SELECT payload_hash FROM arpg_narrative_canon_snapshots WHERE canonical_ref=?',(ref,)).fetchone()
        if row and row['payload_hash']!=h: raise IntegrityError('Stage12 canonical snapshot drift:'+ref)
        if not row:
            with self.runtime._write_lock:self.runtime.conn.execute('INSERT INTO arpg_narrative_canon_snapshots VALUES(?,?,?)',(ref,t,h))
        return copy.deepcopy(obj)
    def _bootstrap_canon(self):
        refs=list(self.CULTURE_REFS)+list(self.LOCAL_ANCHORS)+list(self.FACTION_REFS)+list(self.GLOBAL_NARRATIVE_REFS)+list(self.BELIEF_REFS)+['SOC-PROP-CMP-011','INDN-008']
        for ref in refs:self._snapshot(ref)
    def canonical_snapshot(self,ref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_narrative_canon_snapshots WHERE canonical_ref=?',(str(ref),)).fetchone()
        if not row: raise NotFoundError('narrative canonical snapshot not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('narrative snapshot hash mismatch')
        return json.loads(row['payload_json'])
    def _bootstrap_templates(self):
        for ref,b in self.QUEST_TEMPLATES.items():
            p={'quest_ref':ref,**copy.deepcopy(b),'country_ref':self.COUNTRY_REF,'canonical_mutation':False}
            t,h=self._payload(p); row=self.runtime.conn.execute('SELECT payload_hash FROM arpg_quest_templates WHERE quest_ref=?',(ref,)).fetchone()
            if row and row['payload_hash']!=h: raise IntegrityError('quest template drift:'+ref)
            if not row:
                with self.runtime._write_lock:self.runtime.conn.execute('INSERT INTO arpg_quest_templates VALUES(?,?,?)',(ref,t,h))
    def quest_template(self,ref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_quest_templates WHERE quest_ref=?',(str(ref),)).fetchone()
        if not row: raise NotFoundError('quest template not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('quest template hash mismatch')
        return json.loads(row['payload_json'])
    def list_quest_templates(self): return [self.quest_template(r['quest_ref']) for r in self.runtime.conn.execute('SELECT quest_ref FROM arpg_quest_templates ORDER BY quest_ref')]
    def culture_profile(self):
        return {'country_ref':self.COUNTRY_REF,'culture_identity_ref':'SOC-PROP-FND-011','culture_identity_name':self.canonical_snapshot('SOC-PROP-FND-011')['name'],
                'practice_refs':list(self.CULTURE_REFS),'official_language_ref':None,'official_religion_ref':None,
                'language_guard':'NO_CANONICAL_TER_011_OFFICIAL_LANGUAGE_RESOLVED_DO_NOT_INVENT',
                'belief_guard':'SYS-REL-001_EXISTS_BUT_NO_SINGLE_OFFICIAL_RELIGION_ASSUMED',
                'reputation_model':'CONTEXTUAL_NOT_GLOBAL_PER_SOC-PROP-REP-011','authority':'MASTER_READ_ONLY_PLUS_RUNTIME_PROJECTION'}
    def faction_profile(self):
        return [{'canonical_ref':r,'name':self.canonical_snapshot(r)['name'],'scope':'PLANETARY_SCOPE','territorial_control_claimed':False,'guard':'NO_UNSUPPORTED_TER_011_SPATIALIZATION'} for r in self.FACTION_REFS]
    def global_narrative_anchors(self,max_spoiler_level=1):
        out=[]
        for r in self.GLOBAL_NARRATIVE_REFS:
            e=self.canonical_snapshot(r)
            if int(e.get('spoiler_level',0))<=int(max_spoiler_level):
                out.append({'canonical_ref':r,'name':e.get('name'),'spoiler_level':e.get('spoiler_level',0),'auto_quest':False,'auto_spatialize':False,'authority':'GLOBAL_CANON_READ_ONLY'})
        return out
    def dialogue_brief(self,ref):
        if ref not in self.DIALOGUE_BRIEFS: raise NotFoundError('dialogue brief not found')
        return {'dialogue_ref':ref,**copy.deepcopy(self.DIALOGUE_BRIEFS[ref]),'exact_dialogue_text_canonical':False}
    def list_dialogue_briefs(self): return [self.dialogue_brief(r) for r in sorted(self.DIALOGUE_BRIEFS)]
    def _event_existing(self,event_ref,event_type,payload):
        row=self.runtime.conn.execute('SELECT event_type,payload_hash,result_json,result_hash FROM arpg_narrative_events WHERE world_instance_id=? AND event_ref=?',(self.world_instance_id,str(event_ref))).fetchone()
        if not row:return None
        _,ph=self._payload(payload)
        if row['event_type']!=event_type or row['payload_hash']!=ph: raise ConflictError('narrative event_ref conflict')
        if sha256_text(row['result_json'])!=row['result_hash']: raise IntegrityError('narrative event result hash mismatch')
        out=json.loads(row['result_json']); out['idempotent_replay']=True; return out
    def _record(self,event_ref,event_type,payload,result):
        pt,ph=self._payload(payload); rt,rh=self._payload(result)
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT INTO arpg_narrative_events VALUES(?,?,?,?,?,?)',(self.world_instance_id,str(event_ref),event_type,ph,rt,rh))
        return result
    def _profile_exists(self,profile_ref):
        try:self.engine.arpg(self.world_instance_id).profile(profile_ref); return True
        except Exception: return False
    def accept_quest(self,profile_ref,quest_ref,*,event_ref):
        payload={'profile_ref':profile_ref,'quest_ref':quest_ref}; old=self._event_existing(event_ref,'ACCEPT_QUEST',payload)
        if old:return old
        if not self._profile_exists(profile_ref): raise ValidationError('unknown profile_ref')
        q=self.quest_template(quest_ref); existing=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_quest_instances WHERE world_instance_id=? AND profile_ref=? AND quest_ref=?',(self.world_instance_id,profile_ref,quest_ref)).fetchone()
        if existing:
            inst=json.loads(existing['payload_json']); return self._record(event_ref,'ACCEPT_QUEST',payload,{'status':'PASS','quest':inst,'already_accepted':True})
        inst={'profile_ref':profile_ref,'quest_ref':quest_ref,'state':'ACTIVE','objective_states':{o['objective_ref']:'PENDING' for o in q['objectives']},'completed_objectives':0,'source_refs':q['source_refs'],'authority':self.GAMEPLAY_AUTHORITY}
        self._save_quest(inst); return self._record(event_ref,'ACCEPT_QUEST',payload,{'status':'PASS','quest':inst})
    def _save_quest(self,inst):
        t,h=self._payload(inst)
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT OR REPLACE INTO arpg_quest_instances VALUES(?,?,?,?,?)',(self.world_instance_id,inst['profile_ref'],inst['quest_ref'],t,h))
    def quest_state(self,profile_ref,quest_ref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_quest_instances WHERE world_instance_id=? AND profile_ref=? AND quest_ref=?',(self.world_instance_id,profile_ref,quest_ref)).fetchone()
        if not row: raise NotFoundError('quest instance not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('quest state hash mismatch')
        return json.loads(row['payload_json'])
    def list_quests(self,profile_ref):
        return [self.quest_state(profile_ref,r['quest_ref']) for r in self.runtime.conn.execute('SELECT quest_ref FROM arpg_quest_instances WHERE world_instance_id=? AND profile_ref=? ORDER BY quest_ref',(self.world_instance_id,profile_ref))]
    def _objective_satisfied(self,profile_ref,obj,evidence):
        t=obj['type']
        if t=='VISIT_CANONICAL_REF': return str(evidence.get('canonical_ref'))==obj['canonical_ref']
        if t=='INVENTORY_AT_LEAST': return int(self.items.inventory_snapshot(profile_ref).get('stacks',{}).get(obj['item_ref'],0))>=int(obj['quantity'])
        if t=='BRIDGE_OPERATIONAL': return bool(self.mobility.bridge(obj['bridge_ref']).get('operational'))
        return False
    def submit_objective(self,profile_ref,quest_ref,objective_ref,*,evidence=None,event_ref):
        evidence=copy.deepcopy(evidence or {}); payload={'profile_ref':profile_ref,'quest_ref':quest_ref,'objective_ref':objective_ref,'evidence':evidence}; old=self._event_existing(event_ref,'QUEST_OBJECTIVE',payload)
        if old:return old
        inst=self.quest_state(profile_ref,quest_ref); q=self.quest_template(quest_ref)
        if inst['state']!='ACTIVE': return self._record(event_ref,'QUEST_OBJECTIVE',payload,{'status':'REJECTED','reason':'QUEST_NOT_ACTIVE','quest':inst})
        obj=next((o for o in q['objectives'] if o['objective_ref']==objective_ref),None)
        if not obj: raise ValidationError('unknown objective_ref')
        if inst['objective_states'].get(objective_ref)=='COMPLETE': return self._record(event_ref,'QUEST_OBJECTIVE',payload,{'status':'PASS','quest':inst,'already_complete':True})
        if not self._objective_satisfied(profile_ref,obj,evidence): return self._record(event_ref,'QUEST_OBJECTIVE',payload,{'status':'REJECTED','reason':'OBJECTIVE_EVIDENCE_NOT_SATISFIED','quest':inst})
        inst['objective_states'][objective_ref]='COMPLETE'; inst['completed_objectives']=sum(1 for v in inst['objective_states'].values() if v=='COMPLETE')
        if inst['completed_objectives']==len(inst['objective_states']): inst['state']='READY_TO_TURN_IN'
        self._save_quest(inst); return self._record(event_ref,'QUEST_OBJECTIVE',payload,{'status':'PASS','quest':inst})
    def reputation(self,profile_ref):
        rows=self.runtime.conn.execute('SELECT context_ref,value FROM arpg_context_reputation WHERE world_instance_id=? AND profile_ref=? ORDER BY context_ref',(self.world_instance_id,profile_ref)).fetchall()
        return {r['context_ref']:int(r['value']) for r in rows}
    def _award_reputation(self,profile_ref,awards):
        for ctx,delta in awards.items():
            old=self.runtime.conn.execute('SELECT value FROM arpg_context_reputation WHERE world_instance_id=? AND profile_ref=? AND context_ref=?',(self.world_instance_id,profile_ref,ctx)).fetchone(); val=int(old['value']) if old else 0; val=max(-100,min(100,val+int(delta))); h=sha256_text(canonical_json({'profile_ref':profile_ref,'context_ref':ctx,'value':val}))
            with self.runtime._write_lock:self.runtime.conn.execute('INSERT OR REPLACE INTO arpg_context_reputation VALUES(?,?,?,?,?)',(self.world_instance_id,profile_ref,ctx,val,h))
    def turn_in_quest(self,profile_ref,quest_ref,*,event_ref):
        payload={'profile_ref':profile_ref,'quest_ref':quest_ref}; old=self._event_existing(event_ref,'TURN_IN_QUEST',payload)
        if old:return old
        inst=self.quest_state(profile_ref,quest_ref); q=self.quest_template(quest_ref)
        if inst['state']=='COMPLETED': return self._record(event_ref,'TURN_IN_QUEST',payload,{'status':'PASS','quest':inst,'already_complete':True,'reputation':self.reputation(profile_ref)})
        if inst['state']!='READY_TO_TURN_IN': return self._record(event_ref,'TURN_IN_QUEST',payload,{'status':'REJECTED','reason':'QUEST_OBJECTIVES_INCOMPLETE','quest':inst})
        inst['state']='COMPLETED'; self._save_quest(inst); self._award_reputation(profile_ref,q.get('reputation_awards',{}))
        return self._record(event_ref,'TURN_IN_QUEST',payload,{'status':'PASS','quest':inst,'reputation':self.reputation(profile_ref),'reward_authority':'CONTEXTUAL_REPUTATION_ONLY_STAGE12'})
    def verify(self):
        failures=[]
        try:
            cp=self.culture_profile()
            if cp['official_language_ref'] is not None: failures.append('LANGUAGE_GUARD')
            if cp['official_religion_ref'] is not None: failures.append('RELIGION_GUARD')
            if self.canonical_snapshot('CIT-001').get('territory_refs')!=[self.COUNTRY_REF]: failures.append('VARGA_TERRITORY')
            if len(self.list_quest_templates())!=5: failures.append('QUEST_TEMPLATE_COUNT')
            if len(self.list_dialogue_briefs())!=3: failures.append('DIALOGUE_BRIEF_COUNT')
            for f in self.faction_profile():
                if f['territorial_control_claimed']: failures.append('FACTION_SPATIALIZATION_GUARD')
            if any(x['spoiler_level']>1 for x in self.global_narrative_anchors(1)): failures.append('SPOILER_GUARD')
        except Exception as e: failures.append(type(e).__name__+':'+str(e))
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'quest_templates':len(self.list_quest_templates()),'dialogue_briefs':len(self.list_dialogue_briefs()),'culture_refs':len(self.CULTURE_REFS),'factions':len(self.FACTION_REFS),'authority':self.AUTHORITY}
