# Stage16B Authority Adapter — Mapa de Autoridade (Fase 1 + Fase 2)

Documento produzido **antes** de qualquer edição de código.
Escopo: camada de transporte/adaptação HTTP sobre os cores ARPG/Living já existentes.
Nenhuma regra de gameplay é reimplementada aqui.

---

## 1. Arquitetura autoritativa encontrada

```
IntegratedARPGEngineV16A            01_RUNTIME/integrated_arpg_engine_v16a.py
  └─ IntegratedARPGEngineV15        01_RUNTIME/integrated_arpg_engine_v15.py   (Stage15 save/recovery)
       └─ IntegratedARPGEngineV14 … V01                                        (Stage01-14 ARPG cores)
            └─ IntegratedLivingEngineV15  01_RUNTIME/integrated_engine_v15.py  (traversal/ambiente/Godot adapter)
                 └─ … IntegratedLivingEngineV11  01_RUNTIME/integrated_engine.py
                      └─ LivingRuntime          01_RUNTIME/living_runtime.py   (SQLite + Master READ_ONLY)
```

Composições anexadas por `world_instance_id`:

| acessor | classe | arquivo | papel |
|---|---|---|---|
| `engine.godot(wid)` | `GodotIsometricAdapterV15` | `godot_adapter_v15.py` | **autoridade de sessão + snapshot + comando do cliente** |
| `engine.movement(wid)` | `ContinuousMovementSystem` | `continuous_movement.py` | **autoridade de movimento** (`step_vector`, stamina, relógio, chunk) |
| `engine.collision(wid)` | `CollisionInteractionSystem` | `collision_interaction.py` | gate de colisão (`point_blocked`) |
| `engine.environment(wid)` | `EnvironmentSimulationSystem` | `environment_simulation.py` | `movement_factor` |
| `engine.streaming(wid)` | streaming/ownership | `streaming_system.py` | posse de chunk |
| `engine.atlas_lod(wid)` | `AtlasCountryLOD` | `atlas_country_lod.py` | `godot_chunk_payload` |
| `engine.discovery(wid)` | `PlayerDiscoverySystem` | `player_discovery.py` | filtro de visibilidade |
| `engine.country(wid)` | `CountryScale` | `country_scale.py` | registros de NPC/blocos/cidades |
| `engine.arpg(wid)` | `ARPGGameCore` | `arpg_game_core.py` | perfis do jogador (`profile_ref`) |
| `engine.stage16a(wid)` | `VerticalSliceAssemblyCore` | `arpg_vertical_slice_assembly_core.py` | fachada Stage16A (ground loot, água/bag, HUD, intents) |
| `engine.save_recovery(wid)` | `ARPGSaveRecoveryCore` | `arpg_save_recovery_core.py` | Stage15 save/restore/death |

Bootstrap medido (Python 3.14.6, Master V2.0.1):
`engine.__init__` 0,79 s · `create_world` 16,4 s · `create_profile` 3,0 s · `resume_world` 4,5 s.

### 1.1 Idempotência/replay já existentes nos cores

Padrão canônico: tabela de eventos com `event_ref` como chave; replay devolve o resultado
gravado com `idempotent_replay: true`.
Presente em `arpg_item_core`, `arpg_resource_core`, `arpg_skill_core`, `arpg_ground_loot_core`,
`arpg_economy_crafting_core`, `arpg_narrative_culture_core`, `arpg_technology_machine_robotics_core`,
`arpg_mobility_infrastructure_core`, `arpg_living_integration_core`, `arpg_vertical_slice_assembly_core`.

**`ContinuousMovementSystem.step_vector` NÃO tem `event_ref` nem idempotência.**
Confirmado em runtime: dois `MOVE_VECTOR` idênticos aplicam o passo duas vezes.
→ a supressão de replay de movimento é responsabilidade da camada de transporte.

### 1.2 Sessão já é autoritativa no core

`GodotIsometricAdapterV15` mantém `v15_godot_sessions(world_instance_id, session_ref,
player_ref, role, active, payload_hash)` com hash SHA-256 do payload; `_session()` recusa
linha ausente, inativa ou com hash divergente; `client_command`/`client_snapshot`
**resolvem `player_ref` a partir de `session_ref`** — o cliente nunca fornece o ator.
Verificado: sessão errada → `REJECTED / UNKNOWN_OR_INACTIVE_SESSION`; a tabela sobrevive a restart.

Ou seja, a falha de sessão do servidor histórico **não é do core**: `living_api.py` ignora o
`session_ref` do cliente e injeta uma constante `GODOT-FASTAPI-001`.

### 1.3 Stage15 save/resume

`ARPGSaveRecoveryCore`: `create_snapshot`, `verify_slot`, `restore_slot_to`, `rollback_slot`,
`recover_death`, `set_safe_waypoint`, `ensure_profile`, `verify`.
Continuidade de processo não depende de slot: `IntegratedARPGEngineV16A.resume_world(wid)`
reidrata tudo a partir do mesmo SQLite. Verificado: motion state e sessão sobrevivem ao restart.

---

## 2. Restrição de baseline (determinante do desenho)

O checkpoint protegido
`C:\Users\thall\Documents\ARPG CODEX\ANDROMEDA_ARPG_STAGE16A_PRE_GODOT_V1_8_0_DEV_CHECKPOINT_V0_8_0.zip`
foi verificado byte a byte contra a árvore de trabalho: **724 entradas, 724 verificadas,
0 ausentes, 0 divergentes**. `01_RUNTIME/`, `02_CONTRACTS/`, `03_TESTS/` estão **integralmente
congelados**.

Consequência: `godot_adapter_v15.py` **não pode receber** `MOVE_TO_POINT`.
`MOVE_TO_POINT` é implementado no adapter novo como **tradução de parâmetros** para o
caminho autoritativo `MOVE_VECTOR` já existente. Nenhum arquivo protegido é tocado;
todo o trabalho é aditivo em `12_AUTHORITY_BACKEND/`.

---

## 3. Mapa: HTTP → adapter → core autoritativo → tabelas/eventos

| HTTP | adapter method | core autoritativo chamado | tabelas / eventos persistidos |
|---|---|---|---|
| `GET /health` | `Stage16BAuthorityAdapter.health()` | `engine.health_arpg_v16a(wid)` → `health_arpg_v15` → `health_v15` → `stage16a.verify()`; `runtime.master_version` / `master_release_sha256` | nenhuma escrita (somente leitura) |
| `POST /session/bind` | `bind_session(session_ref)` | `engine.godot(wid).bind_session(session_ref, player_ref_resolvido_pelo_servidor, 'PLAYER')` | `v15_godot_sessions` (core) |
| `POST /session/revoke` | `revoke_session(session_ref)` | `engine.godot(wid).revoke_session(session_ref)` | `v15_godot_sessions` (core) |
| `GET /snapshot?session_ref=` | `snapshot(session_ref)` | `engine.godot(wid).client_snapshot(session_ref)` → `movement.state`, `streaming.owners`, `atlas_lod.godot_chunk_payload`, `environment.state_for_block`, `discovery.known` | lê `v15_godot_sessions`, `v15_motion_state`; escreve `s16b_snapshot_cursor` (adapter) |
| `POST /session/resync` | `resync(session_ref, last_snapshot_sequence?, last_snapshot_id?)` | idem `/snapshot` | lê/escreve `s16b_snapshot_cursor` |
| `POST /command` `MOVE_TO_POINT` | `command(envelope)` → `_move_to_point()` | `engine.godot(wid)._session()` (resolve ator) · `movement.state()` · `environment.state_for_block()` · `engine.godot(wid).client_command(session_ref,'MOVE_VECTOR',…)` → `collision.point_blocked()` → `movement.step_vector()` | escreve `v15_motion_state` (core), `s16b_command_journal` (adapter); efeitos colaterais do core: `streaming.transfer`, `country.reconcile_country_inventory`, avanço de ticks via `orchestrator.run_steps` |

Tabelas novas do adapter (prefixo `s16b_`, no mesmo SQLite do mundo):

```sql
s16b_bootstrap(key PK, value)                       -- world_instance_id, profile_ref, seed, owner_scope
s16b_snapshot_cursor(world_instance_id, session_ref PK,
                     last_sequence, last_snapshot_id, payload_hash)
s16b_command_journal(world_instance_id, command_ref PK,
                     session_ref, command, envelope_hash, result_json, result_hash)
```

Nenhuma tabela de gameplay é criada. Nenhuma regra de dano, inventário, stamina, economia,
quest ou morte é replicada.

---

## 4. Contratos B01 / Stage16A que o backend precisa satisfazer

Fonte: `07_GODOT_ARPG_STAGE16B/scripts/runtime/andromeda_bridge.gd` e `client_session.gd`.

1. **Transporte**: `andromeda_bridge.gd` trata `response_code != 200` como erro de transporte
   e entra em backoff de reconexão. Logo, **rejeições de domínio devem ser HTTP 200** com
   `{"status":"REJECTED","reason":…}`.
2. **Snapshot** deve ter `status == "PASS"`, `server_authoritative == true`,
   `transform.iso_x_m`/`iso_y_m` finitos, `chunk` dicionário, `chunk.entities` array com
   `entity_ref` não vazio e **sem duplicatas**.
3. **`session_ref` no snapshot**: se presente, precisa bater com o do cliente
   (`SNAPSHOT_SESSION_MISMATCH`).
4. **`snapshot_id`**: string não vazia (senão `EMPTY_SNAPSHOT_ID`).
5. **`snapshot_sequence`**: precisa ser `TYPE_INT` (inteiro JSON, nunca float/string),
   `>= 0` e **estritamente crescente**; `<=` último aceito ⇒ `STALE_OR_DUPLICATE_SNAPSHOT`.
6. **Comando**: envelope `{"session_ref", "command", "params"}`; sucesso exige `status == "PASS"`.
7. **Guarda de autoridade**: o cliente já bloqueia `player_ref`, `damage*`, `inventory_grant`,
   `currency_result`, `quest_completion*`, `canon*_mutation`, `death_result`, `bag_contents`,
   `authoritative_ttl` e tokens de comando `DAMAGE/GRANT/CURRENCY_RESULT/QUEST_COMPLETION/
   CANON/DEATH_RESULT/BAG_CONTENT/TTL_RESULT`. **O servidor precisa reaplicar isso**, pois a
   guarda do cliente não é confiável.
8. Manifesto Stage16A: `server_rule = DO_NOT_REIMPLEMENT_AUTHORITATIVE_GAMEPLAY_RULES_IN_GDSCRIPT`,
   `master = ANDROMEDA_CODEX_MASTER_V2_0_1_READ_ONLY`, `canon_mutation = false`.

### 4.1 Lacunas do cliente B01 (bloqueiam o round-trip; NÃO corrigidas nesta rodada)

- `request_snapshot()` faz `GET /snapshot` **sem** `session_ref` → o servidor não tem como
  validar a sessão. Correção de uma linha no lado Godot (próxima rodada).
- O envelope de comando não carrega chave de idempotência → o servidor não consegue
  distinguir retry de repetição legítima. Correção de duas linhas no lado Godot.

---

## 5. Desenho mínimo (Fase 2)

### 5.1 Superfície HTTP

```
GET  /health
POST /session/bind      {"session_ref": "..."}
POST /session/revoke    {"session_ref": "..."}
GET  /snapshot?session_ref=...            (ou header X-Andromeda-Session)
POST /session/resync    {"session_ref", "last_snapshot_sequence"?, "last_snapshot_id"?}
POST /command           {"session_ref", "command", "params", "command_ref"}
```

Sem endpoint de gameplay. Sem endpoint de escrita de canon.

### 5.2 Snapshot — campos mínimos garantidos

```jsonc
{
  "status": "PASS",
  "server_authoritative": true,
  "session_ref": "...",
  "snapshot_id": "S16B-<seq>-<sha16>",
  "snapshot_sequence": 1,              // int, estritamente crescente por sessão, persistido
  "identity": {                        // world/profile identity
    "world_instance_id", "owner_scope", "world_seed",
    "profile_ref", "avatar_ref",
    "engine_class", "engine_version", "engine_authority",
    "master_version", "master_release_sha256"
  },
  "player_ref": "...",                 // projetado pelo servidor (nunca aceito do cliente)
  "transform": {...}, "chunk": {...}, "environment": {...},  // state projection do core
  "authority": "GODOT_CLIENT_ADAPTER_SERVER_AUTHORITATIVE",
  "adapter_authority": "ANDROMEDA_STAGE16B_AUTHORITY_ADAPTER_TRANSPORT_ONLY"
}
```

### 5.3 Comando — regras

1. Envelope precisa de `session_ref`, `command`, `command_ref`; `params` opcional (dict).
2. Varredura recursiva do corpo inteiro: qualquer campo autoritativo ⇒
   `CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN` + `field_path`.
3. Token de comando proibido ⇒ `CLIENT_AUTHORITATIVE_COMMAND_FORBIDDEN`.
4. Comando fora da allowlist da rodada ⇒ `COMMAND_NOT_ENABLED_IN_THIS_ROUND`.
5. Sessão inválida/desconhecida/revogada ⇒ `UNKNOWN_OR_INACTIVE_SESSION` (decidido pelo core).
6. `command_ref` já registrado:
   - mesma sessão + mesmo payload ⇒ devolve o resultado gravado com
     `idempotent_replay: true`, `replay_suppressed: true`, **sem reaplicar**;
   - sessão diferente ⇒ `COMMAND_REF_SESSION_MISMATCH`;
   - payload diferente ⇒ `COMMAND_REF_PAYLOAD_MISMATCH`.
7. Comandos que possuem `event_ref` próprio nos cores (rodadas futuras) recebem o
   `command_ref` como `event_ref`, preservando a idempotência nativa do core.

### 5.4 `MOVE_TO_POINT` — tradução, não regra nova

```
params: {"iso_x_m": float, "iso_y_m": float, "duration_s"?: float, "mode"?: "WALK"|"RUN"|"CROUCH"}

player_ref  ← godot._session(session_ref)['player_ref']           (core resolve o ator)
atual       ← movement.state(player_ref)                          (core)
dx, dy      = alvo − atual
speed       = movement.SPEEDS_MPS[mode]                           (constante do core)
envf        = environment.state_for_block(npc['block_id'])['movement_factor']  (core)
duration_s  = min(duration_pedida, restante / (speed · envf))     ← única decisão do adapter
delegação   → godot.client_command(session_ref, 'MOVE_VECTOR', {dx, dy, duration_s, mode})
                → collision.point_blocked()   (core)
                → movement.step_vector()      (core: distância, stamina, relógio, chunk, fronteira)
```

O adapter **não** calcula posição, stamina, colisão ou tempo. Escolhe apenas `duration_s`
para não ultrapassar o alvo. Teste dedicado garante `moved_m <= distância_restante + 1e-6`.

### 5.5 Reconnect / resync

`POST /session/resync` revalida a sessão, compara o cursor apresentado com o cursor emitido
pelo servidor (`FRESH` / `CURRENT` / `STALE_OR_DUPLICATE` / `UNKNOWN_SNAPSHOT_SEQUENCE` /
`SNAPSHOT_ID_MISMATCH` / `NO_CURSOR`) e devolve um snapshot novo com sequência nova.
O cursor é persistido, portanto sobrevive a restart do processo.

---

## 6. Invariantes preservados

- Master V2.0.1 READ_ONLY; SHA-256 conferido na inicialização; qualquer caminho contendo
  `V2_1_0`/`V2.1.0` é recusado na configuração.
- `SUPPORTED_MASTER_RELEASES` do runtime já aceita **somente** V2.0.1 — nenhuma promoção.
- Checkpoint Stage16A: zero bytes alterados (trabalho puramente aditivo).
- Baseline Living V1.5 histórica: não editada.
- Sem mutação de cânone: nenhum caminho de escrita no Master.
