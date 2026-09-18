from __future__ import annotations

import copy
import json
import threading
from typing import Any, Protocol

from living_runtime import LivingRuntime, ValidationError, IntegrityError, ConflictError, NotFoundError, OfflinePolicyError, new_runtime_id, validate_runtime_id, canonical_json, sha256_text, clock_point
from agent_brain import IntentValidator, RESERVED_PARAMETER_KEYS

ALLOWED_RESPONSE_KEYS = {"dialogue", "candidate_intent", "metadata"}
ALLOWED_CANDIDATE_KEYS = {"target_ref", "intent_type", "parameters", "metadata"}
SAFE_CONTEXT_PATHS = {"entity_kind","lifecycle","canonical_ref","data.name","data.role","data.location_ref","data.needs","data.goals","data.money","data.energy"}

FORBIDDEN_AUTHORITY_KEYS = {
    "world_state", "mutations", "consequences", "execution_class", "action_id", "event_id",
    "validation", "policy_id", "canonical_truth", "canon_mutation", "memory_write", "reputation_delta",
    "relationship_delta", "inventory_write", "money_write", "teleport", "spawn", "kill",
}

class LLMProvider(Protocol):
    provider_id: str
    def generate(self, request: dict[str, Any]) -> dict[str, Any]: ...

class ScriptedProvider:
    """Deterministic local provider for tests/demos; has no authority and performs no network I/O."""
    provider_id = "scripted-local-v1"
    def __init__(self, response: dict[str, Any] | None = None):
        self.response = copy.deepcopy(response or {"dialogue": "...", "candidate_intent": None})
        self.calls = 0
    def generate(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return copy.deepcopy(self.response)


def _safe_text(value: Any, name: str, max_len: int) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be string")
    value = value.strip()
    if len(value) > max_len:
        raise ValidationError(f"{name} exceeds max length {max_len}")
    return value


def _path_get(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    return copy.deepcopy(cur)


class ControlledLLMGateway:
    """Untrusted language boundary. It can create dialogue and candidate intents, never world truth."""
    SCHEMA_VERSION = 1

    def __init__(self, runtime: LivingRuntime, validator: IntentValidator, social: Any | None = None):
        self.runtime = runtime
        self.validator = validator
        self.social = social
        self.conn = runtime.conn
        self._lock = threading.RLock()
        self._providers: dict[str, LLMProvider] = {}
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self.runtime._write_lock:
            self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS llm_agent_profiles(
                profile_id TEXT PRIMARY KEY,
                world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                timeline_id TEXT NOT NULL,
                agent_ref TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                status TEXT NOT NULL,
                profile_json TEXT NOT NULL,
                profile_hash TEXT NOT NULL,
                UNIQUE(world_instance_id, agent_ref)
            );
            CREATE TABLE IF NOT EXISTS llm_requests(
                request_id TEXT PRIMARY KEY,
                world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                timeline_id TEXT NOT NULL,
                agent_ref TEXT NOT NULL,
                request_key TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                request_json TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                UNIQUE(world_instance_id, request_key)
            );
            CREATE TABLE IF NOT EXISTS llm_responses(
                response_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL UNIQUE REFERENCES llm_requests(request_id) ON DELETE CASCADE,
                raw_json TEXT NOT NULL,
                raw_hash TEXT NOT NULL,
                guard_status TEXT NOT NULL,
                guard_json TEXT NOT NULL,
                guard_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS llm_conversation_turns(
                turn_id TEXT PRIMARY KEY,
                world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                timeline_id TEXT NOT NULL,
                agent_ref TEXT NOT NULL,
                counterpart_ref TEXT,
                request_id TEXT NOT NULL REFERENCES llm_requests(request_id) ON DELETE CASCADE,
                user_text TEXT NOT NULL,
                dialogue_text TEXT NOT NULL,
                intent_id TEXT,
                recorded_day INTEGER NOT NULL,
                recorded_tick INTEGER NOT NULL,
                turn_json TEXT NOT NULL,
                turn_hash TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS llm_request_immutable BEFORE UPDATE ON llm_requests BEGIN SELECT RAISE(ABORT,'llm request immutable'); END;
            CREATE TRIGGER IF NOT EXISTS llm_response_immutable BEFORE UPDATE ON llm_responses BEGIN SELECT RAISE(ABORT,'llm response immutable'); END;
            CREATE TRIGGER IF NOT EXISTS llm_turn_immutable BEFORE UPDATE ON llm_conversation_turns BEGIN SELECT RAISE(ABORT,'llm turn immutable'); END;
            """)

    def bind_provider(self, provider: LLMProvider) -> None:
        pid = _safe_text(getattr(provider, "provider_id", None), "provider_id", 128)
        with self._lock:
            self._providers[pid] = provider

    def register_profile(self, world_instance_id: str, agent_ref: str, *, provider_id: str,
                         personality: str = "", allowed_intents: list[str] | None = None,
                         context_paths: list[str] | None = None, max_memories: int = 6,
                         max_dialogue_chars: int = 1600) -> dict[str, Any]:
        world = self.runtime.get_world(world_instance_id)
        validate_runtime_id(agent_ref)
        agent = self.runtime.get_entity(world_instance_id, agent_ref)
        if agent.get("entity_kind") != "AGENT":
            raise ValidationError("LLM profile requires AGENT")
        provider_id = _safe_text(provider_id, "provider_id", 128)
        personality = _safe_text(personality, "personality", 4000)
        allowed_intents = sorted(set(allowed_intents or []))
        if any(not isinstance(x, str) or not x.strip() or len(x) > 128 for x in allowed_intents):
            raise ValidationError("invalid allowed_intents")
        context_paths = context_paths or ["entity_kind", "lifecycle", "canonical_ref", "data.name", "data.role", "data.location_ref"]
        if any(not isinstance(x, str) or not x.strip() or len(x) > 128 for x in context_paths):
            raise ValidationError("invalid context_paths")
        unsafe = sorted(set(context_paths) - SAFE_CONTEXT_PATHS)
        if unsafe:
            raise ValidationError(f"unsafe context_paths: {unsafe}")
        if not isinstance(max_memories, int) or not 0 <= max_memories <= 20:
            raise ValidationError("max_memories must be 0..20")
        if not isinstance(max_dialogue_chars, int) or not 1 <= max_dialogue_chars <= 4000:
            raise ValidationError("max_dialogue_chars must be 1..4000")
        pid = new_runtime_id("llmprofile")
        body = {"profile_id":pid,"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"agent_ref":agent_ref,
                "provider_id":provider_id,"personality":personality,"allowed_intents":allowed_intents,"context_paths":context_paths,
                "max_memories":max_memories,"max_dialogue_chars":max_dialogue_chars,"status":"ACTIVE",
                "authority":"LANGUAGE_AND_CANDIDATE_INTENT_ONLY"}
        h=sha256_text(canonical_json(body))
        with self._lock, self.runtime._write_lock:
            self.conn.execute("INSERT INTO llm_agent_profiles VALUES(?,?,?,?,?,?,?,?)",(pid,world_instance_id,world["timeline_id"],agent_ref,provider_id,"ACTIVE",canonical_json(body),h))
        body["profile_hash"]=h
        return body

    def _profile(self, world_instance_id: str, agent_ref: str) -> dict[str, Any]:
        with self.runtime._write_lock:
            row=self.conn.execute("SELECT profile_json,profile_hash FROM llm_agent_profiles WHERE world_instance_id=? AND agent_ref=? AND status='ACTIVE'",(world_instance_id,agent_ref)).fetchone()
        if not row:
            raise NotFoundError("active LLM profile not found")
        if sha256_text(row["profile_json"]) != row["profile_hash"]:
            raise IntegrityError("LLM profile hash mismatch")
        return json.loads(row["profile_json"])

    def _public_entity_snapshot(self, world_instance_id: str, ref: str, paths: list[str]) -> dict[str, Any]:
        state=self.runtime.get_entity(world_instance_id, ref)
        out={"entity_runtime_id":state["entity_runtime_id"]}
        for p in paths:
            try: out[p]=_path_get(state,p)
            except KeyError: continue
        # Never expose protection/internal version as conversational authority unless explicitly present in safe paths.
        out.pop("protection",None); out.pop("version",None)
        return out

    def build_context(self, world_instance_id: str, agent_ref: str, *, user_text: str,
                      counterpart_ref: str | None = None) -> dict[str, Any]:
        world=self.runtime.get_world(world_instance_id)
        if world["simulation_mode"] == "ROUTINE_OFFLINE":
            raise OfflinePolicyError("LLM dialogue is blocked in ROUTINE_OFFLINE")
        profile=self._profile(world_instance_id,agent_ref)
        user_text=_safe_text(user_text,"user_text",4000)
        actor=self._public_entity_snapshot(world_instance_id,agent_ref,profile["context_paths"])
        counterpart=None
        if counterpart_ref is not None:
            validate_runtime_id(counterpart_ref)
            counterpart=self._public_entity_snapshot(world_instance_id,counterpart_ref,["entity_kind","lifecycle","canonical_ref"])
        memories=[]
        if self.social is not None and profile["max_memories"]:
            memories=self.social.recall_memories(world_instance_id,agent_ref,subject_ref=counterpart_ref,limit=profile["max_memories"])
            memories=[{"memory_type":m["memory_type"],"content":m["content"],"confidence":m["confidence"],"truth_status":m["truth_status"],"tags":m.get("tags",[])} for m in memories]
        return {
            "authority_labels":{"authoritative":["world","actor","counterpart"],"subjective":["memories"],"untrusted":["user_text"]},
            "world":{"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"simulation_mode":world["simulation_mode"],"clock":copy.deepcopy(world["clock_state"])},
            "actor":actor,"counterpart":counterpart,"memories":memories,"personality":profile["personality"],"user_text":user_text,
            "allowed_intents":profile["allowed_intents"],
            "output_contract":{"dialogue":"string","candidate_intent":"null or {intent_type,target_ref?,parameters?,metadata?}"},
            "hard_rule":"Dialogue may be mistaken or deceptive; only authoritative runtime state is world truth. Candidate intents require Canon Guard and Intent Validator."
        }

    def _guard_response(self, world_instance_id: str, agent_ref: str, profile: dict[str,Any], raw: Any) -> dict[str,Any]:
        failures=[]
        if not isinstance(raw,dict):
            return {"status":"REJECTED","failures":["RESPONSE_NOT_OBJECT"],"dialogue":"","candidate_intent":None}
        extra=set(raw)-ALLOWED_RESPONSE_KEYS
        if extra: failures.append("AUTHORITY_FIELDS:"+",".join(sorted(extra)))
        dialogue=raw.get("dialogue","")
        try: dialogue=_safe_text(dialogue,"dialogue",profile["max_dialogue_chars"])
        except ValidationError as exc: failures.append(str(exc)); dialogue=""
        cand=raw.get("candidate_intent")
        clean=None
        if cand is not None:
            if not isinstance(cand,dict): failures.append("CANDIDATE_NOT_OBJECT")
            else:
                cextra=set(cand)-ALLOWED_CANDIDATE_KEYS
                if cextra: failures.append("CANDIDATE_AUTHORITY_FIELDS:"+",".join(sorted(cextra)))
                intent_type=cand.get("intent_type")
                if not isinstance(intent_type,str) or intent_type not in profile["allowed_intents"]: failures.append("INTENT_NOT_ALLOWED")
                params=cand.get("parameters") or {}
                if not isinstance(params,dict): failures.append("PARAMETERS_NOT_OBJECT"); params={}
                bad=set(params) & (RESERVED_PARAMETER_KEYS|FORBIDDEN_AUTHORITY_KEYS)
                if bad: failures.append("RESERVED_PARAMETERS:"+",".join(sorted(bad)))
                meta=cand.get("metadata") or {}
                if not isinstance(meta,dict): failures.append("METADATA_NOT_OBJECT"); meta={}
                mbad=set(meta) & FORBIDDEN_AUTHORITY_KEYS
                if mbad: failures.append("RESERVED_METADATA:"+",".join(sorted(mbad)))
                target=cand.get("target_ref")
                if target is not None:
                    try:
                        validate_runtime_id(target); self.runtime.get_entity(world_instance_id,target)
                    except Exception: failures.append("TARGET_NOT_IN_WORLD")
                if not failures:
                    clean={"actor_ref":agent_ref,"target_ref":target,"intent_type":intent_type,"parameters":copy.deepcopy(params),"metadata":{"llm_guarded":True,**copy.deepcopy(meta)}}
        return {"status":"PASS" if not failures else "REJECTED","failures":failures,"dialogue":dialogue,"candidate_intent":clean}

    def converse(self, world_instance_id: str, agent_ref: str, *, user_text: str,
                 counterpart_ref: str | None = None, request_key: str | None = None,
                 auto_validate: bool = True) -> dict[str,Any]:
        with self._lock:
            return self._converse_locked(world_instance_id, agent_ref, user_text=user_text, counterpart_ref=counterpart_ref, request_key=request_key, auto_validate=auto_validate)

    def _converse_locked(self, world_instance_id: str, agent_ref: str, *, user_text: str,
                         counterpart_ref: str | None = None, request_key: str | None = None,
                         auto_validate: bool = True) -> dict[str,Any]:
        world=self.runtime.get_world(world_instance_id)
        profile=self._profile(world_instance_id,agent_ref)
        if world["simulation_mode"] == "ROUTINE_OFFLINE": raise OfflinePolicyError("LLM dialogue is blocked in ROUTINE_OFFLINE")
        request_key=request_key or new_runtime_id("llmreqkey")
        _safe_text(request_key,"request_key",256)
        with self._lock, self.runtime._write_lock:
            row=self.conn.execute("SELECT request_id,request_json,request_hash FROM llm_requests WHERE world_instance_id=? AND request_key=?",(world_instance_id,request_key)).fetchone()
            if row:
                if sha256_text(row["request_json"])!=row["request_hash"]: raise IntegrityError("LLM request hash mismatch")
                previous=json.loads(row["request_json"])
                if previous.get("agent_ref") != agent_ref or previous.get("counterpart_ref") != counterpart_ref or previous.get("context",{}).get("user_text") != user_text.strip():
                    raise ConflictError("request_key reused with different conversation input")
                rr=self.conn.execute("SELECT * FROM llm_responses WHERE request_id=?",(row["request_id"],)).fetchone()
                tr=self.conn.execute("SELECT turn_json,turn_hash FROM llm_conversation_turns WHERE request_id=?",(row["request_id"],)).fetchone()
                if not rr or not tr or sha256_text(tr["turn_json"])!=tr["turn_hash"]: raise IntegrityError("LLM replay records missing/corrupt")
                out=json.loads(tr["turn_json"]); out["idempotent_replay"]=True; return out
        provider=self._providers.get(profile["provider_id"])
        if provider is None: raise ConflictError("LLM provider is not bound")
        context=self.build_context(world_instance_id,agent_ref,user_text=user_text,counterpart_ref=counterpart_ref)
        rid=new_runtime_id("llmrequest")
        req={"request_id":rid,"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"agent_ref":agent_ref,"counterpart_ref":counterpart_ref,
             "request_key":request_key,"provider_id":profile["provider_id"],"context":context,"created_at":clock_point(world["clock_state"]["day"],world["clock_state"]["tick"])}
        rh=sha256_text(canonical_json(req))
        with self._lock,self.runtime._write_lock:
            self.conn.execute("INSERT INTO llm_requests VALUES(?,?,?,?,?,?,?,?)",(rid,world_instance_id,world["timeline_id"],agent_ref,request_key,profile["provider_id"],canonical_json(req),rh))
        try:
            raw=provider.generate(copy.deepcopy(req))
            guard=self._guard_response(world_instance_id,agent_ref,profile,raw)
        except Exception as exc:
            raw={"provider_error":type(exc).__name__}
            guard={"status":"REJECTED","failures":["PROVIDER_ERROR:"+type(exc).__name__],"dialogue":"","candidate_intent":None}
        raw_json=canonical_json(raw) if isinstance(raw,(dict,list,str,int,float,bool)) or raw is None else canonical_json({"invalid_repr":repr(raw)})
        raw_hash=sha256_text(raw_json); gh=sha256_text(canonical_json(guard)); respid=new_runtime_id("llmresponse")
        with self._lock,self.runtime._write_lock:
            self.conn.execute("INSERT INTO llm_responses VALUES(?,?,?,?,?,?,?)",(respid,rid,raw_json,raw_hash,guard["status"],canonical_json(guard),gh))
        intent=None; validation=None
        if guard["status"]=="PASS" and guard["candidate_intent"] is not None:
            intent=self.validator.ingest_llm_candidate(world_instance_id,guard["candidate_intent"])
            if auto_validate: validation=self.validator.validate_intent(intent["intent_id"])
        memory_id=None
        if self.social is not None and guard["status"]=="PASS":
            mem=self.social.record_memory(world_instance_id,agent_ref,memory_type="INTERACTION",source="COMMUNICATION",subject_ref=counterpart_ref,
                content={"request_id":rid,"counterpart_ref":counterpart_ref,"user_text":_safe_text(user_text,"user_text",4000),"dialogue":guard["dialogue"]},
                confidence=1.0,salience=55,emotional_weight=0,persistence="STANDARD",tags=["conversation","llm-mediated"],truth_status="UNKNOWN")
            memory_id=mem["memory_id"]
        now=self.runtime.get_clock(world_instance_id)
        turn={"turn_id":new_runtime_id("turn"),"request_id":rid,"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"agent_ref":agent_ref,"counterpart_ref":counterpart_ref,
              "user_text":_safe_text(user_text,"user_text",4000),"dialogue":guard["dialogue"],"guard_status":guard["status"],"guard_failures":guard["failures"],
              "intent_id":intent["intent_id"] if intent else None,"validation":validation,"memory_id":memory_id,"recorded_at":clock_point(now["day"],now["tick"])}
        th=sha256_text(canonical_json(turn))
        with self._lock,self.runtime._write_lock:
            self.conn.execute("INSERT INTO llm_conversation_turns VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(turn["turn_id"],world_instance_id,world["timeline_id"],agent_ref,counterpart_ref,rid,turn["user_text"],turn["dialogue"],turn["intent_id"],now["day"],now["tick"],canonical_json(turn),th))
        turn["turn_hash"]=th
        return turn

    def full_integrity_check(self, world_instance_id: str) -> dict[str,Any]:
        failures=[]
        specs=[("llm_agent_profiles","profile_json","profile_hash","profile_id"),("llm_requests","request_json","request_hash","request_id"),("llm_conversation_turns","turn_json","turn_hash","turn_id")]
        with self._lock,self.runtime._write_lock:
            for table,jc,hc,idc in specs:
                for r in self.conn.execute(f"SELECT * FROM {table} WHERE world_instance_id=?",(world_instance_id,)).fetchall():
                    if sha256_text(r[jc])!=r[hc]: failures.append(f"{table}:HASH_MISMATCH:{r[idc]}")
            for r in self.conn.execute("SELECT s.* FROM llm_responses s JOIN llm_requests q ON q.request_id=s.request_id WHERE q.world_instance_id=?",(world_instance_id,)).fetchall():
                if sha256_text(r["raw_json"])!=r["raw_hash"]: failures.append(f"llm_responses:RAW_HASH:{r['response_id']}")
                if sha256_text(r["guard_json"])!=r["guard_hash"]: failures.append(f"llm_responses:GUARD_HASH:{r['response_id']}")
        return {"status":"PASS" if not failures else "FAIL","failures":failures}
