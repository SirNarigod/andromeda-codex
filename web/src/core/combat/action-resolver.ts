// Action Resolver: alcance por bandas MAR + hit/crit/dano (fórmulas do arpg_combat_core).
import type { Band } from "../../data/schemas";
import { hitChance, r6 } from "./formulas";
import { resolveDamage } from "./damage-resolver";
import { effectiveAccuracy, effectiveEvasion } from "./status";
import type { AttackResult, Combatant } from "./types";

export interface RangeCheck {
  band: string;
  distanceM: number;
  meleeMult: number;
  rangedMult: number;
  allowed: boolean;
  blockReason?: string;
}

/** Classifica a distância na banda e diz se ataque corpo-a-corpo (melee=true) ou tiro é permitido. */
export function checkRange(bands: Band[], distanceM: number, melee: boolean): RangeCheck {
  const sorted = [...bands].sort((a, b) => a.m - b.m);
  let band = sorted[sorted.length - 1];
  for (const b of sorted) {
    if (distanceM <= b.m) { band = b; break; }
  }
  const meleeMult = band.melee ?? 0;
  const rangedMult = band.ranged ?? 0;
  const mult = melee ? meleeMult : rangedMult;
  if (mult <= 0) {
    return {
      band: band.n, distanceM, meleeMult, rangedMult, allowed: false,
      blockReason: melee ? "ALCANCE_CORPO_A_CORPO" : "TIRO_BLOQUEADO",
    };
  }
  return { band: band.n, distanceM, meleeMult, rangedMult, allowed: true };
}

export interface AttackInput {
  attacker: Combatant;
  target: Combatant;
  seed: string | number;
  eventRef: string;
  bands: Band[];
  distanceM: number;
  melee: boolean;
  roll: () => number; // [0,1) — injetado (stableRoll em produção, mock em testes)
}

export function resolveAttack(inp: AttackInput): AttackResult {
  const { attacker, target } = inp;
  const range = checkRange(inp.bands, inp.distanceM, inp.melee);
  if (!range.allowed) {
    return { hit: false, critical: false, hitChance: 0, damage: 0, mitigationPct: 0, killed: false, blocked: range.blockReason };
  }
  const acc = effectiveAccuracy(attacker);
  const eva = effectiveEvasion(target) * (target.defending ? 1.25 : 1);
  const hc = hitChance(acc, eva);
  const hitRoll = inp.roll() * 100;
  const hit = hitRoll < hc;
  const critRoll = inp.roll() * 100;
  const critical = hit && critRoll < attacker.critChance;
  if (!hit) {
    return { hit, critical: false, hitChance: r6(hc), damage: 0, mitigationPct: 0, killed: false };
  }
  const bandMult = inp.melee ? range.meleeMult : range.rangedMult;
  const raw = attacker.baseDamage * bandMult * (target.defending ? 0.5 : 1);
  const dmg = resolveDamage({
    raw,
    damageType: attacker.damageType ?? "PHYSICAL",
    attackerLevel: attacker.level,
    targetArmor: target.armor,
    targetResistance: target.resistance ?? 0,
    critical,
    critMultiplier: attacker.critMultiplier,
  });
  target.hp = Math.max(0, r6(target.hp - dmg.final));
  if (target.hp <= 0) target.alive = false;
  return { hit, critical, hitChance: r6(hc), damage: dmg.final, mitigationPct: dmg.mitigationPct, killed: !target.alive };
}
