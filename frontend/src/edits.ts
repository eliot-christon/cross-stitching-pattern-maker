/**
 * Where a hand edit lands, for display only: the page draws strokes and rectangles at once
 * while the API applies them. The API's `edit_pattern` is what counts; these follow its
 * rules exactly so the drawing and the result agree. A fill is connectivity, which stays
 * in the API: nothing here draws it.
 */
import type { Cell, Change } from "./api";

/**
 * The cells of the straight 8-connected lines joining successive `points`, each included:
 * a line of n = max(|dx|, |dy|) steps moves one cell per step along its longer axis and
 * rounds the other, halves up, as `floor((2 i d + n) / (2 n))`.
 */
export function lineCells(points: readonly Cell[]): Cell[] {
  const cells: Cell[] = [];
  points.forEach(([x0, y0], index) => {
    const next = points[index + 1];
    if (next === undefined) {
      cells.push([x0, y0]);
      return;
    }
    const dx = next[0] - x0;
    const dy = next[1] - y0;
    const steps = Math.max(Math.abs(dx), Math.abs(dy));
    for (let i = 0; i < steps; i += 1) {
      cells.push([
        x0 + Math.floor((2 * i * dx + steps) / (2 * steps)),
        y0 + Math.floor((2 * i * dy + steps) / (2 * steps)),
      ]);
    }
  });
  return cells;
}

/** The cells a stroke covers on a grid of `size`: an odd `brush` square on each line cell. */
export function strokeCells(points: readonly Cell[], brush: number, size: Cell): Cell[] {
  const reach = Math.floor(brush / 2);
  const seen = new Set<number>();
  const cells: Cell[] = [];
  for (const [x, y] of lineCells(points)) {
    for (let row = y - reach; row <= y + reach; row += 1) {
      for (let column = x - reach; column <= x + reach; column += 1) {
        const key = row * size[0] + column;
        if (column >= 0 && column < size[0] && row >= 0 && row < size[1] && !seen.has(key)) {
          seen.add(key);
          cells.push([column, row]);
        }
      }
    }
  }
  return cells;
}

/** The cells of the box with corners `from` and `to` (both included, any order), clipped. */
export function rectCells(from: Cell, to: Cell, size: Cell): Cell[] {
  const cells: Cell[] = [];
  const top = Math.max(0, Math.min(from[1], to[1]));
  const bottom = Math.min(size[1] - 1, Math.max(from[1], to[1]));
  const left = Math.max(0, Math.min(from[0], to[0]));
  const right = Math.min(size[0] - 1, Math.max(from[0], to[0]));
  for (let row = top; row <= bottom; row += 1) {
    for (let column = left; column <= right; column += 1) {
      cells.push([column, row]);
    }
  }
  return cells;
}

/** The cells a change is drawn on in advance: a stroke's or a rectangle's; none otherwise. */
export function pendingCells(change: Change): Cell[] {
  switch (change.op) {
    case "stroke":
      return strokeCells(change.points, change.brush, change.grid);
    case "rect":
      return rectCells(change.from, change.to, change.grid);
    default:
      return [];
  }
}
