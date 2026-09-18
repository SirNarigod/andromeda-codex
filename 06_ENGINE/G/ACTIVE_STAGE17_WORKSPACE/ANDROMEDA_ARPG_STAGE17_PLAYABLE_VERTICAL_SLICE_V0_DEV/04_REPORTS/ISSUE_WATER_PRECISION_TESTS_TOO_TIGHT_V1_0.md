# Issue: tolerância de precisão irreal em 2 testes de água (save/reload real)

**Status**: aberta, fora de escopo da rodada de 16/09 (decisão explícita do usuário: tratar depois).

## Onde
- `12_AUTHORITY_BACKEND_STAGE17/tests/test_stage16b_authority_dev_water_time.py::test_01_899_alive_save_reload_900_sunk_via_command`
- `12_AUTHORITY_BACKEND_STAGE17/tests/test_stage16b_authority_save_death_water.py::test_09_ground_loot_899_seconds_survives_real_save_reload_then_sinks`
- `12_AUTHORITY_BACKEND_STAGE17/tests/test_stage16b_authority_save_death_water.py::test_11_water_bag_1799_seconds_survives_save_reload_then_sinks`

## O problema
Cada teste avança o relógio de água por um valor exato via comando dev (`delta_s=899.0`, por exemplo), faz um **save + reload reais** (fecha e reabre a conexão SQLite do mundo, disco de verdade), e então exige `assertAlmostEqual(899.0, valor_restaurado, places=3)` ou `places=5` — ou seja, tolerância de 0,001s a 0,00001s.

Qualquer round-trip real de save/reload consome tempo de parede genuíno (I/O de disco, reconstrução do motor). Nesta máquina, esse custo observado ficou entre 0,07s e 0,14s — **muito acima** da tolerância exigida.

## Como foi descoberto
Durante a implementação do motor de tick em thread de fundo (16/09), a suíte completa (306 testes) apontou esses 3 testes falhando. Investigação:
1. Suspeitei do motor de tick novo (rajada de até 12 ticks síncronos por chamada).
2. Revertida a chamada automática do tick, os mesmos 3 testes **continuaram falhando com magnitude idêntica** — isolado, máquina sem carga, 2 tentativas.
3. Confirma: não é o motor de tick. É uma característica pré-existente de qualquer save/reload real nesta (ou qualquer) máquina.

## Correção sugerida (não implementada)
Uma das duas:
- Relaxar a tolerância desses 3 testes especificamente pra algo realista pra I/O de disco real (ex.: `places=1` ou um delta absoluto de ±0.5s), já que o próprio nome do teste diz "REAL_save_reload" — não deveria fingir precisão de laboratório.
- Ou, se a intenção for testar a MATEMÁTICA do relógio de água isoladamente (sem I/O real), separar essa asserção pra rodar sem o save/reload real no meio (testar advance_water_time() puro, sem round-trip de disco).

## Verificação de quem pega essa issue
Reproduzir com: `python -m unittest test_stage16b_authority_save_death_water.Stage16BAuthoritySaveDeathWaterTests.test_09_ground_loot_899_seconds_survives_real_save_reload_then_sinks -v` (env `ANDROMEDA_MASTER_RELEASE` apontando pro zip do master).
