import { expect, test, type Page } from "@playwright/test";

// Mocked save/library coverage (a real backend is not running in `npm run ci`;
// the persistence round-trip is proven in e2e-backed/save.spec.ts).
const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const SAVED = /\/api\/v1\/me\/saved(\?|$)/;
const DETAIL = /\/api\/v1\/videos\/v1$/;
const ORIGINAL = /\/api\/v1\/videos\/v1\/original/;
const COMMENTS = /\/api\/v1\/videos\/v1\/comments/;
const RATING = /\/api\/v1\/videos\/v1\/rating/;
const SAVE = /\/api\/v1\/videos\/v1\/save/;

function video(id: string, title: string) {
  return {
    id,
    channel_id: "c1",
    title,
    description: "",
    privacy: "public",
    state: "published",
    created_at: new Date().toISOString(),
    views: 1,
    has_thumbnail: false,
  };
}

const detail = video("v1", "Watch Me");

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

test("the library prompts anonymous viewers to sign in", async ({ page }) => {
  await page.goto("/library");
  await expect(page.getByText("Sign in to see your library")).toBeVisible();
});

test("the library lists saved videos", async ({ page }) => {
  await signIn(page);
  await page.route(SAVED, (route) =>
    route.fulfill({
      json: { videos: [video("s1", "Saved Clip")], sort: "recent", limit: 20, offset: 0 },
    }),
  );
  await page.getByRole("link", { name: "Library" }).click();
  await expect(page.getByRole("heading", { name: "Saved Clip" })).toBeVisible();
});

test("an authenticated viewer can save a video from the watch page", async ({ page }) => {
  await signIn(page);
  await page.route(DETAIL, (route) => route.fulfill({ json: detail }));
  await page.route(ORIGINAL, (route) => route.abort());
  await page.route(COMMENTS, (route) => route.fulfill({ json: { comments: [], limit: 20, offset: 0 } }));
  await page.route(RATING, (route) =>
    route.fulfill({ json: { like_count: 0, dislike_count: 0, my_rating: null } }),
  );
  // Not saved initially.
  await page.route(SAVED, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.route(SAVE, (route) => route.fulfill({ status: 204, body: "" }));

  await page.getByRole("heading", { name: "Watch Me" }).click();
  const save = page.getByRole("button", { name: "Save", exact: true });
  await expect(save).toBeEnabled();
  await save.click();
  await expect(page.getByRole("button", { name: "Saved", exact: true })).toBeVisible();
});
