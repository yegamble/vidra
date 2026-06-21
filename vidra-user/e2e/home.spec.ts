import { expect, test } from "@playwright/test";

// The feed loads client-side, so we route-mock the backend call (a real backend
// is not running in `npm run ci`). Match the feed endpoint but not its subpaths
// (/videos/search, /videos/{id}).
const FEED_URL = /\/api\/v1\/videos(\?|$)/;

function video(id: string, title: string, views: number) {
  return {
    id,
    channel_id: "c1",
    title,
    description: "",
    privacy: "public",
    state: "published",
    created_at: new Date().toISOString(),
    views,
    has_thumbnail: false,
    channel_handle: "ada",
    channel_display_name: "Ada Makes",
  };
}

test("header brand is always present", async ({ page }) => {
  await page.route(FEED_URL, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Vidra" })).toBeVisible();
});

test("renders feed cards from the API", async ({ page }) => {
  await page.route(FEED_URL, (route) =>
    route.fulfill({
      json: {
        videos: [video("v1", "First Test Video", 1500), video("v2", "Second Test Video", 0)],
        sort: "recent",
        limit: 20,
        offset: 0,
      },
    }),
  );
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "First Test Video" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Second Test Video" })).toBeVisible();
  await expect(page.getByText("1.5K views")).toBeVisible();
  // Each card links to its channel by handle and shows the channel name.
  const channelLinks = page.getByRole("link", { name: "Ada Makes" });
  await expect(channelLinks.first()).toHaveAttribute("href", "/channels/ada");
  await expect(channelLinks).toHaveCount(2);
});

test("shows the empty state when there are no videos", async ({ page }) => {
  await page.route(FEED_URL, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.goto("/");
  await expect(page.getByText("No videos yet")).toBeVisible();
});

test("shows the error state when the feed fails", async ({ page }) => {
  await page.route(FEED_URL, (route) =>
    route.fulfill({
      status: 500,
      json: { error: { code: "internal", message: "boom" } },
    }),
  );
  await page.goto("/");
  await expect(page.getByText("Something went wrong")).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
});
