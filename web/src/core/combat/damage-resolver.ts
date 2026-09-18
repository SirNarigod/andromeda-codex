// Fiel a ARPGCombatCore._resolve_damage.
import { armorMitigation, resistanceMitigation, r6 } from "./formulas";

export interface DamageInput {
  raw: number;
  damageType: string; // PHYSICAL usa armor; demais usam resistance
  attackerLevel: number;
  targetArmor: number;
  targetResistance: number;
  critical: boolean;
  critMultiplier: number;
}

export interface DamageOutput {
  raw: number;
  preMitigation: number;
  mitigationPct: number;
  final: number;
}

export function resolveDamage(inp: DamageInput): DamageOutput {
  const premit = inp.raw * (inp.critical ? inp.critMultiplier : 1);
  const mitigation =
    inp.damageType === "PHYSICAL"
      ? armorMitigation(inp.targetArmor, inp.attackerLevel)
      : resistanceMitigation(inp.targetResistance);
  const final = Math.max(0.1, premit * (1 - mitigation));
  return { raw: r6(inp.raw), preMitigation: r6(premit), mitigationPct: r6(mitigation * 100), final: r6(final) };
}
