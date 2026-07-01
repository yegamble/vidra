import { expect, test } from "@playwright/test";

import { API_URL, devEmailToken, registerUser } from "./fixtures";

// Proves the FULL password-reset round trip against a real vidra-core +
// PostgreSQL. It uses the dev mail-capture seam (DEV_MAIL_CAPTURE_ENABLED) to
// retrieve the single-use token the backend would otherwise only email: a user
// resets to a new password on the confirm page, then the new password logs in and
// the old one is refused — proving the password actually changed in the database.
test("a user completes a password reset and signs in with the new password", async ({
  page,
  request,
}) => {
  const { email } = await registerUser(request, "resetc");
  const oldPassword = "supersecret-e2e"; // registerUser seeds this password
  const newPassword = "brand-new-pw-9";

  // Start the reset flow, then pull the token from the dev capture endpoint.
  const requested = await request.post(`${API_URL}/api/v1/auth/password-reset`, {
    data: { email },
  });
  expect(requested.status()).toBe(202);
  const token = await devEmailToken(request, email, "reset");
  expect(token).not.toBe("");

  // Complete the reset on the confirm page (as the email link would land).
  await page.goto(`/reset-password/confirm?token=${encodeURIComponent(token)}`);
  await page.getByLabel("New password", { exact: true }).fill(newPassword);
  await page.getByLabel("Confirm new password", { exact: true }).fill(newPassword);
  const confirmed = page.waitForResponse(
    (r) => /\/auth\/password-reset\/confirm$/.test(r.url()) && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Reset password" }).click();
  expect((await confirmed).status()).toBe(204);
  await expect(page.getByText(/your password has been reset/i)).toBeVisible();

  // Persisted effect: the new password logs in; the old one is refused.
  const withNew = await request.post(`${API_URL}/api/v1/auth/login`, {
    data: { email, password: newPassword },
  });
  expect(withNew.status()).toBe(200);
  const withOld = await request.post(`${API_URL}/api/v1/auth/login`, {
    data: { email, password: oldPassword },
  });
  expect(withOld.status()).toBe(401);
});
