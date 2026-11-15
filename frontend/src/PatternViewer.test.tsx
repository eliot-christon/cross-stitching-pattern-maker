import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { gridPixels } from "./grid";
import type { KeyEntry, Pattern } from "./pattern";
import { PatternViewer } from "./PatternViewer";

const KEY: KeyEntry[] = [
  { code: "321", name: "Red", rgb: [199, 43, 59], stitches: 1, skeins: 1, symbol: "Z", symbol_ink: "white" },
  { code: "310", name: "Black", rgb: [0, 0, 0], stitches: 1, skeins: 1, symbol: "A", symbol_ink: "white" },
];

function makePattern(width: number, height: number, overrides: Partial<Pattern> = {}): Pattern {
  const grid = Array.from({ length: height }, (_, row) =>
    Array.from({ length: width }, (_, column) => (row + column) % 2),
  );
  return {
    width,
    height,
    fabric_count: 14,
    grid,
    key: KEY,
    total_stitches: width * height,
    finished_size: { width_in: 1, height_in: 1, width_cm: 2.54, height_cm: 2.54 },
    isolated_stitches: { before: 0, after: 0 },
    converted: null,
    ignored_replacements: [],
    ...overrides,
  };
}

/** What every 2D context was asked to do: images put, texts (with their fill), fills, strokes. */
interface Recording {
  images: Uint8ClampedArray[];
  texts: string[];
  inks: unknown[];
  fills: unknown[];
  strokes: unknown[];
  /** For each stroke, the points its path moved to. */
  paths: { style: unknown; moves: [number, number][] }[];
}

/** A 2D context on every canvas that records images and texts and ignores the rest. */
function stubCanvas(): Recording {
  const recording: Recording = {
    images: [],
    texts: [],
    inks: [],
    fills: [],
    strokes: [],
    paths: [],
  };
  let moves: [number, number][] = [];
  vi.stubGlobal(
    "ImageData",
    class {
      constructor(
        public data: Uint8ClampedArray,
        public width: number,
        public height: number,
      ) {}
    },
  );
  const state: Record<string | symbol, unknown> = { fillStyle: "", strokeStyle: "" };
  const context = new Proxy(
    {
      putImageData: (image: { data: Uint8ClampedArray }) => {
        recording.images.push(image.data);
      },
      fillText: (text: string) => {
        recording.texts.push(text);
        recording.inks.push(state.fillStyle);
      },
      fillRect: () => {
        recording.fills.push(state.fillStyle);
      },
      beginPath: () => {
        moves = [];
      },
      moveTo: (x: number, y: number) => {
        moves.push([x, y]);
      },
      stroke: () => {
        recording.strokes.push(state.strokeStyle);
        recording.paths.push({ style: state.strokeStyle, moves });
      },
      createPattern: () => null,
    } as Record<string | symbol, unknown>,
    {
      get: (target, prop) =>
        prop in state ? state[prop] : prop in target ? target[prop] : () => undefined,
      set: (_target, prop, value) => {
        state[prop] = value;
        return true;
      },
    },
  );
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
    (() => context) as unknown as HTMLCanvasElement["getContext"],
  );
  return recording;
}

/** Every element measures 160 x 160, so the viewer has a size in jsdom. */
function stubSize(px: number) {
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(px);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(px);
}

function button(name: string): HTMLElement {
  return screen.getByRole("button", { name });
}

beforeEach(() => {
  stubSize(160);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("PatternViewer", () => {
  it("shows one canvas named after the mode and the pattern size", () => {
    render(<PatternViewer pattern={makePattern(4, 3)} />);

    expect(screen.getAllByRole("img")).toHaveLength(1);
    expect(screen.getByRole("img")).toHaveAccessibleName("Pattern preview, 4 x 3 stitches");

    fireEvent.click(screen.getByRole("radio", { name: "Symbols" }));

    expect(screen.getByRole("img")).toHaveAccessibleName("Pattern symbols, 4 x 3 stitches");
  });

  it("disables Zoom out and Fit at fit, and the + key zooms in like the button", () => {
    render(<PatternViewer pattern={makePattern(4, 4)} />);

    expect(button("Zoom out")).toBeDisabled();
    expect(button("Fit")).toBeDisabled();

    fireEvent.click(button("Zoom in"));
    expect(button("Zoom out")).toBeEnabled();
    expect(button("Fit")).toBeEnabled();

    fireEvent.click(button("Fit"));
    expect(button("Zoom out")).toBeDisabled();
    expect(button("Fit")).toBeDisabled();

    fireEvent.keyDown(screen.getByRole("group", { name: /pattern viewer/i }), { key: "+" });
    expect(button("Zoom out")).toBeEnabled();
  });

  it("draws each cell's symbol at a readable size, and none on bare fabric", () => {
    const recording = stubCanvas();
    const pattern = makePattern(4, 4);
    pattern.grid = pattern.grid.map((row, r) => row.map((cell, c) => (r === 0 && c === 0 ? null : cell)));
    render(<PatternViewer pattern={pattern} />);

    fireEvent.click(screen.getByRole("radio", { name: "Symbols" }));

    // 160 px over 4 cells: 40 px per cell, readable. One cell is bare.
    expect(recording.texts).toHaveLength(15);
    const expected = pattern.grid
      .flat()
      .filter((cell): cell is number => cell !== null)
      .map((cell) => KEY[cell]?.symbol);
    expect(recording.texts).toEqual(expected);
  });

  it("draws no symbol at fit on a 1000 x 1000 pattern, and only the window once zoomed in", () => {
    const recording = stubCanvas();
    render(<PatternViewer pattern={makePattern(1000, 1000)} />);
    fireEvent.click(screen.getByRole("radio", { name: "Symbols" }));

    expect(recording.texts).toHaveLength(0);
    expect(screen.getByText(/zoom in to read the symbols/i)).toBeInTheDocument();

    // 0.16 px per cell at fit; 1.25^20 brings it past 12 px.
    for (let press = 0; press < 20; press += 1) {
      recording.texts.length = 0;
      fireEvent.click(button("Zoom in"));
    }

    expect(recording.texts.length).toBeGreaterThan(0);
    expect(recording.texts.length).toBeLessThan(2000);
    expect(screen.queryByText(/zoom in to read the symbols/i)).not.toBeInTheDocument();
  });

  it("builds the colour image once for a pattern shown again", () => {
    const recording = stubCanvas();
    const pattern = makePattern(3, 2);

    const { rerender } = render(<PatternViewer pattern={pattern} />);
    rerender(<PatternViewer pattern={pattern} />);

    expect(recording.images.map((data) => Array.from(data))).toEqual([
      Array.from(gridPixels(pattern)),
    ]);
  });

  it("keeps the zoom for a new pattern of the same size, and refits for another size", () => {
    const { rerender } = render(<PatternViewer pattern={makePattern(10, 10)} />);
    fireEvent.click(button("Zoom in"));

    rerender(<PatternViewer pattern={makePattern(10, 10)} />);
    expect(button("Zoom out")).toBeEnabled();

    rerender(<PatternViewer pattern={makePattern(12, 10)} />);
    expect(button("Zoom out")).toBeDisabled();
  });

  it("switches between the pattern after and before cleanup in Colours", () => {
    const recording = stubCanvas();
    const converted = {
      grid: [[1, 1, null]],
      key: KEY,
      total_stitches: 2,
    };
    const pattern = makePattern(3, 1, { grid: [[0, 1, null]], converted });
    render(<PatternViewer pattern={pattern} />);

    expect(screen.getByRole("radio", { name: "After cleanup" })).toBeChecked();
    expect(screen.getByRole("img")).toHaveAccessibleName("After cleanup, 3 x 1 stitches");
    expect(Array.from(recording.images.at(-1) ?? [])).toEqual(Array.from(gridPixels(pattern)));

    fireEvent.click(screen.getByRole("radio", { name: "Before cleanup" }));

    expect(screen.getByRole("img")).toHaveAccessibleName("Before cleanup, 3 x 1 stitches");
    const before = gridPixels({ width: 3, height: 1, grid: converted.grid, key: KEY });
    expect(Array.from(recording.images.at(-1) ?? [])).toEqual(Array.from(before));

    fireEvent.click(screen.getByRole("radio", { name: "Symbols" }));

    expect(screen.queryByRole("radio", { name: "Before cleanup" })).not.toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAccessibleName("Pattern symbols, 3 x 1 stitches");
  });

  it("offers no cleanup switch without the pattern before cleanup", () => {
    render(<PatternViewer pattern={makePattern(3, 1)} />);

    expect(screen.queryByRole("radio", { name: "Before cleanup" })).not.toBeInTheDocument();
  });

  it("adds no status or alert to the page", () => {
    render(<PatternViewer pattern={makePattern(1000, 1000)} />);
    fireEvent.click(screen.getByRole("radio", { name: "Symbols" }));

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("offers three modes, Colours first and checked", () => {
    render(<PatternViewer pattern={makePattern(4, 4)} />);

    const modes = ["Colours", "Symbols", "Symbols on colours"].map((name) =>
      screen.getByRole("radio", { name }),
    );
    expect(modes.map((radio) => (radio as HTMLInputElement).checked)).toEqual([
      true,
      false,
      false,
    ]);
  });

  it("fills each cell with its thread and draws its symbol in the entry's ink", () => {
    const recording = stubCanvas();
    const key: KeyEntry[] = [
      { code: "310", name: "Black", rgb: [0, 0, 0], stitches: 8, skeins: 1, symbol: "B", symbol_ink: "white" },
      { code: "Blanc", name: "White", rgb: [252, 251, 248], stitches: 7, skeins: 1, symbol: "W", symbol_ink: "black" },
    ];
    const pattern = makePattern(4, 4, { key });
    pattern.grid = pattern.grid.map((row, r) => row.map((cell, c) => (r === 3 && c === 3 ? null : cell)));
    render(<PatternViewer pattern={pattern} />);
    recording.fills.length = 0;

    fireEvent.click(screen.getByRole("radio", { name: "Symbols on colours" }));

    expect(screen.getByRole("img")).toHaveAccessibleName("Pattern symbols on colours, 4 x 4 stitches");
    expect(recording.texts).toHaveLength(15);
    recording.texts.forEach((text, i) => {
      expect(recording.inks[i]).toBe(text === "B" ? "#ffffff" : "#000000");
    });
    // (row + column) even is black: 8 such cells, one of them bare; odd is white: 8.
    const count = (fill: string) => recording.fills.filter((f) => f === fill).length;
    expect(count("rgb(0 0 0)")).toBe(7);
    expect(count("rgb(252 251 248)")).toBe(8);
  });

  it("draws red centre lines only once asked, in every mode, and keeps them for a new pattern", () => {
    const recording = stubCanvas();
    const { rerender } = render(<PatternViewer pattern={makePattern(4, 4)} />);
    const red = () => recording.strokes.filter((colour) => colour === "#d62828").length;

    expect(screen.getByRole("checkbox", { name: "Centre lines" })).not.toBeChecked();
    expect(red()).toBe(0);

    fireEvent.click(screen.getByRole("checkbox", { name: "Centre lines" }));
    expect(red()).toBe(1);
    // 4 x 4 at 40 px per cell fills the 160 px viewer: the centre is at 80 px both ways.
    const centre = recording.paths.find((path) => path.style === "#d62828");
    expect(centre?.moves).toEqual([
      [80, 0],
      [0, 80],
    ]);
    for (const name of ["Symbols", "Symbols on colours"]) {
      fireEvent.click(screen.getByRole("radio", { name }));
    }
    expect(red()).toBe(3);

    rerender(<PatternViewer pattern={makePattern(4, 4)} />);
    expect(screen.getByRole("checkbox", { name: "Centre lines" })).toBeChecked();
    expect(red()).toBe(4);
  });

  it("shows the cleaned pattern only in Symbols on colours", () => {
    const recording = stubCanvas();
    const converted = { grid: [[1, 1, null]], key: KEY, total_stitches: 2 };
    render(<PatternViewer pattern={makePattern(3, 1, { grid: [[0, 1, null]], converted })} />);

    fireEvent.click(screen.getByRole("radio", { name: "Symbols on colours" }));

    expect(screen.queryByRole("radio", { name: "Before cleanup" })).not.toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAccessibleName("Pattern symbols on colours, 3 x 1 stitches");
    // The cleaned grid [0, 1, bare] draws Z then A; the converted one would draw A, A.
    expect(recording.texts).toEqual(["Z", "A"]);
  });
});
