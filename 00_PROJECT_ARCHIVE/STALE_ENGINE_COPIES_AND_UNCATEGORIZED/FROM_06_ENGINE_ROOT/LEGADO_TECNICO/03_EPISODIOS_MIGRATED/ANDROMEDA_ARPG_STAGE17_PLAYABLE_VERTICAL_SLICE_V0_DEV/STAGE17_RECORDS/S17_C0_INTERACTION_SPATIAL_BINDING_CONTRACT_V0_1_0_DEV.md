# Stage17 / Etapa 31 — S17-C0 Interaction Spatial Binding Contract

Status: `S17_C0_INTERACTION_SPATIAL_BINDING_CONTRACT = PASS`

Classe representativa: `ENEMY`

Flag: `ENEMY_AUTHORITY_SPATIAL_BINDING_READY = true`

## Resultado

O C0 provou o primeiro binding espacial completo entre uma entidade territorial Python e seu proxy visual Godot sem transformar `Node3D.global_position` em autoridade. O alvo hostil é descoberto no snapshot real, sua posição vem de `movement.state(target_ref)` e chega em `combat_targets[].position` com `position_authority = LIVING_CONTINUOUS_ISOMETRIC_MOVEMENT_RUNTIME`.

O caminho executado foi:

`snapshot autoritativo → target_ref/posição → InteractionSpatialBindingRegistry → AuthoritySpaceMapper.authority_to_local → Node greybox → right-click normal → movement_authority_client → MOVE_TO_POINT → reconciliação → REQUEST_ATTACK`

Não houve alteração do backend Stage17 nem de qualquer baseline Stage16B.

## Auditoria das classes

| Classe | Identidade real | Posição métrica real projetada | Adequada ao C0 | Resultado |
|---|---:|---:|---:|---|
| RESOURCE | Sim (`GTH-*`) | Não; projeção declara `GODOT_LOCAL_PLACEHOLDER_ONLY` | Não | Pendente de projection contract |
| NPC | Sim (`NPC-*`) | Não por NPC individual | Não | Cidade/bloco não é ponto individual de interação |
| ENEMY | Sim (`NPC-*` hostil) | Sim, `movement.state(target_ref)` | Sim | Escolhida e aprovada |
| GROUND_LOOT | Sim quando ativo | Sim, candidate/settled | Não nesta rodada | Limitação de auto-settle fora do C0 |
| DROPPED_BAG | Sim quando ativo | Sim no estado death/recovery | Não nesta rodada | Exigiria morte, fora do C0 |
| VENDOR | Sim | Não individualmente projetada | Não | Presentation-only |
| INTERACTIVE_OBJECT | Sim/local | Não encontrada | Não | Presentation-only |

## Contrato aceito

Um binding válido requer `target_ref`, `target_kind`, `position.iso_x_m`, `position.iso_y_m`, `position.altitude_m`, `identity.world_instance_id`, `session_ref`, `snapshot_sequence` e uma `position_authority` que não seja placeholder.

O frame é o mesmo do Player: metros isométricos territoriais globais. A conversão é exclusivamente a já aprovada em B1:

`AuthoritySpaceMapper.authority_to_local(authority_position)`

O registry escreve a posição no proxy visual, mas nunca lê a posição do proxy para fabricar posição autoritativa ou distância de gameplay.

## Política de ciclo de vida

- Stale/duplicate: `snapshot_sequence <= last_sequence_for_ref` é rejeitado.
- World change: todos os bindings são invalidados e aguardam novo anchor/projection.
- Session/reconnect: revoke, disconnect e reconnect-wait invalidam o cache; só snapshot fresco recria binding.
- Despawn: binding removido, Node escondido/desabilitado e approach pendente cancelado.
- Distância: o stand-off local serve somente à navegação visual; alcance, distância válida, hit e resultado continuam validados pelo backend.

## Evidência live

Headless final: `75/75 PASS`, exit 0.

- World: `rt:world:bd0f78f5-7018-4cc6-8f47-34f8f2875e47`
- Target descoberto: `NPC-01-01-01-003`
- Target authority: `(137106.001094855, -1336956.95467693, 0.0)`
- Player P0: `(137110.245095, -1336956.954677, 0.0)`
- Player P1: `(137108.156776, -1336956.954677, 0.0)`
- Distância backend: `2.155681 m`
- Alcance backend: `2.994 m`
- Ação: `REQUEST_ATTACK = PASS`
- Approach explícito: `1`
- `MOVE_TO_POINT`: `1`
- Spam por frame: `0`
- Rejections: `0`

Editor Bridge final: `75/75 PASS`; debugger `0 errors / 0 warnings`; stop controlado `finalErrors: []`. O alvo live dessa execução foi `NPC-01-01-01-007`, demonstrando que o gate não depende de ref hardcoded.

`Main.tscn` também abriu pelo Editor Bridge, fez `POST /session/bind` e `GET /snapshot` HTTP 200 na sessão normal `GODOT-STAGE17-PLAYABLE-V0-DEV-001`, permaneceu sem erros/warnings e encerrou com `finalErrors: []`.

O executável headless no Windows continua emitindo a linha externa `Failed to read the root certificate store`. Ela não é uma finding do projeto, o gate termina com exit 0, e o debugger real do Editor permaneceu 0/0. A ocorrência está preservada nos logs e no Acceptance Record.

## Regressões finais

- S17-00: `22/22 PASS`
- S17-A live: `17/17 PASS`
- S17-A failed path: `9/9 PASS`
- S17-A total: `26/26 PASS`
- S17-B1: `36/36 PASS`
- S17-B2: `73/73 PASS`
- B01: `54/54 PASS`
- G19: `71/71 PASS`
- Combat: `91/91 PASS`

Ground Loot e Gathering não foram reexecutados porque seus clients/shared approach paths não foram alterados. O caminho alterado foi o cliente de combate, cuja regressão específica 91/91 foi obrigatória e passou.

## Arquivos

Criados:

- `13_GODOT_ARPG_STAGE17/scripts/interaction/interaction_spatial_binding_registry.gd`
- `13_GODOT_ARPG_STAGE17/tests/godot/S17C0InteractionSpatialBindingGate.tscn`
- `13_GODOT_ARPG_STAGE17/tests/godot/s17c0_interaction_spatial_binding_gate.gd`

Modificados:

- `13_GODOT_ARPG_STAGE17/scenes/Main.tscn`
- `13_GODOT_ARPG_STAGE17/scripts/main.gd`
- `13_GODOT_ARPG_STAGE17/scripts/interaction/combat_authority_client.gd`
- `13_GODOT_ARPG_STAGE17/tests/godot/authority_combat_runtime_gate.gd`
- `13_GODOT_ARPG_STAGE17/tests/godot/s17b2_movement_authority_gate.gd`

Os dois harnesses históricos foram ajustados porque assumiam espaço vazio ou moviam proxy de alvo como se fosse autoridade. O número e a intenção dos checks foram preservados.

## Rodadas invalidadas

As rodadas incompletas, warnings, estado contaminado e assumptions históricas foram descartadas e repetidas. O registro completo está em `S17_C0_INVALIDATED_RUNS_V0_1_0_DEV.json`. Nenhum histórico foi apagado; estados contaminados foram movidos para arquivos `_archive_s17c0_*` dentro do runtime Stage17.

## Baseline protegida

Checkpoint e backup Stage16B foram recalculados após a implementação:

`77276aa0bcff0475193d2b85a89fdee7d27564b8b5c83af09f8725b414cd67cc`

Ambos permanecem com 852793 bytes, 304 entradas e `testzip = CLEAN`. Stage16B permanece `CLOSED / READ_ONLY`.

## Housekeeping

O backend Stage17 foi encerrado de forma controlada usando exclusivamente o PID 12384 registrado pelo launcher. O record final informa `CONTROLLED_OWNER_PID_STOP` e a porta 8000 terminou com zero listeners. O editor Godot preexistente, PID 11316, permaneceu aberto e intocado. Runtime, archives, checkpoint e backup foram preservados.

## Escopo restante

Pronto: `ENEMY` somente, para approach inicial estático.

Pendentes: `RESOURCE`, `NPC`, `GROUND_LOOT`, `DROPPED_BAG`, `VENDOR` e `INTERACTIVE_OBJECT`.

`S17_COMBAT_CHASE_AUTHORITY_MIGRATION_PENDING` permanece. C0 não adicionou chase contínuo e não envia comandos de movimento por frame.

## Próximo bloco recomendado

Abrir primeiro `S17-C1 — RESOURCE AUTHORITY POSITION SOURCE + PROJECTION CONTRACT`. A identidade de Resource já existe, mas sua posição projetada ainda é explicitamente placeholder. Só depois abrir `S17-C2 — RESOURCE AUTHORITATIVE APPROACH + REQUEST_GATHER`. Nenhuma posição de Resource deve ser inferida de seu Node Godot.
