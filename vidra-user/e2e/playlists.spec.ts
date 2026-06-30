import { expect, test, type Page } from "@playwright/test";

// Mocked playlist coverage (a real backend is not running in `npm run ci`;
// the persistence round-trip is proven in e2e-backed/playlists.spec.ts).
const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const UNREAD = /\/api\/v1\/me\/notifications\/unread-count$/;
const MY_PLAYLISTS = /\/api\/v1\/me\/playlists$/;
const CREATE = /\/api\/v1\/playlists$/;
const DETAIL = /\/api\/v1\/playlists\/p1$/;
const ADD = /\/api\/v1\/playlists\/p1\/videos$/;
const REMOVE = /\/api\/v1\/playlists\/p1\/videos\/v1$/;
// Watch-page mocks.
const VIDEO = /\/api\/v1\/videos\/v1$/;
const ORIGINAL = /\/api\/v1\/videos\/v1\/original/;
const COMMENTS = /\/api\/v1\/videos\/v1\/comments/;
const RATING = /\/api\/v1\/videos\/v1\/rating/;
const SAVED = /\/api\/v1\/me\/saved(\?|$)/;
const PROGRESS = /\/api\/v1\/videos\/v1\/watch-progress$/;

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

function playlist(id: string, title: string, count: number) {
  return {
    id,
    title,
    description: "",
    visibility: "private",
    video_count: count,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
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
  await page.route(UNREAD, (route) => route.fulfill({ json: { unread_count: 0 } }));
  await page.goto("/login");
  await page.getByLabel("Email").fill("ada@example.test");
  await page.getByLabel("Password").fill("supersecret");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

test("playlists prompt anonymous viewers to sign in", async ({ page }) => {
  await page.goto("/playlists");
  await expect(page.getByText("Sign in to see your playlists")).toBeVisible();
});

test("creating a playlist adds it to the list", async ({ page }) => {
  await signIn(page);
  await page.route(MY_PLAYLISTS, (route) => route.fulfill({ json: { playlists: [] } }));
  await page.route(CREATE, (route) => {
    if (route.request().method() === "POST") return route.fulfill({ json: playlist("p1", "My Mix", 0) });
    return route.fulfill({ json: { playlists: [] } });
  });

  await page.getByRole("link", { name: "Playlists" }).click();
  await expect(page.getByText("No playlists yet")).toBeVisible();
  await page.getByLabel("Playlist title").fill("My Mix");
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("link", { name: /My Mix/ })).toBeVisible();
});

test("the playlist detail shows videos and the owner can remove one", async ({ page }) => {
  await signIn(page);
  await page.route(MY_PLAYLISTS, (route) =>
    route.fulfill({ json: { playlists: [playlist("p1", "My Mix", 1)] } }),
  );
  await page.route(DETAIL, (route) =>
    route.fulfill({ json: { ...playlist("p1", "My Mix", 1), videos: [video("v1", "Clip")] } }),
  );
  await page.route(REMOVE, (route) => route.fulfill({ status: 204, body: "" }));

  await page.getByRole("link", { name: "Playlists" }).click();
  await page.getByRole("link", { name: /My Mix/ }).click();
  await expect(page.getByRole("heading", { name: "My Mix" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Clip" })).toBeVisible();
  await page.getByRole("button", { name: "Remove Clip from playlist" }).click();
  await expect(page.getByRole("heading", { name: "Clip" })).toBeHidden();
});

test("the owner can delete a playlist", async ({ page }) => {
  await signIn(page);
  await page.route(MY_PLAYLISTS, (route) =>
    route.fulfill({ json: { playlists: [playlist("p1", "My Mix", 0)] } }),
  );
  await page.route(DETAIL, (route) => {
    if (route.request().method() === "DELETE") return route.fulfill({ status: 204, body: "" });
    return route.fulfill({ json: { ...playlist("p1", "My Mix", 0), videos: [] } });
  });

  // Reach the detail page via client-side nav so the in-memory session survives.
  await page.getByRole("link", { name: "Playlists" }).click();
  await page.getByRole("link", { name: /My Mix/ }).click();
  await page.getByRole("button", { name: "Delete playlist" }).click();
  await expect(page).toHaveURL(/\/playlists$/);
});

test("a signed-in viewer can add a video to a playlist from the watch page", async ({ page }) => {
  await signIn(page);
  await page.route(VIDEO, (route) => route.fulfill({ json: detail }));
  await page.route(ORIGINAL, (route) => route.abort());
  await page.route(COMMENTS, (route) => route.fulfill({ json: { comments: [], limit: 20, offset: 0 } }));
  await page.route(RATING, (route) =>
    route.fulfill({ json: { like_count: 0, dislike_count: 0, my_rating: null } }),
  );
  await page.route(SAVED, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.route(PROGRESS, (route) => {
    if (route.request().method() === "PUT") return route.fulfill({ status: 204, body: "" });
    return route.fulfill({ json: { video_id: "v1", position_seconds: 0 } });
  });
  await page.route(MY_PLAYLISTS, (route) =>
    route.fulfill({ json: { playlists: [playlist("p1", "My Mix", 0)] } }),
  );
  await page.route(ADD, (route) => route.fulfill({ status: 204, body: "" }));

  await page.getByRole("heading", { name: "Watch Me" }).click();
  await page.getByRole("button", { name: "Save to playlist" }).click();
  const addBtn = page.getByRole("button", { name: "My Mix" });
  await expect(addBtn).toBeVisible();
  await addBtn.click();
  await expect(addBtn).toHaveAttribute("aria-pressed", "true");
});
