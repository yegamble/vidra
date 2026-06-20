import { expect, test } from "@playwright/test";

const CHANNEL = /\/api\/v1\/channels\/ada$/;
const CHANNEL_VIDEOS = /\/api\/v1\/channels\/ada\/videos$/;

const channel = {
  id: "ch1",
  owner_id: "u1",
  handle: "ada",
  display_name: "Ada Makes",
  description: "Cool videos about making things.",
  follower_count: 1500,
  created_at: new Date().toISOString(),
};

function video(id: string, title: string) {
  return {
    id,
    channel_id: "ch1",
    title,
    description: "",
    privacy: "public",
    state: "published",
    created_at: new Date().toISOString(),
    views: 10,
    has_thumbnail: false,
  };
}

test("shows the channel header and its videos", async ({ page }) => {
  await page.route(CHANNEL, (route) => route.fulfill({ json: channel }));
  await page.route(CHANNEL_VIDEOS, (route) =>
    route.fulfill({ json: { videos: [video("v1", "Building a Desk")] } }),
  );

  await page.goto("/channels/ada");

  await expect(page.getByRole("heading", { name: "Ada Makes" })).toBeVisible();
  await expect(page.getByText("@ada")).toBeVisible();
  await expect(page.getByText("1.5K followers")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Building a Desk" })).toBeVisible();
});

test("shows a not-found state for a missing channel", async ({ page }) => {
  const notFound = {
    status: 404,
    json: { error: { code: "not_found", message: "channel not found" } },
  };
  await page.route(CHANNEL, (route) => route.fulfill(notFound));
  await page.route(CHANNEL_VIDEOS, (route) => route.fulfill(notFound));

  await page.goto("/channels/ada");
  await expect(page.getByText("Channel not found")).toBeVisible();
});
