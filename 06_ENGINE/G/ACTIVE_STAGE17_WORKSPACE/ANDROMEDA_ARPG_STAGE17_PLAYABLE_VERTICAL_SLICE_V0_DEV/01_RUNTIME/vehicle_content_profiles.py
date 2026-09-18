from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vehicle_movement import DEFAULT_HANDLING_BY_CLASS, map_transport_category_to_domain

# ============================================================================
# ARPG_STAGE17_VEHICLE_CONTENT_PROFILES_NOT_CANON
#
# Achado da auditoria de 13/09 (fase 5, vertical slice): vehicle_movement.py
# (VehicleMovementSystem.drive()) e arpg_mobility_infrastructure_core.py ja
# funcionam de verdade, mas exigem que quem chama informe vehicle_class/
# max_speed_mps explicitamente - so 3 dos 23 veiculos de conteudo
# (STELLAR_TRANSPORT_VEHICLES_CATALOG_DEV_V1_1.json) tem esses numeros reais
# (STELLAR_ENGINE_VEHICLE_CROSSREF_DEV_V1_0.json). Este arquivo fecha a lacuna
# de DADO (nao de codigo - reaproveita map_transport_category_to_domain e
# DEFAULT_HANDLING_BY_CLASS de vehicle_movement.py sem duplicar), gerando um
# perfil (vehicle_class, max_speed_mps, domain) pros 23, priorizando sempre o
# crossref real quando existe e usando uma estimativa deterministica e
# documentada (nunca escolhida a mao por veiculo) pros outros 20 - mesmo
# metodo ja usado e aprovado no Codice desta sessao pro cartao de veiculo.
# ============================================================================

AUTHORITY = "ARPG_STAGE17_VEHICLE_CONTENT_PROFILES_NOT_CANON"
VERSION = "V0.1.0-PRE-GODOT"

# espelha STELLAR_ENGINE_VEHICLE_CROSSREF_DEV_V1_0.json (so 3 dos 23 tem perfil real)
_ENGINE_CROSSREF: dict[str, dict[str, Any]] = {
    "VEI-008": {"vehicle_class": "ROAD_SERVICE", "speed_kmh": 42.0, "cargo_kg": 180.0, "passengers": 4},
    "VEI-004": {"vehicle_class": "ROAD_CARGO", "speed_kmh": 32.0, "cargo_kg": 900.0, "passengers": 2},
    "VEI-006": {"vehicle_class": "SCOUT", "speed_kmh": 38.0, "cargo_kg": 250.0, "passengers": 3},
}

# espelha STELLAR_MOVEMENT_SPEED_REFERENCE_DEV_V1_0.json (faixa km/h por modal)
_SPEED_RANGE_KMH_BY_TRANSPORT_MODE: dict[str, tuple[float, float]] = {
    "FERROVIARIA": (35.0, 60.0), "NAVAL_SUPERFICIE": (10.0, 20.0), "FLUVIAL": (10.0, 20.0),
    "AEREA": (40.0, 80.0), "SUBMERSA": (5.0, 15.0), "TERRESTRE_ESTRADA": (10.0, 25.0),
    "SUBTERRANEA": (10.0, 25.0),
}
_SPEED_VARIATION_FACTOR: dict[str, float] = {"NORMAL": 0.2, "RUNICO": 0.5, "TECNOLOGICO": 0.85}

_DOMAIN_TO_DEFAULT_CLASS = {"FLYING": "AIRCRAFT", "SUBMERGED": "SUBMERSIBLE", "AQUATIC": "WATERCRAFT"}


def _ground_vehicle_class(variation: str, purpose: str) -> str:
    """Heuristica documentada pros veiculos GROUND sem crossref real (so
    aplicada a esses - os 3 com dado real usam o valor real direto, nunca
    esta heuristica). COMBATE puxa pra SCOUT (agil); LAZER pra ROAD_SERVICE
    (conforto de passageiro); TECNOLOGICO de trabalho tambem ROAD_SERVICE
    (motorizado leve); o resto (NORMAL/RUNICO de trabalho) cai em ROAD_CARGO,
    a classe-padrao de veiculo terrestre de carga comum."""
    v = str(variation).upper()
    p = str(purpose).upper()
    if p == "COMBATE":
        return "SCOUT"
    if p == "LAZER":
        return "ROAD_SERVICE"
    if v == "TECNOLOGICO":
        return "ROAD_SERVICE"
    return "ROAD_CARGO"


def _estimated_speed_kmh(transport_mode: str, variation: str) -> float:
    lo, hi = _SPEED_RANGE_KMH_BY_TRANSPORT_MODE.get(str(transport_mode).upper(), (10.0, 20.0))
    factor = _SPEED_VARIATION_FACTOR.get(str(variation).upper(), 0.4)
    return round(lo + (hi - lo) * factor, 1)


def profile_for_vehicle(vehicle: dict[str, Any]) -> dict[str, Any]:
    """`vehicle` e o dict bruto de 1 entrada de
    STELLAR_TRANSPORT_VEHICLES_CATALOG_DEV_V1_1.json (precisa de vehicle_id,
    category, variation, transport_mode, purpose). Devolve
    {vehicle_class, max_speed_mps, domain, handling, source}, pronto pra
    alimentar VehicleMovementSystem.spawn()/.drive() sem numero inventado a
    mao por veiculo."""
    vehicle_id = vehicle["vehicle_id"]
    category = vehicle.get("category", "")
    variation = vehicle.get("variation") or "NORMAL"
    transport_mode = vehicle.get("transport_mode", "")
    purpose = vehicle.get("purpose", "TRABALHO")

    crossref = _ENGINE_CROSSREF.get(vehicle_id)
    try:
        domain = map_transport_category_to_domain(category, transport_mode)
    except ValueError:
        # VEI-005 (LEGADO_FORA_DA_GRADE, vagonete subterraneo) nao mapeia pra
        # nenhum dos 4 dominios do motor - fallback documentado, nao um erro
        # silencioso: tratado como GROUND/ROAD_CARGO (vagonete sobre trilho).
        domain = "GROUND"

    if crossref:
        vehicle_class = crossref["vehicle_class"]
        max_speed_mps = round(crossref["speed_kmh"] / 3.6, 3)
        source = "engine_crossref"
    else:
        if domain in _DOMAIN_TO_DEFAULT_CLASS:
            vehicle_class = _DOMAIN_TO_DEFAULT_CLASS[domain]
        else:
            vehicle_class = _ground_vehicle_class(variation, purpose)
        max_speed_mps = round(_estimated_speed_kmh(transport_mode, variation) / 3.6, 3)
        source = "estimated_from_content"

    return {
        "vehicle_id": vehicle_id,
        "domain": domain,
        "vehicle_class": vehicle_class,
        "max_speed_mps": max_speed_mps,
        "handling": dict(DEFAULT_HANDLING_BY_CLASS[vehicle_class]),
        "source": source,
        "authority": AUTHORITY,
    }


class VehicleContentProfileIndex:
    """Indice de leitura (sem SQLite, sem zip) dos 23 veiculos de conteudo +
    seus perfis de movimento derivados."""

    VERSION = VERSION
    AUTHORITY = AUTHORITY

    def __init__(self, content_root: str | Path | None = None) -> None:
        self.content_root = Path(content_root) if content_root else self._default_content_root()
        self._vehicles: dict[str, dict[str, Any]] = {}
        self._load()

    @staticmethod
    def _default_content_root() -> Path:
        return Path(__file__).resolve().parents[5]

    def _load(self) -> None:
        path = (self.content_root / "04_MECANICAS" / "ECONOMIA_E_RECURSOS" /
                "STELLAR_TRANSPORT_VEHICLES_CATALOG_DEV_V1_1.json")
        if not path.is_file():
            raise FileNotFoundError(
                f"VehicleContentProfileIndex: catalogo de veiculos nao encontrado em {path} "
                "- passe content_root explicito apontando pra raiz do projeto (ANDROMEDA_CODEX_CLEAN)."
            )
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        for vehicle in doc.get("vehicles", []):
            self._vehicles[vehicle["vehicle_id"]] = vehicle

    def vehicle_ids(self) -> list[str]:
        return sorted(self._vehicles)

    def profile_for(self, vehicle_id: str) -> dict[str, Any]:
        return profile_for_vehicle(self._vehicles[vehicle_id])

    def all_profiles(self) -> dict[str, dict[str, Any]]:
        return {vid: profile_for_vehicle(v) for vid, v in self._vehicles.items()}
