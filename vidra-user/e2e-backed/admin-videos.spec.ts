import { expect, test } from "@playwright/test";

import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  adminToken,
  blockedVideos,
  seedPublishedChannel,
  videoIsPublic,
} from "./fixtures";

// Proves the admin videos-overview block/unblock round trip against a real
// vidra-core + PostgreSQL: the deterministic admin browses all videos, blocks a
// seeded video from the overview (it disappears from public surfaces and enters
// the block-list), then unblocks it (it returns). DB-confirmed via the block-list
// API and the public video-detail endpoint.
test("an admin blocks and unblocks a video from the videos overview", async ({ page, request }) => {
  const { videoId, videoTitle } = await seedPublishedChannel(request);
  const token = await adminToken(request);
  expect(await videoIsPublic(request, videoId)).toBe(true);

  // The deterministic admin logs in through the UI.
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Moderation → All videos, then filter to the seeded video by title.
  await page.getByRole("link", { name: "Moderation" }).click();
  await page.getByRole("link", { name: "All videos" }).click();
  await page.getByLabel("Search videos by title").fill(videoTitle);
  await page.getByRole("button", { name: "Search" }).click();

  const row = page.locator("article", { hasText: videoTitle });
  await expect(row).toBeVisible();
  await expect(row.getByRole("button", { name: "Block" })).toBeVisible();

  // Block it → the row flips to blocked.
  const blocked = page.waitForResponse(
    (r) => /\/admin\/videos\/[^/]+\/block$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await row.getByRole("button", { name: "Block" }).click();
  await blocked;
  await expect(row.getByText("blocked")).toBeVisible();
  await expect(row.getByRole("button", { name: "Unblock" })).toBeVisible();

  // Persisted: it's in the block-list and hidden from the public detail endpoint.
  expect((await blockedVideos(request, token)).some((v) => v.video_id === videoId)).toBe(true);
  expect(await videoIsPublic(request, videoId)).toBe(false);

  // Unblock it → the row flips back and the video is public again.
  const unblocked = page.waitForResponse(
    (r) => /\/admin\/videos\/[^/]+\/block$/.test(r.url()) && r.request().method() === "DELETE" && r.ok(),
  );
  await row.getByRole("button", { name: "Unblock" }).click();
  await unblocked;
  await expect(row.getByRole("button", { name: "Block" })).toBeVisible();

  expect((await blockedVideos(request, token)).some((v) => v.video_id === videoId)).toBe(false);
  expect(await videoIsPublic(request, videoId)).toBe(true);
});
