import { expect, test, type Page } from "@playwright/test";

// Mocked report coverage (a real backend is not running in `npm run ci`; the
// persistence round-trip is proven in e2e-backed/report.spec.ts).
const DETAIL = /\/api\/v1\/videos\/v1$/;
const ORIGINAL = /\/api\/v1\/videos\/v1\/original/;
const COMMENTS = /\/api\/v1\/videos\/v1\/comments/;
const RATING = /\/api\/v1\/videos\/v1\/rating/;
const SAVED = /\/api\/v1\/me\/saved(\?|$)/;
const PROGRESS = /\/api\/v1\/videos\/v1\/watch-progress/;
const VIDEO_REPORT = /\/api\/v1\/videos\/v1\/report$/;
const COMMENT_REPORT = /\/api\/v1\/comments\/c1\/report$/;
const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const UNREAD = /\/api\/v1\/me\/notifications\/unread-count$/;
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
    id: "u1",
    username: "ada",
    email: "ada@example.test",
    role: "user",
    email_verified: false,
    display_name: "Ada",
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

// Mocks the watch-page reads a signed-in viewer triggers (detail, player, rating,
// saved, comments). `comments` is the comment list to return.
async function mockWatch(page: Page, comments: ReturnType<typeof comment>[] = []) {
  await page.route(DETAIL, (route) => route.fulfill({ json: detail }));
  await page.route(ORIGINAL, (route) => route.abort());
  await page.route(RATING, (route) => route.fulfill({ json: NO_RATING }));
  await page.route(SAVED, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.route(PROGRESS, (route) => route.fulfill({ json: { video_id: "v1", position_seconds: 0 } }));
  await page.route(COMMENTS, (route) =>
    route.fulfill({ json: { comments, limit: 20, offset: 0 } }),
  );
}

async function signIn(page: Page) {
  await page.route(LOGIN, (route) => route.fulfill({ json: session }));
  await page.route(FEED, (route) =>
    route.fulfill({ json: { videos: [detail], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.route(UNREAD, (route) => route.fulfill({ json: { unread_count: 0 } }));
  await page.goto("/login");
  await page.getByLabel("Email").fill("ada@example.test");
  await page.getByLabel("Password").fill("supersecret");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

test("anonymous viewers are prompted to sign in to report", async ({ page }) => {
  await mockWatch(page);
  await page.goto("/videos/v1");
  await expect(page.getByRole("link", { name: "Sign in to report" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Report this video" })).toHaveCount(0);
});

test("an authenticated viewer can report a video", async ({ page }) => {
  await signIn(page);
  await mockWatch(page);
  let posted = false;
  await page.route(VIDEO_REPORT, (route) => {
    posted = true;
    return route.fulfill({ status: 204 });
  });

  // Navigate to the watch page from the home feed card (keeps the in-memory session).
  await page.getByRole("heading", { name: "Watch Me" }).click();
  await page.getByRole("button", { name: "Report this video" }).click();

  const dialog = page.getByRole("dialog", { name: "Report this video" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Reason for report").fill("This is spam");
  await dialog.getByRole("button", { name: "Submit report" }).click();

  await expect(page.getByText("your report has been sent to the moderators")).toBeVisible();
  expect(posted).toBe(true);
});

test("an authenticated viewer can report a comment", async ({ page }) => {
  await signIn(page);
  await mockWatch(page, [comment("c1", "Buy cheap stuff at example.com")]);
  let posted = false;
  await page.route(COMMENT_REPORT, (route) => {
    posted = true;
    return route.fulfill({ status: 204 });
  });

  await page.getByRole("heading", { name: "Watch Me" }).click();
  await expect(page.getByText("Buy cheap stuff at example.com")).toBeVisible();
  await page.getByRole("button", { name: "Report this comment" }).click();

  const dialog = page.getByRole("dialog", { name: "Report this comment" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Reason for report").fill("Spam link");
  await dialog.getByRole("button", { name: "Submit report" }).click();

  await expect(page.getByText("your report has been sent to the moderators")).toBeVisible();
  expect(posted).toBe(true);
});
