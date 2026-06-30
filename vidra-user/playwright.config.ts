import { defineConfig, devices } from "@playwright/test";

// Smoke/e2e config. The `webServer` build output is served by `next start`; the
// `ci` script runs `next build` before `playwright test`.
//
// Two projects:
//   - `chromium` (./e2e)         — mocked smoke tests (page.route); the default,
//                                  fast, no backend. This is what `npm run ci` runs.
//   - `backend-backed` (./e2e-backed) — data-effect verification against a REAL
//                                  vidra-core + Postgres (no mocks). Run explicitly
//                                  via `npm run e2e:backed` with the core stack up
//                                  and the app built against it — see .ralph/AGENT.md.
//                                  Never part of `npm run ci`.
// The dev/test server port. Defaults to 3000 (what CI and the AGENT.md docs use);
// override with E2E_PORT when 3000 is taken locally (e.g. another project's server).
const PORT = process.env.E2E_PORT ?? "3000";
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["html", { open: "never" }]],
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", testDir: "./e2e", use: { ...devices["Desktop Chrome"] } },
    {
      // Runs first (as a dependency of backend-backed): seeds the deterministic
      // admin account. Only the *.setup.ts file; never part of `npm run ci`.
      name: "backed-setup",
      testDir: "./e2e-backed",
      testMatch: /.*\.setup\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "backend-backed",
      testDir: "./e2e-backed",
      testIgnore: /.*\.setup\.ts/,
      dependencies: ["backed-setup"],
      // Always capture a trace — it is the persistence evidence for the
      // data-mutating flows the frontend rule requires.
      use: { ...devices["Desktop Chrome"], trace: "on" },
    },
  ],
  webServer: {
    command: `npm run start -- -p ${PORT}`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
