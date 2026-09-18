# ANDRÔMEDA ARPG — CODEX START HERE — STAGE 16B GODOT

## Objetivo
Implementar no Godot o vertical slice já especificado e testado na Stage 16A. Não redesenhar o gameplay. Não duplicar autoridades Python em GDScript.

## Antes de editar qualquer arquivo
1. Detecte a versão instalada do Godot e registre-a.
2. Localize o projeto Godot local e o ANDROMEDA_EDITOR_BRIDGE existente. Não invente endpoints se o bridge já existir.
3. Preserve `06_GODOT_LIVING_V1_5` como referência histórica/read-only.
4. Crie a Stage 16B em `07_GODOT_ARPG_STAGE16B`.
5. Rode o gate histórico Godot e a suíte Stage16A antes da primeira mudança.

## Autoridades
- Master V2.0.1: READ_ONLY.
- Living Simulation V1.0.0: baseline protegida.
- `IntegratedARPGEngineV16A` e cores Stage01–15: resultados de gameplay.
- Godot: input, cenas, física, Navigation, streaming visual, UI e feedback.

O cliente Godot não pode decidir dano, grants de inventário, moeda, conclusão de quest ou mutação canônica.

## Ordem obrigatória de implementação
1. Bridge/session/snapshot e gate headless.
2. Main, Player, câmera e click-to-move.
3. Target selection + right-click contextual + Space + E.
4. Terreno/células/stamina/carga/streaming.
5. NPC + diálogo realtime + HUD.
6. Inimigos + combate/feedback/barras.
7. Universal Ground Loot + Auto Pickup + 0,5 m.
8. Resource nodes → Ground Loot.
9. Vendor/inventory/quest.
10. Save/death/respawn.
11. Playthrough completo + regressão + restore.

## Regras que não podem ser reinterpretadas
- Clique esquerdo em chão move. Clique esquerdo em alvo seleciona sem parar caminho atual. Ground Loot é exceção: clique manda aproximar/coletar.
- Clique direito é clique único: chão move; inimigo hostil persegue/ataca; NPC/recurso/objeto/veículo aproxima e executa ação contextual.
- Space ataca alvo selecionado. E aproxima/interage com alvo não inimigo. I abre/fecha inventário.
- Nenhum pickup acima de 0,5 m. Obstáculo/caminho impossível impede pickup.
- Árvores, rochas, minérios, flora, agricultura, caça, pesca, inimigos e demais fontes físicas passam por Ground Loot antes do inventário.
- Auto Pickup é ON/OFF persistente e não interrompe ação.
- Terreno afeta stamina/carga; não existe mecânica de equilíbrio corporal nesta etapa.
- Diálogo não pausa mundo e não usa botão Próximo. Balão branco arredondado; normal cinza médio; importante laranja claro. Nome NPC só no hover.
- HUD é contextual/minimalista.
- O mundo distante continua Living/Systemic sem cena detalhada Godot.

## Arquivos de autoridade para ler primeiro
- `02_CONTRACTS/ARPG_STAGE16A/ARPG_GODOT_HANDOFF_MANIFEST_V0_6_0.json`
- `02_CONTRACTS/ARPG_STAGE16A/ARPG_STAGE16B_GODOT_ACCEPTANCE_MATRIX_V0_6_0.json`
- `10_ARPG/STAGE16A/ARPG_STAGE16A_PRE_GODOT_CONTRACT_V0_6_0.json`
- `01_RUNTIME/integrated_arpg_engine_v16a.py`
- `01_RUNTIME/arpg_vertical_slice_assembly_core.py`
- `01_RUNTIME/godot_adapter_v15.py` (referência, não autoridade Stage16B final)

## Condição de término
Stage 16 só pode ser fechada quando todos os gates `G16B-01..20` passarem no Godot real, Debugger estiver sem erros, regressões Python continuarem verdes e um restore do checkpoint final reproduzir o resultado.
