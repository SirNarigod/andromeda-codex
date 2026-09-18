// Tipos das fontes canonicas (geradas por tools/gen_web_data.py; nunca editar a mao).
export interface Territory { id: string; name: string; terrain: string; transport: string; xy: [number, number]; }
export interface Route { id: string; name: string; from: string; to: string; mode: string; scale: string; }
export interface Landscape { id: string; name: string; type: string; sub: string; ter: string; }
export interface Creature {
  id: string; name: string; tier: string; hp: number; df: number; sp: number; th: number;
  grp: string; act: string; yield: string; trait: string; hab: string;
}
export interface Npc {
  id: string; name: string; cls: string; tier: string; role: string; hp: number; sp: number;
  dg: number; ar: number; wp?: string[] | null; ps: string | null; as: string | null; sub: string | null;
}
export interface Civilian { id: string; name: string; job: string; est: string; tier: string; }
export interface ClassAttrs { FOR: number; AGI: number; VIT: number; TEC: number; MAG: number; DEF: number; }
export interface ClassDef { id: string; name: string; desc: string; fam: string; pref: string; attrs: ClassAttrs; hp: number; }
export interface Pack { id: string; name?: string; slots: number; price?: string; cat?: string; wt?: number; desc?: string; fx?: Record<string, unknown>; derived: boolean; }
export interface SkillFx { regen_pct?: number; when?: string; dr?: number; sp_regen?: number; buff?: number; heal_pct?: number; ally?: boolean; move?: number; cleanse?: string[]; }
export interface Skill { id: string; name: string; kind: string; cls: string; cost: string | number | null; cdr: number | null; fx: SkillFx; desc: string | null; }
export interface ArsenalClass { class_name: string; weapon_ids: string[]; }
export interface Arsenal { total_weapons: number; total_npcs: number; by_class: ArsenalClass[]; }
export interface QuestRes { id: string; t: string; }
export interface Quest { id: string; title: string; loc: string; premise: string; phases: string[]; res: QuestRes[]; }
export interface Est { id: string; name: string; type: string; loc: string; sub: string; ter: string; fn: string; }
export interface Item { id: string; name: string; cat: string; wt: number | null; price: string | null; prod: string | null; desc: string; link: string | null; fx: Record<string, unknown>; }
export interface Weapon {
  id: string; name: string; cls: string; fam: string; pow: number; rch: number; hdl: number;
  ovr: number; wt: number; traj: string; imp: string; area: string; tier: string; prod: string;
}
export interface Currency { id: string; name: string; ter: string | null; strength: string; mint: string | null; }
export interface Econ { ter: string; food: string; short: string | number; }
export interface Commerce { tiers: string[]; runtime_prices: Record<string, number>; note: string; }
export interface Fauna { cri: string; ter: string; also: string[]; bio: string[]; }
export interface EncounterProfile { id: string; src: string; title: string; mode: string; disp: string; trig: string[]; nonviol: string[]; story: string; }
export interface LootTable { table: Record<string, number>; note: string; }
export interface Condition { id: string; icon: string; name: string; dur: number | null; atk: number; evm: number; dot: number; desc: string; }
export interface VargaPoi { id: string; title: string; function: string; story_use: string; }
export interface Band { n: string; m: number; melee?: number; ranged?: number; evm?: number; grapple?: boolean; longpen?: number; sniper?: number; }
export interface Manifest { generator: string; sources: { path: string; sha16: string }[]; counts: Record<string, number>; }
