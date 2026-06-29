import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Observability: a single logger module is the only place console.* is allowed
  // (see .ralph/specs/observability.md). Everywhere else it is an error.
  {
    rules: {
      "no-console": "error",
    },
  },
  // Dev/CI Node scripts (run via `node`, never shipped to the browser) — console
  // output is their entire purpose, so no-console does not apply to them.
  {
    files: ["scripts/**/*.{mjs,js,ts}"],
    rules: {
      "no-console": "off",
    },
  },
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Test/build artifacts.
    "playwright-report/**",
    "test-results/**",
    "coverage/**",
  ]),
]);

export default eslintConfig;
