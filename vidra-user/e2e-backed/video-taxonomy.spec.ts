import { expect, test } from "@playwright/test";

import { TINY_MP4_BASE64, channelVideos, uniqueId, videoDetail } from "./fixtures";

// Proves the video-taxonomy round trip against a real vidra-core + PostgreSQL:
// a creator picks category/language/license from the studio dropdowns (populated
// from the live GET /videos/config) when publishing, then edits them; both are
// confirmed persisted via the public video-detail API. The dropdowns only offer
// valid ids, so the values are validated server-side on the way in.
test("a creator sets and edits a video's category/language/license", async ({ page, request }) => {
  const id = uniqueId();
  const handle = `ch${id}`;
  const title = `Taxonomy clip ${id}`;

  await page.goto("/signup");
  await page.getByLabel("Username").fill(`fan${id}`);
  await page.getByLabel("Email").fill(`e2e-tax-${id}@example.test`);
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

  // Publish with category=Gaming(7), language=English(en), license=CC BY(1).
  await page.getByLabel("Video title").fill(title);
  await page.getByLabel("Video category").selectOption("7");
  await page.getByLabel("Video language").selectOption("en");
  await page.getByLabel("Video license").selectOption("1");
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

  // Persisted: the public detail API carries what we picked.
  const afterPublish = await videoDetail(request, videoId);
  expect(afterPublish).toMatchObject({ category: "7", language: "en", license: "1" });

  // Edit: change category -> Music(1) and language -> French(fr); license untouched.
  await page.getByRole("button", { name: "Refresh" }).click();
  const row = page.getByRole("listitem").filter({ hasText: title });
  await row.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByLabel("Edit category")).toHaveValue("7"); // pre-filled
  await page.getByLabel("Edit category").selectOption("1");
  await page.getByLabel("Edit language").selectOption("fr");
  const patched = page.waitForResponse(
    (r) => /\/videos\/[^/]+$/.test(r.url()) && r.request().method() === "PATCH" && r.ok(),
  );
  await page.getByRole("button", { name: "Save" }).click();
  await patched;

  // Persisted: the edit is reflected; the untouched license is preserved.
  const afterEdit = await videoDetail(request, videoId);
  expect(afterEdit).toMatchObject({ category: "1", language: "fr", license: "1" });
});
