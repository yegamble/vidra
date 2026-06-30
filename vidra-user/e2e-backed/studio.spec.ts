import { expect, test } from "@playwright/test";

import { TINY_MP4_BASE64, channelVideos, uniqueId } from "./fixtures";

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
  await page.getByRole("link", { name: "Studio", exact: true }).click();
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

// Proves the edit + delete round trips against a real vidra-core + PostgreSQL: a
// creator edits their video's title in the studio "Your videos" list and then
// deletes it; both changes are confirmed persisted by reading the public channel
// video list back through the API.
test("a creator can edit and delete their video", async ({ page, request }) => {
  const id = uniqueId();
  const handle = `ch${id}`;
  const channelName = `Channel ${id}`;
  const videoTitle = `Editable clip ${id}`;
  const newTitle = `Edited clip ${id}`;

  // Sign up and create a channel + publish a video (the only way to own one as the
  // signed-in UI user).
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

  // Refresh "Your videos" to pick up the just-published video, then edit its title
  // (privacy stays public so the public read-back can see it). Scope to the list row
  // — the "Published!" message also links the video by its (old) title.
  await page.getByRole("button", { name: "Refresh" }).click();
  const row = page.getByRole("listitem").filter({ hasText: videoTitle });
  await expect(row.getByRole("link", { name: videoTitle })).toBeVisible();

  await row.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Edit title").fill(newTitle);
  const patched = page.waitForResponse(
    (r) => /\/videos\/[^/]+$/.test(r.url()) && r.request().method() === "PATCH" && r.ok(),
  );
  await page.getByRole("button", { name: "Save" }).click();
  await patched;
  const updatedRow = page.getByRole("listitem").filter({ hasText: newTitle });
  await expect(updatedRow.getByRole("link", { name: newTitle })).toBeVisible();

  // Persisted: the public channel list shows the new title (and not the old one).
  const afterEdit = await channelVideos(request, handle);
  expect(afterEdit.map((v) => v.title)).toContain(newTitle);
  expect(afterEdit.map((v) => v.title)).not.toContain(videoTitle);

  // Delete it.
  await updatedRow.getByRole("button", { name: "Delete" }).click();
  const deleted = page.waitForResponse(
    (r) => /\/videos\/[^/]+$/.test(r.url()) && r.request().method() === "DELETE" && r.ok(),
  );
  await page.getByRole("button", { name: "Confirm" }).click();
  await deleted;
  await expect(page.getByRole("listitem").filter({ hasText: newTitle })).toHaveCount(0);

  // Persisted: the public channel list no longer contains the video.
  const afterDelete = await channelVideos(request, handle);
  expect(afterDelete.map((v) => v.title)).not.toContain(newTitle);
});
