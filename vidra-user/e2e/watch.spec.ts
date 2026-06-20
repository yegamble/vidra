import { expect, test } from "@playwright/test";

// Route-mock the detail endpoint (a real backend is not running in `npm run ci`).
// The <video> preload would hit the original stream — abort it so the test stays
// hermetic; we only assert the element's src, not playback.
const DETAIL_OK = /\/api\/v1\/videos\/v1$/;
const ORIGINAL = /\/api\/v1\/videos\/v1\/original/;

test("plays a video and shows its metadata", async ({ page }) => {
  await page.route(DETAIL_OK, (route) =>
    route.fulfill({
      json: {
        id: "v1",
        channel_id: "c1",
        title: "Watch Me",
        description: "A nice clip.",
        privacy: "public",
        state: "published",
        created_at: new Date().toISOString(),
        views: 4200,
        has_thumbnail: false,
        duration_seconds: 83,
        width: 1280,
        height: 720,
      },
    }),
  );
  await page.route(ORIGINAL, (route) => route.abort());

  await page.goto("/videos/v1");

  await expect(page.getByRole("heading", { name: "Watch Me" })).toBeVisible();
  await expect(page.getByText("4.2K views")).toBeVisible();
  await expect(page.getByText("1:23")).toBeVisible();
  await expect(page.getByText("1280×720")).toBeVisible();
  await expect(page.getByText("A nice clip.")).toBeVisible();

  const src = await page.locator("video").getAttribute("src");
  expect(src).toBe("http://localhost:8080/api/v1/videos/v1/original");
});

test("shows a not-found state for a missing video", async ({ page }) => {
  await page.route(/\/api\/v1\/videos\/missing$/, (route) =>
    route.fulfill({
      status: 404,
      json: { error: { code: "not_found", message: "video not found" } },
    }),
  );
  await page.goto("/videos/missing");
  await expect(page.getByText("Video not found")).toBeVisible();
});
