import type { KeyEntry, Pattern } from "./pattern";

/** A window onto the grid, in cells: the top-left cell and how many columns and rows. */
export interface View {
  firstColumn: number;
  firstRow: number;
  columns: number;
  rows: number;
}

/** One cell in view and the symbol it shows; `null` is bare fabric. */
export interface SymbolCell {
  column: number;
  row: number;
  symbol: string | null;
}

/** One cell in view and its key entry; `null` is bare fabric. */
export interface EntryCell {
  column: number;
  row: number;
  entry: KeyEntry | null;
}

/**
 * The cells inside `view`, row by row, each with its key entry. The view is clipped to
 * the grid, and only the rows and columns in it are read, so the cost follows the view,
 * not the pattern. A cell pointing at a key entry that does not exist throws.
 */
export function visibleCells(
  pattern: Pick<Pattern, "width" | "height" | "grid" | "key">,
  view: View,
): EntryCell[] {
  const { width, height, grid, key } = pattern;
  const firstColumn = Math.max(0, view.firstColumn);
  const firstRow = Math.max(0, view.firstRow);
  const endColumn = Math.min(width, view.firstColumn + view.columns);
  const endRow = Math.min(height, view.firstRow + view.rows);
  const cells: EntryCell[] = [];
  for (let row = firstRow; row < endRow; row++) {
    const cellsOfRow = grid[row] ?? [];
    for (let column = firstColumn; column < endColumn; column++) {
      const index = cellsOfRow[column] ?? null;
      if (index === null) {
        cells.push({ column, row, entry: null });
        continue;
      }
      const entry = key[index];
      if (entry === undefined) {
        throw new Error(
          `cell (${column}, ${row}) points at key entry ${index}, which does not exist`,
        );
      }
      cells.push({ column, row, entry });
    }
  }
  return cells;
}

/** The cells inside `view` with their key entry's `symbol`, as the response gives it. */
export function visibleSymbols(
  pattern: Pick<Pattern, "width" | "height" | "grid" | "key">,
  view: View,
): SymbolCell[] {
  return visibleCells(pattern, view).map(({ column, row, entry }) => ({
    column,
    row,
    symbol: entry === null ? null : entry.symbol,
  }));
}
