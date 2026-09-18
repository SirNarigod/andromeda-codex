# Stage17 Etapa 31 — S17-00 + S17-A

Status: `S17_00_A_PASS`  
Stage17 implementation: `STARTED`  
Playable startup: `READY`

## Resultado

Foi criado um workspace Stage17 fisicamente separado e derivado apenas dos artefatos validados: dependência protegida Stage16A V0.8.1 e backup Stage16B byte-validado. A baseline Stage16B original permaneceu read-only e seus checkpoint/backup conservaram o SHA-256 `77276aa0bcff0475193d2b85a89fdee7d27564b8b5c83af09f8725b414cd67cc`.

O backend Stage17 usa estado próprio em `STAGE17_RUNTIME_STATE`, owner scope `stage17:playable-v0-dev`, seed `160800`, SQLite e saves separados. Nenhum `var/`, world ou save histórico foi copiado.

## Estrutura

- `13_GODOT_ARPG_STAGE17`: fork Godot mutável da Stage17.
- `12_AUTHORITY_BACKEND_STAGE17`: fork do backend; nenhum arquivo funcional foi alterado nesta rodada.
- `STAGE17_RUNTIME_STATE`: SQLite, saves, logs, estado de processo e AppData Godot isolados.
- `STAGE17_TOOLS`: launcher, shutdown, status, runner e auditorias.
- `STAGE17_RECORDS`: evidências exclusivas da Stage17.
- `STAGE16B_BASELINE_PROVENANCE.json`: proveniência do fork.
- `STAGE17_INITIAL_SOURCE_MANIFEST_V0_1_0_DEV.json`: manifesto determinístico inicial.

Manifesto inicial: 1028 arquivos, 12.711.405 bytes, hash `7a03dc2cbf46b86a68de7beeb2a664cd0bf0e219a0adc45fb11a77d4b7f48059`.

## Launcher externo

O launcher PowerShell:

1. valida workspace, backend, Master e interpreter;
2. rejeita porta 8000 ocupada;
3. inicia Uvicorn em `127.0.0.1:8000`, exatamente um worker;
4. injeta somente paths de runtime Stage17;
5. aguarda `GET /health` com `status=PASS`;
6. registra launcher PID, listener PID, identidade e startup;
7. encerra somente o processo cuja identidade, path, start time e relação de parent tenham sido provados.

Interpreter solicitado: `C:\Users\thall\ANDROMEDA_PRODUCT\.venv\Scripts\python.exe` — Python 3.14.6, FastAPI 0.141.1, Uvicorn 0.52.3. O worker real resolve para o Python-base da venv, e essa indirection é registrada e validada. Startup final observado: 8.818,772 ms. Shutdown: PASS, listener 8000 ausente.

## Godot connection presenter

Foi adicionada uma apresentação mínima `CONNECTING / READY / FAILED`. Ela apenas observa a B01; não possui uma segunda máquina de reconnect e não inicia Python.

`READY` requer simultaneamente:

- bridge em `STATE_READY`;
- sessão autoritativa ligada;
- snapshot `server_authoritative=true`, com session_ref compatível, snapshot_id e sequence válidos.

Os guards já existentes nos clientes B01 impedem envio autoritativo normal antes de `authority_session_bound=true`; nenhum bloqueio de gameplay novo foi criado.

## Arquivos Godot criados

- `scenes/ui/AuthorityConnectionStatus.tscn`
- `scripts/ui/authority_connection_status.gd`
- `tests/godot/S17AStartupRuntimeGate.tscn`
- `tests/godot/s17a_startup_runtime_gate.gd`
- UIDs/cache Godot gerados pela importação 4.7.1 dentro do fork.

## Arquivos Godot modificados

- `project.godot`: identidade Stage17, sessão Stage17 e Main restaurado como cena principal.
- `scenes/Main.tscn`: instancia apenas o presenter de conexão.
- `scripts/main.gd`: ajuste nominal de comentário Stage17; nenhuma lógica gameplay.
- `.godot/global_script_class_cache.cfg`: registro da nova classe de apresentação.

Nenhum arquivo do backend funcional foi modificado. Nenhum arquivo Stage16B original foi modificado.

## Testes válidos finais

- S17-00 baseline fork: 22/22 PASS.
- S17-A backend indisponível: 9/9 PASS; `CONNECTING → FAILED`; nenhum READY fabricado.
- S17-A authority live: 17/17 PASS; bind e snapshot reais; `CONNECTING → READY`.
- Main via Editor Bridge: PASS; Godot 4.7.1; OpenGL Compatibility; NVIDIA GTX 1650; debugger 0 erros / 0 warnings; controlled stop `finalErrors: []`.
- B01: 54/54 PASS.
- G19: 71/71 PASS com backend Stage17 real.

## Anomalias e correções

1. O runner herdado apontava hardcoded para Stage16B. A execução foi invalidada; foi criado runner Stage17 próprio.
2. Invocações Godot diretas sem marcador completo foram invalidadas e não usadas como evidência.
3. O primeiro caminho offline permaneceu em CONNECTING durante a janela curta. O gate passou a exercitar o erro de transporte da própria bridge, sem backend/mock, e validou FAILED.
4. A venv Windows cria um launcher e um worker Python-base com PIDs distintos. O launcher foi corrigido para registrar/provar ambos.
5. Duas tentativas iniciais de shutdown recusaram com segurança por parse de DateTime e campo ausente. Ambas foram corrigidas antes do run final.
6. Quatro processos Godot headless de tentativas invalidadas foram identificados por PID, `--headless` e path Stage17, e encerrados de modo controlado.
7. Tentativas anteriores e o Editor Bridge escreveram cache/log no AppData padrão. Os artefatos foram preservados e movidos para `STAGE17_RUNTIME_STATE/invalidated_external_user_data`; o AppData Stage17 externo terminou ausente.

Nenhum erro foi ignorado. Apenas os runs finais completos e com exit code 0 foram aceitos.

## Limites mantidos

- O launcher externo continua obrigatório em S17-A.
- Movimento autoritativo, mapping de coordenadas e reconciliation permanecem deliberadamente fora de escopo.
- O estado atual é runtime de desenvolvimento isolado, não save de release.
- Nenhum backup ou ZIP Stage17 foi criado.

## Próximo processo

`S17-B1/B2 MOVEMENT AUTHORITY`: ligar o click-to-move normal ao `MOVE_TO_POINT`, definir mapping Godot/backend e reconciliation, em microetapas pequenas, preservando B01 e G19.
