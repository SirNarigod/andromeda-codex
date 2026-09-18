# CHANGELOG V0.1.9

## Correção — interação/Depurador

- Separado o pedido de interação da execução da interação.
- `_physics_process` apenas agenda a ação; `_dispatch_pending_interaction()` executa com `call_deferred`.
- Estado de ação é limpo antes da mutação do alvo para evitar reentrância em cadeira/teleporte/coleta.
- `object_id` é capturado antes da ação para não acessar alvo potencialmente alterado.
- Adicionado debounce de 0,18 s para evitar duplicidade por clique.
- Adicionados `is_instance_valid`, `is_inside_tree` e `has_method` nos pontos críticos.
- `Interactable.gd` passou a validar colisão/mesh/player antes de chamadas mutáveis.

Nenhuma regra de controle foi alterada.
