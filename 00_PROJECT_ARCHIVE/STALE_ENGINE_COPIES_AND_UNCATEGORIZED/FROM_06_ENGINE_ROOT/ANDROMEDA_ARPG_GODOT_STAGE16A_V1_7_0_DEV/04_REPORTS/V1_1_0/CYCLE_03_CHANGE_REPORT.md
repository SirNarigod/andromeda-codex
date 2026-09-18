# CYCLE 03 — COMBAT + RESOURCES

Status: **PASS (V1.1.0-DEV)**

## Mudanças aplicadas
- `SPAWN` atômico e event-sourced adicionado ao core, com replay correto de entidades dinâmicas.
- `CombatSystem`: MAR -> equipamento -> combate -> vida -> morte.
- Equipar retira o item do inventário; desequipar devolve.
- Condição/durabilidade do equipamento degrada por uso.
- Combate exige co-localização e respeita proteção narrativa contra morte.
- Morte letal cria `CORPSE` no mesmo evento.
- Coleta do cadáver cria `RESOURCE_BUNDLE` uma única vez.
- `COMBAT_RESOLVED` alimenta testemunhas sociais e reconciliação ecológica via Integration Hub.

## Validação
- Runtime core original: 59/59 PASS.
- Domain + Commerce + Combat + SPAWN: 27/27 PASS.
- Escopo afetado total: **86/86 PASS**.

Nenhum valor de dano, vida, rendimento ou condição foi promovido à Master; são políticas runtime de balanceamento.
