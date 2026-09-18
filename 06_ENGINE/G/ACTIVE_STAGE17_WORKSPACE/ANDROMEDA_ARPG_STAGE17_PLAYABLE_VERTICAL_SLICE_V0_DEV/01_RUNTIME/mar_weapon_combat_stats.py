from __future__ import annotations

import glob
import json
import re
from pathlib import Path
from typing import Any

# ============================================================================
# ARPG_STAGE17_MAR_WEAPON_CONCRETE_COMBAT_STATS_NOT_CANON
#
# Achado da auditoria de 13/09 (fase 5, vertical slice): as 96 armas do MAR ja
# tem stats ABSTRATOS 0-100 (power/handling/reach/etc, em 04_MECANICAS/
# ITENS_E_ARMAS/*.json), mas nenhum sistema do runtime de combate produz um
# numero CONCRETO de jogo (dano em HP, cadencia/min, capacidade de pente, modo
# de tiro) a partir deles - ARPGCombatCore (protegido, nunca editado aqui) so
# resolve ataque/defesa/distancia, sem saber "quanto" uma arma especifica causa.
#
# Este arquivo fecha essa lacuna como leitura pura de conteudo (sem SQLite, sem
# dependencia do zip MASTER_V2 - o conteudo MAR ja e JSON de projeto, nao
# canone selado) + uma formula deterministica por familia/funcao, mesmo
# principio ja usado (e testado contra colisao) no gerador do Codice desta
# sessao: os insumos (stats abstratos + tier) ja variam por arma, entao a
# formula nunca precisa de numero escolhido a mao por item.
#
# NAO edita arpg_combat_core.py nem mar_balance.py (sistema DIFERENTE - opera
# sobre as 30 armas canonicas legadas via zip MASTER_V2, nao sobre as 96 armas
# MAR de conteudo). O ponto de integracao com ARPGCombatCore e o mesmo padrao
# ja usado por combat_distance_states.py#distance_modifiers_for_pair: um
# accessor pronto pra um `engine.mar_weapons_arpg(...)` futuro consumir, sem
# exigir edicao do core agora.
# ============================================================================

AUTHORITY = "ARPG_STAGE17_MAR_WEAPON_CONCRETE_COMBAT_STATS_NOT_CANON"
VERSION = "V0.1.0-PRE-GODOT"

_WEAPON_ID_RE = re.compile(r"^WPN-([A-Z]+)-")

_TIER_INDEX = {
    "R0": 0, "R1": 1, "R2": 2, "R3": 3, "T0": 0, "T1": 1, "T2": 2, "T3": 3,
    "BAIXO": 0, "MÉDIO": 2, "MEDIO": 2, "ALTO": 3,
}

# Sufixo funcional pras 2 familias mistas (TEC/MAG) - mesma classificacao ja
# usada no Codice pra dar tag composta ("Tecnológico · Corpo-a-Corpo" etc.),
# derivada do physics.trajectory_type ja reclassificado individualmente.
_FUNCTIONAL_SUFFIX_PREFIXES = (
    ("ARCO_BALÍSTICO", "THROWN"),
    ("N/A_(CORPO-A-CORPO", "MELEE"),
    ("N/A_(EQUIPAMENTO", "EQUIP"),
)


def _raw_enum_key(value: str) -> str:
    return str(value or "").strip().upper().replace(" ", "_")


def _functional_suffix(trajectory_type: str) -> str | None:
    t = _raw_enum_key(trajectory_type)
    for prefix, suffix in _FUNCTIONAL_SUFFIX_PREFIXES:
        if t.startswith(prefix):
            return suffix
    return None


def _functional_key(prefix: str, trajectory_type: str) -> str:
    if prefix in ("TEC", "MAG"):
        suffix = _functional_suffix(trajectory_type)
        if suffix:
            return f"{prefix}_{suffix}"
        return f"{prefix}_RANGED"
    return prefix


def _tier_index(weapon: dict[str, Any]) -> int:
    raw = weapon.get("runification_tier") or weapon.get("class")
    if raw and str(raw).upper() in _TIER_INDEX:
        return _TIER_INDEX[str(raw).upper()]
    corruption = (weapon.get("stats") or {}).get("corruption_affinity")
    if isinstance(corruption, (int, float)):
        return max(0, min(3, round(corruption / 33)))
    return 1


# Base por familia/funcao - mesma tabela ja usada e verificada (sem colisao
# numerica dentro da mesma categoria) na retrofit do Codice desta sessao.
_BASE_DAMAGE: dict[str, float] = {
    "FUZ": 22, "REV": 28, "ESP": 45, "PRE": 55, "LAM": 18, "IMP": 14, "RAD": 20, "PRO": 30,
    "ARR": 30, "EXP": 80, "CNT": 5,
    "TEC_RANGED": 20, "TEC_MELEE": 24, "TEC_THROWN": 26,
    "MAG_RANGED": 26, "MAG_MELEE": 20,
}
_BASE_FIRE_RATE: dict[str, float] = {  # tiros/ataques por minuto
    "FUZ": 550, "REV": 45, "ESP": 70, "PRE": 35, "LAM": 90, "IMP": 80, "RAD": 85, "PRO": 10,
    "ARR": 12, "EXP": 6, "CNT": 20, "FLA": 15,
    "TEC_RANGED": 400, "TEC_MELEE": 95, "TEC_THROWN": 10,
    "MAG_RANGED": 60, "MAG_MELEE": 90,
}
_BASE_CAPACITY: dict[str, float] = {  # só quem consome munição/energia em pente discreto
    "FUZ": 30, "REV": 6, "ESP": 6, "PRE": 8, "TEC_RANGED": 20,
}


def _fire_mode(key: str, tier_index: int) -> str:
    if key == "FUZ":
        return "RAJADA/AUTOMATICO" if tier_index >= 2 else "SEMI-AUTOMATICO"
    if key in ("REV", "ESP", "PRE"):
        return "SEMI-AUTOMATICO"
    if key == "TEC_RANGED":
        return "AUTOMATICO" if tier_index >= 2 else "SEMI-AUTOMATICO"
    if key == "MAG_RANGED":
        return "CANALIZACAO_CONTINUA"
    if key in ("ARR", "EXP", "PRO", "TEC_THROWN"):
        return "USO_UNICO_ARREMESSO"
    if key in ("TEC_MELEE", "MAG_MELEE", "LAM", "IMP", "RAD"):
        return "N/A_CORPO_A_CORPO"
    if key in ("TEC_EQUIP", "MAG_EQUIP"):
        return "N/A_EQUIPAMENTO_PASSIVO"
    if key in ("CNT", "FLA"):
        return "USO_UNICO_DISPOSITIVO"
    return "N/A"


def compute_concrete_stats(weapon_id: str, weapon: dict[str, Any]) -> dict[str, Any]:
    """Funcao pura - mesma formula ja verificada sem colisao no Codice desta
    sessao, agora nativa do runtime. `weapon` e o dict bruto ja lido do JSON
    de conteudo (precisa de `physics.trajectory_type` e `stats{}`)."""
    match = _WEAPON_ID_RE.match(str(weapon_id).upper())
    if not match:
        raise ValueError(f"weapon_id fora do padrao WPN-XXX-###: {weapon_id!r}")
    prefix = match.group(1)
    trajectory_type = (weapon.get("physics") or {}).get("trajectory_type", "")
    key = _functional_key(prefix, trajectory_type)
    tier_index = _tier_index(weapon)
    stats = weapon.get("stats") or {}
    power = float(stats.get("power", 50))
    handling = float(stats.get("handling", 50))
    utility = float(stats.get("utility", 50))

    base_damage = _BASE_DAMAGE.get(key, _BASE_DAMAGE.get(prefix))
    base_fire_rate = _BASE_FIRE_RATE.get(key, _BASE_FIRE_RATE.get(prefix))
    base_capacity = _BASE_CAPACITY.get(key, _BASE_CAPACITY.get(prefix))

    out: dict[str, Any] = {"weapon_id": weapon_id, "functional_key": key, "tier_index": tier_index,
                            "fire_mode": _fire_mode(key, tier_index)}
    if base_damage is not None:
        out["damage"] = max(0.1, round(base_damage * (0.6 + power / 100) * (1 + tier_index * 0.12), 1))
    if base_fire_rate is not None:
        out["fire_rate_per_min"] = max(0.1, round(base_fire_rate * (0.5 + handling / 100), 1))
    if base_capacity is not None:
        out["capacity"] = max(1, round(base_capacity * (0.6 + utility / 100)))
    return out


class MARWeaponCombatStatsIndex:
    """Indice de leitura (sem SQLite, sem zip) das 96 armas MAR + suas
    estatisticas concretas derivadas. Ponto de integracao documentado pra
    ARPGCombatCore consumir via um accessor `engine.mar_weapons_arpg(...)`
    futuro - nao registra esse accessor aqui (pertence ao arquivo do engine,
    fora do escopo desta integracao), mesmo principio ja usado em
    combat_distance_states.py#distance_modifiers_for_pair."""

    VERSION = VERSION
    AUTHORITY = AUTHORITY

    def __init__(self, content_root: str | Path | None = None) -> None:
        self.content_root = Path(content_root) if content_root else self._default_content_root()
        self._weapons: dict[str, dict[str, Any]] = {}
        self._load()

    @staticmethod
    def _default_content_root() -> Path:
        # 01_RUNTIME -> ...V0_DEV -> ACTIVE_STAGE17_WORKSPACE -> G -> 06_ENGINE -> raiz do projeto
        return Path(__file__).resolve().parents[5]

    def _load(self) -> None:
        weapons_dir = self.content_root / "04_MECANICAS" / "ITENS_E_ARMAS"
        if not weapons_dir.is_dir():
            raise FileNotFoundError(
                f"MARWeaponCombatStatsIndex: pasta de conteudo MAR nao encontrada em {weapons_dir} "
                "- passe content_root explicito apontando pra raiz do projeto (ANDROMEDA_CODEX_CLEAN)."
            )
        for path in sorted(glob.glob(str(weapons_dir / "MAR_*.json"))):
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
            for weapon in doc.get("weapons", []):
                self._weapons[weapon["weapon_id"]] = weapon

    def weapon_ids(self) -> list[str]:
        return sorted(self._weapons)

    def raw(self, weapon_id: str) -> dict[str, Any]:
        return self._weapons[weapon_id]

    def stats_for(self, weapon_id: str) -> dict[str, Any]:
        return compute_concrete_stats(weapon_id, self._weapons[weapon_id])

    def all_stats(self) -> dict[str, dict[str, Any]]:
        return {wid: compute_concrete_stats(wid, w) for wid, w in self._weapons.items()}

    def verify_no_duplicate_stats_within_family(self) -> dict[str, Any]:
        """Confirma a exigencia ja validada no Codice: nenhuma arma da MESMA
        familia/funcao tem estatisticas numericas concretas identicas (equipamento
        passivo, sem numero aplicavel, nao conta como colisao real)."""
        by_key: dict[str, list[tuple[str, tuple]]] = {}
        for wid, w in self._weapons.items():
            stats = compute_concrete_stats(wid, w)
            key = stats["functional_key"]
            tup = (stats.get("damage"), stats.get("fire_rate_per_min"), stats.get("capacity"), stats["fire_mode"])
            by_key.setdefault(key, []).append((wid, tup))
        collisions: list[str] = []
        for key, entries in by_key.items():
            seen: dict[tuple, str] = {}
            for wid, tup in entries:
                if tup[:3] == (None, None, None):
                    continue  # equipamento passivo - ausencia de numero, nao colisao
                if tup in seen:
                    collisions.append(f"{key}: {wid} == {seen[tup]}")
                else:
                    seen[tup] = wid
        return {"status": "PASS" if not collisions else "FAIL", "collisions": collisions,
                "total_weapons": len(self._weapons)}
