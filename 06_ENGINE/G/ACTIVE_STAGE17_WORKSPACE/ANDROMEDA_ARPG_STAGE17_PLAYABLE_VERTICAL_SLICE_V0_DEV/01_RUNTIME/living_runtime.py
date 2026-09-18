from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
import threading
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

MASTER_VERSION = "V2.0.1"
MASTER_RELEASE_SHA256 = "6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2"
SUPPORTED_MASTER_RELEASES = {
    MASTER_RELEASE_SHA256: "V2.0.1",
}

RUNTIME_ID_RE = re.compile(r"^rt:([a-z][a-z0-9_]*):([0-9a-f]{8}-[0-9a-f]{4}-[47][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$")


class RuntimeErrorBase(Exception):
    pass


class ValidationError(RuntimeErrorBase):
    pass


class IntegrityError(RuntimeErrorBase):
    pass


class ConflictError(RuntimeErrorBase):
    pass


class NotFoundError(RuntimeErrorBase):
    pass


class OfflinePolicyError(RuntimeErrorBase):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_runtime_id(record_type: str) -> str:
    return f"rt:{record_type}:{uuid.uuid4()}"


def validate_runtime_id(value: str, expected_type: str | None = None) -> None:
    if not isinstance(value, str):
        raise ValidationError("runtime id must be a string")
    match = RUNTIME_ID_RE.fullmatch(value)
    if not match:
        raise ValidationError(f"invalid runtime id: {value}")
    if expected_type is not None and match.group(1) != expected_type:
        raise ValidationError(f"runtime id type mismatch: expected {expected_type}, got {match.group(1)}")


def clock_point(day: int, tick: int) -> dict[str, int]:
    return {"day": day, "tick": tick}


def _deep_get(obj: dict[str, Any], path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise ValidationError(f"field path not found: {path}")
        cur = cur[part]
    return cur


def _deep_set(obj: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur: dict[str, Any] = obj
    for part in parts[:-1]:
        nxt = cur.get(part)
        if nxt is None:
            nxt = {}
            cur[part] = nxt
        if not isinstance(nxt, dict):
            raise ValidationError(f"non-object path segment: {part}")
        cur = nxt
    cur[parts[-1]] = value


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    sequence: int
    world_instance_id: str
    timeline_id: str
    event_type: str
    occurred_at: dict[str, int]
    source: str
    subjects: list[str]
    payload: dict[str, Any]
    causality: dict[str, Any]
    integrity: dict[str, Any]


class EventBus:
    """In-process post-commit event fan-out. Handlers cannot mutate committed history."""

    def __init__(self) -> None:
        self._handlers: list[Callable[[EventEnvelope], None]] = []
        self._lock = threading.RLock()

    def subscribe(self, handler: Callable[[EventEnvelope], None]) -> Callable[[], None]:
        if not callable(handler):
            raise ValidationError("handler must be callable")
        with self._lock:
            self._handlers.append(handler)

        def unsubscribe() -> None:
            with self._lock:
                if handler in self._handlers:
                    self._handlers.remove(handler)

        return unsubscribe

    def publish(self, event: EventEnvelope) -> list[Exception]:
        with self._lock:
            handlers = tuple(self._handlers)
        failures: list[Exception] = []
        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:  # post-commit subscribers must not roll back truth
                failures.append(exc)
        return failures


class LivingRuntime:
    SCHEMA_VERSION = 1

    def __init__(self, db_path: str | Path = ":memory:", *, master_release_path: str | Path | None = None) -> None:
        self.db_path = str(db_path)
        self.master_release_path = str(master_release_path) if master_release_path is not None else None
        self.master_version_detected = MASTER_VERSION
        self.master_release_sha256_detected = MASTER_RELEASE_SHA256
        self.canonical_ids: set[str] | None = None
        if self.master_release_path is not None:
            self.canonical_ids = self._load_canonical_ids(self.master_release_path)
        self.conn = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self._write_lock = threading.RLock()
        self._shutdown_hooks: list[Callable[[], None]] = []
        self.event_bus = EventBus()
        self._initialize_schema()

    def register_shutdown_hook(self, hook: Callable[[], None]) -> Callable[[], None]:
        if not callable(hook):
            raise ValidationError("shutdown hook must be callable")
        with self._write_lock:
            self._shutdown_hooks.append(hook)
        return hook

    def close(self) -> None:
        with self._write_lock:
            hooks = tuple(reversed(self._shutdown_hooks))
            self._shutdown_hooks.clear()
        for hook in hooks:
            hook()
        self.conn.close()

    @property
    def master_version(self) -> str:
        return self.master_version_detected

    @property
    def master_release_sha256(self) -> str:
        return self.master_release_sha256_detected

    @staticmethod
    def _file_sha256(path: str | Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _load_canonical_ids(self, master_release_path: str | Path) -> set[str]:
        actual = self._file_sha256(master_release_path)
        version = SUPPORTED_MASTER_RELEASES.get(actual)
        if version is None:
            raise IntegrityError(f"master release hash mismatch/unsupported: {actual}")
        self.master_version_detected = version
        self.master_release_sha256_detected = actual
        index_name = "ANDROMEDA_CODEX_MASTER/02_ATLAS/STAGE_08_REFERENCE/01_DATA/ATLAS_ENTITY_INDEX_V1_0.json"
        with zipfile.ZipFile(master_release_path, "r") as zf:
            try:
                data = json.loads(zf.read(index_name))
            except KeyError as exc:
                raise IntegrityError("canonical entity index missing from master release") from exc
            entries = data.get("entries")
            if not isinstance(entries, list) or not entries:
                raise IntegrityError("canonical entity index is invalid or empty")
            ids = {entry.get("id") for entry in entries if isinstance(entry, dict) and isinstance(entry.get("id"), str)}
            if len(ids) != data.get("count"):
                raise IntegrityError("canonical entity index count mismatch")
        return ids

    def canonical_ref_resolves(self, canonical_ref: str) -> bool:
        if self.canonical_ids is None:
            raise IntegrityError("canonical resolver unavailable; master release path required")
        return canonical_ref in self.canonical_ids

    def _initialize_schema(self) -> None:
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runtime_meta(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS worlds(
                    world_instance_id TEXT PRIMARY KEY,
                    timeline_id TEXT NOT NULL UNIQUE,
                    mode TEXT NOT NULL CHECK(mode IN ('PRIVATE','SHARED')),
                    owner_scope TEXT NOT NULL,
                    seed INTEGER NOT NULL CHECK(seed >= 0),
                    simulation_mode TEXT NOT NULL CHECK(simulation_mode IN ('FULL','ACTIVE','AGGREGATE','ROUTINE_OFFLINE')),
                    status TEXT NOT NULL CHECK(status IN ('INITIALIZING','ACTIVE','PAUSED','ARCHIVED','CORRUPT_BLOCKED')),
                    master_version TEXT NOT NULL,
                    release_sha256 TEXT NOT NULL,
                    clock_id TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS clocks(
                    clock_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL UNIQUE REFERENCES worlds(world_instance_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
                    epoch_id TEXT NOT NULL,
                    day INTEGER NOT NULL CHECK(day >= 0),
                    tick INTEGER NOT NULL CHECK(tick >= 0),
                    ticks_per_day INTEGER NOT NULL CHECK(ticks_per_day > 0),
                    state TEXT NOT NULL CHECK(state IN ('RUNNING','PAUSED'))
                );
                CREATE TABLE IF NOT EXISTS bootstrap_states(
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    entity_runtime_id TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    state_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, entity_runtime_id)
                );
                CREATE TABLE IF NOT EXISTS entity_states(
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    entity_runtime_id TEXT NOT NULL,
                    state_id TEXT NOT NULL,
                    origin TEXT NOT NULL CHECK(origin IN ('CANONICAL_BACKED','RUNTIME_BORN')),
                    canonical_ref TEXT,
                    entity_kind TEXT NOT NULL,
                    lifecycle TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK(version >= 0),
                    updated_day INTEGER NOT NULL CHECK(updated_day >= 0),
                    updated_tick INTEGER NOT NULL CHECK(updated_tick >= 0),
                    state_json TEXT NOT NULL,
                    state_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, entity_runtime_id)
                );
                CREATE INDEX IF NOT EXISTS idx_entity_canonical_ref ON entity_states(world_instance_id, canonical_ref);
                CREATE TABLE IF NOT EXISTS events(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    world_instance_id TEXT NOT NULL REFERENCES worlds(world_instance_id) ON DELETE CASCADE,
                    timeline_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_day INTEGER NOT NULL,
                    occurred_tick INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    subjects_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    causality_json TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_events_world_seq ON events(world_instance_id, sequence);
                CREATE TABLE IF NOT EXISTS consequences(
                    consequence_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE RESTRICT,
                    world_instance_id TEXT NOT NULL,
                    timeline_id TEXT NOT NULL,
                    target_ref TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('DIRECT','DERIVED','SCHEDULED')),
                    operation TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PLANNED','APPLIED','BLOCKED','FAILED','SUPERSEDED')),
                    consequence_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS causal_ledger(
                    ledger_entry_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL,
                    timeline_id TEXT NOT NULL,
                    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE RESTRICT,
                    root_event_id TEXT NOT NULL,
                    mutations_json TEXT NOT NULL,
                    recorded_day INTEGER NOT NULL,
                    recorded_tick INTEGER NOT NULL,
                    ledger_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency(
                    world_instance_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS recoveries(
                    recovery_id TEXT PRIMARY KEY,
                    world_instance_id TEXT NOT NULL,
                    timeline_id TEXT NOT NULL,
                    target_ref TEXT NOT NULL,
                    destroyed_at_day INTEGER NOT NULL,
                    due_at_day INTEGER NOT NULL,
                    policy TEXT NOT NULL CHECK(policy='REGENERATE_7_UNIVERSE_DAYS'),
                    status TEXT NOT NULL CHECK(status IN ('SCHEDULED','RECOVERING','COMPLETED','BLOCKED_BY_AUTHORIAL_OVERRIDE')),
                    recovery_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_recovery_due ON recoveries(world_instance_id, due_at_day, status);
                CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON causal_ledger BEGIN SELECT RAISE(ABORT, 'ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON causal_ledger BEGIN SELECT RAISE(ABORT, 'ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS bootstrap_no_update BEFORE UPDATE ON bootstrap_states BEGIN SELECT RAISE(ABORT, 'bootstrap is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS bootstrap_no_delete BEFORE DELETE ON bootstrap_states BEGIN SELECT RAISE(ABORT, 'bootstrap is immutable'); END;
                """
            )
            self.conn.execute("INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('schema_version',?)", (str(self.SCHEMA_VERSION),))

    def _begin(self) -> None:
        self.conn.execute("BEGIN IMMEDIATE")

    def _commit(self) -> None:
        self.conn.execute("COMMIT")

    def _rollback(self) -> None:
        self.conn.execute("ROLLBACK")

    def create_world(
        self,
        owner_scope: str,
        seed: int,
        *,
        mode: str = "PRIVATE",
        ticks_per_day: int = 24,
        epoch_id: str = "STELLAR_RUNTIME_EPOCH",
        world_instance_id: str | None = None,
        timeline_id: str | None = None,
        clock_id: str | None = None,
    ) -> dict[str, Any]:
        if not owner_scope:
            raise ValidationError("owner_scope required")
        if seed < 0:
            raise ValidationError("seed must be >= 0")
        if mode not in {"PRIVATE", "SHARED"}:
            raise ValidationError("invalid world mode")
        if ticks_per_day <= 0:
            raise ValidationError("ticks_per_day must be > 0")
        world_instance_id = world_instance_id or new_runtime_id("world")
        timeline_id = timeline_id or new_runtime_id("timeline")
        clock_id = clock_id or new_runtime_id("clock")
        validate_runtime_id(world_instance_id, "world")
        validate_runtime_id(timeline_id, "timeline")
        validate_runtime_id(clock_id, "clock")
        with self._write_lock:
            self._begin()
            try:
                self.conn.execute(
                    "INSERT INTO worlds VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        world_instance_id,
                        timeline_id,
                        mode,
                        owner_scope,
                        seed,
                        "FULL",
                        "ACTIVE",
                        self.master_version_detected,
                        self.master_release_sha256_detected,
                        clock_id,
                    ),
                )
                self.conn.execute(
                    "INSERT INTO clocks VALUES(?,?,?,?,?,?,?)",
                    (clock_id, world_instance_id, epoch_id, 0, 0, ticks_per_day, "RUNNING"),
                )
                self._commit()
            except Exception:
                self._rollback()
                raise
        return self.get_world(world_instance_id)

    def get_world(self, world_instance_id: str) -> dict[str, Any]:
        with self._write_lock:
            row = self.conn.execute("SELECT * FROM worlds WHERE world_instance_id=?", (world_instance_id,)).fetchone()
            if not row:
                raise NotFoundError("world not found")
            clock = self.get_clock(world_instance_id)
        return {
            "world_instance_id": row["world_instance_id"],
            "timeline_id": row["timeline_id"],
            "mode": row["mode"],
            "owner_scope": row["owner_scope"],
            "baseline": {"master_version": row["master_version"], "release_sha256": row["release_sha256"]},
            "seed": row["seed"],
            "clock": row["clock_id"],
            "simulation_mode": row["simulation_mode"],
            "status": row["status"],
            "clock_state": clock,
        }

    def get_clock(self, world_instance_id: str) -> dict[str, Any]:
        with self._write_lock:
            row = self.conn.execute("SELECT * FROM clocks WHERE world_instance_id=?", (world_instance_id,)).fetchone()
            if not row:
                raise NotFoundError("clock not found")
        return {
            "clock_id": row["clock_id"],
            "epoch_id": row["epoch_id"],
            "day": row["day"],
            "tick": row["tick"],
            "ticks_per_day": row["ticks_per_day"],
            "state": row["state"],
        }

    def set_simulation_mode(self, world_instance_id: str, mode: str) -> None:
        if mode not in {"FULL", "ACTIVE", "AGGREGATE", "ROUTINE_OFFLINE"}:
            raise ValidationError("invalid simulation mode")
        with self._write_lock:
            cur = self.conn.execute("UPDATE worlds SET simulation_mode=? WHERE world_instance_id=?", (mode, world_instance_id))
            if cur.rowcount == 0:
                raise NotFoundError("world not found")

    def set_clock_state(self, world_instance_id: str, state: str) -> None:
        if state not in {"RUNNING", "PAUSED"}:
            raise ValidationError("invalid clock state")
        with self._write_lock:
            cur = self.conn.execute("UPDATE clocks SET state=? WHERE world_instance_id=?", (state, world_instance_id))
            if cur.rowcount == 0:
                raise NotFoundError("world not found")

    def _clock_after_ticks(self, clock: dict[str, Any], delta_ticks: int) -> tuple[int, int]:
        total = clock["day"] * clock["ticks_per_day"] + clock["tick"] + delta_ticks
        return divmod(total, clock["ticks_per_day"])

    def advance_ticks(self, world_instance_id: str, delta_ticks: int, *, source: str = "SYSTEM_CLOCK") -> EventEnvelope:
        if not isinstance(delta_ticks, int) or delta_ticks <= 0:
            raise ValidationError("delta_ticks must be a positive integer")
        allowed_sources = {"SYSTEM_CLOCK", "SYSTEM_RECONCILIATION"}
        if source not in allowed_sources:
            raise ValidationError("invalid clock source")
        with self._write_lock:
            self._begin()
            try:
                world = self.get_world(world_instance_id)
                clock = world["clock_state"]
                if clock["state"] != "RUNNING":
                    raise ConflictError("clock is paused")
                new_day, new_tick = self._clock_after_ticks(clock, delta_ticks)
                self.conn.execute(
                    "UPDATE clocks SET day=?, tick=? WHERE world_instance_id=?",
                    (new_day, new_tick, world_instance_id),
                )
                event = self._append_event_tx(
                    world_instance_id=world_instance_id,
                    event_type="CLOCK_ADVANCED",
                    source=source,
                    subjects=[world["clock"]],
                    payload={
                        "delta_ticks": delta_ticks,
                        "from": clock_point(clock["day"], clock["tick"]),
                        "to": clock_point(new_day, new_tick),
                    },
                    occurred_at=clock_point(new_day, new_tick),
                    causality=None,
                )
                self._append_ledger_tx(event, [{"kind": "CLOCK", "from": event.payload["from"], "to": event.payload["to"]}])
                self._commit()
            except Exception:
                self._rollback()
                raise
        self.event_bus.publish(event)
        return event

    def register_entity(self, world_instance_id: str, state: dict[str, Any]) -> dict[str, Any]:
        world = self.get_world(world_instance_id)
        state = copy.deepcopy(state)
        required = ["state_id", "world_instance_id", "timeline_id", "entity_runtime_id", "origin", "entity_kind", "lifecycle", "version", "updated_at"]
        missing = [k for k in required if k not in state]
        if missing:
            raise ValidationError(f"missing entity fields: {missing}")
        validate_runtime_id(state["state_id"], "state")
        validate_runtime_id(state["entity_runtime_id"])
        if state["world_instance_id"] != world_instance_id or state["timeline_id"] != world["timeline_id"]:
            raise ValidationError("entity world/timeline mismatch")
        if state["origin"] == "CANONICAL_BACKED" and not state.get("canonical_ref"):
            raise ValidationError("canonical-backed entity requires canonical_ref")
        if state["origin"] == "CANONICAL_BACKED":
            if not self.canonical_ref_resolves(state["canonical_ref"]):
                raise ValidationError(f"unknown canonical_ref: {state["canonical_ref"]}")
        for ref in state.get("archetype_refs", []):
            if not self.canonical_ref_resolves(ref):
                raise ValidationError(f"unknown archetype_ref: {ref}")
        if state["origin"] not in {"CANONICAL_BACKED", "RUNTIME_BORN"}:
            raise ValidationError("invalid entity origin")
        if state["version"] != 0:
            raise ValidationError("bootstrap entity version must be 0")
        if state["updated_at"] != clock_point(world["clock_state"]["day"], world["clock_state"]["tick"]):
            raise ValidationError("bootstrap updated_at must equal current clock")
        state_json = canonical_json(state)
        state_hash = sha256_text(state_json)
        with self._write_lock:
            self._begin()
            try:
                self.conn.execute(
                    "INSERT INTO bootstrap_states VALUES(?,?,?,?)",
                    (world_instance_id, state["entity_runtime_id"], state_json, state_hash),
                )
                self.conn.execute(
                    "INSERT INTO entity_states VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        world_instance_id,
                        state["timeline_id"],
                        state["entity_runtime_id"],
                        state["state_id"],
                        state["origin"],
                        state.get("canonical_ref"),
                        state["entity_kind"],
                        state["lifecycle"],
                        state["version"],
                        state["updated_at"]["day"],
                        state["updated_at"]["tick"],
                        state_json,
                        state_hash,
                    ),
                )
                self._commit()
            except Exception:
                self._rollback()
                raise
        return state

    def get_entity(self, world_instance_id: str, entity_runtime_id: str) -> dict[str, Any]:
        with self._write_lock:
            row = self.conn.execute(
                "SELECT state_json,state_hash FROM entity_states WHERE world_instance_id=? AND entity_runtime_id=?",
                (world_instance_id, entity_runtime_id),
            ).fetchone()
            if not row:
                raise NotFoundError("entity not found")
        if sha256_text(row["state_json"]) != row["state_hash"]:
            raise IntegrityError("materialized state hash mismatch")
        return json.loads(row["state_json"])

    def list_entities(self, world_instance_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT state_json,state_hash FROM entity_states WHERE world_instance_id=? ORDER BY entity_runtime_id",
            (world_instance_id,),
        ).fetchall()
        out = []
        for row in rows:
            if sha256_text(row["state_json"]) != row["state_hash"]:
                raise IntegrityError("materialized state hash mismatch")
            out.append(json.loads(row["state_json"]))
        return out

    def _last_event_hash_tx(self, world_instance_id: str) -> str:
        row = self.conn.execute(
            "SELECT event_hash FROM events WHERE world_instance_id=? ORDER BY sequence DESC LIMIT 1", (world_instance_id,)
        ).fetchone()
        return row["event_hash"] if row else "GENESIS"

    def _append_event_tx(
        self,
        *,
        world_instance_id: str,
        event_type: str,
        source: str,
        subjects: list[str],
        payload: dict[str, Any],
        occurred_at: dict[str, int],
        causality: dict[str, Any] | None,
        event_id: str | None = None,
    ) -> EventEnvelope:
        world = self.get_world(world_instance_id)
        event_id = event_id or new_runtime_id("event")
        validate_runtime_id(event_id, "event")
        if source not in {"ACTION", "SYSTEM_CLOCK", "SYSTEM_RECOVERY", "SYSTEM_ROUTINE", "SYSTEM_RECONCILIATION"}:
            raise ValidationError("invalid event source")
        if causality is None:
            causality = {
                "root_event_id": event_id,
                "parent_event_id": None,
                "depth": 0,
                "cascade_budget_remaining": 64,
            }
        required_causality = {"root_event_id", "parent_event_id", "depth", "cascade_budget_remaining"}
        if not isinstance(causality, dict) or not required_causality.issubset(causality):
            raise ValidationError("causality envelope is incomplete")
        validate_runtime_id(causality["root_event_id"], "event")
        if causality["parent_event_id"] is not None:
            validate_runtime_id(causality["parent_event_id"], "event")
        if not isinstance(causality["depth"], int) or causality["depth"] < 0 or causality["depth"] > 8:
            raise ValidationError("causal depth outside allowed range")
        if not isinstance(causality["cascade_budget_remaining"], int) or causality["cascade_budget_remaining"] < 0:
            raise ValidationError("negative or invalid cascade budget")
        if causality["parent_event_id"] is None:
            if causality["root_event_id"] != event_id or causality["depth"] != 0:
                raise ValidationError("root event causality must self-reference with depth 0")
        else:
            parent = self.conn.execute(
                "SELECT world_instance_id,causality_json FROM events WHERE event_id=?",
                (causality["parent_event_id"],),
            ).fetchone()
            if not parent:
                raise ValidationError("causal parent event does not exist")
            if parent["world_instance_id"] != world_instance_id:
                raise ValidationError("causal parent belongs to another world")
            parent_causality = json.loads(parent["causality_json"])
            if causality["root_event_id"] != parent_causality["root_event_id"]:
                raise ValidationError("causal root mismatch with parent")
            if causality["depth"] != parent_causality["depth"] + 1:
                raise ValidationError("causal depth must equal parent depth + 1")
            if parent_causality["cascade_budget_remaining"] <= 0:
                raise ValidationError("causal parent has no remaining cascade budget")
            if causality["cascade_budget_remaining"] > parent_causality["cascade_budget_remaining"] - 1:
                raise ValidationError("child causal budget must be decremented from parent")
        prev_hash = self._last_event_hash_tx(world_instance_id)
        immutable_body = {
            "event_id": event_id,
            "world_instance_id": world_instance_id,
            "timeline_id": world["timeline_id"],
            "event_type": event_type,
            "occurred_at": occurred_at,
            "source": source,
            "subjects": subjects,
            "payload": payload,
            "causality": causality,
            "prev_hash": prev_hash,
        }
        event_hash = sha256_text(canonical_json(immutable_body))
        cur = self.conn.execute(
            "INSERT INTO events(event_id,world_instance_id,timeline_id,event_type,occurred_day,occurred_tick,source,subjects_json,payload_json,causality_json,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                world_instance_id,
                world["timeline_id"],
                event_type,
                occurred_at["day"],
                occurred_at["tick"],
                source,
                canonical_json(subjects),
                canonical_json(payload),
                canonical_json(causality),
                prev_hash,
                event_hash,
            ),
        )
        sequence = int(cur.lastrowid)
        return EventEnvelope(
            event_id=event_id,
            sequence=sequence,
            world_instance_id=world_instance_id,
            timeline_id=world["timeline_id"],
            event_type=event_type,
            occurred_at=occurred_at,
            source=source,
            subjects=copy.deepcopy(subjects),
            payload=copy.deepcopy(payload),
            causality=copy.deepcopy(causality),
            integrity={"prev_hash": prev_hash, "event_hash": event_hash, "algorithm": "SHA-256"},
        )

    def _append_ledger_tx(self, event: EventEnvelope, mutations: list[dict[str, Any]]) -> str:
        ledger_id = new_runtime_id("ledger")
        body = {
            "ledger_entry_id": ledger_id,
            "world_instance_id": event.world_instance_id,
            "timeline_id": event.timeline_id,
            "event_id": event.event_id,
            "root_event_id": event.causality["root_event_id"],
            "mutations": mutations,
            "recorded_at": event.occurred_at,
        }
        ledger_hash = sha256_text(canonical_json(body))
        self.conn.execute(
            "INSERT INTO causal_ledger VALUES(?,?,?,?,?,?,?,?,?)",
            (
                ledger_id,
                event.world_instance_id,
                event.timeline_id,
                event.event_id,
                event.causality["root_event_id"],
                canonical_json(mutations),
                event.occurred_at["day"],
                event.occurred_at["tick"],
                ledger_hash,
            ),
        )
        return ledger_id

    def _normalize_action(self, world_instance_id: str, action: dict[str, Any]) -> dict[str, Any]:
        action = copy.deepcopy(action)
        required = ["action_id", "intent_id", "world_instance_id", "timeline_id", "actor_ref", "action_type", "parameters", "precondition_snapshot", "idempotency_key", "created_at", "status"]
        missing = [k for k in required if k not in action]
        if missing:
            raise ValidationError(f"missing action fields: {missing}")
        validate_runtime_id(action["action_id"], "action")
        validate_runtime_id(action["intent_id"], "intent")
        world = self.get_world(world_instance_id)
        if action["world_instance_id"] != world_instance_id or action["timeline_id"] != world["timeline_id"]:
            raise ValidationError("action world/timeline mismatch")
        if not action["idempotency_key"]:
            raise ValidationError("idempotency_key required")
        if action["status"] not in {"SCHEDULED", "EXECUTING"}:
            raise ValidationError("action must be SCHEDULED or EXECUTING when submitted")
        return action

    def _check_preconditions_tx(self, world_instance_id: str, action: dict[str, Any]) -> None:
        pre = action.get("precondition_snapshot") or {}
        for entity_id, expected in pre.get("entity_versions", {}).items():
            row = self.conn.execute(
                "SELECT version FROM entity_states WHERE world_instance_id=? AND entity_runtime_id=?",
                (world_instance_id, entity_id),
            ).fetchone()
            if not row:
                raise NotFoundError(f"precondition entity missing: {entity_id}")
            if row["version"] != expected:
                raise ConflictError(f"version precondition failed for {entity_id}: expected {expected}, got {row['version']}")

    def _apply_state_consequence_tx(self, world_instance_id: str, c: dict[str, Any], now: dict[str, int]) -> dict[str, Any]:
        entity = self.get_entity(world_instance_id, c["target_ref"])
        if "expected_version" in c and entity["version"] != c["expected_version"]:
            raise ConflictError("consequence expected_version mismatch")
        operation = c["operation"]
        path = c.get("field_path")
        mutation: dict[str, Any] = {"target_ref": c["target_ref"], "operation": operation}
        before_version = entity["version"]
        if operation in {"SET", "TRANSITION"}:
            if not path:
                raise ValidationError("SET/TRANSITION requires field_path")
            old = None
            try:
                old = _deep_get(entity, path)
            except ValidationError:
                if operation == "TRANSITION":
                    raise
            if operation == "TRANSITION" and "from" in c and old != c["from"]:
                raise ConflictError(f"transition mismatch: expected {c['from']}, got {old}")
            _deep_set(entity, path, copy.deepcopy(c.get("value")))
            mutation.update({"field_path": path, "before": old, "after": c.get("value")})
        elif operation in {"INCREMENT", "DECREMENT"}:
            if not path:
                raise ValidationError("increment/decrement requires field_path")
            old = _deep_get(entity, path)
            if not isinstance(old, (int, float)) or isinstance(old, bool):
                raise ValidationError("increment/decrement target must be numeric")
            amount = c.get("amount", 1)
            if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount < 0:
                raise ValidationError("amount must be nonnegative number")
            new = old + amount if operation == "INCREMENT" else old - amount
            _deep_set(entity, path, new)
            mutation.update({"field_path": path, "before": old, "after": new})
        else:
            raise ValidationError(f"unsupported state operation in core: {operation}")
        entity["version"] = before_version + 1
        entity["updated_at"] = copy.deepcopy(now)
        state_json = canonical_json(entity)
        state_hash = sha256_text(state_json)
        self.conn.execute(
            "UPDATE entity_states SET lifecycle=?,version=?,updated_day=?,updated_tick=?,state_json=?,state_hash=? WHERE world_instance_id=? AND entity_runtime_id=?",
            (
                entity["lifecycle"],
                entity["version"],
                now["day"],
                now["tick"],
                state_json,
                state_hash,
                world_instance_id,
                entity["entity_runtime_id"],
            ),
        )
        mutation["version_before"] = before_version
        mutation["version_after"] = entity["version"]
        return mutation

    def _spawn_entity_consequence_tx(self, world_instance_id: str, timeline_id: str, c: dict[str, Any], now: dict[str, int]) -> dict[str, Any]:
        state = copy.deepcopy(c.get("entity"))
        if not isinstance(state, dict):
            raise ValidationError("SPAWN requires entity payload")
        required = ["state_id","world_instance_id","timeline_id","entity_runtime_id","origin","entity_kind","lifecycle","version","updated_at"]
        missing=[k for k in required if k not in state]
        if missing: raise ValidationError(f"SPAWN entity missing fields: {missing}")
        validate_runtime_id(state["state_id"],"state"); validate_runtime_id(state["entity_runtime_id"])
        if state["world_instance_id"] != world_instance_id or state["timeline_id"] != timeline_id:
            raise ValidationError("SPAWN entity world/timeline mismatch")
        if c.get("target_ref") != state["entity_runtime_id"]:
            raise ValidationError("SPAWN target_ref must equal entity_runtime_id")
        if state["origin"] not in {"CANONICAL_BACKED","RUNTIME_BORN"}: raise ValidationError("invalid SPAWN origin")
        if state["origin"]=="CANONICAL_BACKED":
            if not state.get("canonical_ref") or not self.canonical_ref_resolves(state["canonical_ref"]): raise ValidationError("invalid SPAWN canonical_ref")
        for ref in state.get("archetype_refs",[]):
            if not self.canonical_ref_resolves(ref): raise ValidationError(f"unknown SPAWN archetype_ref: {ref}")
        if state["version"] != 0: raise ValidationError("SPAWN entity version must be 0")
        # Dynamic entities start at the event clock, not at world genesis.
        state["updated_at"] = copy.deepcopy(now)
        if self.conn.execute("SELECT 1 FROM entity_states WHERE world_instance_id=? AND entity_runtime_id=?",(world_instance_id,state["entity_runtime_id"])).fetchone():
            raise ConflictError("SPAWN entity already exists")
        text=canonical_json(state); h=sha256_text(text)
        self.conn.execute(
            "INSERT INTO entity_states VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (world_instance_id,timeline_id,state["entity_runtime_id"],state["state_id"],state["origin"],state.get("canonical_ref"),state["entity_kind"],state["lifecycle"],0,now["day"],now["tick"],text,h),
        )
        return {"target_ref":state["entity_runtime_id"],"operation":"SPAWN","entity_kind":state["entity_kind"],"state_hash":h,"version_after":0}

    def _schedule_recovery_tx(self, world_instance_id: str, timeline_id: str, c: dict[str, Any], now: dict[str, int]) -> dict[str, Any]:
        target = self.get_entity(world_instance_id, c["target_ref"])
        if target["entity_kind"] not in {"STRUCTURE", "OBJECT", "FLORA_INSTANCE", "RESOURCE_NODE"}:
            raise ValidationError("recovery target kind is not regenerable core kind")
        destroyed_day = now["day"]
        recovery_id = c.get("recovery_id") or new_runtime_id("recovery")
        validate_runtime_id(recovery_id, "recovery")
        due = destroyed_day + 7
        record = {
            "recovery_id": recovery_id,
            "world_instance_id": world_instance_id,
            "timeline_id": timeline_id,
            "target_ref": c["target_ref"],
            "destroyed_at_day": destroyed_day,
            "due_at_day": due,
            "policy": "REGENERATE_7_UNIVERSE_DAYS",
            "status": "SCHEDULED",
            "restore": copy.deepcopy(c.get("restore", {"lifecycle": "ACTIVE"})),
        }
        self.conn.execute(
            "INSERT INTO recoveries VALUES(?,?,?,?,?,?,?,?,?)",
            (recovery_id, world_instance_id, timeline_id, c["target_ref"], destroyed_day, due, record["policy"], record["status"], canonical_json(record)),
        )
        return {"target_ref": c["target_ref"], "operation": "SCHEDULE_RECOVERY", "recovery_id": recovery_id, "due_at_day": due}

    def _ensure_authorial_recovery_consequences_tx(self, world_instance_id: str, consequences: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Fail-safe authorial rule: regenerable destroyed targets always receive a 7-day recovery schedule."""
        out = [copy.deepcopy(c) for c in consequences]
        scheduled_targets = {c.get("target_ref") for c in out if c.get("operation") == "SCHEDULE_RECOVERY"}
        destroyed_targets: list[str] = []
        for c in out:
            if c.get("operation") not in {"SET", "TRANSITION"}:
                continue
            if c.get("field_path") == "lifecycle" and c.get("value") == "DESTROYED" and c.get("target_ref"):
                destroyed_targets.append(c["target_ref"])
        next_priority = max([int(c.get("priority", 0)) for c in out] + [0]) + 1
        for target_ref in sorted(set(destroyed_targets)):
            if target_ref in scheduled_targets:
                continue
            target = self.get_entity(world_instance_id, target_ref)
            if target.get("entity_kind") not in {"STRUCTURE", "OBJECT", "FLORA_INSTANCE", "RESOURCE_NODE"}:
                continue
            restore: dict[str, Any] = {"lifecycle": "ACTIVE"}
            data = target.get("data")
            if isinstance(data, dict) and "functional" in data:
                restore["data.functional"] = True
            out.append({
                "target_ref": target_ref,
                "operation": "SCHEDULE_RECOVERY",
                "priority": next_priority,
                "kind": "SCHEDULED",
                "restore": restore,
                "authorial_auto_schedule": True,
            })
            next_priority += 1
        return out

    def apply_action(self, world_instance_id: str, action: dict[str, Any], consequences: Iterable[dict[str, Any]]) -> dict[str, Any]:
        action = self._normalize_action(world_instance_id, action)
        consequences = [copy.deepcopy(c) for c in consequences]
        with self._write_lock:
            cached = self.conn.execute(
                "SELECT action_id,result_json FROM idempotency WHERE world_instance_id=? AND idempotency_key=?",
                (world_instance_id, action["idempotency_key"]),
            ).fetchone()
            if cached:
                if cached["action_id"] != action["action_id"]:
                    raise ConflictError("idempotency key reused by different action_id")
                result = json.loads(cached["result_json"])
                result["idempotent_replay"] = True
                return result
            self._begin()
            try:
                world = self.get_world(world_instance_id)
                if world["status"] != "ACTIVE":
                    raise ConflictError("world is not active")
                actor_ref = action["actor_ref"]
                if isinstance(actor_ref, str) and actor_ref.startswith("rt:"):
                    self.get_entity(world_instance_id, actor_ref)
                elif actor_ref not in {"SYSTEM_RECOVERY", "SYSTEM_ROUTINE", "SYSTEM_RECONCILIATION", "SYSTEM_CLOCK"}:
                    raise ValidationError("actor_ref must resolve to runtime entity or approved system actor")
                if world["simulation_mode"] == "ROUTINE_OFFLINE" and action.get("execution_class") != "ROUTINE_SAFE":
                    raise OfflinePolicyError("only ROUTINE_SAFE actions execute offline")
                self._check_preconditions_tx(world_instance_id, action)
                consequences = self._ensure_authorial_recovery_consequences_tx(world_instance_id, consequences)
                now_clock = self.get_clock(world_instance_id)
                now = clock_point(now_clock["day"], now_clock["tick"])
                event_id = action.get("event_id") or new_runtime_id("event")
                subject_candidates = [action["actor_ref"]] + [c["target_ref"] for c in consequences if c.get("target_ref")]
                subjects = list(dict.fromkeys(subject_candidates))
                event = self._append_event_tx(
                    world_instance_id=world_instance_id,
                    event_type=action["action_type"],
                    source={"SYSTEM_ROUTINE": "SYSTEM_ROUTINE", "SYSTEM_RECOVERY": "SYSTEM_RECOVERY", "SYSTEM_RECONCILIATION": "SYSTEM_RECONCILIATION"}.get(action.get("source"), "ACTION"),
                    subjects=subjects,
                    payload={"action_id": action["action_id"], "intent_id": action["intent_id"], "parameters": action["parameters"]},
                    occurred_at=now,
                    causality=action.get("causality"),
                    event_id=event_id,
                )
                mutations: list[dict[str, Any]] = []
                for c in sorted(consequences, key=lambda x: (x.get("priority", 0), x.get("consequence_id", ""))):
                    cid = c.get("consequence_id") or new_runtime_id("consequence")
                    validate_runtime_id(cid, "consequence")
                    c["consequence_id"] = cid
                    c.setdefault("kind", "DIRECT")
                    c.setdefault("priority", 0)
                    c.setdefault("status", "PLANNED")
                    c["event_id"] = event.event_id
                    c["world_instance_id"] = world_instance_id
                    c["timeline_id"] = world["timeline_id"]
                    if c["operation"] in {"SET", "TRANSITION", "INCREMENT", "DECREMENT"}:
                        mutation = self._apply_state_consequence_tx(world_instance_id, c, now)
                    elif c["operation"] == "SPAWN":
                        mutation = self._spawn_entity_consequence_tx(world_instance_id, world["timeline_id"], c, now)
                    elif c["operation"] == "SCHEDULE_RECOVERY":
                        mutation = self._schedule_recovery_tx(world_instance_id, world["timeline_id"], c, now)
                    elif c["operation"] == "NOOP_BLOCKED":
                        mutation = {"target_ref": c["target_ref"], "operation": "NOOP_BLOCKED", "reason": c.get("reason", "BLOCKED")}
                    else:
                        raise ValidationError(f"unsupported consequence operation: {c['operation']}")
                    c["status"] = "BLOCKED" if c["operation"] == "NOOP_BLOCKED" else "APPLIED"
                    self.conn.execute(
                        "INSERT INTO consequences VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (cid, event.event_id, world_instance_id, world["timeline_id"], c["target_ref"], c["kind"], c["operation"], c["priority"], c["status"], canonical_json(c)),
                    )
                    mutations.append(mutation)
                ledger_id = self._append_ledger_tx(event, mutations)
                result = {
                    "action_id": action["action_id"],
                    "status": "SUCCEEDED",
                    "event_id": event.event_id,
                    "event_hash": event.integrity["event_hash"],
                    "ledger_entry_id": ledger_id,
                    "mutation_count": len(mutations),
                    "idempotent_replay": False,
                }
                self.conn.execute(
                    "INSERT INTO idempotency VALUES(?,?,?,?,?)",
                    (world_instance_id, action["idempotency_key"], action["action_id"], event.event_id, canonical_json(result)),
                )
                self._commit()
            except Exception:
                self._rollback()
                raise
        self.event_bus.publish(event)
        return result

    def process_due_recoveries(self, world_instance_id: str) -> list[dict[str, Any]]:
        world = self.get_world(world_instance_id)
        clock = world["clock_state"]
        rows = self.conn.execute(
            "SELECT recovery_json FROM recoveries WHERE world_instance_id=? AND status='SCHEDULED' AND due_at_day<=? ORDER BY due_at_day,recovery_id",
            (world_instance_id, clock["day"]),
        ).fetchall()
        results = []
        for row in rows:
            rec = json.loads(row["recovery_json"])
            target = self.get_entity(world_instance_id, rec["target_ref"])
            consequences = []
            for field, value in rec["restore"].items():
                consequences.append({
                    "target_ref": rec["target_ref"],
                    "operation": "SET",
                    "field_path": field,
                    "value": value,
                    "priority": 0,
                    "kind": "SCHEDULED",
                })
            action = {
                "action_id": new_runtime_id("action"),
                "intent_id": new_runtime_id("intent"),
                "world_instance_id": world_instance_id,
                "timeline_id": world["timeline_id"],
                "actor_ref": "SYSTEM_RECOVERY",
                "action_type": "STRUCTURE_RECOVERED",
                "parameters": {"recovery_id": rec["recovery_id"]},
                "precondition_snapshot": {"entity_versions": {rec["target_ref"]: target["version"]}},
                "idempotency_key": f"recovery:{rec['recovery_id']}",
                "created_at": clock_point(clock["day"], clock["tick"]),
                "status": "SCHEDULED",
                "source": "SYSTEM_RECOVERY",
                "execution_class": "ROUTINE_SAFE",
            }
            result = self.apply_action(world_instance_id, action, consequences)
            with self._write_lock:
                record = copy.deepcopy(rec)
                record["status"] = "COMPLETED"
                self.conn.execute(
                    "UPDATE recoveries SET status='COMPLETED', recovery_json=? WHERE recovery_id=?",
                    (canonical_json(record), rec["recovery_id"]),
                )
            results.append(result)
        return results

    def event_count(self, world_instance_id: str) -> int:
        with self._write_lock:
            return int(self.conn.execute("SELECT COUNT(*) c FROM events WHERE world_instance_id=?", (world_instance_id,)).fetchone()["c"])

    def get_event(self, event_id: str) -> EventEnvelope:
        with self._write_lock:
            row = self.conn.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            if not row:
                raise NotFoundError("event not found")
        return EventEnvelope(
            event_id=row["event_id"], sequence=row["sequence"], world_instance_id=row["world_instance_id"], timeline_id=row["timeline_id"],
            event_type=row["event_type"], occurred_at=clock_point(row["occurred_day"], row["occurred_tick"]), source=row["source"],
            subjects=json.loads(row["subjects_json"]), payload=json.loads(row["payload_json"]), causality=json.loads(row["causality_json"]),
            integrity={"prev_hash": row["prev_hash"], "event_hash": row["event_hash"], "algorithm": "SHA-256"},
        )

    def verify_event_chain(self, world_instance_id: str) -> dict[str, Any]:
        rows = self.conn.execute("SELECT * FROM events WHERE world_instance_id=? ORDER BY sequence", (world_instance_id,)).fetchall()
        prev = "GENESIS"
        failures: list[dict[str, Any]] = []
        for row in rows:
            body = {
                "event_id": row["event_id"],
                "world_instance_id": row["world_instance_id"],
                "timeline_id": row["timeline_id"],
                "event_type": row["event_type"],
                "occurred_at": clock_point(row["occurred_day"], row["occurred_tick"]),
                "source": row["source"],
                "subjects": json.loads(row["subjects_json"]),
                "payload": json.loads(row["payload_json"]),
                "causality": json.loads(row["causality_json"]),
                "prev_hash": row["prev_hash"],
            }
            calc = sha256_text(canonical_json(body))
            if row["prev_hash"] != prev:
                failures.append({"sequence": row["sequence"], "error": "PREV_HASH_MISMATCH"})
            if row["event_hash"] != calc:
                failures.append({"sequence": row["sequence"], "error": "EVENT_HASH_MISMATCH"})
            prev = row["event_hash"]
        return {"events": len(rows), "failures": failures, "status": "PASS" if not failures else "FAIL"}

    def verify_materialized_states(self, world_instance_id: str) -> dict[str, Any]:
        failures = []
        for row in self.conn.execute("SELECT entity_runtime_id,state_json,state_hash FROM entity_states WHERE world_instance_id=?", (world_instance_id,)):
            if sha256_text(row["state_json"]) != row["state_hash"]:
                failures.append({"entity_runtime_id": row["entity_runtime_id"], "error": "STATE_HASH_MISMATCH"})
        return {"states": self.conn.execute("SELECT COUNT(*) c FROM entity_states WHERE world_instance_id=?", (world_instance_id,)).fetchone()["c"], "failures": failures, "status": "PASS" if not failures else "FAIL"}

    def verify_ledger(self, world_instance_id: str) -> dict[str, Any]:
        failures = []
        rows = self.conn.execute("SELECT * FROM causal_ledger WHERE world_instance_id=? ORDER BY rowid", (world_instance_id,)).fetchall()
        for row in rows:
            body = {
                "ledger_entry_id": row["ledger_entry_id"], "world_instance_id": row["world_instance_id"], "timeline_id": row["timeline_id"],
                "event_id": row["event_id"], "root_event_id": row["root_event_id"], "mutations": json.loads(row["mutations_json"]),
                "recorded_at": clock_point(row["recorded_day"], row["recorded_tick"]),
            }
            if sha256_text(canonical_json(body)) != row["ledger_hash"]:
                failures.append({"ledger_entry_id": row["ledger_entry_id"], "error": "LEDGER_HASH_MISMATCH"})
        mutation_events = self.conn.execute(
            "SELECT DISTINCT event_id FROM consequences WHERE world_instance_id=? AND status='APPLIED'", (world_instance_id,)
        ).fetchall()
        ledger_events = {r["event_id"] for r in rows}
        for r in mutation_events:
            if r["event_id"] not in ledger_events:
                failures.append({"event_id": r["event_id"], "error": "MISSING_LEDGER"})
        return {"entries": len(rows), "failures": failures, "status": "PASS" if not failures else "FAIL"}

    def replay_state(self, world_instance_id: str) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for row in self.conn.execute("SELECT entity_runtime_id,state_json,state_hash FROM bootstrap_states WHERE world_instance_id=? ORDER BY entity_runtime_id", (world_instance_id,)):
            if sha256_text(row["state_json"]) != row["state_hash"]:
                raise IntegrityError("bootstrap state hash mismatch")
            states[row["entity_runtime_id"]] = json.loads(row["state_json"])
        rows = self.conn.execute(
            "SELECT c.consequence_json,e.occurred_day,e.occurred_tick FROM consequences c JOIN events e ON e.event_id=c.event_id WHERE c.world_instance_id=? AND c.status='APPLIED' ORDER BY e.sequence,c.priority,c.consequence_id",
            (world_instance_id,),
        ).fetchall()
        for row in rows:
            c = json.loads(row["consequence_json"])
            op = c["operation"]
            if op == "SPAWN":
                state=copy.deepcopy(c.get("entity"))
                if not isinstance(state,dict) or state.get("entity_runtime_id")!=c.get("target_ref"):
                    raise IntegrityError("replay SPAWN payload invalid")
                if c["target_ref"] in states: raise IntegrityError("replay SPAWN target already exists")
                state["version"]=0; state["updated_at"]=clock_point(row["occurred_day"],row["occurred_tick"]); states[c["target_ref"]]=state
                continue
            if op not in {"SET", "TRANSITION", "INCREMENT", "DECREMENT"}:
                continue
            if c["target_ref"] not in states:
                raise IntegrityError("replay target not found in bootstrap or prior SPAWN")
            entity = states[c["target_ref"]]
            path = c["field_path"]
            if op in {"SET", "TRANSITION"}:
                if op == "TRANSITION" and "from" in c and _deep_get(entity, path) != c["from"]:
                    raise IntegrityError("replay transition precondition mismatch")
                _deep_set(entity, path, copy.deepcopy(c.get("value")))
            else:
                old = _deep_get(entity, path)
                amount = c.get("amount", 1)
                _deep_set(entity, path, old + amount if op == "INCREMENT" else old - amount)
            entity["version"] += 1
            entity["updated_at"] = clock_point(row["occurred_day"], row["occurred_tick"])
        return states

    def compare_replay_to_materialized(self, world_instance_id: str) -> dict[str, Any]:
        replayed = self.replay_state(world_instance_id)
        materialized = {x["entity_runtime_id"]: x for x in self.list_entities(world_instance_id)}
        failures = []
        for entity_id in sorted(set(replayed) | set(materialized)):
            if entity_id not in replayed or entity_id not in materialized:
                failures.append({"entity_runtime_id": entity_id, "error": "ENTITY_SET_MISMATCH"})
            elif canonical_json(replayed[entity_id]) != canonical_json(materialized[entity_id]):
                failures.append({"entity_runtime_id": entity_id, "error": "STATE_REPLAY_MISMATCH"})
        return {"entities": len(materialized), "failures": failures, "status": "PASS" if not failures else "FAIL"}

    def replay_clock(self, world_instance_id: str) -> dict[str, Any]:
        with self._write_lock:
            clock = self.get_clock(world_instance_id)
            rows = self.conn.execute(
                "SELECT occurred_day,occurred_tick,payload_json,event_type FROM events WHERE world_instance_id=? ORDER BY sequence",
                (world_instance_id,),
            ).fetchall()
        day, tick = 0, 0
        failures = []
        for row in rows:
            if row["event_type"] != "CLOCK_ADVANCED":
                continue
            payload = json.loads(row["payload_json"])
            if payload.get("from") != clock_point(day, tick):
                failures.append({"error": "CLOCK_FROM_MISMATCH", "expected": clock_point(day, tick), "actual": payload.get("from")})
                break
            to = payload.get("to")
            if not isinstance(to, dict) or not isinstance(to.get("day"), int) or not isinstance(to.get("tick"), int):
                failures.append({"error": "CLOCK_TO_INVALID"})
                break
            day, tick = to["day"], to["tick"]
        if (day, tick) != (clock["day"], clock["tick"]):
            failures.append({"error": "CLOCK_REPLAY_MISMATCH", "replayed": clock_point(day,tick), "materialized": clock_point(clock["day"],clock["tick"])})
        return {"replayed": clock_point(day,tick), "materialized": clock_point(clock["day"],clock["tick"]), "failures": failures, "status": "PASS" if not failures else "FAIL"}

    def integrity_guard(self, world_instance_id: str) -> dict[str, Any]:
        report = self.full_integrity_check(world_instance_id)
        if report["status"] != "PASS":
            with self._write_lock:
                self.conn.execute("UPDATE worlds SET status='CORRUPT_BLOCKED' WHERE world_instance_id=?", (world_instance_id,))
        return report

    def full_integrity_check(self, world_instance_id: str) -> dict[str, Any]:
        def safe(name: str, fn: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
            try:
                return fn(world_instance_id)
            except Exception as exc:
                return {"status": "FAIL", "failures": [{"error": f"{name.upper()}_EXCEPTION", "detail": repr(exc)}]}
        checks = {
            "event_chain": safe("event_chain", self.verify_event_chain),
            "materialized_states": safe("materialized_states", self.verify_materialized_states),
            "ledger": safe("ledger", self.verify_ledger),
            "replay": safe("replay", self.compare_replay_to_materialized),
            "clock_replay": safe("clock_replay", self.replay_clock),
        }
        status = "PASS" if all(v["status"] == "PASS" for v in checks.values()) else "FAIL"
        return {"status": status, "checks": checks}
