# Andrômeda Códex

> Fonte canônica do universo **Stellar/Andrômeda**: worldbuilding, regras do mundo, Temporada 1, mecânicas de gameplay e motor de simulação determinístico.

O **Andrômeda Códex** é o repositório central de conteúdo do universo Stellar/Andrômeda — lore canônica, leis fundamentais, roteiro de episódios, mecânicas do sistema MAR (Magia, Armas e Runas) e motor de simulação em Python/SQLite, com integração para Godot, Unity e UE5. Inclui ainda o **Andromeda Mesa**, RPG de mesa digital jogável no navegador.

**Conteúdo:** 20 territórios, 65 subregiões, 68 localidades, 68 construções, 80 armas, 32 criaturas, 40 NPCs de combate + 33 civis, 16 profissões, 21 quests dinâmicas, economia completa (minerais, crafting, alimentos, munição, runas, veículos, medicina, vestuário), flora, calendário, rotas e atlas continental.

## Onde começar

- **[Códice navegável (wiki)](https://claude.ai/code/artifact/af28a6a4-a910-494f-a790-7a431ca57230)** — a forma mais fácil de explorar todo o conteúdo (territórios, criaturas, classes, itens, sistemas). Gerado a partir dos JSONs abaixo; atualizado após cada rodada de conteúdo.
- **[STELLAR_MASTER_INDEX_DEV_V1_0.md](STELLAR_MASTER_INDEX_DEV_V1_0.md)** — índice de navegação vivo, mantido à mão, com links diretos para os principais arquivos de lore.

## Estrutura

| Pasta | Conteúdo |
|---|---|
| `01_LORE/` | Cânone (`CANON_R2` = confirmado/imutável, `CANON_MASTER_V2` = catálogo ampliado importado, `CANON_DERIVADO_ATIVO` = conteúdo derivado/gameplay ativo), fundamentos (`STELLAR_FOUNDATION`), geografia, ecologia, cosmologia |
| `02_REGRAS/` | Leis fundamentais do mundo (economia, ecologia, magia-tecnologia, soberania, etc.) |
| `03_EPISODIOS/` | Roteiro da Temporada 1 (Kenua, cânone R2) |
| `04_MECANICAS/` | Mecânicas de gameplay: sistema MAR, criaturas, itens/armas, NPCs, economia, profissões, quests, construção, progressão do jogador |
| `05_CRIACAO_PROCEDURAL/` | Docs de autoria/mapas/atlas para geração procedural |
| `06_ENGINE/` | Motor de simulação Python real (SQLite, determinístico). `06_ENGINE\G\ACTIVE_STAGE17_WORKSPACE\...` é a **única árvore de motor ativa/viva** — todo código novo vai lá, nunca em cópia solta |
| `07_AUTOMATION/` | Ferramentas de import/export/validação + `EXPORTS/MESA/andromeda-mesa.html` (RPG de mesa web standalone) |
| `andromeda_codex_assets/` | Assets visuais canônicos (única raiz): `00_image_ai\` (envio p/ IA: `input_references/`, `prompts/`, `output_raw/`), `01_characters\` (por personagem: `model_sheets/`, `expressions/`, `action_poses/`), `02_worldbuilding_environments\`, `03_tech_and_vehicles\`, `04_factions_and_culture\`, `05_marketing_and_promotional\`. Regras em `andromeda_codex_assets\guidelines.md` (resoluções, nomenclatura `[categoria]_[entidade]_[variacao]_vNN`, tags `[COMIC]/[EPIC]/[BLUEPRINT]/[LORE]`) |
| `00_PROJECT_ARCHIVE/` | Material histórico/superado (cópias obsoletas confirmadas, relatórios de build antigos) — seguro ignorar no dia a dia; ver `ARCHIVE_MANIFEST.json` dentro dela para o que foi movido e por quê |

## Motor de simulação e integração multi-engine

O backend de autoridade HTTP+JSON (`06_ENGINE\G\ACTIVE_STAGE17_WORKSPACE\...\12_AUTHORITY_BACKEND_STAGE17\stage16b_authority_api.py`) já foi testado de ponta a ponta (boot real, comando executado, idempotência confirmada) e é o ponto de integração para as 3 engines-alvo. Ver `..\README.md` e os READMEs de `..\09_GODOT_WORKSPACE\` / `..\10_UNITY_WORKSPACE\` / `..\08_UE5_WORKSPACE\` para detalhes.

## Andromeda Mesa

RPG de mesa digital standalone em `07_AUTOMATION/EXPORTS/MESA/andromeda-mesa.html` + `mesa-data.js`: mapa esquemático dos 20 territórios, tabuleiro tático, fichas das 5 classes, bestiário, NPCs, quests, dados, névoa e save local. Basta abrir o HTML no navegador — tutorial = Contrato de Travessia de Varga.

## Convenções

- Todo conteúdo novo segue o padrão já estabelecido: JSON com `authority`/`safety` explícitos, sem informação de arquivo/pasta/build interna vazando para o Códice.
- Assets visuais: única raiz `andromeda_codex_assets\`. Novo personagem = duplicar `_TEMPLATE_character_name\`. Todo asset nasce em `00_image_ai\` e só vai para `01_`–`05_` após aprovação, no padrão `guidelines.md`.
- Nenhuma pasta solta de motor (`ANDROMEDA_ARPG_*`) deve existir fora de `06_ENGINE\G\ACTIVE_STAGE17_WORKSPACE\` — se aparecer uma, é resíduo de import e deve ser investigada antes de arquivada (ver método em `00_PROJECT_ARCHIVE\ARCHIVE_MANIFEST.json`).
- Cânone R2 nunca é editado — todo conteúdo novo de gameplay é `CANON_DERIVADO_ATIVO`.
