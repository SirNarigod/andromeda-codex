# CHANGELOG V0.1.13 DEV FIX1

## Runtime correction

- Corrige `MoveTargetMarker` criado durante `_ready()` enquanto o nó pai ainda monta seus filhos.
- A anexação do marcador ao nó pai agora é diferida com `add_child.call_deferred(...)`.
- `global_position` só é acessado depois que o marcador está dentro da `SceneTree`.
- Uma solicitação visual que ocorra antes de `tree_entered` é preservada e aplicada quando o marcador estiver pronto.
- Atualização do marcador durante perseguição também exige `is_inside_tree()`.

## Escopo preservado

- Sem alteração nos contratos de mouse esquerdo/direito.
- Cooldown global de ataque permanece em 2.0 s.
- Inventário continua oculto por padrão e alternado por `I`.
- Navegação A*, colisões, interação, fauna, masmorra e tocha não foram alteradas.
