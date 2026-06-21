import { expect, test } from "@playwright/test";

// Backend-backed e2e (real vidra-core + Postgres, no mocks): proves a profile
// edit persists. Sign up → edit the display name → save → sign out → sign back
// in → the new display name is still there (a fresh login re-reads the user from
// the database). Unique email per run so it is repeatable without a DB reset.
test("profile edit persists across a fresh login", async ({ page }) => {
  const stamp = Date.now();
  const username = `e2ep${stamp}`;
  const email = `e2e-${stamp}@example.test`;
  const password = "supersecret-e2e";
  const newName = `Ada ${stamp}`;

  // Sign up.
  await page.goto("/signup");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Edit the display name on the settings page (reached via the header link).
  await page.getByRole("link", { name: username }).click();
  await expect(page.getByRole("heading", { name: "Account settings" })).toBeVisible();
  await page.getByLabel("Display name").fill(newName);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Profile saved.")).toBeVisible();

  // Sign out, then sign back in — the fresh session is loaded from the database.
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // The persisted display name is shown on the settings form after the fresh login.
  await page.getByRole("link", { name: username }).click();
  await expect(page.getByLabel("Display name")).toHaveValue(newName);
});
