from __future__ import annotations

import copy, json, math, threading, zipfile
from pathlib import Path
from typing import Any

from living_runtime import (
    LivingRuntime, ValidationError, IntegrityError, ConflictError, NotFoundError,
    canonical_json, sha256_text, new_runtime_id, clock_point,
)

WEAPON_PATH="ANDROMEDA_CODEX_MASTER/05_MAR/FUNCTIONAL/01_MAR/MAR_WEAPONS_FUNCTIONAL_V1_0.json"
RELATIVE_PRICE_BASE={"BAIXO":30.0,"MÉDIO":60.0,"MEDIO":60.0,"ALTO":120.0}
REGULATION_FACTOR={"LIVRE":1.0,"CONTROLADA":1.10,"RESTRITA":1.25}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo,min(hi,v))


def _abs_tick(clock: dict[str,Any]) -> int:
    return int(clock["day"])*int(clock["ticks_per_day"])+int(clock["tick"])


class CommerceSystem:
    """Runtime commerce layer. Canon supplies identity/qualitative constraints; numeric economy remains runtime-only."""
    SCHEMA_VERSION=1

    def __init__(self, runtime: LivingRuntime, world_systems: Any|None=None) -> None:
        self.runtime=runtime; self.conn=runtime.conn; self.world_systems=world_systems; self._lock=threading.RLock(); self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self.runtime._write_lock:
            self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS commerce_catalog_snapshots(
              item_ref TEXT PRIMARY KEY, item_kind TEXT NOT NULL, source_path TEXT NOT NULL,
              payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS commerce_bindings(
              binding_id TEXT PRIMARY KEY, world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
              binding_kind TEXT NOT NULL, owner_ref TEXT, location_ref TEXT, entity_runtime_id TEXT NOT NULL,
              metadata_json TEXT NOT NULL, metadata_hash TEXT NOT NULL,
              UNIQUE(world_instance_id,binding_kind,owner_ref,location_ref)
            );
            CREATE TABLE IF NOT EXISTS commerce_price_quotes(
              quote_id TEXT PRIMARY KEY, world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
              direction TEXT NOT NULL, item_ref TEXT NOT NULL, vendor_runtime_id TEXT NOT NULL,
              buyer_ref TEXT NOT NULL, inventory_runtime_id TEXT NOT NULL, quantity INTEGER NOT NULL,
              unit_price REAL NOT NULL, total_price REAL NOT NULL, expires_abs_tick INTEGER NOT NULL,
              quote_json TEXT NOT NULL, quote_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS commerce_transactions(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id TEXT NOT NULL UNIQUE,
              world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
              event_id TEXT NOT NULL UNIQUE, idempotency_key TEXT NOT NULL,
              transaction_json TEXT NOT NULL, transaction_hash TEXT NOT NULL,
              UNIQUE(world_instance_id,idempotency_key)
            );
            CREATE TRIGGER IF NOT EXISTS commerce_catalog_no_update BEFORE UPDATE ON commerce_catalog_snapshots BEGIN SELECT RAISE(ABORT,'commerce catalog snapshot immutable'); END;
            CREATE TRIGGER IF NOT EXISTS commerce_catalog_no_delete BEFORE DELETE ON commerce_catalog_snapshots BEGIN SELECT RAISE(ABORT,'commerce catalog snapshot immutable'); END;
            CREATE TRIGGER IF NOT EXISTS commerce_quote_no_update BEFORE UPDATE ON commerce_price_quotes BEGIN SELECT RAISE(ABORT,'commerce quote immutable'); END;
            CREATE TRIGGER IF NOT EXISTS commerce_quote_no_delete BEFORE DELETE ON commerce_price_quotes BEGIN SELECT RAISE(ABORT,'commerce quote immutable'); END;
            CREATE TRIGGER IF NOT EXISTS commerce_transaction_no_update BEFORE UPDATE ON commerce_transactions BEGIN SELECT RAISE(ABORT,'commerce transaction immutable'); END;
            CREATE TRIGGER IF NOT EXISTS commerce_transaction_no_delete BEFORE DELETE ON commerce_transactions BEGIN SELECT RAISE(ABORT,'commerce transaction immutable'); END;
            """)
            self.conn.execute("INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('commerce_schema_version',?)",(str(self.SCHEMA_VERSION),))

    @staticmethod
    def _derived_gameplay_catalog() -> list[dict[str,Any]]:
        """Build the non-canonical runtime catalog needed by Country Scale.

        These identities come from the author-authorized V1.2.1 DEV content catalog and are
        deliberately tagged as gameplay derivations. They are not written to the sealed Master.
        Final ARPG itemization/balance replaces these temporary Stage-00 values later.
        """
        from content_catalog import ITEM_NAMES, DUNGEON_WEAPON_BY_REF
        out=[]
        for ref,name in sorted(ITEM_NAMES.items()):
            dungeon=DUNGEON_WEAPON_BY_REF.get(ref)
            if dungeon:
                st=dungeon.get("stats") or {}
                perf={
                    "reach": dungeon.get("tier","MÉDIO"),
                    "control": max(1,min(10,round(float(st.get("handling",50))/10))),
                    "stability": max(1,min(10,round((float(st.get("power",50))+float(st.get("utility",50)))/20))),
                    "mobility": max(1,min(10,round(float(st.get("handling",50))/10))),
                    "durability": max(1,min(10,round(float(dungeon.get("base_durability",50))/10))),
                    "relative_cost": dungeon.get("tier","MÉDIO"),
                }
                category="GAMEPLAY_DERIVED_WEAPON"
            else:
                if ref.startswith("MIN-"): tier="MÉDIO"
                elif ref.startswith("ITEM-MANA") or ref.startswith("ITEM-RUNE"): tier="ALTO"
                else: tier="BAIXO"
                perf={"reach":"N/A","control":0,"stability":0,"mobility":0,"durability":4,"relative_cost":tier}
                category="GAMEPLAY_DERIVED_ITEM"
            out.append({
                "id":ref,
                "name":name,
                "category":category,
                "canonical_status":"DERIVED_GAMEPLAY_NOT_CANON",
                "authority":"AUTHOR_AUTHORIZED_DEV_CONTENT_DERIVATION",
                "performance":perf,
                "balance":{"rarity":"STAGE00_PLACEHOLDER","status":"TEMPORARY_GAMEPLAY_BALANCE"},
                "distribution":{"classification":"RUNTIME","regulation":"LIVRE"},
                "supply":{"maintenance_location_id":None,"maintenance_job_id":None},
                "stage00_note":"Temporary operational record; replace during ARPG itemization stages without mutating Master V2.0.1.",
            })
        return out

    def load_catalog(self, master_release_path: str|Path, *, include_gameplay_derived: bool=False) -> dict[str,Any]:
        with zipfile.ZipFile(str(master_release_path)) as z:
            doc=json.loads(z.read(WEAPON_PATH))
            sources=[("WEAPON",WEAPON_PATH,doc["weapons"])]
        if include_gameplay_derived:
            derived=self._derived_gameplay_catalog()
            sources.append(("GAMEPLAY_DERIVED","RUNTIME_DERIVED_CONTENT_CATALOG_V1_2_1",derived))
        inserted=0; total=0; by_source={}
        with self._lock,self.runtime._write_lock:
            for kind,path,records in sources:
                by_source[path]=len(records); total+=len(records)
                for item in records:
                    ref=item.get("id")
                    if not isinstance(ref,str) or not ref: raise IntegrityError("commerce catalog item missing id")
                    text=canonical_json(item); h=sha256_text(text)
                    row=self.conn.execute("SELECT payload_hash FROM commerce_catalog_snapshots WHERE item_ref=?",(ref,)).fetchone()
                    if row:
                        if row["payload_hash"]!=h: raise IntegrityError("commerce catalog drift")
                        continue
                    self.conn.execute("INSERT INTO commerce_catalog_snapshots VALUES(?,?,?,?,?)",(ref,kind,path,text,h)); inserted+=1
        return {"status":"PASS","inserted":inserted,"count":total,"by_source":by_source,"authority":"MASTER_READ_ONLY_SNAPSHOT","numeric_price_authority":"RUNTIME_ONLY"}

    def catalog_item(self, item_ref: str) -> dict[str,Any]:
        row=self.conn.execute("SELECT payload_json,payload_hash FROM commerce_catalog_snapshots WHERE item_ref=?",(item_ref,)).fetchone()
        if not row: raise NotFoundError(f"commerce catalog item not found: {item_ref}")
        if sha256_text(row["payload_json"])!=row["payload_hash"]: raise IntegrityError("commerce catalog hash mismatch")
        return json.loads(row["payload_json"])

    def items_available_at(self, location_ref: str) -> list[dict[str,Any]]:
        rows=self.conn.execute("SELECT payload_json,payload_hash FROM commerce_catalog_snapshots ORDER BY item_ref").fetchall(); out=[]
        for row in rows:
            if sha256_text(row["payload_json"])!=row["payload_hash"]: raise IntegrityError("commerce catalog hash mismatch")
            item=json.loads(row["payload_json"]); dist=item.get("distribution") or {}; spatial=item.get("spatial") or {}; construction=item.get("construction") or {}
            if location_ref in {dist.get("poi_id"),spatial.get("poi_id"),construction.get("installation_id")}:
                out.append(item)
        return out

    def _state(self, world: dict[str,Any], kind: str, data: dict[str,Any]) -> dict[str,Any]:
        c=world["clock_state"]
        return {"state_id":new_runtime_id("state"),"world_instance_id":world["world_instance_id"],"timeline_id":world["timeline_id"],"entity_runtime_id":new_runtime_id(kind.lower()),"origin":"RUNTIME_BORN","entity_kind":kind,"lifecycle":"ACTIVE","version":0,"updated_at":clock_point(c["day"],c["tick"]),"data":copy.deepcopy(data),"protection":{},"runtime_authority":"RUNTIME_COMMERCE_NOT_CANON"}

    def _bind(self, world_instance_id: str, kind: str, entity_runtime_id: str, *, owner_ref: str|None=None, location_ref: str|None=None, metadata: dict[str,Any]|None=None) -> dict[str,Any]:
        bid=new_runtime_id("cmbind"); body={"binding_id":bid,"world_instance_id":world_instance_id,"binding_kind":kind,"owner_ref":owner_ref,"location_ref":location_ref,"entity_runtime_id":entity_runtime_id,"metadata":copy.deepcopy(metadata or {}),"authority":"RUNTIME_BINDING_NOT_CANON"}; text=canonical_json(body); h=sha256_text(text)
        self.conn.execute("INSERT INTO commerce_bindings VALUES(?,?,?,?,?,?,?,?)",(bid,world_instance_id,kind,owner_ref,location_ref,entity_runtime_id,text,h)); return body

    def _binding_entity(self, world_instance_id: str, kind: str, *, owner_ref: str|None=None, location_ref: str|None=None) -> dict[str,Any]:
        row=self.conn.execute("SELECT entity_runtime_id,metadata_json,metadata_hash FROM commerce_bindings WHERE world_instance_id=? AND binding_kind=? AND owner_ref IS ? AND location_ref IS ?",(world_instance_id,kind,owner_ref,location_ref)).fetchone()
        if not row: raise NotFoundError(f"commerce binding not found: {kind}")
        if sha256_text(row["metadata_json"])!=row["metadata_hash"]: raise IntegrityError("commerce binding hash mismatch")
        return self.runtime.get_entity(world_instance_id,row["entity_runtime_id"])

    def create_account(self, world_instance_id: str, owner_ref: str, *, starting_balance: float=0.0, currency: str="CREDIT_RUNTIME") -> dict[str,Any]:
        if not isinstance(owner_ref,str) or not owner_ref: raise ValidationError("owner_ref required")
        if owner_ref.startswith("rt:"): self.runtime.get_entity(world_instance_id,owner_ref)
        if not math.isfinite(float(starting_balance)) or float(starting_balance)<0: raise ValidationError("starting_balance must be finite and nonnegative")
        world=self.runtime.get_world(world_instance_id)
        with self._lock,self.runtime._write_lock:
            try: wallet=self._binding_entity(world_instance_id,"WALLET",owner_ref=owner_ref,location_ref=None)
            except NotFoundError:
                wallet=self._state(world,"WALLET",{"owner_ref":owner_ref,"currency":currency,"balance":round(float(starting_balance),4),"seed_policy":"RUNTIME_STARTING_BALANCE_NOT_CANON"}); self.runtime.register_entity(world_instance_id,wallet); self._bind(world_instance_id,"WALLET",wallet["entity_runtime_id"],owner_ref=owner_ref)
            try: inv=self._binding_entity(world_instance_id,"INVENTORY",owner_ref=owner_ref,location_ref=None)
            except NotFoundError:
                catalog_refs=[r["item_ref"] for r in self.conn.execute("SELECT item_ref FROM commerce_catalog_snapshots ORDER BY item_ref").fetchall()]
                inv=self._state(world,"INVENTORY",{"owner_ref":owner_ref,"items":{ref:0 for ref in catalog_refs},"capacity_policy":"UNBOUNDED_V1_1_RUNTIME","slot_seed_policy":"KNOWN_CATALOG_ZERO_QUANTITY_NOT_CANON"}); self.runtime.register_entity(world_instance_id,inv); self._bind(world_instance_id,"INVENTORY",inv["entity_runtime_id"],owner_ref=owner_ref)
        return {"status":"PASS","owner_ref":owner_ref,"wallet_runtime_id":wallet["entity_runtime_id"],"inventory_runtime_id":inv["entity_runtime_id"],"balance":wallet["data"]["balance"],"currency":wallet["data"]["currency"]}

    def create_vendor(self, world_instance_id: str, location_ref: str, *, name: str|None=None, stock_seed: int=5, starting_cash: float=1000.0, regulation_factor: float=1.0, catalog_refs: list[str]|None=None) -> dict[str,Any]:
        if not isinstance(stock_seed,int) or isinstance(stock_seed,bool) or stock_seed<0: raise ValidationError("stock_seed must be nonnegative integer")
        if float(starting_cash)<0 or not math.isfinite(float(starting_cash)): raise ValidationError("starting_cash invalid")
        if not 0.5<=float(regulation_factor)<=2.0: raise ValidationError("regulation_factor outside safe runtime range")
        if catalog_refs is None:
            available=self.items_available_at(location_ref)
        else:
            if not isinstance(catalog_refs,list) or any(not isinstance(x,str) or not x for x in catalog_refs): raise ValidationError("catalog_refs invalid")
            available=[self.catalog_item(ref) for ref in sorted(set(catalog_refs))]
        if not available: raise ConflictError("no catalog items available at location")
        world=self.runtime.get_world(world_instance_id)
        with self._lock,self.runtime._write_lock:
            try: vendor=self._binding_entity(world_instance_id,"VENDOR",owner_ref=None,location_ref=location_ref); return {"status":"PASS","idempotent_replay":True,"vendor":vendor}
            except NotFoundError: pass
            catalog_refs=[r["item_ref"] for r in self.conn.execute("SELECT item_ref FROM commerce_catalog_snapshots ORDER BY item_ref").fetchall()]
            stock={ref:0 for ref in catalog_refs}
            for i in available: stock[i["id"]]=stock_seed
            vendor=self._state(world,"VENDOR",{"name":name or f"Vendor@{location_ref}","location_ref":location_ref,"cash_balance":round(float(starting_cash),4),"stock":stock,"regulation_factor":float(regulation_factor),"stock_seed_policy":"RUNTIME_QUANTITY_NOT_CANON"}); self.runtime.register_entity(world_instance_id,vendor); self._bind(world_instance_id,"VENDOR",vendor["entity_runtime_id"],location_ref=location_ref,metadata={"catalog_refs":sorted(stock)})
        return {"status":"PASS","idempotent_replay":False,"vendor":vendor,"available_items":sorted(stock)}

    def _market_factors(self, world_instance_id: str, location_ref: str, item: dict[str,Any]) -> dict[str,Any]:
        pressure=0.0; scarcity_sources=[]; route_capacity=1.0; route_detail={"method":"NO_WORLD_SYSTEMS"}; demand_factor=1.0
        if self.world_systems is not None:
            loc=self.world_systems.resolve_location(location_ref); territory=loc.get("territory_ref")
            for cat in ("MATERIAL","TECHNOLOGY"):
                p=self.world_systems.local_product_pressure(world_instance_id,territory,cat); scarcity_sources.append(p)
            vals=[float(x["pressure"]) for x in scarcity_sources if x["scope"]!="NO_MATCH"]
            pressure=sum(vals)/len(vals) if vals else 0.0
            route_detail=self.world_systems.route_capacity_for_location(world_instance_id,location_ref); route_capacity=float(route_detail["capacity"])
            # Demand derives from the territory population rather than the POI id itself.
            try:
                pop=self.world_systems.resolve_destination_population(world_instance_id,location_ref); demand_factor=1.0+min(max(float(pop["factor"])-1.0,0.0)*0.05,0.25)
            except Exception: demand_factor=1.0
        scarcity_factor=1.0+_clamp(pressure,0,100)/200.0
        logistics_factor=1.0+(1.0-_clamp(route_capacity,0,1))*0.50
        return {"scarcity_pressure":round(pressure,4),"scarcity_factor":round(scarcity_factor,6),"scarcity_sources":scarcity_sources,"route_capacity":round(route_capacity,4),"logistics_factor":round(logistics_factor,6),"route_detail":route_detail,"demand_factor":round(demand_factor,6)}

    def quote(self, world_instance_id: str, buyer_ref: str, vendor_runtime_id: str, item_ref: str, *, quantity: int=1, condition: float=1.0, relationship_score: float=0.0, ttl_ticks: int=2, direction: str="BUY") -> dict[str,Any]:
        direction=direction.upper()
        if direction not in {"BUY","SELL"}: raise ValidationError("direction must be BUY or SELL")
        if not isinstance(quantity,int) or isinstance(quantity,bool) or quantity<=0: raise ValidationError("quantity must be positive integer")
        if not 0.1<=float(condition)<=1.2: raise ValidationError("condition outside runtime pricing range")
        if not -100<=float(relationship_score)<=100: raise ValidationError("relationship_score must be -100..100")
        if not isinstance(ttl_ticks,int) or ttl_ticks<1: raise ValidationError("ttl_ticks must be positive integer")
        buyer=self.create_account(world_instance_id,buyer_ref); wallet=self.runtime.get_entity(world_instance_id,buyer["wallet_runtime_id"]); inv=self.runtime.get_entity(world_instance_id,buyer["inventory_runtime_id"]); vendor=self.runtime.get_entity(world_instance_id,vendor_runtime_id)
        if vendor.get("entity_kind")!="VENDOR" or vendor.get("lifecycle")!="ACTIVE": raise ValidationError("vendor_runtime_id is not an active vendor")
        if isinstance(buyer_ref,str) and buyer_ref.startswith("rt:"):
            buyer_state=self.runtime.get_entity(world_instance_id,buyer_ref); buyer_data=buyer_state.get("data") or {}; buyer_location=buyer_data.get("location_ref"); vendor_location=vendor["data"].get("location_ref")
            active_travel=buyer_data.get("travel") if isinstance(buyer_data.get("travel"),dict) else {}
            if active_travel.get("status")=="IN_TRANSIT": raise ConflictError("buyer is in transit and cannot trade")
            if buyer_location!=vendor_location: raise ConflictError("buyer is not co-located with vendor")
        item=self.catalog_item(item_ref); stock=int((vendor.get("data") or {}).get("stock",{}).get(item_ref,0)); owned=int((inv.get("data") or {}).get("items",{}).get(item_ref,0))
        if direction=="BUY" and stock<quantity: raise ConflictError("vendor stock insufficient")
        if direction=="SELL" and owned<quantity: raise ConflictError("inventory quantity insufficient")
        relative=str((item.get("performance") or {}).get("relative_cost","")).upper(); base=RELATIVE_PRICE_BASE.get(relative)
        if base is None: raise ConflictError(f"relative cost has no runtime policy: {relative}")
        market=self._market_factors(world_instance_id,vendor["data"]["location_ref"],item)
        reg_label=str((item.get("distribution") or {}).get("regulation","")).upper(); canon_reg=REGULATION_FACTOR.get(reg_label,1.0); vendor_reg=float(vendor["data"].get("regulation_factor",1.0)); reg_factor=canon_reg*vendor_reg
        condition_factor=float(condition); relationship_factor=_clamp(1.0-float(relationship_score)*0.001,0.90,1.10)
        gross=base*market["scarcity_factor"]*market["logistics_factor"]*market["demand_factor"]*reg_factor*condition_factor*relationship_factor
        if direction=="SELL": gross*=0.60
        unit=round(max(1.0,gross),2); total=round(unit*quantity,2)
        world=self.runtime.get_world(world_instance_id); c=world["clock_state"]; quote_id=new_runtime_id("quote"); expires=_abs_tick(c)+ttl_ticks
        body={"quote_id":quote_id,"world_instance_id":world_instance_id,"direction":direction,"item_ref":item_ref,"item_name":item.get("name"),"relative_cost":relative,"relative_cost_authority":"MASTER_QUALITATIVE_ONLY","numeric_price_authority":"RUNTIME_ONLY","buyer_ref":buyer_ref,"wallet_runtime_id":wallet["entity_runtime_id"],"inventory_runtime_id":inv["entity_runtime_id"],"vendor_runtime_id":vendor_runtime_id,"vendor_location_ref":vendor["data"]["location_ref"],"quantity":quantity,"unit_price":unit,"total_price":total,"currency":wallet["data"]["currency"],"condition":float(condition),"factors":{"relative_band_base":base,**market,"canon_regulation":reg_label,"regulation_factor":round(reg_factor,6),"condition_factor":condition_factor,"relationship_score":float(relationship_score),"relationship_factor":round(relationship_factor,6),"sell_buyback_factor":0.60 if direction=="SELL" else None},"snapshot_versions":{"wallet":wallet["version"],"inventory":inv["version"],"vendor":vendor["version"]},"created_abs_tick":_abs_tick(c),"expires_abs_tick":expires}
        text=canonical_json(body); h=sha256_text(text)
        with self._lock,self.runtime._write_lock:
            self.conn.execute("INSERT INTO commerce_price_quotes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(quote_id,world_instance_id,direction,item_ref,vendor_runtime_id,buyer_ref,inv["entity_runtime_id"],quantity,unit,total,expires,text,h))
        return body

    def _get_quote(self, quote_id: str) -> dict[str,Any]:
        row=self.conn.execute("SELECT quote_json,quote_hash FROM commerce_price_quotes WHERE quote_id=?",(quote_id,)).fetchone()
        if not row: raise NotFoundError("quote not found")
        if sha256_text(row["quote_json"])!=row["quote_hash"]: raise IntegrityError("quote hash mismatch")
        return json.loads(row["quote_json"])

    def _validate_quote_state(self, q: dict[str,Any]) -> tuple[dict[str,Any],dict[str,Any],dict[str,Any]]:
        world=self.runtime.get_world(q["world_instance_id"]); c=world["clock_state"]
        if _abs_tick(c)>int(q["expires_abs_tick"]): raise ConflictError("quote expired")
        wallet=self.runtime.get_entity(q["world_instance_id"],q["wallet_runtime_id"]); inv=self.runtime.get_entity(q["world_instance_id"],q["inventory_runtime_id"]); vendor=self.runtime.get_entity(q["world_instance_id"],q["vendor_runtime_id"])
        versions=q["snapshot_versions"]
        if wallet["version"]!=versions["wallet"] or inv["version"]!=versions["inventory"] or vendor["version"]!=versions["vendor"]: raise ConflictError("quote stale: commerce state changed")
        return wallet,inv,vendor

    def _ensure_numeric_item_path(self, world_instance_id: str, entity: dict[str,Any], item_ref: str) -> dict[str,Any]:
        # Runtime consequence INCREMENT/DECREMENT requires an existing numeric leaf. Initialize it through an auditable action.
        items=(entity.get("data") or {}).get("items")
        if items is None: items=(entity.get("data") or {}).get("stock")
        if isinstance(items,dict) and item_ref in items: return entity
        container="items" if entity.get("entity_kind")=="INVENTORY" else "stock"
        w=self.runtime.get_world(world_instance_id); c=w["clock_state"]
        action={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":world_instance_id,"timeline_id":w["timeline_id"],"actor_ref":"SYSTEM_RECONCILIATION","action_type":"COMMERCE_ITEM_SLOT_INITIALIZED","parameters":{"entity_runtime_id":entity["entity_runtime_id"],"item_ref":item_ref},"precondition_snapshot":{"entity_versions":{entity["entity_runtime_id"]:entity["version"]}},"idempotency_key":f"commerce-slot:{entity['entity_runtime_id']}:{item_ref}","created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"SYSTEM_RECONCILIATION","execution_class":"ROUTINE_SAFE"}
        self.runtime.apply_action(world_instance_id,action,[{"target_ref":entity["entity_runtime_id"],"operation":"SET","field_path":f"data.{container}.{item_ref}","value":0,"priority":0,"kind":"DIRECT"}])
        return self.runtime.get_entity(world_instance_id,entity["entity_runtime_id"])

    def execute_quote(self, quote_id: str, *, idempotency_key: str) -> dict[str,Any]:
        if not isinstance(idempotency_key,str) or not idempotency_key: raise ValidationError("idempotency_key required")
        q=self._get_quote(quote_id); wid=q["world_instance_id"]
        self.reconcile_transactions(wid)
        old=self.conn.execute("SELECT transaction_json,transaction_hash FROM commerce_transactions WHERE world_instance_id=? AND idempotency_key=?",(wid,idempotency_key)).fetchone()
        if old:
            if sha256_text(old["transaction_json"])!=old["transaction_hash"]: raise IntegrityError("commerce transaction hash mismatch")
            out=json.loads(old["transaction_json"]); out["idempotent_replay"]=True; return out
        wallet,inv,vendor=self._validate_quote_state(q)
        item=q["item_ref"]; qty=int(q["quantity"]); total=float(q["total_price"])
        if q["direction"]=="BUY":
            if float(wallet["data"]["balance"])<total: raise ConflictError("insufficient funds")
            if int(vendor["data"]["stock"].get(item,0))<qty: raise ConflictError("vendor stock insufficient")
            inv=self._ensure_numeric_item_path(wid,inv,item)
            # Slot initialization changes the inventory version, so refresh the quote snapshot only for this controlled zero-slot creation.
            if inv["version"]!=q["snapshot_versions"]["inventory"]:
                q=copy.deepcopy(q); q["snapshot_versions"]["inventory"]=inv["version"]
            cons=[
              {"target_ref":wallet["entity_runtime_id"],"operation":"DECREMENT","field_path":"data.balance","amount":total,"priority":0,"kind":"DIRECT"},
              {"target_ref":vendor["entity_runtime_id"],"operation":"INCREMENT","field_path":"data.cash_balance","amount":total,"priority":1,"kind":"DIRECT"},
              {"target_ref":vendor["entity_runtime_id"],"operation":"DECREMENT","field_path":f"data.stock.{item}","amount":qty,"priority":2,"kind":"DIRECT"},
              {"target_ref":inv["entity_runtime_id"],"operation":"INCREMENT","field_path":f"data.items.{item}","amount":qty,"priority":3,"kind":"DIRECT"},
            ]
        else:
            if int(inv["data"]["items"].get(item,0))<qty: raise ConflictError("inventory quantity insufficient")
            if float(vendor["data"]["cash_balance"])<total: raise ConflictError("vendor cash insufficient")
            cons=[
              {"target_ref":wallet["entity_runtime_id"],"operation":"INCREMENT","field_path":"data.balance","amount":total,"priority":0,"kind":"DIRECT"},
              {"target_ref":vendor["entity_runtime_id"],"operation":"DECREMENT","field_path":"data.cash_balance","amount":total,"priority":1,"kind":"DIRECT"},
              {"target_ref":vendor["entity_runtime_id"],"operation":"INCREMENT","field_path":f"data.stock.{item}","amount":qty,"priority":2,"kind":"DIRECT"},
              {"target_ref":inv["entity_runtime_id"],"operation":"DECREMENT","field_path":f"data.items.{item}","amount":qty,"priority":3,"kind":"DIRECT"},
            ]
        world=self.runtime.get_world(wid); c=world["clock_state"]; action_id=new_runtime_id("action")
        action={"action_id":action_id,"intent_id":new_runtime_id("intent"),"world_instance_id":wid,"timeline_id":world["timeline_id"],"actor_ref":q["buyer_ref"] if str(q["buyer_ref"]).startswith("rt:") else "SYSTEM_RECONCILIATION","action_type":"COMMERCE_PURCHASE" if q["direction"]=="BUY" else "COMMERCE_SALE","parameters":{"quote_id":quote_id,"direction":q["direction"],"item_ref":item,"quantity":qty,"unit_price":q["unit_price"],"total_price":total,"currency":q["currency"],"vendor_runtime_id":vendor["entity_runtime_id"],"wallet_runtime_id":wallet["entity_runtime_id"],"inventory_runtime_id":inv["entity_runtime_id"],"commerce_idempotency_key":idempotency_key},"precondition_snapshot":{"entity_versions":{wallet["entity_runtime_id"]:wallet["version"],vendor["entity_runtime_id"]:vendor["version"],inv["entity_runtime_id"]:inv["version"]}},"idempotency_key":f"commerce:{idempotency_key}","created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"ACTION","execution_class":"INTERACTIVE"}
        result=self.runtime.apply_action(wid,action,cons)
        self.reconcile_transactions(wid)
        row=self.conn.execute("SELECT transaction_json,transaction_hash FROM commerce_transactions WHERE event_id=?",(result["event_id"],)).fetchone()
        if not row: raise IntegrityError("commerce event committed but transaction reconciliation failed")
        out=json.loads(row["transaction_json"]); out["idempotent_replay"]=False; return out

    def reconcile_transactions(self, world_instance_id: str) -> dict[str,Any]:
        rows=self.conn.execute("SELECT event_id,event_type,payload_json,occurred_day,occurred_tick FROM events WHERE world_instance_id=? AND event_type IN ('COMMERCE_PURCHASE','COMMERCE_SALE') ORDER BY sequence",(world_instance_id,)).fetchall(); inserted=0
        with self._lock,self.runtime._write_lock:
            for r in rows:
                if self.conn.execute("SELECT 1 FROM commerce_transactions WHERE event_id=?",(r["event_id"],)).fetchone(): continue
                payload=json.loads(r["payload_json"]); params=payload.get("parameters") or {}; key=params.get("commerce_idempotency_key")
                if not key: raise IntegrityError("commerce event missing idempotency key")
                tid=new_runtime_id("tx"); body={"transaction_id":tid,"world_instance_id":world_instance_id,"event_id":r["event_id"],"event_type":r["event_type"],"idempotency_key":key,"occurred_at":{"day":r["occurred_day"],"tick":r["occurred_tick"]},"item_ref":params.get("item_ref"),"quantity":params.get("quantity"),"unit_price":params.get("unit_price"),"total_price":params.get("total_price"),"currency":params.get("currency"),"direction":params.get("direction"),"vendor_runtime_id":params.get("vendor_runtime_id"),"wallet_runtime_id":params.get("wallet_runtime_id"),"inventory_runtime_id":params.get("inventory_runtime_id"),"authority":"RUNTIME_TRANSACTION_NOT_CANON"}; text=canonical_json(body); h=sha256_text(text)
                self.conn.execute("INSERT INTO commerce_transactions(transaction_id,world_instance_id,event_id,idempotency_key,transaction_json,transaction_hash) VALUES(?,?,?,?,?,?)",(tid,world_instance_id,r["event_id"],key,text,h)); inserted+=1
        return {"status":"PASS","inserted":inserted}

    def account_state(self, world_instance_id: str, owner_ref: str) -> dict[str,Any]:
        wallet=self._binding_entity(world_instance_id,"WALLET",owner_ref=owner_ref,location_ref=None); inv=self._binding_entity(world_instance_id,"INVENTORY",owner_ref=owner_ref,location_ref=None)
        return {"owner_ref":owner_ref,"balance":wallet["data"]["balance"],"currency":wallet["data"]["currency"],"items":copy.deepcopy(inv["data"]["items"]),"wallet_runtime_id":wallet["entity_runtime_id"],"inventory_runtime_id":inv["entity_runtime_id"]}

    def full_integrity_check(self, world_instance_id: str) -> dict[str,Any]:
        failures=[]
        for r in self.conn.execute("SELECT item_ref,payload_json,payload_hash FROM commerce_catalog_snapshots").fetchall():
            if sha256_text(r["payload_json"])!=r["payload_hash"]: failures.append(f"CATALOG_HASH:{r['item_ref']}")
        for r in self.conn.execute("SELECT binding_id,metadata_json,metadata_hash,entity_runtime_id FROM commerce_bindings WHERE world_instance_id=?",(world_instance_id,)).fetchall():
            if sha256_text(r["metadata_json"])!=r["metadata_hash"]: failures.append(f"BINDING_HASH:{r['binding_id']}")
            try:self.runtime.get_entity(world_instance_id,r["entity_runtime_id"])
            except Exception:failures.append(f"BINDING_ENTITY:{r['binding_id']}")
        for r in self.conn.execute("SELECT quote_id,quote_json,quote_hash FROM commerce_price_quotes WHERE world_instance_id=?",(world_instance_id,)).fetchall():
            if sha256_text(r["quote_json"])!=r["quote_hash"]: failures.append(f"QUOTE_HASH:{r['quote_id']}")
        for r in self.conn.execute("SELECT transaction_id,transaction_json,transaction_hash FROM commerce_transactions WHERE world_instance_id=?",(world_instance_id,)).fetchall():
            if sha256_text(r["transaction_json"])!=r["transaction_hash"]: failures.append(f"TRANSACTION_HASH:{r['transaction_id']}")
        return {"status":"PASS" if not failures else "FAIL","failures":failures,"catalog":self.conn.execute("SELECT COUNT(*) c FROM commerce_catalog_snapshots").fetchone()["c"],"transactions":self.conn.execute("SELECT COUNT(*) c FROM commerce_transactions WHERE world_instance_id=?",(world_instance_id,)).fetchone()["c"]}
