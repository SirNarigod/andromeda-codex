# Stellar — Índice Mestre de Referência (DEV v1.0)

> Documento de consulta gerado ao final de uma sessão extensa de world-building do sistema **MAR (Magia, Armas e Runas)** e do mundo **Stellar**. Não substitui os arquivos-fonte (é um índice, não uma cópia) — cada seção aponta para os arquivos reais. Todo o conteúdo aqui listado é `CANON_DERIVADO_ATIVO` ou `GAMEPLAY_DERIVED_DEV_SOURCE`; o cânone R2 imutável permanece intocado em `01_LORE/CANON_R2/`.

---

## 1. Geografia — 20 territórios

| Cód. | Território | Tema/terreno | Pasta |
|---|---|---|---|
| TER-001 | Confederação de Lúminor | Planície comercial | `01_LORE/CANON_DERIVADO_ATIVO/GEOGRAFIA/CONFEDERACAO_DE_LUMINOR/` |
| TER-002 | Reino Ferral de Kharveth | Industrial/ferroviário | `.../REINO_FERRAL_DE_KHARVETH/` |
| TER-003 | República de Ortheon | Nó ferroviário | `.../REPUBLICA_DE_ORTHEON/` |
| TER-004 | Arquipélago Livre de Navyr | Marítimo | `.../ARQUIPELAGO_LIVRE_DE_NAVYR/` |
| TER-005 | Principado de Ithra | Urbano-tecnomágico | `.../PRINCIPADO_DE_ITHRA/` |
| TER-006 | Reino Aéreo de Altavela | Plataformas aéreas | `.../REINO_AEREO_DE_ALTAVELA/` |
| TER-007 | Rubra-Viva | Pântano medicinal | `.../RUBRA_VIVA/` |
| TER-008 | Santuários do Coração | Floresta-dossel sagrada | `.../SANTUARIOS_DO_CORACAO/` |
| TER-009 | Liga Subcristal | Subterrâneo/cristal | `.../LIGA_SUBCRISTAL/` |
| TER-010 | Domínio dos Reis Magos | Urbano-mágico | `.../DOMINIO_DOS_REIS_MAGOS/` |
| TER-011 | Terras Livres | Fronteira mista (6 subregiões) | `.../TERRAS_LIVRES/` |
| TER-012 | Zonas de Contenção | Zona de contenção | `.../ZONAS_DE_CONTENCAO/` |
| TER-013 | Fortaleza do Trovão | Montanha/tempestade | `.../FORTALEZA_DO_TROVAO/` |
| TER-014 | Cadeia de Cinzas | Vulcânico | `.../CADEIA_DE_CINZAS/` |
| TER-015 | Vale das Ruínas | Deserto/ruínas anônimas | `.../VALE_DAS_RUINAS/` |
| TER-016 | Confins de Gelo | Glacial | `.../CONFINS_DE_GELO/` |
| TER-017 | Arquipélago Etéreo | Ilhas flutuantes mágicas | `.../ARQUIPELAGO_ETEREO/` |
| TER-018 | Fossa Abissal | Abismo submerso | `.../FOSSA_ABISSAL/` |
| TER-019 | Mata Perdida | Selva tropical/ruínas cobertas | `.../MATA_PERDIDA/` |

**Totais**: 65 subregiões, 68 localidades (43 + CIT-001/002 pré-existentes + 3 de cada novo território), **68 construções (`EST-001..068`)** cobrindo 100% das localidades — índice em [`CONSTRUCOES/EST_INDEX_DEV_V1_0.json`](01_LORE/CANON_DERIVADO_ATIVO/CONSTRUCOES/EST_INDEX_DEV_V1_0.json).

### Atlas Continental (fase 53)
- [`STELLAR_LANDSCAPE_FEATURES_INDEX_DEV_V1_0.json`](01_LORE/CANON_DERIVADO_ATIVO/GEOGRAFIA/STELLAR_LANDSCAPE_FEATURES_INDEX_DEV_V1_0.json) — 65 paisagens nomeadas (montanhas, pântanos, lagos, florestas, vulcões, geleiras etc.).
- [`STELLAR_ROUTE_NETWORK_DEV_V1_0.json`](01_LORE/CANON_DERIVADO_ATIVO/GEOGRAFIA/STELLAR_ROUTE_NETWORK_DEV_V1_0.json) — 62 rotas (44 locais + 18 continentais), rede mínima conectada, grafo verificado conexo.
- [`STELLAR_BRIDGES_INDEX_DEV_V1_0.json`](01_LORE/CANON_DERIVADO_ATIVO/GEOGRAFIA/STELLAR_BRIDGES_INDEX_DEV_V1_0.json) — 10 pontes (PEQUENA/MÉDIA/GRANDE).
- [`STELLAR_TERRAIN_TRAVEL_SYSTEM_DEV_V1_0.json`](01_LORE/CANON_DERIVADO_ATIVO/GEOGRAFIA/STELLAR_TERRAIN_TRAVEL_SYSTEM_DEV_V1_0.json) — perfil de terreno/modal de transporte por território e subregião.
- [`STELLAR_REGION_COORDINATE_INDEX_DEV_V1_0.json`](01_LORE/CANON_DERIVADO_ATIVO/GEOGRAFIA/STELLAR_REGION_COORDINATE_INDEX_DEV_V1_0.json) — coordenadas sintéticas (79 regiões) no CRS `ACRS-STELLAR-GEODETIC-V1`.
- [`BIOMA_TERRITORIO_LINKS_DEV_V1_0.json`](01_LORE/CANON_DERIVADO_ATIVO/GEOGRAFIA/BIOMA_TERRITORIO_LINKS_DEV_V1_0.json) — vínculo dos 6 biomas R2 aos territórios.

---

## 2. Sistema MAR (Magia, Armas e Runas) — `04_MECANICAS/`

- **80 armas** em 4 classes (Nativos/Soldados/Androids/Magos) — `ITENS_E_ARMAS/MAR_*.json`, índice mestre [`MAR_CLASS_ARMAMENT_MATRIX_DEV_V1_0.json`](04_MECANICAS/ITENS_E_ARMAS/MAR_CLASS_ARMAMENT_MATRIX_DEV_V1_0.json).
- **40 NPCs de combate** (8 Nativos, 16 Soldados, 8 Androids, 8 Magos) — `NPCS/MAR_NPC_ROSTER_*.json`, sistema de 4 funções (Médico/Suporte/Assalto/Franco) em [`MAR_COMBAT_ROLES_DEV_V1_0.json`](04_MECANICAS/NPCS/MAR_COMBAT_ROLES_DEV_V1_0.json).
- **8 androids civis** (Médico/Suporte/Trabalho/Sociável) — [`MAR_ANDROID_UNITS_CIVIS_DEV_V1_0.json`](04_MECANICAS/NPCS/MAR_ANDROID_UNITS_CIVIS_DEV_V1_0.json).
- **Progressão de jogador** — [`STELLAR_PLAYER_PROGRESSION_PROFILE_DEV_V1_0.json`](04_MECANICAS/JOGADOR_E_PROGRESSAO/STELLAR_PLAYER_PROGRESSION_PROFILE_DEV_V1_0.json), liga classes/skills ao jogador.
- **Peças de construção do jogador** (24, estilo sobrevivência) — [`STELLAR_BUILDING_PIECES_CATALOG_DEV_V1_0.json`](04_MECANICAS/CONSTRUCAO_JOGADOR/STELLAR_BUILDING_PIECES_CATALOG_DEV_V1_0.json).

---

## 3. Bestiário e Flora — `04_MECANICAS/CRIATURAS/` + `01_LORE/CANON_DERIVADO_ATIVO/ECOLOGIA/FLORA/`

- **32 criaturas** (13 originais + 6 de bioma TER-014..019 + 7 corrompidas CRI-020..026 + 6 peixes CRI-027..032 fases 60/61) — [`MAR_BESTIARY_GAMEPLAY_STATS_DEV_V1_0.json`](04_MECANICAS/CRIATURAS/MAR_BESTIARY_GAMEPLAY_STATS_DEV_V1_0.json).
- Variantes hostis (Normal/Mágica/Alpha, 10 criaturas × 3) — [`MAR_BESTIARY_VARIANTS_DEV_V1_0.json`](04_MECANICAS/CRIATURAS/MAR_BESTIARY_VARIANTS_DEV_V1_0.json); variantes passivas (15 × 3, incl. peixes) — [`MAR_BESTIARY_VARIANTS_PASSIVE_DEV_V1_0.json`](04_MECANICAS/CRIATURAS/MAR_BESTIARY_VARIANTS_PASSIVE_DEV_V1_0.json).
- **18 espécies de flora** (6 originais + 12 novas) — `FLO-001..018__*.json`; variantes (Comum/Rara) em [`FLORA_VARIANTS_DEV_V1_0.json`](01_LORE/CANON_DERIVADO_ATIVO/ECOLOGIA/FLORA/FLORA_VARIANTS_DEV_V1_0.json).
- **Índice de ameaças** (10 criaturas hostis + COR-001 Raiz Profunda R2 + facção/território de contenção) — [`STELLAR_THREAT_INDEX_DEV_V1_0.json`](01_LORE/CANON_DERIVADO_ATIVO/AMEACAS/STELLAR_THREAT_INDEX_DEV_V1_0.json).

---

## 4. Economia e Recursos — `04_MECANICAS/ECONOMIA_E_RECURSOS/`

| Catálogo | Itens | Arquivo |
|---|---|---|
| Minerais | 16 (`MIN-XXX`) | `MINERAL_RESOURCE_LOCALITY_LINKS_DEV_V1_0.json` |
| Materiais de artesanato | 8 (`MAT-XXX`) | `STELLAR_CRAFT_RESOURCE_CATALOG_DEV_V1_0.json` |
| Receitas de produção | 80 (1 por arma) | `STELLAR_PRODUCTION_RECIPES_DEV_V1_0.json` |
| Alimentos preparados | 8 (`PRT-XXX`) + 8 derivados (`FOOD-XXX`) | `STELLAR_PREPARED_FOOD_DEV_V1_0.json`, `STELLAR_DERIVED_FOOD_DEV_V1_0.json` |
| Munição | 8 (`AMMO-XXX`) | `STELLAR_AMMO_CATALOG_DEV_V1_0.json` |
| Runas | 10 (`RUNA-XXX`) | `STELLAR_RUNE_CATALOG_DEV_V1_0.json` |
| Equipamentos de suporte | 10 (`EQP-XXX`) | `STELLAR_SUPPORT_EQUIPMENT_DEV_V1_0.json` |
| Medicamentos | 8 (`MED-XXX`) | `STELLAR_MEDICINE_CATALOG_DEV_V1_0.json` |
| Armadura de combate | 8 (`VST-XXX`) | `STELLAR_ARMOR_CATALOG_DEV_V1_0.json` |
| Vestuário civil | 19 (`TRJ-XXX`, 1 por território) | `STELLAR_CIVILIAN_CLOTHING_CATALOG_DEV_V1_0.json` |
| Veículos | 23 (`VEI-XXX`, 3 categorias × 3 variações + legado) | `STELLAR_TRANSPORT_VEHICLES_CATALOG_DEV_V1_1.json` |
| Extração de recursos | 29 entradas (16 minério + 13 flora) | `STELLAR_RESOURCE_EXTRACTION_INDEX_DEV_V1_0.json` |
| Agricultura | 8 zonas fixas (`AGZ-XXX`) | `01_LORE/CANON_DERIVADO_ATIVO/AGRICULTURA/AGZ_INDEX_DEV_V1_0.json` |

---

## 5. Sociedade — NPCs, Profissões, Facções, Quests

- **33 NPCs civis nomeados** (`CIV-001..033`) — [`STELLAR_MINOR_NPC_CATALOG_DEV_V1_0.json`](04_MECANICAS/NPCS/STELLAR_MINOR_NPC_CATALOG_DEV_V1_0.json).
- **16 profissões** (`JOB-001..016`) com 21 vínculos a construções — [`STELLAR_PROFESSION_CATALOG_V1_0.json`](04_MECANICAS/TRABALHO_E_PROFISSOES/STELLAR_PROFESSION_CATALOG_V1_0.json) + [`STELLAR_PROFESSION_LOCATION_INDEX_DEV_V1_0.json`](04_MECANICAS/TRABALHO_E_PROFISSOES/STELLAR_PROFESSION_LOCATION_INDEX_DEV_V1_0.json).
- **Distribuição consolidada** de NPCs/fauna/flora/facções em locais — [`STELLAR_ENTITY_LOCATION_INDEX_DEV_V1_0.json`](01_LORE/CANON_DERIVADO_ATIVO/DISTRIBUICAO/STELLAR_ENTITY_LOCATION_INDEX_DEV_V1_0.json).
- **21 quests dinâmicas** (20 territoriais QUEST_TER-001..020, incl. TER-011 fase 60 + contrato de travessia de Varga em SUB-011-001) — `04_MECANICAS/QUESTS_DINAMICAS/`.
- **Facções/instituições-mecânica** (FAC-009/010/011 descongeladas para simulação) — [`ARPG_NARRATIVE_CULTURE_COMPATIBILITY_LAYER_V1_0.json`](04_MECANICAS/FACTIONS_AND_INSTITUTIONS/ARPG_NARRATIVE_CULTURE_COMPATIBILITY_LAYER_V1_0.json).

---

## 6. Fundamentos do mundo

- **Guia de lore das 18 leis fundamentais** ("como o mundo funciona") — [`STELLAR_WORLD_RULES_GUIDE_DEV_V1_0.json`](01_LORE/CANON_DERIVADO_ATIVO/FUNDAMENTOS/STELLAR_WORLD_RULES_GUIDE_DEV_V1_0.json).
- **Calendário de Stellar** (4 estações, 12 meses, 7 dias, 4 períodos) — [`STELLAR_CALENDAR_SYSTEM_DEV_V1_0.json`](01_LORE/CANON_DERIVADO_ATIVO/COSMOLOGIA/STELLAR_CALENDAR_SYSTEM_DEV_V1_0.json).

---

## 7. Extensão Fase 56 — Agrícola/mineral dos 6 novos (TER-014..019)

- **6 zonas agrícolas formais novas (AGZ-098..103)** — `01_LORE/CANON_DERIVADO_ATIVO/AGRICULTURA/AGZ_EXTENSION_098_103_DEV_V1_0.json` (`AUTHORIAL_DECISION_FASE_56`, total formal 8 → 14; AGZ-090..097 intactos):
  - AGZ-098 Terraços de Cinza (TER-014, CINZA_CULTURA, SUB-014-003/EST-051, FLO-013)
  - AGZ-099 Oásis do Poço Fundo (TER-015, OASIS_SUBSISTENCIA, SUB-015-003/EST-054, FLO-014)
  - AGZ-100 Estufas do Abrigo (TER-016, ESTUFA_GLACIAL, SUB-016-002/EST-056, FLO-015 — cultivo protegido)
  - AGZ-101 Jardins Suspensos de Éter (TER-017, AEROPONIA_ETEREA, SUB-017-001/EST-058, FLO-016)
  - AGZ-102 Recifes Luminosos (TER-018, MARICULTURA_ABISSAL, SUB-018-002/EST-062, FLO-017)
  - AGZ-103 Clareiras da Mata (TER-019, AGROFLORESTA_TROPICAL, SUB-019-001/EST-064, FLO-018, `NO_ROOT_ESCALATION`)
- **Mineral secundário detalhado (6/6)**: `MIN-BASALT→TER-014 (SUB-014-001/EST-049)`, `MIN-GOLD→TER-015 (SUB-015-002/EST-053)`, `MIN-QUARTZ→TER-016 (SUB-016-001/EST-055)`, `MIN-CRYSTAL→TER-017 (SUB-017-002/EST-059)`, `MIN-TITAN→TER-018 (SUB-018-001/EST-061)`, `MIN-ROOT-SHARD→TER-019 (SUB-019-002/EST-065)` — campos `secondary_extraction` em `MINERAL_RESOURCE_LOCALITY_LINKS_DEV_V1_0.json`.
- **Extração operacional**: 10 novas entradas em `STELLAR_RESOURCE_EXTRACTION_INDEX_DEV_V1_0.json` (5 minerais + FLO-014..018) + `resources[]` sincronizado nos 12 SUBs-âncora.
- Lacuna da fase 54 ("perfil agrícola/mineral dos 6 novos fica para rodada futura") **resolvida nesta fase 56**.

## 8. Correções Fase 60 — pendências do 04_MECANICAS

- **QUEST_TER-011 criada** (`QUEST_TER-011_V1_0.json`, SUB-011-003 Pastagens Luminais / EST-037, template padrão WELCOME→REPORT + AVOID/REPAIR/ESCALATE_REPORT) — fecha o único território sem quest; contrato de Varga segue como quest especial de travessia em SUB-011-001.
- **Pesca marinha/oásis (CRI-027..029)**: Peixe-Vela (SUB-004-002), Peixe-Lanterna (SUB-018-002/FLO-017), Peixe do Poço (SUB-015-003/AGZ-099) — stats + 9 variantes passivas + extração PESCA via JOB-003 (fontes de JOB-003 estendidas, sem JOB novo). Rios (paisagem RIO) seguem abertos — ver `fishing_node_note` em `STELLAR_MASTERY_PROGRESSION_SYSTEM_DEV_V1_0.json`.
- Extração validada completa: 16 MIN primários + 6 secundários + 18 FLO + 3 FAUNA.

## 9. Fase 61 — Rios + peixes fluviais (fecha item 1 das pendências)

- **3 travessias RIO** (`STELLAR_LANDSCAPE_FEATURES_INDEX`, 65 → 68): PAI-066 Rio Raizel (SUB-011-004, vau LOC-011-004, cruza ROT-023/024), PAI-067 Rio Rubro (SUB-007-002, passa sob PON-002 — o motivo da ponte existir), PAI-068 Rio da Serpente (SUB-019-003, alimenta o pântano). Rios registram travessia, nunca fronteira.
- **3 peixes de rio (CRI-030..032)**: Raizel, Rubro, Traíra da Serpente — stats + 9 variantes + extração PESCA/JOB-003 + SUBs sincronizados.
- Gap "sem RIO / sem peixe" **totalmente fechado**; nó de pesca opera em águas mapeadas (fallback genérico só para não-mapeadas).

## 10. Fase 62 — Imports Master 4–5 (fonte achada no ZIP da raiz)

- **EDUCACAO_CIENCIA (62)** → `01_LORE/CANON_MASTER_V2/EDUCACAO/MASTER_EDUCACAO_CATALOG_V2_0_0.json` (nós operacionais EDUCATION/SCIENCE, verbatim + proveniência; sem colisão; EDU-XXX seguem stubs). TIER_INDEX: PENDENTE → IMPORTADO.
- **ATLAS_RUNTIME** → `01_LORE/CANON_MASTER_V2/ATLAS_RUNTIME/` (index.html/app.js/atlas-core.mjs/styles.css + data/ + catálogo-manifesto com sha256). Abrir `index.html` no navegador. Tools do pacote em `07_AUTOMATION/TOOLS/validate_master.py` + `run_master_atlas_runtime.mjs`.
- **FAUNA_DISTRIBUTION (64 spp)** → `01_LORE/CANON_MASTER_V2/FAUNA/MASTER_FAUNA_DISTRIBUTION_V2_0_0.json` (verbatim + proveniência). Cobre CRI-001..013 (R2); CRI-014+ são gameplay nosso, sem conflito. `note_incomplete_source` do bestiário resolvida.
- Nenhum PENDENTE restante no TIER_INDEX; bloqueios 4–5 eliminados (fonte era o ZIP local).

## 11. Fase 63 — Itens 6–7 (by-design + fase 59)

- **Fase 59 verificada entregue**: 10 ZUM-001..010 (`MAR_CORRUPTED_NPC_ROSTER_DEV_V1_0.json`) cobrem 1:1 as 10 SUBs com `root_corruption` (008-002, 009-002, 011-006, 012-001/002/003, 013-003, 015-002, 016-003, 019-002) — guarda do bestiário atualizada (não diz mais "fica para fase 59").
- **By-design documentado**: extrações via SUB + JOB-016 genérico são fallback pretendido (cobertura EST total, indústria dedicada opcional) — `by_design_resolution_fase_63` no EXTRACTION_INDEX. VEI-005, Asa de Copas, stubs ORG/EDU/ECO/VST, Ivara/Orun e guarda Amadon seguem documentados onde ocorrem.
- **Zero pendências acionáveis em todo o repositório.**

## 12. Fase 70 — Andromeda Mesa (RPG de mesa digital)

- App web standalone em `07_AUTOMATION/EXPORTS/MESA/andromeda-mesa.html` + `mesa-data.js` (77 KB, gerado por `gen_mesa_data.py`): mapa esquemático 20 TER, tabuleiro tático grid 1 m com peões arrastáveis, fichas das 5 classes, bestiário 32 + 58 NPCs + 33 civis, 21 quests, dados, névoa, save local.
- Regra MAR adaptada: d20, TPB 80/100/120, bandas CLINCH 1 m / IN_FIGHTING 2.75 / ECQ 6 / MID 20 / LONG 60, roles MÉDICO/SUPORTE/ASSALTO/FRANCO.
- Abrir o HTML no navegador (duplo clique); tutorial = Contrato de Travessia de Varga.
- **Combate automatizado (fase 71)**: aba 💥 com 96 armas (power/reach/handling + trajetória/impacto/área por família), bandas do engine (mults melee/tiro/evasão, tiro proibido em CLINCH), cover (×.75/×.5, arco ignora metade), AoE PEQUENA 2 m/MÉDIA 6/GRANDE 12, Point Blank e bônus sniper. Playtest: NAT-01 abate vespa (35 vs 15 HP), pares 2 turnos (33 vs 60), erro e cover validados.
- **Conditions (fase 72)**: barra no tabuleiro (⛓ CONTENÇÃO WPN-CNT, ✨ OFUSCADO WPN-FLA, ☣ ESPORO WPN-PRO, 🌿 RAIZ WPN-RAD) — ícone no peão, imobilização sem drag, evasão ×0.7 (RAIZ), ataque −4 (CONTENÇÃO) / −5 (OFUSCADO, consome-se), DoT 2/rodada via ⟳ Rodada, expiração por duração 3. Validado em harness DOM: dano, consumo, bloqueio de drag e tick de rodada.
- **Turnos + movimento (fase 73)**: iniciativa monta fila ordenada (⏭ Próximo, pula caídos), HUD "Rodada N — vez de X (mov Y/Z m)", anel dourado + ▼ no ativo; movimento = max(2, sp/4) m/rodada (PJ 6, NAT-01 4, vespa 14), drag do ativo debita custo e bloqueia sem saldo, wrap restaura movimento e dispara tick de condições. Validado em harness: ordem, débito exato, bloqueio e wrap.
- **Inventário do PJ (fase 74)**: catálogo de 29 itens (8 medicamentos, 10 equipamentos, 8 armaduras VST, 3 ferramentas do kit Varga) na ficha — mochila com peso, 💊 Usar em alvo do tabuleiro (CURATIVO cura 30% teto do baseline, ANTITOXINA/EQP-001 curam ESPORO, sem efeito não consome), 🛡 equipar armadura (+AR entra no CD do combate), 🗡 bainha de armas (empunhada restringe a lista de ataque), 🎒 Kit Varga inicial. Validado em harness: kit, cura com teto, cura de condição, AR no ref e restrição de armas.
- **Loja (fase 75)**: aba 🪙 com 20 moedas (Stavias + 19 territoriais c/ força), 19 estados de escassez, estoque por território (produzido nos ESTs locais + ambulantes), preço = tier base +1 moeda FRACA +1 cura em escassez BAIXA, tabela runtime BAIXO 10/MÉDIO 25/ALTO 60/MUITO_ALTO 150 (RUNTIME_ONLY, lei da economia), carteira em stavias, compra/venda 50%, 🤝 barganha CD12 −20% e 🔄 escambo mesmo-tier só no informal. Validado em harness: tiers, compra/venda/barganha/escambo e recusas por regra.
- **Reformulação visual (fase 76)**: neomorfismo em fundo ósseo (relevos suaves, sem bordas duras), títulos em serifada, cromo sem emojis com rótulos em linguagem simples (Personagem, Criaturas, Mestre), aba Início com passo a passo em 3 etapas + resumo da sessão + glossário, ferramentas do tabuleiro agrupadas (Peões/Turno/Cena/Mesa), ações principais em botão escuro, foco visível e respeito a reduced-motion. Lógica e dados intactos; smoke completo verde.
- **Reações (fase 77)**: lados grupo/hostil/neutro nos peões (ponto colorido, toggle, salvos), ataque de oportunidade automático ao sair de 2,75m de hostil — arma de contato, 1 por rodada, banda pré-movimento, derrubado pela reação cancela o movimento; reset no wrap, toggle mestre liga/desliga. Validado em harness: 39 de dano (100→61), consumo, wrap, neutro sem reação.
- **Encontros (fase 78)**: gerador no Mestre por território (13 registros de distribuição MASTER: CRI-001..013 com território; CRI-014+ ampla distribuição) × intensidade (Calmo 1 passivo / Típico grupo por grp SOLITARY..SWARM / Perigoso hostil +1) — carta com perfil do catálogo (disposição, gatilhos, saídas sem violência), envio do grupo ao tabuleiro com lado certo, e coleta de caídos (PASSIVO 5 / HOSTIL 15 st RUNTIME + vestígio, remove o peão). Validado em harness.
- **Batalha por turnos (fase 79)**: aba Batalha estilo Final Fantasy — fileiras de inimigos (toque para mirar) e do grupo, menu Atacar/Habilidade/Item/Defender/Fugir, 39 habilidades reais (4 ativas por classe: ímpeto/cura/investida/salto + passivas de regen/resistência) com SP e espera, IA inimiga (cura aliado ou ataca), vitória com coleta automática, derrota, fuga por d20. Defesa/ímpeto/passivas integrados ao motor de dano; tabuleiro sem números (minimalista); classes do PJ com nomes reais. Smoke de batalha completa verde.
- **Refação geral (fase 80)**: aba Combate removida (motor segue servindo Batalha e reações, sem depender de DOM), Criaturas virou NPCs, Batalha com setup próprio (Batalha rápida: PJ + N inimigos, ou do tabuleiro), Mapa em lista de territórios, Personagem com Apagar, mochila em 12 slots quadrados estilo Zelda (toque abre Usar/Equipar/Remover). Smoke total verde.
- **Ficha nova (fase 81)**: 5 abas (Início·Ficha·Mapa·Loja·NPCs·Mestre) — Tabuleiro/Batalha/Personagem e todo o JS de cena removidos. Ficha espelha a imagem: Topo (medalhão+nome/espécie/classe), 6 Atributos por classe (medianas das armas: ex. Androids TEC 66/MAG 5), Combate (PV base 28/30, CA=10+armadura, SP, Descansar), árvore de armas da classe por família (Comum ovr≤40 grátis; 25/60/150 st), Traços (4 ativas + passiva, cura usável), mochila com regra exata (usa some; só a maior amplia: 12→20→35→50; igual/menor bloqueia). Loja vende armas-da-classe + Kit Varga 25 st; Encontros removidos; NPCs só consulta. Smoke novo verde.
- **Reorganização (fase 82)**: Início em cartões de jornada clicáveis (Ficha em destaque + Loja/Mapa/NPCs/Mestre) com entrada escalonada; Ficha em 6 seções dobráveis animadas; Loja em 3 categorias (Estoque/Armas/Vender); NPCs com filtro Todos/Aliados/Criaturas; Mestre em acordeões; troca de aba com fade, cartões com hover físico, tudo sob reduced-motion. Smoke verde.

---

## Notas de governança

- Todo conteúdo aqui é **derivado** (`CANON_DERIVADO_ATIVO`/`GAMEPLAY_DERIVED_DEV_SOURCE`) — o cânone R2 confirmado em `01_LORE/CANON_R2/` nunca foi editado.
- Territórios TER-014 a TER-019 (6 novos) e todo o Atlas Continental (fase 53) foram criados por **decisão explícita do autor do projeto** — portão autoral de soberania, registrado em cada arquivo de território.
- Este índice foi gerado após uma validação cruzada completa (fase 54) que não encontrou pendências reais.
- Lacunas conhecidas e deixadas em aberto deliberadamente: cobertura de minerais usa 16 fixos do runtime (cada um com primário + secundários, sem MIN novo); perfil agrícola/mineral dos 6 novos foi resolvido na fase 56 (seção 7 acima).


## Extensão TER-020 — Nérion

- **Nérion — Região Autônoma dos Despertos**: Androids Conscientes, fundada após o despertar dos protótipos de Nicolar Alber e Serverus Vaelkor.
- Registro territorial:  1_LORE/CANON_DERIVADO_ATIVO/GEOGRAFIA/REGIAO_AUTONOMA_DE_NERION/TER-020_NERION_ANDROIDS_CONSCIENTES.json.
- Integrações: 5 subregiões, 7 localidades, 5 paisagens, 3 rotas e 3 quests.
- A Maga responsável pelo despertar permanece oculta; o registro é derivado e não promove fatos ao CANON_R2.

