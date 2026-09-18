from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from living_runtime import ConflictError, canonical_json, sha256_text

# ============================================================================
# ARPG_STAGE17_ROOT_CORRUPTION_RUNTIME_NOT_CANON
#
# Fase 6 (auditoria de 13/09, secao G do relatorio): Raiz Profunda ate agora
# so existia como CONTEUDO (STELLAR_ROOT_CORRUPTION_GATE_DEV_V1_0.json,
# MASTER_RAIZ_PROFUNDA_CATALOG_V2_0_0.json, STELLAR_CORRUPTED_RESOURCES) -
# nenhum sistema de runtime simulava expansao territorial, risco de
# corrupcao/morte ou transicao de fase como algo que evolui, so estado fixo
# declarado em JSON. Este arquivo fecha essa lacuna, autocontido (nunca edita
# os 4 arquivos protegidos nem country_scale.py), mesmo molde de idempotencia
# por event_ref + hash de estado ja usado em vehicle_movement.py /
# construction_placement_system.py.
#
# Regras vindas DIRETO do portao autoral (nao inventadas aqui):
# - As 6 fases de STELLAR_ROOT_PROGRESSION_LAW: IMPLANTACAO -> ENRAIZAMENTO ->
#   ALIMENTACAO_SILENCIOSA -> CORRUPCAO -> EMERGENCIA -> COLHEITA. So avanca
#   um passo por vez (nunca pula fase sem portao). Fase inicial seedada do
#   gate: ALIMENTACAO_SILENCIOSA_PARA_CORRUPCAO (entre fase 3 e 4).
# - NO_ROOT_PHASE_BEYOND_ALIMENTACAO_CORRUPCAO_WITHOUT_NEW_GATE: avancar pra
#   EMERGENCIA/COLHEITA exige gate_override=True (representa um novo portao
#   autoral futuro - este sistema nunca decide isso sozinho).
# - containment_principle: nenhum territorio pode ter mais da metade de suas
#   subregioes corrompidas, EXCETO TER-012 (Zona de Contencao, excecao
#   proposital do proprio gate). O total de subregioes por territorio e
#   gerado proceduralmente em country_scale.py (1-3 por bloco) - este sistema
#   NAO reimplementa isso, quem chama informa total_subregions_in_territory
#   (lido do CountryScaleSystem real).
# - NO_TERRITORY_FULLY_CORRUPTED: incondicional, nem TER-012 pode chegar a
#   100% corrompido.
# ============================================================================

AUTHORITY = "ARPG_STAGE17_ROOT_CORRUPTION_RUNTIME_NOT_CANON"
VERSION = "V0.1.0-PRE-GODOT"

PHASES = [
    "IMPLANTACAO",
    "ENRAIZAMENTO",
    "ALIMENTACAO_SILENCIOSA",
    "CORRUPCAO",
    "EMERGENCIA",
    "COLHEITA",
]
_SEED_PHASE = "ALIMENTACAO_SILENCIOSA"  # ALIMENTACAO_SILENCIOSA_PARA_CORRUPCAO do gate = index 2
_CONTAINMENT_EXCEPTION_TERRITORY = "TER-012"

_INTENSITIES = ("BAIXA", "MEDIA", "ALTA")

# risco por intensidade: banda de roll [0,1) -> resultado. Roll e fornecido
# por quem chama (sem RNG proprio aqui, mesmo principio de nao duplicar fonte
# de aleatoriedade ja usada em country_scale.py/_rng).
_RISK_BANDS = {
    "BAIXA": (0.85, 0.98),   # < 0.85 SAFE, 0.85-0.98 CORRUPTION_RISK, >=0.98 DEATH_RISK
    "MEDIA": (0.65, 0.92),
    "ALTA": (0.40, 0.80),
}


def _hash_state(d: dict[str, Any]) -> str:
    return sha256_text(canonical_json(d))


def risk_outcome(intensity: str, roll: float) -> str:
    intensity = str(intensity).upper()
    if intensity not in _RISK_BANDS:
        raise ValueError(f"unknown intensity {intensity!r} (expected one of {_INTENSITIES})")
    if not 0.0 <= roll < 1.0:
        raise ValueError("roll must be in [0.0, 1.0)")
    safe_ceiling, corruption_ceiling = _RISK_BANDS[intensity]
    if roll < safe_ceiling:
        return "SAFE"
    if roll < corruption_ceiling:
        return "CORRUPTION_RISK"
    return "DEATH_RISK"


class RootCorruptionSystem:
    """Sistema de runtime pra Raiz Profunda (Special Ecosystem): expansao
    territorial de subregioes corrompidas, transicao de fase do portao
    autoral, e risco de corrupcao/morte por intensidade. Le a semente real do
    STELLAR_ROOT_CORRUPTION_GATE_DEV_V1_0.json na primeira inicializacao de
    cada mundo (nao reimporta se o mundo ja tem estado salvo)."""

    VERSION = VERSION
    AUTHORITY = AUTHORITY
    PHASES = PHASES

    def __init__(self, runtime: Any, world_instance_id: str, content_root: str | Path | None = None) -> None:
        self.runtime = runtime
        self.world_instance_id = str(world_instance_id)
        self.content_root = Path(content_root) if content_root else self._default_content_root()
        self._init_db()
        self._seed_from_gate_if_empty()

    @staticmethod
    def _default_content_root() -> Path:
        # 01_RUNTIME -> ...WORKSPACE_DEV -> ACTIVE_STAGE17_WORKSPACE -> G ->
        # 06_ENGINE -> ANDROMEDA_CODEX_CLEAN (raiz do projeto, onde 01_LORE mora)
        return Path(__file__).resolve().parents[5]

    def _gate_path(self) -> Path:
        return (self.content_root / "01_LORE" / "CANON_DERIVADO_ATIVO" / "CORRUPCAO" /
                "STELLAR_ROOT_CORRUPTION_GATE_DEV_V1_0.json")

    def _load_gate(self) -> dict[str, Any]:
        path = self._gate_path()
        if not path.is_file():
            raise FileNotFoundError(
                f"RootCorruptionSystem: portao autoral nao encontrado em {path} - "
                "passe content_root explicito apontando pra raiz do projeto (ANDROMEDA_CODEX_CLEAN)."
            )
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _init_db(self) -> None:
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                """CREATE TABLE IF NOT EXISTS v17_root_corruption_subregions(
                    world_instance_id TEXT NOT NULL, subregion_ref TEXT NOT NULL,
                    territory_ref TEXT NOT NULL, intensity TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, subregion_ref))"""
            )
            self.runtime.conn.execute(
                """CREATE TABLE IF NOT EXISTS v17_root_corruption_phase(
                    world_instance_id TEXT NOT NULL PRIMARY KEY,
                    phase TEXT NOT NULL, payload_hash TEXT NOT NULL)"""
            )
            self.runtime.conn.execute(
                """CREATE TABLE IF NOT EXISTS v17_root_corruption_events(
                    world_instance_id TEXT NOT NULL, event_ref TEXT NOT NULL,
                    event_type TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL, result_hash TEXT NOT NULL,
                    PRIMARY KEY(world_instance_id, event_ref))"""
            )

    def _seed_from_gate_if_empty(self) -> None:
        row = self.runtime.conn.execute(
            "SELECT 1 FROM v17_root_corruption_phase WHERE world_instance_id=?",
            (self.world_instance_id,),
        ).fetchone()
        if row:
            return  # mundo ja tem estado proprio, nunca sobrescreve com a semente
        gate = self._load_gate()
        with self.runtime._write_lock:
            phase_h = _hash_state({"phase": _SEED_PHASE})
            self.runtime.conn.execute(
                "INSERT INTO v17_root_corruption_phase VALUES(?,?,?)",
                (self.world_instance_id, _SEED_PHASE, phase_h),
            )
            for entry in gate.get("corrupted_subregions", []):
                d = {"subregion_ref": entry["subregion_id"], "territory_ref": entry["territory_id"],
                     "intensity": str(entry["intensity"]).upper()}
                h = _hash_state(d)
                self.runtime.conn.execute(
                    "INSERT OR IGNORE INTO v17_root_corruption_subregions VALUES(?,?,?,?,?)",
                    (self.world_instance_id, d["subregion_ref"], d["territory_ref"], d["intensity"], h),
                )

    # ---------- idempotencia (mesmo padrao dos demais modulos Stage17) ----------

    def _event_existing(self, event_ref: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        row = self.runtime.conn.execute(
            "SELECT * FROM v17_root_corruption_events WHERE world_instance_id=? AND event_ref=?",
            (self.world_instance_id, str(event_ref)),
        ).fetchone()
        if not row:
            return None
        if sha256_text(canonical_json(payload)) != row["payload_hash"]:
            raise ConflictError(f"root corruption event_ref {event_ref} already used with a different payload")
        if row["event_type"] != event_type:
            raise ConflictError(f"root corruption event_ref {event_ref} already used for a different event_type")
        result = json.loads(row["result_json"])
        if sha256_text(row["result_json"]) != row["result_hash"]:
            raise ValueError("root corruption event result hash mismatch")
        return {**result, "idempotent_replay": True}

    def _record_event(self, event_ref: str, event_type: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        ptext = canonical_json(payload)
        rtext = canonical_json(result)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT INTO v17_root_corruption_events VALUES(?,?,?,?,?,?)",
                (self.world_instance_id, str(event_ref), event_type, sha256_text(ptext), rtext, sha256_text(rtext)),
            )
        return result

    # ---------- leitura de estado (hash-verificada) ----------

    def _subregion_row_state(self, r: Any) -> dict[str, Any]:
        d = {"subregion_ref": r["subregion_ref"], "territory_ref": r["territory_ref"], "intensity": r["intensity"]}
        if _hash_state(d) != r["payload_hash"]:
            raise ValueError("root corruption subregion state hash mismatch")
        return d

    def corrupted_subregions(self, territory_ref: str | None = None) -> list[dict[str, Any]]:
        if territory_ref is None:
            rows = self.runtime.conn.execute(
                "SELECT * FROM v17_root_corruption_subregions WHERE world_instance_id=?",
                (self.world_instance_id,),
            ).fetchall()
        else:
            rows = self.runtime.conn.execute(
                "SELECT * FROM v17_root_corruption_subregions WHERE world_instance_id=? AND territory_ref=?",
                (self.world_instance_id, str(territory_ref)),
            ).fetchall()
        return [self._subregion_row_state(r) for r in rows]

    def current_phase(self) -> str:
        row = self.runtime.conn.execute(
            "SELECT * FROM v17_root_corruption_phase WHERE world_instance_id=?",
            (self.world_instance_id,),
        ).fetchone()
        d = {"phase": row["phase"]}
        if _hash_state(d) != row["payload_hash"]:
            raise ValueError("root corruption phase state hash mismatch")
        return row["phase"]

    # ---------- comandos ----------

    def corrupt_subregion(self, subregion_ref: str, territory_ref: str, *, intensity: str,
                           total_subregions_in_territory: int, event_ref: str) -> dict[str, Any]:
        """Expande a corrupcao pra uma nova subregiao. `total_subregions_in_territory`
        vem de quem chama (CountryScaleSystem real) - este sistema nao gera
        contagem de subregiao propria, so aplica a regra de contencao sobre o
        numero real."""
        intensity = str(intensity).upper()
        payload = {"subregion_ref": subregion_ref, "territory_ref": territory_ref, "intensity": intensity,
                   "total_subregions_in_territory": total_subregions_in_territory}
        replay = self._event_existing(event_ref, "SUBREGION_CORRUPTED", payload)
        if replay is not None:
            return replay

        if intensity not in _INTENSITIES:
            result = {"status": "REJECTED", "reason": "UNKNOWN_INTENSITY", "intensity": intensity}
            return self._record_event(event_ref, "SUBREGION_CORRUPTED", payload, result)

        existing = self.runtime.conn.execute(
            "SELECT 1 FROM v17_root_corruption_subregions WHERE world_instance_id=? AND subregion_ref=?",
            (self.world_instance_id, str(subregion_ref)),
        ).fetchone()
        if existing:
            result = {"status": "REJECTED", "reason": "SUBREGION_ALREADY_CORRUPTED", "subregion_ref": subregion_ref}
            return self._record_event(event_ref, "SUBREGION_CORRUPTED", payload, result)

        current_count = len(self.corrupted_subregions(territory_ref))
        projected_count = current_count + 1

        if total_subregions_in_territory <= 0:
            result = {"status": "REJECTED", "reason": "INVALID_TERRITORY_SUBREGION_TOTAL"}
            return self._record_event(event_ref, "SUBREGION_CORRUPTED", payload, result)

        if projected_count >= total_subregions_in_territory:
            # NO_TERRITORY_FULLY_CORRUPTED - incondicional, nem TER-012 escapa.
            result = {"status": "REJECTED", "reason": "NO_TERRITORY_FULLY_CORRUPTED", "territory_ref": territory_ref}
            return self._record_event(event_ref, "SUBREGION_CORRUPTED", payload, result)

        if territory_ref != _CONTAINMENT_EXCEPTION_TERRITORY:
            if projected_count / total_subregions_in_territory > 0.5:
                result = {"status": "REJECTED", "reason": "CONTAINMENT_PRINCIPLE_EXCEEDED",
                          "territory_ref": territory_ref, "projected_ratio": round(projected_count / total_subregions_in_territory, 4)}
                return self._record_event(event_ref, "SUBREGION_CORRUPTED", payload, result)

        d = {"subregion_ref": subregion_ref, "territory_ref": territory_ref, "intensity": intensity}
        h = _hash_state(d)
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "INSERT INTO v17_root_corruption_subregions VALUES(?,?,?,?,?)",
                (self.world_instance_id, subregion_ref, territory_ref, intensity, h),
            )
        result = {"status": "PASS", "event_ref": event_ref, **d,
                  "territory_corrupted_count": projected_count, "authority": self.AUTHORITY,
                  "idempotent_replay": False}
        return self._record_event(event_ref, "SUBREGION_CORRUPTED", payload, result)

    def advance_phase(self, *, requested_phase: str, gate_override: bool = False, event_ref: str) -> dict[str, Any]:
        """Avanca exatamente 1 passo na progressao de 6 fases. Passar de
        CORRUPCAO pra EMERGENCIA/COLHEITA exige gate_override=True (representa
        um novo portao autoral - este sistema nunca decide isso sozinho)."""
        requested_phase = str(requested_phase).upper()
        payload = {"requested_phase": requested_phase, "gate_override": gate_override}
        replay = self._event_existing(event_ref, "PHASE_ADVANCED", payload)
        if replay is not None:
            return replay

        current = self.current_phase()
        if requested_phase not in PHASES:
            result = {"status": "REJECTED", "reason": "UNKNOWN_PHASE", "requested_phase": requested_phase}
            return self._record_event(event_ref, "PHASE_ADVANCED", payload, result)

        current_idx = PHASES.index(current)
        requested_idx = PHASES.index(requested_phase)
        if requested_idx != current_idx + 1:
            result = {"status": "REJECTED", "reason": "PHASE_MUST_ADVANCE_ONE_STEP_AT_A_TIME",
                      "current_phase": current, "requested_phase": requested_phase}
            return self._record_event(event_ref, "PHASE_ADVANCED", payload, result)

        if current == "CORRUPCAO" and not gate_override:
            result = {"status": "REJECTED", "reason": "NO_ROOT_PHASE_BEYOND_ALIMENTACAO_CORRUPCAO_WITHOUT_NEW_GATE",
                      "current_phase": current}
            return self._record_event(event_ref, "PHASE_ADVANCED", payload, result)

        h = _hash_state({"phase": requested_phase})
        with self.runtime._write_lock:
            self.runtime.conn.execute(
                "UPDATE v17_root_corruption_phase SET phase=?, payload_hash=? WHERE world_instance_id=?",
                (requested_phase, h, self.world_instance_id),
            )
        result = {"status": "PASS", "event_ref": event_ref, "previous_phase": current, "phase": requested_phase,
                  "authority": self.AUTHORITY, "idempotent_replay": False}
        return self._record_event(event_ref, "PHASE_ADVANCED", payload, result)

    def corruption_risk_roll(self, actor_ref: str, subregion_ref: str, *, roll: float, event_ref: str) -> dict[str, Any]:
        """`roll` e fornecido por quem chama (sem RNG proprio aqui - mesmo
        principio de composicao usado em todo o resto do Stage17: este
        sistema decide o resultado, nunca a fonte de aleatoriedade)."""
        payload = {"actor_ref": actor_ref, "subregion_ref": subregion_ref, "roll": roll}
        replay = self._event_existing(event_ref, "CORRUPTION_RISK_ROLLED", payload)
        if replay is not None:
            return replay

        rows = [r for r in self.corrupted_subregions() if r["subregion_ref"] == subregion_ref]
        if not rows:
            result = {"status": "REJECTED", "reason": "SUBREGION_NOT_CORRUPTED", "subregion_ref": subregion_ref}
            return self._record_event(event_ref, "CORRUPTION_RISK_ROLLED", payload, result)

        intensity = rows[0]["intensity"]
        outcome = risk_outcome(intensity, roll)
        result = {"status": "PASS", "event_ref": event_ref, "actor_ref": actor_ref, "subregion_ref": subregion_ref,
                  "intensity": intensity, "outcome": outcome, "authority": self.AUTHORITY, "idempotent_replay": False}
        return self._record_event(event_ref, "CORRUPTION_RISK_ROLLED", payload, result)

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        rows = self.runtime.conn.execute(
            "SELECT * FROM v17_root_corruption_subregions WHERE world_instance_id=?", (self.world_instance_id,)
        ).fetchall()
        for r in rows:
            try:
                self._subregion_row_state(r)
            except ValueError as e:
                failures.append(f"SUBREGION_HASH:{r['subregion_ref']}:{e}")
        try:
            self.current_phase()
        except ValueError as e:
            failures.append(f"PHASE_HASH:{e}")
        return {"status": "PASS" if not failures else "FAIL", "failures": failures, "subregions": len(rows)}
