# CHANGELOG V0.1.23 DEV

## SELECTION DURING MOVEMENT
- Clique esquerdo em alvo selecionável agora APENAS troca a seleção.
- Selecionar não cancela ações de movimento.
- Selecionar não limpa `_path_points`.
- Selecionar não chama `_cancel_all_actions`.
- Selecionar não chama `_stop_hold_movement`.
- Selecionar não zera `velocity.x/z`.
- Se o personagem já estiver caminhando para um ponto, continua indo ao mesmo ponto após selecionar NPC/inimigo/animal/árvore/pedra/objeto.
- Se estiver parado, selecionar um alvo mantém o personagem parado.
- Clicar em chão vazio continua sendo a única forma normal de criar/trocar destino pelo esquerdo.

## PRESERVED
- Esquerdo em transição de cenário continua aproximando e atravessando.
- E: aproxima e interage/inspeciona alvo não hostil selecionado.
- Espaço: ataca inimigo selecionado.
- Direito: contextual direto.
- Ranged V0.1.19, tiers, aggro, inventário, comerciantes e mapa sem alterações.
- Master V2.0.1 e Living Simulation Engine V1.0.0 permanecem READ_ONLY.
