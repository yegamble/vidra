import { expect, test } from "@playwright/test";

import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  registerUser,
  seedComment,
  seedPublishedChannel,
  uniqueId,
  videoComments,
} from "./fixtures";

// Proves the comments-moderation round trip against a real vidra-core + PostgreSQL:
// a moderator deletes a seeded comment from the admin comments overview, and it is
// gone from both the overview AND the video's public comment list (DB-confirmed via
// the public comments read).
test("a moderator deletes a comment from the overview and it is gone everywhere", async ({ page, request }) => {
  const { videoId } = await seedPublishedChannel(request);
  const commenter = await registerUser(request, "cmt");
  const body = `mod-me-${uniqueId()}`;
  await seedComment(request, videoId, commenter.token, body);

  // Sanity: the comment is on the video's public list.
  expect((await videoComments(request, videoId)).some((c) => c.body === body)).toBe(true);

  // The deterministic admin logs in through the UI.
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Moderation → Comments, then filter to the seeded comment by text.
  await page.getByRole("link", { name: "Moderation" }).click();
  await page.getByRole("link", { name: "Comments" }).click();
  await page.getByLabel("Search comments").fill(body);
  await page.getByRole("button", { name: "Search" }).click();

  const row = page.locator("article", { hasText: body });
  await expect(row).toBeVisible();

  // Delete it (two-step confirm).
  await row.getByRole("button", { name: "Delete" }).click();
  const deleted = page.waitForResponse(
    (r) => /\/api\/v1\/comments\/[^/]+$/.test(r.url()) && r.request().method() === "DELETE" && r.ok(),
  );
  await row.getByRole("button", { name: "Confirm delete" }).click();
  await deleted;

  // Gone from the overview…
  await expect(page.locator("article", { hasText: body })).toHaveCount(0);

  // …and gone from the video's public comment list (the DB row was deleted).
  expect((await videoComments(request, videoId)).some((c) => c.body === body)).toBe(false);
});
