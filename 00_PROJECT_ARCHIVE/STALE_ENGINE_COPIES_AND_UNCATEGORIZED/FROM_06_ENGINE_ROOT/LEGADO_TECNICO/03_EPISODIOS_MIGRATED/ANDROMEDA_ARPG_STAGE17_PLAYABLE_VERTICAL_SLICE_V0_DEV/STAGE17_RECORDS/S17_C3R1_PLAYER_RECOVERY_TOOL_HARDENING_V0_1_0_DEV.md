# Stage17 / Etapa 31 — S17-C3R1 Player Recovery Tool Hardening

Status: `S17_C3R1_PLAYER_RECOVERY_TOOL_HARDENING = PASS`

Nenhum reparo foi executado. `--apply` nunca foi chamado nesta rodada.

## Evidência histórica preservada

Script original (não sobrescrito, permanece intacto no scratchpad da sessão):

- `ORIGINAL_SCRIPT_PATH`: `.../scratchpad/repair_player_position.py`
- `ORIGINAL_SCRIPT_SHA256`: `b6f29a1cc08dbf221eaadd85700053e5ffe61e682a9558ca98ea1e22dd809d33`
- `ORIGINAL_SCRIPT_SIZE`: 4149 bytes

## Script hardened (novo arquivo)

- Path: `STAGE17_TOOLS/recovery/repair_stage17_player_position.py`
- `HARDENED_SCRIPT_SHA256`: `a33b0b7a50794ab58fa382becb52ffcc6eef52f0a718b09096bc44e09b039854`
- Size: 21460 bytes

## As 4 correções da autorização, aplicadas

1. **Destino dinâmico** — removidos `HOME_ISO_X`/`HOME_ISO_Y` hardcoded. O
   destino agora é lido em tempo de execução de
   `STAGE17_CONTENT/RESOURCE_PLACEMENT/CANONICAL/S17_RESOURCE_METRIC_PLACEMENTS_R0001.json`,
   especificamente `canonical_manifest.world_binding.anchor_position` (o
   anchor formal de autoria, não a posição de um Resource individual como
   TREE). `load_and_validate_manifest()` valida schema_version,
   placement_revision, presença de `placements`, presença e finitude de
   `iso_x_m/iso_y_m/altitude_m`, e que `anchor_kind` pertence ao contrato
   aceito (`ACCEPTED_ANCHOR_KINDS`). Qualquer falha aborta com um
   `RecoveryError` código-específico — nenhum fallback hardcoded existe.
2. **World guard dinâmico** — `resolve_stored_world_instance_id()` lê
   `s16b_bootstrap['world_instance_id']` via uma conexão sqlite3
   genuinamente somente-leitura (`mode=ro&immutable=1`) antes de qualquer
   outra coisa. `enforce_world_guard()` compara esse valor contra
   `manifest.world_binding.world_instance_id` e aborta com
   `STAGE17_RECOVERY_WORLD_MISMATCH` se divergirem. `resume_world()` só é
   chamado depois, com o ID **lido**, nunca um literal. Não existe
   `--world-id` nem argumento equivalente — o mundo vem inteiramente do
   próprio estado Stage17.
3. **Player dinâmico** — `PLAYER_REF` hardcoded removido.
   `resolve_avatar()` replica exatamente a semântica de
   `Stage16BAuthorityAdapter._ensure_player_ref()`: lê `profile_ref` de
   `s16b_bootstrap` (via a conexão já aberta do próprio engine, sem abrir
   uma segunda conexão), resolve `engine.arpg(world_id).profile(profile_ref)`,
   extrai `avatar_ref`, e valida que `movement.state(avatar_ref)` existe.
   Nenhuma chamada privada/sem contrato ao adapter foi feita — apenas os
   mesmos métodos públicos do engine que o próprio adapter usa.
4. **Finitude** — `math.isfinite` (via `_finite()`) é exigido para
   `iso_x_m`, `iso_y_m` e `altitude_m` do anchor durante a validação do
   manifesto, antes de qualquer chamada a `sync_to_geodetic`. Altitude
   ausente é tratada como `ANCHOR_INVALID`, nunca substituída por `0.0`
   silenciosamente (o contrato atual do manifesto sempre inclui
   `altitude_m`, então essa exigência é estrita, não uma suposição nova).

## Descoberta durante o hardening: dry-run original tinha efeito colateral real

A primeira versão do script hardened ainda abria o `IntegratedARPGEngineV16A`
completo (via `resume_world()`) mesmo em modo dry-run, para validar
identidade/posição/verify. Executei esse dry-run uma vez contra o mundo real
(autorizado pela Seção 26) e ele **falhou com uma exceção nova e diferente**
(`IntegrityError: gathering node drift:GTH-1D268772796B25C4CC6B` — não
relacionada a `MOTION_OWNER_DIVERGENCE`). Comparando hash do arquivo
principal antes/depois: **o hash mudou** (`6748cb7b...` → `c84d1bda...`,
tamanho +155.648 bytes) e os arquivos `-wal`/`-shm` foram consumidos por um
checkpoint automático. Isso prova, por medição direta, que abrir o engine
não é livre de efeito colateral mesmo quando a chamada falha.

Correção aplicada imediatamente, conforme a Seção 34 da autorização: o modo
dry-run agora **nunca constrói o engine completo**. Ele executa somente os
passos providamente sem escrita (leitura do manifesto + leitura
`s16b_bootstrap` via `mode=ro&immutable=1`) e reporta explicitamente
`engine_dependent_validation: SKIPPED_DRY_RUN_ENGINE_OPEN_HAS_SIDE_EFFECTS`
para tudo que dependeria do engine (avatar, posição, chunk, verify). Re-testei
o dry-run corrigido duas vezes com hash antes/depois: **arquivo principal
byte-idêntico, nenhum `-wal`/`-shm` criado** (prova em
`S17_C3R1_PLAYER_RECOVERY_TOOL_AUDIT_V0_1_0_DEV.json`).

Descobri também que uma conexão `mode=ro` simples (sem `immutable=1`) para um
DB em modo WAL cria arquivos `-wal`/`-shm` vazios só de abrir — não é uma
mutação de dado, mas é uma mutação do sistema de arquivos que uma alegação
de "dry-run" não deveria deixar passar sem prova. `immutable=1` elimina isso
por completo (testado e confirmado).

## Achado novo, não relacionado à ferramenta: `gathering node drift`

`GTH-1D268772796B25C4CC6B` (o mesmo nó HUNTING usado no diagnóstico C3A
desta sessão) agora falha a checagem de integridade de hash em
`ARPGGatheringWorkCore._insert_node()` durante `resume_world()`. Isso
**bloqueia qualquer `resume_world()` no mundo atual**, incluindo uma futura
execução `--apply` desta ferramenta, que também chama `resume_world()`.
Este achado é preservado apenas como registro — nenhuma investigação ou
correção foi feita (fora de escopo desta rodada: só a ferramenta de
recovery e records podem ser tocados). Este bloqueio precisa ser resolvido
antes que `--apply` possa ser tentado com sucesso.

## Testes

`STAGE17_TOOLS/tests/test_repair_stage17_player_position.py` — 18 testes,
todos PASS, cobrindo: parsing de manifesto válido, ausência de arquivo,
schema_version errado, anchor NaN, world_binding ausente, anchor_kind não
aceito, altitude ausente, world guard match/mismatch, provenance
match/mismatch, helper de finitude, e 6 testes de integridade estática de
código-fonte (sem coordenada/PLAYER_REF hardcoded, sem DML SQL dentro de
`.execute()`, sem import de módulos protegidos, gate `--apply` presente,
conexão `immutable=1` presente). Nenhum desses testes toca o DB real.

## `--apply`

**Nunca executado nesta rodada**, nem antes nem depois do hardening.
