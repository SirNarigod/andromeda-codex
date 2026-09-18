from __future__ import annotations

import json
from typing import Any

from living_runtime import ConflictError, canonical_json, sha256_text

# ============================================================================
# ARPG_STAGE17_FAUNA_TERRITORIAL_MIGRATION_NOT_CANON
#
# Fase 8.4 (14/09): ponte agregada de migracao de fauna entre territorios do
# PlanetSystem (fase 7.2). O pipeline _apply_migration_once/eco.migrate ja
# existente (domain_integration.py/ecology_brain.py) funciona ponta a ponta,
# mas SO pra fauna modelada como entidade individual (ANIMAL/CREATURE com
# data.ecology.territory_ref/species_ref via EcologySystem) - a fauna de
# CountryScaleSystem (a que o PlanetSystem/root_corruption_system realmente
# usa) e AGREGADA por bloco/subregiao (count por especie), um modelo
# incompativel. Em vez de forcar essa fauna a virar entidade individual
# (arriscado, tocaria a geracao procedural de country_scale.py), este arquivo
# e um sistema NOVO e paralelo que opera direto sobre a contagem agregada dos
# CountryScaleSystem ja registrados no PlanetSystem - reaproveita so o
# FORMATO de bloco/fauna que country_scale.py ja gera (nunca reimplementa a
# geracao), e o mesmo padrao de idempotencia por event_ref de todo o Stage17.
#
# Regra honesta: so migra fauna pra um bloco do territorio de destino que JA
# tem essa mesma especie (nunca inventa uma populacao nova num bioma onde ela
# nao existia).
# ============================================================================

AUTHORITY = "ARPG_STAGE17_FAUNA_TERRITORIAL_MIGRATION_NOT_CANON"
VERSION = "V0.1.0-PRE-GODOT"


def _hash_state(d: dict[str, Any]) -> str:
    return sha256_text(canonical_json(d))


def _fauna_entries(country: Any, species_ref: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Retorna [(block, fauna_entry)] pra toda entrada com esse species_ref,
    em todos os blocos/estados do territorio."""
    out: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for state in country.world["country"].get("states", []):
        for block in state.get("blocks", []):
            for entry in block.get("fauna", []):
                if entry.get("species_ref") == species_ref:
                    out.append((block, entry))
    return out


class FaunaTerritorialMigration:
    VERSION = VERSION
    AUTHORITY = AUTHORITY

    def __init__(self, planet: Any) -> None:
        self.planet = planet
        self.runtime = planet.runtime
        self.world_instance_id = planet.world_instance_id
        self._init_db()

    def _init_db(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                """CREATE TABLE IF NOT EXISTS v17_fauna_migration_events(
                    world_instance_id TEXT NOT NULL, event_ref TEXT NOT NULL,
                    event_type TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL, result_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, event_ref))"""
            )

    def _event_existing(self, event_ref: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = self.runtime.conn.execute(
            "SELECT * FROM v17_fauna_migration_events WHERE world_instance_id=? AND event_ref=?",
            (self.world_instance_id, str(event_ref)),
        ).fetchone()
        if not row:
            return None
        if sha256_text(canonical_json(payload)) != row["payload_hash"]:
            raise ConflictError(f"fauna migration event_ref {event_ref} already used with a different payload")
        if row["event_type"] != event_type:
            raise ConflictError(f"fauna migration event_ref {event_ref} already used for a different event_type")
        if sha256_text(row["result_json"]) != row["result_hash"]:
            raise ValueError("fauna migration event result hash mismatch")
        result = json.loads(row["result_json"])
        return {**result, "idempotent_replay": True}

    def _record_event(self, event_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        ptext = canonical_json(payload)
        rtext = canonical_json(result)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT INTO v17_fauna_migration_events VALUES(?,?,?,?,?,?)",
                (self.world_instance_id, str(event_ref), event_type, sha256_text(ptext), rtext, sha256_text(rtext)),
            )
        return result

    def fauna_total(self, territory_id: str, species_ref: str) -> int:
        country = self.planet.territory_ref(territory_id)
        return sum(entry["count"] for _, entry in _fauna_entries(country, species_ref))

    def migrate_fauna_delta(
        self, source_territory_id: str, dest_territory_id: str, species_ref: str, count: int,
        *, event_ref: str,
    ) -> dict[str, Any]:
        payload = {
            "source_territory_id": source_territory_id, "dest_territory_id": dest_territory_id,
            "species_ref": species_ref, "count": int(count),
        }
        replay = self._event_existing(event_ref, "FAUNA_MIGRATED", payload)
        if replay is not None:
            return replay

        count = int(count)
        if count <= 0:
            result = {"status": "REJECTED", "reason": "COUNT_MUST_BE_POSITIVE"}
            return self._record_event(event_ref, "FAUNA_MIGRATED", payload, result)
        if source_territory_id == dest_territory_id:
            result = {"status": "REJECTED", "reason": "SOURCE_AND_DEST_MUST_DIFFER"}
            return self._record_event(event_ref, "FAUNA_MIGRATED", payload, result)

        try:
            source_country = self.planet.territory_ref(source_territory_id)
            dest_country = self.planet.territory_ref(dest_territory_id)
        except KeyError as exc:
            result = {"status": "REJECTED", "reason": "TERRITORY_NOT_REGISTERED", "detail": str(exc)}
            return self._record_event(event_ref, "FAUNA_MIGRATED", payload, result)

        source_entries = _fauna_entries(source_country, species_ref)
        available = sum(entry["count"] for _, entry in source_entries)
        if available < count:
            result = {"status": "REJECTED", "reason": "INSUFFICIENT_SOURCE_FAUNA",
                      "available": available, "requested": count}
            return self._record_event(event_ref, "FAUNA_MIGRATED", payload, result)

        dest_entries = _fauna_entries(dest_country, species_ref)
        if not dest_entries:
            result = {"status": "REJECTED", "reason": "NO_MATCHING_FAUNA_POPULATION_IN_DESTINATION"}
            return self._record_event(event_ref, "FAUNA_MIGRATED", payload, result)

        remaining = count
        for _, entry in source_entries:
            if remaining <= 0:
                break
            taken = min(remaining, entry["count"])
            entry["count"] -= taken
            entry["status"] = "EXTIRPATED_LOCAL" if entry["count"] == 0 else entry.get("status", "ACTIVE")
            remaining -= taken
        dest_entries[0][1]["count"] += count

        result = {
            "status": "PASS", "event_ref": event_ref, "species_ref": species_ref,
            "migrated_count": count,
            "source_remaining": self.fauna_total(source_territory_id, species_ref),
            "dest_total": self.fauna_total(dest_territory_id, species_ref),
            "authority": self.AUTHORITY, "idempotent_replay": False,
        }
        return self._record_event(event_ref, "FAUNA_MIGRATED", payload, result)
