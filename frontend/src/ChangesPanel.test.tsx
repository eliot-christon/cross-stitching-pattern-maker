import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Change, DmcThread, Limits, Settings } from "./api";
import { ChangesPanel } from "./ChangesPanel";

const BLACK: DmcThread = { code: "310", name: "Black", rgb: [0, 0, 0] };
const WHITE: DmcThread = { code: "3865", name: "Winter White", rgb: [249, 247, 241] };

const RANGES: Limits["settings"] = {
  width: { min: 1, max: 500, step: 1, default: 100 },
  max_colours: { min: 1, max: 100, step: 1, default: 7 },
  merge_distance: { min: 0, max: 10, step: 0.5, default: 0 },
  min_stitches: { min: 0, max: 1000, step: 1, default: 0 },
  confetti_size: { min: 0, max: 10, step: 1, default: 0 },
  pages_across: { min: 1, max: 20, step: 1, default: 2 },
  pages_down: { min: 1, max: 20, step: 1, default: 2 },
  overlap: { min: 0, max: 5, step: 1, default: 2 },
};

const PLAIN: Settings = {
  width: "100",
  maxColours: "7",
  fabricCount: "14",
  mergeDistance: "0",
  minStitches: "0",
  confettiSize: "0",
  readAs: "picture",
  crop: "",
  backgroundAsFabric: false,
};

const REPLACE: Change = { op: "replace", from: BLACK, to: WHITE };
const REMOVE: Change = { op: "replace", from: WHITE, to: null };
const STROKE: Change = { op: "stroke", thread: BLACK, brush: 3, grid: [10, 10], points: [[1, 1]] };
const ERASER: Change = { op: "stroke", thread: null, brush: 1, grid: [10, 10], points: [[2, 2]] };
const RECT: Change = { op: "rect", thread: WHITE, grid: [10, 10], from: [5, 1], to: [2, 2] };
const FILL: Change = { op: "fill", thread: BLACK, grid: [10, 10], at: [0, 0] };

function panel(overrides: Partial<Parameters<typeof ChangesPanel>[0]> = {}) {
  const props: Parameters<typeof ChangesPanel>[0] = {
    settings: PLAIN,
    ranges: RANGES,
    onReset: vi.fn(),
    changes: [],
    counts: new Map(),
    canUndo: false,
    canRedo: false,
    onUndo: vi.fn(),
    onRedo: vi.fn(),
    onRemove: vi.fn(),
    onResetAll: vi.fn(),
    notice: null,
    ...overrides,
  };
  render(<ChangesPanel {...props} />);
  return props;
}

function entries(): HTMLElement[] {
  return within(screen.getByRole("list", { name: "Edits and replacements" })).getAllByRole("listitem");
}

describe("ChangesPanel", () => {
  it("lists one entry of each kind in order, named by its tool, thread and size", () => {
    panel({ changes: [REPLACE, REMOVE, STROKE, ERASER, RECT, FILL] });

    const texts = entries().map((item) => item.textContent ?? "");
    expect(texts).toHaveLength(6);
    expect(texts[0]).toMatch(/Replace.*310.*Black.*3865.*Winter White/);
    expect(texts[1]).toMatch(/Replace.*3865.*Fabric/);
    expect(texts[2]).toMatch(/Pencil.*310.*3 × 3/);
    expect(texts[3]).toMatch(/Eraser.*Fabric.*1 × 1/);
    expect(texts[4]).toMatch(/Rectangle.*3865.*4 × 2/);
    expect(texts[5]).toMatch(/Fill.*310/);
  });

  it("shows each entry's count from the latest response, a 0 as not in the pattern", () => {
    panel({ changes: [STROKE, REPLACE], counts: new Map<Change, number>([[STROKE, 12], [REPLACE, 0]]) });

    const [first, second] = entries();
    expect(first).toHaveTextContent("12 cells");
    expect(first).not.toHaveClass("inactive");
    expect(second).toHaveTextContent("not in the pattern");
    expect(second).toHaveClass("inactive");
  });

  it("shows no count for an entry the latest response has not seen", () => {
    panel({ changes: [STROKE] });
    expect(entries()[0]).not.toHaveTextContent(/cells|not in the pattern/);
  });

  it("says nothing differs when no setting is off its default and the list is empty", () => {
    panel();
    expect(screen.getByRole("region", { name: "Changes" })).toHaveTextContent(
      "Nothing differs from the plain conversion.",
    );
    expect(screen.queryByRole("list", { name: "Settings changed" })).not.toBeInTheDocument();
  });

  it("shows a setting off its default as a chip whose reset reports the default", () => {
    const props = panel({ settings: { ...PLAIN, mergeDistance: "2" } });

    expect(within(screen.getByRole("list", { name: "Settings changed" })).getByText("Merge distance 2")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Reset merge distance" }));
    expect(props.onReset).toHaveBeenCalledWith({ mergeDistance: "0" });
  });

  it("chips the crop and the background, each reset to off", () => {
    const props = panel({ settings: { ...PLAIN, crop: "10,20,110,70", backgroundAsFabric: true } });

    expect(screen.getByText("Crop 100 × 50 px")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Remove the crop" }));
    fireEvent.click(screen.getByRole("button", { name: "Turn off background as fabric" }));
    expect(props.onReset).toHaveBeenNthCalledWith(1, { crop: "" });
    expect(props.onReset).toHaveBeenNthCalledWith(2, { backgroundAsFabric: false });
  });

  it("removes an entry, undoes, redoes and resets all through its buttons", () => {
    const props = panel({ changes: [REPLACE, STROKE], canUndo: true, canRedo: true });

    fireEvent.click(within(entries()[1] as HTMLElement).getByRole("button", { name: /Remove/ }));
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    fireEvent.click(screen.getByRole("button", { name: "Redo" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset all" }));

    expect(props.onRemove).toHaveBeenCalledWith(STROKE);
    expect(props.onUndo).toHaveBeenCalledOnce();
    expect(props.onRedo).toHaveBeenCalledOnce();
    expect(props.onResetAll).toHaveBeenCalledOnce();
  });

  it("disables undo, redo and reset all when there is nothing to do", () => {
    panel();
    for (const name of ["Undo", "Redo", "Reset all"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
  });

  it("shows a notice", () => {
    panel({ notice: "2 hand edits dropped: the pattern is now 40 × 30." });
    expect(screen.getByRole("status")).toHaveTextContent("2 hand edits dropped");
  });
});
