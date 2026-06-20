import { defineConfig } from "vitest/config";

// Unit/component tests run under Vitest; Playwright e2e specs live in ./e2e and
// are excluded here so the two runners never overlap.
export default defineConfig({
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts", "app/**/*.test.{ts,tsx}"],
  },
});
