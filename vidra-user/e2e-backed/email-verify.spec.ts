import { expect, test } from "@playwright/test";

import { devEmailToken, uniqueId } from "./fixtures";

// Proves the FULL email-verification round trip against a real vidra-core +
// PostgreSQL, using the dev mail-capture seam (DEV_MAIL_CAPTURE_ENABLED) to get
// the token the backend would otherwise only email. A freshly-signed-up
// (unverified) user resends the verification email from settings, follows the
// confirm link, and — proven by a fresh sign-in that re-reads the DB — the
// account is now verified (the "Verify your email" prompt is gone).
test("a user verifies their email end to end", async ({ page, request }) => {
  const id = uniqueId();
  const email = `e2e-verify-${id}@example.test`;
  const password = "supersecret-e2e";

  // Sign up (lands signed in, unverified).
  await page.goto("/signup");
  await page.getByLabel("Username").fill(`verify${id}`);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Settings shows the unverified prompt; resend the verification email.
  await page.getByRole("link", { name: `verify${id}` }).click();
  await expect(page.getByRole("heading", { name: "Verify your email" })).toBeVisible();
  const requested = page.waitForResponse(
    (r) => /\/auth\/verify-email$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await page.getByRole("button", { name: "Resend verification email" }).click();
  await requested;
  await expect(page.getByText("Verification email sent. Check your inbox.")).toBeVisible();

  // Retrieve the captured token and follow the confirm link.
  const token = await devEmailToken(request, email, "verification");
  expect(token).not.toBe("");
  await page.goto(`/verify-email/confirm?token=${encodeURIComponent(token)}`);
  await expect(page.getByText(/your email has been verified/i)).toBeVisible();

  // Persisted effect: a fresh sign-in re-reads the account from the DB, and the
  // "Verify your email" prompt is gone because email_verified is now true.
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await page.getByRole("link", { name: `verify${id}` }).click();
  await expect(page.getByRole("heading", { name: "Account settings" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Verify your email" })).toHaveCount(0);
});
