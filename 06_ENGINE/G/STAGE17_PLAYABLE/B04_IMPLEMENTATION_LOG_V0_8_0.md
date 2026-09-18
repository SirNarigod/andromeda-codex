# B04 — Registro de implementação e validação — V0.8.0

Data: 2026-08-20 (America/Sao_Paulo)

## Resultado

B04 fechada para o escopo local/visual/físico aplicável: `156/156 PASS` em
Godot headless e `156/156 PASS` pelo Andrômeda Editor Bridge. Debugger final e
execução direta de `Main.tscn`: zero erros e zero warnings.

Não houve promoção indevida de stamina, carga, morte aquática, TTL ou Living
SYSTEMIC sem snapshot autoritativo.

## Arquitetura implementada

### Terreno

- `VISUAL_SURFACE`: ArrayMesh determinística com ondulação sutil e pedras apenas
  visuais; estrada, campo, rocha e lama usam materiais placeholder.
- `COLLISION_SURFACE`: superfície macro plana/estável, rampas físicas simplificadas,
  step de 0,30 m com transição filtrada e ponte com clearance.
- `TRAVERSAL_SURFACE`: zones com `surface_kind`, slope, custo candidato e flags
  road/trail/field/rock/mud/water; nenhum débito de stamina local.
- Slopes testados: suave (~9,46°), moderado (~18,43°) e bloqueado (~53,13°).
- Candidatos preservados: 32°, 0,35 m e 0,12 m.

### Navigation

- A célula base de oito polígonos da B02 foi preservada como região de
  compatibilidade e integrada a novas regiões de terreno.
- Layers por capacidade separam terra/água rasa, natação funda e ponte.
- Foram testadas rota plana, slopes, step, água rasa, deep swim, veículo sem
  capacidade aquática, sob ponte, sobre ponte, obstáculo e replanejamento.
- O fechamento dinâmico de uma das duas rotas ao redor do bloqueador recompõe a
  NavigationMesh, preserva a intenção em curso e produz rota alternativa válida.

### Água/corrente

- Volumes carregam profundidade, corrente/direção, classe rasa/funda,
  `swimmable`, veículo permitido e `under_bridge`.
- Player/NPC/animal recebem WADE em água rasa e SWIM local/presentation em água
  funda; veículo comum é bloqueado em água funda.
- Veículo raso expõe penalidade de tração/velocidade e stamina zero.
- Corrente forte expõe fator candidato maior e deslocamento visual suave/capado.
- Exaustão, grace window e derrota continuam no runtime Stage16A; não foram
  marcadas como PASS de integração live.

### Streaming

- Protótipo lógico 5x5 com célula 256 m: 1 ACTIVE + 8 PRELOAD + 16 SYSTEMIC no
  centro da grade.
- Mudança de célula ativa descarrega cenas fora do ring e preserva `cell_ref` e
  `living_macro_ref` em referência sistêmica.
- Não há simulação Living em GDScript e uma região inteira nunca é carregada.

### Ground Loot/Bolsa

- Ground Loot e Bolsa caem como RigidBody e assentam em colisão real.
- Entrada na água ocorre cruzando fisicamente o volume, não por coleta remota.
- Ground Loot em água fica `RECOVERABLE_IN_WATER`; Bolsa fica `FLOATING`.
- 900 s/1800 s e ausência de expiração em terra são apenas metadados de contrato;
  `authoritative_ttl_advanced_locally=false`.

## Correções encontradas no ciclo

1. A primeira rodada tinha conversão `float(null)` no gate, tolerância de contato
   rígida demais, chave antiga da câmera e direção incorreta no teste de zoom.
   O gate foi corrigido; nenhum desses resultados foi contado como PASS.
2. Itens congelados teletransportados já dentro de um Area3D podiam não registrar
   sobreposição após longa execução. O fluxo final passou a representar o caso
   real: corpo físico nasce acima do volume, cai e cruza a superfície.
3. A Bolsa era posicionada 4 cm fora do volume e alternava enter/exit. Sua raiz
   física agora permanece 4 cm dentro do volume, enquanto o visual fica sobre a
   linha d'água.
4. Máscaras de Ground Loot/Bolsa passaram a incluir WATER_VOLUME mantendo layers
   distintas (16 e 4096). B03 foi regredida integralmente.
5. A primeira execução funcional pelo Editor Bridge encontrou dois warnings de
   ternários incompatíveis (`float|null` e `null|string`). O PASS numérico foi
   invalidado; os caminhos foram convertidos para atribuição Variant explícita e
   headless + bridge foram reiniciados com debugger limpo.
6. A primeira tentativa de auditoria de hashes usou uma API .NET indisponível no
   PowerShell 5.1 (`Convert.ToHexString`) e foi invalidada. A auditoria foi refeita
   com `BitConverter`, `ErrorActionPreference=Stop` e confronto SHA-256 real.

Rodadas R1–R6 são diagnósticas/FAIL e permanecem registradas; R7 e o runtime final
são PASS. O diagnóstico temporário de água foi removido após confirmar a causa.

## Testes finais

- B04 headless: 156/156 PASS, exit 0, zero markers de warning/error.
- B04 Editor Bridge: 156/156 PASS, `errors: []`, stop limpo.
- Main direta via Editor Bridge: startup/execução/stop limpos.
- B01: 54/54 PASS.
- B02: 90/90 PASS.
- B03: 357/357 PASS.
- Stage16A: 209/209 PASS em 257,260 s, `OK`, exit 0.
- Stage16A stress: 20/20 PASS, exit 0.
- Baseline: 724/724 SHA-256 idênticos, zero missing/mismatch.
- `06_GODOT_LIVING_V1_5`: 4/4 arquivos do checkpoint idênticos.
- Checkpoint SHA-256: `21626A3152CB37E167EEE24BFF9D3142C5D389A8CA2827594B34211591525A6A`.
- Master SHA-256: `6D9AC3CCE7DCF6A65FDCF73859C332A0211C1AF52D149077BEEF554BF7BBD0B2`.

## Acceptance Matrix

- PASS: G16B-01, G16B-02, G16B-07.
- PARTIAL_EVIDENCE: G16B-03, G16B-04, G16B-08, G16B-09, G16B-11,
  G16B-14, G16B-20, G16B-24, G16B-25, G16B-27.
- Demais gates: não executados/não promovidos.

## Blockers e watch items

- `127.0.0.1:8000`: zero listeners; integração live de stamina, exaustão/morte,
  TTL/save-reload e snapshot Living está `NOT_AVAILABLE`, sem backend substituto.
- Fade material real de oclusores continua parcial; somente probe/preparação B02.
- Natação final, animação e veículo controlável continuam placeholders.
- Streaming local preserva referências, mas não afirma snapshot Living live.
- `config/name` continua com o rótulo B03 porque `project.godot` não estava no
  conjunto de arquivos autorizado na declaração pré-edição; `run/main_scene`
  permanece correto. É somente watch item cosmético.

Nenhum backup final foi criado. B05 não foi iniciada.
