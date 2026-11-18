import type { Change } from "./api";

/**
 * The ordered list of changes with its history, for undo and redo. Pure: every step
 * returns a new history and leaves the one it was given as it was. Undo and redo cover
 * the list only, never the settings.
 */
export interface History {
  readonly list: readonly Change[];
  /** The lists before each step, oldest first. */
  readonly past: readonly (readonly Change[])[];
  /** The lists undone, the next to redo last. */
  readonly future: readonly (readonly Change[])[];
}

export const EMPTY_HISTORY: History = { list: [], past: [], future: [] };

/** A step to `list`: the current list goes on the past, and nothing is left to redo. */
function step(history: History, list: readonly Change[]): History {
  return { list, past: [...history.past, history.list], future: [] };
}

export function append(history: History, change: Change): History {
  return step(history, [...history.list, change]);
}

/** The list without `change` (the entry itself, not an equal one); unchanged without it. */
export function remove(history: History, change: Change): History {
  return history.list.includes(change) ? step(history, history.list.filter((entry) => entry !== change)) : history;
}

/** An empty list, as one step; unchanged when it is already empty. */
export function resetAll(history: History): History {
  return history.list.length === 0 ? history : step(history, []);
}

export function canUndo(history: History): boolean {
  return history.past.length > 0;
}

export function canRedo(history: History): boolean {
  return history.future.length > 0;
}

export function undo(history: History): History {
  const previous = history.past.at(-1);
  if (previous === undefined) {
    return history;
  }
  return { list: previous, past: history.past.slice(0, -1), future: [...history.future, history.list] };
}

export function redo(history: History): History {
  const next = history.future.at(-1);
  if (next === undefined) {
    return history;
  }
  return { list: next, past: [...history.past, history.list], future: history.future.slice(0, -1) };
}

/** Whether `change` was drawn on the pattern's cells (a stroke, rectangle or fill). */
export function isHandEdit(change: Change): boolean {
  return change.op !== "replace";
}

/**
 * The list without its hand edits, replacements kept, as one step, and how many went.
 * With no hand edit, the history comes back as it was.
 */
export function dropHandEdits(history: History): { history: History; dropped: number } {
  const kept = history.list.filter((change) => !isHandEdit(change));
  const dropped = history.list.length - kept.length;
  return { history: dropped === 0 ? history : step(history, kept), dropped };
}

/** The tool a change was made with, as the page names it. */
export function toolName(change: Change): "Replace" | "Pencil" | "Eraser" | "Rectangle" | "Fill" {
  switch (change.op) {
    case "replace":
      return "Replace";
    case "stroke":
      return change.thread === null ? "Eraser" : "Pencil";
    case "rect":
      return "Rectangle";
    case "fill":
      return "Fill";
  }
}

/** The size of a change as the page shows it ("3 × 3": a brush, "4 × 2": a box), or null. */
export function changeSize(change: Change): string | null {
  switch (change.op) {
    case "stroke":
      return `${change.brush} × ${change.brush}`;
    case "rect":
      return `${Math.abs(change.to[0] - change.from[0]) + 1} × ${Math.abs(change.to[1] - change.from[1]) + 1}`;
    default:
      return null;
  }
}
