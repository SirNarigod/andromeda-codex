# CHANGELOG V0.1.25 DEV FIX2

## HUD WARNING CLEANUP

### Warnings removidos
- `torch_state` declarado e não utilizado.
- `action_state` declarado e não utilizado.

### Causa
A V0.1.25 compactou o HUD e deixou duas variáveis antigas em `_update_hud()`.

### Correção
- Removida a declaração de `torch_state`.
- Removido o bloco inteiro de `action_state`.
- HUD compacto continua mostrando zona, moedas, arma e alvo.
- Nenhuma regra de gameplay foi alterada.

### Preservado
- barras 2D de inimigos;
- stamina por ataque;
- lojas;
- setores de teste;
- inimigos ranged/one-shot;
- Alfa;
- seleção, E, Espaço e botão direito.
