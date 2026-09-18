# Andrômeda First Playable V0.1.8

## Corrigido
- Velúrio/fauna hostil não recalcula A* a cada frame/contato físico.
- Repath da fauna agora é orientado por mudança real do alvo e travamento horizontal confirmado.
- Aproximação A* de fauna usa amostragem reduzida para evitar picos fortes de CPU.

## Adicionado
- Clique esquerdo em entradas/saídas de áreas (ex.: masmorra) é tratado como movimento de transição: o personagem caminha até a entrada e atravessa automaticamente.
- Botão direito mantém movimento + interação contextual.

## Preservado
- Navegação por ponte/água.
- Hover contextual.
- Porta/cadeira em toggle.
- Auto-ataque do jogador a cada 2 segundos.
