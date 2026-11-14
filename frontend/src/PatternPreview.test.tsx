import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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

  it("has the column headers Code, Name, Stitches and Skeins", () => {
    render(<PatternPreview pattern={makePattern()} />);

    const table = screen.getByRole("table", { name: "Thread key" });
    for (const name of ["Code", "Name", "Stitches", "Skeins"]) {
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
