# CHANGELOG V0.1.12

## Controle do mouse

- Corrigido regressão da V0.1.11 em que clique curto no chão parava ao soltar.
- Clique curto esquerdo/direito agora persiste até o destino.
- Hold é detectado após 0,18 s e passa a seguir o cursor; release após hold emite parada imediata.
- Movimento inicial ocorre já no press, portanto a janela de detecção não cria atraso perceptível.
- Direito contextual preserva aproximação/interação/ataque mesmo após soltar.
- Entradas/saídas permanecem acionáveis por clique esquerdo.
- Cooldown de ataque de 2,0 s permanece centralizado em `_perform_attack_on()`.
