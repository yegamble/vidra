import { expect, test } from "@playwright/test";

import { registerUser, seedComment, seedPublishedChannel, uniqueId } from "./fixtures";

// Proves the account-mute round trip against a real vidra-core + PostgreSQL: a
// signed-in viewer mutes a commenter from the watch page, that commenter's comment
// is hidden (the backend filters it for the viewer), the muted account shows up on
// the management page, and unmuting restores the comment. Persistence is confirmed
// via the management page (a fresh API read) and the comment reappearing.
test("muting a commenter hides their comment and unmuting restores it", async ({ page, request }) => {
  // Seed a published video and a comment on it by a separate account.
  const { videoId, videoTitle } = await seedPublishedChannel(request);
  const commenter = await registerUser(request, "cmt");
  const body = `mute-me-${uniqueId()}`;
  await seedComment(request, videoId, commenter.token, body);

  // A fresh viewer signs up (the session lives in memory).
  const id = uniqueId();
  await page.goto("/signup");
  await page.getByLabel("Username").fill(`fan${id}`);
  await page.getByLabel("Email").fill(`e2e-fan-${id}@example.test`);
  await page.getByLabel("Password").fill("supersecret-e2e");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Reach the watch page from the home feed (client-side nav keeps the session).
  await page.getByRole("heading", { name: videoTitle }).click();
  await expect(page.getByRole("heading", { level: 1, name: videoTitle })).toBeVisible();
  await expect(page.getByText(body)).toBeVisible();

  // Mute the commenter from their comment → the comment disappears.
  const muted = page.waitForResponse(
    (r) => /\/me\/mutes\/accounts\/[^/]+$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await page.locator("li", { hasText: body }).getByRole("button", { name: "Mute" }).click();
  await muted;
  await expect(page.getByText(body)).toHaveCount(0);

  // The muted account appears on the management page (a fresh API read).
  await page.getByRole("link", { name: `fan${id}` }).click();
  await page.getByRole("link", { name: "Manage" }).click();
  await expect(page.getByText(`@${commenter.username}`)).toBeVisible();

  // Unmute → the account drops out of the list.
  const unmuted = page.waitForResponse(
    (r) => /\/me\/mutes\/accounts\/[^/]+$/.test(r.url()) && r.request().method() === "DELETE" && r.ok(),
  );
  await page.getByRole("button", { name: "Unmute" }).click();
  await unmuted;
  await expect(page.getByText(`@${commenter.username}`)).toHaveCount(0);
  await expect(page.getByText("No muted accounts")).toBeVisible();

  // Back on the watch page (a fresh authed refetch), the comment is visible again.
  await page.getByRole("link", { name: "Home" }).click();
  await page.getByRole("heading", { name: videoTitle }).click();
  await expect(page.getByText(body)).toBeVisible();
});
