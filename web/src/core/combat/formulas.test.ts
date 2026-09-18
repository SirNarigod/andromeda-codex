import { describe, expect, it } from "vitest";
import { armorMitigation, deriveStats, hitChance, mapAttrs, resistanceMitigation } from "./formulas";
import { resolveDamage } from "./damage-resolver";

describe("fórmulas (paridade com arpg_combat_core.py)", () => {
  it("hit 75+(acc-eva)*0.18 clamp [20,98]", () => {
    expect(hitChance(62.5, 40)).toBeCloseTo(79.05, 6);
    expect(hitChance(0, 1000)).toBe(20);
    expect(hitChance(1000, 0)).toBe(98);
  });
  it("armorMitigation = min(0.75, armor/(armor+100+lv*10))", () => {
    expect(armorMitigation(30, 1)).toBeCloseTo(0.21428571428571427, 9);
    expect(armorMitigation(10000, 1)).toBe(0.75);
    expect(armorMitigation(-5, 1)).toBe(0);
  });
  it("resistanceMitigation = clamp/100", () => {
    expect(resistanceMitigation(20)).toBe(0.2);
    expect(resistanceMitigation(500)).toBe(0.75);
    expect(resistanceMitigation(-500)).toBe(-0.5);
  });
  it("mapAttrs usa medianas da classe (Nativos: FOR54 AGI44 VIT33 TEC35 MAG32 DEF26)", () => {
    const m = mapAttrs({ FOR: 54, AGI: 44, VIT: 33, TEC: 35, MAG: 32, DEF: 26 }, 1);
    expect(m).toEqual({ power: 54, precision: 39.5, resilience: 29.5, perception: 38, agility: 44, level: 1 });
  });
  it("deriveStats reproduz player_stats (Nativos nv1, sem mods)", () => {
    const st = deriveStats(mapAttrs({ FOR: 54, AGI: 44, VIT: 33, TEC: 35, MAG: 32, DEF: 26 }, 1));
    expect(st.armor).toBeCloseTo(29.5 * 0.55 + 0.5, 6);
    expect(st.evasion).toBeCloseTo(44 * 1.2 + 38 * 0.6 + 0.25, 6);
    expect(st.accuracy).toBeCloseTo(39.5 * 3.5 + 2.0, 6);
    expect(st.baseDamage).toBeCloseTo(8 + 54 * 0.55 + 0.8, 6);
    expect(st.critChance).toBeCloseTo(5 + 38 * 0.22 + 44 * 0.1, 6);
    expect(st.critMultiplier).toBeCloseTo(1.5 + Math.min(0.5, 44 * 0.005), 6);
  });
  it("resolveDamage: final = max(0.1, raw*crit*(1-mit))", () => {
    const d = resolveDamage({ raw: 10, damageType: "PHYSICAL", attackerLevel: 1, targetArmor: 30, targetResistance: 0, critical: false, critMultiplier: 1.5 });
    expect(d.final).toBeCloseTo(10 * (1 - 0.21428571428571427), 6);
    const floor = resolveDamage({ raw: 0, damageType: "PHYSICAL", attackerLevel: 1, targetArmor: 0, targetResistance: 0, critical: false, critMultiplier: 1.5 });
    expect(floor.final).toBe(0.1);
  });
});
