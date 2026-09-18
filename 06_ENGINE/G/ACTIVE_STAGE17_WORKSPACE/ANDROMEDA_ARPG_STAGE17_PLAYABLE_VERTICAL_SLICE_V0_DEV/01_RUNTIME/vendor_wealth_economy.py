from __future__ import annotations

import json
import time
from typing import Any

from living_runtime import ConflictError, canonical_json, sha256_text


# ============================================================================
# ARPG_STAGE17_VENDOR_WEALTH_ECONOMY_RUNTIME_NOT_CANON
#
# arpg_economy_crafting_core.py (ARPGEconomyCraftingCore) ja rejeita venda do
# jogador pro NPC quando a carteira do vendedor nao cobre (VENDOR_FUNDS_INSUFFICIENT)
# e ja limita todo inventario, inclusive o do proprio vendedor, por slot/peso
# (arpg_item_core.py, INVENTORY_CAPACITY_EXCEEDED) - "NPC nao pode comprar
# infinitamente" e "itens tambem contam" ja estao resolvidos. As duas lacunas
# REAIS que este arquivo fecha: (1) create_vendor grava sempre 2000.0 fixo,
# sem refletir a riqueza territorial ja catalogada (STELLAR_SYSTEMIC_ECONOMY_STATE,
# campo welfare ALTO/MEDIO/BAIXO por territorio); (2) a carteira nunca se
# recupera com o tempo - um vendedor que gasta tudo fica quebrado pra sempre.
#
# Diferente da formula de agua (matematica pura, sem estado, por isso foi
# PORTADA em movement_multimodal.py), aqui e ESTADO PERSISTIDO COMPARTILHADO -
# a carteira do vendedor. Duplicar a tabela criaria dessincronia. Por isso
# este arquivo reaproveita os acessores ja existentes na MESMA tabela
# (economy.wallet()/economy._set_balance(), confirmados seguros de chamar de
# fora - leitura/escrita direta em arpg_economy_wallets, sem efeito colateral
# escondido), nunca cria uma carteira paralela.
#
# `economy` e QUALQUER objeto com .wallet(owner_ref)/._set_balance(owner_ref,
# balance) - nunca o ARPGEconomyCraftingCore real e obrigatorio aqui (esse
# exige o engine inteiro via engine.items_arpg()/engine.mobility_arpg(), nao e
# zip-free) - mesmo padrao duck-typed ja usado em CombatDistanceStateMachine
# (recebe `movement`, nao o ContinuousMovementSystem inteiro).
#
# _set_balance() nao passa pelo audit trail de arpg_economy_events (confirmado
# por investigacao) - por isso todo top-up/reabastecimento daqui tem seu
# PROPRIO journal de idempotencia, no molde de projectile_system.py.
#
# Padrao de tempo decorrido: espelha arpg_water_bag_survival_core.py#
# advance_water_time(delta_s, event_ref) - delta explicito do chamador,
# idempotente, soma num acumulador persistido. OFFLINE_CATCHUP_CAP_S espelha
# o valor ja declarado (mas nunca usado) em arpg_save_recovery_core.py.
# ============================================================================


WELFARE_BY_TERRITORY = {
    # espelha STELLAR_SYSTEMIC_ECONOMY_STATE_DEV_V1_0.json (19 territorios) -
    # mantido em sincronia manual, mesmo precedente de MAX_DIVE_DEPTH_M em
    # movement_multimodal.py.
    "TER-001": "MEDIO", "TER-002": "BAIXO", "TER-003": "MEDIO", "TER-004": "MEDIO",
    "TER-005": "MEDIO", "TER-006": "MEDIO", "TER-007": "MEDIO", "TER-008": "ALTO",
    "TER-009": "MEDIO", "TER-010": "MEDIO", "TER-011": "MEDIO", "TER-012": "BAIXO",
    "TER-013": "MEDIO", "TER-014": "MEDIO", "TER-015": "MEDIO", "TER-016": "MEDIO",
    "TER-017": "BAIXO", "TER-018": "MEDIO", "TER-019": "MEDIO",
}
WEALTH_MULTIPLIER_BY_WELFARE = {"ALTO": 1.5, "MEDIO": 1.0, "BAIXO": 0.6}
DEFAULT_WELFARE = "MEDIO"
BASE_VENDOR_WALLET = 2000.0          # espelha o valor fixo gravado por ARPGEconomyCraftingCore.create_vendor
OFFLINE_CATCHUP_CAP_S = 6 * 60 * 60  # espelha arpg_save_recovery_core.OFFLINE_CATCHUP_CAP_S


def tier_for_territory(territory_id: str) -> tuple[str, float]:
    welfare = WELFARE_BY_TERRITORY.get(territory_id, DEFAULT_WELFARE)
    return welfare, WEALTH_MULTIPLIER_BY_WELFARE[welfare]


def _hash_payload(d: dict[str, Any]) -> str:
    return sha256_text(canonical_json(d))


class VendorWealthEconomy:
    VERSION = "V0.1.0-PRE-GODOT"
    AUTHORITY = "ARPG_STAGE17_VENDOR_WEALTH_ECONOMY_RUNTIME_NOT_CANON"

    def __init__(self, runtime: Any, world_instance_id: str, economy: Any) -> None:
        self.runtime = runtime
        self.world_instance_id = str(world_instance_id)
        self.economy = economy
        self._init_db()

    def _init_db(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                """CREATE TABLE IF NOT EXISTS v17_vendor_wealth_tier(
                    world_instance_id TEXT NOT NULL, vendor_ref TEXT NOT NULL,
                    territory_id TEXT NOT NULL, welfare_tier TEXT NOT NULL, wallet_cap REAL NOT NULL,
                    last_replenish_wallclock_s REAL NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, vendor_ref))"""
            )
            self.runtime.conn.execute(
                """CREATE TABLE IF NOT EXISTS v17_vendor_wealth_events(
                    world_instance_id TEXT NOT NULL, event_ref TEXT NOT NULL,
                    event_type TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL, result_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, event_ref))"""
            )
            # S17 causal bridge (additive, separate table -- never touches the
            # existing v17_vendor_wealth_tier row/hash shape or its tests).
            # Lets outside pressures (corruption, drought/climate) shrink a
            # vendor's effective wallet ceiling without needing register_vendor
            # to be re-run (it isn't idempotent for that) and without
            # inventing a per-item price system that doesn't exist yet.
            self.runtime.conn.execute(
                """CREATE TABLE IF NOT EXISTS v17_vendor_price_pressure(
                    world_instance_id TEXT NOT NULL, vendor_ref TEXT NOT NULL,
                    corruption_multiplier REAL NOT NULL DEFAULT 1.0,
                    climate_multiplier REAL NOT NULL DEFAULT 1.0,
                    updated_wallclock_s REAL NOT NULL,
                    PRIMARY KEY(world_instance_id, vendor_ref))"""
            )

    # ---------- idempotencia (mesmo padrao de projectile_system.py) ----------

    def _event_existing(self, event_ref: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = self.runtime.conn.execute(
            "SELECT * FROM v17_vendor_wealth_events WHERE world_instance_id=? AND event_ref=?",
            (self.world_instance_id, str(event_ref)),
        ).fetchone()
        if not row:
            return None
        if sha256_text(canonical_json(payload)) != row["payload_hash"]:
            raise ConflictError(f"vendor wealth event_ref {event_ref} already used with a different payload")
        if row["event_type"] != event_type:
            raise ConflictError(f"vendor wealth event_ref {event_ref} already used for a different event_type")
        result = json.loads(row["result_json"])
        if sha256_text(row["result_json"]) != row["result_hash"]:
            raise ValueError("vendor wealth event result hash mismatch")
        return {**result, "idempotent_replay": True}

    def _record_event(self, event_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        ptext = canonical_json(payload)
        rtext = canonical_json(result)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT INTO v17_vendor_wealth_events VALUES(?,?,?,?,?,?)",
                (self.world_instance_id, str(event_ref), event_type, sha256_text(ptext), rtext, sha256_text(rtext)),
            )
        return result

    # ---------- estado do tier (hash-verificado) ----------

    def _row_state(self, r: Any) -> dict[str, Any]:
        d = {"vendor_ref": r["vendor_ref"], "territory_id": r["territory_id"], "welfare_tier": r["welfare_tier"],
             "wallet_cap": float(r["wallet_cap"]), "last_replenish_wallclock_s": float(r["last_replenish_wallclock_s"])}
        if _hash_payload(d) != r["payload_hash"]:
            raise ValueError("vendor wealth tier hash mismatch")
        return d

    def _read_tier(self, vendor_ref: str) -> dict[str, Any]:
        row = self.runtime.conn.execute(
            "SELECT * FROM v17_vendor_wealth_tier WHERE world_instance_id=? AND vendor_ref=?",
            (self.world_instance_id, str(vendor_ref)),
        ).fetchone()
        if not row:
            raise KeyError(vendor_ref)
        return self._row_state(row)

    def _save_tier(self, vendor_ref: str, territory_id: str, welfare_tier: str, wallet_cap: float,
                    last_replenish_wallclock_s: float) -> dict[str, Any]:
        d = {"vendor_ref": vendor_ref, "territory_id": territory_id, "welfare_tier": welfare_tier,
             "wallet_cap": wallet_cap, "last_replenish_wallclock_s": last_replenish_wallclock_s}
        h = _hash_payload(d)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO v17_vendor_wealth_tier VALUES(?,?,?,?,?,?,?)",
                (self.world_instance_id, vendor_ref, territory_id, welfare_tier, wallet_cap, last_replenish_wallclock_s, h),
            )
        return d

    # ---------- comandos ----------

    def register_vendor(self, vendor_ref: str, territory_id: str, *, event_ref: str,
                         now_wallclock_s: float | None = None) -> dict[str, Any]:
        payload = {"vendor_ref": vendor_ref, "territory_id": territory_id}
        replay = self._event_existing(event_ref, "REGISTER_VENDOR", payload)
        if replay is not None:
            return replay

        welfare, multiplier = tier_for_territory(territory_id)
        wallet_cap = round(BASE_VENDOR_WALLET * multiplier, 2)
        now = time.time() if now_wallclock_s is None else float(now_wallclock_s)

        current = self.economy.wallet(vendor_ref)
        current_balance = float(current["balance"])
        # nunca reduz um saldo ja acima do teto (nao e punitivo pra vendedor de
        # territorio pobre que ja recebeu 2000.0 fixo em create_vendor) - so
        # sobe ate o teto quando o vendedor esta abaixo dele.
        topped_up = False
        if current_balance < wallet_cap:
            self.economy._set_balance(vendor_ref, wallet_cap)
            topped_up = True

        self._save_tier(vendor_ref, territory_id, welfare, wallet_cap, now)
        result = {"status": "PASS", "event_ref": event_ref, "vendor_ref": vendor_ref, "territory_id": territory_id,
                  "welfare_tier": welfare, "wallet_cap": wallet_cap, "balance_before": current_balance,
                  "topped_up": topped_up, "balance_after": wallet_cap if topped_up else current_balance,
                  "authority": self.AUTHORITY, "idempotent_replay": False}
        return self._record_event(event_ref, "REGISTER_VENDOR", payload, result)

    def replenish(self, vendor_ref: str, *, event_ref: str, now_wallclock_s: float | None = None) -> dict[str, Any]:
        payload = {"vendor_ref": vendor_ref}
        replay = self._event_existing(event_ref, "REPLENISH", payload)
        if replay is not None:
            return replay

        tier = self._read_tier(vendor_ref)
        now = time.time() if now_wallclock_s is None else float(now_wallclock_s)
        raw_delta_s = max(0.0, now - tier["last_replenish_wallclock_s"])
        delta_s = min(raw_delta_s, OFFLINE_CATCHUP_CAP_S)

        rate_per_s = tier["wallet_cap"] / 86400.0  # recupera o teto inteiro em ~24h reais, a partir de zero
        restored = delta_s * rate_per_s

        current = self.economy.wallet(vendor_ref)
        current_balance = float(current["balance"])
        new_balance = min(tier["wallet_cap"], current_balance + restored)
        if new_balance != current_balance:
            self.economy._set_balance(vendor_ref, new_balance)

        self._save_tier(vendor_ref, tier["territory_id"], tier["welfare_tier"], tier["wallet_cap"], now)
        result = {"status": "PASS", "event_ref": event_ref, "vendor_ref": vendor_ref,
                  "elapsed_s_considered": round(delta_s, 6), "elapsed_s_capped": raw_delta_s > OFFLINE_CATCHUP_CAP_S,
                  "restored": round(new_balance - current_balance, 6),
                  "balance_before": current_balance, "balance_after": new_balance, "wallet_cap": tier["wallet_cap"],
                  "authority": self.AUTHORITY, "idempotent_replay": False}
        return self._record_event(event_ref, "REPLENISH", payload, result)

    def state(self, vendor_ref: str) -> dict[str, Any]:
        tier = self._read_tier(vendor_ref)
        live = self.economy.wallet(vendor_ref)
        pressure = self._read_price_pressure(vendor_ref)
        effective_cap = round(tier["wallet_cap"] * pressure["corruption_multiplier"] * pressure["climate_multiplier"], 2)
        return {
            **tier,
            "current_balance": float(live["balance"]),
            "price_pressure": pressure,
            "effective_wallet_cap": effective_cap,
            "authority": self.AUTHORITY,
        }

    # ---------- pressao externa (S17 causal bridges) ----------

    def _read_price_pressure(self, vendor_ref: str) -> dict[str, Any]:
        row = self.runtime.conn.execute(
            "SELECT corruption_multiplier, climate_multiplier FROM v17_vendor_price_pressure "
            "WHERE world_instance_id=? AND vendor_ref=?",
            (self.world_instance_id, str(vendor_ref)),
        ).fetchone()
        if not row:
            return {"corruption_multiplier": 1.0, "climate_multiplier": 1.0}
        return {"corruption_multiplier": float(row["corruption_multiplier"]), "climate_multiplier": float(row["climate_multiplier"])}

    def apply_price_pressure(
        self,
        vendor_ref: str,
        *,
        corruption_multiplier: float | None = None,
        climate_multiplier: float | None = None,
        now_wallclock_s: float | None = None,
    ) -> dict[str, Any]:
        """Sets the externally-computed pressure multipliers for this vendor.
        Idempotent by nature (last-write-wins on a value, not an event) since
        both callers (corruption tick, climate read) recompute from live
        source state every time -- there is nothing to replay.
        """
        current = self._read_price_pressure(vendor_ref)
        merged = {
            "corruption_multiplier": current["corruption_multiplier"] if corruption_multiplier is None else float(corruption_multiplier),
            "climate_multiplier": current["climate_multiplier"] if climate_multiplier is None else float(climate_multiplier),
        }
        now = time.time() if now_wallclock_s is None else float(now_wallclock_s)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO v17_vendor_price_pressure VALUES(?,?,?,?,?)",
                (self.world_instance_id, str(vendor_ref), merged["corruption_multiplier"], merged["climate_multiplier"], now),
            )
        return {"status": "PASS", "vendor_ref": vendor_ref, **merged, "authority": self.AUTHORITY}

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        rows = self.runtime.conn.execute(
            "SELECT * FROM v17_vendor_wealth_tier WHERE world_instance_id=?", (self.world_instance_id,)
        ).fetchall()
        for r in rows:
            try:
                self._row_state(r)
            except ValueError as e:
                failures.append(f"TIER_HASH:{r['vendor_ref']}:{e}")
        events = self.runtime.conn.execute(
            "SELECT * FROM v17_vendor_wealth_events WHERE world_instance_id=?", (self.world_instance_id,)
        ).fetchall()
        for r in events:
            if sha256_text(r["result_json"]) != r["result_hash"]:
                failures.append(f"EVENT_HASH:{r['event_ref']}")
        return {"status": "PASS" if not failures else "FAIL", "failures": failures,
                "vendors": len(rows), "events": len(events)}
