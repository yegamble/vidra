import { expect, test } from "@playwright/test";

import { TINY_MP4_BASE64, channelVideos, uniqueId, videoDetail } from "./fixtures";

// Proves the video-description round trip against a real vidra-core + PostgreSQL:
// a creator publishes a video with a description and later edits it in the studio;
// both are confirmed persisted via the public video-detail API, and the final
// description renders on the watch page. All authed UI actions happen before the
// single hard navigation (which clears the in-memory session).
test("a creator sets and edits a video description", async ({ page, request }) => {
  const id = uniqueId();
  const handle = `ch${id}`;
  const title = `Described clip ${id}`;
  const description = `First description ${id}`;
  const newDescription = `Edited description ${id}`;

  // Sign up, create a channel, and publish a video WITH a description.
  await page.goto("/signup");
  await page.getByLabel("Username").fill(`fan${id}`);
  await page.getByLabel("Email").fill(`e2e-desc-${id}@example.test`);
  await page.getByLabel("Password").fill("supersecret-e2e");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.getByRole("link", { name: "Studio", exact: true }).click();
  await page.getByLabel("Channel handle").fill(handle);
  await page.getByLabel("Channel display name").fill(`Channel ${id}`);
  const channelCreated = page.waitForResponse(
    (r) => /\/api\/v1\/channels$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await page.getByRole("button", { name: "Create channel" }).click();
  await channelCreated;

  await page.getByLabel("Video title").fill(title);
  await page.getByLabel("Video description").fill(description);
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

  const videoId = (await channelVideos(request, handle)).find((v) => v.title === title)!.id;

  // Persisted: the public detail API carries the description we published.
  expect((await videoDetail(request, videoId)).description).toBe(description);

  // Edit the description in the studio (still signed in — no hard nav yet).
  await page.getByRole("button", { name: "Refresh" }).click();
  const row = page.getByRole("listitem").filter({ hasText: title });
  await row.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByLabel("Edit description")).toHaveValue(description);
  await page.getByLabel("Edit description").fill(newDescription);
  const patched = page.waitForResponse(
    (r) => /\/videos\/[^/]+$/.test(r.url()) && r.request().method() === "PATCH" && r.ok(),
  );
  await page.getByRole("button", { name: "Save" }).click();
  await patched;

  // Persisted: the edit is reflected in the public detail API.
  expect((await videoDetail(request, videoId)).description).toBe(newDescription);

  // Displayed: the watch page (a fresh load) shows the edited description.
  await page.goto(`/videos/${videoId}`);
  await expect(page.getByText(newDescription)).toBeVisible();
});
