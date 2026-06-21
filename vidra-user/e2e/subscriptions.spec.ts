import { expect, test, type Page } from "@playwright/test";

const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const SUBS = /\/api\/v1\/me\/subscriptions\/videos(\?|$)/;

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
    display_name: "",
    bio: "",
    created_at: new Date().toISOString(),
  },
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
    views: 3,
    has_thumbnail: false,
  };
}

async function signIn(page: Page) {
  await page.route(LOGIN, (route) => route.fulfill({ json: session }));
  await page.route(FEED, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.goto("/login");
  await page.getByLabel("Email").fill("ada@example.test");
  await page.getByLabel("Password").fill("supersecret");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

test("anonymous users are prompted to sign in", async ({ page }) => {
  await page.goto("/subscriptions");
  await expect(page.getByText("Sign in to see your subscriptions")).toBeVisible();
});

test("shows an empty state when there are no subscription videos", async ({ page }) => {
  await signIn(page);
  await page.route(SUBS, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );
  // Reach subscriptions via the header (client-side nav keeps the session).
  await page.getByRole("link", { name: "Subscriptions" }).click();
  await expect(page.getByText("No videos from your subscriptions yet")).toBeVisible();
});

test("lists videos from followed channels", async ({ page }) => {
  await signIn(page);
  await page.route(SUBS, (route) =>
    route.fulfill({
      json: { videos: [video("v1", "Followed Video")], sort: "recent", limit: 20, offset: 0 },
    }),
  );
  await page.getByRole("link", { name: "Subscriptions" }).click();
  await expect(page.getByRole("heading", { name: "Followed Video" })).toBeVisible();
});
