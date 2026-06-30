import { test as setup } from "@playwright/test";

import { ensureAdmin } from "./fixtures";

// Backed-suite setup: ensure a deterministic admin account exists BEFORE any other
// backed test registers a user. The backend grants the admin role to the first
// account on a fresh instance, so this must run first — it is wired as a dependency
// of the `backend-backed` project (see playwright.config.ts). Admin-gated backed
// tests then log in via `adminToken()` (e.g. to read the moderation queue).
setup("ensure a deterministic admin exists", async ({ request }) => {
  await ensureAdmin(request);
});
