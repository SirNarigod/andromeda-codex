from __future__ import annotations

import copy
import json
import sqlite3
import threading
from typing import Any

from living_runtime import (
    LivingRuntime, ValidationError, IntegrityError, ConflictError, NotFoundError,
    OfflinePolicyError, canonical_json, sha256_text, new_runtime_id, clock_point,
)

OBJECT_CLASSES = {
    "DOOR", "CONTAINER", "WEAPON", "VEHICLE", "STRUCTURE", "MACHINE",
    "FLORA", "RESOURCE_NODE", "BRIDGE", "GENERIC_OBJECT",
}
MATERIAL_CLASSES = {"WOOD", "METAL", "STONE", "GLASS", "ORGANIC", "COMPOSITE", "LIQUID", "UNKNOWN"}
LINK_TYPES = {"ADJACENT", "CONTAINED_BY", "SUPPORTED_BY", "CONNECTED_TO", "ENVIRONMENT_MEMBER"}
INTERACTIONS = {
    "OPEN", "CLOSE", "LOCK", "UNLOCK", "ACTIVATE", "DEACTIVATE",
    "DAMAGE", "REPAIR", "IGNITE", "EXTINGUISH", "HEAT", "COOL",
    "SOAK", "DRY", "HARVEST", "CUT",
}
SYSTEM_ACTORS = {"SYSTEM_ROUTINE", "SYSTEM_RECOVERY", "SYSTEM_RECONCILIATION"}


def _bounded_number(value: Any, lo: float, hi: float, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValidationError(f"{name} must be numeric")
    value = float(value)
    if value < lo or value > hi:
        raise ValidationError(f"{name} outside [{lo},{hi}]")
    return value


class ObjectEnvironmentSystem:
    """Reactive non-agent system. Objects have state machines; they never form intents or use LLMs."""

    PROFILE_AUTHORITY = "RUNTIME_REACTIVE_PROFILE_NOT_CANON"
    LINK_AUTHORITY = "RUNTIME_SPATIAL_REACTION_LINK_NOT_CANON"
    MAX_PROPAGATION_DEPTH = 4
    DEFAULT_PROPAGATION_BUDGET = 32

    def __init__(self, runtime: LivingRuntime) -> None:
        self.runtime = runtime
        self.conn = runtime.conn
        self._lock = threading.RLock()
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self.runtime._write_lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS reactive_profiles(
                    world_instance_id TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    object_class TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    profile_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id,profile_id)
                );
                CREATE TABLE IF NOT EXISTS environment_links(
                    link_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    target_ref TEXT NOT NULL,
                    link_type TEXT NOT NULL,
                    conductance REAL NOT NULL,
                    active INTEGER NOT NULL CHECK(active IN (0,1)),
                    link_json TEXT NOT NULL,
                    link_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id,source_ref,target_ref,link_type)
                );
                CREATE TABLE IF NOT EXISTS reaction_logs(
                    reaction_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    target_ref TEXT NOT NULL,
                    reaction_type TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    record_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS environment_ticks(
                    world_instance_id TEXT NOT NULL,
                    tick_key TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    result_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id,tick_key)
                );
                CREATE TABLE IF NOT EXISTS propagation_runs_env(
                    world_instance_id TEXT NOT NULL,
                    propagation_key TEXT NOT NULL,
                    root_ref TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    result_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id,propagation_key)
                );
                """
            )
            # Immutable audit records.
            self.conn.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS reaction_logs_no_update BEFORE UPDATE ON reaction_logs BEGIN SELECT RAISE(ABORT,'reaction logs immutable'); END;
                CREATE TRIGGER IF NOT EXISTS reaction_logs_no_delete BEFORE DELETE ON reaction_logs BEGIN SELECT RAISE(ABORT,'reaction logs immutable'); END;
                """
            )

    def _world(self, world_instance_id: str) -> dict[str, Any]:
        return self.runtime.get_world(world_instance_id)

    def _assert_canonical(self, ref: str | None) -> None:
        if ref is not None and not self.runtime.canonical_ref_resolves(ref):
            raise ValidationError(f"unknown canonical_ref: {ref}")

    def register_profile(self, world_instance_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        self._world(world_instance_id)
        p = copy.deepcopy(profile)
        p.setdefault("profile_id", new_runtime_id("reactiveprofile"))
        p.setdefault("authority", self.PROFILE_AUTHORITY)
        if p.get("authority") != self.PROFILE_AUTHORITY:
            raise ValidationError("reactive profile authority must remain runtime-only")
        if p.get("object_class") not in OBJECT_CLASSES:
            raise ValidationError("invalid object_class")
        if p.get("material_class", "UNKNOWN") not in MATERIAL_CLASSES:
            raise ValidationError("invalid material_class")
        p["material_class"] = p.get("material_class", "UNKNOWN")
        p["flammable"] = bool(p.get("flammable", False))
        p["supports_open"] = bool(p.get("supports_open", False))
        p["supports_lock"] = bool(p.get("supports_lock", False))
        p["supports_activation"] = bool(p.get("supports_activation", False))
        p["harvestable"] = bool(p.get("harvestable", False))
        p["base_integrity"] = int(_bounded_number(p.get("base_integrity", 100), 1, 100, "base_integrity"))
        p["ignition_temperature"] = _bounded_number(p.get("ignition_temperature", 300), -200, 5000, "ignition_temperature")
        p["ignition_wetness_max"] = _bounded_number(p.get("ignition_wetness_max", 35), 0, 100, "ignition_wetness_max")
        p["heat_resistance"] = _bounded_number(p.get("heat_resistance", 0), 0, 1, "heat_resistance")
        p["water_absorption"] = _bounded_number(p.get("water_absorption", 0.5), 0, 1, "water_absorption")
        p["damage_multiplier"] = _bounded_number(p.get("damage_multiplier", 1), 0, 10, "damage_multiplier")
        p["recovery_policy"] = p.get("recovery_policy", "REGENERATE_7_UNIVERSE_DAYS")
        if p["recovery_policy"] != "REGENERATE_7_UNIVERSE_DAYS":
            raise ValidationError("authorial recovery policy must be 7 universe days")
        body = canonical_json(p)
        with self._lock, self.runtime._write_lock:
            self.conn.execute(
                "INSERT INTO reactive_profiles VALUES(?,?,?,?,?)",
                (world_instance_id, p["profile_id"], p["object_class"], body, sha256_text(body)),
            )
        return p

    def get_profile(self, world_instance_id: str, profile_id: str) -> dict[str, Any]:
        with self.runtime._write_lock:
            row = self.conn.execute(
                "SELECT profile_json,profile_hash FROM reactive_profiles WHERE world_instance_id=? AND profile_id=?",
                (world_instance_id, profile_id),
            ).fetchone()
        if not row:
            raise NotFoundError("reactive profile not found")
        if sha256_text(row["profile_json"]) != row["profile_hash"]:
            raise IntegrityError("reactive profile hash mismatch")
        return json.loads(row["profile_json"])

    def spawn_object(
        self, world_instance_id: str, *, profile_id: str, canonical_ref: str | None = None,
        zone_ref: str | None = None, entity_kind: str | None = None, data: dict[str, Any] | None = None,
        protection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        world = self._world(world_instance_id)
        profile = self.get_profile(world_instance_id, profile_id)
        self._assert_canonical(canonical_ref)
        if zone_ref is not None:
            zone = self.runtime.get_entity(world_instance_id, zone_ref)
            if zone.get("entity_kind") != "ENVIRONMENT_ZONE":
                raise ValidationError("zone_ref must reference ENVIRONMENT_ZONE")
        kind = entity_kind or {
            "STRUCTURE": "STRUCTURE", "BRIDGE": "STRUCTURE", "FLORA": "FLORA_INSTANCE", "RESOURCE_NODE": "RESOURCE_NODE"
        }.get(profile["object_class"], "OBJECT")
        if kind not in {"OBJECT", "STRUCTURE", "FLORA_INSTANCE", "RESOURCE_NODE"}:
            raise ValidationError("invalid reactive entity_kind")
        d = {
            "reactive_profile_id": profile_id,
            "object_class": profile["object_class"],
            "material_class": profile["material_class"],
            "integrity": profile["base_integrity"],
            "functional": True,
            "open": False,
            "locked": False,
            "active": False,
            "temperature": 20.0,
            "wetness": 0.0,
            "burning": False,
            "fire_intensity": 0.0,
            "resource_quantity": 0.0,
            "zone_ref": zone_ref,
        }
        if data:
            d.update(copy.deepcopy(data))
        self._validate_object_data(profile, d)
        now = world["clock_state"]
        state = {
            "state_id": new_runtime_id("state"),
            "world_instance_id": world_instance_id,
            "timeline_id": world["timeline_id"],
            "entity_runtime_id": new_runtime_id("object" if kind == "OBJECT" else kind.lower()),
            "origin": "CANONICAL_BACKED" if canonical_ref else "RUNTIME_BORN",
            "canonical_ref": canonical_ref,
            "entity_kind": kind,
            "lifecycle": "ACTIVE",
            "version": 0,
            "updated_at": clock_point(now["day"], now["tick"]),
            "data": d,
            "protection": copy.deepcopy(protection or {}),
        }
        return self.runtime.register_entity(world_instance_id, state)

    def create_environment_zone(
        self, world_instance_id: str, *, canonical_ref: str | None = None, temperature: float = 20,
        humidity: float = 50, fire_intensity: float = 0, smoke: float = 0, water_level: float = 0,
        contamination: float = 0,
    ) -> dict[str, Any]:
        world = self._world(world_instance_id)
        self._assert_canonical(canonical_ref)
        d = {
            "temperature": _bounded_number(temperature, -200, 5000, "temperature"),
            "humidity": _bounded_number(humidity, 0, 100, "humidity"),
            "fire_intensity": _bounded_number(fire_intensity, 0, 100, "fire_intensity"),
            "smoke": _bounded_number(smoke, 0, 100, "smoke"),
            "water_level": _bounded_number(water_level, 0, 100, "water_level"),
            "contamination": _bounded_number(contamination, 0, 100, "contamination"),
        }
        now = world["clock_state"]
        state = {
            "state_id": new_runtime_id("state"), "world_instance_id": world_instance_id,
            "timeline_id": world["timeline_id"], "entity_runtime_id": new_runtime_id("envzone"),
            "origin": "CANONICAL_BACKED" if canonical_ref else "RUNTIME_BORN", "canonical_ref": canonical_ref,
            "entity_kind": "ENVIRONMENT_ZONE", "lifecycle": "ACTIVE", "version": 0,
            "updated_at": clock_point(now["day"], now["tick"]), "data": d, "protection": {},
        }
        return self.runtime.register_entity(world_instance_id, state)

    def _validate_object_data(self, profile: dict[str, Any], data: dict[str, Any]) -> None:
        _bounded_number(data.get("integrity", 100), 0, 100, "integrity")
        _bounded_number(data.get("temperature", 20), -200, 5000, "temperature")
        _bounded_number(data.get("wetness", 0), 0, 100, "wetness")
        _bounded_number(data.get("fire_intensity", 0), 0, 100, "fire_intensity")
        if float(data.get("resource_quantity", 0)) < 0:
            raise ValidationError("resource_quantity cannot be negative")
        if data.get("locked") and data.get("open"):
            raise ValidationError("object cannot bootstrap open and locked")
        if data.get("burning") and not profile["flammable"]:
            raise ValidationError("nonflammable object cannot bootstrap burning")

    def link(self, world_instance_id: str, source_ref: str, target_ref: str, *, link_type: str = "ADJACENT", conductance: float = 1.0) -> dict[str, Any]:
        self._world(world_instance_id)
        if source_ref == target_ref:
            raise ValidationError("self-link not allowed")
        self.runtime.get_entity(world_instance_id, source_ref)
        self.runtime.get_entity(world_instance_id, target_ref)
        if link_type not in LINK_TYPES:
            raise ValidationError("invalid environment link type")
        conductance = _bounded_number(conductance, 0, 1, "conductance")
        rec = {
            "link_id": new_runtime_id("envlink"), "world_instance_id": world_instance_id,
            "source_ref": source_ref, "target_ref": target_ref, "link_type": link_type,
            "conductance": conductance, "active": True, "authority": self.LINK_AUTHORITY,
        }
        body = canonical_json(rec)
        with self._lock, self.runtime._write_lock:
            self.conn.execute(
                "INSERT INTO environment_links VALUES(?,?,?,?,?,?,?,?,?)",
                (rec["link_id"], world_instance_id, source_ref, target_ref, link_type, conductance, 1, body, sha256_text(body)),
            )
        return rec

    def _profile_for_entity(self, world_instance_id: str, entity: dict[str, Any]) -> dict[str, Any]:
        pid = entity.get("data", {}).get("reactive_profile_id")
        if not pid:
            raise ValidationError("target is not a reactive object")
        return self.get_profile(world_instance_id, pid)

    def _action(self, world: dict[str, Any], actor_ref: str, action_type: str, target: dict[str, Any], parameters: dict[str, Any], *, execution_class: str = "ACTIVE_ONLY", source: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        now = world["clock_state"]
        return {
            "action_id": new_runtime_id("action"), "intent_id": new_runtime_id("intent"),
            "world_instance_id": world["world_instance_id"], "timeline_id": world["timeline_id"],
            "actor_ref": actor_ref, "action_type": action_type, "parameters": copy.deepcopy(parameters),
            "precondition_snapshot": {"entity_versions": {target["entity_runtime_id"]: target["version"]}},
            "idempotency_key": idempotency_key or f"obj:{new_runtime_id('idem')}",
            "created_at": clock_point(now["day"], now["tick"]), "status": "SCHEDULED",
            "execution_class": execution_class,
            **({"source": source} if source else {}),
        }

    def _set(self, target_ref: str, field: str, value: Any, priority: int = 0, kind: str = "DIRECT") -> dict[str, Any]:
        return {"target_ref": target_ref, "operation": "SET", "field_path": field, "value": value, "priority": priority, "kind": kind}

    def _log_reaction(self, world_instance_id: str, event_id: str, target_ref: str, reaction_type: str, details: dict[str, Any]) -> dict[str, Any]:
        rec = {
            "reaction_id": new_runtime_id("reaction"), "world_instance_id": world_instance_id,
            "event_id": event_id, "target_ref": target_ref, "reaction_type": reaction_type,
            "details": copy.deepcopy(details),
        }
        body = canonical_json(rec)
        with self.runtime._write_lock:
            self.conn.execute("INSERT INTO reaction_logs VALUES(?,?,?,?,?,?,?)", (rec["reaction_id"], world_instance_id, event_id, target_ref, reaction_type, body, sha256_text(body)))
        return rec

    def interact(
        self, world_instance_id: str, *, actor_ref: str, target_ref: str, interaction_type: str,
        amount: float | None = None, idempotency_key: str | None = None, routine_safe: bool = False,
    ) -> dict[str, Any]:
        if interaction_type not in INTERACTIONS:
            raise ValidationError("unsupported interaction_type")
        with self._lock:
            world = self._world(world_instance_id)
            target = self.runtime.get_entity(world_instance_id, target_ref)
            profile = self._profile_for_entity(world_instance_id, target)
            d = target["data"]
            if target.get("lifecycle") == "DESTROYED" and interaction_type not in {"REPAIR", "EXTINGUISH", "COOL", "SOAK"}:
                raise ConflictError("destroyed target rejects interaction")
            consequences: list[dict[str, Any]] = []
            reason = interaction_type
            if interaction_type == "OPEN":
                if not profile["supports_open"]: raise ValidationError("profile does not support OPEN")
                if d.get("locked"): raise ConflictError("locked object cannot open")
                consequences.append(self._set(target_ref, "data.open", True))
            elif interaction_type == "CLOSE":
                if not profile["supports_open"]: raise ValidationError("profile does not support CLOSE")
                consequences.append(self._set(target_ref, "data.open", False))
            elif interaction_type == "LOCK":
                if not profile["supports_lock"]: raise ValidationError("profile does not support LOCK")
                if d.get("open"): raise ConflictError("open object cannot lock")
                consequences.append(self._set(target_ref, "data.locked", True))
            elif interaction_type == "UNLOCK":
                if not profile["supports_lock"]: raise ValidationError("profile does not support UNLOCK")
                consequences.append(self._set(target_ref, "data.locked", False))
            elif interaction_type == "ACTIVATE":
                if not profile["supports_activation"]: raise ValidationError("profile does not support activation")
                if not d.get("functional", True): raise ConflictError("nonfunctional object cannot activate")
                consequences.append(self._set(target_ref, "data.active", True))
            elif interaction_type == "DEACTIVATE":
                if not profile["supports_activation"]: raise ValidationError("profile does not support activation")
                consequences.append(self._set(target_ref, "data.active", False))
            elif interaction_type in {"DAMAGE", "CUT"}:
                amt = _bounded_number(10 if amount is None else amount, 0.001, 10000, "damage amount")
                effective = amt * profile["damage_multiplier"]
                new_integrity = max(0.0, float(d["integrity"]) - effective)
                consequences.append(self._set(target_ref, "data.integrity", new_integrity, 0))
                if new_integrity <= 0:
                    consequences += [
                        self._set(target_ref, "data.functional", False, 1),
                        self._set(target_ref, "data.active", False, 2),
                        self._set(target_ref, "data.burning", False, 3),
                        self._set(target_ref, "data.fire_intensity", 0.0, 4),
                        self._set(target_ref, "lifecycle", "DESTROYED", 5),
                        {"target_ref": target_ref, "operation": "SCHEDULE_RECOVERY", "priority": 6, "kind": "SCHEDULED",
                         "restore": {"lifecycle": "ACTIVE", "data.functional": True, "data.integrity": float(profile["base_integrity"]),
                                     "data.active": False, "data.burning": False, "data.fire_intensity": 0.0}},
                    ]
            elif interaction_type == "REPAIR":
                amt = _bounded_number(10 if amount is None else amount, 0.001, 100, "repair amount")
                new_integrity = min(float(profile["base_integrity"]), float(d["integrity"]) + amt)
                consequences.append(self._set(target_ref, "data.integrity", new_integrity))
                if new_integrity > 0 and target.get("lifecycle") != "DESTROYED":
                    consequences.append(self._set(target_ref, "data.functional", True, 1))
            elif interaction_type == "IGNITE":
                if not profile["flammable"]: raise ConflictError("object is nonflammable")
                if float(d["wetness"]) > profile["ignition_wetness_max"]: raise ConflictError("object too wet to ignite")
                consequences += [self._set(target_ref, "data.burning", True), self._set(target_ref, "data.fire_intensity", max(20.0, float(d["fire_intensity"])), 1), self._set(target_ref, "data.temperature", max(float(d["temperature"]), profile["ignition_temperature"]), 2)]
            elif interaction_type == "EXTINGUISH":
                consequences += [self._set(target_ref, "data.burning", False), self._set(target_ref, "data.fire_intensity", 0.0, 1)]
            elif interaction_type == "HEAT":
                amt = _bounded_number(10 if amount is None else amount, 0.001, 5000, "heat amount")
                gain = amt * (1.0 - profile["heat_resistance"])
                new_temp = min(5000.0, float(d["temperature"]) + gain)
                consequences.append(self._set(target_ref, "data.temperature", new_temp))
                if profile["flammable"] and new_temp >= profile["ignition_temperature"] and float(d["wetness"]) <= profile["ignition_wetness_max"]:
                    consequences += [self._set(target_ref, "data.burning", True, 1), self._set(target_ref, "data.fire_intensity", max(20.0, float(d["fire_intensity"])), 2)]
            elif interaction_type == "COOL":
                amt = _bounded_number(10 if amount is None else amount, 0.001, 5000, "cool amount")
                new_temp = max(-200.0, float(d["temperature"]) - amt)
                consequences.append(self._set(target_ref, "data.temperature", new_temp))
            elif interaction_type == "SOAK":
                amt = _bounded_number(10 if amount is None else amount, 0.001, 100, "soak amount")
                new_wet = min(100.0, float(d["wetness"]) + amt * profile["water_absorption"])
                consequences.append(self._set(target_ref, "data.wetness", new_wet))
                if new_wet >= 60 and d.get("burning"):
                    consequences += [self._set(target_ref, "data.burning", False, 1), self._set(target_ref, "data.fire_intensity", 0.0, 2)]
            elif interaction_type == "DRY":
                amt = _bounded_number(10 if amount is None else amount, 0.001, 100, "dry amount")
                consequences.append(self._set(target_ref, "data.wetness", max(0.0, float(d["wetness"]) - amt)))
            elif interaction_type == "HARVEST":
                if not profile["harvestable"]: raise ValidationError("profile is not harvestable")
                amt = _bounded_number(1 if amount is None else amount, 0.001, 1e12, "harvest amount")
                q = float(d.get("resource_quantity", 0))
                if q < amt: raise ConflictError("insufficient resource quantity")
                consequences.append(self._set(target_ref, "data.resource_quantity", q - amt))
            execution_class = "ROUTINE_SAFE" if routine_safe else "ACTIVE_ONLY"
            if routine_safe and actor_ref not in SYSTEM_ACTORS:
                raise ValidationError("ROUTINE_SAFE object interaction requires system actor")
            action = self._action(world, actor_ref, f"OBJECT_{interaction_type}", target, {"interaction_type": interaction_type, "amount": amount}, execution_class=execution_class, source=actor_ref if actor_ref in SYSTEM_ACTORS else None, idempotency_key=idempotency_key)
            result = self.runtime.apply_action(world_instance_id, action, consequences)
            self._log_reaction(world_instance_id, result["event_id"], target_ref, reason, {"actor_ref": actor_ref, "consequence_count": len(consequences)})
            result["target_ref"] = target_ref
            result["interaction_type"] = interaction_type
            return result

    def update_environment(self, world_instance_id: str, zone_ref: str, *, actor_ref: str = "SYSTEM_ROUTINE", deltas: dict[str, float], idempotency_key: str | None = None) -> dict[str, Any]:
        with self._lock:
            world = self._world(world_instance_id)
            zone = self.runtime.get_entity(world_instance_id, zone_ref)
            if zone.get("entity_kind") != "ENVIRONMENT_ZONE": raise ValidationError("not an environment zone")
            allowed = {"temperature": (-200,5000), "humidity": (0,100), "fire_intensity": (0,100), "smoke": (0,100), "water_level": (0,100), "contamination": (0,100)}
            consequences=[]
            for k,v in deltas.items():
                if k not in allowed: raise ValidationError(f"invalid environment field: {k}")
                if not isinstance(v,(int,float)) or isinstance(v,bool): raise ValidationError("environment delta must be numeric")
                cur=float(zone["data"][k]); lo,hi=allowed[k]; nv=min(hi,max(lo,cur+float(v)))
                consequences.append(self._set(zone_ref,f"data.{k}",nv))
            action=self._action(world,actor_ref,"ENVIRONMENT_UPDATE",zone,{"deltas":copy.deepcopy(deltas)},execution_class="ROUTINE_SAFE" if actor_ref=="SYSTEM_ROUTINE" else "ACTIVE_ONLY",source=actor_ref if actor_ref in SYSTEM_ACTORS else None,idempotency_key=idempotency_key)
            result=self.runtime.apply_action(world_instance_id,action,consequences)
            self._log_reaction(world_instance_id,result["event_id"],zone_ref,"ENVIRONMENT_UPDATE",{"deltas":deltas})
            return result

    def simulate_environment_tick(self, world_instance_id: str, *, tick_key: str) -> dict[str, Any]:
        if not isinstance(tick_key,str) or not tick_key: raise ValidationError("tick_key required")
        with self._lock:
            with self.runtime._write_lock:
                cached=self.conn.execute("SELECT result_json,result_hash FROM environment_ticks WHERE world_instance_id=? AND tick_key=?",(world_instance_id,tick_key)).fetchone()
            if cached:
                if sha256_text(cached["result_json"])!=cached["result_hash"]: raise IntegrityError("environment tick hash mismatch")
                out=json.loads(cached["result_json"]); out["idempotent_replay"]=True; return out
            world=self._world(world_instance_id)
            rows=self.conn.execute("SELECT * FROM environment_links WHERE world_instance_id=? AND active=1 AND link_type='ENVIRONMENT_MEMBER' ORDER BY link_id",(world_instance_id,)).fetchall()
            applied=0; blocked=0
            for row in rows:
                zone=self.runtime.get_entity(world_instance_id,row["source_ref"])
                obj=self.runtime.get_entity(world_instance_id,row["target_ref"])
                if zone.get("entity_kind")!="ENVIRONMENT_ZONE": continue
                zd=zone["data"]
                try:
                    offline = world["simulation_mode"] == "ROUTINE_OFFLINE"
                    if float(zd["fire_intensity"])>0 and not offline:
                        self.interact(world_instance_id,actor_ref="SYSTEM_ROUTINE",target_ref=obj["entity_runtime_id"],interaction_type="HEAT",amount=max(1.0,float(zd["fire_intensity"])*0.15*float(row["conductance"])),routine_safe=True,idempotency_key=f"envtick:{tick_key}:{row['link_id']}:heat"); applied+=1
                    elif float(zd["fire_intensity"])>0 and offline:
                        blocked += 1
                    if float(zd["water_level"])>0 or float(zd["humidity"])>=90:
                        self.interact(world_instance_id,actor_ref="SYSTEM_ROUTINE",target_ref=obj["entity_runtime_id"],interaction_type="SOAK",amount=max(float(zd["water_level"])*0.1,5 if float(zd["humidity"])>=90 else 0),routine_safe=True,idempotency_key=f"envtick:{tick_key}:{row['link_id']}:soak"); applied+=1
                    fresh=self.runtime.get_entity(world_instance_id,obj["entity_runtime_id"])
                    if fresh["data"].get("burning") and not offline:
                        self.update_environment(world_instance_id,zone["entity_runtime_id"],deltas={"fire_intensity":2*float(row["conductance"]),"smoke":3*float(row["conductance"])},idempotency_key=f"envtick:{tick_key}:{row['link_id']}:zone"); applied+=1
                    elif fresh["data"].get("burning") and offline:
                        blocked += 1
                except (ConflictError,ValidationError,OfflinePolicyError): blocked+=1
            result={"world_instance_id":world_instance_id,"tick_key":tick_key,"applied":applied,"blocked":blocked,"simulation_mode":world["simulation_mode"],"status":"PASS","idempotent_replay":False}
            body=canonical_json(result)
            with self.runtime._write_lock:self.conn.execute("INSERT INTO environment_ticks VALUES(?,?,?,?)",(world_instance_id,tick_key,body,sha256_text(body)))
            return result

    def propagate_fire(self, world_instance_id: str, root_ref: str, *, propagation_key: str, budget: int | None = None) -> dict[str, Any]:
        budget=self.DEFAULT_PROPAGATION_BUDGET if budget is None else budget
        if not isinstance(budget,int) or budget<1 or budget>self.DEFAULT_PROPAGATION_BUDGET: raise ValidationError("invalid propagation budget")
        with self._lock:
            world = self._world(world_instance_id)
            if world["simulation_mode"] == "ROUTINE_OFFLINE":
                raise OfflinePolicyError("extraordinary fire propagation is blocked offline")
            with self.runtime._write_lock:
                cached=self.conn.execute("SELECT result_json,result_hash FROM propagation_runs_env WHERE world_instance_id=? AND propagation_key=?",(world_instance_id,propagation_key)).fetchone()
            if cached:
                if sha256_text(cached["result_json"])!=cached["result_hash"]: raise IntegrityError("propagation run hash mismatch")
                out=json.loads(cached["result_json"]);out["idempotent_replay"]=True;return out
            root=self.runtime.get_entity(world_instance_id,root_ref);self._profile_for_entity(world_instance_id,root)
            if not root["data"].get("burning"): raise ConflictError("root object is not burning")
            queue=[(root_ref,0)];visited={root_ref};heated=0;ignited=0;stops=[]
            while queue and heated<budget:
                current,depth=queue.pop(0)
                if depth>=self.MAX_PROPAGATION_DEPTH:
                    stops.append({"ref":current,"reason":"MAX_DEPTH"});continue
                rows=self.conn.execute("SELECT * FROM environment_links WHERE world_instance_id=? AND active=1 AND link_type='ADJACENT' AND (source_ref=? OR target_ref=?) ORDER BY link_id",(world_instance_id,current,current)).fetchall()
                for row in rows:
                    if heated>=budget:break
                    other=row["target_ref"] if row["source_ref"]==current else row["source_ref"]
                    if other in visited:continue
                    visited.add(other)
                    try:
                        before=self.runtime.get_entity(world_instance_id,other)
                        self._profile_for_entity(world_instance_id,before)
                        self.interact(world_instance_id,actor_ref="SYSTEM_ROUTINE",target_ref=other,interaction_type="HEAT",amount=100*float(row["conductance"]),routine_safe=True,idempotency_key=f"fireprop:{propagation_key}:{row['link_id']}")
                        heated+=1
                        after=self.runtime.get_entity(world_instance_id,other)
                        if after["data"].get("burning") and not before["data"].get("burning"):
                            ignited+=1;queue.append((other,depth+1))
                    except (ConflictError,ValidationError,OfflinePolicyError):
                        stops.append({"ref":other,"reason":"BLOCKED"})
            result={"world_instance_id":world_instance_id,"propagation_key":propagation_key,"root_ref":root_ref,"heated":heated,"ignited":ignited,"visited":len(visited),"budget":budget,"budget_exhausted":heated>=budget,"stops":stops,"status":"PASS","idempotent_replay":False}
            body=canonical_json(result)
            with self.runtime._write_lock:self.conn.execute("INSERT INTO propagation_runs_env VALUES(?,?,?,?,?)",(world_instance_id,propagation_key,root_ref,body,sha256_text(body)))
            return result

    def full_integrity_check(self, world_instance_id: str) -> dict[str, Any]:
        failures=[]
        base=self.runtime.full_integrity_check(world_instance_id)
        if base.get("status")!="PASS":failures.append({"error":"RUNTIME_INTEGRITY_FAIL","detail":base})
        with self.runtime._write_lock:
            for table,jcol,hcol in [("reactive_profiles","profile_json","profile_hash"),("environment_links","link_json","link_hash"),("reaction_logs","record_json","record_hash"),("environment_ticks","result_json","result_hash"),("propagation_runs_env","result_json","result_hash")]:
                rows=self.conn.execute(f"SELECT rowid,{jcol},{hcol} FROM {table}").fetchall()
                for row in rows:
                    if sha256_text(row[jcol])!=row[hcol]: failures.append({"table":table,"rowid":row["rowid"],"error":"HASH_MISMATCH"})
        for e in self.runtime.list_entities(world_instance_id):
            if e.get("entity_kind") in {"OBJECT","STRUCTURE","FLORA_INSTANCE","RESOURCE_NODE"} and e.get("data",{}).get("reactive_profile_id"):
                try:
                    p=self._profile_for_entity(world_instance_id,e);d=e["data"];self._validate_object_data(p,d)
                    if e.get("lifecycle")=="DESTROYED" and d.get("functional") is not False: failures.append({"entity":e["entity_runtime_id"],"error":"DESTROYED_FUNCTIONAL"})
                    if d.get("burning") is False and float(d.get("fire_intensity",0))>0: failures.append({"entity":e["entity_runtime_id"],"error":"FIRE_STATE_INCONSISTENT"})
                except Exception as exc:failures.append({"entity":e.get("entity_runtime_id"),"error":"OBJECT_INVARIANT_EXCEPTION","detail":repr(exc)})
        return {"world_instance_id":world_instance_id,"failures":failures,"status":"PASS" if not failures else "FAIL"}
