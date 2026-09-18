# Stage 16B — B02 — Main, Player, Camera, Click-to-Move e Navigation

Status do bloco: **PASS local Godot** em 2026-08-20.

Este bloco permanece isolado em `07_GODOT_ARPG_STAGE16B`. O Master V2.0.1, a
baseline Stage16A V0.8.0, `06_GODOT_LIVING_V1_5` e os arquivos fechados da B01 não
foram modificados. `project.godot` é o único arquivo cumulativo da B01 que evoluiu
para selecionar a nova cena principal e registrar o `InputRouter`/InputMap da B02.

## Escopo implementado

- `Main.tscn` com os roots contratuais `RuntimeBridge`, `WorldStreamRoot`,
  `ActorRoot`, `GroundLootRoot`, `EffectsRoot`, `IsometricCameraRig` e `UILayer`;
- superfícies visual, de colisão e de traversal separadas;
- Player placeholder como `CharacterBody3D`, com `CollisionShape3D`,
  `NavigationAgent3D`, `VisualRoot`, `Hurtbox`, `DialogueAnchor` e `TargetAnchor`;
- NavigationMesh placeholder real, com oito células caminháveis e um bloqueio
  central contornado pelo path;
- clique de chão resolvido por raycast físico e convertido em intenção
  `MOVE_TO_POINT`;
- clique esquerdo em alvo convertido em `SELECT_TARGET` sem trocar o destino;
- Ground Loot como exceção explícita, com `APPROACH_PICKUP` e raio direto de
  pickup preservado em `<= 0,5 m`;
- câmera fixa isométrica/oblíqua `45°/55°`, follow suavizado, deadband vertical de
  `0,12 m`, zoom `11–18 m`, sem free orbit e com `OcclusionProbe` preparado;
- roda sem modificador preservada para os dois quick-slots, modificador + roda
  reservado ao zoom e roda em menu reservada ao scroll.

## Limite de autoridade

O movimento executado pelo Godot é previsão/apresentação local para validar input,
física e Navigation. O Player constrói um envelope compatível com a bridge B01
quando existe uma sessão, mas o gate não envia comandos. Nenhum dano, pickup,
inventário, combate, economia, quest, morte, Bag, TTL ou mutação canônica é resolvido
em GDScript.

O endpoint preservado é `http://127.0.0.1:8000`; ele continua sem listener. Nenhum
backend substituto foi criado. O round-trip autoritativo de movimento permanece um
watch item e não foi contado como PASS.

## Evidência executável

O gate `tests/godot/B02RuntimeGate.tscn` cobre 90 checks, incluindo entry point,
InputMap, spawn, cliques
físicos, destinos consecutivos e rápidos, destino impossível, path real, colisão,
desvio do bloqueio, chegada/parada, jitter, câmera, zoom, microdesnível, estabilidade
da resolução de alvo e limites de autoridade.

Resultado final:

- headless: `90/90 PASS`, exit code `0`, sem warning/erro;
- Editor Bridge: `90/90 PASS`, `errors: []`, stop final limpo;
- `Main.tscn` direta pelo Editor Bridge: startup limpo;
- regressão B01: `54/54` headless e `54/54` pelo Editor Bridge;
- Stage16A: `209/209` e stress `20/20`;
- integridade do checkpoint: `724/724`, zero divergências.

Os detalhes completos estão em `B02_ACCEPTANCE_RECORD_V0_8_0.json`,
`B02_EDITOR_BRIDGE_DEBUGGER_V0_8_0.json` e
`B02_IMPLEMENTATION_LOG_V0_8_0.md`.

## Acceptance Matrix

- G16B-01: PASS preservado e revalidado.
- G16B-02: PASS.
- G16B-14: evidência parcial; o probe e o contrato de alpha estão preparados, mas
  o fade visual de materiais de oclusores ainda não foi aplicado.
- G16B-20: evidência parcial de checkpoint; o gate final continua pendente.
- Demais gates: NOT_RUN.

A Stage16 não está completa, nenhum backup final foi criado e a B03 não foi iniciada.
