import { expect, test } from "@playwright/test";

import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  adminToken,
  blockVideo,
  blockedVideos,
  fileVideoReport,
  seedPublishedChannel,
  videoIsPublic,
  uniqueId,
} from "./fixtures";

// Proves the moderation unblock round trip against a real vidra-core + PostgreSQL:
// a video is published and blocked (seeded via the API), the deterministic admin
// logs in through the UI, sees it in the block-list, unblocks it, and a fresh
// refetch keeps it gone — proving the video_blocks row was deleted. DB evidence is
// asserted via the admin block-list API AND the now-public video detail endpoint.
test("an admin unblocks a video from the block-list and it persists", async ({ page, request }) => {
  // Seed a published video and block it via the API as the deterministic admin.
  const { videoId, videoTitle } = await seedPublishedChannel(request);
  const token = await adminToken(request);
  const reason = `blocked-${uniqueId()}`;
  await blockVideo(request, token, videoId, reason);

  // Sanity: it's in the block-list and hidden from the public detail endpoint.
  expect((await blockedVideos(request, token)).some((v) => v.video_id === videoId)).toBe(true);
  expect(await videoIsPublic(request, videoId)).toBe(false);

  // The deterministic admin logs in through the UI.
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Open Moderation → Blocked videos (client-side nav keeps the in-memory session).
  await page.getByRole("link", { name: "Moderation" }).click();
  await page.getByRole("link", { name: "Blocked videos" }).click();
  const row = page.locator("article", { hasText: videoTitle });
  await expect(row).toBeVisible();

  // Unblock it.
  const unblocked = page.waitForResponse(
    (r) => /\/admin\/videos\/[^/]+\/block$/.test(r.url()) && r.request().method() === "DELETE" && r.ok(),
  );
  await row.getByRole("button", { name: "Unblock" }).click();
  await unblocked;

  // It drops out of the list immediately…
  await expect(page.locator("article", { hasText: videoTitle })).toHaveCount(0);

  // …and stays out after a fresh refetch (tab away to Reports + back to Blocked videos).
  await page.getByRole("link", { name: "Reports" }).click();
  await page.getByRole("link", { name: "Blocked videos" }).click();
  await expect(page.locator("article", { hasText: videoTitle })).toHaveCount(0);

  // Persisted: the block-list no longer contains it AND the video is public again.
  expect((await blockedVideos(request, token)).some((v) => v.video_id === videoId)).toBe(false);
  expect(await videoIsPublic(request, videoId)).toBe(true);
});

// Proves the block round trip from the moderation report queue: a viewer reports a
// published video (seeded via the API), the deterministic admin logs in, opens the
// queue, and clicks "Block video" on the report card — the video is then hidden
// from public surfaces and present in the block-list (DB-confirmed via the admin
// block-list API + the now-404 public video detail).
test("an admin blocks a reported video from the moderation queue", async ({ page, request }) => {
  const { videoId } = await seedPublishedChannel(request);
  const reason = await fileVideoReport(request, videoId);
  const token = await adminToken(request);

  // Sanity: public and not blocked before the admin acts.
  expect(await videoIsPublic(request, videoId)).toBe(true);
  expect((await blockedVideos(request, token)).some((v) => v.video_id === videoId)).toBe(false);

  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.getByRole("link", { name: "Moderation" }).click();
  const row = page.locator("article", { hasText: reason });
  await expect(row).toBeVisible();

  const blocked = page.waitForResponse(
    (r) => /\/admin\/videos\/[^/]+\/block$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await row.getByRole("button", { name: "Block video" }).click();
  await blocked;
  await expect(row.getByText("Video blocked")).toBeVisible();

  // Persisted: the video is blocked (in the block-list) and hidden from the public.
  expect((await blockedVideos(request, token)).some((v) => v.video_id === videoId)).toBe(true);
  expect(await videoIsPublic(request, videoId)).toBe(false);
});
