# Stage 16B — B03 — Registro de implementação V0.8.0

Data: 2026-08-20 (America/Sao_Paulo)

## Resultado

A camada local aplicável da B03 foi implementada exclusivamente em
`07_GODOT_ARPG_STAGE16B` e fechou em PASS: 357/357 checks headless e 357/357 via
Andrômeda Editor Bridge, com debugger final limpo. A cena principal também iniciou e
parou diretamente pelo bridge sem erros ou warnings.

Nenhuma autoridade de gameplay foi adicionada a GDScript. A B04 não foi iniciada.

## Autoridades e baseline preservadas

- Master V2.0.1: read-only, SHA-256
  `6D9AC3CCE7DCF6A65FDCF73859C332A0211C1AF52D149077BEEF554BF7BBD0B2`.
- Stage16A V0.8.0: 724/724 arquivos byte-idênticos ao checkpoint, zero divergências.
- Checkpoint: SHA-256
  `21626A3152CB37E167EEE24BFF9D3142C5D389A8CA2827594B34211591525A6A`.
- `06_GODOT_LIVING_V1_5`: incluído na comparação byte a byte; sem divergência.
- B01: fontes e gates mantiveram os hashes aprovados; 54/54 headless e 54/54 via
  Editor Bridge.
- B02: scripts/gate imutáveis mantiveram os hashes aprovados; a composição
  cumulativa recebeu somente as extensões B03 e a correção obrigatória de layers;
  90/90 headless e 90/90 via Editor Bridge.
- Backup final da Stage 16: não autorizado e não criado.

## Implementação

### Resolução de alvo

`scripts/main.gd` passou a fazer raycast multi-hit nas layers contratuais. Cada
colisor/sensor propaga `target_ref`, `target_kind`, identidade hostil, tipo de recurso,
estado settled e referência estável do componente visual.

A ordenação preserva a Stage16A:

1. menor distância de tela ao cursor;
2. menor profundidade visual;
3. prioridade semântica somente em empate;
4. `target_ref` apenas para determinismo final.

Um bloqueador encontrado antes do alvo interrompe a consulta. Hover e movimento da
câmera não reescrevem a seleção resolvida pelo clique.

### Click contract

- esquerdo no chão: `MOVE_TO_POINT` B02;
- esquerdo em alvo comum: `SELECT_TARGET`, sem alterar destino;
- esquerdo em Ground Loot: `PICKUP` a `<= 0,5 m` ou `APPROACH_PICKUP` com path;
- direito no chão: `MOVE_TO_POINT` B02;
- direito em inimigo hostil: envelope local `CHASE_ATTACK`;
- direito em NPC/animal/objeto/veículo: envelope local `APPROACH_INTERACT`;
- direito em árvore/rocha/minério/flora: envelope local `APPROACH_HARVEST`;
- direito em Ground Loot: `PICKUP`/`APPROACH_PICKUP` conforme distância/path.

Os envelopes são construídos por `AndromedaBridge.build_command_envelope`, contêm
`session_ref` e nunca `player_ref`, e não são submetidos. O estado do bridge permaneceu
`CONNECTING` sem round-trip, confirmando ausência de endpoint inventado.

### Placeholders

Foram adicionados atores visuais NPC, inimigo e animal; quatro recursos individuais;
objeto, veículo e Ground Loot físico. Os meshes, materiais, labels e indicadores são
provisórios. Não existem IA final, dano, cooldown, loot table, vendor, quest,
gathering, Auto Pickup remoto, transferência de inventário ou arte final.

O NPC possui nome placeholder oculto por padrão e visível somente no hover. Inimigo
é `ACTOR` hostil; NPC é neutro; animal permanece `ANIMAL` não hostil.

### Collision layers

As 13 layers V0.8.0 foram nomeadas no projeto. Foi encontrado um erro cumulativo da
B02: as constantes locais `4` e `8` eram descritas como target/loot, mas correspondem
a `ACTOR_BODY` e `INTERACTABLE`. A correção necessária passou os placeholders B02
para `INTERACTABLE=8` e `GROUND_LOOT=16`, atualizou a máscara do Player para
`WORLD_STATIC|ACTOR_BODY|RESOURCE_NODE|VEHICLE|NAV_BLOCKER=229` e a máscara do probe
de câmera para `CAMERA_OCCLUDER=256`. Paths e tipos B02 foram preservados.

## Ciclos, anomalias e correções

1. A primeira importação encontrou cast estático inválido do componente
   `AndromedaInteractionTarget` para `CollisionObject3D`. A tentativa foi FAIL. O
   snapshot diagnóstico passou a ler dinamicamente a propriedade do root; importações
   R2/R3 ficaram limpas.
2. O primeiro gate headless atingiu 357/357, mas a primeira execução via Editor Bridge
   mostrou três warnings de `await` desnecessário no gate. O PASS numérico foi
   invalidado. Os três awaits síncronos foram removidos e headless + bridge foram
   reiniciados; ambos ficaram limpos.
3. A primeira tentativa de iniciar a regressão Python com `Start-Process` não executou
   testes porque o ambiente Windows continha as chaves duplicadas `Path/PATH`. Foi
   invalidada.
4. A execução direta seguinte concluiu 209/209 e código 0, mas o redirecionamento
   `*>` do Windows PowerShell encapsulou a saída normal do runner em registros
   `NativeCommandError/RemoteException`. O arquivo foi recusado como evidência final.
   A suíte foi reiniciada com redirecionamento nativo do `cmd`, Python bundled,
   `PYTHONDONTWRITEBYTECODE=1` e o Master V2.0.1 correto; o log bruto final ficou
   limpo e 209/209 passaram.

## Testes finais

- B03 headless: 357/357 PASS; código 0; stderr vazio.
- B03 Editor Bridge: 357/357 PASS; `errors: []`; stop `finalErrors: []`.
- `Main.tscn` direta no Editor Bridge: startup e stop limpos.
- B01 headless: 54/54 PASS; stderr vazio.
- B01 Editor Bridge: 54/54 PASS; `errors: []`; stop limpo.
- B02 headless: 90/90 PASS; stderr vazio.
- B02 Editor Bridge: 90/90 PASS; `errors: []`; stop limpo.
- Stage16A: 209/209 PASS em 267,153 s; log bruto sem artefatos/tracebacks.
- Stage16A stress: 20/20 PASS.
- Baseline: 724/724, zero divergências.
- Backend `127.0.0.1:8000`: zero listeners; `NOT_AVAILABLE`, não contado como PASS.

## Acceptance Matrix

- `G16B-01`: PASS preservado/revalidado.
- `G16B-02`: PASS preservado/revalidado.
- `G16B-03`: `PARTIAL_EVIDENCE_B03_NOT_PASS`; target e right-click intents passam,
  mas cooldown/chase/attack autoritativos exigem backend vivo/bloco posterior.
- `G16B-04`: `PARTIAL_EVIDENCE_B03_NOT_PASS`; limite físico, settled, path e
  bloqueador passam localmente; pickup autoritativo não foi executado.
- `G16B-11`: `PARTIAL_EVIDENCE_B03_NOT_PASS`; nome no hover passa, conversas/choices
  ainda não foram executadas.
- `G16B-14`: parcial B02, sem alteração; fade real ainda falta.
- `G16B-20`: `PARTIAL_EVIDENCE_B03_NOT_FINAL`; regressões e integridade passam neste
  checkpoint, mas o gate final continua reservado para B11.
- `G16B-05`, `G16B-21` e `G16B-22`: NOT_RUN nesta B03.
- Demais gates: estado anterior/NOT_RUN.

## Watch items

- O backend real em `127.0.0.1:8000` não possui listener. Cooldown, resultado de
  ataque/interação e pickup autoritativo permanecem indisponíveis; nenhum substituto
  foi criado.
- Recursos possuem `DropAnchor` e intenção contextual, mas ainda não geram Ground
  Loot após confirmação autoritativa; `G16B-05` permanece NOT_RUN.
- Diálogo alternado, choices e balões pertencem ao bloco posterior; somente o nome de
  NPC no hover foi coberto.
- O fade real de oclusores continua pendente em `G16B-14`.
- Não avançar para B04 sem solicitação explícita.
