from __future__ import annotations

import copy
import json
import math
import threading
from typing import Any

from living_runtime import (
    LivingRuntime, ValidationError, IntegrityError, ConflictError, NotFoundError,
    OfflinePolicyError, new_runtime_id, validate_runtime_id, canonical_json,
    sha256_text, clock_point,
)

MEMORY_SOURCES = {"DIRECT_EVENT", "SENSORY", "COMMUNICATION", "INFERENCE", "SYSTEM_VERIFICATION"}
MEMORY_TYPES = {"EVENT", "OBSERVATION", "INTERACTION", "RUMOR", "INFERENCE", "SYSTEM"}
PERSISTENCE = {"STANDARD", "IMPORTANT", "PERMANENT"}
KNOWLEDGE_SOURCES = {"DIRECT_EVENT", "SENSORY", "MEMORY", "COMMUNICATION", "INFERENCE", "SYSTEM_VERIFICATION"}
TRUTH_STATUSES = {"UNKNOWN", "VERIFIED_TRUE", "VERIFIED_FALSE", "CONTESTED"}
REL_DIMS = {"trust", "affinity", "fear", "respect", "obligation"}
REPUTATION_SCOPES = {"GLOBAL", "FACTION", "SETTLEMENT", "PROFESSION", "REGION", "INSTITUTION"}
MAX_RUMOR_HOPS = 4


def _num(v: Any, name: str) -> float:
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(float(v)):
        raise ValidationError(f"{name} must be finite numeric")
    return float(v)


def _bounded(v: Any, name: str, lo: float, hi: float) -> float:
    x = _num(v, name)
    if x < lo or x > hi:
        raise ValidationError(f"{name} must be between {lo} and {hi}")
    return x


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def _json_value_key(v: Any) -> str:
    return canonical_json(v)


class SocialMemorySystem:
    """Persistent social memory, beliefs, directed relationships, rumor propagation and reputation.

    World truth remains owned by LivingRuntime. This subsystem stores what agents remember/believe
    and social consequences of evidence. Append-only evidence is separated from materialized views.
    """

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
                CREATE TABLE IF NOT EXISTS social_memories(
                    memory_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    agent_ref TEXT NOT NULL,
                    subject_ref TEXT,
                    linked_event_id TEXT,
                    recorded_day INTEGER NOT NULL,
                    recorded_tick INTEGER NOT NULL,
                    memory_json TEXT NOT NULL,
                    memory_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_social_memory_agent ON social_memories(world_instance_id,agent_ref,recorded_day,recorded_tick);
                CREATE INDEX IF NOT EXISTS idx_social_memory_subject ON social_memories(world_instance_id,agent_ref,subject_ref);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_social_memory_event_once ON social_memories(world_instance_id,agent_ref,linked_event_id) WHERE linked_event_id IS NOT NULL;

                CREATE TABLE IF NOT EXISTS knowledge_claims(
                    claim_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    agent_ref TEXT NOT NULL,
                    claim_key TEXT NOT NULL,
                    subject_ref TEXT,
                    source_memory_id TEXT,
                    origin_claim_id TEXT NOT NULL,
                    rumor_hop INTEGER NOT NULL CHECK(rumor_hop >= 0),
                    recorded_day INTEGER NOT NULL,
                    recorded_tick INTEGER NOT NULL,
                    claim_json TEXT NOT NULL,
                    claim_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_claim_agent_key ON knowledge_claims(world_instance_id,agent_ref,claim_key);
                CREATE INDEX IF NOT EXISTS idx_claim_origin ON knowledge_claims(world_instance_id,origin_claim_id);

                CREATE TABLE IF NOT EXISTS knowledge_current(
                    world_instance_id TEXT NOT NULL,
                    timeline_id TEXT NOT NULL,
                    agent_ref TEXT NOT NULL,
                    claim_key TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK(version >= 1),
                    knowledge_json TEXT NOT NULL,
                    knowledge_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id,agent_ref,claim_key)
                );

                CREATE TABLE IF NOT EXISTS relationship_events(
                    relationship_event_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    holder_ref TEXT NOT NULL,
                    subject_ref TEXT NOT NULL,
                    idempotency_key TEXT,
                    recorded_day INTEGER NOT NULL,
                    recorded_tick INTEGER NOT NULL,
                    relationship_event_json TEXT NOT NULL,
                    relationship_event_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id,idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_rel_events_pair ON relationship_events(world_instance_id,holder_ref,subject_ref);

                CREATE TABLE IF NOT EXISTS relationships_current(
                    world_instance_id TEXT NOT NULL,
                    timeline_id TEXT NOT NULL,
                    holder_ref TEXT NOT NULL,
                    subject_ref TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK(version >= 1),
                    relationship_json TEXT NOT NULL,
                    relationship_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id,holder_ref,subject_ref)
                );

                CREATE TABLE IF NOT EXISTS reputation_events(
                    reputation_event_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    subject_ref TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_ref TEXT,
                    idempotency_key TEXT,
                    recorded_day INTEGER NOT NULL,
                    recorded_tick INTEGER NOT NULL,
                    reputation_event_json TEXT NOT NULL,
                    reputation_event_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id,idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_rep_events_subject ON reputation_events(world_instance_id,subject_ref,scope_type,scope_ref);

                CREATE TABLE IF NOT EXISTS reputation_current(
                    world_instance_id TEXT NOT NULL,
                    timeline_id TEXT NOT NULL,
                    subject_ref TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_ref_key TEXT NOT NULL,
                    scope_ref TEXT,
                    version INTEGER NOT NULL CHECK(version >= 1),
                    reputation_json TEXT NOT NULL,
                    reputation_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id,subject_ref,scope_type,scope_ref_key)
                );

                CREATE TABLE IF NOT EXISTS rumor_transmissions(
                    transmission_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    speaker_ref TEXT NOT NULL,
                    listener_ref TEXT NOT NULL,
                    source_claim_id TEXT NOT NULL,
                    origin_claim_id TEXT NOT NULL,
                    rumor_hop INTEGER NOT NULL,
                    transmission_json TEXT NOT NULL,
                    transmission_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id,speaker_ref,listener_ref,source_claim_id)
                );

                CREATE TABLE IF NOT EXISTS social_effect_policies(
                    policy_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    policy_key TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('ACTIVE','DISABLED')),
                    policy_json TEXT NOT NULL,
                    policy_hash TEXT NOT NULL,
                    UNIQUE(world_instance_id,policy_key)
                );
                CREATE INDEX IF NOT EXISTS idx_social_policy_event ON social_effect_policies(world_instance_id,event_type,status);

                CREATE TRIGGER IF NOT EXISTS memories_no_update BEFORE UPDATE ON social_memories BEGIN SELECT RAISE(ABORT,'social memories are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS memories_no_delete BEFORE DELETE ON social_memories BEGIN SELECT RAISE(ABORT,'social memories are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS claims_no_update BEFORE UPDATE ON knowledge_claims BEGIN SELECT RAISE(ABORT,'knowledge claims are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS claims_no_delete BEFORE DELETE ON knowledge_claims BEGIN SELECT RAISE(ABORT,'knowledge claims are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS rel_events_no_update BEFORE UPDATE ON relationship_events BEGIN SELECT RAISE(ABORT,'relationship events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS rel_events_no_delete BEFORE DELETE ON relationship_events BEGIN SELECT RAISE(ABORT,'relationship events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS rep_events_no_update BEFORE UPDATE ON reputation_events BEGIN SELECT RAISE(ABORT,'reputation events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS rep_events_no_delete BEFORE DELETE ON reputation_events BEGIN SELECT RAISE(ABORT,'reputation events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS rumor_no_update BEFORE UPDATE ON rumor_transmissions BEGIN SELECT RAISE(ABORT,'rumor transmissions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS rumor_no_delete BEFORE DELETE ON rumor_transmissions BEGIN SELECT RAISE(ABORT,'rumor transmissions are immutable'); END;
                """
            )
            self.conn.execute("INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('social_memory_schema_version',?)", (str(self.SCHEMA_VERSION),))

    # ---------- reference and protection helpers ----------
    def _validate_ref(self, world_instance_id: str, ref: str, *, require_runtime: bool = False) -> dict[str, Any] | None:
        if not isinstance(ref, str) or not ref:
            raise ValidationError("reference required")
        if ref.startswith("rt:"):
            validate_runtime_id(ref)
            return self.runtime.get_entity(world_instance_id, ref)
        if require_runtime:
            raise ValidationError("runtime agent reference required")
        if not self.runtime.canonical_ref_resolves(ref):
            raise ValidationError(f"unknown canonical reference: {ref}")
        return None

    def _agent(self, world_instance_id: str, agent_ref: str) -> dict[str, Any]:
        state = self._validate_ref(world_instance_id, agent_ref, require_runtime=True)
        if state is None or state.get("entity_kind") != "AGENT":
            raise ValidationError("agent_ref must point to runtime AGENT")
        if state.get("lifecycle") != "ACTIVE":
            raise ValidationError("agent must be ACTIVE")
        return state

    def _relationship_change_allowed(self, holder_state: dict[str, Any]) -> bool:
        p = holder_state.get("protection", {}) if isinstance(holder_state.get("protection", {}), dict) else {}
        return p.get("relationship_change") not in {"BLOCKED", "STORY_AUTHORITY_ONLY"}

    # ---------- memories ----------
    def record_memory(
        self, world_instance_id: str, agent_ref: str, *, memory_type: str, content: dict[str, Any],
        source: str, subject_ref: str | None = None, confidence: float = 1.0,
        salience: float = 50.0, emotional_weight: float = 0.0, persistence: str = "STANDARD",
        linked_event_id: str | None = None, tags: list[str] | None = None, truth_status: str = "UNKNOWN",
    ) -> dict[str, Any]:
        world = self.runtime.get_world(world_instance_id)
        self._agent(world_instance_id, agent_ref)
        if memory_type not in MEMORY_TYPES:
            raise ValidationError("invalid memory_type")
        if source not in MEMORY_SOURCES:
            raise ValidationError("invalid memory source")
        if not isinstance(content, dict):
            raise ValidationError("memory content must be object")
        confidence = _bounded(confidence, "confidence", 0, 1)
        salience = _bounded(salience, "salience", 0, 100)
        emotional_weight = _bounded(emotional_weight, "emotional_weight", -100, 100)
        if persistence not in PERSISTENCE:
            raise ValidationError("invalid persistence")
        if truth_status not in TRUTH_STATUSES:
            raise ValidationError("invalid truth_status")
        if truth_status in {"VERIFIED_TRUE", "VERIFIED_FALSE"} and source not in {"DIRECT_EVENT", "SYSTEM_VERIFICATION"}:
            raise ValidationError("only authoritative evidence may create verified memory")
        if subject_ref is not None:
            self._validate_ref(world_instance_id, subject_ref)
        if linked_event_id is not None:
            ev = self.runtime.get_event(linked_event_id)
            if ev.world_instance_id != world_instance_id:
                raise ValidationError("linked event belongs to another world")
        tags = tags or []
        if not isinstance(tags, list) or any(not isinstance(t, str) or not t for t in tags):
            raise ValidationError("invalid tags")
        clock = world["clock_state"]
        mid = new_runtime_id("memory")
        body = {
            "memory_id": mid, "world_instance_id": world_instance_id, "timeline_id": world["timeline_id"],
            "agent_ref": agent_ref, "subject_ref": subject_ref, "memory_type": memory_type,
            "source": source, "content": copy.deepcopy(content), "confidence": confidence,
            "salience": salience, "emotional_weight": emotional_weight, "persistence": persistence,
            "linked_event_id": linked_event_id, "tags": sorted(set(tags)), "truth_status": truth_status,
            "recorded_at": clock_point(clock["day"], clock["tick"]),
        }
        h = sha256_text(canonical_json(body))
        with self._lock, self.runtime._write_lock:
            self.conn.execute(
                "INSERT INTO social_memories VALUES(?,?,?,?,?,?,?,?,?,?)",
                (mid, world_instance_id, world["timeline_id"], agent_ref, subject_ref, linked_event_id,
                 clock["day"], clock["tick"], canonical_json(body), h),
            )
        body["memory_hash"] = h
        return body

    def remember_event(
        self, world_instance_id: str, agent_ref: str, event_id: str, *, subject_ref: str | None = None,
        salience: float = 70, emotional_weight: float = 0, tags: list[str] | None = None,
        effect_policy_key: str | None = None,
    ) -> dict[str, Any]:
        ev = self.runtime.get_event(event_id)
        if ev.world_instance_id != world_instance_id:
            raise ValidationError("event belongs to another world")
        with self._lock, self.runtime._write_lock:
            existing = self.conn.execute("SELECT memory_json,memory_hash FROM social_memories WHERE world_instance_id=? AND agent_ref=? AND linked_event_id=?", (world_instance_id, agent_ref, event_id)).fetchone()
        if existing:
            if sha256_text(existing["memory_json"]) != existing["memory_hash"]:
                raise IntegrityError("existing event memory hash mismatch")
            memory = json.loads(existing["memory_json"]); memory["memory_hash"] = existing["memory_hash"]; memory["idempotent"] = True
            with self._lock, self.runtime._write_lock:
                crow = self.conn.execute("SELECT claim_json,claim_hash FROM knowledge_claims WHERE world_instance_id=? AND agent_ref=? AND source_memory_id=? ORDER BY recorded_day,recorded_tick,claim_id LIMIT 1", (world_instance_id, agent_ref, memory["memory_id"])).fetchone()
            if not crow or sha256_text(crow["claim_json"]) != crow["claim_hash"]:
                raise IntegrityError("event memory claim missing or corrupt")
            claim = json.loads(crow["claim_json"]); claim["claim_hash"] = crow["claim_hash"]; claim["idempotent"] = True
            return {"memory": memory, "claim": claim, "idempotent": True}
        subject_ref = subject_ref or (ev.subjects[0] if ev.subjects else None)
        memory = self.record_memory(
            world_instance_id, agent_ref, memory_type="EVENT", source="DIRECT_EVENT", subject_ref=subject_ref,
            content={"event_id": ev.event_id, "event_type": ev.event_type, "subjects": ev.subjects, "payload": ev.payload},
            confidence=1.0, salience=salience, emotional_weight=emotional_weight,
            persistence="IMPORTANT" if salience >= 70 else "STANDARD", linked_event_id=event_id,
            tags=(tags or []) + [f"event:{ev.event_type}"], truth_status="VERIFIED_TRUE",
        )
        claim = self.add_claim(
            world_instance_id, agent_ref, claim_key=f"event:{event_id}:occurred", subject_ref=subject_ref,
            predicate="event_occurred", value={"event_id": event_id, "event_type": ev.event_type, "occurred": True},
            confidence=1.0, source="DIRECT_EVENT", truth_status="VERIFIED_TRUE", source_memory_id=memory["memory_id"],
            metadata={"event_id": event_id, "event_type": ev.event_type, "effect_policy_key": effect_policy_key},
        )
        return {"memory": memory, "claim": claim}

    def recall_memories(self, world_instance_id: str, agent_ref: str, *, subject_ref: str | None = None,
                        tags: list[str] | None = None, limit: int = 10) -> list[dict[str, Any]]:
        self._agent(world_instance_id, agent_ref)
        if not isinstance(limit, int) or limit <= 0 or limit > 1000:
            raise ValidationError("limit must be 1..1000")
        if subject_ref is not None:
            self._validate_ref(world_instance_id, subject_ref)
        world = self.runtime.get_world(world_instance_id)
        day = world["clock_state"]["day"]
        with self._lock, self.runtime._write_lock:
            if subject_ref is None:
                rows = self.conn.execute("SELECT * FROM social_memories WHERE world_instance_id=? AND agent_ref=?", (world_instance_id, agent_ref)).fetchall()
            else:
                rows = self.conn.execute("SELECT * FROM social_memories WHERE world_instance_id=? AND agent_ref=? AND subject_ref=?", (world_instance_id, agent_ref, subject_ref)).fetchall()
        wanted = set(tags or [])
        out = []
        for row in rows:
            if sha256_text(row["memory_json"]) != row["memory_hash"]:
                raise IntegrityError("memory hash mismatch")
            m = json.loads(row["memory_json"])
            if wanted and not wanted.issubset(set(m.get("tags", []))):
                continue
            age = max(0, day - m["recorded_at"]["day"])
            half_life = 30.0 if m["persistence"] == "STANDARD" else 120.0
            decay = 1.0 if m["persistence"] == "PERMANENT" else 0.5 ** (age / half_life)
            score = (m["salience"] * 0.6 + abs(m["emotional_weight"]) * 0.25 + m["confidence"] * 15.0) * decay
            m["recall_score"] = round(score, 6)
            out.append(m)
        out.sort(key=lambda x: (-x["recall_score"], -x["recorded_at"]["day"], -x["recorded_at"]["tick"], x["memory_id"]))
        return out[:limit]

    # ---------- knowledge ----------
    def add_claim(
        self, world_instance_id: str, agent_ref: str, *, claim_key: str, predicate: str, value: Any,
        confidence: float, source: str, truth_status: str = "UNKNOWN", subject_ref: str | None = None,
        source_memory_id: str | None = None, origin_claim_id: str | None = None, rumor_hop: int = 0,
        provenance_chain: list[str] | None = None, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        world = self.runtime.get_world(world_instance_id)
        self._agent(world_instance_id, agent_ref)
        if not isinstance(claim_key, str) or not claim_key.strip() or len(claim_key) > 256:
            raise ValidationError("invalid claim_key")
        if not isinstance(predicate, str) or not predicate.strip() or len(predicate) > 128:
            raise ValidationError("invalid predicate")
        confidence = _bounded(confidence, "confidence", 0, 1)
        if source not in KNOWLEDGE_SOURCES:
            raise ValidationError("invalid knowledge source")
        if truth_status not in TRUTH_STATUSES:
            raise ValidationError("invalid truth status")
        if truth_status in {"VERIFIED_TRUE", "VERIFIED_FALSE"} and source not in {"DIRECT_EVENT", "SYSTEM_VERIFICATION"}:
            raise ValidationError("non-authoritative source cannot verify world truth")
        if not isinstance(rumor_hop, int) or rumor_hop < 0 or rumor_hop > MAX_RUMOR_HOPS:
            raise ValidationError("invalid rumor_hop")
        if subject_ref is not None:
            self._validate_ref(world_instance_id, subject_ref)
        if source_memory_id is not None:
            validate_runtime_id(source_memory_id, "memory")
            with self.runtime._write_lock:
                row = self.conn.execute("SELECT agent_ref,world_instance_id FROM social_memories WHERE memory_id=?", (source_memory_id,)).fetchone()
            if not row or row["agent_ref"] != agent_ref or row["world_instance_id"] != world_instance_id:
                raise ValidationError("source memory does not belong to agent/world")
        provenance_chain = list(provenance_chain or [agent_ref])
        if not provenance_chain or provenance_chain[-1] != agent_ref or len(provenance_chain) != len(set(provenance_chain)):
            raise ValidationError("invalid provenance chain")
        if len(provenance_chain) - 1 != rumor_hop:
            raise ValidationError("rumor_hop does not match provenance chain")
        cid = new_runtime_id("claim")
        origin_claim_id = origin_claim_id or cid
        validate_runtime_id(origin_claim_id, "claim")
        if truth_status == "VERIFIED_TRUE":
            self._reject_conflicting_verified_truth(world_instance_id, agent_ref, claim_key, value)
        clock = world["clock_state"]
        body = {
            "claim_id": cid, "world_instance_id": world_instance_id, "timeline_id": world["timeline_id"],
            "agent_ref": agent_ref, "claim_key": claim_key, "subject_ref": subject_ref, "predicate": predicate,
            "value": copy.deepcopy(value), "confidence": confidence, "source": source, "truth_status": truth_status,
            "source_memory_id": source_memory_id, "origin_claim_id": origin_claim_id, "rumor_hop": rumor_hop,
            "provenance_chain": provenance_chain, "metadata": copy.deepcopy(metadata or {}),
            "recorded_at": clock_point(clock["day"], clock["tick"]),
        }
        h = sha256_text(canonical_json(body))
        with self._lock, self.runtime._write_lock:
            self.runtime._begin()
            try:
                self.conn.execute(
                    "INSERT INTO knowledge_claims VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (cid, world_instance_id, world["timeline_id"], agent_ref, claim_key, subject_ref, source_memory_id,
                     origin_claim_id, rumor_hop, clock["day"], clock["tick"], canonical_json(body), h),
                )
                self._rebuild_knowledge_current_tx(world_instance_id, agent_ref, claim_key)
                self.runtime._commit()
            except Exception:
                self.runtime._rollback()
                raise
        body["claim_hash"] = h
        return body

    def _reject_conflicting_verified_truth(self, world_instance_id: str, agent_ref: str, claim_key: str, value: Any) -> None:
        with self.runtime._write_lock:
            rows = self.conn.execute("SELECT claim_json,claim_hash FROM knowledge_claims WHERE world_instance_id=? AND agent_ref=? AND claim_key=?", (world_instance_id,agent_ref,claim_key)).fetchall()
        target = _json_value_key(value)
        for row in rows:
            if sha256_text(row["claim_json"]) != row["claim_hash"]:
                raise IntegrityError("claim hash mismatch")
            c = json.loads(row["claim_json"])
            if c["truth_status"] == "VERIFIED_TRUE" and _json_value_key(c["value"]) != target:
                raise IntegrityError("conflicting VERIFIED_TRUE claims")

    def _derive_knowledge(self, claims: list[dict[str, Any]], version: int) -> dict[str, Any]:
        groups: dict[str, dict[str, Any]] = {}
        for c in claims:
            k = _json_value_key(c["value"])
            g = groups.setdefault(k, {"value": c["value"], "origins": {}, "verified_true": False, "verified_false": False, "latest": c["recorded_at"]})
            origin = c["origin_claim_id"]
            g["origins"][origin] = max(float(c["confidence"]), float(g["origins"].get(origin, 0.0)))
            g["verified_true"] = g["verified_true"] or c["truth_status"] == "VERIFIED_TRUE"
            g["verified_false"] = g["verified_false"] or c["truth_status"] == "VERIFIED_FALSE"
            if (c["recorded_at"]["day"], c["recorded_at"]["tick"]) > (g["latest"]["day"], g["latest"]["tick"]):
                g["latest"] = c["recorded_at"]
        alternatives = []
        for key, g in groups.items():
            conf = 1.0
            for c in g["origins"].values():
                conf *= 1.0 - c
            conf = 1.0 - conf
            authority = 3 if g["verified_true"] else (0 if g["verified_false"] else 1)
            alternatives.append({
                "value": g["value"], "confidence": round(conf,6), "independent_origins": len(g["origins"]),
                "verified_true": g["verified_true"], "verified_false": g["verified_false"], "authority_rank": authority,
                "value_key": key,
            })
        alternatives.sort(key=lambda x: (-x["authority_rank"], -x["confidence"], x["value_key"]))
        verified = [a for a in alternatives if a["verified_true"]]
        if len(verified) > 1:
            raise IntegrityError("conflicting materialized verified truths")
        chosen = alternatives[0]
        nonfalse = [a for a in alternatives if not a["verified_false"] and a["confidence"] >= 0.05]
        status = "VERIFIED_TRUE" if chosen["verified_true"] else ("CONTESTED" if len(nonfalse) > 1 else "UNKNOWN")
        return {
            "version": version, "claim_count": len(claims), "current_value": chosen["value"],
            "confidence": chosen["confidence"], "truth_status": status,
            "alternatives": [{k:v for k,v in a.items() if k not in {"authority_rank","value_key"}} for a in alternatives],
        }

    def _rebuild_knowledge_current_tx(self, world_instance_id: str, agent_ref: str, claim_key: str) -> dict[str, Any]:
        rows = self.conn.execute("SELECT claim_json,claim_hash FROM knowledge_claims WHERE world_instance_id=? AND agent_ref=? AND claim_key=? ORDER BY recorded_day,recorded_tick,claim_id", (world_instance_id,agent_ref,claim_key)).fetchall()
        if not rows:
            raise IntegrityError("cannot materialize empty knowledge")
        claims=[]
        for row in rows:
            if sha256_text(row["claim_json"]) != row["claim_hash"]:
                raise IntegrityError("claim hash mismatch")
            claims.append(json.loads(row["claim_json"]))
        old = self.conn.execute("SELECT version FROM knowledge_current WHERE world_instance_id=? AND agent_ref=? AND claim_key=?", (world_instance_id,agent_ref,claim_key)).fetchone()
        version = (old["version"] + 1) if old else 1
        d = self._derive_knowledge(claims, version)
        body = {
            "world_instance_id": world_instance_id, "timeline_id": claims[-1]["timeline_id"], "agent_ref": agent_ref,
            "claim_key": claim_key, "subject_ref": claims[-1].get("subject_ref"), "predicate": claims[-1].get("predicate"), **d,
        }
        h = sha256_text(canonical_json(body))
        self.conn.execute(
            "INSERT INTO knowledge_current VALUES(?,?,?,?,?,?,?) ON CONFLICT(world_instance_id,agent_ref,claim_key) DO UPDATE SET version=excluded.version,knowledge_json=excluded.knowledge_json,knowledge_hash=excluded.knowledge_hash",
            (world_instance_id, claims[-1]["timeline_id"], agent_ref, claim_key, version, canonical_json(body), h),
        )
        body["knowledge_hash"] = h
        return body

    def get_knowledge(self, world_instance_id: str, agent_ref: str, claim_key: str) -> dict[str, Any] | None:
        self._agent(world_instance_id, agent_ref)
        with self._lock, self.runtime._write_lock:
            row = self.conn.execute("SELECT knowledge_json,knowledge_hash FROM knowledge_current WHERE world_instance_id=? AND agent_ref=? AND claim_key=?", (world_instance_id,agent_ref,claim_key)).fetchone()
        if not row:
            return None
        if sha256_text(row["knowledge_json"]) != row["knowledge_hash"]:
            raise IntegrityError("knowledge current hash mismatch")
        return json.loads(row["knowledge_json"])

    def verify_claim(self, world_instance_id: str, agent_ref: str, *, claim_key: str, predicate: str, value: Any,
                     is_true: bool, subject_ref: str | None = None, metadata: dict[str,Any] | None = None) -> dict[str,Any]:
        return self.add_claim(
            world_instance_id, agent_ref, claim_key=claim_key, predicate=predicate, value=value, confidence=1.0,
            source="SYSTEM_VERIFICATION", truth_status="VERIFIED_TRUE" if is_true else "VERIFIED_FALSE",
            subject_ref=subject_ref, metadata=metadata,
        )

    # ---------- relationships ----------
    def get_relationship(self, world_instance_id: str, holder_ref: str, subject_ref: str) -> dict[str, Any]:
        self._agent(world_instance_id, holder_ref)
        self._validate_ref(world_instance_id, subject_ref)
        with self._lock, self.runtime._write_lock:
            row = self.conn.execute("SELECT relationship_json,relationship_hash FROM relationships_current WHERE world_instance_id=? AND holder_ref=? AND subject_ref=?", (world_instance_id,holder_ref,subject_ref)).fetchone()
        if not row:
            return {"holder_ref": holder_ref, "subject_ref": subject_ref, "version": 0, "trust": 0.0, "affinity": 0.0, "fear": 0.0, "respect": 0.0, "obligation": 0.0, "evidence_count": 0}
        if sha256_text(row["relationship_json"]) != row["relationship_hash"]:
            raise IntegrityError("relationship hash mismatch")
        return json.loads(row["relationship_json"])

    def apply_relationship_delta(self, world_instance_id: str, holder_ref: str, subject_ref: str, deltas: dict[str, Any], *,
                                 reason: str, source_memory_id: str | None = None, source_event_id: str | None = None,
                                 idempotency_key: str | None = None, weight: float = 1.0) -> dict[str, Any]:
        world = self.runtime.get_world(world_instance_id)
        holder = self._agent(world_instance_id, holder_ref)
        self._validate_ref(world_instance_id, subject_ref)
        if holder_ref == subject_ref:
            raise ValidationError("self relationship not allowed")
        if not self._relationship_change_allowed(holder):
            raise ValidationError("relationship change blocked by narrative protection")
        if not isinstance(deltas, dict) or not deltas or any(k not in REL_DIMS for k in deltas):
            raise ValidationError("invalid relationship deltas")
        weight = _bounded(weight, "weight", 0, 1)
        nd = {k: _bounded(v, f"delta.{k}", -200, 200) * weight for k,v in deltas.items()}
        if source_memory_id is not None:
            validate_runtime_id(source_memory_id, "memory")
        if source_event_id is not None:
            self.runtime.get_event(source_event_id)
        clock=world["clock_state"]
        with self._lock, self.runtime._write_lock:
            if idempotency_key:
                row=self.conn.execute("SELECT relationship_event_json FROM relationship_events WHERE world_instance_id=? AND idempotency_key=?",(world_instance_id,idempotency_key)).fetchone()
                if row:
                    body=json.loads(row["relationship_event_json"]); body["idempotent"]=True; return body
            self.runtime._begin()
            try:
                currow=self.conn.execute("SELECT relationship_json,relationship_hash FROM relationships_current WHERE world_instance_id=? AND holder_ref=? AND subject_ref=?",(world_instance_id,holder_ref,subject_ref)).fetchone()
                if currow:
                    if sha256_text(currow["relationship_json"]) != currow["relationship_hash"]: raise IntegrityError("relationship hash mismatch")
                    cur=json.loads(currow["relationship_json"])
                else:
                    cur={"trust":0.0,"affinity":0.0,"fear":0.0,"respect":0.0,"obligation":0.0,"version":0,"evidence_count":0}
                eid=new_runtime_id("relationevent")
                event_body={"relationship_event_id":eid,"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"holder_ref":holder_ref,"subject_ref":subject_ref,"deltas":nd,"reason":reason,"source_memory_id":source_memory_id,"source_event_id":source_event_id,"idempotency_key":idempotency_key,"recorded_at":clock_point(clock["day"],clock["tick"])}
                eh=sha256_text(canonical_json(event_body))
                self.conn.execute("INSERT INTO relationship_events VALUES(?,?,?,?,?,?,?,?,?,?)",(eid,world_instance_id,world["timeline_id"],holder_ref,subject_ref,idempotency_key,clock["day"],clock["tick"],canonical_json(event_body),eh))
                nxt={k:float(cur.get(k,0.0)) for k in REL_DIMS}
                for k,v in nd.items():
                    lo=0.0 if k=="fear" else -100.0
                    nxt[k]=round(_clamp(nxt[k]+v,lo,100.0),6)
                rel={"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"holder_ref":holder_ref,"subject_ref":subject_ref,"version":int(cur.get("version",0))+1,**nxt,"evidence_count":int(cur.get("evidence_count",0))+1}
                rh=sha256_text(canonical_json(rel))
                self.conn.execute("INSERT INTO relationships_current VALUES(?,?,?,?,?,?,?) ON CONFLICT(world_instance_id,holder_ref,subject_ref) DO UPDATE SET version=excluded.version,relationship_json=excluded.relationship_json,relationship_hash=excluded.relationship_hash",(world_instance_id,world["timeline_id"],holder_ref,subject_ref,rel["version"],canonical_json(rel),rh))
                self.runtime._commit()
            except Exception:
                self.runtime._rollback(); raise
        rel["relationship_hash"]=rh; rel["relationship_event_id"]=eid
        return rel

    # ---------- reputation ----------
    @staticmethod
    def _scope_key(scope_ref: str | None) -> str:
        return scope_ref or "__GLOBAL__"

    def get_reputation(self, world_instance_id: str, subject_ref: str, *, scope_type: str="GLOBAL", scope_ref: str | None=None) -> dict[str,Any]:
        self._validate_ref(world_instance_id,subject_ref)
        if scope_type not in REPUTATION_SCOPES: raise ValidationError("invalid reputation scope")
        if scope_type == "GLOBAL" and scope_ref is not None: raise ValidationError("GLOBAL reputation must not have scope_ref")
        if scope_type != "GLOBAL":
            if scope_ref is None: raise ValidationError("non-global reputation requires scope_ref")
            self._validate_ref(world_instance_id,scope_ref)
        key=self._scope_key(scope_ref)
        with self._lock,self.runtime._write_lock:
            row=self.conn.execute("SELECT reputation_json,reputation_hash FROM reputation_current WHERE world_instance_id=? AND subject_ref=? AND scope_type=? AND scope_ref_key=?",(world_instance_id,subject_ref,scope_type,key)).fetchone()
        if not row:
            return {"subject_ref":subject_ref,"scope_type":scope_type,"scope_ref":scope_ref,"version":0,"score":0.0,"evidence_count":0}
        if sha256_text(row["reputation_json"]) != row["reputation_hash"]: raise IntegrityError("reputation hash mismatch")
        return json.loads(row["reputation_json"])

    def apply_reputation_delta(self, world_instance_id: str, subject_ref: str, delta: float, *, scope_type: str="GLOBAL", scope_ref: str | None=None,
                               reason: str, source_memory_id: str | None=None, source_event_id: str | None=None,
                               idempotency_key: str | None=None, weight: float=1.0) -> dict[str,Any]:
        world=self.runtime.get_world(world_instance_id)
        self._validate_ref(world_instance_id,subject_ref)
        if scope_type not in REPUTATION_SCOPES: raise ValidationError("invalid reputation scope")
        if scope_type=="GLOBAL" and scope_ref is not None: raise ValidationError("GLOBAL reputation must not have scope_ref")
        if scope_type!="GLOBAL":
            if scope_ref is None: raise ValidationError("non-global reputation requires scope_ref")
            self._validate_ref(world_instance_id,scope_ref)
        weight=_bounded(weight,"weight",0,1)
        delta=_bounded(delta,"delta",-200,200)*weight
        key=self._scope_key(scope_ref); clock=world["clock_state"]
        with self._lock,self.runtime._write_lock:
            if idempotency_key:
                row=self.conn.execute("SELECT reputation_event_json FROM reputation_events WHERE world_instance_id=? AND idempotency_key=?",(world_instance_id,idempotency_key)).fetchone()
                if row:
                    body=json.loads(row["reputation_event_json"]); body["idempotent"]=True; return body
            self.runtime._begin()
            try:
                currow=self.conn.execute("SELECT reputation_json,reputation_hash FROM reputation_current WHERE world_instance_id=? AND subject_ref=? AND scope_type=? AND scope_ref_key=?",(world_instance_id,subject_ref,scope_type,key)).fetchone()
                if currow:
                    if sha256_text(currow["reputation_json"])!=currow["reputation_hash"]: raise IntegrityError("reputation hash mismatch")
                    cur=json.loads(currow["reputation_json"])
                else: cur={"version":0,"score":0.0,"evidence_count":0}
                eid=new_runtime_id("reputationevent")
                eb={"reputation_event_id":eid,"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"subject_ref":subject_ref,"scope_type":scope_type,"scope_ref":scope_ref,"delta":delta,"reason":reason,"source_memory_id":source_memory_id,"source_event_id":source_event_id,"idempotency_key":idempotency_key,"recorded_at":clock_point(clock["day"],clock["tick"])}
                eh=sha256_text(canonical_json(eb))
                self.conn.execute("INSERT INTO reputation_events VALUES(?,?,?,?,?,?,?,?,?,?,?)",(eid,world_instance_id,world["timeline_id"],subject_ref,scope_type,scope_ref,idempotency_key,clock["day"],clock["tick"],canonical_json(eb),eh))
                rep={"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"subject_ref":subject_ref,"scope_type":scope_type,"scope_ref":scope_ref,"version":int(cur.get("version",0))+1,"score":round(_clamp(float(cur.get("score",0))+delta,-100,100),6),"evidence_count":int(cur.get("evidence_count",0))+1}
                rh=sha256_text(canonical_json(rep))
                self.conn.execute("INSERT INTO reputation_current VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(world_instance_id,subject_ref,scope_type,scope_ref_key) DO UPDATE SET version=excluded.version,reputation_json=excluded.reputation_json,reputation_hash=excluded.reputation_hash",(world_instance_id,world["timeline_id"],subject_ref,scope_type,key,scope_ref,rep["version"],canonical_json(rep),rh))
                self.runtime._commit()
            except Exception:
                self.runtime._rollback(); raise
        rep["reputation_hash"]=rh; rep["reputation_event_id"]=eid
        return rep

    # ---------- social policies / witnessed events ----------
    def register_effect_policy(self, world_instance_id: str, policy: dict[str,Any]) -> dict[str,Any]:
        world=self.runtime.get_world(world_instance_id); p=copy.deepcopy(policy)
        for k in ["policy_key","event_type","subject_index"]:
            if k not in p: raise ValidationError(f"missing social policy field: {k}")
        if not isinstance(p["policy_key"],str) or not p["policy_key"]: raise ValidationError("invalid policy_key")
        if not isinstance(p["event_type"],str) or not p["event_type"]: raise ValidationError("invalid event_type")
        if not isinstance(p["subject_index"],int) or p["subject_index"]<0: raise ValidationError("invalid subject_index")
        p.setdefault("relationship_deltas",{}); p.setdefault("reputation_delta",0.0); p.setdefault("reputation_scope_type","GLOBAL"); p.setdefault("reputation_scope_ref",None); p.setdefault("rumor_effect_factor",0.0); p.setdefault("status","ACTIVE")
        if not isinstance(p["relationship_deltas"],dict) or any(k not in REL_DIMS for k in p["relationship_deltas"]): raise ValidationError("invalid relationship deltas")
        for k,v in p["relationship_deltas"].items(): _bounded(v,f"relationship_deltas.{k}",-200,200)
        _bounded(p["reputation_delta"],"reputation_delta",-200,200); _bounded(p["rumor_effect_factor"],"rumor_effect_factor",0,1)
        if p["reputation_scope_type"] not in REPUTATION_SCOPES: raise ValidationError("invalid reputation scope")
        if p["reputation_scope_type"]=="GLOBAL" and p["reputation_scope_ref"] is not None: raise ValidationError("GLOBAL policy scope_ref must be null")
        if p["reputation_scope_type"]!="GLOBAL": self._validate_ref(world_instance_id,p["reputation_scope_ref"])
        if p["status"] not in {"ACTIVE","DISABLED"}: raise ValidationError("invalid policy status")
        pid=p.get("policy_id") or new_runtime_id("socialpolicy"); validate_runtime_id(pid,"socialpolicy")
        body={"policy_id":pid,"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],**p}; h=sha256_text(canonical_json(body))
        with self._lock,self.runtime._write_lock:
            self.conn.execute("INSERT INTO social_effect_policies VALUES(?,?,?,?,?,?,?,?)",(pid,world_instance_id,world["timeline_id"],p["policy_key"],p["event_type"],p["status"],canonical_json(body),h))
        body["policy_hash"]=h; return body

    def _get_effect_policy(self, world_instance_id: str, *, policy_key: str | None=None, event_type: str | None=None) -> dict[str,Any] | None:
        with self._lock,self.runtime._write_lock:
            if policy_key:
                row=self.conn.execute("SELECT policy_json,policy_hash FROM social_effect_policies WHERE world_instance_id=? AND policy_key=? AND status='ACTIVE'",(world_instance_id,policy_key)).fetchone()
            else:
                rows=self.conn.execute("SELECT policy_json,policy_hash FROM social_effect_policies WHERE world_instance_id=? AND event_type=? AND status='ACTIVE' ORDER BY policy_key",(world_instance_id,event_type)).fetchall()
                if len(rows)>1: raise ConflictError("multiple active social effect policies for event type")
                row=rows[0] if rows else None
        if not row: return None
        if sha256_text(row["policy_json"])!=row["policy_hash"]: raise IntegrityError("social policy hash mismatch")
        return json.loads(row["policy_json"])

    def witness_event(self, world_instance_id: str, observer_ref: str, event_id: str, *, policy_key: str | None=None,
                      salience: float=70, emotional_weight: float=0) -> dict[str,Any]:
        ev=self.runtime.get_event(event_id)
        if ev.world_instance_id!=world_instance_id: raise ValidationError("event belongs to another world")
        policy=self._get_effect_policy(world_instance_id,policy_key=policy_key,event_type=ev.event_type)
        if policy and policy["event_type"]!=ev.event_type: raise ValidationError("policy/event type mismatch")
        idx=policy["subject_index"] if policy else 0
        subject=ev.subjects[idx] if len(ev.subjects)>idx else (ev.subjects[0] if ev.subjects else None)
        remembered=self.remember_event(world_instance_id,observer_ref,event_id,subject_ref=subject,salience=salience,emotional_weight=emotional_weight,effect_policy_key=policy["policy_key"] if policy else None)
        effects={"relationship":None,"reputation":None}
        if policy and subject is not None and subject!=observer_ref:
            if policy["relationship_deltas"]:
                effects["relationship"]=self.apply_relationship_delta(world_instance_id,observer_ref,subject,policy["relationship_deltas"],reason=f"witness:{ev.event_type}",source_memory_id=remembered["memory"]["memory_id"],source_event_id=event_id,idempotency_key=f"witness-rel:{observer_ref}:{event_id}:{policy['policy_id']}")
            if float(policy["reputation_delta"])!=0:
                effects["reputation"]=self.apply_reputation_delta(world_instance_id,subject,policy["reputation_delta"],scope_type=policy["reputation_scope_type"],scope_ref=policy["reputation_scope_ref"],reason=f"witness:{ev.event_type}",source_memory_id=remembered["memory"]["memory_id"],source_event_id=event_id,idempotency_key=f"witness-rep:{observer_ref}:{event_id}:{policy['policy_id']}")
        return {**remembered,"policy":policy,"effects":effects}

    # ---------- rumors ----------
    def transmit_claim(self, world_instance_id: str, speaker_ref: str, listener_ref: str, source_claim_id: str, *, routine_safe: bool=False) -> dict[str,Any]:
        world=self.runtime.get_world(world_instance_id)
        self._agent(world_instance_id,speaker_ref); self._agent(world_instance_id,listener_ref)
        if speaker_ref==listener_ref: raise ValidationError("cannot transmit rumor to self")
        if world["simulation_mode"]=="ROUTINE_OFFLINE" and not routine_safe:
            raise OfflinePolicyError("rumor transmission is blocked offline unless explicitly ROUTINE_SAFE")
        validate_runtime_id(source_claim_id,"claim")
        with self._lock,self.runtime._write_lock:
            row=self.conn.execute("SELECT claim_json,claim_hash FROM knowledge_claims WHERE claim_id=? AND world_instance_id=? AND agent_ref=?",(source_claim_id,world_instance_id,speaker_ref)).fetchone()
            existing=self.conn.execute("SELECT transmission_json,transmission_hash FROM rumor_transmissions WHERE world_instance_id=? AND speaker_ref=? AND listener_ref=? AND source_claim_id=?",(world_instance_id,speaker_ref,listener_ref,source_claim_id)).fetchone()
        if existing:
            if sha256_text(existing["transmission_json"])!=existing["transmission_hash"]: raise IntegrityError("transmission hash mismatch")
            out=json.loads(existing["transmission_json"]); out["idempotent"]=True; return out
        if not row: raise NotFoundError("speaker does not own source claim")
        if sha256_text(row["claim_json"])!=row["claim_hash"]: raise IntegrityError("source claim hash mismatch")
        src=json.loads(row["claim_json"])
        chain=list(src["provenance_chain"])
        if listener_ref in chain: raise ConflictError("rumor provenance cycle blocked")
        hop=int(src["rumor_hop"])+1
        if hop>MAX_RUMOR_HOPS: raise ConflictError("maximum rumor hops reached")
        trust=self.get_relationship(world_instance_id,listener_ref,speaker_ref)["trust"]
        trust_factor=0.35 + 0.65*((float(trust)+100.0)/200.0)
        confidence=round(float(src["confidence"])*trust_factor*0.85,6)
        status="ACCEPTED" if confidence>=0.05 else "DISMISSED_LOW_CONFIDENCE"
        tid=new_runtime_id("rumor")
        body={"transmission_id":tid,"world_instance_id":world_instance_id,"timeline_id":world["timeline_id"],"speaker_ref":speaker_ref,"listener_ref":listener_ref,"source_claim_id":source_claim_id,"origin_claim_id":src["origin_claim_id"],"rumor_hop":hop,"source_confidence":src["confidence"],"listener_trust":trust,"resulting_confidence":confidence,"status":status,"provenance_chain":chain+[listener_ref]}
        h=sha256_text(canonical_json(body))
        with self._lock,self.runtime._write_lock:
            self.conn.execute("INSERT INTO rumor_transmissions VALUES(?,?,?,?,?,?,?,?,?,?)",(tid,world_instance_id,world["timeline_id"],speaker_ref,listener_ref,source_claim_id,src["origin_claim_id"],hop,canonical_json(body),h))
        if status!="ACCEPTED": body["transmission_hash"]=h; return body
        memory=self.record_memory(world_instance_id,listener_ref,memory_type="RUMOR",source="COMMUNICATION",subject_ref=src.get("subject_ref"),content={"speaker_ref":speaker_ref,"claim_key":src["claim_key"],"predicate":src["predicate"],"value":src["value"]},confidence=confidence,salience=min(100,30+abs(float(src.get("metadata",{}).get("social_salience",0)))),emotional_weight=0,persistence="STANDARD",tags=["rumor"],truth_status="UNKNOWN")
        claim=self.add_claim(world_instance_id,listener_ref,claim_key=src["claim_key"],subject_ref=src.get("subject_ref"),predicate=src["predicate"],value=src["value"],confidence=confidence,source="COMMUNICATION",truth_status="UNKNOWN",source_memory_id=memory["memory_id"],origin_claim_id=src["origin_claim_id"],rumor_hop=hop,provenance_chain=chain+[listener_ref],metadata=src.get("metadata",{}))
        effects=self._apply_rumor_effects(world_instance_id,listener_ref,claim,memory)
        body.update({"transmission_hash":h,"listener_memory_id":memory["memory_id"],"listener_claim_id":claim["claim_id"],"effects":effects})
        return body

    def _apply_rumor_effects(self, world_instance_id: str, listener_ref: str, claim: dict[str,Any], memory: dict[str,Any]) -> dict[str,Any]:
        meta=claim.get("metadata",{}); key=meta.get("effect_policy_key")
        if not key: return {"relationship":None,"reputation":None}
        policy=self._get_effect_policy(world_instance_id,policy_key=key)
        if not policy: return {"relationship":None,"reputation":None}
        factor=float(policy.get("rumor_effect_factor",0.0))*float(claim["confidence"])
        subject=claim.get("subject_ref")
        if factor<=0 or subject is None or subject==listener_ref: return {"relationship":None,"reputation":None}
        rel=None; rep=None
        if policy["relationship_deltas"]:
            rel=self.apply_relationship_delta(world_instance_id,listener_ref,subject,policy["relationship_deltas"],reason=f"rumor:{policy['event_type']}",source_memory_id=memory["memory_id"],idempotency_key=f"rumor-rel:{listener_ref}:{claim['claim_id']}",weight=factor)
        if float(policy["reputation_delta"])!=0:
            rep=self.apply_reputation_delta(world_instance_id,subject,policy["reputation_delta"],scope_type=policy["reputation_scope_type"],scope_ref=policy["reputation_scope_ref"],reason=f"rumor:{policy['event_type']}",source_memory_id=memory["memory_id"],idempotency_key=f"rumor-rep:{listener_ref}:{claim['claim_id']}",weight=factor)
        return {"relationship":rel,"reputation":rep}

    # ---------- brain projection ----------
    def project_social_perception(self, brain: Any, world_instance_id: str, agent_ref: str, target_refs: list[str]) -> dict[str,Any]:
        self._agent(world_instance_id,agent_ref)
        if not isinstance(target_refs,list) or not target_refs: raise ValidationError("target_refs required")
        observations=[]
        for ref in sorted(set(target_refs)):
            self._validate_ref(world_instance_id,ref)
            rel=self.get_relationship(world_instance_id,agent_ref,ref)
            rep=self.get_reputation(world_instance_id,ref)
            with self._lock,self.runtime._write_lock:
                rows=self.conn.execute("SELECT knowledge_json,knowledge_hash FROM knowledge_current WHERE world_instance_id=? AND agent_ref=? AND knowledge_json LIKE ?",(world_instance_id,agent_ref,f'%\"subject_ref\":\"{ref}\"%')).fetchall()
            known=0; contested=0; strongest=0.0
            for row in rows:
                if sha256_text(row["knowledge_json"])!=row["knowledge_hash"]: raise IntegrityError("knowledge current hash mismatch")
                k=json.loads(row["knowledge_json"]); known+=1; contested += int(k["truth_status"]=="CONTESTED"); strongest=max(strongest,float(k["confidence"]))
            facts={"relationship":{"trust":rel["trust"],"affinity":rel["affinity"],"fear":rel["fear"],"respect":rel["respect"],"obligation":rel["obligation"]},"reputation":{"global":rep["score"]},"knowledge":{"known_claims":known,"contested_claims":contested},"flags":{"trusted":rel["trust"]>=30,"untrusted":rel["trust"]<=-30,"feared":rel["fear"]>=50,"respected":rel["respect"]>=30 or rep["score"]>=30,"notorious":rep["score"]<=-30}}
            observations.append({"target_ref":ref,"perceived_kind":self.runtime.get_entity(world_instance_id,ref)["entity_kind"] if ref.startswith("rt:") else None,"facts":facts,"confidence":max(0.5,strongest)})
        return brain.record_perception(world_instance_id,agent_ref,observations,source="MEMORY")

    # ---------- replay / integrity ----------
    def _replay_relationship_pair(self, world_instance_id: str, holder_ref: str, subject_ref: str) -> dict[str,Any]:
        with self.runtime._write_lock:
            rows=self.conn.execute("SELECT relationship_event_json,relationship_event_hash FROM relationship_events WHERE world_instance_id=? AND holder_ref=? AND subject_ref=? ORDER BY recorded_day,recorded_tick,relationship_event_id",(world_instance_id,holder_ref,subject_ref)).fetchall()
        cur={"trust":0.0,"affinity":0.0,"fear":0.0,"respect":0.0,"obligation":0.0,"version":0,"evidence_count":0}
        for row in rows:
            if sha256_text(row["relationship_event_json"])!=row["relationship_event_hash"]: raise IntegrityError("relationship event hash mismatch")
            e=json.loads(row["relationship_event_json"])
            for k,v in e["deltas"].items(): cur[k]=round(_clamp(cur[k]+float(v),0 if k=="fear" else -100,100),6)
            cur["version"]+=1; cur["evidence_count"]+=1
        return cur

    def _replay_reputation(self, world_instance_id: str, subject_ref: str, scope_type: str, scope_ref: str|None) -> dict[str,Any]:
        with self.runtime._write_lock:
            if scope_ref is None:
                rows=self.conn.execute("SELECT reputation_event_json,reputation_event_hash FROM reputation_events WHERE world_instance_id=? AND subject_ref=? AND scope_type=? AND scope_ref IS NULL ORDER BY recorded_day,recorded_tick,reputation_event_id",(world_instance_id,subject_ref,scope_type)).fetchall()
            else:
                rows=self.conn.execute("SELECT reputation_event_json,reputation_event_hash FROM reputation_events WHERE world_instance_id=? AND subject_ref=? AND scope_type=? AND scope_ref=? ORDER BY recorded_day,recorded_tick,reputation_event_id",(world_instance_id,subject_ref,scope_type,scope_ref)).fetchall()
        score=0.0; n=0
        for row in rows:
            if sha256_text(row["reputation_event_json"])!=row["reputation_event_hash"]: raise IntegrityError("reputation event hash mismatch")
            e=json.loads(row["reputation_event_json"]); score=round(_clamp(score+float(e["delta"]),-100,100),6); n+=1
        return {"score":score,"version":n,"evidence_count":n}

    def full_integrity_check(self, world_instance_id: str) -> dict[str,Any]:
        failures=[]
        with self._lock,self.runtime._write_lock:
            hash_tables=[("social_memories","memory_json","memory_hash","memory_id"),("knowledge_claims","claim_json","claim_hash","claim_id"),("knowledge_current","knowledge_json","knowledge_hash","claim_key"),("relationship_events","relationship_event_json","relationship_event_hash","relationship_event_id"),("relationships_current","relationship_json","relationship_hash","subject_ref"),("reputation_events","reputation_event_json","reputation_event_hash","reputation_event_id"),("reputation_current","reputation_json","reputation_hash","subject_ref"),("rumor_transmissions","transmission_json","transmission_hash","transmission_id"),("social_effect_policies","policy_json","policy_hash","policy_id")]
            for table,jc,hc,idc in hash_tables:
                rows=self.conn.execute(f"SELECT {jc},{hc},{idc} FROM {table} WHERE world_instance_id=?",(world_instance_id,)).fetchall()
                for r in rows:
                    if sha256_text(r[jc])!=r[hc]: failures.append(f"{table}:HASH_MISMATCH:{r[idc]}")
            # current knowledge replay
            rows=self.conn.execute("SELECT agent_ref,claim_key,knowledge_json FROM knowledge_current WHERE world_instance_id=?",(world_instance_id,)).fetchall()
            for r in rows:
                cr=self.conn.execute("SELECT claim_json,claim_hash FROM knowledge_claims WHERE world_instance_id=? AND agent_ref=? AND claim_key=? ORDER BY recorded_day,recorded_tick,claim_id",(world_instance_id,r["agent_ref"],r["claim_key"])).fetchall()
                try:
                    claims=[]
                    for c in cr:
                        if sha256_text(c["claim_json"])!=c["claim_hash"]: raise IntegrityError("claim hash mismatch")
                        claims.append(json.loads(c["claim_json"]))
                    material=json.loads(r["knowledge_json"]); derived=self._derive_knowledge(claims,material["version"])
                    for key in ["claim_count","current_value","confidence","truth_status","alternatives"]:
                        if material.get(key)!=derived.get(key): failures.append(f"KNOWLEDGE_REPLAY_MISMATCH:{r['agent_ref']}:{r['claim_key']}:{key}"); break
                except Exception as exc: failures.append(f"KNOWLEDGE_REPLAY_ERROR:{r['agent_ref']}:{r['claim_key']}:{type(exc).__name__}")
            # relationship replay
            rows=self.conn.execute("SELECT relationship_json FROM relationships_current WHERE world_instance_id=?",(world_instance_id,)).fetchall()
            for r in rows:
                try:
                    m=json.loads(r["relationship_json"]); holder=m.get("holder_ref","?"); subject=m.get("subject_ref","?")
                    if holder=="?" or subject=="?": raise IntegrityError("relationship materialization missing endpoint")
                    d=self._replay_relationship_pair(world_instance_id,holder,subject)
                    if any(m.get(k)!=d.get(k) for k in ["trust","affinity","fear","respect","obligation","version","evidence_count"]): failures.append(f"REL_REPLAY_MISMATCH:{holder}:{subject}")
                except Exception as exc:
                    failures.append(f"REL_REPLAY_ERROR:{locals().get('holder','?')}:{locals().get('subject','?')}:{type(exc).__name__}")
                    continue
            # reputation replay
            rows=self.conn.execute("SELECT reputation_json FROM reputation_current WHERE world_instance_id=?",(world_instance_id,)).fetchall()
            for r in rows:
                try:
                    m=json.loads(r["reputation_json"]); subject=m.get("subject_ref","?"); scope=m.get("scope_type","?")
                    if subject=="?" or scope=="?": raise IntegrityError("reputation materialization missing identity")
                    d=self._replay_reputation(world_instance_id,subject,scope,m.get("scope_ref"))
                    if any(m.get(k)!=d.get(k) for k in ["score","version","evidence_count"]): failures.append(f"REP_REPLAY_MISMATCH:{subject}:{scope}")
                except Exception as exc:
                    failures.append(f"REP_REPLAY_ERROR:{locals().get('subject','?')}:{type(exc).__name__}")
                    continue
            # provenance cycle/hop
            rows=self.conn.execute("SELECT claim_json FROM knowledge_claims WHERE world_instance_id=?",(world_instance_id,)).fetchall()
            for r in rows:
                c=json.loads(r["claim_json"]); chain=c["provenance_chain"]
                if len(chain)!=len(set(chain)) or len(chain)-1!=c["rumor_hop"] or c["rumor_hop"]>MAX_RUMOR_HOPS: failures.append(f"CLAIM_PROVENANCE_INVALID:{c['claim_id']}")
        return {"status":"PASS" if not failures else "FAIL","failures":failures}

    def integrity_guard(self, world_instance_id: str, *, upstream_guard: Any | None=None) -> dict[str,Any]:
        upstream = upstream_guard(world_instance_id) if upstream_guard else self.runtime.integrity_guard(world_instance_id)
        social = self.full_integrity_check(world_instance_id)
        ok = upstream["status"]=="PASS" and social["status"]=="PASS"
        if not ok:
            with self.runtime._write_lock: self.conn.execute("UPDATE worlds SET status='CORRUPT_BLOCKED' WHERE world_instance_id=?",(world_instance_id,))
        return {"status":"PASS" if ok else "FAIL","upstream":upstream,"social":social}
