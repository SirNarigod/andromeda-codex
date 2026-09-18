# BALANCE_V1 (RUNTIME_ONLY)

Números inventados exclusivamente para o runtime web. Não são cânone,
não voltam aos JSONs de lore, vivem aqui + saves. Ajuste livre por teste.

## Preços (stavias, por tier de item)
| Tier | Preço |
|---|---|
| Comum (ovr ≤ 40) | 0 (grátis, arma padrão de classe) |
| BAIXO | 10 |
| MÉDIO | 25 |
| ALTO | 60 |
| MUITO_ALTO | 150 |
| overall 41–48 | 25 |
| overall 49–56 | 60 |
| overall ≥ 57 | 150 |

Barganha: CD 12 → −20%. Escambo: mesmo tier, 1:1.

## Combate/XP/loot
- XP: vitória = 10 × tier da ameaça; nível = 100 XP cumulativos (teto M1: nv 5).
- Loot base: PASSIVO 5 st / HOSTIL 15 st + yield narrativo da criatura.
- Cura de itens: teto 30% do PV máx por uso.
- Fuga: CD 10 (AGI); falha = rodada perdida.
- IA inimiga: curar aliado < 50% se tiver cura; senão atacar alvo aleatório.

## Corrupção (M1: só pressão/debuff, sem fases além de CORRUPTION)
- Tiles corrompidos (zona SUB-011-006 no grid TER-011; grid TER-012):
  −2 PV/turno de exploração; estado `corrompido` até descansar fora da zona.
- Craft COR-RES: só EST-009, requer componente de criatura corrompida.

## Grid
- Determinístico por seed = id do território (`sha256`). Tamanho M1: 24×24.
- Tiles: transitável / bloqueado (água/montanha por terreno) / POI / corrompido / saída.
- Zona SUB-011-006 no grid TER-011: círculo runtime em (18,18) r=5 (posição na
  síntese é arbitrária; o vínculo canônico SUB-011-006↔TER-011 está preservado).

## Progressão M1
- Recompensa de quest: 30 st + 20 XP. Nível = 1 + XP/100 (teto nv 5).
