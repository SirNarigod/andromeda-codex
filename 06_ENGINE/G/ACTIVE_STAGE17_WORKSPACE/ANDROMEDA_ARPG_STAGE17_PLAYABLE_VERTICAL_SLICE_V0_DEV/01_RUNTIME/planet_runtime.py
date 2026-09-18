from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from living_runtime import canonical_json, sha256_text
from country_scale import CountryScaleSystem
from world_systems import WorldSystems

# ============================================================================
# ARPG_STAGE17_PLANET_RUNTIME_NOT_CANON
#
# Fase 7.2 (fase 7 desta sessao, 13/09): hoje existem 2 arquiteturas de
# territorio paralelas e desconectadas - country_scale.py (CountryScaleSystem,
# granularidade fina: NPCs/shops/minerio/fauna/subregioes, mas hardcoded a 1
# territorio por instancia) e world_systems.py (WorldSystems, granularidade
# macro: populacao/economia/faccoes, ja nativamente multi-territorio sob 1
# world_instance_id). Este arquivo NAO reescreve nenhum dos dois - orquestra
# N instancias de CountryScaleSystem (uma por territorio) + reaproveita
# WorldSystems como camada macro compartilhada sob o world_instance_id real.
#
# Correcao descoberta na implementacao (nao prevista no plano original): a
# tabela country_scale_state tem world_instance_id como FOREIGN KEY real pra
# worlds(world_instance_id) - nao da pra usar uma string sintetica arbitraria
# tipo "{wid}::{territory_id}" (living_runtime.py exige o formato estrito
# rt:<tipo>:<uuid> via validate_runtime_id). Cada territorio ganha entao um
# world_instance_id de verdade, mintado via LivingRuntime.create_world() (que
# ja cria a linha em worlds() + clocks() do jeito que o FK exige, sem
# nenhum SQL cru daqui) - e este arquivo guarda o mapeamento
# territory_id -> world_instance_id filho na sua propria tabela
# (v17_planet_territories), pra poder reidratar depois sem depender do
# chamador lembrar os ids gerados.
#
# 13 territorios confirmados no zip MASTER (STELLAR_TERRITORIES_V1_0.json):
# TER-001..013. Vertical slice desta fase usa 2 (nao os 13 de uma vez).
# ============================================================================

AUTHORITY = "ARPG_STAGE17_PLANET_RUNTIME_NOT_CANON"
VERSION = "V0.1.0-PRE-GODOT"


def _hash_state(d: dict[str, Any]) -> str:
    return sha256_text(canonical_json(d))


def _count_subregions(country_world: dict[str, Any]) -> int:
    """Conta subregioes reais geradas por CountryScaleSystem._build() em
    world['country']['states'][*]['blocks'][*]['subregions'] (chave
    confirmada em country_scale.py - _reconcile_subregions grava
    b['subregions']=subs por bloco)."""
    total = 0
    for state in country_world.get("country", {}).get("states", []):
        for block in state.get("blocks", []):
            total += len(block.get("subregions", []))
    return total


class PlanetSystem:
    """Orquestrador fino de multiplos territorios sob 1 world_instance_id
    "planeta". Nunca duplica logica de simulacao fina (CountryScaleSystem)
    nem macro (WorldSystems) - so roteia, aloca mundos-filho e agrega."""

    VERSION = VERSION
    AUTHORITY = AUTHORITY

    def __init__(self, runtime: Any, world_instance_id: str, master_release_path: str | Path,
                 *, territory_ids: tuple[str, ...] = ("TER-011", "TER-003"), seed: int = 1201) -> None:
        self.runtime = runtime
        self.world_instance_id = str(world_instance_id)
        self.master_release_path = str(master_release_path)
        self.seed = int(seed)
        self._init_db()

        stored = self._load_stored_territory_map()
        if stored is None:
            territory_map = {tid: self.runtime.create_world(
                f"planet:{self.world_instance_id}", self.seed)["world_instance_id"]
                for tid in territory_ids}
            self._persist_territory_map(territory_map)
        else:
            territory_map = stored

        self.territory_map: dict[str, str] = territory_map  # territory_id -> synthetic world_instance_id
        self.countries: dict[str, CountryScaleSystem] = {}
        for territory_id, synthetic_wid in territory_map.items():
            cs = CountryScaleSystem(master_release_path=self.master_release_path,
                                     country_territory_id=territory_id, seed=self.seed)
            cs.attach_runtime(self.runtime, synthetic_wid)
            self.countries[territory_id] = cs

        self.world_systems = WorldSystems(self.runtime)

    def _init_db(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                """CREATE TABLE IF NOT EXISTS v17_planet_territories(
                    world_instance_id TEXT NOT NULL,
                    territory_id TEXT NOT NULL,
                    child_world_instance_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, territory_id))"""
            )

    def _load_stored_territory_map(self) -> dict[str, str] | None:
        rows = self.runtime.conn.execute(
            "SELECT * FROM v17_planet_territories WHERE world_instance_id=?",
            (self.world_instance_id,),
        ).fetchall()
        if not rows:
            return None
        result: dict[str, str] = {}
        for r in rows:
            d = {"territory_id": r["territory_id"], "child_world_instance_id": r["child_world_instance_id"]}
            if _hash_state(d) != r["payload_hash"]:
                raise ValueError(f"planet territory state hash mismatch: {r['territory_id']}")
            result[r["territory_id"]] = r["child_world_instance_id"]
        return result

    def _persist_territory_map(self, territory_map: dict[str, str]) -> None:
        with self.runtime._write_lock:
            for territory_id, child_wid in territory_map.items():
                d = {"territory_id": territory_id, "child_world_instance_id": child_wid}
                h = _hash_state(d)
                self.runtime.conn.execute(
                    "INSERT OR REPLACE INTO v17_planet_territories VALUES(?,?,?,?)",
                    (self.world_instance_id, territory_id, child_wid, h),
                )

    # ---------- acesso ----------

    def territory_ref(self, territory_id: str) -> CountryScaleSystem:
        if territory_id not in self.countries:
            raise KeyError(f"territory {territory_id!r} not registered on this planet "
                            f"(registered: {sorted(self.countries)})")
        return self.countries[territory_id]

    def child_world_instance_id(self, territory_id: str) -> str:
        return self.territory_map[territory_id]

    def subregion_count(self, territory_id: str) -> int:
        return _count_subregions(self.territory_ref(territory_id).world)

    def registered_territory_ids(self) -> list[str]:
        return sorted(self.countries)

    # ---------- integridade ----------

    def persistence_integrity(self) -> dict[str, Any]:
        failures: list[str] = []
        rows = self.runtime.conn.execute(
            "SELECT * FROM v17_planet_territories WHERE world_instance_id=?",
            (self.world_instance_id,),
        ).fetchall()
        if not rows:
            failures.append("PLANET_STATE_MISSING")
        for r in rows:
            d = {"territory_id": r["territory_id"], "child_world_instance_id": r["child_world_instance_id"]}
            if _hash_state(d) != r["payload_hash"]:
                failures.append(f"PLANET_STATE_HASH:{r['territory_id']}")
        per_territory: dict[str, Any] = {}
        for territory_id, cs in self.countries.items():
            result = cs.persistence_integrity()
            per_territory[territory_id] = result
            if result.get("status") not in ("PASS", "SKIPPED"):
                failures.append(f"COUNTRY_INTEGRITY:{territory_id}")
        return {"status": "PASS" if not failures else "FAIL", "failures": failures,
                "territories": per_territory, "authority": self.AUTHORITY}
