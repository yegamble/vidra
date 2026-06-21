import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

// Backend-backed e2e: runs against a REAL vidra-core + PostgreSQL with NO route
// mocks (the `backend-backed` Playwright project). It proves the signup
// data-mutating flow actually persists: UI signup → the account is written to
// Postgres → a fresh UI login reads it back. The frontend must be built pointing
// at the running backend (NEXT_PUBLIC_API_BASE_URL) — see vidra-user/.ralph/AGENT.md.
//
// Each run uses a unique email so it is repeatable without resetting the DB.
test("signup persists the account and a fresh login reads it back", async ({ page }) => {
  // A per-test unique id avoids email/username collisions even when the
  // backend-backed specs run in parallel from the same machine.
  const id = randomUUID().replace(/-/g, "").slice(0, 12);
  const username = `e2ea${id}`;
  const email = `e2e-${id}@example.test`;
  const password = "supersecret-e2e";

  // Sign up through the UI against the real backend.
  await page.goto("/signup");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Create account" }).click();

  // The account is created and the session is established (header shows Sign out).
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Sign out, then sign back in with the same credentials. A successful fresh
  // login can only work if the account row persisted in the database.
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);

  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
});
