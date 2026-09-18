# Regiões do M1 (escolha documentada)

Os 20 territórios são navegáveis (grafo de rotas válido). Grids exploráveis
reais no M1, apenas 3 — demais territórios usam placeholder "em expansão"
com dados válidos (loja/fauna/quests) e viagem liberada.

| Grid | Território | Âncora canônica | Papel no M1 |
|---|---|---|---|
| 1 | TER-011 Terras Livres | SUB-011-001 Fronteira de Varga (VARGA_POIs, NPCs locais, EST-005) | Tutorial: criar → explorar → NPC → quest |
| 2 | TER-001 Confederação de Lúminor | SUB-001-001 Feira Central (EST-001, Câmara Mercantil) | Capital: loja completa, viagem continental |
| 3 | TER-012 Zonas de Contenção | SUB-012-003 Guarnição de Contenção (EST-009, craft C-tier) | Fronteira de risco: pressão de corrupção, loot COR-RES condicional |

Zona corrompida próxima a Varga: **definição existente no Codex, sem invenção**
— `SUB-011-006 Fendas da Névoa` (portão de corrupção, fase 57; fauna
CRI-010..013; flora FLO-002/FLO-006; gate `STELLAR_ROOT_CORRUPTION_GATE_DEV_V1_0.json`).
No M1 ela aparece como **zona de perigo dentro do grid TER-011**
(tiles corrompidos com pressão/debuff), não como grid próprio.
Nenhuma fase além de CORRUPTION sem gate autoral (lei R2).
