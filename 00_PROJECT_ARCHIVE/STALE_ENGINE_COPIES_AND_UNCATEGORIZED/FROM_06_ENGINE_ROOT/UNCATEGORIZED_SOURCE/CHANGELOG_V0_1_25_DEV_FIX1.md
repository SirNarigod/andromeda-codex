# CHANGELOG V0.1.25 DEV FIX1

## PARSER FIX — ENEMY RANGED PROJECTILE

### Defeito observado no Godot 4.7.1
`Wildlife.gd:258` falhava com:

`Cannot infer the type of "end_pos" variable because the value doesn't have a set type.`

### Causa
`_fire_enemy_projectile(target)` recebia um parâmetro sem tipo.
Ao acessar `target.global_position`, o parser não conseguia inferir com segurança
que o resultado era `Vector3`.

### Correção
- `target` passou a ser `Node3D`.
- `start_pos` e `end_pos` passaram a ser explicitamente `Vector3`.
- `travel_time` passou a ser explicitamente `float`.
- `tween` passou a ser explicitamente `Tween`.
- `_resolve_enemy_projectile(projectile, target)` continua tolerante a referências
  que possam ter sido liberadas antes do impacto.

### Escopo
Nenhum comportamento funcional novo foi adicionado.
HUD, lojas, Stamina, setores, ranged, one-shot e Alfa permanecem como na V0.1.25 DEV.
