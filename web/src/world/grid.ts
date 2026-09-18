// Síntese determinística de grids (RUNTIME_ONLY).
// Seed = id do território; mesmo input → mesmo mapa. Honesto: não é fronteira canônica.
// Tamanho M1: 24x24. Tiles: 0 transitável, 1 bloqueado, 2 POI, 3 corrompido, 4 saída.
import { stableRoll } from "../core/rng";
import type { Est, Route, Territory } from "../data/schemas";

export const GRID_SIZE = 24;

export const TILE = { OPEN: 0, BLOCKED: 1, POI: 2, CORRUPT: 3, EXIT: 4 } as const;
export type Tile = (typeof TILE)[keyof typeof TILE];

export interface GridPoi {
  x: number; y: number; estId: string; name: string;
}

export interface GridExit {
  x: number; y: number; routeId: string; to: string;
}

export interface Grid {
  ter: string;
  size: number;
  tiles: Tile[][];
  pois: GridPoi[];
  exits: GridExit[];
  spawn: { x: number; y: number };
  corrupted: boolean; // território com pressão de corrupção
}

function roll01(seed: string, x: number, y: number): number {
  return stableRoll(seed, "tile", `${x},${y}`);
}

/** Densidade de bloqueio por terreno canônico. */
function blockThreshold(terrain: string): number {
  switch (terrain) {
    case "AQUATICO": return 0.45;
    case "MONTANHA_TEMPESTADE": return 0.4;
    case "VULCANICO": return 0.35;
    case "DESERTICO": return 0.25;
    case "FLORESTA_DOSSEL": return 0.3;
    case "PANTANO_CULTIVADO": return 0.3;
    case "SUBTERRANEO": return 0.35;
    default: return 0.18;
  }
}

export interface GridInputs {
  territory: Territory;
  establishments: Est[];
  routesFrom: Route[];
  corrupted: boolean;
  corruptZone?: { cx: number; cy: number; r: number }; // zona corrompida (ex.: SUB-011-006 no TER-011)
}

export function synthesizeGrid(inp: GridInputs): Grid {
  const size = GRID_SIZE;
  const seed = `grid|${inp.territory.id}`;
  const threshold = blockThreshold(inp.territory.terrain);
  const tiles: Tile[][] = [];
  for (let y = 0; y < size; y++) {
    const row: Tile[] = [];
    for (let x = 0; x < size; x++) {
      const r = roll01(seed, x, y);
      let t: Tile = r < threshold ? TILE.BLOCKED : TILE.OPEN;
      // zona corrompida: círculo determinístico
      if (inp.corruptZone) {
        const d = Math.hypot(x - inp.corruptZone.cx, y - inp.corruptZone.cy);
        if (d <= inp.corruptZone.r && t === TILE.OPEN) t = TILE.CORRUPT;
      } else if (inp.corrupted && t === TILE.OPEN) {
        if (roll01(seed + "|corr", x, y) < 0.25) t = TILE.CORRUPT;
      }
      row.push(t);
    }
    tiles.push(row);
  }

  const free: { x: number; y: number }[] = [];
  for (let y = 1; y < size - 1; y++)
    for (let x = 1; x < size - 1; x++) if (tiles[y][x] === TILE.OPEN) free.push({ x, y });

  const pick = (i: number) => free[Math.floor(roll01(seed + "|pick", i, 0) * free.length)];

  // POIs: estabelecimentos do território (até 6 no M1)
  const pois: GridPoi[] = [];
  for (let i = 0; i < Math.min(6, inp.establishments.length); i++) {
    const spot = pick(i);
    if (!spot) break;
    const e = inp.establishments[i];
    tiles[spot.y][spot.x] = TILE.POI;
    pois.push({ x: spot.x, y: spot.y, estId: e.id, name: e.name });
  }

  // Saídas: uma por rota de saída (borda do mapa)
  const exits: GridExit[] = [];
  inp.routesFrom.slice(0, 8).forEach((r, i) => {
    const edge = i % 4;
    const t = 2 + Math.floor(roll01(seed + "|exit", i, 1) * (size - 4));
    const p = edge === 0 ? { x: t, y: 0 } : edge === 1 ? { x: size - 1, y: t } : edge === 2 ? { x: t, y: size - 1 } : { x: 0, y: t };
    tiles[p.y][p.x] = TILE.EXIT;
    exits.push({ x: p.x, y: p.y, routeId: r.id, to: r.to });
  });

  // Spawn: primeiro tile livre (varredura determinística a partir do centro)
  let spawn = { x: Math.floor(size / 2), y: Math.floor(size / 2) };
  outer: for (let rad = 0; rad < size; rad++) {
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        if (Math.max(Math.abs(x - spawn.x), Math.abs(y - spawn.y)) === rad && tiles[y][x] === TILE.OPEN) {
          spawn = { x, y };
          break outer;
        }
      }
    }
  }

  return { ter: inp.territory.id, size, tiles, pois, exits, spawn, corrupted: inp.corrupted };
}

export function isPassable(t: Tile): boolean {
  return t !== TILE.BLOCKED;
}

export function moveOnGrid(g: Grid, x: number, y: number, dx: number, dy: number): { x: number; y: number; moved: boolean } {
  const nx = x + dx;
  const ny = y + dy;
  if (nx < 0 || ny < 0 || nx >= g.size || ny >= g.size) return { x, y, moved: false };
  if (!isPassable(g.tiles[ny][nx])) return { x, y, moved: false };
  return { x: nx, y: ny, moved: true };
}
