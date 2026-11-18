// The JSON body of POST /patterns, written by hand to match `PatternOut` in
// src/cross_stitch/api/app.py. Every number in it is computed by the backend; the frontend
// only displays them.

export interface KeyEntry {
  code: string;
  name: string;
  rgb: [number, number, number];
  stitches: number;
  skeins: number;
  /** The chart symbol the backend gave this entry; shown as is, never reassigned. */
  symbol: string;
  /** The symbol's ink on this thread's colour, as the colour PDF prints it. */
  symbol_ink: "black" | "white";
}

export interface FinishedSize {
  width_in: number;
  height_in: number;
  width_cm: number;
  height_cm: number;
}

/** Stitched cells with no neighbour of the same thread, before and after cleanup. */
export interface IsolatedStitches {
  before: number;
  after: number;
}

/**
 * The pattern before cleanup. Width, height, fabric count and finished size are the
 * cleaned pattern's, which cleanup never changes.
 */
export interface ConvertedPattern {
  /** Rows of indices into this object's `key`; `null` is bare fabric. */
  grid: (number | null)[][];
  key: KeyEntry[];
  total_stitches: number;
}

export interface Pattern {
  width: number;
  height: number;
  fabric_count: number;
  /** Rows of key indices; `null` is bare fabric. */
  grid: (number | null)[][];
  key: KeyEntry[];
  total_stitches: number;
  finished_size: FinishedSize;
  isolated_stitches: IsolatedStitches;
  /** The pattern before cleanup, or `null` when every cleanup setting is 0. */
  converted: ConvertedPattern | null;
  /** The cells each entry of the `changes` sent changed, in order; 0: it did nothing. */
  changed_cells: number[];
}
