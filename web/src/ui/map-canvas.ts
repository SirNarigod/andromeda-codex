// Renderizador do mapa em Canvas 2D (grade 24x24). Sem regras aqui — só desenho + input.
import { TILE, type Grid } from "../world/grid";

export const TILE_COLORS: Record<number, string> = {
  [TILE.OPEN]: "#e8e2d4",
  [TILE.BLOCKED]: "#5a5348",
  [TILE.POI]: "#b98a2f",
  [TILE.CORRUPT]: "#5e2a4d",
  [TILE.EXIT]: "#2f6db9",
};

export function drawMap(canvas: HTMLCanvasElement, grid: Grid, px: number, py: number): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const cell = Math.floor(Math.min(canvas.width, canvas.height) / grid.size);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  for (let y = 0; y < grid.size; y++) {
    for (let x = 0; x < grid.size; x++) {
      ctx.fillStyle = TILE_COLORS[grid.tiles[y][x]];
      ctx.fillRect(x * cell, y * cell, cell, cell);
    }
  }
  // jogador
  ctx.fillStyle = "#1d1d1d";
  ctx.beginPath();
  ctx.arc(px * cell + cell / 2, py * cell + cell / 2, cell / 2.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#fdfcfc";
  ctx.font = `${Math.max(8, cell - 4)}px monospace`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("•", px * cell + cell / 2, py * cell + cell / 2);
}

export type MoveDir = "up" | "down" | "left" | "right";

export function attachMovement(onMove: (d: MoveDir) => void): () => void {
  const handler = (e: KeyboardEvent) => {
    const map: Record<string, MoveDir> = {
      ArrowUp: "up", w: "up", W: "up",
      ArrowDown: "down", s: "down", S: "down",
      ArrowLeft: "left", a: "left", A: "left",
      ArrowRight: "right", d: "right", D: "right",
    };
    const dir = map[e.key];
    if (dir) {
      e.preventDefault();
      onMove(dir);
    }
  };
  window.addEventListener("keydown", handler);
  return () => window.removeEventListener("keydown", handler);
}
