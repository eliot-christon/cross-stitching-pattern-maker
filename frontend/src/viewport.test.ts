import { describe, expect, it } from "vitest";

import type { KeyEntry } from "./pattern";
import { visibleSymbols } from "./symbolView";
import {
  MAX_CELL_PX,
  fitViewport,
  maxScale,
  panBy,
  pinchFactor,
  resizeViewer,
  visibleWindow,
  wheelFactor,
  zoomAt,
} from "./viewport";
import type { Point, Size, Viewport } from "./viewport";

/** The pattern position, in cells, that sits under a viewer point. */
function cellUnder(vp: Viewport, point: Point): Point {
  return { x: (point.x - vp.x) / vp.scale, y: (point.y - vp.y) / vp.scale };
}

function expectViewport(actual: Viewport, expected: Viewport) {
  expect(actual.scale).toBeCloseTo(expected.scale, 9);
  expect(actual.x).toBeCloseTo(expected.x, 9);
  expect(actual.y).toBeCloseTo(expected.y, 9);
}

function expectFinite(vp: Viewport) {
  expect(Number.isFinite(vp.scale)).toBe(true);
  expect(Number.isFinite(vp.x)).toBe(true);
  expect(Number.isFinite(vp.y)).toBe(true);
}

const SQUARE_100: Size = { width: 100, height: 100 };
const VIEWER_400: Size = { width: 400, height: 400 };

describe("fitViewport", () => {
  it("fits a wide pattern by width and centres it vertically", () => {
    const pattern = { width: 100, height: 50 };
    const vp = fitViewport(pattern, VIEWER_400);

    expectViewport(vp, { scale: 4, x: 0, y: 100 });
    expect(visibleWindow(vp, pattern, VIEWER_400)).toEqual({
      firstColumn: 0,
      firstRow: 0,
      columns: 100,
      rows: 50,
    });
  });

  it("fits a small pattern by height and centres it horizontally", () => {
    const pattern = { width: 10, height: 10 };
    const viewer = { width: 1000, height: 800 };
    const vp = fitViewport(pattern, viewer);

    expectViewport(vp, { scale: 80, x: 100, y: 0 });
    expect(maxScale(pattern, viewer)).toBeCloseTo(80, 9);
    expectViewport(zoomAt(vp, pattern, viewer, 2, { x: 500, y: 400 }), vp);
  });

  it("gives one cell the whole viewer for a 1 x 1 pattern", () => {
    const pattern = { width: 1, height: 1 };
    const vp = fitViewport(pattern, VIEWER_400);

    expectViewport(vp, { scale: 400, x: 0, y: 0 });
    expect(visibleWindow(vp, pattern, VIEWER_400)).toEqual({
      firstColumn: 0,
      firstRow: 0,
      columns: 1,
      rows: 1,
    });
  });
});

describe("maxScale", () => {
  it("is the named constant of 64 px per cell when the fit scale is smaller", () => {
    expect(MAX_CELL_PX).toBe(64);
    expect(maxScale(SQUARE_100, VIEWER_400)).toBe(MAX_CELL_PX);
  });
});

describe("zoomAt", () => {
  it("doubles the scale and keeps the cell under the point under it", () => {
    const point = { x: 130, y: 70 };
    const start = fitViewport(SQUARE_100, VIEWER_400);
    const before = cellUnder(start, point);

    const zoomed = zoomAt(start, SQUARE_100, VIEWER_400, 2, point);
    const after = cellUnder(zoomed, point);

    expect(zoomed.scale).toBeCloseTo(8, 9);
    expect(after.x).toBeCloseTo(before.x, 9);
    expect(after.y).toBeCloseTo(before.y, 9);
  });

  it("stops at the maximum scale going in and at the fit scale, centred, going out", () => {
    const start = fitViewport(SQUARE_100, VIEWER_400);
    const point = { x: 130, y: 70 };

    const maxed = zoomAt(start, SQUARE_100, VIEWER_400, 1000, point);
    expect(maxed.scale).toBeCloseTo(64, 9);

    const back = zoomAt(maxed, SQUARE_100, VIEWER_400, 1 / 1000, point);
    expectViewport(back, { scale: 4, x: 0, y: 0 });
  });

  it("returns to the starting state when zoomed in then out by the same factor", () => {
    const start: Viewport = { scale: 10, x: -200, y: -300 };
    const point = { x: 200, y: 200 };

    const zoomed = zoomAt(start, SQUARE_100, VIEWER_400, 1.5, point);
    expect(zoomed.scale).toBeCloseTo(15, 9);
    const back = zoomAt(zoomed, SQUARE_100, VIEWER_400, 1 / 1.5, point);

    expectViewport(back, start);
  });
});

describe("wheelFactor", () => {
  it("zooms in for a negative delta, out for a positive one, and not at all for zero", () => {
    expect(wheelFactor(-100)).toBeGreaterThan(1);
    expect(wheelFactor(100)).toBeLessThan(1);
    expect(wheelFactor(0)).toBe(1);
  });

  it("cancels equal and opposite deltas", () => {
    expect(wheelFactor(-100) * wheelFactor(100)).toBeCloseTo(1, 12);
  });

  it("scales by f then 1/f for deltaY -100 then +100, back to the start", () => {
    const start: Viewport = { scale: 10, x: -200, y: -300 };
    const point = { x: 150, y: 250 };
    const f = wheelFactor(-100);

    const zoomed = zoomAt(start, SQUARE_100, VIEWER_400, wheelFactor(-100), point);
    expect(zoomed.scale).toBeCloseTo(10 * f, 9);
    const back = zoomAt(zoomed, SQUARE_100, VIEWER_400, wheelFactor(100), point);

    expectViewport(back, start);
  });
});

describe("pinchFactor", () => {
  it("is the ratio of the new distance to the old one", () => {
    expect(pinchFactor(100, 200)).toBeCloseTo(2, 12);
    expect(pinchFactor(200, 100)).toBeCloseTo(0.5, 12);
  });

  it("is 1 when the fingers started at the same point", () => {
    expect(pinchFactor(0, 50)).toBe(1);
  });

  it("doubles the scale and keeps the cell under the midpoint when fingers spread", () => {
    const start: Viewport = { scale: 10, x: -200, y: -200 };
    const midpoint = { x: 200, y: 200 };
    const before = cellUnder(start, midpoint);

    const pinched = zoomAt(start, SQUARE_100, VIEWER_400, pinchFactor(100, 200), midpoint);
    const after = cellUnder(pinched, midpoint);

    expect(pinched.scale).toBeCloseTo(20, 9);
    expect(after.x).toBeCloseTo(before.x, 9);
    expect(after.y).toBeCloseTo(before.y, 9);
  });
});

describe("panBy", () => {
  const zoomed: Viewport = { scale: 20, x: -500, y: -500 };

  it("stops with the pattern's top-left corner at the viewer's top-left", () => {
    const vp = panBy(zoomed, SQUARE_100, VIEWER_400, 1e6, 1e6);

    expectViewport(vp, { scale: 20, x: 0, y: 0 });
    const window = visibleWindow(vp, SQUARE_100, VIEWER_400);
    expect(window.firstColumn).toBe(0);
    expect(window.firstRow).toBe(0);
  });

  it("stops with the pattern's bottom-right corner at the viewer's bottom-right", () => {
    const vp = panBy(zoomed, SQUARE_100, VIEWER_400, -1e6, -1e6);

    expectViewport(vp, { scale: 20, x: 400 - 2000, y: 400 - 2000 });
    const window = visibleWindow(vp, SQUARE_100, VIEWER_400);
    expect(window.firstColumn + window.columns - 1).toBe(99);
    expect(window.firstRow + window.rows - 1).toBe(99);
  });

  it("moves freely inside the bounds", () => {
    const vp = panBy(zoomed, SQUARE_100, VIEWER_400, 30, -40);

    expectViewport(vp, { scale: 20, x: -470, y: -540 });
  });

  it("keeps an axis centred where the pattern is smaller than the viewer", () => {
    const pattern = { width: 100, height: 10 };
    const start: Viewport = { scale: 20, x: -100, y: 100 };

    const vp = panBy(start, pattern, VIEWER_400, 0, 300);

    expect(vp.y).toBeCloseTo(100, 9);
    expect(vp.x).toBeCloseTo(-100, 9);
  });
});

describe("visibleWindow", () => {
  it("counts partly visible cells at each edge", () => {
    const pattern = { width: 1000, height: 1000 };
    const viewer = { width: 400, height: 300 };
    const vp: Viewport = { scale: 16, x: -1608, y: -808 };

    expect(visibleWindow(vp, pattern, viewer)).toEqual({
      firstColumn: 100,
      firstRow: 50,
      columns: 26,
      rows: 20,
    });
  });

  it("shows the whole grid and never reaches past the last column or row at fit", () => {
    const pattern = { width: 1000, height: 1000 };
    const viewer = { width: 500, height: 500 };
    const vp = fitViewport(pattern, viewer);

    expect(visibleWindow(vp, pattern, viewer)).toEqual({
      firstColumn: 0,
      firstRow: 0,
      columns: 1000,
      rows: 1000,
    });
  });

  it("gives visibleSymbols a view it can read without leaving the grid", () => {
    const pattern = { width: 1000, height: 1000 };
    const viewer = { width: 500, height: 500 };
    const view = visibleWindow(fitViewport(pattern, viewer), pattern, viewer);
    const entry: KeyEntry = {
      code: "A",
      name: "Thread A",
      rgb: [0, 0, 0],
      stitches: 1,
      skeins: 1,
      symbol: "A", symbol_ink: "white",
    };
    const grid = Array.from({ length: 1000 }, () => Array.from({ length: 1000 }, () => 0));

    const cells = visibleSymbols({ ...pattern, grid, key: [entry] }, view);

    expect(cells).toHaveLength(1_000_000);
    expect(cells[cells.length - 1]).toEqual({ column: 999, row: 999, symbol: "A" });
  });
});

describe("resizeViewer", () => {
  it("keeps the cell at the old centre at the new centre and the scale", () => {
    const start: Viewport = { scale: 20, x: -600, y: -600 };
    const from = VIEWER_400;
    const to = { width: 800, height: 400 };
    const before = cellUnder(start, { x: 200, y: 200 });

    const vp = resizeViewer(start, SQUARE_100, from, to);
    const after = cellUnder(vp, { x: 400, y: 200 });

    expect(vp.scale).toBeCloseTo(20, 9);
    expect(after.x).toBeCloseTo(before.x, 9);
    expect(after.y).toBeCloseTo(before.y, 9);
  });

  it("takes the new fit scale, centred, when it is larger than the old scale", () => {
    const start = fitViewport(SQUARE_100, VIEWER_400);

    const vp = resizeViewer(start, SQUARE_100, VIEWER_400, { width: 800, height: 800 });

    expectViewport(vp, { scale: 8, x: 0, y: 0 });
  });
});

describe("a 0 x 0 viewer", () => {
  const empty: Size = { width: 0, height: 0 };
  const pattern = { width: 100, height: 50 };

  it("gives finite numbers and an empty window from every function", () => {
    const fit = fitViewport(pattern, empty);
    expectFinite(fit);
    expect(Number.isFinite(maxScale(pattern, empty))).toBe(true);
    expectFinite(zoomAt(fit, pattern, empty, 2, { x: 0, y: 0 }));
    expectFinite(panBy(fit, pattern, empty, 10, -10));
    expectFinite(resizeViewer(fit, pattern, empty, VIEWER_400));
    expectFinite(resizeViewer(fitViewport(pattern, VIEWER_400), pattern, VIEWER_400, empty));

    const window = visibleWindow(fit, pattern, empty);
    expect(window.columns === 0 || window.rows === 0).toBe(true);
    expect(Number.isFinite(window.firstColumn)).toBe(true);
    expect(Number.isFinite(window.firstRow)).toBe(true);
  });
});

describe("edge cases found in review", () => {
  const NONE = { firstColumn: 0, firstRow: 0, columns: 0, rows: 0 };

  it("gives a finite factor for a huge wheel delta, which zooms all the way in", () => {
    const factor = wheelFactor(-1e6);
    expect(Number.isFinite(factor)).toBe(true);
    expect(Number.isFinite(wheelFactor(1e6))).toBe(true);

    const vp = zoomAt(fitViewport(SQUARE_100, VIEWER_400), SQUARE_100, VIEWER_400, factor, {
      x: 200,
      y: 200,
    });

    expect(vp.scale).toBe(MAX_CELL_PX);
  });

  it("keeps the window empty after zoom, pan and resize in a 0 x 0 viewer", () => {
    const empty: Size = { width: 0, height: 0 };
    const fit = fitViewport(SQUARE_100, empty);
    const viewports = [
      fit,
      zoomAt(fit, SQUARE_100, empty, 2, { x: 0, y: 0 }),
      panBy(fit, SQUARE_100, empty, 10, -10),
      resizeViewer(fitViewport(SQUARE_100, VIEWER_400), SQUARE_100, VIEWER_400, empty),
    ];

    for (const vp of viewports) {
      expect(visibleWindow(vp, SQUARE_100, empty)).toEqual(NONE);
    }
  });

  it("gives finite numbers and an empty window for a 0 x 0 pattern", () => {
    const pattern: Size = { width: 0, height: 0 };
    const fit = fitViewport(pattern, VIEWER_400);

    expectFinite(fit);
    expectFinite(zoomAt(fit, pattern, VIEWER_400, 2, { x: 10, y: 10 }));
    expectFinite(panBy(fit, pattern, VIEWER_400, 5, 5));
    expect(visibleWindow(fit, pattern, VIEWER_400)).toEqual(NONE);
  });

  it("clamps a resize whose old centre can no longer be centred", () => {
    // At 20 px per cell, scrolled to the bottom-right corner of a 100 x 100 pattern.
    const corner = panBy(
      { scale: 20, x: 0, y: 0 },
      SQUARE_100,
      VIEWER_400,
      -1e6,
      -1e6,
    );

    const vp = resizeViewer(corner, SQUARE_100, VIEWER_400, { width: 800, height: 800 });

    // The old centre (cell 90, 90) cannot reach the new centre: the corner stays put.
    expectViewport(vp, { scale: 20, x: 800 - 2000, y: 800 - 2000 });
  });
});
