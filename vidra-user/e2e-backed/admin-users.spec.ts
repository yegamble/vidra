import { expect, test } from "@playwright/test";

import { ADMIN_EMAIL, ADMIN_PASSWORD, adminToken, adminUsers, registerUser } from "./fixtures";

// Proves the admin user-management round trip against a real vidra-core + PostgreSQL:
// a fresh account is seeded via the API, the deterministic admin logs in through the
// UI, finds the account, promotes it to moderator and then deactivates it — and a
// fresh authed refetch (plus a direct admin API read) confirms both mutations
// persisted (users.role → moderator, users.is_active → false).
test("an admin promotes then deactivates a user, and it persists", async ({ page, request }) => {
  const target = await registerUser(request);

  const token = await adminToken(request);
  const before = (await adminUsers(request, token, target.username))[0];
  expect(before?.role).toBe("user");
  expect(before?.is_active).toBe(true);

  // The deterministic admin logs in through the UI.
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Open the admin users page (client-side nav keeps the in-memory session) and
  // search for the seeded account (scopes the list to one row).
  await page.getByRole("link", { name: "Admin", exact: true }).click();
  await page.getByRole("searchbox", { name: "Search users" }).fill(target.username);
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByText(target.email)).toBeVisible();

  // Promote to moderator.
  const promoted = page.waitForResponse(
    (r) => /\/admin\/users\/[^/]+$/.test(r.url()) && r.request().method() === "PATCH" && r.ok(),
  );
  await page.getByLabel(`Role for ${target.username}`).selectOption("moderator");
  await promoted;
  await expect(page.getByLabel(`Role for ${target.username}`)).toHaveValue("moderator");

  // Deactivate.
  const deactivated = page.waitForResponse(
    (r) => /\/admin\/users\/[^/]+$/.test(r.url()) && r.request().method() === "PATCH" && r.ok(),
  );
  await page.getByRole("button", { name: `Deactivate ${target.username}` }).click();
  await deactivated;
  await expect(page.getByRole("button", { name: `Reactivate ${target.username}` })).toBeVisible();

  // Persisted across a fresh refetch (navigate away + back, re-search).
  await page.getByRole("link", { name: "Home" }).click();
  await page.getByRole("link", { name: "Admin", exact: true }).click();
  await page.getByRole("searchbox", { name: "Search users" }).fill(target.username);
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByLabel(`Role for ${target.username}`)).toHaveValue("moderator");
  await expect(page.getByRole("button", { name: `Reactivate ${target.username}` })).toBeVisible();

  // Persisted in the database (admin API read).
  const after = (await adminUsers(request, token, target.username))[0];
  expect(after?.role).toBe("moderator");
  expect(after?.is_active).toBe(false);
});
