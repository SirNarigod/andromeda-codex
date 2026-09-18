// Índice de dados gerados (tools/gen_web_data.py). Importação tipada dos JSONs.
import type {
  Band, ClassDef, Commerce, Condition, Creature, Currency, Econ, EncounterProfile,
  Est, Fauna, Item, Landscape, LootTable, Manifest, Npc, Civilian, Pack, Quest,
  Route, Skill, Territory, VargaPoi, Weapon, Arsenal,
} from "./schemas";
import territories from "./territories.json";
import routes from "./routes.json";
import landscapes from "./landscapes.json";
import creatures from "./creatures.json";
import npcs from "./npcs.json";
import civilians from "./civilians.json";
import classes from "./classes.json";
import packs from "./packs.json";
import skills from "./skills.json";
import arsenal from "./arsenal.json";
import quests from "./quests.json";
import est from "./est.json";
import currencies from "./currencies.json";
import econ from "./econ.json";
import commerce from "./commerce.json";
import fauna from "./fauna.json";
import encProfiles from "./enc_profiles.json";
import loot from "./loot.json";
import conditions from "./conditions.json";
import varga from "./varga.json";
import items from "./items.json";
import weapons from "./weapons.json";
import bands from "./bands.json";
import speeds from "./speeds.json";
import manifest from "./manifest.json";

export const DATA = {
  territories: territories as Territory[],
  routes: routes as Route[],
  landscapes: landscapes as Landscape[],
  creatures: creatures as Creature[],
  npcs: npcs as Npc[],
  civilians: civilians as Civilian[],
  classes: classes as ClassDef[],
  packs: packs as Pack[],
  skills: skills as Skill[],
  arsenal: arsenal as Arsenal,
  quests: quests as Quest[],
  est: est as Est[],
  currencies: currencies as Currency[],
  econ: econ as Econ[],
  commerce: commerce as Commerce,
  fauna: fauna as Fauna[],
  encProfiles: encProfiles as EncounterProfile[],
  loot: loot as LootTable,
  conditions: conditions as Condition[],
  varga: varga as VargaPoi[],
  items: items as Item[],
  weapons: weapons as Weapon[],
  bands: bands as Band[],
  speeds: speeds as Record<string, string>,
  manifest: manifest as Manifest,
};

export const byId = <T extends { id: string }>(list: T[]): Map<string, T> =>
  new Map(list.map((x) => [x.id, x]));
