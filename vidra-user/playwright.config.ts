import { defineConfig, devices } from "@playwright/test";

// Smoke/e2e config. The `webServer` builds output is served by `next start`; the
// `ci` script runs `next build` before `playwright test`. A backend-backed
// project (for data-effect verification against a real vidra-core) is added in a
// later slice — see .ralph/AGENT.md.
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
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run start",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
