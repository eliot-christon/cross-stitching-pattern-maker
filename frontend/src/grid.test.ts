import { describe, expect, it } from "vitest";

import { gridPixels } from "./grid";
import type { KeyEntry } from "./pattern";

function entry(code: string, rgb: [number, number, number]): KeyEntry {
  return { code, name: `Thread ${code}`, rgb, stitches: 1, skeins: 1 };
}

function cell(pixels: Uint8ClampedArray, index: number): number[] {
  return Array.from(pixels.slice(index * 4, index * 4 + 4));
}

describe("gridPixels", () => {
  it("paints each cell in row order from the key, bare cells transparent", () => {
    const pixels = gridPixels({
      width: 3,
      height: 2,
      grid: [
        [0, 1, null],
        [1, 0, 0],
      ],
      key: [entry("310", [0, 0, 0]), entry("Blanc", [255, 255, 255])],
    });

    expect(pixels.length).toBe(24);
    expect(cell(pixels, 0)).toEqual([0, 0, 0, 255]);
    expect(cell(pixels, 1)).toEqual([255, 255, 255, 255]);
    expect(cell(pixels, 2)).toEqual([0, 0, 0, 0]);
    expect(cell(pixels, 3)).toEqual([255, 255, 255, 255]);
    expect(cell(pixels, 4)).toEqual([0, 0, 0, 255]);
    expect(cell(pixels, 5)).toEqual([0, 0, 0, 255]);
  });

  it("uses the key colour exactly, with no conversion", () => {
    const pixels = gridPixels({
      width: 2,
      height: 2,
      grid: [
        [0, 0],
        [0, 0],
      ],
      key: [entry("X", [10, 20, 30])],
    });

    for (let i = 0; i < 4; i += 1) {
      expect(cell(pixels, i)).toEqual([10, 20, 30, 255]);
    }
  });

  it("handles a 1000x1000 grid with a bare last cell", () => {
    const size = 1000;
    const grid: (number | null)[][] = Array.from({ length: size }, () =>
      Array.from({ length: size }, (): number | null => 0),
    );
    const lastRow = grid[size - 1];
    if (lastRow === undefined) {
      throw new Error("fixture has no last row");
    }
    lastRow[size - 1] = null;

    const pixels = gridPixels({
      width: size,
      height: size,
      grid,
      key: [entry("310", [12, 34, 56])],
    });

    expect(pixels.length).toBe(size * size * 4);
    expect(cell(pixels, 0)).toEqual([12, 34, 56, 255]);
    expect(cell(pixels, size * size - 2)).toEqual([12, 34, 56, 255]);
    expect(cell(pixels, size * size - 1)).toEqual([0, 0, 0, 0]);
  });

  it("returns an empty buffer for an empty grid", () => {
    const pixels = gridPixels({ width: 0, height: 0, grid: [], key: [] });

    expect(pixels.length).toBe(0);
  });
});
