import { describe, expect, it } from "vitest";

import { LINE_MIN_PX, centreLines, tenCellLines } from "./chartAids";

const PATTERN = { width: 40, height: 25 };

describe("tenCellLines", () => {
  it("draws no line below the threshold and the threshold is 4 px", () => {
    expect(LINE_MIN_PX).toBe(4);
    const window = { firstColumn: 5, firstRow: 0, columns: 30, rows: 25 };
    expect(tenCellLines(window, PATTERN, 3)).toEqual({ columns: [], rows: [] });
  });

  it("draws the lines at exactly the threshold", () => {
    const window = { firstColumn: 5, firstRow: 0, columns: 30, rows: 25 };
    expect(tenCellLines(window, PATTERN, 4)).toEqual({
      columns: [10, 20, 30],
      rows: [0, 10, 20, 25],
    });
  });

  it("gives every multiple of 10 and the bottom and right edges inside the window", () => {
    const window = { firstColumn: 5, firstRow: 0, columns: 30, rows: 25 };
    // Columns 5-34: borders 0 and 40 are outside; rows 0-24: 0 and 25 are the edges.
    expect(tenCellLines(window, PATTERN, 10)).toEqual({
      columns: [10, 20, 30],
      rows: [0, 10, 20, 25],
    });
  });

  it("includes the left edge when the window starts at column 0", () => {
    const window = { firstColumn: 0, firstRow: 0, columns: 15, rows: 25 };
    expect(tenCellLines(window, PATTERN, 10).columns).toEqual([0, 10]);
  });
});

describe("centreLines", () => {
  it("puts an even size on a cell border and an odd one in the middle of a cell", () => {
    expect(centreLines({ width: 40, height: 25 })).toEqual({ column: 20, row: 12.5 });
    expect(centreLines({ width: 41, height: 24 })).toEqual({ column: 20.5, row: 12 });
  });
});
