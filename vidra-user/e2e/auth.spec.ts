import { expect, test } from "@playwright/test";

const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;

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

test("signing in shows the account in the header", async ({ page }) => {
  await page.route(LOGIN, (route) => route.fulfill({ json: session }));
  // The post-login redirect lands on home, which loads the feed.
  await page.route(FEED, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );

  await page.goto("/login");
  await page.getByLabel("Email").fill("ada@example.test");
  await page.getByLabel("Password").fill("supersecret");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await expect(page.getByText("ada")).toBeVisible();
});

test("shows an error on bad credentials", async ({ page }) => {
  await page.route(LOGIN, (route) =>
    route.fulfill({
      status: 401,
      json: { error: { code: "unauthorized", message: "invalid credentials" } },
    }),
  );

  await page.goto("/login");
  await page.getByLabel("Email").fill("ada@example.test");
  await page.getByLabel("Password").fill("wrong");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByText("Invalid email or password.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);
});

const RESET = /\/api\/v1\/auth\/password-reset$/;

test("the login page links to the password-reset page", async ({ page }) => {
  await page.route(FEED, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.goto("/login");
  await page.getByRole("link", { name: "Forgot your password?" }).click();
  await expect(page).toHaveURL(/\/reset-password$/);
  await expect(page.getByRole("heading", { name: "Reset your password" })).toBeVisible();
});

test("requesting a password reset shows a neutral confirmation", async ({ page }) => {
  let body: unknown;
  await page.route(RESET, async (route) => {
    body = route.request().postDataJSON();
    await route.fulfill({ status: 202, body: "" });
  });

  await page.goto("/reset-password");
  await page.getByLabel("Email").fill("ada@example.test");
  await page.getByRole("button", { name: "Send reset link" }).click();

  await expect(page.getByText(/check your inbox/i)).toBeVisible();
  expect(body).toEqual({ email: "ada@example.test" });
  // The email field is gone once the neutral confirmation replaces the form.
  await expect(page.getByLabel("Email")).toHaveCount(0);
});

test("shows an error when the reset email is rejected", async ({ page }) => {
  await page.route(RESET, (route) =>
    route.fulfill({
      status: 422,
      json: { error: { code: "unprocessable_entity", message: "validation failed" } },
    }),
  );

  await page.goto("/reset-password");
  await page.getByLabel("Email").fill("not-an-email");
  await page.getByRole("button", { name: "Send reset link" }).click();

  await expect(page.getByText("Enter a valid email address.")).toBeVisible();
  await expect(page.getByText(/check your inbox/i)).toHaveCount(0);
});

const INSTANCE = /\/api\/v1\/instance$/;
const REGISTER = /\/api\/v1\/auth\/register$/;

function instanceJson(registrationEnabled: boolean) {
  return {
    name: "Vidra",
    description: "",
    software: { name: "vidra", version: "0.1.0" },
    registration_enabled: registrationEnabled,
    terms_url: "",
    privacy_url: "",
    contact_email: "",
  };
}

test("signing up shows the account in the header", async ({ page }) => {
  await page.route(INSTANCE, (route) => route.fulfill({ json: instanceJson(true) }));
  await page.route(REGISTER, (route) => route.fulfill({ json: session }));
  await page.route(FEED, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );

  await page.goto("/signup");
  await page.getByLabel("Username").fill("ada");
  await page.getByLabel("Email").fill("ada@example.test");
  await page.getByLabel("Password").fill("supersecret");
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
});

test("maps 422 field errors inline", async ({ page }) => {
  await page.route(INSTANCE, (route) => route.fulfill({ json: instanceJson(true) }));
  await page.route(REGISTER, (route) =>
    route.fulfill({
      status: 422,
      json: {
        error: {
          code: "unprocessable_entity",
          message: "validation failed",
          fields: [{ field: "password", message: "must be at least 8 characters" }],
        },
      },
    }),
  );

  await page.goto("/signup");
  await page.getByLabel("Username").fill("ada");
  await page.getByLabel("Email").fill("ada@example.test");
  await page.getByLabel("Password").fill("short");
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page.getByText("must be at least 8 characters")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);
});

test("shows the registration-closed notice when disabled", async ({ page }) => {
  await page.route(INSTANCE, (route) => route.fulfill({ json: instanceJson(false) }));
  await page.goto("/signup");
  await expect(page.getByText("Registration is closed")).toBeVisible();
  await expect(page.getByRole("button", { name: "Create account" })).toHaveCount(0);
});
