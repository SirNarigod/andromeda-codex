from __future__ import annotations
import copy, hashlib, json, math
from typing import Any

from living_runtime import new_runtime_id, clock_point, canonical_json, sha256_text, ValidationError, ConflictError, NotFoundError, IntegrityError

class CountryLivingDomainBridge:
    """V1.3 authority bridge: Living domain engines execute actions; Country Scale is a spatial/inventory projection."""
    VERSION='V1.3.0'
    AUTHORITY='LIVING_DOMAIN_ENGINES_AUTHORITATIVE_COUNTRY_PROJECTION'

    def __init__(self, engine: Any, world_instance_id: str, country: Any) -> None:
        self.engine=engine; self.runtime=engine.runtime; self.commerce=engine.commerce; self.combat=engine.combat
        self.social=engine.social; self.domain_hub=engine.domain_hub; self.country=country; self.world_instance_id=world_instance_id
        self._init_schema(); country.attach_domain_bridge(self)

    def _init_schema(self)->None:
        with self.runtime._write_lock:
            self.runtime.conn.executescript('''
            CREATE TABLE IF NOT EXISTS country_living_bindings(
              world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
              binding_kind TEXT NOT NULL, country_ref TEXT NOT NULL, runtime_ref TEXT NOT NULL,
              payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
              PRIMARY KEY(world_instance_id,binding_kind,country_ref),
              UNIQUE(world_instance_id,runtime_ref)
            );
            ''')
            self.runtime.conn.execute("INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('country_living_bridge_version',?)",(self.VERSION,))

    def _binding(self,kind:str,country_ref:str)->dict[str,Any]|None:
        row=self.runtime.conn.execute('SELECT * FROM country_living_bindings WHERE world_instance_id=? AND binding_kind=? AND country_ref=?',(self.world_instance_id,kind,country_ref)).fetchone()
        if not row:return None
        if sha256_text(row['payload_json'])!=row['payload_hash']:raise IntegrityError('country bridge binding hash mismatch')
        return json.loads(row['payload_json'])

    def _bind(self,kind:str,country_ref:str,runtime_ref:str,metadata:dict[str,Any]|None=None)->dict[str,Any]:
        body={'world_instance_id':self.world_instance_id,'binding_kind':kind,'country_ref':country_ref,'runtime_ref':runtime_ref,'metadata':copy.deepcopy(metadata or {}),'authority':self.AUTHORITY}
        text=canonical_json(body); h=sha256_text(text)
        with self.runtime._write_lock:
            self.runtime.conn.execute('INSERT INTO country_living_bindings VALUES(?,?,?,?,?,?)',(self.world_instance_id,kind,country_ref,runtime_ref,text,h))
        return body

    def _apply_sets(self,entity_ref:str,fields:dict[str,Any],action_type:str)->dict[str,Any]|None:
        entity=self.runtime.get_entity(self.world_instance_id,entity_ref)
        changes=[]
        for path,value in fields.items():
            # Small path reader for idempotence.
            cur=entity
            try:
                for part in path.split('.'):
                    cur=cur[part]
            except Exception: cur=object()
            if cur!=value: changes.append((path,copy.deepcopy(value)))
        if not changes:return None
        w=self.runtime.get_world(self.world_instance_id); c=w['clock_state']
        action={'action_id':new_runtime_id('action'),'intent_id':new_runtime_id('intent'),'world_instance_id':self.world_instance_id,'timeline_id':w['timeline_id'],'actor_ref':'SYSTEM_RECONCILIATION','action_type':action_type,'parameters':{'entity_ref':entity_ref,'fields':[x[0] for x in changes]},'precondition_snapshot':{'entity_versions':{entity_ref:entity['version']}},'idempotency_key':f"bridge-set:{entity_ref}:{entity['version']}:{hashlib.sha256(repr(changes).encode()).hexdigest()[:12]}",'created_at':clock_point(c['day'],c['tick']),'status':'SCHEDULED','source':'SYSTEM_RECONCILIATION','execution_class':'ROUTINE_SAFE'}
        cons=[{'target_ref':entity_ref,'operation':'SET','field_path':path,'value':value,'priority':i,'kind':'DIRECT'} for i,(path,value) in enumerate(changes)]
        return self.runtime.apply_action(self.world_instance_id,action,cons)

    def ensure_npc(self,npc_id:str)->dict[str,Any]:
        npc=self.country.npc(npc_id); bound=self._binding('NPC',npc_id)
        if bound:
            actor=self.runtime.get_entity(self.world_instance_id,bound['runtime_ref'])
            self._sync_positive_country_items(npc,actor['entity_runtime_id'])
            return self.runtime.get_entity(self.world_instance_id,actor['entity_runtime_id'])
        w=self.runtime.get_world(self.world_instance_id); c=w['clock_state']
        protection={}
        if not npc['protection']['combat_targetable']: protection['death']='BLOCKED'
        if not npc['protection']['hazardous_labor_allowed']: protection['hazardous_labor']='BLOCKED'
        state={'state_id':new_runtime_id('state'),'world_instance_id':self.world_instance_id,'timeline_id':w['timeline_id'],'entity_runtime_id':new_runtime_id('agent'),'origin':'RUNTIME_BORN','entity_kind':'AGENT','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),
               'data':{'name':npc['name'],'country_npc_id':npc_id,'country_class':npc['class'],'location_ref':npc['block_id'],'territory_ref':self.country.country_source['id'],'country_block_ref':npc['block_id'],'country_city_ref':npc.get('city_id'),'bridge_authority':self.AUTHORITY},'protection':protection}
        actor=self.runtime.register_entity(self.world_instance_id,state); self._bind('NPC',npc_id,actor['entity_runtime_id'],{'class':npc['class']})
        acct=self.commerce.create_account(self.world_instance_id,actor['entity_runtime_id'],starting_balance=float(npc['wallet']['balance']))
        inv=self.runtime.get_entity(self.world_instance_id,acct['inventory_runtime_id']); merged=dict(inv['data']['items']); merged.update({k:int(v) for k,v in npc['inventory'].items()})
        self._apply_sets(inv['entity_runtime_id'],{'data.items':merged},'COUNTRY_BRIDGE_ACCOUNT_SEEDED')
        return actor

    def _sync_positive_country_items(self,npc:dict[str,Any],actor_ref:str)->None:
        acct=self.commerce.account_state(self.world_instance_id,actor_ref); inv=self.runtime.get_entity(self.world_instance_id,acct['inventory_runtime_id'])
        owned=dict(inv['data'].get('items',{}))
        for e in self.runtime.list_entities(self.world_instance_id):
            if e.get('entity_kind')=='EQUIPMENT_INSTANCE' and e.get('lifecycle')=='ACTIVE' and e.get('data',{}).get('owner_ref')==actor_ref:
                ref=e['data'].get('item_ref'); owned[ref]=int(owned.get(ref,0))+1
        desired=dict(inv['data'].get('items',{})); changed=False
        for ref,qty in npc.get('inventory',{}).items():
            gap=int(qty)-int(owned.get(ref,0))
            if gap>0: desired[ref]=int(desired.get(ref,0))+gap; changed=True
        if changed:self._apply_sets(inv['entity_runtime_id'],{'data.items':desired},'COUNTRY_BRIDGE_EXTERNAL_ITEM_IMPORT')

    def _living_owned_items(self,actor_ref:str)->tuple[dict[str,int],list[dict[str,Any]]]:
        acct=self.commerce.account_state(self.world_instance_id,actor_ref)
        inv=self.runtime.get_entity(self.world_instance_id,acct['inventory_runtime_id'])
        totals={k:int(v) for k,v in inv['data'].get('items',{}).items() if int(v)>0}; equips=[]
        for e in self.runtime.list_entities(self.world_instance_id):
            if e.get('entity_kind')=='EQUIPMENT_INSTANCE' and e.get('lifecycle')=='ACTIVE' and e.get('data',{}).get('owner_ref')==actor_ref:
                ref=e['data'].get('item_ref'); totals[ref]=int(totals.get(ref,0))+1; equips.append({'runtime_ref':e['entity_runtime_id'],'item_ref':ref,'condition':e['data'].get('condition')})
        return totals,equips

    def _project_npc(self,npc_id:str,actor_ref:str)->None:
        npc=self.country.npc(npc_id); acct=self.commerce.account_state(self.world_instance_id,actor_ref)
        wallet=self.runtime.get_entity(self.world_instance_id,acct['wallet_runtime_id'])
        totals,equips=self._living_owned_items(actor_ref)
        npc['wallet']['balance']=round(float(wallet['data']['balance']),2); npc['inventory']=totals; npc['bridge_equipment']=equips

    def _country_regulation(self,shop:dict[str,Any])->float:
        st=self.country.state(shop['state_id']); b=self.country.block(shop['block_id'])
        wealth=float(st['stats']['wealth']); richness=float(b['climate']['resource_richness'])
        return max(0.75,min(1.25,1.0+(wealth-0.5)*0.15+(0.5-richness)*0.10))

    def ensure_vendor(self,shop_id:str)->dict[str,Any]:
        sh=self.country.shop(shop_id); bound=self._binding('SHOP',shop_id)
        if bound:return self.runtime.get_entity(self.world_instance_id,bound['runtime_ref'])
        refs=sorted(k for k,v in sh['inventory'].items() if int(v)>=0)
        result=self.commerce.create_vendor(self.world_instance_id,shop_id,name=sh['name'],stock_seed=0,starting_cash=float(sh['wallet']['balance']),regulation_factor=self._country_regulation(sh),catalog_refs=refs)
        vendor=result['vendor']; stock={k:0 for k in vendor['data']['stock']}; stock.update({k:int(v) for k,v in sh['inventory'].items()})
        self._apply_sets(vendor['entity_runtime_id'],{'data.stock':stock,'data.cash_balance':round(float(sh['wallet']['balance']),4)},'COUNTRY_BRIDGE_VENDOR_SEEDED')
        self._bind('SHOP',shop_id,vendor['entity_runtime_id'],{'city_id':sh['city_id'],'block_id':sh['block_id']})
        return self.runtime.get_entity(self.world_instance_id,vendor['entity_runtime_id'])

    def _project_shop(self,shop_id:str,vendor_ref:str)->None:
        sh=self.country.shop(shop_id); vendor=self.runtime.get_entity(self.world_instance_id,vendor_ref)
        sh['wallet']['balance']=round(float(vendor['data']['cash_balance']),2)
        sh['inventory']={k:int(v) for k,v in vendor['data'].get('stock',{}).items() if int(v)>0}

    def _locate_actor(self,actor_ref:str,location_ref:str,block_id:str,city_id:str|None)->None:
        self._apply_sets(actor_ref,{'data.location_ref':location_ref,'data.country_block_ref':block_id,'data.country_city_ref':city_id},'COUNTRY_BRIDGE_LOCATION_SYNC')

    def purchase(self,*,shop_id:str,npc_id:str,item_ref:str,quantity:int)->dict[str,Any]:
        if not isinstance(quantity,int) or quantity<=0: raise ValueError('quantity must be positive')
        sh=self.country.shop(shop_id); npc=self.country.npc(npc_id)
        if npc.get('class')=='CHILD' and str(item_ref).startswith('WPN-'):
            return {'status':'REJECTED','reason':'PROTECTED_MINOR_WEAPON_PURCHASE','authority':'CountryProtection+CommerceSystem via CountryLivingDomainBridge'}
        if npc.get('city_id')!=sh.get('city_id'): return {'status':'REJECTED','reason':'ACTOR_NOT_IN_SHOP_CITY','authority':'CommerceSystem via CountryLivingDomainBridge'}
        if int(sh['inventory'].get(item_ref,0))<quantity:return {'status':'REJECTED','reason':'OUT_OF_STOCK','authority':'CommerceSystem via CountryLivingDomainBridge'}
        actor=self.ensure_npc(npc_id); vendor=self.ensure_vendor(shop_id); self._locate_actor(actor['entity_runtime_id'],shop_id,sh['block_id'],sh['city_id'])
        actor=self.runtime.get_entity(self.world_instance_id,actor['entity_runtime_id']); before_n=float(npc['wallet']['balance']); before_s=float(sh['wallet']['balance'])
        quote=self.commerce.quote(self.world_instance_id,actor['entity_runtime_id'],vendor['entity_runtime_id'],item_ref,quantity=quantity,relationship_score=float(npc.get('reputation',0.0)))
        try: tx=self.commerce.execute_quote(quote['quote_id'],idempotency_key=f"country:{shop_id}:{npc_id}:{item_ref}:{self.runtime.event_count(self.world_instance_id)}")
        except ConflictError as exc:
            return {'status':'REJECTED','reason':str(exc).upper().replace(' ','_'),'authority':'CommerceSystem via CountryLivingDomainBridge'}
        self._project_npc(npc_id,actor['entity_runtime_id']); self._project_shop(shop_id,vendor['entity_runtime_id']); self.country.reconcile_country_inventory()
        conservation=round((before_n+before_s)-(float(npc['wallet']['balance'])+float(sh['wallet']['balance'])),6)
        out={'status':'PASS','engine':'CommerceSystem','bridge':'CountryLivingDomainBridge','event_id':tx['event_id'],'item_ref':item_ref,'quantity':quantity,'unit_price':quote['unit_price'],'total_price':quote['total_price'],'buyer_balance':npc['wallet']['balance'],'shop_balance':sh['wallet']['balance'],'money_conservation_delta':conservation,'numeric_price_authority':'RUNTIME_ONLY'}
        self.country._record_event('COUNTRY_COMMERCE_PROJECTED_FROM_LIVING',out); return out

    def equip_country_weapon(self,npc_id:str,item_ref:str|None=None)->dict[str,Any]:
        npc=self.country.npc(npc_id)
        if npc.get('class')=='CHILD' or not npc.get('protection',{}).get('combat_targetable',True):
            return {'status':'REJECTED','reason':'PROTECTED_MINOR_COMBAT','authority':'CountryProtection+CombatSystem via CountryLivingDomainBridge'}
        actor=self.ensure_npc(npc_id); self._locate_actor(actor['entity_runtime_id'],npc['block_id'],npc['block_id'],npc.get('city_id'))
        current=self.combat.equipped_weapon(self.world_instance_id,actor['entity_runtime_id'])
        if current:
            if item_ref is None or current['data']['item_ref']==item_ref:return {'status':'PASS','idempotent_replay':True,'equipment':current}
            self.combat.unequip_weapon(self.world_instance_id,actor['entity_runtime_id'])
        acct=self.commerce.account_state(self.world_instance_id,actor['entity_runtime_id']); inv=self.runtime.get_entity(self.world_instance_id,acct['inventory_runtime_id'])
        choices=[r for r,q in inv['data']['items'].items() if int(q)>0 and str(r).startswith('WPN-')]
        chosen=item_ref or (sorted(choices)[0] if choices else None)
        if not chosen or int(inv['data']['items'].get(chosen,0))<=0:return {'status':'REJECTED','reason':'NO_OWNED_WEAPON'}
        try:r=self.combat.equip_weapon(self.world_instance_id,actor['entity_runtime_id'],chosen)
        except (ConflictError,NotFoundError) as exc:return {'status':'REJECTED','reason':str(exc).upper().replace(' ','_')}
        self._project_npc(npc_id,actor['entity_runtime_id']); self.country.reconcile_country_inventory(); return {'status':'PASS','engine':'CombatSystem',**r}

    def _spawn_country_fauna_target(self,block_id:str,fauna:dict[str,Any])->dict[str,Any]:
        w=self.runtime.get_world(self.world_instance_id); c=w['clock_state']; rid=new_runtime_id('animal')
        state={'state_id':new_runtime_id('state'),'world_instance_id':self.world_instance_id,'timeline_id':w['timeline_id'],'entity_runtime_id':rid,'origin':'RUNTIME_BORN','entity_kind':'ANIMAL','lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':{'species_ref':fauna['species_ref'],'country_fauna_id':fauna['id'],'location_ref':block_id,'territory_ref':self.country.country_source['id'],'ecology':{'territory_ref':self.country.country_source['id'],'biome_ref':None,'energy':80.0,'hunger':20.0,'thirst':20.0,'reproduction_drive':0.0,'threat_pressure':0.0},'bridge_authority':self.AUTHORITY}}
        return self.runtime.register_entity(self.world_instance_id,state)

    def _ensure_witness(self,actor_npc_id:str,block_id:str)->str|None:
        for n in self.country._all_npc_records():
            if n['id']!=actor_npc_id and n.get('block_id')==block_id and n.get('status')=='ACTIVE':
                a=self.ensure_npc(n['id']); self._locate_actor(a['entity_runtime_id'],block_id,block_id,n.get('city_id')); return a['entity_runtime_id']
        return None

    def _add_living_inventory(self,actor_ref:str,item_ref:str,qty:int)->None:
        acct=self.commerce.account_state(self.world_instance_id,actor_ref); inv=self.runtime.get_entity(self.world_instance_id,acct['inventory_runtime_id']); items=dict(inv['data']['items']); items[item_ref]=int(items.get(item_ref,0))+int(qty)
        self._apply_sets(inv['entity_runtime_id'],{'data.items':items},'COUNTRY_BRIDGE_HARVEST_INVENTORY')

    def hunt_fauna(self,*,npc_id:str,block_id:str,fauna_id:str,quantity:int)->dict[str,Any]:
        if not isinstance(quantity,int) or quantity<=0: raise ValueError('quantity must be positive')
        npc=self.country.npc(npc_id); b=self.country.block(block_id); fauna=next((x for x in b['fauna'] if x['id']==fauna_id),None)
        if fauna is None: raise KeyError(fauna_id)
        if npc.get('block_id')!=block_id:return {'status':'REJECTED','reason':'ACTOR_NOT_IN_BLOCK','authority':'CombatSystem via CountryLivingDomainBridge'}
        if npc['class']=='CHILD' or not npc['protection']['combat_targetable']:return {'status':'REJECTED','reason':'PROTECTED_MINOR_COMBAT','authority':'CombatSystem via CountryLivingDomainBridge'}
        equip=self.equip_country_weapon(npc_id)
        if equip.get('status')!='PASS':return equip
        actor=self.ensure_npc(npc_id); self._locate_actor(actor['entity_runtime_id'],block_id,block_id,npc.get('city_id')); witness=self._ensure_witness(npc_id,block_id)
        kills=[]; requested=min(quantity,int(fauna['count']))
        for _ in range(requested):
            target=self._spawn_country_fauna_target(block_id,fauna); final=None; attacks=0
            while self.runtime.get_entity(self.world_instance_id,target['entity_runtime_id'])['lifecycle']=='ACTIVE' and attacks<24:
                final=self.combat.attack(self.world_instance_id,actor['entity_runtime_id'],target['entity_runtime_id']); attacks+=1
            tstate=self.runtime.get_entity(self.world_instance_id,target['entity_runtime_id'])
            if tstate['lifecycle']!='DEAD':
                kills.append({'status':'ESCAPED_OR_UNRESOLVED','target_ref':target['entity_runtime_id'],'attacks':attacks}); continue
            fauna['count']=max(0,int(fauna['count'])-1); fauna['status']='EXTIRPATED_LOCAL' if fauna['count']==0 else 'ACTIVE'
            loot=None
            if final and final.get('corpse_ref'):
                harvested=self.combat.harvest_corpse(self.world_instance_id,actor['entity_runtime_id'],final['corpse_ref']); q=max(1,int(round(float(harvested['resource']['data']['quantity'])))); item_ref='ITEM-FAUNA-'+fauna['species_ref']; self._add_living_inventory(actor['entity_runtime_id'],item_ref,q); loot={'item_ref':item_ref,'quantity':q,'resource_ref':harvested['resource']['entity_runtime_id']}
            kills.append({'status':'KILLED','target_ref':target['entity_runtime_id'],'combat_event_id':final.get('event_id') if final else None,'corpse_ref':final.get('corpse_ref') if final else None,'attacks':attacks,'loot':loot})
        self._project_npc(npc_id,actor['entity_runtime_id']); self.country.reconcile_country_inventory()
        memories=0
        if witness:
            memories=len(self.social.recall_memories(self.world_instance_id,witness,limit=100))
        out={'status':'PASS','engine':'CombatSystem','bridge':'CountryLivingDomainBridge','requested':quantity,'killed':sum(x['status']=='KILLED' for x in kills),'remaining':fauna['count'],'kills':kills,'witness_ref':witness,'witness_memory_count':memories,'country_projection_updated':True}
        self.country._record_event('COUNTRY_HUNT_PROJECTED_FROM_LIVING',out); return out

    def attack_country_npc(self,attacker_npc_id:str,target_npc_id:str)->dict[str,Any]:
        attacker_policy=self.country.can_target(attacker_npc_id)
        attacker=self.country.npc(attacker_npc_id)
        if attacker.get('class')=='CHILD' or not attacker_policy['allowed']:
            return {'status':'REJECTED','reason':'PROTECTED_MINOR_COMBAT','protection_enforced_by':'Country+Living Bridge'}
        policy=self.country.can_target(target_npc_id)
        if not policy['allowed']:return {'status':'REJECTED','reason':policy['reason'],'protection_enforced_by':'Country+Living Bridge'}
        a=self.country.npc(attacker_npc_id); t=self.country.npc(target_npc_id)
        if a['block_id']!=t['block_id']:return {'status':'REJECTED','reason':'NOT_COLOCATED'}
        eq=self.equip_country_weapon(attacker_npc_id)
        if eq.get('status')!='PASS':return eq
        ar=self.ensure_npc(attacker_npc_id); tr=self.ensure_npc(target_npc_id); self._locate_actor(ar['entity_runtime_id'],a['block_id'],a['block_id'],a.get('city_id')); self._locate_actor(tr['entity_runtime_id'],t['block_id'],t['block_id'],t.get('city_id'))
        r=self.combat.attack(self.world_instance_id,ar['entity_runtime_id'],tr['entity_runtime_id']); return {'status':'PASS','engine':'CombatSystem','result':r}

    def full_integrity_check(self)->dict[str,Any]:
        failures=[]; bindings=0
        rows=self.runtime.conn.execute('SELECT * FROM country_living_bindings WHERE world_instance_id=?',(self.world_instance_id,)).fetchall()
        for row in rows:
            bindings+=1
            if sha256_text(row['payload_json'])!=row['payload_hash']:failures.append('BINDING_HASH:'+row['country_ref']); continue
            try:self.runtime.get_entity(self.world_instance_id,row['runtime_ref'])
            except Exception:failures.append('BINDING_TARGET:'+row['country_ref'])
        # Bound projections must be synchronized after bridge actions.
        for row in rows:
            if row['binding_kind']=='NPC':
                npc=self.country.npc(row['country_ref']); actor=row['runtime_ref']; acct=self.commerce.account_state(self.world_instance_id,actor); wallet=self.runtime.get_entity(self.world_instance_id,acct['wallet_runtime_id'])
                if abs(float(npc['wallet']['balance'])-float(wallet['data']['balance']))>0.011:failures.append('NPC_WALLET_DIVERGENCE:'+npc['id'])
                living_items,_=self._living_owned_items(actor)
                country_items={k:int(v) for k,v in npc.get('inventory',{}).items() if int(v)>0}
                if living_items!=country_items:failures.append('NPC_INVENTORY_DIVERGENCE:'+npc['id'])
            elif row['binding_kind']=='SHOP':
                sh=self.country.shop(row['country_ref']); v=self.runtime.get_entity(self.world_instance_id,row['runtime_ref'])
                if abs(float(sh['wallet']['balance'])-float(v['data']['cash_balance']))>0.011:failures.append('SHOP_WALLET_DIVERGENCE:'+sh['id'])
                living_stock={k:int(v) for k,v in v['data'].get('stock',{}).items() if int(v)>0}
                country_stock={k:int(v) for k,v in sh.get('inventory',{}).items() if int(v)>0}
                if living_stock!=country_stock:failures.append('SHOP_INVENTORY_DIVERGENCE:'+sh['id'])
        c=self.commerce.full_integrity_check(self.world_instance_id); cb=self.combat.full_integrity_check(self.world_instance_id)
        if c['status']!='PASS':failures+=['COMMERCE:'+x for x in c.get('failures',[])]
        if cb['status']!='PASS':failures+=['COMBAT:'+x for x in cb.get('failures',[])]
        if self.country.domain_bridge is not self:failures.append('COUNTRY_BRIDGE_NOT_ATTACHED')
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'bindings':bindings,'commerce':c,'combat':cb,'authority':self.AUTHORITY}
