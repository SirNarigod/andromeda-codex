from __future__ import annotations

import copy
import json
import sqlite3
import threading
from typing import Any

from living_runtime import (
    LivingRuntime,
    EventEnvelope,
    ValidationError,
    IntegrityError,
    NotFoundError,
    ConflictError,
    canonical_json,
    sha256_text,
    new_runtime_id,
)


class DomainIntegrationHub:
    """Persistent, idempotent cross-domain integration for committed Living events.

    The hub never rewrites immutable event history. It consumes committed events and
    reconciles derived runtime projections (ecology aggregates, scheduler eligibility,
    social witnessing). Missing optional projections are recorded as SKIPPED rather
    than fabricated.
    """

    SCHEMA_VERSION = 1
    OBSERVABLE_EVENT_TYPES = {
        "ECO_HUNT",
        "ATTACK",
        "KILL",
        "COMBAT_RESOLVED",
        "THEFT",
        "ROBBERY",
        "STRUCTURE_DESTROYED",
        "OBJECT_DESTROYED",
    }

    def __init__(self, runtime: LivingRuntime, ecology: Any, social: Any) -> None:
        if ecology.runtime is not runtime or social.runtime is not runtime:
            raise ValidationError("domain integration systems must share LivingRuntime")
        self.runtime = runtime
        self.ecology = ecology
        self.social = social
        self.conn = runtime.conn
        self._lock = threading.RLock()
        self._unsubscribe = None
        self._initialize_schema()
        self.attach()

    def _initialize_schema(self) -> None:
        with self.runtime._write_lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS domain_integration_queue(
                    event_id TEXT PRIMARY KEY REFERENCES events(event_id) ON DELETE RESTRICT,
                    world_instance_id TEXT NOT NULL,
                    timeline_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','DEFERRED','COMPLETED','FAILED')),
                    attempts INTEGER NOT NULL CHECK(attempts >= 0),
                    queued_day INTEGER NOT NULL CHECK(queued_day >= 0),
                    queued_tick INTEGER NOT NULL CHECK(queued_tick >= 0),
                    result_json TEXT,
                    result_hash TEXT,
                    last_error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_domain_integration_queue_world_status
                    ON domain_integration_queue(world_instance_id,status,event_id);

                CREATE TABLE IF NOT EXISTS domain_integration_effects(
                    effect_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE RESTRICT,
                    world_instance_id TEXT NOT NULL,
                    effect_key TEXT NOT NULL,
                    effect_type TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('APPLIED','SKIPPED')),
                    effect_json TEXT NOT NULL,
                    effect_hash TEXT NOT NULL,
                    UNIQUE(event_id,effect_key)
                );
                CREATE INDEX IF NOT EXISTS idx_domain_integration_effects_world
                    ON domain_integration_effects(world_instance_id,event_id);
                CREATE TRIGGER IF NOT EXISTS domain_effects_no_update BEFORE UPDATE ON domain_integration_effects
                BEGIN SELECT RAISE(ABORT,'domain integration effects are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS domain_effects_no_delete BEFORE DELETE ON domain_integration_effects
                BEGIN SELECT RAISE(ABORT,'domain integration effects are immutable'); END;
                """
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('domain_integration_schema_version',?)",
                (str(self.SCHEMA_VERSION),),
            )

    def attach(self) -> None:
        if self._unsubscribe is not None:
            return

        def handler(event: EventEnvelope) -> None:
            try:
                self.enqueue_event(event)
            except Exception:
                # Event history is already committed. Backfill on the next drain repairs
                # a missed in-process notification without touching immutable history.
                return

        self._unsubscribe = self.runtime.event_bus.subscribe(handler)

    def detach(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def enqueue_event(self, event: EventEnvelope) -> dict[str, Any]:
        with self._lock, self.runtime._write_lock:
            self.conn.execute(
                """INSERT OR IGNORE INTO domain_integration_queue
                   (event_id,world_instance_id,timeline_id,event_type,status,attempts,queued_day,queued_tick)
                   VALUES(?,?,?,?, 'PENDING',0,?,?)""",
                (
                    event.event_id,
                    event.world_instance_id,
                    event.timeline_id,
                    event.event_type,
                    int(event.occurred_at["day"]),
                    int(event.occurred_at["tick"]),
                ),
            )
        return {"status": "QUEUED", "event_id": event.event_id}

    def _backfill_unqueued_events(self, world_instance_id: str) -> int:
        with self._lock, self.runtime._write_lock:
            rows = self.conn.execute(
                """SELECT e.event_id,e.world_instance_id,e.timeline_id,e.event_type,e.occurred_day,e.occurred_tick
                   FROM events e
                   LEFT JOIN domain_integration_queue q ON q.event_id=e.event_id
                   WHERE e.world_instance_id=? AND q.event_id IS NULL
                   ORDER BY e.sequence""",
                (world_instance_id,),
            ).fetchall()
            for r in rows:
                self.conn.execute(
                    """INSERT INTO domain_integration_queue
                       (event_id,world_instance_id,timeline_id,event_type,status,attempts,queued_day,queued_tick)
                       VALUES(?,?,?,?, 'PENDING',0,?,?)""",
                    (r["event_id"], r["world_instance_id"], r["timeline_id"], r["event_type"], r["occurred_day"], r["occurred_tick"]),
                )
        return len(rows)

    def _mutations(self, event_id: str) -> list[dict[str, Any]]:
        with self.runtime._write_lock:
            row = self.conn.execute(
                "SELECT mutations_json,ledger_hash,world_instance_id,timeline_id,root_event_id,recorded_day,recorded_tick,ledger_entry_id,event_id FROM causal_ledger WHERE event_id=?",
                (event_id,),
            ).fetchone()
        if not row:
            return []
        # Runtime integrity guard validates ledger hashes globally. Parsing here is enough
        # to avoid duplicating the private ledger-hash body construction.
        value = json.loads(row["mutations_json"])
        if not isinstance(value, list):
            raise IntegrityError("causal ledger mutations are not a list")
        return value

    def _effect(self, event_id: str, effect_key: str) -> dict[str, Any] | None:
        with self.runtime._write_lock:
            row = self.conn.execute(
                "SELECT effect_json,effect_hash FROM domain_integration_effects WHERE event_id=? AND effect_key=?",
                (event_id, effect_key),
            ).fetchone()
        if not row:
            return None
        if sha256_text(row["effect_json"]) != row["effect_hash"]:
            raise IntegrityError("domain integration effect hash mismatch")
        return json.loads(row["effect_json"])

    def _insert_effect_tx(
        self,
        *,
        event_id: str,
        world_instance_id: str,
        effect_key: str,
        effect_type: str,
        status: str,
        detail: dict[str, Any],
    ) -> dict[str, Any]:
        if status not in {"APPLIED", "SKIPPED"}:
            raise ValidationError("invalid domain integration effect status")
        body = {
            "effect_id": new_runtime_id("domaineffect"),
            "event_id": event_id,
            "world_instance_id": world_instance_id,
            "effect_key": effect_key,
            "effect_type": effect_type,
            "status": status,
            "detail": copy.deepcopy(detail),
        }
        text = canonical_json(body)
        h = sha256_text(text)
        self.conn.execute(
            "INSERT INTO domain_integration_effects VALUES(?,?,?,?,?,?,?,?)",
            (body["effect_id"], event_id, world_instance_id, effect_key, effect_type, status, text, h),
        )
        body["effect_hash"] = h
        return body

    def _population_exists(self, world_instance_id: str, species_ref: str, territory_ref: str) -> bool:
        with self.runtime._write_lock:
            return self.conn.execute(
                "SELECT 1 FROM ecology_populations_current WHERE world_instance_id=? AND species_ref=? AND territory_ref=?",
                (world_instance_id, species_ref, territory_ref),
            ).fetchone() is not None

    def _apply_population_delta_once(
        self,
        *,
        event_id: str,
        world_instance_id: str,
        effect_key: str,
        species_ref: str,
        territory_ref: str,
        delta: int,
        reason: str,
    ) -> dict[str, Any]:
        prior = self._effect(event_id, effect_key)
        if prior:
            prior["idempotent_replay"] = True
            return prior
        with self._lock, self.runtime._write_lock:
            prior = self._effect(event_id, effect_key)
            if prior:
                prior["idempotent_replay"] = True
                return prior
            if not self._population_exists(world_instance_id, species_ref, territory_ref):
                return self._insert_effect_tx(
                    event_id=event_id,
                    world_instance_id=world_instance_id,
                    effect_key=effect_key,
                    effect_type="ECOLOGY_POPULATION_DELTA",
                    status="SKIPPED",
                    detail={"reason": "NO_AGGREGATE_POPULATION", "species_ref": species_ref, "territory_ref": territory_ref, "delta": delta},
                )
            current = self.ecology.get_population(world_instance_id, species_ref, territory_ref)
            if int(current["count"]) + int(delta) < 0:
                return self._insert_effect_tx(
                    event_id=event_id,
                    world_instance_id=world_instance_id,
                    effect_key=effect_key,
                    effect_type="ECOLOGY_POPULATION_DELTA",
                    status="SKIPPED",
                    detail={"reason": "NEGATIVE_POPULATION_GUARD", "species_ref": species_ref, "territory_ref": territory_ref, "delta": delta, "count": current["count"]},
                )
            self.runtime._begin()
            try:
                d = self.ecology._apply_population_delta_tx(world_instance_id, species_ref, territory_ref, int(delta), reason)
                effect = self._insert_effect_tx(
                    event_id=event_id,
                    world_instance_id=world_instance_id,
                    effect_key=effect_key,
                    effect_type="ECOLOGY_POPULATION_DELTA",
                    status="APPLIED",
                    detail={"population_delta": d},
                )
                self.runtime._commit()
                return effect
            except Exception:
                self.runtime._rollback()
                raise

    def _apply_migration_once(
        self,
        *,
        event_id: str,
        world_instance_id: str,
        animal_ref: str,
        species_ref: str,
        source_territory: str,
        destination_territory: str,
    ) -> dict[str, Any]:
        key = f"ecology:migration:{animal_ref}:{source_territory}->{destination_territory}"
        prior = self._effect(event_id, key)
        if prior:
            prior["idempotent_replay"] = True
            return prior
        with self._lock, self.runtime._write_lock:
            prior = self._effect(event_id, key)
            if prior:
                prior["idempotent_replay"] = True
                return prior
            if not self._population_exists(world_instance_id, species_ref, source_territory) or not self._population_exists(world_instance_id, species_ref, destination_territory):
                return self._insert_effect_tx(
                    event_id=event_id,
                    world_instance_id=world_instance_id,
                    effect_key=key,
                    effect_type="ECOLOGY_POPULATION_MIGRATION",
                    status="SKIPPED",
                    detail={"reason": "MISSING_SOURCE_OR_DESTINATION_AGGREGATE", "species_ref": species_ref, "source": source_territory, "destination": destination_territory},
                )
            src = self.ecology.get_population(world_instance_id, species_ref, source_territory)
            if int(src["count"]) <= 0:
                return self._insert_effect_tx(
                    event_id=event_id,
                    world_instance_id=world_instance_id,
                    effect_key=key,
                    effect_type="ECOLOGY_POPULATION_MIGRATION",
                    status="SKIPPED",
                    detail={"reason": "SOURCE_AGGREGATE_EMPTY", "species_ref": species_ref, "source": source_territory, "destination": destination_territory},
                )
            self.runtime._begin()
            try:
                out_delta = self.ecology._apply_population_delta_tx(world_instance_id, species_ref, source_territory, -1, "INDIVIDUAL_MIGRATION_OUT")
                in_delta = self.ecology._apply_population_delta_tx(world_instance_id, species_ref, destination_territory, 1, "INDIVIDUAL_MIGRATION_IN")
                effect = self._insert_effect_tx(
                    event_id=event_id,
                    world_instance_id=world_instance_id,
                    effect_key=key,
                    effect_type="ECOLOGY_POPULATION_MIGRATION",
                    status="APPLIED",
                    detail={"species_ref": species_ref, "animal_ref": animal_ref, "source": source_territory, "destination": destination_territory, "deltas": [out_delta, in_delta]},
                )
                self.runtime._commit()
                return effect
            except Exception:
                self.runtime._rollback()
                raise

    def _disable_scheduler_once(self, event_id: str, world_instance_id: str, entity_ref: str) -> dict[str, Any]:
        key = f"scheduler:disable:{entity_ref}"
        prior = self._effect(event_id, key)
        if prior:
            prior["idempotent_replay"] = True
            return prior
        with self._lock, self.runtime._write_lock:
            prior = self._effect(event_id, key)
            if prior:
                prior["idempotent_replay"] = True
                return prior
            table = self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='orchestration_participants'").fetchone()
            if not table:
                return self._insert_effect_tx(
                    event_id=event_id,
                    world_instance_id=world_instance_id,
                    effect_key=key,
                    effect_type="SCHEDULER_LIFECYCLE",
                    status="SKIPPED",
                    detail={"reason": "ORCHESTRATOR_NOT_INITIALIZED", "entity_ref": entity_ref},
                )
            cur = self.conn.execute(
                "UPDATE orchestration_participants SET enabled=0 WHERE world_instance_id=? AND entity_ref=? AND enabled=1",
                (world_instance_id, entity_ref),
            )
            return self._insert_effect_tx(
                event_id=event_id,
                world_instance_id=world_instance_id,
                effect_key=key,
                effect_type="SCHEDULER_LIFECYCLE",
                status="APPLIED" if cur.rowcount else "SKIPPED",
                detail={"entity_ref": entity_ref, "disabled_rows": int(cur.rowcount), "reason": None if cur.rowcount else "NOT_REGISTERED_OR_ALREADY_DISABLED"},
            )

    @staticmethod
    def _spatial_signature(state: dict[str, Any]) -> tuple[set[str], set[str]]:
        data = state.get("data", {}) if isinstance(state.get("data"), dict) else {}
        eco = data.get("ecology", {}) if isinstance(data.get("ecology"), dict) else {}
        specific: set[str] = set()
        broad: set[str] = set()
        candidates = [
            data.get("location_ref"), data.get("poi_ref"), data.get("site_ref"), data.get("biome_ref"),
            eco.get("biome_ref"), data.get("territory_ref"), eco.get("territory_ref"),
        ]
        for ref in candidates:
            if not isinstance(ref, str) or not ref:
                continue
            if ref.startswith("TER-"):
                broad.add(ref)
            else:
                specific.add(ref)
        return specific, broad

    @classmethod
    def _co_located(cls, a: dict[str, Any], b: dict[str, Any]) -> bool:
        aspec, abroad = cls._spatial_signature(a)
        bspec, bbroad = cls._spatial_signature(b)
        if aspec and bspec:
            return bool(aspec & bspec)
        if abroad and bbroad:
            return bool(abroad & bbroad)
        # One side may only know a territory while the other has a specific site plus
        # territory. In that case territory-level co-location is the best available fact.
        return bool(abroad & bbroad)

    def _witnesses_for_event(self, event: EventEnvelope, mutations: list[dict[str, Any]]) -> list[str]:
        lifecycle_change = any(m.get("field_path") == "lifecycle" for m in mutations)
        if event.source != "ACTION" or (event.event_type not in self.OBSERVABLE_EVENT_TYPES and not lifecycle_change):
            return []
        subject_states: list[dict[str, Any]] = []
        for ref in event.subjects:
            if isinstance(ref, str) and ref.startswith("rt:"):
                try:
                    subject_states.append(self.runtime.get_entity(event.world_instance_id, ref))
                except NotFoundError:
                    continue
        if not subject_states:
            return []
        witnesses = []
        for state in self.runtime.list_entities(event.world_instance_id):
            if state.get("entity_kind") != "AGENT" or state.get("lifecycle") != "ACTIVE":
                continue
            ref = state.get("entity_runtime_id")
            if ref in event.subjects:
                continue
            if any(self._co_located(state, s) for s in subject_states):
                witnesses.append(ref)
        return sorted(set(witnesses))

    def _witness_once(self, event: EventEnvelope, observer_ref: str) -> dict[str, Any]:
        key = f"social:witness:{observer_ref}"
        prior = self._effect(event.event_id, key)
        if prior:
            prior["idempotent_replay"] = True
            return prior
        remembered = self.social.remember_event(
            event.world_instance_id,
            observer_ref,
            event.event_id,
            salience=85 if event.event_type in {"ECO_HUNT", "ATTACK", "KILL", "COMBAT_RESOLVED"} else 70,
            emotional_weight=-30 if event.event_type in {"ECO_HUNT", "ATTACK", "KILL", "COMBAT_RESOLVED"} else 0,
            tags=["auto_witness", "domain_integration"],
        )
        with self._lock, self.runtime._write_lock:
            prior = self._effect(event.event_id, key)
            if prior:
                prior["idempotent_replay"] = True
                return prior
            return self._insert_effect_tx(
                event_id=event.event_id,
                world_instance_id=event.world_instance_id,
                effect_key=key,
                effect_type="SOCIAL_WITNESS",
                status="APPLIED",
                detail={"observer_ref": observer_ref, "memory_id": remembered["memory"]["memory_id"], "claim_id": remembered["claim"]["claim_id"]},
            )

    def _process_event(self, event_id: str) -> dict[str, Any]:
        event = self.runtime.get_event(event_id)
        mutations = self._mutations(event_id)
        effects: list[dict[str, Any]] = []
        deferred = False

        # 1) Lifecycle -> aggregate ecology + scheduler lifecycle.
        for m in mutations:
            target = m.get("target_ref")
            if not isinstance(target, str) or not target.startswith("rt:"):
                continue
            if m.get("field_path") == "lifecycle" and m.get("before") == "ACTIVE" and m.get("after") == "DEAD":
                try:
                    state = self.runtime.get_entity(event.world_instance_id, target)
                except NotFoundError:
                    continue
                effects.append(self._disable_scheduler_once(event.event_id, event.world_instance_id, target))
                if state.get("entity_kind") in {"ANIMAL", "CREATURE"}:
                    data = state.get("data", {})
                    eco = data.get("ecology", {}) if isinstance(data.get("ecology"), dict) else {}
                    species = data.get("species_ref")
                    territory = eco.get("territory_ref")
                    if isinstance(species, str) and isinstance(territory, str):
                        effects.append(self._apply_population_delta_once(
                            event_id=event.event_id,
                            world_instance_id=event.world_instance_id,
                            effect_key=f"ecology:death:{target}",
                            species_ref=species,
                            territory_ref=territory,
                            delta=-1,
                            reason="INDIVIDUAL_DEATH",
                        ))

        # 2) Individual migration -> source/destination aggregate transfer.
        for m in mutations:
            if m.get("field_path") != "data.ecology.territory_ref" or m.get("before") == m.get("after"):
                continue
            target = m.get("target_ref")
            if not isinstance(target, str) or not target.startswith("rt:"):
                continue
            try:
                state = self.runtime.get_entity(event.world_instance_id, target)
            except NotFoundError:
                continue
            if state.get("entity_kind") not in {"ANIMAL", "CREATURE"}:
                continue
            species = state.get("data", {}).get("species_ref")
            if isinstance(species, str) and isinstance(m.get("before"), str) and isinstance(m.get("after"), str):
                effects.append(self._apply_migration_once(
                    event_id=event.event_id,
                    world_instance_id=event.world_instance_id,
                    animal_ref=target,
                    species_ref=species,
                    source_territory=m["before"],
                    destination_territory=m["after"],
                ))

        # 3) Reproduction event -> newly materialized child joins aggregate.
        if event.event_type == "ECO_REPRODUCE":
            with self.runtime._write_lock:
                row = self.conn.execute(
                    "SELECT birth_json,birth_hash FROM ecology_births WHERE reproduction_event_id=?",
                    (event.event_id,),
                ).fetchone()
            if not row:
                deferred = True
            else:
                if sha256_text(row["birth_json"]) != row["birth_hash"]:
                    raise IntegrityError("birth hash mismatch during domain integration")
                birth = json.loads(row["birth_json"])
                effects.append(self._apply_population_delta_once(
                    event_id=event.event_id,
                    world_instance_id=event.world_instance_id,
                    effect_key=f"ecology:birth:{birth['child_ref']}",
                    species_ref=birth["species_ref"],
                    territory_ref=birth["territory_ref"],
                    delta=1,
                    reason="INDIVIDUAL_BIRTH",
                ))

        # 4) Automatic social witnessing for significant, spatially co-located events.
        for observer in self._witnesses_for_event(event, mutations):
            effects.append(self._witness_once(event, observer))

        return {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "deferred": deferred,
            "effects": effects,
            "effects_applied": sum(1 for x in effects if x.get("status") == "APPLIED"),
            "effects_skipped": sum(1 for x in effects if x.get("status") == "SKIPPED"),
        }

    def drain_pending(self, world_instance_id: str, *, limit: int = 256) -> dict[str, Any]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValidationError("domain integration limit must be positive integer")
        backfilled = self._backfill_unqueued_events(world_instance_id)
        with self._lock, self.runtime._write_lock:
            rows = self.conn.execute(
                """SELECT q.* FROM domain_integration_queue q
                   JOIN events e ON e.event_id=q.event_id
                   WHERE q.world_instance_id=? AND q.status IN ('PENDING','DEFERRED')
                   ORDER BY e.sequence LIMIT ?""",
                (world_instance_id, limit),
            ).fetchall()
        results = []
        failures = []
        for row in rows:
            eid = row["event_id"]
            try:
                result = self._process_event(eid)
                status = "DEFERRED" if result["deferred"] else "COMPLETED"
                text = canonical_json(result)
                h = sha256_text(text)
                with self._lock, self.runtime._write_lock:
                    self.conn.execute(
                        "UPDATE domain_integration_queue SET status=?,attempts=attempts+1,result_json=?,result_hash=?,last_error=NULL WHERE event_id=?",
                        (status, text, h, eid),
                    )
                results.append(result)
            except Exception as exc:
                with self._lock, self.runtime._write_lock:
                    self.conn.execute(
                        "UPDATE domain_integration_queue SET status='FAILED',attempts=attempts+1,last_error=? WHERE event_id=?",
                        (f"{type(exc).__name__}:{exc}", eid),
                    )
                failures.append({"event_id": eid, "error": type(exc).__name__, "message": str(exc)})
        pending = self.conn.execute(
            "SELECT COUNT(*) c FROM domain_integration_queue WHERE world_instance_id=? AND status IN ('PENDING','DEFERRED')",
            (world_instance_id,),
        ).fetchone()["c"]
        return {
            "status": "PASS" if not failures else "PARTIAL",
            "backfilled": backfilled,
            "processed": len(results),
            "failed": len(failures),
            "pending": int(pending),
            "results": results,
            "failures": failures,
        }

    def full_integrity_check(self, world_instance_id: str) -> dict[str, Any]:
        failures = []
        with self._lock, self.runtime._write_lock:
            rows = self.conn.execute(
                "SELECT rowid,* FROM domain_integration_effects WHERE world_instance_id=?",
                (world_instance_id,),
            ).fetchall()
            for r in rows:
                if sha256_text(r["effect_json"]) != r["effect_hash"]:
                    failures.append(f"EFFECT_HASH:{r['rowid']}")
            qrows = self.conn.execute(
                "SELECT event_id,status,result_json,result_hash FROM domain_integration_queue WHERE world_instance_id=?",
                (world_instance_id,),
            ).fetchall()
            for r in qrows:
                if r["result_json"] is not None:
                    if not r["result_hash"] or sha256_text(r["result_json"]) != r["result_hash"]:
                        failures.append(f"QUEUE_RESULT_HASH:{r['event_id']}")
            orphans = self.conn.execute(
                """SELECT COUNT(*) c FROM domain_integration_queue q
                   LEFT JOIN events e ON e.event_id=q.event_id
                   WHERE q.world_instance_id=? AND e.event_id IS NULL""",
                (world_instance_id,),
            ).fetchone()["c"]
            if orphans:
                failures.append(f"ORPHAN_QUEUE:{orphans}")
        return {
            "status": "PASS" if not failures else "FAIL",
            "failures": failures,
            "queue": len(qrows),
            "effects": len(rows),
        }
