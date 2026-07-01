import { expect, test } from "@playwright/test";

import { seedCaption, seedPublishedChannel } from "./fixtures";

// Proves the viewer-side caption path against a real vidra-core + PostgreSQL: a
// published video with an uploaded WebVTT caption exposes a <track> on the watch
// page. The player fetches the caption cross-origin (CORS) and serves it back
// through a same-origin blob URL, so this exercises the real fetch→blob→<track>
// path that native cross-origin <track> loading would otherwise block.
test("a viewer sees caption tracks on the watch page", async ({ page, request }) => {
  const { videoId, token } = await seedPublishedChannel(request);
  await seedCaption(request, videoId, token, "en", "English");

  await page.goto(`/videos/${videoId}`);

  const track = page.locator("video track");
  await expect(track).toHaveCount(1);
  await expect(track).toHaveAttribute("srclang", "en");
  await expect(track).toHaveAttribute("label", "English");
  await expect(track).toHaveAttribute("kind", "captions");
  // Served from a same-origin blob (the fetched VTT), not the cross-origin backend
  // URL — confirming the cross-origin fetch succeeded under the backend's CORS.
  expect(await track.getAttribute("src")).toMatch(/^blob:/);
});
