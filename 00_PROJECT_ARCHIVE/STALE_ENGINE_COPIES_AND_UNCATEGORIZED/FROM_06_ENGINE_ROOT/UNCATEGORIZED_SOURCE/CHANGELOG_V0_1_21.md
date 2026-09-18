# CHANGELOG V0.1.21 DEV

## GENERIC LEFT-CLICK SELECTION
- Esquerdo seleciona inimigo, animal, NPC, comerciante, árvore, pedra/rocha e demais objetos `interactable`, `wildlife` ou `hoverable`.
- Ao selecionar, o personagem para imediatamente.
- Selecionar não cria destino de movimento.
- Selecionar cancela caminho, hold movement e ação em andamento.
- Clicar no chão fora de qualquer alvo selecionável continua sendo movimento.
- A seleção persiste ao voltar a andar pelo chão.
- Clicar em outro alvo troca a seleção.

## SPACE
- Espaço só ataca quando o selecionado for um `wildlife` hostil/`is_enemy()`.
- NPC, animal passivo, árvore, pedra ou objeto não é atacado pelo Espaço nesta etapa.
- O HUD orienta `Direito: interagir` ou `Direito: observar` para alvos não hostis.

## TRANSITIONS
- DUNGEON_ENTER/DUNGEON_EXIT continuam como exceção aprovada: esquerdo aproxima e atravessa.

## PRESERVED
- Direito contextual.
- Cooldown global de 2 s.
- Regra final ranged V0.1.19.
- FRACO/MÉDIO/FORTE/ALFA.
- Aggro, inventário, comerciantes e mapa.
- Master V2.0.1 e Living Simulation Engine V1.0.0 permanecem READ_ONLY.
