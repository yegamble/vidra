import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

// Unit/component tests run under Vitest; Playwright e2e specs live in ./e2e and
// are excluded here so the two runners never overlap. The "@/*" alias mirrors
// tsconfig paths so test imports resolve like app code.
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts", "app/**/*.test.{ts,tsx}"],
  },
});
