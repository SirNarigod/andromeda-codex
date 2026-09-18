from __future__ import annotations

import copy, hashlib, math
from typing import Any

from commerce_system import RELATIVE_PRICE_BASE

from living_runtime import (
    LivingRuntime, ValidationError, IntegrityError, ConflictError, NotFoundError,
    new_runtime_id, clock_point,
)


COMBAT_PROFILE_POLICY={
    "AGENT":{"max_health":100.0,"defense":5.0,"evasion":5.0},
    "ANIMAL":{"max_health":40.0,"defense":3.0,"evasion":7.0},
    "CREATURE":{"max_health":60.0,"defense":6.0,"evasion":4.0},
}
YIELD_POLICY={"ANIMAL":2.0,"CREATURE":3.0}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo,min(hi,v))


class CombatSystem:
    """Abstract game-combat resolver bridging MAR equipment to Living state.

    Numeric health/damage/yield values are runtime balancing policy, never canon.
    """
    SCHEMA_VERSION=1

    def __init__(self, runtime: LivingRuntime, commerce: Any, *, domain_hub: Any|None=None) -> None:
        if commerce.runtime is not runtime: raise ValidationError("combat and commerce must share LivingRuntime")
        self.runtime=runtime; self.conn=runtime.conn; self.commerce=commerce; self.domain_hub=domain_hub
        with self.runtime._write_lock:
            self.conn.execute("INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('combat_schema_version',?)",(str(self.SCHEMA_VERSION),))

    def _world_action(self, world_instance_id: str, actor_ref: str, action_type: str, params: dict[str,Any], versions: dict[str,int], consequences: list[dict[str,Any]], idem: str) -> dict[str,Any]:
        w=self.runtime.get_world(world_instance_id); c=w["clock_state"]
        action={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":world_instance_id,"timeline_id":w["timeline_id"],"actor_ref":actor_ref,"action_type":action_type,"parameters":copy.deepcopy(params),"precondition_snapshot":{"entity_versions":copy.deepcopy(versions)},"idempotency_key":idem,"created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"ACTION","execution_class":"ACTIVE_ONLY"}
        return self.runtime.apply_action(world_instance_id,action,consequences)

    @staticmethod
    def _location_refs(e: dict[str,Any]) -> set[str]:
        d=e.get("data") or {}; eco=d.get("ecology") if isinstance(d.get("ecology"),dict) else {}
        refs={d.get("location_ref"),d.get("poi_ref"),d.get("site_ref"),d.get("biome_ref"),d.get("territory_ref"),eco.get("biome_ref"),eco.get("territory_ref")}
        return {x for x in refs if isinstance(x,str) and x}

    def ensure_combat_state(self, world_instance_id: str, entity_ref: str) -> dict[str,Any]:
        e=self.runtime.get_entity(world_instance_id,entity_ref)
        if e.get("lifecycle")!="ACTIVE": raise ConflictError("combatant is not active")
        if isinstance((e.get("data") or {}).get("combat"),dict): return e
        policy=COMBAT_PROFILE_POLICY.get(e.get("entity_kind"))
        if not policy: raise ValidationError("entity kind has no runtime combat profile")
        combat={"health":policy["max_health"],"max_health":policy["max_health"],"defense":policy["defense"],"evasion":policy["evasion"],"runtime_balance_policy":"COMBAT_PROFILE_V1_1_NOT_CANON"}
        w=self.runtime.get_world(world_instance_id);c=w["clock_state"]
        action={"action_id":new_runtime_id("action"),"intent_id":new_runtime_id("intent"),"world_instance_id":world_instance_id,"timeline_id":w["timeline_id"],"actor_ref":"SYSTEM_RECONCILIATION","action_type":"COMBAT_PROFILE_INITIALIZED","parameters":{"entity_ref":entity_ref},"precondition_snapshot":{"entity_versions":{entity_ref:e["version"]}},"idempotency_key":f"combat-profile:{entity_ref}","created_at":clock_point(c["day"],c["tick"]),"status":"SCHEDULED","source":"SYSTEM_RECONCILIATION","execution_class":"ROUTINE_SAFE"}
        self.runtime.apply_action(world_instance_id,action,[{"target_ref":entity_ref,"operation":"SET","field_path":"data.combat","value":combat,"priority":0,"kind":"DIRECT"}])
        return self.runtime.get_entity(world_instance_id,entity_ref)

    def equipped_weapon(self, world_instance_id: str, owner_ref: str) -> dict[str,Any]|None:
        matches=[]
        for e in self.runtime.list_entities(world_instance_id):
            if e.get("entity_kind")=="EQUIPMENT_INSTANCE" and e.get("lifecycle")=="ACTIVE" and (e.get("data") or {}).get("owner_ref")==owner_ref and (e.get("data") or {}).get("equipped") is True:
                matches.append(e)
        if len(matches)>1: raise IntegrityError("owner has multiple active equipped weapons")
        return matches[0] if matches else None

    def equip_weapon(self, world_instance_id: str, owner_ref: str, item_ref: str) -> dict[str,Any]:
        owner=self.runtime.get_entity(world_instance_id,owner_ref)
        if owner.get("lifecycle")!="ACTIVE": raise ConflictError("owner is not active")
        existing=self.equipped_weapon(world_instance_id,owner_ref)
        if existing:
            if existing["data"]["item_ref"]==item_ref: return {"status":"PASS","idempotent_replay":True,"equipment":existing}
            raise ConflictError("owner already has active equipped weapon")
        account=self.commerce.account_state(world_instance_id,owner_ref); inv=self.runtime.get_entity(world_instance_id,account["inventory_runtime_id"])
        if int(inv["data"]["items"].get(item_ref,0))<1: raise ConflictError("weapon not owned in inventory")
        item=self.commerce.catalog_item(item_ref); perf=item.get("performance") or {}; durability=float(perf.get("durability",5))
        w=self.runtime.get_world(world_instance_id);c=w["clock_state"]; eqid=new_runtime_id("equipment")
        state={"state_id":new_runtime_id("state"),"world_instance_id":world_instance_id,"timeline_id":w["timeline_id"],"entity_runtime_id":eqid,"origin":"RUNTIME_BORN","entity_kind":"EQUIPMENT_INSTANCE","lifecycle":"ACTIVE","version":0,"updated_at":clock_point(c["day"],c["tick"]),"data":{"owner_ref":owner_ref,"item_ref":item_ref,"item_name":item.get("name"),"equipped":True,"condition":100.0,"functional":True,"durability_rating":durability,"maintenance_location_ref":((item.get("supply") or {}).get("maintenance_location_id")),"balance_authority":"RUNTIME_ONLY_NOT_CANON"}}
        cons=[{"target_ref":inv["entity_runtime_id"],"operation":"DECREMENT","field_path":f"data.items.{item_ref}","amount":1,"priority":0,"kind":"DIRECT"},{"target_ref":eqid,"operation":"SPAWN","entity":state,"priority":1,"kind":"DIRECT"}]
        r=self._world_action(world_instance_id,owner_ref,"EQUIPMENT_EQUIPPED",{"item_ref":item_ref,"equipment_ref":eqid}, {owner_ref:owner["version"],inv["entity_runtime_id"]:inv["version"]},cons,f"equip:{owner_ref}:{item_ref}:{inv['version']}")
        return {"status":"PASS","event_id":r["event_id"],"idempotent_replay":False,"equipment":self.runtime.get_entity(world_instance_id,eqid)}

    def unequip_weapon(self, world_instance_id: str, owner_ref: str) -> dict[str,Any]:
        eq=self.equipped_weapon(world_instance_id,owner_ref)
        if not eq: raise NotFoundError("no equipped weapon")
        account=self.commerce.account_state(world_instance_id,owner_ref); inv=self.runtime.get_entity(world_instance_id,account["inventory_runtime_id"]); item=eq["data"]["item_ref"]
        cons=[{"target_ref":inv["entity_runtime_id"],"operation":"INCREMENT","field_path":f"data.items.{item}","amount":1,"priority":0,"kind":"DIRECT"},{"target_ref":eq["entity_runtime_id"],"operation":"SET","field_path":"data.equipped","value":False,"priority":1,"kind":"DIRECT"},{"target_ref":eq["entity_runtime_id"],"operation":"TRANSITION","field_path":"lifecycle","from":"ACTIVE","value":"RETURNED","priority":2,"kind":"DIRECT"}]
        r=self._world_action(world_instance_id,owner_ref,"EQUIPMENT_UNEQUIPPED",{"item_ref":item,"equipment_ref":eq["entity_runtime_id"]},{inv["entity_runtime_id"]:inv["version"],eq["entity_runtime_id"]:eq["version"]},cons,f"unequip:{eq['entity_runtime_id']}:{eq['version']}")
        return {"status":"PASS","event_id":r["event_id"]}

    @staticmethod
    def _stable_roll_identity(entity: dict[str,Any]) -> str:
        """Logical identity for deterministic combat RNG.

        Runtime UUIDs are intentionally excluded: two executions of the same seeded logical
        scenario must produce the same combat sequence even when fresh UUIDs are allocated.
        Event ordinal + entity versions still distinguish sequential attacks in one world.
        """
        data=entity.get("data") or {}
        parts=[str(entity.get("entity_kind") or "UNKNOWN")]
        for key in ("country_npc_id","country_fauna_id","canon_ref","species_ref","name","item_ref","location_ref","territory_ref","biome_ref"):
            value=data.get(key)
            if value is not None and value!="": parts.append(f"{key}={value}")
        if len(parts)==1:
            parts.append(f"origin={entity.get('origin','UNKNOWN')}")
        return "|".join(parts)

    def _roll(self, world_instance_id: str, actor: dict[str,Any], target: dict[str,Any], equipment: dict[str,Any]) -> int:
        w=self.runtime.get_world(world_instance_id)
        event_ordinal=self.runtime.event_count(world_instance_id)
        actor_key=self._stable_roll_identity(actor)
        target_key=self._stable_roll_identity(target)
        weapon_key=str((equipment.get("data") or {}).get("item_ref") or "NO_WEAPON_REF")
        key=f"{w['seed']}|event={event_ordinal}|actor={actor_key}|target={target_key}|weapon={weapon_key}|av={actor['version']}|tv={target['version']}|ev={equipment['version']}"
        return int(hashlib.sha256(key.encode()).hexdigest()[:8],16)%100+1

    def attack(self, world_instance_id: str, attacker_ref: str, target_ref: str) -> dict[str,Any]:
        attacker=self.ensure_combat_state(world_instance_id,attacker_ref); target=self.ensure_combat_state(world_instance_id,target_ref); equipment=self.equipped_weapon(world_instance_id,attacker_ref)
        attacker_travel=(attacker.get("data") or {}).get("travel") if isinstance((attacker.get("data") or {}).get("travel"),dict) else {}
        target_travel=(target.get("data") or {}).get("travel") if isinstance((target.get("data") or {}).get("travel"),dict) else {}
        if attacker_travel.get("status")=="IN_TRANSIT" or target_travel.get("status")=="IN_TRANSIT": raise ConflictError("combat cannot start while a combatant is in transit")
        if not equipment: raise ConflictError("no equipped weapon")
        if not bool(equipment["data"].get("functional",True)) or float(equipment["data"].get("condition",0))<=0: raise ConflictError("equipped weapon is not functional")
        shared=self._location_refs(attacker)&self._location_refs(target)
        if not shared: raise ConflictError("combatants are not co-located")
        item=self.commerce.catalog_item(equipment["data"]["item_ref"]); perf=item.get("performance") or {}
        control=float(perf.get("control",5)); stability=float(perf.get("stability",5)); mobility=float(perf.get("mobility",5))
        defense=float(target["data"]["combat"]["defense"]); evasion=float(target["data"]["combat"]["evasion"])
        chance=_clamp(75.0+control*3.0+stability-evasion*2.0,25.0,98.0); roll=self._roll(world_instance_id,attacker,target,equipment); hit=roll<=chance
        raw=5.0+control*1.5+stability+mobility*0.5; damage=round(max(1.0,raw-defense*0.8),2) if hit else 0.0
        health_before=float(target["data"]["combat"]["health"]); lethal=hit and damage>=health_before
        protection=target.get("protection") if isinstance(target.get("protection"),dict) else {}
        death_blocked=lethal and protection.get("death") in {"BLOCKED","STORY_AUTHORITY_ONLY"}
        if death_blocked:
            lethal=False; damage=max(0.0,health_before-1.0)
        health_after=round(max(0.0,health_before-damage),2)
        durability=float(equipment["data"].get("durability_rating",5)); wear=round(max(0.5,(8.0-durability)*0.5+0.5),2); wear=min(wear,float(equipment["data"]["condition"])); condition_after=round(max(0.0,float(equipment["data"]["condition"])-wear),2)
        cons=[]; pri=0
        if hit:
            cons.append({"target_ref":target_ref,"operation":"SET","field_path":"data.combat.health","value":health_after,"priority":pri,"kind":"DIRECT"});pri+=1
        cons.append({"target_ref":equipment["entity_runtime_id"],"operation":"SET","field_path":"data.condition","value":condition_after,"priority":pri,"kind":"DIRECT"});pri+=1
        if condition_after<=0:
            cons.append({"target_ref":equipment["entity_runtime_id"],"operation":"SET","field_path":"data.functional","value":False,"priority":pri,"kind":"DIRECT"});pri+=1
        corpse_id=None
        if lethal:
            cons.append({"target_ref":target_ref,"operation":"TRANSITION","field_path":"lifecycle","from":"ACTIVE","value":"DEAD","priority":pri,"kind":"DIRECT"});pri+=1
            corpse_id=new_runtime_id("corpse"); w=self.runtime.get_world(world_instance_id);c=w["clock_state"]; td=target.get("data") or {}; eco=td.get("ecology") if isinstance(td.get("ecology"),dict) else {}
            corpse={"state_id":new_runtime_id("state"),"world_instance_id":world_instance_id,"timeline_id":w["timeline_id"],"entity_runtime_id":corpse_id,"origin":"RUNTIME_BORN","entity_kind":"CORPSE","lifecycle":"ACTIVE","version":0,"updated_at":clock_point(c["day"],c["tick"]),"data":{"source_entity_ref":target_ref,"source_entity_kind":target.get("entity_kind"),"species_ref":td.get("species_ref"),"location_ref":next(iter(shared)),"territory_ref":eco.get("territory_ref") or td.get("territory_ref"),"biome_ref":eco.get("biome_ref") or td.get("biome_ref"),"harvested":False,"harvestable":target.get("entity_kind") in YIELD_POLICY,"yield_policy":"BIO_RESOURCE_V1_1_NOT_CANON"}}
            cons.append({"target_ref":corpse_id,"operation":"SPAWN","entity":corpse,"priority":pri,"kind":"DERIVED"});pri+=1
        params={"target_ref":target_ref,"equipment_ref":equipment["entity_runtime_id"],"weapon_ref":equipment["data"]["item_ref"],"hit_chance":round(chance,2),"roll":roll,"hit":hit,"damage":damage,"health_before":health_before,"health_after":health_after,"lethal":lethal,"death_blocked_by_protection":death_blocked,"condition_before":equipment["data"]["condition"],"condition_after":condition_after,"corpse_ref":corpse_id,"balance_authority":"RUNTIME_ONLY_NOT_CANON"}
        result=self._world_action(world_instance_id,attacker_ref,"COMBAT_RESOLVED",params,{attacker_ref:attacker["version"],target_ref:target["version"],equipment["entity_runtime_id"]:equipment["version"]},cons,f"combat:{attacker_ref}:{target_ref}:{equipment['version']}:{target['version']}")
        integration=None
        if self.domain_hub is not None: integration=self.domain_hub.drain_pending(world_instance_id)
        return {"status":"PASS","event_id":result["event_id"],**params,"integration":integration}

    def repair_equipment(self, world_instance_id: str, owner_ref: str, equipment_ref: str, *, target_condition: float=100.0) -> dict[str,Any]:
        """Repair an owned MAR equipment instance at its canonical maintenance location.

        The maintenance location/job come from the Master snapshot. Numeric service cost is a
        Living runtime policy derived from relative cost, missing condition and current market
        pressure; it is never written back to canon.
        """
        equipment=self.runtime.get_entity(world_instance_id,equipment_ref); owner=self.runtime.get_entity(world_instance_id,owner_ref)
        if equipment.get("entity_kind")!="EQUIPMENT_INSTANCE" or equipment.get("lifecycle")!="ACTIVE": raise ConflictError("equipment is not active")
        if equipment.get("data",{}).get("owner_ref")!=owner_ref: raise ConflictError("equipment is not owned by requester")
        item=self.commerce.catalog_item(equipment["data"].get("item_ref")); supply=item.get("supply") or {}; maintenance_location=supply.get("maintenance_location_id"); maintenance_job=supply.get("maintenance_job_id")
        if not isinstance(maintenance_location,str) or not maintenance_location: raise ConflictError("equipment has no canonical maintenance location")
        if (owner.get("data") or {}).get("location_ref")!=maintenance_location: raise ConflictError("owner is not at canonical maintenance location")
        current=float(equipment["data"].get("condition",0.0)); target=float(target_condition)
        if not math.isfinite(target) or target<=0 or target>100: raise ValidationError("target_condition must be >0 and <=100")
        if current>=target:
            return {"status":"PASS","idempotent_replay":True,"event_id":None,"equipment":equipment,"cost":0.0,"currency":"CREDIT_RUNTIME","authority":"RUNTIME_MAINTENANCE_NOT_CANON"}
        relative=str((item.get("performance") or {}).get("relative_cost","")).upper(); base=RELATIVE_PRICE_BASE.get(relative)
        if base is None: raise ConflictError(f"relative cost has no runtime maintenance policy: {relative}")
        market=self.commerce._market_factors(world_instance_id,maintenance_location,item); missing_fraction=(target-current)/100.0; service_factor=0.35
        cost=round(max(1.0,base*missing_fraction*service_factor*float(market["scarcity_factor"])*float(market["logistics_factor"])*float(market["demand_factor"])),2)
        account=self.commerce.create_account(world_instance_id,owner_ref); wallet=self.runtime.get_entity(world_instance_id,account["wallet_runtime_id"]); vendor_result=self.commerce.create_vendor(world_instance_id,maintenance_location,name=f"Maintenance@{maintenance_location}",stock_seed=0,starting_cash=0.0); vendor=vendor_result["vendor"]
        if float(wallet["data"].get("balance",0.0))<cost: raise ConflictError("insufficient funds for maintenance")
        params={"equipment_ref":equipment_ref,"item_ref":equipment["data"].get("item_ref"),"condition_before":round(current,4),"condition_after":round(target,4),"maintenance_location_ref":maintenance_location,"maintenance_job_ref":maintenance_job,"relative_cost":relative,"cost":cost,"currency":wallet["data"].get("currency","CREDIT_RUNTIME"),"factors":{"relative_band_base":base,"missing_fraction":round(missing_fraction,6),"service_factor":service_factor,"scarcity_factor":market["scarcity_factor"],"logistics_factor":market["logistics_factor"],"demand_factor":market["demand_factor"]},"numeric_cost_authority":"RUNTIME_ONLY_NOT_CANON","maintenance_source_authority":"MASTER_READ_ONLY"}
        cons=[{"target_ref":wallet["entity_runtime_id"],"operation":"DECREMENT","field_path":"data.balance","amount":cost,"priority":0,"kind":"DIRECT"},{"target_ref":vendor["entity_runtime_id"],"operation":"INCREMENT","field_path":"data.cash_balance","amount":cost,"priority":1,"kind":"DIRECT"},{"target_ref":equipment_ref,"operation":"SET","field_path":"data.condition","value":round(target,4),"priority":2,"kind":"DIRECT"},{"target_ref":equipment_ref,"operation":"SET","field_path":"data.functional","value":True,"priority":3,"kind":"DIRECT"},{"target_ref":equipment_ref,"operation":"SET","field_path":"data.last_maintenance","value":{"location_ref":maintenance_location,"maintenance_job_ref":maintenance_job,"cost":cost,"runtime_only":True},"priority":4,"kind":"DIRECT"}]
        result=self._world_action(world_instance_id,owner_ref,"EQUIPMENT_REPAIRED",params,{equipment_ref:equipment["version"],wallet["entity_runtime_id"]:wallet["version"],vendor["entity_runtime_id"]:vendor["version"]},cons,f"repair:{equipment_ref}:{equipment['version']}:{round(target,4)}")
        return {"status":"PASS","idempotent_replay":False,"event_id":result["event_id"],"cost":cost,"currency":params["currency"],"equipment":self.runtime.get_entity(world_instance_id,equipment_ref),"vendor":self.runtime.get_entity(world_instance_id,vendor["entity_runtime_id"]),"quote_basis":params}

    def harvest_corpse(self, world_instance_id: str, harvester_ref: str, corpse_ref: str) -> dict[str,Any]:
        harvester=self.runtime.get_entity(world_instance_id,harvester_ref); corpse=self.runtime.get_entity(world_instance_id,corpse_ref)
        if corpse.get("entity_kind")!="CORPSE" or corpse.get("lifecycle")!="ACTIVE": raise ConflictError("corpse not available")
        if not corpse["data"].get("harvestable") or corpse["data"].get("harvested"): raise ConflictError("corpse is not harvestable")
        if corpse["data"].get("location_ref") not in self._location_refs(harvester): raise ConflictError("harvester is not co-located with corpse")
        source_kind=corpse["data"].get("source_entity_kind"); quantity=float(YIELD_POLICY.get(source_kind,0.0))
        if quantity<=0: raise ConflictError("no runtime yield policy for corpse")
        w=self.runtime.get_world(world_instance_id);c=w["clock_state"]; rid=new_runtime_id("resource")
        resource={"state_id":new_runtime_id("state"),"world_instance_id":world_instance_id,"timeline_id":w["timeline_id"],"entity_runtime_id":rid,"origin":"RUNTIME_BORN","entity_kind":"RESOURCE_BUNDLE","lifecycle":"ACTIVE","version":0,"updated_at":clock_point(c["day"],c["tick"]),"data":{"resource_type":"BIOLOGICAL_MATERIAL","quantity":quantity,"owner_ref":harvester_ref,"source_corpse_ref":corpse_ref,"species_ref":corpse["data"].get("species_ref"),"location_ref":corpse["data"].get("location_ref"),"territory_ref":corpse["data"].get("territory_ref"),"yield_authority":"RUNTIME_BALANCE_V1_1_NOT_CANON"}}
        cons=[{"target_ref":corpse_ref,"operation":"SET","field_path":"data.harvested","value":True,"priority":0,"kind":"DIRECT"},{"target_ref":corpse_ref,"operation":"TRANSITION","field_path":"lifecycle","from":"ACTIVE","value":"HARVESTED","priority":1,"kind":"DIRECT"},{"target_ref":rid,"operation":"SPAWN","entity":resource,"priority":2,"kind":"DERIVED"}]
        r=self._world_action(world_instance_id,harvester_ref,"CORPSE_HARVESTED",{"corpse_ref":corpse_ref,"resource_ref":rid,"resource_type":"BIOLOGICAL_MATERIAL","quantity":quantity,"yield_authority":"RUNTIME_BALANCE_V1_1_NOT_CANON"},{harvester_ref:harvester["version"],corpse_ref:corpse["version"]},cons,f"harvest:{corpse_ref}")
        return {"status":"PASS","event_id":r["event_id"],"resource":self.runtime.get_entity(world_instance_id,rid)}

    def full_integrity_check(self, world_instance_id: str) -> dict[str,Any]:
        failures=[]; equipment=0; corpses=0; resources=0
        for e in self.runtime.list_entities(world_instance_id):
            if e.get("entity_kind")=="EQUIPMENT_INSTANCE":
                equipment+=1; d=e.get("data") or {}; cond=d.get("condition")
                if not isinstance(cond,(int,float)) or isinstance(cond,bool) or not 0<=float(cond)<=100: failures.append(f"EQUIPMENT_CONDITION:{e['entity_runtime_id']}")
                try:self.commerce.catalog_item(d.get("item_ref"))
                except Exception:failures.append(f"EQUIPMENT_ITEM_REF:{e['entity_runtime_id']}")
            elif e.get("entity_kind")=="CORPSE": corpses+=1
            elif e.get("entity_kind")=="RESOURCE_BUNDLE": resources+=1
            combat=(e.get("data") or {}).get("combat")
            if isinstance(combat,dict):
                h=float(combat.get("health",-1)); mh=float(combat.get("max_health",-1))
                if h<0 or mh<=0 or h>mh: failures.append(f"COMBAT_HEALTH:{e['entity_runtime_id']}")
        replay=self.runtime.compare_replay_to_materialized(world_instance_id)
        if replay["status"]!="PASS": failures.append("REPLAY_MISMATCH")
        return {"status":"PASS" if not failures else "FAIL","failures":failures,"equipment":equipment,"corpses":corpses,"resources":resources,"replay":replay}
