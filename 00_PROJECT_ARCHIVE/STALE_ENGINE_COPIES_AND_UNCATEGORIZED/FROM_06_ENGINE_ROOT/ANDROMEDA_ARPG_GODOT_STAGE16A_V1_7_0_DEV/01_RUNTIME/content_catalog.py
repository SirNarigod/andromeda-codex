from __future__ import annotations

import hashlib
from typing import Any

VERSION = "V1.2.1-DEV"
AUTHORITY = "AUTHOR_AUTHORIZED_NAMING_AND_RESOURCE_EXPANSION_PENDING_MASTER_CONSOLIDATION"
TIERS = ("BAIXO", "MÉDIO", "ALTO")

# New names are explicitly author-authorized but remain outside the sealed Master until consolidation.
STATE_NAMES = {
    "TECHNOLOGY": "Arquenor",
    "ROBOTICS": "Ferravox",
    "MILITARY": "Kharadum",
    "MAGIC": "Lúmen-Vael",
    "NATURE": "Sylvarin",
}

RESOURCE_CATALOG = (
    ("MIN-IRON", "Ferral Bruto", "METAL"),
    ("MIN-COPPER", "Cobrex Condutor", "METAL"),
    ("MIN-TIN", "Estanho Nimbo", "METAL"),
    ("MIN-SILVER", "Argêntea Pálida", "PRECIOUS_METAL"),
    ("MIN-GOLD", "Aúreo Solar", "PRECIOUS_METAL"),
    ("MIN-CRYSTAL", "Cristal Rúnico", "MAGIC_MINERAL"),
    ("MIN-MANA-ORE", "Manalita", "MAGIC_MINERAL"),
    ("MIN-VOID-GLASS", "Vidro Umbral", "MAGIC_MINERAL"),
    ("MIN-STONE", "Rocha Estrutural", "STONE"),
    ("MIN-BASALT", "Basalto Negro", "STONE"),
    ("MIN-QUARTZ", "Quartzo de Veio", "STONE"),
    ("MIN-RARE", "Liga-Núcleo Bruta", "RARE_MINERAL"),
    ("MIN-TITAN", "Titanita Cinzenta", "RARE_MINERAL"),
    ("MIN-ROBOTIUM", "Robotita Azul", "TECH_MINERAL"),
    ("MIN-MAGNETITE", "Magnetita de Pulso", "TECH_MINERAL"),
    ("MIN-ROOT-SHARD", "Fragmento Radicular", "CORRUPTED_MINERAL"),
)

RESOURCE_NAMES = {rid: name for rid, name, _ in RESOURCE_CATALOG}
FLORA_NAMES = {
    "FLR-GRAIN": "Grão-de-Sol",
    "FLR-PASTURE": "Capim Velário",
    "FLR-HARDWOOD": "Madeira-Forte de Syl",
    "FLR-MEDICINAL": "Erva Serenal",
    "FLR-RUNIC_MOSS": "Musgo Rúnico",
    "FLR-FROST_REED": "Junco de Geada",
    "FLR-DESERT_SHRUB": "Arbusto Cinzabrasa",
}
FAUNA_NAMES = {
    "FAU-GRAZER": "Ruminante de Veldra",
    "FAU-BROWSER": "Folhívoro de Dossel",
    "FAU-SCAVENGER": "Varredor Cinzento",
    "FAU-PREDATOR-L": "Rasga-Mato",
    "FAU-PREDATOR-M": "Velúrio-Cinzento",
    "FAU-PREDATOR-H": "Quebra-Casca",
    "FAU-INSECT-POLL": "Lúmen-Polinizador",
    "FAU-INSECT-HIVE": "Ferra-Colmeia",
    "FAU-ROOT-PREDATOR": "Predador Radicular",
}

DUNGEON_WEAPONS = (
    {"item_ref": "WPN-DNG-SWORD-001", "name": "Espada do Vigia Caído", "family": "SWORD", "tier": "MÉDIO", "base_durability": 74, "stats": {"power": 58, "handling": 62, "reach": 48, "utility": 44}},
    {"item_ref": "WPN-DNG-CROSSBOW-001", "name": "Besta de Ferrolho Antiga", "family": "CROSSBOW", "tier": "MÉDIO", "base_durability": 68, "stats": {"power": 70, "handling": 42, "reach": 82, "utility": 47}},
    {"item_ref": "WPN-DNG-BOW-001", "name": "Arco de Galho Negro", "family": "BOW", "tier": "BAIXO", "base_durability": 61, "stats": {"power": 55, "handling": 68, "reach": 78, "utility": 52}},
    {"item_ref": "WPN-DNG-WHIP-001", "name": "Chicote de Corrente Velária", "family": "WHIP", "tier": "ALTO", "base_durability": 79, "stats": {"power": 50, "handling": 72, "reach": 66, "utility": 76}},
)
DUNGEON_WEAPON_BY_REF = {x["item_ref"]: x for x in DUNGEON_WEAPONS}

ITEM_NAMES = {
    "ITEM-TORCH": "Tocha de Breu Claro",
    "ITEM-OLD-KEY": "Chave de Ferro Gasto",
    "ITEM-RUNE-DUST": "Pó Rúnico",
    "ITEM-MANA-CRYSTAL": "Cristal de Mana",
    "ITEM-FOOD": "Ração de Viagem",
    "ITEM-WATER": "Água de Cantil",
    "ITEM-TOOL": "Ferramenta de Campo",
    "ITEM-CIRCUIT": "Circuito Modular",
    "ITEM-SENSOR": "Sensor de Pulso",
    "ITEM-SERVO": "Servo Articulado",
    "ITEM-ACTUATOR": "Atuador de Força",
    "ITEM-GRAIN": "Saco de Grão-de-Sol",
    "ITEM-FRUIT": "Fruta de Veldra",
    "ITEM-ARMOR": "Armadura de Serviço",
    "ITEM-HERB": "Erva Serenal Seca",
    "ITEM-ENERGY-CELL": "Célula de Energia",
    "ITEM-PERSONAL": "Pertence Pessoal",
    "ITEM-FAUNA-RESOURCE": "Recurso Faunístico Processável",
}
ITEM_NAMES.update({x["item_ref"]: x["name"] for x in DUNGEON_WEAPONS})
ITEM_NAMES.update(RESOURCE_NAMES)
ITEM_NAMES.update({f"ITEM-HARVEST-{ref}": f"Colheita de {name}" for ref, name in FLORA_NAMES.items()})
ITEM_NAMES.update({f"ITEM-FAUNA-{ref}": f"Recurso de {name}" for ref, name in FAUNA_NAMES.items()})

CITY_ROOTS = {
    "TECHNOLOGY": ("Axioma", "Dínamo", "Nexora", "Calibre", "Vetor", "Prisma"),
    "ROBOTICS": ("Servália", "Cobalto", "Autômata", "Mecara", "Engren", "Nódulo"),
    "MILITARY": ("Bastião", "Vigília", "Escarpa", "Fortem", "Lança", "Muralha"),
    "MAGIC": ("Aster", "Runária", "Véu", "Lumora", "Espiral", "Névoa"),
    "NATURE": ("Verdel", "Cedral", "Veldra", "Musgália", "Ribeira", "Dossel"),
}
CITY_SUFFIXES = ("Alta", "Baixa", "Nova", "Velha", "do Norte", "do Sul", "do Vale", "da Ponte", "das Fontes", "do Veio")
NPC_GIVEN = {
    "MAGE": ("Arel", "Mira", "Vael", "Sera", "Neris", "Oryn"),
    "NATIVE": ("Taren", "Luma", "Kael", "Nara", "Iven", "Suli"),
    "ROBOT": ("AX", "CR", "V7", "NQ", "K4", "Rho"),
    "WARRIOR": ("Darek", "Mara", "Vorn", "Ilya", "Tarek", "Senn"),
    "MERCENARY": ("Rask", "Vela", "Corin", "Jax", "Nemm", "Tyr"),
    "WORKER": ("Parel", "Ina", "Doran", "Meli", "Rud", "Ena"),
    "CHILD": ("Lio", "Nia", "Tomi", "Mila", "Eri", "Sola"),
}
NPC_FAMILY = ("Valen", "Oris", "Teral", "Marn", "Sorel", "Kerin", "Dovar", "Neral")
SHOP_NAMES = {
    "GENERAL": "Entreposto da Travessia", "WEAPONS": "Forja do Bastião", "MAGIC": "Casa do Prisma Rúnico",
    "TECH": "Oficina Vetorial", "ROBOTICS": "Núcleo de Servos", "MATERIALS": "Depósito do Veio", "FOOD": "Mercado Grão-de-Sol",
}


def _idx(key: str, n: int) -> int:
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(h[:12], 16) % n


def state_name(archetype: str) -> str:
    return STATE_NAMES.get(archetype, f"Estado {archetype.title()}")


def city_name(archetype: str, record_id: str) -> str:
    roots = CITY_ROOTS.get(archetype, CITY_ROOTS["NATURE"])
    return f"{roots[_idx(record_id, len(roots))]} {CITY_SUFFIXES[_idx(record_id + ':s', len(CITY_SUFFIXES))]}"


def npc_name(npc_class: str, record_id: str) -> str:
    given = NPC_GIVEN.get(npc_class, NPC_GIVEN["NATIVE"])
    if npc_class == "ROBOT":
        return f"{given[_idx(record_id, len(given))]}-{100 + _idx(record_id + ':unit', 900)}"
    return f"{given[_idx(record_id, len(given))]} {NPC_FAMILY[_idx(record_id + ':fam', len(NPC_FAMILY))]}"


def shop_name(kind: str, record_id: str) -> str:
    base = SHOP_NAMES.get(kind, "Loja de Travessia")
    return f"{base} {1 + _idx(record_id, 29)}"


def block_name(archetype: str, record_id: str, root_deep: bool = False) -> str:
    if root_deep:
        return f"Fenda Radicular {1 + _idx(record_id, 97)}"
    descriptors = {
        "TECHNOLOGY": "Quadrante Vetorial", "ROBOTICS": "Setor Mecânico", "MILITARY": "Distrito de Vigília",
        "MAGIC": "Círculo Rúnico", "NATURE": "Vale Vivo",
    }
    return f"{descriptors.get(archetype, 'Região')} {1 + _idx(record_id, 97)}"


def subregion_name(parent_block_name: str, record_id: str) -> str:
    terms = ("Norte", "Sul", "Leste", "Oeste", "Central", "Alta", "Baixa")
    return f"{parent_block_name} — {terms[_idx(record_id, len(terms))]}"


def realm_name(record_id: str) -> str:
    roots = ("Círculo de Aster", "Trono de Lumora", "Conclave do Véu", "Coroa de Runária", "Espira de Vael")
    return f"{roots[_idx(record_id, len(roots))]} {1 + _idx(record_id + ':r', 17)}"


def legendary_name(record_id: str) -> str:
    roots = ("Azharel", "Vormir", "Selun", "Khariel", "Nymor", "Thaelor")
    epithets = ("da Bruma", "do Prisma", "da Fenda", "das Runas", "do Véu", "do Trovão")
    return f"{roots[_idx(record_id, len(roots))]} {epithets[_idx(record_id + ':e', len(epithets))]}"


def dungeon_name(record_id: str, root_deep: bool, archetype: str) -> str:
    if root_deep:
        bases = ("Cripta da Raiz Cega", "Poço Radicular", "Câmara da Seiva Negra")
    else:
        bases = {
            "TECHNOLOGY": ("Complexo Vetorial Abandonado", "Subestação Perdida"),
            "ROBOTICS": ("Oficina Autômata Selada", "Poço de Servos"),
            "MILITARY": ("Fortim Subterrâneo", "Arsenal Sepultado"),
            "MAGIC": ("Cripta Rúnica", "Santuário do Véu"),
            "NATURE": ("Ruína do Dossel", "Caverna das Raízes"),
        }.get(archetype, ("Ruína Antiga",))
    return f"{bases[_idx(record_id, len(bases))]} {1 + _idx(record_id + ':d', 31)}"


def object_name(object_type: str, record_id: str) -> str:
    bases = {
        "DOOR": "Porta Reforçada", "TRAPDOOR": "Alçapão de Ferro", "CHAIR": "Cadeira de Carvalho",
        "BOOK": "Códice de Campo", "TORCH": "Tocha de Parede", "GROUND_WEAPON": "Arma Antiga Abandonada",
        "CHEST": "Baú de Expedição", "LEVER": "Alavanca de Mecanismo", "RUNE_PEDESTAL": "Pedestal Rúnico",
        "CONSOLE": "Console de Serviço",
    }
    return f"{bases.get(object_type, 'Objeto de Cena')} {1 + _idx(record_id, 101)}"


def name_status() -> str:
    return "CÂNONE_AUTORIZADO_NOME_PENDING_MASTER_CONSOLIDATION"


def validate_catalog() -> dict[str, Any]:
    failures: list[str] = []
    ids = [x[0] for x in RESOURCE_CATALOG]
    if len(ids) != len(set(ids)):
        failures.append("DUP_RESOURCE_ID")
    weapon_ids = [x["item_ref"] for x in DUNGEON_WEAPONS]
    if len(weapon_ids) != len(set(weapon_ids)):
        failures.append("DUP_DUNGEON_WEAPON_ID")
    if {x["family"] for x in DUNGEON_WEAPONS} != {"SWORD", "CROSSBOW", "BOW", "WHIP"}:
        failures.append("DUNGEON_WEAPON_FAMILIES")
    if any(x["tier"] not in TIERS for x in DUNGEON_WEAPONS):
        failures.append("DUNGEON_WEAPON_TIER")
    for x in DUNGEON_WEAPONS:
        if any(not isinstance(v,int) or not 0 <= v <= 100 for v in x.get("stats",{}).values()):
            failures.append("DUNGEON_WEAPON_STAT_RANGE:" + x["item_ref"])
    return {"status": "PASS" if not failures else "FAIL", "failures": failures, "resources": len(RESOURCE_CATALOG), "named_items": len(ITEM_NAMES), "dungeon_weapons": len(DUNGEON_WEAPONS)}
