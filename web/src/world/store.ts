// Store central serializável (single source of truth; UI só renderiza).
import type { PlayerCharacter } from "../core/character";

export const SAVE_VERSION = 1;

export interface Position {
  ter: string;
  x: number;
  y: number;
}

export interface QuestState {
  id: string;
  phase: string; // WELCOME | EVIDENCE | DECISION | REPORT | DONE
  resolution?: string;
}

export interface GameState {
  version: number;
  seed: string;
  player: PlayerCharacter;
  pos: Position;
  visited: string[]; // territórios visitados
  quests: QuestState[];
  flags: Record<string, boolean>;
  journal: string[];
  turns: number; // turnos de exploração (relógio de corrupção/pressão)
}

export function newGame(player: PlayerCharacter, startTer: string, startX: number, startY: number, seed: string): GameState {
  return {
    version: SAVE_VERSION,
    seed,
    player,
    pos: { ter: startTer, x: startX, y: startY },
    visited: [startTer],
    quests: [],
    flags: {},
    journal: [`Chegada a ${startTer}.`],
    turns: 0,
  };
}

export function logJournal(s: GameState, entry: string): void {
  s.journal.push(`[t${s.turns}] ${entry}`);
  if (s.journal.length > 200) s.journal = s.journal.slice(-200);
}
