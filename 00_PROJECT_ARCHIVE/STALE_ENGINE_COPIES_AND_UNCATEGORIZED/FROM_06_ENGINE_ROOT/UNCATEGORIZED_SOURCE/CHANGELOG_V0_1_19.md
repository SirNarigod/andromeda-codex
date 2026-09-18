# CHANGELOG V0.1.19 DEV

## FINAL RANGED RETREAT RULE
- Proximidade do inimigo não provoca mais recuo automático.
- O único gatilho de recuo automático é o jogador RECEBER DANO com uma arma RANGED equipada.
- Wildlife passa seu próprio Node3D ao Player no evento de dano para definir a direção correta do recuo.
- O dano apenas arma a reação; o path de recuo é criado no update de física seguinte.
- Recuo continua curto: 0.32 s.
- Estabilização continua curta: 0.18 s.
- Durante RETREATING/SETTLING o personagem não dispara.
- Depois da estabilização, o combate ranged normal é retomado.
- Outro dano posterior pode disparar um novo recuo.

## BEHAVIOR FINAL
- Inimigo aproxima sem acertar: NÃO RECUA.
- Inimigo acerta o jogador: RECUA CURTO -> PARA -> VOLTA A ATIRAR.
- Novo dano: novo recuo curto.

## PRESERVED
- Cooldown global de ataque: 2.0 s.
- FRACO / MÉDIO / FORTE / ALFA.
- Aggro por dano.
- Dano de flecha/virote no impacto.
- Inventário, comerciantes, mapa e controles.
- Master V2.0.1 e Living Simulation Engine V1.0.0 permanecem READ_ONLY.
