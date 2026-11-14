// Registers the jest-dom matchers and unmounts rendered trees between tests: with vitest
// globals off, Testing Library cannot install its own afterEach cleanup.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
