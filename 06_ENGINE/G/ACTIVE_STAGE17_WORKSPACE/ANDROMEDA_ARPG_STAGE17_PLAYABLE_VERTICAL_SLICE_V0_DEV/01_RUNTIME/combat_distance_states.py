from __future__ import annotations

import hashlib
import json
import math
from typing import Any


# ============================================================================
# ARPG_STAGE17_COMBAT_DISTANCE_STATE_MACHINE_NOT_CANON
#
# arpg_combat_core.py (ARPGCombatCore) ja calcula distancia real entre duas
# entidades (_distance(), via math.hypot dos iso_x_m/iso_y_m lidos do estado de
# movimento), mas so usa isso como UM gate binario (BASIC_RANGE_M=2.75,
# dentro/fora de alcance) - sem bandas, sem CLINCH/ECQ/IN_FIGHTING, sem
# deteccao de transicao de estado. Este arquivo fecha essa lacuna: 5 bandas de
# distancia, ancoradas exatamente no BASIC_RANGE_M ja real (vira o teto de
# IN_FIGHTING), com estado persistido por par de combatentes pra detectar
# mudanca de banda tick a tick.
#
# Recebe `movement` (um objeto concreto com .state(entity_ref) - um
# ContinuousMovementSystem ou o MultimodalMovementSystem deste mesmo pacote),
# NUNCA o "engine" inteiro que ARPGCombatCore usa - mantem isto testavel sem o
# zip MASTER_V2. NAO edita arpg_combat_core.py nem combat_system.py nesta fase;
# combat_modifiers_for_state() e o ponto de integracao documentado para o
# ARPGCombatCore consumir depois.
# ============================================================================


def _hash_payload(d: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


CLINCH = "CLINCH"
IN_FIGHTING = "IN_FIGHTING"
ECQ = "ECQ"
MID_RANGE = "MID_RANGE"
LONG_RANGE = "LONG_RANGE"

# ancorado no BASIC_RANGE_M=2.75 ja real em arpg_combat_core.py: IN_FIGHTING
# termina exatamente onde o gate de ataque corpo-a-corpo do engine hoje termina.
_BASIC_RANGE_M = 2.75

_BAND_CEILINGS = [
    (CLINCH, 1.0),          # agarrao/corpo colado
    (IN_FIGHTING, _BASIC_RANGE_M),  # = BASIC_RANGE_M do engine
    (ECQ, 6.0),             # ameaca iminente, logo alem do alcance corpo-a-corpo
    (MID_RANGE, 20.0),      # armas curtas/arremesso/pistolas
    # LONG_RANGE = qualquer coisa acima de 20.0
]

_MODIFIERS: dict[str, dict[str, Any]] = {
    CLINCH: {"melee_damage_mult": 1.15, "ranged_allowed": False, "grapple_allowed": True, "evasion_mult": 0.7},
    IN_FIGHTING: {"melee_damage_mult": 1.05, "ranged_damage_mult": 0.5, "grapple_allowed": False, "evasion_mult": 0.85},
    ECQ: {"melee_damage_mult": 0.9, "ranged_damage_mult": 0.75, "long_weapon_penalty_mult": 0.7, "evasion_mult": 1.0},
    MID_RANGE: {"melee_allowed": False, "ranged_damage_mult": 1.0, "evasion_mult": 1.1},
    LONG_RANGE: {"melee_allowed": False, "ranged_damage_mult": 1.0, "sniper_bonus_mult": 1.1, "evasion_mult": 1.15},
}


class CombatDistanceStateMachine:
    VERSION = "V0.1.0-PRE-GODOT"
    AUTHORITY = "ARPG_STAGE17_COMBAT_DISTANCE_STATE_MACHINE_NOT_CANON"

    def __init__(self, runtime: Any, world_instance_id: str, movement: Any) -> None:
        self.runtime = runtime
        self.world_instance_id = str(world_instance_id)
        self.movement = movement
        self._init_db()

    def _init_db(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                """CREATE TABLE IF NOT EXISTS v17_combat_distance_pairs(
                    world_instance_id TEXT NOT NULL, pair_ref TEXT NOT NULL,
                    actor_ref TEXT NOT NULL, target_ref TEXT NOT NULL,
                    state TEXT NOT NULL, distance_m REAL NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, pair_ref))"""
            )

    @staticmethod
    def _pair_ref(actor_ref: str, target_ref: str) -> str:
        return "|".join(sorted([str(actor_ref), str(target_ref)]))

    def distance(self, actor_ref: str, target_ref: str, *, include_altitude: bool = False) -> float:
        a = self.movement.state(actor_ref)
        b = self.movement.state(target_ref)
        dx = float(a["iso_x_m"]) - float(b["iso_x_m"])
        dy = float(a["iso_y_m"]) - float(b["iso_y_m"])
        if not include_altitude:
            return math.hypot(dx, dy)
        dz = float(a.get("altitude_m", 0.0)) - float(b.get("altitude_m", 0.0))
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    @staticmethod
    def classify(distance_m: float) -> str:
        for band, ceiling in _BAND_CEILINGS:
            if distance_m <= ceiling:
                return band
        return LONG_RANGE

    def _save(self, pair_ref: str, actor_ref: str, target_ref: str, state: str, distance_m: float) -> None:
        payload = {"pair_ref": pair_ref, "actor_ref": actor_ref, "target_ref": target_ref, "state": state, "distance_m": distance_m}
        h = _hash_payload(payload)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT OR REPLACE INTO v17_combat_distance_pairs VALUES(?,?,?,?,?,?,?)",
                (self.world_instance_id, pair_ref, actor_ref, target_ref, state, distance_m, h),
            )

    def _row_state(self, r: Any) -> dict[str, Any]:
        d = {"pair_ref": r["pair_ref"], "actor_ref": r["actor_ref"], "target_ref": r["target_ref"],
             "state": r["state"], "distance_m": float(r["distance_m"])}
        if _hash_payload(d) != r["payload_hash"]:
            raise ValueError("combat distance pair state hash mismatch")
        return d

    def update(self, actor_ref: str, target_ref: str, *, include_altitude: bool = False) -> dict[str, Any]:
        pair_ref = self._pair_ref(actor_ref, target_ref)
        dist = self.distance(actor_ref, target_ref, include_altitude=include_altitude)
        to_state = self.classify(dist)
        row = self.runtime.conn.execute(
            "SELECT * FROM v17_combat_distance_pairs WHERE world_instance_id=? AND pair_ref=?",
            (self.world_instance_id, pair_ref),
        ).fetchone()
        from_state = None
        if row:
            prev = self._row_state(row)
            from_state = prev["state"]
        self._save(pair_ref, actor_ref, target_ref, to_state, dist)
        return {"status": "PASS", "pair_ref": pair_ref, "actor_ref": actor_ref, "target_ref": target_ref,
                "distance_m": round(dist, 6), "from_state": from_state, "to_state": to_state,
                "changed": from_state != to_state, "authority": self.AUTHORITY}

    def state_for_pair(self, actor_ref: str, target_ref: str) -> dict[str, Any]:
        pair_ref = self._pair_ref(actor_ref, target_ref)
        row = self.runtime.conn.execute(
            "SELECT * FROM v17_combat_distance_pairs WHERE world_instance_id=? AND pair_ref=?",
            (self.world_instance_id, pair_ref),
        ).fetchone()
        if not row:
            raise KeyError(pair_ref)
        return {**self._row_state(row), "authority": self.AUTHORITY}

    @staticmethod
    def combat_modifiers_for_state(state: str) -> dict[str, Any]:
        if state not in _MODIFIERS:
            raise KeyError(f"unknown combat distance state: {state}")
        return dict(_MODIFIERS[state])

    def distance_modifiers_for_pair(self, actor_ref: str, target_ref: str, *, include_altitude: bool = False) -> dict[str, Any]:
        """Ponto de plugue real pra arpg_combat_core.py (achado da auditoria de
        13/09): ARPGCombatCore ja busca modificadores de OUTROS subsistemas via
        self.engine.skills_arpg(...).combat_modifiers(profile_ref) e
        self.engine.items_arpg(...).equipment_modifiers(profile_ref), sempre no
        formato {"modifiers": {...}}. Este metodo devolve o MESMO formato, pra
        que quando o objeto `engine` (IntegratedARPGEngineV16A ou sucessor) for
        estendido com um accessor tipo `distance_states_arpg(...)`, o encaixe
        seja direto - sem precisar editar arpg_combat_core.py (arquivo
        protegido, so leitura/composicao). Nao registra esse accessor aqui -
        isso pertence ao arquivo do engine, fora do escopo desta integracao."""
        result = self.update(actor_ref, target_ref, include_altitude=include_altitude)
        return {
            "modifiers": self.combat_modifiers_for_state(result["to_state"]),
            "state": result["to_state"],
            "distance_m": result["distance_m"],
            "authority": self.AUTHORITY,
        }

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        rows = self.runtime.conn.execute(
            "SELECT * FROM v17_combat_distance_pairs WHERE world_instance_id=?", (self.world_instance_id,)
        ).fetchall()
        for r in rows:
            try:
                d = self._row_state(r)
            except ValueError as e:
                failures.append(f"PAIR_HASH:{r['pair_ref']}:{e}")
                continue
            if self.classify(d["distance_m"]) != d["state"]:
                failures.append(f"STATE_MISMATCH:{r['pair_ref']}")
        return {"status": "PASS" if not failures else "FAIL", "failures": failures, "pairs": len(rows)}
