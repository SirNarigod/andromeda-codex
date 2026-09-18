# Auditoria "Sistema Nervoso" — Andrômeda

Pedido: depois de corrigir as 3 conexões faltantes, mapear o motor inteiro como uma corrente sanguínea/rede neural — onde a informação flui, e onde ela **deveria** fluir mas não flui.

## Atualização 6 — as 4 pendências fechadas (16/09)

**1. `REQUEST_PLACE_PIECE`**: primeiro comando de jogador pra `construction_placement_system.py` (nunca tinha nenhum). Delega 100% a `place_piece()` já protegido; após sucesso, chama `apply_construction_material_cost()` (pronta desde o lote anterior) pra debitar o material da economia regional de verdade. 6 testes novos (`test_stage17_authority_place_piece.py`), incluindo confirmação de que o material realmente é descontado (`material_cost.status == PASS`).

**2. NPCs registrados no `agent_brain`**: `register_npc_as_agent_participant`/`register_block_npcs_as_agents` em `system_causal_bridges.py` — espelham cada NPC do `country_scale.py` como entidade genérica `AGENT` + participante do orquestrador, idempotente (nunca duplica). Ligado no `_boot()`: o bloco inicial do jogador já registra seus NPCs automaticamente. **Confirmado ao vivo**: 64 NPCs registrados no boot, **63 decisões reais de IA** (`agent_decisions`) gravadas em 1 segundo de tick de fundo rodando. O ecossistema deixou de estar vazio.

**3. `ConsequenceEngine` ganhou peso por relação**: novo campo opcional `weight_from_relation_metadata` no template de consequência — lê um peso do `metadata` da relação casada (ex.: `register_relation(..., metadata={"weight": 0.8})`) e multiplica o valor vindo do evento por esse peso, POR ALVO. Antes, todo alvo sob uma regra recebia o mesmo valor fixo — exatamente o que impedia expressar "cada facção reage proporcional à própria influência" como regra declarativa. Mudança pequena e aditiva (achei o ponto exato: `_materialize_templates` já recebia a relação casada no loop, só faltava usar); 100% compatível com regras antigas (peso ausente = 1.0, comportamento idêntico a antes). 3 testes novos provando isso ponta a ponta, incluindo 2 alvos recebendo valores DIFERENTES de uma mesma regra. As pontes (`system_causal_bridges.py`) continuam como funções compostas — a capacidade agora existe no motor, migrar é decisão futura, não fiz hoje.

**4. Issue aberta**: [`ISSUE_WATER_PRECISION_TESTS_TOO_TIGHT_V1_0.md`](04_REPORTS/ISSUE_WATER_PRECISION_TESTS_TOO_TIGHT_V1_0.md) — documenta os 2 testes de precisão de água, achado, causa provável, correção sugerida (não implementada).

Regressão ampla (travessia, ground loot, skill, combate, coleta, construção): **66/66 OK**.

---

## Atualização 5 — motor de tick reimplementado como thread de fundo (decisão do usuário)

Substituí a versão inline (que causou a regressão) por uma **thread daemon dedicada** (`_orchestrator_tick_loop`), como pedido:

- Acorda a cada `ORCHESTRATOR_TICK_INTERVAL_S` (10s reais em produção) e roda **exatamente 1 tick** por território registrado — nunca rajada de N ticks, que era a causa raiz da regressão anterior.
- Usa o **mesmo `self._lock`** (RLock) que já serializa todo comando/snapshot/troca de território do adapter — não inventei trava nova, reaproveitei a que já protegia tudo. Isso garante que um tick nunca roda ao mesmo tempo que um comando ou uma troca de território mexendo no mesmo motor.
- `close()` agora sinaliza parada e dá `join()` na thread **antes** de fechar qualquer conexão de motor — testado ao vivo: thread realmente para (`is_alive() == False`), fechamento limpo em 37ms.
- Cada território tem seu próprio motor/relógio, então a thread itera todos os registrados — territórios que o jogador não está visitando continuam vivos (ecologia, etc.), não só o ativo.

**Testado ao vivo** (não só teoria): relógio do mundo avançou sozinho de tick 0→2 em 1 segundo real (intervalo reduzido pra 0.2s só no teste manual), thread confirmada daemon e viva, `close()` derruba ela de verdade.

Subconjunto de regressão (travessia multi-território, combate, coleta, skill, ground loot): **60/60 OK**. Thread de fundo confirmada segura em uso real.

---

## Atualização 4 — o motor de tick foi ligado (pedido: "sistema de ticks em tudo que muda em tempo real")

Achado que muda tudo: existe um `WorldSimulationOrchestrator` **completo** (`01_RUNTIME/world_orchestrator.py`) — ecologia, decisão de NPC (`agent_brain.decide()`), projeção social, drenagem de consequências, tudo em fases, com sistema de extensões prontas pra plugar mais coisa. `IntegratedLivingEngineV11.create_world()` já monta e configura ele inteiro. **Só que nada no adapter nunca chamava `run_tick()`** — o mundo inteiro ficava congelado, só mudando quando o jogador mandava um comando direto.

**Ligado agora**: `_advance_world_orchestrator_ticks()` em `andromeda_authority_adapter.py`, chamado a cada `snapshot()` — mesmo padrão do relógio de água (`_advance_authoritative_water_clock`), pausado por tempo real (1 tick a cada 10s reais, até 12 ticks de "catch-up" por chamada, pra nunca travar um snapshot se o servidor ficou muito tempo sem ser consultado). Testado ao vivo: relógio do mundo avançou de tick 0 pra 8 sozinho entre duas chamadas de snapshot.

**O que isso ativa de verdade agora**: ecologia (fauna/flora evoluindo), decisão autônoma de NPC via `agent_brain.decide()` (pra quem já está registrado como participante — ver gap abaixo), projeção social, e a drenagem de eventos pendentes do `ConsequenceEngine` (que agora tem função de verdade, mesmo sem regras registradas em produção ainda).

**Gap que sobra, honesto**: `_phase_npc` só processa NPCs que foram registrados como "participante" do orchestrador (`register_participant`) — e os NPCs gerados por `country_scale.py` nunca foram registrados assim (vivem só como JSON dentro do bloco, nunca viraram entidade genérica `AGENT`). Ligar o motor de tick não cria NPCs pensantes sozinho — só ativa o motor que, quando alimentado, os faria pensar. Ponte de população (`country_scale` NPC → entidade `AGENT` + `register_participant`) é o próximo passo real, não feito ainda.

**Regressão real encontrada e corrigida**: a suíte completa (306 testes) apontou 4 testes de precisão de água (`test_stage16b_authority_dev_water_time.py`, `test_stage16b_authority_save_death_water.py`) falhando por 0.076-0.137s de diferença. Causa raiz real: quando o mundo fica muito tempo sem receber um `snapshot()`, meu código tentava "recuperar o atraso" rodando até 12 ticks de uma vez — cada tick faz trabalho de verdade (grava no banco, roda ecologia), e isso consumiu tempo real de parede suficiente pra vazar nos testes que exigem precisão de milissegundos no relógio de água (que mede tempo real do mesmo jeito).

**Corrigido**: removi a chamada automática de dentro do `snapshot()`. O método `_advance_world_orchestrator_ticks()` continua pronto, testado e funcional isoladamente (confirmei ao vivo antes: relógio do mundo avança de verdade) — só não dispara mais sozinho. Ligar de forma 100% segura exige um dos dois: (a) rodar os ticks numa thread de fundo, fora do caminho de qualquer requisição (correto architeturalmente, trabalho novo real — cuidado com lock de escrita do SQLite/thread-safety); (b) manter inline mas com orçamento de tempo estrito por chamada, aceitando que uma requisição que "pegar" um tick pronto paga um custo pequeno e previsível. Nenhuma das duas feita ainda — decisão de arquitetura que prefiro te consultar antes de implementar, dado que já causou uma regressão real uma vez.

2 dos testes que falharam na suíte completa são ambientais pré-existentes (checkpoint zip ausente nesta máquina, achado antigo desta sessão, não relacionado).

**Correção da minha própria conclusão**: 2 testes (`test_09_ground_loot_899...`, `test_11_water_bag_1799...`) continuaram falhando com ~0.07-0.12s de diferença **mesmo depois de reverter a chamada do tick e com a máquina sem carga** (testei isolado, 2 vezes). Isso prova que **não fui eu** — é um problema pré-existente: esses testes exigem precisão de 0,00001s (`places=5`) num round-trip real de save/reload em disco, o que é uma tolerância frágil por natureza em qualquer máquina, independente do meu código. Não investiguei a fundo (fora do escopo desta rodada, achado incidental) — mas registro aqui pra não ficar parecendo que "sumiu" silenciosamente.

**Sem git neste projeto**, não dá pra confirmar 100% que isso já falhava antes de qualquer coisa desta sessão inteira (não só de hoje) — mas a evidência (mesma magnitude de erro com e sem meu código) aponta fortemente pra "sempre foi assim, dependendo da máquina".

---

## Atualização 3 — os 3 itens de esforço alto

**Correção sobre #6 (migrar as pontes pro `ConsequenceEngine`)**: o motor de regras só faz `SET`/`INCREMENT`/`DECREMENT` direto num campo — não tem como expressar "peso pela influência da facção" nem os outros cálculos que nossas pontes fazem. Migrar de verdade perderia a lógica. **Não fiz isso** — seria fingir uma correção. Ficam como funções compostas (padrão já usado o jogo todo), que é o jeito certo dado o que o motor de regras sabe fazer hoje.

**#8 NPC ganha `faction_ref`** (decisão sua: só WARRIOR/MERCENARY): `assign_npc_faction_membership()` em `system_causal_bridges.py` — nos territórios com facção presente, sorteia deterministicamente (hash do id do NPC, não `random` — rodar 2x dá o mesmo resultado) ponderado pela influência de cada facção. NPCs de outras classes ganham `faction_ref: None` explícito. 3 testes.

**#7 Percepção → IA**: achado real que muda a pergunta — nem `PerceptionSystem` nem `AgentBrain` são instanciados em produção **de jeito nenhum** hoje. A hostilidade em `REQUEST_ATTACK` é 100% disposição estática (`arpg_actor_core.hostility_to_profile`), sem nenhuma simulação de IA rodando. `perceive_and_record_for_agent()` liga os dois sistemas corretamente (roda o cheque geométrico de visão/audição e alimenta `AgentBrain.record_perception()` só quando percebeu de verdade) — mas não tem loop de tick de NPC pra chamar isso ainda. É infraestrutura maior faltando, não um gap de dados como os anteriores. 2 testes.

21/21 testes passando no total (`test_system_causal_bridges.py`).

**O que fica pendente de verdade, sem fingir**: nenhuma das 3 pontes deste lote está ligada ao vivo no jogo — todas dependem de infraestrutura que ainda não existe em produção (motor de regras sem cálculo ponderado, construção sem comando de jogador, IA/percepção sem tick loop). Diferente dos lotes anteriores, aqui não tinha "fio solto" pra plugar; tinha sistema inteiro nunca ligado.

---

## Atualização 2 — segundo lote (skill + construção)

4. **Skill → economia**: `learn_skill` agora cobra ouro ANTES de ensinar (nunca depois — o core não tem "desaprender", então checar depois deixaria skill de graça se a cobrança falhasse). Custo escala pelo tier de riqueza do território (território pobre = treino mais caro, `base_cost / multiplier`). **Ligado ao vivo** em `_request_learn_skill`. Corrigi de quebra um teste de regressão real que sofreu (fixture não tinha saldo pra 6 learns seguidos — ajustei o fixture, não a lógica).
5. **Construção → economia regional**: mapeei os 5 materiais do catálogo (`MIN-IRON→METAL`, `MIN-STONE→STONE`, `MIN-CRYSTAL`/`RUNA-003→MAGIC_MINERAL`, `MAT-001` madeira → flora mais abundante do bloco, já que flora não tem campo `kind`). **Não ligado ao vivo** — achado real: `ConstructionPlacementSystem` nunca é instanciado no adapter, construção não é comando de jogador em produção ainda. Função pronta e testada pra quando isso mudar.

16 testes novos neste lote (`test_system_causal_bridges.py` agora com 16 testes no total), zero regressão real (1 teste precisou de fixture ajustado, não de lógica corrigida).

---

## Atualização 1 — lote de esforço baixo/médio concluído

Ordenei as 8 ausências por esforço e fechei as 3 primeiras juntas (mesmo schema, mesmo padrão):

1. **Vendor ↔ corrupção**: `vendor_wealth_economy.py` ganhou tabela nova `v17_vendor_price_pressure` (aditiva, não toca a tabela/hash existente) + `apply_price_pressure()`/`state()` agora expõe `effective_wallet_cap`. `corruption_vendor_price_multiplier()` já pronta agora tem onde aplicar de verdade — provado por teste real (`test_corruption_pressure_shrinks_effective_cap`).
2. **Vendor ↔ água/clima**: nova `climate_vendor_price_multiplier()` em `system_causal_bridges.py`, usando `rainfall_mm_y`/`humidity_pct` que `country_scale.py` já gera (nada inventado). Composição com corrupção testada junta (`test_climate_and_corruption_pressures_compose`).
3. **Morte do jogador → reação social**: `apply_player_death_social_reaction()` espelha a ponte de kill, mas com sinal invertido (facção fica mais confiante, não com raiva). Testado (`test_death_raises_reputation_instead_of_lowering_it`).

10/10 testes novos passando (`03_TESTS/test_system_causal_bridges.py`), 16/16 testes antigos de `vendor_wealth_economy` sem regressão.

**O que ficou de fora deste lote, honestamente**: as 2 funções de vendor (corrupção/clima) ainda não são chamadas automaticamente por nenhum tick do jogo — ficaram prontas, testadas, e com onde persistir (`apply_price_pressure`), mas falta decidir e implementar QUANDO recalcular (a cada snapshot? a cada tick de corrupção?). A morte do jogador também não tem gatilho automático ainda — hoje a morte é só *projetada* no snapshot (`_death_recovery_projection`), não existe um evento único "player morreu agora" pra disparar a reação; precisaria de detecção de borda (vivo→morto) que não construí ainda.

---

## Conexões corrigidas nesta rodada

Novo arquivo: [`system_causal_bridges.py`](01_RUNTIME/system_causal_bridges.py) (6 testes, todos reais, `03_TESTS/test_system_causal_bridges.py`), + 2 pontos ligados de verdade no `andromeda_authority_adapter.py`:

| # | Ação | Reação | Ligado ao vivo? |
|---|---|---|---|
| 1 | `REQUEST_ATTACK` mata um alvo hostil | toda facção **presente** no território do jogador perde reputação, ponderado pela influência da facção ali | **Sim** — `_request_attack`, campo `faction_reaction` na resposta |
| 2 | `REQUEST_GATHER` completa uma coleta | a macro-economia regional (`country_scale.py`, `mine()`) é debitada no mesmo recurso por **tipo** (mineral/flora/etc.) | **Sim** — `_request_gather`, campo `regional_stock_reaction` na resposta |
| 3 | Corrupção de uma subregião | multiplicador de pressão de preço pro vendor daquele território | **Não** — função pronta e testada (`corruption_vendor_price_multiplier`), mas não fiada em nenhum vendor de verdade ainda (ver gap abaixo) |

Ambas as ligações ao vivo são **best-effort**: envoltas em `try/except`, nunca derrubam o comando principal (matar/coletar sempre funciona mesmo se a reação falhar). Rodei os testes de combate/coleta/travessia existentes depois da mudança — zero regressão confirmada em `test_stage17_authority_cross_territory_travel` e `test_stage16b_authority_ground_loot` (16/16); `test_stage16b_authority_combat`/`test_stage16b_authority_gathering`/`test_stage17_resource_metric_gather` rodando em segundo plano no momento em que este documento foi escrito.

**Por que a #3 não amarrou de vez**: `vendor_wealth_economy.py` só tem `wallet_cap` fixo por território (calculado 1x em `register_vendor`); não tem noção de "preço" por item nem um gancho pra recalcular o teto quando a corrupção muda no meio do jogo, sem re-executar `register_vendor` (que não é idempotente pra isso). Fiar isso direito precisa de um campo novo (`corruption_multiplier`) persistido junto do tier — mudança de schema pequena, mas real, não fiz agora pra não arriscar sem terminar de validar.

---

## Mapa de fluxo — o que já é "corrente sanguínea" de verdade

```
Jogador
  ├─WASD/comando──▶ Movement/Combat/Gathering/Skill (autoridade real)
  │                     │
  │                     ├─▶ Inventário/Wallet (direto, síncrono)
  │                     ├─▶ ConsequenceEngine (existe, TESTADO, mas 0 regras em produção)
  │                     └─▶ system_causal_bridges (NOVO — kill→facção, gather→região)
  │
  ├─travessia─────▶ PlanetSystem / cross_territory_transfer (perfil segue o jogador)
  │
  └─corrupção (tick autônomo)─▶ root_corruption_system ─▶ fauna_territorial_migration
                                                        └─▶ (agora também) preço de vendor [função pronta, não fiada]
```

## Ausências reais encontradas (por sistema, não suposição — cada uma checada no código)

### 1. Vendor não reage a NADA além do próprio território fixo
`vendor_wealth_economy.py` não escuta corrupção (função pronta, não ligada), não escuta guerra/facção, não escuta escassez regional (a conexão #2 nova alimenta `country_scale`, mas nada lê isso de volta pro preço do vendor). É uma extremidade "surda" da rede.

### 2. NPCs não têm facção própria, só território
Confirmado ao investigar a conexão #1: não existe `faction_ref` por NPC em lugar nenhum (`agent_brain.py`, `arpg_narrative_culture_core.py`) — só presença territorial agregada (`WorldSystems`). Isso significa que **todo** sistema de reputação/facção no jogo hoje só pode reagir por território, nunca "você matou um membro específico da Guilda X". Se a intenção de design é ter facções com membros individuais reconhecíveis, essa é a lacuna estrutural raiz — não dá pra corrigir com uma bridge, precisa de uma decisão de schema (NPC ganha `faction_ref` na criação).

### 3. `ConsequenceEngine` é um órgão sem nervos ligados
Confirmado na rodada anterior: motor completo, testado, **zero regras registradas em produção**. As pontes que criei hoje (e as 4 de sessões passadas) são todas "cabos soltos" ponto-a-ponto, não declarativas. Continua sendo a maior peça de infraestrutura pronta e não usada do projeto.

### 4. Percepção/projétil/distância de combate existem mas não se enxergam
Do relatório de arquitetura original: `perception_system.py`, `projectile_system.py`, `combat_distance_states.py` são "Stage17 isoladas" — rodam, têm teste, mas `arpg_combat_core.py` (o combate de verdade) só usa `combat_distance_states`. Percepção (visão/audição de NPC) nunca alimenta decisão de combate ou de IA (`agent_brain.py`) — um NPC pode "não perceber" o jogador e ainda assim reagir, ou perceber e não reagir, sem ligação confirmada.

### 5. Skill não afeta economia nem combate além do próprio dano
`arpg_skill_core.py` está isolado: aprender/usar skill não altera preço de vendor (skills raras deveriam ser mais caras de treinar em territórios pobres?), não altera reputação, não altera stamina de forma cruzada com `arpg_water_bag_survival_core.py` além do que já é nativo.

### 6. Clima/água não afeta economia
`arpg_water_bag_survival_core.py` (sobrevivência) e `water_volume` nunca disparam nada em `vendor_wealth_economy`/`arpg_economy_crafting_core` — um território com escassez de água deveria pressionar preço de comida/água no vendor, e não pressiona.

### 7. Construção (`construction_placement_system.py`) não consome economia regional
Peças colocadas no mundo não descontam de `country_scale` industries/resources — o sistema de construção e a macroeconomia territorial são ilhas completas uma da outra.

### 8. Morte do jogador não афeta nada fora de si mesmo
`death_respawn_client.gd`/`arpg_save_recovery_core.py` cuidam só do próprio jogador. Não há reação social (NPCs comentando, facção ganhando confiança por "fraqueza" do jogador) — capturado só como estado local.

## Prioridade sugerida (impacto de jogo vs. esforço), não implementado

| Prioridade | Ausência | Esforço estimado |
|---|---|---|
| Alta | #1 corrupção→vendor (função já pronta, só falta o schema+fiação) | Pequeno |
| Alta | #3 migrar as 6 pontes existentes (4 antigas + 2 novas) pro `ConsequenceEngine` como regras reais | Médio |
| Média | #6 água/clima→preço | Pequeno |
| Média | #4 percepção→decisão de combate/IA | Médio-Grande |
| Baixa (decisão de design primeiro) | #2 NPC ganhar `faction_ref` próprio | Grande, mexe em schema central |

## Verificação
- As 3 conexões corrigidas: 6/6 testes novos passando, mais 16/16 testes de regressão pré-existentes (travessia + ground loot) confirmados após a mudança.
- Cada ausência listada acima foi confirmada por grep/leitura direta do arquivo citado nesta sessão ou nas anteriores desta mesma auditoria — nenhuma é suposição sobre o que "provavelmente" falta.
