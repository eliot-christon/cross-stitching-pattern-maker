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
}
