import { expect, test, type Page } from "@playwright/test";

const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const ME = /\/api\/v1\/auth\/me$/;

const user = {
  id: "u1",
  username: "ada",
  email: "ada@example.test",
  role: "user",
  email_verified: false,
  display_name: "",
  bio: "",
  created_at: new Date().toISOString(),
};
const session = { token: "acc", refresh_token: "ref", token_type: "Bearer", expires_in: 900, user };

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

test("editing the profile shows a saved confirmation", async ({ page }) => {
  await signIn(page);
  await page.route(ME, (route) =>
    route.fulfill({ json: { ...user, display_name: "Ada Lovelace" } }),
  );

  // Reach settings via the header (client-side nav preserves the in-memory session).
  await page.getByRole("link", { name: "ada" }).click();
  await expect(page.getByRole("heading", { name: "Account settings" })).toBeVisible();

  await page.getByLabel("Display name").fill("Ada Lovelace");
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByText("Profile saved.")).toBeVisible();
});

test("maps a 422 field error inline", async ({ page }) => {
  await signIn(page);
  await page.route(ME, (route) =>
    route.fulfill({
      status: 422,
      json: {
        error: {
          code: "unprocessable_entity",
          message: "validation failed",
          fields: [{ field: "display_name", message: "must be at most 50 characters" }],
        },
      },
    }),
  );

  await page.getByRole("link", { name: "ada" }).click();
  await page.getByLabel("Display name").fill("way too long");
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByText("must be at most 50 characters")).toBeVisible();
});

test("prompts to sign in when the session is gone", async ({ page }) => {
  // A hard load lands signed out (the session lives only in memory).
  await page.goto("/settings");
  await expect(page.getByText("Sign in to manage your account")).toBeVisible();
});
