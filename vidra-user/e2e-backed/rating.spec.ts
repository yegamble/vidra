import { expect, test } from "@playwright/test";

import { seedPublishedChannel, uniqueId, videoRating } from "./fixtures";

// Proves the like round trip against a real vidra-core + PostgreSQL: a viewer
// likes a video from the watch page UI, the button reflects it, and the like is
// confirmed persisted by reading the rating back through the API.
test("liking a video from the watch page persists it", async ({ page, request }) => {
  const { videoId, videoTitle } = await seedPublishedChannel(request);
  expect((await videoRating(request, videoId)).like_count).toBe(0);

  // A fresh viewer signs up (the session lives in memory).
  const id = uniqueId();
  await page.goto("/signup");
  await page.getByLabel("Username").fill(`fan${id}`);
  await page.getByLabel("Email").fill(`e2e-fan-${id}@example.test`);
  await page.getByLabel("Password").fill("supersecret-e2e");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Reach the seeded video's watch page from the home feed (client-side nav keeps
  // the session) and like it.
  await page.getByRole("heading", { name: videoTitle }).click();
  await expect(page.getByRole("heading", { level: 1, name: videoTitle })).toBeVisible();

  const like = page.getByRole("button", { name: "Like", exact: true });
  await expect(like).toHaveAttribute("aria-pressed", "false");
  await like.click();

  // The button reflects the like in the UI...
  await expect(like).toHaveAttribute("aria-pressed", "true");

  // ...and the like is persisted in the database (read back through the API).
  expect((await videoRating(request, videoId)).like_count).toBe(1);
});
