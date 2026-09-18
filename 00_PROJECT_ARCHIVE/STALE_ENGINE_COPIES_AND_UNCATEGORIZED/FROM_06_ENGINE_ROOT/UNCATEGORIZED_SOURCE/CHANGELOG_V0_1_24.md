# CHANGELOG V0.1.24 DEV

## PLAYER RESOURCE BARS
- Barra HUD de HP.
- Barra HUD de Stamina.
- Barra HUD de Proteção.
- Base DEV: 100 HP / 100 Stamina / 60 Proteção.
- Proteção não regenera automaticamente nesta etapa.
- Dano recebido com Proteção: aproximadamente 65% absorvido pela Proteção e 35% pelo HP; excesso passa ao HP.

## ENEMY BARS
- Hostis exibem barra 3D de HP acima do corpo.
- Barras acompanham o inimigo e viram para a câmera.
- Fauna passiva mantém a barra oculta até tornar-se hostil.

## ALPHA SHIELD
- Inimigos ALFA possuem HP + Escudo.
- Escudo máximo é ~48% do HP máximo e obrigatoriamente menor que HP.
- Velúrio Alfa atual: aproximadamente 250 HP / 120 Escudo.
- Alfa exibe duas barras: HP e Escudo.

## WEAPON VS SHIELD
- Cada arma possui `shield_damage_factor` e `hp_through_shield_factor`.
- Algumas armas atingem apenas Escudo enquanto ele existe.
- Outras reduzem HP + Escudo no mesmo impacto.
- Quando ambos caem no mesmo golpe, os valores aplicados nunca são iguais.
- Besta é mais eficiente contra Escudo; arco possui maior passagem relativa para HP.

## PRESERVED
- Seleção durante movimento V0.1.23.
- E, Espaço, botão direito e transições.
- Regra final ranged V0.1.19.
- Tiers, aggro, comerciantes, inventário e mapa.
- Master V2.0.1 / Living Simulation Engine V1.0.0 READ_ONLY.
