import { expect, test } from "@playwright/test";

import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  adminToken,
  fileVideoReport,
  reportsQueue,
  seedPublishedChannel,
} from "./fixtures";

// Proves the moderation resolve round trip against a real vidra-core + PostgreSQL:
// a viewer files a video report (seeded via the API), the deterministic admin logs
// in through the UI, sees it in the moderation queue, resolves it (accept), and a
// fresh authed refetch keeps it out of the open queue — proving the reports.status
// flip (open → accepted) persisted. DB evidence is also asserted via the admin API.
test("an admin resolves a queued report and the resolution persists", async ({ page, request }) => {
  // Seed a published video and an open report against it.
  const { videoId } = await seedPublishedChannel(request);
  const reason = await fileVideoReport(request, videoId);

  // Sanity: the report is queued as open before the admin touches it.
  const token = await adminToken(request);
  const before = (await reportsQueue(request, token)).find((r) => r.reason === reason);
  expect(before?.status).toBe("open");

  // The deterministic admin logs in through the UI.
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Open the moderation queue (client-side nav keeps the in-memory session).
  await page.getByRole("link", { name: "Moderation" }).click();
  const row = page.locator("article", { hasText: reason });
  await expect(row).toBeVisible();

  // Resolve it (accept) with an internal note.
  await row.getByLabel("Internal moderator note").fill("confirmed abuse");
  const resolved = page.waitForResponse(
    (r) => /\/admin\/reports\/[^/]+\/resolve$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await row.getByRole("button", { name: "Accept" }).click();
  await resolved;

  // It drops out of the open view immediately…
  await expect(page.locator("article", { hasText: reason })).toHaveCount(0);

  // …and stays out after a fresh refetch (navigate away + back).
  await page.getByRole("link", { name: "Home" }).click();
  await page.getByRole("link", { name: "Moderation" }).click();
  await expect(page.locator("article", { hasText: reason })).toHaveCount(0);

  // Persisted: the report's status is now "accepted" in the database (admin API read).
  const after = (await reportsQueue(request, token)).find((r) => r.reason === reason);
  expect(after?.status).toBe("accepted");
});

// A separate admin login can re-verify a rejected report flips to rejected too.
test("rejecting a report persists the rejected status", async ({ page, request }) => {
  const { videoId } = await seedPublishedChannel(request);
  const reason = await fileVideoReport(request, videoId);
  const token = await adminToken(request);

  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.getByRole("link", { name: "Moderation" }).click();
  const row = page.locator("article", { hasText: reason });
  await expect(row).toBeVisible();

  const resolved = page.waitForResponse(
    (r) => /\/admin\/reports\/[^/]+\/resolve$/.test(r.url()) && r.request().method() === "POST" && r.ok(),
  );
  await row.getByRole("button", { name: "Reject" }).click();
  await resolved;

  const after = (await reportsQueue(request, token)).find((r) => r.reason === reason);
  expect(after?.status).toBe("rejected");
});
