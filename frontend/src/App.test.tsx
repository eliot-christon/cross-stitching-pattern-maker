import { render, screen } from "@testing-library/react";
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
  },
};

/** fetch answering the page's `/api/limits` request; nothing else is asked for here. */
function stubLimits() {
  const fetchMock = vi.fn((_url: string) =>
    Promise.resolve(
      new Response(JSON.stringify(LIMITS), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
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
});
