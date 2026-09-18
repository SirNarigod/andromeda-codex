from __future__ import annotations

import copy
import json
import sqlite3
import threading
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from living_runtime import (
    LivingRuntime,
    EventEnvelope,
    ValidationError,
    IntegrityError,
    ConflictError,
    NotFoundError,
    OfflinePolicyError,
    canonical_json,
    sha256_text,
    new_runtime_id,
    validate_runtime_id,
    clock_point,
    MASTER_RELEASE_SHA256,
)

MASTER_RELATIONSHIP_PATH = "ANDROMEDA_CODEX_MASTER/07_RELATIONSHIPS/MASTER_RELATIONSHIP_REGISTRY_V2_0_0.json"
ALLOWED_DIRECTIONS = {"OUTGOING", "INCOMING", "BOTH"}
ALLOWED_RULE_STATUS = {"ACTIVE", "DISABLED"}
ALLOWED_OFFLINE_POLICY = {"ACTIVE_ONLY", "ROUTINE_SAFE"}
ALLOWED_DERIVED_OPERATIONS = {"SET", "TRANSITION", "INCREMENT", "DECREMENT", "SCHEDULE_RECOVERY"}
PROHIBITED_OFFLINE_EVENT_TYPES = {"MAJOR_CONFLICT", "RANDOM_PERMADEATH", "WORLD_DESTRUCTION", "WAR_ESCALATION"}
SYSTEM_SUBJECTS = {"SYSTEM_RECOVERY", "SYSTEM_ROUTINE", "SYSTEM_RECONCILIATION", "SYSTEM_CLOCK"}


def _json_path_get(value: Any, path: str) -> Any:
    cur = value
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise ValidationError(f"event path not found: {path}")
    return cur


class ConsequenceEngine:
    """Bounded, deterministic causal propagation over runtime/canonical relationship edges.

    Canon is always read-only. Canonical relationships are imported only as runtime snapshots;
    state mutation always targets materialized runtime entities.
    """

    SCHEMA_VERSION = 1
    MAX_DEPTH = 8
    DEFAULT_BUDGET = 64

    def __init__(self, runtime: LivingRuntime) -> None:
        if not isinstance(runtime, LivingRuntime):
            raise ValidationError("ConsequenceEngine requires LivingRuntime")
        self.runtime = runtime
        self.conn = runtime.conn
        self._engine_lock = threading.RLock()
        self._unsubscribe = None
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self.runtime._write_lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS causal_relations(
                    relation_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    origin TEXT NOT NULL CHECK(origin IN ('RUNTIME','CANONICAL_SNAPSHOT')),
                    external_relation_id TEXT,
                    source_ref TEXT NOT NULL,
                    target_ref TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    active INTEGER NOT NULL CHECK(active IN (0,1)),
                    metadata_json TEXT NOT NULL,
                    relation_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id, external_relation_id)
                );
                CREATE INDEX IF NOT EXISTS idx_causal_rel_out ON causal_relations(world_instance_id,relation_type,source_ref,active);
                CREATE INDEX IF NOT EXISTS idx_causal_rel_in ON causal_relations(world_instance_id,relation_type,target_ref,active);

                CREATE TABLE IF NOT EXISTS causal_rules(
                    rule_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    trigger_event_type TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    direction TEXT NOT NULL CHECK(direction IN ('OUTGOING','INCOMING','BOTH')),
                    derived_event_type TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    max_depth INTEGER NOT NULL CHECK(max_depth BETWEEN 1 AND 8),
                    offline_policy TEXT NOT NULL CHECK(offline_policy IN ('ACTIVE_ONLY','ROUTINE_SAFE')),
                    status TEXT NOT NULL CHECK(status IN ('ACTIVE','DISABLED')),
                    rule_json TEXT NOT NULL,
                    rule_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_causal_rules_trigger ON causal_rules(world_instance_id,trigger_event_type,status,priority,rule_id);

                CREATE TABLE IF NOT EXISTS propagation_runs(
                    root_event_id TEXT PRIMARY KEY REFERENCES events(event_id) ON DELETE RESTRICT,
                    world_instance_id TEXT NOT NULL,
                    timeline_id TEXT NOT NULL,
                    budget_total INTEGER NOT NULL CHECK(budget_total BETWEEN 1 AND 64),
                    budget_used INTEGER NOT NULL CHECK(budget_used >= 0),
                    status TEXT NOT NULL CHECK(status IN ('RUNNING','COMPLETED','BUDGET_EXHAUSTED','FAILED')),
                    rule_set_hash TEXT NOT NULL,
                    started_day INTEGER NOT NULL,
                    started_tick INTEGER NOT NULL,
                    completed_day INTEGER,
                    completed_tick INTEGER,
                    result_json TEXT
                );

                CREATE TABLE IF NOT EXISTS causal_scans(
                    root_event_id TEXT NOT NULL REFERENCES propagation_runs(root_event_id) ON DELETE CASCADE,
                    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE RESTRICT,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','SCANNED','SKIPPED_BUDGET','FAILED')),
                    PRIMARY KEY(root_event_id,event_id)
                );

                CREATE TABLE IF NOT EXISTS causal_expansions(
                    expansion_id TEXT PRIMARY KEY,
                    root_event_id TEXT NOT NULL REFERENCES propagation_runs(root_event_id) ON DELETE CASCADE,
                    parent_event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE RESTRICT,
                    child_event_id TEXT REFERENCES events(event_id) ON DELETE RESTRICT,
                    rule_id TEXT NOT NULL REFERENCES causal_rules(rule_id) ON DELETE RESTRICT,
                    relation_id TEXT NOT NULL REFERENCES causal_relations(relation_id) ON DELETE RESTRICT,
                    subject_ref TEXT NOT NULL,
                    target_ref TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    intent_id TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('RESERVED','APPLIED','FAILED')),
                    signature TEXT NOT NULL UNIQUE,
                    detail_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_expansion_root ON causal_expansions(root_event_id,parent_event_id,status);

                CREATE TABLE IF NOT EXISTS causal_stops(
                    stop_id TEXT PRIMARY KEY,
                    root_event_id TEXT NOT NULL REFERENCES propagation_runs(root_event_id) ON DELETE CASCADE,
                    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE RESTRICT,
                    rule_id TEXT,
                    relation_id TEXT,
                    target_ref TEXT,
                    reason TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    recorded_day INTEGER NOT NULL,
                    recorded_tick INTEGER NOT NULL,
                    stop_signature TEXT NOT NULL UNIQUE
                );

                CREATE TRIGGER IF NOT EXISTS canonical_snapshot_relation_no_update
                BEFORE UPDATE ON causal_relations WHEN OLD.origin='CANONICAL_SNAPSHOT'
                BEGIN SELECT RAISE(ABORT, 'canonical relationship snapshots are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS canonical_snapshot_relation_no_delete
                BEFORE DELETE ON causal_relations WHEN OLD.origin='CANONICAL_SNAPSHOT'
                BEGIN SELECT RAISE(ABORT, 'canonical relationship snapshots are immutable'); END;
                """
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('consequence_engine_schema_version',?)",
                (str(self.SCHEMA_VERSION),),
            )

    # ---------- relationship graph ----------

    def _validate_endpoint_ref(self, world_instance_id: str, ref: str) -> None:
        if not isinstance(ref, str) or not ref:
            raise ValidationError("relationship endpoint ref required")
        if ref.startswith("rt:"):
            self.runtime.get_entity(world_instance_id, ref)
            return
        if not self.runtime.canonical_ref_resolves(ref):
            raise ValidationError(f"relationship endpoint does not resolve: {ref}")

    def register_relation(
        self,
        world_instance_id: str,
        source_ref: str,
        target_ref: str,
        relation_type: str,
        *,
        origin: str = "RUNTIME",
        external_relation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        relation_id: str | None = None,
    ) -> dict[str, Any]:
        world = self.runtime.get_world(world_instance_id)
        if origin not in {"RUNTIME", "CANONICAL_SNAPSHOT"}:
            raise ValidationError("invalid relation origin")
        if not isinstance(relation_type, str) or not relation_type.strip():
            raise ValidationError("relation_type required")
        if origin == "CANONICAL_SNAPSHOT" and not external_relation_id:
            raise ValidationError("canonical snapshot requires external_relation_id")
        self._validate_endpoint_ref(world_instance_id, source_ref)
        self._validate_endpoint_ref(world_instance_id, target_ref)
        relation_id = relation_id or new_runtime_id("relation")
        validate_runtime_id(relation_id, "relation")
        body = {
            "relation_id": relation_id,
            "world_instance_id": world_instance_id,
            "timeline_id": world["timeline_id"],
            "origin": origin,
            "external_relation_id": external_relation_id,
            "source_ref": source_ref,
            "target_ref": target_ref,
            "relation_type": relation_type,
            "active": True,
            "metadata": copy.deepcopy(metadata or {}),
        }
        rhash = sha256_text(canonical_json(body))
        with self._engine_lock, self.runtime._write_lock:
            self.conn.execute(
                "INSERT INTO causal_relations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    relation_id, world_instance_id, world["timeline_id"], origin, external_relation_id,
                    source_ref, target_ref, relation_type, 1, canonical_json(body["metadata"]), rhash,
                ),
            )
        body["relation_hash"] = rhash
        return body

    def deactivate_runtime_relation(self, relation_id: str) -> None:
        validate_runtime_id(relation_id, "relation")
        with self._engine_lock, self.runtime._write_lock:
            row = self.conn.execute("SELECT origin FROM causal_relations WHERE relation_id=?", (relation_id,)).fetchone()
            if not row:
                raise NotFoundError("relation not found")
            if row["origin"] != "RUNTIME":
                raise ConflictError("canonical snapshot relation cannot be deactivated")
            full = self.conn.execute("SELECT * FROM causal_relations WHERE relation_id=?", (relation_id,)).fetchone()
            body = {
                "relation_id": full["relation_id"], "world_instance_id": full["world_instance_id"], "timeline_id": full["timeline_id"],
                "origin": full["origin"], "external_relation_id": full["external_relation_id"], "source_ref": full["source_ref"],
                "target_ref": full["target_ref"], "relation_type": full["relation_type"], "active": False,
                "metadata": json.loads(full["metadata_json"]),
            }
            self.conn.execute("UPDATE causal_relations SET active=0,relation_hash=? WHERE relation_id=?", (sha256_text(canonical_json(body)), relation_id))

    def load_master_relationships(
        self,
        world_instance_id: str,
        *,
        relation_types: Iterable[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        self.runtime.get_world(world_instance_id)
        if not self.runtime.master_release_path:
            raise IntegrityError("master release path required to load canonical relationships")
        actual = self.runtime._file_sha256(self.runtime.master_release_path)
        if actual != self.runtime.master_release_sha256:
            raise IntegrityError("master release hash changed after runtime initialization")
        wanted = set(relation_types) if relation_types is not None else None
        if wanted is not None and any(not isinstance(x, str) or not x for x in wanted):
            raise ValidationError("invalid relationship type filter")
        if limit is not None and (not isinstance(limit, int) or limit <= 0):
            raise ValidationError("limit must be positive integer")
        with zipfile.ZipFile(self.runtime.master_release_path, "r") as zf:
            raw = json.loads(zf.read(MASTER_RELATIONSHIP_PATH))
        rels = raw.get("relationships")
        if not isinstance(rels, list) or raw.get("count") != len(rels):
            raise IntegrityError("master relationship registry count mismatch")
        selected = [r for r in rels if wanted is None or r.get("type") in wanted]
        if limit is not None:
            selected = selected[:limit]
        inserted = 0
        skipped_existing = 0
        with self._engine_lock, self.runtime._write_lock:
            self.runtime._begin()
            try:
                world = self.runtime.get_world(world_instance_id)
                for rel in selected:
                    source_ref = rel.get("source_id")
                    target_ref = rel.get("target_id")
                    rel_type = rel.get("type")
                    external_id = rel.get("id")
                    if not all(isinstance(x, str) and x for x in (source_ref, target_ref, rel_type, external_id)):
                        raise IntegrityError("invalid master relationship record")
                    if not self.runtime.canonical_ref_resolves(source_ref) or not self.runtime.canonical_ref_resolves(target_ref):
                        raise IntegrityError(f"master relationship endpoint does not resolve: {external_id}")
                    existing = self.conn.execute(
                        "SELECT relation_id FROM causal_relations WHERE world_instance_id=? AND external_relation_id=?",
                        (world_instance_id, external_id),
                    ).fetchone()
                    if existing:
                        skipped_existing += 1
                        continue
                    relation_id = new_runtime_id("relation")
                    metadata = {
                        "master_record": copy.deepcopy(rel),
                        "master_registry": "MASTER_RELATIONSHIP_REGISTRY_V2_0_0",
                        "read_only_snapshot": True,
                    }
                    body = {
                        "relation_id": relation_id,
                        "world_instance_id": world_instance_id,
                        "timeline_id": world["timeline_id"],
                        "origin": "CANONICAL_SNAPSHOT",
                        "external_relation_id": external_id,
                        "source_ref": source_ref,
                        "target_ref": target_ref,
                        "relation_type": rel_type,
                        "active": True,
                        "metadata": metadata,
                    }
                    rhash = sha256_text(canonical_json(body))
                    self.conn.execute(
                        "INSERT INTO causal_relations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            relation_id, world_instance_id, world["timeline_id"], "CANONICAL_SNAPSHOT", external_id,
                            source_ref, target_ref, rel_type, 1, canonical_json(metadata), rhash,
                        ),
                    )
                    inserted += 1
                self.runtime._commit()
            except Exception:
                self.runtime._rollback()
                raise
        return {
            "source_count": len(rels),
            "selected": len(selected),
            "inserted": inserted,
            "skipped_existing": skipped_existing,
            "status": "PASS",
        }

    # ---------- causal rules ----------

    def register_rule(self, world_instance_id: str, rule: dict[str, Any]) -> dict[str, Any]:
        world = self.runtime.get_world(world_instance_id)
        r = copy.deepcopy(rule)
        r.setdefault("rule_id", new_runtime_id("rule"))
        validate_runtime_id(r["rule_id"], "rule")
        required = ["name", "trigger_event_type", "relation_type", "direction", "derived_event_type", "consequences"]
        missing = [k for k in required if k not in r]
        if missing:
            raise ValidationError(f"missing causal rule fields: {missing}")
        for k in ["name", "trigger_event_type", "relation_type", "derived_event_type"]:
            if not isinstance(r[k], str) or not r[k].strip():
                raise ValidationError(f"{k} must be non-empty string")
        if r["direction"] not in ALLOWED_DIRECTIONS:
            raise ValidationError("invalid rule direction")
        r.setdefault("priority", 0)
        r.setdefault("max_depth", self.MAX_DEPTH)
        r.setdefault("offline_policy", "ACTIVE_ONLY")
        r.setdefault("status", "ACTIVE")
        r.setdefault("target_entity_kinds", [])
        r.setdefault("event_payload_equals", {})
        if not isinstance(r["priority"], int):
            raise ValidationError("rule priority must be integer")
        if not isinstance(r["max_depth"], int) or not (1 <= r["max_depth"] <= self.MAX_DEPTH):
            raise ValidationError("rule max_depth must be 1..8")
        if r["offline_policy"] not in ALLOWED_OFFLINE_POLICY:
            raise ValidationError("invalid offline policy")
        if r["status"] not in ALLOWED_RULE_STATUS:
            raise ValidationError("invalid rule status")
        if not isinstance(r["target_entity_kinds"], list) or any(not isinstance(x, str) for x in r["target_entity_kinds"]):
            raise ValidationError("target_entity_kinds must be string list")
        if not isinstance(r["event_payload_equals"], dict):
            raise ValidationError("event_payload_equals must be object")
        if not isinstance(r["consequences"], list) or not r["consequences"]:
            raise ValidationError("causal rule requires at least one consequence template")
        for template in r["consequences"]:
            if not isinstance(template, dict) or template.get("operation") not in ALLOWED_DERIVED_OPERATIONS:
                raise ValidationError("unsupported derived consequence template operation")
            if "target_ref" in template:
                raise ValidationError("rule template cannot hard-code target_ref")
            if template["operation"] in {"SET", "TRANSITION", "INCREMENT", "DECREMENT"} and not template.get("field_path"):
                raise ValidationError("state consequence template requires field_path")
            if "value_from_event" in template and "value" in template:
                raise ValidationError("template cannot define both value and value_from_event")
            if "amount_from_event" in template and "amount" in template:
                raise ValidationError("template cannot define both amount and amount_from_event")
        body = {
            "rule_id": r["rule_id"],
            "world_instance_id": world_instance_id,
            "timeline_id": world["timeline_id"],
            "name": r["name"],
            "trigger_event_type": r["trigger_event_type"],
            "relation_type": r["relation_type"],
            "direction": r["direction"],
            "derived_event_type": r["derived_event_type"],
            "priority": r["priority"],
            "max_depth": r["max_depth"],
            "offline_policy": r["offline_policy"],
            "status": r["status"],
            "target_entity_kinds": r["target_entity_kinds"],
            "event_payload_equals": r["event_payload_equals"],
            "consequences": r["consequences"],
        }
        rhash = sha256_text(canonical_json(body))
        with self._engine_lock, self.runtime._write_lock:
            self.conn.execute(
                "INSERT INTO causal_rules VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    r["rule_id"], world_instance_id, world["timeline_id"], r["name"], r["trigger_event_type"],
                    r["relation_type"], r["direction"], r["derived_event_type"], r["priority"], r["max_depth"],
                    r["offline_policy"], r["status"], canonical_json(body), rhash,
                ),
            )
        body["rule_hash"] = rhash
        return body

    def set_runtime_rule_status(self, rule_id: str, status: str) -> None:
        validate_runtime_id(rule_id, "rule")
        if status not in ALLOWED_RULE_STATUS:
            raise ValidationError("invalid rule status")
        with self._engine_lock, self.runtime._write_lock:
            row = self.conn.execute("SELECT rule_json FROM causal_rules WHERE rule_id=?", (rule_id,)).fetchone()
            if not row:
                raise NotFoundError("rule not found")
            body = json.loads(row["rule_json"])
            body["status"] = status
            rhash = sha256_text(canonical_json(body))
            self.conn.execute("UPDATE causal_rules SET status=?,rule_json=?,rule_hash=? WHERE rule_id=?", (status, canonical_json(body), rhash, rule_id))

    def _rule_set_hash(self, world_instance_id: str) -> str:
        rows = self.conn.execute(
            "SELECT rule_json FROM causal_rules WHERE world_instance_id=? AND status='ACTIVE' ORDER BY priority,rule_id",
            (world_instance_id,),
        ).fetchall()
        return sha256_text(canonical_json([json.loads(r["rule_json"]) for r in rows]))

    def _event_as_dict(self, event: EventEnvelope) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "world_instance_id": event.world_instance_id,
            "timeline_id": event.timeline_id,
            "event_type": event.event_type,
            "occurred_at": copy.deepcopy(event.occurred_at),
            "source": event.source,
            "subjects": copy.deepcopy(event.subjects),
            "payload": copy.deepcopy(event.payload),
            "causality": copy.deepcopy(event.causality),
        }

    def _payload_condition_matches(self, event: EventEnvelope, rule: dict[str, Any]) -> bool:
        event_dict = self._event_as_dict(event)
        for path, expected in rule.get("event_payload_equals", {}).items():
            try:
                actual = _json_path_get(event_dict, path)
            except ValidationError:
                return False
            if actual != expected:
                return False
        return True

    def _subject_aliases(self, world_instance_id: str, subject_ref: str) -> list[str]:
        if subject_ref in SYSTEM_SUBJECTS:
            return []
        if subject_ref.startswith("rt:"):
            try:
                state = self.runtime.get_entity(world_instance_id, subject_ref)
            except NotFoundError:
                return [subject_ref]
            aliases = [subject_ref]
            cref = state.get("canonical_ref")
            if isinstance(cref, str):
                aliases.append(cref)
            return aliases
        return [subject_ref]

    def _relations_for_subject(self, world_instance_id: str, subject_ref: str, rule: dict[str, Any]) -> list[dict[str, Any]]:
        aliases = self._subject_aliases(world_instance_id, subject_ref)
        if not aliases:
            return []
        qmarks = ",".join("?" for _ in aliases)
        rel_filter = "" if rule["relation_type"] == "*" else " AND relation_type=?"
        rel_args = [] if rule["relation_type"] == "*" else [rule["relation_type"]]
        rows: list[sqlite3.Row] = []
        if rule["direction"] in {"OUTGOING", "BOTH"}:
            rows += self.conn.execute(
                f"SELECT * FROM causal_relations WHERE world_instance_id=? AND active=1 AND source_ref IN ({qmarks}){rel_filter} ORDER BY relation_id",
                [world_instance_id, *aliases, *rel_args],
            ).fetchall()
        if rule["direction"] in {"INCOMING", "BOTH"}:
            rows += self.conn.execute(
                f"SELECT * FROM causal_relations WHERE world_instance_id=? AND active=1 AND target_ref IN ({qmarks}){rel_filter} ORDER BY relation_id",
                [world_instance_id, *aliases, *rel_args],
            ).fetchall()
        out = []
        seen = set()
        for row in rows:
            key = row["relation_id"]
            if key in seen:
                continue
            seen.add(key)
            if row["source_ref"] in aliases:
                related = row["target_ref"]
            elif row["target_ref"] in aliases:
                related = row["source_ref"]
            else:
                continue
            out.append({"row": row, "related_ref": related})
        return out

    def _materialize_target(self, world_instance_id: str, ref: str) -> tuple[str | None, str | None]:
        if ref.startswith("rt:"):
            try:
                self.runtime.get_entity(world_instance_id, ref)
                return ref, None
            except NotFoundError:
                return None, "TARGET_NOT_MATERIALIZED"
        rows = self.conn.execute(
            "SELECT entity_runtime_id FROM entity_states WHERE world_instance_id=? AND canonical_ref=? ORDER BY entity_runtime_id",
            (world_instance_id, ref),
        ).fetchall()
        if len(rows) == 0:
            return None, "TARGET_NOT_MATERIALIZED"
        if len(rows) > 1:
            return None, "AMBIGUOUS_CANONICAL_TARGET"
        return rows[0]["entity_runtime_id"], None

    def _materialize_templates(self, event: EventEnvelope, target_ref: str, rule: dict[str, Any]) -> list[dict[str, Any]]:
        event_dict = self._event_as_dict(event)
        out = []
        for i, t in enumerate(rule["consequences"]):
            c = copy.deepcopy(t)
            c["target_ref"] = target_ref
            c["kind"] = "DERIVED"
            c.setdefault("priority", rule["priority"] + i)
            if "value_from_event" in c:
                c["value"] = copy.deepcopy(_json_path_get(event_dict, c.pop("value_from_event")))
            if "amount_from_event" in c:
                amount = _json_path_get(event_dict, c.pop("amount_from_event"))
                multiplier = c.pop("multiplier", 1)
                if not isinstance(amount, (int, float)) or isinstance(amount, bool):
                    raise ValidationError("amount_from_event did not resolve to numeric value")
                if not isinstance(multiplier, (int, float)) or isinstance(multiplier, bool):
                    raise ValidationError("multiplier must be numeric")
                amount *= multiplier
                if amount < 0:
                    raise ValidationError("derived amount cannot be negative")
                c["amount"] = amount
            out.append(c)
        return out

    def _protection_block_reason(self, target_state: dict[str, Any], consequences: list[dict[str, Any]]) -> str | None:
        protection = target_state.get("protection")
        if not isinstance(protection, dict):
            data = target_state.get("data")
            protection = data.get("protection") if isinstance(data, dict) else None
        protection = protection if isinstance(protection, dict) else {}
        for c in consequences:
            if c.get("field_path") != "lifecycle" or c.get("operation") not in {"SET", "TRANSITION"}:
                continue
            if c.get("value") == "DEAD" and protection.get("death") in {"BLOCKED", "STORY_AUTHORITY_ONLY"}:
                return "NARRATIVE_PROTECTION_DEATH"
            if c.get("value") == "DESTROYED" and protection.get("world_mutation_scope") in {"BLOCKED", "STORY_AUTHORITY_ONLY"}:
                return "NARRATIVE_PROTECTION_WORLD_MUTATION"
        return None

    def _offline_block_reason(self, world: dict[str, Any], rule: dict[str, Any], consequences: list[dict[str, Any]]) -> str | None:
        if world["simulation_mode"] != "ROUTINE_OFFLINE":
            return None
        if rule["offline_policy"] != "ROUTINE_SAFE":
            return "OFFLINE_RULE_NOT_ROUTINE_SAFE"
        if rule["derived_event_type"] in PROHIBITED_OFFLINE_EVENT_TYPES:
            return "OFFLINE_MAJOR_EVENT_BLOCKED"
        for c in consequences:
            if c.get("field_path") == "lifecycle" and c.get("value") in {"DEAD", "DESTROYED"}:
                return "OFFLINE_MAJOR_LIFECYCLE_MUTATION_BLOCKED"
        return None

    # ---------- propagation ----------

    def _record_stop(
        self,
        root_event_id: str,
        event_id: str,
        reason: str,
        *,
        rule_id: str | None = None,
        relation_id: str | None = None,
        target_ref: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        event = self.runtime.get_event(event_id)
        body = {
            "root_event_id": root_event_id,
            "event_id": event_id,
            "rule_id": rule_id,
            "relation_id": relation_id,
            "target_ref": target_ref,
            "reason": reason,
            "detail": copy.deepcopy(detail or {}),
        }
        sig = sha256_text(canonical_json(body))
        with self.runtime._write_lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO causal_stops VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new_runtime_id("stop"), root_event_id, event_id, rule_id, relation_id, target_ref, reason,
                    canonical_json(body["detail"]), event.occurred_at["day"], event.occurred_at["tick"], sig,
                ),
            )

    def _get_rule(self, rule_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT rule_json,rule_hash FROM causal_rules WHERE rule_id=?", (rule_id,)).fetchone()
        if not row:
            raise NotFoundError("causal rule not found")
        if sha256_text(row["rule_json"]) != row["rule_hash"]:
            raise IntegrityError("causal rule hash mismatch")
        return json.loads(row["rule_json"])

    def _reserve_expansion(
        self,
        *,
        root_event_id: str,
        parent_event_id: str,
        rule: dict[str, Any],
        relation_id: str,
        subject_ref: str,
        target_ref: str,
        depth: int,
    ) -> dict[str, Any]:
        signature_body = {
            "root_event_id": root_event_id,
            "rule_id": rule["rule_id"],
            "relation_id": relation_id,
            "subject_ref": subject_ref,
            "target_ref": target_ref,
            "derived_event_type": rule["derived_event_type"],
        }
        signature = sha256_text(canonical_json(signature_body))
        with self.runtime._write_lock:
            existing = self.conn.execute("SELECT * FROM causal_expansions WHERE signature=?", (signature,)).fetchone()
            if existing:
                return {"existing": dict(existing), "reserved": False, "signature": signature}
            run = self.conn.execute("SELECT * FROM propagation_runs WHERE root_event_id=?", (root_event_id,)).fetchone()
            if not run:
                raise IntegrityError("propagation run missing during expansion")
            if run["budget_used"] >= run["budget_total"]:
                return {"budget_exhausted": True, "reserved": False, "signature": signature}
            expansion_id = new_runtime_id("expansion")
            action_id = new_runtime_id("action")
            intent_id = new_runtime_id("intent")
            detail = {"signature_body": signature_body}
            self.runtime._begin()
            try:
                # Re-check while holding the write transaction.
                run = self.conn.execute("SELECT * FROM propagation_runs WHERE root_event_id=?", (root_event_id,)).fetchone()
                if run["budget_used"] >= run["budget_total"]:
                    self.runtime._rollback()
                    return {"budget_exhausted": True, "reserved": False, "signature": signature}
                self.conn.execute(
                    "INSERT INTO causal_expansions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        expansion_id, root_event_id, parent_event_id, None, rule["rule_id"], relation_id,
                        subject_ref, target_ref, action_id, intent_id, depth, "RESERVED", signature, canonical_json(detail),
                    ),
                )
                self.conn.execute(
                    "UPDATE propagation_runs SET budget_used=budget_used+1 WHERE root_event_id=?",
                    (root_event_id,),
                )
                self.runtime._commit()
            except sqlite3.IntegrityError:
                self.runtime._rollback()
                existing = self.conn.execute("SELECT * FROM causal_expansions WHERE signature=?", (signature,)).fetchone()
                if existing:
                    return {"existing": dict(existing), "reserved": False, "signature": signature}
                raise
            except Exception:
                self.runtime._rollback()
                raise
        return {
            "reserved": True,
            "signature": signature,
            "expansion_id": expansion_id,
            "action_id": action_id,
            "intent_id": intent_id,
        }

    def _execute_reserved(
        self,
        reservation: dict[str, Any],
        *,
        root_event: EventEnvelope,
        parent_event: EventEnvelope,
        rule: dict[str, Any],
        target_ref: str,
        consequences: list[dict[str, Any]],
        relation_id: str,
        subject_ref: str,
    ) -> tuple[str | None, str | None]:
        if not reservation.get("reserved"):
            existing = reservation.get("existing")
            if not existing:
                return None, "BUDGET_EXHAUSTED"
            if existing["status"] == "APPLIED":
                return existing["child_event_id"], "DUPLICATE_EXPANSION"
            if existing["status"] == "FAILED":
                return None, "PREVIOUS_EXPANSION_FAILED"
            # RESERVED may be an interrupted prior run. Reuse IDs so ActionExecutor idempotency can recover safely.
            expansion_id = existing["expansion_id"]
            action_id = existing["action_id"]
            intent_id = existing["intent_id"]
        else:
            expansion_id = reservation["expansion_id"]
            action_id = reservation["action_id"]
            intent_id = reservation["intent_id"]
        world = self.runtime.get_world(parent_event.world_instance_id)
        target = self.runtime.get_entity(parent_event.world_instance_id, target_ref)
        run = self.conn.execute("SELECT budget_total,budget_used FROM propagation_runs WHERE root_event_id=?", (root_event.event_id,)).fetchone()
        remaining = max(0, run["budget_total"] - run["budget_used"])
        action = {
            "action_id": action_id,
            "intent_id": intent_id,
            "world_instance_id": parent_event.world_instance_id,
            "timeline_id": parent_event.timeline_id,
            "actor_ref": "SYSTEM_RECONCILIATION",
            "action_type": rule["derived_event_type"],
            "parameters": {
                "causal_rule_id": rule["rule_id"],
                "relation_id": relation_id,
                "parent_event_id": parent_event.event_id,
                "subject_ref": subject_ref,
                "target_ref": target_ref,
            },
            "precondition_snapshot": {"entity_versions": {target_ref: target["version"]}},
            "idempotency_key": f"causal:{reservation['signature']}",
            "created_at": clock_point(world["clock_state"]["day"], world["clock_state"]["tick"]),
            "status": "SCHEDULED",
            "source": "SYSTEM_RECONCILIATION",
            "execution_class": "ROUTINE_SAFE" if rule["offline_policy"] == "ROUTINE_SAFE" else "ACTIVE_ONLY",
            "causality": {
                "root_event_id": root_event.event_id,
                "parent_event_id": parent_event.event_id,
                "depth": parent_event.causality["depth"] + 1,
                "cascade_budget_remaining": remaining,
            },
        }
        try:
            result = self.runtime.apply_action(parent_event.world_instance_id, action, consequences)
        except Exception as exc:
            with self.runtime._write_lock:
                self.conn.execute(
                    "UPDATE causal_expansions SET status='FAILED',detail_json=? WHERE expansion_id=?",
                    (canonical_json({"error": repr(exc), "rule_id": rule["rule_id"], "relation_id": relation_id}), expansion_id),
                )
            self._record_stop(
                root_event.event_id, parent_event.event_id, "DERIVED_ACTION_FAILED",
                rule_id=rule["rule_id"], relation_id=relation_id, target_ref=target_ref, detail={"error": repr(exc)},
            )
            return None, "DERIVED_ACTION_FAILED"
        child_event_id = result["event_id"]
        with self.runtime._write_lock:
            self.runtime._begin()
            try:
                self.conn.execute(
                    "UPDATE causal_expansions SET child_event_id=?,status='APPLIED',detail_json=? WHERE expansion_id=?",
                    (
                        child_event_id,
                        canonical_json({"event_id": child_event_id, "idempotent_replay": result.get("idempotent_replay", False)}),
                        expansion_id,
                    ),
                )
                self.conn.execute(
                    "INSERT OR IGNORE INTO causal_scans(root_event_id,event_id,status) VALUES(?,?, 'PENDING')",
                    (root_event.event_id, child_event_id),
                )
                self.runtime._commit()
            except Exception:
                self.runtime._rollback()
                raise
        return child_event_id, None

    def _run_summary(self, root_event_id: str, *, idempotent: bool = False) -> dict[str, Any]:
        run = self.conn.execute("SELECT * FROM propagation_runs WHERE root_event_id=?", (root_event_id,)).fetchone()
        if not run:
            raise NotFoundError("propagation run not found")
        expansions = self.conn.execute(
            "SELECT status,COUNT(*) c FROM causal_expansions WHERE root_event_id=? GROUP BY status",
            (root_event_id,),
        ).fetchall()
        stops = self.conn.execute(
            "SELECT reason,COUNT(*) c FROM causal_stops WHERE root_event_id=? GROUP BY reason ORDER BY reason",
            (root_event_id,),
        ).fetchall()
        child_types = self.conn.execute(
            "SELECT e.event_type,COUNT(*) c FROM causal_expansions x JOIN events e ON e.event_id=x.child_event_id WHERE x.root_event_id=? AND x.status='APPLIED' GROUP BY e.event_type ORDER BY e.event_type",
            (root_event_id,),
        ).fetchall()
        return {
            "root_event_id": root_event_id,
            "status": run["status"],
            "budget_total": run["budget_total"],
            "budget_used": run["budget_used"],
            "rule_set_hash": run["rule_set_hash"],
            "expansions": {r["status"]: r["c"] for r in expansions},
            "stops": {r["reason"]: r["c"] for r in stops},
            "derived_event_types": {r["event_type"]: r["c"] for r in child_types},
            "idempotent_replay": idempotent,
        }

    def propagate_from_event(self, world_instance_id: str, root_event_id: str, *, budget: int | None = None) -> dict[str, Any]:
        with self._engine_lock:
            world = self.runtime.get_world(world_instance_id)
            root = self.runtime.get_event(root_event_id)
            if root.world_instance_id != world_instance_id:
                raise ValidationError("root event belongs to another world")
            if root.causality.get("parent_event_id") is not None or root.causality.get("depth") != 0 or root.causality.get("root_event_id") != root.event_id:
                raise ValidationError("propagation must start from a root event")
            max_root_budget = min(self.DEFAULT_BUDGET, root.causality.get("cascade_budget_remaining", self.DEFAULT_BUDGET))
            requested_budget = max_root_budget if budget is None else budget
            if not isinstance(requested_budget, int) or not (1 <= requested_budget <= max_root_budget):
                raise ValidationError(f"budget must be 1..{max_root_budget}")
            current_ruleset = self._rule_set_hash(world_instance_id)
            with self.runtime._write_lock:
                run = self.conn.execute("SELECT * FROM propagation_runs WHERE root_event_id=?", (root_event_id,)).fetchone()
                if run:
                    if run["world_instance_id"] != world_instance_id:
                        raise IntegrityError("propagation run world mismatch")
                    if run["status"] in {"COMPLETED", "BUDGET_EXHAUSTED"}:
                        return self._run_summary(root_event_id, idempotent=True)
                    if run["status"] == "FAILED":
                        raise ConflictError("failed propagation run requires explicit investigation")
                    if run["rule_set_hash"] != current_ruleset:
                        self.conn.execute("UPDATE propagation_runs SET status='FAILED' WHERE root_event_id=?", (root_event_id,))
                        raise IntegrityError("rule set changed during propagation run")
                else:
                    self.conn.execute(
                        "INSERT INTO propagation_runs(root_event_id,world_instance_id,timeline_id,budget_total,budget_used,status,rule_set_hash,started_day,started_tick,completed_day,completed_tick,result_json) VALUES(?,?,?,?,?,'RUNNING',?,?,?,NULL,NULL,NULL)",
                        (
                            root_event_id, world_instance_id, world["timeline_id"], requested_budget, 0, current_ruleset,
                            root.occurred_at["day"], root.occurred_at["tick"],
                        ),
                    )
                    self.conn.execute(
                        "INSERT INTO causal_scans(root_event_id,event_id,status) VALUES(?,?, 'PENDING')",
                        (root_event_id, root_event_id),
                    )
            budget_exhausted = False
            try:
                while True:
                    with self.runtime._write_lock:
                        scan = self.conn.execute(
                            "SELECT s.event_id FROM causal_scans s JOIN events e ON e.event_id=s.event_id WHERE s.root_event_id=? AND s.status='PENDING' ORDER BY e.sequence LIMIT 1",
                            (root_event_id,),
                        ).fetchone()
                    if not scan:
                        break
                    event = self.runtime.get_event(scan["event_id"])
                    if event.causality["depth"] >= self.MAX_DEPTH:
                        self._record_stop(root_event_id, event.event_id, "MAX_DEPTH_REACHED")
                        with self.runtime._write_lock:
                            self.conn.execute("UPDATE causal_scans SET status='SCANNED' WHERE root_event_id=? AND event_id=?", (root_event_id, event.event_id))
                        continue
                    rows = self.conn.execute(
                        "SELECT rule_json,rule_hash FROM causal_rules WHERE world_instance_id=? AND status='ACTIVE' AND trigger_event_type IN (?, '*') ORDER BY priority,rule_id",
                        (world_instance_id, event.event_type),
                    ).fetchall()
                    for rr in rows:
                        if sha256_text(rr["rule_json"]) != rr["rule_hash"]:
                            raise IntegrityError("causal rule hash mismatch during propagation")
                        rule = json.loads(rr["rule_json"])
                        if event.causality["depth"] + 1 > rule["max_depth"]:
                            self._record_stop(root_event_id, event.event_id, "RULE_MAX_DEPTH", rule_id=rule["rule_id"])
                            continue
                        if not self._payload_condition_matches(event, rule):
                            continue
                        for subject_ref in event.subjects:
                            candidates = self._relations_for_subject(world_instance_id, subject_ref, rule)
                            for candidate in candidates:
                                relation = candidate["row"]
                                target_ref, resolve_error = self._materialize_target(world_instance_id, candidate["related_ref"])
                                if resolve_error:
                                    self._record_stop(
                                        root_event_id, event.event_id, resolve_error, rule_id=rule["rule_id"],
                                        relation_id=relation["relation_id"], target_ref=candidate["related_ref"],
                                    )
                                    continue
                                target = self.runtime.get_entity(world_instance_id, target_ref)
                                allowed_kinds = rule.get("target_entity_kinds", [])
                                if allowed_kinds and target.get("entity_kind") not in allowed_kinds:
                                    continue
                                try:
                                    consequences = self._materialize_templates(event, target_ref, rule)
                                except Exception as exc:
                                    self._record_stop(
                                        root_event_id, event.event_id, "TEMPLATE_RESOLUTION_FAILED", rule_id=rule["rule_id"],
                                        relation_id=relation["relation_id"], target_ref=target_ref, detail={"error": repr(exc)},
                                    )
                                    continue
                                protection_reason = self._protection_block_reason(target, consequences)
                                if protection_reason:
                                    self._record_stop(
                                        root_event_id, event.event_id, protection_reason, rule_id=rule["rule_id"],
                                        relation_id=relation["relation_id"], target_ref=target_ref,
                                    )
                                    continue
                                offline_reason = self._offline_block_reason(world, rule, consequences)
                                if offline_reason:
                                    self._record_stop(
                                        root_event_id, event.event_id, offline_reason, rule_id=rule["rule_id"],
                                        relation_id=relation["relation_id"], target_ref=target_ref,
                                    )
                                    continue
                                reservation = self._reserve_expansion(
                                    root_event_id=root_event_id,
                                    parent_event_id=event.event_id,
                                    rule=rule,
                                    relation_id=relation["relation_id"],
                                    subject_ref=subject_ref,
                                    target_ref=target_ref,
                                    depth=event.causality["depth"] + 1,
                                )
                                if reservation.get("budget_exhausted"):
                                    self._record_stop(
                                        root_event_id, event.event_id, "CASCADE_BUDGET_EXHAUSTED", rule_id=rule["rule_id"],
                                        relation_id=relation["relation_id"], target_ref=target_ref,
                                    )
                                    budget_exhausted = True
                                    break
                                child_id, exec_note = self._execute_reserved(
                                    reservation,
                                    root_event=root,
                                    parent_event=event,
                                    rule=rule,
                                    target_ref=target_ref,
                                    consequences=consequences,
                                    relation_id=relation["relation_id"],
                                    subject_ref=subject_ref,
                                )
                                if exec_note == "DUPLICATE_EXPANSION":
                                    self._record_stop(
                                        root_event_id, event.event_id, "DUPLICATE_EXPANSION", rule_id=rule["rule_id"],
                                        relation_id=relation["relation_id"], target_ref=target_ref,
                                    )
                                if exec_note == "BUDGET_EXHAUSTED":
                                    budget_exhausted = True
                                    break
                            if budget_exhausted:
                                break
                        if budget_exhausted:
                            break
                    with self.runtime._write_lock:
                        self.conn.execute("UPDATE causal_scans SET status='SCANNED' WHERE root_event_id=? AND event_id=?", (root_event_id, event.event_id))
                    if budget_exhausted:
                        break
                now = self.runtime.get_clock(world_instance_id)
                with self.runtime._write_lock:
                    if budget_exhausted:
                        self.conn.execute("UPDATE causal_scans SET status='SKIPPED_BUDGET' WHERE root_event_id=? AND status='PENDING'", (root_event_id,))
                        status = "BUDGET_EXHAUSTED"
                    else:
                        status = "COMPLETED"
                    self.conn.execute(
                        "UPDATE propagation_runs SET status=?,completed_day=?,completed_tick=? WHERE root_event_id=?",
                        (status, now["day"], now["tick"], root_event_id),
                    )
                summary = self._run_summary(root_event_id)
                with self.runtime._write_lock:
                    self.conn.execute("UPDATE propagation_runs SET result_json=? WHERE root_event_id=?", (canonical_json(summary), root_event_id))
                return summary
            except Exception:
                with self.runtime._write_lock:
                    self.conn.execute("UPDATE propagation_runs SET status='FAILED' WHERE root_event_id=?", (root_event_id,))
                raise

    # ---------- automatic mode ----------

    def attach_auto_propagation(self) -> None:
        if self._unsubscribe is not None:
            return

        def handler(event: EventEnvelope) -> None:
            if event.causality.get("depth") != 0:
                return
            try:
                self.propagate_from_event(event.world_instance_id, event.event_id)
            except Exception as exc:
                # EventBus is post-commit. We cannot roll back the root fact; record a fail-closed propagation run where possible.
                with self.runtime._write_lock:
                    run = self.conn.execute("SELECT root_event_id FROM propagation_runs WHERE root_event_id=?", (event.event_id,)).fetchone()
                    if run:
                        self.conn.execute("UPDATE propagation_runs SET status='FAILED' WHERE root_event_id=?", (event.event_id,))

        self._unsubscribe = self.runtime.event_bus.subscribe(handler)

    def detach_auto_propagation(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    # ---------- explanation + integrity ----------

    def explain_event(self, event_id: str) -> dict[str, Any]:
        event = self.runtime.get_event(event_id)
        chain = []
        current = event
        seen = set()
        while True:
            if current.event_id in seen:
                raise IntegrityError("causal event cycle detected in immutable ledger")
            seen.add(current.event_id)
            expansion = self.conn.execute("SELECT rule_id,relation_id,subject_ref,target_ref FROM causal_expansions WHERE child_event_id=?", (current.event_id,)).fetchone()
            chain.append({
                "event_id": current.event_id,
                "event_type": current.event_type,
                "depth": current.causality["depth"],
                "parent_event_id": current.causality["parent_event_id"],
                "rule_id": expansion["rule_id"] if expansion else None,
                "relation_id": expansion["relation_id"] if expansion else None,
                "subject_ref": expansion["subject_ref"] if expansion else None,
                "target_ref": expansion["target_ref"] if expansion else None,
            })
            parent_id = current.causality.get("parent_event_id")
            if parent_id is None:
                break
            current = self.runtime.get_event(parent_id)
        chain.reverse()
        return {"root_event_id": chain[0]["event_id"], "event_id": event_id, "depth": event.causality["depth"], "chain": chain}

    def impact_summary(self, root_event_id: str) -> dict[str, Any]:
        summary = self._run_summary(root_event_id)
        rows = self.conn.execute(
            "SELECT target_ref,COUNT(*) c FROM causal_expansions WHERE root_event_id=? AND status='APPLIED' GROUP BY target_ref ORDER BY target_ref",
            (root_event_id,),
        ).fetchall()
        summary["affected_targets"] = {r["target_ref"]: r["c"] for r in rows}
        return summary

    def verify_relationship_integrity(self, world_instance_id: str) -> dict[str, Any]:
        failures = []
        rows = self.conn.execute("SELECT * FROM causal_relations WHERE world_instance_id=? ORDER BY relation_id", (world_instance_id,)).fetchall()
        for row in rows:
            body = {
                "relation_id": row["relation_id"], "world_instance_id": row["world_instance_id"], "timeline_id": row["timeline_id"],
                "origin": row["origin"], "external_relation_id": row["external_relation_id"], "source_ref": row["source_ref"],
                "target_ref": row["target_ref"], "relation_type": row["relation_type"], "active": bool(row["active"]),
                "metadata": json.loads(row["metadata_json"]),
            }
            if sha256_text(canonical_json(body)) != row["relation_hash"]:
                failures.append({"relation_id": row["relation_id"], "error": "RELATION_HASH_MISMATCH"})
        return {"relations": len(rows), "failures": failures, "status": "PASS" if not failures else "FAIL"}

    def verify_rule_integrity(self, world_instance_id: str) -> dict[str, Any]:
        failures = []
        rows = self.conn.execute("SELECT rule_id,rule_json,rule_hash FROM causal_rules WHERE world_instance_id=? ORDER BY rule_id", (world_instance_id,)).fetchall()
        for row in rows:
            if sha256_text(row["rule_json"]) != row["rule_hash"]:
                failures.append({"rule_id": row["rule_id"], "error": "RULE_HASH_MISMATCH"})
        return {"rules": len(rows), "failures": failures, "status": "PASS" if not failures else "FAIL"}

    def verify_causal_graph(self, world_instance_id: str) -> dict[str, Any]:
        failures = []
        runs = self.conn.execute("SELECT * FROM propagation_runs WHERE world_instance_id=? ORDER BY root_event_id", (world_instance_id,)).fetchall()
        for run in runs:
            if run["budget_used"] > run["budget_total"]:
                failures.append({"root_event_id": run["root_event_id"], "error": "BUDGET_OVERRUN"})
            root = self.runtime.get_event(run["root_event_id"])
            if root.causality["depth"] != 0 or root.causality["parent_event_id"] is not None or root.causality["root_event_id"] != root.event_id:
                failures.append({"root_event_id": root.event_id, "error": "INVALID_ROOT_CAUSALITY"})
        expansions = self.conn.execute(
            "SELECT x.*,p.causality_json pc,c.causality_json cc,c.world_instance_id child_world FROM causal_expansions x JOIN events p ON p.event_id=x.parent_event_id LEFT JOIN events c ON c.event_id=x.child_event_id WHERE x.root_event_id IN (SELECT root_event_id FROM propagation_runs WHERE world_instance_id=?) ORDER BY x.rowid",
            (world_instance_id,),
        ).fetchall()
        for x in expansions:
            if x["status"] != "APPLIED":
                continue
            if x["child_event_id"] is None or x["cc"] is None:
                failures.append({"expansion_id": x["expansion_id"], "error": "APPLIED_EXPANSION_MISSING_CHILD"})
                continue
            pc = json.loads(x["pc"])
            cc = json.loads(x["cc"])
            if x["child_world"] != world_instance_id:
                failures.append({"expansion_id": x["expansion_id"], "error": "CROSS_WORLD_CHILD"})
            if cc.get("parent_event_id") != x["parent_event_id"]:
                failures.append({"expansion_id": x["expansion_id"], "error": "PARENT_LINK_MISMATCH"})
            if cc.get("root_event_id") != x["root_event_id"]:
                failures.append({"expansion_id": x["expansion_id"], "error": "ROOT_LINK_MISMATCH"})
            if cc.get("depth") != pc.get("depth") + 1 or cc.get("depth") != x["depth"]:
                failures.append({"expansion_id": x["expansion_id"], "error": "DEPTH_MISMATCH"})
            if cc.get("depth", 999) > self.MAX_DEPTH:
                failures.append({"expansion_id": x["expansion_id"], "error": "DEPTH_LIMIT_EXCEEDED"})
        return {"runs": len(runs), "expansions": len(expansions), "failures": failures, "status": "PASS" if not failures else "FAIL"}

    def full_integrity_check(self, world_instance_id: str) -> dict[str, Any]:
        checks = {
            "runtime_core": self.runtime.full_integrity_check(world_instance_id),
            "relationships": self.verify_relationship_integrity(world_instance_id),
            "rules": self.verify_rule_integrity(world_instance_id),
            "causal_graph": self.verify_causal_graph(world_instance_id),
        }
        status = "PASS" if all(c["status"] == "PASS" for c in checks.values()) else "FAIL"
        return {"status": status, "checks": checks}
