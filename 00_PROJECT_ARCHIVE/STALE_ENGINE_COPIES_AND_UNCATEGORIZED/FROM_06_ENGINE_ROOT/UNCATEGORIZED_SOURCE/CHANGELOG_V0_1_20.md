# CHANGELOG V0.1.20 DEV

## ENEMY SELECTION
- Botão esquerdo em inimigo agora seleciona o alvo.
- A seleção não substitui o movimento: após selecionar, o comando de movimento do esquerdo continua.
- Seleção persiste ao clicar no chão, mover ou cancelar uma ação.
- Seleção troca quando outro inimigo é clicado com o esquerdo.
- Seleção é removida automaticamente quando o alvo morre, deixa a SceneTree ou deixa de ser inimigo.
- Indicador visual amarelo sutil acompanha o alvo selecionado.
- HUD mostra o nome do alvo persistente.

## SPACE ATTACK
- Espaço inicia ataque contra o inimigo selecionado.
- Espaço usa o mesmo pipeline de combate do clique direito:
  - MELEE persegue até alcance curto;
  - MID_MELEE persegue até alcance intermediário;
  - RANGED persegue até alcance de disparo;
  - cooldown global de 2 s é respeitado;
  - projéteis, dano no impacto e reação ranged final são preservados.
- Espaço sem alvo selecionado apenas informa que não existe alvo.

## CONTROL CONTRACT
- Esquerdo chão: mover.
- Esquerdo inimigo: selecionar + mover; nunca atacar automaticamente.
- Esquerdo transição: entrar/sair de cenário.
- Direito inimigo: ataque direto/contextual já existente.
- Espaço: atacar selecionado.

## PRESERVED
- Regra final de armas à distância da V0.1.19 permanece fechada.
- Tiers FRACO/MÉDIO/FORTE/ALFA.
- Aggro, inventário, comerciantes, mundo e transições.
- Master V2.0.1 e Living Simulation Engine V1.0.0 permanecem READ_ONLY.
