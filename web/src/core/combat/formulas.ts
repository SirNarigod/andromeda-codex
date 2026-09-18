// Adaptação runtime (RUNTIME_ONLY): o arpg_combat_core calcula stats a partir de
// attributes {PERCEPTION, AGILITY, ...} + derived {power/precision/resilience_potential}.
// O M1 usa os 6 atributos web (FOR/AGI/VIT/TEC/MAG/DEF, medianas da matriz de armas).
// Mapeamento fixo abaixo; FÓRMULAS de hit/crit/dano/mitigação são byte-fieis ao Python.
// Ver docs/runtime/combat-port.md.
import type { ClassAttrs } from "../../data/schemas";

export interface CombatInputs {
  power: number;      // power_potential
  precision: number;  // precision_potential
  resilience: number; // resilience_potential
  perception: number; // PERCEPTION
  agility: number;    // AGILITY
  level: number;
}

export function mapAttrs(a: ClassAttrs, level: number): CombatInputs {
  return {
    power: a.FOR,
    precision: (a.AGI + a.TEC) / 2,
    resilience: (a.VIT + a.DEF) / 2,
    perception: (a.AGI + a.MAG) / 2,
    agility: a.AGI,
    level,
  };
}

// Derivação fiel a ARPGCombatCore.player_stats (sem equipment/skill modifiers no M1-base;
// equipamento entra via equipment.ts somando os mesmos campos).
export interface DerivedStats {
  level: number; armor: number; evasion: number; accuracy: number;
  baseDamage: number; critChance: number; critMultiplier: number; rangeM: number;
}

export const MIN_HIT = 20.0;
export const MAX_HIT = 98.0;
export const MAX_CRIT = 50.0;
export const MAX_ARMOR_MIT = 0.75;
export const BASIC_RANGE_M = 2.75;
export const FORMULA_VERSION = "ARPG_COMBAT_FORMULAS_V0_4_0";

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export function deriveStats(inp: CombatInputs, mods?: Partial<DerivedStats> & { damageFlat?: number; damagePct?: number }): DerivedStats {
  const m = mods ?? {};
  const armor = (m.armor ?? 0) + inp.resilience * 0.55 + inp.level * 0.5;
  const evasion = (m.evasion ?? 0) + inp.agility * 1.2 + inp.perception * 0.6 + inp.level * 0.25;
  const accuracy = (m.accuracy ?? 0) + inp.precision * 3.5 + inp.level * 2.0;
  let baseDamage = 8.0 + inp.power * 0.55 + inp.level * 0.8;
  baseDamage = (baseDamage + (m.damageFlat ?? 0)) * (1 + (m.damagePct ?? 0) / 100);
  const crit = clamp(5.0 + inp.perception * 0.22 + inp.agility * 0.1 + (m.critChance ?? 0), 0, MAX_CRIT);
  const critMultiplier = 1.5 + Math.min(0.5, inp.agility * 0.005);
  return {
    level: inp.level,
    armor: r6(armor), evasion: r6(evasion), accuracy: r6(accuracy),
    baseDamage: r6(baseDamage), critChance: r6(crit), critMultiplier: r6(critMultiplier),
    rangeM: BASIC_RANGE_M,
  };
}

export function armorMitigation(armor: number, attackerLevel: number): number {
  const a = Math.max(0, armor);
  return Math.min(MAX_ARMOR_MIT, a / (a + 100 + Math.max(1, attackerLevel) * 10));
}

export function resistanceMitigation(resistance: number): number {
  return clamp(resistance, -50, 75) / 100;
}

export function hitChance(acc: number, eva: number): number {
  return clamp(75 + (acc - eva) * 0.18, MIN_HIT, MAX_HIT);
}

export function r6(v: number): number {
  return Math.round(v * 1e6) / 1e6;
}
