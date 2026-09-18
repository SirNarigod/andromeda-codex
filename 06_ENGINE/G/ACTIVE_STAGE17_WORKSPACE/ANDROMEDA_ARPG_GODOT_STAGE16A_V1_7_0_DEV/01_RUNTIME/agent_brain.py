from __future__ import annotations

import copy
import json
import threading
from typing import Any

from living_runtime import (
    LivingRuntime,
    ValidationError,
    IntegrityError,
    ConflictError,
    NotFoundError,
    OfflinePolicyError,
    new_runtime_id,
    validate_runtime_id,
    canonical_json,
    sha256_text,
    clock_point,
)

ALLOWED_INTENT_SOURCES = {
    "AGENT_BRAIN", "PLAYER_INPUT", "LLM_CANDIDATE", "SYSTEM_ROUTINE", "SYSTEM_RECOVERY"
}
RESERVED_PARAMETER_KEYS = {
    "consequences", "mutations", "world_state", "execution_class", "precondition_snapshot",
    "action_id", "event_id", "causality", "status", "world_instance_id", "timeline_id",
}
ALLOWED_OFFLINE_POLICIES = {"ACTIVE_ONLY", "ROUTINE_SAFE"}
ALLOWED_SPATIAL_POLICIES = {"NONE", "SAME_LOCATION"}
ALLOWED_IMPACTS = {"DEATH", "WORLD_MUTATION", "RELATIONSHIP_CHANGE", "PERMANENT_INJURY"}
ALLOWED_CONSEQUENCE_OPS = {"SET", "TRANSITION", "INCREMENT", "DECREMENT"}
ALLOWED_PERCEPTION_SOURCES = {"SENSORY", "MEMORY", "COMMUNICATION", "SYSTEM_OBSERVATION"}
ALLOWED_TARGET_STRATEGIES = {"SELF", "PERCEPTION", "NONE"}


def _path_get(obj: Any, path: str, *, default: Any = ...):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            if default is ...:
                raise ValidationError(f"field path not found: {path}")
            return default
        cur = cur[part]
    return cur


def _path_present(obj: Any, path: str) -> bool:
    try:
        _path_get(obj, path)
        return True
    except ValidationError:
        return False


def _numeric(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValidationError(f"{name} must be numeric")
    return float(value)


def _bounded_number(value: Any, name: str, lo: float, hi: float) -> float:
    value = _numeric(value, name)
    if value < lo or value > hi:
        raise ValidationError(f"{name} must be between {lo} and {hi}")
    return value


def _ref_kind(state: dict[str, Any]) -> str:
    return str(state.get("entity_kind", ""))


class IntentValidator:
    """Deterministic authority gate between untrusted intent and authoritative action."""

    SCHEMA_VERSION = 1

    def __init__(self, runtime: LivingRuntime) -> None:
        self.runtime = runtime
        self.conn = runtime.conn
        self._lock = threading.RLock()
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self.runtime._write_lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS action_policies(
                    policy_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    policy_key TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('ACTIVE','DISABLED')),
                    policy_json TEXT NOT NULL,
                    policy_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id, policy_key)
                );
                CREATE INDEX IF NOT EXISTS idx_action_policy_type ON action_policies(world_instance_id, action_type, status);

                CREATE TABLE IF NOT EXISTS intents(
                    intent_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    actor_ref TEXT NOT NULL,
                    target_ref TEXT,
                    intent_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('CANDIDATE','VALIDATING','VALIDATED','REJECTED','EXPIRED','CONSUMED')),
                    created_day INTEGER NOT NULL,
                    created_tick INTEGER NOT NULL,
                    candidate_json TEXT NOT NULL,
                    candidate_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_intents_actor ON intents(world_instance_id, actor_ref, status);

                CREATE TABLE IF NOT EXISTS intent_validations(
                    validation_id TEXT PRIMARY KEY,
                    intent_id TEXT NOT NULL UNIQUE REFERENCES intents(intent_id) ON DELETE RESTRICT,
                    policy_id TEXT,
                    status TEXT NOT NULL CHECK(status IN ('PASS','REJECTED')),
                    action_id TEXT,
                    validation_json TEXT NOT NULL,
                    validation_hash TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS intent_executions(
                    execution_id TEXT PRIMARY KEY,
                    intent_id TEXT NOT NULL UNIQUE REFERENCES intents(intent_id) ON DELETE RESTRICT,
                    action_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    result_hash TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS intent_candidate_immutable
                BEFORE UPDATE OF candidate_json,candidate_hash,actor_ref,target_ref,intent_type,source,created_day,created_tick ON intents
                BEGIN SELECT RAISE(ABORT, 'intent candidate is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS intent_no_delete
                BEFORE DELETE ON intents
                BEGIN SELECT RAISE(ABORT, 'intent history is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS validation_no_update
                BEFORE UPDATE ON intent_validations
                BEGIN SELECT RAISE(ABORT, 'intent validation is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS validation_no_delete
                BEFORE DELETE ON intent_validations
                BEGIN SELECT RAISE(ABORT, 'intent validation is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS execution_no_update
                BEFORE UPDATE ON intent_executions
                BEGIN SELECT RAISE(ABORT, 'intent execution is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS execution_no_delete
                BEFORE DELETE ON intent_executions
                BEGIN SELECT RAISE(ABORT, 'intent execution is immutable'); END;
                """
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('agent_intent_schema_version',?)",
                (str(self.SCHEMA_VERSION),),
            )

    def _resolve_runtime_target(self, world_instance_id: str, ref: str) -> dict[str, Any]:
        if not isinstance(ref, str) or not ref:
            raise ValidationError("target_ref required")
        if ref.startswith("rt:"):
            return self.runtime.get_entity(world_instance_id, ref)
        if not self.runtime.canonical_ref_resolves(ref):
            raise ValidationError(f"unknown canonical target: {ref}")
        with self.runtime._write_lock:
            rows = self.conn.execute(
                "SELECT entity_runtime_id FROM entity_states WHERE world_instance_id=? AND canonical_ref=? ORDER BY entity_runtime_id",
                (world_instance_id, ref),
            ).fetchall()
        if len(rows) == 0:
            raise NotFoundError(f"canonical target is not materialized in this world: {ref}")
        if len(rows) > 1:
            raise ConflictError(f"canonical target is ambiguous in this world: {ref}")
        return self.runtime.get_entity(world_instance_id, rows[0]["entity_runtime_id"])

    def register_policy(self, world_instance_id: str, policy: dict[str, Any]) -> dict[str, Any]:
        world = self.runtime.get_world(world_instance_id)
        p = copy.deepcopy(policy)
        required = ["policy_key", "action_type", "allowed_sources", "actor_kinds", "offline_policy", "consequence_templates"]
        missing = [k for k in required if k not in p]
        if missing:
            raise ValidationError(f"missing policy fields: {missing}")
        if not isinstance(p["policy_key"], str) or not p["policy_key"].strip():
            raise ValidationError("policy_key required")
        if not isinstance(p["action_type"], str) or not p["action_type"].strip():
            raise ValidationError("action_type required")
        if not isinstance(p["allowed_sources"], list) or not p["allowed_sources"]:
            raise ValidationError("allowed_sources must be non-empty list")
        if any(x not in ALLOWED_INTENT_SOURCES for x in p["allowed_sources"]):
            raise ValidationError("policy has invalid intent source")
        if not isinstance(p["actor_kinds"], list) or not p["actor_kinds"] or any(not isinstance(x, str) or not x for x in p["actor_kinds"]):
            raise ValidationError("actor_kinds must be non-empty strings")
        p.setdefault("target_required", False)
        p.setdefault("target_kinds", [])
        p.setdefault("actor_state_equals", {})
        p.setdefault("target_state_equals", {})
        p.setdefault("resource_requirements", [])
        p.setdefault("target_resource_requirements", [])
        p.setdefault("spatial_policy", "NONE")
        p.setdefault("actor_location_path", "data.location_ref")
        p.setdefault("target_location_path", "data.location_ref")
        p.setdefault("protection_impacts", [])
        p.setdefault("cooldown_ticks", 0)
        p.setdefault("status", "ACTIVE")
        p.setdefault("parameter_schema", {})
        if p["offline_policy"] not in ALLOWED_OFFLINE_POLICIES:
            raise ValidationError("invalid offline_policy")
        if p["spatial_policy"] not in ALLOWED_SPATIAL_POLICIES:
            raise ValidationError("invalid spatial_policy")
        if p["status"] not in {"ACTIVE", "DISABLED"}:
            raise ValidationError("invalid policy status")
        if not isinstance(p["target_required"], bool):
            raise ValidationError("target_required must be boolean")
        if not isinstance(p["target_kinds"], list) or any(not isinstance(x, str) or not x for x in p["target_kinds"]):
            raise ValidationError("target_kinds invalid")
        if not isinstance(p["actor_state_equals"], dict) or not isinstance(p["target_state_equals"], dict):
            raise ValidationError("state_equals must be objects")
        if any(x not in ALLOWED_IMPACTS for x in p["protection_impacts"]):
            raise ValidationError("invalid protection impact")
        if not isinstance(p["cooldown_ticks"], int) or p["cooldown_ticks"] < 0:
            raise ValidationError("cooldown_ticks must be nonnegative integer")
        if not isinstance(p["parameter_schema"], dict):
            raise ValidationError("parameter_schema must be object")
        for name, spec in p["parameter_schema"].items():
            if not isinstance(name, str) or name in RESERVED_PARAMETER_KEYS or not isinstance(spec, dict):
                raise ValidationError("invalid parameter schema")
            if spec.get("type") not in {"string", "number", "integer", "boolean"}:
                raise ValidationError("unsupported parameter type")
            if "required" in spec and not isinstance(spec["required"], bool):
                raise ValidationError("parameter required flag must be boolean")
        for requirement_key, scope in [("resource_requirements", "ACTOR"), ("target_resource_requirements", "TARGET")]:
            reqs = p[requirement_key]
            if not isinstance(reqs, list):
                raise ValidationError(f"{requirement_key} must be list")
            if scope == "TARGET" and reqs and not p["target_required"]:
                raise ValidationError("target resource requirements require target_required policy")
            for r in reqs:
                if not isinstance(r, dict) or not isinstance(r.get("field_path"), str) or not r["field_path"]:
                    raise ValidationError("invalid resource requirement")
                for fixed_key, param_key in [("min_value", "min_from_parameter"), ("consume_amount", "consume_from_parameter")]:
                    if fixed_key in r and param_key in r:
                        raise ValidationError("resource amount cannot be both fixed and parameter-derived")
                    if param_key in r:
                        pname = r[param_key]
                        if not isinstance(pname, str) or pname not in p["parameter_schema"]:
                            raise ValidationError("resource requirement references unknown parameter")
                        if p["parameter_schema"][pname]["type"] not in {"number", "integer"}:
                            raise ValidationError("resource parameter must be numeric")
                minimum = _numeric(r.get("min_value", 0), "resource min_value") if "min_from_parameter" not in r else None
                consume = _numeric(r.get("consume_amount", 0), "resource consume_amount") if "consume_from_parameter" not in r else None
                if minimum is not None and minimum < 0:
                    raise ValidationError("resource minimum cannot be negative")
                if consume is not None and consume < 0:
                    raise ValidationError("resource consume cannot be negative")
                if minimum is not None and consume is not None and consume > minimum:
                    raise ValidationError("resource consume cannot exceed minimum")
        if not isinstance(p["consequence_templates"], list):
            raise ValidationError("consequence_templates must be list")
        for c in p["consequence_templates"]:
            if not isinstance(c, dict) or c.get("target") not in {"ACTOR", "TARGET"}:
                raise ValidationError("consequence target must be ACTOR or TARGET")
            if c.get("target") == "TARGET" and not p["target_required"]:
                raise ValidationError("TARGET consequence requires target_required policy")
            if c.get("operation") not in ALLOWED_CONSEQUENCE_OPS:
                raise ValidationError("unsupported policy consequence operation")
            if not isinstance(c.get("field_path"), str) or not c["field_path"]:
                raise ValidationError("consequence field_path required")
            if "field_path_from_parameter" in c or "target_ref" in c:
                raise ValidationError("dynamic mutation paths/targets are prohibited")
            if c["operation"] in {"SET", "TRANSITION"}:
                if "value" not in c and "value_from_parameter" not in c:
                    raise ValidationError("SET/TRANSITION consequence requires value")
            if c["operation"] in {"INCREMENT", "DECREMENT"}:
                if "amount" not in c and "amount_from_parameter" not in c:
                    raise ValidationError("increment/decrement consequence requires amount")
                if "amount" in c and _numeric(c["amount"], "consequence amount") < 0:
                    raise ValidationError("consequence amount cannot be negative")
        inferred_impacts = set(p["protection_impacts"])
        for c in p["consequence_templates"]:
            if c.get("target") != "TARGET" or c.get("field_path") != "lifecycle" or c.get("operation") not in {"SET", "TRANSITION"}:
                continue
            if c.get("value") == "DEAD":
                inferred_impacts.add("DEATH")
            if c.get("value") == "DESTROYED":
                inferred_impacts.add("WORLD_MUTATION")
        p["protection_impacts"] = sorted(inferred_impacts)
        policy_id = p.get("policy_id") or new_runtime_id("policy")
        validate_runtime_id(policy_id, "policy")
        body = {
            "policy_id": policy_id,
            "world_instance_id": world_instance_id,
            "timeline_id": world["timeline_id"],
            **p,
        }
        phash = sha256_text(canonical_json(body))
        with self._lock, self.runtime._write_lock:
            # One active policy per action type avoids ambiguous authority.
            if body["status"] == "ACTIVE":
                existing = self.conn.execute(
                    "SELECT policy_id FROM action_policies WHERE world_instance_id=? AND action_type=? AND status='ACTIVE'",
                    (world_instance_id, body["action_type"]),
                ).fetchone()
                if existing:
                    raise ConflictError(f"active action policy already exists for {body['action_type']}")
            self.conn.execute(
                "INSERT INTO action_policies VALUES(?,?,?,?,?,?,?,?)",
                (policy_id, world_instance_id, world["timeline_id"], body["policy_key"], body["action_type"], body["status"], canonical_json(body), phash),
            )
        body["policy_hash"] = phash
        return body

    def set_policy_status(self, policy_id: str, status: str) -> None:
        validate_runtime_id(policy_id, "policy")
        if status not in {"ACTIVE", "DISABLED"}:
            raise ValidationError("invalid policy status")
        with self._lock, self.runtime._write_lock:
            row = self.conn.execute("SELECT policy_json,world_instance_id,action_type FROM action_policies WHERE policy_id=?", (policy_id,)).fetchone()
            if not row:
                raise NotFoundError("policy not found")
            if status == "ACTIVE":
                conflict = self.conn.execute(
                    "SELECT policy_id FROM action_policies WHERE world_instance_id=? AND action_type=? AND status='ACTIVE' AND policy_id<>?",
                    (row["world_instance_id"], row["action_type"], policy_id),
                ).fetchone()
                if conflict:
                    raise ConflictError("another active policy exists for this action type")
            body = json.loads(row["policy_json"])
            body["status"] = status
            self.conn.execute(
                "UPDATE action_policies SET status=?,policy_json=?,policy_hash=? WHERE policy_id=?",
                (status, canonical_json(body), sha256_text(canonical_json(body)), policy_id),
            )

    def _get_policy_for_action(self, world_instance_id: str, action_type: str) -> dict[str, Any]:
        with self.runtime._write_lock:
            rows = self.conn.execute(
                "SELECT policy_json,policy_hash FROM action_policies WHERE world_instance_id=? AND action_type=? AND status='ACTIVE'",
                (world_instance_id, action_type),
            ).fetchall()
        if len(rows) == 0:
            raise ValidationError(f"no active action policy for {action_type}")
        if len(rows) > 1:
            raise IntegrityError(f"multiple active action policies for {action_type}")
        if sha256_text(rows[0]["policy_json"]) != rows[0]["policy_hash"]:
            raise IntegrityError("action policy hash mismatch")
        return json.loads(rows[0]["policy_json"])

    def _validate_parameters(self, parameters: dict[str, Any], schema: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        for key in parameters:
            if key in RESERVED_PARAMETER_KEYS:
                reasons.append(f"RESERVED_PARAMETER:{key}")
            elif key not in schema:
                reasons.append(f"UNKNOWN_PARAMETER:{key}")
        for key, spec in schema.items():
            if spec.get("required") and key not in parameters:
                reasons.append(f"MISSING_PARAMETER:{key}")
                continue
            if key not in parameters:
                continue
            value = parameters[key]
            typ = spec["type"]
            valid = (
                (typ == "string" and isinstance(value, str)) or
                (typ == "number" and isinstance(value, (int, float)) and not isinstance(value, bool)) or
                (typ == "integer" and isinstance(value, int) and not isinstance(value, bool)) or
                (typ == "boolean" and isinstance(value, bool))
            )
            if not valid:
                reasons.append(f"PARAMETER_TYPE:{key}")
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if "min" in spec and value < spec["min"]:
                    reasons.append(f"PARAMETER_MIN:{key}")
                if "max" in spec and value > spec["max"]:
                    reasons.append(f"PARAMETER_MAX:{key}")
            if isinstance(value, str) and "enum" in spec and value not in spec["enum"]:
                reasons.append(f"PARAMETER_ENUM:{key}")
        return reasons

    def submit_intent(
        self,
        world_instance_id: str,
        *,
        actor_ref: str,
        intent_type: str,
        parameters: dict[str, Any] | None = None,
        target_ref: str | None = None,
        source: str = "AGENT_BRAIN",
        intent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        world = self.runtime.get_world(world_instance_id)
        if source not in ALLOWED_INTENT_SOURCES:
            raise ValidationError("invalid intent source")
        if not isinstance(intent_type, str) or not intent_type.strip():
            raise ValidationError("intent_type required")
        if not isinstance(parameters or {}, dict):
            raise ValidationError("parameters must be object")
        validate_runtime_id(actor_ref)
        self.runtime.get_entity(world_instance_id, actor_ref)
        if target_ref is not None and (not isinstance(target_ref, str) or not target_ref):
            raise ValidationError("invalid target_ref")
        intent_id = intent_id or new_runtime_id("intent")
        validate_runtime_id(intent_id, "intent")
        now = self.runtime.get_clock(world_instance_id)
        body = {
            "intent_id": intent_id,
            "world_instance_id": world_instance_id,
            "timeline_id": world["timeline_id"],
            "actor_ref": actor_ref,
            "target_ref": target_ref,
            "intent_type": intent_type,
            "parameters": copy.deepcopy(parameters or {}),
            "source": source,
            "created_at": clock_point(now["day"], now["tick"]),
            "status": "CANDIDATE",
            "metadata": copy.deepcopy(metadata or {}),
        }
        ihash = sha256_text(canonical_json(body))
        with self._lock, self.runtime._write_lock:
            self.conn.execute(
                "INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (intent_id, world_instance_id, world["timeline_id"], actor_ref, target_ref, intent_type, source, "CANDIDATE", now["day"], now["tick"], canonical_json(body), ihash),
            )
        body["candidate_hash"] = ihash
        return body

    def ingest_llm_candidate(self, world_instance_id: str, candidate: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(candidate, dict):
            raise ValidationError("LLM candidate must be object")
        allowed = {"actor_ref", "target_ref", "intent_type", "parameters", "metadata"}
        extra = set(candidate) - allowed
        if extra:
            raise ValidationError(f"LLM candidate contains authority fields: {sorted(extra)}")
        return self.submit_intent(
            world_instance_id,
            actor_ref=candidate.get("actor_ref"),
            target_ref=candidate.get("target_ref"),
            intent_type=candidate.get("intent_type"),
            parameters=candidate.get("parameters") or {},
            metadata={"llm_untrusted": True, **copy.deepcopy(candidate.get("metadata") or {})},
            source="LLM_CANDIDATE",
        )

    def get_intent(self, intent_id: str) -> dict[str, Any]:
        validate_runtime_id(intent_id, "intent")
        with self.runtime._write_lock:
            row = self.conn.execute("SELECT * FROM intents WHERE intent_id=?", (intent_id,)).fetchone()
        if not row:
            raise NotFoundError("intent not found")
        if sha256_text(row["candidate_json"]) != row["candidate_hash"]:
            raise IntegrityError("intent candidate hash mismatch")
        body = json.loads(row["candidate_json"])
        body["status"] = row["status"]
        body["candidate_hash"] = row["candidate_hash"]
        return body

    def _reject(self, intent: dict[str, Any], policy_id: str | None, reasons: list[str], checks: list[dict[str, Any]]) -> dict[str, Any]:
        result = {
            "validation_id": new_runtime_id("validation"),
            "intent_id": intent["intent_id"],
            "policy_id": policy_id,
            "status": "REJECTED",
            "reasons": reasons,
            "checks": checks,
            "action": None,
        }
        h = sha256_text(canonical_json(result))
        with self.runtime._write_lock:
            self.runtime._begin()
            try:
                self.conn.execute(
                    "INSERT INTO intent_validations VALUES(?,?,?,?,?,?,?)",
                    (result["validation_id"], intent["intent_id"], policy_id, "REJECTED", None, canonical_json(result), h),
                )
                self.conn.execute("UPDATE intents SET status='REJECTED' WHERE intent_id=?", (intent["intent_id"],))
                self.runtime._commit()
            except Exception:
                self.runtime._rollback()
                raise
        result["validation_hash"] = h
        return result

    def _requirement_amount(self, requirement: dict[str, Any], parameters: dict[str, Any], fixed_key: str, param_key: str) -> float:
        if param_key in requirement:
            pname = requirement[param_key]
            if pname not in parameters:
                raise ValidationError(f"resource parameter missing: {pname}")
            value = _numeric(parameters[pname], f"resource parameter:{pname}")
        else:
            value = _numeric(requirement.get(fixed_key, 0), f"resource {fixed_key}")
        if value < 0:
            raise ValidationError("resource amount cannot be negative")
        return value

    def validate_intent(self, intent_id: str) -> dict[str, Any]:
        with self._lock, self.runtime._write_lock:
            row = self.conn.execute("SELECT * FROM intents WHERE intent_id=?", (intent_id,)).fetchone()
            if not row:
                raise NotFoundError("intent not found")
            existing = self.conn.execute("SELECT validation_json,validation_hash FROM intent_validations WHERE intent_id=?", (intent_id,)).fetchone()
            if existing:
                if sha256_text(existing["validation_json"]) != existing["validation_hash"]:
                    raise IntegrityError("intent validation hash mismatch")
                out = json.loads(existing["validation_json"])
                out["validation_hash"] = existing["validation_hash"]
                out["idempotent_replay"] = True
                return out
            if sha256_text(row["candidate_json"]) != row["candidate_hash"]:
                raise IntegrityError("intent candidate hash mismatch")
            intent = json.loads(row["candidate_json"])
            if row["status"] != "CANDIDATE":
                raise ConflictError(f"intent cannot validate from status {row['status']}")
            checks: list[dict[str, Any]] = []
            reasons: list[str] = []
            policy: dict[str, Any] | None = None
            try:
                policy = self._get_policy_for_action(intent["world_instance_id"], intent["intent_type"])
                checks.append({"check": "POLICY_RESOLVES", "status": "PASS"})
            except IntegrityError:
                # Corruption is not a normal policy rejection; fail closed and surface it.
                raise
            except ValidationError as exc:
                checks.append({"check": "POLICY_RESOLVES", "status": "FAIL", "detail": str(exc)})
                reasons.append("POLICY_NOT_AVAILABLE")
            if policy is None:
                return self._reject(intent, None, reasons, checks)

            policy_id = policy["policy_id"]
            actor = self.runtime.get_entity(intent["world_instance_id"], intent["actor_ref"])
            if actor.get("lifecycle") != "ACTIVE":
                reasons.append("ACTOR_NOT_ACTIVE")
                checks.append({"check": "ACTOR_ACTIVE", "status": "FAIL"})
            else:
                checks.append({"check": "ACTOR_ACTIVE", "status": "PASS"})
            if _ref_kind(actor) not in policy["actor_kinds"]:
                reasons.append("ACTOR_KIND_NOT_ALLOWED")
                checks.append({"check": "ACTOR_KIND", "status": "FAIL"})
            else:
                checks.append({"check": "ACTOR_KIND", "status": "PASS"})
            if intent["source"] not in policy["allowed_sources"]:
                reasons.append("SOURCE_NOT_ALLOWED")
                checks.append({"check": "SOURCE_ALLOWED", "status": "FAIL"})
            else:
                checks.append({"check": "SOURCE_ALLOWED", "status": "PASS"})

            param_reasons = self._validate_parameters(intent["parameters"], policy["parameter_schema"])
            if param_reasons:
                reasons.extend(param_reasons)
                checks.append({"check": "PARAMETERS", "status": "FAIL", "detail": param_reasons})
            else:
                checks.append({"check": "PARAMETERS", "status": "PASS"})

            target: dict[str, Any] | None = None
            if policy["target_required"]:
                if not intent.get("target_ref"):
                    reasons.append("TARGET_REQUIRED")
                    checks.append({"check": "TARGET_RESOLVES", "status": "FAIL"})
                else:
                    try:
                        target = self._resolve_runtime_target(intent["world_instance_id"], intent["target_ref"])
                        checks.append({"check": "TARGET_RESOLVES", "status": "PASS", "resolved_ref": target["entity_runtime_id"]})
                    except (ValidationError, NotFoundError, ConflictError) as exc:
                        reasons.append("TARGET_NOT_RESOLVED")
                        checks.append({"check": "TARGET_RESOLVES", "status": "FAIL", "detail": str(exc)})
                if target is not None and policy["target_kinds"] and _ref_kind(target) not in policy["target_kinds"]:
                    reasons.append("TARGET_KIND_NOT_ALLOWED")
                    checks.append({"check": "TARGET_KIND", "status": "FAIL"})
                elif target is not None:
                    checks.append({"check": "TARGET_KIND", "status": "PASS"})
            elif intent.get("target_ref") is not None:
                reasons.append("UNEXPECTED_TARGET")
                checks.append({"check": "TARGET_POLICY", "status": "FAIL"})

            world = self.runtime.get_world(intent["world_instance_id"])
            if world["simulation_mode"] == "ROUTINE_OFFLINE":
                # Authorial rule: only explicit system routine/recovery may continue offline.
                if policy["offline_policy"] != "ROUTINE_SAFE" or intent["source"] not in {"SYSTEM_ROUTINE", "SYSTEM_RECOVERY"}:
                    reasons.append("OFFLINE_POLICY_BLOCKED")
                    checks.append({"check": "OFFLINE_POLICY", "status": "FAIL"})
                else:
                    checks.append({"check": "OFFLINE_POLICY", "status": "PASS"})
            else:
                checks.append({"check": "OFFLINE_POLICY", "status": "PASS"})

            for path, expected in policy["actor_state_equals"].items():
                actual = _path_get(actor, path, default=None)
                if actual != expected:
                    reasons.append(f"ACTOR_PRECONDITION:{path}")
                    checks.append({"check": "ACTOR_PRECONDITION", "path": path, "status": "FAIL"})
                else:
                    checks.append({"check": "ACTOR_PRECONDITION", "path": path, "status": "PASS"})
            if target is not None:
                for path, expected in policy["target_state_equals"].items():
                    actual = _path_get(target, path, default=None)
                    if actual != expected:
                        reasons.append(f"TARGET_PRECONDITION:{path}")
                        checks.append({"check": "TARGET_PRECONDITION", "path": path, "status": "FAIL"})
                    else:
                        checks.append({"check": "TARGET_PRECONDITION", "path": path, "status": "PASS"})

            for scope, holder, reqs in [("ACTOR", actor, policy["resource_requirements"]), ("TARGET", target, policy["target_resource_requirements"])]:
                if holder is None and reqs:
                    reasons.append(f"{scope}_RESOURCE_TARGET_MISSING")
                    continue
                for r in reqs:
                    actual = _path_get(holder, r["field_path"], default=None)
                    try:
                        minimum = self._requirement_amount(r, intent["parameters"], "min_value", "min_from_parameter")
                        consume = self._requirement_amount(r, intent["parameters"], "consume_amount", "consume_from_parameter")
                    except ValidationError as exc:
                        reasons.append(f"RESOURCE_PARAMETER_INVALID:{r['field_path']}")
                        checks.append({"check": f"{scope}_RESOURCE", "path": r["field_path"], "status": "FAIL", "detail": str(exc)})
                        continue
                    if consume > minimum:
                        reasons.append(f"RESOURCE_REQUIREMENT_INVALID:{r['field_path']}")
                        checks.append({"check": f"{scope}_RESOURCE", "path": r["field_path"], "status": "FAIL"})
                    elif not isinstance(actual, (int, float)) or isinstance(actual, bool) or actual < minimum:
                        reasons.append(f"RESOURCE_INSUFFICIENT:{r['field_path']}")
                        checks.append({"check": f"{scope}_RESOURCE", "path": r["field_path"], "status": "FAIL"})
                    else:
                        checks.append({"check": f"{scope}_RESOURCE", "path": r["field_path"], "status": "PASS"})

            if policy["spatial_policy"] == "SAME_LOCATION" and target is not None:
                aloc = _path_get(actor, policy["actor_location_path"], default=None)
                tloc = _path_get(target, policy["target_location_path"], default=None)
                if aloc is None or tloc is None or aloc != tloc:
                    reasons.append("SPATIAL_CONSTRAINT")
                    checks.append({"check": "SPATIAL", "status": "FAIL", "actor_location": aloc, "target_location": tloc})
                else:
                    checks.append({"check": "SPATIAL", "status": "PASS"})

            if target is not None and policy["protection_impacts"]:
                protection = target.get("protection")
                if not isinstance(protection, dict):
                    protection = _path_get(target, "data.protection", default={})
                protection = protection if isinstance(protection, dict) else {}
                blocked = False
                for impact in policy["protection_impacts"]:
                    if impact == "DEATH" and protection.get("death") in {"BLOCKED", "STORY_AUTHORITY_ONLY"}:
                        blocked = True
                        reasons.append("NARRATIVE_PROTECTION_DEATH")
                    elif impact == "WORLD_MUTATION" and protection.get("world_mutation_scope") in {"BLOCKED", "STORY_AUTHORITY_ONLY"}:
                        blocked = True
                        reasons.append("NARRATIVE_PROTECTION_WORLD_MUTATION")
                    elif impact == "RELATIONSHIP_CHANGE" and protection.get("relationship_change") in {"BLOCKED", "STORY_AUTHORITY_ONLY"}:
                        blocked = True
                        reasons.append("NARRATIVE_PROTECTION_RELATIONSHIP")
                    elif impact == "PERMANENT_INJURY" and protection.get("permanent_injury") in {"BLOCKED", "STORY_AUTHORITY_ONLY"}:
                        blocked = True
                        reasons.append("NARRATIVE_PROTECTION_INJURY")
                checks.append({"check": "NARRATIVE_PROTECTION", "status": "FAIL" if blocked else "PASS"})

            clock = world["clock_state"]
            now_abs = clock["day"] * clock["ticks_per_day"] + clock["tick"]
            cooldown_key = sha256_text(policy["policy_key"])[:16]
            cooldown_path = f"data.agent_runtime.cooldowns.cd_{cooldown_key}"
            cooldown_until = _path_get(actor, cooldown_path, default=0)
            if not isinstance(cooldown_until, int):
                reasons.append("COOLDOWN_STATE_INVALID")
                checks.append({"check": "COOLDOWN", "status": "FAIL"})
            elif cooldown_until > now_abs:
                reasons.append("COOLDOWN_ACTIVE")
                checks.append({"check": "COOLDOWN", "status": "FAIL", "until_tick": cooldown_until})
            else:
                checks.append({"check": "COOLDOWN", "status": "PASS"})

            if reasons:
                return self._reject(intent, policy_id, reasons, checks)

            action_id = new_runtime_id("action")
            entity_versions = {actor["entity_runtime_id"]: actor["version"]}
            resolved_target_ref = None
            if target is not None:
                entity_versions[target["entity_runtime_id"]] = target["version"]
                resolved_target_ref = target["entity_runtime_id"]
            action = {
                "action_id": action_id,
                "intent_id": intent_id,
                "world_instance_id": intent["world_instance_id"],
                "timeline_id": intent["timeline_id"],
                "actor_ref": actor["entity_runtime_id"],
                "action_type": policy["action_type"],
                "parameters": {**copy.deepcopy(intent["parameters"]), "validated_target_ref": resolved_target_ref},
                "precondition_snapshot": {"entity_versions": entity_versions},
                "idempotency_key": f"intent:{intent_id}",
                "created_at": copy.deepcopy(intent["created_at"]),
                "status": "SCHEDULED",
                "execution_class": "ROUTINE_SAFE" if policy["offline_policy"] == "ROUTINE_SAFE" else "ACTIVE_ONLY",
                "source": intent["source"],
                "policy_id": policy_id,
                "policy_hash": sha256_text(canonical_json(policy)),
            }
            result = {
                "validation_id": new_runtime_id("validation"),
                "intent_id": intent_id,
                "policy_id": policy_id,
                "status": "PASS",
                "reasons": [],
                "checks": checks,
                "action": action,
            }
            h = sha256_text(canonical_json(result))
            self.runtime._begin()
            try:
                self.conn.execute(
                    "INSERT INTO intent_validations VALUES(?,?,?,?,?,?,?)",
                    (result["validation_id"], intent_id, policy_id, "PASS", action_id, canonical_json(result), h),
                )
                self.conn.execute("UPDATE intents SET status='VALIDATED' WHERE intent_id=?", (intent_id,))
                self.runtime._commit()
            except Exception:
                self.runtime._rollback()
                raise
            result["validation_hash"] = h
            return result

    def _resolve_template_value(self, template: dict[str, Any], parameters: dict[str, Any], key: str) -> Any:
        direct_key = key
        from_key = f"{key}_from_parameter"
        if direct_key in template:
            return copy.deepcopy(template[direct_key])
        pname = template.get(from_key)
        if not isinstance(pname, str) or pname not in parameters:
            raise ValidationError(f"template parameter not available: {pname}")
        return copy.deepcopy(parameters[pname])

    def _materialize_consequences(self, intent: dict[str, Any], policy: dict[str, Any], action: dict[str, Any]) -> list[dict[str, Any]]:
        actor_ref = action["actor_ref"]
        target_ref = action["parameters"].get("validated_target_ref")
        out: list[dict[str, Any]] = []
        priority = 0
        for scope, target, reqs in [("ACTOR", actor_ref, policy["resource_requirements"]), ("TARGET", target_ref, policy["target_resource_requirements"])]:
            for r in reqs:
                consume = self._requirement_amount(r, intent["parameters"], "consume_amount", "consume_from_parameter")
                if consume:
                    if target is None:
                        raise ValidationError(f"{scope} resource target missing during materialization")
                    out.append({
                        "target_ref": target,
                        "operation": "DECREMENT",
                        "field_path": r["field_path"],
                        "amount": consume,
                        "priority": priority,
                        "kind": "DIRECT",
                    })
                    priority += 1
        for t in policy["consequence_templates"]:
            target = actor_ref if t["target"] == "ACTOR" else target_ref
            if target is None:
                raise ValidationError("validated target missing for consequence template")
            c = {
                "target_ref": target,
                "operation": t["operation"],
                "field_path": t["field_path"],
                "priority": priority,
                "kind": "DIRECT",
            }
            if t["operation"] in {"SET", "TRANSITION"}:
                c["value"] = self._resolve_template_value(t, intent["parameters"], "value")
                if "from" in t:
                    c["from"] = copy.deepcopy(t["from"])
            else:
                amount = self._resolve_template_value(t, intent["parameters"], "amount")
                if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount < 0:
                    raise ValidationError("materialized consequence amount invalid")
                c["amount"] = amount
            out.append(c)
            priority += 1
        if policy["cooldown_ticks"] > 0:
            clock = self.runtime.get_clock(intent["world_instance_id"])
            now_abs = clock["day"] * clock["ticks_per_day"] + clock["tick"]
            cooldown_key = sha256_text(policy["policy_key"])[:16]
            out.append({
                "target_ref": actor_ref,
                "operation": "SET",
                "field_path": f"data.agent_runtime.cooldowns.cd_{cooldown_key}",
                "value": now_abs + policy["cooldown_ticks"],
                "priority": priority,
                "kind": "DIRECT",
            })
        return out

    def execute_validated_intent(self, intent_id: str) -> dict[str, Any]:
        with self._lock, self.runtime._write_lock:
            intent_row = self.conn.execute("SELECT * FROM intents WHERE intent_id=?", (intent_id,)).fetchone()
            if not intent_row:
                raise NotFoundError("intent not found")
            existing_execution = self.conn.execute("SELECT result_json,result_hash FROM intent_executions WHERE intent_id=?", (intent_id,)).fetchone()
            if existing_execution:
                if sha256_text(existing_execution["result_json"]) != existing_execution["result_hash"]:
                    raise IntegrityError("intent execution hash mismatch")
                out = json.loads(existing_execution["result_json"])
                out["idempotent_replay"] = True
                return out
            if intent_row["status"] not in {"VALIDATED", "CONSUMED"}:
                raise ConflictError(f"intent must be VALIDATED before execution, got {intent_row['status']}")
            vrow = self.conn.execute("SELECT validation_json,validation_hash FROM intent_validations WHERE intent_id=?", (intent_id,)).fetchone()
            if not vrow or sha256_text(vrow["validation_json"]) != vrow["validation_hash"]:
                raise IntegrityError("validated intent record missing/corrupt")
            validation = json.loads(vrow["validation_json"])
            if validation["status"] != "PASS" or not validation.get("action"):
                raise ConflictError("rejected intent cannot execute")
            intent = json.loads(intent_row["candidate_json"])
            action = copy.deepcopy(validation["action"])
            policy = self._get_policy_for_action(intent["world_instance_id"], intent["intent_type"])
            if policy["policy_id"] != validation["policy_id"] or sha256_text(canonical_json(policy)) != action["policy_hash"]:
                raise IntegrityError("action policy changed since validation")
            world = self.runtime.get_world(intent["world_instance_id"])
            if world["simulation_mode"] == "ROUTINE_OFFLINE" and intent["source"] not in {"SYSTEM_ROUTINE", "SYSTEM_RECOVERY"}:
                raise OfflinePolicyError("autonomous/LLM/player intents cannot execute offline")
            consequences = self._materialize_consequences(intent, policy, action)
        # Runtime owns its own transaction/lock. Keeping this call outside our inner DB update region makes ownership explicit.
        core_result = self.runtime.apply_action(intent["world_instance_id"], action, consequences)
        result = {
            "intent_id": intent_id,
            "action_id": action["action_id"],
            "event_id": core_result["event_id"],
            "status": core_result["status"],
            "mutation_count": core_result["mutation_count"],
            "idempotent_replay": core_result.get("idempotent_replay", False),
        }
        rhash = sha256_text(canonical_json(result))
        with self._lock, self.runtime._write_lock:
            # Crash-safe reconciliation: if core succeeded but bookkeeping fails, replaying the same action is idempotent.
            self.runtime._begin()
            try:
                self.conn.execute(
                    "INSERT OR IGNORE INTO intent_executions VALUES(?,?,?,?,?,?)",
                    (new_runtime_id("execution"), intent_id, action["action_id"], core_result["event_id"], canonical_json(result), rhash),
                )
                self.conn.execute("UPDATE intents SET status='CONSUMED' WHERE intent_id=?", (intent_id,))
                self.runtime._commit()
            except Exception:
                self.runtime._rollback()
                raise
        return result

    def full_integrity_check(self, world_instance_id: str) -> dict[str, Any]:
        failures: list[str] = []
        with self._lock, self.runtime._write_lock:
            for table, json_col, hash_col, where in [
                ("action_policies", "policy_json", "policy_hash", "world_instance_id=?"),
                ("intents", "candidate_json", "candidate_hash", "world_instance_id=?"),
            ]:
                rows = self.conn.execute(f"SELECT rowid,* FROM {table} WHERE {where}", (world_instance_id,)).fetchall()
                for row in rows:
                    if sha256_text(row[json_col]) != row[hash_col]:
                        failures.append(f"{table}:HASH_MISMATCH:{row['rowid']}")
            rows = self.conn.execute(
                "SELECT v.* FROM intent_validations v JOIN intents i ON i.intent_id=v.intent_id WHERE i.world_instance_id=?",
                (world_instance_id,),
            ).fetchall()
            for row in rows:
                if sha256_text(row["validation_json"]) != row["validation_hash"]:
                    failures.append(f"intent_validations:HASH_MISMATCH:{row['validation_id']}")
            rows = self.conn.execute(
                "SELECT e.* FROM intent_executions e JOIN intents i ON i.intent_id=e.intent_id WHERE i.world_instance_id=?",
                (world_instance_id,),
            ).fetchall()
            for row in rows:
                if sha256_text(row["result_json"]) != row["result_hash"]:
                    failures.append(f"intent_executions:HASH_MISMATCH:{row['execution_id']}")
            orphans = self.conn.execute(
                "SELECT COUNT(*) c FROM intents i LEFT JOIN entity_states e ON e.world_instance_id=i.world_instance_id AND e.entity_runtime_id=i.actor_ref WHERE i.world_instance_id=? AND e.entity_runtime_id IS NULL",
                (world_instance_id,),
            ).fetchone()["c"]
            if orphans:
                failures.append(f"ORPHAN_INTENT_ACTORS:{orphans}")
        return {"status": "PASS" if not failures else "FAIL", "failures": failures}

    def integrity_guard(self, world_instance_id: str) -> dict[str, Any]:
        core = self.runtime.full_integrity_check(world_instance_id)
        agent = self.full_integrity_check(world_instance_id)
        ok = core.get("status") == "PASS" and agent.get("status") == "PASS"
        if not ok:
            with self.runtime._write_lock:
                self.conn.execute("UPDATE worlds SET status='CORRUPT_BLOCKED' WHERE world_instance_id=?", (world_instance_id,))
        return {"status": "PASS" if ok else "FAIL", "runtime": core, "agent_intents": agent}


class AgentBrain:
    """Deterministic utility brain. It can only create candidate intents, never mutate world truth."""

    SCHEMA_VERSION = 1

    def __init__(self, runtime: LivingRuntime, validator: IntentValidator) -> None:
        if validator.runtime is not runtime:
            raise ValidationError("brain and validator must share runtime")
        self.runtime = runtime
        self.validator = validator
        self.conn = runtime.conn
        self._lock = threading.RLock()
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self.runtime._write_lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_behaviors(
                    behavior_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    behavior_key TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('ACTIVE','DISABLED')),
                    behavior_json TEXT NOT NULL,
                    behavior_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id, behavior_key)
                );
                CREATE TABLE IF NOT EXISTS agent_perceptions(
                    perception_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    agent_ref TEXT NOT NULL,
                    recorded_day INTEGER NOT NULL,
                    recorded_tick INTEGER NOT NULL,
                    perception_json TEXT NOT NULL,
                    perception_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_perceptions ON agent_perceptions(world_instance_id,agent_ref,recorded_day DESC,recorded_tick DESC);
                CREATE TABLE IF NOT EXISTS agent_decisions(
                    decision_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    agent_ref TEXT NOT NULL,
                    intent_id TEXT,
                    decision_json TEXT NOT NULL,
                    decision_hash TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS perception_no_update
                BEFORE UPDATE ON agent_perceptions BEGIN SELECT RAISE(ABORT, 'perception history is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS perception_no_delete
                BEFORE DELETE ON agent_perceptions BEGIN SELECT RAISE(ABORT, 'perception history is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS decision_no_update
                BEFORE UPDATE ON agent_decisions BEGIN SELECT RAISE(ABORT, 'decision history is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS decision_no_delete
                BEFORE DELETE ON agent_decisions BEGIN SELECT RAISE(ABORT, 'decision history is immutable'); END;
                """
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('agent_brain_schema_version',?)",
                (str(self.SCHEMA_VERSION),),
            )

    def _get_agent(self, world_instance_id: str, agent_ref: str, *, require_active: bool = True) -> dict[str, Any]:
        state = self.runtime.get_entity(world_instance_id, agent_ref)
        if state.get("entity_kind") != "AGENT":
            raise ValidationError("AgentBrain only controls AGENT entities")
        if require_active and state.get("lifecycle") != "ACTIVE":
            raise ConflictError("agent is not active")
        return state

    def validate_agent_state(self, world_instance_id: str, agent_ref: str) -> dict[str, Any]:
        agent = self._get_agent(world_instance_id, agent_ref, require_active=False)
        failures: list[str] = []
        needs = _path_get(agent, "data.needs", default=None)
        if not isinstance(needs, dict) or not needs:
            failures.append("MISSING_NEEDS")
        else:
            for key, value in needs.items():
                try:
                    _bounded_number(value, f"need:{key}", 0, 100)
                except ValidationError:
                    failures.append(f"INVALID_NEED:{key}")
        risk = _path_get(agent, "data.risk_tolerance", default=50)
        try:
            _bounded_number(risk, "risk_tolerance", 0, 100)
        except ValidationError:
            failures.append("INVALID_RISK_TOLERANCE")
        goals = _path_get(agent, "data.goals", default={})
        if not isinstance(goals, dict):
            failures.append("INVALID_GOALS")
        else:
            for key, value in goals.items():
                try:
                    _bounded_number(value, f"goal:{key}", 0, 100)
                except ValidationError:
                    failures.append(f"INVALID_GOAL:{key}")
        return {"status": "PASS" if not failures else "FAIL", "failures": failures, "agent_ref": agent_ref}

    def register_behavior(self, world_instance_id: str, behavior: dict[str, Any]) -> dict[str, Any]:
        world = self.runtime.get_world(world_instance_id)
        b = copy.deepcopy(behavior)
        required = ["behavior_key", "intent_type", "need_key", "threshold", "target_strategy"]
        missing = [k for k in required if k not in b]
        if missing:
            raise ValidationError(f"missing behavior fields: {missing}")
        if not isinstance(b["behavior_key"], str) or not b["behavior_key"].strip():
            raise ValidationError("behavior_key required")
        if not isinstance(b["intent_type"], str) or not b["intent_type"].strip():
            raise ValidationError("intent_type required")
        if not isinstance(b["need_key"], str) or not b["need_key"].strip():
            raise ValidationError("need_key required")
        _bounded_number(b["threshold"], "threshold", 0, 100)
        if b["target_strategy"] not in ALLOWED_TARGET_STRATEGIES:
            raise ValidationError("invalid target_strategy")
        b.setdefault("need_weight", 100.0)
        b.setdefault("base_priority", 0.0)
        b.setdefault("risk_cost", 0.0)
        b.setdefault("risk_penalty_weight", 1.0)
        b.setdefault("opportunity_bonus", 0.0)
        b.setdefault("goal_key", None)
        b.setdefault("goal_weight", 0.0)
        b.setdefault("target_kinds", [])
        b.setdefault("target_fact_equals", {})
        b.setdefault("agent_state_equals", {})
        b.setdefault("parameters", {})
        b.setdefault("status", "ACTIVE")
        for key in ["need_weight", "base_priority", "risk_cost", "risk_penalty_weight", "opportunity_bonus", "goal_weight"]:
            _numeric(b[key], key)
        _bounded_number(b["risk_cost"], "risk_cost", 0, 100)
        if b["risk_penalty_weight"] < 0:
            raise ValidationError("risk_penalty_weight cannot be negative")
        if b["status"] not in {"ACTIVE", "DISABLED"}:
            raise ValidationError("invalid behavior status")
        if not isinstance(b["target_kinds"], list) or any(not isinstance(x, str) for x in b["target_kinds"]):
            raise ValidationError("target_kinds invalid")
        if not isinstance(b["target_fact_equals"], dict) or not isinstance(b["agent_state_equals"], dict) or not isinstance(b["parameters"], dict):
            raise ValidationError("behavior maps invalid")
        if any(k in RESERVED_PARAMETER_KEYS for k in b["parameters"]):
            raise ValidationError("behavior cannot emit reserved parameters")
        behavior_id = b.get("behavior_id") or new_runtime_id("behavior")
        validate_runtime_id(behavior_id, "behavior")
        body = {"behavior_id": behavior_id, "world_instance_id": world_instance_id, "timeline_id": world["timeline_id"], **b}
        bhash = sha256_text(canonical_json(body))
        with self._lock, self.runtime._write_lock:
            self.conn.execute(
                "INSERT INTO agent_behaviors VALUES(?,?,?,?,?,?,?)",
                (behavior_id, world_instance_id, world["timeline_id"], body["behavior_key"], body["status"], canonical_json(body), bhash),
            )
        body["behavior_hash"] = bhash
        return body

    def set_behavior_status(self, behavior_id: str, status: str) -> None:
        validate_runtime_id(behavior_id, "behavior")
        if status not in {"ACTIVE", "DISABLED"}:
            raise ValidationError("invalid behavior status")
        with self._lock, self.runtime._write_lock:
            row = self.conn.execute("SELECT behavior_json FROM agent_behaviors WHERE behavior_id=?", (behavior_id,)).fetchone()
            if not row:
                raise NotFoundError("behavior not found")
            body = json.loads(row["behavior_json"])
            body["status"] = status
            self.conn.execute(
                "UPDATE agent_behaviors SET status=?,behavior_json=?,behavior_hash=? WHERE behavior_id=?",
                (status, canonical_json(body), sha256_text(canonical_json(body)), behavior_id),
            )

    def record_perception(self, world_instance_id: str, agent_ref: str, observations: list[dict[str, Any]], *, source: str = "SENSORY") -> dict[str, Any]:
        world = self.runtime.get_world(world_instance_id)
        self._get_agent(world_instance_id, agent_ref)
        if source not in ALLOWED_PERCEPTION_SOURCES:
            raise ValidationError("invalid perception source")
        if not isinstance(observations, list):
            raise ValidationError("observations must be list")
        normalized: list[dict[str, Any]] = []
        for obs in observations:
            if not isinstance(obs, dict) or not isinstance(obs.get("target_ref"), str) or not obs["target_ref"]:
                raise ValidationError("invalid observation")
            if obs["target_ref"].startswith("rt:"):
                validate_runtime_id(obs["target_ref"])
            elif not self.runtime.canonical_ref_resolves(obs["target_ref"]):
                raise ValidationError(f"perception target canonical ref unknown: {obs['target_ref']}")
            if not isinstance(obs.get("facts", {}), dict):
                raise ValidationError("observation facts must be object")
            confidence = obs.get("confidence", 1.0)
            _bounded_number(confidence, "confidence", 0, 1)
            perceived_kind = obs.get("perceived_kind")
            if perceived_kind is not None and not isinstance(perceived_kind, str):
                raise ValidationError("perceived_kind invalid")
            normalized.append({
                "target_ref": obs["target_ref"],
                "perceived_kind": perceived_kind,
                "facts": copy.deepcopy(obs.get("facts", {})),
                "confidence": float(confidence),
            })
        clock = world["clock_state"]
        perception_id = new_runtime_id("perception")
        body = {
            "perception_id": perception_id,
            "world_instance_id": world_instance_id,
            "timeline_id": world["timeline_id"],
            "agent_ref": agent_ref,
            "recorded_at": clock_point(clock["day"], clock["tick"]),
            "source": source,
            "observations": normalized,
        }
        phash = sha256_text(canonical_json(body))
        with self._lock, self.runtime._write_lock:
            self.conn.execute(
                "INSERT INTO agent_perceptions VALUES(?,?,?,?,?,?,?,?)",
                (perception_id, world_instance_id, world["timeline_id"], agent_ref, clock["day"], clock["tick"], canonical_json(body), phash),
            )
        body["perception_hash"] = phash
        return body

    def _latest_perception(self, world_instance_id: str, agent_ref: str) -> dict[str, Any] | None:
        with self.runtime._write_lock:
            row = self.conn.execute(
                "SELECT perception_json,perception_hash FROM agent_perceptions WHERE world_instance_id=? AND agent_ref=? ORDER BY recorded_day DESC,recorded_tick DESC,rowid DESC LIMIT 1",
                (world_instance_id, agent_ref),
            ).fetchone()
        if not row:
            return None
        if sha256_text(row["perception_json"]) != row["perception_hash"]:
            raise IntegrityError("perception hash mismatch")
        return json.loads(row["perception_json"])

    def _behavior_candidates(self, world_instance_id: str, agent: dict[str, Any], perception: dict[str, Any] | None) -> list[dict[str, Any]]:
        with self.runtime._write_lock:
            rows = self.conn.execute(
                "SELECT behavior_json,behavior_hash FROM agent_behaviors WHERE world_instance_id=? AND status='ACTIVE' ORDER BY behavior_key",
                (world_instance_id,),
            ).fetchall()
        needs = _path_get(agent, "data.needs", default={})
        goals = _path_get(agent, "data.goals", default={})
        risk_tolerance = _bounded_number(_path_get(agent, "data.risk_tolerance", default=50), "risk_tolerance", 0, 100)
        candidates: list[dict[str, Any]] = []
        for row in rows:
            if sha256_text(row["behavior_json"]) != row["behavior_hash"]:
                raise IntegrityError("behavior hash mismatch")
            b = json.loads(row["behavior_json"])
            if any(_path_get(agent, path, default=None) != expected for path, expected in b.get("agent_state_equals", {}).items()):
                continue
            need = needs.get(b["need_key"])
            if not isinstance(need, (int, float)) or isinstance(need, bool):
                continue
            if need < b["threshold"]:
                continue
            target_ref = None
            perception_id = None
            if b["target_strategy"] == "SELF":
                target_ref = agent["entity_runtime_id"]
            elif b["target_strategy"] == "PERCEPTION":
                if perception is None:
                    continue
                matches = []
                for obs in perception["observations"]:
                    if b["target_kinds"] and obs.get("perceived_kind") not in b["target_kinds"]:
                        continue
                    if any(_path_get(obs.get("facts", {}), path, default=None) != expected for path, expected in b["target_fact_equals"].items()):
                        continue
                    matches.append(obs)
                if not matches:
                    continue
                # Perceived confidence first, then stable reference. Never query target truth here.
                matches.sort(key=lambda x: (-x.get("confidence", 0), x["target_ref"]))
                target_ref = matches[0]["target_ref"]
                perception_id = perception["perception_id"]
            elif b["target_strategy"] == "NONE":
                target_ref = None
            goal_value = goals.get(b.get("goal_key"), 0) if b.get("goal_key") else 0
            if not isinstance(goal_value, (int, float)) or isinstance(goal_value, bool):
                goal_value = 0
            risk_gap = max(0.0, float(b["risk_cost"]) - risk_tolerance)
            score = (
                float(b["base_priority"])
                + float(b["need_weight"]) * (float(need) / 100.0)
                + float(b["goal_weight"]) * (float(goal_value) / 100.0)
                + float(b["opportunity_bonus"])
                - risk_gap * float(b["risk_penalty_weight"])
            )
            candidates.append({
                "behavior_id": b["behavior_id"],
                "behavior_key": b["behavior_key"],
                "intent_type": b["intent_type"],
                "need_key": b["need_key"],
                "need_value": float(need),
                "target_ref": target_ref,
                "parameters": copy.deepcopy(b["parameters"]),
                "score": round(score, 6),
                "perception_id": perception_id,
            })
        candidates.sort(key=lambda c: (-c["score"], c["behavior_key"]))
        return candidates

    def decide(self, world_instance_id: str, agent_ref: str) -> dict[str, Any]:
        world = self.runtime.get_world(world_instance_id)
        if world["simulation_mode"] == "ROUTINE_OFFLINE":
            raise OfflinePolicyError("AgentBrain does not make autonomous decisions offline; only routines continue")
        agent = self._get_agent(world_instance_id, agent_ref)
        state_validation = self.validate_agent_state(world_instance_id, agent_ref)
        if state_validation["status"] != "PASS":
            raise ValidationError(f"invalid agent decision state: {state_validation['failures']}")
        perception = self._latest_perception(world_instance_id, agent_ref)
        candidates = self._behavior_candidates(world_instance_id, agent, perception)
        clock = world["clock_state"]
        decision_id = new_runtime_id("decision")
        selected = candidates[0] if candidates else None
        intent = None
        with self._lock, self.validator._lock, self.runtime._write_lock:
            self.runtime._begin()
            try:
                if selected is not None:
                    intent = self.validator.submit_intent(
                        world_instance_id,
                        actor_ref=agent_ref,
                        target_ref=selected["target_ref"],
                        intent_type=selected["intent_type"],
                        parameters=selected["parameters"],
                        source="AGENT_BRAIN",
                        metadata={
                            "decision_id": decision_id,
                            "behavior_id": selected["behavior_id"],
                            "behavior_key": selected["behavior_key"],
                            "score": selected["score"],
                            "perception_id": selected["perception_id"],
                        },
                    )
                body = {
                    "decision_id": decision_id,
                    "world_instance_id": world_instance_id,
                    "timeline_id": world["timeline_id"],
                    "agent_ref": agent_ref,
                    "decided_at": clock_point(clock["day"], clock["tick"]),
                    "agent_state_version": agent["version"],
                    "perception_id": perception["perception_id"] if perception else None,
                    "candidates": candidates,
                    "selected": selected,
                    "intent_id": intent["intent_id"] if intent else None,
                    "status": "INTENT_PROPOSED" if intent else "NO_ACTION",
                }
                dhash = sha256_text(canonical_json(body))
                self.conn.execute(
                    "INSERT INTO agent_decisions VALUES(?,?,?,?,?,?,?)",
                    (decision_id, world_instance_id, world["timeline_id"], agent_ref, body["intent_id"], canonical_json(body), dhash),
                )
                self.runtime._commit()
            except Exception:
                self.runtime._rollback()
                raise
        body["decision_hash"] = dhash
        return body

    def full_integrity_check(self, world_instance_id: str) -> dict[str, Any]:
        failures: list[str] = []
        with self._lock, self.runtime._write_lock:
            for table, json_col, hash_col in [
                ("agent_behaviors", "behavior_json", "behavior_hash"),
                ("agent_perceptions", "perception_json", "perception_hash"),
                ("agent_decisions", "decision_json", "decision_hash"),
            ]:
                rows = self.conn.execute(f"SELECT rowid,* FROM {table} WHERE world_instance_id=?", (world_instance_id,)).fetchall()
                for row in rows:
                    if sha256_text(row[json_col]) != row[hash_col]:
                        failures.append(f"{table}:HASH_MISMATCH:{row['rowid']}")
            orphans = self.conn.execute(
                "SELECT COUNT(*) c FROM agent_decisions d LEFT JOIN entity_states e ON e.world_instance_id=d.world_instance_id AND e.entity_runtime_id=d.agent_ref WHERE d.world_instance_id=? AND e.entity_runtime_id IS NULL",
                (world_instance_id,),
            ).fetchone()["c"]
            if orphans:
                failures.append(f"ORPHAN_DECISION_AGENTS:{orphans}")
        return {"status": "PASS" if not failures else "FAIL", "failures": failures}

    def integrity_guard(self, world_instance_id: str) -> dict[str, Any]:
        validator_report = self.validator.integrity_guard(world_instance_id)
        brain_report = self.full_integrity_check(world_instance_id)
        ok = validator_report["status"] == "PASS" and brain_report["status"] == "PASS"
        if not ok:
            with self.runtime._write_lock:
                self.conn.execute("UPDATE worlds SET status='CORRUPT_BLOCKED' WHERE world_instance_id=?", (world_instance_id,))
        return {"status": "PASS" if ok else "FAIL", "validator": validator_report, "brain": brain_report}
