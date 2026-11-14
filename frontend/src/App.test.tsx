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

  it("puts the upload form on the page, with no pattern before a conversion", () => {
    render(<App />);

    expect(screen.getByLabelText("Image")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /convert/i })).toBeDisabled();
    expect(screen.queryByRole("table", { name: "Thread key" })).not.toBeInTheDocument();
  });
});
