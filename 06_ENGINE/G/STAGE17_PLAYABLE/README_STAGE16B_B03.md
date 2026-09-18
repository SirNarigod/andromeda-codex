# Andrômeda Códex ARPG — Stage 16B — B03

Este diretório contém a camada Godot da B03 — `Interaction Targets + NPC + Enemy +
Resource Nodes`. A implementação é exclusivamente cliente/apresentação:

- detecta o alvo realmente atingido pelo cursor;
- resolve sobreposição por distância de tela e profundidade, usando tipo somente como
  desempate final;
- apresenta hover, nome de NPC apenas no hover e seleção sutil;
- cria envelopes locais de intenção sem chamar `submit_command`;
- mantém movimento e física local do Player sob a implementação B02;
- nunca decide dano, cooldown, coleta, inventário, vendor, quest, gathering ou IA.

## Cenas placeholder

- `scenes/actors/NPC.tscn`
- `scenes/actors/Enemy.tscn`
- `scenes/actors/Animal.tscn`
- `scenes/interaction/ResourceNode.tscn`
- `scenes/interaction/InteractiveObject.tscn`
- `scenes/interaction/Vehicle.tscn`
- `scenes/interaction/GroundLoot.tscn`

`Main.tscn` instancia árvore, rocha, minério, flora, objeto, veículo e fixtures de
Ground Loot alcançável, inalcançável, não assentado e bloqueado. Toda geometria e
todo material são provisórios; nenhuma arte final foi adicionada.

## Collision layers V0.8.0

1. `WORLD_STATIC`
2. `PLAYER`
3. `ACTOR_BODY`
4. `INTERACTABLE`
5. `GROUND_LOOT`
6. `RESOURCE_NODE`
7. `VEHICLE`
8. `NAV_BLOCKER`
9. `CAMERA_OCCLUDER`
10. `HIT_HURT_SENSOR`
11. `WORLD_TRIGGER`
12. `WATER_VOLUME`
13. `DROPPED_BAG`

A B03 corrigiu os valores numéricos cumulativos dos placeholders B02: o NPC passou
do bit 4 para o bit 8 (`INTERACTABLE`) e Ground Loot passou do bit 8 para o bit 16
(`GROUND_LOOT`). Os mesmos node paths e tipos foram preservados e a B02 foi
revalidada em 90/90 nos dois modos.

## Gate local

Cena: `res://tests/godot/B03RuntimeGate.tscn`

Resultado final:

- headless: 357/357 PASS, código 0, stderr vazio;
- Andrômeda Editor Bridge: 357/357 PASS, `errors: []`, stop com
  `finalErrors: []`;
- `Main.tscn` direta pelo Editor Bridge: startup e stop limpos.

O gate usa a sessão B01 apenas para validar a forma do envelope. Nenhuma requisição
HTTP é enviada. O servidor real `127.0.0.1:8000` não estava disponível e nenhum
endpoint substituto foi criado.

## Estado da Acceptance Matrix

- `G16B-01`: PASS preservado e revalidado;
- `G16B-02`: PASS preservado e revalidado;
- `G16B-03`: `PARTIAL_EVIDENCE_B03_NOT_PASS` — intents contextuais cobertas;
  cooldown e resultado autoritativo não estão disponíveis;
- `G16B-04`: `PARTIAL_EVIDENCE_B03_NOT_PASS` — limite, path, bloqueador e settled
  cobertos localmente; pickup autoritativo não executado;
- `G16B-11`: `PARTIAL_EVIDENCE_B03_NOT_PASS` — nome no hover coberto; conversas e
  escolhas pertencem a bloco posterior;
- `G16B-20`: `PARTIAL_EVIDENCE_B03_NOT_FINAL` — regressões deste checkpoint passam;
- demais gates mantêm o estado anterior ou `NOT_RUN`.

A Stage 16 completa ainda não está aprovada e nenhum backup final foi criado.

