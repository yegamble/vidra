import { expect, test } from "@playwright/test";

import { registerUser } from "./fixtures";

// Proves the password-reset REQUEST round trip against a real vidra-core +
// PostgreSQL: the reset page drives a real POST that the backend accepts with 202
// and the UI shows the neutral (enumeration-safe) confirmation.
//
// The 202 is returned regardless of whether the email exists, so it alone does not
// prove a token row was created. The token-row creation for a KNOWN account is
// confirmed out-of-band via psql in the Ralph loop: when RESET_EMAIL is set the
// request targets that pre-registered account so the psql check is deterministic;
// otherwise (CI) a fresh account is registered and only the UI round trip is proven.
test("a visitor requests a password reset", async ({ page, request }) => {
  const email = process.env.RESET_EMAIL ?? (await registerUser(request, "reset")).email;

  await page.goto("/reset-password");
  await page.getByLabel("Email").fill(email);
  const accepted = page.waitForResponse(
    (r) => /\/auth\/password-reset$/.test(r.url()) && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Send reset link" }).click();
  expect((await accepted).status()).toBe(202);

  await expect(page.getByText(/check your inbox/i)).toBeVisible();
  await expect(page.getByLabel("Email")).toHaveCount(0);
});
