# Stage 16B — B02 — Registro de implementação V0.8.0

Data: 2026-08-20 (America/Sao_Paulo)

## Resultado

A B02 foi implementada exclusivamente em `07_GODOT_ARPG_STAGE16B` e está fechada
como PASS para seu escopo aplicável: Main, Player, câmera isométrica, click-to-move,
colisão e Navigation placeholder. O gate final passou com 90/90 checks no Godot
4.7.1 headless e via Andrômeda Editor Bridge, sem warning ou erro final.

Não foi iniciada a B03.

## Autoridades e áreas preservadas

- Master V2.0.1: read-only; hash conferido
  `6D9AC3CCE7DCF6A65FDCF73859C332A0211C1AF52D149077BEEF554BF7BBD0B2`.
- Stage16A V0.8.0: 724/724 arquivos byte-idênticos ao checkpoint.
- `06_GODOT_LIVING_V1_5`: não editado.
- B01: scripts/cenas re-hashados sem divergência; regressão 54/54 nos dois modos.
- `project.godot`: evolução cumulativa necessária para a B02; o registro histórico
  B01 não foi reescrito.
- GDScript: somente input, cena, física, Navigation, câmera e apresentação local.

## Implementação

### Main e mundo placeholder

`scenes/Main.tscn` contém a topologia contratual:

- `RuntimeBridge`;
- `WorldStreamRoot` com `VisualSurface`, `CollisionSurface` e `TraversalSurface`;
- `ActorRoot`;
- `GroundLootRoot`;
- `EffectsRoot`;
- `IsometricCameraRig`;
- `UILayer`.

O mundo usa apenas geometria placeholder. A malha de navegação manual tem oito
células caminháveis ao redor de um bloqueio central. A margem da área não caminhável
mantém a cápsula afastada da colisão durante o desvio.

### Player e Navigation

O Player é um `CharacterBody3D` com origem nos pés, cápsula visual/física deslocada
localmente, `NavigationAgent3D`, anchors e Hurtbox desabilitada. Destinos são
validados pelo `NavigationServer3D`:

- projeção maior que `0,75 m` é rejeitada;
- path vazio/incompleto é rejeitado;
- destino válido substitui imediatamente o anterior;
- chegada zera a velocidade horizontal e encerra a previsão;
- nenhum resultado autoritativo de gameplay é calculado.

Quando há sessão B01 ativa, `MOVE_TO_POINT` gera apenas um envelope
`session_ref/command/params`, sem `player_ref`. O gate não chama `submit_command`.

### Input

`InputRouter` preserva os contratos Stage16A:

- esquerdo/direito no chão: `MOVE_TO_POINT`;
- esquerdo em alvo: `SELECT_TARGET`, `movement_change: NONE`;
- Ground Loot: `PICKUP` a `<= 0,5 m`, senão `APPROACH_PICKUP` se alcançável;
- direito hostil: `CHASE_ATTACK` marcado `FUTURE`;
- direito NPC/objeto: `APPROACH_INTERACT` marcado `FUTURE`;
- roda sem modificador: ciclo entre exatamente dois quick-slots;
- modificador + roda: zoom;
- menu aberto + roda: scroll apenas.

Combate, interação contextual, pickup autoritativo e quick-slot gameplay não foram
implementados nesta B02.

### Câmera

A câmera usa yaw fixo `45°`, pitch `55°`, distância `14 m`, clamps `11–18 m`,
half-life `0,18 s`, deadband vertical `0,12 m` e sem free orbit. O raycast de
oclusão está preparado entre câmera e follow target com alpha contratual `0,2`.
O fade de material ainda não é executado; por isso G16B-14 permanece parcial.

## Ciclos, anomalias e correções

1. Durante a criação de diretórios, um path duplicado criou somente diretórios
   vazios em uma árvore aninhada acidental. O alvo absoluto foi inspecionado,
   confirmado vazio e removido antes da implementação de arquivos; nenhuma baseline
   foi tocada.
2. A primeira importação encontrou `get_world_3d()` chamado por `Main`, cujo root é
   `Node`. O resultado foi invalidado. A consulta passou a usar o `World3D` do
   Player; nova importação ficou limpa.
3. O primeiro gate funcional passou 69/80. O Player estava centrado `0,9 m` acima da
   NavigationMesh, mantendo o agente preso ao primeiro path point e gerando passos
   alternados. A origem do `CharacterBody3D` foi movida aos pés e cápsula/visual
   receberam offset local.
4. O segundo gate passou 75/82. O `NavigationServer3D` disponibilizava iteration id
   antes de responder com os polígonos. `navigation_ready()` passou a exigir um
   closest-point probe real na célula de spawn.
5. O gate passou 82/82 headless e repetiu 82/82, mas a primeira execução pelo Editor
   Bridge emitiu warning de inteiro atribuído a enum `MouseButton`. Esse resultado
   foi invalidado; o helper recebeu cast explícito e ambos os modos foram reiniciados.
6. A matriz exigia clique físico em Ground Loot. O gate inicial cobria o resolvedor,
   mas não o raycast real do placeholder. Foram adicionados raycast, verificação de
   `APPROACH_PICKUP` e troca do destino. O gate passou 84/84 nos dois modos.
7. A primeira tentativa de regressão Python recebeu incorretamente o ZIP do
   checkpoint como `ANDROMEDA_MASTER_RELEASE`. O runtime rejeitou o hash; a execução
   parcial de 147 testes/7 erros foi invalidada. O Master V2.0.1 correto foi localizado,
   seu hash foi conferido e todos os 209 testes foram reiniciados.
8. A auditoria documental final encontrou aliases locais `pointer_primary` e
   `pointer_context` no InputMap, em vez dos nomes contratuais `pointer_left` e
   `pointer_right`. Os nomes foram alinhados, seis checks de entry point/InputMap
   foram adicionados e B02, Main e B01 foram reexecutadas nos modos aplicáveis.

## Evidências finais

- B02 headless: 90/90 PASS; exit code 0; log limpo.
- B02 Editor Bridge: 90/90 PASS; `errors: []`; stop final limpo.
- `Main.tscn` direta no Editor Bridge: startup e stop limpos.
- B01 headless: 54/54 PASS.
- B01 Editor Bridge: 54/54 PASS; `errors: []`.
- Stage16A: 209/209 PASS em 260,760 s.
- Stage16A stress: 20/20 PASS.
- Integridade: 724/724, zero mismatch.
- Endpoint `127.0.0.1:8000`: sem listener, não contado como PASS.

## Acceptance Matrix atualizada

- G16B-01: PASS preservado/revalidado.
- G16B-02: PASS.
- G16B-14: `PARTIAL_EVIDENCE_B02_NOT_PASS`; falta executar fade de material de
  oclusores.
- G16B-20: `PARTIAL_EVIDENCE_B02_NOT_FINAL`; regressões deste checkpoint passaram,
  mas o gate final permanece para B11.
- G16B-03..13, G16B-15..19 e G16B-21..28: NOT_RUN.

Stage16 completa: não. Backup final: não autorizado/não criado. B03: não iniciada.

## Watch items

- O round-trip autoritativo de `MOVE_TO_POINT` depende do backend real em
  `127.0.0.1:8000`; ele não estava disponível e não foi substituído.
- A superfície B02 é placeholder determinístico; a integração B04 deve preservar a
  separação visual/collision/traversal e repetir path, colisão e jitter.
- O fade real de oclusores ainda é necessário antes de G16B-14 PASS.
- Right-click hostil/contextual permanece somente roteado como intenção futura; não
  constitui G16B-03.
