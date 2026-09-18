# Stage17 / Etapa 31 — S17-C1 Resource Authority Position Contract

Status: `S17_C1_RESOURCE_POSITION_AUTHORITY_GAP`

C2: `NOT_STARTED`

## Conclusão

Os Resource Nodes Stage16A/Stage17 possuem identidade real e persistente, mas não possuem posição métrica territorial individual. O estado atual não satisfaz o pré-requisito espacial de C1 e, portanto, não é permitido projetar uma posição nem iniciar C2.

Este resultado é um **authority source gap**, não apenas um projection gap.

## Fontes auditadas

- `01_RUNTIME/arpg_gathering_work_core.py`
- `01_RUNTIME/arpg_vertical_slice_assembly_core.py`
- `01_RUNTIME/country_scale.py`
- `01_RUNTIME/spatial_coordinates.py`
- `12_AUTHORITY_BACKEND_STAGE17/andromeda_authority_adapter.py`
- `12_AUTHORITY_BACKEND_STAGE17/tests/test_stage16b_authority_gathering.py`
- Godot `gathering_client.gd`, Gathering gate e G19 gate
- schema e definitions do SQLite Stage17 abertos em modo read-only

Nenhuma dessas fontes foi modificada.

## Identidade existente

`arpg_gathering_nodes` persiste:

- `world_instance_id`
- `node_ref`
- `zone_ref`
- `block_ref`
- `activity_type`
- `source_kind`
- `source_ref`
- `output_item_ref`
- `definition_json`
- hashes

O `node_ref` é derivado de `world_seed | activity | block_ref | source_kind | source_ref`. Isso cria uma identidade estável `GTH-*`, mas não cria coordenadas métricas.

## TREE

TREE é um node `LOGGING / FLORA`. O source record do Country Runtime contém identidade, espécie, tier, abundância/capacidade e estado. Não contém `iso_x_m`, `iso_y_m`, `altitude_m`, coordinate center ou outro anchor individual.

Exemplo auditado no runtime atual: `GTH-CA3D9A47934BD64A24B4`. Esta ref é somente evidência; não foi hardcoded em source.

## ORE

ORE é um node `MINING / MINERAL` cujo `source_meta.kind` não é `STONE`. O source record contém identidade, kind, tier, density/capacidade e estado, mas nenhuma posição métrica individual.

Exemplo auditado no runtime atual: `GTH-34AC1BC54C33917F0553` (`MIN-MANA-ORE`). Esta ref é somente evidência; não foi hardcoded em source.

ROCK, FLORA e AGRICULTURE compartilham o mesmo modelo espacial: zone/block sem posição individual.

## Como o gather range funciona hoje

Não existe gather range métrico no backend atual.

`_worker_location()` resolve apenas `(zone_ref, block_ref)`. `create_work_order()` aceita quando `worker.block_ref == node.block_ref`; `execute_work_order()` repete a mesma comparação. Não há cálculo de metros, interaction radius, LOS ou blocker.

Por isso `location_evaluated_server_side = true` significa apenas **co-localização no mesmo bloco**, não proximidade métrica do Resource Node.

O gate G19 encontra um `target_ref` no snapshot e envia `REQUEST_GATHER` diretamente. A distância local utilizada pelo cliente/harness histórico não é enviada e não é revalidada metricamente pelo backend.

## Ground Loot

Ao produzir Ground Loot, `arpg_vertical_slice_assembly_core._ground_delivery_sink()` lê a posição autoritativa do **Player** em `movement.state(profile.avatar_ref)` e a usa como `candidate_position`. Isso prova onde o output nasce, mas não prova onde o Resource Node existe.

Não é válido inverter esse resultado e declarar que a posição do Player ou do drop era a posição do Resource.

## Projection atual

O adapter projeta Resource com:

`position_authority = GODOT_LOCAL_PLACEHOLDER_ONLY`

e sem `position`. Esse label está correto para o estado histórico e não foi alterado.

## Menor mudança correta

É necessário um bloco futuro autorizado de **Resource Metric Placement Authority**, exclusivamente no fork Stage17, antes de retomar C1:

1. definir uma política explícita de placement por `world_instance_id + node_ref`;
2. produzir `iso_x_m`, `iso_y_m` e `altitude_m` no mesmo frame de movement state;
3. garantir que cada posição é caminhável e coerente com zone/block/traversal;
4. persistir a posição ou torná-la uma derivação imutável, versionada e reproduzível;
5. preservar os `GTH-*` existentes e o estado de depletion;
6. validar distância métrica server-side antes de delegar ao core Stage16A;
7. projetar posição, world identity, sequence e authority label;
8. somente depois consumir a projection no InteractionSpatialBindingRegistry.

Não é suficiente escolher o centro do bloco, aplicar offset aleatório, reutilizar o transform da cena ou criar uma seed sem contrato. A política precisa de decisão explícita porque passa a constituir autoridade gameplay-derived Stage17.

## Persistência

Uma posição estável precisa sobreviver a reconnect/reload e manter identidade com o mesmo `node_ref`. A opção de menor risco é uma tabela Stage17 aditiva e hash-protegida. Uma derivação puramente determinística também poderia ser válida, mas somente se a fórmula, versão, inputs e compatibilidade com mundos já existentes forem formalmente contratados.

## Impacto

- Gathering: adicionará proximidade métrica que hoje não existe; yield/tool/depletion continuam delegados ao core protegido.
- Ground Loot: pode continuar nascendo na posição do Player após um gather válido; pickup/settling continuam fora deste bloco.
- Saves: placement não pode mudar silenciosamente entre boots.
- Navigation: posições precisam ser alcançáveis e não cair dentro de blocker/água inválida.
- Security: o cliente não pode fornecer ou corrigir coordenadas do Resource.

## Baselines

Stage16B checkpoint e backup permanecem:

`77276aa0bcff0475193d2b85a89fdee7d27564b8b5c83af09f8725b414cd67cc`

Stage16B permanece `CLOSED / READ_ONLY`.

## Disposição

- `S17_C1_RESOURCE_AUTHORITY_POSITION_CONTRACT = BLOCKED`
- `S17_C1_RESOURCE_POSITION_AUTHORITY_GAP = CONFIRMED`
- `S17_C2_RESOURCE_AUTHORITATIVE_APPROACH_GATHER = NOT_STARTED`
- `ENEMY_AUTHORITY_SPATIAL_BINDING_READY = true` permanece intacto
- `RESOURCE_AUTHORITY_SPATIAL_BINDING_READY = false`

Próximo processo recomendado: `S17-C1A — RESOURCE METRIC PLACEMENT AUTHORITY DESIGN + AUTHORIAL PLACEMENT POLICY`.
