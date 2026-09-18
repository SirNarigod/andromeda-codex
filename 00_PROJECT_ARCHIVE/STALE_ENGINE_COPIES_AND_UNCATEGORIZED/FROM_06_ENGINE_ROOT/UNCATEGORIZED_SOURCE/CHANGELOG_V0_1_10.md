# CHANGELOG V0.1.10

## Correção crítica — interação/pathfinding

**Sintoma no Godot 4.7.1:**
`Trying to assign an array of type "Array" to a variable of type "Array[float]"` em `Main.gd:286`.

**Causa:**
Uma expressão condicional (`A if condição else B`) com literais de array produzia um `Array` genérico. O resultado era atribuído a `Array[float]`, gerando erro somente quando o fluxo de interação/pathfinding entrava no ramo de aproximação com `stop_distance > 0.05`.

**Correção:**
`ring_scales` passa a ser criado como `Array[float] = []` e preenchido exclusivamente por `append()` com valores `float`.

**Escopo:**
Nenhuma regra de controle, combate, porta, cadeira, hover, rio/ponte ou transição de masmorra foi alterada.
