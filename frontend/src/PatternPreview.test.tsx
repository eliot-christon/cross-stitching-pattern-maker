import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { gridPixels } from "./grid";
import type { KeyEntry, Pattern } from "./pattern";
import { PatternPreview } from "./PatternPreview";

function makePattern(overrides: Partial<Pattern> = {}): Pattern {
  const key: KeyEntry[] = [
    { code: "321", name: "Red", rgb: [199, 43, 59], stitches: 5, skeins: 1, symbol: "Z" },
    { code: "310", name: "Black", rgb: [0, 0, 0], stitches: 9, skeins: 2, symbol: "A" },
  ];
  return {
    width: 40,
    height: 20,
    fabric_count: 14,
    grid: [[0, 1, null]],
    key,
    total_stitches: 123,
    finished_size: { width_in: 9.99, height_in: 5.04, width_cm: 25.4, height_cm: 12.7 },
    isolated_stitches: { before: 0, after: 0 },
    converted: null,
    ...overrides,
  };
}

function keyRows(): HTMLElement[] {
  const table = screen.getByRole("table", { name: "Thread key" });
  return within(table).getAllByRole("row");
}

function cellTexts(row: HTMLElement): string[] {
  return within(row)
    .getAllByRole("cell")
    .map((c) => c.textContent ?? "");
}

describe("PatternPreview", () => {
  it("renders the grid canvas with an accessible name, without a canvas context", () => {
    render(<PatternPreview pattern={makePattern()} />);

    expect(screen.getByRole("img", { name: /^Pattern preview/ })).toBeInTheDocument();
  });

  it("lists key rows in the response order, not sorted by stitches", () => {
    render(<PatternPreview pattern={makePattern()} />);

    const rows = keyRows();

    expect(rows).toHaveLength(3);
    const codes = rows.slice(1).map((row) => cellTexts(row).join("|"));
    expect(codes[0]).toContain("321");
    expect(codes[1]).toContain("310");
    expect(codes[0]).not.toContain("310");
  });

  it("shows code, name, stitches and skeins as given", () => {
    render(<PatternPreview pattern={makePattern()} />);

    const rows = keyRows();
    const first = rows[1];
    const second = rows[2];
    if (first === undefined || second === undefined) {
      throw new Error("key rows missing");
    }

    expect(cellTexts(first)).toContain("321");
    expect(cellTexts(first)).toContain("Red");
    expect(cellTexts(first)).toContain("5");
    expect(cellTexts(first)).toContain("1");
    expect(cellTexts(second)).toContain("310");
    expect(cellTexts(second)).toContain("Black");
    expect(cellTexts(second)).toContain("9");
    expect(cellTexts(second)).toContain("2");
  });

  it("puts each value under its own column header", () => {
    render(<PatternPreview pattern={makePattern()} />);

    // Read every row by header name, so stitches and skeins cannot swap unnoticed.
    const [header, ...body] = keyRows().map((row) =>
      Array.from(row.children).map((cell) => cell.textContent ?? ""),
    );
    if (header === undefined) {
      throw new Error("header row missing");
    }
    const byColumn = body.map((cells) =>
      Object.fromEntries(header.map((name, i) => [name, cells[i]])),
    );

    expect(byColumn).toEqual([
      expect.objectContaining({ Code: "321", Name: "Red", Stitches: "5", Skeins: "1" }),
      expect.objectContaining({ Code: "310", Name: "Black", Stitches: "9", Skeins: "2" }),
    ]);
  });

  it("opens in the colour view and offers the symbol view", () => {
    render(<PatternPreview pattern={makePattern()} />);

    expect(screen.getByRole("radio", { name: "Colours" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Symbols" })).not.toBeChecked();
    expect(screen.getByRole("img", { name: /^Pattern preview/ })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /^Pattern symbols/ })).not.toBeInTheDocument();
  });

  it("switches to the symbol view and back", () => {
    render(<PatternPreview pattern={makePattern()} />);

    fireEvent.click(screen.getByRole("radio", { name: "Symbols" }));

    expect(screen.getByRole("radio", { name: "Symbols" })).toBeChecked();
    expect(screen.getByRole("img", { name: "Pattern symbols, 40 x 20 stitches" })).toBeVisible();
    expect(screen.queryByRole("img", { name: /^Pattern preview/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "Colours" }));

    expect(screen.getByRole("img", { name: /^Pattern preview/ })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /^Pattern symbols/ })).not.toBeInTheDocument();
  });

  it("shows every key row with its symbol, as given and in order, in both views", () => {
    render(<PatternPreview pattern={makePattern()} />);

    const rowsByColumn = () => {
      const [header, ...body] = keyRows().map((row) =>
        Array.from(row.children).map((cell) => cell.textContent ?? ""),
      );
      if (header === undefined) {
        throw new Error("header row missing");
      }
      return body.map((cells) => Object.fromEntries(header.map((name, i) => [name, cells[i]])));
    };
    const expected = [
      { "": "", Symbol: "Z", Code: "321", Name: "Red", Stitches: "5", Skeins: "1" },
      { "": "", Symbol: "A", Code: "310", Name: "Black", Stitches: "9", Skeins: "2" },
    ];

    expect(rowsByColumn()).toEqual(expected);

    fireEvent.click(screen.getByRole("radio", { name: "Symbols" }));

    expect(rowsByColumn()).toEqual(expected);
  });

  it("has the column headers Symbol, Code, Name, Stitches and Skeins", () => {
    render(<PatternPreview pattern={makePattern()} />);

    const table = screen.getByRole("table", { name: "Thread key" });
    for (const name of ["Symbol", "Code", "Name", "Stitches", "Skeins"]) {
      expect(within(table).getByRole("columnheader", { name })).toBeInTheDocument();
    }
  });

  it("shows the finished size from the response, not width / fabric_count", () => {
    render(<PatternPreview pattern={makePattern()} />);

    expect(screen.getByText("10.0 x 5.0 in")).toBeInTheDocument();
    expect(screen.getByText("25.4 x 12.7 cm")).toBeInTheDocument();
  });

  it("shows total_stitches as returned even when the key sums to something else", () => {
    render(<PatternPreview pattern={makePattern({ total_stitches: 123 })} />);

    expect(screen.getByText("123 stitches in total")).toBeInTheDocument();
  });

  it("shows the isolated stitches before and after cleanup as returned", () => {
    const isolated_stitches = { before: 42, after: 7 };
    render(<PatternPreview pattern={makePattern({ isolated_stitches })} />);

    expect(screen.getByText("42 before cleanup")).toBeInTheDocument();
    expect(screen.getByText("7 after cleanup")).toBeInTheDocument();
  });

  it("shows width x height and the fabric count as given", () => {
    render(<PatternPreview pattern={makePattern()} />);

    expect(screen.getByText("40 x 20 stitches")).toBeInTheDocument();
    expect(screen.getByText("14 count")).toBeInTheDocument();
  });

  it("renders an empty key and all-null grid with a header row only and total 0", () => {
    render(
      <PatternPreview
        pattern={makePattern({
          width: 2,
          height: 1,
          grid: [[null, null]],
          key: [],
          total_stitches: 0,
        })}
      />,
    );

    expect(keyRows()).toHaveLength(1);
    expect(screen.getByText("0 stitches in total")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /^Pattern preview/ })).toBeInTheDocument();
  });
});

describe("PatternPreview before and after cleanup", () => {
  /** 3 x 1: the cleaned grid holds red, black, bare; before cleanup the black cell was white. */
  function cleanedPattern(): Pattern {
    return makePattern({
      width: 3,
      height: 1,
      grid: [[0, 1, null]],
      converted: {
        grid: [[0, 2, null]],
        key: [
          { code: "321", name: "Red", rgb: [199, 43, 59], stitches: 1, skeins: 1, symbol: "Z" },
          { code: "310", name: "Black", rgb: [0, 0, 0], stitches: 0, skeins: 0, symbol: "A" },
          { code: "Blanc", name: "White", rgb: [252, 251, 248], stitches: 1, skeins: 1, symbol: "B" },
        ],
        total_stitches: 2,
      },
    });
  }

  /** A 2D context per canvas, recording what each one is painted with, by accessible name. */
  function stubCanvas() {
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
    const painted = new Map<string, Uint8ClampedArray[]>();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(function (
      this: HTMLCanvasElement,
    ) {
      const name = this.getAttribute("aria-label") ?? "";
      return {
        putImageData: (image: { data: Uint8ClampedArray }) => {
          painted.set(name, [...(painted.get(name) ?? []), image.data]);
        },
      } as unknown as CanvasRenderingContext2D;
    } as unknown as HTMLCanvasElement["getContext"]);
    return painted;
  }

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows a before and an after grid, each named, when the response has converted", () => {
    render(<PatternPreview pattern={cleanedPattern()} />);

    const images = screen.getAllByRole("img");
    expect(images.map((image) => image.getAttribute("aria-label"))).toEqual([
      "Before cleanup, 3 x 1 stitches",
      "After cleanup, 3 x 1 stitches",
    ]);
    expect(screen.getByText("Before cleanup")).toBeInTheDocument();
    expect(screen.getByText("After cleanup")).toBeInTheDocument();
  });

  it("shows one grid, named as without cleanup, when converted is null", () => {
    render(<PatternPreview pattern={makePattern({ converted: null })} />);

    const images = screen.getAllByRole("img");
    expect(images).toHaveLength(1);
    expect(images[0]).toHaveAccessibleName("Pattern preview, 40 x 20 stitches");
    expect(screen.queryByText("Before cleanup")).not.toBeInTheDocument();
  });

  it("paints the before grid from converted and the after grid from the top level", () => {
    const painted = stubCanvas();
    const pattern = cleanedPattern();
    const converted = pattern.converted;
    if (converted === null) {
      throw new Error("fixture has no converted pattern");
    }
    const before = gridPixels({ width: 3, height: 1, grid: converted.grid, key: converted.key });
    const after = gridPixels(pattern);
    // The fixture's two grids differ, so the canvases cannot pass by swapping.
    expect(Array.from(before)).not.toEqual(Array.from(after));

    render(<PatternPreview pattern={pattern} />);

    expect(painted.get("Before cleanup, 3 x 1 stitches")?.map((d) => Array.from(d))).toEqual([
      Array.from(before),
    ]);
    expect(painted.get("After cleanup, 3 x 1 stitches")?.map((d) => Array.from(d))).toEqual([
      Array.from(after),
    ]);
  });

  it("does not repaint either grid when shown again with the same pattern", () => {
    const painted = stubCanvas();
    const pattern = cleanedPattern();

    const { rerender } = render(<PatternPreview pattern={pattern} />);
    rerender(<PatternPreview pattern={pattern} />);

    expect(painted.get("Before cleanup, 3 x 1 stitches")).toHaveLength(1);
    expect(painted.get("After cleanup, 3 x 1 stitches")).toHaveLength(1);
  });

  it("shows one symbol grid, the cleaned one, in the symbol view", () => {
    render(<PatternPreview pattern={cleanedPattern()} />);

    fireEvent.click(screen.getByRole("radio", { name: "Symbols" }));

    const images = screen.getAllByRole("img");
    expect(images).toHaveLength(1);
    expect(images[0]).toHaveAccessibleName("Pattern symbols, 3 x 1 stitches");
  });

  it("lists the cleaned key only, not the threads cleanup removed", () => {
    render(<PatternPreview pattern={cleanedPattern()} />);

    const codes = keyRows()
      .slice(1)
      .map((row) => cellTexts(row)[2]);
    expect(codes).toEqual(["321", "310"]);
    expect(screen.queryByText("Blanc")).not.toBeInTheDocument();
    expect(screen.getByText("123 stitches in total")).toBeInTheDocument();
  });
});
