# Stage17 / Etapa 31 — S17-C3R3 Gathering Mutable Capacity Contract + Formal Migration Architecture

Rodada 100% read-only / design técnico. Zero mutação, zero `resume_world()`,
zero engine mutável construído, zero migration executada, zero backend
iniciado. Prova por hash ao final. Nenhum código-fonte protegido foi editado
— apenas lido.

## 1. Mapeamento exato da definição (`arpg_gathering_work_core.py`)

Lido integralmente (535 linhas). Divisão dos campos de `_node_definition()`
(linha 184-208):

| Campo | Classe | Justificativa |
|---|---|---|
| `node_ref` | **A. Imutável** | `sha256(seed|activity|block_ref|source_kind|source_ref)[:20]` — função pura dos outros campos imutáveis |
| `world_instance_id` | **A. Imutável** | identidade do mundo |
| `country_ref` | **A. Imutável** | constante `"TER-011"` |
| `zone_ref` / `block_ref` | **A. Imutável** | posição estrutural, nunca reatribuída |
| `activity_type` | **A. Imutável** | fixado na primeira classificação da fonte |
| `source_kind` | **A. Imutável** | `MINERAL`/`FLORA`/`FAUNA`/`FISHING` |
| `source_ref` | **A. Imutável** | id do registro country-scale |
| `output_item_ref` | **A. Imutável** | item de saída fixo |
| `renewability` | **C. Derivado** | função pura de `source_kind` |
| `canonical_context_support_refs`/`_scope` | **C. Derivado** | função pura de `activity_type` |
| `art_dependency`, `authority` | **A. Imutável** | literais constantes |
| `source_meta.*` (species_ref/role/tier/name/kind) | **B. Mutável-mas-estável** | lido da fonte country-scale; na prática nunca muda pós-genesis (tier/name/role são atribuídos uma vez) |
| **`capacity_units`** | **B. Mutável por gameplay (ÚNICA classe FAUNA)** / **A. Imutável na prática (MINERAL/FLORA/FISHING)** | ver Seção 7 |
| `definition_hash` | **D. Hash/provenance** | consequência, não causa |

`_insert_node()` (210-224): recompута e compara hash a cada boot; **não
distingue** entre drift estrutural real e drift de valor de capacidade — é
um único guard binário.

`_bootstrap_nodes()` (226-250): chamado do `__init__`, itera
`world.list_zones()` → `country.block()` → resources → flora → fauna →
fishing, chamando `_insert_node()` para cada. **Aborta inteiro no primeiro
drift encontrado** (não é resiliente a múltiplos).

`_consume_source()` (414-423): autoridade correta e legítima que decrementa
o country-scale ao vivo — `remaining_units` para MINERAL/FLORA, `count`
para FAUNA, estado de runtime separado (`arpg_gathering_runtime_state`)
para FISHING.

`verify()` (515-534): via `_definition_row`/`list_nodes`, apenas confere
auto-consistência do hash já persistido (`sha256(definition_json) ==
definition_hash`) — **não** detecta drift-vs-fonte-viva; esse check só
acontece em `_insert_node()` durante bootstrap.

## 2. Achado estrutural decisivo (novo nesta rodada): a exposição NÃO é uniforme entre classes

Lendo `country_scale.py` integralmente (genesis + mutação), descobri que o
modelo de dados do country-scale **já separa capacidade máxima de
quantidade atual para MINERAL e FLORA, mas NÃO para FAUNA**:

| Fonte | Campo lido por `_node_definition` como "capacity" | Campo mutado por `_consume_source`/`country_scale` gameplay | Mesmo campo? |
|---|---|---|---|
| MINERAL | `resource["capacity_units"]` (linha 231) | `resource["remaining_units"]` (`country_scale.py:682-687`, `arpg_gathering_work_core.py:420`) | **NÃO** — campos distintos |
| FLORA | `flora["capacity_units"]` (linha 239) | `flora["remaining_units"]` (`country_scale.py:697-701`, `arpg_gathering_work_core.py:420`) | **NÃO** — campos distintos |
| FAUNA | `fauna["count"]` (linha 243) | `fauna["count"]` (`country_scale.py:716-720`, `arpg_gathering_work_core.py:421`) | **SIM — mesmo campo** |
| FISHING | fórmula determinística `80 + stable_float(seed,zone_ref,"FISH_CAP")*121` (linha 246), **sem leitura de fonte viva alguma** | `arpg_gathering_runtime_state.remaining_units`, tabela separada (`_set_fishing_remaining`) | Não aplicável — nunca lê o country-scale para capacidade |

`country_scale.py` só escreve `capacity_units` de MINERAL/FLORA no
**momento da geração** (genesis, linhas 215-221/318/330/428) e nunca mais
depois — confirmado por leitura completa do arquivo (nenhuma outra
ocorrência de atribuição a `capacity_units` fora da geração). MINERAL e
FLORA também persistem seu insumo de geração (`density`/`abundance`), o
que lhes dá proveniência estável e reconstruível.

FAUNA (`_fauna()`, linha 431-450) **não persiste `abundance` nem
`climate_factor`** — apenas o resultado final `count` é gravado. Isso
significa que, para FAUNA, **não existe hoje nenhum campo estável de
"capacidade máxima original"** independente da própria contagem mutável —
diferente de MINERAL/FLORA, que têm essa separação por design.

**Conclusão provada por código, não suposta**: o risco de drift está
estruturalmente confinado à classe FAUNA/HUNTING. MINERAL e FLORA já são
protegidos hoje pelo próprio modelo de dados existente (o gathering core lê
corretamente o campo estável, não o mutável). FISHING é imune por
construção (não lê fonte viva nenhuma para capacidade).

## 3. Matriz completa ACTIVITY × SOURCE_KIND

| ACTIVITY | SOURCE_KIND | CAPACITY_SOURCE | MUTABLE? | DRIFT_RISK | ALREADY_OBSERVED |
|---|---|---|---|---|---|
| MINING | MINERAL | `resource.capacity_units` | NÃO (campo dedicado, só genesis) | **NENHUM** | Não |
| LOGGING | FLORA | `flora.capacity_units` | NÃO (campo dedicado, só genesis) | **NENHUM** | Não |
| AGRICULTURE | FLORA | `flora.capacity_units` | NÃO (campo dedicado, só genesis) | **NENHUM** | Não |
| FORAGING | FLORA | `flora.capacity_units` | NÃO (campo dedicado, só genesis) | **NENHUM** | Não |
| HUNTING | FAUNA | `fauna.count` | **SIM — mesmo campo consumido por hunt** | **ALTO** | **SIM (1 de 87 nodes)** |
| FISHING | FISHING (sintético) | fórmula determinística, sem fonte viva | Não aplicável | **NENHUM** | Não |

## 4. Scan read-only de todos os gathering nodes persistidos

Executado via conexão `mode=ro&immutable=1`, sem construir engine, sem
`resume_world()`. Script reimplementa (não importa) o algoritmo exato de
`_node_definition`+`canonical_json`+`sha256_text`, verificado linha-a-linha
contra o core protegido nesta mesma rodada.

```
TOTAL_NODES: 312
MATCHING:    311
DRIFTED:     1
SOURCE_MISSING: 0

drift_by_activity:
  MINING: 0/166   LOGGING: 0/14   AGRICULTURE: 0/14
  FORAGING: 0/28  FISHING: 0/3    HUNTING: 1/87

drift_by_source_kind:
  MINERAL: 0/166  FLORA: 0/56  FISHING: 0/3  FAUNA: 1/87
```

Único node drifted: `GTH-1D268772796B25C4CC6B` (HUNTING/FAUNA,
`FAU-BROWSER-05-04-01`), campo único divergente `capacity_units` (86
persistido vs 58 esperado) — idêntico ao achado da S17-C3R2, agora
confirmado como o **único** caso em todo o mundo, não uma amostra de uma
classe maior ainda não descoberta.

Prova de zero mutação desta rodada:

```
before: c84d1bdaaf6de4cf3e47c3f12c4fce0e217090ebe1d15a759bc09f89b68921c6 / 15060992 bytes
after:  c84d1bdaaf6de4cf3e47c3f12c4fce0e217090ebe1d15a759bc09f89b68921c6 / 15060992 bytes
wal/shm antes e depois: ausentes
```

`country_scale_state.payload_json` auto-consistente (hash bate) — a fonte
usada para recomputar as 312 definições não está corrompida.

## 5. Semântica real de `capacity_units`

Não é uma escolha nominal — a leitura completa dos três usos prova que o
contrato **pretendido** é **D: snapshot da quantidade da fonte no momento
da criação do node** (não A-inicial-com-histórico-preservado, não
B-máximo-com-teto-formal, não C-disponível-corrente-com-atualização-viva).
Prova: `_node_definition` sempre lê o valor **atual** da fonte no instante
do bootstrap, nunca um campo `original_capacity`/`max_capacity` dedicado, e
nunca é chamado de novo fora do bootstrap para "atualizar" nada.

A consequência desse contrato D depende inteiramente de **quão estável** é
o campo lido em cada `source_kind`:

- Para MINERAL/FLORA: o campo lido (`capacity_units`) é, por acidente
  arquitetural feliz, o mesmo campo estável dos dois usados pelo restante
  do sistema como teto fixo — então o contrato D funciona corretamente e
  para sempre, sem nunca colidir.
- Para FAUNA: o campo lido (`count`) é o único campo existente, e é
  exatamente o campo que `_consume_source` (legitimamente) decrementa — o
  contrato D colide com a própria semântica de "quantidade atual" da
  população, porque não existe um campo "quantidade atual" separado de
  "capacidade".

**Fonte de verdade recomendada pós-correção**: `country_scale_state` já é
e deve continuar sendo a autoridade de fauna population count (linha 17 —
Living Ecology, ver Seção 6). O contrato do Gathering deve deixar de tratar
o snapshot inicial de `count` como identidade imutável para fontes
`renewability == "LIVING_ECOLOGY_STAGE14"`, e passar a tratá-lo como uma
leitura projetada (derived view) do estado vivo — sem duplicar
autoridade.

## 6. Relação com Living

O problema nasce inteiramente dentro de `country_scale.py`
(`LIVING_ECOLOGY_STAGE14`), que já é e permanece a autoridade da população
agregada de fauna (`fauna.count`). **Não é necessário alterar Living/
country_scale.py.** O gap está inteiramente do lado de consumo
(`arpg_gathering_work_core.py` tratando um valor observado como se fosse
propriedade estrutural própria). A correção Stage17 deve consumir/observar
esse valor sem duplicá-lo como definição travada por hash — exatamente como
o próprio `node()` (linha 265-278) já faz para `remaining_units` em tempo
de leitura (ele NUNCA usa o `capacity_units` do hash para saber quanto
resta; ele relê a fonte viva a cada chamada). O bug está isolado à
comparação de hash no bootstrap, não ao runtime de leitura normal.

## 7. Quatro arquiteturas avaliadas

**OPTION A — Stage17 gathering compatibility wrapper/subclass.**
Nova classe Stage17-only (ex.
`12_AUTHORITY_BACKEND_STAGE17/stage17_gathering_capacity_contract.py`,
`class Stage17ARPGGatheringWorkCore(ARPGGatheringWorkCore)`), sobrescrevendo
apenas `_insert_node()`: quando o hash diverge, recomputa o diff
campo-a-campo (mesma técnica desta auditoria); se **e somente se** o único
campo divergente for `capacity_units` **e** `renewability ==
"LIVING_ECOLOGY_STAGE14"` **e** a fonte viva ainda existir e for
resolúvel, re-persiste a definição atualizada (mesmo `_payload()`) em vez
de levantar `IntegrityError`; qualquer outro diff continua levantando o
erro original, inalterado. Nenhuma edição de `01_RUNTIME`. Métodos
privados de mesmo nome são normalmente sobrepostos em Python (não há
name-mangling em atributos de underscore simples) — tecnicamente limpo.
**Resolve a causa raiz permanentemente** (Seção 12 satisfeita: todo boot
futuro se autocorrige).

**OPTION B — Stage17 versioned gathering core fork completo.**
Cópia integral do arquivo (~535 linhas) sob um novo nome Stage17, com a
mesma correção escrita diretamente no lugar de `_insert_node`. Evita
qualquer acoplamento a mudanças futuras da classe-base, mas cria
duplicação total de ~500 linhas que precisam ser mantidas manualmente em
sincronia para sempre — viola o princípio de não-duplicação de autoridade
de forma mais séria que A. **Não recomendada** frente a A, que atinge o
mesmo resultado com uma sobreposição cirúrgica de um único método.

**OPTION C — Stage17 pre-bootstrap normalization/migration layer (isolada).**
Um passo Stage17 que, antes de qualquer `ARPGGatheringWorkCore()` ser
construído, re-sincroniza diretamente as linhas já drifted em
`arpg_gathering_nodes` para o valor atual, usando a lógica canônica
existente. **Insuficiente sozinha**: resolve o drift passado, mas não o
futuro — o próximo hunt bem-sucedido reintroduz exatamente a mesma colisão
no boot seguinte, violando o requisito de não-recorrência da Seção 12.
Só é aceitável como o **passo de migração formal de dados** (Seção 18),
nunca como a arquitetura completa — precisa ser combinada com A (ou B) para
cobrir o futuro.

**OPTION D — Stage17 schema/version migration + adapter-level compatibility.**
Adicionar uma tabela Stage17-only paralela para expor "capacidade
atual/disponível" a consumidores futuros como uma view derivada,
independente do hash de definição imutável, com uma tag formal de versão
de contrato (`S17_GATHERING_NODE_DEFINITION_SCHEMA_V2`). Corretamente
separa identidade de estado (Seção 6 do pedido), mas **por si só não
impede o `IntegrityError` de disparar no boot** — precisa de A (ou C) como
mecanismo companheiro para de fato parar o guard de levantar o erro. Não é
uma alternativa independente e sim um refinamento formal que se combina
com A.

## 8. Contrato Stage17 recomendado

**A (subclasse/wrapper) como mecanismo permanente + uma migração formal
única (variante de C, mas com escopo estritamente de backfill, nunca como
hook per-boot) para colocar o node já drifted em conformidade com o novo
contrato antes mesmo de A precisar agir de novo** + uma tag de versão
formal de contrato (espírito de D) registrada por linha migrada.

Nomeado: **`S17_GATHERING_NODE_DEFINITION_SCHEMA_V2`** (contrato); versão
anterior implícita e nunca formalmente nomeada até agora é
`V1`/`LEGACY_UNVERSIONED`.

### Por que não "apenas atualizar o hash a cada boot" (proibido pela Seção 13)

A sobreposição de A é **condicional e restrita**, não um "recompute e
sobrescreva sempre": ela só aceita re-sincronizar quando (1) o diff é
exatamente `{capacity_units}`, mais nenhum outro campo, e (2)
`renewability == LIVING_ECOLOGY_STAGE14`. Qualquer mudança em
`source_ref`, `activity_type`, `output_item_ref`, `zone_ref`/`block_ref`,
`schema`/campos canônicos continua levantando `IntegrityError` exatamente
como hoje — **o guard de integridade estrutural é 100% preservado**
(Seção 14). O que muda é que "capacidade populacional mutável" deixa de
ser tratada como parte da identidade estrutural — ela nunca foi, pela
própria definição do jogo.

## 9. Node identity — preservada

`node_ref` nunca é regenerado (é função pura dos campos estruturais, que
nunca mudam sob esta correção). `GTH-1D268772796B25C4CC6B` continuaria
sendo exatamente `GTH-1D268772796B25C4CC6B` após qualquer migração ou
correção — apenas seu `capacity_units` interno seria atualizado.

## 10. Depleção / Country source — quem é dono de quê após a correção

| Campo | Dono após correção Stage17 |
|---|---|
| `country_scale_state.fauna[].count` | Living/country_scale — autoridade única, inalterada |
| `arpg_gathering_nodes.definition_json.capacity_units` (fonte FAUNA/FLORA/FISHING) | deixa de ser "identidade fixa"; passa a ser um snapshot re-sincronizável, nunca escrito por gameplay diretamente — só por bootstrap/migration |
| `arpg_gathering_nodes.definition_json.capacity_units` (fonte MINERAL/FLORA) | permanece igual — já correto, sem mudança de comportamento |
| runtime `remaining_units`/`node()["remaining_units"]` | inalterado — já sempre lido ao vivo da fonte, nunca do hash |

Nenhuma duplicação de autoridade nova é introduzida — a leitura viva
(`node()`) já não usava o valor hash-travado para "remaining", só o
bootstrap comparava.

## 11. Migração formal do world existente (design, não implementada)

- **ID**: `S17_GATHERING_NODE_MUTABLE_CAPACITY_MIGRATION_V1`
- **Contrato alvo**: `S17_GATHERING_NODE_DEFINITION_SCHEMA_V2`
- **Escopo**: todas as linhas de `arpg_gathering_nodes` do `world_instance_id`
  ativo cujo diff recomputado (mesmo algoritmo desta auditoria, mas
  importando `living_runtime.canonical_json`/`sha256_text` diretamente
  para paridade byte-exata, não uma reimplementação) seja exatamente
  `{capacity_units}` e `renewability=="LIVING_ECOLOGY_STAGE14"`.
- **Genérica por construção**: nenhum `node_ref`/valor numérico
  hardcoded — a query é "para toda linha, recompute e compare"; hoje
  resolve exatamente 1 linha (`GTH-1D268772796B25C4CC6B`), mas se aplica
  igualmente às outras 86 FAUNA e às 56 FLORA/3 FISHING existentes sem
  qualquer código condicional por node_ref.
- **Abort condition**: se QUALQUER linha tiver diff fora do allow-list
  (`{capacity_units}` apenas), a migração inteira aborta sem escrever
  nada — nenhuma linha parcialmente migrada.
- **Preserva**: `node_ref`, `source_ref`, `zone_ref`/`block_ref`,
  `arpg_gathering_runtime_state` (tabela separada, não tocada),
  `country_scale_state` (não tocada — é a fonte, não o alvo).
- **Storage do registro de migração aplicada**: nova tabela Stage17-only
  aditiva, nunca antes existente no schema (confirmado por scan: nenhuma
  tabela de migration/governance/schema_version existe hoje nas 172
  tabelas do DB):
  ```sql
  CREATE TABLE IF NOT EXISTS stage17_gathering_migrations(
    migration_id TEXT NOT NULL,
    world_instance_id TEXT NOT NULL,
    schema_target TEXT NOT NULL,
    applied_at_utc TEXT NOT NULL,
    node_refs_json TEXT NOT NULL,
    before_definition_json TEXT NOT NULL,
    after_definition_json TEXT NOT NULL,
    audit_record_path TEXT NOT NULL,
    PRIMARY KEY(world_instance_id, migration_id)
  );
  ```
  `PRIMARY KEY(world_instance_id, migration_id)` impede reaplicação
  silenciosa a nível de banco (não apenas por convenção) — uma segunda
  tentativa da mesma migração no mesmo mundo falha na inserção.
  `before_definition_json`/`after_definition_json` guardam o snapshot
  completo por node_ref migrado, habilitando rollback direcionado (restaurar
  exatamente essas linhas ao valor anterior) sem precisar de um restore de
  backup inteiro.
- **SQL policy**: não existe hoje nenhuma API pública em
  `ARPGGatheringWorkCore` para atualizar um node já inserido (`_insert_node`
  só insere-ou-valida, nunca atualiza). Não há, portanto, API pública
  cobrindo esta operação. Sob a política desta rodada (Seção 22), um
  UPDATE SQL transacional controlado — apenas nas colunas
  `definition_json`/`definition_hash` de `arpg_gathering_nodes`, com schema
  conhecido, precedido de backup obrigatório, dentro de uma transação,
  seguido de verificação pós-migração (re-hash + re-scan idêntico ao desta
  rodada confirmando `DRIFTED: 0`) e registro de auditoria — é classificado
  **ACEITÁVEL como migração formal versionada**, distinto de SQL ad-hoc
  (que permanece proibido). Não executado nesta rodada.
- **Idempotência**: garantida em dois níveis — chave primária da nova
  tabela de migração, e o próprio cálculo (recomputar sobre um node já
  sincronizado produz diff vazio, portanto um segundo run é naturalmente
  um no-op mesmo sem checar a tabela de migração).
- **Rollback**: restaurar `definition_json`/`definition_hash` dos
  `node_refs_json` afetados a partir de `before_definition_json` — não
  requer reverter o world inteiro.

## 12. Gates obrigatórios para implementação futura (projetados, não executados)

A. bootstrap com contrato V1 (hoje) → aplicar migration V1 → boot novo com
subclasse Stage17 → `verify()` PASS.
B. `list_nodes()` completo (312 nodes) → todos `remaining_units>=0`,
nenhuma exceção.
C. gather HUNTING real → `count` country-scale diminui → reboot → **sem**
`IntegrityError`.
D-I. shutdown/restart repetido duas vezes consecutivas, cada uma com um
gather real intercalado → `verify()` PASS em ambas.
J. teste negativo obrigatório: mutação estrutural artificial
(`source_ref` ou `activity_type` diferente, isolado em ambiente de teste,
nunca no world real) → `_insert_node` **deve continuar levantando**
`IntegrityError` — prova de que o guard estrutural não foi enfraquecido.

## 13. Comparação formal: migrar mundo atual vs. novo mundo DEV

| CRITÉRIO | MIGRATE_CURRENT_WORLD | NEW_CLEAN_DEV_WORLD |
|---|---|---|
| Root-cause safety | Igual — ambos dependem da MESMA correção de contrato (A) sendo implementada; sem ela, um mundo novo sofre o mesmo drift assim que houver HUNTING suficiente | Igual |
| Complexidade de implementação | Baixa — 1 migração formal, escopo de 1 node hoje (312 comparados, apenas 1 requer ação) | Alta — novo `world_instance_id`, novo bake do manifesto canônico de placement, novos `placement_ref` |
| Risco | Baixo — blast radius provado por scan completo (1/312) | Médio — reintroduz toda a superfície de risco de bootstrap já vista nesta sessão (cold-boot world incidents documentados em `S17_C1B_C1_C2_INVALIDATED_RUNS`) |
| Auditabilidade | Alta — migração formal, tabela dedicada, hash antes/depois, este mesmo scan já serve de baseline | Alta, mas exige nova cadeia de evidência do zero |
| Preservação C1B/C1/C2 | **Comprovada nesta rodada**: scan mostra 0/166 MINERAL e 0/56 FLORA drifted — migração nunca tocaria TREE/ORE | Precisa recriar TREE/ORE do zero — nova prova completa necessária |
| Necessidade de player recovery | Sim, depois da migração — ferramenta já pronta (`S17_C3R1`, PASS) | Não — posição nasce correta no world novo, mas a ferramenta hardenizada fica ociosa |
| Contaminação de alvo COMMON | Persiste, mas é **gap separado e já documentado**, independente da escolha | Persiste igualmente (é um gap de lógica do adapter, não do world) |
| Resource placement | Manifesto canônico atual (`S17_RESOURCE_METRIC_PLACEMENTS_R0001.json`) continua válido, `world_binding.world_instance_id` já bate | Requer rebake completo do manifesto para o novo `world_instance_id` |
| Reprodutibilidade de testes | Alta — C1B/C1/C2/GroundLoot/G19 já rodados neste exato world | Zero — tudo precisa ser re-executado |
| Desenvolvimento futuro do Stage17 | Continua no mesmo world, sem interrupção de fluxo | Reinicia o histórico de evidência do zero |
| Custo de tempo | Baixo (1 migração + regressão dirigida) | Alto (rebake + re-verificação completa de C1B/C1/C2/GroundLoot/G19) |

## 14. Recomendação final

**A. STAGE17_VERSIONED_GATHERING_CONTRACT + MIGRATE_CURRENT_WORLD.**

Justificativa: o scan completo desta rodada prova que a contaminação
alegada na Seção 24 do pedido (fauna/NPCs consumidos, drift) tem um
**blast radius medido e pequeno** — exatamente 1 node de 312 — e que
TREE/ORE (a base de C1B/C1/C2) estão comprovadamente intactos (0 drift em
MINERAL e FLORA). Um world novo não eliminaria o player displacement, o
esgotamento do pool COMMON local, nem o histórico de reparo de ownership —
esses são problemas de posição/alvo já com solução dedicada e independente
(ferramenta de recovery já hardenizada, gap COMMON já documentado). Um
world novo, além de não resolver nada disso automaticamente, custaria um
rebake completo do manifesto canônico e uma re-verificação total de
C1B/C1/C2/GroundLoot/G19 — sem nenhum ganho de segurança adicional, já que
a MESMA correção de contrato (Option A) seria necessária em ambos os
casos para prevenir recorrência futura. Migrar o mundo atual é
estritamente mais barato, mais bem evidenciado e igualmente seguro.

## 15. Integridade protegida — confirmada

`01_RUNTIME` (Stage17): lido, **não editado**. Stage16A: não tocado.
Stage16B: `CLOSED / READ_ONLY`, inalterado. Master/Living baseline: não
tocado. Nenhuma escrita no DB nesta rodada (prova por hash, Seção 4).

## 16. Status

`S17_C3R3_GATHERING_MUTABLE_CAPACITY_CONTRACT_DESIGN = COMPLETE`
`S17_C3R3_IMPLEMENTATION = NOT_STARTED`
