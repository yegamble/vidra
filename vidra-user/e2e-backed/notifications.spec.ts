import { expect, test } from "@playwright/test";

import { API_URL, uniqueId } from "./fixtures";

// Proves the notifications round trip against a real vidra-core + PostgreSQL: a
// fan follows a channel (creating a notification for the owner), the owner logs
// in through the UI and sees it with an unread badge, then marks it read — and a
// fresh authed refetch keeps it read (the read persisted). DB evidence (the
// notifications.read_at flip) is captured separately via psql.
test("a follow notifies the channel owner, who can read and clear it", async ({ page, request }) => {
  const id = uniqueId();
  const ownerEmail = `e2e-owner-${id}@example.test`;
  const password = "supersecret-e2e";
  const handle = `ch${id}`;
  const channelName = `Channel ${id}`;

  // Owner registers + creates a channel via the API (so we can log in as them).
  const reg = await request.post(`${API_URL}/api/v1/auth/register`, {
    data: { username: `owner${id}`, email: ownerEmail, password },
  });
  const ownerToken = ((await reg.json()) as { token: string }).token;
  await request.post(`${API_URL}/api/v1/channels`, {
    headers: { Authorization: `Bearer ${ownerToken}` },
    data: { handle, display_name: channelName },
  });

  // A fan registers and follows the channel → creates a notification for the owner.
  const fanReg = await request.post(`${API_URL}/api/v1/auth/register`, {
    data: { username: `fan${id}`, email: `e2e-fan-${id}@example.test`, password },
  });
  const fanToken = ((await fanReg.json()) as { token: string }).token;
  await request.post(`${API_URL}/api/v1/channels/${handle}/follow`, {
    headers: { Authorization: `Bearer ${fanToken}` },
  });

  // The owner logs in through the UI.
  await page.goto("/login");
  await page.getByLabel("Email").fill(ownerEmail);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // The header bell reflects the unread notification.
  await expect(page.getByRole("link", { name: "Notifications (1 unread)" })).toBeVisible();

  // Open the list (client-side nav) → the follow notification is shown.
  await page.getByRole("link", { name: /Notifications/ }).click();
  const message = page.getByText(new RegExp(`started following ${channelName}`));
  await expect(message).toBeVisible();

  // Mark it read; the read persists across a fresh refetch (navigate away + back).
  const read = page.waitForResponse(
    (r) => /\/me\/notifications\/[^/]+\/read$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await page.getByRole("button", { name: "Mark as read" }).click();
  await read;

  await page.getByRole("link", { name: "Home" }).click();
  await page.getByRole("link", { name: /Notifications/ }).click();
  await expect(page.getByText(new RegExp(`started following ${channelName}`))).toBeVisible();
  await expect(page.getByRole("button", { name: "Mark as read" })).toHaveCount(0);
});
