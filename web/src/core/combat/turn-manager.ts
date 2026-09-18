// Turn Manager: ordem por agilidade, rodadas, fuga, fim de batalha.
import { tickStatuses } from "./status";
import type { Combatant, Side } from "./types";

export interface BattleState {
  round: number;
  combatants: Combatant[];
  order: string[]; // refs na ordem do turno
  cursor: number;
  over: boolean;
  winner: Side | "fled" | null;
}

export function startBattle(combatants: Combatant[]): BattleState {
  const order = [...combatants]
    .filter((c) => c.alive)
    .sort((a, b) => b.agility - a.agility)
    .map((c) => c.ref);
  return { round: 1, combatants, order, cursor: 0, over: false, winner: null };
}

export function currentActor(b: BattleState): Combatant | undefined {
  return b.combatants.find((c) => c.ref === b.order[b.cursor]);
}

/** Avança o cursor; pula mortos; incrementa rodada ao fechar a volta. */
export function nextTurn(b: BattleState): Combatant | undefined {
  if (b.over) return undefined;
  for (let i = 0; i < b.order.length; i++) {
    b.cursor = (b.cursor + 1) % b.order.length;
    if (b.cursor === 0) {
      b.round += 1;
      for (const c of b.combatants) {
        for (const k of Object.keys(c.cooldowns)) {
          c.cooldowns[k] = Math.max(0, c.cooldowns[k] - 1);
        }
        c.defending = false;
      }
    }
    const c = currentActor(b);
    if (c && c.alive) return c;
  }
  return undefined;
}

/** Tick de status no início do turno do combatente. */
export function beginTurn(c: Combatant): { dotDamage: number; expired: string[] } {
  return tickStatuses(c);
}

export function checkEnd(b: BattleState): Side | null {
  const partyAlive = b.combatants.some((c) => c.side === "party" && c.alive);
  const foesAlive = b.combatants.some((c) => c.side === "foes" && c.alive);
  if (!partyAlive) { b.over = true; b.winner = "foes"; return "foes"; }
  if (!foesAlive) { b.over = true; b.winner = "party"; return "party"; }
  return null;
}

/** Fuga: CD 10 (AGI do fugitivo como bônus); falha = turno perdido. */
export function tryFlee(c: Combatant, roll: () => number): boolean {
  const chance = Math.min(0.95, 0.5 + c.agility / 100);
  return roll() < chance;
}
