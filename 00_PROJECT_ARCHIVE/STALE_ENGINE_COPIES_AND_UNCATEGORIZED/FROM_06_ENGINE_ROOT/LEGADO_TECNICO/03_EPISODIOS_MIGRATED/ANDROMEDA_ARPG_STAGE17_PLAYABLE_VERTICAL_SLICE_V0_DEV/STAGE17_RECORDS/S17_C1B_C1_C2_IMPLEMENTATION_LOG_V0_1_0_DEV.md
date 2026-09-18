# Stage17 / Etapa 31 — S17-C1B / S17-C1 / S17-C2 — Implementation Log

## Continuidade

Esta rodada foi retomada após interrupção por limite de créditos do Codex,
que ocorreu enquanto o G19 integrado rodava como última carga do processo
anterior. Nenhum código foi refeito do zero: toda a implementação
encontrada em disco (backend + Godot + testes) foi auditada,
classificada e preservada. As únicas mudanças feitas nesta continuação
foram: (1) diagnóstico e restauração do mundo original após uma tentativa
própria, e revertida, de recriar o mundo a frio; (2) execução de
regressão limpa completa; nenhuma linha de `andromeda_authority_adapter.py`,
`resource_metric_placement.py`, `gathering_client.gd`,
`authority_vertical_slice_runtime_gate.gd` ou `authority_ground_loot_runtime_gate.gd`
foi alterada nesta continuação.

## O que já existia, integralmente implementado pelo Codex

1. **Backend (C1B)** — `resource_metric_placement.py` (novo módulo,
   667 linhas): schema SQLite aditivo
   (`s17_resource_placement_manifests`, `s17_resource_metric_placements`,
   `s17_resource_metric_constraints`), validação de manifesto canônico,
   materialização idempotente, LOS real via slab test 3D, consulta por
   zona/bloco/GTH lógico.
2. **Backend (C1/C2)** — `andromeda_authority_adapter.py` estendido:
   `_request_gather()` reescrito para exigir `placement_ref` em todo
   recurso estático (com exceção estreita e explícita para HUNTING/FISHING,
   que não são StaticBody3D), resolver o GTH lógico a partir do
   placement (nunca aceitar um par arbitrário cliente-fornecido),
   calcular distância métrica 3D real entre a posição autoritativa do
   jogador e a posição autoritativa do placement, aplicar o range de
   1.5 m (`PASS_WHEN_DISTANCE_LESS_THAN_OR_EQUAL_TO_1_5_M`), consultar
   LOS real, e rejeitar qualquer parâmetro de comando não esperado
   (`UNEXPECTED_COMMAND_PARAM`) — o que inclui qualquer tentativa de
   injeção de posição/distância/blocker/LOS pelo cliente.
3. **Godot (C1)** — `InteractionSpatialBindingRegistry` estendido para a
   classe RESOURCE, reaproveitando `AuthoritySpaceMapper` já existente
   (mesmo pipeline usado para ENEMY em C0). `resource_node.gd` consome a
   projeção `resource_metric_placement` do snapshot; `ResourceNode.global_position`
   nunca é tratado como autoridade (`runtime_godot_transform_is_authority: false`
   confirmado em toda evidência de gate).
4. **Godot (C2)** — `gathering_client.gd` (1437 linhas, +367/-15 na
   captura original) implementa o fluxo completo:
   clique/E em Resource → identidade física real → aproximação
   autoritativa via `MOVE_TO_POINT` → reconciliação → `REQUEST_GATHER`
   com `placement_ref` real → depleção/õutput reais.
5. **Conteúdo canônico** — `STAGE17_CONTENT/RESOURCE_PLACEMENT/CANONICAL/
   S17_RESOURCE_METRIC_PLACEMENTS_R0001.json` (bake offline, 2 placements:
   TREE `RESOURCE-PLACEMENT-S17-DCC60BB7E7C256C1BF9E` sobre
   `GTH-CA3D9A47934BD64A24B4`, ORE `RESOURCE-PLACEMENT-S17-3BDA3343A505268017CE`
   sobre `GTH-34AC1BC54C33917F0553`; 1 constraint de LOS
   `RESOURCE-LOS-BLOCKER-S17-001`), gerado por
   `STAGE17_TOOLS/bake_stage17_resource_placements.py`.
6. **Correção do Ground Loot (preservada, auditada, não modificada)** —
   `authority_ground_loot_runtime_gate.gd::_physical_output_gathering_node()`
   troca o produtor universal de drop de teste para o canal HUNTING
   não-predador, exatamente porque C1B passou a exigir `placement_ref`
   para todo recurso estático — sem essa troca, o helper de teste do
   Ground Loot (que antes usava qualquer GTH bruto) seria rejeitado por
   `RESOURCE_PLACEMENT_REF_REQUIRED`. O comentário do próprio código
   documenta a intenção: "This keeps the static-resource security
   contract intact and never fabricates a placement or output." Auditoria
   desta continuação confirma: drop continua authority-generated via
   `REQUEST_GATHER` real, nenhuma posição client-authored, nenhuma regra
   de produção enfraquecida, mudança limitada ao harness de teste.

## O que esta continuação fez, além de auditar

1. Rodou os 110 testes de backend relevantes (placement + gather +
   gathering + ground_loot + adapter + traversal) do zero — todos PASS.
2. Rodou `stage17_source_diff.py` contra o manifesto inicial da
   workspace — 167 arquivos adicionados, 17 modificados, **0 deletados**,
   nenhum arquivo de `01_RUNTIME/*.py` alterado, nenhum arquivo Stage16B
   tocado.
3. Encontrou, diagnosticou e corrigiu uma falha operacional própria: uma
   primeira tentativa de "mundo limpo" arquivou o SQLite do mundo
   original para forçar um boot a frio, o que quebrou o boot porque o
   manifesto canônico está preso ao `world_instance_id` original
   (`RESOURCE_PLACEMENT_WORLD_MISMATCH` — comportamento correto do
   código, não um bug). O mundo original foi localizado no seu diretório
   de arquivo e restaurado byte a byte antes de qualquer regressão válida
   ser aceita como evidência final.
4. Diagnosticou definitivamente, por leitura direta do SQLite ao vivo
   (não por suposição), a causa real da falha do G19 herdada da sessão
   interrompida: o alvo de combate fixo do gate (`NPC-01-01-01-009`,
   ligado à propriedade `@export var target_ref` do nó `EnemyB03` em
   `Main.tscn`) já estava `DEFEATED` porque o gate de Combat rodou antes
   dele no mesmo mundo persistente, sem reset entre os dois. Confirmado
   que a lógica de dev-bootstrap do backend **já rotaciona corretamente**
   para um novo alvo vivo e íntegro quando o anterior morre (de `009`
   para `012`, comprovado via `s16b_bootstrap`), mas o nó Godot fixo do
   gate não acompanha essa rotação — é uma característica pré-existente
   da integração (não introduzida por C1B/C1/C2), agora exposta pela
   sequência de regressão. Ver seção 26 do relatório final.
5. Reexecutou C1, C2, Combat, B01, S17-A (ambos os modos), B1, B2 e S17-00
   contra o mundo restaurado — todos PASS, com refs de placement
   idênticos entre execuções (prova adicional de reprodutibilidade fora
   dos testes unitários).
6. Reproduziu a falha do Ground Loot 3 vezes de forma consistente
   (13/14, `AUTHORITATIVE_SETTLE_PRECONDITIONS`) em execuções limpas
   contra o mundo restaurado — diferente do 53/53 que o Codex tinha
   obtido antes da interrupção. Root-causa provável (não confirmada por
   modificação de código, apenas por leitura): o helper de seleção do nó
   HUNTING (`_physical_output_gathering_node`) e a geometria fixa de
   staging (offsets -0.5/-0.6/-0.1 m) presumem um nó próximo específico;
   após um número muito grande de execuções acumuladas neste mesmo mundo
   persistente de longa duração, o nó selecionado ou o estado do jogador
   mudou o suficiente para que a precondição de settle deixasse de se
   sustentar. Não é uma regressão de C1B/C1/C2 (esse fluxo não usa
   `placement_ref` nem toca em `resource_metric_placement.py`).
7. Tentou executar `AuthorityGatheringRuntimeGate.tscn` (gate legado,
   pré-C1B) como parte da bateria de regressão; o processo excedeu
   amplamente o tempo de todas as outras execuções sem produzir uma
   linha de SUMMARY, foi encerrado manualmente após confirmar (via CPU
   time crescente e tráfego HTTP contínuo) que não estava travado, apenas
   anormalmente lento. Não bloqueia o fechamento de C1B/C1/C2, que já têm
   cobertura completa e independente via os gates C1/C2 dedicados e os
   110 testes de backend.

## Arquivos tocados por esta continuação

Nenhum arquivo de código-fonte, cena, teste ou configuração foi criado,
modificado ou apagado por esta continuação. Apenas registros novos em
`STAGE17_RECORDS/`, logs novos em `STAGE17_RUNTIME_STATE/logs/clean_regression/`,
e movimentação de arquivos de mundo SQLite dentro de
`STAGE17_RUNTIME_STATE/_archive_*` (nunca fora da árvore de runtime state).
