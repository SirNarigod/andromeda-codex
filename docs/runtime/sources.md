# Fontes canônicas → dados web (somente leitura)

Gerador: `tools/gen_web_data.py` → `web/src/data/*.json` + `manifest.json`
(sha16 de cada fonte). Regenerar nunca edita as fontes.

| Dado web | Fonte canônica |
|---|---|
| territories, routes | `01_LORE/.../GEOGRAFIA/STELLAR_TERRAIN_TRAVEL_SYSTEM_DEV_V1_0.json`, `STELLAR_ROUTE_NETWORK_DEV_V1_0.json`, `STELLAR_REGION_COORDINATE_INDEX_DEV_V1_0.json` |
| landscapes (PAI→SUB→TER) | `STELLAR_LANDSCAPE_FEATURES_INDEX_DEV_V1_0.json` |
| creatures | `04_MECANICAS/CRIATURAS/MAR_BESTIARY_GAMEPLAY_STATS_DEV_V1_0.json` |
| npcs | `04_MECANICAS/NPCS/MAR_NPC_ROSTER_*.json` + `MAR_CORRUPTED_NPC_ROSTER_DEV_V1_0.json` |
| civilians | `04_MECANICAS/NPCS/STELLAR_MINOR_NPC_CATALOG_DEV_V1_0.json` |
| classes/attrs | `.../SOCIEDADES/CLASSES/MAR_PLAYABLE_CLASSES_LORE_DEV_V1_0.json` + `04_MECANICAS/ITENS_E_ARMAS/MAR_CLASS_ARMAMENT_MATRIX_DEV_V1_0.json` (medianas) |
| skills | rosters (active/passive; `fx` = leitura mecânica runtime) |
| weapons/arsenal | `04_MECANICAS/ITENS_E_ARMAS/*.json` (stats+physics) |
| quests | `04_MECANICAS/QUESTS_DINAMICAS/*.json` |
| est | `01_LORE/.../CONSTRUCOES/EST-*.json` |
| items | medicine/equipment/armor catalogs + `VARGA_STARTER_KIT_V1.json` |
| currencies/econ/commerce | `STELLAR_CURRENCY_SYSTEM_DEV_V1_0.json`, `STELLAR_SYSTEMIC_ECONOMY_STATE_DEV_V1_0.json` |
| fauna/enc_profiles/loot | `01_LORE/CANON_MASTER_V2/FAUNA/MASTER_FAUNA_DISTRIBUTION_V2_0_0.json`, `STELLAR_ENCOUNTER_CATALOG_V1_0.json` |
| conditions | fase 72 da Mesa (CONTENCAO/OFUSCADO/ESPORO/RAIZ) |
| varga | `.../TERRAS_LIVRES/SUBREGIOES/VARGA_VERTICAL_SLICE_MAP_V1.json` |
| bands/speeds | bandas de alcance MAR; velocidades de viagem |

Regras portadas do `01_RUNTIME` (slice STAGE17): hit/crit/dano/mitigação/XP
(`arpg_combat_core.py`), quote→execute (`commerce_system.py`), movimento
(`continuous_movement.py`), relógio de corrupção em 6 fases
(`root_corruption_system.py`), RNG `sha256(seed‖evento)`.
