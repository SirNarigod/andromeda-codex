# Stage17 / Etapa 31 — S17-C1B Resource Metric Placement Authority

Status: `S17_C1B_RESOURCE_METRIC_PLACEMENT_AUTHORITY_PASS`

Supersede: nenhum. Este é um registro novo, distinto do preflight anterior
`S17_C1_RESOURCE_AUTHORITY_POSITION_CONTRACT_V0_1_0_DEV.md` (que permanece
válido como o registro histórico do gap original — não foi reescrito).

## Contexto

Continuação de sessão interrompida por limite de créditos durante a
validação final. Este registro fecha C1B com base em auditoria completa do
workspace (inspeção read-only de todo o estado em disco, do SQLite ao vivo,
dos logs de gate e dos testes de backend) e em regressão limpa executada
nesta continuação.

## Módulo de autoridade

`12_AUTHORITY_BACKEND_STAGE17/resource_metric_placement.py`
(`ResourceMetricPlacementRegistry`, `SCHEMA_VERSION = S17_RESOURCE_METRIC_PLACEMENT_V1`).

## Contrato de placement físico (confirmado por leitura de código + 24 testes)

- `placement_ref` — determinístico: `sha256(world_instance_id | logical_node_ref |
  authoring_object_ref | placement_revision | ordinal)`, prefixo
  `RESOURCE-PLACEMENT-S17-`.
- `logical_node_ref` — obrigatoriamente `GTH-*`, validado contra
  `arpg_gathering_nodes` real (zone_ref/block_ref/source_kind/source_ref
  devem bater com a definição lógica real).
- `world_instance_id`, `zone_ref`, `block_ref`, `resource_kind`,
  `source_kind`, `source_ref`.
- posição métrica: `iso_x_m`, `iso_y_m`, `altitude_m` (finitude validada,
  NaN/Infinity rejeitados).
- `placement_mode` ∈ {EXPLICIT, GENERATED} — EXPLICIT para recursos
  importantes (placement autoral), GENERATED para recursos comuns
  (determinístico dentro de regions/exclusions autorais).
- `placement_revision`, `schema_version`, `source_manifest_hash`,
  `position_authority = STAGE17_RESOURCE_METRIC_PLACEMENT_MATERIALIZED`
  (nunca `GODOT_LOCAL_PLACEHOLDER_ONLY`).
- proveniência: `authoring_object_ref`, `authoring_node_path`, `ordinal`.
- `active` (bool) e `payload_hash` (proteção de integridade por linha).

GTH continua autoridade exclusiva de capacity/remaining_units/depletion/
yield/activity/output — o placement físico não duplica nenhum desses
campos (`logical_gth_depletion_duplicated: false` em `metrics()`).

## N:1 (placement físico → GTH lógico)

Chave primária é `placement_ref`, não `logical_node_ref`. Sem
`unique(logical_node_ref)`. `placements_for_logical()` retorna lista.
`test_18_many_physical_placements_per_gth_are_permitted` prova isso
diretamente. A Playable V0 materializa hoje 1:1 (uma TREE, uma ORE), mas o
schema está pronto para N:1 sem migração futura.

## Reprodutibilidade e persistência (provado, não presumido)

- `test_03_deterministic_hash`, `test_04_deterministic_physical_refs`,
  `test_21_same_manifest_load_is_reproducible`: mesma entrada canônica →
  mesmos refs/posições/hash.
- `test_10_restart_persists_identity_position_and_revision`,
  `test_16_restart_preserves_placements_and_projection_without_duplicates`
  (no módulo de gather): restart real do adapter → mesmos placements,
  zero duplicatas.
- Evidência de runtime independente dos testes unitários: dois processos
  de bake separados (`STAGE17_RUNTIME_STATE/evidence/c1b_repro_final/run_1.json`,
  `run_2.json`) comparados byte-a-byte nesta continuação —
  `canonical_manifest`, `canonical_manifest_hash` e `schema` são
  **idênticos** entre as duas execuções (comparação `dict == dict` em
  Python, não apenas inspeção visual).
- `authority_backend_process.json` do boot original (`launcher_start_time_utc
  2026-08-29T06:26:42Z`) já mostrava `resource_metric_placement.status=PASS`,
  `inserted:0, replayed:2` — ou seja, o boot que sucedeu a interrupção do
  Codex já era um replay idempotente, não uma primeira materialização.

## Blocker / LOS (server-side real, não client raycast)

`ResourceMetricPlacementRegistry.line_of_sight()` faz teste real de
interseção segmento/AABB 3D (slab test) contra
`s17_resource_metric_constraints`, geometria vinda exclusivamente do bake
offline (`geometry_source: OFFLINE_BAKED_MATERIALIZED_SERVER_CONSTRAINTS`,
`client_raycast_used: false`). Confirmado em C2 ao vivo: um gather bloqueado
por `RESOURCE-LOS-BLOCKER-S17-001` foi rejeitado com `mutation_applied:false`
antes de qualquer chamada ao core protegido.

## Migração de world / limitação descoberta nesta continuação

O manifesto canônico prende `world_binding.world_instance_id` a um mundo
específico (`rt:world:bd0f78f5-...`) — `validate_manifest()` rejeita
qualquer outro mundo com `RESOURCE_PLACEMENT_WORLD_MISMATCH`
(`test_13_world_mismatch_rejected` prova isso). Isto é comportamento
**correto e intencional**: um manifesto autoral não pode ser
materializado silenciosamente em um mundo diferente do qual foi baked.
Na prática isso significa que o mundo de desenvolvimento atual não pode
ser recriado a frio sem também regerar o manifesto (rebake) — exatamente
a política já registrada em `S17_C1A_DECISION_RECORD`: "DEV world:
recreate ou migration auditável". Esta continuação tentou uma recriação a
frio por engano (ver `INVALIDATED_RUNS`), confirmou o gap na prática, e
reverteu para o mundo original sem alterar nenhuma linha de código.

## Testes de backend (24/24, execução fresca nesta continuação)

`tests/test_stage17_resource_metric_placement.py` — 24 testes, todos PASS
em execução fresca (unittest direto, sem cache), cobrindo: schema,
ordenação canônica, hash determinístico, refs determinísticos,
materialização TREE/ORE, GTH real, GTH não regenerado, contagem exata na
primeira materialização, persistência a restart, replay sem duplicata,
conflito de revisão rejeitado, mundo errado rejeitado, altitude inválida
rejeitada, NaN/Infinity rejeitados, cliente não pode setar/mover
placement, GTH continua autoridade de depletion, N:1 permitido, query por
zona/bloco, query por GTH lógico, reprodutibilidade de carga, proveniência
retida, métricas sem depleção duplicada, position_authority é backend não
Godot.

## Disposição

- `S17_C1B_RESOURCE_METRIC_PLACEMENT_AUTHORITY = PASS`
- `RESOURCE_PLACEMENT_SCHEMA_N1_READY = true`
- `RESOURCE_PLACEMENT_REPRODUCIBLE = true` (provado por comparação binária)
- `RESOURCE_PLACEMENT_PERSISTENT_ACROSS_RESTART = true`
- `RESOURCE_PLACEMENT_BLOCKER_LOS_SERVER_SIDE = true`
- `RESOURCE_PLACEMENT_WORLD_BOUND_BY_DESIGN = true` (limitação de
  recriação a frio documentada, não corrigida — fora de escopo desta
  rodada)

## Baselines

Stage16B checkpoint e backup permanecem:
`77276aa0bcff0475193d2b85a89fdee7d27564b8b5c83af09f8725b414cd67cc`
Stage16B permanece `CLOSED / READ_ONLY`.

Próximo processo: `S17-C1_RESOURCE_AUTHORITY_POSITION_CONTRACT` (ver
`S17_C1B_C1_C2_ACCEPTANCE_RECORD_V0_1_0_DEV.json`).
