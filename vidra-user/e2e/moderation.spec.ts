import { expect, test, type Page } from "@playwright/test";

// Mocked moderation-queue coverage (a real backend is not running in `npm run ci`;
// the persistence round-trip is proven in e2e-backed/moderation.spec.ts).
const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const UNREAD = /\/api\/v1\/me\/notifications\/unread-count$/;
const REPORTS = /\/api\/v1\/admin\/reports(\?|$)/;
const RESOLVE = /\/api\/v1\/admin\/reports\/[^/]+\/resolve$/;

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

function videoReport(id: string, status: string) {
  return {
    id,
    target_type: "video",
    reason: `reason-${id}`,
    status,
    moderator_note: "",
    created_at: new Date().toISOString(),
    reporter: { username: "alice" },
    video_id: "v1",
    video_title: "Bad clip",
  };
}

function commentReport(id: string, status: string) {
  return {
    id,
    target_type: "comment",
    reason: `reason-${id}`,
    status,
    moderator_note: "",
    created_at: new Date().toISOString(),
    reporter: { username: "bob" },
    comment_id: "c1",
    comment_body: "nasty comment",
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

test("anonymous viewers are gated out of the moderation queue", async ({ page }) => {
  let fetched = false;
  await page.route(REPORTS, (route) => {
    fetched = true;
    return route.fulfill({ json: { reports: [], limit: 20, offset: 0 } });
  });
  await page.goto("/moderation");
  await expect(page.getByText("Moderators only")).toBeVisible();
  expect(fetched).toBe(false);
});

test("regular users do not see the Moderation nav entry", async ({ page }) => {
  await signIn(page, "user");
  await expect(page.getByRole("link", { name: "Moderation" })).toHaveCount(0);
});

test("an admin sees the open report queue", async ({ page }) => {
  await signIn(page, "admin");
  await page.route(REPORTS, (route) =>
    route.fulfill({
      json: { reports: [videoReport("r1", "open"), commentReport("r2", "open")], limit: 100, offset: 0 },
    }),
  );

  await page.getByRole("link", { name: "Moderation" }).click();
  await expect(page.getByRole("link", { name: "Bad clip" })).toBeVisible();
  await expect(page.getByText("nasty comment")).toBeVisible();
  await expect(page.getByText("by alice")).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept" })).toHaveCount(2);
});

test("accepting a report removes it from the open queue", async ({ page }) => {
  await signIn(page, "admin");
  await page.route(REPORTS, (route) =>
    route.fulfill({
      json: { reports: [videoReport("r1", "open"), commentReport("r2", "open")], limit: 100, offset: 0 },
    }),
  );
  await page.route(RESOLVE, (route) => route.fulfill({ status: 204, body: "" }));

  await page.getByRole("link", { name: "Moderation" }).click();
  await expect(page.getByRole("link", { name: "Bad clip" })).toBeVisible();

  const resolved = page.waitForResponse(
    (r) => RESOLVE.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await page.getByRole("button", { name: "Accept" }).first().click();
  await resolved;

  // The video report (r1) was open; resolving drops it from the open-only view.
  await expect(page.getByRole("link", { name: "Bad clip" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Accept" })).toHaveCount(1);
});

test("the All filter shows resolved reports without resolve actions", async ({ page }) => {
  await signIn(page, "admin");
  // open → only the still-open comment report; all → both (video already accepted).
  await page.route(REPORTS, (route) => {
    const openOnly = route.request().url().includes("status=open");
    const reports = openOnly
      ? [commentReport("r2", "open")]
      : [videoReport("r1", "accepted"), commentReport("r2", "open")];
    return route.fulfill({ json: { reports, limit: 100, offset: 0 } });
  });

  await page.getByRole("link", { name: "Moderation" }).click();
  await expect(page.getByText("nasty comment")).toBeVisible();
  await expect(page.getByRole("link", { name: "Bad clip" })).toHaveCount(0);

  await page.getByRole("button", { name: "All" }).click();
  await expect(page.getByRole("link", { name: "Bad clip" })).toBeVisible();
  await expect(page.getByText("accepted")).toBeVisible();
  // Only the still-open comment report keeps its resolve actions.
  await expect(page.getByRole("button", { name: "Accept" })).toHaveCount(1);
});
