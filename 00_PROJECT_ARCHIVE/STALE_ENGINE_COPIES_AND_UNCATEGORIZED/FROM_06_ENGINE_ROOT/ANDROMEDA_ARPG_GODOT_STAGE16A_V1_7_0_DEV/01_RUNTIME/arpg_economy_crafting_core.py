from __future__ import annotations
import copy, hashlib, json, math, zipfile
from typing import Any
from living_runtime import ValidationError, ConflictError, NotFoundError, IntegrityError, canonical_json, sha256_text

class ARPGEconomyCraftingCore:
    AUTHORITY='ANDROMEDA_ARPG_STAGE13_ECONOMY_CRAFTING'
    GAMEPLAY_AUTHORITY='GAMEPLAY_DERIVED_STAGE13_REBALANCEABLE'
    COUNTRY_REF='TER-011'
    MARKET_REF='POI-002'; WORKSHOP_REF='POI-003'; WAREHOUSE_REF='POI-006'; INDUSTRIAL_REF='INDN-008'
    CURRENCY='CREDIT_RUNTIME_NOT_CANON'
    CULINARY_REFS={
      'CUL-PREP-NORM-TER011-001':'Grilo-Cobre tostado',
      'CUL-PREP-NORM-TER011-002':'Grilo-Cobre moído',
      'CUL-PREP-NORM-TER011-003':'Leite veluriano fermentado',
      'CUL-PREP-NORM-TER011-004':'Barra de viagem de leite veluriano concentrado',
    }
    CANON_GOODS={
      'ECO-GOOD-000001':'Leite veluriano',
      'ECO-GOOD-000006':'Grilo-Cobre — ingrediente comestível',
      'ECO-GOOD-000017':'Grãos',
      'ECO-GOOD-000019':'Frutos',
      'ECO-GOOD-000025':'Carnes — classe alimentar genérica',
      'ECO-GOOD-000038':'Serviço funcional de armazenamento',
    }
    RECIPES={
      'CRFT-S13-GRILO-TOSTADO':{'canonical_output_ref':'CUL-PREP-NORM-TER011-001','station':'MARKET_KITCHEN','inputs':{'ECO-GOOD-000006':1},'outputs':{'CUL-PREP-NORM-TER011-001':1}},
      'CRFT-S13-GRILO-MOIDO':{'canonical_output_ref':'CUL-PREP-NORM-TER011-002','station':'MARKET_KITCHEN','inputs':{'ECO-GOOD-000006':2},'outputs':{'CUL-PREP-NORM-TER011-002':1}},
      'CRFT-S13-LEITE-FERMENTADO':{'canonical_output_ref':'CUL-PREP-NORM-TER011-003','station':'MARKET_KITCHEN','inputs':{'ECO-GOOD-000001':1},'outputs':{'CUL-PREP-NORM-TER011-003':1}},
      'CRFT-S13-BARRA-VIAGEM':{'canonical_output_ref':'CUL-PREP-NORM-TER011-004','station':'MARKET_KITCHEN','inputs':{'ECO-GOOD-000001':2,'ECO-GOOD-000017':1},'outputs':{'CUL-PREP-NORM-TER011-004':1}},
    }
    BASE_PRICE_BY_KIND={'MATERIAL':18.0,'COMPONENT':48.0,'CONSUMABLE':30.0,'WEAPON':110.0,'ARMOR':95.0,'TOOL':65.0,'QUEST':10.0,'MISC':25.0}

    def __init__(self,engine:Any,world_instance_id:str)->None:
        self.engine=engine; self.runtime=engine.runtime; self.world_instance_id=world_instance_id
        self.items=engine.items_arpg(world_instance_id); self.mobility=engine.mobility_arpg(world_instance_id)
        self.technology=engine.technology_arpg(world_instance_id); self.narrative=engine.narrative_arpg(world_instance_id)
        self._init_schema(); self._load_canon(); self._bootstrap_item_projections(); self._bootstrap_recipes(); self._bootstrap_market()

    def _init_schema(self):
        with self.runtime._write_lock:
            self.runtime.conn.executescript('''
            CREATE TABLE IF NOT EXISTS arpg_economy_canon(world_instance_id TEXT NOT NULL, canonical_ref TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, PRIMARY KEY(world_instance_id,canonical_ref));
            CREATE TABLE IF NOT EXISTS arpg_economy_wallets(world_instance_id TEXT NOT NULL, owner_ref TEXT NOT NULL, balance REAL NOT NULL, currency TEXT NOT NULL, PRIMARY KEY(world_instance_id,owner_ref));
            CREATE TABLE IF NOT EXISTS arpg_economy_vendors(world_instance_id TEXT NOT NULL, vendor_ref TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, PRIMARY KEY(world_instance_id,vendor_ref));
            CREATE TABLE IF NOT EXISTS arpg_economy_market(world_instance_id TEXT NOT NULL, location_ref TEXT NOT NULL, item_ref TEXT NOT NULL, demand_index REAL NOT NULL, target_stock REAL NOT NULL, units_bought INTEGER NOT NULL, units_sold INTEGER NOT NULL, PRIMARY KEY(world_instance_id,location_ref,item_ref));
            CREATE TABLE IF NOT EXISTS arpg_economy_recipes(world_instance_id TEXT NOT NULL, recipe_ref TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, PRIMARY KEY(world_instance_id,recipe_ref));
            CREATE TABLE IF NOT EXISTS arpg_economy_stashes(world_instance_id TEXT NOT NULL, stash_ref TEXT NOT NULL, owner_ref TEXT NOT NULL, location_ref TEXT NOT NULL, PRIMARY KEY(world_instance_id,stash_ref), UNIQUE(world_instance_id,owner_ref,location_ref));
            CREATE TABLE IF NOT EXISTS arpg_economy_quotes(world_instance_id TEXT NOT NULL, quote_ref TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, PRIMARY KEY(world_instance_id,quote_ref));
            CREATE TABLE IF NOT EXISTS arpg_economy_events(world_instance_id TEXT NOT NULL, event_ref TEXT NOT NULL, event_type TEXT NOT NULL, payload_hash TEXT NOT NULL, result_json TEXT NOT NULL, result_hash TEXT NOT NULL, PRIMARY KEY(world_instance_id,event_ref));
            ''')

    @staticmethod
    def _stable(prefix,*parts): return prefix+hashlib.sha256('|'.join(map(str,parts)).encode()).hexdigest()[:18].upper()
    @staticmethod
    def _pack(x):
        t=canonical_json(x); return t,sha256_text(t)

    def _load_master_doc(self):
        with zipfile.ZipFile(self.engine.master_release_path) as z:
            return json.loads(z.read('ANDROMEDA_CODEX_MASTER/01_CANON/ANDROMEDA_CODEX_CANON_MASTER_V2_0_0.json'))
    def _walk(self,x):
        if isinstance(x,dict):
            yield x
            for v in x.values(): yield from self._walk(v)
        elif isinstance(x,list):
            for v in x: yield from self._walk(v)
    def _load_canon(self):
        wanted=set(self.CULINARY_REFS)|set(self.CANON_GOODS)|{self.MARKET_REF,self.WORKSHOP_REF,self.WAREHOUSE_REF,self.INDUSTRIAL_REF,'ECO-ARCH-COMP-TER-011'}
        found={}
        for d in self._walk(self._load_master_doc()):
            rid=d.get('id') or d.get('entity_id') or d.get('ref')
            if rid in wanted and rid not in found: found[rid]=d
        with self.runtime._write_lock:
            for ref,d in found.items():
                t,h=self._pack(d); self.runtime.conn.execute('INSERT OR IGNORE INTO arpg_economy_canon VALUES(?,?,?,?)',(self.world_instance_id,ref,t,h))
        self._canon=found
    def canonical_snapshot(self,ref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_economy_canon WHERE world_instance_id=? AND canonical_ref=?',(self.world_instance_id,ref)).fetchone()
        if not row: raise NotFoundError('economy canonical snapshot not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('economy canon hash mismatch')
        return json.loads(row['payload_json'])

    def _ensure_item_def(self,ref,name,kind='MATERIAL',canonical=True):
        try:return self.items.definition(ref)
        except Exception: pass
        base=self.items.definition('ITEM-GRAIN' if kind=='MATERIAL' else 'ITEM-FRUIT')
        d=copy.deepcopy(base); d.update({'item_ref':ref,'name':name,'item_kind':kind,'canonical_identity':bool(canonical),'canonical_status':'CANONICAL_IDENTITY_GAMEPLAY_PROJECTION' if canonical else 'GAMEPLAY_DERIVED_NOT_CANON','source_kind':'STAGE13_ECONOMY_CANON_PROJECTION','source_category':'ECONOMY_CULINARY','source_authority':'MASTER_READ_ONLY_IDENTITY' if canonical else self.GAMEPLAY_AUTHORITY,'authority':self.AUTHORITY,'source_snapshot_hash':hashlib.sha256(ref.encode()).hexdigest(),'art_dependency':'NONE_PLACEHOLDER_READY'})
        if kind=='CONSUMABLE': d['consumable_effect']=None
        t,h=self._pack(d)
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT INTO arpg_item_definitions(item_ref,source_kind,source_authority,payload_json,payload_hash) VALUES(?,?,?,?,?)',(ref,d['source_kind'],d['source_authority'],t,h))
        return d
    def _bootstrap_item_projections(self):
        for ref,name in self.CANON_GOODS.items():
            if ref=='ECO-GOOD-000038': continue
            self._ensure_item_def(ref,name,'MATERIAL',True)
        for ref,name in self.CULINARY_REFS.items(): self._ensure_item_def(ref,name,'CONSUMABLE',True)

    def _bootstrap_recipes(self):
        with self.runtime._write_lock:
            for ref,r in self.RECIPES.items():
                x={'recipe_ref':ref,**copy.deepcopy(r),'recipe_authority':'GAMEPLAY_DERIVED_QUANTITIES_CANONICAL_OUTPUT_IDENTITY','canon_guard':'Ingredient quantities are gameplay balance, not canonical facts.'}; t,h=self._pack(x)
                self.runtime.conn.execute('INSERT OR IGNORE INTO arpg_economy_recipes VALUES(?,?,?,?)',(self.world_instance_id,ref,t,h))
    def recipe(self,ref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_economy_recipes WHERE world_instance_id=? AND recipe_ref=?',(self.world_instance_id,ref)).fetchone()
        if not row: raise NotFoundError('craft recipe not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('recipe hash mismatch')
        return json.loads(row['payload_json'])
    def list_recipes(self): return [self.recipe(r['recipe_ref']) for r in self.runtime.conn.execute('SELECT recipe_ref FROM arpg_economy_recipes WHERE world_instance_id=? ORDER BY recipe_ref',(self.world_instance_id,))]

    def _bootstrap_market(self):
        # Runtime service nodes; no specific NPC merchant is canonized.
        self.create_vendor(self.MARKET_REF,'Mercado Fronteiriço de Varga',event_ref='BOOTSTRAP:S13:MARKET')
        self.create_vendor(self.WORKSHOP_REF,'Serviços da Oficina Arco Morto',event_ref='BOOTSTRAP:S13:WORKSHOP')
        self.create_vendor(self.WAREHOUSE_REF,'Armazém Rural da Fronteira',event_ref='BOOTSTRAP:S13:WAREHOUSE')

    def _event_old(self,event_ref,event_type,payload):
        row=self.runtime.conn.execute('SELECT event_type,payload_hash,result_json,result_hash FROM arpg_economy_events WHERE world_instance_id=? AND event_ref=?',(self.world_instance_id,event_ref)).fetchone()
        if not row:return None
        ph=sha256_text(canonical_json(payload))
        if row['event_type']!=event_type or row['payload_hash']!=ph: raise ConflictError('STAGE13_EVENT_REF_CONFLICT')
        if sha256_text(row['result_json'])!=row['result_hash']: raise IntegrityError('economy event hash mismatch')
        out=json.loads(row['result_json']); out['idempotent_replay']=True; return out
    def _record(self,event_ref,event_type,payload,result):
        ph=sha256_text(canonical_json(payload)); out=copy.deepcopy(result); out.setdefault('idempotent_replay',False); t,h=self._pack(out)
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT INTO arpg_economy_events VALUES(?,?,?,?,?,?)',(self.world_instance_id,event_ref,event_type,ph,t,h))
        return out

    def ensure_wallet(self,owner_ref,starting_balance=250.0):
        self.items.ensure_inventory(owner_ref)
        row=self.runtime.conn.execute('SELECT balance,currency FROM arpg_economy_wallets WHERE world_instance_id=? AND owner_ref=?',(self.world_instance_id,owner_ref)).fetchone()
        if not row:
            with self.runtime._write_lock:self.runtime.conn.execute('INSERT INTO arpg_economy_wallets VALUES(?,?,?,?)',(self.world_instance_id,owner_ref,float(starting_balance),self.CURRENCY))
            return {'owner_ref':owner_ref,'balance':float(starting_balance),'currency':self.CURRENCY}
        return {'owner_ref':owner_ref,'balance':float(row['balance']),'currency':row['currency']}
    def wallet(self,owner_ref): return self.ensure_wallet(owner_ref)
    def _set_balance(self,owner_ref,balance):
        if balance < -1e-9: raise ConflictError('negative wallet balance forbidden')
        with self.runtime._write_lock:self.runtime.conn.execute('UPDATE arpg_economy_wallets SET balance=? WHERE world_instance_id=? AND owner_ref=?',(round(float(balance),4),self.world_instance_id,owner_ref))

    def create_vendor(self,location_ref,name,*,event_ref):
        payload={'location_ref':location_ref,'name':name}; old=self._event_old(event_ref,'CREATE_VENDOR',payload)
        if old:return old
        ref=self._stable('SHOP-S13-',self.COUNTRY_REF,location_ref)
        existing=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_economy_vendors WHERE world_instance_id=? AND vendor_ref=?',(self.world_instance_id,ref)).fetchone()
        if existing:
            out=json.loads(existing['payload_json']); return {'status':'PASS','vendor':out,'idempotent_replay':True}
        v={'vendor_ref':ref,'location_ref':location_ref,'name':name,'country_ref':self.COUNTRY_REF,'merchant_identity_claimed':False,'authority':'GAMEPLAY_DERIVED_SERVICE_NODE_ON_CANONICAL_LOCATION'}
        t,h=self._pack(v)
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT INTO arpg_economy_vendors VALUES(?,?,?,?)',(self.world_instance_id,ref,t,h))
        self.items.ensure_inventory(ref,slot_capacity=160,weight_capacity=5000.0); self.ensure_wallet(ref,2000.0)
        # Deterministic starter stock; quantities are gameplay-only.
        seed={'POI-002':{'ITEM-GRAIN':20,'ITEM-FRUIT':12,'ECO-GOOD-000001':8,'ECO-GOOD-000006':10},'POI-003':{'MIN-IRON':15,'MIN-COPPER':12,'ITEM-CIRCUIT':4},'POI-006':{'ITEM-GRAIN':30,'MIN-IRON':10,'ITEM-HARVEST-FLR-HARDWOOD':18}}.get(location_ref,{})
        for item,qty in seed.items():
            try:self.items.grant_item(ref,item,qty,event_ref=f'{event_ref}:stock:{item}')
            except Exception:pass
        return self._record(event_ref,'CREATE_VENDOR',payload,{'status':'PASS','vendor':v})
    def vendor(self,ref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_economy_vendors WHERE world_instance_id=? AND vendor_ref=?',(self.world_instance_id,ref)).fetchone()
        if not row: raise NotFoundError('vendor not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('vendor hash mismatch')
        return json.loads(row['payload_json'])
    def list_vendors(self): return [self.vendor(r['vendor_ref']) for r in self.runtime.conn.execute('SELECT vendor_ref FROM arpg_economy_vendors WHERE world_instance_id=? ORDER BY vendor_ref',(self.world_instance_id,))]

    def ensure_stash(self,owner_ref,location_ref=None):
        location_ref=location_ref or self.MARKET_REF; self.items.ensure_inventory(owner_ref)
        row=self.runtime.conn.execute('SELECT stash_ref FROM arpg_economy_stashes WHERE world_instance_id=? AND owner_ref=? AND location_ref=?',(self.world_instance_id,owner_ref,location_ref)).fetchone()
        if row:return row['stash_ref']
        ref=self._stable('STASH-S13-',self.world_instance_id,owner_ref,location_ref)
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT INTO arpg_economy_stashes VALUES(?,?,?,?)',(self.world_instance_id,ref,owner_ref,location_ref))
        self.items.ensure_inventory(ref,slot_capacity=240,weight_capacity=10000.0); return ref
    def stash_deposit(self,owner_ref,item_ref,quantity,*,event_ref,instance_ref=None):
        stash=self.ensure_stash(owner_ref); return self.items.transfer_item(owner_ref,stash,item_ref,int(quantity),event_ref=event_ref,instance_ref=instance_ref)
    def stash_withdraw(self,owner_ref,item_ref,quantity,*,event_ref,instance_ref=None):
        stash=self.ensure_stash(owner_ref); return self.items.transfer_item(stash,owner_ref,item_ref,int(quantity),event_ref=event_ref,instance_ref=instance_ref)

    def _base_price(self,item_ref):
        d=self.items.definition(item_ref); base=self.BASE_PRICE_BY_KIND.get(d.get('item_kind'),'MISC' in self.BASE_PRICE_BY_KIND and self.BASE_PRICE_BY_KIND['MISC'] or 25.0)
        if d.get('canonical_identity'): base*=1.1
        return float(base)
    def _market_row(self,location_ref,item_ref):
        row=self.runtime.conn.execute('SELECT demand_index,target_stock,units_bought,units_sold FROM arpg_economy_market WHERE world_instance_id=? AND location_ref=? AND item_ref=?',(self.world_instance_id,location_ref,item_ref)).fetchone()
        if not row:
            with self.runtime._write_lock:self.runtime.conn.execute('INSERT INTO arpg_economy_market VALUES(?,?,?,?,?,?,?)',(self.world_instance_id,location_ref,item_ref,1.0,20.0,0,0))
            return {'demand_index':1.0,'target_stock':20.0,'units_bought':0,'units_sold':0}
        return dict(row)
    def _vendor_qty(self,vendor_ref,item_ref):
        inv=self.items.inventory_snapshot(vendor_ref); d=self.items.definition(item_ref)
        if d['stackable']: return int(inv.get('stacks',{}).get(item_ref,0))
        return sum(1 for ir in inv.get('instance_refs',[]) if self.items.instance(ir)['item_ref']==item_ref)
    def _logistics_factor(self):
        try:
            b=self.mobility.bridge('POI-046')
            return 1.25 if not b.get('operational') else round(1.0+(1.0-float(b.get('capacity_factor',1.0)))*0.15,6)
        except Exception:return 1.0
    def price_quote(self,owner_ref,vendor_ref,item_ref,quantity=1,*,direction='BUY',instance_ref=None,event_ref):
        direction=direction.upper(); quantity=int(quantity)
        if direction not in {'BUY','SELL'} or quantity<=0: raise ValidationError('invalid quote request')
        payload={'owner_ref':owner_ref,'vendor_ref':vendor_ref,'item_ref':item_ref,'quantity':quantity,'direction':direction,'instance_ref':instance_ref}; old=self._event_old(event_ref,'PRICE_QUOTE',payload)
        if old:return old
        self.ensure_wallet(owner_ref); v=self.vendor(vendor_ref); d=self.items.definition(item_ref); self.items.ensure_inventory(owner_ref)
        if not d['stackable'] and (quantity!=1 or not instance_ref) and direction=='SELL': raise ValidationError('unique sale requires instance_ref')
        stock=self._vendor_qty(vendor_ref,item_ref); m=self._market_row(v['location_ref'],item_ref); target=float(m['target_stock']); scarcity=max(0.70,min(2.25,1.0+(target-stock)/max(target,1.0)*0.65)); demand=max(0.75,min(1.75,float(m['demand_index']))); logistics=self._logistics_factor(); base=self._base_price(item_ref); unit=base*scarcity*demand*logistics
        if direction=='SELL': unit*=0.58
        unit=round(max(1.0,unit),2); total=round(unit*quantity,2); qref=self._stable('QUOTE-S13-',event_ref,owner_ref,vendor_ref,item_ref,direction)
        q={'quote_ref':qref,**payload,'location_ref':v['location_ref'],'unit_price':unit,'total_price':total,'currency':self.CURRENCY,'factors':{'base':round(base,2),'scarcity':round(scarcity,6),'demand':round(demand,6),'logistics':round(logistics,6),'vendor_stock':stock,'target_stock':target},'numeric_price_authority':'GAMEPLAY_DERIVED_RUNTIME_NOT_CANON'}
        t,h=self._pack(q)
        with self.runtime._write_lock:self.runtime.conn.execute('INSERT OR REPLACE INTO arpg_economy_quotes VALUES(?,?,?,?)',(self.world_instance_id,qref,t,h))
        return self._record(event_ref,'PRICE_QUOTE',payload,{'status':'PASS','quote':q})
    def _quote(self,qref):
        row=self.runtime.conn.execute('SELECT payload_json,payload_hash FROM arpg_economy_quotes WHERE world_instance_id=? AND quote_ref=?',(self.world_instance_id,qref)).fetchone()
        if not row: raise NotFoundError('quote not found')
        if sha256_text(row['payload_json'])!=row['payload_hash']: raise IntegrityError('quote hash mismatch')
        return json.loads(row['payload_json'])
    def execute_trade(self,quote_ref,*,event_ref,inventory_owner_ref=None):
        q=self._quote(quote_ref); payload={'quote_ref':quote_ref}
        if inventory_owner_ref is not None: payload['inventory_owner_ref']=str(inventory_owner_ref)
        old=self._event_old(event_ref,'EXECUTE_TRADE',payload)
        if old:return old
        owner=q['owner_ref']; vendor=q['vendor_ref']; item=q['item_ref']; qty=int(q['quantity']); total=float(q['total_price']); direction=q['direction']; inv_owner=str(inventory_owner_ref or owner); ow=self.wallet(owner); vw=self.wallet(vendor)
        if direction=='BUY':
            if ow['balance']<total:return self._record(event_ref,'EXECUTE_TRADE',payload,{'status':'REJECTED','reason':'INSUFFICIENT_FUNDS'})
            d=self.items.definition(item)
            if d['stackable']:
                if self._vendor_qty(vendor,item)<qty:return self._record(event_ref,'EXECUTE_TRADE',payload,{'status':'REJECTED','reason':'VENDOR_STOCK_INSUFFICIENT'})
                tr=self.items.transfer_item(vendor,inv_owner,item,qty,event_ref=f'{event_ref}:item')
            else:
                # Buying a unique item requires the quote to identify a vendor-owned instance.
                inst=q.get('instance_ref')
                if not inst:return self._record(event_ref,'EXECUTE_TRADE',payload,{'status':'REJECTED','reason':'UNIQUE_INSTANCE_REQUIRED'})
                tr=self.items.transfer_item(vendor,inv_owner,item,1,event_ref=f'{event_ref}:item',instance_ref=inst)
            if tr.get('status')!='PASS': return self._record(event_ref,'EXECUTE_TRADE',payload,{'status':'REJECTED','reason':'ITEM_TRANSFER_FAILED','detail':tr})
            self._set_balance(owner,ow['balance']-total); self._set_balance(vendor,vw['balance']+total); delta_buy=qty; delta_sell=0
        else:
            if vw['balance']<total:return self._record(event_ref,'EXECUTE_TRADE',payload,{'status':'REJECTED','reason':'VENDOR_FUNDS_INSUFFICIENT'})
            tr=self.items.transfer_item(inv_owner,vendor,item,qty,event_ref=f'{event_ref}:item',instance_ref=q.get('instance_ref'))
            if tr.get('status')!='PASS': return self._record(event_ref,'EXECUTE_TRADE',payload,{'status':'REJECTED','reason':'ITEM_TRANSFER_FAILED','detail':tr})
            self._set_balance(owner,ow['balance']+total); self._set_balance(vendor,vw['balance']-total); delta_buy=0; delta_sell=qty
        m=self._market_row(q['location_ref'],item); demand=max(0.75,min(1.75,float(m['demand_index'])+(0.03*delta_buy)-(0.02*delta_sell)))
        with self.runtime._write_lock:self.runtime.conn.execute('UPDATE arpg_economy_market SET demand_index=?,units_bought=units_bought+?,units_sold=units_sold+? WHERE world_instance_id=? AND location_ref=? AND item_ref=?',(demand,delta_buy,delta_sell,self.world_instance_id,q['location_ref'],item))
        return self._record(event_ref,'EXECUTE_TRADE',payload,{'status':'PASS','direction':direction,'item_ref':item,'quantity':qty,'total_price':total,'inventory_owner_ref':inv_owner,'owner_wallet':self.wallet(owner),'vendor_wallet':self.wallet(vendor),'market_demand_index':round(demand,6)})

    def craft(self,actor_ref,recipe_ref,*,event_ref,station_ref=None):
        payload={'actor_ref':actor_ref,'recipe_ref':recipe_ref,'station_ref':station_ref}; old=self._event_old(event_ref,'CRAFT',payload)
        if old:return old
        r=self.recipe(recipe_ref); station=station_ref or self.MARKET_REF
        if r['station']=='MARKET_KITCHEN' and station!=self.MARKET_REF:return self._record(event_ref,'CRAFT',payload,{'status':'REJECTED','reason':'WRONG_STATION'})
        inv=self.items.inventory_snapshot(actor_ref)
        for item,qty in r['inputs'].items():
            if int(inv.get('stacks',{}).get(item,0))<int(qty):return self._record(event_ref,'CRAFT',payload,{'status':'REJECTED','reason':'MISSING_INPUT','item_ref':item})
        for item,qty in r['inputs'].items():self.items.remove_item(actor_ref,item,int(qty),event_ref=f'{event_ref}:consume:{item}')
        for item,qty in r['outputs'].items():self.items.grant_item(actor_ref,item,int(qty),event_ref=f'{event_ref}:produce:{item}')
        return self._record(event_ref,'CRAFT',payload,{'status':'PASS','recipe_ref':recipe_ref,'outputs':copy.deepcopy(r['outputs']),'recipe_authority':r['recipe_authority']})

    def list_crafting_catalog(self):
        return {'stage13_culinary':self.list_recipes(),'stage11_technology':self.technology.list_recipes(),'authority':self.AUTHORITY,'numeric_recipe_authority':'GAMEPLAY_DERIVED'}

    def craft_dispatch(self,actor_ref,recipe_ref,*,event_ref,station_ref=None,machine_ref=None):
        if str(recipe_ref).startswith('CRFT-S13-'):
            return self.craft(actor_ref,recipe_ref,event_ref=event_ref,station_ref=station_ref)
        tech_refs={r['recipe_ref'] for r in self.technology.list_recipes()}
        if recipe_ref in tech_refs:
            if not machine_ref: raise ValidationError('technology crafting requires machine_ref')
            return self.technology.run_recipe(actor_ref,machine_ref,recipe_ref,event_ref=event_ref)
        raise NotFoundError('craft recipe not found in unified catalog')

    def repair_service(self,owner_ref,vendor_ref,instance_ref,*,event_ref):
        payload={'owner_ref':owner_ref,'vendor_ref':vendor_ref,'instance_ref':instance_ref}; old=self._event_old(event_ref,'REPAIR_SERVICE',payload)
        if old:return old
        v=self.vendor(vendor_ref)
        if v['location_ref']!=self.WORKSHOP_REF:return self._record(event_ref,'REPAIR_SERVICE',payload,{'status':'REJECTED','reason':'VENDOR_NOT_WORKSHOP'})
        inst=self.items.instance(instance_ref); missing=max(0.0,float(inst.get('max_durability',0.0))-float(inst.get('durability',0.0)))
        if missing<=0:return self._record(event_ref,'REPAIR_SERVICE',payload,{'status':'REJECTED','reason':'NO_REPAIR_NEEDED'})
        cost=round(max(1.0,missing*0.75),2); w=self.wallet(owner_ref); vw=self.wallet(vendor_ref)
        if w['balance']<cost:return self._record(event_ref,'REPAIR_SERVICE',payload,{'status':'REJECTED','reason':'INSUFFICIENT_FUNDS'})
        res=self.items.repair_instance(owner_ref,instance_ref,event_ref=f'{event_ref}:repair',repair_authority='STAGE13_WORKSHOP_SERVICE')
        if res.get('status')!='PASS':return self._record(event_ref,'REPAIR_SERVICE',payload,{'status':'REJECTED','reason':'ITEM_REPAIR_FAILED','detail':res})
        self._set_balance(owner_ref,w['balance']-cost); self._set_balance(vendor_ref,vw['balance']+cost)
        return self._record(event_ref,'REPAIR_SERVICE',payload,{'status':'PASS','cost':cost,'currency':self.CURRENCY,'repair':res})

    def market_snapshot(self,location_ref=None):
        location_ref=location_ref or self.MARKET_REF; rows=[]
        for v in self.list_vendors():
            if v['location_ref']!=location_ref: continue
            inv=self.items.inventory_snapshot(v['vendor_ref']); rows.append({'vendor':v,'wallet':self.wallet(v['vendor_ref']),'inventory':inv})
        return {'location_ref':location_ref,'vendors':rows,'numeric_prices_canonical':False,'authority':self.AUTHORITY}

    def verify(self):
        failures=[]
        try:
            if len(self.CULINARY_REFS)!=4:failures.append('CULINARY_COUNT')
            if len(self.list_recipes())!=4:failures.append('RECIPE_COUNT')
            vendors=self.list_vendors()
            if len(vendors)<3:failures.append('VENDOR_COUNT')
            for ref in [self.MARKET_REF,self.WORKSHOP_REF,self.WAREHOUSE_REF]:
                if ref not in self._canon: failures.append('CANON_ANCHOR:'+ref)
            for ref in self.CULINARY_REFS:
                d=self.items.definition(ref)
                if not d.get('canonical_identity'):failures.append('CULINARY_ITEM_IDENTITY:'+ref)
            if self.CURRENCY!='CREDIT_RUNTIME_NOT_CANON':failures.append('CURRENCY_GUARD')
        except Exception as e: failures.append('EXCEPTION:'+type(e).__name__+':'+str(e))
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'vendors':len(self.list_vendors()) if not failures else None,'recipes':len(self.RECIPES),'culinary_projections':len(self.CULINARY_REFS),'currency_authority':'RUNTIME_ONLY_NOT_CANON','authority':self.AUTHORITY}
