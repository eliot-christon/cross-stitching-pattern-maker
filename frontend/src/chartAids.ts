/**
 * Where the viewer's chart aids go, in cells from the pattern's top-left, placed as the
 * PDF chart places them (`src/cross_stitch/export/pdf.py`): a bold line every 10 cells and
 * on the pattern's edges, and the centre at width / 2 and height / 2, where the PDF's
 * arrows point. Pure: the canvas code only draws what these return.
 */
import type { View } from "./symbolView";
import type { Size } from "./viewport";

/** Smallest cell, in CSS px, at which the 10-cell lines are drawn. */
export const LINE_MIN_PX = 4;

/** The borders, from `first` to `first + count` inclusive, that carry a 10-cell line. */
function borders(first: number, count: number, cells: number): number[] {
  const lines: number[] = [];
  for (let border = first; border <= first + count; border++) {
    if (border % 10 === 0 || border === cells) {
      lines.push(border);
    }
  }
  return lines;
}

/**
 * The cell borders inside the window that carry a 10-cell line: every multiple of 10 and
 * both edges of the pattern. None when cells are smaller than `LINE_MIN_PX`.
 */
export function tenCellLines(
  view: View,
  pattern: Size,
  scale: number,
): { columns: number[]; rows: number[] } {
  if (!(scale >= LINE_MIN_PX) || view.columns === 0 || view.rows === 0) {
    return { columns: [], rows: [] };
  }
  return {
    columns: borders(view.firstColumn, view.columns, pattern.width),
    rows: borders(view.firstRow, view.rows, pattern.height),
  };
}

/** The centre lines: a cell border for an even size, the middle of a cell for an odd one. */
export function centreLines(pattern: Size): { column: number; row: number } {
  return { column: pattern.width / 2, row: pattern.height / 2 };
}
