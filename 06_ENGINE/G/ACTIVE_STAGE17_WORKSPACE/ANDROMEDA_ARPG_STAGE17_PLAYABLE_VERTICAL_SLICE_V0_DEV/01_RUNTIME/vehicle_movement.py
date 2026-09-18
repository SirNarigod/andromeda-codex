from __future__ import annotations

import json
import math
from typing import Any

from living_runtime import ConflictError, ValidationError, canonical_json, sha256_text


# ============================================================================
# ARPG_STAGE17_VEHICLE_MOVEMENT_RUNTIME_NOT_CANON
#
# Nao existia nenhuma forma de um veiculo se mover livremente em qualquer
# direcao antes deste arquivo - arpg_mobility_infrastructure_core.py (Stage10,
# ja existente) so pula o veiculo entre as duas pontas fixas de um segmento de
# rota pre-cadastrado (travel()), sem posicao continua, sem direcao, sem
# fisica nenhuma. Jogador/NPC/criatura ja tem movimento livre multi-direcional
# de verdade via ContinuousMovementSystem/MultimodalMovementSystem - mas essas
# duas classes exigem que o entity_ref ja exista em country._all_npc_records()
# (chamam country.npc(entity_ref) incondicionalmente), sem caminho de registro
# avulso de uma entidade nova. Registrar veiculo como "NPC falso" acoplaria
# demais - por isso este sistema e AUTOCONTIDO, no molde de projectile_system.py:
# so recebe (runtime, world_instance_id, spatial), nunca o "engine" inteiro nem
# country/streaming/movement, continua testavel sem NPC/zip MASTER_V2.
#
# Duas fisicas novas que este arquivo introduz (nao existem em lugar nenhum do
# motor ainda):
#   - guinada/direcao: heading_deg persistido que gira no maximo
#     max_turn_rate_deg_s por segundo em direcao ao rumo desejado (nunca
#     instantaneo, ao contrario do heading_deg derivado a cada passo em
#     v15_motion_state);
#   - aceleracao/frenagem: current_speed_mps persistido que rampa em direcao a
#     velocidade comandada, no maximo accel_mps2 (acelerando) ou decel_mps2
#     (freando) por segundo.
#
# MAX_DIVE_DEPTH_M e VERTICAL_SPEED_MAX_MPS sao espelhados de
# movement_multimodal.py (mesmos valores, documentados aqui, mantidos em
# sincronia manualmente - mesmo precedente ja usado naquele arquivo pra nao
# depender de instancia alheia).
#
# Fora de escopo deste arquivo (decisao explicita, nao esquecimento):
#   - sincronizar posicao de passageiros (passenger_refs, ja existe em
#     arpg_vehicle_instances) com o veiculo em movimento;
#   - consumo de combustivel/propulsion durante drive() (so travel() debita
#     propulsion hoje);
#   - qualquer edicao em arpg_mobility_infrastructure_core.py - travel()
#     continua servindo pra viagem de longa distancia entre zonas; drive() e a
#     camada nova de navegacao livre/local, os dois coexistem sem se tocar.
# ============================================================================


MAX_DIVE_DEPTH_M = 30.0          # espelha MultimodalMovementSystem.MAX_DIVE_DEPTH_M
VERTICAL_SPEED_MAX_MPS = 6.0     # espelha MultimodalMovementSystem.VERTICAL_SPEED_MAX_MPS

_VALID_DOMAINS = ("GROUND", "AQUATIC", "SUBMERGED", "FLYING")

# Defaults de manobrabilidade por classe de veiculo (gameplay-derived, NOT_CANON
# - mesma disciplina de FLY_SPEEDS_MPS em movement_multimodal.py). ROAD_SERVICE/
# ROAD_CARGO/SCOUT espelham as 3 classes ja reais em VEHICLE_PROFILES de
# arpg_mobility_infrastructure_core.py (sem importar de la - zero acoplamento);
# WATERCRAFT/AIRCRAFT/SUBMERSIBLE sao novas, cobrindo os dominios que ainda nao
# tem nenhum perfil mecanico cadastrado. Toda chamada pode sobrescrever
# max_turn_rate_deg_s/accel_mps2/decel_mps2 explicitamente por cima destes
# defaults.
DEFAULT_HANDLING_BY_CLASS: dict[str, dict[str, float]] = {
    "ROAD_SERVICE": {"max_turn_rate_deg_s": 60.0, "accel_mps2": 3.0, "decel_mps2": 6.0},
    "ROAD_CARGO":   {"max_turn_rate_deg_s": 35.0, "accel_mps2": 1.5, "decel_mps2": 4.0},
    "SCOUT":        {"max_turn_rate_deg_s": 80.0, "accel_mps2": 4.0, "decel_mps2": 7.0},
    "WATERCRAFT":   {"max_turn_rate_deg_s": 20.0, "accel_mps2": 1.0, "decel_mps2": 1.5},
    "AIRCRAFT":     {"max_turn_rate_deg_s": 25.0, "accel_mps2": 2.0, "decel_mps2": 2.0},
    "SUBMERSIBLE":  {"max_turn_rate_deg_s": 15.0, "accel_mps2": 0.8, "decel_mps2": 1.2},
}


def map_transport_category_to_domain(category: str, transport_mode: str) -> str:
    """Traduz (category, transport_mode) do catalogo de lore
    (STELLAR_TRANSPORT_VEHICLES_CATALOG_DEV_V1_1.json) para um dos 4 dominios
    do motor. `category=TERRESTRE` inclui superficie aquatica por decisao de
    fase anterior do catalogo (ex.: VEI-002 Caravela de Navyr, VEI-007 Barcaca
    Encantada de Corrente sao TERRESTRE mas transport_mode
    NAVAL_SUPERFICIE/FLUVIAL) - o mapeamento correto depende do transport_mode,
    nunca so da category. VEI-005 (LEGADO_FORA_DA_GRADE, vagonete subterraneo)
    nao mapeia pra nenhum dos 4 dominios - levanta ValueError."""
    cat = str(category).upper()
    mode = str(transport_mode).upper()
    if cat == "VOADOR":
        return "FLYING"
    if cat == "SUBMERSO":
        return "SUBMERGED"
    if cat == "TERRESTRE":
        if mode in ("NAVAL_SUPERFICIE", "FLUVIAL"):
            return "AQUATIC"
        return "GROUND"
    raise ValueError(f"UNSUPPORTED_VEHICLE_CATEGORY:{cat}")


def _hash_state(d: dict[str, Any]) -> str:
    return sha256_text(canonical_json(d))


class VehicleMovementSystem:
    """Direcao livre (steering + aceleracao) para qualquer veiculo, nos 4
    dominios. Autocontido - so recebe (runtime, world_instance_id, spatial),
    nunca country/streaming/movement/engine inteiro."""

    VERSION = "V0.1.0-PRE-GODOT"
    AUTHORITY = "ARPG_STAGE17_VEHICLE_MOVEMENT_RUNTIME_NOT_CANON"

    def __init__(self, runtime: Any, world_instance_id: str, spatial: Any) -> None:
        self.runtime = runtime
        self.world_instance_id = str(world_instance_id)
        self.spatial = spatial
        self._init_db()

    def _init_db(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                """CREATE TABLE IF NOT EXISTS v17_vehicle_movement_state(
                    world_instance_id TEXT NOT NULL, vehicle_ref TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    iso_x_m REAL NOT NULL, iso_y_m REAL NOT NULL, altitude_m REAL NOT NULL DEFAULT 0,
                    heading_deg REAL NOT NULL DEFAULT 0,
                    current_speed_mps REAL NOT NULL DEFAULT 0,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, vehicle_ref))"""
            )
            self.runtime.conn.execute(
                """CREATE TABLE IF NOT EXISTS v17_vehicle_movement_events(
                    world_instance_id TEXT NOT NULL, event_ref TEXT NOT NULL,
                    event_type TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL, result_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, event_ref))"""
            )

    # ---------- idempotencia (mesmo padrao de projectile_system.py) ----------

    def _event_existing(self, event_ref: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = self.runtime.conn.execute(
            "SELECT * FROM v17_vehicle_movement_events WHERE world_instance_id=? AND event_ref=?",
            (self.world_instance_id, str(event_ref)),
        ).fetchone()
        if not row:
            return None
        if sha256_text(canonical_json(payload)) != row["payload_hash"]:
            raise ConflictError(f"vehicle event_ref {event_ref} already used with a different payload")
        if row["event_type"] != event_type:
            raise ConflictError(f"vehicle event_ref {event_ref} already used for a different event_type")
        result = json.loads(row["result_json"])
        if sha256_text(row["result_json"]) != row["result_hash"]:
            raise ValueError("vehicle event result hash mismatch")
        return {**result, "idempotent_replay": True}

    def _record_event(self, event_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        ptext = canonical_json(payload)
        rtext = canonical_json(result)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT INTO v17_vehicle_movement_events VALUES(?,?,?,?,?,?)",
                (self.world_instance_id, str(event_ref), event_type, sha256_text(ptext), rtext, sha256_text(rtext)),
            )
        return result

    # ---------- estado por veiculo (hash-verificado) ----------

    def _row_state(self, r: Any) -> dict[str, Any]:
        d = {"vehicle_ref": r["vehicle_ref"], "domain": r["domain"],
             "iso_x_m": float(r["iso_x_m"]), "iso_y_m": float(r["iso_y_m"]), "altitude_m": float(r["altitude_m"]),
             "heading_deg": float(r["heading_deg"]), "current_speed_mps": float(r["current_speed_mps"])}
        if _hash_state(d) != r["payload_hash"]:
            raise ValueError("vehicle movement state hash mismatch")
        return d

    def _read_state(self, vehicle_ref: str) -> dict[str, Any]:
        row = self.runtime.conn.execute(
            "SELECT * FROM v17_vehicle_movement_state WHERE world_instance_id=? AND vehicle_ref=?",
            (self.world_instance_id, str(vehicle_ref)),
        ).fetchone()
        if not row:
            raise KeyError(vehicle_ref)
        return self._row_state(row)

    def _save_state(self, vehicle_ref: str, domain: str, iso_x_m: float, iso_y_m: float, altitude_m: float,
                     heading_deg: float, current_speed_mps: float) -> dict[str, Any]:
        d = {"vehicle_ref": vehicle_ref, "domain": domain, "iso_x_m": iso_x_m, "iso_y_m": iso_y_m,
             "altitude_m": altitude_m, "heading_deg": heading_deg, "current_speed_mps": current_speed_mps}
        h = _hash_state(d)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO v17_vehicle_movement_state VALUES(?,?,?,?,?,?,?,?,?)",
                (self.world_instance_id, vehicle_ref, domain, iso_x_m, iso_y_m, altitude_m, heading_deg, current_speed_mps, h),
            )
        return d

    def state(self, vehicle_ref: str) -> dict[str, Any]:
        d = self._read_state(vehicle_ref)
        geo = self.spatial.isometric_to_geodetic(d["iso_x_m"], d["iso_y_m"], d["altitude_m"])
        return {**d, "geodetic": geo, "authority": self.AUTHORITY}

    # ---------- comandos ----------

    def spawn(self, vehicle_ref: str, *, origin: dict[str, float], domain: str, heading_deg: float = 0.0,
              event_ref: str) -> dict[str, Any]:
        if domain not in _VALID_DOMAINS:
            return {"status": "REJECTED", "reason": "INVALID_DOMAIN", "domain": domain}
        payload = {"vehicle_ref": vehicle_ref, "origin": origin, "domain": domain, "heading_deg": heading_deg}
        replay = self._event_existing(event_ref, "VEHICLE_SPAWN", payload)
        if replay is not None:
            return replay

        iso = self.spatial.geodetic_to_isometric(origin["longitude"], origin["latitude"], origin.get("altitude_m", 0.0))
        if domain in ("GROUND", "AQUATIC"):
            alt0 = 0.0
        elif domain == "SUBMERGED":
            alt0 = max(-MAX_DIVE_DEPTH_M, min(0.0, float(origin.get("altitude_m", 0.0))))
        else:  # FLYING
            alt0 = max(0.0, float(origin.get("altitude_m", 0.0)))

        d = self._save_state(vehicle_ref, domain, iso["iso_x_m"], iso["iso_y_m"], alt0, float(heading_deg) % 360.0, 0.0)
        geo = self.spatial.isometric_to_geodetic(d["iso_x_m"], d["iso_y_m"], d["altitude_m"])
        result = {"status": "PASS", "event_ref": event_ref, **d, "geodetic": geo,
                  "authority": self.AUTHORITY, "idempotent_replay": False}
        return self._record_event(event_ref, "VEHICLE_SPAWN", payload, result)

    def drive(self, vehicle_ref: str, *, target_heading_deg: float, commanded_speed_mps: float, duration_s: float,
              max_speed_mps: float, max_turn_rate_deg_s: float | None = None, accel_mps2: float | None = None,
              decel_mps2: float | None = None, vehicle_class: str | None = None, dz_intent: float = 0.0,
              allow_reverse: bool = True, event_ref: str) -> dict[str, Any]:
        if duration_s <= 0:
            raise ValidationError("duration_s must be positive")
        if max_speed_mps <= 0:
            raise ValidationError("max_speed_mps must be positive")

        handling = DEFAULT_HANDLING_BY_CLASS.get(vehicle_class or "", {})
        turn_rate = max_turn_rate_deg_s if max_turn_rate_deg_s is not None else handling.get("max_turn_rate_deg_s")
        accel = accel_mps2 if accel_mps2 is not None else handling.get("accel_mps2")
        decel = decel_mps2 if decel_mps2 is not None else handling.get("decel_mps2")
        if turn_rate is None or accel is None or decel is None:
            return {"status": "REJECTED", "reason": "HANDLING_PARAMS_REQUIRED"}

        payload = {"vehicle_ref": vehicle_ref, "target_heading_deg": target_heading_deg,
                   "commanded_speed_mps": commanded_speed_mps, "duration_s": duration_s,
                   "max_speed_mps": max_speed_mps, "max_turn_rate_deg_s": turn_rate,
                   "accel_mps2": accel, "decel_mps2": decel, "vehicle_class": vehicle_class,
                   "dz_intent": dz_intent, "allow_reverse": allow_reverse}
        replay = self._event_existing(event_ref, "VEHICLE_DRIVE", payload)
        if replay is not None:
            return replay

        current = self._read_state(vehicle_ref)
        domain = current["domain"]

        # guinada: menor diferenca angular (com wraparound 359 <-> 1), limitada
        # ao maximo que o veiculo pode girar neste tick.
        delta = ((float(target_heading_deg) - current["heading_deg"] + 180.0) % 360.0) - 180.0
        max_delta = turn_rate * duration_s
        clamped_delta = max(-max_delta, min(max_delta, delta))
        new_heading = (current["heading_deg"] + clamped_delta) % 360.0

        # aceleracao/frenagem: velocidade atual rampa em direcao a velocidade
        # comandada, nunca pula instantaneamente.
        reverse_cap = -max_speed_mps * 0.3 if allow_reverse else 0.0
        target_speed = max(reverse_cap, min(max_speed_mps, commanded_speed_mps))
        cur_speed = current["current_speed_mps"]
        diff = target_speed - cur_speed
        ramp_rate = accel if abs(target_speed) >= abs(cur_speed) else decel
        max_change = ramp_rate * duration_s
        change = max(-max_change, min(max_change, diff))
        new_speed = cur_speed + change

        # deslocamento ao longo do heading JA CORRIGIDO (nao do rumo bruto pedido)
        heading_rad = math.radians(new_heading)
        dist = new_speed * duration_s
        dx = math.cos(heading_rad) * dist
        dy = math.sin(heading_rad) * dist
        new_x = current["iso_x_m"] + dx
        new_y = current["iso_y_m"] + dy

        vz = max(-VERTICAL_SPEED_MAX_MPS, min(VERTICAL_SPEED_MAX_MPS, dz_intent))
        if domain == "GROUND":
            new_alt = 0.0
        elif domain == "AQUATIC":
            new_alt = 0.0  # embarcacao de superficie - sem mergulho
        elif domain == "SUBMERGED":
            new_alt = max(-MAX_DIVE_DEPTH_M, min(0.0, current["altitude_m"] + vz * duration_s))
        else:  # FLYING
            new_alt = max(0.0, current["altitude_m"] + vz * duration_s)

        saved = self._save_state(vehicle_ref, domain, new_x, new_y, new_alt, new_heading, new_speed)
        geo = self.spatial.isometric_to_geodetic(new_x, new_y, new_alt)
        result = {"status": "PASS", "event_ref": event_ref, "vehicle_ref": vehicle_ref, "domain": domain,
                  "heading_deg": round(new_heading, 6), "current_speed_mps": round(new_speed, 6),
                  "moved_m": round(abs(dist), 6), "iso_x_m": round(new_x, 6), "iso_y_m": round(new_y, 6),
                  "altitude_m": round(new_alt, 6), "geodetic": geo,
                  "authority": self.AUTHORITY, "idempotent_replay": False}
        return self._record_event(event_ref, "VEHICLE_DRIVE", payload, result)

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        rows = self.runtime.conn.execute(
            "SELECT * FROM v17_vehicle_movement_state WHERE world_instance_id=?", (self.world_instance_id,)
        ).fetchall()
        for r in rows:
            try:
                d = self._row_state(r)
            except ValueError as e:
                failures.append(f"STATE_HASH:{r['vehicle_ref']}:{e}")
                continue
            if d["domain"] == "GROUND" and abs(d["altitude_m"]) > 1e-6:
                failures.append(f"GROUND_ALTITUDE_NONZERO:{r['vehicle_ref']}")
            if d["domain"] == "AQUATIC" and abs(d["altitude_m"]) > 1e-6:
                failures.append(f"AQUATIC_ALTITUDE_NONZERO:{r['vehicle_ref']}")
            if d["domain"] == "SUBMERGED" and not (-MAX_DIVE_DEPTH_M - 1e-6 <= d["altitude_m"] <= 1e-6):
                failures.append(f"SUBMERGED_DEPTH_OUT_OF_RANGE:{r['vehicle_ref']}")
            if d["domain"] == "FLYING" and d["altitude_m"] < -1e-6:
                failures.append(f"FLYING_NEGATIVE_ALTITUDE:{r['vehicle_ref']}")
        events = self.runtime.conn.execute(
            "SELECT * FROM v17_vehicle_movement_events WHERE world_instance_id=?", (self.world_instance_id,)
        ).fetchall()
        for r in events:
            if sha256_text(r["result_json"]) != r["result_hash"]:
                failures.append(f"EVENT_HASH:{r['event_ref']}")
        return {"status": "PASS" if not failures else "FAIL", "failures": failures,
                "vehicles": len(rows), "events": len(events)}
