/**
 * Dashboard grid rules, mirroring the server's clamp (API.md §4.3): x 1..12, w 3..12, h 1..6, x + w - 1 <= 12,
 * y >= 1. Widgets never overlap: whatever a moved or resized widget lands on is pushed down below it.
 */
export const COLS = 12;

export interface Box {
  id: string;
  grid_x: number;
  grid_y: number;
  grid_w: number;
  grid_h: number;
}

const clampInt = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(Math.round(v), hi));

export function clampBox<T extends Box>(b: T): T {
  const grid_w = clampInt(b.grid_w, 3, COLS);
  let grid_x = clampInt(b.grid_x, 1, COLS);
  if (grid_x + grid_w - 1 > COLS) grid_x = COLS - grid_w + 1;
  return { ...b, grid_w, grid_x, grid_h: clampInt(b.grid_h, 1, 6), grid_y: Math.max(1, Math.round(b.grid_y)) };
}

export function overlaps(a: Box, b: Box): boolean {
  return (
    a.grid_x < b.grid_x + b.grid_w &&
    b.grid_x < a.grid_x + a.grid_w &&
    a.grid_y < b.grid_y + b.grid_h &&
    b.grid_y < a.grid_y + a.grid_h
  );
}

/** Place `moved` (already clamped) and push any widget it overlaps downward, cascading, until none overlap. */
export function settle<T extends Box>(boxes: T[], movedId: string): T[] {
  const out = boxes.map((b) => ({ ...b }));
  const fixed: T[] = out.filter((b) => b.id === movedId);
  const rest = out.filter((b) => b.id !== movedId).sort((a, b) => a.grid_y - b.grid_y || a.grid_x - b.grid_x);
  for (const b of rest) {
    let hit = fixed.find((f) => overlaps(f, b));
    while (hit) {
      b.grid_y = hit.grid_y + hit.grid_h;
      hit = fixed.find((f) => overlaps(f, b));
    }
    fixed.push(b);
  }
  return out;
}

/** First row below every existing widget: where a newly added widget goes. */
export function nextFreeRow(boxes: Box[]): number {
  return boxes.reduce((y, b) => Math.max(y, b.grid_y + b.grid_h), 1);
}
