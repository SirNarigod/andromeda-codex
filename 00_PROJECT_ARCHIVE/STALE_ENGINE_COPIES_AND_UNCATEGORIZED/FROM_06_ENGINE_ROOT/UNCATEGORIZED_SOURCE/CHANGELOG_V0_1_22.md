# CHANGELOG V0.1.22 DEV

## E — INTERAÇÃO COM ALVO SELECIONADO
- `E` agora opera sobre o alvo atualmente selecionado.
- `E` só inicia ação automática em alvos NÃO hostis.
- NPC/loja/porta/cadeira/livro/baú/alavanca/item/etc:
  - aproxima;
  - entra na distância de interação;
  - executa automaticamente `INTERACT`.
- Animal passivo/árvore/pedra/objeto `hoverable`:
  - aproxima;
  - entra na distância de interação;
  - executa automaticamente `INSPECT`.
- Inimigo selecionado:
  - `E` não ataca;
  - HUD/mensagem orienta Espaço ou botão direito.
- Sem alvo selecionado:
  - `E` apenas informa que é necessário selecionar um alvo.

## ARQUITETURA
- O `E` reutiliza `_begin_target_action`, o mesmo pipeline contextual já usado pelo botão direito.
- Não existe segunda implementação de pathfinding/interação.
- Seleções de objetos consumidos/desativados são limpas quando deixam os grupos selecionáveis.

## CONTROLES PRESERVADOS
- Esquerdo em chão: mover.
- Esquerdo em alvo: selecionar e parar.
- Esquerdo em transição: aproximar e atravessar.
- Espaço: atacar inimigo selecionado.
- Direito: ação contextual direta.
- Cooldown global: 2 s.
- Regra ranged V0.1.19 continua fechada.

## AUTORIDADE
- Master V2.0.1 e Living Simulation Engine V1.0.0 permanecem READ_ONLY.
