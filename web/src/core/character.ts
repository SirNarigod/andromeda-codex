// Criação de personagem jogável: identidade Andrômeda preservada.
// Classes Nativo/Soldado/Android/Mago (+ Corrompidos só como inimigos).
import { deriveStats, mapAttrs } from "./combat/formulas";
import { armorMods, combineMods, emptyMods, weaponMods } from "./combat/equipment";
import type { Combatant } from "./combat/types";
import type { ClassDef, Item, Weapon } from "../data/schemas";

export const PLAYABLE_CLASSES = ["Nativos", "Soldados", "Androids", "Magos"] as const;
export type PlayableClass = (typeof PLAYABLE_CLASSES)[number];

export interface PlayerCharacter {
  name: string;
  classId: PlayableClass;
  origin: string; // território de origem (id TER)
  level: number;
  xp: number;
  hp: number;
  maxHp: number;
  sp: number;
  stavias: number;
  weaponId: string | null;
  armorId: string | null;
  inventory: string[]; // item ids
  packSlots: number;
  affinities: { TEC: number; MAG: number };
  states: string[]; // ferido | exausto | corrompido
}

export function levelForXp(xp: number): number {
  return Math.min(5, 1 + Math.floor(xp / 100));
}

export function createCharacter(name: string, cls: ClassDef, origin: string, weapon: Weapon | undefined): PlayerCharacter {
  return {
    name,
    classId: cls.id as PlayableClass,
    origin,
    level: 1,
    xp: 0,
    hp: cls.hp,
    maxHp: cls.hp,
    sp: 10,
    stavias: 60,
    weaponId: weapon?.id ?? null,
    armorId: null,
    inventory: weapon ? [weapon.id] : [],
    packSlots: 12,
    affinities: { TEC: cls.attrs.TEC, MAG: cls.attrs.MAG },
    states: [],
  };
}

/** Converte o personagem em Combatant (arma/armadura somam via equipment). */
export function toCombatant(
  pc: PlayerCharacter,
  cls: ClassDef,
  weapon: Weapon | undefined,
  armor: Item | undefined,
): Combatant {
  const inp = mapAttrs(cls.attrs, pc.level);
  const mods = combineMods(weaponMods(weapon), armorMods(armor), emptyMods());
  const st = deriveStats(inp, {
    armor: mods.armor, evasion: mods.evasion, accuracy: mods.accuracy,
    critChance: mods.critChance, damageFlat: mods.damageFlat, damagePct: mods.damagePct,
  });
  return {
    ref: "player",
    name: pc.name,
    side: "party",
    hp: pc.hp,
    maxHp: pc.maxHp,
    armor: st.armor,
    evasion: st.evasion,
    accuracy: st.accuracy,
    baseDamage: st.baseDamage,
    critChance: st.critChance,
    critMultiplier: st.critMultiplier,
    level: pc.level,
    agility: cls.attrs.AGI,
    statuses: [],
    defending: false,
    alive: pc.hp > 0,
    cooldowns: {},
    isPlayer: true,
  };
}

/** Converte criatura/NPC tático em Combatant inimigo (xp_reward = 20 + level*15, fiel ao core). */
export function foeCombatant(ref: string, name: string, hp: number, armor: number, level: number, agility: number, baseDamage: number): Combatant {
  return {
    ref, name, side: "foes", hp, maxHp: hp, armor,
    evasion: 10 + level, accuracy: 40 + level * 2, baseDamage,
    critChance: 4 + (level % 5), critMultiplier: 1.5, level, agility,
    statuses: [], defending: false, alive: true, cooldowns: {},
  };
}

export function xpReward(tierLevel: number): number {
  return 20 + tierLevel * 15;
}
