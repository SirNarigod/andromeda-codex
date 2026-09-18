from __future__ import annotations

import copy, json, sqlite3, threading
from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from living_runtime import (
    LivingRuntime, ValidationError, IntegrityError, ConflictError, NotFoundError,
    OfflinePolicyError, canonical_json, sha256_text, new_runtime_id, clock_point,
)
from consequence_engine import ConsequenceEngine
from agent_brain import AgentBrain, IntentValidator
from social_memory import SocialMemorySystem
from ecology_brain import EcologySystem
from object_environment import ObjectEnvironmentSystem
from domain_integration import DomainIntegrationHub

ALLOWED_LOD = {"FULL", "ACTIVE", "AGGREGATE", "ROUTINE_OFFLINE"}
LOD_RANK = {"ROUTINE_OFFLINE": 0, "AGGREGATE": 1, "ACTIVE": 2, "FULL": 3}
PARTICIPANT_SUBSYSTEMS = {"NPC", "ECOLOGY"}
PHASE_ORDER = [
    "PRE_GUARD", "RECOVERY", "ENVIRONMENT", "ECOLOGY_AGGREGATE",
    "ECOLOGY_INDIVIDUAL", "SOCIAL_PROJECTION", "NPC_AUTONOMY",
    "EXTENSIONS", "CONSEQUENCE_DRAIN", "POST_GUARD", "CLOCK_ADVANCE",
]


def _abs_tick(clock: dict[str, Any]) -> int:
    return int(clock["day"]) * int(clock["ticks_per_day"]) + int(clock["tick"])


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, set):
        return sorted(_json_safe(v) for v in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "__dict__"):
        return _json_safe(vars(value))
    raise TypeError(f"unsupported orchestration ledger value: {type(value).__name__}")


class WorldSimulationOrchestrator:
    """Deterministic coordinator. It schedules existing authorities; it does not replace them."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        runtime: LivingRuntime,
        consequence_engine: ConsequenceEngine,
        brain: AgentBrain,
        validator: IntentValidator,
        social: SocialMemorySystem,
        ecology: EcologySystem,
        objects: ObjectEnvironmentSystem,
    ) -> None:
        if any(x.runtime is not runtime for x in [consequence_engine, brain, validator, social, ecology, objects]):
            raise ValidationError("all orchestrated systems must share the same LivingRuntime")
        if brain.validator is not validator or ecology.validator is not validator:
            raise ValidationError("brain/ecology validator mismatch")
        self.runtime = runtime
        self.consequence_engine = consequence_engine
        self.brain = brain
        self.validator = validator
        self.social = social
        self.ecology = ecology
        self.objects = objects
        self.domain_integration = DomainIntegrationHub(runtime, ecology, social)
        self.conn = runtime.conn
        self._lock = threading.RLock()
        self._adapters: dict[str, dict[str, Any]] = {}
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self.runtime._write_lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS orchestration_policies(
                    world_instance_id TEXT PRIMARY KEY REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    policy_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS simulation_scopes(
                    scope_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    scope_ref TEXT NOT NULL,
                    lod TEXT NOT NULL CHECK(lod IN ('FULL','ACTIVE','AGGREGATE')),
                    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                    scope_json TEXT NOT NULL,
                    scope_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id,scope_ref)
                );
                CREATE TABLE IF NOT EXISTS orchestration_participants(
                    participant_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    entity_ref TEXT NOT NULL,
                    subsystem TEXT NOT NULL CHECK(subsystem IN ('NPC','ECOLOGY')),
                    scope_ref TEXT,
                    priority INTEGER NOT NULL,
                    cadence_ticks INTEGER NOT NULL CHECK(cadence_ticks > 0),
                    next_due_abs_tick INTEGER NOT NULL CHECK(next_due_abs_tick >= 0),
                    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                    participant_json TEXT NOT NULL,
                    participant_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id,entity_ref,subsystem)
                );
                CREATE TABLE IF NOT EXISTS orchestration_extension_descriptors(
                    extension_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    extension_key TEXT NOT NULL,
                    version TEXT NOT NULL,
                    modes_json TEXT NOT NULL,
                    cadence_ticks INTEGER NOT NULL CHECK(cadence_ticks > 0),
                    routine_safe INTEGER NOT NULL CHECK(routine_safe IN (0,1)),
                    handler_ref TEXT NOT NULL,
                    descriptor_json TEXT NOT NULL,
                    descriptor_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id,extension_key)
                );
                CREATE TABLE IF NOT EXISTS orchestration_config_snapshots(
                    snapshot_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    snapshot_json TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orchestration_runs(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    tick_key TEXT NOT NULL,
                    simulation_mode TEXT NOT NULL,
                    started_day INTEGER NOT NULL,
                    started_tick INTEGER NOT NULL,
                    completed_day INTEGER,
                    completed_tick INTEGER,
                    status TEXT NOT NULL CHECK(status IN ('RUNNING','COMPLETED','FAILED')),
                    prev_hash TEXT NOT NULL,
                    run_json TEXT,
                    run_hash TEXT,
                    UNIQUE(world_instance_id,tick_key)
                );
                CREATE INDEX IF NOT EXISTS idx_orch_runs_world_seq ON orchestration_runs(world_instance_id,sequence);
                CREATE TABLE IF NOT EXISTS orchestration_phase_log(
                    phase_log_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES orchestration_runs(run_id) ON DELETE RESTRICT,
                    world_instance_id TEXT NOT NULL,
                    phase_order INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PASS','SKIPPED','FAILED')),
                    phase_json TEXT NOT NULL,
                    phase_hash TEXT NOT NULL,
                    UNIQUE(run_id,phase)
                );
                CREATE TRIGGER IF NOT EXISTS orch_phase_no_update BEFORE UPDATE ON orchestration_phase_log BEGIN SELECT RAISE(ABORT,'orchestration phase log is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS orch_phase_no_delete BEFORE DELETE ON orchestration_phase_log BEGIN SELECT RAISE(ABORT,'orchestration phase log is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS orch_config_no_update BEFORE UPDATE ON orchestration_config_snapshots BEGIN SELECT RAISE(ABORT,'orchestration config snapshot is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS orch_config_no_delete BEFORE DELETE ON orchestration_config_snapshots BEGIN SELECT RAISE(ABORT,'orchestration config snapshot is immutable'); END;
                """
            )
            self.conn.execute("INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('orchestrator_schema_version',?)", (str(self.SCHEMA_VERSION),))

    def _default_policy(self) -> dict[str, Any]:
        return {
            "policy_version": "V1.0",
            "authority": "RUNTIME_ORCHESTRATION_NOT_CANON",
            "ticks_per_run": 1,
            "full_npc_budget": 64,
            "active_npc_budget": 24,
            "full_ecology_budget": 96,
            "active_ecology_budget": 32,
            "environment_cadence_ticks": 1,
            "ecology_aggregate_cadence_ticks": 24,
            "integrity_cadence_ticks": 24,
            "consequence_root_budget": 64,
            "max_roots_per_run": 256,
            "extension_budget": 32,
            "fail_closed_on_unexpected": True,
        }

    def configure_world(self, world_instance_id: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        world = self.runtime.get_world(world_instance_id)
        p = self._default_policy()
        if overrides:
            unknown = set(overrides) - set(p)
            if unknown:
                raise ValidationError(f"unknown orchestration policy fields: {sorted(unknown)}")
            p.update(copy.deepcopy(overrides))
        for k in ["ticks_per_run", "full_npc_budget", "active_npc_budget", "full_ecology_budget", "active_ecology_budget", "environment_cadence_ticks", "ecology_aggregate_cadence_ticks", "integrity_cadence_ticks", "consequence_root_budget", "max_roots_per_run", "extension_budget"]:
            if not isinstance(p[k], int) or isinstance(p[k], bool) or p[k] <= 0:
                raise ValidationError(f"{k} must be positive integer")
        if p["consequence_root_budget"] > self.consequence_engine.DEFAULT_BUDGET:
            raise ValidationError("consequence_root_budget exceeds causal engine maximum")
        minimum_root_capacity = p["full_npc_budget"] + p["full_ecology_budget"] + p["extension_budget"] + 4
        if p["max_roots_per_run"] < minimum_root_capacity:
            raise ValidationError(f"max_roots_per_run must be >= {minimum_root_capacity} for configured action budgets")
        if not isinstance(p["fail_closed_on_unexpected"], bool):
            raise ValidationError("fail_closed_on_unexpected must be boolean")
        body = {"world_instance_id": world_instance_id, "timeline_id": world["timeline_id"], **p}
        text = canonical_json(body); h = sha256_text(text)
        with self._lock, self.runtime._write_lock:
            row = self.conn.execute("SELECT 1 FROM orchestration_policies WHERE world_instance_id=?", (world_instance_id,)).fetchone()
            if row:
                self.conn.execute("UPDATE orchestration_policies SET policy_json=?,policy_hash=? WHERE world_instance_id=?", (text,h,world_instance_id))
            else:
                self.conn.execute("INSERT INTO orchestration_policies VALUES(?,?,?,?)", (world_instance_id,world["timeline_id"],text,h))
        body["policy_hash"] = h
        return body

    def get_policy(self, world_instance_id: str) -> dict[str, Any]:
        with self._lock, self.runtime._write_lock:
            row = self.conn.execute("SELECT policy_json,policy_hash FROM orchestration_policies WHERE world_instance_id=?", (world_instance_id,)).fetchone()
        if not row:
            return self.configure_world(world_instance_id)
        if sha256_text(row["policy_json"]) != row["policy_hash"]:
            raise IntegrityError("orchestration policy hash mismatch")
        return json.loads(row["policy_json"])

    def register_scope(self, world_instance_id: str, scope_ref: str, lod: str, *, enabled: bool = True) -> dict[str, Any]:
        world = self.runtime.get_world(world_instance_id)
        if not isinstance(scope_ref, str) or not scope_ref:
            raise ValidationError("scope_ref required")
        if lod not in {"FULL","ACTIVE","AGGREGATE"}:
            raise ValidationError("scope lod invalid")
        if scope_ref.startswith("rt:"):
            self.runtime.get_entity(world_instance_id, scope_ref)
        elif not self.runtime.canonical_ref_resolves(scope_ref):
            raise ValidationError("scope_ref does not resolve")
        sid = new_runtime_id("scope")
        body = {"scope_id":sid,"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"scope_ref":scope_ref,"lod":lod,"enabled":bool(enabled)}
        text=canonical_json(body); h=sha256_text(text)
        with self._lock,self.runtime._write_lock:
            if self.conn.execute("SELECT 1 FROM simulation_scopes WHERE world_instance_id=? AND scope_ref=?",(world_instance_id,scope_ref)).fetchone():
                raise ConflictError("simulation scope already registered")
            self.conn.execute("INSERT INTO simulation_scopes VALUES(?,?,?,?,?,?,?,?)",(sid,world_instance_id,world["timeline_id"],scope_ref,lod,1 if enabled else 0,text,h))
        body["scope_hash"]=h; return body

    def set_scope_lod(self, world_instance_id: str, scope_ref: str, lod: str) -> dict[str, Any]:
        if lod not in {"FULL","ACTIVE","AGGREGATE"}:
            raise ValidationError("scope lod invalid")
        with self._lock,self.runtime._write_lock:
            row=self.conn.execute("SELECT * FROM simulation_scopes WHERE world_instance_id=? AND scope_ref=?",(world_instance_id,scope_ref)).fetchone()
            if not row: raise NotFoundError("scope not found")
            body=json.loads(row["scope_json"]); body["lod"]=lod; text=canonical_json(body);h=sha256_text(text)
            self.conn.execute("UPDATE simulation_scopes SET lod=?,scope_json=?,scope_hash=? WHERE scope_id=?",(lod,text,h,row["scope_id"]))
        body["scope_hash"]=h;return body

    def register_participant(self, world_instance_id: str, entity_ref: str, subsystem: str, *, scope_ref: str | None=None, priority: int=0, cadence_ticks: int=1, metadata: dict[str,Any] | None=None) -> dict[str,Any]:
        world=self.runtime.get_world(world_instance_id)
        if subsystem not in PARTICIPANT_SUBSYSTEMS: raise ValidationError("participant subsystem invalid")
        if not isinstance(priority,int) or isinstance(priority,bool): raise ValidationError("priority must be integer")
        if not isinstance(cadence_ticks,int) or cadence_ticks<=0: raise ValidationError("cadence_ticks must be positive")
        ent=self.runtime.get_entity(world_instance_id,entity_ref)
        expected="AGENT" if subsystem=="NPC" else "ANIMAL"
        if subsystem=="NPC" and ent.get("entity_kind")!="AGENT": raise ValidationError("NPC participant must be AGENT")
        if subsystem=="ECOLOGY" and ent.get("entity_kind") not in {"ANIMAL","CREATURE"}: raise ValidationError("ECOLOGY participant must be ANIMAL/CREATURE")
        if scope_ref:
            if not self.conn.execute("SELECT 1 FROM simulation_scopes WHERE world_instance_id=? AND scope_ref=? AND enabled=1",(world_instance_id,scope_ref)).fetchone():
                raise ValidationError("participant scope not registered/enabled")
        m=copy.deepcopy(metadata or {})
        if not isinstance(m,dict): raise ValidationError("metadata must be object")
        if "social_targets" in m and (not isinstance(m["social_targets"],list) or any(not isinstance(x,str) for x in m["social_targets"])):
            raise ValidationError("social_targets must be string list")
        pid=new_runtime_id("participant");now=_abs_tick(world["clock_state"])
        body={"participant_id":pid,"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"entity_ref":entity_ref,"subsystem":subsystem,"scope_ref":scope_ref,"priority":priority,"cadence_ticks":cadence_ticks,"enabled":True,"metadata":m}
        text=canonical_json(body);h=sha256_text(text)
        with self._lock,self.runtime._write_lock:
            self.conn.execute("INSERT INTO orchestration_participants VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(pid,world_instance_id,world["timeline_id"],entity_ref,subsystem,scope_ref,priority,cadence_ticks,now,1,text,h))
        body["participant_hash"]=h;body["next_due_abs_tick"]=now;return body

    def _effective_lod(self, world_instance_id: str, world_mode: str, scope_ref: str | None) -> str:
        if world_mode == "ROUTINE_OFFLINE": return "ROUTINE_OFFLINE"
        global_rank=LOD_RANK[world_mode]
        if not scope_ref: return world_mode
        row=self.conn.execute("SELECT lod,enabled,scope_json,scope_hash FROM simulation_scopes WHERE world_instance_id=? AND scope_ref=?",(world_instance_id,scope_ref)).fetchone()
        if not row or not row["enabled"]: return "AGGREGATE"
        if sha256_text(row["scope_json"])!=row["scope_hash"]: raise IntegrityError("simulation scope hash mismatch")
        return min((world_mode,row["lod"]), key=lambda x: LOD_RANK[x]) if LOD_RANK[row["lod"]] < global_rank else world_mode

    def attach_extension(self, world_instance_id: str, key: str, handler: Callable[[dict[str,Any]], dict[str,Any]], *, version: str="V1.0", modes: set[str] | None=None, cadence_ticks: int=1, routine_safe: bool=False) -> dict[str,Any]:
        world=self.runtime.get_world(world_instance_id)
        if not isinstance(key,str) or not key: raise ValidationError("extension key invalid")
        if not callable(handler): raise ValidationError("extension handler must be callable")
        if not isinstance(version,str) or not version.strip(): raise ValidationError("extension version required")
        modes=set(modes or {"FULL","ACTIVE","AGGREGATE"})
        if not modes or not modes <= ALLOWED_LOD: raise ValidationError("extension modes invalid")
        if "ROUTINE_OFFLINE" in modes and not routine_safe: raise ValidationError("offline extension must be explicitly routine_safe")
        if not isinstance(cadence_ticks,int) or cadence_ticks<=0: raise ValidationError("extension cadence invalid")
        handler_ref=f"{getattr(handler,'__module__','unknown')}:{getattr(handler,'__qualname__',getattr(handler,'__name__','callable'))}"
        eid=new_runtime_id("extension")
        body={"extension_id":eid,"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"extension_key":key,"version":version,"modes":sorted(modes),"cadence_ticks":cadence_ticks,"routine_safe":bool(routine_safe),"handler_ref":handler_ref,"authority":"RUNTIME_EXTENSION_DESCRIPTOR_NOT_CANON"}
        text=canonical_json(body);h=sha256_text(text)
        with self._lock,self.runtime._write_lock:
            if self.conn.execute("SELECT 1 FROM orchestration_extension_descriptors WHERE world_instance_id=? AND extension_key=?",(world_instance_id,key)).fetchone(): raise ConflictError("extension key already registered for world")
            self.conn.execute("INSERT INTO orchestration_extension_descriptors VALUES(?,?,?,?,?,?,?,?,?,?,?)",(eid,world_instance_id,world["timeline_id"],key,version,canonical_json(sorted(modes)),cadence_ticks,1 if routine_safe else 0,handler_ref,text,h))
            self._adapters[(world_instance_id,key)]={"handler":handler,"modes":modes,"cadence_ticks":cadence_ticks,"routine_safe":bool(routine_safe),"version":version,"handler_ref":handler_ref}
        body["descriptor_hash"]=h;return body

    def _preflight_extensions(self, world_instance_id: str) -> dict[str,Any]:
        rows=self.conn.execute("SELECT * FROM orchestration_extension_descriptors WHERE world_instance_id=? ORDER BY extension_key",(world_instance_id,)).fetchall()
        for row in rows:
            if sha256_text(row["descriptor_json"])!=row["descriptor_hash"]: raise IntegrityError("extension descriptor hash mismatch")
            adapter=self._adapters.get((world_instance_id,row["extension_key"]))
            if adapter is None: raise ConflictError(f"extension handler not bound: {row['extension_key']}")
            if adapter.get("handler_ref")!=row["handler_ref"]: raise IntegrityError("bound extension handler identity drift")
        return {"registered":len(rows),"status":"PASS"}

    def _capture_config_snapshot(self, run_id: str, world_instance_id: str, world: dict[str,Any], policy: dict[str,Any]) -> dict[str,Any]:
        scopes=[]
        for r in self.conn.execute("SELECT scope_ref,lod,enabled,scope_json,scope_hash FROM simulation_scopes WHERE world_instance_id=? ORDER BY scope_ref",(world_instance_id,)).fetchall():
            if sha256_text(r["scope_json"])!=r["scope_hash"]: raise IntegrityError("simulation scope hash mismatch during snapshot")
            scopes.append({"scope_ref":r["scope_ref"],"lod":r["lod"],"enabled":bool(r["enabled"]),"scope_hash":r["scope_hash"]})
        participants=[]
        for r in self.conn.execute("SELECT entity_ref,subsystem,scope_ref,priority,cadence_ticks,next_due_abs_tick,enabled,participant_hash FROM orchestration_participants WHERE world_instance_id=? ORDER BY subsystem,entity_ref",(world_instance_id,)).fetchall():
            participants.append({k:r[k] for k in ["entity_ref","subsystem","scope_ref","priority","cadence_ticks","next_due_abs_tick","enabled","participant_hash"]})
        extensions=[]
        for r in self.conn.execute("SELECT extension_key,version,modes_json,cadence_ticks,routine_safe,handler_ref,descriptor_hash FROM orchestration_extension_descriptors WHERE world_instance_id=? ORDER BY extension_key",(world_instance_id,)).fetchall():
            extensions.append({"extension_key":r["extension_key"],"version":r["version"],"modes":json.loads(r["modes_json"]),"cadence_ticks":r["cadence_ticks"],"routine_safe":bool(r["routine_safe"]),"handler_ref":r["handler_ref"],"descriptor_hash":r["descriptor_hash"]})
        body={"snapshot_id":new_runtime_id("config"),"run_id":run_id,"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"simulation_mode":world["simulation_mode"],"clock":copy.deepcopy(world["clock_state"]),"policy":copy.deepcopy(policy),"scopes":scopes,"participants":participants,"extensions":extensions}
        text=canonical_json(body);h=sha256_text(text)
        self.conn.execute("INSERT INTO orchestration_config_snapshots VALUES(?,?,?,?,?)",(body["snapshot_id"],run_id,world_instance_id,text,h))
        body["snapshot_hash"]=h;return body

    def bind_extension_handler(self, world_instance_id: str, key: str, handler: Callable[[dict[str,Any]], dict[str,Any]]) -> dict[str,Any]:
        if not callable(handler): raise ValidationError("extension handler must be callable")
        with self._lock,self.runtime._write_lock:
            row=self.conn.execute("SELECT * FROM orchestration_extension_descriptors WHERE world_instance_id=? AND extension_key=?",(world_instance_id,key)).fetchone()
            if not row: raise NotFoundError("extension descriptor not found")
            if sha256_text(row["descriptor_json"])!=row["descriptor_hash"]: raise IntegrityError("extension descriptor hash mismatch")
            handler_ref=f"{getattr(handler,'__module__','unknown')}:{getattr(handler,'__qualname__',getattr(handler,'__name__','callable'))}"
            if handler_ref!=row["handler_ref"]: raise IntegrityError("extension handler identity does not match persisted descriptor")
            modes=set(json.loads(row["modes_json"]))
            self._adapters[(world_instance_id,key)]={"handler":handler,"modes":modes,"cadence_ticks":row["cadence_ticks"],"routine_safe":bool(row["routine_safe"]),"version":row["version"],"handler_ref":handler_ref}
        return {"status":"BOUND","world_instance_id":world_instance_id,"extension_key":key,"version":row["version"],"handler_ref":handler_ref}

    def _record_phase(self, run_id: str, world_instance_id: str, phase: str, status: str, detail: dict[str,Any]) -> dict[str,Any]:
        body={"phase_log_id":new_runtime_id("phase"),"run_id":run_id,"world_instance_id":world_instance_id,"phase_order":PHASE_ORDER.index(phase),"phase":phase,"status":status,"detail":_json_safe(copy.deepcopy(detail))}
        text=canonical_json(body);h=sha256_text(text)
        self.conn.execute("INSERT INTO orchestration_phase_log VALUES(?,?,?,?,?,?,?,?)",(body["phase_log_id"],run_id,world_instance_id,body["phase_order"],phase,status,text,h))
        body["phase_hash"]=h;return body

    def _due_participants(self, world_instance_id: str, subsystem: str, world_mode: str, now_abs: int, budget: int) -> list[sqlite3.Row]:
        rows=self.conn.execute("SELECT * FROM orchestration_participants WHERE world_instance_id=? AND subsystem=? AND enabled=1 AND next_due_abs_tick<=?",(world_instance_id,subsystem,now_abs)).fetchall()
        eligible=[]
        for r in rows:
            if sha256_text(r["participant_json"])!=r["participant_hash"]: raise IntegrityError("participant hash mismatch")
            try:
                state=self.runtime.get_entity(world_instance_id,r["entity_ref"])
            except NotFoundError:
                self.conn.execute("UPDATE orchestration_participants SET enabled=0 WHERE participant_id=?",(r["participant_id"],))
                continue
            if state.get("lifecycle")!="ACTIVE":
                # Fail-safe lifecycle filter. DomainIntegrationHub normally retires the
                # participant immediately when the lifecycle transition commits.
                self.conn.execute("UPDATE orchestration_participants SET enabled=0 WHERE participant_id=?",(r["participant_id"],))
                continue
            eff=self._effective_lod(world_instance_id,world_mode,r["scope_ref"])
            if LOD_RANK[eff] >= LOD_RANK["ACTIVE"]:
                eligible.append(r)
        eligible.sort(key=lambda r:(-r["priority"], r["next_due_abs_tick"], r["entity_ref"]))
        return eligible[:budget]

    def _mark_participant_due(self, row: sqlite3.Row, now_abs: int) -> None:
        self.conn.execute("UPDATE orchestration_participants SET next_due_abs_tick=? WHERE participant_id=?",(now_abs+row["cadence_ticks"],row["participant_id"]))

    def _phase_pre_guard(self, world_instance_id: str) -> dict[str,Any]:
        r=self.runtime.full_integrity_check(world_instance_id)
        if r["status"]!="PASS": raise IntegrityError(f"runtime pre-guard failed: {r.get('failures')}")
        return {"runtime":r}

    def _phase_recovery(self, world_instance_id: str) -> dict[str,Any]:
        return self.runtime.process_due_recoveries(world_instance_id)

    def _phase_environment(self, world_instance_id: str, tick_key: str, now_abs: int, policy: dict[str,Any]) -> dict[str,Any]:
        if now_abs % policy["environment_cadence_ticks"]: return {"skipped":"CADENCE"}
        return self.objects.simulate_environment_tick(world_instance_id,tick_key=f"orch:{tick_key}:env")

    def _phase_ecology_aggregate(self, world_instance_id: str, tick_key: str, now_abs: int, policy: dict[str,Any]) -> dict[str,Any]:
        if now_abs % policy["ecology_aggregate_cadence_ticks"]: return {"skipped":"CADENCE"}
        return self.ecology.simulate_population_routine(world_instance_id,routine_key=f"orch:{tick_key}:ecoagg")

    def _phase_ecology_individual(self, world_instance_id: str, world_mode: str, now_abs: int, policy: dict[str,Any]) -> dict[str,Any]:
        if world_mode in {"AGGREGATE","ROUTINE_OFFLINE"}: return {"skipped":"LOD"}
        budget=policy["full_ecology_budget"] if world_mode=="FULL" else policy["active_ecology_budget"]
        rows=self._due_participants(world_instance_id,"ECOLOGY",world_mode,now_abs,budget)
        results=[]
        for r in rows:
            try:
                d=self.ecology.decide(world_instance_id,r["entity_ref"]); ex=self.ecology.execute_decision(d)
                results.append({"entity_ref":r["entity_ref"],"status":ex.get("status","PASS"),"decision_id":d.get("decision_id")})
            except (ValidationError,ConflictError,OfflinePolicyError,NotFoundError) as exc:
                results.append({"entity_ref":r["entity_ref"],"status":"REJECTED","reason":type(exc).__name__})
            self._mark_participant_due(r,now_abs)
        return {"budget":budget,"selected":len(rows),"results":results}

    def _phase_social_projection(self, world_instance_id: str, world_mode: str, now_abs: int, policy: dict[str,Any]) -> dict[str,Any]:
        if world_mode in {"AGGREGATE","ROUTINE_OFFLINE"}: return {"skipped":"LOD"}
        budget=policy["full_npc_budget"] if world_mode=="FULL" else policy["active_npc_budget"]
        rows=self._due_participants(world_instance_id,"NPC",world_mode,now_abs,budget)
        projected=[]
        for r in rows:
            meta=json.loads(r["participant_json"]).get("metadata",{})
            targets=meta.get("social_targets",[])
            if targets:
                try:
                    p=self.social.project_social_perception(self.brain,world_instance_id,r["entity_ref"],targets)
                    projected.append({"entity_ref":r["entity_ref"],"targets":len(targets),"status":p.get("status","PASS")})
                except (ValidationError,ConflictError,NotFoundError) as exc:
                    projected.append({"entity_ref":r["entity_ref"],"targets":len(targets),"status":"REJECTED","reason":type(exc).__name__})
        return {"selected":len(rows),"projected":projected}

    def _phase_npc(self, world_instance_id: str, world_mode: str, now_abs: int, policy: dict[str,Any]) -> dict[str,Any]:
        if world_mode in {"AGGREGATE","ROUTINE_OFFLINE"}: return {"skipped":"LOD"}
        budget=policy["full_npc_budget"] if world_mode=="FULL" else policy["active_npc_budget"]
        rows=self._due_participants(world_instance_id,"NPC",world_mode,now_abs,budget)
        results=[]
        for r in rows:
            try:
                d=self.brain.decide(world_instance_id,r["entity_ref"])
                if not d.get("intent_id"):
                    results.append({"entity_ref":r["entity_ref"],"status":"NO_ACTION","decision_id":d["decision_id"]})
                else:
                    v=self.validator.validate_intent(d["intent_id"])
                    if v.get("status")!="PASS": results.append({"entity_ref":r["entity_ref"],"status":"REJECTED","decision_id":d["decision_id"],"intent_id":d["intent_id"]})
                    else:
                        ex=self.validator.execute_validated_intent(d["intent_id"])
                        results.append({"entity_ref":r["entity_ref"],"status":ex.get("status","PASS"),"decision_id":d["decision_id"],"intent_id":d["intent_id"],"event_id":ex.get("event_id")})
            except (ValidationError,ConflictError,OfflinePolicyError,NotFoundError) as exc:
                results.append({"entity_ref":r["entity_ref"],"status":"REJECTED","reason":type(exc).__name__})
            self._mark_participant_due(r,now_abs)
        return {"budget":budget,"selected":len(rows),"results":results}

    def _phase_extensions(self, context: dict[str,Any], now_abs: int, policy: dict[str,Any]) -> dict[str,Any]:
        out=[]; remaining=policy["extension_budget"]; wid=context["world_instance_id"]
        rows=self.conn.execute("SELECT * FROM orchestration_extension_descriptors WHERE world_instance_id=? ORDER BY extension_key",(wid,)).fetchall()
        for row in rows:
            if remaining<=0: break
            if sha256_text(row["descriptor_json"])!=row["descriptor_hash"]: raise IntegrityError("extension descriptor hash mismatch")
            key=row["extension_key"]; adapter=self._adapters.get((wid,key))
            if adapter is None: raise IntegrityError(f"extension handler missing at runtime: {key}")
            modes=set(json.loads(row["modes_json"]))
            if context["simulation_mode"] not in modes: continue
            if now_abs % row["cadence_ticks"]: continue
            result=adapter["handler"](copy.deepcopy(context))
            if not isinstance(result,dict): raise IntegrityError(f"extension {key} returned non-object")
            out.append({"key":key,"version":row["version"],"handler_ref":row["handler_ref"],"result":result});remaining-=1
        return {"registered":len(rows),"executed":len(out),"remaining_budget":remaining,"extensions":out}

    def _unpropagated_roots(self, world_instance_id: str, limit: int) -> list[str]:
        rows=self.conn.execute("SELECT event_id,causality_json FROM events WHERE world_instance_id=? ORDER BY sequence",(world_instance_id,)).fetchall()
        out=[]
        for r in rows:
            c=json.loads(r["causality_json"])
            if c.get("depth")!=0 or c.get("root_event_id")!=r["event_id"]: continue
            if self.conn.execute("SELECT 1 FROM propagation_runs WHERE root_event_id=?",(r["event_id"],)).fetchone(): continue
            out.append(r["event_id"])
            if len(out)>=limit: break
        return out

    def _phase_consequences(self, world_instance_id: str, policy: dict[str,Any]) -> dict[str,Any]:
        # First reconcile committed domain facts (ecology aggregates, scheduler lifecycle,
        # automatic witnesses), then propagate causal rules. A second bounded integration
        # drain captures any child events emitted during causal propagation.
        integration_before=self.domain_integration.drain_pending(world_instance_id,limit=policy["max_roots_per_run"])
        before=self._unpropagated_roots(world_instance_id,10**9); roots=before[:policy["max_roots_per_run"]]; results=[]
        for eid in roots:
            results.append(self.consequence_engine.propagate_from_event(world_instance_id,eid,budget=policy["consequence_root_budget"]))
        integration_after=self.domain_integration.drain_pending(world_instance_id,limit=policy["max_roots_per_run"])
        after=self._unpropagated_roots(world_instance_id,10**9)
        return {"pending_before":len(before),"roots_processed":len(roots),"pending_after":len(after),"capacity":policy["max_roots_per_run"],"results":results,"domain_integration_before":integration_before,"domain_integration_after":integration_after}

    def drain_pending_consequences(self, world_instance_id: str) -> dict[str,Any]:
        """Public bounded drain used by reconciliation/long-horizon authorities."""
        with self._lock:
            policy=self.get_policy(world_instance_id)
            return self._phase_consequences(world_instance_id,policy)

    def _phase_post_guard(self, world_instance_id: str, now_abs: int, policy: dict[str,Any]) -> dict[str,Any]:
        if now_abs % policy["integrity_cadence_ticks"]:
            r=self.runtime.full_integrity_check(world_instance_id)
            if r["status"]!="PASS": raise IntegrityError("runtime post-guard failed")
            return {"scope":"CORE","runtime":r}
        reports={
            "runtime":self.runtime.full_integrity_check(world_instance_id),
            "consequence":self.consequence_engine.full_integrity_check(world_instance_id),
            "brain":self.brain.full_integrity_check(world_instance_id),
            "validator":self.validator.full_integrity_check(world_instance_id),
            "social":self.social.full_integrity_check(world_instance_id),
            "ecology":self.ecology.full_integrity_check(world_instance_id),
            "objects":self.objects.full_integrity_check(world_instance_id),
        }
        bad=[k for k,v in reports.items() if v.get("status")!="PASS"]
        if bad: raise IntegrityError(f"subsystem post-guard failed: {bad}")
        return {"scope":"FULL","reports":reports}

    def _previous_run_hash(self, world_instance_id: str) -> str:
        row=self.conn.execute("SELECT run_hash FROM orchestration_runs WHERE world_instance_id=? AND status='COMPLETED' AND run_hash IS NOT NULL ORDER BY sequence DESC LIMIT 1",(world_instance_id,)).fetchone()
        return row["run_hash"] if row else "GENESIS"

    def start_background_ticks(self, *, interval_s: float = 0.05):
        from tick_background_service import TickBackgroundService
        service = getattr(self, "_tick_background_service", None)
        if service is None:
            service = TickBackgroundService(self, interval_s=interval_s)
            self._tick_background_service = service
            self.runtime.register_shutdown_hook(service.stop)
        service.start()
        return service

    def register_background_world(self, world_instance_id: str) -> None:
        service = getattr(self, "_tick_background_service", None)
        if service is None:
            raise ConflictError("background tick service is not started")
        service.register_world(world_instance_id)

    def unregister_background_world(self, world_instance_id: str) -> None:
        service = getattr(self, "_tick_background_service", None)
        if service is not None:
            service.unregister_world(world_instance_id)

    def stop_background_ticks(self) -> None:
        service = getattr(self, "_tick_background_service", None)
        if service is not None:
            service.stop()
    def run_tick(self, world_instance_id: str, *, tick_key: str | None=None) -> dict[str,Any]:
        with self._lock, self.runtime._write_lock:
            world=self.runtime.get_world(world_instance_id)
            if world["status"]!="ACTIVE": raise ConflictError("world is not active")
            if world["clock_state"]["state"]!="RUNNING": raise ConflictError("universe clock is paused")
            policy=self.get_policy(world_instance_id); self._preflight_extensions(world_instance_id); before=self.runtime.get_clock(world_instance_id); now_abs=_abs_tick(before)
            key=tick_key or f"{before['day']}:{before['tick']}"
            prior=self.conn.execute("SELECT * FROM orchestration_runs WHERE world_instance_id=? AND tick_key=?",(world_instance_id,key)).fetchone()
            if prior:
                if prior["status"]=="COMPLETED":
                    if not prior["run_json"] or sha256_text(prior["run_json"])!=prior["run_hash"]: raise IntegrityError("orchestration run hash mismatch")
                    body=json.loads(prior["run_json"]);body["idempotent_replay"]=True;return body
                raise ConflictError("orchestration tick already exists but is not completed")
            run_id=new_runtime_id("orun"); prev_hash=self._previous_run_hash(world_instance_id)
            self.conn.execute("INSERT INTO orchestration_runs(run_id,world_instance_id,timeline_id,tick_key,simulation_mode,started_day,started_tick,status,prev_hash) VALUES(?,?,?,?,?,?,?,'RUNNING',?)",(run_id,world_instance_id,world["timeline_id"],key,world["simulation_mode"],before["day"],before["tick"],prev_hash))
            config_snapshot=self._capture_config_snapshot(run_id,world_instance_id,world,policy)
            phases=[]
            context={"run_id":run_id,"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"tick_key":key,"simulation_mode":world["simulation_mode"],"policy_hash":sha256_text(canonical_json(policy)),"config_snapshot_id":config_snapshot["snapshot_id"],"config_snapshot_hash":config_snapshot["snapshot_hash"],"started_at":clock_point(before["day"],before["tick"])}
            try:
                funcs=[
                    ("PRE_GUARD",lambda:self._phase_pre_guard(world_instance_id)),
                    ("RECOVERY",lambda:self._phase_recovery(world_instance_id)),
                    ("ENVIRONMENT",lambda:self._phase_environment(world_instance_id,key,now_abs,policy)),
                    ("ECOLOGY_AGGREGATE",lambda:self._phase_ecology_aggregate(world_instance_id,key,now_abs,policy)),
                    ("ECOLOGY_INDIVIDUAL",lambda:self._phase_ecology_individual(world_instance_id,world["simulation_mode"],now_abs,policy)),
                    ("SOCIAL_PROJECTION",lambda:self._phase_social_projection(world_instance_id,world["simulation_mode"],now_abs,policy)),
                    ("NPC_AUTONOMY",lambda:self._phase_npc(world_instance_id,world["simulation_mode"],now_abs,policy)),
                    ("EXTENSIONS",lambda:self._phase_extensions(context,now_abs,policy)),
                    ("CONSEQUENCE_DRAIN",lambda:self._phase_consequences(world_instance_id,policy)),
                    ("POST_GUARD",lambda:self._phase_post_guard(world_instance_id,now_abs,policy)),
                ]
                for phase,fn in funcs:
                    detail=fn(); status="SKIPPED" if isinstance(detail,dict) and detail.get("skipped") else "PASS"
                    phases.append(self._record_phase(run_id,world_instance_id,phase,status,detail))
                adv=self.runtime.advance_ticks(world_instance_id,policy["ticks_per_run"],source="SYSTEM_CLOCK")
                phases.append(self._record_phase(run_id,world_instance_id,"CLOCK_ADVANCE","PASS",adv))
                after=self.runtime.get_clock(world_instance_id)
                body={**context,"status":"COMPLETED","completed_at":clock_point(after["day"],after["tick"]),"prev_hash":prev_hash,"phases":phases,"phase_count":len(phases)}
                text=canonical_json(body);h=sha256_text(text)
                self.conn.execute("UPDATE orchestration_runs SET completed_day=?,completed_tick=?,status='COMPLETED',run_json=?,run_hash=? WHERE run_id=?",(after["day"],after["tick"],text,h,run_id))
                body["run_hash"]=h;return body
            except Exception as exc:
                self.conn.execute("UPDATE orchestration_runs SET status='FAILED',completed_day=?,completed_tick=? WHERE run_id=?",(before["day"],before["tick"],run_id))
                if isinstance(exc,IntegrityError):
                    self.conn.execute("UPDATE worlds SET status='CORRUPT_BLOCKED' WHERE world_instance_id=?",(world_instance_id,))
                elif policy["fail_closed_on_unexpected"] and not isinstance(exc,(ValidationError,ConflictError,OfflinePolicyError,NotFoundError)):
                    self.conn.execute("UPDATE worlds SET status='PAUSED' WHERE world_instance_id=?",(world_instance_id,))
                raise

    def run_steps(self, world_instance_id: str, count: int) -> list[dict[str,Any]]:
        if not isinstance(count,int) or isinstance(count,bool) or count<=0: raise ValidationError("count must be positive integer")
        out=[]
        for _ in range(count): out.append(self.run_tick(world_instance_id))
        return out

    def verify_run_chain(self, world_instance_id: str) -> dict[str,Any]:
        failures=[];prev="GENESIS"
        with self._lock,self.runtime._write_lock:
            rows=self.conn.execute("SELECT * FROM orchestration_runs WHERE world_instance_id=? AND status='COMPLETED' ORDER BY sequence",(world_instance_id,)).fetchall()
            for r in rows:
                if not r["run_json"] or sha256_text(r["run_json"])!=r["run_hash"]: failures.append(f"RUN_HASH:{r['run_id']}")
                try: body=json.loads(r["run_json"])
                except Exception: body={}
                if r["prev_hash"]!=prev or body.get("prev_hash")!=prev: failures.append(f"RUN_CHAIN:{r['run_id']}")
                prev=r["run_hash"] or prev
        return {"status":"PASS" if not failures else "FAIL","failures":failures,"runs":len(rows)}

    def full_integrity_check(self, world_instance_id: str) -> dict[str,Any]:
        failures=[]
        with self._lock,self.runtime._write_lock:
            p=self.conn.execute("SELECT policy_json,policy_hash FROM orchestration_policies WHERE world_instance_id=?",(world_instance_id,)).fetchall()
            for r in p:
                if sha256_text(r["policy_json"])!=r["policy_hash"]: failures.append("POLICY_HASH")
            for table,j,h in [("simulation_scopes","scope_json","scope_hash"),("orchestration_participants","participant_json","participant_hash"),("orchestration_extension_descriptors","descriptor_json","descriptor_hash"),("orchestration_config_snapshots","snapshot_json","snapshot_hash"),("orchestration_phase_log","phase_json","phase_hash")]:
                rows=self.conn.execute(f"SELECT rowid,* FROM {table} WHERE world_instance_id=?",(world_instance_id,)).fetchall()
                for r in rows:
                    if sha256_text(r[j])!=r[h]: failures.append(f"{table}:HASH:{r['rowid']}")
            orphans=self.conn.execute("SELECT COUNT(*) c FROM orchestration_participants p LEFT JOIN entity_states e ON e.world_instance_id=p.world_instance_id AND e.entity_runtime_id=p.entity_ref WHERE p.world_instance_id=? AND e.entity_runtime_id IS NULL",(world_instance_id,)).fetchone()["c"]
            if orphans: failures.append(f"ORPHAN_PARTICIPANTS:{orphans}")
        chain=self.verify_run_chain(world_instance_id)
        failures.extend(chain["failures"])
        integration=self.domain_integration.full_integrity_check(world_instance_id)
        if integration.get("status")!="PASS": failures.extend([f"DOMAIN_INTEGRATION:{x}" for x in integration.get("failures",[])])
        return {"status":"PASS" if not failures else "FAIL","failures":failures,"run_chain":chain,"domain_integration":integration}

    def integrity_guard(self, world_instance_id: str) -> dict[str,Any]:
        reports={
            "runtime":self.runtime.full_integrity_check(world_instance_id),
            "consequence":self.consequence_engine.full_integrity_check(world_instance_id),
            "brain":self.brain.full_integrity_check(world_instance_id),
            "validator":self.validator.full_integrity_check(world_instance_id),
            "social":self.social.full_integrity_check(world_instance_id),
            "ecology":self.ecology.full_integrity_check(world_instance_id),
            "objects":self.objects.full_integrity_check(world_instance_id),
            "domain_integration":self.domain_integration.full_integrity_check(world_instance_id),
            "orchestrator":self.full_integrity_check(world_instance_id),
        }
        bad=[k for k,v in reports.items() if v.get("status")!="PASS"]
        if bad:
            with self.runtime._write_lock:self.conn.execute("UPDATE worlds SET status='CORRUPT_BLOCKED' WHERE world_instance_id=?",(world_instance_id,))
        return {"status":"PASS" if not bad else "FAIL","failures":bad,"reports":reports}
