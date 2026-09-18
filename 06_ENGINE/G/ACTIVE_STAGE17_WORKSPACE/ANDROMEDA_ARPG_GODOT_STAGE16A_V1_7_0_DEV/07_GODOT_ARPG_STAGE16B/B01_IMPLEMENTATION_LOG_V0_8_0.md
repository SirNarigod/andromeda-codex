# Stage 16B — B01 — Registro de implementação V0.8.0

Data: 2026-08-20 (America/Sao_Paulo)

## Resultado

A B01 de bridge/sessão/snapshot e runtime gate foi implementada exclusivamente em
`07_GODOT_ARPG_STAGE16B`. O gate G16B-01 passou no Godot real 4.7.1, em headless e pela
bridge local do editor, com 54/54 checks e debugger final sem erros ou warnings.

O endpoint runtime já existente `http://127.0.0.1:8000` continua sem listener. Essa
indisponibilidade está registrada como `NOT_AVAILABLE`, não como PASS. Nenhum endpoint
substituto foi criado.

## Autoridades preservadas

- Master V2.0.1: read-only, nenhuma mutação.
- Stage16A V0.8.0: 724/724 arquivos idênticos ao ZIP antes e depois da B01.
- `06_GODOT_LIVING_V1_5`: não editado; gate executado em cópia temporária isolada.
- Stage16B: somente transporte, sessão, validação/projeção de snapshot e estado de
  reconexão. Nenhuma regra autoritativa de gameplay foi implementada em GDScript.

## Arquivos criados

- `project.godot`: projeto Godot 4.7 isolado, autoloads `ClientSession` e
  `AndromedaBridge`, URL/path legados preservados.
- `scripts/runtime/client_session.gd`: bind/revoke local, epoch de sessão e cursor de
  snapshots sequenciados/compatibilidade V1.5.
- `scripts/runtime/andromeda_bridge.gd`: envelopes, HTTP transport existente,
  validação de snapshot, fila de comandos e reconnect/resync.
- `tests/godot/B01RuntimeGate.tscn` e `tests/godot/b01_runtime_gate.gd`: 54 checks.
- `README_STAGE16B_B01.md`: escopo e non-goals.
- logs e registros B01 desta pasta.

O Godot também gerou os arquivos `.gd.uid` e o cache local `.godot`; o cache está
ignorado e não é parte da implementação autoritativa.

## Proteções da bridge

- comandos exigem sessão ativa e mantêm o envelope legado
  `session_ref/command/params`;
- `player_ref` nunca é enviado pelo cliente;
- comandos/campos de dano resolvido, grant de inventário, resultado de moeda,
  conclusão de quest, mutação canônica, resultado de morte, conteúdo de Bolsa e TTL
  autoritativo são bloqueados;
- somente snapshots com `server_authoritative: true` são aplicados;
- snapshot malformado, de outra sessão, duplicado ou stale é rejeitado;
- snapshots V1.5 sem sequência usam modo explícito `LEGACY_RECEIVE_ORDER`;
- reconnect só volta a READY após novo snapshot autoritativo.

## Ciclos de teste e correções

1. A primeira tentativa sandboxed do gate V1.5 encontrou erro no certificate store.
   Foi invalidada e repetida com acesso normal ao Windows: PASS limpo.
2. O alias Python da Microsoft Store não era executável. Foi substituído pelo Python
   bundled 3.12.13; a sequência completa foi reiniciada.
3. O primeiro verificador SHA usou uma API inexistente no PowerShell local e só leu um
   arquivo. O resultado foi descartado; o verificador compatível cobriu 724/724.
4. O gate B01 passou headless, mas inicialmente encerrou antes do attach tardio da
   bridge do editor. Foi adicionado linger configurável e stop controlado.
5. O primeiro debugger anexado detectou duas warnings de shadowing do parâmetro
   `name`. Os parâmetros foram renomeados para `check_id` e os testes reiniciados.
6. Um diagnóstico `--editor` disputou o socket do editor do usuário e revelou que o
   executável GUI não fornece `$LASTEXITCODE`. A instância do usuário foi preservada;
   os gates passaram a usar runtime headless com `Start-Process -Wait -PassThru`.

## Evidências finais

- Gate histórico V1.5: PASS, 0 erros, 0 warnings.
- Stage16A antes da B01: 209/209; stress 20/20.
- B01 headless: 54/54; exit code 0; log limpo.
- B01 via editor bridge: 54/54; `errors: []`; stop controlado.
- Stage16A depois da B01: 209/209 em 249.208 s; stress 20/20.
- Integridade depois da B01: 724/724, 0 divergências.

## Acceptance Matrix

- G16B-01: PASS.
- G16B-02..19 e G16B-21..28: NOT_RUN; continuam registrados e não foram pulados.
- G16B-20: evidência parcial de regressão B01; o gate final continua pendente de B11.
- Stage16 completa: não.
- Backup final autorizado: não.

O próximo bloco contratual é B02: Main, Player, câmera e click-to-move/navigation.

