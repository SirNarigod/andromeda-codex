# CHANGELOG V0.1.11

## Controle
- Hold-to-move no chão com botão esquerdo e direito.
- Soltar o botão ativo interrompe o movimento imediatamente.
- Cursor em movimento atualiza o destino com throttle e limiar espacial.
- Clique direito contextual mantém aproximação/interação/ataque automáticos.
- Entradas/saídas de área permanecem clicáveis como transições de movimento.

## Combate
- Cooldown de ataque de 2,0 s centralizado em `_perform_attack_on()`.
- Repetir clique no mesmo inimigo, trocar alvo ou cancelar ação não zera cooldown.
- Ataque de debug por teclado passa pela mesma trava central.
