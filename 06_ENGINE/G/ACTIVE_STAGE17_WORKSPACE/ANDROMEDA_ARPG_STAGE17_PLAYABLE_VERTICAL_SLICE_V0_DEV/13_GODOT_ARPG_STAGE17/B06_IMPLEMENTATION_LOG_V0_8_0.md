# B06 Implementation Log V0.8.0

## Autoridade preservada

- Godot projeta valores absolutos e eventos já confirmados; nenhum resultado de
  gameplay é calculado no cliente.
- Master V2.0.1, Stage16A, matriz-fonte e `06_GODOT_LIVING_V1_5` permaneceram
  byte-idênticos ao checkpoint.
- Nenhum servidor substituto foi criado; `127.0.0.1:8000` permaneceu sem
  listener.
- Nenhuma arte ou mídia final foi adicionada.

## Implementação

O HUD B05 recebeu um painel de vitais pequeno, um layer de barras por
`target_ref` e um presenter de feedback. A cena principal ganhou um inimigo
Alfa placeholder, reutilizando integralmente a cena `Enemy.tscn`, seu
`VisualRoot`, `Hurtbox` e `HealthBarAnchor`.

As barras são Controls 2D projetados pela câmera, sempre retos e sem herdar a
rotação do ator. O bind é imutável; sobrepor dois inimigos não troca barras nem
o destino do feedback. Fundos e fills são explicitamente cinza/off-white,
vermelho suave e laranja claro, evitando o bug histórico da barra preta.

O presenter rejeita evento de combate não confirmado e qualquer payload que
tente fornecer deltas/rolls para mutação. Freeze atinge apenas `VisualRoot`.
O impulso usa offset temporário da Camera3D, não move o rig/follow e não
reexecuta o pointer resolution. A fila preserva a prioridade Stage16A e mantém
no máximo três feedbacks.

## Correções e rodadas invalidadas

1. A regressão B05 inicial ficou `209/210` porque o harness exigia literalmente
   o label B05. O assertion foi limitado a B05/B06, sem alterar qualquer regra
   funcional; a matriz inteira foi reiniciada e B05 voltou a `210/210`.
2. O primeiro Bridge funcional encontrou sete warnings (seis shadowings e um
   enum cast) e um check dependente da ordem de callbacks, apesar do headless
   inicial ter passado. A rodada foi invalidada; parâmetros foram renomeados, o
   cast `ProcessMode` foi explicitado e a continuidade física passou a usar
   `Engine.get_physics_frames()`. Novo Bridge: `265/265`, debugger `0/0`.
3. Uma consulta Bridge foi feita cedo demais com argumento `res://`; não havia
   processo ativo e nada foi contado. A cena foi executada pelo argumento
   relativo aceito pelo bridge e consultada após startup.
4. A primeira tentativa Stage16A caiu no fallback Linux `/mnt/data` e encerrou
   após 147 testes com sete setup errors. Foi invalidada; o caminho local
   READ_ONLY do Master foi passado por `ANDROMEDA_MASTER_RELEASE` e todos os 209
   testes foram reiniciados.
5. Um stress retornou `20/20`, mas o handle inicial não reteve o exit code. Ele
   não foi contado; o stress foi reiniciado e fechou `20/20`, exit `0`, stderr
   vazio.

## Evidência final

- B06 headless: `265/265`, exit `0`, stderr vazio.
- B06 Editor Bridge: `265/265`, `errors: []`, stop com `finalErrors: []`.
- Main Editor Bridge: `errors: []`, stop com `finalErrors: []`.
- B01: `54/54`; B02: `90/90`; B03: `357/357`; B04: `156/156`;
  B05: `210/210`; todos headless, exit `0`, stderr vazio.
- Stage16A: `209/209`, `254,359 s`, exit `0`.
- Stress: `20/20`, exit `0`, stderr vazio.
- Integridade: `724/724`, zero missing/mismatch; Living `4/4`.
- Checkpoint SHA-256:
  `21626A3152CB37E167EEE24BFF9D3142C5D389A8CA2827594B34211591525A6A`.
- Master SHA-256:
  `6D9AC3CCE7DCF6A65FDCF73859C332A0211C1AF52D149077BEEF554BF7BBD0B2`.

## Acceptance Matrix

- PASS preservado: G16B-01, 02, 07, 10, 11, 12.
- Novo PASS B06: G16B-13 e G16B-15.
- PARTIAL_EVIDENCE: G16B-03, 04, 06, 08, 09, 14, 20, 21, 22, 23,
  24, 25, 26 e 27.
- NOT_EXECUTED: G16B-05, 16, 17, 18, 19 e 28.

B06 está fechada no escopo aplicável. B07 não foi iniciada. Nenhum backup final
foi criado.
