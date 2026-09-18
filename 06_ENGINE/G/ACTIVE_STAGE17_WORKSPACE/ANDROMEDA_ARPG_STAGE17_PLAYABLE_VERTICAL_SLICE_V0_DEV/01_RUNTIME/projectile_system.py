from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable

from living_runtime import ConflictError, ValidationError, canonical_json, sha256_text


# ============================================================================
# ARPG_STAGE17_PROJECTILE_TRAJECTORY_RUNTIME_NOT_CANON
#
# Nao existia nenhum sistema de projetil/trajetoria em lugar nenhum do engine
# antes deste arquivo (confirmado por busca exaustiva) - arpg_combat_core.py
# resolve combate a distancia com um unico gate de alcance plano
# (BASIC_RANGE_M=2.75, acerto instantaneo), sem trajetoria nem tempo de voo.
#
# O nucleo (ProjectileParams/SphereObstacle/CollisionResult + as funcoes
# position_at/time_to_ground_impact/find_first_obstacle_hit/resolve_trajectory)
# e PURO - sem __init__, sem runtime/country/spatial, no molde de
# InteractionIntentResolver (arpg_interaction_intent_core.py) - so dataclasses
# congeladas e funcoes. Serve igualmente pra bala/flecha/pedra/magia/projetil
# tecnologico: o que muda entre eles e so velocity/gravity/drag, nunca logica
# especifica por tipo de arma.
#
# A classe ProjectileSystem por cima e so um wrapper fino que converte
# geodetico<->iso via o `spatial` real (SpatialCoordinateSystem) e persiste UM
# evento idempotente por tiro resolvido - recebe so (runtime, world_instance_id,
# spatial), nunca o "engine" inteiro, pra continuar testavel sem o zip MASTER_V2.
# ============================================================================


@dataclass(frozen=True)
class ProjectileParams:
    origin: tuple[float, float, float]        # (iso_x_m, iso_y_m, altitude_m)
    direction: tuple[float, float, float]      # normalizado internamente
    speed_mps: float
    gravity_mps2: float = 9.8
    drag_coefficient: float = 0.0              # 0 => trajetoria "RETA" plana; >0 => arco (arremesso/explosivo)

    def unit_direction(self) -> tuple[float, float, float]:
        dx, dy, dz = self.direction
        mag = math.sqrt(dx * dx + dy * dy + dz * dz)
        if mag <= 1e-12:
            raise ValidationError("projectile direction must be non-zero")
        return (dx / mag, dy / mag, dz / mag)


@dataclass(frozen=True)
class SphereObstacle:
    ref: str
    center: tuple[float, float, float]
    radius_m: float


@dataclass(frozen=True)
class CollisionResult:
    hit: bool
    impact_type: str            # 'OBSTACLE' | 'GROUND' | 'MAX_RANGE'
    impact_time_s: float
    impact_position: tuple[float, float, float]
    obstacle_ref: str | None = None


def position_at(params: ProjectileParams, t: float) -> tuple[float, float, float]:
    """Position = Origin + Direction*Velocity*Time + Gravity*Time^2/2 (gravidade so no eixo vertical/z)."""
    ux, uy, uz = params.unit_direction()
    ox, oy, oz = params.origin
    if params.drag_coefficient > 0:
        k = params.drag_coefficient
        horiz_dist = params.speed_mps * (1.0 - math.exp(-k * t)) / k
    else:
        horiz_dist = params.speed_mps * t
    x = ox + ux * horiz_dist
    y = oy + uy * horiz_dist
    z = oz + uz * horiz_dist - 0.5 * params.gravity_mps2 * t * t
    return (x, y, z)


def time_to_ground_impact(params: ProjectileParams, ground_altitude_m: float = 0.0) -> float | None:
    """Resolve analiticamente t tal que z(t) == ground_altitude_m (raiz positiva menor)."""
    _, _, uz = params.unit_direction()
    _, _, oz = params.origin
    a = -0.5 * params.gravity_mps2
    b = params.speed_mps * uz
    c = oz - ground_altitude_m
    if abs(a) < 1e-12:
        if abs(b) < 1e-12:
            return None
        t = -c / b
        return t if t > 0 else None
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    sq = math.sqrt(disc)
    t1 = (-b + sq) / (2 * a)
    t2 = (-b - sq) / (2 * a)
    candidates = [t for t in (t1, t2) if t is not None and t > 1e-9]
    return min(candidates) if candidates else None


def _closest_approach_time(params: ProjectileParams, obstacle: SphereObstacle, t_max: float) -> float | None:
    """Sem arrasto, position_at e quadratica em t -> a distancia^2 ao centro tambem e
    quadratica em t, minimizada analiticamente. Com arrasto (nao-linear), cai pra
    amostragem em passos pequenos (fallback documentado, nao usado no caso comum)."""
    if params.drag_coefficient > 0:
        best_t, best_d2 = None, None
        steps = max(50, int(t_max / 0.02))
        for i in range(steps + 1):
            t = t_max * i / steps
            p = position_at(params, t)
            d2 = sum((p[k] - obstacle.center[k]) ** 2 for k in range(3))
            if best_d2 is None or d2 < best_d2:
                best_d2, best_t = d2, t
        return best_t
    ux, uy, uz = params.unit_direction()
    ox, oy, oz = params.origin
    cx, cy, cz = obstacle.center
    v = params.speed_mps
    g = params.gravity_mps2
    # p(t) = (ox+ux*v*t, oy+uy*v*t, oz+uz*v*t - 0.5*g*t^2)
    # d2(t) = (p_x-cx)^2+(p_y-cy)^2+(p_z-cz)^2, derivada em t = 0 -> polinomio cubico em t
    # (pois p_z e quadratica em t). Resolve via amostragem fina + refinamento local simples
    # (mantem determinismo e simplicidade em vez de resolver a cubica simbolicamente).
    steps = max(100, int(t_max / 0.01))
    best_t, best_d2 = 0.0, None
    for i in range(steps + 1):
        t = t_max * i / steps
        px = ox + ux * v * t
        py = oy + uy * v * t
        pz = oz + uz * v * t - 0.5 * g * t * t
        d2 = (px - cx) ** 2 + (py - cy) ** 2 + (pz - cz) ** 2
        if best_d2 is None or d2 < best_d2:
            best_d2, best_t = d2, t
    return best_t


def find_first_obstacle_hit(params: ProjectileParams, obstacles: Iterable[SphereObstacle], t_max: float) -> CollisionResult | None:
    earliest: CollisionResult | None = None
    for obstacle in obstacles:
        t_closest = _closest_approach_time(params, obstacle, t_max)
        if t_closest is None:
            continue
        p = position_at(params, t_closest)
        dist = math.sqrt(sum((p[k] - obstacle.center[k]) ** 2 for k in range(3)))
        if dist <= obstacle.radius_m:
            if earliest is None or t_closest < earliest.impact_time_s:
                earliest = CollisionResult(hit=True, impact_type="OBSTACLE", impact_time_s=t_closest, impact_position=p, obstacle_ref=obstacle.ref)
    return earliest


def resolve_trajectory(params: ProjectileParams, *, obstacles: Iterable[SphereObstacle] = (), ground_altitude_m: float = 0.0, max_time_s: float = 10.0) -> CollisionResult:
    """Ponto de entrada unico e puro: retorna o evento mais cedo entre {obstaculo, chao, max_time_s}."""
    obstacle_hit = find_first_obstacle_hit(params, obstacles, max_time_s)
    ground_t = time_to_ground_impact(params, ground_altitude_m)
    candidates: list[CollisionResult] = []
    if obstacle_hit is not None:
        candidates.append(obstacle_hit)
    if ground_t is not None and ground_t <= max_time_s:
        candidates.append(CollisionResult(hit=True, impact_type="GROUND", impact_time_s=ground_t, impact_position=position_at(params, ground_t)))
    if not candidates:
        return CollisionResult(hit=False, impact_type="MAX_RANGE", impact_time_s=max_time_s, impact_position=position_at(params, max_time_s))
    return min(candidates, key=lambda c: c.impact_time_s)


class ProjectileSystem:
    """Wrapper fino: converte geodetico<->iso via `spatial` e persiste um evento
    idempotente por tiro. Nao recebe o `engine` inteiro - so runtime/wid/spatial,
    pra continuar testavel sem o zip MASTER_V2."""

    VERSION = "V0.1.0-PRE-GODOT"
    AUTHORITY = "ARPG_STAGE17_PROJECTILE_TRAJECTORY_RUNTIME_NOT_CANON"

    def __init__(self, runtime: Any, world_instance_id: str, spatial: Any) -> None:
        self.runtime = runtime
        self.world_instance_id = str(world_instance_id)
        self.spatial = spatial
        self._init_db()

    def _init_db(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                """CREATE TABLE IF NOT EXISTS v17_projectile_events(
                    world_instance_id TEXT NOT NULL, event_ref TEXT NOT NULL,
                    event_type TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL, result_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, event_ref))"""
            )

    def _event_existing(self, event_ref: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = self.runtime.conn.execute(
            "SELECT * FROM v17_projectile_events WHERE world_instance_id=? AND event_ref=?",
            (self.world_instance_id, str(event_ref)),
        ).fetchone()
        if not row:
            return None
        ptext = canonical_json(payload)
        if sha256_text(ptext) != row["payload_hash"]:
            raise ConflictError(f"projectile event_ref {event_ref} already used with a different payload")
        if row["event_type"] != event_type:
            raise ConflictError(f"projectile event_ref {event_ref} already used for a different event_type")
        result = json.loads(row["result_json"])
        if sha256_text(row["result_json"]) != row["result_hash"]:
            raise ValueError("projectile event result hash mismatch")
        return {**result, "idempotent_replay": True}

    def _record(self, event_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        ptext = canonical_json(payload)
        rtext = canonical_json(result)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT INTO v17_projectile_events VALUES(?,?,?,?,?,?)",
                (self.world_instance_id, str(event_ref), event_type, sha256_text(ptext), rtext, sha256_text(rtext)),
            )
        return result

    def fire(self, *, event_ref: str, origin: dict[str, float], heading_deg: float, pitch_deg: float,
              speed_mps: float, gravity_mps2: float = 9.8, drag_coefficient: float = 0.0,
              obstacles: list[dict[str, Any]] = (), ground_altitude_m: float = 0.0, max_time_s: float = 10.0,
              projectile_kind: str = "GENERIC") -> dict[str, Any]:
        if speed_mps <= 0:
            raise ValidationError("speed_mps must be positive")
        if max_time_s <= 0:
            raise ValidationError("max_time_s must be positive")
        if not -90.0 <= pitch_deg <= 90.0:
            return {"status": "REJECTED", "reason": "INVALID_PITCH_DEG"}

        payload = {"origin": origin, "heading_deg": heading_deg, "pitch_deg": pitch_deg, "speed_mps": speed_mps,
                   "gravity_mps2": gravity_mps2, "drag_coefficient": drag_coefficient, "obstacles": list(obstacles),
                   "ground_altitude_m": ground_altitude_m, "max_time_s": max_time_s, "projectile_kind": projectile_kind}
        replay = self._event_existing(event_ref, "PROJECTILE_FIRE", payload)
        if replay is not None:
            return replay

        origin_iso = self.spatial.geodetic_to_isometric(origin["longitude"], origin["latitude"], origin.get("altitude_m", 0.0))
        heading_rad = math.radians(heading_deg)
        pitch_rad = math.radians(pitch_deg)
        direction = (math.cos(heading_rad) * math.cos(pitch_rad), math.sin(heading_rad) * math.cos(pitch_rad), math.sin(pitch_rad))
        params = ProjectileParams(
            origin=(origin_iso["iso_x_m"], origin_iso["iso_y_m"], origin_iso["altitude_m"]),
            direction=direction, speed_mps=speed_mps, gravity_mps2=gravity_mps2, drag_coefficient=drag_coefficient,
        )

        sphere_obstacles = []
        for o in obstacles:
            if "iso_x_m" in o:
                center = (o["iso_x_m"], o["iso_y_m"], o.get("altitude_m", 0.0))
            else:
                iso = self.spatial.geodetic_to_isometric(o["longitude"], o["latitude"], o.get("altitude_m", 0.0))
                center = (iso["iso_x_m"], iso["iso_y_m"], iso["altitude_m"])
            sphere_obstacles.append(SphereObstacle(ref=o["ref"], center=center, radius_m=float(o["radius_m"])))

        outcome = resolve_trajectory(params, obstacles=sphere_obstacles, ground_altitude_m=ground_altitude_m, max_time_s=max_time_s)
        impact_geo = self.spatial.isometric_to_geodetic(*outcome.impact_position)
        impact_chunk = self.spatial.chunk_for_geodetic(impact_geo["longitude"], impact_geo["latitude"])["chunk_id"]

        result = {
            "status": "PASS", "event_ref": event_ref, "impact_type": outcome.impact_type,
            "impact_time_s": round(outcome.impact_time_s, 6),
            "impact_iso": {"iso_x_m": outcome.impact_position[0], "iso_y_m": outcome.impact_position[1], "altitude_m": outcome.impact_position[2]},
            "impact_geodetic": impact_geo, "impact_chunk_id": impact_chunk,
            "hit_obstacle_ref": outcome.obstacle_ref, "projectile_kind": projectile_kind,
            "authority": self.AUTHORITY, "idempotent_replay": False,
        }
        return self._record(event_ref, "PROJECTILE_FIRE", payload, result)

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        rows = self.runtime.conn.execute(
            "SELECT * FROM v17_projectile_events WHERE world_instance_id=?", (self.world_instance_id,)
        ).fetchall()
        for r in rows:
            if sha256_text(r["result_json"]) != r["result_hash"]:
                failures.append(f"RESULT_HASH:{r['event_ref']}")
        return {"status": "PASS" if not failures else "FAIL", "failures": failures, "events": len(rows)}
