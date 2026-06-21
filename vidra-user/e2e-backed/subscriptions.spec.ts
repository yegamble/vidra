import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

// Backend-backed e2e (real vidra-core + Postgres, no mocks): a freshly signed-up
// user with no follows hits the real GET /api/v1/me/subscriptions/videos and the
// view renders its empty state. This proves the authenticated subscriptions
// endpoint + view integrate against the live backend. (The populated round-trip —
// follow a channel that has a published video and see it appear — is pending a
// client-side path to channel pages and an upload flow to seed a video.)
test("a new user's subscriptions feed is empty against the real backend", async ({ page }) => {
  const id = randomUUID().replace(/-/g, "").slice(0, 12);

  await page.goto("/signup");
  await page.getByLabel("Username").fill(`e2es${id}`);
  await page.getByLabel("Email").fill(`e2e-${id}@example.test`);
  await page.getByLabel("Password").fill("supersecret-e2e");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Navigate to subscriptions via the header (client-side nav keeps the session).
  await page.getByRole("link", { name: "Subscriptions" }).click();
  await expect(page.getByText("No videos from your subscriptions yet")).toBeVisible();
});
