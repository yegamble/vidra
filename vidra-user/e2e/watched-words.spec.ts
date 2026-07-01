import { expect, test, type Page } from "@playwright/test";

// Mocked watched-words coverage (a real backend is not running in `npm run ci`;
// the persistence round-trip is proven in e2e-backed/watched-words.spec.ts).
const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const UNREAD = /\/api\/v1\/me\/notifications\/unread-count$/;
const REPORTS = /\/api\/v1\/admin\/reports(\?|$)/;
const WATCHED_WORDS = /\/api\/v1\/admin\/watched-words(\?|$)/;
const DELETE_WORD = /\/api\/v1\/admin\/watched-words\/[^/]+$/;

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

function watchedWord(id: string, word: string, adder = "ada") {
  return { id, word, created_by_username: adder, created_at: new Date().toISOString() };
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

test("anonymous viewers are gated out of the watched-words list", async ({ page }) => {
  let fetched = false;
  await page.route(WATCHED_WORDS, (route) => {
    fetched = true;
    return route.fulfill({ json: { words: [], limit: 20, offset: 0 } });
  });
  await page.goto("/moderation/watched-words");
  await expect(page.getByText("Moderators only")).toBeVisible();
  expect(fetched).toBe(false);
});

test("an admin adds and removes watched words", async ({ page }) => {
  await signIn(page, "admin");
  await page.route(WATCHED_WORDS, (route) => {
    if (route.request().method() === "POST") {
      const word = (route.request().postDataJSON() as { word: string }).word;
      if (word === "abuse") {
        return route.fulfill({
          status: 409,
          json: { error: { code: "conflict", message: "watched word already exists" } },
        });
      }
      return route.fulfill({ status: 201, json: watchedWord("w-new", word) });
    }
    return route.fulfill({ json: { words: [watchedWord("w1", "existing")], limit: 100, offset: 0 } });
  });
  await page.route(DELETE_WORD, (route) =>
    route.request().method() === "DELETE" ? route.fulfill({ status: 204, body: "" }) : route.continue(),
  );

  // Moderation → Watched words (client-side nav keeps the in-memory session).
  await page.getByRole("link", { name: "Moderation" }).click();
  await page.getByRole("link", { name: "Watched words" }).click();
  await expect(page.getByText("existing")).toBeVisible();

  // Add a new term → it prepends to the list.
  const added = page.waitForResponse(
    (r) => WATCHED_WORDS.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await page.getByLabel("Add a watched word").fill("spam");
  await page.getByRole("button", { name: "Add" }).click();
  await added;
  await expect(page.getByText("spam")).toBeVisible();

  // A duplicate term surfaces the conflict message.
  await page.getByLabel("Add a watched word").fill("abuse");
  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.getByText("That word is already on the list.")).toBeVisible();

  // Remove the pre-existing term → its row drops.
  const removed = page.waitForResponse(
    (r) => DELETE_WORD.test(r.url()) && r.request().method() === "DELETE" && r.ok(),
  );
  await page.getByRole("button", { name: "Remove existing" }).click();
  await removed;
  await expect(page.getByText("existing")).toHaveCount(0);
});
