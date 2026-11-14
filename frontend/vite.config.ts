import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    // The dev server forwards /api/* to uvicorn with the prefix stripped, so the browser
    // talks to one origin and the API needs no CORS. 127.0.0.1, not localhost: Node can
    // resolve localhost to ::1 while uvicorn listens on IPv4 only.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
  },
});
