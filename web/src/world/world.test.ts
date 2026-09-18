import { describe, expect, it } from "vitest";
import { DATA } from "../data";
import { moveOnGrid, synthesizeGrid, TILE } from "./grid";
import { loadGame, saveGame, type StorageLike } from "./save";
import { newGame } from "./store";
import { createCharacter } from "../core/character";

function mem(): StorageLike {
  const m = new Map<string, string>();
  return {
    getItem: (k) => m.get(k) ?? null,
    setItem: (k, v) => { m.set(k, v); },
    removeItem: (k) => { m.delete(k); },
  };
}

function gridInputs(ter: string, corrupted: boolean) {
  return {
    territory: DATA.territories.find((t) => t.id === ter)!,
    establishments: DATA.est.filter((e) => e.ter === ter),
    routesFrom: DATA.routes.filter((r) => r.from === ter),
    corrupted,
    corruptZone: ter === "TER-011" ? { cx: 18, cy: 18, r: 5 } : undefined,
  };
}

describe("grid (síntese determinística)", () => {
  it("mesmo input → mesmo mapa", () => {
    const a = synthesizeGrid(gridInputs("TER-011", false));
    const b = synthesizeGrid(gridInputs("TER-011", false));
    expect(a.tiles).toEqual(b.tiles);
    expect(a.pois).toEqual(b.pois);
    expect(a.exits).toEqual(b.exits);
  });
  it("spawn transitável; saídas = rotas (limitadas a 8)", () => {
    const g = synthesizeGrid(gridInputs("TER-011", false));
    expect(g.tiles[g.spawn.y][g.spawn.x]).not.toBe(TILE.BLOCKED);
    const nRoutes = DATA.routes.filter((r) => r.from === "TER-011").length;
    expect(g.exits.length).toBe(Math.min(8, nRoutes));
  });
  it("zona corrompida gera tiles CORRUPT no TER-011", () => {
    const g = synthesizeGrid(gridInputs("TER-011", false));
    const n = g.tiles.flat().filter((t) => t === TILE.CORRUPT).length;
    expect(n).toBeGreaterThan(0);
  });
  it("movimento bloqueia parede e borda", () => {
    const g = synthesizeGrid(gridInputs("TER-001", false));
    const blocked = { x: 0, y: 0, moved: false };
    expect(moveOnGrid(g, 0, 0, -1, 0)).toEqual(blocked);
    // encontra parede adjacente a um livre
    let found = false;
    for (let y = 0; y < g.size && !found; y++) {
      for (let x = 0; x < g.size && !found; x++) {
        if (g.tiles[y][x] !== TILE.BLOCKED && x + 1 < g.size && g.tiles[y][x + 1] === TILE.BLOCKED) {
          expect(moveOnGrid(g, x, y, 1, 0).moved).toBe(false);
          found = true;
        }
      }
    }
    expect(found).toBe(true);
  });
});

describe("save (multi-slot versionado)", () => {
  it("round-trip preserva estado", () => {
    const cls = DATA.classes.find((c) => c.id === "Nativos")!;
    const pc = createCharacter("T", cls, "TER-011", undefined);
    const st = newGame(pc, "TER-011", 5, 5, "seed1");
    const storage = mem();
    saveGame(storage, 2, st);
    const back = loadGame(storage, 2);
    expect(back?.player.name).toBe("T");
    expect(back?.pos).toEqual({ ter: "TER-011", x: 5, y: 5 });
    expect(back?.version).toBe(1);
  });
  it("slot vazio → null; slot inválido → erro", () => {
    expect(loadGame(mem(), 1)).toBeNull();
    expect(() => saveGame(mem(), 9, newGame(createCharacter("T", DATA.classes[0], "TER-011", undefined), "TER-011", 0, 0, "s"))).toThrow();
  });
});
