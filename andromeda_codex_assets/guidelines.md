# Andromeda Codex — Guidelines de Assets Visuais

> Raiz: `andromeda_codex_assets/` | Versão: v02 (unificada) | Universo: Andromeda Codex / Stellar

Este documento define resoluções padrão, nomenclatura e tags tonais para todos os assets visuais do universo. Leitura obrigatória antes de gerar, exportar ou commitar qualquer arte.

Migração: `08_ASSETS_VISUAIS/` foi unificado aqui. Esta é agora a **única raiz canônica** de assets visuais.

---

## 1. Estrutura de Pastas

```
andromeda_codex_assets/
├── guidelines.md
├── 01_characters/
│   ├── protagonists/
│   │   └── [character_name]/
│   │       ├── model_sheets/       # Turnarounds (frente, perfil, costas)
│   │       ├── expressions/        # Caras e bocas (cômicas vs. épicas/sérias)
│   │       └── action_poses/       # Poses de batalha e silhueta
│   ├── antagonists/
│   │   └── [character_name]/
│   │       ├── model_sheets/
│   │       ├── expressions/
│   │       └── action_poses/
│   └── supporting_npcs/
│       └── [character_name]/
│           ├── model_sheets/
│           ├── expressions/
│           └── action_poses/
├── 02_worldbuilding_environments/
│   ├── planets_landscapes/         # Superfícies, ecossistemas e biomas
│   ├── cities_settlements/         # Arquitetura urbana, interiores e distritos
│   └── space_structures/           # Estações orbitais, megastruturas e fendas
├── 03_tech_and_vehicles/
│   ├── starships_fleets/           # Naves principais, caças e cargueiros
│   ├── mechs_combat_rigs/          # Armaduras pesadas e unidades robóticas
│   ├── weapons_arsenal/            # Armas brancas, armas energéticas e artefatos
│   └── gadgets_props/              # Dispositivos cotidianos, itens de sobrevivência
├── 04_factions_and_culture/
│   ├── emblems_insignia/           # Vetores, brasões de corporações e impérios
│   ├── uniforms_attire/            # Roupas civis, trajes espaciais e armaduras militares
│   └── typography_hud/             # Interfaces de bordo, hologramas e fontes
└── 05_marketing_and_promotional/
    ├── key_visuals_posters/        # Pôsteres verticais de temporada/capítulo
    ├── social_media_banners/       # Headers de X/Twitter, YouTube, Discord
    ├── merchandise_mockups/        # Estampas para vestuário, pins e colecionáveis
    └── lore_cards/                 # Fichas visuais estilizadas para divulgação
```

**Regras:**
- Nunca crie arquivos soltos na raiz ou em pasta de categoria. Todo asset vai na subpasta folha (`model_sheets/`, `planets_landscapes/`, `lore_cards/`, etc.).
- `guidelines.md` é o único arquivo permitido na raiz.
- Novo personagem = duplique `_TEMPLATE_character_name/` e renomeie para `[character_name]` em snake_case (ex: `kenua/`, `espinho_negro/`).
- Template disponível em `protagonists/`, `antagonists/` e `supporting_npcs/`.

---

## 2. Resoluções Padrão por Categoria

Todas as dimensões em pixels (L x A). Exportar sempre em 72 DPI para web e 300 DPI para print. Manter master editável (`.psd` / `.kra` / `.blend`) + export flat (`.png` / `.jpg`).

### 01_characters — Personagens
| Subpasta folha | Uso | Resolução base | Proporção | Formato |
|---|---|---|---|---|
| `model_sheets/` | Turnaround frente/perfil/costas | **2048 x 2048** (busto) ou **2160 x 3840** (full-body) | 1:1 ou 9:16 | PNG + fundo transparente |
| `expressions/` | Caras e bocas | **2048 x 2048** (sheet com grid) | 1:1 | PNG |
| `action_poses/` | Poses de batalha / silhueta | **2160 x 3840** | 9:16 | PNG + fundo transparente |

> Vale para `protagonists/`, `antagonists/` e `supporting_npcs/`. NPCs aceitam mínimo **1024 x 1024**.
> `model_sheets/` sempre com 3 vistas no master: frente / perfil / costas + 1 expression sheet em `expressions/`.

### 02_worldbuilding_environments — Worldbuilding
| Subpasta | Uso | Resolução base | Proporção | Formato |
|---|---|---|---|---|
| `planets_landscapes/` | Superfícies, biomas, ecossistemas | **3840 x 2160 (4K UHD)** | 16:9 | JPG 90% / PNG |
| `cities_settlements/` | Arquitetura, interiores, distritos | **3840 x 2160 (4K UHD)** | 16:9 | JPG 90% / PNG |
| `space_structures/` | Estações, megastruturas, fendas | **3840 x 2160 (4K UHD)**, versão vertical **2160 x 3840** se for key art mobile | 16:9 / 9:16 | PNG |

### 03_tech_and_vehicles — Tech
| Subpasta | Uso | Resolução base | Proporção | Formato |
|---|---|---|---|---|
| `starships_fleets/` | Naves, caças, cargueiros (3/4 + ortográficas) | **3840 x 2160** | 16:9 | PNG + master com wireframe |
| `mechs_combat_rigs/` | Armaduras, unidades robóticas | **3000 x 3000** | 1:1 | PNG |
| `weapons_arsenal/` | Brancas, energéticas, artefatos | **2048 x 2048** | 1:1 | PNG transparente |
| `gadgets_props/` | Dispositivos, sobrevivência | **2048 x 2048** | 1:1 | PNG transparente |

### 04_factions_and_culture — Facções e Cultura
| Subpasta | Uso | Resolução base | Proporção | Formato |
|---|---|---|---|---|
| `emblems_insignia/` | Brasões, vetores corporações/impérios | **SVG master** + export **2048 x 2048** PNG | 1:1 | SVG + PNG transparente |
| `uniforms_attire/` | Civis, espaciais, militares | **2048 x 2732** (retrato) | 3:4 | PNG |
| `typography_hud/` | Bordo, hologramas, fontes | **1920 x 1080** base + vetor | 16:9 | SVG + PNG |

### 05_marketing_and_promotional — Marketing
| Subpasta | Uso | Resolução base | Proporção | Formato |
|---|---|---|---|---|
| `key_visuals_posters/` | Pôsteres temporada/capítulo (verticais) | **3840 x 2160 (4K)** + print **4961 x 7016 (A1 @300dpi)** | 16:9 / A-series | PNG + PDF print |
| `social_media_banners/` | Headers X/YouTube/Discord | **1080 x 1080 (1:1 feed)** + **1080 x 1920 (9:16 stories)** + **1500 x 500 (header X)** + **1920 x 1080 (YT)** | 1:1 / 9:16 / 3:1 / 16:9 | JPG 85-90% / PNG |
| `merchandise_mockups/` | Vestuário, pins, colecionáveis | **3000 x 3000** | 1:1 | PNG / JPG |
| `lore_cards/` | Fichas visuais de divulgação | **1024 x 1792** (2.5" x 3.5" @300dpi + bleed) ou **1080 x 1920** digital | 5:7 / 9:16 | PNG |

**Resumo rápido:**
- Key Visuals: **4K (3840x2160)** mínimo.
- Social: sempre entregar o par **1:1 (1080x1080)** + **9:16 (1080x1920)**.
- Print: 300 DPI, CMYK convertido a partir do master RGB.

---

## 3. Regras de Nomenclatura de Arquivos

### 3.1 Padrão

```
[categoria]_[entidade]_[variacao]_vNN.png
```

- Tudo em `snake_case`, minúsculas, sem acentos, sem espaços.
- `categoria`: nome da subpasta folha (ex: `model_sheets`, `expressions`, `action_poses`, `planets_landscapes`, `starships_fleets`, `emblems_insignia`, `key_visuals_posters`).
- `entidade`: nome canônico da lore / pasta `[character_name]` (ex: `kenua`, `espinho_negro`, `stellar_prime`, `frota_aurora`).
- `variacao`: ângulo, traje, bioma ou uso (ex: `front`, `back`, `combat_armor`, `laughing`, `battle_stance`, `night`, `hero_shot`, `feed_1x1`, `stories_9x16`).
- `vNN`: versão com 2 dígitos, `v01`, `v02`... Nunca sobrescrever — sempre incrementar.
- Extensão em minúsculas: `.png`, `.jpg`, `.svg`, `.psd`, `.blend`.
- Path completo indica contexto: `01_characters/protagonists/kenua/model_sheets/model_sheets_kenua_front_v01.png`.

### 3.2 Exemplos válidos por subpasta

```
# characters
01_characters/protagonists/kenua/model_sheets/model_sheets_kenua_front_v01.png
01_characters/protagonists/kenua/expressions/expressions_kenua_laughing_v01.png
01_characters/protagonists/kenua/action_poses/action_poses_kenua_battle_stance_v02.png
01_characters/antagonists/espinho_negro/model_sheets/model_sheets_espinho_negro_back_v01.png

# worldbuilding / tech / culture / marketing
planets_landscapes_stellar_prime_night_v01.jpg
starships_fleets_aurora_hero_shot_v03.png
emblems_insignia_casa_veridian_gold_v01.svg
key_visuals_posters_temporada1_main_4k_v01.png
social_media_banners_temporada1_feed_1x1_v01.jpg
social_media_banners_temporada1_stories_9x16_v01.jpg
lore_cards_kenua_origens_v01.png
weapons_arsenal_lamina_pulsar_icon_v01.png
```

### 3.3 Regras duras

1. Máx. 80 caracteres no nome (sem extensão).
2. Sem `FINAL`, `novo`, `ultimo`, `fix2` — só `vNN`.
3. Master editável mantém o mesmo basename: `model_sheets_kenua_front_v01.psd` acompanha `model_sheets_kenua_front_v01.png`.
4. Sem caracteres especiais: só `a-z`, `0-9`, `_`, `-` (preferir `_`).
5. `v01` é sempre o primeiro commit de uma entidade/variação. Revisão = `v02+`.

---

## 4. Tags de Consistência Tonal

Toda entrega (arquivo + prompt de geração + PR/commit) deve carregar **uma e apenas uma** tag primária. Tag secundária é opcional com `+`.

| Tag | Nome | Quando usar | Paleta / Traço |
|---|---|---|---|
| `[COMIC]` | Quadrinho canônico | `model_sheets/`, `expressions/`, `action_poses/`, lore cards, social narrativo | Traço bold, cel-shaded, cores saturadas, halftone sutil. `expressions/` cômicas aqui |
| `[EPIC]` | Cinemático promocional | Key visuals, pôsteres, banners, matte paintings, `action_poses/` sérias | Luz volumétrica, 4K, bloom controlado, escala monumental |
| `[BLUEPRINT]` | Técnico / esquemático | Naves, mechs, armas, gadgets, HUD, uniformes, emblemas (versão técnica) | Fundo escuro + linhas cyan/âmbar, cotas, wireframe, grade |
| `[LORE]` | Arquivo / in-world | Mapas, documentos, insígnias heráldicas, mockups diegéticos, merchandise | Textura papel/metal, serifas, bordas ornamentais, envelhecimento leve |

### 4.1 Como aplicar

- **No nome do commit/PR:** `[EPIC] key_visuals_posters_temporada1_main_4k_v01`
- **No prompt de geração:** terminar com ` --tag [EPIC]` + descritores da tabela.
- **Na pasta:** não criar subpastas por tag. A tag vive no metadado, não no path.
- `expressions/`: marcar `cômica vs. épica/séria` no `variacao` (ex: `..._laughing_v01` = `[COMIC]`, `..._war_cry_v01` = `[EPIC]`).

Exemplo de prompt:

```
matte painting do porto orbital de Stellar Prime ao pôr-do-sol duplo,
frota Aurora em formação, escala monumental, luz volumétrica --tag [EPIC]
```

### 4.2 Combinações permitidas

- `[EPIC+LORE]`: pôster com moldura de documento in-world.
- `[COMIC+LORE]`: lore card narrado.
- `[BLUEPRINT+LORE]`: esquemático com selo de facção.
- Proibido: `[COMIC+EPIC]` no mesmo asset (escolher um como primário).

---

## 5. Checklist de Entrega

- [ ] Arquivo na subpasta folha correta (`model_sheets/` vs `expressions/` vs `action_poses/`, etc.)?
- [ ] Resolução e proporção conforme §2?
- [ ] Nome no padrão `[categoria]_[entidade]_[variacao]_vNN.ext`?
- [ ] Pasta `[character_name]` em snake_case (sem colchetes no disco)?
- [ ] Tag tonal única aplicada no commit/prompt?
- [ ] Master editável + export flat entregues?
- [ ] Sem texto com erro ortográfico em PT-BR (HUD/lore cards revisados)?

_Versão unificada v02 — `andromeda_codex_assets/` é a raiz única. Dúvidas de lore prevalecem: `01_LORE/` é fonte da verdade._
