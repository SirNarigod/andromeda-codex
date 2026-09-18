from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from living_runtime import canonical_json, sha256_text


# ============================================================================
# ARPG_STAGE17_PERCEPTION_RUNTIME_NOT_CANON
#
# Nao existia nenhum sistema de percepcao espacial em lugar nenhum do motor
# antes deste arquivo (confirmado por busca exaustiva) - arpg_actor_core.py so
# tem aggro omnidirecional por raio (DEFAULT_AGGRO_M=9.0, sem angulo, sem
# parede) e agent_brain.py#record_perception() e so um log generico de
# observacoes, sem geometria nenhuma.
#
# O nucleo (CircleObstacle + segment_intersects_circle/line_of_sight_clear/
# angle_within_fov) e PURO - sem __init__, sem runtime/country/movement, no
# molde de projectile_system.py - so dataclass congelada + funcoes. A oclusao
# de "parede" usa a MESMA matematica de segmento-vs-esfera ja validada em
# projectile_system.py, so em 2D (sem eixo de gravidade/tempo de voo): como
# nao existe nenhum poligono de construcao no motor (so ponto + area_m2), cada
# predio vira um CIRCULO aproximado (raio = sqrt(area_m2/pi)) - aproximacao de
# rodape, documentada, nao silhueta real.
#
# A classe PerceptionSystem por cima e um wrapper fino que so recebe
# (runtime, world_instance_id, movement) - `movement` e qualquer objeto com
# .state(entity_ref), nunca o ContinuousMovementSystem inteiro exigido, mesmo
# padrao duck-typed ja usado em CombatDistanceStateMachine.
#
# Classificacao de ameaca (PASSIVO/HOSTIL no bestiario, ALLIED/FRIENDLY/
# NEUTRAL/WARY/HOSTILE em arpg_actor_core.py) so existe como lore estatico
# hoje, sem espelho no motor - por isso `can_go_hostile` e um bool explicito
# por chamada (quem chama decide a partir da fonte que tiver), nunca derivado
# sozinho aqui. Isso implementa literalmente "NPC neutro que nao da hostil
# apenas ignora": can_go_hostile=False pula toda a geometria, custo zero.
# ============================================================================


@dataclass(frozen=True)
class CircleObstacle:
    ref: str
    center_x: float
    center_y: float
    radius_m: float


def building_to_circle_obstacle(est_id: str, iso_x_m: float, iso_y_m: float, area_m2: float) -> CircleObstacle:
    """Aproxima o rodape de uma construcao como um circulo (nao ha poligono real
    catalogado no motor) - radius = sqrt(area_m2/pi), mesma area do predio."""
    radius = math.sqrt(max(0.0, area_m2) / math.pi)
    return CircleObstacle(ref=est_id, center_x=iso_x_m, center_y=iso_y_m, radius_m=radius)


def segment_intersects_circle(p1: tuple[float, float], p2: tuple[float, float], obstacle: CircleObstacle) -> bool:
    """Menor distancia do centro do circulo ao segmento p1->p2 (projecao escalar
    clampada em [0,1]) - mesmo tipo de matematica ja usada em
    projectile_system._closest_approach_time, sem o eixo de gravidade/tempo."""
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = x2 - x1, y2 - y1
    seg_len2 = dx * dx + dy * dy
    if seg_len2 < 1e-12:
        t = 0.0
    else:
        t = ((obstacle.center_x - x1) * dx + (obstacle.center_y - y1) * dy) / seg_len2
        t = max(0.0, min(1.0, t))
    closest_x, closest_y = x1 + t * dx, y1 + t * dy
    dist = math.hypot(closest_x - obstacle.center_x, closest_y - obstacle.center_y)
    return dist <= obstacle.radius_m


def line_of_sight_clear(observer_xy: tuple[float, float], target_xy: tuple[float, float],
                         obstacles: tuple[CircleObstacle, ...] = ()) -> bool:
    return not any(segment_intersects_circle(observer_xy, target_xy, o) for o in obstacles)


def angle_within_fov(observer_xy: tuple[float, float], observer_heading_deg: float, fov_deg: float,
                      target_xy: tuple[float, float]) -> bool:
    dx = target_xy[0] - observer_xy[0]
    dy = target_xy[1] - observer_xy[1]
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return True  # alvo na mesma posicao do observador - sempre "visivel"
    bearing_deg = math.degrees(math.atan2(dy, dx)) % 360.0
    # menor diferenca angular, com wraparound (mesma formula ja usada em
    # vehicle_movement.py pra guinada) - evita o bug classico de 350 vs 10 graus.
    delta = ((bearing_deg - observer_heading_deg + 180.0) % 360.0) - 180.0
    return abs(delta) <= fov_deg / 2.0


VISION_PROFILE_BY_CATEGORY: dict[str, dict[str, float]] = {
    "HUMANOID": {"fov_deg": 110.0, "range_m": 20.0},
    "PREDATOR_QUADRUPED": {"fov_deg": 150.0, "range_m": 25.0},
    "AVIAN": {"fov_deg": 200.0, "range_m": 35.0},
    "SWARM_INSECT": {"fov_deg": 300.0, "range_m": 8.0},
    "SUBTERRANEAN": {"fov_deg": 60.0, "range_m": 6.0},
    "AQUATIC": {"fov_deg": 130.0, "range_m": 15.0},
}
DEFAULT_VISION_PROFILE = {"fov_deg": 110.0, "range_m": 20.0}

# espelha as chaves de ContinuousMovementSystem.SPEEDS_MPS - raio de audicao
# cresce com a velocidade/barulho do modo de movimento do ALVO (nao do
# observador): agachado=pouco som, correndo=muito som.
HEARING_RADIUS_BY_MODE: dict[str, float] = {"CROUCH": 3.0, "WALK": 10.0, "RUN": 22.0}
DEFAULT_HEARING_RADIUS_M = HEARING_RADIUS_BY_MODE["WALK"]

STATE_IGNORED, STATE_UNAWARE, STATE_SUSPICIOUS, STATE_SEEN = "IGNORED", "UNAWARE", "SUSPICIOUS", "SEEN"


def _hash_state(d: dict[str, Any]) -> str:
    return sha256_text(canonical_json(d))


class PerceptionSystem:
    VERSION = "V0.1.0-PRE-GODOT"
    AUTHORITY = "ARPG_STAGE17_PERCEPTION_RUNTIME_NOT_CANON"

    def __init__(self, runtime: Any, world_instance_id: str, movement: Any) -> None:
        self.runtime = runtime
        self.world_instance_id = str(world_instance_id)
        self.movement = movement
        self._init_db()

    def _init_db(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                """CREATE TABLE IF NOT EXISTS v17_perception_state(
                    world_instance_id TEXT NOT NULL, observer_ref TEXT NOT NULL, target_ref TEXT NOT NULL,
                    state TEXT NOT NULL,
                    last_known_x_m REAL, last_known_y_m REAL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, observer_ref, target_ref))"""
            )

    def _row_state(self, r: Any) -> dict[str, Any]:
        d = {"observer_ref": r["observer_ref"], "target_ref": r["target_ref"], "state": r["state"],
             "last_known_x_m": r["last_known_x_m"], "last_known_y_m": r["last_known_y_m"]}
        if _hash_state(d) != r["payload_hash"]:
            raise ValueError("perception state hash mismatch")
        return d

    def _save(self, observer_ref: str, target_ref: str, state: str,
               last_known_x_m: float | None, last_known_y_m: float | None) -> dict[str, Any]:
        d = {"observer_ref": observer_ref, "target_ref": target_ref, "state": state,
             "last_known_x_m": last_known_x_m, "last_known_y_m": last_known_y_m}
        h = _hash_state(d)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO v17_perception_state VALUES(?,?,?,?,?,?,?)",
                (self.world_instance_id, observer_ref, target_ref, state, last_known_x_m, last_known_y_m, h),
            )
        return d

    def _existing(self, observer_ref: str, target_ref: str) -> dict[str, Any] | None:
        row = self.runtime.conn.execute(
            "SELECT * FROM v17_perception_state WHERE world_instance_id=? AND observer_ref=? AND target_ref=?",
            (self.world_instance_id, observer_ref, target_ref),
        ).fetchone()
        return self._row_state(row) if row else None

    def check(self, observer_ref: str, target_ref: str, *, observer_heading_deg: float, can_go_hostile: bool,
               vision_category: str | None = None, vision_fov_deg: float | None = None,
               vision_range_m: float | None = None, obstacles: tuple[CircleObstacle, ...] = ()) -> dict[str, Any]:
        if not can_go_hostile:
            saved = self._save(observer_ref, target_ref, STATE_IGNORED, None, None)
            return {"status": "PASS", **saved, "authority": self.AUTHORITY}

        profile = VISION_PROFILE_BY_CATEGORY.get(vision_category, DEFAULT_VISION_PROFILE) if vision_category else DEFAULT_VISION_PROFILE
        fov_deg = vision_fov_deg if vision_fov_deg is not None else profile["fov_deg"]
        range_m = vision_range_m if vision_range_m is not None else profile["range_m"]

        observer_state = self.movement.state(observer_ref)
        target_state = self.movement.state(target_ref)
        observer_xy = (float(observer_state["iso_x_m"]), float(observer_state["iso_y_m"]))
        target_xy = (float(target_state["iso_x_m"]), float(target_state["iso_y_m"]))
        distance_m = math.hypot(target_xy[0] - observer_xy[0], target_xy[1] - observer_xy[1])

        seen = (
            distance_m <= range_m
            and angle_within_fov(observer_xy, observer_heading_deg, fov_deg, target_xy)
            and line_of_sight_clear(observer_xy, target_xy, obstacles)
        )
        if seen:
            saved = self._save(observer_ref, target_ref, STATE_SEEN, target_xy[0], target_xy[1])
            return {"status": "PASS", **saved, "distance_m": round(distance_m, 6), "authority": self.AUTHORITY}

        target_mode = str(target_state.get("mode", "WALK")).upper()
        hearing_radius_m = HEARING_RADIUS_BY_MODE.get(target_mode, DEFAULT_HEARING_RADIUS_M)
        if distance_m <= hearing_radius_m:
            saved = self._save(observer_ref, target_ref, STATE_SUSPICIOUS, target_xy[0], target_xy[1])
            return {"status": "PASS", **saved, "distance_m": round(distance_m, 6),
                    "hearing_radius_m": hearing_radius_m, "authority": self.AUTHORITY}

        # UNAWARE - mantem a ultima posicao conhecida de uma deteccao anterior (se houver),
        # nunca apaga o rastro so porque o alvo saiu do alcance agora.
        previous = self._existing(observer_ref, target_ref)
        last_x = previous["last_known_x_m"] if previous else None
        last_y = previous["last_known_y_m"] if previous else None
        saved = self._save(observer_ref, target_ref, STATE_UNAWARE, last_x, last_y)
        return {"status": "PASS", **saved, "distance_m": round(distance_m, 6), "authority": self.AUTHORITY}

    def state_for_pair(self, observer_ref: str, target_ref: str) -> dict[str, Any]:
        row = self.runtime.conn.execute(
            "SELECT * FROM v17_perception_state WHERE world_instance_id=? AND observer_ref=? AND target_ref=?",
            (self.world_instance_id, observer_ref, target_ref),
        ).fetchone()
        if not row:
            raise KeyError((observer_ref, target_ref))
        return {**self._row_state(row), "authority": self.AUTHORITY}

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        rows = self.runtime.conn.execute(
            "SELECT * FROM v17_perception_state WHERE world_instance_id=?", (self.world_instance_id,)
        ).fetchall()
        for r in rows:
            try:
                self._row_state(r)
            except ValueError as e:
                failures.append(f"STATE_HASH:{r['observer_ref']}:{r['target_ref']}:{e}")
        return {"status": "PASS" if not failures else "FAIL", "failures": failures, "pairs": len(rows)}
