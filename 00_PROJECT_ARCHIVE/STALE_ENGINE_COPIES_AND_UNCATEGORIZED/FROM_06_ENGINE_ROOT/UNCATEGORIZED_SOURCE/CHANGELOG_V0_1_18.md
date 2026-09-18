# CHANGELOG V0.1.18 DEV

## RANGED RETREAT REFINEMENT
- Arco, besta e futuras armas RANGED não recuam mais após todo disparo.
- Recuo só é acionado quando o inimigo entra na zona de perigo da arma.
- A zona usa `min_range_m` da arma; quando ausente, aplica fallback proporcional ao alcance.
- Recuo passou a ser limitado por tempo: 0.32 s.
- O caminho de recuo é interrompido quando o timer termina, mesmo que ainda exista rota.
- Estabilização após recuo: 0.18 s.
- Estado AIMING impede novo recuo em loop antes de o personagem tentar o próximo tiro.

## BEHAVIOR
- Inimigo longe: PARAR -> ATIRAR.
- Inimigo perto: RECUAR CURTO -> PARAR -> ATIRAR -> se ainda perto, repetir.
- Nunca dispara durante RETREATING.
- O inimigo continua avançando durante o recuo e pode alcançar/causar dano.

## PRESERVED
- Cooldown global de ataque: 2.0 s.
- Categorias FRACO / MÉDIO / FORTE / ALFA.
- Aggro por dano.
- Dano ranged no impacto do projétil.
- Inventário selecionável e controles aprovados.
- Master V2.0.1 e Living Simulation Engine V1.0.0 continuam READ_ONLY.
