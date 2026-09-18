# ANDRÔMEDA ARPG — CODEX START HERE — STAGE 16B GODOT — V0.8.0

## Objetivo
Implementar no Godot o vertical slice especificado e testado na Stage 16A V0.8.0. Não redesenhar o gameplay. Não duplicar autoridades Python em GDScript.

## Antes de editar qualquer arquivo
1. Detecte a versão instalada do Godot e registre-a.
2. Localize o projeto Godot local e o `ANDROMEDA_EDITOR_BRIDGE` existente. Não invente endpoints se o bridge já existir.
3. Preserve `06_GODOT_LIVING_V1_5` como referência histórica/read-only.
4. Crie/continue a Stage 16B em `07_GODOT_ARPG_STAGE16B`.
5. Rode o gate histórico Godot e a suíte Stage16A antes da primeira mudança.

## Autoridades
- Master V2.0.1: READ_ONLY.
- Living Simulation V1.0.0: baseline protegida.
- `IntegratedARPGEngineV16A` e cores Stage01–15: resultados de gameplay.
- Stage16A V0.8: Ground Loot, traversal, UI/loadout, água, Bolsa, TTL e política de morte do vertical slice.
- Stage15 V1.6.0 permanece baseline histórica selada; sua política antiga de morte não é reescrita. Para o vertical slice Stage16, prevalece a política derivada V0.8 de Bolsa/drop/proteções.
- Godot: input, cenas, física, Navigation, volumes de água, streaming visual, UI e feedback.

O cliente Godot não pode decidir dano, grants de inventário, moeda, conclusão de quest, morte autoritativa, conteúdo da Bolsa, TTL autoritativo ou mutação canônica.

## Regras autorais V0.8.0 — obrigatórias
- Rios rasos podem ser atravessados por Player, NPC, animal e automóvel quando a profundidade permitir.
- Correnteza aumenta o custo de stamina dos seres vivos; corrente forte custa mais.
- Água rasa sob ponte continua atravessável; a ponte não torna a água automaticamente bloqueada.
- Água funda usa nado para Player/NPC/animal e consome stamina mais rapidamente. Veículo comum não atravessa água funda.
- Se stamina chegar a zero na água, Player/NPC/animal entra em exaustão aquática; após a pequena janela gameplay-derived definida pelo backend, pode ocorrer derrota/morte. Não criar sistema de equilíbrio corporal/ragdoll nesta etapa.
- Automóveis não têm stamina: água rasa reduz tração/velocidade.
- Sem Bolsa, o inventário-base é reduzido. Com Bolsa, ela é um container real e segura os itens transportados.
- Peso efetivo para terreno/água inclui inventário-base + conteúdo da Bolsa equipada; uma Bolsa cheia nunca pode pesar zero.
- Compra/venda no vertical slice usa o container efetivo (Bolsa quando equipada; inventário-base quando não), mantendo a carteira econômica no ator.
- O personagem continua limitado a exatamente 2 quick-slots de armas; as duas armas dos quick-slots permanecem com ele na morte.
- Armaduras/roupas equipadas também permanecem com o dono na morte.
- Itens de missão e únicos críticos não podem desaparecer definitivamente.
- Com Bolsa equipada, morte derruba a Bolsa como um único container com o conteúdo comum.
- Bolsa caída em terra permanece até ser recuperada.
- Bolsa caída na água flutua por 30 minutos de exposição autoritativa e depois afunda/sai do estado recuperável.
- Item individual de Ground Loot que permanece na água dura 15 minutos e depois afunda/sai do Ground Loot ativo.
- Player pode recuperar Bolsa de NPC; propriedade original continua registrada e pode alimentar reação/contexto. NPC não rouba automaticamente Bolsa de outro NPC.
- Timers e estados de Bolsa/água precisam sobreviver a save/reload.

## Regras V0.7 que continuam válidas
- Stamina é círculo amarelo radial ao lado do Player e desaparece totalmente quando 100% e inativa.
- `1`/`2` ativam quick-slots; roda sem modificador alterna arma; `zoom_modifier`+roda controla zoom; menu consumindo roda faz apenas scroll.
- Toda UI usa branco/off-white, cantos arredondados, tipografia arredondada legível em cinza e laranja claro para destaque importante, sem copiar assets Nintendo/Zelda.
- Ground Loot universal; pickup somente a `<= 0,5 m`; Auto Pickup ON/OFF persistente.
- Diálogo realtime, sem botão Próximo, sem pausar o mundo.
- Terreno afeta stamina/carga; sem mecânica de equilíbrio corporal.

## Ordem obrigatória de implementação
1. Bridge/session/snapshot e gate headless.
2. Main, Player, câmera e click-to-move.
3. Target/right-click/Space/E + loadout de 2 armas + `1/2/wheel`.
4. Terreno + WaterVolume + shallow/deep/current + stamina/carga + streaming.
5. NPC + diálogo realtime + HUD + stamina ring + inventário/Bag.
6. Inimigos + combate/feedback/barras.
7. Universal Ground Loot + Auto Pickup + 0,5 m + water TTL.
8. Resource nodes → Ground Loot.
9. Vendor/inventory/Bag/quest.
10. Save/death/DroppedBag/recovery/respawn + water timers.
11. Playthrough completo + regressão + restore.

## Arquivos de autoridade para ler primeiro
- `02_CONTRACTS/ARPG_STAGE16A/ARPG_GODOT_HANDOFF_MANIFEST_V0_8_0.json`
- `02_CONTRACTS/ARPG_STAGE16A/ARPG_STAGE16B_GODOT_ACCEPTANCE_MATRIX_V0_8_0.json`
- `10_ARPG/STAGE16A/ARPG_STAGE16A_PRE_GODOT_CONTRACT_V0_8_0.json`
- `01_RUNTIME/integrated_arpg_engine_v16a.py`
- `01_RUNTIME/arpg_vertical_slice_assembly_core.py`
- `01_RUNTIME/arpg_water_bag_survival_core.py`
- `01_RUNTIME/arpg_ground_loot_core.py`
- `01_RUNTIME/arpg_minimal_hud_core.py`
- `01_RUNTIME/godot_adapter_v15.py` (referência, não autoridade Stage16B final)

## Condição de término
Stage 16 só pode ser fechada quando todos os gates `G16B-01..28` passarem no Godot real, o Debugger estiver sem erros, regressões Python continuarem verdes e um restore do checkpoint final reproduzir o resultado.
