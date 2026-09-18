from __future__ import annotations

import math
from typing import Any

from living_runtime import LivingRuntime, ValidationError

RUNTIME_AUTHORITY = "SYSTEM_HEALTH_V1_1_RUNTIME_DIAGNOSTIC"


class SystemHealthMonitor:
    """Read-only cross-domain health diagnostics for Living V1.1.

    The monitor never repairs state and never promotes runtime values to canon. It turns
    silent cross-system drift into explicit failures/warnings that release and long-horizon
    validation can gate on.
    """

    def __init__(self, runtime: LivingRuntime, *, world_systems: Any, orchestrator: Any,
                 ecology: Any, social: Any, objects: Any, consequence_engine: Any,
                 domain_hub: Any, commerce: Any, combat: Any, mobility: Any, society: Any) -> None:
        deps=(world_systems,orchestrator,ecology,social,objects,consequence_engine,domain_hub,commerce,combat,mobility,society)
        if any(getattr(x,"runtime",None) is not runtime for x in deps):
            raise ValidationError("health-monitor dependencies must share LivingRuntime")
        self.runtime=runtime; self.conn=runtime.conn
        self.world_systems=world_systems; self.orchestrator=orchestrator; self.ecology=ecology
        self.social=social; self.objects=objects; self.consequence_engine=consequence_engine
        self.domain_hub=domain_hub; self.commerce=commerce; self.combat=combat
        self.mobility=mobility; self.society=society

    @staticmethod
    def _finite(v: Any) -> bool:
        try:return math.isfinite(float(v))
        except Exception:return False

    def snapshot(self, world_instance_id: str) -> dict[str,Any]:
        self.runtime.get_world(world_instance_id)
        failures:list[str]=[];warnings:list[str]=[];metrics:dict[str,Any]={}

        checks={
            "runtime": self.runtime.full_integrity_check,
            "world_systems": self.world_systems.full_integrity_check,
            "orchestrator": self.orchestrator.full_integrity_check,
            "ecology": self.ecology.full_integrity_check,
            "social": self.social.full_integrity_check,
            "objects": self.objects.full_integrity_check,
            "consequences": self.consequence_engine.full_integrity_check,
            "domain_integration": self.domain_hub.full_integrity_check,
            "commerce": self.commerce.full_integrity_check,
            "combat": self.combat.full_integrity_check,
            "mobility": self.mobility.full_integrity_check,
            "society": self.society.full_integrity_check,
        }
        integrity={}
        for name,fn in checks.items():
            try:r=fn(world_instance_id); st=r.get("status","UNKNOWN") if isinstance(r,dict) else "UNKNOWN"
            except Exception as exc:r={"status":"ERROR","error":f"{type(exc).__name__}: {exc}"};st="ERROR"
            integrity[name]=r
            if st!="PASS":failures.append(f"INTEGRITY:{name}:{st}")

        pops=self.world_systems._entities(world_instance_id,"POPULATION_AGGREGATE")
        pop_total=0
        for p in pops:
            d=p["data"];count=int(d.get("count",0));labor=int(d.get("labor_force",0));emp=int(d.get("employed",0));unemp=int(d.get("unemployed",0));pop_total+=count
            if count<0 or labor<0 or emp<0 or unemp<0:failures.append(f"POP_NEGATIVE:{d.get('settlement_ref')}")
            if labor>count or emp+unemp!=labor:failures.append(f"POP_LABOR_INVARIANT:{d.get('settlement_ref')}")
            for k in ("food_security","welfare_index"):
                if not self._finite(d.get(k)) or not 0<=float(d[k])<=100:failures.append(f"POP_BOUND:{d.get('settlement_ref')}:{k}")
        metrics["human_population"]={"settlements":len(pops),"total":pop_total}

        flows=self.world_systems._entities(world_instance_id,"ECONOMIC_FLOW")
        prices=[];shortages=[]
        for f in flows:
            d=f["data"];ref=d.get("flow_ref")
            if not self._finite(d.get("stock")) or float(d["stock"])<0:failures.append(f"ECON_STOCK:{ref}")
            if not self._finite(d.get("price")) or float(d["price"])<=0:failures.append(f"ECON_PRICE:{ref}")
            if not self._finite(d.get("shortage_pressure")) or not 0<=float(d["shortage_pressure"])<=100:failures.append(f"ECON_SHORTAGE:{ref}")
            if self._finite(d.get("price")):prices.append(float(d["price"]))
            if self._finite(d.get("shortage_pressure")):shortages.append(float(d["shortage_pressure"]))
        metrics["economy"]={"flows":len(flows),"mean_price":round(sum(prices)/len(prices),4) if prices else None,"mean_shortage":round(sum(shortages)/len(shortages),4) if shortages else None}

        factions=self.world_systems._entities(world_instance_id,"FACTION_RUNTIME")
        for f in factions:
            d=f["data"];ref=d.get("faction_ref")
            for k in ("influence","security","stability"):
                if not self._finite(d.get(k)) or not 0<=float(d[k])<=100:failures.append(f"FACTION_BOUND:{ref}:{k}")
            if not self._finite(d.get("treasury")) or float(d["treasury"])<0:failures.append(f"FACTION_TREASURY:{ref}")
            if d.get("influence_not_sovereignty") is not True:failures.append(f"FACTION_SOVEREIGNTY_GUARD:{ref}")
        metrics["factions"]={"count":len(factions)}

        eco_rows=self.conn.execute("SELECT species_ref,territory_ref,count,carrying_capacity FROM ecology_populations_current WHERE world_instance_id=?",(world_instance_id,)).fetchall()
        eco_total=0
        for r in eco_rows:
            eco_total+=int(r["count"])
            if int(r["count"])<0 or int(r["carrying_capacity"])<=0:failures.append(f"ECO_POP:{r['species_ref']}:{r['territory_ref']}")
            if int(r["count"])>int(r["carrying_capacity"])*2:warnings.append(f"ECO_OVERSHOOT:{r['species_ref']}:{r['territory_ref']}")
        metrics["ecology"]={"aggregates":len(eco_rows),"total":eco_total}

        dead_enabled=self.conn.execute("""
          SELECT COUNT(*) c FROM orchestration_participants p
          JOIN entity_states e ON e.world_instance_id=p.world_instance_id AND e.entity_runtime_id=p.entity_ref
          WHERE p.world_instance_id=? AND p.enabled=1 AND e.state_json LIKE '%\"lifecycle\":\"DEAD\"%'
        """,(world_instance_id,)).fetchone()["c"]
        # state_json includes lifecycle at top-level and is hash-protected; this is a diagnostic shortcut.
        if dead_enabled:failures.append(f"SCHEDULER_DEAD_ENABLED:{dead_enabled}")
        metrics["scheduler"]={"dead_enabled":int(dead_enabled)}

        active_contracts=self.conn.execute("SELECT contract_id,worker_ref,employer_ref FROM employment_contracts WHERE world_instance_id=? AND status='ACTIVE'",(world_instance_id,)).fetchall()
        orphan_contracts=0
        for r in active_contracts:
            try:
                worker=self.runtime.get_entity(world_instance_id,r["worker_ref"]); employer=self.runtime.get_entity(world_instance_id,r["employer_ref"])
                if worker.get("lifecycle")!="ACTIVE" or employer.get("lifecycle")!="ACTIVE":orphan_contracts+=1;continue
                self.commerce.account_state(world_instance_id,r["worker_ref"])
            except Exception:orphan_contracts+=1
        if orphan_contracts:failures.append(f"LABOR_ORPHAN_ACTIVE_CONTRACT:{orphan_contracts}")
        metrics["labor"]={"active_contracts":len(active_contracts),"orphan_active_contracts":orphan_contracts}

        for table,label in (("domain_integration_queue","DOMAIN_QUEUE"),("mobility_event_queue","MOBILITY_QUEUE"),("society_event_queue","SOCIETY_QUEUE")):
            try:failed=self.conn.execute(f"SELECT COUNT(*) c FROM {table} WHERE world_instance_id=? AND status='FAILED'",(world_instance_id,)).fetchone()["c"]
            except Exception:failed=0
            if failed:failures.append(f"{label}_FAILED:{failed}")
            metrics.setdefault("queues",{})[label.lower()]=int(failed)

        status="PASS" if not failures else "FAIL"
        return {"status":status,"failures":sorted(set(failures)),"warnings":sorted(set(warnings)),"metrics":metrics,"integrity":integrity,"authority":RUNTIME_AUTHORITY}
