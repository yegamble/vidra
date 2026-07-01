import { expect, test, type Page } from "@playwright/test";

// Mocked comments-moderation coverage (a real backend is not running in
// `npm run ci`; the persistence round-trip is proven in e2e-backed/admin-comments.spec.ts).
const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const UNREAD = /\/api\/v1\/me\/notifications\/unread-count$/;
const REPORTS = /\/api\/v1\/admin\/reports(\?|$)/;
const ADMIN_COMMENTS = /\/api\/v1\/admin\/comments(\?|$)/;
const DELETE_COMMENT = /\/api\/v1\/comments\/[^/]+$/;

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

function adminComment(id: string, body: string, author = "bob") {
  return {
    id,
    video_id: "v1",
    video_title: "Watch Me",
    body,
    author_username: author,
    author_display_name: author,
    created_at: new Date().toISOString(),
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

test("anonymous viewers are gated out of the comments overview", async ({ page }) => {
  let fetched = false;
  await page.route(ADMIN_COMMENTS, (route) => {
    fetched = true;
    return route.fulfill({ json: { comments: [], limit: 20, offset: 0 } });
  });
  await page.goto("/moderation/comments");
  await expect(page.getByText("Moderators only")).toBeVisible();
  expect(fetched).toBe(false);
});

test("an admin browses comments and deletes one from the overview", async ({ page }) => {
  await signIn(page, "admin");
  await page.route(ADMIN_COMMENTS, (route) =>
    route.fulfill({
      json: {
        comments: [adminComment("c1", "spam here"), adminComment("c2", "nice video", "ada")],
        limit: 100,
        offset: 0,
      },
    }),
  );
  let deletedId: string | null = null;
  await page.route(DELETE_COMMENT, (route) => {
    if (route.request().method() === "DELETE") {
      deletedId = route.request().url().match(/\/comments\/([^/]+)$/)?.[1] ?? null;
      return route.fulfill({ status: 204, body: "" });
    }
    return route.continue();
  });

  // Moderation → Comments (client-side nav keeps the in-memory session).
  await page.getByRole("link", { name: "Moderation" }).click();
  await page.getByRole("link", { name: "Comments" }).click();

  await expect(page.getByText("spam here")).toBeVisible();
  await expect(page.getByText("nice video")).toBeVisible();
  await expect(page.getByRole("link", { name: "Watch Me" }).first()).toBeVisible();

  // Delete the spam comment (two-step confirm).
  const spamRow = page.locator("article", { hasText: "spam here" });
  await spamRow.getByRole("button", { name: "Delete" }).click();
  const deleted = page.waitForResponse(
    (r) => DELETE_COMMENT.test(r.url()) && r.request().method() === "DELETE" && r.ok(),
  );
  await spamRow.getByRole("button", { name: "Confirm delete" }).click();
  await deleted;

  await expect(page.getByText("spam here")).toHaveCount(0);
  await expect(page.getByText("nice video")).toBeVisible();
  expect(deletedId).toBe("c1");
});
