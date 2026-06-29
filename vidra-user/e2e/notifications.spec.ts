import { expect, test, type Page } from "@playwright/test";

// Mocked notifications coverage (a real backend is not running in `npm run ci`;
// the persistence round-trip is proven in e2e-backed/notifications.spec.ts).
const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const LIST = /\/api\/v1\/me\/notifications(\?|$)/;
const UNREAD = /\/api\/v1\/me\/notifications\/unread-count$/;
const READ_ALL = /\/api\/v1\/me\/notifications\/read-all$/;
const READ_ONE = /\/api\/v1\/me\/notifications\/[^/]+\/read$/;

function followNotif(id: string, read: boolean) {
  return {
    id,
    type: "follow",
    read,
    created_at: new Date().toISOString(),
    actor: { username: "bob", display_name: "Bob" },
    channel_handle: "ada",
    channel_display_name: "Ada Makes",
  };
}

function commentNotif(id: string, read: boolean) {
  return {
    id,
    type: "comment",
    read,
    created_at: new Date().toISOString(),
    actor: { username: "cara", display_name: "Cara" },
    video_id: "v1",
    video_title: "My clip",
  };
}

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

async function signIn(page: Page, unread = 0) {
  await page.route(LOGIN, (route) => route.fulfill({ json: session }));
  await page.route(FEED, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.route(UNREAD, (route) => route.fulfill({ json: { unread_count: unread } }));
  await page.goto("/login");
  await page.getByLabel("Email").fill("ada@example.test");
  await page.getByLabel("Password").fill("supersecret");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

test("notifications prompt anonymous viewers to sign in", async ({ page }) => {
  await page.goto("/notifications");
  await expect(page.getByText("Sign in to see your notifications")).toBeVisible();
});

test("the header bell shows an unread badge and opens the list", async ({ page }) => {
  await signIn(page, 2);
  // Bell badge reflects the unread count.
  const bell = page.getByRole("link", { name: "Notifications (2 unread)" });
  await expect(bell).toBeVisible();

  await page.route(LIST, (route) =>
    route.fulfill({
      json: {
        notifications: [followNotif("n1", false), commentNotif("n2", false)],
        unread_count: 2,
        limit: 20,
        offset: 0,
      },
    }),
  );
  await bell.click();
  await expect(page.getByText("Bob started following Ada Makes")).toBeVisible();
  await expect(page.getByText("Cara commented on My clip")).toBeVisible();
});

test("marking one notification read removes its unread control", async ({ page }) => {
  await signIn(page, 2);
  await page.route(LIST, (route) =>
    route.fulfill({
      json: {
        notifications: [followNotif("n1", false), commentNotif("n2", false)],
        unread_count: 2,
        limit: 20,
        offset: 0,
      },
    }),
  );
  await page.route(READ_ONE, (route) => route.fulfill({ status: 204, body: "" }));

  await page.getByRole("link", { name: /Notifications/ }).click();
  const markButtons = page.getByRole("button", { name: "Mark as read" });
  await expect(markButtons).toHaveCount(2);
  await markButtons.first().click();
  await expect(page.getByRole("button", { name: "Mark as read" })).toHaveCount(1);
});

test("mark all as read clears the unread controls", async ({ page }) => {
  await signIn(page, 2);
  await page.route(LIST, (route) =>
    route.fulfill({
      json: {
        notifications: [followNotif("n1", false), commentNotif("n2", false)],
        unread_count: 2,
        limit: 20,
        offset: 0,
      },
    }),
  );
  await page.route(READ_ALL, (route) => route.fulfill({ status: 204, body: "" }));

  await page.getByRole("link", { name: /Notifications/ }).click();
  await expect(page.getByRole("button", { name: "Mark as read" })).toHaveCount(2);
  await page.getByRole("button", { name: "Mark all as read" }).click();
  await expect(page.getByRole("button", { name: "Mark as read" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Mark all as read" })).toBeDisabled();
});

test("the notifications list shows an empty state", async ({ page }) => {
  await signIn(page, 0);
  await page.route(LIST, (route) =>
    route.fulfill({ json: { notifications: [], unread_count: 0, limit: 20, offset: 0 } }),
  );
  await page.getByRole("link", { name: /Notifications/ }).click();
  await expect(page.getByText("No notifications yet")).toBeVisible();
});
