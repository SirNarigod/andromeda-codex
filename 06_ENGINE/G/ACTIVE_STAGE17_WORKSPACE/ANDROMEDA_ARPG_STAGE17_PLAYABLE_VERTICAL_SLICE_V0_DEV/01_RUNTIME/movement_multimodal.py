from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from living_runtime import ValidationError


# ============================================================================
# ARPG_STAGE17_MULTIMODAL_MOVEMENT_RUNTIME_NOT_CANON
#
# Adiciona os dominios AQUATIC, SUBMERGED e FLYING por cima do
# ContinuousMovementSystem (continuous_movement.py) ja existente e testado,
# que so implementa GROUND (WALK/RUN/CROUCH). Este arquivo NUNCA edita,
# subclassa ou monkeypatcha continuous_movement.py - so importa a classe e usa
# seus metodos publicos (step_vector, apply_external_stamina_cost,
# sync_to_geodetic, state). O dominio GROUND delega 100% para
# ContinuousMovementSystem.step_vector sem nenhuma logica nova (ver
# step_ground abaixo) - prova de que o sistema existente fica intocado.
#
# A formula de travessia de agua (WADE/SWIM) espelha
# arpg_water_bag_survival_core.WaterBagSurvivalCore.water_traversal_sample -
# foi PORTADA aqui (nao reutilizada via instancia daquela classe, que exige
# um "engine" completo + master_release_path para construir) porque a formula
# em si e pequena e auto-contida (so usa 2 constantes de classe + 1
# staticmethod, confirmado lendo o codigo-fonte linha a linha). Se
# WaterBagSurvivalCore mudar essa formula no futuro, esta copia precisa ser
# atualizada manualmente - documentado aqui de proposito.
#
# Numeros de gameplay (velocidades, custos de stamina, limites de profundidade
# e altitude) sao GAMEPLAY_DERIVED, nunca canone - ancorados nas faixas
# qualitativas ja catalogadas em
# 04_MECANICAS/ECONOMIA_E_RECURSOS/STELLAR_MOVEMENT_SPEED_REFERENCE_DEV_V1_0.json
# (aereo 40-80 km/h, submerso 5-15 km/h) quando aplicavel, e documentados com
# a razao ao lado de cada constante.
# ============================================================================


def _hash_payload(d: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ---- formula de agua portada de WaterBagSurvivalCore.water_traversal_sample ----
# (arpg_water_bag_survival_core.py, verificado: usa so SHALLOW_DEPTH_M,
# VEHICLE_MAX_WADE_DEPTH_M e _flow_class - nenhuma outra dependencia de instancia)
_SHALLOW_DEPTH_M = 0.65


def _flow_class(flow_speed_mps: float) -> tuple[str, float]:
    f = max(0.0, float(flow_speed_mps))
    if f < 0.45:
        return "CALM", 1.0
    if f < 1.15:
        return "CURRENT", 1.35
    return "STRONG_CURRENT", 1.85


def _water_traversal_sample(*, depth_m: float, flow_speed_mps: float, distance_m: float, load_fraction: float) -> dict[str, Any]:
    depth = max(0.0, float(depth_m))
    distance = max(0.0, float(distance_m))
    load = min(2.0, max(0.0, float(load_fraction)))
    flow_class, flow_factor = _flow_class(flow_speed_mps)
    shallow = depth <= _SHALLOW_DEPTH_M
    mode = "WADE" if shallow else "SWIM"
    base_per_m = 0.34 if shallow else 0.95
    depth_factor = (1.0 + (depth / max(0.1, _SHALLOW_DEPTH_M)) * 0.18) if shallow else (1.35 + min(2.0, depth - _SHALLOW_DEPTH_M) * 0.18)
    load_factor = 1.0 + 0.75 * load
    stamina_cost = distance * base_per_m * depth_factor * flow_factor * load_factor
    speed_factor = max(0.25, 1.0 / (1.0 + 0.30 * (depth_factor - 1.0) + 0.20 * (flow_factor - 1.0) + 0.15 * load))
    return {
        "mode": mode, "stamina_cost": round(stamina_cost, 6), "speed_factor": round(speed_factor, 6),
        "flow_class": flow_class, "shallow": shallow,
    }


class MultimodalMovementSystem:
    """Estende ContinuousMovementSystem com dominios AQUATIC/SUBMERGED/FLYING.

    Numeros de velocidade/stamina/profundidade/altitude sao politica de
    gameplay ajustavel, nunca fato canonico de Stellar.
    """

    VERSION = "V0.1.0-PRE-GODOT"
    AUTHORITY = "ARPG_STAGE17_MULTIMODAL_MOVEMENT_RUNTIME_NOT_CANON"

    # profundidade maxima de mergulho livre - teto de gameplay plausivel
    MAX_DIVE_DEPTH_M = 30.0
    # custo extra de stamina por metro de profundidade alem do raso, simulando pressao
    PRESSURE_COST_PER_M = 0.15

    # velocidades de voo: cruise ~58km/h e sprint ~79km/h, dentro da faixa
    # "aereo 40-80 km/h" ja catalogada em STELLAR_MOVEMENT_SPEED_REFERENCE_DEV_V1_0.json
    FLY_SPEEDS_MPS = {"HOVER": 0.0, "CRUISE": 16.0, "SPRINT": 22.0}
    VERTICAL_SPEED_MAX_MPS = 6.0   # ~1/3 do cruise - taxa de subida/descida controlada plausivel
    STALL_SPEED_MPS = 5.0         # velocidade minima sustentada abaixo da qual o voo estola (simplificado)
    STALL_GRACE_S = 1.5           # janela curta antes do estol virar queda real
    FALL_SPEED_MPS = 9.0          # queda a taxa constante (nao integra g=9.8 - mantem determinismo discreto do engine)
    FLIGHT_STAMINA_COST_PER_S = 0.6  # dreno continuo moderado (entre custo de RUN e regen de WALK)

    def __init__(self, runtime: Any, world_instance_id: str, country: Any, spatial: Any, streaming: Any, movement: Any) -> None:
        self.runtime = runtime
        self.world_instance_id = str(world_instance_id)
        self.country = country
        self.spatial = spatial
        self.streaming = streaming
        self.movement = movement
        self._init_db()
        self.bootstrap()

    def _init_db(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                """CREATE TABLE IF NOT EXISTS v17_multimodal_domain_state(
                    world_instance_id TEXT NOT NULL, entity_ref TEXT NOT NULL,
                    domain TEXT NOT NULL DEFAULT 'GROUND',
                    vertical_velocity_mps REAL NOT NULL DEFAULT 0,
                    stall_state TEXT NOT NULL DEFAULT 'STABLE',
                    low_speed_timer_s REAL NOT NULL DEFAULT 0,
                    depth_state TEXT NOT NULL DEFAULT 'SURFACE',
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, entity_ref))"""
            )

    def _save(self, entity_ref: str, state: dict[str, Any]) -> None:
        payload = {k: state[k] for k in ("domain", "vertical_velocity_mps", "stall_state", "low_speed_timer_s", "depth_state")}
        h = _hash_payload(payload)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO v17_multimodal_domain_state VALUES(?,?,?,?,?,?,?,?)",
                (self.world_instance_id, entity_ref, payload["domain"], payload["vertical_velocity_mps"],
                 payload["stall_state"], payload["low_speed_timer_s"], payload["depth_state"], h),
            )

    def _row_state(self, r: Any) -> dict[str, Any]:
        d = {
            "domain": r["domain"], "vertical_velocity_mps": float(r["vertical_velocity_mps"]),
            "stall_state": r["stall_state"], "low_speed_timer_s": float(r["low_speed_timer_s"]),
            "depth_state": r["depth_state"],
        }
        if _hash_payload(d) != r["payload_hash"]:
            raise ValueError("multimodal domain state hash mismatch")
        return d

    def bootstrap(self) -> dict[str, Any]:
        created = 0
        for n in self.country._all_npc_records():
            row = self.runtime.conn.execute(
                "SELECT * FROM v17_multimodal_domain_state WHERE world_instance_id=? AND entity_ref=?",
                (self.world_instance_id, n["id"]),
            ).fetchone()
            if row:
                continue
            self._save(n["id"], {"domain": "GROUND", "vertical_velocity_mps": 0.0, "stall_state": "STABLE",
                                  "low_speed_timer_s": 0.0, "depth_state": "SURFACE"})
            created += 1
        return {"status": "PASS", "created": created}

    def domain_state(self, entity_ref: str) -> dict[str, Any]:
        r = self.runtime.conn.execute(
            "SELECT * FROM v17_multimodal_domain_state WHERE world_instance_id=? AND entity_ref=?",
            (self.world_instance_id, entity_ref),
        ).fetchone()
        if not r:
            raise KeyError(entity_ref)
        return {"entity_ref": entity_ref, **self._row_state(r), "authority": self.AUTHORITY}

    def state(self, entity_ref: str) -> dict[str, Any]:
        """Repassa para o ContinuousMovementSystem - deixa esta classe compativel
        com qualquer consumidor que so precisa de .state() (ex. combat_distance_states.py)."""
        return self.movement.state(entity_ref)

    # ---------------- GROUND ----------------
    def step_ground(self, entity_ref: str, dx: float, dy: float, *, duration_s: float = .25, mode: str = "WALK", environment_factor: float | None = None) -> dict[str, Any]:
        result = self.movement.step_vector(entity_ref, dx, dy, duration_s=duration_s, mode=mode, environment_factor=environment_factor)
        if result.get("status") == "PASS":
            ds = self.domain_state(entity_ref)
            self._save(entity_ref, {**ds, "domain": "GROUND"})
        return {**result, "domain": "GROUND"}

    # ---------------- AQUATIC ----------------
    def step_aquatic(self, entity_ref: str, dx: float, dy: float, *, duration_s: float = .25, depth_m: float,
                      flow_speed_mps: float = 0.0, load_fraction: float = 0.0, under_bridge: bool = False,
                      actor_kind: str = "PLAYER") -> dict[str, Any]:
        distance_m = math.hypot(float(dx), float(dy))
        sample = _water_traversal_sample(depth_m=depth_m, flow_speed_mps=flow_speed_mps, distance_m=distance_m, load_fraction=load_fraction)
        move = self.movement.step_vector(entity_ref, dx, dy, duration_s=duration_s, mode="WALK", environment_factor=sample["speed_factor"])
        if move.get("status") != "PASS":
            return {**move, "domain": "AQUATIC", "water_mode": sample["mode"]}
        stamina_result = self.movement.apply_external_stamina_cost(entity_ref, sample["stamina_cost"], reason=f"AQUATIC_TRAVERSAL:{sample['mode']}")
        target_altitude = 0.0 if sample["mode"] == "WADE" else -min(0.5, depth_m * 0.3)
        self.movement.sync_to_geodetic(entity_ref, {**move["geodetic"], "altitude_m": target_altitude}, reason="AQUATIC_ALTITUDE_ADJUST")
        depth_state = "SURFACE" if sample["mode"] == "WADE" else "SHALLOW"
        ds = self.domain_state(entity_ref)
        self._save(entity_ref, {**ds, "domain": "AQUATIC", "depth_state": depth_state})
        return {**move, "domain": "AQUATIC", "water_mode": sample["mode"], "flow_class": sample["flow_class"],
                "stamina_cost_applied": stamina_result.get("stamina_cost_applied"), "altitude_m": target_altitude}

    # ---------------- SUBMERGED ----------------
    def step_submerged(self, entity_ref: str, dx: float, dy: float, *, target_depth_m: float, duration_s: float = .25,
                        flow_speed_mps: float = 0.0, load_fraction: float = 0.0, actor_kind: str = "PLAYER") -> dict[str, Any]:
        if target_depth_m > self.MAX_DIVE_DEPTH_M:
            return {"status": "REJECTED", "reason": "DEPTH_LIMIT_EXCEEDED", "max_depth_m": self.MAX_DIVE_DEPTH_M}
        distance_m = math.hypot(float(dx), float(dy))
        sample = _water_traversal_sample(depth_m=target_depth_m, flow_speed_mps=flow_speed_mps, distance_m=distance_m, load_fraction=load_fraction)
        move = self.movement.step_vector(entity_ref, dx, dy, duration_s=duration_s, mode="WALK", environment_factor=sample["speed_factor"])
        if move.get("status") != "PASS":
            return {**move, "domain": "SUBMERGED"}
        base_cost = self.movement.apply_external_stamina_cost(entity_ref, sample["stamina_cost"], reason="SUBMERGED_TRAVERSAL")
        pressure_cost_amount = self.PRESSURE_COST_PER_M * max(0.0, target_depth_m - _SHALLOW_DEPTH_M)
        pressure_result = self.movement.apply_external_stamina_cost(entity_ref, pressure_cost_amount, reason="SUBMERGED_PRESSURE")
        self.movement.sync_to_geodetic(entity_ref, {**move["geodetic"], "altitude_m": -float(target_depth_m)}, reason="SUBMERGED_DEPTH_SET")
        depth_state = "DEEP" if target_depth_m > _SHALLOW_DEPTH_M else "SHALLOW"
        ds = self.domain_state(entity_ref)
        self._save(entity_ref, {**ds, "domain": "SUBMERGED", "depth_state": depth_state})
        return {**move, "domain": "SUBMERGED", "depth_state": depth_state, "altitude_m": -float(target_depth_m),
                "stamina_cost_applied": base_cost.get("stamina_cost_applied"),
                "pressure_cost_applied": pressure_result.get("stamina_cost_applied")}

    # ---------------- FLYING ----------------
    def _reconcile_block_chunk(self, entity_ref: str, geo: dict[str, Any]) -> dict[str, Any]:
        """Reconciliacao minima de chunk apos um passo de voo - sync_to_geodetic
        (continuous_movement.py) nao faz isso sozinho, so step_vector faz.
        Replica so a parte de chunk-ownership (nao mexe em bloco/cidade, que sao
        irrelevantes em altitude - creaturas voadoras nao mudam de "bloco" administrativo
        so por estarem no ar)."""
        ch = self.spatial.chunk_for_geodetic(geo["longitude"], geo["latitude"])["chunk_id"]
        oldch = self.streaming.owners.get(entity_ref)
        transfer = None
        if oldch != ch:
            transfer = self.streaming.transfer(entity_ref, ch)
            self.streaming.prune_loaded_chunks(set(self.spatial.chunk_neighbors(ch, 1)))
        return {"chunk_id": ch, "chunk_changed": oldch != ch, "ownership": transfer}

    def step_flying(self, entity_ref: str, dx: float, dy: float, dz: float, *, duration_s: float = .25,
                     mode: str = "CRUISE", environment_factor: float | None = None) -> dict[str, Any]:
        if mode not in self.FLY_SPEEDS_MPS:
            return {"status": "REJECTED", "reason": "UNSUPPORTED_FLIGHT_MODE"}
        if duration_s <= 0 or duration_s > 10:
            return {"status": "REJECTED", "reason": "INVALID_STEP_DURATION"}
        envf = max(.25, min(1.25, float(environment_factor) if environment_factor is not None else 1.0))
        ds = self.domain_state(entity_ref)
        move_state = self.movement.state(entity_ref)

        horiz_mag = math.hypot(float(dx), float(dy))
        base_speed = self.FLY_SPEEDS_MPS[mode]
        maxdist = base_speed * float(duration_s) * envf

        stall_state = ds["stall_state"]
        low_speed_timer = ds["low_speed_timer_s"]
        vertical_delta = max(-self.VERTICAL_SPEED_MAX_MPS * duration_s, min(self.VERTICAL_SPEED_MAX_MPS * duration_s, float(dz)))

        # HOVER e por definicao um voo parado e sustentado (helicoptero/paira magico) -
        # nunca estola. CRUISE/SPRINT estolam quando a velocidade EFETIVA (apos o fator
        # de ambiente, ex. vento contrario forte) cai abaixo do minimo de sustentacao -
        # a magnitude de dx/dy so define direcao (mesma convencao de step_vector),
        # nao velocidade, entao o estol depende so de modo x fator de ambiente.
        effective_speed = base_speed * envf
        if mode != "HOVER" and effective_speed < self.STALL_SPEED_MPS:
            low_speed_timer += duration_s
        else:
            low_speed_timer = 0.0

        if low_speed_timer >= self.STALL_GRACE_S:
            stall_state = "FALLING"
            vertical_delta = -self.FALL_SPEED_MPS * duration_s
        elif low_speed_timer > 0:
            stall_state = "STALLING"
        else:
            stall_state = "STABLE"

        if horiz_mag > 1e-12:
            ux, uy = float(dx) / horiz_mag, float(dy) / horiz_mag
            nx = move_state["iso_x_m"] + ux * maxdist
            ny = move_state["iso_y_m"] + uy * maxdist
        else:
            nx, ny = move_state["iso_x_m"], move_state["iso_y_m"]
        new_altitude = max(0.0, move_state["altitude_m"] + vertical_delta)

        geo = self.spatial.isometric_to_geodetic(nx, ny, new_altitude)
        self.movement.sync_to_geodetic(entity_ref, geo, reason="FLIGHT_STEP")
        recon = self._reconcile_block_chunk(entity_ref, geo)
        stamina_result = self.movement.apply_external_stamina_cost(entity_ref, self.FLIGHT_STAMINA_COST_PER_S * duration_s, reason="FLIGHT_UPKEEP")

        self._save(entity_ref, {**ds, "domain": "FLYING", "vertical_velocity_mps": vertical_delta / duration_s,
                                 "stall_state": stall_state, "low_speed_timer_s": low_speed_timer})

        landed = False
        if new_altitude <= 0.0 and stall_state == "FALLING":
            self.land(entity_ref)
            landed = True

        return {"status": "PASS", "entity_ref": entity_ref, "domain": "FLYING", "mode": mode,
                "moved_m": round(maxdist, 6), "altitude_m": round(new_altitude, 6),
                "vertical_velocity_mps": round(vertical_delta / duration_s, 6), "stall_state": stall_state,
                "low_speed_timer_s": round(low_speed_timer, 6), "geodetic": geo, "landed": landed,
                "stamina": stamina_result.get("stamina_after"), **recon, "authority": self.AUTHORITY}

    def land(self, entity_ref: str) -> dict[str, Any]:
        move_state = self.movement.state(entity_ref)
        geo = self.spatial.isometric_to_geodetic(move_state["iso_x_m"], move_state["iso_y_m"], 0.0)
        self.movement.sync_to_geodetic(entity_ref, geo, reason="LANDING")
        self._reconcile_block_chunk(entity_ref, geo)
        ds = self.domain_state(entity_ref)
        self._save(entity_ref, {**ds, "domain": "GROUND", "vertical_velocity_mps": 0.0, "stall_state": "STABLE", "low_speed_timer_s": 0.0})
        return {"status": "PASS", "entity_ref": entity_ref, "domain": "GROUND"}

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        rows = self.runtime.conn.execute(
            "SELECT * FROM v17_multimodal_domain_state WHERE world_instance_id=?", (self.world_instance_id,)
        ).fetchall()
        for r in rows:
            try:
                d = self._row_state(r)
            except ValueError as e:
                failures.append(f"DOMAIN_STATE_HASH:{r['entity_ref']}:{e}")
                continue
            try:
                mv = self.movement.state(r["entity_ref"])
            except Exception as e:
                failures.append(f"MOVEMENT_STATE_MISSING:{r['entity_ref']}:{e}")
                continue
            if d["domain"] == "SUBMERGED" and mv["altitude_m"] >= 0:
                failures.append(f"SUBMERGED_ALTITUDE_NOT_NEGATIVE:{r['entity_ref']}")
            if d["domain"] == "FLYING" and d["stall_state"] == "STABLE" and mv["altitude_m"] < 0:
                failures.append(f"FLYING_STABLE_NEGATIVE_ALTITUDE:{r['entity_ref']}")
        return {"status": "PASS" if not failures else "FAIL", "failures": failures, "states": len(rows)}
