# Andrômeda Códex ARPG — Stage 16B — B05

## Escopo fechado

B05 implementa a fundação Godot de HUD, World UI, diálogo em tempo real,
stamina radial, dois quick-slots e shell de inventário/Bolsa. Todo o código é
de apresentação, input ou projeção de snapshot; conteúdo de gameplay continua
autoritativo fora do GDScript.

## UI

- tema compartilhado branco/off-white, cantos de 14 px, texto cinza e laranja
  claro para informação importante;
- fonte de sistema com candidatos arredondados e fallbacks; asset tipográfico
  final permanece adiado;
- HUD mínimo e contextual, com painéis grandes apenas quando o inventário é
  aberto por `I`;
- nenhum asset Nintendo/Zelda foi copiado e nenhuma arte final foi adicionada.

## Stamina

`StaminaWorldRing.tscn` é um `Control` em espaço de tela que acompanha a
projeção do Player. O arco amarelo diminui/aumenta conforme a fração recebida,
permanece visível durante consumo/regeneração e some completamente em 100%
inativa. Não há número permanente nem barra horizontal.

## Armas e input

- exatamente dois quick-slots visuais;
- somente um slot projetado como ativo;
- `1` e `2` selecionam seus slots;
- roda sem modificador alterna entre eles;
- `Shift` + roda preserva o zoom B02;
- com inventário aberto, roda é somente scroll.

A troca cria um envelope para o bridge existente, mas não o submete. A ativação
real de `MAIN_HAND`, persistência e modificadores continuam na Stage16A.

## Diálogo

O pool tem até três balões brancos arredondados. Uma conversa usa um balão por
vez e alterna o speaker por turno, evitando spam. Texto normal é cinza; fala
importante é laranja claro e também aparece na linha inferior de acessibilidade.
Não existe botão `Próximo`, pausa do mundo ou trava de movimento. Choices são
pequenas e próximas ao NPC. Os textos B05 são placeholders de teste, nunca
cânone narrativo.

## Inventário e Auto Pickup

O shell mostra inventário-base reduzido, `BAG_SLOT`, container de Bolsa,
equipamento, referência aos slots 1/2, tooltip e controle Auto Pickup ON/OFF.
Conteúdo, peso, persistência, morte e coleta permanecem externos ao cliente.
O controle Auto Pickup nunca habilita coleta remota.

## Execução do gate

```powershell
& 'C:\Program Files\Godot\Godot.exe' --headless --path . `
  --scene res://tests/godot/B05RuntimeGate.tscn -- --gate-success-linger=0
```

Resultado final: `210/210 PASS` headless e `210/210 PASS` pelo Editor Bridge,
com debugger final em `0 erros / 0 warnings`.

Regressões finais: B01 `54/54`, B02 `90/90`, B03 `357/357`, B04 `156/156`,
Stage16A `209/209`, stress `20/20`, baseline `724/724`.

B06 não foi iniciada e nenhum backup final da Stage 16 foi criado.

