# Porte do combate Python → TypeScript (M1)

Fonte: `arpg_combat_core.py` (slice STAGE17; cópia STAGE16A idêntica — 750 linhas),
`FORMULA_VERSION = ARPG_COMBAT_FORMULAS_V0_4_0`.

## Fiel (mesma aritmética, testes de paridade em `formulas.test.ts`)
- `hit = 75 + (acc − eva) × 0.18`, clamp [20, 98]
- `armorMit = min(0.75, armor / (armor + 100 + lv×10))`
- `resistMit = clamp(res, −50, 75) / 100`
- `final = max(0.1, raw × (crit ? mult : 1) × (1 − mit))`
- `critChance = clamp(5 + PER×0.22 + AGI×0.10, 0, 50)`; `mult = 1.5 + min(0.5, AGI×0.005)`
- `armor = resPot×0.55 + lv×0.5`; `evasion = AGI×1.2 + PER×0.6 + lv×0.25`
- `accuracy = precPot×3.5 + lv×2`; `baseDmg = 8 + powPot×0.55 + lv×0.8`
- `xp_reward = 20 + lv×15`; RNG `sha256(seed|evento|canal)` (M1 usa seed string da store)
- PHYSICAL mitiga por armor; demais tipos por resistance

## Adaptado (RUNTIME_ONLY, turno-a-turno em vez de tempo real)
- Atributos Python (PERCEPTION/AGILITY + potentials) não existem no dado web;
  mapeamento fixo em `formulas.mapAttrs`: power=FOR, precision=(AGI+TEC)/2,
  resilience=(VIT+DEF)/2, perception=(AGI+MAG)/2, agility=AGI.
- `attack_interval_s`/`cooldown_s` (tempo real) → **rodadas**: 1 ação/rodada por
  combatente em ordem de AGI; `cdr` de skill = rodadas (já convertido na extração).
- `BASIC_RANGE_M = 2.75` + bandas MAR via `bands.json` (melee/ranged × por banda).
- Equipment/skill modifiers (estágios 05/07) aplicados como somas nos mesmos
  campos (`equipment.ts`); arma: `pow/10` dano, `hdl/10` precisão (runtime).
- `defend` (×0.5 dano recebido, evasão ×1.25) e `flee` (CD ~AGI) são invenção M1.
- Estados `ferido/exausto/corrompido` + 4 condições da Mesa com os mesmos números.
