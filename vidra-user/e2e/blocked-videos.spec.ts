import { expect, test, type Page } from "@playwright/test";

// Mocked block-list coverage (a real backend is not running in `npm run ci`; the
// persistence round-trip is proven in e2e-backed/blocked-videos.spec.ts).
const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const UNREAD = /\/api\/v1\/me\/notifications\/unread-count$/;
const BLOCKED = /\/api\/v1\/admin\/videos\/blocked(\?|$)/;
const UNBLOCK = /\/api\/v1\/admin\/videos\/[^/]+\/block$/;

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

function blocked(id: string, title: string) {
  return {
    video_id: id,
    title,
    privacy: "public",
    state: "published",
    channel_handle: "ada",
    channel_display_name: "Ada Makes",
    reason: `reason-${id}`,
    blocked_by: "e2eadmin",
    blocked_at: new Date().toISOString(),
  };
}

async function signIn(page: Page, role: Role) {
  await page.route(LOGIN, (route) => route.fulfill({ json: session(role) }));
  await page.route(FEED, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.route(UNREAD, (route) => route.fulfill({ json: { unread_count: 0 } }));
  await page.goto("/login");
  await page.getByLabel("Email").fill("mod@example.test");
  await page.getByLabel("Password").fill("supersecret");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

test("anonymous viewers are gated out of the block-list", async ({ page }) => {
  let fetched = false;
  await page.route(BLOCKED, (route) => {
    fetched = true;
    return route.fulfill({ json: { videos: [], limit: 20, offset: 0 } });
  });
  await page.goto("/moderation/blocked");
  await expect(page.getByText("Moderators only")).toBeVisible();
  expect(fetched).toBe(false);
});

test("an admin sees the blocked-video list via the moderation tabs", async ({ page }) => {
  await signIn(page, "admin");
  await page.route(BLOCKED, (route) =>
    route.fulfill({
      json: { videos: [blocked("v1", "Bad clip"), blocked("v2", "Worse clip")], limit: 100, offset: 0 },
    }),
  );

  await page.getByRole("link", { name: "Moderation" }).click();
  await page.getByRole("link", { name: "Blocked videos" }).click();

  await expect(page.getByRole("link", { name: "Bad clip" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Worse clip" })).toBeVisible();
  await expect(page.getByText("Reason: reason-v1")).toBeVisible();
  await expect(page.getByText("by e2eadmin").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Unblock" })).toHaveCount(2);
});

test("unblocking a video removes it from the list", async ({ page }) => {
  await signIn(page, "admin");
  await page.route(BLOCKED, (route) =>
    route.fulfill({ json: { videos: [blocked("v1", "Bad clip")], limit: 100, offset: 0 } }),
  );
  await page.route(UNBLOCK, (route) => route.fulfill({ status: 204, body: "" }));

  await page.getByRole("link", { name: "Moderation" }).click();
  await page.getByRole("link", { name: "Blocked videos" }).click();
  await expect(page.getByRole("link", { name: "Bad clip" })).toBeVisible();

  const unblocked = page.waitForResponse(
    (r) => UNBLOCK.test(r.url()) && r.request().method() === "DELETE" && r.ok(),
  );
  await page.getByRole("button", { name: "Unblock" }).click();
  await unblocked;

  await expect(page.getByRole("link", { name: "Bad clip" })).toHaveCount(0);
  await expect(page.getByText("No blocked videos")).toBeVisible();
});
