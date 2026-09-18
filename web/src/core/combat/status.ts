// Status effects: condições da Mesa (dur/atk/evm/dot) + estados web (ferido/exausto/corrompido).
import type { Combatant, StatusState } from "./types";

export interface StatusDef {
  id: string;
  rounds: number | null;
  atkMod: number;
  evmMult: number;
  dot: number;
  immobilize?: boolean;
}

// Definições das 4 condições (mesmos números da Mesa fase 72).
export const STATUS_DEFS: Record<string, StatusDef> = {
  CONTENCAO: { id: "CONTENCAO", rounds: null, atkMod: -4, evmMult: 0.7, dot: 0, immobilize: true },
  OFUSCADO: { id: "OFUSCADO", rounds: 1, atkMod: -5, evmMult: 1.0, dot: 0 },
  ESPORO: { id: "ESPORO", rounds: 3, atkMod: 0, evmMult: 1.0, dot: 2 },
  RAIZ: { id: "RAIZ", rounds: 3, atkMod: 0, evmMult: 0.7, dot: 2, immobilize: true },
  ferido: { id: "ferido", rounds: null, atkMod: -2, evmMult: 1.0, dot: 0 },
  exausto: { id: "exausto", rounds: null, atkMod: -2, evmMult: 0.9, dot: 0 },
  corrompido: { id: "corrompido", rounds: null, atkMod: 0, evmMult: 1.0, dot: 1 },
};

export function applyStatus(c: Combatant, id: string): void {
  const def = STATUS_DEFS[id];
  if (!def) return;
  const existing = c.statuses.find((s) => s.id === id);
  const state: StatusState = { id, roundsLeft: def.rounds, atkMod: def.atkMod, evmMult: def.evmMult, dot: def.dot };
  if (existing) Object.assign(existing, state);
  else c.statuses.push(state);
}

export function removeStatus(c: Combatant, id: string): void {
  c.statuses = c.statuses.filter((s) => s.id !== id);
}

export function isImmobilized(c: Combatant): boolean {
  return c.statuses.some((s) => STATUS_DEFS[s.id]?.immobilize);
}

/** Aplica DoT e decrementa durações no início do turno do combatente. Retorna dano total. */
export function tickStatuses(c: Combatant): { dotDamage: number; expired: string[] } {
  let dotDamage = 0;
  const expired: string[] = [];
  for (const s of c.statuses) {
    dotDamage += s.dot;
    if (s.roundsLeft !== null) {
      s.roundsLeft -= 1;
      if (s.roundsLeft <= 0) expired.push(s.id);
    }
  }
  if (expired.length) c.statuses = c.statuses.filter((s) => !expired.includes(s.id));
  if (dotDamage > 0) {
    c.hp = Math.max(0, c.hp - dotDamage);
    if (c.hp <= 0) c.alive = false;
  }
  return { dotDamage, expired };
}

export function effectiveAccuracy(c: Combatant): number {
  return c.accuracy + c.statuses.reduce((a, s) => a + s.atkMod, 0);
}

export function effectiveEvasion(c: Combatant): number {
  return c.evasion * c.statuses.reduce((a, s) => a * s.evmMult, 1);
}

/** Marca ferido (<50% PV). Chamado após qualquer dano. */
export function updateWounded(c: Combatant): void {
  if (c.alive && c.hp < c.maxHp / 2 && !c.statuses.some((s) => s.id === "ferido")) applyStatus(c, "ferido");
  if (c.hp >= c.maxHp / 2) removeStatus(c, "ferido");
}
