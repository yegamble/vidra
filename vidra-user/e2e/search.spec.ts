import { expect, test } from "@playwright/test";

const SEARCH = /\/api\/v1\/videos\/search/;
const FEED = /\/api\/v1\/videos(\?|$)/;

function video(id: string, title: string) {
  return {
    id,
    channel_id: "c1",
    title,
    description: "",
    privacy: "public",
    state: "published",
    created_at: new Date().toISOString(),
    views: 10,
    has_thumbnail: false,
  };
}

test("shows matching results for a query", async ({ page }) => {
  await page.route(SEARCH, (route) =>
    route.fulfill({ json: { query: "go", videos: [video("v1", "Go Basics")], limit: 20, offset: 0 } }),
  );
  await page.goto("/search?q=go");
  await expect(page.getByRole("heading", { name: "Go Basics" })).toBeVisible();
});

test("shows an empty state when nothing matches", async ({ page }) => {
  await page.route(SEARCH, (route) =>
    route.fulfill({ json: { query: "zzz", videos: [], limit: 20, offset: 0 } }),
  );
  await page.goto("/search?q=zzz");
  await expect(page.getByText("No results")).toBeVisible();
});

test("prompts for a term when the query is blank", async ({ page }) => {
  await page.goto("/search");
  await expect(page.getByText("Search for videos")).toBeVisible();
});

test("the header search box navigates to results", async ({ page }) => {
  await page.route(FEED, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.route(SEARCH, (route) =>
    route.fulfill({ json: { query: "go", videos: [video("v1", "Go Basics")], limit: 20, offset: 0 } }),
  );
  await page.goto("/");
  await page.getByLabel("Search videos").fill("go");
  await page.getByLabel("Search videos").press("Enter");
  await expect(page).toHaveURL(/\/search\?q=go/);
  await expect(page.getByRole("heading", { name: "Go Basics" })).toBeVisible();
});
