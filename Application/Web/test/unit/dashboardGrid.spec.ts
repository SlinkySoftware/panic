/** Grid clamping matches the server (API.md §4.3) and edits never leave widgets overlapping. */
import { describe, expect, it } from 'vitest';
import { clampBox, nextFreeRow, overlaps, settle, type Box } from '@/components/dashboard/grid';

const box = (id: string, grid_x: number, grid_y: number, grid_w: number, grid_h: number): Box => ({
  id,
  grid_x,
  grid_y,
  grid_w,
  grid_h,
});

describe('clampBox', () => {
  it('clamps width 3..12, height 1..6, x 1..12 and y >= 1', () => {
    expect(clampBox(box('a', 0, 0, 1, 9))).toMatchObject({ grid_x: 1, grid_y: 1, grid_w: 3, grid_h: 6 });
    expect(clampBox(box('a', 20, 3, 40, 0))).toMatchObject({ grid_x: 1, grid_w: 12, grid_h: 1 });
  });

  it('pulls x left so the widget ends at column 12', () => {
    expect(clampBox(box('a', 11, 1, 4, 1))).toMatchObject({ grid_x: 9, grid_w: 4 });
  });
});

describe('settle', () => {
  it('pushes an overlapped widget below the moved one, cascading', () => {
    const out = settle([box('a', 1, 1, 6, 2), box('b', 1, 3, 6, 1), box('m', 1, 1, 12, 1)], 'm');
    const by = Object.fromEntries(out.map((b) => [b.id, b]));
    expect(by.m).toMatchObject({ grid_y: 1 });
    expect(by.a).toMatchObject({ grid_y: 2 });
    expect(by.b).toMatchObject({ grid_y: 4 });
    for (const x of out) for (const y of out) if (x !== y) expect(overlaps(x, y)).toBe(false);
  });

  it('leaves non-overlapping widgets alone', () => {
    const out = settle([box('a', 7, 1, 6, 2), box('m', 1, 1, 6, 2)], 'm');
    expect(out.find((b) => b.id === 'a')).toMatchObject({ grid_x: 7, grid_y: 1 });
  });
});

it('nextFreeRow is the row under the lowest widget', () => {
  expect(nextFreeRow([])).toBe(1);
  expect(nextFreeRow([box('a', 1, 2, 4, 3), box('b', 5, 1, 4, 1)])).toBe(5);
});
