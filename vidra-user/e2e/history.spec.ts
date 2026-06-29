import { expect, test, type Page } from "@playwright/test";

// Mocked watch-history coverage (a real backend is not running in `npm run ci`;
// the persistence round-trip is proven in e2e-backed/history.spec.ts).
const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const HISTORY = /\/api\/v1\/me\/history$/;
const HISTORY_ENTRY = /\/api\/v1\/me\/history\/h1$/;
const DETAIL = /\/api\/v1\/videos\/v1$/;
const ORIGINAL = /\/api\/v1\/videos\/v1\/original/;
const COMMENTS = /\/api\/v1\/videos\/v1\/comments/;
const RATING = /\/api\/v1\/videos\/v1\/rating/;
const SAVED = /\/api\/v1\/me\/saved(\?|$)/;
const WATCH_PROGRESS = /\/api\/v1\/videos\/v1\/watch-progress$/;

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

function historyItem(id: string, title: string, position: number) {
  return { ...video(id, title), position_seconds: position, watched_at: new Date().toISOString() };
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

test("history prompts anonymous viewers to sign in", async ({ page }) => {
  await page.goto("/history");
  await expect(page.getByText("Sign in to see your history")).toBeVisible();
});

test("history lists watched videos with a resume label", async ({ page }) => {
  await signIn(page);
  await page.route(HISTORY, (route) =>
    route.fulfill({ json: { videos: [historyItem("h1", "Watched Clip", 95)], limit: 20, offset: 0 } }),
  );
  await page.getByRole("link", { name: "History" }).click();
  await expect(page.getByRole("heading", { name: "Watched Clip" })).toBeVisible();
  await expect(page.getByText("Resume at 1:35")).toBeVisible();
});

test("removing an entry takes it out of the history list", async ({ page }) => {
  await signIn(page);
  await page.route(HISTORY, (route) =>
    route.fulfill({ json: { videos: [historyItem("h1", "Watched Clip", 0)], limit: 20, offset: 0 } }),
  );
  await page.route(HISTORY_ENTRY, (route) => route.fulfill({ status: 204, body: "" }));
  await page.getByRole("link", { name: "History" }).click();
  await expect(page.getByRole("heading", { name: "Watched Clip" })).toBeVisible();
  await page.getByRole("button", { name: "Remove Watched Clip from history" }).click();
  await expect(page.getByRole("heading", { name: "Watched Clip" })).toBeHidden();
});

test("clearing history empties the list", async ({ page }) => {
  await signIn(page);
  await page.route(HISTORY, (route) =>
    route.fulfill({ json: { videos: [historyItem("h1", "Watched Clip", 0)], limit: 20, offset: 0 } }),
  );
  await page.route(/\/api\/v1\/me\/history$/, (route) => {
    if (route.request().method() === "DELETE") return route.fulfill({ status: 204, body: "" });
    return route.fulfill({ json: { videos: [historyItem("h1", "Watched Clip", 0)], limit: 20, offset: 0 } });
  });
  await page.getByRole("link", { name: "History" }).click();
  await expect(page.getByRole("heading", { name: "Watched Clip" })).toBeVisible();
  await page.getByRole("button", { name: "Clear all history" }).click();
  await expect(page.getByText("No watch history yet")).toBeVisible();
});

test("the watch page offers to resume from the saved position", async ({ page }) => {
  await signIn(page);
  await page.route(DETAIL, (route) => route.fulfill({ json: detail }));
  await page.route(ORIGINAL, (route) => route.abort());
  await page.route(COMMENTS, (route) => route.fulfill({ json: { comments: [], limit: 20, offset: 0 } }));
  await page.route(RATING, (route) =>
    route.fulfill({ json: { like_count: 0, dislike_count: 0, my_rating: null } }),
  );
  await page.route(SAVED, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.route(WATCH_PROGRESS, (route) => {
    if (route.request().method() === "PUT") return route.fulfill({ status: 204, body: "" });
    return route.fulfill({ json: { video_id: "v1", position_seconds: 95 } });
  });

  await page.getByRole("heading", { name: "Watch Me" }).click();
  const resume = page.getByRole("button", { name: "Resume from 1:35" });
  await expect(resume).toBeVisible();
  await resume.click();
  await expect(resume).toBeHidden();
});
