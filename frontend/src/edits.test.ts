import { describe, expect, it } from "vitest";

import type { Cell } from "./api";
import { lineCells, pendingCells, rectCells, strokeCells } from "./edits";

/** Cells as "x,y" strings, sorted, to compare sets. */
function keys(cells: readonly Cell[]): string[] {
  return cells.map(([x, y]) => `${x},${y}`).sort();
}

function eightConnected(cells: readonly Cell[]): boolean {
  return cells.every((cell, i) => {
    const next = cells[i + 1];
    return next === undefined || Math.max(Math.abs(next[0] - cell[0]), Math.abs(next[1] - cell[1])) === 1;
  });
}

describe("lineCells, as the API's edit_pattern draws a stroke", () => {
  it("draws a row from (0, 0) to (4, 0) as its 5 cells", () => {
    expect(lineCells([[0, 0], [4, 0]])).toEqual([[0, 0], [1, 0], [2, 0], [3, 0], [4, 0]]);
  });

  it("draws a diagonal from (0, 0) to (3, 3) as its 4 cells", () => {
    expect(lineCells([[0, 0], [3, 3]])).toEqual([[0, 0], [1, 1], [2, 2], [3, 3]]);
  });

  it("draws (0, 0) to (7, 3) as 8 cells, 8-connected, rows as the API rounds them", () => {
    const cells = lineCells([[0, 0], [7, 3]]);
    expect(cells).toHaveLength(8);
    expect(eightConnected(cells)).toBe(true);
    expect(cells.map(([, y]) => y)).toEqual([0, 0, 1, 1, 2, 2, 3, 3]);
    expect(lineCells([[7, 3], [0, 0]]).map(([, y]) => y)).toEqual([3, 3, 2, 2, 1, 1, 0, 0]);
  });

  it("joins successive points with the joint once, and keeps a single point", () => {
    expect(lineCells([[0, 0], [2, 0], [2, 2]])).toEqual([[0, 0], [1, 0], [2, 0], [2, 1], [2, 2]]);
    expect(lineCells([[3, 4]])).toEqual([[3, 4]]);
  });
});

describe("strokeCells", () => {
  it("stamps a brush 3 at (0, 0) of a 3 x 3 grid on the 4 cells in reach", () => {
    expect(keys(strokeCells([[0, 0]], 3, [3, 3]))).toEqual(keys([[0, 0], [1, 0], [0, 1], [1, 1]]));
  });

  it("covers the whole 3 x 3 grid with a brush 3 at its centre, each cell once", () => {
    expect(strokeCells([[1, 1]], 3, [3, 3])).toHaveLength(9);
  });

  it("clips a line from off the grid", () => {
    expect(keys(strokeCells([[-2, 0], [2, 0]], 1, [3, 1]))).toEqual(keys([[0, 0], [1, 0], [2, 0]]));
  });
});

describe("rectCells", () => {
  it("covers the same 9 cells whatever the corners' order", () => {
    const expected = keys(rectCells([1, 0], [3, 2], [5, 5]));
    expect(expected).toHaveLength(9);
    expect(keys(rectCells([3, 2], [1, 0], [5, 5]))).toEqual(expected);
  });

  it("is clipped to the grid", () => {
    expect(keys(rectCells([3, 2], [1, 0], [3, 2]))).toEqual(keys([[1, 0], [2, 0], [1, 1], [2, 1]]));
    expect(rectCells([5, 5], [9, 9], [3, 3])).toEqual([]);
  });
});

describe("pendingCells", () => {
  it("draws strokes and rectangles, and nothing for a fill or a replacement", () => {
    const black = { code: "310", name: "Black", rgb: [0, 0, 0] as [number, number, number] };
    expect(pendingCells({ op: "stroke", thread: black, brush: 1, grid: [4, 4], points: [[0, 0], [1, 0]] })).toHaveLength(2);
    expect(pendingCells({ op: "rect", thread: null, grid: [4, 4], from: [0, 0], to: [1, 1] })).toHaveLength(4);
    expect(pendingCells({ op: "fill", thread: black, grid: [4, 4], at: [0, 0] })).toEqual([]);
    expect(pendingCells({ op: "replace", from: black, to: null })).toEqual([]);
  });
});
