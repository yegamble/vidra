import { expect, test } from "@playwright/test";

import { TINY_MP4_BASE64, uniqueId } from "./fixtures";

// Proves the publish round trip against a real vidra-core + PostgreSQL: a creator
// signs up, creates a channel, and uploads a video in the studio; the published
// video then appears on the public channel page after a fresh refetch. DB
// evidence (the videos + video_files rows) is captured separately via psql.
test("a creator can create a channel and publish a video", async ({ page }) => {
  const id = uniqueId();
  const handle = `ch${id}`;
  const channelName = `Channel ${id}`;
  const videoTitle = `Studio clip ${id}`;

  // Sign up (the session lives in memory).
  await page.goto("/signup");
  await page.getByLabel("Username").fill(`fan${id}`);
  await page.getByLabel("Email").fill(`e2e-fan-${id}@example.test`);
  await page.getByLabel("Password").fill("supersecret-e2e");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Open the studio (client-side nav) and create a channel.
  await page.getByRole("link", { name: "Studio" }).click();
  await page.getByLabel("Channel handle").fill(handle);
  await page.getByLabel("Channel display name").fill(channelName);
  const channelCreated = page.waitForResponse(
    (r) => /\/api\/v1\/channels$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await page.getByRole("button", { name: "Create channel" }).click();
  await channelCreated;

  // Upload a real (tiny) video; the backend's ffprobe accepts it and publishes it.
  await page.getByLabel("Video title").fill(videoTitle);
  await page.getByLabel("Video file").setInputFiles({
    name: "clip.mp4",
    mimeType: "video/mp4",
    buffer: Buffer.from(TINY_MP4_BASE64, "base64"),
  });
  const uploaded = page.waitForResponse(
    (r) => /\/videos\/[^/]+\/file$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await page.getByRole("button", { name: "Publish" }).click();
  await uploaded;
  await expect(page.getByText("Published!")).toBeVisible();

  // The published video appears on the public channel page (a fresh refetch).
  await page.getByRole("link", { name: new RegExp(channelName) }).first().click();
  await expect(page.getByRole("heading", { name: videoTitle })).toBeVisible();
});
