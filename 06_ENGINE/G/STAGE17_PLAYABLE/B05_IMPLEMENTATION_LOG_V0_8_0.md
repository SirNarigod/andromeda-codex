# B05 — Implementation / Test Log — V0.8.0

## Limites preservados

- Escritas somente em `07_GODOT_ARPG_STAGE16B`.
- Master V2.0.1, Stage16A e `06_GODOT_LIVING_V1_5` permaneceram read-only.
- Nenhum backend substituto foi criado; `127.0.0.1:8000` terminou sem listener.
- Nenhum comando B05 foi submetido pelo cliente.
- Dano, inventário, loot, quest, morte, stamina, `MAIN_HAND`, preferências e
  narrativa permanecem autoritativos fora do GDScript.
- Nenhum backup final da Stage 16 foi criado.

## Arquitetura implementada

### Tema e HUD

`AndromedaMinimalTheme.tres` centraliza fundo off-white, raio de 14 px,
tipografia de sistema com candidatos arredondados, texto `#6B6B6B`/`#8A8A8A`,
laranja importante `#D9A15F` e sombra sutil. `HUD.tscn` mantém mouse filter em
IGNORE fora do menu e coordena apenas projeções.

### Stamina

`StaminaWorldRing.tscn` desenha um arco circular amarelo em screen-space e usa
`Camera3D.unproject_position` sobre o Player. Os estados aceitos são
`CONSUMING`, `REGENERATING` e `INACTIVE`. Fração e atividade são recebidas; não
são calculadas como autoridade local.

### Quick-slots

`WeaponQuickSlots.tscn` contém somente `Slot1` e `Slot2`. Um único slot recebe o
destaque ativo; após 1,2 s o conjunto volta a alpha discreto. Teclas/roda criam
intenções B01 compatíveis e nunca chamam `submit_command`.

### Diálogo

`DialogueBubble.tscn` oferece balão branco arredondado, texto cinza/laranja,
autoavanço por tempo, choices pequenas e ausência estrutural de botão Próximo.
O HUD gerencia um pool máximo de três balões e um balão por conversa, com
turn-index crescente. Fala importante permanece no balão e na linha inferior.

### Inventário

`Inventory.tscn` é um shell aberto por `I`: oito slots-base placeholder,
`BAG_SLOT`, `BagContainer`, equipamento, referências 1/2, tooltip e Auto Pickup.
O menu consome roda apenas como scroll e bloqueia zoom/troca de arma.

## Ciclos e correções

1. O primeiro gate headless encontrou `209/210`: o NPC B03 estava fora da faixa
   visual do spawn e o balão, corretamente limitado à tela, invalidava a
   asserção de proximidade. A fixture passou a reposicionar temporariamente os
   NPCs somente durante o teste e restaurá-los depois. Novo run: `210/210`.
2. O primeiro Editor Bridge executou `210/210`, mas expôs quatro warnings de
   tipagem. O run foi invalidado. Foram removidos dois `await` desnecessários e
   adicionados casts `Key`/`MouseButton`. Headless e Bridge foram reiniciados:
   `210/210`, debugger `0/0`.
3. A primeira regressão B04 ficou em `155/156`: o novo peer B05 havia sido
   colocado exatamente no spawn `(11,0,8)` do teste de pequeno degrau e criava
   bloqueio físico. O placeholder foi movido para `(12,0,-14)`, fora das rotas
   aprovadas. B04 e B05 foram reiniciadas e passaram `156/156` e `210/210`.
4. Uma invocação inicial pelo PowerShell tratou `Godot.exe` como aplicativo GUI
   e devolveu controle antes do processo. O processo de teste exato foi parado,
   sem tocar no editor do usuário, e todos os runs finais usaram
   `Start-Process -Wait` com códigos de saída e stderr separados.

## Resultados finais

- B05 headless: `210/210 PASS`, exit `0`, stderr vazio.
- B05 Editor Bridge: `210/210 PASS`, debugger `0 erros / 0 warnings`.
- `Main.tscn` Editor Bridge: PASS, debugger `0/0`.
- B01: `54/54 PASS`.
- B02: `90/90 PASS`.
- B03: `357/357 PASS`.
- B04: `156/156 PASS`.
- Stage16A: `209/209 PASS` em `275,151 s`, exit `0`.
- Stage16A stress: `20/20 PASS`, exit `0`.
- Baseline: `724/724`, zero missing/mismatch.
- `06_GODOT_LIVING_V1_5`: `4/4`, zero divergências.
- Checkpoint SHA-256:
  `21626A3152CB37E167EEE24BFF9D3142C5D389A8CA2827594B34211591525A6A`.
- Master V2.0.1 SHA-256:
  `6D9AC3CCE7DCF6A65FDCF73859C332A0211C1AF52D149077BEEF554BF7BBD0B2`.

## Acceptance

`G16B-10`, `G16B-11` e `G16B-12` receberam PASS pela execução visual/interativa
completa de seus critérios. `G16B-06`, `08`, `13`, `14`, `20`, `21`, `22`,
`23` e `26` receberam somente `PARTIAL_EVIDENCE` pelos limites documentados no
registro B05. O contrato fonte da Acceptance Matrix não foi alterado.

B05 está fechada no escopo aplicável. B06 não foi iniciada.

