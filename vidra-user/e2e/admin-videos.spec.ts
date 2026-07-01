import { expect, test, type Page } from "@playwright/test";

// Mocked admin videos-overview coverage (a real backend is not running in
// `npm run ci`; the persistence round-trip is proven in e2e-backed/admin-videos.spec.ts).
const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const UNREAD = /\/api\/v1\/me\/notifications\/unread-count$/;
const REPORTS = /\/api\/v1\/admin\/reports(\?|$)/;
const ADMIN_VIDEOS = /\/api\/v1\/admin\/videos(\?|$)/;
const BLOCK_ONE = /\/api\/v1\/admin\/videos\/[^/]+\/block$/;

type Role = "user" | "moderator" | "admin";

function session(role: Role) {
  return {
    token: "acc",
    refresh_token: "ref",
    token_type: "Bearer",
    expires_in: 900,
    user: {
      id: "u1",
      username: "mod",
      email: "mod@example.test",
      role,
      email_verified: false,
      display_name: "Mod",
      bio: "",
      created_at: new Date().toISOString(),
    },
  };
}

function adminVideo(id: string, title: string, blocked = false, privacy = "public", state = "published") {
  return {
    id,
    title,
    privacy,
    state,
    channel_handle: "ada",
    channel_display_name: "Ada Makes",
    views: 3,
    created_at: new Date().toISOString(),
    blocked,
  };
}

async function signIn(page: Page, role: Role) {
  await page.route(LOGIN, (route) => route.fulfill({ json: session(role) }));
  await page.route(FEED, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.route(UNREAD, (route) => route.fulfill({ json: { unread_count: 0 } }));
  await page.route(REPORTS, (route) => route.fulfill({ json: { reports: [], limit: 20, offset: 0 } }));
  await page.goto("/login");
  await page.getByLabel("Email").fill("mod@example.test");
  await page.getByLabel("Password").fill("supersecret");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

test("anonymous viewers are gated out of the admin videos overview", async ({ page }) => {
  let fetched = false;
  await page.route(ADMIN_VIDEOS, (route) => {
    fetched = true;
    return route.fulfill({ json: { videos: [], limit: 20, offset: 0 } });
  });
  await page.goto("/moderation/videos");
  await expect(page.getByText("Moderators only")).toBeVisible();
  expect(fetched).toBe(false);
});

test("an admin browses all videos and blocks one from the overview", async ({ page }) => {
  await signIn(page, "admin");
  await page.route(ADMIN_VIDEOS, (route) =>
    route.fulfill({
      json: {
        videos: [adminVideo("v1", "Fresh clip"), adminVideo("v2", "Bad clip", true)],
        limit: 100,
        offset: 0,
      },
    }),
  );
  await page.route(BLOCK_ONE, (route) =>
    route.request().method() === "POST" ? route.fulfill({ status: 204, body: "" }) : route.continue(),
  );

  // Moderation → All videos (client-side nav keeps the in-memory session).
  await page.getByRole("link", { name: "Moderation" }).click();
  await page.getByRole("link", { name: "All videos" }).click();

  await expect(page.getByRole("link", { name: "Fresh clip" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Bad clip" })).toBeVisible();

  // The already-blocked video shows a "blocked" badge + an Unblock button.
  const blockedRow = page.locator("article", { hasText: "Bad clip" });
  await expect(blockedRow.getByText("blocked")).toBeVisible();
  await expect(blockedRow.getByRole("button", { name: "Unblock" })).toBeVisible();

  // Block the fresh clip.
  const freshRow = page.locator("article", { hasText: "Fresh clip" });
  const blocked = page.waitForResponse(
    (r) => BLOCK_ONE.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await freshRow.getByRole("button", { name: "Block" }).click();
  await blocked;

  // Its row now reflects the block.
  await expect(freshRow.getByText("blocked")).toBeVisible();
  await expect(freshRow.getByRole("button", { name: "Unblock" })).toBeVisible();
});
