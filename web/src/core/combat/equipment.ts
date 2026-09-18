// Efeitos de equipamento: somam os mesmos campos de deriveStats (mods),
// fiel ao estágio 05 do arpg_combat_core (equipment_modifiers).
import type { Item, Weapon } from "../../data/schemas";

export interface EquipmentMods {
  damageFlat: number;
  damagePct: number;
  armor: number;
  evasion: number;
  accuracy: number;
  critChance: number;
  rangeBonusM: number;
}

export function emptyMods(): EquipmentMods {
  return { damageFlat: 0, damagePct: 0, armor: 0, evasion: 0, accuracy: 0, critChance: 0, rangeBonusM: 0 };
}

/** Arma empunhada: power vira dano base (escala runtime: pow/10). */
export function weaponMods(w: Weapon | undefined): EquipmentMods {
  const m = emptyMods();
  if (!w) return m;
  m.damageFlat = (w.pow ?? 0) / 10;
  m.accuracy = (w.hdl ?? 40) / 10;
  return m;
}

/** Armadura: bonus direto (fx.armor do catálogo). */
export function armorMods(item: Item | undefined): EquipmentMods {
  const m = emptyMods();
  if (!item) return m;
  const fx = item.fx as { armor?: number };
  if (typeof fx.armor === "number") m.armor = fx.armor;
  return m;
}

export function combineMods(...mods: EquipmentMods[]): EquipmentMods {
  const out = emptyMods();
  for (const m of mods) {
    out.damageFlat += m.damageFlat;
    out.damagePct += m.damagePct;
    out.armor += m.armor;
    out.evasion += m.evasion;
    out.accuracy += m.accuracy;
    out.critChance += m.critChance;
    out.rangeBonusM += m.rangeBonusM;
  }
  return out;
}
