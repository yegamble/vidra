import { expect, test } from "@playwright/test";

import { seedPublishedChannel, uniqueId } from "./fixtures";

// Proves the save round trip against a real vidra-core + PostgreSQL: a viewer
// saves a video from the watch page UI, the button reflects it, and the saved
// video appears in the library after a fresh refetch (client-side navigation).
// DB evidence (the saved_videos row) is captured separately via psql.
test("saving a video from the watch page persists it and shows in the library", async ({
  page,
  request,
}) => {
  const { videoTitle } = await seedPublishedChannel(request);

  // A fresh viewer signs up (the session lives in memory).
  const id = uniqueId();
  await page.goto("/signup");
  await page.getByLabel("Username").fill(`fan${id}`);
  await page.getByLabel("Email").fill(`e2e-fan-${id}@example.test`);
  await page.getByLabel("Password").fill("supersecret-e2e");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Reach the seeded video's watch page from the home feed and save it.
  await page.getByRole("heading", { name: videoTitle }).click();
  await expect(page.getByRole("heading", { level: 1, name: videoTitle })).toBeVisible();
  const save = page.getByRole("button", { name: "Save", exact: true });
  await expect(save).toBeEnabled();
  await save.click();
  await expect(page.getByRole("button", { name: "Saved", exact: true })).toBeVisible();

  // The saved video appears in the library after a fresh refetch (the library
  // page issues its own GET /me/saved against the real backend).
  await page.getByRole("link", { name: "Library" }).click();
  await expect(page.getByRole("heading", { name: videoTitle })).toBeVisible();
});
