import { expect, test } from "@playwright/test";

import { TINY_MP4_BASE64, captions, channelVideos, uniqueId } from "./fixtures";

const VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n";

// Proves the studio caption round trip against a real vidra-core + PostgreSQL: a
// creator publishes a video, uploads a WebVTT caption from the video's edit
// surface, and it persists (visible via the public captions API); removing it
// deletes it.
test("a creator uploads and removes a caption in the studio", async ({ page, request }) => {
  const id = uniqueId();
  const handle = `ch${id}`;
  const channelName = `Channel ${id}`;
  const videoTitle = `Captioned clip ${id}`;

  // Sign up, create a channel, and publish a video (the only way to own one).
  await page.goto("/signup");
  await page.getByLabel("Username").fill(`fan${id}`);
  await page.getByLabel("Email").fill(`e2e-fan-${id}@example.test`);
  await page.getByLabel("Password").fill("supersecret-e2e");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.getByRole("link", { name: "Studio", exact: true }).click();
  await page.getByLabel("Channel handle").fill(handle);
  await page.getByLabel("Channel display name").fill(channelName);
  const channelCreated = page.waitForResponse(
    (r) => /\/api\/v1\/channels$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await page.getByRole("button", { name: "Create channel" }).click();
  await channelCreated;

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

  // Open the video's edit surface (the captions manager lives there).
  await page.getByRole("button", { name: "Refresh" }).click();
  const row = page.getByRole("listitem").filter({ hasText: videoTitle });
  await row.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByText("No captions yet.")).toBeVisible();

  // Upload an English caption.
  await page.getByLabel("Caption language").fill("en");
  await page.getByLabel("Caption label").fill("English");
  await page.getByLabel("Caption file").setInputFiles({
    name: "cap.vtt",
    mimeType: "text/vtt",
    buffer: Buffer.from(VTT),
  });
  const capUploaded = page.waitForResponse(
    (r) => /\/videos\/[^/]+\/captions$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await page.getByRole("button", { name: "Upload" }).click();
  await capUploaded;
  await expect(page.getByText("English")).toBeVisible();

  // Persisted: the public captions API shows the track.
  const videoId = (await channelVideos(request, handle)).find((v) => v.title === videoTitle)!.id;
  expect((await captions(request, videoId)).some((c) => c.language === "en")).toBe(true);

  // Remove it → gone from the UI and the API.
  const capRemoved = page.waitForResponse(
    (r) => /\/videos\/[^/]+\/captions\/[^/]+$/.test(r.url()) && r.request().method() === "DELETE" && r.ok(),
  );
  await page.getByRole("button", { name: "Remove en caption" }).click();
  await capRemoved;
  await expect(page.getByText("No captions yet.")).toBeVisible();
  expect((await captions(request, videoId)).some((c) => c.language === "en")).toBe(false);
});
