# Andrômeda Códex ARPG — Stage16B B06

## Escopo fechado

B06 implementa somente apresentação de combate no Godot: vitais mínimos do
Player, barras screen-space de inimigo comum/Alfa, feedback semântico, freeze
visual local, impulso de câmera limitado e Reduced Motion. Dano, hit/miss,
crítico, morte, cooldown, XP, loot, resistência, armor e consumo de proteção
continuam fora do GDScript.

## Arquitetura

- `PlayerCombatVitals`: recebe HP/Proteção como frações absolutas; fica em
  alpha `0,22` ocioso e `0,92` quando relevante. A stamina radial B05 permanece
  separada e inalterada.
- `EnemyCombatBar`: `Control` 2D vinculado imutavelmente por `target_ref` ao
  `HealthBarAnchor`. Não herda rotação 3D. Inimigo comum apresenta somente HP;
  Alfa apresenta HP e uma faixa de proteção menor.
- `CombatFeedbackPresenter`: aceita somente tokens conhecidos e exige
  `confirmed_externally=true` para resultados de combate. Campos de mutação
  (`damage`, deltas, rolls, cooldown, XP ou loot) são rejeitados.
- Hit-stop é apenas `VisualRoot.process_mode = DISABLED` por `28/42/58 ms`;
  CharacterBody, física, outros atores, timers e SceneTree continuam ativos.
- O impulso de câmera é transitório, determinístico e limitado a `0,18 m`.
  Não altera follow, zoom, free orbit ou seleção já resolvida.
- Reduced Motion restaura imediatamente freezes locais e zera todo impulso,
  mantendo texto/cor/tokens visíveis.

## Tokens semânticos

`COMBAT_HIT`, `COMBAT_CRITICAL_HIT`, `PLAYER_HURT`,
`PLAYER_SHIELD_HIT`, `TARGET_DEFEATED` e `INTERACTION_BLOCKED`.

São tokens de apresentação; nenhum asset final de áudio foi incluído.

## Resultados finais

- B06 headless: `265/265 PASS`, exit `0`, stderr vazio.
- B06 Editor Bridge: `265/265 PASS`, debugger `0 erros / 0 warnings`.
- `Main.tscn` Editor Bridge: startup/execução/stop limpos, `0/0`.
- Regressões: B01 `54/54`, B02 `90/90`, B03 `357/357`, B04
  `156/156`, B05 `210/210`.
- Stage16A: `209/209 PASS` em `254,359 s`; stress `20/20 PASS`.
- Baseline: `724/724`, zero missing/mismatch; Living V1.5 `4/4`.
- Backend `127.0.0.1:8000`: `NOT_AVAILABLE` (`0` listeners).

G16B-13 e G16B-15 passam. G16B-14, G16B-20 e G16B-23 recebem somente
evidência parcial. O round-trip autoritativo vivo de combate não foi simulado.

B07 não foi iniciada e nenhum backup final da Stage 16 foi criado.
