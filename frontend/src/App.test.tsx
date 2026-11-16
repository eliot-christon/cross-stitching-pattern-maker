import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const LIMIT = { min: 0, max: 10, step: 1, default: 0 };
const LIMITS = {
  max_upload_bytes: 1000,
  settings: {
    width: { min: 1, max: 500, step: 1, default: 100 },
    max_colours: { min: 1, max: 100, step: 1, default: 7 },
    merge_distance: LIMIT,
    min_stitches: LIMIT,
    confetti_size: LIMIT,
    pages_across: { min: 1, max: 20, step: 1, default: 2 },
    pages_down: { min: 1, max: 20, step: 1, default: 2 },
    overlap: { min: 0, max: 5, step: 1, default: 2 },
  },
};

const PATTERN = {
  width: 2,
  height: 1,
  fabric_count: 14,
  grid: [[0, 1]],
  key: [
    { code: "321", name: "Red", rgb: [199, 43, 59], stitches: 1, skeins: 1, symbol: "A", symbol_ink: "white" },
    { code: "310", name: "Black", rgb: [0, 0, 0], stitches: 1, skeins: 1, symbol: "B", symbol_ink: "white" },
  ],
  total_stitches: 2,
  finished_size: { width_in: 0.14, height_in: 0.07, width_cm: 0.36, height_cm: 0.18 },
  isolated_stitches: { before: 2, after: 0 },
  converted: null,
  ignored_replacements: [],
};

/** What the viewer area says before there is a pattern to show. */
const EMPTY = /pattern appears here/i;

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

/** fetch answering `/api/limits` with LIMITS, an inspection finding a picture and any
 * conversion with PATTERN. */
function stubLimits() {
  const answers: Record<string, unknown> = {
    "/api/limits": LIMITS,
    "/api/images/inspect": { kind: "picture", description: "Picture", grid: null, warnings: [], refusal: null },
  };
  const fetchMock = vi.fn((url: string) =>
    Promise.resolve(json(answers[url] ?? PATTERN)),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("shows the app title as a level-1 heading", () => {
    stubLimits();
    render(<App />);

    const title = screen.getByRole("heading", {
      level: 1,
      name: "Cross-stitch pattern maker",
    });

    expect(title).toBeInTheDocument();
  });

  it("puts the upload form on the page once the limits are in, with no Convert button and no pattern", async () => {
    const fetchMock = stubLimits();
    render(<App />);

    expect(await screen.findByLabelText("Image")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /convert/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Thread key" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(["/api/limits"]);
  });

  it("shows an empty viewer, neither a status nor an alert, until an image is chosen", async () => {
    stubLimits();
    render(<App />);

    await screen.findByLabelText("Image");

    expect(screen.getByText(EMPTY)).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("replaces the empty viewer with the pattern once one is shown", async () => {
    stubLimits();
    render(<App />);
    const image = await screen.findByLabelText("Image");

    fireEvent.change(image, {
      target: { files: [new File(["x"], "a.png", { type: "image/png" })] },
    });

    expect(await screen.findByRole("table", { name: "Thread key" })).toBeInTheDocument();
    expect(screen.queryByText(EMPTY)).not.toBeInTheDocument();
  });
});
