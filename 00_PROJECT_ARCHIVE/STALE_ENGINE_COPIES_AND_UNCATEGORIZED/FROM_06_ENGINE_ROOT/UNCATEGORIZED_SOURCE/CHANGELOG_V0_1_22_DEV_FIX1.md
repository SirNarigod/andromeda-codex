# CHANGELOG V0.1.22 DEV FIX1

## RUNTIME FIX — FREED SELECTED TARGET

### Defeito
Ao selecionar/interagir com um objeto que depois era removido da SceneTree,
`_update_selected_target()` podia tentar chamar
`_selected_target_is_selectable(target: Node3D)` com uma referência
`previously freed`.

O Godot rejeitava o argumento tipado antes que `is_instance_valid()` pudesse
executar, gerando erro em runtime.

### Correção
- `_update_selected_target()` valida `_selected_target` antes de qualquer helper.
- Helpers internos de seleção não exigem mais `Node3D` no parâmetro.
- `_selected_target_is_selectable()` valida null/freed antes de qualquer acesso.
- HUD mantém validação explícita antes de usar o alvo.
- Marcador e seleção são limpos quando o alvo não existe mais.

### Escopo preservado
- E: aproxima/interage com alvo selecionado não hostil.
- Espaço: ataca inimigo selecionado.
- Esquerdo: selecionar/parar ou mover no chão.
- Direito: contextual.
- Ranged V0.1.19, tiers, aggro, inventário e mapa sem mudanças.
