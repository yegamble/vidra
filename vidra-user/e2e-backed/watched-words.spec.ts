import { expect, test } from "@playwright/test";

import { ADMIN_EMAIL, ADMIN_PASSWORD, adminToken, uniqueId, watchedWords } from "./fixtures";

// Proves the watched-words round trip against a real vidra-core + PostgreSQL: an
// admin adds a term from the Watched words tab, it persists (visible via the admin
// API read), and removing it deletes the row.
test("an admin adds and removes a watched word and it persists", async ({ page, request }) => {
  const term = `watch-${uniqueId()}`;
  const token = await adminToken(request);
  expect((await watchedWords(request, token)).some((w) => w.word === term)).toBe(false);

  // The deterministic admin logs in through the UI.
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Moderation → Watched words, then add the term.
  await page.getByRole("link", { name: "Moderation" }).click();
  await page.getByRole("link", { name: "Watched words" }).click();
  const added = page.waitForResponse(
    (r) => /\/admin\/watched-words$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await page.getByLabel("Add a watched word").fill(term);
  await page.getByRole("button", { name: "Add" }).click();
  await added;
  await expect(page.getByText(term)).toBeVisible();

  // Persisted: the admin API read shows it.
  expect((await watchedWords(request, token)).some((w) => w.word === term)).toBe(true);

  // Remove it → the row drops and the API read no longer shows it.
  const removed = page.waitForResponse(
    (r) => /\/admin\/watched-words\/[^/]+$/.test(r.url()) && r.request().method() === "DELETE" && r.ok(),
  );
  await page.getByRole("button", { name: `Remove ${term}` }).click();
  await removed;
  await expect(page.getByText(term)).toHaveCount(0);

  expect((await watchedWords(request, token)).some((w) => w.word === term)).toBe(false);
});
