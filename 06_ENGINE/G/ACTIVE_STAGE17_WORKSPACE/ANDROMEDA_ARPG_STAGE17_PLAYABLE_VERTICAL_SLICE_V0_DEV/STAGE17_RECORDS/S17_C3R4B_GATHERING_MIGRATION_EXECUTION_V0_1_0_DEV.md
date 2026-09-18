# Stage17 / Etapa 31 — S17-C3R4B Formal Gathering Migration — Execução no World Real

Status: `S17_C3R4B_FORMAL_GATHERING_MIGRATION = PASS` /
`STAGE17_CURRENT_WORLD_RESUMABLE = true`

## Ordem executada (exatamente como autorizado)

1. Reauditoria read-only do DB real → **312 nodes, 1 mutable capacity
   drift, 0 structural drift** — idêntico à expectativa da S17-C3R2/C3R3.
   Backend OFF, sem listener 8000, único processo Godot é o editor
   pré-existente do usuário (PID 11316). Hash antes/depois da reauditoria:
   `c84d1bda...`/15.060.992 bytes, idêntico.
2. Backup fresco criado: `STAGE17_RUNTIME_STATE/_archive_pre_s17_c3r4_gathering_migration_20260829T150548Z_authority/stage17_world.sqlite`,
   hash `c84d1bda...` — idêntico byte-a-byte ao arquivo real no momento da
   cópia.
3. Backup validado read-only: `world_instance_id` confere
   (`rt:world:bd0f78f5-...`), node problemático presente com
   `capacity_units:86` (não migrado), `fauna.count:58` ao vivo confirmado,
   `player_ref`/`profile_ref` conferem, Player confirmado deslocado
   (`v15_motion_state`: `iso_x_m:102897.28, iso_y_m:857054.61` vs anchor
   `137108.16,-1336956.95` → ~2194 km), tabelas de resource placement
   presentes (`s17_resource_metric_placements`, `s17_resource_metric_constraints`,
   `s17_resource_placement_manifests`). `BACKUP_VALIDATED = true`.
4. Migration aplicada ao DB real:
   `python STAGE17_TOOLS/migrations/migrate_stage17_gathering_mutable_capacity_v1.py --db-path STAGE17_RUNTIME_STATE/authority/stage17_world.sqlite --apply`.

## Resultado da aplicação

```
status: APPLIED
affected_node_count: 1
affected_node_refs: ["GTH-1D268772796B25C4CC6B"]
before_hashes: {"GTH-1D268772796B25C4CC6B": "be85ac2a..."}
after_hashes:  {"GTH-1D268772796B25C4CC6B": "21945ee6..."}
migration_payload_hash: d1b75e632a567fad91bda4e2efd1ff996d4346f3d3ececc522e0e759b6e0fa34
started_at_utc:   2026-08-29T15:07:20.231747+00:00
completed_at_utc: 2026-08-29T15:07:20.294213+00:00
```

Zero valor hardcoded na ferramenta — o `node_ref` e os hashes acima são
**saída**, não entrada, da execução genérica contra os 312 nodes reais.

## Anomalia encontrada, investigada e corrigida na hora (transparência total)

A resposta JSON da PRIMEIRA execução (`--apply`) reportou
`main_db_unchanged: true` e `post_migration_scan` ainda mostrando
`allowed_mutable_capacity_drift_count: 1` — **aparentando que a migração
não tinha feito efeito**, apesar de `status: APPLIED` e dos
before/after_hashes corretos.

Investigação imediata (read-only, sem re-tentar nada):

- `sha256sum` externo ao script, logo após ele terminar, mostrou o arquivo
  principal com hash **diferente** (`7b58e86a...`, +8192 bytes) do valor
  que o próprio script tinha reportado como "hash_after" — E nenhum
  `-wal`/`-shm` restava no disco.
- Uma reauditoria independente nova (processo Python separado) contra o
  arquivo já finalizado confirmou: `capacity_units:58`,
  `definition_hash:21945ee6...` (bate exatamente com `after_hashes`),
  linha de migração presente e correta, **scan completo dos 312 nodes:
  0 drift de qualquer tipo**.

**Conclusão**: o `COMMIT` já tinha se efetivado corretamente — a transação
SQLite era válida e durável desde o primeiro momento. O bug estava
exclusivamente na AUTOVERIFICAÇÃO imediata da ferramenta: ela abria uma
conexão `mode=ro&immutable=1` (que por design nunca consulta um arquivo
`-wal`) e lia o hash do arquivo principal via `sha256_file()` logo após o
`COMMIT`, **antes de qualquer checkpoint** — enquanto os frames recém
commitados ainda viviam só no WAL, os bytes do arquivo principal (e
portanto a leitura `immutable=1`) ainda refletiam o estado anterior. Isso
não é uma falha de integridade de dado — é uma falha de visibilidade da
própria verificação.

**Correção aplicada imediatamente**: `PRAGMA wal_checkpoint(FULL)`
adicionado logo após o `COMMIT`, antes de abrir a conexão de
pós-verificação. Teste de regressão criado e passando
(`test_38_apply_hash_after_and_post_scan_reflect_the_actual_committed_state`).
Nenhuma segunda tentativa de escrita foi feita no DB real — a correção foi
só na ferramenta; o dado real já estava correto.

## Reauditoria final pós-correção (nova execução, dry-run)

```
prior_migration_state: COMPLETE_AND_VERIFIED
status: ALREADY_APPLIED
scan: {total_nodes: 312, matching: 312, allowed_mutable_capacity_drift_count: 0,
       structural_drift_count: 0, unsupported_drift_count: 0,
       country_scale_state_self_consistent: true}
main_db_unchanged: true
```

**312/312 nodes agora batem perfeitamente. Zero drift de qualquer classe.**

## Primeiro resume_world() controlado (raw engine)

`IntegratedARPGEngineV16A` construído contra o DB real (contrato Stage17
instalado antes), `resume_world(world_instance_id)` chamado uma única vez.

- `resume_world_raised: false`, `resume_world_status: "PASS"`.
- `gathering.verify()`: `{status: PASS, nodes: 312, failures: [],
  activities: {MINING:166, LOGGING:14, FORAGING:28, AGRICULTURE:14,
  HUNTING:87, FISHING:3}}`.
- `movement.verify()`: `{status: PASS, failures: [], states: 826}` — sem
  `MOTION_OWNER_DIVERGENCE` (o reparo de ownership de uma rodada anterior
  já havia resolvido a consistência ownership-vs-posição; o deslocamento
  de ~2200 km em si é um problema de posição, não de integridade —
  permanece intocado, ver abaixo).
- `reconciliation_log_during_resume: []` — o mecanismo de reconciliação em
  runtime do contrato Stage17 **não precisou disparar nenhuma vez**,
  porque a migração offline já havia deixado tudo sincronizado antes do
  boot. Confirma a sequência pretendida (Seção 8 da autorização): migração
  primeiro, runtime depois.
- Prova de zero mutação semântica: hash combinado de
  `arpg_gathering_nodes` (312 linhas), `v15_motion_state` (826 linhas,
  posição do Player byte-idêntica) e `chunk_entity_ownership` (826 linhas)
  **idênticos antes e depois** do resume. Único diff físico: arquivo
  principal cresceu (`7b58e86a...`→`2df3d4c5...`, +8192 bytes) e a tabela
  `country_scale_events` ganhou 1 linha nova — inspecionada e confirmada
  como um evento `SCENE_SYSTEM_BOOTSTRAPPED` com payload **idêntico** aos
  95 anteriores (`{"dungeons":12,"objects":423}`) — um log de auditoria
  append-only de um subsistema protegido pré-existente que já dispara em
  todo `resume_world()`, não uma mutação de estado de jogo.

## Backend health smoke (Section 32 — sem Godot)

`Stage16BAuthorityAdapter()` construído com as variáveis de ambiente
apontando para os caminhos reais confirmados (DB, save_root, master
release, manifesto de placement) — o MESMO caminho de boot que a produção
real usa (`_boot()` → `_resume_world_with_immutable_gathering_definitions()`).

- `bootstrap_mode: "RESUMED"`.
- `gathering_resume_compatibility: {status: "NOT_NEEDED", adjustments: []}`
  — o wrapper de compatibilidade pré-existente (Stage16B) não encontrou
  mais nenhuma divergência para compensar, porque a migração formal já
  havia normalizado tudo. Confirma coexistência harmoniosa entre o
  mecanismo antigo e o novo contrato Stage17.
- `health.status: "PASS"`, `arpg_health/stage15_health/stage16a_health:
  PASS`, `failures: []`.
- `resource_metric_placement: {status: PASS, placement_count: 2,
  constraint_count: 1, inserted: 0, replayed: 2, idempotent: true,
  canonical_manifest_hash: f0c79305...}` — **C1B intacto e íntegro**.
- `development_profile_bootstrap.combat_encounter.targets`: COMMON a
  80.295 km (gap já documentado, preservado), ALPHA a **2.194.278 m**
  (~2194 km) — confirmação numérica direta e independente do deslocamento
  do Player, preservado sem alteração.
- Zero mutação semântica adicional: hashes combinados de
  `arpg_gathering_nodes`/`v15_motion_state`/`chunk_entity_ownership`
  idênticos antes/depois deste boot também.

## Housekeeping final

Backend OFF, sem listener 8000, backup preservado
(`_archive_pre_s17_c3r4_gathering_migration_20260829T150548Z_authority`,
hash `c84d1bda...` intacto), editor Godot pré-existente do usuário
preservado (PID 11316, não tocado), Stage16B `CLOSED/READ_ONLY`
inalterado. DB real final: hash `481d0eea...`, sem `-wal`/`-shm`.

## Player recovery

Continua necessário e **não executado nesta rodada** (explicitamente
proibido). A ferramenta `repair_stage17_player_position.py` permanece
`SAFE_TO_EXECUTE_WITH_EXPLICIT_AUTHOR_APPROVAL`, e agora, com
`CURRENT_WORLD_RESUMABLE=true`, seu `--apply` deixou de estar bloqueado
pelo drift de gathering — pode ser autorizado em uma rodada futura
dedicada.
