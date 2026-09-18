# Andrômeda Códex ARPG — Stage 16B — B04

## Terrain / Traversal / Water / Streaming Foundation

Esta pasta continua sendo a única área mutável da Stage 16B. O Master V2.0.1,
a Stage16A V0.8.0 e `06_GODOT_LIVING_V1_5` permanecem read-only.

## Limite de autoridade

O Godot desta B04:

- apresenta terreno, colisão filtrada, navigation, água, corrente e streaming visual;
- detecta `surface_kind`, slope, flags e capacidade de travessia;
- produz somente inputs/candidatos para o snapshot autoritativo;
- não debita stamina, não resolve carga, morte aquática, inventário ou TTL;
- não cria backend substituto e não cria um Living paralelo.

`127.0.0.1:8000` não estava disponível na validação final. As dependências de
snapshot correspondentes permanecem `NOT_AVAILABLE`/`PARTIAL_EVIDENCE`.

## Composição

`TerrainFoundation.tscn` separa explicitamente:

- `VISUAL_SURFACE`: malha procedural com microrelevo inferior a 0,12 m,
  placeholders de estrada/campo/rocha/lama, slopes, step e ponte;
- `COLLISION_SURFACE`: caixas/rampas simplificadas e estáveis, sem reproduzir
  o microdetalhe visual;
- `TRAVERSAL_SURFACE`: zonas de superfície e regiões Navigation por capacidade;
- `WATER_FOUNDATION`: volumes rasos/fundos, corrente, passagem sob ponte e flags;
- `CELL_STREAMING`: uma célula `ACTIVE`, ring `PRELOAD` e referências distantes
  `SYSTEMIC` sem cena Godot.

Navigation layers locais:

- `1`: terra e água rasa;
- `2`: água funda/natação;
- `4`: ponte.

Os candidatos Stage16A permanecem ajustáveis: slope máximo 32°, step 0,35 m e
filtro de microrelevo 0,12 m. O step demonstrado tem 0,30 m e usa transição de
colisão filtrada para não prender o Player.

## Água e itens físicos

`WaterVolume.tscn` expõe profundidade, classe rasa/funda, corrente/direção,
`swimmable`, veículo permitido/bloqueado e `under_bridge`. Corrente visual é
horizontal e limitada a 0,08 m por tick de apresentação.

`GroundLoot.tscn` e `DroppedBag.tscn` usam `WaterWorldItemPresenter`:

- Ground Loot cai fisicamente, assenta e pode entrar na água;
- Bolsa em água fica em estado visual `FLOATING`;
- loot individual em água expõe o contrato de 900 s;
- Bolsa em água expõe o contrato de 1800 s;
- Bolsa em terra expõe ausência de expiração;
- nenhum desses tempos avança em GDScript.

## Execução do gate

```powershell
& 'C:\Program Files\Godot\Godot.exe' --headless --path . `
  --scene res://tests/godot/B04RuntimeGate.tscn -- --gate-success-linger=0
```

Resultado final: `156/156 PASS` headless e `156/156 PASS` pelo Editor Bridge,
com debugger final em `0 erros / 0 warnings`.

Regressões finais: B01 `54/54`, B02 `90/90`, B03 `357/357`, Stage16A
`209/209`, stress `20/20`, baseline `724/724`.

## Acceptance

`G16B-07` recebeu PASS real Godot. `G16B-04`, `G16B-08`, `G16B-09`,
`G16B-14`, `G16B-20`, `G16B-24`, `G16B-25` e `G16B-27` permanecem
`PARTIAL_EVIDENCE` pelos limites autoritativos ou por implementação visual final
ainda não pertencente à B04. Nenhum outro gate foi promovido.

Não há arte final e nenhum backup final da Stage 16 foi criado.
