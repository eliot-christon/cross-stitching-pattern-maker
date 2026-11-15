import { describe, expect, it } from "vitest";

import type { KeyEntry, Pattern } from "./pattern";
import { visibleSymbols } from "./symbolView";

type Grid = Pattern["grid"];

function entry(symbol: string): KeyEntry {
  return {
    code: symbol,
    name: `Thread ${symbol}`,
    rgb: [0, 0, 0],
    stitches: 1,
    skeins: 1,
    symbol,
    symbol_ink: "white",
  };
}

function pattern(grid: Grid, symbols: string[], width?: number, height?: number) {
  return {
    width: width ?? grid[0]?.length ?? 0,
    height: height ?? grid.length,
    grid,
    key: symbols.map(entry),
  };
}

function filledGrid(width: number, height: number): Grid {
  return Array.from({ length: height }, () => Array.from({ length: width }, () => 0));
}

describe("visibleSymbols", () => {
  it("gives each cell its key entry's symbol and bare cells none", () => {
    const cells = visibleSymbols(pattern([[0, 1, null]], ["A", "★"]), {
      firstColumn: 0,
      firstRow: 0,
      columns: 3,
      rows: 1,
    });

    expect(cells).toEqual([
      { column: 0, row: 0, symbol: "A" },
      { column: 1, row: 0, symbol: "★" },
      { column: 2, row: 0, symbol: null },
    ]);
  });

  it("uses the response's symbol as given, never one of its own", () => {
    const cells = visibleSymbols(pattern(filledGrid(4, 3), ["§"]), {
      firstColumn: 0,
      firstRow: 0,
      columns: 4,
      rows: 3,
    });

    expect(cells).toHaveLength(12);
    expect(cells.every((cell) => cell.symbol === "§")).toBe(true);
  });

  it("returns exactly the cells in view, each with its own column and row", () => {
    const cells = visibleSymbols(pattern(filledGrid(100, 100), ["A"]), {
      firstColumn: 10,
      firstRow: 5,
      columns: 10,
      rows: 5,
    });

    expect(cells).toHaveLength(50);
    const positions = new Set(cells.map((cell) => `${cell.column},${cell.row}`));
    expect(positions.size).toBe(50);
    for (let row = 5; row <= 9; row++) {
      for (let column = 10; column <= 19; column++) {
        expect(positions.has(`${column},${row}`)).toBe(true);
      }
    }
  });

  it("clips a view reaching past the last column or row to the cells that exist", () => {
    const cells = visibleSymbols(pattern(filledGrid(5, 4), ["A"]), {
      firstColumn: 3,
      firstRow: 2,
      columns: 10,
      rows: 10,
    });

    expect(cells.map((cell) => [cell.column, cell.row])).toEqual([
      [3, 2],
      [4, 2],
      [3, 3],
      [4, 3],
    ]);
  });

  it("returns nothing for a view entirely outside the grid", () => {
    const view = { firstColumn: 50, firstRow: 0, columns: 5, rows: 5 };

    expect(visibleSymbols(pattern(filledGrid(5, 5), ["A"]), view)).toEqual([]);
  });

  it("reads only the rows and columns in view of a 1000 x 1000 grid", () => {
    const view = { firstColumn: 400, firstRow: 600, columns: 30, rows: 20 };
    const inView = (index: number, first: number, count: number) =>
      index >= first && index < first + count;
    const row = new Proxy(
      Array.from({ length: 1000 }, () => 0),
      {
        get(target, property, receiver) {
          const index = typeof property === "string" ? Number(property) : Number.NaN;
          if (Number.isInteger(index) && !inView(index, view.firstColumn, view.columns)) {
            throw new Error(`column ${index} read outside the view`);
          }
          return Reflect.get(target, property, receiver) as unknown;
        },
      },
    );
    const grid = new Proxy(
      Array.from({ length: 1000 }, () => row),
      {
        get(target, property, receiver) {
          const index = typeof property === "string" ? Number(property) : Number.NaN;
          if (Number.isInteger(index) && !inView(index, view.firstRow, view.rows)) {
            throw new Error(`row ${index} read outside the view`);
          }
          return Reflect.get(target, property, receiver) as unknown;
        },
      },
    );

    const cells = visibleSymbols(pattern(grid, ["A"], 1000, 1000), view);

    expect(cells).toHaveLength(600);
  });

  it("refuses a cell pointing at a key entry that does not exist", () => {
    const view = { firstColumn: 0, firstRow: 0, columns: 2, rows: 1 };

    expect(() => visibleSymbols(pattern([[0, 3]], ["A"]), view)).toThrow(/key entry 3/);
  });
});
