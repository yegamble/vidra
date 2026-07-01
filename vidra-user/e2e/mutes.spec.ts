import { expect, test, type Page } from "@playwright/test";

// Mocked account-mute coverage (a real backend is not running in `npm run ci`; the
// persistence round-trip + hiding effect are proven in e2e-backed/mutes.spec.ts).
const DETAIL = /\/api\/v1\/videos\/v1$/;
const ORIGINAL = /\/api\/v1\/videos\/v1\/original/;
const COMMENTS = /\/api\/v1\/videos\/v1\/comments/;
const RATING = /\/api\/v1\/videos\/v1\/rating/;
const SAVED = /\/api\/v1\/me\/saved(\?|$)/;
const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const MUTE_ONE = /\/api\/v1\/me\/mutes\/accounts\/[^/]+$/;
const MUTES_LIST = /\/api\/v1\/me\/mutes\/accounts(\?|$)/;
const NO_RATING = { like_count: 0, dislike_count: 0, my_rating: null };

const detail = {
  id: "v1",
  channel_id: "c1",
  title: "Watch Me",
  description: "",
  privacy: "public",
  state: "published",
  created_at: new Date().toISOString(),
  views: 1,
  has_thumbnail: false,
};

const session = {
  token: "acc",
  refresh_token: "ref",
  token_type: "Bearer",
  expires_in: 900,
  user: {
    id: "u-ada",
    username: "ada",
    email: "ada@example.test",
    role: "user",
    email_verified: false,
    display_name: "Ada Makes",
    bio: "",
    created_at: new Date().toISOString(),
  },
};

function comment(id: string, body: string, authorId: string, username: string, display: string) {
  return {
    id,
    video_id: "v1",
    body,
    author_id: authorId,
    author_username: username,
    author_display_name: display,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

async function signIn(page: Page) {
  await page.route(LOGIN, (route) => route.fulfill({ json: session }));
  await page.route(FEED, (route) =>
    route.fulfill({ json: { videos: [detail], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.goto("/login");
  await page.getByLabel("Email").fill("ada@example.test");
  await page.getByLabel("Password").fill("supersecret");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

test("muting a comment's author hides that account's comments", async ({ page }) => {
  await signIn(page);

  await page.route(DETAIL, (route) => route.fulfill({ json: detail }));
  await page.route(ORIGINAL, (route) => route.abort());
  await page.route(COMMENTS, (route) =>
    route.fulfill({
      json: {
        comments: [
          comment("cb", "spam from bob", "u-bob", "bob", "Bob Jones"),
          comment("cc", "hi from charlie", "u-charlie", "charlie", "Charlie"),
        ],
        limit: 20,
        offset: 0,
      },
    }),
  );
  await page.route(RATING, (route) => route.fulfill({ json: NO_RATING }));
  await page.route(SAVED, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );

  let mutedId: string | null = null;
  await page.route(MUTE_ONE, (route) => {
    if (route.request().method() === "POST") {
      mutedId = route.request().url().match(/\/accounts\/([^/]+)$/)?.[1] ?? null;
      return route.fulfill({ status: 204, body: "" });
    }
    return route.continue();
  });

  // Reach the watch page via the home feed card (keeps the in-memory session).
  await page.getByRole("heading", { name: "Watch Me" }).click();
  await expect(page.getByText("spam from bob")).toBeVisible();
  await expect(page.getByText("hi from charlie")).toBeVisible();

  // Mute bob (from his comment). His comment disappears; charlie's stays.
  const muted = page.waitForResponse(
    (r) => MUTE_ONE.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await page
    .locator("li", { hasText: "spam from bob" })
    .getByRole("button", { name: "Mute" })
    .click();
  await muted;

  await expect(page.getByText("spam from bob")).toHaveCount(0);
  await expect(page.getByText("hi from charlie")).toBeVisible();
  expect(mutedId).toBe("u-bob");
});

test("the muted-accounts page lists muted accounts and unmutes them", async ({ page }) => {
  await signIn(page);

  await page.route(MUTES_LIST, (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        json: {
          accounts: [
            { user_id: "u-bob", username: "bob", display_name: "Bob Jones", muted_at: new Date().toISOString() },
          ],
          limit: 100,
          offset: 0,
        },
      });
    }
    return route.continue();
  });
  await page.route(MUTE_ONE, (route) =>
    route.request().method() === "DELETE" ? route.fulfill({ status: 204, body: "" }) : route.continue(),
  );

  // Settings → Muted accounts (client-side nav keeps the session).
  await page.getByRole("link", { name: "ada" }).click();
  await page.getByRole("link", { name: "Manage" }).click();
  await expect(page.getByText("Bob Jones")).toBeVisible();
  await expect(page.getByText("@bob")).toBeVisible();

  const unmuted = page.waitForResponse(
    (r) => MUTE_ONE.test(r.url()) && r.request().method() === "DELETE" && r.ok(),
  );
  await page.getByRole("button", { name: "Unmute" }).click();
  await unmuted;

  await expect(page.getByText("Bob Jones")).toHaveCount(0);
  await expect(page.getByText("No muted accounts")).toBeVisible();
});
