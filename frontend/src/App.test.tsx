import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("shows the app title as a level-1 heading", () => {
    render(<App />);

    const title = screen.getByRole("heading", {
      level: 1,
      name: "Cross-stitch pattern maker",
    });

    expect(title).toBeInTheDocument();
  });
});
