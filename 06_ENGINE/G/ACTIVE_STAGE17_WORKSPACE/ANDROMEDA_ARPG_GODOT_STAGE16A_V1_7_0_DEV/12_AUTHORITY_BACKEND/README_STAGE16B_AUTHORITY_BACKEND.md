# Stage16B Authority Backend — V0.8.0

Camada de **transporte/adaptação** HTTP sobre a autoridade ARPG existente
(`IntegratedARPGEngineV16A` / Stage01-16A / Living V1.5).

Não é um backend substituto. Não contém regra de dano, inventário, stamina, economia,
quest, morte, craft, TTL ou cânone. Todo resultado de gameplay é produzido pelos cores
protegidos em `01_RUNTIME/`.

Mapa completo de autoridade: [`STAGE16B_AUTHORITY_ADAPTER_MAP_V0_8_0.md`](STAGE16B_AUTHORITY_ADAPTER_MAP_V0_8_0.md).

---

## Arquivos

| arquivo | papel |
|---|---|
| `authority_config.py` | resolve caminhos e **recusa qualquer master que não seja V2.0.1** |
| `andromeda_authority_adapter.py` | adapter (sem HTTP): sessão, snapshot, comando, replay, cursor |
| `stage16b_authority_api.py` | casca FastAPI: request → um método do adapter → resposta |
| `tests/test_stage16b_authority_adapter.py` | 35 testes do adapter |
| `tests/test_stage16b_authority_http.py` | 16 testes de round-trip HTTP real + restart do servidor |
| `run_stage16b_authority_validation.py` | runner único de validação com evidência JSON |
| `var/` | mundo SQLite autoritativo + saves Stage15 (gerado em runtime) |
| `reports/` | evidência das execuções |

---

## Python / venv

```
Python           3.14.6
venv             C:\Users\thall\ANDROMEDA_PRODUCT\.venv
fastapi          0.141.1
uvicorn          0.52.3
```

Nenhuma dependência nova foi instalada. `httpx` não está presente no venv, por isso a
suíte HTTP usa `urllib` contra um processo uvicorn real em vez de `TestClient`.

## Comando para iniciar o backend

```bash
cd "C:/Users/thall/Documents/andromeda-argp/ANDROMEDA_ARPG_GODOT_STAGE16A_V1_7_0_DEV/12_AUTHORITY_BACKEND" && "C:/Users/thall/ANDROMEDA_PRODUCT/.venv/Scripts/python.exe" -m uvicorn stage16b_authority_api:app --host 127.0.0.1 --port 8000 --workers 1
```

`--workers 1` é obrigatório: um único processo é dono do mundo SQLite autoritativo.

O primeiro start cria o mundo (~20 s: `create_world` ≈ 16 s + `create_profile` ≈ 3 s).
Os starts seguintes fazem `resume_world` (~5 s). `GET /health` só devolve `PASS` quando
o bootstrap terminou.

### Variáveis de ambiente

| variável | default | efeito |
|---|---|---|
| `ANDROMEDA_MASTER_RELEASE` | `C:\Users\thall\ANDROMEDA_PRODUCT\ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip` | master READ_ONLY; SHA-256 conferido no boot |
| `ANDROMEDA_S16B_VAR` | `12_AUTHORITY_BACKEND/var` | raiz de dados de runtime |
| `ANDROMEDA_S16B_DB` | `<var>/stage16b_world.sqlite` | mundo autoritativo |
| `ANDROMEDA_S16B_SAVE_ROOT` | `<var>/saves` | snapshots Stage15 |
| `ANDROMEDA_S16B_SEED` | `160800` | seed do mundo (apenas na criação) |
| `ANDROMEDA_S16B_OWNER_SCOPE` | `stage16b:authority` | owner scope do mundo |
| `ANDROMEDA_S16B_PLAYER_CLASS` | `WARRIOR` | classe do ator resolvido pelo servidor |

## Comando para rodar a validação completa

```bash
cd "C:/Users/thall/Documents/andromeda-argp/ANDROMEDA_ARPG_GODOT_STAGE16A_V1_7_0_DEV/12_AUTHORITY_BACKEND" && "C:/Users/thall/ANDROMEDA_PRODUCT/.venv/Scripts/python.exe" run_stage16b_authority_validation.py
```

---

## Endpoints

| método | rota | descrição |
|---|---|---|
| `GET` | `/health` | estado autoritativo, identidade, master, gates Stage15/16A |
| `POST` | `/session/bind` | abre/reata uma sessão; o **servidor** escolhe o ator |
| `POST` | `/session/revoke` | encerra a sessão |
| `GET` | `/snapshot?session_ref=…` | snapshot autoritativo (também aceita `X-Andromeda-Session`) |
| `POST` | `/session/resync` | reconnect/resync + avaliação de cursor stale |
| `POST` | `/command` | envelope de intenção (`MOVE_TO_POINT` nesta rodada) |

**Toda rejeição de domínio volta como HTTP 200** com `{"status":"REJECTED","reason":…}`,
porque `andromeda_bridge.gd` interpreta qualquer código != 200 como falha de transporte
e entra em backoff de reconexão.

---

## Exemplos reais de request/response

Capturados de uma execução real deste adapter (payloads longos truncados).

### `GET /health`

```json
{
  "status": "PASS",
  "service": "ANDROMEDA_STAGE16B_AUTHORITY_ADAPTER",
  "server_authoritative": true,
  "adapter_version": "V0.8.0-STAGE16B-AUTHORITY-ADAPTER",
  "bootstrap_mode": "CREATED",
  "identity": {
    "world_instance_id": "rt:world:7841cfd5-36c0-40ae-8225-e60adddc012a",
    "owner_scope": "stage16b:examples",
    "world_seed": 160833,
    "profile_ref": "rt:player_profile:22bdd8c5-f4fe-467d-94c6-73317921786b",
    "avatar_ref": "PLY-5DCCD813D14345BE89FB383B65DDBC79",
    "engine_class": "IntegratedARPGEngineV16A",
    "engine_version": "ARPG-V1.8.0-DEV-PRE-GODOT",
    "engine_authority": "ANDROMEDA_ARPG_STAGE16A_VERTICAL_SLICE_PRE_GODOT",
    "master_version": "V2.0.1",
    "master_release_sha256": "6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2"
  },
  "master": { "version": "V2.0.1", "read_only": true },
  "arpg_health": "PASS",
  "stage15_health": "PASS",
  "stage16a_health": "PASS",
  "failures": [],
  "enabled_commands": ["MOVE_TO_POINT"]
}
```

### `POST /session/bind`

Request: `{"session_ref": "GODOT-STAGE16B-001"}`

```json
{
  "status": "PASS",
  "session_ref": "GODOT-STAGE16B-001",
  "player_ref": "NPC-01-01-01-015",
  "role": "PLAYER",
  "authority": "GODOT_CLIENT_ADAPTER_SERVER_AUTHORITATIVE",
  "rebound": false,
  "cursor": { "last_snapshot_sequence": null, "last_snapshot_id": null },
  "enabled_commands": ["MOVE_TO_POINT"]
}
```

O `player_ref` é **decidido pelo servidor**. Se o cliente enviar `player_ref`, a requisição
é recusada.

### `GET /snapshot?session_ref=GODOT-STAGE16B-001`

```json
{
  "status": "PASS",
  "server_authoritative": true,
  "session_ref": "GODOT-STAGE16B-001",
  "snapshot_id": "S16B-000000000000-70d6ead2cdab3ece",
  "snapshot_sequence": 0,
  "player_ref": "NPC-01-01-01-015",
  "authority": "GODOT_CLIENT_ADAPTER_SERVER_AUTHORITATIVE",
  "identity": { "world_instance_id": "rt:world:7841cfd5-…", "master_version": "V2.0.1" },
  "transform": {
    "iso_x_m": 172477.37778480785,
    "iso_y_m": -1472483.0970637298,
    "altitude_m": 0.0,
    "heading_deg": 0.0
  },
  "environment": { "block_id": "STA-01-BLK-01", "movement_factor": 0.88, "visibility": 0.15 },
  "chunk": {
    "chunk_id": "CHK--000225--000284",
    "tile_size_m": 2.0,
    "entity_count": 24,
    "npc_positions_authority": "V1.5_MOTION_STATE",
    "entities": [
      { "entity_ref": "CITY-01-01-01", "kind": "CITY", "isometric": { "x_m": 172477.3778, "y_m": -1472483.0971, "z_m": 0.0 } }
    ]
  }
}
```

`snapshot_sequence` é inteiro, começa em 0, cresce estritamente por sessão e é
**persistido** — sobrevive ao restart do processo. `snapshot_id` carrega a sequência,
portanto é único mesmo quando a projeção do mundo não mudou entre dois snapshots.

### `POST /command` — `MOVE_TO_POINT`

Request:

```json
{
  "session_ref": "GODOT-STAGE16B-001",
  "command": "MOVE_TO_POINT",
  "command_ref": "CR-DOC-0001",
  "params": { "iso_x_m": 172480.37778480785, "iso_y_m": -1472483.0970637298, "duration_s": 0.25, "mode": "WALK" }
}
```

Response (o corpo do core vem inteiro; o adapter só acrescenta os campos de tradução):

```json
{
  "status": "PASS",
  "entity_ref": "NPC-01-01-01-015",
  "moved_m": 0.352,
  "mode": "WALK",
  "stamina": 100.0,
  "iso_x_m": 172477.729785,
  "iso_y_m": -1472483.097064,
  "geodetic": { "longitude": -18.596649992301305, "latitude": -3.7966834803483835, "altitude_m": 0.0 },
  "chunk_id": "CHK--000225--000284",
  "chunk_changed": false,
  "block_changed": false,
  "travel_ticks_advanced": 0,
  "authority": "LIVING_CONTINUOUS_ISOMETRIC_MOVEMENT_RUNTIME",
  "command": "MOVE_TO_POINT",
  "delegated_core_command": "MOVE_VECTOR",
  "target": { "iso_x_m": 172480.37778480785, "iso_y_m": -1472483.0970637298 },
  "requested_duration_s": 0.25,
  "applied_duration_s": 0.25,
  "distance_before_m": 3.0,
  "remaining_distance_m": 2.648,
  "arrived": false,
  "idempotent_replay": false,
  "replay_suppressed": false,
  "command_ref": "CR-DOC-0001",
  "session_ref": "GODOT-STAGE16B-001"
}
```

`0.352 m = 1.6 m/s (WALK) × 0.25 s × 0.88 (movement_factor)` — número produzido pelo core,
não pelo adapter.

### `POST /command` — replay do mesmo `command_ref`

```json
{
  "status": "PASS",
  "command": "MOVE_TO_POINT",
  "moved_m": 0.352,
  "iso_x_m": 172477.729785,
  "idempotent_replay": true,
  "replay_suppressed": true,
  "command_ref": "CR-DOC-0001"
}
```

O resultado é reemitido a partir do journal. **O mundo não avança uma segunda vez.**

### `POST /command` — `player_ref` forjado

```json
{
  "status": "REJECTED",
  "reason": "CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN",
  "field_path": "$.params.player_ref"
}
```

### `POST /command` — sessão errada

```json
{ "status": "REJECTED", "reason": "UNKNOWN_OR_INACTIVE_SESSION", "session_ref": "WRONG-SESSION" }
```

### `POST /session/resync` — cursor stale

Request: `{"session_ref":"GODOT-STAGE16B-001","last_snapshot_sequence":1,"last_snapshot_id":null}`

```json
{
  "status": "PASS",
  "resync": true,
  "session_ref": "GODOT-STAGE16B-001",
  "cursor": {
    "server_last_sequence": 2,
    "server_last_snapshot_id": "S16B-000000000002-d27b683cfbd984ba",
    "client_last_sequence": 1,
    "client_last_snapshot_id": null,
    "cursor_status": "STALE_OR_DUPLICATE"
  },
  "snapshot": { "status": "PASS", "snapshot_sequence": 3, "snapshot_id": "S16B-000000000003-d27b683cfbd984ba" }
}
```

`cursor_status` ∈ `CURRENT` · `STALE_OR_DUPLICATE` · `UNKNOWN_SNAPSHOT_SEQUENCE` ·
`SNAPSHOT_ID_MISMATCH` · `NO_CLIENT_CURSOR`. O resync sempre devolve um snapshot novo,
para que o cliente consiga se recuperar de qualquer um desses estados.

---

## Catálogo de `reason`

| reason | quando |
|---|---|
| `SESSION_REF_REQUIRED` | `session_ref` ausente/vazio |
| `INVALID_SESSION_REF` | `session_ref` fora do charset permitido |
| `UNKNOWN_OR_INACTIVE_SESSION` | sessão não existe, foi revogada ou o hash não confere (decidido pelo core) |
| `COMMAND_REF_REQUIRED` | envelope sem chave de idempotência |
| `INVALID_COMMAND_REF` | `command_ref` fora do charset permitido |
| `COMMAND_REF_SESSION_MISMATCH` | `command_ref` reusado por outra sessão |
| `COMMAND_REF_PAYLOAD_MISMATCH` | `command_ref` reusado com payload diferente |
| `COMMAND_JOURNAL_HASH_MISMATCH` | resultado gravado foi adulterado |
| `INVALID_COMMAND_NAME` | nome de comando fora do padrão |
| `CLIENT_AUTHORITATIVE_COMMAND_FORBIDDEN` | comando contém token autoritativo |
| `CLIENT_AUTHORITATIVE_FIELD_FORBIDDEN` | campo autoritativo em qualquer nível (`field_path` aponta) |
| `UNEXPECTED_ENVELOPE_FIELD` | chave desconhecida no topo do envelope |
| `COMMAND_NOT_ENABLED_IN_THIS_ROUND` | comando fora da allowlist da rodada |
| `INVALID_COMMAND_PARAMS` | `params` não é objeto |
| `INVALID_JSON_BODY` | corpo não é JSON de objeto |
| `INVALID_TARGET_POINT` | `iso_x_m`/`iso_y_m` ausentes ou não finitos |
| `UNSUPPORTED_MOVE_MODE` | modo fora de `WALK`/`RUN`/`CROUCH` |
| `INVALID_STEP_DURATION` | `duration_s` fora de `(0, 10]` |
| `COLLISION_BLOCKED` | recusado pelo core `CollisionInteractionSystem` |
| `COUNTRY_BOUNDARY_BLOCKED` | recusado pelo core `ContinuousMovementSystem` |
| `INSUFFICIENT_STAMINA` | recusado pelo core (`RUN` com stamina < 5) |
| `SNAPSHOT_PROJECTION_INVALID` | projeção do core violaria o contrato B01 |
| `INVALID_SNAPSHOT_SEQUENCE_TYPE` | cursor apresentado não é inteiro |
| `AUTHORITY_NOT_BOOTED` | o mundo autoritativo não subiu (`status: FAIL`) |
| `INTERNAL_ADAPTER_ERROR` | exceção não prevista (`status: FAIL`, com stack no log do servidor) |

---

## Escopo desta rodada

`ENABLED_COMMANDS = ["MOVE_TO_POINT"]`.

`MOVE_VECTOR`, `INTERACT`, `DISCOVER`, `DUNGEON_MOVE` e `PATH_PLAN` existem no adapter
protegido do core mas estão **desabilitados** aqui (`COMMAND_NOT_ENABLED_IN_THIS_ROUND`).
Cada um entra numa rodada própria, com os testes do seu próprio core. Combate e economia
não foram tocados.

## O que falta no lado Godot (bloqueadores do round-trip)

Duas mudanças no cliente B01, nenhuma feita nesta rodada:

1. `andromeda_bridge.gd :: request_snapshot()` faz `GET /snapshot` sem identificar a
   sessão. Precisa anexar o `session_ref`:

   ```gdscript
   var request_error: Error = _snapshot_request.request(
       "%s%s?session_ref=%s" % [server_url(), snapshot_path(), session.session_ref().uri_encode()]
   )
   ```

   Alternativa equivalente: enviar o header `X-Andromeda-Session`, que o backend também aceita.

2. `andromeda_bridge.gd :: build_command_envelope()` precisa incluir uma chave de
   idempotência por intenção:

   ```gdscript
   # novo contador no AndromedaRuntimeBridge: var _command_index: int = 0
   _command_index += 1
   var envelope := {
       "session_ref": session.session_ref(),
       "command": command,
       "command_ref": "%s-%d-%d" % [session.session_ref(), session.session_epoch(), _command_index],
       "params": params.duplicate(true),
   }
   ```

   O `command_ref` precisa ser gerado **uma vez por intenção** e reutilizado em qualquer
   retry do mesmo envelope — é essa estabilidade que torna o retry seguro.

   Sem ela o servidor não consegue distinguir um retry de transporte de uma repetição
   legítima, e por isso recusa o envelope com `COMMAND_REF_REQUIRED`. Aceitar comandos
   sem chave seria exatamente o defeito `duplicate_applied_twice` encontrado na auditoria.

O cliente também precisa chamar `POST /session/bind` antes do primeiro snapshot
(hoje o `ClientSession` só liga o cursor local).

---

## Procedimento obrigatório para os gates Godot de autoridade

Os gates rodam contra o **mundo persistido** em `var/`. Esse mundo acumula estado real
entre execuções, e três formas de contaminação já invalidaram evidência:

1. **Ground Loot acumulado.** Cada gathering (gate ou probe) cria drops permanentes. Com
   dezenas de drops, a seleção do "último grupo de probe" do gate de pickup passa a
   escolher o drop errado e o gate falha por distância.
2. **Dano acumulado no inimigo.** O encontro de desenvolvimento perde vida a cada gate de
   combate. O boot agora só reaproveita um alvo **com vida cheia** e, caso contrário,
   seleciona outro ator íntegro — nunca cura ninguém, porque curar seria regra inventada.
3. **Ferramenta/Bag ausente após drop de morte.** Concessões com `event_ref` fixo são
   *replayadas* pelo item core e não concedem nada. Todo "ensure" de bootstrap usa
   `event_ref` por tentativa e é verificado contra o estado vivo.

### Sequência correta

```bash
cd "C:/Users/thall/Documents/andromeda-argp/ANDROMEDA_ARPG_GODOT_STAGE16A_V1_7_0_DEV/12_AUTHORITY_BACKEND" && PID=$(netstat -ano | grep ":8000 " | grep LISTENING | head -1 | awk '{print $NF}') && taskkill //F //PID "$PID"
```

Depois, com o servidor parado:

```bash
cd "C:/Users/thall/Documents/andromeda-argp/ANDROMEDA_ARPG_GODOT_STAGE16A_V1_7_0_DEV/12_AUTHORITY_BACKEND" && mv var "var_archive_$(date +%Y%m%d_%H%M%S)" && "C:/Users/thall/ANDROMEDA_PRODUCT/.venv/Scripts/python.exe" seed_stage16b_ground_loot_probe.py
```

Suba o servidor e execute os gates **nesta ordem**. `GroundLoot` precisa vir primeiro:
os drops de probe são ancorados na posição do jogador no momento da semeadura, e qualquer
`MOVE_TO_POINT` posterior invalida a âncora.

```
GroundLoot -> Roundtrip -> Profile -> Traversal -> Gathering -> Combat -> EconomyQuest -> SaveDeath
```

Um gate por processo. Nunca em lote: B11 já registrou runs invalidadas por estouro de
limite de batch. Arquive `var/` em vez de apagar — o mundo anterior continua auditável.
