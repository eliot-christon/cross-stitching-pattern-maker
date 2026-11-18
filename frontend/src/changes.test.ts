import { describe, expect, it } from "vitest";

import type { Change, DmcThread } from "./api";
import {
  append,
  canRedo,
  canUndo,
  changeSize,
  dropHandEdits,
  EMPTY_HISTORY,
  redo,
  remove,
  resetAll,
  toolName,
  undo,
  type History,
} from "./changes";

const BLACK: DmcThread = { code: "310", name: "Black", rgb: [0, 0, 0] };
const WHITE: DmcThread = { code: "3865", name: "Winter White", rgb: [249, 247, 241] };

function replace(from: DmcThread, to: DmcThread | null): Change {
  return { op: "replace", from, to };
}

const A = replace(BLACK, WHITE);
const B = replace(WHITE, null);
const R1 = replace(BLACK, WHITE);
const R2 = replace(WHITE, BLACK);
const S1: Change = { op: "stroke", thread: BLACK, brush: 3, grid: [4, 4], points: [[0, 0]] };
const F1: Change = { op: "fill", thread: null, grid: [4, 4], at: [1, 1] };
const RECT: Change = { op: "rect", thread: WHITE, grid: [4, 4], from: [3, 0], to: [0, 1] };

function made(...changes: Change[]): History {
  return changes.reduce(append, EMPTY_HISTORY);
}

describe("the changes history", () => {
  it("appends, undoes and redoes", () => {
    const both = made(A, B);
    expect(both.list).toEqual([A, B]);
    expect(undo(both).list).toEqual([A]);
    expect(redo(undo(both)).list).toEqual([A, B]);
  });

  it("removes one entry, and an undo puts it back in its place", () => {
    const removed = remove(made(A, B), A);
    expect(removed.list).toEqual([B]);
    expect(undo(removed).list).toEqual([A, B]);
    expect(undo(removed).list[0]).toBe(A);
  });

  it("removes the entry itself, not an equal one", () => {
    const twin = replace(BLACK, WHITE);
    expect(remove(made(A), twin).list).toEqual([A]);
    expect(remove(made(A), twin)).toEqual(made(A));
  });

  it("resets all as one step that an undo reverses", () => {
    const reset = resetAll(made(A, B));
    expect(reset.list).toEqual([]);
    expect(undo(reset).list).toEqual([A, B]);
    expect(resetAll(EMPTY_HISTORY)).toBe(EMPTY_HISTORY);
  });

  it("forgets what was undone once something new is appended", () => {
    const branched = append(undo(made(A, B)), R2);
    expect(canRedo(branched)).toBe(false);
    expect(redo(branched)).toBe(branched);
    expect(branched.list).toEqual([A, R2]);
  });

  it("does nothing on undo or redo with no history", () => {
    expect(undo(EMPTY_HISTORY)).toBe(EMPTY_HISTORY);
    expect(redo(EMPTY_HISTORY)).toBe(EMPTY_HISTORY);
    expect(canUndo(EMPTY_HISTORY)).toBe(false);
    expect(canRedo(EMPTY_HISTORY)).toBe(false);
  });

  it("drops the hand edits as one step, keeping the replacements in order", () => {
    const { history, dropped } = dropHandEdits(made(R1, S1, R2, F1));
    expect(history.list).toEqual([R1, R2]);
    expect(dropped).toBe(2);
    expect(undo(history).list).toEqual([R1, S1, R2, F1]);
  });

  it("leaves a list with no hand edit as it was", () => {
    const only = made(R1, R2);
    expect(dropHandEdits(only)).toEqual({ history: only, dropped: 0 });
  });
});

describe("how a change is named", () => {
  it("names the tool by the kind and, for a stroke, by its thread", () => {
    expect([A, S1, { ...S1, thread: null }, RECT, F1].map(toolName)).toEqual([
      "Replace",
      "Pencil",
      "Eraser",
      "Rectangle",
      "Fill",
    ]);
  });

  it("sizes a stroke by its brush and a rectangle by its box, corners in any order", () => {
    expect(changeSize(S1)).toBe("3 × 3");
    expect(changeSize(RECT)).toBe("4 × 2");
    expect(changeSize(A)).toBeNull();
    expect(changeSize(F1)).toBeNull();
  });
});
