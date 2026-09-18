// Saves multi-slot versionados (storage injetável p/ testes).
import { SAVE_VERSION, type GameState } from "./store";

export interface StorageLike {
  getItem(k: string): string | null;
  setItem(k: string, v: string): void;
  removeItem(k: string): void;
}

const PREFIX = "andromeda-m1-save-";
export const MAX_SLOTS = 3;

export function slotKey(slot: number): string {
  return `${PREFIX}${slot}`;
}

export function saveGame(storage: StorageLike, slot: number, state: GameState): void {
  if (slot < 1 || slot > MAX_SLOTS) throw new Error("slot inválido");
  state.version = SAVE_VERSION;
  storage.setItem(slotKey(slot), JSON.stringify(state));
}

export function loadGame(storage: StorageLike, slot: number): GameState | null {
  const raw = storage.getItem(slotKey(slot));
  if (!raw) return null;
  const parsed = JSON.parse(raw) as GameState;
  return migrate(parsed);
}

export function deleteGame(storage: StorageLike, slot: number): void {
  storage.removeItem(slotKey(slot));
}

export function listSlots(storage: StorageLike): (GameState | null)[] {
  return [1, 2, 3].map((s) => {
    try { return loadGame(storage, s); } catch { return null; }
  });
}

/** Migração de versões antigas → atual. M1: só v1 existe; desconhecidas são rejeitadas. */
export function migrate(state: GameState): GameState {
  if (state.version === SAVE_VERSION) return state;
  throw new Error(`save versão ${state.version} sem migração (atual: ${SAVE_VERSION})`);
}

export function browserStorage(): StorageLike {
  return window.localStorage;
}
