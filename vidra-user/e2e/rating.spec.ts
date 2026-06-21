import { expect, test } from "@playwright/test";

// Mocked rating coverage (a real backend is not running in `npm run ci`; the
// persistence round-trip is proven in e2e-backed/rating.spec.ts).
const DETAIL = /\/api\/v1\/videos\/v1$/;
const ORIGINAL = /\/api\/v1\/videos\/v1\/original/;
const COMMENTS = /\/api\/v1\/videos\/v1\/comments/;
const RATING = /\/api\/v1\/videos\/v1\/rating/;
const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const NO_COMMENTS = { comments: [], limit: 20, offset: 0 };

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

test("shows counts and prompts anonymous viewers to sign in to rate", async ({ page }) => {
  await page.route(DETAIL, (route) => route.fulfill({ json: detail }));
  await page.route(ORIGINAL, (route) => route.abort());
  await page.route(COMMENTS, (route) => route.fulfill({ json: NO_COMMENTS }));
  await page.route(RATING, (route) =>
    route.fulfill({ json: { like_count: 3, dislike_count: 1, my_rating: null } }),
  );

  await page.goto("/videos/v1");

  await expect(page.getByRole("button", { name: "Like", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Dislike", exact: true })).toBeDisabled();
  await expect(page.getByText("Sign in to rate")).toBeVisible();
});

test("an authenticated viewer can like a video", async ({ page }) => {
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
  await page.route(COMMENTS, (route) => route.fulfill({ json: NO_COMMENTS }));
  await page.route(RATING, (route) => {
    if (route.request().method() === "PUT") {
      void route.fulfill({ json: { like_count: 1, dislike_count: 0, my_rating: "like" } });
    } else {
      void route.fulfill({ json: { like_count: 0, dislike_count: 0, my_rating: null } });
    }
  });

  await page.getByRole("heading", { name: "Watch Me" }).click();
  const like = page.getByRole("button", { name: "Like", exact: true });
  await expect(like).toHaveAttribute("aria-pressed", "false");

  await like.click();
  await expect(like).toHaveAttribute("aria-pressed", "true");
});
