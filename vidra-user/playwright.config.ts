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
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["html", { open: "never" }]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", testDir: "./e2e", use: { ...devices["Desktop Chrome"] } },
    {
      name: "backend-backed",
      testDir: "./e2e-backed",
      // Always capture a trace — it is the persistence evidence for the
      // data-mutating flows the frontend rule requires.
      use: { ...devices["Desktop Chrome"], trace: "on" },
    },
  ],
  webServer: {
    command: "npm run start",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
