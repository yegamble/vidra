import { expect, test } from "@playwright/test";

// Mocked comments coverage (a real backend is not running in `npm run ci`; the
// persistence round-trip is proven separately in e2e-backed/comments.spec.ts).
const DETAIL = /\/api\/v1\/videos\/v1$/;
const ORIGINAL = /\/api\/v1\/videos\/v1\/original/;
const COMMENTS = /\/api\/v1\/videos\/v1\/comments/;
const RATING = /\/api\/v1\/videos\/v1\/rating/;
const NO_RATING = { like_count: 0, dislike_count: 0, my_rating: null };
const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;

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
    id: "u1",
    username: "ada",
    email: "ada@example.test",
    role: "user",
    email_verified: false,
    display_name: "Ada Makes",
    bio: "",
    created_at: new Date().toISOString(),
  },
};

function comment(id: string, body: string, username = "bob", display = "Bob Jones") {
  return {
    id,
    video_id: "v1",
    body,
    author_username: username,
    author_display_name: display,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

test("shows a video's comments and prompts anonymous viewers to sign in", async ({ page }) => {
  await page.route(DETAIL, (route) => route.fulfill({ json: detail }));
  await page.route(ORIGINAL, (route) => route.abort());
  await page.route(COMMENTS, (route) =>
    route.fulfill({
      json: { comments: [comment("c1", "First!"), comment("c2", "Nice one")], limit: 20, offset: 0 },
    }),
  );
  await page.route(RATING, (route) => route.fulfill({ json: NO_RATING }));

  await page.goto("/videos/v1");

  await expect(page.getByRole("heading", { name: "Comments (2)" })).toBeVisible();
  await expect(page.getByText("First!")).toBeVisible();
  await expect(page.getByText("Nice one")).toBeVisible();
  await expect(page.getByText("Bob Jones").first()).toBeVisible();
  // Anonymous viewers cannot post.
  await expect(page.getByText("to leave a comment")).toBeVisible();
  await expect(page.getByLabel("Add a comment")).toHaveCount(0);
});

test("an authenticated viewer can post a comment", async ({ page }) => {
  // Sign in; the session lives in memory, so reach the watch page via client-side nav.
  await page.route(LOGIN, (route) => route.fulfill({ json: session }));
  await page.route(FEED, (route) =>
    route.fulfill({ json: { videos: [detail], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.goto("/login");
  await page.getByLabel("Email").fill("ada@example.test");
  await page.getByLabel("Password").fill("supersecret");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.route(DETAIL, (route) => route.fulfill({ json: detail }));
  await page.route(ORIGINAL, (route) => route.abort());
  await page.route(COMMENTS, (route) => {
    if (route.request().method() === "POST") {
      void route.fulfill({ json: comment("new1", "Great video", "ada", "Ada Makes") });
    } else {
      void route.fulfill({ json: { comments: [], limit: 20, offset: 0 } });
    }
  });
  await page.route(RATING, (route) => route.fulfill({ json: NO_RATING }));
  await page.route(/\/api\/v1\/me\/saved(\?|$)/, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );

  // Navigate to the watch page from the home feed card (keeps the session).
  await page.getByRole("heading", { name: "Watch Me" }).click();
  await expect(page.getByRole("heading", { name: "Comments (0)" })).toBeVisible();

  await page.getByLabel("Add a comment").fill("Great video");
  await page.getByRole("button", { name: "Post" }).click();

  await expect(page.getByText("Great video")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Comments (1)" })).toBeVisible();
});
