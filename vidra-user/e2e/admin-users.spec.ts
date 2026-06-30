import { expect, test, type Page } from "@playwright/test";

// Mocked admin users coverage (a real backend is not running in `npm run ci`; the
// persistence round-trip is proven in e2e-backed/admin-users.spec.ts).
const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const UNREAD = /\/api\/v1\/me\/notifications\/unread-count$/;
const USERS = /\/api\/v1\/admin\/users(\?|$)/;
const UPDATE = /\/api\/v1\/admin\/users\/[^/]+$/;

type Role = "user" | "moderator" | "admin";

function session(role: Role) {
  return {
    token: "acc",
    refresh_token: "ref",
    token_type: "Bearer",
    expires_in: 900,
    user: {
      id: "u1",
      username: "boss",
      email: "boss@example.test",
      role,
      email_verified: true,
      display_name: "Boss",
      bio: "",
      created_at: new Date().toISOString(),
    },
  };
}

function adminUser(
  id: string,
  username: string,
  role: Role,
  is_active = true,
  email_verified = true,
) {
  return {
    id,
    username,
    email: `${username}@example.test`,
    role,
    is_active,
    email_verified,
    display_name: username,
    created_at: new Date().toISOString(),
  };
}

async function signIn(page: Page, role: Role) {
  await page.route(LOGIN, (route) => route.fulfill({ json: session(role) }));
  await page.route(FEED, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.route(UNREAD, (route) => route.fulfill({ json: { unread_count: 0 } }));
  await page.goto("/login");
  await page.getByLabel("Email").fill("boss@example.test");
  await page.getByLabel("Password").fill("supersecret");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

test("anonymous viewers are gated out of admin users", async ({ page }) => {
  let fetched = false;
  await page.route(USERS, (route) => {
    fetched = true;
    return route.fulfill({ json: { users: [], limit: 20, offset: 0 } });
  });
  await page.goto("/admin/users");
  await expect(page.getByText("Administrators only")).toBeVisible();
  expect(fetched).toBe(false);
});

test("moderators see Moderation but not the Admin nav entry", async ({ page }) => {
  await signIn(page, "moderator");
  await expect(page.getByRole("link", { name: "Moderation" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Admin", exact: true })).toHaveCount(0);
});

test("an admin sees the users list with a self badge", async ({ page }) => {
  await signIn(page, "admin");
  await page.route(USERS, (route) =>
    route.fulfill({
      json: {
        users: [
          adminUser("u1", "boss", "admin"),
          adminUser("u2", "alice", "user"),
          adminUser("u3", "bob", "moderator"),
        ],
        limit: 100,
        offset: 0,
      },
    }),
  );

  await page.getByRole("link", { name: "Admin", exact: true }).click();
  await expect(page.getByText("alice@example.test")).toBeVisible();
  await expect(page.getByText("bob@example.test")).toBeVisible();
  await expect(page.getByText("you", { exact: true })).toBeVisible();
  // The admin's own row controls are disabled (backend forbids self-demote/deactivate).
  await expect(page.getByLabel("Role for boss")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Deactivate boss" })).toBeDisabled();
});

test("the search box filters by query", async ({ page }) => {
  await signIn(page, "admin");
  await page.route(USERS, (route) => {
    const filtered = route.request().url().includes("q=alice");
    const users = filtered
      ? [adminUser("u2", "alice", "user")]
      : [adminUser("u1", "boss", "admin"), adminUser("u2", "alice", "user")];
    return route.fulfill({ json: { users, limit: 100, offset: 0 } });
  });

  await page.getByRole("link", { name: "Admin", exact: true }).click();
  await expect(page.getByText("alice@example.test")).toBeVisible();

  const searched = page.waitForResponse((r) => USERS.test(r.url()) && r.url().includes("q=alice"));
  await page.getByRole("searchbox", { name: "Search users" }).fill("alice");
  await page.getByRole("button", { name: "Search" }).click();
  await searched;
  await expect(page.getByText("boss@example.test")).toHaveCount(0);
  await expect(page.getByText("alice@example.test")).toBeVisible();
});

test("an admin can change a user's role", async ({ page }) => {
  await signIn(page, "admin");
  await page.route(USERS, (route) =>
    route.fulfill({
      json: { users: [adminUser("u1", "boss", "admin"), adminUser("u2", "alice", "user")], limit: 100, offset: 0 },
    }),
  );
  await page.route(UPDATE, (route) =>
    route.fulfill({ json: adminUser("u2", "alice", "moderator") }),
  );

  await page.getByRole("link", { name: "Admin", exact: true }).click();
  const updated = page.waitForResponse(
    (r) => UPDATE.test(r.url()) && r.request().method() === "PATCH" && r.ok(),
  );
  await page.getByLabel("Role for alice").selectOption("moderator");
  await updated;
  await expect(page.getByLabel("Role for alice")).toHaveValue("moderator");
});

test("an admin can deactivate a user", async ({ page }) => {
  await signIn(page, "admin");
  await page.route(USERS, (route) =>
    route.fulfill({
      json: { users: [adminUser("u1", "boss", "admin"), adminUser("u2", "alice", "user")], limit: 100, offset: 0 },
    }),
  );
  await page.route(UPDATE, (route) =>
    route.fulfill({ json: adminUser("u2", "alice", "user", false) }),
  );

  await page.getByRole("link", { name: "Admin", exact: true }).click();
  const updated = page.waitForResponse(
    (r) => UPDATE.test(r.url()) && r.request().method() === "PATCH" && r.ok(),
  );
  await page.getByRole("button", { name: "Deactivate alice" }).click();
  await updated;
  await expect(page.getByRole("button", { name: "Reactivate alice" })).toBeVisible();
});
